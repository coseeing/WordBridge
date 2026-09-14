# app.py
# Install dependencies via requirements.txt:
#   wxPython
#   authlib
#   python-dotenv
#   requests
#   PyJWT
# Example:
#   pip install -r requirements.txt

import json
import os
import threading
import time
import urllib.parse
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Lock
from typing import Optional
from concurrent.futures import Future, TimeoutError

import requests
import wx
import jwt
from dotenv import load_dotenv
from authlib.common.security import generate_token  # for PKCE code_verifier
from authlib.integrations.requests_client import OAuth2Session
from authlib.oauth2.rfc6749.errors import OAuth2Error, InvalidGrantError
from requests import exceptions as req_exc


# ---------------------------
# Load environment variables
# ---------------------------
ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV_PATH, override=True)

ISSUER = os.getenv("OIDC_AUTHORITY")
CLIENT_ID = os.getenv("OIDC_CLIENT_ID")

LOGIN_REDIRECT_URI = os.getenv("OIDC_LOGIN_REDIRECT_URI", "http://127.0.0.1:8765/auth-callback")
LOGOUT_REDIRECT_URI = os.getenv("OIDC_LOGOUT_REDIRECT_URI", "http://127.0.0.1:8765/logout-callback")

SCOPES = os.getenv("OIDC_SCOPES", "openid profile email offline_access")
API_BASE = (os.getenv("API_BASE", "") or "").rstrip("/")

# Callback wait timeout (seconds); default 180s
CALLBACK_TIMEOUT = int(os.getenv("OIDC_CALLBACK_TIMEOUT", "180"))
# UI grace: if callback not received after this many seconds, release the UI lock
LOGOUT_UI_GRACE_SECONDS = int(os.getenv("LOGOUT_UI_GRACE_SECONDS", "8"))

if not ISSUER or not CLIENT_ID:
    raise SystemExit("Please set OIDC_AUTHORITY and OIDC_CLIENT_ID in your .env")


# ---------------------------
# Helper: run a function in a background thread and return a Future
# ---------------------------
def run_in_thread(func, *args, **kwargs) -> Future:
    fut = Future()

    def _target():
        try:
            res = func(*args, **kwargs)
        except Exception as e:
            try:
                fut.set_exception(e)
            except Exception:
                pass
        else:
            try:
                fut.set_result(res)
            except Exception:
                pass

    threading.Thread(target=_target, daemon=True).start()
    return fut


# ---------------------------
# HTTP Handler (inject params via functools.partial)
# ---------------------------

class _AuthHandler(BaseHTTPRequestHandler):
    """
    Injected via partial:
    - login_path: str
    - logout_path: Optional[str]
    - future: Future
    """
    def __init__(self, *args, login_path: str, logout_path: Optional[str], future: Future, **kwargs):
        self._login_path = login_path
        self._logout_path = logout_path
        self._future = future
        super().__init__(*args, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        state = (qs.get("state") or [None])[0]
        code  = (qs.get("code")  or [None])[0]

        def _finish(kind: str, body: bytes, logout_seen: bool = False):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

            if self._future is not None and not self._future.done():
                try:
                    self._future.set_result({
                        "kind": kind,            # "login" / "logout"
                        "path": parsed.path,
                        "state": state,
                        "code": code,            # usually None for logout
                        "logout_seen": logout_seen,
                    })
                except Exception:
                    pass

        if parsed.path == self._login_path:
            _finish("login", b"Login success. You can close this tab.")
        elif self._logout_path and parsed.path == self._logout_path:
            _finish("logout", b"Logout success. You can close this tab.", logout_seen=True)
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, *_):
        return


# ---------------------------
# OIDC Client (Future-based)
# ---------------------------

class LoginError(Exception):
    pass


class LogoutError(Exception):
    pass


class OIDCClient:
    def __init__(
        self,
        issuer: str,
        client_id: str,
        scopes: str,
        login_redirect_uri: str,
        logout_redirect_uri: Optional[str],
        callback_timeout: int = 180,
    ):
        # 1) OIDC discovery (sync; safe in __init__)
        wk = requests.get(f"{issuer}/.well-known/openid-configuration", timeout=20).json()
        self.AUTH_URL = wk["authorization_endpoint"]
        self.TOKEN_URL = wk["token_endpoint"]
        self.LOGOUT_URL = wk.get("end_session_endpoint")

        # 2) OAuth session (PKCE)
        self.session = OAuth2Session(
            client_id=client_id,
            scope=scopes,
            redirect_uri=login_redirect_uri,
            code_challenge_method="S256",
        )

        # Basic settings
        self.ISSUER = issuer
        self.CLIENT_ID = client_id
        self.SCOPES = scopes
        self.LOGIN_REDIRECT_URI = login_redirect_uri
        self.LOGOUT_REDIRECT_URI = logout_redirect_uri
        self.CALLBACK_TIMEOUT = int(callback_timeout)

        # Token state
        self._token: dict = {}

        # Flow mutex (avoid concurrent auth flows)
        self._flow_lock = Lock()
        self._flow_in_progress = False

        # One-shot callback server control
        self._cb_thread: Optional[threading.Thread] = None
        self._cb_guard = Lock()
        self._cb_future: Optional[Future] = None

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
        # Stop server and signal exception to any waiter
        self._stop_callback_server()
        # Ensure flow flag is down
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

    def _run_once_server_loop(self, done_future: Future):
        """One-shot callback server: handle a single callback; end when the future completes."""
        port = int(urllib.parse.urlparse(self.LOGIN_REDIRECT_URI).port or 8765)

        class _OnceServer(HTTPServer):
            allow_reuse_address = True

        login_path  = urllib.parse.urlparse(self.LOGIN_REDIRECT_URI).path
        logout_path = urllib.parse.urlparse(self.LOGOUT_REDIRECT_URI).path if self.LOGOUT_REDIRECT_URI else None

        Handler = partial(_AuthHandler, login_path=login_path, logout_path=logout_path, future=done_future)
        srv = _OnceServer(("127.0.0.1", port), Handler)
        srv.timeout = 0.5

        try:
            while not (done_future and done_future.done()):
                srv.handle_request()
        finally:
            srv.server_close()

    def _start_callback_server(self) -> Future:
        """
        Start a one-shot blocking HTTPServer (in a thread) and return a Future for awaiting.
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

            self._cb_thread = threading.Thread(
                target=self._run_once_server_loop,
                args=(fut,),
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

            if self._cb_thread and self._cb_thread.is_alive():
                self._cb_thread.join(timeout=1.0)

            self._cb_thread = None
            self._cb_future = None

    def login_async(self) -> Future:
        """
        Start the login flow in a background thread; return a Future:
          success -> result is a payload dict
          failure -> exception is LoginError
        """
        def _worker():
            if not self._begin_flow():
                raise LoginError("Another auth flow is in progress; please finish it first.")

            code_verifier = generate_token(48)
            try:
                url, state = self.session.create_authorization_url(
                    self.AUTH_URL,
                    code_challenge_method="S256",
                    code_verifier=code_verifier
                )
            except Exception as e:
                self._end_flow()
                raise LoginError(f"create_authorization_url error: {e}") from e

            fut_cb = self._start_callback_server()

            # Open browser (sync is OK; we're in a worker thread)
            try:
                webbrowser.open(url)
            except Exception as e:
                self._stop_callback_server()
                self._end_flow()
                raise LoginError(f"Failed to open authorization URL: {e}") from e

            # Wait for callback (Future.result with timeout)
            try:
                result = fut_cb.result(timeout=self.CALLBACK_TIMEOUT)
            except TimeoutError:
                self._stop_callback_server()
                self._end_flow()
                raise LoginError("Waiting for OAuth callback timed out")
            except Exception as e:
                self._stop_callback_server()
                self._end_flow()
                raise LoginError(str(e)) from e
            else:
                self._stop_callback_server()
                self._end_flow()

            # Validate callback
            if result.get("kind") != "login":
                raise LoginError("Unexpected callback kind (expect login)")
            if result.get("state") != state:
                raise LoginError("state mismatch")

            code = result.get("code")
            if not code:
                raise LoginError("Missing authorization code in callback")

            # Exchange code for tokens (requests is sync; we're already in a worker thread)
            try:
                t = self.session.fetch_token(
                    self.TOKEN_URL,
                    None,
                    code=code,
                    code_verifier=code_verifier,
                    include_client_id=True,
                )
            except Exception as e:
                raise LoginError(f"fetch_token error: {e}") from e

            self._token.clear()
            self._token.update(t)

            return {
                "raw token": self._mask_token(self._token),
                "information token": jwt.decode(self._token["access_token"], options={"verify_signature": False}),
            }

        return run_in_thread(_worker)

    def logout_async(self) -> Future:
        """
        Start the logout flow in a background thread; return a Future:
          success -> result is a message string
          failure -> exception is LogoutError
        """
        def _worker():
            if not self._begin_flow():
                raise LogoutError("Another auth flow is in progress; please finish it first.")

            try:
                # No end_session_endpoint: clear local token only
                if not self.LOGOUT_URL:
                    self._token.clear()
                    return "end_session_endpoint not available; cleared local token as logout."

                idt = self._token.get("id_token")
                if not idt:
                    # No id_token: open OP logout page; clear local token
                    try:
                        webbrowser.open(self.LOGOUT_URL)
                    except Exception:
                        pass
                    self._token.clear()
                    return "No id_token; opened OP logout page without client context (no redirect). Local token cleared."

                # RP-initiated logout
                logout_state = generate_token(24)
                params = {
                    "post_logout_redirect_uri": self.LOGOUT_REDIRECT_URI,
                    "id_token_hint": idt,
                    "state": logout_state,
                }

                fut_cb = self._start_callback_server()

                try:
                    webbrowser.open(self.LOGOUT_URL + "?" + urllib.parse.urlencode(params))
                except Exception as e:
                    self._stop_callback_server()
                    self._end_flow()
                    raise LogoutError(f"Failed to open logout URL: {e}") from e

                try:
                    result = fut_cb.result(timeout=60)
                except TimeoutError:
                    self._stop_callback_server()
                    self._end_flow()
                    raise LogoutError("Logout not confirmed (timeout); keeping local token.")
                except Exception as e:
                    self._stop_callback_server()
                    self._end_flow()
                    raise LogoutError(str(e)) from e
                else:
                    self._stop_callback_server()
                    self._end_flow()

                if result.get("kind") != "logout":
                    raise LogoutError("Unexpected callback kind (expect logout)")

                if result.get("state") == logout_state and result.get("logout_seen"):
                    self._token.clear()
                    return "Logout confirmed via callback; local token cleared."
                elif result:
                    raise LogoutError("Logout callback state mismatch → token NOT cleared.")
                else:
                    raise LogoutError("Logout not confirmed; keeping local token.")

            except Exception as e:
                raise LogoutError(str(e)) from e

        return run_in_thread(_worker)

    def get_valid_access_token_async(self, grace: int = 60) -> Future:
        """
        Get a usable access token (runs in a worker thread). Refresh or trigger login if needed.
        Returns a Future whose result is the access_token string.
        """
        def _worker():
            if not self._token:
                # Block until login completes (still inside worker thread)
                self.login_async().result()

            now = int(time.time())
            exp = self._token.get("expires_at")

            if exp and (exp - now) < grace:
                if "refresh_token" in self._token:
                    prev_id_token = self._token.get("id_token")
                    try:
                        refreshed = self.session.refresh_token(
                            self.TOKEN_URL,
                            None,
                            refresh_token=self._token["refresh_token"],
                            include_client_id=True,
                        )
                    except (InvalidGrantError, OAuth2Error):
                        self.login_async().result()
                    except req_exc.RequestException as e:
                        raise RuntimeError(f"network error during refresh: {e}") from e
                    else:
                        self._token.update(refreshed)
                        if "id_token" not in self._token and prev_id_token:
                            self._token["id_token"] = prev_id_token
                else:
                    self.login_async().result()

            return self._token["access_token"]

        return run_in_thread(_worker)

    # Legacy convenience aliases (still return Future)
    def start_login_task(self, *args, **kwargs) -> Future:
        return self.login_async()

    def start_logout_task(self, *args, **kwargs) -> Future:
        return self.logout_async()


# ---------------------------
# wx GUI (no asyncio needed)
# ---------------------------

class Frame(wx.Frame):
    def __init__(self, oidc: OIDCClient, api_base: str):
        super().__init__(None, title="wxPython OAuth (Hydra + Kratos) [Future-based]", size=(880, 600))
        self.oidc = oidc
        self.api_base = api_base

        panel = wx.Panel(self)
        self.log = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)

        lbl = wx.StaticText(panel, label="API path or full URL:")
        self.api_input = wx.TextCtrl(panel, value="/blog/api/articles/1")

        lbl_mode = wx.StaticText(panel, label="Auth mode:")
        self.auth_mode_choice = wx.Choice(panel, choices=["auto", "with", "without"])
        self.auth_mode_choice.SetSelection(0)

        self.btn_login = wx.Button(panel, label="Login (PKCE)")
        self.btn_api = wx.Button(panel, label="Call API")
        self.btn_logout = wx.Button(panel, label="Logout (RP-initiated)")

        # Layout
        top = wx.BoxSizer(wx.VERTICAL)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        row.Add(self.api_input, 1, wx.RIGHT, 6)
        row.Add(lbl_mode, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        row.Add(self.auth_mode_choice, 0, wx.RIGHT, 6)
        row.Add(self.btn_api, 0)
        top.Add(row, 0, wx.ALL | wx.EXPAND, 8)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        btns.Add(self.btn_login, 0, wx.RIGHT, 8)
        btns.Add(self.btn_logout, 0, wx.RIGHT, 8)
        top.Add(btns, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        top.Add(self.log, 1, wx.ALL | wx.EXPAND, 8)
        panel.SetSizer(top)

        # Bind events
        self.btn_login.Bind(wx.EVT_BUTTON, self.on_login)
        self.btn_api.Bind(wx.EVT_BUTTON, self.on_api)
        self.btn_logout.Bind(wx.EVT_BUTTON, self.on_logout)

        # Initial button state
        self._set_busy(False if self.oidc else True)

    def _set_busy(self, busy: bool):
        self.btn_login.Enable(not busy)
        self.btn_logout.Enable(not busy)

    @staticmethod
    def build_url(api_base: str, path: str) -> str:
        api_base = api_base.rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        return f"{api_base}{path}"

    # --------------------------- UI flows (Future callbacks) ---------------------------

    def _login_flow(self):
        wx.CallAfter(self._set_busy, True)

        # UI-side soft-release using threading.Timer
        timer = None
        if LOGOUT_UI_GRACE_SECONDS and LOGOUT_UI_GRACE_SECONDS > 0:
            def _soft_release():
                wx.CallAfter(
                    self._on_soft_release_ui,
                    f"[login] pending; you may start a new login/logout now (soft release after {LOGOUT_UI_GRACE_SECONDS}s)."
                )
            timer = threading.Timer(LOGOUT_UI_GRACE_SECONDS, _soft_release)
            timer.daemon = True
            timer.start()

        fut = self.oidc.login_async()

        def _done(f: Future):
            if timer:
                timer.cancel()
            try:
                payload = f.result()
            except LoginError as e:
                wx.CallAfter(self.append, f"[login] error: {e}\n")
            except Exception as e:
                wx.CallAfter(self.append, f"[login] error: {e}\n")
            else:
                wx.CallAfter(self.append, f"[login] success:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n")
            finally:
                wx.CallAfter(self._set_busy, False)

        fut.add_done_callback(_done)

    def _logout_flow(self):
        wx.CallAfter(self._set_busy, True)

        timer = None
        if LOGOUT_UI_GRACE_SECONDS and LOGOUT_UI_GRACE_SECONDS > 0:
            def _soft_release():
                wx.CallAfter(
                    self._on_soft_release_ui,
                    f"[logout] pending; you may start a new login/logout now (soft release after {LOGOUT_UI_GRACE_SECONDS}s)."
                )
            timer = threading.Timer(LOGOUT_UI_GRACE_SECONDS, _soft_release)
            timer.daemon = True
            timer.start()

        fut = self.oidc.logout_async()

        def _done(f: Future):
            if timer:
                timer.cancel()
            try:
                msg = f.result()
            except LogoutError as e:
                wx.CallAfter(self.append, f"[logout] error: {e}\n")
            except Exception as e:
                wx.CallAfter(self.append, f"[logout] error: {e}\n")
            else:
                wx.CallAfter(self.append, f"[logout] success: {msg}\n")
            finally:
                wx.CallAfter(self._set_busy, False)

        fut.add_done_callback(_done)

    def api_request_async(self, method: str, url: str, auth_mode: str = "auto", timeout: int = 20) -> Future:
        def _worker():
            mode = (auth_mode or "auto").lower()
            logs: list[str] = []

            def _send(with_token: bool):
                headers = {}
                if with_token:
                    at = self.oidc.get_valid_access_token_async().result()
                    headers["Authorization"] = f"Bearer {at}"

                resp = requests.request(
                    method.upper(), url,
                    headers=headers, timeout=timeout,
                )
                token_state = "with token" if with_token else "no token"
                logs.append(f"[api_request] auth_mode={mode}, actually {token_state}, status={resp.status_code}")
                return resp

            # Main flow
            if mode == "with":
                logs.append(f"[api_action] auth_mode={mode}")
                resp = _send(True)
            elif mode == "without":
                logs.append(f"[api_action] auth_mode={mode}")
                resp = _send(False)
            elif mode == "auto":
                logs.append("[api_action] auth_mode=auto → try no token...")
                resp = _send(False)
                if resp.status_code == 401:
                    logs.append("[api_action] auth_mode=auto → retry with token...")
                    resp = _send(True)
            else:
                raise ValueError(f"Invalid auth_mode: {mode}")

            try:
                body = resp.json()
            except Exception:
                body = resp.text

            return {
                "logs": logs,
                "status": resp.status_code,
                "data": body,
                "url": url,
                "method": method,
                "auth_mode": mode,
            }

        return run_in_thread(_worker)

    def _api_flow(self, url: str, auth_mode: str = "auto"):
        fut = self.api_request_async("GET", url, auth_mode=auth_mode, timeout=20)

        def _done(f: Future):
            try:
                payload = f.result()
            except Exception as e:
                wx.CallAfter(self.append, f"[api] error: {e}\n")
            else:
                def _ui():
                    for line in payload["logs"]:
                        self.append(line + "\n")
                    self.append(f"[api] {payload['status']} ({payload['url']}):\n{payload['data']}\n")
                wx.CallAfter(_ui)

        fut.add_done_callback(_done)

    def on_login(self, _):
        if not self.oidc:
            raise RuntimeError("no oidc for login")
        if self.oidc.flow_in_progress:
            self.append("Previous auth flow still running; aborting it and starting a new login.\n")
            if hasattr(self.oidc, "abort_pending_flow"):
                self.oidc.abort_pending_flow("user clicked login again")
        self._login_flow()

    def on_logout(self, _):
        if not self.oidc:
            raise RuntimeError("no oidc for logout")
        if self.oidc.flow_in_progress:
            self.append("Previous auth flow still running; aborting it and starting a new logout.\n")
            if hasattr(self.oidc, "abort_pending_flow"):
                self.oidc.abort_pending_flow("user clicked logout again")
        self._logout_flow()

    def on_api(self, _):
        raw = (self.api_input.GetValue() or "").strip()
        if not raw:
            self.append("[api] Please input API path or full URL\n")
            return

        auth_mode = self.auth_mode_choice.GetStringSelection() or "auto"
        if raw.lower().startswith(("http://", "https://")):
            url = raw
        else:
            if not self.api_base:
                self.append("[api] Please set API_BASE in .env\n")
                return
            url = self.build_url(self.api_base, raw)

        self._api_flow(url, auth_mode=auth_mode)

    # ---------------------------

    def _on_soft_release_ui(self, msg: str):
        self.append(msg + "\n")
        self._set_busy(False)

    def append(self, s: str):
        self.log.AppendText(s)


# ---------------------------
# main
# ---------------------------

def main():
    try:
        oidc = OIDCClient(
            issuer=ISSUER,
            client_id=CLIENT_ID,
            scopes=SCOPES,
            login_redirect_uri=LOGIN_REDIRECT_URI,
            logout_redirect_uri=LOGOUT_REDIRECT_URI,
            callback_timeout=CALLBACK_TIMEOUT,
        )
    except Exception as e:
        print("OIDC init failed:", e)
        oidc = None

    app = wx.App(False)
    f = Frame(oidc, API_BASE)
    f.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
