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


def _touch_item(panel, item):
	group_index, model_index = panel.catalog.find_selection(*item)
	touch(panel, panel.catalog.provider_groups[group_index], model_index)


def test_a_pick_made_after_apply_survives_a_rebuild(monkeypatch):
	# Final review I1 (R4/R7): Apply saves DeepSeek, the user then picks
	# their old model again by hand. A live update must keep that pick, and
	# OK must save it, instead of moving back to what Apply stored.
	f = live_fixture(monkeypatch, corrector_config_id=SOL[0], execution_channel=SOL[1])
	panel = f.make_panel()
	touch(panel, "DeepSeek", 0)
	panel.onSave()
	assert _stored(f) == DEEPSEEK_PRO
	_touch_item(panel, SOL)

	rebuild_with(f, panel, _shipped(f))

	assert _item_ids(panel.selection.current_item()) == SOL
	assert (panel.providerList.GetSelection(), panel.modelList.GetSelection()) == panel.catalog.find_selection(*SOL)
	panel.onSave()
	assert _stored(f) == SOL


def test_apply_moves_the_baseline_to_what_it_saved(monkeypatch):
	# After Apply, what is shown is what is stored: the panel is untouched
	# again, and a kept pick (C22) is no longer pending.
	f = live_fixture(monkeypatch, corrector_config_id=SOL[0], execution_channel=SOL[1])
	panel = f.make_panel()
	touch(panel, "Coseeing", 0)
	rebuild_with(f, panel, _shipped_without(SOL[0])(f))
	assert panel._keptUserPick is True

	panel.onSave()

	assert _stored(f) == DEFAULT
	assert panel._keptUserPick is False
	assert panel._storedSelection == DEFAULT
	assert panel._restoredIndices == (panel.providerList.GetSelection(), panel.modelList.GetSelection())


def test_apply_keeps_the_d12_baseline_when_it_saved_no_selection(monkeypatch):
	# The D12 skip branch saves nothing, so the recomputed baseline is the
	# same: a later untouched OK still keeps the unresolved stored model.
	f = live_fixture(monkeypatch, corrector_config_id="gpt-retired&OpenAI", execution_channel="local")
	panel = f.make_panel()
	before = (panel._storedSelection, panel._storedSelectionResolved, panel._restoredIndices)

	panel.onSave()
	rebuild_with(f, panel, _shipped(f))
	f.queued.clear()
	panel.onSave()
	_run_queued(f)

	assert (panel._storedSelection, panel._storedSelectionResolved, panel._restoredIndices) == before
	assert _stored(f) == ("gpt-retired&OpenAI", "local")
	assert f.auth_calls == []


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


# --- Task 11: deferral while a drop-down is open or focus would be hidden --

def _timers(f):
	return f.plugin.wx.timers


def _live_timers(f):
	return [timer for timer in _timers(f) if not timer.stopped]


@pytest.mark.parametrize("which", ["provider", "model"])
def test_an_open_drop_down_defers_the_rebuild_and_polls(monkeypatch, which):
	f = live_fixture(monkeypatch)
	f.box["catalog"] = _bundled_only(f)
	panel = f.make_panel()
	target = panel.providerList if which == "provider" else panel.modelList
	dropped = {"open": True}
	panel._isDroppedDown = lambda choice: dropped["open"] and choice is target
	items = list(panel.providerList.items)

	rebuild_with(f, panel, _shipped(f))
	assert panel.providerList.items == items
	assert [timer.delay_ms for timer in _timers(f)] == [300]

	# The status line is never inside a drop-down: it still follows at once.
	set_status(f, "none", "failed")
	f.fake.emit(change(f))
	assert panel.catalogStatusText.label == _text("failed")
	assert len(_timers(f)) == 1

	dropped["open"] = False
	_timers(f)[0].fire()
	assert len(panel.providerList.items) == len(_shipped(f).provider_groups)
	assert panel._deferTimer is None
	assert len(_timers(f)) == 1


def test_a_notification_after_the_drop_down_closes_runs_the_update_and_stops_the_poll(monkeypatch):
	f = live_fixture(monkeypatch)
	f.box["catalog"] = _bundled_only(f)
	panel = f.make_panel()
	dropped = {"open": True}
	panel._isDroppedDown = lambda choice: dropped["open"]
	rebuild_with(f, panel, _shipped(f))
	timer = _timers(f)[0]

	dropped["open"] = False
	f.fake.emit(change(f))

	assert len(panel.providerList.items) == len(_shipped(f).provider_groups)
	assert timer.stopped is True
	assert panel._deferTimer is None


def _focus(panel, window):
	panel._findFocus = lambda: window


def test_focus_in_a_box_the_rebuild_hides_defers_it(monkeypatch):
	f = live_fixture(monkeypatch, corrector_config_id=SOL[0], execution_channel=SOL[1])
	panel = f.make_panel()
	_focus(panel, panel.accountTextCtrlMap["OpenAI"])
	catalog = panel.catalog

	rebuild_with(f, panel, _without_group(f, "OpenAI"))
	assert panel.catalog is catalog
	assert _shown_boxes(panel) == ["OpenAI"]
	assert len(_live_timers(f)) == 1

	_focus(panel, panel.languageList)
	_live_timers(f)[0].fire()
	assert panel.catalog is f.box["catalog"]
	assert _shown_boxes(panel) == ["Coseeing"]
	assert panel._deferTimer is None
	assert len(_timers(f)) == 1


def test_focus_in_a_box_that_stays_does_not_defer(monkeypatch):
	f = live_fixture(monkeypatch, corrector_config_id=SOL[0], execution_channel=SOL[1])
	panel = f.make_panel()
	field = panel.accountTextCtrlMap["OpenAI"]
	field.SetValue("typing")
	_focus(panel, field)

	rebuild_with(f, panel, _shipped_without("deepseek-flash&DeepSeek")(f))

	assert panel.catalog is f.box["catalog"]
	assert _shown_boxes(panel) == ["OpenAI"]
	assert field.GetValue() == "typing"
	assert getattr(field, "focused", False) is False
	assert _timers(f) == []


def test_focus_on_the_clean_button_defers_when_coseeing_is_left(monkeypatch):
	# F1: the untouched panel of an offline local user moves to their own
	# model when the list arrives, which would hide the focused clean button.
	f = live_fixture(monkeypatch, corrector_config_id="gpt-6-luna&OpenAI", execution_channel="local")
	f.box["catalog"] = _bundled_only(f)
	panel = f.make_panel()
	_focus(panel, panel.coseeingCleanButton)
	catalog = panel.catalog

	rebuild_with(f, panel, _shipped(f))

	assert panel.catalog is catalog
	assert _shown_boxes(panel) == ["Coseeing"]
	assert [timer.delay_ms for timer in _live_timers(f)] == [300]


def test_the_poll_stops_when_the_panel_is_destroyed(monkeypatch):
	f = live_fixture(monkeypatch)
	f.box["catalog"] = _bundled_only(f)
	panel = f.make_panel()
	panel._isDroppedDown = lambda choice: True
	items = list(panel.providerList.items)
	rebuild_with(f, panel, _shipped(f))
	timer = _timers(f)[0]

	panel.bindings[f.plugin.wx.EVT_WINDOW_DESTROY](DestroyEvent(panel))
	assert timer.stopped is True
	panel.alive = False
	timer.fire()

	assert panel.providerList.items == items
	assert f.fake.listeners == []


@pytest.mark.parametrize("winuser, expected", [("absent", False), ("dropped", True), ("closed", False)])
def test_the_drop_down_probe(monkeypatch, winuser, expected):
	import sys

	f = live_fixture(monkeypatch)
	panel = f.make_panel()
	calls = []
	if winuser == "absent":
		monkeypatch.delitem(sys.modules, "winUser", raising=False)
	else:
		def send_message(handle, message, wparam, lparam):
			calls.append((handle, message, wparam, lparam))
			return 1 if winuser == "dropped" else 0

		monkeypatch.setitem(sys.modules, "winUser", SimpleNamespace(sendMessage=send_message))

	assert f.dialogs.LLMSettingsPanel._isDroppedDown(panel, panel.providerList) is expected
	if winuser != "absent":
		assert calls == [(panel.providerList.GetHandle(), 0x0157, 0, 0)]


# --- Task 15: announcements (R3, R8, C11) -----------------------------------

UPDATED = "Model list updated."
UPDATE_FAILED = "Model list update failed."
ANNOUNCEMENT_ROWS = [
	("success-background", (True, "succeeded", False), [UPDATED]),
	("success-user", (True, "succeeded", True), [UPDATED]),
	("failure-panel-open", (False, "failed", True), [UPDATE_FAILED]),
	("failure-url-change", (False, "failed", True), [UPDATE_FAILED]),
	("failure-timer", (False, "failed", False), []),
	("failure-startup", (False, "failed", False), []),
]


@pytest.mark.parametrize("event, expected", [row[1:] for row in ANNOUNCEMENT_ROWS], ids=[row[0] for row in ANNOUNCEMENT_ROWS])
def test_announcements_table(monkeypatch, event, expected):
	f = live_fixture(monkeypatch)
	panel = f.make_panel()
	if event[1] == "failed":
		set_status(f, "none", "failed")

	f.fake.emit(change(f, *event))

	assert f.messages == expected
	# Spoken once: a later notification without an outcome says nothing.
	f.fake.emit(change(f))
	assert f.messages == expected
	assert panel  # still alive


def _hide(panel):
	panel.shown = False


def _deactivate(panel):
	panel.active = False


def _destroy(panel):
	panel.alive = False


SILENT_ROWS = [
	("refresh-start", (False, None, False), None),
	("d8-swap", (True, None, True), None),
	("hidden", (True, "succeeded", True), _hide),
	("inactive", (True, "succeeded", True), _deactivate),
	("destroyed", (True, "succeeded", True), _destroy),
]


@pytest.mark.parametrize("event, condition", [row[1:] for row in SILENT_ROWS], ids=[row[0] for row in SILENT_ROWS])
def test_no_announcement_when(monkeypatch, event, condition):
	f = live_fixture(monkeypatch)
	panel = f.make_panel()
	if condition is not None:
		condition(panel)

	f.fake.emit(change(f, *event))

	assert f.messages == []
	# A dropped announcement is not kept for later (spec 11).
	panel.shown = panel.active = True
	f.fake.emit(change(f))
	assert f.messages == []


def test_only_the_latest_speakable_outcome_behind_a_deferral_is_spoken(monkeypatch):
	f = live_fixture(monkeypatch)
	f.box["catalog"] = _bundled_only(f)
	panel = f.make_panel()
	dropped = {"open": True}
	panel._isDroppedDown = lambda choice: dropped["open"]
	rebuild_with(f, panel, _shipped(f))

	f.fake.emit(change(f, False, "failed", True))
	f.fake.emit(change(f, True, "succeeded", False))
	assert f.messages == []

	dropped["open"] = False
	_timers(f)[0].fire()
	assert f.messages == [UPDATED]


def test_a_background_failure_behind_a_deferral_keeps_the_pending_message(monkeypatch):
	f = live_fixture(monkeypatch)
	f.box["catalog"] = _bundled_only(f)
	panel = f.make_panel()
	dropped = {"open": True}
	panel._isDroppedDown = lambda choice: dropped["open"]
	rebuild_with(f, panel, _shipped(f))

	f.fake.emit(change(f, False, "failed", True))
	f.fake.emit(change(f, False, "failed", False))
	assert f.messages == []

	dropped["open"] = False
	_timers(f)[0].fire()
	assert f.messages == [UPDATE_FAILED]


def test_a_description_change_alone_speaks_nothing(monkeypatch):
	# R11: panelDescription changes; only R3/R8 outcomes are spoken.
	f = live_fixture(monkeypatch)
	panel = f.make_panel()

	set_status(f, "none", "failed")
	f.fake.emit(change(f))

	assert panel.panelDescription == _text("failed")
	assert f.messages == []


def test_the_new_strings_have_translator_comments_and_zh_tw_translations():
	from test_catalog_url_dialog import ADDON, _assert_translated

	_assert_translated(ADDON / "dialogs.py", {UPDATED: "模型清單已更新。", UPDATE_FAILED: "模型清單更新失敗。"})


def test_the_panel_follows_a_real_updater_end_to_end(monkeypatch, tmp_path):
	from test_catalog_retry import FakeScheduler
	from test_catalog_settings_panel import _refuse, _serve_the_server_catalog, real_updater

	f = _panel_fixture(monkeypatch)
	messages = []
	monkeypatch.setattr(f.dialogs, "ui", SimpleNamespace(message=messages.append))
	network = {"get": _refuse}
	scheduler = FakeScheduler()
	updater = real_updater(f, tmp_path, lambda url, **kwargs: network["get"](url, **kwargs), schedule=scheduler)
	url = "https://wordbridge.coseeing.org"
	f.dialogs.registry.replace(updater.initial_catalog(url))
	updater.refresh(url)
	updater.run_latest()
	assert [timer.delay_ms for timer in scheduler.live()] == [60_000]
	f.dialogs.catalog_updater.install(updater)
	try:
		panel = f.make_panel()
		assert len(updater.threads) == 2  # R1
		assert panel.providerList.items == ["Coseeing"]

		updater.run_latest()
		assert messages == [UPDATE_FAILED]
		assert panel.catalogStatusText.label == _text("failed")
		# R6: the panel-open failure continues the schedule.
		assert [timer.delay_ms for timer in scheduler.live()] == [2 * 60_000]

		network["get"] = _serve_the_server_catalog
		scheduler.live()[0].fire()
		updater.run_latest()
		assert messages == [UPDATE_FAILED, UPDATED]
		assert panel.providerList.items == list(f.plugin.catalog.provider_groups)
		assert panel.catalogStatusText.label == ""
		assert scheduler.live() == []
	finally:
		f.dialogs.catalog_updater.uninstall()
