"""The remote seam: a fetched payload behaves exactly like the same content
loaded from disk.

The fetch path is the real one -- catalog_updater.fetch_payload() with a fake
http_get serving bytes, then parse_remote_payload() and the overlay -- and the
reference is the same documents overlaid in memory and built by
load_catalog(). Nothing downstream of the seam may tell the two apart.
"""

import json

import pytest
from fake_http import BodyResponse
from lib.catalog.fallback import load_catalog
from lib.catalog.model import COSEEING_GROUP, CatalogIssue
from lib.catalog.overlay import load_overlay_catalog, overlay_documents
from lib.catalog.remote import parse_remote_payload
from lib.catalog.selection import SelectionState
from lib.catalog.sources import BundledCatalogSource
from lib.llm import SUPPORTED_PROVIDERS
from plugin_modules import load_plugin_module
from shipped_catalog import (
	ADDON_SETTING_DIR,
	SERVER_CATALOG_PATH,
	bundled_document,
	served_document,
	server_document,
)

updater = load_plugin_module("catalog_updater")


class InMemorySource:
	def __init__(self, document, issues=()):
		self.document = document
		self.issues = issues

	def load(self):
		return self.document, self.issues


def _serve(body):
	return lambda url, **kwargs: BodyResponse(body)


def fetched_catalog(body: bytes, runnable_providers=SUPPORTED_PROVIDERS):
	result = updater.fetch_payload("https://wordbridge.coseeing.org", http_get=_serve(body))
	assert result.issue is None
	document, issues = parse_remote_payload(result.body)
	assert issues == ()
	return load_overlay_catalog(BundledCatalogSource(ADDON_SETTING_DIR), document, runnable_providers=runnable_providers)


def in_memory_catalog(remote_document):
	document, issues = overlay_documents(bundled_document(), remote_document)
	return load_catalog(InMemorySource(document, issues), runnable_providers=SUPPORTED_PROVIDERS)


def _body(document) -> bytes:
	return json.dumps(document).encode("utf8")


def test_a_fetched_payload_behaves_exactly_like_the_same_documents_from_disk():
	# What GET / serves: the server file without its providers.
	fetched = fetched_catalog(_body(served_document()))
	reference = in_memory_catalog(served_document())

	assert fetched.provider_groups == reference.provider_groups
	assert fetched.selectable_items == reference.selectable_items
	assert fetched.default_selection() == reference.default_selection()
	assert [entry.price_entry() for entry in fetched.models] == [
		entry.price_entry() for entry in reference.models
	]
	assert any(entry.price_entry() for entry in fetched.models)


def test_a_remote_document_can_add_a_model_with_no_code_change():
	document = served_document()
	document["models"] = document["models"] + [{
		"provider": "OpenAI",
		"model": "gpt-9-future",
		"label": "GPT 9 Future",
		"pricing": {"input_tokens": 1, "output_tokens": 2, "base_unit": 1000000},
		"usage_key": "usage",
	}]

	catalog = fetched_catalog(_body(document))

	assert "GPT 9 Future" in catalog.labels_for("OpenAI")
	assert catalog.get_model("gpt-9-future&OpenAI").price_entry()["pricing"]["input_tokens"] == 1


def test_a_model_for_a_provider_this_release_does_not_bundle_is_dropped():
	# Providers are bundled, so a remote document cannot add one: a model for
	# a provider only a newer release has is dropped, its siblings kept.
	document = served_document()
	document["models"] = document["models"] + [{"provider": "Mistral", "model": "m-large", "label": "M Large"}]

	catalog = fetched_catalog(_body(document))

	codes = {issue.code for issue in catalog.issues}
	assert "Mistral" not in catalog.provider_groups
	assert catalog.get_provider("Mistral") is None
	assert "M Large" not in catalog.labels_for(COSEEING_GROUP)
	assert "unknown_provider" in codes
	assert "unsupported_provider" not in codes
	assert len(catalog.models) == len(served_document()["models"])


def test_a_bundled_provider_this_build_cannot_run_drops_its_models():
	catalog = fetched_catalog(_body(served_document()), runnable_providers=SUPPORTED_PROVIDERS - {"DeepSeek"})

	assert "DeepSeek" not in catalog.provider_groups
	assert "unsupported_provider" in {issue.code for issue in catalog.issues}


def test_the_panel_facing_selection_is_identical_across_sources():
	fetched = fetched_catalog(_body(served_document()))
	reference = in_memory_catalog(served_document())

	from_fetched = SelectionState.restore(fetched, "", "")
	from_reference = SelectionState.restore(reference, "", "")

	assert from_fetched.provider_group == from_reference.provider_group
	assert from_fetched.current_item() == from_reference.current_item()


class FakeSourceWithNoIssues:
	"""A source that reports its second tuple element as None instead of ()."""

	def __init__(self, document):
		self.document = document

	def load(self):
		return self.document, None


def test_a_source_reporting_no_issues_as_none_degrades_instead_of_raising():
	catalog = load_catalog(FakeSourceWithNoIssues(server_document()), runnable_providers=SUPPORTED_PROVIDERS)

	# A valid document with None instead of () must not degrade the whole
	# catalog to the sentinel -- the point is only that load_catalog() must
	# not raise.
	assert catalog.degraded is False
	assert catalog.selectable_items != ()


def test_issues_a_source_reports_reach_the_catalog():
	issue = CatalogIssue("unreadable_file", "remote-payload.json", "simulated 500")

	catalog = load_catalog(InMemorySource(server_document(), (issue,)), runnable_providers=SUPPORTED_PROVIDERS)

	assert issue in catalog.issues


@pytest.mark.parametrize("chunk", [1, 7, 65536])
def test_the_fetch_reassembles_the_body_whatever_the_chunking(chunk, monkeypatch):
	body = SERVER_CATALOG_PATH.read_bytes()
	monkeypatch.setattr(updater, "CHUNK_BYTES", chunk)

	result = updater.fetch_payload("https://wordbridge.coseeing.org", http_get=_serve(body))

	assert result.body == body
