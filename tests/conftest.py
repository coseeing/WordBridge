import builtins
import sys
import os
import types
from pathlib import Path
from dotenv import load_dotenv
import pytest

load_dotenv()

project_root = Path(__file__).parent.parent
tests_path = Path(__file__).parent
addon_path = project_root / "addon" / "globalPlugins" / "WordBridge"
package_path = addon_path / "package"

sys.path.insert(0, str(tests_path))
sys.path.insert(0, str(addon_path))

# Tests import add-on modules directly, bypassing the plugin entry point, so
# they must stand the sandbox up themselves.  package/ deliberately does NOT
# go on sys.path -- that is the behaviour under test.
from lib import vendor

vendor.install(vendor.default_roots(package_path))
vendor.install_stdlib_gapfill(package_path)

def _install_translation():
	# NVDA's initTranslation() installs _ into builtins. A no-op stub leaves
	# _ undefined everywhere, which makes it impossible to tell a correctly
	# bound message from one that would raise NameError in production.
	# Identity keeps every existing assertion about message text valid.
	if not hasattr(builtins, "_"):
		builtins._ = lambda text: text


# NVDA's addonHandler does not exist on this host. lib/coseeing_auth.py imports
# it unconditionally at module scope, so any test file that imports that
# module -- directly or transitively -- needs a stand-in. setdefault() makes
# this idempotent: whichever test module (or file collection order) reaches
# here first wins, and later imports of lib.coseeing_auth see a module already
# satisfied, so this file no longer depends on cross-file collection order to
# pass standalone.
_addon_handler_stub = types.ModuleType("addonHandler")
_addon_handler_stub.initTranslation = _install_translation
sys.modules.setdefault("addonHandler", _addon_handler_stub)
_install_translation()

@pytest.fixture
def model_config():
	def _make_config(model_name, provider):
		return {
			"name": model_name,
			"provider": provider,
			"language": "zh_traditional",
			"template_name": "Standard_v1.json",
			"optional_guidance_enable": {
				"keep_non_chinese_char": True,
				"no_explanation": False
			}
		}
	return _make_config

@pytest.fixture
def credentials():
	def _get_credentials(provider):
		if provider == "Google":
			api_key = os.getenv("TEST_GOOGLE_API_KEY")
			if not api_key:
				pytest.skip("TEST_GOOGLE_API_KEY not found in environment")
		elif provider == "OpenAI":
			api_key = os.getenv("TEST_OPENAI_API_KEY")
			if not api_key:
				pytest.skip("TEST_OPENAI_API_KEY not found in environment")
		elif provider == "Anthropic":
			api_key = os.getenv("TEST_ANTHROPIC_API_KEY")
			if not api_key:
				pytest.skip("TEST_ANTHROPIC_API_KEY not found in environment")
		elif provider == "DeepSeek":
			api_key = os.getenv("TEST_DEEPSEEK_API_KEY")
			if not api_key:
				pytest.skip("TEST_DEEPSEEK_API_KEY not found in environment")
		else:
			pytest.skip(f"Unknown provider: {provider}")

		return {
			"api_key": api_key,
		}
	return _get_credentials

@pytest.fixture
def test_data():
	return {
		"basic_text": "這是測試文字",
		"text_with_typo": "今天天器真好",
		"expected_correction": "今天天氣真好"
	}
