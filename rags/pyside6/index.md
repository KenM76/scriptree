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
