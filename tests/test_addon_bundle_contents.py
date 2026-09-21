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

	sys.modules.update(fakes)
	try:
		yield
	finally:
		for name in fakes:
			if had[name]:
				sys.modules[name] = prior[name]
			else:
				sys.modules.pop(name, None)


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
