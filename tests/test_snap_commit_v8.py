"""v0.8.0 Phase 3 — tests for the snap-commit dock writes.

Phase 3 augments the existing 5-case ``_try_spawn_master`` with
calls to :func:`_set_cell_dock` so every case that establishes a
link relationship ALSO writes the new dock fields
(``_dock_partner_id``, ``_dock_edge``, partner's
``_dock_children_by_edge``).

These tests:
- Verify dock edges are computed correctly from snap-committed
  positions.
- Verify reciprocal updates (child's pointer matches partner's
  reverse index).
- Verify each of the 5 cases writes dock fields consistently.

Phase 5 will read these fields to implement the dock-break + re-find
heuristic at cell-alone drag-end.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.shell.branding_loader import load_branding  # noqa: E402
from scriptree.shell.cell_registry import CellRegistry  # noqa: E402
from scriptree.shell.cell_window import (  # noqa: E402
    CellWindow,
    _compute_dock_edge,
    _set_cell_dock,
    _try_spawn_master,
)
from scriptree.shell.snap_engine import _neighbour_slot_centres  # noqa: E402


def _fresh_registry() -> CellRegistry:
    reg = CellRegistry.instance()
    for c in list(reg.all()):
        c.close()
    return reg


# ---------------------------------------------------------------------------
# _compute_dock_edge
# ---------------------------------------------------------------------------

def test_compute_dock_edge_finds_each_neighbour_slot() -> None:
    """A cell placed at each of a target's 6 slots should resolve to
    the correct edge index."""
    _fresh_registry()
    tgt = CellWindow(load_branding())
    tgt.show()
    tgt.move(500, 500)
    try:
        geo = tgt.geometry()
        cx = geo.x() + geo.width() / 2.0
        cy = geo.y() + geo.height() / 2.0
        slots = _neighbour_slot_centres(
            cx, cy, tgt._size_px, tgt._shape, tgt._orientation,
        )
        for expected_edge, (sx, sy) in enumerate(slots):
            edge = _compute_dock_edge((sx, sy), tgt)
            assert edge == expected_edge, (
                f"Slot {expected_edge} at ({sx}, {sy}) resolved to "
                f"edge {edge}"
            )
    finally:
        tgt.close()


def test_compute_dock_edge_returns_none_when_far_off() -> None:
    """A position not near any of the target's slots returns None."""
    _fresh_registry()
    tgt = CellWindow(load_branding())
    tgt.show()
    tgt.move(500, 500)
    try:
        # 1000 px away — nowhere near a slot.
        edge = _compute_dock_edge((1500, 1500), tgt)
        assert edge is None
    finally:
        tgt.close()


# ---------------------------------------------------------------------------
# _set_cell_dock — direct invocation
# ---------------------------------------------------------------------------

def test_set_cell_dock_writes_both_sides() -> None:
    """After ``_set_cell_dock(child, partner)``, both child fields
    are set AND partner's reverse index points at child."""
    _fresh_registry()
    branding = load_branding()
    partner = CellWindow(branding)
    partner.show()
    partner.move(500, 500)
    child = CellWindow(branding)
    child.show()
    try:
        # Position child at partner's first slot (N for flat-top).
        geo = partner.geometry()
        cx = geo.x() + geo.width() / 2.0
        cy = geo.y() + geo.height() / 2.0
        slots = _neighbour_slot_centres(
            cx, cy, partner._size_px,
            partner._shape, partner._orientation,
        )
        sx, sy = slots[0]
        # Convert centre to top-left.
        child.move(
            int(round(sx - child._size_px / 2)),
            int(round(sy - child._size_px / 2)),
        )
        _set_cell_dock(child, partner)
        assert child._dock_partner_id == partner._id
        assert child._dock_edge == 0
        assert partner._dock_children_by_edge.get(0) == child._id
    finally:
        child.close()
        partner.close()


def test_set_cell_dock_clears_prior_dock_relationship() -> None:
    """When a cell already has a dock partner, re-docking it to a
    new partner clears the old reverse index."""
    _fresh_registry()
    branding = load_branding()
    old_partner = CellWindow(branding)
    new_partner = CellWindow(branding)
    child = CellWindow(branding)
    old_partner.show()
    new_partner.show()
    child.show()
    old_partner.move(300, 300)
    new_partner.move(700, 700)
    try:
        # Manually wire old relationship.
        child._dock_partner_id = old_partner._id
        child._dock_edge = 2
        old_partner._dock_children_by_edge[2] = child._id

        # Position child at new_partner's slot 1 and dock.
        geo = new_partner.geometry()
        cx = geo.x() + geo.width() / 2.0
        cy = geo.y() + geo.height() / 2.0
        slots = _neighbour_slot_centres(
            cx, cy, new_partner._size_px,
            new_partner._shape, new_partner._orientation,
        )
        sx, sy = slots[1]
        child.move(
            int(round(sx - child._size_px / 2)),
            int(round(sy - child._size_px / 2)),
        )
        _set_cell_dock(child, new_partner)
        # New side wired.
        assert child._dock_partner_id == new_partner._id
        assert child._dock_edge == 1
        # Old side cleared.
        assert 2 not in old_partner._dock_children_by_edge
    finally:
        child.close()
        new_partner.close()
        old_partner.close()


def test_set_cell_dock_displaces_prior_child_at_same_edge() -> None:
    """If partner already has a cell docked at the edge child is
    snapping to, that previous cell's dock pointer gets cleared
    (one-child-per-edge invariant)."""
    _fresh_registry()
    branding = load_branding()
    partner = CellWindow(branding)
    prior = CellWindow(branding)
    newcomer = CellWindow(branding)
    partner.show()
    prior.show()
    newcomer.show()
    partner.move(500, 500)
    try:
        # Manually wire prior to edge 3 of partner.
        prior._dock_partner_id = partner._id
        prior._dock_edge = 3
        partner._dock_children_by_edge[3] = prior._id

        # Newcomer snaps to the same edge.
        geo = partner.geometry()
        cx = geo.x() + geo.width() / 2.0
        cy = geo.y() + geo.height() / 2.0
        slots = _neighbour_slot_centres(
            cx, cy, partner._size_px,
            partner._shape, partner._orientation,
        )
        sx, sy = slots[3]
        newcomer.move(
            int(round(sx - newcomer._size_px / 2)),
            int(round(sy - newcomer._size_px / 2)),
        )
        _set_cell_dock(newcomer, partner)
        # Newcomer owns edge 3 now.
        assert partner._dock_children_by_edge[3] == newcomer._id
        assert newcomer._dock_partner_id == partner._id
        assert newcomer._dock_edge == 3
        # Prior's dock pointer cleared.
        assert prior._dock_partner_id is None
        assert prior._dock_edge is None
    finally:
        newcomer.close()
        prior.close()
        partner.close()


# ---------------------------------------------------------------------------
# Symmetry invariant
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Fresh-master snap-engine wiring (Bug 2 regression)
# ---------------------------------------------------------------------------

def test_try_spawn_master_wires_new_master_to_snap_engine(
    monkeypatch,
) -> None:
    """v0.8.0a1+ramps Bug 2 regression — when ``_try_spawn_master``
    creates a new ring (master) from two docking cells, that master
    MUST be wired to the snap engine so a subsequent drag of the
    fresh ring shows the snap-preview overlay.

    Pre-fix symptom: the master could be dragged (``attach_drag``
    fired correctly) but the ``snapPreview`` signal never reached
    any ``show_snap_preview`` handler bound to the master's id —
    no listener had been connected for that id.  User-reported as
    "Docking the ring to a cell or forest does work, but it doesn't
    outline the docking area like the cells do (it should)."

    Test strategy: monkey-patch ``_wire_hex_to_snap`` to record the
    cells it is called with, then drive ``_try_spawn_master`` and
    assert the freshly-created master appears in the call log.
    """
    _fresh_registry()
    branding = load_branding()

    # Two adjacent cells that the snap engine would have committed.
    a = CellWindow(branding)
    b = CellWindow(branding)
    a.show()
    b.show()
    a.move(500, 500)
    b.move(500 + a._size_px, 500)  # edge-adjacent horizontally

    wired_ids: list[str] = []
    import scriptree.shell.ring_main as _rm

    def _spy(hex_win: CellWindow) -> None:
        wired_ids.append(hex_win._id)

    monkeypatch.setattr(_rm, "_wire_hex_to_snap", _spy)

    try:
        _try_spawn_master(a, b)
        reg = CellRegistry.instance()
        master_id = reg.master_of(a._id)
        assert master_id is not None, (
            "_try_spawn_master did not commit a master for the pair "
            "— preconditions wrong?"
        )
        assert master_id in wired_ids, (
            f"Fresh master {master_id[:8]} was NOT wired to the snap "
            f"engine.  wired_ids={[i[:8] for i in wired_ids]}.  Bug 2 "
            f"regression: the snap-preview overlay will not show when "
            f"this ring is dragged."
        )
    finally:
        for c in list(CellRegistry.instance().all()):
            c.close()


# ---------------------------------------------------------------------------
# Snap-shift dock-children cascade (Bug 4 regression)
# ---------------------------------------------------------------------------

def test_move_to_cascades_delta_to_dock_children() -> None:
    """v0.8.0a1+ramps Bug 4 regression — when ``move_to`` shifts a
    cell (e.g. via snap-commit or dock_with), every cell in this
    cell's ``_dock_children_by_edge`` follows by the same delta.

    User-reported: "when I dock the cell to the forest cluster and
    it shifts its position to dock, the cells docked to it don't
    reposition back to their docked locations (they should)."
    """
    _fresh_registry()
    branding = load_branding()
    parent = CellWindow(branding)
    parent.show()
    parent.move(500, 500)
    children: list[CellWindow] = []
    try:
        # Snap 3 cells to parent at distinct edges, wiring via
        # _set_cell_dock so the reverse index is consistent.
        geo = parent.geometry()
        cx = geo.x() + geo.width() / 2.0
        cy = geo.y() + geo.height() / 2.0
        slots = _neighbour_slot_centres(
            cx, cy, parent._size_px,
            parent._shape, parent._orientation,
        )
        for i in (0, 2, 4):
            sx, sy = slots[i]
            c = CellWindow(branding)
            c.show()
            c.move(
                int(round(sx - c._size_px / 2)),
                int(round(sy - c._size_px / 2)),
            )
            _set_cell_dock(c, parent)
            children.append(c)

        # Snapshot relative deltas before parent move.
        deltas_before = [
            (c.pos().x() - parent.pos().x(),
             c.pos().y() - parent.pos().y())
            for c in children
        ]

        # Simulate snap-commit: move parent by (60, 30).
        parent.move_to(parent.pos().x() + 60, parent.pos().y() + 30)

        deltas_after = [
            (c.pos().x() - parent.pos().x(),
             c.pos().y() - parent.pos().y())
            for c in children
        ]
        assert deltas_before == deltas_after, (
            f"Dock-children did not follow parent move_to.  "
            f"Before {deltas_before}, after {deltas_after}.  "
            f"Bug 4: cells docked to a snap-shifted cell stayed put."
        )
    finally:
        for c in children:
            c.close()
        parent.close()


def test_ring_move_to_carries_its_members() -> None:
    """v0.8.0a1+ramps Bug 6 verification — when a ring (master) is
    snap-committed (move_to) to a new position, its dock children
    (ring members) must follow.

    Ring members are wired as dock-children of the ring master via
    ``_set_cell_dock(member, master)`` in ``_try_spawn_master``.
    With the Bug 4 ``move_to`` cascade, those members move when
    the master moves through ``move_to``.

    User-reported regression: "when the ring ended up off the
    screen it docked to the forest, but it left its linked cells
    behind."

    Test strategy: build the ring by hand at exact slot positions
    (rather than going through ``_try_spawn_master`` which animates
    cells into position via ``_smooth_move`` and can't be
    deterministically verified in a synchronous test).
    """
    _fresh_registry()
    branding = load_branding()
    master = CellWindow(branding, role="master")
    master.show()
    master.move(500, 500)

    # Place 2 cells at exact slot positions and wire them as dock children.
    geo = master.geometry()
    cx = geo.x() + geo.width() / 2.0
    cy = geo.y() + geo.height() / 2.0
    slots = _neighbour_slot_centres(
        cx, cy, master._size_px, master._shape, master._orientation,
    )
    members: list[CellWindow] = []
    for i in (0, 3):  # N and S slots
        sx, sy = slots[i]
        m = CellWindow(branding)
        m.show()
        m.move(
            int(round(sx - m._size_px / 2)),
            int(round(sy - m._size_px / 2)),
        )
        # Wire ring membership (link parent) AND dock pointer.
        m._group_master_id = master._id
        m._link_parent_id = master._id
        master._members[m._id] = QPoint(m.pos())
        master._positioned.add(m._id)
        _set_cell_dock(m, master)
        members.append(m)

    # Sanity: dock pointers must be wired (otherwise the test is a no-op).
    assert all(m._dock_partner_id == master._id for m in members), (
        "Test setup failed: dock pointers not wired."
    )

    try:
        offsets_before = [
            (m.pos().x() - master.pos().x(),
             m.pos().y() - master.pos().y())
            for m in members
        ]
        master.move_to(master.pos().x() + 120, master.pos().y() + 80)
        offsets_after = [
            (m.pos().x() - master.pos().x(),
             m.pos().y() - master.pos().y())
            for m in members
        ]
        assert offsets_before == offsets_after, (
            f"Ring members did not follow master.move_to.  "
            f"Before {offsets_before}, after {offsets_after}.  "
            f"Bug 6: ring members left behind when ring relocates."
        )
    finally:
        for m in members:
            m.close()
        master.close()


def test_move_to_cascades_chain_of_dock_children() -> None:
    """A→B→C dock chain: when A is moved via move_to, both B and C
    must follow (recursive cascade)."""
    _fresh_registry()
    branding = load_branding()
    a = CellWindow(branding)
    b = CellWindow(branding)
    c = CellWindow(branding)
    a.show()
    b.show()
    c.show()
    a.move(500, 500)
    try:
        # Position b at a's slot 0, c at b's slot 0.
        a_geo = a.geometry()
        a_cx = a_geo.x() + a_geo.width() / 2.0
        a_cy = a_geo.y() + a_geo.height() / 2.0
        a_slots = _neighbour_slot_centres(
            a_cx, a_cy, a._size_px, a._shape, a._orientation,
        )
        bsx, bsy = a_slots[0]
        b.move(
            int(round(bsx - b._size_px / 2)),
            int(round(bsy - b._size_px / 2)),
        )
        _set_cell_dock(b, a)

        b_geo = b.geometry()
        b_cx = b_geo.x() + b_geo.width() / 2.0
        b_cy = b_geo.y() + b_geo.height() / 2.0
        b_slots = _neighbour_slot_centres(
            b_cx, b_cy, b._size_px, b._shape, b._orientation,
        )
        csx, csy = b_slots[0]
        c.move(
            int(round(csx - c._size_px / 2)),
            int(round(csy - c._size_px / 2)),
        )
        _set_cell_dock(c, b)

        b_delta = (b.pos().x() - a.pos().x(),
                   b.pos().y() - a.pos().y())
        c_delta = (c.pos().x() - b.pos().x(),
                   c.pos().y() - b.pos().y())

        a.move_to(a.pos().x() + 100, a.pos().y() + 50)

        assert (b.pos().x() - a.pos().x(),
                b.pos().y() - a.pos().y()) == b_delta, (
            "B's offset from A changed after A.move_to — B did not follow."
        )
        assert (c.pos().x() - b.pos().x(),
                c.pos().y() - b.pos().y()) == c_delta, (
            "C's offset from B changed — C did not follow the chain."
        )
    finally:
        c.close()
        b.close()
        a.close()


# ---------------------------------------------------------------------------
# Symmetry invariant
# ---------------------------------------------------------------------------

def test_dock_graph_symmetry_after_chain_of_writes() -> None:
    """Whatever pattern of docks we set up, the reverse-index
    invariant holds: for every cell c with _dock_partner_id == p
    and _dock_edge == e, partner._dock_children_by_edge[e] == c._id.
    """
    _fresh_registry()
    branding = load_branding()
    root = CellWindow(branding)
    root.show()
    root.move(500, 500)
    children: list[CellWindow] = []
    try:
        # Snap one cell to each of root's 6 edges.
        geo = root.geometry()
        cx = geo.x() + geo.width() / 2.0
        cy = geo.y() + geo.height() / 2.0
        slots = _neighbour_slot_centres(
            cx, cy, root._size_px, root._shape, root._orientation,
        )
        for i, (sx, sy) in enumerate(slots):
            c = CellWindow(branding)
            c.show()
            c.move(
                int(round(sx - c._size_px / 2)),
                int(round(sy - c._size_px / 2)),
            )
            _set_cell_dock(c, root)
            children.append(c)
        # Verify symmetry.
        for c in children:
            assert c._dock_partner_id == root._id
            assert c._dock_edge is not None
            assert (
                root._dock_children_by_edge.get(c._dock_edge) == c._id
            ), (
                f"Asymmetry: child {c._id[:8]} thinks it's at edge "
                f"{c._dock_edge} but root has "
                f"{root._dock_children_by_edge.get(c._dock_edge)} there"
            )
        # All 6 edges occupied.
        assert len(root._dock_children_by_edge) == 6
    finally:
        for c in children:
            c.close()
        root.close()
