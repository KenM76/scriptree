---
topic: v3-architecture
date: 2026-05-23
status: bug
related: [group_uniform_size_and_repack, move_to_cascades_dock_children]
---
# Settle a docked ring per-member, not as a rigid group

## What happened

Bug 3 (v0.8.0a1): docking a ring to another ring sometimes pushed
the docked ring off the snap slot. Specifically when one of the
ring's members overlapped a member of the destination ring, the
overlap-resolver shifted the whole docked ring as a rigid block to
clear the overlap — moving the master off the snap slot it had just
landed on.

## Root cause

The legacy `_settle_no_overlap` helper computed one delta to clear
all overlaps and shifted the whole master + positioned set by that
delta. Worked for a free-floating master settling on screen, but
wrong for a master that's already docked: the dock slot is fixed,
only the overlapping member should move.

## Fix / recipe

New helper `_relocate_overlapping_members_individually` at
`scriptree/shell/cell_window.py:8728` that:

1. Identifies which specific members overlap something (peer rings,
   the forest, other cells).
2. Re-slots each overlapping member via
   `layout.nearest_free_slot(master, exclude_ids=...)` — finds the
   nearest legal slot that doesn't collide.
3. Master stays at the snap-committed position.

The drag-end / snap-commit code chooses between the two strategies:

```python
if self.role == "master" and self._dock_partner_id is not None:
    # Docked ring — fix the master, re-slot offending members
    self._relocate_overlapping_members_individually(...)
else:
    # Free-floating — original rigid settle is fine
    self._settle_no_overlap(...)
```

## Caveat / TODO

Current implementation only searches slots around the ring's OWN
master. If every slot around this master is taken, the offending
member is auto-hidden (legacy fold-away). A cross-master fallback —
"if no slot here, try a slot near a different ring that's nearby" —
is deferred to a later phase. Users have not hit it yet; once they
do, the helper needs the cross-master search.

## How future-me detects it

* Symptom: ring docks visually correctly, then jumps a slot to the
  side before settling. Old rigid settle ran instead of the new
  per-member helper. Check the if-branch around the drag-end snap
  commit path.
* "My ring docks but a member auto-hides instead of slotting" — the
  per-member helper is running but cross-master fallback isn't
  implemented; user has hit the deferred case.
