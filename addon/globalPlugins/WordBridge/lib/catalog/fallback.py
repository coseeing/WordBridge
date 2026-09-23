from .document import SCHEMA_VERSION, build_catalog
from .model import CatalogIssue


SENTINEL_ID = "default"
# Not translated, like every other catalog label. See the note in sources.py.
SENTINEL_LABEL = "default"

# One entry, the same shape as any other document, parsed by the same
# build_catalog(). The id is a sentinel the Coseeing server resolves to its
# own current model, which is why no model, provider or price string is
# hard-coded here.
FALLBACK_DOCUMENT = {
	"schema_version": SCHEMA_VERSION,
	"providers": {},
	"models": [],
	"coseeings": [{"model": SENTINEL_ID, "label": SENTINEL_LABEL, "active": True}],
}


def load_catalog(source, *, runnable_providers):
	"""Build a catalog from a source, degrading to the sentinel when empty.

	source.load() is someone else's code -- today BundledCatalogSource, later
	a RemoteCatalogSource -- and build_catalog() was deliberately made total
	("problems become issues, never exceptions"). load() gets the same
	treatment here: whatever it raises is caught and turned into an issue, so
	a damaged or misbehaving source degrades to the sentinel rung instead of
	stopping NVDA from starting.
	"""
	try:
		document, source_issues = source.load()
		# Normalising the second element of the tuple stays inside the guard
		# deliberately: a source that returns e.g. (document, None) -- or any
		# other non-iterable second element -- must degrade to the sentinel
		# rung like any other misbehaving source, not raise TypeError straight
		# out of load_catalog (and so out of GlobalPlugin.__init__).
		source_issues = tuple(source_issues or ())
	except Exception as error:
		document = None
		source_issues = (CatalogIssue(
			"unreadable_source",
			type(source).__name__,
			f"{type(error).__name__}: {error}",
		),)
	catalog = build_catalog(document, runnable_providers=runnable_providers)
	issues = source_issues + catalog.issues
	if catalog.selectable_items:
		return type(catalog)(
			providers=catalog.providers,
			models=catalog.models,
			coseeings=catalog.coseeings,
			issues=issues,
			degraded=False,
		)
	fallback = build_catalog(FALLBACK_DOCUMENT, runnable_providers=runnable_providers)
	return type(fallback)(
		providers=fallback.providers,
		models=fallback.models,
		coseeings=fallback.coseeings,
		issues=issues + fallback.issues,
		degraded=True,
	)
