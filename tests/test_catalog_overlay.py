import copy
import json
from pathlib import Path

from lib.catalog import COSEEING_GROUP, LOCAL_CHANNEL, CatalogIssue, is_dropped_issue
from lib.catalog.overlay import OverlaySource, has_local_items, load_overlay_catalog, overlay_documents
from lib.llm import SUPPORTED_PROVIDERS


SERVER_CATALOG = Path(__file__).resolve().parents[1] / "server" / "app" / "setting" / "catalog.json"
SENTINEL = {"model": "default", "label": "default", "active": True}


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


def test_local_channel_comes_from_remote_and_coseeings_from_bundled():
	bundled = _bundled(
		coseeings=(SENTINEL, {"model": "bundled-extra", "label": "bundled-extra"}),
		providers={"DeepSeek": _provider("https://api.deepseek.com/chat/completions")},
		models=[{"model": "bundled-local", "provider": "DeepSeek", "label": "bundled-local"}],
	)

	catalog = _load(StaticSource(bundled), _remote())

	assert [entry.corrector_config_id for entry in catalog.models] == ["gpt-remote&OpenAI"]
	assert set(catalog.providers) == {"OpenAI"}
	assert catalog.labels_for(COSEEING_GROUP) == ("default", "bundled-extra")


def test_remote_coseeings_are_ignored_with_a_lint_issue():
	remote = dict(_remote(), coseeings=[{"model": "remote-only", "label": "remote-only"}])

	document, issues = overlay_documents(_bundled(), remote)

	assert document["coseeings"] == [SENTINEL]
	assert [(issue.code, issue.location) for issue in issues] == [("ignored_remote_coseeings", "remote.coseeings")]
	assert is_dropped_issue(issues[0]) is False


def test_bundled_local_entries_are_ignored_with_a_lint_issue():
	bundled = _bundled(providers={}, models=[])

	document, issues = overlay_documents(bundled, _remote())

	assert document["models"] == _remote()["models"]
	assert [(issue.code, issue.location) for issue in issues] == [("ignored_bundled_local_entries", "bundled")]
	assert is_dropped_issue(issues[0]) is False


def test_the_overlay_document_has_exactly_the_four_keys():
	document, _issues = overlay_documents(_bundled(), dict(_remote(), extra="ignored"))

	assert set(document) == {"schema_version", "providers", "models", "coseeings"}
	assert document["schema_version"] == 1


def test_no_remote_document_gives_the_sentinel_only():
	catalog = _load(StaticSource(_bundled()), None)

	assert catalog.provider_groups == (COSEEING_GROUP,)
	assert catalog.labels_for(COSEEING_GROUP) == ("default",)
	assert catalog.degraded is False
	assert catalog.issues == ()
	assert has_local_items(catalog) is False


def test_a_broken_bundled_file_plus_a_good_remote_gives_the_sentinel_and_local_items():
	broken = StaticSource(None, (CatalogIssue("unreadable_file", "catalog.json", "ValueError"),))

	catalog = _load(broken, _remote())

	assert has_local_items(catalog) is True
	assert catalog.labels_for(COSEEING_GROUP) == ("default",)
	assert catalog.default_selection() == ("default", COSEEING_GROUP)
	assert catalog.degraded is False
	fallback = [issue for issue in catalog.issues if issue.code == "bundled_coseeings_fallback"]
	assert len(fallback) == 1
	assert is_dropped_issue(fallback[0]) is True
	assert "unreadable_file" in _codes(catalog)


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


def test_a_disallowed_remote_provider_and_its_models_are_dropped():
	catalog = _load(StaticSource(_bundled()), _remote(url="https://evil.test/v1"))

	assert catalog.get_provider("OpenAI") is None
	assert "disallowed_provider_url" in _codes(catalog)
	assert "unknown_provider" in _codes(catalog)


def test_the_overlay_source_is_a_load_catalog_source():
	document, issues = OverlaySource(StaticSource(_bundled()), _remote()).load()

	assert document["coseeings"] == [SENTINEL]
	assert issues == ()


def test_the_shipped_target_files_overlay_as_section_7_4():
	# The target bundled content (spec section 2.3) inline, and today's server
	# file minus coseeings, which is exactly the target server content (spec
	# section 2.4). Task 16 switches this to the real files once both apply.
	server = json.loads(SERVER_CATALOG.read_text(encoding="utf8"))
	server.pop("coseeings", None)

	catalog = _load(StaticSource(_bundled()), server)

	assert catalog.provider_groups == ("Anthropic", "DeepSeek", "Google", "OpenAI", COSEEING_GROUP)
	local = [item for item in catalog.selectable_items if item.execution_channel == LOCAL_CHANNEL]
	assert len(local) == 16
	assert catalog.labels_for(COSEEING_GROUP) == ("default",)
	assert [(issue.code, issue.location) for issue in catalog.issues] == [
		("unreferenced_provider", "providers.OpenRouter"),
	]
	assert catalog.find_selection("gpt-6-luna&OpenAI", COSEEING_GROUP) == (-1, -1)
	assert catalog.find_selection("gpt-6-luna&OpenAI", LOCAL_CHANNEL) != (-1, -1)
