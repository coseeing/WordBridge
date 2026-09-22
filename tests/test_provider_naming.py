from pathlib import Path

import pytest

from lib.catalog.document import build_catalog
from lib.catalog.sources import BundledCatalogSource
from lib.llm import SUPPORTED_PROVIDERS
from lib.llm.adapter import ADAPTER_CLASSES
from lib.llm.provider import PROVIDER_CLASSES, get_provider


SETTING_DIR = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge" / "setting"
def catalog():
	document, issues = BundledCatalogSource(SETTING_DIR).load()
	assert issues == ()
	return build_catalog(document, runnable_providers=SUPPORTED_PROVIDERS)


def catalog_document():
	document, issues = BundledCatalogSource(SETTING_DIR).load()
	assert issues == ()
	return document


def test_the_provider_and_adapter_family_tables_agree():
	# A name in one table and not the other is a model the user can select and
	# cannot run.
	assert set(PROVIDER_CLASSES) == set(ADAPTER_CLASSES)
	assert SUPPORTED_PROVIDERS == frozenset(PROVIDER_CLASSES)


def test_every_catalog_provider_name_is_canonical_and_constructible():
	for provider_name in catalog_document()["providers"]:
		assert provider_name == provider_name.strip(), provider_name
		if provider_name not in SUPPORTED_PROVIDERS:
			continue
		entry = catalog().get_provider(provider_name)
		provider = get_provider(provider_name, {"api_key": "test"}, provider_entry=entry)
		assert provider.name == provider_name


def test_every_catalog_model_names_an_existing_provider():
	document = catalog_document()
	for model in document["models"]:
		assert model["provider"] in document["providers"], model


def test_every_active_local_catalog_model_has_pricing():
	for model in catalog_document()["models"]:
		if model["active"]:
			assert model["pricing"], model


def test_provider_lookup_does_not_fall_back_to_a_case_insensitive_glob():
	source = (SETTING_DIR.parent / "lib" / "llm" / "provider.py").read_text(encoding="utf8")

	assert "casefold()" not in source


def test_the_provider_no_longer_reads_its_settings_from_disk():
	source = (SETTING_DIR.parent / "lib" / "llm" / "provider.py").read_text(encoding="utf8")

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
