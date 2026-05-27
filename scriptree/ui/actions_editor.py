"""Editor dialog for ``ToolDef.actions`` — the action-button list.

## For humans

A two-pane dialog launched from the tool editor's "Edit actions..."
button.  Left pane: list of actions with add / remove / up / down
controls.  Right pane: per-action form (id, label, tooltip, argv,
popup mode, confirm text, icon, hidden, section).  OK commits to
the caller's actions list; Cancel discards.

## For maintainers / LLMs

* The dialog owns a **copy** of the actions list (``self._actions``).
  Mutations don't reach the caller until OK is pressed.  This matches
  ``MenuEditorDialog``'s lifecycle so the two editors stay
  conceptually parallel.
* ``ActionDef.__post_init__`` validates id format / popup enum at
  construction time, but the dialog ALSO does its own live checks
  (id pattern + duplicate id) before committing so the user gets a
  inline error before clicking OK and seeing a ValueError stack.
* Argv is edited as one literal arg per line (multi-line text edit).
  Empty lines are stripped.  This matches the visual the user sees
  in the docs ("argv": ["status", "--short"]) and lets them edit
  flag values that contain spaces without quoting headaches.
* Section combobox is populated from ``ToolDef.sections`` so the
  user can only pick a declared section.  The empty entry ("--") is
  always available and maps to ``ActionDef.section = ""``.
"""
from __future__ import annotations

import re
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core.model import ActionDef, ToolDef


_ID_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


class ActionsEditorDialog(QDialog):
    """Edit ``ToolDef.actions`` via a two-pane list + form."""

    def __init__(
        self,
        actions: list[ActionDef],
        *,
        tool: ToolDef,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit action buttons")
        self.resize(820, 540)

        # Deep copy so mutations don't reach the caller until OK.
        self._actions: list[ActionDef] = deepcopy(actions)
        self._tool = tool
        self._current_index: int | None = None
        self._building_panel = False  # guard for signal storms

        self._build_ui()
        self._refresh_list()
        if self._actions:
            self._list.setCurrentRow(0)
        else:
            self._set_form_enabled(False)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        intro = QLabel(
            "Action buttons appear next to the Run button.  Each one fires "
            "with a fixed argv -- form fields are NOT substituted.  Use "
            "them for quick presets (git status, pip list, "
            "diagnostic dumps) that don't need user input."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#555;")
        outer.addWidget(intro)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, stretch=1)

        # --- Left: action list + add/remove/up/down ---
        left = QGroupBox("Actions")
        ll = QVBoxLayout(left)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_selection_changed)
        ll.addWidget(self._list, stretch=1)

        btn_row = QHBoxLayout()
        self._btn_add = QPushButton("+ Add")
        self._btn_add.clicked.connect(self._add_action)
        btn_row.addWidget(self._btn_add)
        self._btn_remove = QPushButton("Remove")
        self._btn_remove.clicked.connect(self._remove_action)
        btn_row.addWidget(self._btn_remove)
        self._btn_up = QPushButton("↑")
        self._btn_up.setFixedWidth(36)
        self._btn_up.clicked.connect(lambda: self._move(-1))
        btn_row.addWidget(self._btn_up)
        self._btn_down = QPushButton("↓")
        self._btn_down.setFixedWidth(36)
        self._btn_down.clicked.connect(lambda: self._move(1))
        btn_row.addWidget(self._btn_down)
        ll.addLayout(btn_row)
        splitter.addWidget(left)

        # --- Right: per-action form ---
        right = QGroupBox("Properties")
        form = QFormLayout(right)

        self._id_edit = QLineEdit()
        self._id_edit.textChanged.connect(self._on_id_changed)
        self._id_edit.setPlaceholderText("e.g. status, log10, branches")
        form.addRow("Id:", self._id_edit)

        self._id_warning = QLabel("")
        self._id_warning.setStyleSheet("color:#b00; font-style:italic;")
        form.addRow("", self._id_warning)

        self._label_edit = QLineEdit()
        self._label_edit.textChanged.connect(self._on_label_changed)
        self._label_edit.setPlaceholderText("Button text shown in the UI")
        form.addRow("Label:", self._label_edit)

        self._tooltip_edit = QLineEdit()
        self._tooltip_edit.textChanged.connect(self._on_tooltip_changed)
        self._tooltip_edit.setPlaceholderText(
            "Hover text (blank = show the resolved argv)"
        )
        form.addRow("Tooltip:", self._tooltip_edit)

        self._argv_edit = QPlainTextEdit()
        self._argv_edit.setPlaceholderText(
            "One argument per line.\n"
            "Example:\n"
            "  status\n"
            "  --short"
        )
        self._argv_edit.setMinimumHeight(96)
        self._argv_edit.textChanged.connect(self._on_argv_changed)
        form.addRow("Argv:", self._argv_edit)

        self._popup_combo = QComboBox()
        self._popup_combo.addItems(["never", "auto", "always"])
        self._popup_combo.currentTextChanged.connect(self._on_popup_changed)
        self._popup_combo.setToolTip(
            "never (default): stream to output pane only.\n"
            "auto: also open a copy-friendly modal when output is short.\n"
            "always: open the modal regardless of output size."
        )
        form.addRow("Popup:", self._popup_combo)

        self._confirm_edit = QLineEdit()
        self._confirm_edit.textChanged.connect(self._on_confirm_changed)
        self._confirm_edit.setPlaceholderText(
            "Leave blank for no confirm prompt"
        )
        form.addRow("Confirm:", self._confirm_edit)

        self._icon_edit = QLineEdit()
        self._icon_edit.textChanged.connect(self._on_icon_changed)
        self._icon_edit.setPlaceholderText(
            "Optional icon name from the bundled icon library"
        )
        form.addRow("Icon:", self._icon_edit)

        self._hidden_check = QCheckBox(
            "Hidden (registered but no visible button)"
        )
        self._hidden_check.toggled.connect(self._on_hidden_changed)
        form.addRow("", self._hidden_check)

        self._section_combo = QComboBox()
        self._section_combo.currentIndexChanged.connect(
            self._on_section_changed
        )
        self._refresh_section_combo()
        form.addRow("Section:", self._section_combo)

        # Live argv preview so the user sees what will fire when the
        # button is clicked.
        self._preview = QLabel("")
        self._preview.setStyleSheet(
            "color:#333; background:#f6f6f6; "
            "padding:4px; border:1px solid #ddd;"
        )
        self._preview.setWordWrap(True)
        self._preview.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        form.addRow("Will run:", self._preview)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        # --- Bottom: OK / Cancel ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _refresh_section_combo(self) -> None:
        self._section_combo.clear()
        self._section_combo.addItem("(none — render in Actions row)", "")
        for s in self._tool.sections:
            self._section_combo.addItem(s.name, s.name)

    # ------------------------------------------------------------------
    # List management
    # ------------------------------------------------------------------

    def _refresh_list(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for a in self._actions:
            item = QListWidgetItem(self._format_list_label(a))
            self._list.addItem(item)
        self._list.blockSignals(False)

    @staticmethod
    def _format_list_label(a: ActionDef) -> str:
        tag = " [hidden]" if a.hidden else ""
        return f"{a.label or '(unnamed)'}  ·  {a.id or '?'}{tag}"

    def _add_action(self) -> None:
        # Pick a unique default id.
        existing_ids = {a.id for a in self._actions}
        n = 1
        new_id = "new_action"
        while new_id in existing_ids:
            n += 1
            new_id = f"new_action_{n}"
        new = ActionDef(id=new_id, label="New action")
        self._actions.append(new)
        self._refresh_list()
        self._list.setCurrentRow(len(self._actions) - 1)

    def _remove_action(self) -> None:
        idx = self._current_index
        if idx is None:
            return
        del self._actions[idx]
        self._refresh_list()
        if self._actions:
            self._list.setCurrentRow(min(idx, len(self._actions) - 1))
        else:
            self._current_index = None
            self._clear_form()
            self._set_form_enabled(False)

    def _move(self, delta: int) -> None:
        idx = self._current_index
        if idx is None:
            return
        new = idx + delta
        if not (0 <= new < len(self._actions)):
            return
        self._actions[idx], self._actions[new] = (
            self._actions[new], self._actions[idx],
        )
        self._refresh_list()
        self._list.setCurrentRow(new)

    # ------------------------------------------------------------------
    # Selection / form sync
    # ------------------------------------------------------------------

    def _on_selection_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._actions):
            self._current_index = None
            self._clear_form()
            self._set_form_enabled(False)
            return
        self._current_index = row
        self._populate_form(self._actions[row])
        self._set_form_enabled(True)

    def _populate_form(self, a: ActionDef) -> None:
        self._building_panel = True
        try:
            self._id_edit.setText(a.id)
            self._label_edit.setText(a.label)
            self._tooltip_edit.setText(a.tooltip)
            self._argv_edit.setPlainText("\n".join(a.argv))
            self._popup_combo.setCurrentText(a.popup or "never")
            self._confirm_edit.setText(a.confirm)
            self._icon_edit.setText(a.icon)
            self._hidden_check.setChecked(a.hidden)
            self._refresh_section_combo()
            idx = self._section_combo.findData(a.section)
            if idx < 0:
                idx = 0  # fall back to (none)
            self._section_combo.setCurrentIndex(idx)
            self._validate_id()
            self._refresh_preview()
        finally:
            self._building_panel = False

    def _clear_form(self) -> None:
        self._building_panel = True
        try:
            for w in (
                self._id_edit, self._label_edit, self._tooltip_edit,
                self._confirm_edit, self._icon_edit,
            ):
                w.clear()
            self._argv_edit.setPlainText("")
            self._popup_combo.setCurrentText("never")
            self._hidden_check.setChecked(False)
            self._section_combo.setCurrentIndex(0)
            self._id_warning.setText("")
            self._preview.setText("")
        finally:
            self._building_panel = False

    def _set_form_enabled(self, enabled: bool) -> None:
        for w in (
            self._id_edit, self._label_edit, self._tooltip_edit,
            self._argv_edit, self._popup_combo, self._confirm_edit,
            self._icon_edit, self._hidden_check, self._section_combo,
        ):
            w.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Per-field change handlers (write into self._actions[current])
    # ------------------------------------------------------------------

    def _current(self) -> ActionDef | None:
        if self._current_index is None:
            return None
        return self._actions[self._current_index]

    def _on_id_changed(self, text: str) -> None:
        if self._building_panel:
            return
        a = self._current()
        if a is None:
            return
        a.id = text.strip()
        self._validate_id()
        self._refresh_current_list_row()
        self._refresh_preview()

    def _on_label_changed(self, text: str) -> None:
        if self._building_panel:
            return
        a = self._current()
        if a is None:
            return
        a.label = text
        self._refresh_current_list_row()
        self._refresh_preview()

    def _on_tooltip_changed(self, text: str) -> None:
        if self._building_panel:
            return
        a = self._current()
        if a is None:
            return
        a.tooltip = text

    def _on_argv_changed(self) -> None:
        if self._building_panel:
            return
        a = self._current()
        if a is None:
            return
        raw = self._argv_edit.toPlainText()
        # Split on newlines, drop empty lines -- "one arg per line"
        # convention.  Lines preserve internal whitespace verbatim so a
        # value like ``--foo=bar baz`` survives unquoted.
        a.argv = [ln for ln in (line.rstrip("\r") for line in raw.split("\n"))
                  if ln != ""]
        self._refresh_preview()

    def _on_popup_changed(self, text: str) -> None:
        if self._building_panel:
            return
        a = self._current()
        if a is None:
            return
        a.popup = text

    def _on_confirm_changed(self, text: str) -> None:
        if self._building_panel:
            return
        a = self._current()
        if a is None:
            return
        a.confirm = text

    def _on_icon_changed(self, text: str) -> None:
        if self._building_panel:
            return
        a = self._current()
        if a is None:
            return
        a.icon = text

    def _on_hidden_changed(self, checked: bool) -> None:
        if self._building_panel:
            return
        a = self._current()
        if a is None:
            return
        a.hidden = checked
        self._refresh_current_list_row()

    def _on_section_changed(self, _idx: int) -> None:
        if self._building_panel:
            return
        a = self._current()
        if a is None:
            return
        a.section = self._section_combo.currentData() or ""

    # ------------------------------------------------------------------
    # Validation + preview
    # ------------------------------------------------------------------

    def _validate_id(self) -> None:
        a = self._current()
        if a is None:
            self._id_warning.setText("")
            return
        msg = ""
        if not a.id:
            msg = "id is required"
        elif not _ID_RE.match(a.id):
            msg = (
                "id must match [a-z_][a-z0-9_]* "
                "(starts with letter/underscore, then "
                "lowercase letters/digits/underscores)"
            )
        else:
            # Duplicate id check (current item is allowed to match
            # itself).
            for i, other in enumerate(self._actions):
                if i == self._current_index:
                    continue
                if other.id == a.id:
                    msg = f"duplicate id: another action uses {a.id!r}"
                    break
        self._id_warning.setText(msg)

    def _refresh_current_list_row(self) -> None:
        if self._current_index is None:
            return
        item = self._list.item(self._current_index)
        if item is None:
            return
        item.setText(self._format_list_label(
            self._actions[self._current_index]
        ))

    def _refresh_preview(self) -> None:
        a = self._current()
        if a is None:
            self._preview.setText("")
            return
        exe = self._tool.executable or "(no executable)"
        argv = " ".join(a.argv) if a.argv else ""
        line = exe + (" " + argv if argv else "")
        self._preview.setText(line)

    # ------------------------------------------------------------------
    # Accept
    # ------------------------------------------------------------------

    def _on_accept(self) -> None:
        # Final validation pass before committing -- block accept on
        # any structural issue, point at the offending action.
        errors: list[str] = []
        seen_ids: set[str] = set()
        for i, a in enumerate(self._actions):
            label = a.label or f"action #{i + 1}"
            if not a.id:
                errors.append(f"{label}: id is empty.")
            elif not _ID_RE.match(a.id):
                errors.append(
                    f"{label}: id {a.id!r} must match [a-z_][a-z0-9_]*."
                )
            elif a.id in seen_ids:
                errors.append(
                    f"{label}: duplicate id {a.id!r}."
                )
            else:
                seen_ids.add(a.id)
            if not a.label:
                errors.append(f"{label}: label is empty.")
            if a.popup not in ("never", "auto", "always"):
                errors.append(
                    f"{label}: popup must be never / auto / always."
                )
        if errors:
            QMessageBox.warning(
                self, "Action validation",
                "Fix these before saving:\n\n• " + "\n• ".join(errors),
            )
            return
        self.accept()

    # ------------------------------------------------------------------
    # Public result accessor
    # ------------------------------------------------------------------

    @property
    def actions(self) -> list[ActionDef]:
        """The edited actions list.  Read after ``exec()`` returns
        :data:`QDialog.DialogCode.Accepted`."""
        return self._actions
