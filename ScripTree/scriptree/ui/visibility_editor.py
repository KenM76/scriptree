"""Dialog for editing a configuration's UI visibility and hidden parameters.

The dialog presents two panels:

1. **UI elements** — checkboxes for each field of :class:`UIVisibility`
   (output pane, extras box, command line, etc.).
2. **Hidden parameters** — a list of the tool's parameters with
   checkboxes. Checking a parameter marks it as hidden; the current
   form value is locked as the hidden default. Users can edit the
   locked value inline.

The caller reads ``result_visibility()`` and ``result_hidden_params()``
after the dialog is accepted.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core.configs import UIVisibility
from ..core.model import ParamDef

# Maps UIVisibility field names to human-readable labels.
# config_bar is handled separately (checkbox + dropdown).
_VIS_LABELS: list[tuple[str, str]] = [
    ("output_pane", "Output pane"),
    ("extras_box", "Extra arguments box"),
    ("command_line", "Command line editor"),
    ("copy_argv", "Copy argv button"),
    ("clear_output", "Clear output button"),
    ("env_button", "Environment button"),
    ("tools_sidebar", "Tools sidebar"),
    ("popup_on_error", "Popup dialog on error"),
    ("popup_on_success", "Popup dialog on success"),
]


class VisibilityEditorDialog(QDialog):
    """Editor for UIVisibility flags and hidden parameters.

    Parameters
    ----------
    visibility:
        The current UIVisibility to edit (will not be mutated).
    hidden_params:
        List of currently hidden param IDs.
    all_params:
        The tool's full param list (for building the hidden-params panel).
    current_values:
        The active configuration's stored values dict — used to show
        locked values for hidden params.
    parent:
        Parent widget.
    """

    def __init__(
        self,
        visibility: UIVisibility,
        hidden_params: list[str],
        all_params: list[ParamDef],
        current_values: dict[str, Any],
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("UI Visibility & Hidden Parameters")
        self.resize(520, 480)

        self._all_params = all_params
        self._current_values = dict(current_values)

        root = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Vertical)
        root.addWidget(splitter, stretch=1)

        # --- UI visibility checkboxes ---
        vis_group = QGroupBox("UI element visibility")
        vis_layout = QVBoxLayout(vis_group)
        vis_layout.setContentsMargins(8, 8, 8, 8)

        note = QLabel(
            "<i>These settings only take effect in <b>standalone mode</b> "
            "(View \u2192 Open in standalone window, or the -standalone "
            "CLI flag). When docked in the main IDE, all controls remain "
            "visible.</i>"
        )
        note.setWordWrap(True)
        vis_layout.addWidget(note)

        self._vis_checks: dict[str, QCheckBox] = {}
        for field_name, label in _VIS_LABELS:
            cb = QCheckBox(label)
            cb.setChecked(getattr(visibility, field_name))
            self._vis_checks[field_name] = cb
            vis_layout.addWidget(cb)

        # Configuration bar — checkbox + dropdown for access level.
        config_bar_row = QHBoxLayout()
        self._chk_config_bar = QCheckBox("Configuration bar")
        config_bar_mode = visibility.config_bar  # "hidden", "read", "readwrite"
        self._chk_config_bar.setChecked(config_bar_mode != "hidden")
        config_bar_row.addWidget(self._chk_config_bar)

        self._cmb_config_bar = QComboBox()
        self._cmb_config_bar.addItem("Read only", "read")
        self._cmb_config_bar.addItem("Read / Write", "readwrite")
        # Set current from the mode.
        if config_bar_mode == "read":
            self._cmb_config_bar.setCurrentIndex(0)
        else:
            self._cmb_config_bar.setCurrentIndex(1)
        self._cmb_config_bar.setEnabled(config_bar_mode != "hidden")
        config_bar_row.addWidget(self._cmb_config_bar)
        config_bar_row.addStretch(1)

        self._chk_config_bar.toggled.connect(self._cmb_config_bar.setEnabled)
        vis_layout.addLayout(config_bar_row)

        vis_layout.addStretch(1)
        splitter.addWidget(vis_group)

        # --- Hidden parameters ---
        hidden_group = QGroupBox("Hidden parameters (locked values)")
        hidden_layout = QVBoxLayout(hidden_group)
        hidden_layout.setContentsMargins(8, 8, 8, 8)

        hint = QLabel(
            "<i>Check a parameter to hide it from the form. "
            "Its value will be locked to what you set here.</i>"
        )
        hint.setWordWrap(True)
        hidden_layout.addWidget(hint)

        hidden_set = set(hidden_params)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(4, 4, 4, 4)

        self._hidden_checks: dict[str, QCheckBox] = {}
        self._hidden_values: dict[str, QLineEdit] = {}

        for param in all_params:
            row = QHBoxLayout()
            cb = QCheckBox(param.label or param.id)
            cb.setChecked(param.id in hidden_set)
            self._hidden_checks[param.id] = cb
            row.addWidget(cb)

            val_edit = QLineEdit()
            val_edit.setPlaceholderText("locked value")
            val_edit.setMinimumWidth(140)
            # Populate with the current value if available.
            stored = current_values.get(param.id, "")
            val_edit.setText(str(stored) if stored is not None else "")
            val_edit.setEnabled(param.id in hidden_set)
            self._hidden_values[param.id] = val_edit
            row.addWidget(val_edit, stretch=1)

            # Toggle value-edit enabled state with the checkbox.
            cb.toggled.connect(val_edit.setEnabled)

            scroll_layout.addLayout(row)

        scroll_layout.addStretch(1)
        scroll.setWidget(scroll_widget)
        hidden_layout.addWidget(scroll, stretch=1)
        splitter.addWidget(hidden_group)

        splitter.setStretchFactor(0, 2)  # visibility
        splitter.setStretchFactor(1, 3)  # hidden params

        # --- OK / Cancel ---
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def result_visibility(self) -> UIVisibility:
        """Return the UIVisibility reflecting the dialog's checkboxes."""
        kwargs: dict[str, Any] = {
            field: cb.isChecked()
            for field, cb in self._vis_checks.items()
        }
        # Config bar: checkbox + dropdown → "hidden", "read", or "readwrite".
        if not self._chk_config_bar.isChecked():
            kwargs["config_bar"] = "hidden"
        else:
            kwargs["config_bar"] = self._cmb_config_bar.currentData()
        return UIVisibility(**kwargs)

    def result_hidden_params(self) -> list[str]:
        """Return the list of param IDs that should be hidden."""
        return [
            pid for pid, cb in self._hidden_checks.items() if cb.isChecked()
        ]

    def result_locked_values(self) -> dict[str, Any]:
        """Return the locked values for hidden params.

        Only includes entries for params that are actually hidden.
        The caller should merge these into ``Configuration.values``.
        """
        result: dict[str, Any] = {}
        for pid, cb in self._hidden_checks.items():
            if cb.isChecked():
                text = self._hidden_values[pid].text()
                result[pid] = text
        return result

