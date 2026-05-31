"""Tests for the install-roots rows on the application SettingsDialog.

The two rows are part of the v0.8.0a23 drop-install feature.  These
tests pin the contract that:

* The QLineEdit values are pre-populated from the QSettings keys
  ``install.shared_root`` / ``install.personal_root``.
* The matching result accessors return what the edits hold,
  stripped of surrounding whitespace.
* A blank field round-trips as an empty string (the convention
  meaning "use the OS default" -- see
  ``scriptree.core.app_install.default_shared_root``).

The dialog is exercised via direct widget access rather than Qt
event simulation, matching the established pattern in
``tests/test_install_dialogs.py``.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.ui.settings_dialog import SettingsDialog


def _fresh_settings() -> QSettings:
    """An in-memory QSettings so tests don't pollute the user INI."""
    s = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                  "ScripTreeTests", "settings_dialog_install_rows")
    s.clear()
    return s


class TestInstallRowDefaults:
    def test_blank_when_no_settings_saved(self) -> None:
        s = _fresh_settings()
        dlg = SettingsDialog(s)
        assert dlg.result_install_shared_root() == ""
        assert dlg.result_install_personal_root() == ""

    def test_prepopulated_from_settings(self, tmp_path) -> None:
        s = _fresh_settings()
        shared = tmp_path / "shared_apps"
        personal = tmp_path / "personal_apps"
        s.setValue("install.shared_root", str(shared))
        s.setValue("install.personal_root", str(personal))
        dlg = SettingsDialog(s)
        assert dlg.result_install_shared_root() == str(shared)
        assert dlg.result_install_personal_root() == str(personal)


class TestInstallRowEdit:
    def test_set_via_line_edit(self, tmp_path) -> None:
        s = _fresh_settings()
        dlg = SettingsDialog(s)
        new_shared = str(tmp_path / "x" / "y")
        dlg._install_shared_edit.setText(new_shared)
        assert dlg.result_install_shared_root() == new_shared

    def test_whitespace_stripped(self) -> None:
        s = _fresh_settings()
        dlg = SettingsDialog(s)
        dlg._install_shared_edit.setText("   C:/Tools/Apps   ")
        assert dlg.result_install_shared_root() == "C:/Tools/Apps"

    def test_blank_round_trip(self) -> None:
        s = _fresh_settings()
        s.setValue("install.shared_root", "/tmp/shared")
        dlg = SettingsDialog(s)
        dlg._install_shared_edit.setText("")
        assert dlg.result_install_shared_root() == ""
