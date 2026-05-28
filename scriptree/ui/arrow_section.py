"""Arrow-style collapsible section widget.

## For humans

A drop-in replacement for the ``QGroupBox(setCheckable=True)``
pattern that ScripTree uses for collapsible blocks (header
description, extras box, command-line box).  The Qt-native pattern
puts a CHECKBOX in the title bar, which the user reads as "enable /
disable this feature" rather than "show / hide it".  This widget
shows a ▶ / ▼ arrow instead — the universally-understood
expand/collapse glyph.

## For maintainers / LLMs

* Public API is a SUBSET of ``QGroupBox`` so callers that used
  ``setChecked`` / ``isChecked`` / ``toggled`` / ``setTitle`` keep
  compiling unchanged.  The widget IS NOT a QGroupBox subclass --
  it just mimics the relevant surface so existing call sites don't
  need to be rewritten.
* The content widget is added via ``setContentWidget`` or
  ``setContentLayout``.  Visibility of that content is the only
  thing the arrow toggles -- the header bar stays visible at all
  times so the user can find the toggle when the section is
  collapsed.
* ``toggled`` (bool) fires on every state change, mirroring the
  ``QGroupBox.toggled`` signal so the original
  ``box.toggled.connect(lambda checked: edit.setVisible(checked))``
  patterns work unchanged.
* Header bar is keyboard-accessible: Space and Enter toggle when
  the widget has focus.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class ArrowSection(QWidget):
    """A header-bar + content widget pair with a ▶/▼ collapse arrow.

    Drop-in replacement for ``QGroupBox(setCheckable=True)`` for
    show/hide-only collapsibles.  Use when the toggle is purely
    visibility -- if you need enable/disable semantics
    (capability gating, etc.), stick with QCheckBox.
    """

    toggled = Signal(bool)
    """Emitted with the new expanded state whenever it changes."""

    def __init__(
        self,
        title: str = "",
        parent: QWidget | None = None,
        *,
        expanded: bool = True,
    ) -> None:
        super().__init__(parent)
        self._expanded = expanded
        self._content_widget: QWidget | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = _ArrowHeader(title, expanded, parent=self)
        self._header.clicked.connect(self._on_header_clicked)
        outer.addWidget(self._header)

        # Content placeholder -- replaced when the caller installs a
        # widget or a layout.
        self._content_holder = QWidget(self)
        self._content_holder_layout = QVBoxLayout(self._content_holder)
        self._content_holder_layout.setContentsMargins(8, 4, 8, 6)
        outer.addWidget(self._content_holder)

        self._content_holder.setVisible(expanded)

    # ------------------------------------------------------------------
    # Content installation
    # ------------------------------------------------------------------

    def setContentWidget(self, widget: QWidget) -> None:
        """Replace the inner content with ``widget``.

        The widget is reparented to the section.  Subsequent toggles
        flip its visibility (via the holder).  Calling this twice
        replaces the previous content; the old widget is reparented
        to ``None`` so callers can dispose of it.
        """
        # Clear any previous content.
        while self._content_holder_layout.count():
            item = self._content_holder_layout.takeAt(0)
            if item is None:
                continue
            old = item.widget()
            if old is not None:
                old.setParent(None)
        self._content_widget = widget
        self._content_holder_layout.addWidget(widget)

    def setContentLayout(self, layout: QLayout) -> None:
        """Install ``layout`` as the content layout."""
        # Replace the holder's layout entirely.
        # Trick: reparent the old layout to a throwaway widget so it
        # gets cleaned up.
        old = self._content_holder.layout()
        if old is not None:
            QWidget().setLayout(old)
        layout.setContentsMargins(8, 4, 8, 6)
        self._content_holder.setLayout(layout)
        self._content_holder_layout = layout  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # State accessors -- mirror QGroupBox so existing call sites work
    # ------------------------------------------------------------------

    def isExpanded(self) -> bool:
        return self._expanded

    def setExpanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = bool(expanded)
        self._header.setExpanded(self._expanded)
        self._content_holder.setVisible(self._expanded)
        self.toggled.emit(self._expanded)

    # Aliases so the previous ``QGroupBox`` API keeps compiling.
    def isChecked(self) -> bool:
        return self.isExpanded()

    def setChecked(self, checked: bool) -> None:
        self.setExpanded(checked)

    def setTitle(self, title: str) -> None:
        self._header.setTitle(title)

    def title(self) -> str:
        return self._header.title()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_header_clicked(self) -> None:
        self.setExpanded(not self._expanded)


class _ArrowHeader(QWidget):
    """The clickable title bar: arrow glyph + label.

    Separate widget so the header alone can carry styling, focus,
    and click handling without the content row interfering.  Emits
    ``clicked`` on mouse release and on Space/Enter when focused --
    the keyboard path is what keeps the toggle accessible.
    """

    clicked = Signal()

    def __init__(
        self,
        title: str,
        expanded: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # A subtle header style so the bar is visually distinct from
        # the surrounding chrome but doesn't shout.  Matches the
        # weight of Qt's native QGroupBox title.
        self.setStyleSheet(
            "_ArrowHeader { "
            "  background: #f0f0f0; "
            "  border: 1px solid #d0d0d0; "
            "  border-radius: 3px; "
            "} "
            "_ArrowHeader:hover { background: #e8e8e8; } "
            "_ArrowHeader:focus { border: 1px solid #4a90e2; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(6)

        self._arrow = QLabel("▼" if expanded else "▶", self)
        self._arrow.setStyleSheet(
            "QLabel { color: #555; font-size: 11px; min-width: 12px; }"
        )
        layout.addWidget(self._arrow)

        self._label = QLabel(title, self)
        self._label.setStyleSheet(
            "QLabel { color: #222; font-weight: 600; }"
        )
        layout.addWidget(self._label, stretch=1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

    def title(self) -> str:
        return self._label.text()

    def setTitle(self, title: str) -> None:
        self._label.setText(title)

    def setExpanded(self, expanded: bool) -> None:
        self._arrow.setText("▼" if expanded else "▶")

    # ------------------------------------------------------------------
    # Click + keyboard
    # ------------------------------------------------------------------

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (
            Qt.Key.Key_Space,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)
