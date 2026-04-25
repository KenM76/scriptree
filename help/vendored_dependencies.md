# Vendored dependencies

ScripTree ships as a self-contained folder. Two layers of vendored
Python dependencies make that possible:

| Layer | Path | Consumed by | Typical size |
|---|---|---|---|
| **ScripTree's own runtime deps** | `lib/pypi/` | The ScripTree GUI (Python 3.11+, PySide6) | ~50 MB after `--trim` |
| **Per-tool runtime deps** | `ScripTreeApps/<tool>/lib/pypi/` | Whatever interpreter the tool launches as a subprocess | Varies per tool |

Both layers follow the **exact same pattern** — same folder layout,
same `requirements.txt` format, same management script.

## The pattern

```
<scope>/lib/
├── requirements.txt   ← pinned versions + optional "# python: <cmd>" header
├── _manifests/        ← per-package provenance notes (auto-generated)
└── pypi/              ← the actual installed packages
```

- **`requirements.txt`** is the source of truth. Every package is
  pinned to an exact version (`pkg==X.Y.Z`) — this is vendoring, not a
  dev environment.
- **`pypi/`** holds the installed binaries. It's populated by
  `pip install --target pypi -r requirements.txt`. Gitignored.
- **`_manifests/`** is for provenance notes: one `.md` per package
  recording version, source, install date. Gitignored except for
  `_manifests/README.md`.

## ScripTree's own `lib/`

See `lib/README.md` at the project root. Key workflow:

```
# First-time setup — install + trim to the ~50 MB minimum footprint
python lib/update_lib.py --trim

# Refresh after bumping a pinned version in lib/requirements.txt
python lib/update_lib.py --upgrade --trim

# Periodic CVE check
python lib/update_lib.py --audit
```

The only required package is PySide6 (plus its transitive `shiboken6`),
and optionally PySide6-QtAds for the docking system. `--trim` strips
Qt modules ScripTree doesn't import (WebEngine, QML, Quick/3D, etc.),
saving several hundred MB.

## Per-tool `lib/` (apps that need their own deps)

Tools launched as subprocesses often need packages **that aren't
PySide6** — e.g. a DXF-rendering tool needs `matplotlib` + `ezdxf` +
`numpy` + `pillow`, a data-analysis tool might need `pandas`, a web
scraper needs `requests` + `beautifulsoup4`. These go in a
`lib/pypi/` folder **inside the tool's own folder**, not in
ScripTree's top-level lib.

**Why not share one big lib?**

1. **Different interpreters.** ScripTree runs on Python 3.11+;
   `dxf-to-pdf` runs on `py -3.12`; some other tool might run on
   Python 3.9. Shared pools don't work across interpreter versions.
2. **Version isolation.** Tool A can pin `Pillow==10.x` while tool B
   pins `Pillow==12.x` without conflict.
3. **Self-contained tool folders.** Move
   `ScripTreeApps/MyTool/` to another project or another machine and
   everything it needs goes with it.
4. **Predictable cleanup.** You can always `rm -rf lib/pypi/` and
   know you only lost ScripTree's own deps — nothing app-specific.

### Layout per tool

```
ScripTreeApps/SolidWorksTools/DxfExport/dxf-to-pdf/
├── dxf-to-pdf.scriptree          ← tool definition
├── dxf_to_pdf.py                 ← script
├── README.md                     ← per-tool doc
└── lib/
    ├── requirements.txt          ← pinned deps; "# python: py -3.12" header
    ├── _manifests/
    └── pypi/                     ← vendored packages
```

The tool's script is responsible for prepending `lib/pypi/` to
`sys.path` before its other imports:

```python
from pathlib import Path
import sys

_LIB = Path(__file__).resolve().parent / "lib" / "pypi"
if _LIB.is_dir():
    sys.path.insert(0, str(_LIB))

# now: import whatever_you_need
```

### Declaring which interpreter a tool needs

At the top of the tool's `lib/requirements.txt`, add a comment:

```
# python: py -3.12
```

`update_lib.py --all-apps` parses this when deciding which Python to
call for each tool's refresh. If absent, falls back to the current
interpreter.

## The management scripts

Four scripts at the ScripTree project root handle dependency
bookkeeping and distribution:

| Script | Purpose |
|---|---|
| `lib/update_lib.py` | Install / upgrade / audit / trim vendored deps. With `--all-apps`, walks `ScripTreeApps/` and refreshes per-tool lib folders too. |
| `ScripTreeApps/audit_vendored.py` | Produces `ScripTreeApps/VENDORED_DEPS.md` — a Markdown audit of every tool's pinned vs installed versions and sizes. Exits 1 on drift. |
| `make_portable.py` | Copy ScripTree to a portable destination folder, strip dev files, run smoke-test. Handles existing `ScripTreeApps/` with keep / overwrite / backup. |
| `make_shortcut.py` | Generate a desktop shortcut (Windows `.lnk`, Linux `.desktop`, macOS `.command`) with the app icon, pointed at the launcher. |

### Running them from the command line

From the project root:

```
python lib/update_lib.py --all-apps
python ScripTreeApps/audit_vendored.py
python make_portable.py --force --scriptreeapps=keep
python make_shortcut.py
```

### Running them through ScripTree itself

The project ships a `.scriptreetree` that groups them as clickable
tools with GUI forms:

```
ScripTreeApps/ScripTreeManagement/ScripTreeManagement.scriptreetree
```

Open it in ScripTree and you get:

- **Dependencies**
  - Update / refresh vendored dependencies — all flags as checkboxes
  - Audit vendored dependencies — produces the Markdown report
- **Distribution**
  - Build portable copy of ScripTree — destination, force, zip, ScripTreeApps handling
  - Create platform-native shortcut — destination picker

Each wraps the corresponding script with labeled fields. Especially
useful for non-developer admins who shouldn't have to memorize flag
combinations.

## Refresh workflow when a CVE drops

1. `python lib/update_lib.py --audit` — list any known CVEs for the
   pinned versions.
2. Edit `lib/requirements.txt` (or the affected tool's
   `lib/requirements.txt`) — bump the problematic package to a patched
   version.
3. `python lib/update_lib.py --upgrade --trim --all-apps` — clean
   reinstall of everything with the new pins.
4. `python ScripTreeApps/audit_vendored.py` — verify pinned==installed
   across all tools.
5. Rebuild the portable: `python make_portable.py --force
   --scriptreeapps=keep`.

## Auditing

`VENDORED_DEPS.md` at the top of `ScripTreeApps/` is auto-generated
by `audit_vendored.py`. It lists:

- Every per-tool `lib/` folder found
- Which Python interpreter each declares
- Each pinned package vs the installed version (MISSING / MISMATCH / OK)
- On-disk size per tool and total

Regenerate it any time:

```
python ScripTreeApps/audit_vendored.py
```

Exit code is `1` if any tool has drift, which makes it suitable for CI.

## FAQ

**Q: Why not let pip resolve deps dynamically at startup?**
A: The whole point of vendoring is "no network, no pip, no admin rights
at runtime." Ship the folder, run `run_scriptree.bat`, done.

**Q: What if I want to share a package between multiple tools?**
A: Just put it in each tool's `lib/requirements.txt`. The duplication
is fine — a per-tool copy of Pillow is ~10 MB, and you get independent
version pinning and clean tool-folder portability in exchange. If
cross-tool sharing becomes compelling later, the update script can be
extended with a shared pool — but until you have many tools with
heavy shared deps, don't bother.

**Q: I want to use the system Python instead of the vendored one.**
A: Set `SCRIPTREE_USE_SYSTEM_DEPS=1` in the environment before launching.
`run_scriptree.py` will skip the `lib/pypi/` injection entirely.
Per-tool `lib/pypi/` is independent — each tool's script decides whether
to inject.
