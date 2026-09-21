from decimal import Decimal
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_INIT = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge" / "__init__.py"

SETTINGS = {
	"corrector_config_id": "deepseek-v4-flash&DeepSeek",
	"execution_channel": "Coseeing",
	"api_key": {},
	"language": "zh_traditional",
	"typo_correction_mode": "standard",
	"customized_words_enable": False,
	"auto_display_report": False,
}


def test_unformattable_cost_reports_an_explicit_unavailable_state(monkeypatch):
	from test_coseeing_auth_nvda import _load_nvda_plugin
	plugin_module = _load_nvda_plugin(monkeypatch, SETTINGS, [], [])[0]
	notified = []

	class _Unformattable:
		pass

	def failing(value):
		raise TypeError("not a Decimal")

	monkeypatch.setattr(plugin_module, "decimal_to_str_0", failing)

	instance = object.__new__(plugin_module.GlobalPlugin)
	instance._notify = notified.append

	plugin_module.GlobalPlugin._report_cost(instance, _Unformattable())

	assert len(notified) == 1
	assert "USD" not in notified[0]


def test_formattable_cost_is_reported_with_its_value(monkeypatch):
	from test_coseeing_auth_nvda import _load_nvda_plugin
	plugin_module = _load_nvda_plugin(monkeypatch, SETTINGS, [], [])[0]
	notified = []

	instance = object.__new__(plugin_module.GlobalPlugin)
	instance._notify = notified.append

	plugin_module.GlobalPlugin._report_cost(instance, Decimal("0.0123"))

	assert len(notified) == 1
	assert "USD" in notified[0]


def test_worker_failure_path_has_no_unreachable_code():
	source = ADDON_INIT.read_text(encoding="utf8")

	assert "raise e" not in source


def test_entry_point_has_no_bare_or_blanket_except():
	source = ADDON_INIT.read_text(encoding="utf8")

	assert "except:" not in source
	assert "except BaseException" not in source


def test_normal_flow_messages_are_not_logged_as_warnings():
	source = ADDON_INIT.read_text(encoding="utf8")

	for message in (
		'log.warning(_("No errors in the selected text."))',
		'log.warning(_("The corrected text has been copied to the clipboard."))',
	):
		assert message not in source


def test_latest_action_publisher_keeps_its_load_bearing_name():
	source = ADDON_INIT.read_text(encoding="utf8")

	assert "def _publish_latest_action(self, action):" in source
	assert "def _set_latest_action" not in source
