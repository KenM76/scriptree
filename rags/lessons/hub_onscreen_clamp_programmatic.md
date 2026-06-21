---
topic: hub_onscreen_clamp_programmatic
date: 2026-06-21
status: gotcha
related: [cell_positioning_central_tracker, rescue_cells_on_reveal,
          collapse_expand_route_through_layout_engine]
---
# Programmatic hub moves must clamp on-screen — live drag did, stale restore didn't (a69)

## What happened (user-reported)

The forest "disappeared" — the user could see no hub and no cells on any
monitor. The forest was running (tray icon present) but the hub was stranded
off-screen at a stale coordinate: a position saved when a monitor with that
geometry was connected, now orphaned after an unplugged monitor or resolution
change.

The `_clamp_to_screen` helper existed and was already called every time the
user interactively dragged the hub — so dragging never stranded it. But
two programmatic move paths did not clamp:

1. `ForestVisibilityManager.show_hub` — the taskbar and tray-only restore
   branches read `self._last_hub_position` and called `w.move(pos)` directly.
2. `ForestController.start` — the `window_position` restore branch called
   `self.forest_window.move(position)` directly.

A stale `window_position` in the `.scriptreeforest` file (monitor unplugged,
display resolution shrank) reached those moves unchecked.

## Root cause

`CellWindow._clamp_to_screen(raw_pos: QPoint) -> QPoint`
(`cell_window.py:9660`) was wired into the drag-end `mouseMoveEvent` path
but not into the programmatic move paths. Programmatic paths trusted the
stored coordinate unconditionally.

## Fix / recipe (a69)

### In `ForestVisibilityManager` — add `_clamp_hub` helper

```python
def _clamp_hub(self, pos: "QPoint") -> "QPoint":
    """Clamp a prospective hub top-left onto a visible screen.

    Reuses the hub's own CellWindow._clamp_to_screen.
    Degrades to the raw point if the hub doesn't expose it.
    """
    w = self._forest_window
    try:
        if w is not None and hasattr(w, "_clamp_to_screen"):
            return w._clamp_to_screen(pos)
    except Exception as exc:
        _log(f"_clamp_hub: {exc!r}")
    return pos
```

Both restore branches in `show_hub` now call `_clamp_hub`:

```python
# Taskbar branch (minimised restore):
w.move(self._clamp_hub(self._last_hub_position))   # a69

# Tray-only branch (hidden restore):
w.move(self._clamp_hub(self._last_hub_position))   # a69
```

Implementation: `scriptree/shell/forest_visibility.py` — `_clamp_hub`
method (~line 550), and both `w.move(...)` calls in `show_hub` (~lines 647
and 676).

### In `ForestController.start`

```python
# a69: clamp the restored/derived position on-screen so a forest
# saved at a coordinate that no longer fits the current display
# (resolution shrank, monitor unplugged) can't start the hub
# off-screen -- the "forest disappeared" bug.
try:
    position = self.forest_window._clamp_to_screen(position)
except Exception as exc:
    _log(f"start: hub position clamp raised {exc!r}")
self.forest_window.move(position)
```

Implementation: `scriptree/shell/forest_controller.py` — `start` method
(~line 469).

## The design rule

**`CellWindow._clamp_to_screen` must be called at EVERY site that moves the
hub programmatically.** The sites are:

| Call site | Where |
|---|---|
| Drag-end `mouseMoveEvent` (interactive) | `cell_window.py` |
| `show_hub` taskbar branch | `forest_visibility.py` |
| `show_hub` tray-only branch | `forest_visibility.py` |
| `ForestController.start` window-position restore | `forest_controller.py` |

If a new programmatic move path is added (e.g. a "Centre on screen" action,
a monitor-follow feature), it must also clamp.

## How future-me detects it

Symptom: `[forest_visibility] show_hub` logged but no window visible on
any monitor; or `[forest_controller] start` completes but no hub appears.
The hub is there — `rescue_all_cells()` from Forest right-click → "Bring
all cells back on-screen" will clamp it back. Root cause: a programmatic
`w.move(pos)` that used an unclamped stored coordinate.
