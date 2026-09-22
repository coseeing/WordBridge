# Bundled Catalog Single-File Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace split provider, model, and price assets with one `setting/catalog.json` while preserving the runtime catalog.

**Architecture:** `BundledCatalogSource` reads one JSON object and passes it unchanged to the existing `build_catalog()` and `load_catalog()` validation and fallback pipeline. Labels and pricing are explicit document data. Task configuration and prompt templates retain their independent readers.

**Tech Stack:** Python 3, JSON, pytest, NVDA add-on bundle tooling.

**Spec:** `docs/superpowers/specs/2026-09-22-bundled-catalog-single-file-design.md`

## Global Constraints

- Keep the current `lib.catalog.document.SCHEMA_VERSION`.
- Preserve all model/provider settings, pricing, labels, active flags, and Coseeing entries.
- Do not change `setting/task/corrector.json` or `setting/templates/*.json`.
- Preserve safe fallback for a missing, unreadable, or invalid catalog document.
- Do not retain a compatibility reader for the retired split paths.

## Review Focus

- A missing `catalog.json` reports `unreadable_file` and falls back to the default sentinel.
- Invalid JSON or a top-level list reports `unreadable_file` at `catalog.json`, without raising.
- A valid document with a bad inner entry retains valid entries and surfaces normal schema issues.
- Each active local model retains `pricing` and `usage_key` for cost calculation.
- The add-on bundle contains `setting/catalog.json` and omits legacy catalog inputs.

---

### Task 1: Define the single-document contract in tests

**Files:**
- Modify: `tests/test_catalog_bundled.py`
- Modify: `tests/test_ai_config_schema.py`
- Modify: `tests/test_provider_naming.py`
- Modify: `tests/test_task_architecture_unittest.py`
- Modify: `tests/test_addon_bundle_contents.py`

**Interfaces:**
- Consumes: `BundledCatalogSource(setting_dir).load() -> tuple[dict | None, tuple[CatalogIssue, ...]]`.
- Produces: tests that treat `setting/catalog.json` as the only bundled catalog input and pin unchanged runtime behavior.

- [ ] **Step 1: Add a canonical-document fixture and failing source tests**

Add this helper to `tests/test_catalog_bundled.py`:

```python
def _write_catalog(root: Path, document: dict) -> Path:
    path = root / "catalog.json"
    path.write_text(json.dumps(document), encoding="utf8")
    return path
```

Test a valid document, invalid JSON, and a top-level list. The invalid inputs must produce `CatalogIssue("unreadable_file", "catalog.json", ...)` and not raise.

- [ ] **Step 2: Run the new tests before production changes**

Run: `python -m pytest tests/test_catalog_bundled.py -q`

Expected: FAIL because the current source still reads `price.json`, `provider/*.json`, and `ai/*.json`.

- [ ] **Step 3: Change assertions from files to catalog entries**

Remove `BUNDLED_LABELS`, `price.json`, and provider-directory assertions. Load `catalog.json` and assert schema keys, explicit labels, OpenAI provider fields, the `gpt-5.6-sol&OpenAI` `price_entry()`, known lint issue, Coseeing labels, and the default sentinel.

- [ ] **Step 4: Convert data-integrity tests to document-level invariants**

In `tests/test_ai_config_schema.py`, load the canonical document and assert unique model/provider pairs, expected provider-to-model sets, and one provider-less `default` Coseeing entry. Preserve the task-config test unchanged. In `tests/test_provider_naming.py`, iterate document `providers` and `models`; verify runnable provider construction and non-empty pricing for active local models.

- [ ] **Step 5: Update packaging and architecture language**

Rename the task-architecture test/docstring to describe the shipped catalog document. Add bundle assertions that `setting/catalog.json` is present and that `setting/ai/`, `setting/provider/`, and `setting/price.json` are absent.

- [ ] **Step 6: Run the changed test group**

Run: `python -m pytest tests/test_catalog_bundled.py tests/test_ai_config_schema.py tests/test_provider_naming.py tests/test_task_architecture_unittest.py tests/test_addon_bundle_contents.py -q`

Expected: FAIL only for absent `catalog.json` and undeleted legacy assets.

- [ ] **Step 7: Commit the contract tests**

Run: `git add tests/test_catalog_bundled.py tests/test_ai_config_schema.py tests/test_provider_naming.py tests/test_task_architecture_unittest.py tests/test_addon_bundle_contents.py && git commit -m "test: define the bundled single-file catalog contract"`

### Task 2: Ship the canonical document and thin source

**Files:**
- Create: `addon/globalPlugins/WordBridge/setting/catalog.json`
- Modify: `addon/globalPlugins/WordBridge/lib/catalog/sources.py`
- Modify: `addon/globalPlugins/WordBridge/lib/catalog/model.py`
- Modify: `addon/globalPlugins/WordBridge/lib/llm/adapter.py`
- Modify: `addon/globalPlugins/WordBridge/dialogs.py`
- Modify: `workspace/evals/README.md`
- Delete: `addon/globalPlugins/WordBridge/setting/ai/*.json`
- Delete: `addon/globalPlugins/WordBridge/setting/provider/*.json`
- Delete: `addon/globalPlugins/WordBridge/setting/price.json`

**Interfaces:**
- Consumes: a JSON object in `setting/catalog.json` compatible with `build_catalog()`.
- Produces: `BundledCatalogSource.load() -> (document, issues)` where `document` is the parsed object or `None` for file-level failure.
- Preserves: `CorrectorCatalog`, `ProviderEntry`, `ModelEntry.price_entry()`, `load_catalog()`, and task/template interfaces.

- [ ] **Step 1: Generate `setting/catalog.json` losslessly**

Put provider objects under `providers`, with explicit `label`, `url`, `setting`, `timeout0`, and `timeout_max`. Put every local model under `models`, with explicit `provider`, `model`, `label`, `active`, `pricing`, and `usage_key`. Put the `default` sentinel and existing Coseeing-enabled models under `coseeings`. Keep the unreferenced OpenRouter provider so its lint issue remains intentional.

- [ ] **Step 2: Simplify `BundledCatalogSource`**

Replace `BUNDLED_LABELS` and split traversal with:

```python
def load(self) -> tuple:
    issues = []
    document = self._read_json(self.setting_dir / "catalog.json", issues)
    return document, tuple(issues)
```

Keep `_read_json()` unchanged so `OSError`, `ValueError`, and non-mapping JSON become `unreadable_file` at `catalog.json`.

- [ ] **Step 3: Remove stale split-layout references**

Update only comments/docs in `lib/catalog/model.py`, `lib/llm/adapter.py`, `dialogs.py`, and `workspace/evals/README.md` so they refer to catalog/model entries rather than `price.json` or `ai/*.json`; do not change runtime APIs.

- [ ] **Step 4: Delete exactly the legacy inputs**

Delete all JSON files in `setting/ai/`, all JSON files in `setting/provider/`, and `setting/price.json`. Keep `setting/task/` and `setting/templates/` untouched.

- [ ] **Step 5: Run focused behavior and packaging checks**

Run: `python -m pytest tests/test_catalog_bundled.py tests/test_ai_config_schema.py tests/test_provider_naming.py tests/test_catalog_fallback.py tests/test_catalog_source_seam.py tests/test_eval_provider_config.py tests/test_provider_model_adapter_unittest.py tests/test_task_architecture_unittest.py tests/test_addon_bundle_contents.py -q`

Expected: PASS.

- [ ] **Step 6: Scan for obsolete runtime dependencies**

Run: `rg -n --glob '*.py' --glob '*.md' 'setting/(ai|provider)|price\.json|BUNDLED_LABELS' addon workspace tests`

Expected: no production path reads or obsolete test assertions.

- [ ] **Step 7: Run regression and artifact checks**

Run: `python -m pytest tests/test_import_purity.py -q && python -m pytest -q && python -m json.tool addon/globalPlugins/WordBridge/setting/catalog.json > /dev/null && git status --short`

Expected: all tests PASS, valid JSON, and only intended migration files changed.

- [ ] **Step 8: Commit the implementation**

Run: `git add addon/globalPlugins/WordBridge/lib/catalog/sources.py addon/globalPlugins/WordBridge/lib/catalog/model.py addon/globalPlugins/WordBridge/lib/llm/adapter.py addon/globalPlugins/WordBridge/dialogs.py addon/globalPlugins/WordBridge/setting/catalog.json workspace/evals/README.md && git add -u addon/globalPlugins/WordBridge/setting && git commit -m "refactor: consolidate the bundled catalog into one document"`
