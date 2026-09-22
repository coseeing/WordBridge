_CATALOG = None


def initialize(catalog) -> None:
	"""Install the process-wide catalog. Called once, from GlobalPlugin.__init__.

	This is a single value, but an explicitly installed one. The import-time
	construction it replaces ran whenever dialogs.py was imported, which made
	a damaged configuration a load failure for the whole add-on.
	"""
	global _CATALOG
	_CATALOG = catalog


def current():
	if _CATALOG is None:
		raise RuntimeError("catalog registry used before initialize()")
	return _CATALOG


def reset() -> None:
	"""Test hook. Production never calls this."""
	global _CATALOG
	_CATALOG = None
