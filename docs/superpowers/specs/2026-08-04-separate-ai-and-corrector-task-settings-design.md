# Separate AI and Corrector Task Settings Design

## Goal

Separate provider/model catalog settings from typo-correction prompt settings so a future task, such as translation, can add its own settings without duplicating AI endpoint definitions.

## Setting Layout

```text
addon/globalPlugins/WordBridge/setting/
├── ai/
│   └── <Provider>-<number>-<model>.json
├── task/
│   └── corrector.json
├── provider/
└── templates/
```

Each file in `setting/ai` represents one selectable provider/model endpoint and contains only endpoint concerns:

```json
{
  "active": true,
  "model": "gemini-2.5-pro",
  "provider": "Google",
  "coseeing": false
}
```

`setting/task/corrector.json` is the sole source of typo-correction prompt settings:

```json
{
  "template_name": {
    "standard": "Standard_v1.json",
    "lite": "Lite_v1.json"
  },
  "optional_guidance_enable": {
    "keep_non_chinese_char": true,
    "no_explanation": true
  }
}
```

## Runtime Design

`ConfigManager` continues to load and index AI endpoint files, but its constructor receives the `setting/ai` directory. `CorrectorConfig` retains `active`, `model`, `provider`, and `coseeing`; it no longer exposes prompt-related fields.

`configManager.py` adds a focused `CorrectorTaskConfig` dataclass plus a `load_corrector_task_config(path)` function. The loader parses the one JSON file and requires both `template_name` and `optional_guidance_enable`.

`dialogs.py` constructs `ConfigManager` using `setting/ai`. The plugin entry point loads the corrector task configuration once from `setting/task/corrector.json`. During `correctTypo`, provider/model values come from the selected `CorrectorConfig`, while the template selected for the active correction mode and optional guidance values come from `CorrectorTaskConfig`.

## Data Flow

```text
selected AI endpoint ──> provider + model ──> create_typo_workflow
corrector task config ─> template by mode + guidance ─┘
```

This preserves the existing `create_typo_workflow` interface and prompt behavior. Only the origin of `template_name` and `optional_guidance_enable` changes.

## Migration and Compatibility

The existing `setting/corrector` directory is renamed to `setting/ai`; its JSON files are migrated in place by removing `template_name` and `optional_guidance_enable`. No compatibility loader for `setting/corrector` is retained because this repository owns the bundled setting files and all runtime/test references change together.

The already agreed task settings remain `keep_non_chinese_char: true` and `no_explanation: true`.

## Validation and Testing

Tests will verify:

- Every AI endpoint JSON has only the endpoint schema and no task prompt keys.
- `task/corrector.json` has the required prompt schema and both guidance flags are true.
- `ConfigManager` still offers the same provider/model catalog and selection behavior when loading `setting/ai`.
- The dedicated task loader returns the standard/lite template mapping and guidance mapping consumed by `correctTypo`.

Malformed task JSON or missing required task keys should fail during loading with the natural `json`/key access error, matching the catalog loader's current fail-fast behavior.

## Non-Goals

- No generic multi-task registry or generic task configuration abstraction is introduced.
- No translation workflow or translation settings are added.
- No prompt template content or provider adapter behavior changes.
