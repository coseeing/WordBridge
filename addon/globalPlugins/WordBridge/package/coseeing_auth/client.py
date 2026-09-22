import logging
import secrets
import threading
import webbrowser
from typing import Callable
from urllib.parse import parse_qs, urlsplit

import requests
from authlib.oauth2.rfc6749.errors import MismatchingStateException, OAuth2Error

from .callback import CallbackCancelled, CallbackTimeout, LoopbackCallbackReceiver, rebuild_callback_url
from .errors import (
    AuthFlowInProgressError,
    ClientClosedError,
    DiscoveryError,
    LoginError,
    LogoutError,
    TokenPersistenceError,
    TokenValidationError,
    failure_site,
)
from .models import AuthConfig, AuthResult, Identity, LogoutMode, LogoutResult
from .oidc import OidcProtocol
from .storage.storage import RefreshTokenPersistence, RefreshTokenStore
from .tokens import TokenLifecycle, TokenState
from .verification import TokenVerifier


class CoseeingAuthClient:
    def __init__(
        self,
        config: AuthConfig,
        *,
        browser_open: Callable[[str], bool] = webbrowser.open,
        logger=None,
        refresh_token_store: RefreshTokenStore | None = None,
    ) -> None:
        protocol = OidcProtocol(config)
        verifier = TokenVerifier(config, protocol.discovery)
        persistence = RefreshTokenPersistence(refresh_token_store)
        lifecycle = TokenLifecycle(config, protocol, verifier, TokenState(), persistence)
        self._configure(
            config,
            browser_open,
            logger,
            protocol,
            verifier,
            lifecycle,
            LoopbackCallbackReceiver,
        )

    @classmethod
    def _from_components(
        cls,
        config: AuthConfig,
        browser_open,
        logger,
        protocol,
        verifier,
        lifecycle,
        callback_factory,
    ):
        client = cls.__new__(cls)
        client._configure(
            config,
            browser_open,
            logger,
            protocol,
            verifier,
            lifecycle,
            callback_factory,
        )
        return client

    def _configure(
        self,
        config,
        browser_open,
        logger,
        protocol,
        verifier,
        lifecycle,
        callback_factory,
    ) -> None:
        self._config = config
        self._browser_open = browser_open
        self._logger = logger if logger is not None else logging.getLogger(__name__)
        self._protocol = protocol
        self._verifier = verifier
        self._lifecycle = lifecycle
        self._callback_factory = callback_factory
        self._interactive_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._operation_condition = threading.Condition(self._state_lock)
        self._inflight_operations = 0
        self._active_operation_threads = {}
        self._closing = False
        self._cleanup_lock = threading.Lock()
        self._active_receiver = None
        self._active_operation = None
        self._interactive_leased = False
        self._closed = False
        self._protocol_closed = False
        self._receiver_cancelled = False
        self._receiver_cancel_attempted = False

    def login(self) -> AuthResult:
        receiver = self._begin_interactive("login", self._config.login_redirect_uri, lease=True)
        pending = None
        result = None
        try:
            try:
                result = self._login_flow(receiver)
            except TokenPersistenceError as error:
                pending = (error, _safe_cause(error, "login persistence failure"))
            except LoginError as error:
                pending = (error, error.__cause__ or _safe_cause(error, "login failure"))
            except CallbackTimeout as error:
                mapped = LoginError(
                    "waiting for authorization callback timed out",
                    operation="login", stage="callback", code="callback_timeout", retryable=True,
                )
                pending = (mapped, _safe_cause(error, "callback wait timed out"))
            except CallbackCancelled as error:
                mapped = LoginError(
                    "authorization callback was cancelled",
                    operation="login", stage="callback", code="callback_cancelled", retryable=True,
                )
                pending = (mapped, _safe_cause(error, "callback wait was cancelled"))
            except Exception as error:
                mapped = self._map_login_error(error, self._login_stage)
                self._log("error", f"login failed during {mapped.stage}: {failure_site(error)}")
                pending = (mapped, _safe_cause(error, mapped.code))
        finally:
            cleanup_error = None
            try:
                receiver.close()
            except Exception as error:
                cleanup_error = error
                self._log("error", "interactive callback cleanup failed")
            finally:
                self._end_interactive(receiver)
            if cleanup_error is not None and pending is None:
                mapped = LoginError(
                    "interactive callback cleanup failed",
                    operation="login",
                    stage="callback",
                    code="callback_failed",
                    retryable=True,
                )
                pending = (mapped, _safe_cause(cleanup_error, "callback cleanup failed"))
        if pending is not None:
            raise pending[0] from pending[1]
        return result

    def logout(self) -> LogoutResult:
        self._ensure_open("logout")
        tokens = self._lifecycle.snapshot()
        if not tokens.id_token or not self._config.logout_redirect_uri:
            return self.logout_local()

        receiver = self._begin_interactive("logout", self._config.logout_redirect_uri, lease=True)
        pending = None
        try:
            self._logout_stage = "discovery"
            endpoint = self._protocol.end_session_endpoint()
            if not endpoint:
                self._lifecycle.clear(operation="logout")
                return LogoutResult(mode=LogoutMode.LOCAL_ONLY)
            state = secrets.token_urlsafe(32)
            logout_url = self._protocol.build_logout_url(state, id_token=tokens.id_token)
            if not logout_url:
                self._lifecycle.clear(operation="logout")
                return LogoutResult(mode=LogoutMode.LOCAL_ONLY)
            self._logout_stage = "callback"
            receiver.start()
            self._logout_stage = "browser"
            if not self._browser_open(logout_url):
                rejected = RuntimeError("browser opener returned false")
                raise LogoutError(
                    "failed to open logout URL",
                    operation="logout", stage="browser", code="browser_open_failed", retryable=True,
                ) from rejected
            self._logout_stage = "callback"
            target = receiver.wait(self._config.callback_timeout)
            callback_url = rebuild_callback_url(self._config.logout_redirect_uri, target)
            query = parse_qs(urlsplit(callback_url).query)
            if "error" in query:
                raise LogoutError(
                    "provider logout failed",
                    operation="logout", stage="logout", code="provider_logout_error", retryable=True,
                ) from _safe_cause(ValueError(), "provider logout error")
            returned_state = (query.get("state") or [None])[0]
            if returned_state != state:
                raise LogoutError(
                    "logout response state did not match",
                    operation="logout", stage="logout", code="state_mismatch", retryable=False,
                ) from _safe_cause(ValueError(), "logout callback state mismatch")
            self._lifecycle.clear(operation="logout")
            return LogoutResult(mode=LogoutMode.PROVIDER_CONFIRMED)
        except TokenPersistenceError as error:
            pending = (error, _safe_cause(error, "logout persistence failure"))
        except LogoutError as error:
            pending = (error, error.__cause__ or _safe_cause(error, "logout failure"))
        except DiscoveryError as error:
            mapped = LogoutError(
                "OIDC discovery failed",
                operation="logout", stage="discovery", code=error.code, retryable=error.retryable,
            )
            pending = (mapped, _safe_cause(error, "logout discovery failed"))
        except CallbackTimeout as error:
            mapped = LogoutError(
                "waiting for logout callback timed out",
                operation="logout", stage="callback", code="callback_timeout", retryable=True,
            )
            pending = (mapped, _safe_cause(error, "logout callback timed out"))
        except CallbackCancelled as error:
            mapped = LogoutError(
                "logout callback was cancelled",
                operation="logout", stage="callback", code="callback_cancelled", retryable=True,
            )
            pending = (mapped, _safe_cause(error, "logout callback was cancelled"))
        except Exception as error:
            mapped = self._map_logout_error(error, getattr(self, "_logout_stage", "callback"))
            pending = (mapped, _safe_cause(error, mapped.code))
        finally:
            cleanup_error = None
            try:
                receiver.close()
            except Exception as error:
                cleanup_error = error
                self._log("error", "interactive callback cleanup failed")
            finally:
                self._end_interactive(receiver)
            if cleanup_error is not None and pending is None:
                mapped = LogoutError(
                    "interactive callback cleanup failed",
                    operation="logout", stage="callback", code="callback_failed", retryable=True,
                )
                pending = (mapped, _safe_cause(cleanup_error, "callback cleanup failed"))
        if pending is not None:
            raise pending[0] from pending[1]

    def logout_local(self) -> LogoutResult:
        with self._open_operation("logout"):
            self._lifecycle.clear(operation="logout")
            return LogoutResult(mode=LogoutMode.LOCAL_ONLY)

    def _ensure_open(self, operation: str) -> None:
        with self._state_lock:
            if self._closed or self._closing:
                raise ClientClosedError(_closed_operation(operation))

    def _login_flow(self, receiver) -> AuthResult:
        self._login_stage = "authorization"
        request = self._protocol.begin_authorization()
        self._login_stage = "callback"
        receiver.start()
        self._login_stage = "browser"
        if not self._browser_open(request.url):
            rejected = RuntimeError("browser opener returned false")
            raise LoginError(
                "failed to open authorization URL",
                operation="login", stage="browser", code="browser_open_failed", retryable=True,
            ) from rejected
        self._login_stage = "callback"
        target = receiver.wait(self._config.callback_timeout)
        callback_url = rebuild_callback_url(self._config.login_redirect_uri, target)
        query = parse_qs(urlsplit(callback_url).query)
        if "error" in query and "code" not in query:
            if (query.get("state") or [None])[0] != request.state:
                mapped = LoginError(
                    "authorization response state did not match",
                    operation="login", stage="authorization", code="state_mismatch", retryable=False,
                )
                raise mapped from _safe_cause(ValueError(), "callback state mismatch")
            error_code = (query.get("error") or [None])[0]
            if error_code == "access_denied":
                mapped = LoginError(
                    "authorization was denied",
                    operation="login", stage="authorization", code="authorization_denied", retryable=True,
                )
                raise mapped from _safe_cause(OSError(), "authorization denied")
            mapped = LoginError(
                "authorization response contained an error",
                operation="login", stage="authorization", code="authorization_error", retryable=True,
            )
            raise mapped from _safe_cause(ValueError(), "authorization response error")
        self._login_stage = "token_exchange"
        candidate = self._protocol.exchange_callback(request, callback_url)
        self._login_stage = "token_validation"
        return self._lifecycle.accept_login(candidate, nonce=request.nonce)

    def restore(self, refresh_token: str) -> AuthResult:
        with self._open_operation("restore"):
            return self._lifecycle.restore(refresh_token)

    def restore_saved_session(self) -> AuthResult | None:
        with self._open_operation("restore_saved_session"):
            return self._lifecycle.restore_saved_session()

    def get_identity(self) -> Identity:
        with self._open_operation("identity"):
            return self._lifecycle.identity()

    def get_access_token(self, *, grace: int = 60, auto_login: bool = True) -> str:
        with self._operation_lease("access_token"):
            return self._lifecycle.get_access_token(grace, auto_login, self.login)

    def get_id_token(self, *, grace: int = 60, auto_login: bool = True) -> str:
        with self._operation_lease("id_token"):
            return self._lifecycle.get_id_token(grace, auto_login, self.login)

    def get_refresh_token(self) -> str | None:
        with self._open_operation("refresh_token"):
            return self._lifecycle.get_refresh_token()

    def cancel_interactive_flow(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            receiver = self._active_receiver
        if receiver is not None:
            receiver.cancel()

    def close(self) -> None:
        current_thread = threading.get_ident()
        receiver = None
        with self._operation_condition:
            self._closing = True
            owned_operations = self._active_operation_threads.get(current_thread, 0)
            receiver = self._active_receiver
        if receiver is not None:
            with self._cleanup_lock:
                with self._state_lock:
                    receiver_cancelled = self._receiver_cancelled
                    cancel_attempted = self._receiver_cancel_attempted
                if not receiver_cancelled and not cancel_attempted:
                    with self._state_lock:
                        self._receiver_cancel_attempted = True
                    try:
                        receiver.cancel()
                    except Exception:
                        self._log("error", "interactive callback cleanup failed")
                    else:
                        with self._state_lock:
                            self._receiver_cancelled = True
        if owned_operations:
            return
        with self._operation_condition:
            while self._inflight_operations:
                self._operation_condition.wait()
        self._finish_close()

    def _finish_close(self) -> None:
        with self._cleanup_lock:
            with self._operation_condition:
                if self._inflight_operations:
                    return
                self._closed = True
                receiver = self._active_receiver
            if receiver is not None:
                with self._state_lock:
                    receiver_cancelled = self._receiver_cancelled
                    cancel_attempted = self._receiver_cancel_attempted
                if not receiver_cancelled and not cancel_attempted:
                    with self._state_lock:
                        self._receiver_cancel_attempted = True
                    try:
                        receiver.cancel()
                    except Exception:
                        self._log("error", "interactive callback cleanup failed")
                        with self._state_lock:
                            self._receiver_cancel_attempted = False
                    else:
                        with self._state_lock:
                            self._receiver_cancelled = True
            with self._state_lock:
                protocol_closed = self._protocol_closed
            if not protocol_closed:
                try:
                    self._protocol.close()
                except Exception:
                    self._log("error", "OIDC protocol cleanup failed")
                else:
                    with self._state_lock:
                        self._protocol_closed = True
            with self._state_lock:
                if not self._receiver_cancelled:
                    self._receiver_cancel_attempted = False

    def _begin_interactive(self, operation: str, redirect_uri: str, *, lease: bool = False):
        with self._state_lock:
            if self._closed or (self._closing and not self._thread_owns_operation_locked()):
                raise ClientClosedError(_closed_operation(operation))
        if not self._interactive_lock.acquire(blocking=False):
            raise AuthFlowInProgressError(operation)
        try:
            with self._state_lock:
                if self._closed or (self._closing and not self._thread_owns_operation_locked()):
                    raise ClientClosedError(_closed_operation(operation))
                receiver = self._callback_factory(redirect_uri)
                self._active_receiver = receiver
                self._active_operation = operation
                self._receiver_cancelled = False
                self._receiver_cancel_attempted = False
                self._interactive_leased = lease
                if lease:
                    self._inflight_operations += 1
                    thread_id = threading.get_ident()
                    self._active_operation_threads[thread_id] = (
                        self._active_operation_threads.get(thread_id, 0) + 1
                    )
            return receiver
        except Exception:
            self._interactive_lock.release()
            raise

    def _end_interactive(self, receiver) -> None:
        release = False
        should_finish = False
        with self._state_lock:
            if self._active_receiver is receiver:
                self._active_receiver = None
                self._active_operation = None
                release = True
                if self._interactive_leased:
                    self._inflight_operations -= 1
                    thread_id = threading.get_ident()
                    owned = self._active_operation_threads[thread_id] - 1
                    if owned:
                        self._active_operation_threads[thread_id] = owned
                    else:
                        del self._active_operation_threads[thread_id]
                    self._operation_condition.notify_all()
                    should_finish = self._closing and not self._inflight_operations and not self._closed
                self._interactive_leased = False
        if release:
            self._interactive_lock.release()
        if should_finish:
            self._finish_close()

    class _OpenOperation:
        def __init__(self, client, operation: str) -> None:
            self._client = client
            self._operation = operation

        def __enter__(self):
            self._client._state_lock.acquire()
            if self._client._closed or self._client._closing:
                self._client._state_lock.release()
                raise ClientClosedError(_closed_operation(self._operation))
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self._client._state_lock.release()

    class _OperationLease:
        def __init__(self, client, operation: str) -> None:
            self._client = client
            self._operation = operation

        def __enter__(self):
            with self._client._operation_condition:
                if self._client._closed or self._client._closing:
                    raise ClientClosedError(_closed_operation(self._operation))
                self._client._inflight_operations += 1
                thread_id = threading.get_ident()
                self._client._active_operation_threads[thread_id] = (
                    self._client._active_operation_threads.get(thread_id, 0) + 1
                )
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            with self._client._operation_condition:
                self._client._inflight_operations -= 1
                thread_id = threading.get_ident()
                owned = self._client._active_operation_threads[thread_id] - 1
                if owned:
                    self._client._active_operation_threads[thread_id] = owned
                else:
                    del self._client._active_operation_threads[thread_id]
                self._client._operation_condition.notify_all()
                should_finish = (
                    not self._client._inflight_operations
                    and self._client._closing
                    and not self._client._closed
                )
            if should_finish:
                self._client._finish_close()

    def _operation_lease(self, operation: str):
        return self._OperationLease(self, operation)

    def _thread_owns_operation_locked(self) -> bool:
        return bool(self._active_operation_threads.get(threading.get_ident(), 0))

    def _open_operation(self, operation: str):
        return self._OpenOperation(self, operation)

    def _log(self, level: str, message: str) -> None:
        try:
            method = getattr(self._logger, level, None)
            if callable(method):
                method(message)
            elif callable(self._logger):
                self._logger(level, message)
        except Exception:
            return

    @staticmethod
    def _map_login_error(error: Exception, stage: str) -> LoginError:
        if isinstance(error, DiscoveryError):
            return LoginError(
                "OIDC discovery failed",
                operation="login", stage="discovery", code=error.code, retryable=error.retryable,
            )
        if stage == "browser":
            return LoginError(
                "failed to open authorization URL",
                operation="login", stage="browser", code="browser_open_failed", retryable=True,
            )
        if isinstance(error, MismatchingStateException):
            return LoginError(
                "authorization response state did not match",
                operation="login", stage="authorization", code="state_mismatch", retryable=False,
            )
        if isinstance(error, OAuth2Error):
            if getattr(error, "error", None) == "access_denied":
                return LoginError(
                    "authorization was denied",
                    operation="login", stage="authorization", code="authorization_denied", retryable=True,
                )
            return LoginError(
                "token exchange was rejected",
                operation="login", stage="token_exchange", code="token_exchange_rejected", retryable=False,
            )
        if isinstance(error, requests.RequestException):
            if stage != "token_exchange":
                return LoginError(
                    "login request failed",
                    operation="login", stage=stage, code=_stage_failure_code(stage), retryable=True,
                )
            return LoginError(
                "token endpoint request failed",
                operation="login", stage="token_exchange", code="token_endpoint_network_error", retryable=True,
            )
        if isinstance(error, OSError):
            if stage != "token_exchange":
                return LoginError(
                    "login request failed",
                    operation="login", stage=stage, code=_stage_failure_code(stage), retryable=True,
                )
            return LoginError(
                "token endpoint request failed",
                operation="login", stage="token_exchange", code="token_endpoint_network_error", retryable=True,
            )
        if isinstance(error, TokenValidationError):
            return LoginError(
                "token validation failed",
                operation="login", stage="token_validation", code=error.code, retryable=error.retryable,
            )
        if stage == "authorization":
            return LoginError(
                "authorization could not be started",
                operation="login", stage="authorization", code="authorization_failed", retryable=True,
            )
        if stage == "callback":
            return LoginError(
                "authorization callback was invalid",
                operation="login", stage="callback", code="invalid_callback", retryable=True,
            )
        if stage == "token_validation":
            # Without this, an unrecognised failure while validating the token
            # -- a TypeError out of PyJWT, say -- fell through to the clause
            # below and was reported as a token_exchange failure. The exchange
            # had already succeeded by then, so the log pointed at the wrong
            # stage entirely, and at the token endpoint rather than at the
            # verifier.
            return LoginError(
                "token validation failed",
                operation="login", stage="token_validation", code="token_validation_failed",
                retryable=False,
            )
        # Every remaining stage keeps the historical code. The name is wrong
        # for `discovery`, which is the last one that can still reach here, but
        # the codes are a published vocabulary; renaming one is a separate
        # change from fixing the stage that actually misreported.
        return LoginError(
            "token exchange failed",
            operation="login", stage="token_exchange", code="token_exchange_failed", retryable=False,
        )

    @staticmethod
    def _map_logout_error(error: Exception, stage: str) -> LogoutError:
        if isinstance(error, DiscoveryError):
            return LogoutError(
                "OIDC discovery failed",
                operation="logout", stage="discovery", code=error.code, retryable=error.retryable,
            )
        if stage == "browser":
            return LogoutError(
                "failed to open logout URL",
                operation="logout", stage="browser", code="browser_open_failed", retryable=True,
            )
        if stage == "discovery":
            return LogoutError(
                "logout discovery failed",
                operation="logout", stage="discovery", code="logout_failed", retryable=True,
            )
        if isinstance(error, requests.RequestException) or isinstance(error, OSError):
            return LogoutError(
                "logout request failed",
                operation="logout", stage="logout", code="logout_failed", retryable=True,
            )
        return LogoutError(
            "logout failed",
            operation="logout", stage="logout", code="logout_failed", retryable=False,
        )


def _closed_operation(operation: str) -> str:
    if operation == "identity":
        return "access_token"
    if operation == "refresh_token":
        return "restore"
    return operation


def _stage_failure_code(stage: str) -> str:
    if stage == "authorization":
        return "authorization_failed"
    if stage == "callback":
        return "callback_failed"
    return "login_failed"


__all__ = ["CoseeingAuthClient"]


class _SanitizedCause(Exception):
    pass


def _safe_cause(error: Exception, context: str) -> Exception:
    return _SanitizedCause(f"{type(error).__name__}: {context}")
