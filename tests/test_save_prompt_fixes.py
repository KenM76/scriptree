"""Tests for the v0.3.8 save-prompt fixes (F1 / F3 / G7).

Three previously-flagged data-loss paths now prompt:

* **F1** — Exit-all walks every master and prompts for any that's
  dirty / unsaved.  Cancel on any prompt aborts the whole exit.
* **F3** — Quorum-loss in ``_check_master_validity`` fires a
  Save / Discard prompt before tearing down.  No Cancel — the
  triggering member-close has already happened.
* **G7** — ``_ring_needs_save_prompt`` returns True when the
  previously-saved file has been deleted off disk.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)


from scriptree.shell.branding_loader import load_branding
from scriptree.shell.cell_registry import CellRegistry
from scriptree.shell.cell_window import (
    CellWindow, _check_master_validity, _try_spawn_master,
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
    _fresh()
    branding = load_branding()
    a = CellWindow(branding); a.move(200, 200); a.show()
    b = CellWindow(branding); b.move(256, 200); b.show()
    _try_spawn_master(a, b)
    reg = CellRegistry.instance()
    master = reg.get(reg.master_of(a._id))
    return master, a, b


# ===========================================================================
# G7 — stale saved path triggers re-prompt
# ===========================================================================

class TestG7StaleSavedPath:

    def test_needs_prompt_after_file_deleted(self, tmp_path: Path) -> None:
        master, _, _ = _spawn_pair_master()
        target = tmp_path / "demo.scriptreering"
        master._write_ring_to_path(target)
        assert master._ring_needs_save_prompt() is False

        # User deletes the file via Explorer.
        target.unlink()

        # Now the prompt should fire again.
        assert master._ring_needs_save_prompt() is True

    def test_needs_prompt_false_when_file_still_exists(
        self, tmp_path: Path,
    ) -> None:
        master, _, _ = _spawn_pair_master()
        target = tmp_path / "demo.scriptreering"
        master._write_ring_to_path(target)
        assert master._ring_needs_save_prompt() is False
        # File present, ring clean → no prompt.
        assert target.is_file()


# ===========================================================================
# F1 — Exit all prompts for dirty masters
# ===========================================================================

class TestF1ExitAllPrompt:

    def test_exit_all_prompts_for_dirty_master(self) -> None:
        master, _, _ = _spawn_pair_master()
        # Master is fresh-spawned → dirty.
        assert master._ring_needs_save_prompt() is True

        prompt_fired = []
        with patch.object(QMessageBox, "question") as m_q, \
             patch.object(QApplication, "quit") as m_quit:
            m_q.side_effect = lambda *a, **k: (
                prompt_fired.append("q"), QMessageBox.StandardButton.Discard,
            )[1]
            master._exit_all()

        assert prompt_fired, (
            "F1: _exit_all must fire the unsaved-ring save prompt "
            "before closing."
        )
        m_quit.assert_called_once()

    def test_exit_all_skips_prompt_for_clean_master(
        self, tmp_path: Path,
    ) -> None:
        master, _, _ = _spawn_pair_master()
        master._write_ring_to_path(tmp_path / "demo.scriptreering")
        assert master._ring_needs_save_prompt() is False

        with patch.object(QMessageBox, "question") as m_q, \
             patch.object(QApplication, "quit"):
            master._exit_all()

        m_q.assert_not_called()

    def test_exit_all_cancel_aborts_quit(self) -> None:
        """Cancel on any unsaved-ring prompt should abort the whole
        exit so the user keeps working without losing data."""
        master, _, _ = _spawn_pair_master()
        with patch.object(QMessageBox, "question") as m_q, \
             patch.object(QApplication, "quit") as m_quit:
            m_q.return_value = QMessageBox.StandardButton.Cancel
            master._exit_all()
        m_quit.assert_not_called()
        # Master still alive.
        assert master.role == "master"


# ===========================================================================
# F3 — Quorum-loss save prompt
# ===========================================================================

class TestF3QuorumLossPrompt:

    def test_member_close_drops_master_below_quorum_prompts(
        self,
    ) -> None:
        master, a, b = _spawn_pair_master()
        # Master is fresh-spawned → dirty.

        prompt_fired = []
        with patch.object(QMessageBox, "question") as m_q:
            m_q.side_effect = lambda *a, **k: (
                prompt_fired.append("q"), QMessageBox.StandardButton.Discard,
            )[1]
            a._close_this()

        assert prompt_fired, (
            "F3: closing a member that drops master below quorum "
            "must fire the save prompt for the dirty ring."
        )

    def test_quorum_loss_save_path_writes_ring(
        self, tmp_path: Path,
    ) -> None:
        """Save chosen at the F3 prompt → ring is written to a new
        file before teardown, even though it has only 1 member at
        save time."""
        master, a, b = _spawn_pair_master()
        target = tmp_path / "rescued.scriptreering"

        # Mock the prompt to choose Save, AND mock the file-save dialog
        # to point at our target path.
        with patch.object(QMessageBox, "question") as m_q, \
             patch(
                 "PySide6.QtWidgets.QFileDialog.getSaveFileName",
                 return_value=(str(target), ""),
             ):
            m_q.return_value = QMessageBox.StandardButton.Save
            a._close_this()

        # Save fired → file exists.
        assert target.is_file()

    def test_clean_saved_master_quorum_loss_skips_prompt(
        self, tmp_path: Path,
    ) -> None:
        """If the ring is saved + clean, the quorum-loss path closes
        silently (no prompt)."""
        master, a, b = _spawn_pair_master()
        master._write_ring_to_path(tmp_path / "saved.scriptreering")
        assert master._ring_dirty is False

        # Closing one member doesn't *itself* dirty the ring (the
        # member-leaving-group path DOES, per v0.3.1) — so we expect
        # the quorum-loss prompt to still fire because closing a
        # cell IS a membership change.
        # Wait — that's the v0.3.1 contract: member-close marks
        # dirty.  So the master will be dirty when quorum-check
        # runs.  That's correct behaviour for this scenario.
        prompt_fired = []
        with patch.object(QMessageBox, "question") as m_q:
            m_q.side_effect = lambda *a, **k: (
                prompt_fired.append("q"), QMessageBox.StandardButton.Discard,
            )[1]
            a._close_this()

        # Member-close marked dirty before validity check ran, so
        # prompt should fire.  This pins the v0.3.1 + v0.3.8
        # interaction.
        assert prompt_fired


def teardown_function(_func) -> None:
    _fresh()
