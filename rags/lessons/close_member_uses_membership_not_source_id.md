---
topic: v3-architecture
date: 2026-05-07
status: bug
related: [cell_window]
---
# `_close_this` must check membership, not `source_a_id` / `source_b_id`

## Symptom

User: "when I closed the first cell that I opened it ended up
closing the ring even though there were two other cells attached."

Reproducer:

1. Spawn cells A and B.  Drag B near A → master spawns; A and B
   become members.  ``master.source_a_id == A._id``,
   ``master.source_b_id == B._id``.
2. Spawn cell C.  Drag C near B → Case 2 path: C joins the master
   group.  ``master._members`` is now ``{A, B, C}`` (3 members).
3. Right-click A → Close this cell.

**Expected:** A closes, master + B + C remain (2 members → still
above the quorum threshold of 2).

**Actual (bug):** master closes too — even though B and C are
still on screen and still part of the cluster.

## Root cause

The old ``_close_this``:

```python
masters_to_close = [
    m for m in registry.masters()
    if m.source_a_id == self._id or m.source_b_id == self._id
]
for master in masters_to_close:
    registry.masterDespawned.emit(master._id)
    master.close()
```

``source_a_id`` / ``source_b_id`` record the **originating pair**
that first triggered ``_try_spawn_master`` — they're frozen at
master-spawn time and never updated when later members join via
Case 2/3/4.  They are NOT the current cluster.  So closing either
of those two original seed cells unconditionally tore the master
down, regardless of how many members had joined since.

## Fix

Replace the source-ID cascade with a membership-aware path:

```python
def _close_this(self):
    if self.role != "master" and self._group_master_id is not None:
        master = registry.get(self._group_master_id)
        if master is not None and master.role == "master":
            master._members.pop(self._id, None)
            master._positioned.discard(self._id)
            master._dock_partners.discard(self._id)
            master._auto_hidden.discard(self._id)
            master._repack_members()
            _check_master_validity(master, registry)
    if self.role == "master":
        registry.masterDespawned.emit(self._id)
    self.close()
    # quit logic...
```

``_check_master_validity`` already enforces the right rule:

> Close the master only when ``len(master._members) < 2``.

So the master survives as long as ≥2 members are still in the
cluster.  Repacking after the removal fills the gap the closed
member left so the surviving members move onto the freed slot.

## How future-me detects it

If you ever find yourself reading ``source_a_id`` /
``source_b_id`` to decide cluster membership, stop.  Those
fields are **identity bookkeeping** for the master's
deterministic ID — useful for the masterSpawned signal payload
and that's about it.  Use ``_members`` (the authoritative dict
of current members) for cluster operations.

## Test

`tests/test_load_into_empty_cell.py::test_close_first_seed_member_keeps_master_with_other_members`
pins the regression — closing the original ``source_a_id`` cell
of a 3-member group leaves master + 2 other members alive.
