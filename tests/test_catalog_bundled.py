import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from lib.catalog.document import SCHEMA_VERSION, build_catalog
from lib.catalog.model import COSEEING_GROUP
from lib.catalog.overlay import load_overlay_catalog
from lib.catalog.sources import BundledCatalogSource
from lib.llm import SUPPORTED_PROVIDERS
from shipped_catalog import bundled_document, server_document, shipped_overlay


ADDON_PATH = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge"
SETTING_DIR = ADDON_PATH / "setting"
CATALOG_PATH = SETTING_DIR / "catalog.json"


def shipped_document():
	return json.loads(CATALOG_PATH.read_text(encoding="utf8"))


def shipped_catalog():
	"""The bundled-only catalog, as the runtime builds it: through the overlay
	with no remote document (catalog_updater never builds the bundled file
	directly)."""
	_document, issues = BundledCatalogSource(SETTING_DIR).load()
	assert issues == ()
	return load_overlay_catalog(BundledCatalogSource(SETTING_DIR), None, runnable_providers=SUPPORTED_PROVIDERS)


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
	# Provider entries ship with the add-on (B1), and so does the model list
	# as it was at release time: it is used until a remote payload is
	# accepted, and whenever none can be loaded.
	assert set(document) == {"schema_version", "providers", "models", "coseeings"}


def test_the_bundled_catalog_alone_offers_the_shipped_model_list():
	catalog = shipped_catalog()

	def local_items(c):
		return [(item.corrector_config_id, item.label) for item in c.selectable_items if item.execution_channel == "local"]

	assert local_items(catalog) == local_items(shipped_overlay())
	assert catalog.labels_for(COSEEING_GROUP) == ("default",)
	assert [(issue.code, issue.location) for issue in catalog.issues] == [
		("unreferenced_provider", "providers.OpenRouter"),
	]
	assert catalog.degraded is False


# --- Guards on the bundled provider entries (spec 10.2) -------------------
# These replace the runtime host allowlist: the bundled file ships with the
# code, so a test is where a wrong URL is caught.

PINNED_URLS = {
	"Anthropic": "https://api.anthropic.com/v1/messages",
	"DeepSeek": "https://api.deepseek.com/chat/completions",
	"Google": "https://generativelanguage.googleapis.com/v1beta",
	"Ollama": "http://localhost:11434/v1/chat/completions",
	"OpenAI": "https://api.openai.com/v1/responses",
	"OpenRouter": "https://openrouter.ai/api/v1/chat/completions",
}
# The hosts RC section 9 allowed for each provider. Users' personal API keys
# are sent to these URLs (Google even puts the key in the query).
RC9_HOSTS = {
	"Anthropic": "api.anthropic.com",
	"DeepSeek": "api.deepseek.com",
	"Google": "generativelanguage.googleapis.com",
	"OpenAI": "api.openai.com",
	"OpenRouter": "openrouter.ai",
}
OLLAMA_HOSTS = frozenset({"localhost", "127.0.0.1"})


def test_the_bundled_providers_are_exactly_the_supported_providers():
	# A provider class cannot ship without a bundled entry, nor an entry
	# without a class.
	assert set(bundled_document()["providers"]) == SUPPORTED_PROVIDERS


def test_every_bundled_provider_url_is_pinned():
	# Changing a URL means changing this table deliberately.
	assert {name: data["url"] for name, data in bundled_document()["providers"].items()} == PINNED_URLS


def test_every_bundled_provider_url_is_on_its_rc9_host():
	for name, data in bundled_document()["providers"].items():
		parts = urlsplit(data["url"])
		assert parts.username is None and parts.password is None, name
		assert (parts.query, parts.fragment) == ("", ""), name
		if name == "Ollama":
			assert parts.hostname in OLLAMA_HOSTS, name
			continue
		assert parts.scheme == "https", name
		assert parts.port is None, name
		assert parts.hostname == RC9_HOSTS[name], name


def test_the_bundled_providers_build_completely():
	providers = bundled_document()["providers"]
	document = {
		"schema_version": SCHEMA_VERSION,
		"providers": providers,
		"models": [{"model": f"m-{name}", "provider": name, "label": name} for name in providers],
	}

	catalog = build_catalog(document, runnable_providers=SUPPORTED_PROVIDERS)

	assert set(catalog.providers) == set(providers)
	assert catalog.issues == ()


# --- Drift guard between the add-on and the server (spec 11) --------------

def _canonical(value):
	# Text, not ==: True == 1 and 0.0 == 0 in Python, so == would accept a
	# false that became 0 or a 0.0 that became 0 (spec finding 8).
	return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _first_differing_provider(bundled, server):
	for name in sorted(set(bundled) | set(server)):
		if name not in bundled or name not in server or _canonical(bundled[name]) != _canonical(server[name]):
			return name
	return None


def test_the_bundled_providers_equal_the_server_providers():
	# A provider parameter change edits both files in the same commit.
	bundled = bundled_document()["providers"]
	server = server_document()["providers"]

	assert _canonical(bundled) == _canonical(server), (
		f"first differing provider: {_first_differing_provider(bundled, server)}"
	)


def test_the_bundled_models_equal_the_server_models():
	# The bundled model list is the server's list at release time: a model
	# change edits both files in the same commit.
	bundled = bundled_document()["models"]
	server = server_document()["models"]

	assert _canonical(bundled) == _canonical(server), (
		f"first differing model index: {_first_differing_index(bundled, server)}"
	)


def _first_differing_index(bundled, server):
	for index in range(max(len(bundled), len(server))):
		if index >= len(bundled) or index >= len(server) or _canonical(bundled[index]) != _canonical(server[index]):
			return index
	return None


def _server_gains(bundled, server):
	server["Mistral"] = dict(server["OpenAI"], label="Mistral")


def _bundled_loses(bundled, server):
	del bundled["Google"]


def _float_to_int(bundled, server):
	bundled["DeepSeek"]["setting"]["temperature"] = 0


def _false_to_int(bundled, server):
	bundled["OpenAI"]["setting"]["store"] = 0


@pytest.mark.parametrize("mutate, expected", [
	(_server_gains, "Mistral"),
	(_bundled_loses, "Google"),
	(_float_to_int, "DeepSeek"),
	(_false_to_int, "OpenAI"),
], ids=["server-gains", "bundled-loses", "float-to-int", "false-to-int"])
def test_the_drift_message_names_the_first_differing_provider(mutate, expected):
	bundled = copy.deepcopy(bundled_document()["providers"])
	server = copy.deepcopy(bundled_document()["providers"])

	mutate(bundled, server)

	assert _canonical(bundled) != _canonical(server)
	assert _first_differing_provider(bundled, server) == expected


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
	# The new add-on offers only the sentinel on Coseeing (U8); a remote
	# payload cannot add Coseeing entries (D1).
	assert shipped_catalog().labels_for("Coseeing") == ("default",)
	assert shipped_overlay().labels_for("Coseeing") == ("default",)


# --- The runtime allowlist is gone (spec 10.1, AC6) ------------------------

ALLOWLIST_TOKENS = (
	"PROVIDER_URL_RULES",
	"ProviderUrlRule",
	"filter_provider_urls",
	"disallowed_provider_url",
	"disallowed_hosts",
	"provider addresses WordBridge does not allow",
)


def test_no_provider_host_allowlist_remains():
	# The guards above replace it; a runtime check of the bundled file would
	# run on data that ships with the code that checks it.
	addon = ADDON_PATH.parents[1]
	files = sorted(addon.rglob("*.py")) + [addon / "locale" / "zh_TW" / "LC_MESSAGES" / "nvda.po"]

	found = [
		(path.relative_to(addon).as_posix(), token)
		for path in files
		for token in ALLOWLIST_TOKENS
		if token in path.read_text(encoding="utf8")
	]

	assert found == []
