# pyside6 — index

Qt6 / PySide6 quirks, Windows process-spawn gotchas, and pytest/PowerShell
subprocess oddities encountered while building V3.

- [pyside6] **no_console_popen_kwargs**: Windows-only flag set
  (`CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`) that prevents a
  console window from popping up when a GUI app spawns CLI tools.
  Helper at `scriptree.core.runner.no_console_popen_kwargs()` — merge
  into every Popen/run call site cross-platform.  Lists the audit
  of every site + exempt cases. → `rags/lessons/no_console_popen_kwargs.md`
- [pyside6] **detached_process_breaks_bat**: DETACHED_PROCESS strips the
  console; cmd.exe needs one for `start "" pythonw.exe`. Use
  CREATE_NO_WINDOW. → `rags/lessons/detached_process_breaks_bat.md`
- [pyside6] **qt_drag_drop_needs_subclass**: monkey-patching
  `dropEvent` doesn't reach Qt's vtable; must subclass and override
  on the class. → `rags/lessons/qt_drag_drop_needs_subclass.md`
- [pyside6] **synthetic_qdropevent_loses_mimedata**: a Python-built
  `QDropEvent` round-trips a base `QObject` instead of `QMimeData` —
  factor drop logic into a helper that takes a `QMimeData` directly
  and test the helper. → `rags/lessons/synthetic_qdropevent_loses_mimedata.md`
- [pyside6] **qmenu_outside_click_redispatches**: `QMenu.exec` forwards
  the dismissing click to the widget under the cursor; record an
  `aboutToHide` timestamp and suppress re-open in the cell's click
  handler. → `rags/lessons/qmenu_outside_click_redispatches.md`
- [pyside6] **powershell_utf8_encoding_writes_bom**: PS 5.1's
  `Set-Content -Encoding utf8` writes a BOM; use
  `[System.IO.File]::WriteAllText` with `UTF8Encoding($false)`.
  → `rags/lessons/powershell_utf8_encoding_writes_bom.md`
- [pyside6] **powershell_background_buffers_stdout**: `$out = python …`
  in a backgrounded PS task buffers everything until exit; pipe through
  `Tee-Object -FilePath` instead. →
  `rags/lessons/powershell_background_buffers_stdout.md`
- [pyside6] **pytest_progress_dots_stall**: a stalled progress line
  isn't a hang — pytest's summary flushes late through pipes. Check
  the actual exit code before killing.
  → `rags/lessons/pytest_progress_dots_stall.md`
- [pyside6] **qmainwindow_as_child_widget**: a `QDockWidget` only
  works under a `QMainWindow` ancestor; embed an internal
  `QMainWindow` inside a `QWidget` to host real dockable panels.
  → `rags/lessons/qmainwindow_as_child_widget.md`
- [pyside6] **hover_tooltip_screen_clamp**: hover tooltips need
  cell-rect anchor + multi-monitor `screenAt` clamp + flip-above
  when off-bottom; fixed `(+12, +18)` offset goes off-screen on
  edges. → `rags/lessons/hover_tooltip_screen_clamp.md`
- [pyside6] **qt_screen_change_signal_debounce**: Qt emits a storm
  of `screenAdded`/`screenRemoved`/`primaryScreenChanged`/per-screen
  `geometryChanged`/`availableGeometryChanged` on monitor topology
  change; debounce via a 200 ms single-shot QTimer stored on the
  QApplication. Hook new screens' per-screen signals in the
  `screenAdded` closure too. →
  `rags/lessons/qt_screen_change_signal_debounce.md`
- [pyside6] **qmenu_per_action_right_click**: `QMenu` does NOT fire
  `customContextMenuRequested` on actions. Use a QObject event
  filter on EVERY QMenu in the tree (recursive + `aboutToShow` re-
  walk + idempotency sentinel) watching `QEvent.ContextMenu` and
  right-click `MouseButtonPress`. Stash per-action data as a Python
  attribute on the QAction, not via `setData`. →
  `rags/lessons/qmenu_per_action_right_click.md`
- [pyside6] **qtads_toggleview_off_on_cycles_floating_dock**:
  `QtAds.CDockWidget.toggleView(True)` is NOT idempotent against an
  already-visible FLOATING dock — it re-shows the floating frame,
  reading as a "new popup" to the user. Short-circuit reinstall
  cycles and guard `toggleView(True)` behind `isVisible()`.
  → `rags/lessons/qtads_toggleview_off_on_cycles_floating_dock.md`
- [pyside6] **qtads_setwidget_cycles_floating_dock**:
  `QtAds.CDockWidget.setWidget(new_widget)` on a CURRENTLY-FLOATING
  dock also re-triggers the show-floating-frame path — independent
  of the toggleView antipattern above. Fix: wrap a permanent host
  `QWidget`+`QVBoxLayout` into the dock once, then reparent
  runner-owned panels in/out of the host's layout. The dock's widget
  never changes → no re-show. Hit on every per-tool content swap in
  v0.8.0a39/a40; fixed in a41.
  → `rags/lessons/qtads_setwidget_cycles_floating_dock.md`
- [pyside6] **qmenu_freeze_under_floating_dialog**: a QMenu
  CANNOT be "frozen visible" under a sibling dialog -- Qt's
  popup-grab on the menu intercepts every mouse press in the app
  (the dialog's clicks included) and an app-level event filter
  that swallows mouse events on QMenu instances breaks the dialog
  too. The popup grab is non-negotiable. Solution (a44):
  **screenshot overlay**. Before closing the real menu, grab a
  ``QPixmap`` of every visible menu in the popup chain (walk up
  to root, then back down for open submenus); close the real
  menus; show each pixmap as a frameless, mouse-transparent,
  always-on-top ``QLabel`` at the original position. The user
  sees the menu chain still there; the grab is released so the
  dialog clicks land. Tag close reason ("x" / "action" /
  "outside") via a dialog attribute set by each handler so
  ``finished`` can decide: X => reopen real menu, otherwise
  destroy overlays and don't reopen. Window flags that matter:
  ``WindowTransparentForInput`` + ``WA_TransparentForMouseEvents``
  + ``WA_ShowWithoutActivating``.
  → `rags/lessons/qmenu_freeze_under_floating_dialog.md`
- [pyside6] **qheaderview_right_click_separate_signal**:
  `QTreeWidget.customContextMenuRequested` fires from the viewport,
  NOT from `QHeaderView`. Wire `header().setContextMenuPolicy` +
  `header().customContextMenuRequested.connect(...)` separately,
  sharing the body's menu-builder with `item=None`. mapToGlobal
  goes through `header()`.
  → `rags/lessons/qheaderview_right_click_separate_signal.md`
