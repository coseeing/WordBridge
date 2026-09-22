import pytest

from lib.catalog import registry
from lib.catalog.document import SCHEMA_VERSION, build_catalog
from lib.catalog.fallback import FALLBACK_DOCUMENT, SENTINEL_ID, load_catalog
from lib.catalog.model import COSEEING_GROUP
from lib.catalog.selection import normalize_selection


RUNNABLE = frozenset({"OpenAI"})


class FakeSource:
	def __init__(self, document, issues=()):
		self.document = document
		self.issues = tuple(issues)

	def load(self):
		return self.document, self.issues


class RaisingSource:
	"""A source whose load() blows up outside the (OSError, ValueError) that
	BundledCatalogSource._read_json already catches -- standing in for a bug
	in a source's own code, or any failure mode of a future network source.
	"""

	def load(self):
		raise RecursionError("boom")


def test_a_usable_document_is_not_replaced():
	document = {
		"schema_version": SCHEMA_VERSION,
		"providers": {"OpenAI": {
			"label": "OpenAI",
			"url": "https://example.invalid",
			"setting": {},
			"timeout0": 10,
			"timeout_max": 20,
		}},
		"models": [{"provider": "OpenAI", "model": "gpt-x", "label": "GPT X"}],
		"coseeings": [],
	}
	catalog = load_catalog(FakeSource(document), runnable_providers=RUNNABLE)

	assert catalog.degraded is False
	assert [item.corrector_config_id for item in catalog.selectable_items] == ["gpt-x&OpenAI"]


def test_an_unusable_document_falls_back_to_the_sentinel():
	catalog = load_catalog(FakeSource({"schema_version": 99}), runnable_providers=RUNNABLE)

	assert catalog.degraded is True
	assert [item.corrector_config_id for item in catalog.selectable_items] == [SENTINEL_ID]
	assert catalog.selectable_items[0].provider_group == COSEEING_GROUP
	assert catalog.selectable_items[0].execution_channel == COSEEING_GROUP


def test_the_fallback_keeps_the_issues_that_explain_it():
	catalog = load_catalog(FakeSource({"schema_version": 99}), runnable_providers=RUNNABLE)

	assert "schema_version" in {issue.code for issue in catalog.issues}


def test_source_level_issues_reach_the_catalog():
	from lib.catalog.model import CatalogIssue

	document = {"schema_version": SCHEMA_VERSION, "providers": {}, "models": [], "coseeings": []}
	source = FakeSource(document, [CatalogIssue("unreadable_file", "x.json", "boom")])
	catalog = load_catalog(source, runnable_providers=RUNNABLE)

	assert "unreadable_file" in {issue.code for issue in catalog.issues}


def test_a_source_that_raises_still_degrades_to_the_sentinel_instead_of_propagating():
	catalog = load_catalog(RaisingSource(), runnable_providers=RUNNABLE)

	assert catalog.degraded is True
	assert [item.corrector_config_id for item in catalog.selectable_items] == [SENTINEL_ID]
	assert "unreadable_source" in {issue.code for issue in catalog.issues}


def test_a_partially_broken_document_stays_undegraded_and_keeps_all_issues():
	from lib.catalog.model import CatalogIssue

	document = {
		"schema_version": SCHEMA_VERSION,
		"providers": {"OpenAI": {
			"label": "OpenAI",
			"url": "https://example.invalid",
			"setting": {},
			"timeout0": 10,
			"timeout_max": 20,
		}},
		"models": [
			{"provider": "OpenAI", "model": "gpt-x", "label": "GPT X"},
			{"provider": "OpenAI", "model": "broken"},  # no label -> incomplete_entry, skipped
		],
		"coseeings": [],
	}
	source = FakeSource(document, [CatalogIssue("unreadable_file", "extra.json", "boom")])
	catalog = load_catalog(source, runnable_providers=RUNNABLE)

	assert catalog.degraded is False
	assert "gpt-x&OpenAI" in [item.corrector_config_id for item in catalog.selectable_items]
	codes = {issue.code for issue in catalog.issues}
	assert "incomplete_entry" in codes
	assert "unreadable_file" in codes


def test_the_fallback_document_and_a_shipped_sentinel_produce_the_same_item():
	fallback = load_catalog(FakeSource({"schema_version": 99}), runnable_providers=RUNNABLE)
	shipped = build_catalog(
		{
			"schema_version": SCHEMA_VERSION,
			"providers": {},
			"models": [],
			"coseeings": list(FALLBACK_DOCUMENT["coseeings"]),
		},
		runnable_providers=RUNNABLE,
	)

	assert fallback.selectable_items == shipped.selectable_items


def test_a_stored_sentinel_still_resolves_against_a_healthy_catalog():
	document = {
		"schema_version": SCHEMA_VERSION,
		"providers": {},
		"models": [],
		"coseeings": [
			{"model": SENTINEL_ID, "label": "Coseeing default"},
			{"model": "ds-x", "provider": "DeepSeek", "label": "DS X"},
		],
	}
	catalog = build_catalog(document, runnable_providers=RUNNABLE)

	assert normalize_selection(catalog, SENTINEL_ID, COSEEING_GROUP) == (SENTINEL_ID, COSEEING_GROUP)


def test_the_registry_refuses_to_answer_before_it_is_initialised():
	registry.reset()

	with pytest.raises(RuntimeError):
		registry.current()


def test_the_registry_returns_what_was_installed():
	catalog = load_catalog(FakeSource({"schema_version": 99}), runnable_providers=RUNNABLE)
	registry.initialize(catalog)
	try:
		assert registry.current() is catalog
	finally:
		registry.reset()
