# Bundled catalog single-file design

## Goal

Replace the split bundled catalog inputs under `setting/ai/`,
`setting/provider/`, and `setting/price.json` with one canonical
`setting/catalog.json`.  The add-on must expose the same selectable models,
provider request configuration, pricing, labels, and Coseeing sentinel as it
does today.

`setting/task/corrector.json` and `setting/templates/*.json` remain separate:
they configure and contain correction prompts, rather than describe the model
catalog.

## Current boundary

`BundledCatalogSource` is the only production component that understands the
split layout.  It reads the three input groups, joins pricing to model entries,
adds labels from `BUNDLED_LABELS`, and produces the catalog document consumed
by `build_catalog()`.

## Target boundary

`setting/catalog.json` contains the schema already consumed by
`build_catalog()`:

```json
{
  "schema_version": 1,
  "providers": { "Provider name": { "label": "...", "url": "...", "setting": {}, "timeout0": 10, "timeout_max": 20 } },
  "models": [{ "provider": "...", "model": "...", "label": "...", "active": true, "pricing": {}, "usage_key": "..." }],
  "coseeings": [{ "model": "default", "label": "Coseeing default", "active": true }]
}
```

`BundledCatalogSource.load()` reads that file as one JSON object and returns
it unchanged, plus any read issue.  `build_catalog()` remains the sole schema
validator.  `load_catalog()` retains its existing total-error handling and
sentinel fallback, so a missing, unreadable, or malformed bundled file cannot
prevent NVDA from starting.

## Migration

1. Generate `setting/catalog.json` from the currently shipped data, preserving
   all models, provider fields, prices, active flags, labels, and Coseeing
   entries.
2. Simplify `BundledCatalogSource` to read only `catalog.json`; remove the
   split-layout traversal and `BUNDLED_LABELS`.
3. Remove the obsolete `setting/ai/`, `setting/provider/`, and `setting/price.json`
   assets.
4. Update tests that assert the source layout.  Tests should assert the
   canonical file's content and confirm that valid, malformed, and unreadable
   single-file input preserve catalog validation and fallback behavior.

There is no compatibility reader for the old split files: the files are
bundled assets released together with the code, so retaining both would create
two sources of truth.

## Acceptance criteria

- Loading the bundled source yields the same usable catalog as before,
  including every local model and the `default` Coseeing sentinel.
- Provider settings and model pricing reach the existing provider adapter and
  cost calculator unchanged.
- A bad `catalog.json` produces catalog issues and degrades safely to the
  existing fallback sentinel when no selectable item remains.
- No production code reads `setting/ai/`, `setting/provider/`, or
  `setting/price.json`.
- Task configuration and prompt-template loading remain unchanged.

## Verification

Run the catalog, provider/config, selection, task-architecture, and import
purity tests.  Also scan source files for references to the retired paths and
inspect the resulting catalog document for the expected provider/model counts.
