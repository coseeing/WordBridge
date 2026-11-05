"""The shipped catalog data, as the add-on sees it after a successful fetch.

The provider entries ship in the add-on's bundled file, next to the Coseeing
channel; the models (labels, prices) live in the server's catalog file, which
`GET /` serves, without its provider entries, as the remote payload
(served_document()). The server file keeps a copy of the provider entries for
the server's own calls, and tests/test_catalog_bundled.py keeps the two
copies equal. Tests about prices
or local model lists read the server file through here, so the regression
protection moves with the data.
"""

import json
from pathlib import Path

from lib.catalog.overlay import load_overlay_catalog
from lib.catalog.sources import BundledCatalogSource
from lib.llm import SUPPORTED_PROVIDERS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_SETTING_DIR = PROJECT_ROOT / "server" / "app" / "setting"
SERVER_CATALOG_PATH = SERVER_SETTING_DIR / "catalog.json"
ADDON_SETTING_DIR = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge" / "setting"


def server_document() -> dict:
	return json.loads(SERVER_CATALOG_PATH.read_text(encoding="utf8"))


def served_document() -> dict:
	"""What the server's GET / serves: its catalog file without `providers`
	(server/app/main.py, load_catalog_bytes)."""
	document = server_document()
	del document["providers"]
	return document


def served_bytes() -> bytes:
	"""The served payload as bytes, the way load_catalog_bytes writes it."""
	return (json.dumps(served_document(), ensure_ascii=False, indent="\t") + "\n").encode("utf8")


def bundled_document() -> dict:
	return json.loads((ADDON_SETTING_DIR / "catalog.json").read_text(encoding="utf8"))


def shipped_overlay():
	"""The catalog a user sees after fetching from the shipped server."""
	return load_overlay_catalog(
		BundledCatalogSource(ADDON_SETTING_DIR),
		served_document(),
		runnable_providers=SUPPORTED_PROVIDERS,
	)


def dropped_issues(catalog) -> list:
	"""Issues other than lint: entries, providers or documents actually dropped."""
	from lib.catalog.model import is_dropped_issue

	return [issue for issue in catalog.issues if is_dropped_issue(issue)]
