# Server Proofreader 與 SSO 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 server 以可設定模型執行 add-on 本地校正流程，並用 SSO access token 關聯本地 user，同時維持訪客額度、回饋與管理權限。

**Architecture:** 校正設定及模型解析獨立於 FastAPI 路由；SSO token 驗證、UserInfo 查詢及本地 user 關聯分層為 dependencies。路由只處理 payload、額度、工作流程、互動資料與 HTTP 回應。資料庫 migration 直接刪除 `User.password`。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、MySQL、Pydantic 2、pytest、既有 `app.package.coseeing_auth`、現有 catalog/typo workflow。

**Spec:** `docs/superpowers/specs/2026-09-23-server-proofreader-sso-design.md`

## Global Constraints

- 只移植 add-on `execution_channel == LOCAL_CHANNEL` 的邏輯；`/proofreader` 請求與回應欄位維持 spec 格式。
- `SSO_ISSUER` 預設 `https://sso.coseeing.org`；`SSO_CLIENT_ID` 預設 `wordbridge`；`SSO_USERINFO_URL` 預設 `https://sso.coseeing.org/userinfo`。
- `DEFAULT_CORRECTOR_CONFIG_ID` 預設 `deepseek-v4-flash&DeepSeek`，部署時可覆蓋；只允許 catalog 中啟用、可執行的本地模型。
- 每次有 token 都呼叫現有 `TokenVerifier.verify_access_token()`；本地 `email_verified=True` 只略過 UserInfo。
- 首次關聯要求 UserInfo `sub` 等於驗證後 token subject、email 非空、`email_verified is True`；`User.password` 從模型、schema、資料庫移除。
- 訪客限制：文字長度 128、每 IP 24 小時成本 0.06、全站訪客 24 小時成本 0.3；一般 user 以本地 quota 比較，superuser 免額度。
- `/users` 與 `/interactions` CRUD 只允許 `is_superuser=True`；訪客回饋只依 `interaction_id`，`review_user_id=NULL`。
- `coseeing_auth` 使用 `server/app/package/coseeing_auth` 的原始碼；第三方套件用 pip。實作任務不得變更 add-on、SSO 系統或 token 驗證器內部策略。
- `server/` 目前在 git 中是未追蹤的既有工作。執行時保留其全部內容；每次提交只 stage 該任務明列的檔案，先確認 `git status`，不得把整個 `server/` 加入暫存區。

## Review Focus

下列五項在對應任務各有測試，review 時特別確認：

1. 有 `Authorization` 但 Bearer 格式錯誤／驗證失敗，應為 401，不能落入訪客額度。（Task 4）
2. 同一 email 已連到另一個 `sso_sub`，應為 409，且原關聯不可改寫。（Task 3）
3. catalog 的 `get_model()` 會回傳停用模型；停用的 Coseeing offer 或本地 model 均不得執行。（Task 2、5）
4. guest 成本比較使用 Decimal；訪客額度達 0.06 或全站 0.3 時拒絕，即使沒有 token。（Task 5）
5. 訪客回饋不得寫入不存在的 user ID；同一個 `interaction_id` 的回饋可被後續提交覆寫。（Task 6）

## 檔案與責任

| 檔案 | 責任 |
| --- | --- |
| `server/app/user/models.py`、`server/app/user/schemas.py` | 本地 user 欄位及 CRUD payload，移除 password。 |
| `server/alembic/versions/20260923_sso_user.py` | SSO 欄位、帳號長度、刪除 password 的 migration。 |
| `server/app/correction_config.py` | 讀 catalog／task 設定、驗證部署預設模型、解析 request model。 |
| `server/app/user/linking.py` | 用 UserInfo 驗證 email，原子查找／綁定／建立本地 user。 |
| `server/app/user/auth.py` | Bearer 擷取、TokenVerifier、optional/required/superuser dependencies。 |
| `server/app/main.py` | 校正、回饋、CRUD router 及初始化。 |
| `server/app/lib/text/chinese.py`、`server/app/lib/tasks/typo/{utils,prompt,text_policy}.py`、`server/requirements.txt` | server workflow 可直接以 pip 依賴匯入。 |
| `server/app/imp.py`、`server/test/*.py` | 移除密碼登入與失效的手動呼叫。 |
| `server/tests/*.py` | 無外部 SSO／模型花費的自動驗證。 |

---

### Task 1: User 模型與資料庫 migration

**Files:**
- Modify: `server/app/user/models.py`
- Modify: `server/app/user/schemas.py`
- Create: `server/alembic/versions/20260923_sso_user.py`
- Test: `server/tests/test_user_storage.py`
- Create: `server/tests/conftest.py`

**Interfaces:**
- Consumes: 既有 `app.baseModel.Base`、`User.account` 唯一鍵、Alembic revision `dad5039f4770`。
- Produces: `User.sso_sub: str | None`、`User.email_verified: bool`、無 `User.password`；`User.account` 最長 254 字元。

- [ ] **Step 1: 建立共用 SQLite session fixture，寫失敗的 schema 測試。** `server/tests/conftest.py` 使用每項測試獨立的記憶體資料庫，供後續任務重用：

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.baseModel import Base
from app.user.models import User


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()
```

`server/tests/test_user_storage.py` 檢查欄位：

```python
from sqlalchemy import create_engine, inspect
from app.baseModel import Base
from app.user.models import User


def test_user_has_sso_fields_and_no_password():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    columns = {column["name"]: column for column in inspect(engine).get_columns("user")}
    assert "sso_sub" in columns
    assert "email_verified" in columns
    assert "password" not in columns
    assert User.__table__.c.account.type.length == 254
```

- [ ] **Step 2: 執行 `cd server && python -m pytest tests/test_user_storage.py -q`，確認新欄位斷言失敗。**
- [ ] **Step 3: 修改 ORM 與 schema。** `User` 加 `sso_sub = mapped_column(String(255), unique=True, nullable=True, default=None)`、`email_verified = mapped_column(Boolean, default=False, nullable=False)`；將 `account` 設為 `String(254)`，完全刪除 password；調整 dataclass 有預設值欄位順序。CRUD schema 只含允許管理員維護的欄位，例如 `account`、`name`、`is_active`、`is_superuser`、`quota`，且不接受或回傳 password。
- [ ] **Step 4: 寫 Alembic revision。** `upgrade()` 對 `user` 新增可空 `sso_sub`、不可空且既有列回填 false 的 `email_verified`、擴大 `account`、建立 `sso_sub` 唯一索引，最後 `drop_column("user", "password")`；`downgrade()` 撤銷 SSO 欄位及長度並以 nullable password 欄位表明原密碼不可恢復。MySQL 的 `alter_column` 明列原型別和 nullable 狀態；不得在 production 自動執行 migration。
- [ ] **Step 5: 再跑測試與 migration 靜態檢查。** 執行 `cd server && python -m pytest tests/test_user_storage.py -q`、`python -m compileall -q app/user alembic/versions/20260923_sso_user.py`。有可用測試資料庫時另跑 Alembic upgrade；正式資料庫只在部署流程執行。
- [ ] **Step 6: 只 stage 本任務的五個檔案並提交** `feat(server): add SSO user fields and remove passwords`。

### Task 2: Server 校正設定與 pip 匯入

**Files:**
- Create: `server/app/correction_config.py`
- Modify: `server/app/lib/text/chinese.py`
- Modify: `server/app/lib/tasks/typo/utils.py`
- Modify: `server/app/lib/tasks/typo/prompt.py`
- Modify: `server/app/lib/tasks/typo/text_policy.py`
- Modify: `server/requirements.txt`
- Test: `server/tests/test_correction_config.py`

**Interfaces:**
- Consumes: `BundledCatalogSource`、`load_catalog`、`SUPPORTED_PROVIDERS`、`setting/task/corrector.json`。
- Produces: `load_correction_settings() -> CorrectionSettings`；`resolve_model(settings, requested_id: str) -> ModelEntry`。

- [ ] **Step 1: 寫失敗的設定測試。** 以真正 bundled catalog 驗證 default、明確模型和停用條目：

```python
import pytest
from app.correction_config import load_correction_settings, resolve_model


def test_default_resolves_to_local_model(monkeypatch):
    monkeypatch.setenv("DEFAULT_CORRECTOR_CONFIG_ID", "deepseek-v4-flash&DeepSeek")
    settings = load_correction_settings()
    assert resolve_model(settings, "default").model == "deepseek-v4-flash"
    assert resolve_model(settings, "gpt-5.6-luna&OpenAI").provider == "OpenAI"


def test_inactive_model_is_rejected(monkeypatch):
    monkeypatch.setenv("DEFAULT_CORRECTOR_CONFIG_ID", "deepseek-v4-flash&DeepSeek")
    settings = load_correction_settings()
    with pytest.raises(LookupError):
        resolve_model(settings, "qwen2&Ollama")


def test_inactive_coseeing_offer_is_rejected(monkeypatch):
    from dataclasses import replace
    monkeypatch.setenv("DEFAULT_CORRECTOR_CONFIG_ID", "deepseek-v4-flash&DeepSeek")
    settings = load_correction_settings()
    offers = tuple(replace(offer, active=False) if offer.corrector_config_id == "gpt-5.6-luna&OpenAI" else offer
                   for offer in settings.catalog.coseeings)
    settings = replace(settings, catalog=replace(settings.catalog, coseeings=offers))
    with pytest.raises(LookupError):
        resolve_model(settings, "gpt-5.6-luna&OpenAI")


def test_invalid_deployment_default_fails_startup(monkeypatch):
    monkeypatch.setenv("DEFAULT_CORRECTOR_CONFIG_ID", "missing&Provider")
    with pytest.raises(ValueError):
        load_correction_settings()
```

- [ ] **Step 2: 執行 `cd server && python -m pytest tests/test_correction_config.py -q`，確認模組或函式缺少而失敗。**
- [ ] **Step 3: 建立設定載入與模型解析。** `CorrectionSettings` 使用 frozen dataclass 保存 catalog、`template_name` dict、`optional_guidance_enable` dict 與 `default_id`；`load_correction_settings()` 讀取相對於 `__file__` 的設定路徑及環境變數，解析 JSON，驗證預設 ID。`resolve_model()` 對非 `default` 的 ID 先要求 `catalog.get_coseeing(id)` 存在且 active，再要求同 ID 的本地 `catalog.get_model(id)` 存在且 active，並檢查 provider；對 default 則要求設定的本地條目 active。找不到拋 `LookupError`，部署預設無效拋 `ValueError`。

```python
def resolve_model(settings, requested_id: str):
    selected_id = settings.default_id if requested_id == "default" else requested_id
    if requested_id != "default":
        offer = settings.catalog.get_coseeing(selected_id)
        if offer is None or not offer.active:
            raise LookupError(selected_id)
    model = settings.catalog.get_model(selected_id)
    if model is None or not model.active or settings.catalog.get_provider(model.provider) is None:
        raise LookupError(selected_id)
    return model
```

- [ ] **Step 4: 把校正 import graph 中的 `_wb_vendor` 引用改為 pip 套件名。** `hanzidentifier`、`pypinyin`、`chinese_converter` 使用一般 import；`requirements.txt` 增加 `Authlib`、`PyJWT[crypto]`、`hanzidentifier`、`pypinyin`、`chinese-converter`，保留 `requests`，依安裝解析結果固定相容版本。`coseeing_auth` 不寫進 requirements；Dockerfile 原有 `pip install -r requirements.txt` 即安裝新增依賴。
- [ ] **Step 5: 重跑設定測試及匯入檢查。** `cd server && python -m pytest tests/test_correction_config.py -q`，接著執行 `python -c 'from app.lib.application.task_runner import run_typo_correction; from app.correction_config import load_correction_settings; print(load_correction_settings().default_id)'`。此時不得需要 NVDA 或 `_wb_vendor`。
- [ ] **Step 6: 只 stage 本任務檔案並提交** `feat(server): load runnable correction models`。

### Task 3: UserInfo 驗證與本地 user 關聯

**Files:**
- Create: `server/app/user/linking.py`
- Test: `server/tests/test_sso_linking.py`

**Interfaces:**
- Consumes: Task 1 的 `User.sso_sub`、`User.email_verified`；已驗證的 `sub`、原 access token、SQLAlchemy `Session`。
- Produces: `resolve_local_user(db: Session, sub: str, token: str) -> User`；回應 403、409、503 的 `HTTPException`。

- [ ] **Step 1: 寫失敗測試。** 使用 Task 1 的 `db` fixture，以 monkeypatch 取代 UserInfo HTTP 呼叫；覆蓋舊 email 綁定、新 user 建立、本地 verified 快路徑、`sub` 不同、`email_verified=1`、相同 email 不同 `sub` 衝突。核心例子：

```python
from app.user.models import User
from app.user.linking import resolve_local_user


def test_existing_verified_sub_does_not_call_userinfo(db, monkeypatch):
    user = User(account="a@example.org", name="A", sso_sub="s1", email_verified=True,
                is_active=True, quota=0.1)
    db.add(user)
    db.commit()
    monkeypatch.setattr("app.user.linking.fetch_userinfo", lambda token: (_ for _ in ()).throw(AssertionError("UserInfo called")))
    assert resolve_local_user(db, "s1", "access-token").id == user.id


def test_email_linked_to_other_sub_is_not_reassigned(db, monkeypatch):
    from fastapi import HTTPException
    user = User(account="a@example.org", name="A", sso_sub="s1", email_verified=True,
                is_active=True, quota=0.1)
    db.add(user)
    db.commit()
    monkeypatch.setattr("app.user.linking.fetch_userinfo", lambda token: {
        "sub": "s2", "email": "a@example.org", "email_verified": True
    })
    try:
        resolve_local_user(db, "s2", "access-token")
        assert False, "expected conflict"
    except HTTPException as error:
        assert error.status_code == 409
    db.refresh(user)
    assert user.sso_sub == "s1"
```

- [ ] **Step 2: 執行 `cd server && python -m pytest tests/test_sso_linking.py -q`，確認缺少 linking 模組。**
- [ ] **Step 3: 實作 `fetch_userinfo(token: str) -> dict`。** 以 `requests.get(SSO_USERINFO_URL, headers={"Authorization": f"Bearer {token}"}, timeout=6)` 呼叫 SSO；HTTP 錯誤、逾時、非物件 JSON 映射為 503，日誌不輸出 token 或原始回應。`sub` 不同、空白 email、`email_verified is not True` 映射 403。
- [ ] **Step 4: 實作 `resolve_local_user`。** 先查 `User.sso_sub == sub` 且 `email_verified=True` 的快路徑；其餘情況查 UserInfo，對既有 sub 更新驗證旗標，否則用已驗證 email 對 `User.account` 做資料庫大小寫不敏感查找。若 email 屬其他 sub 回 409；否則綁定或建立 `account=email`、`name` 截成 30 字元、`quota=0.1`、`is_active=True`、`is_superuser=False`。提交時捕捉 `IntegrityError`、rollback、重讀同一 sub/email；只在關聯與本次 sub 一致時回傳，否則 409。已停用 user 保持停用且回 403。
- [ ] **Step 5: 再跑全部 linking 測試。** `cd server && python -m pytest tests/test_sso_linking.py -q`；加入兩個 session 同時建同一 sub 的測試，確定資料庫唯一鍵只留一筆。
- [ ] **Step 6: 只 stage linking 模組與測試並提交** `feat(server): link verified SSO identity to local users`。

### Task 4: SSO FastAPI dependencies

**Files:**
- Create: `server/app/user/auth.py`
- Test: `server/tests/test_sso_auth.py`

**Interfaces:**
- Consumes: `app.package.coseeing_auth.AuthConfig`、`OidcProtocol`、`TokenVerifier`、Task 3 `resolve_local_user`、`get_db`。
- Produces: `get_bearer_token`、`get_verified_sub`、`get_optional_user`、`require_user`、`require_superuser`。

- [ ] **Step 1: 寫小型 FastAPI app 測試 dependencies。** 讓 `get_token_verifier` dependency 可覆寫為 fake verifier；加 `/optional` 與 `/admin` 測試路由。測試無 header 為 guest、格式錯誤及 token 失敗為 401、有效 token 每次呼叫 verifier、一般 user 訪問 admin 為 403。

```python
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from app.user.auth import get_optional_user, require_superuser

test_app = FastAPI()

@test_app.get("/optional")
def optional(user=Depends(get_optional_user)):
    return {"guest": user is None}

@test_app.get("/admin")
def admin(user=Depends(require_superuser)):
    return {"id": user.id}

def test_guest_is_optional():
    assert TestClient(test_app).get("/optional").json() == {"guest": True}


def test_malformed_bearer_is_not_guest():
    response = TestClient(test_app).get("/optional", headers={"Authorization": "Basic abc"})
    assert response.status_code == 401
```

- [ ] **Step 2: 執行 `cd server && python -m pytest tests/test_sso_auth.py -q`，確認缺少 auth 模組。**
- [ ] **Step 3: 實作依賴。** `get_bearer_token` 使用可選 `Authorization` header，header 存在但格式錯誤回 401；`get_token_verifier` 懶建立 process 內單例，設定 `AuthConfig(issuer=os.getenv("SSO_ISSUER", "https://sso.coseeing.org"), client_id=os.getenv("SSO_CLIENT_ID", "wordbridge"), scopes=("openid",), login_redirect_uri="http://127.0.0.1:8000/auth/callback", logout_redirect_uri=None)`，傳入 `TokenVerifier(config, OidcProtocol(config).discovery)`；`get_verified_sub` 對每個有 token 的請求呼叫 `verify_access_token(token).subject`。`ScopeError`／`TokenValidationError` 回 401；discovery 本身連線失敗回 503，驗證器 introspection fallback 保持原樣。`get_optional_user` 在缺 token 時回 `None`，其餘呼叫 `resolve_local_user(db, sub, token)`；`require_user` 與 `require_superuser` 實作 401／403。
- [ ] **Step 4: 再跑依賴測試。** `cd server && python -m pytest tests/test_sso_auth.py -q`；加入 UserInfo 只在首次／未驗證時被呼叫、有效 token 仍每次被驗證的測試。
- [ ] **Step 5: 只 stage auth 模組與測試並提交** `feat(server): authorize requests with SSO dependencies`。

### Task 5: `/proofreader` 本地執行與訪客額度

**Files:**
- Modify: `server/app/main.py`
- Test: `server/tests/test_proofreader_api.py`

**Interfaces:**
- Consumes: Task 2 `load_correction_settings`、`resolve_model`；Task 4 `get_optional_user`；`run_typo_correction`、`strings_diff`、`Interaction`、`get_db`。
- Produces: `POST /proofreader`，回傳 `request`、`response`、`diff`、`interaction_id`、`cost`。

- [ ] **Step 1: 寫失敗 API 測試。** 測試 app import、訪客請求回 200 並寫 interaction、default 與明確模型、無效 mode 422、停用模型 404、缺 API key 5xx、provider 失敗不寫 interaction。用 `app.dependency_overrides[get_db]` 指向 SQLite `StaticPool` session，`get_optional_user` 覆寫為 `None`；monkeypatch `run_typo_correction` 回傳 `SimpleNamespace(corrected_text="已校正", cost=Decimal("0.000001"))`。測試不連 SSO 或模型服務。

```python
payload = {
    "request": "以經完成",
    "corrector_config_id": "default",
    "language": "zh_traditional",
    "typo_correction_mode": "standard",
    "customized_words": [],
}
response = client.post("/proofreader", json=payload)
assert response.status_code == 200
assert response.json()["response"] == "已校正"
assert isinstance(response.json()["diff"], list)
```

- [ ] **Step 2: 執行 `cd server && python -m pytest tests/test_proofreader_api.py -q`，確認 `app.main` 目前的 import 失敗。**
- [ ] **Step 3: 清理 `main.py` 的失效 import 與 add-on 殘留。** 移除 `configManager`、`settings_repository`、`self`、`DEBUG_MODE`、`_diff_`、`y` 等；server 初始化 Task 2 settings。建立 Pydantic request schema，`request` 非空、`language` 限兩種、mode 依 task JSON、`customized_words` 限字串陣列。`corrector_config_id` 必填。
- [ ] **Step 4: 實作額度與模型執行。** 使用 `Decimal("0.06")`、`Decimal("0.3")`、UTC 24 小時成本查詢；訪客長度大於 128 及達上限回 429，user 達 quota 回 429，superuser 跳過 quota。解析模型後讀 `<PROVIDER>_API_KEY`，取得 catalog provider/price 與 task template，呼叫 `run_typo_correction` 時 `batch_mode=True`、`retries=2`、`backoff=1`，傳入 payload `customized_words`。捕捉 provider 例外並回不洩漏憑證的 5xx。
- [ ] **Step 5: 寫入 `Interaction` 並回應。** `request_time` 在 provider 前、`response_time` 在 provider 後；`cost` 用 Decimal，`model` 寫實際 `model_entry.corrector_config_id`，`user` 可空，category/version 沿既有值。先 `strings_diff(text, result.corrected_text)`，再 `db.add/commit/refresh`；資料庫錯誤 rollback。`cost` 經 `decimal_to_str_0()` 輸出。
- [ ] **Step 6: 加入額度邊界測試並執行。** 在 DB 預植 24 小時內訪客成本 `0.06`（同 IP）及 `0.3`（不同 IP 全站），確認兩條路各回 429；測試 129 字拒絕、128 字可通過，user quota 與 superuser 豁免。跑 `cd server && python -m pytest tests/test_proofreader_api.py -q`。
- [ ] **Step 7: 只 stage `main.py` 與此測試並提交** `feat(server): execute proofreader workflow and enforce quotas`。

### Task 6: 回饋、管理路由與舊入口清理

**Files:**
- Modify: `server/app/main.py`
- Modify: `server/app/user/routers.py`
- Modify: `server/app/imp.py`
- Modify: `server/test/proofreader.py`
- Modify: `server/test/crud.py`
- Delete: `server/test/register.py`
- Test: `server/tests/test_route_permissions.py`

**Interfaces:**
- Consumes: Task 4 `get_optional_user`、`require_superuser`；Task 5 的 FastAPI app 與 Interaction model。
- Produces: 訪客/登入者 `POST /feedback`、僅 superuser 的兩組 CRUD、無 `/login`/`/register`。

- [ ] **Step 1: 寫失敗的路由權限測試。** `GET /users/get_paginated`、`GET /interactions/get_paginated` 在訪客為 401、一般 user 403、superuser 可通過；`POST /login`、`POST /register` 為 404；訪客 feedback 用既有 interaction ID 可寫入／覆寫且 `review_user_id is None`，未知 ID 404，有效登入者回饋記錄 user ID。

```python
response = client.post("/feedback", json={"interaction_id": interaction.id, "review_content": "已確認"})
assert response.status_code == 200
db.refresh(interaction)
assert interaction.review_user_id is None
assert interaction.review_content == "已確認"
response = client.post("/feedback", json={"interaction_id": interaction.id, "review_content": "修正回饋"})
assert response.status_code == 200
db.refresh(interaction)
assert interaction.review_content == "修正回饋"
```

- [ ] **Step 2: 執行 `cd server && python -m pytest tests/test_route_permissions.py -q`，確認舊權限與 feedback 行為失敗。**
- [ ] **Step 3: 改路由依賴。** `/feedback` 改用 `get_optional_user`，以 `interaction_id` 唯一查找、404 處理、設定 `review_content` 與 `review_user_id=(user.id if user else None)`，刪除死碼。`/users` 與 `/interactions` router 都掛 `Depends(require_superuser)`。`server/app/user/routers.py` 刪除 `/login`、`/register`、HS256 secret、密碼檢查與舊 auth dependencies；`main.py` 移除舊 user router 的 `include_router`。不要保留任何舊 token 可通過的入口。
- [ ] **Step 4: 清理資料與手動腳本。** `server/app/imp.py` 不再傳 password；`server/test/proofreader.py` 改成從環境變數讀 SSO access token、送 `corrector_config_id`／`typo_correction_mode`／`customized_words`，允許不給 token 的訪客呼叫。`server/test/crud.py` 改成以環境變數 SSO token 操作 admin CRUD，移除密碼／舊 login 邏輯；刪掉只呼叫 `/register` 的腳本。腳本不得內建 token 或帳密。
- [ ] **Step 5: 跑路由與全部 server 自動測試。** `cd server && python -m pytest tests -q`；`python -c 'from app.main import app; print([route.path for route in app.routes])'`，確認可 import 且 `/login`、`/register` 不在路由表。
- [ ] **Step 6: 只 stage 本任務檔案並提交** `feat(server): secure CRUD and accept guest feedback`。

## 完工驗證與交付

按順序執行 `cd server && python -m pip install -r requirements.txt`、`python -m pytest tests -q`、`python -m compileall -q app`、`python -c 'from app.main import app; print(app.title)'`。在一次性 MySQL 測試庫執行 Alembic upgrade，檢查原有 user 保留、`password` 欄位消失、`sso_sub` 唯一限制及 `email_verified=false` 回填；不要對正式資料庫直接試跑。檢查 `git diff --check` 和 `git status`，確認只納入預期檔案。

若部署環境能提供真實 SSO token、UserInfo 服務與 provider API key，再執行一次真實整合校正；若無，明確回報此部分尚未驗證。本計畫的自動測試均使用假的 SSO 與 provider 回應，不需額外外部費用。
