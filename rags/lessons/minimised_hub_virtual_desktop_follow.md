---
topic: minimised_hub_virtual_desktop_follow
date: 2026-06-19
status: gotcha
related: [show_before_move_desktop_api, forest_visibility_apply_no_reveal]
---
# A minimised taskbar-mode hub does NOT follow the user across virtual desktops — IsWindowOnCurrentVirtualDesktop returns True for minimised windows on other desktops

## What happened

This is a LATENT fragility, NOT fixed in v0.8.0a60-a66.  When the forest hub
is in taskbar mode (minimised to the taskbar) and the user switches to a
different virtual desktop, the hub does NOT follow — even though the
`_follow_user_across_desktops` logic is wired and claims the hub is "on the
current desktop".

## Root cause

`win_virtual_desktops.is_window_on_current_desktop(hwnd)` calls the Windows
`IVirtualDesktopManager.IsWindowOnCurrentVirtualDesktop` COM method.
**This method returns True for a minimised window regardless of which virtual
desktop it logically lives on.**  A minimised window is considered "current"
from the COM API's perspective because it has no visible presence on any
specific desktop — the OS reports it as globally accessible.

So `_follow_user_across_desktops` calls `is_window_on_current_desktop(hwnd)`,
gets `True` (because the hub is minimised), concludes "hub is already here",
and returns without moving it.  The user switches to desktop B; the taskbar
entry is visible on desktop B (minimised windows show on all taskbars), but
clicking it restores the hub on DESKTOP A (where it was originally shown),
not desktop B.

## Impact

Only visible when:
- `show_on_taskbar = True`, `show_always_on_top = False` (taskbar mode).
- The user has Windows 11 virtual desktops enabled.
- The hub is currently minimised.

The follow-the-user feature (a55) works correctly in all other modes (AOT:
hub is always visible, follows on focus; hidden/tray: hub is hidden, follows
on show).

## Potential fix (deferred)

The fix is non-trivial because `IVirtualDesktopManager` is the only stable
COM interface and it lies for minimised windows.  Options:

1. Use the undocumented `IVirtualDesktopManagerInternal` (private interface,
   breaks on OS updates).
2. Track the "last desktop the hub was explicitly shown on" ourselves and
   call `MoveWindowToDesktop` on taskbar-restore instead of relying on
   `is_window_on_current_desktop`.
3. Accept the limitation and document it.

Option 3 is the current stance.

## How future-me detects it

If a user reports "the forest hub doesn't follow me when I'm using taskbar
mode", check:
1. Is `show_on_taskbar = True`?
2. Is the hub currently minimised?
3. Add a log line in `_follow_user_across_desktops` that prints the return
   value of `is_window_on_current_desktop` when the hub is minimised.
   If it always prints `True`, this is the documented known-gap.
