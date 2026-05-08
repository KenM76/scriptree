"""
forest_window.py — the visible "forest" cell.

The forest cell is the on-screen presence of the top-level container
introduced in v0.3.14.  It's a separate widget — NOT a CellWindow
subclass — because:

  * It doesn't dock with rings (no SnapEngine participation, so we
    keep it out of CellRegistry entirely).
  * It has its own right-click menu (forest operations only — no
    Settings, no tools, no member-of-group stuff).
  * It's visually distinct: a 12-sided polygon (dodecagon) larger
    than a normal cell, themed with a deep "forest green" stroke
    so it reads as the workspace root rather than another tool.

We DO reuse the ``compute_polygon`` geometry helper from
``cell_window`` so the painting math stays in one place — extending
that helper to support 12-gons rather than re-implementing it.

Public API
----------
    ForestWindow(branding, controller=None)
        Construct.  ``controller`` is the ForestController that owns
        the menu wiring; if ``None`` the cell paints but right-click
        is a no-op (useful for tests that just assert visuals).

    forest_window.refresh_label()
        Re-read the bound forest's name + item count and update the
        cell label.

    forest_window.move_to(x, y)
        Convenience for placing the cell — same shape as
        ``CellWindow.move(x, y)`` but explicit.

Signals
-------
    rightClicked(QPoint)        — global cursor pos when the user
                                  right-clicked the forest cell.
                                  ``ForestController`` connects this
                                  to its menu builder.
    moved(QPoint)               — emitted on each drag step, in
                                  global coords.  Forest state uses
                                  this to persist position into the
                                  ``last_forest.scriptreeforest``
                                  autoload file.
"""
from __future__ import annotations

import math
import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QPoint, QPointF, QRect, Qt, Signal,
)
from PySide6.QtGui import (
    QColor, QFont, QMouseEvent, QPainter, QPen, QPolygon,
)
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from scriptree.shell.forest_controller import ForestController


def _log(msg: str) -> None:
    print(f"[forest_window] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Geometry — 12-sided polygon (dodecagon) inscribed in size_px square.
# ---------------------------------------------------------------------------

def _dodecagon_polygon(size_px: int) -> tuple[QPolygon, list[QPointF]]:
    """Return ``(QPolygon for setMask + drawPolygon,
    vertices as QPointF for hit-testing)`` of a regular 12-gon
    inscribed in a size_px × size_px square.  First vertex at +X
    so the polygon has flat top and bottom edges (visually settles
    against the desktop the same way a flat-top hexagon does)."""
    cx = cy = size_px / 2.0
    r = size_px / 2.0
    int_pts: list[QPoint] = []
    float_pts: list[QPointF] = []
    for i in range(12):
        theta = math.radians(0.0 + 360.0 / 12 * i)
        fx = cx + r * math.cos(theta)
        fy = cy + r * math.sin(theta)
        int_pts.append(QPoint(round(fx), round(fy)))
        float_pts.append(QPointF(fx, fy))
    return QPolygon(int_pts), float_pts


# ---------------------------------------------------------------------------
# ForestWindow
# ---------------------------------------------------------------------------

class ForestWindow(QWidget):
    """The visible forest cell — top-level container's UI presence."""

    # Default size: 1.6× a normal cell's default (56 → 90).  Scales
    # are kept conservative so the cell still fits on a 1080-tall
    # screen alongside several rings.
    _DEFAULT_SIZE_PX = 96

    rightClicked = Signal(QPoint)
    moved = Signal(QPoint)

    def __init__(
        self,
        branding: dict,
        controller: "ForestController | None" = None,
        *,
        size_px: int | None = None,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._branding = branding
        self._controller = controller
        self._size_px = int(size_px or self._DEFAULT_SIZE_PX)

        # Cell label — updated on the fly via ``refresh_label``.  Default
        # is the branding ``appName`` initial; the controller calls
        # ``refresh_label`` once it knows the bound forest's name.
        self._label_text: str = "F"

        # Visual palette.  The forest cell uses a distinctive deep-green
        # stroke + slightly darker fill so it reads as "the workspace
        # root" not "yet another tool".  These are intentionally NOT
        # plumbed through branding.config.json yet — keeping the look
        # consistent across forests is more important than user-tweak-
        # able theming for this MVP.
        self._fill = QColor(28, 50, 38, 220)        # deep forest green
        self._stroke = QColor(108, 196, 138, 255)   # bright leaf green
        self._stroke_inner = QColor(255, 255, 255, 60)
        self._label_color = QColor(220, 240, 220, 235)

        # Window setup mirrors CellWindow: translucent, no system
        # background, frameless, custom shape via setMask.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.resize(self._size_px, self._size_px)

        self._polygon, self._vertices = _dodecagon_polygon(self._size_px)
        self.setMask(self._polygon)

        # Drag state.
        self._drag_origin: QPoint | None = None
        self._drag_started_at: QPoint | None = None

        _log(
            f"ForestWindow created size={self._size_px} "
            f"controller={'yes' if controller else 'no'}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_label(self, text: str) -> None:
        """Set the centred label text on the forest cell.

        The controller calls this after binding to a ``ForestDef`` —
        typically with a 1-2 character abbreviation derived from the
        forest's ``name`` (e.g. "MF" for "My Forest").
        """
        self._label_text = (text or "F")[:3]
        self.update()

    def set_size(self, size_px: int) -> None:
        """Change the forest cell's size.  Recomputes geometry +
        mask + repaints."""
        self._size_px = max(48, int(size_px))
        self.resize(self._size_px, self._size_px)
        self._polygon, self._vertices = _dodecagon_polygon(self._size_px)
        self.setMask(self._polygon)
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: D401, N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Outer fill.
        painter.setBrush(self._fill)
        painter.setPen(QPen(self._stroke, 3))
        painter.drawPolygon(self._polygon)

        # Inner highlight ring — softer second polygon at 92% size to
        # add visual depth and distinguish the forest from a plain
        # large cell.
        inset = int(self._size_px * 0.04)
        if inset > 0:
            inner_poly = QPolygon([
                QPoint(
                    round(p.x() * (1 - 0.08) + (self._size_px / 2) * 0.08),
                    round(p.y() * (1 - 0.08) + (self._size_px / 2) * 0.08),
                )
                for p in self._vertices
            ])
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(self._stroke_inner, 1))
            painter.drawPolygon(inner_poly)

        # Centred label.
        if self._label_text:
            font = QFont()
            font.setBold(True)
            font.setPixelSize(max(12, int(self._size_px * 0.34)))
            painter.setFont(font)
            painter.setPen(self._label_color)
            painter.drawText(
                QRect(0, 0, self._size_px, self._size_px),
                Qt.AlignmentFlag.AlignCenter,
                self._label_text,
            )

    # ------------------------------------------------------------------
    # Mouse — drag to move, right-click → menu signal
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            # Right-click: emit signal, controller pops the menu.
            self.rightClicked.emit(event.globalPosition().toPoint())
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.pos()
            self._drag_started_at = event.globalPosition().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_origin is None:
            return super().mouseMoveEvent(event)
        new_pos = event.globalPosition().toPoint() - self._drag_origin
        self.move(new_pos)
        self.moved.emit(new_pos)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = None
            self._drag_started_at = None
            event.accept()
            return
        super().mouseReleaseEvent(event)
