---
topic: v3-architecture
date: 2026-05-23
status: bug
related: [link_dock_graph_split, move_to_cascades_dock_children]
---
# Don't add a fresh ring to `forest._positioned` — link it, but not yet positioned

## What happened

Bug 7 (v0.8.0a1), user trigger description (verbatim worth keeping):
"the ring still drags when the forest drags but only under this
specific condition: I drag a cell away from the group, then I drag
another cell from the group to dock with it and form a ring."

A freshly-spawned ring sat at an arbitrary on-screen position and
had no dock path back to the forest. But when the user dragged the
forest, the ring trailed along, even though it visually had nothing
to do with the forest.

## Root cause

v0.6.14's "preserve forest link" block in `_try_spawn_master` was
calling, on a fresh ring spawn:

```python
forest._positioned.add(master._id)
forest._dock_partners.add(master._id)
forest._members[master._id] = QPoint(...)
master._group_master_id = forest._id
```

The first two lines were the bug. `_positioned` and `_dock_partners`
are the forest's positioned-children and dock-children sets — adding
the new ring to both told the forest-drag cascade "this ring is
positioned by me, drag it along." But the ring had no dock pointer
back; it was floating wherever the user spawned it. So forest-drag
moved it via the cascade even though it had no real dock relationship.

## Fix

Remove the `_positioned` and `_dock_partners` adds. Keep only the
link-parent assignment and the membership entry:

```python
# Fresh ring spawn — link to forest but do NOT mark as positioned
master._link_parent_id = forest._id
forest._members[master._id] = QPoint(master.x(), master.y())
# DO NOT: forest._positioned.add(master._id)
# DO NOT: forest._dock_partners.add(master._id)
```

The link assignment is enough for the menu-walking code (e.g.
forest's submenu containing this ring); the cascade logic only acts
on cells that ARE both in `_members` AND in `_positioned`. Fresh
rings stay link-linked, drag-independent.

## How future-me detects it

* User says "the ring follows the forest but I never docked it" —
  some site is adding fresh masters to `forest._positioned` or
  `forest._dock_partners`. Grep for `_positioned.add` and
  `_dock_partners.add` near spawn sites.
* Reproducer: drag a cell off the forest, spawn a ring elsewhere
  with two other cells, drag the forest. If the ring trails, the
  fix has regressed.
* The verbatim user-trigger string above is the canonical reproducer
  description — search for it in case-tracking or issues.
