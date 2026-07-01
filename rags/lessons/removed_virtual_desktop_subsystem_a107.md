# Removed the Windows virtual-desktop "follow the user" subsystem (a107)

**Tag:** [v3-architecture] [forest] [windows] [removal] [cleanup]
**Version:** v0.8.0a107
**Files:** deleted `scriptree/shell/win_virtual_desktops.py`; gutted the follow
logic from `scriptree/shell/forest_visibility.py` (`_FocusWatcher` follow
plumbing, `show_hub`/`_restore_descendants` desktop moves, `_follow_user_across_
desktops` + the two dead `_ensure_*_on_current_desktop` methods); removed
`TestRestoreDescendantsDesktopOrder` + `TestVirtualDesktopFollowGuards` from
`tests/test_forest.py`; cleaned doc/comment refs (`debug_logging.py`,
`forest_controller.py`, `run_scriptreering.py`).
**Archive:** `docs/archive/removed_virtual_desktop_a107/` (full module `.txt` +
reimplementation notes); full pre-removal source in
`D:\Dev\ScripTree-backups\scriptree-src-a106-*.zip`.

## Why removed (user request)

The a55–a70 "forest follows you across Windows virtual desktops" feature never
worked reliably — the hub would strand on the wrong desktop ("forest
disappeared, cells left behind") and the tangle of show-time desktop moves +
per-focus-event COM calls complicated the basic single-screen / multi-monitor
GUI behaviour the user was trying to stabilise. The user asked to remove it and
re-attempt later with a different approach. **Multi-MONITOR (multiple physical
screens) support was KEPT — only multi-DESKTOP (Windows virtual desktops) was
removed.** (Don't conflate the two: "monitor" = physical screen, clamp/rescue
logic stays; "desktop" = Windows virtual desktop, COM `MoveWindowToDesktop`,
gone.)

## What the feature did (and the gotchas to carry forward)

`_FocusWatcher` fired on `focusWindowChanged`; a 120ms-debounced `_fire_follow`
called `_follow_user_across_desktops`, which (if the hub was on a different
virtual desktop than the user) `MoveWindowToDesktop`'d the hub + visible
descendants to the current desktop. `show_hub`/`_restore_descendants` did
corrective moves on reveal. Hard-won facts for any re-implementation:

1. **`MoveWindowToDesktop` rejects a HIDDEN window** (`TYPE_E_ELEMENTNOTFOUND
   0x8002802B`) but accepts a MINIMISED one. So move-before-show works in
   taskbar mode (minimise → move → `showNormal`) but tray mode must show-then-
   move (brief flash). This timing dance was a chronic fragility source.
2. **Per-focus-event moves are racy.** Raw moves on every `focusWindowChanged`
   fired bursts during focus churn (drag, alt-tab) and stranded the hub — hence
   the a70 debounce + a `_drag_started` guard (NEVER move across desktops
   mid-drag). A future approach should avoid per-focus moves entirely (consider
   native "show on all desktops"/pinning instead of chasing focus).
3. The feature was **independent of auto-hide** (user wanted reachability on
   every desktop regardless), so it lived in the always-on focus watcher, not
   the hide path.

## Mechanics of the removal (reusable approach)

* **Archive before deleting.** Copied the whole module to a `.txt` (un-importable)
  + wrote a reimplementation README; the a106 source zip preserves everything
  verbatim. The user explicitly wants to redo it later.
* **Distinguish "remove" vs "neuter to single-screen."** The COM module + the
  three follow methods were pure-vdesktop → deleted whole. `show_hub` /
  `_restore_descendants` / `_FocusWatcher` were SHARED (they also do the kept
  show/hide/clamp/rescue) → surgically stripped of just the desktop-move blocks.
* **Tests split the same way:** pure-vdesktop test classes deleted; the
  rescue/clamp tests that merely *mocked* `wvd.is_supported=False` to bypass the
  move were kept with the now-dead mock removed (else the import of the deleted
  module errors the test).
* Verified: `import` of the touched modules + `test_forest.py` (104) green.

## Reusable takeaways

1. **"Make it work across X" features that chase OS state (virtual desktops,
   focus) via timing-sensitive native calls are a fragility magnet.** When one
   complicates the base behaviour, removing it to get the basics solid first is
   legitimate — archive it, don't just delete.
2. **Name the axis precisely.** "Multi-monitor" ≠ "multi-desktop." A vague
   removal request can nuke the wrong half; confirm which.
3. **Strip shared functions surgically, delete pure ones wholesale** — and fix
   the tests that only *mocked away* the removed dependency.
