"""Copy the add-on's correction code and prompt files into the server.

The server runs the add-on's correction code, so server/app/lib and
server/app/dictionary are whole copies of the add-on's lib and dictionary,
including modules only NVDA can load. The prompts that code reads,
setting/templates and setting/task, are copied the same way. Run this after
changing any of them, or after changing addon_version in buildVars.py:

	python3 server/sync_addon_code.py

Each copied directory is replaced, not merged, so a file deleted in the
add-on goes from the server too. Only those directories are replaced:
server/app/setting also holds server-only files (catalog.json, which
deliberately differs from the add-on's, the Cloudflare ranges and the
version file), and they are left alone.

The add-on version is written to server/app/setting/addon_version.txt: the
server records it with every correction, and the image has no buildVars.py.

The one difference the copy makes: the add-on imports its bundled packages
under the _wb_vendor prefix (lib/vendor.py), while the server installs them
normally, so UNPREFIXED files drop the prefix. Every UNPREFIXED file must
exist in the add-on: one that was renamed or deleted stops the sync, so the
list is corrected instead of silently skipped.

The version and the UNPREFIXED files are checked before any directory is
replaced, so a failed sync leaves the server's copy as it was.
tests/test_server_addon_copy.py fails when the copies drift.
"""

import ast
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addon" / "globalPlugins" / "WordBridge"
SERVER_APP = ROOT / "server" / "app"
BUILDVARS = ROOT / "buildVars.py"
ADDON_VERSION_FILE = SERVER_APP / "setting" / "addon_version.txt"

# Directories under the add-on root, copied to the same path under server/app.
COPIED_DIRS = ("lib", "dictionary", "setting/templates", "setting/task")

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


def as_on_the_server(relative: str, text: str, unprefixed: frozenset = UNPREFIXED) -> str:
	"""The server's text for the add-on file at `relative` (see UNPREFIXED)."""
	if relative not in unprefixed:
		return text
	text = re.sub(r"^from _wb_vendor\.(\w+) import ", r"from \1 import ", text, flags=re.MULTILINE)
	return re.sub(r"^from _wb_vendor import (\w+)$", r"import \1", text, flags=re.MULTILINE)


def read_addon_version(buildvars: Path = BUILDVARS) -> str:
	"""The addon_version keyword argument in buildVars.py."""
	tree = ast.parse(buildvars.read_text(encoding="utf-8"))
	for node in ast.walk(tree):
		if (
			isinstance(node, ast.keyword)
			and node.arg == "addon_version"
			and isinstance(node.value, ast.Constant)
			and isinstance(node.value.value, str)
		):
			return node.value.value
	raise ValueError(f"{buildvars.name} sets no addon_version string")


def sync(
	*,
	addon: Path = ADDON,
	server_app: Path = SERVER_APP,
	buildvars: Path = BUILDVARS,
	unprefixed: frozenset = UNPREFIXED,
) -> None:
	"""Copy COPIED_DIRS from `addon` to `server_app` and write the version.

	Raises ValueError (no version) or FileNotFoundError (an `unprefixed`
	file missing from `addon`) before anything under `server_app` changes.
	"""
	version = read_addon_version(buildvars)
	missing = sorted(relative for relative in unprefixed if not (addon / relative).is_file())
	if missing:
		raise FileNotFoundError("UNPREFIXED names files the add-on does not have: " + ", ".join(missing))
	for relative in COPIED_DIRS:
		target = server_app / relative
		shutil.rmtree(target, ignore_errors=True)
		shutil.copytree(addon / relative, target, ignore=_IGNORED)
	for relative in unprefixed:
		path = server_app / relative
		text = as_on_the_server(relative, path.read_text(encoding="utf-8"), unprefixed)
		path.write_text(text, encoding="utf-8", newline="\n")
	version_file = server_app / ADDON_VERSION_FILE.relative_to(SERVER_APP)
	version_file.write_text(version + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
	sync()
