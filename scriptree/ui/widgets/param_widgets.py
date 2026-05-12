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
from PySide6.QtGui import QAction, QFontMetrics
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.model import ParamDef, ParamType, Widget as WidgetKind


# --- drop-aware text edits -------------------------------------------------
#
# Qt only honors ``dragEnterEvent`` / ``dropEvent`` overrides on real
# subclasses — the C++ vtable is bound at construction, so monkey-patching
# the methods on a stock ``QLineEdit`` instance silently does nothing.
# These two thin subclasses accept dropped files/folders and write the
# local path(s) into the widget. Native text drops (e.g. dragging a
# selection from another text field) still work via the parent
# implementation's fallback.

def _local_paths_from_mime(mime) -> list[str]:
    """Return local filesystem paths from a QMimeData, or []."""
    # PySide6 sometimes hands back a base QObject wrapper for const
    # ``QMimeData*`` pointers (notably for events built in Python rather
    # than dispatched by Qt itself). Access the URL API defensively so
    # the production path is robust and the unit tests can exercise the
    # logic without tripping on the binding artifact.
    has_urls = getattr(mime, "hasUrls", None)
    urls_fn = getattr(mime, "urls", None)
    if has_urls is None or urls_fn is None:
        return []
    if not has_urls():
        return []
    return [u.toLocalFile() for u in urls_fn() if u.isLocalFile()]


def _apply_line_edit_drop(line_edit: QLineEdit, mime) -> bool:
    """If ``mime`` carries local files, write the first into ``line_edit``.

    Returns True iff the drop was consumed.
    """
    paths = _local_paths_from_mime(mime)
    if not paths:
        return False
    line_edit.setText(paths[0])
    return True


def _apply_plain_text_drop(text_edit: QPlainTextEdit, mime) -> bool:
    """If ``mime`` carries local files, insert them at the cursor (one
    per line) into ``text_edit``. Returns True iff consumed."""
    paths = _local_paths_from_mime(mime)
    if not paths:
        return False
    text_edit.insertPlainText("\n".join(paths))
    return True


class _DroppableLineEdit(QLineEdit):
    """QLineEdit that accepts file/folder drops. Replaces the field
    with the first dropped path."""

    def dragEnterEvent(self, event) -> None:  # pragma: no cover - Qt event
        if _local_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # pragma: no cover - Qt event
        if _local_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # pragma: no cover - Qt event
        if _apply_line_edit_drop(self, event.mimeData()):
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class _DroppablePlainTextEdit(QPlainTextEdit):
    """QPlainTextEdit that accepts file/folder drops. Inserts dropped
    paths at the cursor (one per line) so multi-file drops compose
    naturally with the auto-split repeatable-flag pattern."""

    def dragEnterEvent(self, event) -> None:  # pragma: no cover - Qt event
        if _local_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # pragma: no cover - Qt event
        if _local_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # pragma: no cover - Qt event
        if _apply_plain_text_drop(self, event.mimeData()):
            event.acceptProposedAction()
            return
        super().dropEvent(event)


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
        self._edit = _DroppableLineEdit(str(param.default or ""))
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
        self._edit = _DroppablePlainTextEdit(str(param.default or ""))
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
    """Checkbox with a word-wrapped description to its right.

    QCheckBox's built-in text label doesn't wrap — long descriptions
    get clipped off the right edge of the row. This widget splits the
    checkbox and its text into two widgets: a bare ``QCheckBox`` (no
    text) plus a ``QLabel`` with ``setWordWrap(True)`` that flows onto
    additional lines as needed.

    Right-click anywhere on the widget to toggle wrapping off (or back
    on) — wrap is on by default.
    """

    def __init__(self, param: ParamDef) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._box = QCheckBox()
        self._box.setChecked(bool(param.default))
        self._box.toggled.connect(self.valueChanged.emit)

        self._desc_label = QLabel(param.description or param.label)
        self._desc_label.setWordWrap(True)
        # v0.3.9 — align the checkbox indicator with the FIRST text
        # line's vertical centre (matches native QCheckBox behaviour
        # for wrapped-text labels).  Without this the box top-aligns
        # to the row while the QLabel's default AlignVCenter pushes
        # the text down, leaving the box visibly higher than the
        # text it labels.  We compute a top pad equal to
        # ``(line_height − box_height) // 2`` and apply it via a
        # tiny vertical wrapper layout — ``setContentsMargins`` on
        # a leaf QCheckBox doesn't honour the padding the way
        # wrapping it inside a layout does.
        self._desc_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        fm = QFontMetrics(self._desc_label.font())
        line_h = fm.lineSpacing()
        box_h = self._box.sizeHint().height()
        top_pad = max(0, (line_h - box_h) // 2)
        box_holder = QWidget()
        box_holder_layout = QVBoxLayout(box_holder)
        box_holder_layout.setContentsMargins(0, top_pad, 0, 0)
        box_holder_layout.setSpacing(0)
        box_holder_layout.addWidget(self._box)
        box_holder_layout.addStretch(1)
        layout.addWidget(box_holder, alignment=Qt.AlignmentFlag.AlignTop)
        # Clicking the label toggles the checkbox — matches native
        # QCheckBox behavior where the whole "checkbox + text" area
        # is clickable.
        self._desc_label.mousePressEvent = self._on_label_mouse_press
        self._desc_label.setSizePolicy(
            self._desc_label.sizePolicy().horizontalPolicy(),
            self._desc_label.sizePolicy().verticalPolicy(),
        )
        layout.addWidget(self._desc_label, stretch=1)

        # Right-click anywhere on this widget → "Word wrap" toggle.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._desc_label.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._desc_label.customContextMenuRequested.connect(
            lambda pos: self._show_context_menu(
                self._desc_label.mapTo(self, pos)
            )
        )

    def _on_label_mouse_press(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self._box.toggle()
        # Defer to default for right-click (context menu).
        QLabel.mousePressEvent(self._desc_label, ev)

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        wrap_act = QAction("Word wrap", menu)
        wrap_act.setCheckable(True)
        wrap_act.setChecked(self._desc_label.wordWrap())
        wrap_act.toggled.connect(self.set_word_wrap)
        menu.addAction(wrap_act)
        menu.exec(self.mapToGlobal(pos))

    def set_word_wrap(self, on: bool) -> None:
        """Toggle word-wrap on the description label.

        Public API so a batch-toggle from the tab-bar right-click menu
        can flip every checkbox in the tab at once. Also walks up to
        the enclosing ``ReorderableParamForm`` (a QListWidget) and
        asks it to re-measure every row — without that the
        QListWidgetItem's cached sizeHint stays at the old height and
        the newly-wrapped text is clipped.
        """
        self._desc_label.setWordWrap(on)
        self._desc_label.updateGeometry()
        self.updateGeometry()
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, "relayout_rows"):
                parent.relayout_rows()
                break
            parent = parent.parent()

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


class RadioWidget(ParamWidget):
    """A vertical stack of mutually-exclusive radio buttons for an
    ``enum`` param.

    Same value semantics as ``DropdownWidget``: each button's user
    data carries the raw ``ParamDef.choices`` value, the visible
    label comes from ``param.label_for_choice(value)``, and
    ``get_value()`` returns the raw value (never the label).

    A choice with an empty value (``""``) acts as a "none" option —
    selecting it makes the placeholder substitute as ``""`` which
    drops the whole template token (or its enclosing token group).
    The label is whatever the tool author put in
    ``choice_labels``; ``"(none)"`` is a sensible convention.
    """

    def __init__(self, param: ParamDef) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # QButtonGroup gives mutual exclusion + a single signal for
        # "the selection changed" regardless of which button moved.
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[QRadioButton] = []

        for value in param.choices:
            btn = QRadioButton(param.label_for_choice(value))
            btn.setProperty("value", value)
            self._group.addButton(btn)
            layout.addWidget(btn)
            self._buttons.append(btn)

        # Pick the default. If the supplied default isn't one of the
        # choices, leave nothing selected (matches Qt's QComboBox
        # behavior when default is missing).
        if param.default in param.choices:
            for btn in self._buttons:
                if btn.property("value") == param.default:
                    btn.setChecked(True)
                    break

        self._group.buttonClicked.connect(
            lambda _btn: self.valueChanged.emit(self.get_value())
        )

    def get_value(self) -> str:
        checked = self._group.checkedButton()
        if checked is None:
            return ""
        v = checked.property("value")
        return "" if v is None else str(v)

    def set_value(self, value: Any) -> None:
        if value is None:
            # Clear selection — uncheck everything. Need to flip
            # exclusive off first, since QButtonGroup with
            # setExclusive=True doesn't allow zero checked.
            self._group.setExclusive(False)
            for btn in self._buttons:
                btn.setChecked(False)
            self._group.setExclusive(True)
            return
        for btn in self._buttons:
            if btn.property("value") == value or str(btn.property("value")) == str(value):
                btn.setChecked(True)
                return


# --- file / folder pickers -------------------------------------------------

class _PathPickerBase(ParamWidget):
    """Line edit + Browse button + Open button.

    The Open button (v0.3.9+) opens the *containing folder* of the
    current path in the OS file browser.  If the path doesn't exist,
    it walks up the parent chain until it finds an ancestor that
    does — so even a half-typed or planned-but-not-yet-created path
    lands the user near the right neighbourhood.  The path text in
    the line edit is **never** modified by Open.

    Subclasses supply the dialog call invoked by Browse.
    """

    def __init__(self, param: ParamDef, button_label: str = "Browse...") -> None:
        super().__init__()
        self._param = param
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._edit = _DroppableLineEdit(str(param.default or ""))
        self._edit.setPlaceholderText(param.description[:80])
        self._edit.textChanged.connect(self.valueChanged.emit)
        self._btn = QPushButton(button_label)
        self._btn.clicked.connect(self._open_dialog)
        # Open button — locate the path (or its nearest existing
        # ancestor) in the platform file browser.  Non-mutating:
        # the line-edit text is never touched.
        self._btn_open = QPushButton("Open")
        self._btn_open.setToolTip(
            "Open this path's location in the system file browser. "
            "If the path doesn't exist, opens the closest ancestor "
            "folder that does. Does not change the value."
        )
        self._btn_open.clicked.connect(self._open_in_explorer)
        layout.addWidget(self._edit, stretch=1)
        layout.addWidget(self._btn)
        layout.addWidget(self._btn_open)

    def get_value(self) -> str:
        return self._edit.text()

    def set_value(self, value: Any) -> None:
        self._edit.setText("" if value is None else str(value))

    # ``QFileDialog`` uses the native Windows dialog by default (no
    # ``DontUseNativeDialog`` flag). Subclasses implement this.
    def _open_dialog(self) -> None:  # pragma: no cover
        raise NotImplementedError

    # Subclasses may override to change "containing folder" semantics
    # for folder-pickers (where the field IS already a folder).
    def _resolve_open_target(self) -> str | None:
        """Return the directory to open for the current field value.

        Default rule (used by file-pickers):
          * empty field → ``None`` (Open is a no-op)
          * existing file → the file's parent directory
          * existing directory → the directory itself
          * non-existing path → walk up the parent chain to the
            closest ancestor that exists; ``None`` only if even the
            drive / filesystem root is missing (genuinely impossible
            on a healthy system).

        The line-edit text is never modified — this method only
        reads it.
        """
        from pathlib import Path as _Path
        text = self._edit.text().strip()
        if not text:
            return None
        try:
            p = _Path(text).expanduser()
        except (OSError, ValueError, RuntimeError):
            return None
        # Walk up until we find something that exists.  Cap the
        # walk at a sane depth so a malformed path can't loop us.
        for _ in range(64):
            if p.exists():
                if p.is_file():
                    return str(p.parent)
                return str(p)
            parent = p.parent
            if parent == p:
                # Reached the root and still nothing exists.
                return None
            p = parent
        return None

    def _open_in_explorer(self) -> None:
        target = self._resolve_open_target()
        if not target:
            return
        import subprocess as _sp
        import sys as _sys
        try:
            if _sys.platform == "win32":
                _sp.Popen(["explorer", target])
            elif _sys.platform == "darwin":
                _sp.Popen(["open", target])
            else:
                _sp.Popen(["xdg-open", target])
        except OSError:
            # File browser unavailable — silently no-op.  Open is
            # a convenience; failure should never abort form work.
            pass

    def _open_file_in_default_app(self) -> None:
        """Launch the file at the current field value with its OS
        default application — same effect as double-clicking the
        file in Explorer / Finder / a Linux file manager.

        Used by ``FileOpenWidget`` / ``FileSaveWidget``'s "Open file"
        button (v0.3.9+).  No-op when the field is empty or the
        path doesn't point at an existing file (we never auto-create
        and never modify the line-edit text).  Folders fall through
        to ``_open_in_explorer`` semantics so the button still does
        *something* sensible if a folder path lands here.
        """
        from pathlib import Path as _Path
        text = self._edit.text().strip()
        if not text:
            return
        try:
            p = _Path(text).expanduser()
        except (OSError, ValueError, RuntimeError):
            return
        if not p.exists():
            return
        if p.is_dir():
            # Folder semantics: same as the location button.
            self._open_in_explorer()
            return
        import subprocess as _sp
        import sys as _sys
        try:
            if _sys.platform == "win32":
                # ``os.startfile`` is the canonical "double-click"
                # equivalent on Windows — it dispatches via the
                # shell's file-association registry the same way
                # Explorer does.
                import os as _os
                _os.startfile(str(p))  # type: ignore[attr-defined]
            elif _sys.platform == "darwin":
                _sp.Popen(["open", str(p)])
            else:
                _sp.Popen(["xdg-open", str(p)])
        except OSError:
            pass


def _attach_open_file_button(picker: "_PathPickerBase") -> QPushButton:
    """Add an "Open file" button to a file-picker widget.

    File fields (``FILE_OPEN`` / ``FILE_SAVE``) get TWO buttons next
    to Browse:

      * **Open**       — opens the path's location in the OS file
                         browser (walks up to the closest existing
                         ancestor if the path doesn't exist).
      * **Open file**  — launches the file with its OS default
                         application (the equivalent of double-
                         clicking it in Explorer).  No-op when the
                         file doesn't exist; never modifies the
                         line-edit text.

    Folder fields keep their single Open button (which opens the
    folder itself).
    """
    btn = QPushButton("Open file")
    btn.setToolTip(
        "Open this file with its default application — same as "
        "double-clicking it in Explorer / Finder. No-op when the "
        "file does not exist; the field's value is never changed."
    )
    btn.clicked.connect(picker._open_file_in_default_app)
    picker._btn_open_file = btn  # type: ignore[attr-defined]
    picker.layout().addWidget(btn)
    return btn


class FileOpenWidget(_PathPickerBase):
    def __init__(self, param: ParamDef) -> None:
        super().__init__(param)
        _attach_open_file_button(self)

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
    def __init__(self, param: ParamDef) -> None:
        super().__init__(param)
        _attach_open_file_button(self)

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

def _build_tooltip(param: ParamDef) -> str:
    """Format a rich-text tooltip from a ParamDef.

    v0.4.0 (ScripTree4) — universally apply ``param.description`` as
    a hover tooltip on every widget so users get useful inline help
    for every field.  Previously only the placeholder text used
    description (truncated to 80 chars) and Browse buttons had
    static tooltips; the actual input control had no tooltip at all,
    which made densely-populated forms hostile to first-time users.

    Format: bold label on the first line, description below.  Qt
    auto-wraps rich text tooltips that contain HTML, so long
    descriptions render readably without manual line-breaking.
    Returns an empty string when no useful content is available so
    Qt skips the tooltip entirely rather than showing a blank box.
    """
    label = (param.label or "").strip()
    desc = (param.description or "").strip()
    if not label and not desc:
        return ""
    # Escape HTML-special chars in the user-provided text so a stray
    # ``<`` doesn't turn into a malformed tag inside the tooltip.
    import html
    parts: list[str] = []
    if label:
        parts.append(f"<b>{html.escape(label)}</b>")
    if desc:
        parts.append(html.escape(desc).replace("\n", "<br/>"))
    # Wrap in a fixed-width div so Qt's tooltip doesn't expand into a
    # screen-wide block on long descriptions.
    return (
        '<div style="max-width: 380px;">'
        + "<br/>".join(parts)
        + "</div>"
    )


def _apply_tooltip_recursively(widget: QWidget, text: str) -> None:
    """Set ``text`` as the tooltip on ``widget`` AND on every
    interactive child (line edits, spin boxes, combos, etc.) so the
    user gets the same help no matter which sub-control they hover.

    Some of our composite widgets (CheckboxWidget, _PathPickerBase)
    place their interactive child inside a layout; hovering the
    outer QWidget alone doesn't reliably trigger the tooltip on
    child controls because the child intercepts the hover events.
    Setting the tooltip on the descendants directly avoids the
    dead-zone problem.
    """
    if not text:
        return
    widget.setToolTip(text)
    # Walk descendants and propagate the same tooltip.  Skip pure
    # decorative widgets (QLabel acting as a description) so their
    # built-in word-wrap behaviour isn't shadowed by a tooltip
    # repeating the same text.
    for child in widget.findChildren(QWidget):
        if isinstance(child, QLabel):
            continue
        # Don't clobber a child that already set its own more-
        # specific tooltip (Browse/Open buttons have custom text).
        if child.toolTip():
            continue
        child.setToolTip(text)


def build_widget_for(param: ParamDef) -> ParamWidget:
    """Map a ParamDef to its concrete widget class and apply a
    universal hover tooltip drawn from ``param.description``.

    v0.4.0+ — every interactive control built by the factory now
    carries the description as a tooltip so users hovering ANY
    widget see the help text rather than having to guess from the
    label alone.  Subclasses that pre-set a more-specific tooltip
    on a sub-widget (e.g. the Browse button's "Pick a file..."
    blurb) are preserved — ``_apply_tooltip_recursively`` only
    fills in empty tooltips."""
    mapping: dict[WidgetKind, type[ParamWidget]] = {
        WidgetKind.TEXT: TextWidget,
        WidgetKind.TEXTAREA: TextAreaWidget,
        WidgetKind.NUMBER: NumberWidget,
        WidgetKind.CHECKBOX: CheckboxWidget,
        WidgetKind.DROPDOWN: DropdownWidget,
        WidgetKind.ENUM_RADIO: RadioWidget,
        WidgetKind.FILE_OPEN: FileOpenWidget,
        WidgetKind.FILE_SAVE: FileSaveWidget,
        WidgetKind.FOLDER: FolderWidget,
    }
    cls = mapping.get(param.widget, TextWidget)
    widget = cls(param)
    tooltip = _build_tooltip(param)
    _apply_tooltip_recursively(widget, tooltip)
    return widget
