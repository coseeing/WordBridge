import sys
import math
import os
import re
from decimal import Decimal
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency in some environments
    load_dotenv = None

# 將 WordBridge 核心路徑加入 sys.path
# 結構：WordBridge/workspace/evals/provider.py
# 需要加入：WordBridge/addon/globalPlugins/WordBridge
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"

if load_dotenv is not None:
    load_dotenv(PROJECT_ROOT / ".env")


def _bootstrap_addon_env():
    sys.path.insert(0, str(ADDON_PATH))

    # 模擬環境需要的模組 (比照 tests/test_task_architecture_unittest.py)
    import types
    if "addonHandler" not in sys.modules:
        addon_handler = types.ModuleType("addonHandler")
        addon_handler.initTranslation = lambda: None
        sys.modules["addonHandler"] = addon_handler


_bootstrap_addon_env()

from lib.application.task_runner import run_typo_correction

DEFAULT_LANGUAGE = "zh_traditional"
DEFAULT_CORRECTOR_MODE = "standard"
DEFAULT_ESTIMATED_COST_INPUT_PER_MILLION = Decimal("0.14")
DEFAULT_ESTIMATED_COST_OUTPUT_PER_MILLION = Decimal("0.28")

PROVIDER_ENV_KEYS = {
    "OpenAI": "TEST_OPENAI_API_KEY",
    "Google": "TEST_GOOGLE_API_KEY",
    "Anthropic": "TEST_ANTHROPIC_API_KEY",
    "DeepSeek": "TEST_DEEPSEEK_API_KEY",
}


def _get_config(options):
    config = options.get("config", {})
    return {
        "provider_name": config["provider_name"],
        "model_name": config["model_name"],
        "language": config.get("language", DEFAULT_LANGUAGE),
        "template_name": config.get("template_name", "Standard_v3.json"),
        "corrector_mode": config.get("corrector_mode", DEFAULT_CORRECTOR_MODE),
        "optional_guidance_enable": config.get(
            "optional_guidance_enable",
            {
                "no_explanation": True,
                "keep_non_chinese_char": False,
            },
        ),
        "local": config.get("local"),
        "estimated_cost_input_per_million": str(
            config.get("estimated_cost_input_per_million", DEFAULT_ESTIMATED_COST_INPUT_PER_MILLION)
        ),
        "estimated_cost_output_per_million": str(
            config.get("estimated_cost_output_per_million", DEFAULT_ESTIMATED_COST_OUTPUT_PER_MILLION)
        ),
    }


def _get_credential(provider_name, is_local):
    if is_local:
        return {"api_key": "ollama"}

    env_key = PROVIDER_ENV_KEYS.get(provider_name)
    if env_key:
        api_key = os.getenv(env_key)
        if api_key:
            return {"api_key": api_key}

    return None


def _normalize_token_usage(usage_summary):
    prompt_tokens = (
        usage_summary.get("prompt_tokens")
        or usage_summary.get("input_tokens")
        or usage_summary.get("promptTokenCount")
        or usage_summary.get("prompt_cache_hit_tokens", 0) + usage_summary.get("prompt_cache_miss_tokens", 0)
    )
    completion_tokens = (
        usage_summary.get("completion_tokens")
        or usage_summary.get("output_tokens")
        or usage_summary.get("candidatesTokenCount")
        or 0
    )
    cached_tokens = (
        usage_summary.get("cached_tokens")
        or usage_summary.get("cache_read_input_tokens")
        or 0
    )
    total_tokens = usage_summary.get("total_tokens")
    if total_tokens is None:
        total_tokens = prompt_tokens + completion_tokens

    return {
        "total": total_tokens,
        "prompt": prompt_tokens,
        "completion": completion_tokens,
        "cached": cached_tokens,
    }


def _extract_text_fragments(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        fragments = []
        for item in value.values():
            fragments.extend(_extract_text_fragments(item))
        return fragments
    if isinstance(value, list):
        fragments = []
        for item in value:
            fragments.extend(_extract_text_fragments(item))
        return fragments
    return []


def _estimate_text_tokens(text):
    cjk_count = len(re.findall(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]", text))
    ascii_count = sum(1 for char in text if ord(char) < 128)
    other_count = max(len(text) - cjk_count - ascii_count, 0)
    return cjk_count + math.ceil(ascii_count / 4) + math.ceil(other_count / 2)


def _estimate_local_token_usage(raw_data):
    request_items = (raw_data or {}).get("requests", [])
    prompt_tokens = 0
    completion_tokens = 0

    for request_item in request_items:
        request_payload = request_item.get("request_payload", {})
        prompt_text = "".join(_extract_text_fragments(request_payload))
        prompt_tokens += _estimate_text_tokens(prompt_text)

        completion_text = request_item.get("output_text", "")
        completion_tokens += _estimate_text_tokens(completion_text)

    return {
        "total": prompt_tokens + completion_tokens,
        "prompt": prompt_tokens,
        "completion": completion_tokens,
        "cached": 0,
    }


def _estimate_local_cost(token_usage, config):
    input_rate = Decimal(str(config["estimated_cost_input_per_million"]))
    output_rate = Decimal(str(config["estimated_cost_output_per_million"]))
    return (
        Decimal(str(token_usage["prompt"])) * input_rate / Decimal("1000000")
        + Decimal(str(token_usage["completion"])) * output_rate / Decimal("1000000")
    )


def _format_result(result, config=None):
    config = config or {}
    usage_summary = result.usage_summary or {}
    metrics = (result.raw_data or {}).get("metrics", {})
    token_usage = _normalize_token_usage(usage_summary)
    cost = float(result.cost) if result.cost else 0
    metadata = result.raw_data or {}

    if config.get("local") and token_usage["total"] == 0:
        token_usage = _estimate_local_token_usage(metadata)
        estimated_cost = _estimate_local_cost(token_usage, config)
        cost = float(estimated_cost)
        metadata = {
            **metadata,
            "estimated_usage": token_usage,
            "estimated_cost": str(estimated_cost),
            "estimated_cost_source": "local_heuristic",
            "estimated_cost_rates": {
                "input_per_million": config["estimated_cost_input_per_million"],
                "output_per_million": config["estimated_cost_output_per_million"],
            },
        }

    return {
        "output": result.corrected_text,
        "tokenUsage": token_usage,
        "cost": cost,
        "latencyMs": metrics.get("total_latency_ms", 0),
        "metadata": metadata,
    }


def call_api(_prompt, options, context):
    """
    Promptfoo 呼叫 Python Provider 的進入點
    """
    input_text = context["vars"].get("input", "")
    config = _get_config(options)
    credential = _get_credential(config["provider_name"], config["local"])

    try:
        result = run_typo_correction(
            request=input_text,
            batch_mode=False,
            provider_name=config["provider_name"],
            model_name=config["model_name"],
            credential=credential,
            language=config["language"],
            template_name=config["template_name"],
            corrector_mode=config["corrector_mode"],
            optional_guidance_enable=config["optional_guidance_enable"],
            customized_words=[],
            retries=2,
            backoff=1,
        )
        return _format_result(result, config=config)
    except Exception as e:
        return {"error": str(e)}
