---
topic: v3-architecture
date: 2026-07-01
status: recipe
related: [self_contained_python_tool_recipe, embeddable_python_ignores_pythonpath, pip_target_existing_dir_clobbers_siblings]
---
# Vendoring tool dependencies into `lib/pypi`

## What happened

SolidWorks drawing-generation tools needed `ezdxf`, `matplotlib`,
`numpy`, `Pillow`, `fonttools`, and their transitive dependencies at
runtime. The ScripTree portable bundle already vendors PySide6 into
`lib/pypi` for the GUI, but tool-specific packages need to go there
too — and they must be installed against the **bundled** interpreter's
ABI, not any system Python.

## Root cause

`pip install <pkg>` against the system Python produces wheels compiled
for the system ABI. The bundled interpreter is currently **Python 3.14.4
(cp314)**, which is different from what most users have system-installed.
Cross-ABI wheels for compiled extensions (numpy, Pillow, etc.) silently
load wrong or crash with `ImportError: incompatible API`. The only way to
guarantee ABI compatibility is to install with the bundled interpreter itself.

A secondary issue: the bundled interpreter ignores `PYTHONPATH`
(see `embeddable_python_ignores_pythonpath.md`), so packages must be
imported via an explicit `sys.path.insert` inside the script — just
having them in `lib/pypi` is not enough.

## Fix / recipe

### Step 1 — declare the dependency in `lib/requirements.txt`

Add the package with a pinned exact version:

```
# tool deps — SolidWorks drawing tools
ezdxf==1.4.1
matplotlib==3.10.3
numpy==2.3.1
Pillow==11.2.1
fonttools==4.58.2
```

Pinning to exact versions (`==`) ensures reproducible installs across
machines and across CI.

### Step 2 — install using the BUNDLED interpreter

```powershell
# From the ScripTree dev root (D:\Dev\ScripTree):
lib\python\python.exe -m pip install --target lib\pypi ezdxf==1.4.1 matplotlib==3.10.3 numpy==2.3.1 Pillow==11.2.1 fonttools==4.58.2
```

Using `lib\python\python.exe` (not `python`) ensures:
- The ABI tag matches the bundled interpreter (cp314-cp314-win_amd64 etc.)
- The installed bytecode is compatible at runtime

WARNING: see `pip_target_existing_dir_clobbers_siblings.md` — installing
into an existing `lib/pypi` with `--target` can silently DELETE sibling
packages. Prefer staging to a temp dir first:

```powershell
$tmp = New-TemporaryFile | % { $_.DirectoryName + "\" + $_.BaseName + "_pypi" }
New-Item -Type Directory $tmp
lib\python\python.exe -m pip install --target $tmp ezdxf==1.4.1 ...
Copy-Item -Recurse "$tmp\*" "lib\pypi\"
Remove-Item -Recurse $tmp
```

After installing, run:
```powershell
git status --short | findstr "^.D"
```
to catch any packages that were accidentally deleted.

### Step 3 — make the tool script import them at runtime

In the tool script itself, add this near the top (before any `import`
that needs the vendored package):

```python
import os, sys

# Inject vendored packages — required because the embedded Python
# ignores PYTHONPATH (see embeddable_python_ignores_pythonpath.md).
_lib_pypi = os.environ.get("SCRIPTREE_LIB_PYPI", "")
if _lib_pypi and _lib_pypi not in sys.path:
    sys.path.insert(0, _lib_pypi)

import numpy        # now works
import matplotlib   # now works
import ezdxf        # etc.
```

`SCRIPTREE_LIB_PYPI` is published by `run_scriptree.py` to every tool
subprocess.

### Step 4 — deploy to both trees (two-tree obligation)

```powershell
# Repeat the pip install against R:\ScripTree too:
R:\ScripTree\lib\python\python.exe -m pip install --target R:\ScripTree\lib\pypi ezdxf==1.4.1 ...
# OR: xcopy /E the lib\pypi additions from D:\ to R:\
```

Both `D:\Dev\ScripTree\lib\pypi` and `R:\ScripTree\lib\pypi` must be
updated — the two-tree deploy obligation applies to `lib/` just as it
does to source code.

## Size warning / open trade-off

The render stack (ezdxf + matplotlib + numpy + Pillow + fonttools +
transitive deps) adds approximately **115 MB** to `lib/pypi`.

`lib/pypi` is currently NOT gitignored in the ScripTree repo, so
committing vendored packages bloats the public GitHub repo. The
alternative is to gitignore `lib/pypi` (or the tool-specific additions)
and rely on `lib/update_lib.py` to re-vendor per machine — but the
current README says "python/ and pypi/ are deliberately committed."

**This is an unresolved trade-off that Ken needs to decide:**
- Commit `lib/pypi` → self-contained clone, large public repo.
- Gitignore tool-specific packages in `lib/pypi` → small repo, but
  `lib/update_lib.py` must be run before the tools work.
- Middle ground: commit a `lib/pypi.tool_deps/` sidecar, ignored from
  the main pypi dir, with a `make install-tool-deps` step.

Until decided, treat `lib/pypi` changes as requiring explicit review
before committing.

## How future-me detects it

- Tool crashes with `ImportError: No module named 'numpy'` (or similar)
  at startup → package not in `lib/pypi`, or `sys.path.insert` missing.
- `ImportError` with "incompatible API version" → package was installed
  with the system Python (wrong ABI); re-install with the bundled
  interpreter.
- Package IS in `lib/pypi` but import still fails → the embedded
  interpreter's `PYTHONPATH` is ignored; the `sys.path.insert` is the
  required fix.
- `git status` shows deleted files in `lib/pypi` after a pip install →
  pip clobbered siblings; see `pip_target_existing_dir_clobbers_siblings.md`.
