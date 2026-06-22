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
- [v3-architecture] **live_edge_reflow_is_load_bearing_dont_remove**:
  the per-frame _live_edge_reflow_or_fold races the rigid drag cascade
  (relocates without updating _members) -> fast-drag "left behind".
  BUT it is LOAD-BEARING: it lets the forest stay in a corner (members
  relocate around it); removing it (a77) made drag-end shove the whole
  cluster back on-screen -> reverted in a78. Fix the divergence in
  place (sync _members on relocate), do NOT remove the reflow.
  → `rags/lessons/live_edge_reflow_races_rigid_drag.md`
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
