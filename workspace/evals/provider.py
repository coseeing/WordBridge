import sys
import json
from pathlib import Path

# 將 WordBridge 核心路徑加入 sys.path
# 結構：WordBridge/workspace/evals/provider.py
# 需要加入：WordBridge/addon/globalPlugins/WordBridge
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"


def _bootstrap_addon_env():
    sys.path.insert(0, str(ADDON_PATH))

    # 模擬環境需要的模組 (比照 tests/test_task_architecture_unittest.py)
    import types
    if "addonHandler" not in sys.modules:
        addon_handler = types.ModuleType("addonHandler")
        addon_handler.initTranslation = lambda: None
        sys.modules["addonHandler"] = addon_handler


_bootstrap_addon_env()

from lib.application import task_factory

DEFAULT_PROVIDER = "Ollama"
DEFAULT_MODEL = "qwen2"
DEFAULT_LANGUAGE = "zh_traditional"
DEFAULT_CORRECTOR_MODE = "standard"


def _get_config(options):
    config = options.get("config", {})
    return {
        "provider": config.get("provider", DEFAULT_PROVIDER),
        "model": config.get("model", DEFAULT_MODEL),
        "language": config.get("language", DEFAULT_LANGUAGE),
        "corrector_mode": config.get("corrector_mode", DEFAULT_CORRECTOR_MODE),
        "local": config.get("local"),
    }


def _get_credential(provider_name, is_local):
    if is_local:
        return {"api_key": "ollama"}

    config_path = PROJECT_ROOT / "workspace" / "eval_legacy" / "config.json"
    if not config_path.exists():
        return None

    with open(config_path, "r", encoding="utf8") as f:
        creds = json.load(f)
        return creds.get(provider_name)


def _resolve_provider_name(provider_name, is_local):
    if not is_local:
        return provider_name

    if provider_name.strip().lower() == "ollama":
        return "DeepSeek"

    return provider_name


def _normalize_template_name(prompt):
    template_name = prompt.strip()
    if not template_name.endswith(".json"):
        template_name += ".json"
    return template_name


def _create_workflow(
    provider_name,
    model_name,
    credential,
    language,
    template_name,
    corrector_mode,
):
    return task_factory.create_typo_workflow(
        provider_name=provider_name,
        model_name=model_name,
        credential=credential,
        language=language,
        template_name=template_name,
        corrector_mode=corrector_mode,
        optional_guidance_enable={
            "no_explanation": True,
            "keep_non_chinese_char": False,
        },
        max_correction_attempts=3,
    )


def _set_local_ollama_url(workflow, is_local):
    if is_local:
        workflow.executor.provider_object.url = "http://localhost:11434/v1/chat/completions"


def _format_result(result):
    return {
        "output": result.corrected_text,
        "tokenUsage": {
            "total": result.usage_summary.get("total_tokens", 0),
            "prompt": result.usage_summary.get("prompt_tokens", 0),
            "completion": result.usage_summary.get("completion_tokens", 0),
        },
        "cost": float(result.cost) if result.cost else 0,
    }


def call_api(prompt, options, context):
    """
    Promptfoo 呼叫 Python Provider 的進入點
    """
    input_text = context["vars"].get("input", "")
    config = _get_config(options)
    provider_name = _resolve_provider_name(config["provider"], config["local"])
    credential = _get_credential(provider_name, config["local"])

    try:
        template_name = _normalize_template_name(prompt)
        workflow = _create_workflow(
            provider_name=provider_name,
            model_name=config["model"],
            credential=credential,
            language=config["language"],
            template_name=template_name,
            corrector_mode=config["corrector_mode"],
        )
        _set_local_ollama_url(workflow, config["local"])

        result = workflow.run(input_text, batch_mode=False)
        return _format_result(result)
    except Exception as e:
        return {"error": str(e)}
