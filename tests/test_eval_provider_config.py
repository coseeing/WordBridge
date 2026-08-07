import importlib.util
from pathlib import Path
import sys

import pytest

ADDON_PATH = Path(__file__).parents[1] / "addon" / "globalPlugins" / "WordBridge"
sys.path.insert(0, str(ADDON_PATH))
from lib.llm.adapter import get_provider_model_adapter
from lib.llm.provider import get_provider


PROVIDER_PATH = Path(__file__).parents[1] / "workspace" / "evals" / "provider.py"
spec = importlib.util.spec_from_file_location("wordbridge_eval_provider", PROVIDER_PATH)
provider_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider_module)


def test_get_config_reads_explicit_wordbridge_settings():
    config = provider_module._get_config(
        {
            "config": {
                "provider_name": "OpenAI",
                "model_name": "gpt-5.6-luna",
                "language": "zh_traditional",
                "template_name": "Standard_v3.json",
                "corrector_mode": "standard",
                "optional_guidance_enable": {
                    "no_explanation": True,
                    "keep_non_chinese_char": False,
                },
            }
        }
    )

    assert config["provider_name"] == "OpenAI"
    assert config["model_name"] == "gpt-5.6-luna"
    assert config["language"] == "zh_traditional"
    assert config["template_name"] == "Standard_v3.json"
    assert config["corrector_mode"] == "standard"
    assert config["optional_guidance_enable"] == {
        "no_explanation": True,
        "keep_non_chinese_char": False,
    }


@pytest.mark.parametrize("missing_key", ["provider_name", "model_name"])
def test_get_config_requires_provider_and_model(missing_key):
    config = {
        "provider_name": "OpenAI",
        "model_name": "gpt-5.6-luna",
    }
    del config[missing_key]

    with pytest.raises(KeyError, match=missing_key):
        provider_module._get_config({"config": config})


def test_call_api_forwards_provider_config_to_application_runner(monkeypatch):
    captured = {}

    def fake_run_typo_correction(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setenv("TEST_OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(provider_module, "run_typo_correction", fake_run_typo_correction)
    monkeypatch.setattr(provider_module, "_format_result", lambda result, config: result)

    result = provider_module.call_api(
        "WordBridge",
        {
            "config": {
                "provider_name": "OpenAI",
                "model_name": "gpt-5.6-luna",
                "language": "zh_traditional",
                "template_name": "Standard_v3.json",
                "corrector_mode": "standard",
                "optional_guidance_enable": {
                    "no_explanation": True,
                    "keep_non_chinese_char": False,
                },
            }
        },
        {"vars": {"input": "測試文字"}},
    )

    assert result is not None
    assert captured == {
        "request": "測試文字",
        "batch_mode": False,
        "provider_name": "OpenAI",
        "model_name": "gpt-5.6-luna",
        "credential": {"api_key": "test-key"},
        "language": "zh_traditional",
        "template_name": "Standard_v3.json",
        "corrector_mode": "standard",
        "optional_guidance_enable": {
            "no_explanation": True,
            "keep_non_chinese_char": False,
        },
        "customized_words": [],
        "retries": 2,
        "backoff": 1,
    }


def test_ollama_provider_uses_its_provider_setting_file():
    provider = get_provider("Ollama", {"api_key": "ollama"})
    adapter = get_provider_model_adapter("Ollama", "qwen2")

    assert provider.url == "http://localhost:11434/v1/chat/completions"
    assert adapter.model_name == "qwen2"
