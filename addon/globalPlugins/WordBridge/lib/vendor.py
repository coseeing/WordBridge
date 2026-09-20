"""Private-prefix import sandbox for WordBridge's vendored dependencies.

NVDA runs every add-on in one CPython process.  Loading our dependencies by
inserting a directory on ``sys.path`` -- or by deleting the host's modules from
``sys.modules`` so ours win -- changes what every other add-on imports.  This
module loads them under a ``_wb_vendor`` prefix instead, so nothing the host or
another add-on imports is affected.

See docs/superpowers/specs/2026-09-20-r03-import-isolation-design.md.
"""

import builtins
import importlib.abc
import os
import struct
import sys
import types
from importlib.machinery import ExtensionFileLoader, ModuleSpec, PathFinder

PREFIX = "_wb_vendor"


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


class _SandboxLoader(importlib.abc.Loader):
	"""Wraps a real loader to give the module a sandboxed ``__import__``.

	``exec()`` only inserts ``__builtins__`` into a globals dict that lacks it,
	so setting it before ``exec_module`` makes every ``import`` statement and
	every direct ``__import__()`` call in the module -- including ones written
	inside functions and executed much later -- go through our rewrite.  It does
	not reach ``importlib.import_module()`` or any other resolution that
	bypasses a module's own ``__import__``: spec fact 7 found zero such call
	sites across the bundled category 2 packages, and the Windows gate (test 12)
	asserts module origins rather than trusting the mechanism, to catch a future
	dependency version that adds one.
	"""

	def __init__(self, loader, sandbox_import):
		self._loader = loader
		self._sandbox_import = sandbox_import

	def create_module(self, spec):
		creator = getattr(self._loader, "create_module", None)
		return creator(spec) if creator else None

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
	"""The candidate roots in search order; existence is filtered by ``install()``."""
	roots = [str(package_path)]
	key = runtime_key()
	if key is not None:
		roots.append(os.path.join(str(package_path), "_coseeing_auth_deps", key))
	return roots


def install(roots, *, prefix=PREFIX, isolated=None):
	"""Install the sandbox.  Never raises; installs whichever half is missing.

	The namespace module and the meta path finder are tracked as two separate
	conditions rather than one "installed" flag, so a half-completed install --
	an exception between the two, or external state tampering, such as a test
	tearing one down without the other -- repairs itself on the next call
	instead of either wedging in a state that looks installed but is not, or
	inserting a second finder alongside the first.
	"""
	namespace = sys.modules.get(prefix)
	if namespace is None:
		namespace = types.ModuleType(prefix)
		namespace.__path__ = [str(root) for root in roots if os.path.isdir(str(root))]
		namespace.__doc__ = "WordBridge's private vendored-dependency namespace."
		namespace.__spec__ = ModuleSpec(prefix, None, is_package=True)
		sys.modules[prefix] = namespace
	has_finder = any(getattr(finder, "prefix", None) == prefix for finder in sys.meta_path)
	if not has_finder:
		if isolated is None:
			isolated = ISOLATED
		sandbox_import = _make_sandbox_import(prefix, isolated, builtins.__import__)
		sys.meta_path.insert(0, _SandboxFinder(prefix, sandbox_import))
	return namespace
