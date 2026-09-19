import subprocess
import sys
import os
import shutil
import types
from email import policy
from email.parser import Parser
from pathlib import Path

import pytest


PACKAGE_ROOT = Path("addon/globalPlugins/WordBridge/package")
RUNTIME_BUNDLES = {
	"py313-win_amd64": {
		"_cffi_backend.cp313-win_amd64.pyd",
		"charset_normalizer/cd.cp313-win_amd64.pyd",
		"charset_normalizer/md.cp313-win_amd64.pyd",
		"cryptography/hazmat/bindings/_rust.pyd",
	},
}
EXPECTED_PACKAGE_VERSIONS = {
	"Authlib": "1.8.0",
	"requests": "2.34.2",
	"PyJWT": "2.14.0",
	"joserfc": "1.7.5",
	"cryptography": "50.0.1",
	"cffi": "2.1.1",
	"pycparser": "3.0",
	"charset-normalizer": "3.5.1",
	"idna": "3.19",
	"urllib3": "2.7.0",
	"certifi": "2026.7.22",
}


def _sanitized_windows_environment(dependencies: Path, bundle: Path) -> dict[str, str]:
	env = {
		key: os.environ[key]
		for key in ("SystemRoot", "SystemDrive")
		if key in os.environ
	}
	env["PATH"] = os.pathsep.join((str(dependencies), str(bundle)))
	return env


def test_sso_configuration_matches_approved_demo(tmp_path):
	bundle = PACKAGE_ROOT.resolve()
	if sys.platform != "win32":
		addon = bundle.parent
		fixture = tmp_path / "coseeing_auth"
		fixture.mkdir()
		shutil.copy2(bundle / "coseeing_auth" / "errors.py", fixture / "errors.py")
		shutil.copy2(bundle / "coseeing_auth" / "models.py", fixture / "models.py")
		(fixture / "__init__.py").write_text("from .models import AuthConfig\n", encoding="utf-8")
		code = """
import sys
import types
from pathlib import Path

addon = Path(sys.argv[1]).resolve()
fixture = Path(sys.argv[2]).resolve()
assert "PYTHONPATH" not in __import__("os").environ
addon_handler = types.ModuleType("addonHandler")
addon_handler.initTranslation = lambda: None
sys.modules["addonHandler"] = addon_handler
authlib = types.ModuleType("authlib")
integrations = types.ModuleType("authlib.integrations")
base_client = types.ModuleType("authlib.integrations.base_client")
errors = types.ModuleType("authlib.integrations.base_client.errors")
errors.OAuthError = type("OAuthError", (Exception,), {})
for module in (authlib, integrations, base_client, errors):
    sys.modules[module.__name__] = module
sys.path.insert(0, str(fixture.parent))
sys.path.insert(0, str(addon))
from lib.coseeing_auth import build_auth_config
import coseeing_auth

value = build_auth_config()
assert value.issuer == "https://sso.coseeing.org"
assert value.client_id == "a11yvillage"
assert set(value.scopes) == {"openid", "profile", "email", "offline_access"}
assert value.login_redirect_uri == "http://127.0.0.1:8765/auth-callback"
assert value.logout_redirect_uri == "http://127.0.0.1:8765/logout-callback"
assert value.callback_timeout == 180
assert Path(coseeing_auth.__file__).resolve().is_relative_to(fixture)
"""
		subprocess.run(
			[sys.executable, "-I", "-S", "-c", code, str(addon), str(fixture)],
			check=True,
			capture_output=True,
			text=True,
			env={},
		)
		return

	dependencies = bundle / "_coseeing_auth_deps"
	code = """
import sys
from pathlib import Path

bundle = Path(sys.argv[1]).resolve()
assert "PYTHONPATH" not in __import__("os").environ
assert (sys.version_info.major, sys.version_info.minor) == (3, 13)
assert __import__('struct').calcsize('P') == 8
runtime = "py313-win_amd64"
deps = bundle / "_coseeing_auth_deps" / runtime
sys.path.insert(0, str(bundle.parent))
from lib.coseeing_auth import build_auth_config
import coseeing_auth

value = build_auth_config()
assert sys.path.index(str(deps)) < sys.path.index(str(bundle.parent))
assert value.issuer == "https://sso.coseeing.org"
assert value.client_id == "a11yvillage"
assert set(value.scopes) == {"openid", "profile", "email", "offline_access"}
assert value.login_redirect_uri == "http://127.0.0.1:8765/auth-callback"
assert value.logout_redirect_uri == "http://127.0.0.1:8765/logout-callback"
assert value.callback_timeout == 180
assert Path(coseeing_auth.__file__).resolve().is_relative_to(bundle)
"""
	subprocess.run(
		[sys.executable, "-I", "-S", "-c", code, str(bundle)],
		check=True,
		capture_output=True,
		text=True,
		env=_sanitized_windows_environment(dependencies, bundle),
	)


def test_runtime_bundles_contain_native_backend_for_each_supported_runtime():
	for runtime, native_files in RUNTIME_BUNDLES.items():
		bundle = PACKAGE_ROOT / "_coseeing_auth_deps" / runtime
		for relative_path in native_files:
			assert (bundle / relative_path).is_file()
		assert any(bundle.glob("*.dist-info/METADATA"))


def test_runtime_bundle_contains_resolved_package_versions():
	bundle = PACKAGE_ROOT / "_coseeing_auth_deps" / "py313-win_amd64"
	actual = {}
	for metadata_path in bundle.glob("*.dist-info/METADATA"):
		metadata = Parser(policy=policy.default).parsestr(metadata_path.read_text(encoding="utf-8"))
		actual[metadata["Name"]] = metadata["Version"]

	assert actual == EXPECTED_PACKAGE_VERSIONS


def test_windows_bundle_imports_dependencies_from_addon_package():
	if sys.platform != "win32":
		pytest.skip("Windows NVDA bundle import requires a Windows target runtime")

	bundle = PACKAGE_ROOT.resolve()
	dependencies = bundle / "_coseeing_auth_deps"
	code = """
import sys
import struct
import os
from pathlib import Path

bundle = Path(sys.argv[1]).resolve()
assert "PYTHONPATH" not in os.environ
assert (sys.version_info.major, sys.version_info.minor) == (3, 13)
assert struct.calcsize('P') == 8
runtime = "py313-win_amd64"
deps = bundle / "_coseeing_auth_deps" / runtime
assert deps.is_dir()
sys.path.insert(0, str(deps))
sys.path.insert(0, str(bundle))
import authlib
import coseeing_auth
import joserfc
from authlib.integrations.requests_client import OAuth2Session
import jwt
from jwt.algorithms import RSAAlgorithm
import requests
import cryptography
import cffi
import _cffi_backend
import charset_normalizer
import certifi
import idna
import urllib3
import pycparser

assert Path(coseeing_auth.__file__).resolve().is_relative_to(bundle)
assert callable(OAuth2Session)
assert callable(RSAAlgorithm)
assert callable(requests.Session)
for module in (authlib, coseeing_auth, joserfc, jwt, requests, cryptography,
               cffi, _cffi_backend, charset_normalizer, certifi, idna, urllib3,
               pycparser):
    assert Path(module.__file__).resolve().is_relative_to(deps)
"""
	subprocess.run(
		[sys.executable, "-I", "-S", "-c", code, str(bundle)],
		check=True,
		capture_output=True,
		text=True,
		env=_sanitized_windows_environment(dependencies, bundle),
	)


def test_coseeing_auth_bundle_contains_native_refresh_token_storage():
	package = PACKAGE_ROOT / "coseeing_auth"
	storage = package / "storage"
	assert {path.name for path in storage.glob("*.py")} == {
		"__init__.py",
		"macos_keychain.py",
		"storage.py",
		"windows_credentials.py",
	}


@pytest.fixture
def _coseeing_auth_import_dependencies(monkeypatch):
	"""Provide pure-Python import seams for the Windows-only bundled runtime."""
	authlib = types.ModuleType("authlib")
	oauth2 = types.ModuleType("authlib.oauth2")
	rfc6749 = types.ModuleType("authlib.oauth2.rfc6749")
	errors = types.ModuleType("authlib.oauth2.rfc6749.errors")
	integrations = types.ModuleType("authlib.integrations")
	requests_client = types.ModuleType("authlib.integrations.requests_client")

	class OAuth2Error(Exception):
		pass

	class MismatchingStateException(OAuth2Error):
		pass

	class OAuth2Session:
		pass

	errors.OAuth2Error = OAuth2Error
	errors.MismatchingStateException = MismatchingStateException
	requests_client.OAuth2Session = OAuth2Session
	for module in (authlib, oauth2, rfc6749, errors, integrations, requests_client):
		monkeypatch.setitem(sys.modules, module.__name__, module)
	monkeypatch.setitem(sys.modules, "jwt", types.ModuleType("jwt"))


@pytest.mark.usefixtures("_coseeing_auth_import_dependencies")
def test_coseeing_auth_exports_windows_store_and_saved_session_api():
	from coseeing_auth import CoseeingAuthClient, FutureAuthClient, WindowsCredentialStore

	assert WindowsCredentialStore.__module__.endswith("storage.windows_credentials")
	assert callable(CoseeingAuthClient.restore_saved_session)
	assert callable(CoseeingAuthClient.logout_local)
	assert callable(FutureAuthClient.restore_saved_session)
	assert callable(FutureAuthClient.logout_local)
