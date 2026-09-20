# R03：內嵌依賴隔離

## 目標

讓 WordBridge 停止修改整個 NVDA 程序共用的 Python 匯入狀態。

NVDA 把所有 add-on 跑在同一個 CPython 程序裡。WordBridge 目前把自己的
`package/` 目錄插到 `sys.path[0]`，再把宿主已載入的 `cryptography.*` 從
`sys.modules` 刪掉，好讓自己較新的副本勝出。這兩個效果都是全程序範圍的：
在 WordBridge 之後才匯入 `cryptography` 的 add-on 會拿到 WordBridge 的副本，
而 `package/` 底下每一個頂層名稱 —— `pypinyin`、`zhon`、`hanzidentifier`、
`chinese_converter`、`coseeing_auth`、`jwt` —— 都變成全域可匯入。

`2026-09-20-p0-fixes` spec 只把 R03 規劃為可行性探測。其 decision rule 選出的是
**方案 B：私有前綴匯入沙箱**。本文件就是該探測要解鎖的實作設計。

## 已確立的事實

在 NVDA 2026.1（CPython 3.13.13、win_amd64）上由 `docs/superpowers/spikes/` 的
兩支 probe 腳本量測，另加上針對相同依賴版本在 NVDA 之外的量測。本節全部是證據，
不是假設。

**probe 的可信範圍。** probe v1 是在 add-on 啟用的狀態下執行的，所以當時
`sys.modules["cryptography"]` 已經是 WordBridge 的 bundle：`__init__.py` 在
plugin 載入時匯入 `lib.coseeing_auth`，該模組會刪除宿主的項目並把 bundle 放到
`sys.path` 最前面。因此 v1 的 probe 0 盤點到的是我們自己的 bundle，probe 2 則是
把 bundle 換成 bundle 自己，使其「方案 A 可行」的結論成為假陽性。
**v1 只有 probe 1 成立。** probe v2 改為直接從磁碟讀取 NVDA 的副本，不受影響。

1. NVDA 出的是 **cryptography 48.0.1**，精簡到 `library.zip` 裡 54 個項目，
   而 `cryptography.hazmat.bindings._rust.pyd` 以攤平命名放在 zip 旁邊的 NVDA
   程式目錄中。add-on 內嵌的是 **cryptography 50.0.1**。
2. auth stack 會用到 55 個 `cryptography.*` 模組，NVDA 提供其中 49 個，缺 6 個：
   `hazmat.primitives.kdf` 及其 `concatkdf`、`hkdf`、`pbkdf2` 子模組、
   `hazmat.primitives.keywrap`、`hazmat.primitives.padding`。
3. 這 6 個全都是 JWE 專用 —— AES key wrap、PKCS7 對稱填充、PBES2 與 ECDH-ES
   金鑰衍生。WordBridge 驗證的是 RS256 ID token，屬於 JWS，一個都用不到。
   它們被拉進來是因為 `authlib.integrations.base_client` 匯入 joserfc，而
   joserfc 在 import 時就註冊整套演算法。逐步量測結果：單獨
   `import jwt`（PyJWT 2.14.0）只會用到 NVDA 提供的那 49 個；匯入任何
   `authlib.integrations.*` 模組就正好多出這 6 個。`coseeing_auth/oidc.py`
   必需的 `OAuth2Session` 同樣會拉進來，所以這個缺口無法靠調整匯入順序迴避。
4. **authlib 不能拿掉。** `package/coseeing_auth/` 是其他 Coseeing 專案也在用的
   共用函式庫，且規劃中的功能仍依賴 authlib。移除它是跨專案決策，不是
   WordBridge 內部的重構。
5. bundle 的 `_rust.pyd` 可以在私有模組名稱下載入，而宿主自己的 `_rust` 事後
   仍可匯入 —— PyO3 容許同一程序內存在兩份實例。
6. cryptography 50.0.1 的 `_rust` 把 `asn1`、`exceptions`、`ocsp`、`_openssl`
   以純屬性暴露，不註冊任何絕對 `sys.modules` 名稱。因此在私有前綴下載入它
   不可能污染 `cryptography.hazmat.bindings._rust.*`。
7. 內嵌的 `cryptography`、`authlib`、`joserfc`、`jwt` 裡，
   `importlib.import_module` 與 `__import__(` 的出現次數是 **0**。所有跨套件
   引用都是靜態 `import` 敘述。
8. 宿主的 `requests`、`urllib3`、`certifi`、`idna`、`cffi`、
   `charset_normalizer`、`pycparser` 今天本來就勝出 —— `sys.path` 插入無法取代
   已預載的模組 —— 所以 bundle 內這些套件的副本在生產環境從未被載入過。
9. NVDA 的 Python 移除了標準庫的 `secrets`。`package/secrets.py` 是它的逐字
   副本，用途是補這個缺口，而不是遮蔽宿主提供的模組。

### 作廢的既有結論

`review-claude-2.md` 的 T2 需求 1 —— 「刪除 `package/secrets.py`（Python 3.6+
已內建）」—— 在 NVDA 的環境下是**錯的**，由事實 9 作廢。照做會直接弄壞認證：
`coseeing_auth/client.py` 與 `coseeing_auth/oidc.py` 都 `import secrets`，
內嵌套件裡另有 7 處。該檔案保留；本設計只是把它搬家並改為條件式註冊。

## 範圍

未特別註明的路徑皆相對於 `addon/globalPlugins/WordBridge/`。

範圍內：

- 新增 `lib/vendor.py` —— 沙箱本體。
- `__init__.py` —— 移除 `sys.path.insert(0, PACKAGE_PATH)`；把安裝沙箱列為第一
  個動作；`hanzidentifier` 的匯入改走沙箱。
- `lib/coseeing_auth.py` —— 移除 `del sys.modules[...]` 迴圈與
  `_prepare_auth_dependencies()`；依賴匯入改走沙箱；在認證半邊不可得時仍可匯入。
- 另外 4 個檔案、6 行 import 改走前綴：`lib/tasks/typo/prompt.py`（1）、
  `lib/tasks/typo/utils.py`（2）、`lib/tasks/typo/text_policy.py`（1）、
  `lib/text/chinese.py`（2）。連同 `__init__.py`（1）與
  `lib/coseeing_auth.py`（5），共 6 個檔案、12 行。
  `package/hanzidentifier.py` 的 `from zhon import cedict` 屬於 vendored 程式，
  不需修改 —— 沙箱會轉址。
- `package/secrets.py` 搬到 `package/_stdlib_gapfill/secrets.py`。
- `tests/conftest.py`、`tests/test_coseeing_auth_bundle.py`，以及新增測試。
- `docs/superpowers/spikes/` 底下的自我檢查腳本。
- `package/coseeing-auth-dependencies.md` —— 記錄三類分類。

明確**不在**範圍內：

- **修改 `package/coseeing_auth/` 原始碼。** 它與其他專案共用；其匯入不需修改
  即可透過沙箱正常運作。
- **把 auth stack 改為延遲載入。** 今天 `lib/coseeing_auth.py` 在 plugin 載入時
  就匯入 authlib。沙箱會讓延後變得容易，R16 也想要，但在同一次變更裡同時改
  載入*時機*與載入*路徑*，會讓「B 有沒有破壞既有行為」無法回答。留給 R16。
- **精簡 bundle。** 事實 8 暗示 bundle 裡有數個套件是死重。量測並移除屬於 R15，
  而且它需要本設計的分類清單作為輸入。
- 從 NVDA 的 `systemConfig` 目錄移除過時的 `WordBridge(include-auth)` 安裝 ——
  那是維護者的操作步驟，列在人工驗證項下。

## 驗證限制

作者的開發主機是 Linux；Windows 與 NVDA 的驗證由維護者執行。以下每項測試標記為
**[auto]**（可在 Linux 上以 `tests/` 既有的 NVDA stub 模式執行）、
**[win]**（Windows 發佈前關卡）或 **[manual]**。

## 前置作業

**probe v3 必須在實作前執行。** 事實 9 指出 `secrets` 是 NVDA 移除的標準庫模組
之一，但不可假設它是唯一的一個。該 probe 會列出 auth stack 與本地校正路徑匯入的
所有標準庫模組，與 NVDA 的 `library.zip` 及程式目錄比對，得出完整的第一類清單。
拿猜測的清單去實作，等於一次一個生產環境故障地把其餘的找出來。

## 設計

### 三個分類

WordBridge 需要的每個模組都恰好落在三類之一，分類決定它如何解析。清單是明確列舉
的，不是執行期從「剛好存在什麼」推導出來的。

**第一類 —— NVDA 移除的標準庫模組。** 目前已知：`secrets`；完整清單來自
probe v3。這類以**正規名稱**在全域解析，因為共用的 `coseeing_auth` 套件與內嵌的
第三方套件都把它們當成一般標準庫來匯入，無法加前綴。

註冊方式是**條件式**：先試宿主，只有在宿主沒有時才註冊我們的副本。如此一來，將來
若 NVDA 把 `secrets` 加回去，勝出的是新的標準庫，而不是被我們凍結的舊副本遮蔽 ——
後者會把「補缺口」變成本工作正要消除的那種遮蔽行為。

來源從 `package/` 搬到 `package/_stdlib_gapfill/`。除了讓兩類在目錄結構上分開，
這也解決一個歧義：`package/` 是沙箱的根之一，補丁檔若留在該層，會同時以
`_wb_vendor.secrets` 被看見。

**第二類 —— 必須來自我們的第三方套件。** `cryptography`、`authlib`、`joserfc`、
`jwt`、`coseeing_auth`、`pypinyin`、`zhon`、`hanzidentifier`、
`chinese_converter`。這類**只**在 `_wb_vendor.` 前綴下解析，絕不以全域頂層名稱
出現。

`cryptography` 是因為事實 2；其餘是因為宿主沒有副本，而留在全域就會佔用一個共用
的頂層名稱 —— `jwt` 尤其明顯。`coseeing_auth` 則是因為它必須看到沙箱版的 authlib。

**第三類 —— 必須來自宿主的套件。** `requests`、`urllib3`、`certifi`、`idna`、
`charset_normalizer`、`cffi`、`_cffi_backend`、`pycparser`。

這裡刻意**不提供退回我們 bundle 副本的機制**。事實 8 顯示宿主副本本來就勝出、
我們的從未被執行過。如果將來 NVDA 拿掉 `requests`，正確的反應是發出明確且大聲的
失敗、指出宿主環境變了 —— 而不是靜默改用一份未經測試、可能過期的 bundle 副本。

### 架構

`lib/vendor.py` 是 WordBridge 自己的模組，職責只有安裝一個私有命名空間。

**一個全域名稱。** `sys.modules` 裡的 `_wb_vendor` 是不可再縮的足跡：前綴模組
必須能被匯入機制找到。本次變更之後，WordBridge 在 NVDA 程序中的全部殘留就是這個
明顯私有的名稱，外加第一類的條件式註冊。其餘一律歸零。

**用 `__path__` 取代自訂搜尋邏輯。** `_wb_vendor.__path__` 存放實際存在的根目錄：
`package/` 與 `package/_coseeing_auth_deps/<runtime>/`。於是
`import _wb_vendor.cryptography` 由標準的 `PathFinder` 解析，子模組再沿
`_wb_vendor.cryptography.__path__` 自然往下走。本設計沒有任何程式碼在決定檔案
位置。

**一個只回應自家前綴的 finder。** `sys.meta_path` 上的單一 `MetaPathFinder` 對
所有不以 `_wb_vendor.` 開頭的名稱回傳 `None`，因此不可能攔截宿主或第三方的匯入。
它把定位工作委派給標準機制，只為一個目的包裝回傳的 loader：在 `exec_module` 之前
把我們的 `__import__` 注入該模組的 `__builtins__`。原生擴充的 loader 不包裝 ——
事實 6 顯示 `_rust` 不需要任何 Python 名稱。

### 解析規則

注入的 `__import__` 有三條規則：

1. **相對匯入**（`level > 0`）原樣委派給真正的 `__import__`。它們本來就已經在
   前綴樹內解析。
2. **第二類的頂層名稱**改寫為 `_wb_vendor.<name>` 後再委派。
3. **其餘一切**原樣委派，由宿主回答。

規則 2 帶著本設計唯一真正的陷阱：回傳值。`import a.b` 必須回傳 `a`，而
`from a.b import c` 必須回傳 `a.b`。加上前綴後，真正的 `__import__` 會分別回傳
`_wb_vendor` 與 `_wb_vendor.a.b`，所以兩種形式都必須在回傳前從 `sys.modules`
還原。弄錯會把 `cryptography` 綁到 `_wb_vendor` 這個命名空間物件上，而症狀會出現
在離成因很遠的地方。

這段是純 Python，不依賴 NVDA 或 Windows，因此可以在 Linux 上針對捏造的套件完整
測試。測試的力氣要花在這裡。

由於攔截點存在於每個模組自己的 globals 中，它對**稍後在呼叫時才發生的延遲匯入**
依然有效。cryptography 大量使用延遲匯入；這正是方案 A 無法保證、也是選擇 B 的
理由。

事實 7 確立規則 2 在目前的依賴集合中沒有盲區：沒有動態匯入可漏。未來某個依賴版本
若新增動態匯入，會靜默掉回宿主副本 —— 這就是為什麼測試 12 斷言模組來源，而不是
信任機制本身。

### 呼叫端

6 個檔案中的 12 行 import 變成一般的前綴匯入，例如
`from _wb_vendor.pypinyin import Style, lazy_pinyin`。不引入 accessor 函式或
間接層：前綴出現在每個呼叫點上，可讀也可 grep。`__init__.py` 的
`sys.path.insert` 與 `lib/coseeing_auth.py` 的 `del sys.modules[...]` 迴圈刪除。

### 生命週期

**安裝順序是硬約束。** 沙箱必須在任何 `from _wb_vendor.X import ...` 執行前就
安裝完成，因此它是 `__init__.py` 的第一個敘述。測試會直接匯入
`lib/tasks/typo/prompt.py` 這類模組而繞過 `__init__.py`，所以 `tests/conftest.py`
要以 fixture 安裝沙箱。這也讓測試走真正的機制，而不是繞過它。

**安裝一次，永不卸載。** `terminate()` 不拆除沙箱。原生擴充無法可靠卸載 ——
`_rust.pyd` 一旦載入就常駐 —— 拆掉一半比整個留著更糟。常駐的沙箱也讓 NVDA 的
「重新載入外掛」便宜且一致。

誠實的代價：add-on 停用後，`_wb_vendor` 會留在 `sys.modules` 裡直到 NVDA 重啟。
這個殘留無法避免，但遠小於現況 —— 現況是一個被替換的 `cryptography`、一筆被插入
的 `sys.path`，以及 6 個全域頂層名稱。

**runtime 目錄的選擇。** 現行程式檢查 `sys.platform == "win32"` 後就硬寫
`py313-win_amd64`。改為由執行中的直譯器推導 key —— Python 次版本、平台、指標
大小 —— 再確認該目錄存在。推導不出 key 或目錄不存在屬於降級路徑，不是例外。

### 錯誤處理

具約束力的契約：**認證半邊不可得，絕不能阻止 add-on 載入或破壞本地校正。**

這正是現況的缺陷。`_prepare_auth_dependencies()` 在 Windows 上找不到 deps 目錄
時會丟 `ImportError`，而 `lib/coseeing_auth.py` 是由 `__init__.py` 以模組層級
匯入的，所以一個缺失或不相容的 bundle 會讓整個 add-on 失效 —— 連完全不碰網路的
本地校正一起陪葬。

把「不可得」變成狀態而非例外：

- 安裝沙箱永不丟例外。它記錄結果，`_wb_vendor.__path__` 只納入實際存在的根目錄。
- `lib/coseeing_auth.py` 無條件保持可匯入。它在模組層級匯入的錯誤類別
  （`OAuthError`、`ClientClosedError`、`RestoreError`、`TokenUnavailableError`、
  `TokenValidationError`）在真正的類別不可得時改綁私有替身例外類別。替身永遠不會
  被拋出，但檔案中每一處 `except ClientClosedError:` 仍然成立，因此 R02 剛加固過
  的 `terminate()` 路徑不需要任何 `None` 判斷。
- 模組公開 `AUTH_AVAILABLE`。`start_coseeing_auth()` 與
  `get_coseeing_access_token()` 在不可得時拋出明確的領域錯誤，使用者選擇 Coseeing
  通道時由 UI 回報。`shutdown_coseeing_auth()` 變成 no-op，讓 `terminate()` 的
  形狀完全不變。

四種失敗必須可分辨，因為處置不同：

| 失敗 | 訊息必須說明 |
| --- | --- |
| runtime key 推導不出或目錄不存在 | 偵測到的直譯器／平台 |
| bundle 存在但模組載入失敗 | 哪個模組，以及例外型別 |
| 第三類的宿主套件消失 | 是**宿主**環境變了 |
| 沙箱重複安裝 | 不需訊息 —— 這是 no-op |

日誌記錄模組名稱與例外型別，絕不記錄 token、API key 或使用者文字。

## 測試

**Linux 自動化**

1. [auto] 經 shim 的 `import a.b` 回傳 `a`；`from a.b import c` 回傳 `a.b`；
   兩者綁定的都是沙箱模組，而非命名空間物件。
2. [auto] 沙箱套件內的相對匯入在前綴內解析，且不被改寫。
3. [auto] 沙箱程式匯入第三類名稱時解析到宿主副本。
4. [auto] 寫在沙箱模組函式內的延遲匯入，在該函式稍後被呼叫時仍解析到沙箱。
   這是 B 的定義性質。
5. [auto] `_wb_vendor.__path__` 恰好包含實際存在的根目錄；重複安裝是 no-op，
   不會產生第二個命名空間。
6. [auto] 分類清單不會腐爛：兩個根目錄中可匯入的頂層名稱 —— 排除
   `_stdlib_gapfill`、runtime bundle 目錄本身、`__pycache__` 與非模組檔案 ——
   恰好等於第二類 ∪ 第三類，因此新增 bundle 套件卻未分類會讓測試失敗。
7. [auto] 第一類為條件式註冊 —— 宿主模組存在時不註冊我們的；不存在時以正規名稱
   註冊我們的。
8. [auto] 模擬 plugin 載入後，`sys.path` 未被修改，且全域 `sys.modules` 只多出
   `_wb_vendor` 與（若有的）第一類註冊。
9. [auto] 移除 runtime 目錄後：plugin 仍可匯入、本地校正路徑可用、
   `AUTH_AVAILABLE` 為 false、Coseeing 入口拋出領域錯誤、
   `shutdown_coseeing_auth()` 為 no-op。
10. [auto] 認證半邊不可得時，`lib/coseeing_auth.py` 仍可乾淨匯入，且其替身錯誤
    類別讓每一處 `except` 子句維持有效。

**Windows 發佈前關卡**

11. [win] `test_windows_bundle_imports_dependencies_from_addon_package` 改寫為
    沙箱契約：第二類的 9 個套件解析自兩個根目錄下的 `_wb_vendor.*`。
12. [win] 第三類的 8 個套件解析自 NVDA，且第二類的任何頂層名稱 ——
    `cryptography`、`authlib`、`joserfc`、`jwt`、`coseeing_auth`、`pypinyin`、
    `zhon`、`hanzidentifier`、`chinese_converter` —— 都不存在於全域
    `sys.modules`。
13. [win] `test_runtime_bundle_contains_resolved_package_versions` 與
    `test_runtime_bundles_contain_native_backend_for_each_supported_runtime`
    仍通過，並配合搬遷後的 gap-fill 目錄更新。

**自我檢查腳本**

14. [manual] 一支給 NVDA Python Console 的腳本，形式沿用既有 probe：在 add-on
    載入前後快照 `sys.modules` 與 `sys.path`，回報差異，並回報三類各自實際解析
    到的來源。這是唯一能在「真實 NVDA、有其他 add-on 同時存在」的環境下證明未
    污染的工具。維護者安裝新版後執行一次並貼回報告。

**人工驗證**

15. [manual] 在另外安裝一個同樣使用 `requests` 與 `cryptography` 的 add-on 的
    情況下，雙方都正常運作，且 WordBridge 載入後宿主 `cryptography` 的物件識別
    未改變。
16. [manual] 在 Windows/NVDA 上完成登入、token 換發、登出與停用 add-on 的完整
    生命週期。
17. [manual] 執行 15 與 16 之前，先移除 NVDA `systemConfig` 目錄下過時的
    `WordBridge(include-auth)` 副本。它早於 `_coseeing_auth_deps`，自帶一份
    `cryptography`，並會做自己的 `sys.path` 注入，會使結果無法解讀。

## 不在範圍

已列於上方**範圍**一節：`package/coseeing_auth/` 原始碼變更、auth stack 延遲載入
（R16）、bundle 精簡（R15），以及移除過時的 `systemConfig` 安裝。
