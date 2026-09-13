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

## Review fix report (2026-09-13)

### Findings addressed

- Added runtime-specific dependency bundles for CPython 3.11 win32 and
  CPython 3.13 win_amd64, and updated the integration layer to select the
  bundle from the running Python version and pointer width.
- Added the complete cffi backend for both runtimes:
  `_cffi_backend.cp311-win32.pyd` and `_cffi_backend.cp313-win_amd64.pyd`.
  Matching native cryptography and charset-normalizer files are also present
  in each runtime bundle.
- Hardened the Windows import check with `-I -S`, an explicit supported
  runtime matrix, runtime-specific dependency selection, and source checks for
  coseeing_auth plus all direct and transitive dependency modules.
- Restored `addon/globalPlugins/WordBridge/package/coseeing_auth/__init__.py`
  byte-for-byte from the supplied auth package source. Runtime dependency
  selection is implemented in the integration layer instead.

### Fix commit

- `c39758c fix: make Coseeing auth bundle runtime-specific`

### Covering tests and checks

#### `python3 -m pytest tests/test_coseeing_auth_bundle.py -q`

```text
..s                                                                      [100%]
2 passed, 1 skipped in 0.25s
```

The skipped test is the Windows-only isolated import test; no Windows NVDA
runtime is available in this workspace.

#### `python3 -m compileall -q addon/globalPlugins/WordBridge/lib/coseeing_auth.py tests/test_coseeing_auth_bundle.py`

```text
<no output; exit status 0>
```

#### Native bundle inventory

```text
py311-win32/_cffi_backend.cp311-win32.pyd
py313-win_amd64/_cffi_backend.cp313-win_amd64.pyd
```

Both runtime directories also contain their matching cryptography and
charset-normalizer native files, complete `.dist-info` metadata, and license
files. No Linux `.so` files are included.

### Remaining concerns

- The two native import paths still require execution on the corresponding
  Windows NVDA runtimes for final acceptance; this Linux workspace cannot load
  Windows `.pyd` files.
- The runtime-specific bundles duplicate pure Python dependencies, increasing
  the addon package size, to keep each supported NVDA runtime independent of
  host-installed packages.

## Review fix report, round 2 (2026-09-13)

### Findings addressed

- The Windows bundle subprocess now runs with `-I -S` and `env={}`, derives
  the runtime directory from Python major/minor version and pointer width, and
  rejects runtimes outside `py311-win32` and `py313-win_amd64`.
- The subprocess imports and origin-checks `coseeing_auth`, Authlib, requests,
  PyJWT, cryptography, cffi, `_cffi_backend`, charset-normalizer, certifi,
  idna, urllib3, and pycparser. Each dependency must resolve from the selected
  runtime bundle; `coseeing_auth` must resolve from the addon package.
- The non-Windows configuration check now explicitly supplies the development
  test dependency directory in an isolated `-I -S` subprocess with an empty
  environment. This makes the test setup visible and prevents accidental
  masking by inherited `PYTHONPATH` or site initialization.
- The test also explicitly provisions that same test-only dependency path for
  the contract assertion. Deployment selection remains Windows-only and
  runtime-specific in `build_auth_config()`.
- `coseeing_auth/__init__.py` remains byte-for-byte identical to the supplied
  package source; no lazy export change was reintroduced.

### Fix commit

- `c39758c fix: make Coseeing auth bundle runtime-specific` (runtime bundle,
  dependency selection, and first-round validation fixes)
- The round-2 test/report commit is recorded after this report is staged.

### Covering tests and checks

#### `python3 -m pytest tests/test_coseeing_auth_bundle.py -q`

```text
...s                                                                     [100%]
3 passed, 1 skipped in 0.41s
```

The skipped test is the Windows-only import validation. No CPython 3.11 win32
or CPython 3.13 win_amd64 NVDA runtime is available on this Linux host, so the
test records the supported matrix and leaves live native import validation as
a pending Windows acceptance item.

#### `python3 -m compileall -q addon/globalPlugins/WordBridge/lib/coseeing_auth.py tests/test_coseeing_auth_bundle.py`

```text
<no output; exit status 0>
```

#### Source and native bundle checks

```text
coseeing_auth/__init__.py byte-for-byte-match
py311-win32/_cffi_backend.cp311-win32.pyd
py313-win_amd64/_cffi_backend.cp313-win_amd64.pyd
```

No Linux `.so` files are included.

### Unresolved platform limitations

- The isolated subprocess validation for the native modules remains skipped on
  Linux and must be run with both corresponding NVDA Windows runtimes before
  release. The test does not claim live Windows validation.

## Review fix report, round 3 (2026-09-13)

### Findings addressed

- Windows subprocesses now receive an explicit sanitized environment containing
  only available `SystemRoot`/`SystemDrive` values and a `PATH` consisting only
  of the selected dependency bundle and addon package. `PYTHONPATH` is omitted,
  and the subprocess asserts it is absent.
- The Windows configuration contract runs fully in the isolated subprocess,
  including all approved URI, scope, client, and timeout assertions. The same
  process selects and validates `py311-win32` or `py313-win_amd64`, then
  `build_auth_config()` selects the matching dependency directory.
- The non-Windows test no longer adds `sysconfig` `purelib` or any host
  site-packages to `sys.path`. It explicitly skips the complete configuration
  and native import checks because the supplied bundles contain Windows native
  modules that cannot execute on Linux.
- `coseeing_auth/__init__.py` remains byte-for-byte identical to the supplied
  package source.

### Fix commit

- The round-3 fix commit is recorded after this report is staged.

### Covering tests and checks

#### `python3 -m pytest tests/test_coseeing_auth_bundle.py -q`

```text
s.s                                                                      [100%]
1 passed, 2 skipped in 0.02s
```

The passing test verifies both runtime bundle layouts and native backend file
presence. The first skip is the complete Windows configuration contract, and
the second is the Windows dependency import test. Both are explicitly skipped
on Linux with clear Windows runtime reasons; no live native validation is
claimed.

#### `python3 -m compileall -q addon/globalPlugins/WordBridge/lib/coseeing_auth.py tests/test_coseeing_auth_bundle.py`

```text
<no output; exit status 0>
```

#### Source preservation check

```text
coseeing_auth/__init__.py byte-for-byte-match
```

### Unresolved platform limitations

- The complete contract and all native origin checks require execution under
  both CPython 3.11 win32 and CPython 3.13 win_amd64 NVDA runtimes. Those
  runtimes are unavailable on this Linux host, so Windows acceptance remains
  pending.

## Review fix report, round 4 (2026-09-13)

### Findings addressed

- Restored the non-Windows `-I -S` subprocess for the complete AuthConfig
  contract. It uses an empty environment and only the addon `lib` source plus
  a temporary controlled `coseeing_auth` fixture.
- The fixture copies the supplied `models.py` and `errors.py` source, so the
  real AuthConfig validation runs without importing Windows-native or
  host-installed dependencies. The user-supplied `coseeing_auth` package
  source and existing Windows sanitized-runtime checks remain unchanged.
- The subprocess asserts issuer, client ID, all scopes, both callback URIs,
  callback timeout, absent `PYTHONPATH`, and fixture import origin.

### Covering checks

#### `python3 -m pytest tests/test_coseeing_auth_bundle.py -q`

```text
..s                                                                      [100%]
2 passed, 1 skipped in 0.07s
```

#### `python3 -m compileall -q addon/globalPlugins/WordBridge/lib/coseeing_auth.py tests/test_coseeing_auth_bundle.py`

```text
<no output>
```

Exit status: `0`.

#### `git diff --check`

```text
<no output>
```

Exit status: `0`.
