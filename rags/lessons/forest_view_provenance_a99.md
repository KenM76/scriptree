# Provenance-visible forest view: linked subtrees, not a flattened merge (a99)

**Tag:** [v3-architecture] [editor] [ui]
**Version:** v0.8.0a99
**Files:** `scriptree/shell/merged_tree.py` (`build_forest_view`,
`build_forest_view_for_master`, `_FOREST_VIEW_PREFIX` + sweep);
`scriptree/ui/main_window.py` (`_open_forest`); `scriptree/shell/tree_popup.py`
(`_open_full_editor_for` master branch); `scriptree/ui/tree_view.py`
(`_new_folder_item` / `_new_subtree_item` provenance tooltips).
**Tests:** `tests/test_forest_view_a99.py` (5), `tests/test_open_forest_a97.py`.

## The problem (user: "I can't tell what's what")

Opening a forest in the editor used `merged_tree.build_merged_tree`, which
**flattens** every member: it loads each member tree, INLINES its subtree refs,
and wraps it as an anonymous top-level FOLDER.  Provenance (which file backs a
folder) was hidden in a side `_origins` sidecar — invisible in the UI.  So a
"folder" could be an in-memory folder, a linked `.scriptreetree`, or a
synthesised `_groups` category group, and hovering told you nothing.

## The fix — render members as LINKED SUBTREES, not a merge

`build_forest_view(catalog_paths, forest_name)` builds a temp `.scriptreetree`
whose top-level nodes are **bare leaves carrying each member's absolute catalog
path** — NO inlining, NO folder-wrapping, NO origins sidecar.  The editor's
existing `_add_node_item` then routes a `.scriptreetree` leaf to a SUBTREE item
(expandable, file tooltip, read-only children) and a `.scriptree` leaf to a tool
item — so file provenance is shown for free, and editing a member is done in the
member's OWN file (right-click → Open today; inline edit + drag-to-recategorize
is a100).

Wired into BOTH open paths:
* **File→Open** (`MainWindow._open_forest`) — same process, `_launcher.load`.
* **Cell hub double-click** (`tree_popup._open_full_editor_for`) — separate
  editor process via `launch_editor_with_tree`, so it MUST write a temp file
  (can't pass an in-memory TreeDef across the process boundary); hence
  `build_forest_view_for_master` returns a temp path like `build_merged_tree_*`.

## Two gotchas that shaped the design

1. **Gate the cell-hub rewire on `_is_forest_master`.**  A forest hub and a ring
   master share `role == "master"`; only the forest hub has
   `_is_forest_master=True`.  Rings still use the flattened `build_merged_tree`
   (with its origins-sidecar save-back) — switching them too would be an
   unrequested regression to ring editing.  So: forest hub → `build_forest_view`,
   ring master → `build_merged_tree` (unchanged).
2. **Provenance tooltips per row kind** (`tree_view`): in-memory folder →
   "Folder — organises tools within this tree (no separate file)"; linked
   subtree → "Linked tree: `<path>`"; synthesised group (path under `_groups/`)
   → "Auto-group · category 'X' — built from tools' Category fields … this file
   is regenerated, not edited directly".  Detect synth by `"_groups" in
   Path(p).parts` (NOT a `synthesised_by` TreeDef field — that JSON marker is
   dropped by `load_tree`, which has no such field).

## Why this is better than the merge

* File provenance is visible; the three "folder" kinds are distinguishable.
* No `_origins` sidecar, no back-propagation complexity, no flattening.
* Editing routes to the member's own file (a subtree's children come from that
  file), which is the correct source of truth — and sets up a100's inline edit +
  drag-to-recategorize (move a tool between auto-group folders → rewrite the
  tool's `category`).

## Reusable takeaways

1. **A "merge into one editable doc" view destroys provenance; a "linked
   references" view preserves it.**  When the user needs to know *which file*
   backs each row, don't flatten — reference.
2. **Across a process boundary you can't pass an in-memory model** — the
   separate editor process needs a temp file; keep a distinct temp prefix
   (`scriptreeforest_view_`) and add it to the existing janitor sweep.
3. **Shared role ⇒ gate on the distinguishing flag.**  `role=="master"` covers
   forest hubs AND rings; `_is_forest_master` is the discriminator that keeps the
   rewire from regressing the other case.
4. Builds on [[groups_discovery_feedback_loop_a98]] (the `_groups` fix) and
   [[uncategorised_wrapper_tree_floats_to_top_a94]] (category-as-source-of-truth);
   sets up a100 edit routing.
