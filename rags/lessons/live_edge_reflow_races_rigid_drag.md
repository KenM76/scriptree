---
topic: live_edge_reflow_races_rigid_drag_cascade
date: 2026-06-21
status: gotcha
related: [settle_rigid_slide_falls_back_to_engine_repack, full_fit_slot_selection_no_clamp, cell_positioning_central_tracker]
---
# The per-frame live-edge reflow raced the rigid drag cascade → fast-drag "left behind" + gap

## What happened (user-reported, fixed v0.8.0a77)

Stack cells under the forest, docked, then drag the forest QUICKLY to a screen
edge.  Members "relocate but sometimes get left behind", opening a gap and
sometimes overlapping neighbours; once it happens, moving the forest again
leaves the gapped cells behind.  User's read: "they move to where the forest is,
but the forest has already moved by the time they get there."

## Root cause — two systems moving the same members with different models

During a master drag, `CellWindow.moveEvent` ran TWO things each frame:

1. **The rigid cascade** (the correct one): shift every positioned member's
   WIDGET by the drag delta AND shift its stored `_members[mid]` home by the same
   delta.  Widget and stored home stay coupled.
2. **`_live_edge_reflow_or_fold`** (throttled ~50 ms): when a member goes
   off-screen, `group_layout.repack` picks a fresh on-screen slot and the member
   is moved there with an instant `m.move(new_tl)` — **but `_members[mid]` is NOT
   updated**, and the slot isn't reconciled.

So on a fast drag (cascade per-frame, reflow every 50 ms) the widget and the
stored home **diverged**: the reflow yanked the widget to a slot, the cascade
kept shifting the stale home, and they raced.  At drag-end the two disagreed → a
gap (and overlap); on the next drag the cascade shifted the (already-diverged)
home, so the member stayed "left behind".  The instant move avoided animation
lag, but the throttle-vs-per-frame mismatch + the un-synced `_members` was the
real race.

## Fix / recipe

Delete the per-frame reflow from the drag path.  Let members follow the master
RIGIDLY during the drag (widget == stored, clipping transiently at the edge),
and let the **drag-end settle** put everything back:

```python
# moveEvent master-drag block: REMOVE the per-frame call
#   self._live_edge_reflow_or_fold()   # <- raced the cascade; gone in a77
# (the method is left in place, marked deprecated/unused)
```

At drag-end, `mouseReleaseEvent` already calls `_settle_no_overlap`, which (a73)
falls back to the engine re-pack (`_compute_layout`) when the rigid block can't
slide on-screen as a unit.  Because the cascade kept the cluster COHERENT (no
reflow mangling), the settle either slides the clean stack on-screen or the
engine re-packs it — one plan-then-apply pass, no race.

Implementation: `scriptree/shell/cell_window.py` — removed the
`_live_edge_reflow_or_fold()` call in `moveEvent`; method kept but deprecated.

## How future-me detects it

NEVER have two code paths move the same cells on overlapping triggers with
different position models — especially a per-frame rigid translate plus a
throttled reactive relocate that doesn't update the same `_members` store.  One
authority moves cells during a gesture (the rigid cascade); the engine re-packs
at rest (drag-end / resolution-change).  A relocate that writes the widget but
not `_members` (or vice-versa) is a divergence/"left-behind" bug waiting to
happen.
