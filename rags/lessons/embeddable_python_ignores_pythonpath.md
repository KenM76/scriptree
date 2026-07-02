---
topic: v3-architecture
date: 2026-07-01
status: gotcha
related: [self_contained_python_tool_recipe, vendoring_tool_deps_into_lib_pypi]
---
# Embedded/embeddable Python ignores the PYTHONPATH environment variable

## What happened

After vendoring tool dependencies into `lib/pypi`, a tool subprocess
was launched with `PYTHONPATH=lib/pypi` set in its environment in the
expectation that `import numpy` would find the wheel. The import failed
with `ModuleNotFoundError`. The same package imported fine when the
script explicitly inserted the path via `sys.path.insert(0, lib_pypi)`.

## Root cause

The embedded (embeddable) Python distribution that ScripTree bundles
uses a **`._pth` file** to control the interpreter's path configuration.
The bundled interpreter lives at `lib/python/python.exe` and its
`._pth` file is `lib/python/python314._pth`.

The Python embeddable distribution's `._pth` mechanism deliberately
**disables `site.py`** and, with it, the normal `PYTHONPATH` environment
variable processing. This is by design for embeddable distributions —
it gives the embedding application full control over `sys.path` without
environment interference.

Evidence:

```
# This FAILS — PYTHONPATH is silently ignored:
set PYTHONPATH=D:\Dev\ScripTree\lib\pypi
lib\python\python.exe -c "import numpy"
# -> ModuleNotFoundError: No module named 'numpy'

# This WORKS:
lib\python\python.exe -c "import sys; sys.path.insert(0, r'D:\Dev\ScripTree\lib\pypi'); import numpy"
# -> (no error)
```

**The GUI process** (`run_scriptree.py`) works because it does a
programmatic `sys.path.insert(0, lib_pypi)` itself, before importing
PySide6 — it does NOT rely on `PYTHONPATH`. Tool subprocesses spawned
from the GUI inherit the environment variables but NOT the parent's
`sys.path`. The subprocess starts a fresh interpreter whose `sys.path`
is built from the `._pth` file only.

## Fix / recipe

Every tool script that needs packages from `lib/pypi` MUST do an
explicit path injection at the top of the script:

```python
import os
import sys

# The embedded Python ignores PYTHONPATH (controlled by python314._pth).
# We must inject lib/pypi ourselves.
_lib_pypi = os.environ.get("SCRIPTREE_LIB_PYPI", "")
if _lib_pypi and _lib_pypi not in sys.path:
    sys.path.insert(0, _lib_pypi)

# Now vendored packages are importable:
import numpy
import ezdxf
# etc.
```

`SCRIPTREE_LIB_PYPI` is published by `run_scriptree.py` to all tool
subprocesses (so it is always set when running under ScripTree). The
`if _lib_pypi` guard lets the script also run stand-alone for testing
as long as the developer sets `SCRIPTREE_LIB_PYPI` manually or the
packages are installed in the system Python.

### Why `sys.path.insert(0, ...)` not `sys.path.append`?

`insert(0, ...)` ensures the vendored package takes precedence over
any system-Python packages with the same name that might appear in
`sys.path` later. For ABI-sensitive compiled extensions (numpy, Pillow)
this matters — a wrong version silently misbehaves if it loads at all.

### What does `python314._pth` look like?

The `._pth` file is a text file with one entry per line, listing paths
relative to the interpreter directory to add to `sys.path`. It typically
ends with `import site` commented out or absent, which suppresses site
processing and therefore `PYTHONPATH`. Example:

```
python314.zip
.
# Uncomment to run site.py at startup.
# import site
```

If `import site` is uncommented in `._pth`, then `PYTHONPATH` would work
again — but that also re-enables user site-packages, which can introduce
unwanted system packages into the tool's environment. Do NOT uncomment
`import site` as a fix; use the explicit `sys.path.insert` instead.

## How future-me detects it

- Tool script raises `ModuleNotFoundError` for a package that IS
  present in `lib/pypi` → almost certainly the missing `sys.path.insert`.
- `set PYTHONPATH=lib/pypi && lib\python\python.exe -c "import X"` fails →
  confirms the ._pth suppression; no need to investigate further, just
  add the `sys.path.insert` to the script.
- The GUI itself imports from `lib/pypi` fine but a spawned subprocess
  can't → same cause; the GUI does the insert, the subprocess doesn't.
- Searching for "PYTHONPATH" in ScripTree sources finds it is NOT set
  in the environment published to tool subprocesses (`run_scriptree.py`
  lines 626-638 publish `SCRIPTREE_LIB_PYPI`, not `PYTHONPATH`).
