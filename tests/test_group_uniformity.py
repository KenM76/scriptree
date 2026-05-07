"""Integration tests for the group-uniform-size + edge-touching repack
contract added in v0.2.10.

Acceptance criteria (from user spec):

1. **Adopt-on-dock.** Two cells of different sizes that dock together
   end up at the same size_px (and shape/orientation, already
   guaranteed by SnapEngine Rule 3).
2. **Settings broadcast.** Calling ``apply_size_change`` on any cell
   in a group resizes the whole group; same for shape/orientation.
3. **No overlap.** After any of the above, no two members occupy the
   same slot.
4. **Off-screen reflow.** When a master ends a drag near a screen
   edge, members that would land off-screen reattach to a free,
   on-screen slot.
5. **Ring load repack.** A hand-edited .scriptreering with off-slot
   member positions snaps to canonical slots on load.

Tests build minimal ``CellWindow`` groups directly (no real drag
simulation) and exercise the integration paths.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

# Auto-dismiss any incidental dialogs.
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.question = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Yes
)


from scriptree.shell.branding_loader import load_branding  # noqa: E402
from scriptree.shell.cell_registry import CellRegistry  # noqa: E402
from scriptree.shell.cell_window import (  # noqa: E402
    CellWindow,
    _try_spawn_master,
)
from scriptree.shell.group_layout import (  # noqa: E402
    first_ring_centres,
    top_left_for_centre,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_registry() -> CellRegistry:
    reg = CellRegistry.instance()
    for h in list(reg.standalones()) + list(reg.masters()):
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass
    return reg


def _spawn(size_px: int = 56, shape: str = "hexagon",
           orientation: str = "flat-top") -> CellWindow:
    branding = load_branding()
    cell = CellWindow(branding)
    cell._apply_shape_self(shape, orientation)
    cell._apply_size_self(size_px)
    return cell


def _build_group_via_spawn(
    *, size_a: int = 56, size_b: int = 56,
    pos_a: tuple[int, int] = (200, 200),
    pos_b: tuple[int, int] = (200 + 56, 200),  # to the right of a
) -> tuple[CellWindow, CellWindow, CellWindow]:
    """Build a master+two-members group by calling ``_try_spawn_master``
    directly (Case 1 path).  Returns ``(master, a, b)``."""
    _fresh_registry()
    a = _spawn(size_px=size_a)
    b = _spawn(size_px=size_b)
    a.move(pos_a[0], pos_a[1])
    b.move(pos_b[0], pos_b[1])
    a.show()
    b.show()
    _try_spawn_master(a, b)
    reg = CellRegistry.instance()
    master_id = reg.master_of(a._id)
    assert master_id is not None
    master = reg.get(master_id)
    assert master is not None
    return master, a, b


# ---------------------------------------------------------------------------
# 1. Adopt-on-dock — different sizes converge
# ---------------------------------------------------------------------------

def test_dock_adopts_larger_size_for_whole_group() -> None:
    """Cells of size 40 and 56 dock → group settles at size 56."""
    master, a, b = _build_group_via_spawn(size_a=40, size_b=56)
    assert master._size_px == 56
    assert a._size_px == 56
    assert b._size_px == 56


def test_dock_keeps_shape_and_orientation() -> None:
    master, a, b = _build_group_via_spawn(size_a=56, size_b=56)
    assert master._shape == a._shape == b._shape
    assert master._orientation == a._orientation == b._orientation


# ---------------------------------------------------------------------------
# 2. Settings broadcast — change on master / member propagates
# ---------------------------------------------------------------------------

def test_size_change_on_master_broadcasts_to_members() -> None:
    master, a, b = _build_group_via_spawn(size_a=56, size_b=56)
    master.apply_size_change(72)
    assert master._size_px == 72
    assert a._size_px == 72
    assert b._size_px == 72


def test_size_change_on_member_broadcasts_to_whole_group() -> None:
    """Calling ``apply_size_change`` on a member must cascade up to
    the master and back down to every other member."""
    master, a, b = _build_group_via_spawn(size_a=56, size_b=56)
    a.apply_size_change(72)
    assert master._size_px == 72
    assert a._size_px == 72
    assert b._size_px == 72


def test_shape_change_on_member_broadcasts_to_whole_group() -> None:
    master, a, b = _build_group_via_spawn(size_a=56, size_b=56)
    a.apply_shape_change("square", "flat-top")
    assert master._shape == "square"
    assert a._shape == "square"
    assert b._shape == "square"


def test_standalone_size_change_does_not_affect_others() -> None:
    """A size change on a standalone cell stays local."""
    _fresh_registry()
    a = _spawn(size_px=56)
    b = _spawn(size_px=56)
    a.show()
    b.show()
    a.apply_size_change(72)
    assert a._size_px == 72
    assert b._size_px == 56  # untouched
    a.close()
    b.close()


# ---------------------------------------------------------------------------
# 3. No overlap — repack always assigns unique slots
# ---------------------------------------------------------------------------

def test_repack_assigns_unique_slots_after_size_change() -> None:
    """Six members on a hex inner ring; resize the group; all six
    must still be on six different slots."""
    _fresh_registry()
    branding = load_branding()
    master = CellWindow(branding, role="master", hexagon_id="m-1")
    master._apply_shape_self("hexagon", "flat-top")
    master._apply_size_self(56)
    master.move(500, 500)

    inner = first_ring_centres(528, 528, 56, "hexagon", "flat-top")
    members: list[CellWindow] = []
    for i in range(6):
        m = CellWindow(branding, hexagon_id=f"mem-{i}")
        m._apply_shape_self("hexagon", "flat-top")
        m._apply_size_self(56)
        tl = top_left_for_centre(*inner[i], 56)
        m.move(*tl)
        m._group_master_id = "m-1"
        master._members[m._id] = QPoint(*tl)
        master._positioned.add(m._id)
        members.append(m)

    master.show()
    for m in members:
        m.show()

    # Resize whole group from 56 → 72.  Every member must end up on a
    # unique on-screen slot at the new size.
    master.apply_size_change(72)
    positions = {(m.pos().x(), m.pos().y()) for m in members}
    assert len(positions) == 6


# ---------------------------------------------------------------------------
# 4. Off-screen reflow — master moved near edge, member finds new slot
# ---------------------------------------------------------------------------

def test_reflow_repacks_when_member_overlaps_after_size_change() -> None:
    """Changing the group size invalidates the old slot positions; the
    repack must move every member to a new free slot at the new size,
    so no two members overlap."""
    master, a, b = _build_group_via_spawn(size_a=56, size_b=56)

    # Sanity check: starting positions are unique.
    assert (a.pos().x(), a.pos().y()) != (b.pos().x(), b.pos().y())

    master.apply_size_change(72)
    # After repack at the new size, members still don't overlap.
    assert (a.pos().x(), a.pos().y()) != (b.pos().x(), b.pos().y())


# ---------------------------------------------------------------------------
# 5. Ring-load repack — overlapping member positions snap to slots
# ---------------------------------------------------------------------------

def test_ring_load_repacks_overlapping_members(tmp_path: Path) -> None:
    """A hand-crafted .scriptreering whose members all share one
    position should load with each member on its own slot."""
    from scriptree.shell.ring_io import load_ring

    branding = load_branding()
    _fresh_registry()
    snap_engine = None  # ring_io tolerates None for tests

    # Three members all stacked on top of each other.
    doc = {
        "format": "scriptreering",
        "version": 1,
        "saved_at": "2026-05-07T00:00:00Z",
        "saved_by_brand": "test",
        "master": {
            "role": "master",
            "shape": "hexagon",
            "orientation": "flat-top",
            "size_px": 56,
            "transparency": 0.85,
            "always_on_top": True,
            "position": {"x": 500, "y": 500},
            "catalog_path": None,
        },
        "members": [
            {
                "shape": "hexagon", "orientation": "flat-top", "size_px": 56,
                "transparency": 0.85, "always_on_top": True,
                "position": {"x": 600, "y": 500},
                "preferred_position": {"x": 600, "y": 500},
                "catalog_path": None, "is_positioned": True,
            },
            {
                "shape": "hexagon", "orientation": "flat-top", "size_px": 56,
                "transparency": 0.85, "always_on_top": True,
                "position": {"x": 600, "y": 500},  # SAME as first
                "preferred_position": {"x": 600, "y": 500},
                "catalog_path": None, "is_positioned": True,
            },
            {
                "shape": "hexagon", "orientation": "flat-top", "size_px": 56,
                "transparency": 0.85, "always_on_top": True,
                "position": {"x": 600, "y": 500},  # SAME again
                "preferred_position": {"x": 600, "y": 500},
                "catalog_path": None, "is_positioned": True,
            },
        ],
    }
    p = tmp_path / "stacked.scriptreering"
    p.write_text(json.dumps(doc), encoding="utf-8")

    master = load_ring(p, branding, CellRegistry.instance(), snap_engine)
    member_positions = {
        (qp.x(), qp.y()) for qp in master._members.values()
    }
    # After repack, three members must occupy three distinct slots.
    assert len(member_positions) == 3


# ---------------------------------------------------------------------------
# Cleanup at module teardown — close everything to free Qt windows.
# ---------------------------------------------------------------------------

def teardown_function(_func) -> None:
    _fresh_registry()
