---
topic: forest_controller_module_global_handle
date: 2026-06-19
status: recipe
related: [single_instance_handoff_qlocalserver, forest_startup_hub_not_draggable]
---
# Publish the active ForestController as a module global so the single-instance handler can reach it

## What happened

A second forest launch (double-clicking the shortcut while the forest was
already running) dropped a stray standalone cell instead of revealing the
existing forest hub.  Fixed in v0.8.0a64.

## Root cause

`ring_main._handle_primary_message` handles the `spawn_cell` command that
arrives from a second launch.  In bare ring mode, `spawn_cell` correctly
creates a fresh `CellWindow`.  In forest mode, it should instead reveal the
existing hub — but `_handle_primary_message` had no reference to the live
`ForestController` and couldn't call `_visibility.show_hub()`.

The missing link was a module-level variable that `main()` populates after
`ForestController.start()` succeeds.

## Fix / recipe

Declare a module global in `ring_main.py`:

```python
# ring_main.py (v0.8.0a64)
_FOREST_CONTROLLER = None  # type: ignore[var-annotated]
```

Publish it in `main()` right after `_forest_controller.start()` succeeds:

```python
global _FOREST_CONTROLLER
_FOREST_CONTROLLER = _forest_controller
```

Read it in `_handle_primary_message` to gate the `spawn_cell` branch:

```python
if cmd == "spawn_cell":
    fc = _FOREST_CONTROLLER
    if fc is not None and getattr(fc, "forest_window", None) is not None:
        vis = getattr(fc, "_visibility", None)
        try:
            if vis is not None:
                vis.show_hub()
            else:
                w = fc.forest_window
                w.showNormal(); w.raise_(); w.activateWindow()
            _log("  spawn_cell (forest mode) → revealed existing forest hub")
        except Exception as exc:
            _log(f"  spawn_cell: reveal forest hub failed: {exc!r}")
        return
    # Bare ring mode: spawn a fresh standalone hex.
    ...
```

The `getattr` guards make it safe if the controller is partially initialised
(e.g. `start()` raised before assigning `forest_window`).

Implementation:
* `D:\Dev\ScripTree\scriptree\shell\ring_main.py`, `_FOREST_CONTROLLER` (~line 237).
* `D:\Dev\ScripTree\scriptree\shell\ring_main.py`, `main()`, forest-mode block (~line 757).
* `D:\Dev\ScripTree\scriptree\shell\ring_main.py`, `_handle_primary_message`, `spawn_cell` branch (~lines 413-429).

## How future-me detects it

Any time a subsystem that lives in the primary's event loop needs to be
reachable from the single-instance message handler (`_handle_primary_message`),
the cleanest pattern is:

1. Declare a module-level `_X = None` sentinel in `ring_main.py`.
2. Assign `global _X; _X = the_live_object` in `main()` after construction.
3. Read `_X` in `_handle_primary_message` with a `None` check.

Do NOT pass the controller through the `PrimaryServer.messageReceived`
lambda (lambda capture of a mutable would bind a stale reference).  The
module global is the right coordination point for "primary process state
visible to the message handler".
