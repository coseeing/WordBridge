# P1/P2 fixes: correctness defects, packaging weight, and report location

## Goal

Close the P1 and P2 items of `review-claude-2.md` (T4–T9, T11, T12), taking in
the stricter acceptance conditions that `review-codex-2.md` states for the same
defects (R04, R05, R06, R11, R13, R15, R16) wherever those conditions do not
depend on the P3 refactors.

| ID | Task | codex counterpart |
| --- | --- | --- |
| T4 | Re-correction loop segment/history misalignment | R04 |
| T5 | Traditional/simplified tag never fires | R05 |
| T6 | `assert` used as flow control | R05 |
| T7 | Three shadowed / unextractable translations | R11 |
| T8 | Boundary conditions and assorted defects | R06, R18 (partial) |
| T9 | Packaging weight and start-up cost | R15, R16 |
| T11 | Residual settings and naming inconsistency | R14 (partial) |
| T12 | Move report output out of the install directory | R13 |

**T10 (CI test and static-analysis gates) is explicitly excluded from this
batch** by the maintainer's decision. The packaging-content test that
`review-claude-2.md` lists under both T9-4 and T10-4 is still written here, so
that a later CI task can adopt it unchanged.

## Scope

All add-on paths below are relative to `addon/globalPlugins/WordBridge/` unless
noted otherwise.

In scope:

- `lib/tasks/typo/workflow.py`, `lib/tasks/concurrency.py` (T4)
- `lib/tasks/typo/utils.py`, `lib/text/chinese.py` (T5, T6)
- `lib/llm/provider.py`, `configManager.py`, `lib/llm/executor.py` (T7)
- `lib/tasks/typo/text_policy.py`, `__init__.py` (T8)
- `lib/tasks/typo/chinese_dictionary.py`, `lib/tasks/typo/data/`, `buildVars.py`,
  `workspace/evals/generate_zhuyin_dataset.py` (T9)
- `setting/provider/*.json`, `lib/llm/provider.py`, `__init__.py` config spec (T11)
- `__init__.py` `showReport()`, new `lib/report.py`, new `lib/paths.py`,
  `dictionary/__init__.py` (T12)

Explicitly **not** in scope — all P3, deliberately left alone so this batch stays
independently verifiable:

- The single `JobController` and the UI dispatcher abstraction (R07/T14)
- The `WordBridgeError` domain hierarchy (R09/T15)
- `CorrectionService` and the local/Coseeing backend contract (R10/T13)
- Concurrency limits, deadlines and metrics aggregation (R12/T16)
- Settings catalog / selection-state decoupling and import-time side effects
  (R14/T17) — including the `os.makedirs` at import in `dictionary/__init__.py`
- The `coseeing_auth` state machine (R17/T18)
- CI and static-analysis gates (T10)

The report front end is not touched. `analyze_diff` tags are repaired as data
only; rendering them in the report is a separate feature decision.

## Verification constraints

The development host is Linux; Windows and NVDA verification is performed by the
maintainer. Every requirement below is marked either **[auto]** (covered by a
test runnable on this host with the existing `tests/` NVDA-stub pattern) or
**[manual]** (requires Windows/NVDA and must be reported as "pending platform
verification" until the maintainer confirms it).

Measured baseline on this host, 2026-09-21, `python3 -m pytest -q -m "not integration"`:
238 passed, 1 skipped, 16 deselected, **2 failed**. Both failures pre-date this
batch:

- `tests/test_provider_naming.py::test_provider_config_filenames_match_catalog` —
  `ollama.json` is absent from the expected set. Fixed here under T11.
- `tests/test_coseeing_auth_bundle.py::test_sso_configuration_matches_approved_demo` —
  expects `client_id == "a11yvillage"`, while `lib/coseeing_auth.py:140` sets
  `client_id="wordbridge"`. The maintainer confirmed the product value is
  correct; the test expectation is updated here.

The batch is complete only when this command reports zero failures.

## Design

### T4 — Re-correction loop segment/history misalignment

#### Established facts

Read from `lib/tasks/typo/workflow.py:36-72` and `lib/tasks/concurrency.py:5-32`:

- `segments_to_recorrect` and `segments_revised` always have the same length.
  `get_segments_to_recorrect()` emits `""` for a segment with no flagged typo,
  and `_execute_segment("")` returns immediately without an API call because
  `TypoTextPolicy.has_target_language("")` is False. Empty segments therefore
  cost nothing and must keep costing nothing.
- The misalignment is confined to `recorrection_history`. It is built once, in
  the first round, sized to that round's segment count L₁. Every later round
  re-segments `text_corrected_revised` and may produce a different count L₂.
- `parallel_map` receives `iterable` of length L₂ and `iterable_kwargs` of
  length L₁ and pairs them with `zip`, which truncates to `min(L₁, L₂)`.

The two failure modes differ from the one `review-claude-2.md` describes:

- **L₂ > L₁** — the tail tasks are never submitted. `parallel_map` pre-fills
  `results = [None] * len(iterable)` and only assigns submitted indices, so the
  tail stays `None` and `results[j].output_text` raises **`AttributeError`**, not
  `IndexError`.
- **L₂ < L₁** — nothing raises. `recorrection_history[j]` now refers to a
  *different* segment from the previous round, so the model is silently primed
  with another segment's rejected answers.

#### Change

Re-key the history by segment text instead of by list index:

```python
recorrection_history: dict[str, list[str]] = {}
...
use_history = i >= self.max_correction_attempts / 3
history_for_correction = [
	recorrection_history.get(segment, []) if use_history else []
	for segment in segments_revised
]
```

The history's purpose is "you have already answered these for this text, do not
repeat them", which is a property of the text, not of a position in a list that
is rebuilt every round. Segment boundaries may then move freely without
mispairing. A segment whose text changed correctly has no history. Two identical
segments in one round share a history list; the existing `not in` de-duplication
keeps that correct.

The write-back loop stores under the same key:

```python
for segment, result in zip(segments_revised, results, strict=True):
	if result.output_text:
		res_text = result.output_text
		text_corrected += res_text
		history = recorrection_history.setdefault(segment, [])
		if res_text not in history and len(res_text) < len(input_text) * 2:
			history.append(res_text)
	else:
		text_corrected += segment
```

Indexing by `range(len(segments_revised))` is removed entirely.

#### `parallel_map` strictness

`lib/tasks/concurrency.py` must raise instead of truncating:

- Annotate `iterable` and `iterable_kwargs` as `Sequence`, not `Iterable`. The
  current implementation already calls `len(iterable)`, so the existing
  annotation is wrong.
- When `iterable_kwargs is not None` and `len(iterable_kwargs) != len(iterable)`,
  raise `ValueError` naming both lengths, before submitting any work.

With that check in place no `None` can survive in `results`, so the workflow does
not need a separate `None` guard. The sequential branch in `workflow.py` uses
`zip(..., strict=True)` for the same reason.

Segment order, untouched text and `max_correction_attempts` are unchanged.

### T5 — Traditional/simplified tag never fires

`lib/tasks/typo/utils.py:104-105` reads:

```python
char_simplified = char_original
char_traditional = char_original
```

so both comparisons below are unconditionally False and neither conversion tag is
ever produced.

Origin, from git history: commit `7c00aac` (2023-04-14) introduced
`analyze_diff()` with real `to_simplified()` / `to_traditional()` calls. Commit
`f37a090` (2023-04-18, "Added web UI") commented them out — `chinese_converter`
was not vendored at the time — and they were never restored.

`chinese_converter` is vendored today and already imported at the top of the same
file (`utils.py:4`, used by `typo_augmentation`). The fix is to restore the two
calls:

```python
char_simplified = to_simplified(char_original)
char_traditional = to_traditional(char_original)
```

The homophone half of `analyze_diff()` is and always was correct; it is not
changed.

`tags` currently has no consumer: it is written into the report JSON, but
`web/templates/index.template` never reads it, and no other reader exists in the
add-on (verified across the full git history for `.template`, `.html`, `.js`).
Per the maintainer's decision, this batch repairs the data only. Rendering tags
in the report is out of scope.

### T6 — `assert` as flow control

Four `assert` statements participate in control flow:

| Location | Statement | Problem |
| --- | --- | --- |
| `lib/tasks/typo/utils.py:16` | `assert len(char) == 1` in `get_char_pinyin()` | `find_correction_errors()` passes whole diff tokens, which the tokenizer merges from runs of non-Chinese characters |
| `lib/tasks/typo/utils.py:61` | `assert len(tokens) <= 20000` in `create_single_char_mapping()` | A genuine capacity limit expressed as an assertion |
| `lib/tasks/typo/utils.py:181` | `assert len(before_text) == 1 and len(after_text) == 1` | Fires on any multi-character replace token |
| `lib/text/chinese.py:33` | `assert len(char) <= 1` in `is_chinese_character()` | `review_correction_errors()` passes whole tokens, so it raises on the same input |

All four are removed as assertions. `assert` is also stripped under `python -O`,
so behaviour must not depend on any of them.

#### Policy for non-Chinese replacements

Removing the assertions is not sufficient; the policy has to be stated, because
`find_correction_errors()` and `review_correction_errors()` both branch on
single-character Chinese assumptions.

**Adopted policy: if either side of a `replace` is not a single Chinese
character, keep the original text and do not add the position to
`typo_indices`.**

- Keeping the original preserves today's product behaviour.
  `review_correction_errors()` already rejects any replacement where either side
  fails `is_chinese_character()`; this batch does not widen what the corrector is
  allowed to accept.
- Not flagging the position is a deliberate **behaviour change**. Today a
  single-character non-Chinese replacement (`A` → `B`) is added to
  `typo_indices`, which schedules another re-correction round. Since the policy
  will never accept that replacement, the extra round can only spend API budget.
  Chinese non-homophone replacements keep flagging for re-correction exactly as
  before.

Implementation:

- `is_chinese_character()` returns `False` for strings longer than one character
  instead of asserting. It already returns `False` for `""`.
- `get_char_pinyin()` only accepts a single Chinese character. Callers test that
  condition before calling, so the function raises `ValueError` on anything else
  rather than silently returning `[]` — a silent empty list would read as "no
  shared pronunciation" and quietly re-enter the typo branch.
- `find_correction_errors()` gains an explicit branch for the replace case: if
  either side is not a single Chinese character, append `before_text` and
  continue without touching `typo_indices`.
- `create_single_char_mapping()` raises `ValueError` naming the observed and
  maximum token counts.
- `strings_diff()` drops the assertion at line 181 outright.

### T7 — Translation binding and gettext extraction

Three distinct defects:

1. `lib/llm/provider.py:10-17` defines a module-level `def _` *before* trying
   `addonHandler.initTranslation()`. `initTranslation()` installs `_` into
   builtins, and a module global always shadows a builtin, so every provider
   error message is emitted untranslated.
2. `configManager.py:12-14` guards with `if "_" not in globals()`. Under NVDA `_`
   is a builtin and never a global, so the guard is always true and shadows the
   translation function in the same way.
3. `lib/llm/executor.py:53` calls `_(f"...")`. `xgettext` cannot extract a
   runtime-formatted f-string, so the message never reaches the `.pot`.
   `ruff` independently flags this as the single `INT001` in the code base.

#### The fallback pattern

`review-claude-2.md` recommends adopting the shape already in
`lib/llm/executor.py:7-12`. Measured on this host, that shape is itself broken in
the test environment: `tests/conftest.py` installs an `addonHandler` stub whose
`initTranslation` is `lambda: None`, so `import addonHandler` succeeds, nothing
defines `_`, and the first call to `_()` raises `NameError`.

The adopted pattern defines a fallback only when no `_` is reachable at all, and
therefore never shadows the builtin:

```python
try:
	import addonHandler
	addonHandler.initTranslation()
except ImportError:
	pass

try:
	_
except NameError:
	def _(s):
		return s
```

At module level a bare `_` resolves through globals and then builtins. Under NVDA
the builtin exists, so no module global is created. Outside NVDA — notably
`workspace/evals/`, which imports `lib/llm/provider.py` without an NVDA runtime —
the fallback is defined.

This pattern is applied to `lib/llm/provider.py`, `configManager.py` and
`lib/llm/executor.py`.

#### Test stubs

`tests/conftest.py` and the per-file `addonHandler` stubs currently make
`initTranslation` a no-op, which makes it impossible to observe whether a message
was translated. They are changed to install a recognisable marker function into
builtins, so a test can assert that a displayed message actually passed through
`_()`. The stub must remain idempotent across the modules that install it.

#### Static strings

`lib/llm/executor.py:53` becomes a static message plus `.format()`:

```python
raise Exception(_("Parsing error. Unexpected server response. Response: {response}").format(response=response_json))
```

Every other `_()` call site in the touched files is checked for the same shape.
Moving error-message translation to the UI boundary belongs to R09/T15 and is not
done here.

### T8 — Boundary conditions and assorted defects

#### T8-1 `lib/tasks/typo/text_policy.py:30-39`

Three unguarded subscripts: `input_text_tmp[-1]` (line 30), `input_text[-1]`
(line 33) and `input_text_tmp[0]` (line 39). `text` is already guarded at each
site; the input strings are not.

Behaviour is defined for: empty input; empty model response; a response
consisting only of punctuation; and prefix/suffix stripping that consumes the
whole response. The existing punctuation-preservation rules are unchanged — the
fix must not unconditionally append characters or discard valid content to avoid
the exception.

#### T8-2 `latest_action` — already closed

The P0 batch replaced the cross-thread field with a UI-thread single-writer
publishing a frozen snapshot (`__init__.py:210-227`, `:451`, `:560-567`). This
item requires no new change; the spec records it as already satisfied, and the
batch verifies the existing tests still cover it.

#### T8-3 `__init__.py:392-393` dead code

The worker calls `self._notify(...)`, then `log.warning(...)`, then `raise e`,
followed by an unreachable `return`. `raise e` is removed and the `return` kept.
Re-raising inside a worker thread only leaves an unhandled thread exception in
the NVDA log after the user has already been notified, which is what codex R18
rules out.

#### T8-4 `__init__.py:469` bare `except`

Cost formatting is wrapped in a bare `except: pass`, after which the unformatted
value is interpolated into the "This task costs {cost} USD" message. It becomes
an explicit `except (TypeError, ValueError, decimal.InvalidOperation)` that logs
the cause and reports an explicit "cost unavailable" state. No fabricated zero,
no hidden error.

The two `except BaseException: pass` blocks in `showReport()`
(`__init__.py:256-258`, `:267-269`) disappear with the T12 rewrite.

#### T8-5 log levels

Normal-flow messages move from `log.warning` to `log.info` or `log.debug`:
"No errors in the selected text.", "The corrected text has been copied to the
clipboard.", "This task costs {cost} USD.", and the task start/finish notices.
`warning` and `error` are reserved for anomalies. Credentials and full user text
are not logged.

### T9 — Packaging weight and start-up cost

#### Data files

Measured sizes in `lib/tasks/typo/data/`:

| File | Size | Referenced by | Action |
| --- | --- | --- | --- |
| `dict_revised_2015_20231228.xlsx` | 30M | nothing | move to `workspace/data/` |
| `dict_revised_2015_20231228_csv.csv` | 3.6M | `chinese_dictionary.py:7` | **stays** — the only runtime dictionary |
| `chinese_dictionary_bopomofo.csv` | 268K | `workspace/evals/generate_zhuyin_dataset.py:22` | move to `workspace/data/` |
| `chinese_dictionary_pinyin_number.csv` | 240K | nothing | move to `workspace/data/` |
| `readme.txt` | 4K | — | split; each half follows its files |

`workspace/evals/generate_zhuyin_dataset.py` and
`tests/test_generate_zhuyin_dataset_unittest.py` are updated to the new path.
Nothing is rewritten in git history; the repository keeps the files.

#### `buildVars.excludedFiles`

`site_scons/site_tools/NVDATool/addon.py:7-9` matches with `Path.match()`, which
matches from the right, so suffix patterns work without a leading path:

```python
excludedFiles: list[str] = [
	"__pycache__/*",
	"*.pyc",
	"*.pyo",
	"*.xlsx",
	"web/workspace/*",
]
```

`web/workspace/` is not tracked in git; it is created at runtime by today's
`showReport()` and disappears with T12, but the pattern guards a developer
machine that ran the add-on before building. Third-party licence files and
required native files are not excluded. CSV is **not** excluded by extension —
the runtime dictionary is a CSV.

#### Lazy pinyin loading

`lib/tasks/typo/chinese_dictionary.py:20` parses the 3.6M CSV at import time, and
`__init__.py:54` imports `strings_diff` from `lib/tasks/typo/utils.py`, which
imports this module — so the parse is on NVDA's start-up path.

The two module-level mappings are replaced by `get_string_to_pinyin()` and
`get_pinyin_to_string()` backed by one module-level cache guarded by a
`threading.Lock` with double-checked initialisation.

`functools.lru_cache` is not sufficient: it does not hold a lock across the
wrapped call, so several `parallel_map` workers reaching the mapping for the
first time would each parse the file. The lock also prevents any caller from
observing a partially built mapping.

A missing or unreadable dictionary raises an explicit error. It must not degrade
to an empty `defaultdict`, which would silently make every character look like it
has no pronunciation.

The four call sites in `lib/tasks/typo/utils.py` (lines 17, 27, 31-32, 111) are
updated.

Both mappings stay `defaultdict(list)` internally, but the lookups that can miss
(`utils.py:17`, `:111`, and `analyze_diff` for a single non-Chinese character)
switch to `.get(char, [])`. A shared, process-lifetime `defaultdict` grows a new
empty entry on every miss; with the old per-import mapping that was bounded by
the import, and with one cached mapping it is not.

#### Size accounting

Compressed and uncompressed bundle sizes plus the file list are recorded before
and after the change, measured with the same build inputs. The 34MB/27MB figures
in the original reviews are not carried forward as guarantees.

### T11 — Residual settings and naming

1. `coseeing_username` and `coseeing_password` are removed from the config spec
   (`__init__.py:95-96`). No dedicated upgrade test is written (maintainer's
   decision); the acceptance condition is that the existing suite still passes,
   and the actual upgrade path for a user profile holding the old keys is
   **[manual]**.
2. `setting/provider/*.json` filenames are aligned with `Provider.name`:
   `anthropic.json` → `Anthropic.json`, `deepseek.json` → `DeepSeek.json`,
   `google.json` → `Google.json`, `ollama.json` → `Ollama.json`,
   `openrouter.json` → `OpenRouter.json`. `Coseeing.json` and `OpenAI.json`
   already match. The case-insensitive glob fallback at
   `lib/llm/provider.py:31-35` is then removed, leaving the direct
   `setting_dir / f"{name}.json"` lookup.

   No migration is needed for stored user settings: the filename is derived from
   the `Provider.name` class attribute, never from anything persisted. A stored
   `corrector_config_id` naming an unknown provider already falls back through
   `normalize_selection()`.
3. `tests/test_provider_naming.py` is repaired and strengthened: for every
   `setting/ai/*.json`, its `provider` value must resolve to a file in
   `setting/provider/` and to an entry in `setting/price.json`. Deriving the
   expectation from the catalog rather than a hand-written literal set is what
   stops the `ollama.json` regression recurring.
4. `tests/test_coseeing_auth_bundle.py` expects `client_id == "wordbridge"`,
   matching `lib/coseeing_auth.py:140`.

### T12 — Report output location

`showReport()` (`__init__.py:250-287`) currently `rmtree`s and recreates two
directories *inside the add-on install directory* and `copytree`s the static
modules on every single report.

#### New module `lib/report.py`

`generate_report(diff_data) -> Path` owns directory layout, asset provisioning,
template rendering and retention. It does not import NVDA or wx, so it is
testable directly. `GlobalPlugin.showReport()` shrinks to calling it and passing
the result to `OnPreview`. The two `except BaseException: pass` blocks go away
with the old code.

#### Location

```
<user folder>/WordBridge-workspace/
├── dictionary/                       (existing)
└── reports/
    ├── modules/                      shared assets
    │   ├── sweetalert2.all.min.js
    │   └── vue.js
    └── 20260921-143012-a3f9/
        ├── result.txt
        └── result.html
```

The four-character random suffix prevents a collision when two reports are
generated within the same second.

`dictionary/__init__.py` derives the user folder with a chain of six
`os.path.dirname` calls. That chain is extracted into `lib/paths.py` as
`user_workspace_root()` and shared, rather than duplicated. The `os.makedirs`
import-time side effect in `dictionary/__init__.py` belongs to R14/T17 and is
left alone.

#### Static assets

`web/templates/index.template:9-10` loads `modules/sweetalert2.all.min.js` and
`modules/vue.js` by relative path.

Per the maintainer's decision, the assets are copied **once** into
`reports/modules/` and each report references them as `../modules/...`. The copy
runs only when a file is missing or when the installed copy is newer.

This differs from the literal wording of `review-claude-2.md` T12-3 ("reference
the files in the install directory directly") while meeting its intent — no
`copytree` per report, and no writes to the install directory. Absolute
`file:///` URLs into the install directory were rejected: they require correct
encoding of install paths containing spaces or non-ASCII characters, and
`file://` pages loading scripts from a different directory behave inconsistently
across browsers, which would need Windows verification to trust.

#### Retention and failures

- Only directories directly under `reports/` whose names match the
  `YYYYmmdd-HHMMSS-xxxx` pattern are eligible for deletion. `modules/` and
  anything else is never touched.
- The most recent 20 report directories are kept; older ones are deleted.
  "Most recent" is decided by directory name, not by filesystem mtime: the
  `YYYYmmdd-HHMMSS-xxxx` prefix sorts lexicographically in chronological order,
  and mtime changes when a browser or the user touches a report.
- A failed deletion (the browser holds a file open, permissions are refused) is
  logged and does not abort the report being generated.
- A failed report generation propagates to the caller, which notifies the user.
  Nothing is swallowed.
- The install directory is opened read-only for the template.

File I/O still runs where `showReport` runs today, dispatched through the
existing `_run_on_ui`. Moving it to a background worker belongs to R07/T14.

## Error handling

- `parallel_map` raises `ValueError` on a length mismatch before submitting work,
  so a mismatch fails loudly at the call site instead of producing a short result
  list.
- `create_single_char_mapping()` and `get_char_pinyin()` raise `ValueError` with
  the offending value in the message.
- Dictionary load failure raises; it never degrades to an empty mapping.
- Cost formatting failure is logged with its cause and surfaces as an explicit
  "cost unavailable" state.
- Report retention failures are logged; report generation failures reach the user.
- No new user-visible message is introduced without `_()`, and every `_()` takes
  a literal string with `.format()` applied afterwards.

## Tests

New or changed test files, all runnable on this host:

| File | Covers |
| --- | --- |
| `tests/test_recorrection_workflow.py` (new) | T4: fake executor; segment count increasing, decreasing, equal-but-shifted boundaries, no re-correction needed, empty results; parallel and sequential paths; `parallel_map` length mismatch raises |
| `tests/test_typo_diff_tags.py` (new) | T5: traditional→simplified, simplified→traditional, homophone-different-character; T6: mixed Chinese/Latin/digit/URL input through `strings_diff`, `find_correction_errors`, `review_correction_errors` with no `AssertionError`, and identical behaviour under `python -O` (run in a subprocess, since `-O` cannot be toggled inside a pytest process) |
| `tests/test_translation_binding.py` (new) | T7: an injected marker `_` proves messages are translated; the fallback engages only when no `_` is reachable; the executor message is a static string |
| `tests/test_language_text_policy_unittest.py` (extend) | T8-1: empty input, empty response, punctuation-only response, prefix/suffix consuming the response — across lite and standard policies and both languages |
| `tests/test_chinese_dictionary_lazy.py` (new) | T9: a subprocess asserts the cache is still cold after importing `lib.tasks.typo.utils`; concurrent first access loads exactly once and yields a complete mapping; mappings match the pre-change values |
| `tests/test_addon_bundle_contents.py` (new) | T9: calls `createAddonBundleFromPath()` from `site_scons/site_tools/NVDATool/addon.py` into `tmp_path` with `buildVars.excludedFiles`; asserts no `__pycache__`, `.pyc` or `.xlsx`, and that the runtime CSV, the `package/` auth bundle and `web/templates/modules/vue.js` are present |
| `tests/test_provider_naming.py` (fix + extend) | T11: filenames derived from the catalog; every `setting/ai/*.json` provider resolves to a provider config and a `price.json` entry |
| `tests/test_coseeing_auth_bundle.py` (fix) | T11: `client_id == "wordbridge"` |
| `tests/test_report_output.py` (new) | T12: writes under `WordBridge-workspace/reports/`, never into the install directory; two consecutive reports do not overwrite each other; `modules/` is provisioned once and referenced relatively; retention keeps 20 and deletes only pattern-matching directories; a read-only install directory still produces a full report; a failed deletion does not break generation |

`tests/test_addon_bundle_contents.py` zips a 62M tree. Its runtime is measured
during implementation; if it exceeds a few seconds it is marked `slow`.

**[manual]** — pending platform verification, to be reported as such:

- Upgrading a profile that still holds `coseeing_username` / `coseeing_password`
- Report generation, asset loading and keyboard navigation in a real browser on
  Windows
- NVDA start-up no longer reading the 3.6M CSV, measured on Windows
- Translated provider and executor messages in a Traditional Chinese NVDA

`scons pot` regeneration and confirmation that the T7 messages appear in the
`.pot` is also **[manual]** — `scons` is not installed on this host.

## Delivery order

Inner, pure-function layers first, so their tests cannot be confounded by the
outer changes:

1. **T5** — restore the conversion calls (two lines, isolated)
2. **T6** — remove the assertions and state the non-Chinese policy
3. **T4** — re-key the history; make `parallel_map` strict
4. **T7** — translation binding and static strings
5. **T8** — boundary guards, dead code, bare `except`, log levels
6. **T11** — config spec, provider filenames, naming tests
7. **T9** — move data, exclusion patterns, lazy dictionary, bundle test
8. **T12** — `lib/paths.py`, `lib/report.py`, rewrite `showReport()`

One commit per task, each with its own tests, each independently revertible.

## Non-goals

- Rendering `analyze_diff` tags in the report
- Widening what the corrector is permitted to accept for non-Chinese text
- CI, ruff or pyright gates (T10)
- Any P3 item listed under Scope
- Rewriting git history to drop the 30M XLSX
