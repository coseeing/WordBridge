import subprocess
import sys
from pathlib import Path

import pytest


def test_sso_configuration_matches_approved_demo():
	from lib.coseeing_auth import build_auth_config

	value = build_auth_config()
	assert value.issuer == "https://sso.coseeing.org"
	assert value.client_id == "a11yvillage"
	assert set(value.scopes) == {"openid", "profile", "email", "offline_access"}
	assert value.login_redirect_uri == "http://127.0.0.1:8765/auth-callback"
	assert value.logout_redirect_uri == "http://127.0.0.1:8765/logout-callback"
	assert value.callback_timeout == 180


def test_windows_bundle_imports_dependencies_from_addon_package():
	if sys.platform != "win32":
		pytest.skip("Windows NVDA bundle import requires a Windows target runtime")

	bundle = Path("addon/globalPlugins/WordBridge/package").resolve()
	code = """
import sys
from pathlib import Path

bundle = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(bundle))
import authlib
import coseeing_auth
from authlib.integrations.requests_client import OAuth2Session
import jwt
from jwt.algorithms import RSAAlgorithm
import requests

assert Path(coseeing_auth.__file__).resolve().is_relative_to(bundle)
assert callable(OAuth2Session)
assert callable(RSAAlgorithm)
assert callable(requests.Session)
for module in (authlib, jwt, requests):
    assert Path(module.__file__).resolve().is_relative_to(bundle)
"""
	subprocess.run(
		[sys.executable, "-S", "-c", code, str(bundle)],
		check=True,
		capture_output=True,
		text=True,
	)
