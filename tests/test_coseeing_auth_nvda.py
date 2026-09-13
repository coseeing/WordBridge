from concurrent.futures import Future
from threading import Event, RLock, Thread, current_thread
from types import SimpleNamespace
import sys

import lib.coseeing_auth as module
from coseeing_auth_helpers import FakeAuth
from lib.coseeing_auth import CoseeingAuthSession


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


def test_dialog_uses_translatable_labels_and_legacy_yes_no_style(monkeypatch):
	created = []
	class Dialog:
		def __init__(self, *args, **kwargs):
			created.append((args, kwargs))
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
	assert created[0][1]["style"] == 4
	assert created[0][0][1] == "Sign in to Coseeing to use this service, or continue as a guest."
	assert created[0][0][2] == "Coseeing authentication"


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


def test_save_refresh_token_reports_config_save_failure(monkeypatch):
	class Conf(dict):
		def save(self):
			raise OSError("secret save details")
	settings = {"api_key": {"Coseeing": "old", "OpenAI": "keep"}}
	config = SimpleNamespace(conf=Conf({"WordBridge": {"settings": settings}}))
	class Wx:
		class DefaultButtonSet:
			YES_NO = 4
	_install_nvda(monkeypatch, dialog=object, wx=Wx, config=config)
	with __import__("pytest").raises(OSError, match="secret save details"):
		module._NvdaAuthAdapter().save_refresh_token("new")
	assert settings["api_key"] == {"Coseeing": "new", "OpenAI": "keep"}


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
		def session(self):
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
		read_refresh_token=lambda: None,
		save_refresh_token=lambda value: None,
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
