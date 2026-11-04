# Remote catalog: background retry, panel-open retry and live panel update

- **Branch:** `feat/catalog-retry` (from `main` at `102b007`)
- **Workflow:** normal flow (DEVELOPMENT_WORKFLOW.md §3). Nothing here has to be
  byte-identical to a known build, so the complex flow (§4) does not apply.
- **Predecessor:** `docs/superpowers/specs/2026-11-04-remote-catalog-design.md`
  (cited below as "RC §n" / "RC Dn"). This spec **amends** it; §4.3 lists every
  section it changes. Its handoff record
  (`docs/superpowers/finish/2026-11-04-remote-catalog.md`) and review
  (`docs/superpowers/finish/2026-11-04-remote-catalog-review.md`) were read
  first (§3.0 item 1). Nothing in them is deferred into this feature except
  that the review's §七 item 5 (D9) is the decision superseded here.

Paths are relative to `addon/globalPlugins/WordBridge/` unless they start with
`tests/`, `docs/`, `server/` or `/workspace/nvda/`.

## 1. Problem

The remote catalog is fetched at exactly two moments:

1. once in the background at NVDA start: `GlobalPlugin.__init__` schedules
   `wx.CallAfter(self._start_catalog_fetch)` (`__init__.py:229`), which calls
   `self._catalog_updater.refresh(self.settings.catalog_url())`
   (`__init__.py:282-286`);
2. after the user changes the URL in the settings panel and saves
   (`dialogs.py:407-413`, `wx.CallAfter(catalog_updater.request_refresh, …)`).

A failed fetch only records `fetch=failed` (`catalog_updater.py:315-320`). It
is never retried until NVDA restarts or the URL changes. A user who starts NVDA
before the network is up (laptop resume, Wi-Fi still connecting, captive
portal) therefore keeps the bundled-only catalog (only Coseeing "default") or a
stale cache for the whole session. For a user whose stored selection is local
that also means the U7 Yes/No dialog on every correction (RC §12.5,
`__init__.py:288-300`, `:782-787`).

Opening the settings panel does not fetch either. The panel takes one catalog
and one status when it is built (`dialogs.py:132`, `:190`) and never changes
them (RC D9, RC §11.5; the docstring at `dialogs.py:64-69` says "the panel is
not refreshed afterwards"), so a list that arrives while the panel is open is
invisible until the panel is closed and reopened.

## 2. Goals

1. After a failed fetch, retry in the background with doubling waits (R5, R6, R10).
2. Opening the WordBridge settings panel after a failed fetch fetches at once
   (R1).
3. An open panel shows a newly installed catalog and the current status
   without being reopened, without moving focus (R2, R4).
4. While the panel is open, NVDA briefly says whether the update worked (R3).

## 3. Non-goals

- Periodic refresh after a **successful** fetch, and a manual refresh button.
  RC §3 keeps both out of scope; only failures are retried.
- Retrying when the URL is empty or invalid. Those start no fetch (RC D5,
  U9, `catalog_updater.py:125-128`, `:208`), so there is nothing to retry.
- Any speech when no WordBridge settings panel is open (R3). RC §6 "Fetching
  never announces anything" still holds for that case.
- Reacting to network-change notifications from Windows. The schedule is time
  based only.
- Changing the fetch itself (RC §8: limits, timeouts, TLS, allowlist), the
  cache (RC §10), the U7 dialog (RC §12.5, including the user's N2 decision
  that Yes always switches) or the server.
- Persisting the retry state across NVDA restarts or plugin reloads. Each
  `CatalogUpdater` starts with a fresh schedule.

## 4. Decisions

### 4.1 Decided by the user (2026-11-04)

| # | Decision |
| --- | --- |
| R1 | **Panel-open retry.** When the last fetch failed and no fetch is in progress, opening the WordBridge settings panel triggers a fetch. — Decided by the user (2026-11-04) |
| R2 | **Live panel update.** When a fetch completes while the settings panel is open, the Service Provider and model choices and the status line update in place, without reopening the panel. Focus is never moved. **This supersedes RC D9.** — Decided by the user (2026-11-04) |
| R3 | **Announcement.** On such an in-place update NVDA briefly says "Model list updated." (zh_TW 「模型清單已更新」); when the fetch fails, "Model list update failed." (zh_TW 「模型清單更新失敗」). Spoken only while the panel is open; exact conditions in §11. — Decided by the user (2026-11-04) |
| R4 | **Selection on a live update.** Keep the selection currently shown in the panel (even if unsaved) if it still exists in the new list; otherwise fall back to the stored selection; otherwise the default. How "currently shown" is read when the user has not touched the choices is §10.3 (finding F1). — Decided by the user (2026-11-04) |
| R5 | **Background retry with doubling.** After a failed fetch, retry after 1 minute, then 2, 4, 8, 16, 32 minutes. A module constant holds the maximum wait in minutes, hard-coded to 32. A wait equal to the maximum is still performed; when the next wait would exceed it, retrying stops (until NVDA restarts, the URL changes, or the panel-open retry). Any successful fetch stops retrying. At most 6 retries, within about 63 minutes. — Decided by the user (2026-11-04) |
| R6 | **Continuation (panel-open only, as amended by R10).** A fetch triggered by opening the panel (R1) that fails continues the existing retry interval; it does not reset to 1 minute. If background retrying had already stopped, no further automatic retries are scheduled. A URL change no longer falls under this rule (R10). — Decided by the user (2026-11-04) |
| R7 | **F1/C8 confirmed.** R4's "selection currently shown" counts only a selection the user made in this panel. An untouched panel shows the stored selection as resolved in the new list. — Decided by the user (2026-11-04) |
| R8 | **OQ1 → C.** "Model list update failed." is spoken only when a user-triggered fetch fails: the panel-open retry (R1), or a URL change saved in the settings panel. Failures of background retries (and of the startup fetch) are not spoken; they only update the status line. "Model list updated." is announced per R3/C11 whenever an in-place update happens while the panel is open and active, whatever started the fetch (C11's conditions are kept). — Decided by the user (2026-11-04) |
| R9 | **OQ2 → A.** The U7 / RC §12.5 dialog does not trigger a fetch; its behaviour is unchanged. — Decided by the user (2026-11-04) |
| R10 | **F6 → a URL change resets the backoff.** A saved URL change resets the retry step to the first wait (1 minute). Even if background retrying had already stopped, a failure for the new URL schedules the full 1, 2, 4, 8, 16, 32 minute sequence again. A panel-open (R1) fetch that fails still continues the existing interval and, if retrying had stopped, schedules nothing (R6 now applies to panel-open only). — Decided by the user (2026-11-04) |

### 4.2 Decided by orchestrator with the recommended default; user may override before merge

Each row is repeated with its reasoning in the section named. All of them are
marked `Decided by orchestrator with the recommended default; user may override
before merge`.

| # | Decision | Section |
| --- | --- | --- |
| C1 | Every fetch failure of the current generation schedules a retry: network/TLS/DNS errors and any exception (`remote_request_failed`), `remote_timeout`, every non-200 status including 3xx (`remote_http_status`), `remote_too_large`, `remote_malformed`, `remote_schema_version`, `remote_no_models` (including "every provider was disallowed"). A payload accepted with some providers dropped is a success. A cache write failure is a success. Stale and post-shutdown results schedule nothing. | §7.2 |
| C2 | Retries run whether or not a usable cache is installed (`source=cache` as well as `source=none`). | §7.2 |
| C3 | The retry timer is `wx.CallLater` on the main thread, injected as `schedule(delay_ms, callback)` like `ProgressCue` (`lib/progress_cue.py:10-11`). At most one handle exists. Every fetch start cancels it. Its callback re-checks shutdown, the generation it was armed for, and `fetch == failed`. No `threading.Timer`. | §7.3 |
| C4 | One step counter per updater. Every failed fetch of the current generation started by startup, the timer or the panel (R1) takes the next wait and advances the counter. A success resets it, and so does a URL change: every `refresh()` whose URL key differs from the live key (a saved URL change, R10), including a switch to an empty or invalid URL, cancels the timer and resets the counter and the "stopped" state. A new `CatalogUpdater` (NVDA start or plugin reload) starts at 0. A retry always fetches the updater's current URL at the moment it fires, never a URL captured when it was armed. (Amended for R10, 2026-11-04.) | §7.2, §7.4 |
| C5 | R1 runs once per panel instance, at the start of `makeSettings`, before the panel reads the catalog and status. "Last fetch failed" means `status().fetch == "failed"`; `running`, `succeeded`, `off` and `invalid` start nothing. A pending retry timer is cancelled and the fetch runs now. After retries stopped, R1 still fetches (R5). Re-activating the WordBridge category in the same dialog does not fetch again. | §8 |
| C6 | The panel learns of changes through a listener on the updater, called synchronously on the main thread after every state change (`refresh` start, D8 swap, fetch success, fetch failure). A failing listener is logged (type only) and never breaks the updater. | §9 |
| C7 | The open panel always mirrors the live catalog and status, including the RC D8 swap after Apply, and also while its category is hidden. The rebuild never calls `onPanelActivated()`, never calls `SetFocus()`, sets items only on a choice whose labels changed, and is deferred while a choice's drop-down list is open or while focus is in a control the rebuild would hide. | §10 |
| C8 | R4's "selection currently shown" counts only when the user changed the Service Provider or model choice in this panel. An untouched panel shows the stored selection resolved against the new catalog. The D12 baseline (`_storedSelection`, `_storedSelectionResolved`, `_restoredIndices`) is recomputed at every rebuild from the stored values re-read from config. The reading itself is confirmed by the user (R7). | §10.3 |
| C9 | A provider group that appears in the new catalog gets its account box created then, inserted after the existing boxes and placed in the Tab order after the model choice. A group that disappears keeps its (hidden) box and API key text, and `onSave` writes that text back unchanged. | §10.4 |
| C10 | The dropped-entries line ("N catalog entries could not be loaded") is updated live as well. It and the status line always exist from `makeSettings` on and are hidden when they have nothing to say. | §10.5 |
| C11 | Speech happens only for a fetch outcome of the current generation (not for a fetch start or the D8 swap), only when the panel is alive, its category is the one shown, and the settings dialog is the active window. A failure is spoken only when its fetch was user-initiated (R8). It is spoken after the rebuild (so after a deferral too), once, with `ui.message` at the default NORMAL priority. If several speakable outcomes queue up behind a deferral, only the latest is spoken; an outcome that is not speakable (a background failure) leaves the pending announcement as it is. | §11 |
| C12 | No new status-line strings. The six RC §13.3 lines stay as they are and are refreshed live. | §10.5 |
| C13 | Logging: one info line when a retry is scheduled (attempt number and wait), one when retrying stops, one when a panel-open fetch starts. Host only, never path, query or `str(error)` (RC D15). | §12 |
| C14 | A panel that is destroyed, or whose window is already gone, ignores and unregisters itself; `terminate()` stops the timer and drops all listeners through `catalog_updater.uninstall()`. | §14 |
| C15 | The two zh_TW strings end with a full-width period, like every other zh_TW sentence in `nvda.po` (for example `:206`, `:528`): 「模型清單已更新。」, 「模型清單更新失敗。」. | §13 |

### 4.3 What this changes in the predecessor spec

| RC item | Change |
| --- | --- |
| **D9** (RC §4 table, §11.5) | **Superseded by R2.** An open panel is rebuilt in place (§10). RC §11.5's reasons ("rebuilding would move focus and change list contents under a screen reader user") are addressed by C7: focus never moves, a drop-down that is open is never changed, and a control that has focus is never hidden. |
| **U3** fetch timing (RC §4) | Extended by R1, R5, R6 and R10. "No periodic refresh" still holds after a success; after a failure there are up to 6 timed retries per URL change (or per NVDA start), plus R1. |
| RC §3 non-goals | "A manual refresh button or periodic refresh" stays a non-goal with the R5 exception. "Live-refreshing an open settings panel (§11.5)" is removed. |
| **D7** threading (RC §11) | Unchanged for the fetch itself: one daemon thread per fetch, catalog swapped only on the main thread. New: the retry timer and all retry state live on the main thread (§7.3, §14). |
| **D8** URL change (RC §11.3) | `refresh()` also cancels the pending retry timer. A URL change resets the step counter, so a failure for the new URL waits 1 minute (R10, C4). A retry can never fetch the old URL (§7.4). |
| RC §6 | "Startup: no new speech … Fetching never announces anything" holds when no panel is open. With the panel open see §11. |
| RC §11.1 modules | `catalog_updater.py` gains the retry constants, the `schedule` injection, `close()`, listeners and module-level `add_listener`, `remove_listener`, `retry_on_panel_open` (§7–§9). |
| RC §11.3 fetch thread | `_apply` additionally advances or resets the retry schedule and notifies listeners (§7.2, §9). |
| RC §11.7 shutdown | `catalog_updater.uninstall()` first calls `CatalogUpdater.close()` (§14). |
| RC §12.3 D12 | Recomputed at every rebuild (C8, §10.3). The rule itself and the I1/N1 refinement at `dialogs.py:143-145` are unchanged. |
| RC §12.5 U7 | Unchanged; the dialog does not trigger a fetch (R9). A retry that succeeds while the U7 dialog is open behaves exactly like the first fetch did (Yes still switches, N2). Retries make the dialog stop appearing once a list arrives, without a restart. |
| RC §13.3 status line | Now live (C10, C12). The sentence "It reflects the status at the moment the panel opens" no longer holds; the docstring at `dialogs.py:64-69` changes with it. |
| RC §13.4 strings | Two new strings (§13). |
| RC §14 logging | Three new info lines (§12). |
| RC §17 tests | §15 adds tests; the tests listed in §15.4 change. |
| RC §21 acceptance 6 | "There is no periodic fetch" becomes "There is no fetch after a success except on a URL change; after a failure the schedule of §7 applies". |

## 5. Findings that bear on the user decisions

F1. **A literal R4 would break D12.** An untouched panel shows the *resolution*
of the stored selection, not something the user chose. Example: stored
`("gpt-x&OpenAI", "local")`, offline, no cache. The panel shows Coseeing
"default" (`dialogs.py:144-146`), and D12 keeps the stored value on an
untouched save (`dialogs.py:381-394`). If the fetch then succeeds while the
panel is open, a literal R4 keeps "Coseeing / default" on screen because it
still exists. The panel would then show a model the correction does not use.
Worse, the new D12 baseline (where the stored selection now resolves) differs
from what is shown, so OK would save Coseeing default over the user's local
model. C8 reads "currently shown" as "chosen by the user in this panel". For a
touched panel this is exactly R4. For an untouched panel it is R4's second
step, the stored selection. **Confirmed by the user (R7). — Decided by the user (2026-11-04)**

F2. **The provider-change refresh path cannot be reused.**
`onChangeProviderChoice` calls `self.onPanelActivated()`
(`dialogs.py:417-426`). NVDA's `SettingsPanel.onPanelActivated()` is
`self.Show()` (`/workspace/nvda/source/gui/settingsDialogs.py:419-424`). A
live update while another category is shown would make the hidden WordBridge
panel appear over it. The rebuild in §10 does not call it.

F3. **Account boxes exist only for the groups present at `makeSettings`.**
They are created in one loop over `self.catalog.provider_groups`
(`dialogs.py:215-239`), and `_refreshAccountInfo()` indexes
`accountGroupSizerMap[group]` for every group of the current catalog
(`dialogs.py:330-335`). With a catalog that gains a group this raises
`KeyError`. Creating boxes up front for every supported provider would avoid
creating controls later, but `SettingsRepository.api_key()` writes `""` into
the config for any provider it has not seen (`settings_repository.py:106-110`),
so it would add empty keys for providers the user never saw. C9 creates boxes
on demand instead.

F4. **The panel is created lazily, once per dialog.** NVDA builds a category's
panel the first time that category is selected and keeps it until the dialog
closes (`/workspace/nvda/source/gui/settingsDialogs.py:657-683`). Switching
categories only calls `onPanelDeactivated()`/`onPanelActivated()`, which hide
and show it (`:419-430`, `:730-747`). So "opening the panel" is `makeSettings`,
once per dialog (C5). NVDA+Alt+W opens the dialog directly on the WordBridge
category (`__init__.py:794-800`).

F5. **The settings dialog is not modal, and OK destroys it later.**
`popupSettingsDialog` calls `.Show()` (`/workspace/nvda/source/gui/__init__.py:265-281`),
and `SettingsDialog.onOk` calls `DestroyLater()`
(`/workspace/nvda/source/gui/settingsDialogs.py:313-319`). Main-loop callbacks,
including the updater's `_apply` and the deferred `request_refresh` from
`onSave` (`dialogs.py:413`), can therefore run between OK and the panel's
destruction. The listener guards (§14) cover this.

F6. ~~**R5's "until … the URL changes" and R6 agree.** A URL change performs one
fetch. If retrying had already stopped and that fetch fails, nothing more is
scheduled (R6). This also holds when the user corrects a mistyped URL after
retries stopped: the corrected URL gets one attempt, plus R1 on the next panel
open. Mentioned because it may surprise; it is the user's decision.~~
**Resolved by R10 (Decided by the user (2026-11-04)):** a saved URL change
resets the backoff, so a corrected URL whose fetch fails gets the full
1, 2, 4, 8, 16, 32 minute sequence even after retrying had stopped. R6 now
applies to the panel-open retry only.

F7. **wx's Windows `Choice` reports no "drop-down closed" event to Python.**
C7 therefore polls the native combo box's dropped state (§10.2). The Win32
message `CB_GETDROPPEDSTATE` is not defined anywhere in NVDA's source (grep of
`/workspace/nvda/source` is empty), so the constant is defined in
`dialogs.py`. NVDA's `winUser.sendMessage` exists
(`/workspace/nvda/source/winUser.py:597`). This works only on Windows and is a
manual item (§15.6).

None of these makes a user decision unworkable. The user confirmed C8 (R7)
and resolved F6 (R10).

## 6. What NVDA users hear and see

- **Offline at start, network back within the hour:** the full list appears
  by itself. The first retry is 1 minute after the failure, and the later
  retries 2, 4, 8, 16 and 32 minutes after the failure before each. A local-model
  user stops getting the U7 dialog once the list arrives. No speech unless the
  WordBridge settings panel is open.
- **Offline for more than about an hour:** retrying stops. The next attempts
  are on opening the WordBridge panel (one attempt), on changing the URL (the
  full schedule again if that fetch fails, R10), or after restarting NVDA.
- **Opening the WordBridge panel after a failure:** a fetch starts at once. The
  status line says the list is loading (RC §13.3 row 3) when no cache is in
  use. With a cache in use there is no status line while loading, as today.
- **A fetch finishes while the panel is open and shown, and the settings
  dialog is the active window:** the Service Provider and model choices, the
  API key box for the selected provider, the status line and the
  dropped-entries line update. Focus stays where it is. NVDA then says "Model
  list updated." without interrupting what it is already saying. A failure
  says "Model list update failed." only for a fetch the user caused: the one
  started by opening the panel, or by saving a new URL (R8). A failed
  background retry only updates the status line.
- **The drop-down list of a choice is open (Alt+Down):** nothing changes
  until it closes. Then the update happens and the message is spoken.
- **Typing in the API key field of a provider the new list no longer
  offers:** nothing changes until focus leaves that field.
- **Apply with a changed URL:** the list switches at once to the new URL's
  cache or to Coseeing only (RC D8), silently. When the fetch for the new URL
  finishes, the update and the message follow.

## 7. Retry schedule (R5, R6, R10, C1–C4)

### 7.1 Constants and injection

In `catalog_updater.py`:

```python
# The first wait after a failed fetch, and the longest wait still performed
# (R5). Waits double: 1, 2, 4, 8, 16, 32 minutes, then retrying stops.
RETRY_FIRST_WAIT_MINUTES = 1
RETRY_MAX_WAIT_MINUTES = 32
```

Both are read at use (module globals), so tests can monkeypatch them.

`CatalogUpdater.__init__` (`catalog_updater.py:142-172`) gains
`schedule=None`. `schedule(delay_ms, callback)` must return an object with
`Stop()`, the same contract as `ProgressCue` (`lib/progress_cue.py:10-11`),
which `wx.CallLater` meets. `None` disables retries (existing tests that build
an updater without it keep their behaviour). Production
(`__init__.py:269-280`) passes a new module-level seam in `__init__.py`:

```python
def _schedule_catalog_retry(delay_ms, callback):
	return wx.CallLater(delay_ms, callback)
```

It looks up `wx.CallLater` at call time, like `_catalog_http_get`
(`__init__.py:162-165`), so plugin tests can replace it. Plugin tests must not
see retry timers in `wx.timers`, which other tests count
(`tests/test_correction_progress_cue.py:171`).

### 7.2 State machine

New main-thread-only state on `CatalogUpdater`: `_retry_count` (int, 0),
`_retries_stopped` (bool, only for logging once), `_retry_timer` (handle or
`None`), `_current_url` (the URL given to the last `initial_catalog()` or
`refresh()`), `_user_initiated` (bool: whether the current generation's fetch
was started by R1 or by a URL change, read for the failure event, §9, R8),
`_closed` (bool), `_listeners` (list).

**On a failure** (`_apply` with `catalog is None`, after the existing
generation/shutdown check at `catalog_updater.py:301-302` and after recording
`fetch=failed`, `:315-320`):

```
if closed, shut down, or schedule is None: stop
wait = RETRY_FIRST_WAIT_MINUTES * 2 ** _retry_count
if wait > RETRY_MAX_WAIT_MINUTES:
    if not _retries_stopped: log "retries stopped"; _retries_stopped = True
    stop
_retry_count += 1
_retry_timer = schedule(wait * 60_000, <_on_retry_timer bound to the current generation>)
log "retry scheduled attempt=_retry_count delay=wait"
```

**On a success** (`_apply` installing a catalog, `:304-314`):
`_retry_count = 0`, `_retries_stopped = False`, cancel the timer (none can be
pending, since the fetch start cancelled it).

**On any fetch start or URL change** (`refresh()`, `:193-209`, whatever the
trigger): cancel the timer first. When the URL key differs from the live key
(a saved URL change, including to an empty or invalid URL), also reset
`_retry_count = 0` and `_retries_stopped = False` (R10). Otherwise (startup,
timer, R1) the counter is kept.

With the default constants and nothing but failures, the waits are 1, 2, 4, 8,
16, 32 minutes (6 retries, 63 minutes of waiting plus fetch time). The 7th
wait would be 64 > 32, so retrying stops. A wait equal to the maximum is
performed because the test is `>` (R5).

**Which failures (C1).** Every outcome that reaches `_apply` with an `issue`
for the current generation: all `remote_*` codes produced by
`fetch_payload()` (`catalog_updater.py:48-98`), `parse_remote_payload()`, the
acceptance check (`:256-274`), and an unexpected exception in the thread
(`:280-282`). Reasoning: the schedule is bounded (6 small requests in an hour),
and failures that look permanent can be transient. Finding 5 of the
predecessor is one example: a server not yet redeployed answers `GET /` with
404. A proxy error page is another: it can be a 200 with HTML, which shows up
as `remote_malformed`. Not retried: cache-write problems (the catalog is
installed, `:285-293`), stale or post-shutdown results (dropped at
`:283-284`, `:301-302`), empty or invalid URLs (no fetch, `:208`).

**Cache in use (C2).** `source=cache` with `fetch=failed` is retried like
`source=none`. The cache may be stale, and the cost is the same.

**Example of R6 continuation and the R10 reset.** Start at t=0 fails → retry
armed for t=1 min (count 1). The panel opens at t=0:30 → timer cancelled,
fetch now. It fails → wait 2 min (count 2), so the next retry is at about
t=2:30. The URL changes at t=2:00 → timer cancelled, counter reset (R10), D8
swap, fetch for the new URL. It fails → wait 1 min (count 1). After the 6th
scheduled wait has been used, a later timer or panel failure schedules
nothing (R6); a later URL change starts again at 1 minute (R10).

### 7.3 Timer mechanism (C3)

`wx.CallLater` runs its callback on the main thread from the wx event loop.
Starting, stopping and firing it therefore happen on the same thread as
`refresh()`, `_apply()` and the panel, and the retry state needs no lock.
Starting the next fetch is the same cheap work `refresh()` does today (validate,
start a thread), so a firing timer never blocks NVDA. WordBridge already
drives its progress cue with `wx.CallLater` on the main thread
(`__init__.py:735-747`). `threading.Timer` is rejected: it adds a thread that
lives up to 32 minutes, its callback would have to post back to the main
thread, and cancelling it races with that post.

Arming happens only inside `_apply`, which runs on the main thread
(`post_to_ui` is `GlobalPlugin._run_on_ui`, `__init__.py:426-436`). A timer
can still be delivered after `Stop()`, because wx queues the event before
`Stop()` is reached (`lib/progress_cue.py:42-47`). So the callback is guarded:

```
_on_retry_timer(armed_generation):
    _retry_timer = None   (only if it is still this handle)
    if closed or shutdown.is_set(): return
    with lock: current = (armed_generation == _generation and _fetch == FETCH_FAILED)
    if not current: return
    self.refresh(self._current_url)
```

`refresh()` increments the generation (`catalog_updater.py:196-198`), so a
stale delivery of an older handle always fails the generation check. At most
one handle exists: arming happens only after a failure, every fetch start
cancels first, and a failure can only follow a fetch start. Two fetches never
overlap through the retry or R1, because both require `fetch == failed`, which
is never true while the current generation's fetch is running. A URL change
during a running fetch keeps RC §11.3: the old thread is not joined and its
result is discarded.

### 7.4 URL changes and D8 (C4)

The callback fetches `_current_url`, not a captured URL. `_current_url` is set
by `initial_catalog()` and `refresh()`, which are also what set the D8
`_live_key` (`catalog_updater.py:186-189`, `:199-205`). Every `refresh()`
cancels the timer and bumps the generation. A retry can therefore never fetch a
URL other than the current one, and a timer armed for URL A is dead once the
user saves URL B.

| Situation | Timer | Counter | Fetch |
| --- | --- | --- | --- |
| Valid URL B saved while a retry for A is pending | cancelled | reset to 0 (R10) | B now; a failure waits 1 minute |
| Valid URL B saved after retrying for A had stopped | — | reset to 0, "stopped" cleared (R10) | B now; a failure starts the full schedule again |
| Empty or invalid URL saved | cancelled | reset to 0 (R10) | none (RC D5/U9) |
| Later a valid URL saved after that | — | reset to 0 (R10) | B now; a failure waits 1 minute |
| Panel-open retry (R1) | cancelled | kept | now; a failure takes the next wait, or nothing if retrying stopped (R6) |
| Any success | none pending | reset to 0 | — |

## 8. Panel-open retry (R1, C5)

`catalog_updater.retry_on_panel_open() -> bool`, a module function like
`request_refresh()` (`catalog_updater.py:337-341`). It is a no-op returning
`False` without an installed updater. It delegates to
`CatalogUpdater.retry_on_panel_open()`, on the main thread:

1. If closed or shut down: `False`.
2. Under the lock, read `_fetch`. Anything but `FETCH_FAILED` returns `False`.
   That covers `running` (a fetch is in progress, including the window between
   `initial_catalog()`, which already reports `running` for a valid URL
   (`:125-128`, `:189`), and the start of the startup thread), `succeeded`,
   `off` and `invalid`.
3. Log the panel line (§12), then `self.refresh(self._current_url)`. That
   cancels a pending timer, bumps the generation, sets `running` and starts the
   thread. Return `True`.

It runs whether or not retrying has stopped (R5). A pending timer does not
block it: the timer is cancelled and the fetch happens now. The fetch's failure
follows §7.2 (R6: the counter continues; nothing is armed if retrying had
stopped). Its fetch is user-initiated, so its failure is spoken (R8, §11).

**Where it is called.** The first statement of `LLMSettingsPanel.makeSettings`
(`dialogs.py:129`), before `registry.current()` (`:132`) and
`catalog_updater.status()` (`:190`). The panel then opens showing `running`,
for example "The model list is still loading…" when no cache is in use, and
not a stale "could not be loaded". `makeSettings` runs once per panel, i.e.
once per settings dialog (F4). `onPanelActivated` does not trigger R1: going
back and forth between categories must not fire fetches. The outcome reaches
the panel through §9.

## 9. Change notification (C6)

`CatalogUpdater` gains:

```python
@dataclass(frozen=True)
class CatalogChange:
	catalog_changed: bool        # the live catalog was replaced
	outcome: str | None          # "succeeded" / "failed" for a finished fetch, else None
	user_initiated: bool = False # the finished fetch was started by R1 or a URL change (R8)

def add_listener(self, listener) -> None      # main thread
def remove_listener(self, listener) -> None   # main thread; unknown listener is a no-op
def close(self) -> None                       # main thread; idempotent, never raises
```

Module functions `add_listener(listener)` and `remove_listener(listener)`
forward to the installed updater and are no-ops without one, like
`request_refresh()`/`status()` (`catalog_updater.py:337-347`).

Notifications are sent synchronously on the main thread, outside the lock,
after the state and the live catalog are updated. A listener can therefore
read `registry.current()` and `catalog_updater.status()`, the same sources
`makeSettings` reads (`dialogs.py:132`, `:190`).

| Where | Event |
| --- | --- |
| `refresh()`, after the status is set and after the D8 install if any (`:193-209`) | `CatalogChange(catalog_changed=<key changed>, outcome=None)` |
| `_apply()`, success, after `install` and the status update (`:304-314`) | `CatalogChange(True, "succeeded", <user_initiated>)` |
| `_apply()`, failure, after the status update (`:315-320`) | `CatalogChange(False, "failed", <user_initiated>)` |

`<user_initiated>` is `True` when the current generation's fetch was started
by `retry_on_panel_open()` or by a `refresh()` whose URL key changed (a saved
URL change), `False` for the startup fetch and timer retries (R8).
| `initial_catalog()` | none (no listener can exist yet) |

The updater iterates over a copy of the list. Each call is in its own
`try/except Exception`, logged as
`log.warning("WordBridge: catalog listener failed type=%s", type(error).__name__)`,
and the remaining listeners still run. `close()` sets `_closed`, cancels the
timer and clears the listeners.

## 10. Live panel update (R2, R4, C7–C10)

### 10.1 Wiring

In `makeSettings`, after the existing controls are built:

- `catalog_updater.add_listener(self._onCatalogChange)`.
- `self.Bind(wx.EVT_WINDOW_DESTROY, self._onPanelDestroy)`. Destroy events
  bubble up from children (NVDA guards the same way,
  `/workspace/nvda/source/gui/settingsDialogs.py:345-355`). So the handler acts
  only when the event object is the panel, removes the listener, stops the
  deferral timer (§10.2) and always calls `evt.Skip()`.

`_onCatalogChange(change)`:

1. If the panel's C++ object is gone (`not self`), call
   `catalog_updater.remove_listener(self._onCatalogChange)` and return.
2. If the change is speakable (`outcome == "succeeded"`, or
   `outcome == "failed"` and `change.user_initiated`, R8), store its outcome
   as `_pendingAnnouncement` (only the latest is kept, C11). A background
   failure leaves `_pendingAnnouncement` unchanged.
3. If `change.catalog_changed` is true, or a rebuild is already pending, set
   `_pendingRebuild = True`.
4. Update the status line now (§10.5). It is never focusable and never inside
   a drop-down.
5. Call `_applyPendingUpdate()`.

`_applyPendingUpdate()`: if `_mustDefer()` (§10.2), arm the deferral timer and
return. Otherwise, if `_pendingRebuild`, run the rebuild (§10.3–§10.5) inside
`self.Freeze()`/`self.Thaw()` and clear the flag. Then speak
`_pendingAnnouncement` if §11 allows it, and clear it.

For a failure the list does not change, so steps 4 and 5 update the line and
speak at once, unless a rebuild from an earlier success is still deferred.

### 10.2 Deferral: drop-down open or focus about to be hidden

`_mustDefer()` is true when a rebuild is pending and either:

- `providerList` or `modelList` has its drop-down list open. Seam
  `_isDroppedDown(choice)`; production:
  `winUser.sendMessage(choice.GetHandle(), CB_GETDROPPEDSTATE, 0, 0) != 0`
  with `CB_GETDROPPEDSTATE = 0x0157` defined in `dialogs.py` (F7). Any
  exception means "not dropped down". Changing the items of an open list would
  change the list under the user.
- `wx.Window.FindFocus()` is a control the rebuild would hide: the API key
  field of the currently shown provider box, or the Coseeing "clean" button
  (`dialogs.py:227-232`), when the provider group the rebuild selects
  (§10.3) differs from the one shown. Hiding the focused control would move
  focus.

While deferred, a panel-owned `wx.CallLater(DEFERRED_UPDATE_POLL_MS,
self._applyPendingUpdate)` with `DEFERRED_UPDATE_POLL_MS = 300` polls. At most
one is armed. It is stopped in `_onPanelDestroy`, and its callback returns at
once if `not self`. Focus in any other control (the choices themselves while
closed, Language, the URL field, buttons) does not defer: those controls are
not hidden and keep focus.

### 10.3 Choices and selection (R4, C8)

Inputs at rebuild time: `old = self.catalog`, `new = registry.current()`, the
indices shown (`providerList.GetSelection()`, `modelList.GetSelection()`), and
the stored selection re-read with `self.settings.stored_corrector_selection()`
(`settings_repository.py:73-78`). Re-reading matters after Apply, which has
already written a new stored value.

1. `touched = shown_indices != self._restoredIndices`. This is the same test
   `onSave` uses (`dialogs.py:385-386`).
2. If `touched`: `pick = old.get_item(*shown_indices)` as
   `(corrector_config_id, execution_channel)`. If
   `new.find_selection(*pick) != (-1, -1)`, select it (R4 step 1).
3. Otherwise: `SelectionState.restore(new, *stored)` (`lib/catalog/selection.py:51-59`),
   which is the stored selection if `new` offers it (with U6,
   `selection.py:26-29`), else `new.default_selection()` (R4 steps 2–3).
4. Recompute the D12 baseline with the same rule as `dialogs.py:143-147`:
   `_storedSelection = stored`;
   `resolved = self.settings.corrector_selection(catalog=new)`;
   `_storedSelectionResolved = resolved == stored or not stored[1]`;
   `_restoredIndices` = indices of `SelectionState.restore(new, *stored)`.
   Factor this into one helper used by `makeSettings` and the rebuild.
5. `self.catalog = new`; `self.selection = SelectionState(new, gi, mi)`.

Consequences:

- A kept user pick has indices different from the new baseline unless it
  equals it, so `onSave` saves it, as before the update.
- When the user's pick vanished, the panel falls back to the baseline and
  counts as untouched. D12 then protects an unresolved stored value again.
- An untouched panel of an offline local user (F1) moves from Coseeing
  "default" to the user's own model when the list arrives, and an untouched OK
  saves that same model.

**Controls.** `providerList.SetItems(labels)` only when the new group labels
(`_provider_group_label`, `dialogs.py:114-121`) differ from the current
ones. Same for `modelList` with `_display_labels` (`dialogs.py:102-111`).
Then `SetSelection` on both. Never `SetFocus()`. Never `onPanelActivated()`
(F2).

### 10.4 Account boxes (C9)

`_ensureAccountBox(group)`, used by `makeSettings` (replacing the loop body at
`dialogs.py:218-239`) and by the rebuild, creates the box for a group that has
none.

- In `makeSettings` it appends, as today.
- In a rebuild it inserts the new `StaticBoxSizer` into `settingsSizer` right
  after the last existing account box, so the visual order stays "model
  choice, account box, Language". It moves the new API key field (or the clean
  button) in the Tab order with `MoveAfterInTabOrder(self.modelList)`. Without
  that, a control created now would come after "Model list URL:" in the Tab
  order, because wx's Tab order is creation order.
- The box caption is updated with `GetStaticBox().SetLabel(...)` when the
  provider's label changes.

`_refreshAccountInfo()` (`dialogs.py:330-335`) iterates over
`accountGroupSizerMap`, not over the catalog's groups. It shows only the
selected group's box and hides all others, including boxes of groups that
disappeared. `onSave` keeps saving every field in `accountTextCtrlMap`
(`dialogs.py:404-405`), so a vanished provider's key is written back as it is.

`self._sendLayoutUpdatedEvent()` (`/workspace/nvda/source/gui/settingsDialogs.py:483-491`)
is sent only when the set of shown windows changed: the shown account box,
the status line or the dropped-entries line. NVDA's handler re-runs
`SetupScrolling()` on the container (`settingsDialogs.py:722-728`). With its
defaults that scrolls the view back to the top, so it is not done for an
update that changed only items.

### 10.5 Status line and dropped-entries line (C10, C12)

Both `wx.StaticText` lines are created in `makeSettings` at their current
positions (`dialogs.py:166-192`), always, so their place in the window order
(what NVDA+B and object navigation read) never changes. Each is hidden
(`settingsSizer.Show(line, False)`) when it has no text. Updating either sets
the label (`SetLabel`) and shows or hides it.

- Status line: `catalog_status_message(catalog_updater.status())`
  (`dialogs.py:64-92`), unchanged texts (C12). Updated on every
  notification. Its docstring drops "the panel is not refreshed afterwards".
- Dropped-entries line: the same count and the same two strings as
  `dialogs.py:166-185`, recomputed for the new catalog at each rebuild.

No new status text says that a retry is scheduled (C12). At panel open, R1
already turns a failure into `running`. A countdown would go stale, and the
existing failure lines stay true while a retry is pending.

## 11. Announcements (R3, C11)

Spoken from `_applyPendingUpdate()` (main thread) when **all** of these hold:

1. `_pendingAnnouncement` is `"succeeded"` or `"failed"`, i.e. a fetch of the
   current generation finished while this panel existed. Fetch starts, the D8
   swap after Apply, and R1's own start are silent. A failure is only stored
   for a user-initiated fetch (R1 or a saved URL change); failures of the
   startup fetch and of timer retries are never spoken (R8, Decided by the
   user (2026-11-04)).
2. The panel is alive and is the shown category: `self.IsShown()`. Inactive
   categories are hidden (`/workspace/nvda/source/gui/settingsDialogs.py:426-430`).
3. Its top-level dialog is the active window
   (`self.GetTopLevelParent().IsActive()`). Not when another application, the
   "Invalid configuration" message box (`settingsDialogs.py:449-470`) or the
   dictionary dialog (`dialogs.py:352-353`) is in front.
4. For `"succeeded"`, the rebuild has run, so the user can find the new items
   when they hear the message.

Text: `"succeeded"` → "Model list updated."; `"failed"` → "Model list update
failed." Call: `ui.message(text)`. `dialogs.py` gains `import ui`.

Priority: the default. `ui.message` passes `speechPriority=None`
(`/workspace/nvda/source/ui.py:166-178`), which `speech.speak` turns into
`Spri.NORMAL` (`/workspace/nvda/source/speech/speech.py:1126-1140`). NORMAL
is queued behind what NVDA is saying. `NOW` would interrupt it and `NEXT`
would push in ahead of queued speech (`/workspace/nvda/source/speech/priorities.py:18-26`).
NVDA itself still cancels queued speech on the next key press, which is
acceptable for a status message. `ui.message` also flashes the text on a
braille display (`ui.py:178`).

When a condition fails, the pending announcement is dropped, not kept for
later. A message about an update that happened while the user was elsewhere
would be confusing when they come back. The panel itself is already up to
date.

## 12. Logging (C13, RC D15)

New lines, info level, all through the updater's injected `log`:

| When | Line |
| --- | --- |
| A retry is armed (§7.2) | `WordBridge: catalog fetch retry scheduled attempt=%d delay=%dmin` |
| Retrying stops (once per stop, §7.2) | `WordBridge: catalog fetch retries stopped attempts=%d` |
| R1 starts a fetch (§8) | `WordBridge: catalog fetch started on settings panel open host=%s` (host from `redact_url`) |

The existing lines are unchanged: fetched / failed (`catalog_updater.py:310-320`),
source (`:240-246`). A timer retry then shows up as "scheduled", later
followed by "fetched" or "failed". No URL path or query, no `str(error)`, no
`exc_info`, no response body. The listener-failure warning (§9) logs the
exception type only. At most 8 new lines per hour of failures (6 scheduled, 1
stopped, plus R1 lines).

## 13. New strings and suggested zh_TW translations

Both strings are in `dialogs.py`, each with a `# Translators:` comment
(`tests/test_translator_comments.py`). The terms follow the existing
translations: "模型清單" (`addon/locale/zh_TW/LC_MESSAGES/nvda.po:533`),
"無法更新模型清單" (`nvda.po:528`), "失敗" (`nvda.po:241`).

| English | zh_TW | Translators comment (gist) |
| --- | --- | --- |
| `Model list updated.` | `模型清單已更新。` | Spoken when the open WordBridge settings panel has just shown a newly downloaded list of providers and models |
| `Model list update failed.` | `模型清單更新失敗。` | Spoken when downloading the list of providers and models failed while the WordBridge settings panel is open |

The zh_TW wording is the user's, with the full-width period added (C15).

## 14. Threads and lifecycle

- **Main thread only:** `refresh()`, `_apply()`, `retry_on_panel_open()`,
  `_on_retry_timer()`, `close()`, listener add/remove/notify, and the whole
  panel update. The lock keeps guarding only the generation, `_live_key`,
  `_source` and `_fetch` (`catalog_updater.py:166-209`, `:252-254`), because
  `status()` is read from the correction worker thread
  (`__init__.py:288-300`, `:556-562`). Retry state is not in `status()`.
- **Fetch thread:** unchanged (`catalog_updater.py:276-297`).
- **`terminate()`** sets `_shutdown` first (`__init__.py:376`), so the timer
  callback and `_apply` do nothing from then on. `catalog_updater.uninstall()`
  (`catalog_updater.py:332-334`), already called in `terminate()`'s `finally`
  in its own `try` (`__init__.py:411-414`), now calls `close()` on the
  installed updater before dropping it: the timer is stopped and listeners are
  cleared. Plugins are terminated before the GUI
  (`/workspace/nvda/source/core.py:584-585`), so `Stop()` still has a live wx.
  `close()` catches everything (R02 rule, `__init__.py:366-375`).
- **Panel closed while an update is delivered:** the panel unregisters in
  `_onPanelDestroy`. A notification that still reaches it after its C++ object
  is gone returns at step 1 of §10.1. Between OK and the deferred destruction
  (F5) a rebuild may still run. That is harmless: the dialog is no longer
  active, so nothing is spoken (§11 condition 3), and focus is not touched.
- **Plugin reload (NVDA+Ctrl+F3) with the settings dialog open:** the old
  updater is closed, so the open panel stops updating. A newly opened panel
  registers with the new updater.

## 15. Test plan

Hypothesis and mutmut are not dependencies of this repository, so
property-style coverage is written as table-driven tests (as in RC §17).
`_load_nvda_plugin` is imported at function scope, never at module scope
(project rule). No test performs a real HTTP request.

### 15.1 Updater unit tests (`tests/test_catalog_updater.py`, or a new `tests/test_catalog_retry.py`)

The existing `Harness` (`tests/test_catalog_updater.py:82-127`) gains a fake
scheduler. It records `(delay_ms, callback)` and returns handles with `Stop()`
and `fire()`, and it asserts on every call that no other handle is live and
unstopped ("no stacked timers").

- **Full schedule, table-driven over `RETRY_MAX_WAIT_MINUTES`** (monkeypatched):
  failures only, firing each timer and failing again. Expected delays in
  minutes: `32 → [1, 2, 4, 8, 16, 32]`; `0 → []`; `1 → [1]`; `3 → [1, 2]`;
  `40 → [1, 2, 4, 8, 16, 32]`. Each delay is in ms (`× 60_000`). After the
  last, a failure arms nothing and the "retries stopped" line is logged exactly
  once, even after further failures.
- **Equal to the maximum is performed:** with 32, the 6th delay is 32 min and
  it fires a fetch.
- **Success stops:** succeed at each step k (table k = 0…5). Then no timer is
  pending, and a later failure arms 1 min again.
- **Which failures retry (C1), one row per outcome:** 404, 500, 301, timeout
  (fake clock), `Content-Length` too large, streamed too large, non-JSON,
  `schema_version` 2, `remote_no_models`, every provider disallowed, raised
  `Exception` subclass, unexpected exception in `_fetch_and_build` → all arm a
  retry. Not retried: success with one provider dropped; success with a
  failing cache write (`RaisingStoreCache`/`FailingStoreCache`,
  `tests/test_catalog_updater.py:500-511`); a stale result; a result after
  shutdown.
- **Cache in use (C2):** `source=cache`, failure → retry armed.
- **The timer fetches the current URL:** arm for A; `refresh(B)` → the handle
  is stopped. Firing the stopped handle anyway (stale delivery) → no request,
  no thread. B fails → 1 minute (the URL change reset the count, R10). Firing
  it → the request goes to B (`Harness.requests`).
- **URL change to empty or invalid while pending:** stopped, no thread, no
  timer. A later valid URL failing waits 1 minute (R10).
- **R6 after stop (panel-open only):** exhaust the schedule. Then
  `retry_on_panel_open()` fetches and its failure arms nothing.
- **R10 after stop:** exhaust the schedule. Then `refresh(new URL)` fetches and
  its failure arms 1 minute; continuing to fail yields the full
  `[1, 2, 4, 8, 16, 32]` again and a second "retries stopped" line.
- **R10 reset mid-schedule:** three failures (next wait 8 min); `refresh(B)`
  fails → 1 min. `refresh` with the same key (startup, a timer) keeps the
  count.
- **R6 continuation:** 1 min armed; `retry_on_panel_open()` → stopped and
  fetched; failure → 2 min.
- **Never two fetches:** `retry_on_panel_open()` while `running` → `False`,
  no thread. A timer callback whose generation is stale, or while `running`,
  starts nothing.
- **Shutdown and close:** `shutdown.set()` then fire → nothing. `close()` →
  the handle is stopped, listeners cleared, idempotent. `_apply` failure after
  `close()` arms nothing. `schedule=None` → no retries (existing tests
  unchanged).
- **Logs:** scheduled lines carry `attempt` and `delay` only. The panel line
  carries the host only. A capture shows no path, query or `str(error)` (extend
  `test_logs_never_contain_path_query_or_error_text`, `:352`).
- **Listeners:** the event table of §9 (refresh with same key / changed key /
  empty URL, success, failure); a raising listener is logged by type and the
  next one still runs; `remove_listener` of an unknown listener is a no-op;
  module `add_listener`/`remove_listener`/`retry_on_panel_open` are no-ops
  without an updater.
- **`retry_on_panel_open()` conditions table:** `failed` → `True` + thread;
  `failed` with a pending timer → timer stopped + thread; `running`,
  `succeeded`, `off`, `invalid` → `False`, nothing.

### 15.2 Panel tests (NVDA-stubbed, `tests/test_catalog_settings_panel.py`)

The widget stubs (`_install_settings_panel_widget_stubs`, `tests/test_coseeing_auth_nvda.py:885-979`) gain `Show`,
`Hide`, `IsShown`, `SetLabel`, `GetHandle`, `MoveAfterInTabOrder`, `Freeze`,
`Thaw`, `Bind` on the panel, a recorded `SetFocus`, a `FindFocus` seam, sizer
`Insert`, and a recording `ui.message`. `_isDroppedDown` and the
active-dialog check are seams the tests set.

- **R1 at open:** status `failed` (`source=none`) → `retry_on_panel_open`
  called before the status is read, and the status line shows the "still
  loading" row. Status `succeeded` → not called.
- **Selection (R4/C8), table-driven:** each row gives the old catalog, the new
  catalog, the stored selection, whether the user touched the choices, and the
  expected shown `(id, channel)` and baseline:
  - fresh install, untouched → default;
  - stored local unresolved (bundled-only) → untouched → the stored local model (F1);
  - touched pick present in new → kept;
  - touched pick absent, stored present → stored;
  - touched pick absent, stored absent → default;
  - stored Coseeing non-default (U6) → Coseeing default.
- **D12 after a rebuild:** stored local model unresolved in both old and new,
  untouched, `onSave` → stored unchanged. F1 row → `onSave` writes the same
  stored value (no Coseeing default). Touched row → `onSave` saves the pick.
- **Focus never moves:** no `SetFocus` on any control and no
  `onPanelActivated`/`Show` on the panel during a rebuild. With the panel
  hidden (another category), a rebuild runs and the panel stays hidden.
- **Deferral:** drop-down open → items unchanged, a 300 ms poll armed. After
  "closing" and firing → items updated, one announcement. Focus in the shown
  API key field while the selected group changes → deferred. Focus in that
  field while the group stays → not deferred.
- **Account boxes (C9):** a new group's box is created and placed after the
  model choice in the Tab order (`MoveAfterInTabOrder(modelList)`). Existing
  fields keep typed values. A vanished group's box is hidden and its key saved
  unchanged. `_refreshAccountInfo` raises no `KeyError` for any group change.
- **Lines (C10):** each RC §13.3 row updates live. The dropped-entries count
  follows the new catalog. Both lines exist from `makeSettings` and are hidden
  when empty. The layout event is sent only when visibility changed.
- **Announcements (C11, R8):** success → `ui.message("Model list updated.")`,
  whatever started the fetch. A user-initiated failure (R1, saved URL change)
  → `ui.message("Model list update failed.")`. Each is called with the text
  only (default priority). Silent for: refresh start, D8 swap after Apply,
  a timer-retry or startup failure, hidden category, inactive dialog, panel
  destroyed. Two speakable outcomes behind one deferral → only the latest is
  spoken; a background failure behind a deferral leaves the pending one.
- **Lifecycle:** a destroy event from a child does not unregister; one from
  the panel does, and stops the poll. A notification after the panel's object
  is gone unregisters and does nothing else.
- **Existing tests that change:**
  `test_no_status_line_when_the_list_is_fresh`
  (`tests/test_catalog_settings_panel.py:184-188`) and
  `test_the_dropped_entries_line_is_silent_for_the_shipped_overlay` (`:191-194`)
  assert a hidden line instead of `None`. The `catalogIssuesText is None`
  assertions at `tests/test_coseeing_auth_nvda.py:1008`, `:1047` change the
  same way. `test_the_status_line_is_shown_after_…` (`:172-181`) keeps its
  order assertion.

### 15.3 Plugin wiring tests (`tests/test_catalog_plugin_wiring.py` / `tests/test_coseeing_auth_nvda.py`)

- The production updater gets `schedule=_schedule_catalog_retry`. A failed
  startup fetch (fake `http_get` raising) arms one timer through the seam.
  `terminate()` stops it, and firing it afterwards does nothing.
  `catalog_updater.uninstall()` closes the updater even if an earlier
  `terminate()` step raises.
- Plugin tests that count `wx.timers` (`tests/test_correction_progress_cue.py:171`)
  are unaffected, because the seam is replaced in the harness.
- A retry that succeeds makes `_needs_catalog_choice()` false for a stored
  local user (`__init__.py:288-300`): the next NVDA+Alt+O starts the
  correction without the U7 dialog.
- R9: showing the U7 dialog starts no fetch and arms no timer (no new thread,
  no `retry_on_panel_open` call), while `fetch == failed`.

### 15.4 Translations

`nvda.po` gains the two entries of §13. `msgfmt --check` passes.
`tests/test_translator_comments.py` passes.

### 15.5 What is not covered on Linux

Real wx timers, the native combo box's dropped state, Tab order and window
order on Windows, NVDA's speech queue and braille flash, and real network
recovery. See §15.6.

### 15.6 Windows/NVDA manual checks

Each item uses an installed add-on built from the branch. A local server
(`http://localhost:8000`) that can be stopped and started stands in for the
network.

1. Server stopped, no cache, NVDA started: the log shows the failure, then
   `retry scheduled attempt=1 delay=1min`. Start the server within the minute:
   about a minute after the failure the log shows "catalog fetched". With a
   stored local model, NVDA+Alt+O then corrects without the U7 dialog and
   without restarting NVDA.
2. Server kept stopped: attempts 1–6 with delays 1, 2, 4, 8, 16, 32, then
   `retries stopped attempts=6` about 63 minutes after start. The server log
   shows no further requests.
3. After item 2, open the WordBridge panel: one request, the status line says
   loading (no cache) and then failed. NVDA says "Model list update failed."
   No further timed requests (R6).
3a. After item 2, save a different URL (for example `http://localhost:8001`,
   also stopped): the log shows `retry scheduled attempt=1 delay=1min` again
   and the full schedule follows (R10). NVDA says "Model list update failed."
   once for the saved change, and nothing for the timed retries (R8).
4. Panel open with focus on "Service Provider" (closed) while the server comes
   back: the providers appear, the selected value stays, focus stays, and NVDA
   says "Model list updated." once without cutting off its current speech.
   Record what NVDA reads, if anything, when the items are replaced.
5. Same with the drop-down open (Alt+Down): the list does not change while it
   is open. After Escape/Enter the update and the message follow.
6. Focus in an API key field of a provider the new list drops: nothing changes
   until Tab moves on, then the box changes without focus jumping.
7. After providers appear: Tab order is Service Provider, model, the selected
   provider's API key, Language, … , "Model list URL:" last. NVDA+B reads the
   status line only when it is visible.
8. WordBridge panel open but another category shown, or another application
   in front, when the fetch finishes: no speech. Going back shows the new list.
9. Apply with a changed URL: the list switches silently. When the fetch
   finishes, the update and the message follow. OK with a changed URL: no
   message after the dialog closes.
10. Exit NVDA while a retry is pending: NVDA exits promptly, with no WordBridge
    errors in the log.
11. Low vision: a live update that only changes items does not scroll the
    panel. One that changes the shown account box re-lays out the panel as
    choosing a provider does.
12. Braille: the two messages flash on the display.

## 16. Open questions (answered by the user, 2026-11-04)

### OQ1. Should a repeated failure be announced each time while the panel stays open?

With the panel left open on a failing network, timed retries finish at about
1, 3, 7, 15, 31 and 63 minutes, and each says "Model list update failed."
(R3, C11).

- **A. Every failure is announced** (R3 as written). Predictable. At most 6
  extra messages an hour, only while the panel is open, shown and active.
- **B. Only the first failure after the panel opened, or after a success,
  is announced.** Later failures only refresh the status line. Quieter, but a
  failure is sometimes spoken and sometimes not.
- **C. Only failures of fetches the user caused** (R1 at open, Apply with a
  new URL). Timed retries are silent.

**Recommended: A.** It is what R3 says, and the number is small and bounded.

**Answer: C** (R8). — Decided by the user (2026-11-04)

### OQ2. Should a correction that hits the U7 dialog also trigger an immediate fetch?

A local-model user without a list presses NVDA+Alt+O and gets the Yes/No
dialog (RC §12.5). R1 covers the settings panel only.

- **A. No** (this spec). The timed retries and R1 are the only extra
  triggers. The U7 dialog keeps answering only the question it asks (N2).
- **B. Yes, as with R1:** when `fetch == failed`, the dialog's appearance
  starts a fetch. The dialog itself is unchanged, and a later NVDA+Alt+O may
  find the list.

**Answer: A** (R9). — Decided by the user (2026-11-04)

**Recommended: A.** It keeps the dialog's behaviour, which the user decided
twice (U7, N2), free of a race, and the background schedule already retries
within a minute.

## 17. Verification and baseline

Baseline at `102b007` in `/workspace/WordBridge-catalog-retry` (measured
2026-11-04):

```bash
cd /workspace/WordBridge-catalog-retry && /tmp/claude-0/-workspace-WordBridge/9af55a63-c255-4088-9b3c-fe363afb236f/scratchpad/testvenv/bin/python -m pytest -q --ignore-glob='tests/test_integration_*' tests
# 805 passed, 1 skipped
cd /workspace/WordBridge-catalog-retry/server && /workspace/WordBridge/server/.venv/bin/python -m pytest -q
# 103 passed
cd /workspace/WordBridge-catalog-retry && prek run --all-files   # 3/3 Passed
git diff --check
msgfmt --check -o /dev/null addon/locale/zh_TW/LC_MESSAGES/nvda.po
```

- `tests/test_integration_*.py` call paid live APIs. They are never run.
- The server is not changed. Its suite is run only to show it is untouched.
- Linux tests cover only injected boundaries (§15.5).

## 18. Risks

- **Native list replacement under a screen reader.** Replacing a focused
  closed combo box's items may make NVDA re-read its value. Mitigations:
  items are set only when labels differ, the selection is restored, and focus
  is never moved. Verified by §15.6 item 4.
- **Polling the drop-down state** relies on a Win32 message (F7). If it
  misreports, the worst case is changing items while the list is open (no
  focus loss), seen in §15.6 item 5.
- **Tab order of late-created controls** depends on `MoveAfterInTabOrder`
  (§10.4). §15.6 item 7 checks it.
- **Chattiness** is bounded by §7 and §11 (OQ1).
- **Load on the server** from many add-ons retrying at once after an outage:
  6 small `GET /` per add-on over an hour, spread by each add-on's own start
  time. No jitter is added. The `GET /` payload is about 6 KB and served from
  memory (RC §15.1).

## 19. Acceptance criteria

1. After a failed fetch with a valid URL, retries follow 1, 2, 4, 8, 16, 32
   minutes and then stop. Any success stops them. At most one timer exists at
   any time, and none after `terminate()`.
2. A retry never fetches a URL other than the current one, and never starts
   while a fetch for the current generation is running.
3. Opening the WordBridge panel when the last fetch failed starts exactly one
   fetch. In any other state it starts none.
4. Panel-open failures continue the step counter and, after retrying
   stopped, schedule nothing (R6). A saved URL change resets the counter, so
   its failure waits 1 minute even after retrying stopped (R10).
5. A fetch finishing while the panel is open updates the choices, the account
   box, the status line and the dropped-entries line without any `SetFocus`,
   without showing a hidden panel, and never while a drop-down is open.
6. The selection follows R4 as read by C8, and D12 still protects an
   unresolved stored selection on an untouched save.
7. "Model list updated." / "Model list update failed." are spoken only under
   §11's conditions, at the default priority; a failure only for a
   user-initiated fetch (R8).
8. No log line contains a URL path or query, or exception text.
9. The full non-integration suites are green at every commit. prek passes.
   `git diff --check` is clean. `msgfmt --check` passes.
