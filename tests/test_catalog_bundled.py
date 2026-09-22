import json
from pathlib import Path

from lib.catalog.document import SCHEMA_VERSION, build_catalog
from lib.catalog.model import COSEEING_GROUP
from lib.catalog.sources import BUNDLED_LABELS, BundledCatalogSource


ADDON_PATH = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge"
SETTING_DIR = ADDON_PATH / "setting"
RUNNABLE = frozenset({"OpenAI", "Anthropic", "Google", "OpenRouter", "DeepSeek", "Ollama"})


def shipped_catalog():
	document, issues = BundledCatalogSource(SETTING_DIR).load()
	assert issues == ()
	return build_catalog(document, runnable_providers=RUNNABLE)


def test_the_bundled_document_declares_the_current_schema_version():
	document, _ = BundledCatalogSource(SETTING_DIR).load()

	assert document["schema_version"] == SCHEMA_VERSION
	assert set(document) == {"schema_version", "providers", "models", "coseeings"}


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


def test_the_shipped_data_produces_only_the_known_lint_issue():
	catalog = shipped_catalog()

	assert [(issue.code, issue.location) for issue in catalog.issues] == [
		("unreferenced_provider", "providers.OpenRouter"),
	]


def test_the_sentinel_is_offered_on_the_coseeing_channel_only():
	catalog = shipped_catalog()

	assert catalog.get_coseeing("default") is not None
	assert catalog.get_model("default") is None


def test_the_sentinel_is_the_shipped_default_selection():
	assert shipped_catalog().default_selection() == ("default", COSEEING_GROUP)


def test_the_sentinel_matches_the_fallback_entry():
	from lib.catalog.fallback import FALLBACK_DOCUMENT, SENTINEL_ID, SENTINEL_LABEL

	entry = shipped_catalog().get_coseeing(SENTINEL_ID)
	assert (entry.model, entry.label, entry.provider) == (
		FALLBACK_DOCUMENT["coseeings"][0]["model"],
		SENTINEL_LABEL,
		None,
	)


def test_the_shipped_coseeing_labels_are_pinned():
	# Acceptance 4's Coseeing half otherwise rests on nothing but a manual
	# check. This pins the underlying catalog labels -- not the settings
	# panel's rendering, which (after the sentinel translation fix in
	# dialogs.py) substitutes a translated string for the sentinel's entry
	# only; lib/catalog itself must never reach _() (spec decision 9).
	assert shipped_catalog().labels_for("Coseeing") == (
		"Coseeing default", "deepseek-v4-flash", "gpt-5.6-luna",
	)


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


def test_a_nested_non_mapping_price_value_drops_only_its_own_pricing(tmp_path):
	_write_minimal_setting_tree(tmp_path)
	(tmp_path / "price.json").write_text(
		json.dumps({"gpt-x&OpenAI": [1, 2]}), encoding="utf8"
	)
	(tmp_path / "ai" / "OpenAI-00001-gpt-x.json").write_text(
		json.dumps({"active": True, "model": "gpt-x", "provider": "OpenAI", "coseeing": False}),
		encoding="utf8",
	)
	document, issues = BundledCatalogSource(tmp_path).load()

	assert [entry["model"] for entry in document["models"]] == ["gpt-x"]
	assert "pricing" not in document["models"][0]
	assert [issue.code for issue in issues] == ["malformed_price_entry"]
	assert [issue.location for issue in issues] == ["gpt-x&OpenAI"]


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
