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

	response_payload = {"unexpected": True}

	class _Adapter:
		model_name = "fake-model"

		def format_request(self, prompt_bundle, setting):
			return {}

		def parse_response(self, response_json):
			raise KeyError("choices")

	class _Provider:
		setting = {}

		def send(self, payload, model_name):
			return response_payload

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

	# This is the "marker" pattern: a distinctive translation function makes it
	# observable both that the message went through _() at all, and -- by
	# asserting the fully rendered string rather than just a prefix -- that
	# the interpolated response value actually survived the .format() call.
	# A source-level check alone (see test_executor_parse_error_message_is_extractable)
	# cannot tell a real .format(response=response_json) from a dropped one
	# that ships a raw "{response}" placeholder to the user.
	assert str(excinfo.value) == (
		f"<<Parsing error. Unexpected server response. Response: {response_payload}>>"
	)


def test_executor_parse_error_message_is_extractable():
	source = (ADDON_PATH / "lib" / "llm" / "executor.py").read_text(encoding="utf8")

	assert '_("Parsing error. Unexpected server response. Response: {response}")' in source
	assert '_(f"' not in source


@pytest.mark.parametrize(
	"module_path",
	["lib.llm.provider", "configManager", "lib.llm.executor"],
)
def test_fallback_engages_when_no_translation_is_available(module_path):
	code = textwrap.dedent(
		f"""
		import importlib
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

		module = importlib.import_module({module_path!r})

		assert "_" in vars(module), "no builtin _ was available, so the fallback should exist"
		assert module._("raw") == "raw"
		"""
	)
	result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

	assert result.returncode == 0, result.stderr
