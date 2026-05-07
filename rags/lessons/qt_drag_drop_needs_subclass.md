---
topic: pyside6
date: 2026-05-07
status: gotcha
related: [synthetic_qdropevent_loses_mimedata]
---
# Drag-drop overrides need real subclasses, not monkey-patches

## What happened

Tried to add drag-drop support to a `QLineEdit` by assigning
`widget.dropEvent = my_handler` and `widget.dragEnterEvent =
my_handler`.  Drops were silently ignored — Qt never called
the handlers.

## Root cause

Qt binds `dropEvent` / `dragEnterEvent` (and every other
virtual override) via the C++ vtable when the widget is
constructed.  A Python-side attribute assignment doesn't reach
the vtable — Qt dispatches to the C++ default implementation
and never sees the new function.  Same applies to
`mousePressEvent`, `paintEvent`, every other `*Event`.

## Fix / recipe

Subclass the widget and override on the class:

```python
# scriptree/ui/widgets/param_widgets.py
class _DroppableLineEdit(QLineEdit):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls() or ev.mimeData().hasText():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        _apply_line_edit_drop(self, ev.mimeData())
        ev.acceptProposedAction()
```

Then instantiate `_DroppableLineEdit` instead of `QLineEdit`.

## How future-me detects it

Drag the file over the widget — if no border-highlight feedback
appears, the widget never accepted the drag enter, which means
the override didn't take.  Confirm with a `print` inside the
class body's `dragEnterEvent`; if the print never fires, the
vtable isn't seeing your method.
