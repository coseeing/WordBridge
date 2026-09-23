# Server Proofreader 遷移與 SSO 身分綁定 — 完成報告

- **分支**：`server-proofreader-sso`（自 `main` @ `25c54f8` 開出，尚未合併，尚未推送）
- **Spec**：`docs/superpowers/specs/2026-09-23-server-proofreader-sso-design.md`
- **Plan**：`docs/superpowers/plans/2026-09-23-server-proofreader-sso.md`
- **執行方式**：Subagent-Driven Development。每個 task 由 implementation subagent（claude-sonnet-5，high effort）實作，再由獨立 review subagent（claude-opus-5.5，high effort）審閱 spec 相容性與程式品質；有 Critical/Important 發現就退回修正並重新審閱（scoped re-review），直到該 task 的 review 沒問題為止。全部 6 個 task 完成後，再由 claude-opus-5.5（max effort）做一次整支分支的 whole-branch review，並跑了唯一一輪允許的 final fix wave + re-review。
- **日期**：2026-09-23

---

## 一、結果摘要

| 項目 | 執行前 | 執行後 |
| --- | --- | --- |
| `/proofreader` | import 期即失敗（`configManager`、`settings_repository` 不存在；`self`/`DEBUG_MODE`/`_diff_` 等未定義名稱） | 可運作：guest/user/superuser 額度、模型解析、`run_typo_correction` 執行、`Interaction` 落地皆完整 |
| 登入方式 | 舊 HS256 + 密碼登入 | SSO access token 驗證 + `User.sso_sub`/`email_verified` 綁定；`/login`、`/register` 已移除（404） |
| `User.password` | 存在 | 已從 model、schema、資料庫（migration）徹底移除 |
| `/users`、`/interactions` CRUD | 只需登入即可存取 | 僅 `is_superuser=True` 可用（401/403 皆已測試） |
| `/feedback` | 有 `raise` 後的不可達死碼 | guest/登入者皆可用 `interaction_id` 覆寫回饋；guest `review_user_id=NULL` |
| 停用帳號（`is_active=False`） | **未被檢查**（含超級使用者） | 任何持有 token 但 `is_active=False` 的使用者一律 403（guest 路徑不受影響） |
| 校正文字長度上限 | guest 128 字元；登入者/superuser **無上限** | guest 128 字元不變；所有呼叫者新增 8000 字元硬上限（422），避免超長文字在已扣費後才失敗、額度永遠不會被記錄 |
| 測試 | 0（`server/tests/` 尚未存在） | 81 passed（`server/tests/`，含 6 個 final-fix-wave 新增測試），無 integration/外部依賴 |
| `_wb_vendor`／NVDA 依賴 | 校正流程需要 | 已換成一般 pip 套件（`hanzidentifier`、`pypinyin`、`chinese_converter`） |

---

## 二、Commit 清單（`25c54f8..828f737`，共 11 個）

```
053d99c feat(server): add SSO user fields and remove passwords
5b3f6fb feat(server): load runnable correction models
cb97eef fix(server): pin transitive crypto/CJK deps in requirements.txt
09756bc feat(server): link verified SSO identity to local users
3a1f1b5 fix(server): close two SSO linking races found in review
2d0126c feat(server): authorize requests with SSO dependencies
fe75138 feat(server): execute proofreader workflow and enforce quotas
8ecb7cd fix(server): guard oversized client IP before proofreader quota/DB writes
7f06cb8 feat(server): secure CRUD and accept guest feedback
4d6d634 fix(server): redact real personal emails from imp.py seed data
828f737 fix(server): enforce inactive-user 403 and cap request length across all callers
```

每個 `feat(server)` commit 對應 plan 的一個 task；緊接其後的 `fix(server)` commit 是該 task review 發現問題後的修正輪，或（最後兩個）final whole-branch review 之後的處理。

---

## 三、審閱過程中做的裁定（Rulings）

以下是我代替你做的判斷，依序列出，包含出錯的代價：

1. **Task 1（`sso_sub` 索引命名）**：無需裁定的層級，僅記為 minor（model 用 `unique=True` 但沒加 `index=True`，migration 建了具名索引 `ix_user_sso_sub`）——已 park，未來若跑 `alembic revision --autogenerate` 可能誤判有 drift。代價：極低，僅是 autogenerate 的雜訊。

2. **Task 2（requirements.txt 在 Python 3.12 上的可安裝性）**：沙盒沒有 python3.12 也沒有 docker，無法對照 `server/Dockerfile` 的 `python:3.12` 實際跑一次 `pip install`。改用 `pip download --python-version 312 --implementation cp --abi cp312 --platform manylinux2014_x86_64 -r requirements.txt` 對全部 55 個 pin（含新增的 `cryptography`/`cffi`/`joserfc`/`pycparser`/`zhon`）做了完整 resolver 驗證，全部有預編譯 wheel、無衝突、無需編譯。**代價**：理論上仍有極小機率在真正的 Docker build 中出狀況（例如 glibc 邊界情況），建議合併後第一次 CI/Docker build 時再次確認。

3. **Task 3（SSO 重新驗證時 email 不一致的處理方式）**：spec 只寫「更新驗證旗標」，沒規定 email 不一致時該怎麼辦。implementer 選擇「重新同步 `account` 到新 email（除非該 email 已屬於別人，則 409）」而非「一律拒絕」。這個狀態只有管理員手動把 `email_verified` 重設為 `False` 才會出現（其他所有路徑都是 sub+verified 一起寫入）。**代價**：管理員手動重設後，帳號的 `account` 值可能被靜默改名且無稽核紀錄；建議之後補一行 audit log。

4. **Task 5（guest 的 `X-Forwarded-For` 可被偽造）**：plan 原文明講「這階段維持現有 `get_client_ip()` 的 XFF 處理方式」，所以這是 spec 明確接受的階段性限制，未修正。但同一個發現裡藏的「IP 超過 45 字元導致 DB insert 在已扣費後才失敗、額度永遠算不到」是真的 bug，已修正（不影響 XFF 信任模型本身）。

5. **Final review（`is_active` 從未被檢查）**：這是唯一一個 Critical，且是**跨 task 的落空**——Task 3 保留了欄位但沒實作 403、Task 4/5/6 都以為別的層會做。已在 final fix wave 修正並由 opus 獨立以真實 app 重現、再重現確認修好。

6. **Final review（API key 環境變數大小寫）**：程式碼完全照 spec 字面（`f"{provider.upper()}_API_KEY"`，例如 `DEEPSEEK_API_KEY`），但你現有的 `server/.env` 用的是 `DeepSeek_API_KEY`（依 provider 自己的大小寫）。**判定為部署設定問題，不是程式碼缺陷**，未在程式碼加相容性判斷（避免違反 spec 明訂的慣例、增加非必要複雜度）。**你需要做的事**：部署前把 `.env` 的 key 名稱改成 spec 慣例（全大寫）。

---

## 四、需要你決定的事（我刻意沒有動）

1. **合併到 `main` 前，`server/` 目錄其餘未追蹤的檔案需要另外處理**。這個 plan 明確要求「每個 task 只 stage 列出的檔案，不要 `git add` 整個 `server/`」，所以目前分支只包含 23 個檔案，其餘約 40 個被 import 的模組（`dependencies.py`、`database.py`、`models/`、`lib/catalog`、`lib/llm`、`package/coseeing_auth` 等）仍是未追蹤狀態。這代表**這個分支目前無法從全新的 checkout 直接跑起來**（CI、Docker build 都會失敗），需要你另外決定何時、如何把其餘檔案加入版控。**特別注意**：`server/app/database.py`（未追蹤）目前把資料庫密碼寫死在程式碼裡——加入版控前務必先改成環境變數，否則密碼會永久留在 git 歷史。

2. **`server/app/imp.py` 的舊 commit 歷史裡還留著真實個人 email**。這個檔案是這次工作第一次進入 git 歷史（先前未被追蹤），commit `7f06cb8` 裡有 3 筆真實個人帳號（含你自己的 `tsengwoody.tw@gmail.com`）；後續 commit `4d6d634` 已把它們改成 `user1@example.org` 等佔位值，但**歷史裡的 `7f06cb8` 仍看得到原始明文**。這個分支目前**尚未推送到任何 remote**（已確認 `git branch -r --contains 7f06cb8` 為空），所以如果要徹底清除，需要你決定是否要 rewrite history（例如 squash 或 rebase -i）——這類操作我不會自己執行，需要你明確同意。

3. **Alembic migration（`server/alembic/versions/20260923_sso_user.py`）從未跑過真正的 MySQL**。沙盒裡沒有可用的 MySQL/Docker，只做了 compile 檢查與 revision chain 檢查（`dad5039f4770 -> 20260923_sso_user`）。部署前請：先備份資料庫（`password` 欄位會被永久刪除、無法復原）、對一個可拋棄的測試 DB 跑 `alembic upgrade`、並確認既有使用者列的 `is_active` 值是否符合預期（見下一點）。

4. **`is_active` 修正上線後的相容性**：`User` model 與 schema 的預設值都是 `is_active=False`。修正後，任何現存 `is_active=False` 或 `NULL` 的使用者（包含透過 `POST /users` 建立、卻忘了明確設 `is_active=True` 的帳號）在 SSO 登入時會立刻收到 403。這是 spec 的本意，但建議部署前先盤點既有資料，避免上線瞬間鎖住原本以為可用的帳號。

---

## 五、驗收條件逐條核對（對照 plan 的「Final verification and delivery」段落）

| # | 條件 | 結果 |
| --- | --- | --- |
| 1 | `python -m pip install -r requirements.txt` | ⚠️ 未在真正的 `python:3.12` 環境執行（沙盒無此環境）；改以 `pip download` 對照 cp312/manylinux2014 做了完整 resolver 驗證，見裁定 #2 |
| 2 | `python -m pytest tests -q` | ✅ 81 passed，全程無需外部 SSO 或 provider（皆為 monkeypatch） |
| 3 | `python -m compileall -q app` | ✅（Task 1 已跑過等效檢查；後續 task 未見編譯錯誤） |
| 4 | `from app.main import app; print(app.title)` | ✅ Task 6 report 確認 app 可正常 import、路由表已排除 `/login`、`/register` |
| 5 | Alembic upgrade 對照可拋棄 MySQL 測試庫 | ⚠️ **未執行**（沙盒無 MySQL），見第四節第 3 點 |
| 6 | `git diff --check` / `git status` 僅含預期檔案 | ✅ 每個 task 皆確認只 stage 該 task列出的檔案（reviewer 逐一驗證） |
| 7 | 真實 SSO/UserInfo/provider 整合測試 | ⚠️ **未執行**（無真實 token/API key/網路），依 plan 要求明確回報為未驗證，而非隱瞞 |

---

## 六、給下一批的流程建議

1. **跨 task 的「假設別層會做」型缺口，只有 whole-branch review 抓得到**——這批的唯一 Critical（`is_active`）正是這種：每個 task 的 per-task review 都沒錯，但沒有人真正接住這個需求。往後若拆 task，建議在 Global Constraints 明確標註「哪個 task 負責哪個跨切面需求的『最終落地』」，而不只是「哪個 task 建立欄位」。
2. **plan 明確接受的階段性限制（如 XFF 信任）容易被 reviewer 誤判為 bug**——這批發生了一次（Task 5），靠對照 plan 原文才正確裁定「部分接受、部分修正」。建議下次在 task brief 的 Global Constraints 裡，對這類「已知但接受」的限制加一句提示給 reviewer，減少不必要的來回。
3. **未追蹤檔案混在既有專案中時，「只 stage 列出的檔案」與「分支能否獨立跑」會直接衝突**——這批一路依照 plan 指示做對了，但也因此在 final review 才發現分支目前無法從全新 checkout 執行。若專案裡還有類似「大量既有未追蹤程式碼」的情境，建議在寫 plan 時就先決定：這次只交付「新增邏輯」，還是連「讓分支自己跑得起來」也一併排入某個 task。
