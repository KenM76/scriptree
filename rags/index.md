# ScripTree V3 — RAG master index

Project-local lessons learned across V3's v0.2.0 → v0.2.7 build
cycle.  Topic dirs (`pyside6/`, `v3-architecture/`, `v3-process/`)
each have their own index; this file is the flat cross-topic list.

Tag in `[brackets]` is the topic — `grep '[pyside6]' index.md` etc.
gives the per-topic slice.

## All lessons

- [v3-architecture] **auto_organise_doubles_path_segment**: the
  category auto-organise generator writes leaf paths with a
  doubled `ScripTree/Apps/` segment because it computes relatives
  from the wrong base.  Tools missing from
  `_groups/<X>__auto.scriptreetree` catalogs.
  → `rags/lessons/auto_organise_doubles_path_segment.md`
- [pyside6] **no_console_popen_kwargs**: Windows-only flag set
  (`CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`) that prevents a
  console window from popping up when a GUI app spawns CLI tools.
  Helper at `scriptree.core.runner.no_console_popen_kwargs()` —
  merge into every Popen/run call site cross-platform.
  → `rags/lessons/no_console_popen_kwargs.md`
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
- [v3-process] **version_lives_in_two_files**: About dialog reads
  `scriptree/__init__.py::__version__`, NOT `pyproject.toml`.
  Three releases shipped with stale About-dialog version because
  only pyproject was bumped. Bump BOTH in every release commit.
  → `rags/lessons/version_lives_in_two_files.md`
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
- [v3-architecture] **tree_path_prepend_run_time_wiring**: v0.3.2
  closed a dead-code gap on `TreeDef.path_prepend` with a
  five-step kwarg-thread (build_env → build_full_argv → launcher →
  runner setter → main-window glue).  Tree slots between local
  (tool+cfg) and global; setter pattern needed because runners
  are cached across tree-load events.
  → `rags/lessons/tree_path_prepend_run_time_wiring.md`
- [v3-architecture] **capability_wiring_full_audit**: v0.3.3 wired
  every previously-unconsulted capability via a helper module
  (apply_widget_perm / apply_action_perm / apply_text_readonly /
  perm_check); +25 tests; 35/35 wired.  Path-security trio plumbed
  through sanitize_all_values + validate_resolved_path.
  → `rags/lessons/capability_wiring_full_audit.md`
- [v3-architecture] **sanitization_warning_suppression**: v0.3.4
  added three "Don't warn me again" checkboxes to the injection
  popup (per-field / per-tool / global), gated by one new
  `suppress_sanitization_warnings` capability.  QSettings storage
  + Edit ▸ Sanitization warnings... re-enable dialog.
  → `rags/lessons/sanitization_warning_suppression.md`
- [v3-architecture] **cell_click_to_run**: v0.3.5 made cells
  configurable as single-click run buttons.  Two new catalog
  fields (`cell.click_action` / `cell.click_run_mode`), new
  `cell_click_to_run` capability, V1 `-run` flag for auto-click,
  Popen-polling sequencer for tree sequential mode.
  → `rags/lessons/cell_click_to_run.md`
- [v3-architecture] **cell_fill_color_picker**: v0.3.6 added
  per-cell colour override with synced hex / R-G-B / hue rainbow
  controls in the Settings dialog.  Alpha preserved across
  changes; hue slider always full S/V.
  → `rags/lessons/cell_fill_color_picker.md`
- [v3-architecture] **link_dock_graph_split**: v0.8.0 split the
  conflated `_group_master_id` into `_link_parent_id` (group
  membership: forest→rings→cells) and `_dock_partner_id` /
  `_dock_edge` / `_dock_children_by_edge` (spatial adjacency).
  Invariants L1-L5 in `link_dock_audit.py`. Cells always linked
  to forest-or-ring. → `rags/lessons/link_dock_graph_split.md`
- [v3-architecture] **repack_animation_race_dock_position**:
  `_repack_members` animates async (260 ms); calling
  `_set_cell_dock` immediately after reads stale geometry. Pass
  `child_centre=` from the post-repack target.
  → `rags/lessons/repack_animation_race_dock_position.md`
- [v3-architecture] **forest_never_prompts_save**: forest excluded
  from `_ring_needs_save_prompt`; `_close_all_related` pre-walks
  nested rings once to stop double save prompts.
  → `rags/lessons/forest_never_prompts_save.md`
- [v3-architecture] **move_to_cascades_dock_children**:
  `CellWindow.move_to` recursively cascades delta to dock children
  with re-entry guard `_GROUP_MOVE_IN_PROGRESS`. Used by
  snap-commit and `dock_with`.
  → `rags/lessons/move_to_cascades_dock_children.md`
- [v3-architecture] **per_member_relocation_vs_rigid_settle**: for
  docked rings, use new
  `_relocate_overlapping_members_individually` (`cell_window.py:8728`)
  instead of `_settle_no_overlap` — keeps master at the snap slot,
  re-slots only overlapping members.
  → `rags/lessons/per_member_relocation_vs_rigid_settle.md`
- [v3-architecture] **fresh_ring_not_in_forest_positioned**: fresh
  ring spawn must NOT add itself to `forest._positioned` or
  `forest._dock_partners`; link-parent + `_members` entry only.
  Otherwise forest-drag drags the unattached ring.
  → `rags/lessons/fresh_ring_not_in_forest_positioned.md`
- [v3-architecture] **recursive_merged_menu_population**:
  `tree_popup` master path recurses into members (depth-capped at
  8); masters become sub-menus titled via `_popup_header_text`.
  Don't drop non-catalog members — they're rings.
  → `rags/lessons/recursive_merged_menu_population.md`
- [v3-architecture] **ring_auto_name_session_serial**: rings get
  auto-name via `_RING_SERIAL` (`cell_window.py:2677`);
  `_popup_header_text` fall-through `_catalog_path` →
  `_text_label` → `_auto_ring_name` (forest excluded). Loaded
  rings name from filename.
  → `rags/lessons/ring_auto_name_session_serial.md`
- [v3-architecture] **ring_cascade_gated_on_positioned**: ring
  drag uses `_positioned ∩ _members`, not raw link membership —
  matches forest's existing behaviour, lets a dragged-off cell
  stay put on subsequent ring drags.
  → `rags/lessons/ring_cascade_gated_on_positioned.md`
- [v3-architecture] **shake_to_close_ring_prompt**:
  `_close_ring_via_shake_with_prompt` (`cell_window.py:7745`)
  fires Save/Discard/Cancel and re-links members to forest on
  disband. Forest excluded from shake detection.
  → `rags/lessons/shake_to_close_ring_prompt.md`
- [v3-architecture] **snap_engine_wire_on_fresh_master**:
  `_try_spawn_master` must call
  `ring_main._wire_hex_to_snap(master)` after `master.show()` —
  otherwise snap preview never renders on freshly-spawned masters.
  → `rags/lessons/snap_engine_wire_on_fresh_master.md`
- [pyside6] **hover_tooltip_screen_clamp**: cell-rect anchor +
  multi-monitor `screenAt` clamp + flip-above on off-bottom; fixed
  `(+12, +18)` offset goes off-screen on edges.
  → `rags/lessons/hover_tooltip_screen_clamp.md`
- [v3-process] **combridge_bundle_workflow**: stage combridge
  CLI + plugin subdirs side-by-side then
  `lib/install_combridge.ps1 -LocalSource`. Verify-Install's flat
  `Get-ChildItem` is a known false-negative warning.
  `make_portable.py --bundle-combridge` chains it.
  → `rags/lessons/combridge_bundle_workflow.md`
- [v3-process] **make_portable_non_interactive**: non-TTY runners
  need `--scriptreeapps {keep|overwrite|backup}` explicitly or
  the script hangs on the disposition prompt. Release recipe:
  `--force --no-smoke-test --zip --scriptreeapps overwrite`.
  → `rags/lessons/make_portable_non_interactive.md`
- [v3-process] **dropbox_slows_python_on_subst**: Python startup
  from `R:\` (subst into a Dropbox-synced folder) takes 40+ s with
  Dropbox running, ~70 ms killed. Kill Dropbox before any release
  build or unattended R:\ work.
  → `rags/lessons/dropbox_slows_python_on_subst.md`
- [v3-process] **general-purpose__docs_lag_code_after_schema_v3_rename**:
  schema v3 rename + capability-file expansion propagated through
  code but not docs (v0.5.0+); 23-finding copy audit. Schema-bump
  PR checklist: grep `docs/` for `file_open`/`file_save`/
  `enum_radio`/`schema_version.*[12]`. Capability count lives in
  security.md table only.
  → `rags/lessons/general-purpose__docs_lag_code_after_schema_v3_rename.md`
- [pyside6] **qt_screen_change_signal_debounce**: 200 ms single-shot
  QTimer on `app._screen_rescue_timer` debounces Qt's `screenAdded`/
  `screenRemoved`/`primaryScreenChanged`/per-screen `geometryChanged`/
  `availableGeometryChanged` storm; new screens get their per-screen
  signals hooked in the `screenAdded` closure.
  → `rags/lessons/qt_screen_change_signal_debounce.md`
- [pyside6] **qmenu_per_action_right_click**: `QMenu` has no
  `customContextMenuRequested` for actions; install a recursive
  event filter (per menu, sentinel-guarded, `aboutToShow` re-walk)
  watching `QEvent.ContextMenu` + right-`MouseButtonPress`. Stash
  per-action data as a Python attribute on the QAction.
  → `rags/lessons/qmenu_per_action_right_click.md`
- [v3-architecture] **personal_sidecar_two_prong_match**:
  `find_personal_configs_for_app` matches on BOTH `source_filename`
  (basename present under app_dir) AND a `source_locations` entry
  under app_dir. Filename-only would cross-contaminate two installs
  of the same-named tool. Stdlib-only.
  → `rags/lessons/personal_sidecar_two_prong_match.md`
- [v3-architecture] **uninstall_keep_remove_flags_with_backup**:
  `uninstall_app(path, *, remove_local_configs=True,
  remove_shared_configs=True)`. "Keep shared" path COPIES sidecars
  to `<app>_uninstalled_configs/` (numbered on collision) BEFORE
  `shutil.rmtree`; refuses the uninstall if the copy fails. Dialog
  shows live counts; uses `DestructiveRole`.
  → `rags/lessons/uninstall_keep_remove_flags_with_backup.md`
- [v3-architecture] **popup_menu_root_catalog_path**: `tree_popup`
  threads `source_dir` (resolution) AND `root_catalog` (the catalog
  file the menu was built from) through node construction; every
  leaf in a `.scriptreetree` stamps `root_catalog_path` = the tree
  file itself, not the per-leaf catalog.
  → `rags/lessons/popup_menu_root_catalog_path.md`
- [v3-process] **controller_api_cell_or_path**: controller handlers
  that gain a path-based call-site should branch on
  `isinstance(target, (str, Path))` rather than fork a sibling
  method. Use when pre-conditions are identical and only input
  shape varies; new call-sites get the action for free.
  → `rags/lessons/controller_api_cell_or_path.md`
- [v3-architecture] **merged_tree_pushback_to_origins**: v0.8.0a31
  sidecar `<merged>.scriptreetree.origins.json` + `push_back_to_origins`
  walk the saved merged tree and write each top-level folder back
  to its origin; absolute→relative leaf paths; `.scriptree` sources
  skipped cleanly.
  → `rags/lessons/merged_tree_pushback_to_origins.md`
- [v3-architecture] **editor_uninstall_persists_to_forest_file**:
  editor and forest are separate processes; uninstall/drop must
  write to `.scriptreeforest` via
  `MainWindow._persist_uninstall_to_forest_file` to survive forest
  relaunch.
  → `rags/lessons/editor_uninstall_persists_to_forest_file.md`
- [v3-architecture] **merged_tree_dropped_origins_vs_skipped**:
  `PushBackResult` has four categories — written / skipped /
  errors / dropped_origins. Dropped origins = user removed a
  top-level folder; forest excludes the source but source file
  stays on disk.
  → `rags/lessons/merged_tree_dropped_origins_vs_skipped.md`
- [v3-architecture] **merged_tree_inline_subtrees_at_build_time**:
  inline subtree refs at MERGE BUILD TIME so the merged tree owns
  the nodes outright (drag/delete works); cycle guard emits
  "(circular reference)" placeholder. Trade-off: refs are static.
  → `rags/lessons/merged_tree_inline_subtrees_at_build_time.md`
- [v3-architecture] **merged_tree_dedup_by_name_with_disambiguation**:
  two `.scriptreetree` files with the same internal name → append
  parent-dir in parens (`"MSOffice (a_apps)"`), fall back to
  numeric counter. Sidecar keys by disambiguated name so output
  must be stable build-over-build.
  → `rags/lessons/merged_tree_dedup_by_name_with_disambiguation.md`
- [v3-architecture] **editor_forest_sync_via_forest_file**:
  `.scriptreeforest` is the ONLY IPC channel between editor
  subprocess and running forest. Every editor-side action affecting
  forest state MUST write through it. No live update — edit closed
  → forest reloaded.
  → `rags/lessons/editor_forest_sync_via_forest_file.md`
- [pyside6] **qtads_toggleview_off_on_cycles_floating_dock**:
  `CDockWidget.toggleView(True)` re-shows an already-visible
  FLOATING dock as a new popup. Short-circuit reinstall cycles;
  guard `toggleView(True)` behind `isVisible()`.
  → `rags/lessons/qtads_toggleview_off_on_cycles_floating_dock.md`
- [pyside6] **qheaderview_right_click_separate_signal**:
  `QTreeWidget.customContextMenuRequested` fires only from the
  viewport. Wire `header().customContextMenuRequested` separately
  (shared menu-builder, `item=None`); mapToGlobal via `header()`.
  → `rags/lessons/qheaderview_right_click_separate_signal.md`
- [v3-process] **vocabulary_disambiguation_before_editing**:
  "editor" / "tree" / "popup" are 3-way ambiguous; the a35→a38
  regression came from guessing wrong. Consult
  `docs/LLM/glossary.md`, quote the referent, ask before editing.
  → `rags/lessons/vocabulary_disambiguation_before_editing.md`
- [pyside6] **autohide_guard_own_modals**: `_FocusWatcher._fire`
  must return early when `activeModalWidget()` or `activePopupWidget()`
  is non-None — own dialogs/menus are mis-read as "focus left" by
  the parent-walk. Fix: guard before `_is_inside_forest` call.
  → `rags/lessons/autohide_guard_own_modals.md`
- [pyside6] **show_before_move_desktop_api**: `MoveWindowToDesktop`
  returns TYPE_E_ELEMENTNOTFOUND (0x8002802B) for HIDDEN windows.
  Show first, then move. Fix sibling reveal paths too (a59 fixed hub,
  a61 fixed _restore_descendants).
  → `rags/lessons/show_before_move_desktop_api.md`
- [pyside6] **qt_event_filter_never_raise**: `eventFilter` overrides
  must use `getattr(self, "_attr", default)` for every instance attr.
  Teardown can delete attrs before the last Qt event arrives.
  Symptom: "Error calling Python override of eventFilter" on exit.
  → `rags/lessons/qt_event_filter_never_raise.md`
- [v3-architecture] **rescue_cells_on_reveal**: every reveal path
  must call `_rescue_cells_on_screen(shown)` after `cell.show()`.
  Hidden cells don't track hub movement; stale positions can be off-
  screen. Mirrors `screen_watcher.rescue_all_cells` contract.
  → `rags/lessons/rescue_cells_on_reveal.md`
- [v3-architecture] **collapse_expand_route_through_layout_engine**:
  single-click collapse/expand (`_start_expand`) must re-bloom THROUGH
  the layout engine (`_compute_layout`) — a free, on-screen,
  non-overlapping honeycomb slot that forbids the hub centre — not
  replay a remembered coordinate (a67's offset still overlapped). a68.
  → `rags/lessons/collapse_expand_relative_offsets.md`
- [pyside6] **setwindowflags_hides_widget_and_drops_mask**:
  `setWindowFlags()` calls setParent -> HIDES the widget (so
  `isVisible()` is False AFTER it; capture it BEFORE) and recreates the
  Win11 HWND, dropping `setMask()` + `WA_TranslucentBackground`. Re-show
  on the pre-captured visibility, then re-assert mask/translucent bg.
  Cause of "the forest lost its icon and disappeared" after a
  visibility-mode toggle. a71.
  → `rags/lessons/setwindowflags_hides_and_drops_mask.md`
- [v3-architecture] **settle_rigid_slide_falls_back_to_engine_repack**:
  drag-end `_settle_no_overlap` is a RIGID block slide (can't re-arrange);
  at a corner where the cluster can't fit it gave up and left overlap.
  Fall back to `_compute_layout` (engine re-pack: plan all slots, then
  apply). a73.
  → `rags/lessons/settle_rigid_slide_vs_engine_repack.md`
- [v3-architecture] **full_fit_slot_selection_no_clamp**: slot
  selection must require the WHOLE cell on-screen (is_on_screen 1.0),
  not 50% -- a half-fit slot + the reveal's on-screen clamp shoved the
  cell into its neighbour at a corner. find_free_slot/nearest_free_slot
  default fraction_required=1.0; _start_expand uses engine slots
  verbatim (clamp only fallbacks). a74.
  → `rags/lessons/full_fit_slot_selection.md`
- [v3-architecture] **group_layout_pinned_to_tiling_not_delegated**:
  group_layout still has its own slot tables; its outer-ring ORDER
  differs from tiling's and repack depends on it, so it's PINNED to
  tiling by tests/test_geometry_consistency.py (set equality per ring)
  rather than delegated. Hex matches exactly; square uses a different
  size convention (xfail-tracked). a76.
  → `rags/lessons/group_layout_pinned_to_tiling.md`
- [v3-process] **portable_zip_bundles_solidworks_interop_strip_before_public**:
  make_portable.py bundles combridge's SolidWorks plugin folder, which
  carries SolidWorks's OWN SDK interop DLLs (SolidWorks.Interop.*.dll) --
  NOT git-tracked, so a `git ls-files` check misses them. Scan the BUILT
  release zip and strip the interop DLLs (keep ComBridge.Plugins.SolidWorks.dll)
  before `gh release create`. a75 release.
  → `rags/lessons/portable_zip_bundles_solidworks_interop.md`
- [v3-architecture] **fast_drag_left_behind_is_a_throttle_gap** (RESOLVED a79):
  fast-drag "cells gap / left behind" is NOT a _members divergence (that
  diagnosis was proven INERT — _members/_slot are dead-cache at drag-end;
  drag_targets keys off _positioned). Real cause: the 50ms wall-clock reflow
  throttle + Qt move-event coalescing + P4-disabled drag-end recompute leave a
  member FOLDED/stranded at an intermediate position with no final
  re-evaluation; _settle_no_overlap skips _auto_hidden so it can't rescue it.
  Fix: ONE un-throttled reflow at mouseReleaseEvent (clear _last_live_reflow_time;
  call _live_edge_reflow_or_fold) BEFORE settle. Corner-safe (ADDS, never
  removes, the load-bearing reflow; master never moves). a77's removal of the
  reflow was the WRONG fix (reverted a78). 3 regression tests in
  test_chaos_movement.py.
  → `rags/lessons/live_edge_reflow_races_rigid_drag.md`
- [v3-architecture] **remembered_cell_layout_feature** (a83, pending release):
  the forest hub remembers each cell's offset-from-hub as the user drops it
  (captured at user drag-end only, gated on was_dragging) and restores it on
  expand/startup/screen-rescue, engine-tiling only cells whose spot is
  off-screen. New CellWindow._remembered_offsets (keyed by _member_offset_key =
  normalised _catalog_path), _restore_remembered_offsets, _compute_layout(pinned=),
  ForestItem.rel_offset persistence, .scriptreelayout (layout_io) + Cell-layout
  Save/Load/Recent menu (reposition-existing-only). KEY GOTCHA: _start_expand's
  verbatim bloom branch must gate on `m._id in placed`, not `_slot is not None`,
  or a restored seam-straddling/secondary-monitor member (whose _slot is None
  post-load) gets single-screen-clamped off its spot (caught by adversarial
  verify). → `rags/lessons/remembered_cell_layout_a83.md`
- [v3-architecture] **forest_cluster_multidisplay_and_reflow_undock_fixes** (a80,
  pending release): three fixes for a multi-monitor user report. (A) the live reflow's
  relocation fired _check_undock OUTSIDE the _GROUP_MOVE_IN_PROGRESS guard and ejected a
  member from _positioned -> "left behind"; wrap the relocation loop in the guard.
  (B) _clamp_to_screen fell back to primaryScreen() when screenAt(raw_pos) was None
  (cursor above a 2nd monitor) -> forest teleported/oscillated between monitors; prefer
  current/nearest screen. (C) reflow + _check_edge_fold classified on/off-screen against
  ONE screen -> a cell visible on a 2nd monitor got relocated/auto-hidden; new
  _visible_area_on_any_screen (sum of per-screen overlaps) judges visibility across ALL
  monitors. Dock path traced CLEAN (not the cause of symptom 2). Live diagnosis via
  Win32_Process start-time vs deploy-time + the %APPDATA% debug log + saved
  .scriptreeforest. 4 regression tests in test_chaos_movement.py.
  → `rags/lessons/multidisplay_and_reflow_undock_fixes_a80.md`
- [v3-architecture] **known_issue_bloom_overlap_and_second_display_spill**:
  OPEN/deferred (a78) — shrink-then-bloom can overlap the forest icon or
  spill cells to a second display. In _start_expand/_compute_layout
  (multi-display screen pick via screenAt). Fix forward (do NOT revert a74).
  → `rags/lessons/known_issue_bloom_overlap_multidisplay.md`
- [v3-architecture] **forest_startup_hub_not_draggable**: hub not
  draggable at startup — tentative fix: `QTimer.singleShot(0,
  _finalize_hub_interactive)` to raise+activate after Qt maps the
  window. Not reproducible headless; `[forest_startup]` log tag
  captures next live-run data.
  → `rags/lessons/forest_startup_hub_not_draggable.md`
- [v3-architecture] **forest_controller_module_global_handle**:
  publish live `ForestController` as `ring_main._FOREST_CONTROLLER`
  so `_handle_primary_message` reveals the hub on second launch
  instead of spawning a stray cell.
  → `rags/lessons/forest_controller_module_global_handle.md`
- [v3-architecture] **single_instance_ack_semantics**: ack = "delivered",
  not "succeeded". Always ok=true. Surface failures via deferred
  `QTimer.singleShot(0, _notify_handoff_error)`. A modal inside
  readyRead stalls the ack → secondary starts a second instance.
  → `rags/lessons/single_instance_ack_semantics.md`
- [pyside6] **checkable_action_invariant_restore_sender**: restore
  ONLY the firing QAction (pass explicitly; `sender()` unreliable)
  and blockSignals while restoring. Looping over all siblings
  re-emits toggled and corrupts state.
  → `rags/lessons/checkable_action_invariant_restore_sender.md`
- [v3-architecture] **forest_visibility_apply_no_reveal**: LATENT —
  `apply()` can hide but never show the hub. Toggling from hidden
  into AOT/taskbar can leave hub stuck. No fix yet; UI gating limits
  reachability.
  → `rags/lessons/forest_visibility_apply_no_reveal.md`
- [v3-architecture] **minimised_hub_virtual_desktop_follow**: LATENT
  — `IsWindowOnCurrentVirtualDesktop` returns True for minimised
  windows on any desktop. Taskbar-mode hub does not follow across
  virtual desktops while minimised.
  → `rags/lessons/minimised_hub_virtual_desktop_follow.md`
- [v3-architecture] **cell_positioning_central_tracker**: the layout
  engine (tiling.py → layout.py → CellWindow._compute_layout) IS the
  central tracker. Every reveal/restore/rescue path must route member
  positions through it, never replay a stored coordinate. Invariant:
  clamp hub on-screen BEFORE calling _compute_layout. Reveal-path
  audit: startup/_repack_members, collapse/expand a68, resolution
  rescue a72, programmatic hub moves a69. A coordinate replay with no
  free-slot/on-screen/collision check is a latent overlap/off-screen bug.
  → `rags/lessons/cell_positioning_central_tracker.md`
- [v3-architecture] **hub_onscreen_clamp_programmatic**: only live
  mouse-drag clamped the hub; programmatic moves (show_hub
  taskbar/tray restore + forest_controller.start position restore)
  did not, so a stale saved coordinate stranded the hub off-screen —
  "forest disappeared". Fix (a69): ForestVisibilityManager._clamp_hub
  reuses hub._clamp_to_screen; both show_hub restore branches and
  start() call it before w.move().
  → `rags/lessons/hub_onscreen_clamp_programmatic.md`
- [pyside6] **virtual_desktop_follow_debounce**: _follow_user_across_
  desktops must be DEBOUNCED (120 ms _follow_debounce QTimer in
  _FocusWatcher) so focus churn fires ONE COM move, not one per event.
  Also guard with _drag_started: never MoveWindowToDesktop mid-drag
  or the hub disappears from under the cursor. Verify-and-log after
  the move. Fix (a70).
  → `rags/lessons/virtual_desktop_follow_debounce.md`
- [v3-architecture] **group_aware_rescue_repack**: rescue_all_cells
  must be GROUP-AWARE: clamp each MASTER on-screen, then route its
  members through _repack_members(instant=True) -> _compute_layout.
  Clamp true standalones. Leave group members to their master's repack
  — clamping them independently stacks them at the same screen edge.
  Fix (a72).
  → `rags/lessons/group_aware_rescue_repack.md`
- [v3-architecture] **forest_login_autostart**: the forest gained the
  tree-ring's "Auto-load on startup" (Windows Run-key) — single
  configured forest, 3 scopes. ScripTree is single-instance, so ring +
  forest SHARE one Run-key value per scope, written by the unified
  chokepoint `ring_io.recompute_autostart` (combines `--forest` /
  `--autoload-rings`; ring-only path byte-identical to pre-a84). Three
  gotchas: (1) every `ForestPreferences(` copy-constructor must carry a
  new field or it silently resets (6 sites — `_on_visibility_toggle`
  was the miss); (2) `disable_forest_autostart` must recompute ONLY the
  old scope — recomputing "system" unelevated raises PermissionError on
  the HKLM admin check; (3) the `runas` elevate helpers must return
  `ret > 32` and the caller flip the cached scope only on True, else a
  UAC-cancel makes the menu lie. Fix (a84).
  → `rags/lessons/forest_login_autostart_a84.md`
- [v3-architecture] **forest_cells_left_behind**: TWO independent "cells
  left on the desktop" bugs. (A) the forest auto-hide walk
  `_forest_descendants` followed only the LINK graph (`_members`) and
  recursed only into masters, so a ring docked to the forest "purely
  spatially" via Case M1 (`hub._dock_children_by_edge`, never a member)
  was never hidden → fix: walk the DOCK graph too, recurse every node,
  dedupe via `seen`. (B) `_compute_layout` Pass 2 auto-hid an unslottable
  member (LIMBO, `nearest_free_slot`→None at full-fit) and only a later
  pass un-hid it → fix: keep an on-screen limbo member visible. Gotcha
  (adversarial-caught): keep-visible MUST collision-check via
  `tiling.any_polygon_collides` over `occupied_centres` (limbo is entered
  *because* slots collide), else it re-admits the a67/a74 visible-overlap
  class. Fix (a85).
  → `rags/lessons/forest_leftbehind_hide_walk_and_limbo_a85.md`
- [pyside6] **draggable_qmenu_popup_gotchas**: making a QMenu draggable
  failed 3× and was abandoned (a86, reverted a87). A QMenu popup does NOT
  call your overridden `mouseMoveEvent` during a held-button drag (the
  popup grab routes moves through QMenuPrivate) — overriding it to
  `self.move()` the popup silently no-ops; the only fix is an explicit
  `grabMouse()` (fragile in a popup). Direct-handler unit tests
  (synthetic QMouseEvent → `menu.mouseMoveEvent(ev)`) pass while the real
  feature fails — they test math, not popup delivery. A designated handle
  row is undiscoverable AND a menu opening near the screen bottom grows
  UPWARD so the cursor lands far from a top handle. `int(Qt.MouseButton)`
  raises in PySide6 (log the enum, not int()), and a broad except hid it.
  Meta: time-box Qt-internals fights; pivot to a simpler affordance.
  → `rags/lessons/draggable_qmenu_popup_gotchas.md`
- [v3-architecture] **portable_mode_and_ignore_copy** (a89): TWO features. (3)
  "Truly portable" — a `portable` sentinel / `SCRIPTREE_PORTABLE` env redirects
  ALL per-user/registry state under `<install>/_portable_data` (+ personal apps
  under `<install>/ScripTreeApps`). Redirect `default_personal_root` and it
  CASCADES to `_groups` + the forest's 3rd discover root; the rest
  (`default_autoload_path`, the easily-missed `shared_autoload_path`,
  `ring_io._appdata_dir`/`_programdata_dir`-with-`/system`-subdir/
  `_default_rings_dir`, and a `QSettings.setDefaultFormat(IniFormat)+setPath`
  in `ring_main` before the first bare QSettings) each need patching. A 3-agent
  adversarial review caught 5 real gaps (missed shared twin, collapsed
  user/system scope, travelling-ini override defeating portability, success-toast
  on read-only write failure, a falsified "zero registry" doc claim). (4)
  "Ignore this copy" — dual-source both-copies-show is ALREADY the default
  (path-only dedup); built the suppress-one inverse on the existing path-keyed
  `excluded[]` substrate (`ignore_copy`/`forget_excluded` + per-item popup
  button + `ExcludedItemsDialog` rebuilt as a directory `QTreeWidget`). Gotcha:
  match `_norm`/`Path.resolve` between the child-folder test and the excluded
  set or junctioned trees disagree; trailing `/` on app_dir stops
  `SolidWorks/`-vs-`SolidWorksTools/` prefix false-matches.
  → `rags/lessons/portable_mode_and_ignore_copy_a89.md`
- [v3-architecture] **named_root_path_portability** (a92, option #2): forest
  item/catalog/excluded paths are stored as `(root-id, rel-to-that-root)` for
  the portable-aware roots `install`/`apps`/`personal` (`forest_io.known_roots`)
  instead of machine-pinned absolutes — so a reference survives a move /
  portable toggle / cross-machine copy (bases recomputed each load;
  serialization-only, `ForestItem.path` stays absolute in memory; legacy
  bare-path forests still load). A 3-agent review caught 5 real gaps: (1)
  `excluded[]` left absolute desyncs from rooted items → ignored copy reappears
  (root it too, but NO existence-gate so it stays canonical for matching); (2)
  the `_rooted_to_abs(...) or fallback` was DEAD (non-None sentinel) so a
  co-located zipped workspace stranded — gate on `.exists()`; (3) de-dup-by-base
  dropped the `personal` id from reverse lookup under portable mode — keep every
  id; (4)+(5) stale `portable_migrate` doc + undocumented downgrade hazard.
  Foundation for "portable copy incl. local tools" (re-tag root→install) and
  local-vs-network dual-source (different root-ids, same rel).
  → `rags/lessons/named_root_path_portability_a92.md`
- [v3-architecture] **portable_consolidate_feature_a** (a93): "Convert this
  install to portable (copy local tools here)" — copy every forest tool living
  OUTSIDE the install (under `apps`/`personal`) into `<install>/ScripTreeApps`,
  re-root the item (`save_forest` then tags it `root: "install"` because
  `known_roots` lists install FIRST — implicit, no schema field), then
  `migrate_for_toggle(True)` LAST. Primitive = `plan`/`execute`(pure copy, never
  deletes source)/`rebase` in `shell/portable_consolidate.py`. KEY: the handler
  **re-keys `self._spawned`** (old path→new path on the SAME live window) instead
  of close+respawn — closing fires `_on_cell_closed` which would PRUNE the item
  being re-rooted, and `save`'s `_sync_positions_into_items` looks the window up
  by the NEW path. A 3-lens review caught 3 real bugs: (1) private-tool warning
  matched the folder NAME not its CONTENTS (neutral `MyMacros/` of `.csx` slipped
  through; `\.csx` token dead on a dir path) → walk `os.walk` contents; (2) a
  loose tool in a root base (rel `"."`, not `""`) made `dest==dest_root` →
  copytree'd the WHOLE root into `ScripTreeApps-2` → single-file copy into a
  per-tool folder + dedup key = copy SOURCE not `src_folder`; (3) `catalog_path`
  outside the copied folder dangled cross-machine → relink to the new install
  catalog. Deferred: A1 (make NEW portable copy elsewhere) + Feature B (network
  roots / dual-source) — NOT interleaved.
  → `rags/lessons/portable_consolidate_feature_a_a93.md`
- [v3-architecture] **portable_make_copy_feature_a1** (a94): "Make a portable copy
  (incl. local tools)" — build a NEW self-contained portable ScripTree at a chosen
  EMPTY folder (app + install tools + outside tools), live install/forest
  untouched (deep-copy rebase).  New `shell/portable_export.py`: `copy_install_tree`
  (refuses non-empty dest, never rmtree's user data), `rebase_install_items_to_external`,
  `prune_items_outside_external`, `save_forest_for_external_install`.  KEY trick:
  rooting a forest for a DIFFERENT install location — temporarily point
  `forest_io._project_root` at dest for the save so paths tag `root:install` and
  resolve when the copy runs from dest (A1 can't reuse `make_portable.py` — it's
  dev-only and absent from the runtime tree).  A 3-lens review caught 4 real bugs:
  (1) `scriptree.ini` (recent files/layouts/machine paths/SW tool names) copied
  into the shareable copy → exclude it; (2) steps 2-4 unguarded + a cursor
  double-restore (nested except + finally) → one guarded unit, single restore; (3)
  a copy-FAILED personal item serialised `root:personal` and dangled on the dest →
  `prune_items_outside_external` drops anything not under dest/ScripTreeApps; (4)
  install-resident private SW tools travelled un-warned → also scan cur_apps.
  Deferred: bundled-Python USB copy, Feature B, threaded copy progress.
  → `rags/lessons/portable_make_copy_feature_a1_a94.md`
- [authoring][forest-discovery] **uncategorised_wrapper_tree_floats_to_top** (a94):
  a wrapper `.scriptreetree` that represents a folder MUST carry its OWN
  `category` — the discovery priority rule (`forest_discover`) represents a
  folder-with-a-tree BY the tree and STOPS, so the loose `.scriptree` leaves'
  categories are invisible to grouping; only the tree's category counts. An
  uncategorised tree → `group_by_category` passthrough → stand-alone TOP-LEVEL
  cell, re-added every discovery pass.  Real case: `OutlookMigration.scriptreetree`
  had no category → floated to top while its 7 leaves (cat `MSOffice/Outlook`)
  would have folded; fix = add `"category": "MSOffice/Outlook"` to the TREE.
  Caveats: re-organise/restart to apply; an explicitly-pinned `items[]` entry
  beats grouping until removed.
  → `rags/lessons/uncategorised_wrapper_tree_floats_to_top_a94.md`
- [v3-architecture][editor] **tree_editor_root_node_and_metadata** (a95+a96): the
  tree editor's save (`TreeLauncherView._build_tree_def`) rebuilt
  `TreeDef(name, nodes)` only — silently RESET the other 18 of 20 TreeDef fields
  (category, all cell_* icon fields, menus, path_prepend, folder_layout, …) to
  defaults on EVERY save (a95 data-loss fix: `dataclasses.replace(self._tree,
  name=, nodes=)`).  a96 added a clickable ROOT row (`_ROLE_IS_ROOT`) with nodes
  nested under it + a `_TreePropertiesDialog` (name/category/path_prepend via
  toolbar + context menu) so tree metadata is editable in-app at last.  Drag-drop
  keeps a single root via a post-drop `_sweep_strays_under_root`; root not
  draggable/removable/launchable; serialisation walks `root.children`.  KEY
  lesson: rebuild a dataclass from UI with `replace(orig, …)`, never
  `Cls(only,two,fields)` — a constructor silently defaults every omitted field.
  Review caught 1 LOW (blank root inline-rename desync → restore label).
  → `rags/lessons/tree_editor_root_node_and_metadata_a95_a96.md`
- [v3-architecture][forest-discovery] **groups_discovery_feedback_loop** (a98):
  Re-organise duplicated MSOffice (`MSOffice.scriptreetree` + `__auto`) + made a
  circular ref because category grouping writes synthesised trees to
  `default_personal_root()/_groups/` which sits UNDER the personal-apps SCAN
  root — so the synth OUTPUT re-ingests as INPUT.  Bit in TWO places (both
  fixed): the discovery walker `_walk` descended into `_groups`, AND
  `_existing_tree_names`'s `rglob` counted synthesised trees as "existing" →
  `_pick_filename` renamed the fresh synthesis to `__auto` (the duplicate).  Fix:
  skip `_groups` in `_walk` (`_is_skipped_dir`) and in `_existing_tree_names`
  (`"_groups" in tree.parts`).  Groups still show (added from group-pass
  outcomes, not re-discovered).  Lasting fix for the item-5 corruption.
  → `rags/lessons/groups_discovery_feedback_loop_a98.md`
- [v3-architecture][editor][ui] **forest_view_provenance** (a99): opening a forest
  in the editor used `build_merged_tree` which FLATTENED each member into an
  anonymous folder (provenance hidden in an `_origins` sidecar) — so the user
  couldn't tell a real folder from a linked `.scriptreetree` from a synthesised
  `_groups` group.  Fix: `build_forest_view` renders each member as a bare LEAF
  carrying its catalog path → the editor's existing subtree/tool rendering shows
  the file on hover.  Wired into File→Open (`_open_forest`, same process) AND the
  cell-hub double-click (`_open_full_editor_for`, separate editor process → must
  write a temp file).  GATE the cell-hub rewire on `_is_forest_master` (forest
  hub) so RING masters keep the merged view (no regression).  Provenance tooltips
  per row: in-memory folder / 'Linked tree: <path>' / 'Auto-group · category X'
  (synth detected by `"_groups" in Path.parts` — `synthesised_by` is dropped by
  `load_tree`).  Sets up a100 edit routing.
  → `rags/lessons/forest_view_provenance_a99.md`
- [v3-architecture][editor][data-loss] **forest_editor_circular_pushback** (a100):
  two regressions found after a98/a99.  (A) The circular
  `Demo ⊃ ./MSOffice.scriptreetree` came BACK because the forest hub opened via
  the flattened MERGED path → `_inline_subtree_refs` nested groups → Save →
  `merged_tree.push_back_to_origins` wrote a sibling-group ref (RELATIVE `./`
  path = written by a save, NOT the synthesis; a98 guards only the READ side).
  Fix: `show_composite_for` branches on `_is_forest_master` → forest view (no
  push-back); + push-back GUARD strips `.scriptreetree` leaves when writing into
  a `_groups` source (rings untouched).  (B) "can't right-click edit":
  double-LEFT→popup, double-RIGHT→`show_composite_for` was not forest-aware (a99
  only rewired the □ button), subtree rows had no edit action.  Fix: forest-aware
  `show_composite_for` + subtree "Open in editor" → `openTreeRequested` → load
  linked tree editable.  Lessons: read-axis guard ≠ write-axis fix; wire ALL
  gestures; never ingest a regenerated artifact as a merge member.  Review: 0
  findings.  Drag-to-recategorize/inline-edit still pending.
  → `rags/lessons/forest_editor_circular_pushback_a100.md`
- [v3-architecture][editor][data-mutation] **drag_to_recategorize** (a102): editing
  a synthesised auto-group's folder LAYOUT in the editor + Save re-files each
  member by position into the member's own `category` (the source of truth) via a
  targeted JSON edit — NOT writing the regenerated group file.  A 2-lens review
  caught 4 (all fixed): (MED) removing a member was silently lost + reported
  success → clear category of dropped members so removal sticks; (MED) empty
  folders can't persist (regenerate-from-categories) → surface in the dialog;
  (LOW) un-normalised stored category churned → compare `_normalise_category`;
  (LOW) a folder renamed with `/` exploded into nesting → scrub separators.
  Lessons: a view over a DERIVED artifact translates edits to the source, not the
  artifact; honest partial-success feedback; compare normalised forms; scrub
  separators when a layout label becomes a category segment.  Inline subtree edit
  still deferred (Open-in-editor covers it).
  → `rags/lessons/drag_to_recategorize_a102.md`
- [editor][data-mutation] **inline_subtree_edit_writeback**: a103 makes a linked
  subtree's children editable in place + writes each CHANGED subtree back to its
  own file on Save (re-load + `dataclasses.replace` keeps top-level metadata;
  child paths relativised against the SUBTREE's dir; parent keeps a one-line ref,
  never flattens). THE LESSON: a LOSSY editor round-trip is both a metadata STRIP
  and a CHURN engine — `_item_to_node` dropped icon/icon_data/icon_format (all
  nodes), folder display_name, subtree-ref configuration, so a field-wise `==`
  over that lossy projection rewrote + stripped any metadata-bearing subtree on a
  plain NO-OP Save (subtrees auto-expand at load). Two adversarial Workflow passes:
  pass 1 found 10/10 real (2 HIGH silent data-loss); fixes = (A) carry EVERY
  persisted field onto items + re-emit (`_store_node_metadata`, icon roles +6/7/8,
  `_icon_kwargs_from_item`) — also fixes pre-existing parent-save loss; (B)
  `_churn_key` folds `./`-prefix + `\`→`/` so bare/backslash on-disk path FORM
  (our own shipped management tree uses bare) doesn't false-diff; (C) `written_keys`
  de-dupe so a duplicate row can't clobber an edit; (D) gate drops on
  `_ROLE_EXPAND_OK` so a tool can't vanish into a failed-expand subtree.
  Reusable: carry every model field onto the UI item before you diff on it;
  "real files don't have field X" needs a metadata-bearing fixture to prove;
  normalise the comparison to the dimension the file author owns (path form);
  reconcile both ends of a gesture (accept-drop vs refuse-writeback).
  → `rags/lessons/inline_subtree_edit_writeback_a103.md`
- [forest][data-mutation][self-heal] **groups_circular_ref_unprunable_residue**:
  the `_groups` circular ref (Demo ⊃ ./MSOffice.scriptreetree and vice-versa) that
  "kept coming back" was UN-HEALABLE RESIDUE, not an active re-write — all a98/a100
  guards still hold (couldn't reproduce on live code without disabling one). A
  pre-a100 push-back wrote the sibling-group leaf AND stripped the `synthesised_by`
  marker, so `prune_orphan_synthesised` (marker-keyed) could never delete it → it
  sat on disk, re-shown every startup. a104 fixes: (1) `push_back_to_origins`
  REFUSES any `_groups/` source whole-file (marker-independent, stronger than the
  a100 per-child strip); (2) `prune_orphan_synthesised` SELF-HEALS — deletes a
  `_groups` file containing any `.scriptreetree` leaf (structurally illegal) even
  without the marker, so residue is reclaimed + regenerated clean. Forensics: the
  relative `./` leaf form + missing marker fingerprint `save_tree`/push-back, NOT
  `categorize` (which writes marker + leaf name + ABSOLUTE paths). Reusable: a
  "recurring" bug with all guards intact is often un-healed residue — check what
  CLEANS the bad state, not just what writes it; recognise corruption by STRUCTURE
  when the corrupting path strips your marker; guard the whole artifact, not each
  child. → `rags/lessons/groups_circular_ref_unprunable_residue_a104.md`
- [editor][forest] **subtree_tree_properties_a104**: a104 adds "Tree properties…"
  to a LINKED SUBTREE row (was root-row-only), so a forest member like ffmpeg can
  have its name/category/path_prepend edited + written back to its own file
  (`_open_subtree_properties`, `dataclasses.replace` preserves nodes) WITHOUT first
  "Open in editor". A synthesised `_groups` member is exempt (regenerated → info
  dialog, no write). The forest-as-root editor case had no way to set a member's
  Category from its row. Tests: `tests/test_subtree_properties_a104.py` (3).
- [pyside6] **screenshooter_headless_capture**: the headless screenshooter hung
  on tools with a personal-config sidecar collision or an on-open provider —
  `ToolRunnerView.__init__` blocks on `PersonalConfigCollisionDialog.exec()`
  (nested modal loop, no event loop) and `_run_provider` (subprocess, e.g.
  SolidWorks/combridge). Fix: a `tool_runner.HEADLESS_CAPTURE` module flag set
  by the screenshooter in `_ensure_app` (the chokepoint before any widget is
  built); the collision method returns at the prompt (→ default config) and
  `_run_provider` returns at its top. Second defect: `grab()` on an UNSHOWN
  top-level skips the full show/layout cascade, so a nested `QTabWidget`'s
  current page (the param-group tabs) renders EMPTY; fix is the canonical
  `WA_DontShowOnScreen` + `show()` in `_capture` (off-screen but fully laid
  out). Test-isolation: `test_screenshooter.py` runs the shooter as a
  SUBPROCESS so the global never leaks; in-process tests must save/restore it.
  a88. → `rags/lessons/screenshooter_headless_capture_a88.md`
- [shutdown][process-lifecycle][single-instance] **lingering_process_quit_on_empty**:
  a ScripTree `pythonw.exe` lingered after "exit" — and THAT stale primary kept
  re-writing the `_groups` file AND owning the single-instance pipe, so every
  redeploy silently handed off to the OLD process (the reason fixes "didn't take").
  Killing it in Task Manager is what let new code run. Root cause: app sets
  `setQuitOnLastWindowClosed(False)`, but `CellWindow.closeEvent` (the [X] button)
  unregistered + closed WITHOUT `QApplication.quit()`, so closing the last window
  left a headless process; `_close_this`'s `is_last` checked standalones-only
  (missed a last MASTER; prematurely quit a last standalone while a master
  remained). a106 fix: `closeEvent` → `_quit_if_app_empty()` quits iff the registry
  has no standalones AND no masters; `_close_this` defers to it. Safe vs premature
  quit: auto-hide uses `hide()`/`showMinimized()` (cells stay REGISTERED), so a tray
  forest isn't quit — only a truly empty registry quits. Reusable: with
  quitOnLastWindowClosed False, EVERY full-close path (incl. closeEvent) must quit;
  a lingering single-instance primary silently defeats deploys; key quit-on-empty on
  REGISTRATION, not visibility. → `rags/lessons/lingering_process_quit_on_empty_a106.md`
- [forest][windows][removal] **removed_virtual_desktop_subsystem**: a107 deleted the
  a55–a70 Windows virtual-desktop "follow the user across desktops" feature at the
  user's request — it stranded the hub ("forest disappeared, cells left behind") and
  complicated basic GUI behaviour. Deleted `win_virtual_desktops.py` + the follow
  plumbing in `forest_visibility.py`; removed 2 vdesktop test classes; archived
  everything to `docs/archive/removed_virtual_desktop_a107/` for a future re-attempt.
  KEPT multi-MONITOR (physical screens) — only multi-DESKTOP removed. Gotchas for the
  re-do: `MoveWindowToDesktop` rejects a HIDDEN window (TYPE_E_ELEMENTNOTFOUND) but
  accepts a MINIMISED one; per-focus-event moves are racy (needed a debounce +
  never-move-mid-drag guard). Reusable: archive-before-delete; name the axis precisely
  (monitor≠desktop); strip shared funcs surgically + delete pure ones wholesale.
  → `rags/lessons/removed_virtual_desktop_subsystem_a107.md`
- [forest][windows][refactor][model-apply] **forest_visibility_model_apply_refactor**:
  a108 collapsed the THREE divergent forest show paths (tray `show_hub` forced a stored
  pos; taskbar `eventFilter`→`_restore_descendants` trusted the OS; startup did its own
  show) + THREE disagreeing position stores into ONE model→apply design (Ken: "they call
  different code... don't add more patches to fix an underlying issue"). `ForestHubState`
  dataclass = single truth; one idempotent `apply_state()`; `show_hub`/`hide_hub` are thin
  wrappers; `_restore_descendants` DELETED → shared `_reveal_hidden_descendants`; the
  taskbar restore now calls `show_hub` (same code as tray). Drag-capture in
  `forest_controller._on_hex_moved` writes `state.hub_position` (gated visible+not-min) →
  kills "tray click snaps back to show-time pos". TWO gotchas: (1) `setWindowFlags` on
  Win11 recreates the HWND → resets pos to (0,0) + drops mask; old code only repaired it
  `if was_visible`, but the hub's flags apply at startup BEFORE the first show → (0,0)/
  blank/not-draggable. Fix: capture pos before, restore after, reassert chrome
  UNCONDITIONALLY. (2) `moveEvent` fires `hexagonMoved` on programmatic moves too → guard
  the drag-capture on visible+not-minimised. Docking engine PRESERVED (design §6a).
  Headless can't verify window behaviour — design §8 manual matrix is the gate.
  a109 = adversarial-review hardening: a 37-agent Workflow found TWO real bugs in
  the a108 code — (HIGH) the hide branch wasn't idempotent (a 2nd hide while
  hidden wiped hidden_descendant_ids -> next show revealed no cells, the exact
  "forest comes back empty" bug); fixed by an already-hidden no-op early-return.
  (MEDIUM) clamp-on-show re-entered _on_hex_moved and overwrote the saved
  off-screen position with the clamped value; fixed by an _applying_state
  re-entrancy flag. Both with regression tests (109->121 forest). Meta-lesson: a
  render pass must be idempotent on BOTH transitions, and the same move-signal
  carries user intent AND the render pass's own programmatic moves (gate the
  capture). → `rags/lessons/forest_visibility_model_apply_refactor_a108.md`
- [packaging][pyside6][vendored-deps][release] **portable_bundle_trim_strips_required_qt_module**:
  a111 — the portable bundle is minimal; `lib/update_lib.py --trim` deletes every Qt submodule
  not in `TRIM_KEEP_MODULES`, and `make_portable.py` requires a trimmed lib before zipping.
  `QtNetwork` (needed by single_instance.py's QLocalServer) was MISSING from the keep-list AND
  `Qt6Network*.dll` was in the explicit `TRIM_REMOVE_GLOBS` strip-list, so every release zip
  shipped without it → single-instance silently disabled ("handoff errored ... falling through").
  The surviving `QtNetwork.pyi` stub (kept by `*.pyi` in TRIM_ALWAYS_KEEP) made the dir LOOK
  complete. Fix needs BOTH: add "QtNetwork" to TRIM_KEEP_MODULES + remove the two `Qt6Network*`
  globs from TRIM_REMOVE_GLOBS (two independent removal paths). Durable guard: TRIM_KEEP_MODULES
  must == `grep -rhoE "from PySide6\.(Qt[A-Za-z]+)" scriptree/` (a111 = Core/Gui/Widgets/Network).
  → `rags/lessons/portable_bundle_trim_strips_required_qt_module_a111.md`
- [v3-architecture][taxonomy][validate][ux] **canonical_category_catalog**: a112 — there was NO
  controlled vocabulary for the `.scriptree` `category` field (free-form, unenforced), and
  `Demo`/`Demos` had already fragmented the forest into 2 cells. Built: (1) an extensive canonical
  catalog — 799 categories / 185 top-levels across CAD/Office/Media/DevTools/Data/Security/etc.,
  generated by a 27-agent Workflow (one agent per software domain + guide synthesis); synced
  `docs/LLM/category_catalog.md` + `scriptree/resources/category_catalog.json` (test enforces
  doc⊇json). (2) a soft near-dup matcher `scriptree/core/category_catalog.py` (stdlib difflib;
  classifies case/plural/typo; ADVISORY, never rejects). (3) wired into `scriptree validate`
  (per-file + cross-file sibling `[WARN]`, both .scriptree + .scriptreetree). (4) QCompleter
  autocomplete on the Category field in tool_editor.py + tree_view.py. Gotcha: the de-dupe of
  sibling-vs-canonical warnings fell through an if/else into a spurious top-level warning — a
  canonical near-dup must consume the branch. Reusable: Workflow fan-out (1 agent/domain) +
  synthesis is ideal for "make a very extensive list"; pair any generated vocabulary with a soft
  validator + autocomplete so it's used, not drifted.
  → `rags/lessons/canonical_category_catalog_a112.md`
- [v3-architecture][forest][layout][async-race] **bloom_relocation_capture_race**: a113 — the
  intermittent "a bloomed forest cell relocates even though its space is free" bug. Root cause
  (found via a 19-agent RCA Workflow): in mouseReleaseEvent, `_settle_no_overlap()` runs BEFORE
  `_capture_remembered_offset()` in the same synchronous turn; settle relocates an overlapping/
  edge drop via `_smooth_move` -> an ASYNC QPropertyAnimation whose target `self.pos()` isn't
  reached until later turns, so capture stored the PRE-settle STALE offset. On bloom that stale
  spot fails `_restore_remembered_offsets`' on-screen fit-test -> the member is engine-tiled to a
  different slot. Intermittent because a clean drop hits settle's `if _ok(0,0): return` (no anim ->
  correct capture); only overlap/edge drops trip the spiral. FIX: capture the animation's
  `endValue()` (settled destination) not the live pos, for member AND hub. Takeaway: a
  QPropertyAnimation is a WRITE-LATER — reading widget.pos() in the same turn you started a pos
  animation gives the OLD value; read endValue() or defer past the animation duration.
  → `rags/lessons/bloom_relocation_capture_race_a113.md`
