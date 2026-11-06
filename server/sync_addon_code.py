"""Copy the add-on's lib and dictionary packages into the server.

The server runs the add-on's correction code, so server/app/lib and
server/app/dictionary are whole copies of the add-on's lib and dictionary,
including modules only NVDA can load. Run this after changing either
package in the add-on:

	python3 server/sync_addon_code.py

Each target is replaced, not merged, so a file deleted in the add-on goes
from the server too. The one difference it makes: the add-on imports its
bundled packages under the _wb_vendor prefix (lib/vendor.py), while the
server installs them normally, so UNPREFIXED files drop the prefix.
tests/test_server_addon_copy.py fails when the copies drift.
"""

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addon" / "globalPlugins" / "WordBridge"
SERVER_APP = ROOT / "server" / "app"

# Packages under the add-on root, copied to the same name under server/app.
PACKAGES = ("lib", "dictionary")

# Paths relative to those roots. lib/vendor.py and
# lib/coseeing_auth.py also use the prefix but only ever run inside NVDA,
# where it is real, so they are copied as they are.
UNPREFIXED = frozenset(
	{
		"lib/tasks/typo/prompt.py",
		"lib/tasks/typo/text_policy.py",
		"lib/tasks/typo/utils.py",
		"lib/text/chinese.py",
	},
)

_IGNORED = shutil.ignore_patterns("__pycache__", "*.pyc")


def as_on_the_server(relative: str, text: str) -> str:
	"""The server's text for the add-on file at `relative` (see UNPREFIXED)."""
	if relative not in UNPREFIXED:
		return text
	text = re.sub(r"^from _wb_vendor\.(\w+) import ", r"from \1 import ", text, flags=re.MULTILINE)
	return re.sub(r"^from _wb_vendor import (\w+)$", r"import \1", text, flags=re.MULTILINE)


def sync() -> None:
	for package in PACKAGES:
		target = SERVER_APP / package
		shutil.rmtree(target, ignore_errors=True)
		shutil.copytree(ADDON / package, target, ignore=_IGNORED)
	for relative in UNPREFIXED:
		path = SERVER_APP / relative
		text = as_on_the_server(relative, path.read_text(encoding="utf-8"))
		path.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
	sync()
