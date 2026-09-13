import subprocess
import sys
import struct
import sysconfig
from pathlib import Path

import pytest


PACKAGE_ROOT = Path("addon/globalPlugins/WordBridge/package")
RUNTIME_BUNDLES = {
	"py311-win32": {
		"_cffi_backend.cp311-win32.pyd",
		"charset_normalizer/cd.cp311-win32.pyd",
		"charset_normalizer/md.cp311-win32.pyd",
		"cryptography/hazmat/bindings/_rust.pyd",
	},
	"py313-win_amd64": {
		"_cffi_backend.cp313-win_amd64.pyd",
		"charset_normalizer/cd.cp313-win_amd64.pyd",
		"charset_normalizer/md.cp313-win_amd64.pyd",
		"cryptography/hazmat/bindings/_rust.pyd",
	},
}


def _explicit_linux_test_dependency_path() -> Path:
	path = Path(sysconfig.get_paths()["purelib"]).resolve()
	assert path.is_dir()
	for package in ("authlib", "requests", "jwt", "cryptography"):
		assert (path / package).exists()
	if str(path) not in sys.path:
		sys.path.insert(0, str(path))
	return path


def test_sso_configuration_matches_approved_demo():
	if sys.platform != "win32":
		_explicit_linux_test_dependency_path()
	from lib.coseeing_auth import build_auth_config

	value = build_auth_config()
	assert value.issuer == "https://sso.coseeing.org"
	assert value.client_id == "a11yvillage"
	assert set(value.scopes) == {"openid", "profile", "email", "offline_access"}
	assert value.login_redirect_uri == "http://127.0.0.1:8765/auth-callback"
	assert value.logout_redirect_uri == "http://127.0.0.1:8765/logout-callback"
	assert value.callback_timeout == 180


def test_non_windows_configuration_uses_explicit_test_dependency_setup():
	if sys.platform == "win32":
		pytest.skip("Non-Windows test dependency setup is only for development hosts")

	bundle = PACKAGE_ROOT.resolve()
	dependencies = _explicit_linux_test_dependency_path()
	code = """
import sys
from pathlib import Path

bundle = Path(sys.argv[1]).resolve()
dependencies = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(dependencies))
sys.path.insert(0, str(bundle.parent))
sys.path.insert(0, str(bundle))
from lib.coseeing_auth import build_auth_config
import coseeing_auth

value = build_auth_config()
assert value.issuer == "https://sso.coseeing.org"
assert Path(coseeing_auth.__file__).resolve().is_relative_to(bundle)
assert Path(sys.modules["authlib"].__file__).resolve().is_relative_to(dependencies)
assert Path(sys.modules["requests"].__file__).resolve().is_relative_to(dependencies)
assert Path(sys.modules["jwt"].__file__).resolve().is_relative_to(dependencies)
assert Path(sys.modules["cryptography"].__file__).resolve().is_relative_to(dependencies)
"""
	subprocess.run(
		[sys.executable, "-I", "-S", "-c", code, str(bundle), str(dependencies)],
		check=True,
		capture_output=True,
		text=True,
		env={},
	)


def test_runtime_bundles_contain_native_backend_for_each_supported_runtime():
	for runtime, native_files in RUNTIME_BUNDLES.items():
		bundle = PACKAGE_ROOT / "_coseeing_auth_deps" / runtime
		for relative_path in native_files:
			assert (bundle / relative_path).is_file()
		assert any(bundle.glob("*.dist-info/METADATA"))


def test_windows_bundle_imports_dependencies_from_addon_package():
	if sys.platform != "win32":
		pytest.skip("Windows NVDA bundle import requires a Windows target runtime")

	bundle = PACKAGE_ROOT.resolve()
	code = """
import sys
import struct
from pathlib import Path

bundle = Path(sys.argv[1]).resolve()
runtime = f"py{sys.version_info.major}{sys.version_info.minor}-{'win32' if struct.calcsize('P') == 4 else 'win_amd64'}"
assert runtime in {"py311-win32", "py313-win_amd64"}
deps = bundle / "_coseeing_auth_deps" / runtime
assert deps.is_dir()
sys.path.insert(0, str(deps))
sys.path.insert(0, str(bundle))
import authlib
import coseeing_auth
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
for module in (authlib, jwt, requests, cryptography, cffi, _cffi_backend,
               charset_normalizer, certifi, idna, urllib3, pycparser):
    assert Path(module.__file__).resolve().is_relative_to(deps)
"""
	subprocess.run(
		[sys.executable, "-I", "-S", "-c", code, str(bundle)],
		check=True,
		capture_output=True,
		text=True,
	)
