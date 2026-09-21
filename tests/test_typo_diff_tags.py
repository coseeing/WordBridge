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


def test_strings_diff_survives_a_multi_character_latin_token():
	from lib.tasks.typo.utils import strings_diff

	diff = strings_diff("我用 iPhone15 拍照", "我用 iPhone16 拍照")

	assert "".join(entry["before_text"] for entry in diff) == "我用 iPhone15 拍照"


def test_strings_diff_survives_a_url_token():
	from lib.tasks.typo.utils import strings_diff

	diff = strings_diff("請看 http://a.example 說明", "請看 http://b.example 說明")

	assert "".join(entry["after_text"] for entry in diff) == "請看 http://b.example 說明"


def test_find_correction_errors_keeps_non_chinese_text_without_scheduling_a_rerun():
	from lib.tasks.typo.utils import find_correction_errors

	fixed, typo_indices = find_correction_errors("我用 iPhone15 拍照", "我用 iPhone16 拍照")

	assert fixed == "我用 iPhone15 拍照"
	assert typo_indices == []


def test_review_correction_errors_rejects_a_non_chinese_replacement():
	from lib.tasks.typo.utils import review_correction_errors

	assert review_correction_errors("我用 iPhone15 拍照", "我用 iPhone16 拍照") == "我用 iPhone15 拍照"


def test_find_correction_errors_still_flags_a_non_homophone_chinese_replacement():
	from lib.tasks.typo.utils import find_correction_errors

	fixed, typo_indices = find_correction_errors("今天天氣真好", "今天天堂真好")

	assert fixed == "今天天氣真好"
	assert typo_indices == [3]


def test_is_chinese_character_rejects_multi_character_strings():
	from lib.text.chinese import is_chinese_character

	assert is_chinese_character("我") is True
	assert is_chinese_character("iPhone15") is False
	assert is_chinese_character("") is False


def test_get_char_pinyin_rejects_anything_but_a_single_chinese_character():
	from lib.tasks.typo.utils import get_char_pinyin

	with pytest.raises(ValueError):
		get_char_pinyin("iPhone15")


def test_create_single_char_mapping_rejects_too_many_tokens():
	from lib.tasks.typo.utils import MAX_MAPPED_TOKENS, create_single_char_mapping

	with pytest.raises(ValueError):
		create_single_char_mapping(["x"] * (MAX_MAPPED_TOKENS + 1))


def test_mixed_text_behaves_identically_under_python_O():
	result = run_in_subprocess(
		"""
		from lib.tasks.typo.utils import find_correction_errors, review_correction_errors, strings_diff

		before = "我用 iPhone15 拍照"
		after = "我用 iPhone16 拍照"
		if "".join(e["before_text"] for e in strings_diff(before, after)) != before:
			raise SystemExit("strings_diff lost text under -O")
		if find_correction_errors(before, after) != (before, []):
			raise SystemExit("find_correction_errors differs under -O")
		if review_correction_errors(before, after) != before:
			raise SystemExit("review_correction_errors differs under -O")
		""",
		optimized=True,
	)
	assert result.returncode == 0, result.stderr


def test_find_word_candidate_matches_a_chinese_character_against_its_bare_ascii_pinyin_letter():
	# 阿's pinyin set includes the bare letter "a" (a, ā, á, ǎ, à are all
	# pronunciations of 阿), so a customized word of 阿 has always matched
	# input containing a bare "a" -- this pins that pre-existing behaviour.
	from lib.tasks.typo.prompt import TypoPromptStrategy

	strategy = TypoPromptStrategy(language="zh_traditional", template_name="Lite_v1.json")

	assert strategy._find_word_candidate("hello a world", ["阿"]) == ["阿"]


def test_find_word_candidate_matches_a_non_chinese_customized_word_against_an_identical_run():
	from lib.tasks.typo.prompt import TypoPromptStrategy

	strategy = TypoPromptStrategy(language="zh_traditional", template_name="Lite_v1.json")

	assert strategy._find_word_candidate("xxabcxx", ["abc"]) == ["abc"]
	assert strategy._find_word_candidate("xxabdxx", ["abc"]) == []


def test_find_word_candidate_does_not_raise_for_a_chinese_non_chinese_pair():
	from lib.tasks.typo.prompt import TypoPromptStrategy

	strategy = TypoPromptStrategy(language="zh_traditional", template_name="Lite_v1.json")

	assert strategy._find_word_candidate("天x", ["天器"]) == []


def test_find_word_candidate_matches_homophonous_astral_plane_characters():
	# U+24EBA and U+28778 are both real entries in the vendored pinyin
	# dictionary (pronounced "tán") but neither is in is_chinese_character()'s
	# BMP-only interval table, so this pins the astral-plane half of the
	# pre-existing lookup behaviour.
	from lib.tasks.typo.prompt import TypoPromptStrategy
	from lib.text.chinese import is_chinese_character

	first, second = chr(0x24EBA), chr(0x28778)
	assert not is_chinese_character(first)
	assert not is_chinese_character(second)

	strategy = TypoPromptStrategy(language="zh_traditional", template_name="Lite_v1.json")

	assert strategy._find_word_candidate(f"x{first}x", [second]) == [second]
