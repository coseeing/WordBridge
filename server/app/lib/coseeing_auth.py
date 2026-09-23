import sys
import threading
from collections.abc import Callable
from concurrent.futures import CancelledError, Future, InvalidStateError
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from _wb_vendor.coseeing_auth import AuthConfig

import addonHandler

from . import vendor

addonHandler.initTranslation()

COSEEING_REFRESH_TOKEN_TARGET = "org.coseeing.wordbridge/refresh"


class CoseeingAuthUnavailableError(Exception):
	"""The Coseeing auth dependencies are not loadable on this runtime."""


_AUTH_IMPORT_ERROR = None
_AUTH_IMPORT_MODULE = None

# Two separate try/except blocks -- rather than one try wrapping both imports
# -- so a failure can be attributed to the specific import statement that
# raised it. Only two statements are ever in scope, so naming them is cheap,
# and it is what lets unavailable_reason() name "which module" for spec
# failure row 2 regardless of the exception type the failing module raises
# (deferred minor folded in alongside the row 1/row 2 fix below: with this
# broadened `except Exception`, a bundle module raising something other than
# ImportError -- e.g. RuntimeError('boom') -- has no `.name` attribute to
# fall back on, so the import statement itself is the only way to know which
# module was being imported).
try:
	from _wb_vendor.authlib.integrations.base_client.errors import OAuthError
except Exception as error:
	_AUTH_IMPORT_ERROR = error
	_AUTH_IMPORT_MODULE = "_wb_vendor.authlib.integrations.base_client.errors"
else:
	try:
		from _wb_vendor.coseeing_auth.errors import (
			ClientClosedError,
			RestoreError,
			TokenUnavailableError,
			TokenValidationError,
		)
	except Exception as error:
		_AUTH_IMPORT_ERROR = error
		_AUTH_IMPORT_MODULE = "_wb_vendor.coseeing_auth.errors"

if _AUTH_IMPORT_ERROR is not None:
	AUTH_AVAILABLE = False

	class _UnavailableAuthError(Exception):
		"""Placeholder base bound only when the real auth bundle failed to import.

		Binds `OAuthError`, `ClientClosedError`, `RestoreError`,
		`TokenUnavailableError` and `TokenValidationError` to placeholder
		subclasses of this class so the `isinstance()` checks in `_fail()` and
		the `raise ClientClosedError(...)` sites elsewhere in this file stay
		valid on a runtime where the bundle is absent. `_get_singleton_pair()`
		refuses to construct a session while `AUTH_AVAILABLE` is False, so in
		practice those sites never run against these placeholders -- but
		`CoseeingAuthSession` is public and directly constructible, so that is a
		guarantee from the call site, not from these classes being unraisable.

		All five are bound here regardless of which of the two import
		statements above failed: whichever one raised, neither import
		completed, so no real error class from either module is available to
		bind any of the five names to.
		"""

	class OAuthError(_UnavailableAuthError):
		pass

	class ClientClosedError(_UnavailableAuthError):
		pass

	class RestoreError(_UnavailableAuthError):
		pass

	class TokenUnavailableError(_UnavailableAuthError):
		pass

	class TokenValidationError(_UnavailableAuthError):
		pass
else:
	AUTH_AVAILABLE = True


def unavailable_reason() -> str:
	"""Diagnostic string for the auth half being unavailable.

	Spec:284 requires four failure rows stay distinguishable, because their
	remedies differ. Including `_wb_vendor.__path__` is what separates rows 1
	and 2: with the runtime deps directory absent, it is `[.../package]`; with
	a present-but-broken bundle, it is `[.../package, .../py313-win_amd64]` --
	otherwise both read as the identical
	`ModuleNotFoundError: No module named '_wb_vendor.authlib'`. Row 2 also
	names which of the two import statements failed (`_AUTH_IMPORT_MODULE`),
	so a non-ImportError failure -- which has no `.name` attribute -- is still
	attributable to a module.

	Only the exception type and str(error) are ever included, never a
	traceback, tokens or user text.
	"""
	runtime = vendor.runtime_key()
	if runtime is None:
		runtime = f"unsupported (sys.platform={sys.platform!r}, python={sys.version_info[:2]!r})"
	namespace = sys.modules.get(vendor.PREFIX)
	roots = list(getattr(namespace, "__path__", []) or []) if namespace is not None else None
	if _AUTH_IMPORT_ERROR is None:
		return (
			f"Coseeing auth dependencies unavailable "
			f"(runtime={runtime}, _wb_vendor.__path__={roots}, not loaded)"
		)
	detail = f"{_AUTH_IMPORT_MODULE}: {type(_AUTH_IMPORT_ERROR).__name__}: {_AUTH_IMPORT_ERROR}"
	missing_name = getattr(_AUTH_IMPORT_ERROR, "name", None)
	top_level = missing_name.split(".")[0] if missing_name else None
	if top_level in vendor.HOST_ONLY:
		detail = f"{detail} (host environment changed: {top_level!r} is expected from NVDA, not the bundle)"
	return (
		f"Coseeing auth dependencies unavailable "
		f"(runtime={runtime}, _wb_vendor.__path__={roots}, {detail})"
	)


class AuthSessionState:
	def __init__(self) -> None:
		self.refresh_token_was_valid = False


def build_auth_config() -> "AuthConfig":
	from _wb_vendor.coseeing_auth import AuthConfig

	return AuthConfig(
		issuer="https://sso.coseeing.org",
		client_id="wordbridge",
		scopes=("openid", "profile", "email", "offline_access"),
		login_redirect_uri="http://127.0.0.1:8000/auth-callback",
		logout_redirect_uri="http://127.0.0.1:8000/logout-callback",
		callback_timeout=180,
	)


def _new_refresh_token_store():
	from _wb_vendor.coseeing_auth import WindowsCredentialStore

	return WindowsCredentialStore(COSEEING_REFRESH_TOKEN_TARGET)


def has_saved_coseeing_refresh_token() -> bool:
	if not AUTH_AVAILABLE:
		return False
	try:
		return _new_refresh_token_store().load() is not None
	except Exception:
		return False


class CoseeingAuthSession:
	def __init__(
		self,
		*,
		client_factory: Callable[[], object],
		post_ui: Callable[..., None],
		prompt_login: Callable[[], str],
		auth_state: AuthSessionState | None = None,
	) -> None:
		self._client_factory = client_factory
		self._post_ui = post_ui
		self._prompt_login = prompt_login
		self._auth_state = auth_state or AuthSessionState()
		self._guest = False
		self._closed = False
		self._session_ready = False
		self._client = None
		self._waiters: list[Future[str | None]] = []
		self._active = False
		self._close_requested = False
		self._client_creation_in_progress = False
		self._admitted_requests = 0
		self._cleanup_started = False
		self._cleanup_future: Future[None] | None = None
		self._cleanup_error: Exception | None = None
		self._state_lock = threading.RLock()

	def get_access_token(self, *, reconsider_guest: bool = False, silent: bool = False) -> Future[str | None]:
		result: Future[str | None] = Future()
		try:
			self._post_ui(self._request, result, reconsider_guest, silent)
		except Exception as error:
			result.set_exception(error)
		return result

	def logout_local(self) -> Future[None]:
		result: Future[None] = Future()
		try:
			self._post_ui(self._start_logout_local, result)
		except Exception as error:
			result.set_exception(error)
		return result

	def _start_logout_local(self, result: Future[None]) -> None:
		try:
			future = self._call_client("logout_local")
		except Exception as error:
			self._complete(result, error=error)
			return

		def completed(done: Future) -> None:
			try:
				self._post_ui(deliver, done)
			except Exception as error:
				self._complete(result, error=error)

		def deliver(done: Future) -> None:
			try:
				done.result()
			except Exception as error:
				self._complete(result, error=error)
				return
			self._session_ready = False
			self._guest = False
			self._auth_state.refresh_token_was_valid = False
			self._complete(result, value=None)

		future.add_done_callback(completed)

	def close(self) -> Future[None]:
		with self._state_lock:
			if self._cleanup_future is not None:
				return self._cleanup_future
			cleanup: Future[None] = Future()
			self._cleanup_future = cleanup
			self._close_requested = True
		try:
			self._post_ui(self._close_ui, cleanup)
		except Exception:
			try:
				self._post_ui(self._close_ui, cleanup)
			except Exception as retry_error:
				with self._state_lock:
					client = self._client
					creating = self._client_creation_in_progress
					admitted = self._admitted_requests
					if client is not None:
						self._record_close_schedule_failure(retry_error)
						self._finish_handoff(error=ClientClosedError("access_token"))
						self._start_cleanup_once(client, cleanup)
					elif not creating and not admitted:
						self._record_close_schedule_failure(retry_error)
						self._complete_cleanup(error=retry_error)
		return cleanup

	def _record_close_schedule_failure(self, error: Exception) -> None:
		with self._state_lock:
			if self._cleanup_error is None:
				self._cleanup_error = error

	def _complete_cleanup(self, *, error: Exception | None = None) -> None:
		with self._state_lock:
			cleanup = self._cleanup_future
			if cleanup is None or cleanup.done():
				return
			cleanup_error = error or self._cleanup_error
			try:
				if cleanup_error is None:
					cleanup.set_result(None)
				else:
					cleanup.set_exception(cleanup_error)
			except InvalidStateError:
				pass

	def _close_ui(self, cleanup: Future[None]) -> None:
		self._closed = True
		self._finish(error=ClientClosedError("access_token"))
		client = self._client
		if client is None:
			with self._state_lock:
				admitted = self._admitted_requests
				creating = self._client_creation_in_progress
			if not admitted and not creating:
				self._complete_cleanup()
		else:
			self._start_cleanup_once(client, cleanup)

	def _start_cleanup_once(self, client: object, cleanup: Future[None]) -> None:
		with self._state_lock:
			if self._cleanup_started:
				return
			self._cleanup_started = True
		threading.Thread(
			target=self._close_client,
			args=(client, cleanup),
			name="coseeing-auth-session-cleanup",
			daemon=True,
		).start()

	def _close_client(self, client: object, cleanup: Future[None]) -> None:
		try:
			client.close()
		except Exception as error:
			self._complete_cleanup(error=error)
		else:
			self._complete_cleanup()

	def _request(self, waiter: Future[str | None], reconsider_guest: bool, silent: bool = False) -> None:
		with self._state_lock:
			if self._closed or self._close_requested:
				closed = True
				guest = False
			else:
				closed = False
				if reconsider_guest:
					self._guest = False
				if self._active:
					self._waiters.append(waiter)
					return
				if self._guest:
					guest = True
				else:
					guest = False
					self._waiters.append(waiter)
					self._active = True
					self._admitted_requests += 1
		if closed:
			self._complete(waiter, error=ClientClosedError("access_token"))
			return
		if guest:
			self._complete(waiter, value=None)
			return

		try:
			if self._session_ready:
				self._start_access_token(silent=silent)
				return
			self._start_restore_saved_session(silent)
		finally:
			with self._state_lock:
				closing = self._close_requested
				self._admitted_requests -= 1
				if (
					self._close_requested
					and not self._admitted_requests
					and not self._client_creation_in_progress
					and self._client is None
				):
					self._complete_cleanup()
			if closing:
				self._finish_handoff(error=ClientClosedError("access_token"))

	def _call_client(self, method: str, *args, **kwargs):
		with self._state_lock:
			client = self._client
			if client is None:
				self._client_creation_in_progress = True
		if client is None:
			try:
				client = self._client_factory()
			except Exception:
				with self._state_lock:
					self._client_creation_in_progress = False
				raise
			with self._state_lock:
				self._client_creation_in_progress = False
				self._client = client
				if self._close_requested:
					cleanup = self._cleanup_future
					if cleanup is not None:
						self._start_cleanup_once(client, cleanup)
		with self._state_lock:
			if self._close_requested:
				raise ClientClosedError("access_token")
			return getattr(client, method)(*args, **kwargs)

	def _is_closing(self) -> bool:
		with self._state_lock:
			return self._close_requested

	def _start_restore_saved_session(self, silent: bool) -> None:
		try:
			future = self._call_client("restore_saved_session")
			self._watch(
				future,
				lambda result: self._restore_saved_session_succeeded(result, silent=silent),
				silent=silent,
			)
		except Exception as error:
			self._fail(error, silent=silent)

	def _restore_saved_session_succeeded(self, result: object | None, *, silent: bool = False) -> None:
		if result is None:
			self._start_prompt(silent)
			return
		self._auth_state.refresh_token_was_valid = True
		self._session_ready = True
		self._start_access_token(silent=silent)

	def _start_access_token(self, *, silent: bool = False) -> None:
		try:
			future = self._call_client("get_access_token", auto_login=False)
			self._watch(future, self._token_succeeded, silent=silent)
		except Exception as error:
			self._fail(error, silent=silent)

	def _start_prompt(self, silent: bool = False) -> None:
		if silent:
			self._finish(value=None)
			return
		try:
			choice = self._prompt_login()
		except Exception as error:
			self._fail(error, silent=silent)
			return
		if choice == "guest":
			self._guest = True
			self._finish(value=None)
		elif choice == "cancel":
			self._finish(error=CancelledError())
		elif choice == "login":
			try:
				future = self._call_client("login")
				self._watch(future, lambda result: self._login_succeeded(result, silent=silent), silent=silent)
			except Exception as error:
				self._fail(error, silent=silent)
		else:
			self._fail(ValueError(f"unknown login choice: {choice!r}"))

	def _login_succeeded(self, _result: object, *, silent: bool = False) -> None:
		self._auth_state.refresh_token_was_valid = True
		self._session_ready = True
		self._start_access_token(silent=silent)

	def _token_succeeded(self, access_token: str) -> None:
		self._finish(value=access_token)

	def _watch(self, future: Future, succeeded: Callable[[object], None], *, silent: bool = False) -> None:
		def completed(done: Future) -> None:
			try:
				self._post_ui(deliver, done)
			except Exception as error:
				try:
					self._post_ui(deliver_scheduler_error, error)
				except Exception as retry_error:
					try:
						self._post_ui(deliver_scheduler_error, retry_error)
					except Exception:
						self._finish_handoff(error=retry_error)

		def deliver_scheduler_error(error: Exception) -> None:
			if self._closed:
				return
			self._finish(error=error)

		def deliver(done: Future) -> None:
			if self._closed or self._is_closing():
				return
			try:
				value = done.result()
			except Exception as error:
				self._fail(error, silent=silent)
			else:
				succeeded(value)

		future.add_done_callback(completed)

	def _fail(self, error: Exception, *, silent: bool = False) -> None:
		if isinstance(error, OAuthError) and getattr(error, "error", None) in {
			"invalid_grant",
			"invalid_token",
			"token_invalid",
		}:
			self._session_ready = False
			self._start_prompt(silent)
			return
		if isinstance(error, TokenValidationError):
			self._session_ready = False
			self._start_prompt(silent)
			return
		if isinstance(error, RestoreError) and error.code == "refresh_rejected":
			self._session_ready = False
			self._start_prompt(silent)
			return
		if isinstance(error, TokenUnavailableError) and error.code in {
			"refresh_rejected",
			"refresh_unavailable",
		}:
			if error.code == "refresh_rejected":
				self._session_ready = False
			self._start_prompt(silent)
			return
		self._finish(error=error)

	def _finish(self, *, value: str | None = None, error: Exception | None = None) -> None:
		self._finish_handoff(value=value, error=error)

	def _finish_handoff(self, *, value: str | None = None, error: Exception | None = None) -> None:
		with self._state_lock:
			self._active = False
			waiters, self._waiters = self._waiters, []
		for waiter in waiters:
			self._complete(waiter, value=value, error=error)

	@staticmethod
	def _complete(
		waiter: Future[str | None], *, value: str | None = None, error: Exception | None = None
	) -> None:
		try:
			if error is None:
				waiter.set_result(value)
			else:
				waiter.set_exception(error)
		except InvalidStateError:
			pass


def _cause_summary(error: BaseException) -> str:
	"""Name the failure the library mapped away, for the log line above.

	`CoseeingAuthClient` collapses every internal failure onto a small set of
	(operation, stage, code) triples and raises the mapped error `from` a
	`_SanitizedCause` whose message is `"<original type>: <code>"`. That cause
	is the only surviving record of what actually went wrong, and several
	unrelated failures share one code: `code=token_exchange_failed` is what
	both an `OAuthError` (the token endpoint rejected the exchange) and a
	`RuntimeError` (the OIDC protocol was already closed) arrive as. Without
	this, NVDA's log cannot tell them apart.

	Only `_SanitizedCause`'s message is rendered: the library builds it from a
	type name and a fixed code, so it can carry no token, URL or user text.
	Any other cause contributes its type name alone -- never `str()` -- which
	is the same rule the `type=%s` field above already follows.
	"""
	cause = error.__cause__
	if cause is None:
		return "none"
	if type(cause).__name__ == "_SanitizedCause":
		return str(cause)
	return type(cause).__name__


class _NvdaAuthAdapter:
	def __init__(self) -> None:
		# NVDA modules are deliberately imported only when the adapter is built.
		import config
		import gui
		import ui
		import wx
		from logHandler import log

		self._config = config
		self._gui = gui
		self._ui = ui
		self._wx = wx
		self._log = log
		self._active_dialog = None
		self._dialog_lock = threading.RLock()
		self._shutting_down = False

	def post_ui(self, function, *args) -> None:
		self._wx.CallAfter(function, *args)

	def client_factory(self) -> object:
		config = build_auth_config()
		from _wb_vendor.coseeing_auth import CoseeingAuthClient, FutureAuthClient

		return FutureAuthClient(CoseeingAuthClient(
			config,
			refresh_token_store=_new_refresh_token_store(),
		))

	def prompt_login(self) -> str:
		dialog = self._gui.message.MessageDialog(
			self._gui.mainFrame,
			_("Sign in to Coseeing to use this service, or continue as a guest."),
			_("Coseeing authentication"),
			buttons=self._gui.message.DefaultButtonSet.YES_NO,
		)
		dialog.setYesNoLabels(_("Sign in"), _("Continue as guest"))
		with self._dialog_lock:
			self._active_dialog = dialog
		try:
			result = dialog.ShowModal()
		finally:
			with self._dialog_lock:
				if self._active_dialog is dialog:
					self._active_dialog = None
			dialog.Destroy()
		if result == self._wx.ID_YES:
			return "login"
		if result == self._wx.ID_NO:
			return "guest"
		return "cancel"

	def close_active_dialog(self) -> None:
		with self._dialog_lock:
			dialog = self._active_dialog
		if dialog is None:
			return
		try:
			dialog.EndModal(self._wx.ID_CANCEL)
		except Exception as error:
			self._log.warning(
				"Coseeing auth dialog close failed type=%s operation=%s stage=%s code=%s",
				type(error).__name__, "shutdown", "dialog", "close_failed",
			)

	def session(self, *, auth_state: AuthSessionState | None = None) -> CoseeingAuthSession:
		return CoseeingAuthSession(
			client_factory=self.client_factory,
			post_ui=self.post_ui,
			prompt_login=self.prompt_login,
			auth_state=auth_state,
		)

	def notify_completion(self, done: Future) -> None:
		self._notify_completion(done, notify_during_shutdown=False)

	def notify_clean_completion(self, done: Future) -> None:
		self._notify_completion(done, notify_during_shutdown=True)

	def _notify_completion(self, done: Future, *, notify_during_shutdown: bool) -> None:
		try:
			done.result()
		except CancelledError:
			return
		except Exception as error:
			with self._dialog_lock:
				if self._shutting_down and not notify_during_shutdown:
					return
			operation = getattr(error, "operation", "access_token")
			stage = getattr(error, "stage", "unknown")
			code = getattr(error, "code", "unknown")
			self._log.warning(
				"Coseeing auth failure type=%s operation=%s stage=%s code=%s cause=%s",
				type(error).__name__, operation, stage, code, _cause_summary(error),
			)
			try:
				self.post_ui(self._deliver_notification, notify_during_shutdown)
			except Exception:
				return

	def _deliver_notification(self, notify_during_shutdown: bool = False) -> None:
		with self._dialog_lock:
			if self._shutting_down and not notify_during_shutdown:
				return
		self._ui.message(_("Coseeing authentication failed."))


_singleton_lock = threading.RLock()
_singleton_session: CoseeingAuthSession | None = None
_singleton_adapter: _NvdaAuthAdapter | None = None
_shutdown_future: Future[None] | None = None
_auth_state = AuthSessionState()


def _get_singleton_pair() -> tuple[CoseeingAuthSession, _NvdaAuthAdapter]:
	global _singleton_adapter, _singleton_session
	if not AUTH_AVAILABLE:
		raise CoseeingAuthUnavailableError(unavailable_reason())
	with _singleton_lock:
		if _shutdown_future is not None:
			raise ClientClosedError("access_token")
		if _singleton_session is None:
			adapter = _NvdaAuthAdapter()
			_singleton_adapter = adapter
			_singleton_session = adapter.session(auth_state=_auth_state)
		return _singleton_session, _singleton_adapter


def _get_singleton() -> CoseeingAuthSession:
	return _get_singleton_pair()[0]


def has_seen_valid_refresh_token() -> bool:
	return _auth_state.refresh_token_was_valid


def get_coseeing_access_token(*, reconsider_guest: bool = False, silent: bool | None = None) -> Future[str | None]:
	if silent is None:
		silent = not has_seen_valid_refresh_token()
	try:
		return _get_singleton().get_access_token(reconsider_guest=reconsider_guest, silent=silent)
	except Exception as error:
		return _completed_future(error)


def _notify_auth_unavailable() -> None:
	"""Report the domain error when the user selects the Coseeing channel while
	the auth half is unavailable.

	`get_coseeing_access_token()` never raises `CoseeingAuthUnavailableError`
	here: it swallows it into a failed `Future` (see its `except` clause), so
	`start_coseeing_auth()`'s own `except` never fires, and no adapter exists
	yet to deliver the failure through `notify_completion` -- `_singleton_adapter`
	is only ever set once `_get_singleton_pair()` has confirmed the auth half is
	available. Without this, selecting the Coseeing channel while unavailable
	produces complete silence (spec:278-281 requires it be reported).

	NVDA modules are imported lazily here, matching `_NvdaAuthAdapter.__init__`.
	"""
	import ui
	import wx

	try:
		wx.CallAfter(ui.message, _("Coseeing authentication is unavailable on this installation."))
	except Exception:
		pass


def start_coseeing_auth(execution_channel: str, *, silent: bool = True) -> None:
	if execution_channel != "Coseeing":
		return
	if not AUTH_AVAILABLE:
		if not silent:
			_notify_auth_unavailable()
		return
	try:
		future = get_coseeing_access_token(reconsider_guest=True, silent=silent)
	except Exception as error:
		adapter = _singleton_adapter
		if adapter is not None:
			adapter.notify_completion(_completed_future(error))
		return
	adapter = _singleton_adapter
	if adapter is not None:
		future.add_done_callback(adapter.notify_completion)


def reset_coseeing_auth() -> Future[None]:
	global _singleton_adapter, _singleton_session
	with _singleton_lock:
		if _shutdown_future is not None:
			return _shutdown_future
		adapter = _singleton_adapter
		session = _singleton_session
		if adapter is None or session is None:
			completed: Future[None] = Future()
			completed.set_result(None)
			return completed
		adapter._shutting_down = True
		cleanup = session.close()
		_singleton_adapter = None
		_singleton_session = None
	try:
		adapter.post_ui(adapter.close_active_dialog)
	except Exception:
		adapter.close_active_dialog()
	return cleanup


def _reset_captured_coseeing_auth(
	session: CoseeingAuthSession,
	adapter: _NvdaAuthAdapter,
) -> Future[None]:
	global _singleton_adapter, _singleton_session
	with _singleton_lock:
		adapter._shutting_down = True
		cleanup = session.close()
		if _singleton_session is session and _singleton_adapter is adapter:
			_singleton_adapter = None
			_singleton_session = None
	try:
		adapter.post_ui(adapter.close_active_dialog)
	except Exception:
		adapter.close_active_dialog()
	return cleanup


def _settle_none(destination: Future[None], error: Exception | None = None) -> None:
	try:
		if error is None:
			destination.set_result(None)
		else:
			destination.set_exception(error)
	except InvalidStateError:
		pass


def clean_coseeing_auth() -> Future[None]:
	bridge: Future[None] = Future()
	try:
		session, adapter = _get_singleton_pair()
	except Exception as error:
		with _singleton_lock:
			adapter = _singleton_adapter
		if adapter is not None:
			bridge.add_done_callback(getattr(adapter, "notify_clean_completion", adapter.notify_completion))
		_settle_none(bridge, error)
		return bridge

	bridge.add_done_callback(getattr(adapter, "notify_clean_completion", adapter.notify_completion))
	try:
		logout = session.logout_local()
	except Exception as error:
		_settle_none(bridge, error)
		return bridge

	def cleanup_done(done: Future) -> None:
		try:
			done.result()
		except Exception as error:
			_settle_none(bridge, error)
		else:
			_settle_none(bridge)

	def logout_done(done: Future) -> None:
		try:
			done.result()
		except Exception as error:
			_settle_none(bridge, error)
			return
		try:
			cleanup = _reset_captured_coseeing_auth(session, adapter)
		except Exception as error:
			_settle_none(bridge, error)
			return
		cleanup.add_done_callback(cleanup_done)

	logout.add_done_callback(logout_done)
	return bridge


def _completed_future(error: Exception) -> Future:
	future = Future()
	future.set_exception(error)
	return future


def shutdown_coseeing_auth() -> Future[None]:
	global _shutdown_future, _singleton_adapter, _singleton_session
	with _singleton_lock:
		if _shutdown_future is not None:
			return _shutdown_future
		adapter = _singleton_adapter
		session = _singleton_session
		if adapter is not None:
			adapter._shutting_down = True
		if adapter is None or session is None:
			completed: Future[None] = Future()
			completed.set_result(None)
			_shutdown_future = completed
			_singleton_adapter = None
			_singleton_session = None
			return _shutdown_future
		_shutdown_future = session.close()
		_singleton_adapter = None
		_singleton_session = None
	try:
		adapter.post_ui(adapter.close_active_dialog)
	except Exception:
		adapter.close_active_dialog()
	return _shutdown_future
