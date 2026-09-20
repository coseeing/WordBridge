"""R03 feasibility probe: can the auth bundle be isolated from NVDA's imports?

Run inside NVDA's Python Console (NVDA+control+z):

    exec(open(r"C:\\path\\to\\2026-09-20-r03-import-isolation-probe.py", encoding="utf8").read())

It prints a report and also writes it to %TEMP%\\wordbridge-r03-probe.txt.
It imports things and restores what it changed; it writes no product files.

Set BUNDLE below to the installed add-on's dependency directory, normally:
  %APPDATA%\\nvda\\addons\\WordBridge\\globalPlugins\\WordBridge\\package\\_coseeing_auth_deps\\py313-win_amd64
"""

import importlib
import importlib.util
import os
import sys
import tempfile
import traceback
import types

BUNDLE = os.path.join(
	os.environ.get("APPDATA", ""),
	"nvda", "addons", "WordBridge", "globalPlugins", "WordBridge",
	"package", "_coseeing_auth_deps", "py313-win_amd64",
)

HOST_SUBMODULES = [
	"cryptography.hazmat.bindings._rust",
	"cryptography.hazmat.primitives.hashes",
	"cryptography.hazmat.primitives.serialization",
	"cryptography.hazmat.primitives.asymmetric.rsa",
	"cryptography.hazmat.primitives.asymmetric.ec",
	"cryptography.hazmat.primitives.asymmetric.ed25519",
	"cryptography.hazmat.primitives.asymmetric.padding",
	"cryptography.x509",
]


def probe_0():
	lines = ["== PROBE 0: host inventory =="]
	lines.append(f"python: {sys.version}")
	lines.append(f"bundle path exists: {os.path.isdir(BUNDLE)} -> {BUNDLE}")
	for name in ("cryptography", "requests", "urllib3", "certifi", "idna", "cffi"):
		preloaded = name in sys.modules
		try:
			module = importlib.import_module(name)
		except Exception as error:
			lines.append(f"{name}: UNAVAILABLE ({type(error).__name__}: {error})")
			continue
		version = getattr(module, "__version__", "?")
		lines.append(f"{name}: version={version} preloaded={preloaded} file={getattr(module, '__file__', '?')}")
	for name in HOST_SUBMODULES:
		try:
			importlib.import_module(name)
		except Exception as error:
			lines.append(f"host submodule MISSING: {name} ({type(error).__name__}: {error})")
		else:
			lines.append(f"host submodule OK: {name}")
	return lines


def probe_1():
	lines = ["== PROBE 1: prefixed native extension load (decides approach B) =="]
	target = os.path.join(BUNDLE, "cryptography", "hazmat", "bindings", "_rust.pyd")
	lines.append(f"bundle _rust.pyd exists: {os.path.isfile(target)}")
	if not os.path.isfile(target):
		lines.append("PROBE1 RESULT: SKIPPED (bundle not found)")
		return lines

	parent_name = "_wb_vendor_probe"
	parent = types.ModuleType(parent_name)
	parent.__path__ = []
	sys.modules.setdefault(parent_name, parent)
	# The extension's init symbol is PyInit__rust, which CPython derives from
	# the LAST component of the module name, so a private prefix is legal.
	name = parent_name + "._rust"
	try:
		spec = importlib.util.spec_from_file_location(name, target)
		module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(module)
	except ImportError as error:
		lines.append(f"PROBE1 RESULT: ImportError -> {error}")
	except Exception as error:
		lines.append(f"PROBE1 RESULT: {type(error).__name__} -> {error}")
		lines.append(traceback.format_exc())
	else:
		lines.append(f"PROBE1 RESULT: SUCCESS -> {module}")
	finally:
		sys.modules.pop(name, None)
		sys.modules.pop(parent_name, None)

	try:
		host_rust = importlib.import_module("cryptography.hazmat.bindings._rust")
	except Exception as error:
		lines.append(f"host _rust BROKEN after probe: {type(error).__name__}: {error}")
	else:
		lines.append(f"host _rust still importable after probe: {host_rust}")
	return lines


def _crypto_module_names():
	return [n for n in list(sys.modules) if n == "cryptography" or n.startswith("cryptography.")]


def _exercise(jwt, RSAKey):
	key = RSAKey.generate_key(2048)
	token = jwt.encode({"alg": "RS256"}, {"sub": "probe"}, key)
	jwt.decode(token, key)


def probe_2():
	lines = ["== PROBE 2: swap-and-restore leakage (decides approach A) =="]
	if not os.path.isdir(BUNDLE):
		lines.append("PROBE2 RESULT: SKIPPED (bundle not found)")
		return lines

	saved = {name: sys.modules[name] for name in _crypto_module_names()}
	lines.append(f"host cryptography modules snapshotted: {len(saved)}")
	inserted = BUNDLE not in sys.path
	jwt = RSAKey = None
	if inserted:
		sys.path.insert(0, BUNDLE)
	try:
		for name in list(saved):
			del sys.modules[name]
		from joserfc import jwt as bundle_jwt
		from joserfc.jwk import RSAKey as BundleRSAKey
		jwt, RSAKey = bundle_jwt, BundleRSAKey
		_exercise(jwt, RSAKey)
		lines.append("PROBE2 swapped RS256 sign+verify: OK")
	except Exception as error:
		lines.append(f"PROBE2 swapped RS256 sign+verify: FAILED -> {type(error).__name__}: {error}")
		lines.append(traceback.format_exc())
	finally:
		for name in _crypto_module_names():
			del sys.modules[name]
		sys.modules.update(saved)
		if inserted and BUNDLE in sys.path:
			sys.path.remove(BUNDLE)

	if jwt is None:
		lines.append("PROBE2 post-restore: SKIPPED (swapped phase failed)")
	else:
		try:
			_exercise(jwt, RSAKey)
		except Exception as error:
			lines.append(f"PROBE2 post-restore RS256: FAILED -> {type(error).__name__}: {error}")
			lines.append(traceback.format_exc())
			lines.append("  ^ the module named above must go on approach A's eager-import list")
		else:
			lines.append("PROBE2 post-restore RS256: OK -> approach A is viable")

	try:
		host = importlib.import_module("cryptography")
	except Exception as error:
		lines.append(f"host cryptography BROKEN after restore: {type(error).__name__}: {error}")
	else:
		lines.append(f"host cryptography.__file__ after restore: {getattr(host, '__file__', '?')}")
	return lines


def main():
	report = []
	for probe in (probe_0, probe_1, probe_2):
		try:
			report.extend(probe())
		except Exception:
			report.append(f"{probe.__name__} CRASHED:")
			report.append(traceback.format_exc())
		report.append("")
	text = "\n".join(report)
	print(text)
	destination = os.path.join(tempfile.gettempdir(), "wordbridge-r03-probe.txt")
	try:
		with open(destination, "w", encoding="utf8") as handle:
			handle.write(text)
		print(f"report written to {destination}")
	except Exception as error:
		print(f"could not write report: {type(error).__name__}: {error}")


main()
