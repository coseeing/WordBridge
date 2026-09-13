from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit

from .errors import ConfigurationError


class LogoutMode(str, Enum):
    PROVIDER_CONFIRMED = "provider_confirmed"
    LOCAL_ONLY = "local_only"


@dataclass(frozen=True)
class AuthConfig:
    issuer: str
    client_id: str
    scopes: tuple[str, ...]
    login_redirect_uri: str
    logout_redirect_uri: str | None
    callback_timeout: int = 180

    def __post_init__(self) -> None:
        issuer = self.issuer.rstrip("/")
        scopes = tuple(sorted(set(self.scopes)))
        if not issuer.startswith("https://"):
            raise ConfigurationError("issuer must use https")
        if not self.client_id:
            raise ConfigurationError("client_id is required")
        if "openid" not in scopes:
            raise ConfigurationError("openid scope is required")
        if self.callback_timeout <= 0:
            raise ConfigurationError("callback_timeout must be positive")
        _validate_loopback_uri(self.login_redirect_uri)
        if self.logout_redirect_uri is not None:
            _validate_loopback_uri(self.logout_redirect_uri)
            if urlsplit(self.login_redirect_uri).path == urlsplit(self.logout_redirect_uri).path:
                raise ConfigurationError("login and logout callback paths must differ")
        object.__setattr__(self, "issuer", issuer)
        object.__setattr__(self, "scopes", scopes)


def _validate_loopback_uri(uri: str) -> None:
    parsed = urlsplit(uri)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
        raise ConfigurationError("callback URI must use http and literal 127.0.0.1")
    try:
        port = parsed.port
    except ValueError as error:
        raise ConfigurationError("callback URI port must be between 1 and 65535") from error
    if port is None:
        raise ConfigurationError("callback URI requires an explicit port")
    if not 1 <= port <= 65535:
        raise ConfigurationError("callback URI port must be between 1 and 65535")
    if parsed.path in ("", "/"):
        raise ConfigurationError("callback URI requires a non-empty callback path")
    if parsed.query or parsed.fragment:
        raise ConfigurationError("callback URI must not contain query or fragment")


@dataclass(frozen=True)
class Identity:
    issuer: str
    subject: str
    email: str | None
    name: str | None
    coseeing_identity: str | None


@dataclass(frozen=True)
class AuthResult:
    identity: Identity
    access_token_expires_at: int | None
    id_token_expires_at: int | None
    has_refresh_token: bool


@dataclass(frozen=True)
class LogoutResult:
    mode: LogoutMode


@dataclass(frozen=True, repr=False)
class TokenSet:
    access_token: str | None = None
    refresh_token: str | None = None
    id_token: str | None = None
    expires_at: int | None = None

    def __repr__(self) -> str:
        return (
            "TokenSet(access_token=<redacted>, refresh_token=<redacted>, "
            f"id_token=<redacted>, expires_at={self.expires_at!r})"
        )


@dataclass(frozen=True)
class VerifiedClaims:
    subject: str
    email: str | None = None
    name: str | None = None
    coseeing_identity: str | None = None
    expires_at: int | None = None
    scopes: frozenset[str] = frozenset()


@dataclass(frozen=True)
class OidcMetadata:
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    introspection_endpoint: str | None
    end_session_endpoint: str | None
