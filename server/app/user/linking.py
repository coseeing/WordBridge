"""SSO identity verification and local-user linking.

Given an access token whose `sub` has already been cryptographically
verified (Task 4's job, not this module's), `resolve_local_user()` finds or
creates the corresponding local `User`, calling the SSO UserInfo endpoint
only when the local user is not already known to be verified.

Never logs the access token or the raw UserInfo response body.
"""

import os

import requests
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import User

SSO_USERINFO_URL_DEFAULT = "https://sso.coseeing.org/userinfo"
USERINFO_TIMEOUT = 6
# User.name is String(30); truncate anything we derive to fit it.
NAME_MAX_LENGTH = 30

_UNAVAILABLE_DETAIL = "SSO UserInfo endpoint is unavailable"
_UNPARSEABLE_DETAIL = "SSO UserInfo endpoint returned an unparseable response"
_UNVERIFIED_DETAIL = "SSO identity could not be verified"
_CONFLICT_DETAIL = "SSO identity conflicts with an existing account"


def _userinfo_url() -> str:
	return os.environ.get("SSO_USERINFO_URL", SSO_USERINFO_URL_DEFAULT)


def fetch_userinfo(token: str) -> dict:
	"""Call the SSO UserInfo endpoint with `token` as a Bearer credential.

	Returns the parsed JSON object on success. Connection failures,
	timeouts, non-200 responses, and unparseable or non-object bodies all
	raise HTTPException(503). Never logs the token or the response body.
	"""
	try:
		response = requests.get(
			_userinfo_url(),
			headers={"Authorization": f"Bearer {token}"},
			timeout=USERINFO_TIMEOUT,
		)
	except requests.RequestException as error:
		raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL) from error

	if response.status_code != 200:
		raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL)

	try:
		payload = response.json()
	except ValueError as error:
		raise HTTPException(status_code=503, detail=_UNPARSEABLE_DETAIL) from error

	if not isinstance(payload, dict):
		raise HTTPException(status_code=503, detail=_UNPARSEABLE_DETAIL)

	return payload


def _validate_userinfo(payload: dict, sub: str) -> str:
	"""Validate a UserInfo payload against the already-verified token subject.

	Returns the verified, stripped email on success. Raises
	HTTPException(403) when the UserInfo `sub` does not match, the email is
	blank, or `email_verified` is not strictly boolean `True`.
	"""
	userinfo_sub = payload.get("sub")
	email = payload.get("email")
	email_verified = payload.get("email_verified")

	if (
		not isinstance(userinfo_sub, str)
		or userinfo_sub != sub
		or not isinstance(email, str)
		or not email.strip()
		or email_verified is not True
	):
		raise HTTPException(status_code=403, detail=_UNVERIFIED_DETAIL)

	return email.strip()


def _derive_name(name: object, email: str) -> str:
	candidate = name if isinstance(name, str) and name.strip() else email
	return candidate[:NAME_MAX_LENGTH]


def _sync_before_write() -> None:
	"""No-op hook point.

	Production code never overrides this. Tests may monkeypatch it to
	force two concurrent `resolve_local_user()` calls to interleave
	between the "no existing user" check and the write, so the
	IntegrityError recovery path below can be exercised deterministically
	instead of relying on incidental thread scheduling.
	"""
	return None


def _lookup_by_sub(db: Session, sub: str) -> User | None:
	return db.query(User).filter(User.sso_sub == sub).one_or_none()


def _lookup_by_email(db: Session, email: str) -> User | None:
	return db.query(User).filter(func.lower(User.account) == email.lower()).one_or_none()


def _link_or_create(db: Session, *, sub: str, email: str, name: object, existing_by_sub: User | None) -> User:
	if existing_by_sub is not None:
		if existing_by_sub.account.lower() == email.lower():
			existing_by_sub.email_verified = True
			db.commit()
			db.refresh(existing_by_sub)
			return existing_by_sub
		# The subject is already ours, but the freshly UserInfo-verified email
		# no longer matches this row's account (e.g. the SSO profile's email
		# changed). Re-sync the account to the verified email rather than
		# flipping email_verified=True for an email that was never actually
		# checked against this row.
		return _relink_verified_sub_to_new_email(db, existing_by_sub, sub=sub, email=email)

	existing_by_email = _lookup_by_email(db, email)
	if existing_by_email is not None:
		if existing_by_email.sso_sub is not None and existing_by_email.sso_sub != sub:
			raise HTTPException(status_code=409, detail=_CONFLICT_DETAIL)
		return _claim_email_for_subject(db, existing_by_email, sub=sub)

	_sync_before_write()
	new_user = User(
		account=email,
		name=_derive_name(name, email),
		sso_sub=sub,
		email_verified=True,
		is_active=True,
		is_superuser=False,
		quota=0.1,
	)
	db.add(new_user)
	db.commit()
	db.refresh(new_user)
	return new_user


def _claim_email_for_subject(db: Session, user: User, *, sub: str) -> User:
	"""Link an existing, not-yet-linked user (`sso_sub IS NULL`) to `sub`.

	Uses a conditional UPDATE guarded on `sso_sub IS NULL` and checks its
	row count, rather than an ORM attribute set-and-commit, so that two
	concurrent requests for two *different* subjects racing on the same
	unlinked email cannot both "succeed": the loser's UPDATE matches zero
	rows (its WHERE clause is re-evaluated against the database at write
	time, after the winner's commit), and it must reread and either return
	the winner's row (if it happens to match its own subject) or raise 409.
	Last-writer-wins overwrite of `sso_sub` is exactly what this guards
	against.
	"""
	_sync_before_write()
	updated = (
		db.query(User)
		.filter(User.id == user.id, User.sso_sub.is_(None))
		.update({"sso_sub": sub, "email_verified": True})
	)
	if updated == 0:
		db.rollback()
		return _reread_after_conflict(db, sub=sub, email=user.account)
	db.commit()
	db.refresh(user)
	return user


def _relink_verified_sub_to_new_email(db: Session, user: User, *, sub: str, email: str) -> User:
	"""Re-sync an already-linked subject's account to a freshly verified email.

	Refuses to steal an email another user already owns (409). Uses the
	same conditional-UPDATE-plus-rowcount pattern as `_claim_email_for_subject`
	so a concurrent change to this same row cannot be silently overwritten.
	"""
	conflicting = _lookup_by_email(db, email)
	if conflicting is not None and conflicting.id != user.id:
		raise HTTPException(status_code=409, detail=_CONFLICT_DETAIL)
	_sync_before_write()
	updated = (
		db.query(User)
		.filter(User.id == user.id, User.sso_sub == sub)
		.update({"account": email, "email_verified": True})
	)
	if updated == 0:
		db.rollback()
		return _reread_after_conflict(db, sub=sub, email=email)
	db.commit()
	db.refresh(user)
	return user


def _reread_after_conflict(db: Session, *, sub: str, email: str) -> User:
	user = _lookup_by_sub(db, sub)
	if user is not None:
		return user

	user = _lookup_by_email(db, email)
	if user is not None and user.sso_sub == sub:
		return user

	raise HTTPException(status_code=409, detail=_CONFLICT_DETAIL)


def resolve_local_user(db: Session, sub: str, token: str) -> User:
	"""Find or create the local `User` for an already-verified SSO subject.

	Skips the UserInfo call entirely when `sub` already maps to a local
	user with `email_verified=True` (the confirmed fast path). Otherwise
	calls UserInfo, validates it against `sub`, and links or creates a
	user accordingly. Raises HTTPException(403) when UserInfo cannot
	confirm the identity, HTTPException(503) when UserInfo itself is
	unreachable or unparseable, and HTTPException(409) when the verified
	email belongs to a different SSO subject.
	"""
	existing_by_sub = _lookup_by_sub(db, sub)
	if existing_by_sub is not None and existing_by_sub.email_verified is True:
		return existing_by_sub

	payload = fetch_userinfo(token)
	email = _validate_userinfo(payload, sub)
	name = payload.get("name")

	try:
		return _link_or_create(db, sub=sub, email=email, name=name, existing_by_sub=existing_by_sub)
	except IntegrityError:
		db.rollback()
		return _reread_after_conflict(db, sub=sub, email=email)
