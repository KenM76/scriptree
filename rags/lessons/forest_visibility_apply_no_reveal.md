---
topic: forest_visibility_apply_no_reveal
date: 2026-06-19
status: gotcha
related: [autohide_guard_own_modals, rescue_cells_on_reveal]
---
# ForestVisibilityManager.apply has NO reveal path — toggling into a new mode from hidden can strand the hub

## What happened

This is a LATENT fragility, NOT fixed in v0.8.0a60-a66.  It was identified
during the visibility-subsystem audit and documented as a known gap.

## Root cause

`ForestVisibilityManager.apply(prefs)` is the entry point called when the
user toggles a visibility checkbox in the Forest menu.  Its current
implementation can HIDE the hub (the `if self._auto_hide and w.isVisible()
and not w.isMinimized(): self.hide_hub()` branch at ~line 527), but has NO
complementary path to SHOW or SHOWNOMAL the hub if it is currently hidden or
minimised.

Concrete failure scenarios:

1. **Toggle INTO "always on top" from a hidden (tray-only) state.**
   The user is in tray-only mode (hub is hidden).  They open the Forest menu
   via the tray icon, check "Show always on top".  `apply()` flips the flag
   and calls `_apply_always_on_top_flag` but does not call `show_hub()`.
   The hub remains hidden.  The user now has AOT enabled with no hub visible
   and no tray icon to reveal it (AOT mode disables the tray — if the prefs
   say tray off).

2. **Disable "Show on taskbar" while the hub is minimised.**
   `apply()` calls `_apply_taskbar_flag(False)` (swaps Qt.Window → Qt.Tool,
   removing the taskbar entry) but does not call `showNormal()`.  The hub
   is now a hidden `Qt.Tool` with no taskbar entry and no tray icon.
   Unreachable.

## Why this hasn't been fixed yet

The visibility toggles in the Forest menu are only reachable from the hub's
right-click context menu, which is only available when the hub IS visible.
So in practice the user can't reach these toggles while hidden.  The
reachability is limited by the UI, not by the code.

A tray-icon menu ALSO carries the Show/Quit actions but not the Visibility
submenu — by design.  So the tray path can't trigger this issue.

## Fix (deferred)

Add a `showNormal()` / `show_hub()` call in `apply()` after mode transitions
that could leave the hub unreachable:

```python
# After _apply_taskbar_flag and _apply_always_on_top, if the hub is
# now in a "should be visible" mode but isn't:
if aot and w is not None and not w.isVisible():
    self.show_hub()
elif tb and w is not None and w.isHidden():
    # showMinimized creates the taskbar entry
    w.showMinimized()
```

This should be conditioned on "was previously in auto-hide mode and is now
switching out of it" to avoid always-showing on every preferences change.

## How future-me detects it

If the user reports "I changed a visibility setting and the hub disappeared /
I can't reach it anymore", check whether `apply()` has a reveal branch for
the new mode.  The test to write: start in tray-only hidden mode, call
`apply()` with `show_always_on_top=True`, assert the hub is now visible.
