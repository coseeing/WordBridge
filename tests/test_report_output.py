import json
import logging
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

	result = None
	for _ in range(12):
		result = generate_report(DIFF_DATA, root=tmp_path)

	from lib.report import REPORT_DIR_PATTERN

	generated = sorted(
		path.name for path in reports.iterdir()
		if path.is_dir() and REPORT_DIR_PATTERN.fullmatch(path.name)
	)
	# Normally exactly 10 survive. But all 12 calls above can land in the same
	# wall-clock second (they did in this run), in which case the just-created
	# report is protected from deletion even when the one-second-resolution
	# name sort would otherwise have picked it as the oldest -- so at worst
	# 11 survive for that one cycle. Both are correct; what must never happen
	# is fewer than 10, or the just-returned report going missing (below).
	assert len(generated) in (10, 11)
	assert (stranger / "keep.txt").exists()
	# The report just generated (and returned to the caller, who is about to
	# os.startfile() it) must never be among the ones retention deleted. The
	# directory-name timestamp is only one-second resolution, so without an
	# explicit protection this is flaky, not merely theoretical -- 12/60
	# trials of this exact 12-in-a-row scenario reproduced the deletion
	# against the pre-fix code.
	assert result.exists()
	assert result.parent.name in generated


def test_retention_runs_after_the_new_report_is_written(tmp_path, monkeypatch, caplog):
	# The spec says a failed deletion "is logged and does not abort the
	# report being generated"; only a failed *generation* step propagates to
	# the caller. This deliberately asserts NON-propagation -- the plan's
	# original snippet asserted `pytest.raises(OSError)`, which is the
	# opposite of what the spec requires (showReport() would then report
	# "could not be generated" and never call OnPreview(), even though
	# result.html was written successfully). The spec is the binding
	# authority here, not the plan's snippet.
	import lib.report as report_module

	def exploding(*args, **kwargs):
		raise OSError("retention blew up")

	monkeypatch.setattr(report_module, "_prune_old_reports", exploding)

	with caplog.at_level(logging.WARNING, logger=report_module.log.name):
		result = report_module.generate_report(DIFF_DATA, root=tmp_path)

	assert result.exists()
	assert any("retention blew up" in message for message in caplog.messages)

	reports = tmp_path / "reports"
	produced = [path for path in reports.iterdir() if path.is_dir() and path.name != "modules"]
	assert len(produced) == 1
	assert (produced[0] / "result.html").exists()


def test_a_failure_generating_the_report_still_propagates(tmp_path, monkeypatch):
	# The propagation path this task's design point relies on -- a failure in
	# the generation steps themselves (not retention) -- must still surface
	# to the caller so showReport() can notify the user.
	import lib.report as report_module

	def exploding(*args, **kwargs):
		raise OSError("disk full")

	monkeypatch.setattr(report_module, "text2template", exploding)

	with pytest.raises(OSError):
		report_module.generate_report(DIFF_DATA, root=tmp_path)


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


def test_prune_old_reports_orders_by_name_not_mtime(tmp_path):
	# Exercises _prune_old_reports's actual ordering (name-based, not mtime),
	# rather than a bare `sorted()` call on two literal strings that asserts
	# a property of Python's sort and touches none of the code under review.
	# The older-named directory must be the one deleted when only one slot
	# is kept, even though its mtime is made newer than the "younger"-named
	# one -- proving "most recent" is decided by name, not mtime.
	import os
	import time

	from lib.report import _prune_old_reports

	older_name = tmp_path / "20260920-235959-0000"
	newer_name = tmp_path / "20260921-143012-a3f9"
	older_name.mkdir()
	time.sleep(0.01)
	newer_name.mkdir()
	os.utime(older_name, None)

	_prune_old_reports(tmp_path, keep=1)

	assert not older_name.exists()
	assert newer_name.exists()
