---
topic: show_before_move_desktop_api
date: 2026-06-19
status: empirical
related: [autohide_guard_own_modals, qt_event_filter_never_raise]
---
# Show the window before moving it across virtual desktops — HIDDEN windows reject MoveWindowToDesktop

## What happened

After the v0.8.0a59 fix ("move while minimised, don't hide first") the
taskbar-RESTORE path (`_restore_descendants`) still moved cells to the
current virtual desktop BEFORE showing them.  The cells appeared on the
forest's OLD desktop instead of beside the hub on the user's current one.
Fixed in v0.8.0a61.

## Root cause

`MoveWindowToDesktop` (the Windows virtual-desktop COM API) returns
`TYPE_E_ELEMENTNOTFOUND` (HRESULT `0x8002802B`) when the target window is in
a HIDDEN (`.hide()`-d) state.  A MINIMISED window accepts the call fine; a
hidden window does not.

The a59 fix correctly handled the HUB (kept minimised, moved, then restored),
but the sibling path `_restore_descendants` still moved the tracked cells
BEFORE calling `cell.show()`.  Those cells were hidden (not minimised) so
every `MoveWindowToDesktop` call silently no-op'd.

The general rule: **show first, then move**.  Hidden windows reject the COM
call; minimised windows accept it.

## Fix / recipe

In `_restore_descendants` (and any future reveal path):

```python
# WRONG — move while hidden
for cell in cells:
    wvd.move_window_to_desktop(int(cell.winId()), desktop_id)
    cell.show()

# CORRECT (a61) — show first, then move
shown = []
for cell in cells:
    cell.show()
    shown.append(cell)
for cell in shown:
    wvd.move_window_to_desktop(int(cell.winId()), desktop_id)
```

This mirrors the a59 pattern for the hub in `show_hub`.

Implementation: `D:\Dev\ScripTree\scriptree\shell\forest_visibility.py`,
`_restore_descendants`, lines ~829-858.

## How future-me detects it

Every new "reveal" path (show hub from tray, taskbar restore, programmatic
reveal, cell rescue) that also calls `MoveWindowToDesktop` must show the
window BEFORE the COM call.  Symptom of the bug: cells appear on the wrong
virtual desktop after a taskbar click or tray-icon reveal.  Grep for
`move_window_to_desktop` call sites and verify each one is preceded by
`.show()` or `.showNormal()` on the same window.

Also note: this lesson is the SIBLING-PATH corollary to a59.  Whenever you
fix "show before move" on ONE reveal path, audit every other reveal path
for the same defect.
