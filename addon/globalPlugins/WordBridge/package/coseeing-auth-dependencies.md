# Coseeing auth bundle dependencies

The add-on supports the range declared in `buildVars.py`: NVDA 2024.1 through
2026.1.1. The corresponding NVDA Windows runtime is CPython 3.11, 32-bit
(win32). The dependency bundle was prepared for that runtime from PyPI wheels.

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

The package directories and `.dist-info` metadata contain the installed
versions and license metadata. `cryptography` and `cffi` are the only native
dependencies; their bundle files are Windows `win32` wheels and no Linux
`.so` files are included.

The Windows import test is skipped on non-Windows development hosts and must
be run with the supported NVDA Python runtime on Windows before release.
