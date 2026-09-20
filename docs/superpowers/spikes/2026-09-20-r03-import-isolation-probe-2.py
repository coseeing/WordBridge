"""R03 probe v2: what does NVDA actually ship, and what does our stack need?

Run inside NVDA's Python Console (NVDA+control+z), with WordBridge INSTALLED
and ENABLED:

	exec(open(r"C:\\path\\to\\2026-09-20-r03-import-isolation-probe-2.py", encoding="utf8").read())

Probe v1 ran against a host whose `cryptography` WordBridge had already
replaced: `__init__.py` imports `lib.coseeing_auth` at plugin load, which
deletes every `cryptography.*` entry from `sys.modules` and puts the bundle
first on `sys.path`.  So v1's "host inventory" described our own bundle, and
its swap-and-restore probe swapped the bundle for itself.  v1's Probe 1
(prefixed `_rust.pyd` load) is unaffected and stands.

v2 reads NVDA's copy off DISK instead of out of `sys.modules`, so WordBridge
being loaded no longer hides it.  It answers:

  1. Where does NVDA's `cryptography` live, and what is in it?
  2. Which `cryptography` submodules does the Coseeing auth stack actually
     use, and which of those are absent from NVDA's copy?

If (2) comes back EMPTY, the bundled `cryptography` can be dropped and the
whole isolation problem goes away.  If not, the missing list IS the isolation
surface that approach B has to cover.

It imports and reads files; it writes no product files.  The report goes to
stdout and to %TEMP%\\wordbridge-r03-probe-2.txt.
"""

import os
import sys
import tempfile
import traceback
import zipfile

MODULE_SUFFIXES = (".py", ".pyc", ".pyd", ".so")


def _is_crypto_name(name):
	return name == "cryptography" or name.startswith("cryptography.")


def _find_library_zip():
	for entry in sys.path:
		if entry.lower().endswith("library.zip"):
			return entry
	for name in ("requests", "urllib3", "certifi", "idna"):
		module = sys.modules.get(name)
		path = getattr(module, "__file__", "") or ""
		index = path.lower().find("library.zip")
		if index != -1:
			return path[: index + len("library.zip")]
	return None


def _zip_inventory(zip_path):
	"""Every cryptography entry inside library.zip, as forward-slash paths."""
	try:
		with zipfile.ZipFile(zip_path) as archive:
			names = archive.namelist()
	except Exception as error:
		return None, f"{type(error).__name__}: {error}"
	normalised = [name.replace("\\", "/") for name in names]
	return normalised, None


def _disk_inventory(root):
	"""Every path under the NVDA program directory whose name mentions cryptography."""
	found = []
	for directory, _subdirs, files in os.walk(root):
		lowered = directory.lower()
		relevant_dir = "cryptography" in lowered
		for filename in files:
			if relevant_dir or "cryptography" in filename.lower() or "_rust" in filename.lower():
				full = os.path.join(directory, filename)
				found.append(os.path.relpath(full, root).replace("\\", "/"))
	return found


def probe_0():
	"""Say plainly whose cryptography is currently loaded, so v1's mistake cannot repeat."""
	lines = ["== PROBE 0: which cryptography is loaded right now =="]
	lines.append(f"python: {sys.version}")
	module = sys.modules.get("cryptography")
	if module is None:
		lines.append("cryptography: NOT loaded (WordBridge is disabled, or auth was never touched)")
		lines.append("VERDICT: clean host - probe 2's required-set measurement will be EMPTY")
		return lines
	path = getattr(module, "__file__", "?") or "?"
	lines.append(f"sys.modules['cryptography'].__file__ = {path}")
	contaminated = "addons" in path.lower() and "wordbridge" in path.lower()
	if contaminated:
		lines.append("VERDICT: CONTAMINATED - this is WordBridge's bundle, not NVDA's.")
		lines.append("  Expected when the add-on is enabled; probes 1 and 2 are built for this.")
	else:
		lines.append("VERDICT: this looks like NVDA's own copy.")
	loaded = sorted(name for name in sys.modules if _is_crypto_name(name))
	lines.append(f"loaded cryptography.* modules: {len(loaded)}")
	return lines


def probe_1():
	"""Inventory NVDA's cryptography from disk, bypassing sys.modules entirely."""
	lines = ["== PROBE 1: what NVDA ships on disk =="]
	zip_path = _find_library_zip()
	lines.append(f"library.zip: {zip_path}")
	if zip_path is None:
		lines.append("PROBE1 RESULT: FAILED - could not locate library.zip")
		return lines, None

	names, error = _zip_inventory(zip_path)
	if names is None:
		lines.append(f"PROBE1 RESULT: FAILED to read zip -> {error}")
		return lines, None

	crypto_entries = sorted(n for n in names if n.startswith("cryptography/") or n == "cryptography")
	lines.append(f"cryptography entries inside library.zip: {len(crypto_entries)}")
	dist_info = sorted(n for n in names if "cryptography-" in n.lower())
	lines.append(f"cryptography dist-info entries: {dist_info if dist_info else 'NONE (version unknown from the zip)'}")

	program_dir = os.path.dirname(zip_path)
	lines.append(f"NVDA program dir: {program_dir}")
	try:
		disk_entries = _disk_inventory(program_dir)
	except Exception as error:
		disk_entries = []
		lines.append(f"disk walk failed: {type(error).__name__}: {error}")
	native = sorted(n for n in disk_entries if n.lower().endswith((".pyd", ".dll")))
	lines.append(f"cryptography-related files beside the zip: {len(disk_entries)}")
	lines.append(f"  native among them: {native if native else 'NONE'}")

	inventory = set(crypto_entries) | {n for n in disk_entries}
	lines.append("")
	lines.append("-- full library.zip cryptography listing --")
	lines.extend(f"  {name}" for name in crypto_entries)
	return lines, inventory


def _exercise():
	"""Force the auth stack to do real RS256 work so lazy imports actually fire."""
	from joserfc import jwt
	from joserfc.jwk import RSAKey

	key = RSAKey.generate_key(2048)
	token = jwt.encode({"alg": "RS256"}, {"sub": "probe"}, key)
	jwt.decode(token, key)


def probe_2(inventory):
	"""Measure the submodules the stack really needs, then diff against NVDA's copy."""
	lines = ["== PROBE 2: what the auth stack needs, and what NVDA is missing =="]
	before = {name for name in sys.modules if _is_crypto_name(name)}
	lines.append(f"cryptography modules already loaded before the exercise: {len(before)}")
	try:
		_exercise()
	except Exception as error:
		lines.append(f"RS256 exercise FAILED -> {type(error).__name__}: {error}")
		lines.append(traceback.format_exc())
		lines.append("PROBE2 RESULT: required set is INCOMPLETE - treat the list below as a lower bound")
	else:
		lines.append("RS256 sign+verify through the loaded stack: OK")

	required = sorted(name for name in sys.modules if _is_crypto_name(name))
	lines.append(f"cryptography modules the stack touches: {len(required)}")

	rust_children = [n for n in required if ".bindings._rust." in n]
	lines.append("")
	lines.append("-- submodules registered BY the _rust extension under absolute names --")
	if rust_children:
		lines.extend(f"  {name}" for name in rust_children)
		lines.append("  ^ these are created by the extension, not by files. Approach B must")
		lines.append("    check whether loading _rust under a private prefix still writes THESE")
		lines.append("    global names; if it does, B's 'touches no global sys.modules' premise fails.")
	else:
		lines.append("  NONE - this is the EXPECTED result.  Verified off-NVDA against the same")
		lines.append("    version the bundle ships (cryptography 50.0.1): _rust exposes asn1,")
		lines.append("    exceptions, ocsp and _openssl as plain ATTRIBUTES and registers no")
		lines.append("    absolute sys.modules names, so approach B has no hidden native")
		lines.append("    pollution here.  Anything listed above would contradict that.")

	if inventory is None:
		lines.append("")
		lines.append("PROBE2 RESULT: SKIPPED gap analysis (probe 1 produced no inventory)")
		return lines

	missing = []
	present = []
	for name in required:
		if ".bindings._rust." in name:
			continue
		relative = name.replace(".", "/")
		candidates = {relative + suffix for suffix in MODULE_SUFFIXES}
		package_inits = {relative + "/__init__" + suffix for suffix in MODULE_SUFFIXES}
		if inventory & (candidates | package_inits):
			present.append(name)
		else:
			missing.append(name)

	lines.append("")
	lines.append(f"-- gap: needed by the stack, ABSENT from NVDA's copy ({len(missing)}) --")
	if missing:
		lines.extend(f"  {name}" for name in missing)
	else:
		lines.append("  NONE")
	lines.append(f"(present in NVDA's copy: {len(present)})")

	lines.append("")
	if missing:
		lines.append("PROBE2 VERDICT: NVDA's cryptography is INSUFFICIENT. The list above is the")
		lines.append("  isolation surface; approach B is required and must cover exactly it.")
	else:
		lines.append("PROBE2 VERDICT: NVDA's cryptography COVERS everything the stack imported.")
		lines.append("  Before dropping our bundle, check the VERSIONS below - a present-but-older")
		lines.append("  module can still be missing the API joserfc/authlib call.")

	loaded_files = {}
	for name in required[:1] + [n for n in required if n.count(".") <= 2][:12]:
		module = sys.modules.get(name)
		loaded_files[name] = getattr(module, "__file__", "(no __file__)")
	lines.append("")
	lines.append("-- where the currently loaded (bundle) modules come from --")
	for name, path in loaded_files.items():
		lines.append(f"  {name}: {path}")
	return lines


def main():
	report = []
	inventory = None
	try:
		report.extend(probe_0())
	except Exception:
		report.append("probe_0 CRASHED:")
		report.append(traceback.format_exc())
	report.append("")

	try:
		lines, inventory = probe_1()
		report.extend(lines)
	except Exception:
		report.append("probe_1 CRASHED:")
		report.append(traceback.format_exc())
	report.append("")

	try:
		report.extend(probe_2(inventory))
	except Exception:
		report.append("probe_2 CRASHED:")
		report.append(traceback.format_exc())
	report.append("")

	text = "\n".join(report)
	print(text)
	destination = os.path.join(tempfile.gettempdir(), "wordbridge-r03-probe-2.txt")
	try:
		with open(destination, "w", encoding="utf8") as handle:
			handle.write(text)
		print(f"report written to {destination}")
	except Exception as error:
		print(f"could not write report: {type(error).__name__}: {error}")


main()
