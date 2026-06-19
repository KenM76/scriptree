---
topic: rescue_cells_on_reveal
date: 2026-06-19
status: recipe
related: [autohide_guard_own_modals, show_before_move_desktop_api]
---
# Rescue hidden cells back on-screen after every reveal — hub moves while cells are hidden

## What happened

User reported: "after the forest moves, when I reveal it from the taskbar
or tray, some cells are off-screen."  Hidden cells don't track the hub's
movement (the master-drag cascade only shifts members that are in
`_positioned` AND currently visible).  So while the hub is minimised/hidden,
any cell that was already at the edge of the screen can end up off-screen
once the hub is dragged to a new spot.  Fixed in v0.8.0a62.

## Root cause

`show_hub` and `_restore_descendants` call `cell.show()` for each tracked
descendant but never verify that the just-revealed cell's position is still
on-screen.  The cells keep their last recorded position.  If the hub moved
while they were hidden — via user drag, the `_follow_user_across_desktops`
logic, or a display-layout change — those recorded positions may now fall
outside every monitor's available area.

## Fix / recipe

After showing every tracked descendant, call
`ForestVisibilityManager._rescue_cells_on_screen(shown_list)` to clamp
each one back onto a visible screen.  This is the same helper
`screen_watcher.rescue_all_cells` uses, so the clamping contract is identical:

```python
def _rescue_cells_on_screen(self, cells: list[Any]) -> None:
    for cell in cells:
        try:
            raw = cell.pos()
            clamped = cell._clamp_to_screen(raw)
            if clamped != raw:
                cell.move(clamped)
                _log(
                    f"_rescue_cells_on_screen: cell "
                    f"{getattr(cell, '_id', '?')[:8]} "
                    f"({raw.x()},{raw.y()}) -> "
                    f"({clamped.x()},{clamped.y()})"
                )
        except Exception as exc:
            _log(f"_rescue_cells_on_screen: {exc!r}")
            continue
```

Call it in BOTH reveal paths:
* `show_hub` — after the descendant show + move loop, before clearing
  `_hidden_descendant_ids` (line ~683 of `forest_visibility.py`).
* `_restore_descendants` — at the end, after the post-show move loop
  (line ~861 of `forest_visibility.py`).

`CellWindow._clamp_to_screen` uses `QApplication.screenAt(pos)` and falls
back to the primary screen for a position that maps to no screen — so it is
safe even on multi-monitor setups.

Implementation: `D:\Dev\ScripTree\scriptree\shell\forest_visibility.py`,
`_rescue_cells_on_screen` (lines ~870-901), called from `show_hub` (~683)
and `_restore_descendants` (~861).

## How future-me detects it

Any new "reveal" path (show hub, taskbar restore, tray click) that calls
`cell.show()` for a list of previously-hidden cells MUST call
`_rescue_cells_on_screen` afterwards.  The symptom of missing it: cells
appear off-screen or partially clipped after a reveal, especially when the
hub was moved while the forest was hidden.
