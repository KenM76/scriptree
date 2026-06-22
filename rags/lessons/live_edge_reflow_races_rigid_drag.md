---
topic: live_edge_reflow_is_load_bearing_dont_remove
date: 2026-06-22
status: gotcha
related: [settle_rigid_slide_falls_back_to_engine_repack, full_fit_slot_selection_no_clamp, cell_positioning_central_tracker]
---
# The live-edge reflow races the rigid drag cascade — but it's LOAD-BEARING; fix the divergence in-place, do NOT remove it

## The tension (a77 removed it → a78 reverted)

During a master drag, `CellWindow.moveEvent` runs two movers:

1. **Rigid cascade** (per-frame): shifts each positioned member's WIDGET and its
   stored `_members[mid]` home by the drag delta — coupled.
2. **`_live_edge_reflow_or_fold`** (throttled ~50ms): relocates off-screen
   members to free on-screen slots (`group_layout.repack`) via instant `move()`.

**The race (real):** the reflow relocates the widget but does NOT update
`_members[mid]`, so on a FAST drag widget and stored home diverge → at drag-end
they disagree → gap / overlap / "left behind on the next move" (user-reported).

**Why you must NOT just delete the reflow (v0.8.0a77 did — reverted in a78):**
the reflow is what lets you drag the forest INTO A CORNER while keeping it
there.  It relocates the would-be-off-screen members to on-screen slots AROUND
the cornered forest, so the forest stays put.  Remove it and members merely clip
during the drag; then the drag-end `_settle_no_overlap` (rigid block) can't fit
the whole cluster, so it shoves the ENTIRE cluster — forest included — back onto
the screen.  User symptom after a77: "I can't drag the forest to a corner if
there are cells that will go off-screen; it keeps all the cells docked where
they are and pushes everything back onto the screen."  So a78 reverted a77 and
restored the reflow.

## The CORRECT fix (not yet implemented — do this, not removal)

Keep the reflow, but eliminate the divergence: when the reflow relocates a
member, update its stored home (and slot) so the rigid cascade and the reflow
agree on where the member is.

```python
# in _live_edge_reflow_or_fold, after m.move(new_x, new_y):
self._members[m._id] = QPoint(new_x, new_y)   # keep widget == stored home
# (and reconcile m._slot with the slot repack assigned, so _compute_layout's
#  taken_slots stays correct)
```

With widget and `_members` coupled, the per-frame rigid cascade then shifts both
together, the fast-drag divergence disappears, AND the corner-relocate behaviour
is preserved.  Verify against both: (a) fast drag to an edge keeps members
bonded with no gap/left-behind, and (b) drag to a corner keeps the FOREST in the
corner with members relocated on-screen around it.

## How future-me detects it

Two movers on the same cells during a drag is inherently fragile — but here the
reflow is REQUIRED for the corner-stay behaviour, so the answer is to make the
two agree (sync `_members` on relocate), NOT to delete one.  Removing the reflow
trades the fast-drag bug for a worse corner-drag regression.
