# WordBridge Coseeing SSO 整合設計

日期：2026-09-13

狀態：使用者已確認，實作計畫已撰寫；尚未實作。

## 目的與範圍

將 WordBridge 現有的 Coseeing 帳號密碼登入改為使用 addon 已附帶的 `coseeing_auth`。保留舊版 `WordBridge(include-auth)` 的「立即登入／以訪客繼續」選擇，並依新版 wxPython demo 使用 Coseeing SSO。

本次涵蓋 token 取得與保存、addon 啟動與設定儲存觸發、校對與回饋請求的驗證 header，以及驗證流程的生命週期。其他 provider 的 API key 與本機執行流程沿用既有行為。

參考來源：

- 舊版：`WordBridge(include-auth)/dialogs.py`、`lib/auth/registry.py`、`__init__.py`。
- 新版 demo：`/workspace/SSO/SSO/client/wxpython/main.py` 與 `.env`。
- 套件來源：`/workspace/SSO/SSO/packages/coseeing-auth`。
- 實際使用的套件：`addon/globalPlugins/WordBridge/package/coseeing_auth`。

## 已確認需求

1. 提供 `get_coseeing_access_token`，透過 `coseeing_auth` 取得 access token。
2. 沒有 refresh token 時，顯示「立即登入／以訪客繼續」對話框。
3. 有 refresh token 時先嘗試取得 access token；refresh token 過期或失效時，顯示相同對話框。
4. provider 為 Coseeing 時，addon 啟動及 WordBridge 設定儲存後觸發此流程。
5. 選擇訪客後，當次 addon 執行期間的校對請求不再詢問。addon 重啟，或 provider 為 Coseeing 時再次儲存設定，會重新評估登入狀態並在需要時詢問。
6. 訪客請求不帶 `Authorization` header；已登入請求使用 access token 作為 Bearer token。
7. SSO client ID 使用使用者更新後的 `a11yvillage`。

## SSO 設定

| 項目 | 值 |
| --- | --- |
| Issuer | `https://sso.coseeing.org` |
| Client ID | `a11yvillage` |
| Scopes | `openid profile email offline_access` |
| 登入 callback | `http://127.0.0.1:8765/auth-callback` |
| 登出 callback | `http://127.0.0.1:8765/logout-callback` |
| Callback timeout | 180 秒 |

以上值來自 2026-09-13 重新讀取的新版 demo `.env`。由 addon 自己持有這些公開設定，不在執行時依賴外部 SSO 專案目錄，也不沿用舊版 Google 或開發環境設定。瀏覽器登入與 callback 驗證交由套件處理。

## 元件與責任

新增 `addon/globalPlugins/WordBridge/lib/coseeing_auth.py` 作為整合層，套件本身仍以頂層 `coseeing_auth` 匯入。

整合層持有 addon 共用的驗證實例、目前登入或訪客狀態，以及進行中的工作。以 `AuthConfig`、`CoseeingAuthClient` 與 `FutureAuthClient` 使用套件的公開介面；NVDA 設定讀寫、對話框與通知由整合層協調。

`get_coseeing_access_token` 回傳 `Future[str | None]`：成功登入時結果為 access token，使用者選擇訪客時為 `None`，驗證錯誤時 Future 以例外完成。呼叫端不得在 wx 主執行緒等待 `.result()`。Future callback 中也不得阻塞等待同一個 executor 的後續工作。

啟動與設定儲存呼叫可要求重新評估訪客選擇；一般請求呼叫則尊重既有訪客狀態。重疊的呼叫共用進行中的驗證結果，同一時間只顯示一個選擇對話框或執行一個登入流程。

## Token 與登入流程

1. 一般請求若處於訪客狀態，直接完成為 `None`。
2. 若套件已持有 session，呼叫 `get_access_token(auto_login=False)`，由套件重用有效 token 或更新到期 token。
3. 若尚未恢復 session 且已保存 refresh token，先呼叫 `restore(refresh_token)`，成功後取得 access token。
4. 沒有 refresh token，或套件明確回報 refresh token 遭拒時，在 wx 主執行緒顯示選擇對話框。
5. 選「立即登入」後呼叫套件 `login()`，成功後取得 access token、保存最新 refresh token，並清除訪客狀態。
6. 選「以訪客繼續」後記錄本次訪客選擇，完成為 `None`。

禁止套件直接自動登入而略過選擇對話框；需要恢復登入時由整合層決定是否呼叫 `login()`。不把 ID token 當成 API token。

每次成功登入、恢復 session 或更新 access token 後，讀取套件的最新 refresh token 並同步保存，涵蓋 refresh token rotation。

## 保存與舊版相容

延續舊版使用 `config.conf["WordBridge"]["settings"]["api_key"]["Coseeing"]` 保存 refresh token 的方式，以便使用既有保存值。這個欄位供整合層使用，不作為可編輯 API key 顯示。

Access token 僅保存在記憶體。Refresh token 沿用 NVDA 設定儲存方式，不新增加密或 Windows Credential Manager 儲存機制；此限制與舊版相同。設定讀写與必要的持久化遵循 NVDA 設定機制，不修改其他 provider 的值。

伺服器明確拒絕 refresh token 時清除失效的保存值，避免每次重試同一個失效憑證；網路或暫時性服務錯誤不得清除它。舊版 Google 或不同 issuer/client 發出的 token 不保證可沿用，被新 SSO 拒絕時走正常重新登入選擇。

## 觸發時機與 UI

目前程式以 `execution_channel == "Coseeing"` 表示使用者選擇 Coseeing 服務。啟動時讀取並正規化已保存的選擇，再決定是否觸發驗證。

`GlobalPlugin.__init__` 完成基本初始化後排程驗證工作。設定面板 `onSave` 先寫入新選擇，再於新選擇為 Coseeing 時重新評估驗證；這也涵蓋 NVDA 設定介面的「套用」儲存路徑。只切換 provider 下拉選單或取消設定不觸發登入。

重新評估時會解除本次訪客選擇；若已有有效登入狀態則直接取得 token，不強制重新登入。若之前流程仍在執行，合併工作，避免重複開啟視窗。

Coseeing 設定區移除帳號、密碼輸入控制項，改為說明使用瀏覽器登入，並可選擇訪客。原有帳號密碼設定值不再用於請求。所有對話框與使用者通知透過 wx 主執行緒執行，文字沿用 addon 翻譯機制。

## 請求整合

校對 `/proofreader` 與回饋 `/feedback` 共用同一個 token 取得入口。

- 結果為 access token：加入 `Authorization: Bearer <access_token>`。
- 結果為 `None`：省略 `Authorization`，不可送出空的 `Bearer `。
- 驗證以錯誤完成：通知使用者並停止該次請求，不自動當作訪客送出。

校對背景工作可等待驗證結果。回饋流程目前在 UI 回呼中處理請求，需將驗證與 HTTP 請求移至背景，再切回主執行緒顯示結果。

訪客能否使用各 API 仍由伺服器決定；不因用戶端省略 header 而假設伺服器必定接受。401 等錯誤應顯示符合 SSO／訪客情境的訊息，不再要求檢查舊帳號密碼。此變更不新增 API 401 自動重送。

## 錯誤處理與生命週期

使用套件公開錯誤類型及 `code` 區分 refresh token 失效與網路等錯誤，不比對例外訊息文字。

網路中斷、服務錯誤、設定錯誤、token 驗證錯誤、登入取消或 callback 超時，都應結束本次工作並提供可理解的通知，不無限重試、不自動反覆開啟瀏覽器，也不把錯誤當成使用者已選擇訪客。下一次明確觸發可重新嘗試。

關閉選擇對話框若沒有明確選擇訪客，視為取消當次驗證。啟動或儲存設定時的驗證失敗不妨礙 addon 載入或設定保存。

Addon `terminate` 時取消待處理 UI 工作與驗證流程，關閉共用 auth client 並釋放 callback listener/executor；避免關閉後的回呼再次操作 UI 或覆寫狀態。已取得的新 refresh token 在成功時即保存，不只依賴關閉時保存。

記錄錯誤類型、階段與錯誤碼即可，不記錄 token、authorization code 或完整含敏感參數的登入 URL。

## 預計修改位置

- `lib/coseeing_auth.py`：共用驗證流程、訪客狀態、保存協調與生命週期。
- `__init__.py`：啟動／關閉掛鉤、校對與回饋 header、背景回饋工作及驗證錯誤通知。
- `dialogs.py`：Coseeing 登入說明、選擇對話框及設定儲存觸發。
- `configManager.py`：依最終整合需要調整原帳號密碼保存呼叫與選擇判斷。
- `tests/`：新增驗證整合與觸發行為測試。
- 套件打包設定：確認 `coseeing_auth` 的必要依賴均隨 addon 提供；若缺少則在實作時補齊。

不移植舊版 OIDCManager 實作，不新增註冊、綁定帳號、登出 UI 或手動登入快捷鍵，也不調整 SSO 伺服器與 API 協定。

## 驗收與測試

自動測試使用替代 auth client、設定儲存與 UI callback，驗證以下可觀察行為，不開啟真實瀏覽器或使用真實 token：

1. 沒有 refresh token 時顯示一次選擇；選登入可取得 access token 並保存 refresh token。
2. 有效 refresh token 可恢復 session，無需選擇對話框或瀏覽器。
3. Refresh token 明確失效時清除保存值並顯示登入／訪客選擇；網路失敗則保留保存值。
4. 成功更新 token 後保存輪替的 refresh token。
5. 訪客期間多次校對／回饋均不再詢問，且 header 不含 `Authorization`。
6. 重啟或 Coseeing 設定儲存後重新評估訪客狀態；其他 provider 不觸發驗證。
7. 已登入的校對／回饋請求使用有效 access token，並在需要時先更新。
8. 重疊呼叫只產生一個選擇視窗／登入流程；取消、錯誤與關閉能讓等待者結束。
9. 驗證錯誤不送出原本待執行的 API 請求。
10. 移除 Coseeing 帳密控制項後，其他 provider 的憑證保存與設定選擇仍正常。

執行與變更相關的既有測試及打包／匯入檢查。Windows NVDA 手動驗收包含：啟動與設定儲存的對話框可及性、登入時 UI 保持可操作、真實瀏覽器 callback、登入後校對／回饋，以及等待登入時關閉 addon 能釋放 callback port。若實作環境無法執行 NVDA，交付時明確列出尚待手動驗收的項目。
