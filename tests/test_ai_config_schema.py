import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTING_DIR = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge" / "setting"
CATALOG_PATH = SETTING_DIR / "catalog.json"
CORRECTOR_TASK_CONFIG_PATH = SETTING_DIR / "task" / "corrector.json"


def _catalog_document():
	return json.loads(CATALOG_PATH.read_text(encoding="utf8"))


def test_catalog_models_and_coseeings_use_the_expected_entry_shapes():
	document = _catalog_document()

	assert len(document["models"]) == 13
	for entry in document["models"]:
		assert isinstance(entry["model"], str) and entry["model"]
		assert isinstance(entry["provider"], str) and entry["provider"]
		assert isinstance(entry["active"], bool)
		assert isinstance(entry["label"], str) and entry["label"]
		if entry["active"]:
			assert isinstance(entry["pricing"], dict) and entry["pricing"]
			assert isinstance(entry["usage_key"], str) and entry["usage_key"]

	providerless = [entry for entry in document["coseeings"] if "provider" not in entry]
	assert providerless == [{"model": "default", "label": "Coseeing default", "active": True}]


def test_ai_catalog_uses_unique_model_provider_pairs():
	seen_pairs = set()

	for entry in _catalog_document()["models"]:
		pair = (entry["model"], entry["provider"])
		assert pair not in seen_pairs, pair
		seen_pairs.add(pair)


def test_catalog_has_exactly_one_providerless_coseeing_default():
	providerless = [entry for entry in _catalog_document()["coseeings"] if "provider" not in entry]
	assert providerless == [{"model": "default", "label": "Coseeing default", "active": True}]


def test_corrector_task_config_is_the_only_prompt_setting_file():
	with CORRECTOR_TASK_CONFIG_PATH.open("r", encoding="utf-8") as f:
		config = json.load(f)

	assert set(config) == {"template_name", "optional_guidance_enable"}
	assert config["optional_guidance_enable"] == {
		"keep_non_chinese_char": True,
		"no_explanation": True,
	}


def test_provider_catalogs_preserve_approved_and_unaffected_models():
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
	models = _catalog_document()["models"]
	assert {
		provider: {entry["model"] for entry in models if entry["provider"] == provider}
		for provider in expected
	} == expected
