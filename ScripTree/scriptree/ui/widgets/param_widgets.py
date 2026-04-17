"""Param widgets used by the tool runner form.

Each widget exposes a uniform interface::

    class ParamWidget(QWidget):
        valueChanged: Signal(object)
        def get_value(self) -> Any: ...
        def set_value(self, v: Any) -> None: ...

``build_widget_for(param)`` maps a ``ParamDef`` to a concrete widget.

The file-picker and folder-picker widgets use ``QFileDialog`` with
native Windows dialogs — these are the same common dialogs File
Explorer uses, satisfying the "native Windows dialog" requirement.
All ``QFileDialog`` calls are confined to this module so a fork for
another platform only has to change this one file.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from ...core.model import ParamDef, ParamType, Widget as WidgetKind


# --- base class ------------------------------------------------------------

class ParamWidget(QWidget):
    """Common interface for all param widgets."""

    valueChanged = Signal(object)

    def get_value(self) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    def set_value(self, value: Any) -> None:  # pragma: no cover
        raise NotImplementedError


# --- primitives ------------------------------------------------------------

class TextWidget(ParamWidget):
    def __init__(self, param: ParamDef) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._edit = QLineEdit(str(param.default or ""))
        self._edit.setPlaceholderText(param.description[:80])
        self._edit.textChanged.connect(self.valueChanged.emit)
        layout.addWidget(self._edit)

    def get_value(self) -> str:
        return self._edit.text()

    def set_value(self, value: Any) -> None:
        self._edit.setText("" if value is None else str(value))


class TextAreaWidget(ParamWidget):
    def __init__(self, param: ParamDef) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._edit = QPlainTextEdit(str(param.default or ""))
        self._edit.setPlaceholderText(param.description[:80])
        self._edit.setMaximumHeight(80)
        # Monospace font for regexes / patterns.
        font = self._edit.font()
        font.setStyleHint(font.StyleHint.Monospace)
        self._edit.setFont(font)
        self._edit.textChanged.connect(
            lambda: self.valueChanged.emit(self.get_value())
        )
        layout.addWidget(self._edit)

    def get_value(self) -> str:
        return self._edit.toPlainText()

    def set_value(self, value: Any) -> None:
        self._edit.setPlainText("" if value is None else str(value))


class NumberWidget(ParamWidget):
    def __init__(self, param: ParamDef) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if param.type is ParamType.FLOAT:
            self._spin = QDoubleSpinBox()
            self._spin.setRange(-1e12, 1e12)
            self._spin.setDecimals(6)
        else:
            self._spin = QSpinBox()
            self._spin.setRange(-2**31, 2**31 - 1)
        try:
            self._spin.setValue(float(param.default) if param.default != "" else 0)
        except (TypeError, ValueError):
            self._spin.setValue(0)
        self._spin.valueChanged.connect(self.valueChanged.emit)
        layout.addWidget(self._spin)

    def get_value(self) -> int | float:
        return self._spin.value()

    def set_value(self, value: Any) -> None:
        try:
            self._spin.setValue(float(value) if value != "" else 0)
        except (TypeError, ValueError):
            self._spin.setValue(0)


class CheckboxWidget(ParamWidget):
    def __init__(self, param: ParamDef) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._box = QCheckBox(param.description or param.label)
        self._box.setChecked(bool(param.default))
        self._box.toggled.connect(self.valueChanged.emit)
        layout.addWidget(self._box)

    def get_value(self) -> bool:
        return self._box.isChecked()

    def set_value(self, value: Any) -> None:
        self._box.setChecked(bool(value))


class DropdownWidget(ParamWidget):
    """A combo box that shows human-readable labels but emits raw values.

    Each item stores its ``ParamDef.choices`` value as user data while
    displaying the matching entry from ``ParamDef.choice_labels`` (or
    the value itself, if no label was supplied). ``get_value`` always
    returns the raw value so argv assembly stays unchanged — labels
    are purely cosmetic.
    """

    def __init__(self, param: ParamDef) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._combo = QComboBox()
        for value in param.choices:
            self._combo.addItem(param.label_for_choice(value), value)
        if param.default in param.choices:
            idx = self._combo.findData(param.default)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
        self._combo.currentIndexChanged.connect(
            lambda _i: self.valueChanged.emit(self.get_value())
        )
        layout.addWidget(self._combo)

    def get_value(self) -> str:
        data = self._combo.currentData()
        if data is None:
            return self._combo.currentText()
        return str(data)

    def set_value(self, value: Any) -> None:
        if value is None:
            return
        idx = self._combo.findData(str(value))
        if idx < 0:
            # Fallback — match by visible text (for legacy data paths
            # that ran through the old label-equals-value model).
            idx = self._combo.findText(str(value))
        if idx >= 0:
            self._combo.setCurrentIndex(idx)


# --- file / folder pickers -------------------------------------------------

class _PathPickerBase(ParamWidget):
    """Line edit + Browse button. Subclasses supply the dialog call."""

    def __init__(self, param: ParamDef, button_label: str = "Browse...") -> None:
        super().__init__()
        self._param = param
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._edit = QLineEdit(str(param.default or ""))
        self._edit.setPlaceholderText(param.description[:80])
        self._edit.textChanged.connect(self.valueChanged.emit)
        self._btn = QPushButton(button_label)
        self._btn.clicked.connect(self._open_dialog)
        layout.addWidget(self._edit, stretch=1)
        layout.addWidget(self._btn)

    def get_value(self) -> str:
        return self._edit.text()

    def set_value(self, value: Any) -> None:
        self._edit.setText("" if value is None else str(value))

    # ``QFileDialog`` uses the native Windows dialog by default (no
    # ``DontUseNativeDialog`` flag). Subclasses implement this.
    def _open_dialog(self) -> None:  # pragma: no cover
        raise NotImplementedError


class FileOpenWidget(_PathPickerBase):
    def _open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select {self._param.label}",
            self._edit.text(),
            self._param.file_filter or "All files (*)",
        )
        if path:
            self._edit.setText(path)


class FileSaveWidget(_PathPickerBase):
    def _open_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Save {self._param.label}",
            self._edit.text(),
            self._param.file_filter or "All files (*)",
        )
        if path:
            self._edit.setText(path)


class FolderWidget(_PathPickerBase):
    def _open_dialog(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            f"Select {self._param.label}",
            self._edit.text(),
        )
        if path:
            self._edit.setText(path)


# --- factory ---------------------------------------------------------------

def build_widget_for(param: ParamDef) -> ParamWidget:
    """Map a ParamDef to its concrete widget class."""
    mapping: dict[WidgetKind, type[ParamWidget]] = {
        WidgetKind.TEXT: TextWidget,
        WidgetKind.TEXTAREA: TextAreaWidget,
        WidgetKind.NUMBER: NumberWidget,
        WidgetKind.CHECKBOX: CheckboxWidget,
        WidgetKind.DROPDOWN: DropdownWidget,
        WidgetKind.ENUM_RADIO: DropdownWidget,  # v1: render radio as dropdown
        WidgetKind.FILE_OPEN: FileOpenWidget,
        WidgetKind.FILE_SAVE: FileSaveWidget,
        WidgetKind.FOLDER: FolderWidget,
    }
    cls = mapping.get(param.widget, TextWidget)
    return cls(param)
