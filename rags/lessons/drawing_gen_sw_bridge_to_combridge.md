---
topic: v3-architecture
date: 2026-07-01
status: recipe
related: [combridge_finder_scriptree_home_first, self_contained_python_tool_recipe, combridge_bundle_workflow]
---
# Drawing-gen tool migrated from sw_bridge.exe to combridge

## What happened

The SolidWorks drawing-generation tool was the last tool still
invoking `sw_bridge.exe` (the predecessor to combridge). The
sw_bridge lived only at a hardcoded OneDrive path and was never
bundled into ScripTree's `lib/` directory, so the tool was
inherently non-portable. Self-containment required migrating the
launcher to combridge, which IS bundled.

## Root cause

`sw_bridge.exe` was a monolithic, SolidWorks-only predecessor to
combridge. It never received a deployment wrapper for ScripTree;
the drawing-gen tool's `.scriptree` definition pointed to:

```
C:\Users\Ken\OneDrive\Kens_Projects\Claude\sw_bridge\sw_bridge.exe
```

This path:
- Does not exist on any machine other than Ken's.
- Is not bundled into any ScripTree portable distribution.
- Cannot be expressed via a ScripTree env var.

combridge is the documented successor and IS bundled under
`lib/combridge/` in every portable ScripTree install.

## Fix / recipe

### 1. `.csx` script — no changes required

combridge injects the same SolidWorks global variables as sw_bridge:
`swApp`, `swDoc`, `swPart`, `swAssy`, `swDrawing`. The `.csx`
script body ported verbatim — no code changes. This is by design:
combridge's SolidWorks plugin guarantees API compatibility with
sw_bridge for the `run-script` command.

### 2. Launcher change — CLI shape

Old (sw_bridge):
```
sw_bridge.exe run-script <file.csx> <out>
```

New (combridge):
```
combridge solidworks run-script <file.csx> <out>
```

The only differences are:
- Executable: `sw_bridge.exe` → `combridge solidworks` (the plugin subcommand).
- Subcommand prefix: `run-script` stays the same but is now under `solidworks`.

### 3. `.scriptree` launcher update

If the tool's `.scriptree` invokes combridge via a Python wrapper
(the typical pattern for SW tools):

```json
{
  "executable": "%SCRIPTREE_LIB_PYTHON%/python.exe",
  "working_directory": "./.",
  "arguments": ["drawing_gen_launcher.py", "{input_file}", "{output_file}"]
}
```

Inside `drawing_gen_launcher.py`:

```python
import os, sys, subprocess

# Inject lib/pypi for any vendored deps this script uses
_lib_pypi = os.environ.get("SCRIPTREE_LIB_PYPI", "")
if _lib_pypi and _lib_pypi not in sys.path:
    sys.path.insert(0, _lib_pypi)

# Locate combridge (see combridge_finder_scriptree_home_first.md)
from find_combridge import find_combridge   # or inline the function

combridge = find_combridge()
csx_path = os.path.join(os.path.dirname(__file__), "drawing_gen.csx")

result = subprocess.run(
    [str(combridge), "solidworks", "run-script", csx_path, "-"],
    capture_output=True, text=True
)
if result.returncode != 0:
    print(result.stderr, file=sys.stderr)
    sys.exit(result.returncode)
print(result.stdout)
```

If the tool's `.scriptree` invokes combridge DIRECTLY (no Python wrapper):

```json
{
  "executable": "combridge.exe",
  "arguments": ["solidworks", "run-script", "drawing_gen.csx", "-"]
}
```

(ScripTree prepends `lib/combridge` to PATH; bare `combridge.exe` resolves.)

### 4. Precedent — dxf_export already migrated

`dxf_export.py` was a prior migration from sw_bridge to combridge,
following the same pattern. The drawing-gen migration is the second
of its kind. Future tools should start with combridge from day one.

### 5. sw_bridge disposition

`sw_bridge.exe` (and its source at
`C:\Users\Ken\OneDrive\Kens_Projects\Claude\sw_bridge\`) is kept
as a legacy reference but should not be the target of any new code
or new tool definitions. If found in a `.scriptree` definition,
migrate it to combridge.

## How future-me detects it

- Tool fails with "cannot find sw_bridge.exe" or "path not found" pointing
  to an OneDrive location → still using the old sw_bridge launcher; migrate
  to combridge.
- A `.scriptree` file with `"executable": "…sw_bridge…"` → migrate.
- The `.csx` script body itself does NOT need to change — combridge
  injects the same globals.
- combridge invocation is `combridge solidworks run-script <csx> <out>`,
  NOT `combridge run-script <csx> <out>` (the plugin name is required).
