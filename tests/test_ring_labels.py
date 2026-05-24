"""v0.8.0a1+ramps Bug 8 — ring auto-naming + merged-menu cleanup.

User-reported: "Right now they can end up saying 'Cell master 0: no
catalog bound', but they should just say 'ring #' if they haven't
been saved and named they should show their cell siblings menus."

This module pins:

* A freshly-spawned ring master gets an auto-name "Ring N" (session-
  unique serial) on its ``_auto_ring_name`` field.
* ``tree_popup._popup_header_text`` returns that auto-name for
  unbound, unnamed rings (was the generic "Tree Ring" before).
* ``tree_popup.show_tree_popup_for`` skips ring members that have
  no catalog instead of cluttering the menu with disabled "Cell
  XXXXXXXX (no catalog bound)" rows.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


from scriptree.shell.branding_loader import load_branding  # noqa: E402
from scriptree.shell.cell_registry import CellRegistry  # noqa: E402
from scriptree.shell.cell_window import CellWindow, _try_spawn_master  # noqa: E402
from scriptree.shell.tree_popup import _popup_header_text  # noqa: E402


def _fresh() -> CellRegistry:
    reg = CellRegistry.instance()
    for h in list(reg.all()):
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass
    return reg


def _spawn_pair_master() -> tuple[CellWindow, CellWindow, CellWindow]:
    _fresh()
    branding = load_branding()
    a = CellWindow(branding); a.move(200, 200); a.show()
    b = CellWindow(branding); b.move(256, 200); b.show()
    _try_spawn_master(a, b)
    reg = CellRegistry.instance()
    master = reg.get(reg.master_of(a._id))
    assert master is not None
    return master, a, b


class TestRingAutoName:

    def test_fresh_ring_gets_auto_name(self) -> None:
        master, _, _ = _spawn_pair_master()
        assert master._auto_ring_name is not None
        assert master._auto_ring_name.startswith("Ring ")

    def test_auto_name_is_session_unique(self) -> None:
        m1, _, _ = _spawn_pair_master()
        # Second spawn (different cells) gets the next serial.
        _fresh()
        branding = load_branding()
        c = CellWindow(branding); c.move(400, 400); c.show()
        d = CellWindow(branding); d.move(456, 400); d.show()
        _try_spawn_master(c, d)
        reg = CellRegistry.instance()
        m2 = reg.get(reg.master_of(c._id))
        assert m2 is not None
        assert m1._auto_ring_name != m2._auto_ring_name, (
            "Two fresh rings should get distinct auto-names; got "
            f"{m1._auto_ring_name!r} for both."
        )

    def test_popup_header_uses_auto_name_for_unbound_ring(self) -> None:
        master, _, _ = _spawn_pair_master()
        header = _popup_header_text(master)
        assert header == master._auto_ring_name, (
            f"Popup header for unbound ring should be the auto-name "
            f"({master._auto_ring_name!r}), got {header!r}."
        )

    def test_popup_header_prefers_text_label_over_auto_name(self) -> None:
        master, _, _ = _spawn_pair_master()
        master._text_label = "My Ring"
        header = _popup_header_text(master)
        assert header == "My Ring"

    def test_popup_header_for_forest_is_still_forest(self) -> None:
        """Forest gets no auto-serial — its label stays "Forest"."""
        _fresh()
        branding = load_branding()
        forest = CellWindow(branding, role="master")
        forest._is_forest_master = True
        forest.show()
        try:
            # Even if some prior path set _auto_ring_name on it, the
            # forest branch should win.
            forest._auto_ring_name = "Ring 99"
            header = _popup_header_text(forest)
            assert header == "Forest", (
                f"Forest header should be 'Forest', got {header!r}."
            )
        finally:
            forest.close()


class TestForestMenuShowsFreshRing:
    """v0.8.0a1+ramps Bug 9 — the forest's merged-menu must include
    fresh rings as sub-menus, even when those rings have empty
    members (no catalog).  User reported: "the newly formed tree
    ring now doesn't show up on the forest menu at all (it should)."
    """

    def test_forest_menu_has_ring_submenu(self) -> None:
        from PySide6.QtWidgets import QMenu
        from scriptree.shell.tree_popup import _populate_menu_from_member

        _fresh()
        branding = load_branding()
        forest = CellWindow(branding, role="master")
        forest._is_forest_master = True
        forest.show()

        # Build a fresh ring; promote it under the forest the way
        # _try_spawn_master does (link parent = forest, in
        # forest._members, NOT in forest._positioned per Bug 7).
        a = CellWindow(branding); a.show(); a.move(900, 200)
        a._group_master_id = forest._id
        a._link_parent_id = forest._id
        forest._members[a._id] = QPoint(a.pos())

        b = CellWindow(branding); b.show(); b.move(900 + a._size_px, 200)
        b._group_master_id = forest._id
        b._link_parent_id = forest._id
        forest._members[b._id] = QPoint(b.pos())

        _try_spawn_master(a, b)
        reg = CellRegistry.instance()
        ring_id = reg.master_of(a._id)
        assert ring_id is not None
        ring = reg.get(ring_id)
        assert ring is not None
        # Sanity: ring must be in forest._members for the menu to
        # discover it.
        assert ring._id in forest._members, (
            "Bug 9 prerequisite: forest._members must contain the "
            "new ring for the menu builder to find it."
        )

        # Build a menu via the helper and verify the ring appears
        # as a sub-menu titled with its auto-name.
        parent_menu = QMenu(None)
        leaves: list = []
        result = _populate_menu_from_member(
            parent_menu, ring, leaves, reg,
        )
        assert result is True, (
            "Bug 9: master sub-menu population should return True "
            "even for empty rings (the user wants to SEE the ring "
            "exists in the parent menu)."
        )
        # The first (and only) action on parent_menu should be the
        # ring's auto-name as a sub-menu.
        actions = [
            a for a in parent_menu.actions() if a.text()
        ]
        assert len(actions) == 1, (
            f"Expected exactly one sub-menu action for the ring, "
            f"got {[a.text() for a in parent_menu.actions()]}"
        )
        assert actions[0].text() == ring._auto_ring_name, (
            f"Sub-menu label should be the ring's auto-name "
            f"({ring._auto_ring_name!r}), got {actions[0].text()!r}."
        )

    def test_empty_ring_submenu_shows_empty_hint(self) -> None:
        from PySide6.QtWidgets import QMenu
        from scriptree.shell.tree_popup import _populate_menu_from_member

        master, _, _ = _spawn_pair_master()
        # master's two members have no catalog → ring is empty of
        # tools.  The sub-menu under the parent should contain a
        # disabled "(empty)" hint.
        parent_menu = QMenu(None)
        leaves: list = []
        reg = CellRegistry.instance()
        _populate_menu_from_member(
            parent_menu, master, leaves, reg,
        )
        # The ring sub-menu is the first child action.
        ring_action = parent_menu.actions()[0]
        ring_menu = ring_action.menu()
        assert ring_menu is not None
        inner = [a for a in ring_menu.actions() if a.text()]
        assert any("(empty)" in a.text() for a in inner), (
            f"Empty ring sub-menu should show '(empty)' hint, got "
            f"{[a.text() for a in inner]}"
        )


def teardown_function(_func) -> None:
    _fresh()
