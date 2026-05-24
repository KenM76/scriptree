---
topic: v3-architecture
date: 2026-05-23
status: pattern
related: [link_dock_graph_split, fresh_ring_not_in_forest_positioned, per_member_relocation_vs_rigid_settle]
---
# `CellWindow.move_to` cascades dock children recursively

## What happened

Bug 4 (v0.8.0a1): docking a cell to a forest-linked cell moved the
master correctly but did not cascade to anything docked on the
master's other edges. Chains of docked cells broke when any link in
the chain moved.

## Root cause

`move_to` only moved the receiver. Dock children (the cells listed
in `_dock_children_by_edge`) had no follow-on movement, so any chain
A → B → C where A moves would only move A; B and C stayed put.

## Fix / recipe

`CellWindow.move_to` now reads the delta and applies it to every
cell in `_dock_children_by_edge`. Each child's own `move_to` then
re-cascades to its own dock children — chains follow naturally
without explicit recursion in the source.

```python
def move_to(self, new_pos: QPoint) -> None:
    if _GROUP_MOVE_IN_PROGRESS.get(self._id):
        return                                  # guard against re-entry
    old_pos = self.pos()
    dx = new_pos.x() - old_pos.x()
    dy = new_pos.y() - old_pos.y()
    if dx == 0 and dy == 0:
        return

    _GROUP_MOVE_IN_PROGRESS[self._id] = True
    try:
        self.move(new_pos)
        # Cascade to docked neighbours
        for edge, child_ids in self._dock_children_by_edge.items():
            for cid in list(child_ids):
                child = registry.get(cid)
                if child is None:
                    continue
                child.move_to(QPoint(child.x() + dx, child.y() + dy))
    finally:
        _GROUP_MOVE_IN_PROGRESS.pop(self._id, None)
```

The `_GROUP_MOVE_IN_PROGRESS` guard prevents re-entry when two cells
are mutually docked (A's child set contains B, B's child set contains
A — possible after certain dock manipulations).

## Call sites

* `snap_engine.detach_drag` — applied at snap-commit time, so the
  whole docked chain lands at the new position together.
* `dock_with` — when a new dock relation forms, the joining cell's
  move into place cascades to whatever it's already docked to.

## How future-me detects it

* Symptom: drag a cell that has things docked to it, only the
  primary cell moves, the docked ones stay. Most likely a caller
  used `self.move(...)` directly instead of `move_to`. Audit for
  direct `.move(QPoint)` calls.
* Infinite recursion / stack overflow on a dock chain: the re-entry
  guard isn't firing — verify `_GROUP_MOVE_IN_PROGRESS` is keyed on
  cell ID and not getting cleared too early.
