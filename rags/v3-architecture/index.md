# v3-architecture — index

V1↔V3 layering, single-instance handoff, master cells, the
.scriptreering format, and the v0.2.7 cell-metadata-in-catalog
design.

- [v3-architecture] **shim_leaks_core_dir_shadowing_stdlib**: the
  runtime shim (`scriptree/core/_runtime_shim.py`) left its own dir
  `scriptree/core` on the spawned tool's `sys.path`; that dir has
  `platform.py`/`io.py` (package submodules) which SHADOW the stdlib,
  so a tool (or a lib it imports — ezdxf) doing `import platform`
  crashed with `module 'platform' has no attribute 'system'`. Fix:
  shim now evicts its own dir. Regression test added.
  → `rags/lessons/shim_leaks_core_dir_shadowing_stdlib.md`

- [v3-architecture] **auto_organise_doubles_path_segment**: the
  category auto-organise generator writes leaf paths with a
  doubled `ScripTree/Apps/` segment because it computes
  relatives from the wrong base.  Symptom: tools missing from
  `_groups/<X>__auto.scriptreetree` catalogs, missing paths show
  `...\Apps\ScripTree\Apps\...`.
  → `rags/lessons/auto_organise_doubles_path_segment.md`
- [v3-architecture] **forest_hub_cell_stable_settings_id**:
  ``CellWindow.__init__`` accepts an optional ``hexagon_id``; if
  omitted it generates a fresh ``uuid.uuid4()``.  Pre-v0.8.0a47
  the forest hub cell was constructed without one, so it got a
  new uuid every launch and ALL its per-cell QSettings entries
  (``hexagon/<uuid>/text_label``, ``/icon_path``, ``/size_px``,
  ``/transparency``, etc.) were re-saved under a new uuid every
  run -- user customisations silently vanished on restart.
  Fix: pass the frozen sentinel ``FOREST_HUB_HEX_ID =
  "forest-hub"`` defined at the top of ``forest_controller.py``.
  Do NOT change the literal -- existing users' saved settings
  live at ``hexagon/forest-hub/*`` from a47 onward.  Regression
  test in ``tests/test_forest.py``.
  → `rags/lessons/forest_hub_cell_stable_settings_id.md`
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
- [v3-architecture] **merged_tree_pushback_to_origins**: v0.8.0a31
  added a sidecar JSON `<merged>.scriptreetree.origins.json` mapping
  top-level folder → source path; `push_back_to_origins` walks the
  saved merged tree and writes each folder back, converting absolute
  leaf paths to relative-to-origin and skipping `.scriptree`
  single-tool sources cleanly.
  → `rags/lessons/merged_tree_pushback_to_origins.md`
- [v3-architecture] **editor_uninstall_persists_to_forest_file**:
  editor and forest are separate processes; the editor must write
  uninstall/drop changes to the per-user `.scriptreeforest` via
  `MainWindow._persist_uninstall_to_forest_file` (best-effort,
  logged) — removes from `items`, appends to `excluded`.
  → `rags/lessons/editor_uninstall_persists_to_forest_file.md`
- [v3-architecture] **merged_tree_dropped_origins_vs_skipped**:
  `PushBackResult` distinguishes `written` / `skipped` (e.g.
  `.scriptree` wrapper) / `errors` / `dropped_origins` (sidecar
  entry with no matching top-level folder = user removed it →
  forest excludes the source). Dropped origins do NOT modify the
  source file on disk.
  → `rags/lessons/merged_tree_dropped_origins_vs_skipped.md`
- [v3-architecture] **merged_tree_inline_subtrees_at_build_time**:
  `_inline_subtree_refs(node, visited)` recursively replaces
  subtree-pointing leaves with their loaded contents at BUILD time
  (not view time) so the editor owns them and can drag/delete
  freely; cycle → "(circular reference)" placeholder. Trade-off:
  subtree refs become STATIC in the merged tree.
  → `rags/lessons/merged_tree_inline_subtrees_at_build_time.md`
- [v3-architecture] **merged_tree_dedup_by_name_with_disambiguation**:
  two `.scriptreetree` files with the same internal display name
  must be disambiguated by appending the source's parent-folder
  name in parens (`"MSOffice (a_apps)"`), falling back to a numeric
  counter. Order-stable across rebuilds because the sidecar keys
  by the disambiguated name.
  → `rags/lessons/merged_tree_dedup_by_name_with_disambiguation.md`
- [v3-architecture] **editor_forest_sync_via_forest_file**:
  the `.scriptreeforest` file is the ONLY IPC channel between the
  editor subprocess and the running forest. Every editor-side
  action that affects forest membership/state MUST write through
  it; no in-process signals, no live update — the contract is
  edit closed → forest reloaded.
  → `rags/lessons/editor_forest_sync_via_forest_file.md`
- [v3-architecture] **rescue_cells_on_reveal**: every reveal path
  (show_hub, taskbar restore, tray click) must call
  `_rescue_cells_on_screen(shown_list)` after `cell.show()` so
  cells that moved off-screen while hidden are clamped back.
  Mirrors `screen_watcher.rescue_all_cells` contract. Both
  `show_hub` and `_restore_descendants` must call it.
  → `rags/lessons/rescue_cells_on_reveal.md`
- [v3-architecture] **forest_startup_hub_not_draggable**: forest
  hub not draggable at startup (tentative fix a63) — schedule
  `_finalize_hub_interactive` via `QTimer.singleShot(0, ...)` to
  `raise_()` + `activateWindow()` after Qt processes the map event.
  Guard to no-op in taskbar/tray-hidden modes. Bug NOT reproducible
  headless; `[forest_startup]` log tag captures next live-run data.
  → `rags/lessons/forest_startup_hub_not_draggable.md`
- [v3-architecture] **forest_controller_module_global_handle**:
  publish the live `ForestController` as `ring_main._FOREST_CONTROLLER`
  (set in `main()` after `start()` succeeds) so
  `_handle_primary_message` can call `_visibility.show_hub()` on a
  second launch instead of spawning a stray standalone cell.
  → `rags/lessons/forest_controller_module_global_handle.md`
- [v3-architecture] **single_instance_ack_semantics**: the
  single-instance ack means "delivered to the live primary", NOT
  "the work succeeded". Always ack ok=true. Surface failures
  GUI-side via `_notify_handoff_error` (deferred via
  `QTimer.singleShot(0, ...)` — a modal inside `readyRead` stalls
  the ack and causes a second instance). Wrap every
  `_handle_primary_message` branch in try/except; never let
  exceptions escape to the handler.
  → `rags/lessons/single_instance_ack_semantics.md`
- [v3-architecture] **forest_visibility_apply_no_reveal**: LATENT
  gap — `ForestVisibilityManager.apply()` can hide but never show/
  showNormal the hub. Toggling into AOT/taskbar from a hidden state
  leaves the hub stuck. Reachability is currently limited by the UI
  (toggles live on the visible hub) but a defensive showNormal
  branch is missing.
  → `rags/lessons/forest_visibility_apply_no_reveal.md`
- [v3-architecture] **minimised_hub_virtual_desktop_follow**: LATENT
  gap — `IsWindowOnCurrentVirtualDesktop` returns True for minimised
  windows regardless of their virtual desktop. The
  `_follow_user_across_desktops` logic short-circuits and the
  minimised taskbar-mode hub does NOT follow across desktops.
  → `rags/lessons/minimised_hub_virtual_desktop_follow.md`
- [v3-architecture] **cell_positioning_central_tracker**: the layout
  engine (tiling.py → layout.py → CellWindow._compute_layout) IS the
  central tracker. Every reveal/restore/rescue path must route member
  positions through it. Clamp hub on-screen before _compute_layout.
  Reveal-path audit: startup, collapse/expand (a68), resolution rescue
  (a72), programmatic hub moves (a69).
  → `rags/lessons/cell_positioning_central_tracker.md`
- [v3-architecture] **hub_onscreen_clamp_programmatic**: only live
  drag clamped the hub; show_hub restore and start() position restore
  didn't, so a stale coordinate stranded the hub off-screen. Fix (a69):
  ForestVisibilityManager._clamp_hub + call it at both show_hub
  branches and start().
  → `rags/lessons/hub_onscreen_clamp_programmatic.md`
- [v3-architecture] **group_aware_rescue_repack**: rescue_all_cells
  must clamp master then _repack_members(instant=True); standalone
  cells are clamped; group members are left to their master's repack.
  Clamping members independently stacks them. Fix (a72).
  → `rags/lessons/group_aware_rescue_repack.md`
- [v3-architecture] **self_contained_python_tool_recipe**: portable
  `.scriptree` Python tools: `"executable": "%SCRIPTREE_LIB_PYTHON%/python.exe"`;
  `"working_directory": "./."` (co-located scripts by bare name); do NOT
  pass `-3.12` (py-launcher flag, rejected by python.exe). expandvars
  applied to executable/working_directory/path_prepend in
  `runner.py:resolve_tool_path ~L289`. Env vars published at startup:
  SCRIPTREE_HOME, SCRIPTREE_LIB, SCRIPTREE_LIB_PYPI, SCRIPTREE_LIB_PYTHON,
  SCRIPTREE_APPS. Canonical docs: docs/LLM/scriptree_home_env_var.md,
  docs/portable_python.md.
  → `rags/lessons/self_contained_python_tool_recipe.md`
- [v3-architecture] **vendoring_tool_deps_into_lib_pypi**: add packages
  to lib/requirements.txt (pinned exact), install with the BUNDLED
  interpreter (`lib\python\python.exe -m pip install --target lib\pypi`)
  for ABI correctness (cp314). Then inject at runtime via
  `sys.path.insert(0, os.environ["SCRIPTREE_LIB_PYPI"])` — PYTHONPATH
  is ignored by the embedded interpreter. Two-tree deploy obligation
  applies to lib/ too.
  → `rags/lessons/vendoring_tool_deps_into_lib_pypi.md`
- [v3-architecture] **embeddable_python_ignores_pythonpath**: GOTCHA —
  the bundled embeddable Python ignores PYTHONPATH (controlled by
  lib/python/python314._pth which disables site.py). Cannot rely on
  `PYTHONPATH=lib/pypi` for child tool subprocesses. Must do
  `sys.path.insert(0, os.environ["SCRIPTREE_LIB_PYPI"])` inside every
  tool script. Empirically verified: env-var form fails, sys.path.insert
  succeeds.
  → `rags/lessons/embeddable_python_ignores_pythonpath.md`
- [v3-architecture] **combridge_finder_scriptree_home_first**: canonical
  combridge discovery order for tool scripts: (1) SCRIPTREE_COMBRIDGE env
  override; (2) %SCRIPTREE_HOME%/lib/combridge/combridge.exe; (3)
  %SCRIPTREE_LIB%/combridge/combridge.exe; (4) shutil.which (PATH prepend);
  (5) D:/R: hardcoded fallback. Validate SolidWorks plugin DLL presence;
  reject plugin-less dev builds early. For .scriptree executables, use bare
  "combridge.exe" (PATH prepend resolves it).
  → `rags/lessons/combridge_finder_scriptree_home_first.md`
- [v3-architecture] **drawing_gen_sw_bridge_to_combridge**: drawing-gen
  migrated from sw_bridge.exe (OneDrive-only, never bundled) to combridge.
  .csx ported verbatim (combridge injects identical swApp/swDoc/swPart/swAssy/
  swDrawing globals). Only launcher changed: `sw_bridge.exe run-script <csx>
  <out>` → `combridge solidworks run-script <csx> <out>`. Mirrors
  dxf_export.py migration. sw_bridge is legacy; new tools start with combridge.
  → `rags/lessons/drawing_gen_sw_bridge_to_combridge.md`
