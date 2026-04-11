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
	/ "llm_models.json"
)
OPENAI_PRICE_PATH = PROJECT_ROOT / "openai_model_api_price.json"


def test_corrector_configs_use_flattened_schema():
	required_keys = {
		"model",
		"provider",
		"coseeing",
		"template_name",
		"optional_guidance_enable",
	}

	for path in CORRECTOR_CONFIG_DIR.glob("*.json"):
		with path.open("r", encoding="utf-8") as f:
			config = json.load(f)

		assert set(config.keys()) == required_keys, path.name
		assert "model_name" not in config, path.name
		assert "name" not in config, path.name
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


def test_openai_setting_models_match_root_price_file_subset():
	with OPENAI_PRICE_PATH.open("r", encoding="utf-8") as f:
		expected = json.load(f)

	with LLM_MODELS_PATH.open("r", encoding="utf-8") as f:
		llm_models = json.load(f)

	actual = {
		key: value
		for key, value in llm_models.items()
		if value["provider"] in {"OpenAIChatCompletion", "OpenAIResponse"}
	}

	assert actual == expected


def test_openai_corrector_configs_cover_each_root_price_model_entry():
	with OPENAI_PRICE_PATH.open("r", encoding="utf-8") as f:
		expected = json.load(f)

	expected_pairs = {
		(value["provider"], value["model"])
		for value in expected.values()
	}
	actual_pairs = set()

	for path in CORRECTOR_CONFIG_DIR.glob("*.json"):
		with path.open("r", encoding="utf-8") as f:
			config = json.load(f)
		if config["provider"] not in {"OpenAIChatCompletion", "OpenAIResponse"}:
			continue
		actual_pairs.add((config["provider"], config["model"]))

	assert actual_pairs == expected_pairs
