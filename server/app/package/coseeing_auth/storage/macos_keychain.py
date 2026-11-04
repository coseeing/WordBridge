"""macOS Keychain refresh-token storage backed by Security.framework."""

import ctypes
import sys
from contextlib import ExitStack, contextmanager

from ..errors import TokenPersistenceError


ERR_SEC_SUCCESS = 0
ERR_SEC_DUPLICATE_ITEM = -25299
ERR_SEC_ITEM_NOT_FOUND = -25300
_K_CF_STRING_ENCODING_UTF8 = 0x08000100


@contextmanager
def _owned_cf(reference, release):
    """Release a CoreFoundation object exactly once after its use."""
    if not reference:
        raise MemoryError("CoreFoundation allocation failed")
    try:
        yield reference
    finally:
        release(reference)


class _MacOSKeychainError(Exception):
    """A native error which deliberately omits OSStatus and item details."""

    def __init__(self, action: str, status: int) -> None:
        super().__init__(f"macOS Keychain {action} failed")
        self.status = status


class _SanitizedMacOSCause(Exception):
    def __init__(self, action: str) -> None:
        super().__init__(f"macOS Keychain {action} failed")


class _MacOSBindings:
    """Small ctypes boundary, constructed only when the store is used on macOS."""

    def __init__(self) -> None:
        self._core_foundation = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        self._security = ctypes.CDLL(
            "/System/Library/Frameworks/Security.framework/Security"
        )
        cf_type = ctypes.c_void_p
        self._cf_string_create = self._core_foundation.CFStringCreateWithCString
        self._cf_string_create.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        self._cf_string_create.restype = cf_type
        self._cf_data_create = self._core_foundation.CFDataCreate
        self._cf_data_create.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_long]
        self._cf_data_create.restype = cf_type
        self._cf_data_get_length = self._core_foundation.CFDataGetLength
        self._cf_data_get_length.argtypes = [cf_type]
        self._cf_data_get_length.restype = ctypes.c_long
        self._cf_data_get_byte_ptr = self._core_foundation.CFDataGetBytePtr
        self._cf_data_get_byte_ptr.argtypes = [cf_type]
        self._cf_data_get_byte_ptr.restype = ctypes.POINTER(ctypes.c_ubyte)
        self._cf_dict_create = self._core_foundation.CFDictionaryCreateMutable
        self._cf_dict_create.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]
        self._cf_dict_create.restype = cf_type
        self._cf_dict_set = self._core_foundation.CFDictionarySetValue
        self._cf_dict_set.argtypes = [cf_type, cf_type, cf_type]
        self._cf_dict_set.restype = None
        self._cf_release = self._core_foundation.CFRelease
        self._cf_release.argtypes = [cf_type]
        self._cf_release.restype = None
        self._copy_matching = self._security.SecItemCopyMatching
        self._copy_matching.argtypes = [cf_type, ctypes.POINTER(cf_type)]
        self._copy_matching.restype = ctypes.c_int32
        self._update = self._security.SecItemUpdate
        self._update.argtypes = [cf_type, cf_type]
        self._update.restype = ctypes.c_int32
        self._add = self._security.SecItemAdd
        self._add.argtypes = [cf_type, ctypes.POINTER(cf_type)]
        self._add.restype = ctypes.c_int32
        self._delete = self._security.SecItemDelete
        self._delete.argtypes = [cf_type]
        self._delete.restype = ctypes.c_int32

        self._true = ctypes.c_void_p.in_dll(self._core_foundation, "kCFBooleanTrue")
        for name in (
            "kSecClass", "kSecClassGenericPassword", "kSecAttrService", "kSecAttrAccount",
            "kSecReturnData", "kSecValueData",
        ):
            setattr(self, name, ctypes.c_void_p.in_dll(self._security, name))

    @contextmanager
    def _string(self, value: str):
        encoded = value.encode("utf-8")
        with _owned_cf(self._cf_string_create(None, encoded, _K_CF_STRING_ENCODING_UTF8), self._cf_release) as ref:
            yield ref

    @contextmanager
    def _data(self, payload: bytes):
        buffer = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
        with _owned_cf(self._cf_data_create(None, buffer, len(payload)), self._cf_release) as ref:
            yield ref

    @contextmanager
    def _identity_query(self, service: str, account: str):
        with ExitStack() as stack:
            query = stack.enter_context(_owned_cf(self._cf_dict_create(None, 0, None, None), self._cf_release))
            service_ref = stack.enter_context(self._string(service))
            account_ref = stack.enter_context(self._string(account))
            self._cf_dict_set(query, self.kSecClass, self.kSecClassGenericPassword)
            self._cf_dict_set(query, self.kSecAttrService, service_ref)
            self._cf_dict_set(query, self.kSecAttrAccount, account_ref)
            yield query

    @contextmanager
    def _attributes(self, payload: bytes):
        with ExitStack() as stack:
            attributes = stack.enter_context(_owned_cf(self._cf_dict_create(None, 0, None, None), self._cf_release))
            data = stack.enter_context(self._data(payload))
            self._cf_dict_set(attributes, self.kSecValueData, data)
            yield attributes

    def copy_matching(self, service: str, account: str) -> tuple[int, bytes | None]:
        with self._identity_query(service, account) as query:
            self._cf_dict_set(query, self.kSecReturnData, self._true)
            result = ctypes.c_void_p()
            status = self._copy_matching(query, ctypes.byref(result))
            if status != ERR_SEC_SUCCESS:
                return status, None
            with _owned_cf(result, self._cf_release) as data:
                length = self._cf_data_get_length(data)
                return status, ctypes.string_at(self._cf_data_get_byte_ptr(data), length)

    def update(self, service: str, account: str, payload: bytes) -> int:
        with self._identity_query(service, account) as query, self._attributes(payload) as attributes:
            return self._update(query, attributes)

    def add(self, service: str, account: str, payload: bytes) -> int:
        with self._identity_query(service, account) as item, self._data(payload) as data:
            self._cf_dict_set(item, self.kSecValueData, data)
            return self._add(item, None)

    def delete(self, service: str, account: str) -> int:
        with self._identity_query(service, account) as query:
            return self._delete(query)


class _MacOSSecurityApi:
    def __init__(self, bindings=None) -> None:
        self._bindings = _MacOSBindings() if bindings is None else bindings

    def read_generic_password(self, service: str, account: str) -> bytes | None:
        status, payload = self._bindings.copy_matching(service, account)
        if status == ERR_SEC_ITEM_NOT_FOUND:
            return None
        self._check_status("read", status)
        if payload is None:
            raise _MacOSKeychainError("read", status)
        return payload

    def upsert_generic_password(self, service: str, account: str, payload: bytes) -> None:
        status = self._bindings.update(service, account, payload)
        if status == ERR_SEC_SUCCESS:
            return
        if status != ERR_SEC_ITEM_NOT_FOUND:
            self._check_status("write", status)
        status = self._bindings.add(service, account, payload)
        if status == ERR_SEC_SUCCESS:
            return
        if status == ERR_SEC_DUPLICATE_ITEM:
            self._check_status("write", self._bindings.update(service, account, payload))
            return
        self._check_status("write", status)

    def delete_generic_password(self, service: str, account: str) -> None:
        status = self._bindings.delete(service, account)
        if status not in (ERR_SEC_SUCCESS, ERR_SEC_ITEM_NOT_FOUND):
            self._check_status("delete", status)

    @staticmethod
    def _check_status(action: str, status: int) -> None:
        if status != ERR_SEC_SUCCESS:
            raise _MacOSKeychainError(action, status)


class MacOSKeychainStore:
    """Stores a refresh token as a macOS Keychain Generic Password item."""

    def __init__(self, service_name: str, account_name: str = "refresh-token", *, _api=None) -> None:
        if not isinstance(service_name, str) or not service_name:
            raise ValueError("service_name must be a non-empty string")
        if not isinstance(account_name, str) or not account_name:
            raise ValueError("account_name must be a non-empty string")
        self._service_name = service_name
        self._account_name = account_name
        self._api = _api

    def _native_api(self):
        if self._api is None:
            if sys.platform != "darwin":
                raise TokenPersistenceError("macOS Keychain storage is unavailable", operation="storage", code="storage_unsupported", retryable=False)
            self._api = _MacOSSecurityApi()
        return self._api

    def load(self) -> str | None:
        payload = self._call("read", lambda: self._native_api().read_generic_password(self._service_name, self._account_name))
        if payload is None:
            return None
        invalid = False
        try:
            value = payload.decode("utf-8")
        except (AttributeError, UnicodeDecodeError):
            invalid = True
            value = None
        if invalid or not value:
            self._raise_invalid_value("read")
        return value

    def save(self, token: str) -> None:
        if not isinstance(token, str) or not token:
            raise ValueError("token must be a non-empty string")
        invalid = False
        try:
            payload = token.encode("utf-8")
        except UnicodeEncodeError:
            invalid = True
            payload = None
        if invalid:
            self._raise_invalid_value("write")
        self._call("write", lambda: self._native_api().upsert_generic_password(self._service_name, self._account_name, payload))

    def delete(self) -> None:
        self._call("delete", lambda: self._native_api().delete_generic_password(self._service_name, self._account_name))

    @staticmethod
    def _raise_invalid_value(action: str) -> None:
        error = TokenPersistenceError("stored refresh token is invalid", operation="storage", code="storage_value_invalid", retryable=False)
        raise error from _SanitizedMacOSCause(action)

    @staticmethod
    def _call(action: str, operation):
        code = {"read": "storage_read_failed", "write": "storage_write_failed", "delete": "storage_delete_failed"}[action]
        retryable = False
        try:
            return operation()
        except TokenPersistenceError as caught:
            if caught.code == "storage_unsupported":
                code = caught.code
                retryable = caught.retryable
        except Exception:
            pass
        error = TokenPersistenceError(f"refresh token storage {action} failed", operation="storage", code=code, retryable=retryable)
        raise error from _SanitizedMacOSCause(action)
