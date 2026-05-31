"""Phase-3 regression suite for the cell-window drop-install
wiring (``scriptree.shell.cell_window._handle_dropped_installable``).

End-to-end-ish: builds a real forest-master ``CellWindow``,
patches the two install dialogs to return canned answers, drops
a folder or zip path through the handler, and asserts:

* ``install_app`` actually runs (a real file lands at the
  resolved target on disk).
* The post-install refresh fires on the forest controller (when
  one is attached).
* Non-forest cells silently ignore installable drops.
* User-cancel paths (Cancel on either dialog) leave the FS
  untouched.

Auto-dismisses ``QMessageBox`` per the standing rule.  These
tests use real ``tmp_path`` directories so the install logic
actually runs end-to-end -- they're the integration layer the
unit tests in ``test_app_install.py`` + ``test_install_dialogs.py``
sit beneath.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)

from scriptree.core.app_install import ConflictMode
from scriptree.shell.cell_window import CellWindow


# ----------------------------------------------------------------------------
# Cell construction helper
# ----------------------------------------------------------------------------


_BASE_BRANDING = {
    "palette": {},
    "hexagon": {},
}


def _make_forest_cell(*, is_forest_master: bool = True) -> CellWindow:
    """Construct a CellWindow with the minimum config for the
    drop-install tests.

    ``is_forest_master`` toggles the forest-master flag the
    drop handler gates on.  Default ``True`` covers the typical
    "drop onto forest" scenario; pass ``False`` for the
    non-forest-rejection test.
    """
    cell = CellWindow(
        role="master",
        branding=_BASE_BRANDING,
        is_forest_master=is_forest_master,
    )
    return cell


def _patch_location_dialog(target_root: Path, app_name: str = ""):
    """Return a context manager that replaces ``InstallLocationDialog``
    with a fake that:

    * always Accepts on ``exec()``,
    * returns ``target_root`` from ``chosen_root()``,
    * returns ``app_name`` from ``chosen_app_name()`` (or the
      source's stem if blank).

    Patches at the import site inside ``cell_window`` since the
    handler does a lazy ``from ..ui.install_dialogs import``.
    """
    fake_cls = MagicMock()
    fake_instance = MagicMock()
    fake_instance.DialogCode.Accepted = QDialog.DialogCode.Accepted
    fake_instance.exec.return_value = QDialog.DialogCode.Accepted
    fake_instance.chosen_root.return_value = target_root
    fake_instance.chosen_app_name.return_value = app_name
    fake_cls.return_value = fake_instance
    return patch(
        "scriptree.ui.install_dialogs.InstallLocationDialog",
        fake_cls,
    )


def _patch_location_cancel():
    """Replace InstallLocationDialog with a fake that returns
    Rejected from ``exec()`` (= user clicked Cancel)."""
    fake_cls = MagicMock()
    fake_instance = MagicMock()
    fake_instance.DialogCode.Accepted = QDialog.DialogCode.Accepted
    fake_instance.DialogCode.Rejected = QDialog.DialogCode.Rejected
    fake_instance.exec.return_value = QDialog.DialogCode.Rejected
    fake_cls.return_value = fake_instance
    return patch(
        "scriptree.ui.install_dialogs.InstallLocationDialog",
        fake_cls,
    )


def _patch_conflict_dialog(mode: ConflictMode):
    """Return a context manager that replaces
    ``InstallConflictDialog`` with a fake returning ``mode``."""
    fake_cls = MagicMock()
    fake_instance = MagicMock()
    fake_instance.DialogCode.Accepted = QDialog.DialogCode.Accepted
    fake_instance.DialogCode.Rejected = QDialog.DialogCode.Rejected
    if mode == ConflictMode.CANCEL:
        fake_instance.exec.return_value = QDialog.DialogCode.Rejected
    else:
        fake_instance.exec.return_value = QDialog.DialogCode.Accepted
    fake_instance.chosen_mode.return_value = mode
    fake_cls.return_value = fake_instance
    return patch(
        "scriptree.ui.install_dialogs.InstallConflictDialog",
        fake_cls,
    )


# ----------------------------------------------------------------------------
# Folder + zip source builders
# ----------------------------------------------------------------------------


def _make_app_folder(parent: Path, name: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    root = parent / name
    root.mkdir()
    (root / "tool.scriptree").write_text('{"name": "T"}', encoding="utf-8")
    (root / "README.md").write_text("# tool", encoding="utf-8")
    return root


def _make_app_zip(parent: Path, name: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    p = parent / name
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("tool.scriptree", '{"name": "T"}')
        zf.writestr("README.md", "# tool")
    return p


# ============================================================================
# Happy path: folder drop, no conflict
# ============================================================================


class TestFolderDrop:
    def test_folder_drop_installs(self, tmp_path: Path) -> None:
        cell = _make_forest_cell()
        try:
            src = _make_app_folder(tmp_path / "src", "MyTool")
            install_root = tmp_path / "install"

            with _patch_location_dialog(install_root):
                cell._handle_dropped_installable(str(src))

            target = install_root / "MyTool"
            assert target.is_dir()
            assert (target / "tool.scriptree").exists()
            assert (target / "README.md").exists()
        finally:
            cell.close()
            cell.deleteLater()


# ============================================================================
# Happy path: zip drop, no conflict
# ============================================================================


class TestZipDrop:
    def test_zip_drop_installs(self, tmp_path: Path) -> None:
        cell = _make_forest_cell()
        try:
            src = _make_app_zip(tmp_path / "src", "MyTool.zip")
            (tmp_path / "src").mkdir(exist_ok=True)
            src = _make_app_zip(tmp_path / "src", "MyTool.zip")
            install_root = tmp_path / "install"

            with _patch_location_dialog(install_root):
                cell._handle_dropped_installable(str(src))

            target = install_root / "MyTool"
            assert target.is_dir()
            assert (target / "tool.scriptree").exists()
        finally:
            cell.close()
            cell.deleteLater()


# ============================================================================
# Non-forest cells silently ignore
# ============================================================================


class TestNonForestCell:
    def test_non_forest_cell_ignores_installable(
        self, tmp_path: Path,
    ) -> None:
        cell = _make_forest_cell(is_forest_master=False)
        try:
            src = _make_app_folder(tmp_path / "src", "MyTool")
            install_root = tmp_path / "install"

            # Even with the dialogs patched, the handler should
            # never reach them -- the early guard returns first.
            with _patch_location_dialog(install_root):
                cell._handle_dropped_installable(str(src))

            # Nothing installed.
            assert not (install_root / "MyTool").exists()
        finally:
            cell.close()
            cell.deleteLater()


# ============================================================================
# Conflict path: target exists -> retry with chosen mode
# ============================================================================


class TestConflictRetry:
    def test_overwrite_replaces_existing(self, tmp_path: Path) -> None:
        cell = _make_forest_cell()
        try:
            src = _make_app_folder(tmp_path / "src", "MyTool")
            install_root = tmp_path / "install"
            # Pre-populate target with a sentinel file that
            # OVERWRITE should remove.
            existing = install_root / "MyTool"
            existing.mkdir(parents=True)
            (existing / "old.txt").write_text("old", encoding="utf-8")

            with _patch_location_dialog(install_root), \
                    _patch_conflict_dialog(ConflictMode.OVERWRITE):
                cell._handle_dropped_installable(str(src))

            assert not (existing / "old.txt").exists()
            assert (existing / "tool.scriptree").exists()
        finally:
            cell.close()
            cell.deleteLater()

    def test_update_preserves_user_file(self, tmp_path: Path) -> None:
        cell = _make_forest_cell()
        try:
            src = _make_app_folder(tmp_path / "src", "MyTool")
            install_root = tmp_path / "install"
            existing = install_root / "MyTool"
            existing.mkdir(parents=True)
            (existing / "my-edit.scriptree").write_text(
                "user-edited", encoding="utf-8",
            )

            with _patch_location_dialog(install_root), \
                    _patch_conflict_dialog(ConflictMode.UPDATE):
                cell._handle_dropped_installable(str(src))

            # User's file survives; source files arrive.
            assert (existing / "my-edit.scriptree").read_text(
                encoding="utf-8",
            ) == "user-edited"
            assert (existing / "tool.scriptree").exists()
        finally:
            cell.close()
            cell.deleteLater()

    def test_rename_lands_at_numbered_slot(self, tmp_path: Path) -> None:
        cell = _make_forest_cell()
        try:
            src = _make_app_folder(tmp_path / "src", "MyTool")
            install_root = tmp_path / "install"
            existing = install_root / "MyTool"
            existing.mkdir(parents=True)
            (existing / "original.txt").write_text("orig", encoding="utf-8")

            with _patch_location_dialog(install_root), \
                    _patch_conflict_dialog(ConflictMode.RENAME):
                cell._handle_dropped_installable(str(src))

            # Original survives.
            assert (existing / "original.txt").exists()
            # New copy at -2.
            renamed = install_root / "MyTool-2"
            assert renamed.is_dir()
            assert (renamed / "tool.scriptree").exists()
        finally:
            cell.close()
            cell.deleteLater()

    def test_conflict_cancel_leaves_fs_untouched(
        self, tmp_path: Path,
    ) -> None:
        cell = _make_forest_cell()
        try:
            src = _make_app_folder(tmp_path / "src", "MyTool")
            install_root = tmp_path / "install"
            existing = install_root / "MyTool"
            existing.mkdir(parents=True)
            (existing / "original.txt").write_text("orig", encoding="utf-8")

            with _patch_location_dialog(install_root), \
                    _patch_conflict_dialog(ConflictMode.CANCEL):
                cell._handle_dropped_installable(str(src))

            # Nothing changed; original is the ONLY file.
            assert (existing / "original.txt").exists()
            assert not (existing / "tool.scriptree").exists()
        finally:
            cell.close()
            cell.deleteLater()


# ============================================================================
# Location dialog cancel
# ============================================================================


class TestLocationCancel:
    def test_location_cancel_no_install(self, tmp_path: Path) -> None:
        cell = _make_forest_cell()
        try:
            src = _make_app_folder(tmp_path / "src", "MyTool")
            install_root = tmp_path / "install"

            with _patch_location_cancel():
                cell._handle_dropped_installable(str(src))

            # Nothing installed.
            assert not (install_root / "MyTool").exists()
        finally:
            cell.close()
            cell.deleteLater()


# ============================================================================
# Source doesn't exist
# ============================================================================


class TestBadSource:
    def test_missing_source_logged_and_ignored(
        self, tmp_path: Path,
    ) -> None:
        cell = _make_forest_cell()
        try:
            # Should NOT crash; should just log + return.
            cell._handle_dropped_installable(str(tmp_path / "nonexistent"))
        finally:
            cell.close()
            cell.deleteLater()


# ============================================================================
# Post-install refresh
# ============================================================================


class _FakeForestController:
    """A minimal real-class controller for the post-install
    refresh test.

    Using a plain class (rather than ``MagicMock``) lets the
    handler's bound-method recovery trick
    (``hook.__self__``) work properly -- a MagicMock's
    ``__self__`` is yet another MagicMock, not the original
    controller, so the refresh would land on the wrong
    object."""

    def __init__(self) -> None:
        self.refresh_calls: int = 0

    def _populate_forest_menu(self, menu: object) -> None:
        # Real ForestController populates the right-click menu
        # here; tests don't exercise it, so the body is a no-op.
        pass

    def refresh_from_sources(self) -> None:
        self.refresh_calls += 1


class TestPostInstallRefresh:
    def test_refresh_called_when_controller_attached(
        self, tmp_path: Path,
    ) -> None:
        """When a forest controller is attached to the cell, a
        successful install triggers its ``refresh_from_sources``
        so the new app appears in the forest right away."""
        cell = _make_forest_cell()
        try:
            fake_controller = _FakeForestController()
            cell._forest_menu_extension = (
                fake_controller._populate_forest_menu
            )

            src = _make_app_folder(tmp_path / "src", "MyTool")
            install_root = tmp_path / "install"

            with _patch_location_dialog(install_root):
                cell._handle_dropped_installable(str(src))

            assert fake_controller.refresh_calls == 1
        finally:
            cell.close()
            cell.deleteLater()

    def test_refresh_skipped_when_no_controller(
        self, tmp_path: Path,
    ) -> None:
        """Cell without a forest controller attached -- install
        completes silently; no error from the refresh attempt."""
        cell = _make_forest_cell()
        try:
            # No ``_forest_menu_extension`` set.
            cell._forest_menu_extension = None

            src = _make_app_folder(tmp_path / "src", "MyTool")
            install_root = tmp_path / "install"

            with _patch_location_dialog(install_root):
                cell._handle_dropped_installable(str(src))

            # Install still happened.
            assert (install_root / "MyTool" / "tool.scriptree").exists()
            # No exception was raised; that's the test.
        finally:
            cell.close()
            cell.deleteLater()
