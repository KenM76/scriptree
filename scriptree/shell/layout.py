"""Slot-based layout planner (v0.7.0 — thin wrapper over tiling.py).

All geometry lives in :mod:`scriptree.shell.tiling` now.  This
module is the *planner*: given a master and a set of members,
which slot does each member occupy, and where does it go in world
coords?

The planner exposes the same public surface as v0.6.x
(``slot_offset``, ``slot_world_pos``, ``find_free_slot``,
``nearest_free_slot``, ``is_on_screen``) so existing callers in
``cell_window.py`` keep working.  The behaviour change in v0.7.0:

* ``slot_offset`` / ``slot_world_pos`` take ``master_orientation``
  AND optionally ``child_size`` (for variable-size clusters).
* ``find_free_slot`` collision check uses polygon SAT
  (``tiling.polygons_collide``) instead of the v0.6.40 circle
  approximation.
* **Snap-slot binding fix**: callers that arrive here with a
  member at a known snap-committed position should call
  :func:`nearest_free_slot` (not ``find_free_slot``) so the slot
  assigned matches the visible position.  See ``cell_window.py``
  ``_compute_layout`` — v0.6.40 used ``find_free_slot`` which
  picked the first available slot index regardless of where the
  cell actually sat; cells docked at NE could get re-assigned to
  N if N was free, jumbling the cluster.

v0.8.0a75: the legacy ``INNER_RING`` / ``OUTER_RING`` unit-factor
tables were removed -- they had no importers (only the standalone
simulator ``tools/layout_sim.py`` defines its own).  Use
``tiling.slot_offset`` for slot geometry.
"""
from __future__ import annotations

import math
from typing import Optional

from scriptree.shell import tiling
from scriptree.shell.tiling import (
    HEX_FLAT_TOP, HEX_POINTY_TOP,
    Shape, shape_from_legacy,
    apothem, edge_touch_distance, polygons_collide, any_polygon_collides,
    is_on_screen,
)


Slot = Optional[tuple[str, int]]


# ---------------------------------------------------------------------------
# Forwarders that take legacy string args
# ---------------------------------------------------------------------------

def slot_offset(
    slot: tuple[str, int], size_px: int,
    orientation: str = "flat-top",
) -> tuple[int, int]:
    """Pixel offset from master centre to slot centre, with the
    legacy ``orientation`` string for back-compat."""
    shape = HEX_FLAT_TOP if orientation == "flat-top" else HEX_POINTY_TOP
    kind, idx = slot
    return tiling.slot_offset(shape, size_px, kind, idx)


def slot_world_pos(
    master_pos: tuple[int, int], master_size: int,
    slot: tuple[str, int], child_size: int,
    master_orientation: str = "flat-top",
    master_shape: str = "hexagon",
    child_shape: str = "hexagon",
    child_orientation: Optional[str] = None,
) -> tuple[int, int]:
    """Top-left world coords for a child docked at ``slot`` of a
    master whose top-left is at ``master_pos``.  Variable-size
    aware via the (sum-of-apothems) edge-touch distance.
    """
    m_shape = shape_from_legacy(master_shape, master_orientation)
    c_shape = shape_from_legacy(
        child_shape, child_orientation or master_orientation,
    )
    kind, idx = slot
    return tiling.slot_world_pos(
        master_pos, m_shape, master_size, kind, idx, c_shape, child_size,
    )


# ---------------------------------------------------------------------------
# Slot allocation (planner)
# ---------------------------------------------------------------------------

def find_free_slot(
    master_pos: tuple[int, int], master_size: int,
    master_slot: Slot,
    child_size: int,
    taken_slots: set[tuple[str, int]],
    occupied_centres: set[tuple[int, int]],
    screen_rect: tuple[int, int, int, int],
    master_orientation: str = "flat-top",
    overlap_threshold_factor: float = 0.95,  # legacy; ignored — SAT is exact
    master_shape: str = "hexagon",
    child_shape: str = "hexagon",
    child_orientation: Optional[str] = None,
    other_specs: Optional[list[tuple[Shape, int, tuple[float, float]]]] = None,
    fraction_required: float = 1.0,
) -> Slot:
    """Find a slot on the master that is:

      1. Not in ``taken_slots`` (no sibling already there).
      2. Not the back-toward-parent slot, when ``master_slot`` is
         set — inner ``(N+n/2) % n`` and outer ``(2N + n) % 2n``
         are reserved so a child never lands on the master's parent.
      3. On-screen.  ``fraction_required`` (default 1.0 = the WHOLE
         cell must fit) is the fraction of the cell's bbox area that
         must lie inside the screen.  v0.8.0a74 raised the default
         from 0.5 to 1.0: a slot accepted at 50% put the cell's top
         (say) above the screen, and the caller's later on-screen
         clamp then shoved it DOWN into its neighbour — the
         "bloom-into-corner overlap" bug.  Requiring full containment
         means a committed slot never needs clamping, so adjacent
         cells are never displaced.  (Matches ``group_layout.
         slot_fits_on_screen``'s full-containment rule.)
      4. Globally non-colliding with every other placed cell
         (polygon SAT against the candidate child polygon at the
         slot position).

    Returns the slot, or None if no candidate qualifies.  Inner
    ring is tried first, then outer.

    The v0.6.x ``occupied_centres`` parameter remains for callers
    that already snapshotted just centres; pair them with
    ``other_specs`` (shape + size for each occupied centre) for
    SAT to do its job.  When ``other_specs`` is None, falls back
    to a per-occupied-centre uniform-hex assumption.
    """
    m_shape = shape_from_legacy(master_shape, master_orientation)
    c_shape = shape_from_legacy(
        child_shape, child_orientation or master_orientation,
    )

    forbidden: set[tuple[str, int]] = set()
    if master_slot is not None:
        bs = tiling.back_slot(master_slot[1], "inner", m_shape)
        forbidden.add(bs)
        bso = tiling.back_slot(master_slot[1], "outer", m_shape)
        forbidden.add(bso)

    # Convert occupied centres + optional specs into the SAT-pair list.
    if other_specs is None:
        others = [(m_shape, child_size, (float(cx), float(cy)))
                  for cx, cy in occupied_centres]
    else:
        others = other_specs

    n_inner = tiling.inner_count(m_shape)
    n_outer = tiling.outer_count(m_shape)
    for kind, count in (("inner", n_inner), ("outer", n_outer)):
        for i in range(count):
            slot: tuple[str, int] = (kind, i)
            if slot in taken_slots or slot in forbidden:
                continue
            tl = tiling.slot_world_pos(
                master_pos, m_shape, master_size, kind, i, c_shape, child_size,
            )
            if not is_on_screen(tl, child_size, screen_rect, fraction_required):
                continue
            ccx = tl[0] + child_size / 2.0
            ccy = tl[1] + child_size / 2.0
            if tiling.any_polygon_collides(
                c_shape, child_size, (ccx, ccy), others, slop_px=0.5,
            ):
                continue
            return slot
    return None


def nearest_free_slot(
    master_pos: tuple[int, int], master_size: int,
    master_slot: Slot,
    drop_centre: tuple[int, int],
    child_size: int,
    taken_slots: set[tuple[str, int]],
    occupied_centres: set[tuple[int, int]],
    screen_rect: tuple[int, int, int, int],
    master_orientation: str = "flat-top",
    overlap_threshold_factor: float = 0.95,  # legacy; ignored
    master_shape: str = "hexagon",
    child_shape: str = "hexagon",
    child_orientation: Optional[str] = None,
    other_specs: Optional[list[tuple[Shape, int, tuple[float, float]]]] = None,
    fraction_required: float = 1.0,
) -> Slot:
    """Like :func:`find_free_slot` but picks the slot whose
    *centre* is closest to ``drop_centre``.

    ``fraction_required`` (default 1.0 = full containment) is the
    on-screen rule, same as :func:`find_free_slot` — see its rule 3.

    The v0.7.0 ``_compute_layout`` uses this (with the cell's
    current widget centre as ``drop_centre``) to bind a
    snap-committed cell to the slot it physically sits on, instead
    of letting ``find_free_slot``'s first-available logic shuffle
    cells into the wrong slots.
    """
    m_shape = shape_from_legacy(master_shape, master_orientation)
    c_shape = shape_from_legacy(
        child_shape, child_orientation or master_orientation,
    )

    forbidden: set[tuple[str, int]] = set()
    if master_slot is not None:
        forbidden.add(tiling.back_slot(master_slot[1], "inner", m_shape))
        forbidden.add(tiling.back_slot(master_slot[1], "outer", m_shape))

    if other_specs is None:
        others = [(m_shape, child_size, (float(cx), float(cy)))
                  for cx, cy in occupied_centres]
    else:
        others = other_specs

    # v0.7.0 — inner-ring-first, nearest-within-ring.  This matches
    # honeycomb intent: tile inner first, escalate to outer only
    # when inner is full.  Within a ring, pick the slot the cell
    # physically sits closest to (so a snap-committed cell stays
    # at the slot it docked to, not slot 0 in insertion order).
    n_inner = tiling.inner_count(m_shape)
    n_outer = tiling.outer_count(m_shape)
    for kind, count in (("inner", n_inner), ("outer", n_outer)):
        candidates: list[tuple[float, tuple[str, int]]] = []
        for i in range(count):
            slot: tuple[str, int] = (kind, i)
            if slot in taken_slots or slot in forbidden:
                continue
            tl = tiling.slot_world_pos(
                master_pos, m_shape, master_size, kind, i, c_shape, child_size,
            )
            if not is_on_screen(tl, child_size, screen_rect, fraction_required):
                continue
            ccx = tl[0] + child_size / 2.0
            ccy = tl[1] + child_size / 2.0
            if tiling.any_polygon_collides(
                c_shape, child_size, (ccx, ccy), others, slop_px=0.5,
            ):
                continue
            dx = ccx - drop_centre[0]
            dy = ccy - drop_centre[1]
            candidates.append((dx * dx + dy * dy, slot))
        if candidates:
            candidates.sort()
            return candidates[0][1]
    return None
