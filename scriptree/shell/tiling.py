"""Single source of truth for cell-shell tiling geometry (v0.7.0).

No Qt, no widgets, no side effects.  Everything to do with the
shape, size, slot positions, edge-touching distances, and
polygon-polygon collision lives here.  ``layout.py``,
``snap_engine.py``, ``group_layout.py``, and the simulator
``tools/layout_sim.py`` all import from this module — they no
longer carry their own geometry tables.

The motivating bug (v0.6.40): three modules with parallel
slot-offset tables had drifted apart.  ``layout.py`` placed cells
at ``size_px`` (tip-to-tip) while ``snap_engine.py`` and
``group_layout.py`` had the correct ``R√3`` (edge-touching)
factors.  A CI cross-module consistency test now pins them.

Reference: Red Blob Games — Hexagonal Grids
(https://www.redblobgames.com/grids/hexagons/).  "Size" there is
the circumradius (centre-to-vertex distance); here we use
``size_px`` = the bounding-box width of the widget, so the
circumradius is ``size_px / 2``.

What this module owns
---------------------

* :class:`Shape` — the supported regular polygons (flat-top hex,
  pointy-top hex, square; triangle reserved for future).
* :func:`apothem` — centre-to-edge distance for a shape.
* :func:`polygon` — vertex list in widget-local coords (centred on
  origin).
* :func:`slot_offset` — centre-to-centre offset from a master to
  the slot at the given (ring, idx).  Variable-size aware: takes
  both ``master_size`` and ``child_size`` so a 96-px hub master
  with 56-px members tiles correctly.
* :func:`slot_world_pos` — top-left world coords for the child.
* :func:`polygons_collide` — Separating Axis Theorem (SAT) check
  for two convex polygons at given positions.  Used by the new
  collision check in ``layout.find_free_slot``.
* :func:`inner_count` / :func:`outer_count` — slot counts per
  shape (6/12 for hex, 4/8 for square, 3/6 for triangle).
* :func:`back_slot` — given a master docked at ``master_slot`` of
  its parent, the slot in the opposite direction (reserved so a
  child doesn't dock back toward the parent).

Slot indexing convention
------------------------

For all shapes, slot indices walk in the same direction (math
CW = visually CCW with Qt's y-down), starting at the direction
matching ``snap_engine``'s neighbour-offset tables:

* Flat-top hex: 0=N, 1=NE, 2=SE, 3=S, 4=SW, 5=NW
* Pointy-top hex: 0=E, 1=SE, 2=SW, 3=W, 4=NW, 5=NE
* Square: 0=N, 1=E, 2=S, 3=W
* Triangle (point-up): 0=N, 1=SE, 2=SW (3 edges)

The opposite-slot rule is ``(idx + N/2) % N`` for the inner ring
where N is the side count.  Outer ring is at 30° increments
(for hex; varies by shape) starting at the same base angle as
inner, with even indices = axial (past an inner slot) and odd
indices = corner (between two adjacent inner slots).

Variable-size geometry
----------------------

For two regular n-gons sharing one edge:

    edge_touch_distance(spec_a, spec_b) = apothem(spec_a) + apothem(spec_b)

For hex: ``apothem = size_px × √3/4``, so
``edge_touch = (s_a + s_b) × √3/4``.  When sizes are equal this
collapses to the v0.6.40 formula ``size × √3/2``.

For square (inscribed at 45° with vertices at box corners):
``apothem = size_px × √2/4``, edge_touch = ``(s_a + s_b) × √2/4``.

For triangle (point-up, inscribed): ``apothem = size_px × √3/6``,
edge_touch = ``(s_a + s_b) × √3/6``.

Collision check
---------------

For honeycomb-tiled slots, two cells in DIFFERENT slots of the
same master cannot overlap by construction — the geometry
guarantees it.  Overlap concern is for cross-cluster aliasing
(an outer slot of master A lands on an inner slot of master B).
The SAT polygon-polygon check here is the correctness-precise
replacement for the v0.6.39 circle-overlap heuristic; it also
generalises correctly to mixed shapes if/when those ship.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, NamedTuple, Optional


# ---------------------------------------------------------------------------
# Geometry constants — the only place these numbers live
# ---------------------------------------------------------------------------

_SQRT3 = math.sqrt(3)
_SQRT3_HALF = _SQRT3 / 2     # ≈ 0.8660 — apothem-per-circumradius for hex (= cos 30°)
_SQRT3_QRTR = _SQRT3 / 4     # ≈ 0.4330 — apothem-per-size_px for hex
_SQRT2_QRTR = math.sqrt(2) / 4   # ≈ 0.3536 — apothem-per-size_px for square (45°)
_SQRT3_SIXTH = _SQRT3 / 6    # ≈ 0.2887 — apothem-per-size_px for triangle


# ---------------------------------------------------------------------------
# Shape descriptor
# ---------------------------------------------------------------------------

class Shape(NamedTuple):
    """A regular n-gon shape with a fixed rendering orientation.

    name           Canonical short name ("hex", "square", "tri").
    sides          Number of edges/vertices (= inner slot count).
    start_angle    Math angle (CCW from +x, degrees) of slot 0
                   direction from the master centre.  Also the
                   angle of the polygon's first vertex relative
                   to centre (for rendering ``polygon()``).
    orientation    Human-readable orientation tag — "flat-top",
                   "pointy-top", "point-up", "point-down" — or
                   None for shapes that have only one canonical
                   pose (square at 45°).
    """
    name: str
    sides: int
    start_angle: float
    orientation: Optional[str]


HEX_FLAT_TOP = Shape("hex", 6, 90.0, "flat-top")
HEX_POINTY_TOP = Shape("hex", 6, 0.0, "pointy-top")
SQUARE = Shape("square", 4, 90.0, None)
TRIANGLE_POINT_UP = Shape("tri", 3, 90.0, "point-up")
TRIANGLE_POINT_DOWN = Shape("tri", 3, -90.0, "point-down")


def shape_from_legacy(shape_str: str, orientation: str) -> Shape:
    """Map the legacy (shape, orientation) string pair used by the
    rest of the codebase to a :class:`Shape` instance.

    Recognises ``shape='hexagon' orientation='flat-top'`` etc.
    Unknown combos fall back to :data:`HEX_FLAT_TOP`.
    """
    s = (shape_str or "hexagon").lower()
    o = (orientation or "flat-top").lower()
    if s == "hexagon":
        return HEX_FLAT_TOP if o == "flat-top" else HEX_POINTY_TOP
    if s == "square":
        return SQUARE
    if s == "triangle" or s == "tri":
        return TRIANGLE_POINT_DOWN if o == "point-down" else TRIANGLE_POINT_UP
    return HEX_FLAT_TOP


# ---------------------------------------------------------------------------
# Apothem (centre-to-edge distance), edge-touch distance
# ---------------------------------------------------------------------------

def apothem(shape: Shape, size_px: int) -> float:
    """Centre-to-edge-midpoint distance for a regular n-gon
    inscribed in a ``size_px × size_px`` bounding box (the widget).

    Derivation: for a regular n-gon with circumradius
    ``r = size_px/2``, the apothem is ``r × cos(π/n)``.

    * hex (n=6): ``r × √3/2 = size_px × √3/4``
    * square (n=4): ``r × √2/2 = size_px × √2/4``
    * triangle (n=3): ``r × 1/2 = size_px × 1/4``
    """
    r = size_px / 2.0
    return r * math.cos(math.pi / shape.sides)


def edge_touch_distance(
    shape_a: Shape, size_a: int,
    shape_b: Shape, size_b: int,
) -> float:
    """Centre-to-centre distance for two cells of given shapes/sizes
    sharing exactly one edge.

    Geometrically: the sum of the two apothems along the line
    connecting their centres.  Only well-defined when the two
    shapes can share an edge — for hex+hex and square+square this
    is trivial; for cross-shape (hex+triangle in a trihexagonal
    tiling, etc.) the formula still gives the geometric centre
    distance for the shared edge, but whether they actually tile
    is the caller's responsibility.
    """
    return apothem(shape_a, size_a) + apothem(shape_b, size_b)


# ---------------------------------------------------------------------------
# Polygon vertices
# ---------------------------------------------------------------------------

def polygon(shape: Shape, size_px: int) -> list[tuple[float, float]]:
    """Return the n vertices of the shape as ``(x, y)`` pairs in
    widget-local coords, centred on the origin.

    The polygon's edges face the *slot directions* (i.e. the edge
    midpoints point at the slot directions ``shape.start_angle``,
    ``start_angle - 360/n``, …).  Vertices therefore sit halfway
    between adjacent slot directions, offset by ``180°/n`` from
    each.  Vertex 0 is at ``shape.start_angle − 180°/n``
    (the CW-most vertex of the slot-0 edge in math convention).

    Examples:
    - Flat-top hex: slot 0 at 90° (N), vertex 0 at 60° (NE).
      Vertices at 60°, 0°, -60°, -120°, -180°, -240° → E, NE, N,
      NW, W, SW, SE corners (the 6 vertices of a flat-top hex).
    - Pointy-top hex: slot 0 at 0° (E), vertex 0 at -30°.
    - Square: slot 0 at 90° (N), vertex 0 at 45° (NE corner).
    - Triangle point-up: slot 0 at 90° (N edge midpoint),
      vertex 0 at 30° (NE).

    Returned in CW order (in screen coords with y-down).
    """
    r = size_px / 2.0
    half_step_deg = 180.0 / shape.sides
    full_step_deg = 360.0 / shape.sides
    verts: list[tuple[float, float]] = []
    for i in range(shape.sides):
        angle = math.radians(shape.start_angle - half_step_deg - i * full_step_deg)
        verts.append((r * math.cos(angle), -r * math.sin(angle)))
    return verts


# ---------------------------------------------------------------------------
# Slot offsets — the inner ring
# ---------------------------------------------------------------------------

def inner_count(shape: Shape) -> int:
    """Number of slots in the inner ring = number of edges = ``shape.sides``."""
    return shape.sides


def outer_count(shape: Shape) -> int:
    """Number of slots in the outer ring.  For hex (n=6) this is
    12 — 6 axial (past each inner slot) + 6 corner (between
    adjacent inner slots).  For square (n=4) it's 8.  For
    triangle (n=3) it's 6.  General: ``2 × n``."""
    return 2 * shape.sides


def _slot_angle_deg(shape: Shape, kind: str, idx: int) -> float:
    """Math angle (degrees) of the slot direction relative to the
    master centre.

    Inner: indices walk math-CW (subtract from start angle).
    Outer: same direction, 30° steps for hex.  More generally,
    outer steps by ``360/(2n)`` degrees.
    """
    if kind == "inner":
        step = 360.0 / shape.sides
        return shape.start_angle - idx * step
    if kind == "outer":
        step = 360.0 / (2 * shape.sides)
        return shape.start_angle - idx * step
    raise ValueError(f"unknown slot kind: {kind!r}")


def slot_offset(
    master_shape: Shape, master_size: int,
    kind: str, idx: int,
    child_shape: Optional[Shape] = None, child_size: Optional[int] = None,
) -> tuple[int, int]:
    """Centre-to-centre integer pixel offset from the master to
    the slot at ``(kind, idx)``.

    ``child_shape`` / ``child_size`` default to the master's
    values when omitted — this is the common case (uniform-size
    cluster) and matches the v0.6.40 API.  Pass explicit child
    values when sizes differ to get the correct edge-touch
    distance ``(R_master + R_child) × cos(π/n)`` for the inner
    ring.
    """
    if child_shape is None:
        child_shape = master_shape
    if child_size is None:
        child_size = master_size

    angle_rad = math.radians(_slot_angle_deg(master_shape, kind, idx))

    if kind == "inner":
        # Inner = directly adjacent → centres are sum-of-apothems apart.
        d = edge_touch_distance(master_shape, master_size, child_shape, child_size)
    elif kind == "outer":
        if idx % 2 == 0:
            # Axial outer: master ─ inner ─ outer on one line.  Three
            # collinear edge-touching cells.  Distance master→outer =
            # ``apothem(master) + 2·apothem(inner) + apothem(outer)``.
            # Assumes the inner-slot cell on this axis is the same
            # shape/size as the outer cell (common case: uniform
            # cluster).  Collapses to ``2 × R√3`` for uniform hex.
            master_a = apothem(master_shape, master_size)
            inner_a = apothem(child_shape, child_size)  # the cell at the inner slot here
            outer_a = apothem(child_shape, child_size)  # the outer cell itself
            d = master_a + 2 * inner_a + outer_a
        else:
            # Corner outer: at master's vertex direction, between two
            # adjacent inner cells.  Closed-form via law of cosines on
            # the triangle (master_centre, inner_centre, corner_centre):
            #
            #   |corner − inner|² = D² + A² − 2 D A cos(π/n)
            #
            # where A = master→inner edge_touch distance, n = sides.
            # We require |corner − inner| = edge_touch(inner, corner)
            # = 2·apothem(inner) when corner has same shape/size as
            # inner.  Solving for D:
            #
            #   D = A cos(π/n) + √( (2·apothem_inner)² − A² sin²(π/n) )
            #
            # (Larger root — the smaller root is the degenerate inside
            # solution.)  Verified for hex (D = 3R = 1.5·s for uniform
            # s), square (D = s for uniform s), triangle (D = s/2).
            n = master_shape.sides
            A = edge_touch_distance(
                master_shape, master_size, child_shape, child_size,
            )
            apo2 = 2.0 * apothem(child_shape, child_size)
            half = math.pi / n
            sin_h = math.sin(half)
            cos_h = math.cos(half)
            disc_sq = apo2 * apo2 - (A * sin_h) ** 2
            if disc_sq < 0:
                # No edge-touching corner solution for this size ratio —
                # too lopsided to tile.  Fall back to the equal-size
                # answer scaled by master size; not geometrically
                # correct but a sensible bail-out.
                d = 1.5 * master_size
            else:
                d = A * cos_h + math.sqrt(disc_sq)
    else:
        raise ValueError(f"unknown slot kind: {kind!r}")

    return (round(d * math.cos(angle_rad)), round(-d * math.sin(angle_rad)))


def slot_world_pos(
    master_pos: tuple[int, int],
    master_shape: Shape, master_size: int,
    kind: str, idx: int,
    child_shape: Optional[Shape] = None, child_size: Optional[int] = None,
) -> tuple[int, int]:
    """Top-left world coords for a child docked at ``(kind, idx)``
    of a master whose top-left is ``master_pos``."""
    if child_shape is None:
        child_shape = master_shape
    if child_size is None:
        child_size = master_size
    mcx = master_pos[0] + master_size / 2
    mcy = master_pos[1] + master_size / 2
    dx, dy = slot_offset(master_shape, master_size, kind, idx, child_shape, child_size)
    return (round(mcx + dx - child_size / 2), round(mcy + dy - child_size / 2))


# ---------------------------------------------------------------------------
# Back-toward-parent slot rule
# ---------------------------------------------------------------------------

def back_slot(master_inner_idx: int, kind: str, master_shape: Shape) -> tuple[str, int]:
    """Slot of a master's CHILD that points back toward the master's
    PARENT (and is therefore reserved — children mustn't dock there).

    If a master is itself docked at inner slot ``master_inner_idx``
    of its own parent, the master's child slot in the opposite
    direction is forbidden.

    For inner: ``(idx + n/2) % n`` works for even-n shapes (hex 6,
    square 4).  For odd-n (triangle 3) there is no exact "opposite
    slot"; the nearest is ``(idx + n//2) % n`` and the function
    returns that as a conservative ban.

    For outer: opposite at 30° increments around the ring.
    """
    n = master_shape.sides
    if kind == "inner":
        return ("inner", (master_inner_idx + n // 2) % n)
    if kind == "outer":
        return ("outer", (master_inner_idx * 2 + n) % (2 * n))
    raise ValueError(f"unknown slot kind: {kind!r}")


# ---------------------------------------------------------------------------
# Polygon-polygon collision (Separating Axis Theorem)
# ---------------------------------------------------------------------------

def _polygon_at(shape: Shape, size_px: int, centre: tuple[float, float]) -> list[tuple[float, float]]:
    """Return the polygon's vertices translated so the polygon
    centre sits at ``centre``."""
    cx, cy = centre
    return [(cx + vx, cy + vy) for vx, vy in polygon(shape, size_px)]


def _project_polygon(verts: list[tuple[float, float]], axis: tuple[float, float]) -> tuple[float, float]:
    """Project a polygon onto an axis vector; return (min, max)."""
    ax, ay = axis
    dots = [vx * ax + vy * ay for vx, vy in verts]
    return (min(dots), max(dots))


def _polygon_axes(verts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Edge normals (unit vectors) of a convex polygon — the
    candidate separating axes for SAT.
    """
    axes: list[tuple[float, float]] = []
    n = len(verts)
    for i in range(n):
        x0, y0 = verts[i]
        x1, y1 = verts[(i + 1) % n]
        # Edge vector.
        ex, ey = x1 - x0, y1 - y0
        # Perpendicular (normal).
        nx, ny = -ey, ex
        length = math.hypot(nx, ny)
        if length < 1e-9:
            continue
        axes.append((nx / length, ny / length))
    return axes


def polygons_collide(
    shape_a: Shape, size_a: int, centre_a: tuple[float, float],
    shape_b: Shape, size_b: int, centre_b: tuple[float, float],
    slop_px: float = 0.5,
) -> bool:
    """Convex-polygon SAT overlap check.

    Returns True if the two polygons overlap by more than
    ``slop_px`` on every separating axis (i.e. genuine overlap,
    not just adjacent edges).  Adjacent edge-touching cells pass
    (return False) because the overlap on the shared-edge normal
    is exactly zero.

    ``slop_px`` lets us absorb integer-rounding noise — the
    pixel-snapped slot positions in our shell may be off by ±1 px
    from the ideal geometric position.  Set to 0 for exact
    geometric overlap.
    """
    verts_a = _polygon_at(shape_a, size_a, centre_a)
    verts_b = _polygon_at(shape_b, size_b, centre_b)
    for axis in _polygon_axes(verts_a) + _polygon_axes(verts_b):
        amin, amax = _project_polygon(verts_a, axis)
        bmin, bmax = _project_polygon(verts_b, axis)
        # On this axis, the two intervals are separated if one ends
        # before the other begins (modulo the slop).
        if amax < bmin + slop_px or bmax < amin + slop_px:
            return False  # separating axis found → no overlap
    return True  # no separating axis → overlap on every axis → collision


def any_polygon_collides(
    shape: Shape, size: int, centre: tuple[float, float],
    others: Iterable[tuple[Shape, int, tuple[float, float]]],
    slop_px: float = 0.5,
) -> bool:
    """Check a candidate placement against an iterable of other
    placed cells.  Returns True on first collision."""
    for o_shape, o_size, o_centre in others:
        if polygons_collide(shape, size, centre, o_shape, o_size, o_centre, slop_px):
            return True
    return False


# ---------------------------------------------------------------------------
# On-screen check
# ---------------------------------------------------------------------------

def is_on_screen(
    pos: tuple[int, int], size: int,
    screen_rect: tuple[int, int, int, int],
    fraction_required: float = 0.5,
) -> bool:
    """More than ``fraction_required`` of the bounding box visible
    inside the screen rect ``(left, top, right, bottom)``."""
    sl, st, sr, sb = screen_rect
    cl, ct = pos
    cr, cb = pos[0] + size, pos[1] + size
    inter_w = max(0, min(cr, sr) - max(cl, sl))
    inter_h = max(0, min(cb, sb) - max(ct, st))
    return inter_w * inter_h >= size * size * fraction_required
