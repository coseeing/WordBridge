import pytest

from app.correction_config import load_correction_settings, resolve_model


def test_default_resolves_to_local_model(monkeypatch):
	monkeypatch.setenv("DEFAULT_CORRECTOR_CONFIG_ID", "deepseek-flash&DeepSeek")
	settings = load_correction_settings()
	assert resolve_model(settings, "default").model == "deepseek-flash"
	assert resolve_model(settings, "gpt-6-luna&OpenAI").provider == "OpenAI"


def test_inactive_model_is_rejected(monkeypatch):
	monkeypatch.setenv("DEFAULT_CORRECTOR_CONFIG_ID", "deepseek-flash&DeepSeek")
	settings = load_correction_settings()
	with pytest.raises(LookupError):
		resolve_model(settings, "qwen2&Ollama")


def test_the_served_catalog_has_no_coseeing_offers(monkeypatch):
	monkeypatch.setenv("DEFAULT_CORRECTOR_CONFIG_ID", "deepseek-flash&DeepSeek")
	settings = load_correction_settings()

	assert settings.catalog.coseeings == ()


def test_the_ids_released_add_ons_send_are_servable_by_default(monkeypatch):
	# U5 (OQ1 -> B): released add-ons offered these two on Coseeing and keep
	# sending them; the list is the server's own, not part of GET /.
	monkeypatch.delenv("COSEEING_MODEL_IDS", raising=False)
	settings = load_correction_settings()

	assert settings.coseeing_ids == frozenset({"deepseek-flash&DeepSeek", "gpt-6-luna&OpenAI"})
	assert resolve_model(settings, "deepseek-flash&DeepSeek").model == "deepseek-flash"
	assert resolve_model(settings, "gpt-6-luna&OpenAI").model == "gpt-6-luna"


def test_an_unlisted_id_is_rejected_even_if_it_is_an_active_local_model(monkeypatch):
	monkeypatch.delenv("COSEEING_MODEL_IDS", raising=False)
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
