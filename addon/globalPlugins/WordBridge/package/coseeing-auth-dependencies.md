# Coseeing auth bundle dependencies

The add-on supports the range declared in `buildVars.py`: NVDA 2026.1 through
2026.1.1. The dependency bundle targets CPython 3.13 64-bit
(`py313-win_amd64`).

| Package | Version | Wheel | License |
| --- | --- | --- | --- |
| Authlib | 1.8.0 | `authlib-1.8.0-py2.py3-none-any.whl` | BSD-3-Clause |
| requests | 2.34.2 | `requests-2.34.2-py3-none-any.whl` | Apache-2.0 |
| PyJWT | 2.14.0 | `pyjwt-2.14.0-py3-none-any.whl` | MIT |
| joserfc | 1.7.5 | `joserfc-1.7.5-py3-none-any.whl` | BSD-3-Clause |
| pycparser | 3.0 | `pycparser-3.0-py3-none-any.whl` | BSD-3-Clause |
| idna | 3.19 | `idna-3.19-py3-none-any.whl` | BSD-3-Clause |
| urllib3 | 2.7.0 | `urllib3-2.7.0-py3-none-any.whl` | MIT |
| certifi | 2026.7.22 | `certifi-2026.7.22-py3-none-any.whl` | MPL-2.0 |

The CPython 3.13 x64 directory contains the package versions and pure Python
wheels, with these runtime-specific native wheels:

| Package | Wheel |
| --- | --- |
| cryptography | `cryptography-50.0.1-cp311-abi3-win_amd64.whl` |
| cffi | `cffi-2.1.1-cp313-cp313-win_amd64.whl` |
| charset-normalizer | `charset_normalizer-3.5.1-cp313-cp313-win_amd64.whl` |

The directory includes `_cffi_backend` from the matching cffi wheel. The
package directory and `.dist-info` metadata contain the installed versions and
license metadata. No Linux `.so` files are included.

The Windows import test runs the private `_wb_vendor` sandbox against the
real bundle and asserts the contract in the table below: the nine "must come
from us" modules resolve under `_wb_vendor.*` from inside this directory
(from the `_coseeing_auth_deps` runtime subdirectory for the four native/
third-party ones, from the bundle itself for `coseeing_auth` and the CJK
helpers), and the eight "must come from the host" modules never resolve from
inside this directory even though bundled copies of them ship here too. It
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
| must come from us | `cryptography`, `authlib`, `joserfc`, `jwt`, `coseeing_auth`, `pypinyin`, `zhon`, `hanzidentifier`, `chinese_converter` | `_wb_vendor.*` only; never a global top-level name |
| must come from the host | `requests`, `urllib3`, `certifi`, `idna`, `charset_normalizer`, `cffi`, `_cffi_backend`, `pycparser` | NVDA's copies; the bundled copies are never loaded and there is no fallback to them |

`cryptography` needs isolating because NVDA ships a trimmed 48.0.1 that lacks
the six modules `authlib`'s joserfc import pulls in:
`hazmat.primitives.kdf{,.concatkdf,.hkdf,.pbkdf2}`, `hazmat.primitives.keywrap`
and `hazmat.primitives.padding`.

Adding a package to this directory without adding it to a category list fails
`tests/test_vendor_sandbox.py::test_every_bundled_top_level_name_is_classified`.
