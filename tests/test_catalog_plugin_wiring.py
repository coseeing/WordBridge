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


def test_a_posted_fetch_result_is_installed_on_the_ui_queue(monkeypatch):
	import json

	from shipped_catalog import server_document

	plugin, queued, _auth = _load(monkeypatch)
	instance = plugin.GlobalPlugin()
	document = server_document()
	document["models"] = document["models"][:1]
	body = json.dumps(document).encode("utf8")

	class Response:
		status_code = 200
		headers = {}

		def __enter__(self):
			return self

		def __exit__(self, *exc):
			return False

		def iter_content(self, chunk_size):
			yield body

	instance._catalog_updater._http_get = lambda url, **kwargs: Response()
	queued.clear()
	instance._start_catalog_fetch()
	target, args = plugin.started_catalog_threads[0]
	target(*args)
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

	assert plugin._can_write_catalog_cache() is False


@pytest.mark.parametrize("should_write", [True, False])
def test_the_cache_write_check_follows_nvda_state(monkeypatch, should_write):
	import sys

	plugin, _queued, _auth = _load(monkeypatch)
	monkeypatch.setitem(sys.modules, "NVDAState", SimpleNamespace(shouldWriteToDisk=lambda: should_write))

	assert plugin._can_write_catalog_cache() is should_write


def test_the_cache_path_is_under_the_workspace_root(monkeypatch):
	plugin, _queued, _auth = _load(monkeypatch)
	paths = __import__(plugin.__name__ + ".lib.paths", fromlist=["user_workspace_root"])

	monkeypatch.undo()
	assert plugin.CATALOG_CACHE_PATH == paths.user_workspace_root() / "catalog" / "remote-catalog.json"
