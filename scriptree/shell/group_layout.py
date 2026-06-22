"""
group_layout.py — pure-logic ring re-packing for master + members.

## For humans

When two cells dock, they form a *group* whose authoritative size,
shape, and orientation live on the master.  Every member of the group
adopts those values — there is no such thing as a 32-px hexagon
docked next to a 96-px square.  This module owns the geometry that
keeps that promise:

* Compute the slot centres around a master at a given size / shape /
  orientation.
* Decide which member gets which slot when membership, size, or
  orientation changes.
* Find a fallback slot when a member's preferred direction would
  push it off-screen (e.g. master dragged into a corner).

The module is intentionally Qt-light — it accepts plain ``(x, y)``
tuples for positions and a plain ``(left, top, right, bottom)`` for
the screen rect — so the algorithm is pytest-friendly without an
``QApplication``.  The cell-window glue at the call site converts to
``QPoint`` before calling ``CellWindow.move``.

Slot layout
-----------

**Hexagon (flat-top)** — first-ring slots (centre-to-centre offsets
in ``size_px`` units, ordered N, NE, SE, S, SW, NW):

    N : ( 0.00, -0.866)
    NE: (+0.75, -0.433)
    SE: (+0.75, +0.433)
    S : ( 0.00, +0.866)
    SW: (-0.75, +0.433)
    NW: (-0.75, -0.433)

Outer ring (12 slots) is the next concentric ring of the same
honeycomb tiling — directions interleave the inner six with six
"between" slots two cells out.

**Hexagon (pointy-top)** — same offsets rotated 90° (E, SE, SW, W,
NW, NE).

**Square** — 4 first-ring slots (N, E, S, W), 8 outer slots
(N, NE, E, SE, S, SW, W, NW) at radius 2.

Repack algorithm
----------------

1. Build the candidate slot list (first ring + outer ring), filtered
   to slots whose top-left fits inside ``screen_rect``.
2. For every member, compute the slot index its current centre is
   nearest to — this is its *preferred direction*.
3. Sort members by ascending distance from the master (closest first
   so they get first pick of the inner ring).
4. Greedily assign each member:

   a. Try the preferred slot.
   b. If taken or off-screen, walk outwards through nearby slot
      indices (priority: same-shell first, then outer shell) using
      the cyclic distance in slot index for "nearby".
   c. If no slot works, leave the member unplaced (caller decides
      whether to auto-hide or shift the master).

5. Return ``dict[member_id, (x, y) | None]``.

## For maintainers / LLMs

* Slot offset tables MUST stay in lock-step with
  ``snap_engine._FLAT_TOP_OFFSETS`` et al. — the first-ring tables here
  are the same six honeycomb offsets the snap engine uses to detect a
  dock.  If you change the tiling math in one module, change both or
  members will land off the slots they snapped to.
* All offsets are *factors* of ``size_px`` (centre-to-centre), applied
  to the master *centre*, not its top-left.  ``repack`` derives the
  centre as ``top_left + size_px/2`` for both master and members; keep
  that convention or every slot shifts by half a cell.
* ``_nearest_slot_index`` breaks ties by lowest index and ``repack``
  sorts members by ``(dist_sq, member_id)`` — both are deliberate so
  the function is deterministic for tests.  Do not switch to an
  unstable sort key.
* ``screen_rect`` is ``(left, top, right, bottom)`` with right/bottom
  treated as *exclusive* (a slot fits iff ``tl + size <= right``).
  ``screen_rect_at`` builds it from Qt as ``(left, top, right+1,
  bottom+1)`` to match that exclusivity — do not double-correct.
* ``screen_rect=None`` means "skip the fit filter, every slot is
  valid" (headless tests).  ``screen_rect_at`` also returns ``None``
  when no ``QApplication`` exists — callers must treat None as
  "unconstrained", never as "nothing fits".
* ``fixed`` members (V3 v0.3.16+) keep their current top-left verbatim
  and only *reserve* their nearest slot (inner or outer, whichever is
  closer).  They are excluded from the assignment loop; do not also
  add them to ``rows`` or they get double-placed.
* The outer ring is searched with ``pref`` mapped proportionally
  (``round(pref * n_outer / n_inner) % n_outer``); inner has 6 hex / 4
  square slots, outer has 12 hex / 8 square, so this mapping assumes
  those counts — revisit it if a ring's slot count changes.
* ``repack`` returns ``None`` for any unplaceable member; the caller
  owns hiding/edge-folding them — this module never touches Qt.
"""
from __future__ import annotations

import math
from typing import Iterable

# ---------------------------------------------------------------------------
# Slot offset tables — match snap_engine._FLAT_TOP_OFFSETS et al.
# ---------------------------------------------------------------------------

_SQRT3_HALF = math.sqrt(3) / 2   # ≈ 0.866
_SQRT3_QRTR = math.sqrt(3) / 4   # ≈ 0.433

# (dx_factor, dy_factor) in size_px units.
#
# a76: these tables duplicate the geometry that lives in ``tiling.py``
# (the single source of truth).  They are NOT delegated to
# ``tiling.slot_offset`` because this module's OUTER-ring INDEX ORDER
# (6 axials, then 6 corners) differs from tiling's (interleaved), and
# ``repack`` depends on that order.  Instead, the HEXAGON tables are
# PINNED to tiling by ``tests/test_geometry_consistency.py`` (set
# equality per ring) so they can never silently drift.  (Square uses a
# different size convention than tiling -- see that test's xfail.)

# Hexagons — radius 1 (centre-to-centre = size_px) for flat-top edges
# touching, where the centre-to-centre on the y axis between two
# vertically-stacked hexagons is sqrt(3) * size_px / 2.
_FLAT_TOP_FIRST_RING: list[tuple[float, float]] = [
    (0.00,  -_SQRT3_HALF),   # 0 N
    (+0.75, -_SQRT3_QRTR),   # 1 NE
    (+0.75, +_SQRT3_QRTR),   # 2 SE
    (0.00,  +_SQRT3_HALF),   # 3 S
    (-0.75, +_SQRT3_QRTR),   # 4 SW
    (-0.75, -_SQRT3_QRTR),   # 5 NW
]

_POINTY_TOP_FIRST_RING: list[tuple[float, float]] = [
    (+_SQRT3_HALF,  0.00),   # 0 E
    (+_SQRT3_QRTR, +0.75),   # 1 SE
    (-_SQRT3_QRTR, +0.75),   # 2 SW
    (-_SQRT3_HALF,  0.00),   # 3 W
    (-_SQRT3_QRTR, -0.75),   # 4 NW
    (+_SQRT3_QRTR, -0.75),   # 5 NE
]

_SQUARE_FIRST_RING: list[tuple[float, float]] = [
    (0.00, -1.00),   # 0 N
    (+1.00, 0.00),   # 1 E
    (0.00, +1.00),   # 2 S
    (-1.00, 0.00),   # 3 W
]


# Outer (second) ring — 12 hex slots, 8 square slots.  Each entry is
# (dx_factor, dy_factor) in size_px units, ordered to interleave with
# the first ring so a "preferred direction" maps cleanly.
_FLAT_TOP_OUTER_RING: list[tuple[float, float]] = [
    # Six "edge" outer hexes (directly opposite each first-ring slot,
    # i.e. two cells out) and six "between" outer hexes.
    (+0.75 * 2, -_SQRT3_QRTR * 2),     # NE-out
    (+0.75 * 2, +_SQRT3_QRTR * 2),     # SE-out
    (0.00,      +_SQRT3_HALF * 2),     # S-out
    (-0.75 * 2, +_SQRT3_QRTR * 2),     # SW-out
    (-0.75 * 2, -_SQRT3_QRTR * 2),     # NW-out
    (0.00,      -_SQRT3_HALF * 2),     # N-out
    # "Between" hexes one row further away.
    (+1.50,     0.00),                 # ENE-out
    (+0.75,     +_SQRT3_HALF + _SQRT3_QRTR),  # SE-between
    (-0.75,     +_SQRT3_HALF + _SQRT3_QRTR),  # SW-between
    (-1.50,     0.00),                 # WNW-out
    (-0.75,     -(_SQRT3_HALF + _SQRT3_QRTR)),  # NW-between
    (+0.75,     -(_SQRT3_HALF + _SQRT3_QRTR)),  # NE-between
]

_POINTY_TOP_OUTER_RING: list[tuple[float, float]] = [
    # Mirror of _FLAT_TOP_OUTER_RING with the 90° rotation that
    # converts flat-top → pointy-top: (x, y) → (-y, x).
    (+_SQRT3_QRTR * 2,   +0.75 * 2),
    (-_SQRT3_QRTR * 2,   +0.75 * 2),
    (-_SQRT3_HALF * 2,    0.00),
    (-_SQRT3_QRTR * 2,   -0.75 * 2),
    (+_SQRT3_QRTR * 2,   -0.75 * 2),
    (+_SQRT3_HALF * 2,    0.00),
    (0.00,              +1.50),
    (-(_SQRT3_HALF + _SQRT3_QRTR),  +0.75),
    (-(_SQRT3_HALF + _SQRT3_QRTR),  -0.75),
    (0.00,              -1.50),
    (+(_SQRT3_HALF + _SQRT3_QRTR),  -0.75),
    (+(_SQRT3_HALF + _SQRT3_QRTR),  +0.75),
]

_SQUARE_OUTER_RING: list[tuple[float, float]] = [
    # 8 squares around the central square, all touching it edge-to-edge
    # or corner-to-corner at radius 2 (centre-to-centre).
    (0.00, -2.00),     # N-out
    (+2.00, -2.00),    # NE-corner-out  (offset one edge then up)
    (+2.00, 0.00),     # E-out
    (+2.00, +2.00),    # SE-corner-out
    (0.00, +2.00),     # S-out
    (-2.00, +2.00),    # SW-corner-out
    (-2.00, 0.00),     # W-out
    (-2.00, -2.00),    # NW-corner-out
]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def _first_ring_factors(shape: str, orientation: str) -> list[tuple[float, float]]:
    s = (shape or "hexagon").lower()
    if s == "hexagon":
        return _FLAT_TOP_FIRST_RING if orientation == "flat-top" else _POINTY_TOP_FIRST_RING
    return _SQUARE_FIRST_RING


def _outer_ring_factors(shape: str, orientation: str) -> list[tuple[float, float]]:
    s = (shape or "hexagon").lower()
    if s == "hexagon":
        return _FLAT_TOP_OUTER_RING if orientation == "flat-top" else _POINTY_TOP_OUTER_RING
    return _SQUARE_OUTER_RING


def first_ring_centres(
    master_cx: float, master_cy: float,
    size_px: int, shape: str, orientation: str,
) -> list[tuple[float, float]]:
    """Return the centre coords of every first-ring slot around the master."""
    return [
        (master_cx + dx * size_px, master_cy + dy * size_px)
        for dx, dy in _first_ring_factors(shape, orientation)
    ]


def outer_ring_centres(
    master_cx: float, master_cy: float,
    size_px: int, shape: str, orientation: str,
) -> list[tuple[float, float]]:
    """Return the centre coords of every outer (second-ring) slot."""
    return [
        (master_cx + dx * size_px, master_cy + dy * size_px)
        for dx, dy in _outer_ring_factors(shape, orientation)
    ]


def all_slot_centres(
    master_cx: float, master_cy: float,
    size_px: int, shape: str, orientation: str,
) -> list[tuple[float, float]]:
    """Return first-ring slots followed by outer-ring slots."""
    return (
        first_ring_centres(master_cx, master_cy, size_px, shape, orientation)
        + outer_ring_centres(master_cx, master_cy, size_px, shape, orientation)
    )


def top_left_for_centre(cx: float, cy: float, size_px: int) -> tuple[int, int]:
    """Convert a slot centre to the window top-left integer pixel coords."""
    return (round(cx - size_px / 2), round(cy - size_px / 2))


def slot_fits_on_screen(
    cx: float, cy: float, size_px: int,
    screen_rect: tuple[int, int, int, int] | None,
) -> bool:
    """True iff a cell of ``size_px`` centred at ``(cx, cy)`` lies fully
    within ``screen_rect`` (``(left, top, right, bottom)``).

    Pass ``None`` to skip the check (always fits) — useful for tests
    or headless contexts.
    """
    if screen_rect is None:
        return True
    left, top, right, bottom = screen_rect
    tl_x = cx - size_px / 2
    tl_y = cy - size_px / 2
    return (
        tl_x >= left
        and tl_y >= top
        and tl_x + size_px <= right
        and tl_y + size_px <= bottom
    )


# ---------------------------------------------------------------------------
# Direction inference
# ---------------------------------------------------------------------------

def _nearest_slot_index(
    member_cx: float, member_cy: float,
    slot_centres: list[tuple[float, float]],
) -> int:
    """Return the index of the slot whose centre is closest to ``(member_cx, member_cy)``.

    Ties broken by lowest index (so the assignment is deterministic
    when the member sits on a perfect bisector).
    """
    best_i = 0
    best_dist_sq = float("inf")
    for i, (cx, cy) in enumerate(slot_centres):
        d2 = (cx - member_cx) ** 2 + (cy - member_cy) ** 2
        if d2 < best_dist_sq:
            best_dist_sq = d2
            best_i = i
    return best_i


def _slot_search_order(preferred: int, n: int) -> list[int]:
    """Return slot indices in widening-distance order from ``preferred``.

    For ``preferred=2``, ``n=6``: ``[2, 3, 1, 4, 0, 5]`` — same shell,
    walking outwards alternately CW and CCW.
    """
    order = [preferred]
    for step in range(1, n):
        # Alternate +step, -step, but for even n we hit the antipode
        # only once when step == n/2.
        plus = (preferred + step) % n
        minus = (preferred - step) % n
        if plus not in order:
            order.append(plus)
        if minus not in order:
            order.append(minus)
        if len(order) == n:
            break
    return order


# ---------------------------------------------------------------------------
# Repack
# ---------------------------------------------------------------------------

def repack(
    master_top_left: tuple[int, int],
    size_px: int,
    shape: str,
    orientation: str,
    members: dict[str, tuple[int, int]],
    *,
    screen_rect: tuple[int, int, int, int] | None = None,
    fixed: set[str] | None = None,
) -> dict[str, tuple[int, int] | None]:
    """Compute new top-left positions for every member of a group.

    Parameters
    ----------
    master_top_left
        Master cell's top-left pixel position.
    size_px
        Group's shared cell size.  Master and every member render at
        this size after the call.
    shape, orientation
        Group's shared shape / orientation.  ``orientation`` is
        ignored for ``shape == "square"``.
    members
        ``{member_id: (current_top_left_x, current_top_left_y)}`` for
        every member in the group.  Order doesn't matter — sorting
        is internal.
    screen_rect
        Optional ``(left, top, right, bottom)`` to filter slots that
        would push a member off-screen.  ``None`` skips the filter
        (every slot is considered valid).
    fixed
        Optional set of member ids whose **current position is
        preserved verbatim** (V3 v0.3.16+).  Their nearest-slot is
        also marked as taken so non-fixed members cannot be assigned
        to overlap.  Use this when a master moves and only some of
        its members are off-screen — the on-screen ones stay where
        the user placed them; only the off-screen ones get new slots.
        ``None`` (default) reproduces pre-v0.3.16 behaviour: every
        member is up for reassignment.

    Returns
    -------
    dict[str, tuple[int, int] | None]
        ``{member_id: (new_top_left_x, new_top_left_y)}`` for placed
        members; ``None`` for any member that couldn't be placed
        (no free, on-screen slot in either ring).  The caller is
        responsible for hiding unplaced members.

    Guarantees
    ----------
    * No two placed members share a slot — so no overlap.
    * Each member's preferred direction (from its current centre) is
      respected when feasible; otherwise nearest free direction wins.
    * Closer members win first-ring slots over further-out members
      (sorted by centre distance from master ascending).
    * Deterministic for a given input.
    """
    master_cx = master_top_left[0] + size_px / 2
    master_cy = master_top_left[1] + size_px / 2

    inner = first_ring_centres(master_cx, master_cy, size_px, shape, orientation)
    outer = outer_ring_centres(master_cx, master_cy, size_px, shape, orientation)
    n_inner = len(inner)
    n_outer = len(outer)

    # Pre-compute fits-on-screen for every slot so we don't re-evaluate
    # in the assignment hot loop.
    inner_fits = [
        slot_fits_on_screen(cx, cy, size_px, screen_rect)
        for cx, cy in inner
    ]
    outer_fits = [
        slot_fits_on_screen(cx, cy, size_px, screen_rect)
        for cx, cy in outer
    ]

    # ------------------------------------------------------------------
    # Per-member preferred-slot index + distance from master.
    # ------------------------------------------------------------------
    fixed = fixed or set()
    member_ids = list(members.keys())
    rows = []
    for mid in member_ids:
        if mid in fixed:
            continue  # fixed members are not part of the assignment loop
        mtl = members[mid]
        mcx = mtl[0] + size_px / 2
        mcy = mtl[1] + size_px / 2
        pref = _nearest_slot_index(mcx, mcy, inner)
        dist_sq = (mcx - master_cx) ** 2 + (mcy - master_cy) ** 2
        rows.append((mid, pref, dist_sq))

    # Sort: closest-to-master first.  Tie-break by member_id to keep
    # the function deterministic for tests (Python's str compare is
    # well-defined and stable across runs).
    rows.sort(key=lambda r: (r[2], r[0]))

    # ------------------------------------------------------------------
    # Greedy assignment.
    # ------------------------------------------------------------------
    inner_taken: set[int] = set()
    outer_taken: set[int] = set()
    out: dict[str, tuple[int, int] | None] = {}

    # Pre-claim slots occupied by fixed members so the assignment loop
    # avoids overlapping them.  Fixed members keep their current
    # top-left verbatim — we don't snap them to a slot, only mark the
    # nearest slot as taken.  A fixed member's nearest slot might be
    # in the inner OR outer ring; we reserve whichever is closer.
    for mid in fixed:
        if mid not in members:
            continue
        mtl = members[mid]
        mcx = mtl[0] + size_px / 2
        mcy = mtl[1] + size_px / 2
        pref_inner = _nearest_slot_index(mcx, mcy, inner) if inner else None
        pref_outer = _nearest_slot_index(mcx, mcy, outer) if outer else None
        # Pick whichever ring's nearest slot is closest to the member.
        d_inner = (
            (mcx - inner[pref_inner][0]) ** 2 + (mcy - inner[pref_inner][1]) ** 2
            if pref_inner is not None else float("inf")
        )
        d_outer = (
            (mcx - outer[pref_outer][0]) ** 2 + (mcy - outer[pref_outer][1]) ** 2
            if pref_outer is not None else float("inf")
        )
        if d_inner <= d_outer and pref_inner is not None:
            inner_taken.add(pref_inner)
        elif pref_outer is not None:
            outer_taken.add(pref_outer)
        out[mid] = mtl  # keep position unchanged

    for mid, pref, _ in rows:
        chosen: tuple[int, int] | None = None

        # 1. Walk inner ring outward from preferred direction.
        for idx in _slot_search_order(pref, n_inner):
            if idx in inner_taken:
                continue
            if not inner_fits[idx]:
                continue
            inner_taken.add(idx)
            chosen = top_left_for_centre(*inner[idx], size_px)
            break

        if chosen is None:
            # 2. Outer ring — same direction-search heuristic, but the
            #    outer ring has more (or different) slots so we map
            #    `pref` proportionally.
            outer_pref = round(pref * n_outer / n_inner) % n_outer
            for idx in _slot_search_order(outer_pref, n_outer):
                if idx in outer_taken:
                    continue
                if not outer_fits[idx]:
                    continue
                outer_taken.add(idx)
                chosen = top_left_for_centre(*outer[idx], size_px)
                break

        out[mid] = chosen

    return out


# ---------------------------------------------------------------------------
# Convenience: detect whether a member layout matches the group standard
# ---------------------------------------------------------------------------

def members_at_canonical_slots(
    master_top_left: tuple[int, int],
    size_px: int,
    shape: str,
    orientation: str,
    members: dict[str, tuple[int, int]],
    tolerance: float = 1.5,
) -> bool:
    """True iff every member already sits on a unique inner/outer slot.

    Used as a cheap pre-check in the cell-window glue: no need to call
    ``repack`` when the layout is already canonical (e.g. just after a
    fresh ring load).
    """
    candidates = all_slot_centres(
        master_top_left[0] + size_px / 2,
        master_top_left[1] + size_px / 2,
        size_px, shape, orientation,
    )
    used: set[int] = set()
    for mid, mtl in members.items():
        mcx = mtl[0] + size_px / 2
        mcy = mtl[1] + size_px / 2
        idx = _nearest_slot_index(mcx, mcy, candidates)
        if idx in used:
            return False
        used.add(idx)
        cx, cy = candidates[idx]
        if math.hypot(cx - mcx, cy - mcy) > tolerance:
            return False
    return True


def screen_rect_at(
    cx: float, cy: float,
) -> tuple[int, int, int, int] | None:
    """Return the available screen rect containing ``(cx, cy)``.

    Wraps ``QGuiApplication.screenAt`` / ``primaryScreen`` so callers
    don't have to know about Qt.  ``None`` when no QApplication is
    initialised yet (i.e. a unit test running headless without a Qt
    app instance).
    """
    try:
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QGuiApplication
    except ImportError:
        return None
    app = QGuiApplication.instance()
    if app is None:
        return None
    pt = QPoint(round(cx), round(cy))
    screen = QGuiApplication.screenAt(pt)
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None
    g = screen.availableGeometry()
    return (g.left(), g.top(), g.right() + 1, g.bottom() + 1)


def screen_rect_for_master(master_top_left: tuple[int, int], size_px: int) -> tuple[int, int, int, int] | None:
    """Convenience: ``screen_rect_at`` keyed on the master's centre."""
    cx = master_top_left[0] + size_px / 2
    cy = master_top_left[1] + size_px / 2
    return screen_rect_at(cx, cy)
