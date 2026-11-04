# Remote provider/model catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans.
> WordBridge normal flow: one implementer runs every task in order; the
> orchestrator dispatches the final Fable 5.1 review (DEVELOPMENT_WORKFLOW.md §3.3).

**Goal:** The add-on downloads its provider/model catalog from a configurable
URL (default `https://wordbridge.coseeing.org`), caches it per URL, and keeps
only the Coseeing `default` sentinel in the bundled file; the server serves the
catalog at `GET /`.

**Architecture:** Pure, standard-library-only building blocks in
`lib/catalog/` (`remote.py`: URL rules, provider host allowlist, payload
parsing; `overlay.py`: bundled ⊕ remote channel overlay and acceptance;
`cache.py`: atomic per-URL cache file). A plugin-root `catalog_updater.py`
owns the HTTP fetch (injected `requests.get`), the daemon fetch thread, the
generation counter and the status, and hands finished catalogs to the wx main
thread, where `GlobalPlugin._install_catalog()` swaps `registry`. The
settings panel gains a last "Model list URL:" field and a status line.

**Tech Stack:** Python 3.11 (NVDA add-on, standard library only inside
`lib/catalog`), NVDA's host `requests`, wxPython via NVDA `gui`, pytest
(table-driven, no Hypothesis/mutmut), FastAPI server.

**Spec:** `docs/superpowers/specs/2026-11-04-remote-catalog-design.md`
(committed at `0c3ad62`). Section numbers below (§n) refer to it. Paths are
relative to `addon/globalPlugins/WordBridge/` unless they start with
`server/`, `tests/`, `workspace/` or `docs/`.

## Global Constraints

- Branch `feat/remote-catalog`, worktree `/workspace/WordBridge-remote-catalog`; never touch `/workspace/WordBridge`.
- Every commit is green: add-on `…/testvenv/bin/python -m pytest -q --ignore-glob='tests/test_integration_*' tests` (baseline **460 passed, 1 skipped**), server `server/.venv … pytest -q` (baseline **81 passed**), `prek run --all-files` all Passed, `git diff --check` clean. Never run `tests/test_integration_*` (paid live APIs).
- `lib/catalog` imports only the standard library; `tests/test_catalog_document.py` `STDLIB_ONLY` gains exactly `os`, `tempfile`, `urllib` over the whole plan.
- `requests` is NVDA's host copy (`HOST_ONLY`, `lib/vendor.py`); it is injected into fetch code, never imported by `lib/catalog` or `catalog_updater.py`, never vendored.
- No test performs real HTTP or touches the real `WordBridge-workspace` root; caches in tests live under `tmp_path`.
- `_load_nvda_plugin` is imported at function scope, never at module scope (coseeing_auth import poisoning).
- The two target files are applied byte for byte, only inside the task that makes the code work with them (Task 10 for the add-on file, Task 16 for the server file); never committed alone.
- Fetch timing (U3): once after start via `wx.CallAfter`, and once after a saved URL change. No refresh button, no periodic fetch.
- HTTP call is exactly `http_get(url, stream=True, timeout=(5, 10), allow_redirects=False, headers={"Accept": "application/json"})`; 1 MiB (1,048,576 bytes) body limit; 20 s overall deadline; only status 200; `verify` never passed.
- Logging: URLs only as `redact_url()` (`scheme://host[:port]`); errors only as exception type names; never response bodies, `str(error)` or `exc_info`.
- Cache path `user_workspace_root() / "catalog" / "remote-catalog.json"`; written only when `NVDAState.shouldWriteToDisk()` is true; never deleted.
- New UI strings carry `# Translators:` comments and get the §13.4 zh_TW entries in `addon/locale/zh_TW/LC_MESSAGES/nvda.po`, checked with `msgfmt --check`.
- git: stage explicit paths only, check `git diff --cached --stat`; English `<type>: <summary>` messages with a why-body; no `Co-Authored-By`; no `--no-verify`, no push, no `git stash`. New files under `docs/` need `git add -f <path>`. Never stage `server/app/package/coseeing_auth/storage`.
- Deviations go to `.superpowers/sdd/2026-11-04-remote-catalog/progress.md` as `Ruling: <decision> — <reason> — <cost if wrong>`.
- Linux tests cover injected boundaries only; §17.6 (Windows/NVDA manual checks) is not covered by this plan's automation.

## Review Focus

1. **IME / full-width characters in the URL field** — a zh_TW user types `https：//…` (full-width colon) or pads the text with U+3000. Expected: the full-width colon is rejected as `invalid` without raising; U+3000 around the text is stripped (valid), U+3000 inside it is `invalid`. Covered by Task 1 (`test_validate_catalog_url_table` rows `fullwidth-colon`, `ideographic-space-padded`, `ideographic-space-inside`).
2. **Provider `url` that is not a string** (`5`, a list) in a remote payload — `build_catalog()` only rejects `""`/`None`, so a non-string would become `ProviderEntry.url` and break the provider call with the user's key. Expected: dropped with `disallowed_provider_url`, no exception. Covered by Task 2 (`test_provider_url_rules_table` rows `url-int`, `url-list`).
3. **UTF-8 BOM at the start of the payload** (a self-hosted catalog saved by Notepad) — Expected: accepted exactly like the same body without BOM (`json.loads(bytes)` detects it), never `remote_malformed`. Covered by Task 4 (`test_parse_remote_payload_table` row `utf8-bom`).
4. **Unusable `Content-Length` and empty keep-alive chunks** (`"abc"`, `"-1"`, `""`, `b""` chunks) — Expected: no exception; the header is ignored and the streamed 1 MiB limit decides; empty chunks count zero bytes. Covered by Task 6 (`test_unusable_content_length_falls_back_to_the_streamed_limit`, `test_empty_keepalive_chunks_are_skipped`).
5. **URL changed A → B → A before either fetch completes** — Expected: only the last generation installs; the live catalog is bundled ⊕ cache(A) again immediately; B's result is never installed or cached; A's first result is discarded. Covered by Task 8 (`test_url_changed_back_before_fetches_complete_installs_only_the_last`).

---

## File Structure

| File | Responsibility | Task |
| --- | --- | --- |
| `lib/catalog/remote.py` (new) | `DEFAULT_CATALOG_URL`, limits, `UrlCheck`, `validate_catalog_url`, `redact_url`, `PROVIDER_URL_RULES`, `filter_provider_urls`, `parse_remote_payload` | 1, 2, 4 |
| `lib/catalog/overlay.py` (new) | `overlay_documents`, `OverlaySource`, `load_overlay_catalog`, `has_local_items`, `accept_remote_document` | 3, 4 |
| `lib/catalog/cache.py` (new) | `CatalogCache` | 5 |
| `lib/catalog/model.py` | new lint codes in `LINT_ISSUE_CODES` | 3 |
| `lib/catalog/registry.py` | `replace(catalog)` | 7 |
| `settings_repository.py` | `catalog_url`, `save_catalog_url`, `corrector_selection(catalog=None)` | 7 |
| `catalog_updater.py` (new, plugin root) | `FetchResult`, `fetch_payload`, `UpdaterStatus`, `CatalogUpdater`, module `install/uninstall/request_refresh/status` | 6, 8 |
| `__init__.py` | config key, updater wiring, `_install_catalog`, one-snapshot `correctTypo`, `terminate` | 10 |
| `dialogs.py` | URL field, `isValid`, status line, save/refresh, D12 | 11, 12 |
| `setting/catalog.json` | target bundled content | 10 |
| `tests/shipped_catalog.py` (new) | `SERVER_CATALOG_PATH`, `server_document`, `bundled_document`, `shipped_overlay`, `TEMPORARY_LINT_CODES` | 9 |
| `server/app/main.py` | `GET /` | 13, 16 |
| `server/app/correction_config.py`, `server/app/setting/catalog.json` | OQ1, target server content | 16 |

## Batching

16 tasks, three batches (DEVELOPMENT_WORKFLOW.md §3.2): **Batch 1 = Tasks 1–5**
(pure `lib/catalog` modules), **Batch 2 = Tasks 6–10** (fetch, updater,
migration, wiring), **Batch 3 = Tasks 11–16** (panel, server, the three
decision-gated tasks; boundary moved by one so the OQ tasks stay together).
Tasks 14, 15 and 16 are `PENDING USER DECISION`; stop before each until the
answer arrives.

---

### Task 1: Catalog URL validation and redaction

**Files:**
- Create: `addon/globalPlugins/WordBridge/lib/catalog/remote.py`
- Modify: `tests/test_catalog_document.py:287` (`STDLIB_ONLY` += `"urllib"`)
- Test: `tests/test_catalog_remote_url.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `DEFAULT_CATALOG_URL = "https://wordbridge.coseeing.org"`, `MAX_URL_LENGTH = 2048`, `LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})`, `MAX_PAYLOAD_BYTES = 1_048_576`, `FETCH_TIMEOUT = (5, 10)`, `FETCH_DEADLINE_SECONDS = 20`, `CHUNK_BYTES = 65536`.
  - `@dataclass(frozen=True) class UrlCheck: url: str; key: str; error: str | None` with property `enabled -> bool` (`error is None and url != ""`). `error ∈ {None, "invalid", "insecure_scheme"}`; `key == ""` whenever the check is not enabled.
  - `validate_catalog_url(text) -> UrlCheck` — total, never raises, any input type.
  - `redact_url(url) -> str` — `scheme://host[:port]` (IPv6 in brackets, never user info/path/query), `"<invalid url>"` when unparseable.

- [ ] **Step 1: Write the failing tests** in `tests/test_catalog_remote_url.py`

`test_validate_catalog_url_table` parametrized with ids, `(text, url, key, error)`:

| id | text | url | key | error |
| --- | --- | --- | --- | --- |
| empty | `""` | `""` | `""` | None (and `enabled is False`) |
| blank | `"   "` | `""` | `""` | None (`enabled is False`) |
| default | `DEFAULT_CATALOG_URL` | same | `"https://wordbridge.coseeing.org/"` | None |
| padded | `"  https://wordbridge.coseeing.org/  "` | stripped | `"https://wordbridge.coseeing.org/"` | None |
| ideographic-space-padded | `"　https://wordbridge.coseeing.org　"` | stripped | `"https://wordbridge.coseeing.org/"` | None |
| upper-case | `"HTTPS://WordBridge.Coseeing.ORG"` | as typed | `"https://wordbridge.coseeing.org/"` | None |
| default-port | `"https://wordbridge.coseeing.org:443/"` | as typed | `"https://wordbridge.coseeing.org/"` | None |
| port-and-query | `"https://h.test:8443/c?x=1"` | as typed | `"https://h.test:8443/c?x=1"` | None |
| loopback-name | `"http://localhost:8000"` | as typed | `"http://localhost:8000/"` | None |
| loopback-v4 | `"http://127.0.0.1:8000/"` | as typed | `"http://127.0.0.1:8000/"` | None |
| loopback-v6 | `"http://[::1]:8000/"` | as typed | `"http://[::1]:8000/"` | None |
| loopback-upper | `"http://LOCALHOST"` | as typed | `"http://localhost/"` | None |
| max-length | `"https://h.test/" + "a" * 2033` (2048 chars) | as typed | same + nothing | None |
| http-remote | `"http://example.com"` | as typed | `""` | `"insecure_scheme"` |
| http-private-ip | `"http://10.0.0.5"` | as typed | `""` | `"insecure_scheme"` |
| ftp | `"ftp://x"` | | `""` | `"invalid"` |
| no-scheme | `"wordbridge.coseeing.org"` | | `""` | `"invalid"` |
| no-host | `"https://"` | | `""` | `"invalid"` |
| userinfo | `"https://user:pass@h.test/"` | | `""` | `"invalid"` |
| fragment | `"https://h.test/#top"` | | `""` | `"invalid"` |
| empty-fragment | `"https://h.test/#"` | | `""` | `"invalid"` |
| port-range | `"https://h.test:99999/"` | | `""` | `"invalid"` |
| port-text | `"https://h.test:abc/"` | | `""` | `"invalid"` |
| inner-space | `"https://h.test/a b"` | | `""` | `"invalid"` |
| control | `"https://h.test/\x00"` | | `""` | `"invalid"` |
| ideographic-space-inside | `"https://wordbridge.coseeing.org　/x"` | | `""` | `"invalid"` |
| fullwidth-colon | `"https：//wordbridge.coseeing.org"` | | `""` | `"invalid"` |
| bad-ipv6 | `"https://[::1"` | | `""` | `"invalid"` |
| too-long | 2049-character variant of max-length | | `""` | `"invalid"` |

For error rows assert only `key == ""`, `error`, `enabled is False`; `url` is the stripped text.

```python
@pytest.mark.parametrize("value", [None, 5, b"https://x", "https://例子.測試/", "https://h.test/\ud800"])
def test_validate_catalog_url_never_raises(value):
	check = validate_catalog_url(value)
	assert isinstance(check, UrlCheck)
	if not isinstance(value, str):
		assert check.error == "invalid"

def test_empty_path_and_slash_share_a_key():
	assert validate_catalog_url("https://h.test").key == validate_catalog_url("https://h.test/").key

@pytest.mark.parametrize("url, redacted", [
	("https://h.test:8443/secret?token=x", "https://h.test:8443"),
	("https://h.test/p", "https://h.test"),
	("http://[::1]:8000/x", "http://[::1]:8000"),
	("https://u:p@h.test/", "https://h.test"),
	("https://[::1", "<invalid url>"),
])
def test_redact_url(url, redacted): ...

def test_default_catalog_url_is_valid_https():
	check = validate_catalog_url(DEFAULT_CATALOG_URL)
	assert check.enabled and check.key.startswith("https://")
```

- [ ] **Step 2: Run to verify red** — `pytest -q tests/test_catalog_remote_url.py` → collection error `ModuleNotFoundError: No module named 'lib.catalog.remote'`.
- [ ] **Step 3: Implement** `remote.py` per the Interfaces block and §8.1. Order of checks: non-str → invalid; strip; empty → off; length > 2048 or any char with `ch.isspace() or not ch.isprintable()` → invalid; `"#" in text` → invalid; `urlsplit` + `.port` inside `try` → invalid; scheme not in `{"https","http"}` (lower-cased) → invalid; no hostname → invalid; `username is not None or password is not None` → invalid; `http` and hostname not in `LOOPBACK_HOSTS` → `insecure_scheme`. Key: lower scheme + `://` + host (bracketed if it contains `:`) + `:port` unless the scheme default (443/80) + (`path or "/"`) + (`"?" + query` if query). Add `"urllib"` to `STDLIB_ONLY`.
- [ ] **Step 4: Run to verify green** — `pytest -q tests/test_catalog_remote_url.py` → 41 passed. Full add-on suite → **501 passed, 1 skipped**.
- [ ] **Step 5: Commit** — `git add addon/globalPlugins/WordBridge/lib/catalog/remote.py tests/test_catalog_remote_url.py tests/test_catalog_document.py` → `feat: validate and redact the remote catalog URL`.

### Task 2: Provider host allowlist

**Files:**
- Modify: `addon/globalPlugins/WordBridge/lib/catalog/remote.py`
- Test: `tests/test_catalog_provider_allowlist.py`

**Interfaces:**
- Consumes: `CatalogIssue` (`lib/catalog/model.py`), `build_catalog`.
- Produces:
  - `@dataclass(frozen=True) class ProviderUrlRule: schemes: frozenset; hosts: frozenset; any_port: bool = False`.
  - `PROVIDER_URL_RULES: dict[str, ProviderUrlRule]` with exactly the §9 table (Anthropic `api.anthropic.com`, DeepSeek `api.deepseek.com`, Google `generativelanguage.googleapis.com`, OpenAI `api.openai.com`, OpenRouter `openrouter.ai`: `https`, default port only; Ollama: `http`+`https`, `localhost`/`127.0.0.1`, any port).
  - `filter_provider_urls(providers) -> tuple[object, tuple[CatalogIssue, ...]]` — non-mapping input is returned unchanged with `()`. Each drop: `CatalogIssue("disallowed_provider_url", f"providers.{name}", detail)`; detail is `f"host {host} is not allowed for {name}"`, `f"no host is allowed for {name}"` (no rule), or `f"url is not a string for {name}"`; never a path or query.

- [ ] **Step 1: Write the failing tests** in `tests/test_catalog_provider_allowlist.py` (reads `server/app/setting/catalog.json` directly for the first test).

```python
def test_every_provider_url_in_the_server_catalog_is_allowed():
	providers = json.loads(SERVER_CATALOG.read_text("utf8"))["providers"]
	kept, issues = filter_provider_urls(providers)
	assert kept == providers and issues == ()

@pytest.mark.parametrize("name", sorted(PROVIDER_URL_RULES))
def test_a_foreign_host_is_dropped_for_each_provider(name):
	# document with providers[name].url = "https://evil.test/v1/x?key=secret" and one model for name
	# filter -> issue code "disallowed_provider_url", location f"providers.{name}",
	# "evil.test" in detail, "/v1" not in detail, "secret" not in detail
	# build_catalog(filtered doc, runnable_providers=SUPPORTED_PROVIDERS):
	#   get_provider(name) is None and an "unknown_provider" issue at "models[0]"
```

`test_provider_url_rules_table` parametrized `(id, provider, url, dropped)`:
`http-anthropic` (Anthropic, `http://api.anthropic.com/v1/messages`, True), `ollama-localhost` (Ollama, `http://localhost:11434/v1`, False), `ollama-v4` (Ollama, `http://127.0.0.1:11434/v1`, False), `ollama-https` (Ollama, `https://localhost:11434/v1`, False), `ollama-lan` (Ollama, `http://10.0.0.5:11434/v1`, True), `openai-port` (OpenAI, `https://api.openai.com:8443/v1`, True), `openai-explicit-443` (OpenAI, `https://api.openai.com:443/v1`, False), `userinfo` (OpenAI, `https://user:pw@api.openai.com/v1`, True), `lookalike` (OpenAI, `https://api.openai.com.evil.test/v1`, True), `subdomain` (OpenAI, `https://x.api.openai.com/v1`, True), `upper-host` (OpenAI, `https://API.OPENAI.COM/v1`, False), `bad-ipv6` (OpenAI, `https://[::1/v1`, True), `bad-port` (OpenAI, `https://api.openai.com:abc/v1`, True), `url-int` (OpenAI, `5`, True), `url-list` (OpenAI, `["https://api.openai.com"]`, True). Assert `(name in kept) is not dropped` and, when dropped, exactly one `disallowed_provider_url` issue.

```python
def test_an_unknown_provider_name_is_dropped():
	kept, issues = filter_provider_urls({"Mistral": {..., "url": "https://api.mistral.ai/v1"}})
	assert kept == {} and [i.code for i in issues] == ["disallowed_provider_url"]

def test_shapes_build_catalog_reports_are_left_alone():
	assert filter_provider_urls(["x"]) == (["x"], ())
	# a non-mapping provider value, a missing url and url None are kept unchanged with no issue

def test_rules_cover_exactly_the_supported_providers():
	assert set(PROVIDER_URL_RULES) == SUPPORTED_PROVIDERS
```

- [ ] **Step 2: Run to verify red** — `pytest -q tests/test_catalog_provider_allowlist.py` → `ImportError: cannot import name 'PROVIDER_URL_RULES'`.
- [ ] **Step 3: Implement** `ProviderUrlRule`, `PROVIDER_URL_RULES`, `filter_provider_urls` in `remote.py` (§9). Returns a new dict; does not mutate the input.
- [ ] **Step 4: Run to verify green** — 25 passed; full suite **526 passed, 1 skipped**.
- [ ] **Step 5: Commit** — `feat: drop remote providers whose URL host is not allowlisted`.

### Task 3: Bundled ⊕ remote overlay

**Files:**
- Create: `addon/globalPlugins/WordBridge/lib/catalog/overlay.py`
- Modify: `addon/globalPlugins/WordBridge/lib/catalog/model.py:35` (`LINT_ISSUE_CODES`)
- Test: `tests/test_catalog_overlay.py`

**Interfaces:**
- Consumes: `filter_provider_urls` (Task 2), `FALLBACK_DOCUMENT`, `load_catalog` (`fallback.py`), `build_catalog`.
- Produces:
  - `LINT_ISSUE_CODES = frozenset({"unreferenced_provider", "ignored_remote_coseeings", "ignored_bundled_local_entries"})`.
  - `overlay_documents(bundled, remote) -> tuple[dict, tuple[CatalogIssue, ...]]` — total; a non-dict `bundled`/`remote` counts as absent. Output keys exactly `schema_version` (1), `providers`, `models`, `coseeings` (§7.3). Issues: `ignored_remote_coseeings` at `"remote.coseeings"`, `ignored_bundled_local_entries` at `"bundled"`, plus the `filter_provider_urls` issues.
  - `class OverlaySource: __init__(self, bundled_source, remote_document)`; `load() -> (document, issues)` = `bundled_source.load()` + `overlay_documents` + D2: when the overlaid `coseeings` build to no active Coseeing item, they are replaced by `FALLBACK_DOCUMENT["coseeings"]` and `CatalogIssue("bundled_coseeings_fallback", "coseeings", "no active Coseeing entry in the bundled catalog; using the built-in default")` is appended. Exceptions from `bundled_source.load()` propagate (so `load_catalog()` degrades).
  - `load_overlay_catalog(bundled_source, remote_document, *, runnable_providers) -> CorrectorCatalog` = `load_catalog(OverlaySource(...), runnable_providers=...)`.
  - `has_local_items(catalog) -> bool` — any `selectable_items` with `execution_channel == LOCAL_CHANNEL`.

- [ ] **Step 1: Write the failing tests** in `tests/test_catalog_overlay.py`, with a `StaticSource(document, issues=())` and a `RaisingSource` helper:

```python
def test_local_channel_comes_from_remote_and_coseeings_from_bundled(): ...
	# bundled has providers/models A + coseeings [default]; remote has providers/models B
	# -> catalog models are B only, coseeing labels ("default",)
def test_remote_coseeings_are_ignored_with_a_lint_issue():
	# issue ("ignored_remote_coseeings", "remote.coseeings"); is_dropped_issue(issue) is False
def test_bundled_local_entries_are_ignored_with_a_lint_issue():
	# issue ("ignored_bundled_local_entries", "bundled"); is_dropped_issue(issue) is False
def test_no_remote_document_gives_the_sentinel_only():
	# provider_groups == ("Coseeing",), labels ("default",), degraded False, issues == ()
def test_a_broken_bundled_file_plus_a_good_remote_gives_the_sentinel_and_local_items():
	# StaticSource(None, (CatalogIssue("unreadable_file", "catalog.json", "x"),))
	# -> has_local_items True, labels_for("Coseeing") == ("default",), degraded False,
	#    "bundled_coseeings_fallback" in codes and is_dropped_issue(that issue) is True
def test_inactive_only_bundled_coseeings_fall_back_to_the_sentinel(): ...
def test_a_broken_bundled_file_and_no_remote_still_offers_the_sentinel_undegraded(): ...
def test_a_raising_bundled_source_degrades_to_the_fallback_rung():
	# degraded True, provider_groups == ("Coseeing",)
def test_a_disallowed_remote_provider_and_its_models_are_dropped():
	# codes include "disallowed_provider_url" and "unknown_provider"
def test_the_shipped_target_files_overlay_as_section_7_4():
	# bundled = {"schema_version": 1, "coseeings": [sentinel]} (target content, inline)
	# remote = server/app/setting/catalog.json minus "coseeings"
	# provider_groups == ("Anthropic", "DeepSeek", "Google", "OpenAI", "Coseeing")
	# len([i for i in selectable_items if channel == "local"]) == 16
	# labels_for("Coseeing") == ("default",)
	# [(i.code, i.location) for i in issues] == [("unreferenced_provider", "providers.OpenRouter")]
	# find_selection("gpt-6-luna&OpenAI", "Coseeing") == (-1, -1)
```

- [ ] **Step 2: Run to verify red** — `ModuleNotFoundError: No module named 'lib.catalog.overlay'`.
- [ ] **Step 3: Implement** `overlay.py` and the `LINT_ISSUE_CODES` change (update the comment above it).
- [ ] **Step 4: Run to verify green** — 10 passed; full suite **536 passed, 1 skipped**.
- [ ] **Step 5: Commit** — `feat: overlay the remote local channel on the bundled Coseeing channel`.

### Task 4: Remote payload parsing and acceptance

**Files:**
- Modify: `lib/catalog/remote.py`, `lib/catalog/overlay.py`
- Test: `tests/test_catalog_payload.py`

**Interfaces:**
- Consumes: `load_overlay_catalog`, `has_local_items` (Task 3).
- Produces:
  - `parse_remote_payload(body: bytes) -> tuple[dict | None, tuple[CatalogIssue, ...]]` (§8.3). Codes: `remote_malformed` (location `"payload"`, detail = exception type name or `f"expected an object, got {type}"` / `"providers must be a mapping"` / `"models must be a list"`), `remote_schema_version` (detail `f"expected 1, got {value!r}"` only when the value is an int/None; otherwise the type name). Catches `Exception` (covers `RecursionError`).
  - `accept_remote_document(bundled_source, document, *, runnable_providers) -> tuple[CorrectorCatalog | None, tuple[CatalogIssue, ...]]` in `overlay.py` (§8.4): `(catalog, ())` when `has_local_items`, else `(None, (CatalogIssue("remote_no_models", "payload", "the payload offers no selectable local model"),))`.

- [ ] **Step 1: Write the failing tests.** `test_parse_remote_payload_table` parametrized `(id, body, code)` with `code None` meaning accepted:
`valid` (server file bytes, None), `utf8-bom` (`b"\xef\xbb\xbf"` + server file bytes, None), `not-json` (`b"{not json"`, `remote_malformed`), `array` (`b"[]"`, `remote_malformed`), `schema-2` (`remote_schema_version`), `schema-missing` (`remote_schema_version`), `providers-list` (`remote_malformed`), `providers-missing` (`remote_malformed`), `models-missing` (`remote_malformed`), `deep-nesting` (`b"[" * 100000`, `remote_malformed`), `bad-utf8` (`b"\xff\xfe\x00{"`, `remote_malformed`). Assert `document is None` iff `code` is set and the body text never appears in any detail.

```python
def test_a_valid_payload_is_accepted(): # catalog not None, has_local_items, issues == ()
def test_only_inactive_models_is_rejected(): # (None, codes == ["remote_no_models"])
def test_only_unsupported_providers_is_rejected(): # runnable_providers=frozenset()
def test_only_disallowed_hosts_is_rejected(): # every provider url -> https://evil.test/
def test_malformed_details_never_contain_the_body(): # body b'{"secret": [1,' -> "secret" not in detail
```

- [ ] **Step 2: Run to verify red** — `ImportError: cannot import name 'parse_remote_payload'`.
- [ ] **Step 3: Implement** both functions.
- [ ] **Step 4: Run to verify green** — 16 passed; full suite **552 passed, 1 skipped**.
- [ ] **Step 5: Commit** — `feat: parse and accept remote catalog payloads`.

### Task 5: Per-URL catalog cache

**Files:**
- Create: `lib/catalog/cache.py`
- Modify: `tests/test_catalog_document.py` (`STDLIB_ONLY` += `"os"`, `"tempfile"`)
- Test: `tests/test_catalog_cache.py`

**Interfaces:**
- Consumes: `MAX_PAYLOAD_BYTES` (Task 1), `CatalogIssue`.
- Produces:
  - `CACHE_VERSION = 1`; `MAX_CACHE_BYTES = 2 * MAX_PAYLOAD_BYTES` (see Ruling R1 in the ledger).
  - `class CatalogCache: __init__(self, path, *, can_write: Callable[[], bool])`.
  - `load(url_key: str) -> tuple[dict | None, tuple[CatalogIssue, ...]]` — missing file or other `url_key`: `(None, ())`; corrupt (unreadable, > `MAX_CACHE_BYTES`, not JSON, not an object, wrong `cache_version`, `url_key` not a str, `document` not a dict): `(None, (CatalogIssue("unreadable_cache", "cache", <type name or short reason>),))`. Never deletes.
  - `store(url_key: str, document: dict) -> tuple[CatalogIssue, ...]` — `()` on success or when `can_write()` is false or raises; on failure `(CatalogIssue("cache_write_failed", "cache", <type name>),)`. File body `{"cache_version": 1, "url_key": ..., "document": ...}` as UTF-8 JSON (`ensure_ascii=False`). Directory created here (`mkdir(parents=True, exist_ok=True)`), never in `__init__`. Atomic: `NamedTemporaryFile(dir=parent, delete=False, prefix="remote-catalog.", suffix=".tmp")`, write, flush, `os.fsync`, close, `os.replace`; on any exception unlink the temp file best effort.

- [ ] **Step 1: Write the failing tests** in `tests/test_catalog_cache.py` (all under `tmp_path`):

```python
def test_round_trip(): # store then load(key) -> (document, ())
def test_a_missing_file_is_no_cache_and_no_issue(): # (None, ())
def test_another_url_key_is_not_used(): # (None, ()) and the file is unchanged
@pytest.mark.parametrize("content", [b"{not json", b"[]", b'{"cache_version": 2, "url_key": "k", "document": {}}',
	b'{"cache_version": 1, "url_key": 5, "document": {}}', b'{"cache_version": 1, "url_key": "k", "document": []}'])
def test_a_corrupt_cache_is_ignored_and_left_in_place(content):
	# (None, codes == ["unreadable_cache"]), file bytes unchanged
def test_a_file_larger_than_the_limit_is_ignored(): # MAX_CACHE_BYTES + 1 bytes -> unreadable_cache
def test_a_failing_replace_keeps_the_old_file_and_leaves_no_temp_file(monkeypatch):
	# monkeypatch cache module os.replace to raise OSError -> ["cache_write_failed"],
	# old content intact, no "*.tmp" in the directory
def test_can_write_false_writes_nothing(): # no file, no directory
def test_can_write_raising_writes_nothing(): # same, no exception
def test_the_directory_is_created_only_by_store(): # constructing does not create path.parent
def test_a_parent_that_is_a_file_reports_cache_write_failed(): # no exception
```

(5 parametrized + 9 = 14 tests.)
- [ ] **Step 2: Run to verify red** — `ModuleNotFoundError: No module named 'lib.catalog.cache'`.
- [ ] **Step 3: Implement** `cache.py`; add `"os"`, `"tempfile"` to `STDLIB_ONLY`.
- [ ] **Step 4: Run to verify green** — 14 passed; full suite **566 passed, 1 skipped**.
- [ ] **Step 5: Commit** — `feat: cache the accepted remote catalog per URL`.

**— End of Batch 1: stop and report for the batch review. —**

### Task 6: HTTP fetch

**Files:**
- Create: `addon/globalPlugins/WordBridge/catalog_updater.py`
- Modify: `tests/test_import_purity.py:18` (`TOP_LEVEL_INTERNAL_NAMES` += `"catalog_updater"`)
- Test: `tests/test_catalog_fetch.py`

**Interfaces:**
- Consumes: `FETCH_TIMEOUT`, `FETCH_DEADLINE_SECONDS`, `MAX_PAYLOAD_BYTES`, `CHUNK_BYTES` (Task 1).
- Produces:
  - `@dataclass(frozen=True) class FetchResult: body: bytes | None; issue: CatalogIssue | None`.
  - `fetch_payload(url: str, *, http_get, clock=time.monotonic) -> FetchResult` (§8.2). Issue codes, all at location `"fetch"`: `remote_http_status` (detail `str(status)`), `remote_too_large` (detail `"limit 1048576"`), `remote_timeout` (detail `"deadline 20s"`), `remote_request_failed` (detail `type(error).__name__`). The response is used as a context manager. The module imports only the standard library and `.lib.catalog`.

- [ ] **Step 1: Write the failing tests** with a `FakeResponse(status_code, headers, chunks, raise_on_iter=None)` (records `closed`, chunks consumed) and a `FakeClock`:
  - `test_the_call_uses_exactly_the_specified_arguments`: `calls == [(("https://h.test/",), {"stream": True, "timeout": (5, 10), "allow_redirects": False, "headers": {"Accept": "application/json"}})]`.
  - `test_status_200_returns_the_body`: chunks `[b"ab", b"cd"]` → `body == b"abcd"`, `issue is None`.
  - `test_non_200_is_rejected_with_the_number` [301, 304, 404, 500] → `issue.code == "remote_http_status"`, `issue.detail == str(status)`, `body is None`.
  - `test_content_length_over_the_limit_is_rejected_without_reading`: header `"1048577"` → `remote_too_large`, `iter_content` never called.
  - `test_a_streamed_body_over_the_limit_stops_at_the_first_chunk_past_it`: 17 chunks of 65536 + more → consumed == 17, `remote_too_large`.
  - `test_the_overall_deadline_gives_remote_timeout`: clock advances 21 s at the 2nd chunk → `remote_timeout`.
  - `test_an_exception_from_http_get_gives_request_failed_with_the_type_only`: raises `ConnectionError("https://h.test/secret")` → detail `"ConnectionError"`.
  - `test_an_exception_while_reading_gives_request_failed_and_closes`.
  - `test_the_response_is_closed_in_every_case` [200, 404, too-large header, timeout].
  - `test_unusable_content_length_falls_back_to_the_streamed_limit` [`"abc"`, `"-1"`, `""`] → small body accepted; same headers with 17 big chunks → `remote_too_large`. (Review Focus 4)
  - `test_empty_keepalive_chunks_are_skipped`: `[b"", b"{}", b""]` → `body == b"{}"`. (Review Focus 4)
- [ ] **Step 2: Red** — `ModuleNotFoundError: No module named 'catalog_updater'`.
- [ ] **Step 3: Implement** `FetchResult`, `fetch_payload`.
- [ ] **Step 4: Green** — 19 passed; full suite **585 passed, 1 skipped**.
- [ ] **Step 5: Commit** — `feat: fetch the remote catalog with size, time and status limits`.

### Task 7: Registry swap and settings repository

**Files:**
- Modify: `lib/catalog/registry.py`, `settings_repository.py`
- Test: `tests/test_catalog_registry.py` (new), `tests/test_settings_repository.py`

**Interfaces:**
- Produces:
  - `registry.replace(catalog) -> None` — raises `RuntimeError("catalog registry replaced before initialize()")` when not initialized.
  - `SettingsRepository.catalog_url() -> str` — `self._settings.get("catalog_url", DEFAULT_CATALOG_URL)` stripped (non-str → `""`).
  - `SettingsRepository.save_catalog_url(value: str) -> None`.
  - `SettingsRepository.corrector_selection(catalog=None) -> tuple` — uses `catalog` when given and never calls the `current_catalog` callable.
- [ ] **Step 1: Tests** — `test_replace_before_initialize_raises`, `test_replace_swaps_current` (both reset the registry in a fixture); `test_catalog_url_defaults_when_absent` (`== DEFAULT_CATALOG_URL`), `test_catalog_url_is_stripped` (`" https://h.test/ "` → `"https://h.test/"`), `test_save_catalog_url_writes_the_value`, `test_corrector_selection_uses_an_explicit_catalog` (callable is `lambda: pytest.fail(...)`).
- [ ] **Step 2: Red** — `AttributeError: module ... has no attribute 'replace'` / `'catalog_url'`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Green** — 6 passed; full suite **591 passed, 1 skipped**.
- [ ] **Step 5: Commit** — `feat: let the registry swap catalogs and store the catalog URL`.

### Task 8: CatalogUpdater

**Files:**
- Modify: `catalog_updater.py`
- Test: `tests/test_catalog_updater.py`

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces:
  - `@dataclass(frozen=True) class UpdaterStatus: source: str; fetch: str` (`source ∈ {"none","cache","fetched"}`, `fetch ∈ {"off","running","succeeded","failed"}`).
  - `class CatalogUpdater.__init__(self, *, bundled_source, cache, runnable_providers, http_get, post_to_ui, install, shutdown, log, clock=time.monotonic, start_thread=start_daemon_thread)`; `start_thread(target, args) -> thread` (production `start_daemon_thread` makes `threading.Thread(target=..., args=..., name="wordbridge-catalog-fetch", daemon=True)`, starts and returns it).
  - `initial_catalog(url: str) -> CorrectorCatalog` (main thread, §11.2): validate; off/invalid → bundled-only, `fetch="off"` (invalid logged once as `"WordBridge: catalog URL is invalid code=%s; the remote catalog is off"`); else bundled ⊕ accepted cache, `source="cache"` or `"none"`, `fetch="running"`. Records the live key.
  - `refresh(url: str) -> None` (main thread, §11.3, D8).
  - `status() -> UpdaterStatus`; property `thread` (latest started thread or `None`).
  - Internal `_run(generation, check)` (thread) and `_apply(generation, catalog, issue)` (main thread). Log lines exactly §14: `"WordBridge: catalog fetched host=%s bytes=%d models=%d"`, `"WordBridge: catalog fetch failed host=%s code=%s type=%s"`; cache problems `"WordBridge: catalog cache problem code=%s type=%s"`.
  - Module level: `install(updater)`, `uninstall()`, `request_refresh(url)` (no-op without an installed updater), `status() -> UpdaterStatus | None`.
- [ ] **Step 1: Tests** (fake `start_thread` recording `(target, args)`, a list as `post_to_ui` queue, `threading.Event` shutdown, capturing log):
  - `test_startup_with_a_cache_uses_it`, `test_startup_without_a_cache_is_bundled_only`, `test_a_cached_payload_failing_acceptance_is_ignored` (`source == "none"`).
  - `test_a_successful_refresh_posts_an_install_and_writes_the_cache` (`status == ("fetched","succeeded")`).
  - `test_a_failed_refresh_keeps_the_catalog_and_cache` (`fetch == "failed"`, `source` unchanged, nothing installed).
  - `test_out_of_order_completion_installs_only_the_newer` (older target run last: no post, no cache write).
  - `test_shutdown_before_completion_posts_and_writes_nothing`; `test_apply_after_shutdown_does_nothing`.
  - `test_a_url_change_installs_bundled_plus_new_cache_at_once` (D8: install called synchronously in `refresh`).
  - `test_url_changed_back_before_fetches_complete_installs_only_the_last` (Review Focus 5: A→B→A; immediate installs for B then A's cache; only generation 3 posts).
  - `test_an_empty_url_starts_no_thread_and_reads_no_cache` (`fetch == "off"`).
  - `test_an_invalid_stored_url_is_off_and_logged_once`.
  - `test_logs_never_contain_path_query_or_error_text` (URL `https://h.test/p?token=s`, `http_get` raising `OSError("https://h.test/p?token=s")`; no log arg contains `"/p"`, `"token"` or the message).
  - `test_module_request_refresh_is_a_no_op_without_an_updater`, `test_module_functions_delegate_to_the_installed_updater`.
- [ ] **Step 2: Red** — `ImportError: cannot import name 'CatalogUpdater'`.
- [ ] **Step 3: Implement** (lock around generation/status; cache write outside the lock; outer `try/except Exception` in `_run` logs the type only).
- [ ] **Step 4: Green** — 15 passed; full suite **606 passed, 1 skipped**.
- [ ] **Step 5: Commit** — `feat: add the catalog updater with generations and status`.

### Task 9: Move local-catalog tests to the server file

**Files:**
- Create: `tests/shipped_catalog.py`
- Modify: `tests/test_corrector_catalog_unittest.py`, `tests/test_eval_provider_config.py`, `tests/test_provider_model_adapter_unittest.py`, `tests/test_provider_naming.py`, `tests/test_task_architecture_unittest.py`, `tests/test_catalog_source_seam.py`, `tests/test_helpers.py`, `workspace/evals/provider.py`

**Interfaces:**
- Consumes: `overlay_documents`, `load_overlay_catalog` (Task 3), `fetch_payload` (Task 6), `parse_remote_payload` (Task 4).
- Produces (`tests/shipped_catalog.py`): `SERVER_CATALOG_PATH`, `ADDON_SETTING_DIR`, `server_document() -> dict`, `bundled_document() -> dict`, `shipped_overlay() -> CorrectorCatalog` (= `load_overlay_catalog(BundledCatalogSource(ADDON_SETTING_DIR), server_document(), runnable_providers=SUPPORTED_PROVIDERS)`), `TEMPORARY_LINT_CODES = frozenset({"ignored_remote_coseeings", "ignored_bundled_local_entries"})` (comment: removed in Tasks 10 and 16).
- [ ] **Step 1:** Switch every test that reads providers, models or prices through `BundledCatalogSource(SETTING_DIR)` to `server_document()`/`shipped_overlay()`, pinning the same values. Tests needing a non-sentinel Coseeing entry build a fixture document. `test_helpers.py` and `workspace/evals/provider.py` build from `server/app/setting/catalog.json`.
- [ ] **Step 2:** Rewrite `tests/test_catalog_source_seam.py` per §17.3: a fake `http_get` serving the server file bytes; fetch → parse → `load_overlay_catalog` equals `load_catalog(InMemory(overlay_documents(bundled_document(), server_document())[0]))` in provider groups, selectable items, default selection and price entries; keep "add a model with no code change", "None issues", and the unimplemented-provider case (Mistral gets a temporary `PROVIDER_URL_RULES` entry via `monkeypatch.setitem`, models dropped with `unsupported_provider`).
- [ ] **Step 3: Verify the guard** — temporarily apply `target-addon-catalog.json` in a scratch copy (not the worktree) and confirm none of these files fail any more; record the command in the ledger.
- [ ] **Step 4: Green** — full suite **606 passed, 1 skipped** (± seam-test case changes; record the exact count).
- [ ] **Step 5: Commit** — `test: read local catalog data from the server catalog file`.

### Task 10: Wire the updater into the plugin and ship the sentinel-only bundled file

**Files:**
- Modify: `__init__.py`, `setting/catalog.json` (← `target-addon-catalog.json`, byte for byte), `tests/test_coseeing_auth_nvda.py` (harness + counts), `tests/test_coseeing_requests.py`, `tests/test_catalog_bundled.py`, `tests/test_ai_config_schema.py`, `tests/shipped_catalog.py` (drop `ignored_bundled_local_entries` from `TEMPORARY_LINT_CODES`)
- Test: `tests/test_catalog_plugin_wiring.py` (new)

**Interfaces:**
- Consumes: Tasks 5–9.
- Produces:
  - Config spec key `"catalog_url": f"string(default='{DEFAULT_CATALOG_URL}')"`.
  - Module attribute `CATALOG_CACHE_PATH = user_workspace_root() / "catalog" / "remote-catalog.json"` (pure path math, no I/O) and `_can_write_catalog_cache() -> bool` (lazy `import NVDAState`; any exception → `False`).
  - `GlobalPlugin._make_catalog_updater(self) -> CatalogUpdater` (tests monkeypatch it or `CATALOG_CACHE_PATH`), `GlobalPlugin._start_catalog_fetch(self)`, `GlobalPlugin._install_catalog(self, catalog)`.
  - `GlobalPlugin.__init__` order: `_shutdown`; `self.settings`; updater; `catalog_updater.install(updater)`; `self.catalog = updater.initial_catalog(self.settings.catalog_url())`; `registry.initialize`; log issues; task config; panel registration; auth `CallAfter`; `wx.CallAfter(self._start_catalog_fetch)`.
  - `correctTypo`: one `catalog = registry.current()` snapshot for `corrector_selection(catalog=catalog)`, `get_model`, `get_provider` and `catalog.degraded`.
  - `terminate`: the updater thread joins the `workers` list; `catalog_updater.uninstall()` in its own `try` in the `finally`.
- [ ] **Step 1: Harness** — `_load_nvda_plugin` sets `plugin.CATALOG_CACHE_PATH` to a fresh `tempfile.mkdtemp()` path seeded with a cache (`url_key` of `DEFAULT_CATALOG_URL`, `document = server_document()`), replaces `requests.get` with a recorder that raises, and builds `plugin.catalog` from `shipped_overlay()`.
- [ ] **Step 2: New tests** in `tests/test_catalog_plugin_wiring.py`: `test_init_schedules_sign_in_and_fetch_start`, `test_fetch_start_does_nothing_after_terminate`, `test_terminate_joins_the_fetch_thread_and_uninstalls_even_if_an_earlier_step_raises`, `test_install_catalog_updates_registry_and_self_catalog`, `test_correct_typo_uses_one_catalog_snapshot` (patched `registry.current` returns a different catalog on the 2nd call; payload id and degraded check come from the first), `test_no_test_performs_real_http` (recorder list empty after init + queued callbacks run with a fake thread starter).
- [ ] **Step 3: Red** — the new tests fail (`AttributeError: _install_catalog`, queued count 1).
- [ ] **Step 4: Implement** the wiring; apply the target bundled file; migrate the remaining §16.1 tests (`len(queued)` counts at `:367`, `:494`, `:666` → 2 and `:596` → 3; `test_catalog_bundled.py` and `test_ai_config_schema.py` pin keys `{"schema_version", "coseeings"}` and the one sentinel; `test_coseeing_requests.py:28` uses a fixture document with a non-sentinel Coseeing entry).
- [ ] **Step 5: Green** — full suite **≈612 passed, 1 skipped** (record exact); server **81 passed**.
- [ ] **Step 6: Commit** — `feat: load the catalog from the remote URL and cache at startup`.

**— End of Batch 2: stop and report for the batch review. —**

### Task 11: Settings panel URL field, validation and status line

**Files:**
- Modify: `dialogs.py`, `addon/locale/zh_TW/LC_MESSAGES/nvda.po`
- Test: `tests/test_catalog_settings_panel.py` (new; reuses `_install_settings_panel_widget_stubs` and `_make_panel` imported at function scope)

**Interfaces:**
- Consumes: `validate_catalog_url`, `catalog_updater.status()/request_refresh()`, `SettingsRepository.catalog_url/save_catalog_url`.
- Produces: `LLMSettingsPanel.catalogUrlCtrl` (last control, `addLabeledControl(_("Model list URL:"), wx.TextCtrl, size=(self.scaleSize(375), -1), value=...)`, tooltip), `LLMSettingsPanel.catalogStatusText` (`wx.StaticText` or `None`, added right after the dropped-entries line), `isValid() -> bool`, module function `catalog_status_message(status) -> str | None` (§13.3 table).
- [ ] **Step 1: Tests** — `test_the_url_field_is_the_last_control`; `test_is_valid_rejects` [`ftp://x` → malformed message, `http://example.com` → https message]: `_validationErrorMessageBox(message=..., option="Model list URL")` called once, field focused, returns `False`; `test_is_valid_accepts_empty_and_default`; `test_an_unchanged_url_saves_nothing_and_triggers_no_refresh` (also `HTTPS://WORDBRIDGE.COSEEING.ORG/` vs stored default); `test_a_changed_url_saves_the_stripped_text_and_schedules_one_refresh`; `test_catalog_status_message_table` (five §13.3 rows incl. `None` for fresh); `test_the_dropped_entries_line_is_silent_for_the_shipped_overlay`.
- [ ] **Step 2: Red.**
- [ ] **Step 3: Implement**; every new `_()` has a `# Translators:` comment; add the nine §13.4 entries to `nvda.po`; `msgfmt --check -o /dev/null addon/locale/zh_TW/LC_MESSAGES/nvda.po`.
- [ ] **Step 4: Green** — record counts.
- [ ] **Step 5: Commit** — `feat: add the model list URL field and status line to the panel`.

### Task 12: Panel keeps an unresolved stored selection (D12)

**Files:** Modify `dialogs.py`; Test `tests/test_catalog_settings_panel.py`.

**Interfaces:** Produces `LLMSettingsPanel._storedSelectionResolved: bool` and `LLMSettingsPanel._restoredIndices: tuple[int, int]` set in `makeSettings`.
- [ ] **Step 1: Tests** — `test_an_unresolved_stored_selection_survives_an_untouched_save` (stored `gpt-6-luna&OpenAI`/`local`, bundled-only catalog → stored keys unchanged after `onSave`, language still saved); `test_a_changed_choice_overwrites_the_unresolved_selection`; `test_sign_in_uses_the_effective_channel`.
- [ ] **Step 2: Red. Step 3: Implement. Step 4: Green** (record counts).
- [ ] **Step 5: Commit** — `fix: do not overwrite a stored model the panel could not resolve`.

### Task 13: Server `GET /`

**Files:** Modify `server/app/main.py`; Test `server/tests/test_catalog_route.py` (new), `server/tests/test_route_permissions.py`.

**Interfaces:** Produces `load_catalog_bytes(path: Path) -> bytes` (raises `ValueError` for a non-object or `schema_version != 1`), `CATALOG_BYTES`, `@app.get("/")` returning `Response(content=CATALOG_BYTES, media_type="application/json", headers={"Cache-Control": "no-cache"})`.
- [ ] **Step 1: Tests** — `test_root_serves_the_catalog_file_verbatim` (status 200, `content-type` starts with `application/json`, `cache-control == "no-cache"`, body bytes == file bytes); `test_load_catalog_bytes_rejects_bad_files` [`[]`, `{"schema_version": 2}`, `not json`]; anonymous `GET /` → 200 in `test_route_permissions.py`.
- [ ] **Step 2: Red. Step 3: Implement. Step 4: Green** — server **86 passed** (record exact).
- [ ] **Step 5: Commit** — `feat: serve the catalog at the server root`.

### Task 14: PENDING USER DECISION (OQ2) — stored Coseeing selection offered only locally

Written against the recommended option **B** (stay on Coseeing).

**Files:** Modify `lib/catalog/selection.py`; Test `tests/test_corrector_catalog_unittest.py:62-73` (rewritten), `tests/test_selection_state.py`.

**Interfaces:** `normalize_selection(catalog, id, channel)` — when `channel == COSEEING_GROUP` and the id is not on Coseeing, return `catalog.default_selection()`; the unknown-channel branch (`:75-85`) is unchanged.
- [ ] **Step 1: Tests** — `test_a_stored_coseeing_id_offered_only_locally_stays_on_coseeing` (`("gpt-6-luna&OpenAI", "Coseeing")` → `("default", "Coseeing")`); `test_a_stored_local_id_still_resolves_locally`; `test_selection_state_restores_the_coseeing_default_for_it`.
- [ ] **Step 2: Red. Step 3: Implement. Step 4: Green. Step 5: Commit** — `fix: keep a Coseeing selection on Coseeing when its model moved to local`.

### Task 15: PENDING USER DECISION (OQ3) — stored local selection with no remote or cached catalog

Written against the recommended option **B** (refuse with a message, skip the startup sign-in).

**Files:** Modify `__init__.py`, `settings_repository.py`, `nvda.po`; Test `tests/test_catalog_plugin_wiring.py`.

**Interfaces:** `SettingsRepository.stored_execution_channel() -> str` (raw stored value); `GlobalPlugin._local_selection_unavailable(self) -> str | None` returning the §13.4 OQ3 message (`fetch == "running"` → "still loading" text; otherwise → "unavailable" text) when the raw stored channel is `LOCAL_CHANNEL` and `status().source == "none"`.
- [ ] **Step 1: Tests** — `test_correction_refuses_while_the_list_is_loading`, `test_correction_refuses_when_the_list_could_not_be_loaded`, `test_correction_proceeds_once_a_catalog_is_loaded`, `test_startup_skips_coseeing_sign_in_for_a_local_user_without_a_catalog`, `test_a_coseeing_user_is_unaffected`; neither message is sent for a stored Coseeing channel.
- [ ] **Step 2: Red. Step 3: Implement** (+ the two §13.4 OQ3 strings with `# Translators:` and zh_TW). **Step 4: Green. Step 5: Commit** — `fix: do not send a local user's text to Coseeing before the model list loads`.

### Task 16: PENDING USER DECISION (OQ1) — server target catalog and non-default Coseeing ids

Written against the recommended option **B** (server-only `COSEEING_MODEL_IDS`).

**Files:** Modify `server/app/setting/catalog.json` (← `target-server-catalog.json`, byte for byte), `server/app/correction_config.py`, `server/tests/test_correction_config.py`, `server/tests/test_proofreader_api.py`, `server/tests/test_catalog_route.py`, `tests/shipped_catalog.py` (remove `TEMPORARY_LINT_CODES` and its uses), `tests/test_catalog_overlay.py` (read the real files).

**Interfaces:** `CorrectionSettings.coseeing_ids: frozenset[str]` from env `COSEEING_MODEL_IDS` (default `"deepseek-flash&DeepSeek,gpt-6-luna&OpenAI"`, comma-separated, stripped, empty items ignored); `resolve_model()` checks it where it checked `coseeings`.
- [ ] **Step 1: Tests** — `test_a_listed_non_default_id_resolves`, `test_an_unlisted_id_is_rejected`, `test_the_env_var_overrides_the_list`, `test_explicit_model_success` keeps its meaning, `test_inactive_coseeing_offer_is_rejected` rewritten as `test_an_inactive_local_model_is_rejected_even_when_listed`; `GET /` body parses to an object without `coseeings`.
- [ ] **Step 2: Red. Step 3: Implement. Step 4: Green** (both suites; record counts). **Step 5: Commit** — `feat: make the server catalog the remote payload`.
