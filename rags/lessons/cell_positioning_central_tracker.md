---
topic: cell_positioning_central_tracker
date: 2026-06-21
status: recipe
related: [collapse_expand_route_through_layout_engine, rescue_cells_on_reveal,
          hub_onscreen_clamp_programmatic, group_aware_rescue_repack,
          virtual_desktop_follow_debounce]
---
# Cell-positioning central tracker — every reveal path must route through the engine

## What happened (user-reported)

After repeated sessions of cells appearing off-screen, stacked on the forest
hub, or left behind on a different virtual desktop, the user asked: *"Isn't
there a central tracker for knowing where cells are? the forest should know
where there is open space and a side of a docked cell that it can attach to."*

The answer: YES, the tracker exists and is fully functional — but several
reveal/restore/rescue paths were bypassing it and writing positions directly.
The v0.8.0a68-a72 sweep identified and plugged each bypass.

## The geometry engine (source of truth)

Three files form the positioning stack:

| File | Role |
|---|---|
| `scriptree/shell/tiling.py` | Geometry primitives: honeycomb slot offsets, polygon SAT collision. |
| `scriptree/shell/layout.py` | Slot planner: `find_free_slot`, `nearest_free_slot`, `slot_world_pos`, `is_on_screen`. `find_free_slot` enforces: not already taken + not the back-toward-parent slot + `is_on_screen` + global polygon-collision against every other placed cell in the workspace. |
| `scriptree/shell/cell_window.py` | `CellWindow._compute_layout` (line ~4372) — the single slot authority. Walks every `_members` entry, assigns a FREE, ON-SCREEN, NON-COLLIDING honeycomb slot via the planner (line ~4421), **forbids the master's own centre as a collider** so cells always attach to a side rather than piling on the hub (line ~4481 in the pass that excludes the master position from the occupied set). Writes the result into `self._members[mid]`. `_repack_members(fixed=None)` delegates straight to it. |

## The invariant

**Every reveal, restore, and rescue path that writes a cell position must
route through the engine (`_compute_layout` / `_repack_members` /
`layout.find_free_slot` + `is_on_screen` + `slot_world_pos`). A path that
replays a stored coordinate with no free-slot, on-screen, or collision check
is a latent overlap/off-screen bug.**

## Known reveal paths and their engine hooks (a68–a72)

| Path | Engine hook | Notes |
|---|---|---|
| **Startup / spawn** | `_repack_members()` → `_compute_layout` | Always correct — this was the reference implementation. |
| **Collapse/expand** (`_start_expand`) | `_compute_layout(instant=True)` (a68) | Before a68, `_start_expand` replayed stored absolute coordinates, producing off-screen and stacked cells. See `rags/lessons/collapse_expand_relative_offsets.md`. |
| **Auto-hide reveal** (`forest_visibility._rescue_cells_on_screen`) | `CellWindow._clamp_to_screen` per cell | Clamps positions but does NOT re-slot. A cell-to-cell overlap that existed before hide is preserved after reveal. Consider routing through `_repack_members` if overlap proves a problem. |
| **Resolution-change rescue** (`screen_watcher.rescue_all_cells`) | Clamp master then `_repack_members(instant=True)` for each master (a72) | GROUP-AWARE since a72. See `rags/lessons/group_aware_rescue_repack.md`. |
| **Hub programmatic restore** (`show_hub`, `forest_controller.start`) | `_clamp_hub` / `_clamp_to_screen` on hub position (a69) | Hub itself is clamped; members follow via `_rescue_cells_on_screen` afterward. See `rags/lessons/hub_onscreen_clamp_programmatic.md`. |

## Pre-engine call requirement (load-bearing ordering rule)

Before calling `_compute_layout`, the HUB must already be on-screen:

```python
# Clamp the hub FIRST so screenAt(self.pos()) resolves to a real screen.
# An off-screen origin poisons every computed slot.
self.move(self._clamp_to_screen(self.pos()))

# Clear non-floating members' _slot so Pass 1 re-derives around current hub position.
for m in members:
    if not getattr(m, "_floating_intent", False):
        m._slot = None

# Engine assigns free, on-screen, non-overlapping slots.
self._compute_layout(instant=True)
```

If `_compute_layout` is called while the hub is off-screen, `screenAt(self.pos())`
returns `None`, the fallback screen is the primary, and every computed slot is
relative to the primary origin — potentially on a different monitor from where
the user expects the cells.

## How future-me detects it

Any code path that sets `member.move(QPoint(...))` or `member.move(stored_pos)`
without going through `_compute_layout` / `_repack_members` / `layout.find_free_slot`
is suspicious. Symptoms: cells appear stacked on the hub, overlapping each other,
or off-screen after a layout-changing event (collapse/expand, restore, resolution
change, virtual desktop switch).

If a new reveal path is added (e.g. taskbar restore path changes, or a new
"restore all cells" action is added), verify it satisfies:
1. Hub is clamped on-screen before cell placement begins.
2. Cell positions are derived from `_compute_layout`/`_repack_members` (for
   members) or `_clamp_to_screen` (for standalones).
3. `_rescue_cells_on_screen` is called after `cell.show()` to catch any residual
   stale positions.
