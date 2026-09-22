import sys
import threading
from types import SimpleNamespace


SETTINGS = {
	"corrector_config_id": "deepseek-v4-flash&DeepSeek",
	"execution_channel": "Coseeing",
	"api_key": {},
	"language": "zh_traditional",
	"typo_correction_mode": "standard",
	"customized_words_enable": False,
	"auto_display_report": False,
	"sound_effects_enable": False,
}


def _load(monkeypatch, queued, **settings):
	# LOAD-BEARING IMPORT PLACEMENT: keep this import inside the function.
	# tests/test_coseeing_auth_nvda.py installs fake _wb_vendor modules at
	# module scope and imports lib.coseeing_auth under them; a module-scope
	# import here would drag that file into *this* file's collection, which
	# runs before tests/test_coseeing_auth.py ("corr" < "cose") and leaves it
	# with poisoned exception bindings -- 17 unrelated failures. See the long
	# comment in tests/test_correction_notifications.py for the full story.
	from test_coseeing_auth_nvda import _load_nvda_plugin

	return _load_nvda_plugin(monkeypatch, {**SETTINGS, **settings}, [], queued)


class FakeThread:
	def __init__(self, target=None, args=(), daemon=None):
		self.target = target
		self.args = args
		self.daemon = daemon
		self.started = False
		self.alive = False

	def start(self):
		self.started = True
		self.alive = True

	def run_target(self):
		"""Run the worker body the way the real thread would."""
		try:
			self.target(*self.args)
		finally:
			self.alive = False

	def is_alive(self):
		return self.alive

	def join(self, timeout=None):
		self.alive = False


def _fake_threading(monkeypatch, plugin_module):
	created = []

	def factory(*args, **kwargs):
		thread = FakeThread(*args, **kwargs)
		created.append(thread)
		return thread

	monkeypatch.setattr(
		plugin_module,
		"threading",
		SimpleNamespace(Thread=factory, Event=threading.Event),
	)
	return created


def _instance(plugin_module, monkeypatch, *, corrected=None):
	instance = object.__new__(plugin_module.GlobalPlugin)
	instance._shutdown = threading.Event()
	instance.correct_typo_thread = None
	instance._feedback_thread = None
	instance._progress_cue = None
	instance.latest_action = plugin_module.CorrectionAction()
	instance.correctTypo = corrected if corrected is not None else (lambda text: None)
	return instance


def _start(plugin_module, instance, text="測試文字"):
	plugin_module.GlobalPlugin.startCorrection(instance, text)


def test_a_correction_runs_in_one_worker_thread_with_no_nested_thread(monkeypatch):
	queued = []
	plugin_module = _load(monkeypatch, queued)[0]
	created = _fake_threading(monkeypatch, plugin_module)
	instance = _instance(plugin_module, monkeypatch)

	_start(plugin_module, instance)
	assert len(created) == 1
	assert instance.correct_typo_thread is created[0]
	assert created[0].started

	created[0].run_target()

	# The worker must not spawn a second thread: that nesting is what left the
	# outer thread untracked by terminate().
	assert len(created) == 1


def test_the_progress_cue_is_timer_driven_not_sleep_polled(monkeypatch):
	queued = []
	plugin_module = _load(monkeypatch, queued)[0]
	created = _fake_threading(monkeypatch, plugin_module)

	def explode(*args, **kwargs):
		raise AssertionError("the correction path must not sleep-poll")

	monkeypatch.setattr(plugin_module.time, "sleep", explode)
	instance = _instance(plugin_module, monkeypatch)

	_start(plugin_module, instance)
	created[0].run_target()

	assert plugin_module.wx.timers, "the cue must be armed through wx.CallLater"


def test_a_second_correction_while_one_is_running_is_refused(monkeypatch):
	queued = []
	plugin_module = _load(monkeypatch, queued)[0]
	created = _fake_threading(monkeypatch, plugin_module)
	instance = _instance(plugin_module, monkeypatch)
	notified = []
	instance._notify = notified.append

	_start(plugin_module, instance)
	_start(plugin_module, instance)

	assert len(created) == 1
	assert len(notified) == 1
	assert "one proofreading task" in notified[0]


def test_finishing_the_worker_stops_the_cue_and_frees_the_worker_slot(monkeypatch):
	queued = []
	plugin_module = _load(monkeypatch, queued)[0]
	created = _fake_threading(monkeypatch, plugin_module)
	instance = _instance(plugin_module, monkeypatch)

	_start(plugin_module, instance)
	timer = plugin_module.wx.timers[-1]
	created[0].run_target()
	for callback, args in queued:
		callback(*args)

	assert timer.stopped
	assert instance.correct_typo_thread is None


def test_terminate_stops_the_progress_cue(monkeypatch):
	queued = []
	plugin_module, _, gui = _load(monkeypatch, queued)
	_fake_threading(monkeypatch, plugin_module)
	instance = _instance(plugin_module, monkeypatch)
	gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(plugin_module.LLMSettingsPanel)

	_start(plugin_module, instance)
	timer = plugin_module.wx.timers[-1]
	plugin_module.GlobalPlugin.terminate(instance)

	assert timer.stopped
	timer.fire()
	assert len(plugin_module.wx.timers) == 1, "a delivered timer must not re-arm after terminate()"


def test_sound_effects_play_without_blocking_the_ui_thread(monkeypatch):
	queued = []
	plugin_module = _load(monkeypatch, queued, sound_effects_enable=True)[0]
	_fake_threading(monkeypatch, plugin_module)
	instance = _instance(plugin_module, monkeypatch)

	_start(plugin_module, instance)

	played = plugin_module.nvwave.played
	assert len(played) == 1
	# asynchronous=False would block the UI thread for the length of the wave.
	assert played[0][1]["asynchronous"] is True


def test_the_beep_cue_is_used_when_sound_effects_are_disabled(monkeypatch):
	queued = []
	plugin_module = _load(monkeypatch, queued, sound_effects_enable=False)[0]
	_fake_threading(monkeypatch, plugin_module)
	instance = _instance(plugin_module, monkeypatch)

	_start(plugin_module, instance)
	assert plugin_module.nvwave.played == []
	plugin_module.wx.timers[-1].fire()

	# __init__.py does `from tones import beep`, so the recording list lives on
	# the stub module rather than on the plugin module.
	assert len(sys.modules["tones"].beeps) == 1
