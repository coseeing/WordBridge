import importlib
import struct
import sys
import types
from importlib.machinery import ExtensionFileLoader, ModuleSpec, SourceFileLoader
from pathlib import Path

import pytest

from lib import vendor
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


def test_install_reinstalls_a_missing_finder_when_the_namespace_still_exists(
	sandbox_root, install_sandbox
):
	first = install_sandbox([str(sandbox_root)], "_wb_t2a", {"alpha"})
	sys.meta_path[:] = [
		finder for finder in sys.meta_path
		if getattr(finder, "prefix", None) != "_wb_t2a"
	]

	second = install_sandbox([str(sandbox_root)], "_wb_t2a", {"alpha"})

	assert second is first
	matching = [f for f in sys.meta_path if getattr(f, "prefix", None) == "_wb_t2a"]
	assert len(matching) == 1


def test_install_recreates_a_missing_namespace_without_duplicating_the_finder(
	sandbox_root, install_sandbox
):
	first = install_sandbox([str(sandbox_root)], "_wb_t2b", {"alpha"})
	del sys.modules["_wb_t2b"]

	second = install_sandbox([str(sandbox_root)], "_wb_t2b", {"alpha"})

	assert second is not first
	assert sys.modules["_wb_t2b"] is second
	matching = [f for f in sys.meta_path if getattr(f, "prefix", None) == "_wb_t2b"]
	assert len(matching) == 1


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


def test_finder_leaves_extension_loaders_unwrapped_but_wraps_source_loaders(monkeypatch):
	"""Production hits this branch: cryptography's ``_rust`` ships a real .pyd.

	Deleting the ``ExtensionFileLoader`` check would still pass every other
	test here, so this test exists to give that branch its own failure.
	"""
	extension_loader = ExtensionFileLoader("_wb_t5.ext", "/fake/ext.so")
	extension_spec = ModuleSpec("_wb_t5.ext", extension_loader)
	source_loader = SourceFileLoader("_wb_t5.src", "/fake/src.py")
	source_spec = ModuleSpec("_wb_t5.src", source_loader)
	specs = iter([extension_spec, source_spec])
	monkeypatch.setattr(vendor.PathFinder, "find_spec", lambda *a, **k: next(specs))
	finder = vendor._SandboxFinder("_wb_t5", lambda *a, **k: None)

	extension_result = finder.find_spec("_wb_t5.ext")
	source_result = finder.find_spec("_wb_t5.src")

	assert extension_result.loader is extension_loader
	assert isinstance(source_result.loader, vendor._SandboxLoader)


def test_runtime_key_is_none_off_windows(monkeypatch):
	monkeypatch.setattr(sys, "platform", "linux")

	assert vendor.runtime_key() is None


def test_runtime_key_names_the_running_interpreter_on_windows(monkeypatch):
	monkeypatch.setattr(sys, "platform", "win32")
	monkeypatch.setattr(struct, "calcsize", lambda fmt: 8)

	expected = f"py{sys.version_info[0]}{sys.version_info[1]}-win_amd64"
	assert vendor.runtime_key() == expected


def test_runtime_key_matches_the_bundle_directory_actually_on_disk(monkeypatch):
	"""Pins the derived key to the real bundle layout, not just to its own f-string.

	A key whose *shape* is right but does not match the directory NVDA will
	actually find is worse than no key: it degrades silently to the "roots
	that exist" path instead of loading the bundle.
	"""
	monkeypatch.setattr(sys, "platform", "win32")
	monkeypatch.setattr(sys, "version_info", (3, 13, 0))
	monkeypatch.setattr(struct, "calcsize", lambda fmt: 8)
	deps_dir = (
		Path(__file__).resolve().parent.parent
		/ "addon" / "globalPlugins" / "WordBridge" / "package" / "_coseeing_auth_deps"
	)

	assert (deps_dir / "py313-win_amd64").is_dir()
	assert vendor.runtime_key() == "py313-win_amd64"


from pathlib import Path

PACKAGE_ROOT = Path("addon/globalPlugins/WordBridge/package")


def test_every_bundled_top_level_name_is_classified():
	"""Adding a package to the bundle without classifying it must fail here."""
	roots = [PACKAGE_ROOT, PACKAGE_ROOT / "_coseeing_auth_deps" / "py313-win_amd64"]
	skip = {"__pycache__", "_stdlib_gapfill", "_coseeing_auth_deps"}
	found = set()
	for root in roots:
		for entry in root.iterdir():
			if entry.name in skip:
				continue
			if entry.is_dir():
				if not entry.name.endswith(".dist-info"):
					found.add(entry.name)
			elif entry.name.endswith(".py"):
				found.add(entry.name[:-3])
			elif entry.name.endswith(".pyd"):
				found.add(entry.name.split(".")[0])

	assert found == vendor.ISOLATED | vendor.HOST_ONLY


def test_categories_do_not_overlap():
	assert not (vendor.ISOLATED & vendor.HOST_ONLY)


def test_gapfill_skips_a_module_the_host_already_provides(tmp_path):
	directory = tmp_path / "_stdlib_gapfill"
	directory.mkdir()
	(directory / "json.py").write_text("RAISE = 'ours'\n", encoding="utf8")
	host_json = sys.modules["json"]

	registered = vendor.install_stdlib_gapfill(tmp_path)

	assert registered == []
	assert sys.modules["json"] is host_json


def test_gapfill_registers_a_module_the_host_lacks(tmp_path, monkeypatch):
	directory = tmp_path / "_stdlib_gapfill"
	directory.mkdir()
	(directory / "wbfakegap.py").write_text("VALUE = 'gapfill'\n", encoding="utf8")
	monkeypatch.delitem(sys.modules, "wbfakegap", raising=False)

	registered = vendor.install_stdlib_gapfill(tmp_path)
	try:
		assert registered == ["wbfakegap"]
		assert sys.modules["wbfakegap"].VALUE == "gapfill"
		assert sys.modules["wbfakegap"].__name__ == "wbfakegap"
	finally:
		sys.modules.pop("wbfakegap", None)


def test_gapfill_is_a_no_op_without_the_directory(tmp_path):
	assert vendor.install_stdlib_gapfill(tmp_path) == []


def test_secrets_gapfill_ships_and_stays_verbatim():
	source = PACKAGE_ROOT / "_stdlib_gapfill" / "secrets.py"

	assert source.is_file()
	assert not (PACKAGE_ROOT / "secrets.py").exists()
	assert "PEP 506" in source.read_text(encoding="utf8")
