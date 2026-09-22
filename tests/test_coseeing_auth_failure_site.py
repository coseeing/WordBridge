"""`failure_site()` is loaded straight off disk.

`coseeing_auth/errors.py` imports nothing from the bundle, so this test reads
the real shipped file rather than the stubs the other auth tests install --
the point of the helper is what it renders in production, and a stub would
prove nothing about that.
"""
import importlib.util
from pathlib import Path

import pytest

ERRORS_PATH = (
	Path(__file__).resolve().parents[1]
	/ "addon" / "globalPlugins" / "WordBridge" / "package" / "coseeing_auth" / "errors.py"
)


@pytest.fixture(scope="module")
def errors():
	spec = importlib.util.spec_from_file_location("_coseeing_auth_errors_under_test", ERRORS_PATH)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def _raise_type_error(secret):
	raise TypeError(f"unsupported operand for {secret}")


def _call_through():
	_raise_type_error("refresh-token-secret")


def test_failure_site_names_the_type_and_the_innermost_frames(errors):
	try:
		_call_through()
	except TypeError as error:
		site = errors.failure_site(error)
	assert site.startswith("TypeError at ")
	assert "test_coseeing_auth_failure_site.py:" in site
	assert ":_raise_type_error" in site
	assert ":_call_through" in site
	assert site.index("_raise_type_error") < site.index("_call_through"), "innermost frame first"


def test_failure_site_leaks_neither_message_nor_source_text(errors):
	try:
		_call_through()
	except TypeError as error:
		site = errors.failure_site(error)
	assert "refresh-token-secret" not in site
	assert "unsupported operand" not in site
	assert "raise TypeError" not in site


def test_failure_site_survives_an_exception_with_no_traceback(errors):
	assert errors.failure_site(TypeError("never raised")) == "TypeError"


def test_failure_site_bounds_the_frame_chain(errors):
	def recurse(depth):
		if depth == 0:
			raise TypeError("bottom")
		recurse(depth - 1)

	try:
		recurse(20)
	except TypeError as error:
		site = errors.failure_site(error)
	assert site.count(" < ") == errors._FAILURE_SITE_FRAMES - 1
