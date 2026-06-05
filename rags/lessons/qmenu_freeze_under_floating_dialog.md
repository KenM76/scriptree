# A QMenu cannot be "frozen visible" under a sibling dialog — snapshot it instead

**Tag**: `pyside6`
**Date**: 2026-06-05 (final revision; a44 shipped the snapshot approach)
**Versions affected**: v0.8.0a42 (broken freeze) → a43 (close + don't reopen) → **a44 (snapshot overlay + reopen on X)**

## TL;DR

When you show a frameless `QDialog` next to an open `QMenu` (e.g. for
a per-item context panel), you CANNOT keep the menu visible AND let
the user click the dialog. Qt's popup-grab on the menu intercepts
every mouse press in the application; an event filter that swallows
mouse events on `QMenu` instances also swallows the dialog's clicks.

If the UX requires the menu to **look** like it's still there, the
correct approach is a **screenshot overlay**:

1. While the real menu is visible, grab each open `QMenu` in the
   popup chain via `QWidget.grab()` and record its global position.
2. Close the real menu (releases the popup grab and ends the
   `menu.exec()` blocking loop).
3. Show a frameless, mouse-transparent, always-on-top `QLabel` for
   each snapshot, positioned at the original menu's location.
4. Show the dialog on top of the labels.
5. On dialog `finished`: destroy the overlay labels. If the user
   asked for the menu back (e.g. they clicked the dialog's X), call
   `show_tree_popup_for(...)` to bring up a fresh real menu.

The labels are visual-only — they don't grab input, they don't run
event loops, they don't compete with the dialog. Qt happily renders
them, the user sees what looks like the menu still being there, and
the dialog underneath is fully responsive.

## Why an app-level event filter that swallows QMenu events fails

The intuition was: install a QObject event filter on `QApplication`
that returns `True` (swallow) for `MouseMove` / `HoverMove` /
`MouseButtonPress` / `KeyPress` / etc. whenever the target is a
`QMenu`. Menu stays painted, can't navigate. Dialog can be clicked.

What actually happens: when a `QMenu` is shown via `exec()` it
becomes the **active popup widget** (`QApplication.activePopupWidget()`)
and acquires an **implicit mouse grab**. Qt routes every mouse event
in the application to the active popup, regardless of which window
the cursor is over. The dialog's button is under the cursor, the
user clicks — Qt sends the press to the QMenu first, our filter sees
it, swallows it, the dialog never receives the event.

Variants that DON'T fix this:

- Filtering only events whose `event.pos()` lies "inside the menu":
  the popup grab redirects the event to the menu regardless of cursor
  position, and `event.pos()` is relative to the menu — often well
  outside any sensible bound.
- `WA_TransparentForMouseEvents` on the menu: hit-testing is at the
  widget level, the popup grab is at the Qt-event-routing level —
  the attribute affects which child widget gets the event, not
  whether the popup chain receives it at all.
- `setEnabled(False)` on the menu: greys out every action visually
  AND may not even break the grab.

The mouse grab is the load-bearing piece. To break it, you must end
the popup loop — either by `close()` / `hide()` / destroying the
menu. None of those are "frozen but visible." The popup grab is
non-negotiable.

**Conclusion**: if you want the visual without the input behaviour,
replicate the visual via a screenshot. Don't fight the grab.

## The a44 snapshot recipe

```python
# Collect every QMenu currently visible in the popup chain.
# Walk up from source_menu to the root, then back down from the
# root to catch any open submenus we didn't pass through.
chain_up = []
m = source_menu
while m is not None:
    if isinstance(m, QMenu) and m.isVisible():
        chain_up.append(m)
    parent = m.parent() if isinstance(m, QMenu) else None
    if isinstance(parent, QMenu):
        m = parent
    else:
        break
root_menu = chain_up[-1] if chain_up else source_menu

def _collect_open(m, acc):
    if not isinstance(m, QMenu):
        return
    for action in m.actions():
        sub = action.menu()
        if sub is not None and sub.isVisible():
            acc.append(sub)
            _collect_open(sub, acc)

all_menus = list(chain_up)
_collect_open(root_menu, all_menus)

# Dedup preserving order (chain_up walks up; _collect_open walks
# down; the source menu shows up in both).
seen_ids = set()
unique_menus = []
for mm in all_menus:
    if id(mm) in seen_ids:
        continue
    seen_ids.add(id(mm))
    unique_menus.append(mm)

# Snapshot WHILE the menus are still on screen.
snapshots = []
for mm in unique_menus:
    pos = mm.mapToGlobal(QPoint(0, 0))
    pixmap = mm.grab()
    snapshots.append((pixmap, pos))

# Close the real menu chain — cascades from the root.
root_menu.close()

# Mount the overlay labels.  WindowTransparentForInput +
# WA_TransparentForMouseEvents + WA_ShowWithoutActivating
# together guarantee they never compete for focus or clicks.
overlays = []
for pixmap, pos in snapshots:
    overlay = QLabel(None)
    overlay.setPixmap(pixmap)
    overlay.setFixedSize(pixmap.size())
    overlay.setWindowFlags(
        Qt.WindowType.Tool
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.WindowTransparentForInput
    )
    overlay.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    overlay.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    overlay.move(pos)
    overlay.show()
    overlays.append(overlay)

dlg._st_menu_screenshots = overlays  # keep refs alive
```

Three Window/widget flags worth pinning down because they're all
needed:

| Flag | What it does | Why we need it |
|---|---|---|
| `WindowTransparentForInput` | Native window doesn't receive any input | OS-level pass-through; the OS routes clicks to the window below (the dialog) |
| `WA_TransparentForMouseEvents` | Qt widget doesn't receive mouse events | Defense in depth at the Qt layer |
| `WA_ShowWithoutActivating` | Showing the label doesn't activate / steal focus | Without this the label briefly grabs focus on show and the dialog loses keyboard input |
| `WA_DeleteOnClose` | C++ object is deleted on `close()` | Avoid a leak if the cleanup loop races a fast dismiss |

## Dismiss behaviour — distinguishing X from action from outside

`QDialog.finished` fires for all three close paths and doesn't
distinguish them. Tag the close reason with an instance attribute set
by each button handler; outside-click leaves the default in place:

```python
dlg._st_close_reason = "outside"  # default

def _close_via_x():
    dlg._st_close_reason = "x"
    dlg.close()
x_btn.clicked.connect(_close_via_x)

def _trigger_open(p=leaf_path):
    dlg._st_close_reason = "action"
    self._on_open_folder(p)
    dlg.close()
btn_open.clicked.connect(_trigger_open)

def _on_dialog_finished(_r=0):
    reason = getattr(dlg, "_st_close_reason", "outside")
    for overlay in getattr(dlg, "_st_menu_screenshots", []):
        overlay.close()
    dlg._st_menu_screenshots = []
    if reason == "x":
        QTimer.singleShot(50, lambda: show_tree_popup_for(hex_win))
dlg.finished.connect(_on_dialog_finished)
```

The 50 ms delay before the reopen lets Qt finish the dialog's own
teardown / re-event-loop transitions before we run a new
`menu.exec()`. Without it the fresh menu can land under the closing
dialog's z-order on some platforms.

## Three-attempt history (don't repeat it)

* **pre-a30**: explicit `menu.close()` + no reopen. Worked but no way
  to chain right-clicks. Replaced.
* **a30-a41**: relied on Qt to auto-close the menu when the dialog
  got focus, then re-opened via a 50 ms timer on `dlg.finished` so
  the user could chain right-clicks. The menu stayed open on some Qt
  builds; the highlight drifted with the cursor; the reopen was
  spurious.
* **a42**: tried to keep the menu visible-but-frozen via an app-level
  `_MenuFreezeFilter`. Swallowed mouse / hover / wheel / key events
  on every QMenu instance. Drift fixed, dialog clicks dead.
* **a43**: gave up on keeping the menu visible. Close the real menu,
  no reopen. Functionally fine, lost the visual context the user
  wanted.
* **a44** (current): snapshot overlay. Visual context kept (screenshot
  of every open menu pinned in place), grab released (real menu
  closed), dismiss matrix matches user spec (X reopens, action /
  outside don't).

## User report (verbatim, all three rounds)

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

Round 3 (a43 was too aggressive → motivated a44's snapshot):

> "I still want the tool menu visible after I right click on a tool
> and bring up the action menu, and if I click the x on the action
> menu to close it, the tool menu underneath should become
> responsive again. if I click somewhere on screen away from the
> action menu or click an option on the action menu then the tool
> menu and action menu should close."

## Cross-reference

- `rags/lessons/qmenu_per_action_right_click.md` — how the
  right-click on a `QAction` is captured in the first place (event
  filter on every QMenu in the popup tree)
- `rags/lessons/qmenu_outside_click_redispatches.md` — Qt's
  outside-click rebroadcast quirk when menus close

## File pointers

- `scriptree/shell/tree_popup.py`:
  - `_show_for_action(ctx, global_pt, source_menu, source_action)`
    — the snapshot collection + close + overlay mount lives in the
    tail of this method (~lines 1440-1600 as of a44)
  - The note where `_MenuFreezeFilter` used to be — kept as a
    comment block so future me doesn't re-discover the dead-end
