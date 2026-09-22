# R03: vendored dependency isolation

## Goal

Stop WordBridge from mutating import state that the whole NVDA process shares.

NVDA runs every add-on in one CPython process. WordBridge currently inserts its
`package/` directory at `sys.path[0]` and deletes the host's `cryptography.*`
entries from `sys.modules` so its own, newer copy wins. Both effects are
process-wide: another add-on that imports `cryptography` after WordBridge loads
gets WordBridge's copy, and every top-level name under `package/` — `pypinyin`,
`zhon`, `hanzidentifier`, `chinese_converter`, `coseeing_auth`, `jwt` — becomes
globally importable.

The `2026-09-20-p0-fixes` spec specified R03 as a feasibility spike only. Its
decision rule selected **approach B, a private-prefix import sandbox**. This
document is the implementation design that spike was to unblock.

## Established facts

Measured on NVDA 2026.1 (CPython 3.13.13, win_amd64) by the two probe scripts in
`docs/superpowers/spikes/`, plus off-NVDA measurements on the same dependency
versions. Everything in this section is evidence, not assumption.

**Probe provenance.** Probe v1 ran with the add-on enabled, so
`sys.modules["cryptography"]` was already WordBridge's bundle: `__init__.py`
imports `lib.coseeing_auth` at plugin load, which deletes the host's entries and
puts the bundle first on `sys.path`. v1's probe 0 therefore inventoried our own
bundle, and its probe 2 swapped the bundle for itself, making its "approach A is
viable" verdict a false positive. **Only v1's probe 1 stands.** Probe v2 reads
NVDA's copy off disk instead of out of `sys.modules` and is unaffected.

1. NVDA ships **cryptography 48.0.1**, trimmed to 54 entries in `library.zip`,
   with `cryptography.hazmat.bindings._rust.pyd` flattened into the NVDA program
   directory beside the zip. The add-on bundles **cryptography 50.0.1**.
2. The auth stack touches 55 `cryptography.*` modules. NVDA provides 49. Six are
   absent: `hazmat.primitives.kdf` and its `concatkdf`, `hkdf` and `pbkdf2`
   submodules, `hazmat.primitives.keywrap`, and `hazmat.primitives.padding`.
3. All six are JWE-only — AES key wrap, PKCS7 symmetric padding, PBES2 and
   ECDH-ES key derivation. WordBridge verifies RS256 ID tokens, which is JWS and
   needs none of them. They arrive because `authlib.integrations.base_client`
   imports joserfc, which registers its full algorithm set at import time.
   Measured stepwise: `import jwt` (PyJWT 2.14.0) alone touches exactly the 49
   modules NVDA provides; importing any `authlib.integrations.*` module adds
   exactly the six. `OAuth2Session`, which `coseeing_auth/oidc.py` requires,
   pulls them too, so the gap cannot be avoided by reordering imports.
4. **authlib cannot be dropped.** `package/coseeing_auth/` is a shared library
   other Coseeing projects also use, and planned features still depend on
   authlib. Removing it is a cross-project decision, not a WordBridge refactor.
5. The bundle's `_rust.pyd` loads under a private module name while the host's
   own `_rust` stays importable — PyO3 tolerates two instances in one process.
6. cryptography 50.0.1's `_rust` exposes `asn1`, `exceptions`, `ocsp` and
   `_openssl` as plain attributes and registers no absolute `sys.modules` names.
   Loading it under a private prefix therefore cannot pollute
   `cryptography.hazmat.bindings._rust.*`.
7. The vendored `cryptography`, `authlib`, `joserfc` and `jwt` contain **zero**
   `importlib.import_module` and `__import__(` call sites. Every cross-package
   reference is a static `import` statement.
8. The host's `requests`, `urllib3`, `certifi`, `idna`, `cffi`,
   `charset_normalizer` and `pycparser` already win today — `sys.path` insertion
   cannot displace a preloaded module — so the bundled copies of those packages
   have never been loaded in production.
9. NVDA's Python omits the stdlib `secrets` module. `package/secrets.py` is a
   verbatim copy of it, filling that gap rather than shadowing a module the host
   provides.

### Correction (2026-09-22): facts 5 and 7 are wrong, and `cryptography` cannot be prefixed

Shipped, and it broke Coseeing login on NVDA 2026:

```
login failed during token_exchange: TypeError at algorithms.py:688:verify
  < api_jws.py:432:_verify_signature < ... < verification.py:81:verify
TypeError: Expected instance of hashes.HashAlgorithm.
```

`algorithms.py:688` is PyJWT's `key.verify(sig, msg, padding.PKCS1v15(),
self.hash_alg())`. Both errors below were then reproduced off-NVDA.

**Fact 5 was measured for the wrong property.** PyO3 does tolerate two
instances being *loaded*; it does not make their types interchangeable. Each
instance has its own `hashes.HashAlgorithm`, and objects do not cross between
them.

**Fact 7 audited Python source only.** `_rust` resolves the Python classes it
type-checks against by **absolute module name** — it asks the interpreter for
`cryptography.hazmat.primitives.hashes` and reads `HashAlgorithm` off it. That
is a C-level import; it never passes through the `__import__` that
`_SandboxLoader` installs, so the prefix rewrite cannot reach it. Grepping the
vendored Python for `import_module`/`__import__(` could not have found it.

The consequence is that a prefixed `cryptography` is unusable either way:

| host copy in `sys.modules` | result |
| --- | --- |
| present (NVDA) | `TypeError: Expected instance of hashes.HashAlgorithm` |
| absent | `KeyError: 'cryptography.hazmat.primitives.asymmetric.utils'` |

**Using the host's copy instead is still not available**, and facts 1–3 already
said why: NVDA 2026 ships a trimmed cryptography 48.0.1 in `library.zip` whose
`hazmat.primitives.kdf`, `.keywrap` and `.padding` are absent, so `joserfc` —
and therefore `authlib.integrations.requests_client` — will not import. Both
halves were re-measured on the affected machine; the probes and their output
are in `docs/superpowers/spikes/2026-09-22-host-cryptography-probe*.py|.txt`.

**Resolution.** A fourth category, `SHADOWED`, holding `cryptography` alone.
`install_shadowed()` gives it its canonical name process-wide: a meta path
finder answering for that one top-level name out of our roots, plus eviction of
the host's already-loaded `cryptography.*` entries so the next import
re-resolves. `sys.path` is untouched and no other name changes resolution.

The cost is stated rather than hidden: for the life of the process, everything
in it resolves `cryptography` to our copy. That is the same exposure the add-on
had before this work, narrowed from eleven packages to one, and it is what the
design's goal reduces to once the `_rust` constraint is admitted. Nothing is
shadowed when our roots cannot supply the name — off Windows, or with the
runtime bundle missing, the host keeps what it has and the add-on says so in
NVDA's log at load.

A follow-up that would remove even this one: the three missing pieces are six
files totalling 171 lines, all thin re-exports of `_rust`. If NVDA's `_rust`
still carries the symbols (`docs/superpowers/spikes/2026-09-22-host-rust-symbols-probe.py`
measures exactly that), they can be gap-filled under their canonical names the
way `secrets` is, and the bundled cryptography — 11 MB, 9.5 MB of it `_rust.pyd`
— dropped entirely.

### Withdrawn finding

`review-claude-2.md` T2 requirement 1 — "delete `package/secrets.py` (Python 3.6+
has it built in)" — is **wrong for NVDA's environment** and is withdrawn by fact
9. Acting on it would break authentication: `coseeing_auth/client.py` and
`coseeing_auth/oidc.py` both `import secrets`, as do seven call sites inside the
vendored packages. The file stays; this design relocates it and makes it
conditional.

## Scope

Paths are relative to `addon/globalPlugins/WordBridge/` unless noted.

In scope:

- New `lib/vendor.py` — the sandbox.
- `__init__.py` — remove `sys.path.insert(0, PACKAGE_PATH)`; install the sandbox
  as the first action; route the `hanzidentifier` import through it.
- `lib/coseeing_auth.py` — remove the `del sys.modules[...]` loop and
  `_prepare_auth_dependencies()`; route dependency imports through the sandbox;
  make the module importable when the auth half is unavailable.
- Four further files, six import statements, rerouted through the prefix:
  `lib/tasks/typo/prompt.py` (1), `lib/tasks/typo/utils.py` (2),
  `lib/tasks/typo/text_policy.py` (1), `lib/text/chinese.py` (2). With
  `__init__.py` (1) and `lib/coseeing_auth.py` (5) that is twelve statements
  across six files. `package/hanzidentifier.py`'s `from zhon import cedict` is
  vendored code and needs no edit — the sandbox rewrites it.
- `package/secrets.py` moves to `package/_stdlib_gapfill/secrets.py`.
- `tests/conftest.py`, `tests/test_coseeing_auth_bundle.py`, and new tests.
- A self-check script under `docs/superpowers/spikes/`.
- `package/coseeing-auth-dependencies.md` — document the three categories.

Explicitly **not** in scope:

- **Changing `package/coseeing_auth/` source.** It is shared with other projects;
  its imports keep working unmodified through the sandbox.
- **Making the auth stack load lazily.** Today `lib/coseeing_auth.py` imports
  authlib at plugin load. The sandbox makes deferring that easy, and R16 wants
  it, but changing load *timing* in the same change as load *path* would make
  "did B break anything?" unanswerable. Left for R16.
- **Trimming the bundle.** Fact 8 implies several bundled packages are dead
  weight. Measuring and removing them is R15, and it needs this design's
  category lists as its input.
- Removing the stale `WordBridge(include-auth)` install from NVDA's
  `systemConfig` directory — an operational step for the maintainer, noted under
  manual verification.

## Verification constraints

The author's host is Linux; Windows and NVDA verification is the maintainer's.
Each test below is marked **[auto]** (runnable on Linux with the existing NVDA
stub pattern in `tests/`), **[win]** (a Windows pre-release gate) or **[manual]**.

## Prerequisite

**Probe v3 must run before implementation.** Fact 9 identifies `secrets` as one
stdlib module NVDA removed. It must not be assumed to be the only one. The probe
enumerates every stdlib module the auth stack and the local correction path
import, diffs that set against NVDA's `library.zip` and program directory, and
returns the complete category 1 list. Implementing against a guessed list means
discovering the rest one production failure at a time.

## Design

### Three categories

Every module WordBridge needs falls into exactly one of three categories, and the
category determines how it resolves. The lists are explicit, not derived at
runtime from what happens to be present.

**Category 1 — stdlib modules NVDA removed.** Known today: `secrets`; the full
list comes from probe v3. These resolve under their **canonical names**,
globally, because the shared `coseeing_auth` package and the vendored
third-party packages import them as ordinary stdlib. They cannot be prefixed.

Registration is **conditional**: try the host first, and register our copy only
if the host has none. A future NVDA that restores `secrets` then wins, instead of
being shadowed by our frozen copy — which would turn a gap-fill into exactly the
kind of shadowing this work exists to remove.

Sources move from `package/` to `package/_stdlib_gapfill/`. Besides separating
the categories physically, this resolves an ambiguity: `package/` is one of the
sandbox roots, so a gap-fill left at that level would also be visible as
`_wb_vendor.secrets`.

**Category 2 — third-party packages that must come from us.** `authlib`,
`joserfc`, `jwt`, `coseeing_auth`, `pypinyin`, `zhon`, `hanzidentifier`,
`chinese_converter`. These resolve **only** under the `_wb_vendor.` prefix and
never appear as global top-level names.

They qualify because the host has no copy and leaving them global would claim a
shared top-level name — `jwt` especially. `coseeing_auth` qualifies because it
must see the sandboxed authlib.

`cryptography` was in this category and has been moved to category 4; see the
2026-09-22 correction above.

**Category 3 — packages that must come from the host.** `requests`, `urllib3`,
`certifi`, `idna`, `charset_normalizer`, `cffi`, `_cffi_backend`, `pycparser`.

There is deliberately **no fallback to our bundled copies**. Fact 8 shows the
host's copies already win and ours have never been exercised. If a future NVDA
drops `requests`, the correct response is a loud, specific failure naming the
changed host environment — not a silent switch to an untested, possibly stale
bundled copy.

**Category 4 — packages that must come from us under their canonical name.**
`cryptography`, alone. It qualifies under fact 2 like the rest of category 2,
but cannot be prefixed: its `_rust` extension resolves Python types by absolute
module name. Installed by `install_shadowed()`. See the 2026-09-22 correction.

### Architecture

`lib/vendor.py` is WordBridge's own module. It installs a private namespace and
nothing else.

**One global name.** `_wb_vendor` in `sys.modules` is the irreducible footprint:
prefixed modules must be findable by the import machinery. After this change,
WordBridge's total residue in the NVDA process is that one obviously-private
name plus any conditional category 1 registration. Everything else goes to zero.

**`__path__` instead of custom search logic.** `_wb_vendor.__path__` holds the
roots that exist: `package/` and `package/_coseeing_auth_deps/<runtime>/`.
`import _wb_vendor.cryptography` is then resolved by the stock `PathFinder`, and
submodules follow `_wb_vendor.cryptography.__path__` normally. No code in this
design decides where a file lives.

**A finder that answers only for its own prefix.** One `MetaPathFinder` on
`sys.meta_path` returns `None` for every name that does not start with
`_wb_vendor.`, so it cannot intercept a host or third-party import. It delegates
location to the stock machinery and wraps the returned loader for one purpose: to
inject our `__import__` into the module's `__builtins__` before `exec_module`.
Extension-module loaders are left unwrapped — fact 6 shows `_rust` needs no
Python names.

### Resolution rules

The injected `__import__` has three rules:

1. **Relative imports** (`level > 0`) delegate to the real `__import__`
   untouched. They already resolve inside the prefix tree.
2. **Top-level names in category 2** are rewritten to `_wb_vendor.<name>` and
   delegated.
3. **Everything else** delegates unchanged, so the host answers.

Rule 2 carries the design's one genuine trap: the return value. `import a.b`
must return `a`, while `from a.b import c` must return `a.b`. After prefixing,
the real `__import__` returns `_wb_vendor` and `_wb_vendor.a.b` respectively, so
both forms must be restored from `sys.modules` before returning. Getting this
wrong binds `cryptography` to the `_wb_vendor` namespace object, and the failure
appears far from its cause.

This is pure Python with no NVDA or Windows dependency, so it is fully testable
on Linux against fabricated packages. That is where the test effort goes.

Because the interception lives in each module's own globals, it stays in force
for **lazy imports made later, at call time**. cryptography relies heavily on
lazy imports; this property is precisely what approach A could not guarantee and
is the reason B was chosen.

Fact 7 establishes that rule 2 has no blind spot in the current dependency set:
there are no dynamic imports to miss. A future dependency version that adds one
would silently fall through to the host copy — which is why test 12 asserts
module origins rather than trusting the mechanism.

### Call sites

Twelve import statements across six files become ordinary prefixed imports,
for example `from _wb_vendor.pypinyin import Style, lazy_pinyin`. No accessor
function and no indirection layer: the prefix is visible at every call site and
greppable. `__init__.py`'s `sys.path.insert` and `lib/coseeing_auth.py`'s
`del sys.modules[...]` loop are deleted.

### Lifecycle

**Installation order is a hard constraint.** The sandbox must be installed before
any `from _wb_vendor.X import ...` executes, so it is the first statement in
`__init__.py`. Tests import modules such as `lib/tasks/typo/prompt.py` directly,
bypassing `__init__.py`, so `tests/conftest.py` installs the sandbox in a
fixture. That makes the tests exercise the real mechanism rather than route
around it.

**Install once, never uninstall.** `terminate()` does not tear the sandbox down.
Native extensions cannot be reliably unloaded — `_rust.pyd` stays resident once
loaded — and dismantling half of it is worse than leaving it whole. A persistent
sandbox also makes NVDA's "reload plugins" cheap and consistent.

The honest cost: after the add-on is disabled, `_wb_vendor` remains in
`sys.modules` until NVDA restarts. That residue is unavoidable and is far smaller
than today's, which is a replaced `cryptography`, an injected `sys.path` entry
and six global top-level names.

**Runtime selection.** The current code checks `sys.platform == "win32"` and then
hardcodes `py313-win_amd64`. Replace that with a key derived from the running
interpreter — Python minor version, platform, pointer size — and verify the
directory exists. An underivable key or a missing directory is a degradation
path, not an exception.

### Error handling

The binding contract: **the auth half being unavailable must never prevent the
add-on from loading or break local correction.**

This is today's defect. `_prepare_auth_dependencies()` raises `ImportError` when
the deps directory is missing on Windows, and `lib/coseeing_auth.py` is imported
at module level from `__init__.py`, so one missing or mismatched bundle takes the
whole add-on down — including the local correction path, which touches no
network.

Unavailability becomes a state rather than an exception:

- Installing the sandbox never raises. It records its outcome, and
  `_wb_vendor.__path__` holds whichever roots exist.
- `lib/coseeing_auth.py` stays importable unconditionally. The error classes it
  imports at module level (`OAuthError`, `ClientClosedError`, `RestoreError`,
  `TokenUnavailableError`, `TokenValidationError`) bind to private placeholder
  exception classes when the real ones are unavailable. The placeholders are
  never raised, but every `except ClientClosedError:` in the file stays valid,
  so the `terminate()` path that R02 just hardened needs no `None` guards.
- The module exposes `AUTH_AVAILABLE`. `start_coseeing_auth()` and
  `get_coseeing_access_token()` raise a specific domain error when unavailable,
  which the UI reports when the user selects the Coseeing channel.
  `shutdown_coseeing_auth()` becomes a no-op, leaving `terminate()` unchanged in
  shape.

Four failures must stay distinguishable, because their remedies differ:

| Failure | Message must say |
| --- | --- |
| Runtime key underivable or directory absent | what interpreter/platform was detected |
| Bundle present, module fails to load | which module, and the exception type |
| A category 3 host package is missing | that the **host** environment changed |
| Sandbox installed twice | nothing — it is a no-op |

Logs record module names and exception types. They never record tokens, API keys
or user text.

## Tests

**Linux, automated**

1. [auto] `import a.b` through the shim returns `a`; `from a.b import c` returns
   `a.b`; both bind the sandboxed module, not the namespace object.
2. [auto] A relative import inside a sandboxed package resolves within the
   prefix and is not rewritten.
3. [auto] A category 3 name imported from sandboxed code resolves to the host
   copy.
4. [auto] A lazy import written inside a function of a sandboxed module still
   resolves to the sandbox when that function is called later. This is B's
   defining property.
5. [auto] `_wb_vendor.__path__` contains exactly the roots that exist; a second
   install is a no-op and does not create a second namespace.
6. [auto] Category lists cannot rot: the importable top-level names in the two
   roots — excluding `_stdlib_gapfill`, the runtime bundle directory itself,
   `__pycache__` and non-module files — equal category 2 ∪ category 3 exactly,
   so adding a bundled package without classifying it fails.
7. [auto] Category 1 registration is conditional — with a host module present,
   ours is not registered; with it absent, ours is, under the canonical name.
8. [auto] Simulated plugin load leaves `sys.path` unmodified and adds no global
   `sys.modules` key except `_wb_vendor` and any category 1 registration.
9. [auto] With the runtime directory removed: the plugin still imports, the local
   correction path works, `AUTH_AVAILABLE` is false, the Coseeing entry points
   raise the domain error, and `shutdown_coseeing_auth()` is a no-op.
10. [auto] `lib/coseeing_auth.py` imports cleanly with the auth half unavailable,
    and its placeholder error classes keep every `except` clause valid.

**Windows, pre-release gate**

11. [win] `test_windows_bundle_imports_dependencies_from_addon_package` is
    rewritten to the sandbox contract: the nine category 2 packages resolve from
    `_wb_vendor.*` under the two roots.
12. [win] The eight category 3 packages resolve from NVDA, and no category 2
    top-level name — `cryptography`, `authlib`, `joserfc`, `jwt`,
    `coseeing_auth`, `pypinyin`, `zhon`, `hanzidentifier`, `chinese_converter` —
    exists as a global `sys.modules` key.
13. [win] `test_runtime_bundle_contains_resolved_package_versions` and
    `test_runtime_bundles_contain_native_backend_for_each_supported_runtime`
    still pass, updated for the relocated gap-fill directory.

**Self-check script**

14. [manual] A script for NVDA's Python Console, in the style of the existing
    probes: snapshot `sys.modules` and `sys.path` before and after the add-on
    loads, report the delta, and report the resolved origin of each category.
    This is the only instrument that can demonstrate non-pollution in a real
    NVDA with other add-ons present. The maintainer runs it after installing a
    new build and pastes the report back.

**Manual verification**

15. [manual] With a second add-on installed that uses `requests` and
    `cryptography`, both add-ons work, and the host's `cryptography` identity is
    unchanged after WordBridge loads.
16. [manual] Full login, token refresh, logout and add-on-disable lifecycle on
    Windows/NVDA.
17. [manual] Before running 15 and 16, remove the stale
    `WordBridge(include-auth)` copy from NVDA's `systemConfig` directory. It
    predates `_coseeing_auth_deps`, carries its own `cryptography`, and performs
    its own `sys.path` injection, which would make the results unreadable.

## Out of scope

Listed under **Scope** above: `package/coseeing_auth/` source changes, lazy
loading of the auth stack (R16), bundle trimming (R15), and removing the stale
`systemConfig` install.
