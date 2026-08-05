import json
from pathlib import Path

import pytest

from lib.llm.provider import get_provider


PROVIDER_CONFIG_DIR = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge" / "setting" / "provider"


def test_provider_config_filenames_match_catalog():
	expected_filenames = {
		"Coseeing.json",
		"OpenAI.json",
		"anthropic.json",
		"deepseek.json",
		"google.json",
		"openrouter.json",
	}

	actual_filenames = {path.name for path in PROVIDER_CONFIG_DIR.glob("*.json")}

	assert actual_filenames == expected_filenames


@pytest.mark.parametrize(
	("provider_name", "expected_name"),
	[
		("OpenAI", "OpenAI"),
	],
)
def test_provider_factory_accepts_canonical_provider_name_only(provider_name, expected_name):
	provider = get_provider(provider_name, {"api_key": "test"})

	assert provider.name == expected_name


@pytest.mark.parametrize(
	"provider_name",
	["openai", "OPENAI", "Openai", "OpenAIResponse"],
)
def test_provider_factory_rejects_non_canonical_provider_names(provider_name):
	with pytest.raises(ValueError, match=f"Unsupported provider: {provider_name}"):
		get_provider(provider_name, {"api_key": "test"})


def test_deepseek_provider_top_p_is_within_valid_range():
	data = json.loads((PROVIDER_CONFIG_DIR / "deepseek.json").read_text(encoding="utf8"))
	assert 0.0 < data["setting"]["top_p"] <= 1.0
