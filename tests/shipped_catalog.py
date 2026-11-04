"""The shipped catalog data, as the add-on sees it after a successful fetch.

Local-channel data (providers, models, prices) lives only in the server's
catalog file, which is the remote payload `GET /` serves. The add-on's bundled
file carries only the Coseeing channel. Tests about provider parameters,
prices or local model lists read the server file through here, so the
regression protection moves with the data.
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


def bundled_document() -> dict:
	return json.loads((ADDON_SETTING_DIR / "catalog.json").read_text(encoding="utf8"))


def shipped_overlay():
	"""The catalog a user sees after fetching the shipped server file."""
	return load_overlay_catalog(
		BundledCatalogSource(ADDON_SETTING_DIR),
		server_document(),
		runnable_providers=SUPPORTED_PROVIDERS,
	)


def dropped_issues(catalog) -> list:
	"""Issues other than lint: entries, providers or documents actually dropped."""
	from lib.catalog.model import is_dropped_issue

	return [issue for issue in catalog.issues if is_dropped_issue(issue)]
