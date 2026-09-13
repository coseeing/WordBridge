from collections.abc import Iterable
import threading
from typing import Any

import jwt
import requests

from .errors import ScopeError, TokenValidationError
from .models import AuthConfig, VerifiedClaims


_JWKS_REQUEST_HEADERS = {
    "User-Agent": "coseeing-oidc-client/1.0",
    "Accept": "application/json",
}


def _scope_set(value: Any) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        return frozenset(part for part in value.split() if part)
    if isinstance(value, bytes):
        return frozenset()
    if isinstance(value, Iterable):
        return frozenset(str(part) for part in value)
    return frozenset()


def extract_coseeing_identity(claims: dict | None) -> str | None:
    if not isinstance(claims, dict):
        return None
    direct = claims.get("coseeing_identity")
    if isinstance(direct, str) and direct:
        return direct
    ext = claims.get("ext")
    nested = ext.get("coseeing_identity") if isinstance(ext, dict) else None
    return nested if isinstance(nested, str) and nested else None


def _to_verified_claims(claims: dict, scopes: frozenset[str]) -> VerifiedClaims:
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise ValueError("token subject is missing")
    return VerifiedClaims(
        subject=subject,
        email=claims.get("email"),
        name=claims.get("name"),
        coseeing_identity=extract_coseeing_identity(claims),
        expires_at=claims.get("exp"),
        scopes=scopes,
    )


def _validation_error(operation: str, code: str) -> TokenValidationError:
    return TokenValidationError(
        "token validation failed",
        operation=operation,
        stage="token_validation",
        code=code,
        retryable=False,
    )


class JwtAccessTokenVerifier:
    def __init__(
        self,
        issuer: str,
        algorithms: tuple[str, ...] = ("RS256",),
        jwks_client=None,
        leeway: int = 10,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.algorithms = algorithms
        self.jwks_client = jwks_client
        self.leeway = leeway

    def verify(self, token: str, required_scopes=None) -> VerifiedClaims:
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=self.algorithms,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss"], "verify_aud": False},
                leeway=self.leeway,
            )
            scopes = _scope_set(claims.get("scp")) if "scp" in claims else _scope_set(claims.get("scope"))
            required = _scope_set(required_scopes)
            if not required.issubset(scopes):
                raise ScopeError("required scopes are missing")
            return _to_verified_claims(claims, scopes)
        except ScopeError:
            raise
        except (jwt.PyJWTError, jwt.PyJWKClientError, ValueError):
            raise _validation_error("access_token", "jwt_invalid") from None


class IdTokenVerifier:
    def __init__(
        self,
        issuer: str,
        client_id: str,
        algorithms: tuple[str, ...] = ("RS256",),
        jwks_client=None,
        leeway: int = 10,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.client_id = client_id
        self.algorithms = algorithms
        self.jwks_client = jwks_client
        self.leeway = leeway

    def verify(self, token: str, nonce: str | None = None) -> VerifiedClaims:
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=self.algorithms,
                issuer=self.issuer,
                audience=self.client_id,
                options={"require": ["exp", "iat", "iss", "aud"]},
                leeway=self.leeway,
            )
        except (jwt.PyJWTError, jwt.PyJWKClientError, ValueError):
            raise _validation_error("id_token", "id_token_invalid") from None

        try:
            audience = claims.get("aud")
            authorized_party = claims.get("azp")
            if isinstance(audience, (list, tuple)):
                if self.client_id not in audience:
                    raise ValueError("client is not an audience")
                if len(audience) > 1 and authorized_party != self.client_id:
                    raise ValueError("multiple audiences require matching authorized party")
            elif audience != self.client_id:
                raise ValueError("client is not the audience")
            if authorized_party is not None and authorized_party != self.client_id:
                raise ValueError("authorized party does not match client")
        except (TypeError, ValueError):
            raise _validation_error("id_token", "id_token_invalid") from None

        if nonce is not None and claims.get("nonce") != nonce:
            raise TokenValidationError(
                "ID token nonce validation failed",
                operation="id_token",
                stage="token_validation",
                code="nonce_mismatch",
                retryable=False,
            )

        try:
            return _to_verified_claims(claims, frozenset())
        except ValueError:
            raise _validation_error("id_token", "id_token_invalid") from None


class IntrospectionVerifier:
    def __init__(
        self,
        endpoint: str | None,
        client_id: str,
        timeout: int = 6,
        http=requests,
    ) -> None:
        self.endpoint = endpoint
        self.client_id = client_id
        self.timeout = timeout
        self.http = http

    def verify(
        self,
        token: str,
        required_scopes: tuple[str, ...] = (),
    ) -> VerifiedClaims:
        if self.endpoint is None:
            raise _validation_error("access_token", "introspection_invalid")
        try:
            response = self.http.post(
                self.endpoint,
                data={
                    "token": token,
                    "token_type_hint": "access_token",
                    "client_id": self.client_id,
                },
                timeout=self.timeout,
            )
            if response.status_code != 200:
                raise ValueError("introspection request failed")
            claims = response.json()
            if not isinstance(claims, dict) or claims.get("active") is not True:
                raise ValueError("inactive introspection result")
            scopes = _scope_set(claims.get("scope"))
            required = _scope_set(required_scopes)
            if not required.issubset(scopes):
                raise ScopeError("required scopes are missing")
            return _to_verified_claims(claims, scopes)
        except ScopeError:
            raise
        except (requests.RequestException, TypeError, ValueError, AttributeError):
            raise _validation_error("access_token", "introspection_invalid") from None


class TokenVerifier:
    def __init__(self, config: AuthConfig, metadata_provider, *, http=requests) -> None:
        self._config = config
        self._metadata_provider = metadata_provider
        self._http = http
        self._strategy_lock = threading.Lock()
        self._strategies = None

    @classmethod
    def _from_strategies(
        cls,
        *,
        id_token_verifier,
        jwt_access_verifier,
        introspection_verifier,
    ):
        verifier = cls.__new__(cls)
        verifier._strategies = (
            id_token_verifier,
            jwt_access_verifier,
            introspection_verifier,
        )
        verifier._strategy_lock = threading.Lock()
        return verifier

    def _ensure_strategies(self):
        with self._strategy_lock:
            if self._strategies is None:
                metadata = self._metadata_provider()
                jwks = jwt.PyJWKClient(
                    metadata.jwks_uri,
                    cache_keys=True,
                    headers=_JWKS_REQUEST_HEADERS,
                )
                self._strategies = (
                    IdTokenVerifier(
                        issuer=self._config.issuer,
                        client_id=self._config.client_id,
                        algorithms=("RS256",),
                        jwks_client=jwks,
                    ),
                    JwtAccessTokenVerifier(
                        issuer=self._config.issuer,
                        algorithms=("RS256",),
                        jwks_client=jwks,
                    ),
                    IntrospectionVerifier(
                        endpoint=metadata.introspection_endpoint,
                        client_id=self._config.client_id,
                        timeout=6,
                        http=self._http,
                    ),
                )
            return self._strategies

    def verify_id_token(self, token: str, nonce: str | None = None) -> VerifiedClaims:
        id_token, _, _ = self._ensure_strategies()
        return id_token.verify(token, nonce=nonce)

    def verify_access_token(
        self,
        token: str,
        required_scopes: tuple[str, ...] = (),
    ) -> VerifiedClaims:
        _, jwt_access, introspection = self._ensure_strategies()
        try:
            return jwt_access.verify(token, required_scopes=required_scopes)
        except ScopeError:
            raise
        except TokenValidationError:
            try:
                return introspection.verify(token, required_scopes=required_scopes)
            except TokenValidationError as introspection_error:
                raise TokenValidationError(
                    "access token validation failed",
                    operation="access_token",
                    stage="token_validation",
                    code="token_invalid",
                    retryable=False,
                ) from introspection_error
