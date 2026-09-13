# Task 4 report

Implemented Task 4 for Coseeing authentication startup and settings save.

## Changes

- `GlobalPlugin.__init__` normalizes the configured selection and schedules one guarded Coseeing authentication callback with `wx.CallAfter`.
- `GlobalPlugin.terminate` marks queued startup work inactive, calls `shutdown_coseeing_auth()` without waiting for its cleanup future, removes the settings category, and calls the parent cleanup.
- `LLMSettingsPanel` keeps the Coseeing authentication sizer and explanatory text while omitting Coseeing username/password controls.
- `LLMSettingsPanel.onSave` saves the selected provider and model settings, preserves `api_key["Coseeing"]` as the refresh token, saves other provider API keys, and schedules authentication with the selected execution channel.
- Removed `save_coseeing_credentials`; the legacy `coseeing_username` and `coseeing_password` config spec fields remain for compatibility.
- Replaced the obsolete catalog helper test and added isolated NVDA runtime tests for startup, termination, save behavior, refresh-token preservation, local-channel behavior, and Coseeing control construction.

## Verification evidence

Executed from `/workspace/WordBridge`:

```text
python -m pytest tests/test_coseeing_auth_nvda.py -q
/bin/bash: line 1: python: command not found
```

The environment provides `python3`, so the equivalent focused command was run:

```text
python3 -m pytest tests/test_coseeing_auth_nvda.py -q
.................                                                        [100%]
17 passed in 0.23s
```

The requested focused suite was run with the available interpreter:

```text
python3 -m pytest tests/test_coseeing_auth_nvda.py tests/test_corrector_catalog_unittest.py tests/test_corrector_task_config.py -q
...........................                                              [100%]
27 passed in 0.25s
```

Additional checks:

```text
python3 -m py_compile addon/globalPlugins/WordBridge/__init__.py addon/globalPlugins/WordBridge/dialogs.py addon/globalPlugins/WordBridge/configManager.py tests/test_coseeing_auth_nvda.py tests/test_corrector_catalog_unittest.py
exit code 0

git diff --check
exit code 0
```

`ruff check` was attempted for the changed Python files, but `ruff` is not installed in the environment.

## Fix round 1 evidence

The startup normalization test now begins with the invalid pairing
`gemini-3.1-pro-preview&Google` plus `Coseeing`, executes the queued callback
before termination, and asserts that no authentication starts. It then checks
the valid Coseeing startup path and the terminate guard.

Exact focused test output:

```text
python3 -m pytest tests/test_coseeing_auth_nvda.py tests/test_corrector_catalog_unittest.py tests/test_corrector_task_config.py -q
...........................                                              [100%]
27 passed in 0.26s
```

## Commit

Commit message: `feat: trigger Coseeing authentication on startup and settings save`
