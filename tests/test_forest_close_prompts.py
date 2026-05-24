"""v0.8.0a1+ramps Bug 11 — forest never prompts for its own save,
but ring members under the forest still get prompted.

User-reported: "when I right click on forest and close all it asks
me to save the unsaved ring twice instead of just once."

Root cause: ``_ring_needs_save_prompt`` returned True for the forest
(forest is a master with members and no ``_saved_ring_path``), so
both ``_exit_all`` and ``_close_all_related`` fired the "Unsaved
ring" prompt for the forest itself.  Then the actual unsaved ring
got prompted by a separate path, resulting in two identical-looking
dialogs.

Fix:
* ``_ring_needs_save_prompt`` short-circuits to False for the forest.
* ``_close_all_related`` pre-walks master members and prompts for
  each unsaved ring before touching any close, so the user still
  gets the (one) prompt for the unsaved ring member.
"""
from __future__ import annotations

from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])


from scriptree.shell.branding_loader import load_branding  # noqa: E402
from scriptree.shell.cell_registry import CellRegistry  # noqa: E402
from scriptree.shell.cell_window import (  # noqa: E402
    CellWindow, _try_spawn_master,
)


def _fresh() -> CellRegistry:
    reg = CellRegistry.instance()
    for h in list(reg.all()):
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass
    return reg


def _spawn_forest_with_ring() -> tuple[CellWindow, CellWindow, CellWindow, CellWindow]:
    """Spawn a forest with one ring containing two cells inside it,
    matching the user-reported scenario (forest → ring → 2 cells)."""
    _fresh()
    branding = load_branding()
    forest = CellWindow(branding, role="master")
    forest._is_forest_master = True
    forest.show()
    forest.move(500, 500)

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
    ring = reg.get(ring_id)
    assert ring is not None
    return forest, ring, a, b


class TestForestNeverPromptsForSelf:

    def test_forest_ring_needs_save_prompt_returns_false(self) -> None:
        """Even with member content, the forest itself never asks
        to be saved — it's a singleton, not persisted to a file."""
        forest, _, _, _ = _spawn_forest_with_ring()
        assert forest._ring_needs_save_prompt() is False, (
            "Bug 11: forest._ring_needs_save_prompt must return "
            "False so 'Close all' / 'Exit all' don't fire a "
            "redundant prompt for the forest itself."
        )

    def test_ring_under_forest_still_needs_prompt(self) -> None:
        """Sanity: the ring inside the forest is still flagged as
        needing the save prompt (we only relaxed the rule for the
        forest)."""
        _, ring, _, _ = _spawn_forest_with_ring()
        assert ring._ring_needs_save_prompt() is True, (
            "Sanity: an unsaved ring should still need the save "
            "prompt.  Bug 11 fix should not have weakened this."
        )


class TestCloseAllRelatedOnForestPromptsOnce:

    def test_close_all_related_prompts_only_for_ring_not_forest(self) -> None:
        """Right-click forest → 'Close all related' must fire exactly
        ONE save prompt (for the unsaved ring), not two."""
        forest, ring, _, _ = _spawn_forest_with_ring()

        prompt_count = []
        with patch.object(QMessageBox, "question") as m_q, \
             patch.object(QApplication, "quit"):
            def _spy(*args, **kw):
                prompt_count.append("p")
                return QMessageBox.StandardButton.Discard
            m_q.side_effect = _spy
            forest._close_all_related()

        assert len(prompt_count) == 1, (
            f"Bug 11: 'Close all related' on the forest should fire "
            f"exactly one save prompt (for the unsaved ring); "
            f"got {len(prompt_count)}."
        )

    def test_close_all_related_cancel_aborts_close(self) -> None:
        """Cancel on the ring's save prompt aborts the forest close."""
        forest, ring, _, _ = _spawn_forest_with_ring()
        forest_id = forest._id

        with patch.object(QMessageBox, "question") as m_q, \
             patch.object(QApplication, "quit") as m_quit:
            m_q.return_value = QMessageBox.StandardButton.Cancel
            forest._close_all_related()

        reg = CellRegistry.instance()
        assert reg.get(forest_id) is not None, (
            "Cancel on ring prompt should have aborted the forest "
            "close, but the forest was closed anyway."
        )
        m_quit.assert_not_called()


class TestExitAllPromptsOnce:
    """``_exit_all`` walks every master in the registry and prompts
    for each unsaved one.  Forest must skip per Bug 11."""

    def test_exit_all_with_forest_and_ring_prompts_once(self) -> None:
        forest, ring, _, _ = _spawn_forest_with_ring()

        prompt_count = []
        with patch.object(QMessageBox, "question") as m_q, \
             patch.object(QApplication, "quit"):
            def _spy(*args, **kw):
                prompt_count.append("p")
                return QMessageBox.StandardButton.Discard
            m_q.side_effect = _spy
            forest._exit_all()

        assert len(prompt_count) == 1, (
            f"Bug 11: Exit all should prompt once for the unsaved "
            f"ring, not also for the forest.  Got {len(prompt_count)} "
            f"prompts."
        )


def teardown_function(_func) -> None:
    _fresh()
