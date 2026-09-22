"""Can NVDA's own `cryptography` replace the one WordBridge bundles?

Background. R03 loads our `cryptography` under the `_wb_vendor` prefix. That
cannot work: `_rust.pyd` resolves Python types by ABSOLUTE module name
(`cryptography.hazmat.primitives.hashes.HashAlgorithm`) through a C-level
import that never sees the sandbox's `__import__`. With NVDA's copy loaded
under that name, our `SHA256()` fails the host's `isinstance()` check and RS256
verification dies with `TypeError: Expected instance of hashes.HashAlgorithm`.
With no copy loaded under that name at all it dies with a `KeyError` naming the
module it wanted. Either way the prefixed copy is unusable.

So either our copy owns the global `cryptography` name (what the add-on did
before R03, and the pollution R03 exists to remove), or we stop shipping a copy
and use NVDA's. The second is only possible if NVDA's copy has everything the
auth path touches -- the R03 design recorded NVDA's copy as "trimmed", with the
parts we need absent, but did not record WHICH parts. This measures that.

Run inside NVDA's Python Console (NVDA+control+z), with WordBridge installed
and enabled:

	exec(open(r"C:\\path\\to\\2026-09-22-host-cryptography-probe.py", encoding="utf8").read())

Every line is PASS, FAIL, INFO or "<check> CRASHED:". The verdict is the
VERDICT line at the end; FAIL lines above it say what is missing. The report is
also written to %TEMP%\\wordbridge-host-crypto-probe.txt -- send that file.

This probe imports ONLY the host `cryptography` (a plain `import` at Console
scope is not rewritten by the sandbox), so it measures the host copy alone. It
does not modify anything.
"""

import datetime
import os
import sys
import tempfile
import traceback

# What PyJWT's algorithms.py touches. This is the critical path: the ID token
# is verified by PyJWT (coseeing_auth/verification.py), so every one of these
# must resolve or RS256 verification cannot run at all.
JWT_REQUIREMENTS = {
	"cryptography": ["x509"],
	"cryptography.exceptions": ["InvalidSignature", "UnsupportedAlgorithm"],
	"cryptography.hazmat.backends": ["default_backend"],
	"cryptography.hazmat.primitives": ["hashes"],
	"cryptography.hazmat.primitives.asymmetric": ["padding"],
	"cryptography.hazmat.primitives.asymmetric.ec": [
		"ECDSA", "EllipticCurve", "EllipticCurvePrivateKey", "EllipticCurvePrivateNumbers",
		"EllipticCurvePublicKey", "EllipticCurvePublicNumbers",
		"SECP256K1", "SECP256R1", "SECP384R1", "SECP521R1",
	],
	"cryptography.hazmat.primitives.asymmetric.ed25519": ["Ed25519PrivateKey", "Ed25519PublicKey"],
	"cryptography.hazmat.primitives.asymmetric.ed448": ["Ed448PrivateKey", "Ed448PublicKey"],
	"cryptography.hazmat.primitives.asymmetric.rsa": [
		"RSAPrivateKey", "RSAPrivateNumbers", "RSAPublicKey", "RSAPublicNumbers",
		"rsa_crt_dmp1", "rsa_crt_dmq1", "rsa_crt_iqmp", "rsa_recover_prime_factors",
	],
	"cryptography.hazmat.primitives.asymmetric.types": ["PrivateKeyTypes", "PublicKeyTypes"],
	"cryptography.hazmat.primitives.asymmetric.utils": ["decode_dss_signature", "encode_dss_signature"],
	"cryptography.hazmat.primitives.serialization": [
		"Encoding", "NoEncryption", "PrivateFormat", "PublicFormat",
		"load_der_public_key", "load_pem_private_key", "load_pem_public_key", "load_ssh_public_key",
	],
}

# What joserfc touches. Authlib reaches joserfc only through lazy imports the
# login path does not take, so these are reported separately: a FAIL here does
# not block the decision unless the "loaded right now" section shows joserfc
# actually in sys.modules.
JOSERFC_REQUIREMENTS = {
	"cryptography.exceptions": ["InvalidSignature", "InvalidTag"],
	"cryptography.hazmat.primitives.asymmetric.ec": ["ECDH", "derive_private_key", "generate_private_key"],
	"cryptography.hazmat.primitives.asymmetric.rsa": ["generate_private_key"],
	"cryptography.hazmat.primitives.asymmetric.x25519": ["X25519PrivateKey", "X25519PublicKey"],
	"cryptography.hazmat.primitives.asymmetric.x448": ["X448PrivateKey", "X448PublicKey"],
	"cryptography.hazmat.primitives.ciphers": ["Cipher"],
	"cryptography.hazmat.primitives.ciphers.algorithms": ["AES"],
	"cryptography.hazmat.primitives.ciphers.modes": ["CBC", "GCM"],
	"cryptography.hazmat.primitives.kdf.concatkdf": ["ConcatKDFHash"],
	"cryptography.hazmat.primitives.kdf.hkdf": ["HKDF"],
	"cryptography.hazmat.primitives.kdf.pbkdf2": ["PBKDF2HMAC"],
	"cryptography.hazmat.primitives.keywrap": ["InvalidUnwrap", "aes_key_unwrap", "aes_key_wrap"],
	"cryptography.hazmat.primitives.padding": ["PKCS7"],
	"cryptography.hazmat.primitives.serialization": [
		"BestAvailableEncryption", "KeySerializationEncryption",
		"load_der_private_key", "load_ssh_private_key",
	],
	"cryptography.x509": ["load_pem_x509_certificate"],
}

_lines = []


def report(line):
	_lines.append(line)
	print(line)


def check(label, function):
	try:
		function()
	except Exception:
		report(f"{label} CRASHED:")
		for line in traceback.format_exc().splitlines():
			report(f"    {line}")


def _import(name):
	__import__(name)
	return sys.modules[name]


def describe_host_copy():
	report("== host cryptography ==")
	module = _import("cryptography")
	report(f"INFO version={getattr(module, '__version__', '?')}")
	report(f"INFO file={getattr(module, '__file__', '?')}")
	report(f"INFO loader={type(getattr(getattr(module, '__spec__', None), 'loader', None)).__name__}")
	try:
		rust = _import("cryptography.hazmat.bindings._rust")
		report(f"INFO _rust={getattr(rust, '__file__', '?')}")
	except Exception as error:
		report(f"FAIL cryptography.hazmat.bindings._rust is missing: {type(error).__name__}: {error}")


def _resolves(module, name, symbol):
	"""`hashes` and `padding` are submodules, not attributes of their parent.

	A package does not carry a submodule as an attribute until something
	imports it, so `hasattr()` alone reports a perfectly healthy
	`cryptography.hazmat.primitives.hashes` as missing. Import it as the
	fallback -- that is what the `from ... import hashes` in PyJWT does.
	"""
	if hasattr(module, symbol):
		return True
	try:
		_import(f"{name}.{symbol}")
	except Exception:
		return False
	return True


def probe(title, requirements, verdict_key):
	report(f"== {title} ==")
	missing = []
	for name in sorted(requirements):
		try:
			module = _import(name)
		except Exception as error:
			missing.append(name)
			report(f"FAIL {name} does not import: {type(error).__name__}: {error}")
			continue
		absent = [symbol for symbol in requirements[name] if not _resolves(module, name, symbol)]
		if absent:
			missing.append(name)
			report(f"FAIL {name} is missing {absent}")
		else:
			report(f"PASS {name} ({len(requirements[name])} names)")
	_verdicts[verdict_key] = not missing


def rs256_round_trip():
	"""The real thing: sign and verify with the host copy, exactly as PyJWT does."""
	report("== RS256 sign/verify on the host copy ==")
	from cryptography.exceptions import InvalidSignature
	from cryptography.hazmat.primitives import hashes
	from cryptography.hazmat.primitives.asymmetric import padding, rsa

	key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
	message = b"wordbridge host cryptography probe"
	signature = key.sign(message, padding.PKCS1v15(), hashes.SHA256())
	key.public_key().verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
	report("PASS sign/verify with a generated key")

	# PyJWT builds the JWKS key this way (RSAAlgorithm.from_jwk), so verify
	# through a reconstructed public key too, not just the generated one.
	numbers = key.public_key().public_numbers()
	rebuilt = rsa.RSAPublicNumbers(numbers.e, numbers.n).public_key()
	rebuilt.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
	report("PASS verify through RSAPublicNumbers(...).public_key()")

	try:
		rebuilt.verify(b"\x00" * len(signature), message, padding.PKCS1v15(), hashes.SHA256())
	except InvalidSignature:
		report("PASS a bad signature raises InvalidSignature")
	else:
		report("FAIL a bad signature was accepted")
		_verdicts["rs256"] = False
		return
	_verdicts["rs256"] = True


def loaded_modules():
	"""Which copies are live right now -- and whether joserfc is ever loaded."""
	report("== loaded right now ==")
	for prefix in ("cryptography", "_wb_vendor.cryptography"):
		module = sys.modules.get(prefix)
		report(f"INFO {prefix}: {getattr(module, '__file__', 'not loaded')}")
	for name in ("jwt", "joserfc", "authlib", "_wb_vendor.jwt", "_wb_vendor.joserfc", "_wb_vendor.authlib"):
		report(f"INFO {name}: {'loaded' if name in sys.modules else 'not loaded'}")
	tops = sorted({n.split(".")[1] for n in sys.modules if n.startswith("_wb_vendor.") and n.count(".") >= 1})
	report(f"INFO _wb_vendor top-level names loaded: {tops}")


_verdicts = {}

report(f"WordBridge host-cryptography probe {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
report(f"python={sys.version_info[:3]} platform={sys.platform}")
check("== host cryptography ==", describe_host_copy)
check("== PyJWT requirements ==", lambda: probe("PyJWT requirements (critical path)", JWT_REQUIREMENTS, "jwt"))
check("== joserfc requirements ==", lambda: probe("joserfc requirements (only if loaded)", JOSERFC_REQUIREMENTS, "joserfc"))
check("== RS256 round trip ==", rs256_round_trip)
check("== loaded right now ==", loaded_modules)

report("== verdict ==")
for key in ("jwt", "joserfc", "rs256"):
	if key not in _verdicts:
		report(f"INFO {key}: check did not finish -- treat as unknown, not as a pass")
	else:
		report(f"INFO {key}: {'ok' if _verdicts[key] else 'INCOMPLETE'}")
if _verdicts.get("jwt") and _verdicts.get("rs256"):
	report("VERDICT host cryptography can replace the bundled copy for the login path")
else:
	report("VERDICT host cryptography is NOT sufficient -- our copy must own the global name")

_path = os.path.join(tempfile.gettempdir(), "wordbridge-host-crypto-probe.txt")
try:
	with open(_path, "w", encoding="utf8") as handle:
		handle.write("\n".join(_lines) + "\n")
	print(f"report written to {_path}")
except Exception as error:
	print(f"could not write report: {type(error).__name__}: {error}")
