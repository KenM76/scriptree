---
topic: draggable_qmenu_popup_gotchas
date: 2026-06-26
status: feature-abandoned-lessons-captured
version: 0.8.0a86 (reverted in a87)
related: [version_lives_in_two_files, menu_appearance_apply_recursive]
tags: [pyside6, v3-process, ui]
---
# Making a QMenu draggable — why it failed, and what we learned (a86, reverted a87)

User ask: "when I click a forest/cell to bring up a menu, let me drag the menu
to another location."  We attempted a ``DraggableMenu(QMenu)`` subclass three
times; it never moved the popup in real use.  Feature reverted; replaced by a
"Reset layout" action (the real pain was menus/windows opening in awkward
spots, better solved there).  Capturing the Qt gotchas so we don't re-walk this.

## Gotcha 1 — a QMenu popup does NOT deliver ``mouseMoveEvent`` to your override during a button-held drag

The core approach (override ``QMenu.mouseMoveEvent`` and ``self.move()`` the
popup by the cursor delta) **silently does nothing**.  Instrumenting all three
handlers and reading the verbose log proved it:

```
[menu-drag] press armed local=(23,337) menu_pos=(3143,1089)
[menu-drag] press armed local=(40,337) menu_pos=(3143,1089)
```

``mousePressEvent`` fires (we see "press armed"), but there is **no**
``drag-start`` / ``move#`` line afterward — i.e. ``mouseMoveEvent`` is never
called for the drag.  A QMenu shown as a ``Qt.Popup`` owns an internal mouse
grab and routes move events through ``QMenuPrivate`` for item-hover/submenu
navigation; the public ``mouseMoveEvent`` virtual is NOT invoked the way it is
for a normal widget drag.  So overriding it to move the popup can't work.

**The fix we did NOT ship** (feature abandoned): take an explicit
``self.grabMouse()`` in ``mousePressEvent`` after detecting the drag, ``move()``
in ``mouseMoveEvent``, ``releaseMouse()`` in ``mouseReleaseEvent``.  An explicit
grab forces move-event delivery to your handler — but nested grabs inside a
popup are fragile (can break the menu's click-away dismissal), which is part of
why we walked away.

## Gotcha 2 — direct-handler-call unit tests give FALSE confidence for popup behaviour

Every iteration's unit tests PASSED while the real feature FAILED.  The tests
built synthetic ``QMouseEvent``s and called ``menu.mouseMoveEvent(ev)``
**directly**, which exercises the move MATH but bypasses the real popup event
routing — so they cannot catch "the popup never calls mouseMoveEvent."

Lesson: for popup / mouse-grab GUI behaviour, a test that calls the event
handler directly proves only the arithmetic, never the delivery.  You need real
event posting against a SHOWN popup (and even ``QTest`` + popups is unreliable
headless) or a manual test.  Treat green direct-handler tests as necessary, not
sufficient, for anything involving Qt's event grab/routing.

## Gotcha 3 — a designated drag-handle row is undiscoverable, and menus open UPWARD near a screen edge

Two cuts used a designated handle (first the greyed "ScripTree: <name>" title,
then an explicit "≡ drag to move" bar at the top).  The log showed every real
press landing ``in_handle=False``:
- A greyed title looks informational, not grabbable.
- A context menu opened near the SCREEN BOTTOM grows **upward**, so the cursor
  lands near the menu's BOTTOM while a top handle sits ~300 px away — the user
  presses the menu body, never the handle (``menu_pos=(3143,1089)``, press
  ``local.y=337``).

"Drag anywhere" (press + move past an ~8 px threshold = drag; click-in-place =
select the item) is the correct UX model for "move the menu" — but it still
hit Gotcha 1, so it didn't rescue the feature.

## Gotcha 4 — ``int(Qt.MouseButton)`` raises in PySide6, and a broad ``except`` hid it

A diagnostic line ``int(e.button())`` threw ``TypeError: int() argument must be
... not 'MouseButton'``.  It was inside a broad ``try/except`` around the press
logic, so the exception was swallowed and the press path silently broke (the
drag never armed).  Two lessons: log enums AS the enum (``e.button()``), not
``int(...)``; and don't wrap critical-path code in a broad ``except`` that can
swallow a *logging-line* bug into a functional break.  (A unit test caught this,
not the user — the one place direct-handler tests did pay off.)

## Meta-lesson — when a Qt feature means fighting popup internals, re-examine the underlying need

An "if possible" nicety became a multi-build rabbit hole against Qt's popup
grab.  The real user pain (menus opening off-screen / over cells; a tool window
whose docks were merged) was better served by a **"Reset layout"** action than
by making menus draggable.  Abandoning the drag and pivoting was the right call.
Default: time-box a Qt-internals fight, and ask whether a simpler affordance
solves the actual problem.

## What was reverted (a87)

- Deleted ``scriptree/shell/draggable_menu.py`` and ``tests/test_draggable_menu.py``.
- ``cell_window._show_context_menu`` restored to plain ``QMenu(None)`` (removed
  the ``DraggableMenu`` import/instantiation, ``setToolTipsVisible``, and the
  ``add_top_drag_bar()`` call).
- The ``[bloom-diag]`` instrumentation (a separate, still-dormant stacked-cell
  diagnostic) was left in place — it is unrelated to the menu work.
