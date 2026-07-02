---
topic: v3-architecture
date: 2026-07-01
status: gotcha
related: [self_contained_python_tool_recipe, vendoring_tool_deps_into_lib_pypi, embeddable_python_ignores_pythonpath]
---
# Runtime shim leaked `scriptree/core` onto tool sys.path → stdlib shadowing (`platform`, `io`)

## Symptom

A ScripTree Python tool (dxf_length_export, and any DXF tool that imports
ezdxf) crashed at import time with:

```
File ".../lib/pypi/ezdxf/fonts/font_manager.py", line 244, in __init__
    self.platform = platform.system()
AttributeError: module 'platform' has no attribute 'system'
```

`platform.system` is bedrock stdlib — its absence means `import platform`
resolved to the WRONG `platform` module.

## Root cause

The runner splices `scriptree/core/_runtime_shim.py` between the interpreter
and the tool: `python.exe _runtime_shim.py tool.py [args]` (see
`docs/…`/`_runtime_shim.py` docstring). Python's normal rule — "the directory
of the script being run goes on `sys.path[0]`" — therefore puts
**`scriptree/core` on `sys.path`**.

`scriptree/core` is a PACKAGE directory that contains modules whose *top-level*
names collide with the stdlib:

- `scriptree/core/platform.py`  (meant to be imported as `scriptree.core.platform`)
- `scriptree/core/io.py`        (`scriptree.core.io`)

With `scriptree/core` on `sys.path` as a *top-level* location, a bare
`import platform` — issued by the tool OR, far more insidiously, by a
third-party library the tool imports (ezdxf's font manager) — resolves to
`scriptree/core/platform.py` instead of the stdlib. That module has no
`system()`, hence the crash.

The shim already prepends the tool's own dir (so `import _sibling` works), but
it never *removed its own directory*. It only bites tools that (directly or
transitively) `import platform` / `import io`, which is why it stayed latent
until the DXF tools were moved onto the bundled-python + shim path and started
importing ezdxf through it.

## Why it appeared "suddenly"

Before the self-containment migration the DXF tools ran under a system Python
where the exact `sys.path` ordering differed; after moving them to
`%SCRIPTREE_LIB_PYTHON%/python.exe` (which always goes through the shim) the
shim's dir sat ahead of the stdlib for the ezdxf import chain. Nothing about
`platform.py` changed — the exposure did.

## Fix

In `scriptree/core/_runtime_shim.py`, added `_remove_shim_dir_from_path()` and
called it at the end of `_setup_sys_path_for_tool()`. It evicts the shim's own
directory (`os.path.dirname(os.path.abspath(__file__))`) from `sys.path` using
a case-folded absolute-path comparison, exception-safe per entry. The shim has
finished importing everything it needs before it hands off to the tool, so
dropping its own dir is safe — and it is exactly the class of stdlib-shadowing
the shim exists to prevent for the tool's own siblings.

Verified: through the fixed shim, `import platform` →
`lib/python/python314.zip/platform.pyc`, `platform.system()` → "Windows",
ezdxf imports clean. Regression test added:
`tests/test_runtime_shim_and_self_heal.py::TestShimEndToEnd::test_shim_evicts_own_dir_so_stdlib_wins`.

Deployed to both `D:\Dev\ScripTree` and `R:\ScripTree` (`scriptree/core/_runtime_shim.py`
is byte-identical across the two).

## How future-me detects it

- Any tool dying with `module 'X' has no attribute '<basic-attr>'` for a stdlib
  name X (`platform`, `io`, `copy`, `types`, `glob`, `queue`, `select`, …) →
  suspect a same-named `.py` in a directory that leaked onto `sys.path`.
- `ls scriptree/core/*.py` for basenames that match stdlib module names — those
  are landmines if any dir containing them reaches a tool's `sys.path`.
- Print `sys.path[:6]` from inside a tool run through the shim: if
  `…/scriptree/core` appears, the eviction regressed.

## Guard rails

- Do NOT "solve" this by renaming `scriptree/core/platform.py` — it is a
  legitimate package submodule (`scriptree.core.platform`, imported by
  `scriptree/ui/platform_overrides_widget.py`). The fix belongs in the shim.
- Keep the eviction in `_setup_sys_path_for_tool`; the shim's contract is that
  the tool sees a clean `sys.path` (its own dir + SCRIPTREE_TOOL_DIR, stdlib,
  vendored libs) and nothing of ScripTree's internals.
