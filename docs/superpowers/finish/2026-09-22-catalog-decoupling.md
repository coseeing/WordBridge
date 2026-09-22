# Catalog decoupling — 完成報告

**分支：** `catalog-decoupling`
**Spec/Plan：** `.superpowers/sdd/2026-09-22-catalog-decoupling/`（task-1-brief.md … task-8-brief.md）
**執行方式：** 八個循序 task，逐一 TDD 實作；Task 8 是收尾：新增 seam test，並逐條核對 spec 的驗收條件。

---

## 一、這批分支做了什麼

新增 stdlib-only 的 `lib/catalog/`（`model.py`、`document.py`、`sources.py`、`selection.py`、`fallback.py`、`registry.py`），取代原本混在 `ConfigManager` 裡、匯入期就會讀檔的目錄型錄邏輯。`settings_repository.py` 收攏所有設定鍵；`lib/llm` 不再自己讀檔，改吃注入的 provider/price entry；`ConfigManager` 整個刪除；`dialogs.py`、`__init__.py` 重新接線，匯入期不再有任何副作用；`"default"` Coseeing sentinel 出貨並成為新安裝的預設選項，目錄退化（degraded）時整個 catalog 會退回只剩這一個 sentinel 選項，而不是讓附加元件掛掉。

Task 8 沒有新增任何生產程式碼——它只證明一件事：只要一個來源物件的 `load()` 回傳 `(document, issues)`，其餘的一切（provider 分組、可選項目、預設選擇、價格）都與來源是「本地檔案」還是「別的地方」無關。這個 seam 正是未來 `RemoteCatalogSource` 要對齊的契約。

## 二、新增檔案

- `tests/test_catalog_source_seam.py`（新建，逐字照抄 brief 的內容，僅移除 Markdown code fence）

沒有動到 `lib/catalog/`、`lib/llm`、`dialogs.py`、`__init__.py`、`settings_repository.py` 或任何其他生產程式碼。

## 三、Seam test 的第一次執行結果

```
$ python3 -m pytest tests/test_catalog_source_seam.py -q
....                                                                     [100%]
4 passed in 0.10s
```

四個測試**第一次執行就全數通過**，符合 brief 的預期：這不是 TDD 的紅燈階段，而是在證明既有設計的一個性質——`FakeRemoteCatalogSource`（無 HTTP、無快取、無重試，只回傳一個 dict 文件）餵給 `load_catalog()` 之後，產出的 `provider_groups`、`selectable_items`、`default_selection()`、每個 model 的 `price_entry()`，以及 `SelectionState.restore()` 得到的 `provider_group`/`current_item()`，全部與 `BundledCatalogSource` 讀真實檔案系統得到的結果逐位元相同；且往文件裡加一筆 model 或一個未實作的 provider，行為（新增選項可選、未支援的 provider 被降級只剩 Coseeing 分組並掛出 `unsupported_provider` issue）也與純資料變更一致，不需要改任何 Python 程式。

沒有任何斷言失敗，因此不需要停下來回報「seam 不成立」的發現。

## 四、驗收條件逐條核對

Spec 的八條驗收條件，逐條記錄實際輸出：

### 1. 匯入期不讀 `setting/` 下的檔案、不呼叫 `windll`

```
$ python3 -m pytest tests/test_import_purity.py -q
.                                                                        [100%]
1 passed in 0.46s
```

`tests/test_import_purity.py` 用 `sys.addaudithook` 監控 `open` 與 `ctypes.dlopen`/`ctypes.dlsym` 事件，透過 `importlib.util.spec_from_file_location` 把 `__init__.py`（連帶 `dialogs.py`）當成套件載入一次，斷言 `setting/` 路徑與 `CTYPES:` 事件清單皆為空。通過。

### 2. 空的 `setting/ai/` 目錄、或每個檔案都是壞 JSON，仍能載入附加元件、仍能開啟設定面板、仍提供 `"default"` Coseeing 選項

brief 指定的 scratch 腳本（用臨時空目錄）：

```
$ python3 - <<'PY'
import sys, tempfile, pathlib, json
sys.path.insert(0, "addon/globalPlugins/WordBridge")
from lib.catalog.fallback import load_catalog
from lib.catalog.sources import BundledCatalogSource
from lib.llm import SUPPORTED_PROVIDERS
root = pathlib.Path(tempfile.mkdtemp())
(root / "ai").mkdir(); (root / "provider").mkdir()
(root / "price.json").write_text("{}")
catalog = load_catalog(BundledCatalogSource(root), runnable_providers=SUPPORTED_PROVIDERS)
print(catalog.degraded, [item.corrector_config_id for item in catalog.selectable_items])
PY
True ['default']
```

與 brief 預期的 `True ['default']`逐字相符——「載入不掛」與「提供 default」兩項證實。

「仍能開啟設定面板」這一項再往前一步驗證：`dialogs.LLMSettingsPanel.makeSettings()` 只從 `self.catalog.provider_groups`、`self.catalog.labels_for(group)`、`SelectionState.restore(...).provider_group_index/model_index/current_item()` 取資料去餵 `wx.Choice`。用同一個退化 catalog 直接呼叫這幾個方法：

```
provider_groups: ['Coseeing']
provider choice index: 0
labels for selection.provider_group: ['Coseeing default']
model choice index: 0
current_item: SelectableItem(provider_group='Coseeing', corrector_config_id='default', execution_channel='Coseeing', label='Coseeing default')
```

面板會讀到的每一個值都非空、索引都在界內，資料面沒有問題。但這**不等於**在真的 wx/NVDA 環境下實際開啟過面板——現有的 `makeSettings()` 測試（`tests/test_coseeing_auth_nvda.py`）用的是健康的 catalog，本專案沒有任何測試把退化 catalog 接上 wx stub 去跑 `makeSettings()`，真正的 GUI 也只在 stub 下測過。這一段留在下方「無法在此驗證的項目」。

「single 壞檔只移除該筆」在條件 3 一併驗證。

### 3. 單一 `setting/ai/*.json` 壞檔，只移除那一筆

現有 pinned test：

```
$ python3 -m pytest tests/test_catalog_bundled.py::test_a_corrupt_ai_file_is_reported_and_skipped -q
.                                                                        [100%]
1 passed in 0.05s
```

額外用真實出貨的 `setting/` 目錄複製一份做端對端驗證（把其中一個 `ai/*.json` 改成壞 JSON，其餘不動）：

```
target file: Anthropic-00001-claude-opus-5.json
baseline count: 15 degraded count: 14
removed entries: {'claude-opus-5&Anthropic'}
degraded flag: False
issue codes: {'unreferenced_provider', 'unreadable_file'}
```

只少了被弄壞的那一筆（15 → 14），`degraded` 仍是 `False`（整體目錄仍可用，只是有一筆讀不到），`unreadable_file` issue 記錄了原因。符合條件。

### 4. 出貨的 catalog 產出的可選項目與變更前完全一致（加上新 sentinel）

這條**現在無法用一個可執行的 oracle 直接比對**——把 `ConfigManager` 當 oracle 用的五個 characterization test 在 Task 6（commit `6d97ec3`）連同 `ConfigManager` 一起刪除，這是刻意的 controller 裁決，理由是「留著它們只會保證 `ConfigManager` 消失後測試變紅」，它們的任務在當時跑過就已經完成。

用 git 歷史補上證據：checkout `ConfigManager` 被刪除前的最後一個 commit（`a2a6aa1`，`6d97ec3` 的父提交）到獨立 worktree，重跑那五個 oracle test：

```
$ git worktree add --detach <scratch>/wt-verify a2a6aa1
$ python3 -m pytest tests/test_catalog_bundled.py -q -k "legacy_manager"
.....                                                                    [100%]
5 passed, 9 deselected in 0.05s
```

（worktree 事後已用 `git worktree remove --force` 清掉，未影響主 repo。）

五個測試在刪除 `ConfigManager` 前確實全綠：
`test_provider_groups_match_the_legacy_manager`
`test_every_group_offers_the_same_labels_as_the_legacy_manager`
`test_every_provider_group_label_matches_the_legacy_manager`
`test_every_selectable_item_matches_the_legacy_manager`
`test_default_selection_matches_the_legacy_manager`

再加上現存的 exact-value 測試（`tests/test_catalog_bundled.py`、`tests/test_ai_config_schema.py` 等）目前仍然對出貨資料釘住具體數值並持續通過。

**如實陳述：** 條件 4 由「Task 6 之前的 git 歷史（此刻可重現）＋現存的 exact-value 測試」共同佐證，不是由一個目前可執行的比對指令直接證明。這與 brief 正文「這是刻意的 controller 裁決」的說法一致，我沒有嘗試恢復或改寫這五個已刪除的測試。

### 5. `"default"` 是新安裝的預設選擇；既有使用者的已存選擇不受影響

```
$ python3 -m pytest tests/test_settings_repository.py::test_an_empty_stored_selection_resolves_to_the_catalog_default tests/test_settings_repository.py::test_a_stored_selection_is_honoured -q
..                                                                       [100%]
2 passed in 0.02s
```

`test_an_empty_stored_selection_resolves_to_the_catalog_default` 斷言空 `corrector_config_id` 解析為 `("default", COSEEING_GROUP)`；`test_a_stored_selection_is_honoured` 斷言非空的已存值（`"gpt-x&OpenAI"`, `"local"`）原封不動地被採用，不會被 sentinel 覆蓋。兩者合起來正是條件 5 的兩半。

### 6. 幫既有 provider family 加一個 model，只需要改 catalog 資料，不需要改 Python（包括不需要改 label）

由 seam test 本身的 `test_a_remote_document_can_add_a_model_with_no_code_change` 證明：只透過改動記憶體中的文件字典（等同改資料，未動任何 `.py`），新增一筆 OpenAI model 連同其自帶 label（`"GPT 9 Future"`），重新 `load_catalog()` 之後該 label 就出現在 `catalog.labels_for("OpenAI")`，且 `catalog.get_model("gpt-9-future&OpenAI").price_entry()` 讀得到剛剛餵進去的定價。已在第三節的 4 個測試通過紀錄中涵蓋。

### 7. `lib/catalog` 只匯入標準函式庫

```
$ python3 -m pytest tests/test_catalog_document.py::test_the_catalog_package_imports_only_the_standard_library -q
.                                                                        [100%]
1 passed in 0.03s
```

此測試用 `ast.walk` 靜態分析 `lib/catalog/*.py` 的每一個 `Import`/`ImportFrom` 節點（`node.level` 非零，即相對匯入，會被跳過），確保每個匯入的頂層模組都落在 `STDLIB_ONLY` 集合裡——是靜態檢查，不是只看執行期真的跑到什麼分支。

### 8. 完整非 integration 測試綠燈

```
$ python3 -m pytest -q -m "not integration"
435 passed, 1 skipped, 16 deselected in 12.32s
```

Task 8 之前的基準是 `431 passed, 1 skipped, 16 deselected`；新增的 `tests/test_catalog_source_seam.py` 四個測試通過後變成 `435 passed`，其餘計數不變，輸出乾淨（無 warning）。

## 五、無法在此驗證的項目

- **`.pot`／`.po`（更正 brief 原文的說法）。** 本機沒有 `scons`，翻譯字典從未重新產生。Brief 的 Step 5 原文寫「`.pot` was never regenerated」，但這個 repo 裡**根本沒有 `.pot` 檔**——實際存在的是三個已提交的 `.po` 檔：`addon/locale/{zh_CN,zh_HK,zh_TW}/LC_MESSAGES/nvda.po`。這三個檔案目前仍然帶著已經孤兒化的 model/provider msgid（例如 `Anthropic`、`OpenAI`、`gemini-3.1-pro`、`gpt-5.6-sol`——這些字串在 Task 6 之後已經不再透過 `_()`，因為它們現在是純資料，直接來自 catalog），而且**還沒有**這批新增的兩則 UI 字串：degraded-catalog 通知（`"The model list could not be loaded. Coseeing will choose a model for you."`）與損毀 task config 的訊息。待辦是重新產生／合併這三個 `.po` 檔。
- **Windows / NVDA 實機。** 這整批分支沒有在 Windows 或真正的 NVDA 下跑過。設定面板的 wx 接線只被 stub 測過（見第四節條件 2）；需要有人手動開啟面板、切換 provider、選 model、儲存、重開後確認選擇有留住。
- **degraded-catalog 通知與 sentinel 的端對端行為。** 需要一次真正的 Coseeing 往返：選 `"default"` 選項、跑一次校正、確認伺服器接受這個 sentinel id。本機沒有網路對接的環境可以做這件事。

## 六、Commit

```
test: prove the catalog source seam without implementing HTTP
```

（僅新增 `tests/test_catalog_source_seam.py`，本報告另外用 `git add -f` 提交，因為 `docs/` 在 `.gitignore` 內。）
