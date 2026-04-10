from pathlib import Path

import pytest

from lib.llm.provider import get_provider


PROVIDER_CONFIG_DIR = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge" / "setting" / "provider"


def test_provider_config_filenames_use_canonical_titlecase_names():
	expected_filenames = {
		"Anthropic.json",
		"Baidu.json",
		"DeepSeek.json",
		"Google.json",
		"OpenAI.json",
		"OpenRouter.json",
	}

	actual_filenames = {path.name for path in PROVIDER_CONFIG_DIR.glob("*.json")}

	assert actual_filenames == expected_filenames


def test_provider_factory_accepts_canonical_titlecase_name_only():
	provider = get_provider("OpenAI", {"api_key": "test", "secret_key": ""})

	assert provider.name == "OpenAI"


@pytest.mark.parametrize(
	"provider_name",
	["openai", "OPENAI", "Openai"],
)
def test_provider_factory_rejects_non_canonical_provider_names(provider_name):
	with pytest.raises(ValueError, match=f"Unsupported provider: {provider_name}"):
		get_provider(provider_name, {"api_key": "test", "secret_key": ""})
