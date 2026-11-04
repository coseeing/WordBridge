# Remote provider/model catalog — 最終審閱（DEVELOPMENT_WORKFLOW.md §3.3）

- **分支**：`feat/remote-catalog`（自 `main` @ `774560b` 開出），審閱範圍 `774560b..9081560`（26 個 commit）
- **Spec**：`docs/superpowers/specs/2026-11-04-remote-catalog-design.md`（使用者決定 U1–U9；OQ1→B、OQ2→B、OQ3→D）
- **Plan**：`docs/superpowers/plans/2026-11-04-remote-catalog.md`（16 個 task，三批）
- **進度帳本**：`.superpowers/sdd/2026-11-04-remote-catalog/progress.md`
- **審閱者**：Fable 5.1，只讀程式碼，不修改原始碼；突變測試在拋棄式 worktree 進行（`git worktree add --detach <scratchpad>/fable-rv 9081560`，審閱後已 `git worktree remove`）
- **日期**：2026-11-04
- 路徑若無前綴，相對於 `addon/globalPlugins/WordBridge/`。

---

## 一、總評

**可以在修完 1 個 Important 之後合併。** 沒有 Critical。

- 兩套測試在 HEAD 都是綠的（附加元件 719 passed / 1 skipped，伺服器 96 passed），`prek` 全部 Passed，`git diff --check` 乾淨，`msgfmt --check` 通過，沒有 `Co-Authored-By`，沒有 stray file，`storage` symlink 未被追蹤。
- 批次 3（Task 11–16）沒有做過批次 review，所以我做了 34 個突變，**全部被測試抓到**（表三）；另外 2 個針對帳本延後 Minor 的突變存活（表三 M35、M36），列為 Minor。
- 使用者決定 U1–U9 逐一核對都落地了（§二之 4）。plan 的 Review Focus 五項都有對應測試且通過。
- 唯一的 Important 是 D12 和批次 3 第 2 個 Ruling（簽入用 stored channel）**合起來**造成的回歸：**全新安裝**的使用者打開設定面板、什麼都沒改就按「確定」，`main` 上會把 `(default, Coseeing)` 寫進設定並啟動非靜默的 Coseeing 登入流程；這支分支上什麼都不寫、也不登入。我用一個探針測試在 `774560b` 和 `9081560` 各跑一次證實了差異（表三 P1）。修法只要一行，另加一個測試。
- 帳本延後的 Minor 我逐條重新評估並親自驗證（§四），大多仍成立；其中「遠端字串未經轉義就寫進記錄」我用一個假的 provider 名稱做出了偽造的「catalog fetched」記錄行（表三 M38），屬於安全相關、修法便宜，建議在合併前修。

---

## 二、審閱重點逐項

### 1. 正確性與相對 `main` 的回歸

- `correctTypo()` 改為一次快照（`__init__.py:549-575`），`SettingsRepository.corrector_selection(catalog=…)`；突變 M33（改回重讀 registry）被抓到。
- `registry.replace()` 只在主執行緒（`_install_catalog`）呼叫；`_run_on_ui` 在 shutdown 後丟棄 callback，維持原行為。
- `terminate()` 把 fetch thread 加進 `workers`，`catalog_updater.uninstall()` 在 `finally` 內自成一個 `try`（R02 不丟例外的規則沿用）。突變 M09 被抓到。
- 伺服器端：`resolve_model()` 的 Coseeing 供應清單改讀 `COSEEING_MODEL_IDS`，既有兩個測試意義不變；`GET /` 逐位元組回傳檔案。
- **回歸**：見 Important I1（全新安裝的面板「確定」）。這是 `main` 上有、分支上沒有的行為。
- 其他 `main` 行為（退化宣告、面板的「N 個目錄項目無法載入」、Coseeing 路徑、報告、字典）沒有改變；既有測試 460 個都還在而且通過。

### 2. Spec 符合度（含每個使用者決定）

| 決定 | 落地位置 | 結果 |
| --- | --- | --- |
| U1 只用快取、不出貨快照 | `lib/catalog/overlay.py:23-28`（bundled 的 providers/models 一律忽略）、`cache.py` | ✅ 結構性保證；突變 M30 被抓到 |
| U2 provider host allowlist | `lib/catalog/remote.py:142-207` | ✅ 六家 provider 都有規則；`set(PROVIDER_URL_RULES) == SUPPORTED_PROVIDERS` 有測試；我另做了 20 個 URL 的「`urlsplit` vs `requests`」差異探針（表三 D1），沒有一個 URL 能通過 allowlist 卻被 `requests` 送到別的 host |
| U3 只在啟動後與改網址後各抓一次 | `__init__.py:229`（`wx.CallAfter(self._start_catalog_fetch)`）、`dialogs.py:405-408` | ✅ 沒有定時器、沒有按鈕；突變 M12（每次儲存都抓）被抓到 |
| U4 目標檔案 | `setting/catalog.json`、`server/app/setting/catalog.json` | ✅ 帳本記錄 `cmp` 逐位元組相同；附加元件檔只有 `schema_version` 與一個 sentinel；伺服器檔沒有 `coseeings` |
| U5 OQ1→B | `server/app/correction_config.py:21-27, 61-78` | ✅ 預設 `deepseek-flash&DeepSeek,gpt-6-luna&OpenAI`；不在 `GET /` 內（`test_the_served_payload_is_a_schema_1_object_with_local_data`）；突變 M17、M18 被抓到 |
| U6 OQ2→B | `lib/catalog/selection.py:26-29` | ✅ stored Coseeing 絕不移到 local；突變 M01 被抓到（5 個測試） |
| U7 OQ3→D | `__init__.py:285-345, 549-561, 775-780` | ✅ 見下一節逐條核對 |
| U8 Coseeing 群組只有 `default` | `setting/catalog.json` | ✅ `labels_for("Coseeing") == ("default",)` 有測試 |
| U9 無效網址有自己的狀態列 | `catalog_updater.py:102-104, 124-127`、`dialogs.py:77-79` | ✅ `fetch=invalid` 第五個狀態；突變 M14 被抓到 |
| D12 不覆寫無法解析的 stored selection | `dialogs.py:133-141, 376-389` | ✅ 功能正確（突變 M10、M11 被抓到），但對「什麼都沒存」的全新安裝副作用見 I1 |
| D15 記錄只有 scheme/host/port、例外只記型別 | `catalog_updater.py:286-305`、`remote.py:109-124` | ✅ 突變 M24（記 `str(error)`）被抓到；遠端字串未轉義的問題見 m1 |
| §12.5 對話框 | `__init__.py:302-345` | ✅ 標題 `_("WordBridge")`、訊息兩段、`DefaultButtonSet.YES_NO`、`setDefaultFocus(NO)`、`SetEscapeId(NO)`、`ShowModal()` 後重查 `_shutdown`；Yes 寫 `("default","Coseeing")` 再 `startCorrection(text)`；其他答案只講取消句。突變 M03–M05、M08 都被抓到 |
| §13.3 狀態列六列 | `dialogs.py:64-92` | ✅ 表格測試七列（含兩個 None 列） |
| §13.2 網址欄位最後一個、`isValid()` 用 NVDA 的 `_validationErrorMessageBox` | `dialogs.py:305-316, 354-374` | ✅；突變 M15（驗證失敗仍回 True）被抓到 |
| §14 `GET /` | `server/app/main.py:43-62, 164-171` | ✅ `application/json`、`Cache-Control: no-cache`、不需登入；啟動時 fail-loud；突變 M19、M20 被抓到 |

**§12.5 / U7 逐條**（對照 `tests/test_catalog_plugin_wiring.py:333-542`）：

- 預設焦點 No ✅、Escape 等於 No ✅（NVDA 的 `DefaultButton.NO` 是 `closesDialog=True`，`SetEscapeId(NO)` 合法：`/workspace/nvda/source/gui/message.py:296-352, 712`）。
- Yes：先 `save_corrector_selection("default", "Coseeing")` 再 `startCorrection(text)`，校正走 Coseeing 路徑自己取 token ✅。
- No / Escape / 關閉：什麼都不送、stored 不變、講「未傳送文字，模型選擇維持不變。」✅（`test_no_sends_nothing_and_keeps_the_stored_selection` 含 `CANCEL` 參數）。
- 啟動時不替這種使用者做 Coseeing 登入 ✅（`__init__.py:221-226`；三種情況 empty / no-cache / invalid 都有測試；突變 M06 四個測試失敗）。
- 對話框開著時第二次 NVDA+Alt+O 被忽略 ✅（flag 在 `script_correction` 就設，比 spec 說的「ShowModal 前」更早，更安全）。
- `correctTypo()` 的防線（Ruling）✅，突變 M07 被抓到。
- 對話框 parent 用 `gui.mainFrame`：這是 NVDA 自己的用法（`/workspace/nvda/source/updateCheck.py:1005`、`gui/installerGui.py:219`），不算問題，但焦點回到原文件的行為只能在 Windows 驗（§六）。

**Spec 的刻意偏離**（都記在帳本為 `Ruling:`）：批次 3 Ruling 2（未動選單的儲存，登入用 stored channel 而不是 spec §12.3 說的 effective channel）對 U7 使用者是必要的——否則離線沒快取的本機模型使用者只是改個語言就會被拉去 Coseeing 登入——**但對全新安裝（stored 為 `("","")`）它和 D12 一起把 `main` 的行為改掉了**，見 I1。其餘 Ruling 的評估見 §五。

### 3. 執行緒與鎖

- `CatalogUpdater`：`initial_catalog()`、`refresh()`、`_apply()` 都在 wx 主執行緒；`_run()` 在 daemon thread。鎖只保護 generation、`_live_key`、`_source`、`_fetch`，鎖內沒有 I/O、沒有 callback；快取寫入在鎖外（`catalog_updater.py:270-278`）。沒有巢狀鎖，沒有鎖順序問題。
- generation：`refresh()` 對空網址或無效網址也會遞增 generation，所以切到空網址會丟掉進行中的 fetch（帳本 I-3 的測試 `test_switching_to_an_empty_url_discards_the_in_flight_fetch`）。突變 M21（`_apply` 不查 generation）、M23（D8 不即時安裝）都被抓到。A→B→A（Review Focus 5）有測試。
- shutdown：`_is_current()` 同時查 `_shutdown` 與 generation；`_run_on_ui` 在 shutdown 後丟 callback；`terminate()` 在 `TERMINATE_WAIT_SECONDS` 內 join 最新的 fetch thread，卡在 socket read 的 thread 被放棄（daemon）。`test_a_fetch_finishing_after_terminate_writes_and_posts_nothing` 證明 `updater._shutdown is instance._shutdown`。
- 設定面板開著時發生 swap：面板在 `makeSettings` 取一次 `registry.current()` 與 `catalog_updater.status()`，之後不重建控制項（D9）；`onSave` 用快照的 `SelectionState`，id 在每次讀取時重新解析，所以仍有效；`request_refresh` 用 `wx.CallAfter` 延到儲存序列之後。沒有找到競爭。
- U7 對話框：`script_correction` 在主執行緒（NVDA 的 script 由主執行緒派發），`_ask_switch_to_coseeing` 經 `wx.CallAfter` 也在主執行緒，`_catalog_choice_pending` 只在主執行緒讀寫；`correctTypo()` 在 worker thread 呼叫 `_needs_catalog_choice()` 只讀 `status()`（有鎖）和 config。`ShowModal()` 的巢狀事件迴圈可能跑 `terminate()` 或 `_apply()`——前者有重查（突變 M08 被抓到），後者見 m7。
- `_catalog_http_get` 每次呼叫才查 `requests.get`，用的是 NVDA host 的 `requests`；`raw.read1(amt, decode_content=True)` 需要 urllib3 ≥ 2.0——NVDA 的 `uv.lock` 鎖定 urllib3 2.8.0，`buildVars.py:39` 最低 NVDA 2026.1，所以沒問題；測試 venv 也是 2.8.0。

### 4. 安全（U2、D5、D15）

- allowlist 用 `urlsplit().hostname`，`requests` 用 urllib3 的 `parse_url`。我拿 20 個敵意 URL（tab、換行、前導 C0、ESC、反斜線、`#@`、`?@`、中括號、`%00`、全形字、IDNA 句號、`@` userinfo、三斜線…）同時餵兩邊（表三 D1）：**每一個被 allowlist 放行的 URL，`requests` 要嘛送到正確的 host、要嘛直接拒絕**，沒有「放行但送到別處」的情形。Python 3.13 的 `urlsplit` 會對 `[api.openai.com]` 這種假 IPv6 丟 `ValueError`，已涵蓋。
- 殘留問題（都是 Minor）：含 tab / 換行 / 前導 `\x01` 的 URL 會通過 allowlist 進到 `ProviderEntry`（m2）；遠端來的字串（provider 名、host、issue detail）未轉義就寫進 NVDA 記錄，可以偽造記錄行（m1）。
- 網址驗證 `validate_catalog_url`：Review Focus 1（全形冒號、U+3000）有測試；`#` 直接拒絕；userinfo 拒絕；http 只准 loopback（突變 M27、M28 被抓到）。
- 記錄：`redact_url` 只留 scheme/host/port；失敗只記例外型別；`test_logs_never_contain_path_query_or_error_text` 存在；突變 M24 被抓到。
- 快取：以 `url_key` 綁定（突變 M29 被抓到）；只在 `NVDAState.shouldWriteToDisk()` 為真時寫；測試 harness 強制不可寫。
- 附帶發現（**既有問題，不在本分支範圍**）：`lib/llm/provider.py:88, 122` 的 `log.error(... {e})` 會把 `requests` 例外的完整文字寫進記錄，而 `ConnectionError` 的文字含完整 URL——Google 的 API key 在 URL query 裡（`provider.py:173`）。這在 `main` 就存在，建議另開簡化流程處理。

### 5. 測試是否真的抓得到（突變測試）

在拋棄式 worktree 做了 36 個突變（表三），**34 個被抓到、2 個存活**（M35、M36，都是帳本已列出的延後 Minor，對應 m4、m5）。批次 3 的所有關鍵判斷（U6 規則、U7 的七個分支、D12 兩個分支、網址身分比較、狀態列、`isValid`、伺服器 id 清單與空環境變數、`Cache-Control`、schema 檢查）各有至少一個突變被抓到。

### 6. plan 的 Review Focus

| # | 項目 | 測試 | 結果 |
| --- | --- | --- | --- |
| 1 | IME 全形冒號 / U+3000 | `tests/test_catalog_remote_url.py` 的 `fullwidth-colon`、`ideographic-space-padded`、`ideographic-space-inside` 三列 | ✅ 存在、通過 |
| 2 | provider `url` 不是字串 | `tests/test_catalog_provider_allowlist.py` 的 `url-int`、`url-list` | ✅ |
| 3 | UTF-8 BOM | `tests/test_catalog_payload.py` 的 `utf8-bom` 與 `test_a_bom_payload_parses_to_the_same_document` | ✅ |
| 4 | 不可用的 `Content-Length` 與空 chunk | `test_unusable_content_length_falls_back_to_the_streamed_limit`、`test_an_empty_read_ends_the_body`（依 Ruling 改名，因為改用 `read1()` 後空讀取就是 EOF）、另加 `test_a_dripping_server_times_out_at_the_deadline` 三列 | ✅ Ruling 合理 |
| 5 | A→B→A | `test_url_changed_back_before_fetches_complete_installs_only_the_last` | ✅ |

### 7. 翻譯

`addon/locale/zh_TW/LC_MESSAGES/nvda.po` 新增 12 條，與 spec §13.4 的建議譯文逐字相同，`msgfmt --check` 通過。用詞和既有介面一致：「預設」（`nvda.po:45-46`）、「模型清單」（`nvda.po:201-203`）、「NVDA 記錄」（`nvda.po:58`）。每個新 `_()` 都有 `# Translators:` 註解。語句自然，沒有需要改的地方。兩個小瑕疵列在 m14。

### 8. git / 流程限制

- 26 個 commit 都是 `<type>: <summary>` 英文訊息且有說明原因的內文；沒有 `Co-Authored-By`；最大的一個是 Task 10（505/356 行，含 42 個測試遷移，plan 本來就這樣排）。
- `git diff --check 774560b..HEAD` 乾淨；變更只落在 `addon/`、`tests/`、`server/`、`docs/`、`workspace/`；`server/app/package/coseeing_auth/storage` 仍是未追蹤的 symlink。
- 每個 commit 都綠：我在批次 3 抽查了 `a1b0fe6`（696/1）與 `d258e36`（719/1），與帳本記錄一致。
- `tests/test_catalog_document.py:287` 的 `STDLIB_ONLY` 恰好多了 `urllib`、`os`、`tempfile`；`catalog_updater` 已加進 `test_import_purity.py`。
- `TEMPORARY_LINT_CODES` 在 Task 16 已全部移除（grep 為 0）。

---

## 三、發現

### Critical

無。

### Important

#### I1. 全新安裝的使用者在設定面板按「確定」不再寫入預設選擇、也不再啟動 Coseeing 登入（相對 `main` 的回歸）

- **位置**：`dialogs.py:139`（`self._storedSelectionResolved = resolved == self._storedSelection`）、`dialogs.py:381-389`（`onSave` 的 D12 分支與 `signInChannel = self._storedSelection[1]`）。
- **情境**：全新安裝，`nvda.ini` 沒有 `corrector_config_id` / `execution_channel`（stored 為 `("", "")`）。使用者打開 WordBridge 設定，看到預設的「Coseeing / 預設」，直接按「確定」（或只改語言）。
  - `main`（`774560b`）：寫入 `("default", "Coseeing")`，並 `start_coseeing_auth("Coseeing", silent=False)`——這是全新使用者**唯一**會被互動式詢問 Coseeing 登入的地方（校正路徑的 `get_coseeing_access_token()` 用 `silent=None`，沒看過 refresh token 時就是靜默的 guest，`lib/coseeing_auth.py:684-686`）。
  - 分支：`("", "")` 解析成 `("default", "Coseeing")`，所以 `_storedSelectionResolved` 為 `False`；使用者沒動下拉選單，於是 D12 跳過儲存；Ruling 2 讓 `signInChannel = ""`，`start_coseeing_auth("")` 直接返回（`lib/coseeing_auth.py:717`）。**什麼都沒存、沒有登入提示**，使用者一直以 guest 身分使用而不自知。
  - 探針（表三 P1）：同一個測試在 `774560b` 得到 `stored=('default','Coseeing') auth_calls=['Coseeing']`，在 `9081560` 得到 `stored=('','') auth_calls=[]`。
- **原因**：D12 要保護的是「存了一個目前目錄解析不到的模型」，全新安裝沒有東西可保護；但實作把「沒存」和「存了但解析不到」一視同仁。
- **建議修法**（一行 + 一個測試）：只有「真的存了東西」才算未解析——
  `self._storedSelectionResolved = resolved == self._storedSelection or self._storedSelection == ("", "")`
  （或 `not any(self._storedSelection)`）。測試：以 `_panel_settings()` 預設值建面板、不動任何控制項 `onSave()`、跑完 queued callback，斷言 stored 變成 `("default", "Coseeing")` 且 `auth_calls == ["Coseeing"]`（就是表三 P1 的探針）。同時確認 `test_an_unresolved_stored_selection_survives_an_untouched_save` 仍通過。
- **錯了的代價**：不修的話，每個新使用者都要自己去動一次模型選單才會被問要不要登入 Coseeing；也會讓 `nvda.ini` 永遠停在空值（無害但和 `main` 不同）。

### Minor

依建議處理順序排列；m1–m3 是安全相關、修法便宜，建議合併前修。帳本編號以「B1-n」「B2-n」標示（批次 1 / 批次 2 延後的 Minor）。

#### m1. 遠端來的字串未轉義、未截斷就寫進 NVDA 記錄（B2-1，我判定仍為 Minor 但建議合併前修）

- **位置**：`__init__.py:352-357`（`_log_catalog_issues` 用 `%s` 記 `issue.location` 與 `issue.detail`）、`catalog_updater.py:233-235, 302-305`、`lib/catalog/remote.py:204`（`f"providers.{name}"`、`host {host}`）、`lib/catalog/document.py:104-129`（這些用了 `!r`，有轉義但無長度上限）。
- **情境**：自架或被竄改的目錄把 provider 名稱設成 `"Evil\nWordBridge: catalog fetched host=https://fake\x1b[0m"`。實測（表三 M38）`CatalogIssue.location` 和 `detail` 原樣帶著換行與 ESC；寫進記錄後 NVDA 記錄檢視器會出現一行假的「catalog fetched host=https://fake」。provider 名稱長度沒有上限（最多 1 MiB）。
- **建議修法**：在記錄的那幾行改用 `%r`（或在 `CatalogIssue` 建立時 `repr()` 並截到約 200 字元）。`document.py` 的 `!r` 已轉義，只需加截斷。一個測試：provider 名稱含 `\n` 與 `\x1b`，斷言記錄參數裡沒有裸換行。

#### m2. 含 tab / 換行 / 前導 C0 的 provider URL 會通過 allowlist（B1-2）

- **位置**：`lib/catalog/remote.py:156-179`（`_url_problem`）。
- **情境**：payload 的 OpenAI `url` 是 `"https://api.openai.com\t/v1"`。`urlsplit` 會把 `\t\r\n` 和前導 C0 去掉再解析，所以 hostname 是 `api.openai.com`、被放行；但 `ProviderEntry.url` 保留原字串，使用者選了這個模型後 `requests` 直接丟 `InvalidURL: Failed to parse: Host 'api.openai.com\t' contains invalid character`（表三 D1 實測）。結果是「模型看得到、每次都失敗、訊息看不懂」。以 urllib3 2.8 的訊息來看**不會**洩漏 Google 的 key（訊息只含 host），所以我把批次 1 reviewer 的「HIGH」下修為 Minor；但 §二之 4 提到的既有 `provider.py` 記錄問題讓這類 URL 的風險比純功能問題高一點。
- **建議修法**：在 `_url_problem` 加上和 `validate_catalog_url` 一樣的 `any(ch.isspace() or not ch.isprintable() for ch in url)` 檢查，並補 B1-4 的敵意列（tab、前導 `\x01`、trailing dot、`localhost.evil.com`、Ollama `[::1]`、`//host`、`\@`、`%2e`——後六個我已實測都被擋下，加進表格即可）。

#### m3. `redact_url(bytes)` 會丟 `TypeError`，違反「never raises」（B1-1）

- **位置**：`lib/catalog/remote.py:109-124`（`except` 只包住 `_split`，`_host_text(parts.hostname)` 在外面；`urlsplit(b"…")` 回傳 bytes hostname）。
- **情境**：目前所有呼叫端都傳 `check.url`（必為 str），所以是潛在問題；實測 `redact_url(b"https://x")` 丟 `TypeError`。
- **建議修法**：函式開頭 `if not isinstance(url, str): return _INVALID_REDACTED`，並把 `None`、bytes 加進 `test_redact_url`。

#### m4. 沒有測試釘住「快取用 `check.key` 而不是 `check.url` 存」（B2-3）

- **位置**：`catalog_updater.py:276`。
- **情境**：突變 M35（`store(check.url, …)`）**存活**（61 passed）。這個突變在正式環境是嚴重錯誤：預設網址的 key 是 `https://wordbridge.coseeing.org/`（補了 `/`），`url` 是沒有斜線的原文，存錯 key 的話下次啟動 `load(key)` 永遠不中，快取形同不存在。
- **建議修法**：在 `tests/test_catalog_updater.py` 的成功 refresh 測試斷言 `cache.load(check.key)` 回傳該文件，而且用 `DEFAULT_CATALOG_URL`（或大寫 host）當輸入，讓 `url != key`。

#### m5. 沒有測試釘住 `CatalogCache.load()` 的有界讀取（B2-5）

- **位置**：`lib/catalog/cache.py:44`。
- **情境**：突變 M36（`handle.read()`）存活；大小檢查仍會拒絕超大檔，只是主執行緒會把整個檔讀進記憶體。
- **建議修法**：用 spy 斷言 `read(MAX_CACHE_BYTES + 1)` 被呼叫。

#### m6. `schema_version` 為 `1.0` 或 `true` 會被接受（B1-8）

- **位置**：`lib/catalog/remote.py:225`（`version != SCHEMA_VERSION`，Python 的 `1.0 == 1`、`True == 1`）。實測兩者都回 `()`。
- **情境**：一個把版本寫成浮點數的自架目錄被接受，與「必須是 1」的 spec 字面不符；無安全影響。
- **建議修法**：`type(version) is not int or version != SCHEMA_VERSION`；表格加兩列。

#### m7. U7 對話框開著時模型清單到了，按 Yes 仍會把設定改成 Coseeing

- **位置**：`__init__.py:327-336`。
- **情境**：升級後第一次啟動，使用者在第一秒內按 NVDA+Alt+O，對話框跳出；fetch 在對話框開著的巢狀事件迴圈裡完成並安裝了目錄（`_apply` 也是 CallAfter）。使用者讀完訊息按 Yes——此時他選的本機模型其實已經可用，但設定仍被改成 Coseeing 預設、文字送去 Coseeing。spec §12.5 沒有要求重查，所以這不違反 spec，但第一秒視窗正是 U7 最常觸發的情境。
- **建議修法**：`ShowModal()` 回來後先 `if not self._needs_catalog_choice(): self.startCorrection(text); return`（清單已到就直接用使用者自己的模型，不改設定），再處理 Yes/No。加一個測試：`FakeMessageDialog.on_show` 裡 `_install_catalog(…)` 把 source 換成 fetched，Yes 之後 stored 不變、`started == ["原文"]`。

#### m8. 含孤立代理字元（lone surrogate）的 payload 永遠寫不進快取（B1-6）

- **位置**：`lib/catalog/cache.py:76-82`（`ensure_ascii=False` 再 `.encode("utf8")`）。
- **情境**：伺服器 JSON 裡的 `"\ud800"` 跳脫序列會被 `json.loads` 變成孤立代理字元，`encode("utf8")` 丟 `UnicodeEncodeError` → `cache_write_failed`；目錄仍會安裝，只是每次啟動都要重抓。
- **建議修法**：改用 `ensure_ascii=True`（跳脫後可往返），或在 `check_remote_document` 拒絕含代理字元的字串。

#### m9. 快取問題的記錄格式與 spec §10 不一致（B2-6、B1-9）

- **位置**：`catalog_updater.py:233-235`（`type=%s` 放的是一句話而不是型別名；`remote_*` 碼也用「cache problem」記），`lib/catalog/overlay.py:112-118`（bundled source 丟例外時以 `remote_no_models` 回報）。
- **情境**：排錯時記錄會說「cache problem code=remote_no_models type=the payload offers no selectable local model」，看不出其實是 bundled 檔的問題。只影響可讀性。
- **建議修法**：把 detail 的句子改成短代碼；`accept_remote_document` 在 `catalog.degraded` 時回 `bundled_source_failed` 之類的碼。

#### m10. 沒有記錄「目前用的是快取 / 快取因 key 不同而未用」（B2-2）

- **位置**：`catalog_updater.py:181-189, 218-231`、`lib/catalog/cache.py:63-64`。
- **情境**：§17.6 第 6、7 項寫「(log)」，但換網址後舊快取沒被用、或啟動時用了快取，記錄裡都沒有任何一行可以核對。
- **建議修法**：`initial_catalog()` 與 D8 切換後各記一行 `log.info("WordBridge: catalog source=%s fetch=%s host=%s", …)`。

#### m11. 測試強化項（B1-3、B1-5、B1-7）

- 一個測試釘住整張 `PROVIDER_URL_RULES`（schemes / hosts / any_port），避免日後改規則沒人發現；`parse_remote_payload` 的 detail 值（例如 `"JSONDecodeError"`）釘住；原子寫入測試加 `os.fsync` spy，並斷言 `os.replace` 執行時暫存檔已關閉（Windows 上開著的檔不能 replace）。

#### m12. `__init__.py:52` 匯入了正式碼不再使用的 `load_catalog`（B2-7）

- 兩個測試透過 `plugin_module.load_catalog` 建退化目錄。若要移除，測試改從 `lib.catalog.fallback` 匯入即可；留著也無害。

#### m13. `dialogs.py:373` 的 `getattr(super(), "isValid", None)`

- 正式環境 `SettingsPanel.isValid` 一定存在；這段是為了測試 stub（`SettingsPanel=object`）而寫進正式碼。建議在 stub 補 `isValid`，正式碼直接 `return super().isValid()`。

#### m14. 翻譯檔小瑕疵

- `nvda.po` 新條目的 `#:` 行號是手寫的，與實際行號略有出入（例如 `dialogs.py:300` 實際在 `:308`）；下次 `scons pot` + `msgmerge` 會自動修正。
- `__init__.py:322` 重用 `_("WordBridge")` 當對話框標題，這個呼叫點沒有 `# Translators:` 註解（既有 msgid，已有譯文，不影響功能）。

---

## 四、帳本延後 Minor 的重新評估

| 帳本 | 我的驗證 | 本文件 | 嚴重度 |
| --- | --- | --- | --- |
| B1-1 `redact_url` bytes | 實測丟 `TypeError` | m3 | Minor |
| B1-2 控制字元通過 allowlist | 實測 tab / `\n` / 前導 `\x01` 放行；`requests` 拒絕且訊息不含 key | m2 | Minor（原 HIGH 下修） |
| B1-3 釘住整張規則表 | 無此測試 | m11 | Minor |
| B1-4 敵意列 | 我實測 7 個敵意 URL 全部被擋 | m2 | Minor（只缺測試列） |
| B1-5 釘 detail 值 | 無 | m11 | Minor |
| B1-6 孤立代理字元 | 由程式碼推定 | m8 | Minor |
| B1-7 fsync spy / 暫存檔關閉 | 無 | m11 | Minor |
| B1-8 `1.0` / `true` | 實測接受 | m6 | Minor |
| B1-9 bundled 例外變 `remote_no_models` | 由程式碼推定 | m9 | Minor |
| B1-10、B1-11 | 文件已修 | — | 已處理 |
| B2-1 遠端字串未轉義 | 實測可偽造記錄行（M38） | m1 | Minor，建議合併前修 |
| B2-2 記錄 source | 無 | m10 | Minor |
| B2-3 store key 測試 | 突變 M35 存活 | m4 | Minor，建議合併前修 |
| B2-5 有界讀取測試 | 突變 M36 存活 | m5 | Minor |
| B2-6 快取記錄格式 | 由程式碼確認 | m9 | Minor |
| B2-7 未用的 import | 確認 | m12 | Minor |

---

## 五、帳本 Ruling 的評估

| Ruling | 評估 |
| --- | --- |
| 分批 5/5/6、Task 13 與 16 分開 | 合理 |
| D2 在文件層（`OverlaySource.load`）而非 build 之後 | 合理，而且必要：保住 `degraded` 的語意（§12.4）。突變 M31 證明有測試 |
| `STDLIB_ONLY` 分兩次加 | 合理 |
| 快取上限 2 × 1 MiB、`store()` 拒絕超限 | 合理 |
| 無規則的 provider 不論形狀一律丟棄 | 合理，是最保守的讀法 |
| Task 9 單獨 commit | 合理 |
| `fetch=invalid` 第五個狀態 | 合理，U9 需要 |
| 快取寫入丟例外時仍安裝目錄 | 合理 |
| Task 9 的 `dropped_issues(...) == []` | 合理，lint 本來就不該算 |
| `_catalog_http_get`、`_start_catalog_thread` 兩個 seam | 合理；前者還順便保證用的是 NVDA host 的 `requests` |
| Coseeing 路徑測試改用 sentinel | 合理（U8 之後本來就沒有非 sentinel 的 Coseeing 項目） |
| harness 用程序級 TemporaryDirectory | 合理，harness 強制不可寫 |
| `test_empty_keepalive_chunks` 改名 | 合理，`read1()` 的空讀取就是 EOF |
| `_url_identity` 對無效值比原文 | 合理，而且必要（突變 M13 證明） |
| 面板 stub 記錄控制項順序 | 合理 |
| **批次 3 Ruling 2：未動選單的儲存，登入用 stored channel** | 對 U7 使用者必要；對 stored Coseeing + 已下架 id 的使用者結果與 effective 相同；**但對全新安裝 `("","")` 造成 I1**。修 I1 之後這個 Ruling 可以保留 |
| `_needs_catalog_choice()` 讀模組層 `status()` | 合理（單一 plugin 實例；`terminate` 會 uninstall） |
| 重用 `stored_corrector_selection()` | 合理 |
| `correctTypo()` 也擋 U7 | 合理的縱深防禦，突變 M07 證明有測試 |
| `COSEEING_MODEL_IDS=""` 代表沒有非預設 id | 合理，但這是部署人員看得到的行為，列在 §七 |

---

## 六、Windows／NVDA 尚未驗證的手動項目

Linux 上只驗了注入的邊界。以下項目需要在 Windows 用這支分支打包的附加元件實測（spec §17.6 的 13 項，加上審閱時新增的 4 項）：

1. 全新設定、連線中：NVDA 啟動沒有可聽見的延遲；記錄在「NVDA initialized」之後出現 `catalog fetched host=https://wordbridge.coseeing.org`；`%APPDATA%\nvda\WordBridge-workspace\catalog\remote-catalog.json` 出現；重開面板看得到所有 provider。
2. 同上，啟動一秒內打開面板：狀態列說「仍在載入中」，只有 Coseeing 群組。
3. 離線且無快取：只有 Coseeing「預設」、狀態列說無法載入；stored 本機模型時 NVDA+Alt+O 開出 §12.5 對話框，NVDA 依序讀標題、「尚未取得」句、問句、「否 按鈕」；Escape 講取消句、什麼都不送；重開面板 stored 模型不變（D12）；Yes 走 Coseeing 校正，之後面板顯示 Coseeing「預設」。
4. 離線但有快取：顯示快取清單；狀態列說無法更新。
5. 網址 `ftp://x` 再 `http://example.com`：NVDA 讀「Invalid configuration」訊息框（含 Category 與 Option）；焦點回到網址欄位、對話框不關。
6. `http://localhost:8000` 搭配本機伺服器，按套用：關閉後重開面板顯示該伺服器清單；重啟 NVDA 用該網址的快取；切回預設：舊快取不被用（目前記錄沒有這一行，見 m10）、重新抓取。
7. 空網址：無請求（記錄）、只有「預設」；stored 本機模型的使用者每次校正都會看到 §12.5 對話框（U7 + D5 的結果，見 §七）。
8. 本機伺服器把 OpenAI 的 `url` host 改掉：OpenAI 消失、記錄點名 OpenAI 與 host、面板的「無法載入 N 個目錄項目」數到 provider 與其模型。
9. 本機伺服器回超過 1 MiB、或睡 30 秒：被拒絕，NVDA 維持可操作。
10. fetch 卡住時結束 NVDA：約 3 秒內結束，快取檔完整。
11. NVDA Remote「取得外部 IP」仍可用（`497b178` 的回歸檢查）。
12. NVDA 啟動器（未安裝）：不寫快取檔。
13. 語音：「模型清單網址：編輯區，https://wordbridge.coseeing.org」，Tab 順序最後；NVDA+B 讀得到狀態列。
14. **（新增）**§12.5 對話框關閉後焦點回到原本的文件視窗。parent 是 `gui.mainFrame`，與 NVDA 自己的更新提示相同（`updateCheck.py:1005`），但這條路徑不經過 `mainFrame.prePopup()/postPopup()`，只能實測。
15. **（新增）**對話框開著時再按 NVDA+Alt+O 被忽略、按 NVDA+Alt+W 被 NVDA 的 `blockAction`（MODAL_DIALOG_OPEN）擋下。
16. **（新增）**`response.raw.read1()` 在使用者實際安裝的 NVDA 上可用（需 urllib3 ≥ 2.0；NVDA 2026.1 的 `uv.lock` 是 2.8.0）。
17. **（新增）**在有 Windows 代理伺服器 / 公司 TLS 攔截的環境，fetch 失敗時 NVDA 記錄只有 host 與例外型別，沒有完整 URL。

---

## 七、使用者還沒確認的使用者可見預設

以下是 spec 標為「Decided by orchestrator with the recommended default; user may override before merge」的項目，以及會改變使用者可見行為的 Ruling。merge 前請過目：

1. **D4 / D5 抓取與網址規則**：連線 5 秒、讀取 10 秒、整體 20 秒；內容上限 1 MiB；不跟隨轉址；只接受 200；只准 `https`，`http` 只准 `localhost` / `127.0.0.1` / `::1`；網址最長 2048 字元；不准 userinfo 與 `#`。
2. **D5 空網址 = 關閉遠端目錄**：不抓、不讀快取，只剩 Coseeing「預設」；**stored 本機模型的使用者每次校正都會看到 §12.5 的 Yes/No 對話框**（U7 的直接結果）。
3. **D6 / D18 快取位置**：`<NVDA 使用者設定>/WordBridge-workspace/catalog/remote-catalog.json`，單一檔案、以網址 key 綁定；損毀時忽略不刪；只在 NVDA 允許寫入磁碟時寫。
4. **D8 改網址的瞬間行為**：儲存後立刻切到「bundled ⊕ 新網址的快取（若有）」再抓取；在新清單到達前，面板只有 Coseeing（或舊快取）。
5. **D9**：面板開著時清單更新不會重畫，下一次開面板才看得到。
6. **D12**：面板不覆寫解析不到的 stored 模型，除非使用者動了 provider 或模型選單（I1 修好後，全新安裝除外）。
7. **D13 / D14**：退化宣告維持原狀，只在 bundled 檔本身讀不到時才講；抓取失敗不計入「無法載入 N 個目錄項目」，改由狀態列與記錄呈現。
8. **D16 面板配置**：「模型清單網址：」是最後一個控制項；無效值用 NVDA 標準的「Invalid configuration」訊息框擋下儲存。
9. **D17 伺服器 `GET /`**：公開、不需登入、`Cache-Control: no-cache`、逐位元組回傳檔案；伺服器啟動時檔案壞掉會直接失敗。
10. **§13.3 / §13.4 的六條狀態列與對話框文案與 zh_TW 譯文**（§二之 7 已核對）。對話框標題沿用「WordBridge」，按鈕用 NVDA 自己的「是／否」。
11. **Ruling：`COSEEING_MODEL_IDS=""`（有設但空白）代表「只服務 `default`」**，不是回到預設清單；只有未設定才用預設 `deepseek-flash&DeepSeek,gpt-6-luna&OpenAI`。部署人員若把它留空，已發行附加元件送來的兩個舊 id 會得到 404。
12. **Ruling：未動選單的儲存，Coseeing 登入用 stored channel**（§五，I1 修好後保留）。
13. **Ruling：`correctTypo()` 也擋 U7**，只講「未傳送文字，模型選擇維持不變。」。
14. **Ruling：無效的 stored 網址**（手改 `nvda.ini`）有自己的狀態列（U9 使用者已決定），且清空它也會被存回去（`_url_identity`）。
15. **D1 / D2 overlay 規則**：本機頻道只來自遠端、Coseeing 頻道只來自 bundled；放錯地方的 key 以 lint 記錄不計入掉落數；bundled 沒有有效 Coseeing 項目時用內建 sentinel。

---

## 八、審閱者自行驗證的項目

| # | 指令 / 動作 | 結果 |
| --- | --- | --- |
| V1 | `cd /workspace/WordBridge-remote-catalog && <testvenv>/python -m pytest -q --ignore-glob='tests/test_integration_*' tests` | **719 passed, 1 skipped, 3 subtests passed**（14.99 s） |
| V2 | `cd /workspace/WordBridge-remote-catalog/server && /workspace/WordBridge/server/.venv/bin/python -m pytest -q` | **96 passed**（`app.__file__` 確認指向 worktree） |
| V3 | `prek run --all-files` | 全部 Passed（grep `failed` = 0） |
| V4 | `git diff --check 774560b..HEAD` | 乾淨 |
| V5 | `msgfmt --check -o /dev/null addon/locale/zh_TW/LC_MESSAGES/nvda.po` | OK |
| V6 | `git log 774560b..HEAD --format=%B \| grep -ci co-authored` | 0 |
| V7 | `git ls-files server/app/package/coseeing_auth/storage` | 無輸出（symlink 未追蹤） |
| V8 | `git diff --name-only 774560b..HEAD` 篩掉 `addon/ tests/ server/ docs/ workspace/` | 無 stray file |
| V9 | 每個 commit 都有英文 `<type>: <summary>` 與內文 | 26/26 |
| V10 | 批次 3 中間 commit 的附加元件測試（scratch worktree）：`a1b0fe6`、`d258e36` | 696/1、719/1，與帳本一致 |
| V11 | `grep -rn TEMPORARY_LINT_CODES tests addon` | 0 |
| V12 | NVDA `uv.lock` 的 urllib3 版本；`buildVars.py` 最低 NVDA | urllib3 2.8.0；2026.1。`HTTPResponse.read1(amt, decode_content)` 存在 |
| D1 | 20 個敵意 URL 同時餵 `_url_problem("OpenAI", …)` 與 `requests.Request(...).prepare()` + `urllib3.util.parse_url` | 無「放行但送到別的 host」；tab / `\n` / 前導 `\x01` 放行但 `requests` 拒絕（m2） |
| D2 | `redact_url(b"https://x")` | `TypeError`（m3） |
| D3 | `check_remote_document` 以 `schema_version` `1.0` / `True` | 皆接受（m6） |
| M38 | `filter_provider_urls({"Evil\nWordBridge: catalog fetched host=https://fake\x1b[0m": …})` | location / detail 原樣含換行與 ESC（m1） |
| P1 | 探針測試「全新安裝、未動面板按確定」在 `774560b` 與 `9081560` 各跑一次 | `main`：stored `('default','Coseeing')`、`auth_calls=['Coseeing']`；HEAD：stored `('','')`、`auth_calls=[]`（**I1**） |
| M01 | `selection.py` 改回舊規則（stored Coseeing 移到 local） | KILLED：5 failed |
| M02 | `script_correction` 不問直接校正 | KILLED：7 failed |
| M03 | 對話框預設焦點改 Yes | KILLED：1 failed |
| M04 | `SetEscapeId(YES)` | KILLED：1 failed |
| M05 | Cancel / 關閉視為 Yes | KILLED：1 failed（`escape-or-close`） |
| M06 | 啟動不跳過 U7 使用者的登入 | KILLED：4 failed |
| M07 | 移除 `correctTypo()` 的 U7 防線 | KILLED：1 failed |
| M08 | 移除 `ShowModal()` 後的 `_shutdown` 重查 | KILLED：1 failed |
| M09 | `terminate()` 不 join fetch thread | KILLED：1 failed |
| M10 | D12 一律儲存 | KILLED：1 failed |
| M11 | 登入用 effective channel | KILLED：1 failed |
| M12 | 每次儲存都 refresh | KILLED：3 failed |
| M13 | `_url_identity` 比原文 | KILLED：1 failed |
| M14 | 拿掉 `fetch=invalid` 狀態列 | KILLED：1 failed |
| M15 | `isValid` 顯示訊息後仍回 True | KILLED：2 failed |
| M16 | 面板存未 strip 的原文 | KILLED：1 failed |
| M17 | 伺服器不查 id 清單 | KILLED：3 failed |
| M18 | `COSEEING_MODEL_IDS=""` 退回預設清單 | KILLED：1 failed |
| M19 | `GET /` 不送 `Cache-Control` | KILLED：1 failed |
| M20 | 伺服器接受 `schema_version` 2 | KILLED：1 failed |
| M21 | `_apply` 不查 generation | KILLED：2 failed |
| M22 | `allow_redirects=True` | KILLED：2 failed |
| M23 | D8 改網址不即時安裝 | KILLED：6 failed |
| M24 | 失敗記錄改記 `str(error)` | KILLED：1 failed |
| M25 | Anthropic 允許 http | KILLED：1 failed |
| M26 | allowlist 不看 port | KILLED：1 failed |
| M27 | 目錄網址允許 `#` | KILLED：2 failed |
| M28 | 遠端 host 允許 http | KILLED：3 failed |
| M29 | 快取不比對 `url_key` | KILLED：4 failed |
| M30 | 無遠端時用 bundled 的 models | KILLED：1 failed |
| M31 | 拿掉 D2 sentinel 保證 | KILLED：3 failed |
| M32 | 沒有本機項目也接受 payload | KILLED：5 failed |
| M33 | `correctTypo()` 重讀 registry | KILLED：1 failed |
| M34 | fetch 送 `verify=False` | KILLED：2 failed |
| M35 | 快取用 `check.url` 當 key 存 | **SURVIVED**（61 passed）→ m4 |
| M36 | `CatalogCache.load()` 無界 `read()` | **SURVIVED**（18 passed）→ m5 |

沒有執行 `tests/test_integration_*`。沒有啟動任何本機伺服器。拋棄式 worktree 在審閱結束時以 `git worktree remove` 移除。

---

## 修正記錄

修正代理（DEVELOPMENT_WORKFLOW.md §3.4），在 `d271851` 之後於同一分支修正。每一項都先寫會失敗的測試（red），再修（green）；每個 commit 前都跑過附加元件測試、伺服器測試、`prek run --all-files`、`git diff --check`、`msgfmt --check`。新的 Ruling 記在帳本 `## Final review fix round`。

| 發現 | Commit | 說明 |
| --- | --- | --- |
| I1 全新安裝按「確定」 | `8ea2ab6` | stored 為 `("", "")` 時視為已解析（審閱建議的那一行）。新測試 `test_a_fresh_install_untouched_save_stores_the_default_and_signs_in`（shipped / bundled-only 兩列）修正前得到 `('','')`、`auth_calls=[]`，修正後得到 `('default','Coseeing')`、`['Coseeing']`，與 `main` 相同。M10、M11 的測試照舊通過。 |
| m1 遠端字串寫進記錄 | `1c0e7ac` | 新增 `remote.loggable()`：不可列印字元依 `repr()` 方式跳脫、上限 200 字元（跳脫後的字元也計入）再加 `...`。`_log_catalog_issues`、`_log_cache_problems`、fetch 失敗記錄三處都經過它，記錄格式字串不變。M38 的偽造 provider 名稱測試修正前失敗。 |
| m2 provider URL 的空白／控制字元 | `9ff10dd` | `_url_problem` 加上與 `validate_catalog_url` 相同的檢查；規則表多 16 列（tab、CR、LF、前導 tab／C0／空白、結尾空白、U+3000、ESC，以及 B1-4 的 trailing dot、`localhost.evil.com`、Ollama `[::1]`、`//host`、`\@`、`%2e`），其中 10 列修正前失敗。 |
| m3 `redact_url(bytes)` | `2f3afc8` | 非 `str` 一律回 `<invalid url>`；測試加 bytes、`None`、int。 |
| m4 快取 key（M35） | `d1d7d71` | 用 `DEFAULT_CATALOG_URL` 與大寫 host 做「儲存 → 重新啟動讀回」；M35（`store(check.url, …)`）現在 2 failed。 |
| m5 有界讀取（M36） | `d361092` | spy 斷言 `read(MAX_CACHE_BYTES + 1)`；M36（`handle.read()`）現在 1 failed。 |
| m6 `schema_version` 1.0／true | `163e62b` | `check_remote_document` 改為 `type(version) is not int or version != 1`；表格加 1.0、true、"1" 三列。`build_catalog()` 不改（Ruling：它只看 bundled 檔與 overlay 文件，且伺服器副本要保持一致）。 |
| m7 對話框開著時清單到達 | `4f4493f` | 按 Yes 時重查 `_needs_catalog_choice()`：清單已到就用使用者自己存的模型校正、不改設定。No／Escape 仍然什麼都不送（Ruling：審閱的草稿在 Yes/No 之前重查，會在使用者按 No 之後送出文字，違背 No 的承諾）。 |
| m8 孤立代理字元 | `d6820ea` | 寫入改用 `encode("utf8", "surrogatepass")`（`json.loads(bytes)` 本來就用 surrogatepass 解碼）；往返測試。 |
| m9 快取記錄格式 | `d99a9fe` | 快取 detail 改為短代碼（`too_large` 等）；快取 payload 未通過接受檢查時記成 `code=unreadable_cache type=<接受檢查的代碼>`（spec §10）；bundled 來源丟例外時 `accept_remote_document` 回 `bundled_source_failed`，不再誤報 `remote_no_models`。 |
| m10 記錄目前來源 | `f60f472` | 啟動與 D8 切換網址時記 `WordBridge: catalog source=%s fetch=%s host=%s`（info；關閉或無效時 host 為 `(none)`）。§六第 6、7 項現在可以從記錄核對。 |
| m11 測試強化 | `becb582` | 整張 `PROVIDER_URL_RULES` 釘住；`parse_remote_payload` 每一列的 detail 釘住（另加 `invalid-utf8` 列，原 `bad-utf8` 列其實是 UTF-16 BOM → `JSONDecodeError`）；`os.fsync` spy 與「`os.replace` 時暫存檔已關閉」。拿掉 fsync、把 replace 移進 `with` 兩個突變各 1 failed。 |
| m12 未用的 `load_catalog` 匯入 | `b7cd8f3` | 移除；兩個測試改從已載入套件的 `lib.catalog.fallback` 取用。 |
| m13 `getattr(super(), "isValid")` | `8839d45` | 測試 stub 的 `SettingsPanel` 補上 `isValid()`，正式碼改為 `return super().isValid()`；新測試釘住「網址有效時沿用父類別的答案」，`return True` 突變 1 failed。 |
| m14 翻譯檔 | `89aa4c2` | 兩個 `_("WordBridge")` 呼叫點加上 `# Translators:`；新條目的 `#:` 行號改成 `xgettext` 對目前檔案的輸出。 |
| 範圍外：`lib/llm/provider.py:88, 122` | 未修 | `main` 既有問題（`log.error` 記 `str(e)`，可能含 Google 的 `?key=`），不在本分支範圍；交由 orchestrator 向使用者提出。 |

**突變重驗**：M35、M36 由存活變成被抓到；m1、m2、m6、m7、m8、m9、m10、I1 的新測試在修正前都是紅的。

**最後結果**：附加元件 774 passed / 1 skipped（3 subtests passed）；伺服器 96 passed；`prek run --all-files` 全部 Passed；`git diff --check` 乾淨；`msgfmt --check` 通過。沒有執行 `tests/test_integration_*`。

**新增、尚待使用者確認的使用者可見預設**（補充 §七）：

1. m7：§12.5 對話框開著時清單到達，按 Yes 會用使用者自己存的本機模型校正，設定不改成 Coseeing；按 No／Escape 仍不送出。
2. m2：URL 含空白或控制字元的遠端 provider 會被丟掉（以前會顯示但每次都失敗）。
3. m10：每次啟動與每次改網址各多一行 info 記錄。
4. m1：記錄中的目錄 issue 位置與內容超過 200 字元會被截斷，控制字元以跳脫形式顯示。

### 修正 review（Opus 5.5，2026-11-04）

- 範圍 `d271851..ddc17ff`（16 個 commit）。I1、m1–m14 都已修好。我在拋棄式 worktree 做了 28 個還原或突變，24 個被抓到：I1、m1（三處 sink 的轉義與截斷）、m2（10 列）、m3、m4、m5、m6、m7（一律改設定、在 Yes/No 之前就重查、不存設定三種）、m8、m9（三處）、m10（兩處）、m11（fsync、在 `with` 內 replace）、m13。存活 4 個：1 個等價突變；`_log_cache_problems` 拿掉 `loggable()`（那裡只會收到代碼和型別名，屬於防禦性寫法，可接受）；重新加回未使用的 import（沒有 ruff hook，無害）；半空的 stored pair（見 N1）。
- 16 個 commit 每個都綠（721→774 passed / 1 skipped）；HEAD：附加元件 774 passed / 1 skipped，伺服器 96 passed，`prek` 全部 Passed，`git diff --check` 乾淨，`msgfmt --check` 通過，新條目的 `#:` 和 xgettext 一致，沒有 `Co-Authored-By`。
- 沒有新的 Critical 或 Important，只有兩個 Minor。**N1**：Ruling 1 說半空的 pair 只會來自手改 nvda.ini，這個前提不成立。NVDA 不會寫入和目前值（含預設值）相同的設定（`/workspace/nvda/source/config/__init__.py:1363-1367`），而 2026.9.3（`47aa41f`）的預設是 `("deepseek-v4-flash&DeepSeek", "Coseeing")`，所以當時選了 Coseeing GPT-5.6 Luna 的使用者升級後會是 `("gpt-5.6-luna&OpenAI", "")`。這種使用者沒動選單就按「確定」，分支不存也不登入，`main` 則會存 `("default","Coseeing")` 並登入（探針已在兩邊各跑一次證實）。影響不大：這些人在 2026.9.3 已經走過登入，校正也仍走 Coseeing 預設。建議把「stored channel 為空」也算成已解析，並補一個測試（目前沒有測試釘住半空的情形）。**N2**：m7 的 Ruling 7 和 U7 的字面、以及對話框的文案（「用 Coseeing 校正」「設定會改成 Coseeing 預設」）不一致，只在清單於對話框開著時到達才會發生。這個做法合理，但應請使用者明確確認，不要只當成一個新的預設值。
- Ruling 2–6 合理；Ruling 1 的結論可以接受，但理由要改（N1）；Ruling 7 需要使用者確認（N2）。
