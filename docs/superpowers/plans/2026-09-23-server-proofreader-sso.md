# Server Proofreader and SSO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the server run the add-on's local proofreading workflow with a configurable model and link SSO access tokens to local users, while retaining guest limits, feedback, and admin permissions.

**Architecture:** Correction configuration and model resolution are separate from the FastAPI routes. SSO token verification, UserInfo requests, and local-user linking are layered as dependencies. The routes handle only payloads, quotas, workflow execution, interaction records, and HTTP responses. The database migration removes `User.password` outright.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, MySQL, Pydantic 2, pytest, the existing `app.package.coseeing_auth`, and the current catalog/typo workflow.

**Spec:** `docs/superpowers/specs/2026-09-23-server-proofreader-sso-design.md`

## Global Constraints

- Migrate only the add-on's `execution_channel == LOCAL_CHANNEL` logic; retain the `/proofreader` request and response fields defined in the spec.
- `SSO_ISSUER` defaults to `https://sso.coseeing.org`; `SSO_CLIENT_ID` defaults to `wordbridge`; `SSO_USERINFO_URL` defaults to `https://sso.coseeing.org/userinfo`.
- `DEFAULT_CORRECTOR_CONFIG_ID` defaults to `deepseek-v4-flash&DeepSeek` and can be overridden at deployment; allow only enabled, runnable local catalog models.
- Call the existing `TokenVerifier.verify_access_token()` for every request with a token. Local `email_verified=True` skips only UserInfo.
- Initial linking requires the UserInfo `sub` to equal the verified token subject, a nonempty email, and `email_verified is True`. Remove `User.password` from the model, schema, and database.
- Guest limits: 128 text characters, 0.06 cost per IP over 24 hours, and 0.3 cost across all guests over 24 hours. Compare ordinary users against their local quotas; superusers are exempt.
- `/users` and `/interactions` CRUD require `is_superuser=True`. Guest feedback is linked only by `interaction_id`, with `review_user_id=NULL`.
- Use the `server/app/package/coseeing_auth` source; install third-party packages with pip. Implementation tasks must not change the add-on, the SSO system, or the verifier's internal strategy.
- `server/` is currently existing, untracked work in git. Preserve all its contents while executing. Stage only files listed for each task, check `git status` first, and do not stage the entire `server/` directory.

## Review Focus

Each of these five cases has a test in the corresponding task; review them closely:

1. A present `Authorization` header with malformed Bearer syntax or a failed verification must yield 401, never guest access. (Task 4)
2. An email already linked to another `sso_sub` must yield 409 without changing the original link. (Task 3)
3. Catalog `get_model()` returns disabled models; neither a disabled Coseeing offer nor a disabled local model may execute. (Tasks 2 and 5)
4. Guest cost comparisons use Decimal. At 0.06 per IP or 0.3 globally, reject the request even without a token. (Task 5)
5. Guest feedback must not write a nonexistent user ID. A later submission for the same `interaction_id` may overwrite its feedback. (Task 6)

## Files and responsibilities

| File | Responsibility |
| --- | --- |
| `server/app/user/models.py`, `server/app/user/schemas.py` | Local-user fields and CRUD payload; remove password. |
| `server/alembic/versions/20260923_sso_user.py` | Migration for SSO fields, account length, and password removal. |
| `server/app/correction_config.py` | Read catalog/task settings, validate the deployment default, resolve requested models. |
| `server/app/user/linking.py` | Validate email through UserInfo; find, link, or create local users atomically. |
| `server/app/user/auth.py` | Bearer extraction, TokenVerifier, and optional/required/superuser dependencies. |
| `server/app/main.py` | Correction, feedback, CRUD routers, and initialization. |
| `server/app/lib/text/chinese.py`, `server/app/lib/tasks/typo/{utils,prompt,text_policy}.py`, `server/requirements.txt` | Let the server workflow import dependencies installed with pip. |
| `server/app/imp.py`, `server/test/*.py` | Remove password login and obsolete manual calls. |
| `server/tests/*.py` | Automated checks without external SSO or model charges. |

---

### Task 1: User model and database migration

**Files:**
- Modify: `server/app/user/models.py`
- Modify: `server/app/user/schemas.py`
- Create: `server/alembic/versions/20260923_sso_user.py`
- Test: `server/tests/test_user_storage.py`
- Create: `server/tests/conftest.py`

**Interfaces:**
- Consumes: the existing `app.baseModel.Base`, the unique `User.account` key, and Alembic revision `dad5039f4770`.
- Produces: `User.sso_sub: str | None`, `User.email_verified: bool`, no `User.password`, and a 254-character maximum for `User.account`.

- [ ] **Step 1: Create a shared SQLite session fixture and write a failing schema test.** `server/tests/conftest.py` creates a separate in-memory database per test for reuse by later tasks:

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

Check columns in `server/tests/test_user_storage.py`:

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

- [ ] **Step 2: Run `cd server && python -m pytest tests/test_user_storage.py -q` and confirm the new-field assertion fails.**
- [ ] **Step 3: Modify the ORM model and schema.** Add `sso_sub = mapped_column(String(255), unique=True, nullable=True, default=None)` and `email_verified = mapped_column(Boolean, default=False, nullable=False)` to `User`. Set `account` to `String(254)`, remove password completely, and order dataclass fields with defaults correctly. Let the CRUD schema contain only fields admins may maintain, such as `account`, `name`, `is_active`, `is_superuser`, and `quota`; it must neither accept nor return password.
- [ ] **Step 4: Write the Alembic revision.** In `upgrade()`, add nullable `sso_sub` and non-nullable `email_verified` backfilled to false, widen `account`, add a unique index on `sso_sub`, and finally call `drop_column("user", "password")`. In `downgrade()`, remove the SSO fields, restore the old length, and add a nullable password column to show that original passwords cannot be recovered. Specify existing types and nullability in MySQL `alter_column` calls. Do not run this migration automatically against production.
- [ ] **Step 5: Rerun the test and check migration syntax.** Run `cd server && python -m pytest tests/test_user_storage.py -q` and `python -m compileall -q app/user alembic/versions/20260923_sso_user.py`. Also run an Alembic upgrade when a test database is available; run the production migration only through deployment.
- [ ] **Step 6: Stage only these five files and commit** `feat(server): add SSO user fields and remove passwords`.

### Task 2: Server correction settings and pip imports

**Files:**
- Create: `server/app/correction_config.py`
- Modify: `server/app/lib/text/chinese.py`
- Modify: `server/app/lib/tasks/typo/utils.py`
- Modify: `server/app/lib/tasks/typo/prompt.py`
- Modify: `server/app/lib/tasks/typo/text_policy.py`
- Modify: `server/requirements.txt`
- Test: `server/tests/test_correction_config.py`

**Interfaces:**
- Consumes: `BundledCatalogSource`, `load_catalog`, `SUPPORTED_PROVIDERS`, and `setting/task/corrector.json`.
- Produces: `load_correction_settings() -> CorrectionSettings` and `resolve_model(settings, requested_id: str) -> ModelEntry`.

- [ ] **Step 1: Write failing configuration tests.** Use the actual bundled catalog to test the default, an explicit model, and disabled entries:

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

- [ ] **Step 2: Run `cd server && python -m pytest tests/test_correction_config.py -q` and confirm the missing module or functions cause a failure.**
- [ ] **Step 3: Implement configuration loading and model resolution.** Use a frozen `CorrectionSettings` dataclass to hold the catalog, `template_name` and `optional_guidance_enable` dictionaries, and `default_id`. `load_correction_settings()` reads settings relative to `__file__` and from the environment, parses JSON, and validates the configured default. For an ID other than `default`, `resolve_model()` first requires an active `catalog.get_coseeing(id)` offer, then an active matching local `catalog.get_model(id)` entry and a provider. For `default`, require the configured local entry to be active. Raise `LookupError` if a requested model is unavailable and `ValueError` if the deployment default is invalid.

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

- [ ] **Step 4: Replace `_wb_vendor` imports in the correction import graph with pip package imports.** Import `hanzidentifier`, `pypinyin`, and `chinese_converter` normally. Add `Authlib`, `PyJWT[crypto]`, `hanzidentifier`, `pypinyin`, and `chinese-converter` to `requirements.txt`, retaining `requests`; pin compatible versions after resolving installation. Do not list `coseeing_auth` in requirements. The Dockerfile already installs the added dependencies through `pip install -r requirements.txt`.
- [ ] **Step 5: Rerun configuration tests and check imports.** Run `cd server && python -m pytest tests/test_correction_config.py -q`, then `python -c 'from app.lib.application.task_runner import run_typo_correction; from app.correction_config import load_correction_settings; print(load_correction_settings().default_id)'`. NVDA and `_wb_vendor` must not be needed.
- [ ] **Step 6: Stage only this task's files and commit** `feat(server): load runnable correction models`.

### Task 3: UserInfo verification and local-user linking

**Files:**
- Create: `server/app/user/linking.py`
- Test: `server/tests/test_sso_linking.py`

**Interfaces:**
- Consumes: `User.sso_sub` and `User.email_verified` from Task 1; a verified `sub`, the original access token, and a SQLAlchemy `Session`.
- Produces: `resolve_local_user(db: Session, sub: str, token: str) -> User`; raises `HTTPException` with 403, 409, or 503.

- [ ] **Step 1: Write failing tests.** Reuse the `db` fixture from Task 1 and monkeypatch the UserInfo HTTP call. Cover linking an existing email, creating a new user, the locally verified fast path, a mismatched `sub`, `email_verified=1`, and the same email linked to another `sub`. Core examples:

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

- [ ] **Step 2: Run `cd server && python -m pytest tests/test_sso_linking.py -q` and confirm the linking module is missing.**
- [ ] **Step 3: Implement `fetch_userinfo(token: str) -> dict`.** Call SSO through `requests.get(SSO_USERINFO_URL, headers={"Authorization": f"Bearer {token}"}, timeout=6)`. Map HTTP errors, timeouts, and non-object JSON to 503. Do not log the token or raw response. Map a mismatched `sub`, blank email, or `email_verified is not True` to 403.
- [ ] **Step 4: Implement `resolve_local_user`.** First look for `User.sso_sub == sub`; use the fast path when `email_verified=True`. Otherwise query UserInfo, update the verification flag for an existing subject, or perform a database case-insensitive lookup of `User.account` by the verified email. Return 409 if the email belongs to another subject; otherwise link or create a user with `account=email`, `name` truncated to 30 characters, `quota=0.1`, `is_active=True`, and `is_superuser=False`. On commit, catch `IntegrityError`, roll back, and reread by subject/email. Return the user only when the resulting link matches this subject; otherwise return 409. Preserve an inactive user's inactive status and return 403.
- [ ] **Step 5: Rerun all linking tests.** Run `cd server && python -m pytest tests/test_sso_linking.py -q`. Add a test with two sessions creating the same subject concurrently; verify that the database unique key leaves one user.
- [ ] **Step 6: Stage only the linking module and tests, then commit** `feat(server): link verified SSO identity to local users`.

### Task 4: SSO FastAPI dependencies

**Files:**
- Create: `server/app/user/auth.py`
- Test: `server/tests/test_sso_auth.py`

**Interfaces:**
- Consumes: `app.package.coseeing_auth.AuthConfig`, `OidcProtocol`, `TokenVerifier`, Task 3 `resolve_local_user`, and `get_db`.
- Produces: `get_bearer_token`, `get_verified_sub`, `get_optional_user`, `require_user`, and `require_superuser`.

- [ ] **Step 1: Test the dependencies with a small FastAPI app.** Make the `get_token_verifier` dependency overridable with a fake verifier. Add `/optional` and `/admin` test routes. Test that no header is a guest, malformed syntax and verification failures produce 401, a valid token invokes the verifier on every request, and an ordinary user gets 403 from the admin route.

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

- [ ] **Step 2: Run `cd server && python -m pytest tests/test_sso_auth.py -q` and confirm the auth module is missing.**
- [ ] **Step 3: Implement the dependencies.** `get_bearer_token` accepts an optional `Authorization` header and returns 401 when a present header is malformed. `get_token_verifier` lazily creates a process-wide singleton using `AuthConfig(issuer=os.getenv("SSO_ISSUER", "https://sso.coseeing.org"), client_id=os.getenv("SSO_CLIENT_ID", "wordbridge"), scopes=("openid",), login_redirect_uri="http://127.0.0.1:8000/auth/callback", logout_redirect_uri=None)` and `TokenVerifier(config, OidcProtocol(config).discovery)`. For each request with a token, `get_verified_sub` calls `verify_access_token(token).subject`. Map `ScopeError` and `TokenValidationError` to 401; map discovery connection failure to 503, retaining the verifier's existing introspection fallback. `get_optional_user` returns `None` for a missing token and otherwise calls `resolve_local_user(db, sub, token)`. Implement 401/403 behavior in `require_user` and `require_superuser`.
- [ ] **Step 4: Rerun dependency tests.** Run `cd server && python -m pytest tests/test_sso_auth.py -q`. Add tests showing that UserInfo is called only on first use or while locally unverified, while valid tokens are still verified on every request.
- [ ] **Step 5: Stage only the auth module and tests, then commit** `feat(server): authorize requests with SSO dependencies`.

### Task 5: Local `/proofreader` execution and guest quotas

**Files:**
- Modify: `server/app/main.py`
- Test: `server/tests/test_proofreader_api.py`

**Interfaces:**
- Consumes: Task 2 `load_correction_settings` and `resolve_model`; Task 4 `get_optional_user`; `run_typo_correction`, `strings_diff`, `Interaction`, and `get_db`.
- Produces: `POST /proofreader` returning `request`, `response`, `diff`, `interaction_id`, and `cost`.

- [ ] **Step 1: Write failing API tests.** Test that the app imports, a guest gets 200 and an interaction is stored, default and explicit models work, an invalid mode returns 422, a disabled model returns 404, a missing API key produces 5xx, and provider failure writes no interaction. Point `app.dependency_overrides[get_db]` to a SQLite `StaticPool` session and override `get_optional_user` with `None`. Monkeypatch `run_typo_correction` to return a `SimpleNamespace` whose `corrected_text` matches the test assertion below and whose `cost` is `Decimal("0.000001")`. Tests must call neither SSO nor the model provider.

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

- [ ] **Step 2: Run `cd server && python -m pytest tests/test_proofreader_api.py -q` and confirm that `app.main` currently fails to import.**
- [ ] **Step 3: Remove broken imports and add-on remnants from `main.py`.** Remove `configManager`, `settings_repository`, `self`, `DEBUG_MODE`, `_diff_`, `y`, and similar references. Initialize the settings from Task 2 in the server. Create a Pydantic request schema requiring nonempty `request` and `corrector_config_id`, limiting `language` to the two supported values, validating mode against the task JSON, and accepting only an array of strings for `customized_words`.
- [ ] **Step 4: Implement quotas and model execution.** Use `Decimal("0.06")` and `Decimal("0.3")` and query costs over the past 24 hours in UTC. Return 429 when guest text exceeds 128 characters or a guest/user reaches the applicable quota; skip the user quota for superusers. Resolve the model and read `<PROVIDER>_API_KEY`. Obtain the catalog provider, pricing, and task template. Call `run_typo_correction` with `batch_mode=True`, `retries=2`, `backoff=1`, and the payload's `customized_words`. Catch provider failures and return a 5xx that reveals no credentials.
- [ ] **Step 5: Save `Interaction` and respond.** Record `request_time` before the provider call and `response_time` after it. Use Decimal for `cost`, store the actual `model_entry.corrector_config_id` in `model`, allow a null user, and keep the existing category/version values. Call `strings_diff(text, result.corrected_text)` before `db.add/commit/refresh`. Roll back on database errors. Format the returned cost with `decimal_to_str_0()`.
- [ ] **Step 6: Add and run quota-boundary tests.** Seed the database with guest costs of `0.06` within 24 hours for the same IP and `0.3` across different IPs. Check that each limit independently returns 429. Test that 129 characters are rejected, 128 are accepted, ordinary users have a quota, and superusers are exempt. Run `cd server && python -m pytest tests/test_proofreader_api.py -q`.
- [ ] **Step 7: Stage only `main.py` and this test, then commit** `feat(server): execute proofreader workflow and enforce quotas`.

### Task 6: Feedback, admin routes, and removal of old entry points

**Files:**
- Modify: `server/app/main.py`
- Modify: `server/app/user/routers.py`
- Modify: `server/app/imp.py`
- Modify: `server/test/proofreader.py`
- Modify: `server/test/crud.py`
- Delete: `server/test/register.py`
- Test: `server/tests/test_route_permissions.py`

**Interfaces:**
- Consumes: Task 4 `get_optional_user` and `require_superuser`; the FastAPI app and Interaction model from Task 5.
- Produces: guest/authenticated `POST /feedback`, two superuser-only CRUD groups, and no `/login` or `/register`.

- [ ] **Step 1: Write failing route-permission tests.** `GET /users/get_paginated` and `GET /interactions/get_paginated` return 401 for guests and 403 for ordinary users, but allow superusers. `POST /login` and `POST /register` return 404. A guest can write and overwrite feedback for an existing interaction ID with `review_user_id is None`; an unknown ID returns 404. Authenticated feedback records the user ID.

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

- [ ] **Step 2: Run `cd server && python -m pytest tests/test_route_permissions.py -q` and confirm the old permissions and feedback behavior fail.**
- [ ] **Step 3: Change route dependencies.** Make `/feedback` use `get_optional_user`, look up by `interaction_id`, return 404 when missing, set `review_content` and `review_user_id=(user.id if user else None)`, and remove dead code. Attach `Depends(require_superuser)` to both `/users` and `/interactions` routers. Remove `/login`, `/register`, the HS256 secret, password checks, and old auth dependencies from `server/app/user/routers.py`. Remove the old user router's `include_router` from `main.py`. Do not retain any entry point that accepts the old token.
- [ ] **Step 4: Clean up seed data and manual scripts.** Stop passing password in `server/app/imp.py`. Read an SSO access token from an environment variable in `server/test/proofreader.py`, send `corrector_config_id`, `typo_correction_mode`, and `customized_words`, and allow guest calls without a token. Use an environment-provided SSO token for admin CRUD in `server/test/crud.py` and remove its password and old-login logic. Delete the script that only calls `/register`. No script should embed credentials or tokens.
- [ ] **Step 5: Run route and full server tests.** Run `cd server && python -m pytest tests -q`, then `python -c 'from app.main import app; print([route.path for route in app.routes])'`. Confirm the app imports and the route table excludes `/login` and `/register`.
- [ ] **Step 6: Stage only this task's files and commit** `feat(server): secure CRUD and accept guest feedback`.

## Final verification and delivery

Run, in order, `cd server && python -m pip install -r requirements.txt`, `python -m pytest tests -q`, `python -m compileall -q app`, and `python -c 'from app.main import app; print(app.title)'`. Run the Alembic upgrade against a disposable MySQL test database. Check that existing users remain, the `password` column is gone, `sso_sub` is unique, and `email_verified=false` was backfilled. Do not trial the migration against the production database. Check `git diff --check` and `git status` to ensure only intended files are included.

If the deployment environment provides a real SSO token, UserInfo service, and provider API key, also run one real integration correction. Otherwise, explicitly report that this part remains unverified. Automated tests in this plan use simulated SSO and provider responses, so they incur no external model charges.
