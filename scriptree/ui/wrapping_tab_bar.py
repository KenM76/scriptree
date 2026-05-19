"""A QTabBar that wraps onto additional rows when tabs don't fit.

## For humans

Qt's built-in ``QTabBar`` shows scroll arrows when the total tab
width exceeds the available horizontal space — there's no native
way to lay tabs out on multiple rows. This subclass overrides the
layout + paint + hit-testing machinery to do a greedy row-fill:
each tab keeps its natural width, and when adding one more would
exceed the bar's width, it moves to a new row below.

Wrap mode is on by default but can be toggled off (``set_wrap(False)``
restores classic single-row-with-scroll-arrows behavior) — the
runner exposes that toggle via a right-click context menu on the
tab bar.

The helper ``make_wrapping_tab_widget()`` builds a ``QTabWidget`` whose
tab bar is a ``WrappingTabBar``; use it as a drop-in replacement for
``QTabWidget()``.

## For maintainers / LLMs

- ``self._rects`` is the single source of geometry truth: it is
  computed by ``_recompute`` and consumed by ``tabSizeHint``,
  ``sizeHint``, ``paintEvent`` and ``mousePressEvent``. Every code
  path that reads it must keep it in sync with ``self.count()`` —
  ``paintEvent`` re-runs ``_recompute`` if ``len(self._rects) !=
  count``, the safety net for tab add/remove/rename between layout
  events. Don't read ``_rects`` without that staleness check.
- ``_recompute`` early-outs (empty rects, zero height) when wrap is
  off; every override therefore branches on ``self._wrap`` and falls
  back to ``super()`` so disabling wrap fully restores native
  behaviour. Keep the dual path in any new override.
- Greedy fill uses ``super().tabSizeHint(i)`` (the NATURAL width) for
  measurement; ``tabSizeHint`` then returns the cached
  ``_rects[i].size()`` so Qt's own layout agrees with our paint
  geometry. The wrap test ``if rects and x + tw > bar_w`` always
  places ≥1 tab per row (a tab wider than the viewport still renders,
  no infinite wrap).
- ``minimumSizeHint`` reports only one row's height so the parent
  ``QTabWidget`` can shrink the bar; the real multi-row height comes
  from ``sizeHint``/``_total_height`` after ``_recompute`` runs
  against the assigned width. ``resizeEvent``/``tabLayoutChange``
  recompute then call ``updateGeometry()`` so the parent re-queries
  height — don't drop those notifications or row count goes stale on
  resize.
- ``mousePressEvent``: only LeftButton hit-tests ``_rects`` to set
  the current index; everything else (context-menu signal,
  middle-click-close) MUST fall through to ``super()`` — preserve
  that fallthrough.
- ``make_wrapping_tab_widget`` calls ``setTabBar`` BEFORE any tabs
  exist (Qt requires the bar be installed before tabs are added).
  Always construct via the helper, never swap the bar post-hoc.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QStyle,
    QStyleOptionTab,
    QStylePainter,
    QTabBar,
    QTabWidget,
)


class WrappingTabBar(QTabBar):
    """A ``QTabBar`` that lays tabs onto multiple rows when needed."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._wrap = True
        # Positions are recomputed on every layout change; cache them
        # so paintEvent and mousePressEvent agree on the geometry.
        self._rects: list[QRect] = []
        self._total_height: int = 0
        # Turn scroll buttons off in wrap mode (they'd be redundant).
        self.setUsesScrollButtons(False)
        # Leave setExpanding(False) so each tab hugs its label width.
        self.setExpanding(False)
        # Drawing needs opaque backgrounds so the multi-row area
        # renders cleanly.
        self.setDrawBase(True)

    # --- public API ------------------------------------------------------

    def wrap_enabled(self) -> bool:
        return self._wrap

    def set_wrap(self, wrap: bool) -> None:
        if wrap == self._wrap:
            return
        self._wrap = wrap
        # Restore native behavior (scroll arrows) when wrap is off.
        self.setUsesScrollButtons(not wrap)
        self._recompute()
        self.updateGeometry()
        self.update()

    # --- internal layout -------------------------------------------------

    def _recompute(self) -> None:
        if not self._wrap:
            self._rects = []
            self._total_height = 0
            return
        bar_w = max(self.width(), 1)
        x = 0
        y = 0
        row_h = 0
        rects: list[QRect] = []
        for i in range(self.count()):
            size = super().tabSizeHint(i)
            tw, th = size.width(), size.height()
            # Wrap to next row if this tab wouldn't fit, but always
            # place at least one tab per row so a single-tab-wider-
            # than-viewport case still renders.
            if rects and x + tw > bar_w:
                x = 0
                y += row_h
                row_h = 0
            rects.append(QRect(x, y, tw, th))
            x += tw
            if th > row_h:
                row_h = th
        self._rects = rects
        self._total_height = (y + row_h) if rects else 0

    # --- Qt overrides ----------------------------------------------------

    def tabSizeHint(self, index: int) -> QSize:  # noqa: N802
        base = super().tabSizeHint(index)
        if not self._wrap:
            return base
        # In wrap mode the real geometry comes from _rects[]; return
        # the hint Qt's layout code expects to read.
        if 0 <= index < len(self._rects):
            return self._rects[index].size()
        return base

    def sizeHint(self) -> QSize:  # noqa: N802
        base = super().sizeHint()
        if not self._wrap:
            return base
        # Force a recompute against the currently-assigned width so
        # the height we report reflects the number of rows we'll
        # actually draw.
        self._recompute()
        return QSize(base.width(), max(self._total_height, base.height()))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        # Reporting only one tab's worth of height as the minimum
        # lets the parent layout shrink the bar; _recompute() will
        # reflow when given the real width at paint time.
        if not self._wrap:
            return super().minimumSizeHint()
        if self._rects:
            return QSize(1, self._rects[0].height())
        return super().minimumSizeHint()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._wrap:
            self._recompute()
            # New row count may have changed our preferred height —
            # tell the parent QTabWidget to re-query sizeHint.
            self.updateGeometry()

    def tabLayoutChange(self) -> None:  # noqa: N802
        super().tabLayoutChange()
        if self._wrap:
            self._recompute()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._wrap:
            super().paintEvent(event)
            return
        # Make sure our cached geometry matches the current state
        # (tab added/removed/renamed since the last layout change).
        if len(self._rects) != self.count():
            self._recompute()

        painter = QStylePainter(self)
        for i, rect in enumerate(self._rects):
            opt = QStyleOptionTab()
            self.initStyleOption(opt, i)
            opt.rect = rect
            painter.drawControl(QStyle.ControlElement.CE_TabBarTab, opt)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if not self._wrap:
            super().mousePressEvent(event)
            return
        # Left click -> activate the tab under the cursor.
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            for i, rect in enumerate(self._rects):
                if rect.contains(pos):
                    self.setCurrentIndex(i)
                    event.accept()
                    return
        # Fall through to base class (handles context-menu signal,
        # middle-click-close, etc.).
        super().mousePressEvent(event)


def make_wrapping_tab_widget(parent=None) -> QTabWidget:
    """Build a ``QTabWidget`` whose tab bar is a ``WrappingTabBar``.

    Call this instead of ``QTabWidget()`` to get the multi-row
    behavior. ``setTabBar`` must be invoked before any tabs are
    added, which is exactly what this helper does for you.
    """
    tw = QTabWidget(parent)
    tw.setTabBar(WrappingTabBar(tw))
    return tw
