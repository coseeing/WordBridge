# Server improvements: client IP, connections, indexes, startup checks, error codes and dependency lists

- **Branch:** `feat/server-improvements` (from `feat/server-settings` at `918566c`)
- **Workflow:** normal flow (DEVELOPMENT_WORKFLOW.md §3). Nothing has to be
  byte-identical to a known build, so the complex flow (§4) does not apply.
- **Source:** the design was discussed with the user item by item and
  recorded in Traditional Chinese in `storage/spec.md` (main checkout,
  gitignored). This document is its English form; it changes no decision.
  Where verifying a reference showed that an assumption there is wrong or
  incomplete, the design is left as decided and the point is listed in §20.
- **Scope:** `server/`, plus the add-on changes item 11 needs
  (`addon/globalPlugins/WordBridge/`) and the version bump in `buildVars.py`
  (§16).
- **Amends:** `docs/superpowers/specs/2026-09-23-server-proofreader-sso-design.md`
  (cited as "SSO spec"): it kept `get_client_ip()`'s `X-Forwarded-For`
  handling "for this phase" (SSO spec:103), returned 429 for guest text over
  the length limit (SSO spec:103, :143) and wrote "existing category/version
  values" (SSO spec:106). Items 1, 11 and 8 replace those three points.

Paths are relative to the repository root unless they start with `/workspace/`.
Line numbers were checked against `918566c`.

## 1. Background

### 1.1 Deployment (checked on the host, outside the repository)

```
user ──► Cloudflare (proxied) ──► Traefik v3.0.0 (shared entry, /workspace/entry)
     ──► wob-server container (one uvicorn process, /workspace/WordBridgeService/wob)
     ──► MariaDB (elsewhere; commented out in wob's compose file)
```

- Traefik is `traefik:v3.0.0` (`/workspace/entry/entry/docker-compose.yml:5`).
  The server is routed from the `websecure` entry point
  (`/workspace/WordBridgeService/wob/docker-compose.yml:16-17`).
- `wordbridge.coseeing.org` resolves to Cloudflare addresses with the proxy
  on. The user confirmed that the host accepts ports 80/443 only from
  Cloudflare.
- The `websecure` entry point has no `forwardedHeaders` setting
  (`/workspace/entry/entry/traefik.yml:13-17`). By Traefik's documented
  default, Traefik then drops incoming `X-Forwarded-*` headers and sets them
  from the directly connected peer. This comes from the documentation and
  source, not from a test on the host, so item 1 has a post-deployment check
  (§5.7).
- The server container is reachable only through the Docker network `entry`
  (`/workspace/WordBridgeService/wob/docker-compose.yml:11-13`, `:31-34`); it
  publishes no port. The database service is commented out
  (`/workspace/WordBridgeService/wob/docker-compose.yml:21-29`).
- Production runs MariaDB 11.3.2
  (`/workspace/WordBridgeService/mysql/mariadb_upgrade_info`, and the dump
  header `/workspace/WordBridgeService/data/wob.sql:5`).
- Usage is small: the `interaction` table file is about 360 KB
  (`/workspace/WordBridgeService/mysql/WordBridge/interaction.ibd`, 360,448
  bytes).
- Deployment copies the repository's `server/` by hand to `wob/server/`;
  `wob/` is not a git repository. The image is built from that copy
  (`/workspace/WordBridgeService/wob/docker-compose.yml:4-6`).

### 1.2 Invariants this work keeps

- `server/app/lib` and `server/app/dictionary` are whole copies of the
  add-on's packages, made by `server/sync_addon_code.py`
  (`server/sync_addon_code.py:1-14`, `:51-59`) and checked by
  `tests/test_server_addon_copy.py:33-45`. **Every change to `lib` is made in
  the add-on's `lib` and then synced**; the server copy is never edited
  alone.
- `server/app/settings.py` rules: every deployment value comes from an
  environment variable with no built-in fallback; a missing or malformed
  value stops startup with one error that lists every problem and never
  repeats a value (`server/app/settings.py:1-16`, `:90-117`).
- Messages shown to users never reveal keys, the AI service's raw error text
  or other internals. `server/tests/test_provider_key_privacy.py` keeps
  passing.
- Every translatable add-on string has a `# Translators:` comment
  (`tests/test_catalog_url_dialog.py:361`), and log messages are not
  translated (`tests/test_catalog_url_dialog.py:397`).

## 2. Decisions

### 2.1 Decided by the user (2026-11-07)

| # | Item | Decision |
| --- | --- | --- |
| 1 | Client IP for guest quotas | **Do**: new `CLIENT_IP_SOURCE` = `cloudflare` / `proxy` |
| 2 | `/feedback` ownership and length | **Not doing**; recorded as a known risk (§6) |
| 3 | Race in the quota check | **Not doing**; recorded as a known risk (§7) |
| 4 | DB connection held during the AI call | **Do** |
| 5 | Indexes for the quota queries | **Do** |
| 6 | API keys checked at startup | **Do** |
| 7 | Two DB session setups | **Do**: tidy only, keep both |
| 8 | Hard-coded `version` / `category` | **Do**: `version` = add-on version, new `template`, drop `category` |
| 9 | alembic offline mode | **Do** |
| 10 | Dependency lists | **Do**: uv, separate production and dev lists, hashes |
| 11 | Error classes and user messages | **Do**: the server returns an error code, the add-on shows a translated message |

Also decided by the user (2026-11-07):

- Item 11: status codes follow their meaning; compatibility with already
  released add-ons is **not** a constraint.
- Item 7: the admin routes `/users` and `/interactions` are in use, so both
  the sync and async session setups stay. The main routes stay synchronous
  (§11.2).
- Item 2: feedback is only recorded and nobody uses it.
- Release version: this ships as add-on version **2026.11.1** (§16).

Items 5 and 8 share **one** alembic migration.

### 2.2 Decided by orchestrator with the recommended default; user may override before merge

- **D1.** Production is MariaDB 11.3.2 (§1.1).
- **D2.** The existing single-column foreign-key index on
  `interaction.user_id` is kept, so MariaDB cannot refuse the migration
  because a foreign key lacks an index (§9).
- **D3.** The migration must run `upgrade` and `downgrade` on a real
  MariaDB; the server tests use SQLite and cannot check it (§19.3).
- **D4.** MariaDB DDL cannot be rolled back, so the deployment steps start
  with a database backup (§18).
- **D5.** The 403 at `server/app/user/linking.py:78` covers three cases
  (UserInfo `sub` mismatch, blank email, `email_verified` not `True`;
  `server/app/user/linking.py:71-77`), not only an unverified email. The
  code is therefore `account_unverified` (not `email_unverified`) and its
  message does not name one cause.
- **D6.** A new code `account_disabled` for the inactive-account 403
  (`server/app/user/auth.py:123-124`), so a disabled user hears a specific
  message instead of the generic failure.
- **D7.** `DiscoveryError` → 503 (`server/app/user/auth.py:101-102`) is also
  `sso_unavailable`.
- **D8.** The Cloudflare range file's name is the implementer's choice, for
  example `server/app/setting/cloudflare_ips.txt` (§5.4).
- **D9.** The add-on version file's name and format are the implementer's
  choice, for example `server/app/setting/addon_version.txt` (§12.2).
- **D10.** `template` stores the template file name without `.json`
  (`Standard_v1`, `Lite_v1`).
- **D11.** `template` is `String(64)`, not null. Whether existing rows get a
  value or the column allows null for them is the implementer's choice.
- **D12.** `version` widens from `String(8)` to `String(32)`.
- **D13.** 401 responses keep their current body with no `code`; the add-on
  keeps its current 401 message.

Rulings on the findings in §20 (also decided by orchestrator with the
recommended default; user may override before merge):

- **D14 (F1).** `handle_errors` parses the "other status" body defensively
  and always raises `LLMServiceError(kind="other")` (§15.4.1). Today that
  path crashes with `ValueError`/`KeyError`, so the local-mode change is a
  bug fix, not a message change.
- **D15 (F2).** The startup key check covers only the ids `resolve_model()`
  could actually serve; an id that cannot resolve is logged as a warning and
  does not stop startup (§10.2).
- **D16 (F3).** The migration is verified on a real MariaDB from a schema
  built with `Base.metadata.create_all` at `918566c`, never from the
  production dump (§19.3).
- **D17 (F6).** zh_TW uses 您, matching the existing translations (§17).
- **D18 (F9).** The key check lives in the correction-settings startup path,
  not in `app/settings.load_settings()` (§10.2).
- **D19 (F10).** The misleading comment at `server/app/main.py:238-239` is
  rewritten as part of item 11's logging change (§15.5).

## 3. What NVDA users hear and see

- **Local mode** (the user's own API key): nothing changes except one bug
  fix. The messages
  raised by `LLMServiceError` stay exactly as they are
  (`addon/globalPlugins/WordBridge/lib/llm/provider.py:60-92`, `:112-118`,
  `:150-157`; `addon/globalPlugins/WordBridge/lib/llm/executor.py:68-76`).
  One bug fix (D14, §15.4.1): an error status whose body is not JSON or
  lacks `error.message` no longer crashes; the user hears the usual "An
  error occurred, status code = …" message with the status and its reason.
- **Coseeing mode:** instead of "The Coseeing request failed. Please try
  again later." (`addon/globalPlugins/WordBridge/__init__.py:734-736`) for
  every error other than 401 and 429, the user hears a specific message for
  each server `code` (§15). In particular, a guest whose text is longer than
  `GUEST_TEXT_LIMIT` now hears that the text is too long, with the limit,
  instead of today's misleading "Rate limit reached ... check your account
  balance" (`addon/globalPlugins/WordBridge/__init__.py:724-733`, triggered
  by the guest-text 429 at `server/app/main.py:150-151`).
- Guests behind different Cloudflare edges no longer share one per-IP quota
  (item 1), so a guest is less likely to hear the quota message early.
- No settings panel or dialog changes.

## 4. Item summary of affected code

| Item | Server | Add-on |
| --- | --- | --- |
| 1 | `main.py` (`get_client_ip`), `settings.py`, new range file and update script, `.env.example` | — |
| 4 | `main.py` (`proofreader`) | — |
| 5, 8 | `models/models.py`, `models/schemas.py`, `main.py`, new migration, `sync_addon_code.py`, new version file | `buildVars.py` (version bump) |
| 6 | startup key check, `main.py`, `.env.example` | — |
| 7 | `dependencies.py`, `dependenciesA.py` (removed), `main.py` | — |
| 9 | `alembic/env.py`, `alembic.ini` | — |
| 10 | `requirements*.in/.txt`, `Dockerfile` | — |
| 11 | `main.py`, `user/auth.py`, `user/linking.py`, error handler | `lib/llm/errors.py`, `provider.py`, `executor.py` (synced), `__init__.py`, three `.po` files |

## 5. Item 1: guest quotas use the real client IP

### 5.1 Why

Each guest IP gets `GUEST_IP_QUOTA` (`server/app/settings.py:43`,
`server/app/main.py:163-165`), meant as one share per person.
`get_client_ip()` takes the **first** `X-Forwarded-For` value
(`server/app/main.py:109-115`). Behind Cloudflare and Traefik that value is
a Cloudflare edge address, so unrelated guests share one quota and the
effective limit is close to the all-guests `GUEST_GLOBAL_QUOTA`
(`server/app/main.py:164-165`). The comment at `server/app/main.py:77-84`
records that the trust model was kept as-is for the previous phase; this
item replaces it, and that comment is updated.

### 5.2 Behaviour

New required environment variable `CLIENT_IP_SOURCE`, value `cloudflare` or
`proxy`; anything else (or missing) stops startup under the settings rules
(§1.2).

**Peer IP:** the **last** `X-Forwarded-For` value, i.e. the one Traefik
added. Without the header, `request.client.host`.

- **`proxy`** (Cloudflare DNS only, no proxying): client IP = peer IP.
- **`cloudflare`** (Cloudflare proxying; production's current setup):
  - If the peer IP is inside a Cloudflare range **and** `CF-Connecting-IP`
    is present and a valid IP address, client IP = `CF-Connecting-IP`.
  - Otherwise (peer not from Cloudflare, header missing or malformed),
    client IP = peer IP.
- The result still goes through `_storable_ip()`
  (`server/app/main.py:118-127`) so it fits `String(45)`
  (`server/app/models/models.py:22`).
- The first `X-Forwarded-For` value is no longer used anywhere.

### 5.3 Why the last value

Whatever a client sends in `X-Forwarded-For` ends up on the left; the last
value is written by the proxy nearest the server (Traefik) from the TCP
peer and cannot be forged. It stays correct even if Traefik is later set to
trust incoming headers (`forwardedHeaders.insecure`).

Assumption: there is exactly one proxy (Traefik) between the server and the
outside. This is written in a code comment and in `server/.env.example`. If
another proxy is ever added behind Traefik, the code must take the N-th
value from the right.

### 5.4 Cloudflare ranges

- Kept in a bundled file, one CIDR per line, IPv4 and IPv6 (name: D8).
- A separate update script fetches `https://www.cloudflare.com/ips-v4` and
  `https://www.cloudflare.com/ips-v6` and overwrites the file. It is run by
  hand during development; the server never contacts Cloudflare at run
  time.
- If the file goes stale, requests from a new range fall back to the peer IP
  (a Cloudflare edge), which makes quotas **stricter, not bypassable**. That
  is why a bundled file was chosen.
- The file is read and parsed at startup; a missing file or an invalid line
  stops startup.
- The server image includes it: the Dockerfile copies all of `app`
  (`server/Dockerfile:14`).

### 5.5 Misconfiguration (design goal)

| `.env` | Reality | Result |
| --- | --- | --- |
| `proxy` | Cloudflare proxy on | Edge IPs; guests share quotas; too strict but not bypassable |
| `cloudflare` | Cloudflare proxy off | Peer is outside the ranges, falls back to peer IP: correct; a forged `CF-Connecting-IP` is ignored |

### 5.6 Tests

See §19.1, item 1.

### 5.7 Check after deployment

Confirm once in production that the server sees users' real IPs (for
example, log it temporarily, or send one guest request from a known IP).

Reason: Traefik runs in a container. If some connections (for example IPv6
arriving where the Docker network is IPv4 only) are forwarded by Docker's
userland proxy, Traefik sees the Docker gateway address, the range check in
`cloudflare` mode always fails, and all guests fall back to one shared IP.
Only production can show this.

### 5.8 Not doing

- **IPv6 address rotation:** an IPv6 user can change address to get a new
  quota; counting per /64 needs schema and query changes. Usage is small and
  the global limit still caps the total loss.
- **Traefik's own problems:** shared infrastructure; recorded in Appendix A
  only.

## 6. Item 2: `/feedback` (not doing)

The user said feedback is only recorded and unused. Known risks that stay:

- Anyone can overwrite any interaction's `review_content`: there is no owner
  check (`server/app/main.py:296-302`) and ids are sequential.
- `review_content` has no length limit (`server/app/main.py:285-287`);
  content larger than a MySQL `TEXT` column fails the write with a 500
  (`server/app/models/models.py:30`, `server/app/main.py:304`).

## 7. Item 3: race in the quota check (not doing)

`/proofreader` checks the quota (`server/app/main.py:190`), waits for the AI
answer (`:220-236`) and only then writes the cost (`:264-267`). Concurrent
requests can all pass the check, so spending can exceed the quota by up to
the number of concurrent requests. With one process and small usage this
risk is accepted. If it is ever addressed, a process-local lock or an
up-front reservation is enough because there is one process.

## 8. Item 4: no database connection held during the AI call

### 8.1 Why

The transaction that the quota check starts in `/proofreader` ends only at
`db.commit()` (`server/app/main.py:266`), so one connection is held for the
seconds to tens of seconds the AI takes. The sync engine uses SQLAlchemy's
default pool (`server/app/database.py:37`; documented default 5 + 10
overflow = 15 connections). With a dozen slow requests in flight, even
requests that need no AI cannot get a connection.

### 8.2 Behaviour

- After the quota check and before the AI call, end the transaction and
  return the connection to the pool; take a connection again after the AI
  answers to write the record.
- Observable behaviour is unchanged: response body, status codes (except
  item 11's changes) and written columns stay the same.
- `get_optional_user` (`server/app/user/auth.py:106-125`, its `db` at `:109`)
  and `/proofreader` (`server/app/main.py:184-185`) share one `get_db`
  session through FastAPI's per-request dependency cache, and `user` belongs
  to that session. The session factory uses the default
  `expire_on_commit=True` (`server/app/dependencies.py:5`). After the
  transaction ends, the written `interaction` must still be linked to that
  user (mind attribute expiry and reload); how is the implementer's choice.

### 8.3 Test

With a fake provider, assert at the moment of the AI call that the request
holds no database connection (for example, the pool's checked-out count is
0).

## 9. Item 5: indexes for the quota queries

`_sum_cost()` (`server/app/main.py:130-146`) runs three queries:

| Query | Condition | Index |
| --- | --- | --- |
| Signed-in user (`main.py:158`) | `user_id = ? AND request_time > ?` | `(user_id, request_time)` |
| All guests (`main.py:164`) | `user_id IS NULL AND request_time > ?` | `(user_id, request_time)` |
| One guest IP (`main.py:163`) | `user_id IS NULL AND ip_address = ? AND request_time > ?` | `(ip_address, request_time)` |

- Add the two composite indexes on `interaction`.
- Declare them both in the migration and in `__table_args__` of
  `server/app/models/models.py` (the class at `:15-31` has none today), so
  autogenerate shows no difference.
- `user_id` is a foreign key (`server/app/models/models.py:27`); production
  already has its single-column index `KEY user_id`
  (`/workspace/WordBridgeService/data/wob.sql:65`). It is kept (D2).

## 10. Item 6: API keys checked at startup

### 10.1 Why

The key is read per request with
`os.environ.get(f"{PROVIDER}_API_KEY")` (`server/app/main.py:207`), and a
missing key returns 500 (`:208-213`). A deployment that forgets or misspells
a variable starts normally and fails only when a user corrects text.

### 10.2 Behaviour

- The server serves only `DEFAULT_CORRECTOR_CONFIG_ID` and the models in
  `COSEEING_MODEL_IDS` (`server/app/correction_config.py:65-80`).
- At startup, compute the set of providers those models use. For each,
  `<PROVIDER>_API_KEY` must be set and not blank, or startup stops.
  - One error lists every missing variable name and no value, like
    `SettingsError` (`server/app/settings.py:52-53`, `:115-116`).
  - Providers no served model uses are not checked.
- **Which ids count (D15).** Only the ids `resolve_model()` could actually
  serve: `"default"` (already validated at startup,
  `server/app/correction_config.py:49-54`), plus the `COSEEING_MODEL_IDS`
  entries that resolve to an active catalog model with a bundled provider
  (the test at `server/app/correction_config.py:77-79`). An id that cannot
  resolve is logged as a warning at startup and does **not** stop startup,
  so a catalog update that deactivates a model never takes the server down.
  Such an id keeps being rejected per request as today.
- **Where the check lives (D18).** In the correction-settings startup path
  (`load_correction_settings()`, `server/app/correction_config.py:31-62`, or
  an equivalent step run by `app.main` at import, `server/app/main.py:36`),
  **not** in `app/settings.load_settings()`: alembic imports `app.settings`
  (`server/alembic/env.py:24`) and must not need API keys.
- Keys are read once at startup; requests no longer read the environment.
- The "no key → 500" branch in `/proofreader`
  (`server/app/main.py:207-213`) is removed; it can no longer happen.
- `server/.env.example`: replace "Not checked at startup ..."
  (`server/.env.example:48-49`) with a note that the key of every provider a
  served model uses is required.
- Production's `.env` sets all five keys (`server/.env.example:50-54` lists
  them), so this does not stop the current deployment.

### 10.3 Not doing

Startup only checks that keys are set; it does not call the AI services to
validate them. An invalid key surfaces as item 11's
`provider_configuration`.

## 11. Item 7: tidy the two database session setups

### 11.1 Changes

The admin routes `/users` and `/interactions` (fastcrud, superuser only;
`server/app/main.py:308-338`) are in use, so both the sync and async setups
stay.

- Merge `server/app/dependenciesA.py` into `server/app/dependencies.py`.
  - Rename the async dependency `get_session`
    (`server/app/dependenciesA.py:13-15`) to `get_async_session`.
  - Add a comment explaining why there are two: fastcrud supports only async
    sessions; the other routes are sync.
- Delete the unused `Session = sessionmaker(bind=engine)`
  (`server/app/dependenciesA.py:8`), which wrongly binds a sync
  sessionmaker to the async engine (`:6`).
- Update the imports in `server/app/main.py:17` (used at `:310`, `:326`) and
  `server/tests/test_route_permissions.py:13` (used at `:62`, `:261`).
- The admin routes' URLs, permissions and behaviour do not change; neither
  do the two engines in `server/app/database.py:36-40`.

### 11.2 Sync or async (conclusion of the discussion; no code change)

The main routes stay synchronous:

- The `lib` that calls the AI is a copy of the add-on code and must stay
  synchronous (NVDA uses `requests`; e.g.
  `addon/globalPlugins/WordBridge/lib/llm/provider.py:131`).
- FastAPI runs sync routes in a thread pool of about 40 threads (anyio's
  default), far above current usage.
- Async SQLAlchemy cannot lazy-load relationships, which is easier to get
  wrong.

## 12. Item 8: `version`, `template`, and dropping `category`

### 12.1 Why

`version` is meant to record which prompt version produced a result, for
comparisons when tuning prompts. It is hard-coded to `"20260425"`
(`server/app/main.py:259`) and never changed with the prompts.
`category = "1"` (`server/app/main.py:262`) was meant to encode the
template but has always been `1`.

### 12.2 `version` is the add-on version

- The value is the add-on version the server code and prompts correspond to:
  `addon_version` in `buildVars.py` (`buildVars.py:25`), e.g. `2026.11.1`.
  Server and client then share one version identity.
- `server/sync_addon_code.py` reads the version from `buildVars.py` and
  writes it to a server-side file (name and format: D9); the server reads it
  at startup, because the image has no `buildVars.py` (`server/Dockerfile:14-16`
  copies only `app`, `alembic` and `alembic.ini`).
  - A missing or blank file stops startup.
- The drift test checks that the file's content equals `buildVars.py`'s
  `addon_version`.

### 12.3 Prompt files join the sync

- `server/sync_addon_code.py` also copies the add-on's `setting/templates/`
  and `setting/task/`. Today they are identical on both sides (checked with
  `diff -r`), but nothing enforces it; today's sync covers only `lib` and
  `dictionary` (`server/sync_addon_code.py:26`).
- `tests/test_server_addon_copy.py` checks these two directories too (today
  its file sets come from `PACKAGES` only, `tests/test_server_addon_copy.py:20-30`).
- `setting/catalog.json` is **not** synced: the server's copy deliberately
  differs from the add-on's.

### 12.4 New column `template`

- Records the template actually used:
  `template_name[typo_correction_mode]` from `setting/task/corrector.json`
  (`server/app/setting/task/corrector.json:2-5`; read at
  `server/app/main.py:216`).
- Stored without `.json`, e.g. `Standard_v1`, `Lite_v1` (D10).
- `String(64)`, not null (D11).

### 12.5 Drop `category`

- The migration drops `interaction.category`. Every stored value is the
  hard-coded `"1"`, so nothing is lost.
- `downgrade` adds the column back, empty.
- Remove `category` from `server/app/models/models.py:26`,
  `server/app/models/schemas.py:16`, `server/app/main.py:262` and the tests
  (`server/tests/test_proofreader_api.py:73`,
  `server/tests/test_route_permissions.py:79`).

### 12.6 `version` length

`String(8)` (`server/app/models/models.py:25`; production `varchar(8) NOT NULL`,
`/workspace/WordBridgeService/data/wob.sql:58`) cannot hold `2026.11.1`. It
becomes `String(32)` (D12).

### 12.7 Admin routes

`Interaction` in `server/app/models/schemas.py:6-23` gains `template` and
loses `category`; superusers see the new column through `/interactions`.

### 12.8 Known limit

If a prompt changes without an add-on version bump, two different prompts
are recorded under one `version`. `template` covers part of that.

### 12.9 Migration

One migration together with item 5:

- add the two indexes;
- widen `version`;
- add `template`;
- drop `category`.

Its `down_revision` is `20260923_sso_user`
(`server/alembic/versions/20260923_sso_user.py:16`), which is production's
current head (`/workspace/WordBridgeService/data/wob.sql:38`).

D1–D4 (§2.2) apply: MariaDB 11.3.2, the `user_id` index is kept, upgrade
and downgrade must run on a real MariaDB (§19.3), and deployment backs up
the database first (§18).

## 13. Item 9: alembic offline mode

- `run_migrations_offline()` reads `sqlalchemy.url`
  (`server/alembic/env.py:46`), which is `placeholder`
  (`server/alembic.ini:66`), so `alembic upgrade head --sql` fails.
- Use the same URL as online mode, `SETTINGS.database_url("mysql+pymysql")`
  (already computed at `server/alembic/env.py:24-26`). Offline mode only uses
  it to pick the dialect; it does not connect.
- Keep `placeholder` in `alembic.ini` and add a comment that the real
  connection settings come from the environment.
- Check: `alembic upgrade head --sql` prints the SQL of the item 5/8
  migration. That SQL can be reviewed before deployment.

## 14. Item 10: dependency lists with uv

### 14.1 Today

`server/requirements.txt` is an incomplete `pip freeze`:

- **Extra:** test-only `aiosqlite`, `httpx` (`server/requirements.txt:3`,
  `:24`); dev-only `fastapi-cli`, `typer`, `rich`, `watchfiles` (`:17`,
  `:49`, `:43`, `:54`); never imported by the server: `SQLAlchemy-Utils`,
  `ujson`, `orjson`, `email_validator`, `python-multipart`, `PyYAML`
  (`:47`, `:51`, `:31`, `:15`, `:40`, `:41`), among others. (No `import` of
  these modules exists under `server/app`, `server/tests` or
  `server/alembic`.)
- **Missing:** `pytest` is in no server list (it is only in the add-on's
  `tests/requirement.txt:1`); `Mako` (needed by alembic) and
  `typing-inspection` (needed by pydantic) are not pinned.

### 14.2 Behaviour

- Direct dependencies live in two hand-written lists:
  - `server/requirements.in`: production.
  - `server/requirements-dev.in`: includes the production list, plus
    `pytest`, `httpx`, `aiosqlite` and other test and dev packages.
- `uv pip compile` produces `server/requirements.txt` and
  `server/requirements-dev.txt`:
  - `--python-version 3.14`, matching the image (`server/Dockerfile:1`);
  - `--generate-hashes`;
  - dev versions must match production, e.g. by compiling with
    `--constraint requirements.txt` (method: implementer's choice).
- The compile commands are written as comments at the top of each `.in`
  file.
- Production direct dependencies are the packages the code actually
  imports, plus `uvicorn`, `alembic`, `PyMySQL`, `aiomysql` needed to run.
  - Keep `Authlib`, `PyJWT`, `requests` that `app/package/coseeing_auth`
    needs: coseeing_auth is a library shared with other projects, and its
    dependencies are not removed.
  - Whether to keep `uvicorn[standard]`'s extras (`httptools`, `uvloop`, …)
    is the implementer's choice, as long as the server starts.
- Check: in a **clean** environment, installing only
  `requirements-dev.txt` runs the full server test suite; installing only
  `requirements.txt`, `python -c "import app.main"` succeeds (with the full
  set of environment variables).

### 14.3 Dockerfile

- Install with uv, mounted so uv does not stay in the image (today:
  `server/Dockerfile:8-9`):

  ```dockerfile
  RUN --mount=from=ghcr.io/astral-sh/uv:<pinned version>,source=/uv,target=/bin/uv \
      uv pip sync --system requirements.txt
  ```

- uv is pinned to an exact version.
- Hashes are verified at install; `uv pip sync` verifies a hashed list
  automatically — the implementer confirms whether an explicit flag is
  needed.
- Before deploying: production Docker must support BuildKit, which
  `--mount=from=` needs. Recent Docker enables it by default.

## 15. Item 11: error classes and user messages

### 15.1 Why

- The add-on's Coseeing mode handles only 401 and 429 specially; every other
  error is "The Coseeing request failed"
  (`addon/globalPlugins/WordBridge/__init__.py:717-736`). The user cannot
  tell text-too-long from model-unavailable from an overloaded AI service.
- **Misleading today:** a guest text over `GUEST_TEXT_LIMIT` gets 429
  (`server/app/main.py:150-151`, using `_QUOTA_EXCEEDED_DETAIL` at `:88-91`)
  and the add-on says the rate limit or quota was reached and to check the
  account balance (`addon/globalPlugins/WordBridge/__init__.py:724-733`),
  when the text is merely too long.
- Every failure in the AI call is 502 (`server/app/main.py:237-244`), since
  the handler catches `Exception`; the log cannot tell an AI service problem
  from a server bug.

### 15.2 Error body (server)

Every error the server raises itself returns:

```json
{"detail": "English description", "code": "guest_text_too_long", "limit": 128}
```

- `detail`: English, for API users and developers.
- `code`: a fixed error code for the add-on.
- `limit`: only on length errors; the limit that applied.

FastAPI's default body is `{"detail": ...}`; a custom exception handler or
exception class is the implementer's choice.

### 15.3 Status codes and codes

Status codes follow their meaning; released add-ons are not a constraint
(user, §2.1).

| Case | Status | `code` | Notes |
| --- | --- | --- | --- |
| Guest text over `GUEST_TEXT_LIMIT` | 413 (was 429, `main.py:150-151`) | `guest_text_too_long` | with `limit` |
| Text over 8000 characters | 413 (was pydantic's 422, `main.py:75`, `:95`) | `text_too_long` | with `limit` |
| Guest quota used up (one IP or all guests) | 429 (`main.py:165-166`) | `guest_quota_exceeded` | |
| Signed-in user's quota used up | 429 (`main.py:159-160`) | `user_quota_exceeded` | |
| Model unavailable | 422 (was 404, `main.py:194-205`) | `model_unavailable` | |
| AI service overloaded | 502 | `provider_overloaded` | from `kind`, §15.4 |
| AI service rate limit or quota | 502 | `provider_rate_limited` | |
| AI service unreachable or timed out | 502 | `provider_unreachable` | |
| AI service configuration (invalid key, region, unknown model) | 502 | `provider_configuration` | |
| Other AI service error | 502 | `provider_error` | |
| Server bug, failed record write | 500 | `service_error` | bugs were 502 (`main.py:237-244`); write failure `main.py:268-274` |
| Sign-in service unreachable or unparseable | 503 | `sso_unavailable` | `user/linking.py:44`, `:47`, `:52`, `:55`; `user/auth.py:101-102` (D7) |
| Account cannot be confirmed (email unverified, UserInfo `sub` mismatch, blank email) | 403 | `account_unverified` | `user/linking.py:71-78`; one code for all three, message names no single cause (D5) |
| Account disabled | 403 | `account_disabled` | `user/auth.py:123-124` (D6) |
| Account conflict | 409 | `account_conflict` | `user/linking.py:125`, `:180`, `:204` |

- 401 (authentication) keeps its current body without `code`; the add-on
  keeps its current message (D13). 401s come from
  `server/app/user/auth.py:59`, `:98`, `:100`, `:131`.
- Other malformed requests (bad `language`, empty `request`, …) keep
  FastAPI's default 422 without `code` (e.g. `server/app/main.py:95-106`).
- `/feedback` errors are out of scope (item 2), but `/feedback` uses the
  same SSO dependency (`server/app/main.py:293`), so `sso_unavailable` and
  the account codes reach it too.

### 15.4 `LLMServiceError.kind` (add-on `lib`, then synced)

`LLMServiceError` (`addon/globalPlugins/WordBridge/lib/llm/errors.py:1-6`)
gains a `kind` attribute. `provider.py` and `executor.py` set it when
raising:

| `kind` | Source |
| --- | --- |
| `overloaded` | HTTP 503 (`provider.py:84-86`), **and Anthropic's 529**: `handle_errors` has no 529 case today, so it falls to the generic branch (`provider.py:87-92`) |
| `rate_limited` | HTTP 429 (`provider.py:75-83`) |
| `unreachable` | `send()` gets no response after its retries (`provider.py:150-157`); `try_connection()` fails (`provider.py:112-118`; called through `executor.py:37-38` from `lib/tasks/typo/workflow.py:23`) |
| `configuration` | HTTP 401, 403, 404 (`provider.py:62-74`) |
| `other` | Any other HTTP error (`provider.py:87-92`), including bodies that are not JSON or lack `error.message` (§15.4.1); unexpected response shape in `executor.py:66-76` |

- **Local-mode messages do not change**, except the bug fix in §15.4.1. The
  add-on already writes the full message to the NVDA log; that stays.
- After the change, run `python3 server/sync_addon_code.py`.
- The server maps `kind` to the `provider_*` codes in §15.3.
- Paths in this table are under `addon/globalPlugins/WordBridge/lib/llm/`.

#### 15.4.1 Defensive parsing of "other status" bodies (D14)

Today the generic branch reads `json.loads(response.text)["error"]["message"]`
unguarded (`addon/globalPlugins/WordBridge/lib/llm/provider.py:87`), so a
non-JSON body (e.g. an HTML 502 page) or a body without `error.message`
crashes with `ValueError`/`KeyError`/`TypeError` instead of raising
`LLMServiceError`.

- Parse the body defensively. When it is JSON with `error.message`, the
  message stays exactly as today:
  `_("An error occurred, status code = ") + f"{status}, {message}"`
  (`provider.py:88-92`).
- Otherwise still raise `LLMServiceError(kind="other")` with the same msgid
  followed by `f"{status}, {reason}"`, where `reason` is `response.reason`
  when present and otherwise empty.
- The raw body is never included.
- No new translatable string.
- This is a bug fix in local mode (a crash becomes the usual error message)
  and makes these cases `provider_error` (502) on the server instead of
  `service_error` (500).
- Test: non-JSON body, JSON without `error`, JSON with `error` but no
  `message`, each with and without `reason`; all raise `LLMServiceError`
  with `kind == "other"`, the expected text, and no part of the body.

### 15.5 Server log

- AI service failures: log the provider name, `kind` and the AI service's
  raw error text, never the key.
- Server bugs: `logger.exception` with the full traceback.
- The comment at `server/app/main.py:238-239` ("Never surface exception
  details ... to the client or the log"), which `logger.exception` at `:240`
  already contradicts, is rewritten with this change to state the rule
  above: details go to the log, never the key, and never to the client
  (D19).
- Responses to users **never** contain the AI service's raw text, because:
  - it is written for local-mode users (e.g. "check your key") and misleads
    in Coseeing mode;
  - it may contain organisation IDs or partially masked keys;
  - the server has no translations.

### 15.6 Add-on (Coseeing mode)

Change the `/proofreader` response handling in
`addon/globalPlugins/WordBridge/__init__.py:717-736`:

- When the error body has a `code`, speak the translated message for that
  code. `guest_text_too_long` and `text_too_long` insert `limit`.
- Without a `code`, or with a code the add-on does not know, fall back to
  today's status-based behaviour:
  - 401: the authentication message (`__init__.py:717-723`);
  - 429: the quota message (`__init__.py:724-733`);
  - other ≥ 400: "The Coseeing request failed" (`__init__.py:734-736`).
- Log the error `code` and status code to the NVDA log, in English, not
  translated.
- Every new string has a `# Translators:` comment and translations in
  zh_TW, zh_CN and zh_HK (`addon/locale/{zh_TW,zh_CN,zh_HK}/LC_MESSAGES/nvda.po`).
  Terminology follows the existing translations: zh_TW 附加元件, zh_CN
  插件, zh_HK 附加組件 (e.g. `addon/locale/zh_TW/LC_MESSAGES/nvda.po:397`,
  `addon/locale/zh_CN/LC_MESSAGES/nvda.po:436`,
  `addon/locale/zh_HK/LC_MESSAGES/nvda.po:436`).
- Regenerate the `.pot` (`scons pot`, `sconstruct:137-138`) and merge the
  three `.po` files. This needs gettext, which is not installed in the
  current container (`msgfmt` is not on `PATH`) and must be reinstalled.

## 16. Release version

**Decided by the user (2026-11-07):** this work ships as add-on version
**2026.11.1**, not yet released.

- Committed `buildVars.py` says `addon_version="2026.9.3"`
  (`buildVars.py:25`); the latest git tag is `2026.9.2`.
- The task branch commits the bump of `buildVars.py:25` from `"2026.9.3"`
  to `"2026.11.1"` itself, and the server version file (§12.2) holds
  `2026.11.1`.
- The user's identical uncommitted change in the main checkout is left
  alone; it can be discarded later.

## 17. Strings

English is the msgid; zh_TW is the suggested translation (draft for the
user's review). zh_CN and zh_HK translations are added with the same
meaning and the terminology in §15.6.

| `code` | English (msgid) | zh_TW |
| --- | --- | --- |
| `guest_text_too_long` | Guests can correct up to {limit} characters at a time. Sign in to Coseeing to correct longer text. | 訪客每次最多可校對 {limit} 字，登入 Coseeing 即可校對更長的文字。 |
| `text_too_long` | The text is too long. Up to {limit} characters can be corrected at a time. | 文字過長，每次最多可校對 {limit} 字。 |
| `guest_quota_exceeded` | Today's guest quota has been used up. Please try again later or sign in to Coseeing. | 今日訪客額度已用完，請稍後再試或登入 Coseeing。 |
| `user_quota_exceeded` | Your Coseeing account's quota has been used up. | 您的 Coseeing 帳號額度已用完。 |
| `model_unavailable` | The selected model is currently unavailable. Please choose another model in the settings. | 所選的模型目前無法使用，請在設定中改選其他模型。 |
| `provider_overloaded` | The AI service is currently overloaded. Please try again later. | AI 服務目前過載，請稍後再試。 |
| `provider_rate_limited` | Coseeing's AI service has reached its usage limit for now. Please try again later or choose another model. | Coseeing 的 AI 服務暫時達到用量上限，請稍後再試或改選其他模型。 |
| `provider_unreachable` | The AI service could not be reached. Please try again later. | 暫時無法連線到 AI 服務，請稍後再試。 |
| `provider_configuration` | Coseeing's AI service is misconfigured. Please choose another model or try again later. | Coseeing 的 AI 服務設定有問題，請改選其他模型或稍後再試。 |
| `provider_error` | The AI service returned an error. Please try again later. | AI 服務發生錯誤，請稍後再試。 |
| `service_error` | The Coseeing service encountered a problem. Please try again later. | Coseeing 服務發生問題，請稍後再試。 |
| `sso_unavailable` | The Coseeing sign-in service is currently unavailable. Please try again later. | 目前無法連線到 Coseeing 登入服務，請稍後再試。 |
| `account_unverified` | Your Coseeing account could not be verified. Please make sure its email address is verified, then sign in again. | 無法確認您的 Coseeing 帳號，請確認電子郵件已驗證後重新登入。 |
| `account_disabled` | Your Coseeing account has been disabled. Please contact Coseeing. | 您的 Coseeing 帳號已停用，請聯絡 Coseeing。 |
| `account_conflict` | There is a conflict with your Coseeing account. Please contact Coseeing. | Coseeing 帳號發生衝突，請聯絡 Coseeing。 |

zh_TW uses 您 throughout, matching the existing translations (D17, F6).

## 18. Deployment steps (first deployment of this work)

1. Add `CLIENT_IP_SOURCE=cloudflare` to `wob/.env`.
2. Confirm `wob/.env` has the key of every provider a served model uses
   (all five are set today).
3. Confirm production Docker supports BuildKit.
4. Copy the repository's `server/` to `wob/server/` and rebuild the image.
5. Back up the `WordBridge` database with `mysqldump` (D4).
6. Review the migration SQL with `alembic upgrade head --sql`, then run
   `alembic upgrade head`. The Dockerfile does not run migrations
   (`server/Dockerfile:21` starts uvicorn only).
7. Check the client IP as in §5.7.

Order of add-on release and server deployment:

- New add-on, old server: no `code`, so it falls back to today's messages.
- Old add-on, new server: a guest's too-long text now gets "The Coseeing
  request failed" (413 hits the generic branch at
  `addon/globalPlugins/WordBridge/__init__.py:734-736`).

Both combinations work, so the order is free.

## 19. Test plan

Commands: add-on tests `python3 -m pytest -q tests` from the repository root
(`pyproject.toml:191-192`); server tests `python3 -m pytest -q tests` from
`server/`; `prek run --all-files`; `git diff --check`; `msgfmt --check` on
the three `.po` files. Record passed/skipped counts against the baseline.

### 19.1 Unit tests (no NVDA, no network)

- **Item 1:** both modes in the normal case; in `cloudflare` mode, a forged
  `CF-Connecting-IP` from a non-Cloudflare peer is ignored; with several
  `X-Forwarded-For` values the last is used; fallbacks when headers are
  missing or malformed; IPv4 and IPv6; a missing or invalid
  `CLIENT_IP_SOURCE` stops startup; a missing or invalid range file stops
  startup. Existing tests that rely on the first value
  (`server/tests/test_proofreader_api.py:262-303`) are updated.
- **Item 4:** at the moment of the (fake) AI call, the pool's checked-out
  count is 0; the written interaction is linked to the signed-in user.
- **Item 5:** the model declares both indexes; a test (or autogenerate
  check) shows no difference between models and migrations.
- **Item 6:** a served model's provider without a key stops startup and the
  error names every missing variable and no value; an unused provider's key
  is not required; a `COSEEING_MODEL_IDS` id that cannot resolve logs a
  warning, does not stop startup and does not require its provider's key;
  importing `app.settings` (as alembic does) does not need any API key; the
  request path no longer reads the environment. The test at
  `server/tests/test_proofreader_api.py:213` is replaced.
- **Item 7:** imports updated; `server/tests/test_route_permissions.py`
  passes with `get_async_session`.
- **Item 8:** the stored `version` equals the version file; `template` is
  the template stem for each mode; `category` is gone from model, schema and
  `/interactions`; a missing or blank version file stops startup; the drift
  test checks the version file against `buildVars.py` and covers
  `setting/templates/` and `setting/task/`.
- **Item 9:** `alembic upgrade head --sql` produces SQL containing the new
  migration (needs the full set of settings variables, since
  `server/alembic/env.py:24` imports `app.settings`).
- **Item 10:** clean-environment checks in §14.2.
- **Item 11 (server):** one test per row of §15.3 (status, `code`, `limit`
  where present); 401 bodies unchanged; each `kind` maps to its
  `provider_*` code; a non-`LLMServiceError` exception is 500
  `service_error`; responses never contain the provider's raw text; logs
  never contain the key. Tests that assert the old codes change
  (`server/tests/test_proofreader_api.py:190-206`, `:309-316`, `:353-396`).
  `server/tests/test_provider_key_privacy.py` still passes.
- **Item 11 (add-on `lib`):** `kind` for 401/403/404, 429, 503, 529, other
  statuses, `send()` without response, `try_connection()` failure and
  parse failure; messages unchanged (extend `tests/test_llm_errors.py:35-52`,
  `:56`, `:66`, `:101`); the defensive-parsing cases of §15.4.1.
- **Item 11 (add-on UI, NVDA-stubbed):** each `code` gives its message;
  `limit` is inserted; unknown or missing `code` falls back to today's
  messages by status; `code` and status are logged untranslated; every new
  string has a Translators comment and zh_TW/zh_CN/zh_HK translations
  (`tests/test_catalog_url_dialog.py:361`, `:397`). Existing tests in
  `tests/test_coseeing_requests.py:317-373` keep passing or are extended.

### 19.2 Mutation checks

On the IP selection (item 1) and the `kind` → `code` mapping (item 11),
mutate a scratch copy (e.g. take the first `X-Forwarded-For` value, skip
the range check, swap two `kind`s) and confirm the tests catch each mutant.

### 19.3 MariaDB migration check (D3)

- Install MariaDB in the container (e.g. with apt). Record the MariaDB
  version actually used in the handoff (production is 11.3.2).
- alembic cannot build the schema from an empty database (F3), and the
  production dump contains user data, so it is **not** used (D16). Instead:
  1. Build the pre-migration schema with `Base.metadata.create_all` from the
     models at the base commit `918566c`, e.g. from a scratch
     `git worktree add --detach <scratch path> 918566c`.
  2. `alembic stamp 20260923_sso_user`.
  3. `alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head`.
- After `upgrade`: both indexes exist, `KEY user_id` is still there,
  `version` is `varchar(32)`, `template` exists, `category` is gone. After
  `downgrade`: the schema is back to the starting one (with `category`
  empty).
- If MariaDB cannot be installed: at least generate the SQL with
  `alembic upgrade head --sql`, review it by hand, and state in the report
  that it was not run.

### 19.4 Windows/NVDA manual checks (cannot be done here)

Linux tests cannot run NVDA. A human on Windows, with this add-on build
against a server that has this work, checks in Coseeing mode:

1. As a guest, correct text longer than `GUEST_TEXT_LIMIT`: NVDA speaks the
   `guest_text_too_long` message with the number, not the quota message.
2. Text longer than 8000 characters: the `text_too_long` message with 8000.
3. Guest and signed-in quota used up: the two quota messages.
4. A model not served: the `model_unavailable` message.
5. If it can be arranged (e.g. a test server with a wrong key or a
   blocked provider): `provider_configuration` and `provider_unreachable`.
6. All of the above in zh_TW, zh_CN and zh_HK NVDA languages: the
   translated text is spoken, `{limit}` is filled in, no msgid shows.
7. Against the old server: messages fall back to today's.
8. Local mode with the user's own key: messages unchanged.

## 20. Findings while writing the spec

These were found while verifying references. F1, F2, F3, F6, F9 and F10
are closed by the orchestrator's rulings D14–D19 (§2.2; decided by
orchestrator with the recommended default; user may override before merge).
The others are notes for the implementer.

- **F1. `handle_errors` can raise something other than `LLMServiceError`.**
  The generic branch parses the body unguarded:
  `json.loads(response.text)["error"]["message"]`
  (`addon/globalPlugins/WordBridge/lib/llm/provider.py:87`). A non-JSON body
  (e.g. an HTML 502 page) or a different shape raises `ValueError`,
  `KeyError` or `TypeError`, not `LLMServiceError`, so these cases would be
  `service_error` (500) on the server. **Closed by D14:** the body is parsed
  defensively and always raises `LLMServiceError(kind="other")` with the
  existing msgid; the local-mode change is a bug fix (§15.4.1).
- **F2. Which models count for the startup key check.** `COSEEING_MODEL_IDS`
  is not validated at startup; an id that is not an active catalog model is
  rejected only per request (`server/app/correction_config.py:75-79`).
  **Closed by D15:** only ids `resolve_model()` could serve count; an id
  that cannot resolve is a startup warning, not a startup failure (§10.2).
- **F3. alembic cannot build the schema from empty.** The first revision,
  `dad5039f4770`, has `down_revision = None` and only alters
  `interaction.cost` (`server/alembic/versions/dad5039f4770_change_cost_from_float_to_numeric_15_12.py:15-30`);
  `wob/mariadb/init.sql` creates no tables. The production dump
  (`/workspace/WordBridgeService/data/wob.sql`) has the DDL but also user
  data. **Closed by D16:** the dump is not used; the starting schema is
  built with `Base.metadata.create_all` from the models at `918566c`, then
  stamped `20260923_sso_user` (§19.3).
- **F4. Production schema confirms the spec.** `version varchar(8) NOT
  NULL`, `category varchar(8)`, `KEY user_id`, `KEY review_user_id`, head
  `20260923_sso_user` (`/workspace/WordBridgeService/data/wob.sql:38`,
  `:58-59`, `:65-66`). `review_user_id` is also a foreign key with its own
  index; no quota query uses it.
- **F5. The sync replaces whole directories.** `sync()` removes each target
  with `rmtree` before copying (`server/sync_addon_code.py:52-55`). Syncing
  `setting/templates/` and `setting/task/` must replace those subdirectories
  only, never `server/app/setting/`, which also holds the server-only
  `catalog.json` and the new range and version files.
- **F6. 你 vs 您 in the zh_TW drafts.** The existing zh_TW catalogue uses
  您 (6 msgstr lines) and never 你; the drafts use 您 in
  `user_quota_exceeded` but 你 in `account_unverified` and
  `account_disabled`. **Closed by D17:** 您 everywhere; the strings table
  (§17) is updated.
- **F7. `pytest` is listed, but not for the server.** It is pinned in the
  add-on's `tests/requirement.txt:1`; storage/spec.md says it is in no list.
  The conclusion for the server (§14.1) holds.
- **F8. Location of `data/corrector_config/`.** It is
  `/workspace/WordBridgeService/data/corrector_config/`, mounted into the
  container at `/app/data` (`/workspace/WordBridgeService/wob/docker-compose.yml:9-10`),
  not under `wob/server/`.
- **F9. Where the key check lives matters for alembic.** `alembic/env.py`
  imports `app.settings` (`server/alembic/env.py:24`). If item 6's check is
  added to `load_settings()`, running migrations would also require the API
  keys; a check in the app's startup path would not. **Closed by D18:** the
  check goes in the correction-settings startup path, not in
  `load_settings()` (§10.2).
- **F10. The comment at `server/app/main.py:238-239`** says exception
  details are never surfaced "to the client or the log", but
  `logger.exception` at `:240` logs the exception text. **Closed by D19:**
  the comment is rewritten as part of item 11's logging change (§15.5).

Not verified here: Traefik's default `X-Forwarded-*` handling (§1.1, checked
after deployment by §5.7); the SQLAlchemy pool and anyio thread-pool
defaults (§8.1, §11.2) are library defaults, not checked against installed
sources (the server's dependencies are not installed in this container).

## 21. Non-goals

- Item 2 `/feedback` and item 3 quota race (§6, §7).
- Quota bypass by IPv6 address rotation.
- Making the main routes async or removing fastcrud.
- Linting `workspace/` (`.pre-commit-config.yaml` covers only the add-on,
  tests and server).
- Calling AI services at startup to validate keys.
- Running migrations automatically from the Dockerfile.

## Appendix A: out of scope, but needs attention

- **Leaked database password (urgent):** production's DB password is the
  one public on GitHub since `005b542` (`wob/.env`,
  `wob/mariadb/init.sql`); `wob/mariadb/Dockerfile`'s root password is the
  same. It should be changed soon.
- **Traefik** (`/workspace/entry/entry/traefik.yml`, shared
  infrastructure):
  - `api.insecure: true` (`traefik.yml:4-6`) plus a router for `/api` and
    `/dashboard` on the `web` entry point
    (`/workspace/entry/entry/docker-compose.yml:12-13`): the dashboard is
    readable on port 80 without login.
  - `log.level: DEBUG` (`traefik.yml:1-2`).
  - The domain is proxied by Cloudflare, but the certificate resolver uses
    `tlsChallenge` (`traefik.yml:80-82`), so renewal may fail.
- `wob/server/` is a hand-copied deployment directory, older than the
  repository, and still has the deleted `imp.py`
  (`/workspace/WordBridgeService/wob/server/app/imp.py`).
  `/workspace/WordBridgeService/data/corrector_config/` is an old model
  configuration the current code does not read (F8).
