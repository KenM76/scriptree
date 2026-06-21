---
topic: settle_rigid_slide_falls_back_to_engine_repack
date: 2026-06-21
status: gotcha
related: [cell_positioning_central_tracker, collapse_expand_route_through_layout_engine]
---
# Drag-end settle is a RIGID slide — it can't re-arrange a cluster; fall back to the engine re-pack at a corner

## What happened (user-reported, fixed v0.8.0a73)

After the earlier on-screen fixes (a68/a69/a72) the user reported cells still
**overlapping and sometimes undocking specifically when the forest is dragged
into a CORNER**, and gave the key architectural diagnosis: *"The tracker should
always know where cells are, and when it moves them it should plan all cells'
positions before expanding them out... It should know where everything is going
to go ahead of doing the action."*

## Root cause — two placement strategies, the weaker one wins at a corner

There are TWO drag-end placement strategies in `cell_window.py`:

1. `_settle_no_overlap` (~9721) — a **rigid block slide**.  It builds the
   subject set (master + every positioned member at their CURRENT positions) and
   spiral-searches for ONE `(dx, dy)` translation that puts the WHOLE block fully
   on-screen and non-overlapping.  It can only SLIDE the cluster as a unit; it
   **cannot RE-ARRANGE** members into different slots.

2. `_compute_layout` (~4360, via `_repack_members`) — the **engine re-pack**.
   It plans EVERY member's free, on-screen, non-overlapping honeycomb slot up
   front (Pass 1, collision- + on-screen-aware, forbids the master centre), then
   applies them (Pass 2).  This is the "knows where everything goes before
   placing it" planner.

Drag-end calls `_settle_no_overlap` (mouseReleaseEvent ~6977).  The engine
re-pack at drag-end had been DISABLED ("v0.8.0 P4") on the theory that cells
"shouldn't move after I placed them."  So at a CORNER, where the rigid block
**cannot fit on-screen as one unit**, the spiral search returns `best is None`
and the old code just logged and **left the overlap** — cells stranded
overlapping / partly off-screen, which downstream reads as "undocked."

## Fix / recipe (a73)

When the rigid slide fails, fall back to the engine — try-to-preserve, re-plan
when you can't:

```python
# _settle_no_overlap, when best is None:
if self.role == "master" and self._members:
    for mid in list(self._members):          # clear slots so Pass 1 re-derives
        mm = registry.get(mid)
        if mm is not None and not getattr(mm, "_floating_intent", False):
            mm._slot = None
    self._compute_layout(instant=True)        # plan all slots, then apply
```

Net behaviour:
- Rigid slide SUCCEEDS (cluster fits somewhere) -> use it, arrangement preserved
  (the P4 intent).
- Rigid slide FAILS (corner; block can't fit) -> engine re-pack re-arranges
  members into free on-screen slots around the master (the user's "plan
  everything, then place" intent).

Must clear `_slot` first: `_compute_layout` only (re)assigns a member whose
`_slot is None`; after a rigid drag members keep their slot, so without the clear
the re-pack is a no-op.  Floating (user-dragged-out) members are exempted.

## How future-me detects it

A "rigid translate the whole group" placement (one `(dx, dy)` for all) is
fundamentally weaker than the slot engine: it can keep a cluster together but
cannot fit it into a tight/corner region.  Any settle/placement that must hold
the "never overlap, never off-screen" invariant under arbitrary master positions
must be able to fall back to `_compute_layout` (plan-all-then-apply).  See
[[cell_positioning_central_tracker]] for the canonical "route placement through
the engine, never replay a coordinate" rule.
