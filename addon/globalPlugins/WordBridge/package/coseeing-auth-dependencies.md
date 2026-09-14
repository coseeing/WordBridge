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

The Windows import test uses isolated mode, selects the matching runtime
directory, and verifies all direct and transitive modules resolve from that
directory. It is skipped on non-Windows development hosts and must be run on
the supported NVDA Python runtime on Windows before release.
