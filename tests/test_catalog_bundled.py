import json
from pathlib import Path

from lib.catalog.document import SCHEMA_VERSION, build_catalog
from lib.catalog.model import COSEEING_GROUP
from lib.catalog.sources import BundledCatalogSource
from shipped_catalog import TEMPORARY_LINT_CODES, server_document, shipped_overlay


ADDON_PATH = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge"
SETTING_DIR = ADDON_PATH / "setting"
CATALOG_PATH = SETTING_DIR / "catalog.json"
RUNNABLE = frozenset({"OpenAI", "Anthropic", "Google", "OpenRouter", "DeepSeek", "Ollama"})


def shipped_document():
	return json.loads(CATALOG_PATH.read_text(encoding="utf8"))


def shipped_catalog():
	document, issues = BundledCatalogSource(SETTING_DIR).load()
	assert issues == ()
	return build_catalog(document, runnable_providers=RUNNABLE)


def _write_catalog(root: Path, document: dict) -> Path:
	path = root / "catalog.json"
	path.write_text(json.dumps(document), encoding="utf8")
	return path


def test_bundled_source_returns_the_canonical_catalog_document_unchanged(tmp_path):
	expected = {
		"schema_version": SCHEMA_VERSION,
		"providers": {},
		"models": [],
		"coseeings": [{"model": "default", "label": "default", "active": True}],
	}
	_write_catalog(tmp_path, expected)

	document, issues = BundledCatalogSource(tmp_path).load()

	assert document == expected
	assert issues == ()


def test_invalid_catalog_json_is_reported_at_the_canonical_file(tmp_path):
	(tmp_path / "catalog.json").write_text("{not json", encoding="utf8")

	document, issues = BundledCatalogSource(tmp_path).load()

	assert document is None
	assert [(issue.code, issue.location) for issue in issues] == [
		("unreadable_file", "catalog.json"),
	]


def test_non_mapping_catalog_json_is_reported_at_the_canonical_file(tmp_path):
	(tmp_path / "catalog.json").write_text("[]", encoding="utf8")

	document, issues = BundledCatalogSource(tmp_path).load()

	assert document is None
	assert [(issue.code, issue.location) for issue in issues] == [
		("unreadable_file", "catalog.json"),
	]


def test_the_bundled_document_declares_the_current_schema_version():
	document = shipped_document()

	assert document["schema_version"] == SCHEMA_VERSION
	# The Coseeing channel only: local providers and models come from the
	# remote payload, and no snapshot of it ships in the add-on (U1).
	assert set(document) == {"schema_version", "coseeings"}


def test_the_bundled_catalog_alone_offers_only_the_sentinel():
	catalog = shipped_catalog()

	assert catalog.provider_groups == (COSEEING_GROUP,)
	assert catalog.providers == {}
	assert catalog.models == ()
	assert catalog.issues == ()


def test_every_active_local_model_has_explicit_pricing_and_usage_metadata():
	catalog = shipped_overlay()

	assert catalog.models, "the shipped catalog has no model entries"
	for entry in catalog.models:
		if entry.active:
			assert entry.price_entry(), entry.corrector_config_id
			assert entry.usage_key, entry.corrector_config_id


def test_every_provider_entry_matches_its_canonical_document_value():
	document = server_document()
	catalog = shipped_overlay()

	assert document["providers"], "the shipped catalog has no providers"
	for name, data in document["providers"].items():
		entry = catalog.get_provider(name)
		assert entry is not None, name
		assert (entry.label, entry.url, entry.setting, entry.timeout0, entry.timeout_max) == (
			data["label"], data["url"], data["setting"], data["timeout0"], data["timeout_max"],
		), name


def test_the_shipped_data_produces_only_the_known_lint_issue():
	catalog = shipped_overlay()

	assert [
		(issue.code, issue.location) for issue in catalog.issues
		if issue.code not in TEMPORARY_LINT_CODES
	] == [
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
	# The new add-on offers only the sentinel on Coseeing (U8); a remote
	# payload cannot add Coseeing entries (D1).
	assert shipped_catalog().labels_for("Coseeing") == ("default",)
	assert shipped_overlay().labels_for("Coseeing") == ("default",)
