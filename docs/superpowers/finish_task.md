# P1/P2 修正批次 — 完成報告

- **分支**：`p1-p2-fixes`
- **Spec**：`docs/superpowers/specs/2026-09-21-p1-p2-fixes-design.md`
- **Plan**：`docs/superpowers/plans/2026-09-21-p1-p2-fixes.md`
- **執行方式**：Subagent-Driven Development。每個 task 由 implementation subagent（claude-sonnet-5, high）實作，再由獨立 review subagent（claude-opus-5, high）審閱；有發現就退回修正並重新審閱，直到 review 無 Critical/Important 為止。
- **日期**：2026-09-21

---

## 一、結果摘要

| 項目 | 執行前 | 執行後 |
| --- | --- | --- |
| 非整合測試 | 238 passed / **2 failed** / 1 skipped | **308 passed / 0 failed / 0 errors** / 1 skipped / 16 deselected |
| 測試輸出 | — | pristine（無任何 warning） |
| 附加元件封裝（壓縮後） | 37.34 MiB | **8.16 MiB**（−29.18 MiB） |
| 附加元件封裝（未壓縮） | 54.57 MiB | **24.57 MiB**（−30.00 MiB） |
| NVDA 啟動時解析 3.6MB CSV | 是 | 否（改為首次使用時延遲載入） |

最終全分支審閱（claude-opus-5，14 個 commit、約 122KB diff，分三輪閱讀）判定為 **Ship**：**0 Critical、0 Important**。

---

## 二、本次新增的 commit list

依提交順序：

| Commit | 主旨 |
| --- | --- |
| `be7886a` | fix: restore the traditional/simplified conversion in analyze_diff |
| `7727266` | fix: stop using assert for flow control in the diff path |
| `c264c0b` | fix: reproduce the old pinyin lookup exactly in _find_word_candidate |
| `65f9a03` | fix: key the re-correction history by segment text |
| `1cb3857` | fix: stop shadowing NVDA's translation function |
| `9da4579` | test: cover the reachability fallback for all three modules |
| `fbd4974` | fix: guard text-policy boundaries and clean up the entry point |
| `42b1127` | fix: coerce non-Decimal cost before formatting, harden correction tests |
| `449420d` | fix: align provider config filenames and drop residual config keys |
| `108ca80` | perf: stop shipping and parsing non-runtime dictionary data |
| `ef77785` | fix: exclude the report directories where showReport() actually writes |
| `a4bb91e` | fix: exclude review/modules/, the last web/workspace/ depth showReport() writes |
| `5b1e561` | fix: write correction reports to the user workspace |
| `ae2c3c1` | fix: close review findings on T12 report-output extraction |

共 14 個 commit（8 個 task commit + 6 個審閱修正 commit）。

---

## 三、各 Task 完成內容

### Task 1（T5）繁簡轉換標籤 — `be7886a`
`analyze_diff()` 的兩行轉換呼叫在 2023 年 `f37a090` 被註解掉後從未還原，導致兩個轉換標籤永遠不會產生。還原 `to_simplified()` / `to_traditional()` 呼叫。標籤目前僅寫入報告 JSON，前端渲染屬於另一項功能決策，不在範圍內。

### Task 2（T6）移除 assert 流程控制 — `7727266`、`c264c0b`
四個參與流程控制的 `assert` 全數移除（`-O` 會把 assert 整個剝除，行為不得依賴它們）。`is_chinese_character()` 對長度非 1 的字串回傳 `False`；`get_char_pinyin()` 改為驗證失敗即 `ValueError`；`create_single_char_mapping()` 改拋 `ValueError` 並帶出實際／上限 token 數。

明確的行為變更（spec 唯一認可的一項）：`replace` 的任一側不是單一漢字時，保留原文且**不**加入 `typo_indices`——因為 `review_correction_errors()` 本來就會拒絕該替換，標記只會多花一輪 API 額度。

審閱修正：新增 total helper `lookup_char_pinyin()`，讓 `prompt.py::_find_word_candidate` 取得與修改前**逐位元相同**的行為，同時保留 `get_char_pinyin()` 的嚴格契約。

### Task 3（T4）重校正歷程改以文字為鍵 — `65f9a03`
`recorrection_history` 只在第一輪建立並固定長度，之後每輪都會重新切段。段數變多時 `parallel_map` 的 `zip` 會截斷，尾端留下 `None` 造成 `AttributeError`；段數變少時不會報錯，但會把**別的段落**被拒絕的答案餵給模型。改為以段落文字為鍵，並讓 `parallel_map` 在長度不符時於送出任何工作**之前**拋 `ValueError`。

### Task 4（T7）翻譯繫結與 gettext 擷取 — `1cb3857`、`9da4579`
`lib/llm/provider.py`、`configManager.py`、`lib/llm/executor.py` 三處的 `_` 定義改為「只有在完全找不到 `_` 時才建立 fallback」，避免遮蔽。`executor.py` 的 `_(f"...")` 改為靜態字串加 `.format()`，讓 `xgettext` 能擷取。`tests/conftest.py` 的 `initTranslation` 改為實際安裝可辨識的 `_`。

審閱修正：原本只有 `provider` 的 fallback 有測試覆蓋，`executor` 還原成舊寫法不會讓任何測試失敗；改為對三個模組參數化，並逐一在 scratchpad 還原驗證確實會失敗。

### Task 5（T8）邊界防護與進入點清理 — `fbd4974`、`42b1127`
`postprocess_output()` 三處未防護的 subscript 加上 guard（標點保留規則不變）；移除 worker 中不可達的 `raise e`；費用格式化的 bare `except: pass` 改為明確的例外清單，失敗時記錄原因並回報「費用無法取得」；一般流程訊息由 `log.warning` 降為 `log.info`。

審閱修正（**使用者可見的退化**）：`decimal_to_str_0` 只接受 `Decimal`，而 Coseeing（預設通道）的 cost 來自 JSON 數字，導致每次校正都會顯示「費用無法取得」。改為在 `_report_cost` 內以 `Decimal(str(cost))` 統一轉換。

### Task 6（T11）Provider 設定檔名與殘留設定 — `449420d`
五個 provider JSON 改名為與 `Provider.name` 一致，移除大小寫不敏感的 glob fallback；移除 `coseeing_username` / `coseeing_password`；naming 測試改為由 catalog 推導期望值（原本寫死的清單正是 `ollama.json` 漂移的原因）。**本批次第一次達到 0 failed。**

### Task 7（T9）資料搬遷與延遲載入 — `108ca80`、`ef77785`、`a4bb91e`
30MB 的 XLSX（無任何讀取者）與兩個僅供 eval 使用的 CSV 移至 `workspace/data/`；`buildVars.excludedFiles` 補上副檔名樣式（CSV 刻意**不**排除，執行期字典就是 CSV）。`chinese_dictionary.py` 改為以 `threading.Lock` 雙重檢查的延遲載入，字典缺失時直接拋錯而非退化成空 mapping。

審閱修正兩輪：`web/workspace/*` 這個樣式實際上排除不到任何東西（`Path.match()` 的 `*` 不跨路徑分隔符，而報告寫在更深一層），第一輪補的樣式又漏掉 `copytree` 產生的 `review/modules/`。最終以實跑 bundler 驗證：`showReport()` 產出 0 bytes 進入封裝（修正前為 246,686 bytes）。

### Task 8（T12）報告輸出搬離安裝目錄 — `5b1e561`、`ae2c3c1`
新增 `lib/paths.py`、`lib/report.py`；報告改寫到 `<user folder>/WordBridge-workspace/reports/<timestamp>-<rand>/`，靜態資源只佈署一次並以 `../modules/...` 相對引用；保留最近 10 份，且僅刪除符合命名樣式的目錄，retention 在新報告寫入**之後**才執行。

審閱修正：retention 有機率刪掉剛剛產生的那份報告（60 次試驗中 12 次），以及 retention 失敗會讓使用者看不到已寫好的報告。

---

## 四、執行中做出的裁決（Rulings）

以下 9 項為 plan 與現況衝突、或 plan 本身有缺陷時所做的決定。**每一項都可以被推翻**，若判斷有誤請直接回退對應變更。

1. **Task 2 — `prompt.py` 納入範圍**：brief 的檔案清單漏掉 `_find_word_candidate`，它是 `get_char_pinyin()` 的第二個呼叫端，新的 `ValueError` 契約會讓既有測試失敗。*代價*：該 commit 多動一個檔案。
2. **Task 2 — 推翻我自己前一項裁決**：我原本判定以「完全相等」比對非漢字可保持行為不變，審閱者實測推翻——`a`、`e`、`o`、`n`、`q` 本身就是合法拼音，8 個漢字的拼音集合含單一 ASCII 字母。改為抽出 total helper 完整重現舊查詢。*代價*：`utils.py` 多一個小 helper。
3. **Task 3 — 修正 plan 的測試資料**：6 個測試中有 3 個根本跑不起來（迭代器提前耗盡、斷言自相矛盾）。*代價*：兩個測試多一輪 no-op，一個測試改為斷言 1 段而非 2 段初始切分。
4. **Task 4 — 統一 commit 的 Co-Authored-By trailer**：subagent 用了自己的模型名稱，我在 controller 內 amend（分支無 upstream）。*代價*：一個未推送 commit 的 SHA 改變。
5. **Task 5 — cost 轉換位置**：在 `_report_cost` 內轉換，而非呼叫端。*代價*：原本不做轉換的路徑多一次轉換。
6. **Task 6 — SSO port 以產品值為準**：測試期望 8765、產品為 8000。依 git 歷史裁定（`b8ed80e` 出生時是 8765，`8ef7822` 刻意改為 8000，測試從未跟上）；且 8000 已隨多個版本出貨，若與 SSO 註冊值不符，登入早該壞掉。**改測試，不動產品。** *代價*：若判斷有誤，測試會釘住錯誤的 port——但改產品才是真正危險的選項。
7. **Task 7 — 以 stub 取代安裝 SCons**：`buildVars.py` 會連鎖 import SCons，本機沒有。選擇在測試內 stub 並還原，而非安裝套件或改動 build tool。*代價*：測試比 plan 多四行 stub，但讀的仍是真實的 `excludedFiles`。
8. **Task 7 — 修正而非擱置 `web/workspace` 排除樣式**：即使 Task 8 會移除寫入端，spec 對該樣式的用途是「防止曾執行過舊版的開發機把自己的報告打包進去」，而那正是 Task 8 修不到的情境。*代價*：Task 8 之後多兩個匹配不到東西的樣式。
9. **Task 8 — spec 覆蓋 plan 指定的測試**：plan 的 `test_retention_runs_after_the_new_report_is_written` 斷言 `pytest.raises(OSError)`，與 spec 的「刪除失敗只記錄、不中止產生報告」正好相反。依 spec 改寫。*代價*：retention 失敗變成 log 而非使用者可見錯誤——這正是 spec 要的。

### 一項需要更正的紀錄

最終審閱指出我在擱置 `decimalUtils` 缺陷時的**理由有誤**：我寫的是「它是共用工具，`decimal_to_str_10/12` 是其 sibling 的 partial，動它有風險」。實測結果是 `decimal_to_str_0` **只有一個 production 呼叫端**（`__init__.py:217`，本批次自己寫的），而 `decimal_to_str_10/12` 沒有任何 production 呼叫端。**擱置這個決定本身仍然正確**（實際單次費用遠低於 1 美元），但後續處理的成本遠比我當時記錄的低。

---

## 五、待辦：建議的後續任務

最終審閱將全部 27 項 deferred minors 判定為 follow-up，無一需在合併前處理。以下依價值排序：

1. **`lib/text/chinese.py:17-27` 區間表逸出字元錯誤**（最高價值）。八個條目被解析成「BMP 逸出字元 + 字面數字」。雙向都有問題：**47,418** 個星形平面 CJK 碼位被判為非漢字，且 **4,290 個 BMP 字元被誤判為漢字**——包含全部平假名與片假名、CJK 部首、以及 `‘ ’ … → ─ ■ ☃` 等符號。後者代表 `review_correction_errors` 會把假名互換當成合法的漢字修正接受。此缺陷為既有問題，Task 2 未改變它，但讓 `is_chinese_character` 成為兩項政策的唯一閘門。
2. **T7 的前提可能是錯的**（`lib/llm/provider.py:16` 等四處註解）。審閱者指出 NVDA 的 `addonHandler.initTranslation()` 慣例是綁進**呼叫模組的 globals**，而非 builtins；builtins 的 `_` 是 NVDA core 自己的 catalog。佐證：本附加元件自帶 `addon/locale/*/LC_MESSAGES/nvda.po`，其 msgid 不存在於 NVDA core catalog。**出貨的程式碼在兩種模型下都正確**，但註解若誤導後人刪掉 `initTranslation()` 呼叫，字串會靜默綁到錯誤的 catalog。建議在既定的 [manual] 繁中 NVDA 驗證時一併確認，再修正四處註解。
3. **`lib/viewHTML.py:5,7` 的無用 `import addonHandler`**。實測該模組從未使用 `_`；刪掉這三行，`lib/report.py` 才真正符合 spec 宣稱的「不 import NVDA」。
4. **`site_scons/site_tools/NVDATool/addon.py:9` 改用 `full_match()`**（3.13+）。這是 `buildVars.py` 必須逐層列舉路徑的根因；改掉之後單一 `web/workspace/*` 即可涵蓋所有深度。
5. **`lib/decimalUtils.py:30`**：≥10 且 `str()` 含小數點的值會被截斷（`Decimal('10.0')` → `"1"`），且 `Decimal('5E-7')` → `"5E-7"` 與自身 docstring 矛盾。單一呼叫端，修正成本低。
6. **測試覆蓋缺口**：`showReport()` 新的錯誤分支與 `OnPreview` 交接完全沒有測試；`_provision_modules` 的「安裝目錄檔案較新時重新複製」路徑（即升級情境）沒有測試；`tests/test_addon_bundle_contents.py:97` 的 `.xlsx` 斷言目前是恆真的（`addon/` 下已無任何 `.xlsx`），而 spec 預期該檔案將被未來的 CI 任務原封不動採用。

---

## 六、待人工驗證項目（[manual]）

本機為 Linux，以下需由維護者在 Windows/NVDA 環境確認：

- 升級仍持有 `coseeing_username` / `coseeing_password` 的 NVDA 設定檔
- 實際瀏覽器中的報告產生、資源載入與鍵盤導覽
- NVDA 啟動時不再讀取 3.6MB CSV（於 Windows 量測）
- 繁體中文 NVDA 下 provider 與 executor 訊息確實有翻譯
- `scons pot` 重新產生，確認 executor 的解析錯誤字串有被擷取（本機無 `scons`）
- 確認 `https://sso.coseeing.org` 註冊的 redirect URI 確為 port 8000

---

## 七、審閱過程中攔截到的實質問題

記錄於此，作為此流程價值的佐證——以下每一項都通過了實作者的自我審閱，但被獨立審閱擋下：

- Task 2：`get_char_pinyin()` 的新契約會讓 `prompt.py` 在使用者自訂詞彙比對時當掉（17 個既有測試失敗）。
- Task 2：我自己的「完全相等」裁決被實測推翻（8 個漢字 + 276 個星形平面字元的行為改變）。
- Task 3：plan 的 6 個測試中有 3 個無法執行。
- Task 4：`executor` 的 fallback 完全沒有測試覆蓋——還原成舊寫法不會讓任何測試失敗。
- Task 5：**使用者可見的退化**——預設通道每次校正都會顯示「費用無法取得」。
- Task 5：測試工具把 `decimal_to_str_0` 換成 `str()`，等於原測試從未跑到真正的函式（正是上一項漏網的原因）。
- Task 6：`client_id` 修好後，同一個測試還有第二個過期期望（port）被遮蔽。
- Task 7：`buildVars.py` 會連鎖 import SCons，plan 的測試片段無法執行。
- Task 7：`web/workspace/*` 樣式實際排除不到任何東西；第一輪修正又漏掉深一層的 `review/modules/`（246,686 bytes）。
- Task 8：retention 有機率刪掉剛產生的報告（60 次中 12 次）。
- Task 8：retention 失敗會讓使用者看不到已成功寫入的報告。
- 另有 7 項實作者「已驗證、未發現反例」的宣稱被審閱者實測推翻。
