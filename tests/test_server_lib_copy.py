"""server/app/lib is a copy of the add-on's lib; this keeps it one.

The server runs the same correction code as the add-on, so a fix made in one
copy must reach the other. Every file the server has must match the add-on's
file of the same path, with one deliberate difference: the add-on imports
its bundled packages under the _wb_vendor prefix (lib/vendor.py), while the
server installs them normally, so its imports drop the prefix.

The add-on may have files the server does not need (the remote catalog
modules, for example); the reverse is a file nobody keeps in sync.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
ADDON_LIB = ROOT / "addon" / "globalPlugins" / "WordBridge" / "lib"
SERVER_LIB = ROOT / "server" / "app" / "lib"

# vendor.py and coseeing_auth.py only ever run inside NVDA, where the prefix
# is real, so the server copy keeps it there.
_UNPREFIXED = frozenset(
	{
		"tasks/typo/prompt.py",
		"tasks/typo/text_policy.py",
		"tasks/typo/utils.py",
		"text/chinese.py",
	},
)


def _server_files():
	return sorted(
		path.relative_to(SERVER_LIB).as_posix()
		for path in SERVER_LIB.rglob("*")
		if path.is_file() and "__pycache__" not in path.parts
	)


def _as_on_the_server(relative, text):
	if relative not in _UNPREFIXED:
		return text
	text = re.sub(r"^from _wb_vendor\.(\w+) import ", r"from \1 import ", text, flags=re.MULTILINE)
	return re.sub(r"^from _wb_vendor import (\w+)$", r"import \1", text, flags=re.MULTILINE)


def test_the_server_has_no_file_the_add_on_lacks():
	missing = [relative for relative in _server_files() if not (ADDON_LIB / relative).is_file()]

	assert missing == []


@pytest.mark.parametrize("relative", _server_files())
def test_the_server_file_matches_the_add_on(relative):
	addon = (ADDON_LIB / relative).read_bytes()
	server = (SERVER_LIB / relative).read_bytes()
	if relative.endswith(".py"):
		addon = _as_on_the_server(relative, addon.decode("utf-8")).encode("utf-8")

	assert server == addon, f"server/app/lib/{relative} differs from the add-on's lib/{relative}"


@pytest.mark.parametrize("relative", sorted(_UNPREFIXED))
def test_the_unprefixed_files_really_use_the_prefix_in_the_add_on(relative):
	# Keeps _UNPREFIXED honest: a name here that no longer needs the rewrite
	# would hide a real difference.
	assert "_wb_vendor" in (ADDON_LIB / relative).read_text(encoding="utf-8")
