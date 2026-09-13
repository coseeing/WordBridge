from concurrent.futures import Future
from types import SimpleNamespace

import lib.coseeing_auth as module


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
	assert calls == [{"reconsider_guest": True}]


def test_nvda_adapter_maps_dialog_choices_and_only_saves_coseeing(monkeypatch):
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
	assert adapter.read_refresh_token() == "old"
	adapter.save_refresh_token("new")
	assert settings["api_key"] == {"Coseeing": "new", "OpenAI": "keep"}
	assert saved == [True]


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
	adapter = module._NvdaAuthAdapter()
	Dialog.result = Wx.ID_CANCEL
	assert adapter.prompt_login() == "cancel"
	assert adapter._active_dialog is None
	assert Dialog.instances[-1].destroyed is True


def test_shutdown_without_singleton_is_already_complete(monkeypatch):
	monkeypatch.setattr(module, "_singleton_session", None)
	monkeypatch.setattr(module, "_singleton_adapter", None)
	assert module.shutdown_coseeing_auth().result(timeout=1) is None
