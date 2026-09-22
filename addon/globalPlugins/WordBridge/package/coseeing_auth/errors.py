import os
import traceback

# Enough frames to cross a package boundary and still name the call that went
# wrong, without turning one log line into a screenful.
_FAILURE_SITE_FRAMES = 6


def failure_site(error: BaseException) -> str:
    """Locate a failure the mapping layer could not name, leaking no values.

    `CoseeingAuthClient._map_login_error()` folds every exception it does not
    recognise into a single `token_exchange_failed`, and `_safe_cause()` then
    replaces the exception with its bare type name -- so a `TypeError` raised
    anywhere inside the token exchange reaches the log with nothing at all to
    locate it by.

    Only the type name and the innermost frames are rendered, innermost first,
    each as `basename:lineno:function`. `str(error)`, the exception's args and
    the frames' source lines are all excluded, so a token, URL or user string
    carried by the exception cannot reach the log through this. The basename
    alone (never the full path) keeps the Windows user directory out of it,
    matching the rule the rest of this package's logging already follows.
    """
    frames = traceback.extract_tb(error.__traceback__)[-_FAILURE_SITE_FRAMES:]
    site = " < ".join(
        f"{os.path.basename(frame.filename)}:{frame.lineno}:{frame.name}"
        for frame in reversed(frames)
    )
    if not site:
        return type(error).__name__
    return f"{type(error).__name__} at {site}"


class AuthError(Exception):
    default_operation: str | None = None
    default_stage: str | None = None
    default_code: str | None = None

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        stage: str | None = None,
        code: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.operation = operation or self.default_operation
        self.stage = stage or self.default_stage
        self.code = code or self.default_code
        if self.operation is None or self.stage is None or self.code is None:
            raise TypeError("operation, stage, and code are required")
        self.retryable = bool(retryable)


class ConfigurationError(AuthError):
    default_operation = "configure"
    default_stage = "configuration"
    default_code = "invalid_config"


class DiscoveryError(AuthError):
    default_operation = "configure"
    default_stage = "discovery"
    default_code = "discovery_invalid_metadata"


class LoginError(AuthError):
    default_operation = "login"
    default_stage = "authorization"
    default_code = "login_failed"


class LogoutError(AuthError):
    default_operation = "logout"
    default_stage = "logout"
    default_code = "logout_failed"


class RestoreError(AuthError):
    default_operation = "restore"
    default_stage = "refresh"
    default_code = "restore_failed"


class TokenPersistenceError(AuthError):
    default_operation = "storage"
    default_stage = "token_persistence"
    default_code = "storage_failed"


class TokenUnavailableError(AuthError):
    default_operation = "access_token"
    default_stage = "token_validation"
    default_code = "token_missing"


class TokenValidationError(AuthError):
    default_operation = "access_token"
    default_stage = "token_validation"
    default_code = "token_invalid"


class ScopeError(TokenValidationError):
    def __init__(self, message: str, *, operation: str = "access_token") -> None:
        super().__init__(
            message,
            operation=operation,
            stage="scope_validation",
            code="scope_missing",
            retryable=False,
        )


class AuthFlowInProgressError(AuthError):
    def __init__(self, operation: str) -> None:
        super().__init__(
            "another interactive authentication flow is already running",
            operation=operation,
            stage="concurrency",
            code="flow_in_progress",
            retryable=True,
        )


class ClientClosedError(AuthError):
    def __init__(self, operation: str) -> None:
        super().__init__(
            "authentication client is closed",
            operation=operation,
            stage="concurrency",
            code="client_closed",
            retryable=False,
        )
