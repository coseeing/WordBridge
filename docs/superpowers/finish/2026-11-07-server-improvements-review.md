# Server improvements（client IP、連線釋放、索引、啟動檢查、錯誤代碼、相依清單）— 最終審閱（DEVELOPMENT_WORKFLOW.md §3.3）

- **分支**：`feat/server-improvements`（自 `feat/server-settings` @ `918566c` 開出），審閱範圍 `918566c..5bce7cd`（17 個 commit：3 個 docs、14 個程式）
- **Spec**：`docs/superpowers/specs/2026-11-07-server-improvements-design.md`（使用者決定 11 項；orchestrator 預設 D1–D19）
- **Plan**：`docs/superpowers/plans/2026-11-07-server-improvements.md`（12 個 task，三批；Review Focus 五項）
- **進度帳本**：`.superpowers/sdd/2026-11-07-server-improvements/progress.md`（23 條 Ruling；兩次批次 review 延後的 Minor：M1–M6、M-B2-1..8）
- **審閱者**：Fable 5.1，只讀程式碼，不修改原始碼、測試、spec 或 plan；測試、突變測試與 MariaDB 檢查都在拋棄式 worktree 進行（`git worktree add --detach <scratchpad>/review-head 5bce7cd`、`<scratchpad>/review-mut 5bce7cd`、`<scratchpad>/base-918566c 918566c`，審閱後全部 `git worktree remove`）
- **日期**：2026-11-07
- 路徑若無前綴，相對於儲存庫根目錄。行號對 `5bce7cd`。

---

## 一、總評

**可以直接合併。** 沒有 Critical，沒有 Important；6 個 Minor 全是測試覆蓋、用詞一致性與文件層面的事，沒有一個改變使用者聽到的行為或讓安全邊界變弱。帳本已列的 14 個 Minor（M1–M6、M-B2-1..8）我都看過，嚴重度判斷一致，這裡不重複，只在突變表裡標出我用突變獨立證實了其中兩個（M-B2-2、M-B2-3）。

- 兩套測試在 HEAD 都是綠的：附加元件 **1228 passed / 25 skipped / 3 subtests**，伺服器 **250 passed**；`prek run --all-files` 6 個 hook 全部 Passed；`git diff --check 918566c..5bce7cd` 乾淨；沒有 `Co-Authored-By`；沒有 `.pot`／`.mo` 進 commit。
- 使用者的 11 項決定與 D1–D19 逐一核對都落地了（§二之 2）；plan 的 Review Focus 五項都有對應測試，而且我用突變或 MariaDB 實跑證明這些測試真的會抓（§二之 6）。
- **我自己做了 42 個突變，37 個被測試抓到**（表八）。5 個存活的：2 個是帳本已登記的 Minor（M-B2-2 `getlist` 接線、M-B2-3 guard 門檻），1 個是死碼（`provider_failure` 的 `else "other"`，`KINDS` 在建構時就擋掉了），1 個是本審閱新增的 Minor（m2：非長度錯誤的 body 多帶 `"limit": null` 沒有測試擋），1 個是我測試檔選錯（M38 改跑 `tests/test_catalog_url_dialog.py` 就抓到）。
- **MariaDB 11.8.6 上我重跑了整條遷移**（D3、D16）：從 `918566c` 的 `Base.metadata.create_all` 建底、`stamp`、`upgrade head`、`alembic check`、含 `2026.11.1` 列時 `downgrade -1` 被拒且 schema 一個字都沒變、刪列後 `downgrade -1` 回到起點（只差欄位順序）、再 `upgrade head` 與第一次結果逐字相同。離線 SQL 不含 DB 密碼。細節在表九。
- 安全三點都確認：(1) 假造 `CF-Connecting-IP` 只在 peer 是 Cloudflare edge 時才被採信，`proxy` 模式完全不看它，`X-Forwarded-For` 只取最後一個值（突變 M01–M05 全被抓）；(2) API key 與 DB 密碼不進回應、不進 log、不進 `--sql` 輸出（M09、M10、M12 被抓；表九第 4 列）；(3) AI 服務的原始錯誤文字只進 log，回應只有固定的英文 `detail`（M12 被抓）。
- 錯誤代碼契約：伺服器四個檔案送出的代碼集合與附加元件 `_coseeing_error_message` 認得的集合**完全相同，都是 15 個**（我用 grep 各自抽出來比對）；沒有 `code`、`code` 不認得、`limit` 不可用、body 不是物件，四種退路都走回今天的狀態碼訊息（M33–M37 被抓）。
- `lib` 鏡像規則：在 scratch 複本重跑 `python3 server/sync_addon_code.py` 後 `git status` 乾淨；`diff -r` 附加元件與伺服器的 `lib`、`setting/templates`、`setting/task`，只有 `UNPREFIXED` 四個檔案依設計不同。
- 翻譯：三個 `.po` 都通過 `msgfmt --check`，0 條未翻譯；我用 `scons pot` 重新產生 `.pot` 再 `msgmerge`／`msgattrib`，和 commit 進去的三個 catalog **除 `POT-Creation-Date` 外零差異**，所以 `#.` 的 Translators 註解和 `#:` 行號都是 xgettext 真的看到的。zh_TW 的 15 句讀起來自然；唯一的用詞問題是 帳號／帳戶（m1）。

---

## 二、審閱重點逐項

### 1. 正確性與相對 `918566c` 的回歸

- **Client IP（`server/app/client_ip.py:75-100`、`server/app/main.py:129-137`）**：`",".join(forwarded_for).split(",")` 把多行 header 與單行多值攤平，去空白、去空項後取最後一個；沒有 header 用 `request.client.host`；`request.client` 為 `None` 回 `None` → `_storable_ip` 存 `"invalid"`。只有 `source == "cloudflare"` **且** peer 在 Cloudflare 範圍內才看 `CF-Connecting-IP`，且必須能被 `ipaddress.ip_address` 解析；IPv4-mapped IPv6 peer 以 IPv4 比對範圍（`:67-72`）。回傳值經 `ipaddress` 正規化，所以 `2001:DB8::1`／` 2001:db8::1 ` 算同一個訪客（Review Focus 2）。`Headers.getlist` 在 pin 的 starlette 1.6.0 存在（我在 venv 確認）。
- **連線釋放（`server/app/main.py:253-263`）**：配額檢查後、AI 呼叫前 `db.commit()`，失敗則 `rollback` → 500 `service_error`（批次 2 的 carry-over 有做到，`test_a_failed_quota_transaction_end_is_service_error`）。session 用預設 `expire_on_commit=True`，`user` 在 commit 後過期，`InteractionModel(user=user)` 與第二次 commit 時重新載入並正確寫入 `user_id`（`server/tests/test_proofreader_connection.py:69-95` 用檔案型 SQLite + QueuePool 證明 AI 呼叫當下 `checkedout() == 0`；我把那段 commit 拿掉，這個測試回 `[1] == [0]` 失敗，M08）。兩次 commit 之間沒有任何 ORM 物件被讀取，所以不會有過期後的意外 SELECT。
- **索引與遷移（`server/alembic/versions/20261107_interaction_template.py`）**：先用 raw SQL 重建 `KEY user_id`（否則 MariaDB 在建立以 `user_id` 開頭的複合索引時會默默丟掉 FK 的隱含索引，downgrade 會在 1553 錯誤卡一半——帳本有記，我在 11.8.6 重現了修正後的正確行為），再建兩個複合索引、`version` 放寬到 32、`template` 以 `server_default=""` 加入後移除預設、最後 `DROP COLUMN category`。downgrade 先檢查 `CHAR_LENGTH(version) > 8` 的列數，有就 `RuntimeError` 且**一個 DDL 都不跑**（Review Focus 5，MariaDB 實測 schema 不變、head 不動）。
- **啟動檢查（`server/app/correction_config.py:95-115`）**：只檢查 `resolve_model()` 真的能服務的 id 的 provider（D15）；不能解析的 `COSEEING_MODEL_IDS` 項目只 `logger.warning`；錯誤訊息只列變數名不列值；`api_keys` 用 `field(repr=False)`。檢查在 `load_correction_settings()`，`alembic/env.py` 只 import `app.settings`，不需要 key（D18；`test_importing_app_settings_needs_no_api_key` 是 subprocess 測試，43cf587 另外把 key 設成 `""` 防 `server/.env` 回填）。請求路徑不再讀 `os.environ`（`main.py:245`）。
- **錯誤代碼（`server/app/errors.py`、`main.py`、`user/auth.py`、`user/linking.py`）**：`ApiError(HTTPException)` 帶 `code`／`limit`，handler 只在 `limit is not None` 時加欄位；`Exception` 的 catch-all 回 500 `service_error` 後 Starlette 仍會 re-raise 讓 uvicorn 記 traceback。401 維持 `{"detail"}`（D13，`test_401_bodies_have_no_code`）；FastAPI 自己的 422 不動（`test_other_validation_errors_keep_fastapi_422`）。順序：8000 → 訪客 128 → 配額 → 模型（R15，`test_text_over_8000_characters_is_413[guest]`，M11 被抓）。
- **`lib` 的 `kind`（`addon/globalPlugins/WordBridge/lib/llm/`）**：`errors.py` 驗證 `kind ∈ KINDS`；`provider.py` 401/403/404 → configuration、429 → rate_limited、503 → overloaded、529 → overloaded（訊息仍是「An error occurred, status code = 529, Overloaded」）、其他 → other；`send()`／`try_connection()` → unreachable；`executor.py` 解析失敗 → other。`_error_detail()`（`provider.py:32-46`）對 HTML、`{}`、`{"error": {}}`、`{"error": "x"}`、`{"error": {"message": 5}}`、`[1]`、空字串，有無 `reason` 共 14 種組合都只回 `error.message` 或 `reason`，body 永遠不進訊息（Review Focus 3；M40 把 body 放回去立刻被抓）。本機模式訊息逐字未變（`tests/test_llm_errors.py` 既有的訊息測試原封不動）。
- **附加元件（`addon/globalPlugins/WordBridge/__init__.py:198-296`、`:816-822`）**：`status >= 400` 時先讀 body 的 `code`／`limit`，`log.warning` 英文記 status 與 code，有對應訊息就說完 return，否則落到原本的 401／429／其他三段，**原本三段一行都沒改**。`limit` 必須是 `int`、非 `bool`、`> 0`（Review Focus 4）。
- **相對 `918566c` 的回歸**：沒有。狀態碼改變（429→413、404→422、422→413）是使用者決定（spec §2.1「status codes follow their meaning」）；本機模式唯一的行為變化是 D14 的 crash 修正。既有測試除了狀態碼斷言外都保留並通過。

### 2. Spec 符合度（每個使用者決定與 D1–D19）

| 項目 | 落地位置 | 結果 |
| --- | --- | --- |
| 1 `CLIENT_IP_SOURCE`=cloudflare/proxy，最後一個 XFF，範圍檔內建 | `settings.py:46-51,120,147-153`、`client_ip.py`、`setting/cloudflare_ips.txt`（22 段）、`update_cloudflare_ips.py` | ✅ 兩種值以外（含大小寫不同）啟動即停；範圍檔缺少／壞行啟動即停；M01–M05、M21 被抓 |
| 4 AI 呼叫期間不持有連線 | `main.py:253-263` | ✅ `checkedout() == 0`；M08 被抓 |
| 5 兩個複合索引，model 與 migration 都宣告 | `models.py:17-23`、migration `:29-30` | ✅ `test_upgrade_matches_the_model` 以 model 的 `__table__.indexes` 比對；MariaDB `alembic check`：No new upgrade operations |
| 6 啟動檢查 key（D15、D18） | `correction_config.py:95-115` | ✅ M13–M15 被抓；空白 key 視為缺少 |
| 7 合併 session 模組，兩套都留 | `dependencies.py`、`dependenciesA.py` 刪除 | ✅ 錯綁 async engine 的 `Session = sessionmaker(bind=engine)` 已移除；`async_sessionmaker` 取代 `sessionmaker(class_=AsyncSession)` |
| 8 `version` = 附加元件版本、新 `template`、刪 `category`（D9–D12） | `sync_addon_code.py:63-89`、`setting/addon_version.txt`、`main.py:317-318`、`schemas.py:16` | ✅ `2026.11.1`；`Standard_v1`／`Lite_v1`；M25、M26 被抓 |
| 9 alembic offline | `alembic/env.py:47-55`、`alembic.ini:66-69` | ✅ M28 被抓；表九第 4 列 |
| 10 uv、兩份清單、hash（§14） | `requirements*.in/.txt`、`Dockerfile:9-14` | ✅ 37／45 個 pin 全有 hash、版本一致；Docker build **未驗證**（表九） |
| 11 伺服器回代碼、附加元件翻譯（D5–D7、D13、D14、D17、D19） | `errors.py`、`__init__.py`、三個 `.po` | ✅ 15 個代碼兩端集合相同；`main.py:238-239` 的誤導註解已改寫為 `:284-285,293-295` |
| §16 版本 2026.11.1 | `buildVars.py:25`、`addon_version.txt` | ✅ |
| D2 保留 `KEY user_id` | migration `:27` | ✅ MariaDB 實測 upgrade 後仍在 |
| D4／§18 先備份 | spec §18 步驟 5 | 文件層（M-B2-1 已登記要補「先停伺服器」） |
| D16 不用正式 dump | 帳本、我的重跑 | ✅ 都從 `create_all` @ `918566c` 建底 |

### 3. 併發、session 與 expire

- 每個請求一個 `get_db` session，`get_optional_user` 與 `/proofreader` 透過 FastAPI 的依賴快取共用它；`CORRECTION_SETTINGS`、`CLOUDFLARE_NETWORKS`、`ADDON_VERSION` 都是啟動時建好的不可變物件，執行緒間只讀。
- 第一次 `commit()` 是「結束唯讀交易」而不是 `rollback()`（帳本 R6）：`resolve_local_user` 的連結／建立路徑自己已經 commit（`linking.py:112,139,166,190`），所以這次 commit 不會把任何「原本打算回滾」的東西寫進去；而 `get_optional_user` 快速路徑（`sub` 已驗證）只做一個 SELECT。
- `user` 過期後直到寫入都沒被讀取；寫入時 SQLAlchemy 重新載入一次。若這幾秒內該使用者列被刪掉會是 `ObjectDeletedError` → 500 且成本未入帳——機率可忽略，且與 918566c 相同（當時也是 commit 時才同步 FK）。
- 仍持有連線的時間窗：第一次登入或 `email_verified` 未確認的使用者，`resolve_local_user` 在 `_lookup_by_sub`（開交易）之後才呼叫 UserInfo（`linking.py:218-222`，上限 `SSO_USERINFO_TIMEOUT_SECONDS`）。這不在 item 4 的範圍（AI 呼叫），有界，列為 m5 供日後參考。
- 配額競爭（item 3）依使用者決定不處理。

### 4. 安全

- **IP 偽造**：攻擊者能控制的只有 XFF 的左側與 `CF-Connecting-IP`；前者永遠不用，後者只在 peer ∈ Cloudflare 範圍時採信。範圍檔過期只會讓新 edge 的訪客共用配額（更嚴、不可繞過）。uvicorn 預設 `forwarded_allow_ips=127.0.0.1`，Traefik 從 Docker 網路連進來不會被信任，所以 `request.client` 不會被 uvicorn 用 XFF 改寫；就算改寫了，程式先用 header 的最後一個值。經另一個 Cloudflare zone／Worker 打到 origin 的情境帳本 M-B2-7 已登記。
- **key／密碼外洩**：`api_keys` `repr=False`；AI 失敗的 log 經 `masked()` 把所有已設定的 key 換成 `***`（M09）；server bug 的 traceback 也經 `masked()`（M10）；`SettingsError` 只列變數名（`test_the_error_never_echoes_a_key`）；`alembic upgrade --sql` 的 stdout／stderr 我 grep 密碼 0 次。
- **provider 原文**：`_PROVIDER_DETAILS` 是五句固定英文；`test_each_kind_maps_to_its_provider_code` 斷言 `raw provider text` 與 key 不在 `response.text`；M12 把 `str(error)` 放進 detail 立刻被抓。
- 回應裡唯一含部署數值的是 `limit`（128／8000），依 spec 刻意。

### 5. 測試是否真的抓得到（突變測試）

見表八。方法：在 `<scratchpad>/review-mut` 逐一套用字串替換、跑相關測試檔（伺服器 12 個檔、附加元件 3 個檔，`-x`）、`git checkout -- <file>` 還原；每個突變前後 `git status` 都乾淨。

### 6. plan 的 Review Focus

| # | 期望 | 測試 | 我的驗證 |
| --- | --- | --- | --- |
| 1 XFF 多行／尾逗號／IPv4-mapped／無 `request.client` | 最後一行的最後一值；mapped 以 IPv4 比對；無 peer → `invalid`，不 crash | `test_select_uses_the_last_header_line`、`test_select_skips_an_empty_last_item`、`test_select_checks_an_ipv4_mapped_peer_as_ipv4`、`test_no_peer_and_no_header_is_stored_as_invalid` | M01、M04 被抓。多行 header 只在 `select_client_ip` 層有測，API 層的 `getlist` 接線沒有（M30 存活＝M-B2-2，已登記） |
| 2 `CF-Connecting-IP` 寫法不同算同一人 | 以 `ipaddress` 正規化 | `test_select_normalises_cf_connecting_ip`、`test_select_normalises_the_peer` | M05 被抓 |
| 3 provider 錯誤 body 形狀怪異 | 永遠 `LLMServiceError(kind="other")`，不含 body | `test_other_status_bodies_never_crash`（7 種 body × 有無 reason） | M40 被抓 |
| 4 附加元件拿到不能用的 body | 退回狀態碼訊息，不說 `{limit}`、不 crash | `test_unusable_limit_falls_back_to_status_message`（6 種）、`test_non_object_body_falls_back`（4 種） | M33、M34、M37 被抓 |
| 5 有 `2026.11.1` 列時 downgrade | 任何 DDL 前拒絕並說明 | `test_downgrade_refuses_long_versions_before_any_ddl` | M18 被抓；MariaDB 實跑：`RuntimeError: 1 interaction rows have a version longer than 8 characters…`，schema 與 head 不變 |

### 7. 翻譯

- 15 句 zh_TW 全用 您，句式與既有的「請稍後再試」「請登入 Coseeing」一致；「校對」沿用既有譯法（catalog 既有 2 處）。
- **帳號／帳戶**：既有 zh_TW catalog 三處都是「帳戶」（`nvda.po:217` 檢查您的帳戶權限、`:235` 帳戶餘額、`:466` 設定面板的「Coseeing 帳戶」），新的四句用「帳號」（`:42,88,93,98`）。zh_HK 新舊一致用「帳戶」，zh_CN 一致用「账户」。這是 spec §17 草稿表就寫成的，不是實作者走偏，但使用者聽到的會是同一個面板叫「帳戶」、錯誤訊息叫「帳號」（m1）。
- zh_CN：用語與既有一致（你、账户、登录、稍后重试、连接、设置、文本）；「电子邮箱已验证」自然。zh_HK：你、帳戶、登入、稍後再試、連接、電郵地址，與既有一致。
- 兩句帶 `{limit}` 的在三個 catalog 都標了 `python-brace-format`，`{limit}` 都保留。
- `# Translators:` 註解：`__init__.py` 用 `_(` 換行後把註解放在字串上一行、單行者放在 `return _(` 上一行，兩種 xgettext 都抓到（我重產的 `.pot` 有 156 條 Translators 註解，三個 catalog 零差異）。`provider.py` 403／503 的註解搬進呼叫內（R16）後仍被抓到。
- log 不翻譯：`__init__.py:818` 是英文 f-string；我把它包進 `_()` 後 `tests/test_catalog_url_dialog.py::test_log_messages_are_not_translated[__init__.py]` 失敗，規則有測試守著。

### 8. git／流程限制

- 17 個 commit 訊息皆為英文 `<type>: <summary>` 加內文，無 `Co-Authored-By`；沒有 `.pot`／`.mo`／`.env`／`__pycache__` 進 commit；`git diff --check` 乾淨；`prek` 6/6 Passed。
- `server/app/lib`、`dictionary`、`setting/templates`、`setting/task` 都是 sync 產物（重跑後無差異）；`server/app/setting/catalog.json` 未被 sync 覆蓋（`test_sync_replaces_only_the_copied_dirs`）。
- 帳本的 Ruling 與延後 Minor 齊全；Task 7 的「M-B2 carry-over」在 Task 10 有做到。

---

## 三、發現

### Critical

無。

### Important

無。

### Minor

#### m1. zh_TW 新字串用「帳號」，既有介面與另外三句用「帳戶」

- `addon/locale/zh_TW/LC_MESSAGES/nvda.po:42,88,93,98`（新）vs `:217,235,466`（既有）。
- 情境：使用者在設定面板看到「Coseeing 帳戶」，額度用完時聽到「您的 Coseeing 帳號額度已用完」，同一個東西兩個名字。zh_HK（帳戶）與 zh_CN（账户）新舊一致，只有 zh_TW 不一致。
- 建議：四句改成「帳戶」（`您的 Coseeing 帳戶額度已用完。`、`無法確認您的 Coseeing 帳戶…`、`您的 Coseeing 帳戶已停用…`、`Coseeing 帳戶發生衝突…`），或反過來把既有三處改成「帳號」——由使用者定（§五）。`tests/test_coseeing_error_codes.py:30-106` 的 zh_TW 表要同步改。

#### m2. 非長度錯誤的 body 沒有測試擋住多出來的 `"limit": null`

- `server/app/errors.py:73-74`；`server/tests/test_error_codes.py:94-96`。
- 情境：把 `if exc.limit is not None:` 拿掉、永遠寫 `body["limit"] = exc.limit`，250 個測試全綠（突變 M20）。`_coded()` 用 `body.get("limit")`，`None` 與「沒有欄位」分不出來。對附加元件無害（非長度代碼不看 `limit`），但 spec §15.2「`limit`: only on length errors」沒有測試守。
- 建議：在一個配額或模型錯誤的測試加 `assert "limit" not in response.json()`。

#### m3. `provider_failure` 的 `else "other"` 分支到不了

- `server/app/errors.py:54`。
- 情境：`LLMServiceError.__init__` 已經拒絕 `KINDS` 以外的 `kind`（`lib/llm/errors.py:16-18`），所以這個 fallback 永遠不執行；突變 M07 改成 `"configuration"` 全綠。無害，但讀的人會以為有未知 kind 要處理。
- 建議：改成 `PROVIDER_CODES[error.kind]`，或留著並加一行註解說明是防 `lib` 日後放寬時的保險；若留著，`test_each_kind_maps_to_its_provider_code` 可再 parametrize 一個繞過建構子的物件（`SimpleNamespace(kind="made_up")`）來釘住它。

#### m4. `uv pip sync --system` 會把映像檔原有而清單沒列的套件一起移除（含 `pip`），這裡無法驗證

- `server/Dockerfile:13-14`。
- 情境：`uv pip sync` 的語意是「讓環境**恰好**等於清單」，`python:3.14-slim-trixie` 自帶的 `pip` 不在 `requirements.txt`，預期會被移除。執行期不需要 pip（CMD 用 `python -m uvicorn`，遷移用 `python -m alembic`），所以不影響服務；但操作者進容器 `python -m pip …` 會得到 `No module named pip`，可能誤以為映像檔壞了。Docker 不在此環境，我無法實測；帳本的 clean-env 檢查是在 venv 裡做的，venv 本來就沒有 pip 可丟。
- 建議：在 Dockerfile 註解寫明「映像檔內不保留 pip」，或改用 `uv pip install --system --require-hashes --no-cache -r requirements.txt`（只裝、不刪）。第一次 build 時看一眼 `pip` 是否還在，記進交接紀錄。

#### m5. 第一次登入的使用者在 UserInfo HTTP 呼叫期間仍持有 DB 連線（item 4 範圍外）

- `server/app/user/linking.py:218-222`。
- 情境：`_lookup_by_sub()` 開了交易後才 `fetch_userinfo()`（上限 `SSO_USERINFO_TIMEOUT_SECONDS`，正式環境 6 秒）。只影響 `sub` 尚未對應到 `email_verified=True` 的使用者，有界，且與 `918566c` 相同；spec item 4 只處理 AI 呼叫。
- 建議：不必在這次修。若日後再碰連線池，可在 `_lookup_by_sub` 後 `db.commit()` 再呼叫 UserInfo，與 `/proofreader` 同一招。

#### m6. 「全體訪客」配額查詢在訪客列佔多數時 MariaDB 仍會全表掃描

- `server/app/main.py:_sum_cost`（`user_id IS NULL AND request_time > ?`）、索引 `ix_interaction_user_id_request_time`。
- 情境：我灌 20,000 列訪客 + 5,000 列使用者後，`EXPLAIN` 顯示單一 IP 查詢用 `ix_interaction_ip_address_request_time`（26 列）、使用者查詢用 `ix_interaction_user_id_request_time`（1,679 列），但「全體訪客、24 小時」在視窗內佔 27% 時優化器選 `ALL`（24,915 列）；把視窗縮到 1 小時（1%）就用複合索引（278 列）。這是優化器對選擇性的判斷，不是索引設計錯；以目前 360 KB 的表沒有差別。
- 建議：不修。寫進交接紀錄即可：若訪客列成長到讓這個查詢變慢，`(request_time, user_id)` 順序的索引或只掃 `request_time` 的覆蓋索引才會幫到「全體訪客」這一條。

---

## 四、帳本 Ruling 的評估

| # | Ruling | 評估 |
| --- | --- | --- |
| 1 | T1 `sync()` 跳過不在複製樹裡的 UNPREFIXED 路徑 | 合理；風險由 `test_the_unprefixed_files_really_use_the_prefix_in_the_add_on` 擋住；M3 已登記更好的做法 |
| 2 | T4 移除 20 行 `setenv("*_API_KEY")`，斷言改指 `CORRECTION_SETTINGS.api_keys` | 合理，請求路徑確實不讀環境（`test_the_request_uses_the_key_read_at_startup` 刪掉變數仍 200） |
| 3 | T5 兩種模式都在啟動時載入並驗證範圍檔 | 合理；檔案隨映像檔出貨，壞檔是 build 壞；操作者可見的預設（§五） |
| 4 | T5 更新腳本自帶 User-Agent | 合理 |
| 5 | T5 位址正規化後回傳，解析不了的 peer 原樣回傳 | 合理；正是 Review Focus 2 要的；M05 證明有測試 |
| 6 | T7 用 `commit()` 不用 `rollback()`；測試改讓第二次 commit 失敗 | 合理（§二之 3 說明為何 commit 不會多寫東西）；第一次 commit 失敗的路徑 Task 10 補了測試 |
| 7 | T8 downgrade 在有超長 `version` 時拒絕 | 合理且必要（MariaDB DDL 不可回滾）；我在 11.8.6 實證拒絕時 schema 不變 |
| 8 | T8 以 raw SQL 重建 `KEY user_id` | 合理；依賴正式環境索引名為 `user_id`（dump `wob.sql:65` 證實）；離線 SQL 也看得到這一句，部署前可審 |
| 9 | T8 舊列 `template = ''` | 合理（D11 留給實作者）；管理介面可見的預設（§五） |
| 10 | T8 downgrade 後欄位順序不同 | 合理，純外觀；我的 `sort` 比對只差 `AUTO_INCREMENT` |
| 11 | T8 `alembic/env.py` import 兩個 model 模組 | 合理且必要，否則 `alembic check` 無意義；`test_alembic_env_maps_every_model` 守著 |
| 12 | T10 server bug 用 `logger.error` + `masked(traceback)` 而非 `logger.exception` | 合理；traceback 文字相同，多了遮罩；M10 證明遮罩有測試 |
| 13 | T10 catch-all `Exception` handler | 合理；Starlette 仍 re-raise，uvicorn 會記 traceback；M29、M32 被抓 |
| 14 | T10 superuser 403 與 `/feedback` 404 不帶代碼 | 合理，不在 spec 表內，附加元件不呼叫管理路由 |
| 15 | T10 8000 檢查先於訪客 128 | 合理（登入也幫不了 8001 字）；使用者可見的預設（§五） |
| 16 | T9 Translators 註解搬進呼叫內 | 合理；重產 `.pot` 證實仍被抓到 |
| 17 | T11 zh_CN／zh_HK 用 你、账户／帳戶 | 合理，與各自 catalog 既有用法（zh_CN 你×4 您×0；zh_HK 你×4 您×1）一致；使用者可見的預設（§五） |
| 18 | T11 先看 `code` 再看狀態碼 | 合理，spec §15.6 原文如此；伺服器 401 不送代碼（D13） |
| 19 | T11 `limit` 必須是 `int > 0` 且非 `bool` | 合理（Review Focus 4）；M33、M34 被抓 |
| 20 | T12 純 `uvicorn`，不裝 `[standard]` | 合理（spec 留給實作者）；帳本實測 GET / 200。效能面的操作預設（§五） |
| 21 | T12 `--exclude-newer 2026-10-24` | 合理；重新編譯時要往前移，`.in` 有寫 |
| 22 | T12 uv 釘 0.13.5 | 合理 |
| 23 | T12 `SQLAlchemy-Utils`、`zhon` 只當傳遞相依 | 合理；`requirements.txt` 的 `# via fastcrud`／`# via hanzidentifier` 證實；`joserfc` 同理（`# via authlib`，`coseeing_auth` 沒直接 import） |

---

## 五、使用者還沒確認的使用者可見預設

1. **訪客送超過 8000 字聽到的是一般長度訊息，不是訪客訊息**（帳本 R15）：「文字過長，每次最多可校對 8000 字。」而不是「訪客每次最多可校對 128 字，登入 Coseeing 即可校對更長的文字。」理由：登入也校對不了 8001 字。
2. **zh_CN／zh_HK 用「你」**（帳本 R17）：跟各自 catalog 既有的 4 句一致；zh_TW 用「您」（D17）。
3. **spec §17 整張字串表是草稿**（storage/spec.md 標「草稿，請使用者審閱」）：英文 msgid 與 zh_TW 都還沒被使用者逐句確認。特別是：
   - 「帳號」vs 既有介面的「帳戶」（m1）。
   - `guest_quota_exceeded` 的「今日訪客額度已用完」／「Today's guest quota」：配額是滾動的 `QUOTA_WINDOW_HOURS`（正式 24 小時），不是日曆日，「今日」會讓人以為午夜重置。
   - 同一句 `guest_quota_exceeded` 同時用於「這個 IP 用完」與「全體訪客用完」（spec §15.3 如此）。
4. **D5**：email 未驗證、`sub` 不符、email 空白三種情況共用 `account_unverified` 與一句訊息。**D6**：停用帳號聽到專屬訊息「您的 Coseeing 帳號已停用，請聯絡 Coseeing。」**D13**：401 不帶代碼，訊息不變。
5. **狀態碼改變**（使用者已決定原則，但具體值未逐一過目）：訪客文字過長 429→413、8000 字 422→413、模型不可用 404→422、伺服器 bug 502→500。舊版附加元件對新伺服器的 413 會說「The Coseeing request failed」（spec §18）。
6. **D15**：`COSEEING_MODEL_IDS` 裡解析不了的 id 只記 warning，不擋啟動。
7. **舊列的 `template` 是空字串**（R9）：管理路由 `/interactions` 看得到。
8. **AI 服務失敗記 WARNING、server bug 記 ERROR**（`main.py:286,297`）：spec 沒指定等級。
9. **Cloudflare 範圍檔在 `proxy` 模式也必須存在且有效**（R3）。
10. **純 `uvicorn`**（R20）：沒有 `uvloop`／`httptools`，吞吐略低；要的話在 `requirements.in` 改成 `uvicorn[standard]` 重新編譯。
11. **映像檔內可能沒有 `pip`**（m4）。
12. **部署步驟**（M-B2-1）：遷移前要先停伺服器——舊程式還在寫 `category`，`DROP COLUMN` 後它的 INSERT 會失敗。

---

## 六、審閱者自行驗證的項目

| # | 指令／方法 | 結果 |
| --- | --- | --- |
| 1 | `cd <scratch>/review-head/server && /workspace/WordBridge/server/.venv/bin/python -m pytest -q -p no:cacheprovider` | **250 passed**, 5 warnings（6.4 s） |
| 2 | `cd <scratch>/review-head && timeout 900 python3 -m pytest -q -p no:cacheprovider tests` | **1228 passed, 25 skipped, 3 subtests passed**（28.8 s，一次即綠，無需重跑） |
| 3 | `prek run --all-files`（scratch 複本） | 6 個 hook 全部 Passed |
| 4 | `git diff --check 918566c..5bce7cd`；`git log 918566c..5bce7cd` grep `Co-Authored`；`git log --stat` grep `.pot|.mo|.env|__pycache__`；`git ls-files` grep `.pot$|.mo$` | 全部無輸出 |
| 5 | `python3 server/sync_addon_code.py` 後 `git status --porcelain`；`diff -rq` 四個鏡像目錄 | 無變動；只有 UNPREFIXED 的 4 個檔案不同（`prompt.py`、`text_policy.py`、`utils.py`、`chinese.py`）；`addon_version.txt` 與 `buildVars.py` 都是 `2026.11.1` |
| 6 | `msgfmt --check -o /dev/null` ×3；`msgattrib --untranslated` ×3 | 三個都 ok；未翻譯 0／0／0 |
| 7 | scratch 複本 `scons pot` → `msgmerge --no-fuzzy-matching [--no-wrap] -U` → `msgattrib --no-obsolete`，與 commit 的 `.po` diff | zh_TW／zh_CN／zh_HK 除 `POT-Creation-Date` 外 **0 行差異**；`.pot` 有 156 條 Translators 註解；`.pot` 用後刪除 |
| 8 | 既有 catalog 用語計數（`git show 918566c:…nvda.po`） | zh_TW 你0 您8 帳戶3 帳號0 登入3；zh_CN 你4 您0 账户3 登录3；zh_HK 你4 您1 帳戶3 登入3 |
| 9 | 解析 `requirements.txt`／`requirements-dev.txt` | 37／45 個 pin，版本無不一致，dev 多的 8 個都是測試工具（aiosqlite、httpx、httpcore、pytest、pluggy、iniconfig、packaging、pygments）；每個 pin 至少一個 `--hash`；`joserfc` via authlib、`sqlalchemy-utils` via fastcrud、`zhon` via hanzidentifier |
| 10 | venv 內 `starlette.__version__`、`hasattr(Headers, "getlist")` | 1.6.0、True |
| 11 | grep 伺服器四檔與附加元件 `__init__.py` 的代碼集合 | 兩邊都是同一組 15 個代碼 |
| 12 | 突變測試 42 個（表八；腳本在 scratchpad `mutate.py`） | 37 CAUGHT；5 SURVIVED：M07（死碼，m3）、M19（M-B2-3）、M20（m2）、M30（M-B2-2）、M38（換跑 `tests/test_catalog_url_dialog.py` 後 2 failed，CAUGHT） |
| 13 | M08（拿掉 AI 前的 `db.commit()`）只跑 `tests/test_proofreader_connection.py` | 2 個測試都 `assert [1] == [0]` 失敗 |
| 14 | MariaDB 11.8.6-MariaDB-5ubuntu0.1，私有實例 `--port=3307 --bind-address=127.0.0.1`，datadir 在 scratchpad，`sql_mode=STRICT_TRANS_TABLES,…`；流程見表九 | 全部符合預期；結束後 `mariadbd` 已停止 |
| 15 | `alembic upgrade 20260923_sso_user:head --sql`（表九第 4 列） | 8 句 SQL，順序正確；stdout／stderr grep `wbpass` 0 次 |
| 16 | 灌 20,000 訪客列 + 5,000 使用者列後 `ANALYZE` 與三條配額查詢 `EXPLAIN` | 單一 IP：`ix_interaction_ip_address_request_time`（26 列）；使用者：`ix_interaction_user_id_request_time`（1,679 列）；全體訪客 24 h：`ALL`（27% 選擇性）；全體訪客 1 h：複合索引（278 列）（m6） |
| 17 | `MemAvailable` | 開始 9.1 GB，全程未低於 3 GB；pytest 單 worker |
| — | **未驗證** | Docker 映像檔 build（`--mount=from=ghcr.io/astral-sh/uv:0.13.5`、BuildKit、`uv pip sync --system` 對 pip 的影響）；正式環境的 MariaDB 11.3.2（這裡只有 11.8.6；批次 2 審閱者說 11.3.2 有同樣的隱含索引行為）；Traefik 預設的 `X-Forwarded-*` 處理（spec §5.7 部署後檢查）；Windows／NVDA 上的實際語音（spec §19.4 八項） |

### 表八：突變

| # | 突變（檔案） | 結果 | 抓到的測試 |
| --- | --- | --- | --- |
| M01 | 取第一個 XFF 值（`client_ip.py`） | CAUGHT | `test_proxy_mode_uses_the_last_forwarded_value` |
| M02 | `_is_cloudflare` 永遠 True | CAUGHT | `test_cloudflare_mode_ignores_a_forged_header_from_a_non_edge_peer` |
| M03 | `proxy` 模式也信 `CF-Connecting-IP` | CAUGHT | `test_proxy_mode_ignores_cf_connecting_ip`（API 層） |
| M04 | 拿掉 IPv4-mapped 處理 | CAUGHT | `test_select_checks_an_ipv4_mapped_peer_as_ipv4` |
| M05 | `CF-Connecting-IP` 不正規化 | CAUGHT | `test_select_normalises_cf_connecting_ip` |
| M06 | 對調 overloaded／rate_limited 代碼（`errors.py`） | CAUGHT | `test_each_kind_maps_to_its_provider_code[overloaded]` |
| M07 | 未知 kind → configuration | **SURVIVED** | 死碼（m3） |
| M08 | 拿掉 AI 前的 `db.commit()`（`main.py`） | CAUGHT | `test_db_commit_failure_is_5xx…`（-x 先停）；單跑連線測試亦 2 failed |
| M09 | provider 文字不遮罩就記 log | CAUGHT | `test_provider_failure_logs_provider_and_kind_but_never_the_key` |
| M10 | bug traceback 不遮罩 | CAUGHT | `test_a_bug_in_the_ai_call_is_service_error` |
| M11 | 訪客 128 先於 8000 | CAUGHT | `test_text_over_8000_characters_is_413[guest]` |
| M12 | detail 放 `str(error)` | CAUGHT | `test_each_kind_maps_to_its_provider_code` |
| M13 | 空白 key 當作有（`correction_config.py`） | CAUGHT | `test_a_served_provider_without_a_key_stops_startup` |
| M14 | 缺 key 不擋啟動 | CAUGHT | 同上 |
| M15 | 解析不了的 id 擋啟動 | CAUGHT | `test_a_listed_id_whose_local_model_is_inactive_is_rejected` |
| M16 | 不重建 `KEY user_id`（migration） | CAUGHT | `test_upgrade_keeps_the_user_id_index_first` |
| M17 | downgrade 先加欄位再刪索引 | CAUGHT | `test_downgrade_restores_the_previous_shape` |
| M18 | 拿掉超長 version 的 guard | CAUGHT | `test_downgrade_refuses_long_versions_before_any_ddl` |
| M19 | guard 門檻 8 → 80 | **SURVIVED** | M-B2-3（recorder 不看 SQL 文字） |
| M20 | body 永遠帶 `limit`（`errors.py`） | **SURVIVED** | m2 |
| M21 | `CLIENT_IP_SOURCE` 任意值（`settings.py`） | CAUGHT | `test_a_malformed_value_stops_startup[CLIENT_IP_SOURCE-Cloudflare]` |
| M22 | 停用帳號代碼寫錯（`auth.py`） | CAUGHT | `test_a_disabled_account_is_account_disabled` |
| M23 | 衝突代碼寫錯（`linking.py`） | CAUGHT | `test_email_linked_to_other_sub_is_not_reassigned` |
| M24 | `DiscoveryError` 回純 `HTTPException` | CAUGHT | `test_an_unavailable_sso_issuer_is_sso_unavailable` |
| M25 | `template` 存成含 `.json` | CAUGHT | `test_the_stored_template_is_the_template_stem` |
| M26 | `version` 硬編回 `20260425` | CAUGHT | `test_the_stored_version_is_the_add_on_version` |
| M27 | 空白版本檔接受 | CAUGHT | `test_a_missing_or_blank_version_file_stops_startup[blank]` |
| M28 | offline 讀回 `placeholder`（`env.py`） | CAUGHT | `test_offline_upgrade_prints_the_sql` |
| M29 | 拿掉 catch-all handler | CAUGHT | `test_an_unexpected_error_elsewhere_is_service_error` |
| M30 | `get_client_ip` 只讀一個 header | **SURVIVED** | M-B2-2 |
| M31 | `ApiError` body 不帶 `code` | CAUGHT | `test_guest_text_over_the_guest_limit_is_413` |
| M32 | catch-all body 不帶 `code` | CAUGHT | `test_an_unexpected_error_elsewhere_is_service_error` |
| M33 | 附加元件接受 `bool` limit | CAUGHT | `test_unusable_limit_falls_back_to_status_message[bool]` |
| M34 | 接受 `0` | CAUGHT | `…[zero]` |
| M35 | 對調 overloaded／error 訊息 | CAUGHT | `test_each_code_speaks_its_message[provider_overloaded]` |
| M36 | 只在 5xx 看代碼 | CAUGHT | `test_each_code_speaks_its_message[account_conflict]` |
| M37 | 非 dict body 不擋 | CAUGHT | `test_non_object_body_falls_back` |
| M38 | log 訊息包 `_()` | CAUGHT | `test_log_messages_are_not_translated[__init__.py]`、`test_every_translatable_string_has_a_translators_comment[__init__.py]`（第一輪只跑三個檔案時存活，是我選檔的問題） |
| M39 | lib 529 → other（`provider.py`） | CAUGHT | `test_an_http_error_has_its_kind[529]` |
| M40 | `_error_detail` 退回 `response.text` | CAUGHT | `test_other_status_bodies_never_crash[no-reason-html]` |
| M41 | 403 → other | CAUGHT | `test_an_http_error_has_its_kind[403]` |
| M42 | `try_connection` → other | CAUGHT | `test_unreachable_errors_have_kind_unreachable` |

### 表九：MariaDB 11.8.6 遷移重跑

| 步驟 | 指令 | 結果 |
| --- | --- | --- |
| 1 | `DROP DATABASE IF EXISTS WordBridge; CREATE DATABASE … utf8mb4` | 乾淨起點 |
| 2 | 在 `<scratch>/base-918566c/server` 以 venv 執行 `Base.metadata.create_all`（import `app.models.models`、`app.user.models`） | `interaction`：`version varchar(8)`、`category varchar(8)`、`KEY user_id`、`KEY review_user_id`，兩個 FK；與 `wob.sql` 的形狀一致 |
| 3 | 插入一列舊資料（`version='20260425'`, `category='1'`）；`alembic stamp 20260923_sso_user` | `current` = `20260923_sso_user` |
| 4 | `alembic upgrade 20260923_sso_user:head --sql` | 依序 `ALTER TABLE interaction DROP INDEX user_id, ADD INDEX user_id (user_id)`、兩句 `CREATE INDEX`、`MODIFY version VARCHAR(32) NOT NULL`、`ADD COLUMN template VARCHAR(64) NOT NULL DEFAULT ''`、`ALTER COLUMN template DROP DEFAULT`、`DROP COLUMN category`、`UPDATE alembic_version`；grep 密碼 0 次 |
| 5 | `alembic upgrade head`；`SHOW CREATE TABLE` | `version varchar(32) NOT NULL`、`template varchar(64) NOT NULL`（無預設）、無 `category`、`KEY user_id` 仍在、兩個複合索引、兩個 FK 不變；舊列 `template=''` |
| 6 | `alembic check` | `No new upgrade operations detected.` |
| 7 | 插入 `version='2026.11.1'` 列；`alembic downgrade -1` | `RuntimeError: 1 interaction rows have a version longer than 8 characters … Nothing was changed.`；`current` 仍 head；`SHOW CREATE TABLE` 與步驟 5 只差 `AUTO_INCREMENT` |
| 8 | 刪該列；`alembic downgrade -1` | `current` = `20260923_sso_user`；`version varchar(8)`、`category varchar(8) DEFAULT NULL`（舊列為 NULL）、無 `template`、無複合索引、`KEY user_id` 仍在；與步驟 2 排序比對只差 `AUTO_INCREMENT`（`category` 與 `KEY user_id` 位置不同，R10） |
| 9 | `alembic upgrade head`；`alembic check`；`SHOW CREATE TABLE` | 與步驟 5 逐字相同（除 `AUTO_INCREMENT`）；check 乾淨 |
| 10 | 灌資料後 `EXPLAIN`（表六第 16 列） | 見 m6 |

---

## 七、Windows／NVDA 尚未驗證的手動項目

spec §19.4 的八項都還沒做（這裡沒有 NVDA）：訪客超過 128 字、超過 8000 字、兩種配額用完、模型不可用、`provider_configuration`／`provider_unreachable`（需測試伺服器）、三種語言的語音與 `{limit}` 代入、對舊伺服器的退路、本機模式訊息不變。另加兩項：spec §5.7 的部署後 client IP 檢查，與 m4 的映像檔內 `pip` 是否還在。

## 修正記錄

（§3.4 填寫）
