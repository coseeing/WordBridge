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
