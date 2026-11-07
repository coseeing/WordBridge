import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.correction_config import (
	ADDON_VERSION_PATH,
	api_key_variable,
	load_addon_version,
	load_correction_settings,
	resolve_model,
	template_stem,
)
from app.lib.llm import PROVIDER_CLASSES
from app.settings import SettingsError

SERVER = Path(__file__).resolve().parent.parent


def _environ(**overrides):
	"""os.environ (the conftest settings) without any provider key, plus overrides."""
	environ = {name: value for name, value in os.environ.items() if not name.endswith("_API_KEY")}
	environ.update(overrides)
	return environ


def test_default_resolves_to_local_model(monkeypatch):
	monkeypatch.setenv("DEFAULT_CORRECTOR_CONFIG_ID", "deepseek-flash&DeepSeek")
	settings = load_correction_settings()
	assert resolve_model(settings, "default").model == "deepseek-flash"
	assert resolve_model(settings, "gpt-6-luna&OpenAI").provider == "OpenAI"


def test_an_unset_default_model_env_var_stops_startup(monkeypatch):
	monkeypatch.delenv("DEFAULT_CORRECTOR_CONFIG_ID", raising=False)

	with pytest.raises(ValueError, match="DEFAULT_CORRECTOR_CONFIG_ID is not set"):
		load_correction_settings()


def test_an_empty_default_model_env_var_stops_startup(monkeypatch):
	monkeypatch.setenv("DEFAULT_CORRECTOR_CONFIG_ID", "  ")

	with pytest.raises(ValueError, match="DEFAULT_CORRECTOR_CONFIG_ID is empty"):
		load_correction_settings()


def test_the_default_model_comes_from_the_env_var(monkeypatch):
	monkeypatch.setenv("DEFAULT_CORRECTOR_CONFIG_ID", "claude-sonnet-5-5&Anthropic")
	settings = load_correction_settings()

	assert settings.default_id == "claude-sonnet-5-5&Anthropic"
	model = resolve_model(settings, "default")
	assert (model.provider, model.model) == ("Anthropic", "claude-sonnet-5-5")


def test_inactive_model_is_rejected(monkeypatch):
	monkeypatch.setenv("DEFAULT_CORRECTOR_CONFIG_ID", "deepseek-flash&DeepSeek")
	settings = load_correction_settings()
	with pytest.raises(LookupError):
		resolve_model(settings, "qwen2&Ollama")


def test_the_served_catalog_has_no_coseeing_offers(monkeypatch):
	monkeypatch.setenv("DEFAULT_CORRECTOR_CONFIG_ID", "deepseek-flash&DeepSeek")
	settings = load_correction_settings()

	assert settings.catalog.coseeings == ()


def test_an_unset_coseeing_list_stops_startup(monkeypatch):
	monkeypatch.delenv("COSEEING_MODEL_IDS", raising=False)

	with pytest.raises(ValueError, match="COSEEING_MODEL_IDS is not set"):
		load_correction_settings()


def test_the_ids_released_add_ons_send_are_servable_when_listed(monkeypatch):
	# U5 (OQ1 -> B): released add-ons offered these two on Coseeing and keep
	# sending them; the list is the server's own, not part of GET /.
	monkeypatch.setenv("COSEEING_MODEL_IDS", "deepseek-flash&DeepSeek,gpt-6-luna&OpenAI")
	settings = load_correction_settings()

	assert settings.coseeing_ids == frozenset({"deepseek-flash&DeepSeek", "gpt-6-luna&OpenAI"})
	assert resolve_model(settings, "deepseek-flash&DeepSeek").model == "deepseek-flash"
	assert resolve_model(settings, "gpt-6-luna&OpenAI").model == "gpt-6-luna"


def test_an_unlisted_id_is_rejected_even_if_it_is_an_active_local_model(monkeypatch):
	monkeypatch.setenv("COSEEING_MODEL_IDS", "deepseek-flash&DeepSeek,gpt-6-luna&OpenAI")
	settings = load_correction_settings()

	assert settings.catalog.get_model("gemini-3.7-flash&Google").active
	with pytest.raises(LookupError):
		resolve_model(settings, "gemini-3.7-flash&Google")


def test_the_env_var_replaces_the_list(monkeypatch):
	monkeypatch.setenv("COSEEING_MODEL_IDS", " gemini-3.7-flash&Google , ,")
	settings = load_correction_settings()

	assert settings.coseeing_ids == frozenset({"gemini-3.7-flash&Google"})
	assert resolve_model(settings, "gemini-3.7-flash&Google").provider == "Google"
	with pytest.raises(LookupError):
		resolve_model(settings, "gpt-6-luna&OpenAI")


def test_an_empty_env_var_leaves_only_default(monkeypatch):
	monkeypatch.setenv("COSEEING_MODEL_IDS", "")
	settings = load_correction_settings()

	assert settings.coseeing_ids == frozenset()
	assert resolve_model(settings, "default").model == "deepseek-flash"
	with pytest.raises(LookupError):
		resolve_model(settings, "deepseek-flash&DeepSeek")


def test_a_listed_id_whose_local_model_is_inactive_is_rejected(monkeypatch):
	monkeypatch.setenv("COSEEING_MODEL_IDS", "qwen2&Ollama")
	settings = load_correction_settings()

	with pytest.raises(LookupError):
		resolve_model(settings, "qwen2&Ollama")


def test_invalid_deployment_default_fails_startup(monkeypatch):
	monkeypatch.setenv("DEFAULT_CORRECTOR_CONFIG_ID", "missing&Provider")
	with pytest.raises(ValueError):
		load_correction_settings()


# --- provider API keys, checked at startup ----------------------------------


def test_a_served_provider_without_a_key_stops_startup():
	environ = _environ(
		DEFAULT_CORRECTOR_CONFIG_ID="deepseek-flash&DeepSeek",
		COSEEING_MODEL_IDS="gpt-6-luna&OpenAI",
	)

	with pytest.raises(SettingsError) as raised:
		load_correction_settings(environ=environ)

	assert "DEEPSEEK_API_KEY" in str(raised.value)
	assert "OPENAI_API_KEY" in str(raised.value)


def test_a_blank_key_counts_as_missing():
	environ = _environ(COSEEING_MODEL_IDS="", DEEPSEEK_API_KEY="  ")

	with pytest.raises(SettingsError, match="DEEPSEEK_API_KEY"):
		load_correction_settings(environ=environ)


def test_the_error_never_echoes_a_key():
	environ = _environ(COSEEING_MODEL_IDS="gpt-6-luna&OpenAI", OPENAI_API_KEY="sk-visible")

	with pytest.raises(SettingsError) as raised:
		load_correction_settings(environ=environ)

	assert "DEEPSEEK_API_KEY" in str(raised.value)
	assert "sk-visible" not in str(raised.value)


def test_an_unused_providers_key_is_not_required():
	environ = _environ(COSEEING_MODEL_IDS="", DEEPSEEK_API_KEY="key-deepseek")

	settings = load_correction_settings(environ=environ)

	assert settings.api_keys == {"DeepSeek": "key-deepseek"}


def test_an_unservable_coseeing_id_warns_and_needs_no_key(caplog):
	environ = _environ(COSEEING_MODEL_IDS="qwen2&Ollama,missing&Nobody", DEEPSEEK_API_KEY="key-deepseek")

	with caplog.at_level(logging.WARNING, logger="app.correction_config"):
		settings = load_correction_settings(environ=environ)

	warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
	assert any("qwen2&Ollama" in message for message in warnings)
	assert any("missing&Nobody" in message for message in warnings)
	assert settings.api_keys == {"DeepSeek": "key-deepseek"}


def test_api_keys_are_not_in_the_repr():
	settings = load_correction_settings()

	assert settings.api_keys["DeepSeek"] == "test-key-deepseek"
	assert "test-key" not in repr(settings)


def test_importing_app_settings_needs_no_api_key():
	# alembic imports app.settings; running a migration must not need keys.
	# Every key is set to "" rather than removed: app.settings loads
	# server/.env, which never overrides a variable that is set, but would
	# refill a removed one from a developer's real .env and hide a check.
	no_keys = {api_key_variable(provider): "" for provider in PROVIDER_CLASSES}
	result = subprocess.run(
		[sys.executable, "-c", "import app.settings"],
		cwd=SERVER,
		env=_environ(**no_keys),
		capture_output=True,
		text=True,
		timeout=60,
		check=False,
	)

	assert result.returncode == 0, result.stderr


# --- add-on version and template names ------------------------------------------


def test_load_addon_version_reads_the_file(tmp_path):
	path = tmp_path / "addon_version.txt"
	path.write_text("2026.11.1\n", encoding="utf-8")

	assert load_addon_version(path) == "2026.11.1"


def test_the_bundled_version_file_loads():
	# tests/test_server_addon_copy.py checks the file against buildVars.py.
	assert load_addon_version() == ADDON_VERSION_PATH.read_text(encoding="utf-8").strip()
	assert re.fullmatch(r"\d{4}\.\d+\.\d+", load_addon_version())


@pytest.mark.parametrize("content", [None, " \n"], ids=["missing", "blank"])
def test_a_missing_or_blank_version_file_stops_startup(tmp_path, content):
	path = tmp_path / "addon_version.txt"
	if content is not None:
		path.write_text(content, encoding="utf-8")

	with pytest.raises(ValueError, match="addon_version.txt"):
		load_addon_version(path)


def test_template_stem_drops_the_json_suffix():
	assert template_stem("Standard_v1.json") == "Standard_v1"
	assert template_stem("Lite_v1.json") == "Lite_v1"
