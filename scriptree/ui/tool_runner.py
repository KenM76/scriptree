"""Runtime view of a tool: form on top, extras + output below, Run button.

## For humans

This is what the user interacts with day-to-day. Given a ``ToolDef``
(loaded from a ``.scriptree`` file), it renders a form using the
widgets module, and when the user clicks Run it dispatches to
``core.runner.spawn_streaming`` in a worker thread and streams the
child process output to a text pane.

### Editable command preview

The button row carries a "Show full path" checkbox, a "Word wrap"
checkbox, and an editable ``QPlainTextEdit`` that always shows the
full resolved argv (GUI params plus user-added extras). Editing it
calls ``reconcile_edit`` which
parses the edit back into widget values and a list of "extras" —
tokens that don't fit any template entry. Extras are also displayed
in a small box above the output pane, where they can be edited
directly.

### Loop guard

Two code paths update the same widgets and the same preview field:
the user typing into a form widget (``valueChanged`` -> preview
rebuild) and the user typing into the preview (``textEdited`` ->
widget rebuild). A ``_updating`` flag guards against re-entry so
setting widget values programmatically doesn't fire another
reconcile pass.

## For maintainers / LLMs

- ``build_full_argv`` is pure and deterministic and is called on
  every value change inside ``_update_live_cmd``. Providers must
  NEVER run during it — dynamic providers only run during
  form-population/refresh (``_init_providers`` / ``_run_provider`` /
  Refresh-all). Do not move any provider call into the argv path or
  the preview becomes non-deterministic and can block on subprocesses.
- ``_update_live_cmd`` no-ops twice on purpose: (1) when
  ``self._updating`` (loop guard re-entry) and (2) ``if not
  hasattr(self, "_live_cmd")`` — provider on_open population fires
  ``valueChanged`` *before* the preview widget is constructed.
  ``__init__`` does one definitive ``_update_live_cmd()`` after the
  view is built. Removing the ``hasattr`` guard crashes on load.
- The loop guard is the bare ``self._updating`` flag set/cleared in
  try/finally around every programmatic ``set_value``/``set_choices``
  and preview ``setPlainText``. New widget-mutating code must wrap
  itself in the same flag or it self-triggers a reconcile storm.
- Preview text is replaced via ``_set_live_cmd_preserving_cursor``,
  which captures + clamps cursor/selection across ``setPlainText``
  (Qt resets the cursor to 0). Identical-text writes are skipped
  entirely. Keep the no-op-skip and clamp when editing preview I/O.
- Provider orchestration: ``_init_providers`` topo-sorts via
  ``provider_run_order`` (``depends_on`` must be acyclic) and runs
  ``on_open``/``on_change`` immediately; ``on_change`` cascades are
  debounced ~250 ms through per-param ``QTimer``s; Refresh-all and
  per-field ⟳ buttons bypass cache. Providers fail SOFT: error
  tooltip + "(no items)" for choice widgets, form stays usable, Run
  blocked only if the param is required.
- ``_populate_form_rows`` (hence ``_init_providers``) can re-run on a
  config change that alters ``hidden_params`` in standalone mode. It
  rebuilds widgets (old ones ``deleteLater``) and reassigns
  ``_provider_debounce`` fresh; old QTimers parented to ``self``
  outlive their dead dep widgets (benign, never re-fire). Per-param
  ``_provider_debounce[p.id]`` keeps only the last dep's timer though
  every dep is wired to its own timer — see the bug audit.
- Run lifecycle: ``_start_run`` early-returns if ``self._thread is
  not None`` (single concurrent run). Worker lives in ``QThread`` via
  ``moveToThread``; ``finished`` is a queued signal so
  ``_on_finished`` runs on the GUI thread and may safely
  ``thread.quit(); thread.wait(2000)``. ``_stop_run`` escalates
  terminate→kill across two presses (level 1/2). Always clear
  ``_thread``/``_worker`` to ``None`` in ``_on_finished`` or the next
  Run is blocked forever.
- ``_start_run`` re-checks the ``run_tools`` capability at call time
  (keyboard/programmatic invocations bypass the greyed button).
  Sanitization always runs on form values; extras + command-editor
  text are only sanitized when ``injection_protection_on_editor`` is
  granted. Keep capability checks call-time, not construction-time.
- Missing-executable recovery (``_offer_missing_executable_recovery``
  / ``_apply_path_scope_choice``) may rewrite the .scriptree and
  PATH/registry; save failures are collected and surfaced in a
  warning box — never swallow them. ``_recovery_argv0_override`` pins
  argv[0] for the current run only to dodge propagation races.
"""
from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QSize, QThread, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
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
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.configs import (
    Configuration,
    ConfigurationSet,
    UIVisibility,
    add_location_to_personal,
    default_configuration_set,
    is_reserved_config_name,
    load_configs,
    load_personal_configs_for,
    next_available_suffix_num,
    personal_configs_path,
    save_configs,
    save_personal_configs,
    save_personal_configs_at,
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


# Pre-compiled ANSI / VT escape stripper.
#
# Even though run_scriptree.py sets NO_COLOR=1 / TERM=dumb / CLICOLOR=0
# / FORCE_COLOR=0 in os.environ so well-behaved CLIs skip color, some
# tools either ignore those env vars or are explicitly invoked with
# ``--color=always``. Without stripping, ScripTree's QPlainTextEdit
# renders the escape codes as literal text (the ESC byte 0x1B becomes
# "@" in most monospace fonts, producing output like "@[31m993K@[0m").
#
# The pattern matches:
#   - CSI (Control Sequence Introducer):   ESC [ ... <terminator>
#   - OSC (Operating System Command):      ESC ] ... BEL or ESC \
#   - Single-character ESC sequences:      ESC <char>
#
# This catches the common SGR (color) sequences plus cursor-movement
# and clear-screen codes some tools emit. Lone ESC bytes (without a
# valid suffix) are also stripped to keep them from rendering as "@".
_ANSI_RE = re.compile(
    r"\x1B(?:"
    r"\[[0-?]*[ -/]*[@-~]"          # CSI
    r"|\][^\x07\x1B]*(?:\x07|\x1B\\)"  # OSC, terminated by BEL or ST
    r"|[@-Z\\-_]"                    # 7-bit single-char (Fp/Fe/nF)
    r")"
)


def _strip_ansi(s: str) -> str:
    """Remove ANSI / VT escape sequences from ``s``.

    Returns the input unchanged when there are no escapes — the
    ``"\\x1B" not in s`` short-circuit makes the common case (clean
    text from tools that honored NO_COLOR) free.
    """
    if "\x1b" not in s:
        return s
    return _ANSI_RE.sub("", s)


class _FormPanelContainer(QWidget):
    """The outer container of the form panel.

    Subclasses ``QWidget`` solely to provide a real C++ virtual
    override of ``minimumSizeHint``.  Earlier attempts assigned a
    function to ``container.minimumSizeHint`` at the instance level,
    which works for pure-Python callers but is silently ignored by
    Qt's C++ machinery -- ``QWidget::minimumSizeHint()`` is a virtual
    method called through the vtable, and PySide6 only routes calls
    back to Python when the method is declared on a subclass at
    class-definition time.  QtAds asks Qt directly, sees the default
    (which returns 0/0 for an untouched ``QWidget``), and freely
    shrinks the form dock below the bottom band's natural height
    in standalone mode -- exactly the user-reported failure
    ("developer mode works, standalone doesn't").

    The override reads the current sizeHints of the header section
    and bottom band so it stays accurate as those widgets change
    (e.g. extras section expanded vs collapsed, action buttons
    added).  When the references are unset the override falls
    through to the default -- safe during partial construction.
    """

    def __init__(self) -> None:
        super().__init__()
        self._header_ref: QWidget | None = None
        self._bottom_band_ref: QWidget | None = None
        self._form_floor: int = 60
        # Expand to fill the viewport rather than demanding the
        # children's full preferred sum (which makes QtAds wrap us
        # in a scroll area).  Combined with sizeHint==minimumSizeHint
        # below, this lets the form_panel shrink to fit the dock
        # viewport while still claiming a sane minimum.
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.MinimumExpanding,
        )

    def set_size_refs(
        self,
        *,
        header: QWidget,
        bottom_band: QWidget,
        form_floor: int = 60,
    ) -> None:
        """Install references so ``minimumSizeHint`` can read live."""
        self._header_ref = header
        self._bottom_band_ref = bottom_band
        self._form_floor = int(form_floor)
        # Trigger an immediate re-layout pass so the new minimum
        # propagates upward to whatever container (QStackedWidget /
        # QtAds dock area) is asking.
        self.updateGeometry()

    def minimumSizeHint(self) -> QSize:  # noqa: N802 -- Qt naming
        base = super().minimumSizeHint()
        if self._header_ref is None or self._bottom_band_ref is None:
            return base
        h = (
            self._header_ref.sizeHint().height()
            + self._form_floor
            + self._bottom_band_ref.sizeHint().height()
        )
        return QSize(base.width(), max(base.height(), h))

    def sizeHint(self) -> QSize:  # noqa: N802 -- Qt naming
        """Return ``minimumSizeHint`` exactly as the preferred size.

        v0.8.0a19 -- this override is what stops QtAds from wrapping
        the whole dock in its own QScrollArea, which is what made
        the cfg row + Run button get "scrolled away" in standalone
        mode.

        QtAds wraps the dock's content widget in a QScrollArea with
        ``widgetResizable=True`` -- meaning the contained widget gets
        its own preferred (``sizeHint``) HEIGHT, not the viewport
        height, and the scroll area scrolls if that's larger than
        the viewport.  Without this override, ``QWidget.sizeHint``
        sums every child layout item's sizeHint -- including the
        parameters scroll area, whose inner ``ReorderableParamForm``
        reports the FULL height of all rows.  For a tool with 16
        params + a textarea that's ~680 px, well above any
        reasonable dock height -- so form_panel claims 680 px,
        overflows the dock's viewport, and the bottom band gets
        scrolled out of sight.  That is the v0.8.0a16/a17/a18
        regression.

        Returning the minimumSizeHint as the preferred size keeps
        form_panel from claiming any more than it strictly needs;
        the ``MinimumExpanding`` size policy set in ``__init__``
        then lets it grow with the dock viewport when there's room.
        The inner ``form_scroll`` (already inside form_panel)
        handles real param overflow via its own scrollbar -- which
        is what the user actually wants: scroll PARAMS, keep cfg /
        Run row pinned at the bottom.
        """
        return self.minimumSizeHint()


class _FormScrollArea(QScrollArea):
    """A QScrollArea whose ``sizeHint`` is small, but which still
    claims any leftover vertical space via Expanding sizePolicy.

    Background: ``QScrollArea.sizeHint()`` defaults to its inner
    widget's sizeHint when ``widgetResizable=True`` -- so a form
    with 16 param rows reports ~400 px of preferred height.  That
    height then bubbles up through the form_panel's QVBoxLayout
    into form_panel.layout().sizeHint(), pushing form_panel's
    *preferred* height past the dock viewport.  QtAds wraps the
    over-sized content in its own QScrollArea and the bottom band
    (cfg / Run row / status) gets scrolled out of sight.

    Returning a small fixed ``sizeHint`` here breaks that chain:
    form_panel's layout sums up a modest total, form_panel fits
    in the dock without QtAds wrapping, and the ``Expanding``
    policy + ``stretch=1`` on this widget in the parent layout
    still lets it absorb all leftover vertical space.  The inner
    ``form_group``'s real height is irrelevant -- this widget
    scrolls its own contents the moment ``form_group`` doesn't
    fit, exactly like a normal QScrollArea.
    """

    # A modest preferred height for the params area -- big enough
    # that single-row tools render without a huge stretched scroll
    # frame, small enough that the layout's sizeHint sum stays
    # under any reasonable dock viewport.
    _PREFERRED_H = 80

    def sizeHint(self) -> QSize:  # noqa: N802 -- Qt naming
        base = super().sizeHint()
        return QSize(base.width(), self._PREFERRED_H)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 -- Qt naming
        # Don't lock in any minimum from the inner widget -- the
        # parent layout's stretch=1 will grow us, and we can
        # collapse to nearly nothing when the dock is tight.
        base = super().minimumSizeHint()
        return QSize(base.width(), 0)


class _CompactPlainTextEdit(QPlainTextEdit):
    """QPlainTextEdit whose ``sizeHint`` is one text line tall.

    The default ``QPlainTextEdit.sizeHint()`` is roughly 100 px high —
    enough that when the bottom pane (extras + command line) is
    reparented into a dock widget at install time, the dock asks the
    docking system for a ~250 px slice of vertical space even when both
    editors are nominally one-line affairs.

    Overriding ``sizeHint`` to ``(width-of-default, font line spacing
    + a little chrome)`` lets the dock open at the smallest height
    that fits both editors (and their group-box titles + option row)
    without a scrollbar. Users can still drag the dock's resize handle
    or the splitter handle inside the form panel to grow the editors.
    """

    # Chrome budget on top of one text line: small vertical padding
    # the framed text edit reserves for cursor + frame.
    _CHROME_PX = 8

    def sizeHint(self):  # type: ignore[override]
        hint = super().sizeHint()
        line_h = self.fontMetrics().lineSpacing() + self._CHROME_PX
        hint.setHeight(line_h)
        return hint

    def minimumSizeHint(self):  # type: ignore[override]
        hint = super().minimumSizeHint()
        line_h = self.fontMetrics().lineSpacing() + self._CHROME_PX
        hint.setHeight(line_h)
        return hint


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
        # ``reorder_parameters`` capability gate (V3 v0.3.3) — when
        # denied, the form list disables drag-drop entirely so users
        # see-but-can't-rearrange parameters.  Default-allowed.
        from .permission_guards import perm_check
        if perm_check("reorder_parameters"):
            self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.setDefaultDropAction(Qt.DropAction.MoveAction)
        else:
            self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.setUniformItemSizes(False)
        # Never grow a horizontal scrollbar — individual row widgets
        # shrink to the viewport width via resizeEvent() below. Vertical
        # scrollbar is auto: it shows only when the parent layout can't
        # give us enough height for every row.
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # The list should ask its parent for exactly "sum of row
        # heights + frame" worth of vertical space. When the parent
        # can provide it (usual case — the form panel has plenty of
        # room), no inner scrollbar is needed. When the parent is too
        # short, the inner scrollbar kicks in naturally.
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        # Qt's list-widget rowsMoved signal fires after the user drops a
        # row. We translate that to a clean orderChanged emission.
        self.model().rowsMoved.connect(self._on_rows_moved)

    def sizeHint(self) -> QSize:
        """Prefer exactly enough height for all rows + frame.

        The default QListWidget.sizeHint is a generic 256x192 which
        triggers a useless vertical scrollbar whenever the real row
        count fits in the available space but doesn't match 192 px.
        """
        total_h = 2 * self.frameWidth()
        for i in range(self.count()):
            total_h += self.sizeHintForRow(i)
        # Fall back to the default width hint; height is what matters.
        default = super().sizeHint()
        return QSize(default.width(), max(total_h, 1))

    def minimumSizeHint(self) -> QSize:
        # Allow the list to collapse to almost nothing so the parent
        # layout can shrink freely when the window is resized small.
        default = super().minimumSizeHint()
        return QSize(default.width(), 0)

    def resizeEvent(self, event) -> None:  # noqa: N802
        """Keep every row widget sized to the current viewport width.

        QListWidget doesn't do this for setItemWidget()-placed widgets
        by default: the row widget keeps its original sizeHint width,
        so when the viewport shrinks the row overflows and Qt shows a
        horizontal scrollbar (which we've disabled anyway, producing
        clipped text instead). Resetting item sizeHints on every
        resize makes the rows shrink with the viewport.
        """
        super().resizeEvent(event)
        self.relayout_rows()

    def relayout_rows(self) -> None:
        """Re-measure every row at the current viewport width.

        Public so widgets inside the rows (e.g. ``CheckboxWidget``
        when its user toggles word wrap via the right-click menu) can
        ask the list to recompute row heights. Without this, the
        QListWidgetItem's cached sizeHint stays at the old height and
        newly-wrapped text gets clipped.
        """
        vp_w = self.viewport().width()
        for i in range(self.count()):
            item = self.item(i)
            w = self.itemWidget(item)
            if w is None:
                continue
            # Let the row re-compute its preferred height for the new
            # width (word-wrapped labels etc).
            hfw = w.heightForWidth(vp_w) if w.hasHeightForWidth() else 0
            h = max(hfw, w.sizeHint().height())
            item.setSizeHint(QSize(vp_w, h))

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

    def set_row_hidden(self, param_id: str, hidden: bool) -> None:
        """Hide / show the row owned by ``param_id`` (v0.4.0+).

        Used by ``ToolRunnerView`` to honour ``ParamDef.visible_when``
        — when an expression like ``"bom_source == 'drawing'"`` is
        currently False, the row for ``bom_feature_name`` disappears
        from the form so the user only sees fields relevant to the
        mode they've picked.
        """
        for i in range(self.count()):
            item = self.item(i)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == param_id:
                item.setHidden(hidden)
                return

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


# --- save-as (personal / shared) dialog ----------------------------------

class SaveConfigAsDialog(QDialog):
    """Prompt for a configuration name plus storage location.

    The caller supplies flags indicating which storages the user has
    permission to write to — the disallowed radio button is disabled.
    """

    def __init__(
        self,
        parent: QWidget | None,
        *,
        can_write_shared: bool,
        can_write_personal: bool,
        initial_name: str = "",
        initial_storage: str = "shared",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save configuration as")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("New configuration name:"))
        self._name_edit = QLineEdit(initial_name)
        layout.addWidget(self._name_edit)

        layout.addWidget(QLabel("Save to:"))
        self._radio_shared = QRadioButton(
            "Shared \u2014 next to the tool, visible to other users"
        )
        self._radio_personal = QRadioButton(
            "Personal \u2014 your own folder, invisible to others"
        )
        group = QButtonGroup(self)
        group.addButton(self._radio_shared)
        group.addButton(self._radio_personal)

        self._radio_shared.setEnabled(can_write_shared)
        self._radio_personal.setEnabled(can_write_personal)
        if initial_storage == "personal" and can_write_personal:
            self._radio_personal.setChecked(True)
        elif can_write_shared:
            self._radio_shared.setChecked(True)
        elif can_write_personal:
            self._radio_personal.setChecked(True)

        layout.addWidget(self._radio_shared)
        layout.addWidget(self._radio_personal)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def result_name(self) -> str:
        return self._name_edit.text().strip()

    def result_storage(self) -> str:
        return "personal" if self._radio_personal.isChecked() else "shared"


# --- personal-config collision dialog -------------------------------------

class PersonalConfigCollisionDialog(QDialog):
    """Prompted when loading a tool whose filename matches an existing
    personal sidecar at a different location.

    Offers three choices:

    - **CREATE_NEW** — a new personal sidecar with the next available
      ``-NNN`` suffix. The existing file is untouched.
    - **USE_EXISTING** — reuse one of the existing files, appending
      the current tool's parent directory to ``source_locations``.
    - **UPDATE_LOCATION** — reuse one of the existing files, replacing
      ``source_locations`` with just the current tool's parent.
    """

    CREATE_NEW = 1
    USE_EXISTING = 2
    UPDATE_LOCATION = 3

    def __init__(
        self,
        parent: QWidget | None,
        tool_path: Path,
        candidates: list[Path],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Personal configuration collision")
        self.setMinimumWidth(520)
        self._candidates = list(candidates)
        self._chosen_action: int = self.CREATE_NEW

        layout = QVBoxLayout(self)

        header = QLabel(
            f"<b>A personal configuration for <code>{tool_path.name}</code> "
            f"was found, but it's associated with a different "
            f"location.</b>"
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        info = QLabel(
            f"You're loading the tool from:<br>"
            f"<code>{tool_path.parent}</code>"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        if len(candidates) > 1:
            layout.addWidget(QLabel("Pick the existing file to use:"))
            self._candidate_list = QListWidget()
            for cand in candidates:
                self._candidate_list.addItem(cand.name)
            self._candidate_list.setCurrentRow(0)
            layout.addWidget(self._candidate_list)
        else:
            self._candidate_list = None
            layout.addWidget(QLabel(
                f"Existing file: <code>{candidates[0].name}</code>"
            ))

        layout.addWidget(QLabel("<b>What would you like to do?</b>"))

        btn_create = QPushButton("Create a new personal file")
        btn_create.setToolTip(
            "Keep the existing file untouched and create a new personal "
            "sidecar for this tool's location."
        )
        btn_create.clicked.connect(self._accept_create_new)
        layout.addWidget(btn_create)

        btn_use = QPushButton(
            "Use existing \u2014 add this location to it"
        )
        btn_use.setToolTip(
            "Reuse the existing personal configurations. This location "
            "will be added alongside any others already stored."
        )
        btn_use.clicked.connect(self._accept_use_existing)
        layout.addWidget(btn_use)

        btn_update = QPushButton(
            "Use existing \u2014 replace old locations with this one"
        )
        btn_update.setToolTip(
            "Reuse the existing personal configurations. Other stored "
            "locations will be forgotten (useful when the tool has "
            "been moved)."
        )
        btn_update.clicked.connect(self._accept_update_location)
        layout.addWidget(btn_update)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _accept_create_new(self) -> None:
        self._chosen_action = self.CREATE_NEW
        self.accept()

    def _accept_use_existing(self) -> None:
        self._chosen_action = self.USE_EXISTING
        self.accept()

    def _accept_update_location(self) -> None:
        self._chosen_action = self.UPDATE_LOCATION
        self.accept()

    def chosen_action(self) -> int:
        return self._chosen_action

    def selected_candidate(self) -> Path | None:
        if not self._candidates:
            return None
        if self._candidate_list is None:
            return self._candidates[0]
        row = self._candidate_list.currentRow()
        if 0 <= row < len(self._candidates):
            return self._candidates[row]
        return None


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
        interactive: bool = False,
    ) -> None:
        super().__init__()
        self._command = command
        # (username, password, domain) or None for normal spawn.
        self._credentials = credentials
        # When True, the child is spawned with ``stdin=PIPE`` so the
        # UI can call ``send_line()`` to push answers (e.g. y/n/!/q
        # for query-replace) into the running process.
        self._interactive = interactive
        # Set from the worker thread in ``_on_process_start``; read
        # from the UI thread in ``stop`` / ``send_line``. A plain
        # attribute assignment is atomic in CPython and the Stop /
        # Send button races are benign — worst case we call terminate
        # / write to an already-exited process and catch BrokenPipeError.
        self._proc: subprocess.Popen | None = None
        self._stop_level = 0  # 0=running, 1=terminate sent, 2=kill sent

    def run(self) -> None:
        try:
            if self._credentials is not None:
                username, password, domain = self._credentials
                # Run-as-user does NOT support interactive stdin —
                # CreateProcessWithLogonW + interactive pipes would
                # require additional plumbing (proper handle
                # inheritance through impersonation).  Fall back to
                # non-interactive spawn and surface the limitation.
                if self._interactive:
                    self.stderrLine.emit(
                        "[warning] Interactive stdin is not supported "
                        "with run-as-different-user; running non-"
                        "interactively.",
                    )
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
                    interactive=self._interactive,
                )
        except Exception as e:  # noqa: BLE001 - surface to UI
            self.stderrLine.emit(f"[runner error] {e}")
            self.finished.emit(-1, 0.0)
            return
        self.finished.emit(result.exit_code, result.duration_seconds)

    def _on_process_start(self, proc: subprocess.Popen) -> None:
        self._proc = proc

    def send_line(self, text: str) -> bool:
        """Write ``text + '\\n'`` to the child's stdin.

        Called from the UI thread when the user clicks Send (or hits
        Enter in the interactive input box).  Returns True on success,
        False if the pipe is missing, closed, or the write failed —
        in which case the caller should surface the error in the
        output pane and disable the input box.

        Safe to call from any thread; ``Popen.stdin`` writes are
        protected by Python's GIL and the underlying pipe handle is
        independent of the stdout / stderr pump threads.
        """
        proc = self._proc
        if proc is None or proc.stdin is None:
            return False
        if proc.poll() is not None:
            return False
        try:
            proc.stdin.write(text + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            return False
        return True

    def close_stdin(self) -> None:
        """Close the child's stdin pipe to signal EOF.

        Some interactive tools watch for stdin EOF as a clean-exit
        signal (``read EOF`` → break out of the prompt loop and
        finalise).  The output pane's "End input" button calls this.
        """
        proc = self._proc
        if proc is None or proc.stdin is None:
            return
        try:
            proc.stdin.close()
        except OSError:
            pass

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
        # Parent-tree path_prepend (V3 v0.3.2+).  Empty list when this
        # tool was not opened through a loaded ``.scriptreetree``.
        # Updated by ``MainWindow._show_runner`` every time the runner
        # surfaces, so a runner cached in ``MainWindow._runners`` picks
        # up tree-level path edits across re-opens.  See
        # ``set_tree_path_prepend``.
        self._tree_path_prepend: list[str] = []

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

    @property
    def bottom_panel(self) -> QWidget:
        """The bottom-of-form panel (extras + command line).

        Exposed so the main window can reparent it into its own dock
        widget — mirrors how ``output_panel`` is handled. When the dock
        is detached, ``_uninstall_runner_panels`` calls
        :meth:`_return_bottom_panel` to put the panel back where the
        runner originally placed it.
        """
        return self._bottom_pane

    def _return_bottom_panel(self, widget: QWidget) -> None:
        """Re-attach the bottom panel after a MainWindow uninstall.

        v0.8.0a14+ -- the bottom pane sits inside the bottom-band
        widget alongside the cfg row, Run / Stop row, and status
        line.  Re-insert at the captured index so the visual order
        (cfg -> extras + cmd -> Run row -> ...) is preserved.
        Used by ``MainWindow._uninstall_runner_panels``.
        """
        if widget is not self._bottom_pane:
            self._bottom_pane = widget
        layout = getattr(self, "_bottom_band_layout", None)
        if layout is None:
            # Pre-v0.8.0a14 fallback -- should never happen on the
            # current build but keeps the call site safe if a stale
            # MainWindow ever calls back into a fresh runner.
            return
        index = getattr(self, "_bottom_pane_index", layout.count())
        layout.insertWidget(min(index, layout.count()), widget)

    def set_standalone_mode(self, standalone: bool) -> None:
        """Flip the standalone-mode flag with side effects.

        Replaces the previous ``runner._standalone_mode = True``
        assignment that callers used.  v0.8.0a12+ collapses the
        "Extra arguments" section by default in standalone mode
        because direct-launches almost never use extras (the form
        is the canonical input surface); when run inside the main
        editor, extras stays expanded so power users can still see
        and edit the field at a glance.
        """
        self._standalone_mode = bool(standalone)
        extras = getattr(self, "_extras_box", None)
        if extras is not None and standalone:
            extras.setExpanded(False)

    def set_tree_path_prepend(self, paths: list[str] | None) -> None:
        """Set the parent-tree ``path_prepend`` list for this runner.

        Called by ``MainWindow._show_runner`` whenever it surfaces a
        tool that was opened through a loaded ``.scriptreetree``.
        Pass ``None`` or ``[]`` to clear (e.g. when the same runner
        is later reused for a tool opened directly without a tree).

        The value is consumed at run time inside ``_start_run`` and
        forwarded to ``build_full_argv`` as ``tree_path_prepend=``,
        so changes take effect on the next Run click.  Doesn't
        affect the editable live-preview text box (the preview only
        renders argv, not env).
        """
        self._tree_path_prepend = list(paths or [])

    def tree_path_prepend(self) -> list[str]:
        """Return the runner's current parent-tree path_prepend list."""
        return list(self._tree_path_prepend)

    def _build_output_panel(self) -> QWidget:
        """Build the output pane as a standalone widget.

        For interactive tools (``tool.interactive == True`` AND the
        ``interactive_stdin`` capability is granted), an extra input
        row is appended below the output text:

          ┌──────────────────────────────────────┐
          │ Output text (read-only)              │
          ├──────────────────────────────────────┤
          │ Send: [_____________] [y][n][!][q] [Send] [End input]
          └──────────────────────────────────────┘

        Pressing Enter in the line edit, or clicking one of the
        quick-response buttons, writes the line to the running
        process's stdin via the worker's ``send_line``.  When the
        permission is missing or the tool isn't declared interactive,
        the row is hidden and the runner runs in pre-v0.3 one-shot
        mode (matches every existing .scriptree).
        """
        output_box = QGroupBox("Output")
        out_layout = QVBoxLayout(output_box)
        mono = QFont()
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setFamily("Consolas")
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(mono)
        out_layout.addWidget(self._output)

        # Interactive input row — built unconditionally so tests can
        # access it, but visibility is toggled by
        # ``_refresh_interactive_visibility`` based on
        # ``tool.interactive`` AND the runtime permission.
        self._interactive_row = self._build_interactive_input_row()
        out_layout.addWidget(self._interactive_row)
        self._refresh_interactive_visibility()

        return output_box

    def _build_interactive_input_row(self) -> QWidget:
        """Construct the send-line widget shown for interactive tools."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 4, 0, 0)

        prompt_label = QLabel("Send:")
        prompt_label.setToolTip(
            "Type a line and press Enter (or click Send) to write it "
            "to the running tool's stdin."
        )
        row_layout.addWidget(prompt_label)

        self._send_line_edit = QLineEdit()
        self._send_line_edit.setPlaceholderText(
            "Type response, then Enter to send..."
        )
        self._send_line_edit.returnPressed.connect(self._on_send_line)
        row_layout.addWidget(self._send_line_edit, stretch=1)

        # Quick-response buttons.  Order matches Emacs query-replace's
        # most-used answers; ``!`` accepts all remaining matches, ``q``
        # quits the prompt loop.  Tools that don't use the y/n/!/q
        # vocabulary just ignore unrelated input — these are safe
        # convenience shortcuts, not protocol.
        for label, tip in (
            ("y", "Send 'y' (yes — accept this match)"),
            ("n", "Send 'n' (no — skip this match)"),
            ("!", "Send '!' (accept all remaining matches)"),
            ("q", "Send 'q' (quit the prompt loop)"),
        ):
            btn = QPushButton(label)
            btn.setFixedWidth(28)
            btn.setToolTip(tip)
            btn.clicked.connect(
                lambda checked=False, t=label: self._send_quick_response(t)
            )
            row_layout.addWidget(btn)

        self._btn_send = QPushButton("Send")
        self._btn_send.setToolTip("Send the typed line to the tool's stdin.")
        self._btn_send.clicked.connect(self._on_send_line)
        row_layout.addWidget(self._btn_send)

        self._btn_end_input = QPushButton("End input")
        self._btn_end_input.setToolTip(
            "Close the tool's stdin pipe.  Some interactive tools treat "
            "this as a clean-exit signal.",
        )
        self._btn_end_input.clicked.connect(self._on_end_input)
        row_layout.addWidget(self._btn_end_input)

        return row

    def _refresh_interactive_visibility(self) -> None:
        """Show / hide the interactive input row based on tool flag +
        permission state.

        Both must be true:

        * ``self._tool.interactive`` — the .scriptree opted in.
        * ``interactive_stdin`` permission — the org allowed it.

        When either is False the row is hidden and the runner falls
        back to pre-v0.3 one-shot behaviour.
        """
        from ..core.permissions import get_app_permissions

        if not getattr(self, "_interactive_row", None):
            return
        tool_opted_in = bool(getattr(self._tool, "interactive", False))
        if tool_opted_in:
            try:
                perms = get_app_permissions()
                permission_granted = perms.can("interactive_stdin")
            except Exception:  # noqa: BLE001
                permission_granted = False
        else:
            permission_granted = False

        show_row = tool_opted_in and permission_granted
        self._interactive_row.setVisible(show_row)
        self._interactive_enabled = show_row
        self._interactive_permission_denied = (
            tool_opted_in and not permission_granted
        )

    def _build_form_panel(self, tool: ToolDef) -> QWidget:
        """Build the form panel as a standalone widget."""
        from PySide6.QtWidgets import QMenuBar
        # v0.8.0a19+ -- use a QWidget subclass so we can properly
        # override ``minimumSizeHint`` as a real Qt virtual method.
        # Earlier attempts assigned the method to the instance
        # (``container.minimumSizeHint = lambda: ...``), which
        # works for pure-Python callers but is SILENTLY IGNORED by
        # Qt's C++ side -- ``QWidget::minimumSizeHint()`` is a
        # virtual method called through the vtable, and PySide6
        # only routes calls back to Python when the method is
        # declared on a QWidget subclass at class-definition time.
        # QtAds asks Qt directly, sees the unmodified default
        # (which returns 0/0), and freely shrinks the form dock
        # below the bottom band's natural height.  That's the
        # explanation for "developer mode works, standalone
        # doesn't" -- MainWindow's QStackedWidget happens to mask
        # the underlying issue while standalone hits it dead-on.
        container = _FormPanelContainer()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)

        # Custom menus defined in the .scriptree file.
        if tool.menus:
            menu_bar = QMenuBar(container)
            self._build_custom_menus(menu_bar, tool.menus)
            layout.setMenuBar(menu_bar)

        # Header — collapsible group box wrapping the tool name + the
        # description blurb. Some tools have multi-paragraph descriptions
        # that take a third of the form's vertical space; users who've
        # read them once want them out of the way.  Clicking the
        # arrow toggles the description; the title bar stays visible
        # at all times so the toggle is always findable.  Session-
        # only state -- no persistence to .scriptree.
        #
        # v0.8.0a12+ switched from a checkable QGroupBox (Qt-native
        # checkbox in the title) to ArrowSection (▶ / ▼ arrow) per
        # user feedback that the checkbox read as "enable / disable
        # the feature" rather than "show / hide the section."  The
        # ArrowSection API mirrors QGroupBox's setChecked / isChecked
        # / toggled / setTitle so call-site changes were minimal.
        from .arrow_section import ArrowSection
        self._header_box = ArrowSection(f"{tool.name}", expanded=True)
        self._header_box.setToolTip(
            "Click the arrow to collapse or expand the description."
        )
        header_inner = QWidget()
        header_layout = QVBoxLayout(header_inner)
        header_layout.setContentsMargins(0, 0, 0, 0)
        if tool.description:
            desc = QLabel(tool.description)
            desc.setWordWrap(True)
            header_layout.addWidget(desc)
        else:
            header_layout.addWidget(QLabel(
                f"<i>No description provided.</i>"
            ))
        self._header_box.setContentWidget(header_inner)
        layout.addWidget(self._header_box)

        # Layout shape (v0.8.0a12+, per user feedback):
        #
        #   [Header arrow + description]     <- collapsible
        #   ─────────────────────────────
        #   [Parameters scroll area]         <- takes available space
        #   ─────────────────────────────
        #   [Configurations bar]             <- always visible
        #   [Extras arrow + edit]            <- collapsible
        #   [Command line arrow + edit]      <- collapsible
        #   [Run / Stop / etc row]           <- always visible
        #   [Action buttons row]             <- always visible (if any)
        #   [Status line]                    <- always visible
        #
        # The previous layout used a QSplitter so the user could drag
        # a handle between params and "extras + command line."  That
        # drag was rarely used and let the bottom controls disappear
        # off-screen when the user accidentally yanked the handle.
        # The new layout drops the splitter -- the parameters scroll
        # area takes ``stretch=1`` so it absorbs available vertical
        # space, and every control below is at its natural height
        # ("always try to stay visible without a scroll bar").
        # Each collapsible section uses the project's ``ArrowSection``
        # widget (▶ / ▼ arrow) instead of Qt's QGroupBox-with-checkbox,
        # because the checkbox affordance reads as "enable / disable"
        # while the arrow reads as "show / hide" -- closer to the
        # actual semantics.
        from .arrow_section import ArrowSection

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
        # v0.8.0a19 -- use ``_FormScrollArea`` (a QScrollArea
        # subclass with a small ``sizeHint``) so the params area
        # doesn't inflate form_panel.layout().sizeHint().  Combined
        # with ``Expanding`` policy + ``stretch=1`` below, this
        # claims any leftover space when the dock is roomy and
        # collapses (with its own inner scrollbar) when the dock
        # is tight -- without confusing QtAds into wrapping the
        # whole form in a second scroll area.
        form_scroll = _FormScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        form_scroll.setWidget(form_group)
        # Critical for the v0.8.0a13 "controls always visible" rule:
        # the scroll area must be allowed to shrink all the way down
        # so the bottom band (cfg, extras/cmd, Run row, status) keeps
        # its natural height when the dock is tight.  Without this,
        # ``stretch=1`` alone isn't enough -- Qt's QVBoxLayout would
        # still try to honour the scroll area's content sizeHint,
        # which pushes the Run buttons off the bottom of the form
        # dock when the form_group is taller than the dock.
        from PySide6.QtWidgets import QSizePolicy
        form_scroll.setMinimumHeight(0)
        # v0.8.0a19 -- ``_FormScrollArea`` already overrides
        # ``sizeHint`` to a small value, so we keep the natural
        # ``Expanding`` policy here.  Expanding + stretch=1 lets
        # form_scroll claim ALL leftover vertical space in the
        # parent layout (so the params area grows to fill any
        # gap between the header and the bottom band -- the user-
        # visible behaviour they expect: "white area should always
        # be the same size as the full parameters area").
        # The small sizeHint stops the layout sum from inflating
        # form_panel's preferred height past the dock viewport.
        form_scroll.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        layout.addWidget(form_scroll, stretch=1)

        # Bottom pane — extras + command line, wrapped in a single
        # QWidget so MainWindow can detach the whole block into its
        # own dock when the runner is installed in the main editor.
        # When standalone, the bottom_pane sits sequentially in the
        # main layout (no splitter, no drag).
        self._bottom_pane = bottom_pane = QWidget()
        bottom_layout = QVBoxLayout(bottom_pane)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(4)
        # ``_bottom_splitter`` no longer points at a real splitter --
        # kept as an attribute name only because MainWindow's
        # uninstall code historically called ``addWidget`` on it.
        # The setter we expose via ``_return_bottom_panel`` is the
        # supported way to re-attach the panel; MainWindow was
        # updated in the same release.
        self._bottom_splitter = None

        # Mono font handle reused by extras + cmd editors.
        mono = QFont()
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setFamily("Consolas")

        # Extras section — space-separated argv tokens the user has
        # added beyond what the GUI form produces. Populated either
        # by reconciling edits to the command preview or typed
        # directly.  Collapsible (▶ / ▼ arrow toggles visibility of
        # the inner editor; the header bar is always there so the
        # user can find the expander when collapsed).
        self._extras_box = ArrowSection(
            "Extra arguments (space-separated)", expanded=True,
        )
        self._extras_box.setToolTip(
            "Tokens here are appended to the command as-is. "
            "Anything you type in the preview below that doesn't match "
            "a form parameter lands here automatically."
        )
        self._extras_edit = _CompactPlainTextEdit()
        self._extras_edit.setFont(mono)
        self._extras_edit.setPlaceholderText(
            "e.g. --debug 2 --log-file C:/tmp/run.log"
        )
        self._extras_edit.textChanged.connect(self._on_extras_edited)
        self._extras_box.setContentWidget(self._extras_edit)
        bottom_layout.addWidget(self._extras_box)

        # Command preview — editable QPlainTextEdit with "Full path"
        # and "Word wrap" checkboxes.  Same arrow-collapse pattern.
        self._cmd_box = ArrowSection("Command line", expanded=True)
        cmd_inner = QWidget()
        cmd_inner_layout = QVBoxLayout(cmd_inner)
        cmd_inner_layout.setContentsMargins(0, 0, 0, 0)
        cmd_inner_layout.setSpacing(2)
        cmd_opts = QHBoxLayout()
        cmd_opts.setContentsMargins(0, 0, 0, 0)

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
        # Wrap the option row in a QWidget so the cmd section can
        # tuck it inside its content widget cleanly.
        self._cmd_opts_wrapper = cmd_opts_wrapper = QWidget()
        cmd_opts_wrapper.setLayout(cmd_opts)
        cmd_inner_layout.addWidget(cmd_opts_wrapper)

        self._live_cmd = _CompactPlainTextEdit()
        self._live_cmd.setPlaceholderText(
            "Command line — edit to override form values or add extras..."
        )
        preview_font = QFont()
        preview_font.setStyleHint(QFont.StyleHint.Monospace)
        preview_font.setFamily("Consolas")
        self._live_cmd.setFont(preview_font)
        self._live_cmd.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._live_cmd.textChanged.connect(self._on_live_cmd_text_changed)
        cmd_inner_layout.addWidget(self._live_cmd)
        self._cmd_box.setContentWidget(cmd_inner)
        # ``command_line_editor`` capability gate (V3 v0.3.3) — when
        # denied, the live command box becomes read-only so the user
        # can still see what's about to run but can't override.  No
        # behavioural change on Run (validation still runs against
        # the form-derived argv).
        from .permission_guards import apply_text_readonly
        apply_text_readonly(self._live_cmd, "command_line_editor")
        bottom_layout.addWidget(self._cmd_box)

        # Configurations bar: [Config ▾] [Save] [Save As] [Delete] [Edit...]
        # Wrapped in a QWidget so the MainWindow can show/hide it
        # based on whether the form dock is floating.
        self._cfg_set: ConfigurationSet = default_configuration_set()
        # Personal configurations live in a separate sidecar in the
        # user_configs/ directory. Loaded on demand when the tool opens.
        self._personal_cfg_set: ConfigurationSet | None = None
        self._personal_cfg_path: Path | None = None
        # Which set the currently-selected config belongs to. Stored as
        # (storage, name) so the combo handler can route correctly.
        self._active_selection: tuple[str, str] = ("shared", "default")
        self._cfg_loading = False
        self._cfg_widget = QWidget()
        # FlowLayout so the config toolbar wraps onto a second row
        # when the window is too narrow, instead of growing a
        # horizontal scroll bar.
        from .flow_layout import FlowLayout
        cfg_layout = FlowLayout(self._cfg_widget, hspacing=4, vspacing=4)
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
        # FlowLayout doesn't support per-item stretch — the combo just
        # sits at its preferred width and the row wraps when crowded.
        cfg_layout.addWidget(self._cfg_combo)

        # "Default" checkbox — when checked, the selected configuration
        # becomes the default that standalone-mode launches use when no
        # ``-configuration`` CLI arg is supplied.  When unchecked,
        # standalone falls back to whichever configuration was last
        # active.  Only one configuration can be the default at a
        # time; checking it on a different config clears the previous
        # one.  Persists via ConfigurationSet.default_name in the
        # sidecar JSON.
        self._cfg_default_check = QCheckBox("Default")
        self._cfg_default_check.setToolTip(
            "Mark this configuration as the default used by standalone "
            "launches (e.g. clicking a tool in a cell-shell menu).\n\n"
            "If no default is set, standalone falls back to the "
            "last-used configuration. Only one configuration can be "
            "the default at a time."
        )
        self._cfg_default_check.toggled.connect(
            self._on_cfg_default_toggled
        )
        cfg_layout.addWidget(self._cfg_default_check)

        # Configuration write buttons (V3 v0.3.3 capability gates):
        # ``write_configurations`` (legacy umbrella) gates Save / Save
        # As / Delete.  Per-scope gates layer on top — see
        # ``_refresh_cfg_button_perms`` for the scope-aware logic
        # that handles personal vs. shared sidecars.
        from .permission_guards import apply_widget_perm
        self._btn_cfg_save = QPushButton("Save")
        self._btn_cfg_save.setToolTip(
            "Save the current form values into the selected configuration."
        )
        self._btn_cfg_save.clicked.connect(self._cfg_save)
        cfg_layout.addWidget(self._btn_cfg_save)
        apply_widget_perm(self._btn_cfg_save, "write_configurations")

        self._btn_cfg_save_as = QPushButton("Save as...")
        self._btn_cfg_save_as.setToolTip(
            "Create a new configuration with the current form values."
        )
        self._btn_cfg_save_as.clicked.connect(self._cfg_save_as)
        cfg_layout.addWidget(self._btn_cfg_save_as)
        apply_widget_perm(self._btn_cfg_save_as, "write_configurations")

        self._btn_cfg_delete = QPushButton("Delete")
        self._btn_cfg_delete.setToolTip("Delete the selected configuration.")
        self._btn_cfg_delete.clicked.connect(self._cfg_delete)
        cfg_layout.addWidget(self._btn_cfg_delete)
        apply_widget_perm(self._btn_cfg_delete, "write_configurations")

        self._btn_cfg_edit = QPushButton("Edit...")
        self._btn_cfg_edit.setToolTip(
            "Reorder and rename configurations in a popup."
        )
        self._btn_cfg_edit.clicked.connect(self._cfg_edit)
        cfg_layout.addWidget(self._btn_cfg_edit)
        # ``edit_configurations`` capability gate (V3 v0.3.3) — opens
        # the rename / reorder popup; distinct from write
        # (write = save values, edit = rearrange).
        apply_widget_perm(self._btn_cfg_edit, "edit_configurations")

        self._btn_cfg_env = QPushButton("Env...")
        self._btn_cfg_env.setToolTip(
            "Edit environment variables and PATH prepends for the "
            "selected configuration. These layer on top of the "
            "tool-level environment defined in the editor."
        )
        self._btn_cfg_env.clicked.connect(self._cfg_edit_env)
        cfg_layout.addWidget(self._btn_cfg_env)
        # ``edit_environment`` capability gate (V3 v0.3.3).
        from .permission_guards import apply_widget_perm
        apply_widget_perm(self._btn_cfg_env, "edit_environment")

        self._btn_cfg_visibility = QPushButton("Visibility...")
        self._btn_cfg_visibility.setToolTip(
            "Choose which UI elements to show or hide, and lock "
            "individual parameters to fixed values for this "
            "configuration."
        )
        self._btn_cfg_visibility.clicked.connect(self._cfg_edit_visibility)
        cfg_layout.addWidget(self._btn_cfg_visibility)
        # ``edit_visibility`` capability gate (V3 v0.3.3).
        apply_widget_perm(self._btn_cfg_visibility, "edit_visibility")

        self._chk_prompt_creds = QCheckBox("Prompt for alternate credentials")
        self._chk_prompt_creds.setToolTip(
            "When checked, clicking Run will prompt for a username "
            "and password. The process will be launched under that "
            "user's security context (Windows only)."
        )
        self._chk_prompt_creds.toggled.connect(self._on_prompt_creds_toggled)
        cfg_layout.addWidget(self._chk_prompt_creds)
        # ``run_as_different_user`` capability gate (V3 v0.3.3) — when
        # denied, the user can't even tick the box.  Enforced at run
        # time in ``_start_run`` too for keyboard / programmatic.
        apply_widget_perm(self._chk_prompt_creds, "run_as_different_user")

        # v0.8.0a14+ bottom_band rework
        # ---------------------------------------------------------------
        # In v0.8.0a13 we set ``form_scroll.setMinimumHeight(0)`` so
        # the parameters scroll area could compress and let the Run /
        # Stop button row stay visible.  That works in MainWindow's
        # editor (which wraps the form panel in a QStackedWidget) but
        # NOT in StandaloneWindow, which puts the form panel directly
        # into a QtAds dock -- QtAds's dock geometry negotiation
        # doesn't honour the inner scroll area's "I can shrink"
        # promise reliably, and the Run buttons still get pushed off.
        #
        # The robust fix is to wrap everything below ``form_scroll``
        # into one ``bottom_band`` widget with a Fixed vertical size
        # policy.  Qt's QVBoxLayout treats Fixed as "must get
        # sizeHint exactly", so the band claims its natural height
        # first; ``form_scroll`` absorbs whatever is left over (with
        # ``stretch=1`` it'll happily take the rest when there is
        # any).  This makes the layout deterministic across MainWindow
        # AND StandaloneWindow.
        from PySide6.QtWidgets import QSizePolicy
        bottom_band = QWidget()
        bottom_band_layout = QVBoxLayout(bottom_band)
        bottom_band_layout.setContentsMargins(0, 0, 0, 0)
        bottom_band_layout.setSpacing(4)
        bottom_band.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )

        bottom_band_layout.addWidget(self._cfg_widget)

        # The bottom pane (extras + command line ArrowSections).
        # Remember the index inside ``bottom_band_layout`` so
        # ``_return_bottom_panel`` can re-insert it correctly after
        # MainWindow detaches it into its own dock.
        bottom_band_layout.addWidget(self._bottom_pane)
        self._bottom_band = bottom_band
        self._bottom_band_layout = bottom_band_layout
        self._bottom_pane_index = bottom_band_layout.indexOf(
            self._bottom_pane,
        )
        # Backward compat aliases for tests + downstream callers
        # that referenced these names in v0.8.0a12/a13.
        self._main_form_layout = bottom_band_layout

        # Action row: [Run] [Stop] [Copy argv] [Undo] [Redo] [Reset] [Clear]
        # Uses FlowLayout so the buttons wrap to a second row when the
        # window is narrow, instead of causing a horizontal scroll bar.
        action_row = FlowLayout(hspacing=4, vspacing=4)

        # v0.6.1 — Run is green, Stop is red (universal go/stop
        # affordance).  The :disabled rules keep the dimmed state
        # legible instead of a flat saturated block when the button
        # is inactive (Run while running, Stop while idle).
        _RUN_QSS = (
            "QPushButton { background:#2e7d32; color:#fff; "
            "border:1px solid #1b5e20; border-radius:4px; "
            "padding:4px 14px; font-weight:600; } "
            "QPushButton:hover:!disabled { background:#388e3c; } "
            "QPushButton:pressed { background:#1b5e20; } "
            "QPushButton:disabled { background:#c8e6c9; color:#7d7d7d; "
            "border-color:#a5d6a7; }"
        )
        _STOP_QSS = (
            "QPushButton { background:#c62828; color:#fff; "
            "border:1px solid #8e0000; border-radius:4px; "
            "padding:4px 14px; font-weight:600; } "
            "QPushButton:hover:!disabled { background:#d32f2f; } "
            "QPushButton:pressed { background:#8e0000; } "
            "QPushButton:disabled { background:#ffcdd2; color:#7d7d7d; "
            "border-color:#ef9a9a; }"
        )

        self._btn_run = QPushButton("Run")
        self._btn_run.setDefault(True)
        self._btn_run.setStyleSheet(_RUN_QSS)
        self._btn_run.clicked.connect(self._start_run)
        # ``run_tools`` capability gate (V3 v0.3.3): when denied, the
        # Run button stays disabled.  ``_start_run`` ALSO checks at
        # call time so other entry points (keyboard shortcut, custom
        # menu actions wired to "Run") are gated too.
        from .permission_guards import apply_widget_perm
        apply_widget_perm(
            self._btn_run, "run_tools",
            tooltip_when_denied=(
                "Disabled by IT — running tools is not permitted "
                "(capability: run_tools)."
            ),
        )
        action_row.addWidget(self._btn_run)

        self._btn_stop = QPushButton("Stop")
        self._btn_stop.setStyleSheet(_STOP_QSS)
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

        # (FlowLayout has no addStretch — buttons cluster to the left
        # naturally and the row wraps when full.)

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

        # Action row goes into the bottom band (v0.8.0a14+) so it
        # stays at natural height instead of competing with the
        # params scroll area for vertical space.  FlowLayout has no
        # owning widget so we drop it directly via ``addLayout``.
        bottom_band_layout.addLayout(action_row)

        # --- Action-button row (V3 v0.8.0a11+) ---------------------------
        # A second FlowLayout below the Run / Stop / Copy argv row, only
        # populated when ``self._tool.actions`` is non-empty.  Each
        # ``ActionDef`` becomes a single QPushButton that, when clicked,
        # spawns the tool with ``[executable, *action.argv]`` -- no form
        # value substitution, no template language, just the literal argv
        # the producer authored.  Output streams into the same pane Run
        # uses, prefixed with "▶ Action: <label>\n" so the session log
        # stays readable when several actions fire in succession.
        #
        # ``self._action_btns`` mirrors the visible buttons so the
        # enable/disable wiring in ``_start_run`` / ``_start_action`` /
        # ``_on_finished`` can flip them all together -- concurrent
        # Run + action is intentionally prevented (same model as
        # concurrent Run + Run today).
        self._action_btns: list[QPushButton] = []
        visible_actions = [
            a for a in (getattr(self._tool, "actions", None) or [])
            if not a.hidden
        ]
        if visible_actions:
            from .flow_layout import FlowLayout
            actions_row = FlowLayout(hspacing=4, vspacing=4)
            self._actions_label = QLabel("Actions:")
            self._actions_label.setStyleSheet(
                "QLabel { color: #555; padding-right: 4px; }"
            )
            actions_row.addWidget(self._actions_label)
            for action_def in visible_actions:
                btn = QPushButton(action_def.label)
                # Tooltip falls back to the resolved argv when the
                # producer didn't author one -- matches the spec's
                # "tooltip empty -> show argv".
                if action_def.tooltip:
                    btn.setToolTip(action_def.tooltip)
                else:
                    preview = " ".join(
                        [self._tool.executable or "", *action_def.argv]
                    ).strip()
                    btn.setToolTip(preview)
                # Capture ``action_def.id`` by default-argument trick so
                # the closure binds the right id per iteration.
                btn.clicked.connect(
                    lambda _checked=False, _aid=action_def.id:
                        self._start_action(_aid)
                )
                actions_row.addWidget(btn)
                self._action_btns.append(btn)
            bottom_band_layout.addLayout(actions_row)

        self._status = QLabel("")
        bottom_band_layout.addWidget(self._status)

        # Finally attach the bottom band to the outer layout.  No
        # stretch -- it claims its sizeHint exactly (Fixed vertical),
        # leaving the rest of the dock to ``form_scroll`` (which has
        # ``stretch=1`` + ``setMinimumHeight(0)`` so it absorbs
        # whatever space is left and can compress to a tiny strip
        # when the dock is short).  This is the contract that makes
        # the Run / Stop buttons always visible.
        layout.addWidget(bottom_band)

        # Plug the reference widgets into the container so its
        # ``minimumSizeHint`` override (real C++ virtual via the
        # ``_FormPanelContainer`` subclass) reads accurate sizes
        # every time Qt asks -- which it does whenever QtAds is
        # deciding how much room to give the dock.
        container.set_size_refs(
            header=self._header_box,
            bottom_band=bottom_band,
            form_floor=60,
        )

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
                # v0.8.0a29+: no_console_popen_kwargs() suppresses
                # the Windows console-window flash for custom-menu
                # commands that invoke console-subsystem programs.
                from ..core.runner import no_console_popen_kwargs
                act.triggered.connect(
                    lambda checked=False, c=cmd, d=cwd: _sp.Popen(
                        split_command(c), shell=False, cwd=d,
                        **no_console_popen_kwargs(),
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
                # v0.6.0 — a param with a choices_provider gets a small
                # per-param Refresh button beside it (the user may
                # open another drawing / container after the form is
                # up).  The ParamWidget itself stays the entry in
                # ``self._widgets`` so get/set_value is unchanged; we
                # wrap it + the button in a thin container row.
                row_widget: QWidget = widget
                if getattr(param, "choices_provider", None) is not None:
                    row_widget = self._wrap_with_refresh(param.id, widget)
                form.add_param_row(
                    param.id,
                    label_text,
                    row_widget,
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
                    from .wrapping_tab_bar import make_wrapping_tab_widget
                    current_tab_widget = make_wrapping_tab_widget()
                    self._section_tab_widgets.append(current_tab_widget)
                    # Right-click on the tab bar → context menu with
                    # "Wrap tabs" (for multi-row tab layout) and
                    # "Word wrap descriptions" (batch-toggle for every
                    # CheckboxWidget nested inside this tab widget's
                    # pages).
                    self._install_tab_context_menu(current_tab_widget)
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

        # v0.8.0a19 -- assign all of the trailing stretch to the LAST
        # inserted widget so the form area FILLS the available
        # vertical space.  Without this, the addStretch(1) at the
        # bottom of ``form_outer_layout`` swallows every spare pixel
        # and the section (whether a QTabWidget for tab-layout
        # sections like Find Missing Refs's Source / Matching /
        # Apply, a collapse-layout QGroupBox, or a flat
        # ReorderableParamForm) sits at its sizeHint with an empty
        # beige strip of form_group background below it.  Moving
        # the stretch onto the last widget makes the two areas
        # scale together: when the dock grows the param view grows
        # with it; when the dock shrinks the param view's own
        # scrollbar kicks in.
        n = self._form_outer_layout.count()
        if n >= 2:
            # Last widget sits at index ``n - 2`` (the trailing
            # stretch is at ``n - 1``).  Set its stretch to 1 and
            # zero out the trailing spacer so all leftover space
            # flows to the widget instead.
            self._form_outer_layout.setStretch(n - 2, 1)
            self._form_outer_layout.setStretch(n - 1, 0)

        # v0.6.0 — dynamic choice/value providers.  Runs AFTER every
        # widget exists so upstream lookups + topo population work.
        self._init_providers()

    # ==================================================================
    # v0.6.0 — dynamic provider orchestration
    # ==================================================================
    #
    # Design notes:
    #  * Providers run **synchronously**, bounded by
    #    ``ProviderSpec.timeout_sec``.  An async/threaded variant with
    #    a live spinner is a future refinement; synchronous keeps the
    #    integration into this 4k-line view deterministic + testable
    #    and the timeout caps the worst-case stall.
    #  * ``build_full_argv`` purity is untouched — providers only run
    #    in this form-population phase, never during argv assembly.
    #  * Failures fail **soft** per the contract: the param shows an
    #    error tooltip + (for choice widgets) a "(no items)" body,
    #    the rest of the form stays usable, Run is blocked only if
    #    the param is required (the existing required-check already
    #    treats an empty value as missing).

    def _wrap_with_refresh(
        self, param_id: str, widget: QWidget,
    ) -> QWidget:
        """Return a container = [widget(stretch), ⟳ refresh button].

        The ParamWidget remains the ``self._widgets`` entry; only the
        visual row is wrapped.  The button is disabled later if the
        ``dynamic_choices`` capability is denied.
        """
        from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget
        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(widget, stretch=1)
        btn = QToolButton()
        btn.setText("⟳")  # ⟳ clockwise open circle arrow
        btn.setToolTip("Refresh this field from its provider")
        btn.setAutoRaise(True)
        btn.clicked.connect(
            lambda _=False, pid=param_id: self._refresh_provider(
                pid, bypass_cache=True,
            )
        )
        lay.addWidget(btn)
        if not hasattr(self, "_provider_refresh_btns"):
            self._provider_refresh_btns = {}
        self._provider_refresh_btns[param_id] = btn
        return container

    def _provider_params(self) -> list[Any]:
        return [
            p for p in self._tool.params
            if getattr(p, "choices_provider", None) is not None
        ]

    def _init_providers(self) -> None:
        prov_params = self._provider_params()
        # L16 fix: a config change that alters hidden params re-runs
        # this method, which reassigned ``_provider_debounce`` to a
        # fresh dict and leaked the prior QTimers (parented to
        # ``self``, never stopped/deleted — they accumulate across
        # every config switch in a long-lived runner).  Tear the old
        # ones down before rebuilding.
        for _t in getattr(self, "_provider_debounce", {}).values():
            try:
                _t.stop()
                _t.deleteLater()
            except Exception:  # noqa: BLE001
                pass
        # Per-rebuild state.
        self._provider_cache: dict[str, Any] = {}
        self._provider_errors: dict[str, str] = {}
        self._provider_debounce: dict[str, Any] = {}
        if not prov_params:
            return

        from .permission_guards import perm_check
        self._providers_allowed = bool(perm_check("dynamic_choices"))

        if not self._providers_allowed:
            note = (
                "Dynamic choices disabled by policy "
                "(capability: dynamic_choices)."
            )
            for p in prov_params:
                w = self._widgets.get(p.id)
                if w is not None:
                    w.setEnabled(False)
                    w.setToolTip(note)
                btn = getattr(self, "_provider_refresh_btns", {}).get(p.id)
                if btn is not None:
                    btn.setEnabled(False)
                    btn.setToolTip(note)
            return

        # Form-level "Refresh all" — the driving use case (the user
        # opened another drawing/container after the form was up).
        self._add_refresh_all_button()

        # Initial population in dependency order.  on_open + on_change
        # both populate now; manual waits for a click.
        from scriptree.core.providers import provider_run_order
        try:
            order = provider_run_order(self._tool.params)
        except ValueError:
            # Structural errors are caught at load; defensive only.
            order = [p.id for p in prov_params]
        by_id = {p.id: p for p in self._tool.params}
        for pid in order:
            p = by_id.get(pid)
            if p is None or getattr(p, "choices_provider", None) is None:
                continue
            if p.choices_provider.refresh in ("on_open", "on_change"):
                self._run_provider(p)

        # Wire on_change cascades: when any upstream value changes,
        # debounce ~250 ms then re-run this provider.
        #
        # L15 fix: debounce is conceptually PER-PROVIDER, not
        # per-dependency.  The old code created one QTimer per
        # ``depends_on`` entry inside the inner loop and overwrote
        # ``_provider_debounce[p.id]`` each iteration — so a
        # multi-dep provider's earlier timers were orphaned
        # (untracked, un-stoppable, leaked on rebuild).  Create ONE
        # timer per provider and start() it from every dependency's
        # ``valueChanged``; ``_provider_debounce[p.id]`` is then the
        # single correct timer (and the only one to clean up).
        from PySide6.QtCore import QTimer
        for p in prov_params:
            if p.choices_provider.refresh != "on_change":
                continue
            dep_widgets = [
                self._widgets.get(dep) for dep in p.depends_on
            ]
            dep_widgets = [w for w in dep_widgets if w is not None]
            if not dep_widgets:
                continue
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(250)
            timer.timeout.connect(
                lambda pid=p.id: self._refresh_provider(
                    pid, bypass_cache=False,
                )
            )
            self._provider_debounce[p.id] = timer
            for dep_w in dep_widgets:
                dep_w.valueChanged.connect(
                    lambda _v=None, t=timer: t.start()
                )

    def _add_refresh_all_button(self) -> None:
        if getattr(self, "_refresh_all_added", False):
            return
        from PySide6.QtWidgets import QPushButton
        btn = QPushButton("⟳  Refresh dynamic fields")
        btn.setToolTip(
            "Re-run every dynamic field's provider (e.g. after you "
            "open another document in the external app)."
        )
        btn.clicked.connect(self._refresh_all_providers)
        # Top of the form area (index 0; the trailing stretch keeps
        # the rest below).
        self._form_outer_layout.insertWidget(0, btn)
        self._refresh_all_added = True

    def _upstream_values(self, param: Any) -> dict[str, str]:
        """Current values of ``param.depends_on``, coerced to strings
        (a list value is comma-joined — same shape the runner emits)."""
        out: dict[str, str] = {}
        for dep in getattr(param, "depends_on", []) or []:
            w = self._widgets.get(dep)
            if w is None:
                continue
            v = w.get_value()
            if isinstance(v, (list, tuple)):
                out[dep] = ",".join(str(x) for x in v)
            else:
                out[dep] = "" if v is None else str(v)
        return out

    def _run_provider(
        self, param: Any, *, bypass_cache: bool = False,
    ) -> None:
        from scriptree.core.providers import resolve_provider
        spec = param.choices_provider
        upstream = self._upstream_values(param)
        cache_key = (
            tuple(spec.command),
            tuple(sorted(upstream.items())),
        )
        use_cache = (
            spec.cache == "form_session" and not bypass_cache
        )
        if use_cache and param.id in self._provider_cache:
            cached_key, cached_res = self._provider_cache[param.id]
            if cached_key == cache_key:
                self._apply_provider_result(param, cached_res)
                return

        result = resolve_provider(
            spec,
            param_id=param.id,
            param_type=param.type,
            upstream_values=upstream,
            tool_file=getattr(self._tool, "loaded_from", None),
            env=None,  # inherit process env (PATH-prepend parity is
                       # a documented v1 limitation — see the
                       # dynamic_providers doc)
        )
        if spec.cache == "form_session":
            self._provider_cache[param.id] = (cache_key, result)
        self._apply_provider_result(param, result)

    def _apply_provider_result(self, param: Any, result: Any) -> None:
        w = self._widgets.get(param.id)
        if w is None:
            return
        if not result.ok:
            self._provider_errors[param.id] = result.error
            tip = result.error
            if result.detail:
                tip += "\n\n" + result.detail
            w.setToolTip(tip)
            # Choice widgets: empty the list so it visibly reads
            # "(no items)"; scalar widgets keep whatever they had.
            if hasattr(w, "set_choices"):
                try:
                    w.set_choices([], [], None)
                except Exception:  # noqa: BLE001
                    pass
            self._update_live_cmd()
            return
        self._provider_errors.pop(param.id, None)
        if result.is_scalar:
            w.set_value(result.value)
        elif hasattr(w, "set_choices"):
            w.set_choices(
                result.choices, result.choice_labels, result.default,
            )
        # Restore the description tooltip on success.
        if getattr(param, "description", ""):
            w.setToolTip(param.description)
        self._update_live_cmd()

    def _refresh_provider(
        self, param_id: str, *, bypass_cache: bool = True,
    ) -> None:
        if not getattr(self, "_providers_allowed", True):
            return
        by_id = {p.id: p for p in self._tool.params}
        p = by_id.get(param_id)
        if p is None or getattr(p, "choices_provider", None) is None:
            return
        self._run_provider(p, bypass_cache=bypass_cache)
        # A refreshed upstream may feed dependents — re-run any
        # on_change provider that depends on this one.
        for other in self._provider_params():
            if (other.choices_provider.refresh == "on_change"
                    and param_id in (other.depends_on or [])):
                self._run_provider(other, bypass_cache=bypass_cache)

    def _refresh_all_providers(self) -> None:
        if not getattr(self, "_providers_allowed", True):
            return
        from scriptree.core.providers import provider_run_order
        try:
            order = provider_run_order(self._tool.params)
        except ValueError:
            order = [p.id for p in self._provider_params()]
        by_id = {p.id: p for p in self._tool.params}
        for pid in order:
            p = by_id.get(pid)
            if p is not None and getattr(p, "choices_provider", None):
                self._run_provider(p, bypass_cache=True)

    def _install_tab_context_menu(self, tab_widget: QTabWidget) -> None:
        """Wire a right-click context menu onto ``tab_widget``'s tab bar.

        Two actions:

        - **Wrap tabs onto multiple rows** — toggles the
          ``WrappingTabBar``'s multi-row mode. When on (default), tabs
          flow onto additional rows instead of the classic Qt behavior
          of single-row-plus-scroll-arrows.
        - **Word wrap descriptions** — batch-toggle for every
          ``CheckboxWidget`` descendant of the tab widget (across all
          pages, not just the currently visible one). The check mark
          reflects the current state, sampled from the first checkbox.
        """
        from .widgets.param_widgets import CheckboxWidget
        from .wrapping_tab_bar import WrappingTabBar

        tab_bar = tab_widget.tabBar()
        tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        def _show_menu(pos):
            from PySide6.QtGui import QAction
            from PySide6.QtWidgets import QMenu

            boxes = tab_widget.findChildren(CheckboxWidget)
            current_wrap_desc = (
                boxes[0]._desc_label.wordWrap() if boxes else True
            )

            menu = QMenu(tab_bar)

            if isinstance(tab_bar, WrappingTabBar):
                wrap_tabs_act = QAction("Wrap tabs onto multiple rows", menu)
                wrap_tabs_act.setCheckable(True)
                wrap_tabs_act.setChecked(tab_bar.wrap_enabled())
                wrap_tabs_act.toggled.connect(tab_bar.set_wrap)
                menu.addAction(wrap_tabs_act)
                menu.addSeparator()

            desc_act = QAction("Word wrap descriptions", menu)
            desc_act.setCheckable(True)
            desc_act.setChecked(current_wrap_desc)

            def _toggle_desc(on: bool) -> None:
                for box in boxes:
                    box.set_word_wrap(on)

            desc_act.toggled.connect(_toggle_desc)
            menu.addAction(desc_act)
            menu.exec(tab_bar.mapToGlobal(pos))

        tab_bar.customContextMenuRequested.connect(_show_menu)

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

        v0.4.0 — also treats params hidden by ``visible_when`` as
        empty for argv purposes: their stored value is dropped from
        the returned dict so the argument-template
        conditional-emission rules (``{id?--flag}`` etc.) skip them
        naturally.  The widget's actual value PERSISTS in memory
        for re-show — only its contribution to the current argv is
        suppressed.
        """
        values = {pid: w.get_value() for pid, w in self._widgets.items()}
        # Merge in hidden param values from the active configuration.
        hidden = getattr(self, "_active_hidden_params", [])
        if hidden:
            cfg, _set, _storage = self._active_config_and_set()
            if cfg is not None:
                for pid in hidden:
                    if pid not in values and pid in cfg.values:
                        values[pid] = cfg.values[pid]
        # Drop visible_when-hidden params for argv assembly.  See
        # ``_visible_when_hidden_ids`` for the source of truth.
        for pid in self._visible_when_hidden_ids():
            values.pop(pid, None)
        return values

    def _visible_when_hidden_ids(self) -> set[str]:
        """Return the set of param IDs currently hidden by
        ``visible_when``.  Computed by evaluating each param's
        expression against the current widget values (BEFORE this
        method's filtering — we want a snapshot of all entries,
        including the hidden ones, when deciding what's visible).
        """
        from scriptree.core.visible_when import evaluate as _evaluate
        # Raw values BEFORE filtering (so an expression like
        # ``"a == 'x'"`` can see ``a`` even when ``a`` is itself
        # currently hidden).
        raw = {pid: w.get_value() for pid, w in self._widgets.items()}
        hidden_ids: set[str] = set()
        for param in self._tool.params:
            expr = (getattr(param, "visible_when", "") or "").strip()
            if not expr:
                continue
            if not _evaluate(expr, raw):
                hidden_ids.add(param.id)
        return hidden_ids

    def _refresh_visible_when(self) -> None:
        """Apply ``visible_when`` to the form: hide/show rows.

        Called from ``_update_live_cmd`` so every value change
        re-evaluates visibility.  Cheap — the evaluator is a
        single-pass parser, run once per param with a
        ``visible_when`` expression (usually a handful per tool).
        """
        if not self._widgets:
            return
        hidden = self._visible_when_hidden_ids()
        for form in self._section_forms.values():
            for param in self._tool.params:
                # Only call set_row_hidden when the param actually
                # has a row in this form — set_row_hidden is a
                # find-and-no-op otherwise but skipping the call
                # avoids burning cycles on every section x every
                # param on every keystroke.
                form.set_row_hidden(param.id, param.id in hidden)

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

        Cross-platform quoting matches ``ResolvedCommand.display()``:
        double quotes on Windows (``subprocess.list2cmdline`` — native
        convention, safe to paste into cmd.exe), single quotes on POSIX
        (``shlex.quote`` — standard).
        """
        if not cmd.argv:
            return ""
        argv = list(cmd.argv)
        if not self._show_full_path:
            argv[0] = Path(argv[0]).name
        import sys
        if sys.platform == "win32":
            import subprocess
            return subprocess.list2cmdline(argv)
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
        # v0.6.0 — provider on_open population runs inside
        # ``_populate_form_rows`` (form-build phase), which finishes
        # *before* the live-command widget is created.  set_choices /
        # set_value emit ``valueChanged`` during that population, so
        # this can be called early.  No-op until the preview widget
        # exists; __init__ does a definitive _update_live_cmd() once
        # the whole view is constructed.
        if not hasattr(self, "_live_cmd"):
            return
        # v0.4.0 — refresh visible_when-driven row visibility before
        # collecting values, so the argv preview matches what the
        # user actually sees.  Cheap (recursive-descent parser over
        # a handful of expressions); safe to run on every change.
        self._refresh_visible_when()
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

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        """Enable or disable every action button at once.

        Called by ``_start_run`` / ``_start_action`` to lock the row
        while a subprocess is in flight, and by ``_on_finished`` (and
        the action's own completion handler) to re-enable on
        finish.  No-op when ``self._tool.actions`` is empty (the
        button list is empty too).
        """
        for btn in getattr(self, "_action_btns", []) or []:
            btn.setEnabled(enabled)

    def _start_action(self, action_id: str) -> None:
        """Spawn the named action (V3 v0.8.0a11+).

        Mirrors ``_start_run``'s spawn path -- same worker thread,
        same ``stdoutLine`` / ``stderrLine`` / ``finished`` signals,
        same Run / Stop / action-button enable wiring -- but uses
        ``build_full_action_argv`` instead of ``build_full_argv`` so
        the literal action argv is appended without form-value
        substitution.  Output streams to the same pane, prefixed
        with a "▶ Action: <label>\\n" separator so the session log
        stays readable across multiple action firings.

        The same ``run_tools`` capability gate applies -- an action
        is just a different argv for the same tool, so denying
        ``run_tools`` denies actions too.

        v1 deliberately skips the form-value sanitization / extras /
        live-cmd-editor branches of ``_start_run``: actions don't
        consume any of those, so re-running that machinery here would
        be cargo-cult.  The path the action argv travels is literally
        ``ActionDef.argv -> build_full_action_argv -> spawn``.

        Concurrent runs are prevented the same way ``_start_run``
        does -- ``self._thread is not None`` short-circuits.
        """
        from .permission_guards import perm_check
        if not perm_check("run_tools"):
            QMessageBox.warning(
                self, "Action not permitted",
                "Running tools is disabled by your administrator "
                "(capability: run_tools).",
            )
            return
        if self._thread is not None:
            return  # a Run or another action is already in flight

        # Look up the ActionDef so we have the label/popup mode for
        # output formatting + the result-popup decision.
        action_def = None
        for a in self._tool.actions:
            if a.id == action_id:
                action_def = a
                break
        if action_def is None:
            QMessageBox.warning(
                self, "Unknown action",
                f"This tool has no action named {action_id!r}.",
            )
            return

        # Confirm prompt for destructive actions (``confirm`` set).
        if action_def.confirm:
            reply = QMessageBox.question(
                self, f"{self._tool.name} — {action_def.label}",
                action_def.confirm,
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Ok:
                return

        # Build the command via the same machinery Run uses, just
        # routed through the action-specific resolver so the literal
        # argv (no form-value substitution) lands in the spawned
        # process.
        try:
            from ..core.runner import build_full_action_argv
            cfg, _set, _storage = self._active_config_and_set()
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

            cmd = build_full_action_argv(
                self._tool, action_id,
                config_env=cfg.env if cfg else None,
                config_path_prepend=cfg.path_prepend if cfg else None,
                global_env=_g_env or None,
                global_env_overrides=_g_env_override,
                global_path_prepend=_g_path or None,
                global_path_overrides=_g_path_override,
                tree_path_prepend=self._tree_path_prepend or None,
            )
        except RunnerError as e:
            QMessageBox.warning(self, "Action error", str(e))
            return

        # Separator + the action argv preview, so a user reading the
        # output pane after several actions can tell what fired when.
        self._append_line(
            f"▶ Action: {action_def.label}",
            color=QColor("#0050a0"),
        )
        self._append_line(f"$ {cmd.display()}\n")

        # Remember which action is running so the finish handler can
        # show the copy-friendly popup if the producer asked for one.
        # (Phase D will wire the popup; storing the ref here lets
        # Phase D land as a no-op-elsewhere change.)
        self._active_action = action_def
        self._action_stdout_buffer: list[str] = []

        # Disable Run + every other action button while this one is
        # in flight; enable Stop.  ``_on_finished`` flips them back.
        self._btn_run.setEnabled(False)
        self._set_action_buttons_enabled(False)
        self._btn_stop.setEnabled(True)
        self._btn_stop.setText("Stop")
        self._status.setText(f"Running action: {action_def.label}…")

        self._thread = QThread(self)
        self._worker = _RunWorker(cmd, credentials=None, interactive=False)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.stdoutLine.connect(self._on_action_stdout)
        self._worker.stderrLine.connect(self._on_stderr)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()
        self.runningChanged.emit(self._file_path or "", True)

    def _on_action_stdout(self, line: str) -> None:
        """Stdout handler for action runs.

        Routes to the same output pane as Run's ``_on_stdout`` AND
        buffers the line for the result popup (Phase D).  The
        existing ``_on_stdout`` would also buffer for the popup if
        we routed there directly, but keeping a dedicated handler
        for actions makes the code path obvious and lets Phase D
        attach its result-popup logic without touching Run.
        """
        self._on_stdout(line)
        if hasattr(self, "_action_stdout_buffer"):
            self._action_stdout_buffer.append(line)

    def _start_run(self) -> None:
        # ``run_tools`` capability gate (V3 v0.3.3) — call-time check
        # so keyboard shortcuts and programmatic invocations are gated
        # in addition to the already-greyed-out Run button.
        from .permission_guards import perm_check
        if not perm_check("run_tools"):
            QMessageBox.warning(
                self, "Run not permitted",
                "Running tools is disabled by your administrator "
                "(capability: run_tools).",
            )
            return
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
        # Capability lookup BEFORE sanitization so the path-security
        # trio (allow_path_traversal / access_sensitive_paths /
        # allow_symlinks) can suppress their respective warnings
        # when the admin has granted them.  Default deny → strict.
        perms = get_app_permissions()
        if self._file_path:
            from ..core.permissions import load_permissions
            perms = load_permissions(file_path=self._file_path)
        # Use the detailed sanitizer so each warning carries the
        # source field id — needed for the v0.3.4 per-field
        # suppression feature.
        from ..core.sanitize import sanitize_all_values_detailed
        detailed_warnings: list[tuple[str, str]] = sanitize_all_values_detailed(
            {k: str(v) for k, v in values.items() if v},
            path_fields=path_ids,
            labels=labels,
            allow_traversal=perms.can("allow_path_traversal"),
            allow_sensitive=perms.can("access_sensitive_paths"),
        )
        warnings = [w for w, _fid in detailed_warnings]

        # ``allow_symlinks`` capability gate (V3 v0.3.3): when DENIED,
        # check the resolved executable path for symlink components
        # and surface a warning to the same dialog.  Symlink resolution
        # requires disk I/O so we limit it to the executable here
        # (not every form-value path), keeping the run-start fast.
        if not perms.can("allow_symlinks"):
            from ..core.sanitize import validate_resolved_path
            from pathlib import Path as _Path
            try:
                exe_path = self._tool.executable or ""
                if exe_path:
                    resolved = _Path(exe_path).expanduser().resolve()
                    base = (
                        _Path(self._tool.loaded_from).parent
                        if self._tool.loaded_from else resolved.parent
                    )
                    sym_warnings = validate_resolved_path(
                        resolved, base,
                        allow_symlinks=False,
                        allow_traversal=True,  # already checked above
                    )
                    # Symlink warnings are tagged with the synthetic
                    # field id ``__exe__`` so per-field mute can target
                    # them.
                    for w in sym_warnings:
                        detailed_warnings.append((w, "__exe__"))
            except (OSError, RuntimeError, ValueError):
                # Resolution failed (broken symlink, network drive
                # offline, etc.) — skip silently rather than block.
                pass

        editor_protection = perms.can(
            "injection_protection_on_editor"
        )

        if editor_protection:
            # Also sanitize extras and command-line editor content.
            from ..core.sanitize import sanitize_value
            for token in self._extras:
                r = sanitize_value(token, field_label="Extra arguments")
                for w in r.warnings:
                    detailed_warnings.append((w, "__extras__"))
            cmd_text = self._live_cmd.toPlainText().strip()
            if cmd_text:
                r = sanitize_value(cmd_text, field_label="Command line")
                for w in r.warnings:
                    detailed_warnings.append((w, "__cmdline__"))

        # ``suppress_sanitization_warnings`` filtering (V3 v0.3.4).
        # Three suppression scopes:
        #   1. Globally muted    -> skip dialog entirely.
        #   2. This tool muted   -> skip dialog entirely.
        #   3. Per-field muted   -> drop those warnings; if none
        #                           remain after the drop, also skip.
        from ..core import sanitize_suppression as _supp
        if detailed_warnings:
            if _supp.should_skip_dialog(self._file_path):
                detailed_warnings = []
            else:
                texts = [w for w, _f in detailed_warnings]
                fids = [f for _w, f in detailed_warnings]
                kept_texts = _supp.filter_warnings(
                    self._file_path, texts, fids,
                )
                if len(kept_texts) != len(detailed_warnings):
                    kept_q: list[str] = list(kept_texts)
                    new_pairs: list[tuple[str, str]] = []
                    for text, fid in detailed_warnings:
                        if kept_q and kept_q[0] == text:
                            new_pairs.append((text, fid))
                            kept_q.pop(0)
                    detailed_warnings = new_pairs

        warnings = [w for w, _f in detailed_warnings]

        if detailed_warnings:
            warning_fids = [f for _w, f in detailed_warnings]
            detail = "\n".join(f"\u2022 {w}" for w in warnings)
            if not self._show_injection_warning(
                detail, editor_protection, perms,
                warning_fids=warning_fids,
            ):
                return

        try:
            # Thread per-configuration env overrides into the resolve
            # so the child process inherits tool + config env layers.
            cfg, _set, _storage = self._active_config_and_set()
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
                tree_path_prepend=self._tree_path_prepend or None,
            )
        except RunnerError as e:
            QMessageBox.warning(self, "Validation error", str(e))
            return

        # --- executable existence pre-check ---
        # Catch the most common run failure (the tool's executable file
        # was moved/renamed/deleted) before Popen and offer a recovery
        # dialog, the same way tree leaves do. If the executable is a
        # bare name resolved via PATH we skip the check — shutil.which
        # handles PATH resolution in a way that's equivalent to what
        # the OS does.
        exe_path = cmd.argv[0] if cmd.argv else ""
        if exe_path and self._executable_seems_missing(exe_path):
            # Reset before each call so a previous recovery's override
            # doesn't bleed into this run.
            self._recovery_argv0_override = None
            if not self._offer_missing_executable_recovery(exe_path):
                return
            # Recovery may have set tool.executable directly (REPLACE
            # scope) or pinned a one-shot override (PATH-add scopes).
            # Prefer the override when present — for PATH-add scopes
            # tool.executable is now a bare name, but argv[0] for THIS
            # run should be the absolute path the user just picked.
            if cmd.argv:
                override = getattr(self, "_recovery_argv0_override", None)
                cmd.argv[0] = override or self._tool.executable

        # --- credential prompt (run-as-different-user) ---
        credentials: tuple[str, str, str] | None = None
        if cfg is not None and cfg.prompt_credentials:
            # ``run_as_different_user`` gate (V3 v0.3.3): when denied,
            # the configuration's prompt_credentials flag is ignored
            # and the tool runs under the current user's context.  We
            # surface a one-line warning to the output pane so the
            # discrepancy is visible.
            if not perm_check("run_as_different_user"):
                self._append_line(
                    "[run_as_different_user disabled] This configuration "
                    "requested credentials but the capability is not "
                    "granted.  Running under the current user.",
                    color=QColor("#b8860b"),
                )
            else:
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

        # Interactive-stdin gating: tool must have ``interactive=True``
        # AND the ``interactive_stdin`` capability must be granted.
        # When the tool opted in but the permission denies, surface a
        # one-line warning before the run so the user knows why the
        # send-line widget didn't appear.
        tool_opted_in = bool(getattr(self._tool, "interactive", False))
        run_interactive = False
        if tool_opted_in:
            if perms.can("interactive_stdin"):
                run_interactive = True
            else:
                self._append_line(
                    "[interactive disabled] This tool requested "
                    "interactive stdin, but the 'interactive_stdin' "
                    "permission is not granted.  Running non-"
                    "interactively.",
                    color=QColor("#b8860b"),  # dark goldenrod
                )
        # Refresh visibility now in case the user toggled the
        # permission between sessions; an inactive run keeps the
        # row hidden until permission and tool flag agree.
        self._refresh_interactive_visibility()

        self._btn_run.setEnabled(False)
        # Disable action buttons too -- Run holds the worker lock, so
        # actions can't fire concurrently.  ``_on_finished`` flips
        # them back when the run completes.
        self._set_action_buttons_enabled(False)
        self._btn_stop.setEnabled(True)
        self._btn_stop.setText("Stop")
        self._status.setText("Running…")

        self._thread = QThread(self)
        self._worker = _RunWorker(
            cmd, credentials=credentials, interactive=run_interactive,
        )
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

    @staticmethod
    def _executable_seems_missing(exe_path: str) -> bool:
        """Heuristic: does the executable not exist?

        - If ``exe_path`` contains a path separator, check the file
          directly (doesn't exist → missing).
        - Otherwise it's a bare name like ``python`` or ``robocopy``;
          ask ``shutil.which`` to resolve it via PATH. Only flag as
          missing if ``which`` returns None (i.e. it's not on PATH).
        """
        import shutil
        if "/" in exe_path or "\\" in exe_path or ":" in exe_path:
            return not Path(exe_path).exists()
        return shutil.which(exe_path) is None

    def _offer_missing_executable_recovery(self, exe_path: str) -> bool:
        """Show recovery dialog for a missing tool executable.

        Returns True if the user picked a recovery action that allows
        the run to proceed (file replacement, or a PATH-add scope that
        makes the executable resolvable). Returns False if the user
        dismissed.

        The dialog is opened in "scope-picker" mode — instead of just
        offering a path replacement, the user can choose to keep the
        bare executable name and add the parent folder to a search
        path at one of several scopes. See
        ``ui/recovery_dialog.py`` for the full UX.
        """
        from .recovery_dialog import (
            MissingFileRecoveryDialog,
            PathScopeOptions,
            SCOPE_REPLACE_FILE, SCOPE_SESSION,
            SCOPE_SCRIPTREE, SCOPE_SCRIPTREETREE,
            SCOPE_USER_PATH, SCOPE_SYSTEM_PATH,
        )
        from ..core.permissions import get_app_permissions
        from ..core.io import save_tool
        from ..core import path_env

        perms = get_app_permissions()
        can_replace = (
            perms.can("edit_tool_definition")
            and perms.can("save_scriptree")
            and not self._read_only
        )

        # Gather context for the scope picker. The main window owns
        # the launcher tree (sidebar) and the optionally-loaded
        # .scriptreetree path; we pull those via _gather_path_scope_context.
        ctx = self._gather_path_scope_context()
        scope_opts = PathScopeOptions(
            scriptree_path=self._file_path,
            scriptreetree_path=ctx["tree_path"],
            all_scriptrees=ctx["all_scriptrees"],
            all_scriptreetrees=ctx["all_scriptreetrees"],
            permissions=perms,
        )

        dlg = MissingFileRecoveryDialog(
            self,
            title="Executable not found",
            message=(
                "The tool's executable could not be located. This "
                "usually means the program was moved, renamed, or "
                "uninstalled since this tool was set up. Browse to "
                "find it, then choose how ScripTree should remember "
                "the new location."
            ),
            missing_path=exe_path,
            allow_replace=can_replace,
            file_filter="Executables (*.exe *.bat *.cmd *.py *.sh);;All files (*)",
            browse_caption="Select replacement executable",
            path_scope_options=scope_opts,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False

        new_path = dlg.selected_replacement()
        if not new_path:
            return False

        scope = dlg.selected_scope()
        directory = dlg.selected_directory()
        apply_all = dlg.apply_to_all()

        # ------------------------------------------------------------
        # SCOPE_REPLACE_FILE — v1 behavior: bake the absolute path into
        # tool.executable and save.
        # ------------------------------------------------------------
        if scope == SCOPE_REPLACE_FILE or scope is None:
            self._tool.executable = str(Path(new_path).resolve())
            if self._file_path:
                try:
                    save_tool(self._tool, self._file_path)
                except Exception as e:  # noqa: BLE001
                    QMessageBox.warning(
                        self, "Save failed",
                        f"Updated the executable path but couldn't "
                        f"save the tool file:\n{e}\n\n"
                        "The change will be lost when ScripTree "
                        "restarts.",
                    )
            return True

        # ------------------------------------------------------------
        # PATH-add scopes — the user picked "don't bake an absolute
        # path; resolve via search path instead". For that to actually
        # work we have to (a) make sure the search path being chosen
        # actually contains the directory, AND (b) rewrite
        # tool.executable to the bare basename so OS path lookup is
        # used. Without (b) the runner keeps spawning the original
        # missing absolute path and PATH never gets consulted.
        # ------------------------------------------------------------
        if directory is None:
            return False

        # Snapshot the basename from the file the user just picked. We
        # rewrite tool.executable to this for every PATH-add scope so
        # search-path lookup actually engages. The full absolute path
        # is also assigned to argv[0] for THIS run so we don't have to
        # re-trigger the same recovery loop after the search path
        # change has only just landed.
        new_full_path = str(Path(new_path).resolve())
        new_basename = Path(new_full_path).name

        applied: list[str] = []
        errors: list[str] = []

        def _record(label: str, result: path_env.ScopeResult) -> None:
            if result.ok:
                applied.append(f"{label}: {result.message}")
            else:
                errors.append(f"{label}: {result.message}")

        # Persistent scopes change the .scriptree (tool.executable
        # becomes the basename so PATH lookup fires next launch). The
        # session-only scope leaves the .scriptree alone — the user
        # explicitly opted into a transient fix.
        scriptree_persisted = False

        if scope == SCOPE_SESSION:
            _record("session", path_env.add_to_session_path(directory))

        elif scope == SCOPE_SCRIPTREE:
            # Update the in-memory ToolDef so the env editor and any
            # future Save reflect the change immediately, then save.
            existing_pp = list(self._tool.path_prepend or [])
            if directory not in existing_pp:
                self._tool.path_prepend = existing_pp + [directory]
            self._tool.executable = new_basename
            if self._file_path:
                try:
                    save_tool(self._tool, self._file_path)
                    applied.append(
                        f".scriptree {Path(self._file_path).name}: "
                        f"path_prepend += {directory}, executable = "
                        f"{new_basename}"
                    )
                    scriptree_persisted = True
                except Exception as e:  # noqa: BLE001
                    errors.append(
                        f".scriptree {Path(self._file_path).name}: "
                        f"save failed: {e}"
                    )
            # Bulk-apply to other .scriptrees in the sidebar (the
            # current one is already handled in-memory above).
            if apply_all:
                for t in ctx["all_scriptrees"]:
                    if t == self._file_path:
                        continue
                    _record(
                        f".scriptree {Path(t).name}",
                        path_env.add_to_scriptree_path_prepend(t, directory),
                    )

        elif scope == SCOPE_SCRIPTREETREE:
            targets = (
                ctx["all_scriptreetrees"]
                if apply_all and ctx["all_scriptreetrees"]
                else ([ctx["tree_path"]] if ctx["tree_path"] else [])
            )
            for t in targets:
                _record(
                    f".scriptreetree {Path(t).name}",
                    path_env.add_to_scriptreetree_path_prepend(t, directory),
                )
            # Tool's executable still needs to be a bare name for the
            # tree's path_prepend to find it.
            self._tool.executable = new_basename
            if self._file_path:
                try:
                    save_tool(self._tool, self._file_path)
                    applied.append(
                        f".scriptree {Path(self._file_path).name}: "
                        f"executable = {new_basename}"
                    )
                    scriptree_persisted = True
                except Exception as e:  # noqa: BLE001
                    errors.append(
                        f".scriptree {Path(self._file_path).name}: "
                        f"save failed: {e}"
                    )

        elif scope == SCOPE_USER_PATH:
            _record("user PATH", path_env.add_to_user_path(directory))
            self._tool.executable = new_basename
            if self._file_path:
                try:
                    save_tool(self._tool, self._file_path)
                    applied.append(
                        f".scriptree {Path(self._file_path).name}: "
                        f"executable = {new_basename}"
                    )
                    scriptree_persisted = True
                except Exception as e:  # noqa: BLE001
                    errors.append(
                        f".scriptree {Path(self._file_path).name}: "
                        f"save failed: {e}"
                    )

        elif scope == SCOPE_SYSTEM_PATH:
            _record("system PATH", path_env.add_to_system_path(directory))
            self._tool.executable = new_basename
            if self._file_path:
                try:
                    save_tool(self._tool, self._file_path)
                    applied.append(
                        f".scriptree {Path(self._file_path).name}: "
                        f"executable = {new_basename}"
                    )
                    scriptree_persisted = True
                except Exception as e:  # noqa: BLE001
                    errors.append(
                        f".scriptree {Path(self._file_path).name}: "
                        f"save failed: {e}"
                    )

        # Always also prepend to the running session — without this
        # the current Run can't pick up the new directory and the
        # user has to re-launch ScripTree to test their fix. Guarded
        # by the same permission as the dedicated session scope so
        # IT can keep an extra-tight environment if they want to.
        if scope != SCOPE_SESSION and perms.can("add_to_session_path"):
            path_env.add_to_session_path(directory)

        # For THIS run only: pin argv[0] to the absolute new path. The
        # caller reads `_recovery_argv0_override` and rewrites the
        # already-built argv. This avoids any race where the search
        # path change (registry, .scriptree path_prepend, etc.) hasn't
        # propagated to the subprocess context yet.
        self._recovery_argv0_override = new_full_path

        # Surface the result. We mirror error vs. partial-success in
        # the popup so the user can tell whether their .scriptree got
        # rewritten or not.
        if errors:
            QMessageBox.warning(
                self, "Some changes failed",
                "Successful:\n  " + "\n  ".join(applied or ["(none)"])
                + "\n\nFailed:\n  " + "\n  ".join(errors),
            )
            # Even if some persistent steps failed, the run can still
            # proceed if argv0 was pinned to the absolute path.
            return scriptree_persisted or scope == SCOPE_SESSION
        if applied and hasattr(self, "_status") and self._status is not None:
            self._status.setText(
                f"\u2713 {len(applied)} change(s) applied"
            )
        return True

    def _gather_path_scope_context(self) -> dict:
        """Collect IDE-wide context for the scope picker.

        Walks up to find the main window and pulls (a) the path of
        the loaded .scriptreetree (if any), and (b) lists of all
        currently loaded .scriptree / .scriptreetree files in the
        sidebar. Returns plain dicts/lists so the dialog stays
        decoupled from the main window's API.
        """
        result = {
            "tree_path": None,
            "all_scriptrees": [],
            "all_scriptreetrees": [],
        }

        # Walk up parent chain looking for the MainWindow.
        parent = self.parent()
        main_window = None
        while parent is not None:
            # Avoid hard import — duck-type on a sentinel attribute.
            if hasattr(parent, "_launcher") and hasattr(parent, "_runners"):
                main_window = parent
                break
            parent = parent.parent() if hasattr(parent, "parent") else None

        if main_window is None:
            return result

        # Loaded tree path lives on the launcher.
        try:
            tree_file = getattr(main_window._launcher, "_tree_file", None)
            if tree_file:
                result["tree_path"] = str(tree_file)
                result["all_scriptreetrees"] = [str(tree_file)]
        except Exception:  # noqa: BLE001
            pass

        # Loaded .scriptree files = the runner cache keys + the
        # currently-open one if it's not in the cache yet.
        try:
            paths = set()
            for runner in main_window._runners.values():
                fp = getattr(runner, "_file_path", None)
                if fp:
                    paths.add(str(fp))
            if self._file_path:
                paths.add(self._file_path)
            result["all_scriptrees"] = sorted(paths)
        except Exception:  # noqa: BLE001
            pass

        return result

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
        cfg, _set, _storage = self._active_config_and_set()
        if cfg is None or not cfg.prompt_credentials:
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
        # Re-enable every action button.  Symmetric to the disable
        # in ``_start_run`` / ``_start_action``.
        self._set_action_buttons_enabled(True)
        self._btn_stop.setEnabled(False)
        self._btn_stop.setText("Stop")
        self._status.setText(
            f"Finished — exit {exit_code} in {duration:.2f}s"
        )
        self.runningChanged.emit(self._file_path or "", False)

        # Phase D popup hook: if this finish was an action run AND
        # the action asked for a popup, show the copy-friendly
        # result dialog.  The actual dialog class lands in Phase D;
        # for now this branch is a no-op when the dialog module is
        # not yet importable.
        active_action = getattr(self, "_active_action", None)
        if active_action is not None:
            try:
                from .action_result_dialog import maybe_show_action_result
                maybe_show_action_result(
                    parent=self,
                    tool_name=self._tool.name,
                    action=active_action,
                    output_lines=getattr(
                        self, "_action_stdout_buffer", []
                    ),
                    exit_code=exit_code,
                )
            except ImportError:
                # action_result_dialog hasn't landed yet -- silent
                # fall-through is intentional so Phase D can ship
                # without touching this block.
                pass
            self._active_action = None
            self._action_stdout_buffer = []

        # Popup dialogs when output pane is hidden.
        _cfg, _set, _storage = self._active_config_and_set()
        vis = _cfg.ui_visibility if _cfg is not None else UIVisibility()
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

    # --- interactive stdin (v0.3.0) -------------------------------------

    def _on_send_line(self) -> None:
        """User clicked Send (or hit Enter in the input box).

        Pull the typed text, route through the worker's
        ``send_line``, then clear the box and refocus it for the
        next response.  Echo the sent line into the output pane in
        a dim colour so the conversation is self-documenting.
        """
        edit = getattr(self, "_send_line_edit", None)
        if edit is None:
            return
        text = edit.text()
        edit.clear()
        edit.setFocus()
        self._send_text_to_worker(text)

    def _send_quick_response(self, text: str) -> None:
        """User clicked one of the y/n/!/q quick-response buttons.

        Sends ``text`` immediately without consulting the line edit.
        Refocuses the line edit so the next typed key keeps flowing.
        """
        self._send_text_to_worker(text)
        edit = getattr(self, "_send_line_edit", None)
        if edit is not None:
            edit.setFocus()

    def _send_text_to_worker(self, text: str) -> None:
        """Common dispatch for both Send button and quick-response."""
        worker = self._worker
        if worker is None:
            self._append_line(
                "[send] No process is running.",
                color=QColor("#666666"),
            )
            return
        ok = worker.send_line(text)
        if not ok:
            self._append_line(
                "[send] Could not write to the tool's stdin "
                "(pipe closed or process exited).",
                color=QColor("#b00020"),
            )
            return
        # Echo the line we just sent.  Use the same colour as the
        # ``$ <command>`` echo so the user can scan the conversation.
        self._append_line(
            f"> {text}",
            color=QColor("#1976d2"),
        )

    def _on_end_input(self) -> None:
        """User clicked End input — close the child's stdin pipe."""
        worker = self._worker
        if worker is None:
            return
        worker.close_stdin()
        self._append_line("[stdin closed]", color=QColor("#666666"))

    # --- helpers ---------------------------------------------------------

    def _append_line(self, line: str, *, color: QColor | None = None) -> None:
        line = _strip_ansi(line)
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
        *,
        warning_fids: list[str] | None = None,
    ) -> bool:
        """Show the injection warning dialog. Returns True to proceed.

        v0.3.4+ — when the ``suppress_sanitization_warnings``
        capability is granted, three "Don't warn again" checkboxes
        appear at the bottom of the dialog:

        * **For these field(s)** — silence further warnings whose
          source field is in ``warning_fids`` (in this same tool).
        * **For this tool** — silence every warning from this tool.
        * **For all tools** — global mute.

        On Yes / Proceed the chosen scopes are written to QSettings
        via the ``sanitize_suppression`` module.  Re-enable later
        via Edit -> Sanitization warnings... in the main window.
        """
        from PySide6.QtWidgets import (
            QApplication,
            QCheckBox,
            QDialogButtonBox,
        )
        from .permission_guards import perm_check
        from ..core import sanitize_suppression as _supp

        # Build a custom dialog so we can append the suppression
        # checkboxes regardless of editor_protection mode.  The
        # editor-protection-missing branch's permission-file
        # instructions get folded in conditionally.
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

        if not editor_protection:
            # Permission file missing — show instructions with path
            # and copy button so the IT admin can opt in to editor
            # protection.
            perm_dir = perms.app_permissions_dir or "(permissions folder not found)"
            filename = "injection_protection_on_editor"

            lay.addWidget(QLabel(
                "\nTo enable injection protection on the command line "
                "editor and extra arguments (blocking these at the "
                "source), add this file to your permissions folder:"
            ))

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

        # ── v0.3.4 suppression checkboxes ─────────────────────────
        # Three "Don't warn again" scopes.  Each only appears when
        # the suppress_sanitization_warnings capability is granted.
        # The per-field box is also gated on having ``warning_fids``
        # data — without it we have nothing to silence at the field
        # granularity.
        chk_field: QCheckBox | None = None
        chk_tool: QCheckBox | None = None
        chk_global: QCheckBox | None = None
        if perm_check("suppress_sanitization_warnings"):
            unique_fids = sorted({
                f for f in (warning_fids or [])
                if f and not f.startswith("__")
            }) if warning_fids else []
            other_fid_count = sum(
                1 for f in (warning_fids or [])
                if f and f.startswith("__")
            )

            lay.addWidget(QLabel(
                "\n<b>Don't warn me again</b> "
                "(applies on Proceed):"
            ))
            if unique_fids:
                if len(unique_fids) == 1:
                    field_label = f"For field '{unique_fids[0]}'"
                else:
                    field_label = (
                        f"For these {len(unique_fids)} field(s)"
                    )
                if other_fid_count:
                    field_label += (
                        f" (warnings from extras / cmd-line / "
                        f"executable will keep showing)"
                    )
                chk_field = QCheckBox(field_label)
                chk_field.setToolTip(
                    "Silence further warnings about these specific "
                    "fields in this tool only.  Re-enable via "
                    "Edit -> Sanitization warnings..."
                )
                lay.addWidget(chk_field)
            chk_tool = QCheckBox("For this tool (every field)")
            chk_tool.setToolTip(
                "Silence every sanitization warning from this tool. "
                "Re-enable via Edit -> Sanitization warnings..."
            )
            chk_tool.setEnabled(bool(self._file_path))
            if not self._file_path:
                chk_tool.setToolTip(
                    chk_tool.toolTip()
                    + "\n(Disabled: this tool has no on-disk path.)"
                )
            lay.addWidget(chk_tool)
            chk_global = QCheckBox("For all tools, everywhere")
            chk_global.setToolTip(
                "Silence every sanitization warning across the whole "
                "ScripTree install.  Re-enable via "
                "Edit -> Sanitization warnings..."
            )
            lay.addWidget(chk_global)

        lay.addWidget(QLabel("\nDo you want to continue anyway?"))

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes
            | QDialogButtonBox.StandardButton.No
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        proceed = dlg.exec() == QDialog.DialogCode.Accepted

        if proceed:
            # Apply the user's choices BEFORE returning so the next
            # Run picks them up.  Only persist on Yes — Cancel / No
            # leaves the suppression state unchanged.
            if chk_global is not None and chk_global.isChecked():
                _supp.set_globally_muted(True)
            if (
                chk_tool is not None
                and chk_tool.isChecked()
                and self._file_path
            ):
                _supp.mute_tool(self._file_path)
            if (
                chk_field is not None
                and chk_field.isChecked()
                and self._file_path
                and warning_fids
            ):
                # Mute every concrete (non-synthetic) field id that
                # tripped this dialog.
                concrete = {
                    f for f in warning_fids
                    if f and not f.startswith("__")
                }
                _supp.mute_fields_for_tool(self._file_path, concrete)
        return proceed

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
        """Load shared + personal sidecars, or build an in-memory default set.

        Shared sidecar lives next to the .scriptree file; personal sidecar
        lives in the ``user_configs/`` directory and may need a collision
        prompt if a file with the same tool filename already exists for a
        different location.
        """
        # --- Shared ---
        if self._file_path:
            try:
                loaded = load_configs(self._file_path)
            except Exception:  # noqa: BLE001 — corrupt sidecar shouldn't crash
                loaded = None
            if loaded is not None:
                self._cfg_set = loaded
            else:
                self._cfg_set = default_configuration_set(
                    self._collect_values()
                )
        else:
            self._cfg_set = default_configuration_set(self._collect_values())

        # --- Personal ---
        if self._file_path:
            self._load_personal_configs_with_collision_prompt()

        # Apply the active configuration (shared by default for initial load).
        self._active_selection = ("shared", self._cfg_set.active)
        self._apply_configuration(self._cfg_set.active_config())

    def _load_personal_configs_with_collision_prompt(self) -> None:
        """Load the personal sidecar, prompting if there's a collision."""
        from ..core.permissions import get_app_permissions, can_read_personal
        perms = get_app_permissions()
        if not can_read_personal(perms):
            return

        try:
            cfg_set, candidates = load_personal_configs_for(self._file_path)
        except Exception:  # noqa: BLE001 — corrupt sidecar shouldn't crash
            cfg_set, candidates = None, []

        if cfg_set is not None:
            # Exact location match — use it.
            self._personal_cfg_set = cfg_set
            # Figure out which candidate file this came from.
            from ..core.configs import find_personal_config_candidates
            for cand in find_personal_config_candidates(self._file_path):
                try:
                    import json as _json
                    data = _json.loads(cand.read_text(encoding="utf-8"))
                    if data.get("source_filename", "").lower() == \
                            Path(self._file_path).name.lower():
                        locs = [
                            str(Path(l).resolve()).lower()
                            for l in data.get("source_locations", [])
                        ]
                        if str(Path(self._file_path).resolve().parent).lower() in locs:
                            self._personal_cfg_path = cand
                            break
                except Exception:  # noqa: BLE001
                    continue
            return

        if not candidates:
            # No personal sidecar yet — none loaded.
            return

        # Candidates exist but none by location — prompt the user.
        dlg = PersonalConfigCollisionDialog(
            self, Path(self._file_path), candidates,
        )
        result = dlg.exec()
        if result != QDialog.DialogCode.Accepted:
            # Cancel — treat as no personal configs loaded.
            return

        action = dlg.chosen_action()
        chosen = dlg.selected_candidate()

        if action == PersonalConfigCollisionDialog.CREATE_NEW:
            # Leave personal set empty; first Save As Personal will
            # create {stem}.NNN-scriptree.configs.json with N = next avail.
            return

        if chosen is None:
            return

        tool_parent = str(Path(self._file_path).resolve().parent)
        replace = action == PersonalConfigCollisionDialog.UPDATE_LOCATION
        try:
            add_location_to_personal(
                chosen, tool_parent, replace=replace
            )
        except Exception as e:  # noqa: BLE001
            self._status.setText(
                f"<span style='color:#b00020'>Personal config update "
                f"failed: {e}</span>"
            )
            return

        # Now load it.
        try:
            import json as _json
            data = _json.loads(chosen.read_text(encoding="utf-8"))
            from ..core.configs import configs_from_dict
            self._personal_cfg_set = configs_from_dict(data)
            self._personal_cfg_path = chosen
        except Exception as e:  # noqa: BLE001
            self._status.setText(
                f"<span style='color:#b00020'>Personal config load "
                f"failed: {e}</span>"
            )

    def _refresh_cfg_combo(self) -> None:
        """Repopulate the combobox with shared + personal configurations.

        Each item stores a ``(storage, name)`` tuple in its user data so
        handlers can route to the correct ConfigurationSet. Personal
        entries are prefixed with a lock glyph to distinguish them
        visually.

        Also syncs the "Default" checkbox to whichever configuration's
        ``default_name`` matches the now-selected entry.
        """
        self._cfg_loading = True
        try:
            self._cfg_combo.clear()
            for c in self._cfg_set.configurations:
                self._cfg_combo.addItem(c.name, ("shared", c.name))
            if self._personal_cfg_set is not None:
                for c in self._personal_cfg_set.configurations:
                    self._cfg_combo.addItem(
                        f"\U0001f512 {c.name}",
                        ("personal", c.name),
                    )
            # Select the active entry using (storage, name) tuple.
            storage, name = self._active_selection
            for i in range(self._cfg_combo.count()):
                if self._cfg_combo.itemData(i) == (storage, name):
                    self._cfg_combo.setCurrentIndex(i)
                    break
        finally:
            self._cfg_loading = False
        self._sync_cfg_default_check()

    def _sync_cfg_default_check(self) -> None:
        """Sync the "Default" checkbox state to the currently-selected
        configuration's status as the set's ``default_name``."""
        if not hasattr(self, "_cfg_default_check"):
            return  # called before construction completes
        storage, name = self._active_selection
        target_set = (
            self._cfg_set if storage == "shared"
            else self._personal_cfg_set
        )
        is_default = bool(
            target_set is not None and target_set.default_name == name
        )
        # blockSignals so toggling state doesn't fire _on_cfg_default_toggled.
        self._cfg_default_check.blockSignals(True)
        self._cfg_default_check.setChecked(is_default)
        self._cfg_default_check.blockSignals(False)

    def _on_cfg_default_toggled(self, checked: bool) -> None:
        """User toggled the "Default" checkbox.  Update the active
        configuration set's ``default_name`` and persist the sidecar.

        Checking on a different config implicitly clears the previous
        default — only one configuration can be the default at a time
        per (shared / personal) set.
        """
        if self._cfg_loading:
            return
        storage, name = self._active_selection
        target_set = (
            self._cfg_set if storage == "shared"
            else self._personal_cfg_set
        )
        if target_set is None:
            return
        new_default = name if checked else ""
        if target_set.default_name == new_default:
            return
        target_set.default_name = new_default
        # Persist immediately — the user expects this checkbox to
        # behave like the rest of the configuration bar (auto-save
        # on change).
        try:
            self._save_cfg_sidecar()
            verb = (
                f"set '{name}' as default"
                if checked
                else f"cleared default (was '{name}')"
            )
            if hasattr(self, "_status") and self._status is not None:
                self._status.setText(f"✓ {verb}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self, "Save failed",
                f"Could not persist the default-config change:\n\n{exc}",
            )

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
        """Persist both shared and personal sidecars (as permitted).

        Shared is written only if ``can_write_shared`` and the tool file
        is not read-only. Personal is written only if
        ``can_write_personal`` — it's never affected by the tool's
        read-only flag since it lives in the user's own directory.
        """
        if not self._file_path:
            return False
        from ..core.permissions import (
            get_app_permissions,
            can_write_shared,
            can_write_personal,
        )
        perms = get_app_permissions()
        ok = True

        # Shared sidecar.
        if not self._read_only and can_write_shared(perms):
            try:
                save_configs(self._file_path, self._cfg_set)
            except Exception as e:  # noqa: BLE001
                self._status.setText(
                    f"<span style='color:#b00020'>Shared config save "
                    f"failed: {e}</span>"
                )
                ok = False

        # Personal sidecar.
        if (
            self._personal_cfg_set is not None
            and self._personal_cfg_set.configurations
            and can_write_personal(perms)
        ):
            try:
                if self._personal_cfg_path is None:
                    # First save — allocate a new numbered file.
                    self._personal_cfg_path = save_personal_configs(
                        self._file_path,
                        self._personal_cfg_set,
                        suffix_num=next_available_suffix_num(
                            self._file_path
                        ),
                    )
                else:
                    save_personal_configs_at(
                        self._personal_cfg_path,
                        self._personal_cfg_set,
                    )
            except Exception as e:  # noqa: BLE001
                self._status.setText(
                    f"<span style='color:#b00020'>Personal config save "
                    f"failed: {e}</span>"
                )
                ok = False
        return ok

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

        # Build a set of no_persist param IDs — skip applying their
        # saved values so the widget keeps the user's current entry
        # (or ``ParamDef.default`` on fresh load).
        no_persist_ids = {
            p.id for p in self._tool.params if p.no_persist
        }
        self._updating = True
        try:
            for pid, value in cfg.values.items():
                if pid in no_persist_ids:
                    continue
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
        data = self._cfg_combo.currentData()
        if not data:
            return
        storage, name = data
        cfg = self._find_in_set(storage, name)
        if cfg is None:
            return
        self._active_selection = (storage, name)
        if storage == "shared":
            self._cfg_set.active = name
        elif self._personal_cfg_set is not None:
            self._personal_cfg_set.active = name
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
        # Update the "Default" checkbox to reflect whether the
        # newly-selected config is the default for its set.
        self._sync_cfg_default_check()
        label = f"\U0001f512 {name}" if storage == "personal" else name
        self._status.setText(f"Loaded configuration '{label}'.")

    def _find_in_set(self, storage: str, name: str) -> Configuration | None:
        """Look up a configuration by (storage, name)."""
        if storage == "shared":
            return self._cfg_set.find(name)
        if self._personal_cfg_set is not None:
            return self._personal_cfg_set.find(name)
        return None

    def _active_config_and_set(self) -> tuple[Configuration | None, ConfigurationSet | None, str]:
        """Return the active (config, set, storage)."""
        storage, name = self._active_selection
        if storage == "personal" and self._personal_cfg_set is not None:
            return self._personal_cfg_set.find(name), self._personal_cfg_set, "personal"
        return self._cfg_set.find(name), self._cfg_set, "shared"

    def _cfg_save(self) -> None:
        """Overwrite the active configuration with the current state.

        Routes to the right ConfigurationSet based on the active
        selection's storage. no_persist param values are filtered out.
        """
        if not self._file_path:
            return
        cfg, cfg_set, storage = self._active_config_and_set()
        if cfg is None:
            return

        # Check permission for this storage.
        from ..core.permissions import (
            get_app_permissions,
            can_write_shared,
            can_write_personal,
        )
        perms = get_app_permissions()
        if storage == "shared" and not can_write_shared(perms):
            QMessageBox.warning(
                self, "Permission denied",
                "You don't have permission to write shared "
                "configurations. Try Save As \u2192 Personal.",
            )
            return
        if storage == "personal" and not can_write_personal(perms):
            QMessageBox.warning(
                self, "Permission denied",
                "You don't have permission to write personal "
                "configurations.",
            )
            return

        cfg.values = dict(self._persistent_values())
        cfg.extras = list(self._extras)
        if self._save_cfg_sidecar():
            label = (
                f"\U0001f512 {cfg.name}" if storage == "personal" else cfg.name
            )
            self._status.setText(f"Saved configuration '{label}'.")

    def _persistent_values(self) -> dict[str, Any]:
        """Collect form values, filtered to exclude no_persist params.

        Used for writing configurations. ``_collect_values`` is the full
        read that includes every param (used for runs, previews, and undo
        snapshots).
        """
        values = dict(self._collect_values())
        for p in self._tool.params:
            if p.no_persist and p.id in values:
                del values[p.id]
        return values

    def _cfg_save_as(self) -> None:
        """Prompt for a new name + storage (shared/personal) and save."""
        if not self._file_path:
            return

        from ..core.permissions import (
            get_app_permissions,
            can_write_shared,
            can_write_personal,
        )
        perms = get_app_permissions()
        write_shared = can_write_shared(perms) and not self._read_only
        write_personal = can_write_personal(perms)
        if not (write_shared or write_personal):
            QMessageBox.warning(
                self, "Permission denied",
                "You don't have permission to save any configurations.",
            )
            return

        dlg = SaveConfigAsDialog(
            self,
            can_write_shared=write_shared,
            can_write_personal=write_personal,
            initial_storage=self._active_selection[0],
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name = dlg.result_name().strip()
        storage = dlg.result_storage()
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

        # Pick the target set.
        if storage == "personal":
            if self._personal_cfg_set is None:
                self._personal_cfg_set = ConfigurationSet(
                    active=name,
                    configurations=[],
                    source_filename=Path(self._file_path).name,
                    source_locations=[
                        str(Path(self._file_path).resolve().parent)
                    ],
                )
            target_set = self._personal_cfg_set
        else:
            target_set = self._cfg_set

        existing = target_set.find(name)
        if existing is not None:
            reply = QMessageBox.question(
                self,
                "Overwrite configuration?",
                f"A configuration named '{name}' already exists in "
                f"{storage}. Overwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            existing.values = dict(self._persistent_values())
            existing.extras = list(self._extras)
            existing.storage = storage
        else:
            target_set.configurations.append(
                Configuration(
                    name=name,
                    values=dict(self._persistent_values()),
                    extras=list(self._extras),
                    storage=storage,
                )
            )

        target_set.active = name
        self._active_selection = (storage, name)

        if self._save_cfg_sidecar():
            self._refresh_cfg_combo()
            self._refresh_cfg_buttons()
            label = f"\U0001f512 {name}" if storage == "personal" else name
            self._status.setText(f"Saved configuration '{label}'.")

    def _cfg_delete(self) -> None:
        """Remove the active configuration (shared or personal)."""
        cfg, cfg_set, storage = self._active_config_and_set()
        if cfg is None or cfg_set is None:
            return
        # Can't delete the last shared config (must always have one);
        # personal sets can be emptied completely.
        if storage == "shared" and len(cfg_set.configurations) <= 1:
            return
        reply = QMessageBox.question(
            self,
            "Delete configuration?",
            f"Delete configuration '{cfg.name}'? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        cfg_set.configurations = [
            c for c in cfg_set.configurations if c.name != cfg.name
        ]

        # Pick the next active config to display.
        if cfg_set.configurations:
            new_active = cfg_set.configurations[0]
            cfg_set.active = new_active.name
            self._active_selection = (storage, new_active.name)
            self._apply_configuration(new_active)
        else:
            # Personal set emptied — fall back to shared's active config
            # and clean up the empty personal sidecar file.
            if storage == "personal":
                if (
                    self._personal_cfg_path is not None
                    and self._personal_cfg_path.exists()
                ):
                    try:
                        self._personal_cfg_path.unlink()
                    except OSError:
                        pass
                self._personal_cfg_set = None
                self._personal_cfg_path = None
            shared_active = self._cfg_set.active_config()
            self._active_selection = ("shared", shared_active.name)
            self._apply_configuration(shared_active)

        if self._save_cfg_sidecar():
            self._refresh_cfg_combo()
            self._refresh_cfg_buttons()
            label = (
                f"\U0001f512 {cfg.name}" if storage == "personal" else cfg.name
            )
            self._status.setText(f"Deleted configuration '{label}'.")

    def _cfg_edit_env(self) -> None:
        """Open the env-editor popup for the active configuration.

        The dialog edits a copy of the configuration's env/path_prepend
        overrides; on Accept the new values are written back to the
        active Configuration and persisted to the sidecar. Requires a
        file path (same rule as the other configuration buttons).
        """
        if not self._file_path:
            return
        cfg, _cfg_set, _storage = self._active_config_and_set()
        if cfg is None:
            return
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
        cfg, _set, _storage = self._active_config_and_set()
        if cfg is None:
            return
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
        cfg, _set, _storage = self._active_config_and_set()
        if cfg is None:
            return
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

        Searches the shared set first, then personal. Returns True if
        the configuration was found and applied. Used by StandaloneWindow
        and the CLI ``-configuration`` flag.
        """
        cfg = self._cfg_set.find(config_name)
        storage = "shared"
        if cfg is None and self._personal_cfg_set is not None:
            cfg = self._personal_cfg_set.find(config_name)
            storage = "personal"
        if cfg is None:
            return False
        if storage == "shared":
            self._cfg_set.active = config_name
        else:
            assert self._personal_cfg_set is not None
            self._personal_cfg_set.active = config_name
        self._active_selection = (storage, config_name)
        self._cfg_loading = True
        try:
            for i in range(self._cfg_combo.count()):
                if self._cfg_combo.itemData(i) == (storage, config_name):
                    self._cfg_combo.setCurrentIndex(i)
                    break
        finally:
            self._cfg_loading = False
        self._apply_configuration(cfg)
        return True

    @property
    def active_visibility(self) -> UIVisibility:
        """The UIVisibility of the currently active configuration."""
        cfg, _set, _storage = self._active_config_and_set()
        if cfg is None:
            return UIVisibility()
        return cfg.ui_visibility

    @property
    def read_only(self) -> bool:
        """True when the file is not writable and editing is disabled."""
        return self._read_only
