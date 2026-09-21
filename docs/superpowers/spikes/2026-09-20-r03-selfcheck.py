"""R03 self-check: prove WordBridge is not polluting NVDA's import state.

Run inside NVDA's Python Console (NVDA+control+z) with WordBridge INSTALLED
and ENABLED, ideally alongside other add-ons:

	exec(open(r"C:\\path\\to\\2026-09-20-r03-selfcheck.py", encoding="utf8").read())

Every line below is one of PASS, FAIL, INFO, SKIPPED, or "<check> CRASHED:".
Only PASS and FAIL are verdicts. INFO means the check had nothing to judge
yet in this session (e.g. a module not loaded); SKIPPED and CRASHED mean the
check did not run at all. A report with zero FAIL lines is NOT proof of
health by itself -- a check that never ran also prints zero FAIL lines.
Read past the footer for INFO/SKIPPED/CRASHED on the checks everything else
depends on, especially "== namespace ==" and "== _SandboxFinder must be
present ==". Report to %TEMP%\\wordbridge-r03-selfcheck.txt.

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
import datetime
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


def _is_under(path, root):
	"""True if `path` is `root` itself or something inside it, with a
	separator boundary so a sibling directory sharing a prefix -- e.g.
	...\\package2 next to ...\\package -- is never mistaken for being inside.
	A bare normcase().startswith() has no such boundary.
	"""
	target = os.path.normcase(os.path.normpath(str(root)))
	candidate = os.path.normcase(os.path.normpath(str(path)))
	return candidate == target or candidate.startswith(target + os.sep)


def _addon_root():
	namespace = sys.modules.get(PREFIX)
	for entry in getattr(namespace, "__path__", []) or []:
		if isinstance(entry, str) and entry.lower().endswith("package"):
			return entry
	return None


def _addon_version(package_root):
	"""Best-effort only. NVDA installs a manifest.ini one level above
	package/ with a `version = ...` line; this source tree does not carry
	one (it is generated at packaging time), so "unknown" here is expected
	when exercised outside a real NVDA install, not a bug in this script.

	Catches Exception, not just OSError: review round 2 found a non-UTF-8
	manifest.ini raises UnicodeDecodeError (a ValueError, not an OSError),
	which escaped uncaught and killed the whole run -- zero output, zero
	report file -- from what is meant to be a purely cosmetic version
	stamp. Nothing this function does should ever be able to take the rest
	of the script down with it.
	"""
	if not package_root:
		return "unknown"
	manifest_path = os.path.join(os.path.dirname(str(package_root)), "manifest.ini")
	try:
		with open(manifest_path, encoding="utf8") as handle:
			for line in handle:
				if line.strip().lower().startswith("version"):
					return line.split("=", 1)[-1].strip().strip('"')
	except Exception:
		pass
	return "unknown"


def _verdict(passed, message):
	return ("PASS: " if passed else "FAIL: ") + message


def check_namespace():
	lines = ["== namespace =="]
	namespace = sys.modules.get(PREFIX)
	installed = namespace is not None
	lines.append(_verdict(installed, f"{PREFIX} is installed" if installed else f"{PREFIX} is NOT installed"))
	if namespace is None:
		lines.append("  (the add-on is disabled, or this build predates R03)")
		return lines, None
	roots = list(getattr(namespace, "__path__", []) or [])
	lines.append(f"  roots: {roots}")
	root = _addon_root()
	# A miss here silently disabled three downstream checks in an earlier
	# version of this script (review round 1). The "package" basename
	# heuristic is correct today (__init__.py fixes it, vendor.py's
	# default_roots() appends only the py3xx-win_amd64 runtime root beside
	# it), but "correct today" must fail loudly the day it stops being true,
	# not silently downgrade every dependent check to SKIPPED/INFO.
	if root is not None:
		lines.append(_verdict(True, f"a package root was identified: {root}"))
	else:
		lines.append(_verdict(False, "no package root could be identified"))
	return lines, root


def check_meta_path(package_root):
	"""_SandboxFinder must actually be installed on sys.meta_path.  This is
	the single most direct signal of the fail-open failure mode fact (b)
	describes: if this finder is missing or displaced, every other check in
	this script can still read as entirely PASS/INFO, because unwrapped
	imports keep succeeding. Unlike check_sandboxed_import, this does not
	depend on any _wb_vendor.* module having loaded yet in this session, so
	it closes that check's "nothing loaded yet" blind spot.

	This only tests the predicate vendor.py itself uses to decide whether
	an install is needed (`getattr(finder, "prefix", None) == PREFIX`), so
	it proves no more than that predicate does: a foreign object that
	merely exposes a matching `.prefix` attribute reads as PASS here too,
	and would equally cause our own install() to stand down. The matched
	finder's own class name is reported precisely so that case is visible
	rather than silently assumed to be _SandboxFinder. Every match is
	scanned, not just the first: a second finder advertising the same
	prefix was never seen before because a `break` here stopped looking.
	"""
	lines = ["== _SandboxFinder must be present on sys.meta_path =="]
	matches = [
		(position, finder) for position, finder in enumerate(sys.meta_path)
		if getattr(finder, "prefix", None) == PREFIX
	]
	if not matches:
		lines.append(_verdict(False, f"no finder on sys.meta_path advertises prefix={PREFIX!r}"))
		return lines
	index, finder = matches[0]
	ahead = [type(f).__name__ for f in sys.meta_path[:index]]
	lines.append(_verdict(True, f"{type(finder).__name__} present at sys.meta_path[{index}]; ahead of it: {ahead}"))
	if len(matches) > 1:
		extras = [(pos, type(f).__name__) for pos, f in matches[1:]]
		lines.append(_verdict(False, f"more than one finder advertises prefix={PREFIX!r}: {extras}"))
	return lines


def check_no_global_leak(package_root):
	lines = ["== category 2 must not exist as global names =="]
	for name in ISOLATED:
		module = sys.modules.get(name)
		if module is None:
			lines.append(_verdict(True, f"{name} absent from global sys.modules"))
		else:
			lines.append(_verdict(False, f"{name} LEAKED -> {getattr(module, '__file__', '?')}"))
	return lines


def check_no_host_only_under_prefix(package_root):
	"""Fact (c): _wb_vendor.__path__ includes the deps root, and
	deps/requests/__init__.py exists on disk, so a HOST_ONLY name WOULD
	resolve to our bundled copy if anything ever asked for it under the
	prefix -- nothing does today, but nothing stops it either, since
	HOST_ONLY names are simply not in ISOLATED and _SandboxFinder answers
	for any name under the prefix. This proves the current session's state
	rather than the finder's theoretical behaviour: it does not call
	find_spec (see check_sandboxed_import's docstring for why that matters),
	it only asserts none of these names have actually resolved under the
	prefix in sys.modules.

	vendor.py names the *dotted* form as the real hazard --
	_wb_vendor._coseeing_auth_deps.requests, not just _wb_vendor.requests --
	so every loaded name under the prefix is checked by its LAST dotted
	component, not just the direct one-level form.

	A legitimate category 2 package can itself ship a submodule whose own
	name collides with a HOST_ONLY name: authlib bundles
	authlib/oauth2/rfc6749/requests.py, imported unconditionally by
	authlib/oauth2/rfc6749/__init__.py, so using authlib at all loads
	_wb_vendor.authlib.oauth2.rfc6749.requests -- a real, intended part of
	authlib, not a bundled HOST_ONLY copy. Review round 2 verified this
	end-to-end against the real bundle and found the naive last-component
	scan flagged it as a false FAIL on every healthy run that uses auth.
	The discriminator is the SECOND dotted component (the top-level name
	directly under the prefix): _wb_vendor.authlib.oauth2.rfc6749.requests
	has second component "authlib", a category 2 name, so it is a
	submodule of a package that belongs under the prefix and is exempt.
	_wb_vendor._coseeing_auth_deps.requests has second component
	"_coseeing_auth_deps" -- not a category 2 name -- so it is flagged.
	_wb_vendor.requests has second component "requests" itself -- also not
	a category 2 name -- so it is flagged too. ISOLATED and HOST_ONLY are
	disjoint, so this discriminator can never accidentally exempt a direct
	_wb_vendor.<host-only-name> hit.
	"""
	lines = ["== category 3 must not appear under the prefix, in any dotted form =="]
	prefix_dot = PREFIX + "."
	loaded_under_prefix = {
		name: module for name, module in list(sys.modules.items())
		if name.startswith(prefix_dot)
	}
	for name in HOST_ONLY:
		hits = []
		for qualified, module in loaded_under_prefix.items():
			if qualified.rsplit(".", 1)[-1] != name:
				continue
			# qualified always starts with prefix_dot, so parts[0] == PREFIX
			# and parts[1] (the top-level name directly under the prefix)
			# always exists.
			parts = qualified.split(".")
			if parts[1] in ISOLATED:
				continue  # a legitimate submodule of a category 2 package
			hits.append((qualified, module))
		if not hits:
			lines.append(_verdict(True, f"no ...{name} form loaded under {PREFIX} outside a category 2 package"))
			continue
		for qualified, module in hits:
			lines.append(_verdict(False, f"{qualified} IS LOADED -> {getattr(module, '__file__', '?')}"))
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
		inside = _is_under(path, package_root)
		lines.append(_verdict(inside, f"{PREFIX}.{name} -> {path}"))
	return lines


def check_sandboxed_import(package_root):
	"""Fact (b): the sandbox is fail-open by construction -- _wb_vendor's
	__path__ is a working import root the stock PathFinder serves on its own,
	so if _SandboxFinder is ever missing or displaced by another add-on (a
	real possibility in a shared NVDA process with other add-ons present,
	which is exactly where this script runs and where Task 7's Windows gate
	never does), imports keep succeeding -- just unwrapped, with the real
	__import__ and no rewriting. This mirrors the positive check
	tests/test_coseeing_auth_bundle.py adds in Task 7: every loaded
	_wb_vendor.* module with a checkable (non-extension) origin must carry
	a sandboxed __import__ in its __builtins__. __builtins__ can be a dict
	or a module depending on how the module was executed, and a real
	extension module (*.pyd, e.g. cryptography's _rust) is legitimately
	never wrapped by _SandboxLoader -- both are handled below. A checkable
	module with no __import__ entry at all is a FAIL, not a silent pass -- and so is a
	prefixed module with no source __spec__.origin at all: with
	_SandboxFinder installed that state is impossible (vendor.py's find_spec
	raises ModuleNotFoundError rather than returning a namespace portion's
	loader-less spec), so seeing it here means some OTHER finder resolved
	this name, which is exactly the displacement this check exists to catch.

	The exemption below is narrowed to actual extension-module suffixes
	(*.pyd/*.so/*.dll) rather than "anything not ending in .py". Review
	round 2 found the wider form also exempted a *.pyc-origin module (a
	SourcelessFileLoader), but vendor.py:156 wraps everything except an
	ExtensionFileLoader -- a sourceless bytecode-only module IS wrapped by
	_SandboxLoader in the real product and must be checked here too, not
	waved through as "no .py source origin yet".
	"""
	EXTENSION_SUFFIXES = (".pyd", ".so", ".dll")
	lines = ["== every loaded _wb_vendor.* module with a source origin must be sandboxed =="]
	prefix_dot = PREFIX + "."
	seen = False
	for name, module in list(sys.modules.items()):
		if not name.startswith(prefix_dot):
			continue
		spec = getattr(module, "__spec__", None)
		origin = getattr(spec, "origin", None)
		if isinstance(origin, str) and origin.lower().endswith(EXTENSION_SUFFIXES):
			# A real extension module (e.g. *.pyd): never wrapped by
			# _SandboxLoader, so there is no __import__ rewrite to check.
			# Legitimate, not a FAIL.
			continue
		seen = True
		if not isinstance(origin, str):
			lines.append(_verdict(False, f"{name} has no source __spec__.origin (displaced finder?)"))
			continue
		module_builtins = module.__dict__.get("__builtins__")
		if isinstance(module_builtins, dict):
			sandboxed_import = module_builtins.get("__import__")
		else:
			sandboxed_import = getattr(module_builtins, "__import__", None)
		if sandboxed_import is None:
			lines.append(_verdict(False, f"{name} has no __import__ in __builtins__ (displaced finder?)"))
		elif sandboxed_import is not builtins.__import__:
			lines.append(_verdict(True, f"{name} carries a sandboxed __import__"))
		else:
			lines.append(_verdict(False, f"{name} carries the REAL __import__, not a sandboxed one (displaced finder?)"))
	if not seen:
		lines.append("INFO: no checkable (non-extension) _wb_vendor.* module is loaded yet in this session")
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
		ours = _is_under(path, package_root)
		lines.append(_verdict(not ours, f"{name} -> {path}"))
	return lines


def check_sys_path(package_root):
	lines = ["== sys.path must not carry the add-on's package directory =="]
	if package_root is None:
		lines.append("SKIPPED (no namespace root found)")
		return lines
	offenders = [entry for entry in sys.path if _is_under(entry, package_root)]
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
	if package_root is None:
		# Cannot judge origin against a root that was never identified --
		# review round 1 found this branch previously fell through to an
		# affirmative "the host provides secrets" PASS, which is false when
		# the root is simply unknown rather than genuinely not ours.
		lines.append(f"INFO: cannot judge (no package root); secrets -> {path}")
	elif _is_under(path, package_root):
		if "_stdlib_gapfill" in path:
			lines.append(_verdict(True, "our copy comes from _stdlib_gapfill/"))
		else:
			lines.append(_verdict(False, f"our copy does NOT come from _stdlib_gapfill/ -> {path}"))
	else:
		lines.append(_verdict(True, "the host provides secrets; our copy correctly stood down"))
	return lines


_CHECKS = (
	check_meta_path,
	check_no_global_leak,
	check_no_host_only_under_prefix,
	check_sandbox_origins,
	check_sandboxed_import,
	check_host_origins,
	check_sys_path,
	check_stdlib_gapfill,
)


def main():
	report = []
	try:
		namespace_lines, package_root = check_namespace()
	except Exception:
		namespace_lines = ["== namespace ==", "check_namespace CRASHED:", traceback.format_exc()]
		package_root = None
	report.append(f"WordBridge R03 self-check -- {datetime.datetime.now().isoformat(timespec='seconds')}")
	report.append(f"python: {sys.version}")
	report.append(f"executable: {sys.executable}")
	report.append(f"add-on version: {_addon_version(package_root)}")
	report.append("")
	report.extend(namespace_lines)
	report.append("")
	for check in _CHECKS:
		try:
			report.extend(check(package_root))
		except Exception:
			report.append(f"{check.__name__} CRASHED:")
			report.append(traceback.format_exc())
		report.append("")
	text = "\n".join(report)
	failures = sum(1 for line in report if line.startswith("FAIL: "))
	crashes = sum(1 for line in report if line.endswith(" CRASHED:"))
	text += f"\n== {failures} FAILURE(S), {crashes} CRASHED ==\n"
	print(text)
	destination = os.path.join(tempfile.gettempdir(), "wordbridge-r03-selfcheck.txt")
	try:
		with open(destination, "w", encoding="utf8") as handle:
			handle.write(text)
		print(f"report written to {destination}")
	except Exception as error:
		print(f"could not write report: {type(error).__name__}: {error}")


main()
