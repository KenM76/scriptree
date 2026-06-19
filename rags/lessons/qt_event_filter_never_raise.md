---
topic: qt_event_filter_never_raise
date: 2026-06-19
status: gotcha
related: [show_before_move_desktop_api]
---
# A Qt event filter override must NEVER raise — use getattr guards for teardown safety

## What happened

During interpreter / Qt teardown, the installed event filter on the forest
hub (`ForestVisibilityManager.eventFilter`) received a final
`WindowStateChange` event after the Python object's `__dict__` had already
been partially torn down.  This produced Qt's dreaded:

```
Error calling Python override of eventFilter
```

Fixed in v0.8.0a61 alongside the show-before-move fix.

## Root cause

When the interpreter tears down a PySide6 object, Python attributes are
deleted in an undefined order.  A `QObject.eventFilter` override that reads
`self._auto_hide`, `self._taskbar_on`, `self._forest_window` etc. directly
will raise `AttributeError` during this window if those attrs have already
been cleared.  Qt catches the Python exception, prints the error string, and
swallows the event — but the error message is noisy and startling.

## Fix / recipe

Read every instance attribute via `getattr(self, "_attr", default)` inside
`eventFilter`, so a missing attr degrades to "not handled" instead of raising:

```python
def eventFilter(self, obj, event):
    fw = getattr(self, "_forest_window", None)
    if (
        fw is not None
        and obj is fw
        and event.type() == QEvent.Type.WindowStateChange
        and getattr(self, "_auto_hide", False)
        and getattr(self, "_taskbar_on", False)
    ):
        try:
            if not fw.isMinimized() and fw.isVisible():
                QTimer.singleShot(0, self._restore_descendants)
        except Exception as exc:
            _log(f"eventFilter: taskbar restore raised {exc!r}")
    return super().eventFilter(obj, event)
```

The key pattern: every `self._X` access is replaced with `getattr(self, "_X",
safe_default)`.  The `try/except` around the body catches any remaining Qt
call failures.

Implementation: `D:\Dev\ScripTree\scriptree\shell\forest_visibility.py`,
`ForestVisibilityManager.eventFilter`, lines ~785-802.

## How future-me detects it

Any `QObject` subclass that overrides `eventFilter` and reads instance
attributes must follow this pattern.  The symptom is:

```
Error calling Python override of eventFilter
```

printed during app teardown.  The fix is always the same: replace all
`self._attr` reads with `getattr` calls inside `eventFilter`.  The rule
extends to any Qt callback that can arrive after Python teardown begins
(`timerEvent`, `customEvent`, etc.).
