---
topic: v3-architecture
date: 2026-06-04
status: recipe
related: [merged_tree_pushback_to_origins, merged_tree_dedup_by_name_with_disambiguation, recursive_merged_menu_population]
---
# Merged tree must inline subtree references at build time, not view time

## What happened

Pre-v0.8.0a36, when the merged tree (forest-in-editor) included a
leaf node pointing at another `.scriptreetree`, V1's tree-view
expanded that pointer INLINE at view time. The expanded contents
were marked read-only because they belonged to a different file
than the one being edited. Users who hit a catastrophic state
— cycles in subtree refs, duplicate folders, broken catalogs —
couldn't drag or delete the broken items to recover. The merged
tree was effectively a hostage to whatever its constituent sources
contained, with no escape hatch.

## Root cause

Two different layers were doing subtree-resolution at two different
times, with conflicting ownership semantics:

- The merged-tree BUILDER followed top-level catalog paths and
  emitted leaf pointers to them.
- The V1 tree VIEW, when rendering a leaf that pointed at a
  `.scriptreetree`, lazily expanded it inline at display time and
  marked those nodes read-only (different-file = not yours to
  edit).

The view-time expansion was the right choice for a normal editor
session (live link to the referenced file) but the wrong choice
for the merged tree, where the user needs full edit power over
everything visible.

## Fix / recipe

A new helper at the BUILDER layer:
`_inline_subtree_refs(node, visited)` recursively replaces every
subtree-pointing leaf with its loaded contents at BUILD time. The
merged TreeDef then owns those nodes outright — the editor can
drag, drop, and delete them freely. The view-time expansion path
sees plain nodes and does nothing special.

Cycle handling: a `visited` set is threaded through the recursion.
On cycle detection, the helper emits a placeholder folder with a
single "(circular reference)" inner node and stops recursing. This
mirrors the editor's view-time cycle guard at
`scriptree/shell/tree_view.py::_expand_subtree`.

Trade-off accepted: subtree refs were LIVE pre-a36 (re-opening
picked up changes to the referenced file). Post-a36 they are
STATIC — a snapshot taken at merged-tree build time. For the
forest-in-editor workflow this is the right trade: editing power
> live link.

Pinned by
`D:\Dev\ScripTree\tests\test_editor_unhappy_paths_a36.py` (case
covering inline expansion, cycle placeholder, and edit-write-back
through inlined nodes).

## How future-me detects it

- Symptom: in a forest-in-editor session, an item is greyed out /
  read-only when the user expects to be able to drag or delete it.
  Inspect whether it came from an inline-expanded subtree (post-
  a36 builder did its job) or whether the view-time path was hit
  (it shouldn't be for merged trees).
- Any new path that produces a `.scriptreetree` intended for edit
  needs the inline-subtree pass run on it at build time.
- The "(circular reference)" placeholder is the canonical signal
  of a cycle — preserve that text exactly so users searching docs
  for it find the right surface.
