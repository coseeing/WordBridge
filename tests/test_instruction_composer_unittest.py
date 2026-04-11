import sys
import types
import unittest
from pathlib import Path


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


class InstructionComposerTests(unittest.TestCase):
	def test_lite_instruction_composer_builds_messages_and_guidance(self):
		from lib.llm.prompt_bundle import PromptBundle
		from lib.tasks.typo.prompt import LiteTypoPromptStrategy
		from lib.tasks.typo.text_policy import LiteTypoTextPolicy

		policy = LiteTypoTextPolicy("zh_traditional")
		composer = LiteTypoPromptStrategy(
			language="zh_traditional",
			template_name="Lite_v1.json",
			optional_guidance_enable={
				"keep_non_chinese_char": True,
				"no_explanation": True,
			},
			customized_words=["天器"],
		)

		prompt_bundle = composer.compose(
			input_text="abc天器",
			response_text_history=["前一次答案"],
			text_policy=policy,
		)

		self.assertIsInstance(prompt_bundle, PromptBundle)
		self.assertIn("abc天器", prompt_bundle.messages[-3]["content"])
		self.assertEqual(prompt_bundle.messages[-2], {"role": "assistant", "content": "前一次答案"})
		self.assertIn("'前一次答案'是錯誤答案", prompt_bundle.messages[-1]["content"])
		self.assertIn("勿將非漢字用漢字取代", prompt_bundle.system_template)
		self.assertIn("輸出答案即可", prompt_bundle.system_template)
		self.assertIn("參考詞彙: 天器", prompt_bundle.system_template)

	def test_standard_instruction_composer_renders_phone_input(self):
		from lib.tasks.typo.prompt import StandardTypoPromptStrategy
		from lib.tasks.typo.text_policy import StandardTypoTextPolicy

		policy = StandardTypoTextPolicy("zh_traditional")
		composer = StandardTypoPromptStrategy(
			language="zh_traditional",
			template_name="Standard_v1.json",
			optional_guidance_enable={
				"keep_non_chinese_char": False,
				"no_explanation": False,
			},
			customized_words=[],
		)

		prompt_bundle = composer.compose(
			input_text="天器",
			response_text_history=[],
			text_policy=policy,
		)

		self.assertIn("我說天器&", prompt_bundle.messages[-1]["content"])
		self.assertIn("我 說 天 器", prompt_bundle.messages[-1]["content"])
		self.assertEqual(prompt_bundle.system_template, "輸入為文字與其正確拼音，請修正錯字並輸出正確文字:\n(文字&拼音) => 文字")


if __name__ == "__main__":
	unittest.main()
