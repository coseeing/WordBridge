import copy
import json
from pathlib import Path

import pytest
from lib.catalog import COSEEING_GROUP, LINT_ISSUE_CODES, LOCAL_CHANNEL, CatalogIssue, is_dropped_issue
from lib.catalog.document import build_catalog
from lib.catalog.overlay import (
	OverlaySource,
	accept_remote_document,
	has_local_items,
	load_overlay_catalog,
	overlay_documents,
)
from lib.catalog.sources import BundledCatalogSource
from lib.llm import SUPPORTED_PROVIDERS
from shipped_catalog import bundled_document, server_document

SERVER_CATALOG = Path(__file__).resolve().parents[1] / "server" / "app" / "setting" / "catalog.json"
SENTINEL = {"model": "default", "label": "default", "active": True}
OPENAI_URL = "https://api.openai.com/v1/responses"


class StaticSource:
	def __init__(self, document, issues=()):
		self.document = document
		self.issues = issues

	def load(self):
		return copy.deepcopy(self.document), self.issues


class RaisingSource:
	def load(self):
		raise RuntimeError("boom")


def _provider(url):
	return {"label": "x", "url": url, "setting": {}, "timeout0": 10, "timeout_max": 60}


def _remote(provider="OpenAI", model="gpt-remote", url="https://api.openai.com/v1/responses"):
	return {
		"schema_version": 1,
		"providers": {provider: _provider(url)},
		"models": [{"model": model, "provider": provider, "label": model}],
	}


def _bundled(coseeings=(SENTINEL,), **extra):
	return {"schema_version": 1, "coseeings": list(coseeings), **extra}


def _load(bundled_source, remote):
	return load_overlay_catalog(bundled_source, remote, runnable_providers=SUPPORTED_PROVIDERS)


def _codes(catalog):
	return [issue.code for issue in catalog.issues]


def test_providers_and_coseeings_come_from_bundled_and_models_from_remote():
	bundled = _bundled(
		coseeings=(SENTINEL, {"model": "bundled-extra", "label": "bundled-extra"}),
		providers={
			"OpenAI": _provider(OPENAI_URL),
			"DeepSeek": _provider("https://api.deepseek.com/chat/completions"),
		},
		models=[{"model": "bundled-local", "provider": "DeepSeek", "label": "bundled-local"}],
	)

	catalog = _load(StaticSource(bundled), _remote())

	assert [entry.corrector_config_id for entry in catalog.models] == ["gpt-remote&OpenAI"]
	assert set(catalog.providers) == {"DeepSeek", "OpenAI"}
	assert catalog.labels_for(COSEEING_GROUP) == ("default", "bundled-extra")


def _hostile_providers(document):
	document["providers"] = {
		name: {
			"label": "Evil",
			"url": "https://evil.test/v1",
			"setting": {"evil": True},
			"timeout0": 1,
			"timeout_max": 2,
		}
		for name in document["providers"]
	}
	return document


def test_remote_providers_never_reach_a_provider_entry():
	# AC2: every field of every provider entry comes from the bundled file.
	bundled = bundled_document()

	catalog = _load(StaticSource(bundled), _hostile_providers(server_document()))

	for name, data in bundled["providers"].items():
		entry = catalog.get_provider(name)
		assert (entry.label, entry.url, entry.setting, entry.timeout0, entry.timeout_max) == (
			data["label"],
			data["url"],
			data["setting"],
			data["timeout0"],
			data["timeout_max"],
		), name
	assert [(issue.code, issue.location) for issue in catalog.issues] == [
		("unreferenced_provider", "providers.OpenRouter"),
	]


def test_remote_extra_keys_add_no_issue():
	# Every NVDA start and fetch logs each issue as a warning; keys the
	# add-on does not read must not add a line.
	remote = dict(
		server_document(),
		coseeings=[{"model": "remote-only", "label": "remote-only"}],
		extra={"x": 1},
	)

	_document, issues = overlay_documents(bundled_document(), remote)

	assert issues == ()


def test_remote_coseeings_are_ignored_without_an_issue():
	remote = dict(_remote(), coseeings=[{"model": "remote-only", "label": "remote-only"}])

	document, issues = overlay_documents(_bundled(), remote)

	assert document["coseeings"] == [SENTINEL]
	assert issues == ()


def test_remote_models_replace_the_bundled_models_without_an_issue():
	# The bundled models are only the list shipped at release time: an
	# accepted remote payload replaces them as a whole, nothing is merged.
	bundled = _bundled(
		providers={"OpenAI": _provider(OPENAI_URL)},
		models=[{"model": "gpt-bundled", "provider": "OpenAI", "label": "gpt-bundled"}],
	)

	document, issues = overlay_documents(bundled, _remote())

	assert document["models"] == _remote()["models"]
	assert issues == ()


def test_without_a_remote_document_the_bundled_models_are_used():
	models = [{"model": "gpt-bundled", "provider": "OpenAI", "label": "gpt-bundled"}]
	providers = {"OpenAI": _provider(OPENAI_URL)}

	document, issues = overlay_documents(_bundled(providers=providers, models=models), None)

	assert document["models"] == models
	assert document["providers"] == providers
	assert issues == ()


def test_the_lint_codes_are_pinned():
	# unknown_provider: OQ1 -> B, Decided by the user (2026-11-05).
	assert LINT_ISSUE_CODES == {"unreferenced_provider", "unknown_provider"}


def test_the_overlay_document_has_exactly_the_four_keys():
	document, _issues = overlay_documents(_bundled(), dict(_remote(), extra="ignored"))

	assert set(document) == {"schema_version", "providers", "models", "coseeings"}
	assert document["schema_version"] == 1


def test_no_remote_document_and_no_bundled_models_gives_the_sentinel_only():
	# Without any models the bundled provider entries are not used -- that
	# would add one unreferenced_provider warning per provider to every
	# offline start.
	bundled = {key: value for key, value in bundled_document().items() if key != "models"}

	catalog = _load(StaticSource(bundled), None)

	assert catalog.providers == {}
	assert catalog.models == ()
	assert catalog.provider_groups == (COSEEING_GROUP,)
	assert catalog.labels_for(COSEEING_GROUP) == ("default",)
	assert catalog.degraded is False
	assert catalog.issues == ()
	assert has_local_items(catalog) is False


def test_no_remote_document_gives_the_shipped_bundled_models():
	# The list shipped at release time is offered before any remote catalog
	# loads, and whenever none can be loaded.
	catalog = _load(StaticSource(bundled_document()), None)

	assert has_local_items(catalog) is True
	assert [entry.corrector_config_id for entry in catalog.models] == [
		f"{entry['model']}&{entry['provider']}" for entry in bundled_document()["models"]
	]
	assert catalog.labels_for(COSEEING_GROUP) == ("default",)
	assert catalog.default_selection() == ("default", COSEEING_GROUP)
	assert catalog.degraded is False
	assert [(issue.code, issue.location) for issue in catalog.issues] == [
		("unreferenced_provider", "providers.OpenRouter"),
	]


def test_a_broken_bundled_file_plus_a_good_remote_gives_the_sentinel_and_no_local_items():
	# The provider entries have no second copy in the add-on (spec finding 4):
	# every remote model is dropped, but the Coseeing sentinel stays.
	broken = StaticSource(None, (CatalogIssue("unreadable_file", "catalog.json", "ValueError"),))

	catalog = _load(broken, _remote())

	assert has_local_items(catalog) is False
	assert catalog.labels_for(COSEEING_GROUP) == ("default",)
	assert catalog.default_selection() == ("default", COSEEING_GROUP)
	assert catalog.degraded is False
	fallback = [issue for issue in catalog.issues if issue.code == "bundled_coseeings_fallback"]
	assert len(fallback) == 1
	assert is_dropped_issue(fallback[0]) is True
	assert "unreadable_file" in _codes(catalog)
	assert "unknown_provider" in _codes(catalog)
	# As a payload (served without providers), it is rejected, and the
	# bundled file is named as the cause.
	served = {key: value for key, value in _remote().items() if key != "providers"}
	assert accept_remote_document(broken, served, runnable_providers=SUPPORTED_PROVIDERS) == (
		None,
		(CatalogIssue("bundled_source_failed", "bundled", "no_providers"),),
	)


def test_inactive_only_bundled_coseeings_fall_back_to_the_sentinel():
	bundled = _bundled(coseeings=({"model": "default", "label": "default", "active": False},))

	catalog = _load(StaticSource(bundled), _remote())

	assert catalog.labels_for(COSEEING_GROUP) == ("default",)
	assert "bundled_coseeings_fallback" in _codes(catalog)


def test_a_broken_bundled_file_and_no_remote_still_offers_the_sentinel_undegraded():
	catalog = _load(StaticSource(None, (CatalogIssue("unreadable_file", "catalog.json", "OSError"),)), None)

	assert catalog.provider_groups == (COSEEING_GROUP,)
	assert catalog.degraded is False
	assert "bundled_coseeings_fallback" in _codes(catalog)


def test_a_raising_bundled_source_degrades_to_the_fallback_rung():
	catalog = _load(RaisingSource(), _remote())

	assert catalog.degraded is True
	assert catalog.provider_groups == (COSEEING_GROUP,)
	assert "unreadable_source" in _codes(catalog)


def test_a_remote_provider_with_a_foreign_url_is_ignored():
	bundled = _bundled(providers={"OpenAI": _provider(OPENAI_URL)})

	catalog = _load(StaticSource(bundled), _remote(url="https://evil.test/v1"))

	assert catalog.get_provider("OpenAI").url == OPENAI_URL
	assert [entry.corrector_config_id for entry in catalog.models] == ["gpt-remote&OpenAI"]
	assert "unknown_provider" not in _codes(catalog)


@pytest.mark.parametrize("provider", ["Mistral", "openai", "OpenAI "])
def test_a_remote_model_for_a_provider_the_bundled_file_lacks_is_dropped(provider):
	# Names match exactly: no case folding, no trimming.
	remote = server_document()
	index = len(remote["models"])
	remote["models"].append({"model": "m-new", "provider": provider, "label": "M New"})

	catalog = _load(StaticSource(bundled_document()), remote)

	assert ("unknown_provider", f"models[{index}]") in [
		(issue.code, issue.location) for issue in catalog.issues
	]
	assert all(entry.model != "m-new" for entry in catalog.models)
	assert len([item for item in catalog.selectable_items if item.execution_channel == LOCAL_CHANNEL]) == 16


def test_the_overlay_source_is_a_load_catalog_source():
	providers = {"OpenAI": _provider(OPENAI_URL)}

	document, issues = OverlaySource(StaticSource(_bundled(providers=providers)), _remote()).load()

	assert document["providers"] == providers
	assert document["coseeings"] == [SENTINEL]
	assert issues == ()


def test_the_shipped_target_files_overlay_as_section_7_4():
	# The two shipped files, as applied from the target files (spec sections
	# 2.3 and 2.4): the add-on's bundled file and the server's catalog.
	from shipped_catalog import ADDON_SETTING_DIR

	server = json.loads(SERVER_CATALOG.read_text(encoding="utf8"))
	assert bundled_document() == _bundled(providers=server["providers"], models=server["models"])
	assert "coseeings" not in server

	catalog = load_overlay_catalog(
		BundledCatalogSource(ADDON_SETTING_DIR),
		server,
		runnable_providers=SUPPORTED_PROVIDERS,
	)

	assert catalog.provider_groups == ("Anthropic", "DeepSeek", "Google", "OpenAI", COSEEING_GROUP)
	local = [item for item in catalog.selectable_items if item.execution_channel == LOCAL_CHANNEL]
	assert len(local) == 16
	assert catalog.labels_for(COSEEING_GROUP) == ("default",)
	assert [(issue.code, issue.location) for issue in catalog.issues] == [
		("unreferenced_provider", "providers.OpenRouter"),
	]
	assert catalog.find_selection("gpt-6-luna&OpenAI", COSEEING_GROUP) == (-1, -1)
	assert catalog.find_selection("gpt-6-luna&OpenAI", LOCAL_CHANNEL) != (-1, -1)

	# AC2: exactly today's local data. At 774560b the add-on file and the
	# server file carried the same providers and models, and the add-on built
	# them directly; the reference is that direct build of the server
	# document, without the overlay, so anything the overlay loses or changes
	# (prices, labels, provider settings) shows up here.
	today = build_catalog(server, runnable_providers=SUPPORTED_PROVIDERS)

	def local_items(c):
		return [
			(item.corrector_config_id, item.label)
			for item in c.selectable_items
			if item.execution_channel == LOCAL_CHANNEL
		]

	assert local_items(catalog) == local_items(today)
	assert catalog.providers == today.providers
	assert [(entry.corrector_config_id, entry.active, entry.price_entry()) for entry in catalog.models] == [
		(entry.corrector_config_id, entry.active, entry.price_entry()) for entry in today.models
	]
	assert any(entry.price_entry() for entry in catalog.models), (
		"reference has no prices -- test would be vacuous"
	)
