# Coseeing native refresh-token storage — 完成紀錄

已依 design spec 與 implementation plan 完成 Coseeing refresh token 的原生
Windows Credential Manager 整合。

## 交付內容

- 使用 `WindowsCredentialStore("org.coseeing.wordbridge/refresh")` 注入
  `CoseeingAuthClient`，並將 refresh-token restore、rotation、local logout
  委派給 bundled `coseeing_auth` package。
- `CoseeingAuthSession` 不再讀取、儲存或搬運 NVDA 設定檔中的 Coseeing token。
- 設定面板以小寫 `clean` 按鈕取代 Refresh Token 欄位；按鈕狀態依本機 native
  credential 是否存在而定，並正確處理 delete 與 post-delete cleanup 失敗。
- 成功 clean 後會清除 session/singleton；儲存 Coseeing 設定仍會重啟既有登入／訪客流程。
- 新增 storage package bundle contract、session lifecycle、adapter、UI、race、
  cleanup 與 module-isolation 測試。

## 本次新增 commits

- `b292324` chore: ignore local worktrees
- `0022744` build: bundle native Coseeing token storage
- `c3b9625` test: isolate Coseeing bundle configuration check
- `761b884` refactor: delegate Coseeing token lifecycle to native storage
- `0306b75` test: cover Coseeing login cancellation and logout timing
- `127f692` feat: manage Coseeing sessions with Windows credentials
- `051196a` fix: preserve Coseeing clean operation identity
- `cbb9511` feat: add Coseeing credential cleanup control
- `c97bbf4` test: isolate NVDA auth import seams
- `40156cb` test: make NVDA bundle regression order independent
- `a40d4e0` test: verify Coseeing native token storage
- `c5233ac` fix: reflect Coseeing native credential after cleanup error

## 驗證結果

- NVDA auth tests: 27 passed。
- Legacy persistence-path scan: no matches。
- Package source parity（排除 generated `__pycache__`）: clean。
- Credential target scan: 僅 production constant 與兩個對應測試，拼字正確。
- Targeted suite: 76 passed, 1 skipped, 1 known out-of-scope failure。
- Full non-integration suite: 159 passed, 1 skipped, 16 deselected；4 documented
  pre-existing/unrelated failures。

已知的 out-of-scope failure 是既有 SSO configuration test 期待不同的 client ID /
redirect endpoint；本 spec 明定不修改 OIDC endpoint configuration，因此未在本次變更調整。
