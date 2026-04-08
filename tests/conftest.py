import sys
import os
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
sys.path.insert(0, str(package_path))

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
		else:
			pytest.skip(f"Unknown provider: {provider}")

		return {
			"api_key": api_key,
			"secret_key": ""
		}
	return _get_credentials

@pytest.fixture
def test_data():
	return {
		"basic_text": "這是測試文字",
		"text_with_typo": "今天天器真好",
		"expected_correction": "今天天氣真好"
	}
