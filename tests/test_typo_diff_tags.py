import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"

# Several test modules stub _wb_vendor.chinese_converter with identity
# functions through sys.modules.setdefault(), and whichever module imports
# first wins for the whole session. Anything that needs the real vendored
# converter therefore runs in a clean subprocess.
BOOTSTRAP = textwrap.dedent(
	f"""
	import sys
	import types
	from pathlib import Path

	ADDON = Path({str(ADDON_PATH)!r})
	sys.path.insert(0, str(ADDON))

	addon_handler = types.ModuleType("addonHandler")
	addon_handler.initTranslation = lambda: None
	sys.modules["addonHandler"] = addon_handler

	from lib import vendor

	vendor.install(vendor.default_roots(str(ADDON / "package")))
	"""
)


def run_in_subprocess(code: str, *, optimized: bool = False) -> subprocess.CompletedProcess:
	argv = [sys.executable]
	if optimized:
		argv.append("-O")
	argv.extend(["-c", BOOTSTRAP + textwrap.dedent(code)])
	return subprocess.run(argv, capture_output=True, text=True)


def test_analyze_diff_flags_a_traditional_to_simplified_change():
	from lib.tasks.typo import utils

	simplified = {"體": "体", "体": "体"}
	traditional = {"體": "體", "体": "體"}
	with patch.object(utils, "to_simplified", lambda char: simplified.get(char, char)), \
			patch.object(utils, "to_traditional", lambda char: traditional.get(char, char)):
		assert "Tranditional to simplified" in utils.analyze_diff("體", "体")


def test_analyze_diff_flags_a_simplified_to_traditional_change():
	from lib.tasks.typo import utils

	simplified = {"體": "体", "体": "体"}
	traditional = {"體": "體", "体": "體"}
	with patch.object(utils, "to_simplified", lambda char: simplified.get(char, char)), \
			patch.object(utils, "to_traditional", lambda char: traditional.get(char, char)):
		assert "Simplified to tranditional" in utils.analyze_diff("体", "體")


def test_analyze_diff_does_not_flag_a_plain_typo_as_a_conversion():
	from lib.tasks.typo import utils

	with patch.object(utils, "to_simplified", lambda char: char), \
			patch.object(utils, "to_traditional", lambda char: char):
		tags = utils.analyze_diff("器", "氣")

	assert "Tranditional to simplified" not in tags
	assert "Simplified to tranditional" not in tags


def test_analyze_diff_uses_the_real_vendored_converter():
	result = run_in_subprocess(
		"""
		from lib.tasks.typo.utils import analyze_diff

		assert "Tranditional to simplified" in analyze_diff("體", "体"), analyze_diff("體", "体")
		assert "Simplified to tranditional" in analyze_diff("体", "體"), analyze_diff("体", "體")
		"""
	)
	assert result.returncode == 0, result.stderr
