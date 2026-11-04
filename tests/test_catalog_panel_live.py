"""The open settings panel following catalog changes (retry spec sections
10-11, R2, R4, R8, R11).

_load_nvda_plugin and the widget stubs are imported at function scope (via
test_catalog_settings_panel's fixture), never at module scope.
"""

from types import SimpleNamespace

import pytest

from test_catalog_settings_panel import STATUS_TABLE, _bundled_only, _panel_fixture, _status


class FakeUpdater:
	"""The module-level updater the panel talks to, driven by the test."""

	def __init__(self, status):
		self.status_value = status
		self.listeners = []

	def retry_on_panel_open(self):
		return False

	def status(self):
		return self.status_value

	def add_listener(self, listener):
		self.listeners.append(listener)

	def remove_listener(self, listener):
		for index, known in enumerate(self.listeners):
			if known == listener:
				del self.listeners[index]
				return

	def close(self):
		pass

	def emit(self, change):
		for listener in list(self.listeners):
			listener(change)


def live_fixture(monkeypatch, catalog=None, **settings):
	f = _panel_fixture(monkeypatch, **settings)
	f.fake = FakeUpdater(_status(f.dialogs, "fetched", "succeeded"))
	monkeypatch.setattr(f.dialogs.catalog_updater, "_UPDATER", f.fake)
	f.box = {"catalog": catalog if catalog is not None else f.plugin.catalog}
	monkeypatch.setattr(f.dialogs.registry, "current", lambda: f.box["catalog"])
	f.messages = []

	def message(*args, **kwargs):
		assert len(args) == 1 and not kwargs, "ui.message gets the text only (default priority)"
		f.messages.append(args[0])

	monkeypatch.setattr(f.dialogs, "ui", SimpleNamespace(message=message), raising=False)
	return f


def change(f, catalog_changed=False, outcome=None, user_initiated=False):
	return f.dialogs.catalog_updater.CatalogChange(catalog_changed, outcome, user_initiated)


def set_status(f, source, fetch):
	f.fake.status_value = _status(f.dialogs, source, fetch)


class DestroyEvent:
	def __init__(self, source):
		self.source = source
		self.skipped = False

	def GetEventObject(self):
		return self.source

	def Skip(self):
		self.skipped = True


def _text(row_id):
	return {row[0]: row[3] for row in STATUS_TABLE}[row_id]


# --- Task 8: wiring, status line, description, lifecycle ------------------

def test_the_panel_registers_one_listener(monkeypatch):
	f = live_fixture(monkeypatch)

	panel = f.make_panel()

	assert f.fake.listeners == [panel._onCatalogChange]


def test_the_status_line_and_description_follow_live_updates(monkeypatch):
	f = live_fixture(monkeypatch)
	panel = f.make_panel()
	shown = panel.settingsSizer.IsShown

	for source, fetch, row in [
		("none", "failed", "failed"), ("fetched", "succeeded", None), ("none", "running", "loading"),
	]:
		set_status(f, source, fetch)
		f.fake.emit(change(f))
		expected = _text(row) if row else None
		assert panel.catalogStatusText.label == (expected or "")
		assert shown(panel.catalogStatusText) is (expected is not None)
		assert panel.panelDescription == (expected or "")
	assert f.messages == []


def test_a_status_visibility_change_sends_one_layout_event_and_a_text_change_none(monkeypatch):
	f = live_fixture(monkeypatch)
	panel = f.make_panel()

	set_status(f, "none", "failed")
	f.fake.emit(change(f))
	assert panel.layout_events == 1

	set_status(f, "cache", "failed")
	f.fake.emit(change(f))
	assert panel.catalogStatusText.label == _text("stale")
	assert panel.layout_events == 1


def test_one_update_is_applied_in_one_freeze_with_at_most_one_layout_event(monkeypatch):
	# Batch-2 review m2: a success that hides the status line and changes
	# the shown box used to send two layout events (two scrolls to the top).
	f = live_fixture(monkeypatch, corrector_config_id=SOL[0], execution_channel=SOL[1])
	set_status(f, "none", "failed")
	f.box["catalog"] = _bundled_only(f)
	panel = f.make_panel()
	assert _shown_boxes(panel) == ["Coseeing"]

	set_status(f, "fetched", "succeeded")
	rebuild_with(f, panel, _shipped(f))

	assert panel.settingsSizer.IsShown(panel.catalogStatusText) is False
	assert _shown_boxes(panel) == ["OpenAI"]
	assert panel.layout_events == 1
	assert (panel.freeze_count, panel.thaw_count) == (1, 1)


def test_a_hidden_panel_sends_no_layout_event_and_lays_out_when_activated(monkeypatch):
	# Batch-2 review I1: NVDA lays out and re-scrolls the container all
	# categories share, so an event from the hidden WordBridge panel would
	# scroll the category the user is reading back to the top.
	f = live_fixture(monkeypatch, corrector_config_id=SOL[0], execution_channel=SOL[1])
	f.box["catalog"] = _bundled_only(f)
	panel = f.make_panel()
	panel.shown = False

	set_status(f, "none", "failed")
	f.fake.emit(change(f))
	set_status(f, "fetched", "succeeded")
	rebuild_with(f, panel, _shipped(f))
	assert _shown_boxes(panel) == ["OpenAI"]
	assert getattr(panel, "layout_events", 0) == 0
	assert getattr(panel, "layout_calls", 0) == 0

	panel.onPanelActivated()
	assert panel.shown is True
	assert panel.layout_calls == 1
	panel.onPanelActivated()
	assert panel.layout_calls == 1

	set_status(f, "none", "failed")
	f.fake.emit(change(f))
	assert panel.layout_events == 1


def test_a_hidden_panel_retrying_with_the_cache_sends_no_layout_event(monkeypatch):
	# The reviewer's probe: two layout events per retry while hidden.
	f = live_fixture(monkeypatch)
	set_status(f, "cache", "failed")
	panel = f.make_panel()
	panel.shown = False

	for source, fetch, outcome in [("cache", "running", None), ("cache", "failed", "failed")] * 2:
		set_status(f, source, fetch)
		f.fake.emit(change(f, False, outcome))

	assert getattr(panel, "layout_events", 0) == 0


def _status_line(panel):
	return (panel.catalogStatusText.label, panel.settingsSizer.IsShown(panel.catalogStatusText), panel.panelDescription)


def test_a_same_key_retry_with_the_cache_keeps_the_stale_line(monkeypatch):
	# C24: cache/running has no text; a failing retry must not hide and show
	# the "could not be updated" line (and re-lay out the panel) each time.
	f = live_fixture(monkeypatch)
	set_status(f, "cache", "failed")
	panel = f.make_panel()
	stale = (_text("stale"), True, _text("stale"))
	assert _status_line(panel) == stale

	for _ in range(2):
		set_status(f, "cache", "running")
		f.fake.emit(change(f))
		assert _status_line(panel) == stale
		set_status(f, "cache", "failed")
		f.fake.emit(change(f, False, "failed"))
		assert _status_line(panel) == stale
	assert getattr(panel, "layout_events", 0) == 0

	set_status(f, "cache", "running")
	f.fake.emit(change(f))
	set_status(f, "fetched", "succeeded")
	f.fake.emit(change(f, True, "succeeded"))
	assert _status_line(panel) == ("", False, "")
	assert panel.layout_events == 1


def test_a_url_change_with_the_cache_hides_the_stale_line(monkeypatch):
	f = live_fixture(monkeypatch)
	set_status(f, "cache", "failed")
	panel = f.make_panel()

	set_status(f, "cache", "running")
	f.fake.emit(change(f, True))

	assert _status_line(panel) == ("", False, "")


@pytest.mark.parametrize("retried, expected", [(True, "stale"), (False, None)], ids=["r1-started", "already-running"])
def test_the_panel_opens_on_the_stale_line_when_its_fetch_starts_from_a_cache_failure(monkeypatch, retried, expected):
	f = live_fixture(monkeypatch)
	set_status(f, "cache", "failed" if retried else "running")

	def retry_on_panel_open():
		set_status(f, "cache", "running")
		return retried

	f.fake.retry_on_panel_open = retry_on_panel_open
	panel = f.make_panel()

	text = _text(expected) if expected else ""
	assert _status_line(panel) == (text, bool(expected), text)
	# Only a line already shown is kept: a hidden one stays hidden.
	f.fake.emit(change(f))
	assert _status_line(panel) == (text, bool(expected), text)


def test_a_destroy_event_from_a_child_keeps_the_listener(monkeypatch):
	f = live_fixture(monkeypatch)
	panel = f.make_panel()
	event = DestroyEvent(panel.providerList)

	panel.bindings[f.plugin.wx.EVT_WINDOW_DESTROY](event)

	assert f.fake.listeners == [panel._onCatalogChange]
	assert event.skipped is True


def test_a_destroy_event_from_the_panel_unregisters_and_skips(monkeypatch):
	f = live_fixture(monkeypatch)
	panel = f.make_panel()
	event = DestroyEvent(panel)

	panel.bindings[f.plugin.wx.EVT_WINDOW_DESTROY](event)

	assert f.fake.listeners == []
	assert event.skipped is True


def test_a_notification_after_the_panel_is_gone_unregisters_and_does_nothing(monkeypatch):
	f = live_fixture(monkeypatch)
	panel = f.make_panel()
	items = list(panel.providerList.items)
	panel.alive = False
	set_status(f, "none", "failed")
	f.box["catalog"] = _bundled_only(f)

	f.fake.emit(change(f, True, "succeeded"))

	assert f.fake.listeners == []
	assert panel.catalogStatusText.label == ""
	assert panel.providerList.items == items
	assert getattr(panel.providerList, "set_items_calls", 0) == 0
	assert f.messages == []


# --- Task 9: rebuild, selection and the D12 baseline (R4, R7/C8, C22) -----

import dataclasses  # noqa: E402

DEFAULT = ("default", "Coseeing")


def _shipped(f):
	return f.plugin.catalog


def _shipped_without(*ids):
	def build(f):
		catalog = f.plugin.catalog
		return dataclasses.replace(catalog, models=tuple(m for m in catalog.models if m.corrector_config_id not in ids))
	return build


def _item_ids(item):
	return (item.corrector_config_id, item.execution_channel)


def touch(panel, group, model_index):
	"""Choose a provider and a model the way the user does."""
	panel.providerList.SetSelection(panel.catalog.provider_groups.index(group))
	panel.onChangeProviderChoice(None)
	panel.modelList.SetSelection(model_index)


def rebuild_with(f, panel, catalog):
	f.box["catalog"] = catalog
	f.fake.emit(change(f, True))


def _run_queued(f):
	for callback, args in list(f.queued):
		callback(*args)
	f.queued.clear()


SOL = ("gpt-6.1-sol&OpenAI", "local")
DEEPSEEK_PRO = ("deepseek-v4-pro&DeepSeek", "local")
SELECTION_ROWS = [
	("fresh-untouched", _bundled_only, _shipped, ("", ""), None, DEFAULT, DEFAULT),
	("stored-local-unresolved-untouched", _bundled_only, _shipped, ("gpt-6-luna&OpenAI", "local"), None,
		("gpt-6-luna&OpenAI", "local"), ("gpt-6-luna&OpenAI", "local")),
	("touched-pick-kept", _shipped, _shipped, SOL, ("DeepSeek", 0), DEEPSEEK_PRO, SOL),
	("touched-pick-gone-stored-present", _shipped, _shipped_without("deepseek-v4-pro&DeepSeek"), SOL, ("DeepSeek", 0),
		SOL, SOL),
	("touched-pick-gone-stored-absent", _shipped, _shipped_without("deepseek-v4-pro&DeepSeek", SOL[0]), SOL,
		("DeepSeek", 0), DEFAULT, DEFAULT),
	("stored-coseeing-non-default", _bundled_only, _shipped, ("gpt-6-luna&OpenAI", "Coseeing"), None, DEFAULT, DEFAULT),
]


@pytest.mark.parametrize(
	"old, new, stored, touched, expected, baseline", [row[1:] for row in SELECTION_ROWS], ids=[row[0] for row in SELECTION_ROWS],
)
def test_live_selection_table(monkeypatch, old, new, stored, touched, expected, baseline):
	f = live_fixture(monkeypatch, corrector_config_id=stored[0], execution_channel=stored[1])
	f.box["catalog"] = old(f)
	panel = f.make_panel()
	if touched is not None:
		touch(panel, *touched)
	new_catalog = new(f)

	rebuild_with(f, panel, new_catalog)

	assert panel.catalog is new_catalog
	assert _item_ids(panel.selection.current_item()) == expected
	assert (panel.providerList.GetSelection(), panel.modelList.GetSelection()) == new_catalog.find_selection(*expected)
	assert panel._restoredIndices == new_catalog.find_selection(*baseline)


def _stored(f):
	return (f.settings["corrector_config_id"], f.settings["execution_channel"])


def test_an_untouched_save_after_a_rebuild_keeps_an_unresolved_stored_model(monkeypatch):
	f = live_fixture(monkeypatch, corrector_config_id="gpt-retired&OpenAI", execution_channel="local")
	f.box["catalog"] = _bundled_only(f)
	panel = f.make_panel()
	rebuild_with(f, panel, _shipped(f))
	f.queued.clear()

	panel.onSave()
	_run_queued(f)

	assert _stored(f) == ("gpt-retired&OpenAI", "local")
	assert f.auth_calls == []


def test_an_untouched_save_after_the_list_arrives_saves_the_users_own_model(monkeypatch):
	# F1: the offline local user's own model appears; OK must not save the
	# Coseeing default that was shown before, nor sign in to Coseeing.
	f = live_fixture(monkeypatch, corrector_config_id="gpt-6-luna&OpenAI", execution_channel="local")
	f.box["catalog"] = _bundled_only(f)
	panel = f.make_panel()
	rebuild_with(f, panel, _shipped(f))
	assert _item_ids(panel.selection.current_item()) == ("gpt-6-luna&OpenAI", "local")
	f.queued.clear()

	panel.onSave()
	_run_queued(f)

	assert _stored(f) == ("gpt-6-luna&OpenAI", "local")
	assert f.auth_calls == []


def test_a_touched_pick_kept_across_a_rebuild_is_saved(monkeypatch):
	f = live_fixture(monkeypatch, corrector_config_id=SOL[0], execution_channel=SOL[1])
	panel = f.make_panel()
	touch(panel, "DeepSeek", 0)
	rebuild_with(f, panel, _shipped(f))

	panel.onSave()

	assert _stored(f) == DEEPSEEK_PRO


def test_a_kept_pick_equal_to_the_new_baseline_is_saved(monkeypatch):
	# C22: the user explicitly picks the Coseeing default; the new list drops
	# their stored model, so the recomputed baseline is that default too.
	f = live_fixture(monkeypatch, corrector_config_id=SOL[0], execution_channel=SOL[1])
	panel = f.make_panel()
	touch(panel, "Coseeing", 0)
	rebuild_with(f, panel, _shipped_without(SOL[0])(f))
	assert _item_ids(panel.selection.current_item()) == DEFAULT
	f.queued.clear()

	panel.onSave()
	_run_queued(f)

	assert _stored(f) == DEFAULT
	assert f.auth_calls == ["Coseeing"]


def test_a_fallback_rebuild_clears_the_kept_pick(monkeypatch):
	# C22: a rebuild keeps the user's DeepSeek pick (flag set); the next list
	# drops DeepSeek, so the panel falls back to the baseline and counts as
	# untouched again. D12 must then protect the unresolved stored model.
	f = live_fixture(monkeypatch, corrector_config_id="gpt-retired&OpenAI", execution_channel="local")
	panel = f.make_panel()
	touch(panel, "DeepSeek", 0)
	rebuild_with(f, panel, _shipped(f))
	assert panel._keptUserPick is True

	rebuild_with(f, panel, _without_group(f, "DeepSeek"))
	assert _item_ids(panel.selection.current_item()) == DEFAULT
	f.queued.clear()
	panel.onSave()
	_run_queued(f)

	assert panel._keptUserPick is False
	assert _stored(f) == ("gpt-retired&OpenAI", "local")
	assert f.auth_calls == []


def test_a_second_rebuild_keeps_a_kept_pick_equal_to_the_baseline(monkeypatch):
	# C22: the explicit Coseeing default pick is kept while it equals the
	# baseline (the stored model is gone); when the stored model returns, the
	# pick is still the user's and must not fall back to it.
	f = live_fixture(monkeypatch, corrector_config_id=SOL[0], execution_channel=SOL[1])
	panel = f.make_panel()
	touch(panel, "Coseeing", 0)
	rebuild_with(f, panel, _shipped_without(SOL[0])(f))

	rebuild_with(f, panel, _shipped(f))
	assert _item_ids(panel.selection.current_item()) == DEFAULT
	f.queued.clear()
	panel.onSave()
	_run_queued(f)

	assert _stored(f) == DEFAULT
	assert f.auth_calls == ["Coseeing"]


def test_the_baseline_is_reread_from_config_after_apply(monkeypatch):
	f = live_fixture(monkeypatch, corrector_config_id=SOL[0], execution_channel=SOL[1])
	panel = f.make_panel()
	# Apply wrote a new stored selection; then the D8 switch notifies.
	f.settings["corrector_config_id"] = "gpt-6-sol&OpenAI"

	rebuild_with(f, panel, _shipped(f))

	assert panel._storedSelection == ("gpt-6-sol&OpenAI", "local")
	assert _item_ids(panel.selection.current_item()) == ("gpt-6-sol&OpenAI", "local")


def _focused(f, panel):
	windows = list(f.plugin.panel_added_controls) + [panel.providerList, panel.modelList]
	return [window for window in windows if getattr(window, "focused", False)]


@pytest.mark.parametrize("shown", [True, False], ids=["shown", "hidden"])
def test_a_rebuild_never_moves_focus_or_shows_the_panel(monkeypatch, shown):
	f = live_fixture(monkeypatch)
	f.box["catalog"] = _bundled_only(f)
	panel = f.make_panel()
	panel.shown = shown

	rebuild_with(f, panel, _shipped(f))

	assert _focused(f, panel) == []
	assert getattr(panel, "show_calls", 0) == 0
	assert getattr(panel, "activated_calls", 0) == 0
	assert (panel.freeze_count, panel.thaw_count) == (1, 1)
	assert len(panel.providerList.items) == len(_shipped(f).provider_groups)
	assert panel.shown is shown


def test_choices_are_replaced_only_when_their_labels_change(monkeypatch):
	f = live_fixture(monkeypatch)
	panel = f.make_panel()

	rebuild_with(f, panel, _shipped(f))
	assert getattr(panel.providerList, "set_items_calls", 0) == 0
	assert getattr(panel.modelList, "set_items_calls", 0) == 0

	rebuild_with(f, panel, _bundled_only(f))
	assert panel.providerList.set_items_calls == 1


# --- Task 10 (R13): account boxes up front, and the dropped-entries line --

def _shown_boxes(panel):
	return [group for group, box in panel.accountGroupSizerMap.items() if panel.settingsSizer.IsShown(box)]


def _account_groups(f):
	return [*sorted(f.plugin.SUPPORTED_PROVIDERS), "Coseeing"]


@pytest.mark.parametrize("catalog", [_bundled_only, lambda f: f.plugin.catalog], ids=["bundled", "shipped"])
def test_every_supported_provider_has_a_box_in_a_fixed_order(monkeypatch, catalog):
	# R13: the boxes do not depend on the catalog, so no live update ever
	# needs to create one.
	f = live_fixture(monkeypatch)
	f.box["catalog"] = catalog(f)

	panel = f.make_panel()

	groups = _account_groups(f)
	assert list(panel.accountGroupSizerMap) == groups
	assert set(panel.accountTextCtrlMap) == set(groups) - {"Coseeing"}
	boxes = [child for child in panel.settingsSizer.children if any(child is box for box in panel.accountGroupSizerMap.values())]
	assert boxes == [panel.accountGroupSizerMap[group] for group in groups]
	assert _shown_boxes(panel) == ["Coseeing"]


def test_only_the_selected_groups_box_is_shown(monkeypatch):
	f = live_fixture(monkeypatch, corrector_config_id=SOL[0], execution_channel=SOL[1])

	panel = f.make_panel()

	assert _shown_boxes(panel) == ["OpenAI"]


def test_a_live_update_creates_no_window_and_only_shows_hides_and_relabels(monkeypatch):
	f = live_fixture(monkeypatch, corrector_config_id=SOL[0], execution_channel=SOL[1])
	f.box["catalog"] = _bundled_only(f)
	panel = f.make_panel()
	windows = list(f.plugin.created_windows)
	children = list(panel.settingsSizer.children)
	catalog = _shipped(f)
	relabelled = dataclasses.replace(
		catalog, providers={**catalog.providers, "OpenAI": dataclasses.replace(catalog.providers["OpenAI"], label="OpenAI EU")},
	)

	for new, shown, caption in [
		(_shipped(f), ["OpenAI"], "OpenAI Authentication"),
		(relabelled, ["OpenAI"], "OpenAI EU Authentication"),
		(_without_group(f, "OpenAI"), ["Coseeing"], "OpenAI Authentication"),
		(_bundled_only(f), ["Coseeing"], "OpenAI Authentication"),
	]:
		rebuild_with(f, panel, new)
		assert _shown_boxes(panel) == shown
		assert panel.accountGroupSizerMap["OpenAI"].GetStaticBox().label == caption

	assert f.plugin.created_windows == windows
	assert panel.settingsSizer.children == children
	assert [w for w in f.plugin.created_windows if hasattr(w, "moved_after")] == []


def test_tab_and_window_order_is_creation_order(monkeypatch):
	# wx orders windows, and so Tab and NVDA object navigation, by creation.
	f = live_fixture(monkeypatch)
	panel = f.make_panel()
	windows = f.plugin.created_windows

	def at(window):
		return next(index for index, known in enumerate(windows) if known is window)

	order = [at(panel.modelList)]
	for group in _account_groups(f):
		order.append(at(panel.accountGroupSizerMap[group].GetStaticBox()))
		control = panel.coseeingCleanButton if group == "Coseeing" else panel.accountTextCtrlMap[group]
		order.append(at(control))
	order.append(at(panel.languageList))
	assert order == sorted(order)

	rebuild_with(f, panel, _bundled_only(f))
	assert [at(panel.modelList), at(panel.languageList)] == [order[0], order[-1]]


def _without_group(f, group):
	catalog = f.plugin.catalog
	return dataclasses.replace(catalog, models=tuple(m for m in catalog.models if m.provider != group))


def _keys(f):
	return dict(f.settings["api_key"])


def _path_open(f, panel):
	pass


def _path_rebuild(f, panel):
	rebuild_with(f, panel, _bundled_only(f))
	rebuild_with(f, panel, _shipped(f))


def _path_rebuild_after_ok(f, panel):
	# OK ran onSave; the D8 swap arrives before DestroyLater (F5, batch-2 m1).
	panel.onSave()
	rebuild_with(f, panel, _bundled_only(f))
	rebuild_with(f, panel, _shipped(f))


def _path_save(f, panel):
	panel.onSave()


def _path_type_and_save(f, panel):
	panel.accountTextCtrlMap["OpenAI"].SetValue("sk-typed")
	panel.onSave()


def _path_clear_and_save(f, panel):
	panel.accountTextCtrlMap["DeepSeek"].SetValue("")
	panel.onSave()


KEY_ROWS = [
	("open", {}, _path_open, {}),
	("rebuild", {}, _path_rebuild, {}),
	("rebuild-after-ok", {}, _path_rebuild_after_ok, {}),
	("untouched-ok", {}, _path_save, {}),
	("typed-ok", {}, _path_type_and_save, {"OpenAI": "sk-typed"}),
	("kept", {"DeepSeek": "k", "Ollama": ""}, _path_save, {"DeepSeek": "k", "Ollama": ""}),
	("cleared", {"DeepSeek": "k"}, _path_clear_and_save, {"DeepSeek": ""}),
]


@pytest.mark.parametrize("stored, path, expected", [row[1:] for row in KEY_ROWS], ids=[row[0] for row in KEY_ROWS])
def test_no_blank_api_key_is_written(monkeypatch, stored, path, expected):
	# R13: boxes exist for providers the user never used; neither reading
	# their keys nor an OK may add empty entries, and no stored key is lost.
	f = live_fixture(monkeypatch, api_key=dict(stored))
	panel = f.make_panel()

	path(f, panel)

	assert _keys(f) == expected


def test_a_hidden_providers_key_is_shown_in_its_box_and_kept(monkeypatch):
	f = live_fixture(monkeypatch, api_key={"OpenRouter": "r"})
	f.box["catalog"] = _bundled_only(f)
	panel = f.make_panel()

	panel.onSave()

	assert panel.accountTextCtrlMap["OpenRouter"].GetValue() == "r"
	assert "OpenRouter" not in _shown_boxes(panel)
	assert _keys(f) == {"OpenRouter": "r"}


def test_typed_api_keys_survive_a_rebuild(monkeypatch):
	f = live_fixture(monkeypatch, corrector_config_id=SOL[0], execution_channel=SOL[1])
	panel = f.make_panel()
	field = panel.accountTextCtrlMap["OpenAI"]
	field.SetValue("typed")

	rebuild_with(f, panel, _shipped_without("deepseek-flash&DeepSeek")(f))

	assert panel.accountTextCtrlMap["OpenAI"] is field
	assert field.GetValue() == "typed"
	assert _shown_boxes(panel) == ["OpenAI"]


def test_a_vanished_providers_box_is_hidden_and_its_key_saved_unchanged(monkeypatch):
	f = live_fixture(monkeypatch, api_key={"DeepSeek": "k"})
	panel = f.make_panel()
	touch(panel, "DeepSeek", 0)

	rebuild_with(f, panel, _without_group(f, "DeepSeek"))
	panel.onSave()

	assert panel.settingsSizer.IsShown(panel.accountGroupSizerMap["DeepSeek"]) is False
	assert f.settings["api_key"]["DeepSeek"] == "k"


@pytest.mark.parametrize("steps", [
	("bundled", "shipped"),
	("shipped", "bundled"),
	("without-Anthropic", "without-Google"),
], ids=["gain", "lose", "swap"])
def test_refreshing_account_info_never_raises_for_any_group_change(monkeypatch, steps):
	f = live_fixture(monkeypatch)
	catalogs = {
		"bundled": _bundled_only, "shipped": _shipped,
		"without-Anthropic": lambda f: _without_group(f, "Anthropic"),
		"without-Google": lambda f: _without_group(f, "Google"),
	}
	f.box["catalog"] = catalogs[steps[0]](f)
	panel = f.make_panel()

	rebuild_with(f, panel, catalogs[steps[1]](f))

	for index in range(len(panel.catalog.provider_groups)):
		panel.providerList.SetSelection(index)
		panel.onChangeProviderChoice(None)
		assert _shown_boxes(panel) == [panel.catalog.provider_groups[index]]


def test_a_changed_provider_label_updates_the_box_caption(monkeypatch):
	f = live_fixture(monkeypatch)
	panel = f.make_panel()
	catalog = _shipped(f)
	relabelled = dataclasses.replace(
		catalog, providers={**catalog.providers, "OpenAI": dataclasses.replace(catalog.providers["OpenAI"], label="OpenAI EU")},
	)

	rebuild_with(f, panel, relabelled)

	assert panel.accountGroupSizerMap["OpenAI"].GetStaticBox().label == "OpenAI EU Authentication"


def test_the_layout_event_is_sent_only_when_the_shown_box_changes(monkeypatch):
	f = live_fixture(monkeypatch, corrector_config_id=SOL[0], execution_channel=SOL[1])
	panel = f.make_panel()

	rebuild_with(f, panel, _shipped_without("deepseek-flash&DeepSeek")(f))
	assert getattr(panel, "layout_events", 0) == 0

	rebuild_with(f, panel, _without_group(f, "OpenAI"))
	assert _shown_boxes(panel) == ["Coseeing"]
	assert panel.layout_events == 1


def test_the_dropped_entries_line_follows_the_new_catalog(monkeypatch):
	from lib.catalog.model import CatalogIssue

	f = live_fixture(monkeypatch)
	panel = f.make_panel()
	first = CatalogIssue("unreadable_file", "ai/x.json", "ValueError")
	second = CatalogIssue("duplicate_entry", "models[3]", "already defined")
	catalog = _shipped(f)

	rebuild_with(f, panel, dataclasses.replace(catalog, issues=(first, second)))
	assert panel.catalogIssuesText.label == "2 catalog entries could not be loaded; see the NVDA log for details."
	assert panel.settingsSizer.IsShown(panel.catalogIssuesText) is True
	assert panel.layout_events == 1

	rebuild_with(f, panel, dataclasses.replace(catalog, issues=(first,)))
	assert panel.catalogIssuesText.label == "1 catalog entry could not be loaded; see the NVDA log for details."
	assert panel.layout_events == 1

	rebuild_with(f, panel, dataclasses.replace(catalog, issues=()))
	assert panel.settingsSizer.IsShown(panel.catalogIssuesText) is False
	assert panel.layout_events == 2
