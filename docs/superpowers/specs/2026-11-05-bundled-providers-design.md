# Bundled provider entries; the remote catalog supplies models only

- **Branch:** `feat/bundled-providers` (from `main` at `a28dc29`)
- **Workflow:** normal flow (DEVELOPMENT_WORKFLOW.md §3). Nothing has to be
  byte-identical to a known build: the bundled provider block must be
  *equal* to the server's, and a test proves that (§11), so the complex flow
  (§4) does not apply.
- **Predecessors:** `docs/superpowers/specs/2026-11-04-remote-catalog-design.md`
  (cited as "RC §n" / "RC Dn" / "RC Un") and
  `docs/superpowers/specs/2026-11-04-catalog-retry-design.md` (cited as
  "CR §n" / "CR Rn" / "CR Cn"). This spec **amends** both; §15 lists every
  section it supersedes. Their handoff records
  (`docs/superpowers/finish/2026-11-04-remote-catalog.md`,
  `docs/superpowers/finish/2026-11-04-catalog-retry.md`) were read first. The
  catalog-retry record lists this feature as its follow-up ("後續工作").

Paths are relative to `addon/globalPlugins/WordBridge/` unless they start with
`tests/`, `docs/`, `server/` or `/workspace/nvda/`.

## 1. Problem

Since RC, the add-on takes the whole local channel from the remote payload:
`overlay_documents()` builds `providers` from the remote document, filtered by
the host allowlist, and `models` from the remote document
(`lib/catalog/overlay.py:30-41`). The bundled file may carry only
`schema_version` and `coseeings` (`setting/catalog.json:1-10`); provider
entries found there are ignored with the lint issue
`ignored_bundled_local_entries` (`lib/catalog/overlay.py:23-28`).

A provider entry is `label`, `url`, `setting` (the request parameters sent with
the user's personal API key), `timeout0` and `timeout_max`
(`lib/catalog/document.py:11`, `:71-78`). Keeping it remote buys nothing and
costs safety:

1. **The provider set is fixed by code anyway.** A provider is usable only if
   it is in `SUPPORTED_PROVIDERS = frozenset(PROVIDER_CLASSES) &
   frozenset(ADAPTER_CLASSES)` (`lib/llm/__init__.py:27`; the six classes at
   `lib/llm/provider.py:188-195` and `lib/llm/adapter.py:140-147`), and only if
   it has a host rule in `PROVIDER_URL_RULES` (`lib/catalog/remote.py:172-183`).
   The settings panel's account boxes are created from `SUPPORTED_PROVIDERS`
   too (`dialogs.py:80-84`, CR R13). A remote document can never add a
   provider.
2. **The `setting` format is coupled to the adapters.** Each provider class
   merges `setting` into its own request shape; a server-side change to it
   that the installed adapter does not expect breaks corrections.
3. **The allowlist protects only the host.** Within an allowed host, the
   remote payload still sets the parameters sent with the user's key and the
   timeouts (RC §20, first risk). Moving the entries into the add-on removes
   that exposure entirely.

## 2. Goals

1. The add-on's bundled `setting/catalog.json` carries `schema_version`,
   `providers` and `coseeings`. Its `providers` block is exactly the server's
   (`server/app/setting/catalog.json:3-77`: Anthropic, DeepSeek, Google,
   Ollama, OpenAI, OpenRouter), tab-indented like the rest of the file.
   Target content (shown with spaces; the provider block is elided here and
   is copied verbatim from the server file):

   ```json
   {
     "schema_version": 1,
     "providers": { "Anthropic": { ... }, "DeepSeek": { ... }, "Google": { ... },
                    "Ollama": { ... }, "OpenAI": { ... }, "OpenRouter": { ... } },
     "coseeings": [
       { "model": "default", "label": "default", "active": true }
     ]
   }
   ```

2. For the add-on, the remote payload supplies only `models` (with their
   labels, `active`, `pricing` and `usage_key`). Remote `providers` and
   `coseeings` are ignored.
3. `server/app/setting/catalog.json` keeps its `providers` (the server's own
   correction calls need them, `server/app/correction_config.py:46-51`,
   `server/app/main.py:194-221`), but `GET /` stops sending them: it serves
   the catalog document without the `providers` key (B2, §12). — Decided by
   the user (2026-11-05); this replaces "the server is unchanged".
4. A test keeps the two `providers` blocks equal (§11).
5. With the shipped files, nothing the user sees or hears changes (§6).

## 3. Non-goals

- Moving `models`, prices or labels into the add-on. They stay remote; that is
  the point of RC.
- Changing the server's catalog file or its correction calls (§12). (`GET /`
  does change, B2.)
- Bumping `schema_version` (§9.3).
- Changing the fetch, cache format, retry schedule, panel layout or the U7
  dialog (RC §8, §10, §12.5; CR §7–§11).
- Fixing `lib/llm/provider.py:88`, `:122` (`str(e)` in the log), listed as out
  of scope in the RC handoff record.
- Letting a custom catalog URL override provider parameters. That capability
  goes away by design (§5, finding 5).

## 4. Decisions

### 4.1 Decided by the user (2026-11-04)

| # | Decision |
| --- | --- |
| B2 | **The server stops sending `providers`.** `GET /` serves the catalog document without its `providers` key (`schema_version`, `models` and any other key), still validated once at startup, still `application/json` with `Cache-Control: no-cache`. The server file keeps `providers` for the server's own calls, and the drift test (§11) stays. The `2026.11.1-test-*` builds were never released, so their need for a `providers` mapping (finding 6) is not a constraint. — Decided by the user (2026-11-05) |
| B3 | **OQ1 → B.** A remote model whose provider is not bundled is lint: still logged as `unknown_provider`, not counted in the panel's dropped-entries line (§18). — Decided by the user (2026-11-05) |
| B4 | ~~**A payload that carries `providers` is rejected.**~~ Superseded by B5. — Decided by the user (2026-11-05) |
| B5 | **A payload's `providers` key is ignored, like every other key.** `check_remote_document()` checks only that the document is an object, `schema_version` is the integer `1` and `models` is a list; `providers`, whatever its value, is ignored silently (no issue, no log line), as P2 does for every other key. The overlay never reads it, so it cannot reach a `ProviderEntry`. Rejecting it guarded nothing, made `providers` the one key that refuses a payload, and dropped usable test-build caches; an allowlist of keys is not used either, since a new optional key would then refuse the payload on every installed add-on (breaking changes go through `schema_version`). Supersedes B4. — Decided by the user (2026-11-05) |
| B1 | **Provider entries are bundled.** The per-provider `label`, `url`, `setting`, `timeout0` and `timeout_max` move back into the add-on's `setting/catalog.json`, next to `coseeings`. The remote catalog then supplies only `models` to the add-on. The server keeps its `providers` and `GET /` keeps serving them; the add-on ignores the remote `providers`. Accepted cost: tuning a provider parameter needs an add-on release. — Decided by the user (2026-11-04) |

### 4.2 Decided by orchestrator with the recommended default; user may override before merge

Every row is marked `Decided by orchestrator with the recommended default;
user may override before merge`. None changes what a user sees or hears with
the shipped files; the reasoning is in the section named.

| # | Decision | Section |
| --- | --- | --- |
| P1 | Overlay: `providers` from the bundled file **when a remote document is given**, `{}` when there is none; `models` from the remote document; `coseeings` from the bundled file. | §7.3 |
| P2 | Remote `providers`, `coseeings` and every other remote key except `schema_version` and `models` are ignored **silently** (no issue, no log line) (B5). The lint code `ignored_remote_coseeings` is retired. | §7.2 |
| P3 | Bundled `models` are still ignored (U1: no snapshot of the remote list ships), now with the lint code `ignored_bundled_models` at location `bundled.models`. The code `ignored_bundled_local_entries` is retired. | §7.1 |
| P4 | The acceptance rule is unchanged: a payload is accepted when it leaves at least one selectable local model once overlaid. A payload rejected only because the bundled file offers no provider entry is reported as `bundled_source_failed` (detail `no_providers`), not `remote_no_models`. | §8 |
| P5 | `check_remote_document()` no longer requires `providers` and, by B5, does not reject it either. It still requires an object, `schema_version` exactly the integer `1`, and `models` a list. `schema_version` stays `1`. | §9 |
| P6 | The runtime host allowlist is removed (`PROVIDER_URL_RULES`, `ProviderUrlRule`, `_https_only`, `_url_problem`, `filter_provider_urls`, the issue code `disallowed_provider_url`, the probe kind `disallowed_hosts` and its tip string). It is replaced by test-level guards on the bundled file. | §10 |
| P7 | A drift test asserts that the add-on's bundled `providers` and the server's `providers` are equal, compared as canonical JSON text. It lives in the add-on suite (`tests/test_catalog_bundled.py`). | §11 |
| P8 | No migration; `cache_version` stays `1`; the cache keeps storing the payload as fetched. A cache that carries `providers` (every cache written before this release) loads, its `providers` ignored (B5). | §9.4 |
| P9 | ~~Remote models whose provider the bundled file does not have keep today's treatment until the user answers OQ1.~~ Superseded by B3 (OQ1 → B). | §8.2, §18 |
| P10 | The amendment is recorded only in this spec; RC and CR are not edited. | §15 |

P6 changes the **mechanism** of a user decision, RC U2 ("the add-on has a
built-in allowlist of hosts per provider … a remote provider whose `url` host
is not allowed … is dropped"). The goal of U2, that users' keys go only to the
hosts in the committed catalog, is met more strongly: no remote document can
name a provider URL at all, and the hosts are pinned by tests (§10.2). This is
flagged so the user can object; it changes nothing the user sees.

## 5. Findings

1. **The allowlist is dead once providers are bundled.** Its only caller is
   `overlay_documents()` (`lib/catalog/overlay.py:14`, `:39`). The bundled file
   ships inside the add-on with the code that would check it: anyone who can
   change the file can change the check. A runtime check of it guards against
   nothing a test cannot catch earlier.
2. **A user-visible tip becomes unreachable.** The URL dialog's "Test..."
   reports `disallowed_hosts` when every provider in a payload was refused
   (`catalog_updater.py:384-388`), shown as "The model list names only
   provider addresses WordBridge does not allow."
   (`catalog_url_dialog.py:67-70`; zh_TW at
   `addon/locale/zh_TW/LC_MESSAGES/nvda.po:619-622`). With remote providers
   ignored, that situation cannot occur: such a payload now tests "ok" if its
   models name bundled providers, or "no_models" otherwise. The string is
   removed (§13). This follows necessarily from B1; no decision is needed.
3. **The probe mapping has a trap.** `_probe_failure()` maps every `remote_*`
   code to `not_a_list` (`catalog_updater.py:158-165`); only the explicit
   `remote_no_models` branch in `_probe()` (`catalog_updater.py:384-388`)
   yields `no_models`. Removing the `disallowed_hosts` test must keep that
   branch, or a payload with no usable model would be reported as "not a
   WordBridge model list".
4. **A broken bundled file now also loses the local channel.** Today a
   missing or corrupt bundled file loses only `coseeings`, and D2 substitutes
   the sentinel (`lib/catalog/overlay.py:84-90`; pinned by
   `tests/test_catalog_overlay.py:114-126`). After B1 the provider entries have
   no second copy in the add-on (`FALLBACK_DOCUMENT["providers"]` is `{}`,
   `lib/catalog/fallback.py:13-18`), so every remote model is dropped as
   `unknown_provider` and the payload is rejected. That is a broken
   installation, not a state to recover from; P4 makes the log say so.
5. **Custom catalog URLs lose provider overrides.** Today a self-hosted
   catalog can, within the allowlist, change a provider's `setting`, timeouts,
   label, or Ollama's port (`PROVIDER_URL_RULES["Ollama"]` allows any port,
   `lib/catalog/remote.py:178-182`). After B1 those come from the add-on. No
   shipped user is affected: the default server sends the same values (§11),
   and its only Ollama model is inactive (`server/app/setting/catalog.json`,
   `qwen2`, `"active": false`). This is the accepted cost in B1.
6. **~~The server must keep sending `providers`.~~** The remote-catalog
   feature is not released (`buildVars.py:26` on `main` is `2026.9.3`); test
   builds exist (`WordBridge-2026.11.1-test-remote-catalog-1`,
   `WordBridge-2026.11.1-test-catalog-retry-1`), and their
   `check_remote_document()` rejects a payload without a `providers` mapping
   (`lib/catalog/remote.py:266-267`). **Amended (B2, Decided by the user
   (2026-11-05)):** those builds were never released, so they are not a
   constraint; `GET /` stops sending `providers`, and a tester on such a
   build gets "could not be updated" until they install this release. The
   server *file* still keeps `providers` for the server's own calls, and
   `schema_version` is still not bumped (§9.3).
7. **The server never sees add-on files.** The server image copies only
   `server/app`, `alembic` and `alembic.ini` (`server/Dockerfile:14-16`), and
   no server test reads `addon/`. The add-on suite already reads the server
   file (`tests/shipped_catalog.py:18-25`). So the drift test belongs in the
   add-on suite.
8. **Python equality is too loose for the drift test.** `True == 1` and
   `0.0 == 0`, so `dict == dict` would accept `"store": 1` for `false`-style
   drift or `"temperature": 0` for `0.0`. The comparison uses canonical JSON
   text (§11).
9. **The log-forgery test depends on remote provider names.**
   `tests/test_catalog_plugin_wiring.py:145-172` puts a forged provider name in
   the remote `providers` to reach `loggable()` through a
   `disallowed_provider_url` issue. After B1, remote text reaches issue
   details only through `repr()` of model fields
   (`lib/catalog/document.py:104`, `:107`, `:110`, `:129`). The test moves to
   a forged model `provider` (`unknown_provider` detail) and keeps its length
   and control-character assertions.
10. **The account boxes are unaffected.** `ACCOUNT_BOX_GROUPS` comes from
    `SUPPORTED_PROVIDERS` (`dialogs.py:84`), and captions come from
    `_provider_group_label()`, which uses the catalog's provider label or
    falls back to the group name (`dialogs.py:183-190`, `:600-603`). Every
    shipped label equals its key (`server/app/setting/catalog.json:5`, `:20`,
    `:31`, `:43`, `:52`, `:68`), so captions read the same whether the label
    comes from the bundled entry or the fallback.
11. **The direct bundled build in tests changes.**
    `tests/test_catalog_bundled.py:19-22` builds the bundled file with
    `build_catalog()` directly, not through the overlay. With providers in the
    file, `test_the_bundled_catalog_alone_offers_only_the_sentinel`
    (`:78-84`) would see six providers and six `unreferenced_provider` lint
    issues. The runtime never builds the bundled file directly
    (`catalog_updater.py:441-458` always goes through
    `load_overlay_catalog()`), so the test moves to the overlay with no remote
    document.

Nothing here contradicts B1. Findings 2 and 5 are user-visible consequences
that follow from it; OQ1 (§18) is the only open user-visible choice.

## 6. What NVDA users hear and see

- **With the default URL and the shipped server file:** no change. The
  provider groups, models, labels, prices, account boxes, status line and the
  dropped-entries line are the same as today, because the bundled providers
  equal the server's (§11) and `shipped_overlay()` is pinned to today's
  result (`tests/test_catalog_overlay.py:169-211`).
- **Offline with no cache, a rejected payload, or an empty or invalid URL:**
  no change. The catalog is bundled ⊕ nothing, which under P1 is exactly
  today's: Coseeing "default" only, no providers, no issues. The settings
  panel offers only Coseeing; only the Coseeing account box is shown for the
  default selection (`dialogs.py:641-652`); the status line follows RC §13.3
  and CR §10.5 unchanged (`dialogs.py:87-118`); NVDA+Alt+O with a stored local
  selection opens the same U7 dialog, keyed on `source == none`
  (`__init__.py:296-307`, RC §12.5).
- **With a cache written by a test build:** it loads with its `providers`
  ignored (B5, §9.4); its models use the bundled provider entries.
- **Corrections with a personal key:** the same request parameters, URL and
  timeouts as today, now always from the add-on.
- **"Test..." in the Model List URL dialog:** a payload's `providers` (any
  value) decides nothing (B5); the `disallowed_hosts` tip is gone
  (finding 2).
- **Self-hosted catalogs:** provider overrides have no effect (finding 5).
- **No new strings, no new speech.** One string is removed (§13).

## 7. Documents and overlay

### 7.1 Bundled document (P3)

`schema_version`, `providers` (§2.1) and `coseeings`. `BundledCatalogSource`
(`lib/catalog/sources.py`) is unchanged. A bundled `models` key is ignored
with the lint issue `CatalogIssue("ignored_bundled_models", "bundled.models",
"the bundled catalog may not carry models; they are ignored")`. This keeps
RC U1 ("no snapshot of the remote payload ships in the add-on") structural:
offline, the add-on still offers only the Coseeing default.

### 7.2 Remote document (P2)

For the add-on, the remote document is `schema_version` and `models`. Every
other key is ignored without an issue, exactly like the unknown top-level keys
RC §7.2 already ignores:

- `providers`: the default server no longer sends it (B2), but older caches
  and self-hosted catalogs carry it; a lint issue would add a warning line to
  the NVDA log on every start and every fetch for those
  (`__init__.py:365-372` logs every catalog issue as a warning).
- `coseeings`: the server stopped sending it in RC, and the bundled file is
  the only Coseeing source (RC U8). The informational lint
  `ignored_remote_coseeings` (`lib/catalog/overlay.py:33-38`) never counted in
  the panel (`lib/catalog/model.py:37-41`); one rule for every ignored key is
  simpler than keeping it for one key.

### 7.3 Overlay (P1)

`overlay_documents(bundled, remote) -> (document, issues)`:

| Output key | Source |
| --- | --- |
| `schema_version` | `1` |
| `providers` | `bundled["providers"]` when `remote` is a mapping; `{}` when there is no remote document |
| `models` | `remote["models"]`; `[]` when there is no remote document |
| `coseeings` | `bundled["coseeings"]` (D2's sentinel guarantee unchanged, `lib/catalog/overlay.py:80-91`) |

- **Why `{}` without a remote document.** Provider entries without models are
  inert: nothing is selectable on the local channel, so no provider is ever
  looked up for a correction, and the account-box captions read the same
  either way (finding 10). Including them would make `build_catalog()` emit
  one `unreferenced_provider` lint issue per provider
  (`lib/catalog/document.py:36-38`), i.e. six new warning lines in the NVDA
  log on every offline start and every bundled-only install (D8). With `{}`,
  the bundled-only catalog is byte-for-byte today's: sentinel only, no issues.
- A bundled `providers` value that is not a mapping, or an incomplete entry,
  is passed through for `build_catalog()` to report (`malformed_document`,
  `incomplete_provider`, `lib/catalog/document.py:48-79`), as today for any
  document. The guard tests (§10.2) make that impossible to ship.
- The remote `providers` value is never read, so its shape no longer matters.
- With a remote document, `unreferenced_provider` for `OpenRouter` (no model
  names it) is still the one lint issue of the shipped overlay, as today
  (`tests/test_catalog_bundled.py:110-115`).
- `OverlaySource`, `load_overlay_catalog()` and `has_local_items()` keep their
  signatures.

## 8. Acceptance

### 8.1 Rule (P4)

`accept_remote_document(bundled_source, document, *, runnable_providers)`
(`lib/catalog/overlay.py:102-123`) keeps its order and its rule:

1. `check_remote_document(document)` (§9). A failure rejects the payload.
2. Overlay and build. If the result is `degraded` (the bundled source
   raised), reject with `bundled_source_failed` / `unreadable_source`, as
   today.
3. **New:** if the built catalog has no provider entries at all, reject with
   `CatalogIssue("bundled_source_failed", "bundled", "no_providers")`. Under
   P1 providers come only from the bundled file, so an empty set means the
   bundled file is missing, unreadable or lacks its `providers` (finding 4).
   Reporting `remote_no_models` would send whoever reads the log to the
   server.
4. If at least one local item is selectable, accept. Otherwise reject with
   `remote_no_models`.

The same function accepts a cached payload (`catalog_updater.py:441-458`), so a
later add-on release that removes or renames a bundled provider re-checks old
caches, as RC §8.4 intended for the allowlist.

Retry behaviour (CR C1) is unchanged: a rejected fetch is a failed fetch and
arms the retry, whatever the code.

### 8.2 Remote models and the provider set

| A remote model whose `provider` … | Result | Panel line |
| --- | --- | --- |
| is a bundled provider and in `runnable_providers` | kept | — |
| is not a bundled provider | dropped, `unknown_provider` (`lib/catalog/document.py:106-108`) | logged, not counted (B3, OQ1 → B) |
| is a bundled provider but not in `runnable_providers` | dropped, `unsupported_provider` (`:109-111`) | counted |

In production `runnable_providers` is `SUPPORTED_PROVIDERS`
(`__init__.py:276-280`) and the guard test pins the bundled provider names to
exactly that set (§10.2), so the third row occurs only in tests that inject a
smaller set. Entry-level drops never reject a payload unless no local model is
left (§8.1, step 4).

### 8.3 Probe

`CatalogUpdater._probe()` (`catalog_updater.py:366-389`) keeps the same
mapping minus `disallowed_hosts`:

| Kind | When |
| --- | --- |
| `ok` | accepted; `models` = selectable local items |
| `no_models` | `remote_no_models` (explicit branch kept, finding 3) |
| `failed` | `bundled_source_failed` (both details) and anything else, as today |
| others | unchanged (CR §20.3) |

## 9. Document checks, schema and cache

### 9.1 `check_remote_document()` (P5)

`lib/catalog/remote.py:249-270`. Required: an object; `schema_version` of type
`int` and equal to `1`; `models` a list. Every other key, `providers`
included, is ignored (B5, Decided by the user (2026-11-05)). The "providers
must be a mapping" check (`remote.py:266-267`) is removed. Its docstring and
`parse_remote_payload()`'s are updated.

### 9.2 Why not keep requiring `providers`

The default server omits `providers` (B2, §12). A payload that still
carries them is accepted with them ignored (B5): the overlay never reads
them, so rejecting them would guard nothing.

### 9.3 `schema_version`

Stays `1`. The served document only loses a key this add-on ignores, and
`check_remote_document()` no longer requires it (§9.1). A bump gains
nothing; the tester builds of finding 6 reject the providers-less payload
either way, which B2 accepts.

### 9.4 Existing caches (P8, B5)

Caches are `{"cache_version": 1, "url_key": …, "document": <the payload as
fetched>}` (`lib/catalog/cache.py:69-108`). Caches written before this
release (only test builds) contain the server's `providers`. At load
(`catalog_updater.py:441-458`) the document goes through
`accept_remote_document()`, which ignores them (B5): the cache loads as
`source=cache` with the bundled provider entries, and nothing is logged.

- No migration, no `cache_version` bump, no rewrite on load. The next
  successful fetch overwrites the file as today.
- A cache that holds a hostile `providers` block loads, and its values
  never reach a `ProviderEntry` (tested, §17.1).
- The cache keeps storing the payload as fetched, `providers` included when
  a server sends them; they are ignored again at every load.
- The `cache.py` module docstring ("stored before allowlist filtering",
  `cache.py:4-5`) becomes "stored as fetched, so whichever add-on version
  loads it applies its own bundled providers and rules".

## 10. The host allowlist (P6)

### 10.1 Removed from the runtime

From `lib/catalog/remote.py`: `ProviderUrlRule` (`:157-161`), `_https_only`
(`:164-165`), `PROVIDER_URL_RULES` (`:172-183`), `_url_problem` (`:186-214`),
`filter_provider_urls` (`:217-242`), and the comment above the table
(`:168-171`). `_split`, `_DEFAULT_PORTS` and `_host_text` stay; they serve
`validate_catalog_url()` and `redact_url()` (`:55-130`). `urllib` stays in
`lib/catalog`'s standard-library list (`tests/test_catalog_document.py:287`).

Also removed: the `filter_provider_urls` import and call
(`lib/catalog/overlay.py:14`, `:39`); the `disallowed_hosts` branch in
`_probe()` (`catalog_updater.py:385-387`) and its mention in the
`ProbeResult` docstring (`:145`); the tip in `_failure_tip()`
(`catalog_url_dialog.py:67-70`); the `disallowed_provider_url` issue code
everywhere. The R13 comment above `ACCOUNT_BOX_GROUPS` (`dialogs.py:80-83`)
stays true ("build_catalog drops them") and needs no change.

Keeping the code as a guard on the bundled file was considered and rejected:
it would run on data that ships with the code that checks it (finding 1), and
a failing check at runtime could only drop a provider for every user of that
release, which a test catches before release instead.

### 10.2 Replaced by test-level guards (`tests/test_catalog_bundled.py`)

- The bundled file's keys are exactly `{"schema_version", "providers",
  "coseeings"}`.
- `set(bundled["providers"]) == SUPPORTED_PROVIDERS`. This replaces
  `test_rules_cover_exactly_the_supported_providers`
  (`tests/test_catalog_provider_allowlist.py:140-141`): a new provider class
  cannot ship without a bundled entry, and a bundled entry cannot ship without
  a class.
- The full URL of every bundled provider is pinned in a table in the test
  (the six URLs of `server/app/setting/catalog.json:6`, `:21`, `:32`, `:44`,
  `:53`, `:69`). Changing a URL means changing the test deliberately.
- Every non-Ollama URL is `https` on the default port with no user info,
  query or fragment, and its host is the one RC §9 allowed for it
  (`api.anthropic.com`, `api.deepseek.com`,
  `generativelanguage.googleapis.com`, `api.openai.com`, `openrouter.ai`).
  Ollama's host is `localhost` or `127.0.0.1`. This carries RC §9's table
  into the test so the reasoning survives.
- `build_catalog()` of the bundled file with a remote document that names
  every provider yields six `ProviderEntry` objects and no dropped issue (no
  `incomplete_provider`, no `malformed_document`).

## 11. Drift guard between add-on and server (P7)

`tests/test_catalog_bundled.py`:

```python
def _canonical(value):
	return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

def test_the_bundled_providers_equal_the_server_providers():
	assert _canonical(bundled_document()["providers"]) == _canonical(server_document()["providers"])
```

- Canonical text, not `==`, because of finding 8 (`json.dumps` writes `0.0`
  and `0` differently, and `false` and `0` differently).
- The add-on suite, because the server image and suite never see the add-on
  (finding 7) and the add-on suite already reads the server file through
  `tests/shipped_catalog.py`.
- On failure the message names the first differing provider (a small loop
  before the assertion), so a reviewer sees which side to update.
- When a provider parameter changes, both files change in the same commit;
  the add-on change ships with the next release, the server change with the
  next deployment. The test makes a one-sided edit fail the add-on suite,
  which is run before every commit and merge (DEVELOPMENT_WORKFLOW.md §7).
  CI does not catch it: `.github/workflows/build_addon.yml` builds the add-on
  and runs no pytest.

## 12. Server

Amended by B2 (Decided by the user (2026-11-05)); this replaces "Unchanged".

- **Unchanged:** `server/app/setting/catalog.json` (keeps `providers`),
  `server/app/correction_config.py`, and the server's `lib/catalog` copy
  (`server/app/lib/catalog/fallback.py` and `document.py` are identical to
  the add-on's today and stay so; the overlay and remote modules are
  add-on-only, RC §3).
- **Changed:** `server/app/main.py` `load_catalog_bytes()` (`:43-59`) still
  reads and validates the file once at startup (a JSON object with
  `schema_version` 1, otherwise `ValueError`), and returns the bytes of the
  document **without its `providers` key**; every other key is kept in file
  order. `GET /` (`:164-171`) serves those bytes, `application/json`,
  `Cache-Control: no-cache`. The docstrings no longer say "verbatim".
- **Tests** (`server/tests/test_catalog_route.py`): the response has no
  `providers`; its `models` equal the file's `models`; startup still rejects
  a bad file; the other keys survive. The server count grows from 103.
- The add-on suite's `tests/shipped_catalog.py` models the served payload as
  the server file minus `providers`; `shipped_overlay()` uses it.
- **Deployment order: either.** A new add-on ignores `providers` (B5), so
  it works with the production server before and after this change. The new
  server is safe for every add-on that reads models only; the
  `2026.11.1-test-*` builds stop updating (finding 6, B2).

## 13. Strings

No new strings. One string is removed with its `# Translators:` comment
(`catalog_url_dialog.py:67-70`):

| English | zh_TW (removed from `nvda.po:619-622`) |
| --- | --- |
| `The model list names only provider addresses WordBridge does not allow.` | `這份模型清單列出的服務提供者網址都不在 WordBridge 允許的範圍內。` |

The `.po` entry is deleted in the same commit rather than left for `scons pot`
to mark obsolete, and `msgfmt --check` is run.

## 14. Logging

- Remote provider entries are never logged; they are never read.
- No new log lines. With the shipped files the log is the same as today: one
  `unreferenced_provider` warning for OpenRouter per installed fetched or
  cached catalog, none for the bundled-only catalog (P1).
- `bundled_source_failed` / `no_providers` is logged through the existing
  fetch-failure and cache-problem lines (`catalog_updater.py:468-470`,
  `:519-545`), type only, as RC D15 requires.

## 15. What this changes in the predecessor specs

The amendment is stated here; RC and CR are not edited (P10). Superseded or
changed:

| Spec section | Old | Now |
| --- | --- | --- |
| RC §2.3, RC U4 (bundled part) | The bundled file keeps only `schema_version` and `coseeings` | It also carries `providers` (§2.1, B1) |
| RC §2.4 | The server file is "the single source of truth for local-channel data" | It is the source of `models`; `providers` exist twice, kept equal by §11 |
| RC D1, RC §7.3 | The local channel (`providers`, `models`) comes only from the remote payload; keys in the wrong document are ignored with a lint issue | §7.3 table: `providers` and `coseeings` from bundled, `models` from remote; remote extras ignored silently (P2); bundled `models` ignored with `ignored_bundled_models` (P3) |
| RC §7.1 | Bundled may contain only `schema_version` and `coseeings` | §7.1 |
| RC §7.2 | Remote carries `providers`; remote `coseeings` ignored with `ignored_remote_coseeings` | §7.2 |
| RC §7.4 | Shipped result | Unchanged in content; now produced by bundled providers |
| RC §8.3, §8.4 | `providers` must be a mapping; caches "re-filtered" by the allowlist | §9.1; §8.1 step 3; caches re-checked against bundled providers |
| RC U2 (mechanism), RC §9, RC §14 "provider issues name the provider and the host only" | Runtime host allowlist | Removed; test guards (§10) |
| RC §10 cache format note | Payload "stored before allowlist filtering" | Stored as fetched (§9.4) |
| RC §17.1 allowlist, overlay and payload bullets; RC §17.3 Mistral case; RC §17.6 item 8 | Allowlist tests and manual check | §17 |
| RC §20, first risk | Remote controls provider `setting` and timeouts | Resolved; what remains is in §20 |
| RC §21 AC5 | "A provider whose URL host is not allowlisted never reaches `ProviderEntry`" | No remote provider value ever reaches `ProviderEntry` (§21) |
| CR R13 (justification only) | "`PROVIDER_URL_RULES` has rules only for these" | The bundled file has entries only for these (§10.2); the R13 behaviour is unchanged |
| CR C1 | "`remote_no_models` (including 'every provider was disallowed')" | The parenthesis no longer applies; a payload with dropped *models* is still a success |
| CR C16, §20.3 | Test runs "the provider host allowlist"; kind `disallowed_hosts` | §8.3 |
| CR §20.5 | tip `disallowed_hosts` string | Removed (§13) |

## 16. Tests that change

Measured against `main` at `a28dc29`. Each row is rewritten, not just deleted,
so the protection it gave moves to the new rule.

| File | What changes |
| --- | --- |
| `tests/test_catalog_provider_allowlist.py` (whole file) | Removed with the code it tests; its supported-provider and host assertions move to §10.2 |
| `tests/test_catalog_overlay.py:54-66` | Providers now come from bundled; remote providers ignored |
| `tests/test_catalog_overlay.py:68-75` | Remote `coseeings` ignored with **no** issue |
| `tests/test_catalog_overlay.py:78-85`, `:95-111` | `ignored_bundled_models` replaces `ignored_bundled_local_entries`; bundled providers are not used without a remote document |
| `tests/test_catalog_overlay.py:114-126` | Broken bundled file plus good remote: rejected with `bundled_source_failed` / `no_providers` when accepted; still offers the sentinel undegraded when loaded |
| `tests/test_catalog_overlay.py:154-159` | Becomes "a remote provider with a foreign URL is ignored; the bundled entry is used" |
| `tests/test_catalog_overlay.py:162-166` | `OverlaySource` with bundled providers |
| `tests/test_catalog_bundled.py:19-22`, `:69-84` | Bundled keys and the bundled-only catalog through the overlay (finding 11); plus §10.2 and §11 |
| `tests/test_ai_config_schema.py:12-26` | Bundled file is sentinel plus the server's providers; docstrings |
| `tests/test_catalog_payload.py:36-37` | `providers-list` / `providers-missing` now parse (code `None`) |
| `tests/test_catalog_payload.py` `ACCEPT_DOCUMENT_TABLE` `providers-list` row, `:105-113` | Row removed; `test_only_disallowed_hosts_is_rejected` becomes "only unknown providers is rejected with `remote_no_models`" |
| `tests/test_catalog_source_seam.py:89-111` | No `PROVIDER_URL_RULES` patch; a Mistral provider in the remote payload is ignored and its model dropped as `unknown_provider`; `unsupported_provider` is exercised with a `runnable_providers` set lacking one bundled provider |
| `tests/test_catalog_plugin_wiring.py:145-172` | Forged text in a model's `provider` (finding 9) |
| `tests/test_catalog_retry.py:215` | `all-providers-disallowed` → `only-unknown-providers` (still a failure that arms a retry) |
| `tests/test_catalog_retry.py:232-238`, `:270-274` | `dropped-provider` → `dropped-model` (one model naming an unknown provider beside a good one: success, no retry) |
| `tests/test_catalog_retry.py:1037` | `disallowed` probe row → `providers-ignored` (`ok`, B5) plus `unknown-providers-only` (`no_models`) |
| `tests/test_catalog_url_dialog.py:418-419` | `disallowed_hosts` row removed |
| `tests/shipped_catalog.py:1-8` | Docstring: providers are bundled; models come from the server file |

Tests that build from the server file (`tests/test_provider_naming.py`,
`tests/test_provider_model_adapter_unittest.py`,
`tests/test_task_architecture_unittest.py`, `tests/test_eval_provider_config.py`,
`tests/test_helpers.py`, `workspace/evals/provider.py`) keep doing so; with §11
both files carry the same providers, so they need no change.

### 16.1 Commit ordering (every commit green)

1. Bundled file gains `providers`; overlay takes providers from it (P1) and
   bundled `models` lint is renamed (P3); remote `coseeings` silent (P2);
   §10.2 and §11 tests added; the tests in §16 that pin the old overlay are
   migrated in the same commit. `filter_provider_urls` is no longer called
   but still exists with its own tests.
2. Acceptance `no_providers` (P4) and the relaxed `check_remote_document()`
   (P5), with their tests.
3. Removal of the allowlist code, probe kind, tip string and `.po` entry
   (P6), with the rewritten retry, probe, dialog, seam and wiring tests.
4. Only if the user answers OQ1 with B: the lint classification and its
   tests.

## 17. Test plan

Hypothesis and mutmut are not dependencies of this repository; property-style
coverage is table-driven and mutation checks are manual, on a scratch copy, as
in RC §17 and CR §15.

### 17.1 Unit tests (no NVDA, no network)

- **Overlay** (`tests/test_catalog_overlay.py`):
  - A remote document whose `providers` differ from the bundled ones in
    `url` (foreign host), `setting`, `timeout0`, `timeout_max` and `label`
    gives `catalog.get_provider(name)` equal to the bundled entry for every
    field, and no issue mentions `providers`.
  - A remote document with no `providers` key, and one with `providers: []`,
    give the same catalog as the server file.
  - Remote `coseeings` ignored: Coseeing labels are the bundled ones and
    `issues == ()`.
  - Bundled `models` ignored with exactly one `ignored_bundled_models` issue,
    `is_dropped_issue()` false.
  - No remote document: `providers == {}`, `models == ()`, provider groups
    `("Coseeing",)`, `issues == ()`, not degraded.
  - A remote model naming a provider the bundled file lacks is dropped with
    `unknown_provider`; its siblings are kept.
  - `overlay(shipped bundled, shipped server)` still equals RC §7.4 and the
    direct build of the server file (`tests/test_catalog_overlay.py:169-211`),
    including `catalog.providers == today.providers`.
- **Acceptance** (`tests/test_catalog_payload.py`): accepted for the server
  file; `remote_no_models` for only inactive, only unknown-provider and empty
  `models`; `bundled_source_failed` / `no_providers` for a bundled source
  returning `None` with `unreadable_file`, and for a bundled document without
  `providers`; `bundled_source_failed` / `unreadable_source` for a raising
  source (unchanged); the parse table rows of §16.
- **Cache** (`tests/test_catalog_cache.py` or `tests/test_catalog_updater.py`):
  a cache holding the served document (no `providers`) loads as
  `source=cache` and equals `shipped_overlay()`; a cache that carries
  hostile `providers` loads as `source=cache` with the bundled entries and
  logs no warning (B5).
- **Guards and drift** (`tests/test_catalog_bundled.py`): §10.2 and §11.
- **Probe** (`tests/test_catalog_retry.py` probe table): `ok` for a payload
  carrying `providers` (B5); `no_models` for unknown providers only;
  `failed` for `no_providers`.
- **Dialog text** (`tests/test_catalog_url_dialog.py`): every `ProbeResult`
  kind the updater can return has a row; no row for `disallowed_hosts`.

### 17.2 NVDA-stubbed tests

- Plugin wiring: the forged-text test of finding 9; a fetched server payload
  installs a catalog whose provider entries are the bundled ones (identity of
  values with `bundled_document()["providers"]`).
- Settings panel: `test_the_dropped_entries_line_is_silent_for_the_shipped_overlay`
  (`tests/test_catalog_settings_panel.py:305`) unchanged and green; account
  box captions for the shipped overlay and for the bundled-only catalog are
  the same strings.
- No test performs a real HTTP request (existing harness rule, RC §17.2).

### 17.3 Mutation checks (manual, scratch copy)

Each mutant must be killed by a named test; the result goes in the review.

| Mutant | Killed by |
| --- | --- |
| Overlay reads `remote["providers"]` again | remote providers ignored (§17.1, first overlay bullet) |
| Overlay includes bundled providers with no remote document | no remote document: `providers == {}`, `issues == ()` |
| Overlay uses bundled `models` | `ignored_bundled_models` test (models not used) |
| `check_remote_document()` still requires `providers` | `providers-missing` parse row; cache without `providers` |
| Acceptance drops the `has_local_items` check | `remote_no_models` rows |
| Acceptance drops the `no_providers` branch | broken-bundled acceptance test (expects `bundled_source_failed`) |
| `_probe()` loses the `remote_no_models` → `no_models` branch | `unknown-providers-only` probe row (finding 3) |
| Drift test compares with `==` while one bundled value changes `0.0` → `0` or `false` → `0` | the drift test itself, run against the mutated bundled file |
| One bundled provider URL changed to another host | the pinned URL table (§10.2) |

### 17.4 Windows/NVDA manual checks

On an installed add-on built from the branch:

1. Upgrade over `WordBridge-2026.11.1-test-catalog-retry-1` with its cache in
   place, online, against a server that already runs §12: the first start
   logs `catalog source=cache` and no `catalog cache problem` line (the test
   build's cache carries `providers`, ignored by B5); the panel lists the
   same providers and models as before the upgrade, with no dropped-entries
   line, before and after the fetch succeeds.
2. The same upgrade, offline: the old cache loads the same way, so the
   cached models are offered and the status line reads "could not be
   updated" (RC §13.3), not "could not be loaded".
3. Fresh config, offline, stored local model: only Coseeing "default";
   NVDA+Alt+O opens the U7 dialog exactly as before.
4. A correction with a personal key for each of OpenAI, Anthropic, Google and
   DeepSeek succeeds (same parameters as before).
5. Local catalog server (`http://localhost:8000`) serving the server file
   with OpenAI's `url` changed to `http://127.0.0.1:9999/capture` and a
   listener on that port: "Test..." says the list loaded; after saving, an
   OpenAI correction goes to `api.openai.com` and the listener receives
   nothing.
6. The same server serving only models of a provider named `Mistral`:
   "Test..." says "The model list offers no model WordBridge can use."
7. The same server serving the server file plus one `Mistral` model: no
   dropped-entries line (OQ1 → B); the NVDA log has one `unknown_provider`
   warning.
8. Account box captions and Tab order unchanged (CR §15.6 items 7a, 7b).

## 18. Open questions for the user

### OQ1. Should a remote model whose provider this add-on does not have be counted as "could not be loaded"?

**Decided by the user (2026-11-05): B** (B3).

With providers bundled, the server can serve models for a provider that only
a **newer** add-on release has (that is now the only way to add a provider).
An older add-on drops those models with `unknown_provider`, and today that
issue is counted in the panel line "{count} catalog entries could not be
loaded; see the NVDA log for details." (`dialogs.py:152-169`,
`lib/catalog/model.py:37-51`). Users of the older add-on would see that line
until they update, and cannot fix it otherwise.

- **A. Keep today's rule** (counted). A provider-name typo on the server is
  visible in the panel, but so is every model meant for newer releases.
- **B. Treat `unknown_provider` as lint** (add it to `LINT_ISSUE_CODES`): still
  logged as a warning, not counted in the panel. `unsupported_provider` stays
  counted (it can only occur if the bundled file and the code disagree, which
  §10.2 prevents).
- **C. B, plus skip the log line** for remote models with an unknown provider.
  Quieter, but a server typo would leave no trace.

**Recommended: B.** The panel line is meant for "something that should have
loaded did not"; models for a provider the installed release does not have
are expected after B1. The log keeps the detail.

~~Until answered, the spec follows A (P9), which changes nothing visible.~~
Answered B: `unknown_provider` joins `LINT_ISSUE_CODES`.

## 19. Verification and baseline

Baseline at `a28dc29` in `/workspace/WordBridge-bundled-providers` (re-run by
the spec writer on 2026-11-05):

```bash
cd /workspace/WordBridge-bundled-providers && /tmp/claude-0/-workspace-WordBridge/9af55a63-c255-4088-9b3c-fe363afb236f/scratchpad/testvenv/bin/python -m pytest -q --ignore-glob='tests/test_integration_*' tests
# 1053 passed, 1 skipped
cd /workspace/WordBridge-bundled-providers/server && /workspace/WordBridge/server/.venv/bin/python -m pytest -q
# 103 passed
cd /workspace/WordBridge-bundled-providers && prek run --all-files   # all Passed
git diff --check
```

- `tests/test_integration_*.py` call paid live APIs and are never run in
  routine verification.
- `server/app/package/coseeing_auth/storage` is a symlink to the main checkout
  and is never staged (RC §19).
- The server count grows from 103 by the `GET /` tests (§12, B2). The add-on count changes by the
  removed allowlist tests and the added guard, drift, overlay, acceptance and
  cache tests; the plan states the expected number per commit.

## 20. Risks

- **Two copies of the provider block.** Mitigated by §11; a deliberate
  parameter change now needs both files and an add-on release (B1's accepted
  cost).
- **The remote catalog still controls models, labels and prices.** A hostile
  or mistaken payload can still choose which model id is sent with the user's
  key, label it misleadingly, or show a wrong price. Only the provider URL,
  parameters and timeouts are now fixed. Mitigation as before: TLS, the
  default URL being Coseeing's own host, and the user's explicit choice of any
  other URL.
- **Deployment order.** Releasing the add-on before the server is updated
  makes every new add-on fail its fetches until the server is (§12).
- **Broken bundled file** loses the local channel (finding 4); logged as
  `bundled_source_failed` / `no_providers`.
- **Forward compatibility** of models for providers newer than the installed
  release: OQ1.

## 21. Acceptance criteria

1. The bundled `setting/catalog.json` has exactly `schema_version`,
   `providers` and `coseeings`, and its `providers` equal the server's as
   canonical JSON (§11).
2. No value from a remote or cached `providers` block ever reaches a
   `ProviderEntry` (asserted for every field and every provider).
3. With the shipped files, a successful fetch gives exactly today's provider
   groups, local items, labels, prices and provider entries (RC §7.4), and the
   bundled-only catalog is exactly today's (sentinel only, no issues).
4. A payload or cache is accepted when its models are usable, with or
   without a `providers` key (B5).
5. No cache migration; a rejected cache is replaced by the next successful
   fetch.
6. `PROVIDER_URL_RULES`, `filter_provider_urls` and `disallowed_provider_url`
   no longer exist in `addon/`; the `disallowed_hosts` string is gone from the
   code and from `nvda.po`.
7. The server file and correction calls are unchanged; `GET /` serves the
   document without `providers` and the server suite is green (B2).
8. The full non-integration suites are green at every commit; `prek` passes;
   `git diff --check` and `msgfmt --check` are clean.
