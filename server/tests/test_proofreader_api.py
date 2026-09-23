from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.dependencies import get_db
from app.models.models import Interaction
from app.user.auth import get_optional_user
from app.user.models import User

PAYLOAD = {
	"request": "以經完成",
	"corrector_config_id": "default",
	"language": "zh_traditional",
	"typo_correction_mode": "standard",
	"customized_words": [],
}


def _override_get_db(session):
	def _get_db():
		try:
			yield session
		finally:
			pass

	return _get_db


@pytest.fixture(autouse=True)
def _clear_overrides():
	# main.app is a module-level singleton reused across the whole test
	# session -- keep each test's dependency overrides from bleeding into
	# the next one.
	yield
	main_module.app.dependency_overrides.clear()


@pytest.fixture
def fake_run_typo_correction(monkeypatch):
	calls = []

	def _fake(**kwargs):
		calls.append(kwargs)
		return SimpleNamespace(corrected_text="已校正", cost=Decimal("0.000001"))

	monkeypatch.setattr(main_module, "run_typo_correction", _fake)
	return calls


def _client(db, *, user=None):
	main_module.app.dependency_overrides[get_db] = _override_get_db(db)
	main_module.app.dependency_overrides[get_optional_user] = lambda: user
	return TestClient(main_module.app)


def _seed_interaction(db, *, cost, ip_address=None, user=None, age=timedelta(minutes=1)):
	now = datetime.now(timezone.utc) - age
	interaction = Interaction(
		request_time=now,
		response_time=now,
		request_content="x",
		response_content="y",
		ip_address=ip_address,
		cost=cost,
		model="deepseek-v4-flash&DeepSeek",
		version="20260425",
		user=user,
	)
	interaction.category = "1"
	db.add(interaction)
	db.commit()
	return interaction


# --- import sanity ----------------------------------------------------------


def test_app_imports():
	assert main_module.app is not None


# --- happy paths -------------------------------------------------------------


def test_guest_default_model_success(db, fake_run_typo_correction, monkeypatch):
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	client = _client(db)

	response = client.post("/proofreader", json=PAYLOAD)

	assert response.status_code == 200
	body = response.json()
	assert body["response"] == "已校正"
	assert isinstance(body["diff"], list)
	assert body["request"] == PAYLOAD["request"]
	assert body["cost"] == "0.000001"
	assert body["interaction_id"] is not None

	stored = db.query(Interaction).filter(Interaction.id == body["interaction_id"]).one()
	assert stored.model == "deepseek-v4-flash&DeepSeek"
	assert stored.user_id is None
	assert stored.cost == Decimal("0.000001")


def test_explicit_model_success(db, fake_run_typo_correction, monkeypatch):
	monkeypatch.setenv("OPENAI_API_KEY", "test-key")
	client = _client(db)
	payload = dict(PAYLOAD, corrector_config_id="gpt-5.6-luna&OpenAI")

	response = client.post("/proofreader", json=payload)

	assert response.status_code == 200
	assert fake_run_typo_correction[0]["provider_name"] == "OpenAI"
	assert fake_run_typo_correction[0]["model_name"] == "gpt-5.6-luna"

	stored = db.query(Interaction).filter(Interaction.id == response.json()["interaction_id"]).one()
	assert stored.model == "gpt-5.6-luna&OpenAI"


def test_run_typo_correction_receives_all_expected_arguments(db, fake_run_typo_correction, monkeypatch):
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	client = _client(db)
	payload = dict(PAYLOAD, customized_words=["專有名詞", "WordBridge"])

	response = client.post("/proofreader", json=payload)

	assert response.status_code == 200
	assert len(fake_run_typo_correction) == 1
	call = fake_run_typo_correction[0]
	assert call["provider_name"] == "DeepSeek"
	assert call["model_name"] == "deepseek-v4-flash"
	assert call["language"] == "zh_traditional"
	assert call["corrector_mode"] == "standard"
	assert call["template_name"] == "Standard_v1.json"
	assert call["customized_words"] == ["專有名詞", "WordBridge"]
	assert call["batch_mode"] is True
	assert call["retries"] == 2
	assert call["backoff"] == 1


# --- validation ---------------------------------------------------------------


def test_invalid_mode_is_422(db, fake_run_typo_correction, monkeypatch):
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	client = _client(db)
	payload = dict(PAYLOAD, typo_correction_mode="not-a-real-mode")

	response = client.post("/proofreader", json=payload)

	assert response.status_code == 422
	assert db.query(Interaction).count() == 0


def test_missing_required_field_is_422(db, fake_run_typo_correction):
	client = _client(db)
	payload = dict(PAYLOAD)
	del payload["request"]

	response = client.post("/proofreader", json=payload)

	assert response.status_code == 422


def test_empty_request_is_422(db, fake_run_typo_correction):
	client = _client(db)
	payload = dict(PAYLOAD, request="")

	response = client.post("/proofreader", json=payload)

	assert response.status_code == 422


def test_invalid_language_is_422(db, fake_run_typo_correction):
	client = _client(db)
	payload = dict(PAYLOAD, language="en")

	response = client.post("/proofreader", json=payload)

	assert response.status_code == 422


# --- model resolution ----------------------------------------------------------


def test_disabled_model_is_404(db, fake_run_typo_correction):
	client = _client(db)
	payload = dict(PAYLOAD, corrector_config_id="qwen2&Ollama")

	response = client.post("/proofreader", json=payload)

	assert response.status_code == 404
	assert db.query(Interaction).count() == 0


def test_unknown_model_is_404(db, fake_run_typo_correction):
	client = _client(db)
	payload = dict(PAYLOAD, corrector_config_id="does-not-exist&Nobody")

	response = client.post("/proofreader", json=payload)

	assert response.status_code == 404
	assert db.query(Interaction).count() == 0


# --- provider/credential failures ----------------------------------------------


def test_missing_api_key_is_5xx_and_writes_no_interaction(db, fake_run_typo_correction, monkeypatch):
	monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
	client = _client(db)

	response = client.post("/proofreader", json=PAYLOAD)

	assert response.status_code >= 500
	assert "test-key" not in response.text
	assert db.query(Interaction).count() == 0
	assert fake_run_typo_correction == []


def test_provider_failure_is_5xx_and_writes_no_interaction(db, monkeypatch):
	monkeypatch.setenv("DEEPSEEK_API_KEY", "super-secret-key")

	def _boom(**kwargs):
		raise RuntimeError("provider exploded")

	monkeypatch.setattr(main_module, "run_typo_correction", _boom)
	client = _client(db)

	response = client.post("/proofreader", json=PAYLOAD)

	assert response.status_code >= 500
	assert "super-secret-key" not in response.text
	assert db.query(Interaction).count() == 0


def test_db_commit_failure_is_5xx_and_writes_no_interaction(db, fake_run_typo_correction, monkeypatch):
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	client = _client(db)

	before_count = db.query(Interaction).count()

	def _boom():
		raise RuntimeError("db exploded")

	monkeypatch.setattr(db, "commit", _boom)

	response = client.post("/proofreader", json=PAYLOAD)

	assert response.status_code >= 500
	assert "interaction_id" not in response.json()
	assert db.query(Interaction).count() == before_count


# --- IP length guard (Interaction.ip_address is String(45)) -------------------


def test_oversized_forwarded_ip_is_normalized_before_storage(db, fake_run_typo_correction, monkeypatch):
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	client = _client(db)
	oversized_ip = "1" * 200

	response = client.post(
		"/proofreader",
		json=PAYLOAD,
		headers={"X-Forwarded-For": oversized_ip},
	)

	assert response.status_code == 200
	stored = db.query(Interaction).filter(Interaction.id == response.json()["interaction_id"]).one()
	assert len(stored.ip_address) <= 45
	assert stored.ip_address != oversized_ip


def test_oversized_forwarded_ip_still_counts_toward_guest_quota(db, fake_run_typo_correction, monkeypatch):
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	oversized_ip = "2" * 200
	client = _client(db)

	first = client.post(
		"/proofreader",
		json=PAYLOAD,
		headers={"X-Forwarded-For": oversized_ip},
	)
	assert first.status_code == 200

	# Seed the rest of the per-IP quota under whatever normalized value the
	# first request was stored as, so a second oversized-IP request from a
	# guest is still capped rather than silently bypassing the 0.06 limit.
	stored = db.query(Interaction).filter(Interaction.id == first.json()["interaction_id"]).one()
	_seed_interaction(db, cost=Decimal("0.06"), ip_address=stored.ip_address)

	second = client.post(
		"/proofreader",
		json=PAYLOAD,
		headers={"X-Forwarded-For": oversized_ip},
	)

	assert second.status_code == 429


# --- guest quotas ----------------------------------------------------------------


def test_guest_text_over_128_chars_is_429(db, fake_run_typo_correction, monkeypatch):
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	client = _client(db)
	payload = dict(PAYLOAD, request="a" * 129)

	response = client.post("/proofreader", json=payload)

	assert response.status_code == 429
	assert db.query(Interaction).count() == 0


def test_guest_text_at_128_chars_is_accepted(db, fake_run_typo_correction, monkeypatch):
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	client = _client(db)
	payload = dict(PAYLOAD, request="a" * 128)

	response = client.post("/proofreader", json=payload)

	assert response.status_code == 200


def test_request_length_under_cap_is_accepted(db, fake_run_typo_correction, monkeypatch):
	# Must be an authenticated user with enough quota -- a guest this long
	# would already be blocked by the separate, tighter 128-char guest limit.
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	user = User(
		account="atcap@example.org", name="AtCap", sso_sub="sub-atcap", email_verified=True,
		is_active=True, is_superuser=False, quota=1000,
	)
	db.add(user)
	db.commit()
	client = _client(db, user=user)
	payload = dict(PAYLOAD, request="a" * main_module.REQUEST_TEXT_MAX_LENGTH)

	response = client.post("/proofreader", json=payload)

	assert response.status_code == 200


def test_guest_over_length_cap_is_422_not_429_and_writes_no_interaction(
	db, fake_run_typo_correction, monkeypatch
):
	# Above the (tighter) guest limit but this asserts the universal cap
	# fires with 422, distinct from the guest-only 429 quota path.
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	client = _client(db)
	payload = dict(PAYLOAD, request="a" * (main_module.REQUEST_TEXT_MAX_LENGTH + 1))

	response = client.post("/proofreader", json=payload)

	assert response.status_code == 422
	assert db.query(Interaction).count() == 0
	assert fake_run_typo_correction == []


def test_authenticated_user_over_length_cap_is_422_not_502_and_writes_no_interaction(
	db, fake_run_typo_correction, monkeypatch
):
	# Above the guest limit (which does not apply to authenticated users) but
	# also above the universal cap -- must still be rejected before ever
	# reaching the provider.
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	user = User(
		account="longtext@example.org", name="LongText", sso_sub="sub-long", email_verified=True,
		is_active=True, is_superuser=False, quota=1000,
	)
	db.add(user)
	db.commit()
	client = _client(db, user=user)
	payload = dict(PAYLOAD, request="a" * (main_module.REQUEST_TEXT_MAX_LENGTH + 1))

	response = client.post("/proofreader", json=payload)

	assert response.status_code == 422
	assert db.query(Interaction).count() == 0
	assert fake_run_typo_correction == []


def test_guest_ip_quota_exact_boundary_is_429(db, fake_run_typo_correction, monkeypatch):
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	# TestClient's default client IP is "testclient" -- seed exactly the
	# per-IP quota for that same IP within the trailing 24h window.
	_seed_interaction(db, cost=Decimal("0.06"), ip_address="testclient")
	client = _client(db)

	response = client.post("/proofreader", json=PAYLOAD)

	assert response.status_code == 429
	assert db.query(Interaction).count() == 1


def test_guest_ip_quota_just_under_boundary_is_accepted(db, fake_run_typo_correction, monkeypatch):
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	_seed_interaction(db, cost=Decimal("0.059999999999"), ip_address="testclient")
	client = _client(db)

	response = client.post("/proofreader", json=PAYLOAD)

	assert response.status_code == 200


def test_guest_global_quota_exact_boundary_is_429_independent_of_ip(db, fake_run_typo_correction, monkeypatch):
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	# Spread 0.3 total cost across other guest IPs -- none of which is the
	# requesting IP, so the per-IP check alone would pass.
	_seed_interaction(db, cost=Decimal("0.1"), ip_address="1.2.3.4")
	_seed_interaction(db, cost=Decimal("0.1"), ip_address="5.6.7.8")
	_seed_interaction(db, cost=Decimal("0.1"), ip_address="9.9.9.9")
	client = _client(db)

	response = client.post(
		"/proofreader",
		json=PAYLOAD,
		headers={"X-Forwarded-For": "203.0.113.9"},
	)

	assert response.status_code == 429
	assert db.query(Interaction).count() == 3


def test_guest_quota_ignores_interactions_older_than_24h(db, fake_run_typo_correction, monkeypatch):
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	_seed_interaction(db, cost=Decimal("0.06"), ip_address="testclient", age=timedelta(hours=25))
	client = _client(db)

	response = client.post("/proofreader", json=PAYLOAD)

	assert response.status_code == 200


# --- authenticated user quotas -----------------------------------------------


def test_ordinary_user_quota_is_enforced(db, fake_run_typo_correction, monkeypatch):
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	user = User(
		account="user@example.org", name="User", sso_sub="sub-1", email_verified=True,
		is_active=True, is_superuser=False, quota=0.05,
	)
	db.add(user)
	db.commit()
	_seed_interaction(db, cost=Decimal("0.05"), user=user)

	client = _client(db, user=user)
	response = client.post("/proofreader", json=PAYLOAD)

	assert response.status_code == 429


def test_ordinary_user_under_quota_is_accepted(db, fake_run_typo_correction, monkeypatch):
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	user = User(
		account="user2@example.org", name="User2", sso_sub="sub-2", email_verified=True,
		is_active=True, is_superuser=False, quota=0.5,
	)
	db.add(user)
	db.commit()
	_seed_interaction(db, cost=Decimal("0.05"), user=user)

	client = _client(db, user=user)
	response = client.post("/proofreader", json=PAYLOAD)

	assert response.status_code == 200
	stored = db.query(Interaction).filter(Interaction.id == response.json()["interaction_id"]).one()
	assert stored.user_id == user.id


def test_superuser_is_exempt_from_quota(db, fake_run_typo_correction, monkeypatch):
	monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
	user = User(
		account="admin@example.org", name="Admin", sso_sub="sub-3", email_verified=True,
		is_active=True, is_superuser=True, quota=0.01,
	)
	db.add(user)
	db.commit()
	_seed_interaction(db, cost=Decimal("1.0"), user=user)

	client = _client(db, user=user)
	response = client.post("/proofreader", json=PAYLOAD)

	assert response.status_code == 200
