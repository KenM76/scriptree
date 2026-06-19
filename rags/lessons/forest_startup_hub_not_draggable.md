---
topic: forest_startup_hub_not_draggable
date: 2026-06-19
status: empirical
related: [rescue_cells_on_reveal, diagnostics_tagged_stderr_logs]
---
# Forest hub not draggable at startup until a manual hide/show — schedule activation one tick later

## What happened

User reported: "the forest hub won't move when I first launch ScripTree;
I have to hide it and show it again, then it drags fine."  Fixed (tentatively)
in v0.8.0a63.

## Root cause

**Best-guess, not confirmed under the headless test platform.**

The forest's startup show path (`ForestController.start`) was the ONLY reveal
path that never called `raise_()` + `activateWindow()` on the hub.  Every
subsequent reveal (`show_hub`, `_restore_descendants`) does.  On Windows, a
frameless `Qt.Tool` window shown without being activated can miss the first
drag gesture — the OS may not have committed the window to the foreground
input queue by the time the user attempts the drag.

The bug is NOT reproducible under the headless/offscreen Qt platform used by
the test suite, which makes it impossible to write a deterministic regression
test.  The `[forest_startup]` diagnostic log was added so the NEXT live run
can confirm or refute the theory: if the hub shows up as `isVisible=True,
isMinimized=False, isActive=False` in the log right after startup, the theory
is confirmed.

## Fix / recipe

Schedule `_finalize_hub_interactive` one event-loop tick after the initial
`show()` call:

```python
# forest_controller.py — ForestController.start  (v0.8.0a63)
self.forest_window.show()
# ...
try:
    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, self._finalize_hub_interactive)
except Exception as exc:
    _log(f"start: could not schedule hub finalize: {exc!r}")
```

`_finalize_hub_interactive` (on `ForestController`) runs after Qt has
processed the map event and calls:

```python
def _finalize_hub_interactive(self) -> None:
    try:
        w = self.forest_window
        if w is None or not w.isVisible() or w.isMinimized():
            _log("[forest_startup] _finalize_hub_interactive: hub not visible/not ready; skip")
            return
        w.raise_()
        w.activateWindow()
        _log(
            f"[forest_startup] _finalize_hub_interactive: "
            f"raised+activated hub  isActive={w.isActiveWindow()}"
        )
    except Exception as exc:
        _log(f"_finalize_hub_interactive: {exc!r}")
```

The guard `not w.isVisible() or w.isMinimized()` makes this a no-op in
taskbar-mode (hub starts minimised — we don't want to force-show it) and
tray-only mode (hub stays hidden).

Diagnostic log tags: `[forest_startup]`.  To diagnose a persistent failure,
enable verbose logging (Forest ▶ Debug ▶ Enable verbose logging), reproduce,
then read `%APPDATA%\ScripTree\logs\` and grep for `[forest_startup]`.

Implementation: `D:\Dev\ScripTree\scriptree\shell\forest_controller.py`,
`ForestController.start` (~line 572) and `_finalize_hub_interactive`.

## How future-me detects it

If a user reports "forest hub won't drag at startup", check:
1. Is `[forest_startup] _finalize_hub_interactive` in the log?  If not, the
   singleShot is not firing.
2. Does `isActive=False` appear in the log?  If yes, the raise+activate is
   not taking hold — investigate OS-level window-activation policy (Windows
   foreground lock, anti-focus-steal).

This is a "best-guess fix + diagnostics" pattern: write the tentative fix,
instrument it thoroughly, and let the next live run confirm it.  See also
the a56→a58 virtual-desktop saga for the same approach.
