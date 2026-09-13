# Task 2 report: Coseeing auth session state machine

## Result

Implemented the Future based `CoseeingAuthSession` coordinator and deterministic
test harness. The coordinator keeps guest/session/active/closed state on the UI
queue, merges overlapping callers, isolates caller cancellation, serializes
restore/login/token/refresh persistence, classifies recoverable refresh errors,
and performs client cleanup on a background thread.

## Files

- `addon/globalPlugins/WordBridge/lib/coseeing_auth.py`
  - Added `CoseeingAuthSession`.
  - Added lazy client creation, UI callback marshalling, waiter completion,
    guest remembrance/reconsideration, refresh rotation persistence, login and
    restore flows, error classification, and asynchronous close cleanup.
- `tests/coseeing_auth_helpers.py`
  - Added controllable `FakeAuth` and `AuthHarness`; no sleeps are used.
- `tests/test_coseeing_auth.py`
  - Added 15 deterministic tests covering guest behavior, restore and login,
    refresh rotation, current-session recovery, direct errors, persistence
    failures, overlap/cancellation, prompt cancellation, and close behavior.

Task 1 files and unrelated user files were not staged or modified by this task.

## Commits

- `25843a9` (`25843a92438bb14c8ea9e8668c8af6d40dd80f28`):
  `feat: coordinate Coseeing login and guest sessions`

This report is documentation for the implementation commit and is intentionally
not included in that commit.

## Commands and output

The exact brief command was attempted first:

```text
python -m pytest tests/test_coseeing_auth.py -q
/bin/bash: line 1: python: command not found
exit=127
```

The available interpreter was used for equivalent focused verification:

```text
python3 -m pytest tests/test_coseeing_auth.py -q
...............                                                          [100%]
15 passed in 0.18s
exit=0
```

```text
python3 -m pytest tests/test_coseeing_auth.py tests/test_coseeing_auth_bundle.py -q
.................s                                                       [100%]
17 passed, 1 skipped in 0.26s
exit=0
```

```text
python3 -m compileall -q addon/globalPlugins/WordBridge/lib/coseeing_auth.py tests/coseeing_auth_helpers.py tests/test_coseeing_auth.py
<no output>
exit=0
```

```text
git diff --check
<no output>
exit=0
```

## Concerns

- `python` is unavailable on PATH, so the required test commands ran as
  equivalent `python3` commands.
- `ruff` is unavailable on PATH (`ruff check ...` exited 127); no lint result
  is claimed.
- The combined bundle suite retains its existing one platform skip for the
  supplied Windows native dependency validation on this Linux host.

## Review fix report (2026-09-13)

### Findings addressed

- High: runtime dependency preparation now runs before importing
  `coseeing_auth.errors`; an isolated runtime import regression test verifies
  that a dependency available only through the selected runtime directory is
  found before the package initializer executes.
- High: `close()` now posts its state transition to the UI queue and uses a
  lock-protected close request as a guard while a UI operation is in progress.
  A client created after the close request is still cleaned up, and cleanup is
  started once on a background thread without waiting on the UI thread.
- Medium: waiter completion catches `InvalidStateError`, so cancellation races
  cannot prevent subsequent waiters from being completed.
- Medium: synchronous UI callback scheduling failures are caught and fail the
  active waiters while clearing the operation. Entry-point scheduling failures
  and synchronous client factory/submission failures are covered as well.
- Low: only `RestoreError(refresh_rejected)` and
  `TokenUnavailableError(refresh_rejected|refresh_unavailable)` enter recovery;
  `RestoreError(refresh_unavailable)` now propagates.
- Medium: deterministic tests now cover lazy client construction, two live
  overlapping waiters, paused-factory close, blocked asynchronous cleanup and
  cleanup thread identity, callback scheduler failure, sync factory/submission
  failures, and the import ordering contract.

### Fix commit

- `8657aec` (`8657aec3222e46137e78b4b8a059e7185a650caa`):
  `fix: harden Coseeing auth session coordination`

The original implementation and report commits remain:

- `25843a9`: `feat: coordinate Coseeing login and guest sessions`
- `2254e13`: `docs: report Coseeing auth session task`

### Verification commands and exact output

#### `python3 -m pytest tests/test_coseeing_auth.py tests/test_coseeing_auth_bundle.py -q`

```text
.........................s                                               [100%]
25 passed, 1 skipped in 0.32s
exit=0
```

#### `python3 -m compileall -q addon/globalPlugins/WordBridge/lib/coseeing_auth.py tests/coseeing_auth_helpers.py tests/test_coseeing_auth.py`

```text
<no output>
exit=0
```

#### `git diff --check`

```text
<no output>
exit=0
```

### Concerns

- The combined suite retains one expected Windows native dependency skip on
  this Linux host.
- The pre-existing modification to
  `addon/globalPlugins/WordBridge/package/coseeing-auth-dependencies.md` was
  left untouched and unstaged.

## Review fix round 5 report (2026-09-13)

### Findings addressed

- High: close scheduler fallback and persistent watcher scheduler fallback
  now use `_finish_handoff()`, which serializes terminalization under the
  state lock without invoking the UI-owned finisher from a background thread.
  Cleanup still starts exactly once for an existing client, and every waiter
  present at the handoff is completed.
- High: `_request()` now checks closing state, guest state, active state, and
  waiter registration while holding one lock. A caller cannot append after
  `_finish_handoff()` has drained the active waiters.
- Medium: cleanup Future completion is serialized and cancellation-safe when
  close/factory/cleanup completion races overlap.
- Added deterministic tests for the append-versus-drain interleaving, a
  background watcher callback scheduler failure, and overlapping waiters on
  existing-client close scheduler failure.

### Verification commands and exact output

#### `python3 -m pytest tests/test_coseeing_auth.py tests/test_coseeing_auth_bundle.py -q`

```text
.....................................s                                   [100%]
37 passed, 1 skipped in 0.37s
exit=0
```

#### `python3 -m compileall -q addon/globalPlugins/WordBridge/lib/coseeing_auth.py tests/coseeing_auth_helpers.py tests/test_coseeing_auth.py`

```text
<no output>
exit=0
```

#### `git diff --check`

```text
<no output>
exit=0
```

### Concerns

- The combined suite retains one expected Windows native dependency skip on
  this Linux host.
- `python` is unavailable on PATH; the requested checks used `python3`.
- The pre-existing modification to
  `addon/globalPlugins/WordBridge/package/coseeing-auth-dependencies.md` and
  untracked `WordBridge(include-auth)/` were left untouched.

## Review fix round 4 report (2026-09-13)

### Findings addressed

- When both close UI scheduling attempts fail with an existing client, active
  waiters now finish with `ClientClosedError`, the client is still closed once,
  and the cleanup Future reports the scheduler failure instead of suppressing
  it.
- When close scheduling fails during client creation and the factory raises,
  the active waiter receives the factory error and the cleanup Future completes
  instead of remaining pending.
- When all `_watch` UI-post attempts fail, the operation now drains its active
  waiters and clears `_active` and `_waiters` with the final scheduler error.
- Added deterministic regressions for all three boundaries.

### Verification commands and exact output

#### `python3 -m pytest tests/test_coseeing_auth.py tests/test_coseeing_auth_bundle.py -q`

```text
...................................s                                     [100%]
35 passed, 1 skipped in 0.37s
exit=0
```

#### `python3 -m compileall -q addon/globalPlugins/WordBridge/lib/coseeing_auth.py tests/coseeing_auth_helpers.py tests/test_coseeing_auth.py`

```text
<no output>
exit=0
```

#### `git diff --check`

```text
<no output>
exit=0
```

### Concerns

- The combined suite retains one expected Windows native dependency skip on
  this Linux host.
- `python` is unavailable on PATH; the requested checks used `python3`.
- The pre-existing modification to
  `addon/globalPlugins/WordBridge/package/coseeing-auth-dependencies.md` and
  untracked `WordBridge(include-auth)/` were left untouched.

## Review fix round 3 report (2026-09-13)

### Findings addressed

- High: client construction now tracks its in-progress UI operation. If close
  is requested while the factory is paused and the close callback cannot be
  scheduled, publication hands the client to the one-time cleanup owner before
  rejecting the operation, so the client is closed exactly once and cleanup
  completion reflects the real close call.
- High: close scheduling retries the UI close transition before reporting an
  unrecoverable scheduling error. An active waiter is completed by the queued
  UI transition before cleanup completes; cleanup is not reported successful
  merely because a client cleanup thread finished.
- Medium: watcher delivery retries scheduler-error delivery through the UI
  queue after a second scheduling failure. The test uses a deterministic
  repeated-failure schedule and verifies the final error delivery completes the
  waiter on the UI queue without callback-thread state mutation.
- Added deterministic tests for both close race paths and repeated watcher
  scheduler failure. All prior behavior tests remain green.

### Fix commit

- `24a3f62` (`24a3f624cc568b8b34b36c994eb9e3153ad2ab37`):
  `fix: harden Coseeing auth close handoff`

### Verification commands and exact output

#### `python3 -m pytest tests/test_coseeing_auth.py tests/test_coseeing_auth_bundle.py -q`

```text
................................s                                        [100%]
32 passed, 1 skipped in 0.33s
exit=0
```

#### `python3 -m compileall -q addon/globalPlugins/WordBridge/lib/coseeing_auth.py tests/coseeing_auth_helpers.py tests/test_coseeing_auth.py`

```text
<no output>
exit=0
```

#### `git diff --check`

```text
<no output>
exit=0
```

### Concerns

- The combined suite retains one expected Windows native dependency skip on
  this Linux host.
- The pre-existing modification to
  `addon/globalPlugins/WordBridge/package/coseeing-auth-dependencies.md` was
  left untouched and unstaged.

## Review fix round 2 report (2026-09-13)

### Findings addressed

- Close and client submission are now serialized. Client construction remains
  on the UI operation, and the final method submission is guarded against the
  atomic close request, so a paused factory cannot submit restore or login
  after close. A client created during that race is retained by the UI state
  and closed exactly once by the queued close transition.
- Close scheduling failures no longer fall back to mutating `_closed`,
  `_active`, or `_waiters` from the caller thread. The cleanup future reports
  the scheduler failure when no UI close transition can be posted.
- Auth Future callbacks never mutate coordinator state directly. Normal
  completion and scheduler-error delivery are both posted to the UI queue;
  scheduler errors are retried through a UI delivery callback.
- Cancellation-safe waiter completion remains protected against
  `InvalidStateError`, allowing later waiters to complete after a caller
  cancels.
- Error classification remains exact: `RestoreError(refresh_rejected)` and
  `TokenUnavailableError(refresh_rejected|refresh_unavailable)` recover;
  `RestoreError(refresh_unavailable)` propagates.
- Added deterministic tests for pending login Future cancellation, close
  scheduling failure, paused-factory shutdown, and both pointer-width runtime
  directory selections. Existing overlap, asynchronous cleanup, and import
  ordering tests continue to run.

### Fix commit

- `182597f` (`182597ff1cd265da4746081daf9ce3b5d0179f12`):
  `fix: serialize Coseeing auth shutdown`

### Verification commands and exact output

#### `python3 -m pytest tests/test_coseeing_auth.py tests/test_coseeing_auth_bundle.py -q`

```text
.............................s                                           [100%]
29 passed, 1 skipped in 0.36s
exit=0
```

#### `python3 -m compileall -q addon/globalPlugins/WordBridge/lib/coseeing_auth.py tests/coseeing_auth_helpers.py tests/test_coseeing_auth.py`

```text
<no output>
exit=0
```

#### `git diff --check`

```text
<no output>
exit=0
```

### Concerns

- The combined suite retains one expected Windows native dependency skip on
  this Linux host.
- The pre-existing modification to
  `addon/globalPlugins/WordBridge/package/coseeing-auth-dependencies.md` was
  left untouched and unstaged.
