# Task 5 report

Implemented shared SSO authorization for Coseeing proofreader and feedback requests.

## Changes

- Added `build_coseeing_headers(access_token)` to produce a Bearer header for a nonempty token and no `Authorization` header for guests.
- Proofreader waits on `get_coseeing_access_token().result()` in its existing worker thread, aborts on authentication failure, and sends authentication notifications through `wx.CallAfter`.
- Feedback captures the interaction ID and text after the dialog closes, then starts the daemon `wordbridge-feedback` worker. The worker waits for the shared auth Future, uses the snapshot, sends `timeout=120`, handles HTTP status before JSON decoding, and routes notifications through wx.
- Removed the legacy Coseeing username/password login calls and implementation. Existing request payloads and proofreader result/cost handling remain intact.
- Requests and UI updates are suppressed after plugin termination.

## Validation

```text
python3 -m pytest tests/test_coseeing_requests.py tests/test_coseeing_auth.py tests/test_coseeing_auth_nvda.py -q
61 passed in 0.34s

python3 -m compileall -q addon/globalPlugins/WordBridge/__init__.py addon/globalPlugins/WordBridge/lib/coseeing.py tests/test_coseeing_requests.py
git diff --check
```

The environment does not provide a `python` executable, so the equivalent `python3` command was used.
