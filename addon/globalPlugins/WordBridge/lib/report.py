import json
import logging
import os
import re
import secrets
import shutil
from datetime import datetime
from pathlib import Path

from .paths import user_workspace_root
from .viewHTML import text2template


log = logging.getLogger(__name__)

ADDON_PATH = Path(__file__).resolve().parent.parent
TEMPLATE_MODULES_PATH = ADDON_PATH / "web" / "templates" / "modules"

REPORTS_DIR_NAME = "reports"
MODULES_DIR_NAME = "modules"
# Deliberately anchored: only directories this module created are ever
# eligible for deletion.
REPORT_DIR_PATTERN = re.compile(r"\d{8}-\d{6}-[0-9a-f]{4}")
DEFAULT_KEEP = 10


def _new_report_dir_name() -> str:
	# The random suffix keeps two reports generated within the same second
	# apart. The timestamp prefix sorts lexicographically in chronological
	# order, which is what retention relies on.
	return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


def _provision_modules(reports_root: Path) -> None:
	destination = reports_root / MODULES_DIR_NAME
	destination.mkdir(parents=True, exist_ok=True)
	for source in TEMPLATE_MODULES_PATH.iterdir():
		if not source.is_file():
			continue
		target = destination / source.name
		if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
			continue
		shutil.copyfile(source, target)


def _prune_old_reports(reports_root: Path, keep: int) -> None:
	directories = sorted(
		(path for path in reports_root.iterdir()
		 if path.is_dir() and REPORT_DIR_PATTERN.fullmatch(path.name)),
		key=lambda path: path.name,
	)
	for path in directories[:-keep] if keep > 0 else directories:
		try:
			shutil.rmtree(path)
		except OSError as error:
			# A browser may still hold a file open. The report just produced
			# matters more than reclaiming this directory.
			log.warning("WordBridge: could not remove the old report %s: %s", path, error)


def generate_report(diff_data, *, root: Path | None = None, keep: int = DEFAULT_KEEP) -> Path:
	"""Render diff_data into a self-contained report and return its HTML path.

	Nothing is written inside the add-on install directory: the template and
	the static modules are only ever read from it.
	"""
	workspace_root = Path(root) if root is not None else user_workspace_root()
	reports_root = workspace_root / REPORTS_DIR_NAME
	reports_root.mkdir(parents=True, exist_ok=True)

	_provision_modules(reports_root)

	report_dir = reports_root / _new_report_dir_name()
	report_dir.mkdir()

	raw_path = report_dir / "result.txt"
	raw_path.write_text(json.dumps(diff_data), encoding="utf8")

	html_path = report_dir / "result.html"
	text2template(str(raw_path), str(html_path))

	# Retention runs last, after the new report exists, so a retention failure
	# can never cost the report that was just produced.
	_prune_old_reports(reports_root, keep)

	return html_path
