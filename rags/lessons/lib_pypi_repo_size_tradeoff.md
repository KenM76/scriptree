---
topic: v3-process
date: 2026-07-01
status: resolved
related: [vendoring_tool_deps_into_lib_pypi, portable_zip_bundles_solidworks_interop, make_portable_non_interactive]
---
# lib/pypi repo-size trade-off: committing vendored tool deps bloats the public repo

## RESOLUTION (2026-07-01) — relocated to an app-local `_vendor`

Decision made and implemented: the SolidWorks DXF render stack was **moved OUT
of `lib/pypi` into the tools' own private folder**,
`ScripTreeApps/SolidWorks/Export/SwDxfExport/_vendor/` (86 MB on disk, ~31 MB
zipped). Rationale that settled it: **the DXF tools are SolidWorks-private and
are NOT in the public release zip, yet their deps were sitting in the shared,
committed `lib/pypi` that IS in the zip** — bloating a public download with
~31 MB (zipped) of deps for tools it doesn't even ship. A safety grep confirmed
nothing else (the `scriptree` package, the public catalog, or the GUI packages
PySide6/shiboken/QtAds/CommonRegex) imports any of the closure — it was 100%
for the DXF tools.

What was done:
- Copied the full tier-2 closure (ezdxf, matplotlib, numpy(+numpy.libs),
  Pillow, fonttools, pyparsing, typing_extensions, contourpy, cycler,
  kiwisolver, packaging, python-dateutil, six) into `SwDxfExport/_vendor`
  (stripped of `__pycache__`/`tests`/`*.pyi`).
- Repointed each DXF tool's `_ensure_scriptree_lib_on_path` to insert the
  co-located vendor dir FIRST — `__file__`'s grandparent `/ _vendor` (scripts
  live at `SwDxfExport/<tool>/<script>.py`) — with `%SCRIPTREE_LIB_PYPI%` and
  user-site/pip kept as fallbacks.
- Removed the entire render stack from BOTH `lib/pypi` trees
  (156 MB → 53 MB) and removed the render section from `lib/requirements.txt`
  (leaving a NOTE that points here). `lib/pypi` is back to GUI-only deps.
- Verified end-to-end: all three DXF tools load their deps from `_vendor`
  through the runtime shim with `lib/pypi` emptied of them; `ezdxf.__file__`
  resolves under `_vendor`.

Net: the public release zip drops ~31 MB and carries only what ScripTree's own
GUI needs. The tiers below are retained for reference (minimum footprints).

### Minimum DXF footprints (measured, trimmed, cp314)
- **ezdxf-only** (dxf-cleanup, dxf-length-export, dxf-export sans PDF):
  ezdxf + numpy(+numpy.libs 21 MB!) + fonttools + pyparsing + typing_extensions
  = ~58 MB on disk / ~18 MB zipped. numpy is the unavoidable tax (ezdxf requires it).
- **Full** (adds dxf-to-pdf + PDF rollup): + matplotlib + Pillow + small deps
  = ~101 MB on disk (86 MB after the `__pycache__`/tests/pyi trim) / ~31 MB zipped.

### Watch-out
`_vendor` lives in the Dropbox-synced `R:` tree too, so the no-bytecode policy
applies: tools must run with `PYTHONDONTWRITEBYTECODE=1` (inherited from
ScripTree's launcher) or they'll write `__pycache__` into `_vendor` and trigger
a sync storm — exactly as they would have in `lib/pypi`. Same exposure, same
mitigation.

---

## Original write-up (the trade-off, before it was resolved)

## What happened

After vendoring the SolidWorks render stack (ezdxf + matplotlib + numpy
+ Pillow + fonttools + transitive deps) into `lib/pypi` as part of the
self-containment migration, the `lib/pypi` directory grew by approximately
**115 MB**. Since `lib/pypi` is NOT gitignored in the ScripTree repo, this
would be committed directly into the public `KenM76/scriptree` GitHub repo.

## Root cause

There is a documented contradiction between two goals:

1. **Self-containment (current README position):** `lib/python/` and
   `lib/pypi/` are "deliberately committed so that a fresh clone is
   immediately runnable."
2. **Lean public repo:** A 115 MB addition to `lib/pypi` for SolidWorks
   tool dependencies that are SolidWorks-private (per the never-publish
   rule) creates unnecessary bloat in a public open-source repository —
   and those deps aren't useful to anyone without SolidWorks tools.

Additionally, `lib/update_lib.py` exists precisely to re-vendor packages
on a fresh machine, which partially contradicts the "commit everything"
position.

## The unresolved trade-off

This is an open decision for Ken. The three realistic options:

### Option A — Commit everything (status quo extended)
Commit the full `lib/pypi` including tool-specific wheels.

- Pro: `git clone` → immediately runnable, no extra steps.
- Con: 115 MB of SolidWorks-tool-specific packages bloats the public
  repo permanently (Git history never forgets large files). Tools for
  non-SolidWorks users see the bloat and can't use those tools anyway.

### Option B — Gitignore tool-specific packages
Add tool-specific package dirs to `.gitignore`, keep GUI-only packages
(PySide6, etc.) committed.

- Pro: Lean public repo.
- Con: Contradicts the current README ("deliberately committed");
  new machines / CI must run `lib/update_lib.py` before SolidWorks
  tools work. Must also update `make_portable.py` to install them
  before zipping.
- Implementation: add entries to `.gitignore` like:
  ```
  lib/pypi/ezdxf*/
  lib/pypi/matplotlib*/
  lib/pypi/numpy*/
  lib/pypi/PIL*/
  lib/pypi/Pillow*/
  lib/pypi/fonttools*/
  # ... transitive deps ...
  ```

### Option C — Separate tool-dep vendor dir
Create `lib/pypi_tool_deps/` (gitignored), keep `lib/pypi/` (GUI-only,
committed). Tool scripts `sys.path.insert` both dirs. `update_lib.py`
populates `lib/pypi_tool_deps/` on-demand. `make_portable.py` merges
them before zipping.

- Pro: Clean separation of what is / isn't committed; public repo stays
  lean; portable zip remains self-contained.
- Con: More infrastructure to maintain; two dirs to inject into
  `sys.path`.

## Immediate holding pattern

Until Ken decides, treat **all `lib/pypi` additions for tool-specific
deps as NOT committed**. Install them locally for dev/test, deploy to
both `D:\Dev\ScripTree\lib\pypi` and `R:\ScripTree\lib\pypi` (the
two-tree deploy obligation still applies), but hold the `git add`.

If the decision is Option B or C, update both `lib/update_lib.py`
(to install tool deps) and the README (to document the install step).

## UPDATE 2026-07-01 — size partly mitigated + a bytecode-policy bug found & fixed

Two follow-ups landed the same day:

### 1. `--trim` now covers tool deps (not just PySide6)

`lib/update_lib.py`'s `cmd_trim` was PySide6/Qt-only. It now also runs a
**generic pass over EVERY vendored package** (`_trim_generic`) that strips:
`__pycache__/`, `tests/` + `test/` dirs, `*.pyi` stubs, and per-package
build/example extras (`GENERIC_TRIM_PACKAGE_EXTRAS` — currently
`numpy/_core/include`, `matplotlib/mpl-data/sample_data`). Result:
`lib/pypi` went **189 MB → ~140 MB** (≈49 MB / 26% freed) with the render
stack fully functional afterward (verified with a real ezdxf→matplotlib
render). So the "115 MB" figure above is the *untrimmed* install; the
trimmed footprint is materially smaller. The size trade-off (A/B/C above)
is still open, just on a smaller number.

`numpy.testing` is deliberately KEPT (public runtime API) — only literal
`tests`/`test` dirs are removed.

### 2. THE REAL GOTCHA: `pip install --target` violated the no-bytecode policy

`pip install --target lib/pypi ...` compiles `.pyc` by default → it wrote
**~38 MB of `__pycache__/`** into `lib/pypi`. Because `R:\ScripTree` is a
Dropbox subst (and OneDrive installs are supported), that DIRECTLY
violates `docs/LLM/no_bytecode_policy.md` — bytecode in a cloud-synced
tree triggers the 15–30 s-per-launch sync storm the policy exists to
prevent. Fixes applied to `update_lib.py`:

- `cmd_install`'s pip command now passes **`--no-compile`** so fresh
  vendoring never writes bytecode.
- `_trim_generic` strips any `__pycache__` a manual (non-`--no-compile`)
  `pip install` left behind.
- `update_lib.py` itself now sets `sys.dont_write_bytecode = True` at the
  top (it runs in-tree; the policy requires every in-tree entry-point to
  guard).

Note: real ScripTree *tool* subprocesses already inherit
`PYTHONDONTWRITEBYTECODE=1` from the launcher `.bat`, so the DXF tools
importing from `lib/pypi` won't re-introduce bytecode. The exposure was
purely the one-time `pip install --target` step. When you re-vendor,
always `python lib/update_lib.py --upgrade --trim` (which now uses
`--no-compile` + the generic trim) rather than a bare `pip install`.

## How future-me detects it

- `git diff --stat` after `pip install --target lib/pypi <tool-pkg>` shows
  hundreds of new files totalling tens/hundreds of MB → this trade-off
  applies. Stop and check what Ken decided.
- `git ls-tree -r HEAD --name-only | grep lib/pypi | wc -l` shows an
  unexpectedly large file count → tool-specific deps were committed without
  a decision having been made.
- The README says "python/ and pypi/ are deliberately committed" but the
  `.gitignore` excludes some `lib/pypi/` entries → the decision was made;
  follow the gitignore, not the stale README sentence.
