# P1/P2 修正：正確性缺陷、打包體積與報表位置

## 目標

完成 `review-claude-2.md` 的 P1 與 P2 項目（T4–T9、T11、T12），並納入
`review-codex-2.md` 對同一批缺陷訂定的較嚴格驗收條件（R04、R05、R06、R11、
R13、R15、R16）中，不依賴 P3 重構的部分。

| ID | 任務 | codex 對應 |
| --- | --- | --- |
| T4 | 重校迴圈的分段／歷史錯位 | R04 |
| T5 | 繁簡標記永遠不觸發 | R05 |
| T6 | 以 `assert` 做流程控制 | R05 |
| T7 | 三處被遮蔽／抽不到的翻譯 | R11 |
| T8 | 邊界條件與雜項缺陷 | R06、R18（部分） |
| T9 | 打包瘦身與啟動成本 | R15、R16 |
| T11 | 殘留設定與命名不一致 | R14（部分） |
| T12 | 報表輸出移出安裝目錄 | R13 |

**T10（CI 測試與靜態檢查門檻）依維護者決定排除於本批之外。**
`review-claude-2.md` 在 T9-4 與 T10-4 重複列出的打包內容測試仍會在此撰寫，
之後接 CI 時可原樣採用。

## 範圍

除非另有註明，以下 add-on 路徑皆相對於 `addon/globalPlugins/WordBridge/`。

包含範圍：

- `lib/tasks/typo/workflow.py`、`lib/tasks/concurrency.py`（T4）
- `lib/tasks/typo/utils.py`、`lib/text/chinese.py`（T5、T6）
- `lib/llm/provider.py`、`configManager.py`、`lib/llm/executor.py`（T7）
- `lib/tasks/typo/text_policy.py`、`__init__.py`（T8）
- `lib/tasks/typo/chinese_dictionary.py`、`lib/tasks/typo/data/`、`buildVars.py`、
  `workspace/evals/generate_zhuyin_dataset.py`（T9）
- `setting/provider/*.json`、`lib/llm/provider.py`、`__init__.py` config spec（T11）
- `__init__.py` 的 `showReport()`、新增 `lib/report.py`、新增 `lib/paths.py`、
  `dictionary/__init__.py`（T12）

明確**不**包含——全部屬於 P3，刻意不動，讓本批可獨立驗收：

- 單一 `JobController` 與 UI dispatcher 抽象（R07/T14）
- `WordBridgeError` domain error 階層（R09/T15）
- `CorrectionService` 與 local／Coseeing backend 契約（R10/T13）
- 併發上限、deadline 與 metrics 彙整（R12/T16）
- 設定 catalog／選擇狀態解耦與 import-time side effect（R14/T17）——
  包含 `dictionary/__init__.py` import 時的 `os.makedirs`
- `coseeing_auth` 狀態機（R17/T18）
- CI 與靜態檢查門檻（T10）

報表前端不動。`analyze_diff` 的 tags 只修復資料正確性，在報表中呈現標記是另一個
功能決定。

## 驗證限制

開發主機為 Linux；Windows 與 NVDA 的驗證由維護者執行。以下每項需求皆標記為
**[auto]**（可在本機以 `tests/` 既有的 NVDA stub 樣式執行的測試涵蓋）或
**[manual]**（需要 Windows/NVDA，在維護者確認前一律回報為「待平台驗證」）。

本機 2026-09-21 實測基線，`python3 -m pytest -q -m "not integration"`：
238 passed、1 skipped、16 deselected、**2 failed**。兩個失敗都早於本批：

- `tests/test_provider_naming.py::test_provider_config_filenames_match_catalog` ——
  預期清單漏了 `ollama.json`。於 T11 修正。
- `tests/test_coseeing_auth_bundle.py::test_sso_configuration_matches_approved_demo` ——
  預期 `client_id == "a11yvillage"`，而 `lib/coseeing_auth.py:140` 實際設為
  `client_id="wordbridge"`。維護者確認程式值正確，於此更新測試期望值。

本批要到這道指令回報零失敗才算完成。

## 設計

### T4 — 重校迴圈的分段／歷史錯位

#### 已確認事實

讀自 `lib/tasks/typo/workflow.py:36-72` 與 `lib/tasks/concurrency.py:5-32`：

- `segments_to_recorrect` 與 `segments_revised` 恆等長。
  `get_segments_to_recorrect()` 對沒有標記錯字的段落輸出 `""`，而
  `_execute_segment("")` 會因 `TypoTextPolicy.has_target_language("")` 為 False
  而立即返回，不發 API 請求。空段落目前不花錢，修正後也必須維持不花錢。
- 錯位只發生在 `recorrection_history`。它只在第一輪建立一次，大小為該輪的段數
  L₁。之後每一輪都會重新切分 `text_corrected_revised`，段數 L₂ 可能不同。
- `parallel_map` 收到長度 L₂ 的 `iterable` 與長度 L₁ 的 `iterable_kwargs`，用
  `zip` 配對，截斷到 `min(L₁, L₂)`。

兩種失效模式都與 `review-claude-2.md` 的描述不同：

- **L₂ > L₁** —— 尾端的工作根本沒送出。`parallel_map` 預先填
  `results = [None] * len(iterable)`，只對送出的索引賦值，所以尾端維持 `None`，
  `results[j].output_text` 丟的是 **`AttributeError`**，不是 `IndexError`。
- **L₂ < L₁** —— 不會拋例外。`recorrection_history[j]` 指向的是上一輪**另一個**
  段落，模型被靜默餵入別的段落被否決過的答案。

#### 變更

歷史改以段落文字為 key，不再以 list 索引對齊：

```python
recorrection_history: dict[str, list[str]] = {}
...
use_history = i >= self.max_correction_attempts / 3
history_for_correction = [
	recorrection_history.get(segment, []) if use_history else []
	for segment in segments_revised
]
```

歷史的用途是「這段文字你已經答過這些，別再重複」，這件事本來就是**文字**的屬性，
不是某個每輪重建的 list 中的位置。段落邊界因此可以自由移動而不會配錯。文字被改
掉的段落自然沒有歷史，這也是正確的。同一輪出現兩個相同段落會共用一份歷史，既有的
`not in` 去重仍然成立。

回填迴圈以同一個 key 寫入：

```python
for segment, result in zip(segments_revised, results, strict=True):
	if result.output_text:
		res_text = result.output_text
		text_corrected += res_text
		history = recorrection_history.setdefault(segment, [])
		if res_text not in history and len(res_text) < len(input_text) * 2:
			history.append(res_text)
	else:
		text_corrected += segment
```

完全移除 `range(len(segments_revised))` 的索引存取。

#### `parallel_map` 嚴格化

`lib/tasks/concurrency.py` 必須拋錯而非截斷：

- `iterable` 與 `iterable_kwargs` 的型別註記從 `Iterable` 改為 `Sequence`。
  現行實作已經在呼叫 `len(iterable)`，既有註記本來就是錯的。
- 當 `iterable_kwargs is not None` 且 `len(iterable_kwargs) != len(iterable)`
  時，在送出任何工作**之前**丟 `ValueError`，訊息中指明兩者長度。

有了這道檢查，`results` 就不可能殘留 `None`，workflow 不需要額外的 `None` 防護。
`workflow.py` 的循序分支基於同樣理由改用 `zip(..., strict=True)`。

段落順序、未重校文字與 `max_correction_attempts` 上限維持不變。

### T5 — 繁簡標記永遠不觸發

`lib/tasks/typo/utils.py:104-105` 目前是：

```python
char_simplified = char_original
char_traditional = char_original
```

因此下方兩個比較恆為 False，兩種轉換標記永遠不會產生。

來歷（查自 git 紀錄）：commit `7c00aac`（2023-04-14）引入 `analyze_diff()` 時，
用的是真正的 `to_simplified()` / `to_traditional()` 呼叫。commit `f37a090`
（2023-04-18，「Added web UI」）把它們註解掉——當時 `chinese_converter` 尚未
vendored——之後沒有再恢復。

`chinese_converter` 今天已經 vendored，而且就在同一個檔案頂端被 import
（`utils.py:4`，`typo_augmentation` 在用）。修正就是把兩個呼叫補回去：

```python
char_simplified = to_simplified(char_original)
char_traditional = to_traditional(char_original)
```

`analyze_diff()` 的同音判別部分一直是正確的，不做變更。

`tags` 目前沒有任何消費端：它會寫進報表 JSON，但
`web/templates/index.template` 從未讀取，add-on 內也沒有其他讀取點
（已針對 `.template`、`.html`、`.js` 查核全部 git 歷史）。依維護者決定，本批只
修復資料正確性；在報表呈現標記不在範圍內。

### T6 — 以 `assert` 做流程控制

有四處 `assert` 參與流程控制：

| 位置 | 敘述 | 問題 |
| --- | --- | --- |
| `lib/tasks/typo/utils.py:16` | `get_char_pinyin()` 的 `assert len(char) == 1` | `find_correction_errors()` 傳入的是整個 diff token，而 tokenizer 會把連續非中文字元合併成單一 token |
| `lib/tasks/typo/utils.py:61` | `create_single_char_mapping()` 的 `assert len(tokens) <= 20000` | 真正的容量上限卻寫成斷言 |
| `lib/tasks/typo/utils.py:181` | `assert len(before_text) == 1 and len(after_text) == 1` | 任何多字元 replace token 都會觸發 |
| `lib/text/chinese.py:33` | `is_chinese_character()` 的 `assert len(char) <= 1` | `review_correction_errors()` 傳入整個 token，對同樣輸入也會拋例外 |

四處全部不再以斷言形式存在。`assert` 在 `python -O` 下會被移除，因此行為不得
依賴其中任何一個。

#### 非中文替換的政策

只拿掉斷言並不夠，必須明確定義政策，因為 `find_correction_errors()` 與
`review_correction_errors()` 都建立在「單一中文字」的假設上分支。

**採用政策：`replace` 的任一側若不是單一中文字，保留原文，且不將該位置加入
`typo_indices`。**

- 保留原文維持現行產品行為。`review_correction_errors()` 本來就會拒絕任一側
  `is_chinese_character()` 不成立的替換；本批不擴張校正器可以接受的範圍。
- 不標記位置是刻意的**行為改變**。目前單字元的非中文替換（`A` → `B`）會被加入
  `typo_indices`，因而排入下一輪重校。既然政策永遠不會接受這個替換，多跑的那一輪
  只會消耗 API 預算。中文的非同音替換仍與過去完全一樣標記重校。

實作：

- `is_chinese_character()` 對長度大於 1 的字串回傳 `False`，不再斷言。它對 `""`
  本來就回傳 `False`。
- `get_char_pinyin()` 只接受單一中文字。呼叫端會在呼叫前先判斷該條件，因此函式對
  其他輸入丟 `ValueError`，而不是靜默回傳 `[]`——靜默的空 list 會被讀成「不同音」，
  悄悄走回錯字分支。
- `find_correction_errors()` 在 replace 分支加上明確判斷：任一側不是單一中文字時，
  附加 `before_text` 後直接繼續，不碰 `typo_indices`。
- `create_single_char_mapping()` 丟 `ValueError`，訊息中列出實際與上限的 token 數。
- `strings_diff()` 直接刪除第 181 行的斷言。

### T7 — 翻譯綁定與 gettext 擷取

三個各自獨立的缺陷：

1. `lib/llm/provider.py:10-17` 在嘗試 `addonHandler.initTranslation()` **之前**就
   定義了 module-level 的 `def _`。`initTranslation()` 是把 `_` 注入 builtins，而
   module global 永遠遮蔽 builtin，所以 provider 的所有錯誤訊息實際上都未翻譯。
2. `configManager.py:12-14` 用 `if "_" not in globals()` 判斷。在 NVDA 下 `_` 是
   builtin、永遠不是 global，因此該判斷恆為真，以同樣方式遮蔽翻譯函式。
3. `lib/llm/executor.py:53` 呼叫 `_(f"...")`。`xgettext` 無法擷取執行期格式化的
   f-string，訊息從未進入 `.pot`。`ruff` 也獨立把它標為整個程式碼庫唯一的
   `INT001`。

#### fallback 樣式

`review-claude-2.md` 建議採用 `lib/llm/executor.py:7-12` 既有的寫法。本機實測顯示
該寫法在測試環境下本身就是壞的：`tests/conftest.py` 安裝的 `addonHandler` stub
其 `initTranslation` 是 `lambda: None`，所以 `import addonHandler` 成功、沒有任何
地方定義 `_`，第一次呼叫 `_()` 就 `NameError`。

採用的樣式只在完全找不到 `_` 時才定義 fallback，因此絕不遮蔽 builtin：

```python
try:
	import addonHandler
	addonHandler.initTranslation()
except ImportError:
	pass

try:
	_
except NameError:
	def _(s):
		return s
```

在 module 層，裸 `_` 會依序查 globals 與 builtins。NVDA 下 builtin 存在，就不會
建立 module global。在 NVDA 之外——特別是 `workspace/evals/`，它會在沒有 NVDA
runtime 的情況下 import `lib/llm/provider.py`——fallback 才會被定義。

此樣式套用於 `lib/llm/provider.py`、`configManager.py` 與 `lib/llm/executor.py`。

#### 測試 stub

`tests/conftest.py` 與各檔案自己的 `addonHandler` stub 目前把 `initTranslation`
設為 no-op，導致無法觀察訊息是否真的被翻譯。改為注入一個可辨識的標記函式到
builtins，讓測試能斷言顯示的訊息確實經過 `_()`。該 stub 在多個模組安裝時必須維持
冪等。

#### 靜態字串

`lib/llm/executor.py:53` 改為靜態訊息加 `.format()`：

```python
raise Exception(_("Parsing error. Unexpected server response. Response: {response}").format(response=response_json))
```

所觸及檔案中其他每一處 `_()` 呼叫點都會檢查是否有相同問題。把錯誤訊息的翻譯移到
UI 邊界屬於 R09/T15，不在此處進行。

### T8 — 邊界條件與雜項缺陷

#### T8-1 `lib/tasks/typo/text_policy.py:30-39`

三處未防護的索引：`input_text_tmp[-1]`（第 30 行）、`input_text[-1]`（第 33 行）
與 `input_text_tmp[0]`（第 39 行）。`text` 在每一處都已經有防護，輸入字串沒有。

定義下列情境的行為：空輸入、模型回傳空字串、模型只回傳標點、prefix/suffix 剝除後
把整個回應吃光。既有的前後標點保留規則不變——修正不得為了避免例外而無條件補字或
丟棄有效內容。

#### T8-2 `latest_action` —— 已完成

P0 批次已把這個跨執行緒欄位改為「UI 執行緒單一寫入者 + frozen snapshot」
（`__init__.py:210-227`、`:451`、`:560-567`）。本項不需要新變更；規格在此記錄其
已滿足，本批只驗證既有測試仍覆蓋。

#### T8-3 `__init__.py:392-393` 死碼

worker 先 `self._notify(...)`、再 `log.warning(...)`、接著 `raise e`，後面跟著
永遠到不了的 `return`。移除 `raise e`，保留 `return`。在 worker thread 裡
re-raise 只會在使用者已收到通知之後，於 NVDA log 留下一個無人處理的 thread
exception，而這正是 codex R18 明文排除的。

#### T8-4 `__init__.py:469` 裸 `except`

成本格式化被裹在裸 `except: pass` 裡，之後未格式化的原值會被插進
「This task costs {cost} USD」訊息。改為明確的
`except (TypeError, ValueError, decimal.InvalidOperation)`，記錄原因，並回報明確的
「成本無法取得」狀態。不偽造零、不隱藏錯誤。

`showReport()` 中的兩個 `except BaseException: pass`
（`__init__.py:256-258`、`:267-269`）隨 T12 的改寫一併消失。

#### T8-5 日誌層級

正常流程的訊息從 `log.warning` 降為 `log.info` 或 `log.debug`：
「No errors in the selected text.」、「The corrected text has been copied to the
clipboard.」、「This task costs {cost} USD.」，以及任務開始／完成的提示。
`warning` 與 `error` 保留給異常。不記錄憑證與使用者全文。

### T9 — 打包瘦身與啟動成本

#### 資料檔案

`lib/tasks/typo/data/` 的實測大小：

| 檔案 | 大小 | 引用者 | 處置 |
| --- | --- | --- | --- |
| `dict_revised_2015_20231228.xlsx` | 30M | 無 | 移至 `workspace/data/` |
| `dict_revised_2015_20231228_csv.csv` | 3.6M | `chinese_dictionary.py:7` | **保留**——唯一的 runtime 字典 |
| `chinese_dictionary_bopomofo.csv` | 268K | `workspace/evals/generate_zhuyin_dataset.py:22` | 移至 `workspace/data/` |
| `chinese_dictionary_pinyin_number.csv` | 240K | 無 | 移至 `workspace/data/` |
| `readme.txt` | 4K | — | 拆分，各半跟著自己的檔案走 |

`workspace/evals/generate_zhuyin_dataset.py` 與
`tests/test_generate_zhuyin_dataset_unittest.py` 更新為新路徑。不改寫 git 歷史，
版本庫仍保有這些檔案。

#### `buildVars.excludedFiles`

`site_scons/site_tools/NVDATool/addon.py:7-9` 用 `Path.match()` 比對，而它是
**從右側比對**，所以副檔名 pattern 不需要前置路徑就有效：

```python
excludedFiles: list[str] = [
	"__pycache__/*",
	"*.pyc",
	"*.pyo",
	"*.xlsx",
	"web/workspace/*",
]
```

`web/workspace/` 未納入 git 版控，是現行 `showReport()` 在執行期建立的，會隨 T12
消失；保留此 pattern 是為了防範「先跑過 add-on 再建置」的開發機器。第三方授權檔與
必要的原生檔案不排除。**不以副檔名排除 CSV**——runtime 字典本身就是 CSV。

#### 字典延遲載入

`lib/tasks/typo/chinese_dictionary.py:20` 在 import 時解析 3.6M 的 CSV，而
`__init__.py:54` 從 `lib/tasks/typo/utils.py` import `strings_diff`，後者又 import
這個模組——所以這次解析落在 NVDA 的啟動必經路徑上。

兩個 module-level mapping 改為 `get_string_to_pinyin()` 與
`get_pinyin_to_string()`，背後是單一 module-level 快取，以 `threading.Lock` 做
雙重檢查初始化。

`functools.lru_cache` 不足：它不會在被包裹的呼叫外圍持鎖，多個 `parallel_map`
worker 首次取用時會各自解析一次檔案。鎖同時確保沒有任何呼叫端會讀到部分建構的
mapping。

字典缺失或無法讀取時丟明確例外。不得退化成空的 `defaultdict`——那會讓每個字看起來
都沒有讀音。

`lib/tasks/typo/utils.py` 的四個呼叫點（第 17、27、31-32、111 行）一併更新。

兩個 mapping 內部仍維持 `defaultdict(list)`，但可能查不到的查詢
（`utils.py:17`、`:111`，以及 `analyze_diff` 對單一非中文字的查詢）改用
`.get(char, [])`。共用且存活於整個行程的 `defaultdict` 每次 miss 都會長出一個空
項目；舊的「每次 import 各一份」實作把它限制在該次 import 之內，單一快取則沒有這個
界限。

#### 體積帳

在相同建置輸入下，記錄變更前後的壓縮與解壓大小以及檔案清單。原 review 的
34MB／27MB 數字不作為保證值沿用。

### T11 — 殘留設定與命名

1. 從 config spec 移除 `coseeing_username` 與 `coseeing_password`
   （`__init__.py:95-96`）。依維護者決定**不另寫升級測試**；驗收條件為既有測試
   全數通過，而持有舊 key 的使用者設定檔實際升級行為屬 **[manual]**。
2. `setting/provider/*.json` 檔名對齊 `Provider.name`：
   `anthropic.json` → `Anthropic.json`、`deepseek.json` → `DeepSeek.json`、
   `google.json` → `Google.json`、`ollama.json` → `Ollama.json`、
   `openrouter.json` → `OpenRouter.json`。`Coseeing.json` 與 `OpenAI.json` 已相符。
   接著移除 `lib/llm/provider.py:31-35` 的 case-insensitive glob 兜底，只留
   `setting_dir / f"{name}.json"` 的直接查找。

   已儲存的使用者設定不需要遷移：檔名由 `Provider.name` 類別屬性推導，從不取自任何
   持久化的值。已儲存的 `corrector_config_id` 若指向未知 provider，
   `normalize_selection()` 本來就會退回預設。
3. 修復並強化 `tests/test_provider_naming.py`：對每個 `setting/ai/*.json`，其
   `provider` 值都必須能對應到 `setting/provider/` 的檔案與 `setting/price.json`
   的條目。從 catalog 推導期望值而非手寫字面清單，才能阻止 `ollama.json` 這類
   退化再次發生。
4. `tests/test_coseeing_auth_bundle.py` 的期望值改為
   `client_id == "wordbridge"`，與 `lib/coseeing_auth.py:140` 一致。

### T12 — 報表輸出位置

`showReport()`（`__init__.py:250-287`）目前每產生一份報表就 `rmtree` 並重建
**add-on 安裝目錄內**的兩個目錄，並 `copytree` 一次靜態資源。

#### 新模組 `lib/report.py`

`generate_report(diff_data) -> Path` 負責目錄配置、資源準備、模板渲染與保留策略。
它不 import NVDA 或 wx，因此可直接測試。`GlobalPlugin.showReport()` 縮減為呼叫它
並把結果交給 `OnPreview`。兩個 `except BaseException: pass` 隨舊程式一起消失。

#### 位置

```
<user folder>/WordBridge-workspace/
├── dictionary/                       （既有）
└── reports/
    ├── modules/                      共用資源
    │   ├── sweetalert2.all.min.js
    │   └── vue.js
    └── 20260921-143012-a3f9/
        ├── result.txt
        └── result.html
```

四碼亂數後綴避免同一秒內產生兩份報表時撞名。

`dictionary/__init__.py` 以六層 `os.path.dirname` 推導使用者資料夾。該段抽到
`lib/paths.py` 的 `user_workspace_root()` 共用，而非複製一份。
`dictionary/__init__.py` 在 import 時的 `os.makedirs` side effect 屬 R14/T17，
維持不動。

#### 靜態資源

`web/templates/index.template:9-10` 以相對路徑載入
`modules/sweetalert2.all.min.js` 與 `modules/vue.js`。

依維護者決定，資源**只複製一次**到 `reports/modules/`，每份報表以
`../modules/...` 引用。只有在檔案不存在、或安裝目錄中的版本較新時才會複製。

這與 `review-claude-2.md` T12-3 的字面說法（「直接引用安裝目錄中的檔案」）不同，
但符合其意圖——不再每份報表 `copytree`，也不對安裝目錄寫入。使用指向安裝目錄的
絕對 `file:///` URL 的方案已被排除：它需要正確編碼含空白或非 ASCII 字元的安裝
路徑，而且 `file://` 頁面載入另一個目錄的 `file://` 腳本在各瀏覽器行為不一致，
必須做 Windows 實測才敢採信。

#### 保留策略與失敗處理

- 只有直接位於 `reports/` 底下、名稱符合 `YYYYmmdd-HHMMSS-xxxx` 格式的目錄才可被
  刪除。`modules/` 與其他任何東西都不會被碰。
- 保留最近 20 份報表目錄，較舊的刪除。「最近」以目錄名稱判定，不用檔案系統 mtime：
  `YYYYmmdd-HHMMSS-xxxx` 前綴的字典序即時間序，而 mtime 會在瀏覽器或使用者觸碰報表
  時改變。
- 刪除失敗（瀏覽器佔用檔案、權限不足）記錄後繼續，不中止本次報表產生。
- 報表產生失敗向上傳遞給呼叫端，由其通知使用者。不吞任何錯誤。
- 安裝目錄只以唯讀方式開啟模板。

檔案 I/O 仍在 `showReport` 今天執行的位置，經既有的 `_run_on_ui` 派送。把它移到
背景 worker 屬於 R07/T14。

## 錯誤處理

- `parallel_map` 在送出工作前對長度不符丟 `ValueError`，讓不一致在呼叫點大聲失敗，
  而不是產出一份長度不足的結果清單。
- `create_single_char_mapping()` 與 `get_char_pinyin()` 丟 `ValueError`，訊息中
  包含造成問題的值。
- 字典載入失敗直接拋錯，絕不退化為空 mapping。
- 成本格式化失敗記錄原因，並以明確的「成本無法取得」狀態呈現。
- 報表保留策略的失敗記錄下來；報表產生失敗則傳達給使用者。
- 不引入任何未經 `_()` 的使用者可見訊息，且每個 `_()` 都接字面字串、之後才
  `.format()`。

## 測試

新增或修改的測試檔，全部可在本機執行：

| 檔案 | 涵蓋 |
| --- | --- |
| `tests/test_recorrection_workflow.py`（新增） | T4：fake executor；段數增加、減少、相同但邊界移動、無需重校、空結果；並行與循序兩條路徑；`parallel_map` 長度不符必須拋錯 |
| `tests/test_typo_diff_tags.py`（新增） | T5：繁轉簡、簡轉繁、同音不同字；T6：中英數與網址混排文字通過 `strings_diff`、`find_correction_errors`、`review_correction_errors` 不拋 `AssertionError`，且 `python -O` 下行為一致（以子行程執行，因為 `-O` 無法在 pytest 行程內切換） |
| `tests/test_translation_binding.py`（新增） | T7：注入的標記 `_` 證明訊息確實被翻譯；fallback 只在完全取不到 `_` 時生效；executor 的訊息是靜態字串 |
| `tests/test_language_text_policy_unittest.py`（擴充） | T8-1：空輸入、空回應、只有標點的回應、prefix/suffix 吃光回應——涵蓋 lite 與 standard 兩種 policy 及兩種語言 |
| `tests/test_chinese_dictionary_lazy.py`（新增） | T9：以子行程斷言 import `lib.tasks.typo.utils` 之後快取仍未載入；並行首次存取只載入一次且 mapping 完整；mapping 結果與變更前一致 |
| `tests/test_addon_bundle_contents.py`（新增） | T9：以 `buildVars.excludedFiles` 呼叫 `site_scons/site_tools/NVDATool/addon.py` 的 `createAddonBundleFromPath()` 打包到 `tmp_path`；斷言不含 `__pycache__`、`.pyc`、`.xlsx`，且 runtime CSV、`package/` auth bundle 與 `web/templates/modules/vue.js` 都在 |
| `tests/test_provider_naming.py`（修復＋擴充） | T11：檔名由 catalog 推導；每個 `setting/ai/*.json` 的 provider 都對應得到 provider 設定檔與 `price.json` 條目 |
| `tests/test_coseeing_auth_bundle.py`（修復） | T11：`client_id == "wordbridge"` |
| `tests/test_report_output.py`（新增） | T12：寫入 `WordBridge-workspace/reports/`，絕不寫入安裝目錄；連續兩份報表互不覆蓋；`modules/` 只準備一次並以相對路徑引用；保留策略保留 20 份且只刪符合格式的目錄；安裝目錄唯讀時仍能產生完整報表；刪除失敗不影響產生 |

`tests/test_addon_bundle_contents.py` 要壓縮一棵 62M 的檔案樹。實作時會實測其耗時，
若超過數秒就標記為 `slow`。

**[manual]** —— 待平台驗證，交付時必須如此註記：

- 升級仍持有 `coseeing_username` / `coseeing_password` 的設定檔
- Windows 上以真實瀏覽器驗證報表產生、資源載入與鍵盤操作
- 在 Windows 上量測 NVDA 啟動不再讀取 3.6M CSV
- 在繁體中文 NVDA 上實測 provider 與 executor 的訊息確實被翻譯

重新產生 `scons pot` 並確認 T7 的訊息出現在 `.pot` 中同樣是 **[manual]**——
本機未安裝 `scons`。

## 交付順序

由內而外，先處理純函式層，避免其測試被外層變更干擾判讀：

1. **T5** —— 恢復轉換呼叫（兩行，孤立）
2. **T6** —— 移除斷言並確立非中文政策
3. **T4** —— 歷史改為以文字為 key；`parallel_map` 嚴格化
4. **T7** —— 翻譯綁定與靜態字串
5. **T8** —— 邊界防護、死碼、裸 `except`、日誌層級
6. **T11** —— config spec、provider 檔名、命名測試
7. **T9** —— 搬移資料、排除規則、字典延遲載入、打包測試
8. **T12** —— `lib/paths.py`、`lib/report.py`、改寫 `showReport()`

每個任務一個 commit，各自帶測試，各自可獨立回退。

## 非目標

- 在報表中呈現 `analyze_diff` 的 tags
- 擴張校正器對非中文文字可接受的範圍
- CI、ruff 或 pyright 門檻（T10）
- 範圍一節列出的任何 P3 項目
- 改寫 git 歷史以移除 30M 的 XLSX
