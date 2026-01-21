import sys
import os
from pathlib import Path
from dotenv import load_dotenv
import pytest

load_dotenv()

project_root = Path(__file__).parent.parent
addon_path = project_root / "addon" / "globalPlugins" / "WordBridge"
package_path = addon_path / "package"

sys.path.insert(0, str(addon_path))
sys.path.insert(0, str(package_path))

@pytest.fixture
def gemini_credentials():
	api_key = os.getenv("TEST_GOOGLE_API_KEY")
	if not api_key:
		pytest.skip("TEST_GOOGLE_API_KEY not found in environment")
	
	return {
		"api_key": api_key,
		"secret_key": ""
	}

@pytest.fixture
def gemini_config():
	return {
		"model_name": "gemini-2.5-flash",
		"provider": "google",
		"language": "zh_traditional",
		"template_name": "Standard_v1.json",
		"optional_guidance_enable": {
			"keep_non_chinese_char": True,
			"no_explanation": False
		}
	}
