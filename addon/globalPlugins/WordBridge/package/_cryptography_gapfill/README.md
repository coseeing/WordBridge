# cryptography gap-fill

These six files are copied verbatim from the `cryptography` 48.0.1 wheel
(each one matches that wheel's `RECORD` hash; `tests/test_vendor_sandbox.py`
pins the SHA-256 of every file):

- `cryptography/hazmat/primitives/kdf/__init__.py`
- `cryptography/hazmat/primitives/kdf/concatkdf.py`
- `cryptography/hazmat/primitives/kdf/hkdf.py`
- `cryptography/hazmat/primitives/kdf/pbkdf2.py`
- `cryptography/hazmat/primitives/keywrap.py`
- `cryptography/hazmat/primitives/padding.py`

NVDA ships `cryptography` in `library.zip`, but its py2exe build only collects
modules that something imports statically, so these six files are left out.
The `_rust.pyd` extension is a single binary, so it still contains the symbols
behind them. `joserfc` imports these modules when it loads, and authlib's
`requests_client` imports `joserfc`, so Coseeing authentication needs them.

`lib/vendor.py`'s `install_cryptography_gapfill()` serves these files under
their canonical names, but **only when NVDA has no copy of its own**. Its
finder sits at the end of `sys.meta_path`, and it never replaces or evicts a
module NVDA has already loaded. WordBridge does not ship any other part of
`cryptography`. A second copy in the same process breaks NVDA Remote's local
relay server (see `HOST_ONLY` in `lib/vendor.py`).

The files come from 48.0.1 and not from a newer release because 48.0.1's
`keywrap.py` is pure Python built on `Cipher`/`AES`/`ECB`. From 50.0 on,
`keywrap.py` calls `_rust.openssl.keywrap`, which a 48.x host does not have.
The other five files are byte-identical across 48.0.1, 50.0.0 and 50.0.1.

License: dual Apache-2.0 / BSD-3-Clause. See `LICENSE`, `LICENSE.APACHE` and
`LICENSE.BSD`.
