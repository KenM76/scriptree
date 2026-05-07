---
topic: v3-architecture
date: 2026-05-07
status: gotcha
related: [detached_process_breaks_bat]
---
# V1's CLI defaults to MainWindow when given a .scriptree path

## What happened

`v1_launcher.launch_tool` invoked `python run_scriptree.py
foo.scriptree` to launch a tool from a V3 cell.  Instead of
the lightweight standalone runner appearing, V1's full
MainWindow editor opened — wrong UX entirely for a cell click.

## Root cause

V1's CLI treats a `.scriptree` argument as "open this in the
editor" by default.  The lightweight runner is a separate
mode gated behind `-standalone`.  Without that flag, you get
the editor.

## Fix / recipe

`v1_launcher` MUST always pass `-standalone` for cell-shell
tool launches:

```python
# scriptree/shell/v1_launcher.py:launch_tool
args = [str(run_scriptree_py), "-standalone", str(scriptree_path)]
subprocess.Popen([sys.executable, *args], ...)
```

If V3 ever needs to launch the V1 editor instead (e.g. an
"Edit tool" action), build a separate launcher path that
omits the flag.

## How future-me detects it

Click a tool cell and the V1 MainWindow editor appears
instead of the simple Run-controls dock.  Check the args
passed to V1; missing `-standalone` is the cause.
