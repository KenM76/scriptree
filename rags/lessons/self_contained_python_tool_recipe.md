---
topic: v3-architecture
date: 2026-07-01
status: recipe
related: [embeddable_python_ignores_pythonpath, vendoring_tool_deps_into_lib_pypi, combridge_finder_scriptree_home_first]
---
# Canonical "self-contained Python tool" recipe for ScripTree apps

## What happened

SolidWorks tools were migrated from hardcoded `D:\`/`R:\` paths to
properly portable `.scriptree` definitions so they run from any
ScripTree install without machine-specific hacks. This required
understanding exactly how ScripTree publishes its environment to
tool subprocesses, how the executable field is resolved, and what
the correct working-directory/path conventions are.

## Root cause

Several related misconceptions existed simultaneously:

- Developers mixed up the `py` launcher's version selector (e.g. `-3.12`)
  with `python.exe` flags — `python.exe -3.12 myscript.py` immediately
  fails because `-3.12` is not a valid Python interpreter flag.
- The bundled Python's `exe` path (`lib/python/python.exe`) wasn't
  referenced via the published env var, so tools broke when the install
  moved.
- Working directory was set to the ScripTree install root rather than
  the tool's own directory, forcing scripts to use absolute paths to
  their own siblings.

## Fix / recipe

A fully portable `.scriptree` Python tool has this shape:

```json
{
  "name": "My Tool",
  "category": "MyCategory/Subcat",
  "executable": "%SCRIPTREE_LIB_PYTHON%/python.exe",
  "working_directory": "./.",
  "arguments": ["myscript.py", "{param1}"],
  "params": [...]
}
```

Key rules:

**1. executable — always `%SCRIPTREE_LIB_PYTHON%/python.exe`**

`os.path.expandvars()` is applied to the `executable`,
`working_directory`, and `path_prepend` fields before subprocess
launch. Source: `scriptree/core/runner.py`, `resolve_tool_path`,
approximately line 289. The runner also calls `expandvars` on the
full argument list.

Do NOT write:
- `"D:/Dev/ScripTree/lib/python/python.exe"` — absolute; breaks on
  any other machine.
- `"python"` — resolves to the system Python, which is the wrong
  ABI / missing the vendored packages.
- `"%SCRIPTREE_LIB_PYTHON%/python.exe -3.12 myscript.py"` — the
  `-3.12` flag is a `py` (launcher) flag, not a `python.exe` flag;
  `python.exe` rejects it immediately with "unrecognized option".

**2. working_directory — `"./."` (the tool's own directory)**

`"./."` resolves to the directory that contains the `.scriptree`
file. With this setting, the tool script can reference co-located
helpers by bare filename (e.g. `"myscript.py"`, `"helper.py"`
as an argument) without any path qualification. This is the most
portable choice.

Do NOT use `"."` (resolves to the ScripTree install root at
launch time) or an absolute path.

**3. No `-3.12` or similar launcher flags in the executable field**

The bundled Python is already the correct version
(currently 3.14.4 / cp314 ABI). There is no `py.exe` launcher
in the embedded distribution; `python.exe` takes no version argument.

**4. Published env vars (available to every tool subprocess)**

ScripTree's `run_scriptree.py` publishes these before spawning any
tool (lines approximately 626-638):

| Variable | Value |
|---|---|
| `SCRIPTREE_HOME` | Root of the ScripTree install |
| `SCRIPTREE_LIB` | `<SCRIPTREE_HOME>/lib` |
| `SCRIPTREE_LIB_PYPI` | `<SCRIPTREE_HOME>/lib/pypi` (vendored wheels) |
| `SCRIPTREE_LIB_PYTHON` | `<SCRIPTREE_HOME>/lib/python` (bundled interpreter) |
| `SCRIPTREE_APPS` | `<SCRIPTREE_HOME>/ScripTreeApps` |

All five are inherited by every tool subprocess, so tool scripts can
use them at runtime (e.g. `os.environ["SCRIPTREE_LIB_PYPI"]`).

Canonical docs for this:
- `D:/Dev/ScripTree/docs/LLM/scriptree_home_env_var.md`
- `D:/Dev/ScripTree/docs/portable_python.md`

## How future-me detects it

- Tool script dies with "unrecognized option: -3.12" → remove the
  launcher flag from the executable field.
- Tool works from a fixed machine but not after deploy → executable
  or working_directory contains an absolute path; switch to the
  env-var form.
- Script can't find its own helper file → working_directory is wrong;
  set to `"./."`.
- Script imports fail despite packages being in `lib/pypi` →
  see `embeddable_python_ignores_pythonpath.md` for the PYTHONPATH
  gotcha and the required `sys.path.insert` fix.
