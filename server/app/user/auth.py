"""FastAPI dependencies that authorize requests against the SSO issuer.

Layering (spec: "SSO dependencies and local users"):

1. `get_bearer_token` extracts an optional Bearer token from the
   `Authorization` header. No header at all means "guest" (`None`). A
   header that is present but not a well-formed Bearer credential is
   always a 401 -- it is never silently downgraded to guest.
2. `get_token_verifier` lazily builds a process-wide `TokenVerifier`
   singleton from `AuthConfig`/`OidcProtocol` (env-configurable issuer
   and client id).
3. `get_verified_sub` calls `TokenVerifier.verify_access_token()` for
   every request that carries a token -- unconditionally, even when
   `resolve_local_user()` will go on to skip the UserInfo round-trip
   because the local user is already `email_verified=True`. Only the
   UserInfo call is ever skipped; cryptographic token verification is
   not.
4. `get_optional_user` maps a verified `sub` to a local `User` via
   `resolve_local_user()`, or returns `None` for a guest.
5. `require_user` / `require_superuser` turn "no local user" into 401,
   and "not a superuser" into 403.
"""

import os
import threading
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.package.coseeing_auth.errors import DiscoveryError, ScopeError, TokenValidationError
from app.package.coseeing_auth.models import AuthConfig
from app.package.coseeing_auth.oidc import OidcProtocol
from app.package.coseeing_auth.verification import TokenVerifier

from .linking import resolve_local_user
from .models import User

_MALFORMED_AUTH_DETAIL = "Authorization header must be a well-formed Bearer credential"
_TOKEN_INVALID_DETAIL = "access token could not be verified"
_DISCOVERY_UNAVAILABLE_DETAIL = "SSO issuer is unavailable"
_AUTH_REQUIRED_DETAIL = "authentication is required"
_SUPERUSER_REQUIRED_DETAIL = "superuser privileges are required"


def get_bearer_token(authorization: Optional[str] = Header(default=None)) -> Optional[str]:
	"""Extract the Bearer token from an optional `Authorization` header.

	Returns `None` when the header is absent entirely (a guest request).
	Raises HTTPException(401) when the header is present but is not a
	well-formed `Bearer <token>` credential -- this is never downgraded
	to a guest.
	"""
	if authorization is None:
		return None
	parts = authorization.split(None, 1)
	if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
		raise HTTPException(status_code=401, detail=_MALFORMED_AUTH_DETAIL)
	return parts[1]


_verifier_lock = threading.Lock()
_verifier: Optional[TokenVerifier] = None


def get_token_verifier() -> TokenVerifier:
	"""Lazily build the process-wide `TokenVerifier` singleton."""
	global _verifier
	if _verifier is None:
		with _verifier_lock:
			if _verifier is None:
				config = AuthConfig(
					issuer=os.getenv("SSO_ISSUER", "https://sso.coseeing.org"),
					client_id=os.getenv("SSO_CLIENT_ID", "wordbridge"),
					scopes=("openid",),
					login_redirect_uri="http://127.0.0.1:8000/auth/callback",
					logout_redirect_uri=None,
				)
				_verifier = TokenVerifier(config, OidcProtocol(config).discovery)
	return _verifier


def get_verified_sub(
	token: Optional[str] = Depends(get_bearer_token),
	verifier: TokenVerifier = Depends(get_token_verifier),
) -> Optional[str]:
	"""Cryptographically verify `token`, if any, and return its subject.

	Called for every request that carries a token -- this is the one
	step that must never be skipped, even for a locally-verified user.
	"""
	if token is None:
		return None
	try:
		claims = verifier.verify_access_token(token)
	except ScopeError:
		raise HTTPException(status_code=401, detail=_TOKEN_INVALID_DETAIL)
	except TokenValidationError:
		raise HTTPException(status_code=401, detail=_TOKEN_INVALID_DETAIL)
	except DiscoveryError:
		raise HTTPException(status_code=503, detail=_DISCOVERY_UNAVAILABLE_DETAIL)
	return claims.subject


def get_optional_user(
	sub: Optional[str] = Depends(get_verified_sub),
	token: Optional[str] = Depends(get_bearer_token),
	db: Session = Depends(get_db),
) -> Optional[User]:
	"""Resolve the local `User` for a verified subject, or `None` for a guest."""
	if sub is None:
		return None
	return resolve_local_user(db, sub, token)


def require_user(user: Optional[User] = Depends(get_optional_user)) -> User:
	"""Require a resolved local user, raising 401 for guests."""
	if user is None:
		raise HTTPException(status_code=401, detail=_AUTH_REQUIRED_DETAIL)
	return user


def require_superuser(user: User = Depends(require_user)) -> User:
	"""Require a resolved local user with `is_superuser=True`, raising 403 otherwise."""
	if not user.is_superuser:
		raise HTTPException(status_code=403, detail=_SUPERUSER_REQUIRED_DETAIL)
	return user
