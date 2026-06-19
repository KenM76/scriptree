---
topic: collapse_expand_relative_offsets
date: 2026-06-19
status: gotcha
related: [rescue_cells_on_reveal, show_before_move_desktop_api]
---
# Forest collapse/expand must re-anchor members RELATIVE to the master + clamp on-screen — not restore stale absolute positions

## What happened (user-reported, fixed v0.8.0a67)

Two symptoms, same root cause, in the **single-click collapse/expand**
("slide the cells in / out") path on a master hex (forest or ring) — NOT
the auto-hide visibility path (`forest_visibility.show_hub`, which a62 had
already fixed via `_rescue_cells_on_screen`):

1. **Off-screen:** collapse the forest, drag it to a screen edge, expand —
   the cells re-bloomed at their stale absolute positions, which were now
   off every screen, and nothing pulled them back.
2. **Stacked on the master:** expand → collapse → move the forest → expand,
   and every cell ended up sitting on top of the forest instead of spread
   out around it.

The user's words nailed it: *"It's like it isn't checking their positions
when the forest is clicked and they expand out."*

## Root cause

`CellWindow._start_expand` (cell_window.py) restored each member to
`self._members.get(m._id)` — the **stored ABSOLUTE position** captured at the
last collapse. That anchor is stale the instant the master moves:

- The master-drag cascade (`moveEvent` → `_shift_positioned_members`,
  default `all_members=False`) only shifts the stored positions of
  **`_positioned`** members. Forest members that are *loose-linked* (linked
  but not in `_positioned` — e.g. auto-discovered/dropped items, see the
  v0.8.0 P2 cascade-gate comment) are NOT shifted, so their stored absolute
  position stays put while the forest moves away.
- There is an intentional design that **separated members keep their
  independent position during a master drag** (`moveEvent` comment), so you
  must NOT "fix" this by force-shifting all members in the drag — that would
  regress break-free behaviour.

## Fix / recipe

Re-anchor at the **expand** site using a movement-invariant **offset**, and
always clamp on-screen. Do NOT touch `_members` semantics or the drag cascade.

```python
# __init__: new dict, captured at collapse, consumed at expand
self._collapse_offsets: dict[str, QPoint] = {}

# _start_collapse, in the per-member loop (alongside the existing
# self._members[m._id] = QPoint(m.pos())):
self._collapse_offsets[m._id] = m.pos() - self.pos()   # offset from master NOW

# _expand_target_for(m): resolution order, then clamp on-screen
offset = self._collapse_offsets.get(m._id)
if offset is not None:
    target = self.pos() + offset            # follows the master wherever it moved
else:
    stored = self._members.get(m._id)       # legacy: loaded-collapsed, no offset yet
    target = QPoint(stored) if stored is not None else self.pos() + QPoint(self._size_px + 8, 0)
return m._clamp_to_screen(target)           # never off-screen (falls back to primary)

# _start_expand: use it instead of the raw stored position
restore = self._expand_target_for(m)
```

`m._clamp_to_screen(point) -> QPoint` (cell_window.py ~9621) is the same
contract `screen_watcher.rescue_all_cells` uses: clamp to the containing
screen's `availableGeometry`, falling back to the primary screen for a point
that maps to no screen.

Why offsets, not "shift `_members` by the master delta": the offset is
independent of whether the drag cascade already shifted `_members`, so there
is no double-count, and it works identically for positioned and loose-linked
members. If the master did not move since collapse, `master.pos() + offset`
equals the original absolute position — identical to the old behaviour.

Implementation:
* `scriptree/shell/cell_window.py` — `_collapse_offsets` init (~3652);
  recorded in `_start_collapse` (~10565); `_expand_target_for` (~10592);
  used by `_start_expand`.

## How future-me detects it

Two distinct reveal mechanisms exist and BOTH must place cells on-screen
relative to the (possibly moved) master:
- **auto-hide visibility** (`forest_visibility.show_hub` / `_restore_descendants`)
  → `ForestVisibilityManager._rescue_cells_on_screen` (a62);
- **single-click collapse/expand** (`cell_window._start_expand`)
  → `_expand_target_for` (a67).

If a NEW reveal/restore path is added, it must do the same: re-anchor to the
master's current position and clamp via `_clamp_to_screen`. A restore that
trusts a stored ABSOLUTE coordinate is a latent off-screen/stacking bug.
