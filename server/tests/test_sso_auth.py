from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_db
from app.package.coseeing_auth.errors import DiscoveryError, ScopeError, TokenValidationError
from app.user.auth import (
	get_optional_user,
	get_token_verifier,
	require_superuser,
	require_user,
)
from app.user.models import User


class FakeVerifier:
	"""A fake `TokenVerifier` that counts every `verify_access_token()` call."""

	def __init__(self, sub="sub-1", error=None):
		self.sub = sub
		self.error = error
		self.calls = 0

	def verify_access_token(self, token, required_scopes=()):
		self.calls += 1
		if self.error is not None:
			raise self.error
		return SimpleNamespace(subject=self.sub)


def _override_get_db(session):
	def _get_db():
		try:
			yield session
		finally:
			pass

	return _get_db


def _make_app(db_session, verifier):
	app = FastAPI()

	@app.get("/optional")
	def optional(user=Depends(get_optional_user)):
		return {"guest": user is None}

	@app.get("/user")
	def user_route(user=Depends(require_user)):
		return {"id": user.id}

	@app.get("/admin")
	def admin(user=Depends(require_superuser)):
		return {"id": user.id}

	app.dependency_overrides[get_db] = _override_get_db(db_session)
	app.dependency_overrides[get_token_verifier] = lambda: verifier
	return app


def _bearer(token="tok"):
	return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def verifier():
	return FakeVerifier()


@pytest.fixture
def client(db, verifier):
	return TestClient(_make_app(db, verifier))


# --- get_bearer_token / guest vs. malformed --------------------------------

def test_guest_is_optional(client):
	response = client.get("/optional")
	assert response.status_code == 200
	assert response.json() == {"guest": True}


def test_malformed_bearer_scheme_is_401(client):
	response = client.get("/optional", headers={"Authorization": "Basic abc"})
	assert response.status_code == 401


def test_header_without_scheme_is_401(client):
	response = client.get("/optional", headers={"Authorization": "tok-without-scheme"})
	assert response.status_code == 401


def test_bearer_without_token_is_401(client):
	response = client.get("/optional", headers={"Authorization": "Bearer "})
	assert response.status_code == 401


def test_guest_never_downgrades_malformed_header(client):
	# A malformed header must 401, never silently fall through to guest=True.
	response = client.get("/optional", headers={"Authorization": "Basic abc"})
	assert response.status_code == 401
	assert response.json() != {"guest": True}


# --- verifier error mapping -------------------------------------------------

def test_scope_error_maps_to_401(db):
	verifier = FakeVerifier(error=ScopeError("missing scope"))
	app_client = TestClient(_make_app(db, verifier))
	response = app_client.get("/optional", headers=_bearer())
	assert response.status_code == 401


def test_token_validation_error_maps_to_401(db):
	verifier = FakeVerifier(
		error=TokenValidationError(
			"bad token", operation="access_token", stage="token_validation", code="jwt_invalid"
		)
	)
	app_client = TestClient(_make_app(db, verifier))
	response = app_client.get("/optional", headers=_bearer())
	assert response.status_code == 401


def test_discovery_error_maps_to_503(db):
	verifier = FakeVerifier(
		error=DiscoveryError("discovery down", code="discovery_network_error", retryable=True)
	)
	app_client = TestClient(_make_app(db, verifier))
	response = app_client.get("/optional", headers=_bearer())
	assert response.status_code == 503


# --- require_user / require_superuser --------------------------------------

def test_require_user_401_without_token(client):
	response = client.get("/user")
	assert response.status_code == 401


def test_ordinary_user_gets_403_from_admin(db, monkeypatch):
	user = User(
		account="user@example.org", name="User", sso_sub="sub-1", email_verified=True,
		is_active=True, is_superuser=False, quota=0.1,
	)
	db.add(user)
	db.commit()
	verifier = FakeVerifier(sub="sub-1")
	app_client = TestClient(_make_app(db, verifier))
	response = app_client.get("/admin", headers=_bearer())
	assert response.status_code == 403


def test_superuser_gets_200_from_admin(db):
	user = User(
		account="admin@example.org", name="Admin", sso_sub="sub-1", email_verified=True,
		is_active=True, is_superuser=True, quota=0.1,
	)
	db.add(user)
	db.commit()
	verifier = FakeVerifier(sub="sub-1")
	app_client = TestClient(_make_app(db, verifier))
	response = app_client.get("/admin", headers=_bearer())
	assert response.status_code == 200
	assert response.json() == {"id": user.id}


# --- token verification happens every request, UserInfo only when needed --

def test_verifier_runs_every_request_but_userinfo_only_while_unverified(db, monkeypatch):
	calls = {"userinfo": 0}

	def fake_userinfo(token):
		calls["userinfo"] += 1
		return {"sub": "sub-1", "email": "a@example.org", "email_verified": True}

	monkeypatch.setattr("app.user.linking.fetch_userinfo", fake_userinfo)
	verifier = FakeVerifier(sub="sub-1")
	app_client = TestClient(_make_app(db, verifier))

	first = app_client.get("/optional", headers=_bearer())
	second = app_client.get("/optional", headers=_bearer())

	assert first.status_code == 200
	assert second.status_code == 200
	# The token is verified cryptographically on every single request...
	assert verifier.calls == 2
	# ...but UserInfo is only called once: the first request links/verifies
	# the local user, and the second hits the already-verified fast path.
	assert calls["userinfo"] == 1
