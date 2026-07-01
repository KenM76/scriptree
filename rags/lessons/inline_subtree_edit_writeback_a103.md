# Inline subtree edit: write edits back to the referenced .scriptreetree (a103) — and the LOSSY-ROUND-TRIP data-loss class it exposed

**Tag:** [v3-architecture] [editor] [data-mutation] [adversarial-review]
**Version:** v0.8.0a103
**Files:** `scriptree/ui/tree_view.py` (`_expand_subtree`, `_store_node_metadata`,
`_add_node_item`, `_item_to_node`, `_icon_kwargs_from_item`, `_churn_key`,
`_write_back_subtrees`, `_write_one_subtree_if_changed`, `_is_legal_drop_target`,
`_on_file_dropped`, `_new_subtree_item`); roles `_ROLE_EXPAND_OK` (+5),
`_ROLE_ICON`/`_ROLE_ICON_DATA`/`_ROLE_ICON_FORMAT` (+6/+7/+8).
**Tests:** `tests/test_inline_subtree_edit_a103.py` (16) + updated
`tests/test_nested_trees.py::test_subtree_label_not_inline_editable_but_drop_enabled`.
**Review:** FIVE adversarial Workflow passes, finding rate **10 → 3 → 1 → 2 → (0)**.
Pass 1: 10/10 real (2 HIGH silent data-loss).  Pass 2 (verify-the-fix): 3 real —
2 NEW regressions FIX 1 introduced + 1 original not fully closed.  Pass 3: 1 real
(a drop hole one path deeper — Above/Below the placeholder).  Pass 4 (convergence,
*combining* topologies the per-pass fixtures never crossed): 2 real HIGH — (a) a
group opened AS ROOT never ran the write-back (early `return` before the call);
(b) the duplicate-row dedupe `continue` skipped RECURSION, losing an edit made
through a duplicate row's NESTED subtree.  Pass 5: closure check.  **Lesson: on
data-mutating code, review the FIXES too, and explicitly CROSS the feature's
independent dimensions (which root × which member × which drop indicator × how
many references) — every pass here surfaced a defect one combination deeper, and
several of the worst bugs were introduced BY a fix.**

## What the feature does

A linked-subtree row in the developer editor is expandable (`_expand_subtree`
loads the referenced `.scriptreetree`'s nodes as children, resolved against THAT
file's dir). a103 makes those children **editable in place** — drop a tool in
(internal drag or external Explorer drop onto the row), remove one, rename a
folder. On Save, `_write_back_subtrees` walks the tree and, per CHANGED subtree,
rewrites **that referenced file's** `nodes` (re-load + `dataclasses.replace`
keeps the file's top-level metadata; child leaf paths relativised against the
**subtree's own** dir). The parent tree still records the subtree as a one-line
leaf ref — children are never flattened/inlined (`_item_to_node` serialises a
subtree row as a leaf, never recursing).

Guards: skip if `_ROLE_EXPAND_OK` is not True (circular/load-error view — never
clobber an unreadable file); skip synthesised `_groups/` (regenerated from tool
categories by a98/a102 — owned by drag-to-recategorize); skip if unchanged.

## THE BIG LESSON — a lossy editor round-trip is BOTH a strip AND a churn engine

The first cut compared `existing.nodes == new_nodes` and trusted "real authored
files have no folder metadata, so the round-trip is exact." **That reasoning was
wrong**, and a 4-lens adversarial review (with empirical repros) proved it:

`_item_to_node` dropped, on serialize, **every** per-node field the item didn't
carry: `icon`/`icon_data`/`icon_format` (ALL node kinds), folder `display_name`,
and subtree-ref `configuration` (the `.scriptree` leaf branch carried
`configuration`; the `.scriptreetree` subtree branch did not). Because `TreeNode`
is a plain `@dataclass` (field-wise `__eq__`) and `io.py` round-trips all those
fields, **any** metadata-bearing subtree made `existing.nodes != new_nodes`. So:

1. **The unchanged-skip guard never fired** → the file was rewritten, and
2. **the rewrite dropped the metadata** → silent permanent data loss,

…on a plain **no-op Save** (subtrees auto-expand at parent-load, so
`_ROLE_EXPAND_OK=True` with zero user action). Reproduced: a subtree whose
folder had `display_name='Pretty Group'`+icon and whose leaf had its own icon
triplet lost all of it just by opening the parent and clicking Save.

**Takeaway: when a view re-serialises a model through a UI item, the item must
carry EVERY persisted field, or the diff is dishonest and the save is lossy. A
field-wise `==` over a lossy projection silently strips exactly the fields the
projection can't represent.** This was latent in the parent-tree save too
(pre-a103); a103 only made it bite a *referenced* file on a no-op save.

## The 10 findings → 4 fix clusters

**Cluster A — lossless round-trip (findings #1,#2,#4,#5,#6,#8; 2×HIGH).**
New icon roles + `_store_node_metadata(item,node)` (called for folder, subtree,
AND leaf branches of `_add_node_item`) carry display_name/configuration/icon
triplet onto every item; `_item_to_node` re-emits them for all three kinds
(`_icon_kwargs_from_item` helper). Now the round-trip is exact → no strip, and
the diff is honest. Bonus: fixes the pre-existing parent-save metadata loss.

**Cluster B — path-form false-diff (finding #3 HIGH, #7 MED).**
A subtree stores leaf paths bare (`update_lib.scriptree` — ScripTree's OWN
shipped management tree does this) or with backslashes; `load_tree` keeps the
on-disk string verbatim, but the editor re-serialises via `_maybe_relative` as
`./forward/slash`. Raw `==` saw a change → churned the file on every no-op Save.
Fix: module fn `_churn_key(node)` folds a leading `./` + normalises `\`→`/` on
leaf paths (recursing children, comparing every other field incl. the icon
triplet); the skip-guard compares `[_churn_key(n) …]` lists. Only a GENUINE
structural/metadata change writes; pure path-form differences are ignored and
the file keeps its original form.

**Finding #9 — duplicate rows clobber (LOW).** Same file referenced by two rows:
after editing one, `_visit` reached the other (stale) row, reloaded the
just-written file, saw a diff, and wrote the pre-edit content back — order
dependent. Fix: `written_keys: set` of RESOLVED subtree paths in `_visit`; a
duplicate row whose file was already written this pass is skipped (write AND
recursion). First row that actually changes the file wins; an unchanged first
row does NOT block a later edited duplicate (only WRITES add to the set).

**Finding #10 — drop onto failed-expand subtree → silent loss (HIGH).**
`_is_legal_drop_target` accepted OnItem drops onto ANY subtree, but write-back
skips non-`EXPAND_OK` subtrees AND the parent serialises the subtree as a
one-line ref (children not walked) → a tool dropped onto a broken subtree landed
in NEITHER file. Fix: both `_is_legal_drop_target` (internal drag) and
`_on_file_dropped` (external drop) require `_ROLE_EXPAND_OK is True` for a
subtree to be a drop container; otherwise the drop is refused (internal) or falls
through to a sibling-in-parent (external, so it's saved, not lost).

## Pass 2 & 3 — the fixes spawned their own bugs (review the fix!)

FIX 1 (carry folder `display_name` so it round-trips) introduced TWO new
regressions, both HIGH/MED, both silent:

* **Folder rename shadowed.** The editor showed a folder by its `name`, but
  carrying `display_name` meant an inline RENAME (which edits the label/`name`)
  left the old `display_name` in place; every consumer renders `display_name or
  name`, so the rename appeared to do nothing. Fix: the folder row now shows the
  EFFECTIVE label (`display_name or name or "(folder)"`), the authored `name`
  lives in `_ROLE_FOLDER_NAME`, and `_item_to_node` uses a **shown-baseline**
  test — if the row's text still equals `display_name or authored or "(folder)"`
  it's untouched (round-trip both); otherwise the user retyped it, so the text
  becomes the new `name` and the stale `display_name` is dropped (rename wins).
* **Empty-name folder churned + mutated.** `_new_folder_item(node.name or
  "(folder)")` made the placeholder the actual `item.text(0)`, so a `name=""`
  folder serialised as name `"(folder)"` AND false-diffed. Same shown-baseline
  fix recovers `""` from `_ROLE_FOLDER_NAME`.

And the FIX-4 drop gate had to be hardened THREE times as each pass found the
loss one path deeper: OnItem onto a subtree (pass 1) → external drop onto the
load-error PLACEHOLDER child (pass 2, `_nearest_drop_container` walks up past
it) → internal-drag Above/Below the placeholder, reparenting into the failed
subtree via `target.parent()` (pass 3). The durable fix is a **structural
backstop**: `dropEvent` runs `_rescue_strays_from_unwritable_subtrees()` on every
internal drop, moving any DRAGGABLE child (the placeholder stub is not draggable)
out of a non-`EXPAND_OK` subtree to its parent — so a node can't remain
serialised-to-no-file regardless of which gate path let it in.

Pass 4 (convergence) then crossed dimensions the per-pass fixtures never had:
* **Group-as-root never wrote back.** `_save_tree`'s a102 synthesised-group
  branch `return`s early, *before* the sole `_write_back_subtrees()` call — so
  inline-editing a non-group member subtree under a `_groups/` root reached no
  file. Fix: a shared `_persist_subtree_edits()` called on BOTH save paths.
* **Dedupe `continue` skipped recursion.** The duplicate-row guard skipped the
  whole row (write *and* recursion); a nested subtree edited only through a
  duplicate row was lost. Fix: gate only the WRITE on the resolved-path key,
  ALWAYS recurse (nested files de-dupe by their own key).

## Reusable takeaways

1. **A UI-item round-trip must be FIELD-COMPLETE before you diff on it.** Carry
   every persisted model field onto the item (icon triplet, display_name on
   folders, configuration on subtree refs), or `==` lies and the save strips.
2. **"Real files don't have field X" is not a safety argument — prove the
   round-trip with a metadata-bearing fixture.** The 8 first-cut tests passed
   because none carried icons/folder-display_name; the gap was invisible to them.
3. **Normalise the comparison to the dimension you don't own.** On-disk path FORM
   (`./`, `\`) is the file author's choice, not an edit — fold it out of the
   churn key so a no-op Save never rewrites a file (esp. our own shipped trees).
4. **A view over a derived/forwarded artifact must write the SOURCE, once.**
   De-dupe writes by resolved path so a duplicate row can't clobber an edit.
5. **Reconcile both ends of a gesture.** Accepting a drop (UI) and refusing the
   write-back (persistence) were each defensible but, unreconciled, produced
   silent loss — gate the drop on the same predicate the write-back uses.
6. **Adversarial review with EMPIRICAL repro earns its keep on data-mutating
   code.** Two passes (find→verify, then verify-the-fix) caught a 2×HIGH silent
   data-loss class the author had rationalised away. Pin agents to absolute
   `D:/Dev/ScripTree` paths — the worktree cwd was a stale a82 snapshot.
7. Builds on [[drag_to_recategorize_a102]] (the `_groups` skip + "write the
   source of truth, not the artifact" principle), [[forest_view_provenance_a99]]
   (the non-flattening linked-subtree view this edits), and
   [[forest_editor_circular_pushback_a100]] (the "Open in editor" path).
