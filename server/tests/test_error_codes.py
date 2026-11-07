"""Every error the server raises itself carries a code the add-on can speak.

The body is {"detail": <English>, "code": <code>} plus "limit" on length
errors. 401s and FastAPI's own validation 422s keep their old bodies.
"""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.dependencies import get_db
from app.lib.llm import LLMServiceError
from app.models.models import Interaction
from app.package.coseeing_auth.errors import DiscoveryError
from app.user.auth import get_optional_user, get_token_verifier
from app.user.models import User

PAYLOAD = {
	"request": "以經完成",
	"corrector_config_id": "default",
	"language": "zh_traditional",
	"typo_correction_mode": "standard",
	"customized_words": [],
}
DEEPSEEK_KEY = "test-key-deepseek"


@pytest.fixture(autouse=True)
def _clear_overrides():
	yield
	main_module.app.dependency_overrides.clear()


@pytest.fixture
def fake_correction(monkeypatch):
	calls = []

	def _fake(**kwargs):
		calls.append(kwargs)
		return SimpleNamespace(corrected_text="已校正", cost=Decimal("0.000001"))

	monkeypatch.setattr(main_module, "run_typo_correction", _fake)
	return calls


def _client(db, *, user=None, raise_server_exceptions=True):
	def _get_db():
		yield db

	main_module.app.dependency_overrides[get_db] = _get_db
	main_module.app.dependency_overrides[get_optional_user] = lambda: user
	return TestClient(main_module.app, raise_server_exceptions=raise_server_exceptions)


def _user(db, *, quota=1000.0, is_active=True):
	user = User(
		account="codes@example.org",
		name="Codes",
		sso_sub="sub-codes",
		email_verified=True,
		is_active=is_active,
		is_superuser=False,
		quota=quota,
	)
	db.add(user)
	db.commit()
	return user


def _seed(db, *, cost, ip_address=None, user=None):
	now = datetime.now(timezone.utc) - timedelta(minutes=1)
	db.add(
		Interaction(
			request_time=now,
			response_time=now,
			request_content="x",
			response_content="y",
			ip_address=ip_address,
			cost=cost,
			model="deepseek-flash&DeepSeek",
			version="2026.11.1",
			template="Standard_v1",
			user=user,
		),
	)
	db.commit()


def _coded(response):
	body = response.json()
	return response.status_code, body.get("code"), body.get("limit")


# --- length ----------------------------------------------------------------------


def test_guest_text_over_the_guest_limit_is_413(db, fake_correction):
	response = _client(db).post("/proofreader", json=dict(PAYLOAD, request="a" * 129))

	assert _coded(response) == (413, "guest_text_too_long", 128)
	assert fake_correction == []
	assert db.query(Interaction).count() == 0


@pytest.mark.parametrize("signed_in", [False, True], ids=["guest", "user"])
def test_text_over_8000_characters_is_413(db, fake_correction, signed_in):
	# For a guest the universal limit is checked first: signing in would not
	# help with this text.
	user = _user(db) if signed_in else None

	response = _client(db, user=user).post("/proofreader", json=dict(PAYLOAD, request="a" * 8001))

	assert _coded(response) == (413, "text_too_long", 8000)
	assert fake_correction == []


# --- quotas ----------------------------------------------------------------------


def test_guest_ip_quota_is_guest_quota_exceeded(db, fake_correction):
	_seed(db, cost=Decimal("0.06"), ip_address="testclient")

	assert _coded(_client(db).post("/proofreader", json=PAYLOAD)) == (429, "guest_quota_exceeded", None)


def test_guest_global_quota_is_guest_quota_exceeded(db, fake_correction):
	_seed(db, cost=Decimal("0.3"), ip_address="203.0.113.77")

	assert _coded(_client(db).post("/proofreader", json=PAYLOAD)) == (429, "guest_quota_exceeded", None)


def test_user_quota_is_user_quota_exceeded(db, fake_correction):
	user = _user(db, quota=0.05)
	_seed(db, cost=Decimal("0.05"), user=user)

	response = _client(db, user=user).post("/proofreader", json=PAYLOAD)

	assert _coded(response) == (429, "user_quota_exceeded", None)


# --- model -----------------------------------------------------------------------


@pytest.mark.parametrize(
	"model_id",
	["does-not-exist&Nobody", "qwen2&Ollama", "gemini-3.7-flash&Google"],
	ids=["unknown", "inactive", "unlisted"],
)
def test_an_unavailable_model_is_422(db, fake_correction, model_id):
	response = _client(db).post("/proofreader", json=dict(PAYLOAD, corrector_config_id=model_id))

	assert _coded(response) == (422, "model_unavailable", None)
	assert fake_correction == []


# --- the AI service ---------------------------------------------------------------


@pytest.mark.parametrize(
	"kind, code",
	[
		("overloaded", "provider_overloaded"),
		("rate_limited", "provider_rate_limited"),
		("unreachable", "provider_unreachable"),
		("configuration", "provider_configuration"),
		("other", "provider_error"),
	],
)
def test_each_kind_maps_to_its_provider_code(db, monkeypatch, kind, code):
	def _fail(**kwargs):
		raise LLMServiceError(f"raw provider text {DEEPSEEK_KEY}", kind=kind)

	monkeypatch.setattr(main_module, "run_typo_correction", _fail)

	response = _client(db).post("/proofreader", json=PAYLOAD)

	assert _coded(response) == (502, code, None)
	assert "raw provider text" not in response.text
	assert DEEPSEEK_KEY not in response.text
	assert db.query(Interaction).count() == 0


def test_provider_failure_logs_provider_and_kind_but_never_the_key(db, monkeypatch, caplog):
	def _fail(**kwargs):
		raise LLMServiceError(f"Incorrect API key provided: {DEEPSEEK_KEY}", kind="configuration")

	monkeypatch.setattr(main_module, "run_typo_correction", _fail)

	with caplog.at_level(logging.WARNING, logger="app.main"):
		_client(db).post("/proofreader", json=PAYLOAD)

	assert "DeepSeek" in caplog.text
	assert "configuration" in caplog.text
	assert "Incorrect API key provided" in caplog.text
	assert DEEPSEEK_KEY not in caplog.text


def test_a_bug_in_the_ai_call_is_service_error(db, monkeypatch, caplog):
	def _bug(**kwargs):
		raise RuntimeError(f"bug {DEEPSEEK_KEY}")

	monkeypatch.setattr(main_module, "run_typo_correction", _bug)

	with caplog.at_level(logging.ERROR, logger="app.main"):
		response = _client(db).post("/proofreader", json=PAYLOAD)

	assert _coded(response) == (500, "service_error", None)
	assert "bug" not in response.text
	assert "Traceback" in caplog.text
	assert "RuntimeError" in caplog.text
	assert DEEPSEEK_KEY not in caplog.text


def _failing_commit(db, monkeypatch, failing_call):
	real_commit = db.commit
	commits = []

	def _commit():
		commits.append(None)
		if len(commits) == failing_call:
			raise RuntimeError("db exploded")
		return real_commit()

	monkeypatch.setattr(db, "commit", _commit)
	return commits


def test_a_failed_quota_transaction_end_is_service_error(db, fake_correction, monkeypatch):
	_failing_commit(db, monkeypatch, failing_call=1)

	response = _client(db).post("/proofreader", json=PAYLOAD)

	assert _coded(response) == (500, "service_error", None)
	assert fake_correction == []


def test_a_failed_write_is_service_error(db, fake_correction, monkeypatch):
	commits = _failing_commit(db, monkeypatch, failing_call=2)

	response = _client(db).post("/proofreader", json=PAYLOAD)

	assert _coded(response) == (500, "service_error", None)
	assert len(commits) == 2


def test_an_unexpected_error_elsewhere_is_service_error(db, fake_correction, monkeypatch):
	def _boom(*args):
		raise ValueError("diff exploded")

	monkeypatch.setattr(main_module, "strings_diff", _boom)

	response = _client(db, raise_server_exceptions=False).post("/proofreader", json=PAYLOAD)

	assert _coded(response) == (500, "service_error", None)
	assert "exploded" not in response.text


# --- sign-in ------------------------------------------------------------------------


class _Verifier:
	def __init__(self, error=None, sub="sub-codes"):
		self.error = error
		self.sub = sub

	def verify_access_token(self, token, required_scopes=()):
		if self.error is not None:
			raise self.error
		return SimpleNamespace(subject=self.sub)


def _signed_in_client(db, verifier):
	def _get_db():
		yield db

	main_module.app.dependency_overrides[get_db] = _get_db
	main_module.app.dependency_overrides[get_token_verifier] = lambda: verifier
	return TestClient(main_module.app)


def test_an_unavailable_sso_issuer_is_sso_unavailable(db, fake_correction):
	verifier = _Verifier(error=DiscoveryError("down", code="discovery_network_error", retryable=True))

	response = _signed_in_client(db, verifier).post(
		"/proofreader",
		json=PAYLOAD,
		headers={"Authorization": "Bearer t"},
	)

	assert _coded(response) == (503, "sso_unavailable", None)


@pytest.mark.parametrize("route", ["/proofreader", "/feedback"])
def test_a_disabled_account_is_account_disabled(db, fake_correction, route):
	_user(db, is_active=False)
	body = PAYLOAD if route == "/proofreader" else {"interaction_id": 1, "review_content": "x"}

	response = _signed_in_client(db, _Verifier()).post(
		route,
		json=body,
		headers={"Authorization": "Bearer t"},
	)

	assert _coded(response) == (403, "account_disabled", None)


def test_401_bodies_have_no_code(db, fake_correction):
	response = _signed_in_client(db, _Verifier()).post(
		"/proofreader",
		json=PAYLOAD,
		headers={"Authorization": "Basic abc"},
	)

	assert response.status_code == 401
	assert response.json() == {"detail": "Authorization header must be a well-formed Bearer credential"}


def test_other_validation_errors_keep_fastapi_422(db, fake_correction):
	response = _client(db).post("/proofreader", json=dict(PAYLOAD, language="en"))

	assert response.status_code == 422
	assert "code" not in response.json()
