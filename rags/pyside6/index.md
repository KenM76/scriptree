# pyside6 — index

Qt6 / PySide6 quirks, Windows process-spawn gotchas, and pytest/PowerShell
subprocess oddities encountered while building V3.

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
