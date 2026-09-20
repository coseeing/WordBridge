# R03 import isolation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop WordBridge from mutating import state that the whole NVDA process shares, by loading its vendored dependencies under a private `_wb_vendor` prefix instead of injecting `sys.path` and deleting the host's `cryptography.*` modules.

**Architecture:** One private namespace module `_wb_vendor` whose `__path__` holds the bundle roots, so the stock `PathFinder` does all file location. One `MetaPathFinder` that answers only for names starting with `_wb_vendor.` and wraps the returned loader to inject a custom `__import__` into each sandboxed module's `__builtins__`. That injected `__import__` rewrites the nine isolated top-level names to their prefixed form and delegates everything else to the host. Because the interception lives in each module's own globals, it also covers the lazy imports cryptography performs at call time.

**Tech Stack:** Python 3.13 (NVDA 2026.1 runtime), `importlib.machinery.PathFinder`, `importlib.abc.MetaPathFinder`/`Loader`, pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-r03-import-isolation-design.md` (Traditional Chinese translation alongside it as `..._ZH-TW.md`). Read the spec before Task 2 — the plan argues from it.

## Global Constraints

- Branch: `r03-import-isolation`. It already carries the spec and probe v2.
- Indentation is **tabs**, in product code and tests alike. Match surrounding files.
- Private prefix is exactly `_wb_vendor`.
- **Category 1** (stdlib modules NVDA removed): `secrets` is the only member known today; the complete list is Task 1's deliverable. Registered under **canonical** names, globally, and **only when the host lacks them**.
- **Category 2** (must come from us, prefix-only, exactly nine): `cryptography`, `authlib`, `joserfc`, `jwt`, `coseeing_auth`, `pypinyin`, `zhon`, `hanzidentifier`, `chinese_converter`.
- **Category 3** (must come from the host, exactly eight): `requests`, `urllib3`, `certifi`, `idna`, `charset_normalizer`, `cffi`, `_cffi_backend`, `pycparser`. **No fallback to the bundled copies.** A missing category 3 package is a loud failure naming the host environment.
- `addon/globalPlugins/WordBridge/package/coseeing_auth/` source is **not modified**. It is shared with other Coseeing projects.
- The auth half being unavailable must never prevent the add-on from loading or break local correction.
- The sandbox installs once and is never uninstalled. `terminate()` does not tear it down.
- Do not change *when* the auth stack loads — only *how* it resolves. Lazy loading is R16.
- Do not trim the bundle. That is R15.
- Regression gate is the **non-network** suite:
  `python3 -m pytest tests/ -q --ignore=tests/test_integration_deepseek.py --ignore=tests/test_integration_google.py --ignore=tests/test_integration_anthropic.py --ignore=tests/test_integration_openai_response.py`
  Baseline before any task: **2 failed, 190 passed, 1 skipped**. The two failures are pre-existing and unrelated: `tests/test_coseeing_auth_bundle.py::test_sso_configuration_matches_approved_demo` and `tests/test_provider_naming.py::test_provider_config_filenames_match_catalog`. Do not treat them as regressions and do not fix them here.
- The four `tests/test_integration_*.py` files hit live paid APIs and drift run to run. Never use the full-suite number as evidence.

## File Structure

| File | Responsibility |
| --- | --- |
| `addon/globalPlugins/WordBridge/lib/vendor.py` | **New.** The whole sandbox: category lists, the `__import__` shim, the finder/loader pair, runtime-root derivation, `install()`, and the conditional stdlib gap-fill. Single module because these parts are meaningless apart and are always installed together. |
| `addon/globalPlugins/WordBridge/package/_stdlib_gapfill/secrets.py` | **Moved** from `package/secrets.py`. Category 1 sources, physically separated from category 2. |
| `addon/globalPlugins/WordBridge/__init__.py` | Installs the sandbox as its first action; loses `sys.path.insert`; imports `hanzidentifier` through the prefix. |
| `addon/globalPlugins/WordBridge/lib/coseeing_auth.py` | Loses `_prepare_auth_dependencies()` and the `del sys.modules` loop; gains `AUTH_AVAILABLE`, placeholder error classes, and unavailable-state entry points. |
| `addon/globalPlugins/WordBridge/lib/tasks/typo/prompt.py`, `.../utils.py`, `.../text_policy.py`, `addon/globalPlugins/WordBridge/lib/text/chinese.py` | Six import statements rerouted through the prefix. |
| `tests/test_vendor_sandbox.py` | **New.** Everything provable on Linux: shim semantics, namespace composition, idempotence, category-list integrity, gap-fill conditionality, no-pollution snapshot. |
| `tests/conftest.py` | Installs the sandbox for tests that import add-on modules directly. |
| `tests/test_coseeing_auth_bundle.py` | Windows gate rewritten to the sandbox contract; `_coseeing_auth_import_dependencies` stubs `_wb_vendor.*`. |
| `docs/superpowers/spikes/2026-09-20-r03-stdlib-gap-probe.py` | **New.** Task 1's probe. |
| `docs/superpowers/spikes/2026-09-20-r03-selfcheck.py` | **New.** Task 8's post-install self-check. |
| `addon/globalPlugins/WordBridge/package/coseeing-auth-dependencies.md` | Documents the three categories. |

## Task Dependency Order

Task 1 is independent and can run at any time. Otherwise: 2 → 3 → 4 → (5, 6) → 7 → 8.

---

### Task 1: R03 probe v3 — enumerate the stdlib gap

**Files:**
- Create: `docs/superpowers/spikes/2026-09-20-r03-stdlib-gap-probe.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a report the maintainer pastes back. No product code, no test.

**Why this does not block the rest.** The gap-fill mechanism built in Task 4 is **data-driven**: it registers whatever modules exist in `package/_stdlib_gapfill/`. The probe's output therefore determines which *files* belong in that directory, not which *code* gets written. Implementation proceeds; shipping does not, until the directory's contents match the probe.

- [ ] **Step 1: Write the probe script**

Create `docs/superpowers/spikes/2026-09-20-r03-stdlib-gap-probe.py`:

```python
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
```

- [ ] **Step 2: Verify the script parses**

Run: `python3 -m py_compile docs/superpowers/spikes/2026-09-20-r03-stdlib-gap-probe.py`
Expected: exit 0, no output. This is the only check possible off Windows.

- [ ] **Step 3: Commit**

```bash
git add -f docs/superpowers/spikes/2026-09-20-r03-stdlib-gap-probe.py
git commit -m "spike: add R03 probe for NVDA's removed stdlib modules"
```

Note: `docs/` is in `.gitignore`; every spec, plan and spike in this repo is force-added. `-f` is required and correct.

- [ ] **Step 4: Hand the probe to the maintainer**

Ask them to run it in NVDA's Python Console and paste back `%TEMP%\wordbridge-r03-stdlib-gap.txt`. Record the resulting category 1 list in the task report. If it names modules beyond `secrets`, those copies must be added to `package/_stdlib_gapfill/` before release — flag that explicitly; Task 4 builds the mechanism but ships only `secrets`.

---

### Task 2: The `__import__` shim

**Files:**
- Create: `addon/globalPlugins/WordBridge/lib/vendor.py`
- Test: `tests/test_vendor_sandbox.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_make_sandbox_import(prefix: str, isolated: frozenset[str], real_import: Callable) -> Callable`. Task 3 passes it `builtins.__import__` and hands the result to the loader.

This is the one piece of the design that can fail in a way that surfaces far from its cause: get the return value wrong and `cryptography` gets bound to the `_wb_vendor` namespace object. It is pure Python with no NVDA dependency, so it is written test-first and proven on Linux.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vendor_sandbox.py`:

```python
import sys
import types

import pytest

from lib.vendor import _make_sandbox_import


ISOLATED = frozenset({"alpha", "beta"})


@pytest.fixture
def recording_import(monkeypatch):
	"""A stand-in for builtins.__import__ that records calls and publishes modules."""
	calls = []

	def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
		calls.append((name, tuple(fromlist or ()), level))
		parts = name.split(".")
		for index in range(len(parts)):
			partial = ".".join(parts[: index + 1])
			if partial not in sys.modules:
				monkeypatch.setitem(sys.modules, partial, types.ModuleType(partial))
		return sys.modules[parts[0]]

	fake_import.calls = calls
	return fake_import


def test_plain_import_returns_the_prefixed_top_level_module(recording_import):
	sandbox_import = _make_sandbox_import("_wb_test", ISOLATED, recording_import)

	result = sandbox_import("alpha.child")

	assert recording_import.calls == [("_wb_test.alpha.child", (), 0)]
	assert result is sys.modules["_wb_test.alpha"]


def test_from_import_returns_the_prefixed_submodule(recording_import):
	sandbox_import = _make_sandbox_import("_wb_test", ISOLATED, recording_import)

	result = sandbox_import("alpha.child", fromlist=("thing",))

	assert recording_import.calls == [("_wb_test.alpha.child", ("thing",), 0)]
	assert result is sys.modules["_wb_test.alpha.child"]


def test_relative_import_is_delegated_untouched(recording_import):
	sandbox_import = _make_sandbox_import("_wb_test", ISOLATED, recording_import)

	sandbox_import("child", fromlist=("thing",), level=2)

	assert recording_import.calls == [("child", ("thing",), 2)]


def test_host_name_is_delegated_untouched(recording_import):
	sandbox_import = _make_sandbox_import("_wb_test", ISOLATED, recording_import)

	sandbox_import("requests.adapters")

	assert recording_import.calls == [("requests.adapters", (), 0)]


def test_bare_isolated_name_is_prefixed(recording_import):
	sandbox_import = _make_sandbox_import("_wb_test", ISOLATED, recording_import)

	result = sandbox_import("beta")

	assert recording_import.calls == [("_wb_test.beta", (), 0)]
	assert result is sys.modules["_wb_test.beta"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_vendor_sandbox.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'lib.vendor'`. `tests/conftest.py` already puts `addon/globalPlugins/WordBridge` on `sys.path`, which is why `lib.vendor` is the import path.

- [ ] **Step 3: Write the shim**

Create `addon/globalPlugins/WordBridge/lib/vendor.py`:

```python
"""Private-prefix import sandbox for WordBridge's vendored dependencies.

NVDA runs every add-on in one CPython process.  Loading our dependencies by
inserting a directory on ``sys.path`` -- or by deleting the host's modules from
``sys.modules`` so ours win -- changes what every other add-on imports.  This
module loads them under a ``_wb_vendor`` prefix instead, so nothing the host or
another add-on imports is affected.

See docs/superpowers/specs/2026-09-20-r03-import-isolation-design.md.
"""

import sys


def _make_sandbox_import(prefix, isolated, real_import):
	"""Build the ``__import__`` that sandboxed modules see.

	Top-level names in ``isolated`` are rewritten to ``<prefix>.<name>``;
	everything else is delegated unchanged so the host answers.

	The return value matters as much as the rewrite.  ``import a.b`` must
	return ``a`` while ``from a.b import c`` must return ``a.b``, and after
	prefixing the real ``__import__`` would return the prefix namespace and
	``<prefix>.a.b`` respectively.  Both are restored from ``sys.modules``
	before returning, so the import statement binds the module the source
	code names.
	"""
	prefix_dot = prefix + "."

	def sandbox_import(name, globals=None, locals=None, fromlist=(), level=0):
		if level > 0:
			# Already inside the prefix tree; relative resolution is correct.
			return real_import(name, globals, locals, fromlist, level)
		top = name.partition(".")[0]
		if top not in isolated:
			return real_import(name, globals, locals, fromlist, level)
		prefixed = prefix_dot + name
		real_import(prefixed, globals, locals, fromlist, 0)
		if fromlist:
			return sys.modules[prefixed]
		return sys.modules[prefix_dot + top]

	return sandbox_import
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_vendor_sandbox.py -q`
Expected: 5 passed.

- [ ] **Step 5: Run the regression gate**

Run: `python3 -m pytest tests/ -q --ignore=tests/test_integration_deepseek.py --ignore=tests/test_integration_google.py --ignore=tests/test_integration_anthropic.py --ignore=tests/test_integration_openai_response.py`
Expected: 2 failed, 195 passed, 1 skipped — the baseline two failures, plus the five new tests.

- [ ] **Step 6: Commit**

```bash
git add addon/globalPlugins/WordBridge/lib/vendor.py tests/test_vendor_sandbox.py
git commit -m "feat: add the vendored-import rewriting shim"
```

---

### Task 3: Sandbox installation — namespace, roots, finder and loader

**Files:**
- Modify: `addon/globalPlugins/WordBridge/lib/vendor.py`
- Test: `tests/test_vendor_sandbox.py`

**Interfaces:**
- Consumes: `_make_sandbox_import` from Task 2.
- Produces:
  - `PREFIX: str` — `"_wb_vendor"`.
  - `install(roots, *, prefix=PREFIX, isolated=ISOLATED) -> ModuleType` — idempotent; returns the namespace module.
  - `runtime_key() -> str | None` — `"py313-win_amd64"` shape, or `None` off a supported runtime.
  - `default_roots(package_path) -> list[str]` — the roots that exist.
  - `ISOLATED: frozenset[str]` is defined in Task 4; until then Task 3's tests pass their own set explicitly.

The `isolated` and `prefix` parameters exist so tests can stand up a second, disposable sandbox rather than fight the production one for global state. Production calls `install(default_roots(PACKAGE_PATH))` and nothing else.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vendor_sandbox.py`:

```python
import importlib
import struct

from lib import vendor


@pytest.fixture
def sandbox_root(tmp_path):
	"""A fabricated two-package tree: alpha lazily imports beta by absolute name."""
	alpha = tmp_path / "alpha"
	alpha.mkdir()
	(alpha / "__init__.py").write_text(
		"def get():\n"
		"\timport beta\n"
		"\treturn beta.VALUE\n",
		encoding="utf8",
	)
	beta = tmp_path / "beta"
	beta.mkdir()
	(beta / "__init__.py").write_text("VALUE = 'sandbox'\n", encoding="utf8")
	return tmp_path


@pytest.fixture
def install_sandbox():
	"""Install a disposable sandbox and remove every trace afterwards."""
	installed = []

	def _install(roots, prefix, isolated):
		installed.append(prefix)
		return vendor.install(roots, prefix=prefix, isolated=frozenset(isolated))

	yield _install

	for prefix in installed:
		for name in [n for n in sys.modules if n == prefix or n.startswith(prefix + ".")]:
			del sys.modules[name]
		sys.meta_path[:] = [
			finder for finder in sys.meta_path
			if getattr(finder, "prefix", None) != prefix
		]


def test_namespace_path_holds_only_roots_that_exist(sandbox_root, install_sandbox):
	missing = sandbox_root / "not-here"

	namespace = install_sandbox([str(sandbox_root), str(missing)], "_wb_t1", {"alpha"})

	assert namespace.__path__ == [str(sandbox_root)]


def test_install_is_idempotent(sandbox_root, install_sandbox):
	first = install_sandbox([str(sandbox_root)], "_wb_t2", {"alpha"})
	finders_after_first = len(sys.meta_path)

	second = install_sandbox([str(sandbox_root)], "_wb_t2", {"alpha"})

	assert second is first
	assert len(sys.meta_path) == finders_after_first


def test_lazy_import_inside_a_function_resolves_to_the_sandbox(
	sandbox_root, install_sandbox, monkeypatch
):
	"""B's defining property: interception survives to call time.

	A host `beta` exists and would win any resolution that is not sandboxed.
	`alpha.get()` imports `beta` when CALLED, long after alpha was loaded.
	"""
	host_beta = types.ModuleType("beta")
	host_beta.VALUE = "host"
	monkeypatch.setitem(sys.modules, "beta", host_beta)
	install_sandbox([str(sandbox_root)], "_wb_t3", {"alpha", "beta"})

	alpha = importlib.import_module("_wb_t3.alpha")

	assert alpha.get() == "sandbox"
	assert sys.modules["beta"] is host_beta


def test_finder_declines_every_name_outside_its_prefix(sandbox_root, install_sandbox):
	install_sandbox([str(sandbox_root)], "_wb_t4", {"alpha"})
	finder = next(f for f in sys.meta_path if getattr(f, "prefix", None) == "_wb_t4")

	assert finder.find_spec("alpha", None, None) is None
	assert finder.find_spec("requests", None, None) is None
	assert finder.find_spec("_wb_t4other.alpha", None, None) is None


def test_runtime_key_is_none_off_windows(monkeypatch):
	monkeypatch.setattr(sys, "platform", "linux")

	assert vendor.runtime_key() is None


def test_runtime_key_names_the_running_interpreter_on_windows(monkeypatch):
	monkeypatch.setattr(sys, "platform", "win32")
	monkeypatch.setattr(struct, "calcsize", lambda fmt: 8)

	expected = f"py{sys.version_info[0]}{sys.version_info[1]}-win_amd64"
	assert vendor.runtime_key() == expected
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_vendor_sandbox.py -q`
Expected: the six new tests fail with `AttributeError: module 'lib.vendor' has no attribute 'install'` (and `runtime_key`). The five Task 2 tests still pass.

- [ ] **Step 3: Write the installation machinery**

Add to `addon/globalPlugins/WordBridge/lib/vendor.py`, after the imports and before `_make_sandbox_import`:

```python
import builtins
import importlib.abc
import os
import struct
import types
from importlib.machinery import ExtensionFileLoader, PathFinder

PREFIX = "_wb_vendor"
```

Then append to the same file:

```python
class _SandboxLoader(importlib.abc.Loader):
	"""Wraps a real loader to give the module a sandboxed ``__import__``.

	``exec()`` only inserts ``__builtins__`` into a globals dict that lacks it,
	so setting it before ``exec_module`` makes every absolute import in the
	module -- including ones written inside functions and executed much later --
	go through our rewrite.
	"""

	def __init__(self, loader, sandbox_import):
		self._loader = loader
		self._sandbox_import = sandbox_import

	def create_module(self, spec):
		return self._loader.create_module(spec)

	def exec_module(self, module):
		sandboxed_builtins = dict(vars(builtins))
		sandboxed_builtins["__import__"] = self._sandbox_import
		module.__dict__["__builtins__"] = sandboxed_builtins
		self._loader.exec_module(module)

	def __getattr__(self, name):
		# is_package, get_source, get_filename, get_resource_reader, ...
		return getattr(self._loader, name)


class _SandboxFinder(importlib.abc.MetaPathFinder):
	"""Answers only for its own prefix, so it can never intercept a host import."""

	def __init__(self, prefix, sandbox_import):
		self.prefix = prefix
		self._prefix_dot = prefix + "."
		self._sandbox_import = sandbox_import

	def find_spec(self, fullname, path=None, target=None):
		if not fullname.startswith(self._prefix_dot):
			return None
		spec = PathFinder.find_spec(fullname, path, target)
		if spec is None or spec.loader is None:
			return spec
		if isinstance(spec.loader, ExtensionFileLoader):
			# Native extensions resolve no Python names; cryptography 50.0.1's
			# _rust exposes its submodules as attributes and registers nothing
			# in sys.modules.  Leave its loader alone.
			return spec
		spec.loader = _SandboxLoader(spec.loader, self._sandbox_import)
		return spec


def runtime_key():
	"""Name the dependency bundle directory for the running interpreter."""
	if sys.platform != "win32":
		return None
	if struct.calcsize("P") != 8:
		return None
	return f"py{sys.version_info[0]}{sys.version_info[1]}-win_amd64"


def default_roots(package_path):
	"""The sandbox roots that actually exist, in search order."""
	roots = [str(package_path)]
	key = runtime_key()
	if key is not None:
		roots.append(os.path.join(str(package_path), "_coseeing_auth_deps", key))
	return roots


def install(roots, *, prefix=PREFIX, isolated=None):
	"""Install the sandbox once.  Never raises; a second call is a no-op."""
	existing = sys.modules.get(prefix)
	if existing is not None:
		return existing
	if isolated is None:
		isolated = ISOLATED
	namespace = types.ModuleType(prefix)
	namespace.__path__ = [str(root) for root in roots if os.path.isdir(str(root))]
	namespace.__doc__ = "WordBridge's private vendored-dependency namespace."
	sys.modules[prefix] = namespace
	sandbox_import = _make_sandbox_import(prefix, isolated, builtins.__import__)
	sys.meta_path.insert(0, _SandboxFinder(prefix, sandbox_import))
	return namespace
```

`ISOLATED` does not exist yet — Task 4 defines it. Until then, every call passes `isolated=` explicitly, which the tests do.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_vendor_sandbox.py -q`
Expected: 11 passed.

- [ ] **Step 5: Prove the lazy-import test can fail**

Temporarily change `_SandboxLoader.exec_module` to call `self._loader.exec_module(module)` without setting `__builtins__`, then run:

Run: `python3 -m pytest tests/test_vendor_sandbox.py::test_lazy_import_inside_a_function_resolves_to_the_sandbox -q`
Expected: FAIL with `assert 'host' == 'sandbox'`. Restore the line and confirm it passes again. Record both outputs in the task report — this test is the plan's only evidence that B delivers what A could not, and a test that cannot fail is worth nothing.

- [ ] **Step 6: Run the regression gate**

Run: `python3 -m pytest tests/ -q --ignore=tests/test_integration_deepseek.py --ignore=tests/test_integration_google.py --ignore=tests/test_integration_anthropic.py --ignore=tests/test_integration_openai_response.py`
Expected: 2 failed, 201 passed, 1 skipped.

- [ ] **Step 7: Commit**

```bash
git add addon/globalPlugins/WordBridge/lib/vendor.py tests/test_vendor_sandbox.py
git commit -m "feat: install the vendored-dependency namespace and its finder"
```

---

### Task 4: Category lists, stdlib gap-fill, and the anti-rot test

**Files:**
- Modify: `addon/globalPlugins/WordBridge/lib/vendor.py`
- Move: `addon/globalPlugins/WordBridge/package/secrets.py` → `addon/globalPlugins/WordBridge/package/_stdlib_gapfill/secrets.py`
- Test: `tests/test_vendor_sandbox.py`

**Interfaces:**
- Consumes: `install`, `PREFIX` from Task 3.
- Produces:
  - `ISOLATED: frozenset[str]` (nine names), `HOST_ONLY: frozenset[str]` (eight names).
  - `install_stdlib_gapfill(package_path) -> list[str]` — names it registered.

The gap-fill is **data-driven**: it registers whatever `.py` files sit in `package/_stdlib_gapfill/`. Task 1's probe decides the contents of that directory; this task builds the mechanism and ships the one member known today.

- [ ] **Step 1: Move the gap-fill source**

```bash
mkdir -p addon/globalPlugins/WordBridge/package/_stdlib_gapfill
git mv addon/globalPlugins/WordBridge/package/secrets.py addon/globalPlugins/WordBridge/package/_stdlib_gapfill/secrets.py
```

Do **not** add an `__init__.py`. The directory is a plain source folder that `install_stdlib_gapfill` reads by path; making it a package would also make it importable as `_wb_vendor._stdlib_gapfill`, which is the ambiguity the move exists to remove.

Do **not** edit the file. It is a verbatim copy of the stdlib `secrets` and must stay that way.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_vendor_sandbox.py`:

```python
from pathlib import Path

PACKAGE_ROOT = Path("addon/globalPlugins/WordBridge/package")


def test_every_bundled_top_level_name_is_classified():
	"""Adding a package to the bundle without classifying it must fail here."""
	roots = [PACKAGE_ROOT, PACKAGE_ROOT / "_coseeing_auth_deps" / "py313-win_amd64"]
	skip = {"__pycache__", "_stdlib_gapfill", "_coseeing_auth_deps"}
	found = set()
	for root in roots:
		for entry in root.iterdir():
			if entry.name in skip:
				continue
			if entry.is_dir():
				if not entry.name.endswith(".dist-info"):
					found.add(entry.name)
			elif entry.name.endswith(".py"):
				found.add(entry.name[:-3])
			elif entry.name.endswith(".pyd"):
				found.add(entry.name.split(".")[0])

	assert found == vendor.ISOLATED | vendor.HOST_ONLY


def test_categories_do_not_overlap():
	assert not (vendor.ISOLATED & vendor.HOST_ONLY)


def test_gapfill_skips_a_module_the_host_already_provides(tmp_path):
	directory = tmp_path / "_stdlib_gapfill"
	directory.mkdir()
	(directory / "json.py").write_text("RAISE = 'ours'\n", encoding="utf8")
	host_json = sys.modules["json"]

	registered = vendor.install_stdlib_gapfill(tmp_path)

	assert registered == []
	assert sys.modules["json"] is host_json


def test_gapfill_registers_a_module_the_host_lacks(tmp_path, monkeypatch):
	directory = tmp_path / "_stdlib_gapfill"
	directory.mkdir()
	(directory / "wbfakegap.py").write_text("VALUE = 'gapfill'\n", encoding="utf8")
	monkeypatch.delitem(sys.modules, "wbfakegap", raising=False)

	registered = vendor.install_stdlib_gapfill(tmp_path)
	try:
		assert registered == ["wbfakegap"]
		assert sys.modules["wbfakegap"].VALUE == "gapfill"
		assert sys.modules["wbfakegap"].__name__ == "wbfakegap"
	finally:
		sys.modules.pop("wbfakegap", None)


def test_gapfill_is_a_no_op_without_the_directory(tmp_path):
	assert vendor.install_stdlib_gapfill(tmp_path) == []


def test_secrets_gapfill_ships_and_stays_verbatim():
	source = PACKAGE_ROOT / "_stdlib_gapfill" / "secrets.py"

	assert source.is_file()
	assert not (PACKAGE_ROOT / "secrets.py").exists()
	assert "PEP 506" in source.read_text(encoding="utf8")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_vendor_sandbox.py -q`
Expected: the six new tests fail — `AttributeError` for `vendor.ISOLATED`, `vendor.HOST_ONLY` and `vendor.install_stdlib_gapfill`. The first two may instead fail on the move if Step 1 was skipped.

- [ ] **Step 4: Add the lists and the gap-fill**

Add `import importlib.util` to `lib/vendor.py`'s imports, then add after `PREFIX = "_wb_vendor"`:

```python
# Must come from us.  Prefix-only; never a global top-level name.
ISOLATED = frozenset({
	"cryptography",
	"authlib",
	"joserfc",
	"jwt",
	"coseeing_auth",
	"pypinyin",
	"zhon",
	"hanzidentifier",
	"chinese_converter",
})

# Must come from the host.  We ship copies, but they are never loaded: NVDA
# preloads all of these and sys.path insertion cannot displace a loaded module,
# so our copies have never run in production.  There is deliberately no
# fallback to them -- if NVDA ever stops shipping one, that must fail loudly
# rather than silently switch to an untested copy.
HOST_ONLY = frozenset({
	"requests",
	"urllib3",
	"certifi",
	"idna",
	"charset_normalizer",
	"cffi",
	"_cffi_backend",
	"pycparser",
})

STDLIB_GAPFILL_DIRNAME = "_stdlib_gapfill"
```

Then append to the same file:

```python
def install_stdlib_gapfill(package_path):
	"""Register copies of stdlib modules NVDA removed, under canonical names.

	NVDA's Python omits parts of the standard library -- `secrets` is the
	member known today.  The shared coseeing_auth package and the vendored
	third-party packages import those as ordinary stdlib, so they cannot be
	prefixed; they have to answer to the canonical name.

	Registration is conditional: the host is tried first, and our copy is used
	only if the host has none.  A future NVDA that restores the module then
	wins, instead of being shadowed by our frozen copy -- which would turn a
	gap-fill into the shadowing this whole design exists to remove.
	"""
	directory = os.path.join(str(package_path), STDLIB_GAPFILL_DIRNAME)
	if not os.path.isdir(directory):
		return []
	registered = []
	for entry in sorted(os.listdir(directory)):
		name, extension = os.path.splitext(entry)
		if extension != ".py" or name.startswith("_"):
			continue
		if name in sys.modules:
			continue
		try:
			builtins.__import__(name)
		except ImportError:
			pass
		else:
			continue
		spec = importlib.util.spec_from_file_location(name, os.path.join(directory, entry))
		module = importlib.util.module_from_spec(spec)
		sys.modules[name] = module
		try:
			spec.loader.exec_module(module)
		except Exception:
			del sys.modules[name]
			raise
		registered.append(name)
	return registered
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_vendor_sandbox.py -q`
Expected: 17 passed.

- [ ] **Step 6: Run the regression gate**

Run the non-network gate from Global Constraints.
Expected: 2 failed, 207 passed, 1 skipped.

If `tests/test_coseeing_auth_bundle.py` gains a failure here, it is because something still expects `package/secrets.py`. Do not revert the move — record the failure and leave it; Task 7 owns that file.

- [ ] **Step 7: Commit**

```bash
git add addon/globalPlugins/WordBridge/lib/vendor.py addon/globalPlugins/WordBridge/package/_stdlib_gapfill/secrets.py tests/test_vendor_sandbox.py
git commit -m "feat: classify vendored packages and gap-fill NVDA's removed stdlib"
```

---

### Task 5: Route `lib/coseeing_auth.py` through the sandbox

**Files:**
- Modify: `addon/globalPlugins/WordBridge/lib/coseeing_auth.py:1-56`, and its five deferred imports
- Test: `tests/test_vendor_sandbox.py`

**Interfaces:**
- Consumes: the `_wb_vendor` prefix from Task 3.
- Produces: `AUTH_AVAILABLE: bool` and `CoseeingAuthUnavailableError`, both read by tests and by Task 6's messaging.

The current file raises `ImportError` at module scope when the bundle is missing, and `__init__.py` imports it at module scope — so one missing bundle takes the whole add-on down, local correction included. That is the defect this task closes.

A useful discovery while reading: `shutdown_coseeing_auth()` already returns a completed future when no singleton was ever built, and `get_coseeing_access_token()` already converts exceptions into a failed future. So the guard belongs in **one** place — singleton construction — and the existing error paths carry it outward. Do not add guards to every entry point.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vendor_sandbox.py`:

```python
def test_coseeing_auth_module_imports_without_the_bundle():
	"""The add-on must load on a runtime where the auth bundle is absent."""
	from lib import coseeing_auth

	assert hasattr(coseeing_auth, "AUTH_AVAILABLE")
	assert issubclass(coseeing_auth.ClientClosedError, BaseException)
	assert issubclass(coseeing_auth.OAuthError, BaseException)


def test_unavailable_auth_yields_a_failed_future_not_an_exception(monkeypatch):
	from lib import coseeing_auth

	monkeypatch.setattr(coseeing_auth, "AUTH_AVAILABLE", False)
	monkeypatch.setattr(coseeing_auth, "_singleton_session", None)
	monkeypatch.setattr(coseeing_auth, "_singleton_adapter", None)

	future = coseeing_auth.get_coseeing_access_token()

	assert isinstance(future.exception(), coseeing_auth.CoseeingAuthUnavailableError)


def test_unavailable_auth_leaves_shutdown_a_no_op(monkeypatch):
	from lib import coseeing_auth

	monkeypatch.setattr(coseeing_auth, "AUTH_AVAILABLE", False)
	monkeypatch.setattr(coseeing_auth, "_shutdown_future", None)
	monkeypatch.setattr(coseeing_auth, "_singleton_session", None)
	monkeypatch.setattr(coseeing_auth, "_singleton_adapter", None)

	future = coseeing_auth.shutdown_coseeing_auth()

	assert future.done()
	assert future.exception() is None


def test_has_saved_refresh_token_is_false_without_the_bundle(monkeypatch):
	from lib import coseeing_auth

	monkeypatch.setattr(coseeing_auth, "AUTH_AVAILABLE", False)

	assert coseeing_auth.has_saved_coseeing_refresh_token() is False


def test_no_module_deletion_or_path_injection_remains():
	source = Path("addon/globalPlugins/WordBridge/lib/coseeing_auth.py").read_text(encoding="utf8")

	assert "del sys.modules" not in source
	assert "sys.path.insert" not in source
	assert "_prepare_auth_dependencies" not in source
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_vendor_sandbox.py -q`
Expected: five failures — `AttributeError` for `AUTH_AVAILABLE` / `CoseeingAuthUnavailableError`, and the source-scan test failing on `del sys.modules`.

- [ ] **Step 3: Replace the dependency-preparation block**

In `addon/globalPlugins/WordBridge/lib/coseeing_auth.py`, delete everything from
`_auth_dependencies_prepared = False` through the line
`from coseeing_auth.errors import ClientClosedError, RestoreError, TokenUnavailableError, TokenValidationError`
— that is `_auth_dependency_path()`, `_prepare_auth_dependencies()`, the bare
`_prepare_auth_dependencies()` call, and the two dependency imports — and put this in its place:

```python
COSEEING_REFRESH_TOKEN_TARGET = "org.coseeing.wordbridge/refresh"


class CoseeingAuthUnavailableError(Exception):
	"""The Coseeing auth dependencies are not loadable on this runtime."""


try:
	from _wb_vendor.authlib.integrations.base_client.errors import OAuthError
	from _wb_vendor.coseeing_auth.errors import (
		ClientClosedError,
		RestoreError,
		TokenUnavailableError,
		TokenValidationError,
	)
except ImportError as error:  # noqa: F841 - kept for the diagnostic below
	AUTH_AVAILABLE = False
	_AUTH_IMPORT_ERROR = error

	class _UnavailableAuthError(Exception):
		"""Never raised.

		Binding the names keeps every `except ClientClosedError:` in this file
		valid, so the terminate() path needs no None guards on a runtime where
		the bundle is absent.
		"""

	class OAuthError(_UnavailableAuthError):
		pass

	class ClientClosedError(_UnavailableAuthError):
		pass

	class RestoreError(_UnavailableAuthError):
		pass

	class TokenUnavailableError(_UnavailableAuthError):
		pass

	class TokenValidationError(_UnavailableAuthError):
		pass
else:
	AUTH_AVAILABLE = True
	_AUTH_IMPORT_ERROR = None


def _unavailable_reason() -> str:
	runtime = vendor.runtime_key()
	detail = f"{type(_AUTH_IMPORT_ERROR).__name__}: {_AUTH_IMPORT_ERROR}" if _AUTH_IMPORT_ERROR else "not loaded"
	return f"Coseeing auth dependencies unavailable (runtime={runtime}, {detail})"
```

Add `from . import vendor` to the module's imports (it is a sibling of `coseeing_auth.py` inside `lib/`).

- [ ] **Step 4: Update the five deferred imports**

Change each of these to its prefixed form:

| Line | From | To |
| --- | --- | --- |
| 9 (`if TYPE_CHECKING:`) | `from coseeing_auth import AuthConfig` | `from _wb_vendor.coseeing_auth import AuthConfig` |
| in `build_auth_config()` | `from coseeing_auth import AuthConfig` | `from _wb_vendor.coseeing_auth import AuthConfig` |
| in `_new_refresh_token_store()` | `from coseeing_auth import WindowsCredentialStore` | `from _wb_vendor.coseeing_auth import WindowsCredentialStore` |
| in `_get_singleton_pair()`'s region (~471) | `from coseeing_auth import CoseeingAuthClient, FutureAuthClient` | `from _wb_vendor.coseeing_auth import CoseeingAuthClient, FutureAuthClient` |

Verify none remain:

Run: `grep -n "^\s*from coseeing_auth\|^\s*from authlib\|^\s*import authlib" addon/globalPlugins/WordBridge/lib/coseeing_auth.py`
Expected: no output.

- [ ] **Step 5: Add the two availability guards**

At the top of `_get_singleton_pair()`, before anything else in the body:

```python
	if not AUTH_AVAILABLE:
		raise CoseeingAuthUnavailableError(_unavailable_reason())
```

At the top of `has_saved_coseeing_refresh_token()`:

```python
	if not AUTH_AVAILABLE:
		return False
```

Add no other guards. `get_coseeing_access_token()` already wraps `_get_singleton()` in `try/except Exception` and returns `_completed_future(error)`; `start_coseeing_auth()` already routes a failed future to the adapter; `shutdown_coseeing_auth()` already returns a completed future when the singleton is `None`, which it always is when construction never succeeded.

- [ ] **Step 6: Remove imports the deletion orphaned**

Run: `python3 -m ruff check addon/globalPlugins/WordBridge/lib/coseeing_auth.py --select F401`
Remove whatever it reports (`pathlib.Path` is the expected one). Do not remove `sys` without checking — it is used elsewhere in the file.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_vendor_sandbox.py -q`
Expected: 22 passed.

- [ ] **Step 8: Run the regression gate**

Run the non-network gate from Global Constraints.
Expected: 2 failed, 212 passed, 1 skipped.

`tests/test_coseeing_auth_nvda.py` exercises this module heavily through stubs; if any of its 26 tests fail, the cause is almost certainly a name the placeholder block did not bind. Fix by binding the missing name, not by relaxing the test.

- [ ] **Step 9: Commit**

```bash
git add addon/globalPlugins/WordBridge/lib/coseeing_auth.py tests/test_vendor_sandbox.py
git commit -m "fix: resolve Coseeing auth dependencies through the sandbox"
```

---

### Task 6: Remove the global `sys.path` injection

**Files:**
- Modify: `addon/globalPlugins/WordBridge/__init__.py:10-12`, `:42`
- Modify: `addon/globalPlugins/WordBridge/lib/tasks/typo/prompt.py:5`
- Modify: `addon/globalPlugins/WordBridge/lib/tasks/typo/utils.py:4-5`
- Modify: `addon/globalPlugins/WordBridge/lib/tasks/typo/text_policy.py:1`
- Modify: `addon/globalPlugins/WordBridge/lib/text/chinese.py:1-2`
- Modify: `tests/conftest.py`
- Test: `tests/test_vendor_sandbox.py`

**Interfaces:**
- Consumes: `install`, `default_roots`, `install_stdlib_gapfill` from Tasks 3 and 4.
- Produces: nothing new. After this task the add-on no longer touches `sys.path`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vendor_sandbox.py`:

```python
def test_plugin_entry_point_no_longer_injects_sys_path():
	source = Path("addon/globalPlugins/WordBridge/__init__.py").read_text(encoding="utf8")

	assert "sys.path.insert" not in source
	assert "vendor.install" in source


def test_installing_the_sandbox_adds_exactly_one_global_name(sandbox_root, install_sandbox):
	path_before = list(sys.path)
	modules_before = set(sys.modules)

	install_sandbox([str(sandbox_root)], "_wb_t5", {"alpha"})

	assert sys.path == path_before
	assert set(sys.modules) - modules_before == {"_wb_t5"}


def test_local_correction_imports_resolve_through_the_prefix():
	"""The add-on's own modules must not rely on package/ being on sys.path."""
	for relative in (
		"lib/tasks/typo/prompt.py",
		"lib/tasks/typo/utils.py",
		"lib/tasks/typo/text_policy.py",
		"lib/text/chinese.py",
	):
		source = Path("addon/globalPlugins/WordBridge") / relative
		text = source.read_text(encoding="utf8")
		for bare in ("from pypinyin", "from chinese_converter", "import chinese_converter", "from hanzidentifier"):
			assert f"\n{bare}" not in f"\n{text}", f"{relative} still imports {bare!r} bare"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_vendor_sandbox.py -q`
Expected: three failures on the source scans and the global-name assertion.

- [ ] **Step 3: Rewrite the entry point's prologue**

In `addon/globalPlugins/WordBridge/__init__.py`, replace:

```python
PATH = os.path.dirname(__file__)
PACKAGE_PATH = os.path.join(PATH, "package")
sys.path.insert(0, PACKAGE_PATH)
```

with:

```python
PATH = os.path.dirname(__file__)
PACKAGE_PATH = os.path.join(PATH, "package")

# Installing the sandbox must precede every _wb_vendor import below, and it
# replaces the sys.path injection that used to expose package/ to the whole
# NVDA process.  See lib/vendor.py.
from .lib import vendor

vendor.install(vendor.default_roots(PACKAGE_PATH))
vendor.install_stdlib_gapfill(PACKAGE_PATH)
```

`lib/__init__.py` is empty, so this import pulls in nothing else.

Then change line 42:

```python
from hanzidentifier import has_chinese
```

to:

```python
from _wb_vendor.hanzidentifier import has_chinese
```

- [ ] **Step 4: Rewrite the four local-correction imports**

| File | From | To |
| --- | --- | --- |
| `lib/tasks/typo/prompt.py:5` | `from pypinyin import Style, lazy_pinyin` | `from _wb_vendor.pypinyin import Style, lazy_pinyin` |
| `lib/tasks/typo/utils.py:4` | `from chinese_converter import to_simplified, to_traditional` | `from _wb_vendor.chinese_converter import to_simplified, to_traditional` |
| `lib/tasks/typo/utils.py:5` | `from pypinyin import pinyin` | `from _wb_vendor.pypinyin import pinyin` |
| `lib/tasks/typo/text_policy.py:1` | `import chinese_converter` | `from _wb_vendor import chinese_converter` |
| `lib/text/chinese.py:1` | `from hanzidentifier import identify` | `from _wb_vendor.hanzidentifier import identify` |
| `lib/text/chinese.py:2` | `from hanzidentifier import MIXED, SIMPLIFIED, TRADITIONAL` | `from _wb_vendor.hanzidentifier import MIXED, SIMPLIFIED, TRADITIONAL` |

`text_policy.py` uses `from _wb_vendor import chinese_converter` rather than `import _wb_vendor.chinese_converter` so the module keeps binding the plain name `chinese_converter`, leaving the rest of the file untouched.

`package/hanzidentifier.py`'s `from zhon import cedict` is **not** edited. It is vendored code loaded through the sandbox, so the shim rewrites it.

- [ ] **Step 5: Install the sandbox for tests**

In `tests/conftest.py`, replace:

```python
sys.path.insert(0, str(tests_path))
sys.path.insert(0, str(addon_path))
sys.path.insert(0, str(package_path))
```

with:

```python
sys.path.insert(0, str(tests_path))
sys.path.insert(0, str(addon_path))

# Tests import add-on modules directly, bypassing the plugin entry point, so
# they must stand the sandbox up themselves.  package/ deliberately does NOT
# go on sys.path -- that is the behaviour under test.
from lib import vendor

vendor.install(vendor.default_roots(package_path))
vendor.install_stdlib_gapfill(package_path)
```

Off Windows `runtime_key()` returns `None`, so the only root is `package/`. That makes `pypinyin`, `zhon`, `hanzidentifier`, `chinese_converter` and `coseeing_auth` resolvable on Linux while `authlib`, `jwt` and `cryptography` are not — which matches how the auth tests already work: they stub those modules rather than import the real ones.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_vendor_sandbox.py -q`
Expected: 25 passed.

- [ ] **Step 7: Run the regression gate**

Run the non-network gate from Global Constraints.
Expected: 2 failed, 215 passed, 1 skipped — the baseline two, plus one new failure is acceptable **only** in `tests/test_coseeing_auth_bundle.py`, which Task 7 owns. Record the exact failure. Any failure in another file is a real regression from this task: the likely cause is a module that imported a vendored package bare and was missed. Find it with

```bash
grep -rn "^\s*\(from\|import\) \(pypinyin\|zhon\|hanzidentifier\|chinese_converter\|coseeing_auth\|authlib\|jwt\|joserfc\|cryptography\)\b" addon/globalPlugins/WordBridge/ --include=*.py | grep -v "_coseeing_auth_deps\|package/"
```

Expected output after this task: nothing.

- [ ] **Step 8: Commit**

```bash
git add addon/globalPlugins/WordBridge/__init__.py addon/globalPlugins/WordBridge/lib/tasks/typo/prompt.py addon/globalPlugins/WordBridge/lib/tasks/typo/utils.py addon/globalPlugins/WordBridge/lib/tasks/typo/text_policy.py addon/globalPlugins/WordBridge/lib/text/chinese.py tests/conftest.py tests/test_vendor_sandbox.py
git commit -m "fix: stop putting the add-on's package directory on sys.path"
```

---

### Task 7: Rewrite the Windows gate and document the categories

**Files:**
- Modify: `tests/test_coseeing_auth_bundle.py:149-250`
- Modify: `addon/globalPlugins/WordBridge/package/coseeing-auth-dependencies.md`

**Interfaces:**
- Consumes: everything from Tasks 3–6.
- Produces: the pre-release gate that proves the contract on the real bundle.

`test_windows_bundle_imports_dependencies_from_addon_package` asserts that all thirteen dependencies resolve from the deps directory. Under the sandbox that premise is wrong in two ways: the nine category 2 packages now live under `_wb_vendor.*`, and the eight category 3 packages must come from **outside** the bundle. The test has to change; changing it is how the new contract gets enforced.

Do **not** touch `test_sso_configuration_matches_approved_demo`. It is one of the two known-failing baseline tests and is out of scope.

- [ ] **Step 1: Rewrite the gate**

Replace the body of `test_windows_bundle_imports_dependencies_from_addon_package` with:

```python
def test_windows_bundle_imports_dependencies_through_the_sandbox():
	if sys.platform != "win32":
		pytest.skip("Windows NVDA bundle import requires a Windows target runtime")

	bundle = PACKAGE_ROOT.resolve()
	dependencies = bundle / "_coseeing_auth_deps"
	code = """
import sys
import struct
import os
from pathlib import Path

bundle = Path(sys.argv[1]).resolve()
assert "PYTHONPATH" not in os.environ
assert (sys.version_info.major, sys.version_info.minor) == (3, 13)
assert struct.calcsize('P') == 8
deps = bundle / "_coseeing_auth_deps" / "py313-win_amd64"
assert deps.is_dir()

sys.path.insert(0, str(bundle.parent))
from lib import vendor

vendor.install(vendor.default_roots(bundle))
vendor.install_stdlib_gapfill(bundle)

import _wb_vendor.authlib
import _wb_vendor.coseeing_auth
import _wb_vendor.joserfc
import _wb_vendor.jwt
import _wb_vendor.cryptography
import _wb_vendor.pypinyin
import _wb_vendor.zhon
import _wb_vendor.hanzidentifier
import _wb_vendor.chinese_converter
from _wb_vendor.authlib.integrations.requests_client import OAuth2Session
from _wb_vendor.jwt.algorithms import RSAAlgorithm

assert callable(OAuth2Session)
assert callable(RSAAlgorithm)

for name in ("authlib", "joserfc", "jwt", "cryptography"):
    module = sys.modules["_wb_vendor." + name]
    assert Path(module.__file__).resolve().is_relative_to(deps), name
for name in ("coseeing_auth", "pypinyin", "zhon", "hanzidentifier", "chinese_converter"):
    module = sys.modules["_wb_vendor." + name]
    assert Path(module.__file__).resolve().is_relative_to(bundle), name

for name in vendor.ISOLATED:
    assert name not in sys.modules, "leaked global name: " + name

for name in vendor.HOST_ONLY:
    module = sys.modules.get(name)
    if module is None or getattr(module, "__file__", None) is None:
        continue
    assert not Path(module.__file__).resolve().is_relative_to(deps), name
"""
	subprocess.run(
		[sys.executable, "-I", "-c", code, str(bundle)],
		check=True,
		capture_output=True,
		text=True,
		env=_sanitized_windows_environment(dependencies, bundle),
	)
```

The flags change from `-I -S` to `-I`. `-S` existed to force every import to come from the bundle, which was the old contract. The new contract requires the opposite for category 3: `authlib` imports `requests`, the shim declines to rewrite it, and it must resolve from outside the bundle. With `-S` there is no outside, so `-S` now contradicts what is being tested. `-I` still ignores `PYTHONPATH` and the user site directory, and the environment is still sanitized.

- [ ] **Step 2: Prefix the stub fixture**

In `_coseeing_auth_import_dependencies`, change the six module names and the `jwt` stub to their prefixed forms, so the shim's rewrite finds them:

```python
	authlib = types.ModuleType("_wb_vendor.authlib")
	oauth2 = types.ModuleType("_wb_vendor.authlib.oauth2")
	rfc6749 = types.ModuleType("_wb_vendor.authlib.oauth2.rfc6749")
	errors = types.ModuleType("_wb_vendor.authlib.oauth2.rfc6749.errors")
	integrations = types.ModuleType("_wb_vendor.authlib.integrations")
	requests_client = types.ModuleType("_wb_vendor.authlib.integrations.requests_client")
```

and

```python
	monkeypatch.setitem(sys.modules, "_wb_vendor.jwt", types.ModuleType("_wb_vendor.jwt"))
```

Leave the class definitions and attribute assignments exactly as they are.

- [ ] **Step 3: Prefix the export test's import**

In `test_coseeing_auth_exports_windows_store_and_saved_session_api`, change

```python
	from coseeing_auth import CoseeingAuthClient, FutureAuthClient, WindowsCredentialStore
```

to

```python
	from _wb_vendor.coseeing_auth import CoseeingAuthClient, FutureAuthClient, WindowsCredentialStore
```

- [ ] **Step 4: Document the three categories**

Append to `addon/globalPlugins/WordBridge/package/coseeing-auth-dependencies.md`:

```markdown
## Import categories

The add-on loads these through the private `_wb_vendor` sandbox rather than by
modifying `sys.path` or `sys.modules`. See
`docs/superpowers/specs/2026-09-20-r03-import-isolation-design.md`.

| Category | Members | Resolution |
| --- | --- | --- |
| stdlib NVDA removed | `secrets` | canonical name, registered only when the host lacks it, sources in `package/_stdlib_gapfill/` |
| must come from us | `cryptography`, `authlib`, `joserfc`, `jwt`, `coseeing_auth`, `pypinyin`, `zhon`, `hanzidentifier`, `chinese_converter` | `_wb_vendor.*` only; never a global top-level name |
| must come from the host | `requests`, `urllib3`, `certifi`, `idna`, `charset_normalizer`, `cffi`, `_cffi_backend`, `pycparser` | NVDA's copies; the bundled copies are never loaded and there is no fallback to them |

`cryptography` needs isolating because NVDA ships a trimmed 48.0.1 that lacks
the six modules `authlib`'s joserfc import pulls in:
`hazmat.primitives.kdf{,.concatkdf,.hkdf,.pbkdf2}`, `hazmat.primitives.keywrap`
and `hazmat.primitives.padding`.

Adding a package to this directory without adding it to a category list fails
`tests/test_vendor_sandbox.py::test_every_bundled_top_level_name_is_classified`.
```

- [ ] **Step 5: Run the regression gate**

Run the non-network gate from Global Constraints.
Expected: 2 failed, 215 passed, 1 skipped — back to exactly the baseline two failures. The Windows gate skips on Linux; that skip is the pre-existing one.

- [ ] **Step 6: Commit**

```bash
git add tests/test_coseeing_auth_bundle.py addon/globalPlugins/WordBridge/package/coseeing-auth-dependencies.md
git commit -m "test: assert the sandbox contract on the real Windows bundle"
```

---

### Task 8: Post-install self-check and manual verification handoff

**Files:**
- Create: `docs/superpowers/spikes/2026-09-20-r03-selfcheck.py`

**Interfaces:**
- Consumes: the installed add-on.
- Produces: a report the maintainer pastes back. No product code.

**Deviation from the spec, stated deliberately.** Spec test 14 describes snapshotting `sys.modules` and `sys.path` "before and after the add-on loads". That is not obtainable from NVDA's Python Console: by the time the Console exists, the add-on has already loaded. The script therefore asserts the end-state invariants directly, which measures the same property — that nothing outside `_wb_vendor` was touched — with an instrument that actually exists.

- [ ] **Step 1: Write the self-check script**

Create `docs/superpowers/spikes/2026-09-20-r03-selfcheck.py`:

```python
"""R03 self-check: prove WordBridge is not polluting NVDA's import state.

Run inside NVDA's Python Console (NVDA+control+z) with WordBridge INSTALLED
and ENABLED, ideally alongside other add-ons:

	exec(open(r"C:\\path\\to\\2026-09-20-r03-selfcheck.py", encoding="utf8").read())

Every line below is PASS or FAIL.  Report to
%TEMP%\\wordbridge-r03-selfcheck.txt.
"""

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


def main():
	report = []
	namespace_lines, package_root = check_namespace()
	report.extend(namespace_lines)
	report.append("")
	for check in (check_no_global_leak, check_sandbox_origins, check_host_origins,
	              check_sys_path, check_stdlib_gapfill):
		try:
			if check is check_no_global_leak:
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
```

- [ ] **Step 2: Verify the script parses**

Run: `python3 -m py_compile docs/superpowers/spikes/2026-09-20-r03-selfcheck.py`
Expected: exit 0, no output.

- [ ] **Step 3: Commit**

```bash
git add -f docs/superpowers/spikes/2026-09-20-r03-selfcheck.py
git commit -m "spike: add R03 post-install self-check"
```

- [ ] **Step 4: Run the full gate one last time**

Run the non-network gate from Global Constraints.
Expected: 2 failed, 215 passed, 1 skipped — the two pre-existing failures only.

- [ ] **Step 5: Hand the manual verification to the maintainer**

Report these as **pending platform verification**. Do not mark the plan complete without saying so.

1. **Clear the decks first.** Remove the stale `WordBridge(include-auth)` copy from `C:\Program Files\NVDA\systemConfig\`. It predates `_coseeing_auth_deps`, ships its own `cryptography`, and does its own `sys.path` injection; leaving it makes every result below ambiguous.
2. **Self-check.** Install the new build, run Task 8's script in NVDA's Python Console, paste back `%TEMP%\wordbridge-r03-selfcheck.txt`. Expect `0 FAILURE(S)`.
3. **Coexistence.** With another add-on installed that uses `requests` and `cryptography`, confirm both work and that the host's `cryptography` is unchanged after WordBridge loads — probe v2 reports its origin.
4. **Auth lifecycle.** Login, token refresh, logout, and disabling the add-on mid-correction.
5. **Degradation.** Rename `package/_coseeing_auth_deps/py313-win_amd64` and restart NVDA: the add-on must still load, local correction must still work, and selecting the Coseeing channel must produce an intelligible message rather than silence or a crash.
6. **Windows gate.** Run `python -m pytest tests/test_coseeing_auth_bundle.py -q` on the Windows NVDA runtime so `test_windows_bundle_imports_dependencies_through_the_sandbox` actually executes instead of skipping.

---

## Self-Review

**Spec coverage.** Every spec section maps to a task. Established facts and the withdrawn `secrets.py` finding → Tasks 1 and 4. Three categories → Task 4. Architecture (namespace, `__path__`, prefix-only finder, injected `__import__`) → Tasks 2 and 3. Resolution rules including the return-value trap → Task 2. Call sites → Tasks 5 and 6. Lifecycle (install order, install-once, runtime selection) → Tasks 3 and 6. Error handling → Task 5. Spec tests 1–4 → Task 2 and Task 3; 5 → Task 3; 6–7 → Task 4; 8 → Task 6; 9–10 → Task 5; 11–13 → Task 7; 14 → Task 8; 15–17 → Task 8 Step 5. The spec's prerequisite probe → Task 1.

**Placeholder scan.** No TBD, TODO, "handle edge cases" or "similar to Task N". Every code step carries literal code; every `Run:` step names an exact command and an exact expectation. The one genuinely open value — the complete category 1 list — is isolated behind Task 1 by making the gap-fill data-driven, so no code step depends on it.

**Type consistency.** `_make_sandbox_import(prefix, isolated, real_import)` is defined in Task 2 and called in Task 3 with exactly those three arguments. `install(roots, *, prefix=PREFIX, isolated=None)` is defined in Task 3 and called in Tasks 6 and 7 as `install(default_roots(PACKAGE_PATH))`, and in tests with explicit `prefix=`/`isolated=`. `ISOLATED` and `HOST_ONLY` are named identically in Task 4's definition, Task 7's gate, Task 8's script and the dependency doc. `runtime_key()`, `default_roots()` and `install_stdlib_gapfill()` keep their names across Tasks 3, 4, 5, 6 and 7. `AUTH_AVAILABLE` and `CoseeingAuthUnavailableError` are defined in Task 5 and asserted in Task 5's tests only.

**Known forward reference.** Task 3's `install()` reads `ISOLATED` when `isolated=None`, but `ISOLATED` is not defined until Task 4. Between those tasks every call site passes `isolated=` explicitly, so the name is never evaluated. This is called out in Task 3 Step 3 rather than left to be discovered.
