# Freezing a QMenu in place while a sibling dialog has focus

**Tag**: `pyside6`
**Date**: 2026-06-05
**Versions affected**: pre-v0.8.0a42 — fixed in v0.8.0a42

## TL;DR

When you pop a frameless `QDialog` next to an open `QMenu` (e.g. for a
per-item context panel), the menu stays VISIBLE and continues to
respond to mouse-move / hover / wheel / key events. The user moves
their mouse toward the dialog, drifts over the menu, and watches the
highlighted action drift away from the one their dialog belongs to —
the visual association between "this dialog" and "this menu item"
breaks immediately.

**Fix**: while the dialog is alive, install a QApplication-level event
filter that swallows interactive events targeted at every `QMenu`
instance. Pin the right-clicked action as the menu's active item once
so the highlight stays anchored. Remove the filter on `dialog.finished`.

This is independent of the
[per-action right-click filter](qmenu_per_action_right_click.md)
that catches the right-click in the first place — that one only
intercepts a brief event cycle, this one suspends ALL menu
interaction for the lifetime of a sibling window.

## Why an APP-level filter, not per-menu?

Qt routes mouse events to the topmost `QMenu` *under the cursor*, not
to the menu we showed the dialog for. A submenu the user hovered into
will be the actual recipient of mouse-move events, and a filter only
on the top menu won't see them. The popup chain can also contain
menus we don't directly know about (Qt's own submenus opened lazily).

Filtering at `QApplication.installEventFilter` level and gating on
`isinstance(obj, QMenu)` covers every open menu in one shot.

## The freezer

```python
class _MenuFreezeFilter(QObject):
    _FREEZE_TYPES = frozenset({
        QEvent.Type.MouseMove,
        QEvent.Type.HoverMove,
        QEvent.Type.HoverEnter,
        QEvent.Type.HoverLeave,
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonRelease,
        QEvent.Type.MouseButtonDblClick,
        QEvent.Type.Wheel,
        QEvent.Type.KeyPress,
        QEvent.Type.KeyRelease,
        QEvent.Type.ShortcutOverride,
        QEvent.Type.ContextMenu,
    })

    def eventFilter(self, obj, event) -> bool:
        if isinstance(obj, QMenu) and event.type() in self._FREEZE_TYPES:
            return True            # swallow -- menu does not respond
        return False                # everything else flows normally
```

**Events deliberately NOT swallowed**: `Paint`, `Resize`, `Show`,
`Hide`. The menu must still repaint as the dialog moves over it, and
Qt's hide-on-dialog-close path must still work. Events on non-`QMenu`
objects (the dialog itself, the rest of the app) pass through
untouched.

`ShortcutOverride` is in the swallow set because without it a keypress
inside the menu's event loop still triggers a shortcut-bound action
even when `KeyPress` is dropped.

## Install/remove pairing

```python
_app = QApplication.instance()
freezer = _MenuFreezeFilter(_app)
_app.installEventFilter(freezer)
dlg._st_menu_freezer = freezer    # keep a strong ref on the dialog

def _remove(_r: int = 0) -> None:
    app = QApplication.instance()
    flt = getattr(dlg, "_st_menu_freezer", None)
    if app is not None and flt is not None:
        app.removeEventFilter(flt)
    try: delattr(dlg, "_st_menu_freezer")
    except Exception: pass

dlg.finished.connect(_remove)
```

Two anchors that matter:

1. **Strong ref on the dialog** — `_app.installEventFilter` doesn't
   take ownership; without `dlg._st_menu_freezer = freezer` the
   `QObject` is eligible for GC the moment the local goes out of
   scope, and your menus get un-frozen seconds into the dialog.
2. **`finished` not `destroyed`** — `destroyed` fires after the C++
   object is gone, so `getattr(dlg, ...)` raises. `finished` runs
   while the Python wrapper is still valid and is emitted on every
   close path (X, accept, reject, escape).

## Anchoring the highlight

Before showing the dialog, pin the right-clicked action as the menu's
active item:

```python
source_menu.setActiveAction(source_action)
```

Without this, the highlight is wherever the user's mouse happened to
be when they right-clicked, which is usually correct but isn't
guaranteed. Calling `setActiveAction` once makes the association
deterministic. The freezer then keeps it pinned because every event
that would shift the highlight gets swallowed.

## Where this lives in ScripTree

- `scriptree/shell/tree_popup.py`:
  - `_MenuFreezeFilter` (sibling of `_PerItemContextFilter`)
  - `_show_for_action(ctx, global_pt, source_menu, source_action)` —
    extended signature so the right-click handler can plumb the menu
    + action through
  - Install/remove happens in `_show_for_action`'s tail, gated on
    `source_menu is not None and source_action is not None` so older
    callers still work.

## User report (verbatim)

> "When I left click on a cell and pop up the tool menu, then right
> click a tool in the menu to bring up the action menu for that
> tool, the underlying menu should stay locked in place while I have
> the action menu open for that too. Right now if I move the mouse I
> end up navigating the tool menu and the action menu get's left
> behind."

## When to apply

Any time you show a sibling popup (dialog, panel, tooltip-like
window) that should "belong to" one item of an open QMenu. Without
this freeze, the menu acts independently and the visual link breaks
the moment the user moves the mouse.

## Cross-reference

- `rags/lessons/qmenu_per_action_right_click.md` — how the
  right-click on a QAction is captured in the first place
- `rags/lessons/qmenu_outside_click_redispatches.md` — Qt's quirky
  re-dispatch behaviour when menus close; relevant if you ever want
  to **dismiss** the menu instead of freezing it
