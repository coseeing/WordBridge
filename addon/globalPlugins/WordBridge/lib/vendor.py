"""Private-prefix import sandbox for WordBridge's vendored dependencies.

NVDA runs every add-on in one CPython process.  Loading our dependencies by
inserting a directory on ``sys.path`` -- or by deleting the host's modules from
``sys.modules`` so ours win -- changes what every other add-on imports.  This
module loads them under a ``_wb_vendor`` prefix instead, so nothing the host or
another add-on imports is affected.

``cryptography`` is the one exception, and it is deliberate: see ``SHADOWED``.

See docs/superpowers/specs/2026-09-20-r03-import-isolation-design.md.
"""

import builtins
import importlib.abc
import importlib.util
import os
import struct
import sys
import types
from importlib.machinery import ExtensionFileLoader, ModuleSpec, PathFinder

PREFIX = "_wb_vendor"

# Must come from us.  Prefix-only; never a global top-level name.
ISOLATED = frozenset({
	"authlib",
	"joserfc",
	"jwt",
	"coseeing_auth",
	"pypinyin",
	"zhon",
	"hanzidentifier",
	"chinese_converter",
})

# Must come from the host, and deliberately not shipped: NVDA preloads all of
# these.  The bundle used to carry copies that were never loaded; they were
# removed as dead weight, and tests/test_vendor_sandbox.py now fails if one is
# added back.  There is deliberately no fallback -- if NVDA ever stops shipping
# one, that must fail loudly rather than silently switch to an untested copy.
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

# Must come from us, but CANNOT be prefixed -- it has to answer to its own
# canonical name, which means shadowing the host's copy for the whole process.
#
# `cryptography`'s work is done by `hazmat/bindings/_rust`, a PyO3 extension.
# When it type-checks an argument it resolves the expected Python class by
# ABSOLUTE module name -- it asks the interpreter for
# `cryptography.hazmat.primitives.hashes` and reads `HashAlgorithm` off it.
# That is a C-level import; it never passes through the `__import__` that
# `_SandboxLoader` installs, so the prefix rewrite cannot reach it.  A copy
# loaded as `_wb_vendor.cryptography` therefore checks its own `SHA256()`
# against whatever else is registered under the canonical name:
#
#   host copy loaded  -> TypeError: Expected instance of hashes.HashAlgorithm
#   nothing loaded    -> KeyError: 'cryptography.hazmat.primitives.asymmetric.utils'
#
# Both were reproduced off-NVDA; the first is what NVDA 2026 actually hit, in
# PyJWT's `algorithms.py` RS256 `verify`, which broke Coseeing login outright.
#
# Using the host's copy instead is not available either: NVDA ships a trimmed
# cryptography 48.0.1 in library.zip.  It is complete enough for PyJWT, but
# `hazmat.primitives.kdf`, `.keywrap` and `.padding` are absent, and without
# them `joserfc` -- and therefore `authlib.integrations.requests_client`, which
# imports it transitively -- will not import at all (measured; see
# docs/superpowers/spikes/2026-09-22-host-cryptography-probe-output.txt).
#
# So exactly one name is shadowed, by `install_shadowed()`, and the cost is
# stated rather than hidden: for the life of the process, everything in it
# resolves `cryptography` to our copy.  That is the same exposure the add-on
# had before the sandbox existed, reduced from eleven packages to this one.
SHADOWED = frozenset({"cryptography"})

STDLIB_GAPFILL_DIRNAME = "_stdlib_gapfill"


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
	sites across ``cryptography``, ``authlib``, ``joserfc`` and ``jwt``, and a
	separate grep across all nine category 2 packages for
	``import_module``/``__import__(``/``importlib.resources``/``pkgutil``/
	``pkg_resources`` confirms the same holds for the rest.  The Windows gate
	(test 12) asserts module origins rather than trusting the mechanism, to
	catch a future dependency version that adds one.
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
		if fullname[len(self._prefix_dot):].partition(".")[0] in SHADOWED:
			# The bytes are on our roots, so PathFinder would happily load a
			# SHADOWED package under the prefix -- recreating exactly the
			# second cryptography instance that install_shadowed() exists to
			# prevent. Nothing imports it this way today; this is the guard
			# that keeps it that way.
			raise ModuleNotFoundError(
				f"{fullname!r} is shadowed under its canonical name, not the prefix",
				name=fullname,
			)
		spec = PathFinder.find_spec(fullname, path, target)
		if spec is None:
			return None
		if spec.loader is None:
			# A name under our prefix that PathFinder can only resolve as a PEP
			# 420 namespace portion is not one of our packages: the prefix
			# namespace's __path__ is a real, searchable import root, so
			# PathFinder will just as happily walk into _stdlib_gapfill,
			# _coseeing_auth_deps, __pycache__ or a *.dist-info tree as into a
			# real vendored package.  Every actual category 2 package (and
			# every real subpackage of one) ships an __init__.py and never
			# reaches this branch; the one bundled exception --
			# cryptography/hazmat/bindings/_rust, a .pyi-only stub dir -- is
			# shadowed by the sibling _rust.pyd, which FileFinder resolves
			# first, so it never gets here either.  Failing outright (rather
			# than returning the inert namespace spec) is what keeps a stray
			# directory such as _coseeing_auth_deps or a *.dist-info tree
			# from ever loading as _wb_vendor.<name>.  ``importlib.util.find_spec()`` surfaces
			# this as a raised ``ModuleNotFoundError`` rather than returning
			# ``None``, which Task 8's self-check should expect if it ever
			# enumerates prefix submodules this way.
			raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)
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
		# ModuleSpec(..., is_package=True) defaults submodule_search_locations
		# to its own empty list, independent of __path__ above. The import
		# machinery itself only ever consults __path__, so that alone is
		# harmless -- but pkgutil.iter_modules() and importlib.resources read
		# __spec__.submodule_search_locations instead, and would see an empty
		# package. Point it at the exact same list object rather than a copy.
		namespace.__spec__.submodule_search_locations = namespace.__path__
		sys.modules[prefix] = namespace
	has_finder = any(getattr(finder, "prefix", None) == prefix for finder in sys.meta_path)
	if not has_finder:
		if isolated is None:
			isolated = ISOLATED
		sandbox_import = _make_sandbox_import(prefix, isolated, builtins.__import__)
		sys.meta_path.insert(0, _SandboxFinder(prefix, sandbox_import))
	return namespace


class _ShadowFinder(importlib.abc.MetaPathFinder):
	"""Resolves a few exact top-level names from our roots, and nothing else.

	It answers only for the top-level name.  Once ``cryptography`` itself is
	loaded from our root, its ``__path__`` points into that root, so the
	ordinary machinery finds every submodule there -- the finder does not need
	to (and must not) claim ``cryptography.*``, which keeps its reach as small
	as the shadowing requires.
	"""

	def __init__(self, shadowed, roots):
		self.shadowed = frozenset(shadowed)
		self.roots = [str(root) for root in roots]

	def find_spec(self, fullname, path=None, target=None):
		if fullname not in self.shadowed:
			return None
		return PathFinder.find_spec(fullname, self.roots, target)


def _resolved_from(module, roots):
	"""Did this already-loaded module come out of one of our roots?"""
	spec = getattr(module, "__spec__", None)
	origin = getattr(spec, "origin", None) or getattr(module, "__file__", None)
	if not origin:
		# A module with no origin -- frozen, a test stub, a namespace portion
		# -- cannot be shown to be ours, so it counts as the host's and gets
		# evicted.  Erring this way costs a reload; erring the other way would
		# leave the host's copy in place and reintroduce the two-instance
		# TypeError this whole mechanism exists to prevent.
		return False
	origin = os.path.abspath(str(origin))
	return any(origin.startswith(os.path.abspath(root) + os.sep) for root in roots)


def install_shadowed(roots, *, shadowed=SHADOWED):
	"""Make ``SHADOWED`` names resolve to our copies, process-wide.

	Two steps, in this order: install the finder, then evict the host's copies
	from ``sys.modules``.  ``sys.modules`` wins over every finder, so eviction
	is what actually makes the next import re-resolve -- and doing it second
	means there is no window where the name is evicted but unresolvable.

	Nothing is evicted for a name our roots cannot supply.  Off Windows, or
	with the runtime bundle missing, that is the whole of ``SHADOWED``: the
	host keeps the copy it has, which is the only working outcome available,
	rather than losing it to a shadow that cannot be provided.  Our own copy is
	never evicted either, so a repeat call cannot load it a second time and
	recreate the duplicate-instance state.

	``sys.path`` is not touched, and no name outside ``shadowed`` changes
	resolution.

	Never raises: this runs at add-on import, before NVDA's ``log`` exists, and
	a failure here must not take the add-on -- or the screen reader -- down.
	Returns ``(shadowed, evicted, skipped)`` for the caller to log: the names
	now served from our roots, the ``sys.modules`` entries dropped to make that
	happen, and the names our roots could not supply.
	"""
	roots = [str(root) for root in roots if os.path.isdir(str(root))]
	resolvable = []
	for name in sorted(shadowed):
		try:
			spec = PathFinder.find_spec(name, roots)
		except Exception:
			spec = None
		if spec is not None and spec.loader is not None:
			resolvable.append(name)
	skipped = sorted(set(shadowed) - set(resolvable))
	if not resolvable:
		return [], [], skipped
	if not any(isinstance(finder, _ShadowFinder) for finder in sys.meta_path):
		sys.meta_path.insert(0, _ShadowFinder(resolvable, roots))
	evicted = []
	for name in sorted(sys.modules):
		if name.partition(".")[0] not in resolvable:
			continue
		try:
			if _resolved_from(sys.modules[name], roots):
				continue
			del sys.modules[name]
		except Exception:
			continue
		evicted.append(name)
	return resolvable, evicted, skipped


def install_stdlib_gapfill(package_path):
	"""Register copies of stdlib modules NVDA removed, under canonical names.

	NVDA's Python omits parts of the standard library -- `secrets` is the
	member known today.  The shared coseeing_auth package and the vendored
	third-party packages import those as ordinary stdlib, so they cannot be
	prefixed; they have to answer to the canonical name.

	Every ``*.py`` file in the directory is a candidate except a dunder name
	such as ``__init__.py``.  A single leading underscore is not excluded:
	NVDA's stripped stdlib can drop a private helper module (``_pydecimal``,
	``_pyio``, ...) as easily as a public one, and Task 1's probe -- which
	decides what actually lands in this directory -- may name one.

	Registration is conditional: the host is tried first, via a real import,
	and our copy is used only if the host has none.  A future NVDA that
	restores the module then wins, instead of being shadowed by our frozen
	copy -- which would turn a gap-fill into the shadowing this whole design
	exists to remove.  The probe fully executes the host module and leaves it
	installed in ``sys.modules`` on success -- for `secrets` that also pulls in
	`base64`, `hmac` and `random` at add-on load, the same as it would for any
	other importer.  A host module that exists on disk but raises
	``ImportError`` while executing is indistinguishable, from here, from one
	that is simply absent, so our copy registers over it; that is accepted
	because a host module that cannot finish importing is not a usable one
	either way.

	Never raises (spec:270): the per-file work below -- the host probe and,
	when it stands down, executing our own copy -- is wrapped in a single
	``except Exception``, so one broken file (a host module raising something
	other than ``ImportError`` while it is probed, or our own copy failing to
	exec) cannot take the rest of the directory, or the caller, down with it.
	A module partially executed by our own copy is still removed from
	``sys.modules`` before the failure is recorded, exactly as it was before
	this was caught here instead of propagating to the caller.

	Returns ``(registered, failures)``: ``registered`` is the list of names
	newly bound under their canonical name, in the shape this function always
	returned; ``failures`` is a list of ``(name, exception)`` pairs, one per
	file that raised, for the caller to log. Logging is this function's
	caller's job, not its own -- it has no NVDA ``log`` to write to and must
	not decide what the caller does with a broken gap-fill file.
	"""
	directory = os.path.join(str(package_path), STDLIB_GAPFILL_DIRNAME)
	if not os.path.isdir(directory):
		return [], []
	registered = []
	failures = []
	for entry in sorted(os.listdir(directory)):
		name, extension = os.path.splitext(entry)
		if extension != ".py" or name.startswith("__"):
			continue
		if name in sys.modules:
			continue
		try:
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
			except BaseException:
				try:
					del sys.modules[name]
				except KeyError:
					pass
				raise
		except Exception as error:
			failures.append((name, error))
			continue
		registered.append(name)
	return registered, failures
