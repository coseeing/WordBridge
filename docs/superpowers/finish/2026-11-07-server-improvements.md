# server 改進 11 項 交接紀錄

- 日期：2026-11-07
- 分支：`feat/server-improvements`。它接在 `feat/server-settings` 後面，`feat/server-settings` 又接在 `feat/bundled-model-list` 後面。三個分支依序 fast-forward merge 到 `main`（`edef80b..24f64a3`），沒有 push，分支都已刪除。
- 討論紀錄（中文）：`storage/spec.md`，被 git 忽略。
- spec：`docs/superpowers/specs/2026-11-07-server-improvements-design.md`。使用者的決定都有標註；D1–D19 是協調者採用的預設。
- plan：`docs/superpowers/plans/2026-11-07-server-improvements.md`。共 12 個 task，分三批：1–4、5–8、9–12。前兩批之後各做了一次批次 review，都沒有 Critical 或 Important；只有第 1 批有 1 項 Important，已在第 2 批開始前修好。
- review 與修正記錄：`docs/superpowers/finish/2026-11-07-server-improvements-review.md`。Fable 5.1 審查整個分支：Critical 0、Important 0、Minor 6。修正階段一併處理了兩次批次 review 延後的 14 項 Minor。m5、m6 不修，記在後續工作。
- 進度帳本：`.superpowers/sdd/2026-11-07-server-improvements/progress.md`，被 git 忽略，已從任務 worktree 搬回主 checkout。裡面有全部的 Ruling。

## 做了什麼

| # | 項目 | 結果 |
| --- | --- | --- |
| 1 | 訪客額度用的 client IP | 新增必填的 `CLIENT_IP_SOURCE`（`cloudflare`／`proxy`）。`cloudflare` 模式只在連線端落在內附的 Cloudflare 範圍（`server/app/setting/cloudflare_ips.txt`，更新腳本是 `server/update_cloudflare_ips.py`）時，才採用 `CF-Connecting-IP`；`proxy` 模式取 `X-Forwarded-For` 的最後一個值 |
| 2 | `/feedback` 權限 | 不做（使用者決定），已知風險記在 spec |
| 3 | 額度競態 | 不做（使用者決定），已知風險記在 spec |
| 4 | 呼叫 AI 時佔用 DB 連線 | 查完額度就 commit、歸還連線；有測試量測呼叫 AI 期間借出的連線數為 0 |
| 5 | 額度查詢索引 | `(user_id, request_time)`、`(ip_address, request_time)` |
| 6 | API key 檢查 | 啟動時檢查實際服務得到的 provider 都有 key；請求時不再讀環境變數 |
| 7 | 兩套 DB 連線 | `dependenciesA.py` 併入 `dependencies.py`，非同步的函式改名為 `get_async_session` |
| 8 | 寫死的值 | `version` 改記 add-on 版本（`server/app/setting/addon_version.txt`，由同步腳本從 `buildVars.py` 產生）；新增 `template` 欄位；刪除 `category`；prompt 檔納入同步 |
| 9 | alembic 離線模式 | `alembic upgrade head --sql` 可以用了，輸出不含 DB 密碼。另外修好 `env.py` 原本沒有 import models 的問題 |
| 10 | 套件清單 | `requirements.in`、`requirements-dev.in`，用 uv 0.13.5 產生含 hash 的鎖定檔；Dockerfile 用 `uv pip install --system --require-hashes`，保留 pip（使用者決定） |
| 11 | 錯誤分類 | `LLMServiceError.kind`；server 回 `{"detail","code"}`，長度錯誤另附 `limit`，狀態碼依語意調整；add-on 依 `code` 顯示 15 種新訊息，三種語言都有翻譯；沒有 `code` 時退回依狀態碼顯示 |

版本是 `2026.11.1`（使用者決定）。`buildVars.py` 的版本號變更已經 commit。

## 驗證（`main` @ `24f64a3`，Linux）

| 項目 | 結果 |
| --- | --- |
| add-on 測試 | 1231 passed、25 skipped、3 subtests（worktree 基準是 1160 passed、25 skipped；主 checkout 因為有 `.env`，skipped 較少） |
| server 測試 | 263 passed（基準 166） |
| `prek run --all-files` | 6/6 Passed |
| `git diff --check edef80b..`、`msgfmt --check`（zh_TW／zh_CN／zh_HK） | 通過 |
| 突變測試 | 批次 review、最終 review 和修正階段都做過；存活的突變都已補上測試，或在 review 文件說明原因 |
| migration | 在 MariaDB 11.8.6 上跑過完整的 upgrade、`alembic check`、downgrade（含超長版本的拒絕）、再 upgrade。11.3.2 只靠原始碼比對 |
| 乾淨環境 | 只裝 `requirements.txt` 時 `import app.main` 和 `GET /` 正常；只裝 `requirements-dev.txt` 時 server 測試全部通過 |

沒有打包測試版套件。

## 部署步驟（spec §18）

1. **先更換資料庫密碼**（見下方「需要立即處理」）。
2. 在 `wob/.env` 加上 `CLIENT_IP_SOURCE=cloudflare`，並確認 served models 用到的 provider key 都已設定。
3. 確認正式環境的 Docker 支援 BuildKit，Dockerfile 的 `RUN --mount=from=` 需要它。
4. 把 repo 的 `server/` 複製到 `wob/server/`，build 新的 image。
5. **停掉 server。**
6. 用 `mysqldump` 備份 `WordBridge` 資料庫。MariaDB 的 DDL 無法 rollback。
7. 用新的 image 先跑 `python -m alembic upgrade head --sql` 檢查 SQL，再跑 `docker compose run --rm <service> python -m alembic upgrade head`。
8. 啟動 server。
9. 上線後確認以下兩件事（見「尚未驗證」）：
   - client IP 是使用者的真實 IP；
   - image 裡還有 pip（`docker run --rm <image> python -m pip --version`）。

要回滾時同樣要先停 server，而且 downgrade 只能線上執行。已經寫入 `2026.11.1` 這類超過 8 個字元的紀錄時，downgrade 會拒絕，要改用備份還原。

server 和 add-on 的部署順序沒有限制：
- 新 add-on 遇到舊 server 時，沒有 `code`，退回原本的訊息。
- 舊 add-on 遇到新 server 時，訪客文字過長會顯示「The Coseeing request failed」。

## 需要立即處理

- **資料庫密碼外洩**：正式環境的 DB 密碼就是 `005b542` 起公開在 GitHub 上的那一個（`wob/.env`、`wob/mariadb/init.sql`），`wob/mariadb/Dockerfile` 的 root 密碼也一樣。請盡快更換。

## 尚未驗證

- **Windows／NVDA**：spec §19.4 的 8 項都還沒做，步驟見 review 文件「七」。重點：
  - 訪客超過 128 字、超過 8000 字、兩種額度用完、模型無法使用時聽到的訊息；
  - 三種語言的語音，以及 `{limit}` 是否正確代入；
  - 遇到舊 server 時的退路；
  - 本機模式的訊息不變。
- **client IP**（spec §5.7）：Traefik 預設會刪掉外部帶來的 `X-Forwarded-For`，這點只依文件和原始碼判斷。如果有 IPv6 連線經過 Docker 的 userland proxy，server 看到的會是 Docker 閘道的 IP，所有訪客就會共用同一份額度。
- **Docker image**：container 裡沒有 Docker，沒有實際 build 過，也沒有確認 image 裡的 pip。
- **MariaDB 11.3.2**：沒有實機跑過 migration。審閱者比對原始碼後，確認 11.3.2 一樣會默默刪掉外鍵的隱含索引，而 migration 重建 `KEY user_id` 的做法在 11.3.2 也有效。

## 還沒確認的使用者可見預設

review 文件「五」列了完整清單。其中最值得再看一次的：
- 錯誤訊息字串表（spec §17）沒有逐句確認過。特別是 `guest_quota_exceeded` 的「今日訪客額度已用完」：額度其實是滾動的 `QUOTA_WINDOW_HOURS`（24 小時），不是到午夜重置，「今日」可能讓人誤會。
- 訪客送出超過 8000 字時，聽到的是一般的長度訊息，不是「請登入」。
- zh_CN、zh_HK 用「你」；zh_TW 用「您」和「帳戶」。

## 範圍外的觀察（共用基礎設施）

Traefik（`/workspace/entry/entry/traefik.yml`）有三個問題：
- `api.insecure: true` 加上 `web` 入口上 `/api`、`/dashboard` 的路由，管理面板在 80 port 不需要登入就能看。
- `log.level: DEBUG`。
- 網域經過 Cloudflare 代理，憑證卻用 `tlsChallenge`，續期可能會失敗。

## 後續工作

- review m5：第一次登入的使用者，在呼叫 UserInfo 期間（最多 6 秒）仍佔著 DB 連線。
- review m6：訪客紀錄佔大多數時，「全體訪客」的額度查詢可能仍然全表掃描。這是 MariaDB 優化器的選擇，不是索引設計錯誤。
- 殘餘風險（spec §5.5、§21）：經由其他 Cloudflare zone 或 Worker 送來的請求可以自己設定 `CF-Connecting-IP`；`GUEST_GLOBAL_QUOTA` 封頂了損失，完整的解法是 Authenticated Origin Pulls（mTLS）。
- 不做的第 2、3 項（`/feedback` 權限、額度競態）：使用量變大時再評估。
- pre-commit hook 還沒裝進 `.git/hooks`，要啟用請執行 `prek install`。
