# Corrector catalog decoupling, with a seam for a future remote source

## Goal

Close T17 of `review-claude-2.md` (R14 of `review-codex-2.md`): split the
settings catalog from the UI's selection state, remove the import-time side
effects that make a damaged configuration take the whole add-on down, and do
both in a shape that a future remote HTTP catalog can be dropped into without
touching any consumer.

Today a new model cannot ship without a new add-on release, because the model's
display name is hard-coded in `configManager.py`'s `LABEL_DICT`. The end state
this design serves is: **one JSON payload, fetched at runtime, replaces the
whole catalog — models, labels, prices and provider parameters.**

This batch builds the seam and the data model. It does **not** implement the
HTTP fetch.

## Decisions taken

These were settled with the maintainer before this spec was written. They are
recorded because several of them are not recoverable from the code.

| # | Decision |
| --- | --- |
| 1 | This phase implements the seam only. No HTTP, no cache, no signature, no merge/overlay. |
| 2 | The catalog covers all four of today's data sets: models, display labels, prices, provider parameters. |
| 3 | Validation is per entry. A bad entry is skipped and recorded; it never raises. |
| 4 | When nothing valid remains, a built-in fallback catalog is used, holding exactly one Coseeing entry whose id is the sentinel `"default"`. The Coseeing server accepts `"default"` and picks the model itself, so no model, provider or price string is hard-coded in Python. |
| 5 | That sentinel entry is **also present in the normal catalog and always selectable**, and it is the default selection for new installations. |
| 6 | `SettingsRepository` owns every `config.conf["WordBridge"]["settings"]` key, not only the catalog-related ones. |
| 7 | The document has four top-level keys: `schema_version`, `providers`, `models`, `coseeings`. Coseeing is a channel, not a provider — its entries need only an id and a label, never provider parameters, pricing or a `usage_key`. Presence in `models` *is* the local channel; presence in `coseeings` *is* the Coseeing channel. No `local` / `coseeing` booleans. |
| 8 | A `coseeings` entry is self-contained: `label` is required and is never inherited from a same-id `models` entry. Entries exist in `coseeings` that have no counterpart in `models` at all, and a lookup rule would make the behaviour depend on whether one happens to be there. `setting/provider/Coseeing.json` is deleted, since Coseeing is no longer a provider and its `url` was never read — `COSEEING_BASE_URL` in `__init__.py` is the real endpoint. |

Decision 5 carries a reliability argument beyond the product one: a fallback
that appears only when everything else is broken is a path nobody has
exercised. Making it the everyday default means the disaster path is the path
already known to work.

## Scope

Paths are relative to `addon/globalPlugins/WordBridge/` unless noted.

In scope:

- New `lib/catalog/` package: `model.py`, `document.py`, `sources.py`,
  `selection.py`, `fallback.py`, `registry.py`
- New `settings_repository.py`
- `configManager.py` — `ConfigManager` and `LABEL_DICT` removed; `normalize_selection`
  and `make_corrector_config_id` move into `lib/catalog/`
- `dialogs.py` — import-time catalog construction and `ctypes` call removed; panel
  drives a `SelectionState`
- `__init__.py` — explicit catalog initialisation, static config spec defaults,
  task config loaded at plugin init, catalog entries passed into the correction path
- `lib/llm/provider.py`, `lib/llm/adapter.py` — stop reading files, receive entries
- `lib/application/task_factory.py`, `lib/application/task_runner.py` — pass entries through
- `setting/ai/` — one new entry for the sentinel
- `setting/provider/Coseeing.json` — deleted
- `workspace/evals/provider.py` — one call site updated

Out of scope, explicitly:

- The HTTP client, caching, offline policy, payload signing, and bundled⊕remote
  overlay semantics
- `CorrectionService` (T13), `JobController` (T14), domain errors (T15),
  concurrency policy (T16), the `coseeing_auth` state machine (T18)
- Renaming `configManager.py`, which will be handled when T13 restructures
  `__init__.py`
- Any change to `format_request` / `parse_response` in provider or adapter
  subclasses
- Changing what the Coseeing request carries. The body keeps sending the derived
  `corrector_config_id` (`deepseek-v4-flash&DeepSeek`), not a bare model name.
  Sending the bare name would change the format of *every* existing Coseeing
  request, and this repo cannot establish how the server treats an id without
  `&` — `server/` is empty. It is a self-contained follow-up once that is
  confirmed: one value in `correctTypo()`, no catalog data change.

## Architecture

### Modules and dependency direction

```
lib/catalog/
  model.py      CorrectorCatalog, ProviderEntry, ModelEntry, SelectableItem, CatalogIssue
  document.py   build_catalog(document, *, runnable_providers) -> CorrectorCatalog
  sources.py    CatalogSource protocol; BundledCatalogSource
  selection.py  SelectionState
  fallback.py   FALLBACK_DOCUMENT
  registry.py   initialize(catalog) / current()
```

`lib/catalog` imports **only the standard library**. It must not import `wx`,
`config`, `addonHandler`, `requests`, or anything under `lib/llm`. Two things
follow: its tests need no NVDA stubs, and a future `RemoteCatalogSource` is a
new class in `sources.py` with no consumer change.

```
dialogs.py ─────┐
__init__.py ────┼──→ lib/catalog
task_factory ───┘
                     lib/llm/provider.py, lib/llm/adapter.py  ← receive entries
```

### Ownership and initialisation

NVDA instantiates `LLMSettingsPanel` itself (`categoryClasses` holds the class),
so constructor injection is unavailable. `lib/catalog/registry.py` provides
`initialize(catalog)` and `current()`. `GlobalPlugin.__init__` calls
`initialize()` exactly once; the panel calls `current()`. This is still a
process-wide single value, but an explicitly initialised one — which is the
difference that matters: `dialogs.py`'s module-level `ConfigManager(...)`
disappears.

`current()` before `initialize()` is a programming error and raises. Tests
initialise explicitly.

## The catalog document

The wire format. `BundledCatalogSource` produces it by flattening today's four
data sets; a future `RemoteCatalogSource` will produce the same shape from one
HTTP response.

The on-disk `setting/ai/*.json` files do **not** change: flattening them is
exactly `BundledCatalogSource`'s job, and it emits a `coseeings` entry for each
file whose `coseeing` field is true. No data migration.

```jsonc
{
  "schema_version": 1,
  "providers": {
    "OpenAI": {
      "label": "OpenAI",
      "url": "https://api.openai.com/v1/responses",
      "setting": { "max_output_tokens": 4096, "...": "..." },
      "timeout0": 10,
      "timeout_max": 20
    }
  },
  "models": [
    {
      "provider": "OpenAI",
      "model": "gpt-5.6-sol",
      "label": "gpt-5.6-sol",
      "active": true,
      "pricing": { "input_tokens": 1.25, "output_tokens": 10, "base_unit": 1000000 },
      "usage_key": "usage"
    }
  ],
  "coseeings": [
    {
      "model": "default",
      "label": "Coseeing default (server chooses)",
      "active": true
    },
    {
      "model": "deepseek-v4-flash",
      "provider": "DeepSeek",
      "label": "deepseek-v4-flash",
      "active": true
    }
  ]
}
```

`models` and `coseeings` are two lists of *offers*, one per channel, not one
list with channel flags. A model served by both channels appears in both,
because the two offers genuinely differ: the local one needs provider
parameters, a `Provider` subclass and a price; the Coseeing one needs an id the
server recognises. Today exactly one model is in both
(`deepseek-v4-flash&DeepSeek`).

### Model entry fields

| Field | Required | Default | Notes |
| --- | --- | --- | --- |
| `provider` | yes | — | Must not contain `&` |
| `model` | yes | — | Must not contain `&` |
| `label` | no | the `model` string | Display name. Moving this out of `LABEL_DICT` is what lets a remote payload add a model |
| `active` | no | `true` | |
| `pricing` | no | `None` | **Optional on purpose**: `qwen2&Ollama` ships with no price entry today and must stay usable |
| `usage_key` | no | `None` | Paired with `pricing` |

### Identity

`corrector_config_id` is **never a field**. It is always derived, by one rule:

```python
def make_corrector_config_id(model: str, provider: str | None = None) -> str:
	return model if provider is None else f"{model}&{provider}"
```

A `models` entry always has a provider, so its id always contains `&`. A
`coseeings` entry for a model the server serves on its own — the sentinel, whose
id is therefore `"default"` — has no provider and gets a bare id. The two forms
cannot collide, because one always contains `&` and the other never does.

Deriving rather than declaring means a model/provider pair has exactly one
identity, with no second place for it to be written differently.

Price data belongs to the (provider, model) **pair**, not to either alone —
`setting/price.json` is keyed by exactly that pair — so it is nested in the
model entry rather than carried in `providers`.

### Coseeing entry fields

| Field | Required | Default | Notes |
| --- | --- | --- | --- |
| `model` | yes | — | Must not contain `&` |
| `label` | **yes** | — | Never inherited from a same-id `models` entry. See decision 8 |
| `provider` | no | — | **Part of the identity, not a lookup key**: present, the id is `model&provider`, matching the local offer of the same model; absent, the id is the bare `model`, for something the server serves on its own. Must not contain `&`. Never used to look anything up in `providers` |
| `active` | no | `true` | |

A Coseeing entry carries no `pricing`, no `usage_key` and no provider
parameters, because the request goes to `COSEEING_BASE_URL/proofreader` with
nothing but the id, and the cost comes back in the response.

### Provider entry fields

`label`, `url`, `setting`, `timeout0`, `timeout_max` — **all required**,
`label` included. `providers` describes local providers only; Coseeing has no
entry here.

Today `setting/provider/*.json` carries no `label`, and `LABEL_DICT` supplies
one for five of the seven providers, with `dialogs.py` falling back to the raw
name for `Ollama` and `OpenRouter`. That fallback moves into
`BundledCatalogSource`, which emits `LABEL_DICT.get(name, name)` — identical
output, but the defaulting now happens where the data is *produced* rather than
where it is validated. A document is either complete or it is not; a consumer
should never have to know which fields might be missing.

## Validation and degradation

`build_catalog()` always returns a `CorrectorCatalog`. Problems become
`catalog.issues` — a tuple of `CatalogIssue(code, location, detail)` — never
exceptions. Callers do not need `try`/`except`.

Each list is validated on its own. Because the channel is carried by which list
an entry is in, no rule needs to ask what channels an entry wants.

**`models` entries** — every one of them is a local offer, so the provider rules
apply unconditionally:

| Condition | Outcome |
| --- | --- |
| `pricing` absent | Entry kept, `pricing=None`. Not an error. |
| The provider has no valid entry in `providers` | Entry dropped. Issue recorded. |
| The provider name is not in `runnable_providers` | Entry dropped. Issue recorded. |
| Provider entry missing `label` / `url` / `setting` / `timeout0` / `timeout_max` | Provider dropped; its models follow the two rows above. |
| Provider referenced by no `models` entry | Legal. Lint-level issue only. |
| `model` or `provider` empty, or containing `&` | Entry dropped. Issue recorded. |
| Duplicate `corrector_config_id` within `models` | First wins, rest dropped. Issue recorded. (Today this raises `ValueError` and takes the add-on down at import.) |

**`coseeings` entries**:

| Condition | Outcome |
| --- | --- |
| `model` or `label` absent or empty | Entry dropped. Issue recorded. |
| `model` or `provider` containing `&` | Entry dropped. Issue recorded. |
| Duplicate `corrector_config_id` within `coseeings` | First wins, rest dropped. Issue recorded. |
| The id also appears in `models` | **Not** a duplicate. It is one model offered on both channels, which is the shipped state of `deepseek-v4-flash&DeepSeek`. |
| The provider named is unknown, or absent altogether | Irrelevant. `providers` is never consulted for a Coseeing entry. |

**Whole document**: an unrecognised `schema_version` major version rejects the
document and the fallback is used.

### Why dropping a `models` entry does not hide the model

Under the single-list design this rule needed a caveat, because dropping an
entry would have taken its Coseeing offer with it. With two lists it needs
none: dropping a `models` entry removes a local offer that could not have
worked, and the model's Coseeing offer is a separate entry that is untouched.

A local correction needs three things the Coseeing channel does not: provider
parameters, a `Provider` subclass and a matching adapter. Data alone cannot
supply the latter two — a new provider family needs a new add-on release. So:

- A remote payload naming a model whose provider parameters are absent still
  reaches users through its `coseeings` entry, which is what the server can
  actually serve.
- A remote payload supplying complete provider parameters for a family this
  build has no code for would otherwise produce a selectable item that raises
  `ValueError: Unsupported provider` when the user presses the hotkey. The
  `runnable_providers` rule turns that runtime crash into an option that simply
  does not appear.

`runnable_providers` is injected — `lib/catalog` must not import `lib/llm`.
`lib/llm` exports `SUPPORTED_PROVIDERS` as the intersection of `get_provider()`'s
family table and `get_provider_model_adapter()`'s, and a test asserts the two
tables are equal.

### Degradation ladder

1. **Normal** — at least one selectable item.
2. **Degraded** — some entries dropped; the rest work. Issues surfaced.
3. **Empty** — zero selectable items: `FALLBACK_DOCUMENT` is used. It is
   `{"schema_version": 1, "providers": {}, "models": [], "coseeings": [<the
   sentinel>]}` — the same shape as any other document, parsed by the same
   `build_catalog()`, so there is one code path, not two.

The add-on always loads. A damaged catalog never prevents NVDA from starting or
the settings panel from opening.

### The `"default"` sentinel

`correctTypo()`'s Coseeing branch already sends `corrector_config_id` verbatim,
so `"default"` reaches the server with no special-casing. The entry exists only
in `coseeings`, so the local path — which would fail on
`get_provider("Coseeing")` — is structurally unreachable rather than suppressed
by a flag. Cost comes back from the server, so the absence of pricing costs
nothing.

`normalize_selection()` follows the lists: a stored `execution_channel` of
`Coseeing` is honoured when the stored id is in `coseeings`, `local` when it is
in `models`, and anything else falls back to `default_selection()` — which
returns the first `coseeings` entry, the sentinel.

Self-healing: a user whose stored selection is `"default"` while a healthy
catalog is loaded still resolves, because the sentinel is a normal entry in that
catalog. If a future catalog omits it, `normalize_selection()` falls back to the
catalog default. No migration code.

Visibility: issues are always logged in full; the settings panel shows a summary
line; and the first correction of a session that runs under the fallback catalog
announces it once through `ui.message`. Users who never open the settings panel
still learn that the server is choosing the model — once, not on every
correction.

## Decomposing `ConfigManager`

### `CorrectorCatalog` (immutable)

Takes over everything except the mutable `provider` attribute:
`selectable_items`, `provider_groups`, `get_model(id)`, `get_provider(name)`,
`default_selection()`, `find_selection(id, channel)`,
`get_item(group_index, model_index)`. The index-based API stays, because
`wx.Choice` needs it.

The one change that removes the mutable attribute:

```python
# before: a hidden mutable field decides the answer
@property
def model_labels(self): ...          # reads self.provider

# after: a pure function of its argument
def labels_for(self, provider_group: str) -> tuple[str, ...]: ...
```

`model_labels` is the only member that forced `ConfigManager.provider` to exist.

### `SelectionState` (`lib/catalog/selection.py`, owned by the panel)

Holds `provider_group_index` and `model_index`. It lives under `lib/catalog`
because it is a selection *into* a catalog and imports only `model.py`, so it is
testable without `wx`.

- `SelectionState.restore(catalog, corrector_config_id, execution_channel)`
  encapsulates today's normalise → `find_selection` → `(-1, -1)` → default dance
  from `dialogs.py`
- `choose_provider_group(index)` switches group and resets the model index
- `current_item()` returns the `SelectableItem`

### `SettingsRepository` (`settings_repository.py`)

The only module that touches `config.conf["WordBridge"]["settings"]`. Typed
accessors for every key: corrector selection, language, correction mode, API key
per provider, max character count, and the three booleans.

Two resolutions live here:

- `corrector_selection()` resolves an empty stored value to the catalog's current
  default. This is what lets the config spec defaults be static.
- `language()` resolves an empty stored value to the OS UI language, calling
  `ctypes.windll.kernel32.GetUserDefaultUILanguage()` lazily and once, guarded so
  that a failure degrades to `zh_traditional` instead of failing an import.

## Import-time side effects

| Today | After |
| --- | --- |
| `dialogs.py:53-54` builds `ConfigManager` and calls `default_selection()` at import | Removed. `GlobalPlugin.__init__` calls `registry.initialize()` |
| `dialogs.py:35` calls `ctypes.windll.kernel32.GetUserDefaultUILanguage()` at import | Moves into `SettingsRepository.language()`, lazy and guarded |
| `__init__.py:109` calls `load_corrector_task_config()` at import | Moves into plugin init; a corrupt file degrades to defaults with a user-visible message |
| `config.conf.spec` defaults derive from the catalog and from `ctypes` | Static strings; the real defaults are resolved at read time |

After this, importing the add-on's modules reads no file under `setting/` and
makes no `windll` call.

### `LABEL_DICT` splits in two

`configManager.py`'s `LABEL_DICT` holds both model display names **and** UI
strings (`zh_traditional`, `zh_simplified`, `standard`, `lite`,
`personal_api_key`, `coseeing_account`). Only the model names move into catalog
data. The UI strings stay in `dialogs.py`. Sending UI strings through the
catalog would make a future remote payload a channel for rewriting the
interface's own wording.

## Provider and adapter injection

```python
def get_provider(provider_name, credential, retries=2, backoff=1, *, provider_entry) -> Provider
def get_provider_model_adapter(provider_name, model_name, *, price_entry) -> ProviderModelAdapter
```

Both keyword arguments are **required**. A "read the bundled catalog if not
supplied" default would leave a second file-reading path inside `lib/llm`, which
would silently diverge from the live catalog once a remote source exists.

`Provider.__init__` no longer reads `setting/provider/<name>.json`;
`ProviderModelAdapter._load_model_entry` no longer reads `setting/price.json`.
`create_typo_workflow()` and `run_typo_correction()` gain the two parameters and
pass them through, so the add-on's correction path is structurally forced to use
the live catalog.

Deliberately unchanged:

- `CostCalculator` — it consumes `{model, provider, pricing, usage_key}`, so
  `ModelEntry.price_entry()` produces that shape, returning `{}` when there is no
  price. Byte-for-byte equivalent to today's `.get(..., {})`, which is what keeps
  `qwen2&Ollama` working.
- `adapter.get_model_entry()`'s public signature.
- Every `format_request` / `parse_response`.

Removed: `getattr(self, 'setting_name', self.name)` in `provider.py:36`. No
subclass defines `setting_name`; it was a fallback for filename mismatches, and
after injection there is no filename.

Updated call sites: `workspace/evals/provider.py` (one), `tests/test_provider_naming.py`
(three, and that file is rewritten to derive from the catalog), and
`tests/test_eval_provider_config.py` (one).

## Testing

Written in this order. Layer 2 must be green **before** any production code
changes.

1. **Document validation** (`tests/test_catalog_document.py`) — one test per row
   of both validation tables, including the `qwen2&Ollama` missing-price guard,
   both provider rules, and the case that must *not* be treated as a duplicate:
   the same id in `models` and in `coseeings`.
2. **Bundled fidelity** (`tests/test_catalog_bundled.py`) — a characterisation
   test: building from the real `setting/` directory yields exactly the same
   selectable items, ids, labels and prices as today's `ConfigManager` +
   `LABEL_DICT` + `price.json`. This is the proof that nothing was lost, so it is
   written against the current implementation as oracle before the refactor
   starts. It also asserts the issue list contains exactly the one known lint
   (`OpenRouter.json` referenced by no `models` entry), so a future orphan file
   is caught — `Coseeing.json` is deleted in this batch, so it is not on that
   list.
3. **Selection and settings** (`tests/test_selection_state.py`,
   `tests/test_settings_repository.py`) — restore, unknown id, unavailable
   channel, group switch resetting the model index; empty-string resolution,
   `ctypes` failure degrading to `zh_traditional`, writes reaching config.
4. **Fallback** (`tests/test_catalog_fallback.py`) — a broken document yields
   exactly one item with id `"default"` in the Coseeing group; a stored
   `"default"` under a healthy catalog resolves; and the fallback entry and the
   shipped sentinel produce identical `SelectableItem`s.
5. **The seam** (`tests/test_catalog_source_seam.py`) — a `FakeRemoteCatalogSource`
   returning an in-memory document produces catalog, selection and panel-facing
   results identical to the same content loaded from bundled files. This proves
   the seam without implementing HTTP, and becomes the contract a future
   `RemoteCatalogSource` is written against.
6. **Import purity** (`tests/test_import_purity.py`) — in a subprocess, an
   `sys.addaudithook` on the `open` event asserts that importing `dialogs` and the
   plugin module reads nothing under `setting/` and makes no `windll` call.
7. **Injection and purity** — `create_typo_workflow()` without the entries
   raises `TypeError`; `SUPPORTED_PROVIDERS` equals the adapter family table; and
   every module under `lib/catalog/` imports nothing outside the standard
   library, walked from its ASTs so the assertion cannot be satisfied by an
   import that merely happens not to run.

Regression baseline: 343 passed, 1 skipped, 16 deselected. Existing
`tests/test_corrector_catalog_unittest.py` is rewritten against the new API;
everything else stays green.

Not tested here, by scope: network, caching, signing, and overlay merge.

## Acceptance criteria

1. No module under `addon/globalPlugins/WordBridge/` reads a file under
   `setting/` at import time, and no `windll` call happens at import — asserted
   by test 6.
2. An empty `setting/ai/` directory, or JSON corrupt in every file, still loads
   the add-on, still opens the settings panel, and still offers the `"default"`
   Coseeing option.
3. A single corrupt `setting/ai/*.json` file removes only that entry.
4. The shipped catalog produces exactly the same selectable options as before
   this change, plus the new sentinel entry — asserted by test 2. Deleting
   `setting/provider/Coseeing.json` changes nothing observable, because no
   `ai/*.json` ever named it and `COSEEING_BASE_URL` is a constant in
   `__init__.py`.
5. `"default"` is the default selection for a new installation; existing users'
   stored selections are untouched.
6. Adding a model to an existing provider family requires editing catalog data
   only — no Python change, including no label change.
7. `lib/catalog` imports nothing outside the standard library — asserted by a
   test.
8. The full non-integration suite is green.

## Risks

- **`config.conf.spec` defaults become empty strings.** Every read path must go
  through `SettingsRepository`; a missed raw subscript would surface as an empty
  model id. Mitigated by making the repository the only module that touches
  `config.conf`, and by test 3.
- **Decision 5 changes what new installations select.** Existing users are
  unaffected, but a new user now reaches the Coseeing server's choice of model
  rather than the first item in the list. This is intended; it is called out
  here because it is a product-visible change riding along with a refactor.
- **The server's `"default"` contract is external.** If the Coseeing server ever
  stops accepting `"default"`, the fallback stops working. No test in this repo
  can cover that; the `server/` directory here is empty.
- **The sentinel's real model is invisible.** The proofreader response carries
  `response`, `interaction_id` and `cost` but no model name, so neither the UI nor
  the report can say which model served a `"default"` request. Acceptable now; if
  the server later echoes the model, the UI can show it.
