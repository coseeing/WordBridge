import threading
import time
from types import SimpleNamespace

from test_coseeing_auth_nvda import _load_nvda_plugin

SETTINGS = {
	"corrector_config_id": "deepseek-v4-flash&DeepSeek",
	"execution_channel": "Coseeing",
	"api_key": {},
	"language": "zh_traditional",
	"typo_correction_mode": "standard",
	"customized_words_enable": False,
	"auto_display_report": False,
}


def _plugin(monkeypatch, queued):
	return _load_nvda_plugin(monkeypatch, SETTINGS, [], queued)[0]


def _instance(plugin_module):
	instance = object.__new__(plugin_module.GlobalPlugin)
	instance._shutdown = threading.Event()
	return instance


def test_request_is_skipped_once_shutdown_started(monkeypatch):
	plugin_module = _plugin(monkeypatch, [])
	instance = _instance(plugin_module)
	instance._shutdown.set()
	posted = []
	monkeypatch.setattr(plugin_module.requests, "post", lambda *a, **k: posted.append(k), raising=False)

	assert plugin_module.GlobalPlugin._post_coseeing_request(instance, "http://example.invalid") is None
	assert posted == []


def test_response_arriving_after_shutdown_is_discarded(monkeypatch):
	plugin_module = _plugin(monkeypatch, [])
	instance = _instance(plugin_module)

	def post(url, **kwargs):
		instance._shutdown.set()
		return SimpleNamespace(status_code=200)

	monkeypatch.setattr(plugin_module.requests, "post", post, raising=False)

	assert plugin_module.GlobalPlugin._post_coseeing_request(instance, "http://example.invalid") is None


def test_request_uses_explicit_connect_and_read_timeouts(monkeypatch):
	plugin_module = _plugin(monkeypatch, [])
	instance = _instance(plugin_module)
	record = {}
	monkeypatch.setattr(
		plugin_module.requests,
		"post",
		lambda url, **kwargs: record.update(kwargs) or SimpleNamespace(status_code=200),
		raising=False,
	)

	plugin_module.GlobalPlugin._post_coseeing_request(instance, "http://example.invalid")

	assert record["timeout"] == (10, 120)
	assert plugin_module.COSEEING_TIMEOUT == (10, 120)


def test_post_holds_no_lock_across_the_http_call(monkeypatch):
	"""terminate() must not block on an in-flight HTTP call: no lock guards the post."""
	plugin_module, config, gui = _load_nvda_plugin(monkeypatch, SETTINGS, [], [])
	instance = _instance(plugin_module)
	gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(plugin_module.LLMSettingsPanel)
	terminate_finished = threading.Event()

	def post(url, **kwargs):
		def call_terminate():
			plugin_module.GlobalPlugin.terminate(instance)
			terminate_finished.set()

		terminator = threading.Thread(target=call_terminate)
		terminator.start()
		terminator.join(timeout=2)
		assert not terminator.is_alive(), "terminate() blocked while the HTTP call was in flight"
		return SimpleNamespace(status_code=200)

	monkeypatch.setattr(plugin_module.requests, "post", post, raising=False)
	plugin_module.GlobalPlugin._post_coseeing_request(instance, "http://example.invalid")

	assert terminate_finished.is_set()


def test_notify_schedules_nothing_once_shutdown_started(monkeypatch):
	queued = []
	plugin_module = _plugin(monkeypatch, queued)
	instance = _instance(plugin_module)
	instance._shutdown.set()

	plugin_module.GlobalPlugin._notify(instance, "訊息")

	assert queued == []


def test_notify_callback_is_inert_if_shutdown_happens_before_delivery(monkeypatch):
	queued = []
	plugin_module = _plugin(monkeypatch, queued)
	instance = _instance(plugin_module)
	messages = []
	monkeypatch.setattr(plugin_module, "ui", SimpleNamespace(message=messages.append))

	plugin_module.GlobalPlugin._notify(instance, "訊息")
	assert len(queued) == 1

	instance._shutdown.set()
	callback, args = queued.pop()
	callback(*args)

	assert messages == []


def test_clipboard_and_report_are_dispatched_not_called_inline(monkeypatch):
	queued = []
	plugin_module = _plugin(monkeypatch, queued)
	instance = _instance(plugin_module)
	copied = []
	reported = []
	monkeypatch.setattr(plugin_module.api, "copyToClip", copied.append, raising=False)
	monkeypatch.setattr(plugin_module.GlobalPlugin, "showReport", lambda self, diff: reported.append(diff))

	plugin_module.GlobalPlugin._run_on_ui(instance, plugin_module.api.copyToClip, "修正")
	plugin_module.GlobalPlugin._run_on_ui(instance, instance.showReport, [])

	assert copied == []
	assert reported == []
	for callback, args in queued:
		callback(*args)
	assert copied == ["修正"]
	assert reported == [[]]


def test_onpreview_schedules_nothing_once_shutdown_started(monkeypatch):
	queued = []
	plugin_module = _plugin(monkeypatch, queued)
	instance = _instance(plugin_module)
	instance._shutdown.set()

	plugin_module.GlobalPlugin.OnPreview(instance, "report.html")

	assert queued == []


def test_onpreview_callback_is_inert_if_shutdown_happens_before_delivery(monkeypatch):
	queued = []
	plugin_module = _plugin(monkeypatch, queued)
	instance = _instance(plugin_module)
	opened = []
	monkeypatch.setattr(plugin_module.os, "startfile", opened.append, raising=False)

	plugin_module.GlobalPlugin.OnPreview(instance, "report.html")
	assert len(queued) == 1

	instance._shutdown.set()
	callback, args = queued.pop()
	callback(*args)

	assert opened == []


from concurrent.futures import Future


def test_latest_action_is_published_as_one_snapshot_on_the_ui_thread(monkeypatch):
	queued = []
	plugin_module = _plugin(monkeypatch, queued)
	instance = _instance(plugin_module)
	instance.latest_action = plugin_module.CorrectionAction()
	instance.readDictionary = lambda: []
	future = Future()
	future.set_result("access")
	monkeypatch.setattr(plugin_module, "get_coseeing_access_token", lambda: future)
	monkeypatch.setattr(plugin_module, "strings_diff", lambda request, response: ["d"])
	monkeypatch.setattr(plugin_module.api, "copyToClip", lambda text: None, raising=False)
	monkeypatch.setattr(plugin_module, "log", SimpleNamespace(warning=lambda *args: None))
	monkeypatch.setattr(
		plugin_module.requests,
		"post",
		lambda url, **kwargs: SimpleNamespace(
			status_code=200,
			json=lambda: {"response": "修正", "interaction_id": "i-1", "cost": 0},
		),
		raising=False,
	)
	before = instance.latest_action

	plugin_module.GlobalPlugin.correctTypo(instance, "原文")

	assert instance.latest_action is before, "the worker thread must not write latest_action"

	for callback, args in list(queued):
		callback(*args)

	assert instance.latest_action.request == "原文"
	assert instance.latest_action.response == "修正"
	assert instance.latest_action.interaction_id == "i-1"
	assert instance.latest_action.diff == ["d"]


def test_correction_action_is_immutable(monkeypatch):
	plugin_module = _plugin(monkeypatch, [])
	action = plugin_module.CorrectionAction(request="a")
	try:
		action.request = "b"
	except Exception as error:
		assert type(error).__name__ == "FrozenInstanceError"
	else:
		assert False, "CorrectionAction must be frozen"


def test_terminate_returns_within_budget_while_a_worker_is_blocked(monkeypatch):
	queued = []
	plugin_module = _plugin(monkeypatch, queued)
	instance = _instance(plugin_module)
	monkeypatch.setattr(plugin_module, "log", SimpleNamespace(warning=lambda *args: None))
	plugin_module.gui.settingsDialogs.NVDASettingsDialog.categoryClasses = [plugin_module.LLMSettingsPanel]

	release = threading.Event()
	worker = threading.Thread(target=lambda: release.wait(30), daemon=True)
	worker.start()
	instance.correct_typo_thread = worker
	instance._feedback_thread = None

	started = time.monotonic()
	plugin_module.GlobalPlugin.terminate(instance)
	elapsed = time.monotonic() - started
	release.set()

	assert instance._shutdown.is_set()
	assert elapsed < plugin_module.TERMINATE_WAIT_SECONDS + 2
	assert worker.is_alive(), "terminate must not wait for the worker to finish"


def test_terminate_is_safe_when_called_twice(monkeypatch):
	plugin_module = _plugin(monkeypatch, [])
	instance = _instance(plugin_module)
	monkeypatch.setattr(plugin_module, "log", SimpleNamespace(warning=lambda *args: None))
	plugin_module.gui.settingsDialogs.NVDASettingsDialog.categoryClasses = [plugin_module.LLMSettingsPanel]
	instance.correct_typo_thread = None
	instance._feedback_thread = None

	plugin_module.GlobalPlugin.terminate(instance)
	plugin_module.GlobalPlugin.terminate(instance)

	assert instance._shutdown.is_set()
