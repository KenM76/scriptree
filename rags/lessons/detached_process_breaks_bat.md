---
topic: pyside6
date: 2026-05-07
status: gotcha
related: [v1_cli_needs_standalone_flag]
---
# DETACHED_PROCESS breaks .bat shims on Windows

## What happened

`v1_launcher` spawned `run_scriptree.bat` with
`creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`.
The `.bat` flashed a console for an instant, exited, and no editor
window ever appeared.  Replacing the `.bat` with a direct python
call worked — confirming the bridge wasn't the problem.

## Root cause

`DETACHED_PROCESS` strips the console entirely from the child.
But `cmd.exe` (which is what runs the `.bat`) needs a console to
execute `start "" pythonw.exe …` — without one the `start`
verb has nothing to attach to and exits immediately.

`CREATE_NEW_PROCESS_GROUP` alone is fine; `DETACHED_PROCESS` is
the part that kills the shim.

## Fix / recipe

Use `CREATE_NO_WINDOW` (0x08000000) instead of `DETACHED_PROCESS`.
That hides the cmd window without removing the console handle.

```python
# scriptree/shell/v1_launcher.py:_spawn
CREATE_NO_WINDOW = 0x08000000
flags = CREATE_NO_WINDOW
subprocess.Popen([bat_path, *args], creationflags=flags, ...)
```

Or skip the `.bat` entirely and call the python entry point
directly: `[sys.executable, str(run_scriptree_py), *args]`.

## How future-me detects it

A spawned `.bat` flashes and exits with no GUI — even though
running the same `.bat` by hand works.  Check the
`creationflags` first.  The smoking-gun symptom is that
removing the `.bat` from the chain fixes it instantly.
