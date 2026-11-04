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
	settings = _panel_settings(**settings_overrides)
	plugin, config, gui = _load_nvda_plugin(monkeypatch, settings, [], queued)
	dialogs = plugin.dialogs
	helper_calls, _captions, Sizer = _install_settings_panel_widget_stubs(monkeypatch, plugin, gui, config)
	monkeypatch.setattr(dialogs, "has_saved_coseeing_refresh_token", lambda: False)

	def make_panel():
		plugin.panel_added_controls.clear()
		helper_calls.clear()
		return _make_panel(monkeypatch, dialogs, Sizer)

	return SimpleNamespace(
		plugin=plugin, dialogs=dialogs, settings=settings, queued=queued,
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


def test_no_status_line_when_the_list_is_fresh(monkeypatch):
	f = _panel_fixture(monkeypatch)
	monkeypatch.setattr(f.dialogs.catalog_updater, "status", lambda: _status(f.dialogs, "fetched", "succeeded"))

	assert f.make_panel().catalogStatusText is None


def test_the_dropped_entries_line_is_silent_for_the_shipped_overlay(monkeypatch):
	f = _panel_fixture(monkeypatch)

	assert f.make_panel().catalogIssuesText is None
