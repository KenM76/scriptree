"""v0.8.0 Phase 2 — tests for link-driven drag cascade.

The corrected model:
* Ring drag moves every cell with ``_link_parent_id == ring._id``,
  regardless of whether the cell is in the ring's ``_positioned``
  dock cluster.
* Forest drag moves all linked rings unconditionally, plus
  forest-linked cells that have a dock path back to forest.
  Floating cells linked to forest with no dock path stay put.

Phase 2 implements this by widening the drag_targets set in
``CellWindow.moveEvent`` to union with
``registry.link_children_of(self._id)`` — additive only,
preserves all v0.6.x behaviour.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.shell.branding_loader import load_branding  # noqa: E402
from scriptree.shell.cell_registry import CellRegistry  # noqa: E402
from scriptree.shell.cell_window import CellWindow  # noqa: E402


def _fresh_registry() -> CellRegistry:
    reg = CellRegistry.instance()
    for c in list(reg.all()):
        c.close()
    return reg


def _simulate_master_drag(
    master: CellWindow, dx: int, dy: int,
) -> None:
    """Force a master-drag moveEvent that triggers GROUP_MOVE cascade.

    Sets _drag_started + _last_pos so the cascade-arm condition is
    met, then calls move() which fires moveEvent.  Resets
    _drag_started afterward so subsequent tests see a clean state.
    """
    master._drag_started = True
    master._last_pos = QPoint(master.pos())
    target = QPoint(master.pos().x() + dx, master.pos().y() + dy)
    master.move(target)
    master._drag_started = False


# ---------------------------------------------------------------------------
# Ring cascade: link-children move unconditionally
# ---------------------------------------------------------------------------

def test_ring_drag_moves_link_children_in_positioned() -> None:
    """Baseline: cells in the ring's _positioned set move with the
    ring (already true pre-P2, but verify P2 didn't break it)."""
    _fresh_registry()
    branding = load_branding()
    ring = CellWindow(branding, role="master")
    ring.show()
    ring.move(400, 400)
    cells: list[CellWindow] = []
    try:
        for i in range(3):
            c = CellWindow(branding)
            c.show()
            c.move(460 + i * 60, 400)
            ring._members[c._id] = QPoint(c.pos())
            ring._positioned.add(c._id)
            c._group_master_id = ring._id
            c._link_parent_id = ring._id  # P1 mirror
            cells.append(c)
        # Snapshot relative deltas.
        deltas_before = [
            (c.pos().x() - ring.pos().x(), c.pos().y() - ring.pos().y())
            for c in cells
        ]
        _simulate_master_drag(ring, 100, 50)
        deltas_after = [
            (c.pos().x() - ring.pos().x(), c.pos().y() - ring.pos().y())
            for c in cells
        ]
        assert deltas_before == deltas_after, (
            f"Cells in ring._positioned did not move rigidly with "
            f"the ring.  Before {deltas_before}, after {deltas_after}."
        )
    finally:
        for c in cells:
            c.close()
        ring.close()


def test_ring_drag_leaves_dragged_off_cell_alone() -> None:
    """v0.8.0a1+ramps Bug 10 — a cell that the user has dragged out
    of a ring (link parent still the ring, but NOT in the ring's
    ``_positioned`` set after ``_break_free_from_cluster`` ran) MUST
    stay put when the ring is later dragged.

    User-reported: "when I drag a cell off the ring, it should stay
    put when I drag the ring."  The original P2 behaviour cascaded
    every link-child unconditionally; v0.8.0a1+ramps generalises the
    forest's dock-path gate to rings — the cell has to be in the
    ring's ``_positioned`` cluster to follow.
    """
    _fresh_registry()
    branding = load_branding()
    ring = CellWindow(branding, role="master")
    ring.show()
    ring.move(400, 400)
    # Anchor cell — in _positioned, normal cluster member (will
    # still follow the ring drag).
    anchor = CellWindow(branding)
    anchor.show()
    anchor.move(460, 400)
    ring._members[anchor._id] = QPoint(anchor.pos())
    ring._positioned.add(anchor._id)
    anchor._group_master_id = ring._id
    anchor._link_parent_id = ring._id

    # Dragged-off cell — link parent is still the ring, but NOT in
    # _positioned (simulates _break_free_from_cluster having fired
    # at the 4 px drag threshold).
    pulled = CellWindow(branding)
    pulled.show()
    pulled.move(800, 200)
    pulled._group_master_id = ring._id
    pulled._link_parent_id = ring._id

    try:
        pos_before = (pulled.pos().x(), pulled.pos().y())
        anchor_delta_before = (
            anchor.pos().x() - ring.pos().x(),
            anchor.pos().y() - ring.pos().y(),
        )
        _simulate_master_drag(ring, 75, 40)
        pos_after = (pulled.pos().x(), pulled.pos().y())
        anchor_delta_after = (
            anchor.pos().x() - ring.pos().x(),
            anchor.pos().y() - ring.pos().y(),
        )
        # Pulled cell stays exactly where it was.
        assert pos_before == pos_after, (
            f"Dragged-off cell followed ring drag.  "
            f"Before {pos_before}, after {pos_after}.  Bug 10 "
            f"regression: the ring cascade should gate on "
            f"_positioned, not link membership."
        )
        # Anchor (in cluster) DOES follow — sanity that we didn't
        # break the in-cluster path.
        assert anchor_delta_before == anchor_delta_after, (
            f"Anchor cell offset from ring changed: "
            f"{anchor_delta_before} → {anchor_delta_after}.  Bug 10 "
            f"fix went too far — _positioned cells must still follow."
        )
    finally:
        pulled.close()
        anchor.close()
        ring.close()


# ---------------------------------------------------------------------------
# Forest cascade: rings follow unconditionally; floating cells gated
# ---------------------------------------------------------------------------

def test_forest_drag_does_not_move_loose_linked_ring() -> None:
    """v0.8.0a1+ramps spec — a ring linked to the forest but NOT in
    the forest's ``_positioned`` set (i.e. dragged out of the cluster
    so it sits on its own) must STAY PUT when the forest is dragged.

    User-reported regression from the first v0.8.0 sketch (which made
    rings cascade unconditionally): "once I make a ring that is not
    docked to the forest cluster it [shouldn't] move when I move the
    forest."  The forest-cascade gate now treats rings the same as
    cells — both require a dock-path proxy (``_positioned``
    membership) to follow.
    """
    _fresh_registry()
    branding = load_branding()
    forest = CellWindow(branding, role="master")
    forest._is_forest_master = True
    forest.show()
    forest.move(500, 500)

    ring = CellWindow(branding, role="master")
    ring.show()
    ring.move(700, 500)
    ring._group_master_id = forest._id
    ring._link_parent_id = forest._id
    # Deliberately NOT in forest._positioned — loose-linked ring.

    try:
        pos_before = (ring.pos().x(), ring.pos().y())
        _simulate_master_drag(forest, 60, 30)
        pos_after = (ring.pos().x(), ring.pos().y())
        assert pos_before == pos_after, (
            f"Loose-linked ring moved with forest drag.  "
            f"Before {pos_before}, after {pos_after}.  Per "
            f"v0.8.0a1+ramps spec the forest cascade must gate "
            f"rings on the same _positioned dock-path proxy used "
            f"for cells."
        )
    finally:
        ring.close()
        forest.close()


def test_fresh_ring_spawned_from_loose_cells_does_not_dock_to_forest() -> None:
    """v0.8.0a1+ramps Bug 7 regression — when two forest-linked
    loose cells dock together to spawn a fresh ring, that ring is
    link-attached to the forest (so cells shaken out re-link to
    forest correctly) but MUST NOT be added to ``forest._positioned``.

    User-reported scenario: "the separated ring still drags when
    forest drags but only under this specific condition: I drag a
    cell away from the group, then I drag another cell from the
    group directly to dock with the other cell and form a ring."

    Pre-fix path: the v0.6.14 forest-link-preservation block in
    ``_try_spawn_master`` called ``forest._positioned.add(master._id)``
    unconditionally, so the forest cascade picked the ring up the
    next time the forest was dragged — even though the ring sat at
    an arbitrary position with no dock path back to the forest.
    """
    _fresh_registry()
    branding = load_branding()
    forest = CellWindow(branding, role="master")
    forest._is_forest_master = True
    forest.show()
    forest.move(500, 500)

    # Two cells loose-linked to forest (link parent = forest, NOT in
    # forest._positioned — mirrors what _break_free_from_cluster
    # produces after the user drags a cell away from the cluster).
    a = CellWindow(branding); a.show(); a.move(900, 200)
    a._group_master_id = forest._id
    a._link_parent_id = forest._id
    forest._members[a._id] = QPoint(a.pos())

    b = CellWindow(branding); b.show(); b.move(900 + a._size_px, 200)
    b._group_master_id = forest._id
    b._link_parent_id = forest._id
    forest._members[b._id] = QPoint(b.pos())

    from scriptree.shell.cell_window import _try_spawn_master
    _try_spawn_master(a, b)

    reg = CellRegistry.instance()
    ring_id = reg.master_of(a._id)
    assert ring_id is not None and ring_id != forest._id, (
        "Expected a fresh ring to spawn for the loose-linked pair."
    )
    ring = reg.get(ring_id)
    assert ring is not None

    # Sanity: ring is link-child of forest.
    assert ring._link_parent_id == forest._id, (
        f"Fresh ring's link parent should be forest, got "
        f"{ring._link_parent_id!r}"
    )

    # Bug 7 — must NOT be in forest._positioned (would cascade).
    assert ring._id not in forest._positioned, (
        f"Fresh ring {ring._id[:8]} was added to forest._positioned. "
        f"That makes the forest cascade pull it along on every forest "
        f"drag even though the ring isn't dock-adjacent to forest."
    )

    # And the forest-drag itself must leave the ring alone.
    pos_before = (ring.pos().x(), ring.pos().y())
    _simulate_master_drag(forest, 70, 40)
    pos_after = (ring.pos().x(), ring.pos().y())
    assert pos_before == pos_after, (
        f"Fresh ring {ring._id[:8]} followed forest drag.  "
        f"Before {pos_before}, after {pos_after}.  Bug 7 leak."
    )


def test_forest_drag_moves_docked_ring() -> None:
    """Companion to test_forest_drag_does_not_move_loose_linked_ring:
    a ring that IS in the forest's ``_positioned`` set (i.e. dock-
    attached to the forest cluster) MUST follow the forest drag."""
    _fresh_registry()
    branding = load_branding()
    forest = CellWindow(branding, role="master")
    forest._is_forest_master = True
    forest.show()
    forest.move(500, 500)

    ring = CellWindow(branding, role="master")
    ring.show()
    ring.move(700, 500)
    ring._group_master_id = forest._id
    ring._link_parent_id = forest._id
    forest._members[ring._id] = QPoint(ring.pos())
    forest._positioned.add(ring._id)  # dock-attached ring

    try:
        delta_before = (
            ring.pos().x() - forest.pos().x(),
            ring.pos().y() - forest.pos().y(),
        )
        _simulate_master_drag(forest, 60, 30)
        delta_after = (
            ring.pos().x() - forest.pos().x(),
            ring.pos().y() - forest.pos().y(),
        )
        assert delta_before == delta_after, (
            f"Dock-attached ring did not follow forest drag.  "
            f"Before {delta_before}, after {delta_after}.  The "
            f"existing _positioned cascade should pick it up; if "
            f"this regresses, GROUP_MOVE skipped rings."
        )
    finally:
        ring.close()
        forest.close()


def test_forest_drag_leaves_floating_forest_linked_cell_alone() -> None:
    """A cell linked directly to forest, NOT in forest._positioned
    (no dock path), MUST stay put when forest drags.

    Per the user's spec: 'if there is no dock path back to the
    forest then those objects stay put when the forest is dragged.'
    """
    _fresh_registry()
    branding = load_branding()
    forest = CellWindow(branding, role="master")
    forest._is_forest_master = True
    forest.show()
    forest.move(500, 500)

    # A standalone cell linked to forest but floating — no dock path.
    floater = CellWindow(branding)
    floater.show()
    floater.move(900, 900)
    floater._group_master_id = forest._id
    floater._link_parent_id = forest._id
    # NOT in forest._positioned.

    try:
        pos_before = (floater.pos().x(), floater.pos().y())
        _simulate_master_drag(forest, 50, 50)
        pos_after = (floater.pos().x(), floater.pos().y())
        assert pos_before == pos_after, (
            f"Floating forest-linked cell moved with forest drag.  "
            f"Before {pos_before}, after {pos_after}.  P2 forest "
            f"cascade should gate cell-kind link children on dock "
            f"path (proxied in P2 by _positioned membership)."
        )
    finally:
        floater.close()
        forest.close()


def test_three_deep_cascade_forest_to_ring_to_cell() -> None:
    """Drag the forest; ring follows; cells linked to ring follow
    via the ring's own moveEvent cascade triggered by its move.
    All three end up shifted by the same delta."""
    _fresh_registry()
    branding = load_branding()
    forest = CellWindow(branding, role="master")
    forest._is_forest_master = True
    forest.show()
    forest.move(500, 500)

    ring = CellWindow(branding, role="master")
    ring.show()
    ring.move(700, 500)
    ring._group_master_id = forest._id
    ring._link_parent_id = forest._id
    # v0.8.0a1+ramps spec — for the forest cascade to reach the ring,
    # the ring must be dock-attached (in forest._positioned).  Without
    # this the loose-linked-ring test asserts the ring stays put.
    forest._members[ring._id] = QPoint(ring.pos())
    forest._positioned.add(ring._id)

    cell = CellWindow(branding)
    cell.show()
    cell.move(760, 500)
    ring._members[cell._id] = QPoint(cell.pos())
    ring._positioned.add(cell._id)
    cell._group_master_id = ring._id
    cell._link_parent_id = ring._id

    try:
        # Capture relative positions.
        ring_off = (
            ring.pos().x() - forest.pos().x(),
            ring.pos().y() - forest.pos().y(),
        )
        cell_off = (
            cell.pos().x() - ring.pos().x(),
            cell.pos().y() - ring.pos().y(),
        )
        _simulate_master_drag(forest, 80, 80)
        # All three should still be at the same RELATIVE offsets.
        new_ring_off = (
            ring.pos().x() - forest.pos().x(),
            ring.pos().y() - forest.pos().y(),
        )
        new_cell_off = (
            cell.pos().x() - ring.pos().x(),
            cell.pos().y() - ring.pos().y(),
        )
        assert new_ring_off == ring_off, (
            f"Ring offset from forest changed: {ring_off} → {new_ring_off}"
        )
        assert new_cell_off == cell_off, (
            f"Cell offset from ring changed: {cell_off} → {new_cell_off}"
        )
    finally:
        cell.close()
        ring.close()
        forest.close()
