import builtins
import hashlib
import importlib
import re
import shutil
import struct
import subprocess
import sys
import textwrap
import types
from collections import Counter
from importlib.machinery import ExtensionFileLoader, ModuleSpec, SourceFileLoader
from pathlib import Path

import pytest
from lib import vendor
from lib.vendor import _make_sandbox_import

ISOLATED = frozenset({"alpha", "beta"})

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "addon" / "globalPlugins" / "WordBridge" / "package"
ADDON_ROOT = PACKAGE_ROOT.parent


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
	"""A fabricated tree: alpha lazily imports beta by absolute name; gamma
	imports a real host stdlib module (json) -- gamma is never a name in the
	fabricated ISOLATED set, so its plain `import json` is category 3 shaped:
	delegated unchanged, resolving to the real host copy.
	"""
	alpha = tmp_path / "alpha"
	alpha.mkdir()
	(alpha / "__init__.py").write_text(
		"def get():\n\timport beta\n\treturn beta.VALUE\n",
		encoding="utf8",
	)
	beta = tmp_path / "beta"
	beta.mkdir()
	(beta / "__init__.py").write_text("VALUE = 'sandbox'\n", encoding="utf8")
	gamma = tmp_path / "gamma"
	gamma.mkdir()
	(gamma / "__init__.py").write_text(
		"import json\ndef get_json():\n\treturn json\n",
		encoding="utf8",
	)
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
		sys.meta_path[:] = [finder for finder in sys.meta_path if getattr(finder, "prefix", None) != prefix]


def test_namespace_path_holds_only_roots_that_exist(sandbox_root, install_sandbox):
	missing = sandbox_root / "not-here"

	namespace = install_sandbox([str(sandbox_root), str(missing)], "_wb_t1", {"alpha"})

	assert namespace.__path__ == [str(sandbox_root)]


def test_namespace_spec_submodule_search_locations_matches_path(sandbox_root, install_sandbox):
	"""The import machinery only ever consults __path__, but pkgutil.iter_modules()
	and importlib.resources read __spec__.submodule_search_locations instead;
	ModuleSpec(..., is_package=True) defaults that to its own empty list, so
	without this the namespace would look like an empty package to either tool.
	"""
	namespace = install_sandbox([str(sandbox_root)], "_wb_t1b", {"alpha"})

	assert namespace.__spec__.submodule_search_locations is namespace.__path__


def test_sandboxed_code_resolves_a_real_host_module(sandbox_root, install_sandbox):
	"""Spec test 3, at integration level: a category-3-shaped name imported
	from real sandboxed code -- run through the actual installed sandbox
	end to end, not the `recording_import` stand-in `test_host_name_is_
	delegated_untouched` above uses -- resolves to the real host copy.
	"""
	import json as host_json

	install_sandbox([str(sandbox_root)], "_wb_t1c", {"alpha", "beta"})

	gamma = importlib.import_module("_wb_t1c.gamma")

	assert gamma.get_json() is host_json
	assert gamma.json is host_json
	assert gamma.__dict__["__builtins__"]["__import__"] is not builtins.__import__


def test_install_is_idempotent(sandbox_root, install_sandbox):
	first = install_sandbox([str(sandbox_root)], "_wb_t2", {"alpha"})
	finders_after_first = len(sys.meta_path)

	second = install_sandbox([str(sandbox_root)], "_wb_t2", {"alpha"})

	assert second is first
	assert len(sys.meta_path) == finders_after_first


def test_install_reinstalls_a_missing_finder_when_the_namespace_still_exists(sandbox_root, install_sandbox):
	first = install_sandbox([str(sandbox_root)], "_wb_t2a", {"alpha"})
	sys.meta_path[:] = [finder for finder in sys.meta_path if getattr(finder, "prefix", None) != "_wb_t2a"]

	second = install_sandbox([str(sandbox_root)], "_wb_t2a", {"alpha"})

	assert second is first
	matching = [f for f in sys.meta_path if getattr(f, "prefix", None) == "_wb_t2a"]
	assert len(matching) == 1


def test_install_recreates_a_missing_namespace_without_duplicating_the_finder(sandbox_root, install_sandbox):
	first = install_sandbox([str(sandbox_root)], "_wb_t2b", {"alpha"})
	del sys.modules["_wb_t2b"]

	second = install_sandbox([str(sandbox_root)], "_wb_t2b", {"alpha"})

	assert second is not first
	assert sys.modules["_wb_t2b"] is second
	matching = [f for f in sys.meta_path if getattr(f, "prefix", None) == "_wb_t2b"]
	assert len(matching) == 1


def test_lazy_import_inside_a_function_resolves_to_the_sandbox(sandbox_root, install_sandbox, monkeypatch):
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
	for dirname in (
		vendor.STDLIB_GAPFILL_DIRNAME,
		vendor.CRYPTOGRAPHY_GAPFILL_DIRNAME,
		"_coseeing_auth_deps",
		"__pycache__",
	):
		namespace_dir = sandbox_root / dirname
		namespace_dir.mkdir()
		(namespace_dir / "stub.py").write_text("VALUE = 'stub'\n", encoding="utf8")

	install_sandbox([str(sandbox_root)], "_wb_t6", {"alpha"})

	for dirname in (
		vendor.STDLIB_GAPFILL_DIRNAME,
		vendor.CRYPTOGRAPHY_GAPFILL_DIRNAME,
		"_coseeing_auth_deps",
		"__pycache__",
	):
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

	Also imports the real ``hanzidentifier``, on the eager local-correction
	path every user hits: its ``from zhon import cedict`` is the exact
	rewrite the spec names by example (spec:92-93), and had no auto coverage
	of its own before this.
	"""
	install_sandbox([str(PACKAGE_ROOT)], "_wb_t7", {"pypinyin", "hanzidentifier", "zhon"})

	top = importlib.import_module("_wb_t7.pypinyin")
	sub = importlib.import_module("_wb_t7.pypinyin.contrib")
	hanzi = importlib.import_module("_wb_t7.hanzidentifier")

	assert top.__name__ == "_wb_t7.pypinyin"
	assert sub.__name__ == "_wb_t7.pypinyin.contrib"
	assert hanzi.__name__ == "_wb_t7.hanzidentifier"
	assert hanzi.cedict.__name__ == "_wb_t7.zhon.cedict"


def test_finder_leaves_extension_loaders_unwrapped_but_wraps_source_loaders(monkeypatch):
	"""No bundled package ships a native extension today (cryptography, the one
	that did, now comes from the host), but a future dependency could.

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
		/ "addon"
		/ "globalPlugins"
		/ "WordBridge"
		/ "package"
		/ "_coseeing_auth_deps"
	)

	assert (deps_dir / "py313-win_amd64").is_dir()
	assert vendor.runtime_key() == "py313-win_amd64"


def test_every_bundled_top_level_name_is_classified():
	"""Adding a package to the bundle without classifying it -- or shipping a
	HOST_ONLY copy -- must fail here."""
	deps_root = PACKAGE_ROOT / "_coseeing_auth_deps"
	roots = [PACKAGE_ROOT] + sorted(entry for entry in deps_root.glob("*") if entry.is_dir())
	skip = {"__pycache__", "_stdlib_gapfill", "_cryptography_gapfill", "_coseeing_auth_deps"}
	names = []
	for root in roots:
		for entry in root.iterdir():
			if entry.name in skip:
				continue
			if entry.is_dir():
				if not entry.name.endswith(".dist-info"):
					names.append(entry.name)
			elif entry.name.endswith(".py"):
				names.append(entry.name[:-3])
			elif entry.name.endswith(".pyd"):
				names.append(entry.name.split(".")[0])

	assert set(names) == vendor.ISOLATED
	# HOST_ONLY copies are never loaded, so shipping them is dead weight -- and
	# for cryptography, actively harmful: see test_no_cryptography_is_bundled.
	assert not set(names) & vendor.HOST_ONLY
	# The same top-level name present in more than one root is the precondition
	# for a namespace __path__ that spans both -- vendor.install() would then
	# resolve it to whichever root's copy PathFinder happens to walk first, a
	# nondeterministic winner that varies with filesystem/OS listing order.
	duplicated = {name for name, count in Counter(names).items() if count > 1}
	assert not duplicated, f"present in more than one root: {duplicated}"


def test_categories_do_not_overlap():
	assert not (vendor.ISOLATED & vendor.HOST_ONLY)


def test_category_sizes_and_spot_membership():
	"""Pins WHICH category each name is in, not just the union and the overlap.

	Moving a name from one frozenset to the other leaves both tests above
	green -- the union is unchanged and the intersection is still empty -- so
	the isolation behaviour would silently invert for that package with
	nothing here to catch it.
	"""
	assert len(vendor.ISOLATED) == 8
	assert len(vendor.HOST_ONLY) == 9
	assert {"coseeing_auth", "authlib", "joserfc", "jwt"} <= vendor.ISOLATED
	assert {"requests", "_cffi_backend", "cryptography"} <= vendor.HOST_ONLY


def test_gapfill_skips_a_module_the_host_already_provides(tmp_path):
	directory = tmp_path / "_stdlib_gapfill"
	directory.mkdir()
	(directory / "json.py").write_text("RAISE = 'ours'\n", encoding="utf8")
	host_json = sys.modules["json"]

	try:
		registered, failures = vendor.install_stdlib_gapfill(tmp_path)

		assert registered == []
		assert failures == []
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
		registered, failures = vendor.install_stdlib_gapfill(tmp_path)

		assert registered == []
		assert failures == []
		assert not hasattr(sys.modules[name], "RAISE")
	finally:
		sys.modules.pop(name, None)


def test_gapfill_registers_a_module_the_host_lacks(tmp_path, monkeypatch):
	directory = tmp_path / "_stdlib_gapfill"
	directory.mkdir()
	(directory / "wbfakegap.py").write_text("VALUE = 'gapfill'\n", encoding="utf8")
	monkeypatch.delitem(sys.modules, "wbfakegap", raising=False)

	registered, failures = vendor.install_stdlib_gapfill(tmp_path)
	try:
		assert registered == ["wbfakegap"]
		assert failures == []
		assert sys.modules["wbfakegap"].VALUE == "gapfill"
		assert sys.modules["wbfakegap"].__name__ == "wbfakegap"
	finally:
		sys.modules.pop("wbfakegap", None)


def test_gapfill_registers_a_module_whose_name_has_a_single_leading_underscore(tmp_path, monkeypatch):
	"""A single leading underscore must not be excluded like __init__.py is:
	NVDA's stripped stdlib can drop a private helper module (e.g. _pydecimal)
	just as easily as a public one, and the data-driven gap-fill must still
	fill that gap rather than silently skipping the file.
	"""
	directory = tmp_path / "_stdlib_gapfill"
	directory.mkdir()
	(directory / "_wbfakegap.py").write_text("VALUE = 'gapfill'\n", encoding="utf8")
	monkeypatch.delitem(sys.modules, "_wbfakegap", raising=False)

	registered, failures = vendor.install_stdlib_gapfill(tmp_path)
	try:
		assert registered == ["_wbfakegap"]
		assert failures == []
		assert sys.modules["_wbfakegap"].VALUE == "gapfill"
	finally:
		sys.modules.pop("_wbfakegap", None)


def test_gapfill_is_a_no_op_without_the_directory(tmp_path):
	assert vendor.install_stdlib_gapfill(tmp_path) == ([], [])


def test_gapfill_records_a_failure_without_raising_when_our_own_copy_fails_to_exec(tmp_path, monkeypatch):
	"""spec:270: installing the sandbox never raises, even when a gap-fill file
	we ship ourselves is the one that is broken -- e.g. Task 1's probe adding a
	second file whose own import is missing. A broken file must not stop the
	rest of the directory from being registered, and a module it partially
	executed must not linger in sys.modules.
	"""
	directory = tmp_path / "_stdlib_gapfill"
	directory.mkdir()
	(directory / "wbbrokengap.py").write_text("import this_module_does_not_exist_anywhere\n", encoding="utf8")
	(directory / "wbgoodgap.py").write_text("VALUE = 'gapfill'\n", encoding="utf8")
	monkeypatch.delitem(sys.modules, "wbbrokengap", raising=False)
	monkeypatch.delitem(sys.modules, "wbgoodgap", raising=False)

	try:
		registered, failures = vendor.install_stdlib_gapfill(tmp_path)

		assert registered == ["wbgoodgap"]
		assert sys.modules["wbgoodgap"].VALUE == "gapfill"
		assert len(failures) == 1
		failed_name, error = failures[0]
		assert failed_name == "wbbrokengap"
		assert isinstance(error, ImportError)
		assert "wbbrokengap" not in sys.modules
	finally:
		sys.modules.pop("wbbrokengap", None)
		sys.modules.pop("wbgoodgap", None)


def test_gapfill_records_a_failure_without_raising_when_the_host_probe_itself_raises(tmp_path, monkeypatch):
	"""The host probe (`builtins.__import__(name)`) only treats ImportError as
	"the host does not have this module" (fact 9's documented case). A host
	module that exists on disk but raises something else while it executes --
	e.g. a RuntimeError -- must still be recorded as a failure rather than
	crashing install_stdlib_gapfill() and, through it, add-on load.
	"""
	name = "wbforcedhostprobefailure"
	directory = tmp_path / "_stdlib_gapfill"
	directory.mkdir()
	(directory / f"{name}.py").write_text("VALUE = 'gapfill'\n", encoding="utf8")
	monkeypatch.delitem(sys.modules, name, raising=False)

	real_import = builtins.__import__

	def fake_import(imported_name, *args, **kwargs):
		if imported_name == name:
			raise RuntimeError("boom")
		return real_import(imported_name, *args, **kwargs)

	monkeypatch.setattr(builtins, "__import__", fake_import)

	registered, failures = vendor.install_stdlib_gapfill(tmp_path)

	assert registered == []
	assert len(failures) == 1
	failed_name, error = failures[0]
	assert failed_name == name
	assert isinstance(error, RuntimeError)
	assert name not in sys.modules


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


def test_unavailable_reason_distinguishes_missing_directory_from_broken_bundle(monkeypatch):
	"""Spec:284 row 1 (runtime key underivable or directory absent) and row 2
	(bundle present, module fails to load) must stay distinguishable, because
	their remedies differ. Without _wb_vendor.__path__ in the message, both
	read as the byte-identical
	"ModuleNotFoundError: No module named '_wb_vendor.authlib...'".
	"""
	from lib import coseeing_auth

	same_error = ModuleNotFoundError(
		"No module named '_wb_vendor.authlib.integrations.base_client.errors'",
		name="_wb_vendor.authlib.integrations.base_client.errors",
	)
	monkeypatch.setattr(coseeing_auth, "_AUTH_IMPORT_ERROR", same_error)
	monkeypatch.setattr(
		coseeing_auth,
		"_AUTH_IMPORT_MODULE",
		"_wb_vendor.authlib.integrations.base_client.errors",
	)
	monkeypatch.setattr(coseeing_auth.vendor, "runtime_key", lambda: "py313-win_amd64")

	directory_absent = types.ModuleType("_wb_vendor")
	directory_absent.__path__ = [r"C:\addon\package"]
	monkeypatch.setitem(sys.modules, "_wb_vendor", directory_absent)
	message_directory_absent = coseeing_auth.unavailable_reason()

	bundle_present_but_broken = types.ModuleType("_wb_vendor")
	bundle_present_but_broken.__path__ = [
		r"C:\addon\package",
		r"C:\addon\package\_coseeing_auth_deps\py313-win_amd64",
	]
	monkeypatch.setitem(sys.modules, "_wb_vendor", bundle_present_but_broken)
	message_bundle_present = coseeing_auth.unavailable_reason()

	assert message_directory_absent != message_bundle_present
	assert r"['C:\\addon\\package']" in message_directory_absent
	assert "_coseeing_auth_deps" in message_bundle_present


def test_unavailable_reason_names_which_import_statement_failed(monkeypatch):
	"""Deferred minor folded into the row 1/row 2 fix: with the broadened
	`except Exception`, a bundle module raising something other than
	ImportError has no `.name` attribute to name a module with, so the two
	import statements in lib/coseeing_auth.py must name themselves.
	"""
	from lib import coseeing_auth

	monkeypatch.setattr(coseeing_auth, "_AUTH_IMPORT_ERROR", RuntimeError("boom"))
	monkeypatch.setattr(coseeing_auth, "_AUTH_IMPORT_MODULE", "_wb_vendor.coseeing_auth.errors")

	message = coseeing_auth.unavailable_reason()

	assert "_wb_vendor.coseeing_auth.errors" in message
	assert "RuntimeError: boom" in message


def test_unavailable_reason_flags_a_host_only_name_going_missing(monkeypatch):
	"""Spec:284 row 3: a category 3 (host-only) package going missing must say
	the host environment changed, not just name the module.
	"""
	from lib import coseeing_auth

	error = ModuleNotFoundError("No module named 'requests'", name="requests")
	monkeypatch.setattr(coseeing_auth, "_AUTH_IMPORT_ERROR", error)
	monkeypatch.setattr(
		coseeing_auth,
		"_AUTH_IMPORT_MODULE",
		"_wb_vendor.authlib.integrations.base_client.errors",
	)

	message = coseeing_auth.unavailable_reason()

	assert "host environment changed" in message
	assert "'requests'" in message


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
	source = (PACKAGE_ROOT.parent / "lib" / "coseeing_auth.py").read_text(encoding="utf8")

	assert "del sys.modules" not in source
	assert "sys.path.insert" not in source
	assert "_prepare_auth_dependencies" not in source


def test_coseeing_auth_reports_unavailable_when_no_bundle_resolves(tmp_path):
	"""Exercises the actual `except Exception` branch in coseeing_auth.py.

	`test_coseeing_auth_module_imports_without_the_bundle` above only passes
	against a module whose import already succeeded (see
	tests/test_coseeing_auth.py, which registers working `_wb_vendor.*` stubs
	before this file's tests run), so it never proves the placeholder branch
	exists or works. This test installs the sandbox in a fresh subprocess
	against a package tree with no `coseeing_auth` or `authlib` packages in it
	at all -- nothing resolvable, from any file order -- and asserts
	`AUTH_AVAILABLE` actually goes False and every placeholder name binds to a
	subclass of the module's own `_UnavailableAuthError`.
	"""
	addon = tmp_path / "addon"
	lib = addon / "lib"
	package = addon / "package"
	lib.mkdir(parents=True)
	package.mkdir(parents=True)  # deliberately empty: no coseeing_auth, no authlib

	shutil.copy2(PACKAGE_ROOT.parent / "lib" / "coseeing_auth.py", lib / "coseeing_auth.py")
	shutil.copy2(PACKAGE_ROOT.parent / "lib" / "__init__.py", lib / "__init__.py")
	shutil.copy2(PACKAGE_ROOT.parent / "lib" / "vendor.py", lib / "vendor.py")

	code = """
	import sys
	import types
	sys.path.insert(0, sys.argv[1])
	addon_handler = types.ModuleType("addonHandler")
	addon_handler.initTranslation = lambda: None
	sys.modules["addonHandler"] = addon_handler
	from lib import vendor
	vendor.install(vendor.default_roots(sys.argv[2]))
	import lib.coseeing_auth as module
	assert module.AUTH_AVAILABLE is False, "expected no bundle to resolve"
	names = (
		"OAuthError", "ClientClosedError", "RestoreError",
		"TokenUnavailableError", "TokenValidationError",
	)
	for name in names:
		cls = getattr(module, name)
		assert issubclass(cls, module._UnavailableAuthError), name
	"""
	subprocess.run(
		[sys.executable, "-S", "-c", textwrap.dedent(code), str(addon), str(package)],
		check=True,
		capture_output=True,
		text=True,
	)


def test_plugin_entry_point_no_longer_injects_sys_path():
	source = (ADDON_ROOT / "__init__.py").read_text(encoding="utf8")

	assert "sys.path.insert" not in source
	assert "vendor.install" in source


def test_installing_the_sandbox_adds_exactly_one_global_name(sandbox_root, install_sandbox):
	path_before = list(sys.path)
	modules_before = set(sys.modules)

	install_sandbox([str(sandbox_root)], "_wb_t5", {"alpha"})

	assert sys.path == path_before
	assert set(sys.modules) - modules_before == {"_wb_t5"}


def test_local_correction_imports_resolve_through_the_prefix():
	"""The add-on's own modules must not rely on package/ being on sys.path."""
	for relative in (
		"lib/tasks/typo/prompt.py",
		"lib/tasks/typo/utils.py",
		"lib/tasks/typo/text_policy.py",
		"lib/text/chinese.py",
	):
		source = ADDON_ROOT / relative
		text = source.read_text(encoding="utf8")
		for bare in (
			"from pypinyin",
			"from chinese_converter",
			"import chinese_converter",
			"from hanzidentifier",
		):
			assert f"\n{bare}" not in f"\n{text}", f"{relative} still imports {bare!r} bare"


_BARE_VENDORED_IMPORT = re.compile(
	r"^[ \t]*(?:from|import)[ \t]+"
	r"(pypinyin|zhon|hanzidentifier|chinese_converter|coseeing_auth|authlib|jwt|joserfc|cryptography)\b",
)


def test_no_bare_vendored_import_exists_anywhere_outside_package():
	"""Standing gate for Step 7's grep, run as part of the suite rather than by
	hand: walks every .py file under the add-on except package/ itself (the
	vendored sources legitimately import each other bare -- the sandbox's
	__import__ shim rewrites those at load time) and fails on any bare import
	of a vendored package name, catching a violation the four hand-picked
	files in the test above cannot see (any other module, `import pypinyin`
	without `from`, `import zhon`, ...).  Only meaningful once package/ is off
	sys.path for the whole test session -- otherwise a violation would still
	resolve at runtime and this test alone would not catch it.
	"""
	violations = []
	for path in sorted(ADDON_ROOT.rglob("*.py")):
		relative = path.relative_to(ADDON_ROOT)
		if relative.parts[0] == "package":
			continue
		text = path.read_text(encoding="utf8")
		for line_number, line in enumerate(text.splitlines(), start=1):
			if _BARE_VENDORED_IMPORT.match(line):
				violations.append(f"{relative}:{line_number}: {line.strip()}")

	assert violations == []


def test_plugin_entry_point_installs_the_sandbox_before_importing_coseeing_auth():
	"""Pins the lifecycle's hard constraint: installing the sandbox must
	precede every `_wb_vendor` import, including the transitive one inside
	`lib/coseeing_auth.py`.  A source-order assertion is cheap and catches a
	future edit that moves the install below the import without needing to
	actually exercise plugin load end-to-end.

	Asserts against the *first* relative import in the file (`.dialogs`,
	which transitively reaches `lib/tasks/typo/text_policy.py`'s own
	`_wb_vendor` import) rather than only the two imports named below, so
	moving the install below an earlier consumer -- not just below
	`coseeing_auth` or `hanzidentifier` specifically -- still fails here.
	"""
	source = (ADDON_ROOT / "__init__.py").read_text(encoding="utf8")

	install_index = source.index("\nvendor.install(")
	# The *first* relative import overall is "from .lib import vendor" itself
	# (needed to reach vendor.install in the first place, so it necessarily
	# precedes it, and searching from install_index would only ever find an
	# index >= install_index -- making the comparison below vacuously true).
	# What must come after the install is the first relative import *past
	# that one line*, since any of those can transitively reach a _wb_vendor
	# consumer such as lib/tasks/typo/text_policy.py.
	vendor_import = "from .lib import vendor"
	first_relative_import_after_install_index = source.index(
		"\nfrom .",
		source.index(vendor_import) + len(vendor_import),
	)
	coseeing_auth_import_index = source.index("from .lib import coseeing_auth")
	hanzidentifier_import_index = source.index("from _wb_vendor.hanzidentifier import has_chinese")

	assert install_index < first_relative_import_after_install_index
	assert install_index < coseeing_auth_import_index
	assert install_index < hanzidentifier_import_index


# --- cryptography: the host's copy, with the files py2exe left out filled in ---

# The six files NVDA's py2exe build leaves out of library.zip, pinned to the
# cryptography 48.0.1 wheel they are copied from verbatim (each digest matches
# that wheel's RECORD). 48.0.1 rather than a newer release because its
# keywrap.py is pure Python over Cipher/AES/ECB, while 50.x's calls
# `_rust.openssl.keywrap`, which a 48.x host does not have; the other five are
# byte-identical across 48.0.1, 50.0.0 and 50.0.1.
_CRYPTOGRAPHY_GAPFILL_SHA256 = {
	"cryptography/hazmat/primitives/kdf/__init__.py": "bf7ca2601194dbbd84a233576f07d865d6db7c8f5c54e0821b79d78530dd6b79",
	"cryptography/hazmat/primitives/kdf/concatkdf.py": "0459ce292ef6b71285d3242f012af435aeee873bcb1e95027242b988d002fda4",
	"cryptography/hazmat/primitives/kdf/hkdf.py": "33494011f468738929a78fa7c038fdc81faf359ba420e60442b5255ac04d9fda",
	"cryptography/hazmat/primitives/kdf/pbkdf2.py": "5dc86493df6cf8c93a6fa2920a8baa764f0557288d54e48521e9e69d6ded2e04",
	"cryptography/hazmat/primitives/keywrap.py": "508fb4504490c415d3294d47aeb4685300e216cad689ff35ab25e55757bb9326",
	"cryptography/hazmat/primitives/padding.py": "413f94f8dbd5d9e4063b5c153db0e234635273d91e4434be8a0e5c40eacbcf41",
}


@pytest.fixture
def host_gap_root(tmp_path):
	"""A fake host package with one submodule present and the rest missing,
	plus a gap-fill directory that carries copies of all of them."""
	host = tmp_path / "host"
	(host / "wbhost").mkdir(parents=True)
	(host / "wbhost" / "__init__.py").write_text("", encoding="utf8")
	(host / "wbhost" / "present.py").write_text("ORIGIN = 'host'\n", encoding="utf8")

	gap = tmp_path / "package" / vendor.CRYPTOGRAPHY_GAPFILL_DIRNAME / "wbhost"
	(gap / "sub").mkdir(parents=True)
	(gap / "present.py").write_text("ORIGIN = 'gapfill'\n", encoding="utf8")
	(gap / "absent.py").write_text("ORIGIN = 'gapfill'\n", encoding="utf8")
	(gap / "sub" / "__init__.py").write_text("ORIGIN = 'gapfill'\n", encoding="utf8")
	(gap / "sub" / "leaf.py").write_text("ORIGIN = 'gapfill-leaf'\n", encoding="utf8")
	return tmp_path


@pytest.fixture
def install_host_gapfill(host_gap_root, monkeypatch):
	"""Install a disposable gap-fill over the fake host, then undo it."""
	monkeypatch.syspath_prepend(str(host_gap_root / "host"))
	before = dict(sys.modules)
	meta_before = list(sys.meta_path)
	names = frozenset({"wbhost.present", "wbhost.absent", "wbhost.sub", "wbhost.sub.leaf"})

	def install():
		return vendor.install_cryptography_gapfill(host_gap_root / "package", names=names)

	yield install
	sys.meta_path[:] = meta_before
	for name in set(sys.modules) - set(before):
		del sys.modules[name]


def test_cryptography_comes_from_the_host():
	"""Regression for NVDA Remote's "Get external IP" hanging forever.

	NVDA imports its own cryptography before any add-on loads
	(bdDetect -> handyTech -> globalCommands -> _remoteClient.server), and
	_remoteClient.server keeps those module objects. Replacing the canonical
	name with a second copy -- what install_shadowed() did -- made the host's
	`_rust` type-check NVDA's own `hashes.SHA256()` against our classes, so
	LocalRelayServer's certificate generation raised TypeError outside the
	portcheck thread's try block and the progress dialog never closed.
	"""
	assert "cryptography" in vendor.HOST_ONLY
	assert "cryptography" not in vendor.ISOLATED
	assert not hasattr(vendor, "SHADOWED")
	assert not hasattr(vendor, "install_shadowed")


def test_no_cryptography_is_bundled():
	for root in [PACKAGE_ROOT, *sorted((PACKAGE_ROOT / "_coseeing_auth_deps").glob("*"))]:
		assert not (root / "cryptography").exists(), root
		assert not list(root.glob("cryptography-*.dist-info")), root


def test_the_cryptography_gapfill_ships_verbatim():
	root = PACKAGE_ROOT / vendor.CRYPTOGRAPHY_GAPFILL_DIRNAME
	shipped = {
		path.relative_to(root).as_posix() for path in root.rglob("*.py") if "__pycache__" not in path.parts
	}
	assert shipped == set(_CRYPTOGRAPHY_GAPFILL_SHA256)
	for relative, expected in _CRYPTOGRAPHY_GAPFILL_SHA256.items():
		normalized = (root / relative).read_bytes().replace(b"\r\n", b"\n")
		assert hashlib.sha256(normalized).hexdigest() == expected, relative
	for license_name in ("LICENSE", "LICENSE.APACHE", "LICENSE.BSD"):
		assert (root / license_name).is_file(), license_name


def test_the_default_gapfill_names_match_the_shipped_files():
	expected = {
		relative[: -len("/__init__.py")] if relative.endswith("/__init__.py") else relative[: -len(".py")]
		for relative in _CRYPTOGRAPHY_GAPFILL_SHA256
	}
	assert vendor.CRYPTOGRAPHY_GAPFILL == {name.replace("/", ".") for name in expected}


def test_gapfill_serves_a_module_the_host_lacks(install_host_gapfill):
	assert install_host_gapfill() is True
	assert importlib.import_module("wbhost.absent").ORIGIN == "gapfill"


def test_gapfill_never_replaces_a_module_the_host_has(install_host_gapfill):
	install_host_gapfill()
	assert importlib.import_module("wbhost.present").ORIGIN == "host"


def test_gapfill_serves_a_missing_subpackage_and_its_children(install_host_gapfill):
	install_host_gapfill()
	assert importlib.import_module("wbhost.sub").ORIGIN == "gapfill"
	assert importlib.import_module("wbhost.sub.leaf").ORIGIN == "gapfill-leaf"


def test_gapfill_evicts_nothing(install_host_gapfill):
	host = importlib.import_module("wbhost")
	present = importlib.import_module("wbhost.present")
	modules_before = dict(sys.modules)

	install_host_gapfill()

	assert dict(sys.modules) == modules_before
	assert sys.modules["wbhost"] is host
	assert sys.modules["wbhost.present"] is present


def test_gapfill_finder_runs_last_and_declines_every_other_name(install_host_gapfill):
	"""Appended, not inserted: it is only ever asked after every host finder
	has already come up empty, so it cannot outrank the host by construction."""
	install_host_gapfill()
	finder = sys.meta_path[-1]
	assert isinstance(finder, vendor._GapFillFinder)
	assert finder.find_spec("json") is None
	assert finder.find_spec("wbhost") is None
	assert finder.find_spec("wbhost.absentnot") is None


def test_gapfill_inserts_exactly_one_finder(install_host_gapfill):
	install_host_gapfill()
	install_host_gapfill()
	assert len([f for f in sys.meta_path if isinstance(f, vendor._GapFillFinder)]) == 1


def test_gapfill_is_a_no_op_without_its_directory(tmp_path):
	meta_before = list(sys.meta_path)
	assert vendor.install_cryptography_gapfill(tmp_path) is False
	assert sys.meta_path == meta_before


def test_gapfill_never_raises(monkeypatch, tmp_path):
	(tmp_path / vendor.CRYPTOGRAPHY_GAPFILL_DIRNAME).mkdir()
	meta_before = list(sys.meta_path)

	class Exploding(list):
		def append(self, item):
			raise RuntimeError("boom")

	monkeypatch.setattr(sys, "meta_path", Exploding(meta_before))
	assert vendor.install_cryptography_gapfill(tmp_path) is False


def test_nvda_remote_certificate_survives_coseeing_auth_loading(tmp_path):
	"""End-to-end regression on a real cryptography standing in for NVDA's.

	The host copy is trimmed the way py2exe trims it (the six gap-fill files
	removed), NVDA's _remoteClient.server imports are replayed first, and only
	then is the add-on's import setup run and the whole Coseeing auth stack
	(authlib -> joserfc -> the gap-filled modules, plus PyJWT) imported.
	Afterwards NVDA's own module objects must still be the registered ones,
	and LocalRelayServer's certificate generation -- which raised TypeError
	under install_shadowed() -- must succeed.
	"""
	host = pytest.importorskip("cryptography")
	pytest.importorskip("requests")
	runtimes = sorted(entry for entry in (PACKAGE_ROOT / "_coseeing_auth_deps").glob("*") if entry.is_dir())
	assert runtimes, "no runtime bundle to take authlib/joserfc/jwt from"

	trimmed = tmp_path / "host"
	shutil.copytree(Path(host.__file__).parent, trimmed / "cryptography")
	primitives = trimmed / "cryptography" / "hazmat" / "primitives"
	shutil.rmtree(primitives / "kdf")
	(primitives / "keywrap.py").unlink()
	(primitives / "padding.py").unlink()

	code = textwrap.dedent("""
		import datetime, importlib, importlib.util, sys
		addon_lib, package, runtime, trimmed = sys.argv[1:5]
		sys.path.insert(0, trimmed)

		# NVDA startup: _remoteClient/server.py:40-43, before any add-on loads.
		from cryptography import x509
		from cryptography.hazmat.primitives import hashes, serialization
		from cryptography.hazmat.primitives.asymmetric import rsa
		from cryptography.x509.oid import NameOID
		assert importlib.util.find_spec("cryptography.hazmat.primitives.padding") is None
		host_modules = {n: m for n, m in sys.modules.items() if n.split(".")[0] == "cryptography"}

		# Add-on load, in __init__.py's order.
		sys.path.insert(0, addon_lib)
		import vendor
		vendor.install([package, runtime])
		assert vendor.install_cryptography_gapfill(package) is True

		auth = importlib.import_module("_wb_vendor.coseeing_auth")
		jwt = importlib.import_module("_wb_vendor.jwt")
		jwe = importlib.import_module("_wb_vendor.joserfc.jwe")
		jwk = importlib.import_module("_wb_vendor.joserfc.jwk")
		importlib.import_module("_wb_vendor.authlib.integrations.requests_client")

		for name, module in host_modules.items():
			assert sys.modules[name] is module, "host module replaced: " + name
		copies = [n for n, m in sys.modules.items()
			if n.split(".")[0] == "cryptography" and runtime in (getattr(m, "__file__", None) or "")]
		assert not copies, copies
		for name in ("kdf", "kdf.concatkdf", "keywrap", "padding"):
			module = sys.modules["cryptography.hazmat.primitives." + name]
			assert module.__file__.startswith(package), (name, module.__file__)

		# ID-token verification path.
		key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
		token = jwt.encode({"sub": "s"}, key, algorithm="RS256")
		assert jwt.decode(token, key.public_key(), algorithms=["RS256"])["sub"] == "s"

		# joserfc on the gap-filled modules: keywrap, concatkdf, padding.
		ec = jwk.ECKey.generate_key("P-256")
		for alg, enc, k in (
			("A128KW", "A128CBC-HS256", jwk.OctKey.generate_key(128)),
			("ECDH-ES+A128KW", "A128GCM", ec),
		):
			sealed = jwe.encrypt_compact({"alg": alg, "enc": enc}, b"hi", k)
			assert jwe.decrypt_compact(sealed, k).plaintext == b"hi", alg

		# NVDA Remote: RemoteCertificateManager._generateSelfSignedCert.
		private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
		name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "NVDA Remote Access Service")])
		now = datetime.datetime.now(datetime.timezone.utc)
		cert = (
			x509.CertificateBuilder().subject_name(name).issuer_name(name)
			.public_key(private.public_key()).serial_number(x509.random_serial_number())
			.not_valid_before(now).not_valid_after(now + datetime.timedelta(days=365))
			.sign(private, hashes.SHA256())
		)
		assert cert.fingerprint(hashes.SHA256())
		private.private_bytes(
			encoding=serialization.Encoding.PEM,
			format=serialization.PrivateFormat.PKCS8,
			encryption_algorithm=serialization.NoEncryption(),
		)
		print("ok")
	""")
	result = subprocess.run(
		[
			sys.executable,
			"-c",
			code,
			str(ADDON_ROOT / "lib"),
			str(PACKAGE_ROOT),
			str(runtimes[0]),
			str(trimmed),
		],
		check=False,
		capture_output=True,
		text=True,
	)
	assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
