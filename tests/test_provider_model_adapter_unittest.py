import importlib.util
import sys
import types
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"
PACKAGE_PATH = ADDON_PATH / "package"

sys.path.insert(0, str(ADDON_PATH))
sys.path.insert(0, str(PACKAGE_PATH))

addon_handler = types.ModuleType("addonHandler")
addon_handler.initTranslation = lambda: None
sys.modules.setdefault("addonHandler", addon_handler)

requests_module = types.ModuleType("requests")
requests_utils = types.ModuleType("requests.utils")
requests_utils.urlparse = urlparse
requests_module.utils = requests_utils
requests_module.get = lambda *args, **kwargs: None
requests_module.post = lambda *args, **kwargs: None
sys.modules.setdefault("requests", requests_module)
sys.modules.setdefault("requests.utils", requests_utils)

pypinyin_module = types.ModuleType("pypinyin")
pypinyin_module.lazy_pinyin = lambda text, style=None: list(text)
pypinyin_module.pinyin = lambda text, style=None: [[char] for char in text]

class _Style:
	TONE3 = object()

pypinyin_module.Style = _Style
sys.modules.setdefault("pypinyin", pypinyin_module)

chinese_converter_module = types.ModuleType("chinese_converter")
chinese_converter_module.to_traditional = lambda text: text
chinese_converter_module.to_simplified = lambda text: text
sys.modules.setdefault("chinese_converter", chinese_converter_module)


class ProviderModelAdapterTests(unittest.TestCase):
	def test_provider_model_adapter_module_exists(self):
		spec = importlib.util.find_spec("lib.llm.adapter")
		self.assertIsNotNone(spec)

	def test_openai_standard_models_use_default_adapter(self):
		from lib.llm.adapter import OpenAIChatAdapter, get_provider_model_adapter

		adapter = get_provider_model_adapter("OpenAI", "gpt-4.1-2025-04-14")

		self.assertIsInstance(adapter, OpenAIChatAdapter)
		payload = adapter.format_request(
			messages=[{"role": "user", "content": "原始文字"}],
			system_template="系統提示",
			setting={
				"max_completion_tokens": 4096,
				"seed": 0,
				"temperature": 0.0,
				"top_p": 0.0,
				"stop": [" =>"],
			},
		)

		self.assertEqual(payload["model"], "gpt-4.1-2025-04-14")
		self.assertEqual(payload["messages"][0], {"role": "system", "content": "系統提示"})
		self.assertEqual(payload["messages"][1], {"role": "user", "content": "原始文字"})
		self.assertIn("temperature", payload)
		self.assertIn("top_p", payload)
		self.assertIn("stop", payload)

	def test_openai_gpt5_family_uses_reasoning_adapter_override(self):
		from lib.llm.adapter import OpenAIReasoningAdapter, get_provider_model_adapter

		adapter = get_provider_model_adapter("OpenAI", "gpt-5")

		self.assertIsInstance(adapter, OpenAIReasoningAdapter)
		payload = adapter.format_request(
			messages=[{"role": "user", "content": "原始文字"}],
			system_template="系統提示",
			setting={
				"max_completion_tokens": 4096,
				"seed": 0,
				"temperature": 0.0,
				"top_p": 0.0,
				"stop": [" =>"],
			},
		)

		self.assertEqual(payload["model"], "gpt-5")
		self.assertEqual(payload["messages"][0]["role"], "user")
		self.assertTrue(payload["messages"][0]["content"].startswith("系統提示\n原始文字"))
		self.assertNotIn("temperature", payload)
		self.assertNotIn("top_p", payload)
		self.assertNotIn("stop", payload)

	def test_provider_sends_preformatted_payload_without_reformatting(self):
		from lib.llm.provider import OpenaiProvider

		captured = {}

		class FakeResponse:
			status_code = 200

			def json(self):
				return {"choices": [{"message": {"content": "ok"}}]}

		def fake_post(api_url, headers, json, timeout):
			captured["api_url"] = api_url
			captured["headers"] = headers
			captured["json"] = json
			captured["timeout"] = timeout
			return FakeResponse()

		provider = OpenaiProvider({"api_key": "test", "secret_key": ""})
		payload = {
			"model": "gpt-5",
			"messages": [{"role": "user", "content": "已格式化內容"}],
		}

		provider.retries = 1
		provider.backoff = 1

		with patch("lib.llm.provider.requests.post", side_effect=fake_post):
			response = provider.chat_completion(payload)

		self.assertEqual(captured["json"], payload)
		self.assertEqual(response["choices"][0]["message"]["content"], "ok")

	def test_google_provider_uses_model_name_to_build_request_url(self):
		from lib.llm.provider import GoogleProvider

		captured = {}

		class FakeResponse:
			status_code = 200

			def json(self):
				return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

		def fake_post(api_url, headers, json, timeout):
			captured["api_url"] = api_url
			captured["headers"] = headers
			captured["json"] = json
			captured["timeout"] = timeout
			return FakeResponse()

		provider = GoogleProvider({"api_key": "google-key", "secret_key": ""})
		payload = {"contents": [{"role": "user", "parts": [{"text": "已格式化內容"}]}]}

		provider.retries = 1
		provider.backoff = 1

		with patch("lib.llm.provider.requests.post", side_effect=fake_post):
			provider.send(payload, model_name="gemini-2.5-flash")

		self.assertEqual(
			captured["api_url"],
			"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=google-key",
		)
		self.assertEqual(captured["json"], payload)

	def test_adapter_calculates_total_usage_and_cost_from_usage_history(self):
		from lib.llm.adapter import get_provider_model_adapter

		adapter = get_provider_model_adapter("OpenAI", "gpt-4.1-2025-04-14")
		usage_history = [
			{"prompt_tokens": 10, "completion_tokens": 5},
			{"prompt_tokens": 1, "completion_tokens": 2},
		]

		self.assertEqual(
			adapter.get_total_usage(usage_history),
			{"prompt_tokens": 11, "completion_tokens": 7},
		)
		self.assertEqual(adapter.get_total_cost(usage_history), Decimal("0.000078"))

	def test_workflow_uses_executor_for_format_parse_and_usage(self):
		from lib.llm.executor import LLMExecutor
		from lib.tasks.typo.prompt import LiteTypoPromptStrategy
		from lib.tasks.typo.text_policy import LiteTypoTextPolicy
		from lib.tasks.typo.workflow import TypoCorrectionWorkflow

		class FakeProvider:
			def __init__(self):
				self.sent_payload = None
				self.sent_model_name = None
				self.try_connection_called = False
				self.setting = {
					"max_completion_tokens": 4096,
					"seed": 0,
					"temperature": 0.0,
					"top_p": 0.0,
					"stop": [" =>"],
				}

			def try_connection(self):
				self.try_connection_called = True

			def send(self, payload, model_name=None):
				self.sent_payload = payload
				self.sent_model_name = model_name
				return {
					"choices": [{"message": {"content": "修正文字"}}],
					"usage": {"prompt_tokens": 11, "completion_tokens": 7},
				}

		class FakeAdapter:
			provider_name = "OpenAI"
			model_name = "gpt-4.1-2025-04-14"

			def __init__(self):
				self.format_called = False
				self.parse_called = False
				self.extract_usage_called = False

			def format_request(self, messages, system_template, setting):
				self.format_called = True
				return {
					"model": self.model_name,
					"messages": [{"role": "system", "content": system_template}] + messages,
					**setting,
				}

			def parse_response(self, response):
				self.parse_called = True
				return response["choices"][0]["message"]["content"]

			def extract_usage(self, response):
				self.extract_usage_called = True
				return response["usage"]

			def get_model_entry(self):
				return {
					"pricing": {
						"prompt_tokens": 2,
						"completion_tokens": 8,
						"base_unit": 1000000,
					}
				}

			def get_total_usage(self, usage_history):
				return {"prompt_tokens": 11, "completion_tokens": 7}

			def get_total_cost(self, usage_history):
				return Decimal("0.000078")

		provider = FakeProvider()
		adapter = FakeAdapter()
		prompt_strategy = LiteTypoPromptStrategy(
			language="zh_traditional",
			template_name="Lite_v1.json",
			optional_guidance_enable={
				"keep_non_chinese_char": False,
				"no_explanation": False,
			},
			customized_words=[],
		)
		text_policy = LiteTypoTextPolicy("zh_traditional")
		executor = LLMExecutor(
			provider_object=provider,
			adapter_object=adapter,
		)

		workflow = TypoCorrectionWorkflow(
			executor=executor,
			prompt_strategy=prompt_strategy,
			text_policy=text_policy,
			max_correction_attempts=0,
		)
		result = workflow.run("測試文字", batch_mode=False)

		self.assertEqual(result.corrected_text, "修正文字")
		self.assertTrue(provider.try_connection_called)
		self.assertEqual(provider.sent_model_name, "gpt-4.1-2025-04-14")
		self.assertEqual(provider.sent_payload["model"], "gpt-4.1-2025-04-14")
		self.assertTrue(adapter.format_called)
		self.assertTrue(adapter.parse_called)
		self.assertTrue(adapter.extract_usage_called)
		self.assertEqual(
			executor.get_total_usage(),
			{"prompt_tokens": 11, "completion_tokens": 7},
		)
		self.assertEqual(executor.get_total_cost(), Decimal("0.000078"))


if __name__ == "__main__":
	unittest.main()
