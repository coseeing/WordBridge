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


def test_bundle_excludes_a_developer_machines_leftover_correction_reports(tmp_path):
	# web/workspace/ does not exist in git -- __init__.py's showReport() only
	# creates it at runtime, one level deeper than "web/workspace/*" reaches:
	# Path.match()'s "*" does not cross a path separator, so the bare pattern
	# only matches files directly inside web/workspace/, never inside
	# web/workspace/default/ or web/workspace/review/ where the add-on
	# actually writes. Build a throwaway source tree that reproduces that
	# layout so the exclusion patterns get genuinely exercised, since there is
	# no tracked fixture to bundle.
	source = tmp_path / "addon-src"
	leftover_files = [
		"globalPlugins/WordBridge/web/workspace/default/report.html",
		"globalPlugins/WordBridge/web/workspace/review/index.html",
	]
	for relative_path in leftover_files:
		path = source / relative_path
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text("leftover from a previous run")

	bundler = _load_bundler()
	build_vars = _load_build_vars()
	dest = tmp_path / "test.nvda-addon"
	bundler.createAddonBundleFromPath(source, str(dest), build_vars.excludedFiles)
	with zipfile.ZipFile(dest) as archive:
		names = archive.namelist()

	assert [name for name in names if name.endswith("report.html")] == []
	assert [name for name in names if name.endswith("index.html")] == []
