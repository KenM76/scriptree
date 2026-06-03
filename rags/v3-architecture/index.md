# v3-architecture — index

V1↔V3 layering, single-instance handoff, master cells, the
.scriptreering format, and the v0.2.7 cell-metadata-in-catalog
design.

- [v3-architecture] **v1_cli_needs_standalone_flag**: V1 opens
  the editor by default for a `.scriptree` arg; cell launches
  must pass `-standalone`.
  → `rags/lessons/v1_cli_needs_standalone_flag.md`
- [v3-architecture] **cell_members_dict_not_list**:
  `CellWindow._members` is `dict[member_id, QPoint]` — iterate
  keys and look up via `CellRegistry`.
  → `rags/lessons/cell_members_dict_not_list.md`
- [v3-architecture] **single_instance_handoff_qlocalserver**:
  per-user `QLocalServer` pipe; `--new-process` opts out of
  both handoff and listen; `SCRIPTREERING_PIPE_NAME` env-var
  for tests. → `rags/lessons/single_instance_handoff_qlocalserver.md`
- [v3-architecture] **master_cells_no_catalog_path**: masters
  have no catalog of their own; route double-right through
  `show_composite_for`, not `show_tree_for`.
  → `rags/lessons/master_cells_no_catalog_path.md`
- [v3-architecture] **cell_metadata_in_catalog_json**: v0.2.7
  promoted icon/label/scale/opacity to a `cell` sub-object in
  the catalog JSON, with QSettings as fallback; defaults are
  omitted to keep legacy files byte-identical.
  → `rags/lessons/cell_metadata_in_catalog_json.md`
- [v3-architecture] **icon_path_relative_normalization**:
  store as forward-slash relative path when icon is under
  catalog dir; absolute otherwise.
  → `rags/lessons/icon_path_relative_normalization.md`
- [v3-architecture] **embed_unembed_icon_roundtrip**:
  `embed_icon` writes base64 + format and clears the path;
  `unembed_icon_to_file` does the reverse, restoring a
  relative path. → `rags/lessons/embed_unembed_icon_roundtrip.md`
- [v3-architecture] **camelcase_precedence_in_label**:
  CamelCase abbreviation wins over multi-word first-letter
  derivation: "SolidWorks toolkit" → "SW", not "St".
  → `rags/lessons/camelcase_precedence_in_label.md`
- [v3-architecture] **wordskip_list_for_abbreviations**:
  skip `{a, an, and, or, the, of, to, in, on, for, at, by, as,
  is, if}` when deriving multi-word labels, case-insensitive.
  → `rags/lessons/wordskip_list_for_abbreviations.md`
- [v3-architecture] **explode_tree_via_temp_ring**: turn a
  `.scriptreetree` into a multi-cell ring by writing a synthetic
  `.scriptreering` to `%TEMP%` and handing it to the cell shell;
  no new imperative API needed.
  → `rags/lessons/explode_tree_via_temp_ring.md`
- [v3-architecture] **save_as_rebinds_path**: Save-As must
  re-bind `self._tree_file` (and refresh `_tree_read_only`)
  *before* delegating to the existing save method.
  → `rags/lessons/save_as_rebinds_path.md`
- [v3-architecture] **group_uniform_size_and_repack**: cells in a
  master group share `size_px` / `shape` / `orientation`; settings
  broadcast through `_apply_group_geometry` and a pure-logic
  `group_layout.repack` keeps members edge-touching, non-overlapping,
  and on-screen.
  → `rags/lessons/group_uniform_size_and_repack.md`
- [v3-architecture] **close_member_uses_membership_not_source_id**:
  master.source_a_id / source_b_id are frozen identity fields, not
  the current cluster — `_close_this` must use `_members` and let
  `_check_master_validity` enforce the quorum rule, otherwise
  closing one of the original two seed cells of a 3+ member ring
  tears down the whole master.
  → `rags/lessons/close_member_uses_membership_not_source_id.md`
- [v3-architecture] **interactive_stdin_with_two_layer_gate**: v0.3.0
  added an interactive-stdin runner mode (Emacs M-% style send-line
  widget); enabled iff (`ToolDef.interactive` AND the
  `interactive_stdin` permission file is writable).  Per-tool author
  opt-in × org admin opt-in.  Print prompts with `flush=True`;
  treat empty `readline()` as EOF.
  → `rags/lessons/interactive_stdin_with_two_layer_gate.md`
- [v3-architecture] **ring_dirty_membership_only**: ring close-
  prompt fires iff `_ring_dirty` OR `_saved_ring_path is None`.
  Flip the bit only at membership-change sites (Case 1 spawn,
  Case 2/3 add, Case 4 transfer, member-close, leave-group,
  shake-detected) — NOT at position-only sites (drag, repack,
  drift, collapse).  Reset in `_write_ring_to_path` and
  `ring_io.load_ring`.
  → `rags/lessons/ring_dirty_membership_only.md`
- [v3-architecture] **tree_path_prepend_run_time_wiring**: v0.3.2
  closed the dead-code gap on `TreeDef.path_prepend` with a
  five-step pattern — kwarg in `build_env`, forwarded through
  `build_full_argv`, exposed via `TreeLauncherView.tree_path_prepend()`,
  consumed via `ToolRunnerView.set_tree_path_prepend(list)`,
  refreshed each `MainWindow._show_runner`.  Tree slots between
  local (tool+cfg) and global in the prepend list.
  → `rags/lessons/tree_path_prepend_run_time_wiring.md`
- [v3-architecture] **capability_wiring_full_audit**: v0.3.3 wired
  every previously-unconsulted capability in `CAPABILITIES`.  Helper
  module `ui/permission_guards.py` (apply_widget_perm /
  apply_action_perm / apply_text_readonly / perm_check) standardises
  the gate pattern.  +25 tests; final tally is 35/35 wired (was 14
  direct + 6 helper-mediated, 15 unwired).  Path-security trio
  (allow_symlinks / allow_path_traversal / access_sensitive_paths)
  required new code paths plumbed through `sanitize_all_values` and
  `validate_resolved_path`.
  → `rags/lessons/capability_wiring_full_audit.md`
- [v3-architecture] **sanitization_warning_suppression**: v0.3.4
  added three "Don't warn me again" checkboxes to the injection
  popup (per-field / per-tool / global), all gated by a single new
  ``suppress_sanitization_warnings`` capability.  Storage in
  QSettings via `core/sanitize_suppression.py`; re-enable dialog
  under Edit ▸ Sanitization warnings...  +22 tests.
  → `rags/lessons/sanitization_warning_suppression.md`
- [v3-architecture] **cell_click_to_run**: v0.3.5 added a per-cell
  setting that turns single-click into a Run button.  Two new
  catalog fields (`cell.click_action`, `cell.click_run_mode`) +
  new `cell_click_to_run` capability + V1 `-run` flag for auto-
  click.  Sequential mode uses Popen polling; parallel iterates
  `launch_tool`.  +24 tests.  Lazy-import-shadowing trap in
  SettingsDialog noted.
  → `rags/lessons/cell_click_to_run.md`
- [v3-architecture] **cell_fill_color_picker**: v0.3.6 added
  per-cell `cell.fill_color` (`#RRGGBB`) override + Settings
  dialog group with synced hex / R-G-B spinboxes / hue rainbow
  slider / reset.  Alpha-preservation rule keeps transparency
  independent.  Hue slider always picks fully-saturated full-V
  colour (not a full HSV editor — power users type hex directly).
  +28 tests.
  → `rags/lessons/cell_fill_color_picker.md`
- [v3-architecture] **link_dock_graph_split**: v0.8.0 split the
  single `_group_master_id` into two orthogonal graphs:
  `_link_parent_id` (forest→rings→cells membership) and
  `_dock_partner_id`/`_dock_edge`/`_dock_children_by_edge`
  (spatial edge adjacency). Invariants L1-L5 in
  `link_dock_audit.py`. Always-linked rule: cells link to forest or
  a ring, never orphan. → `rags/lessons/link_dock_graph_split.md`
- [v3-architecture] **repack_animation_race_dock_position**:
  `_repack_members` is async (260 ms QPropertyAnimation); calling
  `_set_cell_dock` immediately after reads stale `child.geometry()`
  and silently fails edge detection. Pass `child_centre=` kwarg
  from `master._members[mid]` instead.
  → `rags/lessons/repack_animation_race_dock_position.md`
- [v3-architecture] **forest_never_prompts_save**:
  `_ring_needs_save_prompt` (`cell_window.py:7657`) must early-
  return for `_is_forest_master`; `_close_all_related` pre-walks
  nested rings exactly once to avoid double save prompts.
  → `rags/lessons/forest_never_prompts_save.md`
- [v3-architecture] **move_to_cascades_dock_children**:
  `CellWindow.move_to` cascades delta to every cell in
  `_dock_children_by_edge`; children's `move_to` re-cascades for
  chains. `_GROUP_MOVE_IN_PROGRESS` guard prevents re-entry on
  mutual-dock cycles.
  → `rags/lessons/move_to_cascades_dock_children.md`
- [v3-architecture] **per_member_relocation_vs_rigid_settle**:
  `_settle_no_overlap` shifts a master+positioned set as a rigid
  block — wrong when master is docked. New
  `_relocate_overlapping_members_individually` (cell_window.py:8728)
  fixes the master at the dock slot and re-slots only the
  overlapping members.
  → `rags/lessons/per_member_relocation_vs_rigid_settle.md`
- [v3-architecture] **fresh_ring_not_in_forest_positioned**:
  spawning a fresh ring while a forest exists must NOT add it to
  `forest._positioned` or `forest._dock_partners`. Link-parent +
  `_members` entry only. Otherwise forest-drag drags the
  unattached ring.
  → `rags/lessons/fresh_ring_not_in_forest_positioned.md`
- [v3-architecture] **recursive_merged_menu_population**:
  `tree_popup.show_tree_popup_for` master path must recurse into
  members (depth-cap 8) — masters become sub-menus titled via
  `_popup_header_text`. Filtering "no catalog" was too aggressive
  and hid rings from the forest menu.
  → `rags/lessons/recursive_merged_menu_population.md`
- [v3-architecture] **ring_auto_name_session_serial**: rings get
  auto-name via session-global `_RING_SERIAL` counter (cell_window.py
  :2677); `_popup_header_text` fall-through `_catalog_path` →
  `_text_label` → `_auto_ring_name`. Forest excluded from the
  fall-through. Loaded rings name from filename.
  → `rags/lessons/ring_auto_name_session_serial.md`
- [v3-architecture] **ring_cascade_gated_on_positioned**: ring
  drag uses the `_positioned` subset of `_members`, not raw link
  membership — matches forest's existing behaviour and lets a
  dragged-off cell stay put when the ring later moves.
  → `rags/lessons/ring_cascade_gated_on_positioned.md`
- [v3-architecture] **shake_to_close_ring_prompt**: replaces
  v0.6.x auto-close on quorum loss; `_close_ring_via_shake_with_prompt`
  (cell_window.py:7745) fires Save/Discard/Cancel, then re-links
  members to forest on disband per always-linked spec. Forest
  excluded from shake.
  → `rags/lessons/shake_to_close_ring_prompt.md`
- [v3-architecture] **snap_engine_wire_on_fresh_master**:
  `_try_spawn_master` must call `ring_main._wire_hex_to_snap(master)`
  after `master.show()` — without it, snap preview never renders on
  freshly-spawned masters even though the engine still emits.
  → `rags/lessons/snap_engine_wire_on_fresh_master.md`
- [v3-architecture] **personal_sidecar_two_prong_match**:
  `find_personal_configs_for_app` (`scriptree/core/configs.py`)
  must match on BOTH `source_filename` (basename present anywhere
  under app_dir) AND a `source_locations` entry resolving under
  app_dir. Filename-only matching cross-contaminates two installs
  of the same-named tool. Stdlib-only, mirror of load-time predicate.
  → `rags/lessons/personal_sidecar_two_prong_match.md`
- [v3-architecture] **uninstall_keep_remove_flags_with_backup**:
  `ForestController.uninstall_app(path, *, remove_local_configs=True,
  remove_shared_configs=True)` — both default True. Shared-config
  "keep" path COPIES sidecars to a sibling `<app>_uninstalled_configs/`
  (numbered `-2`, `-3` on collision) BEFORE `shutil.rmtree`; if the
  copy raises, REFUSE the uninstall. Dialog labels show live file
  counts; Uninstall button uses `DestructiveRole`.
  → `rags/lessons/uninstall_keep_remove_flags_with_backup.md`
- [v3-architecture] **popup_menu_root_catalog_path**:
  `_add_node_to_menu` / `_build_menu_for_catalog` in `tree_popup.py`
  thread BOTH `source_dir` (path resolution) and `root_catalog`
  (the catalog FILE the menu was built from) through the recursion.
  Every leaf in a `.scriptreetree` stamps `root_catalog_path` =
  the tree file, not the per-leaf catalog — that's what keys
  "Uninstall app..." to the correct app folder.
  → `rags/lessons/popup_menu_root_catalog_path.md`
