"""Bundled ⊕ remote: one catalog document from the two sources.

Each channel comes from exactly one document. The local channel
(`providers`, `models`) comes only from the remote payload and the Coseeing
channel (`coseeings`) only from the bundled file, so there are no merge or
precedence rules and every entry can be traced to one file. Keys found in the
wrong document are ignored with a lint issue; that is what makes "no snapshot
of the remote payload ships in the add-on" structural.
"""

from .document import SCHEMA_VERSION, build_catalog
from .fallback import FALLBACK_DOCUMENT, load_catalog
from .model import COSEEING_GROUP, LOCAL_CHANNEL, CatalogIssue
from .remote import filter_provider_urls


def overlay_documents(bundled, remote) -> tuple:
	"""Returns (document, issues). Total: a non-mapping counts as absent."""
	bundled = bundled if isinstance(bundled, dict) else {}
	remote = remote if isinstance(remote, dict) else None
	issues = []

	if "providers" in bundled or "models" in bundled:
		issues.append(CatalogIssue(
			"ignored_bundled_local_entries",
			"bundled",
			"the bundled catalog may not carry providers or models; they are ignored",
		))

	if remote is None:
		providers, models = {}, []
	else:
		if "coseeings" in remote:
			issues.append(CatalogIssue(
				"ignored_remote_coseeings",
				"remote.coseeings",
				"the remote catalog may not carry coseeings; they are ignored",
			))
		providers, provider_issues = filter_provider_urls(remote.get("providers", {}))
		issues.extend(provider_issues)
		models = remote.get("models", [])

	document = {
		"schema_version": SCHEMA_VERSION,
		"providers": providers,
		"models": models,
		"coseeings": bundled.get("coseeings", []),
	}
	return document, tuple(issues)


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
			issues += (CatalogIssue(
				"bundled_coseeings_fallback",
				"coseeings",
				"no active Coseeing entry in the bundled catalog; using the built-in default",
			),)
		return document, issues


def load_overlay_catalog(bundled_source, remote_document, *, runnable_providers):
	return load_catalog(OverlaySource(bundled_source, remote_document), runnable_providers=runnable_providers)


def has_local_items(catalog) -> bool:
	return any(item.execution_channel == LOCAL_CHANNEL for item in catalog.selectable_items)
