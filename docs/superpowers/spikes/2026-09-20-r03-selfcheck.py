"""R03 self-check: prove WordBridge is not polluting NVDA's import state.

Run inside NVDA's Python Console (NVDA+control+z) with WordBridge INSTALLED
and ENABLED, ideally alongside other add-ons:

	exec(open(r"C:\\path\\to\\2026-09-20-r03-selfcheck.py", encoding="utf8").read())

Every line below is PASS or FAIL.  Report to
%TEMP%\\wordbridge-r03-selfcheck.txt.

Deviation from spec test 14, stated deliberately: the spec describes
snapshotting sys.modules and sys.path "before and after the add-on loads".
That is not obtainable from NVDA's Python Console -- by the time the Console
exists, the add-on has already loaded, so there is no "before" to snapshot.
This script instead asserts the end-state invariants directly: that nothing
outside _wb_vendor was touched. That measures the same property -- no
pollution of the shared process -- with an instrument that actually exists
in NVDA. Do not "fix" this by trying to snapshot an earlier state; there is
none to snapshot from here.
"""

import builtins
import os
import sys
import tempfile
import traceback

PREFIX = "_wb_vendor"
ISOLATED = (
	"cryptography", "authlib", "joserfc", "jwt", "coseeing_auth",
	"pypinyin", "zhon", "hanzidentifier", "chinese_converter",
)
HOST_ONLY = (
	"requests", "urllib3", "certifi", "idna", "charset_normalizer",
	"cffi", "_cffi_backend", "pycparser",
)


def _addon_root():
	namespace = sys.modules.get(PREFIX)
	for entry in getattr(namespace, "__path__", []) or []:
		if entry.lower().endswith("package"):
			return entry
	return None


def _verdict(passed, message):
	return ("PASS: " if passed else "FAIL: ") + message


def check_namespace():
	lines = ["== namespace =="]
	namespace = sys.modules.get(PREFIX)
	lines.append(_verdict(namespace is not None, f"{PREFIX} is installed"))
	if namespace is None:
		lines.append("  (the add-on is disabled, or this build predates R03)")
		return lines, None
	roots = list(getattr(namespace, "__path__", []) or [])
	lines.append(f"  roots: {roots}")
	return lines, _addon_root()


def check_no_global_leak():
	lines = ["== category 2 must not exist as global names =="]
	for name in ISOLATED:
		module = sys.modules.get(name)
		if module is None:
			lines.append(_verdict(True, f"{name} absent from global sys.modules"))
		else:
			lines.append(_verdict(False, f"{name} LEAKED -> {getattr(module, '__file__', '?')}"))
	return lines


def check_no_host_only_under_prefix():
	"""Fact (c): _wb_vendor.__path__ includes the deps root, and
	deps/requests/__init__.py exists on disk, so _wb_vendor.requests WOULD
	resolve to our bundled copy if anything ever asked for it -- nothing does
	today, but nothing stops it either, since HOST_ONLY names are simply not
	in ISOLATED and _SandboxFinder answers for any name under the prefix.
	This proves the current session's state rather than the finder's
	theoretical behaviour: it does not call find_spec (see check_sandboxed_import
	for why that matters), it only asserts none of these names have actually
	been loaded under the prefix in sys.modules.
	"""
	lines = ["== category 3 must not appear under the prefix =="]
	for name in HOST_ONLY:
		qualified = PREFIX + "." + name
		lines.append(_verdict(qualified not in sys.modules, f"{qualified} not loaded"))
	return lines


def check_sandbox_origins(package_root):
	lines = ["== category 2 must resolve under the prefix =="]
	if package_root is None:
		lines.append("SKIPPED (no namespace root found)")
		return lines
	for name in ISOLATED:
		module = sys.modules.get(PREFIX + "." + name)
		if module is None:
			lines.append(f"INFO: {PREFIX}.{name} not loaded yet (lazy, or auth unused this session)")
			continue
		path = getattr(module, "__file__", "?") or "?"
		inside = os.path.normcase(path).startswith(os.path.normcase(package_root))
		lines.append(_verdict(inside, f"{PREFIX}.{name} -> {path}"))
	return lines


def check_sandboxed_import():
	"""Fact (b): the sandbox is fail-open by construction -- _wb_vendor's
	__path__ is a working import root the stock PathFinder serves on its own,
	so if _SandboxFinder is ever missing or displaced by another add-on (a
	real possibility in a shared NVDA process with other add-ons present,
	which is exactly where this script runs and where Task 7's Windows gate
	never does), imports keep succeeding -- just unwrapped, with the real
	__import__ and no rewriting. This mirrors the positive check
	tests/test_coseeing_auth_bundle.py adds in Task 7: every loaded
	_wb_vendor.* module with a source origin must carry a sandboxed
	__import__ in its __builtins__. __builtins__ can be a dict or a module
	depending on how the module was executed, and an extension module (no
	.py origin, e.g. cryptography's _rust.pyd) is legitimately never wrapped
	by _SandboxLoader -- both are handled below. A .py-origin module with no
	__import__ entry at all is a FAIL, not a silent pass.
	"""
	lines = ["== every loaded _wb_vendor.* module with a source origin must be sandboxed =="]
	prefix_dot = PREFIX + "."
	seen = False
	for name, module in list(sys.modules.items()):
		if not name.startswith(prefix_dot):
			continue
		spec = getattr(module, "__spec__", None)
		origin = getattr(spec, "origin", None)
		if not isinstance(origin, str) or not origin.endswith(".py"):
			# Extension modules (e.g. *.pyd) are never wrapped; legitimate, not a FAIL.
			continue
		seen = True
		module_builtins = module.__dict__.get("__builtins__")
		if isinstance(module_builtins, dict):
			sandboxed_import = module_builtins.get("__import__")
		else:
			sandboxed_import = getattr(module_builtins, "__import__", None)
		if sandboxed_import is None:
			lines.append(_verdict(False, f"{name} has no __import__ in __builtins__ (displaced finder?)"))
		else:
			lines.append(_verdict(sandboxed_import is not builtins.__import__, f"{name} carries a sandboxed __import__"))
	if not seen:
		lines.append("INFO: no _wb_vendor.* module with a .py source origin is loaded yet in this session")
	return lines


def check_host_origins(package_root):
	lines = ["== category 3 must come from NVDA, not from our bundle =="]
	for name in HOST_ONLY:
		module = sys.modules.get(name)
		if module is None:
			lines.append(f"INFO: {name} not loaded in this session")
			continue
		path = getattr(module, "__file__", "") or "(built-in)"
		if package_root is None:
			lines.append(f"INFO: {name} -> {path}")
			continue
		ours = os.path.normcase(path).startswith(os.path.normcase(package_root))
		lines.append(_verdict(not ours, f"{name} -> {path}"))
	return lines


def check_sys_path(package_root):
	lines = ["== sys.path must not carry the add-on's package directory =="]
	if package_root is None:
		lines.append("SKIPPED (no namespace root found)")
		return lines
	target = os.path.normcase(package_root)
	offenders = [entry for entry in sys.path if os.path.normcase(entry).startswith(target)]
	lines.append(_verdict(not offenders, f"sys.path entries under the bundle: {offenders}"))
	return lines


def check_stdlib_gapfill(package_root):
	lines = ["== category 1 gap-fill =="]
	module = sys.modules.get("secrets")
	if module is None:
		lines.append("INFO: secrets not loaded in this session")
		return lines
	path = getattr(module, "__file__", "?") or "?"
	lines.append(f"  secrets -> {path}")
	if package_root and os.path.normcase(path).startswith(os.path.normcase(package_root)):
		lines.append(_verdict("_stdlib_gapfill" in path, "our copy comes from _stdlib_gapfill/"))
	else:
		lines.append(_verdict(True, "the host provides secrets; our copy correctly stood down"))
	return lines


# Checks that take no argument -- they inspect sys.modules directly rather
# than needing the add-on's package root.
_NO_ARG_CHECKS = (check_no_global_leak, check_no_host_only_under_prefix, check_sandboxed_import)


def main():
	report = []
	namespace_lines, package_root = check_namespace()
	report.extend(namespace_lines)
	report.append("")
	for check in (check_no_global_leak, check_no_host_only_under_prefix, check_sandboxed_import,
	              check_sandbox_origins, check_host_origins, check_sys_path, check_stdlib_gapfill):
		try:
			if check in _NO_ARG_CHECKS:
				report.extend(check())
			else:
				report.extend(check(package_root))
		except Exception:
			report.append(f"{check.__name__} CRASHED:")
			report.append(traceback.format_exc())
		report.append("")
	text = "\n".join(report)
	failures = sum(1 for line in report if line.startswith("FAIL: "))
	text += f"\n== {failures} FAILURE(S) ==\n"
	print(text)
	destination = os.path.join(tempfile.gettempdir(), "wordbridge-r03-selfcheck.txt")
	try:
		with open(destination, "w", encoding="utf8") as handle:
			handle.write(text)
		print(f"report written to {destination}")
	except Exception as error:
		print(f"could not write report: {type(error).__name__}: {error}")


main()
