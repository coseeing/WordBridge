# Catalog retry and live settings panel update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans.
> WordBridge normal flow: one implementer runs every task in order; the
> orchestrator dispatches the final Fable 5.1 review (DEVELOPMENT_WORKFLOW.md §3.3).

**Goal:** A failed remote-catalog fetch is retried in the background with
doubling waits (1–32 min), opening the WordBridge settings panel after a
failure fetches at once, and an open panel updates its choices, account boxes,
status line and accessible description in place and briefly says whether the
update worked; the model list URL is changed through an NVDA-style
"Change..." dialog with a "Test..." button and saved on that dialog's OK.

**Architecture:** All retry state lives on the wx main thread inside
`CatalogUpdater` (`catalog_updater.py`): an injected `schedule(delay_ms,
callback)` (production: `wx.CallLater` through `_schedule_catalog_retry` in
`__init__.py`) arms one guarded timer per failure; `refresh()` cancels it and
resets the counter on a URL-key change; `retry_on_panel_open()` serves R1;
listeners receive a `CatalogChange` after every state change. The settings
panel (`dialogs.py`) registers one listener, always owns its status and
dropped-entries lines, and rebuilds in place (`_rebuild`) without moving focus,
deferring while a drop-down is open or focus sits in a control the rebuild
would hide. The URL group (read-only box + "Change...") opens
`CatalogUrlDialog` (`catalog_url_dialog.py`, on NVDA's public
`SettingsDialog`), whose "Test..." runs `CatalogUpdater.probe()` (the normal
fetch and acceptance path, no install, no cache) on a daemon thread.

**Tech Stack:** Python (NVDA add-on; NVDA runs Python 3.13), wxPython via NVDA
`gui`, pytest (table-driven; no Hypothesis/mutmut), gettext `nvda.po`.

**Spec:** `docs/superpowers/specs/2026-11-04-catalog-retry-design.md`
(decisions committed at `94f68ec`, `bbf08d1` and `dbb0355`), which amends
`docs/superpowers/specs/2026-11-04-remote-catalog-design.md` ("RC"). §n below
refers to the retry spec. Paths are relative to
`addon/globalPlugins/WordBridge/` unless they start with `tests/`, `docs/`,
`server/` or `/workspace/`.

## Global Constraints

- Branch `feat/catalog-retry`, worktree `/workspace/WordBridge-catalog-retry`; never touch the main checkout `/workspace/WordBridge`.
- Every commit is green: add-on `/tmp/claude-0/-workspace-WordBridge/9af55a63-c255-4088-9b3c-fe363afb236f/scratchpad/testvenv/bin/python -m pytest -q --ignore-glob='tests/test_integration_*' tests` (baseline **805 passed, 1 skipped**); server `cd server && /workspace/WordBridge/server/.venv/bin/python -m pytest -q` (baseline **103 passed**, unchanged by this plan); `prek run --all-files` all Passed; `git diff --check` clean. Never run `tests/test_integration_*` (paid live APIs). At most 3 pytest workers; stop pytest if MemAvailable < 3 GB.
- NVDA runs Python 3.13 (`/workspace/nvda/pyproject.toml`, `requires-python = ">=3.13,<3.14"`) while the test venv is 3.14: no 3.14-only syntax or library behaviour.
- `catalog_updater.py` imports only the standard library and `.lib.catalog`; wx, `requests`, the log and the scheduler are injected (its module docstring).
- Retry constants (§7.1, R5): `RETRY_FIRST_WAIT_MINUTES = 1`, `RETRY_MAX_WAIT_MINUTES = 32`, module globals read at use; wait = `RETRY_FIRST_WAIT_MINUTES * 2 ** count`; stop when wait `>` max; delay in ms = wait × 60_000.
- Panel constants (§10.2): `CB_GETDROPPEDSTATE = 0x0157`, `DEFERRED_UPDATE_POLL_MS = 300`, both in `dialogs.py`.
- Log lines (§12), info level, exact: `WordBridge: catalog fetch retry scheduled attempt=%d delay=%dmin`, `WordBridge: catalog fetch retries stopped attempts=%d`, `WordBridge: catalog fetch started on settings panel open host=%s` (host from `redact_url`); listener failure: `log.warning("WordBridge: catalog listener failed type=%s", type(error).__name__)`. Never a URL path/query, `str(error)`, `exc_info` or a body (RC D15).
- Strings (§13): `Model list updated.` → `模型清單已更新。`; `Model list update failed.` → `模型清單更新失敗。` (C15 full-width period), each with a `# Translators:` comment; zh_TW in `addon/locale/zh_TW/LC_MESSAGES/nvda.po`, checked with `msgfmt --check -o /dev/null addon/locale/zh_TW/LC_MESSAGES/nvda.po`. No new status-line strings (C12).
- `ui.message(text)` with the text only (default NORMAL priority, §11). Never `SetFocus()`, `onPanelActivated()` or `Show()` on the panel during a live update (C7, F2).
- User decisions (2026-11-04): R1–R6 as amended; R7 (C8 confirmed); R8 (OQ1 → C: only user-initiated failures are spoken); R9 (OQ2 → A: the U7 dialog starts no fetch); R10 (a saved URL change resets the backoff; R6 covers the panel-open retry only); R11 (`panelDescription` mirrors the status line); R12 (URL through a "Change..." dialog, saved on its OK). Orchestrator defaults C16–C21 (spec §20): no reuse of NVDA's private `_SetURLDialog`; validation on the dialog's OK with `_url_identity`; empty URL allowed with the placeholder; strings per §20.5; live updates never touch the dialog; a test result binds to the tested text.
- URL dialog strings and zh_TW (spec §20.5) are copied verbatim, each with a `# Translators:` comment; the URL group stays the panel's last item (RC D16).
- The probe never installs a catalog, writes the cache or changes updater state; it uses `fetch_payload(check.url, http_get=self._http_get, clock=self._clock)` (D4) and `parse_remote_payload` + `accept_remote_document` (RC §8.3/§8.4).
- `_load_nvda_plugin` and the widget stubs are imported at function scope, never at module scope (coseeing_auth import poisoning). No test performs real HTTP. Plugin tests must not see retry timers in `wx.timers`.
- `tests/test_translator_comments.py` named by spec §13/§15.4 does not exist in this repository; every task that adds strings (12–15) checks its own `# Translators:` comments and zh_TW entries instead.
- git (DEVELOPMENT_WORKFLOW.md §8): stage explicit paths only and check `git diff --cached --stat`; English `<type>: <summary>` with a why-body; no `Co-Authored-By`; no `--no-verify` (restage if prek edits); no push; no `git stash`; new files under `docs/` need `git add -f <exact path>`; delete nothing outside the scratchpad.
- Deviations go to `.superpowers/sdd/2026-11-04-catalog-retry/progress.md` as `Ruling: <decision> — <reason> — <cost if wrong>`.
- Mutant checks named in a task are run after its commit by editing the committed file in the worktree, running the named test (expected FAIL), and restoring with `git checkout -- <file>`; results go to the ledger.
- Linux tests cover injected boundaries only; spec §15.6 and §20.7 (Windows/NVDA manual checks, items 1–17 and 3a) is not automated.

## Review Focus

1. **A stopped timer delivered late after a fresh failure** — wx may deliver timer A's event after `Stop()`; if by then the next generation has failed too (so `fetch == failed`) only the generation check stops a second, overlapping fetch and keeps the newer handle stoppable. Expected: nothing starts, and `close()` still stops the newer handle. Covered by Task 1 (`test_a_stopped_timer_delivered_late_starts_nothing`).
2. **URL saved twice quickly, A → B → A, while a retry for A is pending** — Expected: every change cancels the pending timer and resets the count; only the last URL is ever fetched by a later retry; the stale A handle does nothing. Covered by Task 2 (`test_a_retry_fetches_the_current_url_not_the_armed_one`, row `a-b-a`).
3. **OK pressed (DestroyLater) and an update arriving before and after the panel's C++ object is gone** — Expected: before destruction the rebuild may run but nothing is spoken (dialog inactive); after it, the listener unregisters itself and touches no control. Covered by Task 8 (`test_a_notification_after_the_panel_is_gone_unregisters_and_does_nothing`) and Task 15 (`test_no_announcement_when[destroyed]`, `[inactive]`).
4. **The user is typing an API key in a box that stays while the list arrives** — Expected: typed text kept, no deferral, focus untouched, the box stays shown. Covered by Task 10 (`test_typed_api_keys_survive_a_rebuild`) and Task 11 (`test_focus_in_a_box_that_stays_does_not_defer`).
5. **The category is hidden (user on another NVDA settings category) when the list arrives, then the dialog stays inactive** — Expected: the hidden panel is rebuilt but never shown (`Show`/`onPanelActivated` never called) and nothing is spoken. Covered by Task 9 (`test_a_rebuild_never_moves_focus_or_shows_the_panel`) and Task 15 (`test_no_announcement_when[hidden]`).

---

## File Structure

| File | Responsibility | Tasks |
| --- | --- | --- |
| `catalog_updater.py` | retry constants, `schedule` injection, timer, R10 reset, `retry_on_panel_open`, `CatalogChange`, listeners, `close()`, module `add_listener`/`remove_listener`/`retry_on_panel_open`, `uninstall()` closes | 1–4 |
| `__init__.py` | `_schedule_catalog_retry` seam passed as `schedule=` | 6 (erratum, final review m7: was listed as 5) |
| `catalog_updater.py` (probe) | `ProbeResult`, `CatalogUpdater.probe`, module `probe_url` | 5 |
| `dialogs.py` | R1 call, always-present lines, `panelDescription`, listener/destroy wiring, `_rebuild`, account boxes on demand, deferral, URL group, announcements | 7–11, 14, 15 |
| `catalog_url_dialog.py` (new) | `CatalogUrlDialog`, `url_identity` (moved from `dialogs._url_identity`), `invalid_url_message`, test-result texts | 12, 13 |
| `addon/locale/zh_TW/LC_MESSAGES/nvda.po` | new entries per task | 12–15 |
| `tests/test_catalog_retry.py` (new) | updater retry/listener/probe tests with `FakeScheduler` | 1–5 |
| `tests/test_catalog_updater.py` | `Harness(schedule=None)` passthrough | 1 |
| `tests/test_coseeing_auth_nvda.py` | harness: retry seam recorder; richer `SettingsPanel`/`SettingsDialog`, widget, sizer, expando, message and progress stubs; two `catalogIssuesText is None` assertions | 6, 7, 12, 14 |
| `tests/test_catalog_plugin_wiring.py` | wiring tests | 6 |
| `tests/test_catalog_settings_panel.py` | R1/lines/description at open; URL-field tests replaced by URL-group tests | 7, 14 |
| `tests/test_catalog_panel_live.py` (new) | live update tests with a `FakeUpdater` and one real-updater end-to-end test | 8–11, 15 |
| `tests/test_catalog_url_dialog.py` (new) | dialog OK and Test tests | 12, 13 |

## Batching

15 tasks, three batches of 5 (DEVELOPMENT_WORKFLOW.md §3.2):
**Batch 1 = Tasks 1–5** (`catalog_updater.py`: retry, URL reset, panel-open
retry, listeners, probe), **Batch 2 = Tasks 6–10** (plugin wiring, panel open,
live wiring, rebuild, account boxes), **Batch 3 = Tasks 11–15** (deferral, URL
dialog OK, URL dialog Test, panel URL group, announcements). Stop and report
after Batches 1 and 2 for a batch review; Batch 3 is covered by the final
Fable review.

Expected add-on counts after each task (skipped stays 1; server stays 103):
T1 841, T2 848, T3 860, T4 877, T5 894, T6 900, T7 911, T8 917, T9 929,
T10 938, T11 947, T12 965, T13 980, T14 979 (12 added, 13 URL-field tests
replaced), T15 995. A task whose real count differs records it in the ledger;
the next task's numbers shift by the same amount.

---

### Task 1: Retry schedule core

**Files:**
- Modify: `catalog_updater.py` (constants after `_FETCH`; `CatalogUpdater.__init__` `:142-172`; `refresh` `:193-209`; `_apply` `:299-320`)
- Modify: `tests/test_catalog_updater.py:82-100` (`Harness.__init__(self, tmp_path, responses=None, schedule=None)` passes `schedule=schedule`)
- Create: `tests/test_catalog_retry.py`

**Interfaces:**
- Consumes: existing `CatalogUpdater`, `Harness`, `_payload`, `_ok`, `FakeResponse`, `URL_A`, `URL_B`, `updater_module` from `tests/test_catalog_updater.py` (imported as `from test_catalog_updater import …`).
- Produces:
  - `RETRY_FIRST_WAIT_MINUTES = 1`, `RETRY_MAX_WAIT_MINUTES = 32` (module globals).
  - `CatalogUpdater(..., schedule=None)`; `schedule(delay_ms: int, callback) -> handle` with `handle.Stop()`; `None` disables retries.
  - Private, used by Tasks 2–4: `_retry_count: int`, `_retries_stopped: bool`, `_retry_timer`, `_cancel_retry_timer() -> None`, `_schedule_retry() -> None`, `_on_retry_timer(armed_generation: int) -> None`, `_current_url: str`.
  - Test helpers in `tests/test_catalog_retry.py`: `FakeTimer` (`delay_ms`, `callback`, `stopped`, `fired`, `Stop()`, `fire()`), `FakeScheduler` (`timers`, `__call__(delay_ms, callback)` asserting no other live handle — "no stacked timers" —, `live() -> list`), `retry_harness(tmp_path, responses) -> Harness` (with a `FakeScheduler` at `h.scheduler`), `finish(h)` (runs the newest thread and delivers), `fire_and_finish(h)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_catalog_retry.py`

`STOPPED = "WordBridge: catalog fetch retries stopped attempts=%d"`, `SCHEDULED = "WordBridge: catalog fetch retry scheduled attempt=%d delay=%dmin"`.

- `test_retry_schedule_table` parametrized `(maximum, expected)` with ids `max-32: 32 → [1, 2, 4, 8, 16, 32]`, `max-0: 0 → []`, `max-1: 1 → [1]`, `max-3: 3 → [1, 2]`, `max-40: 40 → [1, 2, 4, 8, 16, 32]`. URL_A answers 500. `initial_catalog`, `refresh`, `finish`; while `h.scheduler.live()`: record its delay, `fire_and_finish`. Assert `delays == [m * 60_000 for m in expected]`, `h.requests == [URL_A] * (1 + len(expected))`. Then `h.updater.refresh(URL_A); finish(h)` twice more: `h.scheduler.live() == []` and exactly one log record `("info", STOPPED, len(expected))`.
- `test_a_wait_equal_to_the_maximum_is_performed`: maximum 32; after five fires the live timer has `delay_ms == 32 * 60_000`; firing it appends a 7th request.
- `test_a_success_resets_the_schedule` parametrized `k` in `0..5` (ids `k0`…`k5`): fail at start, fire-and-fail `k` times, switch the response to `_ok(_payload("fresh"))`, fire-and-finish. Assert `h.scheduler.live() == []`, `h.status() == ("fetched", "succeeded")`. Then response 500, `refresh(URL_A)`, `finish` → the live timer's `delay_ms == 60_000`.
- `test_every_fetch_failure_arms_a_retry` parametrized (12 rows, ids): `404`, `500`, `301` (status codes), `timeout` (`h.updater._clock` returns 0 then 100 forever), `declared-too-large` (`Content-Length` `MAX_PAYLOAD_BYTES + 1`, small body), `streamed-too-large` (headers `{}`, body `MAX_PAYLOAD_BYTES + 1` bytes), `non-json` (`b"<html>"`), `schema-2` (`schema_version` 2), `no-models` (`active=False`), `all-providers-disallowed` (provider url `https://evil.test/v1`), `raised-exception` (`OSError`), `build-exception` (monkeypatch `parse_remote_payload` to raise `RuntimeError`). Each: `status()[1] == "failed"` and `len(h.scheduler.live()) == 1` with `delay_ms == 60_000`.
- `test_outcomes_that_are_not_failures_arm_nothing` parametrized (5 rows): `dropped-provider` (payload with one allowed and one disallowed provider/model → succeeded), `cache-write-raises` / `cache-write-reports` (`RaisingStoreCache` / `FailingStoreCache` from `test_catalog_updater`), `stale` (two refreshes, run the older thread's failure only), `after-shutdown` (`shutdown.set()` before `deliver`). Each: `h.scheduler.timers == []`.
- `test_a_failure_with_a_cache_in_use_is_retried`: `seed_cache(URL_A, _payload("cached"))`, 500 → `h.status() == ("cache", "failed")` and one live timer.
- `test_every_fetch_start_cancels_the_pending_timer`: arm; `refresh(URL_A)` → that handle `stopped is True`, `h.scheduler.live() == []`.
- `test_a_stopped_timer_delivered_late_starts_nothing`: arm `t1`; `refresh(URL_A)`; `finish` (fails again, arms `t2`); `t1.fire()` → thread count and `h.requests` unchanged, `h.updater._retry_timer is t2`; `h.updater._cancel_retry_timer()` → `t2.stopped`.
- `test_a_timer_firing_while_the_fetch_runs_starts_nothing`: `initial_catalog`, `refresh` (generation 1, running); `h.updater._on_retry_timer(1)` → `len(h.threads) == 1`.
- `test_shutdown_stops_retries`: arm; `h.shutdown.set()`; `fire()` → no new thread.
- `test_without_a_scheduler_nothing_is_retried`: plain `Harness` (schedule None), failure → no exception, no `SCHEDULED`/`STOPPED` record.
- `test_retry_log_lines_carry_only_attempt_and_delay`: URL_A raises `OSError("… https://a.test/catalog?token=secret-a")`; after the first failure the records include `("info", SCHEDULED, 1, 1)`; after exhausting with maximum 32, `("info", STOPPED, 6)`; `h.log.text()` contains neither `/catalog`, `token`, `secret` nor `connect`.

- [ ] **Step 2: Run to verify red**

Run: `…/testvenv/bin/python -m pytest -q tests/test_catalog_retry.py`
Expected: FAIL — `TypeError: Harness.__init__() got an unexpected keyword argument 'schedule'` / `CatalogUpdater.__init__() got an unexpected keyword argument 'schedule'` (36 failed).

- [ ] **Step 3: Implement in `catalog_updater.py`**

- Constants with the §7.1 comment.
- `__init__(..., start_thread=start_daemon_thread, schedule=None)`; initialise `_retry_count = 0`, `_retries_stopped = False`, `_retry_timer = None`, `_current_url = ""`.
- `initial_catalog(url)` and `refresh(url)` set `_current_url = url`; `refresh` calls `_cancel_retry_timer()` first.
- `_cancel_retry_timer()`: swap the handle to `None`, then `Stop()` it.
- `_apply`: success → `_retry_count = 0`, `_retries_stopped = False`, `_cancel_retry_timer()`; failure (after the status and warning) → `_schedule_retry()`.
- `_schedule_retry()`: §7.2 pseudo-code verbatim; the callback is `functools.partial(self._on_retry_timer, generation)` with `generation` read under the lock.
- `_on_retry_timer(armed_generation)`: §7.3 pseudo-code; clear `_retry_timer` only when `armed_generation` is current; then `self.refresh(self._current_url)`.
- Extend the class docstring: retry state is main-thread only (§14).

- [ ] **Step 4: Run to verify green**

Run: the Step 2 command → `36 passed`. Full add-on suite → **841 passed, 1 skipped**. `prek run --all-files` Passed; `git diff --check` clean.

- [ ] **Step 5: Commit**

```bash
git add addon/globalPlugins/WordBridge/catalog_updater.py tests/test_catalog_updater.py tests/test_catalog_retry.py
git commit -m "feat: retry a failed catalog fetch with doubling waits"
```

- [ ] **Step 6: Mutant checks** (restore with `git checkout -- addon/globalPlugins/WordBridge/catalog_updater.py`): drop the generation comparison in `_on_retry_timer` → `test_a_stopped_timer_delivered_late_starts_nothing` FAILS; drop the `_fetch == FETCH_FAILED` comparison → `test_a_timer_firing_while_the_fetch_runs_starts_nothing` FAILS; remove `_cancel_retry_timer()` from `refresh` → `test_every_fetch_start_cancels_the_pending_timer` FAILS (and `FakeScheduler` reports a stacked timer); `>` → `>=` → `test_retry_schedule_table[max-32]` FAILS. Record in the ledger.

---

### Task 2: URL changes reset the backoff (R10, C4, §7.4)

**Files:**
- Modify: `catalog_updater.py` (`refresh`)
- Test: `tests/test_catalog_retry.py`

**Interfaces:**
- Consumes: Task 1 helpers and state.
- Produces: `refresh(url)` resets `_retry_count = 0` and `_retries_stopped = False` whenever `check.key != _live_key` (the existing `changed`), including a switch to an empty or invalid URL. Same-key refreshes (startup, timer) keep the count.

- [ ] **Step 1: Write the failing tests**

- `test_a_retry_fetches_the_current_url_not_the_armed_one` parametrized `a-b` / `a-b-a` (2): A fails (armed `tA`); `refresh(URL_B)` (and for `a-b-a` then `refresh(URL_A)` again before B finishes, with the final URL X = A, otherwise X = B); `tA.stopped`; `tA.fire()` → no new thread or request; finish the newest thread (X fails) → live timer `delay_ms == 60_000`; fire-and-finish → `h.requests[-1] == X`.
- `test_a_url_change_resets_the_schedule`: A fails 3 times (live delay 4 min); `refresh(URL_B)`; then B keeps failing → delays `[1, 2, 4, 8, 16, 32]` min.
- `test_a_url_change_after_retries_stopped_starts_the_full_schedule_again`: exhaust A; `refresh(URL_B)` and keep failing → `[1, 2, 4, 8, 16, 32]` again; `STOPPED` records == 2.
- `test_a_same_key_refresh_keeps_the_count`: A fails (count 1); `refresh("  " + URL_A + "  ")`, finish → live delay `2 * 60_000`.
- `test_switching_to_an_empty_or_invalid_url_cancels_and_resets` parametrized `empty` (`""`) / `invalid` (`"http://example.com/"`) (2): A fails twice (live delay 4 min); `refresh(value)` → that handle stopped, no new thread, `live() == []`; `refresh(URL_B)`, finish → delay `60_000`.

- [ ] **Step 2: Run to verify red**

Run: `…/python -m pytest -q tests/test_catalog_retry.py -k "current_url or resets or same_key or switching"`
Expected: FAIL — the URL-change rows see `delay_ms == 120_000`/`240_000` etc. instead of `60_000` (6 failed); `test_a_same_key_refresh_keeps_the_count` passes already (1 passed).

- [ ] **Step 3: Implement** the reset in `refresh()` from the existing `changed` flag, after the lock block; update the `refresh` docstring ("a URL change also resets the retry schedule, R10").

- [ ] **Step 4: Run to verify green**

Step 2 command → `7 passed`. Full suite → **848 passed, 1 skipped**. prek Passed; `git diff --check` clean.

- [ ] **Step 5: Commit** — `git add addon/globalPlugins/WordBridge/catalog_updater.py tests/test_catalog_retry.py`; `feat: reset the catalog retry schedule when the URL changes`.

- [ ] **Step 6: Mutant checks:** reset on every refresh (not only `changed`) → `test_a_same_key_refresh_keeps_the_count` FAILS; `_on_retry_timer` refreshing the URL given to `initial_catalog` instead of `_current_url` → `test_a_retry_fetches_the_current_url_not_the_armed_one[a-b]` FAILS. Ledger.

---

### Task 3: Panel-open retry (R1, R6, C5, §8)

**Files:**
- Modify: `catalog_updater.py` (method + module function)
- Test: `tests/test_catalog_retry.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: `CatalogUpdater.retry_on_panel_open() -> bool` (main thread; `False` when shut down or `status().fetch != "failed"`; otherwise logs `WordBridge: catalog fetch started on settings panel open host=%s` with `redact_url(validate_catalog_url(self._current_url).url)`, calls `refresh(self._current_url)`, returns `True`). Module `retry_on_panel_open() -> bool` (`False` without an installed updater). Task 4 adds the `_closed` check and the user-initiated flag.

- [ ] **Step 1: Write the failing tests**

- `test_retry_on_panel_open_conditions` parametrized (6) `(state, expected_result, expected_new_threads)`: `failed` → True, 1; `failed-with-timer` → True, 1 and the armed handle `stopped`; `running` (after `refresh`, not finished) → False, 0; `succeeded` → False, 0; `off` (`initial_catalog("")`) → False, 0; `invalid` (`"http://example.com/"`) → False, 0.
- `test_a_panel_open_failure_continues_the_schedule`: failure (1 min armed); `retry_on_panel_open()`, finish → live delay `2 * 60_000`.
- `test_a_panel_open_failure_after_retries_stopped_arms_nothing`: exhaust; `retry_on_panel_open() is True`; finish → `live() == []`, `STOPPED` records still 1.
- `test_retry_on_panel_open_never_starts_a_second_fetch`: failure; first call True, second call False; exactly one new thread.
- `test_the_panel_open_log_line_names_only_the_host`: record `("info", "WordBridge: catalog fetch started on settings panel open host=%s", "https://a.test")`; no `token`/`/catalog` in `h.log.text()`.
- `test_module_retry_on_panel_open` parametrized `no-updater` → `False` / `installed` (failed harness via `updater_module.install`) → `True` and one new thread (2).

- [ ] **Step 2: Red:** `-k panel_open` → `AttributeError: 'CatalogUpdater' object has no attribute 'retry_on_panel_open'` (12 failed).
- [ ] **Step 3: Implement** both functions per §8 steps 1–3.
- [ ] **Step 4: Green:** `12 passed`; full suite **860 passed, 1 skipped**; prek Passed; `git diff --check` clean.
- [ ] **Step 5: Commit** — `feat: fetch the catalog when the settings panel opens after a failure`.
- [ ] **Step 6: Mutant check:** accept `FETCH_RUNNING` as well → `test_retry_on_panel_open_conditions[running]` FAILS. Ledger.

---

### Task 4: Change events, listeners and close (C6, C14, R8, §9)

**Files:**
- Modify: `catalog_updater.py`
- Test: `tests/test_catalog_retry.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `@dataclass(frozen=True) class CatalogChange: catalog_changed: bool; outcome: str | None; user_initiated: bool = False`.
  - `CatalogUpdater.add_listener(listener) -> None`, `remove_listener(listener) -> None` (removes the first `==` match, so an equal bound method works; unknown is a no-op), `close() -> None` (idempotent, never raises: `_closed = True`, cancel timer, clear listeners).
  - Notifications, synchronous, outside the lock, over a copy of the list, each call in its own `try/except Exception` logging the §12 warning: `refresh()` end → `CatalogChange(changed, None)`; `_apply` success after install/status/log → `CatalogChange(True, "succeeded", self._user_initiated)`; failure after status/log/`_schedule_retry()` → `CatalogChange(False, "failed", self._user_initiated)`.
  - `_user_initiated`: set in `refresh()` to `changed`; `retry_on_panel_open()` sets it to `True` after its `refresh()`; timer and startup refreshes leave `changed` False.
  - `_closed` makes `_schedule_retry`, `_on_retry_timer` and `retry_on_panel_open` do nothing.
  - Module: `add_listener(listener)`, `remove_listener(listener)` forward or no-op; `uninstall()` calls `_UPDATER.close()` (inside `try/except Exception: pass`) before dropping it.

- [ ] **Step 1: Write the failing tests**

- `test_change_events_table` parametrized (9 rows; each row builds a harness, attaches a recording listener at the stated point, runs the scenario, asserts the exact list of `CatalogChange`):
  - `refresh-same-key`: `[C(False, None)]`
  - `refresh-new-key`: `refresh(URL_B)` → `[C(True, None)]`
  - `refresh-empty-url`: `refresh("")` → `[C(True, None)]`
  - `startup-success`: `[C(False, None), C(True, "succeeded", False)]`
  - `startup-failure`: `[C(False, None), C(False, "failed", False)]`
  - `timer-failure` (listener added after the first failure, then fire-and-finish): `[C(False, None), C(False, "failed", False)]`
  - `panel-failure`: `[C(False, None), C(False, "failed", True)]`
  - `url-change-failure`: `[C(True, None), C(False, "failed", True)]`
  - `url-change-success`: `[C(True, None), C(True, "succeeded", True)]`
- `test_listeners_see_the_new_state_when_notified`: on the success event the listener reads `h.updater.status() == ("fetched","succeeded")` (as `UpdaterStatus`) and `len(h.installed) == 1`; on a failure event the retry timer is already live.
- `test_a_raising_listener_is_logged_by_type_and_the_next_still_runs`: first listener raises `ValueError("secret")`; second records; record `("warning", "WordBridge: catalog listener failed type=%s", "ValueError")`; `"secret" not in h.log.text()`.
- `test_remove_listener_accepts_an_equal_bound_method_and_ignores_unknown`: add `obj.method`, remove a fresh `obj.method` → no more events; removing an unknown callable raises nothing.
- `test_close_stops_the_timer_clears_listeners_and_is_idempotent`: armed handle `stopped`; later `refresh` notifies nobody; `close()` twice raises nothing.
- `test_after_close_nothing_is_armed_or_started`: `refresh`, run thread (failure posted), `close()`, `deliver()` → `h.scheduler.timers` holds no new handle; `retry_on_panel_open() is False`; firing the stopped handle starts no thread.
- `test_close_never_raises_when_stop_raises`: the handle's `Stop` raises `RuntimeError` → `close()` returns; listeners cleared.
- `test_module_listener_functions_without_an_updater_are_no_ops`.
- `test_uninstall_closes_the_installed_updater`: install, arm, `updater_module.uninstall()` → handle stopped, `status() is None`.

- [ ] **Step 2: Red:** `-k "event or listener or close or uninstall"` → `AttributeError: module … has no attribute 'CatalogChange'` (17 failed).
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Green:** `17 passed`; full suite **877 passed, 1 skipped**; prek Passed; `git diff --check` clean.
- [ ] **Step 5: Commit** — `feat: notify catalog listeners and close the updater on uninstall`.
- [ ] **Step 6: Mutant checks:** `user_initiated` always `False` → `test_change_events_table[panel-failure]` FAILS; `uninstall()` without `close()` → `test_uninstall_closes_the_installed_updater` FAILS. Ledger.

---

### Task 5: URL probe for the dialog's "Test..." (C16, spec §20.3)

**Files:**
- Modify: `catalog_updater.py`
- Test: `tests/test_catalog_retry.py`

**Interfaces:**
- Consumes: existing `fetch_payload`, `parse_remote_payload`, `accept_remote_document`, `load_overlay_catalog`, `validate_catalog_url`.
- Produces:
  - `@dataclass(frozen=True) class ProbeResult: kind: str; detail: str = ""; models: int = 0` — kinds exactly as the spec §20.3 table: `ok`, `invalid`, `insecure_scheme`, `empty`, `network`, `http_status`, `not_a_list`, `disallowed_hosts`, `no_models`, `failed`, plus `unavailable` from the module function.
  - `CatalogUpdater.probe(url: str) -> ProbeResult` — thread-safe, never raises, touches no updater state (no lock writes, no generation, no install, no cache, no timer, no listener, no log line of its own). `models` = number of selectable local items (`sum(len(catalog.items_for(g)) for g in catalog.provider_groups if g != COSEEING_GROUP)`). `disallowed_hosts` when acceptance says `remote_no_models` and `load_overlay_catalog(bundled, document, …).issues` holds a `disallowed_provider_url`.
  - Module `probe_url(url: str) -> ProbeResult` — `ProbeResult("unavailable")` without an installed updater.

- [ ] **Step 1: Write the failing tests**

- `test_probe_result_table` parametrized (13) `(id, response, url, expected)`: `ok` (`_payload("fresh")`) → `ProbeResult("ok", models=1)`; `invalid` (`"ftp://x"`, no request) → `("invalid")`; `insecure` (`"http://example.com"`) → `("insecure_scheme")`; `empty` (`"  "`) → `("empty")`; `network-raise` (`OSError`) → `("network", "OSError")`; `network-timeout` (clock 0 then 100) → kind `network`; `http-404` → `("http_status", "404")`; `non-json` → kind `not_a_list`; `schema-2` → `not_a_list`; `too-large` (`Content-Length` over the limit) → `not_a_list`; `disallowed` (provider url `https://evil.test/v1`) → `disallowed_hosts`; `no-models` (`active=False`) → `no_models`; `build-exception` (monkeypatch `accept_remote_document` to raise) → `failed`. Rows without a request assert `h.requests == []`.
- `test_probe_sends_the_d4_request`: a recording `http_get` sees `(url, stream=True, timeout=(5, 10), allow_redirects=False, headers={"Accept": "application/json"})`.
- `test_probe_installs_caches_and_changes_nothing`: after an `ok` probe of URL_B on a harness started on URL_A: `h.installed == []`, `h.cache.stores == []`, `h.threads == []`, `h.scheduler.timers == []`, `h.status()` and `h.updater._generation` unchanged, no listener call, no new log record.
- `test_module_probe_url` parametrized `no-updater` → `ProbeResult("unavailable")` / `installed` → `kind == "ok"` (2).

- [ ] **Step 2: Red:** `-k probe` → `AttributeError: … 'probe'` (17 failed).
- [ ] **Step 3: Implement** per Interfaces (reusing `_fetch_and_build` is not possible because it hides the document; call the four functions directly).
- [ ] **Step 4: Green:** `17 passed`; full suite **894 passed, 1 skipped**; prek Passed; `git diff --check` clean.
- [ ] **Step 5: Commit** — `feat: probe a model list URL without installing it`.
- [ ] **Step 6: Mutant check:** call `self._install(catalog)` in `probe` → `test_probe_installs_caches_and_changes_nothing` FAILS. Ledger.

**Batch 1 ends here: stop and report for the batch review.**

---

### Task 6: Plugin wiring (§7.1, §14, §15.3, R9)

**Files:**
- Modify: `__init__.py` (new `_schedule_catalog_retry` next to `_catalog_http_get` `:161-165`; `_make_catalog_updater` `:269-280` passes `schedule=_schedule_catalog_retry` as a global name looked up when the updater is built)
- Modify: `tests/test_coseeing_auth_nvda.py` (`_load_nvda_plugin`, next to the `_start_catalog_thread` replacement at `:368-375`: keep `plugin.real_schedule_catalog_retry`, replace `_schedule_catalog_retry` with a recorder appending `Timer`-like handles to `plugin.catalog_retry_timers`)
- Test: `tests/test_catalog_plugin_wiring.py`

**Interfaces:**
- Consumes: Task 4 (`uninstall()` closes).
- Produces: `_schedule_catalog_retry(delay_ms, callback)` → `wx.CallLater(delay_ms, callback)`; test harness attributes `plugin.catalog_retry_timers` (handles with `delay_ms`, `stopped`, `Stop()`, `fire()`) and `plugin.real_schedule_catalog_retry`.

- [ ] **Step 1: Write the failing tests** (in `tests/test_catalog_plugin_wiring.py`, using `NO_CACHE_URL`)

- `test_a_failed_startup_fetch_arms_one_retry_through_the_seam`: run the queued fetch start, run the recorded thread target (refused network → failure), run the queue → `[t.delay_ms for t in plugin.catalog_retry_timers] == [60_000]` and `plugin.wx.timers == []`.
- `test_the_retry_seam_uses_wx_call_later_at_call_time`: monkeypatch `plugin.wx.CallLater` with a recorder; `plugin.real_schedule_catalog_retry(5, cb)` → recorder got `(5, cb)` and its return value is returned.
- `test_terminate_stops_a_pending_retry_and_a_late_firing_does_nothing`: after the failure, `instance.terminate()` → timer `stopped`; `fire()` → `plugin.started_catalog_threads` unchanged.
- `test_terminate_closes_the_updater_even_if_earlier_steps_raise`: `shutdown_coseeing_auth` and `_stop_progress_cue` raise → timer `stopped`, `catalog_updater.status() is None`.
- `test_a_successful_retry_lets_a_local_user_correct_without_the_dialog`: `_choice_fixture(catalog_url=NO_CACHE_URL)`, failure → timer; replace `_http_get` with the server body (`fake_http.BodyResponse`, `shipped_catalog.server_document()`); `fire()`, run the new target, run the queue → `f.instance._needs_catalog_choice() is False`; `script_correction(None)` → `f.started == ["原文"]`, `FakeMessageDialog.instances == []`.
- `test_the_switch_dialog_starts_no_fetch` (R9): after the failure, `script_correction(None)` and run the queue (dialog answers No) → no new entry in `plugin.started_catalog_threads`, the retry handle not stopped, `catalog_updater.status().fetch == "failed"`.

- [ ] **Step 2: Red:** `-k "retry or switch_dialog_starts or closes_the_updater"` → `AttributeError: … no attribute 'real_schedule_catalog_retry'` / `catalog_retry_timers == []` (5 failed; `test_the_switch_dialog_starts_no_fetch` fails on the missing timer).
- [ ] **Step 3: Implement** the seam and the `schedule=` argument; harness recorder.
- [ ] **Step 4: Green:** `6 passed`; full suite **900 passed, 1 skipped** (in particular `tests/test_correction_progress_cue.py` unchanged); prek Passed; `git diff --check` clean.
- [ ] **Step 5: Commit** — `feat: drive catalog retries from a wx.CallLater seam`.
- [ ] **Step 6: Mutant check:** pass `schedule=None` → `test_a_failed_startup_fetch_arms_one_retry_through_the_seam` FAILS. Ledger.

---

### Task 7: Panel open — R1, always-present lines, accessible description (C5, C10, R11)

**Files:**
- Modify: `dialogs.py` (`makeSettings` `:129-192`, `catalog_status_message` docstring `:64-69`)
- Modify: `tests/test_coseeing_auth_nvda.py` (stubs: `_load_nvda_plugin` `SettingsPanel` stub and `Wx`; `_install_settings_panel_widget_stubs` `:885-979`; assertions `:1008`, `:1047`)
- Modify: `tests/test_catalog_settings_panel.py` (`:184-194`)

**Interfaces:**
- Consumes: Task 3 module `catalog_updater.retry_on_panel_open()`.
- Produces (dialogs.py):
  - `_dropped_entries_message(catalog) -> str | None` (module function; the two existing strings, moved from `makeSettings`).
  - `LLMSettingsPanel._setLine(line, text: str | None) -> bool` — `SetLabel(text or "")`, `self.settingsSizer.Show(line, bool(text))`; returns whether visibility changed.
  - `LLMSettingsPanel._updateStatusLine() -> bool` — sets `catalogStatusText` from `catalog_status_message(catalog_updater.status())` and `self.panelDescription = message or ""`; returns `_setLine`'s result.
  - `self.catalogIssuesText`, `self.catalogStatusText` always `wx.StaticText`, never `None`.
  - `makeSettings` statement order: `catalog_updater.retry_on_panel_open()`, then `self.settingsSizer = settingsSizer`, then the existing body.
- Produces (test stubs, used by Tasks 8–15): the harness `SettingsPanel` stub class gains `panelDescription = ""`, `__bool__` (instance `alive`, default True), recorded `Bind`, `Freeze`/`Thaw` counters, `IsShown()` (instance `shown`, default True), recorded `Show`/`Hide`/`onPanelActivated`, `GetTopLevelParent()` returning an object whose `IsActive()` reads instance `active` (default True), recorded `_sendLayoutUpdatedEvent`, `GetChildren()`; `Wx.EVT_WINDOW_DESTROY`; `Widget` gains `SetLabel`, `GetItems`, `GetHandle`, `MoveAfterInTabOrder` (recorded), `set_items_calls`; `Sizer` tracks `children`, `Show(item, show=True, recursive=False)`/`Hide`/`IsShown(item)`, `Insert(index, item, **kw)`, `InsertSpacer`, `GetChildren()`; static box sizers carry `GetStaticBox().SetLabel`; `Helper.addItem` appends to its sizer's `children`.

- [ ] **Step 1: Write the failing tests** (`tests/test_catalog_settings_panel.py`)

- `test_opening_the_panel_retries_only_after_a_failure` parametrized `failed` → 1 thread / `succeeded` → 0 / `running` → 0 (3): a real `CatalogUpdater` (fake bundled source, cache under `tmp_path`, recording `start_thread`) installed in `f.dialogs.catalog_updater` and driven to the state; `make_panel()` → threads started; for `failed` also `panel.catalogStatusText.label == STATUS_TABLE[2][3]` (still loading), proving R1 ran before the status was read.
- `test_the_panel_description_is_the_status_line` parametrized over `STATUS_TABLE` (7): `panel.panelDescription == (message or "")`, `panel.catalogStatusText.label == (message or "")`, `panel.settingsSizer.IsShown(panel.catalogStatusText) is (message is not None)`.
- `test_both_lines_exist_in_their_place_when_empty`: fresh status → both lines exist, hidden, order issues line < status line < `providerList` in `panel_added_controls`.
- Change `test_no_status_line_when_the_list_is_fresh` and `test_the_dropped_entries_line_is_silent_for_the_shipped_overlay` to assert the line is hidden with label `""`; change the two `catalogIssuesText is None` assertions in `tests/test_coseeing_auth_nvda.py` the same way.

- [ ] **Step 2: Red:** `tests/test_catalog_settings_panel.py tests/test_coseeing_auth_nvda.py` → the new tests and the changed assertions FAIL (`AttributeError: 'NoneType' object has no attribute 'label'`, `panelDescription` missing); 13 failed.
- [ ] **Step 3: Implement** per Interfaces; update the `catalog_status_message` docstring (drop "the panel is not refreshed afterwards"); stubs per Interfaces.
- [ ] **Step 4: Green:** both files pass; full suite **911 passed, 1 skipped**; prek Passed; `git diff --check` clean.
- [ ] **Step 5: Commit** — `feat: retry on settings panel open and mirror the status in the description`.

---

### Task 8: Live wiring — listener, status line, description, lifecycle (C6, C10, C14, R11, §10.1)

**Files:**
- Modify: `dialogs.py`
- Create: `tests/test_catalog_panel_live.py`

**Interfaces:**
- Consumes: Task 4 `CatalogChange`, module `add_listener`/`remove_listener`; Task 7 stubs, `_updateStatusLine`.
- Produces:
  - `makeSettings` ends with `catalog_updater.add_listener(self._onCatalogChange)` and `self.Bind(wx.EVT_WINDOW_DESTROY, self._onPanelDestroy)`; initialises `_pendingRebuild = False`, `_pendingAnnouncement = None`, `_deferTimer = None`.
  - `_onCatalogChange(change) -> None` — §10.1 steps 1–5 (step 2's speakable test: `outcome == "succeeded"` or (`outcome == "failed"` and `change.user_initiated`)); a status-line visibility change sends `_sendLayoutUpdatedEvent()`.
  - `_applyPendingUpdate() -> None` — this task: returns at once when `not self`; if `_pendingRebuild` calls `self._rebuild()` (Task 9; this task defines `_rebuild() -> bool` returning `False`); clears the flag. Deferral and speech come in Tasks 11 and 15; the URL box refresh in Task 14.
  - `_onPanelDestroy(evt) -> None` — only when `evt.GetEventObject() is self`: remove the listener, stop `_deferTimer`; always `evt.Skip()`.
  - Test helpers in `tests/test_catalog_panel_live.py`: `FakeUpdater` (`status_value`, `listeners`, `retry_on_panel_open()` → False, `status()`, `add_listener`, `remove_listener`, `emit(change)`), `live_fixture(monkeypatch, **settings)` (panel fixture with the `FakeUpdater` installed via `dialogs.catalog_updater.install`, a mutable `catalog` returned by `dialogs.registry.current`, `messages` recorded from `dialogs.ui.message`, `_findFocus`/`_isDroppedDown` seams default `None`/`False`), `change(catalog_changed=False, outcome=None, user_initiated=False)`.

- [ ] **Step 1: Write the failing tests**

- `test_the_panel_registers_one_listener`: `fake.listeners == [panel._onCatalogChange]`.
- `test_the_status_line_and_description_follow_live_updates`: status sequence fetched → none/failed → fetched → none/running, emitting `change()` each time; after each, `catalogStatusText.label`, `IsShown`, `panelDescription` equal the `STATUS_TABLE` text (or `""`/hidden), and `f.messages == []` throughout.
- `test_a_status_visibility_change_sends_one_layout_event_and_a_text_change_none`: none → failed: 1 layout event; failed → cache/failed (text changes, stays shown): still 1.
- `test_a_destroy_event_from_a_child_keeps_the_listener`: `panel.bindings[wx.EVT_WINDOW_DESTROY](evt)` with `GetEventObject()` a child → listener kept, `evt.skipped`.
- `test_a_destroy_event_from_the_panel_unregisters_and_skips`: object is the panel → `fake.listeners == []`, `evt.skipped`.
- `test_a_notification_after_the_panel_is_gone_unregisters_and_does_nothing`: `panel.alive = False`; emit a success with a changed catalog → `fake.listeners == []`, status label and `providerList.items` unchanged, no `SetItems`.

- [ ] **Step 2: Red:** `tests/test_catalog_panel_live.py` → `fake.listeners == []` / missing `EVT_WINDOW_DESTROY` binding (6 failed).
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Green:** `6 passed`; full suite **917 passed, 1 skipped**; prek Passed; `git diff --check` clean.
- [ ] **Step 5: Commit** — `feat: keep the settings panel status line live`.
- [ ] **Step 6: Mutant check:** `_onPanelDestroy` without the `is self` test → `test_a_destroy_event_from_a_child_keeps_the_listener` FAILS. Ledger.

---

### Task 9: Rebuild — selection and D12 baseline (R2, R4, R7/C8, §10.3)

**Files:**
- Modify: `dialogs.py`
- Test: `tests/test_catalog_panel_live.py`

**Interfaces:**
- Consumes: Task 8 `_applyPendingUpdate`, `_rebuild` placeholder.
- Produces:
  - `_storedBaseline(catalog) -> tuple` → `(stored, storedResolved, restoredSelection)` (pure; the `dialogs.py:143-147` rule: `resolved = self.settings.corrector_selection(catalog=catalog)`, `storedResolved = resolved == stored or not stored[1]`, `SelectionState.restore(catalog, *resolved)`); `makeSettings` uses it.
  - `_applyBaseline(baseline) -> None` sets `_storedSelection`, `_storedSelectionResolved`, `_restoredIndices`.
  - `_chooseSelection(new) -> SelectionState` (pure): touched = shown indices `!= self._restoredIndices`; touched and `new.find_selection(*pick) != (-1, -1)` → that; else the baseline's restored selection for `new` (stored re-read via `stored_corrector_selection()`).
  - `_rebuild() -> bool` (returns "shown windows changed", used by Task 10): choose, apply baseline, `self.catalog = new`, `self.selection = …`; `providerList.SetItems` only when `GetItems()` differs from the new labels, same for `modelList`; `SetSelection` on both; Freeze/Thaw around it (in `_applyPendingUpdate`). Never `SetFocus`, `Show`, `onPanelActivated`.

- [ ] **Step 1: Write the failing tests**

Catalogs: `bundled` (bundled-only, `_bundled_only` as in `tests/test_catalog_settings_panel.py`), `shipped` (`f.plugin.catalog`), `shipped_without(model_id)` (`dataclasses.replace` dropping one model).

- `test_live_selection_table` parametrized (6) `(old, new, stored, touch, expected_item, expected_baseline_item)` — `touch` is a `(group, model_index)` chosen with `providerList.SetSelection` + `onChangeProviderChoice` + `modelList.SetSelection` before the update, or `None`:
  - `fresh-untouched`: bundled → shipped, `("", "")`, None → `("default", "Coseeing")`, same.
  - `stored-local-unresolved-untouched` (F1): bundled → shipped, `("gpt-6-luna&OpenAI", "local")`, None → that model, same.
  - `touched-pick-kept`: shipped → shipped, `("gpt-6.1-sol&OpenAI", "local")`, `("DeepSeek", 0)` → DeepSeek's first item; baseline the stored model.
  - `touched-pick-gone-stored-present`: shipped → `shipped_without(picked)`, stored as above, the picked model → the stored model.
  - `touched-pick-gone-stored-absent`: shipped → `shipped_without(picked)` also without the stored model → default.
  - `stored-coseeing-non-default` (U6): bundled → shipped, `("gpt-6-luna&OpenAI", "Coseeing")`, None → `("default", "Coseeing")`.
  Each asserts `panel.selection.current_item()` ids, `providerList.GetSelection()`/`modelList.GetSelection()` equal the selection's indices, and `panel._restoredIndices` equal the baseline item's indices in `new`.
- `test_an_untouched_save_after_a_rebuild_keeps_an_unresolved_stored_model`: stored `("gpt-retired&OpenAI", "local")`, bundled → shipped, `onSave` → stored unchanged, `auth_calls == []`.
- `test_an_untouched_save_after_the_list_arrives_saves_the_users_own_model` (F1): stored `("gpt-6-luna&OpenAI", "local")`, bundled → shipped, `onSave` → stored `("gpt-6-luna&OpenAI", "local")`, never `("default", "Coseeing")`, `auth_calls == []`.
- `test_a_touched_pick_kept_across_a_rebuild_is_saved`: `touched-pick-kept` then `onSave` → DeepSeek's first item, channel `local`.
- `test_the_baseline_is_reread_from_config_after_apply`: untouched panel; write a new stored selection into `f.settings` (as Apply does), emit `change(catalog_changed=True)` with the same catalog → `_storedSelection` equals the new stored value.
- `test_a_rebuild_never_moves_focus_or_shows_the_panel` parametrized `shown` / `hidden` (2): bundled → shipped; no widget has `focused`, `panel.show_calls == panel.activated_calls == 0`, `panel.freeze_count == panel.thaw_count == 1`; for `hidden` (`panel.shown = False`) the rebuild still ran (`providerList.items` updated) and `panel.shown is False`.
- `test_choices_are_replaced_only_when_their_labels_change`: emit a catalog-changed event with the same catalog → `set_items_calls == 0` on both choices; then bundled → shipped → `providerList.set_items_calls == 1`.

- [ ] **Step 2: Red:** `-k "selection or save_after or kept_across or reread or rebuild_never or replaced_only"` → items unchanged (placeholder `_rebuild`) (12 failed, except `[hidden]`/`[shown]` failing on unchanged items).
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Green:** `12 passed`; full suite **929 passed, 1 skipped**; prek Passed; `git diff --check` clean.
- [ ] **Step 5: Commit** — `feat: rebuild the settings panel choices when the catalog changes`.
- [ ] **Step 6: Mutant checks:** keep the old D12 baseline (skip `_applyBaseline` in `_rebuild`) → `test_an_untouched_save_after_the_list_arrives_saves_the_users_own_model` FAILS; literal R4 (keep the shown item whenever it exists, ignoring touched) → `test_live_selection_table[stored-local-unresolved-untouched]` FAILS; add `self.providerList.SetFocus()` → `test_a_rebuild_never_moves_focus_or_shows_the_panel` FAILS. Ledger.

---

### Task 10: Account boxes on demand (C9, §10.4)

**Files:**
- Modify: `dialogs.py` (account loop `:215-241`, `_refreshAccountInfo` `:330-335`, `_rebuild`)
- Test: `tests/test_catalog_panel_live.py`

**Interfaces:**
- Consumes: Task 9 `_rebuild`.
- Produces:
  - `_ensureAccountBox(group, *, live: bool) -> None` — creates the box once (caption `_provider_group_label(catalog, group) + " " + _("Authentication")`, Coseeing clean button or `API Key:` field as today). `live=False` appends through the panel's helper; `live=True` inserts the box (with a spacer) into `settingsSizer` right after the last existing account box and moves every window it created, in creation order, after `self.modelList` in the Tab order (`MoveAfterInTabOrder` chain) — new windows found by diffing `self.GetChildren()` before/after.
  - `_updateAccountCaption(group) -> None` — `GetStaticBox().SetLabel(...)` when the caption changed (`self._accountCaptions`).
  - `_refreshAccountInfo() -> bool` — iterates `accountGroupSizerMap`, shows only the selected group's box; returns whether the shown group changed (`self._shownAccountGroup`).
  - `_rebuild()` returns `True` when `_refreshAccountInfo()` or the dropped-entries line (`_setLine(self.catalogIssuesText, _dropped_entries_message(new))`) changed visibility; `_applyPendingUpdate` then sends one `_sendLayoutUpdatedEvent()`.

- [ ] **Step 1: Write the failing tests**

- `test_a_new_provider_gets_its_box_after_the_model_choice_in_tab_order`: bundled → shipped; every new group is in `accountGroupSizerMap`; each new box's first created window's `MoveAfterInTabOrder` argument is `panel.modelList` and its field follows it in the chain; in `panel.settingsSizer.children` every new box sits after the Coseeing box and before the `languageList`.
- `test_typed_api_keys_survive_a_rebuild`: shipped panel, type `"typed"` into the OpenAI field, shipped → shipped with a new provider → field value `"typed"`, same widget object.
- `test_a_vanished_providers_box_is_hidden_and_its_key_saved_unchanged`: stored key `"k"` for DeepSeek; shipped → shipped without DeepSeek → its box hidden; `onSave` → `api_key["DeepSeek"] == "k"`.
- `test_refreshing_account_info_never_raises_for_any_group_change` parametrized `gain` / `lose` / `swap` (3): emit the change, then `onChangeProviderChoice` for every index → no exception; exactly one box shown.
- `test_a_changed_provider_label_updates_the_box_caption`: shipped → shipped with OpenAI's label `"OpenAI EU"` → that box's static box label is `"OpenAI EU Authentication"`.
- `test_the_layout_event_is_sent_only_when_the_shown_box_changes`: same-group update → 0 events; update moving the selection to another group (pick gone) → 1.
- `test_the_dropped_entries_line_follows_the_new_catalog` (C10): shipped → a catalog with two dropped issues → line shown with `"2 catalog entries could not be loaded; see the NVDA log for details."` and one layout event; → one issue → the singular text, no new layout event; → none → hidden, one more layout event.

- [ ] **Step 2: Red:** `-k "box or account or caption or layout_event_is_sent_only"` → `KeyError` from `_refreshAccountInfo` / missing boxes (9 failed).
- [ ] **Step 3: Implement** per Interfaces (`makeSettings` uses `_ensureAccountBox(group, live=False)`).
- [ ] **Step 4: Green:** `9 passed`; full suite **938 passed, 1 skipped**; prek Passed; `git diff --check` clean.
- [ ] **Step 5: Commit** — `feat: create account boxes for providers that appear in a live update`.
- [ ] **Step 6: Mutant check:** drop the `MoveAfterInTabOrder` chain → `test_a_new_provider_gets_its_box_after_the_model_choice_in_tab_order` FAILS. Ledger.

### Task 10 revision: account boxes up front (R13, Decided by the user (2026-11-04))

Replaces Task 10's on-demand creation after the batch-2 review (spec §10.4, R13).

**Files:** `dialogs.py` (`ACCOUNT_BOX_GROUPS`; `makeSettings` account loop; `_ensureAccountBox` → `_makeAccountBox`; `_rebuild`; `onSave` key loop; `_accountBoxInsertIndex` removed), `settings_repository.py` (`stored_api_key`), `tests/test_coseeing_auth_nvda.py` (widget stub records every created window in `plugin.created_windows`), `tests/test_settings_repository.py`, `tests/test_catalog_panel_live.py`.

**Interfaces:**
- Produces: `ACCOUNT_BOX_GROUPS = tuple(sorted(SUPPORTED_PROVIDERS)) + (COSEEING_GROUP,)`; `SettingsRepository.stored_api_key(provider) -> str` (never writes); `_makeAccountBox(group) -> None` (makeSettings only); `_updateAccountCaptions() -> None` (rebuild); `onSave` writes a key only when `value != stored_api_key(group)`.
- Removes: `_ensureAccountBox(group, *, live)`, `_accountBoxInsertIndex()`, every `MoveAfterInTabOrder`, `InsertSpacer` and `Insert` call.

- [ ] **Step 1: Failing tests** (`tests/test_catalog_panel_live.py`, `tests/test_settings_repository.py`): `test_every_supported_provider_has_a_box_in_a_fixed_order` (bundled/shipped, 2), `test_only_the_selected_groups_box_is_shown`, `test_a_live_update_creates_no_window_and_only_shows_hides_and_relabels`, `test_tab_and_window_order_is_creation_order`, `test_no_blank_api_key_is_written` (paths: open, rebuild, rebuild-after-ok, untouched-ok, typed-ok, kept, cleared — 7), `test_a_stored_api_key_read_never_writes` (+ aggregated section). `test_a_new_provider_gets_its_box_after_the_model_choice_in_tab_order` is replaced.
- [ ] **Step 2: Red**, **Step 3: Implement**, **Step 4: Green** (full suite; counts in the ledger), **Step 5: Commit** — `feat: create every account box up front and only show or hide it`.
- [ ] **Step 6: Mutants:** create boxes from the catalog's groups → `test_every_supported_provider_has_a_box_in_a_fixed_order[bundled]` FAILS; `onSave` writes every field → `test_no_blank_api_key_is_written[untouched-ok]` FAILS; populate with `api_key()` → `test_no_blank_api_key_is_written[open]` FAILS.

Task 11 consumes `_refreshAccountInfo`/`accountTextCtrlMap` from this revision (no box creation in the rebuild).

---

**Batch 2 ends here: stop and report for the batch review.**

---

### Task 11: Deferral — open drop-down or focus about to be hidden (C7, §10.2)

**Files:**
- Modify: `dialogs.py`
- Test: `tests/test_catalog_panel_live.py`

**Interfaces:**
- Consumes: Tasks 8–10.
- Produces:
  - `CB_GETDROPPEDSTATE = 0x0157`, `DEFERRED_UPDATE_POLL_MS = 300`.
  - `_isDroppedDown(choice) -> bool` — `import winUser` inside the `try`; `winUser.sendMessage(choice.GetHandle(), CB_GETDROPPEDSTATE, 0, 0) != 0`; any exception → `False`.
  - `_findFocus()` → `wx.Window.FindFocus()`, any exception → `None`.
  - `_mustDefer() -> bool` — §10.2: a rebuild is pending and (either choice dropped down, or the focus is the shown group's API key field / the Coseeing clean button while `_chooseSelection(registry.current()).provider_group` differs from the shown group).
  - `_applyPendingUpdate` arms at most one `wx.CallLater(DEFERRED_UPDATE_POLL_MS, self._onDeferTimer)` while deferred; `_onDeferTimer()` clears `_deferTimer`, returns if `not self`, else `_applyPendingUpdate()`. `_onPanelDestroy` stops it.

- [ ] **Step 1: Write the failing tests**

- `test_an_open_drop_down_defers_the_rebuild_and_polls` parametrized `provider` / `model` (2): `_isDroppedDown` true for that choice; bundled → shipped → items unchanged, `[t.delay_ms for t in wx.timers] == [300]`; a second event arms no second timer; "close" it, `fire()` → items updated, no timer live.
- `test_focus_in_a_box_the_rebuild_hides_defers_it`: shipped panel showing OpenAI with focus in its field; new catalog without the shown pick (touched) so the group changes → deferred; focus moves to `languageList`, `fire()` → rebuilt.
- `test_focus_in_a_box_that_stays_does_not_defer`: focus in the shown OpenAI field; update keeps OpenAI → rebuilt at once, no timer.
- `test_focus_on_the_clean_button_defers_when_coseeing_is_left`: Coseeing shown with focus on `coseeingCleanButton`; untouched panel whose stored local model arrives (F1) → deferred.
- `test_the_poll_stops_when_the_panel_is_destroyed`: deferred; destroy event from the panel → the poll handle `stopped`; firing it does nothing.
- `test_the_drop_down_probe` parametrized `no-winuser` → False / `dropped` (stub `winUser.sendMessage` returning 1, recording `msg == 0x0157`) → True / `closed` (returns 0) → False (3), calling the real `_isDroppedDown`.

- [ ] **Step 2: Red:** `-k "defer or drop_down or clean_button or poll_stops"` → items updated immediately / missing `_isDroppedDown` (9 failed).
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Green:** `9 passed`; full suite **947 passed, 1 skipped**; prek Passed; `git diff --check` clean.
- [ ] **Step 5: Commit** — `feat: defer a live panel update while a list is open or focus would move`.
- [ ] **Step 6: Mutant check:** `_mustDefer` ignoring the focus rule → `test_focus_in_a_box_the_rebuild_hides_defers_it` FAILS. Ledger.

---

### Task 12: URL dialog — OK paths (R12, C17, C18, spec §20.2)

**Files:**
- Create: `catalog_url_dialog.py`
- Modify: `dialogs.py` (`_url_identity` `:95-99` moves to the new module as `url_identity`; `isValid` `:360-379` takes its two texts from `invalid_url_message`)
- Modify: `tests/test_coseeing_auth_nvda.py` (harness: `gui.settingsDialogs.SettingsDialog` stub recording `DestroyLater`/`SetReturnCode`, `onOk` → return code OK; `Wx` gains `EVT_TEXT`, `EVT_CHAR_HOOK`, `WXK_RETURN`, `ID_OK`, `ID_CANCEL`)
- Modify: `addon/locale/zh_TW/LC_MESSAGES/nvda.po`
- Create: `tests/test_catalog_url_dialog.py`

**Interfaces:**
- Consumes: `SettingsRepository.catalog_url()`/`save_catalog_url()`, `validate_catalog_url`.
- Produces:
  - `url_identity(text) -> object` (the moved `_url_identity`; `dialogs.py` imports it, so the import direction is `dialogs → catalog_url_dialog`).
  - `invalid_url_message(error: str) -> str` — the two existing texts and their `# Translators:` comments, moved from `isValid`.
  - `class CatalogUrlDialog(SettingsDialog)`: `title = _("Set Model List URL")`; `__init__(self, parent, *, settings, panel)`; `makeSettings(sizer)` builds `self.urlCtrl` (label `"Model list URL:"`, existing tooltip, `size=(scaleSize(375), -1)`, value `settings.catalog_url()`) and `self.testButton` (`"&Test..."`), binds `EVT_TEXT` → `_onTextChange`; `postInit()` focuses `urlCtrl`; `onOk(evt)` per spec §20.2 steps 1–4; `savedUrl: str | None` (None until a save); `testStatus` in `{"untested", "passed", "failed"}`; seams `_showError(message)`, `_askSaveAnyway(failed: bool) -> ReturnCode` (production: `gui.message.MessageDialog`, caption `_("Warning")`, `DefaultButtonSet.YES_NO_CANCEL`, `setDefaultFocus(ReturnCode.CANCEL)`, `SetEscapeId(ReturnCode.CANCEL)`).
  - `onOk` calls `self._panel._updateCatalogUrlBox()` after saving and before `super().onOk(evt)`; Task 14 defines that method (this task's tests pass a stub panel).

- [ ] **Step 1: Write the failing tests** (`tests/test_catalog_url_dialog.py`; dialog built with `object.__new__` and `makeSettings` like the panel, with a recording stub panel)

- `test_the_dialog_shows_the_stored_url_and_focuses_it`: `urlCtrl.GetValue()` is the stored URL, `postInit()` → `urlCtrl.focused`, title `"Set Model List URL"`.
- `test_test_is_enabled_only_for_non_blank_text` parametrized `empty`/`blank`/`url` → disabled/disabled/enabled after `_onTextChange` (3).
- `test_ok_table` parametrized (11) `(id, stored, typed, status, answer, saved, closed, error, warned)`: `unchanged-same`; `unchanged-other-spelling` (`"  HTTPS://WORDBRIDGE.COSEEING.ORG/  "`); `passed` → saved stripped, no warning; `untested-yes` → warning "not tested", saved; `untested-no` → closed, not saved; `untested-cancel` → dialog stays (no `SetReturnCode`), not saved; `failed-yes` → warning "failed", saved; `failed-no` → closed, not saved; `empty` (stored default, typed `""`) → saved `""` without warning; `invalid-malformed` (`"ftp://x"`) → error `MALFORMED`, field focused, stays; `invalid-insecure` (`"http://example.com"`) → error `INSECURE`, stays. Each asserts `settings` content, `dialog.savedUrl`, `return_codes`, warning texts (§20.5 exact), error texts.
- `test_the_box_is_updated_before_the_dialog_closes`: the stub panel records `"box"` and the dialog stub records `"close"` → order `["box", "close"]`.
- `test_editing_the_text_resets_a_passed_test`: `testStatus = "passed"`, `_onTextChange` → `"untested"`.
- `test_the_warning_defaults_to_cancel`: production `_askSaveAnyway` with a `gui.message` stub → `setDefaultFocus(CANCEL)`, `SetEscapeId(CANCEL)`, buttons `YES_NO_CANCEL`, caption `"Warning"`.
- `test_the_dialog_strings_have_translator_comments_and_translations`: every new msgid of this task (§20.5 rows: title, warnings, `Warning`) has a `# Translators:` line directly above its `_()` call in `catalog_url_dialog.py` and its exact zh_TW `msgstr` in `nvda.po`.

- [ ] **Step 2: Red:** `tests/test_catalog_url_dialog.py` → `ModuleNotFoundError: … catalog_url_dialog` (18 failed).
- [ ] **Step 3: Implement** per Interfaces; add the `nvda.po` entries; existing panel tests still pass (isValid uses the moved texts).
- [ ] **Step 4: Green:** `18 passed`; `msgfmt --check` exit 0; full suite **965 passed, 1 skipped**; prek Passed; `git diff --check` clean.
- [ ] **Step 5: Commit** — `feat: add a dialog that saves the model list URL on OK`.
- [ ] **Step 6: Mutant check:** skip the warning for an untested URL → `test_ok_table[untested-no]` FAILS. Ledger.

---

### Task 13: URL dialog — Test (C16, C21, spec §20.3)

**Files:**
- Modify: `catalog_url_dialog.py`, `addon/locale/zh_TW/LC_MESSAGES/nvda.po`
- Modify: `tests/test_coseeing_auth_nvda.py` (harness `gui.IndeterminateProgressDialog` stub with `done()`)
- Test: `tests/test_catalog_url_dialog.py`

**Interfaces:**
- Consumes: Task 5 `catalog_updater.probe_url`, `ProbeResult`; Task 12 dialog.
- Produces:
  - `_onTest(evt)`: strip; invalid → `_showError(invalid_url_message(...))`, no thread; otherwise `self._progress = gui.IndeterminateProgressDialog(self, title=self.title, message=_("Validating the model list URL..."))` and `_start_probe_thread(self._runProbe, (text,))`.
  - Module seam `_start_probe_thread(target, args)` → daemon `threading.Thread(name="wordbridge-catalog-url-test")`, started.
  - `_runProbe(text)` (probe thread) → `wx.CallAfter(self._onProbeDone, text, catalog_updater.probe_url(text))`.
  - `_onProbeDone(text, result)` (main thread): return if `not self`; `done()` the progress dialog; `testStatus = "passed"/"failed"` only when `urlCtrl.GetValue().strip() == text`; `_showResult(message, ok)` (seam; production `gui.message.MessageDialog.alert(message, caption, self)` with `_("Success")` / `_("Error")`).
  - `probe_result_message(result: ProbeResult) -> str` — §20.5 texts: `ok` singular/plural, failure = `"The model list URL failed the test. {tip}"` with the tip per kind (`unavailable`, `empty`, `failed` → the "other" tip; `invalid`/`insecure_scheme` never reach it).

- [ ] **Step 1: Write the failing tests**

- `test_test_validates_first_without_a_request` parametrized `invalid`/`insecure` (2): error shown, no probe thread started.
- `test_test_runs_off_the_ui_thread_and_posts_the_result`: `_start_probe_thread` recorder: no probe yet after `_onTest`; progress dialog created with the §20.5 text; running the target posts exactly one `wx.CallAfter` entry `(dialog._onProbeDone, (text, result))`; delivering it calls `done()`.
- `test_test_result_messages` parametrized (9) over `ProbeResult`: `ok-1` (`models=1` → `"The model list loaded. It offers 1 model."`), `ok-many` (`models=12` → `"… 12 models."`), `network`, `http_status` (detail `"404"` → `"… HTTP status 404. …"`), `not_a_list`, `no_models`, `disallowed_hosts`, `failed`, `unavailable` — exact §20.5 English; status `passed` only for `ok`.
- `test_a_result_for_changed_text_leaves_the_status_untested`: text changed between `_onTest` and delivery → message shown, `testStatus == "untested"`.
- `test_a_result_after_the_dialog_is_gone_does_nothing`: `dialog.alive = False` → no message, no `done()` call raises.
- `test_a_passed_test_then_ok_saves_without_a_warning`: real updater harness (Task 5) installed; `ok` probe delivered; `onOk` → saved, `_askSaveAnyway` never called.
- `test_the_test_strings_have_translator_comments_and_translations`: as in Task 12 for this task's msgids.

- [ ] **Step 2: Red:** `-k "test_test or result or passed_test or test_strings"` → `AttributeError: … '_onTest'` (15 failed).
- [ ] **Step 3: Implement** per Interfaces; `nvda.po` entries.
- [ ] **Step 4: Green:** `15 passed`; `msgfmt --check` exit 0; full suite **980 passed, 1 skipped**; prek Passed; `git diff --check` clean.
- [ ] **Step 5: Commit** — `feat: test a model list URL off the UI thread`.
- [ ] **Step 6: Mutant check:** set `passed` without the same-text check → `test_a_result_for_changed_text_leaves_the_status_untested` FAILS. Ledger.

---

### Task 14: Panel URL group replaces the editable field (R12, C18, C20, spec §20.1, §20.4)

**Files:**
- Modify: `dialogs.py` (`:311-324` field → group; delete `isValid` `:360-379`; delete the URL block of `onSave` `:407-413`; `_onCatalogChange` refreshes the box)
- Modify: `tests/test_coseeing_auth_nvda.py` (harness: `wx.lib.expando` module with `ExpandoTextCtrl` = `Widget`; `guiHelper.associateElements(a, b)` returning a marker that `Helper.addItem` accepts)
- Modify: `tests/test_catalog_settings_panel.py` (the 13 URL-field/`isValid`/URL-save tests at `:51-140` are replaced by the tests below)
- Modify: `addon/locale/zh_TW/LC_MESSAGES/nvda.po`

**Interfaces:**
- Consumes: Task 12 `CatalogUrlDialog` (`savedUrl`), Task 8 `_onCatalogChange`.
- Produces:
  - `self.catalogUrlBox` (read-only `ExpandoTextCtrl`, `style=wx.TE_READONLY`, `EVT_CHAR_HOOK` → `_onCatalogUrlBoxKey`), `self.catalogUrlChangeButton` (`_("Change...")`, `EVT_BUTTON` → `onChangeCatalogUrl`), inside `wx.StaticBoxSizer(wx.HORIZONTAL, self, label=_("Model list URL"))`, added last.
  - `_updateCatalogUrlBox() -> None` — `SetValue(settings.catalog_url() or _("No model list URL"))`.
  - `_onCatalogUrlBoxKey(evt)` — `WXK_RETURN` → `onChangeCatalogUrl(evt)`, else `evt.Skip()`.
  - `onChangeCatalogUrl(evt)` — `dialog = self._makeCatalogUrlDialog()` (seam: `CatalogUrlDialog(self, settings=self.settings, panel=self)`); `ShowModal() == wx.ID_OK and dialog.savedUrl is not None` → `catalog_updater.request_refresh(dialog.savedUrl)`; then `_updateCatalogUrlBox()`.
  - `self.catalogUrlCtrl` and `LLMSettingsPanel.isValid` no longer exist.

- [ ] **Step 1: Write the failing tests** (`tests/test_catalog_settings_panel.py`)

- `test_the_url_group_is_last_with_a_read_only_box_and_a_change_button` parametrized `stored` (`"http://localhost:8000"`) / `default` / `empty` (`""` → `"No model list URL"`) (3): the last two entries of `panel_added_controls` are the box and the button; the box has `TE_READONLY` style and the expected value; no `TextCtrl` labelled `"Model list URL:"` exists.
- `test_enter_in_the_box_and_the_button_open_the_dialog` parametrized `enter`/`button` (2): fake dialog class records construction (`settings is panel.settings`, `panel is panel`).
- `test_other_keys_in_the_box_are_skipped`: a non-Return key → `evt.skipped`, no dialog.
- `test_a_saved_url_refreshes_once_resets_the_backoff_and_updates_the_box`: real updater harness with one failure armed at count 3; fake dialog returning OK with `savedUrl = URL_B` (and saving it into `f.settings`) → one new thread for `URL_B`, a failure of it arms `60_000`; box shows `URL_B`.
- `test_a_cancelled_or_unsaved_dialog_refreshes_nothing` parametrized `cancel`/`ok-unsaved` (2): no thread, no `request_refresh`.
- `test_a_live_update_refreshes_the_url_box`: write a new URL into `f.settings`, emit a `CatalogChange` through the installed updater → box shows it.
- `test_settings_ok_no_longer_saves_or_refreshes_the_url`: `onSave` → `"catalog_url" not in f.settings`, no `request_refresh` queued.
- `test_the_panel_has_no_url_validation`: stored `"http://example.com"` → `panel.isValid() is True` (NVDA's default) and `"isValid" not in vars(LLMSettingsPanel)`.
- `test_the_url_group_strings_have_translator_comments_and_translations`: `"No model list URL"` → `"未設定模型清單網址"`, `"Change..."` → `"變更..."`, `"Model list URL"` reused.

- [ ] **Step 2: Red:** `tests/test_catalog_settings_panel.py -k "url_group or open_the_dialog or other_keys or saved_url or unsaved or url_box or no_longer or no_url_validation"` → `AttributeError: … 'catalogUrlBox'` (12 failed).
- [ ] **Step 3: Implement** per Interfaces; remove the 13 superseded tests; `nvda.po` entries (the obsolete `"Model list URL:"`-tooltip entries stay, they are still used by the dialog).
- [ ] **Step 4: Green:** the file passes; `msgfmt --check` exit 0; full suite **979 passed, 1 skipped**; prek Passed; `git diff --check` clean.
- [ ] **Step 5: Commit** — `feat: change the model list URL from a read-only box and a dialog`.
- [ ] **Step 6: Mutant check:** refresh with the stored URL even when the dialog was cancelled → `test_a_cancelled_or_unsaved_dialog_refreshes_nothing[cancel]` FAILS. Ledger.

---

### Task 15: Announcements, strings and translations (R3, R8, C11, C15, §11, §13)

**Files:**
- Modify: `dialogs.py` (`import ui`; announcement step in `_applyPendingUpdate`)
- Modify: `addon/locale/zh_TW/LC_MESSAGES/nvda.po`
- Test: `tests/test_catalog_panel_live.py`

**Interfaces:**
- Consumes: Tasks 4, 8–11; `CatalogUpdater` and `FakeScheduler`-style handles for the end-to-end test.
- Produces:
  - `_announcement_text(outcome: str) -> str` (module function, each string with its `# Translators:` comment from §13).
  - `_canAnnounce() -> bool` — `self.IsShown() and self.GetTopLevelParent().IsActive()`, any exception → `False`.
  - `_applyPendingUpdate` (after the rebuild, never while deferred): take and clear `_pendingAnnouncement`; when set and `_canAnnounce()`, `ui.message(_announcement_text(outcome))`.

- [ ] **Step 1: Write the failing tests**

- `test_announcements_table` parametrized (6) `(event, expected)`: `success-background` `change(True, "succeeded", False)` → `["Model list updated."]`; `success-user` `(True, "succeeded", True)` → same; `failure-panel-open` `(False, "failed", True)` → `["Model list update failed."]`; `failure-url-change` (same flags) → same; `failure-timer` `(False, "failed", False)` → `[]`; `failure-startup` (same) → `[]`. The recorder asserts `ui.message` got exactly one positional argument and no keywords.
- `test_no_announcement_when` parametrized (5): `refresh-start` `change(False, None)`; `d8-swap` `change(True, None)`; `hidden` (`panel.shown = False`, success); `inactive` (`panel.active = False`, success); `destroyed` (`panel.alive = False`, success) → `f.messages == []`.
- `test_only_the_latest_speakable_outcome_behind_a_deferral_is_spoken`: drop-down open; emit user failure, then success; close, `fire()` → `["Model list updated."]`.
- `test_a_background_failure_behind_a_deferral_keeps_the_pending_message`: drop-down open; user failure, then background failure; close, `fire()` → `["Model list update failed."]`.
- `test_a_description_change_alone_speaks_nothing` (R11): status none → failed with `change()` → `panelDescription` updated, `f.messages == []`.
- `test_the_new_strings_have_translator_comments_and_zh_tw_translations`: in `dialogs.py` the line before each `_("Model list updated.")`/`_("Model list update failed.")` is a `# Translators:` comment; `nvda.po` has `msgid "Model list updated."` → `msgstr "模型清單已更新。"` and `msgid "Model list update failed."` → `msgstr "模型清單更新失敗。"`.
- `test_the_panel_follows_a_real_updater_end_to_end`: real `CatalogUpdater` (as in Task 6, with a recording scheduler) whose startup fetch failed; `make_panel()` (R1 thread started); run it failing, deliver → `["Model list update failed."]`, status line "could not be loaded", 1 min timer; switch to the server body, fire the timer, run, deliver → messages end with `"Model list updated."`, `providerList.items` has every shipped group.

- [ ] **Step 2: Red:** `-k "announce or latest or keeps_the_pending or description_change or new_strings or end_to_end"` → `f.messages == []` / missing po entries (16 failed, except the silent rows that pass already: expect 10 failed, 6 passed).
- [ ] **Step 3: Implement** per Interfaces; add the two `nvda.po` entries (with the reference comment style of neighbouring entries).
- [ ] **Step 4: Green:** `16 passed`; `msgfmt --check -o /dev/null addon/locale/zh_TW/LC_MESSAGES/nvda.po` exit 0; full suite **995 passed, 1 skipped**; server **103 passed**; prek Passed; `git diff --check` clean.
- [ ] **Step 5: Commit** — `feat: announce live model list updates in the settings panel`.
- [ ] **Step 6: Mutant checks:** speak failures regardless of `user_initiated` → `test_announcements_table[failure-timer]` FAILS; drop the `IsActive()` test → `test_no_announcement_when[inactive]` FAILS. Ledger.
