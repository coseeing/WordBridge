import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from lib.decimalUtils import decimal_to_str_0 as real_decimal_to_str_0


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
	# LOAD-BEARING IMPORT PLACEMENT: this import must stay inside the test
	# function, not at module scope. tests/test_coseeing_auth_nvda.py:32-65
	# installs fake _wb_vendor modules, imports the real lib.coseeing_auth
	# under them (binding its exception classes -- see lib/coseeing_auth.py:44
	# -- to those fakes), then restores only the vendor stubs afterwards.
	# sys.modules["lib.coseeing_auth"] stays cached with the poisoned
	# bindings for the rest of the process, because Python does not
	# re-execute an already-imported module. Today tests/test_coseeing_auth.py
	# collects (and does its own real `import lib.coseeing_auth`) before
	# tests/test_coseeing_auth_nvda.py, so it wins that race and the poison
	# never matters -- but this file collects *before* test_coseeing_auth.py
	# alphabetically ("corr" < "cose"). A module-scope import here would force
	# test_coseeing_auth_nvda.py to run during *this* file's collection,
	# before test_coseeing_auth.py ever imports lib.coseeing_auth for real,
	# handing the race to the poisoned import instead -- 17 unrelated
	# failures in test_coseeing_auth.py. Keeping the import inside the test
	# function defers it to execution time, after every file's collection
	# (including test_coseeing_auth.py's) has already run. See the
	# `# THE NAME IS LOAD-BEARING:` block at __init__.py's
	# _publish_latest_action for this codebase's existing convention for
	# flagging exactly this class of hazard.
	from test_coseeing_auth_nvda import _load_nvda_plugin

	plugin_module = _load_nvda_plugin(monkeypatch, SETTINGS, [], [])[0]
	# _load_nvda_plugin() stubs decimal_to_str_0 as plain str() (see
	# test_coseeing_auth_nvda.py:223), which never raises TypeError for a
	# non-Decimal value the way the real function does. Swap in the real
	# implementation so this test exercises the real coercion/formatting
	# behaviour of _report_cost(), not the harness's simplified stand-in.
	monkeypatch.setattr(plugin_module, "decimal_to_str_0", real_decimal_to_str_0)
	notified = []
	warnings = []
	monkeypatch.setattr(plugin_module, "log", SimpleNamespace(
		warning=lambda *args, **kwargs: warnings.append(args),
		info=lambda *args, **kwargs: None,
		debug=lambda *args, **kwargs: None,
		exception=lambda *args, **kwargs: None,
	))

	class _Unformattable:
		# __str__ deliberately returns something Decimal(...) cannot parse.
		# That is what actually drives _report_cost() into its except branch
		# (Decimal(str(cost)) raising InvalidOperation) -- not a monkeypatch
		# of decimal_to_str_0, which the real coercion step never even
		# reaches for a value like this.
		def __str__(self):
			return "not-a-number"

	instance = object.__new__(plugin_module.GlobalPlugin)
	instance._notify = notified.append

	plugin_module.GlobalPlugin._report_cost(instance, _Unformattable())

	assert notified == ["This task's cost is unavailable."]
	assert len(warnings) == 1
	assert warnings[0][1] == "InvalidOperation"


def test_formattable_cost_is_reported_with_its_value(monkeypatch):
	# See the load-bearing-import comment on
	# test_unformattable_cost_reports_an_explicit_unavailable_state above --
	# it applies here too.
	from test_coseeing_auth_nvda import _load_nvda_plugin

	plugin_module = _load_nvda_plugin(monkeypatch, SETTINGS, [], [])[0]
	# See the decimal_to_str_0 note in
	# test_unformattable_cost_reports_an_explicit_unavailable_state above.
	monkeypatch.setattr(plugin_module, "decimal_to_str_0", real_decimal_to_str_0)
	notified = []

	instance = object.__new__(plugin_module.GlobalPlugin)
	instance._notify = notified.append

	plugin_module.GlobalPlugin._report_cost(instance, Decimal("0.0123"))

	assert notified == ["This task costs 0.0123 USD."]


def test_cost_matching_the_coseeing_response_shape_is_reported_with_its_value(monkeypatch):
	# Regression test for the Coseeing channel's actual shape: __init__.py's
	# Coseeing branch does `cost = result["cost"]` straight out of
	# data.json(), so cost is a plain JSON float/int, never a Decimal --
	# unlike the local channel's Executor.get_total_cost(). decimal_to_str_0()
	# raises TypeError on anything that isn't already a Decimal, so without
	# coercion this is the exact input that made every successful Coseeing
	# correction report "cost unavailable".
	from test_coseeing_auth_nvda import _load_nvda_plugin

	plugin_module = _load_nvda_plugin(monkeypatch, SETTINGS, [], [])[0]
	# See the decimal_to_str_0 note in
	# test_unformattable_cost_reports_an_explicit_unavailable_state above.
	monkeypatch.setattr(plugin_module, "decimal_to_str_0", real_decimal_to_str_0)
	notified = []

	instance = object.__new__(plugin_module.GlobalPlugin)
	instance._notify = notified.append

	plugin_module.GlobalPlugin._report_cost(instance, 0.0123)

	assert notified == ["This task costs 0.0123 USD."]


def test_worker_failure_path_has_no_unreachable_code():
	source = ADDON_INIT.read_text(encoding="utf8")

	# A plain "raise e" not in source substring check would false-fail on a
	# legitimate future `raise error`/`raise err`/`raise exc` -- this file
	# already binds `except Exception as error:` elsewhere -- since "raise e"
	# is a literal prefix of all three. Match "raise e" as its own token.
	assert re.search(r"\braise e\b", source) is None


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
