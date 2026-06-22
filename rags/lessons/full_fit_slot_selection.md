---
topic: full_fit_slot_selection_no_clamp
date: 2026-06-21
status: gotcha
related: [settle_rigid_slide_falls_back_to_engine_repack, cell_positioning_central_tracker]
---
# Slot selection must require the WHOLE cell on-screen (1.0), not 50% — else the reveal clamp shoves it into a neighbour

## What happened (user-reported, fixed v0.8.0a74)

Drag the forest into a corner with cells collapsed, then bloom: a cell "tries to
re-position where the top side goes higher than the screen, then gets pushed
into a position that overlaps the cells around it in order to stay on screen."
The user's diagnosis was exact: *"The algorithm sees the edge as available, but
doesn't check that that edge will cause the adjacent cell to be positioned
off-screen."*

## Root cause — two pieces

1. **The slot selector accepted a slot at only 50% on-screen.**
   `tiling.is_on_screen(pos, size, screen_rect, fraction_required=0.5)` returns
   True when ≥ 50% of the cell's *area* is inside the screen. `layout.find_free_slot`
   / `nearest_free_slot` called it with the default 0.5, so a slot whose **top
   half is above the screen** was committed as a valid dock position.
2. **The reveal then clamped that slot on-screen, into the neighbour.**
   `_compute_layout` wrote that half-off-screen slot to `_members[mid]`, and the
   a68 bloom did `target = m._clamp_to_screen(_members[mid])` — pushing the cell
   DOWN so its top hits the screen edge. That clamped position is no longer the
   honeycomb slot; it lands on top of the cell occupying the slot below.

The two planners even disagreed: `group_layout.slot_fits_on_screen` already
required FULL containment, while `layout.py` used 0.5.

## Fix / recipe (a74)

Make slot SELECTION require full containment, so a committed slot never needs
clamping:

```python
# layout.find_free_slot / nearest_free_slot — new param, default full-fit:
def find_free_slot(..., fraction_required: float = 1.0) -> Slot:
    ...
    if not is_on_screen(tl, child_size, screen_rect, fraction_required):
        continue
# cell_window._compute_layout — use full-fit for the pre-pass slot-release,
# the nearest_free_slot call, AND the Pass-2 show/hide check (all 1.0).
# cell_window._start_expand — for an ENGINE-PLACED member (m._slot set), use
# the engine slot VERBATIM (no clamp); clamp ONLY the floating / no-slot
# fallback.  Clamping a slot the engine already fitted is what displaced the
# neighbour.
```

Consequence: at a tight corner a cell with no wholly-fitting slot is auto-hidden
(it reassigns to a free outer-ring slot in the open quadrant first; auto-hide is
the last resort, and the cell returns when the master moves back — see
`test_chaos_movement.test_hidden_cells_return_when_master_moves_back`).  This is
the user's stated preference: never overlapping, never half-off-screen.

Test alignment: `test_chaos_movement._on_screen_slot_count` (the expected-
visibility bound) was bumped from the 0.5 default to `is_on_screen(..., 1.0)` to
match the engine — same purpose ("use all on-screen slots"), corrected threshold.

Implementation: `scriptree/shell/layout.py` (both selectors),
`scriptree/shell/cell_window.py` (`_compute_layout` ×3 + `_start_expand`).

## How future-me detects it

Two rules for resting placement of a cell:
1. **Select only wholly-on-screen slots** (`is_on_screen(..., 1.0)`), so the
   chosen position is final.
2. **Never clamp an engine-assigned slot** — clamping moves the cell off its
   honeycomb slot into whatever is below/beside it.  Clamp only positions the
   engine did NOT choose (floating members, fallbacks).
A 50%-fit slot + an on-screen clamp is a guaranteed overlap at a screen edge.
