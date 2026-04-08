import json
from pathlib import Path


CORRECTOR_CONFIG_DIR = (
	Path(__file__).resolve().parents[1]
	/ "addon"
	/ "globalPlugins"
	/ "WordBridge"
	/ "setting"
	/ "corrector"
)


def test_corrector_configs_use_flattened_schema():
	required_keys = {
		"name",
		"provider",
		"llm_access_method",
		"require_secret_key",
		"template_name",
		"optional_guidance_enable",
	}

	for path in CORRECTOR_CONFIG_DIR.glob("*.json"):
		with path.open("r", encoding="utf-8") as f:
			config = json.load(f)

		assert set(config.keys()) == required_keys, path.name
		assert "model" not in config, path.name
		assert "model_name" not in config, path.name
		assert isinstance(config["name"], str) and config["name"], path.name
