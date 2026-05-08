"""Tests pinning the v0.3.17 "no reshift on docking" contract.

Per direct user direction the runtime invariant is:

    "moving one element does not cause a reshift in the others ...
     and it should dock to where I put it."

Concretely:

  * **Case 5** (cell repositioned within its own group) — only the
    moved cell's position changes; siblings stay verbatim.
  * **Case 4** (cell transfers between groups) — neither the old
    group's survivors nor the new group's existing members shift.
  * **Cases 2 / 3** (standalone joins existing group) — the
    group's existing members keep their positions; only the
    newcomer arrives at the snap-committed edge.
  * **Member close** — closing a cell leaves a gap; remaining
    members stay where the user placed them.
  * **Drag-drop catalog onto ring** (``_drop_spawn_member_and_link``)
    — only the new cell gets a slot; existing members stay verbatim.
  * **Forest auto-attach of a ring** — same rule: existing forest
    members keep their positions.

These are unit-level tests against the bookkeeping layer, not the
visual layer.  We assert the master's ``_members`` dict and the
widget positions of siblings remain unchanged across each
operation.

Vocabulary used in the tests (matching the user's terminology):

    associated      — has ``_group_master_id`` set; belongs to a
                      ring or to the forest.
    docked          — physically adjacent on a specific edge;
                      tracked in ``_docked_to`` / ``_dock_partners``.
    associatedocked — both: belongs to a group AND is positioned
                      on its master's honeycomb slots
                      (``_positioned`` set).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.shell.branding_loader import load_branding
from scriptree.shell.cell_registry import CellRegistry
from scriptree.shell.cell_window import (
    CellWindow, _try_spawn_master,
)


def _fresh() -> CellRegistry:
    reg = CellRegistry.instance()
    for h in list(reg.standalones()) + list(reg.masters()):
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass
    return reg


def _spawn_pair_master() -> tuple[CellWindow, CellWindow, CellWindow]:
    """Build a master + 2 members.  Returns (master, a, b)."""
    _fresh()
    a = CellWindow(load_branding())
    a.move(200, 200)
    a.show()
    b = CellWindow(load_branding())
    b.move(256, 200)
    b.show()
    _try_spawn_master(a, b)
    reg = CellRegistry.instance()
    master = reg.get(reg.master_of(a._id))
    assert master is not None
    return master, a, b


# ===========================================================================
# Case 5 — moving a cell within its own group
# ===========================================================================

class TestCase5_NoReshiftWithinGroup:

    def test_dragging_member_does_not_move_siblings(self) -> None:
        """User drags ``a`` to a new position within the same ring.
        ``b``'s widget position must remain byte-identical."""
        master, a, b = _spawn_pair_master()
        b_pos_before = (b.pos().x(), b.pos().y())
        # Simulate the snap engine committing ``a`` at a new
        # position within the same group.
        a.move(400, 200)  # User dragged here
        _try_spawn_master(a, b)  # Snap commit (Case 5)
        # ``a`` ended up where the user dropped it.
        assert (a.pos().x(), a.pos().y()) == (400, 200)
        # ``b`` did NOT shift.
        assert (b.pos().x(), b.pos().y()) == b_pos_before


# ===========================================================================
# Cases 2 / 3 — standalone joins an existing group
# ===========================================================================

class TestCase2_StandaloneJoinsExistingGroup:

    def test_existing_members_keep_positions(self) -> None:
        """A standalone ``c`` docking with an existing group member
        ``b`` becomes a ring member, but ``a`` and ``b`` keep their
        positions verbatim."""
        master, a, b = _spawn_pair_master()
        a_pos_before = (a.pos().x(), a.pos().y())
        b_pos_before = (b.pos().x(), b.pos().y())
        # New standalone arrives.
        c = CellWindow(load_branding())
        c.move(312, 200)
        c.show()
        # Snap commit: ``c`` (standalone) docks with ``b`` (already
        # a member of master's group) — Case 2.
        _try_spawn_master(c, b)
        # ``c`` joins the group.
        assert c._group_master_id == master._id
        # ``a`` and ``b`` did NOT shift.
        assert (a.pos().x(), a.pos().y()) == a_pos_before
        assert (b.pos().x(), b.pos().y()) == b_pos_before
        # ``c`` ended up where the user dropped it.
        assert (c.pos().x(), c.pos().y()) == (312, 200)


# ===========================================================================
# Member close — survivors keep positions
# ===========================================================================

class TestCloseMember_NoReshift:

    def test_closing_a_member_does_not_move_remaining(self) -> None:
        """Closing one cell leaves a gap; the rest stay where the
        user placed them.  The master may auto-close if its quorum
        check fires (< 2 members) — that's expected and
        independent of the no-reshift rule."""
        # Build a 3-member ring so the close doesn't break quorum.
        master, a, b = _spawn_pair_master()
        c = CellWindow(load_branding())
        c.move(312, 200)
        c.show()
        _try_spawn_master(c, b)
        a_pos_before = (a.pos().x(), a.pos().y())
        b_pos_before = (b.pos().x(), b.pos().y())
        # Close ``c``.
        c._close_this()
        # ``a`` and ``b`` stay put.
        assert (a.pos().x(), a.pos().y()) == a_pos_before
        assert (b.pos().x(), b.pos().y()) == b_pos_before


# ===========================================================================
# Drag-drop catalog onto a ring
# ===========================================================================

class TestDropCatalog_OnlyNewcomerMoves:

    def test_drop_catalog_keeps_existing_members(
        self, tmp_path: Path,
    ) -> None:
        """Dropping a ``.scriptree`` file onto a master ring spawns
        a new cell and joins it as a member.  The new cell takes a
        free slot; existing members stay verbatim."""
        master, a, b = _spawn_pair_master()
        a_pos_before = (a.pos().x(), a.pos().y())
        b_pos_before = (b.pos().x(), b.pos().y())
        # Synthesise a tool catalog so _drop_spawn_member_and_link
        # has a path to bind to.
        from scriptree.core.io import save_tool
        from scriptree.core.model import (
            ParamDef, ParamType, ToolDef, Widget,
        )
        tool = ToolDef(
            name="x", executable="echo",
            params=[ParamDef(
                id="p", label="P",
                type=ParamType.STRING, widget=Widget.TEXT,
            )],
        )
        catalog = tmp_path / "x.scriptree"
        save_tool(tool, catalog)
        master._drop_spawn_member_and_link(catalog)
        # ``a`` and ``b`` stay put.
        assert (a.pos().x(), a.pos().y()) == a_pos_before
        assert (b.pos().x(), b.pos().y()) == b_pos_before


# ===========================================================================
# Forest auto-attach — existing members stay put
# ===========================================================================

class TestHomeRestoration_AfterCornerExcursion:
    """v0.3.17 — when the master moves to a corner that pushes
    members off-screen, those members go to temp slots.  When the
    master returns, members must be restored to their ORDINARY
    slot (``_members[id]``), not stranded at temp."""

    def test_home_position_preserved_across_temp_relocation(self) -> None:
        """A direct unit test against ``_repack_members`` in surgical
        mode: ``_members[id]`` must NOT change, even when the widget
        gets a temp slot."""
        master, a, b = _spawn_pair_master()
        # Capture each member's HOME (the master tracks them in
        # _members after the spawn).
        a_home = QPoint(master._members[a._id])
        b_home = QPoint(master._members[b._id])
        # Run a surgical repack with one member as fixed.  Both
        # members' HOME slots must remain the same after the call.
        master._repack_members(fixed={a._id})
        assert master._members[a._id] == a_home
        assert master._members[b._id] == b_home

    def test_canonical_repack_does_update_home(self) -> None:
        """Sanity: when ``_repack_members`` runs in CANONICAL mode
        (``fixed=None``, used by Case 1 of fresh ring spawn), the
        new positions ARE the HOME slots — ``_members`` updates."""
        master, a, b = _spawn_pair_master()
        # Manually nudge a member's stored HOME to a non-canonical
        # position so the canonical repack genuinely changes it.
        master._members[a._id] = QPoint(99, 99)
        master._repack_members()  # canonical mode
        # Stored HOME has been updated to a fresh canonical slot
        # (no longer (99, 99)).
        assert master._members[a._id] != QPoint(99, 99)


class TestForestAutoAttach_NoReshift:

    def test_attaching_ring_to_forest_does_not_move_existing_forest_members(
        self, tmp_path: Path,
    ) -> None:
        """When the forest auto-attaches a ring, the ring lands on
        a free slot but existing forest members keep their
        positions verbatim."""
        from scriptree.core.io import save_tool
        from scriptree.core.model import (
            ParamDef, ParamType, ToolDef, Widget,
        )
        from scriptree.shell.forest_controller import ForestController
        from scriptree.shell.forest_io import ForestDef

        # Synthesise a tool catalog for the first item.
        tool = ToolDef(
            name="t", executable="echo",
            params=[ParamDef(
                id="p", label="P",
                type=ParamType.STRING, widget=Widget.TEXT,
            )],
        )
        first_path = tmp_path / "first.scriptree"
        save_tool(tool, first_path)

        _fresh()
        ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
        ctrl.start(forest=ForestDef(), suppress_first_run=True)
        # Add the first tool — that's the existing forest member
        # whose position must not shift when more arrive.
        ctrl.add_item(str(first_path), "tool")
        # Capture position.
        first_id = next(iter(ctrl.forest_window._members.keys()))
        first_cell = CellRegistry.instance().get(first_id)
        first_pos = (first_cell.pos().x(), first_cell.pos().y())

        # Now attach a ring (synthesise via a second tool — the
        # exact path doesn't matter; we just need a second add).
        second_path = tmp_path / "second.scriptree"
        save_tool(tool, second_path)
        ctrl.add_item(str(second_path), "tool")

        # First cell didn't shift.
        assert (first_cell.pos().x(), first_cell.pos().y()) == first_pos
