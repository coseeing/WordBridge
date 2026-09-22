# Catalog Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the corrector catalog from the UI's selection state and from the settings store, remove every import-time side effect, and put the whole catalog behind a `CatalogSource` seam that a future remote HTTP source can be dropped into without touching any consumer.

**Architecture:** A new stdlib-only `lib/catalog/` package owns an immutable `CorrectorCatalog` built from a plain document (`schema_version`, `providers`, `models`, `coseeings`). `BundledCatalogSource` produces that document by flattening today's `setting/ai/*.json`, `setting/provider/*.json` and `setting/price.json`. Consumers — the settings panel, the plugin entry point, and the LLM provider/adapter factories — receive catalog entries instead of reading files. Work proceeds inside-out: the pure data layer first, the characterization test that proves nothing is lost second, then injection, then the rewiring that removes the import-time globals.

**Tech Stack:** Python 3.11+ (NVDA runtime is CPython 3.13 x64; this host runs 3.14.4), pytest 9.1.1, wxPython (stubbed in tests), configobj (stubbed in tests).

**Spec:** `docs/superpowers/specs/2026-09-22-catalog-decoupling-design.md` (Traditional Chinese: `..._ZH-TW.md`)

## Global Constraints

- All add-on paths are relative to `addon/globalPlugins/WordBridge/` unless noted otherwise.
- **Indentation in this repo is tabs**, in Python, JSON and `.template` files. `pyproject.toml` sets `indent-style = "tab"` and ignores `W191`. Match it. The only exception is `workspace/evals/provider.py`, which uses 4 spaces — match *that* file's existing style when editing it.
- Run tests with `python3 -m pytest`. There is **no** `python`, `py`, `uv`, `scons`, `ruff` or `pyright` on PATH. Any step needing `scons` cannot be run here and must be reported as pending.
- `tests/conftest.py` puts `addon/globalPlugins/WordBridge/` and `tests/` on `sys.path` and installs the `_wb_vendor` sandbox, so `from lib.catalog.model import ModelEntry` works from tests. `package/` is deliberately **not** on `sys.path`.
- **`lib/catalog/` may import only the standard library.** No `wx`, no `config`, no `addonHandler`, no `requests`, nothing under `lib/llm`. Task 1 adds an AST-walking test that enforces this; every later task must keep it green.
- **Catalog labels are plain data and are not passed through `_()`.** `lib/catalog` cannot call NVDA's translation builtin. This is correct on the merits: today's `LABEL_DICT` maps every model and provider name to itself except `gemini-3.1-pro-preview` → `gemini-3.1-pro`, which is a rename, not a translation. Consequence to state in the Task 6 commit message: those strings leave the `.pot`. UI strings (`zh_traditional`, `zh_simplified`, `standard`, `lite`, `personal_api_key`, `coseeing_account`) stay in `dialogs.py` wrapped in `_()`.
- **Baseline before this plan: `python3 -m pytest -q -m "not integration"` reports 343 passed, 1 skipped, 16 deselected.** Every task must leave that number no worse, and most tasks add to it.
- New test modules that need the NVDA plugin harness must import `_load_nvda_plugin` **inside the test function**, never at module scope. See the comment at the top of `tests/test_correction_notifications.py` for why; a module-scope import reorders collection and poisons `lib.coseeing_auth`'s exception bindings, costing 17 unrelated failures.
- Commit after every task. Branch: create `catalog-decoupling` from `main` before Task 1.
- `docs/` is in `.gitignore`; spec and plan files are tracked with `git add -f`, following the existing convention.

---

## File Structure

**Created:**

- `addon/globalPlugins/WordBridge/lib/catalog/__init__.py` — package marker and public surface.
- `addon/globalPlugins/WordBridge/lib/catalog/model.py` — `make_corrector_config_id`, `CatalogIssue`, `ProviderEntry`, `ModelEntry`, `CoseeingEntry`, `SelectableItem`, `CorrectorCatalog`.
- `addon/globalPlugins/WordBridge/lib/catalog/document.py` — `SCHEMA_VERSION`, `build_catalog()`; all validation lives here.
- `addon/globalPlugins/WordBridge/lib/catalog/sources.py` — `CatalogSource` protocol, `BundledCatalogSource`, `BUNDLED_LABELS`.
- `addon/globalPlugins/WordBridge/lib/catalog/fallback.py` — `FALLBACK_DOCUMENT`, `load_catalog()`.
- `addon/globalPlugins/WordBridge/lib/catalog/selection.py` — `normalize_selection()`, `SelectionState`.
- `addon/globalPlugins/WordBridge/lib/catalog/registry.py` — `initialize()`, `current()`, `reset()`.
- `addon/globalPlugins/WordBridge/settings_repository.py` — `SettingsRepository`, `LANGUAGE_VALUES`, `TYPO_CORRECTION_MODE_VALUES`, `os_default_language()`.
- `addon/globalPlugins/WordBridge/setting/ai/Coseeing-00000-default.json` — the sentinel entry (Task 7).
- `tests/test_catalog_document.py`, `tests/test_catalog_bundled.py`, `tests/test_selection_state.py`, `tests/test_catalog_fallback.py`, `tests/test_settings_repository.py`, `tests/test_import_purity.py`, `tests/test_catalog_source_seam.py`.

**Modified:**

- `configManager.py` — `ConfigManager`, `LABEL_DICT`, `make_corrector_config_id` and `normalize_selection` removed; only `CorrectorTaskConfig` / `load_corrector_task_config` remain.
- `dialogs.py` — import-time catalog and `ctypes` call removed; panel drives `SelectionState` and `SettingsRepository`.
- `__init__.py` — static config-spec defaults, catalog initialised in `GlobalPlugin.__init__`, task config loaded there too, catalog entries passed into the correction path, one-time degraded-catalog announcement.
- `lib/llm/provider.py`, `lib/llm/adapter.py`, `lib/llm/__init__.py` — stop reading files, receive entries, export `SUPPORTED_PROVIDERS`.
- `lib/application/task_factory.py`, `lib/application/task_runner.py` — pass entries through.
- `workspace/evals/provider.py` — one call site.
- `tests/test_provider_naming.py`, `tests/test_eval_provider_config.py`, `tests/test_corrector_catalog_unittest.py`, `tests/test_ai_config_schema.py`.

**Deleted:**

- `addon/globalPlugins/WordBridge/setting/provider/Coseeing.json` (Task 7).

---

### Task 1: The catalog data model and document validation

**Files:**
- Create: `addon/globalPlugins/WordBridge/lib/catalog/__init__.py`
- Create: `addon/globalPlugins/WordBridge/lib/catalog/model.py`
- Create: `addon/globalPlugins/WordBridge/lib/catalog/document.py`
- Test: `tests/test_catalog_document.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `make_corrector_config_id(model: str, provider: str | None = None) -> str`
  - `CatalogIssue(code: str, location: str, detail: str)` — frozen
  - `ProviderEntry(name, label, url, setting, timeout0, timeout_max)` — frozen
  - `ModelEntry(provider, model, label, active=True, pricing=None, usage_key=None)` — frozen; `.corrector_config_id` property, `.price_entry() -> dict`
  - `CoseeingEntry(model, label, provider=None, active=True)` — frozen; `.corrector_config_id` property
  - `SelectableItem(provider_group, corrector_config_id, execution_channel, label)` — frozen
  - `CorrectorCatalog(providers, models, coseeings, issues=(), degraded=False)` with `.provider_groups`, `.items_for(group)`, `.labels_for(group)`, `.selectable_items`, `.get_model(id)`, `.get_coseeing(id)`, `.get_provider(name)`, `.find_selection(id, channel)`, `.get_item(group_index, model_index)`, `.default_selection()`
  - `SCHEMA_VERSION = 1`
  - `build_catalog(document: dict, *, runnable_providers: frozenset[str]) -> CorrectorCatalog`
  - `COSEEING_GROUP = "Coseeing"`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_catalog_document.py`:

```python
import ast
from pathlib import Path

import pytest

from lib.catalog.document import SCHEMA_VERSION, build_catalog
from lib.catalog.model import COSEEING_GROUP, make_corrector_config_id


RUNNABLE = frozenset({"OpenAI", "DeepSeek"})

PROVIDER = {
	"label": "OpenAI",
	"url": "https://api.openai.com/v1/responses",
	"setting": {"temperature": 0.0},
	"timeout0": 10,
	"timeout_max": 20,
}


def document(**overrides):
	base = {
		"schema_version": SCHEMA_VERSION,
		"providers": {"OpenAI": dict(PROVIDER)},
		"models": [{"provider": "OpenAI", "model": "gpt-x", "label": "GPT X"}],
		"coseeings": [],
	}
	base.update(overrides)
	return base


def codes(catalog):
	return sorted(issue.code for issue in catalog.issues)


def test_identity_joins_model_and_provider():
	assert make_corrector_config_id("gpt-x", "OpenAI") == "gpt-x&OpenAI"


def test_identity_without_a_provider_is_the_bare_model():
	assert make_corrector_config_id("default") == "default"


def test_a_complete_document_yields_one_local_item():
	catalog = build_catalog(document(), runnable_providers=RUNNABLE)

	assert catalog.issues == ()
	assert [item.corrector_config_id for item in catalog.selectable_items] == ["gpt-x&OpenAI"]
	assert catalog.selectable_items[0].execution_channel == "local"
	assert catalog.labels_for("OpenAI") == ("GPT X",)


def test_a_model_without_pricing_is_kept():
	# The rule protects a future remote entry whose price has not been
	# published. The shipped instance is qwen2&Ollama, which is active: false.
	catalog = build_catalog(document(), runnable_providers=RUNNABLE)

	entry = catalog.get_model("gpt-x&OpenAI")
	assert entry.pricing is None
	assert entry.price_entry() == {}


def test_pricing_is_carried_into_the_price_entry_shape():
	doc = document(models=[{
		"provider": "OpenAI",
		"model": "gpt-x",
		"label": "GPT X",
		"pricing": {"input_tokens": 1.25, "base_unit": 1000000},
		"usage_key": "usage",
	}])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.get_model("gpt-x&OpenAI").price_entry() == {
		"model": "gpt-x",
		"provider": "OpenAI",
		"pricing": {"input_tokens": 1.25, "base_unit": 1000000},
		"usage_key": "usage",
	}


def test_a_model_naming_an_absent_provider_is_dropped():
	doc = document(models=[{"provider": "Mistral", "model": "m-large", "label": "M"}])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.selectable_items == ()
	assert "unknown_provider" in codes(catalog)


def test_a_model_whose_provider_has_no_implementation_is_dropped():
	doc = document(
		providers={"OpenAI": dict(PROVIDER), "Mistral": dict(PROVIDER, label="Mistral")},
		models=[{"provider": "Mistral", "model": "m-large", "label": "M"}],
	)
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.selectable_items == ()
	assert "unsupported_provider" in codes(catalog)


def test_a_coseeing_entry_survives_its_provider_being_absent():
	doc = document(
		models=[],
		coseeings=[{"model": "m-large", "provider": "Mistral", "label": "M large"}],
	)
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert [item.corrector_config_id for item in catalog.selectable_items] == ["m-large&Mistral"]
	assert catalog.selectable_items[0].execution_channel == COSEEING_GROUP
	assert "unknown_provider" not in codes(catalog)


def test_a_provider_entry_missing_a_required_field_is_dropped():
	broken = dict(PROVIDER)
	del broken["label"]
	catalog = build_catalog(document(providers={"OpenAI": broken}), runnable_providers=RUNNABLE)

	assert catalog.get_provider("OpenAI") is None
	assert "incomplete_provider" in codes(catalog)


def test_a_provider_no_model_names_is_a_lint_issue_only():
	doc = document(providers={"OpenAI": dict(PROVIDER), "DeepSeek": dict(PROVIDER, label="DeepSeek")})
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert [item.corrector_config_id for item in catalog.selectable_items] == ["gpt-x&OpenAI"]
	assert codes(catalog) == ["unreferenced_provider"]


def test_an_entry_with_a_separator_in_its_name_is_dropped():
	doc = document(models=[{"provider": "OpenAI", "model": "gpt&x", "label": "GPT X"}])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.selectable_items == ()
	assert "reserved_separator" in codes(catalog)


def test_an_entry_missing_its_label_is_dropped():
	doc = document(models=[{"provider": "OpenAI", "model": "gpt-x"}])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.selectable_items == ()
	assert "incomplete_entry" in codes(catalog)


def test_a_duplicate_id_keeps_the_first_entry():
	doc = document(models=[
		{"provider": "OpenAI", "model": "gpt-x", "label": "first"},
		{"provider": "OpenAI", "model": "gpt-x", "label": "second"},
	])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.labels_for("OpenAI") == ("first",)
	assert "duplicate_entry" in codes(catalog)


def test_the_same_id_on_both_channels_is_not_a_duplicate():
	doc = document(coseeings=[{"model": "gpt-x", "provider": "OpenAI", "label": "GPT X via Coseeing"}])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert codes(catalog) == []
	assert [item.execution_channel for item in catalog.selectable_items] == ["local", COSEEING_GROUP]


def test_an_inactive_entry_is_not_selectable_but_is_still_looked_up():
	doc = document(models=[{"provider": "OpenAI", "model": "gpt-x", "label": "GPT X", "active": False}])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.selectable_items == ()
	assert catalog.get_model("gpt-x&OpenAI") is not None


def test_an_unrecognised_schema_version_yields_an_empty_catalog():
	catalog = build_catalog(document(schema_version=99), runnable_providers=RUNNABLE)

	assert catalog.selectable_items == ()
	assert codes(catalog) == ["schema_version"]


def test_a_non_mapping_document_yields_an_empty_catalog():
	catalog = build_catalog("not a document", runnable_providers=RUNNABLE)

	assert catalog.selectable_items == ()
	assert codes(catalog) == ["malformed_document"]


def test_coseeing_group_sorts_last_and_local_groups_sort_alphabetically():
	doc = document(
		providers={"OpenAI": dict(PROVIDER), "DeepSeek": dict(PROVIDER, label="DeepSeek")},
		models=[
			{"provider": "OpenAI", "model": "gpt-x", "label": "GPT X"},
			{"provider": "DeepSeek", "model": "ds-x", "label": "DS X"},
		],
		coseeings=[{"model": "default", "label": "Coseeing default"}],
	)
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.provider_groups == ("DeepSeek", "OpenAI", COSEEING_GROUP)


def test_default_selection_prefers_the_first_coseeing_entry():
	doc = document(coseeings=[{"model": "default", "label": "Coseeing default"}])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	assert catalog.default_selection() == ("default", COSEEING_GROUP)


def test_default_selection_falls_back_to_the_first_local_entry():
	catalog = build_catalog(document(), runnable_providers=RUNNABLE)

	assert catalog.default_selection() == ("gpt-x&OpenAI", "local")


def test_default_selection_raises_when_nothing_is_selectable():
	catalog = build_catalog(document(models=[]), runnable_providers=RUNNABLE)

	with pytest.raises(ValueError):
		catalog.default_selection()


def test_find_selection_and_get_item_round_trip():
	doc = document(coseeings=[{"model": "default", "label": "Coseeing default"}])
	catalog = build_catalog(doc, runnable_providers=RUNNABLE)

	indices = catalog.find_selection("default", COSEEING_GROUP)
	assert indices != (-1, -1)
	assert catalog.get_item(*indices).corrector_config_id == "default"


def test_find_selection_reports_a_miss():
	catalog = build_catalog(document(), runnable_providers=RUNNABLE)

	assert catalog.find_selection("nope", "local") == (-1, -1)


CATALOG_DIR = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge" / "lib" / "catalog"
STDLIB_ONLY = {"dataclasses", "json", "pathlib", "typing", "collections", "functools", "types", "copy"}


def test_the_catalog_package_imports_only_the_standard_library():
	# Walked from the AST rather than observed at runtime, so an import that
	# merely happens not to execute cannot satisfy this.
	for path in sorted(CATALOG_DIR.glob("*.py")):
		tree = ast.parse(path.read_text(encoding="utf8"))
		for node in ast.walk(tree):
			if isinstance(node, ast.Import):
				roots = [alias.name.split(".")[0] for alias in node.names]
			elif isinstance(node, ast.ImportFrom):
				if node.level:
					continue
				roots = [(node.module or "").split(".")[0]]
			else:
				continue
			for root in roots:
				assert root in STDLIB_ONLY, f"{path.name} imports {root!r}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_catalog_document.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'lib.catalog'`.

- [ ] **Step 3: Write `lib/catalog/model.py`**

```python
from dataclasses import dataclass, field


COSEEING_GROUP = "Coseeing"
LOCAL_CHANNEL = "local"


def make_corrector_config_id(model: str, provider: str | None = None) -> str:
	"""The one identity rule.

	A local offer always joins with "&"; an entry the server provides on its
	own has no provider and gets the bare model name. The two forms cannot
	collide, because one always contains "&" and the other never does.
	"""
	if "&" in model or (provider is not None and "&" in provider):
		raise ValueError("model and provider must not contain '&'")
	return model if provider is None else f"{model}&{provider}"


@dataclass(frozen=True)
class CatalogIssue:
	code: str
	location: str
	detail: str


@dataclass(frozen=True)
class ProviderEntry:
	name: str
	label: str
	url: str
	setting: dict
	timeout0: int
	timeout_max: int


@dataclass(frozen=True)
class ModelEntry:
	provider: str
	model: str
	label: str
	active: bool = True
	pricing: dict | None = None
	usage_key: str | None = None

	@property
	def corrector_config_id(self) -> str:
		return make_corrector_config_id(self.model, self.provider)

	def price_entry(self) -> dict:
		"""The shape CostCalculator consumes.

		{} when there is no price, which is byte-for-byte what the old
		price.json lookup returned via .get(key, {}).
		"""
		if self.pricing is None:
			return {}
		return {
			"model": self.model,
			"provider": self.provider,
			"pricing": self.pricing,
			"usage_key": self.usage_key,
		}


@dataclass(frozen=True)
class CoseeingEntry:
	model: str
	label: str
	provider: str | None = None
	active: bool = True

	@property
	def corrector_config_id(self) -> str:
		return make_corrector_config_id(self.model, self.provider)


@dataclass(frozen=True)
class SelectableItem:
	provider_group: str
	corrector_config_id: str
	execution_channel: str
	label: str


@dataclass(frozen=True)
class CorrectorCatalog:
	providers: dict = field(default_factory=dict)
	models: tuple = ()
	coseeings: tuple = ()
	issues: tuple = ()
	degraded: bool = False

	def __post_init__(self):
		groups: dict[str, list] = {}
		for entry in self.models:
			if not entry.active:
				continue
			groups.setdefault(entry.provider, []).append(SelectableItem(
				provider_group=entry.provider,
				corrector_config_id=entry.corrector_config_id,
				execution_channel=LOCAL_CHANNEL,
				label=entry.label,
			))
		for entry in self.coseeings:
			if not entry.active:
				continue
			groups.setdefault(COSEEING_GROUP, []).append(SelectableItem(
				provider_group=COSEEING_GROUP,
				corrector_config_id=entry.corrector_config_id,
				execution_channel=COSEEING_GROUP,
				label=entry.label,
			))
		object.__setattr__(self, "_groups", {name: tuple(items) for name, items in groups.items()})

	@property
	def provider_groups(self) -> tuple:
		local = sorted(name for name in self._groups if name != COSEEING_GROUP)
		if COSEEING_GROUP in self._groups:
			return tuple(local + [COSEEING_GROUP])
		return tuple(local)

	def items_for(self, provider_group: str) -> tuple:
		return self._groups.get(provider_group, ())

	def labels_for(self, provider_group: str) -> tuple:
		return tuple(item.label for item in self.items_for(provider_group))

	@property
	def selectable_items(self) -> tuple:
		return tuple(
			item
			for group in self.provider_groups
			for item in self._groups[group]
		)

	def get_model(self, corrector_config_id: str):
		for entry in self.models:
			if entry.corrector_config_id == corrector_config_id:
				return entry
		return None

	def get_coseeing(self, corrector_config_id: str):
		for entry in self.coseeings:
			if entry.corrector_config_id == corrector_config_id:
				return entry
		return None

	def get_provider(self, name: str):
		return self.providers.get(name)

	def find_selection(self, corrector_config_id: str, execution_channel: str) -> tuple:
		for group_index, group in enumerate(self.provider_groups):
			for model_index, item in enumerate(self._groups[group]):
				if (
					item.corrector_config_id == corrector_config_id
					and item.execution_channel == execution_channel
				):
					return (group_index, model_index)
		return (-1, -1)

	def get_item(self, group_index: int, model_index: int) -> SelectableItem:
		group = self.provider_groups[group_index]
		return self._groups[group][model_index]

	def default_selection(self) -> tuple:
		for item in self.items_for(COSEEING_GROUP):
			return (item.corrector_config_id, item.execution_channel)
		for item in self.selectable_items:
			return (item.corrector_config_id, item.execution_channel)
		raise ValueError("No selectable corrector entries available")
```

- [ ] **Step 4: Write `lib/catalog/document.py`**

```python
from .model import (
	CatalogIssue,
	CoseeingEntry,
	CorrectorCatalog,
	ModelEntry,
	ProviderEntry,
)


SCHEMA_VERSION = 1
PROVIDER_FIELDS = ("label", "url", "setting", "timeout0", "timeout_max")


def _text(value) -> bool:
	return isinstance(value, str) and value != ""


def build_catalog(document, *, runnable_providers) -> CorrectorCatalog:
	"""Always returns a catalog. Problems become issues, never exceptions."""
	issues = []
	if not isinstance(document, dict):
		issues.append(CatalogIssue("malformed_document", "document", f"expected a mapping, got {type(document).__name__}"))
		return CorrectorCatalog(issues=tuple(issues))
	if document.get("schema_version") != SCHEMA_VERSION:
		issues.append(CatalogIssue(
			"schema_version",
			"document",
			f"expected {SCHEMA_VERSION}, got {document.get('schema_version')!r}",
		))
		return CorrectorCatalog(issues=tuple(issues))

	providers = _build_providers(document.get("providers"), issues)
	models = _build_models(document.get("models"), providers, runnable_providers, issues)
	coseeings = _build_coseeings(document.get("coseeings"), issues)

	named = {entry.provider for entry in models}
	for name in sorted(set(providers) - named):
		issues.append(CatalogIssue("unreferenced_provider", f"providers.{name}", "no models entry names this provider"))

	return CorrectorCatalog(
		providers=providers,
		models=models,
		coseeings=coseeings,
		issues=tuple(issues),
	)


def _build_providers(raw, issues) -> dict:
	providers = {}
	if not isinstance(raw, dict):
		return providers
	for name in sorted(raw):
		location = f"providers.{name}"
		data = raw[name]
		if not _text(name) or "&" in name:
			issues.append(CatalogIssue("reserved_separator", location, "provider name is empty or contains '&'"))
			continue
		if not isinstance(data, dict):
			issues.append(CatalogIssue("incomplete_provider", location, "entry is not a mapping"))
			continue
		missing = [key for key in PROVIDER_FIELDS if key not in data or data[key] in ("", None)]
		if missing:
			issues.append(CatalogIssue("incomplete_provider", location, f"missing {', '.join(missing)}"))
			continue
		providers[name] = ProviderEntry(
			name=name,
			label=data["label"],
			url=data["url"],
			setting=data["setting"],
			timeout0=data["timeout0"],
			timeout_max=data["timeout_max"],
		)
	return providers


def _build_models(raw, providers, runnable_providers, issues) -> tuple:
	entries = []
	seen = set()
	for index, data in enumerate(raw or ()):
		location = f"models[{index}]"
		if not isinstance(data, dict):
			issues.append(CatalogIssue("incomplete_entry", location, "entry is not a mapping"))
			continue
		model, provider, label = data.get("model"), data.get("provider"), data.get("label")
		if not (_text(model) and _text(provider) and _text(label)):
			issues.append(CatalogIssue("incomplete_entry", location, "model, provider and label are all required"))
			continue
		if "&" in model or "&" in provider:
			issues.append(CatalogIssue("reserved_separator", location, "model and provider must not contain '&'"))
			continue
		active = data.get("active", True)
		if not isinstance(active, bool):
			issues.append(CatalogIssue("invalid_active", location, f"active must be a boolean, got {active!r}"))
			continue
		if provider not in providers:
			issues.append(CatalogIssue("unknown_provider", location, f"no providers entry for {provider!r}"))
			continue
		if provider not in runnable_providers:
			issues.append(CatalogIssue("unsupported_provider", location, f"this build has no implementation for {provider!r}"))
			continue
		entry = ModelEntry(
			provider=provider,
			model=model,
			label=label,
			active=active,
			pricing=data.get("pricing"),
			usage_key=data.get("usage_key"),
		)
		if entry.corrector_config_id in seen:
			issues.append(CatalogIssue("duplicate_entry", location, f"{entry.corrector_config_id!r} already defined"))
			continue
		seen.add(entry.corrector_config_id)
		entries.append(entry)
	return tuple(entries)


def _build_coseeings(raw, issues) -> tuple:
	entries = []
	seen = set()
	for index, data in enumerate(raw or ()):
		location = f"coseeings[{index}]"
		if not isinstance(data, dict):
			issues.append(CatalogIssue("incomplete_entry", location, "entry is not a mapping"))
			continue
		model, label, provider = data.get("model"), data.get("label"), data.get("provider")
		if not (_text(model) and _text(label)):
			issues.append(CatalogIssue("incomplete_entry", location, "model and label are both required"))
			continue
		if provider is not None and not _text(provider):
			issues.append(CatalogIssue("incomplete_entry", location, "provider, when present, must be a non-empty string"))
			continue
		if "&" in model or (provider is not None and "&" in provider):
			issues.append(CatalogIssue("reserved_separator", location, "model and provider must not contain '&'"))
			continue
		active = data.get("active", True)
		if not isinstance(active, bool):
			issues.append(CatalogIssue("invalid_active", location, f"active must be a boolean, got {active!r}"))
			continue
		entry = CoseeingEntry(model=model, label=label, provider=provider, active=active)
		if entry.corrector_config_id in seen:
			issues.append(CatalogIssue("duplicate_entry", location, f"{entry.corrector_config_id!r} already defined"))
			continue
		seen.add(entry.corrector_config_id)
		entries.append(entry)
	return tuple(entries)
```

- [ ] **Step 5: Write `lib/catalog/__init__.py`**

```python
from .document import SCHEMA_VERSION, build_catalog
from .model import (
	COSEEING_GROUP,
	LOCAL_CHANNEL,
	CatalogIssue,
	CorrectorCatalog,
	CoseeingEntry,
	ModelEntry,
	ProviderEntry,
	SelectableItem,
	make_corrector_config_id,
)

__all__ = [
	"COSEEING_GROUP",
	"LOCAL_CHANNEL",
	"SCHEMA_VERSION",
	"CatalogIssue",
	"CorrectorCatalog",
	"CoseeingEntry",
	"ModelEntry",
	"ProviderEntry",
	"SelectableItem",
	"build_catalog",
	"make_corrector_config_id",
]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_catalog_document.py -q`
Expected: PASS, every test.

- [ ] **Step 7: Run the whole suite**

Run: `python3 -m pytest -q -m "not integration"`
Expected: 343 + 25 passed, 1 skipped, 16 deselected. No failures.

- [ ] **Step 8: Commit**

```bash
git add addon/globalPlugins/WordBridge/lib/catalog tests/test_catalog_document.py
git commit -m "feat: add the corrector catalog data model and document validation"
```

---

### Task 2: `BundledCatalogSource` and the characterization test

This task must land **before** anything is removed: the characterization test uses the current `ConfigManager` as its oracle, so `ConfigManager` has to still exist and still be correct while it is written.

**Files:**
- Create: `addon/globalPlugins/WordBridge/lib/catalog/sources.py`
- Test: `tests/test_catalog_bundled.py` (create)

**Interfaces:**
- Consumes: `build_catalog`, `SCHEMA_VERSION`, `make_corrector_config_id` from Task 1.
- Produces:
  - `BUNDLED_LABELS: dict[str, str]` — the display-name map lifted out of `configManager.LABEL_DICT`, model and provider names only, with `_()` removed.
  - `BundledCatalogSource(setting_dir)` with `load() -> tuple[dict, tuple[CatalogIssue, ...]]`.

**Note on the `load()` signature.** The spec describes a source as producing the document. A source also has read-level failures of its own — a file that is not valid JSON — that cannot be expressed inside the document. Returning `(document, issues)` lets a corrupt `setting/ai/*.json` be reported rather than silently vanish, and gives a future `RemoteCatalogSource` the same place to report a 500 or a truncated body.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_catalog_bundled.py`:

```python
import json
from pathlib import Path

from lib.catalog.document import SCHEMA_VERSION, build_catalog
from lib.catalog.model import COSEEING_GROUP
from lib.catalog.sources import BUNDLED_LABELS, BundledCatalogSource


ADDON_PATH = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge"
SETTING_DIR = ADDON_PATH / "setting"
RUNNABLE = frozenset({"OpenAI", "Anthropic", "Google", "OpenRouter", "DeepSeek", "Ollama"})


def shipped_catalog():
	document, issues = BundledCatalogSource(SETTING_DIR).load()
	assert issues == ()
	return build_catalog(document, runnable_providers=RUNNABLE)


def legacy_manager():
	from configManager import ConfigManager

	return ConfigManager(SETTING_DIR / "ai")


def test_the_bundled_document_declares_the_current_schema_version():
	document, _ = BundledCatalogSource(SETTING_DIR).load()

	assert document["schema_version"] == SCHEMA_VERSION
	assert set(document) == {"schema_version", "providers", "models", "coseeings"}


def test_provider_groups_match_the_legacy_manager():
	assert shipped_catalog().provider_groups == tuple(legacy_manager().provider_groups)


def test_every_group_offers_the_same_labels_as_the_legacy_manager():
	catalog, manager = shipped_catalog(), legacy_manager()

	for group in manager.provider_groups:
		manager.provider = group
		assert catalog.labels_for(group) == tuple(manager.model_labels), group


def test_every_selectable_item_matches_the_legacy_manager():
	catalog, manager = shipped_catalog(), legacy_manager()

	expected = [
		(item.provider_group, item.corrector_config_id, item.execution_channel)
		for group in manager.provider_groups
		for item in manager.endpoints[group]
	]
	actual = [
		(item.provider_group, item.corrector_config_id, item.execution_channel)
		for item in catalog.selectable_items
	]
	assert actual == expected


def test_default_selection_matches_the_legacy_manager():
	assert shipped_catalog().default_selection() == legacy_manager().default_selection()


def test_every_price_entry_matches_price_json():
	price = json.loads((SETTING_DIR / "price.json").read_text(encoding="utf8"))
	catalog = shipped_catalog()

	for entry in catalog.models:
		assert entry.price_entry() == price.get(entry.corrector_config_id, {}), entry.corrector_config_id


def test_every_provider_entry_matches_its_json_file():
	catalog = shipped_catalog()

	for path in (SETTING_DIR / "provider").glob("*.json"):
		entry = catalog.get_provider(path.stem)
		if entry is None:
			continue
		data = json.loads(path.read_text(encoding="utf8"))
		assert (entry.url, entry.setting, entry.timeout0, entry.timeout_max) == (
			data["url"], data["setting"], data["timeout0"], data["timeout_max"]
		), path.name
		assert entry.label == BUNDLED_LABELS.get(path.stem, path.stem)


def test_the_shipped_data_produces_only_the_known_lint_issues():
	# OpenRouter.json is named by no ai config. Coseeing.json is removed in a
	# later task; until then it is unreferenced too.
	catalog = shipped_catalog()

	assert sorted(issue.code for issue in catalog.issues) == [
		"unreferenced_provider",
		"unreferenced_provider",
	]
	assert sorted(issue.location for issue in catalog.issues) == [
		"providers.Coseeing",
		"providers.OpenRouter",
	]


def test_an_ai_file_without_a_provider_becomes_a_coseeing_only_entry(tmp_path):
	_write_minimal_setting_tree(tmp_path)
	(tmp_path / "ai" / "Coseeing-00000-default.json").write_text(
		json.dumps({"active": True, "model": "default", "coseeing": True}), encoding="utf8"
	)
	document, issues = BundledCatalogSource(tmp_path).load()

	assert issues == ()
	assert [entry["model"] for entry in document["coseeings"]] == ["default"]
	assert document["models"] == []


def test_a_corrupt_ai_file_is_reported_and_skipped(tmp_path):
	_write_minimal_setting_tree(tmp_path)
	(tmp_path / "ai" / "OpenAI-00001-gpt-x.json").write_text(
		json.dumps({"active": True, "model": "gpt-x", "provider": "OpenAI", "coseeing": False}),
		encoding="utf8",
	)
	(tmp_path / "ai" / "Broken-00001.json").write_text("{not json", encoding="utf8")
	document, issues = BundledCatalogSource(tmp_path).load()

	assert [entry["model"] for entry in document["models"]] == ["gpt-x"]
	assert [issue.code for issue in issues] == ["unreadable_file"]


def _write_minimal_setting_tree(root: Path):
	(root / "ai").mkdir(parents=True)
	(root / "provider").mkdir(parents=True)
	(root / "provider" / "OpenAI.json").write_text(
		json.dumps({
			"name": "OpenAI",
			"url": "https://example.invalid",
			"setting": {},
			"timeout0": 10,
			"timeout_max": 20,
		}),
		encoding="utf8",
	)
	(root / "price.json").write_text("{}", encoding="utf8")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_catalog_bundled.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'lib.catalog.sources'`.

- [ ] **Step 3: Write `lib/catalog/sources.py`**

Copy the model and provider display names out of `configManager.LABEL_DICT` **without** the `_()` wrapper, and leave the UI strings behind. The full map:

```python
import json
from pathlib import Path

from .document import SCHEMA_VERSION
from .model import CatalogIssue


# Display names, lifted from configManager.LABEL_DICT. Not translated: every
# entry maps a name to itself apart from gemini-3.1-pro-preview, which is a
# rename. lib/catalog cannot reach NVDA's translation builtin, and a model
# name is not translatable content.
BUNDLED_LABELS = {
	"Anthropic": "Anthropic",
	"Coseeing": "Coseeing",
	"DeepSeek": "DeepSeek",
	"Google": "Google",
	"OpenAI": "OpenAI",
	"claude-opus-5": "claude-opus-5",
	"claude-sonnet-5": "claude-sonnet-5",
	"deepseek-v4-flash": "deepseek-v4-flash",
	"deepseek-v4-pro": "deepseek-v4-pro",
	"gemini-3.1-pro-preview": "gemini-3.1-pro",
	"gemini-3.1-flash-lite": "gemini-3.1-flash-lite",
	"gemini-3.5-flash-lite": "gemini-3.5-flash-lite",
	"gemini-3.7-flash": "gemini-3.7-flash",
	"gemini-3.8-flash": "gemini-3.8-flash",
	"gpt-5.6-sol": "gpt-5.6-sol",
	"gpt-5.6-terra": "gpt-5.6-terra",
	"gpt-5.6-luna": "gpt-5.6-luna",
}


class BundledCatalogSource:
	"""Flattens the shipped setting/ tree into one catalog document.

	This is the only place that knows the on-disk layout. A future
	RemoteCatalogSource implements the same load() and returns the same
	document shape, so nothing downstream changes.
	"""

	def __init__(self, setting_dir):
		self.setting_dir = Path(setting_dir)

	def load(self) -> tuple:
		issues = []
		price = self._read_json(self.setting_dir / "price.json", issues) or {}
		providers = {}
		for path in sorted((self.setting_dir / "provider").glob("*.json")):
			data = self._read_json(path, issues)
			if data is None:
				continue
			providers[path.stem] = {
				"label": BUNDLED_LABELS.get(path.stem, path.stem),
				"url": data.get("url"),
				"setting": data.get("setting"),
				"timeout0": data.get("timeout0"),
				"timeout_max": data.get("timeout_max"),
			}

		models = []
		coseeings = []
		for path in sorted((self.setting_dir / "ai").glob("*.json")):
			data = self._read_json(path, issues)
			if data is None:
				continue
			model = data.get("model")
			provider = data.get("provider")
			active = data.get("active", True)
			label = BUNDLED_LABELS.get(model, model)
			if provider is None:
				# No provider means no local offer: the server serves it alone.
				coseeings.append({"model": model, "label": label, "active": active})
				continue
			key = f"{model}&{provider}"
			entry = {
				"provider": provider,
				"model": model,
				"label": label,
				"active": active,
			}
			priced = price.get(key)
			if priced:
				entry["pricing"] = priced.get("pricing")
				entry["usage_key"] = priced.get("usage_key")
			models.append(entry)
			if data.get("coseeing"):
				coseeings.append({
					"model": model,
					"provider": provider,
					"label": label,
					"active": active,
				})

		document = {
			"schema_version": SCHEMA_VERSION,
			"providers": providers,
			"models": models,
			"coseeings": coseeings,
		}
		return document, tuple(issues)

	def _read_json(self, path, issues):
		try:
			with path.open("r", encoding="utf8") as handle:
				return json.load(handle)
		except (OSError, ValueError) as error:
			issues.append(CatalogIssue(
				"unreadable_file",
				str(path.name),
				f"{type(error).__name__}: {error}",
			))
			return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_catalog_bundled.py -q`
Expected: PASS.

If `test_every_group_offers_the_same_labels_as_the_legacy_manager` fails for `Ollama` or `OpenRouter`, the cause is `BUNDLED_LABELS` missing an entry — the legacy fallback is `LABEL_DICT.get(item, item)`, which `BUNDLED_LABELS.get(name, name)` reproduces. Do not add entries for names `LABEL_DICT` did not have.

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m pytest -q -m "not integration"`
Expected: no failures.

- [ ] **Step 6: Commit**

```bash
git add addon/globalPlugins/WordBridge/lib/catalog/sources.py tests/test_catalog_bundled.py
git commit -m "feat: flatten the shipped setting tree into a catalog document"
```

---

### Task 3: Selection state, normalisation, fallback and the registry

**Files:**
- Create: `addon/globalPlugins/WordBridge/lib/catalog/selection.py`
- Create: `addon/globalPlugins/WordBridge/lib/catalog/fallback.py`
- Create: `addon/globalPlugins/WordBridge/lib/catalog/registry.py`
- Test: `tests/test_selection_state.py` (create)
- Test: `tests/test_catalog_fallback.py` (create)

**Interfaces:**
- Consumes: everything from Tasks 1 and 2.
- Produces:
  - `normalize_selection(catalog, corrector_config_id, execution_channel) -> tuple[str, str]`
  - `SelectionState(catalog, provider_group_index, model_index)` with `.restore(catalog, corrector_config_id, execution_channel)` classmethod, `.provider_group`, `.choose_provider_group(index)`, `.current_item()`
  - `SENTINEL_ID = "default"`, `SENTINEL_LABEL`, `FALLBACK_DOCUMENT`
  - `load_catalog(source, *, runnable_providers) -> CorrectorCatalog`
  - `registry.initialize(catalog)`, `registry.current()`, `registry.reset()`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_selection_state.py`:

```python
import pytest

from lib.catalog.document import SCHEMA_VERSION, build_catalog
from lib.catalog.model import COSEEING_GROUP
from lib.catalog.selection import SelectionState, normalize_selection


RUNNABLE = frozenset({"OpenAI", "DeepSeek"})

PROVIDER = {
	"label": "x",
	"url": "https://example.invalid",
	"setting": {},
	"timeout0": 10,
	"timeout_max": 20,
}


def catalog():
	return build_catalog(
		{
			"schema_version": SCHEMA_VERSION,
			"providers": {"OpenAI": dict(PROVIDER), "DeepSeek": dict(PROVIDER)},
			"models": [
				{"provider": "DeepSeek", "model": "ds-x", "label": "DS X"},
				{"provider": "OpenAI", "model": "gpt-x", "label": "GPT X"},
			],
			"coseeings": [
				{"model": "default", "label": "Coseeing default"},
				{"model": "ds-x", "provider": "DeepSeek", "label": "DS X"},
			],
		},
		runnable_providers=RUNNABLE,
	)


def test_a_valid_selection_is_returned_unchanged():
	assert normalize_selection(catalog(), "gpt-x&OpenAI", "local") == ("gpt-x&OpenAI", "local")


def test_an_unknown_id_falls_back_to_the_catalog_default():
	assert normalize_selection(catalog(), "nope", "local") == ("default", COSEEING_GROUP)


def test_an_empty_id_falls_back_to_the_catalog_default():
	assert normalize_selection(catalog(), "", "") == ("default", COSEEING_GROUP)


def test_a_channel_the_entry_does_not_offer_falls_back_to_the_other_one():
	assert normalize_selection(catalog(), "gpt-x&OpenAI", COSEEING_GROUP) == ("gpt-x&OpenAI", "local")


def test_a_coseeing_only_entry_asked_for_locally_stays_on_coseeing():
	assert normalize_selection(catalog(), "default", "local") == ("default", COSEEING_GROUP)


def test_an_unrecognised_channel_name_is_normalised():
	assert normalize_selection(catalog(), "gpt-x&OpenAI", "nonsense") == ("gpt-x&OpenAI", "local")


def test_restore_finds_the_stored_selection():
	state = SelectionState.restore(catalog(), "gpt-x&OpenAI", "local")

	assert state.provider_group == "OpenAI"
	assert state.current_item().corrector_config_id == "gpt-x&OpenAI"


def test_restore_falls_back_to_the_default_for_an_unknown_selection():
	state = SelectionState.restore(catalog(), "nope", "local")

	assert state.provider_group == COSEEING_GROUP
	assert state.current_item().corrector_config_id == "default"


def test_choosing_a_group_resets_the_model_index():
	state = SelectionState.restore(catalog(), "default", COSEEING_GROUP)
	coseeing_index = catalog().provider_groups.index(COSEEING_GROUP)
	state.choose_provider_group(coseeing_index)
	state.model_index = 1
	assert state.current_item().corrector_config_id == "ds-x&DeepSeek"

	state.choose_provider_group(0)

	assert state.provider_group == "DeepSeek"
	assert state.model_index == 0


def test_restore_raises_only_when_the_catalog_is_empty():
	empty = build_catalog({"schema_version": SCHEMA_VERSION}, runnable_providers=RUNNABLE)

	with pytest.raises(ValueError):
		SelectionState.restore(empty, "anything", "local")
```

Create `tests/test_catalog_fallback.py`:

```python
import pytest

from lib.catalog import registry
from lib.catalog.document import SCHEMA_VERSION, build_catalog
from lib.catalog.fallback import FALLBACK_DOCUMENT, SENTINEL_ID, load_catalog
from lib.catalog.model import COSEEING_GROUP
from lib.catalog.selection import normalize_selection


RUNNABLE = frozenset({"OpenAI"})


class FakeSource:
	def __init__(self, document, issues=()):
		self.document = document
		self.issues = tuple(issues)

	def load(self):
		return self.document, self.issues


def test_a_usable_document_is_not_replaced():
	document = {
		"schema_version": SCHEMA_VERSION,
		"providers": {"OpenAI": {
			"label": "OpenAI",
			"url": "https://example.invalid",
			"setting": {},
			"timeout0": 10,
			"timeout_max": 20,
		}},
		"models": [{"provider": "OpenAI", "model": "gpt-x", "label": "GPT X"}],
		"coseeings": [],
	}
	catalog = load_catalog(FakeSource(document), runnable_providers=RUNNABLE)

	assert catalog.degraded is False
	assert [item.corrector_config_id for item in catalog.selectable_items] == ["gpt-x&OpenAI"]


def test_an_unusable_document_falls_back_to_the_sentinel():
	catalog = load_catalog(FakeSource({"schema_version": 99}), runnable_providers=RUNNABLE)

	assert catalog.degraded is True
	assert [item.corrector_config_id for item in catalog.selectable_items] == [SENTINEL_ID]
	assert catalog.selectable_items[0].provider_group == COSEEING_GROUP
	assert catalog.selectable_items[0].execution_channel == COSEEING_GROUP


def test_the_fallback_keeps_the_issues_that_explain_it():
	catalog = load_catalog(FakeSource({"schema_version": 99}), runnable_providers=RUNNABLE)

	assert "schema_version" in {issue.code for issue in catalog.issues}


def test_source_level_issues_reach_the_catalog():
	from lib.catalog.model import CatalogIssue

	document = {"schema_version": SCHEMA_VERSION, "providers": {}, "models": [], "coseeings": []}
	source = FakeSource(document, [CatalogIssue("unreadable_file", "x.json", "boom")])
	catalog = load_catalog(source, runnable_providers=RUNNABLE)

	assert "unreadable_file" in {issue.code for issue in catalog.issues}


def test_the_fallback_document_and_a_shipped_sentinel_produce_the_same_item():
	fallback = load_catalog(FakeSource({"schema_version": 99}), runnable_providers=RUNNABLE)
	shipped = build_catalog(
		{
			"schema_version": SCHEMA_VERSION,
			"providers": {},
			"models": [],
			"coseeings": list(FALLBACK_DOCUMENT["coseeings"]),
		},
		runnable_providers=RUNNABLE,
	)

	assert fallback.selectable_items == shipped.selectable_items


def test_a_stored_sentinel_still_resolves_against_a_healthy_catalog():
	document = {
		"schema_version": SCHEMA_VERSION,
		"providers": {},
		"models": [],
		"coseeings": [
			{"model": SENTINEL_ID, "label": "Coseeing default"},
			{"model": "ds-x", "provider": "DeepSeek", "label": "DS X"},
		],
	}
	catalog = build_catalog(document, runnable_providers=RUNNABLE)

	assert normalize_selection(catalog, SENTINEL_ID, COSEEING_GROUP) == (SENTINEL_ID, COSEEING_GROUP)


def test_the_registry_refuses_to_answer_before_it_is_initialised():
	registry.reset()

	with pytest.raises(RuntimeError):
		registry.current()


def test_the_registry_returns_what_was_installed():
	catalog = load_catalog(FakeSource({"schema_version": 99}), runnable_providers=RUNNABLE)
	registry.initialize(catalog)
	try:
		assert registry.current() is catalog
	finally:
		registry.reset()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_selection_state.py tests/test_catalog_fallback.py -q`
Expected: collection errors for `lib.catalog.selection`, `lib.catalog.fallback` and `lib.catalog.registry`.

- [ ] **Step 3: Write `lib/catalog/selection.py`**

```python
from .model import COSEEING_GROUP, LOCAL_CHANNEL


def normalize_selection(catalog, corrector_config_id: str, execution_channel: str) -> tuple:
	"""Resolve a stored selection against a catalog.

	Membership decides the channel: an id in coseeings can run on Coseeing, an
	id in models can run locally. Anything unresolvable becomes the catalog's
	default, which is why an empty stored value -- what a fresh install has,
	now that the config spec defaults are static -- lands on the default too.
	"""
	on_coseeing = catalog.get_coseeing(corrector_config_id) is not None
	on_local = catalog.get_model(corrector_config_id) is not None

	if execution_channel == COSEEING_GROUP and on_coseeing:
		return (corrector_config_id, COSEEING_GROUP)
	if execution_channel == LOCAL_CHANNEL and on_local:
		return (corrector_config_id, LOCAL_CHANNEL)
	if on_local:
		return (corrector_config_id, LOCAL_CHANNEL)
	if on_coseeing:
		return (corrector_config_id, COSEEING_GROUP)
	return catalog.default_selection()


class SelectionState:
	"""What the settings panel currently has selected.

	This is deliberately not on the catalog: the catalog answers the same
	question for everyone, and the panel's in-progress choice is nobody
	else's business. It was ConfigManager.provider that forced the two
	together.
	"""

	def __init__(self, catalog, provider_group_index: int, model_index: int):
		self.catalog = catalog
		self.provider_group_index = provider_group_index
		self.model_index = model_index

	@classmethod
	def restore(cls, catalog, corrector_config_id: str, execution_channel: str) -> "SelectionState":
		corrector_config_id, execution_channel = normalize_selection(
			catalog, corrector_config_id, execution_channel
		)
		indices = catalog.find_selection(corrector_config_id, execution_channel)
		if indices == (-1, -1):
			indices = catalog.find_selection(*catalog.default_selection())
		return cls(catalog, indices[0], indices[1])

	@property
	def provider_group(self) -> str:
		return self.catalog.provider_groups[self.provider_group_index]

	def choose_provider_group(self, index: int) -> None:
		self.provider_group_index = index
		self.model_index = 0

	def current_item(self):
		return self.catalog.get_item(self.provider_group_index, self.model_index)
```

- [ ] **Step 4: Write `lib/catalog/fallback.py`**

```python
from .document import SCHEMA_VERSION, build_catalog


SENTINEL_ID = "default"
# Not translated, like every other catalog label. See the note in sources.py.
SENTINEL_LABEL = "Coseeing default"

# One entry, the same shape as any other document, parsed by the same
# build_catalog(). The id is a sentinel the Coseeing server resolves to its
# own current model, which is why no model, provider or price string is
# hard-coded here.
FALLBACK_DOCUMENT = {
	"schema_version": SCHEMA_VERSION,
	"providers": {},
	"models": [],
	"coseeings": [{"model": SENTINEL_ID, "label": SENTINEL_LABEL, "active": True}],
}


def load_catalog(source, *, runnable_providers):
	"""Build a catalog from a source, degrading to the sentinel when empty."""
	document, source_issues = source.load()
	catalog = build_catalog(document, runnable_providers=runnable_providers)
	issues = tuple(source_issues) + catalog.issues
	if catalog.selectable_items:
		return type(catalog)(
			providers=catalog.providers,
			models=catalog.models,
			coseeings=catalog.coseeings,
			issues=issues,
			degraded=False,
		)
	fallback = build_catalog(FALLBACK_DOCUMENT, runnable_providers=runnable_providers)
	return type(fallback)(
		providers=fallback.providers,
		models=fallback.models,
		coseeings=fallback.coseeings,
		issues=issues + fallback.issues,
		degraded=True,
	)
```

- [ ] **Step 5: Write `lib/catalog/registry.py`**

```python
_CATALOG = None


def initialize(catalog) -> None:
	"""Install the process-wide catalog. Called once, from GlobalPlugin.__init__.

	This is a single value, but an explicitly installed one. The import-time
	construction it replaces ran whenever dialogs.py was imported, which made
	a damaged configuration a load failure for the whole add-on.
	"""
	global _CATALOG
	_CATALOG = catalog


def current():
	if _CATALOG is None:
		raise RuntimeError("catalog registry used before initialize()")
	return _CATALOG


def reset() -> None:
	"""Test hook. Production never calls this."""
	global _CATALOG
	_CATALOG = None
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_selection_state.py tests/test_catalog_fallback.py -q`
Expected: PASS.

- [ ] **Step 7: Run the whole suite**

Run: `python3 -m pytest -q -m "not integration"`
Expected: no failures.

- [ ] **Step 8: Commit**

```bash
git add addon/globalPlugins/WordBridge/lib/catalog tests/test_selection_state.py tests/test_catalog_fallback.py
git commit -m "feat: add selection state, catalog fallback and the registry"
```

---

### Task 4: Inject provider and price entries into the LLM layer

**Files:**
- Modify: `addon/globalPlugins/WordBridge/lib/llm/provider.py:29-41`, `:190-204`
- Modify: `addon/globalPlugins/WordBridge/lib/llm/adapter.py:10-15`, `:43-48`, `:147-160`
- Modify: `addon/globalPlugins/WordBridge/lib/llm/__init__.py`
- Modify: `addon/globalPlugins/WordBridge/lib/application/task_factory.py:9-25`
- Modify: `addon/globalPlugins/WordBridge/lib/application/task_runner.py`
- Modify: `workspace/evals/provider.py:212-225`
- Modify: `tests/test_provider_naming.py`
- Modify: `tests/test_eval_provider_config.py`

**Interfaces:**
- Consumes: `ProviderEntry`, `ModelEntry.price_entry()`, `BundledCatalogSource`, `build_catalog` from Tasks 1–2.
- Produces:
  - `lib.llm.provider.PROVIDER_CLASSES: dict[str, type]`
  - `lib.llm.adapter.ADAPTER_CLASSES: dict[str, type]`
  - `lib.llm.SUPPORTED_PROVIDERS: frozenset[str]`
  - `get_provider(provider_name, credential, retries=2, backoff=1, *, provider_entry) -> Provider`
  - `get_provider_model_adapter(provider_name, model_name, *, price_entry) -> ProviderModelAdapter`
  - `create_typo_workflow(..., *, provider_entry, price_entry, ...)`
  - `run_typo_correction(..., provider_entry=..., price_entry=...)`

- [ ] **Step 1: Write the failing tests**

Replace the body of `tests/test_provider_naming.py` with a catalog-derived version:

```python
import json
from pathlib import Path

import pytest

from lib.catalog.document import build_catalog
from lib.catalog.sources import BundledCatalogSource
from lib.llm import SUPPORTED_PROVIDERS
from lib.llm.adapter import ADAPTER_CLASSES
from lib.llm.provider import PROVIDER_CLASSES, get_provider


SETTING_DIR = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge" / "setting"
PROVIDER_CONFIG_DIR = SETTING_DIR / "provider"
AI_CONFIG_DIR = SETTING_DIR / "ai"
PRICE_PATH = SETTING_DIR / "price.json"


def catalog():
	document, issues = BundledCatalogSource(SETTING_DIR).load()
	assert issues == ()
	return build_catalog(document, runnable_providers=SUPPORTED_PROVIDERS)


def test_the_provider_and_adapter_family_tables_agree():
	# A name in one table and not the other is a model the user can select and
	# cannot run.
	assert set(PROVIDER_CLASSES) == set(ADAPTER_CLASSES)
	assert SUPPORTED_PROVIDERS == frozenset(PROVIDER_CLASSES)


def test_every_provider_config_filename_is_the_canonical_provider_name():
	for path in PROVIDER_CONFIG_DIR.glob("*.json"):
		assert path.stem == path.stem.strip(), path.name
		if path.stem not in SUPPORTED_PROVIDERS:
			continue
		entry = catalog().get_provider(path.stem)
		provider = get_provider(path.stem, {"api_key": "test"}, provider_entry=entry)
		assert provider.name == path.stem


def test_every_ai_config_names_an_existing_provider_config():
	for path in AI_CONFIG_DIR.glob("*.json"):
		provider = json.loads(path.read_text(encoding="utf8")).get("provider")
		if provider is None:
			continue
		assert (PROVIDER_CONFIG_DIR / f"{provider}.json").exists(), (
			f"{path.name} names provider {provider!r} with no setting/provider/{provider}.json"
		)


def test_every_active_ai_config_has_a_price_entry():
	price = json.loads(PRICE_PATH.read_text(encoding="utf8"))

	for path in AI_CONFIG_DIR.glob("*.json"):
		data = json.loads(path.read_text(encoding="utf8"))
		if not data.get("active") or data.get("provider") is None:
			continue
		key = f"{data['model']}&{data['provider']}"
		assert key in price, f"{path.name} has no price.json entry for {key!r}"


def test_provider_lookup_does_not_fall_back_to_a_case_insensitive_glob():
	source = (PROVIDER_CONFIG_DIR.parents[1] / "lib" / "llm" / "provider.py").read_text(encoding="utf8")

	assert "casefold()" not in source


def test_the_provider_no_longer_reads_its_settings_from_disk():
	source = (PROVIDER_CONFIG_DIR.parents[1] / "lib" / "llm" / "provider.py").read_text(encoding="utf8")

	assert "setting_name" not in source
	assert '"setting"' not in source or "setting_dir" not in source


def test_provider_factory_accepts_canonical_provider_name_only():
	entry = catalog().get_provider("OpenAI")
	provider = get_provider("OpenAI", {"api_key": "test"}, provider_entry=entry)

	assert provider.name == "OpenAI"
	assert provider.url == entry.url
	assert provider.timeout_max == entry.timeout_max


@pytest.mark.parametrize("provider_name", ["openai", "OPENAI", "Openai", "OpenAIResponse"])
def test_provider_factory_rejects_non_canonical_provider_names(provider_name):
	entry = catalog().get_provider("OpenAI")

	with pytest.raises(ValueError, match=f"Unsupported provider: {provider_name}"):
		get_provider(provider_name, {"api_key": "test"}, provider_entry=entry)


def test_deepseek_provider_top_p_is_within_valid_range():
	entry = catalog().get_provider("DeepSeek")

	assert 0.0 < entry.setting["top_p"] <= 1.0


def test_the_workflow_factory_requires_both_entries():
	from lib.application.task_factory import create_typo_workflow

	with pytest.raises(TypeError):
		create_typo_workflow(
			provider_name="OpenAI",
			model_name="gpt-5.6-sol",
			credential={"api_key": "test"},
			language="zh_traditional",
			template_name="Standard_v1.json",
			corrector_mode="standard",
			optional_guidance_enable={},
		)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_provider_naming.py -q`
Expected: `ImportError: cannot import name 'SUPPORTED_PROVIDERS'`.

- [ ] **Step 3: Rewrite `Provider.__init__` and `get_provider`**

In `lib/llm/provider.py`, replace the file-reading constructor:

```python
class Provider:
	def __init__(self, credential: dict, retries: int = 2, backoff: int = 1, *, provider_entry):
		self.credential = credential
		self.retries = retries
		self.backoff = backoff

		# Injected, never read from disk: the live catalog may come from a
		# remote source, and a second file-reading path here would silently
		# diverge from it.
		self.url = provider_entry.url
		self.setting = provider_entry.setting
		self.timeout0 = provider_entry.timeout0
		self.timeout_max = provider_entry.timeout_max
```

Delete the `from pathlib import Path` import if nothing else in the module uses it, and delete the `setting_dir` / `setting_path` lines.

Replace the factory:

```python
PROVIDER_CLASSES = {
	"OpenAI": OpenAIProvider,
	"Anthropic": AnthropicProvider,
	"DeepSeek": DeepseekProvider,
	"Ollama": OllamaProvider,
	"Google": GoogleProvider,
	"OpenRouter": OpenrouterProvider,
}


def get_provider(provider_name: str, credential: dict, retries: int = 2, backoff: int = 1, *, provider_entry) -> Provider:
	provider_class = PROVIDER_CLASSES.get(provider_name)
	if not provider_class:
		raise ValueError(f"Unsupported provider: {provider_name}")

	return provider_class(credential, retries=retries, backoff=backoff, provider_entry=provider_entry)
```

- [ ] **Step 4: Rewrite the adapter's price lookup**

In `lib/llm/adapter.py`:

```python
class ProviderModelAdapter(ABC):
	def __init__(self, provider_name: str, model_name: str, *, price_entry: dict):
		self.provider_name = provider_name
		self.model_name = model_name
		# {} when the catalog has no price for this pair, which is exactly what
		# the old price.json lookup returned via .get(key, {}).
		self._model_entry = price_entry or {}
		self._cost_calculator = CostCalculator(self._model_entry)
```

Delete `_load_model_entry` entirely, and the now-unused `import json` and `from pathlib import Path`.

Replace the factory:

```python
ADAPTER_CLASSES = {
	"OpenAI": OpenAIAdapter,
	"Anthropic": AnthropicAdapter,
	"Google": GoogleAdapter,
	"OpenRouter": OpenRouterAdapter,
	"DeepSeek": DeepSeekAdapter,
	"Ollama": DeepSeekAdapter,
}


def get_provider_model_adapter(provider_name: str, model_name: str, *, price_entry: dict) -> ProviderModelAdapter:
	adapter_class = ADAPTER_CLASSES.get(provider_name)
	if not adapter_class:
		raise ValueError(f"Unsupported provider/model adapter: {provider_name}/{model_name}")
	return adapter_class(provider_name, model_name, price_entry=price_entry)
```

- [ ] **Step 5: Export `SUPPORTED_PROVIDERS`**

Add to `lib/llm/__init__.py`, alongside the existing re-exports:

```python
from .adapter import ADAPTER_CLASSES
from .provider import PROVIDER_CLASSES

# The intersection, not either table alone: a name in one and not the other is
# a model the user could select and could not run.
SUPPORTED_PROVIDERS = frozenset(PROVIDER_CLASSES) & frozenset(ADAPTER_CLASSES)
```

`lib/llm/__init__.py` defines no `__all__` today; do not add one.

- [ ] **Step 6: Thread the entries through the task layer**

In `lib/application/task_factory.py`, add two required keyword parameters and pass them on:

```python
def create_typo_workflow(
	*,
	provider_name: str,
	model_name: str,
	credential: dict,
	provider_entry,
	price_entry: dict,
	language: str,
	...
):
	provider_object = get_provider(
		provider_name, credential, retries=retries, backoff=backoff, provider_entry=provider_entry
	)
	adapter_object = get_provider_model_adapter(provider_name, model_name, price_entry=price_entry)
```

`lib/application/task_runner.py` forwards `**workflow_kwargs` already and needs no change — confirm by reading it.

- [ ] **Step 7: Update the two remaining call sites**

`workspace/evals/provider.py` (4-space indentation in this file). Add near the other imports:

```python
from lib.catalog.document import build_catalog
from lib.catalog.model import make_corrector_config_id
from lib.catalog.sources import BundledCatalogSource
from lib.llm import SUPPORTED_PROVIDERS

_CATALOG = None


def _catalog():
    global _CATALOG
    if _CATALOG is None:
        setting_dir = Path(__file__).resolve().parents[2] / "addon" / "globalPlugins" / "WordBridge" / "setting"
        document, _issues = BundledCatalogSource(setting_dir).load()
        _CATALOG = build_catalog(document, runnable_providers=SUPPORTED_PROVIDERS)
    return _CATALOG
```

(Use the `Path` import the file already has; add `from pathlib import Path` if it does not.)

In `call_api`, before `run_typo_correction`:

```python
    catalog = _catalog()
    provider_entry = catalog.get_provider(config["provider_name"])
    model_entry = catalog.get_model(
        make_corrector_config_id(config["model_name"], config["provider_name"])
    )
    price_entry = model_entry.price_entry() if model_entry is not None else {}
```

and pass `provider_entry=provider_entry, price_entry=price_entry` into the `run_typo_correction(...)` call.

In `tests/test_eval_provider_config.py`, update the direct `get_provider` / `get_provider_model_adapter` calls the same way, building the catalog with `BundledCatalogSource` as `tests/test_provider_naming.py` does.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_provider_naming.py tests/test_eval_provider_config.py -q`
Expected: PASS.

- [ ] **Step 9: Run the whole suite**

Run: `python3 -m pytest -q -m "not integration"`
Expected: no failures. `tests/test_provider_model_adapter_unittest.py` constructs adapters directly — if it fails, update its constructor calls to pass `price_entry={...}` with the same dict it previously expected `_load_model_entry` to return.

- [ ] **Step 10: Commit**

```bash
git add addon/globalPlugins/WordBridge/lib workspace/evals/provider.py tests
git commit -m "feat: inject provider and price entries instead of reading files"
```

---

### Task 5: `SettingsRepository`

**Files:**
- Create: `addon/globalPlugins/WordBridge/settings_repository.py`
- Test: `tests/test_settings_repository.py` (create)

**Interfaces:**
- Consumes: `CorrectorCatalog`, `normalize_selection` from Tasks 1 and 3.
- Produces:
  - `LANGUAGE_VALUES = ["zh_traditional", "zh_simplified"]`
  - `TYPO_CORRECTION_MODE_VALUES = ["standard", "lite"]`
  - `os_default_language() -> str`
  - `SettingsRepository(settings, catalog)` where `settings` is the mapping at `config.conf["WordBridge"]["settings"]` and `catalog` is a zero-argument callable returning the current `CorrectorCatalog`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_repository.py`:

```python
import pytest

from lib.catalog.document import SCHEMA_VERSION, build_catalog
from lib.catalog.model import COSEEING_GROUP
from settings_repository import SettingsRepository, os_default_language


RUNNABLE = frozenset({"OpenAI"})


def catalog():
	return build_catalog(
		{
			"schema_version": SCHEMA_VERSION,
			"providers": {"OpenAI": {
				"label": "OpenAI",
				"url": "https://example.invalid",
				"setting": {},
				"timeout0": 10,
				"timeout_max": 20,
			}},
			"models": [{"provider": "OpenAI", "model": "gpt-x", "label": "GPT X"}],
			"coseeings": [{"model": "default", "label": "Coseeing default"}],
		},
		runnable_providers=RUNNABLE,
	)


def repository(**settings):
	base = {
		"corrector_config_id": "",
		"execution_channel": "",
		"language": "",
		"typo_correction_mode": "",
		"api_key": {},
		"max_char_count": 512,
		"auto_display_report": False,
		"customized_words_enable": True,
		"sound_effects_enable": True,
	}
	base.update(settings)
	return SettingsRepository(base, catalog), base


def test_an_empty_stored_selection_resolves_to_the_catalog_default():
	repo, _ = repository()

	assert repo.corrector_selection() == ("default", COSEEING_GROUP)


def test_a_stored_selection_is_honoured():
	repo, _ = repository(corrector_config_id="gpt-x&OpenAI", execution_channel="local")

	assert repo.corrector_selection() == ("gpt-x&OpenAI", "local")


def test_saving_a_selection_writes_both_keys():
	repo, settings = repository()

	repo.save_corrector_selection("gpt-x&OpenAI", "local")

	assert settings["corrector_config_id"] == "gpt-x&OpenAI"
	assert settings["execution_channel"] == "local"


def test_an_empty_language_resolves_to_the_os_default():
	repo, _ = repository()

	assert repo.language() == os_default_language()


def test_a_stored_language_is_honoured():
	repo, _ = repository(language="zh_simplified")

	assert repo.language() == "zh_simplified"


def test_an_unknown_language_resolves_to_the_os_default():
	repo, _ = repository(language="klingon")

	assert repo.language() == os_default_language()


def test_the_os_language_probe_degrades_when_ctypes_is_unavailable():
	# There is no windll on this host, so the guarded probe must already be
	# taking its failure path rather than raising.
	assert os_default_language() in ("zh_traditional", "zh_simplified")


def test_an_unknown_correction_mode_resolves_to_the_default():
	repo, _ = repository(typo_correction_mode="nonsense")

	assert repo.typo_correction_mode() == "standard"


def test_an_api_key_defaults_to_empty_and_is_created_on_read():
	repo, settings = repository()

	assert repo.api_key("OpenAI") == ""
	repo.save_api_key("OpenAI", "sk-test")
	assert settings["api_key"]["OpenAI"] == "sk-test"


def test_the_boolean_settings_round_trip():
	repo, settings = repository()

	repo.save_auto_display_report(True)
	repo.save_customized_words_enable(False)
	repo.save_sound_effects_enable(False)

	assert (settings["auto_display_report"], settings["customized_words_enable"], settings["sound_effects_enable"]) == (True, False, False)
	assert repo.auto_display_report() is True
	assert repo.customized_words_enable() is False
	assert repo.sound_effects_enable() is False


def test_max_char_count_round_trips():
	repo, settings = repository()

	repo.save_max_char_count(1024)

	assert settings["max_char_count"] == 1024
	assert repo.max_char_count() == 1024
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_settings_repository.py -q`
Expected: `ModuleNotFoundError: No module named 'settings_repository'`.

- [ ] **Step 3: Write `settings_repository.py`**

```python
from functools import lru_cache

from lib.catalog.selection import normalize_selection


LANGUAGE_VALUES = ["zh_traditional", "zh_simplified"]
LANGUAGE_FALLBACK = "zh_traditional"
TYPO_CORRECTION_MODE_VALUES = ["standard", "lite"]
TYPO_CORRECTION_MODE_DEFAULT = "standard"


@lru_cache(maxsize=1)
def os_default_language() -> str:
	"""The UI language NVDA's host is running in, resolved lazily.

	This used to run at dialogs.py import time. Off Windows -- and on any
	runtime where the call fails -- it degrades to Traditional Chinese rather
	than taking the module's import down with it.
	"""
	try:
		import ctypes
		import locale

		code = locale.windows_locale[ctypes.windll.kernel32.GetUserDefaultUILanguage()]
	except Exception:
		return LANGUAGE_FALLBACK
	return LANGUAGE_FALLBACK if code in ("zh_TW", "zh_MO", "zh_HK") else "zh_simplified"


class SettingsRepository:
	"""The only place that touches config.conf["WordBridge"]["settings"].

	It also owns the two resolutions that let the config spec defaults be
	static strings: an empty corrector selection becomes the catalog's
	default, and an empty language becomes the OS UI language.
	"""

	def __init__(self, settings, catalog):
		self._settings = settings
		self._catalog = catalog

	def corrector_selection(self) -> tuple:
		return normalize_selection(
			self._catalog(),
			self._settings.get("corrector_config_id", ""),
			self._settings.get("execution_channel", ""),
		)

	def save_corrector_selection(self, corrector_config_id: str, execution_channel: str) -> None:
		self._settings["corrector_config_id"] = corrector_config_id
		self._settings["execution_channel"] = execution_channel

	def language(self) -> str:
		value = self._settings.get("language", "")
		return value if value in LANGUAGE_VALUES else os_default_language()

	def save_language(self, value: str) -> None:
		self._settings["language"] = value

	def typo_correction_mode(self) -> str:
		value = self._settings.get("typo_correction_mode", "")
		return value if value in TYPO_CORRECTION_MODE_VALUES else TYPO_CORRECTION_MODE_DEFAULT

	def save_typo_correction_mode(self, value: str) -> None:
		self._settings["typo_correction_mode"] = value

	def api_key(self, provider: str) -> str:
		keys = self._settings.setdefault("api_key", {})
		if provider not in keys:
			keys[provider] = ""
		return keys[provider]

	def save_api_key(self, provider: str, value: str) -> None:
		self._settings.setdefault("api_key", {})[provider] = value

	def max_char_count(self) -> int:
		return self._settings["max_char_count"]

	def save_max_char_count(self, value: int) -> None:
		self._settings["max_char_count"] = value

	def auto_display_report(self) -> bool:
		return self._settings["auto_display_report"]

	def save_auto_display_report(self, value: bool) -> None:
		self._settings["auto_display_report"] = value

	def customized_words_enable(self) -> bool:
		return self._settings["customized_words_enable"]

	def save_customized_words_enable(self, value: bool) -> None:
		self._settings["customized_words_enable"] = value

	def sound_effects_enable(self) -> bool:
		return self._settings["sound_effects_enable"]

	def save_sound_effects_enable(self, value: bool) -> None:
		self._settings["sound_effects_enable"] = value
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_settings_repository.py -q`
Expected: PASS.

- [ ] **Step 5: Run the whole suite and commit**

```bash
python3 -m pytest -q -m "not integration"
git add addon/globalPlugins/WordBridge/settings_repository.py tests/test_settings_repository.py
git commit -m "feat: put every WordBridge setting behind one repository"
```

---

### Task 6: Rewire `dialogs.py` and `__init__.py`, and delete `ConfigManager`

This is the task that makes the import-time side effects go away, so `dialogs.py` and `__init__.py` change together: `__init__.py` imports four module-level names from `dialogs.py` that are about to stop existing.

**Files:**
- Modify: `addon/globalPlugins/WordBridge/dialogs.py`
- Modify: `addon/globalPlugins/WordBridge/__init__.py`
- Modify: `addon/globalPlugins/WordBridge/configManager.py`
- Modify: `tests/test_corrector_catalog_unittest.py`
- Test: `tests/test_import_purity.py` (create)

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces:
  - `configManager.py` exporting only `CorrectorTaskConfig` and `load_corrector_task_config`.
  - `GlobalPlugin.settings: SettingsRepository`, `GlobalPlugin.correctorTaskConfig`.
  - `dialogs.LLMSettingsPanel` reading the catalog through `registry.current()`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_import_purity.py`:

```python
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"

PROBE = r"""
import sys
sys.path.insert(0, {tests!r})
sys.path.insert(0, {addon!r})

from lib import vendor
vendor.install(vendor.default_roots({package!r}))
vendor.install_stdlib_gapfill({package!r})

opened = []
import sys as _sys
def audit(event, args):
	if event == "open":
		opened.append(str(args[0]))
	if event == "ctypes.dlopen" or event == "ctypes.dlsym":
		opened.append("CTYPES:" + str(args[0]))
_sys.addaudithook(audit)

import nvda_stubs  # installs the NVDA module stand-ins
opened.clear()

import dialogs  # noqa: F401

setting_reads = [path for path in opened if "setting" + {sep!r} in path]
ctypes_calls = [path for path in opened if path.startswith("CTYPES:")]
print(repr(setting_reads))
print(repr(ctypes_calls))
"""


def test_importing_dialogs_reads_no_setting_file_and_calls_no_windll(tmp_path):
	stub = tmp_path / "nvda_stubs.py"
	stub.write_text(NVDA_STUBS, encoding="utf8")
	script = PROBE.format(
		tests=str(tmp_path),
		addon=str(ADDON_PATH),
		package=str(ADDON_PATH / "package"),
		sep="/",
	)
	result = subprocess.run(
		[sys.executable, "-c", script],
		capture_output=True,
		text=True,
		cwd=str(PROJECT_ROOT),
	)

	assert result.returncode == 0, result.stderr
	setting_reads, ctypes_calls = result.stdout.strip().splitlines()
	assert setting_reads == "[]", f"dialogs read setting files at import: {setting_reads}"
	assert ctypes_calls == "[]", f"dialogs called into ctypes at import: {ctypes_calls}"


NVDA_STUBS = '''
import sys
from types import SimpleNamespace

for name in ("addonHandler",):
	module = SimpleNamespace(initTranslation=lambda: None)
	sys.modules[name] = module

sys.modules["config"] = SimpleNamespace(conf=SimpleNamespace(spec={}))
sys.modules["wx"] = SimpleNamespace(
	Choice=object, TextCtrl=object, CheckBox=object, Button=object,
	StaticText=object, StaticBoxSizer=object, BoxSizer=object, Dialog=object,
	VERTICAL=0, HORIZONTAL=1, ALL=2, OK=3, CANCEL=4,
	TE_PASSWORD=5, TE_PROCESS_ENTER=6, TE_READONLY=7, TE_MULTILINE=8,
	EVT_CHOICE=object(), EVT_BUTTON=object(),
	ToolTip=lambda value: value, Size=lambda w, h: (w, h),
	CallAfter=lambda *a, **k: None, CallLater=lambda *a, **k: None,
)
sys.modules["gui"] = SimpleNamespace(
	settingsDialogs=SimpleNamespace(NVDASettingsDialog=type("D", (), {"categoryClasses": []}), SettingsPanel=object),
	guiHelper=SimpleNamespace(BoxSizerHelper=object, BORDER_FOR_DIALOGS=0),
	nvdaControls=SimpleNamespace(SelectOnFocusSpinCtrl=object),
	mainFrame=SimpleNamespace(),
	contextHelp=SimpleNamespace(ContextHelpMixin=object),
)
sys.modules["gui.settingsDialogs"] = sys.modules["gui"].settingsDialogs
sys.modules["gui.contextHelp"] = sys.modules["gui"].contextHelp
sys.modules["configobj.validate"] = SimpleNamespace(
	VdtValueTooBigError=ValueError, VdtValueTooSmallError=ValueError
)
'''
```

Note: the stub file is written into `tmp_path`, which the probe puts on `sys.path`. If importing `dialogs` needs another NVDA module, add it to `NVDA_STUBS` — the point of the test is the two assertions, not the stub list.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_import_purity.py -q`
Expected: FAIL, with `setting_reads` listing `setting/ai/*.json`, and (on Windows) a ctypes call. On this Linux host the `ctypes` assertion may already pass because `windll` does not exist — the `setting_reads` assertion is the one that must fail now.

- [ ] **Step 3: Strip `configManager.py` down to the task config**

Delete `LABEL_DICT`, `make_corrector_config_id`, `normalize_selection`, `CorrectorConfig`, `SelectableItem` and `ConfigManager`. Keep the translation-binding preamble, `CorrectorTaskConfig` and `load_corrector_task_config`. The file should be about 40 lines.

- [ ] **Step 4: Rewire `dialogs.py`**

Remove from the module level: the `ConfigManager` import, `LABEL_DICT`'s model and provider entries, the `os_language_code` / `LANGUAGE_DEFAULT` block, `AI_CONFIG_FOLDER_PATH`, `TYPO_CORRECTION_MODE_DEFAULT`, `LANGUAGE_VALUES`, `TYPO_CORRECTION_MODE_VALUES`, `configManager = ConfigManager(...)` and `CORRECTOR_CONFIG_ID_DEFAULT, EXECUTION_CHANNEL_DEFAULT = ...`.

Add:

```python
from .lib.catalog import registry
from .lib.catalog.selection import SelectionState
from .settings_repository import (
	LANGUAGE_VALUES,
	TYPO_CORRECTION_MODE_VALUES,
	SettingsRepository,
)

# UI strings only. Model and provider display names live in the catalog now;
# sending them through here would make a future remote payload a channel for
# rewriting the interface's own wording.
LABEL_DICT = {
	"zh_traditional": _("Traditional Chinese"),
	"zh_simplified": _("Simplified Chinese"),
	"standard": _("Standard"),
	"lite": _("Lite"),
	"personal_api_key": _("Personal API Key"),
	"coseeing_account": _("Coseeing Account"),
}
LANGUAGE_LABELS = [LABEL_DICT[value] for value in LANGUAGE_VALUES]
TYPO_CORRECTION_MODE_LABELS = [LABEL_DICT[value] for value in TYPO_CORRECTION_MODE_VALUES]
```

In `makeSettings`, replace the opening block:

```python
	def makeSettings(self, settingsSizer):
		settingsSizerHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

		self.catalog = registry.current()
		self.settings = SettingsRepository(config.conf["WordBridge"]["settings"], registry.current)
		self.selection = SelectionState.restore(self.catalog, *self.settings.corrector_selection())

		providerLabelText = _("Service Provider:")
		self.providerList = settingsSizerHelper.addLabeledControl(
			providerLabelText,
			wx.Choice,
			choices=list(self.catalog.provider_groups),
		)
		self.providerList.SetToolTip(wx.ToolTip(_("Choose the service provider for the WordBridge")))
		self.providerList.Bind(wx.EVT_CHOICE, self.onChangeProviderChoice)
		self.providerList.SetSelection(self.selection.provider_group_index)

		modelLabelText = _("Large Language Model:")
		self.modelList = settingsSizerHelper.addLabeledControl(
			modelLabelText,
			wx.Choice,
			choices=list(self.catalog.labels_for(self.selection.provider_group)),
		)
		self.modelList.SetToolTip(wx.ToolTip(_("Choose the large language model for the Word Bridge")))
		self.modelList.SetSelection(self.selection.model_index)
```

The account group loop iterates `self.catalog.provider_groups` instead of `zip(configManager.provider_groups, configManager.endpoint_labels)`; use the group name for the box label, except for `COSEEING_GROUP`. Replace `config.conf[...]["api_key"][endpoint]` reads with `self.settings.api_key(endpoint)`.

Replace the remaining helpers:

```python
	def _refreshModelChoice(self):
		self.modelList.SetItems(list(self.catalog.labels_for(self.selection.provider_group)))
		self.modelList.SetSelection(0)

	def _refreshAccountInfo(self):
		for group in self.catalog.provider_groups:
			if group == self.selection.provider_group:
				self.settingsSizer.Show(self.accountGroupSizerMap[group], recursive=True)
			else:
				self.settingsSizer.Hide(self.accountGroupSizerMap[group], recursive=True)

	def onChangeProviderChoice(self, evt):
		self.selection.choose_provider_group(self.providerList.GetSelection())

		self.Freeze()
		self._refreshAccountInfo()
		self._refreshModelChoice()
		self.onPanelActivated()
		self._sendLayoutUpdatedEvent()
		self.Thaw()
```

And `onSave`:

```python
	def onSave(self):
		self.selection.provider_group_index = self.providerList.GetSelection()
		self.selection.model_index = self.modelList.GetSelection()
		selected_item = self.selection.current_item()
		self.settings.save_corrector_selection(
			selected_item.corrector_config_id, selected_item.execution_channel
		)
		self.settings.save_language(LANGUAGE_VALUES[self.languageList.GetSelection()])
		self.settings.save_typo_correction_mode(
			TYPO_CORRECTION_MODE_VALUES[self.typoCorrectionModeList.GetSelection()]
		)
		self.settings.save_max_char_count(self.maxCharCountSpinCtrl.GetValue())
		self.settings.save_auto_display_report(self.autoDisplayReportEnable.GetValue())
		self.settings.save_customized_words_enable(self.customizedWordEnable.GetValue())
		self.settings.save_sound_effects_enable(self.soundEffectsEnable.GetValue())

		for group, control in self.accountTextCtrlMap.items():
			self.settings.save_api_key(group, control.GetValue())

		wx.CallAfter(lambda: start_coseeing_auth(selected_item.execution_channel, silent=False))
```

Language and mode selection in `makeSettings` read `self.settings.language()` and `self.settings.typo_correction_mode()` and index into `LANGUAGE_VALUES` / `TYPO_CORRECTION_MODE_VALUES` — both always return a valid member, so the old "not in the list, write the default back" branches are deleted.

- [ ] **Step 5: Rewire `__init__.py`**

Change the imports:

```python
from .dialogs import LLMSettingsPanel, FeedbackDialog
from .configManager import load_corrector_task_config
from .lib.catalog import registry
from .lib.catalog.document import build_catalog
from .lib.catalog.fallback import load_catalog
from .lib.catalog.selection import normalize_selection
from .lib.catalog.sources import BundledCatalogSource
from .lib.llm import SUPPORTED_PROVIDERS
from .settings_repository import SettingsRepository
```

Make the config spec static — no catalog, no `ctypes`:

```python
config.conf.spec["WordBridge"] = {
	"settings": {
		# Empty means "not chosen yet". SettingsRepository resolves it against
		# the catalog at read time, which is what keeps this spec -- evaluated
		# at import -- independent of the catalog.
		"corrector_config_id": "string(default='')",
		"execution_channel": "string(default='')",
		"language": "string(default='')",
		"typo_correction_mode": "string(default='')",
		"api_key": {},
		"max_char_count": "integer(default=512,min=256,max=4096)",
		"auto_display_report": "boolean(default=False)",
		"customized_words_enable": "boolean(default=True)",
		"sound_effects_enable": "boolean(default=True)",
	}
}
```

Delete the module-level `correctorTaskConfig = load_corrector_task_config(...)` line and build both the catalog and the task config in `GlobalPlugin.__init__`, before the panel is registered:

```python
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.catalog = load_catalog(
			BundledCatalogSource(os.path.join(PATH, "setting")),
			runnable_providers=SUPPORTED_PROVIDERS,
		)
		registry.initialize(self.catalog)
		for issue in self.catalog.issues:
			log.warning(
				"WordBridge: catalog issue code=%s location=%s: %s",
				issue.code, issue.location, issue.detail,
			)
		self.correctorTaskConfig = self._load_corrector_task_config()
		self.settings = SettingsRepository(config.conf["WordBridge"]["settings"], registry.current)
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(LLMSettingsPanel)
		self._shutdown = threading.Event()
		_, channel = self.settings.corrector_selection()
		wx.CallAfter(self._start_coseeing_auth, channel)
		self.latest_action = CorrectionAction()
		self.correct_typo_thread = None
		self._feedback_thread = None
		self._progress_cue = None
		self._degraded_catalog_announced = False

	def _load_corrector_task_config(self):
		try:
			return load_corrector_task_config(CORRECTOR_TASK_CONFIG_PATH)
		except (OSError, ValueError, KeyError) as error:
			# A damaged task config used to take the add-on's import down.
			log.warning(
				"WordBridge: could not load the corrector task config type=%s: %s",
				type(error).__name__, error,
			)
			return CorrectorTaskConfig(
				template_name={"standard": "Standard_v1.json", "lite": "Lite_v1.json"},
				optional_guidance_enable={"keep_non_chinese_char": True, "no_explanation": True},
			)
```

Import `CorrectorTaskConfig` from `.configManager` for that fallback. Those values are the current contents of `setting/task/corrector.json`, copied verbatim — the fallback exists so a damaged file degrades to today's shipped behaviour instead of taking the add-on's import down.

In `correctTypo`, replace `normalize_selection(configManager, ...)` with the catalog form and look up the entries for the local branch:

```python
		catalog = registry.current()
		stored_id = config.conf["WordBridge"]["settings"]["corrector_config_id"]
		stored_channel = config.conf["WordBridge"]["settings"]["execution_channel"]
		corrector_config_id, execution_channel = normalize_selection(catalog, stored_id, stored_channel)
		language = self.settings.language()
		corrector_mode = self.settings.typo_correction_mode()
		template_name = self.correctorTaskConfig.template_name[corrector_mode]
		optional_guidance_enable = self.correctorTaskConfig.optional_guidance_enable
		...
		if execution_channel == "local":
			model_entry = catalog.get_model(corrector_config_id)
			provider_entry = catalog.get_provider(model_entry.provider)
			credential = {"api_key": self.settings.api_key(model_entry.provider)}
			result = run_typo_correction(
				request=request,
				batch_mode=batch_mode,
				provider_name=model_entry.provider,
				model_name=model_entry.model,
				credential=credential,
				provider_entry=provider_entry,
				price_entry=model_entry.price_entry(),
				...
			)
```

Keep every existing `try` / `except` and notification around that call exactly as it is.

- [ ] **Step 6: Rewrite `tests/test_corrector_catalog_unittest.py`**

Point every assertion at the catalog instead of `ConfigManager`, keeping the same expectations:

```python
import unittest
from pathlib import Path

from lib.catalog.document import build_catalog
from lib.catalog.model import COSEEING_GROUP
from lib.catalog.sources import BundledCatalogSource
from lib.llm import SUPPORTED_PROVIDERS


SETTING_DIR = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge" / "setting"


def shipped_catalog():
	document, _issues = BundledCatalogSource(SETTING_DIR).load()
	return build_catalog(document, runnable_providers=SUPPORTED_PROVIDERS)


class CorrectorCatalogTests(unittest.TestCase):
	def test_google_model_labels_match_approved_text_model_catalog(self):
		self.assertEqual(
			shipped_catalog().labels_for("Google"),
			(
				"gemini-3.8-flash",
				"gemini-3.7-flash",
				"gemini-3.5-flash-lite",
				"gemini-3.1-pro",
				"gemini-3.1-flash-lite",
			),
		)

	def test_openai_and_anthropic_model_labels_match_replacement_catalog(self):
		catalog = shipped_catalog()
		self.assertEqual(catalog.labels_for("Anthropic"), ("claude-opus-5", "claude-sonnet-5"))
		self.assertEqual(
			catalog.labels_for("OpenAI"),
			("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"),
		)

	def test_provider_groups_include_coseeing_last(self):
		groups = shipped_catalog().provider_groups
		self.assertEqual(groups[-1], COSEEING_GROUP)
		self.assertEqual(sorted(groups[:-1]), list(groups[:-1]))
```

Preserve any other test in that file by translating it the same way; delete only assertions that were about `ConfigManager`'s mutable `provider` attribute, which no longer exists. `test_default_selection_uses_first_coseeing_endpoint` currently expects `deepseek-v4-flash&DeepSeek` — leave that expectation until Task 7 adds the sentinel, then update it there.

- [ ] **Step 7: Run the tests**

Run: `python3 -m pytest tests/test_import_purity.py tests/test_corrector_catalog_unittest.py -q`
Expected: PASS.

Run: `python3 -m pytest -q -m "not integration"`
Expected: no failures. `tests/test_coseeing_auth_nvda.py` and `tests/test_coseeing_lifecycle.py` construct the plugin — if they fail because `GlobalPlugin.__init__` now builds a catalog, extend `_load_nvda_plugin`'s stubs rather than weakening the production code.

- [ ] **Step 8: Commit**

```bash
git add addon/globalPlugins/WordBridge tests
git commit -m "refactor: initialise the catalog explicitly instead of at import"
```

The commit message must state that model and provider display names leave the `.pot`, and why.

---

### Task 7: The sentinel entry, and deleting `Coseeing.json`

**Files:**
- Create: `addon/globalPlugins/WordBridge/setting/ai/Coseeing-00000-default.json`
- Delete: `addon/globalPlugins/WordBridge/setting/provider/Coseeing.json`
- Modify: `addon/globalPlugins/WordBridge/__init__.py` (degraded announcement)
- Modify: `tests/test_ai_config_schema.py`, `tests/test_catalog_bundled.py`, `tests/test_corrector_catalog_unittest.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `"default"` as the shipped catalog's `default_selection()`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_catalog_bundled.py`, replace `test_the_shipped_data_produces_only_the_known_lint_issues` and add three:

```python
def test_the_shipped_data_produces_only_the_known_lint_issue():
	catalog = shipped_catalog()

	assert [(issue.code, issue.location) for issue in catalog.issues] == [
		("unreferenced_provider", "providers.OpenRouter"),
	]


def test_the_sentinel_is_offered_on_the_coseeing_channel_only():
	catalog = shipped_catalog()

	assert catalog.get_coseeing("default") is not None
	assert catalog.get_model("default") is None


def test_the_sentinel_is_the_shipped_default_selection():
	assert shipped_catalog().default_selection() == ("default", COSEEING_GROUP)


def test_the_sentinel_matches_the_fallback_entry():
	from lib.catalog.fallback import FALLBACK_DOCUMENT, SENTINEL_ID, SENTINEL_LABEL

	entry = shipped_catalog().get_coseeing(SENTINEL_ID)
	assert (entry.model, entry.label, entry.provider) == (
		FALLBACK_DOCUMENT["coseeings"][0]["model"],
		SENTINEL_LABEL,
		None,
	)
```

Delete `legacy_manager()` and the four tests that use it — `ConfigManager` no longer exists after Task 6, and the sentinel makes the comparison meaningless anyway. Their job is done: they proved the flattening was faithful at the moment it mattered.

In `tests/test_ai_config_schema.py`, update the schema test:

```python
def test_ai_configs_use_endpoint_only_schema():
	allowed_keys = {"model", "provider", "coseeing", "active"}
	ai_paths = sorted(AI_CONFIG_DIR.glob("*.json"))

	assert len(ai_paths) == 14
	coseeing_only = 0
	for path in ai_paths:
		with path.open("r", encoding="utf-8") as f:
			config = json.load(f)

		assert set(config.keys()) <= allowed_keys, path.name
		assert "template_name" not in config, path.name
		assert "optional_guidance_enable" not in config, path.name
		if "active" in config:
			assert isinstance(config["active"], bool), path.name
		assert isinstance(config["model"], str) and config["model"], path.name
		assert isinstance(config["coseeing"], bool), path.name
		if "provider" in config:
			assert isinstance(config["provider"], str) and config["provider"], path.name
		else:
			# No provider means no local offer: the Coseeing server serves it
			# on its own. Exactly one shipped entry is like this.
			coseeing_only += 1
			assert config["coseeing"] is True, path.name
			assert config["model"] == "default", path.name

	assert coseeing_only == 1
```

`test_ai_catalog_uses_unique_model_provider_pairs` must tolerate a missing `provider`: use `config.get("provider")` in the pair.

In `tests/test_corrector_catalog_unittest.py`, update the default-selection expectation to `("default", COSEEING_GROUP)`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_catalog_bundled.py tests/test_ai_config_schema.py -q`
Expected: FAIL — 13 files not 14, no sentinel, two lint issues not one.

- [ ] **Step 3: Add the sentinel and remove the orphan provider**

Create `addon/globalPlugins/WordBridge/setting/ai/Coseeing-00000-default.json` (tabs, matching the other files' 4-space style — check one first and match it exactly):

```json
{
    "active": true,
    "model": "default",
    "coseeing": true
}
```

The filename is load-bearing for ordering: `BundledCatalogSource` walks `sorted(glob)`, and `Coseeing-00000-` sorts before `DeepSeek-`, which puts the sentinel first in `coseeings` and therefore makes it `default_selection()`.

Delete `setting/provider/Coseeing.json`:

```bash
git rm addon/globalPlugins/WordBridge/setting/provider/Coseeing.json
```

- [ ] **Step 4: Announce a degraded catalog once per session**

In `__init__.py`'s `correctTypo`, immediately before the channel branch:

```python
		if self.catalog.degraded and not self._degraded_catalog_announced:
			self._degraded_catalog_announced = True
			self._notify(_("The model list could not be loaded. Coseeing will choose a model for you."))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_catalog_bundled.py tests/test_ai_config_schema.py tests/test_corrector_catalog_unittest.py -q`
Expected: PASS.

- [ ] **Step 6: Run the whole suite and commit**

```bash
python3 -m pytest -q -m "not integration"
git add addon/globalPlugins/WordBridge tests
git commit -m "feat: ship the Coseeing default sentinel and drop the orphan provider"
```

---

### Task 8: The seam test, and the final sweep

**Files:**
- Test: `tests/test_catalog_source_seam.py` (create)

**Interfaces:**
- Consumes: everything above. Produces nothing new.

- [ ] **Step 1: Write the failing test**

Create `tests/test_catalog_source_seam.py`:

```python
from pathlib import Path

from lib.catalog.fallback import load_catalog
from lib.catalog.model import COSEEING_GROUP
from lib.catalog.selection import SelectionState
from lib.catalog.sources import BundledCatalogSource
from lib.llm import SUPPORTED_PROVIDERS


SETTING_DIR = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge" / "setting"


class FakeRemoteCatalogSource:
	"""What a RemoteCatalogSource will be: a document from somewhere else.

	It holds no HTTP, no cache and no retry, because none of that changes what
	the rest of the add-on sees. That is the claim this test exists to prove.
	"""

	def __init__(self, document):
		self.document = document

	def load(self):
		return self.document, ()


def test_a_document_from_a_remote_source_behaves_exactly_like_the_bundled_one():
	document, issues = BundledCatalogSource(SETTING_DIR).load()
	assert issues == ()

	bundled = load_catalog(BundledCatalogSource(SETTING_DIR), runnable_providers=SUPPORTED_PROVIDERS)
	remote = load_catalog(FakeRemoteCatalogSource(document), runnable_providers=SUPPORTED_PROVIDERS)

	assert remote.provider_groups == bundled.provider_groups
	assert remote.selectable_items == bundled.selectable_items
	assert remote.default_selection() == bundled.default_selection()
	assert [entry.price_entry() for entry in remote.models] == [
		entry.price_entry() for entry in bundled.models
	]


def test_a_remote_document_can_add_a_model_with_no_code_change():
	document, _ = BundledCatalogSource(SETTING_DIR).load()
	document["models"] = document["models"] + [{
		"provider": "OpenAI",
		"model": "gpt-9-future",
		"label": "GPT 9 Future",
		"pricing": {"input_tokens": 1, "output_tokens": 2, "base_unit": 1000000},
		"usage_key": "usage",
	}]
	catalog = load_catalog(FakeRemoteCatalogSource(document), runnable_providers=SUPPORTED_PROVIDERS)

	assert "GPT 9 Future" in catalog.labels_for("OpenAI")
	entry = catalog.get_model("gpt-9-future&OpenAI")
	assert entry.price_entry()["pricing"]["input_tokens"] == 1


def test_a_remote_document_naming_an_unimplemented_provider_offers_only_coseeing():
	document, _ = BundledCatalogSource(SETTING_DIR).load()
	document["providers"] = dict(document["providers"], Mistral={
		"label": "Mistral",
		"url": "https://example.invalid",
		"setting": {},
		"timeout0": 10,
		"timeout_max": 20,
	})
	document["models"] = document["models"] + [
		{"provider": "Mistral", "model": "m-large", "label": "M Large"}
	]
	document["coseeings"] = document["coseeings"] + [
		{"model": "m-large", "provider": "Mistral", "label": "M Large"}
	]
	catalog = load_catalog(FakeRemoteCatalogSource(document), runnable_providers=SUPPORTED_PROVIDERS)

	assert "Mistral" not in catalog.provider_groups
	assert "M Large" in catalog.labels_for(COSEEING_GROUP)
	assert "unsupported_provider" in {issue.code for issue in catalog.issues}


def test_the_panel_facing_selection_is_identical_across_sources():
	document, _ = BundledCatalogSource(SETTING_DIR).load()
	bundled = load_catalog(BundledCatalogSource(SETTING_DIR), runnable_providers=SUPPORTED_PROVIDERS)
	remote = load_catalog(FakeRemoteCatalogSource(document), runnable_providers=SUPPORTED_PROVIDERS)

	from_bundled = SelectionState.restore(bundled, "", "")
	from_remote = SelectionState.restore(remote, "", "")

	assert from_bundled.provider_group == from_remote.provider_group
	assert from_bundled.current_item() == from_remote.current_item()
```

- [ ] **Step 2: Run it**

Run: `python3 -m pytest tests/test_catalog_source_seam.py -q`
Expected: PASS immediately. This one test is written last on purpose — it asserts a property of the design rather than driving new code, so it passing first time is the point, not a failure of TDD. If any assertion fails, the seam is not what the spec claims and the implementation is wrong.

- [ ] **Step 3: Verify every acceptance condition from the spec**

Run each and record the output:

```bash
python3 -m pytest -q -m "not integration"
python3 -m pytest tests/test_import_purity.py -q
python3 -m pytest tests/test_catalog_document.py::test_the_catalog_package_imports_only_the_standard_library -q
```

Then check by hand, in a scratch directory:

```bash
# Acceptance 2: an empty ai directory still yields the sentinel
python3 - <<'PY'
import sys, tempfile, pathlib, json
sys.path.insert(0, "addon/globalPlugins/WordBridge")
from lib.catalog.fallback import load_catalog
from lib.catalog.sources import BundledCatalogSource
from lib.llm import SUPPORTED_PROVIDERS
root = pathlib.Path(tempfile.mkdtemp())
(root / "ai").mkdir(); (root / "provider").mkdir()
(root / "price.json").write_text("{}")
catalog = load_catalog(BundledCatalogSource(root), runnable_providers=SUPPORTED_PROVIDERS)
print(catalog.degraded, [item.corrector_config_id for item in catalog.selectable_items])
PY
```

Expected output: `True ['default']`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_catalog_source_seam.py
git commit -m "test: prove the catalog source seam without implementing HTTP"
```

- [ ] **Step 5: Report what could not be verified here**

Write the completion report to `docs/superpowers/finish/2026-09-22-catalog-decoupling.md` listing, at minimum:

- `scons` is not on PATH, so the `.pot` was never regenerated. The claim that model and provider names left the `.pot` is reasoned, not measured.
- Nothing in this batch was exercised on Windows or under NVDA. The settings panel's wx wiring is covered only by stubs; the panel must be opened by hand, a provider switched, a model chosen, saved, and the choice confirmed to survive a restart.
- The degraded-catalog announcement and the sentinel's end-to-end behaviour need a real Coseeing round trip: select the `"default"` option, run a correction, and confirm the server accepts the sentinel id.

---

## Self-Review

**Spec coverage.** Every section of the spec maps to a task: data model and identity → Task 1; document schema and `BundledCatalogSource` → Task 2; validation tables → Task 1 (rules) and Task 2 (shipped data); degradation ladder and sentinel → Tasks 3 and 7; `ConfigManager` decomposition → Tasks 3, 5 and 6; import-time side effects → Task 6, asserted by `tests/test_import_purity.py`; provider/adapter injection → Task 4; the seven testing layers → Tasks 1–8 in order; acceptance conditions → Task 8, Step 3.

**One deviation, recorded deliberately.** The spec says a source produces the document; this plan has `load()` return `(document, issues)` so that a file which is not valid JSON can be reported rather than silently vanishing, and so a future remote source has somewhere to report a 500. Task 2's note explains it; `tests/test_catalog_bundled.py::test_a_corrupt_ai_file_is_reported_and_skipped` pins it.

**One ordering constraint that is easy to get wrong.** Task 2's characterization tests use `ConfigManager` as their oracle and must be green before Task 6 deletes it. Task 7 then removes those four tests, because the sentinel makes the comparison meaningless — their purpose was to prove the flattening was faithful at the moment the old implementation was still there to compare against.

**Type consistency.** `make_corrector_config_id(model, provider=None)`, `ModelEntry.price_entry() -> dict`, `CorrectorCatalog.labels_for(group) -> tuple`, `SelectionState.restore(catalog, id, channel)`, `load_catalog(source, *, runnable_providers)`, `get_provider(..., *, provider_entry)`, `get_provider_model_adapter(..., *, price_entry)` are spelled identically everywhere they appear.
