"""R03 probe v3: which stdlib modules has NVDA removed that WordBridge needs?

Run inside NVDA's Python Console (NVDA+control+z) with WordBridge INSTALLED
and ENABLED:

	exec(open(r"C:\\path\\to\\2026-09-20-r03-stdlib-gap-probe.py", encoding="utf8").read())

`package/secrets.py` exists because NVDA's Python omits the stdlib `secrets`.
This probe answers whether `secrets` is the only such module.

NVDA is a py2exe frozen program: there is no python.exe in its install
directory, `sys.executable` is nvda.exe, and nvda.exe's own argparse rejects
`-I`/`-S`/`-c` (`-c` collides with NVDA's `--config-path`). A subprocess
cannot measure this environment. Even a same-version standalone python.exe
would not help: `-I -S` strips env/site/cwd paths, not py2exe's per-module
trimming, so it would report NONE regardless of what NVDA actually removed.

This probe therefore measures in-process, off disk, with no subprocess:

  1. Exercise WordBridge's import graph, including call-time imports, so
     every stdlib name it touches -- dotted submodules included -- lands in
     sys.modules, whether NVDA provides it or the add-on is shimming it.
  2. Keep every sys.modules name whose root package is in
     sys.stdlib_module_names, has its own __file__ (frozen/builtin names
     come from the interpreter itself, never library.zip), and is not an
     alias of another sys.modules entry (os.path is ntpath/posixpath under
     another name; that real name is checked on its own). A name currently
     resolving from the add-on's own directories is labelled shimmed-by-addon
     and kept as a PRIME candidate for category 1, never excluded -- that is
     where the one known member, `secrets`, lives today.
  3. Read what NVDA's frozen runtime actually provides from disk: the
     namelist of its library.zip, the loose .py/.pyd/.dll files in its
     program directory, and sys.builtin_module_names.
  4. Diff (2) against (3). Needed and not provided is category 1.

It writes no product files.  The report goes to stdout and to
%TEMP%\\wordbridge-r03-stdlib-gap.txt.
"""

import os
import sys
import tempfile
import traceback
import zipfile

# A path containing one of these is ours or a third party, not NVDA's own tree.
VENDOR_MARKERS = ("addons", "wordbridge", "site-packages", "dist-packages")


def _is_vendor(path):
	lowered = (path or "").lower()
	return any(marker in lowered for marker in VENDOR_MARKERS)


def _root_name(name):
	return name.split(".", 1)[0]


def _is_alias(module, name):
	"""True if `name` is not this module's own canonical identity -- it is a second
	sys.modules key pointing at a module that answers to a different name and is
	checked separately under that name. Two independent CPython identity signals
	are consulted because neither is authoritative on its own: sys.modules["os.path"]
	disagrees with `module.__name__` (which is "ntpath"/"posixpath") but agrees with
	`module.__spec__.name`; some frozen bootstrap modules do the reverse (agree on
	__name__, disagree on __spec__.name). Either disagreeing is enough to call it an
	alias, so both cases are caught the same way.
	"""
	if getattr(module, "__name__", name) != name:
		return True
	spec = getattr(module, "__spec__", None)
	if spec is not None and getattr(spec, "name", name) != name:
		return True
	return False


def _needed_stdlib_names():
	"""Every sys.modules name (dotted submodules included) whose root package is
	stdlib, has its own __file__, and is not an alias of another sys.modules entry;
	a name resolving from the add-on's own directories is flagged, not excluded.
	"""
	stdlib_roots = set(sys.stdlib_module_names)
	needed = {}
	for name, module in list(sys.modules.items()):
		if module is None:
			continue
		if _root_name(name) not in stdlib_roots:
			continue
		path = getattr(module, "__file__", None)
		if path is None:
			continue
		if _is_alias(module, name):
			continue
		needed[name] = _is_vendor(path)
	return needed


def _zip_entry_to_module_name(entry):
	"""Zip entry path to dotted module name; '__init__' entries collapse to their package.
	Accepts .pyd too -- today's py2exe layout keeps extension modules beside the zip, not
	in it, but a future layout using zipextimporter-style bundling would put them inside.
	"""
	entry = entry.replace("\\", "/")
	if entry.endswith("/"):
		return None
	root, ext = os.path.splitext(entry)
	if ext.lower() not in (".py", ".pyc", ".pyo", ".pyd"):
		return None
	parts = [part for part in root.split("/") if part]
	if not parts:
		return None
	if parts[-1] == "__init__":
		parts = parts[:-1]
	if not parts:
		return None
	return ".".join(parts)


def _library_zip_path():
	"""Locate NVDA's library.zip from a loaded module's __file__, falling back to beside
	sys.executable. Walks path components with os.path rather than slicing by an index
	found on a case-folded copy of the path -- str.lower() is not length-preserving for
	some non-ASCII characters, so a profile path containing one could garble that slice.
	"""
	for _name, module in list(sys.modules.items()):
		path = getattr(module, "__file__", None)
		if not path:
			continue
		head = path
		while True:
			head, tail = os.path.split(head)
			if not tail:
				break
			if tail.lower() == "library.zip":
				return os.path.join(head, tail)
	candidate = os.path.join(os.path.dirname(sys.executable), "library.zip")
	if os.path.isfile(candidate):
		return candidate
	return None


def _provided_names(library_zip_path):
	"""Names NVDA's frozen runtime actually provides: the zip, the program directory, and builtins."""
	provided = set(sys.builtin_module_names)
	with zipfile.ZipFile(library_zip_path) as archive:
		for entry in archive.namelist():
			module_name = _zip_entry_to_module_name(entry)
			if module_name:
				provided.add(module_name)
	program_dir = os.path.dirname(library_zip_path)
	try:
		for entry in os.listdir(program_dir):
			if entry.lower().endswith((".py", ".pyd", ".dll")):
				provided.add(os.path.splitext(entry)[0])
	except OSError:
		pass
	return provided


def _missing_names(needed, provided):
	"""needed minus provided, sorted -- the category 1 list."""
	return sorted(name for name in needed if name not in provided)


def probe_0():
	lines = ["== PROBE 0: environment =="]
	lines.append(f"python: {sys.version}")
	lines.append(f"executable: {sys.executable}")
	lines.append(f"addon loaded: {'globalPlugins.WordBridge' in sys.modules or any(n.endswith('WordBridge') for n in sys.modules)}")
	return lines


def probe_1():
	"""Force the add-on's import graph -- including call-time imports -- to be present before measuring."""
	lines = ["== PROBE 1: exercise WordBridge's import graph =="]
	targets = [
		("auth stack (import)", "from coseeing_auth import CoseeingAuthClient"),
		(
			"auth stack (call-time)",
			"from coseeing_auth import AuthConfig; AuthConfig("
			"issuer='https://sso.coseeing.org', client_id='wordbridge', "
			"scopes=('openid', 'profile', 'email', 'offline_access'), "
			"login_redirect_uri='http://127.0.0.1:8000/auth-callback', "
			"logout_redirect_uri='http://127.0.0.1:8000/logout-callback', "
			"callback_timeout=180)",
		),
		("local correction", "from pypinyin import lazy_pinyin"),
		("local correction (call-time)", "from pypinyin import lazy_pinyin; lazy_pinyin('測試')"),
		("local correction", "import chinese_converter"),
		("local correction", "from hanzidentifier import identify"),
		("local correction (call-time)", "from hanzidentifier import identify; identify('測試')"),
		("local correction (zhon, call-time)", "from zhon import cedict; cedict.all"),
	]
	for label, statement in targets:
		try:
			exec(statement, {})
		except Exception as error:
			lines.append(f"{label}: {statement!r} -> {type(error).__name__}: {error}")
		else:
			lines.append(f"{label}: {statement!r} -> OK")
	return lines


def probe_2():
	"""Diff WordBridge's needed stdlib names against what NVDA's frozen runtime provides on disk."""
	lines = ["== PROBE 2: stdlib names NVDA's frozen runtime does not provide =="]
	needed = _needed_stdlib_names()
	lines.append(f"needed stdlib names in play (dotted submodules included): {len(needed)}")

	zip_path = _library_zip_path()
	if zip_path is None:
		lines.append("")
		lines.append("PROBE2 FAILED: could not locate NVDA's library.zip.")
		lines.append("  tried: the __file__ of every loaded module for a 'library.zip' path segment,")
		lines.append(f"  and {os.path.join(os.path.dirname(sys.executable), 'library.zip')!r} beside sys.executable.")
		lines.append("  Cannot measure what NVDA provides -- no category 1 list follows.")
		return lines

	lines.append(f"library.zip: {zip_path}")
	try:
		provided = _provided_names(zip_path)
	except Exception as error:
		lines.append(f"PROBE2 FAILED to read library.zip: {type(error).__name__}: {error}")
		lines.append(traceback.format_exc())
		return lines

	lines.append(f"names NVDA's runtime provides (zip + program dir + builtins): {len(provided)}")

	sentinel_names = ("os", "json")
	unseen_sentinels = [sentinel for sentinel in sentinel_names if sentinel not in provided]
	if unseen_sentinels:
		lines.append("")
		lines.append(f"PROBE2 FAILED: {zip_path!r} does not look like NVDA's stdlib-bearing library.zip.")
		lines.append(f"  expected at least {sentinel_names} to be present; missing: {unseen_sentinels}.")
		lines.append("  Cannot measure what NVDA provides -- no category 1 list follows.")
		return lines

	missing = _missing_names(needed, provided)
	lines.append("")
	lines.append(f"-- CATEGORY 1 LIST: needed stdlib names NVDA's runtime does not provide ({len(missing)}) --")
	if missing:
		for name in missing:
			tag = "shimmed-by-addon" if needed[name] else "NOT YET SHIMMED"
			lines.append(f"  {name}  [{tag}]")
		lines.append("  ^ every name here needs a copy in package/_stdlib_gapfill/, if not already there")
		if "secrets" not in missing:
			lines.append("  ^ SANITY CHECK: 'secrets' is not in this list, and that is also wrong -- it is")
			lines.append("    already known to be missing (package/secrets.py exists to fill that gap).")
			lines.append("    Either the probe located the wrong library.zip, or probe 1 above did not")
			lines.append("    actually import 'secrets' into sys.modules before this probe ran.")
	else:
		lines.append("  NONE")
		lines.append("  ^ SANITY CHECK: 'secrets' is already known to be missing (package/secrets.py")
		lines.append("    exists to fill that gap). If 'secrets' is not in the list above, this result")
		lines.append("    is wrong. Check, in order:")
		lines.append("    1. the probe could not locate the correct library.zip -- re-check the")
		lines.append("       'library.zip:' line above; a wrong fallback guess can still open as a")
		lines.append("       valid, mostly-empty zip instead of failing outright.")
		lines.append("    2. probe 1 above did not actually import 'secrets' into sys.modules before")
		lines.append("       this probe ran (check probe 1's lines for an OK against the auth stack).")
		lines.append("    3. NVDA's library.zip or program directory genuinely contains a 'secrets'")
		lines.append("       entry on this build, meaning fact 9 is stale for this NVDA version.")
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
	destination = os.path.join(tempfile.gettempdir(), "wordbridge-r03-stdlib-gap.txt")
	try:
		with open(destination, "w", encoding="utf8") as handle:
			handle.write(text)
		print(f"report written to {destination}")
	except Exception as error:
		print(f"could not write report: {type(error).__name__}: {error}")


main()
