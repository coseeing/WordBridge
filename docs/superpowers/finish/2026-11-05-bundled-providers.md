# provider 改回內建（bundled providers）交接紀錄

- 日期：2026-11-05
- 分支：`feat/bundled-providers`，已 fast-forward merge 到 `main`（`a28dc29..d1bef55`，未 push）
- spec：`docs/superpowers/specs/2026-11-05-bundled-providers-design.md`，修訂 `2026-11-04-remote-catalog-design.md` 的 D1 與合併規則
- plan：`docs/superpowers/plans/2026-11-05-bundled-providers.md`，6 個 task，一批做完
- review 與修正記錄：`docs/superpowers/finish/2026-11-05-bundled-providers-review.md`（Critical 0、Important 0、Minor 8，修 6 個，2 個是 `main` 原有的問題，不修）

## 做了什麼

- add-on 內建的 `setting/catalog.json` 改成 `schema_version`、`providers`、`coseeings`。`providers` 和 server 的 `server/app/setting/catalog.json` 內容相同，測試以正規化的 JSON 比對兩邊，不會不同步。
- 遠端清單只提供 `models`。遠端的 `coseeings` 和不認得的欄位直接忽略。
- **遠端或快取的清單帶 `providers` 時整份拒收**（使用者決定 B4：還沒發佈，不需要相容）。「測試…」沿用「伺服器的回應不是 WordBridge 模型清單」。
- **server 的 `GET /` 不再送 `providers`**（使用者決定 B2）。server 自己仍用檔案裡的 providers；送出的內容由 server 重新序列化，`ensure_ascii=False`、tab 縮排。
- **內建檔沒有的 provider 的模型**只記 log，不算進「無法載入」（使用者決定 OQ1 → B，在 `fef68ef` 單獨一個 commit）。
- 執行期的網域白名單（`PROVIDER_URL_RULES`、`filter_provider_urls`）和「測試…」的 `disallowed_hosts` 字串（含 zh_TW）移除。改由測試檢查內建 provider：名稱等於 `SUPPORTED_PROVIDERS`、網址固定、官方網域 https、Ollama 只能是本機。

## 驗證（`main` @ `d1bef55`，Linux）

| 項目 | 結果 |
| --- | --- |
| add-on 測試（不含 integration） | 1056 passed、1 skipped（基準 1053 passed、1 skipped） |
| server 測試 | 104 passed（基準 103） |
| integration 測試（真實 API） | 沒有跑（這次沒有改到模型呼叫） |
| `prek run --all-files` | 3/3 Passed |
| `git diff --check a28dc29..`、`msgfmt --check` | 通過 |
| 突變測試 | 實作者 12 組、review 25 組，全部被抓到 |

## 測試版套件

- 檔名：`WordBridge-2026.11.1-test-bundled-providers-1.nvda-addon`
- 來源 commit：`d1bef55`
- 大小：4,223,766 bytes
- sha256：`6f4cc680717bc179135958d962ccb54ca16db1b0bbedd0e808616d9a95df449d`
- 位置：`/workspace/WordBridge/ref/`（被 git 忽略）

## 部署順序

**先部署 server，再發佈 add-on。** 正式 server 更新前送的清單還帶著 `providers`，新版 add-on 會整份拒收，使用者會一直看到「無法更新」。server 部署後，之前的 `2026.11.1-test-*` 測試版反過來會拒收沒有 `providers` 的清單，這點使用者已經接受。

## 尚未驗證

Windows、NVDA 和真實網路環境都沒有驗證。手動測試共 13 項，步驟見 review 文件「六」。最需要注意的：

- 從 catalog-retry 測試版升級並保留快取：第一次啟動記錄一行 `unreadable_cache type=remote_providers_not_allowed`，抓取成功後清單和升級前相同（第 1、2 項）。
- 用個人金鑰對 OpenAI、Anthropic、Google、DeepSeek 各校正一次，參數和之前相同（第 4 項）。
- 本機跑新版 server，`GET /` 沒有 `providers`；跑舊版 server 時「測試…」說不是 WordBridge 模型清單（第 5、6 項）。
- 加一個 `Mistral` 模型時，面板不出現「無法載入」，記錄有 `unknown_provider`（第 8 項）。

## 還沒確認的使用者可見預設

review 文件第七節列了 12 項。

## 後續工作

- server 的 `lib/catalog/model.py` 的 `LINT_ISSUE_CODES` 和 add-on 的不同（review m6，`main` 原本就是這樣，目前沒有行為影響）。
- `ProbeResult.kind` 和「變更…」對話框的 `RESULT_ROWS` 沒有對照測試（review m8，catalog-retry 留下的）。
