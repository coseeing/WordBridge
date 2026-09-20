"""R03 probe v3: which stdlib modules has NVDA removed that WordBridge needs?

Run inside NVDA's Python Console (NVDA+control+z) with WordBridge INSTALLED
and ENABLED:

	exec(open(r"C:\\path\\to\\2026-09-20-r03-stdlib-gap-probe.py", encoding="utf8").read())

`package/secrets.py` exists because NVDA's Python omits the stdlib `secrets`.
This probe answers whether `secrets` is the only such module, by taking every
non-third-party module WordBridge's auth stack and local correction path have
imported and checking each one against a fresh interpreter's ability to import
it without the add-on's directories on sys.path.

It writes no product files.  The report goes to stdout and to
%TEMP%\\wordbridge-r03-stdlib-gap.txt.
"""

import os
import subprocess
import sys
import tempfile
import traceback

# Anything resolving from one of these is ours or a third party, not stdlib.
VENDOR_MARKERS = ("addons", "wordbridge", "site-packages", "dist-packages")


def _is_vendor(path):
	lowered = (path or "").lower()
	return any(marker in lowered for marker in VENDOR_MARKERS)


def _candidate_stdlib_names():
	"""Top-level module names currently loaded that look like stdlib."""
	names = set()
	for name, module in list(sys.modules.items()):
		if "." in name or module is None:
			continue
		if name in sys.builtin_module_names:
			continue
		path = getattr(module, "__file__", None)
		if path is None or _is_vendor(path):
			continue
		names.add(name)
	return sorted(names)


def probe_0():
	lines = ["== PROBE 0: environment =="]
	lines.append(f"python: {sys.version}")
	lines.append(f"executable: {sys.executable}")
	lines.append(f"addon loaded: {'globalPlugins.WordBridge' in sys.modules or any(n.endswith('WordBridge') for n in sys.modules)}")
	return lines


def probe_1():
	"""Force the add-on's own import graph to be present before measuring."""
	lines = ["== PROBE 1: exercise WordBridge's import graph =="]
	targets = [
		("auth stack", "from coseeing_auth import CoseeingAuthClient"),
		("local correction", "from pypinyin import lazy_pinyin"),
		("local correction", "import chinese_converter"),
		("local correction", "from hanzidentifier import identify"),
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
	"""Ask a clean interpreter which of those names it cannot import."""
	lines = ["== PROBE 2: stdlib names NVDA cannot import on its own =="]
	names = _candidate_stdlib_names()
	lines.append(f"candidate stdlib names in play: {len(names)}")

	code = (
		"import sys\n"
		"missing = []\n"
		"for name in sys.argv[1:]:\n"
		"    try:\n"
		"        __import__(name)\n"
		"    except Exception as error:\n"
		"        missing.append(f'{name}: {type(error).__name__}')\n"
		"print('\\n'.join(missing))\n"
	)
	try:
		result = subprocess.run(
			[sys.executable, "-I", "-S", "-c", code, *names],
			capture_output=True,
			text=True,
			timeout=120,
		)
	except Exception as error:
		lines.append(f"PROBE2 FAILED to run isolated interpreter: {type(error).__name__}: {error}")
		lines.append(traceback.format_exc())
		return lines

	missing = [line for line in result.stdout.splitlines() if line.strip()]
	lines.append("")
	lines.append(f"-- CATEGORY 1 LIST: stdlib names this interpreter cannot import ({len(missing)}) --")
	if missing:
		lines.extend(f"  {entry}" for entry in missing)
		lines.append("  ^ every name here needs a copy in package/_stdlib_gapfill/")
	else:
		lines.append("  NONE")
		lines.append("  ^ if this contradicts package/secrets.py existing, the -I -S isolation")
		lines.append("    is not reproducing NVDA's trimmed environment; report that rather")
		lines.append("    than concluding the gap-fill is unnecessary.")
	if result.stderr.strip():
		lines.append("")
		lines.append(f"isolated interpreter stderr: {result.stderr.strip()[:500]}")
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
