import sys
import types
import unittest
from decimal import Decimal
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
hanzidentifier_module.identify = lambda text: hanzidentifier_module.TRADITIONAL if text else ""
sys.modules.setdefault("hanzidentifier", hanzidentifier_module)


class TaskArchitectureTests(unittest.TestCase):
	def test_llm_executor_coordinates_prompt_policy_provider_and_adapter(self):
		from lib.llm.executor import LLMExecutor
		from lib.llm.prompt_bundle import PromptBundle

		class FakeProvider:
			def __init__(self):
				self.setting = {"temperature": 0}
				self.payload = None
				self.model_name = None

			def send(self, payload, model_name=None):
				self.payload = payload
				self.model_name = model_name
				return {"text": "模型輸出", "usage": {"prompt_tokens": 3, "completion_tokens": 2}}

		class FakeAdapter:
			model_name = "fake-model"

			def __init__(self):
				self.format_called = False
				self.parse_called = False
				self.extract_usage_called = False

			def format_request(self, prompt_bundle, setting):
				self.format_called = True
				return {
					"messages": prompt_bundle.messages,
					"system": prompt_bundle.system_template,
					"setting": setting,
				}

			def parse_response(self, response):
				self.parse_called = True
				return response["text"]

			def extract_usage(self, response):
				self.extract_usage_called = True
				return response["usage"]

			def get_total_usage(self, usage_history):
				return {"prompt_tokens": sum(x["prompt_tokens"] for x in usage_history)}

			def get_total_cost(self, usage_history):
				return Decimal("0.001")

		class FakePromptStrategy:
			def compose(self, input_text, response_text_history, text_policy):
				return PromptBundle(
					messages=[{"role": "user", "content": input_text}],
					system_template="系統提示",
				)

		class FakeTextPolicy:
			def has_target_language(self, text):
				return True

			def postprocess_output(self, text, input_text):
				return f"{text}:{input_text}"

			def normalize_response(self, sentence):
				return sentence

		executor = LLMExecutor(FakeProvider(), FakeAdapter())
		result = executor.execute(
			input_text="測試文字",
			prompt_strategy=FakePromptStrategy(),
			text_policy=FakeTextPolicy(),
			previous_results=["前次"],
		)

		self.assertEqual(result.original_text, "測試文字")
		self.assertEqual(result.output_text, "模型輸出:測試文字")
		self.assertEqual(result.usage, {"prompt_tokens": 3, "completion_tokens": 2})
		self.assertEqual(executor.get_total_usage(), {"prompt_tokens": 3})
		self.assertEqual(executor.get_total_cost(), Decimal("0.001"))

	def test_typo_workflow_uses_executor_and_returns_task_result(self):
		from lib.tasks.typo.result import TypoCorrectionResult
		from lib.tasks.typo.workflow import TypoCorrectionWorkflow

		class FakeExecutionResult:
			def __init__(self, output_text):
				self.output_text = output_text
				self.raw_response = {"raw": output_text}
				self.usage = {"prompt_tokens": 1, "completion_tokens": 1}

		class FakeExecutor:
			def __init__(self):
				self.ensure_connection_called = False
				self.calls = []

			def ensure_connection(self):
				self.ensure_connection_called = True

			def execute(self, input_text, prompt_strategy, text_policy, previous_results=None):
				self.calls.append(input_text)
				return FakeExecutionResult("天氣真好")

			def get_total_usage(self):
				return {"prompt_tokens": 1, "completion_tokens": 1}

			def get_total_cost(self):
				return Decimal("0.0001")

		workflow = TypoCorrectionWorkflow(
			executor=FakeExecutor(),
			prompt_strategy=object(),
			text_policy=object(),
			max_correction_attempts=0,
		)

		result = workflow.run("天器真好", batch_mode=False)

		self.assertIsInstance(result, TypoCorrectionResult)
		self.assertTrue(workflow.executor.ensure_connection_called)
		self.assertEqual(result.corrected_text, "天氣真好")
		self.assertEqual(result.usage_summary, {"prompt_tokens": 1, "completion_tokens": 1})
		self.assertEqual(result.cost, Decimal("0.0001"))

	def test_task_factory_and_runner_build_and_execute_typo_workflow(self):
		from lib.application import task_factory, task_runner
		from lib.tasks.typo.workflow import TypoCorrectionWorkflow

		class FakeWorkflow:
			def __init__(self):
				self.requests = []

			def run(self, request, batch_mode=True):
				self.requests.append((request, batch_mode))
				return {"corrected_text": "修正結果", "diff": []}

		fake_workflow = FakeWorkflow()

		original_create = task_factory.create_typo_workflow
		try:
			task_factory.create_typo_workflow = lambda **kwargs: fake_workflow

			result = task_runner.run_typo_correction(request="原始文字", batch_mode=False)

			self.assertEqual(result, {"corrected_text": "修正結果", "diff": []})
			self.assertEqual(fake_workflow.requests, [("原始文字", False)])
		finally:
			task_factory.create_typo_workflow = original_create

		self.assertTrue(TypoCorrectionWorkflow)

	def test_task_factory_supports_openai_response_provider_contract(self):
		from lib.application import task_factory
		from lib.tasks.typo.workflow import TypoCorrectionWorkflow

		captured = {}

		class FakeProvider:
			setting = {}

		class FakeAdapter:
			pass

		original_get_provider = task_factory.get_provider
		original_get_provider_model_adapter = task_factory.get_provider_model_adapter
		try:
			def fake_get_provider(provider_name, credential, retries=2, backoff=1):
				captured["provider_name"] = provider_name
				return FakeProvider()

			def fake_get_provider_model_adapter(provider_name, model_name):
				captured["adapter_provider_name"] = provider_name
				captured["model_name"] = model_name
				return FakeAdapter()

			task_factory.get_provider = fake_get_provider
			task_factory.get_provider_model_adapter = fake_get_provider_model_adapter

			workflow = task_factory.create_typo_workflow(
				provider_name="OpenAIResponse",
				model_name="gpt-4.1-2025-04-14",
				credential={"api_key": "test"},
				language="zh_traditional",
				template_name="Lite_v1.json",
				corrector_mode="lite",
				optional_guidance_enable={},
				customized_words=[],
			)
		finally:
			task_factory.get_provider = original_get_provider
			task_factory.get_provider_model_adapter = original_get_provider_model_adapter

		self.assertIsInstance(workflow, TypoCorrectionWorkflow)
		self.assertEqual(captured["provider_name"], "OpenAIResponse")
		self.assertEqual(captured["adapter_provider_name"], "OpenAIResponse")
		self.assertEqual(captured["model_name"], "gpt-4.1-2025-04-14")


if __name__ == "__main__":
	unittest.main()
