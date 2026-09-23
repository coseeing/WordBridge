from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.baseModel import Base
from app.dependencies import get_db
from app.dependenciesA import get_session
from app.models.models import Interaction
from app.user.auth import get_optional_user, get_token_verifier
from app.user.models import User


async def _override_get_session():
	# The CRUD routers (fastcrud crud_router) use a separate async session
	# dependency (get_session, bound to the real MySQL deployment engine).
	# Route-permission tests only need this to resolve to *some* working
	# async session so the request completes end-to-end for a superuser --
	# an in-memory sqlite engine is enough.
	from sqlalchemy.ext.asyncio import AsyncSession

	engine = create_async_engine(
		"sqlite+aiosqlite://",
		connect_args={"check_same_thread": False},
		poolclass=StaticPool,
	)
	async with engine.begin() as conn:
		await conn.run_sync(Base.metadata.create_all)
	async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
	async with async_session() as session:
		yield session
	await engine.dispose()


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


def _client(db, *, user=None):
	main_module.app.dependency_overrides[get_db] = _override_get_db(db)
	main_module.app.dependency_overrides[get_optional_user] = lambda: user
	main_module.app.dependency_overrides[get_session] = _override_get_session
	return TestClient(main_module.app)


def _seed_interaction(db, *, user=None):
	now = datetime.now(timezone.utc)
	interaction = Interaction(
		request_time=now,
		response_time=now,
		request_content="x",
		response_content="y",
		ip_address="1.2.3.4",
		cost=0,
		model="deepseek-v4-flash&DeepSeek",
		version="20260425",
		user=user,
	)
	interaction.category = "1"
	db.add(interaction)
	db.commit()
	db.refresh(interaction)
	return interaction


def _ordinary_user(db):
	user = User(
		account="user@example.org", name="User", sso_sub="sub-1", email_verified=True,
		is_active=True, is_superuser=False, quota=0.1,
	)
	db.add(user)
	db.commit()
	return user


def _superuser(db):
	user = User(
		account="admin@example.org", name="Admin", sso_sub="sub-2", email_verified=True,
		is_active=True, is_superuser=True, quota=0.1,
	)
	db.add(user)
	db.commit()
	return user


# --- /users, /interactions CRUD: superuser only -----------------------------


def test_users_get_paginated_guest_is_401(db):
	client = _client(db)
	response = client.get("/users/get_paginated")
	assert response.status_code == 401


def test_users_get_paginated_ordinary_user_is_403(db):
	user = _ordinary_user(db)
	client = _client(db, user=user)
	response = client.get("/users/get_paginated")
	assert response.status_code == 403


def test_users_get_paginated_superuser_is_200(db):
	user = _superuser(db)
	client = _client(db, user=user)
	response = client.get("/users/get_paginated")
	assert response.status_code == 200


def test_interactions_get_paginated_guest_is_401(db):
	client = _client(db)
	response = client.get("/interactions/get_paginated")
	assert response.status_code == 401


def test_interactions_get_paginated_ordinary_user_is_403(db):
	user = _ordinary_user(db)
	client = _client(db, user=user)
	response = client.get("/interactions/get_paginated")
	assert response.status_code == 403


def test_interactions_get_paginated_superuser_is_200(db):
	user = _superuser(db)
	client = _client(db, user=user)
	response = client.get("/interactions/get_paginated")
	assert response.status_code == 200


# --- /login, /register: no longer provided ----------------------------------


def test_login_is_404(db):
	client = _client(db)
	response = client.post("/login", data={"username": "a", "password": "b"})
	assert response.status_code == 404


def test_register_is_404(db):
	client = _client(db)
	response = client.post("/register", json={"account": "a", "name": "b"})
	assert response.status_code == 404


# --- /feedback: guest and authenticated, create then overwrite, 404 ---------


def test_guest_feedback_create_then_overwrite(db):
	interaction = _seed_interaction(db)
	client = _client(db)

	response = client.post(
		"/feedback",
		json={"interaction_id": interaction.id, "review_content": "已確認"},
	)
	assert response.status_code == 200
	db.refresh(interaction)
	assert interaction.review_user_id is None
	assert interaction.review_content == "已確認"

	response = client.post(
		"/feedback",
		json={"interaction_id": interaction.id, "review_content": "修正回饋"},
	)
	assert response.status_code == 200
	db.refresh(interaction)
	assert interaction.review_content == "修正回饋"
	assert interaction.review_user_id is None
	assert db.query(Interaction).filter(Interaction.id == interaction.id).count() == 1


def test_authenticated_feedback_records_user_id(db):
	interaction = _seed_interaction(db)
	user = _ordinary_user(db)
	client = _client(db, user=user)

	response = client.post(
		"/feedback",
		json={"interaction_id": interaction.id, "review_content": "已確認"},
	)
	assert response.status_code == 200
	db.refresh(interaction)
	assert interaction.review_user_id == user.id
	assert interaction.review_content == "已確認"


def test_feedback_unknown_interaction_is_404(db):
	client = _client(db)
	response = client.post(
		"/feedback",
		json={"interaction_id": 999999, "review_content": "x"},
	)
	assert response.status_code == 404


# --- inactive user: 403 through the REAL dependency chain -------------------
#
# Unlike the tests above (which override get_optional_user directly, bypassing
# resolve_local_user()/is_active entirely), these wire a fake TokenVerifier
# through the real chain: get_bearer_token -> get_verified_sub ->
# get_optional_user -> resolve_local_user -> the is_active check. This is the
# only way to actually exercise the guard the reviewer found missing.


class _FakeVerifier:
	def __init__(self, sub):
		self.sub = sub

	def verify_access_token(self, token, required_scopes=()):
		return SimpleNamespace(subject=self.sub)


def _client_with_real_auth_chain(db, *, verifier):
	# Deliberately do NOT override get_optional_user here -- that is the
	# point of this fixture: the real chain (including the is_active check)
	# must run.
	main_module.app.dependency_overrides[get_db] = _override_get_db(db)
	main_module.app.dependency_overrides[get_token_verifier] = lambda: verifier
	main_module.app.dependency_overrides[get_session] = _override_get_session
	return TestClient(main_module.app)


def _inactive_user(db, *, is_superuser=False):
	user = User(
		account="inactive@example.org", name="Inactive", sso_sub="sub-inactive",
		email_verified=True, is_active=False, is_superuser=is_superuser, quota=0.1,
	)
	db.add(user)
	db.commit()
	return user


def test_inactive_user_is_403_on_proofreader_real_chain(db):
	_inactive_user(db)
	verifier = _FakeVerifier(sub="sub-inactive")
	client = _client_with_real_auth_chain(db, verifier=verifier)

	response = client.post(
		"/proofreader",
		json={
			"request": "測試",
			"corrector_config_id": "default",
			"language": "zh_traditional",
			"typo_correction_mode": "standard",
			"customized_words": [],
		},
		headers={"Authorization": "Bearer tok"},
	)

	assert response.status_code == 403
	assert db.query(Interaction).count() == 0


def test_inactive_superuser_is_403_on_admin_route_real_chain(db):
	_inactive_user(db, is_superuser=True)
	verifier = _FakeVerifier(sub="sub-inactive")
	client = _client_with_real_auth_chain(db, verifier=verifier)

	response = client.get("/users/get_paginated", headers={"Authorization": "Bearer tok"})

	assert response.status_code == 403


def test_no_token_still_reaches_guest_path_real_chain(db):
	# Regression guard: the is_active check must never intercept a request
	# that carries no token at all -- that must stay a guest.
	verifier = _FakeVerifier(sub="sub-inactive")
	client = _client_with_real_auth_chain(db, verifier=verifier)

	response = client.get("/users/get_paginated")

	assert response.status_code == 401
