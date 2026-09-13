from lib.coseeing_auth import CoseeingAuthSession
import lib.coseeing_auth as auth_module
from coseeing_auth import LoginError, RestoreError, TokenUnavailableError, TokenValidationError
from coseeing_auth.errors import ClientClosedError
from concurrent.futures import CancelledError
import shutil
import struct
import subprocess
import sys
from threading import Event, Thread
from pathlib import Path

import pytest

from coseeing_auth_helpers import AuthHarness, FakeAuth


def test_guest_is_remembered_until_reconsidered():
	h = AuthHarness(CoseeingAuthSession)
	first = h.session.get_access_token()
	h.drain()
	assert first.result(timeout=1) is None
	second = h.session.get_access_token()
	h.drain()
	assert second.result(timeout=1) is None
	assert h.prompts == 1
	third = h.session.get_access_token(reconsider_guest=True)
	h.drain()
	assert third.result(timeout=1) is None
	assert h.prompts == 2
	assert h.auth is None


def test_client_is_constructed_lazily_for_guest():
	h = AuthHarness(CoseeingAuthSession)
	result = h.session.get_access_token()
	h.drain()
	assert result.result(timeout=1) is None
	assert h.auth is None


def test_auth_errors_import_after_runtime_dependency_preparation(tmp_path):
	addon = tmp_path / "addon"
	lib = addon / "lib"
	architecture = "win32" if struct.calcsize("P") == 4 else "win_amd64"
	deps = addon / "package" / "_coseeing_auth_deps" / (
		f"py{sys.version_info.major}{sys.version_info.minor}-{architecture}"
	)
	lib.mkdir(parents=True)
	deps.mkdir(parents=True)
	shutil.copy2(Path("addon/globalPlugins/WordBridge/lib/coseeing_auth.py"), lib / "coseeing_auth.py")
	shutil.copy2(Path("addon/globalPlugins/WordBridge/lib/__init__.py"), lib / "__init__.py")
	(deps / "runtime_marker.py").write_text("READY = True\n", encoding="utf-8")
	(deps / "coseeing_auth").mkdir()
	(deps / "coseeing_auth" / "errors.py").write_text(
		"from runtime_marker import READY\n"
		"class ClientClosedError(Exception):\n pass\n"
		"class RestoreError(Exception):\n pass\n"
		"class TokenUnavailableError(Exception):\n pass\n",
		encoding="utf-8",
	)
	(deps / "coseeing_auth" / "__init__.py").write_text(
		"from runtime_marker import READY\nfrom .errors import *\n", encoding="utf-8"
	)
	code = """
import sys
import struct
sys.platform = "win32"
sys.path.insert(0, sys.argv[1])
architecture = "win32" if struct.calcsize("P") == 4 else "win_amd64"
from lib.coseeing_auth import CoseeingAuthSession
assert CoseeingAuthSession
"""
	subprocess.run([sys.executable, "-S", "-c", code, str(addon)], check=True, capture_output=True, text=True)


@pytest.mark.parametrize(("pointer_size", "expected_architecture"), ((4, "win32"), (8, "win_amd64")))
def test_runtime_dependency_path_selects_pointer_width(monkeypatch, pointer_size, expected_architecture):
	monkeypatch.setattr(auth_module.sys, "platform", "win32")
	monkeypatch.setattr(auth_module.struct, "calcsize", lambda format_code: pointer_size)
	assert auth_module._auth_dependency_path().name == (
		f"py{auth_module.sys.version_info.major}{auth_module.sys.version_info.minor}-{expected_architecture}"
	)


def test_restore_persists_rotated_refresh_before_completing():
	h = AuthHarness(CoseeingAuthSession, refresh="old")
	result = h.session.get_access_token()
	h.drain()
	assert h.auth.calls[0] == ("restore", ("old",), {})
	h.resolve(object())
	h.resolve("access")
	assert not result.done()
	h.resolve("rotated")
	assert result.result(timeout=1) == "access"
	assert h.saved == "rotated"
	assert h.prompts == 0


def test_login_saves_refresh_and_returns_access():
	h = AuthHarness(CoseeingAuthSession, choice="login")
	result = h.session.get_access_token()
	h.drain()
	assert h.auth.calls[0][0] == "login"
	h.resolve(object())
	h.resolve("access")
	h.resolve("refresh")
	assert result.result(timeout=1) == "access"
	assert h.saved == "refresh"
	assert all(call[2].get("auto_login") is False for call in h.auth.calls if call[0] == "get_access_token")


def test_ready_session_reuses_client_without_prompting():
	h = AuthHarness(CoseeingAuthSession, choice="login")
	_login_session(h)
	result = h.session.get_access_token()
	h.drain()
	h.resolve("access-again")
	h.resolve("refresh-again")
	assert result.result(timeout=1) == "access-again"
	assert h.prompts == 1
	assert h.auth.calls[0] == ("get_access_token", (), {"auto_login": False})


def test_overlapping_live_waiters_receive_the_same_result():
	h = AuthHarness(CoseeingAuthSession, refresh="old")
	first = h.session.get_access_token()
	h.drain()
	second = h.session.get_access_token()
	h.drain()
	assert not first.done()
	assert not second.done()
	assert h.auth.calls == [("restore", ("old",), {})]
	h.resolve(object())
	h.resolve("access")
	h.resolve("refresh")
	assert first.result(timeout=1) == "access"
	assert second.result(timeout=1) == "access"


@pytest.mark.parametrize(
	"code,prompted,stored",
	[("refresh_rejected", True, None), ("token_endpoint_network_error", False, "old")],
)
def test_restore_failure_classification(code, prompted, stored):
	h = AuthHarness(CoseeingAuthSession, refresh="old")
	result = h.session.get_access_token()
	h.drain()
	h.reject(RestoreError("synthetic", code=code))
	assert h.saved == stored
	assert bool(h.prompts) is prompted
	if prompted:
		assert result.result(timeout=1) is None
	else:
		with pytest.raises(RestoreError):
			result.result(timeout=1)


def _login_session(h):
	result = h.session.get_access_token()
	h.drain()
	h.resolve(object())
	h.resolve("access")
	h.resolve("refresh")
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
	h = AuthHarness(CoseeingAuthSession, refresh="old")
	result = h.session.get_access_token()
	h.drain()
	h.reject(RestoreError("synthetic", code="refresh_unavailable"))
	with pytest.raises(RestoreError):
		result.result(timeout=1)
	assert h.prompts == 0


def test_token_validation_error_is_returned_without_prompt():
	h = AuthHarness(CoseeingAuthSession, choice="login")
	result = h.session.get_access_token()
	h.drain()
	h.resolve(object())
	h.reject(TokenValidationError("synthetic"))
	with pytest.raises(TokenValidationError):
		result.result(timeout=1)
	assert h.prompts == 1


def test_login_error_is_returned_without_retrying_login():
	h = AuthHarness(CoseeingAuthSession, choice="login")
	result = h.session.get_access_token()
	h.drain()
	h.reject(LoginError("synthetic", code="callback_timeout"))
	with pytest.raises(LoginError):
		result.result(timeout=1)
	assert [call[0] for call in h.auth.calls].count("login") == 1


def test_pending_login_future_cancellation_reaches_caller():
	h = AuthHarness(CoseeingAuthSession, choice="login")
	result = h.session.get_access_token()
	h.drain()
	assert h.auth.pending[0].cancel()
	h.drain()
	with pytest.raises(CancelledError):
		result.result(timeout=1)


def test_save_failure_is_returned_to_waiter():
	h = AuthHarness(CoseeingAuthSession, choice="login", save_error=OSError("disk"))
	result = h.session.get_access_token()
	h.drain()
	h.resolve(object())
	h.resolve("access")
	h.resolve("refresh")
	with pytest.raises(OSError):
		result.result(timeout=1)


def test_overlapping_callers_share_one_operation_and_cancel_independently():
	h = AuthHarness(CoseeingAuthSession, refresh="old")
	first = h.session.get_access_token()
	h.drain()
	second = h.session.get_access_token()
	assert second.cancel()
	h.drain()
	assert h.auth.calls == [("restore", ("old",), {})]
	h.resolve(object())
	h.resolve("access")
	h.resolve("refresh")
	assert first.result(timeout=1) == "access"
	assert second.cancelled()


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
	assert h.prompts == 1


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
		read_refresh_token=lambda: "old",
		save_refresh_token=lambda value: None,
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
		read_refresh_token=lambda: "old",
		save_refresh_token=lambda value: None,
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
		read_refresh_token=lambda: None,
		save_refresh_token=lambda value: None,
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
	assert auth.calls == [("login", (), {}), ("close", (), {})]


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
		read_refresh_token=lambda: "old",
		save_refresh_token=lambda value: None,
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
	assert [call[0] for call in auth.calls] == ["restore", "restore"]
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
		read_refresh_token=lambda: "old",
		save_refresh_token=lambda value: None,
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
		read_refresh_token=lambda: "old",
		save_refresh_token=lambda value: None,
		prompt_login=lambda: "guest",
	).get_access_token()
	with pytest.raises(OSError, match="factory"):
		result.result(timeout=1)


def test_sync_client_submission_failure_completes_waiter():
	class BrokenAuth:
		def restore(self, token):
			raise OSError("submit")

	result = CoseeingAuthSession(
		client_factory=BrokenAuth,
		post_ui=lambda fn, *args: fn(*args),
		read_refresh_token=lambda: "old",
		save_refresh_token=lambda value: None,
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
		read_refresh_token=lambda: None,
		save_refresh_token=lambda value: None,
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


def test_cancel_prompt_completes_with_cancelled_error():
	h = AuthHarness(CoseeingAuthSession, choice="cancel")
	result = h.session.get_access_token()
	h.drain()
	with pytest.raises(CancelledError):
		result.result(timeout=1)
	assert h.auth is None
