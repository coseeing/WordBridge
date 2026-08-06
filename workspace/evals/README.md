# WordBridge 評估工具

這個目錄使用 [Promptfoo](https://www.promptfoo.dev/) 呼叫 WordBridge 的 Python workflow，評估中文錯字修正的準確度、延遲與成本。評估可使用本機 Ollama，或透過 OpenAI API 執行。

以下指令都假設目前位於 repository 根目錄。

## 環境需求

- Python 3.11（專案目前使用 3.11.10）
- Node.js 20 以上
- npm / npx
- 本機評估另需安裝 [Ollama](https://ollama.com/)
- OpenAI 評估需有可使用目標模型的 API key，並會產生實際 API 費用

## 建立環境

### Mac

建立並啟用 Python virtual environment：

```bash
python3.11 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r workspace/evals/requirements.txt python-dotenv
```

### Windows

在 PowerShell 中，啟用環境的指令是：

```powershell
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r workspace/evals/requirements.txt python-dotenv
```

本專案目前以 Promptfoo 0.120.19 驗證。第一次使用時可先確認 CLI 能正常執行：

```bash
npx promptfoo@0.120.19 --version
```

### 使用本機 Ollama

安裝 Ollama 後下載 config 預設使用的模型，並確認服務已啟動：

```bash
ollama pull qwen2
ollama serve
```

若 Ollama 已由桌面程式或系統服務啟動，不需要再次執行 `ollama serve`。Provider 預設連線至 `http://localhost:11434/v1/chat/completions`。

`Ollama_qwen2_full_error.yaml` 明確指定 `venv/bin/python`。在 Windows 上執行本機評估時，請將其中的 `pythonExecutable` 改為 `venv\\Scripts\\python.exe`；其他 config 會使用目前已啟用 virtual environment 的 Python。

### 使用 OpenAI API

在 repository 根目錄建立或更新 `.env`：

```dotenv
TEST_OPENAI_API_KEY=your_api_key_here
```

`.env` 已被 Git 忽略，請勿將真實 API key 寫進 config 或提交到版本庫。`provider.py` 也支援下列名稱：

- `TEST_ANTHROPIC_API_KEY`
- `TEST_GOOGLE_API_KEY`
- `TEST_DEEPSEEK_API_KEY`

## 資料與封存

新版評估流程使用的原始語料已放在 `workspace/evals/datasets/gpt4_250_sentence_gt.txt`。API credential 只從 `.env` 或系統環境變數讀取；原本的 `workspace/archive/eval/` 保留作為歷史封存，不再是新版流程的必要路徑。

產生 Zhuyin 評估資料集：

```bash
python workspace/evals/generate_zhuyin_dataset.py
```

## 執行評估

先啟用 virtual environment，再從 repository 根目錄執行。建議先跑小型 smoke test：

```bash
npx promptfoo@0.120.19 eval \
  -c workspace/evals/promptfooconfig/OpenAI_gpt-5.6-luna_smoke.yaml \
  -j 1
```

OpenAI 完整評估包含三份資料集，目前共 743 筆案例（單錯 249、雙錯 247、三錯 247）：

```bash
npx promptfoo@0.120.19 eval \
  -c workspace/evals/promptfooconfig/OpenAI_gpt-5.6-luna_full_error.yaml \
  -j 1
```

本機 Ollama 評估：

```bash
npx promptfoo@0.120.19 eval \
  -c workspace/evals/promptfooconfig/Ollama_qwen2_full_error.yaml \
  -j 1
```

只評估特定錯誤數量時，可改用：

```bash
npx promptfoo@0.120.19 eval -c workspace/evals/promptfooconfig/Ollama_qwen2_1_error.yaml -j 1
npx promptfoo@0.120.19 eval -c workspace/evals/promptfooconfig/Ollama_qwen2_2_error.yaml -j 1
npx promptfoo@0.120.19 eval -c workspace/evals/promptfooconfig/Ollama_qwen2_3_error.yaml -j 1
```

各 config 的用途如下：

| Config | Provider | 資料範圍 |
| --- | --- | --- |
| `Ollama_qwen2_1_error.yaml` | 本機 Ollama / qwen2 | 單錯資料集 |
| `Ollama_qwen2_2_error.yaml` | 本機 Ollama / qwen2 | 雙錯資料集 |
| `Ollama_qwen2_3_error.yaml` | 本機 Ollama / qwen2 | 三錯資料集 |
| `Ollama_qwen2_full_error.yaml` | 本機 Ollama / qwen2 | 單錯、雙錯、三錯 |
| `OpenAI_gpt-5.6-luna_1_error.yaml` | OpenAI / gpt-5.6-luna | 單錯資料集 |
| `OpenAI_gpt-5.6-luna_2_error.yaml` | OpenAI / gpt-5.6-luna | 雙錯資料集 |
| `OpenAI_gpt-5.6-luna_3_error.yaml` | OpenAI / gpt-5.6-luna | 三錯資料集 |
| `OpenAI_gpt-5.6-luna_full_error.yaml` | OpenAI / gpt-5.6-luna | 單錯、雙錯、三錯 |
| `Anthropic_claude-sonnet-5_1_error.yaml` | Anthropic / claude-sonnet-5 | 單錯資料集 |
| `Anthropic_claude-sonnet-5_2_error.yaml` | Anthropic / claude-sonnet-5 | 雙錯資料集 |
| `Anthropic_claude-sonnet-5_3_error.yaml` | Anthropic / claude-sonnet-5 | 三錯資料集 |
| `Anthropic_claude-sonnet-5_full_error.yaml` | Anthropic / claude-sonnet-5 | 單錯、雙錯、三錯 |

若只想先驗證一筆資料流，可在任一指令後加上 `--filter-first-n 1`。若要重新發出所有模型請求並重新量測成本與延遲，請加上 `--no-cache`。

## 查看與匯出結果

在瀏覽器查看最近一次評估：

```bash
npx promptfoo@0.120.19 view
```

也可以在 eval 指令加入 `-o` 匯出 JSON：

```bash
npx promptfoo@0.120.19 eval \
  -c workspace/evals/promptfooconfig/OpenAI_gpt-5.6-luna_smoke.yaml \
  -j 1 \
  -o workspace/evals/report.json
```

主要指標：

- `case_f2`：以 recall 為較高權重的單筆修正分數。
- `case_ned`：模型輸出與預期答案的標準化編輯距離，越低越好。
- `overall_precision`、`overall_recall`、`overall_f2`：整批資料彙總指標。
- `cost`：WordBridge 依 `addon/globalPlugins/WordBridge/setting/price.json` 與模型回傳的 token usage 計算。
- `latency`：整個 WordBridge workflow 的耗時。

每筆案例的通過門檻定義在對應 config 的 `defaultTest.assert`。詳細計分邏輯位於 `assertions.py`，Provider 與 WordBridge 的橋接邏輯位於 `provider.py`。

## 常見問題

### 找不到 Python 套件

確認已啟用 `venv`，並以 `python -m pip install ...` 安裝依賴。若 Promptfoo 仍使用到其他 Python，請檢查 config 的 `pythonExecutable`。

### OpenAI 評估回報缺少 credential

確認 `.env` 位於 repository 根目錄、變數名稱為 `TEST_OPENAI_API_KEY`，且已安裝 `python-dotenv`。也可以先在目前 shell 中設定同名環境變數。

### Ollama 連線失敗

確認 Ollama 正在監聽 port 11434，並以 `ollama list` 確認已下載 `qwen2`。

### 評估沒有重新呼叫模型

Promptfoo 預設會使用 cache。需要重新量測時加入 `--no-cache`；這會重新呼叫雲端模型並產生費用。
