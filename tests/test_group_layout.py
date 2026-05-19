"""Pure-logic tests for ``scriptree.shell.group_layout``.

No QApplication needed — every assertion runs against integer pixel
math with synthetic ``screen_rect`` rectangles.
"""
from __future__ import annotations

import math

from scriptree.shell.group_layout import (
    _nearest_slot_index,
    _slot_search_order,
    all_slot_centres,
    first_ring_centres,
    members_at_canonical_slots,
    outer_ring_centres,
    repack,
    slot_fits_on_screen,
    top_left_for_centre,
)


# ---------------------------------------------------------------------------
# Slot geometry
# ---------------------------------------------------------------------------

def test_first_ring_hex_flat_top_has_six_slots() -> None:
    slots = first_ring_centres(500, 500, 56, "hexagon", "flat-top")
    assert len(slots) == 6


def test_first_ring_hex_pointy_top_has_six_slots() -> None:
    slots = first_ring_centres(500, 500, 56, "hexagon", "pointy-top")
    assert len(slots) == 6


def test_first_ring_square_has_four_slots() -> None:
    slots = first_ring_centres(500, 500, 56, "square", "flat-top")
    assert len(slots) == 4


def test_outer_ring_hex_has_twelve_slots() -> None:
    slots = outer_ring_centres(500, 500, 56, "hexagon", "flat-top")
    assert len(slots) == 12


def test_outer_ring_square_has_eight_slots() -> None:
    slots = outer_ring_centres(500, 500, 56, "square", "flat-top")
    assert len(slots) == 8


def test_first_ring_hex_slots_at_honeycomb_distance() -> None:
    """For flat-top hexagons of bounding-box width ``size_px``, the
    edge-touching centre-to-centre distance is ``sqrt(3)/2 *
    size_px`` ≈ 0.866 * size_px (matches snap_engine's offsets)."""
    cx, cy, sz = 500, 500, 56
    expected = math.sqrt(3) / 2 * sz
    for slot_cx, slot_cy in first_ring_centres(cx, cy, sz, "hexagon", "flat-top"):
        d = math.hypot(slot_cx - cx, slot_cy - cy)
        assert abs(d - expected) < 0.01, (
            f"slot at ({slot_cx},{slot_cy}) is {d:.2f}px from centre, "
            f"want {expected:.2f}"
        )


def test_first_ring_square_slots_at_size_distance() -> None:
    """For squares the edge-touching distance is exactly ``size_px``."""
    cx, cy, sz = 500, 500, 64
    for slot_cx, slot_cy in first_ring_centres(cx, cy, sz, "square", ""):
        d = math.hypot(slot_cx - cx, slot_cy - cy)
        assert abs(d - sz) < 0.01


def test_top_left_centred_on_size_px() -> None:
    assert top_left_for_centre(500, 500, 56) == (472, 472)
    assert top_left_for_centre(500, 500, 64) == (468, 468)


# ---------------------------------------------------------------------------
# Screen-fits
# ---------------------------------------------------------------------------

def test_slot_fits_on_screen_inside() -> None:
    assert slot_fits_on_screen(500, 500, 56, (0, 0, 1920, 1080))


def test_slot_fits_on_screen_off_left() -> None:
    assert not slot_fits_on_screen(20, 500, 56, (0, 0, 1920, 1080))


def test_slot_fits_on_screen_off_top() -> None:
    assert not slot_fits_on_screen(500, 20, 56, (0, 0, 1920, 1080))


def test_slot_fits_on_screen_off_right() -> None:
    assert not slot_fits_on_screen(1900, 500, 56, (0, 0, 1920, 1080))


def test_slot_fits_on_screen_off_bottom() -> None:
    assert not slot_fits_on_screen(500, 1060, 56, (0, 0, 1920, 1080))


def test_slot_fits_none_screen_is_unconstrained() -> None:
    assert slot_fits_on_screen(0, 0, 56, None)


# ---------------------------------------------------------------------------
# Direction inference
# ---------------------------------------------------------------------------

def test_nearest_slot_index_picks_closest() -> None:
    slots = [(0, 0), (10, 0), (0, 10)]
    assert _nearest_slot_index(0, 0, slots) == 0
    assert _nearest_slot_index(11, 1, slots) == 1
    assert _nearest_slot_index(-2, 9, slots) == 2


def test_search_order_widens_from_preferred() -> None:
    assert _slot_search_order(0, 6) == [0, 1, 5, 2, 4, 3]
    assert _slot_search_order(2, 6) == [2, 3, 1, 4, 0, 5]
    assert _slot_search_order(0, 4) == [0, 1, 3, 2]


# ---------------------------------------------------------------------------
# repack — happy paths
# ---------------------------------------------------------------------------

def test_repack_single_member_uses_preferred_inner_slot() -> None:
    inner = first_ring_centres(500, 500, 56, "hexagon", "flat-top")
    # Member centred on the SE slot — should land on slot index 2.
    se_cx, se_cy = inner[2]
    member_tl = (round(se_cx - 28), round(se_cy - 28))
    out = repack(
        master_top_left=(472, 472),
        size_px=56,
        shape="hexagon", orientation="flat-top",
        members={"m1": member_tl},
    )
    assert out["m1"] == top_left_for_centre(*inner[2], 56)


def test_repack_assigns_unique_slots_no_overlap() -> None:
    """Six members all preferring the same direction must end up on
    six different slots — no overlap allowed."""
    inner = first_ring_centres(500, 500, 56, "hexagon", "flat-top")
    n_pref = inner[0]
    members = {
        f"m{i}": top_left_for_centre(n_pref[0] + i * 0.001, n_pref[1] + i * 0.001, 56)
        for i in range(6)
    }
    out = repack((472, 472), 56, "hexagon", "flat-top", members)
    placed = [v for v in out.values() if v is not None]
    assert len(placed) == 6
    assert len(set(placed)) == 6  # all unique


def test_repack_falls_back_to_outer_ring_when_inner_full() -> None:
    """7th member should land on the outer ring."""
    inner = first_ring_centres(500, 500, 56, "hexagon", "flat-top")
    members = {f"m{i}": top_left_for_centre(*inner[i], 56) for i in range(6)}
    members["m6"] = top_left_for_centre(*inner[0], 56)  # also wants N
    out = repack((472, 472), 56, "hexagon", "flat-top", members)
    inner_tls = {top_left_for_centre(*c, 56) for c in inner}
    outer_tls = {
        top_left_for_centre(*c, 56)
        for c in outer_ring_centres(500, 500, 56, "hexagon", "flat-top")
    }
    # Six members on inner, one on outer.
    inner_count = sum(1 for v in out.values() if v in inner_tls)
    outer_count = sum(1 for v in out.values() if v in outer_tls)
    assert inner_count == 6
    assert outer_count == 1


def test_repack_closest_member_wins_first_ring_slot() -> None:
    """When the inner ring has 6 free slots and we pass 6 members of
    varying distance, the closest member should NEVER end up on the
    outer ring."""
    inner = first_ring_centres(500, 500, 56, "hexagon", "flat-top")
    members = {
        # Six members all preferring direction 0 (N) but at different
        # distances from the master.
        "near": top_left_for_centre(inner[0][0], inner[0][1] - 1, 56),
        "mid1": top_left_for_centre(inner[0][0], inner[0][1] - 30, 56),
        "mid2": top_left_for_centre(inner[0][0], inner[0][1] - 60, 56),
        "far1": top_left_for_centre(inner[0][0], inner[0][1] - 120, 56),
        "far2": top_left_for_centre(inner[0][0], inner[0][1] - 200, 56),
        "far3": top_left_for_centre(inner[0][0], inner[0][1] - 280, 56),
    }
    out = repack((472, 472), 56, "hexagon", "flat-top", members)
    inner_tls = {top_left_for_centre(*c, 56) for c in inner}
    assert out["near"] in inner_tls


def test_repack_square_inner_ring_caps_at_four() -> None:
    inner = first_ring_centres(500, 500, 64, "square", "")
    members = {f"m{i}": top_left_for_centre(*inner[i], 64) for i in range(4)}
    members["m4"] = top_left_for_centre(*inner[0], 64)
    out = repack((468, 468), 64, "square", "", members)
    inner_tls = {top_left_for_centre(*c, 64) for c in inner}
    on_inner = sum(1 for v in out.values() if v in inner_tls)
    assert on_inner == 4
    # m4 must not be on the inner ring.
    assert out["m4"] not in inner_tls


# ---------------------------------------------------------------------------
# Off-screen reflow
# ---------------------------------------------------------------------------

def test_repack_skips_off_screen_inner_slot() -> None:
    """Master at the right edge — the E slot won't fit; the member
    that wants E should fall back to a different valid direction."""
    # Master right against a 500x500 screen.
    sz = 56
    master_tl = (500 - sz, 200)
    master_cx = master_tl[0] + sz / 2
    master_cy = master_tl[1] + sz / 2
    inner = first_ring_centres(master_cx, master_cy, sz, "hexagon", "flat-top")
    # NE slot (idx 1) has cx = master_cx + 0.75 * sz → 500-28+42 = 514 → off-screen at right=500
    members = {"m1": top_left_for_centre(*inner[1], sz)}
    out = repack(master_tl, sz, "hexagon", "flat-top", members,
                 screen_rect=(0, 0, 500, 500))
    placed_tl = out["m1"]
    assert placed_tl is not None
    # Placed member must be fully on-screen.
    assert placed_tl[0] >= 0 and placed_tl[1] >= 0
    assert placed_tl[0] + sz <= 500 and placed_tl[1] + sz <= 500


def test_repack_returns_none_when_no_slot_fits() -> None:
    """A 1x1 screen rect leaves zero room → member is unplaced."""
    out = repack(
        master_top_left=(0, 0),
        size_px=56,
        shape="hexagon", orientation="flat-top",
        members={"m1": (200, 200)},
        screen_rect=(0, 0, 56, 56),  # only the master fits
    )
    assert out["m1"] is None


# ---------------------------------------------------------------------------
# Shape-shrink: hex(6) → square(4) drops two members to outer ring
# ---------------------------------------------------------------------------

def test_repack_shape_change_hex_to_square_reassigns_extras() -> None:
    """Six members on a hex inner ring re-packed as squares (4 inner
    slots) → four stay on inner, two move to outer."""
    inner_hex = first_ring_centres(500, 500, 56, "hexagon", "flat-top")
    members = {f"m{i}": top_left_for_centre(*inner_hex[i], 56) for i in range(6)}

    out = repack(
        master_top_left=(472, 472),
        size_px=56,
        shape="square", orientation="",
        members=members,
    )
    inner_sq = first_ring_centres(500, 500, 56, "square", "")
    outer_sq = outer_ring_centres(500, 500, 56, "square", "")
    inner_tls = {top_left_for_centre(*c, 56) for c in inner_sq}
    outer_tls = {top_left_for_centre(*c, 56) for c in outer_sq}

    on_inner = sum(1 for v in out.values() if v in inner_tls)
    on_outer = sum(1 for v in out.values() if v in outer_tls)
    assert on_inner == 4
    assert on_outer == 2


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_repack_is_deterministic_for_identical_input() -> None:
    inner = first_ring_centres(500, 500, 56, "hexagon", "flat-top")
    members = {f"m{i}": top_left_for_centre(*inner[i], 56) for i in range(6)}
    a = repack((472, 472), 56, "hexagon", "flat-top", members)
    b = repack((472, 472), 56, "hexagon", "flat-top", members)
    assert a == b


# ---------------------------------------------------------------------------
# members_at_canonical_slots
# ---------------------------------------------------------------------------

def test_canonical_check_true_when_already_on_slots() -> None:
    inner = first_ring_centres(500, 500, 56, "hexagon", "flat-top")
    members = {f"m{i}": top_left_for_centre(*inner[i], 56) for i in range(3)}
    assert members_at_canonical_slots((472, 472), 56, "hexagon", "flat-top", members)


def test_canonical_check_false_when_overlapping() -> None:
    inner = first_ring_centres(500, 500, 56, "hexagon", "flat-top")
    members = {
        "m1": top_left_for_centre(*inner[0], 56),
        "m2": top_left_for_centre(*inner[0], 56),  # same slot!
    }
    assert not members_at_canonical_slots((472, 472), 56, "hexagon", "flat-top", members)


# ---------------------------------------------------------------------------
# repack — surgical reflow via the ``fixed`` parameter (V3 v0.3.16+)
# ---------------------------------------------------------------------------

def test_repack_fixed_members_keep_their_position() -> None:
    """A fixed member's position is returned verbatim — no snap to
    a slot, no reassignment.  Used by surgical reflow."""
    inner = first_ring_centres(500, 500, 56, "hexagon", "flat-top")
    n_pos = top_left_for_centre(*inner[0], 56)
    # Use a deliberately off-canonical position for the fixed
    # member so we can detect any accidental snap-to-slot.
    fixed_pos = (n_pos[0] + 5, n_pos[1] + 7)
    members = {
        "fixed": fixed_pos,
        "loose": top_left_for_centre(*inner[1], 56),
    }
    out = repack(
        (472, 472), 56, "hexagon", "flat-top", members,
        fixed={"fixed"},
    )
    # Fixed member's position is byte-identical to input.
    assert out["fixed"] == fixed_pos
    # Loose member still landed on a valid slot.
    assert out["loose"] is not None


def test_repack_fixed_members_block_their_slot() -> None:
    """Non-fixed members must NOT be assigned to the slot a fixed
    member is occupying.  Without slot-blocking the loose member
    could overlap the fixed one."""
    inner = first_ring_centres(500, 500, 56, "hexagon", "flat-top")
    # Fixed member sits exactly on inner[3].  Loose member also
    # prefers inner[3] (same direction).  After repack, loose must
    # land elsewhere.
    fixed_pos = top_left_for_centre(*inner[3], 56)
    loose_pos = top_left_for_centre(
        inner[3][0] + 0.001, inner[3][1] + 0.001, 56,
    )
    members = {
        "fixed": fixed_pos,
        "loose": loose_pos,
    }
    out = repack(
        (472, 472), 56, "hexagon", "flat-top", members,
        fixed={"fixed"},
    )
    assert out["fixed"] == fixed_pos
    assert out["loose"] is not None
    assert out["loose"] != fixed_pos


def test_repack_no_fixed_reproduces_legacy_behaviour() -> None:
    """``fixed=None`` (default) preserves pre-v0.3.16 behaviour:
    every member is up for reassignment, fixed parameter is a
    purely additive opt-in."""
    inner = first_ring_centres(500, 500, 56, "hexagon", "flat-top")
    # Member at a non-canonical position should be snapped onto a
    # slot when fixed=None.
    bad_pos = (inner[0][0] - 28 + 17, inner[0][1] - 28 + 19)
    members = {"m": bad_pos}
    out = repack((472, 472), 56, "hexagon", "flat-top", members)
    # Snapped to a slot — not the input position.
    assert out["m"] != bad_pos
    assert out["m"] in [
        top_left_for_centre(*c, 56) for c in inner
    ]
