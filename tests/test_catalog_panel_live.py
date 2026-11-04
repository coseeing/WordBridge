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
