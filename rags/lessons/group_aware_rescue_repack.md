---
topic: group_aware_rescue_repack
date: 2026-06-21
status: recipe
related: [cell_positioning_central_tracker, hub_onscreen_clamp_programmatic,
          qt_screen_change_signal_debounce, rescue_cells_on_reveal]
---
# Resolution-change rescue must be GROUP-AWARE — clamp master then repack members (a72)

## What happened (user-reported)

After a monitor resolution change (or unplugging a secondary monitor), multiple
cells from the same ring ended up stacked in the same corner. The pre-a72
`rescue_all_cells` clamped EACH cell's top-left independently — master AND
members — so a ring of five cells could get five different "nearest screen
edge" positions, producing a stack at the corner rather than a valid honeycomb
arrangement.

A second issue: if the master was clamped first by the loop and then a member
was clamped to the same edge, the member sat on the master's position with no
collision check.

## Root cause

Pre-a72 `screen_watcher.rescue_all_cells` (`screen_watcher.py`) treated every
cell identically: walk `CellRegistry.instance().all()`, clamp each cell's
top-left via `_clamp_to_screen`. No group/member distinction. The clamp for
a master moved it but didn't repack its members, and the clamp for members
ignored the master's new position.

## Fix / recipe (a72): GROUP-AWARE rescue

```python
def rescue_all_cells() -> int:
    """Bring every cell back onto a visible work area — GROUP-AWARE."""
    ...
    for cell in cells:
        # Detect role: master (hub or ring) vs. member vs. standalone
        is_master = (
            getattr(cell, "role", None) == "master"
            or getattr(cell, "_is_forest_master", False)
        )
        has_master = getattr(cell, "_group_master_id", None) is not None

        if is_master:
            # 1. Clamp the master on-screen first.
            if _clamp(cell):
                moved += 1
            # 2. Route its members through the layout engine.
            #    _repack_members(instant=True) -> _compute_layout ->
            #    find_free_slot + is_on_screen + slot_world_pos.
            #    Assigns each member a FREE, ON-SCREEN, NON-OVERLAPPING
            #    honeycomb slot around the master's now-clamped position.
            try:
                cell._repack_members(instant=True)
            except Exception as exc:
                _log(f"rescue_all_cells: repack {cell._id[:8]} raised {exc!r}")

        elif not has_master:
            # True standalone (no group master) — clamp it.
            if _clamp(cell):
                moved += 1

        # else: member of a group — its master's repack above places it
        # on a free on-screen slot; don't clamp it independently here
        # (that would fight the engine).
```

Key points:
- The loop no longer clamps group members at all. The master's `_repack_members`
  already handles them through `_compute_layout`, which assigns free,
  on-screen, non-colliding slots.
- The master must be clamped BEFORE `_repack_members` so that
  `screenAt(master.pos())` resolves to a valid screen inside `_compute_layout`.
  An off-screen master causes `_compute_layout` to fall back to the primary
  screen and computes slots relative to the wrong origin.
- True standalones (no `_group_master_id`) still get a simple clamp — they
  have no members to repack.

Implementation: `scriptree/shell/screen_watcher.py` — `rescue_all_cells`
function (~lines 62-140).

## Interaction with the screen-change debounce

`rescue_all_cells` is called from the 200 ms debounced
`app._screen_rescue_timer` callback, which fires after Qt's signal storm
settles. The debounce is documented in
`rags/lessons/qt_screen_change_signal_debounce.md`. The group-awareness
fix lives entirely inside `rescue_all_cells`; the debounce mechanism is
unchanged.

## How future-me detects it

Symptom: after a resolution change or monitor unplug, several cells of the
same ring are stacked in the same corner — typically the nearest screen edge.
The members are touching or overlapping rather than arranged in a honeycomb.

Also triggered by: Forest right-click → "Bring all cells back on-screen"
(which calls `rescue_all_cells` directly from `forest_controller._on_rescue_offscreen`).
If members stack after a manual rescue, it's the same root cause.

To confirm: check `[screen_watcher]` log entries. A pre-a72 rescue would
log `moved N` where N == (masters + members); a post-a72 rescue logs each
master clamp separately and does not log individual member moves (they're
handled silently by `_repack_members`).
