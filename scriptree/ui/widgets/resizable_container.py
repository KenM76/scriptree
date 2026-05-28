"""Vertical-resize wrapper for multi-line / list param widgets.

## For humans

Adds a thin drag handle below a child widget so the user can grow
or shrink it vertically by dragging.  Used in the form panel for
widgets whose content benefits from more room when it gets long:

* ``TextAreaWidget`` -- multi-line text (regexes, scripts, long
  messages).
* ``CheckboxListWidget`` -- list of toggle options.
* ``_PathListWidget`` (parent of ``FolderListWidget`` /
  ``FileListWidget``) -- list of paths.

The previous pattern was ``setMaximumHeight(80 or 160)`` which
capped the widget at a fixed height.  Users with many items / long
text had to scroll inside the widget even when there was plenty of
vertical space available on the form.

## For maintainers / LLMs

* The handle is a thin (5 px) strip styled as a grip with three
  small dots in the middle.  Cursor flips to ``SizeVerCursor`` on
  hover.  Click-and-drag emits ``dragged(delta_y_px)``.
* The container drives ``child.setFixedHeight(new_h)`` on each
  drag step, clamped to ``min_height``.  No max -- the user can
  grow the widget as tall as they want; the surrounding form
  scroll area in ``ToolRunnerView`` already handles the
  consequence of an overgrown row by scrolling.
* No persistence -- the resized height is session-only.  If we
  ever want to remember per-tool sizes, the sidecar JSON is the
  place.
* Layout: outer ``QVBoxLayout`` with zero margins, child on top
  (stretch=1 so it absorbs added height), handle at the bottom
  (fixed 5 px).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter
from PySide6.QtWidgets import QVBoxLayout, QWidget


class _ResizeHandle(QWidget):
    """A thin clickable strip that emits ``dragged`` on vertical drags."""

    dragged = Signal(int)  # delta in pixels (positive = down)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(5)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setAutoFillBackground(True)
        # A muted gray strip so it reads as chrome, not content.
        self.setStyleSheet(
            "_ResizeHandle { "
            "  background: #ececec; "
            "  border-top: 1px solid #d0d0d0; "
            "  border-bottom: 1px solid #d0d0d0; "
            "} "
            "_ResizeHandle:hover { background: #d8d8d8; }"
        )
        self._last_y: int | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_y = int(event.globalPosition().y())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._last_y is not None:
            y = int(event.globalPosition().y())
            self.dragged.emit(y - self._last_y)
            self._last_y = y
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._last_y = None
        event.accept()

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        # Three small dots in the middle as a grip indicator.
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#888"))
        painter.setPen(Qt.PenStyle.NoPen)
        cx = self.width() // 2
        cy = self.height() // 2
        for dx in (-6, 0, 6):
            painter.drawEllipse(QPoint(cx + dx, cy), 1, 1)


class ResizableContainer(QWidget):
    """Wrap ``child`` with a bottom drag handle for vertical resize.

    ``initial_height`` sets the child's starting fixed height; the
    user can grow it without limit via the handle.  ``min_height``
    is the smallest the child can be dragged to.  When ``child`` is
    a ``QPlainTextEdit`` / ``QListWidget`` / ``QScrollArea`` the
    container plays well with the form's outer scroll area --
    growing the child just makes the row taller.
    """

    def __init__(
        self,
        child: QWidget,
        *,
        initial_height: int = 120,
        min_height: int = 32,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._child = child
        self._min_height = int(min_height)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ``setFixedHeight`` rather than ``setMaximumHeight`` so the
        # child claims exactly the height we set, instead of letting
        # the form layout grow it to its sizeHint.  Drag updates
        # this value directly.
        child.setFixedHeight(int(initial_height))
        layout.addWidget(child, stretch=1)

        self._handle = _ResizeHandle(self)
        self._handle.dragged.connect(self._on_dragged)
        layout.addWidget(self._handle)

    # ------------------------------------------------------------------
    # Drag handling
    # ------------------------------------------------------------------

    def _on_dragged(self, delta_y: int) -> None:
        new_h = max(self._min_height, self._child.height() + int(delta_y))
        self._child.setFixedHeight(new_h)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def child_widget(self) -> QWidget:
        """The wrapped widget (so tests + downstream code can reach it)."""
        return self._child

    def current_child_height(self) -> int:
        """Current pixel height of the child -- exposed for tests."""
        return self._child.height()
