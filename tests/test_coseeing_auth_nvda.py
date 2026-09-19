from concurrent.futures import Future
import importlib.util
import ctypes
from threading import Event, RLock, Thread, current_thread
from types import SimpleNamespace
from pathlib import Path
import sys
import pytest

import lib.coseeing_auth as module
from coseeing_auth_helpers import FakeAuth
from lib.coseeing_auth import CoseeingAuthSession
from lib.coseeing import build_coseeing_headers


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"


def _load_nvda_plugin(monkeypatch, settings, auth_calls, queued):
	class Config(dict):
		def save(self):
			pass

	config = SimpleNamespace(conf=Config({"WordBridge": {"settings": settings}}))
	config.conf.spec = {}

	class ParentPlugin:
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

	wx_choice = Choice
	class Wx:
		CallAfter = staticmethod(lambda function, *args: queued.append((function, args)))
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
	monkeypatch.setitem(sys.modules, "logHandler", SimpleNamespace(log=SimpleNamespace()))
	monkeypatch.setitem(sys.modules, "nvwave", SimpleNamespace())
	monkeypatch.setitem(sys.modules, "scriptHandler", SimpleNamespace(script=lambda **kwargs: lambda function: function))
	monkeypatch.setitem(sys.modules, "textInfos", SimpleNamespace(POSITION_SELECTION=object()))
	monkeypatch.setitem(sys.modules, "tones", SimpleNamespace(beep=lambda *args: None))
	monkeypatch.setitem(sys.modules, "ui", SimpleNamespace(message=lambda *args: None))
	monkeypatch.setitem(sys.modules, "hanzidentifier", SimpleNamespace(has_chinese=lambda text: True))
	monkeypatch.setitem(sys.modules, "configobj.validate", SimpleNamespace(
		VdtValueTooBigError=ValueError,
		VdtValueTooSmallError=ValueError,
	))
	monkeypatch.setitem(sys.modules, "configobj", SimpleNamespace(validate=sys.modules["configobj.validate"]))
	monkeypatch.setitem(sys.modules, "requests", SimpleNamespace())
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
	monkeypatch.setitem(sys.modules, dictionary_package.__name__, dictionary_package)
	monkeypatch.setitem(sys.modules, f"{package_name}.dictionary.dialog", SimpleNamespace(DictionaryEntryDialog=object))

	monkeypatch.setattr("builtins._", lambda text: text, raising=False)
	spec = importlib.util.spec_from_file_location(
		package_name,
		ADDON_PATH / "__init__.py",
		submodule_search_locations=[str(ADDON_PATH)],
	)
	plugin = importlib.util.module_from_spec(spec)
	sys.modules[package_name] = plugin
	spec.loader.exec_module(plugin)
	plugin.dialogs = sys.modules[f"{package_name}.dialogs"]
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

	class Manager:
		endpoints = {"OpenAI": [object()], "Coseeing": [object()]}
		channel = "Coseeing"

		def get_item_by_index(self, provider_index, model_index):
			return SimpleNamespace(corrector_config_id="deepseek&DeepSeek", execution_channel=self.channel)

	dialogs.configManager = Manager()
	assert dialogs.configManager.get_item_by_index(0, 0).execution_channel == "Coseeing"
	panel = object.__new__(dialogs.LLMSettingsPanel)
	panel.providerList = Control(0)
	panel.modelList = Control(0)
	panel.languageList = Control(0)
	panel.typoCorrectionModeList = Control(0)
	panel.maxCharCountSpinCtrl = Control(512)
	panel.autoDisplayReportEnable = Control(False)
	panel.customizedWordEnable = Control(True)
	panel.soundEffectsEnable = Control(True)
	panel._coseeingRefreshTokenOnOpen = "saved-refresh"
	panel.accountTextCtrlMap = {
		"Coseeing": Control("updated-refresh"),
		"OpenAI": Control("updated-key"),
	}

	panel.onSave()
	assert config.conf["WordBridge"]["settings"]["execution_channel"] == "Coseeing"
	assert settings["api_key"] == {"Coseeing": "updated-refresh", "OpenAI": "updated-key"}
	assert settings["coseeing_username"] == "legacy-user"
	assert settings["coseeing_password"] == "legacy-password"
	assert len(queued) == 1
	callback, args = queued.pop()
	assert auth_calls == ["reset"]
	callback(*args)
	assert auth_calls == ["reset", "Coseeing"]

	Manager.channel = "local"
	panel.accountTextCtrlMap["Coseeing"].value = "saved-refresh"
	panel.onSave()
	callback, args = queued.pop()
	callback(*args)
	assert config.conf["WordBridge"]["settings"]["execution_channel"] == "local"
	assert auth_calls == ["reset", "Coseeing"]


def test_settings_panel_keeps_coseeing_sizer_without_legacy_credential_controls(monkeypatch):
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
		def __init__(self, *args, value="", **kwargs):
			self.value = value

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
			pass

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
	panel = object.__new__(dialogs.LLMSettingsPanel)
	panel.scaleSize = lambda value: value
	panel._refreshAccountInfo = lambda: None
	panel.makeSettings(Sizer())

	assert "Coseeing" in panel.accountGroupSizerMap
	assert "Coseeing" in panel.accountTextCtrlMap
	refresh_token_controls = [
		call for call in Helper.calls if call[0] == "Refresh Token:"
	]
	assert len(refresh_token_controls) == 1
	_, control_type, kwargs = refresh_token_controls[0]
	assert control_type is plugin.wx.TextCtrl
	assert kwargs["value"] == "refresh-token"
	assert "style" not in kwargs


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
	monkeypatch.setitem(__import__("sys").modules, "logHandler", SimpleNamespace(log=SimpleNamespace(warning=lambda *args: None)))
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
	monkeypatch.setitem(__import__("sys").modules, "logHandler", SimpleNamespace(log=SimpleNamespace(warning=lambda *args: None)))
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


def test_client_factory_builds_exact_future_client(monkeypatch):
	constructed = []
	class Client:
		def __init__(self, config):
			constructed.append(("client", config))
	class FutureClient:
		def __init__(self, client):
			self._client = client
			constructed.append(("future", client))
	class Wx:
		class DefaultButtonSet:
			YES_NO = 4
	_install_nvda(monkeypatch, dialog=object, wx=Wx)
	monkeypatch.setitem(sys.modules, "coseeing_auth", SimpleNamespace(
		CoseeingAuthClient=Client, FutureAuthClient=FutureClient,
	))
	config = object()
	monkeypatch.setattr(module, "build_auth_config", lambda: config)
	result = module._NvdaAuthAdapter().client_factory()
	assert isinstance(result, FutureClient)
	assert constructed == [("client", config), ("future", result._client)]


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
