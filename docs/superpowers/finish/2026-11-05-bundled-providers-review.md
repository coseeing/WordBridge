# Bundled providers（服務提供者條目內建、遠端清單只供模型）— 最終審閱（DEVELOPMENT_WORKFLOW.md §3.3）

- **分支**：`feat/bundled-providers`（自 `main` @ `a28dc29` 開出），審閱範圍 `a28dc29..fef68ef`（10 個 commit：4 個 docs、6 個程式）
- **Spec**：`docs/superpowers/specs/2026-11-05-bundled-providers-design.md`（使用者決定 B1–B4；orchestrator 預設 P1–P10；OQ1 → B），修訂 `2026-11-04-remote-catalog-design.md`（RC）與 `2026-11-04-catalog-retry-design.md`（CR）
- **Plan**：`docs/superpowers/plans/2026-11-05-bundled-providers.md`（6 個 task，一批）
- **進度帳本**：`.superpowers/sdd/2026-11-05-bundled-providers/progress.md`（13 條 Ruling）
- **審閱者**：Fable 5.1，只讀程式碼，不修改原始碼、測試、spec 或 plan；突變測試在拋棄式 worktree 進行（`git worktree add --detach <scratchpad>/fable-bp fef68ef`，審閱後 `git worktree remove`）
- **日期**：2026-11-05
- 路徑若無前綴，相對於 `addon/globalPlugins/WordBridge/`。

---

## 一、總評

**可以直接合併。** 沒有 Critical，沒有 Important；8 個 Minor 全是文件、測試衛生與未來維護成本，沒有一個改變使用者看到或聽到的行為。

- 兩套測試在 HEAD 都是綠的（附加元件 **1056 passed / 1 skipped**，伺服器 **104 passed**），`prek` 全部 Passed，`msgfmt --check` 通過，沒有 `Co-Authored-By`，沒有 stray file。唯一的衛生瑕疵：`git diff --check main..HEAD` 在 **plan 文件**抓到一個行尾空白（m1；帳本記的「diff --check clean」是對工作樹跑的，沒有對 `main` 跑）。
- 使用者四個決定 B1–B4 與 OQ1 → B 逐一核對都落地了（§二之 2）；plan 的 Review Focus 五項都有對應測試且通過（§二之 6）。
- **我自己做了 25 個突變，25 個全部被測試抓到**（表八 M01–M25），涵蓋 overlay 的三條來源規則、B4 的拒絕與順序、`no_providers` 分支與 detail、`has_local_items`、probe 的 `remote_no_models` 分支、快取拒絕的記錄與不安裝、兩個 lint code、allowlist 掃描、內建檔的 URL／名稱／型別漂移（含 finding 8 的 `0.0→0`、`false→0`，我另外證明 `dict ==` 會放過這兩個）、伺服器 `GET /` 的三種退化。
- 離線／無快取／拒絕 payload 的路徑和 `main` 逐 byte 相同：overlay 在沒有遠端文件時 `providers == {}`，所以內建目錄仍是「只有 Coseeing default、沒有 issue、不 degraded」（`test_the_bundled_catalog_alone_offers_only_the_sentinel`、`test_no_remote_document_gives_the_sentinel_only`）；帳號方塊標題在有無清單時相同（`test_account_box_captions_are_the_same_with_and_without_a_fetched_list`）；U7 對話框仍以 `source == none` 判斷（`__init__.py:308`，未改）。
- `catalog_updater.py` 的執行緒與鎖沒有動：唯一的改動是 `_probe()` 少呼叫一次 `load_overlay_catalog()`（`:383-386`），仍然不碰鎖、generation、cache、timer、listener。
- 內建檔的 `providers` 區塊和伺服器檔 `server/app/setting/catalog.json:3-77` 的文字（含 tab 縮排）**逐字相同**（表八 V9），不只 canonical JSON 相同。
- 記錄紀律（RC D15）：新增的 issue code 兩個 detail 都是常數字串；`unknown_provider` 的 detail 仍經 `loggable()`（`__init__.py:365-372`），forged-text 測試改走 model 的 `provider` 欄位（finding 9）仍然釘住長度與控制字元。沒有新的記錄行、沒有 `str(error)`、沒有 body。

---

## 二、審閱重點逐項

### 1. 正確性與相對 `main` 的回歸

- **Overlay（`lib/catalog/overlay.py:21-45`）**：`providers = bundled.get("providers", {})` 只在 `remote` 是 mapping 時（`:37`），沒有遠端文件時 `({}, [])`（`:35`）；`models` 永遠只讀 `remote`；`coseeings` 永遠只讀 `bundled`；遠端的 `providers`、`coseeings`、其他 key 一個字都不讀（突變 M04、M06、M08 證明）。內建的 `models` 以 `ignored_bundled_models`／`bundled.models` 報 lint（M07）。
- **Acceptance（`:99-125`）**：順序是 document check → overlay/build → `degraded` → **新增** `not catalog.providers` → `has_local_items`。`no_providers` 只會在 bundled 檔缺少／壞掉／全部 incomplete 時發生，因為 `build_catalog()` 不會因 `runnable_providers` 丟掉 provider entry（`document.py:48-79`），所以「bundled 正常但這個 build 跑不了」仍是 `remote_no_models`。五種壞 bundled（unreadable、無 key、`{}`、list、全部 incomplete）都得到 `("bundled_source_failed", "bundled", "no_providers")`；只壞一個 entry 時 payload 仍接受、只掉那個 provider 的模型（Review Focus 3）。
- **Document check（`lib/catalog/remote.py:161-187`）**：object → `schema_version` 是 `int` 且等於 1 → **沒有 `providers` key**（B4，`:181-182`，任何值）→ `models` 是 list。同一個函式服務抓取、快取與 probe 三條路徑，所以舊快取在 `_local_catalog()`（`catalog_updater.py:439-456`）被記成 `unreadable_cache type=remote_providers_not_allowed` 後走內建目錄（M13、M14 證明記錄與不安裝都有測試）。
- **Probe（`catalog_updater.py:365-387`）**：`remote_providers_not_allowed` 落在 `_probe_failure()` 的 `remote_*` → `not_a_list` 桶；`remote_no_models` 的明確分支保留（finding 3，M12 證明少了它兩列會變 `not_a_list`）；`bundled_source_failed` → `failed`／detail 是 code。
- **伺服器（`server/app/main.py:43-64`）**：仍在啟動時讀一次、驗一次（物件、`schema_version == 1`），回傳去掉 `providers` 後以 `ensure_ascii=False, indent="\t"` 重新序列化的 bytes，其他 key 依檔案順序。我用自己的腳本比對：目前伺服器檔 `models` 段的 **84 個數字 token 經 round-trip 後全部相同**（表八 V10），所以帳本 Ruling 擔心的 `2.50 → 2.5` 在今天的檔案不會發生。`correction_config.py`、`server/app/setting/catalog.json`、`server/app/lib/catalog/` 都沒改（`git diff --stat` 證實）。
- **相對 `main` 的回歸**：沒有。`main` 上「遠端 provider 的 `url`／`setting`／timeout 可以在 allowlist 內改寫」的能力依 B1 刻意移除（finding 5）；其餘 `main` 的行為（重試排程、面板即時更新、U7、字典、報告）都沒碰，既有測試全數保留並通過。

### 2. Spec 符合度（每個使用者決定）

| 決定 | 落地位置 | 結果 |
| --- | --- | --- |
| B1 provider 條目內建；遠端只供 `models` | `setting/catalog.json:2-77`、`overlay.py:35-37` | ✅ 區塊逐字同伺服器檔；突變 M04/M05/M06 全部被抓到 |
| B2 `GET /` 不送 `providers`；伺服器檔保留 | `server/app/main.py:63-64`、`server/tests/test_catalog_route.py` | ✅ 104 passed；M23/M24/M25 被抓到；`Cache-Control: no-cache`、`application/json` 不變 |
| B3（OQ1 → B）`unknown_provider` 是 lint：記錄不計數 | `lib/catalog/model.py:40-44`、`dialogs.py:152`（未改） | ✅ `test_a_model_for_a_provider_this_release_lacks_is_not_counted_in_the_dropped_line`、`test_an_unknown_provider_issue_is_still_logged`；`unsupported_provider` 仍計數（以 served 檔的 DeepSeek 數推導）；M15 被抓到 |
| B4 任何 `providers` key 都整份拒絕（抓取與快取） | `remote.py:181-182`、`catalog_updater.py:439-456` | ✅ 七種值（null/list/str/number/{}/hostile/伺服器本身）× parse 與 accept 兩條路徑；快取拒絕有記錄、不安裝；抓取拒絕不安裝、不寫快取、arm 重試；M01/M02/M03 被抓到 |
| P1 無遠端文件時 `providers == {}` | `overlay.py:35` | ✅ 離線目錄零 issue；M05 被抓到（含面板標題測試） |
| P2 遠端 `coseeings`／其他 key 靜默忽略 | `overlay.py:36-38` | ✅ `test_remote_extra_keys_add_no_issue`；M08 被抓到 |
| P3 `ignored_bundled_models` | `overlay.py:27-32` | ✅ M06/M07/M16 |
| P4 `no_providers` | `overlay.py:118-122` | ✅ M09/M10 |
| P5 document check 不再要求 `providers` | `remote.py:181-185` | ✅ `providers-missing` 解析成功；M02 |
| P6 allowlist 全部移除 | `remote.py`（−88 行）、`catalog_updater.py:383-386`、`catalog_url_dialog.py:64-68`、`nvda.po` | ✅ 我用 grep 在 `addon/`、`server/`、`tests/`、`*.md`、三個 `.po` 全域搜尋 `allowlist|disallowed|filter_provider_urls|PROVIDER_URL_RULES|ProviderUrlRule|_https_only|_url_problem|ignored_remote_coseeings|ignored_bundled_local_entries`，只剩 `tests/test_catalog_bundled.py` 的掃描測試本身；`remote.py` 的 `dataclass` import 仍被 `UrlCheck` 使用；伺服器的 `lib/catalog` 從來沒有 `remote.py`／`overlay.py`（RC §3），`document.py`、`fallback.py` 與附加元件逐 byte 相同 |
| P7 漂移測試用 canonical JSON | `tests/test_catalog_bundled.py:161-181` | ✅ M18/M19 被抓到；`dict ==` 對同兩個突變回 `True`（表八 V8） |
| P8 不遷移快取、`cache_version` 不變 | `cache.py` 只改 docstring | ✅ |
| P10 RC/CR 不改 | `git diff --stat` | ✅ |

### 3. 離線／無快取／被拒 payload 的使用者可見路徑

| 情境 | 目錄 | 面板 | NVDA+Alt+O（stored 本機模型） | 「測試...」 |
| --- | --- | --- | --- | --- |
| 離線、無快取 | bundled ⊕ None：sentinel only、`issues == ()` | 只有 Coseeing；只有 Coseeing 帳號方塊；狀態列照 CR §10.5 | U7 對話框（`source == none`） | — |
| 舊測試版快取（含 `providers`） | 拒絕 → 同上；記錄一行 `unreadable_cache type=remote_providers_not_allowed` | 同上 | U7 對話框 | — |
| 抓到含 `providers` 的 payload | 保留現有目錄、`fetch=failed`、arm 重試 | 狀態列「無法更新」（有快取時）或「無法載入」 | 依 source | 「伺服器的回應不是 WordBridge 模型清單。請確認網址是否正確。」 |
| 全部模型指向未內建的 provider | `remote_no_models` → 失敗、重試 | 同上 | 依 source | 「這份模型清單沒有 WordBridge 可以使用的模型。」 |
| 一個模型指向未內建的 provider | 成功；那個模型掉、記錄 `unknown_provider` | **不**出現「N 個目錄項目無法載入」（B3） | 正常 | 載入成功、模型數不含它 |
| 內建檔壞掉／缺 `providers` | `bundled_source_failed`/`no_providers` → 失敗、重試；離線時 sentinel（`bundled_coseeings_fallback` 時） | 只有 Coseeing | U7 | 「請確認已連上網際網路，且網址正確。」（`failed` 桶，見 §七第 4 項） |

每一列都對應到我跑過或突變過的測試（`test_catalog_updater.py`、`test_catalog_retry.py` 的 FAILURE/NOT_FAILURE/PROBE 列、`test_catalog_settings_panel.py`、`test_catalog_url_dialog.py`）。

### 4. 執行緒與狀態

`catalog_updater.py` 的 diff 只有 `ProbeResult` docstring 與 `_probe()` 少三行。`_probe()` 仍在 daemon thread 上只做 validate → fetch → parse → accept，讀 `self._bundled_source`（每次重新讀檔，純函式）與 `self._runnable_providers`（不可變），不進鎖、不改 generation、不排 timer、不通知 listener；`_fetch_and_build()` 在 fetch thread 做完全相同的事，所以 CR 審閱的執行緒結論全部維持。`_local_catalog()` 沒改，仍在主執行緒。

### 5. 測試是否真的抓得到（突變測試）

25 個突變（表八 M01–M25）全部被抓到，每個 spec §17.3 列的突變都在內，另加：B4 檢查順序（M03，被 `test_a_huge_remote_detail_is_logged_bounded_on_fetch_failure` 抓到，因為它的 payload 同時有壞 schema 和 providers）、`no_providers` 的 detail（M10）、快取拒絕不記錄／仍安裝（M13、M14）、allowlist 掃描（M17）、內建 provider 改名／缺 `setting`（M21、M22）、伺服器 `ensure_ascii=True` 與連 `models` 一起丟掉（M24、M25）。沒有存活的突變。帳本記錄的突變我沒有重做，因為我的集合是它的超集。

### 6. plan 的 Review Focus

| # | 項目 | 測試 | 結果 |
| --- | --- | --- | --- |
| 1 | `providers` 任何值（null/"x"/7/[]/{}/hostile/伺服器本身） | `test_any_remote_providers_key_rejects_the_payload`×7、`test_a_cache_that_carries_providers_is_rejected`、`test_a_fetched_payload_that_carries_providers_is_not_installed_or_cached`、retry `carries-providers`、probe `providers-rejected`、wiring `..._keeps_the_current_catalog`；缺 `providers` → `test_a_payload_without_providers_is_accepted` | ✅ M01 被八個以上測試抓到 |
| 2 | `openai`、`OpenAI `、`Mistral` | `test_a_remote_model_for_a_provider_the_bundled_file_lacks_is_dropped[3]`（`_text()` 不 strip、不 fold，`document.py:14-15`） | ✅ 16 個本機項目保留、那一個掉 |
| 3 | 一個 incomplete 的內建 entry | `test_one_incomplete_bundled_provider_drops_only_its_models`、`[all-incomplete]` | ✅ M09/M10/M22 |
| 4 | 同時帶 `providers`、`coseeings`、未知 key | `test_remote_extra_keys_add_no_issue`（overlay 層） | ✅ M08；注意 plan 這一條的文字是 B4 之前寫的，系統層現在整份拒絕（m5） |
| 5 | 一邊多／少一個 provider、`0.0 → 0` | `test_the_drift_message_names_the_first_differing_provider`×4、`test_the_bundled_providers_equal_the_server_providers` | ✅ M18/M19/M21 被抓到且訊息點名正確的 provider |

### 7. 翻譯

沒有新字串。刪掉一條（`這份模型清單列出的服務提供者網址都不在 WordBridge 允許的範圍內。`，`nvda.po` 舊 `:619-622`）連同 `#.` 註解與 `#:` 參照，`msgfmt --check` 通過；`zh_CN`、`zh_HK` 本來就沒有這條（grep 證實）；`TASK13_STRINGS` 同步移除。剩下 11 條 `catalog_url_dialog.py` 的 `#:` 行號因刪了 4 行而過期（m2）。

### 8. git／流程限制

- 10 個 commit 都是英文 `<type>: <summary>` 加說明原因的內文，沒有 `Co-Authored-By`；最大的是 Task 1（de7ca12，14 個檔案）與 Task 4（bbb129f，10 個檔案），都是 spec §16.1 規定「同一個 commit 遷移測試」的結果。
- 變更只落在 `addon/`、`tests/`、`docs/`、`server/`；`git status` 乾淨；`tests/test_catalog_provider_allowlist.py` 以 `git rm` 刪除（spec §16 要求）。
- 每個程式 commit 都綠：我在拋棄式 worktree 重跑 de7ca12、58c1986、31b1774、bbb129f、02aac5a（表八 V11），數字與帳本一致。
- 資源：pytest 單一 worker，MemAvailable 全程 > 4.9 GB。

---

## 三、發現

### Critical

無。

### Important

無。

### Minor

依建議處理順序；m1、m2、m7 修法便宜，建議合併前一起處理（或 m2 留給 `scons pot`）。

#### m1. `git diff --check main..HEAD` 不乾淨：plan 文件一個行尾空白

- **位置**：`docs/superpowers/plans/2026-11-05-bundled-providers.md:299`（Task 6 Step 3 的 `... it is still logged). ` 句尾）。
- **情境**：spec §21 AC8 與 plan Global Constraints 都要求 `git diff --check` clean；帳本每個 task 記「diff --check clean」，但那是對工作樹跑的（沒有 staged/unstaged 變更時永遠 clean），對 `main..HEAD` 跑就抓到。只影響文件。
- **建議修法**：刪掉那個空白，`docs:` commit。

#### m2. `nvda.po` 11 條 `#:` 行號過期

- **位置**：`addon/locale/zh_TW/LC_MESSAGES/nvda.po:620`（`catalog_url_dialog.py:72` → 實際 `:68`），以及 `:80/:83/:86/:91/:116/:146/:170/:220/:223/:228` 十條，全部差 4（刪掉 tip 分支的四行）。
- **情境**：只影響翻譯者對照原始碼；`msgfmt` 不檢查。下次 `scons pot` + `msgmerge` 自動修正。
- **建議修法**：留給下次 `scons pot`，或在 m1 的 commit 一起手動 −4。

#### m3. `ProbeResult` docstring 重排後留下一行 118 字

- **位置**：`catalog_updater.py:145`。
- **情境**：刪掉 `disallowed_hosts` 時把兩行併成一行，超過 `pyproject.toml` 的 `line-length = 110`（ruff 沒開 E501，所以 `prek` 沒抓）。純版面。
- **建議修法**：重新折行成 `not_a_list, no_models, failed, or unavailable (no updater installed).` / `detail: the issue detail (the HTTP status for http_status), ...`。

#### m4. 帳本的 task 編號停留在 B2／B4 之前的 plan

- **位置**：`.superpowers/sdd/2026-11-05-bundled-providers/progress.md:8`（「Task 4 implements B … revert Task 4's code commit to go back to A」）、`:14-15`（「T3 removes filter_provider_urls」「T4 adds unknown_provider」）。
- **情境**：執行的 plan 加了 Task 3（B2）與 Task 4（B4）之後，allowlist 移除是 Task 5、OQ1 是 Task 6。照帳本去 revert「Task 4 的 commit」會 revert 到 B4（`bbb129f`）而不是 OQ1（`fef68ef`）。帳本在 `.gitignore` 內，只影響接手的人。
- **建議修法**：在帳本補一行勘誤：OQ1 → B 的 commit 是 `fef68ef`（Task 6），B4 是 `bbb129f`（Task 4）。

#### m5. plan Review Focus 4 的文字是 B4 之前的

- **位置**：`docs/superpowers/plans/2026-11-05-bundled-providers.md:56`。
- **情境**：寫「一個同時帶 `providers`、`coseeings`、未知 key 的 payload（舊快取或自架伺服器）… overlay 不加任何 issue」。B4 之後這種 payload 在 `check_remote_document()` 就整份拒絕，overlay 根本看不到；測試 `test_remote_extra_keys_add_no_issue` 直接呼叫 `overlay_documents()`，是正確的「縱深防禦」層級，但 plan 的情境描述會誤導讀者以為系統接受它。
- **建議修法**：plan 加一句「（B4 之後系統層拒絕；這一項只檢查 overlay 層）」，或留在 handoff 記錄說明。

#### m6. 伺服器的 `lib/catalog/model.py` 與附加元件的不同（`main` 就如此）

- **位置**：`server/app/lib/catalog/model.py:29-35`（`LINT_ISSUE_CODES = frozenset({"unreferenced_provider"})`）vs `lib/catalog/model.py:40-44`。
- **情境**：spec §12 只宣稱 `document.py`、`fallback.py` 兩份相同（我驗證為逐 byte 相同），`model.py` 在 `main` 就已經分岔（RC 時附加元件加了兩個 overlay 的 lint code，伺服器沒跟）。伺服器不做 overlay、也沒有任何程式呼叫 `is_dropped_issue()`，所以沒有行為影響。這支分支沒有讓它更糟，但也沒有同步。
- **建議修法**：不在本分支處理；記在 handoff 的後續工作：要嘛把伺服器的 `LINT_ISSUE_CODES` 同步成三個 code，要嘛在 spec 說明兩份 `model.py` 允許不同。

#### m7. `test_the_bundled_providers_build_completely` 用硬編的 `RUNNABLE`

- **位置**：`tests/test_catalog_bundled.py:19`、`:153`（另 `:32` 的 `shipped_catalog()` 也用它）。
- **情境**：新增一個 provider 時要改三處：provider class、`setting/catalog.json`、伺服器檔；`test_the_bundled_providers_are_exactly_the_supported_providers` 已經釘住前兩者相等，但這個測試會因 `RUNNABLE` 少了新名字而以 `unsupported_provider` 失敗，變成第四處要改，而且錯誤訊息（`catalog.issues != ()`）不會說是測試常數過期。
- **建議修法**：`runnable_providers=SUPPORTED_PROVIDERS`（檔案已經 import），刪掉 `RUNNABLE`。

#### m8. 沒有測試把 `catalog_updater` 會回傳的 `ProbeResult.kind` 集合和對話框的 `RESULT_ROWS` 對起來

- **位置**：`tests/test_catalog_url_dialog.py:408-420`（7 種 kind）、`catalog_updater.py:143-147`（docstring 列 10 種；`invalid`／`insecure_scheme`／`empty` 在對話框先驗證所以不進 `_failure_tip`）。
- **情境**：spec §17.1 的「every `ProbeResult` kind the updater can return has a row」目前靠人眼；這次刪 `disallowed_hosts` 時兩邊都有改，但若日後新增一種 kind 而忘了對話框，它會靜默落到「請確認已連上網際網路，且網址正確。」。CR 就是這樣，本分支沒有變差。
- **建議修法**（可選）：在對話框測試加一個斷言：`{row kind for RESULT_ROWS} ⊇ {kinds grep 自 catalog_updater 原始碼的 ProbeResult("...")} − {"invalid", "insecure_scheme", "empty"}`。

---

## 四、帳本 Ruling 的評估

| # | Ruling | 評估 |
| --- | --- | --- |
| 1 | OQ1 → B 在「Task 4」實作 | 決定本身是使用者的；編號是舊 plan 的（實際是 Task 6，`fef68ef`），見 m4 |
| 2 | 最終 review 由協調者派 | 符合 §3.3 |
| 3 | B2 以新的 Task 3 在 Task 2 之後落地 | 合理：Task 2 先讓附加元件接受沒有 `providers` 的 payload，每個 commit 才都綠；我重跑 31b1774 證實 |
| 4 | B2 序列化：`json.dumps(…, ensure_ascii=False, indent="\t") + "\n"` | 合理。代價（數字文字可能改寫）我用腳本驗證今天的檔案 84 個數字 token 全部不變（V10）；`ensure_ascii=False` 有測試釘住（M24） |
| 5 | B4 的 code `remote_providers_not_allowed`、位置 `payload`、排在 `schema_version` 之後 `models` 之前 | 合理：與其他 document-check code 同一命名法，自然落到 probe 的 `remote_*` 桶；順序有測試抓（M03） |
| 6 | B4 的「測試...」對應 `not_a_list` | 可接受；代價是自架舊版伺服器的人看到「請確認網址是否正確」而網址其實沒錯。列在 §七第 3 項 |
| 7 | B4 自成 Task 4、排在伺服器 task 之後 | 合理 |
| 8 | T1：以 `vars(entry)` 比較 | 合理，updater 用的是 plugin 自己那份 `lib.catalog`，class 不同 |
| 9 | T4：刪掉 `test_a_cache_without_providers_loads` | 合理；M02 證明被 `test_a_cache_of_the_served_document_loads_with_the_bundled_providers` 抓到，案例沒丟 |
| 10 | T4：hostile 測試改成拒絕測試；overlay 層保留 `test_remote_providers_never_reach_a_provider_entry` | 合理且必要（縱深防禦）；M04 證明 overlay 層的測試還咬得住 |
| 11 | T4：seam 測試改名、payload 不帶 provider entry | 合理 |
| 12 | T5：`TASK13_STRINGS` 移除那條 | 必要，否則測試斷言一條已不存在的字串 |
| 13 | T5：`git rm tests/test_catalog_provider_allowlist.py` | 正確：spec §16 明寫「removed with the code it tests」，§8 的「不刪別人的檔案」指分支外的檔案 |
| — | T6：DeepSeek 數量由 served 檔推導 | 合理（檔案有 2 個，`>= 2` 保住複數句型） |
| — | T5 process note（mutation restore 吃掉未 commit 的編輯） | 已自行補救並重跑；建議以後突變只在 commit 之後做（帳本已這樣寫） |

---

## 五、審閱者自行驗證的項目

| # | 指令 / 動作 | 結果 |
| --- | --- | --- |
| V1 | `cd /workspace/WordBridge-bundled-providers && <testvenv>/python -m pytest -q --ignore-glob='tests/test_integration_*' tests` | **1056 passed, 1 skipped, 3 subtests passed**（19.93 s） |
| V2 | `cd server && /workspace/WordBridge/server/.venv/bin/python -m pytest -q` | **104 passed**, 5 warnings |
| V3 | `prek run --all-files` | 3/3 Passed |
| V4 | `git diff --check main..HEAD` | **1 個行尾空白**（plan 文件 `:299`，m1）；程式碼與 `.po` 乾淨 |
| V5 | `msgfmt --check -o /dev/null addon/locale/zh_TW/LC_MESSAGES/nvda.po` | OK |
| V6 | `git log main..HEAD --format=%B \| grep -ci co-authored` | 0 |
| V7 | `git diff --name-only main..HEAD` 篩掉 `addon/ tests/ docs/ server/`；`git status --short` | 無 stray file；工作樹乾淨 |
| V8 | finding 8：對內建 `providers` 做 `temperature 0.0→0`、`store false→0` 後 `dict ==` 與 canonical 文字比較 | `==` 回 `True`（放過），canonical 文字不同（抓到） |
| V9 | 內建檔與伺服器檔的 `"providers": {…}` 區塊文字比對（含 tab） | 逐字相同（1487 字元）；伺服器檔第 3–77 行 |
| V10 | 伺服器檔去 `providers` 後 `json.dumps(indent="\t")` 的 `models` 段數字 token vs 原檔 | 84 個 token 全部相同 |
| V11 | 拋棄式 worktree 重跑中間 commit 的附加元件測試：de7ca12、58c1986、31b1774、bbb129f、02aac5a | 1074/1、1084/1、1085/1、1096/1、1053/1，伺服器在 02aac5a 為 104 passed；與帳本逐一相同 |
| V12 | 全域 grep allowlist 殘留（`addon/`、`server/`、`tests/`、`*.md`、`*.po`） | 只剩 `tests/test_catalog_bundled.py` 的掃描測試常數 |
| V13 | `server/app/lib/catalog/{document,fallback}.py` vs 附加元件 | `cmp` 相同；`model.py` 在 `main` 就不同（m6） |
| V14 | `zh_CN`、`zh_HK` 的 `.po` 是否有被刪的字串 | 沒有 |
| V15 | `nvda.po` 的 `catalog_url_dialog.py` `#:` 行號 vs 實際 `_(` 行 | 11 條差 4（m2） |
| M01 | `check_remote_document` 不拒絕 `providers` | KILLED：16 failed（parse/accept 七值、快取、retry、wiring） |
| M02 | 改回 `main` 的「providers 必須是 mapping」 | KILLED：48 failed |
| M03 | `providers` 檢查搬到 `schema_version` 之前 | KILLED：1 failed（`test_a_huge_remote_detail_is_logged_bounded_on_fetch_failure`） |
| M04 | overlay 改讀 `remote["providers"]` | KILLED：18 failed |
| M05 | 無遠端文件時也放入內建 providers | KILLED：3 failed（sentinel-only、bundled-only、面板標題） |
| M06 | overlay 用內建 `models` | KILLED：2 failed |
| M07 | lint 位置 `bundled.models` → `bundled` | KILLED：1 failed |
| M08 | 恢復 `ignored_remote_coseeings` lint | KILLED：2 failed |
| M09 | 刪掉 `no_providers` 分支 | KILLED：8 failed |
| M10 | `no_providers` detail 改成 `unreadable_source` | KILLED：6 failed |
| M11 | 刪掉 `has_local_items` 檢查（一律接受） | KILLED：8 failed |
| M12 | `_probe` 刪掉 `remote_no_models → no_models` | KILLED：2 failed（`[unknown-providers-only]`、`[no-models]`） |
| M13 | `_local_catalog` 不記錄被拒的快取 | KILLED：4 failed |
| M14 | `_local_catalog` 被拒的快取仍安裝 | KILLED：5 failed |
| M15 | `LINT_ISSUE_CODES` 拿掉 `unknown_provider` | KILLED：2 failed |
| M16 | `LINT_ISSUE_CODES` 拿掉 `ignored_bundled_models` | KILLED：2 failed |
| M17 | `catalog_updater.py` 註解加 `disallowed_hosts` | KILLED：1 failed（掃描） |
| M18 | 內建檔 DeepSeek `temperature 0.0 → 0` | KILLED：2 failed（漂移 + `[float-to-int]`） |
| M19 | 內建檔 OpenAI `store false → 0` | KILLED：2 failed |
| M20 | 內建檔 OpenAI host 改掉 | KILLED：4 failed（pinned、rc9 host、漂移、entry 比對） |
| M21 | 內建檔 `OpenRouter` 改名 | KILLED：7 failed |
| M22 | 內建檔 Google 缺 `setting` | KILLED：4 failed |
| M23 | 伺服器 `load_catalog_bytes` 回傳原檔 bytes | KILLED：3 failed |
| M24 | 伺服器 `ensure_ascii=True` | KILLED：1 failed（UTF-8 斷言） |
| M25 | 伺服器連 `models` 一起丟掉 | KILLED：4 failed |

---

## 六、Windows／NVDA 尚未驗證的手動項目

Linux 上只驗了注入的邊界（假的 HTTP、stub 的 wx 控制項、假的 scheduler）。以下需要在 Windows 用這支分支打包的附加元件實測（spec §17.4 的 1–8；審閱時新增 9–13）：

1. 從 `WordBridge-2026.11.1-test-catalog-retry-1` 升級、保留它的快取、連線：面板的 provider 與模型和升級前相同，沒有「無法載入」那一行；NVDA 記錄**第一次啟動**有一行 `catalog cache problem code=unreadable_cache type=remote_providers_not_allowed`（B4 拒絕舊快取），抓取成功後快取被覆寫、第二次啟動不再出現。（spec §17.4 第 1 項寫「記錄沒有快取問題」，依 B4 第一次啟動應該**有**一行，請以這裡為準。）
2. 同樣升級、離線：舊快取被拒 → 面板只有 Coseeing「default」、狀態列說無法載入；每次啟動記錄都有上一項那一行，直到連線成功。
3. 乾淨設定、離線、stored 本機模型：只有 Coseeing「default」；NVDA+Alt+O 開 U7 對話框，和 `main` 完全相同。
4. 用個人 key 對 OpenAI、Anthropic、Google、DeepSeek 各做一次校正：成功，參數與之前相同（現在永遠來自附加元件）。
5. 本機伺服器（`http://localhost:8000`）跑**這支分支**的 server：`GET /` 的 body 沒有 `providers`、tab 縮排、中文 label 是 UTF-8 文字不是 `\uXXXX`、`Cache-Control: no-cache`；「測試...」說清單已載入、模型數和之前相同。
6. 本機伺服器改跑**舊版** server（會送 `providers`）：「測試...」說「伺服器的回應不是 WordBridge 模型清單。請確認網址是否正確。」；存檔後狀態列顯示無法更新、記錄 `catalog fetch failed … code=remote_providers_not_allowed`、一分鐘後重試。
7. 本機伺服器只送 provider 名為 `Mistral` 的模型：「測試...」說「這份模型清單沒有 WordBridge 可以使用的模型。」。
8. 本機伺服器送伺服器檔加一個 `Mistral` 模型：面板**沒有**「N 個目錄項目無法載入」（OQ1 → B）；記錄有一行 `code=unknown_provider location=models[17]`（伺服器檔有 17 個模型，索引 0–16，加上去的是第 17 個）；其他模型正常。
9. 本機伺服器把 OpenAI 的 `url` 改成 `http://127.0.0.1:9999/capture` 並在那個 port 開監聽：舊版 server 的話「測試...」直接拒絕（第 6 項）；若用這支分支的 server（它不送 `providers`），校正仍打到 `api.openai.com`、監聽器收不到任何東西。
10. 帳號方塊標題與 Tab 順序和 CR §15.6 的 7a、7b 相同（標題來自內建 label，和 group 名相同）。
11. 自架 Ollama 使用者（若有）：本機 `http://localhost:11434` 校正不變；自架清單再也不能改 Ollama 的 port（finding 5）。
12. 已部署的正式伺服器（`https://wordbridge.coseeing.org`）更新**之前**，這支分支的附加元件會把它現在送的 payload（含 `providers`）整份拒絕：部署順序必須是**伺服器先、附加元件後**，或同時；否則新附加元件的使用者會一直看到「無法更新」直到伺服器更新。這一點 spec 只在 B2 提到測試版，沒有寫部署順序，請在發布時確認。
13. 伺服器部署後，舊的附加元件（test 版）會拒絕沒有 `providers` 的 payload（finding 6）——使用者已接受，只提醒。

---

## 七、使用者還沒確認的使用者可見預設

spec §4.2 標為「Decided by orchestrator with the recommended default; user may override before merge」的項目，以及改變使用者可見行為的 Ruling。merge 前請過目：

1. **P1 離線時 `providers == {}`**：離線／無快取／被拒 payload 時目錄完全是今天的樣子（只有 Coseeing、零 issue），記錄不會多六行 `unreferenced_provider`。
2. **P2 遠端 `coseeings` 與未知 key 靜默忽略**：不再記錄 `ignored_remote_coseeings`；自架伺服器多送什麼都不會在記錄留痕（但 `providers` 除外，B4 整份拒絕）。
3. **Ruling：含 `providers` 的 payload 在「測試...」顯示「伺服器的回應不是 WordBridge 模型清單。請確認網址是否正確。」**：對自架舊版伺服器的人，網址其實正確；沒有專屬的提示字串。
4. **P4 `bundled_source_failed`/`no_providers` 在「測試...」落到 `failed` 桶**：內建檔壞掉時使用者看到「請確認已連上網際網路，且網址正確。」，和網路問題同一句；記錄才看得出是 `bundled_source_failed`。這是壞掉的安裝，不是正常狀態。
5. **P3 `ignored_bundled_models`**：內建檔若帶 `models` 會記一行 lint（不計數）；今天的檔案沒有。
6. **P8／B4 舊快取**：測試版寫的快取在每次啟動被拒並記一行警告，直到一次成功抓取覆寫它；不刪、不遷移。
7. **Ruling：`GET /` 的 bytes 由伺服器重新序列化**（不再是原檔 bytes）：今天的檔案數字文字不變（V10）；日後若在檔案寫 `2.50` 會被送成 `2.5`，值相同。
8. **OQ1 → B 的後果**（使用者已決定，只提醒）：伺服器上 provider 名稱打錯（例如 `OpenAi`）時，那些模型從面板消失而**沒有**「N 個目錄項目無法載入」；只有記錄有 `unknown_provider`。全部打錯時才會變成抓取失敗（`remote_no_models`）。
9. **B3 與 incomplete 內建 entry 的計數**：內建檔一個 entry 壞掉時，面板那一行只算 1（`incomplete_provider`），雖然那個 provider 的 N 個模型都掉了（它們是 `unknown_provider`，不計）。同樣只會在壞掉的安裝發生。
10. **P6 allowlist 改成測試守門**：RC U2「使用者的 key 只送到允許的 host」現在由 `tests/test_catalog_bundled.py` 的 pinned URL 表與 RC9 host 表保證，執行期不再檢查；spec §4.2 已旗標供使用者反對。
11. **finding 5 自架清單失去 provider 覆寫**：包括 Ollama 的 port；B1 已接受。
12. **部署順序**（§六第 12 項）：伺服器先於附加元件。
