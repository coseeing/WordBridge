import ast
from pathlib import Path

import pytest

from lib.catalog.document import SCHEMA_VERSION, build_catalog
from lib.catalog.model import COSEEING_GROUP, make_corrector_config_id


RUNNABLE = frozenset({"OpenAI", "DeepSeek"})

PROVIDER = {
	"label": "OpenAI",
	"url": "https://api.openai.com/v1/responses",
	"setting": {"temperature": 0.0},
	"timeout0": 10,
	"timeout_max": 20,
}


def document(**overrides):
	base = {
		"schema_version": SCHEMA_VERSION,
		"providers": {"OpenAI": dict(PROVIDER)},
		"models": [{"provider": "OpenAI", "model": "gpt-x", "label": "GPT X"}],
		"coseeings": [],
	}
	base.update(overrides)
	return base


def codes(catalog):
	return sorted(issue.code for issue in catalog.issues)


def test_identity_joins_model_and_provider():
	assert make_corrector_config_id("gpt-x", "OpenAI") == "gpt-x&OpenAI"


def test_identity_without_a_provider_is_the_bare_model():
	assert make_corrector_config_id("default") == "default"


def test_a_complete_document_yields_one_local_item():
	catalog = build_catalog(document(), runnable_providers=RUNNABLE)

	assert catalog.issues == ()
	assert [item.corrector_config_id for item in catalog.selectable_items] == ["gpt-x&OpenAI"]
	assert catalog.selectable_items[0].execution_channel == "local"
	assert catalog.labels_for("OpenAI") == ("GPT X",)


def test_a_model_without_pricing_is_kept():
	# The rule protects a future remote entry whose price has not been
	# published. The shipped instance is qwen2&Ollama, which is active: false.
	catalog = build_catalog(document(), runnable_providers=RUNNABLE)

	entry = catalog.get_model("gpt-x&OpenAI")
	assert entry.pricing is None
	assert entry.price_entry() == {}


def test_pricing_is_carried_into_the_price_entry_shape():
	doc = document(models=[{
		"provider": "OpenAI",
		"model": "gpt-x",
		"label": "GPT X",
		"pricing": {"input_tokens": 1.25, "base_unit": 1000000},
		"usage_key": "usage",
	}])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.get_model("gpt-x&OpenAI").price_entry() == {
		"model": "gpt-x",
		"provider": "OpenAI",
		"pricing": {"input_tokens": 1.25, "base_unit": 1000000},
		"usage_key": "usage",
	}


def test_a_model_naming_an_absent_provider_is_dropped():
	doc = document(models=[{"provider": "Mistral", "model": "m-large", "label": "M"}])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.selectable_items == ()
	assert "unknown_provider" in codes(catalog)


def test_a_model_whose_provider_has_no_implementation_is_dropped():
	doc = document(
		providers={"OpenAI": dict(PROVIDER), "Mistral": dict(PROVIDER, label="Mistral")},
		models=[{"provider": "Mistral", "model": "m-large", "label": "M"}],
	)
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.selectable_items == ()
	assert "unsupported_provider" in codes(catalog)


def test_a_coseeing_entry_survives_its_provider_being_absent():
	doc = document(
		models=[],
		coseeings=[{"model": "m-large", "provider": "Mistral", "label": "M large"}],
	)
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert [item.corrector_config_id for item in catalog.selectable_items] == ["m-large&Mistral"]
	assert catalog.selectable_items[0].execution_channel == COSEEING_GROUP
	assert "unknown_provider" not in codes(catalog)


def test_a_provider_entry_missing_a_required_field_is_dropped():
	broken = dict(PROVIDER)
	del broken["label"]
	catalog = build_catalog(document(providers={"OpenAI": broken}), runnable_providers=RUNNABLE)

	assert catalog.get_provider("OpenAI") is None
	assert "incomplete_provider" in codes(catalog)


def test_a_provider_no_model_names_is_a_lint_issue_only():
	doc = document(providers={"OpenAI": dict(PROVIDER), "DeepSeek": dict(PROVIDER, label="DeepSeek")})
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert [item.corrector_config_id for item in catalog.selectable_items] == ["gpt-x&OpenAI"]
	assert codes(catalog) == ["unreferenced_provider"]


def test_an_entry_with_a_separator_in_its_name_is_dropped():
	doc = document(models=[{"provider": "OpenAI", "model": "gpt&x", "label": "GPT X"}])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.selectable_items == ()
	assert "reserved_separator" in codes(catalog)


def test_an_entry_missing_its_label_is_dropped():
	doc = document(models=[{"provider": "OpenAI", "model": "gpt-x"}])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.selectable_items == ()
	assert "incomplete_entry" in codes(catalog)


def test_a_duplicate_id_keeps_the_first_entry():
	doc = document(models=[
		{"provider": "OpenAI", "model": "gpt-x", "label": "first"},
		{"provider": "OpenAI", "model": "gpt-x", "label": "second"},
	])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.labels_for("OpenAI") == ("first",)
	assert "duplicate_entry" in codes(catalog)


def test_the_same_id_on_both_channels_is_not_a_duplicate():
	doc = document(coseeings=[{"model": "gpt-x", "provider": "OpenAI", "label": "GPT X via Coseeing"}])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert codes(catalog) == []
	assert [item.execution_channel for item in catalog.selectable_items] == ["local", COSEEING_GROUP]


def test_an_inactive_entry_is_not_selectable_but_is_still_looked_up():
	doc = document(models=[{"provider": "OpenAI", "model": "gpt-x", "label": "GPT X", "active": False}])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.selectable_items == ()
	assert catalog.get_model("gpt-x&OpenAI") is not None


def test_an_unrecognised_schema_version_yields_an_empty_catalog():
	catalog = build_catalog(document(schema_version=99), runnable_providers=RUNNABLE)

	assert catalog.selectable_items == ()
	assert codes(catalog) == ["schema_version"]


def test_a_non_mapping_document_yields_an_empty_catalog():
	catalog = build_catalog("not a document", runnable_providers=RUNNABLE)

	assert catalog.selectable_items == ()
	assert codes(catalog) == ["malformed_document"]


def test_a_scalar_models_value_does_not_raise_and_is_a_malformed_document_issue():
	doc = document(models=5)
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.selectable_items == ()
	matches = [issue for issue in catalog.issues if issue.code == "malformed_document"]
	assert [issue.location for issue in matches] == ["models"]


def test_a_scalar_coseeings_value_does_not_raise_and_is_a_malformed_document_issue():
	doc = document(coseeings=7)
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.coseeings == ()
	matches = [issue for issue in catalog.issues if issue.code == "malformed_document"]
	assert [issue.location for issue in matches] == ["coseeings"]


def test_a_non_mapping_providers_value_does_not_raise_and_is_a_malformed_document_issue():
	doc = document(providers=[])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	matches = [issue for issue in catalog.issues if issue.code == "malformed_document"]
	assert [issue.location for issue in matches] == ["providers"]


def test_a_non_string_provider_key_does_not_raise():
	doc = document(providers={"OpenAI": dict(PROVIDER), 123: dict(PROVIDER, label="Bad key")})
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	matches = [issue for issue in catalog.issues if issue.code == "invalid_provider_name"]
	assert [issue.location for issue in matches] == ["providers.123"]
	assert catalog.get_provider("OpenAI") is not None


def test_coseeing_group_sorts_last_and_local_groups_sort_alphabetically():
	doc = document(
		providers={"OpenAI": dict(PROVIDER), "DeepSeek": dict(PROVIDER, label="DeepSeek")},
		models=[
			{"provider": "OpenAI", "model": "gpt-x", "label": "GPT X"},
			{"provider": "DeepSeek", "model": "ds-x", "label": "DS X"},
		],
		coseeings=[{"model": "default", "label": "Coseeing default"}],
	)
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.provider_groups == ("DeepSeek", "OpenAI", COSEEING_GROUP)


def test_default_selection_prefers_the_first_coseeing_entry():
	doc = document(coseeings=[{"model": "default", "label": "Coseeing default"}])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.default_selection() == ("default", COSEEING_GROUP)


def test_default_selection_falls_back_to_the_first_local_entry():
	catalog = build_catalog(document(), runnable_providers=RUNNABLE)

	assert catalog.default_selection() == ("gpt-x&OpenAI", "local")


def test_default_selection_raises_when_nothing_is_selectable():
	catalog = build_catalog(document(models=[]), runnable_providers=RUNNABLE)

	with pytest.raises(ValueError):
		catalog.default_selection()


def test_find_selection_and_get_item_round_trip():
	doc = document(coseeings=[{"model": "default", "label": "Coseeing default"}])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	indices = catalog.find_selection("default", COSEEING_GROUP)
	assert indices != (-1, -1)
	assert catalog.get_item(*indices).corrector_config_id == "default"


def test_find_selection_reports_a_miss():
	catalog = build_catalog(document(), runnable_providers=RUNNABLE)

	assert catalog.find_selection("nope", "local") == (-1, -1)


CATALOG_DIR = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge" / "lib" / "catalog"
STDLIB_ONLY = {"dataclasses", "json", "pathlib", "typing", "collections", "functools", "types", "copy"}


def test_the_catalog_package_imports_only_the_standard_library():
	# Walked from the AST rather than observed at runtime, so an import that
	# merely happens not to execute cannot satisfy this.
	catalog_files = sorted(CATALOG_DIR.rglob("*.py"))
	# rglob (not glob) so a future subpackage isn't silently skipped, and an
	# explicit non-empty check so this cannot go quietly vacuous if
	# lib/catalog moves or CATALOG_DIR stops resolving.
	assert catalog_files, f"no .py files found under {CATALOG_DIR}"
	for path in catalog_files:
		tree = ast.parse(path.read_text(encoding="utf8"))
		for node in ast.walk(tree):
			if isinstance(node, ast.Import):
				roots = [alias.name.split(".")[0] for alias in node.names]
			elif isinstance(node, ast.ImportFrom):
				if node.level:
					continue
				roots = [(node.module or "").split(".")[0]]
			else:
				continue
			for root in roots:
				assert root in STDLIB_ONLY, f"{path.name} imports {root!r}"
