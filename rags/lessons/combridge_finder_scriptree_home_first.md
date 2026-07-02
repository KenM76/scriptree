---
topic: v3-architecture
date: 2026-07-01
status: recipe
related: [self_contained_python_tool_recipe, combridge_bundle_workflow, drawing_gen_sw_bridge_to_combridge]
---
# combridge finder resolution order: SCRIPTREE_HOME-first

## What happened

SolidWorks tool scripts that needed to locate `combridge.exe` at
runtime were hardcoding `R:/ScripTree/lib/combridge/combridge.exe`
or `D:/Dev/ScripTree/...`. This immediately broke on any other
machine or any portable install. A canonical discovery order was
established so tools always find combridge correctly regardless of
where ScripTree is installed.

## Root cause

There is no single authoritative "where is combridge?" API exposed
to tool scripts — they must discover it themselves. The naive approach
is to hardcode the dev/runtime paths. This fails:

- On another user's machine (different drive letter / folder name).
- In a portable ScripTree install on a USB drive.
- If Ken's `D:` vs `R:` subst alias changes.

Additionally, a combridge build without the SolidWorks plugin DLL
should be REJECTED early with a clear error, not fail silently at
the COM call.

## Fix / recipe

Use this discovery order in any Python tool script that needs
`combridge.exe`:

```python
import os
import shutil
from pathlib import Path

def find_combridge() -> Path:
    """
    Locate combridge.exe using a portable resolution order.

    Priority:
      1. SCRIPTREE_COMBRIDGE env var — explicit override (for testing / CI).
      2. %SCRIPTREE_HOME%/lib/combridge/combridge.exe — standard install location.
      3. %SCRIPTREE_LIB%/combridge/combridge.exe — alternate lib spelling.
      4. shutil.which("combridge.exe") — PATH lookup (ScripTree prepends
         lib/combridge to PATH before spawning tool subprocesses).
      5. Dev/runtime fallback hardcodes (D: and R:) — last resort only.

    Raises FileNotFoundError with a helpful message if nothing resolves.
    Also validates that the SolidWorks plugin DLL is present alongside
    the exe — a combridge build without plugins is useless for SW tools.
    """
    candidates = []

    # 1. Explicit override
    override = os.environ.get("SCRIPTREE_COMBRIDGE")
    if override:
        candidates.append(Path(override))

    # 2. SCRIPTREE_HOME (the standard install root)
    home = os.environ.get("SCRIPTREE_HOME")
    if home:
        candidates.append(Path(home) / "lib" / "combridge" / "combridge.exe")

    # 3. SCRIPTREE_LIB (alternate form)
    lib = os.environ.get("SCRIPTREE_LIB")
    if lib:
        candidates.append(Path(lib) / "combridge" / "combridge.exe")

    # 4. PATH lookup (ScripTree prepends lib/combridge to PATH)
    which_result = shutil.which("combridge.exe")
    if which_result:
        candidates.append(Path(which_result))

    # 5. Last-resort dev/runtime fallbacks
    for fallback in [
        r"D:\Dev\ScripTree\lib\combridge\combridge.exe",
        r"R:\ScripTree\lib\combridge\combridge.exe",
    ]:
        candidates.append(Path(fallback))

    for candidate in candidates:
        if not candidate.exists():
            continue
        # Validate that the SolidWorks plugin is present.
        plugin_dir = candidate.parent / "plugins" / "ComBridge.Plugins.SolidWorks"
        plugin_dll = plugin_dir / "ComBridge.Plugins.SolidWorks.dll"
        if not plugin_dll.exists():
            # Found combridge.exe but the SW plugin is missing — this is a
            # dev build without the plugin; reject and keep searching.
            continue
        return candidate

    raise FileNotFoundError(
        "combridge.exe with SolidWorks plugin not found.\n"
        "Checked: SCRIPTREE_COMBRIDGE, SCRIPTREE_HOME/lib/combridge, "
        "SCRIPTREE_LIB/combridge, PATH, D:/Dev fallback, R:/ScripTree fallback.\n"
        "Ensure ScripTree has a combridge bundle installed (lib/install_combridge.ps1)."
    )
```

### For `.scriptree` files whose executable IS combridge directly

If the `.scriptree` tool invokes combridge directly as its `executable`
(rather than calling it from within a Python script), use bare
`"combridge.exe"` — no path at all:

```json
{
  "executable": "combridge.exe",
  "arguments": ["solidworks", "run-script", "my_script.csx", "-"]
}
```

ScripTree's runner prepends `<SCRIPTREE_HOME>/lib/combridge` to `PATH`
before launching every tool, so the bare name resolves correctly via the
standard PATH mechanism. This is the simplest and most portable form.

### Plugin validation rationale

Validating `plugins/ComBridge.Plugins.SolidWorks/ComBridge.Plugins.SolidWorks.dll`
exists catches the case where a developer's machine has a `combridge.exe`
build from a different project or a partial build that lacks the SolidWorks
plugin. A combridge without the SolidWorks plugin will either fail at the
`solidworks` subcommand or connect to the wrong COM server — better to fail
fast with a clear error.

Do NOT validate for `SolidWorks.Interop.*.dll` — those interop DLLs are
SolidWorks SDK files that are gitignored and must be stripped from public
release zips (see `portable_zip_bundles_solidworks_interop.md`). The
presence of the plugin DLL alone is sufficient.

## How future-me detects it

- Script raises `FileNotFoundError: combridge.exe … not found` → SCRIPTREE_HOME
  is not set (tool not launched via ScripTree), or the combridge bundle was
  not installed; run `lib/install_combridge.ps1`.
- Tool works on dev machine but not on another → hardcoded path leaked into
  the script; switch to `find_combridge()` above.
- combridge.exe found but `solidworks` subcommand fails immediately → plugin
  missing; the validation above would have caught this.
- ScripTree's runner prepending `lib/combridge` to PATH can be confirmed by
  inspecting `run_scriptree.py`'s env-building code.
