import json
from pathlib import Path

import pytest

from lib.llm.provider import get_provider


PROVIDER_CONFIG_DIR = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge" / "setting" / "provider"


AI_CONFIG_DIR = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge" / "setting" / "ai"
PRICE_PATH = PROVIDER_CONFIG_DIR.parent / "price.json"


def test_every_provider_config_filename_is_the_canonical_provider_name():
	# Derived from the files themselves rather than a hand-written literal so
	# that adding a provider cannot silently drift out of the check.
	for path in PROVIDER_CONFIG_DIR.glob("*.json"):
		assert path.stem == path.stem.strip(), path.name
		if path.stem == "Coseeing":
			continue
		provider = get_provider(path.stem, {"api_key": "test"})
		assert provider.name == path.stem


def test_every_ai_config_names_an_existing_provider_config():
	for path in AI_CONFIG_DIR.glob("*.json"):
		provider = json.loads(path.read_text(encoding="utf8"))["provider"]

		assert (PROVIDER_CONFIG_DIR / f"{provider}.json").exists(), (
			f"{path.name} names provider {provider!r} with no setting/provider/{provider}.json"
		)


def test_every_active_ai_config_has_a_price_entry():
	# price.json is keyed by the corrector config id, "<model>&<provider>".
	# Ollama-00001-qwen2.json is active: false and deliberately has no entry.
	price = json.loads(PRICE_PATH.read_text(encoding="utf8"))

	for path in AI_CONFIG_DIR.glob("*.json"):
		data = json.loads(path.read_text(encoding="utf8"))
		if not data.get("active"):
			continue
		key = f"{data['model']}&{data['provider']}"

		assert key in price, f"{path.name} has no price.json entry for {key!r}"


def test_provider_lookup_does_not_fall_back_to_a_case_insensitive_glob():
	source = (PROVIDER_CONFIG_DIR.parents[1] / "lib" / "llm" / "provider.py").read_text(encoding="utf8")

	assert "casefold()" not in source


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
	data = json.loads((PROVIDER_CONFIG_DIR / "DeepSeek.json").read_text(encoding="utf8"))
	assert 0.0 < data["setting"]["top_p"] <= 1.0
