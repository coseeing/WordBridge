import importlib.util
import sys
import types
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_DIR = PROJECT_ROOT / "addon"


def _load_bundler():
	path = PROJECT_ROOT / "site_scons" / "site_tools" / "NVDATool" / "addon.py"
	spec = importlib.util.spec_from_file_location("_nvda_addon_bundler", path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


@contextmanager
def _stubbed_missing_build_tools():
	# buildVars.py imports site_scons.site_tools.NVDATool.typings, which forces
	# Python to run site_scons/site_tools/NVDATool/__init__.py first -- a
	# package's __init__ always executes before any of its submodules do.
	# That __init__ unconditionally does `from SCons.Script import Environment,
	# Builder` and `from .docs import md2html` (which itself does `import
	# markdown`), even though typings.py itself only imports from `typing` and
	# neither excludedFiles nor createAddonBundleFromPath (what this test
	# actually needs) touches SCons or markdown. Both are build-time-only
	# dependencies this test host does not install, so we install throwaway
	# stand-ins for the duration of the import and restore sys.modules
	# afterwards -- the same convention tests/conftest.py already uses to stub
	# addonHandler.
	fake_scons_script = types.ModuleType("SCons.Script")
	fake_scons_script.Environment = object
	fake_scons_script.Builder = object
	fake_scons = types.ModuleType("SCons")
	fake_scons.Script = fake_scons_script

	fakes = {
		"SCons": fake_scons,
		"SCons.Script": fake_scons_script,
		"markdown": types.ModuleType("markdown"),
	}

	had = {name: name in sys.modules for name in fakes}
	prior = {name: sys.modules.get(name) for name in fakes}

	# The exec below also imports and caches site_scons and every submodule it
	# pulls in (site_scons.site_tools.NVDATool, .addon, .manifests, .docs,
	# .typings, .utils) into sys.modules as a side effect, with
	# site_scons.site_tools.NVDATool.docs.markdown permanently bound to our
	# throwaway markdown stub and .Environment/.Builder bound to `object`.
	# Popping just the three fake keys leaves those cached, stub-poisoned
	# modules behind. Nothing else in this repo imports site_scons today, but
	# this batch has already been bitten twice by cross-test module-cache
	# contamination, so snapshot what is cached before the exec and drop every
	# site_scons* key the exec added, in the same finally as the fakes.
	before_modules = set(sys.modules)

	sys.modules.update(fakes)
	try:
		yield
	finally:
		for name in fakes:
			if had[name]:
				sys.modules[name] = prior[name]
			else:
				sys.modules.pop(name, None)
		for name in list(sys.modules):
			if name not in before_modules and (name == "site_scons" or name.startswith("site_scons.")):
				del sys.modules[name]


def _load_build_vars():
	path = PROJECT_ROOT / "buildVars.py"
	spec = importlib.util.spec_from_file_location("_wordbridge_build_vars", path)
	module = importlib.util.module_from_spec(spec)
	with _stubbed_missing_build_tools():
		spec.loader.exec_module(module)
	return module


@pytest.fixture(scope="module")
def bundle_names(tmp_path_factory):
	bundler = _load_bundler()
	build_vars = _load_build_vars()
	dest = tmp_path_factory.mktemp("bundle") / "test.nvda-addon"
	bundler.createAddonBundleFromPath(ADDON_DIR, str(dest), build_vars.excludedFiles)
	with zipfile.ZipFile(dest) as archive:
		return archive.namelist()


def test_bundle_excludes_bytecode_and_caches(bundle_names):
	assert [name for name in bundle_names if "__pycache__" in name] == []
	assert [name for name in bundle_names if name.endswith(".pyc")] == []
	assert [name for name in bundle_names if name.endswith(".pyo")] == []


def test_bundle_excludes_the_non_runtime_spreadsheet(bundle_names):
	assert [name for name in bundle_names if name.endswith(".xlsx")] == []


def test_bundle_keeps_the_runtime_dictionary(bundle_names):
	assert any(name.endswith("dict_revised_2015_20231228_csv.csv") for name in bundle_names)


def test_bundle_keeps_the_report_assets(bundle_names):
	assert any(name.endswith("web/templates/modules/vue.js") for name in bundle_names)
	assert any(name.endswith("web/templates/index.template") for name in bundle_names)


def test_bundle_keeps_the_vendored_auth_package(bundle_names):
	assert any("/package/" in name or name.startswith("package/") for name in bundle_names)


def test_bundle_keeps_the_single_catalog_and_omits_retired_catalog_inputs(bundle_names):
	assert any(name.endswith("setting/catalog.json") for name in bundle_names)
	assert not any("setting/ai/" in name for name in bundle_names)
	assert not any("setting/provider/" in name for name in bundle_names)
	assert not any(name.endswith("setting/price.json") for name in bundle_names)


def test_bundle_excludes_a_developer_machines_leftover_correction_reports(tmp_path):
	# web/workspace/ does not exist in git. showReport() used to rmtree() and
	# recreate it inside the add-on install directory on every report,
	# copytree()-ing web/templates/modules/ (flat -- vue.js and
	# sweetalert2.all.min.js, no deeper nesting) into it each time; reports
	# now go to the user workspace instead (lib/report.py's generate_report())
	# and web/workspace/ is never written by current code. The exclusion
	# patterns below stay regardless: they guard a developer machine that
	# still carries a web/workspace/ directory left over from an older build,
	# which bundling must still exclude. Path.match()'s "*" does not cross a
	# path separator, so a pattern has to name each depth it needs to reach
	# explicitly; these are the old showReport()'s *actual* filenames, not
	# invented placeholders -- an earlier round used "report.html"/
	# "index.html" and that mismatch with reality was exactly why it missed
	# web/workspace/review/modules/.
	source = tmp_path / "addon-src"
	leftover_files = [
		"globalPlugins/WordBridge/web/workspace/default/result.txt",
		"globalPlugins/WordBridge/web/workspace/review/result.txt",
		"globalPlugins/WordBridge/web/workspace/review/result.html",
		"globalPlugins/WordBridge/web/workspace/review/modules/vue.js",
		"globalPlugins/WordBridge/web/workspace/review/modules/sweetalert2.all.min.js",
	]
	# Same basename as one of the leftovers, but the actual template source
	# showReport() copies *from* -- must survive bundling. Without this, an
	# over-broad rule (e.g. excluding "*" or "*.js" everywhere) would make the
	# assertions below pass for the wrong reason; this makes the test fail in
	# both directions.
	survivor_file = "globalPlugins/WordBridge/web/templates/modules/vue.js"

	for relative_path in leftover_files + [survivor_file]:
		path = source / relative_path
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text("stub content")

	bundler = _load_bundler()
	build_vars = _load_build_vars()
	dest = tmp_path / "test.nvda-addon"
	bundler.createAddonBundleFromPath(source, str(dest), build_vars.excludedFiles)
	with zipfile.ZipFile(dest) as archive:
		names = set(archive.namelist())

	for relative_path in leftover_files:
		assert relative_path not in names, f"{relative_path} should have been excluded"
	assert survivor_file in names, "an over-broad exclusion pattern would also drop this"
