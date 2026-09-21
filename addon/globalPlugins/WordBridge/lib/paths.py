import os
from pathlib import Path


def user_workspace_root() -> Path:
	"""The WordBridge-workspace directory beside the NVDA user configuration.

	Six levels up from this file is the NVDA user configuration directory:
	lib/ -> WordBridge/ -> globalPlugins/ -> addon/ -> <add-on>/ -> addons/ -> <user config>.
	Extracted from dictionary/__init__.py so the dictionary and the report
	agree on one derivation instead of duplicating the chain.
	"""
	user_folder = Path(__file__).resolve().parents[5]
	return user_folder / "WordBridge-workspace"
