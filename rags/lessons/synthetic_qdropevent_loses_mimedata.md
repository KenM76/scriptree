---
topic: pyside6
date: 2026-05-07
status: gotcha
related: [qt_drag_drop_needs_subclass]
---
# Synthetic QDropEvents lose QMimeData type in PySide6

## What happened

Wrote a pytest that constructed a `QDropEvent` in Python and
called the widget's `dropEvent(ev)` directly.  Inside the
handler, `ev.mimeData()` returned an opaque base `QObject`
that couldn't be cast back to `QMimeData` and had none of
the `.urls()` / `.text()` accessors.

## Root cause

PySide6 doesn't preserve the Python-constructed `QMimeData`
through the synthetic event round-trip.  The C++ side stores
a `QMimeData*` and on the way back out hands you a generic
`QObject` wrapper.  Real Qt-generated events come through the
event loop with a different code path that preserves the
type.

## Fix / recipe

Don't test the event handler directly.  Factor the actual
drop logic into a helper that takes a `QMimeData` argument,
and test that helper:

```python
# scriptree/ui/widgets/param_widgets.py
def _apply_line_edit_drop(le: QLineEdit, mime: QMimeData) -> None:
    if mime.hasUrls():
        le.setText(mime.urls()[0].toLocalFile())
    elif mime.hasText():
        le.setText(mime.text())

class _DroppableLineEdit(QLineEdit):
    def dropEvent(self, ev):
        _apply_line_edit_drop(self, ev.mimeData())
        ev.acceptProposedAction()
```

In the test, build a real `QMimeData` and call
`_apply_line_edit_drop(le, mime)` directly.

## How future-me detects it

A test that builds a `QDropEvent` and calls
`widget.dropEvent(ev)` works at the C++ level (no exception)
but the handler sees an empty `mimeData`.  If you find
yourself reaching for `sip.cast` or `shiboken6.wrapInstance`
to recover the type, stop — refactor into a helper and test
the helper instead.
