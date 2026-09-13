# Coseeing SSO Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 WordBridge 使用附帶的 `coseeing_auth` 取得 Coseeing access token，保留登入／訪客選擇，並接入啟動、設定儲存、校對與回饋。

**Architecture:** 用 `lib/coseeing_auth.py` 統一管理 Future 驗證流程、refresh token 與訪客狀態。套件 `FutureAuthClient` 負責背景 OIDC 操作；整合層用 callback 串接結果，wx 主執行緒負責狀態、設定及 UI。現有校對與回饋程式僅透過共用入口取得 token 與產生 header。

**Tech Stack:** Python、NVDA、wxPython、concurrent.futures、coseeing_auth、requests、pytest、SCons。

**Spec:** [2026-09-13-coseeing-auth-integration-design.md](../specs/2026-09-13-coseeing-auth-integration-design.md)。使用者已於本次對話確認 spec；執行者須先讀 spec 與本計畫。

## Global Constraints

- Issuer：`https://sso.coseeing.org`。
- Client ID：`a11yvillage`。
- Scopes：`openid profile email offline_access`。
- 登入 callback：`http://127.0.0.1:8765/auth-callback`。
- 登出 callback：`http://127.0.0.1:8765/logout-callback`。
- Callback timeout：180 秒。
- 公開入口回傳 `Future[str | None]`；`None` 只代表使用者明確選擇訪客。
- Refresh token 保存在 `config.conf["WordBridge"]["settings"]["api_key"]["Coseeing"]`；access token 僅在記憶體。
- 訪客請求完全省略 `Authorization`；已登入使用 access token，不使用 ID token。
- 僅 `execution_channel == "Coseeing"` 的啟動／儲存設定會重設訪客選擇；一般 API 請求尊重訪客狀態。
- wx 主執行緒不得等待未完成 Future 或進行 HTTP 請求。
- 不在 `FutureAuthClient` 的單 worker callback 內等待新提交的 Future。
- Refresh token 明確遭拒才清除保存值；網路失敗不清除、不自動改成訪客。
- 不修改舊版參考目錄、不移植 OIDCManager、不新增註冊／綁定／登出 UI／登入快捷鍵、不修改伺服器或增加 401 重送。
- 不记录 token、authorization code、完整登入 URL 或含敏感資料的例外內容。
- 保留使用者未提交的 `WordBridge(include-auth)/` 與 `package/coseeing_auth/` 內容；不可用批次覆蓋方式重裝整個 package 目錄。

## 檔案與責任

| 檔案 | 動作與責任 |
| --- | --- |
| `addon/globalPlugins/WordBridge/lib/coseeing_auth.py` | 新增：設定、可測試的驗證協調器、NVDA adapter、共用入口與關閉 |
| `addon/globalPlugins/WordBridge/lib/coseeing.py` | 修改：以純函式建立 Bearer header；移除已無呼叫者的舊登入函式 |
| `addon/globalPlugins/WordBridge/__init__.py` | 修改：啟動／關閉、校對驗證、背景回饋 |
| `addon/globalPlugins/WordBridge/dialogs.py` | 修改：Coseeing 說明、儲存觸發；實際選擇對話框由整合層建立 |
| `addon/globalPlugins/WordBridge/configManager.py` | 移除不再使用的 `save_coseeing_credentials`，保留既有 selection normalization |
| `requirements-coseeing-auth.txt` | 新增：套件公開依賴限制，用於依賴準備與測試 |
| `addon/globalPlugins/WordBridge/package/` | 補齊經目標 Windows 驗證的依賴、版本 metadata 與授權文件 |
| `tests/coseeing_auth_helpers.py` | 新增：可控制完成時機的假 auth client 與 UI 佇列 |
| `tests/test_coseeing_auth.py` | 新增：token、訪客、錯誤、重疊呼叫與關閉測試 |
| `tests/test_coseeing_auth_nvda.py` | 新增：NVDA 設定、UI、啟動／儲存掛鉤測試 |
| `tests/test_coseeing_requests.py` | 新增：校對／回饋請求與 header 測試 |
| `tests/test_coseeing_auth_bundle.py` | 新增：套件來源、依賴與 Windows 匯入檢查 |

以上新測試不呼叫真實 SSO。既有 `tests/conftest.py` 已將 addon 與 package 加入 `sys.path`；核心可用 `from lib.coseeing_auth import ...` 匯入，勿為單元測試執行整個 NVDA plugin 初始化。

## 執行前檢查

- [ ] 讀取執行時適用的 `AGENTS.md`、spec 與本計畫，依執行 skill 決定隔離方式；工作樹若不含未追蹤的使用者套件，要保留來源並將必要檔案帶入，不能假設 git worktree 會帶入未追蹤內容。
- [ ] 執行 `git status --short`，記錄原有變更；後續每次 commit 只指定本任務檔案。
- [ ] 執行 `python -m pytest tests/test_corrector_task_config.py tests/test_corrector_catalog_unittest.py tests/test_task_architecture_unittest.py -q` 記錄基線。缺少測試依賴時先記錄原因，使用隔離 Python 環境補齊，不把環境錯誤視為產品回歸。

## Task 1：可部署的驗證套件與設定

**Files:** 新增 `requirements-coseeing-auth.txt`、`tests/test_coseeing_auth_bundle.py`；新增整合層的 `build_auth_config`；補齊 addon `package/` 的依賴。

**Interfaces:** Consumes：附帶套件的 `AuthConfig`。Produces：`build_auth_config() -> AuthConfig`，後續 coordinator 的預設 client factory 使用它。

- [ ] **Step 1：先加入設定契約測試。**

```python
def test_sso_configuration_matches_approved_demo():
    from lib.coseeing_auth import build_auth_config
    value = build_auth_config()
    assert value.issuer == "https://sso.coseeing.org"
    assert value.client_id == "a11yvillage"
    assert set(value.scopes) == {"openid", "profile", "email", "offline_access"}
    assert value.login_redirect_uri == "http://127.0.0.1:8765/auth-callback"
    assert value.logout_redirect_uri == "http://127.0.0.1:8765/logout-callback"
    assert value.callback_timeout == 180
```

- [ ] **Step 2：執行 `python -m pytest tests/test_coseeing_auth_bundle.py -q`。** 預期因新整合層尚不存在失敗；若先因 Authlib 等缺少而失敗，將它列入本 task 的依賴檢查。
- [ ] **Step 3：建立設定函式及公開依賴清單。**

```python
def build_auth_config():
    from coseeing_auth import AuthConfig
    return AuthConfig(
        issuer="https://sso.coseeing.org",
        client_id="a11yvillage",
        scopes=("openid", "profile", "email", "offline_access"),
        login_redirect_uri="http://127.0.0.1:8765/auth-callback",
        logout_redirect_uri="http://127.0.0.1:8765/logout-callback",
        callback_timeout=180,
    )
```

`requirements-coseeing-auth.txt` 使用來源套件 `pyproject.toml` 的實際限制：

```text
Authlib>=1.6.2,<2
requests>=2.32.5,<3
PyJWT[crypto]>=2.10.1,<3
```

- [ ] **Step 4：驗證部署依賴，不能以 Linux 開發環境匯入成功代替。** 先檢查 `buildVars.py` 宣告的 NVDA 2024.1 至 2026.1.1 支援範圍，從對應 NVDA 原始碼／執行環境取得 Python 版本與 Windows 架構，再選擇相容 wheel。記錄選定版本與 wheel 檔名於 `package/coseeing-auth-dependencies.md`，包含 Authlib、requests、PyJWT 與傳遞依賴。用暫存目錄準備依賴，僅補入缺少檔案；不能將 Linux `.so` 放入 Windows addon。若支援範圍需要不同二進位版本，先檢查 NVDA 已提供的相容模組並驗證；無法滿足時回報具體套件／ABI 差異，不自行提高最低 NVDA 版本。

Windows 目標環境的匯入檢查程式放在 bundle 測試中，以全新 process 執行：

```python
import sys
from pathlib import Path

bundle = Path("addon/globalPlugins/WordBridge/package").resolve()
sys.path.insert(0, str(bundle))
import coseeing_auth
from authlib.integrations.requests_client import OAuth2Session
from jwt.algorithms import RSAAlgorithm
import requests

assert Path(coseeing_auth.__file__).resolve().is_relative_to(bundle)
assert callable(OAuth2Session)
assert callable(RSAAlgorithm)
assert callable(requests.Session)
```

該 process 的第三方來源只允許 addon package 或已記錄且受支援 NVDA 隨附的路徑；禁止靠開發機全域 site-packages 掩蓋漏包。保存版本 metadata 與授權；既有翻譯 `pythonSources` 已涵蓋新 `lib/*.py`，不需為此改動它。

- [ ] **Step 5：重跑 bundle 設定測試；在可取得的 Windows 目標驗證匯入。** 無 Windows 時保留明確待驗收項目，不宣稱 addon 已可部署。
- [ ] **Step 6：審查精確 diff 並提交：** `git commit -m "build: prepare Coseeing auth dependencies and configuration"`。只加入新 requirements、測試、整合層與核對過的依賴檔案；使用者附帶套件若需納入交付，確認內容無改寫後一起納入。

## Task 2：驗證狀態機與 Future 串接

**Files:** `lib/coseeing_auth.py`、`tests/coseeing_auth_helpers.py`、`tests/test_coseeing_auth.py`。

**Interfaces:**

```python
# 均在 lib/coseeing_auth.py 定義；Callable 型別來自 collections.abc。
# client_factory() 回傳 FutureAuthClient 或具有同樣方法的測試替身。
# post_ui(callback, *args) 排程到主執行緒；read/save/prompt 都只在該執行緒執行。
class CoseeingAuthSession:
    def __init__(self, *, client_factory, post_ui, read_refresh_token,
                 save_refresh_token, prompt_login): ...
    def get_access_token(self, *, reconsider_guest=False) -> Future[str | None]: ...
    def close(self) -> Future[None]: ...

# prompt_login() 的結果："login"、"guest"、"cancel"。
# 此區是介面宣告；下列步驟描述各方法必須實作的流程。
```

- [ ] **Step 1：建立可控制排程的測試替身與首批測試。** 不用 sleep 控制執行順序。

```python
from collections import deque
from concurrent.futures import Future

class FakeAuth:
    def __init__(self):
        self.calls = []
        self.pending = deque()

    def _submit(self, name, *args, **kwargs):
        result = Future()
        self.calls.append((name, args, kwargs))
        self.pending.append(result)
        return result

    def restore(self, token):
        return self._submit("restore", token)

    def get_access_token(self, *, auto_login=False):
        return self._submit("get_access_token", auto_login=auto_login)

    def get_refresh_token(self):
        return self._submit("get_refresh_token")

    def login(self):
        return self._submit("login")

    def close(self):
        self.calls.append(("close", (), {}))

class AuthHarness:
    def __init__(self, session_class, refresh=None, choice="guest"):
        self.auth = FakeAuth()
        self.queue = deque()
        self.saved = refresh
        self.choice = choice
        self.prompts = 0
        self.session = session_class(
            client_factory=lambda: self.auth,
            post_ui=lambda fn, *args: self.queue.append((fn, args)),
            read_refresh_token=lambda: self.saved,
            save_refresh_token=self.save,
            prompt_login=self.prompt,
        )

    def save(self, value):
        self.saved = value

    def prompt(self):
        self.prompts += 1
        return self.choice

    def drain(self):
        while self.queue:
            fn, args = self.queue.popleft()
            fn(*args)

    def resolve(self, value):
        self.auth.pending.popleft().set_result(value)
        self.drain()

    def reject(self, error):
        self.auth.pending.popleft().set_exception(error)
        self.drain()
```

```python
from lib.coseeing_auth import CoseeingAuthSession
from coseeing_auth_helpers import AuthHarness

def test_guest_is_remembered_until_reconsidered():
    h = AuthHarness(CoseeingAuthSession)
    first = h.session.get_access_token()
    h.drain()
    assert first.result(timeout=1) is None
    second = h.session.get_access_token()
    h.drain()
    assert second.result(timeout=1) is None
    assert h.prompts == 1
    third = h.session.get_access_token(reconsider_guest=True)
    h.drain()
    assert third.result(timeout=1) is None
    assert h.prompts == 2
    assert h.auth.calls == []

def test_restore_persists_rotated_refresh_before_completing():
    h = AuthHarness(CoseeingAuthSession, refresh="old")
    result = h.session.get_access_token()
    h.drain()
    assert h.auth.calls[0] == ("restore", ("old",), {})
    h.resolve(object())
    h.resolve("access")
    assert not result.done()
    h.resolve("rotated")
    assert result.result(timeout=1) == "access"
    assert h.saved == "rotated"
    assert h.prompts == 0
```

- [ ] **Step 2：執行 `python -m pytest tests/test_coseeing_auth.py -q`，確認缺少協調器而失敗。**
- [ ] **Step 3：實作 coordinator。** `get_access_token` 建立呼叫者 Future，將處理排到 UI；UI 狀態包含 `_guest`、`_closed`、`_session_ready`、`_client`、`_waiters`、`_active`。重疊呼叫加入同一次工作的 waiters，各自取消 Future 不取消其他呼叫者。正在進行中的工作優先合併，不因 `reconsider_guest` 再開對話框。

每個套件 Future 的 callback 只把完成結果排回 UI；在 UI callback 中读取已完成 Future 的結果，再提交下一步，不等待下一步：

```python
def _watch(self, future, succeeded):
    def completed(done):
        self._post_ui(deliver, done)

    def deliver(done):
        if self._closed:
            return
        try:
            value = done.result()  # done 已完成，沒有阻塞。
        except Exception as error:
            self._fail(error)
        else:
            succeeded(value)

    future.add_done_callback(completed)
```

在同一 task 定義 `_fail(error)`：根據下方錯誤規則選擇詢問或完成例外；`_finish(value=None, error=None)`：先解除 active 狀態，再向所有尚未完成的 waiters 傳遞結果／例外。所有同步提交錯誤及 `save_refresh_token` 錯誤也必須进入 `_fail`，不能讓 waiters 懸置。

流程順序如下：

```text
closed -> 完成 ClientClosedError
active -> 合併 waiter
reconsider_guest -> 清除 guest
guest -> 完成 None
session_ready -> get_access_token(auto_login=False)
saved refresh -> restore -> session_ready=True -> get_access_token(auto_login=False)
otherwise -> prompt_login
prompt login -> login -> session_ready=True -> get_access_token(auto_login=False)
prompt guest -> guest=True -> 完成 None
prompt cancel -> 完成 CancelledError
token success -> get_refresh_token -> save_refresh_token -> 完成 access token
```

`client_factory` 採 lazy 建立，訪客不必先建立 auth client。`_fail` 僅對 `RestoreError` 或 `TokenUnavailableError` 且 `code == "refresh_rejected"` 清除保存值並令 `_session_ready=False`，再詢問；用新的明確登入覆蓋 session，不調用套件私有 state。當已登入 session 沒有 refresh token 且 access token 到期，套件回報 `TokenUnavailableError(code="refresh_unavailable")` 時也詢問。其他錯誤（包括 token 驗證失敗）直接完成例外。`ClientClosedError` 需從 `coseeing_auth.errors` 匯入（頂層未 re-export），`CancelledError` 從 `concurrent.futures` 匯入。

- [ ] **Step 4：補齊並執行錯誤與登入測試。**

```python
import pytest
from coseeing_auth import RestoreError

@pytest.mark.parametrize("code,prompted,stored", [
    ("refresh_rejected", True, None),
    ("token_endpoint_network_error", False, "old"),
])
def test_restore_failure_classification(code, prompted, stored):
    h = AuthHarness(CoseeingAuthSession, refresh="old")
    result = h.session.get_access_token()
    h.drain()
    h.reject(RestoreError("synthetic", code=code))
    assert h.saved == stored
    assert bool(h.prompts) is prompted
    if prompted:
        assert result.result(timeout=1) is None
    else:
        with pytest.raises(RestoreError):
            result.result(timeout=1)

def test_login_saves_refresh_and_returns_access():
    h = AuthHarness(CoseeingAuthSession, choice="login")
    result = h.session.get_access_token()
    h.drain()
    assert h.auth.calls[0][0] == "login"
    h.resolve(object())
    h.resolve("access")
    h.resolve("refresh")
    assert result.result(timeout=1) == "access"
    assert h.saved == "refresh"
```

以同一 harness 增加目前 session 的 `TokenUnavailableError(refresh_rejected)`、`refresh_unavailable`、LoginError timeout／取消、TokenValidationError、保存錯誤、有效 token 重用與 refresh rotation 測試。斷言錯誤時無額外 `login` 呼叫；所有 `get_access_token` 呼叫的 `auto_login` 都為 False。

- [ ] **Step 5：測試併發與關閉。** 在第一次套件 Future 未完成前呼叫兩次入口，斷言 `auth.calls` 只有一次 restore，完成後兩個結果一致。取消其中一個 waiter，另一個仍完成。`close()` 先設 closed、完成等待中的 caller 為 `ClientClosedError`，再以單獨背景 thread 呼叫 `FutureAuthClient.close()`；回傳 cleanup Future。不要在 UI 等待它。測試關閉後 drain UI 不再詢問、不保存 token；cleanup Future 完成且只呼叫一次 client.close。若對話框正顯示，由 NVDA adapter 的關閉程序主動取消。
- [ ] **Step 6：執行 `python -m pytest tests/test_coseeing_auth.py tests/test_coseeing_auth_bundle.py -q` 並提交。** Commit：`feat: coordinate Coseeing login and guest sessions`。

## Task 3：NVDA 設定、對話框與共用入口

**Files:** `lib/coseeing_auth.py`、`tests/test_coseeing_auth_nvda.py`。

**Interfaces:** Consumes：Task 2 `CoseeingAuthSession`。Produces：

```python
def get_coseeing_access_token(*, reconsider_guest=False) -> Future[str | None]: ...
def start_coseeing_auth(execution_channel: str) -> None: ...
def shutdown_coseeing_auth() -> Future[None]: ...
```

- [ ] **Step 1：寫 adapter 行為測試。** 用 monkeypatch 的 NVDA `config`、`wx.CallAfter` 佇列與 `gui.message.MessageDialog` 替身。dialog 的返回值分別為 YES、NO、取消，斷言映射為 login、guest、cancel；配置保存只修改 `api_key.Coseeing`，不改 OpenAI key。模組的 NVDA imports 放在 adapter 建立時，以免核心測試依賴 NVDA。

```python
def test_local_channel_does_not_request_auth(monkeypatch):
    import lib.coseeing_auth as module
    calls = []
    monkeypatch.setattr(module, "get_coseeing_access_token",
                        lambda **kw: calls.append(kw))
    module.start_coseeing_auth("local")
    assert calls == []

def test_coseeing_channel_reconsiders_guest(monkeypatch):
    from concurrent.futures import Future
    import lib.coseeing_auth as module
    calls = []
    completed = Future()
    completed.set_result(None)
    def request(**kwargs):
        calls.append(kwargs)
        return completed
    monkeypatch.setattr(module, "get_coseeing_access_token", request)
    module.start_coseeing_auth("Coseeing")
    assert calls == [{"reconsider_guest": True}]
```

- [ ] **Step 2：執行 `python -m pytest tests/test_coseeing_auth_nvda.py -q`，確認失敗來源為尚未實作的 adapter。**
- [ ] **Step 3：實作 NVDA adapter 與入口。** 共用實例以鎖保護建立；constructor 只配置 adapter，讀取 config／顯示視窗由 coordinator 排到主執行緒。套件 client 使用 `FutureAuthClient(CoseeingAuthClient(build_auth_config()))`。

```python
def read_refresh_token():
    value = config.conf["WordBridge"]["settings"]["api_key"].get("Coseeing", "")
    return value or None

def save_refresh_token(value):
    keys = config.conf["WordBridge"]["settings"]["api_key"]
    next_value = value or ""
    if keys.get("Coseeing", "") == next_value:
        return
    keys["Coseeing"] = next_value
    config.conf.save()
```

實作時先確認目標 NVDA 的 `config.conf.save()` 對 profile／安全模式的行為，沿用其禁止保存規則。保存失敗回報當次驗證錯誤，不能宣稱已持久化；不自行寫設定檔，也不切換 profile。上述 code 是 adapter 內的 closures，`config` 由該 adapter 的延遲 import 提供。

Dialog 使用舊版的 `gui.message.MessageDialog`、`DefaultButtonSet.YES_NO` 與 `setYesNoLabels`，文字使用 `_()`；以 `try/finally` 清除 active dialog 引用並銷毀。YES → login、NO → guest、其他 → cancel。關閉 addon 時只取消自己持有的 active dialog。

`start_coseeing_auth` 對其他 channel 立即返回；Coseeing 呼叫入口並在完成 callback 排程失敗通知。日誌只用 type、operation、stage、code；不要串入 `str(error)` 或 traceback。已關閉狀態不再顯示錯誤通知。`shutdown_coseeing_auth` 關閉既有 singleton，不為了關閉而建立 client；保持冪等。

- [ ] **Step 4：加測關閉對話框、儲存失敗與已排程通知取消。** 驗證 dialog 銷毀後沒有 CallAfter 重開、關閉回傳 Future、關閉 client 不阻塞 UI 排程，以及有成功登入的狀態不會因設定儲存強制 login。
- [ ] **Step 5：執行兩個 auth 測試檔並提交：** `feat: connect Coseeing auth to NVDA settings and dialogs`。

## Task 4：啟動與設定儲存掛鉤、移除帳密控制項

**Files:** `__init__.py`、`dialogs.py`、`configManager.py`、`tests/test_coseeing_auth_nvda.py`；檢查 `tests/test_corrector_catalog_unittest.py` 的既有帳密測試。

**Interfaces:** Consumes：`start_coseeing_auth(execution_channel)`、`shutdown_coseeing_auth()`、既有 `normalize_selection`。Produces：啟動與儲存後使用已正規化 channel 的行為。

- [ ] **Step 1：先加入掛鉤測試。** 在 `tests/test_coseeing_auth_nvda.py` 以 `monkeypatch.setitem(sys.modules, name, module)` 建立 `gui`／`config`／`globalPluginHandler` 等 NVDA 替身，再透過 `importlib.util.spec_from_file_location` 以獨立 package 名稱載入真實 plugin／panel，呼叫 `GlobalPlugin.__init__`、`terminate`、`LLMSettingsPanel.onSave`。替身的父類初始化與 category registry 使用最小可操作實作；不在全域 `tests/conftest.py` 污染其他測試。`tests/test_helpers.py` 是 provider 測試工具，不提供 NVDA harness。不可只搜尋原始碼字串驗證掛鉤。

以 recorder 捕捉真實掛鉤呼叫，測試應包含以下斷言：

```python
assert auth_calls == ["Coseeing"]       # 啟動或儲存一次只觸發一次
assert saved_channel == "Coseeing"      # 觸發時已寫入新選擇
assert "Coseeing" not in panel.accountTextCtrlMap1
assert "Coseeing" not in panel.accountTextCtrlMap2
assert config_keys["OpenAI"] == "updated-key"
assert config_keys["Coseeing"] == "saved-refresh"
```

`auth_calls` 為 patch 後 `start_coseeing_auth` 的呼叫記錄；`saved_channel` 在 recorder 中讀取 config；`config_keys` 指向 fake config 的 `api_key`。panel 控制項使用 `GetSelection`／`GetValue` 替身；先設定 Coseeing 再儲存 local 的案例應驗證新選擇為 local，不登入。下拉切換及取消不執行 `onSave`，因此不產生 auth 呼叫。

- [ ] **Step 2：執行 `python -m pytest tests/test_coseeing_auth_nvda.py -q`，記錄掛鉤測試失敗。**
- [ ] **Step 3：在 GlobalPlugin 完成基本初始化後正規化選擇並排程。**

```python
settings = config.conf["WordBridge"]["settings"]
_, channel, _ = normalize_selection(
    configManager, settings["corrector_config_id"], settings["execution_channel"],
)
wx.CallAfter(start_coseeing_auth, channel)
```

對應的已排程 callback 必須受 shutdown 狀態保護。`terminate` 呼叫 `shutdown_coseeing_auth()` 且不等待 cleanup Future，再沿用既有 category 移除與父類清理。

- [ ] **Step 4：修改 panel。** 每個 Coseeing authentication sizer 放入說明用 StaticText 後跳過帳密 TextCtrl 建立；保留 sizer map 以供 `_refreshAccountInfo` 顯示隱藏。檢查所有 map 索引，不再假設 Coseeing 存在於兩個 control maps。

```python
if endpoint == "Coseeing":
    self.accountGroupSizerHelper.addItem(wx.StaticText(
        self,
        label=_("Sign in to Coseeing in your browser, or choose to continue as a guest when saving settings."),
    ))
    continue
```

在 `onSave` 完成現有選擇及其他 provider API key 保存後加入 `wx.CallAfter(start_coseeing_auth, selected_item.execution_channel)`。移除 `save_coseeing_credentials` import、呼叫與函式；保留舊 config spec 欄位作為相容資料，不再讀寫它們作驗證。已有測試若只測被移除帳密函式，換成設定儲存不覆寫 refresh token 的行為測試。

- [ ] **Step 5：執行 `python -m pytest tests/test_coseeing_auth_nvda.py tests/test_corrector_catalog_unittest.py tests/test_corrector_task_config.py -q` 並提交。** Commit：`feat: trigger Coseeing authentication on startup and settings save`。

## Task 5：校對與回饋請求共用 token

**Files:** `__init__.py`、`lib/coseeing.py`、`tests/test_coseeing_requests.py`。

**Interfaces:** Consumes：`get_coseeing_access_token() -> Future[str | None]`。Produces：`build_coseeing_headers(access_token: str | None) -> dict[str, str]`；plugin 私有方法 `_send_coseeing_feedback(interaction_id, feedback_value)` 只在背景 thread 執行。

- [ ] **Step 1：寫 header 與 API 行為測試。**

```python
from lib.coseeing import build_coseeing_headers

def test_guest_has_no_authorization_header():
    assert build_coseeing_headers(None) == {}

def test_signed_in_header_uses_access_token():
    assert build_coseeing_headers("access") == {"Authorization": "Bearer access"}
```

沿用 Task 4 的 plugin 替身，patch `get_coseeing_access_token` 為已完成或失敗的 Future、`requests.post` 為 recorder，直接執行真實校對／背景回饋方法。分別以訪客與登入案例斷言兩個 endpoint 的 headers、原有 JSON payload；以失敗 Future 斷言沒有 post，並且通知排到 UI。

- [ ] **Step 2：執行 `python -m pytest tests/test_coseeing_requests.py -q`，確認失敗。**
- [ ] **Step 3：新增 header 純函式，替換校對的舊登入。**

```python
def build_coseeing_headers(access_token: str | None) -> dict[str, str]:
    if access_token is None:
        return {}
    if not access_token:
        raise ValueError("access token must not be empty")
    return {"Authorization": f"Bearer {access_token}"}
```

校對背景 thread 在 Coseeing 分支呼叫入口 `.result()`，成功才建立 headers 與 post；例外時 `wx.CallAfter(ui.message, translated_message)` 後 return。移除目前捕捉登入錯誤後以空字串繼續送出的邏輯；保留現有 timeout、payload、結果與成本處理。401 訊息改為登入無效或訪客無權限，沒有自動重送。

- [ ] **Step 4：拆出回饋背景工作。** `show()` 只收集對話框輸入，先複製當次 interaction ID 與 feedback 值，再啟動 thread：

```python
threading.Thread(
    target=self._send_coseeing_feedback,
    args=(interaction_id, feedback_value),
    name="wordbridge-feedback",
    daemon=True,
).start()
```

`_send_coseeing_feedback` 先等待共用 token Future、建立 headers，再呼叫既有 `/feedback`；增加明確 `timeout=120`，先處理 HTTP 錯誤再解 JSON，所有通知透過 wx。關閉狀態下不再開始新 request／更新 UI；已在途 request 受 timeout 限制。移除兩個 `obtain_openai_key` 呼叫與 import，確認無呼叫者後刪除 `lib/coseeing.py` 的舊帳密登入實作。

- [ ] **Step 5：補測回饋快照與 UI 非阻塞。** 在開啟回饋後改變 `latest_action`，斷言背景工作仍使用原 interaction ID；讓 auth Future 保持 pending，UI 回呼應已返回且沒有 post；完成 Future 後才 post。401、timeout 與非法 JSON 均可結束工作並通知。
- [ ] **Step 6：執行 `python -m pytest tests/test_coseeing_requests.py tests/test_coseeing_auth.py tests/test_coseeing_auth_nvda.py -q` 並提交。** Commit：`feat: authorize Coseeing proofreader and feedback requests with SSO`。

## Task 6：整合驗證與交付

**Files:** 必要時修正前述檔案；更新本計畫 checkbox 與測試結果。無獨立新功能。

**Interfaces:** 驗證 Tasks 1–5 的公開入口與實際 plugin 呼叫鏈，不新增介面。

- [ ] **Step 1：執行聚焦測試與回歸。**

```bash
python -m pytest tests/test_coseeing_auth.py tests/test_coseeing_auth_nvda.py tests/test_coseeing_requests.py tests/test_coseeing_auth_bundle.py tests/test_corrector_catalog_unittest.py tests/test_corrector_task_config.py tests/test_task_architecture_unittest.py -q
git diff --check
```

預期全數通過，沒有真實 SSO/API 呼叫。若新變更造成失敗，先修正並重跑相關檔案；不為了取得通過結果移除測試斷言。

- [ ] **Step 2：檢查 translation 與打包。** 執行 `scons` 及 `scons pot`。用 `python -m zipfile -l` 檢查產生的 `.nvda-addon`：有 auth 模組、使用者附帶套件、必要依賴／授權；沒有 `.env`、舊版參考資料或測試 token。Task 1 的 Windows 匯入檢查需對解開的交付 artifact 再執行一次，以確認不是只在 source tree 可用。
- [ ] **Step 3：執行 Windows NVDA 手動驗收，無環境則明確標示未執行。** Coseeing 啟動時選訪客、連續校對不重問；儲存 Coseeing 設定後再次選登入；瀏覽器 callback 成功且 NVDA 仍可操作；重啟後 refresh 恢復；校對／回饋正常；設定切到其他 provider 不詢問；等待登入時關閉 addon 後 `127.0.0.1:8765` listener 已释放。登入取消、callback timeout、網路錯誤各驗一次，不顯示 token。
- [ ] **Step 4：覆核 spec 覆蓋與任務差異。** 確認新環境或套件支援限制已有實際證據，沒有把尚未完成的 Windows 部署驗證標為成功；確認只變更已授權檔案。
- [ ] **Step 5：提交最後修正與驗證紀錄，交付修改摘要、測試結果與尚待人工驗收項目。** 不自行 push、建立 PR 或部署；執行整合步驟依使用者後續指示。

## Spec 覆蓋檢查

| Spec 要求 | 任務 |
| --- | --- |
| `a11yvillage` 與新版 SSO 設定、套件可匯入 | 1 |
| Token 取得／恢復／更新、訪客有效期間、錯誤分類 | 2 |
| 輪替保存、NVDA 設定、對話框、關閉與通知 | 2、3 |
| 啟動／設定儲存條件與移除帳密欄位 | 4 |
| 校對／回饋 headers、驗證失敗停止請求 | 5 |
| 單一登入流程、UI 不阻塞、回呼關閉保護 | 2、3、5 |
| 自動測試、translation、打包、Windows NVDA 驗收 | 1、6 |

本文件是實作計畫，不代表上述程式碼、測試或 Windows 驗收已完成。執行時逐項勾選，並保留實際命令與結果。
