# Coseeing auth bundle dependencies

The add-on supports the range declared in `buildVars.py`: NVDA 2026.1 through
2026.1.1. The dependency bundle targets CPython 3.13 64-bit
(`py313-win_amd64`).

| Package | Version | Wheel | License |
| --- | --- | --- | --- |
| Authlib | 1.8.0 | `authlib-1.8.0-py2.py3-none-any.whl` | BSD-3-Clause |
| PyJWT | 2.14.0 | `pyjwt-2.14.0-py3-none-any.whl` | MIT |
| joserfc | 1.7.5 | `joserfc-1.7.5-py3-none-any.whl` | BSD-3-Clause |

The CPython 3.13 x64 directory contains only those three pure Python wheels
and their `.dist-info` metadata (installed versions and licenses). It has no
native code.

`cryptography`, `requests`, `urllib3`, `certifi`, `idna`,
`charset-normalizer`, `cffi` (with `_cffi_backend`) and `pycparser` are
resolved by `pip` as dependencies of the packages above but are **not
shipped**: they come from NVDA (see "must come from the host" below). Remove
them after regenerating the bundle;
`tests/test_vendor_sandbox.py::test_every_bundled_top_level_name_is_classified`
and `::test_no_cryptography_is_bundled` fail if one is left behind.

The Windows import test runs the private `_wb_vendor` sandbox against the
real bundle and asserts the contract in the table below: the nine "must come
from us" modules resolve under `_wb_vendor.*` from inside this directory
(from the `_coseeing_auth_deps` runtime subdirectory for the four native/
third-party ones, from the bundle itself for `coseeing_auth` and the CJK
helpers), and the eight "must come from the host" modules never resolve from
inside this directory. It
is skipped on non-Windows development hosts and must be run on the supported
NVDA Python runtime on Windows before release.

The test runs the interpreter with `-I` only, not `-I -S`. `-S` was dropped
because it forced every import to resolve from the bundle, which is exactly
the old contract this test no longer checks: under the sandbox, category 3
(`requests` and friends) must resolve from *outside* the bundle -- with `-S`
there is no "outside" for those imports to come from, since `-S` suppresses
the site-packages initialization that makes the host's copies importable at
all. `-I` on its own still ignores `PYTHONPATH` and the user site directory,
and the environment the subprocess runs in is still sanitized by
`_sanitized_windows_environment` (only `SystemRoot`/`SystemDrive` survive,
and `PATH` is pinned to the dependency and bundle directories), so the test
still cannot pick up stray configuration from the machine it runs on.

## Import categories

The add-on loads these through the private `_wb_vendor` sandbox rather than by
modifying `sys.path` or `sys.modules`. See
`docs/superpowers/specs/2026-09-20-r03-import-isolation-design.md`.

| Category | Members | Resolution |
| --- | --- | --- |
| stdlib NVDA removed | `secrets` | canonical name, registered only when the host lacks it, sources in `package/_stdlib_gapfill/` |
| must come from us | `authlib`, `joserfc`, `jwt`, `coseeing_auth`, `pypinyin`, `zhon`, `hanzidentifier`, `chinese_converter` | `_wb_vendor.*` only; never a global top-level name |
| must come from the host | `cryptography`, `requests`, `urllib3`, `certifi`, `idna`, `charset_normalizer`, `cffi`, `_cffi_backend`, `pycparser` | NVDA's copies only; not shipped in the bundle, and there is no fallback |
| missing from the host's `cryptography` | `cryptography.hazmat.primitives.kdf{,.concatkdf,.hkdf,.pbkdf2}`, `.keywrap`, `.padding` | canonical name, served from `package/_cryptography_gapfill/` only when NVDA has no copy; never replaces or evicts a loaded module |

`cryptography` must never have a second copy in the NVDA process. Its `_rust`
extension resolves Python classes by absolute module name, so two copies
reject each other's objects with a `TypeError`. WordBridge 2026.9.1 shipped
cryptography 50.0.1 and evicted NVDA's copy, and that broke NVDA Remote: the
local relay server could not build its certificate, so "Get external IP" hung.

NVDA's py2exe build leaves out the six modules that `authlib`'s joserfc import
pulls in, but `_rust.pyd` still carries the symbols behind them. Those modules
are gap-filled from the cryptography 48.0.1 wheel. See
`package/_cryptography_gapfill/README.md`.

Adding a package to this directory without adding it to a category list fails
`tests/test_vendor_sandbox.py::test_every_bundled_top_level_name_is_classified`.
