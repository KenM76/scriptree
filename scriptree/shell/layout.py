"""Pure-logic slot-based layout for the cell shell (v0.6.35).

No Qt, no widgets, no side effects.  Mirrors the algorithm proven
in ``tools/layout_sim.py`` and pinned by
``tests/test_layout_algorithm.py``.

The data model:

* Every cell has a ``slot`` of ``("inner", N)`` (N in 0..5) or
  ``("outer", N)`` (N in 0..11) — or ``None`` (floating).
* World position of a docked cell = parent's centre + slot offset
  - child size/2 (centre-to-top-left conversion).
* Layout is a function of the tree, not an animation timer.  Call
  ``compute_member_positions`` once per state change.

This module is imported by ``cell_window.py`` to compute slot
assignments + world positions for masters and their members.  The
existing ``CellWindow._members: dict[id, QPoint]`` stays as the
canonical "where each member is now" map; this module computes
what positions go INTO that dict given the tree's slot state.
"""
from __future__ import annotations

import math
from typing import Optional


# ---------------------------------------------------------------------------
# Geometry — flat-top hex honeycomb
# ---------------------------------------------------------------------------

# Inner ring: 6 slots at 60° increments around the master centre,
# distance = size_px (the flat-top hex adjacency distance).
# Indices start at East (slot 0), walk counter-clockwise.
INNER_RING: list[tuple[float, float]] = [
    (math.cos(math.radians(60 * i)), -math.sin(math.radians(60 * i)))
    for i in range(6)
]

# Outer ring: 12 slots at 30° increments, distance ≈ 2 * size_px.
OUTER_RING: list[tuple[float, float]] = [
    (2 * math.cos(math.radians(30 * i)), -2 * math.sin(math.radians(30 * i)))
    for i in range(12)
]


Slot = Optional[tuple[str, int]]


def slot_offset(slot: tuple[str, int], size_px: int) -> tuple[int, int]:
    """Pixel offset from master centre to slot centre."""
    kind, idx = slot
    if kind == "inner":
        fx, fy = INNER_RING[idx]
    elif kind == "outer":
        fx, fy = OUTER_RING[idx]
    else:
        raise ValueError(f"unknown slot kind: {kind!r}")
    return (round(fx * size_px), round(fy * size_px))


def slot_world_pos(
    master_pos: tuple[int, int], master_size: int,
    slot: tuple[str, int], child_size: int,
) -> tuple[int, int]:
    """Top-left world coords for a child docked at ``slot`` of a
    master whose top-left is at ``master_pos``.
    """
    mcx = master_pos[0] + master_size / 2
    mcy = master_pos[1] + master_size / 2
    dx, dy = slot_offset(slot, master_size)
    ccx = mcx + dx
    ccy = mcy + dy
    return (round(ccx - child_size / 2), round(ccy - child_size / 2))


# ---------------------------------------------------------------------------
# Slot allocation
# ---------------------------------------------------------------------------

def is_on_screen(
    pos: tuple[int, int], size: int,
    screen_rect: tuple[int, int, int, int],
) -> bool:
    """More than half of the bounding box visible inside the
    screen rect ``(left, top, right, bottom)``."""
    sl, st, sr, sb = screen_rect
    cl, ct = pos
    cr, cb = pos[0] + size, pos[1] + size
    inter_w = max(0, min(cr, sr) - max(cl, sl))
    inter_h = max(0, min(cb, sb) - max(ct, st))
    return inter_w * inter_h * 2 >= size * size


def find_free_slot(
    master_pos: tuple[int, int], master_size: int,
    master_slot: Slot,
    child_size: int,
    taken_slots: set[tuple[str, int]],
    occupied_centres: set[tuple[int, int]],
    screen_rect: tuple[int, int, int, int],
    overlap_threshold_factor: float = 0.75,
) -> Slot:
    """Find a slot on the master that is:

      1. Not in ``taken_slots`` (no sibling already there).
      2. Not the back-toward-parent slot, when ``master_slot`` is
         set — inner ``(N+3) % 6`` and outer ``(2N + 6) % 12`` are
         reserved so a child never lands on the master's parent.
      3. On-screen (more than half of the cell visible).
      4. Globally non-colliding with every occupied centre — guards
         the honeycomb-tiling aliasing case where two cells in
         different clusters land on the same world coordinate.

    Returns the slot, or None if no candidate qualifies.  Inner
    ring is tried first, then outer.
    """
    forbidden: set[tuple[str, int]] = set()
    if master_slot is not None:
        _, pi = master_slot
        forbidden.add(("inner", (pi + 3) % 6))
        forbidden.add(("outer", (pi * 2 + 6) % 12))

    threshold_sq = (child_size * overlap_threshold_factor) ** 2

    for kind, count in (("inner", 6), ("outer", 12)):
        for i in range(count):
            slot: tuple[str, int] = (kind, i)
            if slot in taken_slots or slot in forbidden:
                continue
            tl = slot_world_pos(master_pos, master_size, slot, child_size)
            if not is_on_screen(tl, child_size, screen_rect):
                continue
            ccx = tl[0] + child_size // 2
            ccy = tl[1] + child_size // 2
            collides = False
            for (ox, oy) in occupied_centres:
                dx = ccx - ox
                dy = ccy - oy
                if dx * dx + dy * dy < threshold_sq:
                    collides = True
                    break
            if collides:
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
    overlap_threshold_factor: float = 0.75,
) -> Slot:
    """Like :func:`find_free_slot` but picks the slot CLOSEST to
    ``drop_centre`` rather than the first valid one.  Used for
    drag-drop / snap targets so the cell snaps to the slot the user
    aimed at."""
    forbidden: set[tuple[str, int]] = set()
    if master_slot is not None:
        _, pi = master_slot
        forbidden.add(("inner", (pi + 3) % 6))
        forbidden.add(("outer", (pi * 2 + 6) % 12))

    threshold_sq = (child_size * overlap_threshold_factor) ** 2
    candidates: list[tuple[float, tuple[str, int]]] = []

    for kind, count in (("inner", 6), ("outer", 12)):
        for i in range(count):
            slot: tuple[str, int] = (kind, i)
            if slot in taken_slots or slot in forbidden:
                continue
            tl = slot_world_pos(master_pos, master_size, slot, child_size)
            if not is_on_screen(tl, child_size, screen_rect):
                continue
            ccx = tl[0] + child_size // 2
            ccy = tl[1] + child_size // 2
            collides = False
            for (ox, oy) in occupied_centres:
                dx = ccx - ox
                dy = ccy - oy
                if dx * dx + dy * dy < threshold_sq:
                    collides = True
                    break
            if collides:
                continue
            dx = ccx - drop_centre[0]
            dy = ccy - drop_centre[1]
            candidates.append((dx * dx + dy * dy, slot))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]
