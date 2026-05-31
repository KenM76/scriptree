"""Application-wide Settings dialog.

## For humans

Accessible via Edit → Settings. Provides:

1. **Layout** — checkbox to remember/restore the window layout on restart.
2. **Permissions / Settings paths** — relocation overrides for the
   permissions folder and the settings INI file itself.
3. **Personal configurations folder** — where per-user, hand-edited
   tool configurations live.
4. **Drop-install locations** — shared + personal roots for the
   drag-folder-onto-forest-cell install flow (v0.8.0a23+).  Blank
   means "use OS defaults" -- see
   :mod:`scriptree.core.app_install` for fall-back rules.
5. **Global environment variables** — KEY=VALUE pairs with their own
   override checkbox.
6. **Global PATH prepend** — directories to prepend to PATH, with their
   own override checkbox.

## For maintainers / LLMs

- This dialog is a pure value container: after ``exec() ==
  Accepted`` the caller reads the result accessors and is solely
  responsible for persisting to ``QSettings`` (key ``"ScripTree"``).
  The dialog itself does NOT write ``QSettings`` — don't add silent
  persistence here or two code paths will fight over the same keys.
- The env / PATH text boxes use the same one-entry-per-line text
  convention as :mod:`env_editor`; parsing/validation semantics must
  stay consistent with that module so global vs tool-level env behave
  identically.
- Each override group is gated by its own checkbox: an unchecked
  group means "do not apply", which is distinct from "apply empty".
  Callers must honour the checkbox state, not just the text content.
- ``_SETTINGS_KEY`` is duplicated in :mod:`main_window`; keep the two
  literals in sync — they index the same ``QSettings`` namespace.
- Settings dialogs are constructed with a real parent so they centre
  on the main window; preserve the ``parent`` argument when editing
  construction.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_SETTINGS_KEY = "ScripTree"


class SettingsDialog(QDialog):
    """Application settings dialog.

    After ``exec() == Accepted``, read the result methods to apply
    changed settings. The caller is responsible for persisting to
    ``QSettings``.
    """

    def __init__(
        self,
        settings: QSettings,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ScripTree Settings")
        self.setMinimumWidth(520)
        self.resize(580, 560)
        self._settings = settings

        root = QVBoxLayout(self)

        # --- Layout section ---
        layout_group = QGroupBox("Layout")
        layout_lay = QVBoxLayout(layout_group)

        self._chk_remember_layout = QCheckBox(
            "Remember window layout on exit"
        )
        self._chk_remember_layout.setToolTip(
            "When enabled, ScripTree saves the position, size, and "
            "dock arrangement of the main window and restores them "
            "on next startup."
        )
        self._chk_remember_layout.setChecked(
            settings.value("remember_layout", True, type=bool)
        )
        layout_lay.addWidget(self._chk_remember_layout)
        root.addWidget(layout_group)

        # --- Permissions path ---
        perm_group = QGroupBox("Permissions")
        perm_lay = QVBoxLayout(perm_group)

        perm_hint = QLabel(
            "<i>Custom path to the permissions folder. To enable "
            "changing this location, you must first add the "
            "<b>settings/change_permissions_path</b> permission file "
            "to the <b>current</b> permissions folder and ensure it "
            "is writable for your user.</i>"
        )
        perm_hint.setWordWrap(True)
        perm_lay.addWidget(perm_hint)

        perm_row = QHBoxLayout()
        self._perm_path_edit = QLineEdit()
        self._perm_path_edit.setPlaceholderText(
            "(default — auto-detected from project root)"
        )
        saved_perm_path = settings.value("permissions_path", "", type=str)
        self._perm_path_edit.setText(saved_perm_path)
        perm_row.addWidget(self._perm_path_edit, stretch=1)

        self._btn_browse_perm = QPushButton("Browse...")
        self._btn_browse_perm.clicked.connect(self._browse_permissions_dir)
        perm_row.addWidget(self._btn_browse_perm)
        perm_lay.addLayout(perm_row)

        # Disable if the user doesn't have the capability.
        from ..core.permissions import get_app_permissions
        _perms = get_app_permissions(saved_perm_path or None)
        if not _perms.can("change_permissions_path"):
            self._perm_path_edit.setEnabled(False)
            self._btn_browse_perm.setEnabled(False)
            self._perm_path_edit.setToolTip(
                "You do not have permission to change this. "
                "Add the settings/change_permissions_path file "
                "to the current permissions folder first."
            )

        root.addWidget(perm_group)

        # --- Settings path ---
        settings_group = QGroupBox("Settings file location")
        settings_lay = QVBoxLayout(settings_group)

        settings_hint = QLabel(
            "<i>Custom path for the settings INI file. To enable "
            "changing this, add a <b>change_settings_path</b> "
            "permission file to your current permissions folder.</i>"
        )
        settings_hint.setWordWrap(True)
        settings_lay.addWidget(settings_hint)

        settings_row = QHBoxLayout()
        self._settings_path_edit = QLineEdit()
        self._settings_path_edit.setPlaceholderText(
            "(default — scriptree.ini in project root)"
        )
        saved_settings_path = settings.value("settings_path", "", type=str)
        self._settings_path_edit.setText(saved_settings_path)
        settings_row.addWidget(self._settings_path_edit, stretch=1)

        self._btn_browse_settings = QPushButton("Browse...")
        self._btn_browse_settings.clicked.connect(self._browse_settings_file)
        settings_row.addWidget(self._btn_browse_settings)
        settings_lay.addLayout(settings_row)

        if not _perms.can("change_settings_path"):
            self._settings_path_edit.setEnabled(False)
            self._btn_browse_settings.setEnabled(False)
            self._settings_path_edit.setToolTip(
                "Add the change_settings_path permission file first."
            )

        root.addWidget(settings_group)

        # --- Personal configurations folder ---
        pc_group = QGroupBox("Personal configurations folder")
        pc_lay = QVBoxLayout(pc_group)

        pc_hint = QLabel(
            "<i>Where your personal configurations are stored. "
            "Personal configs are private to you and live outside the "
            "shared tool sidecar. Leave blank for the default "
            "(<code>ScripTree/user_configs/</code>).</i>"
        )
        pc_hint.setWordWrap(True)
        pc_lay.addWidget(pc_hint)

        pc_row = QHBoxLayout()
        self._personal_configs_edit = QLineEdit()
        self._personal_configs_edit.setPlaceholderText(
            "(default — ScripTree/user_configs/)"
        )
        saved_pc = settings.value("personal_configs_path", "", type=str)
        self._personal_configs_edit.setText(saved_pc)
        pc_row.addWidget(self._personal_configs_edit, stretch=1)

        self._btn_browse_personal = QPushButton("Browse...")
        self._btn_browse_personal.clicked.connect(
            self._browse_personal_configs_dir
        )
        pc_row.addWidget(self._btn_browse_personal)
        pc_lay.addLayout(pc_row)

        root.addWidget(pc_group)

        # --- Drop-install roots ---
        # Two locations where dragged folders/zips land on the forest
        # cell.  Both default to OS-canonical paths resolved by
        # ``scriptree.core.app_install.default_shared_root`` /
        # ``default_personal_root``; leaving these fields blank means
        # "use the default".  When set, the values are honoured FIRST
        # before the OS fall-back logic kicks in.  See
        # ``scriptree/core/app_install.py`` for the resolution order.
        install_group = QGroupBox("Drop-install locations")
        install_lay = QVBoxLayout(install_group)

        install_hint = QLabel(
            "<i>When you drag a folder or zip onto a forest cell, "
            "ScripTree offers to install it in one of these "
            "locations.  Leave blank for the OS defaults "
            "(<code>&lt;install&gt;/ScripTreeApps/</code> for "
            "<b>shared</b>; per-user app data for "
            "<b>personal</b>).</i>"
        )
        install_hint.setWordWrap(True)
        install_lay.addWidget(install_hint)

        # Shared row.
        shared_label = QLabel("Shared root:")
        install_lay.addWidget(shared_label)
        shared_row = QHBoxLayout()
        self._install_shared_edit = QLineEdit()
        self._install_shared_edit.setPlaceholderText(
            "(default — <ScripTree install>/ScripTreeApps/)"
        )
        saved_shared = settings.value(
            "install.shared_root", "", type=str,
        )
        self._install_shared_edit.setText(saved_shared)
        shared_row.addWidget(self._install_shared_edit, stretch=1)
        self._btn_browse_install_shared = QPushButton("Browse...")
        self._btn_browse_install_shared.clicked.connect(
            self._browse_install_shared_dir
        )
        shared_row.addWidget(self._btn_browse_install_shared)
        install_lay.addLayout(shared_row)

        # Personal row.
        personal_label = QLabel("Personal root:")
        install_lay.addWidget(personal_label)
        personal_row = QHBoxLayout()
        self._install_personal_edit = QLineEdit()
        self._install_personal_edit.setPlaceholderText(
            "(default — OS per-user app data)"
        )
        saved_personal = settings.value(
            "install.personal_root", "", type=str,
        )
        self._install_personal_edit.setText(saved_personal)
        personal_row.addWidget(
            self._install_personal_edit, stretch=1,
        )
        self._btn_browse_install_personal = QPushButton("Browse...")
        self._btn_browse_install_personal.clicked.connect(
            self._browse_install_personal_dir
        )
        personal_row.addWidget(self._btn_browse_install_personal)
        install_lay.addLayout(personal_row)

        root.addWidget(install_group)

        # --- Global environment variables ---
        env_group = QGroupBox("Global environment variables")
        env_lay = QVBoxLayout(env_group)

        hint_env = QLabel(
            "<i>Enter KEY=VALUE pairs, one per line. These are merged "
            "into every tool's environment at run time.</i>"
        )
        hint_env.setWordWrap(True)
        env_lay.addWidget(hint_env)

        self._env_edit = QPlainTextEdit()
        self._env_edit.setPlaceholderText(
            "PYTHONPATH=C:\\my\\libs\n"
            "LOG_LEVEL=info"
        )
        saved_env = settings.value("global_env", "", type=str)
        self._env_edit.setPlainText(saved_env)
        env_lay.addWidget(self._env_edit)

        self._chk_override_tool_env = QCheckBox(
            "Override tool and configuration environment variables"
        )
        self._chk_override_tool_env.setToolTip(
            "When enabled, the global environment variables above take "
            "the highest priority — they override values set in "
            "individual tool definitions and configurations. When "
            "disabled, they sit between OS environment and tool-level "
            "env (tools can still override them)."
        )
        self._chk_override_tool_env.setChecked(
            settings.value("global_env_override", False, type=bool)
        )
        env_lay.addWidget(self._chk_override_tool_env)
        root.addWidget(env_group, stretch=1)

        # --- Global PATH prepend ---
        path_group = QGroupBox("Global PATH prepend")
        path_lay = QVBoxLayout(path_group)

        hint_path = QLabel(
            "<i>Enter directories, one per line. These are prepended "
            "to the PATH for every tool run.</i>"
        )
        hint_path.setWordWrap(True)
        path_lay.addWidget(hint_path)

        self._path_edit = QPlainTextEdit()
        self._path_edit.setPlaceholderText(
            "C:\\Tools\\bin\n"
            "C:\\PortableApps\\Python"
        )
        saved_path = settings.value("global_path_prepend", "", type=str)
        self._path_edit.setPlainText(saved_path)
        path_lay.addWidget(self._path_edit)

        self._chk_override_tool_path = QCheckBox(
            "Override tool and configuration PATH entries"
        )
        self._chk_override_tool_path.setToolTip(
            "When enabled, the global PATH directories above are "
            "prepended at the highest priority — before any PATH "
            "entries from individual tools or configurations. When "
            "disabled, they are prepended after tool and config "
            "entries (lower search priority)."
        )
        self._chk_override_tool_path.setChecked(
            settings.value("global_path_override", False, type=bool)
        )
        path_lay.addWidget(self._chk_override_tool_path)
        root.addWidget(path_group, stretch=1)

        # --- OK / Cancel ---
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _browse_permissions_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select permissions folder",
            self._perm_path_edit.text(),
        )
        if path:
            self._perm_path_edit.setText(path)

    def _browse_settings_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Select settings INI file",
            self._settings_path_edit.text() or "scriptree.ini",
            "INI files (*.ini);;All files (*)",
        )
        if path:
            self._settings_path_edit.setText(path)

    def _browse_personal_configs_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select personal configurations folder",
            self._personal_configs_edit.text(),
        )
        if path:
            self._personal_configs_edit.setText(path)

    def _browse_install_shared_dir(self) -> None:
        """Pick a folder for the shared drop-install root.

        Empty string in the edit means "use the default" -- the
        browse dialog defaults to the home directory so the user has
        a sensible starting point if they haven't picked anything
        yet.
        """
        start = self._install_shared_edit.text().strip()
        path = QFileDialog.getExistingDirectory(
            self, "Select shared drop-install root", start,
        )
        if path:
            self._install_shared_edit.setText(path)

    def _browse_install_personal_dir(self) -> None:
        """Pick a folder for the personal drop-install root."""
        start = self._install_personal_edit.text().strip()
        path = QFileDialog.getExistingDirectory(
            self, "Select personal drop-install root", start,
        )
        if path:
            self._install_personal_edit.setText(path)

    # --- result accessors ---

    def result_permissions_path(self) -> str:
        return self._perm_path_edit.text().strip()

    def result_settings_path(self) -> str:
        return self._settings_path_edit.text().strip()

    def result_personal_configs_path(self) -> str:
        return self._personal_configs_edit.text().strip()

    def result_install_shared_root(self) -> str:
        """Return the user-chosen shared drop-install root.

        Empty string means "use the default" -- ``app_install``
        treats blank as "no override" and falls back to its OS rules.
        """
        return self._install_shared_edit.text().strip()

    def result_install_personal_root(self) -> str:
        """Return the user-chosen personal drop-install root.

        Empty string means "use the default" (OS per-user app data).
        """
        return self._install_personal_edit.text().strip()

    def result_remember_layout(self) -> bool:
        return self._chk_remember_layout.isChecked()

    def result_global_env_text(self) -> str:
        """Return the raw KEY=VALUE text."""
        return self._env_edit.toPlainText()

    def result_global_env(self) -> dict[str, str]:
        """Parse the env text into a dict."""
        return _parse_env_text(self._env_edit.toPlainText())

    def result_override_tool_env(self) -> bool:
        return self._chk_override_tool_env.isChecked()

    def result_global_path_text(self) -> str:
        """Return the raw path-prepend text."""
        return self._path_edit.toPlainText()

    def result_global_path_prepend(self) -> list[str]:
        """Parse the path text into a list of directories."""
        return _parse_path_text(self._path_edit.toPlainText())

    def result_override_tool_path(self) -> bool:
        return self._chk_override_tool_path.isChecked()


def _parse_env_text(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines into a dict. Blank lines and comments ignored."""
    env: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            env[key] = value.strip()
    return env


def _parse_path_text(text: str) -> list[str]:
    """Parse one-directory-per-line text into a list. Blank/comments ignored."""
    paths: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        paths.append(line)
    return paths


def load_global_env(settings: QSettings) -> dict[str, str]:
    """Load the global env dict from QSettings."""
    raw = settings.value("global_env", "", type=str)
    return _parse_env_text(raw)


def load_global_path_prepend(settings: QSettings) -> list[str]:
    """Load the global PATH prepend list from QSettings."""
    raw = settings.value("global_path_prepend", "", type=str)
    return _parse_path_text(raw)


def global_env_overrides_tool(settings: QSettings) -> bool:
    """Return True if global env should override tool-level env."""
    return settings.value("global_env_override", False, type=bool)


def global_path_overrides_tool(settings: QSettings) -> bool:
    """Return True if global PATH should override tool-level path."""
    return settings.value("global_path_override", False, type=bool)
