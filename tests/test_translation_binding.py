import builtins
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"


@pytest.mark.parametrize(
	"module_path",
	["lib.llm.provider", "configManager", "lib.llm.executor"],
)
def test_module_does_not_shadow_the_translation_builtin(module_path):
	import importlib

	module = importlib.import_module(module_path)

	assert "_" not in vars(module), (
		f"{module_path} defines a module-level _, which shadows the builtin "
		"that addonHandler.initTranslation() installs"
	)


def test_executor_messages_go_through_the_installed_translation(monkeypatch):
	from lib.llm import executor

	monkeypatch.setattr(builtins, "_", lambda text: f"<<{text}>>")

	class _Adapter:
		model_name = "fake-model"

		def format_request(self, prompt_bundle, setting):
			return {}

		def parse_response(self, response_json):
			raise KeyError("choices")

	class _Provider:
		setting = {}

		def send(self, payload, model_name):
			return {"unexpected": True}

	class _Policy:
		def has_target_language(self, text):
			return True

		def normalize_response(self, sentence):
			return sentence

		def postprocess_output(self, response_text, input_text):
			return response_text

	class _Strategy:
		def compose(self, input_text, response_text_history, text_policy):
			return {}

	llm_executor = executor.LLMExecutor(_Provider(), _Adapter())

	with pytest.raises(Exception) as excinfo:
		llm_executor.execute(
			input_text="測試",
			prompt_strategy=_Strategy(),
			text_policy=_Policy(),
		)

	assert str(excinfo.value).startswith("<<")


def test_executor_parse_error_message_is_extractable():
	source = (ADDON_PATH / "lib" / "llm" / "executor.py").read_text(encoding="utf8")

	assert '_("Parsing error. Unexpected server response. Response: {response}")' in source
	assert '_(f"' not in source


def test_fallback_engages_when_no_translation_is_available():
	code = textwrap.dedent(
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

		from lib.llm import provider

		assert "_" in vars(provider), "no builtin _ was available, so the fallback should exist"
		assert provider._("raw") == "raw"
		"""
	)
	result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

	assert result.returncode == 0, result.stderr
