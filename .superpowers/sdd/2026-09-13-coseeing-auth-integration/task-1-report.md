# Task 1 implementation report

## Files changed

- Added `requirements-coseeing-auth.txt` with the approved Authlib, requests,
  and PyJWT version constraints.
- Added `addon/globalPlugins/WordBridge/lib/coseeing_auth.py` with
  `build_auth_config() -> AuthConfig` and the approved SSO configuration.
- Added `tests/test_coseeing_auth_bundle.py` with the configuration contract
  test and a Windows-only isolated bundle import test.
- Added `addon/globalPlugins/WordBridge/package/coseeing-auth-dependencies.md`
  documenting selected wheels, versions, transitive dependencies, licenses,
  and the NVDA runtime target.
- Added the attached `coseeing_auth` package and the missing Authlib, requests,
  PyJWT, cryptography, cffi, pycparser, and requests transitive dependency
  files to `addon/globalPlugins/WordBridge/package/`, including `.dist-info`
  metadata and license files.
- Made the attached `coseeing_auth` public exports lazy so constructing
  `AuthConfig` does not eagerly load native cryptography on non-Windows hosts.

## Commit

- `b8ed80e build: prepare Coseeing auth dependencies and configuration`

## Tests and focused checks

### `python3 -m pytest tests/test_coseeing_auth_bundle.py -q`

```text
.s                                                                       [100%]
1 passed, 1 skipped in 0.02s
```

The skipped test is the Windows NVDA bundle import check, skipped because this
workspace is Linux. It uses a fresh `python -S` process on Windows and checks
that `coseeing_auth`, Authlib, PyJWT, and requests resolve from the addon
package.

### `python3 -S` addon package configuration import

```text
bundle config import OK from addon package
```

The command inserted only `addon/globalPlugins/WordBridge/package` as the
third-party path and verified that `AuthConfig` came from
`coseeing_auth.models`.

### Bundle metadata check

```text
PyJWT 2.10.1
Authlib 1.6.2
certifi 2026.7.22
cffi 2.1.1
charset-normalizer 3.5.1
cryptography 45.0.7
idna 3.19
pycparser 3.0
requests 2.32.5
urllib3 2.7.0
```

### `python3 -m compileall -q addon/globalPlugins/WordBridge/lib/coseeing_auth.py tests/test_coseeing_auth_bundle.py`

```text
<no output; exit status 0>
```

The package contains Windows `.pyd` files for cryptography, cffi, and
charset-normalizer and no Linux `.so` files.

## Concerns

- A Windows NVDA runtime was unavailable, so the native import check remains a
  release acceptance item. The selected target is CPython 3.11 32-bit Windows,
  matching the available NVDA runtime evidence for the declared 2024.1 through
  2026.1.1 range.
- The bundle includes the full Authlib and cryptography distributions supplied
  or selected for the auth client, so the package addition is large.
