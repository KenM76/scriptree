# A QMenu cannot be "frozen but visible" under a sibling dialog — close it instead

**Tag**: `pyside6`
**Date**: 2026-06-05 (revised after v0.8.0a42 → a43 walkback)
**Versions affected**: v0.8.0a42 — replaced by an explicit-close design in a43

## TL;DR

When you show a frameless `QDialog` next to an open `QMenu` (e.g. for
a per-item context panel), there is **no way** to keep the menu
visible AND let the user click the dialog's buttons. Qt's popup-grab
on the menu intercepts every mouse press in the application — the
dialog's own clicks are routed through the menu's modal event loop
before they reach the dialog.

You have two real options:

1. **Close the menu when the dialog opens.** Releases the popup grab,
   the dialog becomes clickable, the user mentally bridges "this
   dialog is for the item I right-clicked" via the dialog's title.
   This is the design ScripTree shipped in v0.8.0a43.
2. **Hide the menu and overlay a screenshot widget.** Same end-state
   visually as the "frozen" idea but the screenshot is a regular
   `QLabel` with no event loop, no popup grab, no input. More work,
   only worth it if the user really, really needs the menu to stay
   on screen.

The "install an app-level event filter and swallow events on
QMenu instances" approach (v0.8.0a42) is tempting but broken — the
swallowed events include the dialog's clicks. See the failure
section below.

## Why the freeze idea fails

The intuition was: install a QObject event filter on `QApplication`
that returns `True` (swallow) for `MouseMove` / `HoverMove` /
`MouseButtonPress` / `KeyPress` / etc. whenever the target is a
`QMenu`. Menu stays painted, can't navigate. Dialog can be clicked.

What actually happens: when a `QMenu` is shown via `exec()`, it
becomes the **active popup widget** (`QApplication.activePopupWidget()`)
and acquires an **implicit mouse grab**. Qt routes every mouse event
in the application to the active popup, regardless of which window
the cursor is over. The dialog's button is under the cursor, the
user clicks — Qt sends the press to the QMenu first, our filter sees
it, swallows it, the dialog never receives the event.

Variants that DON'T fix it:

- Filtering only events whose `event.pos()` lies inside the menu's
  rect: still misses, because Qt's popup-grab redirects the event to
  the menu regardless of where it came from. `event.pos()` is the
  position relative to the menu, often well outside any sensible
  bound.
- `WA_TransparentForMouseEvents` on the menu: hit-testing is at the
  widget level, the popup grab is at the Qt-event-routing level —
  the attribute affects which child widget gets the event, not
  whether the popup chain receives it at all.
- `setEnabled(False)` on the menu: greys out every action visually
  (ugly) and may not even break the grab.

The mouse grab is the load-bearing piece. To break it, you must end
the popup loop — either by closing the menu, hiding it via
`hide()` (which Qt treats as a popup dismiss), or by destroying it.
None of those are "frozen but visible." The popup grab is
non-negotiable.

## What v0.8.0a43 does

```python
# In _show_for_action, BEFORE dlg.show():
if source_menu is not None:
    root_menu = source_menu
    while True:
        parent = root_menu.parent()
        if isinstance(parent, QMenu) and parent.isVisible():
            root_menu = parent
        else:
            break
    root_menu.close()   # cascades to all open submenus; releases grab
```

`close()` is preferred over `hide()` because it also tears down the
modal popup event loop the `QMenu` was running via `exec()` — without
that, the cell window's call site (`menu.exec(global_pt)`) is still
blocked.

We walk up to the root menu because the user might have right-clicked
inside a submenu; closing only the deepest submenu would leave the
parents open and they'd still hold the popup grab.

We do **not** reopen the menu when the dialog dismisses. The earlier
v0.8.0a30→a41 design did, via a 50 ms `QTimer` on `dlg.finished`,
but the user reported the reopen as a spurious popup ("then the tool
menu pops up again"). The dialog's title bar already shows the tool
name so the visual association doesn't need the menu to stay on
screen, and the user can re-click the cell if they want to right-click
another tool.

## Why the dialog itself wasn't the problem (debunking a tempting
red herring)

It's natural to suspect window flags: `Qt.Tool | FramelessWindowHint
| WindowStaysOnTopHint` doesn't aggressively pull focus, so maybe Qt
doesn't auto-close the menu when the dialog appears. That's true on
recent Qt builds — but it's not really the menu's "focus" that
matters, it's the popup grab. Changing the dialog's flags to
`Qt.Dialog` (which would pull focus) does cause Qt's popup auto-close
to fire, but only as a side effect; relying on it is platform-fragile.
Explicit `menu.close()` is the deterministic version.

## Three-attempt history (don't repeat it)

* **pre-a30**: explicit `menu.close()` + no reopen. Worked but no
  way to chain right-clicks. Replaced.
* **a30-a41**: relied on Qt to auto-close the menu when the dialog
  got focus, then re-opened via a 50 ms timer on `dlg.finished` so
  the user could chain right-clicks. The menu stayed open on some Qt
  builds; the highlight drifted with the cursor; the reopen was
  spurious.
* **a42**: tried to keep the menu visible-but-frozen via an app-level
  `_MenuFreezeFilter`. Swallowed mouse / hover / wheel / key events
  on every QMenu instance. Drift fixed, dialog clicks dead.
* **a43** (current): close the menu, no reopen. Simple, works,
  shippable.

## User report (verbatim, both rounds)

Round 1 (a41 problem → motivated a42's freeze):

> "When I left click on a cell and pop up the tool menu, then right
> click a tool in the menu to bring up the action menu for that
> tool, the underlying menu should stay locked in place while I have
> the action menu open for that too. Right now if I move the mouse I
> end up navigating the tool menu and the action menu get's left
> behind."

Round 2 (a42's freeze → motivated a43's walkback):

> "Now when I right click the tool in the tool menu, I can't click
> on anything in the action menu until I click on the x on the tool
> menu to close it. then the other menu becomes active. after this I
> can click on the items in the action menu and they activate, but
> then the tool menu-pops up again."

## Cross-reference

- `rags/lessons/qmenu_per_action_right_click.md` — how the
  right-click on a `QAction` is captured in the first place (event
  filter on every QMenu in the popup tree)
- `rags/lessons/qmenu_outside_click_redispatches.md` — Qt's
  outside-click rebroadcast quirk when menus close

## File pointers

- `scriptree/shell/tree_popup.py`:
  - `_show_for_action(ctx, global_pt, source_menu, source_action)`
    — the close-menu-before-show path lives in the tail of this
    method
  - The note where `_MenuFreezeFilter` used to be — kept as a
    comment block so future me doesn't re-discover the dead-end
