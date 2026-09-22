import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"

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
