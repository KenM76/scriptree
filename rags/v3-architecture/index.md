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
