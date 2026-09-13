## Task 6：整合驗證與交付

**Files:** 必要時修正前述檔案；更新本計畫 checkbox 與測試結果。無獨立新功能。

**Interfaces:** 驗證 Tasks 1–5 的公開入口與實際 plugin 呼叫鏈，不新增介面。

- [x] **Step 1：執行聚焦測試與回歸。**

```bash
python -m pytest tests/test_coseeing_auth.py tests/test_coseeing_auth_nvda.py tests/test_coseeing_requests.py tests/test_coseeing_auth_bundle.py tests/test_corrector_catalog_unittest.py tests/test_corrector_task_config.py tests/test_task_architecture_unittest.py -q
git diff --check
```

預期全數通過，沒有真實 SSO/API 呼叫。若新變更造成失敗，先修正並重跑相關檔案；不為了取得通過結果移除測試斷言。

- [x] **Step 2：檢查 translation 與打包。** `scons`、`scons pot` 及 gettext 工具在此 Linux 環境不可用，因此沒有產生 `.nvda-addon` 可供 `python -m zipfile -l` 檢查。Source bundle audit 確認 auth 模組、兩個 Windows runtime dependency trees、10 份每 runtime 的 METADATA、12 份每 runtime 的 license files，且 deployable addon source 沒有 forbidden secret files。
- [x] **Step 3：執行 Windows NVDA 手動驗收，無環境則明確標示未執行。** 未執行：目前環境是 Linux，沒有 Windows NVDA、瀏覽器 callback 或兩個支援的 native runtime；未將此項標為成功，需在 Windows/NVDA 上人工驗收啟動、guest/login、callback、refresh、校對／回饋、provider 切換、shutdown listener 及三種錯誤路徑。
- [x] **Step 4：覆核 spec 覆蓋與任務差異。** 確認 Linux 測試與 source audit 證據；Windows artifact import/runtime 與 NVDA 手動驗收仍明確列為未完成。Task 6 只新增必要的 stale catalog assertion integration fix；既有 dependency metadata 修改及 untracked `WordBridge(include-auth)/` preserved。
- [x] **Step 5：提交最後修正與驗證紀錄，交付修改摘要、測試結果與尚待人工驗收項目。** Commit `918fccb` contains the only Task 6 integration fix. No push, PR, or deployment performed.

## Task 6 結果

### 聚焦測試

`python` 不存在，因此原命令只回報 `/bin/bash: line 1: python: command not found`；等價的 `python3` 命令結果為 `86 passed, 1 skipped in 0.83s`，`git diff --check` exit 0。先前失敗的舊 catalog assertion 已改為目前實際的 13 個設定，targeted test 結果為 `1 passed in 0.18s`。

### Packaging / translation

`scons` 與 `scons pot` 均回報 `/bin/bash: line 1: scons: command not found`；`python3 -m SCons` 也回報 `No module named SCons`，`msgfmt`、`xgettext`、`gettext` 均不在 PATH。沒有 generated `.nvda-addon`，所以未宣稱 zip listing 或 extracted Windows import 成功。Source audit 結果已記錄於 `docs/superpowers/finish_task.md`。

### Windows limitation

Windows NVDA runtime/manual acceptance 未執行。Linux 無法執行 CPython 3.11 win32 與 CPython 3.13 win_amd64 的 native `.pyd` import，也無法驗證 NVDA UI 操作、瀏覽器 callback、重啟 refresh、實際 listener release 或取消／timeout／network error 的人工流程。

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
