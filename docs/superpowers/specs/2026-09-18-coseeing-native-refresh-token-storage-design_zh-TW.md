# Coseeing 原生重新整理權杖儲存

## 目標

透過隨附的 `coseeing_auth` 儲存 API，將 Coseeing 的重新整理權杖儲存在
Windows 認證管理員，而非將 NVDA 設定檔當作有效權杖儲存區。

## 範圍

這項變更適用於 Windows 上的 WordBridge NVDA 附加元件。隨附的
`coseeing_auth` 套件已提供 `WindowsCredentialStore` 及其重新整理權杖
生命週期；本工作將該 API 整合至 WordBridge，而不修改其實作。

認證目標名稱必須完全為：

```
org.coseeing.wordbridge/refresh
```

不進行舊版權杖遷移。本變更既不讀取也不修改既有的
`config.conf["WordBridge"]["settings"]["api_key"]["Coseeing"]` 值。

## 設計

### 原生儲存區接線

`_NvdaAuthAdapter.client_factory()` 將建立：

```python
WindowsCredentialStore("org.coseeing.wordbridge/refresh")
```

並在建立 `CoseeingAuthClient` 時，以 `refresh_token_store` 傳入。client
仍會包裝於 `FutureAuthClient` 中，以維持既有的 UI 執行緒邊界。

### 工作階段流程

`CoseeingAuthSession` 不再接收讀取或儲存重新整理權杖的回呼，且在取得
存取權杖後不再呼叫 `get_refresh_token()`。

對於尚未備妥的工作階段，它將呼叫 `restore_saved_session()`：

- 還原成功的結果會將工作階段標示為已備妥，並繼續取得存取權杖。
- `None` 結果表示沒有原生認證資料，接著進入既有的登入或以訪客身分繼續提示。
- 儲存或還原失敗時，沿用既有的失敗處理／通知流程。

互動式登入或權杖重新整理後，`coseeing_auth` 會自行保存新的或輪替後的
重新整理權杖；其登出操作會刪除原生認證資料。WordBridge 僅繼續負責 UI
相關事務：提示使用者登入或以訪客身分繼續、將工作派送至 NVDA 的 UI 執行緒、
關閉對話方塊，以及呈現一般性的失敗通知。

### 設定介面與設定檔

Coseeing 專用的「重新整理權杖」欄位改為文字標示為 `clean` 的按鈕。其他提供者
的 API 金鑰控制項維持不變。

設定面板開啟時，僅在
`WindowsCredentialStore("org.coseeing.wordbridge/refresh").load()` 回傳權杖時
啟用按鈕。這是本機存在性檢查，而非網路驗證：沒有權杖或儲存區讀取失敗時，按鈕
維持停用。如此可避免設定介面依賴 SSO 是否可用，並仍允許清除本機儲存但已過期或
遭撤銷的認證資料。

選取 `clean` 時執行 `logout_local()`。此操作會清除 client 記憶體中的權杖狀態和
Windows 認證管理員的認證資料，然後關閉並重設 WordBridge 的驗證單例。成功時立即
停用按鈕；刪除失敗時保留啟用狀態，並沿用既有的一般驗證失敗通知流程。僅為回應
手動編輯權杖而存在的變更偵測／重設行為則會移除。

成功清除後，若使用者儲存設定面板且選用的執行通道仍為 Coseeing，仍會啟動
Coseeing 驗證。因為沒有原生認證資料，將再次顯示既有的登入或以訪客身分繼續提示。

本版本保留既有的 `api_key["Coseeing"]` 設定值，不會由新的驗證流程顯示、
載入、儲存、清除或遷移。

## 錯誤處理

`TokenPersistenceError` 仍可透過既有的驗證工作階段失敗流程觀察到。通知與
記錄使用穩定的錯誤中繼資料，且不得包含權杖值。若刪除儲存資料失敗，須回報為
驗證失敗；WordBridge 不得將其視為登出成功。

## 測試

更新驗證工作階段與 NVDA 面板測試，以涵蓋：

- 使用 `org.coseeing.wordbridge/refresh` 建立 `WindowsCredentialStore`，
  並將其注入 `CoseeingAuthClient`；
- 原生儲存區為空（`restore_saved_session() -> None`）時，進入既有的
  登入／訪客提示；
- 已還原的原生工作階段在未使用設定檔權杖回呼或 `get_refresh_token()` 的情況下，
  繼續取得存取權杖；
- 僅在存在原生認證資料時啟用 `clean` 按鈕；
- 本機登出清除原生認證資料與記憶體工作階段、成功時停用按鈕，以及刪除失敗時
  保持啟用狀態；
- 清除後儲存 Coseeing 通道設定時，再次開啟登入或以訪客身分繼續提示；
- 持續以一般性方式處理儲存錯誤，且不在記錄中留下權杖。

套件封裝測試也應納入新的 `coseeing_auth/storage` 模組，確保發行的附加元件包含
Windows 介接器。

## 非目標

- 匯入、刪除或以其他方式修改 NVDA 設定檔中歷史遺留的明文 Coseeing 值。
- 新增 Windows 以外平台的明文備援儲存方式。
- 修改 Coseeing 登入對話方塊、端點設定或提供者選取行為。
