# ScripTree V3 — RAG master index

Project-local lessons learned across V3's v0.2.0 → v0.2.7 build
cycle.  Topic dirs (`pyside6/`, `v3-architecture/`, `v3-process/`)
each have their own index; this file is the flat cross-topic list.

Tag in `[brackets]` is the topic — `grep '[pyside6]' index.md` etc.
gives the per-topic slice.

## All lessons

- [pyside6] **detached_process_breaks_bat**: DETACHED_PROCESS strips
  the console; cmd.exe needs one for `start "" pythonw.exe`. Use
  CREATE_NO_WINDOW. → `rags/lessons/detached_process_breaks_bat.md`
- [pyside6] **qt_drag_drop_needs_subclass**: monkey-patching
  `dropEvent` doesn't reach Qt's vtable; subclass and override on
  the class. → `rags/lessons/qt_drag_drop_needs_subclass.md`
- [pyside6] **synthetic_qdropevent_loses_mimedata**: synthetic
  `QDropEvent`s round-trip a base `QObject`, not a `QMimeData` —
  factor drop logic into helpers and test those.
  → `rags/lessons/synthetic_qdropevent_loses_mimedata.md`
- [pyside6] **qmenu_outside_click_redispatches**: `QMenu.exec`
  forwards the dismissing click; record `aboutToHide` timestamp and
  suppress cell re-open within 250 ms.
  → `rags/lessons/qmenu_outside_click_redispatches.md`
- [pyside6] **powershell_utf8_encoding_writes_bom**: `-Encoding utf8`
  in PS 5.1 writes a BOM; use `WriteAllText` + `UTF8Encoding($false)`.
  → `rags/lessons/powershell_utf8_encoding_writes_bom.md`
- [pyside6] **powershell_background_buffers_stdout**:
  `$out = python …` in a PS background task buffers until process
  exit; pipe through `Tee-Object -FilePath` to stream live.
  → `rags/lessons/powershell_background_buffers_stdout.md`
- [pyside6] **pytest_progress_dots_stall**: a stalled progress %
  isn't a hang — the summary flushes late through pipes; check
  exit code before killing.
  → `rags/lessons/pytest_progress_dots_stall.md`
- [v3-architecture] **v1_cli_needs_standalone_flag**: V1 opens
  the full editor for a `.scriptree` path by default; cell
  launches must pass `-standalone`.
  → `rags/lessons/v1_cli_needs_standalone_flag.md`
- [v3-architecture] **cell_members_dict_not_list**:
  `CellWindow._members` is `dict[member_id, QPoint]` — iterate keys
  and resolve via `CellRegistry`.
  → `rags/lessons/cell_members_dict_not_list.md`
- [v3-architecture] **single_instance_handoff_qlocalserver**:
  per-user `QLocalServer` pipe; `--new-process` opts out of both
  halves; env override for tests.
  → `rags/lessons/single_instance_handoff_qlocalserver.md`
- [v3-architecture] **master_cells_no_catalog_path**: masters have
  no catalog of their own; route double-right through
  `show_composite_for`, not `show_tree_for`.
  → `rags/lessons/master_cells_no_catalog_path.md`
- [v3-architecture] **cell_metadata_in_catalog_json**: v0.2.7
  promoted icon/label/scale/opacity to a `cell` sub-object in the
  catalog JSON; defaults omitted to keep legacy files byte-identical.
  → `rags/lessons/cell_metadata_in_catalog_json.md`
- [v3-architecture] **icon_path_relative_normalization**:
  forward-slash relative path when icon is under catalog dir,
  absolute otherwise.
  → `rags/lessons/icon_path_relative_normalization.md`
- [v3-architecture] **embed_unembed_icon_roundtrip**: `embed_icon`
  base64-encodes and clears the path; `unembed_icon_to_file` does
  the reverse, restoring a relative path.
  → `rags/lessons/embed_unembed_icon_roundtrip.md`
- [v3-architecture] **camelcase_precedence_in_label**: CamelCase
  wins over multi-word first-letter derivation: "SolidWorks toolkit"
  → "SW", not "St". → `rags/lessons/camelcase_precedence_in_label.md`
- [v3-architecture] **wordskip_list_for_abbreviations**: skip
  `{a, an, and, or, the, of, to, in, on, for, at, by, as, is, if}`
  case-insensitively when deriving multi-word labels.
  → `rags/lessons/wordskip_list_for_abbreviations.md`
- [v3-process] **backup_first_discipline**: timestamped
  `Compress-Archive` to OneDrive before every risky multi-file
  mutation. → `rags/lessons/backup_first_discipline.md`
- [v3-process] **auto_dismiss_qmessagebox_in_tests**: replace
  `QMessageBox.{warning,information,critical,question}` with auto-OK
  lambdas at test module load.
  → `rags/lessons/auto_dismiss_qmessagebox_in_tests.md`
- [v3-process] **sweep_replace_pattern_for_renames**: `git mv` for
  files, then PS regex sweep using `WriteAllText` +
  `UTF8Encoding($false)` to avoid BOMs.
  → `rags/lessons/sweep_replace_pattern_for_renames.md`
- [v3-process] **v2_stale_import_pattern**: V2's `try/import/bare-
  except: pass` blocks silently swallow renamed-module failures —
  fix the import AND replace the bare except with a logged narrow
  catch. → `rags/lessons/v2_stale_import_pattern.md`
- [v3-process] **beta_style_report_per_session**: write
  `docs/beta-reports/YYYY-MM-DD__claude__<slug>.md` after every
  multi-fix session, with verbatim user quote and `file:line` refs.
  → `rags/lessons/beta_style_report_per_session.md`
- [v3-process] **diagnostics_tagged_stderr_logs**: every subsystem
  emits `[Tag] message` to stderr via a local `_log()` helper.
  → `rags/lessons/diagnostics_tagged_stderr_logs.md`
- [pyside6] **qmainwindow_as_child_widget**: a `QDockWidget` only
  works under a `QMainWindow` ancestor; embed an internal
  `QMainWindow` inside a `QWidget` to host real dockable panels.
  → `rags/lessons/qmainwindow_as_child_widget.md`
- [v3-architecture] **explode_tree_via_temp_ring**: turn a
  `.scriptreetree` into a multi-cell ring by writing a synthetic
  `.scriptreering` to `%TEMP%` and handing it to the cell shell;
  no new imperative API needed.
  → `rags/lessons/explode_tree_via_temp_ring.md`
- [v3-architecture] **save_as_rebinds_path**: Save-As must re-bind
  `self._tree_file` (and refresh `_tree_read_only`) *before*
  delegating to the existing save method.
  → `rags/lessons/save_as_rebinds_path.md`
- [v3-architecture] **group_uniform_size_and_repack**: cells in a
  master group share `size_px` / `shape` / `orientation`; settings
  broadcast through `_apply_group_geometry` and a pure-logic
  `group_layout.repack` keeps members edge-touching, non-overlapping,
  and on-screen.  → `rags/lessons/group_uniform_size_and_repack.md`
- [v3-architecture] **close_member_uses_membership_not_source_id**:
  master.source_a_id / source_b_id are frozen identity fields, not
  the current cluster — `_close_this` must use `_members` and let
  `_check_master_validity` enforce the quorum rule.
  → `rags/lessons/close_member_uses_membership_not_source_id.md`
- [v3-architecture] **interactive_stdin_with_two_layer_gate**: v0.3.0
  interactive-stdin runner mode requires BOTH `ToolDef.interactive`
  AND the `interactive_stdin` permission file (default-deny) to
  surface the send-line widget.  Tool author × admin opt-in.
  → `rags/lessons/interactive_stdin_with_two_layer_gate.md`
- [v3-architecture] **ring_dirty_membership_only**: ring close-
  prompt fires iff `_ring_dirty` OR `_saved_ring_path is None`;
  flip the bit only at membership-change sites, never at position-
  only sites.  Reset on save / load.
  → `rags/lessons/ring_dirty_membership_only.md`
