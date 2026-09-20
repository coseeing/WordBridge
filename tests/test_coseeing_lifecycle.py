import threading
import time
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

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
	plugin_module, _, gui = _load_nvda_plugin(monkeypatch, SETTINGS, [], [])
	instance = _instance(plugin_module)
	instance.correct_typo_thread = None
	instance._feedback_thread = None
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


def test_feedback_reads_one_internally_consistent_snapshot_despite_nested_event_loop(monkeypatch):
	# Spec Tests item 8: latest_action observed from the UI thread is always
	# internally consistent -- request, response and interaction_id come from
	# the same task, even though FeedbackDialog.ShowModal() runs a nested wx
	# event loop that can deliver a pending _set_latest_action callback for a
	# second, unrelated task while the dialog is still open.
	queued = []
	plugin_module = _plugin(monkeypatch, queued)
	instance = _instance(plugin_module)
	instance.latest_action = plugin_module.CorrectionAction(
		interaction_id="i-first", request="first-req", response="first-resp"
	)
	future = Future()
	future.set_result(None)
	monkeypatch.setattr(plugin_module, "get_coseeing_access_token", lambda: future)
	monkeypatch.setattr(plugin_module, "ui", SimpleNamespace(message=lambda *args, **kwargs: None))
	monkeypatch.setattr(plugin_module, "log", SimpleNamespace(warning=lambda *args, **kwargs: None))

	dialog_args = []
	record = {}

	class Dialog:
		feedbackTextCtrl = SimpleNamespace(GetValue=lambda: "feedback text")

		def __init__(self, *args):
			dialog_args.append(args)

		def __enter__(self):
			return self

		def __exit__(self, *args):
			return False

		def ShowModal(self):
			# Simulate a second, unrelated correction completing and
			# publishing its own snapshot while this dialog is open.
			instance.latest_action = plugin_module.CorrectionAction(
				interaction_id="i-second", request="second-req", response="second-resp"
			)
			return plugin_module.wx.ID_OK

	monkeypatch.setattr(plugin_module, "FeedbackDialog", Dialog)
	plugin_module.wx.ID_OK = plugin_module.wx.OK
	monkeypatch.setattr(
		plugin_module.requests,
		"post",
		lambda url, **kwargs: record.update(url=url, **kwargs) or SimpleNamespace(status_code=200, json=lambda: {}),
		raising=False,
	)

	plugin_module.GlobalPlugin.script_correctionFeedback(instance, None)
	assert len(queued) == 1
	show, args = queued.pop()
	show(*args)

	worker = instance._feedback_thread
	worker.join(timeout=1)

	assert dialog_args[0][1:] == ("first-req", "first-resp")
	assert record["json"]["interaction_id"] == "i-first"


def test_terminate_returns_within_budget_while_a_worker_is_blocked(monkeypatch):
	# Both workers must be real, live daemon threads so a per-worker budget
	# (join each worker for the full TERMINATE_WAIT_SECONDS) is distinguishable
	# from the shared budget the spec requires (join all workers together
	# within one TERMINATE_WAIT_SECONDS deadline). With only one worker ever
	# joined, a per-worker regression that doubles the wait cannot be caught.
	queued = []
	plugin_module = _plugin(monkeypatch, queued)
	instance = _instance(plugin_module)
	monkeypatch.setattr(plugin_module, "log", SimpleNamespace(warning=lambda *args: None))
	plugin_module.gui.settingsDialogs.NVDASettingsDialog.categoryClasses = [plugin_module.LLMSettingsPanel]

	release = threading.Event()
	worker = threading.Thread(target=lambda: release.wait(30), daemon=True)
	feedback_worker = threading.Thread(target=lambda: release.wait(30), daemon=True)
	worker.start()
	feedback_worker.start()
	instance.correct_typo_thread = worker
	instance._feedback_thread = feedback_worker

	try:
		started = time.monotonic()
		plugin_module.GlobalPlugin.terminate(instance)
		elapsed = time.monotonic() - started

		assert instance._shutdown.is_set()
		assert elapsed < plugin_module.TERMINATE_WAIT_SECONDS + 0.5
		assert worker.is_alive(), "terminate must not wait for the worker to finish"
		assert feedback_worker.is_alive(), "terminate must not wait for the feedback worker to finish"
	finally:
		release.set()


def test_terminate_is_safe_when_called_twice(monkeypatch):
	auth_calls = []
	plugin_module, _, gui = _load_nvda_plugin(monkeypatch, SETTINGS, auth_calls, [])
	instance = _instance(plugin_module)
	monkeypatch.setattr(plugin_module, "log", SimpleNamespace(warning=lambda *args: None))
	gui.settingsDialogs.NVDASettingsDialog.categoryClasses = [plugin_module.LLMSettingsPanel]
	instance.correct_typo_thread = None
	instance._feedback_thread = None

	plugin_module.GlobalPlugin.terminate(instance)
	plugin_module.GlobalPlugin.terminate(instance)

	assert instance._shutdown.is_set()
	# A second terminate() that did nothing at all would still leave
	# _shutdown set from the first call, so that alone cannot prove the
	# second call did real work. Assert the parent's terminate() actually ran
	# twice, and that the stubbed auth shutdown was invoked twice too.
	assert auth_calls.count("shutdown") == 2
	assert plugin_module.GlobalPlugin.terminated == 2


def test_terminate_survives_worker_is_alive_raising(monkeypatch):
	"""R02: terminate() never raises, even if a worker's is_alive() blows up.

	The rest of the cleanup tail (shutdown_coseeing_auth(), the
	categoryClasses removal, and the parent's terminate()) must still run.
	"""
	auth_calls = []
	plugin_module, _, gui = _load_nvda_plugin(monkeypatch, SETTINGS, auth_calls, [])
	instance = _instance(plugin_module)
	exceptions_logged = []
	monkeypatch.setattr(
		plugin_module,
		"log",
		SimpleNamespace(
			warning=lambda *args: None,
			exception=lambda *args, **kwargs: exceptions_logged.append(args),
		),
	)
	gui.settingsDialogs.NVDASettingsDialog.categoryClasses = [plugin_module.LLMSettingsPanel]

	class ExplodingWorker:
		def is_alive(self):
			raise RuntimeError("is_alive boom")

	instance.correct_typo_thread = ExplodingWorker()
	instance._feedback_thread = None

	plugin_module.GlobalPlugin.terminate(instance)

	assert instance._shutdown.is_set()
	assert exceptions_logged, "the is_alive() exception must be logged, not swallowed silently"
	assert auth_calls.count("shutdown") == 1, "shutdown_coseeing_auth() must still run"
	assert plugin_module.LLMSettingsPanel not in gui.settingsDialogs.NVDASettingsDialog.categoryClasses
	assert plugin_module.GlobalPlugin.terminated == 1, "the parent's terminate() must still run"


def test_terminate_survives_shutdown_coseeing_auth_raising(monkeypatch):
	"""R02: terminate() never raises, even if shutdown_coseeing_auth() blows up.

	The categoryClasses removal and the parent's terminate() must still run
	-- otherwise the WordBridge settings panel leaks into NVDA's settings
	dialog for the rest of the session.
	"""
	plugin_module, _, gui = _load_nvda_plugin(monkeypatch, SETTINGS, [], [])
	instance = _instance(plugin_module)
	exceptions_logged = []
	monkeypatch.setattr(
		plugin_module,
		"log",
		SimpleNamespace(
			warning=lambda *args: None,
			exception=lambda *args, **kwargs: exceptions_logged.append(args),
		),
	)
	monkeypatch.setattr(
		plugin_module,
		"shutdown_coseeing_auth",
		lambda: (_ for _ in ()).throw(RuntimeError("shutdown boom")),
	)
	gui.settingsDialogs.NVDASettingsDialog.categoryClasses = [plugin_module.LLMSettingsPanel]
	instance.correct_typo_thread = None
	instance._feedback_thread = None

	plugin_module.GlobalPlugin.terminate(instance)

	assert instance._shutdown.is_set()
	assert exceptions_logged, "the shutdown_coseeing_auth() exception must be logged, not swallowed silently"
	assert plugin_module.LLMSettingsPanel not in gui.settingsDialogs.NVDASettingsDialog.categoryClasses
	assert plugin_module.GlobalPlugin.terminated == 1, "the parent's terminate() must still run"


def test_terminate_runs_cleanup_tail_when_join_raises_keyboardinterrupt(monkeypatch):
	"""Round 2 regression: a BaseException (not an Exception) from the join
	loop must not skip the cleanup tail. terminate() MAY still propagate a
	BaseException such as KeyboardInterrupt -- that is intended, since
	swallowing the process's own exit request in a screen reader's teardown
	would be worse -- but shutdown_coseeing_auth(), the categoryClasses
	removal, and the parent's terminate() must all still run first.
	"""
	auth_calls = []
	plugin_module, _, gui = _load_nvda_plugin(monkeypatch, SETTINGS, auth_calls, [])
	instance = _instance(plugin_module)
	monkeypatch.setattr(plugin_module, "log", SimpleNamespace(warning=lambda *args: None))
	gui.settingsDialogs.NVDASettingsDialog.categoryClasses = [plugin_module.LLMSettingsPanel]

	class ExplodingWorker:
		def is_alive(self):
			raise KeyboardInterrupt("is_alive boom")

	instance.correct_typo_thread = ExplodingWorker()
	instance._feedback_thread = None

	with pytest.raises(KeyboardInterrupt):
		plugin_module.GlobalPlugin.terminate(instance)

	assert instance._shutdown.is_set()
	assert auth_calls.count("shutdown") == 1, "shutdown_coseeing_auth() must still run"
	assert plugin_module.LLMSettingsPanel not in gui.settingsDialogs.NVDASettingsDialog.categoryClasses
	assert plugin_module.GlobalPlugin.terminated == 1, "the parent's terminate() must still run"
