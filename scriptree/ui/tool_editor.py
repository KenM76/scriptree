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

## For maintainers / LLMs

- Unsaved-changes guard (v0.6.2): :meth:`is_dirty` compares
  ``tool_to_dict(self._tool)`` against ``self._baseline`` (a
  ``tool_to_dict`` snapshot taken at construction AND re-taken after
  every successful save). It deliberately serialises rather than
  tracking a flag, because the property-panel handlers mutate
  ``self._tool`` in place — a boolean dirty flag would miss those.
  Keep ``_baseline`` resynced on every save path or false-positive
  prompts return.
- :meth:`is_dirty` fails *safe*: if ``tool_to_dict`` ever raises it
  returns ``True`` (warn rather than silently lose work). Do not
  "fix" this to return ``False`` on exception.
- :meth:`_confirm_leave` is the single guard shared by Close and
  Cancel. Save branch returns ``False`` on purpose: the real save
  path (``_on_save``) emits ``saved`` and the main window navigates
  back itself, so this handler must NOT also emit ``cancelled``
  (double-navigation / double-emit). Save-blocked (validation,
  read-only, dialog-cancelled) correctly stays in the editor.
- ``_on_close`` and ``_on_cancel`` both gate on ``_confirm_leave``
  before emitting ``cancelled`` — a stray click must never silently
  discard unsaved work. Any new exit path must route through
  ``_confirm_leave`` too.
- Edits are in-place mutations of ``self._tool`` via ``_push_param``;
  there is no working copy. "Cancel discards" relies entirely on the
  caller throwing away this editor instance and reloading from disk —
  do not assume ``self._tool`` is pristine after a cancelled edit.
- Save is permission-gated upstream (``save_scriptree`` /
  ``save_as_scriptree`` checked in :mod:`main_window`); this view's
  Save button does not re-check capability, so do not invoke
  ``_on_save`` from a path that bypasses that gate.
- ``saved`` carries the final ``ToolDef``; the main window owns
  swapping back to the runner. The editor does not manage its own
  lifetime.
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
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QButtonGroup,
    QRadioButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.io import save_tool, tool_to_dict
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
# v0.8.0a22+ -- per-OS overrides editor section.  Self-contained
# QGroupBox slotted in after the Tool group; data-binds via
# ``load_from_tool`` / ``apply_to_tool`` and emits ``changed`` /
# ``previewOsChanged`` to drive the rest of the editor.
from .platform_overrides_widget import PlatformOverridesWidget
from .widgets.param_widgets import _DroppableLineEdit, build_widget_for


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

        # v0.6.2 — unsaved-changes detection.  Snapshot the tool's
        # serialised form right after construction; ``is_dirty()``
        # compares the live tool against it.  Serialised comparison
        # (not object identity) is robust to the in-place mutation
        # the property-panel handlers do, and ignores incidental
        # object churn.  Refreshed after every successful save.
        self._baseline = tool_to_dict(self._tool)

    # --- UI construction -------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        # Top: exe / name / description.
        top = QGroupBox("Tool")
        top_form = QFormLayout(top)
        # Drop-aware so the user can drag a binary onto it from
        # Explorer instead of clicking Browse — same convenience as
        # the param widgets in the runner form.
        self._exe_edit = _DroppableLineEdit(self._tool.executable)
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

        # v0.8.0a25+ Category line.  Slash-delimited taxonomy that
        # drives the forest's auto-organise pass.  Empty by default
        # so legacy tools stay byte-identical on round-trip.  See
        # ``docs/LLM/category_authoring.md`` for the contract.
        self._category_edit = QLineEdit(self._tool.category)
        self._category_edit.setPlaceholderText(
            "e.g. MSOffice/Word -- optional, used by the forest "
            "auto-organise pass"
        )
        self._category_edit.setToolTip(
            "Slash-delimited category path (e.g. 'MSOffice/Word').\n"
            "When two or more tools share a top-level category the "
            "forest auto-creates a single grouped cell for them.\n"
            "Empty = uncategorised (the tool appears as a flat cell)."
        )
        self._category_edit.textChanged.connect(
            self._on_category_changed
        )
        # v0.8.0a112 -- autocomplete from the canonical category catalog so the
        # user converges on the blessed vocabulary instead of a near-duplicate.
        try:
            from scriptree.ui.category_completer import attach_category_completer
            attach_category_completer(self._category_edit)
        except Exception:  # noqa: BLE001 -- completer is a nicety, never fatal
            pass
        top_form.addRow("Category:", self._category_edit)

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

        # Interactive stdin (V3 v0.3.0) — opt-in flag that tells the
        # runner to spawn the child with ``stdin=PIPE`` and surface a
        # send-line widget below the output pane.  Off by default;
        # use it for tools that implement query-replace-style prompt
        # loops (Emacs M-%) — pick a match, type ``y``/``n``/``!``/``q``,
        # hit Enter.  The runner ALSO requires the ``interactive_stdin``
        # capability to be granted; when missing the row is hidden and
        # the tool runs non-interactively.
        self._interactive_check = QCheckBox(
            "Allow this tool to read live input from stdin while running"
        )
        self._interactive_check.setToolTip(
            "When checked, the runner shows a send-line widget below "
            "the output pane so you can type responses (y / n / ! / q) "
            "to a running tool's prompt loop, Emacs M-% style.  Also "
            "requires the 'interactive_stdin' permission to be granted."
        )
        self._interactive_check.setChecked(bool(self._tool.interactive))
        self._interactive_check.toggled.connect(self._on_interactive_toggled)
        top_form.addRow("Interactive:", self._interactive_check)

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

        # Action buttons — tool.actions.  Rendered as a row next to
        # Run in ToolRunnerView when the tool is loaded.  Same UX
        # pattern as the menus row above: status label + Edit button
        # that opens a dedicated dialog.  Empty list = no row in
        # the runner.
        actions_row = QHBoxLayout()
        self._actions_status = QLabel(_actions_summary(self._tool))
        self._actions_status.setStyleSheet("color: #666;")
        actions_row.addWidget(self._actions_status, stretch=1)
        actions_btn = QPushButton("Edit actions...")
        actions_btn.setToolTip(
            "Add and configure the action buttons that appear next to "
            "Run in the tool runner.  Each action fires a fixed argv "
            "(no form-field substitution) -- useful for quick presets "
            "like 'git status', 'pip list --outdated', diagnostic "
            "dumps, etc."
        )
        actions_btn.clicked.connect(self._edit_tool_actions)
        actions_row.addWidget(actions_btn)
        actions_wrapper = QWidget()
        actions_wrapper.setLayout(actions_row)
        top_form.addRow("Action buttons:", actions_wrapper)

        outer.addWidget(top)

        # v0.8.0a22+ -- per-OS overrides section.  Slots in between
        # the Tool group and the Parameters splitter so the author
        # sees it as a natural extension of "executable / argument
        # template / PATH prepend" rather than an afterthought.
        # The widget hides its tabs behind a collapsible group box
        # so tools that don't use the feature aren't visually
        # taxed.
        self._platform_overrides = PlatformOverridesWidget()
        self._platform_overrides.load_from_tool(self._tool)
        # Live-refresh the inherited-preview rows whenever the
        # top-level executable / argument_template / path_prepend
        # change so the read-only side of each tab reflects what
        # would be inherited at any moment.
        self._exe_edit.textChanged.connect(
            self._refresh_platform_overrides_inherited
        )
        outer.addWidget(self._platform_overrides)

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
        # v0.6.0 — dynamic provider editor.  The button text reflects
        # whether the selected param currently has a provider so the
        # author can see at a glance which params are dynamic.
        self._prop_provider_btn = QPushButton("Provider…")
        self._prop_provider_btn.setToolTip(
            "Configure a dynamic choices/value provider: run an "
            "external command at form-open time to populate this "
            "field, optionally cascading from other params."
        )
        self._prop_provider_btn.clicked.connect(self._on_edit_provider)

        # v0.8.0a50 — emit mode + select-all master.  Only meaningful
        # on multiselect rendered as checkbox_list or dropdown.  Hidden
        # via ``_set_prop_row_visible`` for any other type/widget combo
        # in ``_populate_property_panel``.
        self._prop_emit = QComboBox()
        self._prop_emit.addItem("Send the SELECTED items (default)", "selected")
        self._prop_emit.addItem("Send the UNSELECTED items (complement)", "unselected")
        self._prop_emit.currentIndexChanged.connect(
            self._on_prop_emit_changed
        )
        self._prop_select_all = QCheckBox()
        self._prop_select_all.toggled.connect(
            self._on_prop_select_all_changed
        )

        # v0.8.0a51 — Default master-state picker.  Three radios in
        # a horizontal row: "All selected" / "All deselected" /
        # "Custom selection."  Clicking a radio mutates
        # ``param.default`` immediately (sets the full choice list,
        # the empty list, or leaves it alone respectively).  The
        # radios' displayed state is derived from the CURRENT
        # ``param.default`` vs ``param.choices`` at each
        # ``_load_param_into_panel`` so the picker stays honest
        # when the author edits choices.  Shown only for
        # checkbox_list / dropdown-multi without a provider --
        # provider-backed catalogs source their default from the
        # provider response, not from the static field.
        self._prop_default_state = QWidget()
        _ds_layout = QHBoxLayout(self._prop_default_state)
        _ds_layout.setContentsMargins(0, 0, 0, 0)
        _ds_layout.setSpacing(8)
        self._prop_default_state_group = QButtonGroup(self)
        self._prop_default_state_all = QRadioButton("All selected")
        self._prop_default_state_none = QRadioButton("All deselected")
        self._prop_default_state_custom = QRadioButton("Custom")
        self._prop_default_state_group.addButton(self._prop_default_state_all, 0)
        self._prop_default_state_group.addButton(self._prop_default_state_none, 1)
        self._prop_default_state_group.addButton(self._prop_default_state_custom, 2)
        _ds_layout.addWidget(self._prop_default_state_all)
        _ds_layout.addWidget(self._prop_default_state_none)
        _ds_layout.addWidget(self._prop_default_state_custom)
        _ds_layout.addStretch(1)
        self._prop_default_state_group.buttonClicked.connect(
            self._on_prop_default_state_picked
        )

        # v0.4.0 — every property row gets a hover tooltip on BOTH
        # the label and the input.  Previously the only tooltips on
        # the property panel were the ones manually wired above
        # (no_persist, no_split, choices, section); the rest of the
        # fields had no inline help at all, which made the editor
        # hostile to first-time tool authors.
        #
        # ``_add_prop_row`` is a tiny wrapper that calls
        # ``QFormLayout.addRow(label_widget, input)`` AFTER setting
        # the same tooltip on both so the user gets help whether
        # they hover the field name or the field itself.
        self._add_prop_row(
            "ID:", self._prop_id,
            "Internal identifier for this parameter.  Used inside "
            "the argument template (e.g. <code>{my_id}</code>) and "
            "in saved configurations.  Must be a valid Python "
            "identifier — letters, digits, underscores; can't "
            "start with a digit.  Renaming an ID rewrites every "
            "reference in the argument template.",
        )
        self._add_prop_row(
            "Label:", self._prop_label,
            "Human-readable name shown next to the field in the "
            "form.  Keep it short — under 30 characters typically "
            "fits the available space without truncation.",
        )
        self._add_prop_row(
            "Description:", self._prop_desc,
            "Longer help text that appears as a placeholder inside "
            "the field AND as a hover tooltip in the runner form. "
            "First few words show as placeholder; full text shows on "
            "hover.  This is the user's primary in-app help — write "
            "it as if the reader has never seen the tool before.",
        )
        self._add_prop_row(
            "Type:", self._prop_type,
            "Data type the field collects.  Limits which widgets "
            "are available (e.g. <code>bool</code> requires "
            "<code>checkbox</code>; <code>path</code> requires one "
            "of the file/folder pickers).  Type drives validation, "
            "default coercion, and how the value is rendered into "
            "the argument template.",
        )
        self._add_prop_row(
            "Widget:", self._prop_widget,
            "Visual control used to collect the value.  Filtered by "
            "the chosen Type — only compatible widgets appear in "
            "the dropdown.",
        )
        self._add_prop_row(
            "Required:", self._prop_required,
            "When checked, the user can't click Run until this "
            "field has a non-empty value.  An empty required field "
            "shows a red outline and disables the Run button.",
        )
        self._add_prop_row(
            "Do not save value:", self._prop_no_persist,
            "When checked, the parameter's value is never written "
            "into any saved configuration.  Useful for passwords, "
            "tokens, and other sensitive or scratch values.  The "
            "user's most recent entry is kept during the session "
            "but is lost when the tool is reloaded.",
        )
        self._add_prop_row(
            "Do not auto-split:", self._prop_no_split,
            "Opt out of the auto-split rule for this parameter.  "
            "By default, when a string param's placeholder is the "
            "entire template token (e.g. "
            "<code>argument_template=[\"{flags}\"]</code>) and the "
            "value contains whitespace, ScripTree splits it into "
            "multiple argv tokens — perfect for typing repeatable "
            "flags.  Check this box to disable that for this param: "
            "the value emits as a single argv token even with "
            "embedded spaces.",
        )
        self._add_prop_row(
            "Default:", self._prop_default,
            "Pre-filled value shown when the user first opens the "
            "form.  Should be the most useful starting point for "
            "the typical run — not an example.  For "
            "<code>bool</code> use <code>true</code> / "
            "<code>false</code>; for <code>enum</code> use one of "
            "the declared choices.",
        )
        self._add_prop_row(
            "Default state:", self._prop_default_state,
            "v0.8.0a51+.  Quick-picker for checkbox_list / "
            "dropdown-multi initial state.  <b>All selected</b> "
            "fills the Default field with every choice (form opens "
            "all-ticked).  <b>All deselected</b> empties it (form "
            "opens with nothing ticked).  <b>Custom</b> leaves the "
            "Default field alone -- edit it directly above to pick "
            "a partial selection.  The picker auto-syncs with the "
            "Default field when you edit choices.",
        )
        self._add_prop_row(
            "Choices:", self._prop_choices,
            "Dropdown choices.  Each entry is either a bare value "
            "(used both in argv and as the visible label) or "
            "<code>value=label</code> to show a descriptive label "
            "while sending the value to the command.  Comma-"
            "separated.  Only meaningful for <code>enum</code> / "
            "<code>multiselect</code> types.",
        )
        self._add_prop_row(
            "File filter:", self._prop_filter,
            "Qt file-dialog filter applied to "
            "<code>file_open</code> / <code>file_save</code> "
            "pickers.  Format: "
            "<code>&lt;name&gt; (*.ext1 *.ext2);;...</code> — e.g. "
            "<code>Text (*.txt);;All files (*)</code>.  Only "
            "meaningful for path-type / file-picker widgets.",
        )
        self._add_prop_row(
            "Section:", self._prop_section,
            "Which section this param belongs to.  The list tracks "
            "the tool's declared sections — use the +§ / ✎§ / −§ "
            "buttons above the param list to manage them.  Empty "
            "section falls into a synthetic 'Other' bucket at the "
            "end of the form.",
        )
        self._add_prop_row(
            "Provider:", self._prop_provider_btn,
            "Dynamic choices/value provider (v0.6.0).  Runs an "
            "external command at form-open time to populate this "
            "field — live dropdowns, dependent checkbox lists, "
            "auto-detected paths.  Click to configure.",
        )
        self._add_prop_row(
            "Emit:", self._prop_emit,
            "v0.8.0a50+.  Which half of the user's selection "
            "reaches the runner.  <b>Send the SELECTED items "
            "(default)</b> is the historical behaviour.  <b>Send "
            "the UNSELECTED items</b> is for deselect-to-act "
            "forms — e.g. \"here's everything currently enabled, "
            "untick what you want to turn off, then Run.\"  Only "
            "meaningful for multiselect rendered as checkbox_list "
            "or dropdown.",
        )
        self._add_prop_row(
            "Select-all master:", self._prop_select_all,
            "When checked, the checkbox_list shows a tri-state "
            "\"Select all\" master at the top so the user can "
            "tick or untick every row at once.  Highly recommended "
            "for any list with more than a handful of items, and "
            "especially for emit:unselected forms where the master "
            "becomes \"un-toggle everything.\"",
        )
        middle.addWidget(right_box)
        middle.setStretchFactor(0, 1)
        middle.setStretchFactor(1, 2)

        # Argument template + live preview + form preview.
        #
        # The lower half of the editor is a small internal QMainWindow
        # whose central widget is the template editor and whose right
        # dock holds the form preview.  Wrapping in a QMainWindow gives
        # the preview a real ``QDockWidget`` — users can detach it,
        # float it onto a second monitor, re-dock it left/right/top/
        # bottom, or hide it via the editor's View menu.  When docked
        # the resize behaviour is identical to the prior splitter.
        #
        # The preview renders exactly what a ``ToolRunnerView`` would
        # show at runtime for the tool *as currently edited*, with all
        # input widgets disabled so the user can't type into them by
        # mistake.  Every param mutation path calls
        # ``_rebuild_form_preview`` to keep it in sync.
        self._preview_host = QMainWindow()
        # ``Qt.Widget`` strips the QMainWindow's window-flag bits so it
        # behaves as a normal child widget inside our outer layout.
        self._preview_host.setWindowFlags(Qt.WindowType.Widget)
        # Allow the host to expand into available space.
        self._preview_host.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

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

        # Template box becomes the central widget of the internal host.
        self._preview_host.setCentralWidget(tmpl_box)

        # Populate the visual list from the initial template.
        self._sync_visual_from_model()

        # Form preview — wrapped in a QDockWidget so the user can
        # detach / float / re-dock it independently.
        self._form_preview_container = QWidget()
        self._form_preview_layout = QVBoxLayout(self._form_preview_container)
        self._form_preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_scroll = QScrollArea()
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setWidget(self._form_preview_container)

        self._preview_dock = QDockWidget(
            "Form preview (what the user will see)", self._preview_host
        )
        self._preview_dock.setObjectName("FormPreviewDock")
        self._preview_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._preview_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self._preview_dock.setWidget(preview_scroll)
        self._preview_host.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self._preview_dock
        )

        outer.addWidget(self._preview_host, stretch=1)

        # Buttons.
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        # v0.6.2 — "Close" returns to the form (runner) window, with
        # an unsaved-changes guard.  "Cancel" is the explicit
        # discard-and-leave action; it carries the same guard so no
        # exit path can silently drop edits.
        self._btn_close = QPushButton("Close")
        self._btn_close.setToolTip(
            "Return to the tool's form. Prompts to save if there "
            "are unsaved changes."
        )
        self._btn_close.clicked.connect(self._on_close)
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setToolTip(
            "Discard edits and return to the tool's form."
        )
        self._btn_cancel.clicked.connect(self._on_cancel)
        self._btn_save = QPushButton("Save")
        self._btn_save.setDefault(True)
        self._btn_save.clicked.connect(self._on_save)
        self._btn_save_as = QPushButton("Save as...")
        self._btn_save_as.clicked.connect(self._on_save_as)
        btn_row.addWidget(self._btn_close)
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
        # Capability gates (V3 v0.3.3) — independent of read-only:
        # an admin can deny save / save-as without making files
        # actually read-only on disk.  ``apply_widget_perm`` is a
        # no-op when the capability is granted.
        from .permission_guards import apply_widget_perm
        apply_widget_perm(self._btn_save, "save_scriptree")
        apply_widget_perm(self._btn_save_as, "save_as_scriptree")

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

    def _on_category_changed(self, text: str) -> None:
        """Mirror the Category line edit into ``ToolDef.category``.

        Stored verbatim -- the loader normalises on next load
        (strips slashes, drops empty segments).  We don't
        re-normalise on every keystroke because users WILL type
        ``/Word`` partway through typing ``MSOffice/Word`` and we
        shouldn't snip the caret out from under them.
        """
        self._tool.category = text

    def _on_interactive_toggled(self, checked: bool) -> None:
        """Mirror the checkbox state into ``ToolDef.interactive``.

        The runner re-evaluates this flag at run time; a Save is
        still required to persist the change to disk.
        """
        self._tool.interactive = bool(checked)

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

    def _edit_tool_actions(self) -> None:
        """Open the action-buttons editor and write results back to the tool.

        Same lifecycle as ``_edit_tool_menus`` -- the dialog mutates a
        deep copy of the list and only commits to ``self._tool.actions``
        on OK.  The main Save button persists to disk.
        """
        from .actions_editor import ActionsEditorDialog

        dlg = ActionsEditorDialog(
            self._tool.actions, tool=self._tool, parent=self,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self._tool.actions = dlg.actions
        self._actions_status.setText(_actions_summary(self._tool))

    # --- property-row tooltip helper (v0.4.0+) ---------------------------

    def _add_prop_row(
        self,
        label: str,
        widget: QWidget,
        tooltip_html: str,
    ) -> None:
        """Add a row to the property panel with the same hover
        tooltip on both the label and the input.

        Also stashes the row's label widget on a dict keyed by the
        input widget so ``_refresh_prop_visibility`` can hide /
        show the whole row (label + input) based on the param's
        type — keeps the panel uncluttered for types that don't
        need a given field.
        """
        from PySide6.QtWidgets import QLabel
        label_widget = QLabel(label)
        label_widget.setToolTip(tooltip_html)
        if not widget.toolTip():
            widget.setToolTip(tooltip_html)
        if not hasattr(self, "_prop_row_labels"):
            self._prop_row_labels: dict[QWidget, QLabel] = {}
        self._prop_row_labels[widget] = label_widget
        self._prop_layout.addRow(label_widget, widget)

    def _set_prop_row_visible(self, widget: QWidget, visible: bool) -> None:
        """Show / hide both the label and the input of the row
        owned by ``widget``.  Used by
        ``_refresh_prop_visibility``."""
        label = self._prop_row_labels.get(widget) if hasattr(
            self, "_prop_row_labels"
        ) else None
        if label is not None:
            label.setVisible(visible)
        widget.setVisible(visible)

    def _refresh_prop_visibility(self) -> None:
        """Hide property rows that aren't relevant to the currently
        selected param's type / widget combo.

        v0.4.0 — concrete de-busy step.  Previously the property
        panel showed every field for every param, including:

          * ``Choices:`` for a string field (meaningless).
          * ``File filter:`` for an integer field (meaningless).
          * ``Do not auto-split:`` for a checkbox (meaningless).

        Now we only show fields that affect the current param.
        The panel collapses to the minimum useful set per type.
        """
        if self._current_param_index is None:
            return
        if not (0 <= self._current_param_index < len(self._tool.params)):
            return
        param = self._tool.params[self._current_param_index]
        from ..core.model import ParamType, Widget as W
        is_enum = param.type in (ParamType.ENUM, ParamType.MULTISELECT)
        is_path = param.type is ParamType.PATH
        is_file_widget = param.widget in (W.FILE, W.SAVE_FILE)
        is_string = param.type is ParamType.STRING

        # Always-visible: ID, Label, Description, Type, Widget,
        # Required, Default, Section.  Conditional:
        self._set_prop_row_visible(self._prop_choices, is_enum)
        self._set_prop_row_visible(self._prop_filter, is_path and is_file_widget)
        self._set_prop_row_visible(self._prop_no_split, is_string)
        # "Do not save value" makes sense for any field that holds
        # a typed secret — keep visible for all string / path types
        # but hide for booleans (no secret bools).
        self._set_prop_row_visible(
            self._prop_no_persist,
            param.type in (
                ParamType.STRING, ParamType.PATH, ParamType.INTEGER,
                ParamType.NUMBER,
            ),
        )
        # v0.8.0a50+ -- emit + select_all rows are only meaningful
        # for multiselect rendered as checkbox_list or dropdown.
        # ``Select-all master`` further restricts to checkbox_list
        # (the master checkbox UX is checkbox_list-specific; a
        # dropdown-multi has its own affordances).
        is_multi_emit = (
            param.type is ParamType.MULTISELECT
            and param.widget in (W.CHECKBOX_LIST, W.DROPDOWN)
        )
        self._set_prop_row_visible(self._prop_emit, is_multi_emit)
        self._set_prop_row_visible(
            self._prop_select_all,
            param.type is ParamType.MULTISELECT
            and param.widget is W.CHECKBOX_LIST,
        )
        # v0.8.0a51+ -- the default-state radio picker is shown
        # ONLY when the param is a static-choice multiselect
        # rendered as checkbox_list / dropdown.  Provider-backed
        # catalogs source the initial selection from the provider
        # response (its ``default`` key in the JSON it emits),
        # so the static-default picker would be misleading.
        self._set_prop_row_visible(
            self._prop_default_state,
            is_multi_emit and param.choices_provider is None,
        )

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
            # When no param is selected, hide all conditional rows
            # so the panel reads as obviously empty rather than a
            # field-by-field "0 / 0 / 0" form.
            self._set_prop_row_visible(self._prop_choices, False)
            self._set_prop_row_visible(self._prop_filter, False)
            self._set_prop_row_visible(self._prop_no_split, False)
            self._set_prop_row_visible(self._prop_no_persist, False)
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
            # v0.6.0 — surface whether this param is dynamic right on
            # the button so the author doesn't have to open it to
            # find out.
            if param.choices_provider is not None:
                self._prop_provider_btn.setText("Provider ✓")
            else:
                self._prop_provider_btn.setText("Provider…")
            # v0.8.0a50+ — emit + select_all panel values.
            emit_idx = self._prop_emit.findData(
                getattr(param, "emit", "selected"),
            )
            if emit_idx >= 0:
                self._prop_emit.setCurrentIndex(emit_idx)
            self._prop_select_all.setChecked(
                bool(getattr(param, "select_all", False)),
            )
            # v0.8.0a51+ — recompute the default-state radio's
            # displayed selection from the current default vs
            # choices.  The radios block signals during this set
            # so we don't trigger ``_on_prop_default_state_picked``
            # in response to our own programmatic update.
            self._sync_default_state_radios(param)
            # v0.4.0 — hide rows that don't apply to this param's
            # type / widget combo to keep the panel uncluttered.
            self._refresh_prop_visibility()
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

    def _on_prop_emit_changed(self, _idx: int) -> None:
        """v0.8.0a50+ -- the multiselect emit-mode dropdown.

        Persists into ``param.emit`` ("selected" | "unselected").
        ParamDef.__post_init__ guards against illegal combinations
        at save / reload time; the editor UI also hides this row
        for non-applicable widgets via ``_refresh_prop_visibility``,
        so this handler doesn't need to re-validate.
        """
        if self._building_panel:
            return
        param = self._current_param()
        if param is None:
            return
        new_emit = self._prop_emit.currentData()
        if new_emit in ("selected", "unselected"):
            param.emit = str(new_emit)
            self._update_preview()

    def _on_prop_select_all_changed(self, checked: bool) -> None:
        """v0.8.0a50+ -- the ``Select all`` master-checkbox toggle.

        Only legal on ``checkbox_list``; ParamDef.__post_init__
        enforces.  The editor hides this row for other widgets.
        """
        if self._building_panel:
            return
        param = self._current_param()
        if param is None:
            return
        param.select_all = bool(checked)
        self._update_preview()

    def _sync_default_state_radios(self, param: ParamDef) -> None:
        """v0.8.0a51+ -- reflect the current ``param.default`` vs
        ``param.choices`` as a radio selection.

        ``All selected``  is shown when ``set(default) == set(choices)``
                          AND choices is non-empty.
        ``All deselected`` is shown when ``default`` is the empty list.
        ``Custom``        otherwise -- including the case where
                          ``default`` is some non-empty proper subset
                          AND the case where ``default`` is set but
                          ``choices`` is empty (rare; left to author).

        Signals are blocked during this set so the programmatic
        update doesn't fire ``_on_prop_default_state_picked``.
        """
        choices_set = {str(c) for c in (param.choices or [])}
        default_raw = param.default if isinstance(param.default, list) else []
        default_set = {str(c) for c in default_raw}
        if choices_set and default_set == choices_set:
            target = self._prop_default_state_all
        elif not default_set:
            target = self._prop_default_state_none
        else:
            target = self._prop_default_state_custom
        # Block while we set so the click signal stays quiet.
        for btn in (
            self._prop_default_state_all,
            self._prop_default_state_none,
            self._prop_default_state_custom,
        ):
            btn.blockSignals(True)
        try:
            self._prop_default_state_group.setExclusive(False)
            self._prop_default_state_all.setChecked(False)
            self._prop_default_state_none.setChecked(False)
            self._prop_default_state_custom.setChecked(False)
            self._prop_default_state_group.setExclusive(True)
            target.setChecked(True)
        finally:
            for btn in (
                self._prop_default_state_all,
                self._prop_default_state_none,
                self._prop_default_state_custom,
            ):
                btn.blockSignals(False)

    def _on_prop_default_state_picked(self, button) -> None:  # noqa: ANN001
        """v0.8.0a51+ -- handle a click on one of the three radios.

        Acts immediately on ``param.default``:
          * All selected    -> default = list(param.choices)
          * All deselected  -> default = []
          * Custom          -> leave ``default`` alone

        After mutating ``default``, the ``Default:`` text field
        gets re-rendered through the standard
        ``_load_param_into_panel`` path so the picker + the raw
        field stay in lock-step.
        """
        if self._building_panel:
            return
        param = self._current_param()
        if param is None:
            return
        if button is self._prop_default_state_all:
            param.default = list(param.choices)
        elif button is self._prop_default_state_none:
            param.default = []
        else:
            return  # "Custom" -- leave default alone
        # Re-render so the Default text field reflects the new
        # value; _sync_default_state_radios will re-check the
        # same radio (idempotent).
        self._load_param_into_panel(param)
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

    def _on_edit_provider(self) -> None:
        """Open the dynamic-provider editor for the selected param."""
        if self._building_panel:
            return
        param = self._current_param()
        if param is None:
            return
        from .provider_editor import ProviderEditorDialog, apply_to_param
        other_ids = [
            p.id for p in self._tool.params if p.id != param.id
        ]
        dlg = ProviderEditorDialog(param, other_ids, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            apply_to_param(dlg, param)
            # Refresh the panel (Choices row may now be irrelevant,
            # button label flips to "Provider ✓") and the preview.
            self._load_param_into_panel(param)
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

    def save(self) -> None:
        """Public entry point — same as clicking the Save button.

        Invoked by the main window's File → Save tool action so the
        same code path runs for both keyboard / menu shortcuts and the
        editor's own button row.
        """
        self._on_save()

    def save_as(self) -> None:
        """Public entry point — same as clicking the Save as... button."""
        self._on_save_as()

    def file_path(self) -> str | None:
        """Return the on-disk path the editor is currently bound to,
        or ``None`` for an unsaved tool."""
        return self._file_path

    def preview_dock(self) -> QDockWidget:
        """Return the form-preview QDockWidget — used by the main window
        to wire its View menu's Show/Hide form preview toggle to the
        same dock the user can also drag/float directly."""
        return self._preview_dock

    def _refresh_platform_overrides_inherited(self) -> None:
        """Push the editor's current top-level Executable /
        argument_template / path_prepend values into every
        platform tab's read-only "inherited from default" preview.

        Hooked to ``self._exe_edit.textChanged`` so a typo
        correction propagates to every tab without the author
        having to switch away and back.  ``argument_template``
        and ``path_prepend`` are edited via separate widgets;
        their change handlers call this too (added incrementally
        as those edit paths are wired).  For now the executable
        is the most-edited field and the highest-value hookup.
        """
        if not hasattr(self, "_platform_overrides"):
            return  # constructor not finished
        try:
            self._platform_overrides.refresh_inherited(
                executable=self._tool.executable,
                argument_template_text=_template_to_text(
                    self._tool.argument_template,
                ),
                path_prepend=list(self._tool.path_prepend or []),
            )
        except Exception:  # noqa: BLE001
            # Refresh is decorative -- never crash the editor over it.
            pass

    def _on_save(self) -> None:
        if self._read_only and self._file_path is not None:
            QMessageBox.warning(
                self, "Read-only",
                "This file is read-only and cannot be saved.",
            )
            return
        # v0.8.0a22+ -- flush the per-OS overrides widget into
        # ``self._tool.platforms`` BEFORE validation / save so
        # the on-disk file reflects whatever's in the tabs.  The
        # widget's ``apply_to_tool`` drops keys whose override
        # toggle is off, so a previously-saved override the user
        # un-ticked also gets removed correctly.
        self._platform_overrides.apply_to_tool(self._tool)
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
        # Edits are now persisted — reset the dirty baseline so a
        # subsequent Close doesn't re-warn about already-saved work.
        self._baseline = tool_to_dict(self._tool)
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
        # Edits are now persisted — reset the dirty baseline so a
        # subsequent Close doesn't re-warn about already-saved work.
        self._baseline = tool_to_dict(self._tool)
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

    def is_dirty(self) -> bool:
        """True iff the tool has unsaved edits.

        Serialised comparison against the post-construction (or
        post-save) baseline — robust to the in-place mutation the
        property-panel handlers do."""
        try:
            return tool_to_dict(self._tool) != self._baseline
        except Exception:  # noqa: BLE001
            # If serialisation ever throws, fail safe: assume dirty
            # so the user is warned rather than silently losing work.
            return True

    def _confirm_leave(self) -> bool:
        """Guard shared by Close / Cancel.  Returns True if it's OK
        to leave the editor now (caller then emits ``cancelled`` /
        navigates away), False to stay.

        Clean (not dirty) → leave silently.  Dirty → Save / Discard /
        Cancel.  Save runs the normal save path (which emits
        ``saved`` and navigates back to the form itself), so on the
        Save branch we return False and let that flow take over."""
        if not self.is_dirty():
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Unsaved changes")
        box.setText(
            "This tool has unsaved changes.\n\n"
            "Save them before returning to the form?"
        )
        save_b = box.addButton(
            "Save", QMessageBox.ButtonRole.AcceptRole
        )
        discard_b = box.addButton(
            "Discard", QMessageBox.ButtonRole.DestructiveRole
        )
        cancel_b = box.addButton(
            "Cancel", QMessageBox.ButtonRole.RejectRole
        )
        box.setDefaultButton(save_b)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel_b:
            return False  # stay in the editor
        if clicked is discard_b:
            return True  # leave, dropping edits
        # Save: run the real save path.  If it actually persisted
        # (file no longer dirty), it already emitted ``saved`` →
        # the main window returns to the form.  We return False so
        # this handler doesn't ALSO emit ``cancelled``.  If the save
        # was blocked (validation error / read-only / cancelled save
        # dialog), staying in the editor is the right outcome.
        self._on_save()
        return False

    def _on_close(self) -> None:
        """Return to the form (runner) window, warning first if
        there are unsaved changes."""
        if self._confirm_leave():
            self.cancelled.emit()

    def _on_cancel(self) -> None:
        # Cancel = discard-and-leave, but still guard so a stray
        # click can't silently destroy unsaved work.
        if self._confirm_leave():
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


def _actions_summary(tool: ToolDef) -> str:
    """Short status for the ``Edit actions...`` inline label.

    Reports the visible vs hidden count so the user can tell at a
    glance whether actions are defined and how many will render as
    buttons.  Mirrors :func:`_menus_summary`'s shape.
    """
    if not tool.actions:
        return "<i>none</i>"
    visible = sum(1 for a in tool.actions if not a.hidden)
    hidden = len(tool.actions) - visible
    parts = [f"{visible} button{'s' if visible != 1 else ''}"]
    if hidden:
        parts.append(f"{hidden} hidden")
    return ", ".join(parts)


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
