import sys
import threading
from collections.abc import Callable
from concurrent.futures import CancelledError, Future, InvalidStateError
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from coseeing_auth import AuthConfig

import addonHandler

addonHandler.initTranslation()

_auth_dependencies_prepared = False
COSEEING_REFRESH_TOKEN_TARGET = "org.coseeing.wordbridge/refresh"


def _auth_dependency_path() -> Path | None:
	if sys.platform != "win32":
		return None

	return (
		Path(__file__).resolve().parents[1]
		/ "package"
		/ "_coseeing_auth_deps"
		/ "py313-win_amd64"
	)


def _prepare_auth_dependencies() -> None:
	global _auth_dependencies_prepared
	path = _auth_dependency_path()
	if path is not None and not path.is_dir():
		raise ImportError(f"Coseeing auth dependencies are unavailable for Python {sys.version_info[:2]}")
	if path is None:
		return
	path_string = str(path)
	if path_string not in sys.path:
		sys.path.insert(0, path_string)
	if _auth_dependencies_prepared:
		return

	# NVDA may preload its own cryptography from library.zip.  Remove that
	# module tree before coseeing_auth imports Authlib, otherwise Python keeps
	# resolving cryptography submodules from the preloaded NVDA package even
	# after the addon dependency directory is first on sys.path.
	for module_name in tuple(sys.modules):
		if module_name == "cryptography" or module_name.startswith("cryptography."):
			del sys.modules[module_name]
	_auth_dependencies_prepared = True


_prepare_auth_dependencies()
from authlib.integrations.base_client.errors import OAuthError
from coseeing_auth.errors import ClientClosedError, RestoreError, TokenUnavailableError, TokenValidationError


class AuthSessionState:
	def __init__(self) -> None:
		self.refresh_token_was_valid = False


def build_auth_config() -> "AuthConfig":
	_prepare_auth_dependencies()
	from coseeing_auth import AuthConfig

	return AuthConfig(
		issuer="https://sso.coseeing.org",
		client_id="wordbridge",
		scopes=("openid", "profile", "email", "offline_access"),
		login_redirect_uri="http://127.0.0.1:8000/auth-callback",
		logout_redirect_uri="http://127.0.0.1:8000/logout-callback",
		callback_timeout=180,
	)


def _new_refresh_token_store():
	from coseeing_auth import WindowsCredentialStore

	return WindowsCredentialStore(COSEEING_REFRESH_TOKEN_TARGET)


def has_saved_coseeing_refresh_token() -> bool:
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
		from coseeing_auth import CoseeingAuthClient, FutureAuthClient

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
				"Coseeing auth failure type=%s operation=%s stage=%s code=%s",
				type(error).__name__, operation, stage, code,
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


def start_coseeing_auth(execution_channel: str, *, silent: bool = True) -> None:
	if execution_channel != "Coseeing":
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
