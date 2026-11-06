"""Load a plugin-root module the way NVDA does: as a submodule of a package.

Plugin-root modules (catalog_updater.py, settings_repository.py) import their
siblings relatively, so a bare top-level import raises "attempted relative
import with no known parent package". A minimal package stub whose __path__
is the add-on directory reproduces the production shape without a full
plugin load (the technique tests/test_settings_repository.py uses).

The module's `.lib.catalog` is then a different module object from the
tests' own `lib.catalog`, so compare issues by code, not by class.
"""

import importlib.util
import sys
import types
from pathlib import Path

ADDON_PATH = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge"
PACKAGE_NAME = "wordbridge_plugin_module_probe"


def load_plugin_module(name: str):
	if PACKAGE_NAME not in sys.modules:
		package = types.ModuleType(PACKAGE_NAME)
		package.__path__ = [str(ADDON_PATH)]
		sys.modules[PACKAGE_NAME] = package
	full_name = f"{PACKAGE_NAME}.{name}"
	if full_name in sys.modules:
		return sys.modules[full_name]
	spec = importlib.util.spec_from_file_location(full_name, ADDON_PATH / f"{name}.py")
	module = importlib.util.module_from_spec(spec)
	sys.modules[full_name] = module
	spec.loader.exec_module(module)
	return module
