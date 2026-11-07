"""server/app/lib, dictionary and the prompt files are whole copies of the add-on's.

The server runs the same correction code as the add-on, so a change made in
one copy must reach the other. server/sync_addon_code.py makes the copies;
these tests fail when someone edits one side only, adds or deletes a file
on one side only, or changes the rewrite rule without the copies.
"""

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
_spec = importlib.util.spec_from_file_location("sync_addon_code", ROOT / "server" / "sync_addon_code.py")
sync_addon_code = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_addon_code)


def _files(root):
	return {
		path.relative_to(root).as_posix()
		for package in sync_addon_code.COPIED_DIRS
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


def test_the_prompt_directories_are_copied():
	assert "setting/templates/Standard_v1.json" in SERVER_FILES
	assert "setting/task/corrector.json" in SERVER_FILES
	# The server's catalog deliberately differs from the add-on's.
	assert "setting/catalog.json" not in ADDON_FILES


def test_the_version_file_matches_build_vars():
	# Read buildVars.py a second, simpler way, so a version bump needs no
	# test change and a broken read_addon_version() still fails here.
	declared = re.search(r'addon_version="([^"]+)"', sync_addon_code.BUILDVARS.read_text(encoding="utf-8"))
	assert declared is not None
	assert sync_addon_code.read_addon_version() == declared.group(1)
	written = sync_addon_code.ADDON_VERSION_FILE.read_text(encoding="utf-8")
	assert written == declared.group(1) + "\n"


def test_read_addon_version_reads_the_keyword(tmp_path):
	buildvars = tmp_path / "buildVars.py"
	buildvars.write_text('addon_info = AddonInfo(addon_name="x", addon_version="1.2.3")\n', encoding="utf-8")
	assert sync_addon_code.read_addon_version(buildvars) == "1.2.3"

	buildvars.write_text('addon_info = AddonInfo(addon_name="x")\n', encoding="utf-8")
	with pytest.raises(ValueError, match="addon_version"):
		sync_addon_code.read_addon_version(buildvars)


def test_sync_replaces_only_the_copied_dirs(tmp_path):
	addon = tmp_path / "addon"
	server_app = tmp_path / "server_app"
	for relative, text in {
		"lib/a.py": "a",
		"dictionary/d.txt": "d",
		"setting/templates/T.json": "t",
		"setting/task/c.json": "c",
		"setting/catalog.json": "add-on",
	}.items():
		(addon / relative).parent.mkdir(parents=True, exist_ok=True)
		(addon / relative).write_text(text, encoding="utf-8")
	for relative, text in {
		"setting/catalog.json": "server",
		"setting/templates/old.json": "old",
		"setting/cloudflare_ips.txt": "ranges",
	}.items():
		(server_app / relative).parent.mkdir(parents=True, exist_ok=True)
		(server_app / relative).write_text(text, encoding="utf-8")
	buildvars = tmp_path / "buildVars.py"
	buildvars.write_text('addon_info = AddonInfo(addon_version="9.9.9")\n', encoding="utf-8")

	sync_addon_code.sync(addon=addon, server_app=server_app, buildvars=buildvars)

	assert (server_app / "setting/catalog.json").read_text(encoding="utf-8") == "server"
	assert (server_app / "setting/cloudflare_ips.txt").read_text(encoding="utf-8") == "ranges"
	assert not (server_app / "setting/templates/old.json").exists()
	assert (server_app / "setting/templates/T.json").read_text(encoding="utf-8") == "t"
	assert (server_app / "setting/task/c.json").read_text(encoding="utf-8") == "c"
	assert (server_app / "lib/a.py").read_text(encoding="utf-8") == "a"
	assert (server_app / "setting/addon_version.txt").read_text(encoding="utf-8") == "9.9.9\n"
