"""v0.8.0a76 — pin group_layout's slot-geometry tables to tiling.

tiling.py is meant to be the SINGLE source of truth for cell-shell
geometry (its header says layout/snap_engine/group_layout "no longer
carry their own geometry tables").  In reality ``group_layout.py``
still carries its own hardcoded ``_FLAT_TOP_FIRST_RING`` /
``_*_OUTER_RING`` factor tables.  Reordering group_layout to delegate
to ``tiling.slot_offset`` is risky -- its outer-ring INDEX ORDER
differs from tiling's (group_layout groups the 6 axials then 6
corners; tiling interleaves them), and ``group_layout.repack`` -- used
by every drag-reflow path -- depends on that order.

So instead of a risky reorder, these tests PIN the duplicated tables:
they assert group_layout's slot positions equal tiling's
``slot_offset`` positions AS A SET (order-independent) per ring, so the
two can never silently DRIFT apart (the v0.6.40 bug class the tiling
module was created to end).  Any future divergence fails here.

HEXAGON (the load-bearing shape: the forest hub and all cells are
hexes) matches exactly, flat-top and pointy-top.  SQUARE does NOT --
group_layout treats ``size_px`` as the edge-to-edge width (apothem =
size/2) while tiling treats it as circumradius-based (apothem ≈
0.354·size).  That square size-convention reconciliation is tracked
by the ``xfail`` below; it does not affect hex clusters.
"""
from __future__ import annotations

import pytest

from scriptree.shell import group_layout as gl
from scriptree.shell import tiling


def _offsets_match(a: list[tuple[int, int]], b: list[tuple[int, int]],
                   tol: int = 1) -> bool:
    """True iff ``a`` and ``b`` are the same SET of offsets (±tol px),
    ignoring order — both must have the same length and every offset
    in one has a unique near-match in the other."""
    if len(a) != len(b):
        return False
    remaining = list(b)
    for ax, ay in a:
        for i, (bx, by) in enumerate(remaining):
            if abs(ax - bx) <= tol and abs(ay - by) <= tol:
                remaining.pop(i)
                break
        else:
            return False
    return not remaining


def _gl_offsets(centre_fn, shape: str, orient: str, size: int = 1000):
    cx = cy = 5000
    return [
        (round(x - cx), round(y - cy))
        for x, y in centre_fn(cx, cy, size, shape, orient)
    ]


def _tiling_offsets(shape: str, orient: str, kind: str, size: int = 1000):
    spec = tiling.shape_from_legacy(shape, orient)
    n = tiling.inner_count(spec) if kind == "inner" else tiling.outer_count(spec)
    return [tiling.slot_offset(spec, size, kind, i) for i in range(n)]


@pytest.mark.parametrize("orient", ["flat-top", "pointy-top"])
def test_group_layout_hex_inner_ring_matches_tiling(orient: str) -> None:
    gl_off = _gl_offsets(gl.first_ring_centres, "hexagon", orient)
    t_off = _tiling_offsets("hexagon", orient, "inner")
    assert _offsets_match(gl_off, t_off), (
        f"hex/{orient} INNER ring drift between group_layout and tiling:\n"
        f"  group_layout={sorted(gl_off)}\n  tiling      ={sorted(t_off)}"
    )


@pytest.mark.parametrize("orient", ["flat-top", "pointy-top"])
def test_group_layout_hex_outer_ring_matches_tiling(orient: str) -> None:
    gl_off = _gl_offsets(gl.outer_ring_centres, "hexagon", orient)
    t_off = _tiling_offsets("hexagon", orient, "outer")
    assert _offsets_match(gl_off, t_off), (
        f"hex/{orient} OUTER ring drift between group_layout and tiling:\n"
        f"  group_layout={sorted(gl_off)}\n  tiling      ={sorted(t_off)}"
    )


@pytest.mark.xfail(
    strict=True,
    reason="KNOWN (a76): group_layout square uses size=edge-width "
           "(apothem size/2); tiling square uses size=circumradius-based "
           "(apothem ~0.354*size).  Hexagon is the load-bearing shape and "
           "matches exactly; squares are experimental.  If this starts "
           "PASSING the square size-convention was reconciled -- remove the "
           "xfail.",
)
def test_group_layout_square_matches_tiling() -> None:
    gl_off = _gl_offsets(gl.first_ring_centres, "square", "flat-top")
    t_off = _tiling_offsets("square", "flat-top", "inner")
    assert _offsets_match(gl_off, t_off)
