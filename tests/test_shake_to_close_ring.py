"""v0.8.0a1+ramps Bug 5 — shake-on-ring close prompt.

Per user spec: "shake to close and have a box come up then to close,
save or cancel."

Pre-v0.8.0 the shake gesture was wired only to standalone cells (to
disassociate from their group), and rings auto-closed when their
member count dropped below 2.  v0.8.0 disabled auto-close, so there
was no explicit way to dispose of a ring.  This module pins the new
shake-on-ring path:

* Shake on a ring → modal Save / Close / Cancel dialog
* Cancel → ring untouched
* Close (Discard) → ring disbands; members re-link to forest
* Save → save first, then disband (cancel-on-save aborts the close)
* Shake on the forest is a no-op (forest never closes by shake)
"""
from __future__ import annotations

from pathlib import Path
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


class TestShakeOnRingPrompt:

    def test_cancel_keeps_ring_alive(self) -> None:
        """Cancel on the shake prompt must leave the ring intact."""
        master, a, b = _spawn_pair_master()
        master_id = master._id

        with patch.object(QMessageBox, "question") as m_q:
            m_q.return_value = QMessageBox.StandardButton.Cancel
            master._close_ring_via_shake_with_prompt()

        # Ring is still registered and alive.
        reg = CellRegistry.instance()
        assert reg.get(master_id) is not None, (
            "Ring closed despite Cancel on shake prompt."
        )
        assert master.role == "master"
        assert a._group_master_id == master_id
        assert b._group_master_id == master_id

    def test_close_disbands_ring(self) -> None:
        """Close (Discard) on the shake prompt disbands the ring."""
        master, a, b = _spawn_pair_master()
        master_id = master._id

        with patch.object(QMessageBox, "question") as m_q:
            # Discard maps to Close button label.
            m_q.return_value = QMessageBox.StandardButton.Discard
            master._close_ring_via_shake_with_prompt()

        reg = CellRegistry.instance()
        assert reg.get(master_id) is None, (
            "Ring still in registry after Close-on-shake."
        )
        # Members are still on screen but no longer linked to the ring.
        assert a._group_master_id != master_id
        assert b._group_master_id != master_id
        assert a._link_parent_id != master_id
        assert b._link_parent_id != master_id

    def test_save_then_close(self, tmp_path: Path) -> None:
        """Save on the shake prompt writes the ring then disbands."""
        master, a, b = _spawn_pair_master()
        master_id = master._id
        target = tmp_path / "shake_saved.scriptreering"

        with patch.object(QMessageBox, "question") as m_q, \
             patch(
                 "PySide6.QtWidgets.QFileDialog.getSaveFileName",
                 return_value=(str(target), ""),
             ):
            m_q.return_value = QMessageBox.StandardButton.Save
            master._close_ring_via_shake_with_prompt()

        # File written.
        assert target.is_file(), (
            "Save-on-shake did not write the ring file."
        )
        # Ring disbanded.
        reg = CellRegistry.instance()
        assert reg.get(master_id) is None

    def test_shake_on_forest_is_noop(self) -> None:
        """Shake on the forest master must NEVER close it (the forest
        is the workspace root)."""
        _fresh()
        branding = load_branding()
        forest = CellWindow(branding, role="master")
        forest._is_forest_master = True
        forest.show()
        forest.move(500, 500)
        forest_id = forest._id

        try:
            with patch.object(QMessageBox, "question") as m_q:
                m_q.return_value = QMessageBox.StandardButton.Discard
                forest._close_ring_via_shake_with_prompt()
            # Forest still alive — even with a Discard answer, the
            # method should have early-returned without prompting.
            reg = CellRegistry.instance()
            assert reg.get(forest_id) is not None, (
                "Forest was closed by shake — must never happen."
            )
            m_q.assert_not_called()
        finally:
            forest.close()

    def teardown_method(self, _method) -> None:
        _fresh()
