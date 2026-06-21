---
topic: collapse_expand_route_through_layout_engine
date: 2026-06-21
status: gotcha
related: [rescue_cells_on_reveal, show_before_move_desktop_api]
supersedes_note: "v0.8.0a67 tried a relative-offset restore; it STILL overlapped. v0.8.0a68 routes through the layout engine — that is the real fix."
---
# Forest collapse/expand must re-bloom THROUGH the layout engine (`_compute_layout`), not replay remembered coordinates

## What happened (user-reported)

Single-click COLLAPSE of the forest hex, drag the forest, single-click EXPAND
("slide the cells out") put cells in the wrong place:
- **off-screen** when the forest had moved to an edge, and
- **stacked on top of the forest icon** / on each other.

The user's diagnosis was exactly right: *"Isn't there a central tracker for
knowing where cells are? the forest should know where there is open space and a
side of a docked cell that it can attach to."*

## Root cause

`CellWindow._start_expand` restored each member to a remembered ABSOLUTE
coordinate (`self._members[m._id]`, captured at collapse) with **no free-slot,
on-screen, or collision check**. So any stale/duplicate/zero-offset stored
coordinate produced overlap, and a moved forest produced off-screen cells.

v0.8.0a67's intermediate attempt (record each member's offset-from-master at
collapse, restore `master.pos() + offset`, clamp on-screen) FIXED off-screen but
**still overlapped** — because preserved relative offsets still stack when
offsets are small/shared, and it never consulted the free-slot engine. Replaying
a coordinate is the wrong model.

## The central tracker DOES exist — use it

- `tiling.py` — geometry source of truth (slot offsets, polygon SAT collision).
- `layout.py` — the slot PLANNER: `find_free_slot` / `nearest_free_slot`
  (both apply: not-taken + not-back-toward-parent + `is_on_screen` + global
  polygon-collision), `slot_world_pos`.
- `CellWindow._compute_layout` (cell_window.py ~4360) — the single authority that
  walks every member, assigns a FREE, ON-SCREEN, NON-COLLIDING honeycomb slot via
  the planner, **forbids the master's own centre as a collider** (~4481 — "attach
  to a side, never on the forest icon"), and writes the result into
  `self._members[mid]`. `_repack_members(fixed=None)` delegates straight to it.
  Startup and spawn already use this; collapse/expand did not.

## Fix / recipe (v0.8.0a68)

In `_start_expand`, before revealing members, route placement through the engine:

```python
# 1. Clamp the HUB on-screen first, so _compute_layout's screenAt(self.pos())
#    resolves to a real screen (an off-screen hub computes every slot off a bad origin).
self.move(self._clamp_to_screen(self.pos()))
# 2. Clear each non-floating member's _slot so Pass 1 re-derives a fresh slot
#    around the hub's CURRENT position (floating/user-dragged members keep their pos).
for m in members:
    if not getattr(m, "_floating_intent", False):
        m._slot = None
# 3. Engine assigns free, on-screen, non-overlapping slots and writes _members[mid].
self._compute_layout(instant=True)
# 4. Bloom: per leaf member, move to hub centre, setVisible(True), animate to
#    self._members[m._id] (engine slot, re-clamped for safety). Nested-ring
#    sub-masters are dropped onto their engine slot FIRST, then recursed, so their
#    children bloom around the ring's correct on-screen slot (not the hub centre
#    mid-animation).
```

Two ordering rules that are load-bearing:
- **Clamp the hub BEFORE `_compute_layout`** — it reads `screenAt(self.pos())` to
  pick the screen; an off-screen origin poisons every slot.
- **Place a nested ring at its engine slot BEFORE recursing into its expand** —
  otherwise the ring is at the hub centre mid-bloom and its children lay out
  around the wrong point.

The a67 offset machinery (`_collapse_offsets`, `_expand_target_for`) was removed.

Implementation: `scriptree/shell/cell_window.py` — `_start_expand` (the engine
pre-pass + leaf/sub-master split).

## How future-me detects it

ANY reveal/restore/rebloom path that writes a cell position must go through the
engine (`_compute_layout` / `_repack_members` / `layout.find_free_slot` +
`is_on_screen` + `slot_world_pos`), never replay a stored coordinate. The reveal
paths and their engine hooks:
- collapse/expand: `_start_expand` -> `_compute_layout` (a68);
- auto-hide visibility reveal: `forest_visibility._rescue_cells_on_screen` (a62)
  — note this only CLAMPS; consider routing it through `_repack_members` too;
- resolution-change: `screen_watcher.rescue_all_cells` — currently per-cell clamp
  only (can stack); should also route masters through `_repack_members`.
A coordinate replay with no free-slot/on-screen/collision check is a latent
overlap/off-screen bug.
