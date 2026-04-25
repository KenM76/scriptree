"""Inline property-panel editor for a ToolDef.

Layout (left-to-right)::

    ┌────────────────────────────────────────────────────────┐
    │ Executable / name / description at top                 │
    ├───────────────┬────────────────────────────────────────┤
    │ Param list    │ Property panel                         │
    │ (with + ↑ ↓ −)│ (id, label, type, widget, required,    │
    │               │  default, description, choices,        │
    │               │  file_filter)                          │
    ├───────────────┴────────────────────────────────────────┤
    │ Argument template editor (one line per token)          │
    │ Live preview of the resulting command line             │
    ├────────────────────────────────────────────────────────┤
    │ [Save]  [Save as...]  [Test run]  [Cancel]             │
    └────────────────────────────────────────────────────────┘

All edits go through ``_push_param`` which rewrites the ``ParamDef``
and rebuilds the affected views. Edits are local until Save is
clicked — Cancel discards them. The editor returns the final
``ToolDef`` via the ``saved`` signal.
"""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.io import save_tool
from ..core.model import (
    VALID_WIDGETS,
    ParamDef,
    ParamType,
    Section,
    ToolDef,
    Widget,
    default_widget_for,
)
from .env_editor import EnvEditorDialog
from ..core.runner import RunnerError, resolve
from .widgets.param_widgets import build_widget_for


class ToolEditorView(QWidget):
    """Editor for one ToolDef. Emits ``saved`` with the new ToolDef."""

    saved = Signal(object, str)  # (ToolDef, path_str)
    cancelled = Signal()

    def __init__(
        self,
        tool: ToolDef,
        file_path: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tool = deepcopy(tool)
        self._file_path = file_path
        self._current_param_index: int | None = None
        self._building_panel = False  # guard to skip signals during rebuild

        # Read-only enforcement — disable saving when file is not writable.
        if file_path:
            from ..core.permissions import check_write_access
            access = check_write_access(file_path)
            self._read_only: bool = not access.fully_writable
        else:
            self._read_only = False

        self._build_ui()
        self._refresh_section_combo_prop()
        self._refresh_param_list()
        if self._tool.params:
            self._param_list.setCurrentRow(0)

    # --- UI construction -------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        # Top: exe / name / description.
        top = QGroupBox("Tool")
        top_form = QFormLayout(top)
        self._exe_edit = QLineEdit(self._tool.executable)
        self._exe_edit.textChanged.connect(self._on_exe_changed)
        exe_row = QHBoxLayout()
        exe_row.addWidget(self._exe_edit, stretch=1)
        exe_btn = QPushButton("Browse...")
        exe_btn.clicked.connect(self._browse_exe)
        exe_row.addWidget(exe_btn)
        exe_wrapper = QWidget()
        exe_wrapper.setLayout(exe_row)
        top_form.addRow("Executable:", exe_wrapper)

        self._name_edit = QLineEdit(self._tool.name)
        self._name_edit.textChanged.connect(self._on_name_changed)
        top_form.addRow("Name:", self._name_edit)

        self._desc_edit = QLineEdit(self._tool.description)
        self._desc_edit.textChanged.connect(self._on_desc_changed)
        top_form.addRow("Description:", self._desc_edit)

        # Tool-level environment editor. Opens a popup that edits
        # ``tool.env`` and ``tool.path_prepend`` together. These are
        # the defaults; individual configurations in the runner can
        # layer their own overrides on top.
        env_row = QHBoxLayout()
        self._env_status = QLabel(_env_summary(self._tool))
        self._env_status.setStyleSheet("color: #666;")
        env_row.addWidget(self._env_status, stretch=1)
        env_btn = QPushButton("Edit environment...")
        env_btn.setToolTip(
            "Edit environment variables and PATH prepends applied "
            "whenever this tool is run. Per-configuration overrides "
            "layer on top."
        )
        env_btn.clicked.connect(self._edit_tool_env)
        env_row.addWidget(env_btn)
        env_wrapper = QWidget()
        env_wrapper.setLayout(env_row)
        top_form.addRow("Environment:", env_wrapper)

        # Custom menus — tool.menus. Rendered as a QMenuBar above the
        # form by ToolRunnerView when the tool is run.
        menus_row = QHBoxLayout()
        self._menus_status = QLabel(_menus_summary(self._tool))
        self._menus_status.setStyleSheet("color: #666;")
        menus_row.addWidget(self._menus_status, stretch=1)
        menus_btn = QPushButton("Edit menus...")
        menus_btn.setToolTip(
            "Add, reorder, and configure the custom menu bar that "
            "appears above the form when the tool runs. Each top-level "
            "menu can hold actions, submenus, and separators."
        )
        menus_btn.clicked.connect(self._edit_tool_menus)
        menus_row.addWidget(menus_btn)
        menus_wrapper = QWidget()
        menus_wrapper.setLayout(menus_row)
        top_form.addRow("Custom menus:", menus_wrapper)

        outer.addWidget(top)

        # Middle: param list | property panel.
        middle = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(middle, stretch=1)

        # Left — param list + section toolbar.
        left_box = QGroupBox("Parameters")
        left_layout = QVBoxLayout(left_box)

        # Section management row. Empty sections list = legacy flat
        # mode. "+ Section" prompts for a name and creates one; it
        # can then be assigned to individual params via the Section
        # combobox in the property panel.
        section_row = QHBoxLayout()
        section_row.addWidget(QLabel("Sections:"))
        section_row.addStretch(1)
        for label, slot, tip in (
            ("+ §", self._add_section, "Add a new section."),
            ("✎ §", self._rename_section,
             "Rename a section (pick which one)."),
            ("− §", self._remove_section,
             "Delete a section (its params fall back to 'no section')."),
            ("↑", self._move_section_up,
             "Move the selected section up."),
            ("↓", self._move_section_down,
             "Move the selected section down."),
        ):
            b = QPushButton(label)
            b.setFixedWidth(36)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            section_row.addWidget(b)
        left_layout.addLayout(section_row)

        # Section list with per-section layout indicators.
        self._section_list = QListWidget()
        self._section_list.setMaximumHeight(90)
        self._section_list.setToolTip(
            "Declared sections. The icon shows layout mode:\n"
            "  [▤] = collapsible section\n"
            "  [⊞] = tab page\n"
            "Consecutive tab sections are grouped into one tab widget."
        )
        left_layout.addWidget(self._section_list)
        self._refresh_section_list()

        # Layout toggle button — switches selected section between
        # collapse and tab mode.
        layout_row = QHBoxLayout()
        self._toggle_layout_btn = QPushButton("Toggle layout")
        self._toggle_layout_btn.setToolTip(
            "Switch the selected section between collapsible and tab mode."
        )
        self._toggle_layout_btn.clicked.connect(self._toggle_section_layout)
        layout_row.addWidget(self._toggle_layout_btn)
        self._all_collapse_btn = QPushButton("All ▤")
        self._all_collapse_btn.setToolTip("Set all sections to collapsible.")
        self._all_collapse_btn.setFixedWidth(50)
        self._all_collapse_btn.clicked.connect(self._set_all_collapse)
        layout_row.addWidget(self._all_collapse_btn)
        self._all_tabs_btn = QPushButton("All ⊞")
        self._all_tabs_btn.setToolTip("Set all sections to tab mode.")
        self._all_tabs_btn.setFixedWidth(50)
        self._all_tabs_btn.clicked.connect(self._set_all_tabs)
        layout_row.addWidget(self._all_tabs_btn)
        layout_row.addStretch(1)
        left_layout.addLayout(layout_row)

        self._param_list = QListWidget()
        self._param_list.currentRowChanged.connect(self._on_param_selected)
        left_layout.addWidget(self._param_list, stretch=1)
        btn_row = QHBoxLayout()
        for label, slot in (
            ("+", self._add_param),
            ("−", self._remove_param),
            ("↑", self._move_param_up),
            ("↓", self._move_param_down),
        ):
            b = QPushButton(label)
            b.setFixedWidth(32)
            b.clicked.connect(slot)
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        left_layout.addLayout(btn_row)
        middle.addWidget(left_box)

        # Right — property panel.
        right_box = QGroupBox("Property panel")
        self._prop_layout = QFormLayout(right_box)
        self._prop_id = QLineEdit()
        self._prop_id.editingFinished.connect(self._on_prop_id_changed)
        self._prop_label = QLineEdit()
        self._prop_label.textChanged.connect(self._on_prop_label_changed)
        self._prop_desc = QLineEdit()
        self._prop_desc.textChanged.connect(self._on_prop_desc_changed)
        self._prop_type = QComboBox()
        for t in ParamType:
            self._prop_type.addItem(t.value, t)
        self._prop_type.currentIndexChanged.connect(self._on_prop_type_changed)
        self._prop_widget = QComboBox()
        self._prop_widget.currentIndexChanged.connect(
            self._on_prop_widget_changed
        )
        self._prop_required = QCheckBox()
        self._prop_required.toggled.connect(self._on_prop_required_changed)
        self._prop_no_persist = QCheckBox()
        self._prop_no_persist.setToolTip(
            "When checked, the parameter's value is never written into "
            "any saved configuration. Useful for passwords, tokens, and "
            "other sensitive or scratch values. The user's most recent "
            "entry is kept during the session but is lost when the tool "
            "is reloaded (the widget returns to the default)."
        )
        self._prop_no_persist.toggled.connect(
            self._on_prop_no_persist_changed
        )
        self._prop_no_split = QCheckBox()
        self._prop_no_split.setToolTip(
            "Opt out of the auto-split rule for this parameter. By "
            "default, when a string param's placeholder is the entire "
            "template token (e.g. argument_template=[\"{flags}\"]) "
            "and the value contains whitespace, ScripTree splits the "
            "value into multiple argv tokens — perfect for typing "
            "repeatable flags. Check this box to disable that for "
            "this param: the value will always emit as a single argv "
            "token, even with embedded spaces. Only meaningful for "
            "string-typed params; ignored otherwise."
        )
        self._prop_no_split.toggled.connect(
            self._on_prop_no_split_changed
        )
        self._prop_default = QLineEdit()
        self._prop_default.textChanged.connect(self._on_prop_default_changed)
        self._prop_choices = QLineEdit()
        self._prop_choices.setPlaceholderText(
            "fast=Fast mode,slow=Slow mode,auto  "
            "(value or value=label, comma-separated)"
        )
        self._prop_choices.setToolTip(
            "Dropdown choices. Each entry is either a bare value "
            "(used both in argv and as the visible label) or "
            "<code>value=label</code> to show a descriptive label "
            "while sending the value to the command."
        )
        self._prop_choices.textChanged.connect(self._on_prop_choices_changed)
        self._prop_filter = QLineEdit()
        self._prop_filter.setPlaceholderText("Text (*.txt);;All (*)")
        self._prop_filter.textChanged.connect(self._on_prop_filter_changed)
        self._prop_section = QComboBox()
        self._prop_section.setToolTip(
            "Which section this param belongs to. The list tracks the "
            "tool's declared sections — use the +§/✎§/−§ buttons above "
            "the param list to manage them."
        )
        self._prop_section.currentIndexChanged.connect(
            self._on_prop_section_changed
        )

        self._prop_layout.addRow("ID:", self._prop_id)
        self._prop_layout.addRow("Label:", self._prop_label)
        self._prop_layout.addRow("Description:", self._prop_desc)
        self._prop_layout.addRow("Type:", self._prop_type)
        self._prop_layout.addRow("Widget:", self._prop_widget)
        self._prop_layout.addRow("Required:", self._prop_required)
        self._prop_layout.addRow("Do not save value:", self._prop_no_persist)
        self._prop_layout.addRow("Do not auto-split:", self._prop_no_split)
        self._prop_layout.addRow("Default:", self._prop_default)
        self._prop_layout.addRow("Choices:", self._prop_choices)
        self._prop_layout.addRow("File filter:", self._prop_filter)
        self._prop_layout.addRow("Section:", self._prop_section)
        middle.addWidget(right_box)
        middle.setStretchFactor(0, 1)
        middle.setStretchFactor(1, 2)

        # Argument template + live preview + form preview.
        #
        # The lower half of the editor is a horizontal splitter with
        # the template editor on the left and a live form preview on
        # the right. The preview renders exactly what a ``ToolRunnerView``
        # would show at runtime for the tool *as currently edited*,
        # with all input widgets disabled so the user can't type into
        # them by mistake. Every param mutation path calls
        # ``_rebuild_form_preview`` to keep it in sync.
        lower_split = QSplitter(Qt.Orientation.Horizontal)

        tmpl_box = QGroupBox("Argument template")
        tmpl_outer = QVBoxLayout(tmpl_box)

        # --- Tab widget: Text vs. Visual template editing --------
        self._tmpl_tabs = QTabWidget()
        self._tmpl_syncing = False  # guard for tab-switch syncing
        tmpl_outer.addWidget(self._tmpl_tabs)

        # -- Text tab (raw, one entry per line) --
        text_tab = QWidget()
        text_layout = QVBoxLayout(text_tab)
        text_layout.setContentsMargins(4, 4, 4, 4)
        tmpl_help = QLabel(
            "<i>One argv entry per line. Use <code>{param_id}</code> for "
            "substitution or <code>{param_id?--flag}</code> for conditional "
            "flags. Put <b>multiple tokens separated by spaces</b> on one "
            "line to form a group — all tokens emit together or all drop "
            "together when any substitution is empty.</i>"
        )
        tmpl_help.setWordWrap(True)
        text_layout.addWidget(tmpl_help)
        self._tmpl_edit = QPlainTextEdit()
        mono = QFont()
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setFamily("Consolas")
        self._tmpl_edit.setFont(mono)
        self._tmpl_edit.setPlainText(
            _template_to_text(self._tool.argument_template)
        )
        self._tmpl_edit.textChanged.connect(self._on_template_changed)
        text_layout.addWidget(self._tmpl_edit)
        self._tmpl_tabs.addTab(text_tab, "Text")

        # -- Visual tab (structured list with per-entry editing) --
        visual_tab = QWidget()
        vis_layout = QVBoxLayout(visual_tab)
        vis_layout.setContentsMargins(4, 4, 4, 4)
        vis_help = QLabel(
            "<i>Each row is one argv entry. A <b>group</b> (multiple "
            "tokens separated by spaces) emits all-or-nothing. Use "
            "the buttons to add, remove, or reorder entries.</i>"
        )
        vis_help.setWordWrap(True)
        vis_layout.addWidget(vis_help)

        self._tmpl_list = QListWidget()
        self._tmpl_list.setDragDropMode(
            QListWidget.DragDropMode.InternalMove
        )
        self._tmpl_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._tmpl_list.model().rowsMoved.connect(
            self._on_visual_template_reordered
        )
        vis_layout.addWidget(self._tmpl_list)

        vis_btn_row = QHBoxLayout()
        btn_add_token = QPushButton("+ Token")
        btn_add_token.setToolTip(
            "Add a single argv token, e.g. {param_id} or --flag"
        )
        btn_add_token.clicked.connect(self._vis_add_token)
        vis_btn_row.addWidget(btn_add_token)

        btn_add_group = QPushButton("+ Group")
        btn_add_group.setToolTip(
            "Add a token group (multiple tokens that emit together "
            "or drop together), e.g. --flag {param_id}"
        )
        btn_add_group.clicked.connect(self._vis_add_group)
        vis_btn_row.addWidget(btn_add_group)

        btn_edit = QPushButton("Edit")
        btn_edit.setToolTip("Edit the selected entry")
        btn_edit.clicked.connect(self._vis_edit_entry)
        vis_btn_row.addWidget(btn_edit)

        btn_remove = QPushButton("−")
        btn_remove.setToolTip("Remove the selected entry")
        btn_remove.clicked.connect(self._vis_remove_entry)
        vis_btn_row.addWidget(btn_remove)

        vis_btn_row.addStretch(1)
        vis_layout.addLayout(vis_btn_row)
        self._tmpl_tabs.addTab(visual_tab, "Visual")

        # Sync between tabs when the user switches.
        self._tmpl_tabs.currentChanged.connect(self._on_tmpl_tab_changed)

        # --- Live preview (shared, always visible) ---------------
        self._preview = QLineEdit()
        self._preview.setReadOnly(True)
        tmpl_outer.addWidget(QLabel("Live preview:"))
        tmpl_outer.addWidget(self._preview)
        lower_split.addWidget(tmpl_box)

        # Populate the visual list from the initial template.
        self._sync_visual_from_model()

        # Form preview panel.
        preview_box = QGroupBox("Form preview (what the user will see)")
        preview_outer = QVBoxLayout(preview_box)
        preview_outer.setContentsMargins(6, 6, 6, 6)
        self._form_preview_container = QWidget()
        self._form_preview_layout = QVBoxLayout(self._form_preview_container)
        self._form_preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_scroll = QScrollArea()
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setWidget(self._form_preview_container)
        preview_outer.addWidget(preview_scroll)
        lower_split.addWidget(preview_box)
        lower_split.setStretchFactor(0, 1)
        lower_split.setStretchFactor(1, 1)
        outer.addWidget(lower_split)

        # Buttons.
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.clicked.connect(self._on_cancel)
        self._btn_save = QPushButton("Save")
        self._btn_save.setDefault(True)
        self._btn_save.clicked.connect(self._on_save)
        self._btn_save_as = QPushButton("Save as...")
        self._btn_save_as.clicked.connect(self._on_save_as)
        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_save_as)
        btn_row.addWidget(self._btn_save)
        outer.addLayout(btn_row)

        # Disable save buttons for read-only files.
        if self._read_only:
            self._btn_save.setEnabled(False)
            self._btn_save.setToolTip("File is read-only.")
            self._btn_save_as.setEnabled(False)
            self._btn_save_as.setToolTip("File is read-only.")

        self._update_preview()

    # --- top fields ------------------------------------------------------

    def _browse_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select executable", self._exe_edit.text(),
            "Executables (*.exe *.bat *.cmd *.py *.sh);;All files (*)",
        )
        if path:
            self._exe_edit.setText(path)

    def _on_exe_changed(self, text: str) -> None:
        self._tool.executable = text
        self._update_preview()

    def _on_name_changed(self, text: str) -> None:
        self._tool.name = text

    def _on_desc_changed(self, text: str) -> None:
        self._tool.description = text

    # --- tool-level environment -----------------------------------------

    def _edit_tool_env(self) -> None:
        """Open the env-editor popup and write results back to the tool.

        Edits are held on the in-memory ``ToolDef`` until the user
        clicks Save in the main editor — same lifecycle as every
        other field in this dialog. The inline status label below the
        button refreshes to summarize the new state.
        """
        dlg = EnvEditorDialog(
            self._tool.env,
            self._tool.path_prepend,
            title=f"Environment — {self._tool.name or 'tool'}",
            parent=self,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self._tool.env = dlg.result_env()
        self._tool.path_prepend = dlg.result_paths()
        self._env_status.setText(_env_summary(self._tool))

    def _edit_tool_menus(self) -> None:
        """Open the custom-menus editor and write results back to the tool.

        Same lifecycle as ``_edit_tool_env`` — edits sit on the
        in-memory ``ToolDef.menus`` until the main Save button writes
        the .scriptree file.
        """
        from .menu_editor import MenuEditorDialog

        dlg = MenuEditorDialog(self._tool.menus, parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self._tool.menus = dlg.menus
        self._menus_status.setText(_menus_summary(self._tool))

    # --- param list ------------------------------------------------------

    def _refresh_param_list(self) -> None:
        self._param_list.clear()
        has_sections = bool(self._tool.sections)
        for p in self._tool.params:
            if has_sections:
                sec = p.section or "(none)"
                text = f"{p.label}  ({p.id})  \u2014 {sec}"
            else:
                text = f"{p.label}  ({p.id})"
            self._param_list.addItem(QListWidgetItem(text))

    def _add_param(self) -> None:
        base_id = "param"
        n = 1
        used = {p.id for p in self._tool.params}
        while f"{base_id}{n}" in used:
            n += 1
        new_param = ParamDef(id=f"{base_id}{n}")
        self._tool.params.append(new_param)
        self._refresh_param_list()
        self._param_list.setCurrentRow(len(self._tool.params) - 1)
        self._update_preview()

    def _remove_param(self) -> None:
        idx = self._current_param_index
        if idx is None:
            return
        del self._tool.params[idx]
        self._refresh_param_list()
        if self._tool.params:
            self._param_list.setCurrentRow(min(idx, len(self._tool.params) - 1))
        else:
            self._current_param_index = None
            self._clear_prop_panel()
        self._update_preview()

    def _move_param_up(self) -> None:
        idx = self._current_param_index
        if idx is None or idx == 0:
            return
        self._tool.params[idx - 1], self._tool.params[idx] = (
            self._tool.params[idx],
            self._tool.params[idx - 1],
        )
        self._refresh_param_list()
        self._param_list.setCurrentRow(idx - 1)
        self._update_preview()

    def _move_param_down(self) -> None:
        idx = self._current_param_index
        if idx is None or idx >= len(self._tool.params) - 1:
            return
        self._tool.params[idx + 1], self._tool.params[idx] = (
            self._tool.params[idx],
            self._tool.params[idx + 1],
        )
        self._refresh_param_list()
        self._param_list.setCurrentRow(idx + 1)
        self._update_preview()

    def _on_param_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._tool.params):
            self._current_param_index = None
            self._clear_prop_panel()
            return
        self._current_param_index = row
        self._load_param_into_panel(self._tool.params[row])

    # --- property panel --------------------------------------------------

    def _clear_prop_panel(self) -> None:
        self._building_panel = True
        try:
            self._prop_id.setText("")
            self._prop_label.setText("")
            self._prop_desc.setText("")
            self._prop_type.setCurrentIndex(0)
            self._prop_required.setChecked(False)
            self._prop_no_persist.setChecked(False)
            self._prop_no_split.setChecked(False)
            self._prop_default.setText("")
            self._prop_choices.setText("")
            self._prop_filter.setText("")
            self._populate_widget_combo(ParamType.STRING)
            if self._prop_section.count() > 0:
                self._prop_section.setCurrentIndex(0)
        finally:
            self._building_panel = False

    def _load_param_into_panel(self, param: ParamDef) -> None:
        self._building_panel = True
        try:
            self._prop_id.setText(param.id)
            self._prop_label.setText(param.label)
            self._prop_desc.setText(param.description)
            type_idx = self._prop_type.findData(param.type)
            if type_idx >= 0:
                self._prop_type.setCurrentIndex(type_idx)
            self._populate_widget_combo(param.type)
            widget_idx = self._prop_widget.findData(param.widget)
            if widget_idx >= 0:
                self._prop_widget.setCurrentIndex(widget_idx)
            self._prop_required.setChecked(param.required)
            self._prop_no_persist.setChecked(param.no_persist)
            self._prop_no_split.setChecked(param.no_split)
            self._prop_default.setText(
                "" if param.default is None else str(param.default)
            )
            self._prop_choices.setText(_format_choices(param))
            self._prop_filter.setText(param.file_filter)
            # Section combo — index 0 is "(no section)" with data "",
            # and further items mirror tool.sections in order.
            sec_idx = self._prop_section.findData(param.section or "")
            if sec_idx < 0:
                sec_idx = 0
            self._prop_section.setCurrentIndex(sec_idx)
        finally:
            self._building_panel = False

    def _populate_widget_combo(self, ptype: ParamType) -> None:
        self._prop_widget.clear()
        for w in VALID_WIDGETS[ptype]:
            self._prop_widget.addItem(w.value, w)

    def _current_param(self) -> ParamDef | None:
        if self._current_param_index is None:
            return None
        return self._tool.params[self._current_param_index]

    def _on_prop_id_changed(self) -> None:
        param = self._current_param()
        if param is None or self._building_panel:
            return
        new_id = self._prop_id.text().strip()
        if new_id == param.id:
            return
        if not new_id.isidentifier():
            QMessageBox.warning(
                self, "Invalid id",
                f"{new_id!r} is not a valid identifier.",
            )
            self._prop_id.setText(param.id)
            return
        if any(p.id == new_id for p in self._tool.params if p is not param):
            QMessageBox.warning(self, "Duplicate id", f"Id {new_id!r} is already used.")
            self._prop_id.setText(param.id)
            return
        param.id = new_id
        self._refresh_param_list_keep_selection()
        self._update_preview()

    def _on_prop_label_changed(self, text: str) -> None:
        if self._building_panel:
            return
        param = self._current_param()
        if param is None:
            return
        param.label = text
        self._refresh_param_list_keep_selection()
        self._update_preview()

    def _on_prop_desc_changed(self, text: str) -> None:
        if self._building_panel:
            return
        param = self._current_param()
        if param:
            param.description = text
            self._update_preview()

    def _on_prop_type_changed(self, _idx: int) -> None:
        if self._building_panel:
            return
        param = self._current_param()
        if param is None:
            return
        new_type: ParamType = self._prop_type.currentData()
        param.type = new_type
        param.widget = default_widget_for(new_type)
        # Reload the panel so the widget dropdown updates.
        self._load_param_into_panel(param)
        self._update_preview()

    def _on_prop_widget_changed(self, _idx: int) -> None:
        if self._building_panel:
            return
        param = self._current_param()
        if param is None:
            return
        new_widget: Widget | None = self._prop_widget.currentData()
        if new_widget is not None:
            param.widget = new_widget
            self._update_preview()

    def _on_prop_required_changed(self, checked: bool) -> None:
        if self._building_panel:
            return
        param = self._current_param()
        if param:
            param.required = checked
            self._update_preview()

    def _on_prop_no_persist_changed(self, checked: bool) -> None:
        if self._building_panel:
            return
        param = self._current_param()
        if param:
            param.no_persist = bool(checked)
            self._update_preview()

    def _on_prop_no_split_changed(self, checked: bool) -> None:
        if self._building_panel:
            return
        param = self._current_param()
        if param:
            param.no_split = bool(checked)
            self._update_preview()

    def _on_prop_default_changed(self, text: str) -> None:
        if self._building_panel:
            return
        param = self._current_param()
        if param:
            param.default = text
            self._update_preview()

    def _on_prop_choices_changed(self, text: str) -> None:
        if self._building_panel:
            return
        param = self._current_param()
        if param:
            values, labels = _parse_choices(text)
            param.choices = values
            param.choice_labels = labels
            self._update_preview()

    def _on_prop_filter_changed(self, text: str) -> None:
        if self._building_panel:
            return
        param = self._current_param()
        if param:
            param.file_filter = text

    def _on_prop_section_changed(self, idx: int) -> None:
        if self._building_panel:
            return
        param = self._current_param()
        if param is None:
            return
        new_section = self._prop_section.itemData(idx) or ""
        if new_section == param.section:
            return
        param.section = new_section
        self._refresh_param_list_keep_selection()
        self._update_preview()

    def _refresh_section_list(self) -> None:
        """Rebuild the section list widget from the model."""
        self._section_list.clear()
        for sec in self._tool.sections:
            icon = "⊞" if sec.layout == "tab" else "▤"
            self._section_list.addItem(f"[{icon}] {sec.name}")

    def _toggle_section_layout(self) -> None:
        """Toggle the selected section between collapse and tab."""
        row = self._section_list.currentRow()
        if row < 0 or row >= len(self._tool.sections):
            return
        sec = self._tool.sections[row]
        sec.layout = "collapse" if sec.layout == "tab" else "tab"
        self._refresh_section_list()
        self._section_list.setCurrentRow(row)
        self._update_preview()

    def _set_all_collapse(self) -> None:
        for sec in self._tool.sections:
            sec.layout = "collapse"
        self._refresh_section_list()
        self._update_preview()

    def _set_all_tabs(self) -> None:
        for sec in self._tool.sections:
            sec.layout = "tab"
        self._refresh_section_list()
        self._update_preview()

    # --- section management ---------------------------------------------

    def _refresh_section_combo_prop(self) -> None:
        """Refill the property panel's Section combo from tool.sections."""
        self._building_panel = True
        try:
            self._prop_section.clear()
            self._prop_section.addItem("(no section)", "")
            for sec in self._tool.sections:
                self._prop_section.addItem(sec.name, sec.name)
        finally:
            self._building_panel = False

    def _add_section(self) -> None:
        name, ok = QInputDialog.getText(
            self, "New section", "Section name:"
        )
        name = name.strip() if ok else ""
        if not name:
            return
        if any(s.name == name for s in self._tool.sections):
            QMessageBox.warning(
                self, "Duplicate section",
                f"A section named {name!r} already exists.",
            )
            return
        self._tool.sections.append(Section(name=name))
        self._refresh_section_combo_prop()
        self._refresh_section_list()
        self._refresh_param_list_keep_selection()
        # Push the currently-selected param into the new section as a
        # convenience — one less click for the common case.
        param = self._current_param()
        if param is not None and not param.section:
            param.section = name
            # Update the panel combo so it reflects the new membership.
            if self._current_param_index is not None:
                self._load_param_into_panel(param)
        self._update_preview()

    def _rename_section(self) -> None:
        if not self._tool.sections:
            QMessageBox.information(
                self, "No sections", "This tool has no sections yet."
            )
            return
        names = [s.name for s in self._tool.sections]
        old, ok = QInputDialog.getItem(
            self, "Rename section", "Which section:",
            names, 0, False,
        )
        if not ok or not old:
            return
        new, ok = QInputDialog.getText(
            self, "Rename section", f"New name for {old!r}:",
            text=old,
        )
        new = new.strip() if ok else ""
        if not new or new == old:
            return
        if any(s.name == new for s in self._tool.sections):
            QMessageBox.warning(
                self, "Duplicate section",
                f"A section named {new!r} already exists.",
            )
            return
        for sec in self._tool.sections:
            if sec.name == old:
                sec.name = new
                break
        # Re-point any param that was in the old section.
        for p in self._tool.params:
            if p.section == old:
                p.section = new
        self._refresh_section_combo_prop()
        self._refresh_section_list()
        self._refresh_param_list_keep_selection()
        if self._current_param_index is not None:
            self._load_param_into_panel(
                self._tool.params[self._current_param_index]
            )
        self._update_preview()

    def _remove_section(self) -> None:
        if not self._tool.sections:
            QMessageBox.information(
                self, "No sections", "This tool has no sections yet."
            )
            return
        names = [s.name for s in self._tool.sections]
        target, ok = QInputDialog.getItem(
            self, "Remove section", "Delete which section:",
            names, 0, False,
        )
        if not ok or not target:
            return
        self._tool.sections = [
            s for s in self._tool.sections if s.name != target
        ]
        # Orphan the params that were in the removed section — they
        # fall back to "no section" rather than being deleted.
        for p in self._tool.params:
            if p.section == target:
                p.section = ""
        self._refresh_section_combo_prop()
        self._refresh_section_list()
        self._refresh_param_list_keep_selection()
        if self._current_param_index is not None:
            self._load_param_into_panel(
                self._tool.params[self._current_param_index]
            )
        self._update_preview()

    def _move_section_up(self) -> None:
        self._move_section_by(-1)

    def _move_section_down(self) -> None:
        self._move_section_by(+1)

    def _move_section_by(self, delta: int) -> None:
        """Reorder the currently-selected section in ``tool.sections``.

        The section list drives both the visible display order in the
        runner and the collapsed/tab layout groupings, so swapping two
        entries here is enough — no need to renumber params (their
        membership is keyed by section name, not index).
        """
        if not self._tool.sections:
            return
        row = self._section_list.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "No section selected",
                "Select a section in the list first, then use ↑ / ↓ to "
                "reorder.",
            )
            return
        new_row = row + delta
        if not (0 <= new_row < len(self._tool.sections)):
            return
        secs = self._tool.sections
        secs[row], secs[new_row] = secs[new_row], secs[row]
        self._refresh_section_list()
        self._refresh_param_list_keep_selection()
        self._section_list.setCurrentRow(new_row)
        self._update_preview()

    def _refresh_param_list_keep_selection(self) -> None:
        idx = self._current_param_index
        self._refresh_param_list()
        if idx is not None:
            self._param_list.setCurrentRow(idx)

    # --- template + preview ---------------------------------------------

    def _on_template_changed(self) -> None:
        if self._tmpl_syncing:
            return
        self._tool.argument_template = _text_to_template(
            self._tmpl_edit.toPlainText()
        )
        self._update_preview()

    # --- visual template tab helpers -----------------------------------

    def _sync_visual_from_model(self) -> None:
        """Rebuild the visual list widget from the model."""
        self._tmpl_list.clear()
        for entry in self._tool.argument_template:
            self._tmpl_list.addItem(self._visual_label(entry))

    def _sync_text_from_model(self) -> None:
        """Rebuild the text tab from the model."""
        self._tmpl_syncing = True
        try:
            self._tmpl_edit.setPlainText(
                _template_to_text(self._tool.argument_template)
            )
        finally:
            self._tmpl_syncing = False

    @staticmethod
    def _visual_label(entry) -> str:
        """Return a display string for one template entry."""
        if isinstance(entry, list):
            return "[group]  " + " ".join(entry)
        return entry

    def _on_tmpl_tab_changed(self, index: int) -> None:
        """Sync data between text and visual tabs on switch."""
        if index == 0:
            # Switching to Text — rebuild text from model.
            self._sync_text_from_model()
        else:
            # Switching to Visual — rebuild list from model.
            self._sync_visual_from_model()

    def _visual_to_model(self) -> None:
        """Read the visual list back into the model and refresh."""
        entries: list = []
        for i in range(self._tmpl_list.count()):
            text = self._tmpl_list.item(i).text()
            if text.startswith("[group]  "):
                raw = text[len("[group]  "):]
                tokens = raw.split()
                entries.append(tokens if len(tokens) > 1 else tokens[0] if tokens else "")
            else:
                entries.append(text)
        self._tool.argument_template = entries
        self._update_preview()

    def _on_visual_template_reordered(self) -> None:
        self._visual_to_model()

    def _vis_add_token(self) -> None:
        text, ok = QInputDialog.getText(
            self, "Add token",
            "Argv token (e.g. {param_id} or --verbose or a literal):",
        )
        if not ok or not text.strip():
            return
        self._tmpl_list.addItem(text.strip())
        self._visual_to_model()

    def _vis_add_group(self) -> None:
        text, ok = QInputDialog.getText(
            self, "Add group",
            "Space-separated tokens (all emit together or all drop).\n"
            "Example: --flag {param_id}",
        )
        if not ok or not text.strip():
            return
        tokens = text.strip().split()
        if len(tokens) < 2:
            # Single token — add as plain, not group
            self._tmpl_list.addItem(tokens[0])
        else:
            self._tmpl_list.addItem("[group]  " + " ".join(tokens))
        self._visual_to_model()

    def _vis_edit_entry(self) -> None:
        item = self._tmpl_list.currentItem()
        if item is None:
            return
        text = item.text()
        is_group = text.startswith("[group]  ")
        raw = text[len("[group]  "):] if is_group else text
        label = "Group tokens:" if is_group else "Token:"
        new_text, ok = QInputDialog.getText(
            self, "Edit entry", label, QLineEdit.EchoMode.Normal, raw,
        )
        if not ok or not new_text.strip():
            return
        tokens = new_text.strip().split()
        if len(tokens) > 1:
            item.setText("[group]  " + " ".join(tokens))
        else:
            item.setText(tokens[0])
        self._visual_to_model()

    def _vis_remove_entry(self) -> None:
        row = self._tmpl_list.currentRow()
        if row < 0:
            return
        self._tmpl_list.takeItem(row)
        self._visual_to_model()

    def _update_preview(self) -> None:
        values = {p.id: p.default for p in self._tool.params}
        try:
            cmd = resolve(self._tool, values, ignore_required=True)
            self._preview.setText(cmd.display())
        except RunnerError as e:
            self._preview.setText(f"[error: {e}]")
        self._rebuild_form_preview()

    def _rebuild_form_preview(self) -> None:
        """Re-render the form preview panel from the current ToolDef state.

        Mirrors the runner's mixed-layout logic: collapse sections
        render as ``QGroupBox``, consecutive tab sections are grouped
        into a single ``QTabWidget``, and section-less tools get a
        flat ``QFormLayout``.  Rows aren't drag-reorderable (preview
        only).
        """
        # Clear all children from the VBoxLayout.
        while self._form_preview_layout.count() > 0:
            item = self._form_preview_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not self._tool.params:
            placeholder = QLabel(
                "<i>No parameters yet. Add one with <b>+</b> in the "
                "list on the left.</i>"
            )
            placeholder.setWordWrap(True)
            self._form_preview_layout.addWidget(placeholder)
            return

        groups = self._tool.grouped_params()
        if len(groups) == 1 and groups[0][0] is None:
            # No sections declared — flat form, original behavior.
            flat = QWidget()
            flat_layout = QFormLayout(flat)
            flat_layout.setFieldGrowthPolicy(
                QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
            )
            flat_layout.setContentsMargins(0, 0, 0, 0)
            for param in groups[0][1]:
                self._add_preview_row(param, flat_layout)
            self._form_preview_layout.addWidget(flat)
            return

        # Mixed layout: group consecutive tab sections into QTabWidgets.
        current_tab_widget: QTabWidget | None = None

        def _flush_tabs() -> None:
            nonlocal current_tab_widget
            if current_tab_widget is not None:
                self._form_preview_layout.addWidget(current_tab_widget)
                current_tab_widget = None

        def _make_form(params: list) -> QWidget:
            w = QWidget()
            form = QFormLayout(w)
            form.setFieldGrowthPolicy(
                QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
            )
            if not params:
                form.addRow(QLabel("<i>(empty section)</i>"))
            else:
                for param in params:
                    self._add_preview_row(param, form)
            return w

        for section, params in groups:
            assert section is not None
            is_tab = getattr(section, "layout", "collapse") == "tab"

            if is_tab:
                if current_tab_widget is None:
                    current_tab_widget = QTabWidget()
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setWidget(_make_form(params))
                scroll.setFrameShape(QScrollArea.Shape.NoFrame)
                current_tab_widget.addTab(
                    scroll, section.name or "(unnamed)"
                )
            else:
                _flush_tabs()
                box = QGroupBox(section.name or "(unnamed)")
                box.setCheckable(True)
                box.setChecked(not section.collapsed)
                box_layout = QVBoxLayout(box)
                box_layout.setContentsMargins(8, 6, 8, 6)
                form_widget = _make_form(params)
                box_layout.addWidget(form_widget)
                form_widget.setVisible(not section.collapsed)
                box.toggled.connect(form_widget.setVisible)
                self._form_preview_layout.addWidget(box)

        _flush_tabs()
        self._form_preview_layout.addStretch(1)

    def _add_preview_row(self, param: ParamDef, layout: QFormLayout) -> None:
        """Build one disabled preview widget + label row and append it."""
        try:
            widget = build_widget_for(param)
        except Exception as e:  # noqa: BLE001 — keep editor usable on bad state
            widget = QLabel(f"<i>[preview error: {e}]</i>")
        widget.setEnabled(False)
        label_text = param.label + (" *" if param.required else "")
        label = QLabel(label_text)
        if param.description:
            label.setToolTip(param.description)
            widget.setToolTip(param.description)
        layout.addRow(label, widget)

    # --- save / cancel --------------------------------------------------

    def _on_save(self) -> None:
        if self._read_only and self._file_path is not None:
            QMessageBox.warning(
                self, "Read-only",
                "This file is read-only and cannot be saved.",
            )
            return
        errors = self._tool.validate()
        if errors:
            QMessageBox.warning(self, "Validation errors", "\n".join(errors))
            return
        path = self._file_path
        if path is None:
            path = self._ask_save_path()
            if path is None:
                return
        self._maybe_relativize_paths(path)
        save_tool(self._tool, path)
        self._file_path = path
        self.saved.emit(self._tool, path)

    def _on_save_as(self) -> None:
        if self._read_only:
            QMessageBox.warning(
                self, "Read-only",
                "This file is read-only and cannot be saved.",
            )
            return
        path = self._ask_save_path()
        if path is None:
            return
        errors = self._tool.validate()
        if errors:
            QMessageBox.warning(self, "Validation errors", "\n".join(errors))
            return
        self._maybe_relativize_paths(path)
        save_tool(self._tool, path)
        self._file_path = path
        self.saved.emit(self._tool, path)

    def _maybe_relativize_paths(self, save_path: str) -> None:
        """Convert ``executable`` and ``working_directory`` to paths
        relative to ``save_path``'s directory when they live inside
        that directory tree.

        Makes the containing folder portable — moving it preserves
        the link to the sibling executable/helper files. Paths that
        point outside the save folder are left absolute (they're
        almost certainly system tools or shared resources). Bare
        names like ``python`` or empty strings are untouched.

        Mirrors the behavior of ``tree_view._maybe_relative`` for
        tree leaf paths.
        """
        save_dir = Path(save_path).resolve().parent

        def _relativize(raw: str) -> str:
            if not raw:
                return raw
            p = Path(raw)
            if not p.is_absolute():
                # Already relative — leave it alone (user's choice).
                return raw
            try:
                target = p.resolve()
            except (OSError, ValueError):
                return raw
            try:
                rel = os.path.relpath(target, save_dir)
            except ValueError:
                # Different drives on Windows — can't relativize.
                return raw
            rel_posix = rel.replace("\\", "/")
            # Only rewrite when the target is INSIDE save_dir's tree.
            # If it's outside, relpath produces ``../..`` chains that
            # are usually worse than just keeping absolute.
            if rel_posix.startswith("../"):
                return raw
            if not rel_posix.startswith("./"):
                rel_posix = "./" + rel_posix
            return rel_posix

        self._tool.executable = _relativize(self._tool.executable)
        if self._tool.working_directory:
            self._tool.working_directory = _relativize(
                self._tool.working_directory
            )

    def _ask_save_path(self) -> str | None:
        default_name = (self._tool.name or "tool") + ".scriptree"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save .scriptree", default_name,
            "ScripTree files (*.scriptree);;All files (*)",
        )
        return path or None

    def _on_cancel(self) -> None:
        self.cancelled.emit()


# --- environment summary ---------------------------------------------------

def _env_summary(tool: ToolDef) -> str:
    """Return a short status string describing tool env overrides.

    Used by the inline status label next to the ``Edit environment...``
    button so the user can see at a glance whether anything is set.
    """
    n_env = len(tool.env or {})
    n_paths = len(tool.path_prepend or [])
    if not n_env and not n_paths:
        return "<i>no overrides</i>"
    parts = []
    if n_env:
        parts.append(f"{n_env} var{'s' if n_env != 1 else ''}")
    if n_paths:
        parts.append(f"{n_paths} path{'s' if n_paths != 1 else ''}")
    return ", ".join(parts)


def _menus_summary(tool: ToolDef) -> str:
    """Short status for the ``Edit menus...`` inline label.

    Reports unique top-level menu names and total item count so the
    user can tell at a glance whether custom menus are defined.
    """
    if not tool.menus:
        return "<i>none</i>"
    # Preserve first-occurrence order of menu names.
    names: list[str] = []
    for m in tool.menus:
        key = m.menu or "Tools"
        if key not in names:
            names.append(key)
    n_items = len(tool.menus)
    return f"{', '.join(names)} — {n_items} item{'s' if n_items != 1 else ''}"


# --- choices text round-trip helpers ---------------------------------------

def _parse_choices(text: str) -> tuple[list[str], list[str]]:
    """Parse the Choices line into parallel value and label lists.

    Accepted format::

        value, value=label, value2, value2=label2, ...

    An entry without ``=`` is a bare value with no descriptive label
    (label slot stays empty string so ``label_for_choice`` falls back
    to the value). Whitespace around values and labels is trimmed.
    Empty entries are dropped silently.
    """
    values: list[str] = []
    labels: list[str] = []
    for raw in text.split(","):
        entry = raw.strip()
        if not entry:
            continue
        if "=" in entry:
            v, lbl = entry.split("=", 1)
            values.append(v.strip())
            labels.append(lbl.strip())
        else:
            values.append(entry)
            labels.append("")
    return values, labels


def _format_choices(param: ParamDef) -> str:
    """Render a param's choices + labels back into the editable line."""
    parts: list[str] = []
    for i, value in enumerate(param.choices):
        label = (
            param.choice_labels[i]
            if i < len(param.choice_labels)
            else ""
        )
        if label:
            parts.append(f"{value}={label}")
        else:
            parts.append(value)
    return ",".join(parts)


# --- template text round-trip helpers --------------------------------------

def _template_to_text(entries: list) -> str:
    """Render an argument_template list as newline-separated lines.

    Groups (list[str]) are flattened into a single space-separated line.
    Plain strings become one line each.
    """
    lines: list[str] = []
    for entry in entries:
        if isinstance(entry, list):
            lines.append(" ".join(entry))
        else:
            lines.append(entry)
    return "\n".join(lines)


def _text_to_template(text: str) -> list:
    """Parse the editor's text into argument_template form.

    Each non-blank line becomes one entry. If the line has one
    whitespace-delimited token, it's stored as a string. If it has two
    or more, it's stored as a group (list[str]) — the runner will then
    emit them all or drop them all together.
    """
    out: list = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        tokens = line.split()
        if len(tokens) == 1:
            out.append(tokens[0])
        else:
            out.append(tokens)
    return out
