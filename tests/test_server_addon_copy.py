"""server/app/lib and server/app/dictionary are whole copies of the add-on's.

The server runs the same correction code as the add-on, so a change made in
one copy must reach the other. server/sync_addon_code.py makes the copies;
these tests fail when someone edits one side only, adds or deletes a file
on one side only, or changes the rewrite rule without the copies.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
_spec = importlib.util.spec_from_file_location("sync_addon_code", ROOT / "server" / "sync_addon_code.py")
sync_addon_code = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_addon_code)


def _files(root):
	return {
		path.relative_to(root).as_posix()
		for package in sync_addon_code.PACKAGES
		for path in (root / package).rglob("*")
		if path.is_file() and "__pycache__" not in path.parts
	}


ADDON_FILES = _files(sync_addon_code.ADDON)
SERVER_FILES = _files(sync_addon_code.SERVER_APP)


def test_the_server_has_exactly_the_add_on_files():
	assert sorted(SERVER_FILES - ADDON_FILES) == [], "only on the server"
	assert sorted(ADDON_FILES - SERVER_FILES) == [], "only in the add-on"


@pytest.mark.parametrize("relative", sorted(SERVER_FILES & ADDON_FILES))
def test_the_server_file_matches_the_add_on(relative):
	addon = (sync_addon_code.ADDON / relative).read_bytes()
	server = (sync_addon_code.SERVER_APP / relative).read_bytes()
	if relative.endswith(".py"):
		addon = sync_addon_code.as_on_the_server(relative, addon.decode("utf-8")).encode("utf-8")

	assert server == addon, f"server/app/{relative} differs; run python3 server/sync_addon_code.py"


@pytest.mark.parametrize("relative", sorted(sync_addon_code.UNPREFIXED))
def test_the_unprefixed_files_really_use_the_prefix_in_the_add_on(relative):
	# Keeps UNPREFIXED honest: a name here that no longer needs the rewrite
	# would hide a real difference.
	assert "_wb_vendor" in (sync_addon_code.ADDON / relative).read_text(encoding="utf-8")
