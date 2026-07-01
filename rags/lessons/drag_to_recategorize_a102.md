# Drag-to-recategorize: edit a synthesised group's layout → rewrite tool categories (a102)

**Tag:** [v3-architecture] [editor] [data-mutation]
**Version:** v0.8.0a102
**Files:** `scriptree/ui/tree_view.py` (`_is_synthesised_group`,
`_recategorize_tools_from_layout`, `_original_member_paths`, `_save_tree`
synthesised-group branch).
**Tests:** `tests/test_recategorize_a102.py` (6). Adversarial review: 4 findings,
all fixed.

## What it does

A synthesised auto-group (`_groups/<Top>.scriptreetree`) is REGENERATED from tool
`category` fields, so writing the group file from the editor is futile (the next
Re-organise overwrites it). a102: when the user opens such a group (right-click a
linked-tree row → **Open in editor**), rearranges tools among its sub-folders, and
**Saves**, ScripTree instead **re-files each member by its folder POSITION into the
member's own `category`** — the source of truth. A tool now under `MSOffice →
Excel` gets `category: "MSOffice/Excel"`; directly under the root gets
`"MSOffice"`. Re-organise then rebuilds the group from those categories.

Mechanism: detect via `"_groups" in Path(self._tree_file).resolve().parts`; walk
the a96 root row (prefix `[top]`, folders append their name); for each leaf/subtree
member, **targeted JSON edit** — read the `.scriptree`/`.scriptreetree`, change ONLY
the `category` key, preserve everything else. Only members whose category actually
changes are written.

## Four findings a 2-lens adversarial review caught (all fixed)

1. **(MED) Removing a member was silently lost AND reported as success.**
   `_remove_selected` is a widget-only op — it never touched the member's file —
   so a removed tool's category still pointed into the group and it **reappeared
   on the next Re-organise**, while the dialog said "success". Fix: capture the
   originally-loaded member paths (`_original_member_paths`, from `self._tree`),
   and on save **clear the `category`** of any member no longer in the layout — so
   removing a tool from the group actually takes it out (→ uncategorised → top
   level).
2. **(MED) New empty folders vanish on regeneration.** Folders exist only because
   some member's category records the segment — an empty folder has no member, so
   it's dropped. Inherent to the regenerate-from-categories model. Fix: **surface
   it** — the save dialog now states the group is rebuilt from tool categories and
   empty folders aren't kept (don't silently imply they're saved).
3. **(LOW) Un-normalised stored category caused needless churn + inflated count.**
   `old` was the raw on-disk string; a tool stored `"MSOffice/Word/"` is the SAME
   position as `"MSOffice/Word"` but `old != new` triggered a rewrite. Fix:
   compare `_normalise_category(old) == _normalise_category(new)` — grouping feeds
   on the normalised value, so only genuine moves are written/counted.
4. **(LOW) A folder inline-renamed to contain `/` broke the round-trip.** Folder
   rows are editable; renaming one to `"A/B"` produced category `"Top/A/B"`, which
   the next synth pass splits into two nested folders `A → B`. Fix: **scrub path
   separators** from each folder segment (`_seg`, mirroring
   `categorize._safe_stem`) before building the category, so the inversion exactly
   inverts the synthesis.

(One claim — non-atomic `write_text` — was REJECTED: it matches the established
project-wide convention for writing catalog files; not an a102 defect.)

## Scope (and what's deliberately NOT here)

a102 = drag-to-recategorize only — the user's explicit "edit folder location →
update Category" ask. True **inline** editing of a linked subtree's CONTENTS in
place (write-back per-subtree) is NOT here; the **Open in editor** path (a100)
already opens any linked tree as an editable root, so that capability exists.

## Reusable takeaways

1. **A view over a DERIVED artifact must translate edits to the SOURCE of truth,
   not the artifact.** The synthesised group file is derived from tool categories;
   editing it is futile, so the save re-expresses the layout as categories.
2. **Honest feedback beats silent partial success.** Removal and empty-folder
   edits don't fully round-trip through a regenerated structure — make the dialog
   say so (and make removal actually stick) rather than reporting blanket success.
3. **Compare NORMALISED forms when the downstream consumer normalises.** Raw-string
   equality over-rewrites and miscounts.
4. **When a layout segment becomes a category segment, scrub the separator** — an
   editable folder name can smuggle a `/` that explodes into extra nesting.
5. Builds on [[forest_view_provenance_a99]] (the provenance view that makes groups
   openable) and the category-as-source-of-truth principle in
   [[uncategorised_wrapper_tree_floats_to_top_a94]].
