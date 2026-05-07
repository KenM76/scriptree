"""Tests for the action button row: Undo / Redo / Reset / Clear output.

Covers:
- Button row layout (Run and Copy argv moved off the preview row).
- Undo/Redo walks the edit history correctly.
- Reset restores the initial snapshot.
- Undo is disabled at history floor; Redo disabled at top.
- Clear output wipes the pane (confirmation dialog monkeypatched).
- Reset prompts for confirmation.
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

from scriptree.core.model import ParamDef, ToolDef  # noqa: E402
from scriptree.ui import tool_runner as tr_mod  # noqa: E402
from scriptree.ui.tool_runner import ToolRunnerView  # noqa: E402


def _tool() -> ToolDef:
    return ToolDef(
        name="demo",
        executable="/bin/echo",
        argument_template=["{name}"],
        params=[ParamDef(id="name", label="Name", default="hello")],
    )


def _auto_yes(monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Yes),
    )


def _auto_no(monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **kw: QMessageBox.StandardButton.No),
    )


def _simulate_edit(view: ToolRunnerView, text: str) -> None:
    """Simulate a user typing into the command preview.

    Setting plain text under the updating guard prevents the textChanged
    signal from firing, then we call _on_live_cmd_edited manually —
    exactly one reconcile + history push, same as if the user typed it.
    """
    view._updating = True
    view._live_cmd.setPlainText(text)
    view._updating = False
    view._on_live_cmd_edited(text)


class TestActionRowLayout:
    def test_run_button_exists(self) -> None:
        view = ToolRunnerView(_tool())
        assert view._btn_run is not None

    def test_initial_button_state(self) -> None:
        view = ToolRunnerView(_tool())
        assert not view._btn_undo.isEnabled()
        assert not view._btn_redo.isEnabled()
        assert not view._btn_reset.isEnabled()


class TestUndoRedo:
    def test_undo_after_edit_reverts_extras(self) -> None:
        view = ToolRunnerView(_tool())
        _simulate_edit(view, "/bin/echo hello --extra-flag")
        assert "--extra-flag" in view._extras
        assert view._btn_undo.isEnabled()

        view._undo_edit()
        assert view._extras == []
        assert not view._btn_undo.isEnabled()
        assert view._btn_redo.isEnabled()

    def test_redo_replays_edit(self) -> None:
        view = ToolRunnerView(_tool())
        _simulate_edit(view, "/bin/echo hello --extra-flag")
        view._undo_edit()
        view._redo_edit()
        assert "--extra-flag" in view._extras
        assert not view._btn_redo.isEnabled()

    def test_new_edit_truncates_redo_tail(self) -> None:
        view = ToolRunnerView(_tool())
        _simulate_edit(view, "/bin/echo hello --a")
        view._undo_edit()
        # Fork the timeline
        _simulate_edit(view, "/bin/echo hello --b")
        # Redo should no longer be possible
        assert not view._btn_redo.isEnabled()


class TestReset:
    def test_reset_restores_initial_state(self, monkeypatch) -> None:
        _auto_yes(monkeypatch)
        view = ToolRunnerView(_tool())
        _simulate_edit(view, "/bin/echo hello --extra")
        assert view._extras == ["--extra"]

        view._reset_edits()
        assert view._extras == []

    def test_reset_cancelled_by_user(self, monkeypatch) -> None:
        _auto_no(monkeypatch)
        view = ToolRunnerView(_tool())
        _simulate_edit(view, "/bin/echo hello --extra")
        view._reset_edits()
        assert view._extras == ["--extra"]  # unchanged

    def test_reset_noop_at_floor(self, monkeypatch) -> None:
        _auto_yes(monkeypatch)
        view = ToolRunnerView(_tool())
        view._reset_edits()
        # Nothing happens — we're already at the floor.
        assert not view._btn_reset.isEnabled()


class TestClearOutput:
    def test_clear_output_wipes_pane(self, monkeypatch) -> None:
        _auto_yes(monkeypatch)
        view = ToolRunnerView(_tool())
        view._output.setPlainText("some output")
        view._clear_output()
        assert view._output.toPlainText() == ""

    def test_clear_output_cancelled(self, monkeypatch) -> None:
        _auto_no(monkeypatch)
        view = ToolRunnerView(_tool())
        view._output.setPlainText("some output")
        view._clear_output()
        assert view._output.toPlainText() == "some output"
