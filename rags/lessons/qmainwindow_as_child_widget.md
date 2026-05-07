---
topic: pyside6
date: 2026-05-07
status: pattern
related: []
---
# QMainWindow as a child widget for embedded docks

## What happened / rule

We needed the **form preview** inside `ToolEditorView` (a `QWidget`)
to be a *real* `QDockWidget` — floatable, re-dockable, hideable.
But `QDockWidget` only meaningfully attaches to a `QMainWindow`.
The editor itself is a `QWidget` embedded in a `QStackedWidget`,
so we couldn't just upgrade it to `QMainWindow` without reshaping
the surrounding plumbing.

The fix: an **internal `QMainWindow`** as a child of the editor
widget, hosting its own central widget (template editor) and a
`QDockWidget` (form preview).  Outer editor stays a plain
`QWidget`, drops into the existing stack unchanged.

## Root cause / rationale

`QDockWidget.setFloating(True)` and the dock-area machinery
require a `QMainWindow` ancestor to read/write dock geometry
state.  Adding the dock to a plain `QWidget` parent silently
no-ops the dock UX (no float button, no drop-target preview).

A `QMainWindow` is itself a `QWidget` — it can be added as a
child of any layout.  Strip its top-level decorations with
`Qt.WindowType.Widget` so it doesn't render as a separate
window.

## Fix / recipe

```python
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget, QMainWindow, QSizePolicy

class ToolEditorView(QWidget):
    def _build_ui(self):
        outer = QVBoxLayout(self)
        # ... top fields, param list ...

        self._preview_host = QMainWindow()
        # Strip top-level window flags so it lays out as a child.
        self._preview_host.setWindowFlags(Qt.WindowType.Widget)
        self._preview_host.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding,
        )
        # Central widget: whatever should always be visible.
        self._preview_host.setCentralWidget(tmpl_box)

        # Real dockable preview.
        self._preview_dock = QDockWidget("Form preview", self._preview_host)
        self._preview_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._preview_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self._preview_dock.setWidget(preview_scroll)
        self._preview_host.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self._preview_dock,
        )

        outer.addWidget(self._preview_host, stretch=1)
```

The user can now drag the preview's titlebar to detach it,
re-dock left/right/top/bottom, or close it via its close
button.  The host's `restoreState()` / `saveState()` work like
in any QMainWindow if you want to persist the layout.

## How future-me detects it

If a `QDockWidget` won't float, the parent isn't a
`QMainWindow`.  If you catch yourself reaching for
`QSplitter` to "fake" a dockable panel inside a `QWidget`,
swap in this pattern instead.

## Test caveats

- `QDockWidget.isVisible()` requires the host `QMainWindow` to
  be visible.  In offscreen pytest runs, use `isHidden()`
  instead — it reflects the show/hide state without needing
  the parent painted.
- `QMainWindow.windowFlags() & Qt.WindowType.Widget` is
  `Qt.WindowType.Widget == 0`, so the bitwise-AND always
  evaluates falsy.  Don't assert on flag bits; assert on
  `isWindow()` / `parentWidget()` instead.
