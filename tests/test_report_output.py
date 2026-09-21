import json
import re
import sys
import types
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"
sys.path.insert(0, str(ADDON_PATH))

addon_handler = types.ModuleType("addonHandler")
addon_handler.initTranslation = lambda: None
sys.modules.setdefault("addonHandler", addon_handler)


DIFF_DATA = [
	{"operation": "equal", "before_text": "今天", "after_text": "今天", "before_descs": "", "after_descs": "", "tags": None},
	{"operation": "replace", "before_text": "器", "after_text": "氣", "before_descs": "", "after_descs": "", "tags": ["x"]},
]


def test_report_is_written_under_the_user_workspace(tmp_path):
	from lib.report import generate_report

	result = generate_report(DIFF_DATA, root=tmp_path)

	assert result.exists()
	assert result.parent.parent == tmp_path / "reports"
	assert result.name == "result.html"


def test_nothing_is_written_into_the_install_directory(tmp_path):
	from lib.report import generate_report

	before = {path for path in ADDON_PATH.rglob("*") if "__pycache__" not in str(path)}
	generate_report(DIFF_DATA, root=tmp_path)
	after = {path for path in ADDON_PATH.rglob("*") if "__pycache__" not in str(path)}

	assert before == after


def test_two_consecutive_reports_do_not_overwrite_each_other(tmp_path):
	from lib.report import generate_report

	first = generate_report(DIFF_DATA, root=tmp_path)
	second = generate_report(DIFF_DATA, root=tmp_path)

	assert first != second
	assert first.exists()
	assert second.exists()


def test_assets_are_provisioned_once_and_referenced_relatively(tmp_path):
	from lib.report import generate_report

	first = generate_report(DIFF_DATA, root=tmp_path)
	modules = tmp_path / "reports" / "modules"
	assert (modules / "vue.js").exists()
	assert (modules / "sweetalert2.all.min.js").exists()

	marker = modules / "vue.js"
	stamp = marker.stat().st_mtime_ns
	generate_report(DIFF_DATA, root=tmp_path)
	assert marker.stat().st_mtime_ns == stamp

	html = first.read_text(encoding="utf8")
	assert '"../modules/vue.js"' in html or "'../modules/vue.js'" in html or "../modules/vue.js" in html


def test_retention_keeps_ten_reports_and_only_touches_matching_directories(tmp_path):
	from lib.report import generate_report

	reports = tmp_path / "reports"
	reports.mkdir()
	stranger = reports / "not-a-report"
	stranger.mkdir()
	(stranger / "keep.txt").write_text("keep", encoding="utf8")

	for _ in range(12):
		generate_report(DIFF_DATA, root=tmp_path)

	from lib.report import REPORT_DIR_PATTERN

	generated = sorted(
		path.name for path in reports.iterdir()
		if path.is_dir() and REPORT_DIR_PATTERN.fullmatch(path.name)
	)
	assert len(generated) == 10
	assert (stranger / "keep.txt").exists()


def test_retention_runs_after_the_new_report_is_written(tmp_path, monkeypatch):
	import lib.report as report_module

	def exploding(*args, **kwargs):
		raise OSError("retention blew up")

	monkeypatch.setattr(report_module, "_prune_old_reports", exploding)

	with pytest.raises(OSError):
		report_module.generate_report(DIFF_DATA, root=tmp_path)

	reports = tmp_path / "reports"
	produced = [path for path in reports.iterdir() if path.is_dir() and path.name != "modules"]
	assert len(produced) == 1
	assert (produced[0] / "result.html").exists()


def test_a_failed_deletion_does_not_break_generation(tmp_path, monkeypatch):
	import lib.report as report_module

	for _ in range(11):
		report_module.generate_report(DIFF_DATA, root=tmp_path)

	def refuse(path, *args, **kwargs):
		raise PermissionError(str(path))

	monkeypatch.setattr(report_module.shutil, "rmtree", refuse)

	result = report_module.generate_report(DIFF_DATA, root=tmp_path)

	assert result.exists()


def test_report_directory_names_sort_chronologically():
	from lib.report import REPORT_DIR_PATTERN

	assert REPORT_DIR_PATTERN.fullmatch("20260921-143012-a3f9")
	assert not REPORT_DIR_PATTERN.fullmatch("modules")
	assert not REPORT_DIR_PATTERN.fullmatch("not-a-report")
	assert sorted(["20260921-143012-a3f9", "20260920-235959-0000"])[0] == "20260920-235959-0000"
