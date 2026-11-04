"""Guard against .gitignore rules that silently drop source files from git.

The root .gitignore once carried an unanchored ``storage`` rule meant for the
repo-root ``storage/`` notes folder.  It also matched the server's
``app/package/coseeing_auth/storage/`` package, which was therefore never
committed: every fresh checkout (clone, CI, Docker build) failed with
``ModuleNotFoundError: No module named 'app.package.coseeing_auth.storage'``
while the original working copy kept working.  These tests ask git itself,
so they fail in any checkout where the rule regresses.
"""

import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STORAGE_MODULES = (
	"__init__.py",
	"macos_keychain.py",
	"storage.py",
	"windows_credentials.py",
)
STORAGE_PACKAGES = (
	"server/app/package/coseeing_auth/storage",
	"addon/globalPlugins/WordBridge/package/coseeing_auth/storage",
)
STORAGE_SOURCES = [
	f"{package}/{module}" for package in STORAGE_PACKAGES for module in STORAGE_MODULES
]


def _git(*args: str) -> subprocess.CompletedProcess:
	return subprocess.run(
		["git", "-C", str(PROJECT_ROOT), *args],
		check=False,
		capture_output=True,
		text=True,
	)


@pytest.fixture(scope="module", autouse=True)
def _require_git_checkout():
	if shutil.which("git") is None:
		pytest.skip("git is not installed")
	if _git("rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
		pytest.skip("not running from a git checkout")


@pytest.mark.parametrize("path", STORAGE_SOURCES)
def test_coseeing_auth_storage_module_is_tracked(path):
	result = _git("ls-files", "--error-unmatch", "--", path)
	assert result.returncode == 0, f"{path} is not tracked by git: {result.stderr}"


@pytest.mark.parametrize("path", STORAGE_SOURCES)
def test_coseeing_auth_storage_module_is_not_ignored(path):
	# --no-index evaluates the ignore rules even for tracked files, so a
	# force-added file under an ignoring rule is still reported.
	result = _git("check-ignore", "-v", "--no-index", "--", path)
	assert result.returncode == 1, f"{path} is matched by an ignore rule: {result.stdout}"


def test_root_storage_notes_folder_stays_ignored():
	result = _git("check-ignore", "-q", "--no-index", "--", "storage/notes.md")
	assert result.returncode == 0, "the repo-root storage/ folder must stay ignored"


def test_root_docs_folder_stays_ignored():
	result = _git("check-ignore", "-q", "--no-index", "--", "docs/notes.md")
	assert result.returncode == 0, "the repo-root docs/ folder must stay ignored"


@pytest.mark.parametrize("path", ["addon/docs/readme.md", "server/app/docs/index.md"])
def test_a_docs_folder_below_the_root_is_not_ignored(path):
	# An unanchored ``docs`` rule would hide any nested docs/ folder the same
	# way the old ``storage`` rule hid the server's storage package.
	result = _git("check-ignore", "-v", "--no-index", "--", path)
	assert result.returncode == 1, f"{path} is matched by an ignore rule: {result.stdout}"
