# P0 fixes: report injection, shutdown blocking, and vendored dependency isolation

## Goal

Resolve the three P0 items shared by `review-claude-2.md` (T1–T3) and
`review-codex-2.md` (R01–R03):

1. **R01** — user text and model output can reach executable content in the
   correction report.
2. **R02** — an in-flight Coseeing HTTP request can block add-on termination,
   and background work can touch UI state after unload.
3. **R03** — the add-on mutates Python import state that the whole NVDA
   process shares.

R01 and R02 are specified here for implementation. R03 is specified here only
as a feasibility spike; its implementation design depends on the spike result
and will be written separately.

## Scope

All paths below are relative to `addon/globalPlugins/WordBridge/` unless noted.

In scope:

- `lib/viewHTML.py`, `web/templates/index.template` (R01)
- `__init__.py` — `_post_coseeing_request()`, `terminate()`, `_post_coseeing_ui()`,
  `correctTypo()` notification paths, `latest_action` (R02)
- A standalone spike script, run on Windows/NVDA, that writes no product code (R03)

Explicitly **not** in scope — these belong to R07/T14 and are deliberately left
alone so this batch stays independently verifiable:

- The single `JobController` and the UI dispatcher abstraction
- Removing the `sleep(5)` polling loop in `correctionAction()`
- Flattening the nested `script_correction` → `correctionAction` threads
- Moving the sound cue to `wx.Timer` / `wx.CallLater`

## Verification constraints

The author's development host is Linux; NVDA and Windows verification is
performed by the maintainer. Every requirement below is therefore marked either
**[auto]** (covered by a test runnable on Linux with the existing NVDA-stub
pattern in `tests/`) or **[manual]** (requires Windows/NVDA and must be reported
as "pending platform verification" until the maintainer confirms it).

## Design

### R01 — Report script/HTML injection

Two injection points were confirmed by reading the template. The Vue `{{ }}`
interpolation used for the main diff table (around `index.template:215`) is
auto-escaped and is **not** affected; it must keep working unchanged.

#### Python side — `lib/viewHTML.py`

`text2template()` builds `content_config` and substitutes `json.dumps(...)`
into an inline `<script>` at `index.template:7`. `json.dumps` does not encode
`<`, `>` or `&`, so a `</script>` sequence anywhere in the selected text or the
model output terminates the script element early.

After serialisation and before substitution, escape the following characters to
their JSON `\uXXXX` forms:

| Character | Escape |
| --- | --- |
| `<` | `<` |
| `>` | `>` |
| `&` | `&` |
| `U+2028` | ` ` |
| `U+2029` | ` ` |

These are valid JSON string escapes, so `JSON.parse` returns exactly the
original value. This deliberately keeps the inline `window.contentConfig`
assignment: switching to `<script type="application/json">` does not change how
the HTML parser terminates on `</script`, so it would not be a fix on its own.

Note that `text2template()` already decodes decimal and hexadecimal character
references before embedding. The escaping step must run **after** that decoding,
otherwise `&#60;script&#62;` would slip through.

#### Template side — `index.template`

`buildDescriptionList` composes HTML with template literals and passes the
result to SweetAlert's `html:` option. `chr` is a user character, so
`<img src=x onerror=...>` executes.

Rebuild it as DOM construction returning a `DocumentFragment`:

- All text assigned through `textContent`, never string concatenation.
- SweetAlert2 accepts an `HTMLElement` for `html:`, so `Swal.fire({ html: container })`
  needs no other change.
- Existing class names (`correction-dialog__entry`, `correction-dialog__text`,
  `correction-dialog__section`, `correction-dialog__label`, and the
  `--original` / `--corrected` modifiers) are preserved so styling is unchanged.
- `didRender: ariaHandler`, `customClass`, `confirmButtonText` and `width` are
  preserved so the accessibility behaviour is unchanged.

### R02 — Shutdown blocking and cross-thread state

#### Termination flag

Replace `self._coseeing_auth_terminated` (bool) and `self._coseeing_request_lock`
(`threading.RLock`) with a single `threading.Event`. Event get/set is atomic, so
the flag needs no lock, and `terminate()` can no longer be blocked by a thread
holding the lock across I/O.

The defensive `if not hasattr(self, "_coseeing_request_lock")` re-initialisation
in `_post_coseeing_request()` is removed along with the lock.

#### HTTP outside any lock

`_post_coseeing_request()` becomes: check the event → issue the request with no
lock held → check the event again on return and discard the response if
termination started meanwhile.

Both `timeout=120` call sites (`__init__.py:302` for `/proofreader` and
`__init__.py:497` for `/feedback`) change to an explicit
`(connect_timeout, read_timeout)` tuple. The read timeout **stays at 120
seconds**: a proofreading request is proxied to an LLM and shortening it would
be an unjustified functional regression. The connect timeout becomes 10 seconds
so an unreachable host fails fast.

Shutdown responsiveness comes from the 3-second termination budget below, not
from shortening the request timeout. Cancellation is cooperative: an
already-issued HTTP call is not aborted, it is abandoned, and a daemon worker
still blocked on it does not delay NVDA.

#### Unified UI dispatch

Add a single `_notify(message)` helper that always routes through
`wx.CallAfter` and checks the termination event twice — once before scheduling
and once inside the delivered callback.

This replaces `_post_coseeing_ui()` — all eleven of its call sites already pass
`ui.message`, so narrowing the signature from `(function, *args)` to `(message)`
loses nothing — and collapses the three repeated
`if execution_channel == "Coseeing": ... else: ui.message(...)` blocks in
`correctTypo()` into single calls. This change reduces the diff rather than
expanding it, and it removes the current situation where the local channel calls
`ui.message` directly from a worker thread while the Coseeing channel does not.

The same dispatch rule applies to the other two UI effects `correctTypo()`
performs from a worker thread: `api.copyToClip()` (`__init__.py:353`) and
`showReport()` (`__init__.py:371`, which calls `os.startfile`). Both move behind
the termination-checked `wx.CallAfter` path, so a task that finishes after
unload cannot write the clipboard or open a browser window.

#### `latest_action` single-writer

`latest_action` is currently a dict mutated by a worker thread and read by the
UI thread when the feedback dialog opens. A torn read sends mismatched
request/response/interaction_id to the Coseeing feedback endpoint, so this is a
correctness problem, not only a style problem.

The worker builds a frozen dataclass snapshot and hands it to the UI thread via
`wx.CallAfter(self._set_latest_action, snapshot)`. The UI thread becomes the
only writer, and the feedback script already reads on the UI thread, so the race
is removed without introducing a lock.

#### Bounded termination

Worker threads become `daemon=True`. `terminate()` sets the event, then waits a
bounded time (3 seconds) for workers and returns regardless of the outcome. It
must never join without a timeout.

### R03 — Vendored dependency isolation (spike only)

#### Established facts

- NVDA ships a **trimmed** `cryptography` in `library.zip`; parts `coseeing_auth`
  needs are absent. Using the host copy is therefore not an option.
- NVDA preloads that copy, so "import ours first" is not achievable — this is why
  `coseeing_auth.py:44-50` currently deletes the host's `cryptography.*` entries
  from `sys.modules`. That is the behaviour to remove.
- The bundle contains four native extensions: `_cffi_backend.cp313-win_amd64.pyd`,
  `charset_normalizer/cd` and `md`, and `cryptography/hazmat/bindings/_rust.pyd`
  (a PyO3 extension).

#### Narrowing observation

The only package that *must* be isolated is `cryptography`. The host's
`requests`, `urllib3`, `idna`, `certifi` and `charset_normalizer` are not
trimmed, and `authlib`, `joserfc` and `jwt` are pure Python and can be loaded
under a private prefix with no native concerns. This reduces the isolation
surface from eleven packages and four extensions to one package and one
extension, and makes it possible to stop touching the global `sys.path`
entirely.

The spike must confirm this premise before it is relied upon.

#### Candidate approaches

**A — Scoped `sys.modules` shadowing.** Snapshot the host's `cryptography*`
entries, swap in the bundle's, import the auth stack, then **restore** the
snapshot. Our authlib/joserfc already hold references to our copy; the host's
references are untouched. Low cost, but `cryptography` performs lazy imports,
so any submodule first touched *after* the restore would resolve to the trimmed
copy. Viability depends on whether an eager-import list is enumerable and stable.

**B — Private-prefix import sandbox.** Load `cryptography` (and the pure-Python
auth packages) under a `_wb_vendor.*` prefix via a `MetaPathFinder` active only
during bundle import, leaving every global `sys.modules` entry untouched.
Extension modules resolve their init function from the last name component
(`PyInit__rust`), so a prefixed name is theoretically loadable. The unknown is
whether PyO3 tolerates two instances of the same extension in one process.

**C — Helper process.** Run authentication in a separate CPython process
(NVDA's `python.exe` with `-I` plus the bundle directory), exchanging only the
access token over stdio. The main process never imports `cryptography` or
`authlib`, so the problem disappears at the source, and process termination
becomes a clean kill — which also simplifies R02's shutdown path and R17's state
machine. Highest cost, but its risk is predictable rather than discovered
mid-implementation.

#### Spike probes

The deliverable is one script the maintainer runs in NVDA's Python Console,
printing a structured report. It writes no product code and modifies no files.

**Probe 0 — host inventory.** Report the host `cryptography` version, file path,
and which submodules survive trimming; report `requests` and `urllib3` versions
against Authlib's minimums. This validates or refutes the narrowing observation.

**Probe 1 — extension double-load (decides B).** With the host copy already
loaded, load the bundle's `_rust.pyd` as
`_wb_vendor.cryptography.hazmat.bindings._rust` via
`spec_from_file_location` + `module_from_spec` + `exec_module`. The script must
distinguish three outcomes: `ImportError` for a missing init symbol, a PyO3
already-initialised error, and success. On success it must also confirm the
host's own `_rust` still works.

**Probe 2 — swap-and-restore leakage (decides A).** Using a fixed offline RS256
token and JWKS as fixtures — no real login required — perform: swap → verify
signature → restore → verify signature again. A second success means lazy
imports are not falling back to the trimmed copy. A failure must report which
submodule triggered it, which becomes A's eager-import list. The script must
also confirm that after restore, `cryptography.__file__` points back into NVDA's
`library.zip`.

#### Decision rule

| Probe result | Chosen approach |
| --- | --- |
| Probe 1 succeeds | **B** |
| Probe 1 fails, Probe 2 clean after restore | **A**, with the eager-import list and a regression test |
| Both fail | **C** |

## Error handling

- R01: escaping is unconditional and cannot fail; no new error path.
- R02: a response that arrives after termination is discarded silently, since
  there is no longer a UI to notify. A request that fails for any other reason
  keeps its existing user-facing message.
- R02: `terminate()` never raises. Exceeding the 3-second wait is logged at
  warning level and termination proceeds.
- R03: none — the spike only reports.

## Tests

R01:

1. **[auto]** No literal `<` or `>` appears between `<script>` and `</script>`
   in the output of `text2template()`.
2. **[auto]** Round trip: extracting and `json.loads`-ing the embedded JSON
   returns a value equal to the original diff, proving the escaping is lossless.
3. **[auto]** Payload table: `</script><script>alert(1)</script>`,
   `<img src=x onerror=alert(1)>`, single and double quotes, `&`, newlines,
   Traditional and Simplified Chinese, and numeric character references such as
   `&#31532;` (which `text2template` decodes before embedding).
4. **[manual]** Open a report generated from text containing the above payloads;
   the browser console shows no errors, no extra script runs, no event fires,
   and the text renders verbatim.

R02:

5. **[auto]** With a fake HTTP call that blocks indefinitely, `terminate()`
   returns within the 3-second budget and does not wait for the call.
6. **[auto]** A response arriving after termination produces no notification,
   no clipboard write and no report.
7. **[auto]** Interleaved admission and termination, and repeated `terminate()`
   calls, are safe.
8. **[auto]** `latest_action` observed from the UI thread is always internally
   consistent: `request`, `response` and `interaction_id` come from the same task.
9. **[manual]** Trigger a correction, immediately disable the add-on; NVDA
   completes the disable within roughly three seconds and the log contains no
   unhandled exception.

R03:

10. **[manual]** The spike script runs to completion in NVDA's Python Console
    and produces a report covering all three probes.

## Delivery order

1. R01 and R02 ship together. They are independent of each other, both carry
   Linux-runnable regression tests, and neither changes the architecture.
2. In parallel, the R03 spike script is delivered for the maintainer to run. It
   does not block step 1.
3. R03's implementation design is written once the probe results are in.

## Non-goals

- Any part of R07/T14 (job controller, UI dispatcher, removing the polling
  loop, nested threads, sound-cue timer).
- R13/T12, moving report output out of the install directory. R01 changes only
  how content is encoded, not where it is written.
- Changing `_rust`, cffi, or any vendored package's contents or versions.
- Reducing the bundle size (R15/T9).
- Any P1/P2/P3 item.
