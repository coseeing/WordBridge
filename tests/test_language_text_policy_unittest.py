import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"
PACKAGE_PATH = ADDON_PATH / "package"

sys.path.insert(0, str(ADDON_PATH))
sys.path.insert(0, str(PACKAGE_PATH))

addon_handler = types.ModuleType("addonHandler")
addon_handler.initTranslation = lambda: None
sys.modules.setdefault("addonHandler", addon_handler)

pypinyin_module = types.ModuleType("pypinyin")
pypinyin_module.lazy_pinyin = lambda text, style=None: list(text)
pypinyin_module.pinyin = lambda text, style=None, heteronym=False: [[char] for char in text]


class _Style:
	TONE3 = object()


pypinyin_module.Style = _Style
sys.modules.setdefault("pypinyin", pypinyin_module)

chinese_converter_module = types.ModuleType("chinese_converter")
chinese_converter_module.to_traditional = lambda text: text
chinese_converter_module.to_simplified = lambda text: text
sys.modules.setdefault("chinese_converter", chinese_converter_module)

hanzidentifier_module = types.ModuleType("hanzidentifier")
hanzidentifier_module.MIXED = "mixed"
hanzidentifier_module.SIMPLIFIED = "simplified"
hanzidentifier_module.TRADITIONAL = "traditional"
hanzidentifier_module.identify = lambda text: hanzidentifier_module.TRADITIONAL
sys.modules.setdefault("hanzidentifier", hanzidentifier_module)


class LanguageTextPolicyTests(unittest.TestCase):
	def test_standard_language_text_policy_wraps_and_trims_text(self):
		from lib.tasks.typo.text_policy import StandardTypoTextPolicy

		policy = StandardTypoTextPolicy("zh_traditional")

		self.assertEqual(policy.preprocess_input("天器"), "我說天器")
		self.assertEqual(policy.postprocess_output("我說天氣", "天器"), "天氣")
		self.assertTrue(policy.has_target_language("天器"))
		self.assertFalse(policy.has_target_language("abc"))

	def test_standard_language_text_policy_does_not_strip_when_prefix_is_not_present(self):
		from lib.tasks.typo.text_policy import StandardTypoTextPolicy

		policy = StandardTypoTextPolicy("zh_traditional")

		self.assertEqual(policy.postprocess_output("天氣", "天器"), "天氣")

	def test_language_text_policy_normalizes_response_for_target_language(self):
		from lib.tasks.typo.text_policy import StandardTypoTextPolicy

		policy = StandardTypoTextPolicy("zh_traditional")

		with patch("lib.tasks.typo.text_policy.has_simplified_chinese_char", return_value=True):
			with patch("lib.tasks.typo.text_policy.chinese_converter.to_traditional", return_value="繁體結果"):
				self.assertEqual(policy.normalize_response("简体结果"), "繁體結果")


if __name__ == "__main__":
	unittest.main()
