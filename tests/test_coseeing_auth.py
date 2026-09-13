from lib.coseeing_auth import CoseeingAuthSession
from coseeing_auth import LoginError, RestoreError, TokenUnavailableError, TokenValidationError
from coseeing_auth.errors import ClientClosedError
from concurrent.futures import CancelledError

import pytest

from coseeing_auth_helpers import AuthHarness


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
	assert h.auth.calls == []


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
	h = AuthHarness(CoseeingAuthSession, choice="login")
	result = h.session.get_access_token()
	h.drain()
	cleanup = h.session.close()
	with pytest.raises(ClientClosedError):
		result.result(timeout=1)
	assert cleanup.result(timeout=1) is None
	assert [call[0] for call in h.auth.calls].count("close") == 1
	assert h.session.close() is cleanup
	h.resolve(object())
	assert h.prompts == 1


def test_close_before_ui_drain_does_not_prompt_or_create_client():
	h = AuthHarness(CoseeingAuthSession)
	result = h.session.get_access_token()
	cleanup = h.session.close()
	h.drain()
	with pytest.raises(ClientClosedError):
		result.result(timeout=1)
	assert cleanup.result(timeout=1) is None
	assert h.auth.calls == []
	assert h.prompts == 0


def test_cancel_prompt_completes_with_cancelled_error():
	h = AuthHarness(CoseeingAuthSession, choice="cancel")
	result = h.session.get_access_token()
	h.drain()
	with pytest.raises(CancelledError):
		result.result(timeout=1)
	assert h.auth.calls == []
