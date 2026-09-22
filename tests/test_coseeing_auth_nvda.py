from concurrent.futures import Future
import dataclasses
import importlib
import importlib.util
import ctypes
import json
from threading import Event, RLock, Thread, current_thread
from types import SimpleNamespace
from pathlib import Path
from urllib.parse import urlparse
import sys
import types
import pytest


class OAuthError(Exception):
	pass


class ClientClosedError(Exception):
	pass


class RestoreError(Exception):
	pass


class TokenUnavailableError(Exception):
	pass


class TokenValidationError(Exception):
	pass


_TEMPORARY_IMPORT_MODULES = {
	"addonHandler": types.ModuleType("addonHandler"),
	"_wb_vendor.authlib": types.ModuleType("_wb_vendor.authlib"),
	"_wb_vendor.authlib.integrations": types.ModuleType("_wb_vendor.authlib.integrations"),
	"_wb_vendor.authlib.integrations.base_client": types.ModuleType("_wb_vendor.authlib.integrations.base_client"),
	"_wb_vendor.authlib.integrations.base_client.errors": types.ModuleType(
		"_wb_vendor.authlib.integrations.base_client.errors"
	),
	"_wb_vendor.coseeing_auth": types.ModuleType("_wb_vendor.coseeing_auth"),
	"_wb_vendor.coseeing_auth.errors": types.ModuleType("_wb_vendor.coseeing_auth.errors"),
}
_MISSING_MODULE = object()
_ORIGINAL_IMPORT_MODULES = {
	name: sys.modules.get(name, _MISSING_MODULE)
	for name in _TEMPORARY_IMPORT_MODULES
}
_TEMPORARY_IMPORT_MODULES["addonHandler"].initTranslation = lambda: None
_TEMPORARY_IMPORT_MODULES["_wb_vendor.authlib.integrations.base_client.errors"].OAuthError = OAuthError
for error in (ClientClosedError, RestoreError, TokenUnavailableError, TokenValidationError):
	setattr(_TEMPORARY_IMPORT_MODULES["_wb_vendor.coseeing_auth.errors"], error.__name__, error)
sys.modules.update(_TEMPORARY_IMPORT_MODULES)

import lib.coseeing_auth as module
from coseeing_auth_helpers import FakeAuth
from lib.coseeing_auth import CoseeingAuthSession
from lib.coseeing import build_coseeing_headers

for _module_name, _original_module in _ORIGINAL_IMPORT_MODULES.items():
	if _original_module is _MISSING_MODULE:
		sys.modules.pop(_module_name, None)
	else:
		sys.modules[_module_name] = _original_module


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"
_STUB_UNAVAILABLE_REASON = "stub unavailable reason for test"


def _load_nvda_plugin(monkeypatch, settings, auth_calls, queued, *, auth_available=True, log_warnings=None):
	class Config(dict):
		def save(self):
			pass

	config = SimpleNamespace(conf=Config({"WordBridge": {"settings": settings}}))
	config.conf.spec = {}

	class AutoPropertyType(type):
		"""Faithful stand-in for NVDA's baseObject.AutoPropertyType.

		The real GlobalPlugin inherits AutoPropertyObject, whose metaclass
		turns every `_get_x`/`_set_x`/`_del_x` method in a class body into a
		property `x`. A plain stub base hides that entirely, which is how a
		`_set_latest_action` method shipped: under the real metaclass the
		`self.latest_action = ...` inside it recursed without bound and wedged
		NVDA during global plugin initialization, with no traceback.

		Only the naming rule is reproduced -- that is the part that bites.
		"""

		def __init__(cls, name, bases, namespace, **kwargs):
			super().__init__(name, bases, namespace, **kwargs)
			props = {n[5:] for n in namespace if n[0:5] in ("_get_", "_set_", "_del_")}
			for prop in props:
				getter = namespace.get(f"_get_{prop}")
				setter = namespace.get(f"_set_{prop}")
				deleter = namespace.get(f"_del_{prop}")
				if prop in namespace:
					raise TypeError(f"{prop} is already a class attribute")
				setattr(cls, prop, property(getter, setter, deleter))

	class ParentPlugin(metaclass=AutoPropertyType):
		initialized = 0
		terminated = 0

		def __init__(self, *args, **kwargs):
			self.__class__.initialized += 1

		def terminate(self, *args, **kwargs):
			self.__class__.terminated += 1

	class Choice:
		def __init__(self, *args, **kwargs):
			self.selection = 0

		def SetSelection(self, value):
			self.selection = value

		def GetSelection(self):
			return self.selection

	class Timer:
		"""Stand-in for what wx.CallLater returns: a handle with Stop()."""

		def __init__(self, delay_ms, callback, args):
			self.delay_ms = delay_ms
			self.callback = callback
			self.args = args
			self.stopped = False

		def Stop(self):
			self.stopped = True

		def fire(self):
			"""Deliver the timer the way wx's event loop would."""
			self.callback(*self.args)

	wx_choice = Choice
	wx_timer = Timer
	wx_timers = []

	def call_later(delay_ms, callback, *args):
		timer = wx_timer(delay_ms, callback, args)
		wx_timers.append(timer)
		return timer

	class Wx:
		CallAfter = staticmethod(lambda function, *args: queued.append((function, args)))
		CallLater = staticmethod(call_later)
		timers = wx_timers
		Choice = wx_choice
		TE_PASSWORD = 1
		TE_PROCESS_ENTER = 2
		TE_READONLY = 8
		VERTICAL = 3
		HORIZONTAL = 4
		ALL = 5
		EVT_CHOICE = object()
		EVT_BUTTON = object()
		OK = 6
		CANCEL = 7
		StaticText = type("StaticText", (), {})
		StaticBoxSizer = type("StaticBoxSizer", (), {})
		BoxSizer = type("BoxSizer", (), {})
		Dialog = type("Dialog", (), {})
		TextCtrl = type("TextCtrl", (), {})
		CheckBox = type("CheckBox", (), {})
		Button = type("Button", (), {})
		ToolTip = staticmethod(lambda value: value)
		Size = staticmethod(lambda width, height: (width, height))

	gui = SimpleNamespace(
		settingsDialogs=SimpleNamespace(
			NVDASettingsDialog=type(
				"NVDASettingsDialog",
				(),
				{"categoryClasses": []},
			)
		),
		guiHelper=SimpleNamespace(
			BoxSizerHelper=type("BoxSizerHelper", (), {}),
			BORDER_FOR_DIALOGS=0,
		),
		nvdaControls=SimpleNamespace(SelectOnFocusSpinCtrl=object),
		mainFrame=SimpleNamespace(),
		contextHelp=SimpleNamespace(ContextHelpMixin=type("ContextHelpMixin", (), {})),
	)
	monkeypatch.setitem(sys.modules, "config", config)
	monkeypatch.setitem(sys.modules, "wx", Wx)
	monkeypatch.setitem(sys.modules, "gui", gui)
	monkeypatch.setitem(sys.modules, "gui.settingsDialogs", SimpleNamespace(SettingsPanel=object))
	monkeypatch.setitem(sys.modules, "gui.contextHelp", SimpleNamespace(ContextHelpMixin=type("ContextHelpMixin", (), {})))
	monkeypatch.setitem(sys.modules, "globalPluginHandler", SimpleNamespace(GlobalPlugin=ParentPlugin))
	monkeypatch.setitem(sys.modules, "addonHandler", SimpleNamespace(initTranslation=lambda: None))
	monkeypatch.setitem(sys.modules, "api", SimpleNamespace())
	warning_sink = (lambda *args, **kwargs: log_warnings.append(args[0] if args else kwargs)) if log_warnings is not None else (lambda *args, **kwargs: None)
	monkeypatch.setitem(
		sys.modules,
		"logHandler",
		SimpleNamespace(log=SimpleNamespace(
			warning=warning_sink,
			info=lambda *args, **kwargs: None,
			debug=lambda *args, **kwargs: None,
			exception=lambda *args, **kwargs: None,
		)),
	)
	played = []
	monkeypatch.setitem(sys.modules, "nvwave", SimpleNamespace(
		playWaveFile=lambda *args, **kwargs: played.append((args, kwargs)),
		played=played,
	))
	monkeypatch.setitem(sys.modules, "scriptHandler", SimpleNamespace(script=lambda **kwargs: lambda function: function))
	monkeypatch.setitem(sys.modules, "textInfos", SimpleNamespace(POSITION_SELECTION=object()))
	beeps = []
	monkeypatch.setitem(sys.modules, "tones", SimpleNamespace(
		beep=lambda *args: beeps.append(args),
		beeps=beeps,
	))
	monkeypatch.setitem(sys.modules, "ui", SimpleNamespace(message=lambda *args: None))
	monkeypatch.setitem(sys.modules, "_wb_vendor.hanzidentifier", SimpleNamespace(has_chinese=lambda text: True))
	monkeypatch.setitem(sys.modules, "configobj.validate", SimpleNamespace(
		VdtValueTooBigError=ValueError,
		VdtValueTooSmallError=ValueError,
	))
	monkeypatch.setitem(sys.modules, "configobj", SimpleNamespace(validate=sys.modules["configobj.validate"]))
	# GlobalPlugin.__init__ now builds a catalog, which pulls in the real
	# lib.llm package (SUPPORTED_PROVIDERS) -- unlike lib.application.task_runner
	# below, that module is never stubbed away, so lib/llm/provider.py's own
	# `import requests` / `from requests.utils import urlparse` really execute.
	# A bare SimpleNamespace() has no `.utils`, so that import used to raise
	# "'requests' is not a package". `from package.module import name` always
	# goes through the import system for "package.module" -- a plain `.utils`
	# attribute on the fake `requests` object is not enough, sys.modules needs
	# a "requests.utils" entry too. urlparse is read-only data plumbing (no
	# network I/O), so wiring in the real one keeps this a fake network client
	# while letting the real import machinery resolve it; every test that
	# could otherwise reach the network still replaces `.get`/`.post` itself.
	fake_requests = SimpleNamespace(utils=SimpleNamespace(urlparse=urlparse))
	monkeypatch.setitem(sys.modules, "requests", fake_requests)
	monkeypatch.setitem(sys.modules, "requests.utils", fake_requests.utils)
	monkeypatch.setattr(
		ctypes,
		"windll",
		SimpleNamespace(kernel32=SimpleNamespace(GetUserDefaultUILanguage=lambda: 1033)),
		raising=False,
	)

	package_name = f"task4_wordbridge_{id(auth_calls)}"
	package = type(sys)(package_name)
	package.__path__ = [str(ADDON_PATH)]
	monkeypatch.setitem(sys.modules, package_name, package)
	auth_module = type(sys)(f"{package_name}.lib.coseeing_auth")
	auth_module.start_coseeing_auth = lambda channel, **kwargs: auth_calls.append(channel) if channel == "Coseeing" else None
	clean_future = Future()
	clean_future.set_result(None)
	auth_module.clean_coseeing_auth = lambda: clean_future
	auth_module.has_saved_coseeing_refresh_token = lambda: False
	auth_module.AUTH_AVAILABLE = auth_available
	auth_module.unavailable_reason = lambda: _STUB_UNAVAILABLE_REASON
	reset_future = Future()
	reset_future.set_result(None)
	auth_module.reset_coseeing_auth = lambda: auth_calls.append("reset") or reset_future
	auth_module.shutdown_coseeing_auth = lambda: auth_calls.append("shutdown")
	lib_package = type(sys)(f"{package_name}.lib")
	lib_package.__path__ = [str(ADDON_PATH / "lib")]
	monkeypatch.setitem(sys.modules, f"{package_name}.lib", lib_package)
	monkeypatch.setitem(sys.modules, auth_module.__name__, auth_module)
	monkeypatch.setitem(sys.modules, f"{package_name}.lib.coseeing", SimpleNamespace(build_coseeing_headers=build_coseeing_headers))
	monkeypatch.setitem(sys.modules, f"{package_name}.lib.decimalUtils", SimpleNamespace(decimal_to_str_0=str))
	monkeypatch.setitem(sys.modules, f"{package_name}.lib.tasks.typo.utils", SimpleNamespace(strings_diff=lambda *args: []))
	monkeypatch.setitem(sys.modules, f"{package_name}.lib.viewHTML", SimpleNamespace(text2template=lambda *args: None))
	monkeypatch.setitem(sys.modules, f"{package_name}.lib.application.task_runner", SimpleNamespace(run_typo_correction=lambda *args, **kwargs: None))
	dictionary_package = type(sys)(f"{package_name}.dictionary")
	dictionary_package.__path__ = [str(ADDON_PATH / "dictionary")]
	dictionary_package.WBW_DICTIONARY_PATH = "/tmp/wordbridge-test-dictionary"
	monkeypatch.setitem(sys.modules, dictionary_package.__name__, dictionary_package)
	monkeypatch.setitem(sys.modules, f"{package_name}.dictionary.dialog", SimpleNamespace(DictionaryEntryDialog=object))

	monkeypatch.setattr("builtins._", lambda text: text, raising=False)
	spec = importlib.util.spec_from_file_location(
		package_name,
		ADDON_PATH / "__init__.py",
		submodule_search_locations=[str(ADDON_PATH)],
	)
	# Spec test 8: this exec_module call is a real, unstubbed run of the real
	# __init__.py -- the only NVDA-side modules faked above are the ones this
	# helper builds stand-ins for; `.lib.vendor`, `.dialogs` and
	# `.configManager` are the genuine files on disk. Snapshotting immediately
	# around it and asserting the delta is what actually proves "leaves
	# sys.path unmodified and adds no global sys.modules key except
	# _wb_vendor and any category 1 registration" -- executing the file
	# without checking either only proves it did not raise.
	modules_before = set(sys.modules)
	path_before = list(sys.path)
	plugin = importlib.util.module_from_spec(spec)
	sys.modules[package_name] = plugin
	spec.loader.exec_module(plugin)
	plugin.dialogs = sys.modules[f"{package_name}.dialogs"]

	assert sys.path == path_before, "exec_module must never mutate sys.path"
	# The real pollution spec test 8 cares about is a category 2 top-level
	# name becoming globally importable (the whole reason this design exists);
	# it is not "no new sys.modules key at all" -- this minimal harness, unlike
	# a real NVDA process that has already warmed most of the stdlib by the
	# time an add-on loads, does not have e.g. `csv` pre-imported, and
	# __init__.py's ordinary `import csv` is not the pollution under test.
	from lib import vendor

	added = set(sys.modules) - modules_before
	leaked = added & vendor.ISOLATED
	assert not leaked, f"category 2 name(s) leaked as bare global sys.modules key(s): {sorted(leaked)}"

	# GlobalPlugin.__init__ now builds a catalog and a SettingsRepository
	# before anything else runs (registry.initialize() at __init__.py's
	# catalog line). Many tests below construct their plugin instance via
	# object.__new__(plugin.GlobalPlugin), deliberately bypassing __init__ so
	# they don't also start Coseeing auth or register the settings panel --
	# but correctTypo() and _make_progress_cue() now reach self.settings and
	# registry.current() regardless. Doing this once here, against the real
	# shipped setting/ tree, means callers just assign instance.settings /
	# instance.correctorTaskConfig from plugin.settings / plugin.correctorTaskConfig
	# instead of each reimplementing catalog bootstrap.
	plugin.catalog = plugin.load_catalog(
		plugin.BundledCatalogSource(str(ADDON_PATH / "setting")),
		runnable_providers=plugin.SUPPORTED_PROVIDERS,
	)
	plugin.registry.initialize(plugin.catalog)
	plugin.correctorTaskConfig = plugin.load_corrector_task_config(plugin.CORRECTOR_TASK_CONFIG_PATH)
	plugin.settings = plugin.SettingsRepository(config.conf["WordBridge"]["settings"], plugin.registry.current)

	return plugin, config, gui


def test_global_plugin_starts_normalized_coseeing_auth_and_guards_queued_callback(monkeypatch):
	auth_calls = []
	queued = []
	settings = {
		"corrector_config_id": "gemini-3.1-pro-preview&Google",
		"execution_channel": "Coseeing",
		"api_key": {},
	}
	plugin, config, gui = _load_nvda_plugin(monkeypatch, settings, auth_calls, queued)

	instance = plugin.GlobalPlugin()
	# The one thing this task's real __init__ must do that no test above
	# exercises: wire self.settings/self.correctorTaskConfig/self.catalog
	# onto the instance it constructs. Without this, deleting the line that
	# does it leaves the suite green while production correctTypo() raises
	# AttributeError the first time it runs -- see the fix report for the
	# mutation that proves it.
	assert isinstance(instance.settings, plugin.SettingsRepository)
	assert instance.correctorTaskConfig is not None
	assert instance.catalog is not None
	# __init__.py:195 sets this so correctTypo()'s degraded-catalog announcement
	# has a flag to guard -- `and` short-circuits, so dropping or reordering
	# that line stays green everywhere except here, and everywhere except a
	# degraded user's first correction (see fix-round-1 in task-7-report.md).
	assert instance._degraded_catalog_announced is False
	assert len(queued) == 1
	callback, args = queued.pop(0)
	callback(*args)
	assert auth_calls == []
	instance.terminate()
	assert auth_calls == ["shutdown"]

	settings["corrector_config_id"] = "deepseek-v4-flash&DeepSeek"
	instance = plugin.GlobalPlugin()
	callback, args = queued.pop(0)
	instance.terminate()
	callback(*args)
	assert auth_calls == ["shutdown", "shutdown"]

	instance = plugin.GlobalPlugin()
	callback, args = queued.pop(0)
	callback(*args)
	assert auth_calls == ["shutdown", "shutdown", "Coseeing"]
	instance.terminate()
	assert auth_calls == ["shutdown", "shutdown", "Coseeing", "shutdown"]
	assert gui.settingsDialogs.NVDASettingsDialog.categoryClasses == []
	assert config.conf["WordBridge"]["settings"]["execution_channel"] == "Coseeing"


_SHADOW_WARNING = "WordBridge: vendored packages not shadowed under their canonical names"


def _without_shadow_warning(warnings):
	"""Drop the shadow warning these tests always provoke.

	`install_shadowed()` finds no Windows runtime bundle on this host, so it
	stands down and `__init__.py` says so at load. That is correct behaviour
	off-Windows, and orthogonal to what the auth-reason tests below assert --
	but it is asserted in its own right by
	`test_plugin_load_warns_when_nothing_can_be_shadowed`, so filtering it here
	cannot hide its disappearance.
	"""
	return [warning for warning in warnings if _SHADOW_WARNING not in str(warning)]


def test_plugin_load_logs_the_unavailable_auth_reason(monkeypatch):
	"""Carried item (a)/(b): __init__.py must log coseeing_auth's unavailable
	reason at plugin load when AUTH_AVAILABLE is False, using only the reason
	string (never the raw exception or a traceback).
	"""
	auth_calls = []
	queued = []
	warnings = []
	settings = {
		"corrector_config_id": "gemini-3.1-pro-preview&Google",
		"execution_channel": "local",
		"api_key": {},
	}

	_load_nvda_plugin(
		monkeypatch, settings, auth_calls, queued,
		auth_available=False, log_warnings=warnings,
	)

	assert _without_shadow_warning(warnings) == [_STUB_UNAVAILABLE_REASON]


def test_plugin_load_does_not_log_when_auth_is_available(monkeypatch):
	auth_calls = []
	queued = []
	warnings = []
	settings = {
		"corrector_config_id": "gemini-3.1-pro-preview&Google",
		"execution_channel": "local",
		"api_key": {},
	}

	_load_nvda_plugin(
		monkeypatch, settings, auth_calls, queued,
		auth_available=True, log_warnings=warnings,
	)

	assert _without_shadow_warning(warnings) == []


def test_plugin_load_warns_when_nothing_can_be_shadowed(monkeypatch):
	"""The shadow standing down is what breaks Coseeing login, and it is
	otherwise silent -- the only later evidence is a TypeError deep inside
	PyJWT. Loading on a host with no runtime bundle must say so at load.
	"""
	warnings = []
	settings = {
		"corrector_config_id": "gemini-3.1-pro-preview&Google",
		"execution_channel": "local",
		"api_key": {},
	}

	_load_nvda_plugin(monkeypatch, settings, [], [], log_warnings=warnings)

	assert [w for w in warnings if _SHADOW_WARNING in str(w)] == [
		_SHADOW_WARNING + ": %s -- Coseeing authentication will not work on this runtime",
	]


@pytest.mark.parametrize("payload", [
	# Each of these parses as JSON but isn't the expected mapping shape, so
	# raw_config["template_name"] (configManager.py) raises TypeError, not
	# one of OSError/ValueError/KeyError -- the exact gap that let a corrupt
	# task config take plugin construction down.
	"[1, 2]",
	'"hello"',
	"123",
	"null",
])
def test_corrupt_task_config_type_error_falls_back_and_notifies(monkeypatch, tmp_path, payload):
	settings = {
		"corrector_config_id": "gemini-3.1-pro-preview&Google",
		"execution_channel": "local",
		"api_key": {},
	}
	queued = []
	plugin, _config, _gui = _load_nvda_plugin(monkeypatch, settings, [], queued)
	messages = []
	monkeypatch.setattr(plugin, "ui", SimpleNamespace(message=messages.append))
	corrupt = tmp_path / "corrector.json"
	corrupt.write_text(payload, encoding="utf8")
	monkeypatch.setattr(plugin, "CORRECTOR_TASK_CONFIG_PATH", str(corrupt))
	instance = object.__new__(plugin.GlobalPlugin)
	instance._shutdown = Event()

	task_config = instance._load_corrector_task_config()

	assert task_config.template_name == {"standard": "Standard_v1.json", "lite": "Lite_v1.json"}
	assert task_config.optional_guidance_enable == {
		"keep_non_chinese_char": True, "no_explanation": True,
	}
	# The notification is deferred (self._notify() -> wx.CallAfter()), the
	# same way _start_coseeing_auth is -- ui.message() is never called
	# synchronously, mid-construction.
	assert messages == []
	assert len(queued) == 1
	callback, args = queued.pop()
	callback(*args)
	assert messages == [
		"The bundled correction settings file is damaged; WordBridge is using its built-in defaults."
	]


def test_corrupt_task_config_key_error_falls_back_and_notifies(monkeypatch, tmp_path):
	# A mapping missing a required key raises KeyError, not TypeError --
	# both must be caught; see the parametrized TypeError test above.
	settings = {
		"corrector_config_id": "gemini-3.1-pro-preview&Google",
		"execution_channel": "local",
		"api_key": {},
	}
	queued = []
	plugin, _config, _gui = _load_nvda_plugin(monkeypatch, settings, [], queued)
	messages = []
	monkeypatch.setattr(plugin, "ui", SimpleNamespace(message=messages.append))
	corrupt = tmp_path / "corrector.json"
	corrupt.write_text(json.dumps({"template_name": {}}), encoding="utf8")
	monkeypatch.setattr(plugin, "CORRECTOR_TASK_CONFIG_PATH", str(corrupt))
	instance = object.__new__(plugin.GlobalPlugin)
	instance._shutdown = Event()

	task_config = instance._load_corrector_task_config()

	assert task_config.template_name == {"standard": "Standard_v1.json", "lite": "Lite_v1.json"}
	assert task_config.optional_guidance_enable == {
		"keep_non_chinese_char": True, "no_explanation": True,
	}
	callback, args = queued.pop()
	callback(*args)
	assert messages == [
		"The bundled correction settings file is damaged; WordBridge is using its built-in defaults."
	]


def test_task_config_fallback_matches_the_shipped_corrector_json(monkeypatch, tmp_path):
	"""Nothing else keeps _load_corrector_task_config's hard-coded fallback in
	sync with setting/task/corrector.json -- pin that they still agree, so an
	edit to the shipped file that isn't mirrored here is caught.
	"""
	settings = {
		"corrector_config_id": "gemini-3.1-pro-preview&Google",
		"execution_channel": "local",
		"api_key": {},
	}
	plugin, _config, _gui = _load_nvda_plugin(monkeypatch, settings, [], [])
	corrupt = tmp_path / "corrector.json"
	corrupt.write_text("null", encoding="utf8")
	monkeypatch.setattr(plugin, "CORRECTOR_TASK_CONFIG_PATH", str(corrupt))
	instance = object.__new__(plugin.GlobalPlugin)
	instance._shutdown = Event()

	fallback = instance._load_corrector_task_config()

	shipped = json.loads((ADDON_PATH / "setting" / "task" / "corrector.json").read_text(encoding="utf8"))
	assert fallback.template_name == shipped["template_name"]
	assert fallback.optional_guidance_enable == shipped["optional_guidance_enable"]


def test_real_init_falls_back_to_shipped_defaults_and_notifies_on_a_corrupt_task_config(monkeypatch, tmp_path):
	"""Pins the self._shutdown reorder in GlobalPlugin.__init__.

	Every other fallback test above constructs its instance via
	object.__new__(plugin.GlobalPlugin) and sets instance._shutdown by hand,
	so none of them exercise the fallback through the real __init__ -- which
	is exactly what moving self._shutdown = threading.Event() to the top of
	__init__ exists to make safe (self._notify()/self._run_on_ui() both read
	self._shutdown, and _load_corrector_task_config() -- which can call
	self._notify() -- now runs before anything else in __init__ that used to
	set self._shutdown). This test goes through plugin.GlobalPlugin() itself,
	not object.__new__, so it would fail with AttributeError if that ordering
	regressed.
	"""
	settings = {
		"corrector_config_id": "gemini-3.1-pro-preview&Google",
		"execution_channel": "local",
		"api_key": {},
	}
	queued = []
	plugin, _config, _gui = _load_nvda_plugin(monkeypatch, settings, [], queued)
	messages = []
	monkeypatch.setattr(plugin, "ui", SimpleNamespace(message=messages.append))
	corrupt = tmp_path / "corrector.json"
	corrupt.write_text("null", encoding="utf8")
	monkeypatch.setattr(plugin, "CORRECTOR_TASK_CONFIG_PATH", str(corrupt))

	instance = plugin.GlobalPlugin()

	assert instance.correctorTaskConfig.template_name == {
		"standard": "Standard_v1.json", "lite": "Lite_v1.json",
	}
	assert instance.correctorTaskConfig.optional_guidance_enable == {
		"keep_non_chinese_char": True, "no_explanation": True,
	}
	# _load_corrector_task_config() -- and the wx.CallAfter() its deferred
	# notification schedules -- runs before wx.CallAfter(self._start_coseeing_auth,
	# ...) later in __init__, so the notification is the first of the two
	# callbacks queued during construction.
	assert len(queued) == 2
	callback, args = queued.pop(0)
	callback(*args)
	assert messages == [
		"The bundled correction settings file is damaged; WordBridge is using its built-in defaults."
	]
	instance.terminate()


def test_settings_save_preserves_coseeing_refresh_token_and_starts_selected_channel(monkeypatch):
	auth_calls = []
	queued = []
	settings = {
		"corrector_config_id": "old&OpenAI",
		"execution_channel": "local",
		"api_key": {"Coseeing": "saved-refresh", "OpenAI": "old-key"},
		"language": "zh_traditional",
		"typo_correction_mode": "standard",
		"max_char_count": 512,
		"auto_display_report": False,
		"customized_words_enable": True,
		"sound_effects_enable": True,
		"coseeing_username": "legacy-user",
		"coseeing_password": "legacy-password",
	}
	plugin, config, _ = _load_nvda_plugin(monkeypatch, settings, auth_calls, queued)
	dialogs = plugin.dialogs

	class Control:
		def __init__(self, value):
			self.value = value

		def GetSelection(self):
			return self.value

		def GetValue(self):
			return self.value

	class FakeSelection:
		# Stands in for SelectionState: onSave() only ever writes the two
		# index attributes and reads current_item() back, so a fixed item
		# (deliberately not what providerList/modelList's indices would
		# resolve to in the real catalog) is what makes this deterministic
		# without needing a real catalog/registry here.
		provider_group_index = 0
		model_index = 0

		def current_item(self):
			return SimpleNamespace(corrector_config_id="deepseek&DeepSeek", execution_channel="Coseeing")

	panel = object.__new__(dialogs.LLMSettingsPanel)
	panel.selection = FakeSelection()
	panel.settings = dialogs.SettingsRepository(settings, lambda: None)
	panel.providerList = Control(0)
	panel.modelList = Control(0)
	panel.languageList = Control(0)
	panel.typoCorrectionModeList = Control(0)
	panel.maxCharCountSpinCtrl = Control(512)
	panel.autoDisplayReportEnable = Control(False)
	panel.customizedWordEnable = Control(True)
	panel.soundEffectsEnable = Control(True)
	panel.accountTextCtrlMap = {
		"OpenAI": Control("updated-key"),
	}

	panel.onSave()
	assert config.conf["WordBridge"]["settings"]["execution_channel"] == "Coseeing"
	assert settings["api_key"] == {"Coseeing": "saved-refresh", "OpenAI": "updated-key"}
	assert settings["coseeing_username"] == "legacy-user"
	assert settings["coseeing_password"] == "legacy-password"
	assert len(queued) == 1
	callback, args = queued.pop()
	assert auth_calls == []
	callback(*args)
	assert auth_calls == ["Coseeing"]

	settings["api_key"].pop("Coseeing")
	panel.onSave()
	assert "Coseeing" not in settings["api_key"]


def test_settings_panel_uses_clean_button_without_legacy_credential_controls(monkeypatch):
	auth_calls = []
	queued = []
	settings = {
		"corrector_config_id": "deepseek-v4-flash&DeepSeek",
		"execution_channel": "Coseeing",
		"api_key": {"Coseeing": "refresh-token"},
		"language": "zh_traditional",
		"typo_correction_mode": "standard",
		"max_char_count": 512,
		"auto_display_report": False,
		"customized_words_enable": True,
		"sound_effects_enable": True,
		"coseeing_username": "legacy-user",
		"coseeing_password": "legacy-password",
	}
	plugin, config, gui = _load_nvda_plugin(monkeypatch, settings, auth_calls, queued)
	dialogs = plugin.dialogs

	class Widget:
		def __init__(self, *args, value="", label="", **kwargs):
			self.value = value
			self.label = label
			self.enabled = True
			self.bindings = {}

		def Enable(self, enabled=True):
			self.enabled = enabled

		def Disable(self):
			self.enabled = False

		def IsEnabled(self):
			return self.enabled

		def SetSelection(self, value):
			self.value = value

		def GetSelection(self):
			return self.value

		def SetValue(self, value):
			self.value = value

		def GetValue(self):
			return self.value

		def SetToolTip(self, value):
			pass

		def Bind(self, event, callback):
			self.bindings[event] = callback

	class Sizer:
		def Show(self, item, recursive=True):
			pass

		def Hide(self, item, recursive=True):
			pass

	class Helper:
		calls = []

		def __init__(self, owner, sizer=None, **kwargs):
			self.sizer = sizer or Sizer()

		def addLabeledControl(self, label, control_type, **kwargs):
			self.calls.append((label, control_type, kwargs))
			return control_type(None, **kwargs)

		def addItem(self, item):
			return item

	monkeypatch.setattr(gui.guiHelper, "BoxSizerHelper", Helper)
	monkeypatch.setattr(plugin.wx, "Choice", Widget)
	monkeypatch.setattr(plugin.wx, "TextCtrl", Widget)
	monkeypatch.setattr(plugin.wx, "CheckBox", Widget)
	monkeypatch.setattr(plugin.wx, "Button", Widget)
	monkeypatch.setattr(plugin.wx, "StaticText", Widget)
	monkeypatch.setattr(plugin.wx, "StaticBoxSizer", lambda *args, **kwargs: Sizer())
	monkeypatch.setattr(gui.nvdaControls, "SelectOnFocusSpinCtrl", Widget)
	config.conf.getConfigValidation = lambda path: SimpleNamespace(kwargs={"min": 256, "max": 4096})
	monkeypatch.setattr(dialogs, "has_saved_coseeing_refresh_token", lambda: False)
	panel = object.__new__(dialogs.LLMSettingsPanel)
	panel.scaleSize = lambda value: value
	panel._refreshAccountInfo = lambda: None
	panel.makeSettings(Sizer())

	assert "Coseeing" in panel.accountGroupSizerMap
	assert panel.coseeingCleanButton.label == "clean"
	assert panel.coseeingCleanButton.IsEnabled() is False
	assert panel.coseeingCleanButton.bindings[plugin.wx.EVT_BUTTON] == panel.onCleanCoseeingAuth
	assert "Coseeing" not in panel.accountTextCtrlMap
	assert "Coseeing" not in {
		endpoint for endpoint, control in panel.accountTextCtrlMap.items()
		if isinstance(control, plugin.wx.TextCtrl)
	}

	monkeypatch.setattr(dialogs, "has_saved_coseeing_refresh_token", lambda: True)
	panel = object.__new__(dialogs.LLMSettingsPanel)
	panel.scaleSize = lambda value: value
	panel._refreshAccountInfo = lambda: None
	panel.makeSettings(Sizer())
	assert panel.coseeingCleanButton.IsEnabled() is True

	settings["api_key"].pop("Coseeing")
	panel = object.__new__(dialogs.LLMSettingsPanel)
	panel.scaleSize = lambda value: value
	panel._refreshAccountInfo = lambda: None
	panel.makeSettings(Sizer())
	assert "Coseeing" not in settings["api_key"]


def _panel_settings(**overrides):
	settings = {
		"corrector_config_id": "",
		"execution_channel": "",
		"api_key": {},
		"language": "zh_traditional",
		"typo_correction_mode": "standard",
		"max_char_count": 512,
		"auto_display_report": False,
		"customized_words_enable": True,
		"sound_effects_enable": True,
	}
	settings.update(overrides)
	return settings


def _install_settings_panel_widget_stubs(monkeypatch, plugin, gui, config):
	"""Wires the same wx/gui.guiHelper stand-ins
	test_settings_panel_uses_clean_button_without_legacy_credential_controls
	uses, so makeSettings() can run headless, and captures what it renders.

	Returns (helper_calls, static_box_captions, Sizer): helper_calls is every
	settingsSizerHelper.addLabeledControl() call as (label, control_type,
	kwargs) -- kwargs["choices"] is what a wx.Choice was built with -- and
	static_box_captions is the label given to each wx.StaticBoxSizer(...), in
	provider_groups order.
	"""
	class Widget:
		def __init__(self, *args, value="", label="", **kwargs):
			self.value = value
			self.label = label
			self.enabled = True
			self.bindings = {}
			self.items = kwargs.get("choices", [])

		def Enable(self, enabled=True):
			self.enabled = enabled

		def Disable(self):
			self.enabled = False

		def IsEnabled(self):
			return self.enabled

		def SetSelection(self, value):
			self.value = value

		def GetSelection(self):
			return self.value

		def SetValue(self, value):
			self.value = value

		def GetValue(self):
			return self.value

		def SetToolTip(self, value):
			pass

		def Bind(self, event, callback):
			self.bindings[event] = callback

		def SetItems(self, items):
			self.items = items

	class Sizer:
		def Show(self, item, recursive=True):
			pass

		def Hide(self, item, recursive=True):
			pass

	helper_calls = []

	class Helper:
		def __init__(self, owner, sizer=None, **kwargs):
			self.sizer = sizer or Sizer()

		def addLabeledControl(self, label, control_type, **kwargs):
			helper_calls.append((label, control_type, kwargs))
			return control_type(None, **kwargs)

		def addItem(self, item):
			return item

	static_box_captions = []

	def static_box_sizer(orientation, parent, label=""):
		static_box_captions.append(label)
		return Sizer()

	monkeypatch.setattr(gui.guiHelper, "BoxSizerHelper", Helper)
	monkeypatch.setattr(plugin.wx, "Choice", Widget)
	monkeypatch.setattr(plugin.wx, "TextCtrl", Widget)
	monkeypatch.setattr(plugin.wx, "CheckBox", Widget)
	monkeypatch.setattr(plugin.wx, "Button", Widget)
	monkeypatch.setattr(plugin.wx, "StaticText", Widget)
	monkeypatch.setattr(plugin.wx, "StaticBoxSizer", static_box_sizer)
	monkeypatch.setattr(gui.nvdaControls, "SelectOnFocusSpinCtrl", Widget)
	config.conf.getConfigValidation = lambda path: SimpleNamespace(kwargs={"min": 256, "max": 4096})
	return helper_calls, static_box_captions, Sizer


def _make_panel(monkeypatch, dialogs, Sizer):
	panel = object.__new__(dialogs.LLMSettingsPanel)
	panel.scaleSize = lambda value: value
	panel._refreshAccountInfo = lambda: None
	panel.makeSettings(Sizer())
	return panel


def test_settings_panel_summary_line_appears_only_when_the_catalog_has_issues(monkeypatch):
	"""Spec: "the settings panel shows a summary line" (Validation and
	degradation -> Visibility) -- the one of the spec's three issue-visibility
	channels dialogs.py never implemented. catalog.degraded is only True on
	the Empty rung, so without this there was no user-visible surfacing at
	all on rung 2 ("Degraded: some entries dropped; the rest work").
	"""
	auth_calls = []
	queued = []
	settings = _panel_settings()
	plugin, config, gui = _load_nvda_plugin(monkeypatch, settings, auth_calls, queued)
	dialogs = plugin.dialogs
	helper_calls, static_box_captions, Sizer = _install_settings_panel_widget_stubs(monkeypatch, plugin, gui, config)
	monkeypatch.setattr(dialogs, "has_saved_coseeing_refresh_token", lambda: False)

	clean_catalog = dataclasses.replace(plugin.catalog, issues=())
	monkeypatch.setattr(dialogs.registry, "current", lambda: clean_catalog)
	panel = _make_panel(monkeypatch, dialogs, Sizer)
	assert panel.catalogIssuesText is None

	from lib.catalog.model import CatalogIssue

	issue = CatalogIssue("unreadable_file", "ai/Google-broken.json", "ValueError: boom")
	catalog_with_issue = dataclasses.replace(plugin.catalog, issues=(issue,))
	monkeypatch.setattr(dialogs.registry, "current", lambda: catalog_with_issue)
	panel = _make_panel(monkeypatch, dialogs, Sizer)
	assert panel.catalogIssuesText is not None
	assert "1" in panel.catalogIssuesText.label


def test_settings_panel_summary_line_is_silent_for_the_shipped_healthy_catalog(monkeypatch):
	"""Regression guard: the shipped, fully healthy catalog always carries
	exactly one "unreferenced_provider" issue (providers.OpenRouter -- pinned
	by tests/test_catalog_bundled.py's
	test_the_shipped_data_produces_only_the_known_lint_issue), because the
	spec's own validation table classifies an unreferenced provider as
	"Legal. Lint-level issue only." Nothing failed to load and all 15 shipped
	entries are selectable, so on every clean install the panel must render
	no line at all -- rendering one here would be a permanent false alarm a
	blind user hears every time they open settings.
	"""
	auth_calls = []
	queued = []
	settings = _panel_settings()
	plugin, config, gui = _load_nvda_plugin(monkeypatch, settings, auth_calls, queued)
	dialogs = plugin.dialogs
	helper_calls, static_box_captions, Sizer = _install_settings_panel_widget_stubs(monkeypatch, plugin, gui, config)
	monkeypatch.setattr(dialogs, "has_saved_coseeing_refresh_token", lambda: False)

	# The real, unmodified shipped catalog -- not a fabricated fixture -- is
	# the regression surface. If it stopped carrying the lint issue this
	# assertion (not the one below) would fail, and the test would no longer
	# be exercising the exclusion at all.
	assert plugin.catalog.issues, "fixture no longer carries the shipped lint issue -- test would be vacuous"
	assert all(issue.code == "unreferenced_provider" for issue in plugin.catalog.issues)

	panel = _make_panel(monkeypatch, dialogs, Sizer)
	assert panel.catalogIssuesText is None


def test_settings_panel_summary_line_ignores_lint_issues_and_uses_correct_grammar(monkeypatch):
	"""Lint issues (unreferenced_provider) must not inflate the dropped-entry
	count, and the line must use the singular message form for exactly one
	dropped issue and the plural form for more than one -- NVDA reads this
	aloud, so "1 catalog entries" is a grammar defect a blind user hears
	every time.
	"""
	auth_calls = []
	queued = []
	settings = _panel_settings()
	plugin, config, gui = _load_nvda_plugin(monkeypatch, settings, auth_calls, queued)
	dialogs = plugin.dialogs
	helper_calls, static_box_captions, Sizer = _install_settings_panel_widget_stubs(monkeypatch, plugin, gui, config)
	monkeypatch.setattr(dialogs, "has_saved_coseeing_refresh_token", lambda: False)

	from lib.catalog.model import CatalogIssue

	lint_issue = CatalogIssue("unreferenced_provider", "providers.OpenRouter", "no models entry names this provider")
	first_dropped = CatalogIssue("unreadable_file", "ai/Google-broken.json", "ValueError: boom")
	second_dropped = CatalogIssue("duplicate_entry", "models[3]", "'gpt&OpenAI' already defined")

	one_dropped_catalog = dataclasses.replace(plugin.catalog, issues=(lint_issue, first_dropped))
	monkeypatch.setattr(dialogs.registry, "current", lambda: one_dropped_catalog)
	panel = _make_panel(monkeypatch, dialogs, Sizer)
	assert panel.catalogIssuesText is not None
	assert panel.catalogIssuesText.label == "1 catalog entry could not be loaded; see the NVDA log for details."

	two_dropped_catalog = dataclasses.replace(
		plugin.catalog, issues=(lint_issue, first_dropped, second_dropped)
	)
	monkeypatch.setattr(dialogs.registry, "current", lambda: two_dropped_catalog)
	panel = _make_panel(monkeypatch, dialogs, Sizer)
	assert panel.catalogIssuesText is not None
	assert panel.catalogIssuesText.label == "2 catalog entries could not be loaded; see the NVDA log for details."


def test_settings_panel_renders_provider_group_captions_through_their_catalog_labels(monkeypatch):
	"""Acceptance 6 ("no Python change, including no label change") is false
	for providers unless the panel actually reads ProviderEntry.label: before
	this fix dialogs.py rendered the raw provider *key* everywhere -- the
	wx.Choice items and every account box's caption -- so a remote payload
	changing a provider's display name would never show up.
	"""
	auth_calls = []
	queued = []
	settings = _panel_settings()
	plugin, config, gui = _load_nvda_plugin(monkeypatch, settings, auth_calls, queued)
	dialogs = plugin.dialogs
	helper_calls, static_box_captions, Sizer = _install_settings_panel_widget_stubs(monkeypatch, plugin, gui, config)
	monkeypatch.setattr(dialogs, "has_saved_coseeing_refresh_token", lambda: False)

	original = plugin.catalog
	openai_entry = original.get_provider("OpenAI")
	assert openai_entry is not None
	relabeled_providers = dict(original.providers)
	relabeled_providers["OpenAI"] = dataclasses.replace(openai_entry, label="OpenAI Displayed")
	relabeled_catalog = dataclasses.replace(original, providers=relabeled_providers)
	monkeypatch.setattr(dialogs.registry, "current", lambda: relabeled_catalog)

	_make_panel(monkeypatch, dialogs, Sizer)

	provider_call = next(call for call in helper_calls if call[0] == "Service Provider:")
	choices = provider_call[2]["choices"]
	assert "OpenAI Displayed" in choices
	assert "OpenAI" not in choices
	assert any(caption.startswith("OpenAI Displayed ") for caption in static_box_captions)
	# Coseeing has no ProviderEntry (by design) -- its caption must still fall
	# back to the raw group name rather than breaking.
	assert any(caption.startswith("Coseeing ") for caption in static_box_captions)


def test_the_sentinel_model_label_is_rendered_through_the_translation_map(monkeypatch):
	"""I3: SENTINEL_LABEL ("Coseeing default") ships untranslated from
	lib/catalog (spec decision 9 forbids lib/catalog from reaching _()), and
	it is the everyday default selection on every fresh install (spec
	decision 5) -- the most user-visible string in the batch for a zh-only,
	blind-user product. The panel must render it through
	dialogs.MODEL_LABEL_TRANSLATIONS instead of the raw catalog label.

	The fake catalog below gives the sentinel coseeing entry a deliberately
	different raw label, so a rendered "Coseeing default" can only have come
	from the translation map -- never from entry.label passing through
	untouched, which is what every *other* model/coseeing label must still do.
	"""
	auth_calls = []
	queued = []
	settings = _panel_settings()
	plugin, config, gui = _load_nvda_plugin(monkeypatch, settings, auth_calls, queued)
	dialogs = plugin.dialogs
	helper_calls, static_box_captions, Sizer = _install_settings_panel_widget_stubs(monkeypatch, plugin, gui, config)
	monkeypatch.setattr(dialogs, "has_saved_coseeing_refresh_token", lambda: False)

	original = plugin.catalog
	other_coseeings = tuple(
		dataclasses.replace(entry, label="RAW SENTINEL LABEL FROM CATALOG")
		if entry.corrector_config_id == dialogs.SENTINEL_ID else entry
		for entry in original.coseeings
	)
	assert other_coseeings != original.coseeings, "fixture did not find the sentinel entry"
	catalog = dataclasses.replace(original, coseeings=other_coseeings)
	monkeypatch.setattr(dialogs.registry, "current", lambda: catalog)

	_make_panel(monkeypatch, dialogs, Sizer)

	model_call = next(call for call in helper_calls if call[0] == "Large Language Model:")
	choices = model_call[2]["choices"]
	assert dialogs.MODEL_LABEL_TRANSLATIONS[dialogs.SENTINEL_ID] in choices
	assert "RAW SENTINEL LABEL FROM CATALOG" not in choices
	# Every other Coseeing-offered model's label must still pass through
	# untouched -- only the sentinel is mapped.
	untranslated_labels = {
		entry.label for entry in original.coseeings
		if entry.corrector_config_id != dialogs.SENTINEL_ID
	}
	assert untranslated_labels, "fixture needs at least one non-sentinel Coseeing entry"
	assert untranslated_labels <= set(choices)


def test_refreshing_the_model_choice_still_renders_the_sentinel_through_the_translation_map(monkeypatch):
	"""Guards dialogs.py:256 (_refreshModelChoice, called from
	onChangeProviderChoice whenever the user switches provider groups):
	nothing in this suite referenced it before this test, so reverting that
	one call site from _display_labels back to catalog.labels_for would go
	undetected -- the sentinel would render translated when the panel first
	opens (makeSettings uses _display_labels directly) and then revert to
	the raw catalog label the moment the user changes provider group and
	switches back to Coseeing.

	Uses the same relabelled-sentinel fixture as
	test_the_sentinel_model_label_is_rendered_through_the_translation_map, so
	a rendered translated label can only have come from the translation map,
	never from entry.label passing through untouched.
	"""
	auth_calls = []
	queued = []
	settings = _panel_settings()
	plugin, config, gui = _load_nvda_plugin(monkeypatch, settings, auth_calls, queued)
	dialogs = plugin.dialogs
	helper_calls, static_box_captions, Sizer = _install_settings_panel_widget_stubs(monkeypatch, plugin, gui, config)
	monkeypatch.setattr(dialogs, "has_saved_coseeing_refresh_token", lambda: False)

	original = plugin.catalog
	other_coseeings = tuple(
		dataclasses.replace(entry, label="RAW SENTINEL LABEL FROM CATALOG")
		if entry.corrector_config_id == dialogs.SENTINEL_ID else entry
		for entry in original.coseeings
	)
	assert other_coseeings != original.coseeings, "fixture did not find the sentinel entry"
	catalog = dataclasses.replace(original, coseeings=other_coseeings)
	monkeypatch.setattr(dialogs.registry, "current", lambda: catalog)

	panel = _make_panel(monkeypatch, dialogs, Sizer)

	coseeing_index = catalog.provider_groups.index("Coseeing")
	panel.selection.choose_provider_group(coseeing_index)

	panel._refreshModelChoice()

	assert dialogs.MODEL_LABEL_TRANSLATIONS[dialogs.SENTINEL_ID] in panel.modelList.items
	assert "RAW SENTINEL LABEL FROM CATALOG" not in panel.modelList.items


def test_nvda_module_setup_leaves_real_bundle_exports_importable(monkeypatch):
	"""The real, unmodified package/coseeing_auth still imports and exports what
	it should -- resolved through the sandbox, not through package/ sitting on
	sys.path (which this task removes).
	"""
	cached_bundle = sys.modules.get("_wb_vendor.coseeing_auth")
	if cached_bundle is not None:
		assert Path(cached_bundle.__file__).resolve().is_relative_to(ADDON_PATH / "package")
	authlib = types.ModuleType("_wb_vendor.authlib")
	oauth2 = types.ModuleType("_wb_vendor.authlib.oauth2")
	rfc6749 = types.ModuleType("_wb_vendor.authlib.oauth2.rfc6749")
	errors = types.ModuleType("_wb_vendor.authlib.oauth2.rfc6749.errors")
	integrations = types.ModuleType("_wb_vendor.authlib.integrations")
	requests_client = types.ModuleType("_wb_vendor.authlib.integrations.requests_client")

	class OAuth2Error(Exception):
		pass

	class MismatchingStateException(OAuth2Error):
		pass

	class OAuth2Session:
		pass

	errors.OAuth2Error = OAuth2Error
	errors.MismatchingStateException = MismatchingStateException
	requests_client.OAuth2Session = OAuth2Session
	for dependency in (authlib, oauth2, rfc6749, errors, integrations, requests_client):
		monkeypatch.setitem(sys.modules, dependency.__name__, dependency)
	monkeypatch.setitem(sys.modules, "_wb_vendor.jwt", types.ModuleType("_wb_vendor.jwt"))

	bundle = importlib.import_module("_wb_vendor.coseeing_auth")
	assert Path(bundle.__file__).resolve().is_relative_to(ADDON_PATH / "package")
	assert callable(bundle.WindowsCredentialStore)


def test_clean_button_disables_on_success_and_reenables_on_failure(monkeypatch):
	auth_calls = []
	queued = []
	settings = {
		"corrector_config_id": "deepseek-v4-flash&DeepSeek",
		"execution_channel": "Coseeing",
		"api_key": {},
	}
	plugin, _config, _gui = _load_nvda_plugin(monkeypatch, settings, auth_calls, queued)
	dialogs = plugin.dialogs

	class Button:
		def __init__(self):
			self.enabled = True

		def Enable(self, enabled=True):
			self.enabled = enabled

		def Disable(self):
			self.enabled = False

		def IsEnabled(self):
			return self.enabled

	panel = object.__new__(dialogs.LLMSettingsPanel)
	panel.coseeingCleanButton = Button()
	monkeypatch.setattr(dialogs, "has_saved_coseeing_refresh_token", lambda: True)
	pending = Future()
	monkeypatch.setattr(dialogs, "clean_coseeing_auth", lambda: pending)
	panel.onCleanCoseeingAuth(None)
	assert panel.coseeingCleanButton.IsEnabled() is False
	pending.set_exception(RuntimeError("sanitized"))
	callback, args = queued.pop()
	callback(*args)
	assert panel.coseeingCleanButton.IsEnabled() is True

	pending = Future()
	monkeypatch.setattr(dialogs, "clean_coseeing_auth", lambda: pending)
	panel.onCleanCoseeingAuth(None)
	pending.set_result(None)
	callback, args = queued.pop()
	callback(*args)
	assert panel.coseeingCleanButton.IsEnabled() is False


def test_clean_button_stays_disabled_when_cleanup_fails_after_native_logout(monkeypatch):
	auth_calls = []
	queued = []
	settings = {
		"corrector_config_id": "deepseek-v4-flash&DeepSeek",
		"execution_channel": "Coseeing",
		"api_key": {},
	}
	plugin, _config, _gui = _load_nvda_plugin(monkeypatch, settings, auth_calls, queued)
	dialogs = plugin.dialogs

	class Button:
		def __init__(self):
			self.enabled = True

		def Enable(self, enabled=True):
			self.enabled = enabled

		def Disable(self):
			self.enabled = False

		def IsEnabled(self):
			return self.enabled

	logout = Future()
	cleanup = Future()
	class Session:
		def logout_local(self):
			return logout

	adapter = SimpleNamespace(
		notify_clean_completion=lambda done: None,
		notify_completion=lambda done: None,
	)
	monkeypatch.setattr(module, "_get_singleton_pair", lambda: (Session(), adapter))
	monkeypatch.setattr(module, "_reset_captured_coseeing_auth", lambda session, captured: cleanup)
	monkeypatch.setattr(dialogs, "clean_coseeing_auth", module.clean_coseeing_auth)
	monkeypatch.setattr(dialogs, "has_saved_coseeing_refresh_token", lambda: False)
	panel = object.__new__(dialogs.LLMSettingsPanel)
	panel.coseeingCleanButton = Button()

	panel.onCleanCoseeingAuth(None)
	logout.set_result(None)
	cleanup.set_exception(RuntimeError("cleanup failed after native logout"))
	callback, args = queued.pop()
	callback(*args)

	assert panel.coseeingCleanButton.IsEnabled() is False


def _install_nvda(monkeypatch, *, dialog, wx, config=None, ui=None, log=None, call_after=None):
	if config is None:
		config = SimpleNamespace(conf={})
	if ui is None:
		ui = SimpleNamespace(message=lambda text: None)
	if log is None:
		log = SimpleNamespace(warning=lambda *args: None)
	if call_after is None:
		call_after = lambda function, *args: function(*args)
	monkeypatch.setitem(sys.modules, "config", config)
	monkeypatch.setitem(sys.modules, "wx", SimpleNamespace(CallAfter=call_after, **vars(wx)))
	monkeypatch.setitem(sys.modules, "gui", SimpleNamespace(
		mainFrame="frame",
		message=SimpleNamespace(MessageDialog=dialog, DefaultButtonSet=wx.DefaultButtonSet),
	))
	monkeypatch.setitem(sys.modules, "ui", ui)
	monkeypatch.setitem(sys.modules, "logHandler", SimpleNamespace(log=log))
	monkeypatch.setattr(module, "_", lambda text: text, raising=False)


def test_local_channel_does_not_request_auth(monkeypatch):
	calls = []
	monkeypatch.setattr(module, "get_coseeing_access_token", lambda **kw: calls.append(kw), raising=False)
	module.start_coseeing_auth("local")
	assert calls == []


def test_coseeing_channel_reconsiders_guest(monkeypatch):
	calls = []
	completed = Future()
	completed.set_result(None)
	monkeypatch.setattr(module, "get_coseeing_access_token", lambda **kw: calls.append(kw) or completed, raising=False)
	module.start_coseeing_auth("Coseeing")
	assert calls == [{"reconsider_guest": True, "silent": True}]


def test_coseeing_channel_notifies_when_auth_is_unavailable_and_not_silent(monkeypatch):
	"""Spec:278-281: selecting the Coseeing channel while the auth half is
	unavailable must be reported by the UI when the user asked for it (not
	silent), rather than silence.

	Before this fix: get_coseeing_access_token() swallows
	CoseeingAuthUnavailableError into a failed Future rather than raising, so
	start_coseeing_auth()'s own `except` never fires; it then reads
	`_singleton_adapter`, which is None because `_get_singleton_pair()` never
	got far enough to build one, and returns -- nothing is ever notified and
	the Future's exception is never retrieved.
	"""
	messages = []
	monkeypatch.setattr(module, "AUTH_AVAILABLE", False)
	monkeypatch.setattr(module, "_singleton_adapter", None)
	monkeypatch.setitem(sys.modules, "wx", SimpleNamespace(CallAfter=lambda function, *args: function(*args)))
	monkeypatch.setitem(sys.modules, "ui", SimpleNamespace(message=lambda text: messages.append(text)))
	monkeypatch.setattr(module, "_", lambda text: text, raising=False)

	module.start_coseeing_auth("Coseeing", silent=False)

	assert messages == ["Coseeing authentication is unavailable on this installation."]


def test_coseeing_channel_stays_silent_when_auth_unavailable_and_silent_requested(monkeypatch):
	"""silent=True -- the case at plugin construction, __init__.py:118 -- must
	stay silent even when the auth half is unavailable. Only the explicit,
	user-initiated selection (dialogs.py:276, silent=False) should notify.
	"""
	messages = []
	monkeypatch.setattr(module, "AUTH_AVAILABLE", False)
	monkeypatch.setattr(module, "_singleton_adapter", None)
	monkeypatch.setitem(sys.modules, "wx", SimpleNamespace(CallAfter=lambda function, *args: function(*args)))
	monkeypatch.setitem(sys.modules, "ui", SimpleNamespace(message=lambda text: messages.append(text)))
	monkeypatch.setattr(module, "_", lambda text: text, raising=False)

	module.start_coseeing_auth("Coseeing", silent=True)

	assert messages == []


def test_nvda_adapter_maps_dialog_choices(monkeypatch):
	settings = {"api_key": {"Coseeing": "old", "OpenAI": "keep"}}
	saved = []
	class Conf(dict):
		def save(self):
			saved.append(True)

	config = SimpleNamespace(conf=Conf({"WordBridge": {"settings": settings}}))

	class Dialog:
		result = 0
		created = []
		def __init__(self, *args, **kwargs):
			self.__class__.created.append((args, kwargs))
		def setYesNoLabels(self, yes, no):
			self.labels = (yes, no)
		def ShowModal(self):
			return self.result
		def Destroy(self):
			self.destroyed = True

	class Wx:
		ID_YES = 1
		ID_NO = 2
		ID_CANCEL = 3

		class DefaultButtonSet:
			YES_NO = 4

	class Ui:
		messages = []
		def message(self, text):
			self.messages.append(text)

	monkeypatch.setitem(__import__("sys").modules, "config", config)
	monkeypatch.setitem(__import__("sys").modules, "wx", Wx)
	monkeypatch.setitem(__import__("sys").modules, "gui", SimpleNamespace(
		mainFrame="frame",
		message=SimpleNamespace(MessageDialog=Dialog, DefaultButtonSet=Wx.DefaultButtonSet),
	))
	monkeypatch.setitem(__import__("sys").modules, "ui", Ui())
	monkeypatch.setitem(__import__("sys").modules, "logHandler", SimpleNamespace(log=SimpleNamespace(
		warning=lambda *args, **kwargs: None,
		info=lambda *args, **kwargs: None,
		debug=lambda *args, **kwargs: None,
		exception=lambda *args, **kwargs: None,
	)))
	monkeypatch.setattr(module, "_", lambda text: text, raising=False)
	adapter = module._NvdaAuthAdapter()
	for result, expected in ((Wx.ID_YES, "login"), (Wx.ID_NO, "guest"), (Wx.ID_CANCEL, "cancel")):
		Dialog.result = result
		assert adapter.prompt_login() == expected


def test_nvda_dialog_is_destroyed_after_each_choice(monkeypatch):
	class Dialog:
		result = 0
		instances = []
		def __init__(self, *args, **kwargs):
			self.__class__.instances.append(self)
		def setYesNoLabels(self, yes, no):
			pass
		def ShowModal(self):
			return self.result
		def Destroy(self):
			self.destroyed = True

	class Wx:
		ID_YES = 1
		ID_NO = 2
		ID_CANCEL = 3
		class DefaultButtonSet:
			YES_NO = 4

	monkeypatch.setitem(__import__("sys").modules, "config", SimpleNamespace(conf={}))
	monkeypatch.setitem(__import__("sys").modules, "wx", Wx)
	monkeypatch.setitem(__import__("sys").modules, "gui", SimpleNamespace(
		mainFrame="frame",
		message=SimpleNamespace(MessageDialog=Dialog, DefaultButtonSet=Wx.DefaultButtonSet),
	))
	monkeypatch.setitem(__import__("sys").modules, "ui", SimpleNamespace(message=lambda text: None))
	monkeypatch.setitem(__import__("sys").modules, "logHandler", SimpleNamespace(log=SimpleNamespace(
		warning=lambda *args, **kwargs: None,
		info=lambda *args, **kwargs: None,
		debug=lambda *args, **kwargs: None,
		exception=lambda *args, **kwargs: None,
	)))
	monkeypatch.setattr(module, "_", lambda text: text, raising=False)
	adapter = module._NvdaAuthAdapter()
	Dialog.result = Wx.ID_CANCEL
	assert adapter.prompt_login() == "cancel"
	assert adapter._active_dialog is None
	assert Dialog.instances[-1].destroyed is True


def test_shutdown_without_singleton_is_already_complete(monkeypatch):
	monkeypatch.setattr(module, "_singleton_session", None)
	monkeypatch.setattr(module, "_singleton_adapter", None)
	monkeypatch.setattr(module, "_shutdown_future", None)
	assert module.shutdown_coseeing_auth().result(timeout=1) is None


def test_shutdown_permanently_blocks_singleton_resurrection(monkeypatch):
	monkeypatch.setattr(module, "_singleton_session", None)
	monkeypatch.setattr(module, "_singleton_adapter", None)
	monkeypatch.setattr(module, "_shutdown_future", None)
	assert module.shutdown_coseeing_auth().result(timeout=1) is None

	monkeypatch.setattr(module, "_NvdaAuthAdapter", lambda: pytest.fail("singleton resurrected"))
	with pytest.raises(module.ClientClosedError):
		module.get_coseeing_access_token().result(timeout=1)


def test_dialog_uses_nvda_2026_yes_no_buttons(monkeypatch):
	created = []
	class Dialog:
		def __init__(self, parent, message, title, dialog_type=None, *, buttons=None):
			created.append((parent, message, title, dialog_type, buttons))
		def setYesNoLabels(self, yes, no):
			self.labels = (yes, no)
		def ShowModal(self):
			return 3
		def Destroy(self):
			pass
	class Wx:
		ID_YES = 1
		ID_NO = 2
		ID_CANCEL = 3
		class DefaultButtonSet:
			YES_NO = 4
	_install_nvda(monkeypatch, dialog=Dialog, wx=Wx)
	adapter = module._NvdaAuthAdapter()
	assert adapter.prompt_login() == "cancel"
	assert created == [
		("frame", "Sign in to Coseeing to use this service, or continue as a guest.", "Coseeing authentication", None, 4),
	]


def test_shutdown_cancels_only_active_dialog(monkeypatch):
	shown = Event()
	finish = Event()
	class Dialog:
		def __init__(self, *args, **kwargs):
			pass
		def setYesNoLabels(self, yes, no):
			pass
		def ShowModal(self):
			shown.set()
			finish.wait(timeout=1)
			return 3
		def EndModal(self, result):
			assert result == 3
			finish.set()
		def Destroy(self):
			self.destroyed = True
	class Wx:
		ID_YES = 1
		ID_NO = 2
		ID_CANCEL = 3
		class DefaultButtonSet:
			YES_NO = 4
	_install_nvda(monkeypatch, dialog=Dialog, wx=Wx)
	adapter = module._NvdaAuthAdapter()
	thread = Thread(target=adapter.prompt_login)
	thread.start()
	assert shown.wait(timeout=1)
	adapter.close_active_dialog()
	thread.join(timeout=1)
	assert not thread.is_alive()
	assert adapter._active_dialog is None


def test_client_factory_injects_exact_windows_credential_target(monkeypatch):
	constructed = []
	class Store:
		def __init__(self, target):
			self.target = target
			constructed.append(("store", target))
	class Client:
		def __init__(self, config, *, refresh_token_store):
			self.config = config
			self.store = refresh_token_store
			constructed.append(("client", config, refresh_token_store))
	class FutureClient:
		def __init__(self, client):
			self.client = client
	class Wx:
		class DefaultButtonSet:
			YES_NO = 4
	_install_nvda(monkeypatch, dialog=object, wx=Wx)
	monkeypatch.setitem(sys.modules, "_wb_vendor.coseeing_auth", SimpleNamespace(
		CoseeingAuthClient=Client, FutureAuthClient=FutureClient, WindowsCredentialStore=Store,
	))
	config = object()
	monkeypatch.setattr(module, "build_auth_config", lambda: config)
	result = module._NvdaAuthAdapter().client_factory()
	assert result.client.store.target == "org.coseeing.wordbridge/refresh"
	assert constructed[0] == ("store", "org.coseeing.wordbridge/refresh")


@pytest.mark.parametrize("value,expected", [("stored", True), (None, False)])
def test_saved_refresh_token_state_is_local_existence_check(monkeypatch, value, expected):
	class Store:
		def load(self):
			return value
	monkeypatch.setattr(module, "_new_refresh_token_store", lambda: Store(), raising=False)
	assert module.has_saved_coseeing_refresh_token() is expected


def test_saved_refresh_token_read_failure_is_treated_as_absent(monkeypatch):
	class Store:
		def load(self):
			raise RuntimeError("native storage unavailable")
	monkeypatch.setattr(module, "_new_refresh_token_store", lambda: Store(), raising=False)
	assert module.has_saved_coseeing_refresh_token() is False


def test_clean_logs_out_then_resets_singleton(monkeypatch):
	logout = Future()
	cleanup = Future()
	calls = []

	class Session:
		def logout_local(self):
			calls.append("logout_local")
			return logout

	class Adapter:
		def notify_completion(self, done):
			calls.append(("notify", done))

	monkeypatch.setattr(module, "_get_singleton_pair", lambda: (Session(), module._singleton_adapter))
	monkeypatch.setattr(module, "_singleton_adapter", Adapter())
	monkeypatch.setattr(
		module, "_reset_captured_coseeing_auth", lambda session, adapter: calls.append("reset") or cleanup,
		raising=False,
	)
	result = module.clean_coseeing_auth()
	logout.set_result(None)
	assert calls[0] == "logout_local"
	assert "reset" in calls
	assert not result.done()
	cleanup.set_result(None)
	assert result.result(timeout=1) is None


def test_clean_logout_failure_notifies_without_reset_or_secret_logging(monkeypatch):
	logout = Future()
	calls = []
	logs = []
	class Wx:
		class DefaultButtonSet:
			YES_NO = 4
	_install_nvda(
		monkeypatch,
		dialog=object,
		wx=Wx,
		log=SimpleNamespace(warning=lambda *args: logs.append(args)),
	)

	class Session:
		def logout_local(self):
			return logout

	adapter = module._NvdaAuthAdapter()
	notify_completion = adapter.notify_clean_completion
	def notify(done):
		calls.append(("notify", done))
		notify_completion(done)
	adapter.notify_clean_completion = notify

	monkeypatch.setattr(module, "_get_singleton_pair", lambda: (Session(), adapter))
	monkeypatch.setattr(module, "_singleton_adapter", adapter)
	monkeypatch.setattr(module, "_reset_captured_coseeing_auth", lambda session, adapter: calls.append("reset"), raising=False)
	result = module.clean_coseeing_auth()
	class TokenPersistenceError(RuntimeError):
		pass

	error = TokenPersistenceError("refresh-token-secret")
	logout.set_exception(error)
	with pytest.raises(TokenPersistenceError, match="refresh-token-secret"):
		result.result(timeout=1)
	assert "reset" not in calls
	assert calls == [("notify", result)]
	assert "refresh-token-secret" not in " ".join(map(str, logs))


def test_clean_cleanup_failure_notifies_through_shutting_down_adapter(monkeypatch):
	logout = Future()
	cleanup = Future()
	messages = []
	logs = []
	class Wx:
		class DefaultButtonSet:
			YES_NO = 4
	_install_nvda(
		monkeypatch,
		dialog=object,
		wx=Wx,
		ui=SimpleNamespace(message=messages.append),
		log=SimpleNamespace(warning=lambda *args: logs.append(args)),
	)

	class Session:
		def logout_local(self):
			return logout
	adapter = module._NvdaAuthAdapter()
	monkeypatch.setattr(module, "_get_singleton_pair", lambda: (Session(), adapter), raising=False)
	monkeypatch.setattr(module, "_reset_captured_coseeing_auth", lambda session, captured: cleanup, raising=False)
	result = module.clean_coseeing_auth()
	logout.set_result(None)
	adapter._shutting_down = True
	error = RuntimeError("refresh-token-secret")
	cleanup.set_exception(error)
	with pytest.raises(RuntimeError, match="refresh-token-secret"):
		result.result(timeout=1)
	assert messages == ["Coseeing authentication failed."]
	assert "refresh-token-secret" not in " ".join(map(str, logs))


def test_clean_resets_only_captured_singleton_after_intervening_reset(monkeypatch):
	logout = Future()
	old_cleanup = Future()
	new_cleanup = Future()
	old_session = SimpleNamespace(logout_local=lambda: logout, close=lambda: old_cleanup)
	new_session = SimpleNamespace(close=lambda: new_cleanup)
	old_adapter = SimpleNamespace(_shutting_down=False, post_ui=lambda function, *args: function(*args), close_active_dialog=lambda: None, notify_completion=lambda done: None)
	new_adapter = SimpleNamespace(_shutting_down=False, post_ui=lambda function, *args: function(*args), close_active_dialog=lambda: None)
	monkeypatch.setattr(module, "_singleton_session", old_session)
	monkeypatch.setattr(module, "_singleton_adapter", old_adapter)
	monkeypatch.setattr(module, "_shutdown_future", None)
	result = module.clean_coseeing_auth()
	assert module.reset_coseeing_auth() is old_cleanup
	monkeypatch.setattr(module, "_singleton_session", new_session)
	monkeypatch.setattr(module, "_singleton_adapter", new_adapter)
	logout.set_result(None)
	assert not new_adapter._shutting_down
	assert module._singleton_session is new_session
	assert not result.done()
	old_cleanup.set_result(None)
	assert result.result(timeout=1) is None
	assert not new_cleanup.done()


def test_singleton_creation_is_locked(monkeypatch):
	entered = Event()
	release = Event()
	instances = []
	class Adapter:
		def __init__(self):
			entered.set()
			release.wait(timeout=1)
		def session(self, **kwargs):
			instance = object()
			instances.append(instance)
			return instance
	monkeypatch.setattr(module, "_NvdaAuthAdapter", Adapter)
	monkeypatch.setattr(module, "_singleton_adapter", None)
	monkeypatch.setattr(module, "_singleton_session", None)
	results = []
	first = Thread(target=lambda: results.append(module._get_singleton()))
	second = Thread(target=lambda: results.append(module._get_singleton()))
	first.start()
	assert entered.wait(timeout=1)
	second.start()
	release.set()
	first.join(timeout=1)
	second.join(timeout=1)
	assert results == [instances[0], instances[0]]


def test_queued_notification_is_suppressed_after_shutdown(monkeypatch):
	queued = []
	messages = []
	class Dialog:
		pass
	class Wx:
		class DefaultButtonSet:
			YES_NO = 4
	_install_nvda(
		monkeypatch, dialog=Dialog, wx=Wx, ui=SimpleNamespace(message=messages.append),
		call_after=lambda function, *args: queued.append((function, args)),
	)
	adapter = module._NvdaAuthAdapter()
	failed = Future()
	failed.set_exception(RuntimeError("secret"))
	adapter.notify_completion(failed)
	adapter._shutting_down = True
	function, args = queued.pop()
	function(*args)
	assert messages == []


def test_dialog_close_logging_uses_exception_type_without_sensitive_text(monkeypatch):
	logs = []
	class Dialog:
		def EndModal(self, result):
			raise RuntimeError("refresh-token-secret")
	class Wx:
		ID_CANCEL = 3
		class DefaultButtonSet:
			YES_NO = 4
	_install_nvda(
		monkeypatch, dialog=Dialog, wx=Wx,
		log=SimpleNamespace(warning=lambda *args: logs.append(args)),
	)
	adapter = module._NvdaAuthAdapter()
	adapter._active_dialog = Dialog()
	adapter.close_active_dialog()
	logged = " ".join(str(value) for args in logs for value in args)
	assert "RuntimeError" in logged
	assert "refresh-token-secret" not in logged
	assert "Dialog" not in logged


def test_shutdown_reuses_existing_singleton_cleanup_future(monkeypatch):
	cleanup = Future()
	class Session:
		def close(self):
			return cleanup
	class Adapter:
		_shutting_down = False
		def post_ui(self, function, *args):
			function(*args)
		def close_active_dialog(self):
			pass
	monkeypatch.setattr(module, "_singleton_session", Session())
	monkeypatch.setattr(module, "_singleton_adapter", Adapter())
	monkeypatch.setattr(module, "_shutdown_future", None)
	first = module.shutdown_coseeing_auth()
	second = module.shutdown_coseeing_auth()
	assert first is second
	assert not second.done()
	cleanup.set_result(None)
	assert first.result(timeout=1) is None


def test_concurrent_shutdown_callers_share_blocked_client_cleanup(monkeypatch):
	close_started = Event()
	close_release = Event()
	client = FakeAuth(close_started, close_release)
	session = CoseeingAuthSession(
		client_factory=lambda: client,
		post_ui=lambda function, *args: function(*args),
		prompt_login=lambda: "guest",
	)
	session._client = client

	class Adapter:
		_shutting_down = False
		def post_ui(self, function, *args):
			function(*args)
		def close_active_dialog(self):
			pass

	first_released = Event()
	second_returned = Event()
	base_lock = RLock()
	first_thread = None
	class PublicationGate:
		def __enter__(self):
			base_lock.acquire()
			return self
		def __exit__(self, exc_type, exc_value, traceback):
			base_lock.release()
			if current_thread() is first_thread and not first_released.is_set():
				first_released.set()
				assert second_returned.wait(timeout=1)

	monkeypatch.setattr(module, "_singleton_session", session)
	monkeypatch.setattr(module, "_singleton_adapter", Adapter())
	monkeypatch.setattr(module, "_shutdown_future", None)
	monkeypatch.setattr(module, "_singleton_lock", PublicationGate())
	results = []
	first = Thread(target=lambda: results.append(module.shutdown_coseeing_auth()))
	first_thread = first
	second = Thread(target=lambda: (results.append(module.shutdown_coseeing_auth()), second_returned.set()))
	first.start()
	assert close_started.wait(timeout=1)
	second.start()
	assert first_released.wait(timeout=1)
	second.join(timeout=1)
	assert not second.is_alive()
	first.join(timeout=1)
	assert not first.is_alive()
	assert results[0] is results[1]
	assert not results[0].done()
	close_release.set()
	assert results[0].result(timeout=1) is None


def test_failure_log_names_the_mapped_cause(monkeypatch):
	"""The library maps many distinct failures onto one (stage, code) pair.

	`code=token_exchange_failed` is reached by an `OAuthError` (the token
	endpoint rejected the exchange) and by a `RuntimeError` (the OIDC protocol
	was already closed) alike, so the log line must carry the sanitized cause
	the library attached, or the two are indistinguishable in NVDA's log.
	"""
	logs = []
	class Dialog:
		pass
	class Wx:
		class DefaultButtonSet:
			YES_NO = 4
	_install_nvda(
		monkeypatch, dialog=Dialog, wx=Wx,
		log=SimpleNamespace(warning=lambda *args: logs.append(args)),
	)
	class _SanitizedCause(Exception):
		pass
	error = RuntimeError("mapped")
	error.operation = "login"
	error.stage = "token_exchange"
	error.code = "token_exchange_failed"
	error.__cause__ = _SanitizedCause("OAuthError: token_exchange_failed")
	failed = Future()
	failed.set_exception(error)
	module._NvdaAuthAdapter().notify_completion(failed)
	logged = " ".join(str(value) for args in logs for value in args)
	assert "OAuthError: token_exchange_failed" in logged


def test_failure_log_never_renders_an_unsanitized_cause(monkeypatch):
	"""Only `_SanitizedCause` is library-built from a type name and a fixed
	code. Any other cause contributes its type name and nothing else, so no
	token, URL or user text can reach the log through it.
	"""
	logs = []
	class Dialog:
		pass
	class Wx:
		class DefaultButtonSet:
			YES_NO = 4
	_install_nvda(
		monkeypatch, dialog=Dialog, wx=Wx,
		log=SimpleNamespace(warning=lambda *args: logs.append(args)),
	)
	error = RuntimeError("mapped")
	error.operation = "login"
	error.stage = "token_exchange"
	error.code = "token_exchange_failed"
	error.__cause__ = ValueError("refresh-token-secret")
	failed = Future()
	failed.set_exception(error)
	module._NvdaAuthAdapter().notify_completion(failed)
	logged = " ".join(str(value) for args in logs for value in args)
	assert "ValueError" in logged
	assert "refresh-token-secret" not in logged
