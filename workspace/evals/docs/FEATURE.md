# WordBridge 提示詞評估與成本監控架構 (WordBridge Eval Framework)

## 1. 目標 (Objectives)

* **精準度量化**：利用 $F_2$ 與標準化編輯距離 (NED) 取代肉眼觀察，確保糾錯精準度 。
* **預算管控**：即時計算每次請求的 Token 成本，並監控「提示詞快取 (Prompt Caching)」的省錢效益 。
* **快速迭代**：建立自動化測試流水線，支援多版本 Prompt Template 與不同模型（如 GPT-5.4 Nano, Gemini 2.5 Flash）的並行測試 。

## 2. 目錄結構建議 (Project Structure)

建議在 WordBridge Repo 下 `workspace/evals/` 資料夾：

```
WordBridge/
├── addon/globalPlugins/WordBridge     # 核心糾錯邏輯 (Python)
├── evals/
│   ├── datasets/                      # 存放測試案例 (CSV/JSON)
│   ├── prompts/                       # 不同版本的 Prompt 模板 (.txt)
│   ├── provider.py                    # Promptfoo 與 WordBridge 的橋接腳本
│   ├── assertions.py                  # 自定義 F2 與 NED 計算腳本
│   └── promptfooconfig/               # 依 provider、model 與錯字數分類的設定檔
```

## 3. 實作階段 (Phases)

### 第一階段：測試資料集整理 (Datasets)

為了模擬 NVDA 用戶的真實場景，資料集需包含兩部分：

1. **基準數據**：採用 **SIGHAN15** 或 **CSCD-NS** (Weibo 數據集)，後者包含大量母語人士的輸入錯誤 。
2. **合成噪音 (Noise Generator)**：撰寫 Python 腳本生成以下錯誤：
* **同音誤選**：將常用詞替換為 Pinyin 相同但意義錯誤的字 。
* **物理誤觸**：模擬 QWERTY 鍵盤鄰近按鍵的替換（如 `p` -> `o`） 。

### 第二階段：Provider 橋接實作 (`evals/provider.py`)

這是在 Node.js 環境（Promptfoo）中執行 Python（WordBridge）的入口。

```python
def call_api(prompt, options, context):
    input_text = context["vars"].get("input", "")
    workflow = _create_workflow(...)
    result = workflow.run(input_text, batch_mode=False)

    return {
        "output": result.corrected_text,
        "tokenUsage": {
            "total":  result.raw_data["usage_summary"].get("total_tokens", 0),
            "prompt": result.raw_data["usage_summary"].get("prompt_tokens", 0),
            "completion": result.raw_data["usage_summary"].get("completion_tokens", 0),
            "cached": result.raw_data["usage_summary"].get("cached_tokens", 0),  # 只保留供應商明確回傳值
        },
        "cost": float(result.cost),
        "latencyMs": result.raw_data["metrics"]["total_latency_ms"],
        "metadata": result.raw_data,
    }
```

### 第三階段：準確度斷言實作 (`evals/assertions.py`)

定義維護者要求的「精確」指標。

* **$F_2$ Score**：因漏改可能不會被使用者發現，而錯改會被工具標示並進入確認流程，因此 Recall（抓到錯）權重高於 Precision（不改錯）。
* **NED (Normalized Edit Distance)**：處理長度不一的句子評估 。

$$d_{norm}(s, t) = \frac{d_{Levenshtein}(s, t)}{\max(|s|, |t|)}$$

```python
# 核心計算邏輯
def get_assert(output, context):
    expected = context['vars']['expected']
    # 計算 NED 與 F2...
    # 若 NED < 0.1 且 F2 > 0.8 則 pass = True
    return {"pass": True, "score": f2_value, "reason": "Recall prioritized"}
```

### 第四階段：成本與快取追蹤 (Cost Tracker)

成本計算目前在 WordBridge Python 端完成，而不是在 Promptfoo 端手寫費率。實際流程如下：

1. `addon/globalPlugins/WordBridge/setting/price.json` 定義各模型費率。
2. `lib/llm/cost_calculator.py` 根據 usage 欄位計算單次與總成本。
3. `lib/llm/executor.py` 保留每次 request 的原始 usage、延遲與 request cost。
4. `lib/tasks/typo/workflow.py` 彙整成 `TypoCorrectionResult.raw_data`。
5. `workspace/evals/provider.py` 再把 `cost`、`latencyMs`、`tokenUsage`、`metadata` 回傳給 Promptfoo。

`metadata` 目前至少包含：

```json
{
  "metrics": {
    "request_count": 2,
    "total_latency_ms": 742.8,
    "llm_latency_ms": 601.4
  },
  "usage_summary": {
    "prompt_tokens": 120,
    "completion_tokens": 34
  },
  "cost": "0.00123",
  "requests": [
    {
      "request_payload": {},
      "raw_response": {},
      "raw_usage": {},
      "usage": {},
      "latency_ms": 301.2,
      "request_cost": "0.00061"
    }
  ]
}
```

Promptfoo 這邊主要負責設定門檻與觀測：

```yaml
# promptfooconfig/Ollama_qwen2_full_error.yaml
defaultTest:
  assert:
    - type: cost
      threshold: 0.002 # 單次請求不能超過 0.002 USD
    - type: latency
      threshold: 800  # 整體 workflow 延遲需低於 800ms
```

補充：

* `tokenUsage` 已在 `provider.py` 做 provider-agnostic normalization，可兼容 OpenAI、Anthropic、Google、DeepSeek 等不同 usage 欄位。
* `cached` tokens 只在供應商明確回傳快取欄位時才保留，不做推算或折算。
* 本地 `Ollama` / fallback provider 若沒有明確 usage / cost，`provider.py` 會用 request/response 文字長度做近似 token 與成本估算，並在 `metadata.estimated_*` 欄位標示來源。

## 4. 執行與觀測 (Execution)

```
pip install requests pypinyin chinese_converter hanzidentifier jiwer tqdm
```

1. **啟動測試**：執行 `npx promptfoo eval -c workspace/evals/promptfooconfig/Ollama_qwen2_full_error.yaml`。
2. **查看矩陣**：執行 `npx promptfoo view`，觀察 `F_2`、`NED`、`cost`、`latencyMs`。
3. **檢查 Raw Data**：展開 provider 回傳內容，確認 `metadata.metrics`、`metadata.usage_summary`、`metadata.requests[*]` 都有值。本地模式若是估算成本，還應看到 `metadata.estimated_usage`、`metadata.estimated_cost`、`metadata.estimated_cost_source`。
4. **快取驗證**：第二次執行相同測試，只有在供應商明確回傳快取欄位時，才檢查 `tokenUsage.cached` 或 `metadata.usage_summary` 中的快取數值。

## 5. 未來擴充 (Future Work)

* **LLM-as-a-Judge**：引入更強的模型（如 Claude 4.6）來判定 WordBridge 的修正是否保留了用戶的語氣 。
* **CI/CD Gate**：設定 GitHub Action，若 $F_2$ 低於 0.85 則不允許 Pull Request 合併 。
