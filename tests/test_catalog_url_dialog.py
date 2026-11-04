"""The "Set Model List URL" dialog (retry spec R12, section 20).

_load_nvda_plugin and the widget stubs are imported at function scope (via
test_catalog_settings_panel's fixture), never at module scope.
"""

import importlib
import io
import re
import tokenize
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_catalog_settings_panel import DEFAULT_URL, INSECURE, MALFORMED, _panel_fixture


ADDON = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge"
PO = Path(__file__).resolve().parents[1] / "addon" / "locale" / "zh_TW" / "LC_MESSAGES" / "nvda.po"
RETURN_CODE = SimpleNamespace(OK=5100, CANCEL=5101, YES=5103, NO=5104)
ID_OK = 5100
NOT_TESTED = "The model list URL has not been tested. Save it without testing it first?"
FAILED = "The model list URL failed the test. Save it anyway?"


class FakeMessageDialog:
	"""gui.message.MessageDialog: records what it was built with and answers.

	An OK-only dialog is a message, not a question: it is recorded with the
	alerts (and its type in alert_types) when shown, not in instances."""

	instances = []
	alerts = []
	alert_types = []
	answer = None

	def __init__(self, parent, message, title="", dialogType="STANDARD", *, buttons=None, helpId=""):
		self.parent, self.message, self.title, self.dialog_type, self.buttons = parent, message, title, dialogType, buttons
		self.default_focus = None
		self.escape_id = None
		if not self._is_message():
			FakeMessageDialog.instances.append(self)

	def _is_message(self):
		return tuple(self.buttons or ()) == ("OK",)

	def setDefaultFocus(self, id):
		self.default_focus = id
		return self

	def SetEscapeId(self, id):
		self.escape_id = id
		return self

	def ShowModal(self):
		if self._is_message():
			FakeMessageDialog.alerts.append((self.message, self.title, self.parent))
			FakeMessageDialog.alert_types.append(self.dialog_type)
			return RETURN_CODE.OK
		return FakeMessageDialog.answer

	@classmethod
	def alert(cls, message, caption="", parent=None, **kwargs):
		cls.alerts.append((message, caption, parent))
		cls.alert_types.append("STANDARD")


class StubPanel:
	def __init__(self, order):
		self.order = order

	def _updateCatalogUrlBox(self):
		self.order.append("box")


def dialog_fixture(monkeypatch, **settings):
	f = _panel_fixture(monkeypatch, **settings)
	f.module = importlib.import_module(f.plugin.__name__ + ".catalog_url_dialog")
	FakeMessageDialog.instances = []
	FakeMessageDialog.alerts = []
	FakeMessageDialog.alert_types = []
	FakeMessageDialog.answer = None
	monkeypatch.setattr(f.plugin.gui, "message", SimpleNamespace(
		MessageDialog=FakeMessageDialog,
		DefaultButtonSet=SimpleNamespace(YES_NO_CANCEL="YES_NO_CANCEL"),
		ReturnCode=RETURN_CODE,
		DialogType=SimpleNamespace(STANDARD="STANDARD", WARNING="WARNING", ERROR="ERROR"),
		DefaultButton=SimpleNamespace(OK="OK"),
	), raising=False)
	f.order = []
	f.panel = StubPanel(f.order)
	repository = f.plugin.SettingsRepository(f.settings, f.dialogs.registry.current)

	def make_dialog():
		dialog = f.module.CatalogUrlDialog(None, settings=repository, panel=f.panel)
		dialog.DestroyLater = lambda: f.order.append("close")
		return dialog

	f.make_dialog = make_dialog
	return f


def _warnings():
	return [dialog.message for dialog in FakeMessageDialog.instances]


def _errors():
	return [alert[0] for alert in FakeMessageDialog.alerts]


# --- Task 12: the dialog and its OK -----------------------------------------

def test_the_dialog_shows_the_stored_url_and_focuses_it(monkeypatch):
	f = dialog_fixture(monkeypatch, catalog_url="http://localhost:8000")

	dialog = f.make_dialog()

	assert f.module.CatalogUrlDialog.title == "Set Model List URL"
	assert dialog.urlCtrl.GetValue() == "http://localhost:8000"
	assert dialog.urlCtrl.focused is True
	assert dialog.testButton.IsEnabled() is True
	assert dialog.testStatus == "untested"
	assert dialog.savedUrl is None


@pytest.mark.parametrize("text, enabled", [("", False), ("   ", False), (DEFAULT_URL, True)], ids=["empty", "blank", "url"])
def test_test_is_enabled_only_for_non_blank_text(monkeypatch, text, enabled):
	f = dialog_fixture(monkeypatch)
	dialog = f.make_dialog()

	dialog.urlCtrl.SetValue(text)
	dialog._onTextChange(None)

	assert dialog.testButton.IsEnabled() is enabled


LOCAL = "http://localhost:8000"
OK_ROWS = [
	# id, stored (None = the default), typed, status, answer, saved, closed, error, warning
	("unchanged-same", None, DEFAULT_URL, "untested", None, None, True, None, None),
	("unchanged-other-spelling", None, "  HTTPS://WORDBRIDGE.COSEEING.ORG/  ", "untested", None, None, True, None, None),
	("passed", None, "  " + LOCAL + "  ", "passed", None, LOCAL, True, None, None),
	("untested-yes", None, LOCAL, "untested", RETURN_CODE.YES, LOCAL, True, None, NOT_TESTED),
	("untested-no", None, LOCAL, "untested", RETURN_CODE.NO, None, True, None, NOT_TESTED),
	("untested-cancel", None, LOCAL, "untested", RETURN_CODE.CANCEL, None, False, None, NOT_TESTED),
	("failed-yes", None, LOCAL, "failed", RETURN_CODE.YES, LOCAL, True, None, FAILED),
	("failed-no", None, LOCAL, "failed", RETURN_CODE.NO, None, True, None, FAILED),
	("empty", None, "", "untested", None, "", True, None, None),
	("invalid-malformed", None, "ftp://x", "untested", None, None, False, MALFORMED, None),
	("invalid-insecure", None, "http://example.com", "untested", None, None, False, INSECURE, None),
]


@pytest.mark.parametrize(
	"stored, typed, status, answer, saved, closed, error, warning", [row[1:] for row in OK_ROWS], ids=[row[0] for row in OK_ROWS],
)
def test_ok_table(monkeypatch, stored, typed, status, answer, saved, closed, error, warning):
	settings = {} if stored is None else {"catalog_url": stored}
	f = dialog_fixture(monkeypatch, **settings)
	dialog = f.make_dialog()
	dialog.urlCtrl.SetValue(typed)
	dialog.testStatus = status
	dialog.urlCtrl.focused = False
	FakeMessageDialog.answer = answer

	dialog.onOk(None)

	if saved is None:
		assert f.settings.get("catalog_url", stored) == stored
	else:
		assert f.settings["catalog_url"] == saved
	assert dialog.savedUrl == saved
	assert getattr(dialog, "return_codes", []) == ([ID_OK] if closed else [])
	assert f.order == (["box"] if saved is not None else []) + (["close"] if closed else [])
	assert _warnings() == ([warning] if warning else [])
	assert _errors() == ([error] if error else [])
	assert getattr(dialog.urlCtrl, "focused", False) is (error is not None)


def test_the_box_is_updated_before_the_dialog_closes(monkeypatch):
	f = dialog_fixture(monkeypatch)
	dialog = f.make_dialog()
	dialog.urlCtrl.SetValue(LOCAL)
	dialog.testStatus = "passed"

	dialog.onOk(None)

	assert f.order == ["box", "close"]


def test_editing_the_text_resets_a_passed_test(monkeypatch):
	f = dialog_fixture(monkeypatch)
	dialog = f.make_dialog()
	dialog.testStatus = "passed"

	dialog._onTextChange(None)

	assert dialog.testStatus == "untested"


def test_the_text_and_test_handlers_are_bound(monkeypatch):
	f = dialog_fixture(monkeypatch)

	dialog = f.make_dialog()

	assert dialog.urlCtrl.bindings[f.plugin.wx.EVT_TEXT] == dialog._onTextChange
	assert dialog.testButton.bindings[f.plugin.wx.EVT_BUTTON] == dialog._onTest


@pytest.mark.parametrize("failed, text", [(False, NOT_TESTED), (True, FAILED)], ids=["untested", "failed"])
def test_the_warning_defaults_to_cancel(monkeypatch, failed, text):
	f = dialog_fixture(monkeypatch)
	dialog = f.make_dialog()
	FakeMessageDialog.answer = RETURN_CODE.NO

	assert dialog._askSaveAnyway(failed) == RETURN_CODE.NO

	[warning] = FakeMessageDialog.instances
	assert (warning.parent, warning.message, warning.title, warning.dialog_type, warning.buttons) == (
		dialog, text, "Warning", "WARNING", "YES_NO_CANCEL",
	)
	assert warning.default_focus == RETURN_CODE.CANCEL
	assert warning.escape_id == RETURN_CODE.CANCEL


def test_an_error_is_an_error_alert_on_the_dialog(monkeypatch):
	f = dialog_fixture(monkeypatch)
	dialog = f.make_dialog()

	dialog._showError("message")

	assert FakeMessageDialog.alerts == [("message", "Error", dialog)]
	# Final review m6: NVDA's error icon and sound, as _SetURLDialog's failure.
	assert FakeMessageDialog.alert_types == ["ERROR"]


# --- translator comments and zh_TW entries ----------------------------------

def _po_entries():
	"""msgid -> msgstr for the single-line entries of nvda.po."""
	text = PO.read_text(encoding="utf8")
	return {
		match.group(1).replace('\\"', '"'): match.group(2).replace('\\"', '"')
		for match in re.finditer(r'^msgid "(.*)"\nmsgstr "(.*)"$', text, flags=re.M)
	}


def _translation_calls(path):
	"""(line number, has a Translators comment) for every `_(` call.

	xgettext --add-comments=Translators: semantics: the comment block (one
	or more comment lines) must end on the line right before the line that
	holds `_(`. Comments and strings mentioning `_()` are not calls.
	"""
	source = path.read_text(encoding="utf8")
	lines = source.splitlines()
	tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
	calls = []
	for index, token in enumerate(tokens[:-1]):
		following = tokens[index + 1]
		if token.type == tokenize.NAME and token.string == "_" and following.string == "(":
			previous = tokens[index - 1] if index else None
			if previous is not None and previous.string == ".":
				continue
			line = token.start[0]
			block = []
			above = line - 2
			while above >= 0 and lines[above].strip().startswith("#"):
				block.append(lines[above].strip())
				above -= 1
			calls.append((line, any(comment.startswith("# Translators:") for comment in block)))
	return calls


@pytest.mark.parametrize("name", ["dialogs.py", "catalog_url_dialog.py"])
def test_every_translatable_string_has_a_translators_comment(name):
	# C23: no tests/test_translator_comments.py exists in this repository.
	calls = _translation_calls(ADDON / name)

	assert calls
	assert [line for line, commented in calls if not commented] == []


def _assert_translated(path, entries):
	"""Each msgid sits in a `_(` call with a Translators comment (on the
	call's line or the line after a bare `_(`), and nvda.po has its zh_TW."""
	lines = path.read_text(encoding="utf8").splitlines()
	calls = dict(_translation_calls(path))
	po = _po_entries()
	for msgid, msgstr in entries.items():
		literal = '"' + msgid.replace('"', '\\"') + '"'
		found = [number for number, line in enumerate(lines, 1) if "_(" + literal in line]
		found += [
			number - 1 for number, line in enumerate(lines, 1)
			if line.strip().startswith(literal) and number > 1 and lines[number - 2].rstrip().endswith("_(")
		]
		assert found, msgid
		for number in found:
			assert calls.get(number) is True, (msgid, number)
		assert po.get(msgid) == msgstr, msgid


TASK12_STRINGS = {
	"Set Model List URL": "設定模型清單網址",
	"&Test...": "測試(&T)...",
	"Warning": "警告",
	"Error": "錯誤",
	FAILED: "模型清單網址測試失敗。仍要儲存嗎？",
	NOT_TESTED: "模型清單網址尚未測試。確定不先測試就儲存嗎？",
	"Model list URL:": "模型清單網址：",
	MALFORMED: "請輸入完整的網址，例如 https://wordbridge.coseeing.org，或將此欄位留空。",
	INSECURE: "模型清單網址必須以 https:// 開頭。只有 localhost 可以使用 http://。",
}


def test_the_dialog_strings_have_translator_comments_and_translations():
	_assert_translated(ADDON / "catalog_url_dialog.py", TASK12_STRINGS)


# --- Task 13: Test... -------------------------------------------------------

def _probe(f, kind, detail="", models=0):
	return f.plugin.dialogs.catalog_updater.ProbeResult(kind, detail, models)


def _record_threads(monkeypatch, f):
	threads = []
	monkeypatch.setattr(f.module, "_start_probe_thread", lambda target, args: threads.append((target, args)))
	return threads


def _progress(f):
	return f.plugin.gui.IndeterminateProgressDialog.instances


@pytest.mark.parametrize("text, error", [("ftp://x", MALFORMED), ("http://example.com", INSECURE)], ids=["invalid", "insecure"])
def test_test_validates_first_without_a_request(monkeypatch, text, error):
	f = dialog_fixture(monkeypatch)
	threads = _record_threads(monkeypatch, f)
	_progress(f).clear()
	dialog = f.make_dialog()
	dialog.urlCtrl.SetValue(text)

	dialog._onTest(None)

	assert _errors() == [error]
	assert threads == []
	assert _progress(f) == []


def test_test_runs_off_the_ui_thread_and_posts_the_result(monkeypatch):
	f = dialog_fixture(monkeypatch)
	threads = _record_threads(monkeypatch, f)
	probed = []
	result = _probe(f, "ok", models=3)
	monkeypatch.setattr(f.module.catalog_updater, "probe_url", lambda url: probed.append(url) or result)
	_progress(f).clear()
	dialog = f.make_dialog()
	dialog.urlCtrl.SetValue("  " + LOCAL + " ")
	f.queued.clear()

	dialog._onTest(None)
	assert probed == []
	assert threads == [(dialog._runProbe, (LOCAL,))]
	[progress] = _progress(f)
	assert (progress.parent, progress.title, progress.message) == (dialog, "Set Model List URL", "Validating the model list URL...")

	target, args = threads[0]
	target(*args)
	assert probed == [LOCAL]
	assert f.queued == [(dialog._onProbeDone, (LOCAL, result))]
	assert progress.done_calls == 0

	callback, args = f.queued.pop()
	callback(*args)
	assert progress.done_calls == 1
	assert FakeMessageDialog.alerts == [("The model list loaded. It offers 3 models.", "Success", dialog)]
	assert dialog.testStatus == "passed"


def test_the_probe_thread_is_a_named_daemon(monkeypatch):
	import threading

	f = dialog_fixture(monkeypatch)
	ran = threading.Event()
	seen = {}

	def target(value):
		seen["thread"] = threading.current_thread()
		seen["value"] = value
		ran.set()

	f.module._start_probe_thread(target, ("x",))

	assert ran.wait(5)
	assert seen["value"] == "x"
	assert seen["thread"] is not threading.main_thread()
	assert seen["thread"].daemon is True
	assert seen["thread"].name == "wordbridge-catalog-url-test"


NETWORK_TIP = "There was a network error. Check that you are connected to the internet and try again."
OTHER_TIP = "Make sure you are connected to the internet and the URL is correct."
RESULT_ROWS = [
	("ok-1", ("ok", "", 1), "The model list loaded. It offers 1 model.", True),
	("ok-many", ("ok", "", 12), "The model list loaded. It offers 12 models.", True),
	("network", ("network", "OSError", 0), "The model list URL failed the test. " + NETWORK_TIP, False),
	("http_status", ("http_status", "404", 0),
		"The model list URL failed the test. The server answered with HTTP status 404. Check that the URL is correct.", False),
	("not_a_list", ("not_a_list", "", 0),
		"The model list URL failed the test. The server's answer is not a WordBridge model list. Check that the URL is correct.",
		False),
	("no_models", ("no_models", "", 0), "The model list URL failed the test. The model list offers no model WordBridge can use.", False),
	("disallowed_hosts", ("disallowed_hosts", "", 0),
		"The model list URL failed the test. The model list names only provider addresses WordBridge does not allow.", False),
	("failed", ("failed", "", 0), "The model list URL failed the test. " + OTHER_TIP, False),
	("unavailable", ("unavailable", "", 0), "The model list URL failed the test. " + OTHER_TIP, False),
]


@pytest.mark.parametrize("probe, message, ok", [row[1:] for row in RESULT_ROWS], ids=[row[0] for row in RESULT_ROWS])
def test_test_result_messages(monkeypatch, probe, message, ok):
	f = dialog_fixture(monkeypatch)
	dialog = f.make_dialog()
	dialog.urlCtrl.SetValue(LOCAL)

	dialog._onProbeDone(LOCAL, _probe(f, *probe))

	assert f.module.probe_result_message(_probe(f, *probe)) == message
	assert FakeMessageDialog.alerts == [(message, "Success" if ok else "Error", dialog)]
	# Final review m6: a failure has NVDA's error icon and sound (_SetURLDialog
	# uses wx.ICON_ERROR); a success stays a plain message.
	assert FakeMessageDialog.alert_types == ["STANDARD" if ok else "ERROR"]
	assert dialog.testStatus == ("passed" if ok else "failed")


def test_a_result_for_changed_text_leaves_the_status_untested(monkeypatch):
	f = dialog_fixture(monkeypatch)
	_record_threads(monkeypatch, f)
	dialog = f.make_dialog()
	dialog.urlCtrl.SetValue(LOCAL)
	dialog._onTest(None)
	dialog.urlCtrl.SetValue("http://localhost:9000")
	dialog._onTextChange(None)

	dialog._onProbeDone(LOCAL, _probe(f, "ok", models=1))

	assert len(FakeMessageDialog.alerts) == 1
	assert dialog.testStatus == "untested"


def test_a_result_after_the_dialog_is_gone_does_nothing(monkeypatch):
	f = dialog_fixture(monkeypatch)
	_record_threads(monkeypatch, f)
	_progress(f).clear()
	dialog = f.make_dialog()
	dialog.urlCtrl.SetValue(LOCAL)
	dialog._onTest(None)
	dialog.alive = False

	dialog._onProbeDone(LOCAL, _probe(f, "ok", models=1))

	assert FakeMessageDialog.alerts == []
	assert _progress(f)[0].done_calls == 0
	assert dialog.testStatus == "untested"


def test_a_passed_test_then_ok_saves_without_a_warning(monkeypatch, tmp_path):
	from test_catalog_settings_panel import _serve_the_server_catalog, real_updater

	f = dialog_fixture(monkeypatch)
	threads = _record_threads(monkeypatch, f)
	updater = real_updater(f, tmp_path, _serve_the_server_catalog)
	updater.initial_catalog(DEFAULT_URL)
	f.dialogs.catalog_updater.install(updater)
	try:
		dialog = f.make_dialog()
		dialog.urlCtrl.SetValue("https://mirror.test/catalog")
		f.queued.clear()
		dialog._onTest(None)
		target, args = threads[0]
		target(*args)
		callback, args = f.queued.pop()
		callback(*args)
		assert dialog.testStatus == "passed"

		dialog.onOk(None)
	finally:
		f.dialogs.catalog_updater.uninstall()

	assert f.settings["catalog_url"] == "https://mirror.test/catalog"
	assert dialog.savedUrl == "https://mirror.test/catalog"
	assert FakeMessageDialog.instances == []
	assert updater.installed == []


TASK13_STRINGS = {
	"Validating the model list URL...": "正在驗證模型清單網址...",
	"Success": "成功",
	"The model list loaded. It offers {count} model.": "已載入模型清單，共有 {count} 個模型。",
	"The model list loaded. It offers {count} models.": "已載入模型清單，共有 {count} 個模型。",
	"The model list URL failed the test. {tip}": "模型清單網址測試失敗。{tip}",
	NETWORK_TIP: "發生網路錯誤。請確認已連上網際網路，然後再試一次。",
	"The server answered with HTTP status {status}. Check that the URL is correct.": "伺服器回應 HTTP 狀態碼 {status}。請確認網址是否正確。",
	"The server's answer is not a WordBridge model list. Check that the URL is correct.":
		"伺服器的回應不是 WordBridge 模型清單。請確認網址是否正確。",
	"The model list offers no model WordBridge can use.": "這份模型清單沒有 WordBridge 可以使用的模型。",
	"The model list names only provider addresses WordBridge does not allow.":
		"這份模型清單列出的服務提供者網址都不在 WordBridge 允許的範圍內。",
	OTHER_TIP: "請確認已連上網際網路，且網址正確。",
}


def test_the_test_strings_have_translator_comments_and_translations():
	_assert_translated(ADDON / "catalog_url_dialog.py", TASK13_STRINGS)
