"""The settings panel's model list URL field and status line (spec section 13).

_load_nvda_plugin and the widget stubs are imported at function scope, never
at module scope (importing test_coseeing_auth_nvda at collection time poisons
coseeing_auth).
"""

from types import SimpleNamespace

import pytest


DEFAULT_URL = "https://wordbridge.coseeing.org"
MALFORMED = "Enter a complete web address, such as https://wordbridge.coseeing.org, or leave the field empty."
INSECURE = "The model list URL must start with https://. http:// is allowed only for localhost."


def _panel_fixture(monkeypatch, **settings_overrides):
	from test_coseeing_auth_nvda import (
		_install_settings_panel_widget_stubs,
		_load_nvda_plugin,
		_make_panel,
		_panel_settings,
	)

	queued = []
	auth_calls = []
	settings = _panel_settings(**settings_overrides)
	plugin, config, gui = _load_nvda_plugin(monkeypatch, settings, auth_calls, queued)
	dialogs = plugin.dialogs
	helper_calls, _captions, Sizer = _install_settings_panel_widget_stubs(monkeypatch, plugin, gui, config)
	monkeypatch.setattr(dialogs, "has_saved_coseeing_refresh_token", lambda: False)

	def make_panel():
		plugin.panel_added_controls.clear()
		helper_calls.clear()
		return _make_panel(monkeypatch, dialogs, Sizer)

	return SimpleNamespace(
		plugin=plugin, dialogs=dialogs, settings=settings, queued=queued, auth_calls=auth_calls,
		helper_calls=helper_calls, make_panel=make_panel,
	)


def _status(dialogs, source, fetch):
	return dialogs.catalog_updater.UpdaterStatus(source=source, fetch=fetch)


def _save(panel):
	panel.onSave()


def test_the_url_field_is_the_last_control_with_the_stored_value(monkeypatch):
	f = _panel_fixture(monkeypatch, catalog_url="http://localhost:8000")

	panel = f.make_panel()

	assert f.plugin.panel_added_controls[-1] is panel.catalogUrlCtrl
	label, control_type, kwargs = f.helper_calls[-1]
	assert label == "Model list URL:"
	assert control_type is f.plugin.wx.TextCtrl
	assert kwargs["value"] == "http://localhost:8000"
	assert kwargs["size"] == (375, -1)


def test_the_url_field_shows_the_default_when_nothing_is_stored(monkeypatch):
	f = _panel_fixture(monkeypatch)

	panel = f.make_panel()

	assert panel.catalogUrlCtrl.GetValue() == DEFAULT_URL


@pytest.mark.parametrize("text, message", [("ftp://x", MALFORMED), ("http://example.com", INSECURE)])
def test_is_valid_rejects_a_bad_url_with_nvdas_message_box(monkeypatch, text, message):
	f = _panel_fixture(monkeypatch)
	panel = f.make_panel()
	calls = []
	panel._validationErrorMessageBox = lambda **kwargs: calls.append(kwargs)
	panel.catalogUrlCtrl.SetValue(text)

	assert panel.isValid() is False
	assert calls == [{"message": message, "option": "Model list URL"}]
	assert getattr(panel.catalogUrlCtrl, "focused", False) is True


def test_is_valid_defers_to_nvdas_settings_panel_for_a_valid_url(monkeypatch):
	f = _panel_fixture(monkeypatch)
	panel = f.make_panel()
	parent = f.dialogs.LLMSettingsPanel.__mro__[1]
	monkeypatch.setattr(parent, "isValid", lambda self: False)

	assert panel.isValid() is False


@pytest.mark.parametrize("text", ["", "   ", DEFAULT_URL, "http://localhost:8000"])
def test_is_valid_accepts_empty_default_and_loopback(monkeypatch, text):
	f = _panel_fixture(monkeypatch)
	panel = f.make_panel()
	panel._validationErrorMessageBox = lambda **kwargs: pytest.fail("no message box for a valid URL")
	panel.catalogUrlCtrl.SetValue(text)

	assert panel.isValid() is True


@pytest.mark.parametrize("typed", [DEFAULT_URL, "  HTTPS://WORDBRIDGE.COSEEING.ORG/  "])
def test_an_unchanged_url_saves_nothing_and_triggers_no_refresh(monkeypatch, typed):
	f = _panel_fixture(monkeypatch)
	panel = f.make_panel()
	panel.catalogUrlCtrl.SetValue(typed)
	f.queued.clear()

	_save(panel)

	assert "catalog_url" not in f.settings
	assert not [call for call in f.queued if call[0] == f.dialogs.catalog_updater.request_refresh]


def test_a_changed_url_saves_the_stripped_text_and_schedules_one_refresh(monkeypatch):
	f = _panel_fixture(monkeypatch)
	panel = f.make_panel()
	panel.catalogUrlCtrl.SetValue("  http://localhost:8000  ")
	f.queued.clear()

	_save(panel)

	assert f.settings["catalog_url"] == "http://localhost:8000"
	refreshes = [call for call in f.queued if call[0] == f.dialogs.catalog_updater.request_refresh]
	assert refreshes == [(f.dialogs.catalog_updater.request_refresh, ("http://localhost:8000",))]


def test_clearing_an_invalid_stored_url_saves_the_empty_value(monkeypatch):
	# Both an invalid and an empty URL have no key; clearing a hand-edited
	# bad value must still be saved.
	f = _panel_fixture(monkeypatch, catalog_url="http://example.com")
	panel = f.make_panel()
	panel.catalogUrlCtrl.SetValue("")
	f.queued.clear()

	_save(panel)

	assert f.settings["catalog_url"] == ""
	assert [call for call in f.queued if call[0] == f.dialogs.catalog_updater.request_refresh] == [
		(f.dialogs.catalog_updater.request_refresh, ("",)),
	]


STATUS_TABLE = [
	("off", "none", "off", "The model list URL is empty, so only the Coseeing default is available."),
	("invalid", "none", "invalid", "The model list URL is invalid, so no model list was loaded."),
	("loading", "none", "running", "The model list is still loading. Until it loads, only the Coseeing default is available."),
	("failed", "none", "failed", "The model list could not be loaded, so only the Coseeing default is available. See the NVDA log for details."),
	("stale", "cache", "failed", "The model list could not be updated. WordBridge is using the list it saved earlier."),
	("cache-running", "cache", "running", None),
	("fetched", "fetched", "succeeded", None),
]


@pytest.mark.parametrize("source, fetch, message", [row[1:] for row in STATUS_TABLE], ids=[row[0] for row in STATUS_TABLE])
def test_catalog_status_message_table(monkeypatch, source, fetch, message):
	f = _panel_fixture(monkeypatch)

	assert f.dialogs.catalog_status_message(_status(f.dialogs, source, fetch)) == message


def test_no_status_message_without_an_updater(monkeypatch):
	f = _panel_fixture(monkeypatch)

	assert f.dialogs.catalog_status_message(None) is None


def test_the_status_line_is_shown_after_the_dropped_entries_line_and_before_the_provider_list(monkeypatch):
	f = _panel_fixture(monkeypatch)
	monkeypatch.setattr(f.dialogs.catalog_updater, "status", lambda: _status(f.dialogs, "none", "failed"))

	panel = f.make_panel()

	assert panel.catalogStatusText is not None
	assert panel.catalogStatusText.label == STATUS_TABLE[3][3]
	controls = f.plugin.panel_added_controls
	assert controls.index(panel.catalogStatusText) < controls.index(panel.providerList)


def _line_shown(panel, line):
	return panel.settingsSizer.IsShown(line)


def test_no_status_line_when_the_list_is_fresh(monkeypatch):
	f = _panel_fixture(monkeypatch)
	monkeypatch.setattr(f.dialogs.catalog_updater, "status", lambda: _status(f.dialogs, "fetched", "succeeded"))

	panel = f.make_panel()

	assert panel.catalogStatusText.label == ""
	assert _line_shown(panel, panel.catalogStatusText) is False


def test_the_dropped_entries_line_is_silent_for_the_shipped_overlay(monkeypatch):
	f = _panel_fixture(monkeypatch)

	panel = f.make_panel()

	assert panel.catalogIssuesText.label == ""
	assert _line_shown(panel, panel.catalogIssuesText) is False


@pytest.mark.parametrize("source, fetch, message", [row[1:] for row in STATUS_TABLE], ids=[row[0] for row in STATUS_TABLE])
def test_the_panel_description_is_the_status_line(monkeypatch, source, fetch, message):
	# R11: NVDA reads panelDescription as the property page's description
	# when focus enters the panel (gui/settingsDialogs.py:504-505).
	f = _panel_fixture(monkeypatch)
	monkeypatch.setattr(f.dialogs.catalog_updater, "status", lambda: _status(f.dialogs, source, fetch))

	panel = f.make_panel()

	assert panel.panelDescription == (message or "")
	assert panel.catalogStatusText.label == (message or "")
	assert _line_shown(panel, panel.catalogStatusText) is (message is not None)


def test_both_lines_exist_in_their_place_when_empty(monkeypatch):
	f = _panel_fixture(monkeypatch)
	monkeypatch.setattr(f.dialogs.catalog_updater, "status", lambda: _status(f.dialogs, "fetched", "succeeded"))

	panel = f.make_panel()

	controls = f.plugin.panel_added_controls
	assert controls.index(panel.catalogIssuesText) < controls.index(panel.catalogStatusText) < controls.index(panel.providerList)
	assert not _line_shown(panel, panel.catalogIssuesText)
	assert not _line_shown(panel, panel.catalogStatusText)


class _Log:
	def __init__(self):
		self.records = []

	def info(self, *args):
		self.records.append(args)

	warning = info


def real_updater(f, tmp_path, http_get, schedule=None):
	"""The plugin package's own CatalogUpdater with fakes at its edges:
	threads are recorded, posted results are queued in `updater.posted`."""
	import threading

	module = f.dialogs.catalog_updater
	cache_module = __import__(f.plugin.__name__ + ".lib.catalog.cache", fromlist=["CatalogCache"])
	threads = []
	posted = []
	installed = []

	def install(catalog):
		installed.append(catalog)
		f.dialogs.registry.replace(catalog)

	updater = module.CatalogUpdater(
		bundled_source=f.plugin.BundledCatalogSource(str(f.plugin.PATH) + "/setting"),
		cache=cache_module.CatalogCache(tmp_path / "catalog" / "remote-catalog.json", can_write=lambda: False),
		runnable_providers=f.plugin.SUPPORTED_PROVIDERS,
		http_get=http_get,
		post_to_ui=lambda function, *args: posted.append((function, args)),
		install=install,
		shutdown=threading.Event(),
		log=_Log(),
		start_thread=lambda target, args: threads.append((target, args)) or SimpleNamespace(is_alive=lambda: False),
		schedule=schedule,
	)
	updater.threads, updater.posted, updater.installed = threads, posted, installed

	def run_latest():
		target, args = threads[-1]
		target(*args)
		queue, posted[:] = list(posted), []
		for function, args in queue:
			function(*args)

	updater.run_latest = run_latest
	return updater


def _refuse(url, **kwargs):
	raise OSError("offline")


def _serve_the_server_catalog(url, **kwargs):
	import json

	from fake_http import BodyResponse
	from shipped_catalog import server_document

	return BodyResponse(json.dumps(server_document()).encode("utf8"))


@pytest.mark.parametrize("state, new_threads", [("failed", 1), ("succeeded", 0), ("running", 0)])
def test_opening_the_panel_retries_only_after_a_failure(monkeypatch, tmp_path, state, new_threads):
	f = _panel_fixture(monkeypatch)
	updater = real_updater(f, tmp_path, _serve_the_server_catalog if state == "succeeded" else _refuse)
	updater.initial_catalog(DEFAULT_URL)
	updater.refresh(DEFAULT_URL)
	if state != "running":
		updater.run_latest()
	f.dialogs.catalog_updater.install(updater)
	threads = len(updater.threads)
	try:
		panel = f.make_panel()
	finally:
		f.dialogs.catalog_updater.uninstall()

	assert len(updater.threads) - threads == new_threads
	if state == "failed":
		# R1 ran before the status was read: the panel opens on "loading".
		assert panel.catalogStatusText.label == STATUS_TABLE[2][3]


def _bundled_only(f):
	overlay = __import__(f.plugin.__name__ + ".lib.catalog.overlay", fromlist=["load_overlay_catalog"])
	return overlay.load_overlay_catalog(
		f.plugin.BundledCatalogSource(str(f.plugin.PATH) + "/setting"), None,
		runnable_providers=f.plugin.SUPPORTED_PROVIDERS,
	)


def _run_queued(f):
	for callback, args in list(f.queued):
		callback(*args)
	f.queued.clear()


def test_an_unresolved_stored_selection_survives_an_untouched_save(monkeypatch):
	# Offline with no cache: the stored local model is not in the catalog.
	f = _panel_fixture(monkeypatch, corrector_config_id="gpt-6-luna&OpenAI", execution_channel="local")
	catalog = _bundled_only(f)
	monkeypatch.setattr(f.dialogs.registry, "current", lambda: catalog)
	panel = f.make_panel()
	panel.languageList.SetSelection(1)
	f.queued.clear()

	_save(panel)
	_run_queued(f)

	assert (f.settings["corrector_config_id"], f.settings["execution_channel"]) == ("gpt-6-luna&OpenAI", "local")
	assert f.settings["language"] == "zh_simplified"
	# The user's channel is still local: no Coseeing sign-in prompt.
	assert f.auth_calls == []


@pytest.mark.parametrize("catalog_kind", ["shipped", "bundled-only"])
def test_a_fresh_install_untouched_save_stores_the_default_and_signs_in(monkeypatch, catalog_kind):
	# Nothing stored yet (a fresh nvda.ini): there is nothing for D12 to
	# protect, so OK on the untouched panel behaves as on main -- the default
	# Coseeing selection is written and the interactive Coseeing sign-in runs.
	f = _panel_fixture(monkeypatch)
	assert (f.settings["corrector_config_id"], f.settings["execution_channel"]) == ("", "")
	if catalog_kind == "bundled-only":
		catalog = _bundled_only(f)
		monkeypatch.setattr(f.dialogs.registry, "current", lambda: catalog)
	panel = f.make_panel()
	f.queued.clear()

	_save(panel)
	_run_queued(f)

	assert (f.settings["corrector_config_id"], f.settings["execution_channel"]) == ("default", "Coseeing")
	assert f.auth_calls == ["Coseeing"]


@pytest.mark.parametrize("catalog_kind", ["shipped", "bundled-only"])
def test_an_upgrader_with_only_a_stored_id_saves_the_default_and_signs_in(monkeypatch, catalog_kind):
	# NVDA does not write a value equal to the spec default, and 2026.9.3
	# defaulted execution_channel to "Coseeing": a user who chose Coseeing
	# GPT-5.6 Luna there is stored with an empty channel. As on main, OK on
	# the untouched panel stores the shown default and signs in to Coseeing.
	f = _panel_fixture(monkeypatch, corrector_config_id="gpt-5.6-luna&OpenAI", execution_channel="")
	if catalog_kind == "bundled-only":
		catalog = _bundled_only(f)
		monkeypatch.setattr(f.dialogs.registry, "current", lambda: catalog)
	panel = f.make_panel()
	f.queued.clear()

	_save(panel)
	_run_queued(f)

	assert (f.settings["corrector_config_id"], f.settings["execution_channel"]) == ("default", "Coseeing")
	assert f.auth_calls == ["Coseeing"]


@pytest.mark.parametrize("catalog_kind", ["shipped", "bundled-only"])
def test_an_upgrader_with_only_a_stored_local_channel_keeps_it(monkeypatch, catalog_kind):
	# 2026.9.3's default id was deepseek-v4-flash&DeepSeek, so a user who
	# chose it on the local channel is stored as ("", "local"). That is a
	# local user: D12 and U7 keep the stored selection and sign in to nothing.
	f = _panel_fixture(monkeypatch, corrector_config_id="", execution_channel="local")
	if catalog_kind == "bundled-only":
		catalog = _bundled_only(f)
		monkeypatch.setattr(f.dialogs.registry, "current", lambda: catalog)
	panel = f.make_panel()
	f.queued.clear()

	_save(panel)
	_run_queued(f)

	assert (f.settings["corrector_config_id"], f.settings["execution_channel"]) == ("", "local")
	assert f.auth_calls == []


def test_a_changed_choice_overwrites_the_unresolved_selection(monkeypatch):
	# A retired local model: unresolved, shown as the Coseeing default.
	f = _panel_fixture(monkeypatch, corrector_config_id="gpt-retired&OpenAI", execution_channel="local")
	panel = f.make_panel()
	openai = f.plugin.catalog.provider_groups.index("OpenAI")
	panel.providerList.SetSelection(openai)
	panel.modelList.SetSelection(0)
	f.queued.clear()

	_save(panel)
	_run_queued(f)

	first_openai = f.plugin.catalog.items_for("OpenAI")[0]
	assert (f.settings["corrector_config_id"], f.settings["execution_channel"]) == (
		first_openai.corrector_config_id, "local",
	)
	assert f.auth_calls == []


def test_choosing_coseeing_explicitly_saves_it_and_signs_in(monkeypatch):
	f = _panel_fixture(monkeypatch, corrector_config_id="gpt-6.1-sol&OpenAI", execution_channel="local")
	panel = f.make_panel()
	panel.providerList.SetSelection(f.plugin.catalog.provider_groups.index("Coseeing"))
	panel.modelList.SetSelection(0)
	f.queued.clear()

	_save(panel)
	_run_queued(f)

	assert (f.settings["corrector_config_id"], f.settings["execution_channel"]) == ("default", "Coseeing")
	assert f.auth_calls == ["Coseeing"]


def test_a_resolved_selection_is_saved_as_before(monkeypatch):
	f = _panel_fixture(monkeypatch, corrector_config_id="gpt-6.1-sol&OpenAI", execution_channel="local")
	panel = f.make_panel()
	f.settings["corrector_config_id"] = "changed-behind-the-panel"

	_save(panel)

	assert (f.settings["corrector_config_id"], f.settings["execution_channel"]) == ("gpt-6.1-sol&OpenAI", "local")
