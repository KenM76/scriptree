---
topic: pyside6
date: 2026-05-07
status: gotcha
related: []
---
# QMenu.exec() outside-click dispatches to underlying widget

## What happened

A cell's right-click opened a `QMenu` (the tree popup) via
`menu.exec(pos)`.  Clicking outside the menu — including back
on the cell that opened it — closed the menu AND immediately
re-fired the click on the cell, which re-opened the menu.
End result: the menu felt impossible to dismiss by clicking
its source cell.

## Root cause

Qt's `QMenu` closes when you click outside it, AND it doesn't
swallow that click — it forwards it to the widget under the
cursor.  If that widget is the cell whose menu just closed,
the cell's click handler treats it as a fresh open request
and the cycle repeats.

## Fix / recipe

Record a "menu just closed" timestamp on the cell via
`aboutToHide`, and have the cell's click handler suppress
re-open within ~250 ms:

```python
# scriptree/shell/cell_window.py
class CellWindow(QWidget):
    def __init__(self, ...):
        ...
        self._menu_closed_at = 0.0  # monotonic timestamp

    def _open_tree_menu(self):
        menu = build_tree_menu(...)
        menu.aboutToHide.connect(self._on_menu_closed)
        menu.exec(self.mapToGlobal(self.rect().center()))

    def _on_menu_closed(self):
        self._menu_closed_at = time.monotonic()

    def click(self, kind: str):
        if kind == "single" and (time.monotonic() - self._menu_closed_at) < 0.25:
            return  # eat the redispatched click
        ...
```

Same suppression in `tree_popup.show_tree_popup_for` for the
standalone branch.

## How future-me detects it

A right-click menu that "won't go away" — clicking the cell
re-opens it instantly.  Or: clicks meant for blank space behind
a popup land on the widget under the cursor.  Both signal
QMenu's outside-click forwarding.
