import sys
import types

import pytest

from lib.vendor import _make_sandbox_import


ISOLATED = frozenset({"alpha", "beta"})


@pytest.fixture
def recording_import(monkeypatch):
	"""A stand-in for builtins.__import__ that records calls and publishes modules."""
	calls = []

	def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
		calls.append((name, globals, locals, tuple(fromlist or ()), level))
		parts = name.split(".")
		for index in range(len(parts)):
			partial = ".".join(parts[: index + 1])
			if partial not in sys.modules:
				monkeypatch.setitem(sys.modules, partial, types.ModuleType(partial))
		return sys.modules[parts[0]]

	fake_import.calls = calls
	return fake_import


def test_plain_import_returns_the_prefixed_top_level_module(recording_import):
	sandbox_import = _make_sandbox_import("_wb_test", ISOLATED, recording_import)

	result = sandbox_import("alpha.child")

	assert recording_import.calls == [("_wb_test.alpha.child", None, None, (), 0)]
	assert result is sys.modules["_wb_test.alpha"]


def test_from_import_returns_the_prefixed_submodule(recording_import):
	sandbox_import = _make_sandbox_import("_wb_test", ISOLATED, recording_import)

	result = sandbox_import("alpha.child", fromlist=("thing",))

	assert recording_import.calls == [("_wb_test.alpha.child", None, None, ("thing",), 0)]
	assert result is sys.modules["_wb_test.alpha.child"]


def test_relative_import_is_delegated_untouched(recording_import):
	sandbox_import = _make_sandbox_import("_wb_test", ISOLATED, recording_import)
	caller_globals = {"__package__": "somepkg"}

	result = sandbox_import("child", caller_globals, None, ("thing",), 2)

	assert recording_import.calls == [("child", caller_globals, None, ("thing",), 2)]
	assert recording_import.calls[0][1] is caller_globals
	assert result is sys.modules["child"]


def test_host_name_is_delegated_untouched(recording_import):
	sandbox_import = _make_sandbox_import("_wb_test", ISOLATED, recording_import)

	result = sandbox_import("hostpkg.adapters")

	assert recording_import.calls == [("hostpkg.adapters", None, None, (), 0)]
	assert result is sys.modules["hostpkg"]


def test_bare_isolated_name_is_prefixed(recording_import):
	sandbox_import = _make_sandbox_import("_wb_test", ISOLATED, recording_import)

	result = sandbox_import("beta")

	assert recording_import.calls == [("_wb_test.beta", None, None, (), 0)]
	assert result is sys.modules["_wb_test.beta"]


import importlib
import struct

from lib import vendor


@pytest.fixture
def sandbox_root(tmp_path):
	"""A fabricated two-package tree: alpha lazily imports beta by absolute name."""
	alpha = tmp_path / "alpha"
	alpha.mkdir()
	(alpha / "__init__.py").write_text(
		"def get():\n"
		"\timport beta\n"
		"\treturn beta.VALUE\n",
		encoding="utf8",
	)
	beta = tmp_path / "beta"
	beta.mkdir()
	(beta / "__init__.py").write_text("VALUE = 'sandbox'\n", encoding="utf8")
	return tmp_path


@pytest.fixture
def install_sandbox():
	"""Install a disposable sandbox and remove every trace afterwards."""
	installed = []

	def _install(roots, prefix, isolated):
		installed.append(prefix)
		return vendor.install(roots, prefix=prefix, isolated=frozenset(isolated))

	yield _install

	for prefix in installed:
		for name in [n for n in sys.modules if n == prefix or n.startswith(prefix + ".")]:
			del sys.modules[name]
		sys.meta_path[:] = [
			finder for finder in sys.meta_path
			if getattr(finder, "prefix", None) != prefix
		]


def test_namespace_path_holds_only_roots_that_exist(sandbox_root, install_sandbox):
	missing = sandbox_root / "not-here"

	namespace = install_sandbox([str(sandbox_root), str(missing)], "_wb_t1", {"alpha"})

	assert namespace.__path__ == [str(sandbox_root)]


def test_install_is_idempotent(sandbox_root, install_sandbox):
	first = install_sandbox([str(sandbox_root)], "_wb_t2", {"alpha"})
	finders_after_first = len(sys.meta_path)

	second = install_sandbox([str(sandbox_root)], "_wb_t2", {"alpha"})

	assert second is first
	assert len(sys.meta_path) == finders_after_first


def test_lazy_import_inside_a_function_resolves_to_the_sandbox(
	sandbox_root, install_sandbox, monkeypatch
):
	"""B's defining property: interception survives to call time.

	A host `beta` exists and would win any resolution that is not sandboxed.
	`alpha.get()` imports `beta` when CALLED, long after alpha was loaded.
	"""
	host_beta = types.ModuleType("beta")
	host_beta.VALUE = "host"
	monkeypatch.setitem(sys.modules, "beta", host_beta)
	install_sandbox([str(sandbox_root)], "_wb_t3", {"alpha", "beta"})

	alpha = importlib.import_module("_wb_t3.alpha")

	assert alpha.get() == "sandbox"
	assert sys.modules["beta"] is host_beta


def test_finder_declines_every_name_outside_its_prefix(sandbox_root, install_sandbox):
	install_sandbox([str(sandbox_root)], "_wb_t4", {"alpha"})
	finder = next(f for f in sys.meta_path if getattr(f, "prefix", None) == "_wb_t4")

	assert finder.find_spec("alpha", None, None) is None
	assert finder.find_spec("requests", None, None) is None
	assert finder.find_spec("_wb_t4other.alpha", None, None) is None


def test_runtime_key_is_none_off_windows(monkeypatch):
	monkeypatch.setattr(sys, "platform", "linux")

	assert vendor.runtime_key() is None


def test_runtime_key_names_the_running_interpreter_on_windows(monkeypatch):
	monkeypatch.setattr(sys, "platform", "win32")
	monkeypatch.setattr(struct, "calcsize", lambda fmt: 8)

	expected = f"py{sys.version_info[0]}{sys.version_info[1]}-win_amd64"
	assert vendor.runtime_key() == expected
