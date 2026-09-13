# SDD ledger — plan: docs/superpowers/plans/2026-09-13-coseeing-auth-integration.md

## Setup

- Existing workspace is the user-provided `/workspace/WordBridge` checkout on `main`, with untracked `WordBridge(include-auth)/` and `addon/globalPlugins/WordBridge/package/coseeing_auth/`; preserve both as required by the plan.
- Ruling: work in the supplied checkout instead of creating a second worktree — the user explicitly scoped the implementation to this shared workspace and the plan explicitly requires preserving its untracked package sources; a separate worktree would omit those sources and risk implementing against the wrong bundle. Cost if wrong: changes remain on the supplied branch and can be moved later.
- Baseline command `python -m pytest ...` could not run because `python` is not installed; use `python3` where available and record environment limitations.

## Pre-flight plan scan

| Row | Shared files/interface or task self-consistency | Finding | Ruling |
|---|---|---|---|
| 1 | Task 1 ↔ Task 2: `lib/coseeing_auth.py`, `build_auth_config` / coordinator | Task 1 establishes config; Task 2 consumes the same module and package client API. No contradiction. | Proceed; spec is binding if package API differs. |
| 2 | Task 2 ↔ Task 3: `lib/coseeing_auth.py`, `CoseeingAuthSession` / NVDA adapter | Task 3 layers singleton and NVDA callbacks over Task 2 Future interface. No contradiction. | Proceed; keep core imports NVDA-free. |
| 3 | Task 3 ↔ Task 4: `lib/coseeing_auth.py`, `start_coseeing_auth`, `shutdown_coseeing_auth` | Task 4 consumes the exact public hooks and normalized channel. No contradiction. | Proceed. |
| 4 | Task 4 ↔ Task 5: `__init__.py`, request entry points / shared token hook | Task 4 owns lifecycle and notifications; Task 5 adds request token use. No contradiction. | Proceed; preserve error notification behavior. |
| 5 | Task 5 ↔ Task 6: request code/package / final artifact | Task 6 validates all earlier outputs and may make necessary corrections. No contradiction. | Proceed. |
| 6 | Task 1 self-consistency: requirements, config, bundle test/package | Files and tests match stated config contract; Windows validation may be unavailable. | Implement and explicitly report unavailable Windows validation. |
| 7 | Task 2 self-consistency: test harness, state machine, Future lifecycle | Required tests exercise the declared interface and callback rules. No contradiction found. | Proceed. |
| 8 | Task 3 self-consistency: adapter, UI, singleton hooks | Public hooks and adapter behavior align with Global Constraints. No contradiction found. | Proceed. |
| 9 | Task 4 self-consistency: plugin/dialog/config changes and tests | Stated removal of legacy credentials aligns with preserving other providers. No contradiction found. | Proceed. |
| 10 | Task 5 self-consistency: requests and tests | Token header rules and request cancellation are coherent. No contradiction found. | Proceed. |
| 11 | Task 6 self-consistency: integration/packaging | Final validation depends on platform tools; no product ambiguity. | Run available checks and record limitations. |

Task 1: fix round 1/5 (3 addressed, 1 open; commits 4b07079..b862052)
Task 1: fix round 2/5 (2 addressed, 2 open; commits b862052..f6e0c5d)
Task 1: fix round 3/5 (1 addressed, 1 open; commit f15b06e)
Task 1: fix round 4/5 (1 addressed, 0 open; commit e26a09b)
Task 1: complete (commits 3871cc9..e26a09b, review clean; Windows NVDA runtime acceptance pending)
Task 2: fix round 1/5 (4 addressed, 2 open; commits 2254e13..e93a46a)
Task 2: fix round 2/5 (3 addressed, 1 open; commits e93a46a..3cd2a3c)
Task 2: fix round 3/5 (3 addressed, 0 open but new shutdown hang; commits 3cd2a3c..5828bc2)
Task 2: fix round 4/5 (2 addressed, 1 open; commit fb02bc2)
Task 2: fix round 5/5 (2 addressed, 1 open; commit f91c9f5)
Task 2: parked — close scheduling failure can complete cleanup before a client created in an admitted request is closed and can leave that waiter pending. Ruling: carry the smallest synchronized close handoff fix into the next integration task because this is load-bearing for addon shutdown; cost if wrong: a narrow close race may remain until final review.
Task 2: complete (commits e26a09b..f91c9f5, 1 parked finding)
Task 3: fix round 1/5 (5 addressed, 3 open; commits fdfc273..4836d7b)
Task 3: fix round 2/5 (3 addressed, 0 open; commits 4836d7b..5273cc5)
Task 3: fix round 3/5 (2 addressed, 0 open; commit e8b4425)
Task 3: complete (commits f91c9f5..e8b4425, review clean)
Task 4: fix round 1/5 (1 addressed, 3 minor deferred; commit 5b78b57)
Task 4: complete (commits e8b4425..5b78b57, review clean; 3 minor deferred)

Task 6: complete (commits 918fccb, a564dfa, 41ac560; focused suite 86 passed, 1 skipped; full suite has 7 unrelated live/catalog failures; packaging and Windows/NVDA manual acceptance unavailable in this Linux environment)

## Task 6 verification ledger

- Focused regression: `python3 -m pytest tests/test_coseeing_auth.py tests/test_coseeing_auth_nvda.py tests/test_coseeing_requests.py tests/test_coseeing_auth_bundle.py tests/test_corrector_catalog_unittest.py tests/test_corrector_task_config.py tests/test_task_architecture_unittest.py -q` → `86 passed, 1 skipped in 0.83s`.
- Formatting: `git diff --check` → exit 0.
- Packaging: `scons` and `scons pot` → unavailable (`scons: command not found`); `python3 -m SCons` → `No module named SCons`.
- Translation tools: `msgfmt`, `xgettext`, and `gettext` absent from PATH.
- Source bundle audit: 9 `coseeing_auth` Python modules; both `py311-win32` and `py313-win_amd64` have all 10 required dependency roots, 10 METADATA files, 12 license files, and zero forbidden deployable secret files.
- Windows/NVDA: not run; no Windows NVDA or supported native runtime is available.
- Task 6 fix: updated the stale architecture test from 14 to the current 13 catalog entries; committed as `918fccb`.
- Full repository `python3 -m pytest -q`: 146 passed, 1 skipped, 7 unrelated failures (six live provider cost assertions and the stale Ollama filename assertion); no provider test or catalog file was changed.
- Pytest discovery hygiene: `testpaths = ["tests"]` committed as `41ac560`, preventing vendored dependency tests from changing import order.

## Final review fix wave

Commit `d416e55` addresses all six Important findings in one cohesive auth integration change:

1. Global shutdown now permanently rejects later singleton/token requests with `ClientClosedError`; queued callbacks cannot reopen auth.
2. Close scheduling failure keeps cleanup pending across an admitted request, closes any client created by that request, and completes all admitted waiters with `ClientClosedError`.
3. Proofreader and feedback requests serialize termination against POST, and queued result/error UI callbacks re-check termination before delivery.
4. Proofreader and feedback HTTP status, connection, timeout, malformed JSON, and missing-field failures use stable translated messages without raw exception or `KeyError` leakage.
5. A rotated token whose persistence fails is retained for the next call; retry saves the same token and returns the original authenticated access token without reauthentication.
6. Bundle validation asserts production import order puts the runtime-specific dependency directory ahead of addon imports.

Regression additions cover singleton resurrection, admitted close handoff, rotated-token retry, terminated proofreader work, proofreader status/connection/response failures, stable feedback failures, and production import ordering.

Previously deferred minors are now explicit: legacy `coseeing_username`/`coseeing_password` schema keys remain for settings compatibility but are unused; packaging/translation remains blocked by unavailable SCons/gettext tools; Windows native import and NVDA manual acceptance remain pending because this host is Linux. No additional review minor is undocumented.

Review-wave verification: focused command → `93 passed, 1 skipped in 0.85s`; full `python3 -m pytest -q` → `153 passed, 1 skipped, 7 failed` from existing live provider cost assertions and the stale Ollama filename assertion; compileall → exit 0; `git diff --check` → exit 0.

Final rerun after commit `742f4ac`: focused suite `93 passed, 1 skipped in 0.88s`; full suite `153 passed, 1 skipped, 7 failed in 23.94s`; compileall exit 0; `git diff --check` exit 0.
