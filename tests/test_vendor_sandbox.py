import hashlib
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

PACKAGE_ROOT = (
	Path(__file__).resolve().parent.parent
	/ "addon" / "globalPlugins" / "WordBridge" / "package"
)


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


def test_finder_declines_every_namespace_portion_under_the_prefix(sandbox_root, install_sandbox):
	"""Round 2: generalizes ruling 2 from one directory name to the property
	behind it.  A prefixed name that PathFinder can only resolve as a PEP 420
	namespace portion (no __init__.py) is never one of our packages, whatever
	it happens to be called -- the prefix namespace's __path__ is a real,
	searchable import root, so PathFinder will walk into _stdlib_gapfill,
	_coseeing_auth_deps and __pycache__ exactly as readily as into a real
	vendored package.  All three must fail here, while an ordinary
	category-2-style package under the same prefix still resolves.
	"""
	for dirname in (vendor.STDLIB_GAPFILL_DIRNAME, "_coseeing_auth_deps", "__pycache__"):
		namespace_dir = sandbox_root / dirname
		namespace_dir.mkdir()
		(namespace_dir / "stub.py").write_text("VALUE = 'stub'\n", encoding="utf8")

	install_sandbox([str(sandbox_root)], "_wb_t6", {"alpha"})

	for dirname in (vendor.STDLIB_GAPFILL_DIRNAME, "_coseeing_auth_deps", "__pycache__"):
		with pytest.raises(ModuleNotFoundError):
			importlib.import_module(f"_wb_t6.{dirname}")

	assert importlib.import_module("_wb_t6.alpha") is not None


def test_finder_still_resolves_a_real_package_and_a_real_subpackage(install_sandbox):
	"""Anti-rot half of the property-based fix in round 2: it must not
	blanket-block everything under the prefix, only names PathFinder can't
	otherwise resolve to a real loader.  Uses the actual bundled ``pypinyin``
	and its real ``pypinyin.contrib`` subpackage (both pure Python, so this
	runs the same on every platform) rather than the fabricated ``alpha``
	stand-in, so a future dependency version that ships a subpackage without
	an __init__.py fails loudly here instead of silently degrading to a
	namespace portion.
	"""
	install_sandbox([str(PACKAGE_ROOT)], "_wb_t7", {"pypinyin"})

	top = importlib.import_module("_wb_t7.pypinyin")
	sub = importlib.import_module("_wb_t7.pypinyin.contrib")

	assert top.__name__ == "_wb_t7.pypinyin"
	assert sub.__name__ == "_wb_t7.pypinyin.contrib"


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


def test_every_bundled_top_level_name_is_classified():
	"""Adding a package to the bundle without classifying it must fail here."""
	deps_root = PACKAGE_ROOT / "_coseeing_auth_deps"
	roots = [PACKAGE_ROOT] + sorted(entry for entry in deps_root.glob("*") if entry.is_dir())
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


def test_category_sizes_and_spot_membership():
	"""Pins WHICH category each name is in, not just the union and the overlap.

	Moving a name from one frozenset to the other leaves both tests above
	green -- the union is unchanged and the intersection is still empty -- so
	the isolation behaviour would silently invert for that package with
	nothing here to catch it.
	"""
	assert len(vendor.ISOLATED) == 9
	assert len(vendor.HOST_ONLY) == 8
	assert {"cryptography", "coseeing_auth"} <= vendor.ISOLATED
	assert {"requests", "_cffi_backend"} <= vendor.HOST_ONLY


def test_gapfill_skips_a_module_the_host_already_provides(tmp_path):
	directory = tmp_path / "_stdlib_gapfill"
	directory.mkdir()
	(directory / "json.py").write_text("RAISE = 'ours'\n", encoding="utf8")
	host_json = sys.modules["json"]

	try:
		registered = vendor.install_stdlib_gapfill(tmp_path)

		assert registered == []
		assert sys.modules["json"] is host_json
	finally:
		# If the implementation ever regressed to unconditional registration,
		# leaving our two-line stub installed as sys.modules["json"] would
		# poison every later test in the session; restore it unconditionally.
		sys.modules["json"] = host_json


def test_gapfill_probes_the_host_for_a_module_not_yet_imported(tmp_path):
	"""The probe branch -- not the ``sys.modules`` short-circuit -- is what
	matters on NVDA, where a stdlib module can be importable but not yet
	present in ``sys.modules`` at add-on load time.  ``json`` above never
	reaches ``builtins.__import__`` because pytest has already imported it;
	this uses a stdlib module absent from ``sys.modules`` at test time instead.
	"""
	name = "colorsys"
	if name in sys.modules:
		pytest.skip(f"{name} is already imported in this session")
	directory = tmp_path / "_stdlib_gapfill"
	directory.mkdir()
	(directory / f"{name}.py").write_text("RAISE = 'ours'\n", encoding="utf8")

	try:
		registered = vendor.install_stdlib_gapfill(tmp_path)

		assert registered == []
		assert not hasattr(sys.modules[name], "RAISE")
	finally:
		sys.modules.pop(name, None)


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


def test_gapfill_registers_a_module_whose_name_has_a_single_leading_underscore(
	tmp_path, monkeypatch
):
	"""A single leading underscore must not be excluded like __init__.py is:
	NVDA's stripped stdlib can drop a private helper module (e.g. _pydecimal)
	just as easily as a public one, and the data-driven gap-fill must still
	fill that gap rather than silently skipping the file.
	"""
	directory = tmp_path / "_stdlib_gapfill"
	directory.mkdir()
	(directory / "_wbfakegap.py").write_text("VALUE = 'gapfill'\n", encoding="utf8")
	monkeypatch.delitem(sys.modules, "_wbfakegap", raising=False)

	registered = vendor.install_stdlib_gapfill(tmp_path)
	try:
		assert registered == ["_wbfakegap"]
		assert sys.modules["_wbfakegap"].VALUE == "gapfill"
	finally:
		sys.modules.pop("_wbfakegap", None)


def test_gapfill_is_a_no_op_without_the_directory(tmp_path):
	assert vendor.install_stdlib_gapfill(tmp_path) == []


def test_secrets_gapfill_ships_and_stays_verbatim():
	source = PACKAGE_ROOT / "_stdlib_gapfill" / "secrets.py"

	assert source.is_file()
	assert not (PACKAGE_ROOT / "secrets.py").exists()
	normalized = source.read_bytes().replace(b"\r\n", b"\n")
	digest = hashlib.sha256(normalized).hexdigest()
	assert digest == "277000574358a6ecda4bb40e73332ae81a3bc1c8e1fa36f50e5c6a7d4d3f0f17"


def test_coseeing_auth_module_imports_without_the_bundle():
	"""The add-on must load on a runtime where the auth bundle is absent."""
	from lib import coseeing_auth

	assert hasattr(coseeing_auth, "AUTH_AVAILABLE")
	assert issubclass(coseeing_auth.ClientClosedError, BaseException)
	assert issubclass(coseeing_auth.OAuthError, BaseException)


def test_unavailable_auth_yields_a_failed_future_not_an_exception(monkeypatch):
	from lib import coseeing_auth

	monkeypatch.setattr(coseeing_auth, "AUTH_AVAILABLE", False)
	monkeypatch.setattr(coseeing_auth, "_singleton_session", None)
	monkeypatch.setattr(coseeing_auth, "_singleton_adapter", None)

	future = coseeing_auth.get_coseeing_access_token()

	assert isinstance(future.exception(), coseeing_auth.CoseeingAuthUnavailableError)


def test_unavailable_auth_leaves_shutdown_a_no_op(monkeypatch):
	from lib import coseeing_auth

	monkeypatch.setattr(coseeing_auth, "AUTH_AVAILABLE", False)
	monkeypatch.setattr(coseeing_auth, "_shutdown_future", None)
	monkeypatch.setattr(coseeing_auth, "_singleton_session", None)
	monkeypatch.setattr(coseeing_auth, "_singleton_adapter", None)

	future = coseeing_auth.shutdown_coseeing_auth()

	assert future.done()
	assert future.exception() is None


def test_has_saved_refresh_token_is_false_without_the_bundle(monkeypatch):
	from lib import coseeing_auth

	monkeypatch.setattr(coseeing_auth, "AUTH_AVAILABLE", False)

	assert coseeing_auth.has_saved_coseeing_refresh_token() is False


def test_no_module_deletion_or_path_injection_remains():
	source = Path("addon/globalPlugins/WordBridge/lib/coseeing_auth.py").read_text(encoding="utf8")

	assert "del sys.modules" not in source
	assert "sys.path.insert" not in source
	assert "_prepare_auth_dependencies" not in source
