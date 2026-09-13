import struct
import sys
import threading
from collections.abc import Callable
from concurrent.futures import CancelledError, Future, InvalidStateError
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from coseeing_auth import AuthConfig


def _auth_dependency_path() -> Path | None:
	if sys.platform != "win32":
		return None

	python_version = f"{sys.version_info.major}{sys.version_info.minor}"
	architecture = "win32" if struct.calcsize("P") == 4 else "win_amd64"
	return (
		Path(__file__).resolve().parents[1]
		/ "package"
		/ "_coseeing_auth_deps"
		/ f"py{python_version}-{architecture}"
	)


def _prepare_auth_dependencies() -> None:
	path = _auth_dependency_path()
	if path is not None and not path.is_dir():
		raise ImportError(f"Coseeing auth dependencies are unavailable for Python {sys.version_info[:2]}")
	if path is not None and str(path) not in sys.path:
		sys.path.insert(0, str(path))


_prepare_auth_dependencies()
from coseeing_auth.errors import ClientClosedError, RestoreError, TokenUnavailableError


def build_auth_config() -> "AuthConfig":
	_prepare_auth_dependencies()
	from coseeing_auth import AuthConfig

	return AuthConfig(
		issuer="https://sso.coseeing.org",
		client_id="a11yvillage",
		scopes=("openid", "profile", "email", "offline_access"),
		login_redirect_uri="http://127.0.0.1:8765/auth-callback",
		logout_redirect_uri="http://127.0.0.1:8765/logout-callback",
		callback_timeout=180,
	)


class CoseeingAuthSession:
	def __init__(
		self,
		*,
		client_factory: Callable[[], object],
		post_ui: Callable[..., None],
		read_refresh_token: Callable[[], str | None],
		save_refresh_token: Callable[[str | None], None],
		prompt_login: Callable[[], str],
	) -> None:
		self._client_factory = client_factory
		self._post_ui = post_ui
		self._read_refresh_token = read_refresh_token
		self._save_refresh_token = save_refresh_token
		self._prompt_login = prompt_login
		self._guest = False
		self._closed = False
		self._session_ready = False
		self._client = None
		self._waiters: list[Future[str | None]] = []
		self._active = False
		self._close_requested = False
		self._client_creation_in_progress = False
		self._cleanup_started = False
		self._cleanup_future: Future[None] | None = None
		self._state_lock = threading.RLock()

	def get_access_token(self, *, reconsider_guest: bool = False) -> Future[str | None]:
		result: Future[str | None] = Future()
		try:
			self._post_ui(self._request, result, reconsider_guest)
		except Exception as error:
			result.set_exception(error)
		return result

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
			with self._state_lock:
				client = self._client
				creating = self._client_creation_in_progress
			if client is not None:
				self._start_cleanup_once(client, cleanup)
			try:
				self._post_ui(self._close_ui, cleanup)
			except Exception as retry_error:
				if client is None and not creating:
					cleanup.set_exception(retry_error)
					return cleanup
		return cleanup

	def _close_ui(self, cleanup: Future[None]) -> None:
		self._closed = True
		self._finish(error=ClientClosedError("access_token"))
		client = self._client
		if client is None:
			cleanup.set_result(None)
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
			cleanup.set_exception(error)
		else:
			cleanup.set_result(None)

	def _request(self, waiter: Future[str | None], reconsider_guest: bool) -> None:
		if self._closed or self._is_closing():
			self._complete(waiter, error=ClientClosedError("access_token"))
			return
		if reconsider_guest:
			self._guest = False
		if self._active:
			self._waiters.append(waiter)
			return
		if self._guest:
			self._complete(waiter, value=None)
			return

		self._waiters.append(waiter)
		self._active = True
		if self._session_ready:
			self._start_access_token()
			return
		try:
			refresh_token = self._read_refresh_token()
		except Exception as error:
			self._fail(error)
			return
		if refresh_token:
			self._start_restore(refresh_token)
		else:
			self._start_prompt()

	def _call_client(self, method: str, *args, **kwargs):
		if self._client is None:
			with self._state_lock:
				self._client_creation_in_progress = True
			try:
				client = self._client_factory()
			finally:
				with self._state_lock:
					self._client_creation_in_progress = False
			with self._state_lock:
				self._client = client
				if self._close_requested:
					cleanup = self._cleanup_future
					if cleanup is not None:
						self._start_cleanup_once(client, cleanup)
		else:
			client = self._client
		with self._state_lock:
			if self._close_requested:
				raise ClientClosedError("access_token")
			return getattr(client, method)(*args, **kwargs)

	def _is_closing(self) -> bool:
		with self._state_lock:
			return self._close_requested

	def _start_restore(self, refresh_token: str) -> None:
		try:
			future = self._call_client("restore", refresh_token)
			self._watch(future, self._restore_succeeded)
		except Exception as error:
			self._fail(error)

	def _restore_succeeded(self, _result: object) -> None:
		self._session_ready = True
		self._start_access_token()

	def _start_access_token(self) -> None:
		try:
			future = self._call_client("get_access_token", auto_login=False)
			self._watch(future, self._token_succeeded)
		except Exception as error:
			self._fail(error)

	def _start_prompt(self) -> None:
		try:
			choice = self._prompt_login()
		except Exception as error:
			self._fail(error)
			return
		if choice == "guest":
			self._guest = True
			self._finish(value=None)
		elif choice == "cancel":
			self._finish(error=CancelledError())
		elif choice == "login":
			try:
				future = self._call_client("login")
				self._watch(future, self._login_succeeded)
			except Exception as error:
				self._fail(error)
		else:
			self._fail(ValueError(f"unknown login choice: {choice!r}"))

	def _login_succeeded(self, _result: object) -> None:
		self._session_ready = True
		self._start_access_token()

	def _token_succeeded(self, access_token: str) -> None:
		try:
			future = self._call_client("get_refresh_token")
			self._watch(future, lambda refresh: self._refresh_succeeded(access_token, refresh))
		except Exception as error:
			self._fail(error)

	def _refresh_succeeded(self, access_token: str, refresh_token: str | None) -> None:
		try:
			self._save_refresh_token(refresh_token)
		except Exception as error:
			self._fail(error)
		else:
			self._finish(value=access_token)

	def _watch(self, future: Future, succeeded: Callable[[object], None]) -> None:
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
						return

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
				self._fail(error)
			else:
				succeeded(value)

		future.add_done_callback(completed)

	def _fail(self, error: Exception) -> None:
		if isinstance(error, RestoreError) and error.code == "refresh_rejected":
			self._session_ready = False
			try:
				self._save_refresh_token(None)
			except Exception as save_error:
				self._finish(error=save_error)
				return
			self._start_prompt()
			return
		if isinstance(error, TokenUnavailableError) and error.code in {
			"refresh_rejected",
			"refresh_unavailable",
		}:
			if error.code == "refresh_rejected":
				self._session_ready = False
				try:
					self._save_refresh_token(None)
				except Exception as save_error:
					self._finish(error=save_error)
					return
			self._start_prompt()
			return
		self._finish(error=error)

	def _finish(self, *, value: str | None = None, error: Exception | None = None) -> None:
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
