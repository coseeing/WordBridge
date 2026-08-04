import json
import sys
import types
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"
PACKAGE_PATH = ADDON_PATH / "package"
CORRECTOR_TASK_CONFIG_PATH = ADDON_PATH / "setting" / "task" / "corrector.json"

sys.path.insert(0, str(ADDON_PATH))
sys.path.insert(0, str(PACKAGE_PATH))

addon_handler = types.ModuleType("addonHandler")
addon_handler.initTranslation = lambda: None
sys.modules.setdefault("addonHandler", addon_handler)


def test_load_corrector_task_config_returns_bundled_prompt_settings():
	from configManager import CorrectorTaskConfig, load_corrector_task_config

	config = load_corrector_task_config(CORRECTOR_TASK_CONFIG_PATH)

	assert isinstance(config, CorrectorTaskConfig)
	assert config.template_name == {
		"standard": "Standard_v1.json",
		"lite": "Lite_v1.json",
	}
	assert config.optional_guidance_enable == {
		"keep_non_chinese_char": True,
		"no_explanation": True,
	}


def test_load_corrector_task_config_rejects_missing_required_key(tmp_path):
	from configManager import load_corrector_task_config

	path = tmp_path / "corrector.json"
	path.write_text(json.dumps({"template_name": {}}), encoding="utf-8")

	with pytest.raises(KeyError, match="optional_guidance_enable"):
		load_corrector_task_config(path)


def test_load_corrector_task_config_rejects_malformed_json(tmp_path):
	from configManager import load_corrector_task_config

	path = tmp_path / "corrector.json"
	path.write_text("{", encoding="utf-8")

	with pytest.raises(json.JSONDecodeError):
		load_corrector_task_config(path)
