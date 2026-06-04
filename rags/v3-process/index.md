# v3-process — index

How V3 actually got built: backup discipline, sweep-replace
pattern, V2 stale-import hunting, beta reports, and the
diagnostics conventions.

- [v3-process] **version_lives_in_two_files**: the About dialog
  reads `scriptree/__init__.py::__version__`, NOT `pyproject.toml`.
  Three releases shipped with stale About-dialog version because
  only pyproject was bumped. Bump BOTH in every release commit.
  → `rags/lessons/version_lives_in_two_files.md`
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
- [v3-process] **combridge_bundle_workflow**: separate
  `KenM76/combridge` repo builds CLI + `plugins/<Name>/` subdirs
  via per-plugin `CopyToPluginsRoot AfterTargets="Build"`; stage
  side-by-side then `lib/install_combridge.ps1 -LocalSource`.
  Verify-Install's flat `Get-ChildItem` is a known false-negative
  warning. `make_portable.py --bundle-combridge` chains it.
  → `rags/lessons/combridge_bundle_workflow.md`
- [v3-process] **make_portable_non_interactive**: PowerShell
  `Start-Process` / non-TTY runners need `--scriptreeapps
  {keep|overwrite|backup}` explicitly or the script hangs on the
  ScripTreeApps disposition prompt. Release recipe:
  `--force --no-smoke-test --zip --scriptreeapps overwrite`.
  → `rags/lessons/make_portable_non_interactive.md`
- [v3-process] **dropbox_slows_python_on_subst**: Python startup
  from `R:\` (subst into `D:\Stanley Dropbox\Resource`) takes 40+
  seconds with Dropbox running, ~70 ms with it killed (~600×
  difference). Kill Dropbox before release builds and any
  unattended R:\ work.
  → `rags/lessons/dropbox_slows_python_on_subst.md`
- [v3-process] **general-purpose__docs_lag_code_after_schema_v3_rename**:
  schema v3 rename and capability-file expansion (v0.5.0+) propagated
  through code but not through user-facing docs — copy audit found
  23 findings (11 P0, 9 P1, 3 P2). Schema-bump PR checklist must
  grep `docs/` for old widget names (`file_open`/`file_save`/
  `enum_radio`) and `schema_version.*[12]`. Capability count should
  live in ONE place (security.md table); README/features.md link
  in. See `docs/COPY_AUDIT_2026-05-31.md`.
  → `rags/lessons/general-purpose__docs_lag_code_after_schema_v3_rename.md`
- [v3-process] **controller_api_cell_or_path**: when a controller
  handler gains a second call-site that hands it a path instead of
  a `CellWindow`, branch the existing method on `isinstance(target,
  (str, Path))` rather than forking a sibling method. New
  call-sites (CLI, programmatic, future right-click features) pick
  up the action automatically. Different shape from the
  "two-publics-share-a-helper" pattern — use it when pre-conditions
  are identical and only the input shape varies.
  → `rags/lessons/controller_api_cell_or_path.md`
- [v3-process] **vocabulary_disambiguation_before_editing**:
  "editor" / "tree" / "popup" are 3-way ambiguous in ScripTree
  (MainWindow vs ToolEditorView vs StandaloneWindow;
  TreeLauncherView vs `.scriptreetree` file vs merged tree).
  v0.8.0a35→a38 regression: lead engineer guessed wrong surface
  and had to revert. Ask before editing; consult
  `docs/LLM/glossary.md`; quote the referent back to confirm.
  → `rags/lessons/vocabulary_disambiguation_before_editing.md`
