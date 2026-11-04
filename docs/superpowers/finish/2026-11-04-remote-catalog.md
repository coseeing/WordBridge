# 遠端模型清單（remote catalog）交接紀錄

- 日期：2026-11-04
- 分支：`feat/remote-catalog`，已 fast-forward merge 到 `main`（`774560b..e98d34e`，48 個 commit，未 push）
- spec：`docs/superpowers/specs/2026-11-04-remote-catalog-design.md`
- plan：`docs/superpowers/plans/2026-11-04-remote-catalog.md`
- review 與修正記錄：`docs/superpowers/finish/2026-11-04-remote-catalog-review.md`

## 做了什麼

- add-on 的 provider 和 model 清單改從遠端網址取得。網址可在設定面板設定，預設是 `https://wordbridge.coseeing.org`。
- 內建的 `setting/catalog.json` 只保留 Coseeing default。
- 取得的清單會依網址分別快取。取不到時用快取；沒有快取就只有 Coseeing default。
- provider 網址鎖定官方網域。
- server 的 `GET /` 原樣回傳 `server/app/setting/catalog.json`。這個檔是模型清單唯一的來源。
- server 以 `COSEEING_MODEL_IDS` 保留可服務的 Coseeing 模型 id，預設是 `deepseek-flash&DeepSeek,gpt-6-luna&OpenAI`，讓已發行的 add-on 繼續可用。
- 使用者的決定（U1–U9、OQ1→B、OQ2→B、OQ3→D、對話框選「是」一律切到 Coseeing default）都記在 spec。

## 驗證（`main` @ `e98d34e`，Linux）

| 項目 | 結果 |
| --- | --- |
| add-on 測試（不含 integration） | 778 passed、1 skipped（基準 460 passed、1 skipped） |
| server 測試 | 96 passed（基準 81） |
| integration 測試（真實 API） | 22 passed、2 skipped（供應商回報過載） |
| `prek run --all-files` | 3/3 Passed |
| `git diff --check` | 乾淨 |

## 測試版套件

- 檔名：`WordBridge-2026.11.1-test-remote-catalog-1.nvda-addon`
- 來源 commit：`e98d34e`
- 大小：4,211,862 bytes
- sha256：`c5ebbdcf26c15f7e9a041f36ffcd2b8112084c0c229a4be7f2695b764009efc2`
- 位置：`/tmp/claude-0/-workspace-WordBridge/9af55a63-c255-4088-9b3c-fe363afb236f/scratchpad/pack-remote-catalog/`。這是 session 的暫存區，要保留的話請另外複製。
- 套件內沒有 `catalog-remote.json`，也沒有捆綁的 cryptography；有 6 個 cryptography 補缺檔和 zh_TW 翻譯。

## 部署順序

1. **先部署 server。** 新的 `GET /` 要先上線，再發佈這版 add-on。否則新安裝的使用者只會看到 Coseeing default。
2. server 的 `COSEEING_MODEL_IDS` 不要設成空字串。空字串代表只接受 `default`，已發行 add-on 送來的兩個舊 id 會收到 404。不設定才會用預設清單。

## 尚未驗證

Windows、NVDA、真實 TLS 和代理伺服器環境都沒有驗證。手動測試共 17 項，步驟見 review 文件「六、Windows／NVDA 尚未驗證的手動項目」。其中最重要的幾項：

- 離線且沒有快取、存的是本機模型時，按 NVDA+Alt+O 的對話框朗讀，以及「是」和「否」的行為（第 3 項）。
- 抓取卡住時結束 NVDA，應在約 3 秒內結束（第 10 項）。
- NVDA Remote 的「取得外部 IP」仍可使用（第 11 項）。
- 網址欄位的朗讀和 Tab 順序（第 13 項）。

## 還沒確認的使用者可見預設

review 文件第七節列了 15 項，修正輪又多了 3 項：

- URL 含空白或控制字元的 provider 會被丟棄。
- 每次啟動、每次改網址，各多寫一行 info 記錄。
- 記錄中的 catalog 問題超過 200 字元會被截斷，控制字元改用跳脫形式。

## 範圍外、待處理

- `lib/llm/provider.py:88,122` 會把 `str(e)` 寫進記錄。連線錯誤的訊息裡可能有 Google 網址中的 `?key=`，也就是使用者的 API 金鑰。這是 `main` 原本就有的問題。
- 根目錄 `.gitignore` 的 `storage` 規則把 `server/app/package/coseeing_auth/storage/` 也忽略了。新的 checkout 跑 server 測試會缺模組。
