import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ADDON_PATH = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge"

PAYLOAD = "</script><script>alert(1)</script><img src=x onerror=alert(1)>\"'&\n繁體简体"


def _load_view_html(monkeypatch):
	"""Load lib/viewHTML.py without registering it in sys.modules.

	Keeping it out of sys.modules avoids the cross-test pollution that the
	existing suite suffers from.
	"""
	monkeypatch.setitem(sys.modules, "addonHandler", types.SimpleNamespace(initTranslation=lambda: None))
	spec = importlib.util.spec_from_file_location(
		"wordbridge_view_html_under_test",
		ADDON_PATH / "lib" / "viewHTML.py",
	)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def _inline_config(html):
	"""Return the JSON text assigned to window.contentConfig."""
	assignment = html.split("window.contentConfig = ", 1)[1]
	return assignment.split(";", 1)[0]


def _render(monkeypatch, tmp_path, diff):
	view_html = _load_view_html(monkeypatch)
	src = tmp_path / "result.txt"
	src.write_text(json.dumps(diff, ensure_ascii=False), encoding="utf8")
	dst = tmp_path / "result.html"
	view_html.text2template(str(src), str(dst))
	return dst.read_text(encoding="utf8")


def test_inline_config_contains_no_raw_angle_brackets(monkeypatch, tmp_path):
	html = _render(monkeypatch, tmp_path, [{"operation": "replace", "before_text": PAYLOAD, "after_text": PAYLOAD}])
	config = _inline_config(html)
	assert "<" not in config
	assert ">" not in config
	assert "&" not in config


def test_inline_config_round_trips_unchanged(monkeypatch, tmp_path):
	diff = [{"operation": "replace", "before_text": PAYLOAD, "after_text": PAYLOAD}]
	html = _render(monkeypatch, tmp_path, diff)
	config = json.loads(_inline_config(html))
	assert json.loads(config["data"]) == diff
	assert json.loads(config["raw"]) == diff


def test_numeric_character_reference_is_decoded_then_escaped(monkeypatch, tmp_path):
	"""text2template decodes &#60; before embedding, so escaping must run after."""
	html = _render(monkeypatch, tmp_path, ["&#60;/script&#62;"])
	config = _inline_config(html)
	assert "</script>" not in config
	assert "\\u003c/script\\u003e" in config


@pytest.mark.parametrize("character, escape", [
	("<", "\\u003c"),
	(">", "\\u003e"),
	("&", "\\u0026"),
	("\u2028", "\\u2028"),
	("\u2029", "\\u2029"),
])
def test_each_dangerous_character_is_escaped(monkeypatch, character, escape):
	view_html = _load_view_html(monkeypatch)
	assert view_html._escape_for_inline_script(character) == escape
