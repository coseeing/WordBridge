import pytest

from app.correction_config import load_correction_settings, resolve_model


def test_default_resolves_to_local_model(monkeypatch):
	monkeypatch.setenv("DEFAULT_CORRECTOR_CONFIG_ID", "deepseek-v4-flash&DeepSeek")
	settings = load_correction_settings()
	assert resolve_model(settings, "default").model == "deepseek-v4-flash"
	assert resolve_model(settings, "gpt-5.6-luna&OpenAI").provider == "OpenAI"


def test_inactive_model_is_rejected(monkeypatch):
	monkeypatch.setenv("DEFAULT_CORRECTOR_CONFIG_ID", "deepseek-v4-flash&DeepSeek")
	settings = load_correction_settings()
	with pytest.raises(LookupError):
		resolve_model(settings, "qwen2&Ollama")


def test_inactive_coseeing_offer_is_rejected(monkeypatch):
	from dataclasses import replace
	monkeypatch.setenv("DEFAULT_CORRECTOR_CONFIG_ID", "deepseek-v4-flash&DeepSeek")
	settings = load_correction_settings()
	offers = tuple(replace(offer, active=False) if offer.corrector_config_id == "gpt-5.6-luna&OpenAI" else offer
	               for offer in settings.catalog.coseeings)
	settings = replace(settings, catalog=replace(settings.catalog, coseeings=offers))
	with pytest.raises(LookupError):
		resolve_model(settings, "gpt-5.6-luna&OpenAI")


def test_invalid_deployment_default_fails_startup(monkeypatch):
	monkeypatch.setenv("DEFAULT_CORRECTOR_CONFIG_ID", "missing&Provider")
	with pytest.raises(ValueError):
		load_correction_settings()
