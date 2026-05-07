"""Tests for the missing-file recovery dialog (ui/recovery_dialog.py).

Covers:
- Dialog constructs with / without Browse permission.
- Path field is read-only but selectable.
- Copy button copies the path to the clipboard.
- selected_replacement() returns None before any browse.
- ``_offer_missing_tool_recovery`` in tree_view updates the leaf path
  when the user picks a replacement.
- ``_executable_seems_missing`` detects missing absolute paths and
  bare names not on PATH.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from scriptree.ui.recovery_dialog import MissingFileRecoveryDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class TestMissingFileRecoveryDialog:
    def test_construct_with_browse(self, qapp):
        dlg = MissingFileRecoveryDialog(
            None,
            title="Test",
            message="Missing",
            missing_path="/tmp/does-not-exist.txt",
            allow_replace=True,
        )
        try:
            assert dlg.windowTitle() == "Test"
            assert dlg.selected_replacement() is None
        finally:
            dlg.close()
            dlg.deleteLater()
            qapp.processEvents()

    def test_construct_without_browse(self, qapp):
        dlg = MissingFileRecoveryDialog(
            None,
            title="Test",
            message="Missing",
            missing_path="/tmp/does-not-exist.txt",
            allow_replace=False,
        )
        try:
            assert dlg.selected_replacement() is None
        finally:
            dlg.close()
            dlg.deleteLater()
            qapp.processEvents()

    def test_path_field_is_editable(self, qapp):
        """As of v0.1.11 the path field is editable + drop-aware so
        users can type/paste/drop a replacement path without going
        through the Browse dialog. The original path is still shown
        as the field's initial value."""
        dlg = MissingFileRecoveryDialog(
            None,
            title="Test",
            message="Missing",
            missing_path=r"C:\some\path.scriptree",
            allow_replace=True,
        )
        try:
            assert not dlg._path_edit.isReadOnly()
            assert dlg._path_edit.text() == r"C:\some\path.scriptree"
        finally:
            dlg.close()
            dlg.deleteLater()
            qapp.processEvents()

    def test_typing_real_path_arms_replacement(self, qapp, tmp_path):
        """Typing the absolute path of a real file into the field
        should arm the replacement (selected_replacement returns it)
        without the user having to click Browse."""
        real = tmp_path / "found.exe"
        real.touch()

        dlg = MissingFileRecoveryDialog(
            None,
            title="Test",
            message="Missing",
            missing_path=r"C:\old\missing.exe",
            allow_replace=True,
        )
        try:
            dlg._path_edit.setText(str(real))
            qapp.processEvents()
            assert dlg.selected_replacement() == str(real)
        finally:
            dlg.close()
            dlg.deleteLater()
            qapp.processEvents()

    def test_typing_garbage_does_not_arm(self, qapp):
        """Typing a path that doesn't point at a real file should not
        arm the replacement — Apply stays disabled."""
        dlg = MissingFileRecoveryDialog(
            None,
            title="Test",
            message="Missing",
            missing_path=r"C:\old\missing.exe",
            allow_replace=True,
        )
        try:
            dlg._path_edit.setText(r"C:\definitely\not\real.exe")
            qapp.processEvents()
            assert dlg.selected_replacement() is None
        finally:
            dlg.close()
            dlg.deleteLater()
            qapp.processEvents()

    def test_typing_in_scope_mode_reveals_picker(self, qapp, tmp_path):
        """In scope-picker mode, entering a real path should reveal
        the scope panel (it starts hidden until a path is picked)."""
        from scriptree.ui.recovery_dialog import PathScopeOptions

        real = tmp_path / "found.exe"
        real.touch()

        dlg = MissingFileRecoveryDialog(
            None,
            title="Test",
            message="Missing",
            missing_path=r"C:\old\missing.exe",
            allow_replace=True,
            path_scope_options=PathScopeOptions(),
        )
        try:
            assert dlg._scope_frame is not None
            assert dlg._scope_frame.isVisible() is False
            dlg.show()
            qapp.processEvents()

            dlg._path_edit.setText(str(real))
            qapp.processEvents()

            assert dlg._scope_frame.isVisible() is True
            assert dlg._btn_ok is not None
            assert dlg._btn_ok.isEnabled() is True
        finally:
            dlg.close()
            dlg.deleteLater()
            qapp.processEvents()

    def test_path_field_accepts_file_url_drop(self, qapp, tmp_path):
        """Dragging a file from Explorer fires our drop handler which
        replaces the field text. We don't go through real Qt event
        dispatch (synthetic QDropEvent loses concrete QMimeData type
        in PySide6); instead exercise the same helper the drop event
        calls."""
        from scriptree.ui.widgets.param_widgets import (
            _apply_line_edit_drop,
        )
        from PySide6.QtCore import QMimeData, QUrl

        real = tmp_path / "dragged.exe"
        real.touch()

        dlg = MissingFileRecoveryDialog(
            None,
            title="Test",
            message="Missing",
            missing_path=r"C:\old\missing.exe",
            allow_replace=True,
        )
        try:
            md = QMimeData()
            md.setUrls([QUrl.fromLocalFile(str(real))])
            consumed = _apply_line_edit_drop(dlg._path_edit, md)
            qapp.processEvents()
            assert consumed is True
            assert dlg._path_edit.text().replace("\\", "/") == \
                str(real).replace("\\", "/")
            # textChanged -> _on_path_edit_changed -> _replacement_path
            assert dlg.selected_replacement() == dlg._path_edit.text()
        finally:
            dlg.close()
            dlg.deleteLater()
            qapp.processEvents()

    def test_copy_path_to_clipboard(self, qapp, monkeypatch):
        # Monkeypatch the clipboard instead of touching the real one —
        # on Windows, the Qt clipboard ownership interacts poorly with
        # test isolation when dialogs stay alive across tests.
        captured: list[str] = []

        class _FakeClip:
            def setText(self, text: str) -> None:
                captured.append(text)

        monkeypatch.setattr(
            QApplication, "clipboard", staticmethod(lambda: _FakeClip())
        )

        dlg = MissingFileRecoveryDialog(
            None,
            title="Test",
            message="Missing",
            missing_path="/a/b/c.txt",
            allow_replace=False,
        )
        try:
            dlg._copy_path()
            assert captured == ["/a/b/c.txt"]
        finally:
            dlg.close()
            dlg.deleteLater()
            qapp.processEvents()


class TestExecutableSeemsMissing:
    def test_existing_absolute_path(self, tmp_path: Path, qapp):
        """A real, existing absolute path is NOT flagged as missing."""
        from scriptree.ui.tool_runner import ToolRunnerView
        exe = tmp_path / "fake.exe"
        exe.touch()
        assert ToolRunnerView._executable_seems_missing(str(exe)) is False

    def test_missing_absolute_path(self, tmp_path: Path, qapp):
        from scriptree.ui.tool_runner import ToolRunnerView
        exe = tmp_path / "missing.exe"
        assert ToolRunnerView._executable_seems_missing(str(exe)) is True

    def test_bare_name_on_path(self, qapp):
        """A bare name that resolves via PATH is NOT flagged."""
        from scriptree.ui.tool_runner import ToolRunnerView
        # Python is always on PATH in a pytest environment.
        name = "python"
        if shutil.which(name):
            assert ToolRunnerView._executable_seems_missing(name) is False

    def test_bare_name_not_on_path(self, qapp):
        from scriptree.ui.tool_runner import ToolRunnerView
        name = "this-binary-should-not-exist-anywhere-xyzzy"
        assert ToolRunnerView._executable_seems_missing(name) is True
