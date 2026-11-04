# Remote provider/model catalog

- **Branch:** `feat/remote-catalog` (from `main` at `774560b`)
- **Workflow:** normal flow (DEVELOPMENT_WORKFLOW.md §3). Nothing here has to be
  byte-identical to a known build, so the complex flow (§4) does not apply.
- **Predecessor:** `docs/superpowers/specs/2026-09-22-catalog-decoupling-design.md`
  built the `CatalogSource` seam and listed "the HTTP client, caching, offline
  policy, payload signing, and bundled⊕remote overlay semantics" as out of
  scope. This spec fills in everything except signing.

Paths are relative to `addon/globalPlugins/WordBridge/` unless they start with
`server/`, `tests/`, `workspace/` or `/workspace/nvda/`.

## 1. Problem

Every provider, model, label, price and provider parameter ships inside the
add-on, in `setting/catalog.json`, read by `BundledCatalogSource`
(`lib/catalog/sources.py:7-21`). Adding or retiring a model needs a new add-on
release (the last three commits on `main` are exactly that: `a3935fd`,
`1937dbb`, `774560b`). The server keeps a second copy of the same file
(`server/app/setting/catalog.json`, identical to the add-on file today), so the
two can drift.

## 2. Goals

1. The add-on fetches the provider/model catalog from a URL at runtime.
2. The URL is a WordBridge setting. Default: `https://wordbridge.coseeing.org`.
   A `GET` of that URL returns the catalog JSON.
3. The bundled `setting/catalog.json` keeps only `schema_version` and
   `coseeings` (the Coseeing default sentinel). Target content (the
   orchestrator-supplied `target-addon-catalog.json` is applied byte for byte,
   tab-indented; it is shown here with spaces):

   ```json
   {
     "schema_version": 1,
     "coseeings": [
       {
         "model": "default",
         "label": "default",
         "active": true
       }
     ]
   }
   ```

4. The remote payload carries `schema_version`, `providers` and `models`, and no
   `coseeings`. It becomes `server/app/setting/catalog.json`, the single source
   of truth for local-channel data. Its exact content is today's server file
   minus the `coseeings` key (6 providers, 17 models, 16 active); a separate
   reference copy is not kept.
5. The server's `GET /` returns that file.

## 3. Non-goals

- Payload signing. TLS plus the provider host allowlist (§9) is the whole
  integrity story in this phase.
- A manual refresh button or periodic refresh (§4, user decision).
- Reacting to NVDA configuration-profile switches or "revert to saved
  configuration" changing `catalog_url`; the new value takes effect at the next
  NVDA start or the next save in the WordBridge panel.
- Live-refreshing an open settings panel (§11.5).
- Validating provider `setting`, `timeout0`/`timeout_max` or `pricing` values
  beyond what `build_catalog()` already checks (see Risks).
- User guide changes (`addon/doc/*/readme.md` does not describe individual
  settings today). Follow-up once the open questions are answered.
- Changing `server/app/lib/catalog/` (a copy of the add-on package today,
  byte-identical as of `774560b`). The server does not use `selection.py` or
  `registry.py`, and the new modules are add-on-only. The copies diverge after
  this phase; that is accepted.

## 4. Decisions

### Decided by the user (2026-11-04)

| # | Decision |
| --- | --- |
| U1 | **Offline policy: cache only.** After a successful fetch the payload is stored in a cache file under NVDA's user config directory. On fetch failure the cache is used. With no cache (for example, the first start while offline) only the bundled Coseeing default is offered. No snapshot of the remote payload ships in the add-on. — Decided by the user (2026-11-04) |
| U2 | **Provider URL security.** The add-on has a built-in allowlist of hosts per provider, derived from the provider URLs in the committed catalog. A remote provider whose `url` host is not allowed for that provider is dropped and logged, because users' personal API keys are sent to that URL. — Decided by the user (2026-11-04) |
| U3 | **Fetch timing.** Once, in the background, after NVDA starts (never blocking NVDA startup or the UI thread), and again right after the user changes the URL in the settings panel and saves. No manual refresh button, no periodic refresh. — Decided by the user (2026-11-04) |
| U4 | **Target files.** The bundled catalog becomes the content in §2.3; the server catalog becomes the remote payload; `catalog-remote.json` is not kept; `GET /` serves the server catalog. — Decided by the user (2026-11-04) |
| U5 | **OQ1 → B.** The server keeps its own list of servable Coseeing model ids (env `COSEEING_MODEL_IDS`, default `deepseek-flash&DeepSeek,gpt-6-luna&OpenAI`), not exposed in `GET /`, so released add-ons keep working (§15.2, §18). — Decided by the user (2026-11-04) |
| U6 | **OQ2 → B.** A stored `(non-default id, Coseeing)` selection whose id is not offered on Coseeing stays on Coseeing and resolves to `default` (§12.1, §18). — Decided by the user (2026-11-04) |
| U7 | **OQ3 → new option D.** A stored local selection with no remote or cached catalog: the correction asks, in a Yes/No dialog, whether to switch to the Coseeing default; Yes saves `(default, Coseeing)` and runs the correction on Coseeing, No sends nothing and keeps the stored selection. No Coseeing sign-in at startup for this user (§12.5, §18). — Decided by the user (2026-11-04) |
| U8 | **Coseeing group offers only `default`.** The bundled target file in §2.3 is intended (finding 1). — Decided by the user (2026-11-04) |
| U9 | **Invalid URL status.** An invalid stored URL gets its own status line, distinct from the empty-URL line (§13.3). — Decided by the user (2026-11-04) |

### Decided by orchestrator with the recommended default; user may override before merge

Each row is repeated with its reasoning in the section named. All of them are
marked `Decided by orchestrator with the recommended default; user may override
before merge`.

| # | Decision | Section |
| --- | --- | --- |
| D1 | Overlay: the local channel (`providers`, `models`) comes only from the remote payload and the Coseeing channel (`coseeings`) only from the bundled file. Keys in the wrong document are ignored with a lint issue. | §7 |
| D2 | The Coseeing sentinel is guaranteed: if the bundled file yields no active Coseeing entry, `FALLBACK_DOCUMENT`'s entry is used. | §7 |
| D3 | A payload is accepted as a whole or not at all at the document level. Entry-level problems drop entries (existing `build_catalog()` rules). A payload that leaves no selectable local model is rejected. | §8.4 |
| D4 | HTTP client: NVDA's `requests`, injected. `stream=True`, timeout `(5, 10)` seconds, a 20-second overall deadline, a 1 MiB body limit, only status 200 accepted, no redirects, TLS verification always on. | §8 |
| D5 | URL rules: `https` required; `http` only for `localhost`, `127.0.0.1` and `::1`; no user info, no fragment, at most 2048 characters. Empty means "remote catalog off": no request, no cache. | §8.1 |
| D6 | Cache: one file, `<NVDA user config>/WordBridge-workspace/catalog/remote-catalog.json`. It records the URL it was fetched from and is used only for that URL. Written atomically, only when NVDA may write to disk. A corrupt or mismatched cache is ignored, not deleted. | §10 |
| D7 | Threading: the network work, parsing, validation, catalog build and cache write run on a daemon thread. The live catalog is swapped only on the wx main thread. Stale results (an older generation or after shutdown) are discarded. | §11 |
| D8 | On a URL change, the live catalog switches at once to bundled ⊕ (cache for the new URL, if any) and a fetch for the new URL starts. A payload from another URL is never shown. | §11.3 |
| D9 | An open settings panel is not refreshed when a new catalog arrives. The new list appears the next time the panel opens. | §11.5 |
| D10 | A correction uses one catalog snapshot from start to end. | §11.4 |
| D11 | A stored local selection that is not in a successfully loaded catalog keeps today's rule: it resolves to the catalog default. | §12.1 |
| D12 | The settings panel does not overwrite a stored model selection it could not resolve unless the user changed the Service Provider or model choice. | §12.3 |
| D13 | The existing degraded-catalog announcement (`__init__.py:416-422`) is unchanged. It still fires only when the final catalog is the fallback rung. | §12.4 |
| D14 | Fetch failures and cache problems are reported through the updater's status (panel status line and log), not as `catalog.issues`, so they never inflate the "N catalog entries could not be loaded" line. | §11.6, §13.3 |
| D15 | Logging: the catalog URL is logged as scheme, host and port only; error details are logged as exception type only; response bodies are never logged. | §14 |
| D16 | Config key `catalog_url`, static default, owned by `SettingsRepository`. The panel field is the last control in the panel. Validation uses NVDA's `isValid()` / `_validationErrorMessageBox()`. | §13 |
| D17 | Server: `GET /` serves the file's bytes, read and checked once at startup, `application/json`, `Cache-Control: no-cache`, no authentication. | §15.1 |
| D18 | Cache location reuses `lib/paths.py:user_workspace_root()`, the root the dictionary and reports already use, instead of a second derivation. | §10 |

The user-visible questions in §18 were answered by the user on 2026-11-04 (U5–U7).

## 5. Findings that bear on the user decisions

1. **Coseeing users lose two choices.** Today the Coseeing group offers
   `default`, `deepseek-flash&DeepSeek` and `gpt-6-luna&OpenAI`
   (`setting/catalog.json`, `coseeings`). With the target files the bundled
   file holds only `default` and the remote payload holds no `coseeings`
   (and is ignored if it did, D1), so the Coseeing group offers only
   `default`. This follows from U4; it is called out because it is
   user-visible.
2. **Stored Coseeing selections would move to the local channel.**
   `normalize_selection()` returns the local channel for any stored id that is
   on the local channel, even when the stored channel is Coseeing
   (`lib/catalog/selection.py:20-25`). This rule is pinned by
   `tests/test_corrector_catalog_unittest.py:62-73`. A user whose saved
   selection is (`gpt-6-luna&OpenAI`, Coseeing) is therefore silently moved to
   the local OpenAI channel with their personal key (usually empty) once the
   remote catalog loads. See OQ2.
3. **The server rejects every non-default Coseeing id once its catalog has no
   `coseeings`.** `resolve_model()` requires an active Coseeing offer for any
   id except `"default"` (`server/app/correction_config.py:67-71`). Released
   add-ons that send `gpt-6-luna&OpenAI` or `deepseek-flash&DeepSeek` would get
   404 (`server/app/main.py:153-159`), which they announce as "The Coseeing
   request failed" (`__init__.py:502-504`). See OQ1.
4. **Before the first successful fetch, local users have no model.** With no
   cache, the catalog is bundled-only. A stored local selection then resolves
   to the Coseeing default (`lib/catalog/selection.py:26`,
   `lib/catalog/model.py:186-188`), so the correction text would go to the
   Coseeing server instead of the provider the user chose. The same resolution
   decides the startup Coseeing sign-in (`__init__.py:181-182`); this is what
   `tests/test_coseeing_auth_nvda.py:342` (the assertion at line 370) catches
   when the target files are applied. See OQ3.
5. **The default URL has no `GET /` today.** `server/app/main.py` defines no
   root route, so `https://wordbridge.coseeing.org` returns 404 until the
   server change is deployed. The server must be deployed **before** an add-on
   release with this feature, or every new installation starts with only
   `default` (U1).
6. **The bundled catalog is also read by tools that need local providers.**
   `workspace/evals/provider.py:46-52` and `tests/test_helpers.py:15-20` (used
   by the paid integration tests) build their catalog from the add-on's
   `setting/`. After §2.3 they find no providers. Both move to
   `server/app/setting/catalog.json`.
7. **Google sends the API key in the URL query** (`lib/llm/provider.py:173`),
   and the other providers send it in a header (`lib/llm/provider.py:47-51`,
   `:158`). The allowlist (U2) therefore protects keys for every provider, and
   provider URLs must never be logged in full.

None of these makes a user decision unworkable. Findings 1–4 are settled by
U5–U8.

## 6. What NVDA users hear and see

- **Normal day (cache present, online):** no change from today's lists. The
  list is the cached one at start and is replaced in the background about a
  second later.
- **First start after upgrading, online:** for about a second the Service
  Provider list contains only Coseeing. Afterwards it shows Anthropic,
  DeepSeek, Google, OpenAI and Coseeing, as today.
- **Coseeing group:** only "default" (Chinese UI: "預設"). See finding 1.
- **No cache and the fetch fails, or the URL is empty or invalid:** only
  Coseeing "default". The settings panel shows a status line explaining why
  (§13.3). A correction with a stored local selection opens the Yes/No dialog
  of §12.5 (U7).
- **Settings panel:** a new last field, "Model list URL:". An invalid value
  blocks saving with NVDA's standard "Invalid configuration" message box.
- **Startup:** no new speech, no delay. Fetching never announces anything.

## 7. Documents and overlay

### 7.1 Bundled document

Exactly the content in §2.3. `BundledCatalogSource` (`lib/catalog/sources.py`)
is unchanged. The bundled file may contain only `schema_version` and
`coseeings`.

### 7.2 Remote payload

Same schema as today's catalog document (`lib/catalog/document.py:18-45`):
`schema_version` (must be `1`, `document.py:10`, `:24-30`), `providers`
(mapping), `models` (list). A `coseeings` key, if present, is ignored with the
lint issue `ignored_remote_coseeings`. Unknown top-level keys are ignored.

### 7.3 Overlay (D1, D2)

`overlay_documents(bundled, remote) -> (document, issues)` in
`lib/catalog/overlay.py`:

| Output key | Source |
| --- | --- |
| `schema_version` | `1` |
| `providers` | `remote["providers"]` after the allowlist filter (§9); `{}` when there is no accepted remote document |
| `models` | `remote["models"]`; `[]` when there is no accepted remote document |
| `coseeings` | `bundled["coseeings"]` |

- `providers` or `models` present in the bundled document are ignored with the
  lint issue `ignored_bundled_local_entries`. This makes "no snapshot of the
  remote payload ships in the add-on" (U1) structural.
- Both new codes are added to `LINT_ISSUE_CODES` (`lib/catalog/model.py:35`),
  so they are logged but do not count as dropped entries in the panel.
- D2: after `build_catalog()`, if the result has no active Coseeing entry
  (bundled file missing, corrupt or emptied), the build is repeated with
  `FALLBACK_DOCUMENT["coseeings"]` (`lib/catalog/fallback.py:13-18`) and the
  issue `bundled_coseeings_fallback` is recorded (a dropped-level issue).
  Without this, a broken bundled file plus a good remote payload would leave no
  Coseeing group, and `default_selection()` (`lib/catalog/model.py:186-191`)
  would send every Coseeing user to the first local model, Anthropic.
- The result goes through the existing `load_catalog()` ladder
  (`lib/catalog/fallback.py:21-63`) through a small in-memory source, so there
  is still one validation path (`build_catalog()`).

**Why channels, not entry merge.** The predecessor made the channel structural:
presence in `models` is the local offer, presence in `coseeings` is the
Coseeing offer (predecessor decision 7). Taking each channel from exactly one
document needs no merge or precedence rules and no duplicate handling across
documents, and an entry can always be traced to one file.

### 7.4 Shipped result

`overlay(target bundled, target server)` gives the provider groups
`("Anthropic", "DeepSeek", "Google", "OpenAI", "Coseeing")`, the same 16 local
items as today with the same labels and prices, Coseeing `("default",)`, and
one lint issue (`unreferenced_provider` for `providers.OpenRouter`, as today:
`tests/test_catalog_bundled.py:98`).

## 8. Fetching

### 8.1 URL validation and normalisation (D5)

`validate_catalog_url(text) -> UrlCheck(url, key, error)` in
`lib/catalog/remote.py`. It is pure and never raises.

| Input (after stripping surrounding whitespace) | Result |
| --- | --- |
| empty | valid; remote catalog **off** (no request, no cache read or write) |
| longer than 2048 characters, or containing whitespace/control characters | `invalid` |
| `urllib.parse.urlsplit` raises, or `.port` raises | `invalid` |
| scheme not `https`/`http` | `invalid` |
| no host | `invalid` |
| user info (`user:pass@`) | `invalid` (it would also end up in logs) |
| fragment present | `invalid` |
| `http` and host not `localhost`, `127.0.0.1` or `::1` | `insecure_scheme` |
| otherwise | valid |

- `url` is the stripped text, sent as typed.
- `key` is the comparison and cache key: lower-case scheme and host, default
  port removed, empty path treated as `/`, query kept.
- "URL changed" means the `key` changed. The panel saves the stripped text, not
  the normalised form, so a panel saved with an untouched default does not write
  a non-default value into `nvda.ini`.
- `http` for loopback exists for the local development server (the commented
  `COSEEING_BASE_URL` at `__init__.py:119`).
- A stored value that fails validation (for example, hand-edited `nvda.ini`)
  behaves like "off" (no request, no cache) but has its own status
  `fetch=invalid` and status line (U9), and is logged once. The panel shows
  the value so the user can fix it.

### 8.2 HTTP client (D4)

`requests` is the host's copy (`lib/vendor.py:56-66`, `HOST_ONLY`); NVDA itself
uses it for downloads (`/workspace/nvda/source/addonStore/network.py:303`,
`stream=True`). `__init__.py` already imports it (`__init__.py:44`). The fetch
code receives `http_get` (production: `requests.get`) by injection, so
`lib/catalog` stays standard-library-only and tests never touch the network.

Call:

```python
http_get(url, stream=True, timeout=(5, 10), allow_redirects=False,
         headers={"Accept": "application/json"})
```

- No credentials, cookies, Coseeing token or identifiers are sent.
- **TLS:** `verify` is left at the default (`True`). Never `verify=False`.
  NVDA's own `verify=False` call (`/workspace/nvda/source/updateCheck.py:1085-1093`)
  only harvests a certificate to update the Windows root store and is not a
  pattern to copy.
- **Redirects:** off. A 3xx is a failure (`remote_http_status`). The URL is
  user-configured, and following a redirect could downgrade to `http`.
- **Status:** only 200 is accepted. Any other status is `remote_http_status`
  (the detail holds the number only).
- **Size:** if `Content-Length` is greater than 1 MiB (1,048,576 bytes), fail
  without reading the body. Otherwise read `iter_content(65536)` and abort
  with `remote_too_large` as soon as the total exceeds the limit. Today's
  payload is about 6 KB.
- **Time:** connect 5 s, read 10 s per socket read, plus a 20 s overall
  deadline checked between chunks (`remote_timeout`), so a server dripping
  bytes cannot hold the thread for long.
- **Content-Type:** not checked; JSON parsing decides.
- **Exceptions:** everything raised by `http_get` or while reading is caught
  and becomes `remote_request_failed`, with the exception type name only.
  This includes `SSLError`, timeouts and connection errors. Nothing escapes the
  thread.
- The response is always closed (`with`).

### 8.3 Parsing

`parse_remote_payload(body: bytes) -> (document | None, issues)`:
`json.loads(body)`. Any exception (`ValueError`, `UnicodeDecodeError`,
`RecursionError` from deep nesting) becomes `remote_malformed`. A non-object
becomes `remote_malformed`. A `schema_version` other than `1` becomes
`remote_schema_version`. `providers` not a mapping, or `models` not a list,
becomes `remote_malformed`.

### 8.4 Acceptance (D3)

A parsed payload is **accepted** when §8.3 passes and
`build_catalog(overlay(bundled, payload))` has at least one selectable item on
the local channel. Otherwise it is rejected with `remote_no_models`. A rejected
payload is not cached and not installed; the live catalog stays as it is.
Entry-level problems (an incomplete model, an unknown provider, a disallowed
host) only drop entries, following the existing per-entry rules
(`lib/catalog/document.py:48-133`), and do not reject the payload.

The same acceptance rule is applied to a cached payload at load (§10), so a
change to the allowlist or `SUPPORTED_PROVIDERS` in a later add-on version
re-filters old caches.

## 9. Provider host allowlist (U2)

`PROVIDER_URL_RULES` in `lib/catalog/remote.py`, derived from the provider URLs
in the committed catalog (`setting/catalog.json` at `774560b`, identical to
`server/app/setting/catalog.json`):

| Provider | Schemes | Hosts | Port |
| --- | --- | --- | --- |
| Anthropic | https | `api.anthropic.com` | default only |
| DeepSeek | https | `api.deepseek.com` | default only |
| Google | https | `generativelanguage.googleapis.com` | default only |
| OpenAI | https | `api.openai.com` | default only |
| OpenRouter | https | `openrouter.ai` | default only |
| Ollama | http, https | `localhost`, `127.0.0.1` | any |

`filter_provider_urls(providers) -> (providers, issues)` runs on the remote
`providers` before `build_catalog()`:

- The host is `urlsplit(url).hostname`, which is lower-case. URLs with user
  info, an unparseable URL or port, a scheme that is not allowed, a host that
  is not allowed, or a non-default port for a non-Ollama provider are dropped.
- A provider name with no rule is dropped. A test asserts
  `set(PROVIDER_URL_RULES) == SUPPORTED_PROVIDERS` (`lib/llm/__init__.py:27`),
  so a new provider class cannot ship without a rule.
- Each drop records `CatalogIssue("disallowed_provider_url", "providers.<name>",
  "host <host> is not allowed for <name>")`. The detail holds the host only,
  never the path or query. This is a dropped-level issue, so it is counted in
  the panel summary line (`dialogs.py:112-131`).
- The models that named a dropped provider are then dropped by the existing
  `unknown_provider` rule (`lib/catalog/document.py:106-108`), which records an
  issue per model.
- Anything that is not a mapping is left for `build_catalog()` to report as it
  does today.

## 10. Cache (U1, D6, D18)

- **Path:** `user_workspace_root() / "catalog" / "remote-catalog.json"`.
  `user_workspace_root()` (`lib/paths.py:4-13`) is the `WordBridge-workspace`
  directory inside the NVDA user config directory (NVDA's own accessor for
  that directory is `NVDAState.WritePaths.configDir`,
  `/workspace/nvda/source/NVDAState.py:20-28`). It survives add-on updates,
  which replace the add-on directory. The path is computed in `__init__.py` and
  injected; tests always pass a `tmp_path`.
- **Format:**

  ```json
  {"cache_version": 1, "url_key": "https://wordbridge.coseeing.org/", "document": { "...": "the accepted payload, before allowlist filtering" }}
  ```

  The payload is stored before filtering so the filter is re-applied by
  whichever add-on version loads it.
- **Keyed by URL:** a cache whose `url_key` differs from the current key is not
  used. There is one file, so a successful fetch for a new URL replaces the old
  URL's cache.
- **Read:** on the main thread in `GlobalPlugin.__init__` (one file of about
  6 KB, next to the bundled file read that already happens there,
  `__init__.py:168-171`), and on a URL change (§11.3). At most 1 MiB + 1 byte
  is read; more is treated as corrupt.
- **Corrupt cache:** unreadable, not JSON, not an object, wrong
  `cache_version`, wrong `url_key` type, or a payload that fails §8.4: ignored,
  logged once (`unreadable_cache`, type only), **not deleted**. The next
  successful fetch overwrites it.
- **Write:** only on the fetch thread, only after acceptance, and only when
  `NVDAState.shouldWriteToDisk()` is true
  (`/workspace/nvda/source/NVDAState.py:336-343`: never from secure mode or
  the launcher; NVDA's add-on store applies the same guard,
  `/workspace/nvda/source/addonStore/network.py:296-298`). The check is
  injected as `can_write`. The directory is created at write time, never at
  import (unlike `dictionary/__init__.py:7-8`).
- **Atomic:** write to a `NamedTemporaryFile` in the same directory, flush,
  `os.fsync`, then `os.replace`. If anything fails, the temporary file is
  removed (best effort), `cache_write_failed` is logged (type only), and the
  in-memory catalog is still installed. This is the same approach as NVDA's
  `FaultTolerantFile` (`/workspace/nvda/source/fileUtils.py:20-43`), which
  `lib/catalog` cannot import.
- **Empty URL:** the cache is neither read nor written nor deleted.

`lib/catalog` stays standard-library-only. `cache.py` and `remote.py` add
`os`, `tempfile` and `urllib` to the allowed set in
`tests/test_catalog_document.py:287`, which is updated deliberately in the same
commit.

## 11. Threads and lifecycle (D7–D10, D14)

### 11.1 Modules

```
lib/catalog/
  remote.py      validate_catalog_url, PROVIDER_URL_RULES, filter_provider_urls,
                 parse_remote_payload, redact_url, limits (stdlib only)
  overlay.py     overlay_documents (stdlib only)
  cache.py       CatalogCache(path, *, can_write): load(url_key) / store(url_key, document)
  registry.py    + replace(catalog)
catalog_updater.py   CatalogUpdater, fetch_payload(); module-level install()/request_refresh()/status()
```

`catalog_updater.py` sits at the plugin root, next to `settings_repository.py`.
It imports only the standard library and `.lib.catalog`. `wx`, `requests`,
`config` and `logHandler` are injected by `__init__.py`. Its name is added to
`TOP_LEVEL_INTERNAL_NAMES` in `tests/test_import_purity.py:18`. Importing it
has no side effects, so `tests/test_import_purity.py` stays green.

`CatalogUpdater` holds: the bundled source, the cache, `runnable_providers`,
`http_get`, `post_to_ui` (production: `GlobalPlugin._run_on_ui`,
`__init__.py:273-283`), `install` (a main-thread callback), the shutdown event,
the logger, a clock, a thread starter, a lock, a generation counter, the latest
thread, and a status: `source ∈ {none, cache, fetched}` and
`fetch ∈ {off, invalid, running, succeeded, failed}`. `off` means the URL
is empty; `invalid` means a stored value failed §8.1 (U9). Both start no
fetch and read no cache.

### 11.2 Startup

`GlobalPlugin.__init__` (`__init__.py:161-187`), on the main thread:

1. Read the URL through `SettingsRepository.catalog_url()` and validate it.
2. `catalog = updater.initial_catalog(url)`: bundled ⊕ (cache for this URL, if
   accepted), through `load_catalog()`. This replaces the
   `load_catalog(BundledCatalogSource(...))` call at `__init__.py:168-171`.
3. `registry.initialize(catalog)`, log issues as today (`__init__.py:173-177`).
4. `wx.CallAfter(self._start_catalog_fetch)`. This is the same deferral pattern
   as `_start_coseeing_auth` (`__init__.py:182`, `:218-220`). It runs once the
   wx main loop starts dispatching, which is after `globalPluginHandler`
   initialisation (`/workspace/nvda/source/core.py:928`) and when NVDA enters
   `app.MainLoop()` (`core.py:1088`). Unlike `core.postNvdaStartup`
   (`core.py:53`, `:1078-1084`), it also fires when the plugin is reloaded
   without restarting NVDA. `_start_catalog_fetch` returns at once if
   `_shutdown` is set or the URL is off, and otherwise starts a daemon thread
   named `wordbridge-catalog-fetch`. Starting the thread is the only work done
   on the main thread.

### 11.3 Fetch thread and URL change

`updater.refresh(url)` (main thread): under the lock, increment the generation,
record `(generation, url_key)`, and set `fetch=running`, or `off` for an empty
URL, or `invalid` for one that fails §8.1. If the key differs from the one the live catalog was built for (D8),
immediately install bundled ⊕ (cache for the new key, if any) and set `source`
to match. Then start a thread for this generation. Older threads are not
joined; their results are discarded.

Fetch thread for generation *g*:

1. `fetch_payload()` (§8.2), parse (§8.3), build and accept (§8.4). The catalog
   is built on this thread; `build_catalog()` is pure.
2. If `shutdown.is_set()` or *g* is not the current generation, stop; nothing
   is written or posted.
3. Store the cache (§10). This happens outside the lock so a slow disk never
   blocks the main thread. A stale writer can race in between the check and the
   write, but its file carries its own `url_key`, so it can never be used for
   the wrong URL. The worst case is that the next start has no cache and
   fetches again.
4. `post_to_ui(self._apply, g, catalog_or_none, outcome)`. On the main thread,
   `_apply` re-checks the generation and shutdown, then either installs the
   catalog (`source=fetched`, `fetch=succeeded`) or records `fetch=failed`
   (keeping the current catalog and source).

### 11.4 Installing a catalog (D10)

`GlobalPlugin._install_catalog(catalog)` runs only on the main thread. It calls
`registry.replace(catalog)`, sets `self.catalog = catalog`, and logs the
catalog's issues through the same loop as at startup. Python reference
assignment is atomic; the main-thread rule exists so that the panel's reads
(`dialogs.py:91-93`) can never see two catalogs.

`correctTypo()` runs on a worker thread (`__init__.py:549`) and today reads the
catalog twice: `registry.current()` at `__init__.py:404`, then
`self.settings.corrector_selection()` at `:405`, which calls
`registry.current` again (`settings_repository.py:60-65`). It also reads
`self.catalog.degraded` at `:416`. After this change it takes one snapshot,
`catalog = registry.current()`, and uses it for everything:
`SettingsRepository.corrector_selection(catalog=None)` gains an optional
explicit catalog, and the degraded check reads `catalog.degraded`. A swap in
the middle of a correction therefore cannot make `get_model()` return `None`
for an id that was just resolved.

### 11.5 Settings panel open during a swap (D9)

The panel keeps the catalog it took at `makeSettings` (`dialogs.py:91`) and its
`SelectionState`. A swap does not rebuild its controls. Rebuilding would move
focus and change list contents under a screen reader user. `onSave` saves ids
from that snapshot, which stay valid because ids are re-resolved at every read
(`settings_repository.py:60-65`). While the dialog is open, a correction cannot
start (`__init__.py:607-614`).

### 11.6 Status, not issues (D14)

Fetch failures (`remote_*`) and cache problems (`unreadable_cache`,
`cache_write_failed`) are logged and reflected in the updater status. They are
not added to `catalog.issues`, which keeps "{count} catalog entries could not
be loaded" (`dialogs.py:112-131`) about entries in the document actually in
use. `disallowed_provider_url` and overlay issues are about that document, so
they are in `catalog.issues`.

### 11.7 Shutdown

`terminate()` already sets `_shutdown` first (`__init__.py:232`). The latest
fetch thread is added to the `workers` list it joins within the shared
`TERMINATE_WAIT_SECONDS` budget (`__init__.py:237-254`). A `requests` read
cannot be interrupted, so a thread that is still blocked is abandoned. It is a
daemon, the existing "background work still running" warning covers it, and
step 2 of §11.3 keeps it from writing or posting. `_run_on_ui` already drops
callbacks after shutdown (`__init__.py:273-283`). `catalog_updater.uninstall()`
runs in the same `finally` block as `shutdown_coseeing_auth()`
(`__init__.py:257-261`), in its own `try`, following the R02 rule that
`terminate()` never raises (`__init__.py:223-231`).

## 12. Selection semantics

### 12.1 Stored id missing from a loaded catalog (D11)

When a remote or cached payload is in use (`source != none`) and the stored id
is not offered on its channel, today's rule applies unchanged: resolve to
`default_selection()` (`lib/catalog/selection.py:26`), which is the Coseeing
`default` (`lib/catalog/model.py:186-188`). This is what already happens when a
release retires a model (for example, GPT-5.6 in `a3935fd`). Stored values are
never rewritten on read (`settings_repository.py:60-65`), so a model that
returns in a later payload comes back by itself.

The two user-visible cases not covered by this rule were OQ2 and OQ3:

- **Stored Coseeing id offered only locally (U6, OQ2 → B).** A stored
  `execution_channel == "Coseeing"` whose id is not offered on Coseeing
  resolves to `default_selection()` (the Coseeing `default`), never to the
  local channel. `normalize_selection()` changes accordingly; the rule pinned
  at `tests/test_corrector_catalog_unittest.py:62-73` is rewritten, and the
  unknown-channel case (`:75-85`) is unchanged. Stored values are still not
  rewritten on read.
- **Stored local selection while `source == none` (U7, OQ3 → D).** See §12.5.

### 12.2 Startup Coseeing sign-in

`_start_coseeing_auth(channel)` keeps using the resolved selection
(`__init__.py:181-182`), except that it is skipped when the **stored**
`execution_channel` is `local` and `source == none` (U7): the user chose a
local model, and only a Yes in the §12.5 dialog moves them to Coseeing.

### 12.3 Panel does not overwrite an unresolved selection (D12)

`makeSettings` records whether `normalize_selection()` changed the stored
`(id, channel)`, and the restored indices. In `onSave` (`dialogs.py:286-292`),
if the stored selection was unresolved and the user did not change the Service
Provider or model choice, `save_corrector_selection()` is skipped. Without
this, a user who is offline with no cache and opens the panel only to change
the language would lose their saved local model. The `start_coseeing_auth`
call at `dialogs.py:305` uses the effective (resolved) channel.

### 12.4 Degraded announcement (D13)

`CorrectorCatalog.degraded` keeps its meaning: the final catalog is the
fallback rung of `load_catalog()` (`lib/catalog/fallback.py:46-63`). With D2
that can now happen only when the source itself raises. The one-shot
announcement (`__init__.py:416-422`, "The model list could not be loaded.
Coseeing will choose a model for you.") is unchanged. It does not fire for the
new bundled-only state, because a Coseeing user loses nothing there; the
bundled-only state is explained by the panel status line (§13.3) and, for local
users, by the §12.5 dialog.

### 12.5 Stored local selection with no remote or cached catalog (U7)

Applies when a correction is requested (`script_correction`, NVDA+Alt+O),
the selected text passed `isTextValid()`, the **stored**
`execution_channel` (`SettingsRepository.stored_execution_channel()`, the raw
value) is `local`, and the updater status has `source == none` — the first
start after the upgrade before the first fetch, offline with no cache, or an
empty or invalid URL. `normalize_selection()` is unchanged by this; the check
is keyed on the raw stored channel, before the resolution that would otherwise
send the text to the Coseeing default.

1. `script_correction` schedules `wx.CallAfter(self._ask_switch_to_coseeing,
   text)` and returns. A `gui.message.MessageDialog` must be built on the main
   thread, and NVDA recommends `wx.CallAfter` over a modal dialog shown
   directly from a script (`/workspace/nvda/source/gui/__init__.py:948-955`).
   While this dialog is open, a second correction request is ignored (a flag
   set before `ShowModal()` and cleared after it).
2. The dialog: `gui.message.MessageDialog(gui.mainFrame, message,
   _("WordBridge"), buttons=DefaultButtonSet.YES_NO)`
   (`/workspace/nvda/source/gui/message.py:361-364`, `:420-428`), with
   `setDefaultFocus(ReturnCode.NO)` and `SetEscapeId(ReturnCode.NO)`
   (`message.py:699`, `:712`). **Title** "WordBridge" (the existing
   translated panel title). **Message** (two paragraphs, information first, so
   NVDA reads "not available" before the question when the dialog opens):

   > The model list is not available yet, so the model you selected cannot be used.
   >
   > Switch to the Coseeing default and correct this text with Coseeing? Your
   > WordBridge setting will be changed to the Coseeing default.

   **Buttons** NVDA's own Yes and No (already translated by NVDA). **Initial
   focus and default button: No**, so pressing Enter or Escape sends nothing.
   NVDA reads: "WordBridge dialog, The model list is not available yet, …,
   No button".
3. After `ShowModal()` returns, re-check `_shutdown` (the nested loop can run
   `terminate()`).
   - **Yes:** `self.settings.save_corrector_selection("default", "Coseeing")`
     — the same write the panel's `onSave` does, so NVDA persists it the same
     way as any panel change — then `self.startCorrection(text)`. The correction
     takes the Coseeing path, which requests its own access token
     (`__init__.py:467`); no separate sign-in call is made. Yes does this
     **always**, even if the model list arrived and was installed while the
     dialog was open (the nested event loop can run the fetch result): the
     answer is to the question the dialog asked. — Decided by the user
     (2026-11-04)
   - **No (or Escape, or closed):** nothing is sent anywhere, the stored
     selection is unchanged, and NVDA says "The text was not sent. Your model
     selection was not changed." — also when the model list arrived while the
     dialog was open.
4. No new speech happens before the dialog: a `ui.message` would be cut off by
   the dialog's own focus announcement, so the information is the dialog's
   first sentence instead.

## 13. Settings

### 13.1 Config spec and repository (D16)

`__init__.py:102-117` gains, inside `"settings"`:

```python
"catalog_url": f"string(default='{DEFAULT_CATALOG_URL}')",
```

`DEFAULT_CATALOG_URL = "https://wordbridge.coseeing.org"` lives in
`lib/catalog/remote.py`. It is a static string like the predecessor's spec
defaults, and it is separate from `COSEEING_BASE_URL` (`__init__.py:118`)
because the proofreader endpoint is not configurable. `SettingsRepository`
(`settings_repository.py:47-58`, the only owner of these keys) gains
`catalog_url() -> str` (the stored value, stripped) and
`save_catalog_url(value)`.

### 13.2 Panel field

- **Position:** the last control, after "Sound effect credits"
  (`dialogs.py:242-248`). Tab order is creation order, so every existing
  control keeps its position and users' muscle memory is preserved.
- **Control:** `settingsSizerHelper.addLabeledControl(_("Model list URL:"),
  wx.TextCtrl, size=(self.scaleSize(375), -1), value=...)`, the same shape as
  the API key fields (`dialogs.py:173-178`). The tooltip follows the existing
  choice controls (`dialogs.py:140`).
- **What NVDA reads on focus:** "Model list URL: edit,
  https://wordbridge.coseeing.org" (the label is bound by
  `addLabeledControl`).
- **Validation:** `isValid()` runs `validate_catalog_url()`. When it fails, it
  calls `self._validationErrorMessageBox(message=..., option=_("Model list
  URL"))` (`/workspace/nvda/source/gui/settingsDialogs.py:449-470`), focuses
  the field and returns `False`. NVDA then aborts the save for every panel and
  keeps the dialog open (`settingsDialogs.py:758-764`, `:775-799`). NVDA reads
  the "Invalid configuration" message box, which includes 'Category:
  "WordBridge"' and 'Option: "Model list URL"' (`settingsDialogs.py:457-468`).
  The same pattern is used by NVDA's speech panel (`settingsDialogs.py:2030-2043`).
- **Save:** `onSave` writes the stripped text only if its key differs from the
  stored key. If it does, `wx.CallAfter(catalog_updater.request_refresh, url)`
  runs after the dialog's save sequence, the same deferral as
  `dialogs.py:305`. That covers both OK and Apply.

### 13.3 Panel status line

A `wx.StaticText` added at the top of the panel, directly after the existing
dropped-entries line (`dialogs.py:112-131`), because it explains why the
Service Provider list below is short. It is not in the Tab order. NVDA reads
it with NVDA+B ("Reads all controls in the active window",
`/workspace/nvda/source/globalCommands.py:3234-3239`) or object navigation,
like the existing summary line. It reflects the status at the moment the panel
opens:

| Status | Line |
| --- | --- |
| `fetch=off` | "The model list URL is empty, so only the Coseeing default is available." |
| `fetch=invalid` (U9) | "The model list URL is invalid, so no model list was loaded." |
| `source=none`, `fetch=running` | "The model list is still loading. Until it loads, only the Coseeing default is available." |
| `source=none`, `fetch=failed` | "The model list could not be loaded, so only the Coseeing default is available. See the NVDA log for details." |
| `source=cache`, `fetch=failed` | "The model list could not be updated. WordBridge is using the list it saved earlier." |
| otherwise | none |

### 13.4 New strings and suggested zh_TW translations

Every new `_()` call gets a `# Translators:` comment. The zh_TW entries go into
`addon/locale/zh_TW/LC_MESSAGES/nvda.po`. The terms follow the existing ones:
"模型清單" (`nvda.po:202-203`), "預設" (`nvda.po:45-46`), "NVDA 記錄"
(`nvda.po:58`).

| English | zh_TW | Translators comment (gist) |
| --- | --- | --- |
| `Model list URL:` | `模型清單網址：` | Label of the edit field for the address the model list is downloaded from |
| `The address WordBridge downloads the model list from. Leave it empty to use only the Coseeing default.` | `WordBridge 下載模型清單的網址。留空則只使用 Coseeing 預設。` | Tooltip of that field |
| `Model list URL` | `模型清單網址` | Option name in NVDA's "Invalid configuration" message; same as the label without the colon |
| `Enter a complete web address, such as https://wordbridge.coseeing.org, or leave the field empty.` | `請輸入完整的網址，例如 https://wordbridge.coseeing.org，或將此欄位留空。` | Validation error for a malformed URL |
| `The model list URL must start with https://. http:// is allowed only for localhost.` | `模型清單網址必須以 https:// 開頭。只有 localhost 可以使用 http://。` | Validation error for plain http to a remote host |
| `The model list URL is empty, so only the Coseeing default is available.` | `模型清單網址為空白，因此只能使用 Coseeing 預設。` | Panel status line |
| `The model list is still loading. Until it loads, only the Coseeing default is available.` | `模型清單仍在載入中。載入完成前，只能使用 Coseeing 預設。` | Panel status line |
| `The model list could not be loaded, so only the Coseeing default is available. See the NVDA log for details.` | `無法載入模型清單，因此只能使用 Coseeing 預設。詳情請參閱 NVDA 記錄。` | Panel status line |
| `The model list could not be updated. WordBridge is using the list it saved earlier.` | `無法更新模型清單。WordBridge 正在使用先前儲存的清單。` | Panel status line |
| `The model list URL is invalid, so no model list was loaded.` | `模型清單網址無效，未取得模型清單。` | Panel status line for an invalid stored URL (U9) |
| `The model list is not available yet, so the model you selected cannot be used.\n\nSwitch to the Coseeing default and correct this text with Coseeing? Your WordBridge setting will be changed to the Coseeing default.` | `模型清單尚未取得，因此無法使用您選擇的模型。\n\n要改用 Coseeing 預設，並使用 Coseeing 校正這段文字嗎？您的 WordBridge 設定會改為 Coseeing 預設。` | Message of the Yes/No dialog in §12.5; Yes switches to Coseeing and sends the text there |
| `The text was not sent. Your model selection was not changed.` | `未傳送文字，模型選擇維持不變。` | Spoken after the user answers No in that dialog |

The dialog title reuses the existing `_("WordBridge")` (`nvda.po:52`); the
buttons are NVDA's own Yes and No.

## 14. Logging (D15)

- `redact_url(url)` returns `scheme://host[:port]`. The path and query are
  never logged, because a user-entered URL may carry a token.
- Success: `log.info("WordBridge: catalog fetched host=%s bytes=%d models=%d", ...)`.
- Failure: `log.warning("WordBridge: catalog fetch failed host=%s code=%s type=%s", ...)`,
  with the status number for `remote_http_status`. Never `str(error)`:
  `requests` exception messages contain the full URL. Never `exc_info`. This
  follows the privacy rule already applied at `__init__.py:70-98`.
- Catalog issues use the existing format (`__init__.py:173-177`). Provider
  issues name the provider and the host only (§9).
- Response bodies, provider `setting` values and API keys are never logged. The
  catalog fetch never handles API keys.

## 15. Server

### 15.1 `GET /` (D17)

In `server/app/main.py`:

- At import, next to `CORRECTION_SETTINGS = load_correction_settings()`
  (`server/app/main.py:39`), read `SETTING_DIR / "catalog.json"` as bytes
  (`server/app/correction_config.py:18`) and `json.loads` them. The result
  must be an object with `schema_version == 1`; otherwise the module raises at
  startup, the same fail-loud stance as `load_correction_settings()`
  (`correction_config.py:31-55`). The file only changes with a deployment, so it
  is not re-read per request.
- `@app.get("/")` returns `Response(content=CATALOG_BYTES,
  media_type="application/json", headers={"Cache-Control": "no-cache"})`. The
  bytes are served verbatim, so the payload is the file. No authentication,
  because the catalog is public data; route-permission tests pin that an
  anonymous `GET /` returns 200.

### 15.2 Resolving `corrector_config_id` without `coseeings`

Today `resolve_model()` maps `"default"` to `DEFAULT_CORRECTOR_CONFIG_ID`
(default `deepseek-flash&DeepSeek`, `correction_config.py:20`, `:43`, `:67`).
That still works with the target file, because `deepseek-flash` is an active
DeepSeek model there. Any other id requires an active `coseeings` offer
(`correction_config.py:68-71`), and the target file has none. This changes
which models Coseeing users of **released** add-ons can use, so it was OQ1.

**Decided by the user (2026-11-04): B (U5).** `CorrectionSettings` gains
`coseeing_ids: frozenset[str]`, read at startup from the env var
`COSEEING_MODEL_IDS` (comma-separated, items stripped, empty items ignored;
default `deepseek-flash&DeepSeek,gpt-6-luna&OpenAI`). `resolve_model()`
checks it where it checked the `coseeings` offer
(`correction_config.py:68-71`); the local-model check after it is unchanged.
The list is server-only and is not part of the `GET /` payload. Released
add-ons keep working exactly as today, and the two server tests keep their
meaning.

## 16. Tests that depend on the bundled catalog today

### 16.1 Measured

The target files were applied to a scratch copy of `774560b`. Result: add-on
**42 failed, 418 passed, 1 skipped**; server **2 failed, 79 passed**. Each test
reads providers, models or non-sentinel Coseeing offers from
`addon/globalPlugins/WordBridge/setting/catalog.json` through
`BundledCatalogSource`, or builds the plugin catalog from it:

| File | Failing | How it reads the bundled catalog |
| --- | --- | --- |
| `tests/test_ai_config_schema.py` | 3 | `CATALOG_PATH` (`:6-7`) |
| `tests/test_catalog_bundled.py` | 5 | `shipped_catalog()` (`:19-20`); pins providers, prices and the Coseeing labels (`:128-134`) |
| `tests/test_catalog_source_seam.py` | 2 | `BundledCatalogSource(SETTING_DIR)` (`:58-103`) |
| `tests/test_corrector_catalog_unittest.py` | 5 | `shipped_catalog()` (`:13-15`); includes the OQ2 rule at `:62-85` |
| `tests/test_coseeing_auth_nvda.py` | 4 | plugin init via `_load_nvda_plugin` (`:76`); `:342`, `:931`, `:997`, `:1032` |
| `tests/test_coseeing_requests.py` | 4 | plugin catalog; `:28` (×2, expects `deepseek-flash&DeepSeek`), `:632`, `:718` |
| `tests/test_eval_provider_config.py` | 1 | `_catalog()` (`:25-26`); `:127` |
| `tests/test_provider_model_adapter_unittest.py` | 11 | `_catalog()` (`:47-52`) |
| `tests/test_provider_naming.py` | 5 | `BundledCatalogSource(SETTING_DIR)` (`:14`, `:20`) |
| `tests/test_task_architecture_unittest.py` | 2 | `:33`, `:51` |
| `server/tests/test_correction_config.py` | 1 | `test_default_resolves_to_local_model` (`:6-10`): `LookupError: gpt-6-luna&OpenAI` |
| `server/tests/test_proofreader_api.py` | 1 | `test_explicit_model_success` (`:109-121`): 404 |

The integration tests and the evals are not part of routine verification, but
they also read the add-on catalog: `tests/test_helpers.py:15-20` and
`workspace/evals/provider.py:46-52` (finding 6).

### 16.2 Migration rule

- A new helper `tests/shipped_catalog.py` exposes `SERVER_CATALOG_PATH`
  (`server/app/setting/catalog.json`), `server_document()`,
  `bundled_document()` and `shipped_overlay()`. The last one is the catalog a
  user sees after a successful fetch of the shipped server file.
- Tests about provider parameters, prices or local model lists read the server
  file through the helper. They pin the **same** values as today, so the
  regression protection moves with the data and is not lost.
  `test_helpers.py` and `workspace/evals/provider.py` switch to the server file
  too.
- `tests/test_catalog_bundled.py` and `tests/test_ai_config_schema.py` pin the
  new bundled content exactly: keys `{"schema_version", "coseeings"}`, the one
  sentinel.
- Plugin-level tests (`_load_nvda_plugin`) seed the catalog through a
  `tmp_path` cache file for the configured URL, or through an injected updater.
  They never touch the network or the real workspace root. Following the
  project rule, `_load_nvda_plugin` is imported at function scope, never at
  module scope.
- Tests that need a non-sentinel Coseeing entry (`test_coseeing_auth_nvda.py:1075`,
  `test_coseeing_requests.py:28`) build a fixture document that has one,
  instead of relying on shipped data that no longer has one.

### 16.3 Commit ordering (every commit green)

The two target files are **not** committed on their own.
They are, byte for byte:

- `/tmp/claude-0/-workspace-WordBridge/9af55a63-c255-4088-9b3c-fe363afb236f/scratchpad/remote-catalog/target-addon-catalog.json`
  → `addon/globalPlugins/WordBridge/setting/catalog.json`
- `/tmp/claude-0/-workspace-WordBridge/9af55a63-c255-4088-9b3c-fe363afb236f/scratchpad/remote-catalog/target-server-catalog.json`
  → `server/app/setting/catalog.json`

1. The new modules (§11.1) are built and tested against in-memory fixtures
   while both catalog files are still unchanged.
2. **One task** applies `target-addon-catalog.json` to `setting/catalog.json`,
   wires the updater into `GlobalPlugin`, and migrates all 42 add-on tests (and
   `test_helpers.py`, `workspace/evals/provider.py`) in the same commit. At that
   point the helper reads the server file as it is, still with `coseeings`, so
   the overlay records the `ignored_remote_coseeings` lint. Tests that pin the
   lint list allow for it until step 3.
3. **One task**, after OQ1 is answered, applies `target-server-catalog.json` to
   `server/app/setting/catalog.json`, implements the OQ1 option, updates the two
   server tests, adds the `GET /` tests, and removes the temporary lint
   allowance from step 2. If OQ1 is answered before step 2 starts, step 3 may
   run first.

## 17. Test plan

Hypothesis and mutmut are not dependencies of this repository (neither is
installed in the test venv), so property-style coverage is written as
table-driven tests.

### 17.1 Unit tests (no NVDA, no network)

- `tests/test_catalog_remote_url.py`: every row of §8.1, including `[::1]`,
  upper-case scheme and host, `""` vs `"/"` key equality, a bad port, and a
  2049-character URL. `validate_catalog_url` never raises for any input in the
  table, including non-ASCII text.
- `tests/test_catalog_provider_allowlist.py`: every provider URL in the server
  file is allowed. For each provider: a foreign host is dropped with
  `disallowed_provider_url`, the detail has no path or query, and the provider's
  models are dropped with `unknown_provider`. Also: `http` to Anthropic is
  dropped; Ollama `http://localhost:11434` and `http://127.0.0.1:11434` are
  allowed and `http://10.0.0.5:11434` is not; port 8443 for OpenAI is dropped;
  user info is dropped; a lookalike host (`api.openai.com.evil.test`) and a
  subdomain (`x.api.openai.com`) are dropped; an unknown provider name is
  dropped; `set(PROVIDER_URL_RULES) == SUPPORTED_PROVIDERS`.
- `tests/test_catalog_overlay.py`: the channel sources (§7.3); remote
  `coseeings` ignored with a lint issue; bundled `providers`/`models` ignored
  with a lint issue; no remote document gives the sentinel only; a broken
  bundled file plus a good remote gives the sentinel plus local items
  (`bundled_coseeings_fallback`); `overlay(target bundled, target server)`
  matches §7.4 exactly, including that `gpt-6-luna&OpenAI` is **not** a
  Coseeing item.
- `tests/test_catalog_payload.py`: §8.3 and §8.4. Valid payload; non-JSON; JSON
  array; `schema_version` 2; `providers` a list; `models` missing; a payload
  with only inactive or only unsupported models gives `remote_no_models`;
  `"[" * 100000` gives `remote_malformed` and does not raise.
- `tests/test_catalog_cache.py` (`tmp_path`): round trip; `url_key` mismatch
  ignored; corrupt JSON, wrong `cache_version` and a non-object ignored and the
  file left in place; a cached payload failing §8.4 ignored; with `os.replace`
  failing (monkeypatched), the old file is intact and no `.tmp` file remains;
  `can_write=False` writes nothing; the directory is created lazily; a file
  larger than the limit is ignored.
- `tests/test_catalog_fetch.py` (fake `http_get` returning objects with
  `status_code`, `headers`, `iter_content`, context manager): exact call
  kwargs (`stream=True`, `timeout=(5, 10)`, `allow_redirects=False`, no
  `verify`, no auth headers); 200 accepted; 301/304/404/500 rejected with the
  number in the detail; `Content-Length` over the limit is rejected without
  calling `iter_content`; a streamed body over the limit stops reading at the
  first chunk past it; a fake clock past 20 s gives `remote_timeout`; a raised
  `Exception` subclass gives `remote_request_failed` with the type name only;
  the response is closed in every case.
- `tests/test_catalog_updater.py` (fake thread starter that records targets,
  manual `post_to_ui` queue, fake clock): startup with a cache gives
  `source=cache`; without one, bundled only; a successful refresh posts an
  install and writes the cache; a failure leaves the cache and catalog
  untouched and sets `fetch=failed`; two refreshes completed out of order
  install only the newer one, and the older one writes no cache; shutdown set
  before completion means no post and no write; a URL change installs bundled ⊕
  cache(new) at once (D8); an empty URL starts no thread; a log capture shows
  no path, query or `str(error)`.
- `tests/test_catalog_registry.py`: `replace()` before `initialize()` raises;
  `replace()` swaps `current()`.
- `tests/test_settings_repository.py`: `catalog_url` default and save;
  `corrector_selection(catalog=...)` uses the given catalog and never calls the
  callable.
- `tests/test_catalog_document.py:287`: `STDLIB_ONLY` gains exactly `os`,
  `tempfile` and `urllib`.

### 17.2 NVDA-stubbed tests (existing harness, `_load_nvda_plugin`)

- Plugin init schedules two callbacks (sign-in and fetch start). The existing
  `assert len(queued) == 1` at `tests/test_coseeing_auth_nvda.py:367`, `:494`
  and `:666`, and `== 2` at `:596`, are updated to the new count. The
  fetch-start callback does nothing after `terminate()`. `terminate()` joins
  the fetch thread within the budget and calls `catalog_updater.uninstall()`
  even if an earlier step raises.
- `_install_catalog` updates both `registry.current()` and `self.catalog`.
  `correctTypo` with a registry swapped between its reads (monkeypatched
  `registry.current` returning a different catalog on the second call) still
  uses the first snapshot, both for the payload id and for the degraded check.
- Panel: the URL field is the last control. `isValid()` with `ftp://x` and with
  `http://example.com` calls the message box with the right message and option,
  focuses the field and returns `False`. An unchanged URL saves nothing and
  triggers no refresh. A changed URL saves the stripped text and schedules
  `request_refresh` once. The status line text matches each row of §13.3, and
  there is no line when the status is fresh. The dropped-entries line stays
  silent for `shipped_overlay()` (the healthy catalog). D12: with an unresolved
  stored local id and untouched choices, `onSave` leaves the stored id
  unchanged; after the user changes the model choice, it saves the new one.
- No test performs a real HTTP request: the plugin harness replaces
  `requests.get` with a function that fails the test.

### 17.3 Seam test

`tests/test_catalog_source_seam.py` keeps its contract ("a document from a
remote source behaves exactly like the same content loaded from disk"), now
against the real path. The fake `http_get` serves the server file's bytes;
fetch → parse → overlay → `load_catalog()` must equal
`load_catalog(InMemory(overlay(bundled, json.load(server file))))` in provider
groups, selectable items, default selection and price entries. The existing
"add a model with no code change", "unimplemented provider" and "None issues"
cases are kept and fed through the same fake. The unimplemented-provider case
no longer adds a remote Coseeing entry (remote `coseeings` are ignored); it
asserts the Mistral models are dropped with `unsupported_provider` (Mistral gets
a temporary rule in that test, so the allowlist does not drop it first).

### 17.4 Regression

Every test in §16.1 is migrated per §16.2 and must pass with the target files
applied. U6 and U7 each get their own named tests: for U6, a stored
`("gpt-6-luna&OpenAI", "Coseeing")` resolves to `("default", "Coseeing")`;
for U7, the dialog is scheduled instead of a correction, its message, title,
default focus and escape id match §12.5, Yes saves `("default", "Coseeing")`
and starts a Coseeing correction, No starts nothing, sends nothing, keeps the
stored values and speaks the cancel line, a second request while it is open is
ignored, a stored Coseeing user never sees it, it does not appear once
`source != none`, and startup skips the Coseeing sign-in for that user.

### 17.5 Server

- `GET /` returns 200, `application/json`, `Cache-Control: no-cache`, and a body
  byte-identical to `server/app/setting/catalog.json`. The body parses to an
  object without `coseeings`. An anonymous client works.
- A startup check: a non-object or wrong `schema_version` in the file raises
  (monkeypatched path).
- The two failing tests keep their meaning under U5 (the ids are in the
  default `COSEEING_MODEL_IDS`). `test_inactive_coseeing_offer_is_rejected`
  (`:20-28`) becomes vacuous without `coseeings` and is rewritten as "an id
  not in `COSEEING_MODEL_IDS` is rejected" plus "a listed id whose local model
  is inactive is rejected".

### 17.6 Windows/NVDA manual checks

Each item is tested on an installed add-on built from the branch.

1. Fresh user config, online: NVDA starts with no audible delay. The NVDA log
   shows "catalog fetched host=https://wordbridge.coseeing.org" after "NVDA
   initialized". `%APPDATA%\nvda\WordBridge-workspace\catalog\remote-catalog.json`
   exists. Reopening the panel shows all providers.
2. Same, opening the panel within the first second: the status line says the
   list is loading, and Coseeing is the only group.
3. Offline with no cache: only Coseeing "default"; the status line says the
   list could not be loaded. With a stored local model, NVDA+Alt+O opens the
   §12.5 dialog: NVDA reads the title, the "not available" sentence, the
   question, and "No button". Escape speaks the cancel line and sends nothing;
   reopening the panel still shows the stored model is unchanged (D12). Yes
   corrects the text through Coseeing and the panel then shows Coseeing
   "default".
4. Offline with a cache: the cached list; the status line says it could not be
   updated.
5. URL `ftp://x`, then `http://example.com`: NVDA reads the "Invalid
   configuration" message box. Focus returns to the URL field and the dialog
   stays open.
6. URL `http://localhost:8000` with the local server running, then Apply: the
   panel re-opened after closing shows that server's list. Restart NVDA: the
   cache is used for that URL. Switch back to the default: the old cache is not
   used (log), and a new fetch runs.
7. Empty URL: no request (log), only "default".
8. Local server serving a payload with OpenAI's `url` host changed: OpenAI
   disappears, the log names "OpenAI" and the host, and the panel's
   dropped-entries line counts the provider and its models.
9. Local server serving more than 1 MiB, or sleeping 30 s: rejected, NVDA stays
   responsive.
10. Exit NVDA while the local server is sleeping during a fetch: NVDA exits
    within about 3 s, and the cache file is intact.
11. NVDA Remote "Get external IP" still works (regression check for `497b178`,
    since `requests` comes from the host).
12. NVDA launcher (not installed): no cache file is written.
13. Speech: "Model list URL: edit, https://wordbridge.coseeing.org". It is last
    in the Tab order. NVDA+B reads the status line.

## 18. Open questions (answered by the user on 2026-11-04)

### OQ1. How does the server resolve a non-default `corrector_config_id` once its catalog has no `coseeings`?

Released add-ons let Coseeing users pick `deepseek-flash&DeepSeek` and
`gpt-6-luna&OpenAI`, and send those ids (finding 3). The new add-on sends only
`default` (finding 1).

- **A. Only `default` is accepted.** Other ids get 404. Simplest, but users of
  released add-ons with a non-default Coseeing selection see "The Coseeing
  request failed" until they upgrade or change the setting.
- **B. A server-only list of servable ids**, for example the env var
  `COSEEING_MODEL_IDS` with default `deepseek-flash&DeepSeek,gpt-6-luna&OpenAI`.
  It is checked where `coseeings` was checked
  (`correction_config.py:68-71`) and is not part of the `GET /` payload.
  Released add-ons keep working exactly as today; the two server tests keep
  their meaning. The cost is a second short list to maintain on the server.
- **C. Unknown non-default ids are served by the deployment default.**
  Released add-ons keep working, but a user who explicitly chose `gpt-6-luna`
  is silently served `deepseek-flash`. The recorded `Interaction.model` stays
  truthful (`main.py:219`).

**Recommended: B.** It is the only option that changes nothing for installed
add-ons. It can be removed later with no add-on change.

**Decided by the user (2026-11-04): B** (U5, §15.2).

### OQ2. What happens to a stored Coseeing selection whose id is now offered only on the local channel?

Affects users who chose Coseeing `gpt-6-luna` or `deepseek-flash` (finding 2).

- **A. Keep today's rule:** move to the local channel
  (`selection.py:22-23`). Their text then goes straight to OpenAI or DeepSeek
  with their personal key, which is usually empty, so the correction fails with
  an authentication error.
- **B. Stay on Coseeing:** a stored Coseeing channel whose id is not offered on
  Coseeing resolves to the Coseeing default (`default`). The rule at
  `tests/test_corrector_catalog_unittest.py:62-73` is rewritten; the
  unknown-channel case (`:75-85`) is unchanged.
- **C. B plus a one-time spoken notice** on the first correction ("Your
  Coseeing model is no longer offered; Coseeing will choose a model for
  you."). This adds one string.

**Recommended: B.** The user keeps the channel (and the account and billing)
they chose. Stored values are not rewritten, so nothing is lost if the answer
changes later.

**Decided by the user (2026-11-04): B** (U6, §12.1).

### OQ3. What does a correction do when the stored selection is local and no remote or cached catalog is loaded?

This happens on the first start after the upgrade before the fetch finishes,
when offline with no cache, or with an empty URL (finding 4).

- **A. Today's resolution:** use the Coseeing default. The text goes to the
  Coseeing server (guest quota or the Coseeing account) instead of the
  provider the user chose. Startup also starts a silent Coseeing sign-in.
- **B. Refuse with a message** (the two strings in §13.4), keep the stored
  selection, and skip the startup Coseeing sign-in for this user.
  `normalize_selection()` is unchanged; the check lives in `correctTypo()` and
  at startup, keyed on the raw stored channel and `source == none`.
- **C. A, plus the existing degraded announcement** ("The model list could not
  be loaded. Coseeing will choose a model for you.") once per session.

**Recommended: B.** Text is never sent to a processor the user did not choose,
and the message says what to fix.

**Decided by the user (2026-11-04): a new option D** (U7, §12.5): say that the
model list is not available yet and ask, in a Yes/No dialog, whether to
switch to the Coseeing default. Yes saves `(default, Coseeing)` and corrects
the text with Coseeing; No sends nothing and keeps the stored selection. No
Coseeing sign-in at startup for this user. The two option-B strings in §13.4
are replaced by the dialog strings.

### What could start before the answers

Everything in §16.3 steps 1–2 except the OQ2 and OQ3 code paths and their tests.
All three answers arrived on 2026-11-04, so nothing waits any more.

## 19. Verification and baseline

Baseline at `774560b` in `/workspace/WordBridge-remote-catalog`:

```bash
cd /workspace/WordBridge-remote-catalog && /tmp/claude-0/-workspace-WordBridge/9af55a63-c255-4088-9b3c-fe363afb236f/scratchpad/testvenv/bin/python -m pytest -q --ignore-glob='tests/test_integration_*' tests
# 460 passed, 1 skipped
cd /workspace/WordBridge-remote-catalog/server && /workspace/WordBridge/server/.venv/bin/python -m pytest -q
# 81 passed
cd /workspace/WordBridge-remote-catalog && prek run --all-files   # all Passed
git diff --check
```

- `tests/test_integration_*.py` call paid live APIs and are excluded from
  routine verification.
- `server/app/package/coseeing_auth/storage` is a symlink to the main checkout
  (the root `.gitignore` `storage` rule keeps that directory out of git, a
  pre-existing problem). Never stage it.
- Linux tests cover only the injected boundaries. NVDA on Windows, real TLS,
  real proxies and the Windows file system are covered only by §17.6.

## 20. Risks

- **The remote catalog controls more than URLs.** Within the allowlisted hosts,
  a payload still sets provider `setting` (request parameters sent with the
  user's key), `timeout0`/`timeout_max`, `pricing` (only the displayed cost)
  and labels. Only the URL host is protected (U2). A hostile or mistaken
  payload could raise token limits or show misleading prices. Mitigation in this
  phase: TLS, the allowlist, the default URL being Coseeing's own host, and the
  user's explicit choice of any other URL.
- **Deployment order** (finding 5): the server's `GET /` must be live before the
  add-on release.
- **First-start window:** on the first start after upgrading, about a second
  with only `default`. Its behaviour for local users is OQ3.
- **Abandoned threads:** a fetch blocked in a socket read survives
  `terminate()` as a daemon thread (as correction workers already do). It
  cannot write or post (§11.3, step 2).
- **Server/add-on `lib/catalog` copies diverge** (§3). There is no test linking
  them today, and the server does not import the changed modules.

## 21. Acceptance criteria

1. NVDA startup performs no network I/O on the main thread, and importing the
   add-on reads no `setting/` file and performs no network I/O
   (`tests/test_import_purity.py`).
2. With the target files applied, a successful fetch of the shipped server file
   gives exactly the provider groups, local items, labels and prices of today,
   with Coseeing `default` only (§7.4).
3. With no cache and a failing fetch, the add-on loads, the panel opens, and
   only `default` is offered, with the status line.
4. A cache is used only for the URL it came from. A corrupt cache never stops
   the add-on loading.
5. A provider whose URL host is not allowlisted never reaches `ProviderEntry`
   (asserted for every provider).
6. A changed URL triggers exactly one fetch. An unchanged save triggers none.
   There is no periodic fetch.
7. `GET /` serves the server catalog byte for byte.
8. The full non-integration suites are green at every commit. prek passes.
   `git diff --check` is clean.
