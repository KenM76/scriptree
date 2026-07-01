# Removed: Windows virtual-desktop "follow the user" subsystem (v0.8.0a107)

This subsystem was **removed** in v0.8.0a107 at the user's request — it never
worked reliably (the hub would strand on the wrong desktop / "disappear, cells
left behind"), and it complicated the basic single-screen/multi-monitor GUI
behaviour we were trying to stabilise. **We intend to re-implement it later,
probably with a different approach** (e.g. native window pinning / "show on all
desktops", or a cleaner event model), so this folder preserves what was deleted.

> NOTE: **multi-MONITOR** (multiple physical screens) support was KEPT. Only
> **virtual-DESKTOP** (multiple Windows virtual desktops) code was removed.

## What's here / where the full code lives

* `win_virtual_desktops.py.txt` — the **entire** COM module, verbatim (renamed
  `.txt` so it can never be imported). This wrapped `IVirtualDesktopManager`:
  `is_supported()`, `is_window_on_current_desktop(hwnd)`,
  `get_window_desktop_id(hwnd)`, `get_current_desktop_id()`,
  `move_window_to_desktop(hwnd, desktop_id)`, `ensure_on_current_desktop(hwnd)`.
* Full pre-removal source of EVERY touched file is in the backup zip
  `D:\Dev\ScripTree-backups\scriptree-src-a106-*.zip` (cut immediately before
  this removal) — `forest_visibility.py`, `cell_window.py`, `test_forest.py` etc.

## What was deleted from `scriptree/shell/forest_visibility.py`

The whole feature hung off `_FocusWatcher` (focus-change → move hub to the
user's current desktop) plus show-time corrective moves. Removed:

1. **`_FocusWatcher` follow plumbing** — the `on_focus_changed_for_follow`
   ctor param + `self._on_focus_changed_for_follow`; the `_follow_debounce`
   `QTimer(120ms)` and its `timeout→_fire_follow`; the `if
   self._on_focus_changed_for_follow is not None: self._follow_debounce.start()`
   line in `_on_focus_changed`; and the `_fire_follow` method. **Kept** the
   hide-only watcher (`_debounce`/`_fire`/`_is_inside_forest`/`suppress_for`).

2. **Manager wiring** — `ForestVisibilityManager.__init__` passed
   `on_focus_changed_for_follow=self._follow_user_across_desktops` into
   `_FocusWatcher(...)`. That kwarg was dropped.

3. **`show_hub` desktop moves** — resolving `desktop_id` on entry; the
   taskbar-mode pre-show `move_window_to_desktop` (while minimised); the
   corrective post-show move; the tray-mode show-then-move; and the
   descendant post-show move loop. **Kept** the structure: suppress watcher →
   `showNormal()`/`show()` → clamp last position on-screen (`_clamp_hub`) →
   show descendants → `_rescue_cells_on_screen(...)` → raise/activate.

4. **`_restore_descendants` desktop move** — the `if shown:` block that moved
   each freshly-shown descendant to the current desktop. **Kept** the
   `cell.show()` loop + `_rescue_cells_on_screen(shown)`.

5. **Three methods deleted whole** — `_ensure_hub_on_current_desktop`
   (was dead — no callers), `_ensure_descendants_on_current_desktop` (dead,
   pre-a61), and `_follow_user_across_desktops` (the core follow, called by the
   debounced `_fire_follow`). The a70 drag-guard
   (`if getattr(self._forest_window, "_drag_started", False): return`) lived
   here — **if you re-add follow, keep a "never move during drag" rule.**

### The core follow method (deleted) — for reference

```python
def _follow_user_across_desktops(self) -> None:
    # Called (debounced ~120ms) on focusWindowChanged, regardless of auto-hide.
    from scriptree.shell import win_virtual_desktops as wvd
    if not wvd.is_supported():
        return
    if self._forest_window is None:
        return
    # Don't force native-window creation on an un-shown widget.
    if not self._forest_window.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
        return
    # a70: never move across desktops mid-drag (the #1 "hub disappeared" cause).
    if getattr(self._forest_window, "_drag_started", False):
        return
    hwnd = int(self._forest_window.winId())
    if wvd.is_window_on_current_desktop(hwnd):
        return
    desktop_id = wvd.get_current_desktop_id()
    if desktop_id is None:
        return
    wvd.move_window_to_desktop(hwnd, desktop_id)
    for descendant in self._forest_descendants():
        try:
            if descendant.isVisible():
                wvd.move_window_to_desktop(int(descendant.winId()), desktop_id)
        except Exception:
            continue
```

## Hard-won lessons (carry into any re-implementation)

* `MoveWindowToDesktop` returns `TYPE_E_ELEMENTNOTFOUND (0x8002802B)` for a
  **hidden** window but works on a **minimised** one. So move-before-show works
  in taskbar mode (minimise → move → `showNormal`) but tray mode must show first
  then move (brief flash). This timing dance was a big source of fragility.
* Raw `MoveWindowToDesktop` on **every** `focusWindowChanged` fired bursts of
  racy COM calls during focus churn (drag, alt-tab) and stranded the hub —
  hence the a70 120ms debounce + the drag guard. A future approach should avoid
  per-focus-event moves entirely.
* The feature was independent of auto-hide (the user wanted the forest reachable
  on every desktop regardless), which is why it lived in the always-on focus
  watcher rather than the hide path.

## Also removed elsewhere (a107)

* `scriptree/shell/win_virtual_desktops.py` — deleted.
* `tests/test_forest.py` — `TestRestoreDescendantsDesktopOrder`,
  `TestVirtualDesktopFollowGuards`.
* Doc/comment + env-var references (`SCRIPTREE_VDM_DEBUG`,
  `[win_virtual_desktops:debug]`) in `debug_logging.py`, `forest_controller.py`,
  `run_scriptreering.py`.
