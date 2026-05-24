---
topic: v3-architecture
date: 2026-05-23
status: pattern
related: [close_member_uses_membership_not_source_id, ring_dirty_membership_only, move_to_cascades_dock_children, fresh_ring_not_in_forest_positioned]
---
# v0.8.0 split: `_link_parent_id` (group graph) vs `_dock_partner_id` (spatial graph)

## What happened

v0.6.x conflated two independent relationships on a single field
(`_group_master_id` doubled as both "I'm a member of this group" and
"I'm spatially adjacent to this thing"). Once the forest got its own
collapse-cascade and rings began docking to forest cells, the
ambiguity bit: cells in a ring lost their forest link when the ring
docked elsewhere; collapsing the forest didn't reach cells inside a
ring; a dragged-off cell still "belonged" to its old master.

v0.8.0 P1-P3 splits the two graphs explicitly.

## The two graphs

| Field | Graph | What it means |
|---|---|---|
| `_link_parent_id` | **Group graph** — forest → rings → cells | Logical membership. A cell linked to a ring belongs to that ring; the ring linked to the forest belongs to the forest. Mirror of the master's `_members` dict from the member side. |
| `_dock_partner_id` + `_dock_edge` + `_dock_children_by_edge` | **Dock graph** — spatial edge adjacency | Where I'm geometrically touching the next thing. Independent of group membership. A standalone cell docked to a ring's edge has a dock partner but no link parent. |

**v0.8.0 spec rule**: a cell is ALWAYS linked to either the forest or
a ring — never link-orphaned. (Standalone cells get a forest link.)
Dock is optional and orthogonal.

## Phases as they landed

* **P1 — mirror writes** (`cell_window.py`): every assignment to
  `_group_master_id` is mirrored to `_link_parent_id`. Existing call
  sites continue to work; new code reads `_link_parent_id`.
* **P2 — link-driven cascade** (`cell_window.py:6113`): ring/forest
  drag walks `_link_parent_id` to find children to move, not
  `_dock_partners`. This is what lets a forest collapse propagate
  down through rings into cells.
* **P3 — atomic dock writes** (`_try_spawn_master` cases): when a
  cell docks to a ring or a ring docks to the forest, the dock pointer
  + dock edge + dock children entry are written atomically alongside
  the link assignment, never partially.

## Invariants

`scriptree/shell/link_dock_audit.py` defines five invariants L1-L5
checked at idle:

- **L1**: every non-forest cell has a non-null `_link_parent_id`.
- **L2**: `_link_parent_id` resolves to a master that lists this cell
  in its `_members`.
- **L3**: `_dock_partner_id` (if non-null) resolves to a master, and
  the partner has this cell's id in `_dock_children_by_edge[edge]`.
- **L4**: `_dock_edge` is in `{N, NE, SE, S, SW, NW}` (flat-top hex)
  iff `_dock_partner_id` is set.
- **L5**: no cell is both a `_link_parent` AND a `_dock_partner` of
  the same other cell (would indicate a graph collapse bug).

## Fix / recipe

When adding any new operation that touches cluster state, decide
explicitly which graph it operates on:

```python
# Wrong (v0.6.x conflation):
master._group_master_id = forest._id   # Means... what? Link? Dock?

# Right (v0.8.0):
cell._link_parent_id = ring_master._id        # Group membership
cell._dock_partner_id = standalone_cell._id   # Spatial adjacency
cell._dock_edge = "NE"
standalone_cell._dock_children_by_edge.setdefault("SW", set()).add(cell._id)
```

For movement: use `_link_parent_id` for cascade ("everyone in my
group follows me"). Use `_dock_partner_id` + `_dock_children_by_edge`
for adjacency cascade ("everyone touching my edge follows me").
Both can apply — they're additive, not alternatives.

## How future-me detects it

* "Why did this cell stop belonging to the forest when X happened?"
  — check whether the operation cleared `_link_parent_id` when it
  meant to clear `_dock_partner_id` (or vice versa).
* "Why is the audit logging L1 violations?" — a new code path is
  setting `_link_parent_id = None` on a non-forest cell. Trace back
  to the assignment site.
* If you find yourself writing `_group_master_id = ...` in new code,
  stop — write both fields (mirror) or use the appropriate one.
