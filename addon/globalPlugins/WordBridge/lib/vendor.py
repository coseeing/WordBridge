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
