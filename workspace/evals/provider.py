import os
import sys
import json
from pathlib import Path

# 將 WordBridge 核心路徑加入 sys.path
# 結構：WordBridge/workspace/evals/provider.py
# 需要加入：WordBridge/addon/globalPlugins/WordBridge
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"

sys.path.insert(0, str(ADDON_PATH))

# 模擬環境需要的模組 (比照 tests/test_task_architecture_unittest.py)
import types
if "addonHandler" not in sys.modules:
    addon_handler = types.ModuleType("addonHandler")
    addon_handler.initTranslation = lambda: None
    sys.modules["addonHandler"] = addon_handler

from lib.application import task_factory

def call_api(prompt, options, context):
    """
    Promptfoo 呼叫 Python Provider 的進入點
    """
    input_text = context['vars'].get('input', '')
    config = options.get('config', {})
    provider_name = config.get('provider', 'DeepSeek') # 預設改用 DeepSeek 以獲得標準 payload
    model_name = config.get('model', 'qwen2')
    language = config.get('language', 'zh_traditional')
    corrector_mode = config.get('corrector_mode', 'standard')

    credential = None
    if config.get('local'):
        # 如果是本地 Ollama，我們模擬一個 DeepSeek 格式的 credential
        credential = {"api_key": "ollama"}
        # 使用 DeepSeek Provider 因為它的 Adapter 會產出標準的 messages 格式，Ollama 才能讀懂
        provider_name = "DeepSeek"
    else:
        config_path = PROJECT_ROOT / "workspace" / "eval_legacy" / "config.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf8") as f:
                creds = json.load(f)
                credential = creds.get(provider_name)

    try:
        # 處理 template_name，確保有 .json 延展名
        template_name = prompt.strip()
        if not template_name.endswith(".json"):
            template_name += ".json"

        workflow = task_factory.create_typo_workflow(
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
            max_correction_attempts=3
        )
        
        # 關鍵：如果是本地 Ollama，覆蓋 executor 中的 provider url
        if config.get('local'):
            # Ollama 的 OpenAI 兼容路徑
            workflow.executor.provider_object.url = "http://localhost:11434/v1/chat/completions"

        result = workflow.run(input_text, batch_mode=False)

        return {
            "output": result.corrected_text,
            "tokenUsage": {
                "total": result.usage_summary.get("total_tokens", 0),
                "prompt": result.usage_summary.get("prompt_tokens", 0),
                "completion": result.usage_summary.get("completion_tokens", 0),
            },
            "cost": float(result.cost) if result.cost else 0
        }
    except Exception as e:
        return {"error": str(e)}
