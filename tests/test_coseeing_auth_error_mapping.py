"""`_map_login_error()` must not relabel the stage it was handed.

Loaded in a subprocess with `package/` on `sys.path`, because importing the
real `coseeing_auth.client` registers `coseeing_auth` in `sys.modules` and the
rest of the auth tests run against stubs under that name. Keeping it out of
this process is what stops the two from poisoning each other.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PACKAGE_ROOT = (
	Path(__file__).resolve().parent.parent
	/ "addon" / "globalPlugins" / "WordBridge" / "package"
)


def _run(body):
	pytest.importorskip("requests", reason="the real client module needs requests to import")
	pytest.importorskip("cryptography")
	runtimes = sorted(entry for entry in (PACKAGE_ROOT / "_coseeing_auth_deps").glob("*") if entry.is_dir())
	assert runtimes, "no runtime bundle to take authlib/jwt/joserfc from"
	result = subprocess.run(
		[sys.executable, "-c", textwrap.dedent(body), str(PACKAGE_ROOT), str(runtimes[0])],
		check=False, capture_output=True, text=True,
	)
	assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_an_unmapped_failure_keeps_the_stage_it_happened_in():
	"""A TypeError raised while validating the token was reported as
	`stage=token_exchange code=token_exchange_failed`, because the fallback
	hard-coded that stage. On NVDA that sent the investigation to the token
	endpoint while the real failure was in PyJWT, two stages later.
	"""
	_run("""
		import sys
		# The runtime bundle also carries a Windows-only cryptography, which
		# would shadow the host's the moment that directory goes on sys.path.
		# Importing the host copy first pins the canonical name to it; every
		# submodule then resolves through its __path__.
		import cryptography
		sys.path.insert(0, sys.argv[2])  # the vendored authlib/jwt/joserfc
		sys.path.insert(0, sys.argv[1])  # package/
		from coseeing_auth.client import CoseeingAuthClient

		mapped = CoseeingAuthClient._map_login_error(TypeError("boom"), "token_validation")
		assert (mapped.stage, mapped.code) == ("token_validation", "token_validation_failed"), (
			mapped.stage, mapped.code
		)
		assert mapped.operation == "login"
		print("ok")
	""")


def test_the_existing_stage_codes_are_unchanged():
	"""The fix adds a stage; it must not renumber the ones already in use."""
	_run("""
		import sys
		# The runtime bundle also carries a Windows-only cryptography, which
		# would shadow the host's the moment that directory goes on sys.path.
		# Importing the host copy first pins the canonical name to it; every
		# submodule then resolves through its __path__.
		import cryptography
		sys.path.insert(0, sys.argv[2])  # the vendored authlib/jwt/joserfc
		sys.path.insert(0, sys.argv[1])  # package/
		from coseeing_auth.client import CoseeingAuthClient

		expected = {
			"token_exchange": ("token_exchange", "token_exchange_failed"),
			"authorization": ("authorization", "authorization_failed"),
			"callback": ("callback", "invalid_callback"),
			"discovery": ("token_exchange", "token_exchange_failed"),
		}
		for stage, want in expected.items():
			mapped = CoseeingAuthClient._map_login_error(TypeError("boom"), stage)
			assert (mapped.stage, mapped.code) == want, (stage, mapped.stage, mapped.code)
		print("ok")
	""")
