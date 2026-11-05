# Bundled provider entries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans.
> WordBridge normal flow: one implementer runs every task in order; the
> orchestrator dispatches the final Fable 5.1 review (DEVELOPMENT_WORKFLOW.md §3.3).

**Goal:** The add-on's bundled `setting/catalog.json` carries the six provider
entries (equal to the server's, pinned by a drift test), the remote catalog
supplies only `models`, and the runtime provider host allowlist is replaced
by test-level guards on the bundled file, with nothing a user sees or hears
changing for the shipped files; the server's `GET /` stops sending
`providers` (B2), and models for an unbundled provider are lint (OQ1 → B).

**Architecture:** `overlay_documents()` (`lib/catalog/overlay.py`) takes
`providers` and `coseeings` from the bundled document and `models` from the
remote one; without a remote document `providers` is `{}`, so the
bundled-only catalog stays the Coseeing sentinel with no issues.
`accept_remote_document()` gains one rejection, `bundled_source_failed` /
`no_providers`, and `check_remote_document()` stops looking at `providers`.
The allowlist code in `lib/catalog/remote.py`, the probe kind
`disallowed_hosts` and its tip string are removed; `tests/test_catalog_bundled.py`
pins the bundled provider names, URLs and hosts, and compares the bundled and
server `providers` as canonical JSON.

**Tech Stack:** Python (NVDA add-on; NVDA runs Python 3.13), pytest
(table-driven; no Hypothesis/mutmut), gettext `nvda.po`.

**Spec:** `docs/superpowers/specs/2026-11-05-bundled-providers-design.md`
(commit `ba1f558`), which amends
`docs/superpowers/specs/2026-11-04-remote-catalog-design.md` ("RC") and
`docs/superpowers/specs/2026-11-04-catalog-retry-design.md` ("CR"). §n below
refers to the bundled-providers spec. Paths are relative to
`addon/globalPlugins/WordBridge/` unless they start with `tests/`, `docs/` or
`server/`.

## Global Constraints

- Branch `feat/bundled-providers`, worktree `/workspace/WordBridge-bundled-providers`; never touch the main checkout `/workspace/WordBridge`.
- Every commit is green: add-on `/tmp/claude-0/-workspace-WordBridge/9af55a63-c255-4088-9b3c-fe363afb236f/scratchpad/testvenv/bin/python -m pytest -q --ignore-glob='tests/test_integration_*' tests` (baseline **1053 passed, 1 skipped**); server `cd server && /workspace/WordBridge/server/.venv/bin/python -m pytest -q` (baseline **103 passed**; grows only in Task 3, §12 as amended by B2); `prek run --all-files` all Passed; `git diff --check` clean. Never run `tests/test_integration_*`. At most 3 pytest workers; stop pytest if MemAvailable < 3 GB.
- NVDA runs Python 3.13: no 3.14-only syntax. `_load_nvda_plugin` and the widget stubs are imported at function scope only. No real HTTP in tests.
- Server (B2, Decided by the user (2026-11-05)): `server/app/setting/catalog.json`, `correction_config.py` and the server `lib/catalog` are unchanged; only `server/app/main.py` `load_catalog_bytes()`/`GET /` and `server/tests/test_catalog_route.py` change, in Task 3 alone. `schema_version` stays `1`; `cache_version` stays `1`; no cache migration (P8, §9.3–§9.4).
- Bundled file (§2.1): keys exactly `schema_version`, `providers`, `coseeings`; `providers` copied verbatim (tab-indented) from `server/app/setting/catalog.json:3-77`; `coseeings` unchanged.
- B4 (Decided by the user (2026-11-05)): a remote or cached document with a `providers` key (any value) is rejected by `check_remote_document()` with `CatalogIssue("remote_providers_not_allowed", "payload", "providers are bundled with the add-on; the payload may not carry them")`; "Test..." maps it to `not_a_list` (the existing `remote_*` bucket). Done in Task 4 only, after the server stops sending `providers` (Task 3).
- Issue codes: new `ignored_bundled_models` at location `bundled.models`, detail `the bundled catalog may not carry models; they are ignored` (P3); new rejection `CatalogIssue("bundled_source_failed", "bundled", "no_providers")` (P4). Retired: `ignored_bundled_local_entries`, `ignored_remote_coseeings`, `disallowed_provider_url`; probe kind `disallowed_hosts`.
- `LINT_ISSUE_CODES == {"unreferenced_provider", "ignored_bundled_models"}` after Task 1; Task 6 adds `"unknown_provider"` (OQ1 → B).
- Remote `coseeings` and every other key except `schema_version`, `models` and `providers` are ignored silently: no issue, no log line (P2). The overlay never reads remote `providers` (Task 1); from Task 4 the document check rejects them (B4).
- String removed (§13): `The model list names only provider addresses WordBridge does not allow.` and its zh_TW `這份模型清單列出的服務提供者網址都不在 WordBridge 允許的範圍內。`, deleted from `addon/locale/zh_TW/LC_MESSAGES/nvda.po` in the same commit; `msgfmt --check -o /dev/null addon/locale/zh_TW/LC_MESSAGES/nvda.po` clean. No new strings.
- Logging (§14, RC D15): no new log lines; issue details reach the log only through `loggable()`.
- OQ1, Decided by the user (2026-11-05): **B**. A remote model whose provider is not bundled is lint: still logged as `unknown_provider` through `loggable()`, not counted in the panel's dropped-entries line. `unsupported_provider` stays counted. Tasks 1–5 keep today's rule (A); everything OQ1-dependent is in Task 6.

## Review Focus

1. **A `providers` key of any value** (`null`, `"x"`, `7`, `[]`, `{}`, a hostile mapping, the server's own block) in a fetched or cached payload — an outdated server or a test build's cache. Expected: rejected as a whole with `remote_providers_not_allowed`, the current catalog kept, a retry armed, "Test..." says "not a WordBridge model list"; absent `providers` is accepted. Covered by Task 4 (`test_any_remote_providers_key_rejects_the_payload`) and Task 2 (`test_a_payload_without_providers_is_accepted`).
2. **A remote model whose provider differs from a bundled name only by case or a trailing space** (`openai`, `OpenAI `) or names a provider only a newer release has (`Mistral`). Expected: that model dropped with `unknown_provider`, its siblings kept, the payload accepted. Covered by Task 1 (`test_a_remote_model_for_a_provider_the_bundled_file_lacks_is_dropped`).
3. **A bundled file with one incomplete provider entry** (a hand-edited or badly merged release). Expected: only that provider's models are dropped (`incomplete_provider`, `unknown_provider`), the payload is accepted; when no entry is usable, `bundled_source_failed` / `no_providers`. Covered by Task 2 (`test_one_incomplete_bundled_provider_drops_only_its_models`, `test_a_bundled_file_without_usable_providers_is_reported_as_such[all-incomplete]`).
4. **A payload carrying `providers`, `coseeings` and unknown top-level keys at once** (an old cache or a self-hosted server). Expected: the overlay adds no issue at all, so the NVDA log gains no warning line. Covered by Task 1 (`test_remote_extra_keys_add_no_issue`).
5. **Drift where one side gains or loses a whole provider, or a value changes type** (`0.0` → `0`). Expected: the drift check fails and its message names that provider. Covered by Task 1 (`test_the_drift_message_names_the_first_differing_provider`).

---

## File Structure

| File | Responsibility | Tasks |
| --- | --- | --- |
| `setting/catalog.json` | bundled `providers` + `coseeings` | 1 |
| `lib/catalog/overlay.py` | overlay rule (P1–P3), `no_providers` acceptance (P4), docstrings | 1, 2 |
| `lib/catalog/model.py` | `LINT_ISSUE_CODES` and its comment | 1, 6 |
| `lib/catalog/cache.py` | module docstring ("stored as fetched") | 1 |
| `lib/catalog/remote.py` | relaxed `check_remote_document()` (P5); allowlist removed (P6) | 2, 4, 5 |
| `catalog_updater.py` | `_probe()` without `disallowed_hosts`; `ProbeResult` docstring | 5 |
| `catalog_url_dialog.py`, `addon/locale/zh_TW/LC_MESSAGES/nvda.po` | tip string removed | 5 |
| `tests/test_catalog_bundled.py` | §10.2 guards, §11 drift, bundled-only via overlay, AC6 scan | 1, 5 |
| `tests/test_catalog_overlay.py`, `tests/test_ai_config_schema.py`, `tests/shipped_catalog.py` | overlay rule, shipped result | 1, 2 |
| `tests/test_catalog_payload.py` | acceptance and parse tables | 1, 2 |
| `tests/test_catalog_updater.py` | `BundledSentinel` with providers; cache loads | 1, 2 |
| `tests/test_catalog_retry.py` | failure, non-failure and probe rows | 1, 2 |
| `tests/test_catalog_source_seam.py`, `tests/test_catalog_plugin_wiring.py`, `tests/test_catalog_settings_panel.py` | seam, wiring, captions, OQ1 | 1, 6 |
| `server/app/main.py`, `server/tests/test_catalog_route.py` | `GET /` without `providers` (B2) | 3 |
| `tests/shipped_catalog.py` | `served_document()` = server file minus `providers` | 3 |
| `lib/catalog/remote.py`, `tests/test_catalog_payload.py`, `tests/test_catalog_updater.py`, `tests/test_catalog_retry.py`, `tests/test_catalog_plugin_wiring.py`, `tests/test_catalog_source_seam.py` | B4 rejection; payload fixtures without `providers` | 4 |
| `tests/test_catalog_provider_allowlist.py`, `tests/test_catalog_url_dialog.py` | removed / row removed | 5 |

Six tasks, one batch (fewer than 10). Task order is §16.1, with the server
task (B2) after the add-on accepts a providers-less payload, the B4 rejection
after the server stops sending them, and OQ1 last.
Expected add-on counts (skipped stays 1): **T1 1074, T2 1084, T3 1085,
T4 ≈1095, T5 ≈1052, T6 ≈1055** (T4 onwards estimated: the ledger records the real numbers); server 103 until T3, **104** from T3 on. A task whose real count differs records it in the ledger; later
numbers shift by the same amount.

Test fixtures used by several tasks: `bundled_document()` and
`server_document()` from `tests/shipped_catalog.py` (fresh dicts per call).
`BundledSentinel` in `tests/test_catalog_updater.py` and
`tests/test_catalog_payload.py` becomes "the bundled file's shape":
`{"schema_version": 1, "providers": bundled_document()["providers"], "coseeings": [sentinel]}`.

---

### Task 1: Bundled providers; the overlay takes only models from the remote document (P1, P2, P3, P7, §10.2, §11)

**Files:**
- Modify: `setting/catalog.json`; `lib/catalog/overlay.py:1-49` (module docstring, `overlay_documents`, drop the `filter_provider_urls` import); `lib/catalog/model.py:30-42`; `lib/catalog/cache.py:1-6`
- Test: `tests/test_catalog_bundled.py`, `tests/test_catalog_overlay.py`, `tests/test_ai_config_schema.py`, `tests/shipped_catalog.py`, `tests/test_catalog_payload.py`, `tests/test_catalog_updater.py`, `tests/test_catalog_retry.py`, `tests/test_catalog_source_seam.py`, `tests/test_catalog_plugin_wiring.py`, `tests/test_catalog_settings_panel.py`

**Interfaces:**
- Produces: `overlay_documents(bundled, remote) -> (document, issues)` with the §7.3 table; `filter_provider_urls` still exists in `remote.py` (removed in Task 5) but nothing calls it. Test helpers `_canonical(value) -> str` and `_first_differing_provider(bundled: dict, server: dict) -> str | None` (first name in sorted union of keys whose canonical values differ, or present on one side only) in `tests/test_catalog_bundled.py`.

- [ ] **Step 1: Write the failing tests**

`tests/test_catalog_bundled.py` (`shipped_catalog()` now returns `load_overlay_catalog(BundledCatalogSource(SETTING_DIR), None, runnable_providers=RUNNABLE)` after asserting the source's issues are `()`, finding 11):
- `test_the_bundled_document_declares_the_current_schema_version`: `set(document) == {"schema_version", "providers", "coseeings"}`.
- `test_the_bundled_catalog_alone_offers_only_the_sentinel`: unchanged assertions plus `catalog.degraded is False`.
- `test_the_bundled_providers_are_exactly_the_supported_providers`: `set(bundled_document()["providers"]) == SUPPORTED_PROVIDERS`.
- `test_every_bundled_provider_url_is_pinned`: `{name: data["url"]} == {"Anthropic": "https://api.anthropic.com/v1/messages", "DeepSeek": "https://api.deepseek.com/chat/completions", "Google": "https://generativelanguage.googleapis.com/v1beta", "Ollama": "http://localhost:11434/v1/chat/completions", "OpenAI": "https://api.openai.com/v1/responses", "OpenRouter": "https://openrouter.ai/api/v1/chat/completions"}`.
- `test_every_bundled_provider_url_is_on_its_rc9_host`: with `urlsplit`, every non-Ollama URL has scheme `https`, `port is None`, `username`/`password` `None`, empty query and fragment, hostname from `RC9_HOSTS = {"Anthropic": "api.anthropic.com", "DeepSeek": "api.deepseek.com", "Google": "generativelanguage.googleapis.com", "OpenAI": "api.openai.com", "OpenRouter": "openrouter.ai"}`; Ollama's hostname is in `{"localhost", "127.0.0.1"}`.
- `test_the_bundled_providers_build_completely`: `build_catalog({"schema_version": 1, "providers": bundled["providers"], "models": [one model per provider]}, runnable_providers=RUNNABLE)` → six `ProviderEntry` (`set(catalog.providers) == set(bundled["providers"])`), `catalog.issues == ()`.
- `test_the_bundled_providers_equal_the_server_providers`: §11 body, `assert … , f"first differing provider: {_first_differing_provider(...)}"`.
- `test_the_drift_message_names_the_first_differing_provider` parametrized (ids `server-gains`: server adds `Mistral` → `"Mistral"`; `bundled-loses`: bundled drops `Google` → `"Google"`; `float-to-int`: bundled `DeepSeek.setting.temperature` `0.0` → `0` → `"DeepSeek"`; `false-to-int`: bundled `OpenAI.setting.store` `False` → `0` → `"OpenAI"`), each on deep copies of `bundled_document()["providers"]`; also asserts `_canonical` of the two sides differs.

`tests/test_catalog_overlay.py`:
- `test_providers_and_coseeings_come_from_bundled_and_models_from_remote` (replaces `:54-66`): bundled has providers `OpenAI` and `DeepSeek` and a bundled model; remote `_remote()` → models `["gpt-remote&OpenAI"]`, `set(catalog.providers) == {"DeepSeek", "OpenAI"}`, Coseeing labels `("default", "bundled-extra")`.
- `test_remote_providers_never_reach_a_provider_entry` (AC2): remote = `server_document()` with every provider's `url` `https://evil.test/v1`, `setting` `{"evil": True}`, `timeout0` 1, `timeout_max` 2, `label` `"Evil"`; with `StaticSource(bundled_document())`, for every bundled name `(label, url, setting, timeout0, timeout_max)` equals the bundled values; issues `== [("unreferenced_provider", "providers.OpenRouter")]`.
- `test_remote_extra_keys_add_no_issue` (Review Focus 4): `overlay_documents(bundled_document(), dict(server_document(), coseeings=[…], extra={"x": 1}))[1] == ()`.
- `test_remote_coseeings_are_ignored_without_an_issue` (replaces `:68-75`): `document["coseeings"] == [SENTINEL]`, `issues == ()`.
- `test_bundled_models_are_ignored_with_a_lint_issue` (replaces `:78-85`): `[(code, location)] == [("ignored_bundled_models", "bundled.models")]`, `is_dropped_issue` False, models are the remote ones; and `overlay_documents(_bundled(providers={…}), _remote())[1] == ()`.
- `test_the_lint_codes_are_pinned`: `LINT_ISSUE_CODES == {"unreferenced_provider", "ignored_bundled_models"}`.
- `test_no_remote_document_gives_the_sentinel_only` (`:95-111`): `StaticSource(bundled_document())` → `providers == {}`, `models == ()`, groups `(COSEEING_GROUP,)`, `issues == ()`, not degraded, no local items.
- `test_a_broken_bundled_file_plus_a_good_remote_gives_the_sentinel_and_no_local_items` (`:114-126`): `has_local_items` False, default selection the sentinel, not degraded, one `bundled_coseeings_fallback`, `unreadable_file` and `unknown_provider` in codes.
- `test_a_remote_provider_with_a_foreign_url_is_ignored` (`:154-159`): bundled OpenAI at the real URL, `_remote(url="https://evil.test/v1")` → `get_provider("OpenAI").url == "https://api.openai.com/v1/responses"`, model kept, no `unknown_provider`.
- `test_a_remote_model_for_a_provider_the_bundled_file_lacks_is_dropped` parametrized `["Mistral", "openai", "OpenAI "]` (Review Focus 2): `server_document()` plus one model of that provider, shipped bundled → `("unknown_provider", "models[17]")` in issues, the model absent, 16 local items.
- `test_the_overlay_source_is_a_load_catalog_source` (`:162-166`): bundled with providers → `document["providers"]` is the bundled mapping, `issues == ()`.
- `test_the_shipped_target_files_overlay_as_section_7_4`: `bundled_document() == {"schema_version": 1, "providers": server["providers"], "coseeings": [SENTINEL]}`; rest unchanged.

Others:
- `tests/test_ai_config_schema.py`: `test_the_bundled_catalog_is_the_sentinel_plus_the_server_providers`; docstrings of `_catalog_document`/`_server_document`. `tests/shipped_catalog.py` docstring (§16).
- `tests/test_catalog_payload.py` / `tests/test_catalog_updater.py`: `BundledSentinel` with providers (fixture note above). `test_only_disallowed_hosts_is_rejected` → `test_only_unknown_providers_is_rejected` (every model's `provider` `"Mistral"` → `remote_no_models`). `test_a_rejected_payload_is_not_cached_or_installed` uses `_payload("bad", provider="Mistral")`.
- `tests/test_catalog_updater.py`: `test_a_cache_of_the_server_file_loads_with_the_bundled_providers` (`seed_cache(URL_A, server_document())`; `initial_catalog` → source `cache`, `catalog.providers == shipped_overlay().providers`, same local item ids); `test_a_cache_with_hostile_providers_loads_the_bundled_entries` (every provider `url` `https://evil.test/`, other fields changed → every `get_provider(name)` field equals the bundled value).
- `tests/test_catalog_retry.py`: failure row `all-providers-disallowed` → `only-unknown-providers` (`_payload(provider="Mistral")`); non-failure row `dropped-provider` → `dropped-model` (a good model plus a `Mistral` model → succeeded, no timer); probe row `disallowed` → `hostile-providers-ignored` (`_payload("fresh", url="https://evil.test/v1")` → `ok`, 1 model) and `unknown-providers-only` (`_payload(provider="Mistral")` → `no_models`).
- `tests/test_catalog_source_seam.py`: `fetched_catalog(body, runnable_providers=SUPPORTED_PROVIDERS)`; `test_a_remote_provider_entry_cannot_add_a_provider` (Mistral provider + model in the payload, no monkeypatch → `Mistral` not a group, `unknown_provider` in codes, `unsupported_provider` not); `test_a_bundled_provider_this_build_cannot_run_drops_its_models` (`runnable_providers=SUPPORTED_PROVIDERS - {"DeepSeek"}` → `DeepSeek` not a group, `unsupported_provider` in codes). Drop the `remote`/`ProviderUrlRule` imports.
- `tests/test_catalog_plugin_wiring.py`: `test_remote_text_in_catalog_issues_cannot_forge_a_log_line` puts `forged` in a new model's `provider` and selects the `unknown_provider` line (finding 9; same length and control-character assertions); `test_a_fetched_payload_installs_the_bundled_provider_entries` (server payload with hostile providers fetched and delivered → `instance.catalog.get_provider(name)` fields equal `bundled_document()["providers"][name]` for every name).
- `tests/test_catalog_settings_panel.py`: `test_account_box_captions_are_the_same_with_and_without_a_fetched_list`: `[f.dialogs._provider_group_label(c, g) for g in f.dialogs.ACCOUNT_BOX_GROUPS]` equal for `_bundled_only(f)` and the overlay of the server document.

- [ ] **Step 2: Run to verify red**

Run: the add-on suite. Expected: the new and rewritten tests above FAIL (bundled keys, providers `{}` from the bundled side, lint codes, drift `KeyError: 'providers'`); nothing else.

- [ ] **Step 3: Implement**

- `setting/catalog.json`: insert the server's `providers` block verbatim between `schema_version` and `coseeings`.
- `overlay_documents`: lint only for `"models" in bundled` (P3 values); `providers = bundled.get("providers", {})` and `models = remote.get("models", [])` when `remote` is a mapping, `({}, [])` otherwise; no remote-key lint (P2). Module docstring states the §7.3 rule.
- `LINT_ISSUE_CODES` and its comment: `unreferenced_provider`, `ignored_bundled_models`.
- `cache.py` docstring sentence per §9.4.

- [ ] **Step 4: Run to verify green**

Full add-on suite → **1074 passed, 1 skipped**; server 103; `prek run --all-files`; `git diff --check`.

- [ ] **Step 5: Commit** (explicit paths; `git diff --cached --stat`)

`feat: bundle the provider entries and take only models from the remote catalog`

- [ ] **Step 6: Mutation checks** (§17.3; restore with `git checkout -- <file>`): overlay reads `remote.get("providers", {})` → `test_remote_providers_never_reach_a_provider_entry` FAILS; overlay uses bundled providers with no remote document → `test_no_remote_document_gives_the_sentinel_only` FAILS; overlay uses `bundled.get("models")` → `test_bundled_models_are_ignored_with_a_lint_issue` FAILS; drift test with `==` instead of `_canonical` while bundled `DeepSeek.setting.temperature` is `0` → `_canonical` version FAILS and the `==` version passes (proves finding 8); one bundled URL host changed → `test_every_bundled_provider_url_is_pinned` FAILS.

---

### Task 2: `no_providers` rejection and the relaxed document check (P4, P5)

**Files:**
- Modify: `lib/catalog/overlay.py:102-123` (`accept_remote_document` and docstring); `lib/catalog/remote.py:249-282` (`check_remote_document`, `parse_remote_payload` docstrings)
- Test: `tests/test_catalog_payload.py`, `tests/test_catalog_overlay.py`, `tests/test_catalog_updater.py`, `tests/test_catalog_retry.py`

**Interfaces:**
- Consumes: Task 1's overlay.
- Produces: `accept_remote_document(...)` returns `(None, (CatalogIssue("bundled_source_failed", "bundled", "no_providers"),))` when the built, undegraded catalog has `providers == {}`; `check_remote_document(document)` checks only object, `schema_version`, `models`.

- [ ] **Step 1: Write the failing tests**

`tests/test_catalog_payload.py`:
- `PARSE_TABLE`: `providers-list` and `providers-missing` become `(…, None, None)` (Task 4 turns `providers-list` into a rejection).
- `ACCEPT_DOCUMENT_TABLE`: remove the `providers-list` row.
- `test_a_payload_without_providers_is_accepted` (Review Focus 1, absent half): `_server_document()` minus `providers` → accepted; `catalog.providers` and the local item ids equal those of `_accept(_server_document())`.
- `test_empty_models_is_rejected`: `models == []` → `[("remote_no_models", "payload")]`.
- `test_a_bundled_file_without_usable_providers_is_reported_as_such` parametrized ids `unreadable-file` (source returns `(None, (CatalogIssue("unreadable_file", "catalog.json", "ValueError"),))`), `no-providers-key`, `empty-providers`, `providers-list`, `all-incomplete` (every entry without `setting`): `[(code, location, detail)] == [("bundled_source_failed", "bundled", "no_providers")]`.
- `test_one_incomplete_bundled_provider_drops_only_its_models` (Review Focus 3): bundled `OpenAI` without `setting` → accepted; no `OpenAI` group; `incomplete_provider` and `unknown_provider` in `catalog.issues`.

`tests/test_catalog_overlay.py`: the broken-bundled test also asserts `accept_remote_document(broken, _remote(), runnable_providers=SUPPORTED_PROVIDERS) == (None, (CatalogIssue("bundled_source_failed", "bundled", "no_providers"),))`.

`tests/test_catalog_updater.py`: `test_a_cache_without_providers_loads` (server document minus `providers` seeded → source `cache`, 16 local items); `test_a_fetch_without_bundled_providers_is_logged_by_code` (`h.updater._bundled_source` without providers; fetch → status `("none", "failed")` and the record `("warning", "WordBridge: catalog fetch failed host=%s code=%s type=%s", "https://a.test", "bundled_source_failed", "no_providers")`).

`tests/test_catalog_retry.py`: failure row `bundled-no-providers` (bundled source swapped, good payload) arms a retry (CR C1); probe row `bundled-no-providers` → kind `failed`, detail `bundled_source_failed`.

- [ ] **Step 2: Run to verify red**

Run: the add-on suite. Expected FAIL: `test_a_payload_without_providers_is_accepted` (`remote_malformed`), the parse rows, the `no_providers` rows (`remote_no_models`), the cache-without-providers and log tests.

- [ ] **Step 3: Implement**

- `check_remote_document`: delete the `providers` check; docstring "An object with schema_version 1 and a models list".
- `accept_remote_document`: after the `degraded` branch, `if not catalog.providers: return None, (CatalogIssue("bundled_source_failed", "bundled", "no_providers"),)`; docstring per §8.1 (no allowlist wording).

- [ ] **Step 4: Run to verify green** → **1084 passed, 1 skipped**; server 103; prek; `git diff --check`.

- [ ] **Step 5: Commit** `feat: report missing bundled providers and stop requiring remote providers`

- [ ] **Step 6: Mutation checks**: restore the `providers` check → `test_parse_remote_payload_table[providers-missing]` and `test_a_cache_without_providers_loads` FAIL; drop the `has_local_items` branch (always accept) → `test_only_inactive_models_is_rejected` FAILS; drop the `no_providers` branch → `test_a_bundled_file_without_usable_providers_is_reported_as_such` FAILS.

---

### Task 3: The server's `GET /` stops sending `providers` (B2, §12)

**Files:**
- Modify: `server/app/main.py:43-62` (`load_catalog_bytes` and its docstring), `:164-171` (`catalog()` docstring); `tests/shipped_catalog.py` (docstring, `served_document()`, `shipped_overlay()` uses it)
- Test: `server/tests/test_catalog_route.py`; `tests/test_catalog_source_seam.py`, `tests/test_catalog_payload.py`

**Interfaces:**
- Consumes: Task 2 (`check_remote_document()` accepts a document without `providers`).
- Produces: `load_catalog_bytes(path) -> bytes` — validated as today, returns `(json.dumps(document_without_providers, ensure_ascii=False, indent="\t") + "\n").encode("utf8")`, keys in file order. `served_document() -> dict` in `tests/shipped_catalog.py` (server file minus `providers`).

- [ ] **Step 1: Write the failing tests** (`server/tests/test_catalog_route.py`)
  - `test_root_serves_the_catalog_without_providers` (replaces `test_root_serves_the_catalog_file_verbatim`): 200, `application/json`, `no-cache`; `"providers" not in body`; `body["models"] == file["models"]`; `set(body) == set(file) - {"providers"}`.
  - `test_the_served_payload_is_a_schema_1_object_with_local_data`: `"providers" not in body` instead of the mapping check.
  - `test_load_catalog_bytes_keeps_every_other_key_in_file_order` (replaces `..._returns_the_file_bytes_unchanged`): a file with `schema_version`, `providers`, `models`, `extra` → `list(json.loads(result)) == ["schema_version", "models", "extra"]`, values equal, non-ASCII label kept as UTF-8 text (not `\u` escapes).
  - `test_load_catalog_bytes_accepts_a_file_without_providers`: returns the same document.
  - `test_load_catalog_bytes_rejects_a_bad_file` unchanged (startup still fails loudly).
  - Add-on: `test_a_fetched_payload_behaves_exactly_like_the_same_documents_from_disk` and the seam selection test fetch `served_document()`; `PARSE_TABLE` row `served` (the served bytes) parses.
- [ ] **Step 2: Run to verify red**: `cd server && …/.venv/bin/python -m pytest -q tests/test_catalog_route.py` FAILS on `providers` present and file-order bytes; add-on: `ImportError: served_document`.
- [ ] **Step 3: Implement** `load_catalog_bytes` as in Interfaces; docstrings say the served payload is the file without `providers` (the add-on bundles them); `served_document()`.
- [ ] **Step 4: Verify**: server **104 passed** (two tests replaced, one added); add-on **1085 passed, 1 skipped** (one parse row added); prek; `git diff --check`.
- [ ] **Step 5: Commit** `feat: stop sending provider entries from the catalog route`
- [ ] **Step 6: Mutation check**: `load_catalog_bytes` returns the file bytes again → `test_root_serves_the_catalog_without_providers` FAILS.

---

### Task 4: Reject a payload that carries `providers` (B4)

**Files:**
- Modify: `lib/catalog/remote.py` (`check_remote_document`: after the `schema_version` check, `if "providers" in document: return _issue("remote_providers_not_allowed", "providers are bundled with the add-on; the payload may not carry them")`; docstrings)
- Test: `tests/test_catalog_payload.py`, `tests/test_catalog_updater.py`, `tests/test_catalog_retry.py`, `tests/test_catalog_plugin_wiring.py`, `tests/test_catalog_source_seam.py`, and every other test that feeds the server file as a payload (they switch to `served_document()` / the served bytes)

**Interfaces:**
- Consumes: Task 3's `served_document()`; `_probe_failure()` maps every `remote_*` code to `not_a_list` (no probe code change).
- Produces: `_payload()` in `tests/test_catalog_updater.py` without a `providers` key and without its `url` parameter.

- [ ] **Step 1: Write the failing tests**
  - `test_any_remote_providers_key_rejects_the_payload` (`tests/test_catalog_payload.py`) parametrized ids `null`, `list`, `string`, `number`, `empty-mapping`, `hostile-mapping`, `server-providers`: `_accept(dict(served, providers=value))` → `(None, [("remote_providers_not_allowed", "payload")])`; `parse_remote_payload` of the same body → `document is None`, same code.
  - `PARSE_TABLE`: `valid`/`utf8-bom` use the served bytes; `server-file` (the server file's bytes) → `remote_providers_not_allowed`; `providers-list` → `remote_providers_not_allowed`. `ACCEPT_DOCUMENT_TABLE` gains `providers-mapping` → `remote_providers_not_allowed`.
  - `tests/test_catalog_updater.py`: `test_a_cache_that_carries_providers_is_rejected` (seed the server file → `initial_catalog` gives source `none`, no local items, the record `("warning", "WordBridge: catalog cache problem code=%s type=%s", "unreadable_cache", "remote_providers_not_allowed")`); `test_a_fetched_payload_that_carries_providers_is_not_installed_or_cached` (`installed == []`, `cache.stores == []`, status `("none", "failed")`). `test_a_cache_with_hostile_providers_loads_the_bundled_entries` is replaced by the first.
  - `tests/test_catalog_retry.py`: failure row `carries-providers` arms a retry; probe row `hostile-providers-ignored` → `providers-rejected` (`not_a_list`, detail `providers are bundled with the add-on; the payload may not carry them`).
  - `tests/test_catalog_plugin_wiring.py`: `test_a_fetched_payload_installs_the_bundled_provider_entries` fetches `served_document()`; new `test_a_fetched_payload_with_providers_keeps_the_current_catalog`.
- [ ] **Step 2: Run to verify red**: the rejection tests FAIL (accepted today).
- [ ] **Step 3: Implement** the check; `_payload()` and every payload fixture drop `providers`; tests feeding the server file as a payload use `served_document()`.
- [ ] **Step 4: Verify**: full add-on suite green (count in the ledger); server 104; prek; `git diff --check`.
- [ ] **Step 5: Commit** `feat: reject a catalog payload that carries provider entries`
- [ ] **Step 6: Mutation check**: remove the `providers` rejection → `test_any_remote_providers_key_rejects_the_payload` FAILS.

---

### Task 5: Remove the runtime host allowlist, the probe kind and its tip (P6, §13)

**Files:**
- Modify: `lib/catalog/remote.py:8`, `:157-242` (remove `ProviderUrlRule`, `_https_only`, the comment, `PROVIDER_URL_RULES`, `_url_problem`, `filter_provider_urls`; drop the `dataclass` import if unused; keep `_split`, `_DEFAULT_PORTS`, `_host_text`); `catalog_updater.py:144-147`, `:384-388`; `catalog_url_dialog.py:67-70`; `addon/locale/zh_TW/LC_MESSAGES/nvda.po:619-622`
- Delete: `tests/test_catalog_provider_allowlist.py`
- Test: `tests/test_catalog_bundled.py`, `tests/test_catalog_url_dialog.py`

**Interfaces:**
- Consumes: Tasks 1–4. `_probe()` keeps `if issues[0].code == "remote_no_models": return ProbeResult("no_models")` (finding 3); `ProbeResult` kinds: ok, invalid, insecure_scheme, empty, network, http_status, not_a_list, no_models, failed, unavailable.

- [ ] **Step 1: Write the failing test** `test_no_provider_host_allowlist_remains` in `tests/test_catalog_bundled.py` (AC6): no `addon/**/*.py` file and not `nvda.po` contains any of `PROVIDER_URL_RULES`, `ProviderUrlRule`, `filter_provider_urls`, `disallowed_provider_url`, `disallowed_hosts`, `provider addresses WordBridge does not allow`. Remove the `disallowed_hosts` row from `RESULT_ROWS` in `tests/test_catalog_url_dialog.py`.

- [ ] **Step 2: Run to verify red**: `test_no_provider_host_allowlist_remains` FAILS listing `remote.py`, `catalog_updater.py`, `catalog_url_dialog.py`, `nvda.po`.

- [ ] **Step 3: Implement**: remove the code above and `tests/test_catalog_provider_allowlist.py` (its supported-provider and host assertions already live in Task 1's guards); delete the `.po` entry with its comment and reference lines. `msgfmt --check -o /dev/null addon/locale/zh_TW/LC_MESSAGES/nvda.po`.

- [ ] **Step 4: Run to verify green** → T4 − 43 allowlist tests − one dialog row + one scan; server 104; prek; `git diff --check`; `msgfmt --check` clean; `grep -rn "allowlist" addon/` lists nothing stale.

- [ ] **Step 5: Commit** `refactor: remove the provider host allowlist now that providers are bundled`

- [ ] **Step 6: Mutation check**: in `_probe()` delete the `remote_no_models` → `no_models` branch → `test_probe_result_table[unknown-providers-only]` and `[no-models]` FAIL (get `not_a_list`).

---

### Task 6: OQ1 → B — remote models for a provider this release lacks are lint (§18)

OQ1 was answered by the user on 2026-11-05 with **B**. Kept as the last task,
separate from Tasks 1–5, so the decision is one revertable commit.

**Files:**
- Modify: `lib/catalog/model.py:30-42` (`LINT_ISSUE_CODES` and its comment). The spec already records B3 (committed with the plan amendment).
- Test: `tests/test_catalog_settings_panel.py`, `tests/test_catalog_overlay.py` (`test_the_lint_codes_are_pinned`), `tests/test_catalog_plugin_wiring.py`

**Interfaces:**
- Consumes: `dialogs._dropped_entries_message(catalog) -> str | None`; `lib.catalog.model.is_dropped_issue`; `GlobalPlugin._log_catalog_issues` (unchanged: logs every issue).

- [ ] **Step 1: Write the failing tests**
  - `test_a_model_for_a_provider_this_release_lacks_is_not_counted_in_the_dropped_line` (`tests/test_catalog_settings_panel.py`): the overlay of `server_document()` plus one `Mistral` model, built with the plugin's own `lib.catalog` (like `_bundled_only`) → `f.dialogs._dropped_entries_message(catalog) is None`; the catalog still has the `("unknown_provider", "models[17]")` issue.
  - `test_an_unsupported_provider_is_still_counted_in_the_dropped_line`: the same server document with `runnable_providers=SUPPORTED_PROVIDERS - {"DeepSeek"}` → message `"{n} catalog entries could not be loaded; see the NVDA log for details."` with `n` the number of DeepSeek models (the B/`unsupported_provider` boundary).
  - `test_the_lint_codes_are_pinned`: `{"unreferenced_provider", "ignored_bundled_models", "unknown_provider"}`.
  - `test_an_unknown_provider_issue_is_still_logged` (`tests/test_catalog_plugin_wiring.py`): a fetched server payload plus one `Mistral` model → exactly one warning line containing `code=unknown_provider` and `models[17]`.
- [ ] **Step 2: Run to verify red**: the first test and the lint pin FAIL under A (message is "1 catalog entry could not be loaded; …"); the unsupported and logging tests pass already (they pin what B must not change).
- [ ] **Step 3: Implement**: add `"unknown_provider"` to `LINT_ISSUE_CODES`; the comment says why (after B1 a model for a provider only a newer release bundles is expected; it is still logged).
- [ ] **Step 4: Verify** → T5 + 3 (three new tests; the lint pin is modified); server 104; prek; `git diff --check`.
- [ ] **Step 5: Commit** `feat: stop counting models for an unbundled provider as dropped entries`
