# Catalog retry、面板即時更新與網址對話框 — 最終審閱（DEVELOPMENT_WORKFLOW.md §3.3）

- **分支**：`feat/catalog-retry`（自 `main` @ `102b007` 開出），審閱範圍 `102b007..5ce394d`（37 個 commit）
- **Spec**：`docs/superpowers/specs/2026-11-04-catalog-retry-design.md`（使用者決定 R1–R13；orchestrator 預設 C1–C24），修訂 `docs/superpowers/specs/2026-11-04-remote-catalog-design.md`（取代 D9，更動 U3、D7、D8、D12、§12.5/U7、§13、§17）
- **Plan**：`docs/superpowers/plans/2026-11-04-catalog-retry.md`（15 個 task，三批；Task 10 以「Task 10 revision」改為 R13）
- **進度帳本**：`.superpowers/sdd/2026-11-04-catalog-retry/progress.md`
- **審閱者**：Fable 5.1，只讀程式碼，不修改原始碼、測試、spec 或 plan；突變測試在拋棄式 worktree 進行（`git worktree add --detach <scratchpad>/fable-cr 5ce394d`、`<scratchpad>/fable-cr2`，審閱後已 `git worktree remove`）
- **日期**：2026-11-04
- 路徑若無前綴，相對於 `addon/globalPlugins/WordBridge/`；NVDA 原始碼引用 `/workspace/nvda/source/...`。

---

## 一、總評

**可以在修完 1 個 Important 之後合併。** 沒有 Critical。

- 兩套測試在 HEAD 都是綠的（附加元件 **1037 passed / 1 skipped**，伺服器 **103 passed**），`prek` 全部 Passed，`git diff --check` 乾淨，`msgfmt --check` 通過，沒有 `Co-Authored-By`，沒有 stray file，`git status` 乾淨。
- 批次 3（Task 11–15）與 R13 重做沒有做過批次 review，所以我把突變集中在這兩塊：**自己做了 79 個突變，76 個被測試抓到，3 個存活**（表八）。存活的 3 個是帳本已經列為延後 Minor 的 M2、M3（只影響記錄一行／關機後等價），以及一個等價突變（R09，caption 沒變也重設一次）。
- 使用者決定 R1–R13 逐一核對都落地了（§二之 2），plan 的 Review Focus 五項都有對應測試且通過（§二之 6）。
- 唯一的 Important 是 **R4/R7 在「按過套用」之後失效**：`onSave` 不重算 D12 基準（`_restoredIndices`、`_keptUserPick`），所以使用者按「套用」存了 Y、又親手改回原本的 X 之後，清單一更新，面板會默默跳回 Y，按「確定」存的是 Y。我用探針測試重現（表八 P1），修法三行、另加一個測試；修法本身我也在拋棄式 worktree 驗過（表八 P2）。
- 帳本延後的 Minor 我逐條重新評估並親自驗證（§四），全部維持 Minor。
- 翻譯 21 條新字串與 spec §13／§20.5 逐字相同，用詞和 NVDA 的 zh_TW 一致（§二之 7）。純註解 commit `1341ccd` 我用 token 比對證明沒有改到任何程式 token（表八 V9）。

---

## 二、審閱重點逐項

### 1. 正確性與相對 `main` 的回歸

- **Updater（`catalog_updater.py`）**：重試狀態全部在主執行緒（`_retry_count`、`_retries_stopped`、`_retry_timer`、`_current_url`、`_user_initiated`、`_closed`、`_listeners`，`:229-237`），鎖仍只保護 generation／`_live_key`／`_source`／`_fetch`。`_schedule_retry()`（`:376-390`）照 spec §7.2 的虛擬碼：等待 = `1 * 2 ** count`，`> 32` 才停，等於 32 仍重試，「retries stopped」只記一次。`_on_retry_timer()`（`:392-402`）先查 `_closed`／shutdown，再在鎖內查「armed generation 是現在的 generation 而且 `fetch == failed`」，只有通過才清掉 `_retry_timer` 再 `refresh(self._current_url)`——所以 stale 的 handle 不會動到較新的 handle（突變 U13 證明有測試）。`refresh()`（`:259-286`）一開始就 `_cancel_retry_timer()`，key 不同時重設計數與 stopped（R10），`_user_initiated = changed`。`retry_on_panel_open()`（`:288-306`）只在 `fetch == failed` 時啟動，之後把 `_user_initiated` 設為 True（見 m7 的順序備註）。
- **Probe**（`:337-369`）：走 `validate_catalog_url` → `fetch_payload`（D4 參數）→ `parse_remote_payload` → `accept_remote_document`，不碰鎖、generation、cache、timer、listener、log；`disallowed_hosts` 以 `load_overlay_catalog(...).issues` 判斷。`_fetch_and_build` 在 fetch thread 做的事和它一樣，所以在任何執行緒呼叫都安全。
- **面板（`dialogs.py`）**：`makeSettings` 第一句就是 R1（`:201`），再讀狀態（`:234`）；兩條狀態列永遠存在、空時隱藏（`:230-238`）；`panelDescription` 跟著狀態列（`:238`、`:586`）。`_onCatalogChange`（`:393-407`）→ `_applyPendingUpdate`（`:409-445`）：一個 Freeze 裡更新狀態列、網址框、重建，最多送一次 layout event，延後時先排 300 ms 的輪詢再返回，**宣告永遠在重建之後、不在延後期間**。`_rebuild`（`:515-536`）不呼叫 `SetFocus()`、`Show()`、`onPanelActivated()`（突變 R19、M17/M18 證明）。
- **網址對話框（`catalog_url_dialog.py`）**：`onOk`（`:176-199`）照 spec §20.2 四步：驗證→身分比較→未測試／失敗警告（Yes 存、No 關不存、Cancel 留在對話框）→ 存、**先更新面板的唯讀框再關**（`:198-199`，對應 NVDA `_SetURLDialog.py:127-129`）。`_onTest`（`:133-148`）先驗證、再開 `IndeterminateProgressDialog`、再在 daemon thread 跑 `probe_url`，結果用 `wx.CallAfter` 送回（`:150-152`），`_onProbeDone`（`:154-165`）先查 `not self`，狀態只在欄位內容沒變時改（C21）。
- **相對 `main` 的回歸**：面板的 `isValid()` 與 `onSave` 的網址區塊移除（R12 要求）；`onSave` 現在只在值和 `stored_api_key()` 不同時才寫 key（`:711-716`），`{}` 維持 `{}`；`_refreshAccountInfo` 改走 `accountGroupSizerMap`（`:630-641`），不再對目錄沒有的 group 丟 `KeyError`。其餘 `main` 行為（U7 對話框、D12、報告、字典）沒有改變；既有測試全部還在而且通過。**回歸只有 I1**（在 `main` 上是潛在、在這支分支上因為即時更新而變成可見）。

### 2. Spec 符合度（每個使用者決定）

| 決定 | 落地位置 | 結果 |
| --- | --- | --- |
| R1 開面板時最後一次失敗就立刻抓 | `dialogs.py:201`、`catalog_updater.py:288-306` | ✅ `failed` 才啟動、`running/succeeded/off/invalid` 不動；`makeSettings` 一次一個 dialog；突變 R20（晚於讀狀態）被抓到 |
| R2 面板原地更新、不動焦點 | `dialogs.py:393-445, 515-536` | ✅ 無 `SetFocus`／`Show`／`onPanelActivated`；隱藏的面板照樣重建但不顯示；突變 R19 被抓到 |
| R3 「模型清單已更新。」／「模型清單更新失敗。」 | `dialogs.py:140-148, 441-445` | ✅ `ui.message(text)` 只帶文字（NORMAL）；突變 P12（多傳 priority）、P13（對調）被抓到 |
| R4/R7/C8 只保留使用者在面板選的 | `dialogs.py:553-568` | ✅ 六列表格測試；**但按「套用」之後基準不重算，見 I1** |
| R5 1,2,4,8,16,32 分鐘、常數 32、等於照做、超過就停 | `catalog_updater.py:29-32, 376-390` | ✅ 表格測試五個 max；`>`→`>=` 突變被抓到（帳本 M4） |
| R6 panel-open 失敗延續間隔、停了就不排 | `catalog_updater.py:304`（同 key 的 `refresh` 不重設） | ✅ `test_a_panel_open_failure_continues_the_schedule`、`..._after_retries_stopped_arms_nothing`；end-to-end 測試斷言 2 分鐘 |
| R8 只講使用者觸發的失敗 | `catalog_updater.py:283, 305`、`dialogs.py:399-404` | ✅ 事件表九列；突變 U05、P07 被抓到 |
| R9 U7 對話框不抓 | `__init__.py`（未改）、`test_the_switch_dialog_starts_no_fetch` | ✅ 對話框期間 thread 數、timer 都不變 |
| R10 改網址重設退避 | `catalog_updater.py:274-276` | ✅ 含切到空／無效網址；停了之後再改網址重跑整串；突變帳本 M5 被抓到 |
| R11 `panelDescription` | `dialogs.py:238, 586` | ✅ 七列狀態表 + 即時跟隨；突變 R17 被抓到 |
| R12 「變更...」對話框、對話框的確定才存 | `dialogs.py:354-374, 680-686`、`catalog_url_dialog.py` | ✅ 見 §二之 4 逐條；`onSave` 不再碰網址（`test_settings_ok_no_longer_saves_or_refreshes_the_url`） |
| R13 帳號方塊一次建好、固定順序、只顯示／隱藏／改標題 | `dialogs.py:83, 265-274, 594-641`、`settings_repository.py:113-118` | ✅ 建立順序 = sorted(SUPPORTED_PROVIDERS)+Coseeing；即時更新不建視窗、不 `MoveAfterInTabOrder`；讀 key 不寫入（NVDA `AggregatedSection.__contains__` 對不存在的 key 丟 `KeyError`，`config/__init__.py:1236-1241`，我核對過）；突變 R01–R10 全部被抓到 |

**Spec 的刻意偏離**都記在帳本為 `Ruling:`，評估見 §五。

### 3. 執行緒、timer 與面板生命週期

- **只有一個重試 timer**：只有 `_apply` 的失敗分支會 arm，每次 `refresh()` 先 cancel，`FakeScheduler` 在每次 arm 時斷言沒有別的 live handle；`close()` 先清 listeners 再 cancel 並吞例外（`:320-328`）。`terminate()` 先 `_shutdown.set()`（`__init__.py:384`），`catalog_updater.uninstall()` 在 `finally` 內自成一個 try（`:419-422`），所以 `_on_retry_timer`、`_apply`、`_schedule_retry` 在那之後都不做事（突變 U08、帳本 M9）。
- **延後輪詢 timer**：面板擁有，最多一個（`:435-436`，突變 P19），`_onPanelDestroy` 停掉（`:388-390`，突變 P20），任何一次通知跑完更新也停掉（`:438-440`，突變 P21）。
- **Probe thread**：daemon、具名（真的開 thread 的測試 `test_the_probe_thread_is_a_named_daemon`）；結果只經 `wx.CallAfter` 回主執行緒（突變 D15），對話框沒了就丟掉（突變 D17）。測試期間 `wx.ProgressDialog` 預設 `PD_APP_MODAL` 會停用所有視窗，所以使用者按不到「確定」，不會有「測到一半存檔」的競爭。
- **面板生命週期**：NVDA 的設定對話框非 modal、OK 走 `DestroyLater()`（`settingsDialogs.py:313-319`），所以 OK 之後 `_apply` 仍可能送到面板：`_onCatalogChange` 第一句 `if not self` 就自行註銷（`:395-398`，突變 R16）；真正銷毀時 `EVT_WINDOW_DESTROY` 以 `GetEventObject() is self` 分辨子視窗的事件（`:385-391`，NVDA 自己的 `_onWindowDestroy` 也註明 `ExpandoTextCtrl` 初始化時會送 destroy event，`settingsDialogs.py:345-355`），永遠 `evt.Skip()`。面板只在 `_getCategoryPanel` 建一次（`:657-683`），切類別只呼叫 `onPanelDeactivated/onPanelActivated`（`:730-747`），所以 R1 只跑一次。隱藏時不送 layout event（`_requestLayout`，`:495-505`；NVDA 的 handler 會把共用的 container 捲回頂端 `:722-728`），改在 `onPanelActivated` 補 `Layout()`。
- **網址對話框的生命週期**：`CatalogUrlDialog` 是 NVDA 公開的 `SettingsDialog`，和 NVDA 的 `_SetURLDialog` 一樣以 `ShowModal()` 開、`onOk` 走 `DestroyLater()`；modal loop 在 idle 處理 pending delete、`~wxDialog` → `Show(false)` → 結束 loop 時回傳 `SetReturnCode` 的值。NVDA 的 `SettingsDialog.__new__` 在**同類別的舊實例已銷毀但 Python 還抓著**時會丟 `RuntimeError`（`settingsDialogs.py:175-180`）。我檢查了所有會抓住這個對話框的東西：`onChangeCatalogUrl` 的區域變數、`wx.CallAfter` 的待處理事件（處理完即釋放）、probe thread（`Thread.run` 結束會 `del _target`）、NVDA `MessageDialog`（`ShowModal` 後自己 `_instances.remove` 並 `Destroy()`，`message.py:1134-1137`，不在 Python 端保留 parent）、`IndeterminateProgressDialog.done()` 會 `Destroy()`。沒有找到會把它留住的參照，和 NVDA 自己的用法相同，但「連續按兩次變更...」只能在 Windows 驗（§六第 18 項）。
- **C20**：對話框開著時的即時更新只會重建面板（在 modal 後面），`_findFocus()` 是對話框的欄位、不是面板的控制項，所以不會延後；設定對話框不是 active window，所以不講話（突變 P09）。

### 4. 網址對話框（R12、C16–C21）逐條

- OK 不變（含同 key 不同拼法）→ 不存、不 refresh（`test_ok_table[unchanged-*]`，突變 D01）。
- 有效且測過 → 存 strip 後的字串（突變 D02）、框先更新再關（D09）、`request_refresh` 一次、之後的失敗等 1 分鐘（`test_a_saved_url_refreshes_once_resets_the_backoff_and_updates_the_box` 用真的 updater，從計數 3 重設）。
- 未測試／失敗 → Warning Yes/No/Cancel（`MessageDialog`，`DialogType.WARNING`，`YES_NO_CANCEL`，預設焦點與 Escape 都是 Cancel：突變 D05、D06）；Yes 存、No 關不存（D04）、Cancel 留著（D03）；文案依狀態不同（D10）。
- 無效 → 錯誤訊息、留在對話框、焦點回欄位（D07）；空字串 → 直接存、不警告（D08）。
- Test：先驗證（D13）、「測試...」只在非空白時啟用（D12）、改字就回 untested（D11）、結果對應九種 `ProbeResult`（含 HTTP 狀態碼 D22、成功標題 D19）、不裝也不寫 cache（帳本 M10、`test_a_passed_test_then_ok_saves_without_a_warning` 斷言 `installed == []`）。
- 面板：唯讀 `ExpandoTextCtrl`＋「變更...」是最後兩個控制項、都是群組 StaticBox 的子視窗（P06）、Enter 開對話框、其他鍵 `Skip()`（P02）、取消或未存不 refresh（P01）、即時更新刷新框（P03）、空網址顯示「未設定模型清單網址」（P05）。

### 5. 測試是否真的抓得到（突變測試）

79 個突變（表八），76 個被抓到。批次 3 的每個分支（對話框 OK 的四步、Test 的執行緒與結果、面板的延後規則、宣告的四個條件、R13 的建立順序與 key 規則、C24、I1 的隱藏面板）各至少一個突變被抓到。存活的 3 個：U10、U11 是帳本延後的 M2、M3（見 §四），R09 是等價突變。另外帳本自己記錄的 T11e 存活也確認是等價（`_applyPendingUpdate` 自己會先查 `not self`）。

### 6. plan 的 Review Focus

| # | 項目 | 測試 | 結果 |
| --- | --- | --- | --- |
| 1 | 停掉的 timer 在新失敗之後才送達 | `test_a_stopped_timer_delivered_late_starts_nothing` | ✅；我另加突變 U13（stale 送達清掉較新的 handle）被抓到 |
| 2 | A→B→A 期間 A 的重試仍待命 | `test_a_retry_fetches_the_current_url_not_the_armed_one[a-b-a]` | ✅ |
| 3 | OK（DestroyLater）前後各一次更新 | `test_a_notification_after_the_panel_is_gone_unregisters_and_does_nothing`、`test_no_announcement_when[destroyed|inactive]` | ✅；突變 R16 被抓到 |
| 4 | 在留著的 box 裡打 API key 時清單到達 | `test_typed_api_keys_survive_a_rebuild`、`test_focus_in_a_box_that_stays_does_not_defer` | ✅；突變 P18 被抓到 |
| 5 | 類別被隱藏時到達、對話框之後維持 inactive | `test_a_rebuild_never_moves_focus_or_shows_the_panel[hidden]`、`test_no_announcement_when[hidden]`、`test_a_hidden_panel_sends_no_layout_event_and_lays_out_when_activated` | ✅；突變 P08、R15、R18 被抓到 |

### 7. 翻譯

`addon/locale/zh_TW/LC_MESSAGES/nvda.po` 新增 21 條（Task 12 五條、Task 13 十一條、Task 14 兩條、Task 15 兩條，另把「Model list URL」的 `#.` 改成群組標籤的說明），與 spec §13／§20.5 的建議譯文逐字相同，`msgfmt --check` 通過。用詞和 NVDA zh_TW 一致：「變更...」（`/workspace/nvda/source/locale/zh_TW/LC_MESSAGES/nvda.po:13771`）、「測試(&T)...」（`:12378`）、「警告」（`:6971`）、「成功」（`:12408`）；「正在驗證模型清單網址...」對應 NVDA 的「正在驗證 URL...」（`:12393`）的句型；「模型清單」「無法更新模型清單」沿用既有條目；兩句宣告依 C15 用全形句號。單複數兩條 msgstr 相同，中文本來就不分。語句自然，沒有需要改的地方。每個新的 `_(` 都有緊接在前一行的 `# Translators:` 註解（通用測試 `test_every_translatable_string_has_a_translators_comment` 涵蓋 `dialogs.py` 與 `catalog_url_dialog.py`，我另外用自己的 tokenizer 檢查相同）。純註解 commit `1341ccd`：去掉 COMMENT/NL/NEWLINE 的 token 串前後完全相同（3600 個 token），新增 32 行全是註解，唯一刪除的是一行沒有「Translators:」前綴的舊註解（改寫成有前綴的）。小瑕疵見 m6。

### 8. git / 流程限制

- 37 個 commit 都是英文 `<type>: <summary>` 加說明原因的內文；沒有 `Co-Authored-By`；最大的是 Task 12（512/18 行，含新模組、harness stub 與 24 個測試），其餘都在 400 行以下。
- `git diff --check 102b007..HEAD` 乾淨；變更只落在 `addon/`、`tests/`、`docs/`；`git status` 乾淨。
- 每個 commit 都綠：我在拋棄式 worktree 抽查了 `b7fec5d`（960/1）、`1341ccd`（979/1）、`080e848`（1003/1）、`db22fd0`（1020/1），與帳本記錄一致。
- `catalog_updater.py` 仍只 import 標準函式庫與 `.lib.catalog`；`catalog_url_dialog.py` 的 import 方向是 `dialogs → catalog_url_dialog`，沒有循環。
- NVDA 的 Python 3.13 限制：沒有用到 3.14 才有的語法或行為。

---

## 三、發現

### Critical

無。

### Important

#### I1. 按「套用」之後，親手改回原本的選擇會被下一次即時更新默默推翻（R4/R7 失效）

- **位置**：`dialogs.py:688-718`（`onSave` 存完不重算 `_restoredIndices`／`_storedSelectionResolved`／`_keptUserPick`）、`dialogs.py:553-568`（`_chooseSelection` 用開面板時算的 `_restoredIndices` 判斷 `touched`）。
- **情境**：stored 是 X（例如 `gpt-6.1-sol&OpenAI/local`，可解析）。使用者開面板，改選 DeepSeek 的第一個模型，按「套用」（存了 DeepSeek）；想一想又親手改回 X；這時背景重試成功（或 R1 的抓取完成），清單原地更新。`_chooseSelection` 看到「目前顯示 = 開面板時的基準 X」→ 判定**沒動過** → 改用「stored 解析後的值」= DeepSeek → 面板跳回 DeepSeek，NVDA 只說「模型清單已更新。」。使用者按「確定」→ 存的是 DeepSeek。使用者在這個面板親手選的 X 被丟掉，違反 R4 與 R7（「使用者在這個面板做的選擇」）。
  - 探針（表八 P1）：`touch(DeepSeek)`→`onSave()`→改回 X→`rebuild_with(同一份目錄)`，結果顯示的是 `deepseek-v4-pro&DeepSeek`。
  - 既有的 `test_the_baseline_is_reread_from_config_after_apply` 是直接改 `f.settings` 來模擬「套用」，沒有經過 `onSave`，所以抓不到。
  - 在 `main` 上同樣的 staleness 只影響 D12 的「跳過儲存」分支（stored 無法解析時，套用後改回基準再按確定不會存），是潛在問題；這支分支的即時重建讓它變成可見。
- **建議修法**（三行 + 一個測試）：`onSave` 的最後重算基準並清旗標——

  ```python
  # What is shown is now what is stored (or still protected by D12):
  # a later rebuild measures "touched" against this, not the open-time baseline.
  self._applyBaseline(self._storedBaseline(self.catalog))
  self._keptUserPick = False
  ```

  在 D12 的跳過分支裡什麼都沒存，重算得到相同的基準，所以不改變 D12／U7 的行為；存了東西的分支，新基準就等於剛存的值。我在拋棄式 worktree 套上這段：探針通過，`test_catalog_panel_live.py`、`test_catalog_settings_panel.py`、`test_catalog_plugin_wiring.py` 全綠，**只有** `tests/test_coseeing_auth_nvda.py::test_settings_save_preserves_coseeing_refresh_token_and_starts_selected_channel` 失敗（它用手工組出來的面板，沒有 `panel.catalog`）——修的時候給那個測試補 `panel.catalog = plugin.catalog`，或改用 `self.selection` 持有的目錄。測試：表八 P1 的探針（套用→改回→同一份目錄的即時更新→顯示仍是 X→`onSave()` 存 X）。
- **錯了的代價**：不修的話，「套用再改回」的使用者會存到錯的模型而沒有任何提示；這條路徑只需要套用、改回、再等一次清單更新，三者在離線→連線的情境下都很自然。

### Minor

依建議處理順序排列；帳本編號以「B1-n」「B2-n」標示（批次 1／批次 2 延後的 Minor）。m1–m3 修法便宜，建議合併前一起修。

#### m1. `makeSettings` 的 R1 呼叫沒有防護（B2-m6）

- **位置**：`dialogs.py:201`。
- **情境**：`retry_on_panel_open()` → `refresh()` → `threading.Thread.start()` 在系統資源不足時丟 `RuntimeError: can't start new thread`，整個 `makeSettings` 失敗，NVDA 的設定對話框對 WordBridge 類別顯示錯誤、使用者連設定都進不去。機率低但後果是整個面板。
- **建議修法**：`try: retried = catalog_updater.retry_on_panel_open() except Exception as error: log.warning(type only); retried = False`。一個測試：`retry_on_panel_open` 丟例外時面板仍建好、狀態列照常。

#### m2. `_schedule_retry` 裡 `schedule()` 丟例外時計數已加、失敗事件沒通知（B1-M5）

- **位置**：`catalog_updater.py:386-390`、`:518-519`。
- **情境**：`wx.CallLater` 只有在 wx app 不存在時才會丟（NVDA 關閉中），此時 `_retry_count` 已 +1、`_retry_timer` 是 None、`_apply` 的 `_notify` 被跳過，面板不會聽到那次失敗（開著的面板不說「更新失敗」）。正式環境幾乎不會發生。
- **建議修法**：把 `self._schedule(...)` 包在 `try/except Exception` 裡，記型別、把 `_retry_count` 減回去（或先排再加），讓 `_notify` 照常執行。

#### m3. `_rebuild` 先改 `self.catalog`／`self.selection` 再改控制項（B2-m5）

- **位置**：`dialogs.py:523-532`。
- **情境**：`SetItems` 或 `SetSelection` 中途丟例外時，`self.catalog` 已是新目錄、控制項還是舊的；下一次 `_chooseSelection` 會拿舊控制項的索引去查新目錄。只在 wx 失敗時發生。
- **建議修法**：把兩行指派搬到 `SetSelection` 之後（`_updateAccountCaptions`／`_refreshAccountInfo` 讀 `self.catalog`／`self.selection`，所以要放在它們之前）。

#### m4. 存活突變對應的兩個缺測試（B1-M2、B1-M3）

- **位置**：`catalog_updater.py:507-509`（成功時 `_retries_stopped = False`）、`:295-296`（`retry_on_panel_open` 的 shutdown 檢查）。
- **情境**：突變 U10（成功不重設 `_retries_stopped`）存活：之後再次用完整串時少記一行「retries stopped」，只影響記錄。突變 U11（`retry_on_panel_open` 不查 `_shutdown`）存活：正式環境 `terminate()` 同時 set shutdown 和 close，等價；只有測試裡單獨 `shutdown.set()` 才看得出來（會多開一個結果被丟掉的 thread）。
- **建議修法**：`test_a_success_resets_the_schedule` 加「再次用完後 STOPPED 記錄變 2」；`test_retry_on_panel_open_conditions` 加 `shut-down` 列。

#### m5. `retry_on_panel_open()` 在 `refresh()` 之後才設 `_user_initiated`

- **位置**：`catalog_updater.py:304-305`。
- **情境**：`refresh()` 已經啟動 fetch thread 並把 `_user_initiated` 設成 `changed`（False），回來才改成 True。正式環境結果一定經 `wx.CallAfter` 回主執行緒，所以 `_apply` 看到的一定是 True；但只要有人給 updater 一個同步的 `start_thread`＋`post_to_ui`（測試或日後重構），panel-open 的失敗就會被當成背景失敗而不講話。
- **建議修法**：`refresh(url, *, user_initiated=None)`，在 `refresh` 裡一次設定，`retry_on_panel_open` 傳 `True`。

#### m6. `nvda.po` 兩條 `#:` 行號過期；失敗訊息沒有錯誤圖示／音效

- `#: dialogs.py:358`（「Change...」）實際在 `:370`，`#: dialogs.py:643`（「No model list URL」）實際在 `:670`——Task 15 之後的位移；下次 `scons pot` + `msgmerge` 會自動修正。
- `_showError`／`_showResult` 的失敗用 `MessageDialog.alert`（標準型），不像 NVDA `_SetURLDialog` 的失敗用 `wx.ICON_ERROR`；帳本已裁定只差圖示／音效。要對齊的話改成 `MessageDialog(self, message, caption, dialogType=DialogType.ERROR, buttons=(DefaultButton.OK,)).ShowModal()`。列在 §七供使用者決定。

#### m7. 測試衛生（B1-M7）與 plan 勘誤（B1-M6）

- `test_module_retry_on_panel_open[no-updater]`、`test_module_probe_url[no-updater]` 應先 `uninstall()`，否則依賴前一個測試沒有留下 `_UPDATER`。
- plan 的 File Structure 把 `__init__.py` 的 seam 列在 Task 5，實際是 Task 6；文件勘誤。
- 帳本記的 B1-M8（`tests/test_report_output.py::test_a_failed_deletion_does_not_break_generation` 偶發）我這次四輪完整測試都沒遇到；不在本分支範圍，只記錄。

---

## 四、帳本延後 Minor 的重新評估

| 帳本 | 我的驗證 | 本文件 | 嚴重度 |
| --- | --- | --- | --- |
| B1-M2 成功重設 `_retries_stopped` 沒測 | 突變 U10 存活（411 passed） | m4 | Minor（只影響記錄） |
| B1-M3 `retry_on_panel_open` 的 shutdown 檢查沒測 | 突變 U11 存活（411 passed） | m4 | Minor（正式環境等價） |
| B1-M5 `schedule()` 丟例外 | 由程式碼推定；只在 wx app 消失時發生 | m2 | Minor |
| B1-M6 plan 勘誤 | 確認 | m7 | Minor（文件） |
| B1-M7 no-updater 測試先 `uninstall()` | 確認 | m7 | Minor（測試衛生） |
| B1-M8 偶發測試 | 四輪完整測試未重現 | m7 | 記錄 |
| B2-m5 `_rebuild` 指派順序 | 由程式碼確認 | m3 | Minor |
| B2-m6 R1 呼叫沒防護 | 由程式碼確認 | m1 | Minor，建議合併前修 |
| B2-m1、m2、m3、m4、m7、I1、I2 | 已修（`b7fec5d`、`d5f5d6e`、`a59944f`、`6bffacb`、`f2a847b`），我用自己的突變 R04/R05/R10、R15/R18、R11/R12 重新證實 | — | 已處理 |

---

## 五、帳本 Ruling 的評估

| Ruling | 評估 |
| --- | --- |
| Task 2 的 `-k` 漏選一個測試、另選到 success 列 | 合理，plan 的筆誤，測試集如 plan |
| Task 4 listeners 測試拆成 success/failure 兩列 | 合理 |
| C22 在 Task 9 以額外一列實作 | 合理；`_keptUserPick` 的兩端後來由 I2（`6bffacb`）釘住，我的突變 R11、R12 證實 |
| C23 通用測試放在 Task 12、既有字串以純註解 commit 補註解 | 合理；token 比對證明只加註解（表八 V9） |
| 批次 1 M4（listener 自行註銷）在 Task 8 釘住 | 合理，面板的 listener 正是如此 |
| Task 9 的數量勘誤、M15 由另一個測試抓到 | 合理（我的突變 R11 也抓到 stale 基準的一種） |
| Task 10：`_make_panel` 不再把 `_refreshAccountInfo` 換成 no-op | 合理而且必要 |
| R13：key 只在值和 `stored_api_key()` 不同時才寫 | 合理；代價只是「無法刻意存一個空白條目」，沒有行為依賴它。列在 §七 |
| R13：`api_key()` 保留 create-on-read | 合理（既有行為，只影響實際用到的 provider） |
| C24 在開面板時用 `retry_on_panel_open()` 的回傳值 | 合理；`cache/running` 只會在 R1 從 `cache/failed` 啟動時出現，我的突變 R14 證實有測試 |
| I1 隱藏面板只呼叫自己的 `Layout()` | 可接受；NVDA 切回類別時會對 container `Layout()`＋`SetupScrolling()`（`settingsDialogs.py:744-746`），列為手動項目 11 |
| Task 11 多一個測試、row id 改名 | 合理 |
| Task 12：24 個測試；警告用 `MessageDialog` + `DialogType.WARNING` | 合理，與 NVDA 的 `wx.ICON_WARNING` 對應 |
| Task 12：「否」以 OK 關閉但不存 | 合理，`_SetURLDialog.py:97-131` 相同；列在 §七 |
| Task 12：Test 按鈕放在欄位的 containing sizer、欄位值在建構時給 | 合理，`_SetURLDialog.py:79-91` 相同 |
| Task 13：17 個測試；`_onTest` 遇到無效網址也把焦點放回欄位 | 合理 |
| Task 14：對話框 seam 是模組全域 `dialogs.CatalogUrlDialog` | 合理 |
| Task 14：`ExpandoTextCtrl` 在 `makeSettings` 內 import | 合理（NVDA 一定有 `wx.lib.expando`，`settingsDialogs.py` 自己也用） |
| Task 14：框與按鈕是群組 StaticBox 的子視窗 | 合理，`settingsDialogs.py:950-957` 相同；物件導覽層級由手動項目 7b 驗 |
| Task 15：end-to-end 測試斷言 2 分鐘而非 plan 的 1 分鐘 | **正確**，R6 就是這樣；plan 寫錯 |
| Task 15：`test_no_announcement_when` 兼驗「被丟掉的宣告不會之後再講」 | 合理，spec §11 的要求 |

---

## 六、Windows／NVDA 尚未驗證的手動項目

Linux 上只驗了注入的邊界（假的 scheduler、假的 `winUser.sendMessage`、stub 的 wx 控制項）。以下項目需要在 Windows 用這支分支打包的附加元件實測（spec §15.6 的 1–13 含 3a、7a、7b；§20.7 的 14–17；審閱時新增 18–22）。本地伺服器 `http://localhost:8000` 可停可開：

1. 伺服器停、無快取、啟動 NVDA：記錄先有失敗，再有 `retry scheduled attempt=1 delay=1min`；一分鐘內開伺服器，約一分鐘後記錄出現「catalog fetched」；stored 本機模型的使用者按 NVDA+Alt+O 直接校正，不出 U7 對話框、不用重啟。
2. 伺服器一直停：attempts 1–6、delay 1,2,4,8,16,32，約 63 分鐘後 `retries stopped attempts=6`；伺服器記錄沒有更多請求。
3. 第 2 項之後開 WordBridge 面板：一個請求，狀態列先說載入中（無快取）再說失敗，NVDA 說「模型清單更新失敗。」；之後沒有定時請求（R6）。
3a. 第 2 項之後改存另一個網址（例如也停掉的 `http://localhost:8001`）：記錄再出現 `retry scheduled attempt=1 delay=1min` 並跑完整串（R10）；只有存檔那次說「模型清單更新失敗。」，定時重試不說（R8）。
4. 面板開著、焦點在「服務提供者」（收合）時伺服器恢復：provider 出現、選的值不變、焦點不動，NVDA 說一次「模型清單已更新。」且不打斷正在讀的內容。記下項目被替換時 NVDA 讀了什麼（spec §18 的風險：替換焦點所在的 combo box 的項目可能讓 NVDA 重讀值）。
5. 同上但下拉清單打開（Alt+Down）：清單開著時不變；Escape/Enter 後更新與訊息才來。
6. 焦點在新清單已不提供的 provider 的 API key 欄位：Tab 離開之前什麼都不變，之後方塊換掉、焦點不跳。
7. provider 出現後 Tab 順序：服務提供者、模型、所選 provider 的 API key、語言、……、「模型清單網址」群組最後；NVDA+B 只在狀態列可見時讀到它。
7a. （R13）物件導覽（NVDA+小鍵盤 4/6）和 Tab 順序都和畫面一致：模型之後是所選 provider 的方塊（群組名、再「API Key:」或「clean」），再來語言；隱藏的方塊兩者都跳過；每個 provider 輪流選一遍、即時更新前後順序都不變。
7b. NVDA+B 與物件導覽對每個帳號方塊讀出群組名與它自己的欄位／按鈕，不會讀到隱藏方塊的控制項；HWND z-order 是 §10.4 的建立順序：狀態列與掉落條目列在服務提供者之前、網址群組最後。
8. WordBridge 面板開著但顯示別的類別、或別的程式在前面時抓取完成：不講話；切回來看到新清單。
9. 套用／存了新網址：清單靜默切換；抓取完成後更新與訊息跟著來。改網址後按「確定」關掉對話框：之後沒有訊息。
10. 重試待命時關閉 NVDA：立刻結束，記錄沒有 WordBridge 錯誤。
11. 低視能：只換項目的更新不捲動面板；換顯示方塊的更新像選 provider 一樣重排；快取在用、伺服器停：「無法更新模型清單……」那一行在每次重試都不動（C24）；WordBridge 面板開著但顯示別的類別且往下捲時，重試或新清單不會把那個類別捲回頂端（I1）；切回 WordBridge 時版面正確（Ruling：只呼叫面板自己的 `Layout()`）。
12. 點字：兩句訊息在點字顯示器閃現。
13. 無障礙描述（R11）：伺服器停、無快取，從別的類別 Tab 或方向鍵進入 WordBridge 類別與面板：NVDA 把狀態列當面板描述讀出；即時更新改了狀態後再進出一次讀到新描述，清單正常載入後沒有描述。
14. Tab 到「模型清單網址」群組：NVDA 讀群組名、唯讀框的網址（或「未設定模型清單網址」）、再「變更...」。
15. 在框裡按 Enter 開「設定模型清單網址」，焦點在欄位；「測試...」顯示進度對話框（「正在驗證模型清單網址...」）再顯示結果，兩者都唸出；測試通過後按確定關閉，焦點回到框、框已經讀新網址。
16. 未測試就按確定：Warning Yes/No/Cancel 唸出、焦點在取消；Escape 回到網址對話框。
17. 存了新網址後在 NVDA 設定對話框按取消：新網址仍在（NVDA+Alt+W 再開看得到）。
18. **（新增）**連續開關「變更...」對話框（確定存檔、取消、測試後確定、警告選否各一次，之後再開一次）都能開，記錄沒有 NVDA 的 `RuntimeError: Cannot open new settings dialog while instance still exists`（`settingsDialogs.py:175-180` 的守門；Python 端找不到會留住對話框的參照，但只能實測）。
19. **（新增）**按 OK 關閉 NVDA 設定對話框後約一秒內清單才到達（例如 R1 的抓取還在跑）：記錄沒有錯誤、沒有講話（`_onCatalogChange` 的 `if not self` 依賴 wxPython 對已銷毀視窗的 `__bool__`）。
20. **（新增）**「測試...」跑的那幾秒（伺服器睡 10 秒）：進度對話框期間按不到網址對話框的確定／取消（`wx.ProgressDialog` 預設 app-modal）；結果出來後對話框恢復可用。
21. **（新增）**在網址對話框開著時清單到達（例如把伺服器開起來再按變更...）：面板在後面更新但不講話；關閉對話框後面板已是新清單；若在警告或結果訊息框開著時到達也一樣。
22. **（新增）**在面板的唯讀框有焦點時發生即時更新（網址沒變）：NVDA 不重讀框（`SetValue` 只在值變了才呼叫）。

---

## 七、使用者還沒確認的使用者可見預設

以下是 spec 標為「Decided by orchestrator with the recommended default; user may override before merge」的項目，以及會改變使用者可見行為的 Ruling。merge 前請過目：

1. **C1 哪些失敗會重試**：所有到達 `_apply` 的失敗（網路／TLS／DNS、逾時、所有非 200 含 3xx、過大、格式錯、schema 版本、沒有可用模型含「全部 provider 被擋」）都重試；有 provider 被丟掉的成功、快取寫入失敗都算成功，不重試。
2. **C2**：有快取在用時（`source=cache`）照樣重試。
3. **C5**：R1 只在 `makeSettings`（每次設定對話框一次）跑；同一個對話框裡切回 WordBridge 類別不再抓；待命的 timer 會被取消、立刻抓。
4. **C7**：面板也在類別被隱藏時更新；下拉清單開著、或焦點在會被隱藏的 API key 欄位／clean 按鈕時延後（每 300 ms 再看一次）。
5. **C10**：「N 個目錄項目無法載入」那一行也即時更新；兩條線永遠存在、空時隱藏。
6. **C11**：只在面板是顯示中的類別且設定對話框是 active window 時講；延後時先等重建；排隊的多個結果只講最後一個；不能講時直接丟掉、不補講。
7. **C12**：沒有新的狀態列文字（不顯示「x 分鐘後重試」）。
8. **C15**：兩句宣告用全形句號。
9. **C16**：不用 NVDA 私有的 `_SetURLDialog`；「測試...」走 WordBridge 自己的抓取與接受檢查（D4 的 5/10/20 秒、1 MiB、不跟轉址、host allowlist、至少一個本機模型），不安裝、不寫快取。
10. **C17**：驗證移到對話框的確定；「有沒有變」用既有的 `_url_identity`（同 key 不同拼法視為沒變）；存 strip 後的原文。
11. **C18**：空網址仍允許，唯讀框顯示「未設定模型清單網址」；「測試...」只在非空白時啟用；群組仍是面板最後一項。
12. **C19／§20.5 文案與譯文**（§二之 7 已核對）。
13. **C20**：對話框開著時面板照樣更新但不講話；每次更新也刷新唯讀框。
14. **C21**：測試結果只對當時測的文字有效；改了字就回「未測試」。
15. **C22**：被即時重建保留的使用者選擇是「黏」的：之後就算親手改回基準再按確定也會存（Coseeing 基準會啟動登入）；只有重建退回基準時才清掉。（修 I1 時「套用」也會清掉這個旗標。）
16. **C24**：快取在用時，同 key 的重試（timer 或 R1）讓「無法更新模型清單，WordBridge 使用先前儲存的清單」那一行留著不閃；改網址或成功才清。
17. **Ruling：API key 只在和已存的值不同時才寫**：沒用過的 provider 空欄位不會產生空白條目；清空欄位會存成空字串。
18. **Ruling：警告對話框是 NVDA `MessageDialog` 的 WARNING 型（有警告音效）；「否」關閉網址對話框但不存**（和 NVDA 的更新鏡像對話框相同）。
19. **Ruling：無效網址的錯誤與測試失敗的訊息用標準型 `alert`**，沒有錯誤圖示／音效（NVDA 的鏡像對話框失敗時有）。見 m6。
20. **Ruling：隱藏時的版面只在切回時呼叫面板自己的 `Layout()`**（手動項目 11）。
21. **R6／R10 的組合**（使用者已決定，只是提醒結果）：重試用完後，開面板只抓一次、失敗不再排；改網址則整串重來。

---

## 八、審閱者自行驗證的項目

| # | 指令 / 動作 | 結果 |
| --- | --- | --- |
| V1 | `cd /workspace/WordBridge-catalog-retry && <testvenv>/python -m pytest -q --ignore-glob='tests/test_integration_*' tests` | **1037 passed, 1 skipped, 3 subtests passed**（20.38 s） |
| V2 | `cd server && /workspace/WordBridge/server/.venv/bin/python -m pytest -q` | **103 passed** |
| V3 | `prek run --all-files` | 3/3 Passed |
| V4 | `git diff --check 102b007..HEAD` | 乾淨 |
| V5 | `msgfmt --check -o /dev/null addon/locale/zh_TW/LC_MESSAGES/nvda.po` | OK |
| V6 | `git log 102b007..HEAD --format=%B \| grep -ci co-authored` | 0 |
| V7 | `git diff --name-only 102b007..HEAD` 篩掉 `addon/ tests/ docs/`；`git status --short` | 無 stray file；工作樹乾淨 |
| V8 | 37 個 commit 都有英文 `<type>: <summary>` 與內文 | 37/37 |
| V9 | `1341ccd` 的 token 比對（去掉 COMMENT/NL/NEWLINE/INDENT 後 `tokenize` 串前後比較） | 完全相同（3600 token）；新增 32 行全是註解，刪除 1 行舊註解 |
| V10 | 批次 3 與 R13 中間 commit 的附加元件測試（拋棄式 worktree）：`b7fec5d`、`1341ccd`、`080e848`、`db22fd0` | 960/1、979/1、1003/1、1020/1，與帳本一致 |
| V11 | `nvda.po` 新條目 `#:` 行號對實際行號 | 21 條中 19 條正確，2 條過期（m6） |
| V12 | NVDA `AggregatedSection.__getitem__/__contains__`（`config/__init__.py:1179-1241`）對 `api_key` 子鍵不存在的行為 | 快取 `KeyError` 並丟出，不建立條目 → `stored_api_key` 不寫入 |
| V13 | NVDA `SettingsDialog.__new__`／`_onWindowDestroy`（`settingsDialogs.py:159-182, 345-355`）、`MessageDialog.ShowModal/alert`（`message.py:830-853, 1130-1137`）、`IndeterminateProgressDialog`（`gui/__init__.py:968-975`）、`_SetURLDialog`（`:60-131`）、General 面板鏡像群組（`:938-1004, 1125-1133`） | 對話框模式、`DestroyLater`＋`ShowModal`、`alert` 參數、`associateElements(TextCtrl, Button)`、`ReturnCode` 為 `IntEnum` 都與實作相符 |
| V14 | `grep` NVDA zh_TW po：「變更...」「測試(&T)...」「警告」「成功」 | 與新譯文一致 |
| P1 | 探針測試：stored X，`touch(DeepSeek)`→`onSave()`→改回 X→同一份目錄的 `rebuild_with` | 顯示變成 `deepseek-v4-pro&DeepSeek`（**I1**） |
| P2 | 在拋棄式 worktree 套上 I1 的建議修法再跑 P1 與面板／wiring 測試 | P1 通過；212 passed、1 failed（手工組面板的既有測試缺 `panel.catalog`，見 I1） |
| D01 | `onOk` 不比較身分（沒變也存） | KILLED：1 failed（`test_ok_table[unchanged-same]`） |
| D02 | `onOk` 存未 strip 的原文 | KILLED：1 failed |
| D03 | 警告選 Cancel 仍存 | KILLED：1 failed（`[untested-cancel]`） |
| D04 | 警告選 No 不關對話框 | KILLED：1 failed（`[untested-no]`） |
| D05 | 警告預設焦點 Yes | KILLED：1 failed |
| D06 | 警告 Escape = No | KILLED：1 failed |
| D07 | `onOk` 跳過驗證 | KILLED：1 failed（`[invalid-malformed]`） |
| D08 | 空網址也警告 | KILLED：1 failed（`[empty]`） |
| D09 | 先關對話框再更新框 | KILLED：1 failed |
| D10 | 失敗／未測試用同一句警告 | KILLED：1 failed |
| D11 | 改字不重設 passed | KILLED：1 failed |
| D12 | 「測試...」永遠啟用 | KILLED：1 failed |
| D13 | Test 不先驗證 | KILLED：1 failed |
| D14 | probe 在 UI 執行緒 inline 跑 | KILLED：1 failed |
| D15 | 結果不經 `wx.CallAfter` | KILLED：1 failed |
| D16 | 文字改了仍設狀態 | KILLED：1 failed |
| D17 | 對話框沒了仍處理結果 | KILLED：1 failed |
| D18 | 進度對話框不 `done()` | KILLED：1 failed |
| D19 | 失敗標題用「Success」 | KILLED：1 failed |
| D20 | probe thread 非 daemon | KILLED：1 failed |
| D21 | `postInit` 不設焦點 | KILLED：1 failed |
| D22 | HTTP 狀態碼提示漏掉狀態碼 | KILLED：1 failed |
| U01 | probe 的 models 把 Coseeing 也算進去 | KILLED：1 failed（`test_probe_result_table[ok]`） |
| U02 | probe 對空網址也抓 | KILLED：1 failed |
| U03 | probe 把 `http_status` 當 network | KILLED：1 failed |
| U04 | probe 把 disallowed 當 no_models | KILLED：1 failed |
| U05 | `refresh` 一律 user-initiated | KILLED：1 failed（`test_change_events_table`） |
| U06 | 失敗先通知再 arm | KILLED：1 failed |
| U07 | `close()` 不清 listeners | KILLED：1 failed |
| U08 | `_schedule_retry` 不查 `_closed` | KILLED：1 failed |
| U09 | `retry_on_panel_open` 不查 `_closed` | KILLED：1 failed |
| U10 | 成功不重設 `_retries_stopped`（帳本 M2） | **SURVIVED**（411 passed）→ m4 |
| U11 | `retry_on_panel_open` 不查 shutdown（帳本 M3） | **SURVIVED**（411 passed）→ m4 |
| U12 | panel-open 記錄寫完整網址 | KILLED：1 failed |
| U13 | stale timer 送達時清掉較新的 handle | KILLED：1 failed |
| P01 | 取消對話框仍 refresh | KILLED：1 failed |
| P02 | 框裡任何鍵都開對話框 | KILLED：1 failed |
| P03 | 即時更新不刷新框 | KILLED：1 failed |
| P04 | 框不是唯讀 | KILLED：1 failed |
| P05 | 空網址顯示空字串 | KILLED：1 failed |
| P06 | 框與按鈕的父視窗是面板 | KILLED：1 failed |
| P07 | 任何失敗都講 | KILLED：1 failed（`[failure-timer]`） |
| P08 | `_canAnnounce` 不看 `IsShown` | KILLED：1 failed（`[hidden]`） |
| P09 | `_canAnnounce` 不看 `IsActive` | KILLED：1 failed（`[inactive]`） |
| P10 | 不能講時留著下次講 | KILLED：1 failed |
| P11 | 延後期間就講 | KILLED：1 failed |
| P12 | `ui.message` 多傳 priority | KILLED：1 failed |
| P13 | 兩句宣告對調 | KILLED：1 failed |
| P14 | 背景失敗覆蓋待講的宣告 | KILLED：1 failed |
| P15 | `_mustDefer` 不看下拉 | KILLED：1 failed |
| P16 | 只看 provider 的下拉 | KILLED：1 failed（`[model]`） |
| P17 | `_mustDefer` 不看焦點 | KILLED：1 failed |
| P18 | 焦點在顯示中的方塊就一律延後 | KILLED：1 failed |
| P19 | 堆疊多個輪詢 timer | KILLED：1 failed |
| P20 | 銷毀不停輪詢 | KILLED：1 failed |
| P21 | 通知跑完更新不停輪詢 | KILLED：1 failed |
| P22 | `_isDroppedDown` 例外時回 True | KILLED：1 failed（`[absent]`） |
| P23 | Win32 訊息碼錯 | KILLED：1 failed |
| P24 | 狀態列也延後 | KILLED：1 failed |
| R01 | 方塊依目錄的 group 建 | KILLED：1 failed（`[bundled]`） |
| R02 | Coseeing 方塊排第一 | KILLED：1 failed |
| R03 | provider 不排序 | KILLED：1 failed |
| R04 | 欄位用 `api_key()` 填（寫空白） | KILLED：1 failed（`[open]`） |
| R05 | `onSave` 每個欄位都寫 | KILLED：1 failed（`[untouched-ok]`） |
| R06 | `onSave` 跳過清空的 key | KILLED：1 failed（`[cleared]`） |
| R07 | `_refreshAccountInfo` 走目錄的 group | KILLED：1 failed |
| R08 | caption 永不更新 | KILLED：1 failed |
| R09 | caption 沒變也 `SetLabel` | **SURVIVED**（169 passed）— 等價突變，不列為發現 |
| R10 | `stored_api_key` 寫入空白 | KILLED：1 failed |
| R11 | `touched` 不看 `_keptUserPick` | KILLED：1 failed |
| R12 | `_rebuild` 永不清 `_keptUserPick` | KILLED：1 failed |
| R13 | C24 的 keepStale 不看 `catalog_changed` | KILLED：1 failed |
| R14 | 開面板時不看 `retried` 一律 keep_stale | KILLED：1 failed |
| R15 | 隱藏時也送 layout event | KILLED：1 failed |
| R16 | `_onCatalogChange` 沒有 `not self` 守門 | KILLED：1 failed |
| R17 | 即時更新不改 `panelDescription` | KILLED：1 failed |
| R18 | `onPanelActivated` 不補 `Layout()` | KILLED：1 failed |
| R19 | 重建時 `SetFocus()` | KILLED：1 failed |
| R20 | R1 晚於讀狀態 | KILLED：1 failed（end-to-end） |

沒有執行 `tests/test_integration_*`。沒有啟動任何本機伺服器。pytest 一律單一 worker，MemAvailable 全程高於 4.7 GB。兩個拋棄式 worktree 在審閱結束時以 `git worktree remove` 移除。

---

## 修正記錄

修正者：fix agent（DEVELOPMENT_WORKFLOW.md §3.4），自 `792a966` 起，分支 `feat/catalog-retry`。每一項都先寫會失敗的測試（red）再修（green）；每個 commit 前都跑了附加元件測試、伺服器測試、`prek run --all-files`、`git diff --check`、`msgfmt --check`。進度帳本另記了 Ruling（`.superpowers/sdd/2026-11-04-catalog-retry/progress.md` 的「Final review fix round」）。

| 發現 | Commit | 說明 |
| --- | --- | --- |
| I1 | `805a14e` | `onSave` 最後 `_applyBaseline(self._storedBaseline(self.catalog))` 並清掉 `_keptUserPick`。表八 P1 的探針寫成 `test_a_pick_made_after_apply_survives_a_rebuild`（修前顯示 `deepseek-v4-pro&DeepSeek`，修後是 X、按確定存 X）；另加 `test_apply_moves_the_baseline_to_what_it_saved`（套用後基準＝剛存的值、旗標清掉）與 `test_apply_keeps_the_d12_baseline_when_it_saved_no_selection`（D12 跳過分支的基準不變，修前修後都綠，防回歸）。手工組的面板測試補 `panel.catalog`。突變：拿掉重算基準 → 2 failed；拿掉清旗標 → 1 failed。 |
| m1 | `7669519` | `makeSettings` 的 R1 呼叫包在 `try` 裡，`log.warning` 只記例外型別（D15），面板照常建好、狀態列照讀。測試 `test_a_raising_panel_open_retry_still_builds_the_panel`（例外訊息含網址與 token，記錄只有 `RuntimeError`）。 |
| m2 | `ddc3fba` | `schedule()` 包在 `try` 裡：丟例外時記型別、不加計數、不設 timer，`_apply` 照常通知失敗；計數改在 timer 排好之後才加。測試 `test_a_raising_scheduler_keeps_the_count_and_still_notifies`（之後正常排的第一次仍是 attempt=1、1 分鐘）。突變「重新丟出」與「失敗路徑也加計數」都被抓到。 |
| m3 | `2492b29` | `_rebuild` 在 `SetItems`／`SetSelection` 之後、帳號方塊之前才指派 `catalog`、`selection`，以及 D12 基準與 `_keptUserPick`（見 Ruling）。測試 `test_a_failing_widget_update_leaves_the_panel_on_the_old_catalog`（`SetItems` 丟例外時狀態全不變；恢復後的下一次更新選到正確的 X）。 |
| m4 | `01d55ba` | `test_a_success_after_retries_stopped_lets_the_next_schedule_log_its_stop`（再次用完後 STOPPED 記錄兩次）與 `test_retry_on_panel_open_conditions[shut-down]`。突變 **U10、U11 修前存活（1043 passed）、修後各 1 failed，已殺死。** |
| m5 | `83e4e0d` | 照建議改成 `refresh(url, *, user_initiated=None)`，在啟動 thread 之前一次設定；`retry_on_panel_open` 傳 `True`。測試 `test_user_initiated_is_set_before_a_synchronous_fetch_completes`（同步的 `start_thread`＋`post_to_ui`：panel-open／改網址為 True、timer 為 False；修前 panel-open 列失敗）。 |
| m6（圖示） | `0d8e660` | 網址對話框的兩種錯誤——無效網址與「測試...」失敗——都改成 `MessageDialog(self, message, caption, dialogType=DialogType.ERROR, buttons=(DefaultButton.OK,)).ShowModal()`；成功仍是標準 `alert`（與 NVDA `_SetURLDialog` 相同）。修前 8 個測試失敗（錯誤一個、失敗結果七列）。 |
| m6（`#:`） | `0d30e08` | 本分支新增條目中過期的 `#:` 全部改到 msgid 目前所在行：審閱點名的「Change...」「No model list URL」，另有「Model list URL」（Task 14 起就過期，審閱沒列出），以及這輪修正讓 `dialogs.py` 下移 7 行、`catalog_url_dialog.py` 下移 10 行而過期的 5 條，共 8 條。只改參照，msgid／msgstr 不變；`msgfmt --check` 通過。分支之前就有的條目照 Task 12 的 orchestrator 指示不動。 |
| m7（測試衛生） | `f6a33db` | 兩個 `[no-updater]` 測試先 `uninstall()`。red 用 scratchpad 的測試證明：先裝一個失敗狀態的 updater，兩個測試修前都失敗、修後都通過。 |
| m7（plan 勘誤） | `7e6e277` | plan 的 File Structure：`__init__.py` 的 seam 改為 Task 6。 |
| m7（B1-M8 偶發測試） | 未修 | 不在本分支範圍；這輪的完整測試都沒有重現。列為未確認的預設：維持原狀。 |

**沒有修的項目**：只有 B1-M8（上表）。R09 是等價突變，照審閱不列為發現。

**新的 Ruling**（帳本有完整的「Ruling: 決定 — 理由 — 錯了的代價」）：

1. m6 讓網址對話框的**兩種**錯誤都用 `DialogType.ERROR`（指示只點名測試失敗）；取代 Task 12「無效網址的錯誤用標準 `alert`」的 Ruling。理由：同一個對話框只有一種錯誤訊息樣式，NVDA 的失敗訊息是 `wx.ICON_ERROR`。錯了的代價：打錯網址時會有 Windows 錯誤音效；改回只要一行。
2. m3 除了 `catalog`／`selection`，也把 D12 基準與 `_keptUserPick` 移到控制項更新之後；四者描述的都是控制項顯示的內容。代價：無。
3. m2 改成「排好 timer 才加計數」，而不是失敗後再減回；結果相同。代價：無。
4. m6 的 `#:` 修了本分支新增條目中全部 8 條過期的，不只點名的 2 條。代價：無，`scons pot`＋`msgmerge` 本來就會重寫。

**新的使用者可見預設**（取代 §七第 19 項）：

- 網址對話框的「無效網址」錯誤與「測試...」失敗的訊息，現在有 NVDA 的錯誤圖示與 Windows 錯誤音效（`DialogType.ERROR`）；測試成功仍是沒有圖示與音效的一般訊息。手動驗證：§六第 15、16 項時順便確認兩種錯誤都有錯誤音效、NVDA 照常讀出標題與訊息。
- §七第 15 項（C22）的括號現在成立：按「套用」會重算 D12 基準並清掉「黏」的使用者選擇；套用之後親手改的選擇，在下一次即時更新時會保留，按「確定」會存（R4／R7）。

**最終驗證**（`7e6e277`）：

| 項目 | 結果 |
| --- | --- |
| 附加元件 `pytest -q --ignore-glob='tests/test_integration_*' tests` | **1048 passed, 1 skipped**, 3 subtests passed（基準 1037＋這輪 11 個新測試） |
| 伺服器 `pytest -q` | **103 passed** |
| `prek run --all-files` | 3/3 Passed |
| `git diff --check` | 乾淨 |
| `msgfmt --check` | 通過 |

附註：修 m4 之前確認 U10／U11 存活的那兩次突變執行，誤把 `tests` 整個傳進去，收進了 `tests/test_integration_*`；24 個整合測試全部在 credentials fixture 因為沒有 `TEST_*_API_KEY` 而 skip，沒有呼叫任何 provider。其餘每次執行都帶了 `--ignore-glob`。pytest 一律單一 worker，MemAvailable 全程高於 4.3 GB；沒有留下背景程序。
