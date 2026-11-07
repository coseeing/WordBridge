# Server Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans.
> WordBridge normal flow: one implementer runs every task in order; the
> orchestrator dispatches the final Fable 5.1 review (DEVELOPMENT_WORKFLOW.md §3.3).
> 12 tasks, so batches of 4 (Tasks 1–4, 5–8, 9–12); the implementer stops after
> batches 1 and 2 for a batch review. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship spec items 1, 4–11 and the 2026.11.1 version bump: real guest IPs behind Cloudflare, no DB connection held across the AI call, quota indexes, startup key checks, one session module, `version`/`template` columns, working alembic offline mode, hashed uv lock files, and coded errors the add-on speaks in three languages.

**Architecture:** Server changes stay in `server/app` (FastAPI, sync routes, SQLAlchemy 2). Pure logic goes in small new modules (`app/client_ip.py`, `app/errors.py`) that `app/main.py` wires in at import. Every `lib` change is made in the add-on and copied by `server/sync_addon_code.py`, which now also copies `setting/templates`, `setting/task` and writes `server/app/setting/addon_version.txt` from `buildVars.py`.

**Tech Stack:** Python 3.14, FastAPI 0.141, SQLAlchemy 2.0.54, alembic 1.20, pytest, uv (pinned), MariaDB (verification only), gettext.

**Spec:** `docs/superpowers/specs/2026-11-07-server-improvements-design.md` (commits 588c1ef, 244effa).

## Global Constraints

- Never hand-edit `server/app/lib`, `server/app/dictionary`, `server/app/setting/templates`, `server/app/setting/task`; edit the add-on and run `python3 server/sync_addon_code.py`. `tests/test_server_addon_copy.py` enforces it.
- `server/app/setting/catalog.json` is not synced; the sync never replaces `server/app/setting/` as a whole (spec F5).
- Every deployment value comes from an environment variable with no built-in fallback; errors list every problem and never echo a value (`server/app/settings.py`).
- Responses never contain provider raw text, keys or internals; logs never contain keys. `server/tests/test_provider_key_privacy.py` keeps passing.
- Do not modify `server/app/package/coseeing_auth`; keep Authlib, PyJWT, requests as production dependencies.
- Add-on version is `2026.11.1` (`buildVars.py:25`), and the server version file holds the same.
- Local-mode (own API key) messages do not change, except the D14 crash fix.
- 401 bodies keep `{"detail": ...}` with no `code` (D13). Other FastAPI 422s keep their default body.
- Every new add-on string has a `# Translators:` comment xgettext sees (inside a bare `_(` when the literal is on its own line); log messages are never wrapped in `_()`.
- Translations: zh_TW 附加元件 / 您 and `--no-wrap`; zh_CN 插件; zh_HK 附加組件; merge with `--no-fuzzy-matching` then `msgattrib --no-obsolete`; `msgfmt --check`; never commit `.pot`/`.mo`.
- Tests that load the NVDA plugin import `_load_nvda_plugin` at function scope.
- ruff pinned at 0.16.3; `prek run --all-files` and `git diff --check` clean before every commit. No `prek install`.
- git: stage explicit paths, check `git diff --cached --stat`, English `<type>: <summary>` messages with a body, no Co-Authored-By, no `--no-verify`, no stash, no push, never touch `/workspace/WordBridge`.
- pytest ≤ 3 workers; stop if MemAvailable < 3 GB.
- Commands: server tests `cd server && /workspace/WordBridge/server/.venv/bin/python -m pytest -q -p no:cacheprovider` (baseline 166 passed); root tests `timeout 900 python3 -m pytest -q -p no:cacheprovider tests` (baseline 1160 passed, 25 skipped, 3 subtests).

## Review Focus

1. **Odd `X-Forwarded-For` shapes from Traefik/Docker:** the header repeated on several lines, trailing comma/empty last element, an IPv4-mapped IPv6 peer (`::ffff:173.245.48.1`), and no `request.client` at all. Expected: the last value of the last header line; an IPv4-mapped peer is range-checked as IPv4; no peer gives `invalid`, never a crash. → Task 5 (`test_select_*`), Task 6 (`test_no_peer_and_no_header_is_stored_as_invalid`).
2. **`CF-Connecting-IP` spelled differently for the same address** (`2001:DB8::1` vs `2001:db8::1`, surrounding spaces): one guest must get one quota. Expected: the address is normalised with `ipaddress` before use. → Task 5 (`test_select_normalises_cf_connecting_ip`).
3. **Provider error bodies with an unexpected shape:** JSON list, `error` a string, `message` not a string, no `reason`. Expected: always `LLMServiceError(kind="other")`, never the body. → Task 9 (`test_other_status_bodies_never_crash`).
4. **A Coseeing error body the add-on cannot use:** a known length `code` with `limit` missing, a string, or `true`; a body that is not JSON or not an object. Expected: fall back to the status message, never speak `{limit}` or crash. → Task 11 (`test_unusable_limit_falls_back_to_status_message`, `test_non_object_body_falls_back`).
5. **`alembic downgrade` after the new code has written `2026.11.1` (9 characters) rows:** shrinking `version` back to `varchar(8)` would fail half-way on MariaDB (non-transactional DDL). Expected: the downgrade refuses before any DDL with a message naming the problem. → Task 8 (`test_downgrade_refuses_long_versions_before_any_ddl`, MariaDB check step).

---

### Task 1: Version 2026.11.1, version file and prompt directories in the sync

**Files:**
- Modify: `buildVars.py:25`, `server/sync_addon_code.py`, `tests/test_server_addon_copy.py`
- Create: `server/app/setting/addon_version.txt` (generated by the sync)

**Interfaces:**
- Produces: `sync_addon_code.COPIED_DIRS = ("lib", "dictionary", "setting/templates", "setting/task")` (replaces `PACKAGES`); `sync_addon_code.BUILDVARS: Path`; `sync_addon_code.ADDON_VERSION_FILE = SERVER_APP / "setting" / "addon_version.txt"`; `read_addon_version(buildvars: Path = BUILDVARS) -> str`; `sync(*, addon: Path = ADDON, server_app: Path = SERVER_APP, buildvars: Path = BUILDVARS) -> None`. File format: the version and one `\n`.

- [ ] **Step 1: Write the failing tests** in `tests/test_server_addon_copy.py` (`_files` iterates `COPIED_DIRS`):
  - `test_the_prompt_directories_are_copied`: `"setting/templates/Standard_v1.json" in SERVER_FILES` and `"setting/task/corrector.json" in SERVER_FILES`; `"setting/catalog.json" not in ADDON_FILES` (catalog not part of the sync).
  - `test_the_version_file_matches_build_vars`: `ADDON_VERSION_FILE.read_text(encoding="utf-8") == read_addon_version() + "\n"` and `read_addon_version() == "2026.11.1"`.
  - `test_read_addon_version_reads_the_keyword(tmp_path)`: a file containing `addon_info = AddonInfo(addon_name="x", addon_version="1.2.3")` → `"1.2.3"`; a file without it raises `ValueError`.
  - `test_sync_replaces_only_the_copied_dirs(tmp_path)`: build a fake add-on tree (lib/a.py, dictionary/d.txt, setting/templates/T.json, setting/task/c.json, setting/catalog.json) and a fake server_app with `setting/catalog.json` = `"server"`, `setting/templates/old.json`, `setting/cloudflare_ips.txt`; run `sync(addon=..., server_app=..., buildvars=...)`; assert server `catalog.json` still `"server"`, `cloudflare_ips.txt` kept, `old.json` gone, `T.json` copied, `addon_version.txt` written. (UNPREFIXED files are absent from the fake tree; `sync` must skip a missing UNPREFIXED path only when it is outside the copied tree — simplest: rewrite only paths that exist.)
- [ ] **Step 2: Run** `timeout 900 python3 -m pytest -q -p no:cacheprovider tests/test_server_addon_copy.py` — Expected red: `AttributeError: ... has no attribute 'COPIED_DIRS'` (collection error).
- [ ] **Step 3: Implement** in `server/sync_addon_code.py`: `read_addon_version` with `ast` (find the `addon_version` keyword whose value is a `str` constant; `ValueError` otherwise); `sync()` rmtree+copytree per `COPIED_DIRS` entry under `server_app`, then the UNPREFIXED rewrite, then writes the version file. Update the module docstring (what is copied, why `catalog.json` is not). Bump `buildVars.py:25` to `"2026.11.1"`, then run `python3 server/sync_addon_code.py`.
- [ ] **Step 4: Run** the same file — green. Full root suite: 1160 + new tests (~+4 plus newly parametrised template/task file comparisons) passed, 25 skipped. Server suite: 166 passed (unchanged).
- [ ] **Step 5: Commit** `feat: sync the prompt files and the add-on version to the server` (paths: `buildVars.py server/sync_addon_code.py server/app/setting/addon_version.txt tests/test_server_addon_copy.py`).

### Task 2: One database-session module (item 7)

**Files:**
- Modify: `server/app/dependencies.py`, `server/app/main.py:16-17,310,326`, `server/tests/test_route_permissions.py:13,19-37,62,261`
- Delete: `server/app/dependenciesA.py`

**Interfaces:**
- Produces: `app.dependencies.get_db()` (unchanged), `app.dependencies.get_async_session() -> AsyncGenerator[AsyncSession, None]`, `app.dependencies.async_session` (async sessionmaker, `expire_on_commit=False`). No sync sessionmaker bound to the async engine.

- [ ] **Step 1: Update tests** — `server/tests/test_route_permissions.py` imports `get_async_session` from `app.dependencies` and overrides it; add `test_the_async_dependency_lives_in_dependencies`: `importlib.util.find_spec("app.dependenciesA") is None`.
- [ ] **Step 2: Run** server suite — red: `ImportError: cannot import name 'get_async_session'`.
- [ ] **Step 3: Implement** — move the async engine session into `dependencies.py` with a comment: fastcrud's `crud_router` needs an async session; every other route is sync (spec §11.2). Delete `dependenciesA.py`; update `main.py`.
- [ ] **Step 4: Run** server suite — 167 passed.
- [ ] **Step 5: Commit** `refactor: merge the async session dependency into dependencies.py`.

### Task 3: alembic offline mode (item 9)

**Files:**
- Modify: `server/alembic/env.py:34-55`, `server/alembic.ini:66`
- Create: `server/tests/test_alembic_offline.py`

**Interfaces:**
- Produces: `run_alembic_sql(*args) -> subprocess.CompletedProcess` helper inside the test module (runs `[sys.executable, "-m", "alembic", *args]` with `cwd=server/`, the conftest environment, `capture_output=True, text=True`). Task 8 adds assertions to this file.

- [ ] **Step 1: Write the failing test** `test_offline_upgrade_prints_the_sql`: `result = run_alembic_sql("upgrade", "head", "--sql")`; `result.returncode == 0`, `"ALTER TABLE user ADD COLUMN sso_sub" in result.stdout`, `"UPDATE alembic_version SET version_num='20260923_sso_user'" in result.stdout`, `"placeholder" not in result.stderr`.
- [ ] **Step 2: Run** — red: non-zero return code (`Could not parse SQLAlchemy URL from string 'placeholder'`).
- [ ] **Step 3: Implement** — `run_migrations_offline()` passes the module-level `url` (from `SETTINGS.database_url("mysql+pymysql")`); comment that offline mode uses it only for the dialect. In `alembic.ini` add a comment above `sqlalchemy.url = placeholder`: the real connection settings come from the environment (`alembic/env.py`).
- [ ] **Step 4: Run** server suite — 168 passed.
- [ ] **Step 5: Commit** `fix: let alembic print migration SQL offline`.

### Task 4: Provider API keys checked at startup (item 6, D15, D18)

**Files:**
- Modify: `server/app/correction_config.py`, `server/app/main.py:205-214`, `server/tests/conftest.py`, `server/tests/test_correction_config.py`, `server/tests/test_proofreader_api.py:190-201` (+ drop the now-meaningless per-test `setenv("*_API_KEY")` lines), `server/.env.example:46-54`

**Interfaces:**
- Consumes: `app.settings.Settings`, `SettingsError`, `load_settings(environ)`.
- Produces: `api_key_variable(provider: str) -> str` (`f"{provider.upper()}_API_KEY"`); `CorrectionSettings.api_keys: Mapping[str, str]` (`field(default_factory=dict, repr=False)`, keyed by catalog provider name); `load_correction_settings(settings: Settings | None = None, environ: Mapping[str, str] | None = None) -> CorrectionSettings` raising `SettingsError("Provider API keys are missing: A_API_KEY, B_API_KEY")` (sorted names, no values). Unresolvable `COSEEING_MODEL_IDS` entries: `logger.warning` naming the id, no key needed.

- [ ] **Step 1: Write the failing tests** in `server/tests/test_correction_config.py` using an explicit `environ` dict built from `os.environ` minus every `*_API_KEY`:
  - `test_a_served_provider_without_a_key_stops_startup`: default DeepSeek, ids `gpt-6-luna&OpenAI`, no keys → `SettingsError`; message contains `DEEPSEEK_API_KEY` and `OPENAI_API_KEY`.
  - `test_a_blank_key_counts_as_missing`: `DEEPSEEK_API_KEY="  "` → message contains `DEEPSEEK_API_KEY`.
  - `test_the_error_never_echoes_a_key`: OpenAI key `"sk-visible"`, DeepSeek missing → `"sk-visible" not in str(error)`.
  - `test_an_unused_providers_key_is_not_required`: ids `""`, only `DEEPSEEK_API_KEY` set → `settings.api_keys == {"DeepSeek": <value>}`.
  - `test_an_unservable_coseeing_id_warns_and_needs_no_key(caplog)`: ids `"qwen2&Ollama,missing&Nobody"` → loads; both ids in `caplog.text` at WARNING; `"Ollama" not in settings.api_keys`.
  - `test_api_keys_are_not_in_the_repr`: `"test-key" not in repr(settings)`.
  - `test_importing_app_settings_needs_no_api_key`: subprocess `python -c "import app.settings"` with every `*_API_KEY` removed → return code 0.
  - In `test_proofreader_api.py` replace `test_missing_api_key_is_5xx_and_writes_no_interaction` with `test_the_request_uses_the_key_read_at_startup`: `monkeypatch.delenv("DEEPSEEK_API_KEY")` → 200 and `fake_run_typo_correction[0]["credential"] == {"api_key": main_module.CORRECTION_SETTINGS.api_keys["DeepSeek"]}`.
  - `conftest.py` sets `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `OPENROUTER_API_KEY` to `test-key-<provider>`.
- [ ] **Step 2: Run** server suite — red: `TypeError: load_correction_settings() got an unexpected keyword argument 'environ'` and the proofreader test gets 500.
- [ ] **Step 3: Implement** in `correction_config.py`; `main.py` builds `credential` from `CORRECTION_SETTINGS.api_keys[model_entry.provider]` and drops the `os` import and the 500 branch. `.env.example`: replace "Not checked at startup …" with "Required for every provider a served model uses (the default model and the servable COSEEING_MODEL_IDS); the server refuses to start without them."
- [ ] **Step 4: Run** server suite — 168 − 1 + 8 = 175 passed. Root suite unchanged.
- [ ] **Step 5: Commit** `feat: require the served providers' API keys at startup`.

**Batch 1 ends here: run the full verification (root, server, prek, `git diff --check`), update the ledger, report.**

### Task 5: Client IP selection and Cloudflare ranges (item 1, part 1)

**Files:**
- Create: `server/app/client_ip.py`, `server/app/setting/cloudflare_ips.txt`, `server/update_cloudflare_ips.py`, `server/tests/test_client_ip.py`
- Modify: `server/app/settings.py`, `server/tests/conftest.py`, `server/tests/test_settings.py`, `server/.env.example`

**Interfaces:**
- Produces:
  - `app.settings.CLIENT_IP_SOURCES = ("cloudflare", "proxy")`; `Settings.client_ip_source: str`; `CLIENT_IP_SOURCE` in `REQUIRED_VARIABLES`; problem text `CLIENT_IP_SOURCE must be cloudflare or proxy`.
  - `app.client_ip.CLOUDFLARE_RANGES_PATH: Path` (`app/setting/cloudflare_ips.txt`).
  - `load_cloudflare_networks(path: Path) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]` — one CIDR per line, blank lines ignored, `ValueError` naming the file and every bad line number; missing file or no ranges → `ValueError`.
  - `select_client_ip(*, forwarded_for: Sequence[str], cf_connecting_ip: str | None, peer_host: str | None, source: str, cloudflare_networks) -> str | None`.
  - `server/update_cloudflare_ips.py`: `render_ranges(v4_text: str, v6_text: str) -> str` (validates every line with `ip_network(strict=True)`, raises `ValueError`), `main()` fetches `https://www.cloudflare.com/ips-v4` and `/ips-v6` with `urllib.request` and overwrites the file.
- Algorithm the tests do not fully fix: peer = last non-empty item of `",".join(forwarded_for).split(",")` stripped, else `peer_host`. For the range check, a peer that parses as IPv6 with `.ipv4_mapped` is checked as that IPv4. In `cloudflare` mode, when the peer is in a range and `cf_connecting_ip.strip()` parses, return `str(ip_address(...))` (normalised); otherwise return the peer. A peer that parses is returned as `str(ip_address(peer))`; one that does not (e.g. `testclient`) is returned unchanged.

- [ ] **Step 1: Write the failing tests** in `server/tests/test_client_ip.py` (`CF = load_cloudflare_networks(CLOUDFLARE_RANGES_PATH)`; edge `173.245.48.1`, edge v6 `2400:cb00::1`):
  - `test_proxy_mode_uses_the_last_forwarded_value`: `["6.6.6.6, 10.0.0.2"]`, CF header `1.1.1.1` → `"10.0.0.2"`.
  - `test_proxy_mode_without_the_header_uses_the_peer`: `[]`, peer `"10.0.0.9"` → `"10.0.0.9"`.
  - `test_cloudflare_mode_trusts_cf_connecting_ip_from_an_edge` (v4 and v6 parametrised): `["9.9.9.9, 173.245.48.1"]` + `"198.51.100.7"` → `"198.51.100.7"`; `["2400:cb00::1"]` + `"2001:db8::7"` → `"2001:db8::7"`.
  - `test_cloudflare_mode_ignores_a_forged_header_from_a_non_edge_peer`: `["173.245.48.1, 203.0.113.5"]` + `"198.51.100.7"` → `"203.0.113.5"`.
  - `test_cloudflare_mode_falls_back_when_the_header_is_missing_or_malformed` (parametrised `None`, `""`, `"not-an-ip"`, `"1.2.3.4, 5.6.7.8"`) → the edge peer.
  - `test_select_uses_the_last_header_line`: `["1.1.1.1", "203.0.113.5"]` proxy → `"203.0.113.5"`.
  - `test_select_skips_an_empty_last_item`: `["203.0.113.5, "]` → `"203.0.113.5"`.
  - `test_select_checks_an_ipv4_mapped_peer_as_ipv4`: `["::ffff:173.245.48.1"]` + `"198.51.100.7"` cloudflare → `"198.51.100.7"`.
  - `test_select_normalises_cf_connecting_ip`: `" 2001:DB8::1 "` and `"2001:db8::1"` give the same result.
  - `test_select_with_no_peer_returns_none`: `[]`, `None` → `None`.
  - `test_the_bundled_ranges_load`: `len(CF) > 10` and both versions present.
  - `test_a_bad_line_stops_loading(tmp_path)`: `"173.245.48.0/20\nnope\n10.0.0.1/8\n"` → `ValueError` matching `line 2` and `line 3`; missing file and empty file → `ValueError`.
  - `test_render_ranges_validates_and_round_trips(tmp_path)`: output loads with `load_cloudflare_networks`; `render_ranges("nope", "")` raises `ValueError`.
  - `server/tests/test_settings.py`: `COMPLETE["CLIENT_IP_SOURCE"] = "cloudflare"`; `test_client_ip_source_accepts_both_values` (parametrised); `test_a_malformed_value_stops_startup` gains `("CLIENT_IP_SOURCE", "Cloudflare")` and `("CLIENT_IP_SOURCE", "traefik")`.
- [ ] **Step 2: Run** server suite — red: `ModuleNotFoundError: No module named 'app.client_ip'`; settings tests fail on `CLIENT_IP_SOURCE`.
- [ ] **Step 3: Implement** the settings reader (`_Reader.choice(name, options)`), `client_ip.py`, the update script; run `python3 server/update_cloudflare_ips.py` to create the range file; `conftest.py` sets `CLIENT_IP_SOURCE=cloudflare`; `.env.example` gets a "Client IP" section: `CLIENT_IP_SOURCE=cloudflare` with notes (cloudflare = proxied through Cloudflare, proxy = DNS only; assumes exactly one proxy, Traefik, in front of the server; ranges file updated with `python3 server/update_cloudflare_ips.py`).
- [ ] **Step 4: Run** server suite — ≈ 175 + 22 passed.
- [ ] **Step 5: Commit** `feat: choose the client IP from the proxy and Cloudflare headers`.

### Task 6: Use the selected client IP in `/proofreader` (item 1, part 2)

**Files:**
- Modify: `server/app/main.py:77-84,109-115`, `server/tests/test_proofreader_api.py`

**Interfaces:**
- Consumes: `select_client_ip`, `load_cloudflare_networks`, `CLOUDFLARE_RANGES_PATH`, `SETTINGS.client_ip_source`.
- Produces: `main.CLOUDFLARE_NETWORKS` (loaded at import); `get_client_ip(request: Request) -> str | None` (uses `request.headers.getlist("x-forwarded-for")`, `request.headers.get("cf-connecting-ip")`, `request.client.host if request.client else None`).

- [ ] **Step 1: Write the failing tests** in `server/tests/test_proofreader_api.py`:
  - `test_cloudflare_mode_stores_cf_connecting_ip_from_an_edge`: headers `X-Forwarded-For: 9.9.9.9, 173.245.48.1`, `CF-Connecting-IP: 198.51.100.7` → stored `ip_address == "198.51.100.7"`.
  - `test_a_forged_cf_header_from_a_non_edge_peer_is_ignored`: XFF `173.245.48.1, 203.0.113.5` + CF `198.51.100.7` → stored `"203.0.113.5"`.
  - `test_guests_behind_one_edge_have_separate_quotas`: seed 0.06 for `198.51.100.7`; request via edge with CF `198.51.100.8` → 200.
  - `test_proxy_mode_ignores_cf_connecting_ip`: `monkeypatch.setattr(main_module, "SETTINGS", dataclasses.replace(main_module.SETTINGS, client_ip_source="proxy"))`; same edge headers → stored `"173.245.48.1"`.
  - `test_no_peer_and_no_header_is_stored_as_invalid`: call `main_module.get_client_ip` with a stub request (`headers` = `starlette.datastructures.Headers({})`, `client=None`) → `None`; `_storable_ip(None) == "invalid"`.
  - Existing XFF tests keep their single-value headers (last == first) and keep passing.
- [ ] **Step 2: Run** — red: the first, second and fourth store `9.9.9.9`/`173.245.48.1`; the stub request raises `AttributeError`.
- [ ] **Step 3: Implement** `get_client_ip` and replace the comment at `main.py:77-84` with the new trust model (last XFF value is Traefik's; exactly one proxy; Cloudflare ranges bundled; stale ranges only make quotas stricter).
- [ ] **Step 4: Run** server suite — ≈ +5 passed.
- [ ] **Step 5: Mutation check (§19.2)** — in a scratch copy of `server/` (never the worktree), apply each mutant to `app/client_ip.py` and run `tests/test_client_ip.py tests/test_proofreader_api.py`: (a) take the first `X-Forwarded-For` value, (b) skip the range check, (c) trust `CF-Connecting-IP` in `proxy` mode, (d) drop the IPv4-mapped handling. Each must fail at least one test; record results in the ledger.
- [ ] **Step 6: Commit** `feat: count guest quotas per real client IP`.

### Task 7: No database connection held during the AI call (item 4)

**Files:**
- Modify: `server/app/main.py` (`proofreader`)
- Create: `server/tests/test_proofreader_connection.py`

**Interfaces:**
- Consumes: `get_db`, `get_verified_sub` (overridden), real `get_optional_user`.
- Produces: nothing new; `proofreader` calls `db.commit()` after the quota check and model resolution, before `run_typo_correction`.

- [ ] **Step 1: Write the failing tests** with a file SQLite engine (`tmp_path / "pool.db"`, default `QueuePool`), `Base.metadata.create_all`, `sessionmaker(engine)` (default `expire_on_commit=True`, like production), `get_db` overridden by a generator that opens and closes a session per request, `get_verified_sub` overridden to return `None` (guest) or `"sub-pool"` (seeded verified user, quota 1000); the fake `run_typo_correction` records `engine.pool.checkedout()`:
  - `test_a_guest_request_holds_no_connection_during_the_ai_call`: recorded `== [0]`; 200.
  - `test_a_signed_in_request_holds_no_connection_and_links_the_user`: recorded `== [0]`; the stored interaction's `user_id == user.id` (queried in a fresh session).
- [ ] **Step 2: Run** — red: recorded `[1]`.
- [ ] **Step 3: Implement** — one `db.commit()` with a comment (ends the read-only quota transaction so the pooled connection is free during the AI call; `user` expires and reloads on the write).
- [ ] **Step 4: Run** server suite — +2 passed.
- [ ] **Step 5: Commit** `perf: release the database connection during the AI call`.

### Task 8: `version`, `template`, no `category`, quota indexes, one migration (items 5, 8)

**Files:**
- Modify: `server/app/models/models.py`, `server/app/models/schemas.py`, `server/app/correction_config.py`, `server/app/main.py`, `server/tests/test_proofreader_api.py:59-75`, `server/tests/test_route_permissions.py:66-82`, `server/tests/test_alembic_offline.py`
- Create: `server/alembic/versions/20261107_interaction_template.py`, `server/tests/test_interaction_migration.py`

**Interfaces:**
- Produces:
  - `Interaction.version: String(32)`; `Interaction.template: Mapped[str] = mapped_column(String(64))` (required init argument, placed after `version`); `category` removed; `__table_args__` with `Index("ix_interaction_user_id_request_time", "user_id", "request_time")` and `Index("ix_interaction_ip_address_request_time", "ip_address", "request_time")`.
  - `correction_config.ADDON_VERSION_PATH = SETTING_DIR / "addon_version.txt"`; `load_addon_version(path: Path = ADDON_VERSION_PATH) -> str` (`ValueError` when missing or blank); `template_stem(template_name: str) -> str` (`"Standard_v1.json"` → `"Standard_v1"`).
  - `main.ADDON_VERSION` (loaded at import).
  - Migration `revision = "20261107_interaction_template"`, `down_revision = "20260923_sso_user"`. Upgrade: both indexes, `version` → `String(32)` (`existing_nullable=False`), add `template` `String(64)` NOT NULL with `server_default=""` then drop the server default (existing rows get `""`, D11), drop `category`. Downgrade: online only, first `SELECT COUNT(*) FROM interaction WHERE CHAR_LENGTH(version) > 8`; non-zero → `RuntimeError` saying how many rows and to restore the backup or shorten them; then add `category` `String(8)` NULL, drop `template`, `version` → `String(8)`, drop both indexes. If MariaDB drops the implicit `user_id` FK index when the composite index is created, the upgrade recreates it explicitly (D2); decided in Step 6.

- [ ] **Step 1: Write the failing tests**
  - `test_proofreader_api.py`: `test_the_stored_version_is_the_add_on_version`: stored `version == "2026.11.1" == main_module.ADDON_VERSION`; `test_the_stored_template_is_the_template_stem` (parametrised `standard` → `Standard_v1`, `lite` → `Lite_v1`).
  - `test_correction_config.py`: `test_load_addon_version_reads_the_file(tmp_path)`; `test_a_missing_or_blank_version_file_stops_startup(tmp_path)` (parametrised missing / `" \n"`) → `ValueError`.
  - `test_route_permissions.py`: `test_the_admin_schema_has_template_not_category`: `"template" in InteractionSchema.model_fields`, `"category" not in`; `"category" not in Interaction.__table__.c`.
  - `server/tests/test_interaction_migration.py`: load the migration module by path, replace its `op` with a recorder:
    - `test_upgrade_matches_the_model`: created index names/columns == the model's `Interaction.__table__.indexes`; the `version` alter's `type_.length == 32 == Interaction.__table__.c.version.type.length`; added `template` length 64, `nullable=False`; `drop_column("interaction", "category")`; `down_revision == "20260923_sso_user"`.
    - `test_downgrade_refuses_long_versions_before_any_ddl`: recorder's bind returns count 3 → `RuntimeError` matching `3`, and no DDL op was recorded.
  - `test_alembic_offline.py`: `test_offline_sql_contains_the_new_migration`: stdout contains `CREATE INDEX ix_interaction_user_id_request_time`, `CREATE INDEX ix_interaction_ip_address_request_time`, `ALTER TABLE interaction DROP COLUMN category`, `version_num='20261107_interaction_template'`.
- [ ] **Step 2: Run** server suite — red: missing `ADDON_VERSION`/`load_addon_version`, migration file not found.
- [ ] **Step 3: Implement** models, schema, loader, `main.py` (`version=ADDON_VERSION, template=template_stem(template_name)`, no `category`), the migration (downgrade check skipped in offline mode via `context.is_offline_mode()`), update `_seed_interaction` helpers (`version="2026.11.1"`, `template="Standard_v1"`, no `category`).
- [ ] **Step 4: Run** server suite — ≈ +9 passed.
- [ ] **Step 5: MariaDB check (D3, D16)** — `apt-get install -y mariadb-server`; record `mariadbd --version`. Scratch `git worktree add --detach <scratchpad>/base-918566c 918566c`; create database `WordBridge`; from the base worktree's `server/` run `Base.metadata.create_all` (with `app.user.models` and `app.models.models` imported) against it; `alembic stamp 20260923_sso_user`; then in the task worktree `alembic upgrade head`, `SHOW CREATE TABLE interaction` (expect both composite indexes, `KEY user_id`, `version varchar(32)`, `template`, no `category`), `alembic check` (no differences), insert one row with `version='2026.11.1'`, `alembic downgrade -1` (expect the refusal and an unchanged schema), delete the row, `alembic downgrade -1` (schema equal to the starting one, `category` empty), `alembic upgrade head`. Record commands and output in the ledger. Remove the scratch worktree afterwards (`git worktree remove`; it is ours).
- [ ] **Step 6: Fix** whatever Step 5 shows (for example the implicit `user_id` index) with a test first where SQLite can show it; otherwise record a `Ruling:`.
- [ ] **Step 7: Commit** `feat: record the add-on version and template and index the quota queries`.

**Batch 2 ends here: full verification, ledger, report.**

### Task 9: `LLMServiceError.kind` and defensive error parsing (item 11 lib, D14)

**Files:**
- Modify: `addon/globalPlugins/WordBridge/lib/llm/errors.py`, `.../lib/llm/provider.py:58-118,150-157`, `.../lib/llm/executor.py:66-76`, `tests/test_llm_errors.py`; then `python3 server/sync_addon_code.py` (server copies)

**Interfaces:**
- Produces: `LLMServiceError(message: str = "", *, kind: str = "other")` with `.kind`; `errors.KINDS = frozenset({"overloaded", "rate_limited", "unreachable", "configuration", "other"})`; an unknown kind raises `ValueError`. Mapping: 401/403/404 → `configuration`; 429 → `rate_limited`; 503 → `overloaded` (existing message); 529 → `overloaded` with the generic "An error occurred, status code = " message; other statuses → `other`; `send()` without response and `try_connection()` failure → `unreachable`; executor `KeyError` → `other`. Generic branch text: `_("An error occurred, status code = ") + f"{status}, {detail}"` where `detail` is `error.message` when the body is a JSON object whose `error` is an object with a `str` `message`, else `getattr(response, "reason", None) or ""`.

- [ ] **Step 1: Write the failing tests** in `tests/test_llm_errors.py`:
  - `test_an_http_error_has_its_kind` (parametrised 401/403/404 → configuration, 429 → rate_limited, 503 → overloaded, 529 with `{"error": {"message": "Overloaded"}}` → overloaded and message `"An error occurred, status code = 529, Overloaded"`, 500 → other).
  - `test_other_status_bodies_never_crash` (parametrised bodies `"<html>bad gateway</html>"`, `"{}"`, `'{"error": {}}'`, `'{"error": "x"}'`, `'{"error": {"message": 5}}'`, `"[1]"`, each with `reason="Bad Gateway"` and with no `reason` attribute): raises `LLMServiceError`, `kind == "other"`, `str(error) == "An error occurred, status code = 502, Bad Gateway"` (or `"... = 502, "`), no body fragment (`html`, `error`, `[1]`) in it.
  - `test_unreachable_errors_have_kind_unreachable` for `send()` and `try_connection()`.
  - `test_an_unexpected_response_shape_has_kind_other`.
  - `test_an_unknown_kind_is_rejected`.
  - Existing message tests stay unchanged.
- [ ] **Step 2: Run** `timeout 900 python3 -m pytest -q -p no:cacheprovider tests/test_llm_errors.py` — red: `AttributeError: 'LLMServiceError' object has no attribute 'kind'`, `JSONDecodeError`.
- [ ] **Step 3: Implement**; no new translatable string. Run `python3 server/sync_addon_code.py`.
- [ ] **Step 4: Run** root suite (≈ +25 passed, 25 skipped) and server suite (unchanged count; `test_provider_key_privacy.py` passes).
- [ ] **Step 5: Commit** `feat: classify AI service errors by kind and stop crashing on odd error bodies`.

### Task 10: Coded error responses on the server (item 11 server, D5–D7, D13, D19)

**Files:**
- Create: `server/app/errors.py`, `server/tests/test_error_codes.py`
- Modify: `server/app/main.py`, `server/app/user/auth.py:98-102,123-124`, `server/app/user/linking.py:21-78,125,180,204`, `server/tests/test_proofreader_api.py` (old status asserts), `server/tests/test_sso_auth.py`, `server/tests/test_sso_linking.py`

**Interfaces:**
- Consumes: `LLMServiceError.kind` (Task 9).
- Produces in `app/errors.py`:
  - `class ApiError(HTTPException)`: `__init__(self, status_code: int, code: str, detail: str, *, limit: int | None = None)`; attributes `code`, `limit`.
  - `PROVIDER_CODES = {"overloaded": "provider_overloaded", "rate_limited": "provider_rate_limited", "unreachable": "provider_unreachable", "configuration": "provider_configuration", "other": "provider_error"}`.
  - `provider_failure(error: LLMServiceError) -> ApiError` (502, code from `PROVIDER_CODES`, fixed English detail without provider text).
  - `api_error_handler(request, exc: ApiError) -> JSONResponse` → `{"detail", "code"}` plus `"limit"` only when set; `unexpected_error_handler(request, exc: Exception) -> JSONResponse` → 500 `service_error`. Both registered in `main.py`.
- `main.py`: the `max_length` leaves `ProofreaderRequest.request` (keep `min_length=1`); `proofreader` checks `len(text) > REQUEST_TEXT_MAX_LENGTH` first (413 `text_too_long`, `limit=8000`), then the guest limit (413 `guest_text_too_long`, `limit=SETTINGS.guest_text_limit`), then quotas (429 `guest_quota_exceeded` / `user_quota_exceeded`), then the model (422 `model_unavailable`). `LLMServiceError` → `logger.warning("AI service %s failed (%s): %s", provider, kind, text)` with every configured API key replaced by `***` in `text`, then `provider_failure`; any other exception → `logger.exception`, 500 `service_error`; write failure → 500 `service_error`. Rewrite the comment at `main.py:238-239` (details go to the log, never the key, never the client).

- [ ] **Step 1: Write the failing tests** in `server/tests/test_error_codes.py` (reuse `_client`/fake helpers from `test_proofreader_api.py` by import), asserting `(status, body["code"], body.get("limit"))`:
  - guest 129 chars → `(413, "guest_text_too_long", 128)`; anyone 8001 chars → `(413, "text_too_long", 8000)` (guest and user parametrised); guest 8001 chars gets `text_too_long` (the universal limit is checked first).
  - guest IP quota and global quota → `(429, "guest_quota_exceeded", None)`; user quota → `(429, "user_quota_exceeded", None)`.
  - unknown, inactive and unlisted model → `(422, "model_unavailable", None)`.
  - `test_each_kind_maps_to_its_provider_code` (parametrised over the 5 kinds, fake raises `LLMServiceError("raw provider text sk-test", kind=k)`) → 502 and the mapped code; `"raw provider text" not in response.text`.
  - `test_a_bug_in_the_ai_call_is_service_error` → `(500, "service_error", None)`.
  - `test_a_failed_write_is_service_error` → `(500, "service_error", None)`.
  - `test_an_unexpected_error_elsewhere_is_service_error`: monkeypatch `strings_diff` to raise; `TestClient(app, raise_server_exceptions=False)` → `(500, "service_error", None)`.
  - `test_provider_failure_logs_provider_and_kind_but_never_the_key(caplog)`: message contains the configured DeepSeek key → log has `DeepSeek`, the kind, `raw provider text`, not the key.
  - `test_sso_unavailable_and_account_codes` via the real dependency chain (`get_token_verifier` override raising `DiscoveryError` → `(503, "sso_unavailable")`; inactive user → `(403, "account_disabled")`).
  - `test_401_bodies_have_no_code`: malformed `Authorization` → `response.json() == {"detail": "Authorization header must be a well-formed Bearer credential"}`.
  - `test_other_validation_errors_keep_fastapi_422`: `language="en"` → 422 and `"code" not in body`.
  - `test_sso_linking.py`: existing 403/503/409 asserts gain `excinfo.value.code == "account_unverified" / "sso_unavailable" / "account_conflict"`.
  - Update old asserts: 404 → 422 for models, guest text 429 → 413, the 8000-character 422s → 413.
- [ ] **Step 2: Run** server suite — red: `ModuleNotFoundError: No module named 'app.errors'`.
- [ ] **Step 3: Implement** as in Interfaces.
- [ ] **Step 4: Run** server suite — ≈ +25 passed; `test_provider_key_privacy.py` passes.
- [ ] **Step 5: Mutation check (§19.2)** — in a scratch copy, swap two entries of `PROVIDER_CODES`, map 529 to `other` in the add-on lib, and drop the key scrubbing; each must fail a test; record in the ledger.
- [ ] **Step 6: Commit** `feat: return an error code with every server error`.

### Task 11: The add-on speaks the error codes (item 11 add-on, §17)

**Files:**
- Modify: `addon/globalPlugins/WordBridge/__init__.py:717-736`, `addon/locale/{zh_TW,zh_CN,zh_HK}/LC_MESSAGES/nvda.po`
- Create: `tests/test_coseeing_error_codes.py`

**Interfaces:**
- Produces in `__init__.py`: `_coseeing_error_details(response) -> tuple[str | None, int | None]` (code and limit from the JSON object body; anything else `(None, None)`; `limit` only when an `int` > 0 and not `bool`); `_coseeing_error_message(code: str | None, limit: int | None) -> str | None` (the §17 message, `None` for unknown/missing code or a length code without a usable limit). The worker logs `log.warning("Coseeing proofreader request failed: status %s, code %s", status, code)`, speaks the code message when there is one, else today's 401/429/other chain.
- Strings: exactly the 15 msgids of spec §17, length codes with `{limit}` filled by `.format(limit=limit)`.

- [ ] **Step 1: Write the failing tests** (`_load_nvda_plugin` imported inside each fixture function; worker fixture copied from `test_proofreader_failures_use_stable_notification`):
  - `test_each_code_speaks_its_message` (parametrised over the 15 codes; body `{"detail": "x", "code": c, "limit": 128}` with status from the spec table) → `messages == [expected English]`, `{limit}` filled with 128 for the two length codes.
  - `test_unknown_or_missing_code_falls_back_by_status` (parametrised 401/429/503 × no code / `"made_up"`) → today's messages.
  - `test_unusable_limit_falls_back_to_status_message` (limit missing, `"128"`, `True`, `0`) → `"The Coseeing request failed. Please try again later."` for 413.
  - `test_non_object_body_falls_back` (json raises `ValueError`; json returns a list) → status message.
  - `test_code_and_status_are_logged_untranslated` (via `log_warnings`) → an entry containing `413` and `guest_text_too_long`.
  - `test_the_error_strings_have_translator_comments_and_translations`: `_assert_translated(ADDON / "__init__.py", ZH_TW)` from `test_catalog_url_dialog` (imported in the function) with the §17 zh_TW table; zh_CN and zh_HK `.po` files have a non-empty msgstr for each msgid (multi-line entries joined).
- [ ] **Step 2: Run** `timeout 900 python3 -m pytest -q -p no:cacheprovider tests/test_coseeing_error_codes.py` — red: messages are the generic fallback.
- [ ] **Step 3: Implement**; every `_(` carries a `# Translators:` comment xgettext sees.
- [ ] **Step 4: Translate** — `apt-get install -y gettext`; `scons pot`; for zh_TW `msgmerge --no-fuzzy-matching --no-wrap -U` then `msgattrib --no-obsolete --no-wrap -o`; zh_CN/zh_HK the same without `--no-wrap`; fill the 15 msgstrs (zh_TW from §17 with 您; zh_CN 插件 terms; zh_HK 附加組件 terms); `msgfmt --check -o /dev/null` each. Do not stage `.pot`/`.mo`. Check that the merge touched only the new entries and line references (`git diff --stat`).
- [ ] **Step 5: Run** root suite — ≈ +30 passed, 25 skipped; `tests/test_catalog_url_dialog.py` translator tests pass.
- [ ] **Step 6: Commit** `feat: tell Coseeing users why a correction failed` (source + three `.po` + test).

### Task 12: uv dependency lists and Dockerfile (item 10)

**Files:**
- Create: `server/requirements.in`, `server/requirements-dev.in`, `server/requirements-dev.txt`
- Modify: `server/requirements.txt`, `server/Dockerfile:8-9`

**Interfaces:**
- Produces: production direct dependencies = what `server/app` and `server/alembic` import plus runtime needs: `fastapi`, `fastcrud`, `pydantic`, `SQLAlchemy`, `python-dotenv`, `requests`, `Authlib`, `PyJWT[crypto]`, `cryptography`, `joserfc` (only if imported), `chinese-converter`, `hanzidentifier`, `pypinyin`, `zhon` (only those the lib imports), `alembic`, `PyMySQL`, `aiomysql`, `uvicorn` (extras: implementer's choice — record it). Dev: `-r requirements.in`, `pytest`, `httpx`, `aiosqlite`. Compile with `uv pip compile --python-version 3.14 --generate-hashes`; dev with `--constraint requirements.txt`; the commands are comments at the top of each `.in`. Existing pins are kept as preferences (compile into the existing `requirements.txt`).

- [ ] **Step 1: Inventory** — grep every top-level import under `server/app`, `server/alembic`, `server/tests`; map to distributions; record the list in the ledger.
- [ ] **Step 2: Write** the `.in` files; install uv (`python3 -m pip install --break-system-packages uv==<pinned>`); compile both lists.
- [ ] **Step 3: Clean-environment checks** (scratchpad venvs, never the main venv): (a) venv + `uv pip sync requirements-dev.txt` (hash-checked) → full server suite passes with the same count; (b) venv + `uv pip sync requirements.txt` → with the conftest's environment variables, `python -c "import app.main"` succeeds; also `python -m alembic upgrade head --sql` succeeds. Confirm whether `uv pip sync` verifies hashes without a flag (try a tampered hash; record the result). Expected red before the lists exist: (a) fails on a fresh venv with only the old `requirements.txt` (no `pytest`).
- [ ] **Step 4: Dockerfile** — `RUN --mount=from=ghcr.io/astral-sh/uv:<pinned>,source=/uv,target=/bin/uv uv pip sync --system requirements.txt` (plus `--require-hashes` if Step 3 shows it is needed). Docker is not available here: record that the image build is unverified.
- [ ] **Step 5: Run** full verification; commit `build: lock the server dependencies with uv and hashes`.

**After Task 12: full verification, ledger, final report.**
