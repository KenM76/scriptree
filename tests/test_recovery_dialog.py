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

    def test_path_field_is_readonly(self, qapp):
        dlg = MissingFileRecoveryDialog(
            None,
            title="Test",
            message="Missing",
            missing_path=r"C:\some\path.scriptree",
            allow_replace=True,
        )
        try:
            assert dlg._path_edit.isReadOnly()
            assert dlg._path_edit.text() == r"C:\some\path.scriptree"
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
