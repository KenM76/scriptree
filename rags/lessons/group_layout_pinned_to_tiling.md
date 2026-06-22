---
topic: group_layout_pinned_to_tiling_not_delegated
date: 2026-06-21
status: gotcha
related: [cell_positioning_central_tracker, full_fit_slot_selection_no_clamp]
---
# group_layout's geometry tables are PINNED to tiling by test, not delegated — its outer-ring order differs

## Context

`tiling.py` is the intended single source of truth for cell geometry; its header
claims `layout.py`, `snap_engine.py`, and `group_layout.py` "no longer carry
their own geometry tables."  That is FALSE for `group_layout.py` — it still has
hardcoded `_FLAT_TOP_FIRST_RING` / `_*_OUTER_RING` factor tables.  Cleaning this
up (v0.8.0a76) the safe way:

## Why not just delegate group_layout to tiling.slot_offset

The slot VALUES match for hexagons, but the outer-ring INDEX ORDER differs:
- `group_layout` outer ring = 6 axials (NE,SE,S,SW,NW,N), then 6 corners.
- `tiling` outer ring = axial/corner INTERLEAVED, walking CW in 360/(2n)° steps.

`group_layout.repack` (used by every drag-reflow path: `_repack_members(fixed=…)`
at many call sites) drives `_slot_search_order` / `_nearest_slot_index` over the
ordered list, so reordering it would change packing behaviour in the most
bug-prone code.  Too risky to bundle with a bug-fix.

## What was done instead — pin with a consistency test

`tests/test_geometry_consistency.py` asserts group_layout's slot offsets equal
`tiling.slot_offset`'s AS A SET (order-independent) per ring.  This guarantees
the duplicated tables can never silently DRIFT from tiling (the v0.6.40 drift
bug class), without touching the order `repack` relies on.

Empirical state (verified):
- **Hexagon flat-top + pointy-top: inner AND outer match exactly.** (Asserted.)
- **Square: does NOT match.** group_layout treats `size_px` as the edge-to-edge
  width (apothem = size/2 → inner offsets at ±size); tiling treats it as
  circumradius-based (apothem ≈ 0.354·size → inner offsets at ±0.707·size).
  Tracked by a `strict=True` xfail (so a future reconciliation, which would make
  it pass, trips the test to remove the xfail).  Hexagon is the load-bearing
  shape (the forest + all cells are hexes); squares are experimental.

## How future-me detects it

If you change a slot table in EITHER `tiling.py` or `group_layout.py`,
`test_geometry_consistency.py` will fail unless both agree (hex).  To fully
de-duplicate group_layout you must also reconcile the outer-ring ORDER with
tiling AND re-verify every `repack` call site — do it as its own change with the
consistency test as the safety net, not alongside unrelated fixes.  The square
size-convention is a separate, open reconciliation.
