# 模型清單重試與面板即時更新（catalog-retry）交接紀錄

- 日期：2026-11-04
- 分支：`feat/catalog-retry`，已 fast-forward merge 到 `main`（`102b007..bb66496`，48 個 commit，未 push）
- spec：`docs/superpowers/specs/2026-11-04-catalog-retry-design.md`，修訂 `2026-11-04-remote-catalog-design.md`，取代其 D9
- plan：`docs/superpowers/plans/2026-11-04-catalog-retry.md`，15 個 task，分三批
- review 與修正記錄：`docs/superpowers/finish/2026-11-04-catalog-retry-review.md`

## 做了什麼（使用者決定 R1–R13）

- **背景重試**：抓取失敗後，依序等 1、2、4、8、16、32 分鐘重試。上限是常數 32 分鐘，等於上限也重試；成功就停止。
  - 改網址時重試間隔歸零，即使背景重試已經停止也一樣（R10）。
  - 開面板觸發的抓取失敗時，接著原本的間隔；重試已經停止的話就不再排（R6）。
- **開面板時重試（R1）**：上次抓取失敗時，打開設定面板就重抓一次。
- **面板即時更新（R2）**：面板開著時清單更新，選單、狀態行和「無法載入的項目」那一行都會直接更新，焦點不移動。
  - 只保留使用者在面板上親手選的項目（R4、R7、C8、C22）。
  - 下拉選單開著，或焦點在即將被隱藏的控制項上時，先延後更新。
- **播報**：即時更新時說「模型清單已更新。」；只有使用者觸發的抓取失敗時才說「模型清單更新失敗。」（R3、R8）。「是否切換到 Coseeing default」的對話框不會觸發抓取（R9）。
- **面板描述（R11）**：狀態文字同時設成面板的 `panelDescription`，進入面板時 NVDA 會念出來。
- **網址設定（R12）**：比照 NVDA 的更新鏡像伺服器設定，改成唯讀框加「變更…」按鈕。
  - 對話框裡有「測試…」，在背景用 WordBridge 自己的抓取限制和驗證流程測試，不套用清單、不寫快取。
  - 對話框按確定時就存檔。
- **金鑰群組框（R13）**：比照 WorldVoice，開面板時就依固定順序為所有支援的 provider 和 Coseeing 建好，之後只顯示、隱藏或改標題。讀取金鑰時不會寫入空白項目。

## 驗證（`main` @ `bb66496`，Linux）

| 項目 | 結果 |
| --- | --- |
| add-on 測試（不含 integration） | 1053 passed、1 skipped（基準 805 passed、1 skipped） |
| server 測試 | 103 passed |
| integration 測試（真實 API） | 22 passed、2 skipped（供應商回報過載） |
| `prek run --all-files` | 3/3 Passed |
| `git diff --check`、`msgfmt --check` | 通過 |
| 突變測試（各輪 review 合計） | 先前被殺的突變在修正後都沒有存活；剩下存活的都是等價突變 |

## 測試版套件

- 檔名：`WordBridge-2026.11.1-test-catalog-retry-1.nvda-addon`
- 來源 commit：`bb66496`
- 大小：4,224,303 bytes
- sha256：`4b8ec8eccc4438c2f6e104e5e174cdb8c8d60aa27d8af07575534b360c24a2b6`
- 位置：`/tmp/claude-0/-workspace-WordBridge/9af55a63-c255-4088-9b3c-fe363afb236f/scratchpad/pack-catalog-retry/`。這是 session 的暫存區，要保留的話請另外複製。

## 尚未驗證

Windows、NVDA 和真實網路環境都沒有驗證。手動測試共 22 項，步驟見 review 文件「六」。其中最需要注意的幾項：

- 金鑰群組框的物件導覽和 Tab 順序，是否和畫面上的順序一致（7a、7b）。
- 面板開著、但正在看別的類別並捲到下方時，背景重試或新清單送達，不會讓那個類別捲回頂端（11）。
- 「變更…」對話框的朗讀；對話框關閉後焦點回到原位；「測試…」的進度和結果朗讀（14–17）。
- 連續開關「變更…」不會觸發 NVDA 的 `RuntimeError`；按確定後一秒內清單剛好送達的情況（18–22）。

## 還沒確認的使用者可見預設

review 文件第七節列了 21 項。其中第 19 項已被修正輪取代：網址無效和測試失敗的訊息，現在都會顯示 NVDA 的錯誤圖示並發出錯誤音效。

## 後續工作

- **provider 項目改放回 add-on 內建的 `catalog.json`**，遠端只提供模型、價格和標籤。這是使用者在 2026-11-04 的決定，要另外走一次一般流程。
