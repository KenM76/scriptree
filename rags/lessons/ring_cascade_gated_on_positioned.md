---
topic: v3-architecture
date: 2026-05-23
status: pattern
related: [link_dock_graph_split, fresh_ring_not_in_forest_positioned]
---
# Ring drag cascade is gated on `_positioned`, not on link membership

## What happened

Bug 10 (v0.8.0a1): when the user dragged a cell off a ring (the
"break free" gesture, 4 px threshold) and then dragged the ring,
the dragged-off cell still followed the ring's drag. Should have
stayed put — the user had deliberately separated it.

User spec evolved from v0.6.x: "when I drag a cell off the ring,
it should stay put when I drag the ring."

## Root cause

v0.8.0 P2 (link-driven cascade) had the ring's drag walk every
link-child — every cell with `_link_parent_id == ring._id`. The
dragged-off cell still had `_link_parent_id` pointing at the ring
(it's still link-linked until the user explicitly closes it), so
the cascade picked it up.

But `_break_free_from_cluster` (the 4 px threshold handler) already
drops the dragged cell from `master._positioned`. The cascade should
respect that signal: link membership says "I'm in this group", but
`_positioned` says "I'm physically positioned by my master's drag."

## Fix

Make the link-children widening at `scriptree/shell/cell_window.py:6175`
a no-op for rings — same as it already was for forests. The cascade
uses the `_positioned` set, which naturally excludes anyone who
dragged off:

```python
# Forest and ring drag cascade — same rule now
if self.role == "master":
    members_to_move = self._positioned & set(self._members.keys())
    # NOT: members_to_move = set(self._members.keys())
    for mid in members_to_move:
        ...
```

Forest already worked this way (so a forest-linked cell that has
been dragged-off-and-not-redocked stays put when forest moves).
Aligning ring to the same rule fixed Bug 10.

## Why not just clear `_link_parent_id` on break-free?

The cell is still link-linked to the ring conceptually — the user
can re-dock by dragging it back. Clearing the link would require
re-establishing it on re-dock, doubling the bookkeeping. The
`_positioned` flag is exactly the right signal: it's set on dock
and cleared on break-free, by code that already exists.

## How future-me detects it

* "I dragged a cell off the ring, then dragged the ring, and the
  cell came with" — the cascade is using link membership instead
  of `_positioned`. Check the master-drag branch in cell_window.py
  around line 6175.
* Forest behaviour was already correct in v0.6.x; if forests start
  exhibiting this same Bug 10 pattern, look for an inadvertent
  alignment to the ring (wrong) behaviour during a refactor.
