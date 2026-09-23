import threading

import pytest
import requests
from fastapi import HTTPException
from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session

from app.baseModel import Base
from app.user.models import User
from app.user.linking import fetch_userinfo, resolve_local_user


VALID_USERINFO = {"sub": "s1", "email": "a@example.org", "email_verified": True}


def _patch_userinfo(monkeypatch, payload):
	monkeypatch.setattr("app.user.linking.fetch_userinfo", lambda token: payload)


def _no_userinfo_call(monkeypatch):
	def _fail(token):
		raise AssertionError("UserInfo called")
	monkeypatch.setattr("app.user.linking.fetch_userinfo", _fail)


# --- fast path -----------------------------------------------------------

def test_existing_verified_sub_does_not_call_userinfo(db, monkeypatch):
	user = User(account="a@example.org", name="A", sso_sub="s1", email_verified=True,
	            is_active=True, quota=0.1)
	db.add(user)
	db.commit()
	_no_userinfo_call(monkeypatch)
	assert resolve_local_user(db, "s1", "access-token").id == user.id


def test_existing_unverified_sub_calls_userinfo_and_updates_flag(db, monkeypatch):
	user = User(account="a@example.org", name="A", sso_sub="s1", email_verified=False,
	            is_active=True, quota=0.1)
	db.add(user)
	db.commit()
	_patch_userinfo(monkeypatch, VALID_USERINFO)

	result = resolve_local_user(db, "s1", "access-token")

	assert result.id == user.id
	assert result.email_verified is True


# --- linking by email ------------------------------------------------------

def test_link_existing_user_by_email(db, monkeypatch):
	user = User(account="a@example.org", name="A", sso_sub=None, email_verified=False,
	            is_active=True, quota=0.1)
	db.add(user)
	db.commit()
	_patch_userinfo(monkeypatch, VALID_USERINFO)

	result = resolve_local_user(db, "s1", "access-token")

	assert result.id == user.id
	assert result.sso_sub == "s1"
	assert result.email_verified is True


def test_link_by_email_is_case_insensitive(db, monkeypatch):
	user = User(account="A@Example.org", name="A", sso_sub=None, email_verified=False,
	            is_active=True, quota=0.1)
	db.add(user)
	db.commit()
	_patch_userinfo(monkeypatch, VALID_USERINFO)

	result = resolve_local_user(db, "s1", "access-token")

	assert result.id == user.id
	assert result.sso_sub == "s1"


def test_linking_preserves_inactive_status(db, monkeypatch):
	user = User(account="a@example.org", name="A", sso_sub=None, email_verified=False,
	            is_active=False, quota=0.1)
	db.add(user)
	db.commit()
	_patch_userinfo(monkeypatch, VALID_USERINFO)

	result = resolve_local_user(db, "s1", "access-token")

	assert result.id == user.id
	assert result.is_active is False


def test_verified_sub_with_stale_account_resyncs_to_new_email(db, monkeypatch):
	"""A row already linked to `sub` but whose stored account no longer
	matches the freshly UserInfo-verified email must not simply be flagged
	verified in place (that would vouch for an email never actually
	checked against this row) — it re-syncs the account to match."""
	user = User(account="old@example.org", name="Old", sso_sub="s1", email_verified=False,
	            is_active=True, quota=0.1)
	db.add(user)
	db.commit()
	_patch_userinfo(monkeypatch, {"sub": "s1", "email": "new@example.org", "email_verified": True})

	result = resolve_local_user(db, "s1", "access-token")

	assert result.id == user.id
	assert result.account == "new@example.org"
	assert result.email_verified is True


def test_verified_sub_cannot_steal_email_owned_by_another_user(db, monkeypatch):
	stale = User(account="old@example.org", name="Old", sso_sub="s1", email_verified=False,
	             is_active=True, quota=0.1)
	other = User(account="new@example.org", name="Other", sso_sub="s3", email_verified=True,
	             is_active=True, quota=0.1)
	db.add_all([stale, other])
	db.commit()
	_patch_userinfo(monkeypatch, {"sub": "s1", "email": "new@example.org", "email_verified": True})

	with pytest.raises(HTTPException) as excinfo:
		resolve_local_user(db, "s1", "access-token")

	assert excinfo.value.status_code == 409
	db.refresh(stale)
	db.refresh(other)
	assert stale.account == "old@example.org"
	assert stale.email_verified is False
	assert other.sso_sub == "s3"


def test_email_linked_to_other_sub_is_not_reassigned(db, monkeypatch):
	user = User(account="a@example.org", name="A", sso_sub="s1", email_verified=True,
	            is_active=True, quota=0.1)
	db.add(user)
	db.commit()
	monkeypatch.setattr("app.user.linking.fetch_userinfo", lambda token: {
		"sub": "s2", "email": "a@example.org", "email_verified": True
	})
	try:
		resolve_local_user(db, "s2", "access-token")
		assert False, "expected conflict"
	except HTTPException as error:
		assert error.status_code == 409
	db.refresh(user)
	assert user.sso_sub == "s1"


# --- creation --------------------------------------------------------------

def test_create_new_user_when_no_match(db, monkeypatch):
	_patch_userinfo(monkeypatch, {"sub": "s9", "email": "new@example.org", "email_verified": True, "name": "New Person"})

	result = resolve_local_user(db, "s9", "access-token")

	assert result.account == "new@example.org"
	assert result.sso_sub == "s9"
	assert result.email_verified is True
	assert result.is_active is True
	assert result.is_superuser is False
	assert result.quota == 0.1
	assert result.name == "New Person"


def test_create_new_user_falls_back_to_email_when_name_missing(db, monkeypatch):
	_patch_userinfo(monkeypatch, {"sub": "s9", "email": "new@example.org", "email_verified": True})

	result = resolve_local_user(db, "s9", "access-token")

	assert result.name == "new@example.org"


def test_create_new_user_truncates_long_name(db, monkeypatch):
	long_name = "N" * 60
	_patch_userinfo(monkeypatch, {"sub": "s9", "email": "new@example.org", "email_verified": True, "name": long_name})

	result = resolve_local_user(db, "s9", "access-token")

	assert result.name == long_name[:30]
	assert len(result.name) == 30


# --- 403 validation failures -------------------------------------------------

def test_mismatched_sub_returns_403_and_creates_nothing(db, monkeypatch):
	_patch_userinfo(monkeypatch, {"sub": "other-sub", "email": "new@example.org", "email_verified": True})

	with pytest.raises(HTTPException) as excinfo:
		resolve_local_user(db, "s1", "access-token")

	assert excinfo.value.status_code == 403
	assert db.query(User).count() == 0


def test_email_verified_truthy_but_not_strict_true_returns_403(db, monkeypatch):
	_patch_userinfo(monkeypatch, {"sub": "s1", "email": "a@example.org", "email_verified": 1})

	with pytest.raises(HTTPException) as excinfo:
		resolve_local_user(db, "s1", "access-token")

	assert excinfo.value.status_code == 403
	assert db.query(User).count() == 0


def test_blank_email_returns_403(db, monkeypatch):
	_patch_userinfo(monkeypatch, {"sub": "s1", "email": "  ", "email_verified": True})

	with pytest.raises(HTTPException) as excinfo:
		resolve_local_user(db, "s1", "access-token")

	assert excinfo.value.status_code == 403
	assert db.query(User).count() == 0


def test_missing_email_returns_403(db, monkeypatch):
	_patch_userinfo(monkeypatch, {"sub": "s1", "email_verified": True})

	with pytest.raises(HTTPException) as excinfo:
		resolve_local_user(db, "s1", "access-token")

	assert excinfo.value.status_code == 403


# --- fetch_userinfo itself --------------------------------------------------

class _FakeResponse:
	def __init__(self, status_code=200, json_value=None, json_error=None):
		self.status_code = status_code
		self._json_value = json_value
		self._json_error = json_error

	def json(self):
		if self._json_error is not None:
			raise self._json_error
		return self._json_value


def test_fetch_userinfo_connection_error_returns_503(monkeypatch):
	def _raise(*args, **kwargs):
		raise requests.ConnectionError("boom")
	monkeypatch.setattr("app.user.linking.requests.get", _raise)

	with pytest.raises(HTTPException) as excinfo:
		fetch_userinfo("secret-token")

	assert excinfo.value.status_code == 503


def test_fetch_userinfo_timeout_returns_503(monkeypatch):
	def _raise(*args, **kwargs):
		raise requests.Timeout("timed out")
	monkeypatch.setattr("app.user.linking.requests.get", _raise)

	with pytest.raises(HTTPException) as excinfo:
		fetch_userinfo("secret-token")

	assert excinfo.value.status_code == 503


def test_fetch_userinfo_non_200_returns_503(monkeypatch):
	monkeypatch.setattr("app.user.linking.requests.get", lambda *a, **k: _FakeResponse(status_code=500))

	with pytest.raises(HTTPException) as excinfo:
		fetch_userinfo("secret-token")

	assert excinfo.value.status_code == 503


def test_fetch_userinfo_unparseable_json_returns_503(monkeypatch):
	monkeypatch.setattr(
		"app.user.linking.requests.get",
		lambda *a, **k: _FakeResponse(json_error=ValueError("bad json")),
	)

	with pytest.raises(HTTPException) as excinfo:
		fetch_userinfo("secret-token")

	assert excinfo.value.status_code == 503


def test_fetch_userinfo_non_object_json_returns_503(monkeypatch):
	monkeypatch.setattr("app.user.linking.requests.get", lambda *a, **k: _FakeResponse(json_value=["not", "an", "object"]))

	with pytest.raises(HTTPException) as excinfo:
		fetch_userinfo("secret-token")

	assert excinfo.value.status_code == 503


def test_fetch_userinfo_sends_bearer_token_and_returns_payload(monkeypatch):
	captured = {}

	def _get(url, headers=None, timeout=None):
		captured["url"] = url
		captured["headers"] = headers
		captured["timeout"] = timeout
		return _FakeResponse(json_value=VALID_USERINFO)

	monkeypatch.setattr("app.user.linking.requests.get", _get)

	result = fetch_userinfo("secret-token")

	assert result == VALID_USERINFO
	assert captured["headers"] == {"Authorization": "Bearer secret-token"}
	assert captured["timeout"] == 6


# --- concurrency -------------------------------------------------------------

def test_concurrent_creation_of_same_subject_leaves_one_user(monkeypatch, tmp_path):
	"""Two sessions racing to create the same brand-new subject must not
	produce two rows: the loser hits the DB's unique constraint on
	`sso_sub`, and resolve_local_user() recovers by rereading and returning
	the winner's row instead.

	Real thread scheduling alone is not a reliable way to hit the exact
	interleaving (both sessions must observe "no existing user" before
	either commits), so the race is forced deterministically through the
	`_sync_before_write` hook: both threads block there until both have
	arrived, then are released together right before their writes.
	"""
	db_path = tmp_path / "concurrent.db"
	engine = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"timeout": 30})
	Base.metadata.create_all(engine)

	monkeypatch.setattr(
		"app.user.linking.fetch_userinfo",
		lambda token: {"sub": "conc-sub", "email": "conc@example.org", "email_verified": True},
	)

	barrier = threading.Barrier(2)

	def _sync():
		barrier.wait(timeout=5)

	monkeypatch.setattr("app.user.linking._sync_before_write", _sync)

	results = []
	errors = []

	def worker():
		session = Session(engine)
		try:
			results.append(resolve_local_user(session, "conc-sub", "token").id)
		except Exception as error:  # noqa: BLE001 - recorded for assertion below
			errors.append(error)
		finally:
			session.close()

	threads = [threading.Thread(target=worker) for _ in range(2)]
	for thread in threads:
		thread.start()
	for thread in threads:
		thread.join(timeout=10)

	assert errors == [], errors
	assert len(results) == 2
	assert results[0] == results[1]

	with Session(engine) as check:
		users = check.query(User).filter(User.sso_sub == "conc-sub").all()
		assert len(users) == 1

	Base.metadata.drop_all(engine)
	engine.dispose()


def test_concurrent_link_by_email_with_different_subjects_does_not_reassign(monkeypatch, tmp_path):
	"""Two different, brand-new subjects both carry the same verified email
	for one existing, not-yet-linked row. Only one may win the link; the
	other must be rejected (409), never silently overwrite the winner's
	`sso_sub` (last-writer-wins would break the "never reassign" guarantee).
	"""
	db_path = tmp_path / "email_race.db"
	engine = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"timeout": 30})
	Base.metadata.create_all(engine)

	with Session(engine) as setup:
		user = User(account="shared@example.org", name="Shared", sso_sub=None, email_verified=False,
		            is_active=True, quota=0.1)
		setup.add(user)
		setup.commit()
		user_id = user.id

	def _userinfo(token):
		# `token` doubles as the subject here so each thread gets a distinct,
		# self-consistent UserInfo payload without shared state.
		return {"sub": token, "email": "shared@example.org", "email_verified": True}

	monkeypatch.setattr("app.user.linking.fetch_userinfo", _userinfo)

	barrier = threading.Barrier(2)

	def _sync():
		barrier.wait(timeout=5)

	monkeypatch.setattr("app.user.linking._sync_before_write", _sync)

	results = {}
	errors = {}

	def worker(sub):
		session = Session(engine)
		try:
			results[sub] = resolve_local_user(session, sub, sub).sso_sub
		except Exception as error:  # noqa: BLE001 - recorded for assertion below
			errors[sub] = error
		finally:
			session.close()

	subs = ("race-s1", "race-s2")
	threads = [threading.Thread(target=worker, args=(sub,)) for sub in subs]
	for thread in threads:
		thread.start()
	for thread in threads:
		thread.join(timeout=10)

	assert len(errors) == 1, errors
	assert len(results) == 1, results
	losing_error = next(iter(errors.values()))
	assert isinstance(losing_error, HTTPException)
	assert losing_error.status_code == 409

	winning_sub = next(iter(results))
	assert results[winning_sub] == winning_sub

	with Session(engine) as check:
		refreshed = check.get(User, user_id)
		assert refreshed.sso_sub == winning_sub
		assert refreshed.email_verified is True
		# Exactly one user still owns the email; no duplicate was created.
		assert check.query(User).filter(func.lower(User.account) == "shared@example.org").count() == 1

	Base.metadata.drop_all(engine)
	engine.dispose()
