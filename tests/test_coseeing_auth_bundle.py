import subprocess
import sys
import os
import shutil
import types
from email import policy
from email.parser import Parser
from pathlib import Path

import pytest


PACKAGE_ROOT = (
	Path(__file__).resolve().parent.parent
	/ "addon" / "globalPlugins" / "WordBridge" / "package"
)
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


def test_windows_bundle_imports_dependencies_through_the_sandbox():
	if sys.platform != "win32":
		pytest.skip("Windows NVDA bundle import requires a Windows target runtime")

	bundle = PACKAGE_ROOT.resolve()
	dependencies = bundle / "_coseeing_auth_deps"
	code = """
import sys
import struct
import os
import builtins
from importlib.machinery import ExtensionFileLoader
from pathlib import Path

bundle = Path(sys.argv[1]).resolve()
assert "PYTHONPATH" not in os.environ
assert (sys.version_info.major, sys.version_info.minor) == (3, 13)
assert struct.calcsize('P') == 8
deps = bundle / "_coseeing_auth_deps" / "py313-win_amd64"
assert deps.is_dir()

sys.path.insert(0, str(bundle.parent))
from lib import vendor

vendor.install(vendor.default_roots(bundle))
# install_stdlib_gapfill's result is intentionally not asserted here: on a
# stock CPython 3.13 release machine the host already ships secrets, so the
# host-probe branch wins and the gap-fill registers nothing. There is no
# way to prove this call on a machine where it never has anything to do --
# do not "fix" this with an assertion, it can only fail.
vendor.install_stdlib_gapfill(bundle)

import _wb_vendor.authlib
import _wb_vendor.coseeing_auth
import _wb_vendor.joserfc
import _wb_vendor.jwt
import _wb_vendor.cryptography
import _wb_vendor.cryptography.hazmat.bindings._rust as wb_rust
import _wb_vendor.pypinyin
import _wb_vendor.zhon
import _wb_vendor.hanzidentifier
import _wb_vendor.chinese_converter
from _wb_vendor.authlib.integrations.requests_client import OAuth2Session
from _wb_vendor.jwt.algorithms import RSAAlgorithm

assert callable(OAuth2Session)
assert callable(RSAAlgorithm)

for name in ("authlib", "joserfc", "jwt", "cryptography"):
    module = sys.modules["_wb_vendor." + name]
    assert Path(module.__file__).resolve().is_relative_to(deps), name
for name in ("coseeing_auth", "pypinyin", "zhon", "hanzidentifier", "chinese_converter"):
    module = sys.modules["_wb_vendor." + name]
    path = Path(module.__file__).resolve()
    assert path.is_relative_to(bundle) and not path.is_relative_to(deps), name

for name in vendor.ISOLATED:
    assert name not in sys.modules, "leaked global name: " + name

# Positive pin for category 3: authlib eagerly imports requests, so requests
# is the one host-only name that is always non-vacuous today. Prove the host
# copy is actually the one loaded, not merely that no bundled copy is --
# the loop below only ever proves the latter, and every one of its category
# 3 names could in principle skip it and still pass.
import requests

assert callable(requests.Session)
assert not Path(requests.__file__).resolve().is_relative_to(bundle)

for name in vendor.HOST_ONLY:
    module = sys.modules.get(name)
    if module is None or getattr(module, "__file__", None) is None:
        continue
    assert not Path(module.__file__).resolve().is_relative_to(deps), name
    assert "_wb_vendor." + name not in sys.modules, name

# (a) The sandbox is fail-open by construction: the prefix namespace's
# __path__ is a working import root that the stock PathFinder serves on its
# own, so if _SandboxFinder is ever missing, displaced, or declines a name,
# the import still succeeds -- just unwrapped, with the real __import__ and
# no rewriting. Assert every loaded _wb_vendor.* module with a source origin
# (the manually-built _wb_vendor namespace module itself is excluded one
# line below by the "_wb_vendor." dotted-prefix test -- its own name is
# exactly "_wb_vendor", with no trailing dot; the origin filter here only
# excludes extension modules, which do not go through _SandboxLoader) actually
# received the rewritten __import__ rather than the real one.
for name, module in list(sys.modules.items()):
    if not name.startswith("_wb_vendor."):
        continue
    spec = getattr(module, "__spec__", None)
    origin = getattr(spec, "origin", None)
    if not isinstance(origin, str) or not origin.endswith(".py"):
        continue
    module_builtins = module.__dict__.get("__builtins__")
    if isinstance(module_builtins, dict):
        sandboxed_import = module_builtins.get("__import__")
    else:
        sandboxed_import = getattr(module_builtins, "__import__", None)
    assert sandboxed_import is not None, name
    assert sandboxed_import is not builtins.__import__, name

# (b) cryptography/hazmat/bindings/_rust/ ships only .pyi stubs and has no
# __init__.py, so it is a PEP 420 namespace portion unless the sibling
# _rust.pyd shadows it -- which is only true because FileFinder prefers an
# extension module over a namespace portion of the same name. That ordering
# is unprovable off Windows; here it is proven for real, on the real
# runtime. If it ever broke, _SandboxFinder would raise ModuleNotFoundError
# for this name instead of the import quietly degrading.
assert isinstance(wb_rust.__loader__, ExtensionFileLoader), type(wb_rust.__loader__)
assert wb_rust.__spec__.origin.endswith(".pyd"), wb_rust.__spec__.origin
"""
	result = subprocess.run(
		[sys.executable, "-I", "-c", code, str(bundle)],
		check=False,
		capture_output=True,
		text=True,
		env=_sanitized_windows_environment(dependencies, bundle),
	)
	if result.returncode:
		pytest.fail(
			f"sandbox gate failed ({result.returncode})\n"
			f"--- stderr ---\n{result.stderr}\n"
			f"--- stdout ---\n{result.stdout}"
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
	"""Provide pure-Python import seams for the Windows-only bundled runtime.

	Registered under the ``_wb_vendor`` prefix: ``package/`` no longer sits on
	``sys.path`` (see the r03-import-isolation design), so the real
	``package/coseeing_auth`` is only reachable through the sandbox, which
	rewrites its internal ``import authlib...`` / ``import jwt`` statements to
	``_wb_vendor.authlib...`` / ``_wb_vendor.jwt``.
	"""
	authlib = types.ModuleType("_wb_vendor.authlib")
	oauth2 = types.ModuleType("_wb_vendor.authlib.oauth2")
	rfc6749 = types.ModuleType("_wb_vendor.authlib.oauth2.rfc6749")
	errors = types.ModuleType("_wb_vendor.authlib.oauth2.rfc6749.errors")
	integrations = types.ModuleType("_wb_vendor.authlib.integrations")
	requests_client = types.ModuleType("_wb_vendor.authlib.integrations.requests_client")

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
	monkeypatch.setitem(sys.modules, "_wb_vendor.jwt", types.ModuleType("_wb_vendor.jwt"))


@pytest.mark.usefixtures("_coseeing_auth_import_dependencies")
def test_coseeing_auth_exports_windows_store_and_saved_session_api():
	from _wb_vendor.coseeing_auth import CoseeingAuthClient, FutureAuthClient, WindowsCredentialStore

	assert WindowsCredentialStore.__module__.endswith("storage.windows_credentials")
	assert callable(CoseeingAuthClient.restore_saved_session)
	assert callable(CoseeingAuthClient.logout_local)
	assert callable(FutureAuthClient.restore_saved_session)
	assert callable(FutureAuthClient.logout_local)
