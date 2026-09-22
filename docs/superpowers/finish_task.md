# Corrector catalog 解耦 — 完成報告

- **分支**：`catalog-decoupling`（自 `main` @ `0cc4da0` 開出，尚未合併）
- **Spec**：`docs/superpowers/specs/2026-09-22-catalog-decoupling-design.md`
- **Plan**：`docs/superpowers/plans/2026-09-22-catalog-decoupling.md`
- **執行方式**：Subagent-Driven Development。每個 task 由 implementation subagent（claude-sonnet-5）實作，再由獨立 review subagent（claude-opus-5）審閱；有發現就退回修正並重新審閱，直到 review 沒有 Critical/Important 為止。全部 task 完成後再做一次整支分支的 whole-branch review。
- **日期**：2026-09-22

---

## 一、結果摘要

| 項目 | 執行前 | 執行後 |
| --- | --- | --- |
| 非整合測試 | 343 passed / 1 skipped / 16 deselected | **448 passed / 0 failed / 1 skipped / 16 deselected** |
| 測試輸出 | — | pristine（無 warning） |
| import 期讀取 `setting/` 檔案 | 有（`dialogs.py` 建 `ConfigManager`、讀 `ai/*.json`） | **無**（由 `tests/test_import_purity.py` 把關） |
| import 期呼叫 `ctypes.windll` | 有（`dialogs.py:35`） | **無**（改為 lazy + guarded） |
| 重複的 corrector id 會怎樣 | `ValueError`，整個附加元件在 import 時倒掉 | 記為 issue、保留第一筆，**永不拋例外** |
| `configManager.py` | 201 行 | **20 行**（只留 `CorrectorTaskConfig` / `load_corrector_task_config`） |
| 新增模型需要改的東西 | Python（`LABEL_DICT`）+ JSON | **只要 catalog 資料** |
| 新安裝的預設選擇 | `deepseek-v4-flash&DeepSeek` | **`default`**（由 Coseeing 伺服器決定模型） |

程式碼變動：24 個 commit、38 個檔案、+3718 / −482。

---

## 二、這批做了什麼

新增一個**只依賴標準函式庫**的 `lib/catalog/` 套件，擁有一個不可變的 `CorrectorCatalog`，由一份平坦文件（`schema_version` / `providers` / `models` / `coseeings`）建成。`BundledCatalogSource` 負責把今天的 `setting/ai/*.json`、`setting/provider/*.json`、`setting/price.json` 攤平成那份文件；未來的 `RemoteCatalogSource` 只要產出同樣形狀，所有 consumer 都不用動。

- **驗證逐筆進行、永不致命**：壞的項目被跳過並記成 `CatalogIssue`，`build_catalog()` 一定回傳 catalog。
- **降級階梯三級**：正常 / 降級（部分項目被丟棄）/ 空（改用內建 fallback，只有一個 id 為 `"default"` 的 Coseeing 項目）。fallback 走的是同一條 `build_catalog()`，不是第二條程式路徑。
- **`"default"` sentinel 同時也是日常預設值**，不只是災難路徑——這樣「災難路徑」就是每天都被走過的路徑。
- **`SettingsRepository`** 成為唯一接觸 `config.conf["WordBridge"]["settings"]` 的模組，`config.conf.spec` 的預設值因此可以變成靜態字串。
- **`lib/llm` 不再讀檔**：`get_provider()` / `get_provider_model_adapter()` 改為必填的 keyword 注入。
- **`ConfigManager` 與 `LABEL_DICT` 刪除**，catalog 由 `GlobalPlugin.__init__` 明確初始化。

---

## 三、Commit 清單（24 個，依時間順序）

| # | Commit | 說明 |
| --- | --- | --- |
| 1 | `9ffbf5a` | feat: add the corrector catalog data model and document validation |
| 2 | `4a30a57` | fix: never raise from build_catalog on malformed models, coseeings, or providers |
| 3 | `5531d34` | feat: flatten the shipped setting tree into a catalog document |
| 4 | `6d0defa` | fix: guard BundledCatalogSource against non-mapping JSON, pin group labels to the legacy oracle |
| 5 | `8b32bd5` | feat: add selection state, catalog fallback and the registry |
| 6 | `2883922` | fix: load_catalog exception safety and normalize_selection active-filtering |
| 7 | `87dedc3` | feat: inject provider and price entries instead of reading files |
| 8 | `9dbecce` | fix: match test_eval_provider_config.py's 4-space indentation |
| 9 | `bda135f` | feat: put every WordBridge setting behind one repository |
| 10 | `a2a6aa1` | fix: make the os-language probe tests actually falsifiable |
| 11 | `6d97ec3` | refactor: initialise the catalog explicitly instead of at import |
| 12 | `92446e2` | fix: total-catch the corrupt task config path and notify the user |
| 13 | `85db49e` | test: pin the GlobalPlugin.__init__ self._shutdown reorder |
| 14 | `d3e747c` | feat: ship the Coseeing default sentinel and drop the orphan provider |
| 15 | `06178ae` | test: cover the degraded-catalog announcement and its __init__ wiring |
| 16 | `d5e2da8` | test: prove the catalog source seam without implementing HTTP |
| 17 | `63d5503` | docs: record the catalog-decoupling completion report |
| 18 | `796b73b` | fix: make settings_repository's catalog import relative and gate it |
| 19 | `d9aa57c` | fix: close two containment holes in the catalog source seam |
| 20 | `30a6f45` | fix: surface catalog issues and provider/sentinel labels in the settings panel |
| 21 | `cacc685` | fix: three worker-thread robustness minors in correctTypo() |
| 22 | `5df2fb7` | chore: clean up remaining folded-in minors from the whole-branch review |
| 23 | `26beaa8` | fix: panel catalog-issue summary no longer flags lint-only issues |
| 24 | `fe38f06` | test: assert the import-purity file scan is non-empty |

Task 對應：1–2 → Task 1；3–4 → Task 2；5–6 → Task 3；7–8 → Task 4；9–10 → Task 5；11–13 → Task 6；14–15 → Task 7；16–17 → Task 8；18–24 → whole-branch review 的修正。

---

## 四、Review 抓到、值得你知道的問題

八個 task 各自通過 review，但**真正嚴重的一個是整支分支 review 才看到的**。

### 1. Critical — 附加元件在 NVDA 下根本載入不了（`796b73b` 修正）

`settings_repository.py` 用了絕對 import `from lib.catalog.selection import ...`，是整個附加元件裡唯一一處絕對內部 import。它之所以在測試裡能通過，是因為 `tests/conftest.py` 把附加元件目錄放上 `sys.path`；而 NVDA 載入時是以 `globalPlugins.WordBridge` 這個 package 形式載入，那個目錄**不在** `sys.path`，`lib/vendor.py` 也刻意從不動 `sys.path`。由於 `__init__.py` 與 `dialogs.py` 都在 module scope import 它，這是**整個附加元件的載入失敗**。

它在 Task 5 引入，八個 task-scoped gate 全部看不到，因為每個 gate 都照 `conftest.py` 的方式 bootstrap。缺的那道閘門（production 形狀的 import：以 package 方式載入、附加元件目錄不在 `sys.path`）已補上，另加一個 AST 掃描禁止任何內部絕對 import。

**這是這批最重要的流程教訓**：測試環境的 `sys.path` 比正式環境寬鬆，所以「測試全綠」無法證明能載入。

### 2. Important — spec 要求的面板 issue 摘要行從未實作（`30a6f45`、`26beaa8`）

spec 的 Visibility 段落列了三個管道：完整 log、**設定面板摘要行**、每 session 一次的語音公告。只有兩個存在，plan 也沒提到，所以沒有任何 task 負責。由於 `catalog.degraded` 只在「空」那一級為 True，降級階梯的第 2 級（唯一真的會發生的一級——「空」需要整棵樹都讀不到）對使用者**完全無聲**：一個壞掉的 `setting/ai/Google-*.json` 會默默從視障使用者的下拉選單移除一個模型，只在 NVDA log 留一行。

補上之後又發現它反過來製造了假警報（見第 6 點）。

### 3. Important — `ProviderEntry.label` 是 schema 必填卻無人讀取（`30a6f45`）

`document.py` 會拒絕沒有 `label` 的 provider 項目，但面板一直用原始的 provider key 當顯示文字。也就是 acceptance 6（「新增模型只要改資料，連 label 都不用改 Python」）對 model 成立、對 provider 不成立：遠端 payload 改不了 provider 的顯示名稱。已改為透過 `ProviderEntry.label` 渲染（`Coseeing` group 沒有 provider 項目，走原名 fallback）。今天畫面上的文字完全沒變，因為 Task 2 的 oracle 測試證明過每個出貨 provider 的 label 都等於它的 key。

### 4. Important — sentinel 標籤未翻譯，而它是每個新安裝的預設值（`30a6f45`）

`SENTINEL_LABEL = "Coseeing default"`。其他所有 catalog label 都是模型或品牌名的恆等翻譯，「不翻譯」沒有成本；這一個是英文句子片段，而且是**每個新 zh 使用者**在模型下拉選單裡聽到的第一個選項。已改為由面板以 `corrector_config_id` 為 key 做翻譯（對映留在 client 端，因此不會打開 spec 防守的「遠端 payload 改寫介面用字」那扇門）。catalog 資料維持純資料。

**注意**：這只是讓它「可翻譯」。實際文字在 `.po` 重新產生前仍是英文（見第五節）。

### 5. Important × 3 — 三次「測試全綠掩蓋壞掉的路徑」

這是這批反覆出現的失效模式，每次都由 reviewer 用實測證明（把那幾行刪掉、測試依然全綠）：

- 損壞的 `corrector.json` 仍會讓 plugin init 崩潰——fallback 的 `except` 漏接 `TypeError`（頂層是 array / string / number / null 時）。同時 spec 要求的「使用者可見訊息」只做了 log 那一半。
- `__init__` 若不再設定 `self.settings` / `self.correctorTaskConfig` / `self.catalog`，整組測試仍全綠，而正式路徑會在 worker thread 丟 `AttributeError`——因為七處測試夾具用 `object.__new__` 手動塞了這些屬性。
- 修正上一項所依賴的 `self._shutdown` 重排，本身沒有任何測試釘住；把它改回原位，91 個測試依然全綠而真實建構路徑會再次崩潰。

### 6. Important — 我的修正自己製造的回歸（`26beaa8`）

補上第 2 點的面板摘要行之後，它在**每個健康安裝**上都會朗讀「1 catalog entries could not be loaded」。原因是出貨 catalog 永遠帶著一個 lint 級 issue（`unreferenced_provider: OpenRouter`，`setting/provider/OpenRouter.json` 沒有任何 `ai/*.json` 指向它），但 `degraded=False`、15 個項目全部可選——什麼都沒有載入失敗。在螢幕閱讀器產品裡，這是每次開設定都會被唸出來的**不實常駐警報**，反而摧毀了這個需求本來要建立的訊號價值。

已改為只計算**真正被丟棄**的項目（spec 的驗證表本身就把 `unreferenced_provider` 標為「Legal. Lint-level issue only.」），log 仍保留全部 issue，並修正單複數文法。

---

## 五、尚未完成、需要人工處理的事

### 1. 翻譯檔（沒有 `scons`，此環境無法執行）

**更正一個常見誤解：這個 repo 裡沒有 `.pot` 檔**。實際存在的是三個已簽入的 `.po`：`addon/locale/{zh_CN,zh_HK,zh_TW}/LC_MESSAGES/nvda.po`。需要處理的是重新產生／合併這三個檔案。

需要補進去的新 msgid（請照字面 grep）：

- `"The bundled correction settings file is damaged; WordBridge is using its built-in defaults."`
- `"The model list could not be loaded. Coseeing will choose a model for you."`
- 面板的 catalog issue 摘要行（單數與複數兩個形式）
- `"Coseeing default"`（sentinel 標籤，第四節第 4 點）

**另外請注意**：這三個 `.po` 檔**在這批之前就已經**缺了至少十個 `__init__.py` 的使用者可見字串（例如 `"This task's cost is unavailable."`、`"The correction report could not be generated."`、`"Only one proofreading task can run at a time..."`）。所以重新合併不是「只加四五條」，而是一次補齊。

同時，model 與 provider 的顯示名稱**離開**了翻譯檔（它們現在是 catalog 資料）。這不是退步：我已逐一確認三個 `.po` 裡那些 msgid 全都是恆等翻譯（`msgid "Anthropic"` / `msgstr "Anthropic"`，`gemini-3.1-pro-preview` → `gemini-3.1-pro` 是改名而非翻譯）。

### 2. Windows / NVDA 實機驗證（這批完全沒做）

設定面板的 wx 接線只被 stub 覆蓋。建議照這個腳本手動走一遍：

1. 開設定面板；切換 provider group，確認模型清單重置到第一項；存檔；重開確認選擇留存。
2. 弄壞一個 `setting/ai/*.json`，確認**只有**那個模型消失、面板仍可開啟、且出現 issue 摘要行。
3. 清空 `setting/ai/`，確認面板只剩 `"Coseeing default"`，且第一次校正時公告一次（只有一次）。
4. 把 `setting/task/corrector.json` 改成 `null`，確認附加元件仍載入並唸出「內建預設值」訊息。

### 3. Coseeing 伺服器的外部契約

選 `"default"` 跑一次真實校正，確認伺服器接受這個裸 sentinel id。這是本 repo 任何測試都無法涵蓋的唯一外部契約（`server/` 目錄是空的）。

### 4. 需要你決定的 spec 矛盾（我刻意沒有動程式）

spec 說未來的 `RemoteCatalogSource` 是「`sources.py` 裡的一個新 class，consumer 不用改」。但 `lib/catalog` 的純標準庫規則（由 AST 測試把關）禁止 `requests` / `_wb_vendor`，而附加元件的 HTTP 是 vendored `requests`。

seam 本身沒問題——`load_catalog` 是 duck-typed，只透過 `source.load()` 接觸 source，所以 remote source 可以放在 `lib/catalog` **外面**而完全不動任何 consumer。但 spec 那句具體承諾照字面無法實現。這批的成本正是由那個未來證成的，所以值得你明確決定並寫回 spec：是放寬白名單、還是把 remote source 放在 `lib/catalog` 外。

### 5. 一個向後相容的細節，值得寫進 release note

acceptance 5 說「既有使用者的既存選擇不受影響」。對**曾經按過設定面板確定鍵**的人來說是對的。但從未按過的既有使用者沒有存過 `corrector_config_id`，空值現在會解析到 sentinel——他們會從 `deepseek-v4-flash&DeepSeek`（舊的 spec 預設）變成「由伺服器選模型」。同一個 channel、不同的模型。這是 spec decision 5 的本意，但範圍比「新安裝」更廣，而 spec 的 Risk 段與前一版完成報告都是用「新安裝」在描述它。

---

## 六、驗收條件逐條核對

| # | 條件 | 結果 |
| --- | --- | --- |
| 1 | import 期不讀 `setting/`、不呼叫 `windll` | ✅ `tests/test_import_purity.py`（audit hook 在 import 前安裝、路徑已正規化反斜線，所以在 Windows 上不會變成空測試） |
| 2 | 空的 `ai/` 仍能載入、開面板、提供 `"default"` | ✅ 資料層已驗（輸出 `True ['default']`）；「面板真的能開」僅以資料流推論，**未在真實 wx/NVDA 下開過**（見第五節） |
| 3 | 單一壞檔只移除那一筆 | ✅ 測試 + 對真實 `setting/` 複本的端到端檢查（15→14） |
| 4 | 出貨 catalog 選項與改動前相同，外加 sentinel | ⚠️ 無法用「現在可執行」的 oracle 證明——五個以 `ConfigManager` 為 oracle 的特徵化測試在 Task 6 隨 `ConfigManager` 一起刪除（我的裁定）。證據是它們刪除前確實全綠（Task 8 以暫時 worktree checkout `a2a6aa1` 重跑確認），加上現存的精確值測試 |
| 5 | `"default"` 是新安裝預設、既存選擇不動 | ✅ 但範圍比字面更廣，見第五節第 5 點 |
| 6 | 新增模型只需改資料 | ✅ 由 seam 測試直接證明（model 與 provider 皆成立，後者是第四節第 3 點修好的） |
| 7 | `lib/catalog` 只依賴標準函式庫 | ✅ AST 掃描（走語法樹，不是執行期觀察，所以「剛好沒執行到」的 import 也躲不過） |
| 8 | 非整合測試全綠 | ✅ 448 passed / 1 skipped / 16 deselected |

---

## 七、給下一批的流程建議

1. **加一個 production 形狀的 import 閘門**，而且從第一個 task 就加。本批唯一的 Critical 就是靠它才抓到，而它在測試環境裡隱形了四個 task。
2. **「刪掉這幾行、測試是否仍全綠」應該成為 reviewer 的標準動作**。這批三次靠它抓到綠燈掩蓋的壞路徑，一次抓到我自己修正造成的回歸。
3. **plan 直接給 verbatim 程式碼時，reviewer 要對照 spec 而不是對照 plan**。本批有四處 plan 給的程式碼違反 spec 的約束（`build_catalog` 會拋例外、`normalize_selection` 掉了 `active` 檢查、`import dialogs` 根本不能執行、`max_char_count` 夾值會掉失）。
