"""Does NVDA's `_rust` still carry what the three missing wrappers need?

The first probe (2026-09-22-host-cryptography-probe.py) found NVDA's
cryptography 48.0.1 complete for PyJWT but missing three things joserfc needs:
`hazmat.primitives.kdf` (the whole package), `hazmat.primitives.keywrap` and
`hazmat.primitives.padding`. Without them joserfc will not import, and neither
will `authlib.integrations.requests_client`, which imports it transitively.

All six of those files are thin Python re-exports of the Rust extension:

	kdf/hkdf.py        HKDF = rust_openssl.kdf.HKDF
	keywrap.py         aes_key_wrap = rust_openssl.keywrap.aes_key_wrap
	padding.py         from ..bindings._rust import PKCS7PaddingContext, ...

NVDA trimmed the Python files out of library.zip, but `_rust.pyd` is one
binary -- if the Rust symbols are still in it, we can gap-fill those six small
files under their canonical names (the same pattern as the `secrets` gap-fill:
adding names the host lacks, shadowing nothing) and drop the entire bundled
cryptography. This measures whether that is possible.

Run inside NVDA's Python Console (NVDA+control+z):

	exec(open(r"D:\\2026-09-22-host-rust-symbols-probe.py", encoding="utf8").read())

Report goes to %TEMP%\\wordbridge-host-rust-probe.txt. This probe only reads
attributes and runs two self-contained crypto operations; it changes nothing.
"""

import datetime
import os
import sys
import tempfile
import traceback

_lines = []
_missing = []


def report(line):
	_lines.append(line)
	print(line)


def want(container, path, names):
	for name in names:
		if hasattr(container, name):
			report(f"PASS {path}.{name}")
		else:
			_missing.append(f"{path}.{name}")
			report(f"FAIL {path}.{name} is absent")


def check(label, function):
	try:
		function()
	except Exception:
		_missing.append(label)
		report(f"{label} CRASHED:")
		for line in traceback.format_exc().splitlines():
			report(f"    {line}")


def symbols():
	report("== _rust symbols the gap-fill would need ==")
	import cryptography
	from cryptography.hazmat.bindings import _rust
	report(f"INFO cryptography version={getattr(cryptography, '__version__', '?')}")

	# padding.py re-exports these four from _rust itself, not from _rust.openssl.
	want(_rust, "_rust", [
		"ANSIX923PaddingContext", "ANSIX923UnpaddingContext",
		"PKCS7PaddingContext", "PKCS7UnpaddingContext",
	])
	openssl = getattr(_rust, "openssl", None)
	if openssl is None:
		_missing.append("_rust.openssl")
		report("FAIL _rust.openssl is absent -- nothing below can be checked")
		return
	want(getattr(openssl, "kdf", None) or object(), "_rust.openssl.kdf", [
		"HKDF", "HKDFExpand", "PBKDF2HMAC", "ConcatKDFHash", "ConcatKDFHMAC",
	])
	want(getattr(openssl, "keywrap", None) or object(), "_rust.openssl.keywrap", [
		"aes_key_wrap", "aes_key_unwrap", "aes_key_wrap_with_padding", "aes_key_unwrap_with_padding",
	])

	# kdf/__init__.py and padding.py both import this name.
	from cryptography import utils
	want(utils, "cryptography.utils", ["Buffer"])


def functional():
	"""Attribute presence is not proof the Rust side works. Exercise it."""
	report("== functional ==")
	from cryptography.hazmat.bindings._rust import PKCS7PaddingContext, PKCS7UnpaddingContext
	from cryptography.hazmat.bindings._rust import openssl as rust_openssl
	from cryptography.hazmat.primitives import hashes

	derived = rust_openssl.kdf.HKDF(hashes.SHA256(), 32, b"salt", b"info").derive(b"key material")
	report(f"PASS HKDF derived {len(derived)} bytes")

	expected = b"\x11" * 32
	wrapped = rust_openssl.keywrap.aes_key_wrap(b"\x00" * 32, expected)
	unwrapped = rust_openssl.keywrap.aes_key_unwrap(b"\x00" * 32, wrapped)
	report(f"PASS AES key wrap/unwrap round trip ({unwrapped == expected})")

	padder = PKCS7PaddingContext(128)
	padded = padder.update(b"12345678") + padder.finalize()
	unpadder = PKCS7UnpaddingContext(128)
	restored = unpadder.update(padded) + unpadder.finalize()
	report(f"PASS PKCS7 pad/unpad round trip ({restored == b'12345678'})")


report(f"WordBridge host _rust symbol probe {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
report(f"python={sys.version_info[:3]} platform={sys.platform}")
check("== symbols ==", symbols)
check("== functional ==", functional)

report("== verdict ==")
if _missing:
	report(f"VERDICT gap-fill NOT possible -- {len(_missing)} missing: {_missing}")
else:
	report("VERDICT gap-fill possible: the host _rust has everything the six wrappers need")

_path = os.path.join(tempfile.gettempdir(), "wordbridge-host-rust-probe.txt")
try:
	with open(_path, "w", encoding="utf8") as handle:
		handle.write("\n".join(_lines) + "\n")
	print(f"report written to {_path}")
except Exception as error:
	print(f"could not write report: {type(error).__name__}: {error}")
