from pathlib import Path

from lib.catalog.fallback import load_catalog
from lib.catalog.model import COSEEING_GROUP, CatalogIssue
from lib.catalog.selection import SelectionState
from lib.catalog.sources import BundledCatalogSource
from lib.llm import SUPPORTED_PROVIDERS


SETTING_DIR = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge" / "setting"


class FakeRemoteCatalogSource:
	"""What a RemoteCatalogSource will be: a document from somewhere else.

	It holds no HTTP, no cache and no retry, because none of that changes what
	the rest of the add-on sees. That is the claim this test exists to prove.
	"""

	def __init__(self, document):
		self.document = document

	def load(self):
		return self.document, ()


class FakeSourceWithNoIssues:
	"""A source that reports its second tuple element as None instead of ().

	This is exactly the shape a not-yet-written RemoteCatalogSource could
	return -- a 200 response with nothing to report -- and load_catalog()
	must degrade to the sentinel rung rather than let TypeError escape
	tuple(None), which would otherwise propagate straight out of
	GlobalPlugin.__init__.
	"""

	def __init__(self, document):
		self.document = document

	def load(self):
		return self.document, None


class FakeSourceReportingAnIssue:
	"""A source that actually uses the issues half of the (document, issues)
	contract -- proving that half is wired end to end, not just declared.
	"""

	def __init__(self, document, issue):
		self.document = document
		self.issue = issue

	def load(self):
		return self.document, (self.issue,)


def test_a_document_from_a_remote_source_behaves_exactly_like_the_bundled_one():
	document, issues = BundledCatalogSource(SETTING_DIR).load()
	assert issues == ()

	bundled = load_catalog(BundledCatalogSource(SETTING_DIR), runnable_providers=SUPPORTED_PROVIDERS)
	remote = load_catalog(FakeRemoteCatalogSource(document), runnable_providers=SUPPORTED_PROVIDERS)

	assert remote.provider_groups == bundled.provider_groups
	assert remote.selectable_items == bundled.selectable_items
	assert remote.default_selection() == bundled.default_selection()
	assert [entry.price_entry() for entry in remote.models] == [
		entry.price_entry() for entry in bundled.models
	]


def test_a_remote_document_can_add_a_model_with_no_code_change():
	document, _ = BundledCatalogSource(SETTING_DIR).load()
	document["models"] = document["models"] + [{
		"provider": "OpenAI",
		"model": "gpt-9-future",
		"label": "GPT 9 Future",
		"pricing": {"input_tokens": 1, "output_tokens": 2, "base_unit": 1000000},
		"usage_key": "usage",
	}]
	catalog = load_catalog(FakeRemoteCatalogSource(document), runnable_providers=SUPPORTED_PROVIDERS)

	assert "GPT 9 Future" in catalog.labels_for("OpenAI")
	entry = catalog.get_model("gpt-9-future&OpenAI")
	assert entry.price_entry()["pricing"]["input_tokens"] == 1


def test_a_remote_document_naming_an_unimplemented_provider_offers_only_coseeing():
	document, _ = BundledCatalogSource(SETTING_DIR).load()
	document["providers"] = dict(document["providers"], Mistral={
		"label": "Mistral",
		"url": "https://example.invalid",
		"setting": {},
		"timeout0": 10,
		"timeout_max": 20,
	})
	document["models"] = document["models"] + [
		{"provider": "Mistral", "model": "m-large", "label": "M Large"}
	]
	document["coseeings"] = document["coseeings"] + [
		{"model": "m-large", "provider": "Mistral", "label": "M Large"}
	]
	catalog = load_catalog(FakeRemoteCatalogSource(document), runnable_providers=SUPPORTED_PROVIDERS)

	assert "Mistral" not in catalog.provider_groups
	assert "M Large" in catalog.labels_for(COSEEING_GROUP)
	assert "unsupported_provider" in {issue.code for issue in catalog.issues}


def test_the_panel_facing_selection_is_identical_across_sources():
	document, _ = BundledCatalogSource(SETTING_DIR).load()
	bundled = load_catalog(BundledCatalogSource(SETTING_DIR), runnable_providers=SUPPORTED_PROVIDERS)
	remote = load_catalog(FakeRemoteCatalogSource(document), runnable_providers=SUPPORTED_PROVIDERS)

	from_bundled = SelectionState.restore(bundled, "", "")
	from_remote = SelectionState.restore(remote, "", "")

	assert from_bundled.provider_group == from_remote.provider_group
	assert from_bundled.current_item() == from_remote.current_item()


def test_a_source_reporting_no_issues_as_none_degrades_instead_of_raising():
	document, _ = BundledCatalogSource(SETTING_DIR).load()

	catalog = load_catalog(FakeSourceWithNoIssues(document), runnable_providers=SUPPORTED_PROVIDERS)

	# A source this well-behaved (a valid document, just a None instead of an
	# empty tuple) should not degrade the whole catalog to the sentinel --
	# the point is only that load_catalog() must not raise.
	assert catalog.degraded is False
	assert catalog.selectable_items != ()


def test_issues_a_source_reports_reach_the_catalog():
	document, _ = BundledCatalogSource(SETTING_DIR).load()
	issue = CatalogIssue("unreadable_file", "remote-payload.json", "simulated 500")

	catalog = load_catalog(
		FakeSourceReportingAnIssue(document, issue), runnable_providers=SUPPORTED_PROVIDERS
	)

	assert issue in catalog.issues
