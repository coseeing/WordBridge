import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORRECTOR_CONFIG_DIR = (
	PROJECT_ROOT
	/ "addon"
	/ "globalPlugins"
	/ "WordBridge"
	/ "setting"
	/ "corrector"
)
LLM_MODELS_PATH = (
	PROJECT_ROOT
	/ "addon"
	/ "globalPlugins"
	/ "WordBridge"
	/ "setting"
	/ "price.json"
)


def test_corrector_configs_use_flattened_schema():
	required_keys = {
		"model",
		"provider",
		"coseeing",
		"template_name",
		"optional_guidance_enable",
	}
	allowed_keys = required_keys | {"active"}

	for path in CORRECTOR_CONFIG_DIR.glob("*.json"):
		with path.open("r", encoding="utf-8") as f:
			config = json.load(f)

		assert required_keys <= set(config.keys()) <= allowed_keys, path.name
		assert "model_name" not in config, path.name
		assert "name" not in config, path.name
		if "active" in config:
			assert isinstance(config["active"], bool), path.name
		assert isinstance(config["model"], str) and config["model"], path.name
		assert isinstance(config["coseeing"], bool), path.name


def test_corrector_catalog_uses_unique_model_provider_pairs():
	seen_pairs = set()

	for path in CORRECTOR_CONFIG_DIR.glob("*.json"):
		with path.open("r", encoding="utf-8") as f:
			config = json.load(f)

		pair = (config["model"], config["provider"])
		assert pair not in seen_pairs, path.name
		seen_pairs.add(pair)


def test_coseeing_duplicate_corrector_files_are_removed():
	assert not list(CORRECTOR_CONFIG_DIR.glob("Coseeing-*.json"))


def test_provider_catalogs_preserve_approved_and_unaffected_models():
	with LLM_MODELS_PATH.open("r", encoding="utf-8") as f:
		prices = json.load(f)

	expected = {
		"OpenAI": {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"},
		"Anthropic": {"claude-opus-5", "claude-sonnet-5"},
		"DeepSeek": {"deepseek-v4-flash", "deepseek-v4-pro"},
		"Google": {
			"gemini-2.5-pro",
			"gemini-3.1-pro-preview",
			"gemini-3.1-flash-lite",
			"gemini-3.5-flash",
			"gemini-3.5-flash-lite",
			"gemini-3.6-flash",
		},
	}
	price_models = {
		provider: {
			entry["model"] for entry in prices.values()
			if entry["provider"] == provider
		}
		for provider in expected
	}
	corrector_models = {provider: set() for provider in expected}
	for path in CORRECTOR_CONFIG_DIR.glob("*.json"):
		with path.open("r", encoding="utf-8") as f:
			config = json.load(f)
		if config["provider"] in corrector_models:
			corrector_models[config["provider"]].add(config["model"])

	assert price_models == expected
	assert corrector_models == expected
