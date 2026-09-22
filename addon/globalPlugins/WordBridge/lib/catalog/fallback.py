from .document import SCHEMA_VERSION, build_catalog


SENTINEL_ID = "default"
# Not translated, like every other catalog label. See the note in sources.py.
SENTINEL_LABEL = "Coseeing default"

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
	"""Build a catalog from a source, degrading to the sentinel when empty."""
	document, source_issues = source.load()
	catalog = build_catalog(document, runnable_providers=runnable_providers)
	issues = tuple(source_issues) + catalog.issues
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
