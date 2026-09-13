from dataclasses import dataclass
import secrets
import string
from threading import Lock
from typing import Any, Callable
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

import requests
from authlib.integrations.requests_client import OAuth2Session

from .errors import DiscoveryError
from .models import AuthConfig, OidcMetadata, TokenSet


_DISCOVERY_TIMEOUT = 20
_TOKEN_TIMEOUT = 6
_PKCE_ALPHABET = string.ascii_letters + string.digits + "-._~"


@dataclass(frozen=True)
class AuthorizationRequest:
    url: str
    state: str
    nonce: str
    code_verifier: str


class OidcProtocol:
    def __init__(
        self,
        config: AuthConfig,
        *,
        http: Any | None = None,
        oauth_session_factory: Callable[..., Any] = OAuth2Session,
    ) -> None:
        self._config = config
        self._http = http if http is not None else requests.Session()
        self._oauth_session_factory = oauth_session_factory
        self._metadata: OidcMetadata | None = None
        self._discovery_lock = Lock()
        self._resource_lock = Lock()
        self._cleanup_lock = Lock()
        self._oauth_sessions: list[Any] = []
        self._closed = False
        self._http_closed = False

    def discovery(self) -> OidcMetadata:
        metadata = self._metadata
        if metadata is not None:
            return metadata
        with self._discovery_lock:
            metadata = self._metadata
            if metadata is not None:
                return metadata
            try:
                response = self._http.get(
                    f"{self._config.issuer}/.well-known/openid-configuration",
                    timeout=_DISCOVERY_TIMEOUT,
                )
                response.raise_for_status()
            except (requests.RequestException, OSError, ValueError) as error:
                raise DiscoveryError(
                    "OIDC discovery request failed",
                    code="discovery_network_error",
                    retryable=True,
                ) from None
            try:
                body = response.json()
                metadata = OidcMetadata(
                    authorization_endpoint=_https_endpoint(body, "authorization_endpoint"),
                    token_endpoint=_https_endpoint(body, "token_endpoint"),
                    jwks_uri=_https_endpoint(body, "jwks_uri"),
                    introspection_endpoint=_optional_https_endpoint(body, "introspection_endpoint"),
                    end_session_endpoint=_optional_https_endpoint(body, "end_session_endpoint"),
                )
            except (TypeError, ValueError, KeyError) as error:
                raise DiscoveryError("OIDC discovery metadata is invalid") from None
            self._metadata = metadata
            return metadata

    def _oauth(self) -> Any:
        with self._resource_lock:
            if self._closed:
                raise RuntimeError("OIDC protocol is closed")
        session = self._oauth_session_factory(
            client_id=self._config.client_id,
            scope=" ".join(self._config.scopes),
            redirect_uri=self._config.login_redirect_uri,
            code_challenge_method="S256",
        )
        with self._cleanup_lock:
            late_session = False
            with self._resource_lock:
                if self._closed:
                    self._oauth_sessions.append(session)
                    late_session = True
                else:
                    self._oauth_sessions.append(session)
            if late_session:
                cleanup_error = None
                try:
                    _close_owned(session)
                except Exception as error:
                    cleanup_error = error
                else:
                    with self._resource_lock:
                        self._oauth_sessions = [
                            owned for owned in self._oauth_sessions if owned is not session
                        ]
                if cleanup_error is not None:
                    raise RuntimeError("OIDC protocol is closed") from _safe_protocol_cause(
                        cleanup_error
                    )
                raise RuntimeError("OIDC protocol is closed")
            return session

    def close(self) -> None:
        with self._cleanup_lock:
            with self._resource_lock:
                self._closed = True
                sessions = tuple(self._oauth_sessions)
                http_closed = self._http_closed
            failures = []
            closed_sessions = []
            for session in sessions:
                try:
                    _close_owned(session)
                except Exception:
                    failures.append(session)
                else:
                    closed_sessions.append(session)
            if not http_closed:
                try:
                    _close_owned(self._http)
                except Exception:
                    failures.append(self._http)
                else:
                    http_closed = True
            with self._resource_lock:
                self._oauth_sessions = [
                    session
                    for session in self._oauth_sessions
                    if not any(session is closed for closed in closed_sessions)
                ]
                self._http_closed = http_closed
            if failures:
                raise _ProtocolCleanupError()

    def begin_authorization(self) -> AuthorizationRequest:
        metadata = self.discovery()
        code_verifier = _random_string(48)
        nonce = _random_string(24)
        url, state = self._oauth().create_authorization_url(
            metadata.authorization_endpoint,
            redirect_uri=self._config.login_redirect_uri,
            code_challenge_method="S256",
            code_verifier=code_verifier,
            nonce=nonce,
        )
        return AuthorizationRequest(url=url, state=state, nonce=nonce, code_verifier=code_verifier)

    def exchange_callback(self, request: AuthorizationRequest, callback_url: str) -> TokenSet:
        body = self._oauth().fetch_token(
            self.discovery().token_endpoint,
            authorization_response=callback_url,
            state=request.state,
            code_verifier=request.code_verifier,
            include_client_id=True,
            timeout=_TOKEN_TIMEOUT,
        )
        return _token_set(body)

    def refresh(self, refresh_token: str) -> TokenSet:
        body = self._oauth().refresh_token(
            self.discovery().token_endpoint,
            refresh_token=refresh_token,
            include_client_id=True,
            timeout=_TOKEN_TIMEOUT,
        )
        return _token_set(body)

    def end_session_endpoint(self) -> str | None:
        return self.discovery().end_session_endpoint

    def build_logout_url(self, state: str, id_token: str | None = None) -> str | None:
        endpoint = self.end_session_endpoint()
        if endpoint is None:
            return None
        parsed = urlsplit(endpoint)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        params["state"] = state
        if self._config.logout_redirect_uri is not None:
            params["post_logout_redirect_uri"] = self._config.logout_redirect_uri
        if id_token is not None:
            params["id_token_hint"] = id_token
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params), parsed.fragment))


def _random_string(length: int) -> str:
    return "".join(secrets.choice(_PKCE_ALPHABET) for _ in range(length))


def _https_endpoint(body: dict[str, Any], name: str) -> str:
    value = body[name]
    if not _is_https_url(value):
        raise ValueError(name)
    return value


def _optional_https_endpoint(body: dict[str, Any], name: str) -> str | None:
    if name not in body or body[name] is None:
        return None
    return _https_endpoint(body, name)


def _is_https_url(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if any(character.isspace() for character in value):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
        hostname = parsed.hostname
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and bool(hostname)
        and parsed.username is None
        and parsed.password is None
        and parsed.fragment == ""
        and (port is None or 1 <= port <= 65535)
    )


def _token_set(body: dict[str, Any]) -> TokenSet:
    return TokenSet(
        access_token=body.get("access_token"),
        refresh_token=body.get("refresh_token"),
        id_token=body.get("id_token"),
        expires_at=body.get("expires_at"),
    )


def _close_owned(resource: Any) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        close()


class _ProtocolCleanupError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("OIDC protocol cleanup failed")


class _SafeProtocolCause(Exception):
    def __init__(self) -> None:
        super().__init__("OIDC protocol resource cleanup failed")


def _safe_protocol_cause(_error: Exception) -> Exception:
    return _SafeProtocolCause()
