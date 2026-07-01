# Forest editor: circular `_groups` ref via merged-tree push-back; double-click dispatch gaps (a100)

**Tag:** [v3-architecture] [editor] [merged-tree] [data-loss]
**Version:** v0.8.0a100
**Files:** `scriptree/shell/merged_tree.py` (`push_back_to_origins` guard,
`_refs_groups_tree`, `_strip_groups_tree_refs`); `scriptree/shell/v1_launcher.py`
(`show_composite_for`); `scriptree/ui/tree_view.py` (`openTreeRequested`,
subtree "Open in editor", `_emit_open_tree_for`); `scriptree/ui/main_window.py`
(signal wiring).
**Tests:** `tests/test_edit_routing_a100.py` (4). Adversarial review: 0 findings.
**Builds on / supersedes the gap in:** [[groups_discovery_feedback_loop_a98]]
(a98 fixed the READ side; this is the WRITE side), [[forest_view_provenance_a99]].

## Two bugs the user hit after a98/a99 (both real gaps in my own work)

### Bug A — circular `Demo ⊃ ./MSOffice.scriptreetree` recurs on reorganize

a98 stopped the discovery feedback loop, but the duplicate/circular came BACK.
Empirical smoking gun: the regenerated `_groups/Demo.scriptreetree` contained a
leaf `./MSOffice.scriptreetree` (a sibling group) — and that path was **relative
(`./`)**, while `categorize.group_by_category` only ever writes **absolute** leaf
paths and never cross-references groups. So the leaf was injected by a **save /
write-back path**, not the synthesis. a98 guards the read/discover/group side; it
**cannot** stop a write.

Root cause (root-caused + reproduced): the forest hub opened in the editor via
the **flattened merged path** (`build_merged_tree_for_master` →
`build_merged_tree` → `_inline_subtree_refs`). With a `_groups` group tree as a
forest member, inlining nested one group inside another; on **Save →
`merged_tree.push_back_to_origins`**, each top-level folder's children are
written back to its origin file, and `_restore_relative_leaf_paths` relativised
the sibling group path to `./MSOffice.scriptreetree`. Self-perpetuating; the seed
is a position-vs-name origin-matching desync in push-back when folders are
reordered.

### Bug B — "can't right-click and edit; looks like previous versions"

Three dispatch/menu gaps meant the a99 provenance view + editing were unreachable:
1. Forest-hub **double-LEFT-click → a popup MENU** (`cell_window` →
   `show_tree_popup_for`), not an editor.
2. Forest-hub **double-RIGHT-click → `v1_launcher.show_composite_for`**, which
   built the **flattened merge unconditionally** (never checked
   `_is_forest_master`). a99 had only rewired `_open_full_editor_for` (the popup
   □ button), so the common gestures still got the old flattened view.
3. A linked-**subtree** row's right-click menu had **no "open in editor"** action
   (the "Edit" action is gated to leaves), so even in the provenance view you
   couldn't open the underlying `.scriptreetree` to set its Category.

## The fixes (a100)

* **(A) Forest hubs never take the merged/push-back path.**
  `v1_launcher.show_composite_for` now branches on `_is_forest_master` →
  `build_forest_view_for_master` (provenance view, no inlining, no push-back);
  ring masters keep `build_merged_tree_for_master`. This removes the corrupting
  path for forests AND gives double-right the provenance view.
* **(B) Defensive push-back guard.** Before writing an origin, if the source is
  under `_groups`, strip any `.scriptreetree` leaf child (recursively) — a
  synthesised group's legitimate children are tool (`.scriptree`) leaves only, so
  any tree leaf is a bogus sibling-group ref. Gated on `_groups`, so ring
  origins' legitimate subtree members are untouched. Protects every push-back
  path, not just forests.
* **(C) Subtree "Open in editor".** New `openTreeRequested(str)` signal +
  subtree-only menu action → `main_window._load_file_into_ui(path)` loads the
  linked `.scriptreetree` as the editable root, so the user can set its
  Category/properties and Save.

## Reusable takeaways

1. **A guard on the READ axis does nothing for corruption written on the WRITE
   axis.** a98 (discovery skip) and this bug (push-back write) are different
   pipelines over the same `_groups` files; a `relative` path in
   supposedly-synthesised output is the tell that a *save* path, not the
   generator, produced it.
2. **Wiring one of several entry points isn't "done".** a99 rewired the □-button
   editor path but not `show_composite_for` (double-right) — the user's actual
   gesture. Enumerate ALL gestures that reach a behavior (grep every caller).
3. **A merged/back-propagating view must never ingest a regenerated artifact as
   a member.** Treat `_groups` group trees as provenance leaves (forest view),
   never as merge members with push-back.
4. **Investigation hygiene:** the first investigation agent returned a placeholder
   stub (`root_cause: "test"`); always sanity-check agent output, and re-run with
   a concrete empirical clue (here, the exact corrupted file + the relative-vs-
   absolute insight) when the first pass is hollow.

## Still pending (the bigger a100/a101 scope)

Drag-to-recategorize (move a tool between auto-group folders → rewrite its
`category`) and inline edit-in-place of linked subtrees + save-to-owning-file.
These MUTATE source files and must get the adversarial review before shipping
(per the user). This a100 only fixed the two regressions + added "Open in
editor"; it did NOT add drag-to-recategorize.
