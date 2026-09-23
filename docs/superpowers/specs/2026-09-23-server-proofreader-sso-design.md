# Server 校正流程移植與 SSO 身分關聯

## 目的與成功條件

讓 `server/app/main.py` 的 `/proofreader` 真正執行 WordBridge add-on 的本地校正工作流程，並讓 server 使用統一 SSO 身分。訪客仍可校正且受到既有額度限制；登入者由已驗證的 SSO token 對應到 server 自己的 `User`。部署者可設定 `"default"` 實際使用的模型。完成後，server 能啟動、處理校正及回饋、寫入互動紀錄，並以依賴項控制各路由權限。

本設計延續已確認的討論。只移植 `addon/globalPlugins/WordBridge/__init__.py::correctTypo()` 中 `execution_channel == LOCAL_CHANNEL` 的執行邏輯；該函式的 `else` 是 add-on 呼叫 server 的客戶端程式碼，不是 server 要再執行一次的路徑。add-on 的 NVDA 操作、通知和 UI 狀態也不屬於 server。

## 已確認的產品與安全決策

| 項目 | 決策 |
| --- | --- |
| 預設模型 | `corrector_config_id="default"` 由 server 解析成部署時可更換的模型 ID。 |
| 訪客 | 無 token 可呼叫 `/proofreader`；維持長度、每 IP 與全站訪客額度限制。 |
| 登入 | 只接受 SSO access token；停用舊 `/login`，不再使用 server 自簽 HS256 token。 |
| 首次關聯 | 先驗 access token，再用同一枚 token 查 SSO UserInfo，要求相同 `sub`、非空 email、`email_verified` **嚴格為 `true`**。 |
| 建立 user | 用已驗證 email 查既有 `User.account`；命中則綁定 `sub`，否則以該 email 建立新的 server user 並綁定。 |
| 後續請求 | 每次都驗 access token；若 `sub` 已對應到 `email_verified=True` 的本地 user，直接使用本地欄位，不再為此呼叫 UserInfo。 |
| 管理路由 | `/users` 與 `/interactions` CRUD 只開放已登入且 `is_superuser=True` 的 server user。 |
| 回饋 | 訪客可提交該次校正的回饋；此階段只依 `interaction_id` 找互動，不加入回饋憑證或 IP 綁定。 |
| 相依套件 | `coseeing_auth` 已放在 `server/app/package/coseeing_auth`，從專案原始碼匯入；第三方套件由 pip 安裝。 |

## 現況與改動範圍

目前 `/proofreader` 混入尚未移除的 add-on 專用欄位與函式，例如 `self`、`DEBUG_MODE`、`provider`、`model`、`_diff_`，並 import server 不存在的 `configManager`、`settings_repository`。catalog registry 沒有初始化。`get_auth_user_or_none` 因 `OAuth2PasswordBearer(auto_error=True)` 在無 token 時已先拒絕請求；`/feedback` 與 CRUD 仍依賴舊 HS256 登入。這些是本次要解決的執行與權限缺口。

主要修改面：

- `server/app/main.py`：校正、回饋、路由依賴與初始化。
- `server/app/user/`：SSO 依賴、user 查找與建立、模型及對應 schema；移除舊登入與註冊路由。
- `server/app/package/coseeing_auth/`：沿用目前程式碼；不另行安裝 `coseeing_auth`，也不改 token 驗證策略。
- `server/app/lib/`、`server/requirements.txt`：讓 server 專用的校正依賴使用一般 pip 套件，不依賴 NVDA `_wb_vendor` 或 `addonHandler`。
- Alembic migration：新增 SSO 欄位、調整帳號欄位長度，並刪除 user 密碼欄位。
- `server/app/imp.py` 與 `server/test/` 中仍引用 `User.password`、`/login` 或舊 payload 的資料匯入及呼叫範例：配合 SSO 流程更新或移除失效範例。

不變更 add-on 的請求格式，不修改 SSO 系統，也不移植 add-on 的遠端呼叫分支。

## 部署設定與初始化

| 設定 | 值與用途 |
| --- | --- |
| `SSO_ISSUER` | 預設 `https://sso.coseeing.org`；供現有 `AuthConfig` 和 `TokenVerifier` 使用。 |
| `SSO_CLIENT_ID` | 預設 `wordbridge`；與 add-on 使用的 SSO client 一致。 |
| `SSO_USERINFO_URL` | 預設 `https://sso.coseeing.org/userinfo`；部署在不同 SSO 環境時一併指定。 |
| `DEFAULT_CORRECTOR_CONFIG_ID` | 預設 `deepseek-v4-flash&DeepSeek`；部署者可指定另一個 catalog 中啟用且可執行的本地模型 ID。 |
| `<PROVIDER>_API_KEY` | 依實際所選模型的 provider 名稱取得，例如 `DEEPSEEK_API_KEY`。 |

server 啟動時讀取 `server/app/setting/catalog.json`，以 `BundledCatalogSource` 與 `load_catalog(..., runnable_providers=SUPPORTED_PROVIDERS)` 建立 catalog；讀取 `server/app/setting/task/corrector.json` 取得校正模式的模板與 optional guidance。這些物件由 server 模組或 FastAPI app state 持有，請求處理時明確取得，不使用 add-on 的 `self` 或未初始化的 registry。啟動時檢查預設模型 ID 是否指向 catalog 中啟用、provider 可執行的本地模型；無效設定要清楚報錯，不能悄悄改選別的模型。catalog 的 fallback `"default"` 僅含 Coseeing 項目，不能當成 server 本地執行模型。

`coseeing_auth` 從 `app.package.coseeing_auth` 匯入。它的 `AuthConfig` 需要 loopback `login_redirect_uri`，server 可給符合型別約束的固定本地 URI；server 不執行 OAuth 登入跳轉。`TokenVerifier` 使用 `OidcProtocol.discovery`。現有驗證器首次使用會取得 discovery/JWKS，之後使用快取；新 `kid` 可能重新抓公鑰，JWT 校驗失敗可能呼叫線上 introspection。**每次請求仍驗 token；本地 `email_verified` 快取只省去後續 UserInfo 查詢。** 不承諾所有 token 驗證都完全離線，也不修改驗證器以強制離線。

## SSO 依賴與本地 user

依照 `/workspace/SSO/SSO/server/fastapi/dependencies.py` 的分層方式建立 FastAPI dependencies，但用資料庫 `User` 取代該範例的暫存 dict：

1. 可選 Bearer 擷取：無 `Authorization` 視為訪客；提供了格式錯誤或非 Bearer 的 header 視為無效憑證。
2. 驗證 access token：呼叫既有 `TokenVerifier.verify_access_token()`，取得已驗證的 `subject`。失敗時拒絕，不能降級成訪客。
3. 解析或建立本地 user：先依唯一 `sso_sub` 查找；若該列 `email_verified=True`，直接回傳。若查無 `sub`，或查到但本地 `email_verified=False`，走 UserInfo 確認流程。
4. 可選 user dependency：無 token 回傳 `None`，供 `/proofreader`、`/feedback` 使用。
5. 必要 user dependency：無 token 回 401；管理員 dependency 再要求 `is_superuser=True`，否則 403。

UserInfo 使用**同一枚 access token**，HTTP Bearer 呼叫 `SSO_USERINFO_URL`，設定明確 timeout。要求回應為物件，`sub` 是字串且等於已驗證 token 的 `subject`，`email` 是非空字串，`email_verified is True`；任何一項不符都不建立或綁定 user。UserInfo 的 `sub` 必須與 token subject 一致，也符合 [OpenID Connect Core 的 UserInfo 驗證要求](https://openid.net/specs/openid-connect-core-1_0.html#UserInfoResponse)。這個 email 來自 UserInfo；access token 的 email 欄位即使存在，也不代替首次 UserInfo 的驗證結果。

資料模型與 migration：

- `User.sso_sub`：可空、唯一、長度足以存 SSO subject；舊帳號先保持 `NULL`。唯一索引允許多筆 `NULL`。
- `User.email_verified`：不可空布林，既有列資料回填 `false`；首次 UserInfo 驗證成功才改為 `true`。之後這個本地值是「曾經驗證且已建立關聯」的持久記錄；SSO 日後撤銷 email 驗證，不會被每次請求即時發現。
- `User.account`：仍是唯一 email/帳號鍵，但 `String(30)` 不足以容納一般 email；擴至 254 字元。以 email 查舊 user 時應按資料庫的大小寫不敏感比對語意處理，並靠唯一限制防止重複。
- `User.password`：直接從 ORM 模型、資料庫欄位及 user CRUD schema 移除；migration 刪除既有密碼資料。server 不再驗證、儲存或回傳本地密碼，舊帳號仍可透過已驗證 email 與 SSO `sub` 建立關聯。

首次確認 UserInfo 後，若 `sso_sub` 已有 user，更新該列的 email 驗證狀態；若無，依已驗證 email 查 `User.account`。匹配到無 `sso_sub` 的舊 user 時，填入 `sso_sub`、`email_verified=True`。若 email 已屬於**不同** `sso_sub`，回 409，不能接管該 user。若 email 沒有匹配，建立 `account=<已驗證 email>`、`sso_sub=<verified subject>`、`email_verified=True`、`is_active=True`、`is_superuser=False`、24 小時額度 `quota=0.1` 的 user；名稱可取 UserInfo `name`，缺少時用 email 並符合欄位長度。綁定與建立需以 transaction 和資料庫唯一限制處理同時請求：遇唯一衝突先 rollback、重讀 `sso_sub`/email，再只接受與同一 subject 一致的結果。既有 `is_active=False` 的 user 綁定後仍保持停用，授權時回 403。

本地 `email_verified=True` 後不再要求 UserInfo；每次仍依 SSO token 驗證結果的 `sub` 查 server user。這個快取行為是已確認需求，而非把 access token 的 email claim 當作已驗證。SSO UserInfo 連線或回應失敗時，只影響首次綁定或本地尚未驗證的 user，回 503，不把請求當訪客。

## 路由權限

| 路由 | 無 token | 有效 SSO token | 無效 token |
| --- | --- | --- | --- |
| `POST /proofreader` | 訪客限制 | 本地 user 額度；superuser 免額度 | 401 |
| `POST /feedback` | 可依 `interaction_id` 提交 | 可依 `interaction_id` 提交，記錄回饋 user | 401 |
| `/users` CRUD | 401 | 僅 superuser；一般 user 403 | 401 |
| `/interactions` CRUD | 401 | 僅 superuser；一般 user 403 | 401 |
| `/login`、`/register` | 不再提供 | 不再提供 | 不再提供 |

`/feedback` 沿用 `interaction_id`、`review_content` 請求欄位。查不到互動時 404。訪客回饋將 `review_user_id` 保持 `NULL`；登入者記錄其 user ID。採用「只看 interaction_id」的已確認規則，因此**知道有效 interaction ID 的人可以寫入或覆寫該筆回饋**；這是此階段的明確限制，不宣稱已確認回饋者就是原校正者。移除現有 `feedback` 函式中 `raise` 後不可到達的錯誤程式碼。

## `/proofreader` 校正流程

請求沿用 add-on 目前傳送的 JSON：

```json
{
  "request": "待校正文字",
  "corrector_config_id": "default",
  "language": "zh_traditional",
  "typo_correction_mode": "standard",
  "customized_words": []
}
```

`request` 為非空字串；`corrector_config_id`、`language`、`typo_correction_mode` 為所需字串，`customized_words` 為字串陣列（未提供時可用空陣列）。`language` 只接受 add-on 會送出的 `zh_traditional`、`zh_simplified`。依任務設定檔驗證 mode 並取得 `template_name`、`optional_guidance_enable`；其餘無效 payload 回 422，避免目前的 `KeyError` 或未定義變數。server 直接使用 payload 的 `customized_words`，不讀 add-on 本機字典或 UI 設定。

1. 取得可選 user 與 client IP。先套用既有 24 小時額度：訪客文字長度大於 128 字拒絕；同 IP 訪客花費達 0.06 拒絕；所有訪客合計達 0.3 拒絕；登入 user 花費達其 `quota` 拒絕，superuser 免此限制。查詢使用 `Interaction.cost` 的 Decimal 金額與 UTC 時間；達上限回 429。現階段沿用既有 `get_client_ip()` 的 `X-Forwarded-For` 取值方式。
2. `corrector_config_id="default"` 時解析成 `DEFAULT_CORRECTOR_CONFIG_ID`，否則使用請求的 ID。明確指定的 ID 需要是 catalog 啟用的 `coseeings` offer，而且能對應啟用的 `models` 本地條目；解析後確認 provider 條目存在且 server 支援。`CorrectorCatalog.get_model()` 本身不檢查 `active`，此處需自行檢查。找不到或無法執行時回 404；部署的預設模型若不符合條件，啟動設定檢查應先失敗。
3. 依 model provider 取對應環境變數 API key。呼叫 `run_typo_correction(request=text, batch_mode=True, provider_name=..., model_name=..., credential=..., provider_entry=..., price_entry=..., language=..., template_name=..., corrector_mode=..., optional_guidance_enable=..., customized_words=..., retries=2, backoff=1)`。這對應 add-on `LOCAL_CHANNEL` 分支的執行參數；server 的 `batch_mode=True` 對應正式環境 `DEBUG_MODE=False`。缺少憑證或 provider 執行失敗應回清楚的 5xx 並記錄安全的錯誤資訊，不把 API key 或原始 token 放進回應/日誌，也不寫成功互動。
4. 取得 `result.corrected_text`、`result.cost`，以 `strings_diff(text, corrected_text)` 產生 diff。成功後寫一筆 `Interaction`，含 UTC request/response time、原文與結果、IP、Decimal cost、**實際執行的模型 ID**、既有 category/version 值及可空 user 關聯；提交成功才回應。

回應維持既有 add-on 期待的欄位：

```json
{
  "request": "待校正文字",
  "response": "校正結果",
  "diff": [],
  "interaction_id": 123,
  "cost": "0.000001"
}
```

`diff` 的實際結構由 `strings_diff()` 回傳；`cost` 沿用 `decimal_to_str_0()` 的十進位字串表示。資料庫寫入失敗要 rollback 並回 5xx，不能回報一個沒有儲存的 `interaction_id`。

## 錯誤邊界

| 狀況 | 對外結果 |
| --- | --- |
| 無 token 且路由允許訪客 | 訪客流程 |
| token 格式錯誤、過期或驗證不通過 | 401，附 Bearer authentication header |
| UserInfo `sub` 不同、email 空白、`email_verified` 非布林 `true` | 403，不綁定或建立 user |
| UserInfo 暫時無法取得、逾時或無法解析 | 503，只在需要 UserInfo 時發生 |
| email 已綁定不同 `sub`，或唯一性衝突不能安全恢復 | 409 |
| 已停用 user；一般 user 訪問管理 CRUD | 403 |
| 額度達上限 | 429 |
| payload 或 mode 無效 | 422 |
| 明確指定模型不存在、停用或無可執行本地條目 | 404 |
| provider/資料庫執行失敗 | 5xx；服務端記錄可排查資訊，回應不含秘密 |

## 驗收與可執行證據

實作階段需在 server 支援的 Python 環境安裝第三方依賴，確認 `app.main` 可 import、FastAPI 可啟動，且沒有 `_wb_vendor`、`self`、缺失模組或未定義名稱阻止請求。更新 `requirements.txt`（含本地 `coseeing_auth` 所需的 `Authlib`、`PyJWT[crypto]`、`requests` 與校正流程需要的文字套件），並確認 Alembic migration 能對既有資料套用。

以模擬的 SSO 回應與 provider 執行進行路由驗收，避免自動檢查花費真實模型額度：

- 無 token 可校正並寫入互動；訪客文字、同 IP 及全站額度邊界均回 429。
- 有效 token 首次呼叫 UserInfo；匹配舊 `User.account` 即綁定；無匹配即建立 email 帳號。後續相同 `sub` 且本地驗證旗標為 true 時不呼叫 UserInfo，但仍每次驗 token。
- 本地旗標為 false 時再次查 UserInfo；錯誤 `sub`、空 email、非嚴格 true、無效 token、SSO 逾時及跨 `sub` 衝突均依上表處理；並行首次請求不產生重複 user。
- 一般 user 受 24 小時額度限制，superuser 可通過；一般 user 與訪客無法操作兩組 CRUD，superuser 可以。
- 訪客與登入者可提交 `interaction_id` 回饋；訪客 `review_user_id` 為空；無效 ID 回 404。
- `default` 與啟用的明確模型都能解析成 catalog 本地條目，回應含可用 diff、正確成本與互動 ID，資料庫記錄實際模型。停用或未知模型被拒絕。

實際 SSO UserInfo 與真實模型呼叫需在具備相應 token、API key 和網路的部署環境做整合檢查；本地模擬通過不等同已驗證外部服務可用。
