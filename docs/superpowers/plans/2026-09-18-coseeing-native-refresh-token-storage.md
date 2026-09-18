# Coseeing 原生重新整理權杖儲存 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 WordBridge 將 Coseeing refresh token 交由 Windows Credential Manager 保存，並在設定面板提供狀態正確的 `clean` 本機登出按鈕。

**Architecture:** 隨附的 `coseeing_auth` package 擁有 refresh-token persistence、還原、輪替及本機登出責任；WordBridge 的 `CoseeingAuthSession` 只協調 Future 與 NVDA UI 執行緒。`lib/coseeing_auth.py` 提供單一的原生 store factory、saved-token 查詢與清除入口，`dialogs.py` 僅根據這些公開入口呈現和更新 `clean` 按鈕。

**Tech Stack:** Python 3.13、NVDA、wxPython、`concurrent.futures`、`coseeing_auth`、Windows Credential Manager、pytest。

**Spec:** [2026-09-18-coseeing-native-refresh-token-storage-design_zh-TW.md](../specs/2026-09-18-coseeing-native-refresh-token-storage-design_zh-TW.md)（英文原文：[2026-09-18-coseeing-native-refresh-token-storage-design.md](../specs/2026-09-18-coseeing-native-refresh-token-storage-design.md)）。執行者須先讀 spec 與本計畫。

## Global Constraints

- Windows Credential Manager target 必須完全等於 `org.coseeing.wordbridge/refresh`。
- `clean` 按鈕 label 必須完全是小寫 `clean`。
- 按鈕狀態只反映 Credential Manager 中是否存在 token，不對 SSO 發送驗證請求。
- 有 token 時啟用 `clean`；沒有 token 或本機讀取失敗時停用。
- `clean` 成功時必須同時清除 package 記憶體 token state、原生 credential，並關閉及重設 WordBridge auth singleton。
- `clean` 刪除失敗時保留按鈕啟用狀態，並走既有的一般 authentication-failure 通知，不顯示敏感內容。
- 成功清除後，若儲存設定時 execution channel 仍為 `Coseeing`，必須再次啟動既有登入／訪客提示流程。
- 不讀取、不顯示、不儲存、不清除、不遷移既有的 `config.conf["WordBridge"]["settings"]["api_key"]["Coseeing"]`。
- 不新增非 Windows 的明文 fallback，不修改登入對話框、OIDC endpoint 或 provider selection 行為。
- 不記錄 token、authorization code、完整登入 URL，或可能包含敏感資料的例外文字。
- 保留工作區內使用者已複製但尚未提交的 `addon/globalPlugins/WordBridge/package/coseeing_auth/` 更新；不可用套件安裝指令或批次覆蓋改寫它。

---

## 檔案與責任

| 檔案 | 動作與責任 |
| --- | --- |
| `addon/globalPlugins/WordBridge/package/coseeing_auth/*.py` | 納管使用者已同步的新 package 生命週期 API；不在本工作重寫其內部邏輯 |
| `addon/globalPlugins/WordBridge/package/coseeing_auth/storage/__init__.py` | 公開 storage contract 與 Windows/macOS adapter |
| `addon/globalPlugins/WordBridge/package/coseeing_auth/storage/storage.py` | `RefreshTokenStore` 與 persistence 協調 |
| `addon/globalPlugins/WordBridge/package/coseeing_auth/storage/windows_credentials.py` | Windows Credential Manager 實作 |
| `addon/globalPlugins/WordBridge/package/coseeing_auth/storage/macos_keychain.py` | 上游 package 快照的一部分；本功能不啟用 macOS 流程 |
| `addon/globalPlugins/WordBridge/lib/coseeing_auth.py` | 原生 store 建立、session restore/access/logout 協調、singleton 清除與 NVDA 通知 |
| `addon/globalPlugins/WordBridge/dialogs.py` | `clean` 按鈕、enable 狀態及非同步完成後的 UI 更新 |
| `tests/coseeing_auth_helpers.py` | 提供 `restore_saved_session()`、`logout_local()` 可控 Future 測試替身 |
| `tests/test_coseeing_auth.py` | 驗證 session 不再手動搬運 refresh token，並驗證 local logout 狀態 |
| `tests/test_coseeing_auth_nvda.py` | 驗證 store target、singleton clear、通知、按鈕和設定儲存流程 |
| `tests/test_coseeing_auth_bundle.py` | 驗證發行 package 內含且公開新版 storage 模組 |

## 執行前檢查

- [ ] 讀取執行時適用的 `AGENTS.md`、上述 spec 與本計畫；依執行 skill 決定是否建立隔離 worktree。若使用 worktree，必須先保留並帶入目前尚未提交的 package 更新。
- [ ] 執行 `git status --short --untracked-files=all`，記錄基線。預期至少看到使用者已更新的 `addon/globalPlugins/WordBridge/package/coseeing_auth/*.py`；`storage/` 因根目錄 `.gitignore` 的 `storage` 規則而被忽略，納管時必須使用明確路徑與 `git add -f`。
- [ ] 執行 `diff -rq /workspace/SSO/SSO/packages/coseeing-auth/src/coseeing_auth addon/globalPlugins/WordBridge/package/coseeing_auth`。預期無輸出；若有差異，停止 package 納管並先列出差異請使用者確認，不自行覆蓋。
- [ ] 執行 `python -m pytest tests/test_coseeing_auth.py tests/test_coseeing_auth_nvda.py tests/test_coseeing_auth_bundle.py -q` 並保存基線結果。現有測試仍描述設定檔 token 流程，後續 task 會以新契約取代。

### Task 1：驗證並納管新版 `coseeing_auth` storage package

**Files:**
- Modify: `tests/test_coseeing_auth_bundle.py:119-189`
- Add existing ignored files: `addon/globalPlugins/WordBridge/package/coseeing_auth/storage/__init__.py`
- Add existing ignored files: `addon/globalPlugins/WordBridge/package/coseeing_auth/storage/storage.py`
- Add existing ignored files: `addon/globalPlugins/WordBridge/package/coseeing_auth/storage/windows_credentials.py`
- Add existing ignored files: `addon/globalPlugins/WordBridge/package/coseeing_auth/storage/macos_keychain.py`
- Add existing user updates: `addon/globalPlugins/WordBridge/package/coseeing_auth/__init__.py`
- Add existing user updates: `addon/globalPlugins/WordBridge/package/coseeing_auth/client.py`
- Add existing user updates: `addon/globalPlugins/WordBridge/package/coseeing_auth/errors.py`
- Add existing user updates: `addon/globalPlugins/WordBridge/package/coseeing_auth/future.py`
- Add existing user updates: `addon/globalPlugins/WordBridge/package/coseeing_auth/tokens.py`
- Add existing byte-identical upstream update: `addon/globalPlugins/WordBridge/package/coseeing_auth/callback.py`
- Add existing byte-identical upstream update: `addon/globalPlugins/WordBridge/package/coseeing_auth/models.py`
- Add existing byte-identical upstream update: `addon/globalPlugins/WordBridge/package/coseeing_auth/oidc.py`
- Add existing byte-identical upstream update: `addon/globalPlugins/WordBridge/package/coseeing_auth/verification.py`

**Interfaces:**
- Consumes: `/workspace/SSO/SSO/packages/coseeing-auth/src/coseeing_auth`，作為使用者已同步內容的唯一本機來源依據。
- Produces: `WindowsCredentialStore(target_name: str)`、`CoseeingAuthClient(..., refresh_token_store=store)`、`FutureAuthClient.restore_saved_session() -> Future`、`FutureAuthClient.logout_local() -> Future`。

- [ ] **Step 1：加入 bundle contract 測試。** 在 `tests/test_coseeing_auth_bundle.py` 新增：

```python
def test_coseeing_auth_bundle_contains_native_refresh_token_storage():
	package = PACKAGE_ROOT / "coseeing_auth"
	storage = package / "storage"
	assert {path.name for path in storage.glob("*.py")} == {
		"__init__.py",
		"macos_keychain.py",
		"storage.py",
		"windows_credentials.py",
	}


def test_coseeing_auth_exports_windows_store_and_saved_session_api():
	from coseeing_auth import CoseeingAuthClient, FutureAuthClient, WindowsCredentialStore

	assert WindowsCredentialStore.__module__.endswith("storage.windows_credentials")
	assert callable(CoseeingAuthClient.restore_saved_session)
	assert callable(CoseeingAuthClient.logout_local)
	assert callable(FutureAuthClient.restore_saved_session)
	assert callable(FutureAuthClient.logout_local)
```

- [ ] **Step 2：執行 package contract 測試。** Run: `python -m pytest tests/test_coseeing_auth_bundle.py -q`。Expected: PASS，因新版 package 已由使用者放入工作區；若 FAIL，只修正缺少的納管／公開介面問題，不重裝 package。

- [ ] **Step 3：再次確認 package 與 SSO 來源一致。** Run: `diff -rq /workspace/SSO/SSO/packages/coseeing-auth/src/coseeing_auth addon/globalPlugins/WordBridge/package/coseeing_auth`。Expected: 無輸出。

- [ ] **Step 4：明確加入 package 檔案。** 一般檔案使用 `git add`；storage 目錄因 ignore 規則使用：

```bash
git add -f addon/globalPlugins/WordBridge/package/coseeing_auth/storage/__init__.py \
  addon/globalPlugins/WordBridge/package/coseeing_auth/storage/storage.py \
  addon/globalPlugins/WordBridge/package/coseeing_auth/storage/windows_credentials.py \
  addon/globalPlugins/WordBridge/package/coseeing_auth/storage/macos_keychain.py
git add addon/globalPlugins/WordBridge/package/coseeing_auth tests/test_coseeing_auth_bundle.py
```

- [ ] **Step 5：確認 staged diff 只包含 SSO 同步內容與 bundle contract。** Run: `git diff --cached --check && git diff --cached --stat`。Expected: 無 whitespace error，storage 四個模組都出現在 stat 中。

- [ ] **Step 6：提交 package 快照。**

```bash
git commit -m "build: bundle native Coseeing token storage"
```

### Task 2：將 session 切換為 package-owned refresh-token lifecycle

**Files:**
- Modify: `addon/globalPlugins/WordBridge/lib/coseeing_auth.py:77-454`
- Modify: `tests/coseeing_auth_helpers.py:6-86`
- Modify: `tests/test_coseeing_auth.py:19-914`

**Interfaces:**
- Consumes: `FutureAuthClient.restore_saved_session() -> Future[AuthResult | None]`、`get_access_token(auto_login=False) -> Future[str]`、`logout_local() -> Future[LogoutResult]`。
- Produces:

```python
class CoseeingAuthSession:
	def __init__(self, *, client_factory, post_ui, prompt_login,
	             auth_state: AuthSessionState | None = None) -> None: ...
	def get_access_token(self, *, reconsider_guest: bool = False,
	                     silent: bool = False) -> Future[str | None]: ...
	def logout_local(self) -> Future[None]: ...
	def close(self) -> Future[None]: ...
```

- [ ] **Step 1：先把測試替身改成新版 client contract。** `FakeAuth` 不再實作 `restore(token)` 或 `get_refresh_token()`，改為：

```python
class FakeAuth:
	def __init__(self, close_started=None, close_release=None):
		self.calls = []
		self.pending = deque()
		self.close_started = close_started
		self.close_release = close_release
		self.close_thread_name = None

	def _submit(self, name, *args, **kwargs):
		result = Future()
		self.calls.append((name, args, kwargs))
		self.pending.append(result)
		return result

	def restore_saved_session(self):
		return self._submit("restore_saved_session")

	def get_access_token(self, *, auto_login=False):
		return self._submit("get_access_token", auto_login=auto_login)

	def login(self):
		return self._submit("login")

	def logout_local(self):
		return self._submit("logout_local")

	def close(self):
		self.calls.append(("close", (), {}))
		self.close_thread_name = current_thread().name
		if self.close_started is not None:
			self.close_started.set()
		if self.close_release is not None:
			self.close_release.wait(timeout=5)
```

`AuthHarness` 移除 `refresh`、`save_error`、`saved` 與 `save()`，並使用以下建構參數：

```python
self.session = session_class(
	client_factory=make_auth,
	post_ui=lambda fn, *args: self.queue.append((fn, args)),
	prompt_login=self.prompt,
	auth_state=auth_state,
)
```

- [ ] **Step 2：以新版生命週期測試取代手動 token 測試。** 刪除只驗證 `read_refresh_token`、`save_refresh_token`、`get_refresh_token` 或 `_pending_refresh` 的測試，加入下列核心案例：

```python
def test_saved_session_restore_returns_access_without_manual_refresh_callbacks():
	h = AuthHarness(CoseeingAuthSession)
	result = h.session.get_access_token()
	h.drain()
	assert h.auth.calls == [("restore_saved_session", (), {})]
	h.resolve(object())
	h.resolve("access")
	assert result.result(timeout=1) == "access"
	assert [call[0] for call in h.auth.calls] == [
		"restore_saved_session", "get_access_token",
	]
	assert h.prompts == 0


def test_missing_saved_session_prompts_without_manual_token_access():
	h = AuthHarness(CoseeingAuthSession, choice="guest")
	result = h.session.get_access_token()
	h.drain()
	h.resolve(None)
	assert result.result(timeout=1) is None
	assert h.prompts == 1
	assert h.auth.calls == [("restore_saved_session", (), {})]


def test_login_returns_access_without_requesting_refresh_token():
	h = AuthHarness(CoseeingAuthSession, choice="login")
	result = h.session.get_access_token()
	h.drain()
	h.resolve(None)
	assert h.auth.calls[-1][0] == "login"
	h.resolve(object())
	h.resolve("access")
	assert result.result(timeout=1) == "access"
	assert "get_refresh_token" not in [call[0] for call in h.auth.calls]
```

- [ ] **Step 3：加入 session 本機登出測試。** 驗證完成前 Future 不完成、成功後清除 session 狀態，錯誤則原樣交給呼叫端：

```python
def test_logout_local_clears_package_state_and_session_flags():
	h = AuthHarness(CoseeingAuthSession)
	h.session._session_ready = True
	h.session._guest = True
	result = h.session.logout_local()
	h.drain()
	assert h.auth.calls == [("logout_local", (), {})]
	h.resolve(object())
	assert result.result(timeout=1) is None
	assert h.session._session_ready is False
	assert h.session._guest is False


def test_logout_local_failure_reaches_caller():
	h = AuthHarness(CoseeingAuthSession)
	result = h.session.logout_local()
	h.drain()
	error = RuntimeError("sanitized persistence failure")
	h.reject(error)
	with pytest.raises(RuntimeError, match="sanitized persistence failure"):
		result.result(timeout=1)
```

- [ ] **Step 4：執行 targeted tests，確認舊實作失敗。** Run: `python -m pytest tests/test_coseeing_auth.py -q`。Expected: FAIL，原因包含 constructor 仍要求 read/save callbacks、呼叫 `restore`，以及缺少 `logout_local()`。

- [ ] **Step 5：實作 saved-session restore 流程。** 在 `CoseeingAuthSession.__init__` 移除 read/save callbacks 及 `_pending_refresh`。尚未 ready 時一律呼叫：

```python
def _start_restore_saved_session(self, silent: bool) -> None:
	try:
		future = self._call_client("restore_saved_session")
		self._watch(
			future,
			lambda result: self._restore_saved_session_succeeded(result, silent=silent),
			silent=silent,
		)
	except Exception as error:
		self._fail(error, silent=silent)


def _restore_saved_session_succeeded(self, result, *, silent: bool) -> None:
	if result is None:
		self._start_prompt(silent)
		return
	self._auth_state.refresh_token_was_valid = True
	self._session_ready = True
	self._start_access_token(silent=silent)
```

`_token_succeeded` 直接 `self._finish(value=access_token)`。移除 `_refresh_succeeded()`、`_retry_pending_refresh()`，並從 `_fail()` 移除對設定檔 callback 的清除；保留既有錯誤分類及登入／訪客決策，但 refresh-token persistence 完全交給 package。

- [ ] **Step 6：實作可獨立完成的本機登出 Future。** `logout_local()` 將開始動作排到 UI 執行緒；package Future 的 callback 只把結果排回 UI，不在 worker callback 操作 wx。成功 handler 設定 `_session_ready = False`、`_guest = False`、`_auth_state.refresh_token_was_valid = False`，然後完成呼叫端 Future。錯誤直接完成為 exception，不呼叫 access-token waiters 的 `_finish()`。

```python
def logout_local(self) -> Future[None]:
	result: Future[None] = Future()
	try:
		self._post_ui(self._start_logout_local, result)
	except Exception as error:
		result.set_exception(error)
	return result


def _start_logout_local(self, result: Future[None]) -> None:
	try:
		future = self._call_client("logout_local")
	except Exception as error:
		self._complete(result, error=error)
		return

	def completed(done: Future) -> None:
		try:
			self._post_ui(deliver, done)
		except Exception as error:
			self._complete(result, error=error)

	def deliver(done: Future) -> None:
		try:
			done.result()
		except Exception as error:
			self._complete(result, error=error)
			return
		self._session_ready = False
		self._guest = False
		self._auth_state.refresh_token_was_valid = False
		self._complete(result, value=None)

	future.add_done_callback(completed)
```

- [ ] **Step 7：機械式更新其餘 constructor 與 concurrency 測試。** 所有直接建立 `CoseeingAuthSession` 的測試移除 `read_refresh_token=`、`save_refresh_token=`；舊 `restore` 斷言改為 `restore_saved_session` 且無引數。保留原有 close、scheduler failure、重疊 caller、取消與 shutdown race 測試的同步語意，不因改 storage 而刪除。

- [ ] **Step 8：執行 session 測試。** Run: `python -m pytest tests/test_coseeing_auth.py -q`。Expected: PASS。

- [ ] **Step 9：檢查已移除的舊 token 搬運路徑。** Run:

```bash
rg -n "read_refresh_token|save_refresh_token|_pending_refresh|get_refresh_token" \
  addon/globalPlugins/WordBridge/lib/coseeing_auth.py \
  tests/coseeing_auth_helpers.py tests/test_coseeing_auth.py
```

Expected: 無輸出。

- [ ] **Step 10：提交 session 遷移。**

```bash
git add addon/globalPlugins/WordBridge/lib/coseeing_auth.py \
  tests/coseeing_auth_helpers.py tests/test_coseeing_auth.py
git commit -m "refactor: delegate Coseeing token lifecycle to native storage"
```

### Task 3：接入 Windows store、查詢狀態與 singleton 清除流程

**Files:**
- Modify: `addon/globalPlugins/WordBridge/lib/coseeing_auth.py:15-74,456-679`
- Modify: `tests/test_coseeing_auth_nvda.py:384-734`

**Interfaces:**
- Consumes: Task 1 的 `WindowsCredentialStore`、`CoseeingAuthClient(refresh_token_store=...)`；Task 2 的 `CoseeingAuthSession.logout_local() -> Future[None]`。
- Produces:

```python
COSEEING_REFRESH_TOKEN_TARGET = "org.coseeing.wordbridge/refresh"

def has_saved_coseeing_refresh_token() -> bool: ...
def clean_coseeing_auth() -> Future[None]: ...
```

- [ ] **Step 1：先加入 store factory 與 client injection 測試。** 以 fake module 取得實際 constructor 參數：

```python
def test_client_factory_injects_exact_windows_credential_target(monkeypatch):
	constructed = []

	class Store:
		def __init__(self, target):
			self.target = target
			constructed.append(("store", target))

	class Client:
		def __init__(self, config, *, refresh_token_store):
			self.config = config
			self.store = refresh_token_store
			constructed.append(("client", config, refresh_token_store))

	class FutureClient:
		def __init__(self, client):
			self.client = client

	monkeypatch.setitem(sys.modules, "coseeing_auth", SimpleNamespace(
		CoseeingAuthClient=Client,
		FutureAuthClient=FutureClient,
		WindowsCredentialStore=Store,
	))
	config = object()
	monkeypatch.setattr(module, "build_auth_config", lambda: config)
	result = module._NvdaAuthAdapter().client_factory()
	assert result.client.store.target == "org.coseeing.wordbridge/refresh"
	assert constructed[0] == ("store", "org.coseeing.wordbridge/refresh")
```

- [ ] **Step 2：加入 saved-token existence 測試。** fake store 的 `load()` 分別回傳 token、`None` 與拋出 `TokenPersistenceError`，斷言 `has_saved_coseeing_refresh_token()` 依序為 `True`、`False`、`False`，並斷言沒有建立 HTTP/OIDC client。

```python
@pytest.mark.parametrize("value,expected", [("stored", True), (None, False)])
def test_saved_refresh_token_state_is_local_existence_check(monkeypatch, value, expected):
	class Store:
		def load(self):
			return value
	monkeypatch.setattr(module, "_new_refresh_token_store", lambda: Store())
	assert module.has_saved_coseeing_refresh_token() is expected


def test_saved_refresh_token_read_failure_is_treated_as_absent(monkeypatch):
	class Store:
		def load(self):
			raise RuntimeError("native storage unavailable")
	monkeypatch.setattr(module, "_new_refresh_token_store", lambda: Store())
	assert module.has_saved_coseeing_refresh_token() is False
```

- [ ] **Step 3：加入 public clean orchestration 測試。** 測試成功時先呼叫 singleton session 的 `logout_local()`，完成後才呼叫既有 `reset_coseeing_auth()` 並等待 cleanup；失敗時不 reset，回傳原錯誤且交給 adapter 的 generic notification。

```python
def test_clean_logs_out_then_resets_singleton(monkeypatch):
	logout = Future()
	cleanup = Future()
	calls = []

	class Session:
		def logout_local(self):
			calls.append("logout_local")
			return logout

	class Adapter:
		def notify_completion(self, done):
			calls.append(("notify", done))

	monkeypatch.setattr(module, "_get_singleton", lambda: Session())
	monkeypatch.setattr(module, "_singleton_adapter", Adapter())
	monkeypatch.setattr(module, "reset_coseeing_auth", lambda: calls.append("reset") or cleanup)
	result = module.clean_coseeing_auth()
	logout.set_result(None)
	assert calls[0] == "logout_local"
	assert "reset" in calls
	assert not result.done()
	cleanup.set_result(None)
	assert result.result(timeout=1) is None
```

另加入失敗案例：讓 `logout_local()` Future 以帶有 `refresh-token-secret` 文字的 `TokenPersistenceError` 失敗，斷言 bridge Future 回傳該錯誤、`reset_coseeing_auth()` 未被呼叫、`notify_completion()` 收到 bridge Future，且現有 log capture 不含 `refresh-token-secret`。

- [ ] **Step 4：執行 targeted adapter tests，確認失敗。** Run: `python -m pytest tests/test_coseeing_auth_nvda.py -k "client_factory or saved_refresh_token or clean" -q`。Expected: FAIL，原因是尚未注入 store，且查詢／清除入口不存在。

- [ ] **Step 5：建立唯一 store factory 並注入 client。** 在 `lib/coseeing_auth.py` 定義：

```python
COSEEING_REFRESH_TOKEN_TARGET = "org.coseeing.wordbridge/refresh"


def _new_refresh_token_store():
	from coseeing_auth import WindowsCredentialStore
	return WindowsCredentialStore(COSEEING_REFRESH_TOKEN_TARGET)


def has_saved_coseeing_refresh_token() -> bool:
	try:
		return _new_refresh_token_store().load() is not None
	except Exception:
		return False
```

`_NvdaAuthAdapter.client_factory()` 必須以 `refresh_token_store=_new_refresh_token_store()` 建立 `CoseeingAuthClient`。移除 adapter 的設定檔 `read_refresh_token()` 與 `save_refresh_token()`；`session()` 只傳 Task 2 的 constructor 參數。

- [ ] **Step 6：實作 public clean orchestration。** `clean_coseeing_auth()` 建立 bridge `Future[None]`，呼叫現有 singleton 的 `logout_local()`；成功後鏈接 `reset_coseeing_auth()` 的 cleanup Future，兩者都成功才完成 bridge。任何失敗都保留 exception，且以開始操作時取得的 adapter 呼叫 `notify_completion()`；不得把 `str(error)` 寫入 log。不得在 Future callback 中等待另一個 Future。

```python
def _settle_none(destination: Future[None], error: Exception | None = None) -> None:
	try:
		if error is None:
			destination.set_result(None)
		else:
			destination.set_exception(error)
	except InvalidStateError:
		pass


def clean_coseeing_auth() -> Future[None]:
	bridge: Future[None] = Future()
	try:
		session = _get_singleton()
		adapter = _singleton_adapter
		logout = session.logout_local()
	except Exception as error:
		_settle_none(bridge, error)
		return bridge

	if adapter is not None:
		bridge.add_done_callback(adapter.notify_completion)

	def cleanup_done(done: Future) -> None:
		try:
			done.result()
		except Exception as error:
			_settle_none(bridge, error)
		else:
			_settle_none(bridge)

	def logout_done(done: Future) -> None:
		try:
			done.result()
		except Exception as error:
			_settle_none(bridge, error)
			return
		try:
			cleanup = reset_coseeing_auth()
		except Exception as error:
			_settle_none(bridge, error)
			return
		cleanup.add_done_callback(cleanup_done)

	logout.add_done_callback(logout_done)
	return bridge
```

- [ ] **Step 7：更新舊 adapter 測試。** 將 `test_nvda_adapter_maps_dialog_choices_and_only_saves_coseeing` 改為只驗證 dialog choice；刪除 `test_save_refresh_token_reports_config_save_failure`。將所有 `CoseeingAuthSession` constructor 更新成 Task 2 介面，並保留 shutdown/concurrency assertions。

- [ ] **Step 8：執行 auth 與 adapter 測試。** Run: `python -m pytest tests/test_coseeing_auth.py tests/test_coseeing_auth_nvda.py -q`。Expected: PASS。

- [ ] **Step 9：提交 native adapter 與清除流程。**

```bash
git add addon/globalPlugins/WordBridge/lib/coseeing_auth.py tests/test_coseeing_auth_nvda.py
git commit -m "feat: manage Coseeing sessions with Windows credentials"
```

### Task 4：以 `clean` 按鈕取代 refresh-token 編輯欄位

**Files:**
- Modify: `addon/globalPlugins/WordBridge/dialogs.py:18,98-130,245-275`
- Modify: `tests/test_coseeing_auth_nvda.py:188-346`

**Interfaces:**
- Consumes: Task 3 的 `has_saved_coseeing_refresh_token() -> bool`、`clean_coseeing_auth() -> Future[None]`，以及既有 `start_coseeing_auth(channel, silent=False)`。
- Produces: `LLMSettingsPanel.coseeingCleanButton`、`onCleanCoseeingAuth(self, event)`、`_finishCleanCoseeingAuth(self, done: Future[None])`。

- [ ] **Step 1：改寫設定面板建構測試。** fake widget 明確保存 label、enable 狀態及 bound callback：

```python
class Widget:
	def __init__(self, *args, value="", label="", **kwargs):
		self.value = value
		self.label = label
		self.enabled = True
		self.bindings = {}

	def Enable(self, enabled=True):
		self.enabled = enabled

	def Disable(self):
		self.enabled = False

	def IsEnabled(self):
		return self.enabled

	def Bind(self, event, callback):
		self.bindings[event] = callback
```

然後驗證沒有 token 時按鈕存在且停用，且沒有 Refresh Token text control：

```python
monkeypatch.setattr(dialogs, "has_saved_coseeing_refresh_token", lambda: False)
panel = object.__new__(dialogs.LLMSettingsPanel)
panel.scaleSize = lambda value: value
panel._refreshAccountInfo = lambda: None
panel.makeSettings(Sizer())
assert panel.coseeingCleanButton.label == "clean"
assert panel.coseeingCleanButton.IsEnabled() is False
assert "Coseeing" not in panel.accountTextCtrlMap
assert not [call for call in Helper.calls if call[0] == "Refresh Token:"]
```

另以 `has_saved_coseeing_refresh_token=lambda: True` 建立面板，斷言 `IsEnabled() is True`。fake `Bind` 必須保存 callback，讓下一步能實際觸發。
再以不含 `api_key["Coseeing"]` 的設定建立面板，斷言 `makeSettings()` 後該 key 仍不存在，證明狀態查詢不會建立舊版設定值。

- [ ] **Step 2：加入 clean 成功與失敗 UI 測試。** 成功時操作進行中先停用，Future 成功後維持停用；失敗時重新啟用。完成 callback 必須經 `wx.CallAfter` 回 UI。

```python
def test_clean_button_disables_on_success_and_reenables_on_failure(monkeypatch):
	pending = Future()
	monkeypatch.setattr(dialogs, "clean_coseeing_auth", lambda: pending)
	panel.onCleanCoseeingAuth(None)
	assert panel.coseeingCleanButton.IsEnabled() is False
	pending.set_exception(RuntimeError("sanitized"))
	callback, args = queued.pop()
	callback(*args)
	assert panel.coseeingCleanButton.IsEnabled() is True
```

成功案例使用新的 Future，`set_result(None)` 後 drain `wx.CallAfter`，斷言仍停用。

- [ ] **Step 3：改寫設定儲存測試。** `accountTextCtrlMap` 只含其他 provider；保留既有 `api_key["Coseeing"] == "saved-refresh"` 作為 sentinel。呼叫 `onSave()` 後斷言 sentinel 完全未修改；另以不含 Coseeing key 的設定再執行一次，斷言不會建立該 key。execution channel 為 Coseeing 時 queued `start_coseeing_auth(..., silent=False)` 仍被執行，且不再呼叫 `reset_coseeing_auth()`。

```python
assert settings["api_key"]["Coseeing"] == "saved-refresh"
assert auth_calls == ["Coseeing"]
```

- [ ] **Step 4：執行 panel tests，確認舊 UI 失敗。** Run: `python -m pytest tests/test_coseeing_auth_nvda.py -k "settings_panel or settings_save or clean_button" -q`。Expected: FAIL，原因是仍建立 Refresh Token `TextCtrl` 且沒有 clean handlers。

- [ ] **Step 5：建立 `clean` 按鈕。** 先更新 `tests/test_coseeing_auth_nvda.py` 的動態 plugin stub，避免測試載入 `dialogs.py` 時缺少新公開符號：

```python
clean_future = Future()
clean_future.set_result(None)
auth_module.clean_coseeing_auth = lambda: clean_future
auth_module.has_saved_coseeing_refresh_token = lambda: False
```

接著更新 production import：

```python
from .lib.coseeing_auth import (
	clean_coseeing_auth,
	has_saved_coseeing_refresh_token,
	start_coseeing_auth,
)
```

在 Coseeing account group 中不加入 `accountTextCtrlMap`，改為：

```python
self.coseeingCleanButton = wx.Button(self, label="clean")
self.coseeingCleanButton.Enable(has_saved_coseeing_refresh_token())
self.coseeingCleanButton.Bind(wx.EVT_BUTTON, self.onCleanCoseeingAuth)
self.accountGroupSizerHelper.addItem(self.coseeingCleanButton)
```

Coseeing branch 必須位於 `if endpoint not in config.conf[...]["api_key"]` 的預設值寫入之前並以 `continue` 結束；只有其他 provider 才可建立空白 API-key 預設值。如此既有 Coseeing 值保持不變，缺少時也不會被建立。

- [ ] **Step 6：實作非同步按鈕 handler。** 點擊後立即停用防止重複操作；Future callback 只排程 UI handler：

```python
def onCleanCoseeingAuth(self, event) -> None:
	self.coseeingCleanButton.Disable()
	future = clean_coseeing_auth()
	future.add_done_callback(
		lambda done: wx.CallAfter(self._finishCleanCoseeingAuth, done)
	)


def _finishCleanCoseeingAuth(self, done: Future[None]) -> None:
	try:
		done.result()
	except Exception:
		self.coseeingCleanButton.Enable(True)
	else:
		self.coseeingCleanButton.Enable(False)
```

從 `concurrent.futures` 匯入 `Future` 只供 type annotation。通知由 Task 3 的 public clean 流程處理，這裡不得顯示例外文字。

- [ ] **Step 7：簡化 `onSave()`。** 移除 `_coseeingRefreshTokenOnOpen`、`coseeing_refresh_token_changed` 與 refresh-token edit/reset branch。迴圈只儲存 `accountTextCtrlMap` 中其他 provider 的 API key，之後照常以 `wx.CallAfter(lambda: start_coseeing_auth(selected_item.execution_channel, silent=False))` 啟動所選通道。

- [ ] **Step 8：執行 UI 與 auth 整合測試。** Run: `python -m pytest tests/test_coseeing_auth_nvda.py -q`。Expected: PASS。

- [ ] **Step 9：確認 legacy 設定值沒有任何 active read/write。** Run:

```bash
rg -n "_coseeingRefreshTokenOnOpen|Refresh Token:|api_key.*Coseeing|Coseeing.*api_key" \
  addon/globalPlugins/WordBridge/lib/coseeing_auth.py addon/globalPlugins/WordBridge/dialogs.py
```

Expected: 無輸出。一般 provider 的 `api_key` 讀寫仍存在且不得移除。

- [ ] **Step 10：提交設定面板。**

```bash
git add addon/globalPlugins/WordBridge/dialogs.py tests/test_coseeing_auth_nvda.py
git commit -m "feat: add Coseeing credential cleanup control"
```

### Task 5：全套驗證與交付檢查

**Files:**
- Verify only: `addon/globalPlugins/WordBridge/package/coseeing_auth/`
- Verify only: `addon/globalPlugins/WordBridge/lib/coseeing_auth.py`
- Verify only: `addon/globalPlugins/WordBridge/dialogs.py`
- Verify only: `tests/coseeing_auth_helpers.py`
- Verify only: `tests/test_coseeing_auth.py`
- Verify only: `tests/test_coseeing_auth_nvda.py`
- Verify only: `tests/test_coseeing_auth_bundle.py`

**Interfaces:**
- Consumes: Tasks 1–4 的完成結果。
- Produces: 經 targeted/full test、diff 與敏感資料掃描驗證的可交付變更；本 task 不新增 API。

- [ ] **Step 1：執行 storage/auth targeted suite。** Run:

```bash
python -m pytest \
  tests/test_coseeing_auth_bundle.py \
  tests/test_coseeing_auth.py \
  tests/test_coseeing_auth_nvda.py -q
```

Expected: PASS。

- [ ] **Step 2：執行所有非外部整合測試。** Run: `python -m pytest -m "not integration" -q`。Expected: PASS；若有既存失敗，與執行前基線逐項比對並在交付摘要列出，不可籠統宣稱全數通過。

- [ ] **Step 3：執行敏感資料與 legacy path 掃描。** Run:

```bash
rg -n "read_refresh_token|save_refresh_token|_pending_refresh|Refresh Token:" \
  addon/globalPlugins/WordBridge tests/test_coseeing_auth.py \
  tests/test_coseeing_auth_nvda.py tests/coseeing_auth_helpers.py
```

Expected: 無 active code 或測試引用；若翻譯 catalog/歷史文件出現不在本 task 修改。

- [ ] **Step 4：驗證 package 來源與 credential target。** Run:

```bash
diff -rq /workspace/SSO/SSO/packages/coseeing-auth/src/coseeing_auth \
  addon/globalPlugins/WordBridge/package/coseeing_auth
rg -n 'org\.coseeing\.wordbridge/refresh' \
  addon/globalPlugins/WordBridge/lib/coseeing_auth.py \
  tests/test_coseeing_auth_nvda.py
```

Expected: `diff` 無輸出；target 只出現在整合常數與對應測試，拼字完全一致。

- [ ] **Step 5：檢查 commit 與工作樹。** Run: `git status --short && git log --oneline -5`。Expected: 本計畫產生四個功能 commit；只剩執行前已記錄且未納入本工作的使用者變更。

- [ ] **Step 6：若驗證造成必要的小修，重跑受影響的 targeted test 後獨立提交。** Commit message 使用：

```bash
git commit -m "test: verify Coseeing native token storage"
```

沒有修正時不建立空 commit。
