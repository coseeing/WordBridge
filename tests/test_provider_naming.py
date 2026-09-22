import json
from pathlib import Path

import pytest

from lib.catalog.document import build_catalog
from lib.catalog.sources import BundledCatalogSource
from lib.llm import SUPPORTED_PROVIDERS
from lib.llm.adapter import ADAPTER_CLASSES
from lib.llm.provider import PROVIDER_CLASSES, get_provider


SETTING_DIR = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge" / "setting"
PROVIDER_CONFIG_DIR = SETTING_DIR / "provider"
AI_CONFIG_DIR = SETTING_DIR / "ai"
PRICE_PATH = SETTING_DIR / "price.json"


def catalog():
	document, issues = BundledCatalogSource(SETTING_DIR).load()
	assert issues == ()
	return build_catalog(document, runnable_providers=SUPPORTED_PROVIDERS)


def test_the_provider_and_adapter_family_tables_agree():
	# A name in one table and not the other is a model the user can select and
	# cannot run.
	assert set(PROVIDER_CLASSES) == set(ADAPTER_CLASSES)
	assert SUPPORTED_PROVIDERS == frozenset(PROVIDER_CLASSES)


def test_every_provider_config_filename_is_the_canonical_provider_name():
	for path in PROVIDER_CONFIG_DIR.glob("*.json"):
		assert path.stem == path.stem.strip(), path.name
		if path.stem not in SUPPORTED_PROVIDERS:
			continue
		entry = catalog().get_provider(path.stem)
		provider = get_provider(path.stem, {"api_key": "test"}, provider_entry=entry)
		assert provider.name == path.stem


def test_every_ai_config_names_an_existing_provider_config():
	for path in AI_CONFIG_DIR.glob("*.json"):
		provider = json.loads(path.read_text(encoding="utf8")).get("provider")
		if provider is None:
			continue
		assert (PROVIDER_CONFIG_DIR / f"{provider}.json").exists(), (
			f"{path.name} names provider {provider!r} with no setting/provider/{provider}.json"
		)


def test_every_active_ai_config_has_a_price_entry():
	price = json.loads(PRICE_PATH.read_text(encoding="utf8"))

	for path in AI_CONFIG_DIR.glob("*.json"):
		data = json.loads(path.read_text(encoding="utf8"))
		if not data.get("active") or data.get("provider") is None:
			continue
		key = f"{data['model']}&{data['provider']}"
		assert key in price, f"{path.name} has no price.json entry for {key!r}"


def test_provider_lookup_does_not_fall_back_to_a_case_insensitive_glob():
	source = (PROVIDER_CONFIG_DIR.parents[1] / "lib" / "llm" / "provider.py").read_text(encoding="utf8")

	assert "casefold()" not in source


def test_the_provider_no_longer_reads_its_settings_from_disk():
	source = (PROVIDER_CONFIG_DIR.parents[1] / "lib" / "llm" / "provider.py").read_text(encoding="utf8")

	assert "setting_name" not in source
	assert "setting_dir" not in source


def test_provider_factory_accepts_canonical_provider_name_only():
	entry = catalog().get_provider("OpenAI")
	provider = get_provider("OpenAI", {"api_key": "test"}, provider_entry=entry)

	assert provider.name == "OpenAI"
	assert provider.url == entry.url
	assert provider.timeout_max == entry.timeout_max


@pytest.mark.parametrize("provider_name", ["openai", "OPENAI", "Openai", "OpenAIResponse"])
def test_provider_factory_rejects_non_canonical_provider_names(provider_name):
	entry = catalog().get_provider("OpenAI")

	with pytest.raises(ValueError, match=f"Unsupported provider: {provider_name}"):
		get_provider(provider_name, {"api_key": "test"}, provider_entry=entry)


def test_deepseek_provider_top_p_is_within_valid_range():
	entry = catalog().get_provider("DeepSeek")

	assert 0.0 < entry.setting["top_p"] <= 1.0


def test_the_workflow_factory_requires_both_entries():
	from lib.application.task_factory import create_typo_workflow

	with pytest.raises(TypeError):
		create_typo_workflow(
			provider_name="OpenAI",
			model_name="gpt-5.6-sol",
			credential={"api_key": "test"},
			language="zh_traditional",
			template_name="Standard_v1.json",
			corrector_mode="standard",
			optional_guidance_enable={},
		)
