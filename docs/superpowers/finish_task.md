# R03 匯入隔離 — 完成報告

**分支：** `r03-import-isolation`
**基準：** `c45247e`（分支上原有的 spec、plan、probe v2）
**HEAD：** `9109a82`
**新增 commit：** 28 個，26 個檔案，+2444 / −197
**執行方式：** Subagent-Driven Development。實作 `claude-sonnet-5`，審閱 `claude-opus-5`，八個 task 各自經過「實作 → review → fix loop → scoped re-review」直到 clean，最後再做一次 whole-branch review 與單一 fix wave。

---

## 這個分支做了什麼

NVDA 讓所有 add-on 共用同一個 CPython 行程。在此之前，WordBridge 把自己的 `package/` 目錄插到全域 `sys.path[0]`，並且從 `sys.modules` 刪掉宿主預載的 `cryptography.*`，好讓自己較新的副本勝出。這兩個動作都是行程全域的：在 WordBridge 之後才 `import cryptography` 的其他 add-on 會拿到 WordBridge 的副本，而 `package/` 底下每一個頂層名稱（`pypinyin`、`zhon`、`hanzidentifier`、`chinese_converter`、`coseeing_auth`、`jwt`）都變成全域可匯入。

本分支改用私有的 `_wb_vendor` 匯入沙箱取代上述兩個機制。

**核心主張已由最終審閱以實測驗證，而非僅憑閱讀推斷：** 在真實 bundle 上安裝真實沙箱後測量差異 —

- 本地校正半邊（add-on 載入時即 eager 匯入）：載入 38 個前綴模組，新增的非 stdlib 頂層 `sys.modules` key **恰好只有 `_wb_vendor`**，`sys.path` 逐位元組不變，category 2 全域洩漏為 `[]`，38 個模組全部帶有被改寫過的 `__import__`。
- 認證半邊（強制掛入 deps root）：85 個前綴模組，零洩漏，零未沙箱化模組，且 `requests` 解析到**宿主**副本而非 bundled 副本 —— 端對端證明 rule 3 的委派正確。
- `package/hanzidentifier.py` 裡那行 bare `from zhon import cedict` 被透明改寫，`has_chinese("測試")` 回傳 `True` 且沒有留下全域 `zhon` key。
- 舊機制已消失：add-on 程式碼中 `sys.path` 只剩註解，`del sys.modules` 完全不存在。

殘留精確地說是**一個 `sys.modules` key 加一個 `sys.meta_path` entry**（finder 本身，spec 已揭露），以及在宿主缺少該模組時才註冊的 category 1 gap-fill。

---

## 架構

| 檔案 | 角色 |
| --- | --- |
| `addon/globalPlugins/WordBridge/lib/vendor.py` | **新增。** 整個沙箱：三份分類清單、`__import__` shim、finder/loader 配對、runtime root 推導、`install()`、條件式 stdlib gap-fill。 |
| `addon/globalPlugins/WordBridge/package/_stdlib_gapfill/secrets.py` | 由 `package/secrets.py` 移入。category 1 來源，與 category 2 實體分離。 |
| `addon/globalPlugins/WordBridge/__init__.py` | 第一個動作即安裝沙箱；移除 `sys.path.insert`；認證不可用時記錄診斷。 |
| `addon/globalPlugins/WordBridge/lib/coseeing_auth.py` | 移除 `_prepare_auth_dependencies()` 與 `del sys.modules` 迴圈；新增 `AUTH_AVAILABLE`、placeholder 例外類別、不可用狀態的進入點。 |
| `lib/tasks/typo/{prompt,utils,text_policy}.py`、`lib/text/chinese.py` | 匯入改走前綴。 |
| `tests/test_vendor_sandbox.py` | **新增**，813 行。Linux 上可證明的一切。 |
| `tests/conftest.py` | 為直接匯入 add-on 模組的測試安裝沙箱；`package/` 不再進入 `sys.path`。 |
| `tests/test_coseeing_auth_bundle.py` | Windows 出版前關卡，改寫為沙箱契約。 |
| `docs/superpowers/spikes/2026-09-20-r03-stdlib-gap-probe.py` | **新增。** probe v3。 |
| `docs/superpowers/spikes/2026-09-20-r03-selfcheck.py` | **新增。** 安裝後自我檢查。 |

**三分類**（`lib/vendor.py` 內為權威來源，`package/coseeing-auth-dependencies.md` 有對照表）：

1. **NVDA 移除的 stdlib**（目前已知只有 `secrets`）— 以**正規名稱**全域註冊，且**僅在宿主沒有時**才註冊，未來 NVDA 補回即自動讓位。
2. **必須由我們提供**（九個，僅前綴可見）：`cryptography`、`authlib`、`joserfc`、`jwt`、`coseeing_auth`、`pypinyin`、`zhon`、`hanzidentifier`、`chinese_converter`。
3. **必須由宿主提供**（八個，**刻意不提供 fallback**）：`requests`、`urllib3`、`certifi`、`idna`、`charset_normalizer`、`cffi`、`_cffi_backend`、`pycparser`。

---

## 新增的 commit

| # | Commit | 說明 |
| --- | --- | --- |
| 1 | `df286de` | spike: add R03 probe for NVDA's removed stdlib modules |
| 2 | `9d2d80b` | fix: rewrite R03 stdlib gap probe to measure in-process, off disk |
| 3 | `a33b3a5` | fix: eliminate needed-set false positives in R03 stdlib gap probe |
| 4 | `ce56fe8` | fix: keep add-on-shimmed names in the needed-set despite alias status |
| 5 | `af11fc8` | feat: add the vendored-import rewriting shim |
| 6 | `4c45c1f` | feat: install the vendored-dependency namespace and its finder |
| 7 | `f635552` | fix: self-heal half-installed sandbox, honest docstrings, cover extension/runtime-key gaps |
| 8 | `c59d116` | feat: classify vendored packages and gap-fill NVDA's removed stdlib |
| 9 | `4850607` | fix: close gap-fill classification gap and gapfill-namespace leak (review round 1) |
| 10 | `08b3e05` | fix: block every namespace portion under the vendor prefix, not just one name (review round 2) |
| 11 | `725e214` | fix: resolve Coseeing auth dependencies through the sandbox |
| 12 | `6496bb6` | fix: close review round-1 gaps in the Coseeing auth sandbox routing |
| 13 | `dc64255` | fix: stop putting the add-on's package directory on sys.path |
| 14 | `2fd61ac` | fix: close review round-1 gaps in Task 6's import-isolation change |
| 15 | `a83d4d1` | fix: make the sandbox-install ordering test actually assertable |
| 16 | `abe0e1f` | test: assert the sandbox contract on the real Windows bundle |
| 17 | `d41ea67` | fix: close review round-1 gaps in Task 7's Windows sandbox gate |
| 18 | `a3a193c` | fix: make the HOST_ONLY shadow check non-vacuous for unloaded names |
| 19 | `9ef5ee0` | spike: add R03 post-install self-check |
| 20 | `e14b10a` | fix: close review round-1 gaps in Task 8's self-check |
| 21 | `45732af` | fix: close review round-2 gap in Task 8's self-check discriminator |
| 22 | `12b7594` | fix: correct R03 spike scripts for the post-sandbox import graph |
| 23 | `b6b40f5` | fix: make install_stdlib_gapfill() never raise; fix namespace spec locations |
| 24 | `cf42fd8` | fix: report Coseeing-unavailable to the UI; distinguish unavailable_reason() rows |
| 25 | `5ba81de` | fix: install the sandbox in test_sso_configuration_matches_approved_demo |
| 26 | `5271956` | fix: exclude __pycache__ from the packaged nvda-addon bundle |
| 27 | `b6d0d5d` | test: close remaining R03 review gaps |
| 28 | `9109a82` | fix: translate auth-unavailable string, fix stale privacy comment, close vendor sandbox test gap |

Commit 1–21 是八個 task 的實作與其 review fix round；22–27 是最終 whole-branch review 的單一 fix wave；28 是交付前最後三項修正。

---

## 測試狀態

非網路回歸關卡：

```
python3 -m pytest tests/ -q \
  --ignore=tests/test_integration_deepseek.py --ignore=tests/test_integration_google.py \
  --ignore=tests/test_integration_anthropic.py --ignore=tests/test_integration_openai_response.py
```

| | 結果 |
| --- | --- |
| 分支開始前 | `2 failed, 190 passed, 1 skipped` |
| 現在 | `2 failed, 238 passed, 1 skipped` |

新增 48 個測試，**零回歸**。兩個 failure 自始至終是同兩個，且與本次變更無關：

- `test_coseeing_auth_bundle.py::test_sso_configuration_matches_approved_demo` — `build_auth_config()` 的 `client_id` 是 `"wordbridge"`、port 8000，測試期望 `"a11yvillage"`、port 8765。
- `test_provider_naming.py::test_provider_config_filenames_match_catalog` — 磁碟上多了一個 `ollama.json`。

這兩項都在本次範圍外。每個測試檔單獨執行也都通過。

---

## 尚待維護者在 Windows/NVDA 上執行（全部 pending）

以下**沒有任何一項**能在此環境驗證。請依序執行，最好同一次 session 完成：

1. **先清場。** 從 `C:\Program Files\NVDA\systemConfig\` 移除舊的 `WordBridge(include-auth)` 副本。它早於 `_coseeing_auth_deps`、自帶一份 `cryptography`、且會自己做 `sys.path` 注入，留著會讓後續所有結果無法判讀。
2. **跑 probe v3**（`docs/superpowers/spikes/2026-09-20-r03-stdlib-gap-probe.py`），貼回 `%TEMP%\wordbridge-r03-stdlib-gap.txt`。**這是 spec 指定的前置條件**：目前 category 1 清單除了 `secrets` 之外仍屬未知。若它列出其他模組，那些副本必須在出版前放進 `package/_stdlib_gapfill/`。第一個健全性檢查是：`secrets` 是否出現在清單中？若否，結果就是錯的。
3. **冷啟自我檢查**（`docs/superpowers/spikes/2026-09-20-r03-selfcheck.py`）。四個本地校正名稱（`hanzidentifier`、`pypinyin`、`chinese_converter`、`zhon`）必須是 PASS；五個認證堆疊名稱此時顯示 INFO 屬正常。
4. **完整認證生命週期** — 登入、token refresh、登出，並做一次校正。
5. **再跑一次自我檢查。** 這一次九個 category 2 名稱都必須是 PASS 而非 INFO，且結尾為 `0 FAILURE(S), 0 CRASHED`。
6. **共存測試。** 另外安裝一個會用到 `requests` 與 `cryptography` 的 add-on，確認兩者都正常，且 WordBridge 載入後宿主的 `cryptography` 身分未變。
7. **降級測試。** 把 `package/_coseeing_auth_deps/py313-win_amd64` 改名後重啟 NVDA：add-on 仍須載入、本地校正仍須運作、選擇 Coseeing 頻道須說出可理解的訊息而非沉默或當機。
8. **Windows 關卡。** 在 Windows NVDA runtime 上執行 `python -m pytest tests/test_coseeing_auth_bundle.py -q`，讓 `test_windows_bundle_imports_dependencies_through_the_sandbox` 真正執行而非被 skip。

---

## 已知取捨與遺留事項

- **沙箱是 fail-open 的。** `_wb_vendor` 命名空間的 `__path__` 本身就是一個可用的匯入根，stock `PathFinder` 會自行服務它，所以若 `_SandboxFinder` 被其他 add-on 移除或擠掉，匯入仍會成功——只是未經包裝、沒有改寫。這是刻意接受的：讓它 fail-closed 意味著拿掉 `__path__` 並自行實作搜尋，而 spec 明確拒絕了這條路。緩解方式是 Windows 關卡與自我檢查腳本都會正面斷言「每個已載入的 `_wb_vendor.*` source module 都帶有沙箱化的 `__import__`」。
- **`importlib.import_module()` 繞過 shim。** 已量測確認九個 category 2 套件目前完全沒有動態匯入呼叫點；未來版本若新增，會靜默落回宿主副本，而 Windows 關卡斷言模組來源正是為此而設。
- **兩個既有的測試順序相依**（皆非本分支造成，皆被字母序掩蓋）：`test_language_text_policy_unittest.py` + `test_instruction_composer_unittest.py`（`pypinyin` stub 衝突）；以及 `test_coseeing_auth_nvda.py` + `test_coseeing_auth.py`（17 failed —— 前者先匯入 `lib.coseeing_auth`，使後者的假 `_wb_vendor.*` 錯誤模組無法生效）。後者是本次審閱新發現的，值得另行處理。
- **範圍外（依 spec）：** 認證堆疊改為 lazy 載入是 R16；精簡 bundle 是 R15；`package/coseeing_auth/` 原始碼不得修改，因為它與其他 Coseeing 專案共用。
