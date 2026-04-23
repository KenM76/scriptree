"""A horizontal-first layout that wraps child widgets to the next row
when horizontal space runs out.

Used for button rows (Run / Stop / Copy argv / Undo / Redo / Reset /
Clear) and the configuration toolbar — both of which previously sat
inside a ``QHBoxLayout`` and caused a horizontal scroll bar on the
form whenever the window was narrower than the full row.

This is a textbook Qt ``QLayout`` subclass; the shape is based on the
``FlowLayout`` example that ships with Qt (widgets/layouts/flowlayout
in the C++ examples), ported to Python/PySide6. Drop in as a replacement
for ``QHBoxLayout``.
"""
from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QStyle, QWidget


class FlowLayout(QLayout):
    """Horizontal layout that wraps items onto additional rows as needed."""

    def __init__(
        self,
        parent: QWidget | None = None,
        margin: int = 0,
        hspacing: int = -1,
        vspacing: int = -1,
    ) -> None:
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        else:
            self.setContentsMargins(QMargins(margin, margin, margin, margin))
        self._hspace = hspacing
        self._vspace = vspacing
        self._items: list[QLayoutItem] = []

    # --- QLayout overrides -------------------------------------------------

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    # --- spacing helpers ---------------------------------------------------

    def horizontal_spacing(self) -> int:
        if self._hspace >= 0:
            return self._hspace
        return self._smart_spacing(QStyle.PixelMetric.PM_LayoutHorizontalSpacing)

    def vertical_spacing(self) -> int:
        if self._vspace >= 0:
            return self._vspace
        return self._smart_spacing(QStyle.PixelMetric.PM_LayoutVerticalSpacing)

    def _smart_spacing(self, pm: QStyle.PixelMetric) -> int:
        parent = self.parent()
        if parent is None:
            return -1
        if parent.isWidgetType():
            return parent.style().pixelMetric(pm, None, parent)
        return parent.spacing()  # parent is another layout

    # --- core algorithm ----------------------------------------------------

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0

        for item in self._items:
            wid = item.widget()
            space_x = self.horizontal_spacing()
            if space_x == -1 and wid is not None:
                space_x = wid.style().layoutSpacing(
                    QSizePolicy.ControlType.PushButton,
                    QSizePolicy.ControlType.PushButton,
                    Qt.Orientation.Horizontal,
                )
            space_y = self.vertical_spacing()
            if space_y == -1 and wid is not None:
                space_y = wid.style().layoutSpacing(
                    QSizePolicy.ControlType.PushButton,
                    QSizePolicy.ControlType.PushButton,
                    Qt.Orientation.Vertical,
                )

            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        return y + line_height - rect.y() + m.bottom()
