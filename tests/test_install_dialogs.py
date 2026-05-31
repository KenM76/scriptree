"""Phase-2 regression suite for the drop-install dialogs
(``scriptree.ui.install_dialogs``).

Tests exercise dialog state via direct slot calls rather than
simulating Qt clicks, matching the testing pattern used
elsewhere in the codebase.  Auto-dismisses ``QMessageBox`` per
the standing rule.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)

from scriptree.core.app_install import ConflictMode
from scriptree.ui.install_dialogs import (
    InstallConflictDialog,
    InstallLocationDialog,
)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _make_folder(parent: Path, name: str) -> Path:
    p = parent / name
    p.mkdir()
    return p


def _make_zip(parent: Path, name: str) -> Path:
    p = parent / name
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("README.md", "# hi")
    return p


# ============================================================================
# InstallLocationDialog
# ============================================================================


class TestLocationDialogConstruct:
    def test_constructs_from_folder_source(self, tmp_path: Path) -> None:
        src = _make_folder(tmp_path, "MyTool")
        dlg = InstallLocationDialog(None, src)
        # Shared is the default.
        assert dlg._shared_radio.isChecked() is True
        # The "Install as" field defaults to the inferred name.
        assert dlg._name_edit.text() == "MyTool"

    def test_constructs_from_zip_source(self, tmp_path: Path) -> None:
        src = _make_zip(tmp_path, "MyTool.zip")
        dlg = InstallLocationDialog(None, src)
        # Zip stem becomes the default "Install as" name.
        assert dlg._name_edit.text() == "MyTool"

    def test_preview_paths_populated(self, tmp_path: Path) -> None:
        """Each radio shows a preview path under it."""
        src = _make_folder(tmp_path, "X")
        dlg = InstallLocationDialog(None, src)
        # Previews end with the app name.
        assert dlg._shared_preview.text().endswith("X")
        assert dlg._personal_preview.text().endswith("X")

    def test_preview_updates_when_name_edited(
        self, tmp_path: Path,
    ) -> None:
        src = _make_folder(tmp_path, "X")
        dlg = InstallLocationDialog(None, src)
        dlg._name_edit.setText("Renamed")
        # Shared + personal previews now end with the new name.
        assert dlg._shared_preview.text().endswith("Renamed")
        assert dlg._personal_preview.text().endswith("Renamed")


class TestLocationDialogChoice:
    def test_default_choice_is_shared(self, tmp_path: Path) -> None:
        src = _make_folder(tmp_path, "X")
        dlg = InstallLocationDialog(None, src)
        # Simulate user clicking Install with defaults.
        dlg._on_install()
        # The dialog is accepted; the chosen root is the shared
        # default.
        from scriptree.core.app_install import default_shared_root
        assert dlg.chosen_root() == default_shared_root().resolve()

    def test_personal_choice(self, tmp_path: Path) -> None:
        src = _make_folder(tmp_path, "X")
        dlg = InstallLocationDialog(None, src)
        dlg._personal_radio.setChecked(True)
        dlg._on_install()
        from scriptree.core.app_install import default_personal_root
        assert dlg.chosen_root() == default_personal_root().resolve()

    def test_browse_without_path_refuses(self, tmp_path: Path) -> None:
        """Selecting Other without browsing first must NOT
        accept -- the user has to pick a folder."""
        src = _make_folder(tmp_path, "X")
        dlg = InstallLocationDialog(None, src)
        dlg._browse_radio.setChecked(True)
        # Call the install slot directly; should refuse.
        dlg._on_install()
        # The dialog wasn't accepted.
        assert dlg.result() != dlg.DialogCode.Accepted

    def test_browse_with_path(self, tmp_path: Path) -> None:
        """When a browse path was set programmatically, the
        Other radio accepts and returns that path."""
        src = _make_folder(tmp_path, "X")
        custom = _make_folder(tmp_path, "elsewhere")
        dlg = InstallLocationDialog(None, src)
        dlg._browsed_path = custom
        dlg._browse_radio.setChecked(True)
        dlg._on_install()
        assert dlg.chosen_root() == custom.resolve()

    def test_chosen_app_name_returns_edited_name(
        self, tmp_path: Path,
    ) -> None:
        src = _make_folder(tmp_path, "X")
        dlg = InstallLocationDialog(None, src)
        dlg._name_edit.setText("Renamed")
        assert dlg.chosen_app_name() == "Renamed"

    def test_chosen_app_name_scrubs_unsafe(
        self, tmp_path: Path,
    ) -> None:
        src = _make_folder(tmp_path, "X")
        dlg = InstallLocationDialog(None, src)
        # Even if user types unsafe chars, the result is scrubbed.
        dlg._name_edit.setText("My<bad>Name")
        cleaned = dlg.chosen_app_name()
        assert "<" not in cleaned
        assert ">" not in cleaned


# ============================================================================
# InstallConflictDialog
# ============================================================================


class TestConflictDialog:
    def test_default_is_update(self, tmp_path: Path) -> None:
        dlg = InstallConflictDialog(None, "MyTool")
        assert dlg._rb_update.isChecked() is True

    def test_picks_update(self, tmp_path: Path) -> None:
        dlg = InstallConflictDialog(None, "MyTool")
        dlg._on_proceed()
        assert dlg.chosen_mode() == ConflictMode.UPDATE

    def test_picks_overwrite(self, tmp_path: Path) -> None:
        dlg = InstallConflictDialog(None, "MyTool")
        dlg._rb_overwrite.setChecked(True)
        dlg._on_proceed()
        assert dlg.chosen_mode() == ConflictMode.OVERWRITE

    def test_picks_rename(self, tmp_path: Path) -> None:
        dlg = InstallConflictDialog(None, "MyTool")
        dlg._rb_rename.setChecked(True)
        dlg._on_proceed()
        assert dlg.chosen_mode() == ConflictMode.RENAME

    def test_cancel_yields_cancel_mode(self, tmp_path: Path) -> None:
        dlg = InstallConflictDialog(None, "MyTool")
        dlg._on_cancel()
        assert dlg.chosen_mode() == ConflictMode.CANCEL

    def test_default_before_exec_is_cancel(self, tmp_path: Path) -> None:
        """Before _on_proceed or _on_cancel fires, ``chosen_mode``
        returns CANCEL -- the safe default for a caller that
        skipped the return-value check."""
        dlg = InstallConflictDialog(None, "MyTool")
        # No interaction yet.
        assert dlg.chosen_mode() == ConflictMode.CANCEL

    def test_existing_path_shown(self, tmp_path: Path) -> None:
        """Optional existing_path is displayed in the dialog so
        the user knows exactly which folder they're conflicting
        with -- useful when shared + personal both have a folder
        called ``MyTool`` and the user can't remember which one
        triggered the dialog."""
        existing = _make_folder(tmp_path, "MyTool")
        dlg = InstallConflictDialog(None, "MyTool", existing)
        # Walk the children and verify the path appears.
        from PySide6.QtWidgets import QLabel
        labels = [
            c.text() for c in dlg.findChildren(QLabel)
            if isinstance(c, QLabel)
        ]
        assert any(str(existing) in lbl for lbl in labels)
