# Coseeing auth bundle dependencies

The add-on supports the range declared in `buildVars.py`: NVDA 2024.1 through
2026.1.1. The dependency bundle has a runtime-specific directory for each
supported NVDA runtime: CPython 3.11 32-bit (`py311-win32`) and CPython 3.13
64-bit (`py313-win_amd64`). The integration layer selects the directory from
the running Python version and pointer width.

### CPython 3.11 32-bit (`py311-win32`)

| Package | Version | Wheel | License |
| --- | --- | --- | --- |
| Authlib | 1.6.2 | `authlib-1.6.2-py2.py3-none-any.whl` | BSD-3-Clause |
| requests | 2.32.5 | `requests-2.32.5-py3-none-any.whl` | Apache-2.0 |
| PyJWT | 2.10.1 | `PyJWT-2.10.1-py3-none-any.whl` | MIT |
| cryptography | 45.0.7 | `cryptography-45.0.7-cp311-abi3-win32.whl` | Apache-2.0 / BSD-3-Clause |
| cffi | 2.1.1 | `cffi-2.1.1-cp311-cp311-win32.whl` | MIT |
| pycparser | 3.0 | `pycparser-3.0-py3-none-any.whl` | BSD-3-Clause |
| charset-normalizer | 3.5.1 | `charset_normalizer-3.5.1-cp311-cp311-win32.whl` | MIT |
| idna | 3.19 | `idna-3.19-py3-none-any.whl` | BSD-3-Clause |
| urllib3 | 2.7.0 | `urllib3-2.7.0-py3-none-any.whl` | MIT |
| certifi | 2026.7.22 | `certifi-2026.7.22-py3-none-any.whl` | MPL-2.0 |

The CPython 3.13 x64 directory contains the same package versions and pure
Python wheels, with these runtime-specific native wheels:

| Package | Wheel |
| --- | --- |
| cryptography | `cryptography-45.0.7-cp311-abi3-win_amd64.whl` |
| cffi | `cffi-2.1.1-cp313-cp313-win_amd64.whl` |
| charset-normalizer | `charset_normalizer-3.5.1-cp313-cp313-win_amd64.whl` |

Both directories include `_cffi_backend` from the matching cffi wheel. The
package directories and `.dist-info` metadata contain the installed versions
and license metadata. No Linux `.so` files are included.

The Windows import test uses isolated mode, selects the matching runtime
directory, and verifies all direct and transitive modules resolve from that
directory. It is skipped on non-Windows development hosts and must be run with
both supported NVDA Python runtimes on Windows before release.
