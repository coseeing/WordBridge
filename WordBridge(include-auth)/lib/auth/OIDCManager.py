from concurrent.futures import Future, TimeoutError
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from threading import Lock
from typing import Optional, Callable, Any
import time
import urllib.parse
import webbrowser

import jwt
from authlib.common.security import generate_token  # for PKCE code_verifier
from authlib.integrations.requests_client import OAuth2Session
from authlib.oauth2.rfc6749.errors import OAuth2Error, InvalidGrantError
import requests
from requests import exceptions as req_exc

from .utils import run_in_thread
from .Verifier import TokenVerifier, ScopeError


class _AuthHandler(BaseHTTPRequestHandler):
	"""
	Injected via partial:
	- login_path: str
	- logout_path: Optional[str]
	- future: Future
	"""
	def __init__(self, *args, login_path: Optional[str], logout_path: Optional[str], future: Future, **kwargs):
		self._login_path = login_path
		self._logout_path = logout_path
		self._future = future
		super().__init__(*args, **kwargs)

	def do_GET(self):
		parsed = urllib.parse.urlparse(self.path)
		qs = urllib.parse.parse_qs(parsed.query)
		state = (qs.get("state") or [None])[0]
		code  = (qs.get("code")  or [None])[0]
		err   = (qs.get("error") or [None])[0]
		err_desc = (qs.get("error_description") or [None])[0]
		err_uri  = (qs.get("error_uri") or [None])[0]

		def _finish(kind: str, body: bytes, logout_seen: bool = False):
			self.send_response(200)
			self.send_header("Content-Type", "text/plain; charset=utf-8")
			self.end_headers()
			self.wfile.write(body)

			if self._future is not None and not self._future.done():
				try:
					self._future.set_result({
						"kind": kind,			# "login" / "logout"
						"path": parsed.path,
						"state": state,
						"code": code,			# usually None for logout
						"logout_seen": logout_seen,
						"error": err,
						"error_description": err_desc,
						"error_uri": err_uri,
					})
				except Exception:
					pass

		if self._login_path and parsed.path == self._login_path:
			if err:
				body = f"Login failed: {err} {err_desc or ''}".encode("utf-8")
			else:
				body = b"Login success. You can close this tab."
			_finish("login", body)
		elif self._logout_path and parsed.path == self._logout_path:
			if err:
				body = f"Logout failed: {err} {err_desc or ''}".encode("utf-8")
				_finish("logout", body, logout_seen=False)
			else:
				_finish("logout", b"Logout success. You can close this tab.", logout_seen=True)
		else:
			self.send_response(404); self.end_headers()

	def log_message(self, *_):
		return


class LoginError(Exception):
	pass


class LogoutError(Exception):
	pass


class AccessTokenError(Exception):
	pass


class Manager:
	def __init__(
		self,
		issuer: str,
		client_id: str,
		scopes: str,
		login_redirect_uri: str,
		logout_redirect_uri: Optional[str],
		callback_timeout: int = 180,
		verify_access_token_jwt: bool = True,
		client_secret: Optional[str] = None,
	):
		# 1) OIDC discovery (sync; safe in __init__)
		wk = requests.get(f"{issuer}/.well-known/openid-configuration", timeout=20).json()
		self.AUTH_URL = wk["authorization_endpoint"]
		self.TOKEN_URL = wk["token_endpoint"]
		self.LOGOUT_URL = wk.get("end_session_endpoint")
		self.JWKS_URI = wk.get("jwks_uri")

		# Basic settings
		self.ISSUER = issuer
		self.CLIENT_ID = client_id
		self.SCOPES = scopes
		self.LOGIN_REDIRECT_URI = login_redirect_uri
		self.LOGOUT_REDIRECT_URI = logout_redirect_uri
		self.CALLBACK_TIMEOUT = int(callback_timeout)
		# Whether to verify access_token as JWT (some providers like Google issue opaque ATs)
		self._verify_access_token_jwt = bool(verify_access_token_jwt)

		# 2) OAuth session (PKCE)
		kwargs = {
			"client_id": client_id,
			"scope": scopes,
			"redirect_uri": login_redirect_uri,
			"code_challenge_method": "S256",
		}
		if self.ISSUER.rstrip("/") == "https://accounts.google.com":
			kwargs["client_secret"] = client_secret
			kwargs["token_endpoint_auth_method"] = "client_secret_post"

		self.session = OAuth2Session(**kwargs)

		# Token state
		self._token: dict = {}
		self._token_lock = Lock()

		# Flow mutex (avoid concurrent auth flows)
		self._flow_lock = Lock()
		self._flow_in_progress = False
		self._shared_flow_future: Optional[Future] = None
		self._shared_flow_kind: Optional[str] = None  # "login" | "logout"

		# One-shot callback server control
		self._cb_thread: Optional[threading.Thread] = None
		self._cb_guard = Lock()
		self._cb_future: Optional[Future] = None
		self._cb_port: Optional[int] = None
		self._cb_host: str = "127.0.0.1"

		# Injectables
		self._browser_open: Callable[[str], Any] = webbrowser.open
		self._logger: Any = None  # logging.Logger-like or callable(level, message)
		# Allow init-time injection via kwargs-like after construction by setter methods

		# Verifier for ID Token and potential reuse elsewhere
		self._verifier = TokenVerifier(
			issuer=self.ISSUER,
			client_id=self.CLIENT_ID,
			jwt_algorithms=["RS256","RS384","RS512","ES256","ES384","ES512","PS256","PS384","PS512"],
		)

	# --------- Flow mutex ----------
	def _begin_flow(self) -> bool:
		with self._flow_lock:
			if self._flow_in_progress:
				return False
			self._flow_in_progress = True
			return True

	def _end_flow(self):
		with self._flow_lock:
			self._flow_in_progress = False

	def abort_pending_flow(self, reason: str = "aborted by UI"):
		"""
		Hard-cancel the current auth flow:
		- stop the one-shot HTTP callback server (signal exception to the waiting future)
		- mark the flow as ended
		This lets a new login/logout start cleanly.
		"""
		self._stop_callback_server()
		self._end_flow()

	@property
	def flow_in_progress(self) -> bool:
		with self._flow_lock:
			return self._flow_in_progress

	# --------- helpers ---------
	@staticmethod
	def _mask_token(t: dict) -> dict:
		m = dict(t)
		for k in ("access_token", "refresh_token", "id_token"):
			if k in m and isinstance(m[k], str):
				v = m[k]
				m[k] = (v[:6] + "..." + v[-6:]) if len(v) > 12 else "***"
		return m

	def _run_once_server_loop(self, done_future: Future, bind_port: int, login_path: Optional[str], logout_path: Optional[str]):
		"""One-shot callback server: handle a single callback; end when the future completes.
		Bind to the specific port of the active redirect URI (login/logout).
		"""

		class _OnceServer(HTTPServer):
			allow_reuse_address = True

		Handler = partial(_AuthHandler, login_path=login_path, logout_path=logout_path, future=done_future)
		srv = _OnceServer((self._cb_host, bind_port), Handler)
		srv.timeout = 0.5

		try:
			while not (done_future and done_future.done()):
				srv.handle_request()
		finally:
			srv.server_close()

	def _start_callback_server(self, kind: str) -> Future:
		"""
		Start a one-shot blocking HTTPServer (in a thread) and return a Future for awaiting.
		The bind port is derived from the corresponding redirect URI for the flow kind.
		"""
		with self._cb_guard:
			# If an old thread exists, end it first
			if self._cb_thread and self._cb_thread.is_alive():
				if self._cb_future is not None and not self._cb_future.done():
					try:
						self._cb_future.set_exception(RuntimeError("callback server superseded"))
					except Exception:
						pass
				self._cb_thread.join(timeout=1.0)

			fut = Future()
			self._cb_future = fut

			# Determine bind port and paths based on kind
			if kind == "login":
				parsed = urllib.parse.urlparse(self.LOGIN_REDIRECT_URI)
				bind_port = int(parsed.port or 8765)
				login_path = parsed.path
				logout_path = None
			elif kind == "logout":
				parsed = urllib.parse.urlparse(self.LOGOUT_REDIRECT_URI or "")
				bind_port = int(parsed.port or 8765)
				login_path = None
				logout_path = parsed.path if parsed.path else None
			else:
				raise ValueError(f"unknown callback kind: {kind}")

			self._cb_port = bind_port

			self._cb_thread = threading.Thread(
				target=self._run_once_server_loop,
				args=(fut, bind_port, login_path, logout_path),
				daemon=True,
			)
			self._cb_thread.start()

		return fut

	def _stop_callback_server(self):
		with self._cb_guard:
			if self._cb_future is not None and not self._cb_future.done():
				try:
					self._cb_future.set_exception(RuntimeError("callback server stopped"))
				except Exception:
					pass

			# Send a wake-up request to quickly unblock handle_request
			if self._cb_port is not None:
				try:
					requests.get(f"http://{self._cb_host}:{self._cb_port}/__stop__", timeout=0.2)
				except Exception:
					pass

			if self._cb_thread and self._cb_thread.is_alive():
				self._cb_thread.join(timeout=1.0)

			self._cb_thread = None
			self._cb_future = None
			self._cb_port = None

	# --------- Logger / Browser injection ---------
	def set_logger(self, logger: Any):
		self._logger = logger

	def set_browser_open(self, browser_open: Callable[[str], Any]):
		self._browser_open = browser_open or webbrowser.open

	def _log(self, level: str, message: str):
		logger = self._logger
		if not logger:
			return
		try:
			# logging.Logger-like
			method = getattr(logger, level, None)
			if callable(method):
				method(message); return
			# callable(level, msg)
			if callable(logger):
				logger(level, message)
		except Exception:
			pass

	# --------- Public API

	def login_async(self) -> Future:
		"""
		Start the login flow in a background thread; return a Future:
		  success -> result is a payload dict
		  failure -> exception is LoginError
		"""
		def _worker():
			code_verifier = generate_token(48)
			nonce = generate_token(24)
			try:
				extra = {}
				if self.ISSUER.rstrip("/") == "https://accounts.google.com":
					extra.update({"access_type": "offline", "prompt": "consent"})

				url, state = self.session.create_authorization_url(
					self.AUTH_URL,
					code_challenge_method="S256",
					code_verifier=code_verifier,
					nonce=nonce,
					**extra,
				)
			except Exception as e:
				raise LoginError(f"create_authorization_url error: {e}") from e

			self._log("info", "starting login callback server")
			fut_cb = self._start_callback_server("login")

			# Open browser (sync is OK; we're in a worker thread)
			try:
				self._log("info", "opening authorization URL in browser")
				self._browser_open(url)
			except Exception as e:
				self._stop_callback_server()
				raise LoginError(f"Failed to open authorization URL: {e}") from e

			# Wait for callback (Future.result with timeout)
			try:
				result = fut_cb.result(timeout=self.CALLBACK_TIMEOUT)
			except TimeoutError:
				self._stop_callback_server()
				self._log("error", "OAuth login callback timed out")
				raise LoginError("Waiting for OAuth callback timed out")
			except Exception as e:
				self._stop_callback_server()
				raise LoginError(str(e)) from e
			else:
				self._stop_callback_server()

			# Validate callback
			if result.get("kind") != "login":
				self._log("error", "unexpected callback kind during login")
				raise LoginError("Unexpected callback kind (expect login)")
			if result.get("state") != state:
				self._log("error", "authorization response state mismatch")
				raise LoginError("state mismatch")
			if result.get("error"):
				desc = result.get("error_description")
				uri = result.get("error_uri")
				extra = f"; {desc}" if desc else ""
				extra += f"; see {uri}" if uri else ""
				raise LoginError(f"authorization error: {result.get('error')}{extra}")

			code = result.get("code")
			if not code:
				raise LoginError("Missing authorization code in callback")

			# Exchange code for tokens (requests is sync; we're already in a worker thread)
			try:
				t = self.session.fetch_token(
					self.TOKEN_URL,
					code=code,
					code_verifier=code_verifier,
					include_client_id=True,
				)
			except Exception as e:
				self._log("error", f"token exchange failed: {e}")
				raise LoginError(f"fetch_token error: {e}") from e

			# Validate ID Token using JWKS and nonce
			idt = t.get("id_token")
			if not idt:
				raise LoginError("id_token missing in token response; ensure 'openid' scope is requested")

			try:
				if not self._verifier:
					raise LoginError("id_token verifier not available; cannot verify id_token")
				id_claims = self._verifier.verify_id_token(
					token=idt,
					nonce=nonce,
				)
			except Exception as e:
				self._log("error", f"id_token verification failed: {e}")
				raise LoginError(f"id_token verification failed: {e}") from e

			# Access token handling: some providers (e.g., Google) issue opaque access tokens
			at = t.get("access_token")
			if not at:
				raise LoginError("access_token missing in token response")

			if self._verify_access_token_jwt:
				try:
					at_claims = self._verifier.verify_access_token(token=at)#, mode="remote")
				except Exception as e:
					self._log("error", f"access_token verification failed: {e}")
					raise LoginError(f"access_token verification failed: {e}") from e
			else:
				# Skip verification; claims unknown for opaque tokens
				at_claims = None

			# Save token atomically
			with self._token_lock:
				self._token.clear()
				self._token.update(t)
			self._log("info", "login success; tokens stored")

			return {
				"raw token": self._mask_token(self._token),
				"id_token_claims": id_claims,
				"access_token_claims": at_claims,
			}
		# Shared flow future: if already in progress, return the same future
		with self._flow_lock:
			if self._flow_in_progress and self._shared_flow_future is not None and self._shared_flow_kind == "login":
				return self._shared_flow_future
			# start new flow
			self._flow_in_progress = True
			self._shared_flow_kind = "login"
			fut = run_in_thread(_worker)
			self._shared_flow_future = fut

			def _cleanup(_: Future):
				with self._flow_lock:
					self._flow_in_progress = False
					self._shared_flow_kind = None
					self._shared_flow_future = None
			fut.add_done_callback(_cleanup)
			return fut

	def logout_async(self) -> Future:
		"""
		Start the logout flow in a background thread; return a Future:
		  success -> result is a message string
		  failure -> exception is LogoutError
		"""
		def _worker():

			try:
				# No end_session_endpoint: clear local token only
				if not self.LOGOUT_URL:
					with self._token_lock:
						self._token.clear()
					return "end_session_endpoint not available; cleared local token as logout."

				with self._token_lock:
					idt = self._token.get("id_token")
				if not idt:
					# No id_token: open OP logout page; clear local token
					try:
						self._log("info", "opening OP logout page without client context")
						self._browser_open(self.LOGOUT_URL)
					except Exception:
						pass
					with self._token_lock:
						self._token.clear()
					return "No id_token; opened OP logout page without client context (no redirect). Local token cleared."

				# RP-initiated logout
				logout_state = generate_token(24)
				params = {
					"post_logout_redirect_uri": self.LOGOUT_REDIRECT_URI,
					"id_token_hint": idt,
					"state": logout_state,
				}

				# If no redirect URI configured, perform best-effort OP logout without callback
				if not self.LOGOUT_REDIRECT_URI:
					try:
						self._log("info", "opening OP logout without redirect; clearing local token")
						self._browser_open(self.LOGOUT_URL + "?" + urllib.parse.urlencode({
							"id_token_hint": idt
						}))
					except Exception:
						pass
					with self._token_lock:
						self._token.clear()
					return "Opened OP logout without redirect (no LOGOUT_REDIRECT_URI). Local token cleared."

				self._log("info", "starting logout callback server")
				fut_cb = self._start_callback_server("logout")

				try:
					self._log("info", "opening RP-initiated logout URL in browser")
					self._browser_open(self.LOGOUT_URL + "?" + urllib.parse.urlencode(params))
				except Exception as e:
					self._stop_callback_server()
					raise LogoutError(f"Failed to open logout URL: {e}") from e

				try:
					result = fut_cb.result(timeout=self.CALLBACK_TIMEOUT)
				except TimeoutError:
					self._stop_callback_server()
					self._log("error", "logout callback timed out")
					raise LogoutError("Logout not confirmed (timeout); keeping local token.")
				except Exception as e:
					self._stop_callback_server()
					raise LogoutError(str(e)) from e
				else:
					self._stop_callback_server()

				if result.get("kind") != "logout":
					raise LogoutError("Unexpected callback kind (expect logout)")
				if result.get("error"):
					desc = result.get("error_description")
					uri = result.get("error_uri")
					extra = f"; {desc}" if desc else ""
					extra += f"; see {uri}" if uri else ""
					raise LogoutError(f"logout error: {result.get('error')}{extra}")

				if result.get("state") == logout_state and result.get("logout_seen"):
					with self._token_lock:
						self._token.clear()
					self._log("info", "logout confirmed; tokens cleared")
					return "Logout confirmed via callback; local token cleared."
				elif result:
					raise LogoutError("Logout callback state mismatch → token NOT cleared.")
				else:
					raise LogoutError("Logout not confirmed; keeping local token.")

			except Exception as e:
				raise LogoutError(str(e)) from e
		# Shared flow future: if already in progress, return the same future
		with self._flow_lock:
			if self._flow_in_progress and self._shared_flow_future is not None and self._shared_flow_kind == "logout":
				return self._shared_flow_future
			self._flow_in_progress = True
			self._shared_flow_kind = "logout"
			fut = run_in_thread(_worker)
			self._shared_flow_future = fut

			def _cleanup(_: Future):
				with self._flow_lock:
					self._flow_in_progress = False
					self._shared_flow_kind = None
					self._shared_flow_future = None
			fut.add_done_callback(_cleanup)
			return fut

	def get_valid_access_token_async(self, grace: int = 60, auto_login: bool = True, on_fail: str = "raise") -> Future:
		"""
		Get a usable access token (runs in a worker thread). Will refresh or optionally trigger login.
		After obtaining an access token, validate it using AccessTokenVerifier:
		- Google (issuer = https://accounts.google.com): use remote validation mode
		- Others: use auto mode (try JWT first, then remote if needed)
	
		Params:
		- grace: seconds before expiry to consider token as expiring.
		- auto_login: if True, when refresh is not possible or rejected, start login flow.
		- on_fail: when auto_login is False and token cannot be provided:
			- "raise" -> raise AccessTokenError
			- "none"  -> return None
	
		Returns a Future whose result is the access_token string, or None per on_fail.
		"""
		def _worker():
			now = int(time.time())

			# Snapshot current token state
			with self._token_lock:
				has_token = bool(self._token)
				exp = self._token.get("expires_at") if has_token else None
				rt = self._token.get("refresh_token") if has_token else None
				prev_id_token = self._token.get("id_token") if has_token else None
				has_rt = ("refresh_token" in self._token) if has_token else False

			# Helper: validate the given access token using AccessTokenVerifier
			def _validate(at: str) -> bool:
				is_google = (self.ISSUER.rstrip("/") == "https://accounts.google.com")
				mode = "remote" if is_google else "auto"
				try:
					sub = self._verifier.verify_access_token(at, required_scopes=self.SCOPES, mode=mode)
					self._log("info", f"access token active (mode={mode})")
					return True
				except jwt.InvalidTokenError as e:
					self._log("warning", f"access token Invalid: {e}")
					return False
				except ScopeError as e:
					# Scope mismatch means token is not suitable for current request
					self._log("warning", f"access token missing required scopes: {e}")
					return False
				except Exception as e:
					# Any unexpected validation failure => treat as invalid
					self._log("warning", f"access token validation error: {e}")
					return False

			# No token at all (not logged in yet)
			if not has_token:
				self._log("info", "no token available")
				if auto_login:
					self._log("info", "auto_login=True; triggering login")
					self.login_async().result()
				else:
					if on_fail == "none":
						return None
					raise AccessTokenError("no token available and auto_login=False")

			# Token exists; check local expiry hint and handle refresh/login
			if exp and (exp - now) < grace:
				if has_rt:
					try:
						self._log("info", "attempting token refresh (grace window)")
						refreshed = self.session.refresh_token(
							self.TOKEN_URL,
							refresh_token=rt,
							include_client_id=True,
						)
					except (InvalidGrantError, OAuth2Error):
						self._log("warning", "refresh rejected")
						if auto_login:
							self._log("info", "auto_login=True; triggering re-login")
							self.login_async().result()
						else:
							if on_fail == "none":
								return None
							raise AccessTokenError("refresh rejected and auto_login=False")
					except req_exc.RequestException as e:
						self._log("error", f"network error during refresh: {e}")
						raise RuntimeError(f"network error during refresh: {e}") from e
					else:
						with self._token_lock:
							self._token.update(refreshed)
							if "id_token" not in self._token and prev_id_token:
								self._token["id_token"] = prev_id_token
						self._log("info", "token refresh successful")
				else:
					self._log("info", "no refresh_token available")
					if auto_login:
						self._log("info", "auto_login=True; triggering re-login")
						self.login_async().result()
					else:
						if on_fail == "none":
							return None
						raise AccessTokenError("no refresh_token and auto_login=False")

			# Obtain the current access token after potential refresh/login
			with self._token_lock:
				at = self._token.get("access_token")
			if not at:
				if on_fail == "none":
					return None
				raise AccessTokenError("access_token missing after processing")

			# Validate the token using the new verifier (JWT or remote depending on issuer)
			if _validate(at):
				return at

			# Token considered invalid by validator; try one recovery attempt:
			# 1) Try refresh (if possible), else 2) try login (if allowed)
			with self._token_lock:
				rt = self._token.get("refresh_token")
				prev_id_token = self._token.get("id_token")

			if rt:
				try:
					self._log("info", "validator marked token invalid; attempting refresh")
					refreshed = self.session.refresh_token(
						self.TOKEN_URL,
						refresh_token=rt,
						include_client_id=True,
					)
				except (InvalidGrantError, OAuth2Error):
					self._log("warning", "refresh rejected after validator failure")
					refreshed = None
				except req_exc.RequestException as e:
					self._log("error", f"network error during refresh: {e}")
					raise RuntimeError(f"network error during refresh: {e}") from e
				else:
					with self._token_lock:
						self._token.update(refreshed)
						if "id_token" not in self._token and prev_id_token:
							self._token["id_token"] = prev_id_token
					self._log("info", "token refresh successful (after validator failure)")

					with self._token_lock:
						at = self._token.get("access_token")
					if at and _validate(at):
						return at

			# If refresh didn't work or we had no refresh token, optionally trigger login
			if auto_login:
				self._log("info", "validator still failing; triggering re-login")
				self.login_async().result()
				with self._token_lock:
					at = self._token.get("access_token")
				if at and _validate(at):
					return at

			# Final fallback based on on_fail policy
			if on_fail == "none":
				return None
			raise AccessTokenError("unable to provide a valid access token after validation/refresh/login")

		return run_in_thread(_worker)

	def get_identity(self):
		pass

	# --------- Restore session from a refresh_token ---------
	def restoreSessionFromRefreshToken(self, refresh_token: str) -> dict:
		"""
		Restore login state by exchanging a refresh token for new credentials.

		On success, updates internal token storage and returns a payload similar
		to login_async's result: {"raw token", "id_token_claims", "access_token_claims"}.

		Raises LoginError on failure.
		"""
		if not refresh_token or not isinstance(refresh_token, str):
			raise LoginError("refresh_token is required to restore session")

		try:
			self._log("info", "restoring session via refresh_token")
			refreshed = self.session.refresh_token(
				self.TOKEN_URL,
				refresh_token=refresh_token,
				include_client_id=True,
			)
		except (InvalidGrantError, OAuth2Error) as e:
			self._log("warning", f"refresh rejected during restore: {e}")
			raise LoginError(f"refresh rejected: {e}") from e
		except req_exc.RequestException as e:
			self._log("error", f"network error during refresh: {e}")
			raise LoginError(f"network error during refresh: {e}") from e

		# Ensure access_token is present
		at = refreshed.get("access_token")
		if not at:
			raise LoginError("access_token missing after refresh")

		# Verify access_token when applicable (skip for opaque tokens)
		if self._verify_access_token_jwt:
			try:
				at_claims = self._verifier.verify_access_token(token=at)
			except Exception as e:
				self._log("error", f"access_token verification failed: {e}")
				raise LoginError(f"access_token verification failed: {e}") from e
		else:
			at_claims = None

		# Verify id_token if provided by the OP; some providers do not return it on refresh
		id_claims = None
		idt = refreshed.get("id_token")
		if idt:
			try:
				id_claims = self._verifier.verify_id_token(token=idt)
			except Exception as e:
				self._log("error", f"id_token verification failed: {e}")
				raise LoginError(f"id_token verification failed: {e}") from e
		else:
			# If no new id_token provided, keep any existing id_token (if available)
			with self._token_lock:
				prev_idt = self._token.get("id_token")
			if prev_idt:
				refreshed["id_token"] = prev_idt
				try:
					id_claims = self._verifier.verify_id_token(token=prev_idt)
				except Exception:
					# If the previous id_token is expired/invalid, we simply omit id_claims
					id_claims = None

		# If server did not return a new refresh_token, preserve the provided one
		if not refreshed.get("refresh_token"):
			refreshed["refresh_token"] = refresh_token

		# Atomically store the refreshed token set
		with self._token_lock:
			self._token.clear()
			self._token.update(refreshed)

		self._log("info", "session restored; tokens stored")

		return {
			"raw token": self._mask_token(self._token),
			"id_token_claims": id_claims,
			"access_token_claims": at_claims,
		}

	def restore_session_from_refresh_token_async(self, refresh_token: str) -> Future:
		"""
		Async wrapper for restoreSessionFromRefreshToken. Returns a Future whose
		result is the same payload dict as the sync method or raises LoginError.
		"""
		return run_in_thread(lambda: self.restoreSessionFromRefreshToken(refresh_token))

	def get_refresh_token(self) -> Optional[str]:
		"""Return the currently stored refresh_token, if any (plain string)."""
		with self._token_lock:
			rt = self._token.get("refresh_token")
		return rt
