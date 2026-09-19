"""Windows Credential Manager refresh-token storage."""

import ctypes
import sys

from ..errors import TokenPersistenceError


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


DWORD = ctypes.c_uint32
LPBYTE = ctypes.POINTER(ctypes.c_ubyte)


class CREDENTIAL_ATTRIBUTEW(ctypes.Structure):
    _fields_ = [
        ("Keyword", ctypes.c_wchar_p),
        ("Flags", DWORD),
        ("ValueSize", DWORD),
        ("Value", LPBYTE),
    ]


PCREDENTIAL_ATTRIBUTEW = ctypes.POINTER(CREDENTIAL_ATTRIBUTEW)


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", DWORD),
        ("Type", DWORD),
        ("TargetName", ctypes.c_wchar_p),
        ("Comment", ctypes.c_wchar_p),
        ("LastWritten", ctypes.c_byte * 8),
        ("CredentialBlobSize", DWORD),
        ("CredentialBlob", LPBYTE),
        ("Persist", DWORD),
        ("AttributeCount", DWORD),
        ("Attributes", PCREDENTIAL_ATTRIBUTEW),
        ("TargetAlias", ctypes.c_wchar_p),
        ("UserName", ctypes.c_wchar_p),
    ]


PCREDENTIALW = ctypes.POINTER(CREDENTIALW)


class _WindowsCredentialError(Exception):
    """A native error whose text intentionally excludes native details."""

    def __init__(self, action: str, winerror: int) -> None:
        super().__init__(f"Windows credential {action} failed")
        self.winerror = winerror


class _SanitizedWindowsCause(Exception):
    def __init__(self, action: str) -> None:
        super().__init__(f"Windows credential {action} failed")


class _WindowsCredentialApi:
    def __init__(self, advapi32=None) -> None:
        self._dll = advapi32 or ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self._dll.CredReadW.argtypes = [ctypes.c_wchar_p, DWORD, DWORD, ctypes.POINTER(PCREDENTIALW)]
        self._dll.CredReadW.restype = ctypes.c_int
        self._dll.CredWriteW.argtypes = [PCREDENTIALW, DWORD]
        self._dll.CredWriteW.restype = ctypes.c_int
        self._dll.CredDeleteW.argtypes = [ctypes.c_wchar_p, DWORD, DWORD]
        self._dll.CredDeleteW.restype = ctypes.c_int
        self._dll.CredFree.argtypes = [ctypes.c_void_p]
        self._dll.CredFree.restype = None

    def read(self, target_name: str) -> bytes | None:
        credential = PCREDENTIALW()
        if not self._dll.CredReadW(target_name, CRED_TYPE_GENERIC, 0, ctypes.byref(credential)):
            error = ctypes.get_last_error()
            if error == ERROR_NOT_FOUND:
                return None
            raise _WindowsCredentialError("read", error)
        try:
            size = credential.contents.CredentialBlobSize
            return ctypes.string_at(credential.contents.CredentialBlob, size)
        finally:
            self._dll.CredFree(credential)

    def write(self, target_name: str, payload: bytes) -> None:
        blob = ctypes.create_string_buffer(payload)
        credential = CREDENTIALW()
        credential.Type = CRED_TYPE_GENERIC
        credential.TargetName = target_name
        credential.CredentialBlobSize = len(payload)
        credential.CredentialBlob = ctypes.cast(blob, LPBYTE)
        credential.Persist = CRED_PERSIST_LOCAL_MACHINE
        if not self._dll.CredWriteW(ctypes.byref(credential), 0):
            raise _WindowsCredentialError("write", ctypes.get_last_error())

    def delete(self, target_name: str) -> None:
        if self._dll.CredDeleteW(target_name, CRED_TYPE_GENERIC, 0):
            return
        error = ctypes.get_last_error()
        if error != ERROR_NOT_FOUND:
            raise _WindowsCredentialError("delete", error)


class WindowsCredentialStore:
    """Stores a refresh token as a Windows Generic Credential."""

    def __init__(self, target_name: str, *, _api=None) -> None:
        if not isinstance(target_name, str) or not target_name:
            raise ValueError("target_name must be a non-empty string")
        self._target_name = target_name
        self._api = _api

    def _native_api(self):
        if self._api is None:
            self._api = _WindowsCredentialApi()
        return self._api

    def load(self) -> str | None:
        payload = self._call_native(
            "read", lambda: self._native_api().read(self._target_name)
        )
        if payload is None:
            return None
        invalid = False
        try:
            value = payload.decode("utf-8")
        except (UnicodeDecodeError, AttributeError):
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
        self._call_native(
            "write", lambda: self._native_api().write(self._target_name, payload)
        )

    def delete(self) -> None:
        self._call_native("delete", lambda: self._native_api().delete(self._target_name))

    def _call_native(self, action: str, operation):
        if self._api is None and sys.platform != "win32":
            raise TokenPersistenceError(
                "Windows credential storage is unavailable",
                operation="storage",
                code="storage_unsupported",
                retryable=False,
            )
        return self._call(action, operation)

    @staticmethod
    def _raise_invalid_value(action: str) -> None:
        error = TokenPersistenceError(
            "stored refresh token is invalid",
            operation="storage",
            code="storage_value_invalid",
            retryable=False,
        )
        raise error from _SanitizedWindowsCause(action)

    @staticmethod
    def _call(action: str, operation):
        code = {
            "read": "storage_read_failed",
            "write": "storage_write_failed",
            "delete": "storage_delete_failed",
        }[action]
        retryable = False
        try:
            return operation()
        except TokenPersistenceError as caught:
            if caught.code == "storage_unsupported":
                code = caught.code
                retryable = caught.retryable
        except Exception:
            pass
        error = TokenPersistenceError(
            f"refresh token storage {action} failed",
            operation="storage",
            code=code,
            retryable=retryable,
        )
        raise error from _SanitizedWindowsCause(action)
