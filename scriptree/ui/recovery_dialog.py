"""Shared dialog for "file not found" recovery.

Shown whenever ScripTree references a file that no longer exists on
disk — a tool file that a tree leaf points to, a tool's executable
path, a recently-opened file that has moved, etc.

The dialog has two operating modes:

**Simple mode** (default; used for missing .scriptree / .scriptreetree
files in the tree view and recent-files menu):

- Displays a clear message explaining what's missing.
- Shows the expected path in a read-only ``QLineEdit`` that's
  selectable / copy-pasteable.
- Optional **Browse for replacement...** button that opens a native
  file picker. If the user picks a file, the dialog accepts with
  the new path available via :meth:`selected_replacement`.
- Offers a **Close** button that dismisses the dialog without action.

**Path-scope mode** (used for missing tool *executables* via
``tool_runner._offer_missing_executable_recovery``): the same first
step (Browse to find the file) but instead of accepting immediately,
the dialog grows to show a **scope picker**. The user can choose to
either keep the v1 behavior (replace the path stored in the
.scriptree) or *just add the parent folder to a search path* at one
of several scopes (System / User PATH, the running session's env, the
tool's path_prepend, the parent tree's path_prepend). Per-file scopes
get an "apply to all in sidebar" checkbox so the user can fix every
loaded tool/tree in one click. Each scope is gated by a permission
capability; denied scopes render as a greyed-out row with a "denied
by IT — see permissions/<file>" note instead of being silently hidden,
so users always understand why options aren't available.

Permission enforcement for the original Browse button is the caller's
responsibility — pass ``allow_replace=False`` to hide the Browse
button entirely (e.g. when the user lacks ``edit_tree_structure`` /
``edit_tool_definition``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ..core.permissions import PermissionSet
from .widgets.param_widgets import _DroppableLineEdit


# Scope identifiers returned by selected_scope(). None of these are
# user-visible — they're the contract between the dialog and its
# caller for routing the chosen action.
SCOPE_REPLACE_FILE = "replace_file"
SCOPE_SESSION = "session"
SCOPE_SCRIPTREE = "scriptree"
SCOPE_SCRIPTREETREE = "scriptreetree"
SCOPE_USER_PATH = "user_path"
SCOPE_SYSTEM_PATH = "system_path"


@dataclass
class PathScopeOptions:
    """Caller-supplied context for the scope-picker UI.

    Each ``None`` / empty field disables the matching scope option.
    The dialog never invents a scope that wasn't supplied — if the
    caller doesn't know about a parent .scriptreetree, the
    "scriptreetree path_prepend" scope just doesn't appear.
    """

    # Path of the .scriptree file whose executable is missing. Used
    # to (a) save back when the user picks "replace path in this file"
    # and (b) target the "this tool's path_prepend" scope.
    scriptree_path: str | None = None

    # Path of the parent .scriptreetree, if the tool was opened via
    # the IDE tree. None means "no parent tree context available".
    scriptreetree_path: str | None = None

    # Lists of all currently-loaded .scriptree / .scriptreetree files
    # in the IDE sidebar. Drives the "apply to all" checkboxes for
    # the per-file scopes. Empty list -> the "apply to all" checkbox
    # for that scope hides itself (no point applying to "all of
    # nothing").
    all_scriptrees: list[str] = field(default_factory=list)
    all_scriptreetrees: list[str] = field(default_factory=list)

    # Permission set used to gate each scope. When None the dialog
    # treats every scope as allowed (testing convenience). Real
    # callers should always pass a real PermissionSet.
    permissions: PermissionSet | None = None


class MissingFileRecoveryDialog(QDialog):
    """Modal dialog for recovering from a missing-file reference."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        title: str,
        message: str,
        missing_path: str,
        allow_replace: bool,
        file_filter: str = "All files (*)",
        browse_caption: str = "Select replacement file",
        path_scope_options: PathScopeOptions | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(620)
        self._replacement_path: str | None = None
        self._file_filter = file_filter
        self._browse_caption = browse_caption
        self._scope_options = path_scope_options
        # Snapshot of the path the dialog opened with — used by
        # _on_path_edit_changed so a typed-back-to-original is treated
        # the same as "no replacement chosen yet".
        self._original_missing_path = missing_path
        # Result fields populated when the user accepts.
        self._selected_scope: str | None = None
        self._selected_directory: str | None = None
        self._apply_to_all: bool = False
        # Per-scope radio + checkbox refs, set during _build_scope_panel.
        self._scope_buttons: dict[str, QRadioButton] = {}
        self._apply_all_checkbox: QCheckBox | None = None

        self._outer = QVBoxLayout(self)

        msg = QLabel(message)
        msg.setWordWrap(True)
        self._outer.addWidget(msg)

        self._outer.addWidget(QLabel("<b>Expected location:</b>"))

        path_row = QHBoxLayout()
        # Editable + drop-aware. Users can type/paste a new path or
        # drag a file from Explorer onto the field — both are quicker
        # than clicking Browse for someone who already knows where the
        # binary lives. Browse remains available; it just no longer
        # has to be the only entry point.
        self._path_edit = _DroppableLineEdit(missing_path)
        self._path_edit.setCursorPosition(0)
        self._path_edit.setPlaceholderText(
            "Drop a file here, paste a path, or click Browse..."
        )
        self._path_edit.textChanged.connect(self._on_path_edit_changed)
        # Pressing Enter in the path field is the keyboard shortcut
        # for "I'm done — use this path". In simple mode it accepts the
        # dialog directly; in scope mode it just clicks Apply (which the
        # user must have already enabled by entering a valid path).
        self._path_edit.returnPressed.connect(self._on_path_edit_return)
        path_row.addWidget(self._path_edit, stretch=1)

        btn_copy = QPushButton("Copy")
        btn_copy.setToolTip("Copy the path to the clipboard.")
        btn_copy.clicked.connect(self._copy_path)
        path_row.addWidget(btn_copy)
        self._outer.addLayout(path_row)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._outer.addWidget(self._status_label)

        if not allow_replace:
            hint = QLabel(
                "<i>You don't have permission to replace this path. "
                "Copy it above and ask an administrator to fix the "
                "reference, or restore the file to the expected "
                "location.</i>"
            )
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #888;")
            self._outer.addWidget(hint)

        # Scope-picker frame — built here but only shown after Browse
        # picks a file (and only when path_scope_options were supplied).
        self._scope_frame: QGroupBox | None = None
        if path_scope_options is not None:
            self._scope_frame = self._build_scope_panel(path_scope_options)
            self._scope_frame.setVisible(False)
            self._outer.addWidget(self._scope_frame)

        # Button row.
        self._btn_row = QHBoxLayout()
        self._btn_row.addStretch(1)

        self._btn_browse: QPushButton | None = None
        if allow_replace:
            self._btn_browse = QPushButton("Browse for replacement...")
            self._btn_browse.setToolTip(
                "Pick a replacement file. Then choose how to remember "
                "the new location."
            )
            self._btn_browse.clicked.connect(self._browse)
            self._btn_row.addWidget(self._btn_browse)

        # OK button is hidden in simple mode (Browse accepts directly)
        # and only appears in scope-picker mode after Browse.
        self._btn_ok: QPushButton | None = None
        if path_scope_options is not None:
            self._btn_ok = QPushButton("Apply")
            self._btn_ok.setEnabled(False)
            self._btn_ok.clicked.connect(self._on_ok)
            self._btn_row.addWidget(self._btn_ok)

        self._btn_close = QPushButton("Close")
        self._btn_close.clicked.connect(self.reject)
        self._btn_row.addWidget(self._btn_close)

        self._outer.addLayout(self._btn_row)

    # --- scope-picker UI ------------------------------------------------

    def _build_scope_panel(
        self, opts: PathScopeOptions
    ) -> QGroupBox:
        """Construct the radio-button scope picker.

        Each scope is one row; denied scopes render as greyed-out
        radios with an "(no permission)" suffix. Per-file scopes get
        an "apply to all in sidebar" checkbox below them when the
        sidebar has more than just the current file.
        """
        box = QGroupBox(
            "What should we do with the new location?"
        )
        layout = QVBoxLayout(box)

        # The currently-selected radio. Defaults to "replace path in
        # this tool's .scriptree" — the v1 behavior. Always allowed
        # if the dialog was opened in scope mode, since the caller
        # already passed allow_replace to get here.
        group = QButtonGroup(box)
        self._scope_button_group = group

        def _add_row(
            scope: str,
            label: str,
            tooltip: str,
            allowed: bool,
            denied_reason: str = "",
        ) -> QRadioButton:
            row = QHBoxLayout()
            btn = QRadioButton(label)
            btn.setEnabled(allowed)
            btn.setToolTip(tooltip)
            self._scope_buttons[scope] = btn
            group.addButton(btn)
            row.addWidget(btn)

            if not allowed:
                note = QLabel(
                    f"<i>{denied_reason}</i>"
                )
                note.setStyleSheet("color: #888;")
                note.setWordWrap(True)
                row.addWidget(note, stretch=1)

            row.addStretch(1)
            wrapper = QWidget()
            wrapper.setLayout(row)
            layout.addWidget(wrapper)
            return btn

        perms = opts.permissions

        def _can(cap: str) -> bool:
            return perms is None or perms.can(cap)

        def _denied_msg(cap: str, friendly: str) -> str:
            return (
                f"Disabled by IT \u2014 to enable, ask an admin to "
                f"create the empty file <code>permissions/&lt;category&gt;/"
                f"{cap}</code> in the ScripTree install. "
                f"({friendly})"
            )

        # 1. Replace path in the .scriptree itself (always available).
        first = _add_row(
            SCOPE_REPLACE_FILE,
            "Replace the path stored in this tool's .scriptree",
            "Update the tool's executable field to the absolute "
            "path you just picked. Same as the v1 behavior.",
            allowed=True,
        )
        first.setChecked(True)  # default selection

        layout.addWidget(QLabel(
            "<i>Or, instead of editing the .scriptree, add the "
            "new folder to a search path:</i>"
        ))

        # 2. Session env (lost on exit, no admin, low blast radius).
        _add_row(
            SCOPE_SESSION,
            "Add folder to ScripTree session PATH (this run only)",
            "Modify os.environ['PATH'] in the running ScripTree "
            "process. Affects every tool you launch this session "
            "but disappears when ScripTree exits.",
            allowed=_can("add_to_session_path"),
            denied_reason=_denied_msg(
                "add_to_session_path",
                "session-only, no admin needed, low risk",
            ),
        )

        # 3. This .scriptree's path_prepend.
        st_allowed = (
            _can("add_to_scriptree_path_prepend")
            and opts.scriptree_path is not None
        )
        st_denied_reason = (
            _denied_msg(
                "add_to_scriptree_path_prepend",
                "writes to this single .scriptree file",
            )
            if not _can("add_to_scriptree_path_prepend")
            else "<i>(no .scriptree file context available)</i>"
        )
        _add_row(
            SCOPE_SCRIPTREE,
            "Add folder to this tool's .scriptree path_prepend",
            "Append the folder to the tool's path_prepend list and "
            "save the .scriptree file. Future launches of this tool "
            "(in this or any future ScripTree session) will pick it up.",
            allowed=st_allowed,
            denied_reason=st_denied_reason,
        )

        # 4. The parent .scriptreetree's path_prepend.
        sttree_allowed = (
            _can("add_to_scriptreetree_path_prepend")
            and opts.scriptreetree_path is not None
        )
        sttree_denied_reason = (
            _denied_msg(
                "add_to_scriptreetree_path_prepend",
                "writes to the parent .scriptreetree file",
            )
            if not _can("add_to_scriptreetree_path_prepend")
            else "<i>(no .scriptreetree parent loaded)</i>"
        )
        _add_row(
            SCOPE_SCRIPTREETREE,
            "Add folder to this tree's .scriptreetree path_prepend",
            "Append the folder to the .scriptreetree's path_prepend "
            "list. Inherited by every tool launched via this tree.",
            allowed=sttree_allowed,
            denied_reason=sttree_denied_reason,
        )

        # "Apply to all" checkbox — single checkbox for whichever
        # per-file scope the user picks (kept simple instead of one
        # per scope). The label updates live via radio toggles.
        all_count = (
            len(opts.all_scriptrees) + len(opts.all_scriptreetrees)
        )
        if all_count > 1:
            indent = QHBoxLayout()
            indent.addSpacing(20)
            self._apply_all_checkbox = QCheckBox(
                "Also apply to all .scriptree / .scriptreetree files "
                "in the sidebar"
            )
            self._apply_all_checkbox.setToolTip(
                f"Iterates the IDE sidebar tree "
                f"({len(opts.all_scriptrees)} .scriptree, "
                f"{len(opts.all_scriptreetrees)} .scriptreetree) and "
                "applies the same path_prepend update to each. Only "
                "active when one of the per-file scopes is selected."
            )
            self._apply_all_checkbox.setEnabled(False)
            indent.addWidget(self._apply_all_checkbox)
            indent.addStretch(1)
            wrapper = QWidget()
            wrapper.setLayout(indent)
            layout.addWidget(wrapper)

            # Wire up enable/disable based on radio state.
            def _refresh_apply_all():
                if self._apply_all_checkbox is None:
                    return
                checked = (
                    self._scope_buttons.get(SCOPE_SCRIPTREE)
                    and self._scope_buttons[SCOPE_SCRIPTREE].isChecked()
                ) or (
                    self._scope_buttons.get(SCOPE_SCRIPTREETREE)
                    and self._scope_buttons[SCOPE_SCRIPTREETREE].isChecked()
                )
                self._apply_all_checkbox.setEnabled(bool(checked))
                if not checked:
                    self._apply_all_checkbox.setChecked(False)

            for btn in group.buttons():
                btn.toggled.connect(lambda _: _refresh_apply_all())

        # 5. User PATH.
        _add_row(
            SCOPE_USER_PATH,
            "Add folder to user PATH (persistent, no admin)",
            "Modify the current user's PATH (HKCU\\Environment\\Path "
            "on Windows). Persists across sessions and is picked up "
            "by future processes you launch from anywhere.",
            allowed=_can("add_to_user_path"),
            denied_reason=_denied_msg(
                "add_to_user_path",
                "modifies the current user's PATH; affects every "
                "shell / program the user runs",
            ),
        )

        # 6. System PATH (heaviest).
        _add_row(
            SCOPE_SYSTEM_PATH,
            "Add folder to system PATH (persistent, requires admin)",
            "Modify the system PATH (HKLM on Windows). Affects every "
            "user on this machine. Requires admin elevation.",
            allowed=_can("add_to_system_path"),
            denied_reason=_denied_msg(
                "add_to_system_path",
                "system-wide; requires admin elevation",
            ),
        )

        return box

    # --- slots ---------------------------------------------------------

    def _copy_path(self) -> None:
        QApplication.clipboard().setText(self._path_edit.text())
        self._status_label.setText(
            "<span style='color:#007700;'>Path copied to clipboard.</span>"
        )

    def _on_path_edit_changed(self, text: str) -> None:
        """User typed/pasted/dropped a new path into the field.

        Treat any path that points to a real file as a candidate
        replacement: reveal the scope picker and enable Apply, mirroring
        the post-Browse state. If the user erases the field or types
        garbage we hide the picker again and disable Apply, since there
        is no replacement to act on.
        """
        text = text.strip()
        candidate = (
            text if text and text != self._original_missing_path
            and Path(text).is_file()
            else None
        )
        if candidate is None:
            self._replacement_path = None
            if self._scope_options is not None:
                if self._scope_frame is not None:
                    self._scope_frame.setVisible(False)
                if self._btn_ok is not None:
                    self._btn_ok.setEnabled(False)
                if self._btn_browse is not None:
                    self._btn_browse.setEnabled(True)
            return

        self._replacement_path = candidate
        if self._scope_options is not None:
            self._activate_scope_picker(candidate)

    def _on_path_edit_return(self) -> None:
        """Enter-key in the path field. Accept (simple mode) or apply
        (scope mode), but only when the typed path is a real file."""
        if self._replacement_path is None:
            return
        if self._scope_options is None:
            self.accept()
        elif self._btn_ok is not None and self._btn_ok.isEnabled():
            self._on_ok()

    def _activate_scope_picker(self, picked_path: str) -> None:
        """Reveal the scope picker after a path has been picked."""
        if self._scope_frame is not None:
            self._scope_frame.setVisible(True)
        if self._btn_ok is not None:
            self._btn_ok.setEnabled(True)
        if self._btn_browse is not None:
            self._btn_browse.setEnabled(False)
        self._status_label.setText(
            f"<span style='color:#007700;'>Selected: {picked_path}</span>"
        )
        self.adjustSize()

    def _browse(self) -> None:
        start_dir = str(Path(self._path_edit.text()).parent)
        path, _ = QFileDialog.getOpenFileName(
            self, self._browse_caption, start_dir, self._file_filter,
        )
        if not path:
            return
        # Writing to the field triggers _on_path_edit_changed which
        # sets _replacement_path, reveals the picker (scope mode), or
        # accepts the dialog (simple mode below).
        self._path_edit.setText(path)
        self._replacement_path = path

        if self._scope_options is None:
            # Simple mode — accept immediately, caller reads
            # selected_replacement().
            self.accept()
            return
        # Scope mode — _on_path_edit_changed already revealed the picker.

    def _on_ok(self) -> None:
        # Determine which scope radio is checked.
        for scope, btn in self._scope_buttons.items():
            if btn.isChecked():
                self._selected_scope = scope
                break
        self._selected_directory = (
            str(Path(self._replacement_path).parent)
            if self._replacement_path else None
        )
        self._apply_to_all = bool(
            self._apply_all_checkbox is not None
            and self._apply_all_checkbox.isChecked()
        )
        self.accept()

    # --- result accessors ---------------------------------------------

    def selected_replacement(self) -> str | None:
        """Path the user picked via Browse. None if they cancelled."""
        return self._replacement_path

    def selected_scope(self) -> str | None:
        """Which scope the user chose (one of the SCOPE_* constants).

        ``None`` when the dialog wasn't opened in scope mode (simple
        callers in tree_view / main_window). In scope mode, defaults
        to ``SCOPE_REPLACE_FILE`` if the user accepts without changing
        the radio (matches the v1 behavior of the simple Browse flow).
        """
        return self._selected_scope

    def selected_directory(self) -> str | None:
        """Folder portion of the replacement path.

        Used by all scopes except ``SCOPE_REPLACE_FILE`` (which uses
        the full file path via :meth:`selected_replacement`).
        """
        return self._selected_directory

    def apply_to_all(self) -> bool:
        """Whether the "apply to all in sidebar" checkbox was on."""
        return self._apply_to_all
