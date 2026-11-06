"""The settings panel's model list URL group and status line (spec sections 13, 20).

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
		plugin=plugin,
		dialogs=dialogs,
		settings=settings,
		queued=queued,
		auth_calls=auth_calls,
		helper_calls=helper_calls,
		make_panel=make_panel,
	)


def _status(dialogs, source, fetch):
	return dialogs.catalog_updater.UpdaterStatus(source=source, fetch=fetch)


def _save(panel):
	panel.onSave()


# --- Task 14: the URL group (R12, C18, C20, spec 20.1/20.4) ----------------


@pytest.mark.parametrize(
	"stored, shown",
	[
		({"catalog_url": "http://localhost:8000"}, "http://localhost:8000"),
		({}, DEFAULT_URL),
		({"catalog_url": ""}, "No model list URL"),
	],
	ids=["stored", "default", "empty"],
)
def test_the_url_group_is_last_with_a_read_only_box_and_a_change_button(monkeypatch, stored, shown):
	f = _panel_fixture(monkeypatch, **stored)

	panel = f.make_panel()

	controls = f.plugin.panel_added_controls
	assert controls[-2:] == [panel.catalogUrlBox, panel.catalogUrlChangeButton]
	assert panel.catalogUrlBox.style & f.plugin.wx.TE_READONLY
	assert panel.catalogUrlBox.GetValue() == shown
	assert panel.catalogUrlChangeButton.label == "Change..."
	# As NVDA's update mirror group: both are children of the group's box.
	group = panel.settingsSizer.children[-1]
	assert group.GetStaticBox().label == "Model list URL"
	assert panel.catalogUrlBox.parent is group.GetStaticBox()
	assert panel.catalogUrlChangeButton.parent is group.GetStaticBox()
	assert "Model list URL:" not in [call[0] for call in f.helper_calls]
	assert not hasattr(panel, "catalogUrlCtrl")


def _group_holding(panel, control):
	return next(
		child
		for child in panel.settingsSizer.children
		if hasattr(child, "GetStaticBox") and control in child.children
	)


@pytest.mark.parametrize(
	"caption, members, labels",
	[
		(
			"Personal dictionary",
			("customizedWordEnable", "wordDictionaryCtrl"),
			["Apply personal dictionary", "Edit dictionary"],
		),
		(
			"Sound effects",
			("soundEffectsEnable", "soundEffectsCtrl"),
			["Enable sound effect cues", "Sound effect credits"],
		),
	],
	ids=["dictionary", "sound"],
)
def test_a_setting_and_its_button_share_a_group(monkeypatch, caption, members, labels):
	# As NVDA's "NVDA Development" group: the controls keep their full
	# labels and are children of the group's box.
	f = _panel_fixture(monkeypatch)

	panel = f.make_panel()

	controls = [getattr(panel, name) for name in members]
	group = _group_holding(panel, controls[0])
	assert group.GetStaticBox().label == caption
	assert group.children == controls
	assert [control.label for control in controls] == labels
	assert all(control.parent is group.GetStaticBox() for control in controls)


def test_the_account_box_controls_are_children_of_their_box(monkeypatch):
	f = _panel_fixture(monkeypatch)

	panel = f.make_panel()

	for group, sizer in panel.accountGroupSizerMap.items():
		control = panel.coseeingCleanButton if group == "Coseeing" else panel.accountTextCtrlMap[group]
		assert control.parent is sizer.GetStaticBox(), group


class KeyEvent:
	def __init__(self, key):
		self.key = key
		self.skipped = False

	def GetKeyCode(self):
		return self.key

	def Skip(self):
		self.skipped = True


class FakeUrlDialog:
	"""Stands in for CatalogUrlDialog; `saves` is what its OK saves."""

	instances = []  # noqa: RUF012
	answer = None
	saves = None

	def __init__(self, parent, *, settings, panel):
		self.parent, self.settings, self.panel = parent, settings, panel
		self.savedUrl = None
		FakeUrlDialog.instances.append(self)

	def ShowModal(self):
		if FakeUrlDialog.saves is not None:
			self.settings.save_catalog_url(FakeUrlDialog.saves)
			self.savedUrl = FakeUrlDialog.saves
		return FakeUrlDialog.answer


def _fake_dialog(monkeypatch, f, answer, saves=None):
	FakeUrlDialog.instances = []
	FakeUrlDialog.answer = answer
	FakeUrlDialog.saves = saves
	monkeypatch.setattr(f.dialogs, "CatalogUrlDialog", FakeUrlDialog)
	refreshes = []
	monkeypatch.setattr(f.dialogs.catalog_updater, "request_refresh", refreshes.append)
	return refreshes


@pytest.mark.parametrize("how", ["enter", "button"])
def test_enter_in_the_box_and_the_button_open_the_dialog(monkeypatch, how):
	f = _panel_fixture(monkeypatch)
	panel = f.make_panel()
	_fake_dialog(monkeypatch, f, f.plugin.wx.ID_CANCEL)

	if how == "enter":
		panel.catalogUrlBox.bindings[f.plugin.wx.EVT_CHAR_HOOK](KeyEvent(f.plugin.wx.WXK_RETURN))
	else:
		panel.catalogUrlChangeButton.bindings[f.plugin.wx.EVT_BUTTON](None)

	[dialog] = FakeUrlDialog.instances
	assert dialog.parent is panel
	assert dialog.settings is panel.settings
	assert dialog.panel is panel


def test_other_keys_in_the_box_are_skipped(monkeypatch):
	f = _panel_fixture(monkeypatch)
	panel = f.make_panel()
	_fake_dialog(monkeypatch, f, f.plugin.wx.ID_CANCEL)
	event = KeyEvent(ord("A"))

	panel.catalogUrlBox.bindings[f.plugin.wx.EVT_CHAR_HOOK](event)

	assert event.skipped is True
	assert FakeUrlDialog.instances == []


URL_B = "https://b.test/catalog"


def test_a_saved_url_refreshes_once_resets_the_backoff_and_updates_the_box(monkeypatch, tmp_path):
	from test_catalog_retry import FakeScheduler

	f = _panel_fixture(monkeypatch)
	scheduler = FakeScheduler()
	updater = real_updater(f, tmp_path, _refuse, schedule=scheduler)
	updater.initial_catalog(DEFAULT_URL)
	updater.refresh(DEFAULT_URL)
	updater.run_latest()
	for _ in range(2):
		scheduler.live()[0].fire()
		updater.run_latest()
	assert scheduler.live()[0].delay_ms == 4 * 60_000
	f.dialogs.catalog_updater.install(updater)
	try:
		panel = f.make_panel()
		FakeUrlDialog.instances = []
		FakeUrlDialog.answer = f.plugin.wx.ID_OK
		FakeUrlDialog.saves = URL_B
		monkeypatch.setattr(f.dialogs, "CatalogUrlDialog", FakeUrlDialog)
		threads = len(updater.threads)

		panel.onChangeCatalogUrl(None)

		assert len(updater.threads) == threads + 1
		assert updater.threads[-1][1][1].url == URL_B
		updater.run_latest()
		assert [timer.delay_ms for timer in scheduler.live()] == [60_000]
		assert panel.catalogUrlBox.GetValue() == URL_B
	finally:
		f.dialogs.catalog_updater.uninstall()


def test_a_saved_url_is_refreshed_once_and_shown_without_a_listener(monkeypatch):
	# The box follows the stored URL even when no live update arrives.
	f = _panel_fixture(monkeypatch)
	panel = f.make_panel()
	refreshes = _fake_dialog(monkeypatch, f, f.plugin.wx.ID_OK, saves=URL_B)

	panel.onChangeCatalogUrl(None)

	assert refreshes == [URL_B]
	assert panel.catalogUrlBox.GetValue() == URL_B


@pytest.mark.parametrize("answer", ["cancel", "ok-unsaved"])
def test_a_cancelled_or_unsaved_dialog_refreshes_nothing(monkeypatch, answer):
	f = _panel_fixture(monkeypatch)
	panel = f.make_panel()
	code = f.plugin.wx.ID_CANCEL if answer == "cancel" else f.plugin.wx.ID_OK
	refreshes = _fake_dialog(monkeypatch, f, code)
	f.queued.clear()

	panel.onChangeCatalogUrl(None)

	assert refreshes == []
	assert f.queued == []
	assert panel.catalogUrlBox.GetValue() == DEFAULT_URL


def test_a_live_update_refreshes_the_url_box(monkeypatch):
	from test_catalog_panel_live import change, live_fixture

	f = live_fixture(monkeypatch)
	panel = f.make_panel()
	f.settings["catalog_url"] = "http://localhost:9000"

	f.fake.emit(change(f))

	assert panel.catalogUrlBox.GetValue() == "http://localhost:9000"


def test_settings_ok_no_longer_saves_or_refreshes_the_url(monkeypatch):
	f = _panel_fixture(monkeypatch)
	panel = f.make_panel()
	refreshes = _fake_dialog(monkeypatch, f, None)
	f.queued.clear()

	_save(panel)

	assert "catalog_url" not in f.settings
	assert refreshes == []
	assert [call for call in f.queued if call[0] == f.dialogs.catalog_updater.request_refresh] == []


def test_the_panel_has_no_url_validation(monkeypatch):
	f = _panel_fixture(monkeypatch, catalog_url="http://example.com")
	panel = f.make_panel()

	assert panel.isValid() is True
	assert "isValid" not in vars(f.dialogs.LLMSettingsPanel)


def test_the_url_group_strings_have_translator_comments_and_translations():
	from test_catalog_url_dialog import ADDON, _assert_translated

	_assert_translated(
		ADDON / "dialogs.py",
		{
			"No model list URL": "未設定模型清單網址",
			"Change...": "變更...",
			"Model list URL": "模型清單網址",
		},
	)


def test_the_group_captions_have_translator_comments_and_translations():
	from test_catalog_url_dialog import ADDON, _assert_translated

	_assert_translated(
		ADDON / "dialogs.py",
		{
			"Personal dictionary": "個人化辭典",
			"Sound effects": "音效",
		},
	)


STATUS_TABLE = [
	("off", "none", "off", "The model list URL is empty, so only the Coseeing default is available."),
	("invalid", "none", "invalid", "The model list URL is invalid, so no model list was loaded."),
	(
		"loading",
		"none",
		"running",
		"The model list is still loading. Until it loads, only the Coseeing default is available.",
	),
	(
		"failed",
		"none",
		"failed",
		"The model list could not be loaded, so only the Coseeing default is available. See the NVDA log for details.",
	),
	(
		"stale",
		"cache",
		"failed",
		"The model list could not be updated. WordBridge is using the list it saved earlier.",
	),
	("cache-running", "cache", "running", None),
	# The add-on's release-time model list is in use: the list is not short,
	# so a load in progress says nothing, like cache/running.
	(
		"bundled-off",
		"bundled",
		"off",
		"The model list URL is empty, so WordBridge is using the model list that came with the add-on.",
	),
	(
		"bundled-invalid",
		"bundled",
		"invalid",
		"The model list URL is invalid, so WordBridge is using the model list that came with the add-on.",
	),
	("bundled-running", "bundled", "running", None),
	(
		"bundled-failed",
		"bundled",
		"failed",
		"The model list could not be updated. WordBridge is using the model list that came with the add-on.",
	),
	("fetched", "fetched", "succeeded", None),
]


@pytest.mark.parametrize(
	"source, fetch, message", [row[1:] for row in STATUS_TABLE], ids=[row[0] for row in STATUS_TABLE]
)
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
	monkeypatch.setattr(
		f.dialogs.catalog_updater, "status", lambda: _status(f.dialogs, "fetched", "succeeded")
	)

	panel = f.make_panel()

	assert panel.catalogStatusText.label == ""
	assert _line_shown(panel, panel.catalogStatusText) is False


def test_the_dropped_entries_line_is_silent_for_the_shipped_overlay(monkeypatch):
	f = _panel_fixture(monkeypatch)

	panel = f.make_panel()

	assert panel.catalogIssuesText.label == ""
	assert _line_shown(panel, panel.catalogIssuesText) is False


@pytest.mark.parametrize(
	"source, fetch, message", [row[1:] for row in STATUS_TABLE], ids=[row[0] for row in STATUS_TABLE]
)
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
	monkeypatch.setattr(
		f.dialogs.catalog_updater, "status", lambda: _status(f.dialogs, "fetched", "succeeded")
	)

	panel = f.make_panel()

	controls = f.plugin.panel_added_controls
	assert (
		controls.index(panel.catalogIssuesText)
		< controls.index(panel.catalogStatusText)
		< controls.index(panel.providerList)
	)
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
		cache=cache_module.CatalogCache(
			tmp_path / "catalog" / "remote-catalog.json", can_write=lambda: False
		),
		runnable_providers=f.plugin.SUPPORTED_PROVIDERS,
		http_get=http_get,
		post_to_ui=lambda function, *args: posted.append((function, args)),
		install=install,
		shutdown=threading.Event(),
		log=_Log(),
		start_thread=lambda target, args: (
			threads.append((target, args)) or SimpleNamespace(is_alive=lambda: False)
		),
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
	from shipped_catalog import served_document

	return BodyResponse(json.dumps(served_document()).encode("utf8"))


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
		# R1 ran before the status was read, from the shipped bundled model
		# list: the panel keeps that list's "could not be updated" line (C24).
		assert panel.catalogStatusText.label == {row[0]: row[3] for row in STATUS_TABLE}["bundled-failed"]


class _BundledWithoutModels:
	"""The shipped bundled file without its model list."""

	def __init__(self, inner):
		self.inner = inner

	def load(self):
		document, issues = self.inner.load()
		return {key: value for key, value in document.items() if key != "models"}, issues


def _coseeing_only(f):
	"""No local models at all: only the Coseeing default (source "none")."""
	overlay = __import__(f.plugin.__name__ + ".lib.catalog.overlay", fromlist=["load_overlay_catalog"])
	return overlay.load_overlay_catalog(
		_BundledWithoutModels(f.plugin.BundledCatalogSource(str(f.plugin.PATH) + "/setting")),
		None,
		runnable_providers=f.plugin.SUPPORTED_PROVIDERS,
	)


def test_account_box_captions_are_the_same_with_and_without_a_fetched_list(monkeypatch):
	# Spec finding 10: captions come from the provider label or fall back to
	# the group name, and every bundled label equals its key.
	from shipped_catalog import served_document

	f = _panel_fixture(monkeypatch)
	overlay = __import__(f.plugin.__name__ + ".lib.catalog.overlay", fromlist=["load_overlay_catalog"])
	fetched = overlay.load_overlay_catalog(
		f.plugin.BundledCatalogSource(str(f.plugin.PATH) + "/setting"),
		served_document(),
		runnable_providers=f.plugin.SUPPORTED_PROVIDERS,
	)
	bundled_only = _coseeing_only(f)

	assert fetched.providers and not bundled_only.providers
	assert [f.dialogs._provider_group_label(fetched, group) for group in f.dialogs.ACCOUNT_BOX_GROUPS] == [
		f.dialogs._provider_group_label(bundled_only, group) for group in f.dialogs.ACCOUNT_BOX_GROUPS
	]


def _served_overlay(f, document, runnable_providers=None):
	overlay = __import__(f.plugin.__name__ + ".lib.catalog.overlay", fromlist=["load_overlay_catalog"])
	return overlay.load_overlay_catalog(
		f.plugin.BundledCatalogSource(str(f.plugin.PATH) + "/setting"),
		document,
		runnable_providers=f.plugin.SUPPORTED_PROVIDERS if runnable_providers is None else runnable_providers,
	)


def test_a_model_for_a_provider_this_release_lacks_is_not_counted_in_the_dropped_line(monkeypatch):
	# OQ1 -> B (Decided by the user, 2026-11-05): after B1 the server can list
	# models for a provider only a newer release bundles; users of this
	# release cannot fix that, so it is lint -- logged, not counted.
	from shipped_catalog import served_document

	f = _panel_fixture(monkeypatch)
	document = served_document()
	index = len(document["models"])
	document["models"].append({"provider": "Mistral", "model": "m-large", "label": "M Large"})

	catalog = _served_overlay(f, document)

	assert ("unknown_provider", f"models[{index}]") in [
		(issue.code, issue.location) for issue in catalog.issues
	]
	assert f.dialogs._dropped_entries_message(catalog) is None


def test_an_unsupported_provider_is_still_counted_in_the_dropped_line(monkeypatch):
	# The B boundary: a bundled provider this build cannot run means the
	# bundled file and the code disagree, which is still worth showing.
	from shipped_catalog import served_document

	f = _panel_fixture(monkeypatch)

	catalog = _served_overlay(f, served_document(), f.plugin.SUPPORTED_PROVIDERS - {"DeepSeek"})

	deepseek = sum(1 for model in served_document()["models"] if model["provider"] == "DeepSeek")
	assert deepseek >= 2, "the served file has too few DeepSeek models for this test"
	assert f.dialogs._dropped_entries_message(catalog) == (
		f"{deepseek} catalog entries could not be loaded; see the NVDA log for details."
	)


def _run_queued(f):
	for callback, args in list(f.queued):
		callback(*args)
	f.queued.clear()


def test_an_unresolved_stored_selection_survives_an_untouched_save(monkeypatch):
	# Offline with no cache: the stored local model is not in the catalog.
	f = _panel_fixture(monkeypatch, corrector_config_id="gpt-6-luna&OpenAI", execution_channel="local")
	catalog = _coseeing_only(f)
	monkeypatch.setattr(f.dialogs.registry, "current", lambda: catalog)
	panel = f.make_panel()
	panel.languageList.SetSelection(1)
	f.queued.clear()

	_save(panel)
	_run_queued(f)

	assert (f.settings["corrector_config_id"], f.settings["execution_channel"]) == (
		"gpt-6-luna&OpenAI",
		"local",
	)
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
		catalog = _coseeing_only(f)
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
		catalog = _coseeing_only(f)
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
		catalog = _coseeing_only(f)
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
		first_openai.corrector_config_id,
		"local",
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

	assert (f.settings["corrector_config_id"], f.settings["execution_channel"]) == (
		"gpt-6.1-sol&OpenAI",
		"local",
	)
