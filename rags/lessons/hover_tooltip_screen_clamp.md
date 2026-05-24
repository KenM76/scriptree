---
topic: pyside6
date: 2026-05-23
status: bug
related: []
---
# Hover tooltip must clamp to screen and centre on the cell, not free-fall offset

## What happened

User report (Bug 12, v0.8.0a1): the hover tooltip for cells near the
right edge of the screen appeared off-screen, and tooltips for cells
near the bottom appeared FAR below the cell — sometimes most of the
way down the next screen.

## Root cause

`_CellHoverTip.show` in `scriptree/shell/cell_window.py:175` was
positioning the tooltip relative to the cursor anchor with a fixed
`(+12 px, +18 px)` offset from a "bottom centre" reference point.
That reference was a screen-space point computed without knowledge of
the cell's actual rect on the screen — so for cells near edges, the
fixed offset could push the tooltip clean off the visible area.

## Fix / recipe

Take the cell's geometry as an optional kwarg and use it as the
anchor; clamp against the screen that contains the anchor; flip to
the opposite side of the cell if still off-screen.

```python
# scriptree/shell/cell_window.py:175 (_CellHoverTip.show)
def show(self, text: str, anchor: QPoint,
         *, cell_rect: QRect | None = None) -> None:
    self.setText(text)
    self.adjustSize()
    w, h = self.width(), self.height()

    if cell_rect is not None:
        # Centre horizontally on the cell, park 6 px below the bottom edge
        x = cell_rect.center().x() - w // 2
        y = cell_rect.bottom() + 6
    else:
        # Legacy callers — keep the old (anchor + offset) behaviour
        x = anchor.x() + 12
        y = anchor.y() + 18

    # Clamp to whichever screen contains the anchor (multi-monitor safe)
    screen = QGuiApplication.screenAt(QPoint(x, y)) or QGuiApplication.primaryScreen()
    avail = screen.availableGeometry()
    x = max(avail.left(), min(x, avail.right() - w))

    # If clamped y still puts us off the bottom, flip above the cell
    if cell_rect is not None and y + h > avail.bottom():
        y = cell_rect.top() - h - 6
    y = max(avail.top(), min(y, avail.bottom() - h))

    self.move(x, y)
    self.raise_()
    self.show_()  # or super().show(), depending on the subclass
```

Callers in the cell hover path now pass `cell_rect=cell.geometry()`
(translated to global if needed). Old call sites without the kwarg
fall through to the legacy offset but still get the screen clamp.

## How future-me detects it

* Symptom: tooltip appears partly or fully off-screen, OR far below
  the cell, OR on the wrong monitor.
* Multi-monitor users will hit this first when monitors have
  different sizes — `screenAt(QPoint)` returns the right screen for
  the cell, not always the primary screen.
* If the tooltip is just slightly off the bottom edge of a single
  monitor, the "flip above" branch isn't firing — verify `cell_rect`
  is non-None for the caller in question.
