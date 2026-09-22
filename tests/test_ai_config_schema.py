import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTING_DIR = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge" / "setting"
AI_CONFIG_DIR = SETTING_DIR / "ai"
CORRECTOR_TASK_CONFIG_PATH = SETTING_DIR / "task" / "corrector.json"
LLM_MODELS_PATH = SETTING_DIR / "price.json"


def test_ai_configs_use_endpoint_only_schema():
	allowed_keys = {"model", "provider", "coseeing", "active"}
	ai_paths = sorted(AI_CONFIG_DIR.glob("*.json"))

	assert len(ai_paths) == 14
	coseeing_only = 0
	for path in ai_paths:
		with path.open("r", encoding="utf-8") as f:
			config = json.load(f)

		assert set(config.keys()) <= allowed_keys, path.name
		assert "template_name" not in config, path.name
		assert "optional_guidance_enable" not in config, path.name
		if "active" in config:
			assert isinstance(config["active"], bool), path.name
		assert isinstance(config["model"], str) and config["model"], path.name
		assert isinstance(config["coseeing"], bool), path.name
		if "provider" in config:
			assert isinstance(config["provider"], str) and config["provider"], path.name
		else:
			# No provider means no local offer: the Coseeing server serves it
			# on its own. Exactly one shipped entry is like this.
			coseeing_only += 1
			assert config["coseeing"] is True, path.name
			assert config["model"] == "default", path.name

	assert coseeing_only == 1


def test_ai_catalog_uses_unique_model_provider_pairs():
	seen_pairs = set()

	for path in AI_CONFIG_DIR.glob("*.json"):
		with path.open("r", encoding="utf-8") as f:
			config = json.load(f)

		pair = (config["model"], config.get("provider"))
		assert pair not in seen_pairs, path.name
		seen_pairs.add(pair)


def test_ai_catalog_has_no_duplicate_coseeing_files():
	# The one legitimate exception is the shipped sentinel, whose name has to
	# sort first among "ai/*.json" for BundledCatalogSource to pick it as the
	# default. Anything else matching this glob would be a duplicate.
	assert list(AI_CONFIG_DIR.glob("Coseeing-*.json")) == [
		AI_CONFIG_DIR / "Coseeing-00000-default.json",
	]


def test_corrector_task_config_is_the_only_prompt_setting_file():
	with CORRECTOR_TASK_CONFIG_PATH.open("r", encoding="utf-8") as f:
		config = json.load(f)

	assert set(config) == {"template_name", "optional_guidance_enable"}
	assert config["optional_guidance_enable"] == {
		"keep_non_chinese_char": True,
		"no_explanation": True,
	}


def test_provider_catalogs_preserve_approved_and_unaffected_models():
	with LLM_MODELS_PATH.open("r", encoding="utf-8") as f:
		prices = json.load(f)

	expected = {
		"OpenAI": {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"},
		"Anthropic": {"claude-opus-5", "claude-sonnet-5"},
		"DeepSeek": {"deepseek-v4-flash", "deepseek-v4-pro"},
		"Google": {
			"gemini-3.1-pro-preview",
			"gemini-3.1-flash-lite",
			"gemini-3.5-flash-lite",
			"gemini-3.7-flash",
			"gemini-3.8-flash",
		},
	}
	price_models = {
		provider: {
			entry["model"] for entry in prices.values()
			if entry["provider"] == provider
		}
		for provider in expected
	}
	ai_models = {provider: set() for provider in expected}
	for path in AI_CONFIG_DIR.glob("*.json"):
		with path.open("r", encoding="utf-8") as f:
			config = json.load(f)
		if config.get("provider") in ai_models:
			ai_models[config["provider"]].add(config["model"])

	assert price_models == expected
	assert ai_models == expected
