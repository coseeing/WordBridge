import threading
from typing import Protocol, runtime_checkable

from ..errors import TokenPersistenceError


@runtime_checkable
class RefreshTokenStore(Protocol):
    def load(self) -> str | None: ...

    def save(self, token: str) -> None: ...

    def delete(self) -> None: ...


_UNKNOWN = object()


class _SanitizedStorageCause(Exception):
    def __init__(self, action: str) -> None:
        super().__init__(f"refresh token storage {action} failed")


class RefreshTokenPersistence:
    def __init__(self, store: RefreshTokenStore | None = None) -> None:
        self._store = store
        self._persisted: str | None | object = _UNKNOWN
        self._lock = threading.RLock()

    def load(self, operation: str) -> str | None:
        if self._store is None:
            return None
        with self._lock:
            value = self._call("read", operation, self._store.load)
            if value is not None and (not isinstance(value, str) or not value):
                raise TokenPersistenceError(
                    "stored refresh token is invalid",
                    operation=operation,
                    code="storage_value_invalid",
                    retryable=False,
                ) from _SanitizedStorageCause("read")
            self._persisted = value
            return value

    def save_if_changed(self, token: str | None, operation: str) -> None:
        if self._store is None or not token:
            return
        with self._lock:
            if self._persisted is not _UNKNOWN and self._persisted == token:
                return
            self._call("write", operation, self._store.save, token)
            self._persisted = token

    def delete(self, operation: str) -> None:
        if self._store is None:
            return
        with self._lock:
            self._call("delete", operation, self._store.delete)
            self._persisted = None

    @staticmethod
    def _call(action: str, operation: str, method, *args):
        code = {
            "read": "storage_read_failed",
            "write": "storage_write_failed",
            "delete": "storage_delete_failed",
        }[action]
        mapped_code = code
        retryable = False
        try:
            return method(*args)
        except TokenPersistenceError as error:
            mapped_code = error.code if error.code != "storage_failed" else code
            retryable = error.retryable
        except Exception:
            pass
        error = TokenPersistenceError(
            f"refresh token storage {action} failed",
            operation=operation,
            code=mapped_code,
            retryable=retryable,
        )
        raise error from _SanitizedStorageCause(action)
