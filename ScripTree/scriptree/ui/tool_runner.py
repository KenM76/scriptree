"""Runtime view of a tool: form on top, extras + output below, Run button.

This is what the user interacts with day-to-day. Given a ``ToolDef``
(loaded from a ``.scriptree`` file), it renders a form using the
widgets module, and when the user clicks Run it dispatches to
``core.runner.spawn_streaming`` in a worker thread and streams the
child process output to a text pane.

## Editable command preview

The button row carries a "Show full path" checkbox, a "Word wrap"
checkbox, and an editable ``QPlainTextEdit`` that always shows the
full resolved argv (GUI params plus user-added extras). Editing it
calls ``reconcile_edit`` which
parses the edit back into widget values and a list of "extras" —
tokens that don't fit any template entry. Extras are also displayed
in a small box above the output pane, where they can be edited
directly.

## Loop guard

Two code paths update the same widgets and the same preview field:
the user typing into a form widget (``valueChanged`` -> preview
rebuild) and the user typing into the preview (``textEdited`` ->
widget rebuild). A ``_updating`` flag guards against re-entry so
setting widget values programmatically doesn't fire another
reconcile pass.
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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

from ..core.configs import (
    Configuration,
    ConfigurationSet,
    UIVisibility,
    default_configuration_set,
    is_reserved_config_name,
    load_configs,
    save_configs,
)
from ..core.io import save_tool
from ..core.model import ParamDef, ToolDef
from .env_editor import EnvEditorDialog
from ..core.credentials import StoredCredential, get_session_store
from ..core.permissions import check_write_access
from ..core.sanitize import sanitize_all_values
from ..core.runner import (
    ResolvedCommand,
    RunnerError,
    build_full_argv,
    reconcile_edit,
    resolve,
    spawn_streaming,
    spawn_streaming_as_user,
)
from .widgets.param_widgets import ParamWidget, build_widget_for


# --- reorderable form container -------------------------------------------

class ReorderableParamForm(QListWidget):
    """A QListWidget that renders a tool's params as drag-reorderable rows.

    Each row is a custom item widget with three parts:
    a drag handle on the left, the param label, and the real input widget.
    Dragging a row up or down rearranges the items via Qt's internal-move
    drag drop; after the move the ``orderChanged`` signal fires with the
    new param-id order.

    The layout is deliberately simpler than QFormLayout — labels are
    fixed-width so columns line up roughly without needing a label
    alignment pass. This keeps drag-drop plumbing trivial.
    """

    orderChanged = Signal(list)  # list[str] — param ids in new order

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.setUniformItemSizes(False)
        # Qt's list-widget rowsMoved signal fires after the user drops a
        # row. We translate that to a clean orderChanged emission.
        self.model().rowsMoved.connect(self._on_rows_moved)

    def add_param_row(
        self,
        param_id: str,
        label_text: str,
        widget: QWidget,
        tooltip: str = "",
    ) -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(2, 2, 2, 2)
        row_layout.setSpacing(6)

        handle = QLabel("\u2630")  # three horizontal bars — universal "drag" glyph
        handle.setFixedWidth(18)
        handle.setStyleSheet("color: #888;")
        handle.setToolTip("Drag to reorder this parameter.")
        row_layout.addWidget(handle)

        label = QLabel(label_text)
        label.setMinimumWidth(140)
        label.setMaximumWidth(180)
        label.setWordWrap(True)
        if tooltip:
            label.setToolTip(tooltip)
        row_layout.addWidget(label)

        row_layout.addWidget(widget, stretch=1)

        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, param_id)
        # Size hint drives row height. Pick up the container's preferred.
        item.setSizeHint(row.sizeHint())
        self.addItem(item)
        self.setItemWidget(item, row)

    def current_order(self) -> list[str]:
        return [
            self.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.count())
        ]

    def _on_rows_moved(self, *_args: Any) -> None:
        self.orderChanged.emit(self.current_order())


# --- configuration edit dialog --------------------------------------------

class ConfigurationEditDialog(QDialog):
    """Popup for reordering and renaming configurations.

    Works on a deep copy of the ``ConfigurationSet`` passed in; the
    caller reads ``result_configurations()`` only after ``exec`` returns
    ``Accepted``. Dismissing the dialog leaves the original set
    untouched.

    The UI is a QListWidget (drag-reorderable, each item editable
    in-place via double-click) plus Up/Down/Rename/OK/Cancel buttons.
    """

    def __init__(
        self,
        cfg_set: ConfigurationSet,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit configurations")
        self.resize(360, 320)

        # Work on a private copy — preserve Configuration.values/extras
        # so nothing gets lost if the user only renames/reorders.
        self._working: list[Configuration] = [
            Configuration(
                name=c.name,
                values=dict(c.values),
                extras=list(c.extras),
            )
            for c in cfg_set.configurations
        ]

        layout = QVBoxLayout(self)

        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        for i, c in enumerate(self._working):
            item = QListWidgetItem(c.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            # Stash the original index so we can re-associate the row
            # with its Configuration even after drag-drop and renames.
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._list.addItem(item)
        layout.addWidget(self._list, stretch=1)

        hint = QLabel(
            "<i>Drag rows to reorder. Double-click a row to rename.</i>"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        self._btn_up = QPushButton("Move up")
        self._btn_up.clicked.connect(lambda: self._move(-1))
        self._btn_down = QPushButton("Move down")
        self._btn_down.clicked.connect(lambda: self._move(1))
        self._btn_rename = QPushButton("Rename")
        self._btn_rename.clicked.connect(self._rename)
        btn_row.addWidget(self._btn_up)
        btn_row.addWidget(self._btn_down)
        btn_row.addWidget(self._btn_rename)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        dialog_btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        dialog_btns.accepted.connect(self._on_accept)
        dialog_btns.rejected.connect(self.reject)
        layout.addWidget(dialog_btns)

        if self._working:
            self._list.setCurrentRow(0)

    # --- helpers --------------------------------------------------------

    def _move(self, delta: int) -> None:
        row = self._list.currentRow()
        new_row = row + delta
        if row < 0 or new_row < 0 or new_row >= self._list.count():
            return
        item = self._list.takeItem(row)
        self._list.insertItem(new_row, item)
        self._list.setCurrentRow(new_row)

    def _rename(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        self._list.editItem(self._list.item(row))

    def _collect_names_from_list(self) -> list[str]:
        return [self._list.item(i).text().strip() for i in range(self._list.count())]

    def _on_accept(self) -> None:
        names = self._collect_names_from_list()
        if any(not n for n in names):
            QMessageBox.warning(
                self,
                "Invalid name",
                "Configuration names cannot be empty.",
            )
            return
        reserved = [n for n in names if is_reserved_config_name(n)]
        if reserved:
            QMessageBox.warning(
                self,
                "Reserved name",
                f"The name '{reserved[0]}' is reserved by ScripTree "
                "and cannot be used for user configurations.",
            )
            return
        if len(set(names)) != len(names):
            QMessageBox.warning(
                self,
                "Duplicate name",
                "Configuration names must be unique.",
            )
            return
        self.accept()

    def result_configurations(self) -> list[Configuration]:
        """Return the edited list in the order shown in the list widget.

        Uses the ``UserRole`` data we stashed at init time to map each
        row back to its original working-copy Configuration — this way
        drag-drop reordering and inline rename both survive without
        name-collision heuristics.
        """
        result: list[Configuration] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            original_idx = item.data(Qt.ItemDataRole.UserRole)
            if original_idx is None or not (0 <= original_idx < len(self._working)):
                continue
            cfg = self._working[original_idx]
            cfg.name = item.text().strip()
            result.append(cfg)
        return result


# --- worker thread --------------------------------------------------------

class _RunWorker(QObject):
    """Runs ``spawn_streaming`` in a worker thread and re-emits each line.

    Qt signals cross the thread boundary cleanly, which is why we use
    this wrapper instead of calling the runner directly from the UI
    thread (that would block the event loop).

    The worker also exposes :meth:`stop` so the UI can ask the child
    process to terminate. The Popen handle is stashed via the
    ``on_start`` callback that ``spawn_streaming`` invokes right after
    spawning the process, so the main thread can touch it without
    racing the pump threads.

    When ``credentials`` are provided, the worker uses
    ``spawn_streaming_as_user`` instead of ``spawn_streaming`` to
    launch the child process under a different user's security context.
    """

    stdoutLine = Signal(str)
    stderrLine = Signal(str)
    finished = Signal(int, float)

    def __init__(
        self,
        command: ResolvedCommand,
        *,
        credentials: tuple[str, str, str] | None = None,
    ) -> None:
        super().__init__()
        self._command = command
        # (username, password, domain) or None for normal spawn.
        self._credentials = credentials
        # Set from the worker thread in ``_on_process_start``; read
        # from the UI thread in ``stop``. A plain attribute assignment
        # is atomic in CPython and the Stop button races are benign —
        # worst case we call terminate on an already-exited process.
        self._proc: subprocess.Popen | None = None
        self._stop_level = 0  # 0=running, 1=terminate sent, 2=kill sent

    def run(self) -> None:
        try:
            if self._credentials is not None:
                username, password, domain = self._credentials
                result = spawn_streaming_as_user(
                    self._command,
                    username,
                    password,
                    domain,
                    self.stdoutLine.emit,
                    self.stderrLine.emit,
                    on_start=self._on_process_start,
                )
            else:
                result = spawn_streaming(
                    self._command,
                    self.stdoutLine.emit,
                    self.stderrLine.emit,
                    on_start=self._on_process_start,
                )
        except Exception as e:  # noqa: BLE001 - surface to UI
            self.stderrLine.emit(f"[runner error] {e}")
            self.finished.emit(-1, 0.0)
            return
        self.finished.emit(result.exit_code, result.duration_seconds)

    def _on_process_start(self, proc: subprocess.Popen) -> None:
        self._proc = proc

    def stop(self) -> int:
        """Ask the child process to stop.

        First press sends ``terminate()`` (SIGTERM / graceful on POSIX,
        ``TerminateProcess`` on Windows). A second press escalates to
        ``kill()``. Returns the new stop level (1 or 2); returns 0 if
        there's no live process to stop.
        """
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return 0
        if self._stop_level == 0:
            try:
                proc.terminate()
            except OSError:
                pass
            self._stop_level = 1
        else:
            try:
                proc.kill()
            except OSError:
                pass
            self._stop_level = 2
        return self._stop_level


# --- main widget ----------------------------------------------------------

class ToolRunnerView(QWidget):
    """Form + output pane for running one tool.

    The widget takes ownership of the tool definition and manages one
    active run at a time. Launching Run while a process is live is
    disabled by the button state.
    """

    # Emitted whenever the run state of this view changes. Arguments
    # are ``(file_path_or_empty_string, is_running)``. The MainWindow
    # listens on this so the launcher tree can mark any currently
    # running tool with a visible indicator. Unsaved (in-memory) tools
    # emit an empty path string.
    runningChanged = Signal(str, bool)

    # Emitted when the active configuration's UIVisibility changes
    # (e.g. user switches to a "standalone" config that hides the
    # command line). The MainWindow listens to adjust dock visibility.
    visibilityChanged = Signal(object)  # arg: UIVisibility

    def __init__(
        self,
        tool: ToolDef,
        file_path: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tool = tool
        self._file_path = file_path
        self._widgets: dict[str, ParamWidget] = {}
        self._thread: QThread | None = None
        self._worker: _RunWorker | None = None

        # Editable-preview state.
        self._extras: list[str] = []
        self._show_full_path = False
        # Stderr buffer for popup-on-error when output pane is hidden.
        self._stderr_buffer: list[str] = []
        # Params currently hidden by the active configuration.
        self._active_hidden_params: list[str] = []
        # When True, _apply_visibility actually hides/shows widgets.
        # When False (the default, i.e. docked in the main window),
        # visibility flags are ignored so the user always has full
        # access to all controls.
        self._standalone_mode: bool = False
        # When True, all editing/saving controls are disabled because
        # the file (or its sidecar) is not writable by the current user.
        if file_path:
            access = check_write_access(file_path)
            self._read_only: bool = not access.fully_writable
        else:
            self._read_only = False
        # Re-entry guard for the preview <-> widgets <-> extras round-trip.
        # When set, all three update slots short-circuit so setting a
        # widget value programmatically doesn't trigger another reconcile.
        self._updating = False

        # Undo / redo history for manual edits to the command preview.
        # Each entry is a snapshot of ``(widget_values, extras)``. On a
        # successful reconcile from ``_on_live_cmd_edited`` we push a
        # new snapshot and truncate any redo tail. Undo/Redo walk the
        # list and reapply snapshots via ``_apply_snapshot``. The first
        # entry (index 0) is the "initial" state used by Reset.
        self._history: list[tuple[dict, list[str]]] = []
        self._history_index: int = -1
        # Guard to prevent snapshot pushes while we're restoring one.
        self._restoring_snapshot = False

        # Build the two major panels as standalone widgets so the
        # MainWindow can reparent them into QDockWidgets when needed.
        # When used standalone (no dock), they sit in a vertical
        # splitter inside this widget's own layout.
        self._form_container = self._build_form_panel(tool)
        self._output_container = self._build_output_panel()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._inner_splitter = QSplitter(Qt.Orientation.Vertical)
        self._inner_splitter.addWidget(self._form_container)
        self._inner_splitter.addWidget(self._output_container)
        self._inner_splitter.setStretchFactor(0, 3)
        self._inner_splitter.setStretchFactor(1, 2)
        layout.addWidget(self._inner_splitter)

        # Seed the preview with the initial defaults.
        self._update_live_cmd()

        # Load the sidecar configurations file (if any). If missing,
        # build a single in-memory "default" configuration seeded with
        # the current widget values so the UI always has something to
        # display in the combobox. We do this AFTER the first
        # _update_live_cmd so the defaults come from widget init, not
        # a stale snapshot.
        self._load_or_init_configs()
        self._refresh_cfg_combo()
        self._refresh_cfg_buttons()

        # Capture the initial state as history entry 0 — this is what
        # Reset restores to and the floor for Undo.
        self._push_history_snapshot()
        self._refresh_edit_buttons()

    @property
    def form_panel(self) -> QWidget:
        """The form panel (header, params, extras, cmd, config, actions)."""
        return self._form_container

    @property
    def output_panel(self) -> QWidget:
        """The output panel."""
        return self._output_container

    def _build_output_panel(self) -> QWidget:
        """Build the output pane as a standalone widget."""
        output_box = QGroupBox("Output")
        out_layout = QVBoxLayout(output_box)
        mono = QFont()
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setFamily("Consolas")
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(mono)
        out_layout.addWidget(self._output)
        return output_box

    def _build_form_panel(self, tool: ToolDef) -> QWidget:
        """Build the form panel as a standalone widget."""
        from PySide6.QtWidgets import QMenuBar
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)

        # Custom menus defined in the .scriptree file.
        if tool.menus:
            menu_bar = QMenuBar(container)
            self._build_custom_menus(menu_bar, tool.menus)
            layout.setMenuBar(menu_bar)

        # Header.
        header = QLabel(f"<h2>{tool.name}</h2>")
        layout.addWidget(header)
        if tool.description:
            layout.addWidget(QLabel(tool.description))

        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter, stretch=1)

        # Form — one reorderable list per section (or one flat list
        # if the tool doesn't declare sections). Users drag rows up
        # or down within a section to rearrange widgets; reorder is
        # persisted back to the .scriptree file if a ``file_path`` was
        # supplied. Section headers are collapsible QGroupBox widgets
        # whose "checked" state drives both the expand/collapse UI and
        # the ``Section.collapsed`` field on save.
        form_group = QGroupBox("Parameters")
        self._form_outer_layout = QVBoxLayout(form_group)
        self._form_outer_layout.setContentsMargins(6, 6, 6, 6)
        # Map from section-name -> ReorderableParamForm. The empty
        # string key is used for the single form when no sections are
        # declared.
        self._section_forms: dict[str, ReorderableParamForm] = {}
        # Map from section-name -> QGroupBox (so collapse toggling
        # can save back to the model).
        self._section_boxes: dict[str, QGroupBox] = {}
        # The trailing stretch must exist *before* _populate_form_rows
        # runs, because that method inserts widgets at count-1 (i.e.
        # just before this stretch). Without it the first population
        # reverses the section order.
        self._form_outer_layout.addStretch(1)
        if not tool.params:
            self._form_outer_layout.insertWidget(
                0, QLabel("<i>This tool has no parameters. Click Run.</i>")
            )
        else:
            self._populate_form_rows()
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        form_scroll.setWidget(form_group)
        splitter.addWidget(form_scroll)

        # Extras box — space-separated argv tokens the user has added
        # beyond what the GUI form produces. Populated either by
        # reconciling edits to the command preview or typed directly.
        self._extras_box = extras_box = QGroupBox("Extra arguments (space-separated)")
        extras_layout = QVBoxLayout(extras_box)
        extras_layout.setContentsMargins(6, 4, 6, 6)
        extras_help = QLabel(
            "<i>Tokens here are appended to the command as-is. "
            "Anything you type in the preview below that doesn't match "
            "a form parameter lands here automatically.</i>"
        )
        extras_help.setWordWrap(True)
        extras_layout.addWidget(extras_help)
        self._extras_edit = QPlainTextEdit()
        self._extras_edit.setMaximumHeight(60)
        mono = QFont()
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setFamily("Consolas")
        self._extras_edit.setFont(mono)
        self._extras_edit.setPlaceholderText(
            "e.g. --debug 2 --log-file C:/tmp/run.log"
        )
        self._extras_edit.textChanged.connect(self._on_extras_edited)
        extras_layout.addWidget(self._extras_edit)
        splitter.addWidget(extras_box)

        # Command preview — editable QPlainTextEdit with "Full path"
        # and "Word wrap" checkboxes.
        self._cmd_box = cmd_box = QGroupBox("Command line")
        cmd_layout = QVBoxLayout(cmd_box)
        cmd_layout.setContentsMargins(6, 4, 6, 6)
        cmd_opts = QHBoxLayout()

        self._chk_full_path = QCheckBox("Full path")
        self._chk_full_path.setToolTip(
            "Show the executable's full path in the command preview."
        )
        self._chk_full_path.setChecked(False)
        self._chk_full_path.toggled.connect(self._on_full_path_toggled)
        cmd_opts.addWidget(self._chk_full_path)

        self._chk_word_wrap = QCheckBox("Word wrap")
        self._chk_word_wrap.setToolTip(
            "Wrap long command lines in the preview."
        )
        self._chk_word_wrap.setChecked(False)
        self._chk_word_wrap.toggled.connect(self._on_word_wrap_toggled)
        cmd_opts.addWidget(self._chk_word_wrap)

        cmd_opts.addStretch(1)
        cmd_layout.addLayout(cmd_opts)

        self._live_cmd = QPlainTextEdit()
        self._live_cmd.setPlaceholderText(
            "Command line — edit to override form values or add extras..."
        )
        preview_font = QFont()
        preview_font.setStyleHint(QFont.StyleHint.Monospace)
        preview_font.setFamily("Consolas")
        self._live_cmd.setFont(preview_font)
        self._live_cmd.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._live_cmd.textChanged.connect(self._on_live_cmd_text_changed)
        cmd_layout.addWidget(self._live_cmd)
        splitter.addWidget(cmd_box)

        splitter.setStretchFactor(0, 3)  # form
        splitter.setStretchFactor(1, 0)  # extras (compact)
        splitter.setStretchFactor(2, 0)  # command line (compact)

        # Configurations bar: [Config ▾] [Save] [Save As] [Delete] [Edit...]
        # Wrapped in a QWidget so the MainWindow can show/hide it
        # based on whether the form dock is floating.
        self._cfg_set: ConfigurationSet = default_configuration_set()
        self._cfg_loading = False
        self._cfg_widget = QWidget()
        cfg_layout = QHBoxLayout(self._cfg_widget)
        cfg_layout.setContentsMargins(0, 0, 0, 0)
        cfg_layout.addWidget(QLabel("Configuration:"))

        # Read-only indicator — shown when the file is not writable.
        self._read_only_label = QLabel("\U0001f512 Read-only")
        self._read_only_label.setStyleSheet(
            "QLabel { color: #888; font-style: italic; padding: 0 4px; }"
        )
        self._read_only_label.setToolTip(
            "This file or its configuration sidecar is not writable. "
            "Editing is disabled."
        )
        self._read_only_label.setVisible(self._read_only)
        cfg_layout.addWidget(self._read_only_label)

        self._cfg_combo = QComboBox()
        self._cfg_combo.setMinimumWidth(180)
        self._cfg_combo.currentIndexChanged.connect(self._on_cfg_combo_changed)
        cfg_layout.addWidget(self._cfg_combo, stretch=1)

        self._btn_cfg_save = QPushButton("Save")
        self._btn_cfg_save.setToolTip(
            "Save the current form values into the selected configuration."
        )
        self._btn_cfg_save.clicked.connect(self._cfg_save)
        cfg_layout.addWidget(self._btn_cfg_save)

        self._btn_cfg_save_as = QPushButton("Save as...")
        self._btn_cfg_save_as.setToolTip(
            "Create a new configuration with the current form values."
        )
        self._btn_cfg_save_as.clicked.connect(self._cfg_save_as)
        cfg_layout.addWidget(self._btn_cfg_save_as)

        self._btn_cfg_delete = QPushButton("Delete")
        self._btn_cfg_delete.setToolTip("Delete the selected configuration.")
        self._btn_cfg_delete.clicked.connect(self._cfg_delete)
        cfg_layout.addWidget(self._btn_cfg_delete)

        self._btn_cfg_edit = QPushButton("Edit...")
        self._btn_cfg_edit.setToolTip(
            "Reorder and rename configurations in a popup."
        )
        self._btn_cfg_edit.clicked.connect(self._cfg_edit)
        cfg_layout.addWidget(self._btn_cfg_edit)

        self._btn_cfg_env = QPushButton("Env...")
        self._btn_cfg_env.setToolTip(
            "Edit environment variables and PATH prepends for the "
            "selected configuration. These layer on top of the "
            "tool-level environment defined in the editor."
        )
        self._btn_cfg_env.clicked.connect(self._cfg_edit_env)
        cfg_layout.addWidget(self._btn_cfg_env)

        self._btn_cfg_visibility = QPushButton("Visibility...")
        self._btn_cfg_visibility.setToolTip(
            "Choose which UI elements to show or hide, and lock "
            "individual parameters to fixed values for this "
            "configuration."
        )
        self._btn_cfg_visibility.clicked.connect(self._cfg_edit_visibility)
        cfg_layout.addWidget(self._btn_cfg_visibility)

        self._chk_prompt_creds = QCheckBox("Prompt for alternate credentials")
        self._chk_prompt_creds.setToolTip(
            "When checked, clicking Run will prompt for a username "
            "and password. The process will be launched under that "
            "user's security context (Windows only)."
        )
        self._chk_prompt_creds.toggled.connect(self._on_prompt_creds_toggled)
        cfg_layout.addWidget(self._chk_prompt_creds)

        layout.addWidget(self._cfg_widget)

        # Action row: [Run] [Stop] [Copy argv] [Undo] [Redo] [Reset] [Clear]
        action_row = QHBoxLayout()

        self._btn_run = QPushButton("Run")
        self._btn_run.setDefault(True)
        self._btn_run.clicked.connect(self._start_run)
        action_row.addWidget(self._btn_run)

        self._btn_stop = QPushButton("Stop")
        self._btn_stop.setToolTip(
            "Terminate the running child process. First press sends "
            "terminate; a second press sends kill."
        )
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_run)
        action_row.addWidget(self._btn_stop)

        self._btn_preview = QPushButton("Copy argv")
        self._btn_preview.clicked.connect(self._copy_argv)
        action_row.addWidget(self._btn_preview)

        self._btn_undo = QPushButton("Undo")
        self._btn_undo.setToolTip("Undo the last manual edit to the command line.")
        self._btn_undo.clicked.connect(self._undo_edit)
        action_row.addWidget(self._btn_undo)

        self._btn_redo = QPushButton("Redo")
        self._btn_redo.setToolTip("Redo the next manual edit to the command line.")
        self._btn_redo.clicked.connect(self._redo_edit)
        action_row.addWidget(self._btn_redo)

        self._btn_reset = QPushButton("Reset")
        self._btn_reset.setToolTip(
            "Discard every manual edit and restore the form defaults."
        )
        self._btn_reset.clicked.connect(self._reset_edits)
        action_row.addWidget(self._btn_reset)

        self._btn_clear_output = QPushButton("Clear output")
        self._btn_clear_output.setToolTip("Clear the output pane.")
        self._btn_clear_output.clicked.connect(self._clear_output)
        action_row.addWidget(self._btn_clear_output)

        action_row.addStretch(1)

        # User/credential indicator — shows which user the tool will
        # run as when prompt_credentials is active and credentials are
        # cached. Hidden by default; shown when a run-as user is active.
        self._user_indicator = QLabel("")
        self._user_indicator.setStyleSheet(
            "QLabel { color: #0050a0; font-weight: bold; padding: 2px 6px; "
            "border: 1px solid #0050a0; border-radius: 3px; }"
        )
        self._user_indicator.setToolTip(
            "This tool is configured to run as a different user."
        )
        self._user_indicator.setVisible(False)
        action_row.addWidget(self._user_indicator)

        layout.addLayout(action_row)

        self._status = QLabel("")
        layout.addWidget(self._status)

        return container

    # --- form construction & reorder ------------------------------------

    def _build_custom_menus(self, menu_bar: Any, items: list) -> None:
        """Build custom menus from MenuItemDef list onto a QMenuBar."""
        from PySide6.QtWidgets import QMenu
        from collections import defaultdict
        from ..core.model import MenuItemDef

        # Group items by their menu name.
        groups: dict[str, list[MenuItemDef]] = defaultdict(list)
        for item in items:
            groups[item.menu or "Tools"].append(item)

        for menu_name, menu_items in groups.items():
            menu = menu_bar.addMenu(menu_name)
            self._populate_menu(menu, menu_items)

    def _populate_menu(self, menu: Any, items: list) -> None:
        """Populate a QMenu with MenuItemDef items (recursive for submenus)."""
        import subprocess as _sp
        from PySide6.QtGui import QAction
        from ..core.sanitize import split_command

        for item in items:
            if item.label == "-":
                menu.addSeparator()
                continue
            if item.children:
                sub = menu.addMenu(item.label)
                self._populate_menu(sub, item.children)
                continue
            act = QAction(item.label, self)
            if item.tooltip:
                act.setToolTip(item.tooltip)
            if item.shortcut:
                act.setShortcut(item.shortcut)
            if item.command:
                cmd = item.command
                cwd = self._tool.working_directory or None
                act.triggered.connect(
                    lambda checked=False, c=cmd, d=cwd: _sp.Popen(
                        split_command(c), shell=False, cwd=d,
                    )
                )
            menu.addAction(act)

    def _populate_form_rows(self) -> None:
        """Clear and refill the form area from ``self._tool.params``.

        Walks the tool's ``grouped_params()`` output and creates one
        ``ReorderableParamForm`` per section.  Each section's
        ``layout`` field determines its visual container:

        - ``"collapse"`` — a collapsible ``QGroupBox`` (the default).
        - ``"tab"`` — a page inside a ``QTabWidget``.

        Consecutive tab-layout sections are grouped into a single
        ``QTabWidget``.  A collapse section between two tab runs
        creates separate tab widgets above and below it.

        When the tool has no sections at all, ``grouped_params``
        returns a single ``(None, params)`` tuple and we emit a single
        unframed form.
        """
        # Tear down any existing forms first.
        self._section_forms.clear()
        self._section_boxes.clear()
        self._widgets.clear()
        self._section_tab_widgets: list[QTabWidget] = []
        # Remove all widgets except the trailing stretch.
        while self._form_outer_layout.count() > 1:
            item = self._form_outer_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        groups = self._tool.grouped_params()

        # Track the current tab widget for consecutive tab sections.
        current_tab_widget: QTabWidget | None = None

        def _insert_widget(w: QWidget) -> None:
            self._form_outer_layout.insertWidget(
                self._form_outer_layout.count() - 1, w
            )

        def _flush_tab_widget() -> None:
            """Insert the active tab widget into the layout."""
            nonlocal current_tab_widget
            if current_tab_widget is not None:
                _insert_widget(current_tab_widget)
                current_tab_widget = None

        hidden = set(getattr(self, "_active_hidden_params", []))

        for section, params in groups:
            form = ReorderableParamForm()
            section_key = section.name if section is not None else ""
            form.orderChanged.connect(
                lambda order, key=section_key: self._on_form_reordered(
                    key, list(order)
                )
            )
            for param in params:
                if param.id in hidden:
                    continue  # skip hidden params — their values come from config
                widget = build_widget_for(param)
                self._widgets[param.id] = widget
                label_text = param.label + (" *" if param.required else "")
                form.add_param_row(
                    param.id,
                    label_text,
                    widget,
                    tooltip=param.description,
                )
                widget.valueChanged.connect(self._update_live_cmd)

            self._section_forms[section_key] = form

            is_tab = (
                section is not None
                and getattr(section, "layout", "collapse") == "tab"
            )

            if section is None:
                # No section declared — legacy flat form.
                _flush_tab_widget()
                _insert_widget(form)
            elif is_tab:
                # Start a new tab widget if we're not already in one.
                if current_tab_widget is None:
                    current_tab_widget = QTabWidget()
                    self._section_tab_widgets.append(current_tab_widget)
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setWidget(form)
                scroll.setFrameShape(QScrollArea.Shape.NoFrame)
                current_tab_widget.addTab(
                    scroll, section.name or "(unnamed)"
                )
            else:
                # Collapse section — flush any open tab widget first.
                _flush_tab_widget()
                box = QGroupBox(section.name or "(unnamed)")
                box.setCheckable(True)
                box.setChecked(not section.collapsed)
                box_layout = QVBoxLayout(box)
                box_layout.setContentsMargins(8, 6, 8, 6)
                box_layout.addWidget(form)
                form.setVisible(not section.collapsed)
                box.toggled.connect(
                    lambda checked, key=section_key, f=form:
                        self._on_section_toggled(key, checked, f)
                )
                self._section_boxes[section_key] = box
                _insert_widget(box)

        # Flush any trailing tab widget.
        _flush_tab_widget()

    def _on_section_toggled(
        self, section_name: str, expanded: bool, form: QWidget
    ) -> None:
        """Collapse/expand a section and persist the new state."""
        form.setVisible(expanded)
        # Mirror into the model so save picks it up.
        for sec in self._tool.sections:
            if sec.name == section_name:
                sec.collapsed = not expanded
                break
        if self._file_path and not self._read_only:
            try:
                save_tool(self._tool, self._file_path)
            except Exception:  # noqa: BLE001
                pass  # Collapse state is cosmetic — don't nag on failure.

    def _on_form_reordered(self, section_name: str, new_order: list) -> None:
        """Called after the user drags a form row to a new position.

        Rewrites the slice of ``self._tool.params`` belonging to the
        affected section (identified by ``section_name``), preserving
        the relative order of params in other sections. Persists to
        disk if we have a file path.
        """
        if not new_order:
            return
        id_to_param = {p.id: p for p in self._tool.params}
        try:
            reordered_slice = [id_to_param[pid] for pid in new_order]
        except KeyError:
            return

        moved_ids = set(new_order)
        # Rebuild tool.params:
        # - For params NOT in the moved section, keep their position.
        # - For params IN the moved section, replace each with the
        #   next one from ``reordered_slice`` in order.
        new_params: list[ParamDef] = []
        reorder_iter = iter(reordered_slice)
        for p in self._tool.params:
            if p.id in moved_ids:
                new_params.append(next(reorder_iter))
            else:
                new_params.append(p)
        self._tool.params = new_params

        self._update_live_cmd()
        if self._file_path and not self._read_only:
            try:
                save_tool(self._tool, self._file_path)
                self._status.setText(
                    f"Reordered \u2014 saved to {Path(self._file_path).name}"
                )
            except Exception as e:  # noqa: BLE001 — surface to UI
                self._status.setText(
                    f"<span style='color:#b00020'>Reorder save failed: {e}</span>"
                )
        elif self._read_only:
            self._status.setText("Reordered (not saved — file is read-only).")
        else:
            self._status.setText("Reordered (unsaved — no file path).")

    # --- value extraction ------------------------------------------------

    def _collect_values(self) -> dict[str, Any]:
        """Collect values from visible widgets plus locked hidden-param values.

        Hidden params are not rendered in the form, so their values come
        from the active configuration's stored ``values`` dict instead.
        """
        values = {pid: w.get_value() for pid, w in self._widgets.items()}
        # Merge in hidden param values from the active configuration.
        hidden = getattr(self, "_active_hidden_params", [])
        if hidden:
            cfg = self._cfg_set.active_config()
            for pid in hidden:
                if pid not in values and pid in cfg.values:
                    values[pid] = cfg.values[pid]
        return values

    def _resolve_for_preview(self) -> ResolvedCommand | None:
        try:
            return build_full_argv(
                self._tool,
                self._collect_values(),
                self._extras,
                ignore_required=True,
            )
        except RunnerError as e:
            self._status.setText(f"<span style='color:red'>{e}</span>")
            return None

    def _render_preview_text(self, cmd: ResolvedCommand) -> str:
        """Render argv to a display string, honouring the Full Path toggle.

        When the checkbox is off we swap the first token (the
        executable) for its basename so the preview isn't dominated by
        a long install path. The stored ``_extras`` and the real argv
        used at run time are unaffected — this is purely cosmetic.
        """
        if not cmd.argv:
            return ""
        argv = list(cmd.argv)
        if not self._show_full_path:
            argv[0] = Path(argv[0]).name
        return " ".join(shlex.quote(a) for a in argv)

    def _update_live_cmd(self, *_: Any) -> None:
        """Refresh the editable command preview on the button row.

        Called from widget ``valueChanged`` signals, the Full Path
        toggle, and at the end of ``_on_live_cmd_edited``. Skips when
        the update was caused by another handler (loop guard).

        Cursor position is preserved across the ``setText`` call:
        without this, every keystroke the user types in the middle of
        the line would jump back to the end of the line on the next
        refresh. When the new text is identical to the current text
        (a common no-op path — the user's edit was already canonical)
        we skip the setText entirely to avoid even the subtle cursor
        quirks Qt has around selection state.
        """
        if self._updating:
            return
        try:
            cmd = build_full_argv(
                self._tool,
                self._collect_values(),
                self._extras,
                ignore_required=True,
            )
        except RunnerError as e:
            self._updating = True
            try:
                err_text = f"[template error: {e}]"
                if self._live_cmd.toPlainText() != err_text:
                    self._set_live_cmd_preserving_cursor(err_text)
                self._live_cmd.setToolTip(str(e))
            finally:
                self._updating = False
            return
        text = self._render_preview_text(cmd)
        self._updating = True
        try:
            if self._live_cmd.toPlainText() != text:
                self._set_live_cmd_preserving_cursor(text)
            self._live_cmd.setToolTip(text)
        finally:
            self._updating = False

    def _set_live_cmd_preserving_cursor(self, new_text: str) -> None:
        """Replace the preview text without yanking the cursor.

        ``QPlainTextEdit.setPlainText`` moves the cursor to the start,
        which breaks mid-word editing. We capture the cursor position
        (and any selection) before the replace and restore them
        afterwards, clamping to the new text's length in case
        canonicalization shortened the string.
        """
        tc = self._live_cmd.textCursor()
        old_pos = tc.position()
        had_selection = tc.hasSelection()
        sel_start = tc.selectionStart() if had_selection else -1
        sel_end = tc.selectionEnd() if had_selection else -1

        self._live_cmd.setPlainText(new_text)

        new_len = len(new_text)
        tc2 = self._live_cmd.textCursor()
        if had_selection and sel_start >= 0:
            tc2.setPosition(min(sel_start, new_len))
            tc2.setPosition(
                min(sel_end, new_len), QTextCursor.MoveMode.KeepAnchor
            )
        else:
            tc2.setPosition(min(old_pos, new_len))
        self._live_cmd.setTextCursor(tc2)

    # --- Full Path / Word Wrap checkboxes --------------------------------

    def _on_full_path_toggled(self, checked: bool) -> None:
        self._show_full_path = checked
        self._update_live_cmd()

    def _on_word_wrap_toggled(self, checked: bool) -> None:
        self._live_cmd.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if checked
            else QPlainTextEdit.LineWrapMode.NoWrap
        )

    # --- editable command preview ---------------------------------------

    def _on_live_cmd_text_changed(self) -> None:
        """Wrapper for QPlainTextEdit.textChanged (no argument).

        QPlainTextEdit fires ``textChanged`` for both user and
        programmatic edits, unlike QLineEdit's ``textEdited``. The
        ``_updating`` guard distinguishes the two.
        """
        if self._updating:
            return
        self._on_live_cmd_edited(self._live_cmd.toPlainText())

    def _on_live_cmd_edited(self, text: str) -> None:
        """Parse the user's edit and push changes back into widgets + extras.

        Uses ``reconcile_edit`` to split the edit into known-param
        updates and leftover extras. Each affected widget is updated
        under the ``_updating`` guard so it doesn't trigger another
        preview rebuild while we're still processing this edit.
        """
        if self._updating:
            return
        result = reconcile_edit(
            self._tool, text, self._collect_values()
        )
        if not result.ok:
            # Unclosed quote or similar — leave the user's text alone
            # and just show a hint in the status bar. A subsequent
            # successful edit will re-sync.
            self._status.setText(
                "<span style='color:#b00020'>unparseable edit "
                "(unclosed quote?)</span>"
            )
            return
        self._status.setText("")
        self._updating = True
        try:
            # Push new values into the widgets that changed.
            for pid, value in result.values.items():
                widget = self._widgets.get(pid)
                if widget is None:
                    continue
                if widget.get_value() != value:
                    widget.set_value(value)
            # Update extras state and the extras display.
            self._extras = list(result.extras)
            self._extras_edit.setPlainText(" ".join(self._extras))
        finally:
            self._updating = False
        # Push a history snapshot so Undo/Redo can walk this edit.
        self._push_history_snapshot()
        self._refresh_edit_buttons()
        # NOTE: we deliberately do NOT re-render the preview to the
        # canonical form here. Doing so would fight the user mid-edit
        # by replacing their in-progress text with a canonicalized
        # version (stripped quotes, reordered tokens, normalized
        # basename) and shifting the cursor. The widgets are now in
        # sync via reconcile_edit; any subsequent widget-triggered
        # _update_live_cmd (from Full Path toggle, extras edit, etc.)
        # will re-canonicalize the preview at a natural boundary.

    # --- editable extras box --------------------------------------------

    def _on_extras_edited(self) -> None:
        if self._updating:
            return
        raw = self._extras_edit.toPlainText().strip()
        if raw:
            try:
                self._extras = shlex.split(raw, posix=True)
            except ValueError:
                # Unclosed quote — don't clobber state mid-edit.
                return
        else:
            self._extras = []
        self._update_live_cmd()

    # --- run button ------------------------------------------------------

    def is_running(self) -> bool:
        """True if a child process is currently live for this tool.

        Used by :class:`MainWindow` to decide whether it's safe to
        close, refresh, or drop a cached runner view.
        """
        return self._thread is not None

    def _start_run(self) -> None:
        if self._thread is not None:
            return  # run already in progress

        # --- input sanitization ---
        # Always sanitize form field values. Additionally sanitize the
        # extras box and command-line editor text when the
        # injection_protection_on_editor permission is enabled.
        from ..core.model import ParamType
        from ..core.permissions import get_app_permissions

        values = self._collect_values()
        path_ids = {
            p.id for p in self._tool.params
            if p.type is ParamType.PATH
        }
        labels = {p.id: p.label for p in self._tool.params}
        warnings = sanitize_all_values(
            {k: str(v) for k, v in values.items() if v},
            path_fields=path_ids,
            labels=labels,
        )

        # Check if editor injection protection is enabled.
        perms = get_app_permissions()
        if self._file_path:
            from ..core.permissions import load_permissions
            perms = load_permissions(file_path=self._file_path)
        editor_protection = perms.can(
            "injection_protection_on_editor"
        )

        if editor_protection:
            # Also sanitize extras and command-line editor content.
            from ..core.sanitize import sanitize_value
            for token in self._extras:
                r = sanitize_value(token, field_label="Extra arguments")
                warnings.extend(r.warnings)
            cmd_text = self._live_cmd.toPlainText().strip()
            if cmd_text:
                r = sanitize_value(cmd_text, field_label="Command line")
                warnings.extend(r.warnings)

        if warnings:
            detail = "\n".join(f"\u2022 {w}" for w in warnings)
            if not self._show_injection_warning(
                detail, editor_protection, perms
            ):
                return

        try:
            # Thread per-configuration env overrides into the resolve
            # so the child process inherits tool + config env layers.
            cfg = (
                self._cfg_set.active_config()
                if self._cfg_set.configurations
                else None
            )
            # Load global env from application settings.
            from ..core.app_settings import get_settings
            from .settings_dialog import (
                load_global_env, global_env_overrides_tool,
                load_global_path_prepend, global_path_overrides_tool,
            )
            _qs = get_settings()
            _g_env = load_global_env(_qs)
            _g_env_override = global_env_overrides_tool(_qs)
            _g_path = load_global_path_prepend(_qs)
            _g_path_override = global_path_overrides_tool(_qs)

            cmd = build_full_argv(
                self._tool,
                self._collect_values(),
                self._extras,
                config_env=cfg.env if cfg else None,
                config_path_prepend=cfg.path_prepend if cfg else None,
                global_env=_g_env or None,
                global_env_overrides=_g_env_override,
                global_path_prepend=_g_path or None,
                global_path_overrides=_g_path_override,
            )
        except RunnerError as e:
            QMessageBox.warning(self, "Validation error", str(e))
            return

        # --- credential prompt (run-as-different-user) ---
        credentials: tuple[str, str, str] | None = None
        if cfg is not None and cfg.prompt_credentials:
            credentials = self._obtain_credentials(cfg)
            if credentials is None:
                # User cancelled the credential dialog.
                return

        if credentials is not None:
            user_display = credentials[0]
            if credentials[2]:  # domain
                user_display = f"{credentials[2]}\\{credentials[0]}"
            self._append_line(f"$ (as {user_display}) {cmd.display()}\n")
        else:
            self._append_line(f"$ {cmd.display()}\n")

        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._btn_stop.setText("Stop")
        self._status.setText("Running…")

        self._thread = QThread(self)
        self._worker = _RunWorker(cmd, credentials=credentials)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.stdoutLine.connect(self._on_stdout)
        self._worker.stderrLine.connect(self._on_stderr)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()
        self.runningChanged.emit(self._file_path or "", True)

    def _obtain_credentials(
        self, cfg: Configuration
    ) -> tuple[str, str, str] | None:
        """Get credentials for run-as-user, from cache or dialog.

        Returns ``(username, password, domain)`` or ``None`` if the
        user cancels the prompt.
        """
        store = get_session_store()
        store_key = self._credential_store_key()

        # Check the session cache first.
        cached = store.get(store_key)
        if cached is not None:
            self._update_user_indicator(cached.username, cached.domain)
            return (cached.username, cached.get_password(), cached.domain)

        # Show the credential dialog.
        from .credential_dialog import CredentialDialog

        dlg = CredentialDialog(
            tool_name=self._tool.name,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None

        username = dlg.username()
        password = dlg.password()
        domain = dlg.domain()

        # Cache if the user asked to remember.
        if dlg.remember():
            store.put(
                store_key,
                StoredCredential.create(username, password, domain),
            )

        self._update_user_indicator(username, domain)
        return (username, password, domain)

    def _credential_store_key(self) -> str:
        """Build the session-store key for this tool + active config."""
        path = self._file_path or "<unsaved>"
        cfg_name = self._cfg_set.active
        return f"{path}::{cfg_name}"

    def _update_user_indicator(
        self, username: str = "", domain: str = ""
    ) -> None:
        """Show or hide the user indicator label on the action bar."""
        if username:
            display = f"{domain}\\{username}" if domain else username
            self._user_indicator.setText(f"\U0001f464 Run as: {display}")
            self._user_indicator.setVisible(True)
        else:
            self._user_indicator.setVisible(False)

    def _refresh_user_indicator(self) -> None:
        """Update the user indicator from the session credential store.

        Called when the active configuration changes to reflect whether
        cached credentials exist for the new config.
        """
        cfg = self._cfg_set.active_config()
        if not cfg.prompt_credentials:
            self._user_indicator.setVisible(False)
            return
        store = get_session_store()
        cached = store.get(self._credential_store_key())
        if cached is not None:
            self._update_user_indicator(cached.username, cached.domain)
        else:
            # Show a hint that credentials will be prompted.
            self._user_indicator.setText("\U0001f464 Run as: (will prompt)")
            self._user_indicator.setVisible(True)

    def _stop_run(self) -> None:
        """Ask the live child process to stop. Escalates terminate→kill
        on a second press."""
        if self._worker is None:
            return
        level = self._worker.stop()
        if level == 0:
            # Nothing to stop — process either hasn't started yet
            # (rare race) or already exited. Disable and move on.
            self._btn_stop.setEnabled(False)
            return
        if level == 1:
            self._btn_stop.setText("Kill")
            self._status.setText("Stopping…")
            self._append_line(
                "[stop requested — sent terminate]",
                color=QColor("#666666"),
            )
        elif level == 2:
            self._btn_stop.setEnabled(False)
            self._status.setText("Killing…")
            self._append_line(
                "[kill sent]",
                color=QColor("#666666"),
            )

    def _on_stdout(self, line: str) -> None:
        self._append_line(line)

    def _on_stderr(self, line: str) -> None:
        self._append_line(line, color=QColor("#b00020"))
        self._stderr_buffer.append(line)
        if len(self._stderr_buffer) > 30:
            self._stderr_buffer = self._stderr_buffer[-30:]

    def _on_finished(self, exit_code: int, duration: float) -> None:
        self._append_line(
            f"[exit {exit_code} in {duration:.2f}s]",
            color=QColor("#666666"),
        )
        # Tear down thread.
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
        self._thread = None
        self._worker = None
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._btn_stop.setText("Stop")
        self._status.setText(
            f"Finished — exit {exit_code} in {duration:.2f}s"
        )
        self.runningChanged.emit(self._file_path or "", False)

        # Popup dialogs when output pane is hidden.
        vis = self._cfg_set.active_config().ui_visibility
        if exit_code != 0 and vis.popup_on_error:
            stderr_text = "".join(self._stderr_buffer[-20:]).strip()
            QMessageBox.critical(
                self,
                f"{self._tool.name} — Error",
                f"Process exited with code {exit_code}"
                f" in {duration:.2f}s.\n\n"
                + (stderr_text if stderr_text else "(no stderr output)"),
            )
        elif exit_code == 0 and vis.popup_on_success:
            QMessageBox.information(
                self,
                f"{self._tool.name} — Success",
                f"Completed successfully in {duration:.2f}s.",
            )
        self._stderr_buffer.clear()

    # --- helpers ---------------------------------------------------------

    def _append_line(self, line: str, *, color: QColor | None = None) -> None:
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if color is not None:
            fmt = cursor.charFormat()
            fmt.setForeground(color)
            cursor.setCharFormat(fmt)
        cursor.insertText(line + "\n")
        # Reset format so the next plain line isn't colored.
        if color is not None:
            cursor.setCharFormat(self._output.currentCharFormat())
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    def _show_injection_warning(
        self,
        detail: str,
        editor_protection: bool,
        perms: Any,
    ) -> bool:
        """Show the injection warning dialog. Returns True to proceed."""
        from PySide6.QtWidgets import QApplication

        if editor_protection:
            # Permission file present — simple warning.
            reply = QMessageBox.warning(
                self,
                "Suspicious input detected",
                "The following inputs contain potentially unsafe "
                "characters:\n\n" + detail + "\n\n"
                "Do you want to continue anyway?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            return reply == QMessageBox.StandardButton.Yes

        # Permission file missing — show instructions with path and copy button.
        perm_dir = perms.app_permissions_dir or "(permissions folder not found)"
        filename = "injection_protection_on_editor"

        dlg = QDialog(self)
        dlg.setWindowTitle("Suspicious input detected")
        dlg.setMinimumWidth(480)
        lay = QVBoxLayout(dlg)

        lay.addWidget(QLabel(
            "The following inputs contain potentially unsafe characters:\n"
        ))
        detail_label = QLabel(detail)
        detail_label.setWordWrap(True)
        lay.addWidget(detail_label)

        lay.addWidget(QLabel(
            "\nTo enable injection protection on the command line "
            "editor and extra arguments (blocking these at the "
            "source), add this file to your permissions folder:"
        ))

        # Copyable filename.
        file_row = QHBoxLayout()
        file_field = QLineEdit(filename)
        file_field.setReadOnly(True)
        file_row.addWidget(file_field, stretch=1)
        btn_copy_name = QPushButton("Copy name")
        btn_copy_name.clicked.connect(
            lambda: QApplication.clipboard().setText(filename)
        )
        file_row.addWidget(btn_copy_name)
        lay.addLayout(file_row)

        # Permissions path with open-folder button.
        path_row = QHBoxLayout()
        path_field = QLineEdit(perm_dir)
        path_field.setReadOnly(True)
        path_row.addWidget(path_field, stretch=1)
        btn_open_folder = QPushButton("Open folder")
        btn_open_folder.clicked.connect(
            lambda: self._open_folder_in_explorer(perm_dir)
        )
        path_row.addWidget(btn_open_folder)
        lay.addLayout(path_row)

        lay.addWidget(QLabel("\nDo you want to continue anyway?"))

        from PySide6.QtWidgets import QDialogButtonBox
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes
            | QDialogButtonBox.StandardButton.No
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        return dlg.exec() == QDialog.DialogCode.Accepted

    @staticmethod
    def _open_folder_in_explorer(path: str) -> None:
        """Open a folder in the system file browser."""
        import subprocess as _sp
        import sys as _sys
        from pathlib import Path as _Path
        p = _Path(path)
        if not p.exists():
            return
        if _sys.platform == "win32":
            _sp.Popen(["explorer", str(p)])
        elif _sys.platform == "darwin":
            _sp.Popen(["open", str(p)])
        else:
            _sp.Popen(["xdg-open", str(p)])

    def _copy_argv(self) -> None:
        cmd = self._resolve_for_preview()
        if cmd is None:
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(cmd.display())
        self._status.setText("Copied argv to clipboard.")

    # --- edit history (undo / redo / reset) -----------------------------

    def _snapshot(self) -> tuple[dict, list[str]]:
        """Take a snapshot of current widget values + extras."""
        return (dict(self._collect_values()), list(self._extras))

    def _push_history_snapshot(self) -> None:
        """Push the current state onto the undo stack.

        Truncates any redo tail past the current index — the usual
        "typing after undo forks the timeline" behavior. No-ops if the
        state is identical to the current top of stack (avoids filling
        history with duplicate snapshots from redundant refreshes).
        """
        if self._restoring_snapshot:
            return
        snap = self._snapshot()
        if (
            self._history_index >= 0
            and self._history_index < len(self._history)
            and self._history[self._history_index] == snap
        ):
            return
        # Drop redo tail.
        del self._history[self._history_index + 1:]
        self._history.append(snap)
        self._history_index = len(self._history) - 1

    def _apply_snapshot(self, snap: tuple[dict, list[str]]) -> None:
        """Restore widgets + extras from a snapshot, then refresh preview."""
        values, extras = snap
        self._restoring_snapshot = True
        self._updating = True
        try:
            for pid, value in values.items():
                widget = self._widgets.get(pid)
                if widget is None:
                    continue
                if widget.get_value() != value:
                    widget.set_value(value)
            self._extras = list(extras)
            self._extras_edit.setPlainText(" ".join(self._extras))
        finally:
            self._updating = False
            self._restoring_snapshot = False
        self._update_live_cmd()

    def _undo_edit(self) -> None:
        if self._history_index <= 0:
            return
        self._history_index -= 1
        self._apply_snapshot(self._history[self._history_index])
        self._refresh_edit_buttons()
        self._status.setText("Undid last edit.")

    def _redo_edit(self) -> None:
        if self._history_index >= len(self._history) - 1:
            return
        self._history_index += 1
        self._apply_snapshot(self._history[self._history_index])
        self._refresh_edit_buttons()
        self._status.setText("Redid edit.")

    def _reset_edits(self) -> None:
        """Discard every manual edit, restoring the initial snapshot."""
        if not self._history:
            return
        # If we're already at the initial state, nothing to do.
        if self._history_index == 0:
            self._status.setText("Nothing to reset.")
            return
        reply = QMessageBox.question(
            self,
            "Reset manual edits?",
            "Discard every manual edit to the command line and "
            "restore the form defaults?\n\nThis cannot be undone "
            "beyond what's in the undo history.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        # Apply the very first snapshot without wiping history — this
        # lets the user still Redo back to where they were if they
        # change their mind.
        self._history_index = 0
        self._apply_snapshot(self._history[0])
        self._refresh_edit_buttons()
        self._status.setText("Reset to initial defaults.")

    def _clear_output(self) -> None:
        if not self._output.toPlainText():
            return
        reply = QMessageBox.question(
            self,
            "Clear output?",
            "Clear the output pane?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._output.clear()
        self._status.setText("Output cleared.")

    def _refresh_edit_buttons(self) -> None:
        """Enable/disable Undo/Redo/Reset based on history cursor."""
        can_undo = self._history_index > 0
        can_redo = self._history_index < len(self._history) - 1
        self._btn_undo.setEnabled(can_undo)
        self._btn_redo.setEnabled(can_redo)
        self._btn_reset.setEnabled(can_undo)

    # --- configurations (sidecar) ---------------------------------------

    def _load_or_init_configs(self) -> None:
        """Load the sidecar file, or build an in-memory default set."""
        if self._file_path:
            try:
                loaded = load_configs(self._file_path)
            except Exception:  # noqa: BLE001 — corrupt sidecar shouldn't crash
                loaded = None
            if loaded is not None:
                self._cfg_set = loaded
                # Apply the active configuration's values to the form.
                self._apply_configuration(self._cfg_set.active_config())
                return
        # Fresh set seeded with the current widget defaults.
        self._cfg_set = default_configuration_set(self._collect_values())

    def _refresh_cfg_combo(self) -> None:
        """Repopulate the configuration combobox from the current set."""
        self._cfg_loading = True
        try:
            self._cfg_combo.clear()
            for c in self._cfg_set.configurations:
                self._cfg_combo.addItem(c.name)
            # Select the active entry.
            idx = self._cfg_combo.findText(self._cfg_set.active)
            if idx >= 0:
                self._cfg_combo.setCurrentIndex(idx)
        finally:
            self._cfg_loading = False

    def _refresh_cfg_buttons(self) -> None:
        """Enable/disable configuration buttons based on state.

        - The entire bar is disabled when there is no file path
          (nowhere to write the sidecar).
        - All write-capable buttons are also disabled when the file
          is read-only (``_read_only`` flag).
        - Delete is additionally disabled when only one configuration
          remains — the set must always have at least one entry.
        """
        has_path = self._file_path is not None
        can_write = has_path and not self._read_only
        # Combo stays enabled even for read-only — user can switch
        # configs to view them (just won't persist the active pointer).
        self._cfg_combo.setEnabled(has_path)
        self._btn_cfg_save.setEnabled(can_write)
        self._btn_cfg_save_as.setEnabled(can_write)
        self._btn_cfg_edit.setEnabled(can_write)
        self._btn_cfg_env.setEnabled(can_write)
        self._btn_cfg_visibility.setEnabled(can_write)
        self._btn_cfg_delete.setEnabled(
            can_write and len(self._cfg_set.configurations) > 1
        )
        self._chk_prompt_creds.setEnabled(can_write)

    def _save_cfg_sidecar(self) -> bool:
        """Persist the sidecar file. Returns True on success."""
        if not self._file_path or self._read_only:
            return False
        try:
            save_configs(self._file_path, self._cfg_set)
            return True
        except Exception as e:  # noqa: BLE001
            self._status.setText(
                f"<span style='color:#b00020'>Config save failed: {e}</span>"
            )
            return False

    def _apply_configuration(self, cfg: Configuration) -> None:
        """Push a configuration's values + extras into the widgets.

        Also applies UI visibility and hidden-param settings from the
        configuration. If the set of hidden params differs from what
        was previously active, the form is rebuilt so hidden widgets
        are removed (and their locked values are fed to
        ``_collect_values`` instead).
        """
        # Detect whether we need a form rebuild (hidden params changed).
        # Hidden params only take effect in standalone mode; in docked
        # mode all params remain visible so the user can edit everything.
        old_hidden = getattr(self, "_active_hidden_params", [])
        new_hidden = cfg.hidden_params if self._standalone_mode else []

        if sorted(old_hidden) != sorted(new_hidden):
            self._active_hidden_params = list(new_hidden)
            # Rebuild the form — _populate_form_rows reads _active_hidden_params.
            self._populate_form_rows()

        self._updating = True
        try:
            for pid, value in cfg.values.items():
                widget = self._widgets.get(pid)
                if widget is None:
                    continue
                widget.set_value(value)
            self._extras = list(cfg.extras)
            self._extras_edit.setPlainText(" ".join(self._extras))
        finally:
            self._updating = False
        self._update_live_cmd()
        self._apply_visibility(cfg.ui_visibility)
        # Sync the credential prompt checkbox without triggering toggled.
        self._chk_prompt_creds.blockSignals(True)
        self._chk_prompt_creds.setChecked(cfg.prompt_credentials)
        self._chk_prompt_creds.blockSignals(False)
        self._refresh_user_indicator()

    def _apply_visibility(self, vis: UIVisibility) -> None:
        """Show/hide UI elements according to the UIVisibility flags.

        Only takes effect when ``_standalone_mode`` is True. In docked
        (IDE) mode all controls remain visible so the user can always
        switch configurations and access every feature. The
        ``visibilityChanged`` signal still fires regardless so the
        StandaloneWindow / MainWindow can react.

        ``config_bar`` is a string: "hidden", "read", or "readwrite".
        - "hidden" — entire config bar hidden
        - "read" — combo visible (switch configs), write buttons hidden
        - "readwrite" — full config bar
        The Visibility button is always hidden in standalone mode.
        """
        if self._standalone_mode:
            self._extras_box.setVisible(vis.extras_box)
            self._cmd_box.setVisible(vis.command_line)
            self._btn_preview.setVisible(vis.copy_argv)
            self._btn_clear_output.setVisible(
                vis.clear_output and vis.output_pane
            )
            self._btn_cfg_env.setVisible(vis.env_button)

            # Config bar mode.
            cb_mode = vis.config_bar  # "hidden", "read", "readwrite"
            if cb_mode == "hidden":
                self._cfg_widget.setVisible(False)
            else:
                self._cfg_widget.setVisible(True)
                is_rw = cb_mode == "readwrite"
                self._btn_cfg_save.setVisible(is_rw)
                self._btn_cfg_save_as.setVisible(is_rw)
                self._btn_cfg_delete.setVisible(is_rw)
                self._btn_cfg_edit.setVisible(is_rw)
                self._btn_cfg_env.setVisible(is_rw and vis.env_button)
                self._chk_prompt_creds.setVisible(is_rw)

            # Visibility button never shows in standalone mode —
            # the user edits visibility from the IDE, not standalone.
            self._btn_cfg_visibility.setVisible(False)

        # Output pane + tools sidebar are controlled by the parent
        # window; emit the full visibility object so it can decide.
        self.visibilityChanged.emit(vis)

    def _on_cfg_combo_changed(self, _idx: int) -> None:
        if self._cfg_loading:
            return
        name = self._cfg_combo.currentText()
        if not name:
            return
        cfg = self._cfg_set.find(name)
        if cfg is None:
            return
        self._cfg_set.active = name
        self._apply_configuration(cfg)
        # Save the active-pointer change so it sticks across sessions.
        self._save_cfg_sidecar()
        # Reset the undo history to the newly-loaded configuration —
        # the old history is tied to the previous configuration and
        # would be confusing to walk.
        self._history.clear()
        self._history_index = -1
        self._push_history_snapshot()
        self._refresh_edit_buttons()
        self._status.setText(f"Loaded configuration '{name}'.")

    def _cfg_save(self) -> None:
        """Overwrite the active configuration with the current state."""
        if not self._file_path:
            return
        cfg = self._cfg_set.active_config()
        cfg.values = dict(self._collect_values())
        cfg.extras = list(self._extras)
        if self._save_cfg_sidecar():
            self._status.setText(f"Saved configuration '{cfg.name}'.")

    def _cfg_save_as(self) -> None:
        """Prompt for a new name and create a new configuration."""
        if not self._file_path:
            return
        name, ok = QInputDialog.getText(
            self,
            "Save configuration as",
            "New configuration name:",
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if is_reserved_config_name(name):
            QMessageBox.warning(
                self,
                "Reserved name",
                f"The name '{name}' is reserved by ScripTree and "
                "cannot be used for user configurations.",
            )
            return
        if self._cfg_set.find(name) is not None:
            reply = QMessageBox.question(
                self,
                "Overwrite configuration?",
                f"A configuration named '{name}' already exists. "
                "Overwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            existing = self._cfg_set.find(name)
            assert existing is not None
            existing.values = dict(self._collect_values())
            existing.extras = list(self._extras)
        else:
            self._cfg_set.configurations.append(
                Configuration(
                    name=name,
                    values=dict(self._collect_values()),
                    extras=list(self._extras),
                )
            )
        self._cfg_set.active = name
        if self._save_cfg_sidecar():
            self._refresh_cfg_combo()
            self._refresh_cfg_buttons()
            self._status.setText(f"Saved configuration '{name}'.")

    def _cfg_delete(self) -> None:
        """Remove the active configuration after confirmation."""
        if len(self._cfg_set.configurations) <= 1:
            return
        cfg = self._cfg_set.active_config()
        reply = QMessageBox.question(
            self,
            "Delete configuration?",
            f"Delete configuration '{cfg.name}'? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._cfg_set.configurations = [
            c for c in self._cfg_set.configurations if c.name != cfg.name
        ]
        # Move active to the first remaining entry and re-apply it.
        new_active = self._cfg_set.configurations[0]
        self._cfg_set.active = new_active.name
        self._apply_configuration(new_active)
        if self._save_cfg_sidecar():
            self._refresh_cfg_combo()
            self._refresh_cfg_buttons()
            self._status.setText(f"Deleted configuration '{cfg.name}'.")

    def _cfg_edit_env(self) -> None:
        """Open the env-editor popup for the active configuration.

        The dialog edits a copy of the configuration's env/path_prepend
        overrides; on Accept the new values are written back to the
        active Configuration and persisted to the sidecar. Requires a
        file path (same rule as the other configuration buttons).
        """
        if not self._file_path:
            return
        cfg = self._cfg_set.active_config()
        dlg = EnvEditorDialog(
            cfg.env,
            cfg.path_prepend,
            title=f"Environment — {cfg.name}",
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        cfg.env = dlg.result_env()
        cfg.path_prepend = dlg.result_paths()
        if self._save_cfg_sidecar():
            self._status.setText(
                f"Updated environment for '{cfg.name}'."
            )

    def _cfg_edit(self) -> None:
        """Open the rename/reorder popup and apply the result."""
        if not self._file_path:
            return
        dlg = ConfigurationEditDialog(self._cfg_set, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_order = dlg.result_configurations()
        if not new_order:
            return
        # Preserve active selection when possible — match by the
        # *old* name if it still exists in the new list, otherwise
        # fall back to the first entry.
        old_active_in_new = None
        for c in new_order:
            if c.name == self._cfg_set.active:
                old_active_in_new = c.name
                break
        self._cfg_set.configurations = new_order
        self._cfg_set.active = old_active_in_new or new_order[0].name
        if self._save_cfg_sidecar():
            self._refresh_cfg_combo()
            self._refresh_cfg_buttons()
            self._status.setText("Configurations updated.")

    def _cfg_edit_visibility(self) -> None:
        """Open the visibility editor dialog for the active configuration.

        The dialog (Phase 3) lets the user toggle UI element visibility
        and mark individual params as hidden with locked values. On
        Accept the new UIVisibility and hidden_params are written back
        to the active Configuration and persisted to the sidecar.
        """
        if not self._file_path:
            return
        cfg = self._cfg_set.active_config()
        # Import here to avoid circular imports — the editor is a
        # separate module created in Phase 3.
        try:
            from .visibility_editor import VisibilityEditorDialog
        except ImportError:
            QMessageBox.information(
                self,
                "Not yet available",
                "The visibility editor will be available after Phase 3.",
            )
            return
        dlg = VisibilityEditorDialog(
            cfg.ui_visibility,
            cfg.hidden_params,
            self._tool.params,
            cfg.values,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        cfg.ui_visibility = dlg.result_visibility()
        cfg.hidden_params = dlg.result_hidden_params()
        # Merge locked values into cfg.values so hidden params have
        # their locked defaults available for _collect_values().
        locked = dlg.result_locked_values()
        for pid, val in locked.items():
            cfg.values[pid] = val
        if self._save_cfg_sidecar():
            self._apply_configuration(cfg)
            self._status.setText(
                f"Updated visibility for '{cfg.name}'."
            )

    def _on_prompt_creds_toggled(self, checked: bool) -> None:
        """Handle the 'Prompt for alternate credentials' checkbox toggle."""
        cfg = self._cfg_set.active_config()
        cfg.prompt_credentials = checked
        self._save_cfg_sidecar()
        # When unchecked, clear any cached credentials for this config
        # so the next check starts fresh.
        if not checked:
            store = get_session_store()
            store.remove(self._credential_store_key())
            self._update_user_indicator()
        else:
            self._refresh_user_indicator()

    # --- public interface for standalone / external callers ----------------

    def apply_named_configuration(self, config_name: str) -> bool:
        """Switch to a named configuration and apply it.

        Returns True if the configuration was found and applied.
        Used by StandaloneWindow and CLI ``-configuration`` flag.
        """
        cfg = self._cfg_set.find(config_name)
        if cfg is None:
            return False
        self._cfg_set.active = config_name
        self._cfg_loading = True
        try:
            idx = self._cfg_combo.findText(config_name)
            if idx >= 0:
                self._cfg_combo.setCurrentIndex(idx)
        finally:
            self._cfg_loading = False
        self._apply_configuration(cfg)
        return True

    @property
    def active_visibility(self) -> UIVisibility:
        """The UIVisibility of the currently active configuration."""
        return self._cfg_set.active_config().ui_visibility

    @property
    def read_only(self) -> bool:
        """True when the file is not writable and editing is disabled."""
        return self._read_only
