---
topic: autohide_guard_own_modals
date: 2026-06-19
status: empirical
related: [focus_watcher_parent_walk_limits, forest_visibility_apply_no_reveal]
---
# Auto-hide must guard against its own modal dialogs and popup menus

## What happened

The forest hub would vanish while the user was interacting with a dialog
the forest itself spawned — for example, a `QMessageBox.warning(...)` popped
by the forest's Settings flow, or the cell right-click context menu.  The
auto-hide logic (a52-era "forest vanishes while I'm in a dialog" complaint)
was fixed in v0.8.0a60.

## Root cause

`_FocusWatcher._fire` checks `QApplication.activeWindow()` and calls
`_is_inside_forest()` to decide whether to hide.  `_is_inside_forest` walks
the active widget's parent chain looking for a `CellWindow` or the forest hub.
The walk is sound for PARENTED dialogs, but a `QMessageBox.warning(parent=None,
...)` (static convenience call) or any other unparented dialog has NO Qt parent
at all — its `parent()` chain terminates immediately at the `QMessageBox` itself.
The walk therefore returns `False` ("not inside the forest"), and `_fire`
concluded that focus had left the forest and hid the hub mid-interaction.

## Fix / recipe

Insert an unconditional early-return at the TOP of `_fire` before the
`_is_inside_forest` call:

```python
# forest_visibility.py — _FocusWatcher._fire  (v0.8.0a60)
try:
    if (
        app.activeModalWidget() is not None
        or app.activePopupWidget() is not None
    ):
        return   # one of OUR dialogs / menus is open — don't hide
except Exception:
    pass
```

`QApplication.activeModalWidget()` and `QApplication.activePopupWidget()` only
ever return widgets that belong to THIS Qt application process.  So if either
is non-None, the user is plainly still interacting with ScripTree; suppress
the hide until the dialog / menu closes.

Implementation: `D:\Dev\ScripTree\scriptree\shell\forest_visibility.py`,
`_FocusWatcher._fire`, lines ~379-385.

## How future-me detects it

Symptom: forest hub + cells disappear while a ScripTree-spawned dialog is
open — Settings, About, any `QMessageBox.warning`, or the cell context menu.
Also triggers when a static `QMessageBox.warning(parent=None, ...)` call has
no parent to walk to.  The invariant: if `activeModalWidget/activePopupWidget`
is non-None, the code MUST return without hiding.
