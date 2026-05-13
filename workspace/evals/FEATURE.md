# WordBridge 提示詞評估與成本監控架構 (WordBridge Eval Framework)

## 1. 目標 (Objectives)

* **精準度量化**：利用 $F_{0.5}$ 與標準化編輯距離 (NED) 取代肉眼觀察，確保糾錯精準度 。
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
│   ├── assertions.py                  # 自定義 F0.5 與 NED 計算腳本
│   └── promptfooconfig.yaml           # Promptfoo 總配置文件
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
import os
from wordbridge.main import WordBridgeCorrector # 假設的進入點

def call_api(prompt, options, context):
    # 初始化 WordBridge 並帶入 Prompt Template
    corrector = WordBridgeCorrector(template=prompt)

    # 執行糾錯並捕捉原始數據 (Raw Data)
    input_text = context['vars']['input']
    result = corrector.correct(input_text)

    # 回傳給 Promptfoo 做統計
    return {
        "output": result.text,
        "tokenUsage": {
            "total": result.usage.total_tokens,
            "prompt": result.usage.prompt_tokens,
            "completion": result.usage.completion_tokens,
            "cached": getattr(result.usage, 'cached_tokens', 0) # 捕捉快取命中
        }
    }
```

### 第三階段：準確度斷言實作 (`evals/assertions.py`)

定義維護者要求的「精確」指標。

* **$F_{0.5}$ Score**：對視障用戶而言，Precision（不改錯）比 Recall（抓到錯）重要兩倍 。
* **NED (Normalized Edit Distance)**：處理長度不一的句子評估 。

$$d_{norm}(s, t) = \frac{d_{Levenshtein}(s, t)}{\max(|s|, |t|)}$$

```python
# 核心計算邏輯
def get_assert(output, context):
    expected = context['vars']['expected']
    # 計算 NED 與 F0.5...
    # 若 NED < 0.1 且 F0.5 > 0.8 則 pass = True
    return {"pass": True, "score": f05_value, "reason": "Precision prioritized"}
```

### 第四階段：成本與快取追蹤 (Cost Tracker)

Promptfoo 會自動加總成本，但我們需在 `promptfooconfig.yaml` 中定義 2026 年的費率：

```yaml
# promptfooconfig.yaml
defaultTest:
  assert:
    - type: cost
      threshold: 0.002 # 單次請求不能超過 0.002 USD
    - type: latency
      threshold: 800  # 延遲需低於 800ms (確保 NVDA 朗讀不卡頓)

providers:
  - id: file://provider.py
    config:
      # 模擬 2026 旗艦與 Nano 模型價格
      cost_input: 0.0000025   # GPT-5.4 價格
      cost_cached: 0.00000025 # 快取命中價格 (10% cost)
```

## 4. 執行與觀測 (Execution)

```
pip install requests pypinyin chinese_converter hanzidentifier jiwer tqdm
```

1. **啟動測試**：執行 `npx promptfoo eval`。
2. **查看矩陣**：執行 `npx promptfoo view`。你可以並列看見：
  * `Prompt v1 (極簡型)`：成本 $0.0001, F_{0.5}: 0.72$。
  * `Prompt v2 (Few-shot)`：成本 $0.0008, F_{0.5}: 0.91$ (雖然貴，但更準確)。
1. **快取驗證**：第二次執行測試，檢查 `cached` tokens 是否增加，確認 Prompt Template 前綴是否穩定觸發供應商快取 。

## 5. 未來擴充 (Future Work)

* **LLM-as-a-Judge**：引入更強的模型（如 Claude 4.6）來判定 WordBridge 的修正是否保留了用戶的語氣 。
* **CI/CD Gate**：設定 GitHub Action，若 $F_{0.5}$ 低於 0.85 則不允許 Pull Request 合併 。
