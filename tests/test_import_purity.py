import ast
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"

# The Critical whole-branch finding: settings_repository.py:3 used to be a
# bare `from lib.catalog.selection import normalize_selection` -- an absolute
# import of an add-on-internal name. It only ever resolved because
# tests/conftest.py puts the add-on directory on sys.path; under NVDA, where
# the add-on's own directory is never on sys.path, that import raises
# ModuleNotFoundError and takes the whole add-on down. Every other internal
# import in the tree is relative; this scan is the gate that catches the next
# one before it ships.
TOP_LEVEL_INTERNAL_NAMES = frozenset({"lib", "dialogs", "configManager", "dictionary", "settings_repository"})


def _internal_python_files():
	# package/ is vendored third-party code (coseeing_auth et al.), not
	# add-on-internal source -- excluded deliberately, the same way the spec
	# excludes it elsewhere.
	return sorted(
		path for path in ADDON_PATH.rglob("*.py")
		if "package" not in path.relative_to(ADDON_PATH).parts
	)


def test_no_addon_module_imports_an_internal_package_absolutely():
	internal_files = _internal_python_files()
	# Otherwise a mis-pointed ADDON_PATH (or the tree going missing) would
	# make this scan -- and the test -- pass vacuously, offenders == []
	# regardless. The floor is a small margin under the tree's current size,
	# not the exact count, so this doesn't need updating on every new module.
	assert internal_files, f"no .py files found under {ADDON_PATH}"
	assert len(internal_files) >= 20, (
		f"expected at least 20 add-on-internal .py files, found {len(internal_files)} -- "
		"ADDON_PATH may be wrong"
	)

	offenders = []
	for path in internal_files:
		tree = ast.parse(path.read_text(encoding="utf8"), filename=str(path))
		for node in ast.walk(tree):
			if isinstance(node, ast.Import):
				for alias in node.names:
					root = alias.name.split(".")[0]
					if root in TOP_LEVEL_INTERNAL_NAMES:
						offenders.append((path, root))
			elif isinstance(node, ast.ImportFrom):
				if node.level:  # relative import -- exactly what's required
					continue
				root = (node.module or "").split(".")[0]
				if root in TOP_LEVEL_INTERNAL_NAMES:
					offenders.append((path, root))
	assert offenders == [], (
		"add-on-internal top-level import(s) found -- these only resolve "
		"because tests put the add-on directory on sys.path, and fail under "
		f"NVDA: {offenders}"
	)

# Spec test 6 asks for "importing dialogs and the plugin module": a bare
# `import dialogs` cannot work standalone, because dialogs.py imports its
# siblings with relative imports (`from .lib.catalog import registry`,
# `from .lib.coseeing_auth import ...`, `from .settings_repository import
# ...`) -- a top-level `import dialogs` raises "attempted relative import
# with no known parent package". The add-on has to be loaded as a package
# instead, the same way tests/test_coseeing_auth_nvda.py's
# _load_nvda_plugin() loads __init__.py: via
# importlib.util.spec_from_file_location() with submodule_search_locations
# set to the add-on directory. __init__.py imports `.dialogs` itself, so one
# exec_module() of __init__.py pulls dialogs.py in transitively -- one import
# covers both modules, which is what this test needs.
PROBE = r"""
import sys
sys.path.insert(0, {tests!r})
sys.path.insert(0, {addon!r})

from lib import vendor
vendor.install(vendor.default_roots({package!r}))
vendor.install_stdlib_gapfill({package!r})

opened = []
import sys as _sys
def audit(event, args):
	if event == "open":
		opened.append(str(args[0]))
	if event == "ctypes.dlopen" or event == "ctypes.dlsym":
		opened.append("CTYPES:" + str(args[0]))
_sys.addaudithook(audit)

import nvda_stubs  # installs the NVDA module stand-ins
opened.clear()

import importlib.util

spec = importlib.util.spec_from_file_location(
	"wordbridge_import_purity_probe",
	{addon!r} + "/__init__.py",
	submodule_search_locations=[{addon!r}],
)
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)  # noqa: this is the import under test

# Normalise before filtering: an opened path on Windows uses "\\", and NVDA
# -- the only platform this add-on actually runs on -- is Windows-only, so a
# filter that only ever matches "setting/" would go quietly vacuous there.
setting_reads = [path for path in opened if "setting/" in path.replace("\\", "/")]
ctypes_calls = [path for path in opened if path.startswith("CTYPES:")]
print(repr(setting_reads))
print(repr(ctypes_calls))
"""


def test_importing_the_plugin_reads_no_setting_file_and_calls_no_windll(tmp_path):
	stub = tmp_path / "nvda_stubs.py"
	stub.write_text(NVDA_STUBS, encoding="utf8")
	script = PROBE.format(
		tests=str(tmp_path),
		addon=str(ADDON_PATH),
		package=str(ADDON_PATH / "package"),
	)
	result = subprocess.run(
		[sys.executable, "-c", script],
		capture_output=True,
		text=True,
		cwd=str(PROJECT_ROOT),
	)

	assert result.returncode == 0, result.stderr
	setting_reads, ctypes_calls = result.stdout.strip().splitlines()
	assert setting_reads == "[]", f"the plugin read setting files at import: {setting_reads}"
	assert ctypes_calls == "[]", f"the plugin called into ctypes at import: {ctypes_calls}"


NVDA_STUBS = '''
import builtins
import sys
from types import SimpleNamespace

addon_handler = SimpleNamespace(
	initTranslation=lambda: setattr(builtins, "_", lambda text: text)
)
sys.modules["addonHandler"] = addon_handler

sys.modules["config"] = SimpleNamespace(conf=SimpleNamespace(spec={}))
sys.modules["api"] = SimpleNamespace(
	getFocusObject=lambda: None,
	copyToClip=lambda text: None,
)
sys.modules["globalPluginHandler"] = SimpleNamespace(GlobalPlugin=object)
sys.modules["logHandler"] = SimpleNamespace(log=SimpleNamespace(
	warning=lambda *a, **k: None,
	info=lambda *a, **k: None,
	debug=lambda *a, **k: None,
	exception=lambda *a, **k: None,
))
sys.modules["nvwave"] = SimpleNamespace(playWaveFile=lambda *a, **k: None)
sys.modules["scriptHandler"] = SimpleNamespace(script=lambda **k: (lambda function: function))
sys.modules["textInfos"] = SimpleNamespace(POSITION_SELECTION=object())
sys.modules["tones"] = SimpleNamespace(beep=lambda *a: None)
sys.modules["ui"] = SimpleNamespace(message=lambda *a: None)
sys.modules["wx"] = SimpleNamespace(
	Choice=type("Choice", (), {}),
	TextCtrl=type("TextCtrl", (), {}),
	CheckBox=type("CheckBox", (), {}),
	Button=type("Button", (), {}),
	StaticText=type("StaticText", (), {}),
	StaticBoxSizer=type("StaticBoxSizer", (), {}),
	BoxSizer=type("BoxSizer", (), {}),
	Dialog=type("Dialog", (), {}),
	VERTICAL=0, HORIZONTAL=1, ALL=2, OK=3, CANCEL=4,
	TE_PASSWORD=5, TE_PROCESS_ENTER=6, TE_READONLY=7, TE_MULTILINE=8,
	EVT_CHOICE=object(), EVT_BUTTON=object(),
	ToolTip=lambda value: value, Size=lambda w, h: (w, h),
	CallAfter=lambda *a, **k: None, CallLater=lambda *a, **k: None,
)
sys.modules["gui"] = SimpleNamespace(
	settingsDialogs=SimpleNamespace(
		NVDASettingsDialog=type("D", (), {"categoryClasses": []}),
		SettingsPanel=type("SettingsPanel", (), {}),
		SettingsDialog=type("SettingsDialog", (), {}),
	),
	guiHelper=SimpleNamespace(BoxSizerHelper=type("BoxSizerHelper", (), {}), BORDER_FOR_DIALOGS=0),
	nvdaControls=SimpleNamespace(SelectOnFocusSpinCtrl=type("SelectOnFocusSpinCtrl", (), {})),
	mainFrame=SimpleNamespace(),
	contextHelp=SimpleNamespace(ContextHelpMixin=type("ContextHelpMixin", (), {})),
)
sys.modules["gui.settingsDialogs"] = sys.modules["gui"].settingsDialogs
sys.modules["gui.contextHelp"] = sys.modules["gui"].contextHelp
sys.modules["configobj.validate"] = SimpleNamespace(
	VdtValueTooBigError=ValueError, VdtValueTooSmallError=ValueError
)
'''


# Production-shaped: unlike PROBE above (and tests/conftest.py:17), the add-on
# directory itself is never put on sys.path here -- only the tmp_path stub
# directory is. That is exactly the gap that let settings_repository.py's
# absolute `from lib.catalog.selection import normalize_selection` (the
# Critical whole-branch finding) hide behind a green suite for four tasks: it
# only ever resolved because the add-on directory was importable as a bare
# top-level location. vendor.py is loaded directly by file path (it has no
# relative imports of its own) rather than via `from lib import vendor`,
# since a bare `import lib` is precisely what must NOT be required to load
# this plugin.
PRODUCTION_PROBE = r"""
import sys
sys.path.insert(0, {tests!r})

import importlib.util

_vendor_spec = importlib.util.spec_from_file_location(
	"wordbridge_vendor_probe", {addon!r} + "/lib/vendor.py"
)
vendor = importlib.util.module_from_spec(_vendor_spec)
sys.modules[_vendor_spec.name] = vendor
_vendor_spec.loader.exec_module(vendor)
vendor.install(vendor.default_roots({package!r}))
vendor.install_stdlib_gapfill({package!r})

import nvda_stubs  # installs the NVDA module stand-ins

spec = importlib.util.spec_from_file_location(
	"wordbridge_production_shape_probe",
	{addon!r} + "/__init__.py",
	submodule_search_locations=[{addon!r}],
)
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)  # noqa: this is the import under test
print("OK")
"""


def test_the_plugin_package_imports_with_the_addon_directory_off_sys_path(tmp_path):
	"""Reproduces production: under NVDA the add-on's own directory is never
	on sys.path -- only globalPlugins/ (its parent) is, and __init__.py loads
	as a submodule via submodule_search_locations, exactly as
	spec_from_file_location does here. With only the stub directory on
	sys.path, an absolute add-on-internal import (like the one this test
	guards against regressing) raises ModuleNotFoundError instead of quietly
	resolving the way it does when the add-on directory sits on sys.path, as
	it does for every other test in this suite via tests/conftest.py:17.
	"""
	stub = tmp_path / "nvda_stubs.py"
	stub.write_text(NVDA_STUBS, encoding="utf8")
	script = PRODUCTION_PROBE.format(
		tests=str(tmp_path),
		addon=str(ADDON_PATH),
		package=str(ADDON_PATH / "package"),
	)
	result = subprocess.run(
		[sys.executable, "-c", script],
		capture_output=True,
		text=True,
		cwd=str(PROJECT_ROOT),
	)

	assert result.returncode == 0, result.stderr
	assert result.stdout.strip() == "OK"
