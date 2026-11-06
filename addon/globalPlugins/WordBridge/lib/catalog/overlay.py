"""Bundled ⊕ remote: one catalog document from the two sources.

The provider entries (`providers`) and the Coseeing channel (`coseeings`)
always come from the bundled file, which ships with the code that sends the
user's key. The models (`models`) come from exactly one document: the remote
payload when there is one, otherwise the bundled file, which carries the
model list as it was at release time. An accepted remote payload replaces
the bundled models as a whole; there is no merge, and every entry can be
traced to one file. Remote keys other than `models` are never read. Without
any models the provider entries are left out too: unused, they would only
add one unreferenced_provider issue per provider to every offline start.
"""

from .document import SCHEMA_VERSION, build_catalog
from .fallback import FALLBACK_DOCUMENT, load_catalog
from .model import COSEEING_GROUP, LOCAL_CHANNEL, CatalogIssue
from .remote import check_remote_document


def overlay_documents(bundled, remote) -> tuple:
	"""Returns (document, issues). Total: a non-mapping counts as absent."""
	bundled = bundled if isinstance(bundled, dict) else {}
	remote = remote if isinstance(remote, dict) else None
	if remote is not None:
		models = remote.get("models", [])
	else:
		models = bundled.get("models", [])
	# With a remote payload the providers are always offered, so a payload
	# without usable models is rejected for its models (remote_no_models),
	# not blamed on the bundled file.
	providers = bundled.get("providers", {}) if remote is not None or models else {}

	document = {
		"schema_version": SCHEMA_VERSION,
		"providers": providers,
		"models": models,
		"coseeings": bundled.get("coseeings", []),
	}
	return document, ()


def _offers_coseeing(coseeings) -> bool:
	probe = build_catalog(
		{"schema_version": SCHEMA_VERSION, "coseeings": coseeings},
		runnable_providers=frozenset(),
	)
	return bool(probe.items_for(COSEEING_GROUP))


class OverlaySource:
	"""A load_catalog() source for bundled ⊕ remote.

	The Coseeing sentinel is guaranteed here, at the document level: if the
	bundled file offers no active Coseeing entry (missing, corrupt, emptied),
	FALLBACK_DOCUMENT's entry is used instead. Doing it before the build --
	rather than after it -- keeps `degraded` meaning what it always meant:
	only a source that raises reaches load_catalog()'s fallback rung. Without
	the guarantee, a broken bundled file plus a good remote payload would
	leave no Coseeing group, and default_selection() would send every
	Coseeing user to the first local model.

	Exceptions from bundled_source.load() propagate on purpose, so
	load_catalog() degrades exactly as it does for any other source.
	"""

	def __init__(self, bundled_source, remote_document):
		self.bundled_source = bundled_source
		self.remote_document = remote_document

	def load(self) -> tuple:
		bundled, bundled_issues = self.bundled_source.load()
		document, overlay_issues = overlay_documents(bundled, self.remote_document)
		issues = tuple(bundled_issues or ()) + overlay_issues
		if not _offers_coseeing(document["coseeings"]):
			document["coseeings"] = [dict(entry) for entry in FALLBACK_DOCUMENT["coseeings"]]
			issues += (
				CatalogIssue(
					"bundled_coseeings_fallback",
					"coseeings",
					"no active Coseeing entry in the bundled catalog; using the built-in default",
				),
			)
		return document, issues


def load_overlay_catalog(bundled_source, remote_document, *, runnable_providers):
	return load_catalog(OverlaySource(bundled_source, remote_document), runnable_providers=runnable_providers)


def has_local_items(catalog) -> bool:
	return any(item.execution_channel == LOCAL_CHANNEL for item in catalog.selectable_items)


def accept_remote_document(bundled_source, document, *, runnable_providers) -> tuple:
	"""Returns (catalog, ()) for an accepted payload, (None, issues) otherwise.

	A payload is accepted as a whole or not at all: it must leave at least
	one selectable local model once overlaid on the bundled file, whose own
	models it then replaces. The same
	rule is applied to a cached payload, so a later add-on version with a
	different bundled provider set re-checks an old cache. The
	document-level checks run first, because overlay_documents() always
	writes schema_version 1 and build_catalog() would never see a wrong one.
	"""
	issues = check_remote_document(document)
	if issues:
		return None, issues
	catalog = load_overlay_catalog(bundled_source, document, runnable_providers=runnable_providers)
	if catalog.degraded:
		# OverlaySource guarantees the Coseeing sentinel, so only a bundled
		# source that raised reaches the fallback rung. Said so, rather than
		# blaming the payload with remote_no_models.
		return None, (CatalogIssue("bundled_source_failed", "bundled", "unreadable_source"),)
	if not catalog.providers:
		# Provider entries come only from the bundled file, so none at all
		# means it is missing, unreadable or lacks them -- a broken
		# installation, not a payload problem.
		return None, (CatalogIssue("bundled_source_failed", "bundled", "no_providers"),)
	if has_local_items(catalog):
		return catalog, ()
	return None, (
		CatalogIssue("remote_no_models", "payload", "the payload offers no selectable local model"),
	)
