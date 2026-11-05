"""GlobalPlugin's use of the catalog updater (spec sections 11.2-11.7).

_load_nvda_plugin is imported at function scope, never at module scope
(importing test_coseeing_auth_nvda at collection time poisons coseeing_auth).
"""

import dataclasses
from decimal import Decimal
from types import SimpleNamespace

import pytest


DEFAULT_URL = "https://wordbridge.coseeing.org"


def _settings(**overrides):
	settings = {
		"corrector_config_id": "gpt-6.1-sol&OpenAI",
		"execution_channel": "local",
		"api_key": {"OpenAI": "key"},
		"language": "zh_traditional",
		"typo_correction_mode": "standard",
		"customized_words_enable": False,
		"auto_display_report": False,
		"sound_effects_enable": True,
	}
	settings.update(overrides)
	return settings


def _load(monkeypatch, settings=None, log_warnings=None):
	from test_coseeing_auth_nvda import _load_nvda_plugin

	queued = []
	auth_calls = []
	plugin, config, gui = _load_nvda_plugin(
		monkeypatch, settings if settings is not None else _settings(), auth_calls, queued,
		log_warnings=log_warnings,
	)
	return plugin, queued, auth_calls


def test_the_config_spec_declares_catalog_url_with_the_default(monkeypatch):
	plugin, _queued, _auth = _load(monkeypatch)

	assert plugin.config.conf.spec["WordBridge"]["settings"]["catalog_url"] == f"string(default='{DEFAULT_URL}')"


def test_init_schedules_sign_in_then_fetch_start(monkeypatch):
	plugin, queued, _auth = _load(monkeypatch)

	instance = plugin.GlobalPlugin()

	assert [callback for callback, _args in queued] == [instance._start_coseeing_auth, instance._start_catalog_fetch]
	instance.terminate()


def test_init_uses_the_cache_for_the_configured_url(monkeypatch):
	plugin, _queued, _auth = _load(monkeypatch)

	instance = plugin.GlobalPlugin()

	assert instance.catalog.get_model("gpt-6.1-sol&OpenAI") is not None
	assert plugin.registry.current() is instance.catalog
	assert plugin.catalog_updater.status() == plugin.catalog_updater.UpdaterStatus(source="cache", fetch="running")
	instance.terminate()


def test_init_with_an_empty_url_is_bundled_only(monkeypatch):
	plugin, queued, _auth = _load(monkeypatch, _settings(catalog_url=""))

	instance = plugin.GlobalPlugin()
	for callback, args in list(queued):
		callback(*args)

	assert instance.catalog.models == ()
	assert instance.catalog.labels_for("Coseeing") == ("default",)
	assert plugin.started_catalog_threads == []
	assert plugin.catalog_updater.status().fetch == "off"
	# A stored local model and no model list: no Coseeing sign-in (U7).
	assert _auth == []
	instance.terminate()


def test_the_fetch_start_callback_starts_one_fetch_for_the_configured_url(monkeypatch):
	plugin, queued, _auth = _load(monkeypatch)
	instance = plugin.GlobalPlugin()

	callback, args = queued[1]
	callback(*args)

	assert len(plugin.started_catalog_threads) == 1
	_target, (generation, check) = plugin.started_catalog_threads[0]
	assert check.url == DEFAULT_URL
	assert plugin.network_calls == []
	instance.terminate()


def test_the_fetch_start_callback_does_nothing_after_terminate(monkeypatch):
	plugin, queued, _auth = _load(monkeypatch)
	instance = plugin.GlobalPlugin()
	instance.terminate()

	callback, args = queued[1]
	callback(*args)

	assert plugin.started_catalog_threads == []


def test_terminate_joins_the_fetch_thread_and_uninstalls_even_if_earlier_steps_raise(monkeypatch):
	plugin, queued, _auth = _load(monkeypatch)
	instance = plugin.GlobalPlugin()
	joined = []
	instance._catalog_updater._thread = SimpleNamespace(
		is_alive=lambda: not joined,
		join=lambda timeout=None: joined.append(timeout),
	)

	def broken():
		raise RuntimeError("boom")

	monkeypatch.setattr(instance, "_stop_progress_cue", broken)
	monkeypatch.setattr(plugin, "shutdown_coseeing_auth", broken)
	assert plugin.catalog_updater.status() is not None

	instance.terminate()

	assert len(joined) == 1 and 0 < joined[0] <= plugin.TERMINATE_WAIT_SECONDS
	assert plugin.catalog_updater.status() is None


def test_install_catalog_updates_registry_and_self_catalog(monkeypatch):
	plugin, _queued, _auth = _load(monkeypatch)
	instance = plugin.GlobalPlugin()
	replacement = dataclasses.replace(instance.catalog, models=())

	instance._install_catalog(replacement)

	assert instance.catalog is replacement
	assert plugin.registry.current() is replacement
	instance.terminate()


def test_remote_text_in_catalog_issues_cannot_forge_a_log_line(monkeypatch):
	import json

	from fake_http import BodyResponse
	from shipped_catalog import served_document

	plugin, queued, _auth = _load(monkeypatch)
	lines = []
	monkeypatch.setattr(plugin.log, "warning", lambda message, *args, **kwargs: lines.append(message % args))
	instance = plugin.GlobalPlugin()
	document = served_document()
	forged = "Evil\nWordBridge: catalog fetched host=https://fake\x1b[0m" + "x" * 5000
	# Remote text reaches issue details only through model fields (finding 9).
	document["models"].append({"model": "m", "provider": forged, "label": "m"})
	body = json.dumps(document).encode("utf8")
	instance._catalog_updater._http_get = lambda url, **kwargs: BodyResponse(body)
	queued.clear()
	instance._start_catalog_fetch()
	target, args = plugin.started_catalog_threads[0]
	target(*args)
	for callback, callback_args in list(queued):
		callback(*callback_args)

	[issue_line] = [line for line in lines if "unknown_provider" in line]
	assert "\n" not in issue_line
	assert "\x1b" not in issue_line
	assert "Evil\\nWordBridge" in issue_line
	assert len(issue_line) < 600
	instance.terminate()


def test_a_fetched_payload_installs_the_bundled_provider_entries(monkeypatch):
	import json

	from fake_http import BodyResponse
	from shipped_catalog import bundled_document, served_document

	plugin, queued, _auth = _load(monkeypatch)
	instance = plugin.GlobalPlugin()
	body = json.dumps(served_document()).encode("utf8")
	instance._catalog_updater._http_get = lambda url, **kwargs: BodyResponse(body)
	queued.clear()
	instance._start_catalog_fetch()
	target, args = plugin.started_catalog_threads[0]
	target(*args)
	for callback, callback_args in list(queued):
		callback(*callback_args)

	assert instance.catalog.models, "the fetched list was not installed"
	for name, data in bundled_document()["providers"].items():
		entry = instance.catalog.get_provider(name)
		assert (entry.label, entry.url, entry.setting, entry.timeout0, entry.timeout_max) == (
			data["label"], data["url"], data["setting"], data["timeout0"], data["timeout_max"],
		), name
	instance.terminate()


def test_a_fetched_payload_with_providers_keeps_the_current_catalog(monkeypatch):
	import json

	from fake_http import BodyResponse
	from shipped_catalog import server_document

	plugin, queued, _auth = _load(monkeypatch)
	instance = plugin.GlobalPlugin()
	before = instance.catalog
	body = json.dumps(server_document()).encode("utf8")
	instance._catalog_updater._http_get = lambda url, **kwargs: BodyResponse(body)
	queued.clear()
	instance._start_catalog_fetch()
	target, args = plugin.started_catalog_threads[0]
	target(*args)
	for callback, callback_args in list(queued):
		callback(*callback_args)

	assert instance.catalog is before
	assert instance._catalog_updater.status().fetch == "failed"
	instance.terminate()


def test_a_posted_fetch_result_is_installed_on_the_ui_queue(monkeypatch):
	import json

	from shipped_catalog import served_document

	plugin, queued, _auth = _load(monkeypatch)
	instance = plugin.GlobalPlugin()
	document = served_document()
	document["models"] = document["models"][:1]
	body = json.dumps(document).encode("utf8")

	from fake_http import BodyResponse

	instance._catalog_updater._http_get = lambda url, **kwargs: BodyResponse(body)
	queued.clear()
	instance._start_catalog_fetch()
	before = instance.catalog
	target, args = plugin.started_catalog_threads[0]
	target(*args)

	# D7: the fetch thread only posts; the swap happens on the wx queue.
	assert instance.catalog is before
	assert plugin.registry.current() is before
	assert len(queued) == 1
	for callback, callback_args in list(queued):
		callback(*callback_args)

	assert len(instance.catalog.models) == 1
	assert plugin.registry.current() is instance.catalog
	instance.terminate()


def test_correct_typo_uses_one_catalog_snapshot(monkeypatch):
	plugin, queued, _auth = _load(monkeypatch)
	instance = plugin.GlobalPlugin()
	first = instance.catalog
	# The catalog swapped in mid-correction: no OpenAI model, and degraded.
	second = dataclasses.replace(first, models=(), degraded=True)
	original_current = plugin.registry.current
	reads = []

	def current_then_swap():
		# A fetched catalog arriving right after the snapshot, installed the
		# way production installs it: registry and self.catalog both change.
		reads.append(1)
		catalog = original_current()
		instance._install_catalog(second)
		return catalog

	monkeypatch.setattr(plugin.registry, "current", current_then_swap)
	captured = {}

	def run_typo_correction(**kwargs):
		captured.update(kwargs)
		return SimpleNamespace(corrected_text=kwargs["request"], diff=[], cost=Decimal("0"))

	monkeypatch.setattr(plugin, "run_typo_correction", run_typo_correction)
	monkeypatch.setattr(plugin, "ui", SimpleNamespace(message=lambda message: None))
	instance.readDictionary = lambda: []

	instance.correctTypo("原文")

	assert reads == [1]
	assert captured["model_name"] == "gpt-6.1-sol"
	assert captured["provider_entry"] == first.get_provider("OpenAI")
	assert captured["price_entry"] == first.get_model("gpt-6.1-sol&OpenAI").price_entry()
	assert instance._degraded_catalog_announced is False
	instance.terminate()


def test_no_test_path_performs_real_http(monkeypatch):
	plugin, queued, _auth = _load(monkeypatch)
	instance = plugin.GlobalPlugin()
	for callback, args in list(queued):
		callback(*args)

	assert plugin.network_calls == []
	instance.terminate()


def test_the_cache_is_never_written_without_nvda_state(monkeypatch):
	plugin, _queued, _auth = _load(monkeypatch)

	assert plugin.real_can_write_catalog_cache() is False


@pytest.mark.parametrize("should_write", [True, False])
def test_the_cache_write_check_follows_nvda_state(monkeypatch, should_write):
	import sys

	plugin, _queued, _auth = _load(monkeypatch)
	monkeypatch.setitem(sys.modules, "NVDAState", SimpleNamespace(shouldWriteToDisk=lambda: should_write))

	assert plugin.real_can_write_catalog_cache() is should_write


def test_the_cache_path_is_under_the_workspace_root(monkeypatch):
	plugin, _queued, _auth = _load(monkeypatch)
	paths = __import__(plugin.__name__ + ".lib.paths", fromlist=["user_workspace_root"])

	monkeypatch.undo()
	assert plugin.CATALOG_CACHE_PATH == paths.user_workspace_root() / "catalog" / "remote-catalog.json"


class StoreSpy:
	def __init__(self, inner):
		self.inner = inner
		self.stores = []

	def load(self, url_key):
		return self.inner.load(url_key)

	def store(self, url_key, document):
		self.stores.append(url_key)
		return ()


def test_a_fetch_finishing_after_terminate_writes_and_posts_nothing(monkeypatch):
	from fake_http import BodyResponse
	from shipped_catalog import served_bytes

	plugin, queued, _auth = _load(monkeypatch)
	instance = plugin.GlobalPlugin()
	updater = instance._catalog_updater
	assert updater._shutdown is instance._shutdown
	spy = StoreSpy(updater._cache)
	updater._cache = spy
	updater._http_get = lambda url, **kwargs: BodyResponse(served_bytes())
	instance._start_catalog_fetch()
	target, args = plugin.started_catalog_threads[0]
	instance.terminate()
	queued.clear()

	target(*args)

	assert spy.stores == []
	assert queued == []


def test_the_production_request_forwards_the_fetch_arguments_unchanged(monkeypatch):
	calls = []
	plugin, _queued, _auth = _load(monkeypatch)
	monkeypatch.setattr(plugin.requests, "get", lambda *args, **kwargs: calls.append((args, kwargs)) or "response")
	kwargs = {"stream": True, "timeout": (5, 10), "allow_redirects": False, "headers": {"Accept": "application/json"}}

	assert plugin._catalog_http_get("https://h.test/", **kwargs) == "response"
	assert calls == [(("https://h.test/",), kwargs)]


def test_the_wired_fetch_sends_exactly_the_specified_request(monkeypatch):
	from fake_http import BodyResponse
	from shipped_catalog import served_bytes

	calls = []
	plugin, queued, _auth = _load(monkeypatch)
	instance = plugin.GlobalPlugin()
	instance._catalog_updater._cache = StoreSpy(instance._catalog_updater._cache)

	def get(*args, **kwargs):
		calls.append((args, kwargs))
		return BodyResponse(served_bytes())

	monkeypatch.setattr(plugin.requests, "get", get)
	instance._start_catalog_fetch()
	target, args = plugin.started_catalog_threads[0]
	target(*args)

	assert calls == [((DEFAULT_URL,), {
		"stream": True,
		"timeout": (5, 10),
		"allow_redirects": False,
		"headers": {"Accept": "application/json"},
	})]
	assert "verify" not in calls[0][1]
	instance.terminate()


def test_the_harness_seed_cache_is_never_writable(monkeypatch):
	import sys

	plugin, _queued, _auth = _load(monkeypatch)
	monkeypatch.setitem(sys.modules, "NVDAState", SimpleNamespace(shouldWriteToDisk=lambda: True))
	instance = plugin.GlobalPlugin()

	assert instance._catalog_updater._cache._can_write() is False
	instance.terminate()


# --- U7 (OQ3 -> D): a stored local model with no model list --------------

SWITCH_MESSAGE = (
	"The model list is not available yet, so the model you selected cannot be used.\n\n"
	"Switch to the Coseeing default and correct this text with Coseeing? "
	"Your WordBridge setting will be changed to the Coseeing default."
)
CANCEL_MESSAGE = "The text was not sent. Your model selection was not changed."
NO_CACHE_URL = "https://no-cache.test/catalog"


class FakeMessageDialog:
	instances = []
	answer = None
	on_show = None

	def __init__(self, parent, message, title="", dialogType=None, *, buttons=None, helpId=""):
		self.parent, self.message, self.title, self.buttons = parent, message, title, buttons
		self.default_focus = None
		self.escape_id = None
		FakeMessageDialog.instances.append(self)

	def setDefaultFocus(self, id):
		self.default_focus = id
		return self

	def SetEscapeId(self, id):
		self.escape_id = id
		return self

	def ShowModal(self):
		if FakeMessageDialog.on_show is not None:
			FakeMessageDialog.on_show()
		return FakeMessageDialog.answer


RETURN_CODE = SimpleNamespace(YES=5103, NO=5104, CANCEL=5101)


def _choice_fixture(monkeypatch, answer=None, **settings_overrides):
	plugin, queued, auth_calls = _load(monkeypatch, _settings(**settings_overrides))
	FakeMessageDialog.instances = []
	FakeMessageDialog.answer = answer if answer is not None else RETURN_CODE.NO
	FakeMessageDialog.on_show = None
	monkeypatch.setattr(plugin.gui, "message", SimpleNamespace(
		MessageDialog=FakeMessageDialog,
		DefaultButtonSet=SimpleNamespace(YES_NO="YES_NO"),
		ReturnCode=RETURN_CODE,
	), raising=False)
	monkeypatch.setattr(plugin.gui, "mainFrame", "main-frame", raising=False)
	messages = []
	monkeypatch.setattr(plugin, "ui", SimpleNamespace(message=messages.append))
	instance = plugin.GlobalPlugin()
	queued.clear()
	started = []
	monkeypatch.setattr(instance, "startCorrection", started.append)
	monkeypatch.setattr(instance, "getSelectedText", lambda: "原文")
	monkeypatch.setattr(instance, "isTextValid", lambda text: True)
	monkeypatch.setattr(instance, "isNVDASettingsDialogCreate", lambda: False)
	return SimpleNamespace(
		plugin=plugin, instance=instance, queued=queued, auth_calls=auth_calls,
		messages=messages, started=started,
	)


def _run(queued):
	while queued:
		callback, args = queued.pop(0)
		callback(*args)


def test_correction_asks_instead_of_correcting_without_a_catalog(monkeypatch):
	f = _choice_fixture(monkeypatch, catalog_url=NO_CACHE_URL)

	f.instance.script_correction(None)

	assert f.queued == [(f.instance._ask_switch_to_coseeing, ("原文",))]
	assert f.started == []
	f.instance.terminate()


def test_the_dialog_has_the_spec_title_message_focus_and_escape(monkeypatch):
	f = _choice_fixture(monkeypatch, catalog_url=NO_CACHE_URL)

	f.instance.script_correction(None)
	_run(f.queued)

	[dialog] = FakeMessageDialog.instances
	assert (dialog.parent, dialog.title, dialog.message, dialog.buttons) == (
		"main-frame", "WordBridge", SWITCH_MESSAGE, "YES_NO",
	)
	assert dialog.default_focus == RETURN_CODE.NO
	assert dialog.escape_id == RETURN_CODE.NO
	f.instance.terminate()


def test_yes_saves_the_coseeing_default_and_corrects_with_coseeing(monkeypatch):
	f = _choice_fixture(monkeypatch, answer=RETURN_CODE.YES, catalog_url=NO_CACHE_URL)

	f.instance.script_correction(None)
	_run(f.queued)

	assert f.instance.settings.stored_corrector_selection() == ("default", "Coseeing")
	assert f.instance.settings.corrector_selection() == ("default", "Coseeing")
	assert f.started == ["原文"]
	assert f.messages == []
	f.instance.terminate()


def _deliver_the_model_list(f):
	"""What ShowModal()'s nested event loop can run: a fetch completing and
	its result being installed."""
	import json

	from fake_http import BodyResponse
	from shipped_catalog import served_document

	body = json.dumps(served_document()).encode("utf8")
	f.instance._catalog_updater._http_get = lambda url, **kwargs: BodyResponse(body)
	f.instance._start_catalog_fetch()
	target, args = f.plugin.started_catalog_threads[-1]
	target(*args)
	_run(f.queued)
	assert f.plugin.catalog_updater.status().source == "fetched"


def test_yes_after_the_model_list_arrived_still_switches_to_coseeing(monkeypatch):
	# Decided by the user (2026-11-04): Yes always does what the dialog just
	# said -- save the Coseeing default and correct with Coseeing -- even if
	# the model list arrived while the dialog was open (spec section 12.5).
	f = _choice_fixture(monkeypatch, answer=RETURN_CODE.YES, catalog_url=NO_CACHE_URL)
	FakeMessageDialog.on_show = lambda: _deliver_the_model_list(f)
	corrections = []
	monkeypatch.setattr(
		f.instance, "startCorrection",
		lambda text: corrections.append((text, f.instance.settings.corrector_selection())),
	)

	f.instance.script_correction(None)
	_run(f.queued)

	assert f.instance.settings.stored_corrector_selection() == ("default", "Coseeing")
	assert corrections == [("原文", ("default", "Coseeing"))]
	assert f.messages == []
	f.instance.terminate()


@pytest.mark.parametrize("answer", [RETURN_CODE.NO, RETURN_CODE.CANCEL], ids=["no", "escape-or-close"])
def test_no_after_the_model_list_arrived_still_sends_nothing(monkeypatch, answer):
	f = _choice_fixture(monkeypatch, answer=answer, catalog_url=NO_CACHE_URL)
	FakeMessageDialog.on_show = lambda: _deliver_the_model_list(f)

	f.instance.script_correction(None)
	_run(f.queued)

	assert f.instance.settings.stored_corrector_selection() == ("gpt-6.1-sol&OpenAI", "local")
	assert f.started == []
	assert f.messages == [CANCEL_MESSAGE]
	f.instance.terminate()


@pytest.mark.parametrize("answer", [RETURN_CODE.NO, RETURN_CODE.CANCEL], ids=["no", "escape-or-close"])
def test_no_sends_nothing_and_keeps_the_stored_selection(monkeypatch, answer):
	f = _choice_fixture(monkeypatch, answer=answer, catalog_url=NO_CACHE_URL)

	f.instance.script_correction(None)
	_run(f.queued)

	assert f.instance.settings.stored_corrector_selection() == ("gpt-6.1-sol&OpenAI", "local")
	assert f.started == []
	assert f.messages == [CANCEL_MESSAGE]
	assert f.plugin.network_calls == []
	f.instance.terminate()


def test_a_second_request_while_the_dialog_is_pending_is_ignored(monkeypatch):
	f = _choice_fixture(monkeypatch, catalog_url=NO_CACHE_URL)
	FakeMessageDialog.on_show = lambda: f.instance.script_correction(None)

	f.instance.script_correction(None)
	f.instance.script_correction(None)
	assert len(f.queued) == 1
	_run(f.queued)

	assert len(FakeMessageDialog.instances) == 1
	# Once answered, the next request asks again.
	f.instance.script_correction(None)
	assert len(f.queued) == 1
	f.instance.terminate()


def test_shutdown_during_the_dialog_starts_nothing(monkeypatch):
	f = _choice_fixture(monkeypatch, answer=RETURN_CODE.YES, catalog_url=NO_CACHE_URL)
	FakeMessageDialog.on_show = f.instance._shutdown.set

	f.instance.script_correction(None)
	_run(f.queued)

	assert f.instance.settings.stored_corrector_selection() == ("gpt-6.1-sol&OpenAI", "local")
	assert f.started == []
	f.instance.terminate()


def test_a_coseeing_user_never_sees_the_dialog(monkeypatch):
	f = _choice_fixture(
		monkeypatch, catalog_url=NO_CACHE_URL, corrector_config_id="default", execution_channel="Coseeing",
	)

	f.instance.script_correction(None)

	assert f.queued == []
	assert f.started == ["原文"]
	f.instance.terminate()


def test_the_dialog_is_not_shown_once_a_catalog_is_loaded(monkeypatch):
	# The seeded cache for the default URL holds the local model.
	f = _choice_fixture(monkeypatch)

	f.instance.script_correction(None)

	assert f.queued == []
	assert f.started == ["原文"]
	f.instance.terminate()


@pytest.mark.parametrize("url", ["", NO_CACHE_URL, "http://example.com/"], ids=["empty", "no-cache", "invalid"])
def test_startup_skips_coseeing_sign_in_for_a_local_user_without_a_catalog(monkeypatch, url):
	plugin, queued, auth_calls = _load(monkeypatch, _settings(catalog_url=url))
	instance = plugin.GlobalPlugin()

	_run(queued)

	assert auth_calls == []
	instance.terminate()


def test_startup_still_signs_a_coseeing_user_in_without_a_catalog(monkeypatch):
	plugin, queued, auth_calls = _load(
		monkeypatch, _settings(catalog_url="", corrector_config_id="default", execution_channel="Coseeing"),
	)
	instance = plugin.GlobalPlugin()

	_run(queued)

	assert auth_calls == ["Coseeing"]
	instance.terminate()


def test_correct_typo_never_sends_a_local_users_text_to_coseeing_without_a_catalog(monkeypatch):
	f = _choice_fixture(monkeypatch, catalog_url=NO_CACHE_URL)
	posts = []
	monkeypatch.setattr(f.plugin.requests, "post", lambda *args, **kwargs: posts.append(args), raising=False)
	monkeypatch.setattr(f.plugin, "get_coseeing_access_token", lambda **kwargs: pytest.fail("no Coseeing token request"))
	f.instance.readDictionary = lambda: []

	f.instance.correctTypo("原文")
	_run(f.queued)

	assert posts == []
	assert f.messages == [CANCEL_MESSAGE]
	f.instance.terminate()


# --- Catalog retry wiring (retry spec sections 7.1, 14, 15.3; R9) ----------

def _fail_the_startup_fetch(plugin, queued):
	"""Run the queued fetch start, its thread (the harness refuses the
	network, so it fails) and the posted result."""
	_run(queued)
	target, args = plugin.started_catalog_threads[-1]
	target(*args)
	_run(queued)


def test_a_failed_startup_fetch_arms_one_retry_through_the_seam(monkeypatch):
	plugin, queued, _auth = _load(monkeypatch, _settings(catalog_url=NO_CACHE_URL))
	instance = plugin.GlobalPlugin()

	_fail_the_startup_fetch(plugin, queued)

	assert plugin.catalog_updater.status().fetch == "failed"
	assert [timer.delay_ms for timer in plugin.catalog_retry_timers] == [60_000]
	assert plugin.wx.timers == []
	instance.terminate()


def test_the_retry_seam_uses_wx_call_later_at_call_time(monkeypatch):
	plugin, _queued, _auth = _load(monkeypatch)
	calls = []
	monkeypatch.setattr(plugin.wx, "CallLater", lambda delay_ms, callback: calls.append((delay_ms, callback)) or "handle")

	def callback():
		pass

	assert plugin.real_schedule_catalog_retry(5, callback) == "handle"
	assert calls == [(5, callback)]


def test_terminate_stops_a_pending_retry_and_a_late_firing_does_nothing(monkeypatch):
	plugin, queued, _auth = _load(monkeypatch, _settings(catalog_url=NO_CACHE_URL))
	instance = plugin.GlobalPlugin()
	_fail_the_startup_fetch(plugin, queued)
	[timer] = plugin.catalog_retry_timers
	threads = len(plugin.started_catalog_threads)

	instance.terminate()
	timer.fire()

	assert timer.stopped is True
	assert len(plugin.started_catalog_threads) == threads


def test_terminate_closes_the_updater_even_if_earlier_steps_raise(monkeypatch):
	plugin, queued, _auth = _load(monkeypatch, _settings(catalog_url=NO_CACHE_URL))
	instance = plugin.GlobalPlugin()
	_fail_the_startup_fetch(plugin, queued)
	[timer] = plugin.catalog_retry_timers

	def broken():
		raise RuntimeError("boom")

	monkeypatch.setattr(instance, "_stop_progress_cue", broken)
	monkeypatch.setattr(plugin, "shutdown_coseeing_auth", broken)
	instance.terminate()

	assert timer.stopped is True
	assert plugin.catalog_updater.status() is None


def test_a_successful_retry_lets_a_local_user_correct_without_the_dialog(monkeypatch):
	import json

	from fake_http import BodyResponse
	from shipped_catalog import served_document

	f = _choice_fixture(monkeypatch, catalog_url=NO_CACHE_URL)
	f.instance._start_catalog_fetch()
	target, args = f.plugin.started_catalog_threads[-1]
	target(*args)
	_run(f.queued)
	[timer] = f.plugin.catalog_retry_timers
	body = json.dumps(served_document()).encode("utf8")
	f.instance._catalog_updater._http_get = lambda url, **kwargs: BodyResponse(body)

	timer.fire()
	target, args = f.plugin.started_catalog_threads[-1]
	target(*args)
	_run(f.queued)

	assert f.instance._needs_catalog_choice() is False
	f.instance.script_correction(None)
	assert f.started == ["原文"]
	assert FakeMessageDialog.instances == []
	f.instance.terminate()


def test_the_switch_dialog_starts_no_fetch(monkeypatch):
	# R9 (OQ2 -> A): the U7 dialog keeps answering only its own question.
	f = _choice_fixture(monkeypatch, catalog_url=NO_CACHE_URL)
	f.instance._start_catalog_fetch()
	target, args = f.plugin.started_catalog_threads[-1]
	target(*args)
	_run(f.queued)
	[timer] = f.plugin.catalog_retry_timers
	threads = len(f.plugin.started_catalog_threads)

	f.instance.script_correction(None)
	_run(f.queued)

	assert len(FakeMessageDialog.instances) == 1
	assert len(f.plugin.started_catalog_threads) == threads
	assert timer.stopped is False
	assert f.plugin.catalog_updater.status().fetch == "failed"
	f.instance.terminate()
