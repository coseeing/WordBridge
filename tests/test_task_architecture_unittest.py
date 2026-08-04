import sys
import types
import unittest
import builtins
from decimal import Decimal
from importlib import util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"
PACKAGE_PATH = ADDON_PATH / "package"

sys.path.insert(0, str(ADDON_PATH))
sys.path.insert(0, str(PACKAGE_PATH))

addon_handler = types.ModuleType("addonHandler")
addon_handler.initTranslation = lambda: None
sys.modules.setdefault("addonHandler", addon_handler)

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
	def test_dialogs_builds_the_real_thirteen_endpoint_catalog_without_legacy_corrector_directory(self):
		"""Catches dialogs bootstrapping ConfigManager from the removed legacy directory."""
		with _nvda_module_stubs():
			dialogs = _load_module("WordBridge.dialogs", ADDON_PATH / "dialogs.py")

		self.assertEqual(len(dialogs.configManager.configs), 13)
		self.assertEqual(len(dialogs.configManager.config_by_id), 13)

	def test_plugin_local_correction_uses_endpoint_and_task_configs_with_unchanged_runner_interface(self):
		"""Catches prompt values being read from CorrectorConfig instead of task settings."""
		captured = {}
		with _nvda_module_stubs(captured) as nvda_stubs:
			nvda_stubs.track_corrector_task_loader()
			plugin = _load_module("WordBridge", ADDON_PATH / "__init__.py", package=True)
			self.assertEqual(
				nvda_stubs.corrector_task_loader_paths,
				[str(ADDON_PATH / "setting" / "task" / "corrector.json")],
			)
			expected_task_config = nvda_stubs.sentinel_task_config
			nvda_stubs.config.conf["WordBridge"]["settings"]["typo_correction_mode"] = "lite"
			instance = object.__new__(plugin.GlobalPlugin)
			instance.readDictionary = lambda: []
			instance.latest_action = {}

			plugin.GlobalPlugin.correctTypo(instance, "測試文字")

		self.assertEqual(
			nvda_stubs.corrector_task_loader_paths,
			[str(ADDON_PATH / "setting" / "task" / "corrector.json")],
		)
		self.assertEqual(
			captured,
			{
				"request": "測試文字",
				"batch_mode": True,
				"provider_name": "OpenAI",
				"model_name": "gpt-5.6-sol",
				"credential": {"api_key": "test-key"},
				"language": "zh_traditional",
				"template_name": expected_task_config.template_name["lite"],
				"corrector_mode": "lite",
				"optional_guidance_enable": expected_task_config.optional_guidance_enable,
				"customized_words": [],
				"retries": 2,
				"backoff": 1,
			},
		)

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

	def test_task_factory_passes_canonical_openai_provider_name(self):
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
				provider_name="OpenAI",
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
		self.assertEqual(captured["provider_name"], "OpenAI")
		self.assertEqual(captured["adapter_provider_name"], "OpenAI")
		self.assertEqual(captured["model_name"], "gpt-4.1-2025-04-14")


if __name__ == "__main__":
	unittest.main()


class _nvda_module_stubs:
	def __init__(self, captured_runner_args=None):
		self.captured_runner_args = captured_runner_args
		self.original_modules = {}

	def __enter__(self):
		self.original_modules = sys.modules.copy()
		self.original_sys_path = sys.path.copy()
		self.original_translation = getattr(builtins, "_", None)
		addon_handler_module = types.ModuleType("addonHandler")
		addon_handler_module.initTranslation = lambda: setattr(builtins, "_", lambda text: text)
		sys.modules["addonHandler"] = addon_handler_module

		package = types.ModuleType("WordBridge")
		package.__path__ = [str(ADDON_PATH)]
		sys.modules["WordBridge"] = package

		ctypes_module = types.ModuleType("ctypes")
		ctypes_module.windll = types.SimpleNamespace(
			kernel32=types.SimpleNamespace(GetUserDefaultUILanguage=lambda: 1033)
		)
		sys.modules["ctypes"] = ctypes_module

		config_module = types.ModuleType("config")
		config_module.conf = _FakeConf()
		self.config = config_module
		sys.modules["config"] = config_module
		configobj_module = types.ModuleType("configobj")
		configobj_validate = types.ModuleType("configobj.validate")
		configobj_validate.VdtValueTooBigError = type("VdtValueTooBigError", (Exception,), {})
		configobj_validate.VdtValueTooSmallError = type("VdtValueTooSmallError", (Exception,), {})
		sys.modules["configobj"] = configobj_module
		sys.modules["configobj.validate"] = configobj_validate

		wx_module = types.ModuleType("wx")
		wx_module.Choice = type("Choice", (), {})
		wx_module.TextCtrl = type("TextCtrl", (), {})
		wx_module.CheckBox = type("CheckBox", (), {})
		wx_module.Button = type("Button", (), {})
		wx_module.Dialog = type("Dialog", (), {})
		wx_module.ToolTip = lambda value: value
		wx_module.EVT_CHOICE = object()
		wx_module.EVT_BUTTON = object()
		wx_module.TE_PASSWORD = 1
		wx_module.TE_PROCESS_ENTER = 2
		wx_module.VERTICAL = 1
		wx_module.StaticBoxSizer = object
		wx_module.CallAfter = lambda callback, *args, **kwargs: callback(*args, **kwargs)
		sys.modules["wx"] = wx_module

		gui_module = types.ModuleType("gui")
		gui_module.guiHelper = types.SimpleNamespace(BoxSizerHelper=object)
		gui_module.nvdaControls = types.SimpleNamespace(SelectOnFocusSpinCtrl=object)
		gui_module.settingsDialogs = types.SimpleNamespace(
			NVDASettingsDialog=types.SimpleNamespace(categoryClasses=[])
		)
		gui_module.mainFrame = types.SimpleNamespace()
		sys.modules["gui"] = gui_module
		gui_context_help = types.ModuleType("gui.contextHelp")
		gui_context_help.ContextHelpMixin = type("ContextHelpMixin", (), {})
		sys.modules["gui.contextHelp"] = gui_context_help
		gui_settings_dialogs = types.ModuleType("gui.settingsDialogs")
		gui_settings_dialogs.SettingsPanel = object
		sys.modules["gui.settingsDialogs"] = gui_settings_dialogs

		global_plugin_handler = types.ModuleType("globalPluginHandler")
		global_plugin_handler.GlobalPlugin = object
		sys.modules["globalPluginHandler"] = global_plugin_handler
		sys.modules["api"] = types.SimpleNamespace(copyToClip=lambda text: None, getFocusObject=lambda: None)
		sys.modules["logHandler"] = types.SimpleNamespace(log=types.SimpleNamespace(warning=lambda message: None))
		sys.modules["nvwave"] = types.SimpleNamespace(playWaveFile=lambda *args, **kwargs: None)
		sys.modules["scriptHandler"] = types.SimpleNamespace(script=lambda **kwargs: lambda function: function)
		sys.modules["textInfos"] = types.SimpleNamespace(POSITION_SELECTION=object())
		sys.modules["tones"] = types.SimpleNamespace(beep=lambda *args: None)
		sys.modules["ui"] = types.SimpleNamespace(message=lambda message: None)
		sys.modules["hanzidentifier"] = types.SimpleNamespace(has_chinese=lambda text: True)

		dictionary_package = types.ModuleType("WordBridge.dictionary")
		dictionary_package.__path__ = []
		sys.modules["WordBridge.dictionary"] = dictionary_package
		sys.modules["WordBridge.dictionary.dialog"] = types.SimpleNamespace(DictionaryEntryDialog=object)
		sys.modules["WordBridge.lib.coseeing"] = types.SimpleNamespace(obtain_openai_key=lambda *args: "")
		sys.modules["WordBridge.lib.decimalUtils"] = types.SimpleNamespace(decimal_to_str_0=lambda cost: str(cost))
		sys.modules["WordBridge.lib.tasks.typo.utils"] = types.SimpleNamespace(strings_diff=lambda request, response: [])
		sys.modules["WordBridge.lib.viewHTML"] = types.SimpleNamespace(text2template=lambda src, dst: None)
		if self.captured_runner_args is not None:
			def run_typo_correction(
				*, request, batch_mode, provider_name, model_name, credential, language,
				template_name, corrector_mode, optional_guidance_enable,
				customized_words, retries, backoff,
			):
				self.captured_runner_args.update({
					"request": request,
					"batch_mode": batch_mode,
					"provider_name": provider_name,
					"model_name": model_name,
					"credential": credential,
					"language": language,
					"template_name": template_name,
					"corrector_mode": corrector_mode,
					"optional_guidance_enable": optional_guidance_enable,
					"customized_words": customized_words,
					"retries": retries,
					"backoff": backoff,
				})
				return types.SimpleNamespace(corrected_text=request, cost=Decimal("0"))
			sys.modules["WordBridge.lib.application.task_runner"] = types.SimpleNamespace(
				run_typo_correction=run_typo_correction,
			)
		return self

	def track_corrector_task_loader(self):
		config_manager = _load_module("WordBridge.configManager", ADDON_PATH / "configManager.py")
		real_loader = config_manager.load_corrector_task_config
		self.corrector_task_loader_paths = []

		def tracked_loader(path):
			self.corrector_task_loader_paths.append(str(path))
			real_task_config = real_loader(path)
			self.sentinel_task_config = type(real_task_config)(
				template_name={
					mode: f"sentinel-template:{template_name}"
					for mode, template_name in real_task_config.template_name.items()
				},
				optional_guidance_enable={
					key: f"sentinel-guidance:{key}:{value}"
					for key, value in real_task_config.optional_guidance_enable.items()
				},
			)
			return self.sentinel_task_config

		config_manager.load_corrector_task_config = tracked_loader

	def __exit__(self, exc_type, exc, traceback):
		for name in sorted(set(sys.modules) - set(self.original_modules)):
			sys.modules.pop(name, None)
		for name, module in self.original_modules.items():
			sys.modules[name] = module
		sys.path[:] = self.original_sys_path
		if self.original_translation is None:
			if hasattr(builtins, "_"):
				del builtins._
		else:
			builtins._ = self.original_translation


class _FakeConf(dict):
	def __init__(self):
		super().__init__({
			"WordBridge": {"settings": {
				"corrector_config_id": "gpt-5.6-sol&OpenAI",
				"execution_channel": "local",
				"language": "zh_traditional",
				"typo_correction_mode": "standard",
				"api_key": {"OpenAI": "test-key"},
				"customized_words_enable": False,
				"auto_display_report": False,
				"sound_effects_enable": False,
			}}})
		self.spec = {}


def _load_module(name, path, package=False):
	spec = util.spec_from_file_location(name, path, submodule_search_locations=[] if package else None)
	module = util.module_from_spec(spec)
	sys.modules[name] = module
	spec.loader.exec_module(module)
	return module
