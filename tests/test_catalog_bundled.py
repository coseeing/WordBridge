import json
from pathlib import Path

from lib.catalog.document import SCHEMA_VERSION, build_catalog
from lib.catalog.sources import BUNDLED_LABELS, BundledCatalogSource


ADDON_PATH = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge"
SETTING_DIR = ADDON_PATH / "setting"
RUNNABLE = frozenset({"OpenAI", "Anthropic", "Google", "OpenRouter", "DeepSeek", "Ollama"})


def shipped_catalog():
	document, issues = BundledCatalogSource(SETTING_DIR).load()
	assert issues == ()
	return build_catalog(document, runnable_providers=RUNNABLE)


def legacy_manager():
	from configManager import ConfigManager

	return ConfigManager(SETTING_DIR / "ai")


def test_the_bundled_document_declares_the_current_schema_version():
	document, _ = BundledCatalogSource(SETTING_DIR).load()

	assert document["schema_version"] == SCHEMA_VERSION
	assert set(document) == {"schema_version", "providers", "models", "coseeings"}


def test_provider_groups_match_the_legacy_manager():
	assert shipped_catalog().provider_groups == tuple(legacy_manager().provider_groups)


def test_every_group_offers_the_same_labels_as_the_legacy_manager():
	catalog, manager = shipped_catalog(), legacy_manager()

	for group in manager.provider_groups:
		manager.provider = group
		assert catalog.labels_for(group) == tuple(manager.model_labels), group


def test_every_provider_group_label_matches_the_legacy_manager():
	catalog, manager = shipped_catalog(), legacy_manager()

	assert tuple(
		catalog.get_provider(group).label if catalog.get_provider(group) else group
		for group in catalog.provider_groups
	) == tuple(manager.endpoint_labels)


def test_every_selectable_item_matches_the_legacy_manager():
	catalog, manager = shipped_catalog(), legacy_manager()

	expected = [
		(item.provider_group, item.corrector_config_id, item.execution_channel)
		for group in manager.provider_groups
		for item in manager.endpoints[group]
	]
	actual = [
		(item.provider_group, item.corrector_config_id, item.execution_channel)
		for item in catalog.selectable_items
	]
	assert actual == expected


def test_default_selection_matches_the_legacy_manager():
	assert shipped_catalog().default_selection() == legacy_manager().default_selection()


def test_every_price_entry_matches_price_json():
	price = json.loads((SETTING_DIR / "price.json").read_text(encoding="utf8"))
	catalog = shipped_catalog()

	for entry in catalog.models:
		assert entry.price_entry() == price.get(entry.corrector_config_id, {}), entry.corrector_config_id


def test_every_provider_entry_matches_its_json_file():
	catalog = shipped_catalog()

	for path in (SETTING_DIR / "provider").glob("*.json"):
		entry = catalog.get_provider(path.stem)
		assert entry is not None, path.name
		data = json.loads(path.read_text(encoding="utf8"))
		assert (entry.url, entry.setting, entry.timeout0, entry.timeout_max) == (
			data["url"], data["setting"], data["timeout0"], data["timeout_max"]
		), path.name
		assert entry.label == BUNDLED_LABELS.get(path.stem, path.stem)


def test_the_shipped_data_produces_only_the_known_lint_issues():
	# OpenRouter.json is named by no ai config. Coseeing.json is removed in a
	# later task; until then it is unreferenced too.
	catalog = shipped_catalog()

	assert sorted(issue.code for issue in catalog.issues) == [
		"unreferenced_provider",
		"unreferenced_provider",
	]
	assert sorted(issue.location for issue in catalog.issues) == [
		"providers.Coseeing",
		"providers.OpenRouter",
	]


def test_an_ai_file_without_a_provider_becomes_a_coseeing_only_entry(tmp_path):
	_write_minimal_setting_tree(tmp_path)
	(tmp_path / "ai" / "Coseeing-00000-default.json").write_text(
		json.dumps({"active": True, "model": "default", "coseeing": True}), encoding="utf8"
	)
	document, issues = BundledCatalogSource(tmp_path).load()

	assert issues == ()
	assert [entry["model"] for entry in document["coseeings"]] == ["default"]
	assert document["models"] == []


def test_a_corrupt_ai_file_is_reported_and_skipped(tmp_path):
	_write_minimal_setting_tree(tmp_path)
	(tmp_path / "ai" / "OpenAI-00001-gpt-x.json").write_text(
		json.dumps({"active": True, "model": "gpt-x", "provider": "OpenAI", "coseeing": False}),
		encoding="utf8",
	)
	(tmp_path / "ai" / "Broken-00001.json").write_text("{not json", encoding="utf8")
	document, issues = BundledCatalogSource(tmp_path).load()

	assert [entry["model"] for entry in document["models"]] == ["gpt-x"]
	assert [issue.code for issue in issues] == ["unreadable_file"]


def test_a_wrong_typed_provider_file_is_reported_and_skipped(tmp_path):
	_write_minimal_setting_tree(tmp_path)
	(tmp_path / "provider" / "OpenAI.json").write_text("[1, 2]", encoding="utf8")
	document, issues = BundledCatalogSource(tmp_path).load()

	assert document["providers"] == {}
	assert [issue.code for issue in issues] == ["unreadable_file"]
	assert [issue.location for issue in issues] == ["OpenAI.json"]


def test_a_wrong_typed_price_file_is_reported_and_skipped(tmp_path):
	_write_minimal_setting_tree(tmp_path)
	(tmp_path / "price.json").write_text(json.dumps(["not", "a", "mapping"]), encoding="utf8")
	(tmp_path / "ai" / "OpenAI-00001-gpt-x.json").write_text(
		json.dumps({"active": True, "model": "gpt-x", "provider": "OpenAI", "coseeing": False}),
		encoding="utf8",
	)
	document, issues = BundledCatalogSource(tmp_path).load()

	assert [entry["model"] for entry in document["models"]] == ["gpt-x"]
	assert [issue.code for issue in issues] == ["unreadable_file"]
	assert [issue.location for issue in issues] == ["price.json"]


def test_a_wrong_typed_ai_file_is_reported_and_skipped(tmp_path):
	_write_minimal_setting_tree(tmp_path)
	(tmp_path / "ai" / "OpenAI-00001-gpt-x.json").write_text("42", encoding="utf8")
	document, issues = BundledCatalogSource(tmp_path).load()

	assert document["models"] == []
	assert document["coseeings"] == []
	assert [issue.code for issue in issues] == ["unreadable_file"]
	assert [issue.location for issue in issues] == ["OpenAI-00001-gpt-x.json"]


def _write_minimal_setting_tree(root: Path):
	(root / "ai").mkdir(parents=True)
	(root / "provider").mkdir(parents=True)
	(root / "provider" / "OpenAI.json").write_text(
		json.dumps({
			"name": "OpenAI",
			"url": "https://example.invalid",
			"setting": {},
			"timeout0": 10,
			"timeout_max": 20,
		}),
		encoding="utf8",
	)
	(root / "price.json").write_text("{}", encoding="utf8")
