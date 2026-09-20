import sys
import types


class OAuthError(Exception):
	def __init__(self, *args, error=None, **kwargs):
		super().__init__(*args)
		self.error = error


class AuthError(Exception):
	def __init__(self, message, *, code=None, **kwargs):
		super().__init__(message)
		self.code = code


class LoginError(AuthError):
	pass


class RestoreError(AuthError):
	pass


class TokenUnavailableError(AuthError):
	pass


class TokenValidationError(AuthError):
	pass


class ClientClosedError(AuthError):
	pass


addon_handler = types.ModuleType("addonHandler")
addon_handler.initTranslation = lambda: None
authlib = types.ModuleType("_wb_vendor.authlib")
authlib_integrations = types.ModuleType("_wb_vendor.authlib.integrations")
authlib_base_client = types.ModuleType("_wb_vendor.authlib.integrations.base_client")
authlib_errors = types.ModuleType("_wb_vendor.authlib.integrations.base_client.errors")
authlib_errors.OAuthError = OAuthError
coseeing_auth = types.ModuleType("_wb_vendor.coseeing_auth")
coseeing_errors = types.ModuleType("_wb_vendor.coseeing_auth.errors")
for error in (LoginError, RestoreError, TokenUnavailableError, TokenValidationError, ClientClosedError):
	setattr(coseeing_auth, error.__name__, error)
	setattr(coseeing_errors, error.__name__, error)
sys.modules.update({
	"addonHandler": addon_handler,
	"_wb_vendor.authlib": authlib,
	"_wb_vendor.authlib.integrations": authlib_integrations,
	"_wb_vendor.authlib.integrations.base_client": authlib_base_client,
	"_wb_vendor.authlib.integrations.base_client.errors": authlib_errors,
	"_wb_vendor.coseeing_auth": coseeing_auth,
	"_wb_vendor.coseeing_auth.errors": coseeing_errors,
})

from lib.coseeing_auth import AuthSessionState, CoseeingAuthSession
import lib.coseeing_auth as auth_module

for module_name in (
	"addonHandler", "_wb_vendor.authlib", "_wb_vendor.authlib.integrations",
	"_wb_vendor.authlib.integrations.base_client",
	"_wb_vendor.authlib.integrations.base_client.errors", "_wb_vendor.coseeing_auth",
	"_wb_vendor.coseeing_auth.errors",
):
	sys.modules.pop(module_name, None)
from concurrent.futures import CancelledError, Future
import shutil
import subprocess
import sys
from threading import Event, Thread, current_thread
import threading
from pathlib import Path

import pytest

from lib import vendor
from coseeing_auth_helpers import AuthHarness, FakeAuth


def test_guest_is_remembered_until_reconsidered():
	h = AuthHarness(CoseeingAuthSession)
	first = h.session.get_access_token()
	h.drain()
	h.resolve(None)
	assert first.result(timeout=1) is None
	second = h.session.get_access_token()
	h.drain()
	assert second.result(timeout=1) is None
	assert h.prompts == 1
	third = h.session.get_access_token(reconsider_guest=True)
	h.drain()
	h.resolve(None)
	assert third.result(timeout=1) is None
	assert h.prompts == 2
	assert h.auth is not None


def test_auth_error_classes_bind_when_the_sandbox_resolves_the_bundle(tmp_path):
	"""Rewritten for the sandbox (R03 ruling P2).

	The old test faked bare `authlib`/`coseeing_auth` modules and relied on
	`_prepare_auth_dependencies()`'s sys.path insertion, which R03 removed.
	This installs the real `_wb_vendor` sandbox against a fabricated bundle
	tree -- the shape `vendor.default_roots()` expects, a runtime-specific
	`authlib` under `_coseeing_auth_deps/py313-win_amd64` and a
	runtime-independent `coseeing_auth` at the package root -- and asserts
	`lib.coseeing_auth`'s error classes bind to real classes rather than the
	unavailable placeholders.
	"""
	addon = tmp_path / "addon"
	lib = addon / "lib"
	package = addon / "package"
	deps = package / "_coseeing_auth_deps" / "py313-win_amd64"
	auth_pkg = package / "coseeing_auth"
	authlib_base_client = deps / "authlib" / "integrations" / "base_client"
	lib.mkdir(parents=True)
	auth_pkg.mkdir(parents=True)
	authlib_base_client.mkdir(parents=True)

	shutil.copy2(Path("addon/globalPlugins/WordBridge/lib/coseeing_auth.py"), lib / "coseeing_auth.py")
	shutil.copy2(Path("addon/globalPlugins/WordBridge/lib/__init__.py"), lib / "__init__.py")
	shutil.copy2(Path("addon/globalPlugins/WordBridge/lib/vendor.py"), lib / "vendor.py")

	(auth_pkg / "errors.py").write_text(
		"class ClientClosedError(Exception):\n\tpass\n"
		"class RestoreError(Exception):\n\tpass\n"
		"class TokenUnavailableError(Exception):\n\tpass\n"
		"class TokenValidationError(Exception):\n\tpass\n",
		encoding="utf-8",
	)
	(auth_pkg / "__init__.py").write_text("from .errors import *\n", encoding="utf-8")

	(deps / "authlib" / "__init__.py").write_text("", encoding="utf-8")
	(deps / "authlib" / "integrations" / "__init__.py").write_text("", encoding="utf-8")
	(authlib_base_client / "__init__.py").write_text("", encoding="utf-8")
	(authlib_base_client / "errors.py").write_text(
		"class OAuthError(Exception):\n\tpass\n", encoding="utf-8"
	)

	code = """
	import sys
	import types
	sys.platform = "win32"
	sys.version_info = (3, 13, 0)
	sys.path.insert(0, sys.argv[1])
	addon_handler = types.ModuleType("addonHandler")
	addon_handler.initTranslation = lambda: None
	sys.modules["addonHandler"] = addon_handler
	from lib import vendor
	vendor.install(vendor.default_roots(sys.argv[2]))
	import lib.coseeing_auth as module
	assert module.AUTH_AVAILABLE is True, module._AUTH_IMPORT_ERROR
	assert module.OAuthError.__module__.startswith("_wb_vendor.")
	assert issubclass(module.OAuthError, Exception)
	assert issubclass(module.ClientClosedError, Exception)
	assert issubclass(module.RestoreError, Exception)
	assert issubclass(module.TokenUnavailableError, Exception)
	assert issubclass(module.TokenValidationError, Exception)
	"""
	subprocess.run(
		[sys.executable, "-S", "-c", code, str(addon), str(package)],
		check=True, capture_output=True, text=True,
	)


def test_default_roots_selects_the_windows_deps_root_for_a_supported_runtime(monkeypatch):
	"""Rewritten for the sandbox (R03 ruling P2): runtime selection now lives
	in `vendor.default_roots()`, not the deleted `_auth_dependency_path()`.
	"""
	monkeypatch.setattr(sys, "platform", "win32")
	monkeypatch.setattr(sys, "version_info", (3, 13, 0))
	package_path = Path("addon/globalPlugins/WordBridge/package")

	roots = vendor.default_roots(package_path)

	assert roots[-1] == str(package_path / "_coseeing_auth_deps" / "py313-win_amd64")


def test_saved_session_restore_returns_access_without_manual_refresh_callbacks():
	h = AuthHarness(CoseeingAuthSession)
	result = h.session.get_access_token()
	h.drain()
	assert h.auth.calls == [("restore_saved_session", (), {})]
	h.resolve(object())
	h.resolve("access")
	assert result.result(timeout=1) == "access"
	assert [call[0] for call in h.auth.calls] == [
		"restore_saved_session", "get_access_token",
	]
	assert h.prompts == 0


def test_missing_saved_session_prompts_without_manual_token_access():
	h = AuthHarness(CoseeingAuthSession, choice="guest")
	result = h.session.get_access_token()
	h.drain()
	h.resolve(None)
	assert result.result(timeout=1) is None
	assert h.prompts == 1
	assert h.auth.calls == [("restore_saved_session", (), {})]


def test_login_returns_access_without_requesting_refresh_token():
	h = AuthHarness(CoseeingAuthSession, choice="login")
	result = h.session.get_access_token()
	h.drain()
	h.resolve(None)
	assert h.auth.calls[-1][0] == "login"
	h.resolve(object())
	h.resolve("access")
	assert result.result(timeout=1) == "access"
	assert "get_refresh_token" not in [call[0] for call in h.auth.calls]
	assert all(call[2].get("auto_login") is False for call in h.auth.calls if call[0] == "get_access_token")


def test_ready_session_reuses_client_without_prompting():
	h = AuthHarness(CoseeingAuthSession, choice="login")
	_login_session(h)
	result = h.session.get_access_token()
	h.drain()
	h.resolve("access-again")
	assert result.result(timeout=1) == "access-again"
	assert h.prompts == 1
	assert h.auth.calls[0] == ("get_access_token", (), {"auto_login": False})


def test_overlapping_live_waiters_receive_the_same_result():
	h = AuthHarness(CoseeingAuthSession)
	first = h.session.get_access_token()
	h.drain()
	second = h.session.get_access_token()
	h.drain()
	assert not first.done()
	assert not second.done()
	assert h.auth.calls == [("restore_saved_session", (), {})]
	h.resolve(object())
	h.resolve("access")
	assert first.result(timeout=1) == "access"
	assert second.result(timeout=1) == "access"


@pytest.mark.parametrize(
"code,prompted",
	[("refresh_rejected", True), ("token_endpoint_network_error", False)],
)
def test_restore_failure_classification(code, prompted):
	h = AuthHarness(CoseeingAuthSession)
	result = h.session.get_access_token()
	h.drain()
	h.reject(RestoreError("synthetic", code=code))
	assert bool(h.prompts) is prompted
	if prompted:
		assert result.result(timeout=1) is None
	else:
		with pytest.raises(RestoreError):
			result.result(timeout=1)


def _login_session(h):
	result = h.session.get_access_token()
	h.drain()
	h.resolve(None)
	h.resolve(object())
	h.resolve("access")
	assert result.result(timeout=1) == "access"
	h.auth.calls.clear()


@pytest.mark.parametrize("error", [
	TokenUnavailableError("synthetic", code="refresh_rejected"),
	TokenUnavailableError("synthetic", code="refresh_unavailable"),
])
def test_current_session_recovery_errors_prompt_without_login(error):
	h = AuthHarness(CoseeingAuthSession, choice="login")
	_login_session(h)
	h.choice = "guest"
	initial_prompts = h.prompts
	result = h.session.get_access_token()
	h.drain()
	h.reject(error)
	assert result.result(timeout=1) is None
	assert h.prompts == initial_prompts + 1
	assert all(call[0] != "login" for call in h.auth.calls)


def test_restore_refresh_unavailable_is_not_recoverable():
	h = AuthHarness(CoseeingAuthSession)
	result = h.session.get_access_token()
	h.drain()
	h.reject(RestoreError("synthetic", code="refresh_unavailable"))
	with pytest.raises(RestoreError):
		result.result(timeout=1)
	assert h.prompts == 0


def test_silent_invalid_refresh_does_not_prompt():
	h = AuthHarness(CoseeingAuthSession, choice="login")
	result = h.session.get_access_token(silent=True)
	h.drain()
	h.reject(RestoreError("synthetic", code="refresh_rejected"))

	assert result.result(timeout=1) is None
	assert h.prompts == 0


def test_silent_missing_refresh_does_not_prompt():
	h = AuthHarness(CoseeingAuthSession, choice="login")
	result = h.session.get_access_token(silent=True)
	h.drain()
	h.resolve(None)
	assert result.result(timeout=1) is None
	assert h.prompts == 0


def test_successful_restore_marks_shared_auth_state_as_valid():
	state = AuthSessionState()
	h = AuthHarness(CoseeingAuthSession, auth_state=state)
	result = h.session.get_access_token(silent=True)
	h.drain()
	h.resolve(object())
	h.resolve("access")

	assert result.result(timeout=1) == "access"
	assert state.refresh_token_was_valid is True


def test_default_access_token_mode_follows_shared_validity_history(monkeypatch):
	state = AuthSessionState()
	calls = []
	completed = Future()
	completed.set_result(None)

	class Session:
		def get_access_token(self, **kwargs):
			calls.append(kwargs)
			return completed

	monkeypatch.setattr(auth_module, "_auth_state", state)
	monkeypatch.setattr(auth_module, "_get_singleton", lambda: Session())

	auth_module.get_coseeing_access_token()
	state.refresh_token_was_valid = True
	auth_module.get_coseeing_access_token()

	assert calls == [{"reconsider_guest": False, "silent": True}, {"reconsider_guest": False, "silent": False}]


@pytest.mark.parametrize("error", [
	OAuthError(error="invalid_grant"),
	TokenValidationError("synthetic", code="jwt_invalid", operation="access_token"),
	TokenValidationError("synthetic", code="jwt_invalid", operation="id_token"),
	TokenValidationError("synthetic", code="scope_missing", operation="access_token"),
	TokenValidationError("synthetic", code="nonce_mismatch", operation="id_token"),
])
def test_invalid_authentication_error_prompts(error):
	h = AuthHarness(CoseeingAuthSession, choice="login")
	_login_session(h)
	h.choice = "guest"
	initial_prompts = h.prompts
	result = h.session.get_access_token()
	h.drain()
	h.reject(error)
	assert result.result(timeout=1) is None
	assert h.prompts == initial_prompts + 1


def test_unknown_oauth_error_does_not_prompt():
	h = AuthHarness(CoseeingAuthSession, choice="login")
	_login_session(h)
	result = h.session.get_access_token()
	h.drain()
	h.reject(OAuthError(error="server_error"))
	with pytest.raises(OAuthError):
		result.result(timeout=1)
	assert h.prompts == 1


def test_login_error_is_returned_without_retrying_login():
	h = AuthHarness(CoseeingAuthSession, choice="login")
	result = h.session.get_access_token()
	h.drain()
	h.resolve(None)
	h.reject(LoginError("synthetic", code="callback_timeout"))
	with pytest.raises(LoginError):
		result.result(timeout=1)
	assert [call[0] for call in h.auth.calls].count("login") == 1


def test_pending_login_future_cancellation_reaches_caller():
	h = AuthHarness(CoseeingAuthSession, choice="login")
	result = h.session.get_access_token()
	h.drain()
	h.resolve(None)
	assert h.auth.calls[-1][0] == "login"
	assert h.auth.pending[0].cancel()
	h.drain()
	with pytest.raises(CancelledError):
		result.result(timeout=1)


def test_overlapping_callers_share_one_operation_and_cancel_independently():
	h = AuthHarness(CoseeingAuthSession)
	first = h.session.get_access_token()
	h.drain()
	second = h.session.get_access_token()
	assert second.cancel()
	h.drain()
	assert h.auth.calls == [("restore_saved_session", (), {})]
	h.resolve(object())
	h.resolve("access")
	assert first.result(timeout=1) == "access"
	assert second.cancelled()


def test_logout_local_clears_package_state_and_session_flags():
	h = AuthHarness(CoseeingAuthSession)
	h.session._session_ready = True
	h.session._guest = True
	h.session._auth_state.refresh_token_was_valid = True
	result = h.session.logout_local()
	h.drain()
	assert h.auth.calls == [("logout_local", (), {})]
	assert not result.done()
	assert h.session._session_ready is True
	assert h.session._guest is True
	assert h.session._auth_state.refresh_token_was_valid is True
	h.resolve(object())
	assert result.result(timeout=1) is None
	assert h.session._session_ready is False
	assert h.session._guest is False
	assert h.session._auth_state.refresh_token_was_valid is False


def test_logout_local_failure_reaches_caller():
	h = AuthHarness(CoseeingAuthSession)
	h.session._session_ready = True
	h.session._guest = True
	h.session._auth_state.refresh_token_was_valid = True
	result = h.session.logout_local()
	h.drain()
	assert not result.done()
	assert h.session._session_ready is True
	assert h.session._guest is True
	assert h.session._auth_state.refresh_token_was_valid is True
	error = RuntimeError("sanitized persistence failure")
	h.reject(error)
	with pytest.raises(RuntimeError, match="sanitized persistence failure"):
		result.result(timeout=1)
	assert h.session._session_ready is True
	assert h.session._guest is True
	assert h.session._auth_state.refresh_token_was_valid is True


def test_close_completes_waiters_and_cleans_up_client_once():
	h = AuthHarness(CoseeingAuthSession, choice="login", close_blocked=True)
	result = h.session.get_access_token()
	h.drain()
	cleanup = h.session.close()
	h.drain()
	with pytest.raises(ClientClosedError):
		result.result(timeout=1)
	assert h.close_started.wait(timeout=1)
	assert not cleanup.done()
	h.close_release.set()
	assert cleanup.result(timeout=1) is None
	assert [call[0] for call in h.auth.calls].count("close") == 1
	assert h.auth.calls[-1][0] == "close"
	assert h.auth.close_thread_name != "MainThread"
	assert h.session.close() is cleanup
	h.resolve(object())
	assert h.prompts == 0


def test_close_racing_paused_factory_does_not_submit_work_or_leak_client():
	started = Event()
	release = Event()
	created = []
	queue = []

	class Client(FakeAuth):
		pass

	def make_client():
		started.set()
		release.wait(timeout=5)
		client = Client()
		created.append(client)
		return client

	session = CoseeingAuthSession(
		client_factory=make_client,
		post_ui=lambda fn, *args: queue.append((fn, args)),
		prompt_login=lambda: "guest",
	)
	result = session.get_access_token()

	def drain_one():
		fn, args = queue.pop(0)
		fn(*args)

	ui = Thread(target=drain_one)
	ui.start()
	assert started.wait(timeout=1)
	cleanup = session.close()
	release.set()
	ui.join(timeout=1)
	while queue:
		fn, args = queue.pop(0)
		fn(*args)
	with pytest.raises(ClientClosedError):
		result.result(timeout=1)
	assert cleanup.result(timeout=1) is None
	assert created and created[0].calls == [("close", (), {})]


def test_failed_close_schedule_hands_off_client_created_during_factory():
	started = Event()
	release = Event()
	queue = []
	created = []
	post_count = 0

	def post_ui(fn, *args):
		nonlocal post_count
		post_count += 1
		if post_count == 1:
			queue.append((fn, args))
		else:
			raise RuntimeError("UI scheduler stopped")

	def make_client():
		started.set()
		release.wait(timeout=5)
		client = FakeAuth()
		created.append(client)
		return client

	session = CoseeingAuthSession(
		client_factory=make_client,
		post_ui=post_ui,
		prompt_login=lambda: "guest",
	)
	result = session.get_access_token()

	def run_request():
		fn, args = queue.pop(0)
		fn(*args)

	ui = Thread(target=run_request)
	ui.start()
	assert started.wait(timeout=1)
	cleanup = session.close()
	release.set()
	ui.join(timeout=1)
	assert cleanup.result(timeout=1) is None
	with pytest.raises(ClientClosedError):
		result.result(timeout=1)
	assert created and created[0].calls == [("close", (), {})]


def test_close_schedule_failure_retries_ui_transition_for_active_waiter():
	queue = []
	post_count = 0

	def post_ui(fn, *args):
		nonlocal post_count
		post_count += 1
		if post_count in (1, 3):
			queue.append((fn, args))
		elif post_count == 2:
			raise RuntimeError("transient UI scheduler failure")
		else:
			raise AssertionError("unexpected UI scheduling")

	auth = FakeAuth()
	session = CoseeingAuthSession(
		client_factory=lambda: auth,
		post_ui=post_ui,
		prompt_login=lambda: "login",
	)
	result = session.get_access_token()
	fn, args = queue.pop(0)
	fn(*args)
	cleanup = session.close()
	fn, args = queue.pop(0)
	fn(*args)
	with pytest.raises(ClientClosedError):
		result.result(timeout=1)
	assert cleanup.result(timeout=1) is None
	assert auth.calls == [("restore_saved_session", (), {}), ("close", (), {})]


def test_callback_ui_submission_failure_fails_waiters_and_clears_operation():
	queue = []
	post_count = 0

	def post_ui(fn, *args):
		nonlocal post_count
		post_count += 1
		if post_count == 1:
			queue.append((fn, args))
		elif post_count == 2:
			raise RuntimeError("UI scheduler stopped")
		else:
			queue.append((fn, args))

	from coseeing_auth_helpers import FakeAuth
	auth = FakeAuth()
	session = CoseeingAuthSession(
		client_factory=lambda: auth,
		post_ui=post_ui,
		prompt_login=lambda: "guest",
	)
	result = session.get_access_token()
	fn, args = queue.pop(0)
	fn(*args)
	auth.pending.popleft().set_result(object())
	fn, args = queue.pop(0)
	fn(*args)
	with pytest.raises(RuntimeError, match="UI scheduler stopped"):
		result.result(timeout=1)
	second = session.get_access_token()
	fn, args = queue.pop(0)
	fn(*args)
	assert not second.done()
	assert [call[0] for call in auth.calls] == ["restore_saved_session", "restore_saved_session"]
	second.cancel()


def test_repeated_watch_scheduler_failure_is_delivered_on_ui():
	queue = []
	post_count = 0

	def post_ui(fn, *args):
		nonlocal post_count
		post_count += 1
		if post_count in (1, 4):
			queue.append((fn, args))
		else:
			raise RuntimeError("UI scheduler stopped")

	auth = FakeAuth()
	session = CoseeingAuthSession(
		client_factory=lambda: auth,
		post_ui=post_ui,
		prompt_login=lambda: "guest",
	)
	result = session.get_access_token()
	fn, args = queue.pop(0)
	fn(*args)
	auth.pending.popleft().set_result(object())
	fn, args = queue.pop(0)
	fn(*args)
	with pytest.raises(RuntimeError, match="UI scheduler stopped"):
		result.result(timeout=1)


def test_sync_client_factory_failure_completes_waiter():
	result = CoseeingAuthSession(
		client_factory=lambda: (_ for _ in ()).throw(OSError("factory")),
		post_ui=lambda fn, *args: fn(*args),
		prompt_login=lambda: "guest",
	).get_access_token()
	with pytest.raises(OSError, match="factory"):
		result.result(timeout=1)


def test_sync_client_submission_failure_completes_waiter():
	class BrokenAuth:
		def restore_saved_session(self):
			raise OSError("submit")

	result = CoseeingAuthSession(
		client_factory=BrokenAuth,
		post_ui=lambda fn, *args: fn(*args),
		prompt_login=lambda: "guest",
	).get_access_token()
	with pytest.raises(OSError, match="submit"):
		result.result(timeout=1)


def test_close_before_ui_drain_does_not_prompt_or_create_client():
	h = AuthHarness(CoseeingAuthSession)
	result = h.session.get_access_token()
	cleanup = h.session.close()
	h.drain()
	with pytest.raises(ClientClosedError):
		result.result(timeout=1)
	assert cleanup.result(timeout=1) is None
	assert h.auth is None
	assert h.prompts == 0


def test_close_scheduling_failure_does_not_mutate_ui_state_off_thread():
	queue = []
	post_count = 0

	def post_ui(fn, *args):
		nonlocal post_count
		post_count += 1
		if post_count == 1:
			queue.append((fn, args))
		else:
			raise RuntimeError("UI scheduler stopped")

	auth = FakeAuth()
	session = CoseeingAuthSession(
		client_factory=lambda: auth,
		post_ui=post_ui,
		prompt_login=lambda: "guest",
	)
	result = session.get_access_token()
	cleanup = session.close()
	with pytest.raises(RuntimeError, match="UI scheduler stopped"):
		cleanup.result(timeout=1)
	fn, args = queue.pop(0)
	fn(*args)
	with pytest.raises(ClientClosedError):
		result.result(timeout=1)
	assert auth.calls == []


def test_close_schedule_and_retry_failure_finishes_existing_client_waiters_and_reports_error(monkeypatch):
	queue = []
	post_count = 0

	def post_ui(fn, *args):
		nonlocal post_count
		post_count += 1
		if post_count == 1:
			queue.append((fn, args))
		else:
			raise RuntimeError("UI scheduler stopped")

	auth = FakeAuth()
	session = CoseeingAuthSession(
		client_factory=lambda: auth,
		post_ui=post_ui,
		prompt_login=lambda: "login",
	)
	result = session.get_access_token()
	fn, args = queue.pop(0)
	fn(*args)
	second = Future()
	session._request(second, False)
	monkeypatch.setattr(
		session,
		"_finish",
		lambda **kwargs: pytest.fail("close fallback called UI finisher from background thread"),
	)
	cleanup = session.close()
	with pytest.raises(ClientClosedError):
		result.result(timeout=1)
	with pytest.raises(ClientClosedError):
		second.result(timeout=1)
	with pytest.raises(RuntimeError, match="UI scheduler stopped"):
		cleanup.result(timeout=1)
	assert auth.calls == [("restore_saved_session", (), {}), ("close", (), {})]


def test_close_schedule_failure_and_factory_error_finish_waiter_and_cleanup():
	started = Event()
	release = Event()
	queue = []
	post_count = 0

	def post_ui(fn, *args):
		nonlocal post_count
		post_count += 1
		if post_count == 1:
			queue.append((fn, args))
		else:
			raise RuntimeError("UI scheduler stopped")

	def make_client():
		started.set()
		release.wait(timeout=5)
		raise OSError("factory")

	session = CoseeingAuthSession(
		client_factory=make_client,
		post_ui=post_ui,
		prompt_login=lambda: "guest",
	)
	result = session.get_access_token()
	fn, args = queue.pop(0)
	ui = Thread(target=lambda: fn(*args))
	ui.start()
	assert started.wait(timeout=1)
	cleanup = session.close()
	release.set()
	ui.join(timeout=1)
	with pytest.raises(OSError, match="factory"):
		result.result(timeout=1)
	assert cleanup.result(timeout=1) is None


def test_close_schedule_failure_waits_for_admitted_request_client_handoff():
	started = Event()
	release = Event()
	published = Event()
	close_started = Event()
	close_release = Event()
	first_failure = Event()
	second_attempt = Event()
	queue = []
	post_count = 0
	created = []

	def post_ui(fn, *args):
		nonlocal post_count
		post_count += 1
		if post_count == 1:
			queue.append((fn, args))
		elif post_count == 2:
			first_failure.set()
			raise RuntimeError("UI scheduler stopped")
		elif post_count == 3:
			second_attempt.set()
			published.wait(timeout=5)
			raise RuntimeError("UI scheduler stopped")
		else:
			raise RuntimeError("UI scheduler stopped")

	def make_client():
		started.set()
		release.wait(timeout=5)
		client = FakeAuth(close_started, close_release)
		created.append(client)
		published.set()
		return client

	session = CoseeingAuthSession(
		client_factory=make_client,
		post_ui=post_ui,
		prompt_login=lambda: "guest",
	)
	result = session.get_access_token()
	request_thread = Thread(target=lambda: (lambda item: item[0](*item[1]))(queue.pop(0)))
	request_thread.start()
	assert started.wait(timeout=1)
	cleanup_holder = []
	close_thread = Thread(target=lambda: cleanup_holder.append(session.close()))
	close_thread.start()
	assert first_failure.wait(timeout=1)
	with session._state_lock:
		cleanup_before_publication = session._cleanup_future
	assert cleanup_before_publication is not None
	assert not cleanup_before_publication.done()
	assert created == []
	assert second_attempt.wait(timeout=1)
	release.set()
	request_thread.join(timeout=1)
	close_thread.join(timeout=1)
	assert not request_thread.is_alive()
	assert not close_thread.is_alive()
	cleanup = cleanup_holder[0]
	assert close_started.wait(timeout=1)
	assert not cleanup.done()
	with pytest.raises(ClientClosedError):
		result.result(timeout=1)
	close_release.set()
	with pytest.raises(RuntimeError, match="UI scheduler stopped"):
		cleanup.result(timeout=1)
	assert created and created[0].calls == [("close", (), {})]


def test_persistent_watch_scheduler_failure_finishes_waiters_and_clears_operation():
	queue = []
	post_count = 0

	def post_ui(fn, *args):
		nonlocal post_count
		post_count += 1
		if post_count == 1:
			queue.append((fn, args))
		else:
			raise RuntimeError("UI scheduler stopped")

	auth = FakeAuth()
	session = CoseeingAuthSession(
		client_factory=lambda: auth,
		post_ui=post_ui,
		prompt_login=lambda: "guest",
	)
	result = session.get_access_token()
	fn, args = queue.pop(0)
	fn(*args)
	auth.pending.popleft().set_result(object())
	with pytest.raises(RuntimeError, match="UI scheduler stopped"):
		result.result(timeout=1)
	assert not session._active
	assert session._waiters == []


def test_request_admission_is_atomic_with_waiter_drain():
	entered_append = Event()
	release_append = Event()

	class BlockingWaiters(list):
		def append(self, waiter):
			entered_append.set()
			release_append.wait(timeout=1)
			super().append(waiter)

	session = CoseeingAuthSession(
		client_factory=lambda: FakeAuth(),
		post_ui=lambda fn, *args: None,
		prompt_login=lambda: "guest",
	)
	waiter = session.get_access_token()
	session._active = True
	session._waiters = BlockingWaiters()
	request = Thread(target=session._request, args=(waiter, False))
	request.start()
	assert entered_append.wait(timeout=1)
	finisher = Thread(target=session._finish, kwargs={"error": RuntimeError("finished")})
	finisher.start()
	release_append.set()
	request.join(timeout=1)
	finisher.join(timeout=1)
	assert not request.is_alive()
	assert not finisher.is_alive()
	with pytest.raises(RuntimeError, match="finished"):
		waiter.result(timeout=1)
	assert not session._active
	assert session._waiters == []


def test_watch_scheduler_fallback_uses_synchronized_handoff(monkeypatch):
	queue = []
	post_count = 0

	def post_ui(fn, *args):
		nonlocal post_count
		post_count += 1
		if post_count == 1:
			queue.append((fn, args))
		else:
			raise RuntimeError("UI scheduler stopped")

	auth = FakeAuth()
	session = CoseeingAuthSession(
		client_factory=lambda: auth,
		post_ui=post_ui,
		prompt_login=lambda: "guest",
	)
	finish_threads = []
	original_finish = session._finish

	def fail_if_called_from_callback(*, value=None, error=None):
		finish_threads.append(current_thread().name)
		if current_thread() is not threading.main_thread():
			raise AssertionError("background callback called UI finisher")
		original_finish(value=value, error=error)

	monkeypatch.setattr(session, "_finish", fail_if_called_from_callback)
	result = session.get_access_token()
	fn, args = queue.pop(0)
	fn(*args)
	callback = Thread(target=lambda: auth.pending.popleft().set_result(object()))
	callback.start()
	callback.join(timeout=1)
	assert not callback.is_alive()
	with pytest.raises(RuntimeError, match="UI scheduler stopped"):
		result.result(timeout=1)
	assert finish_threads == []


def test_cancel_prompt_completes_with_cancelled_error():
	h = AuthHarness(CoseeingAuthSession, choice="cancel")
	result = h.session.get_access_token()
	h.drain()
	h.resolve(None)
	with pytest.raises(CancelledError):
		result.result(timeout=1)
	assert h.auth is not None
