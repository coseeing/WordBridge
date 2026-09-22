# 校正 catalog 解耦，並預留未來遠端來源的接縫

> 本文為 `2026-09-22-catalog-decoupling-design.md` 的繁體中文版，內容等價。

## 目標

收掉 `review-claude-2.md` 的 T17（`review-codex-2.md` 的 R14）：把設定 catalog 與
UI 的選擇狀態拆開、消除讓損壞設定拖垮整個 add-on 的 import-time side effect，並且
讓成果具備「未來換上遠端 HTTP catalog 時，任何 consumer 都不必改」的形狀。

今天新增一個 model 必須發新版 add-on，因為顯示名稱寫死在 `configManager.py` 的
`LABEL_DICT` 裡。本設計服務的終局是：**執行期取得一份 JSON payload，即可替換整個
catalog——model、顯示名稱、價格與 provider 參數。**

本批次只建立接縫與資料模型，**不實作 HTTP 取得**。

## 已拍板的決策

以下在撰寫 spec 前已與維護者確認。記錄下來是因為其中數項無法從程式碼反推。

| # | 決策 |
| --- | --- |
| 1 | 本階段只做接縫。不做 HTTP、快取、簽章、合併覆蓋。 |
| 2 | catalog 涵蓋今天四組資料：model、顯示名稱、價格、provider 參數。 |
| 3 | 逐筆驗證。壞的一筆跳過並記錄，永不拋例外。 |
| 4 | 全數無效時使用內建 fallback catalog，內含**一筆** Coseeing 條目，其 `corrector_config_id` 為 sentinel `"default"`。Coseeing 伺服器接受 `"default"` 並自行挑選 model，因此 Python 裡不寫死任何 model / provider / 價格字串。 |
| 5 | 該 sentinel 條目**同時存在於正常 catalog 中且永遠可選**，並且是新安裝的預設選擇。 |
| 6 | `SettingsRepository` 收納 `config.conf["WordBridge"]["settings"]` 的**全部**鍵，不只 catalog 相關的兩項。 |

決策 5 除了產品面的理由，還有一個可靠度理由：只在其他東西全壞時才出現的 fallback，
是一條沒人走過的路。讓它成為日常預設，等於災難路徑就是那條已知能動的路徑。

## 範圍

除另註明外，路徑相對於 `addon/globalPlugins/WordBridge/`。

範圍內：

- 新增 `lib/catalog/`：`model.py`、`document.py`、`sources.py`、`selection.py`、
  `fallback.py`、`registry.py`
- 新增 `settings_repository.py`
- `configManager.py` — 移除 `ConfigManager` 與 `LABEL_DICT`；`normalize_selection`
  與 `make_corrector_config_id` 移入 `lib/catalog/`
- `dialogs.py` — 移除 import 期的 catalog 建構與 `ctypes` 呼叫；面板改用 `SelectionState`
- `__init__.py` — 明確初始化 catalog、config spec 預設改靜態、task config 於 plugin
  init 載入、把 catalog 條目傳入校正路徑
- `lib/llm/provider.py`、`lib/llm/adapter.py` — 不再讀檔，改為接收條目
- `lib/application/task_factory.py`、`lib/application/task_runner.py` — 傳遞條目
- `setting/ai/` — 新增 sentinel 那一筆
- `workspace/evals/provider.py` — 一處呼叫點更新

明確排除：

- HTTP client、快取、離線政策、payload 簽章、bundled ⊕ remote 的覆蓋語意
- `CorrectionService`（T13）、`JobController`（T14）、domain errors（T15）、
  併發政策（T16）、`coseeing_auth` 狀態機（T18）
- `configManager.py` 改名——留待 T13 重整 `__init__.py` 時一併處理
- provider / adapter 子類的 `format_request` / `parse_response` 任何改動

## 架構

### 模組與依賴方向

```
lib/catalog/
  model.py      CorrectorCatalog, ProviderEntry, ModelEntry, SelectableItem, CatalogIssue
  document.py   build_catalog(document, *, runnable_providers) -> CorrectorCatalog
  sources.py    CatalogSource 協定；BundledCatalogSource
  selection.py  SelectionState
  fallback.py   FALLBACK_DOCUMENT
  registry.py   initialize(catalog) / current()
```

`lib/catalog` **只 import 標準函式庫**，不得 import `wx`、`config`、`addonHandler`、
`requests`，也不得 import `lib/llm` 下的任何東西。由此得到兩件事：它的測試不需要
NVDA stub；未來的 `RemoteCatalogSource` 只是 `sources.py` 裡多一個類別，consumer
一行都不用改。

```
dialogs.py ─────┐
__init__.py ────┼──→ lib/catalog
task_factory ───┘
                     lib/llm/provider.py, lib/llm/adapter.py  ←── 接收條目
```

### 持有與初始化

NVDA 自己 new `LLMSettingsPanel`（`categoryClasses` 裡放的是類別），所以無法用建構子
注入。`lib/catalog/registry.py` 提供 `initialize(catalog)` 與 `current()`；
`GlobalPlugin.__init__` 明確呼叫一次 `initialize()`，面板呼叫 `current()`。它仍是
行程內的單一值，但**是被明確初始化的**——這正是關鍵差別：`dialogs.py` 模組層級那行
`ConfigManager(...)` 因此消失。

在 `initialize()` 之前呼叫 `current()` 屬於程式錯誤，直接拋例外。測試自行明確初始化。

## catalog document

這是 wire format。`BundledCatalogSource` 把今天四組資料攤平成它；未來的
`RemoteCatalogSource` 會從一次 HTTP 回應產生同樣形狀。

```jsonc
{
  "schema_version": 1,
  "providers": {
    "OpenAI": {
      "label": "OpenAI",
      "url": "https://api.openai.com/v1/responses",
      "setting": { "max_output_tokens": 4096, "...": "..." },
      "timeout0": 10,
      "timeout_max": 20
    }
  },
  "models": [
    {
      "provider": "OpenAI",
      "model": "gpt-5.6-sol",
      "label": "gpt-5.6-sol",
      "active": true,
      "coseeing": false,
      "local": true,
      "pricing": { "input_tokens": 1.25, "output_tokens": 10, "base_unit": 1000000 },
      "usage_key": "usage"
    },
    {
      "provider": "Coseeing",
      "model": "default",
      "corrector_config_id": "default",
      "label": "Coseeing 預設（由伺服器決定）",
      "active": true,
      "coseeing": true,
      "local": false
    }
  ]
}
```

### model 條目欄位

| 欄位 | 必填 | 預設 | 說明 |
| --- | --- | --- | --- |
| `provider` | 是 | — | 不得含 `&` |
| `model` | 是 | — | 不得含 `&` |
| `corrector_config_id` | 否 | `make_corrector_config_id(model, provider)` | 顯式形式是為 sentinel 而存在，其 id 為 `"default"`，不含 `&` |
| `label` | 否 | `model` 字串本身 | 顯示名稱。把它移出 `LABEL_DICT` 正是遠端 payload 能新增 model 的前提 |
| `active` | 否 | `true` | |
| `coseeing` | 否 | `false` | 提供 Coseeing 通道 |
| `local` | 否 | `true` | 省略即為 true，使現有 13 個 `setting/ai/*.json` 一字不改仍然正確 |
| `pricing` | 否 | `None` | **刻意選配**：`qwen2&Ollama` 今天就沒有價格條目，且必須維持可用 |
| `usage_key` | 否 | `None` | 與 `pricing` 成對 |

`corrector_config_id` 絕不重複儲存：顯式欄位不存在時即由推導產生，因此一組
(model, provider) 只有一個身分。

價格屬於 (provider, model) **這一對**，不屬於其中任一方——`setting/price.json` 正是
以這一對為 key——所以它巢狀在 model 條目裡，而不是放在 `providers`。

### provider 條目欄位

`label`、`url`、`setting`、`timeout0`、`timeout_max`。除 `label` 外皆為必填；
`label` 預設為 provider 名稱。

## 驗證與降級

`build_catalog()` 永遠回傳一個 `CorrectorCatalog`。問題成為 `catalog.issues`
（`CatalogIssue(code, location, detail)` 的 tuple），永不是例外。呼叫端不需要
`try`/`except`。

兩條 provider 規則**只對要求 local 通道的條目生效**。`local: false` 的條目已聲明它
沒有 local 通道，兩條規則皆不適用、也不為它產生 issue——sentinel 的 provider
`Coseeing` 沒有 `Provider` 子類，不該被回報為問題。

| 情況 | 處置 |
| --- | --- |
| `pricing` 缺 | 條目保留，`pricing=None`。不算錯誤。 |
| `local: true` 且 provider 在 `providers` 中無有效條目 | 該 model 的 **local** 通道被抑制；Coseeing 通道不受影響。記 issue。 |
| `local: true` 且 provider 名稱不在 `runnable_providers` 中 | **local** 通道被抑制。記 issue。 |
| 兩個通道都被抑制 | 該條目產生零個可選項目。記 issue。 |
| provider 條目缺 `url` / `setting` / `timeout0` / `timeout_max` | provider 丟棄；其下 model 依上兩列處理。 |
| provider 未被任何 model 條目引用（不論該條目的通道為何） | 合法，只記 lint 級 issue。sentinel 指名 provider `Coseeing`，因此 `Coseeing.json` 即使對應條目為 `local: false` 仍算被引用。 |
| `model` 或 `provider` 為空，或含 `&` | 條目丟棄。記 issue。 |
| `corrector_config_id` 重複 | 首筆勝出，其餘丟棄。記 issue。（今天這會 `raise ValueError`，在 import 期讓整個 add-on 掛掉。） |
| `schema_version` 主版本不認得 | 整份 document 不採用，改用 fallback。 |

### 為何是抑制 local 通道，而不是丟棄整筆

一次本地校正需要三樣 Coseeing 通道不需要的東西：provider 參數、`Provider` 子類、
對應的 adapter。資料本身補不出後兩者——新的 provider 家族需要發新版 add-on。

- 遠端 payload 指名某個 model、沒附 provider 參數、但 `coseeing: true`：這是伺服器
  **跑得動**的 model。丟棄整筆等於藏起一個可用選項。
- 遠端 payload 為本 build 沒有程式碼的家族附上完整 provider 參數：若不擋，使用者會
  選得到、然後按下快捷鍵時得到 `ValueError: Unsupported provider`。`runnable_providers`
  規則把這個執行期爆炸變成「選單裡不出現」。

`runnable_providers` 以注入方式提供——`lib/catalog` 不得 import `lib/llm`。
`lib/llm` 匯出 `SUPPORTED_PROVIDERS`，取 `get_provider()` 家族表與
`get_provider_model_adapter()` 家族表的交集，並以測試斷言兩表相等。

### 降級三階

1. **正常** — 至少一個可選項目。
2. **降級** — 部分條目被丟棄，其餘照常運作，issues 可見。
3. **全空** — 零個可選項目：改用 `FALLBACK_DOCUMENT`。它只有一筆，形狀與出貨
   catalog 裡的 sentinel 完全相同，因此是一條程式路徑而非兩套。

add-on 永遠能載入。損壞的 catalog 絕不會阻止 NVDA 啟動或設定面板開啟。

### `"default"` sentinel

`correctTypo()` 的 Coseeing 分支本來就把 `corrector_config_id` 原樣送出，所以
`"default"` 直接抵達伺服器，零特例程式碼。該條目只有 Coseeing 通道
（`local: false`），因此永遠碰不到會在 `get_provider("Coseeing")` 失敗的本地路徑。
成本由伺服器回傳，`pricing: None` 不造成任何影響。

自我痊癒：使用者儲存值為 `"default"` 而 catalog 健康時仍可解析，因為 sentinel 在該
catalog 中就是一筆正常條目；若未來某份 catalog 省略它，`normalize_selection()` 回落
到 catalog 預設。不需要遷移程式碼。

可見性：issues 永遠完整記錄於 log；設定面板顯示一行摘要；該 session 中第一次在
fallback catalog 下執行的校正，透過 `ui.message` 告知一次。從不開設定面板的使用者
仍會知道「model 是伺服器決定的」——一次，而非每次校正都念。

## `ConfigManager` 的拆解

### `CorrectorCatalog`（不可變）

承接除可變的 `provider` 欄位外的全部：`selectable_items`、`provider_groups`、
`get_model(id)`、`get_provider(name)`、`default_selection()`、
`find_selection(id, channel)`、`get_item(group_index, model_index)`。索引式 API
保留，因為 `wx.Choice` 需要它。

移除可變欄位的關鍵改動只有一處：

```python
# 之前：隱藏的可變欄位決定回傳什麼
@property
def model_labels(self): ...          # 讀 self.provider

# 之後：純函式，答案只由參數決定
def labels_for(self, provider_group: str) -> tuple[str, ...]: ...
```

`model_labels` 是唯一逼出 `ConfigManager.provider` 的成員。

### `SelectionState`（`lib/catalog/selection.py`，由面板持有）

持有 `provider_group_index` 與 `model_index`。放在 `lib/catalog` 之下是因為它是
「對某個 catalog 的一個選擇」，只 import `model.py`，因此不需要 `wx` 即可測試。

- `SelectionState.restore(catalog, corrector_config_id, execution_channel)` 封裝今天
  `dialogs.py` 裡那段「正規化 → `find_selection` → `(-1, -1)` → 用預設」的流程
- `choose_provider_group(index)` 換組並把 model 索引歸零
- `current_item()` 回傳 `SelectableItem`

### `SettingsRepository`（`settings_repository.py`）

唯一碰 `config.conf["WordBridge"]["settings"]` 的模組。對每一個鍵提供具型別的存取器：
校正選擇、語言、校正模式、各 provider 的 API key、字數上限，以及三個布林旗標。

兩個解析住在這裡：

- `corrector_selection()` 把空字串解析為 catalog 當下的預設。這正是 config spec 預設
  能改成靜態值的原因。
- `language()` 把空字串解析為作業系統 UI 語言，延遲且只呼叫一次
  `ctypes.windll.kernel32.GetUserDefaultUILanguage()`，並加防護：失敗時降級為
  `zh_traditional`，而不是讓 import 失敗。

## import 期 side effect

| 今天 | 之後 |
| --- | --- |
| `dialogs.py:53-54` 於 import 期建立 `ConfigManager` 並呼叫 `default_selection()` | 移除。改由 `GlobalPlugin.__init__` 呼叫 `registry.initialize()` |
| `dialogs.py:35` 於 import 期呼叫 `ctypes.windll.kernel32.GetUserDefaultUILanguage()` | 移入 `SettingsRepository.language()`，延遲且有防護 |
| `__init__.py:109` 於 import 期呼叫 `load_corrector_task_config()` | 移入 plugin init；檔案損壞時降級為預設值並給出使用者可見訊息 |
| `config.conf.spec` 的預設值來自 catalog 與 `ctypes` | 改為靜態字串；真正的預設在讀取時解析 |

之後，import add-on 的模組不會讀取 `setting/` 下任何檔案，也不會有任何 `windll` 呼叫。

### `LABEL_DICT` 一分為二

`configManager.py` 的 `LABEL_DICT` 同時含 model 顯示名稱**與** UI 字串
（`zh_traditional`、`zh_simplified`、`standard`、`lite`、`personal_api_key`、
`coseeing_account`）。只有 model 名稱移入 catalog 資料，UI 字串留在 `dialogs.py`。
把 UI 字串送進 catalog，未來的遠端 payload 就會變成可以改寫介面用字的管道。

## provider 與 adapter 的注入

```python
def get_provider(provider_name, credential, retries=2, backoff=1, *, provider_entry) -> Provider
def get_provider_model_adapter(provider_name, model_name, *, price_entry) -> ProviderModelAdapter
```

兩個關鍵字參數皆為**必填**。若留一個「沒傳就去讀 bundled catalog」的預設，等於在
`lib/llm` 裡留下第二條讀檔路徑；一旦遠端來源存在，它會與現行 catalog 悄悄分歧。

`Provider.__init__` 不再讀 `setting/provider/<name>.json`；
`ProviderModelAdapter._load_model_entry` 不再讀 `setting/price.json`。
`create_typo_workflow()` 與 `run_typo_correction()` 增加這兩個參數並往下傳，使
add-on 的校正路徑在型別上被迫使用當下的 catalog。

刻意不動的部分：

- **`CostCalculator`** — 它吃的是 `{model, provider, pricing, usage_key}`，因此
  `ModelEntry.price_entry()` 產出同樣形狀，無價格時回傳 `{}`。與今天
  `.get(..., {})` 逐位元組等價，這正是 `qwen2&Ollama` 得以繼續運作的原因。
- `adapter.get_model_entry()` 的公開簽章。
- 每一個 `format_request` / `parse_response`。

移除：`provider.py:36` 的 `getattr(self, 'setting_name', self.name)`。全 repo 沒有
任何子類定義 `setting_name`，它是檔名對不上時的兜底，而注入之後根本不存在檔名。

需更新的呼叫點：`workspace/evals/provider.py`（一處）、`tests/test_provider_naming.py`
（三處，且該檔本就要改寫為從 catalog 推導）、`tests/test_eval_provider_config.py`（一處）。

## 測試

依此順序撰寫。第 2 層必須在**任何 production code 變更之前**就是綠的。

1. **document 驗證**（`tests/test_catalog_document.py`）— 驗證表每一列各一個測試，
   包含 `qwen2&Ollama` 的缺價守衛與兩條 local 抑制規則。
2. **bundled 保真度**（`tests/test_catalog_bundled.py`）— characterization test：以
   真實 `setting/` 目錄建 catalog，斷言產出的可選項目、ids、labels 與價格**與今天
   `ConfigManager` + `LABEL_DICT` + `price.json` 的結果逐項相同**。這是「什麼都沒
   弄丟」的證明，因此以現行實作為 oracle，在重構開始前寫好。它並斷言 issue 清單恰好
   只含一筆已知 lint（`OpenRouter.json` 未被任何 model 引用），使未來多出的孤兒檔案
   會被抓到。
3. **選擇與設定**（`tests/test_selection_state.py`、`tests/test_settings_repository.py`）
   — 還原、未知 id、通道不可用、換組時 model 索引歸零；空字串解析、`ctypes` 失敗降級
   為 `zh_traditional`、寫入確實落到 config。
4. **fallback**（`tests/test_catalog_fallback.py`）— 壞掉的 document 產生恰好一筆、
   id 為 `"default"`、僅 Coseeing 的項目；健康 catalog 下儲存值 `"default"` 可解析；
   且 fallback 條目與出貨 sentinel 產生完全相同的 `SelectableItem`。
5. **接縫本身**（`tests/test_catalog_source_seam.py`）— 以 `FakeRemoteCatalogSource`
   回傳記憶體中的 document，斷言 catalog、selection 與面板取得的結果與同樣內容來自
   bundled 檔案時完全一致。它在不實作 HTTP 的前提下證明接縫成立，並成為未來
   `RemoteCatalogSource` 的契約。
6. **import 純淨度**（`tests/test_import_purity.py`）— 於子行程中以
   `sys.addaudithook` 攔 `open` 事件，斷言 import `dialogs` 與 plugin 模組期間沒有
   讀取 `setting/` 下任何檔案、也沒有 `windll` 呼叫。
7. **注入與純度** — 缺少條目時 `create_typo_workflow()` 拋 `TypeError`；
   `SUPPORTED_PROVIDERS` 等於 adapter 家族表；且 `lib/catalog/` 下每個模組都不 import
   標準函式庫以外的東西——以 AST 走訪斷言，使「剛好沒執行到」的 import 無法蒙混過關。

回歸基線：343 passed、1 skipped、16 deselected。既有
`tests/test_corrector_catalog_unittest.py` 改寫至新 API，其餘全部維持綠燈。

依範圍不測：網路、快取、簽章、覆蓋合併。

## 驗收條件

1. `addon/globalPlugins/WordBridge/` 下沒有任何模組在 import 期讀取 `setting/` 下的
   檔案，import 期也沒有任何 `windll` 呼叫——由測試 6 斷言。
2. `setting/ai/` 為空目錄，或每個檔案的 JSON 都損壞時，add-on 仍可載入、設定面板仍可
   開啟，且仍提供 `"default"` 這個 Coseeing 選項。
3. 單一 `setting/ai/*.json` 損壞時只移除該筆。
4. 出貨 catalog 產生的可選項目與本次變更前完全相同，外加新的 sentinel 條目——由測試
   2 斷言。
5. `"default"` 是新安裝的預設選擇；既有使用者的儲存選擇不受影響。
6. 為既有 provider 家族新增 model 只需編輯 catalog 資料——不需要任何 Python 改動，
   包含不需要改 label。
7. `lib/catalog` 不 import 標準函式庫以外的任何東西——由測試斷言。
8. 完整的非整合測試套件全綠。

## 風險

- **`config.conf.spec` 預設值變成空字串。** 每一條讀取路徑都必須經過
  `SettingsRepository`；漏掉一個裸 subscript 會表現為空的 model id。緩解方式是讓
  repository 成為唯一碰 `config.conf` 的模組，並以測試 3 守住。
- **決策 5 改變了新安裝的選擇。** 既有使用者不受影響，但新使用者拿到的是 Coseeing
  伺服器挑的 model，而不是清單中碰巧排第一的那個。這是刻意的；在此列出是因為它是
  一項隨重構一起上路、且使用者看得見的產品改動。
- **伺服器的 `"default"` 契約是外部的。** 若 Coseeing 伺服器哪天不再接受
  `"default"`，fallback 就失效。本 repo 沒有任何測試涵蓋得到——這裡的 `server/`
  是空目錄。
- **sentinel 實際用了哪個 model 看不到。** proofreader 回應含 `response`、
  `interaction_id` 與 `cost`，沒有 model 名稱，因此 UI 與報表都無法說明
  `"default"` 請求由哪個 model 服務。現階段可接受；若伺服器日後回傳該資訊，UI 再顯示。
