---
topic: pyside6
date: 2026-06-04
status: gotcha
related: [qmainwindow_as_child_widget, vocabulary_disambiguation_before_editing]
---
# QtAds toggleView(False)+toggleView(True) on a floating dock re-pops the window

## What happened

User report from v0.8.0a38 era: "single left clicking on a tool...
pops up a new [popup] every time I click on a tool." Every left-
click in the developer-editor tree was making a fresh floating
window appear, even though the user had already detached the Output
and Run-controls docks and arranged them to taste.

## Root cause

`MainWindow._show_runner` ran a full panel reinstall cycle on EVERY
click: `_uninstall_runner_panels` followed by
`_install_runner_panels`. Internally, each of those called
`QtAds.CDockWidget.toggleView(False)` followed by `toggleView(True)`
on the Output and Run-controls dock widgets.

When the docks are still attached to the main window, the off-on
cycle is visually a no-op — the panel area is the same area. But
when the user has DETACHED a dock (it's now a floating QtAds
container in its own top-level window), `toggleView(False)` hides
the floating frame and `toggleView(True)` shows it again. To the
user that reads as "a new popup appeared on every click."

Subtlety: `toggleView(True)` is NOT idempotent against an already-
visible floating dock. It treats the call as a state transition
from hidden → shown, with all the side effects of bringing a window
to the foreground.

## Fix / recipe

Two guards in v0.8.0a39:

1. `_show_runner` short-circuits when the cached runner IS the
   active runner for the clicked tool — no uninstall/install dance
   for same-tool re-click.
2. `_install_runner_panels` guards each `toggleView(True)` behind
   an `isVisible()` check so it doesn't re-show an already-visible
   dock.

```python
if dock_widget.isVisible():
    return  # don't toggleView(True); it side-effects floating docks
dock_widget.toggleView(True)
```

## How future-me detects it

- Symptom: a QtAds-hosted panel "pops up" or "flashes to front"
  unexpectedly when the user repeats an action. Suspect a
  `toggleView` call cycling state on an already-visible dock.
- Rule of thumb: treat `toggleView(True)` on a CDockWidget as a
  hidden→shown transition. Always check `isVisible()` first when
  the intent is "make sure it's visible," not "show it again."
- Same caution applies anywhere a dock might be floating — any
  off/on cycle pattern is a potential floating-window pop.
