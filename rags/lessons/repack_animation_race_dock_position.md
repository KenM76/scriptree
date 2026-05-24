---
topic: v3-architecture
date: 2026-05-23
status: bug
related: [group_uniform_size_and_repack, link_dock_graph_split, move_to_cascades_dock_children]
---
# `_repack_members` is async — don't read `child.geometry()` immediately after

## What happened

After dragging a ring onto a forest-linked cell, the new dock partner
was set correctly on the ring master, but one of the ring's members
was left behind when the forest later moved the ring. The dock
pointer for that ring → forest edge was never wired.

## Root cause

`_repack_members` uses `_smooth_move(duration_ms=260)` (an async
QPropertyAnimation) to animate members into their new slots. Code
that called `_set_cell_dock(member, master)` immediately after the
repack read `child.geometry()` to compute which edge of the master
the child was touching — but the geometry it got back was the
pre-animation position, not the target slot. The 4 px slack in
`_compute_dock_edge` silently let the mismatch pass: edge wasn't
detected, dock pointer wasn't wired, cascade later left the member
behind.

## Fix

`_set_cell_dock` in `scriptree/shell/cell_window.py:9658` now takes
an optional `child_centre=(cx, cy)` kwarg. Callers that run
immediately after a repack pass the target centre explicitly from
`master._members[mid]` (the post-repack target the animation is
heading toward), bypassing the stale `child.geometry()` read.

```python
# In _set_cell_dock signature:
def _set_cell_dock(self, child, master, *, child_centre=None):
    if child_centre is None:
        rect = child.geometry()
        cx, cy = rect.center().x(), rect.center().y()
    else:
        cx, cy = child_centre
    edge = self._compute_dock_edge(master, cx, cy)
    ...

# At call sites that follow _repack_members():
target = master._members[mid]   # post-repack target slot centre
master._set_cell_dock(child, master, child_centre=target)
```

The default path (no kwarg) keeps working for callers that don't
follow a repack.

## How future-me detects it

* Symptom: a docked-and-grouped member drifts out of the group when
  the master moves later. Inspect `master._dock_children_by_edge` —
  the missing member's id won't be in any edge's set.
* Add a `print(child.geometry(), target)` at the top of
  `_set_cell_dock`. After a fresh repack, the two will be many
  pixels apart for the animating member.
* Anywhere that calls `_repack_members` and then `_set_cell_dock` is
  suspect. Either pass `child_centre` explicitly, or defer the dock
  wire until the animation finishes (use `_smooth_move`'s `finished`
  signal if you need the geometry).
