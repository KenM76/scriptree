# v3-process — index

How V3 actually got built: backup discipline, sweep-replace
pattern, V2 stale-import hunting, beta reports, and the
diagnostics conventions.

- [v3-process] **backup_first_discipline**: timestamped
  `Compress-Archive` to OneDrive before any risky multi-file
  mutation. → `rags/lessons/backup_first_discipline.md`
- [v3-process] **auto_dismiss_qmessagebox_in_tests**: replace
  `QMessageBox.{warning,information,critical,question}` with
  auto-OK lambdas at test module load; tests must not block
  on dialogs. → `rags/lessons/auto_dismiss_qmessagebox_in_tests.md`
- [v3-process] **sweep_replace_pattern_for_renames**: `git mv`
  for files (preserves history), then PS regex sweep with
  `[System.IO.File]::WriteAllText` + `UTF8Encoding($false)`
  to avoid BOMs.
  → `rags/lessons/sweep_replace_pattern_for_renames.md`
- [v3-process] **v2_stale_import_pattern**: V2's
  `try: from apps.shell.X; except: pass` blocks silently
  swallow import failures after the V3 rename — fix the
  import AND replace the bare except with a logged narrow
  catch. → `rags/lessons/v2_stale_import_pattern.md`
- [v3-process] **beta_style_report_per_session**: write
  `docs/beta-reports/YYYY-MM-DD__claude__<slug>.md` after
  every multi-fix session, with verbatim user quote and
  `file:line` references.
  → `rags/lessons/beta_style_report_per_session.md`
- [v3-process] **diagnostics_tagged_stderr_logs**: every
  subsystem emits `[Tag] message` to stderr via a local
  `_log()` helper; lets a single-tag `findstr` isolate one
  subsystem's activity.
  → `rags/lessons/diagnostics_tagged_stderr_logs.md`
