---
topic: v3-architecture
date: 2026-05-07
status: pattern
related: [snap_engine, cell_window, ring_io]
---
# Group-uniform size + edge-touching repack

## What happened / rule

Two cells in the same master group MUST share `size_px`, `shape`,
and `orientation`.  A user-facing change to any of those on any
member (or on the master) propagates to the whole group, then a
**repack** recomputes member positions so:

1. Every member is edge-touching the master at the new geometry.
2. No two members share a slot (no overlap).
3. Every member is on-screen, when feasible.
4. A member's preferred direction is preserved when feasible.

Off-screen reflow uses the same repack: when the master moves to
a screen edge and would push a member off-screen, that member is
reassigned to the closest free, on-screen slot.

## Architecture

* `scriptree/shell/group_layout.py` — pure-logic module.  Computes
  first-ring (6 hex / 4 square) and outer-ring (12 hex / 8 square)
  slot centres; assigns members to slots by widening-search from
  their preferred direction; filters slots that don't fit a given
  `screen_rect`.
* `CellWindow._apply_group_geometry(*, size_px, shape, orientation)`
  — public entry-point.  Standalone → applies to self only.
  Member → forwards to its master.  Master → applies to itself and
  every member, then calls `_repack_members()`.
* `CellWindow._repack_members()` — calls `group_layout.repack(...)`
  and moves each member to the returned position.  Members with no
  on-screen slot are auto-hidden via `_check_edge_fold`.
* `CellWindow._reflow_members_after_master_move()` — drag-end hook.
  Cheap pre-check: if every member is already on a canonical
  on-screen slot, no-op; otherwise full repack.

## Wiring points

| Trigger | Hook | Notes |
|---|---|---|
| `apply_shape_change` / `apply_size_change` on any cell | `_apply_group_geometry` (group-aware) | Settings dialog calls these |
| Cell joins group (Cases 2/3/4/5 in `_try_spawn_master`) | `_adopt_member_geometry` + `master._repack_members()` | Source resized to match master |
| Fresh master spawn (Case 1) | Master inherits sources' shape/orient + `max(a.size, b.size)` | Larger source wins so neither shrinks |
| Master drag end | `_reflow_members_after_master_move` (drag-end only) | Avoids per-pixel cost during drag |
| `ring_io.load_ring` | `master._repack_members()` (replaces `_check_edge_fold`) | Hand-edited rings auto-canonicalise on load |

## Repack algorithm

```
def repack(master_top_left, size_px, shape, orientation,
           members: dict[id, (x, y)],
           screen_rect: (left, top, right, bottom) | None
           ) -> dict[id, (x, y) | None]:
    inner = first_ring_centres(...)        # 6 hex or 4 square
    outer = outer_ring_centres(...)        # 12 hex or 8 square
    inner_fits = [fits(slot, screen_rect) for slot in inner]
    outer_fits = [fits(slot, screen_rect) for slot in outer]

    # Per-member preferred direction = nearest inner slot to
    # current centre.  Distance from master used as priority key.
    rows = sorted(members,
                  key=lambda m: (dist_to_master(m), member_id(m)))

    inner_taken, outer_taken = set(), set()
    for member in rows:
        # 1. Walk inner ring outward from preferred direction
        for idx in widening_search(member.preferred, n_inner):
            if idx not in inner_taken and inner_fits[idx]:
                place_at(inner[idx]); inner_taken.add(idx); break

        # 2. Outer ring fallback
        if not placed:
            for idx in widening_search(scaled_pref, n_outer):
                if idx not in outer_taken and outer_fits[idx]:
                    place_at(outer[idx]); outer_taken.add(idx); break

        # 3. Unplaced — caller hides via auto-hidden set
```

The widening-search order is `[pref, pref+1, pref-1, pref+2,
pref-2, ...]` modulo ring size — ensures the closest-direction
slot is tried first when the preferred slot is taken.

## Why edge-touching distance is √3/2 × size_px (hex) and 1.0 × size_px (square)

For a flat-top regular hexagon with bounding-box width
`size_px`, neighbour centre-to-centre distance in any of the six
directions is `(√3/2) × size_px ≈ 0.866 × size_px` (matches
`snap_engine._FLAT_TOP_OFFSETS`).  The first test in
`test_group_layout.py::test_first_ring_hex_slots_at_honeycomb_distance`
got this wrong on the first run — caught and corrected.

For squares the distance is `1.0 × size_px` (cell-to-cell
edge-touching).

## Test caveats

* `_apply_size_self` and `_apply_shape_self` are non-broadcasting
  helpers — useful in tests when you want to set one cell's
  geometry without triggering a propagation.
* The test scaffold builds groups by calling `_try_spawn_master`
  directly — full-fidelity dock simulation would need
  `SnapEngine.attach_drag` + simulated mouse events, which is
  expensive and brittle.

## How future-me detects it

If two cells in a master group end up at different sizes,
`_adopt_member_geometry` didn't run on the dock case path.  Check
all four Case 2/3/4/5 branches in `_try_spawn_master`.

If members overlap after a settings change, `_repack_members` is
running but the slot-uniqueness contract in
`group_layout.repack` is broken — write a focused
`test_group_layout.py` case before patching.
