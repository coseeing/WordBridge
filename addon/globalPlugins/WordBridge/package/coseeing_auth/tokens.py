import threading
import time
from collections.abc import Callable
from typing import Any

import requests
from authlib.oauth2.rfc6749.errors import OAuth2Error

from .errors import RestoreError, TokenUnavailableError, TokenValidationError
from .models import AuthConfig, AuthResult, Identity, TokenSet


class TokenState:
    def __init__(self, initial: TokenSet | None = None) -> None:
        self._lock = threading.RLock()
        self._tokens = initial or TokenSet()

    def snapshot(self) -> TokenSet:
        with self._lock:
            return self._tokens

    def replace_after(self, candidate: TokenSet, validate: Callable[[TokenSet], Any]) -> Any:
        validated = validate(candidate)
        with self._lock:
            self._tokens = candidate
        return validated

    def clear(self) -> None:
        with self._lock:
            self._tokens = TokenSet()


class TokenLifecycle:
    def __init__(self, config: AuthConfig, protocol: Any, verifier: Any, state: TokenState) -> None:
        self._config = config
        self._protocol = protocol
        self._verifier = verifier
        self._state = state
        self._refresh_lock = threading.Lock()

    def accept_login(self, candidate: TokenSet, nonce: str | None) -> AuthResult:
        if not candidate.id_token:
            raise self._token_error("login", "ID token is missing", "token_missing", False)
        return self._state.replace_after(
            candidate,
            lambda value: self._validate_candidate(value, nonce=nonce, operation="login"),
        )

    def restore(self, refresh_token: str) -> AuthResult:
        if not refresh_token:
            raise RestoreError(
                "refresh token is missing",
                operation="restore",
                stage="refresh",
                code="token_missing",
                retryable=False,
            )
        previous = self._state.snapshot()
        try:
            response = self._protocol.refresh(refresh_token)
        except OAuth2Error as error:
            if getattr(error, "error", None) == "invalid_grant":
                raise RestoreError(
                    "refresh token was rejected",
                    operation="restore",
                    stage="refresh",
                    code="refresh_rejected",
                    retryable=False,
                ) from None
            raise RestoreError(
                "refresh request failed",
                operation="restore",
                stage="refresh",
                code="restore_failed",
                retryable=False,
            ) from None
        except (requests.RequestException, OSError):
            raise RestoreError(
                "refresh request failed",
                operation="restore",
                stage="refresh",
                code="token_endpoint_network_error",
                retryable=True,
            ) from None

        candidate = merge_refresh_candidate(response, previous, refresh_token)
        return self._state.replace_after(
            candidate,
            lambda value: self._validate_candidate(value, nonce=None, operation="restore"),
        )

    def identity(self) -> Identity:
        tokens = self._state.snapshot()
        if not tokens.access_token:
            raise self._token_error("access_token", "access token is missing", "token_missing", True)
        return self._validate_candidate(tokens, nonce=None, operation="access_token").identity

    def get_access_token(
        self, grace: int = 60, auto_login: bool = True, reauthenticate: Callable[[], Any] | None = None
    ) -> str:
        return self._get_token("access", grace, auto_login, reauthenticate)

    def get_id_token(
        self, grace: int = 60, auto_login: bool = True, reauthenticate: Callable[[], Any] | None = None
    ) -> str:
        return self._get_token("id", grace, auto_login, reauthenticate)

    def get_refresh_token(self) -> str | None:
        return self._state.snapshot().refresh_token

    def snapshot(self) -> TokenSet:
        return self._state.snapshot()

    def clear(self) -> None:
        self._state.clear()

    def _get_token(
        self,
        token_kind: str,
        grace: int,
        auto_login: bool,
        reauthenticate: Callable[[], Any] | None,
    ) -> str:
        operation = f"{token_kind}_token"
        current = self._state.snapshot()
        current_error = self._current_validation_error(current, token_kind, grace)
        if self._has_current_candidate(current, token_kind, grace) and current_error is None:
            return self._select_token(current, token_kind)
        initial = current

        with self._refresh_lock:
            current = self._state.snapshot()
            if current != initial:
                current_error = self._current_validation_error(current, token_kind, grace)
            if self._has_current_candidate(current, token_kind, grace) and current_error is None:
                return self._select_token(current, token_kind)

            if current.refresh_token:
                refresh_error = None
                try:
                    response = self._protocol.refresh(current.refresh_token)
                except OAuth2Error as error:
                    if getattr(error, "error", None) == "invalid_grant":
                        refresh_error = self._unavailable_error(
                            operation, "refresh token was rejected", "refresh_rejected", False
                        )
                    else:
                        refresh_error = self._unavailable_error(
                            operation, "refresh request failed", "refresh_failed", True
                        )
                except (requests.RequestException, OSError):
                    refresh_error = self._unavailable_error(
                        operation, "refresh request failed", "token_endpoint_network_error", True
                    )
                else:
                    candidate = merge_refresh_candidate(response, current, supplied_refresh_token=None)
                    if self._select_token(candidate, token_kind, raise_error=False):
                        candidate_error = None
                        try:
                            result = self._validate_candidate(candidate, nonce=None, operation=operation)
                        except TokenValidationError as error:
                            candidate_error = error
                        if candidate_error is None:
                            self._state.replace_after(candidate, lambda value: result)
                            return self._select_token(candidate, token_kind)
                        refresh_error = candidate_error
                    else:
                        refresh_error = self._missing_after_recovery_error(operation)

                if refresh_error is not None and not auto_login:
                    raise refresh_error
            elif current_error is not None and not auto_login:
                raise current_error

            if not auto_login or reauthenticate is None:
                if current_error is not None:
                    raise current_error
                if not self._select_token(current, token_kind, raise_error=False):
                    raise self._missing_error(operation, "token_missing") from None
                raise self._unavailable_error(
                    operation, "token refresh is unavailable", "refresh_unavailable", True
                ) from None

            reauthenticate()
            current = self._state.snapshot()
            current_error = self._current_validation_error(current, token_kind, grace)
            if self._has_current_candidate(current, token_kind, grace) and current_error is None:
                return self._select_token(current, token_kind)
            if current_error is not None:
                raise current_error
            raise self._missing_after_recovery_error(operation) from None

    def _current_validation_error(
        self, candidate: TokenSet, token_kind: str, grace: int
    ) -> TokenValidationError | None:
        if not self._has_current_candidate(candidate, token_kind, grace):
            return None
        try:
            self._validate_candidate(candidate, nonce=None, operation=f"{token_kind}_token")
        except TokenValidationError as error:
            return error
        return None

    def _has_current_candidate(self, candidate: TokenSet, token_kind: str, grace: int) -> bool:
        token = self._select_token(candidate, token_kind, raise_error=False)
        return bool(token) and (
            candidate.expires_at is None or candidate.expires_at > int(time.time()) + grace
        )

    @staticmethod
    def _select_token(candidate: TokenSet, token_kind: str, raise_error: bool = True) -> str | None:
        token = candidate.access_token if token_kind == "access" else candidate.id_token
        if not token and raise_error:
            operation = f"{token_kind}_token"
            raise TokenLifecycle._missing_error(operation, "token_missing")
        return token

    @staticmethod
    def _missing_error(operation: str, code: str) -> TokenUnavailableError:
        return TokenUnavailableError(
            f"{operation.replace('_token', ' token')} is missing",
            operation=operation,
            stage="token_validation",
            code=code,
            retryable=True,
        )

    @staticmethod
    def _missing_after_recovery_error(operation: str) -> TokenUnavailableError:
        return TokenLifecycle._missing_error(operation, "token_missing_after_recovery")

    @staticmethod
    def _unavailable_error(operation: str, message: str, code: str, retryable: bool) -> TokenUnavailableError:
        return TokenUnavailableError(
            message, operation=operation, stage="refresh", code=code, retryable=retryable
        )

    def _validate_candidate(self, candidate: TokenSet, *, nonce: str | None, operation: str) -> AuthResult:
        if not candidate.access_token:
            raise self._token_error(operation, "access token is missing", "token_missing", True)
        access_error = None
        try:
            access = self._verifier.verify_access_token(candidate.access_token, self._config.scopes)
        except TokenValidationError as error:
            access_error = self._token_error(operation, "token validation failed", error.code, error.retryable)
        if access_error is not None:
            raise access_error from _SanitizedVerifierCause()
        identity_claims = None
        if candidate.id_token:
            id_error = None
            try:
                identity_claims = self._verifier.verify_id_token(candidate.id_token, nonce=nonce)
            except TokenValidationError as error:
                id_error = self._token_error(operation, "token validation failed", error.code, error.retryable)
            if id_error is not None:
                raise id_error from _SanitizedVerifierCause()
        if identity_claims is not None and identity_claims.subject != access.subject:
            raise self._token_error(operation, "token subjects do not match", "subject_mismatch", False)
        subject = identity_claims.subject if identity_claims is not None else access.subject
        identity = Identity(
            issuer=self._config.issuer,
            subject=subject,
            email=identity_claims.email if identity_claims is not None else None,
            name=identity_claims.name if identity_claims is not None else None,
            coseeing_identity=access.coseeing_identity,
        )
        return AuthResult(
            identity=identity,
            access_token_expires_at=candidate.expires_at,
            id_token_expires_at=identity_claims.expires_at if identity_claims is not None else None,
            has_refresh_token=bool(candidate.refresh_token),
        )

    @staticmethod
    def _token_error(operation: str, message: str, code: str, retryable: bool) -> TokenValidationError:
        return TokenValidationError(
            message,
            operation=operation,
            stage="token_validation",
            code=code,
            retryable=retryable,
        )


def merge_refresh_candidate(
    response: TokenSet,
    previous: TokenSet,
    supplied_refresh_token: str | None,
) -> TokenSet:
    return TokenSet(
        access_token=response.access_token,
        refresh_token=response.refresh_token or supplied_refresh_token or previous.refresh_token,
        id_token=response.id_token or previous.id_token,
        expires_at=response.expires_at,
    )


class _SanitizedVerifierCause(Exception):
    def __init__(self) -> None:
        super().__init__("token verifier rejected candidate")
