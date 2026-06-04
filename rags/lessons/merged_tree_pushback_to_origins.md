---
topic: v3-architecture
date: 2026-06-04
status: recipe
related: [editor_uninstall_persists_to_forest_file, merged_tree_dropped_origins_vs_skipped, merged_tree_inline_subtrees_at_build_time, merged_tree_dedup_by_name_with_disambiguation]
---
# Merged-tree edits push back to their origin catalogs via a sidecar map

## What happened

When V3's forest opens in V1's editor, the editor doesn't see the
forest directly — it sees a MERGED TREE, a synthetic
`.scriptreetree` that aggregates every forest member's catalog into
one tree. Pre-v0.8.0a31 the editor's save wrote that merged file
back to disk verbatim — to a temp path with no relationship to any
real source. The user's edits never reached the originating
`.scriptreetree` / `.scriptree` files. The merged tree was effectively
a read-only view that pretended to be editable.

## Root cause

The merged-tree builder collapsed N source catalogs into one
in-memory tree, then serialised that tree to a temp file. The
provenance of each top-level folder (which source file it came
from, what leaf paths were originally relative to) was discarded
during the merge — there was nowhere for the editor's save to look
up "which file does THIS folder belong to?"

## Fix / recipe

A sidecar JSON file rides alongside every merged tree, mapping each
top-level folder name to its source path:

- `<merged>.scriptreetree.origins.json` — written by the merge
  builder at build time, structure
  `{ "folder_name": "absolute/source/path.scriptreetree", ... }`.
- `merged_tree.is_merged_tree(path)` — heuristic + sidecar-exists
  check; the editor's save logic branches on this.
- `merged_tree.push_back_to_origins(merged_path) -> PushBackResult`
  — walks the saved merged tree, splits it by top-level folder, and
  writes each folder back to its sidecar-recorded source path.

Two non-trivial details inside `push_back_to_origins`:

1. **Leaf path convention conversion.** Merged trees use absolute
   leaf paths (cross-source aggregation needs absolutes). Source
   catalogs use leaf paths relative to the catalog's own dir.
   `_restore_relative_leaf_paths` rewrites each leaf back to
   relative-to-origin before serialising.
2. **`.scriptree` single-tool sources are SKIPPED.** A `.scriptree`
   describes one tool — there's no wrapper-folder analog. When the
   sidecar entry points at a `.scriptree`, the push-back skips it
   cleanly (records in `skipped`, not `errors`).

Code lives in
`D:\Dev\ScripTree\scriptree\shell\merged_tree.py` — search for
`push_back_to_origins`, `_origins_sidecar_path`, and
`_restore_relative_leaf_paths`.

Pinned by
`D:\Dev\ScripTree\tests\test_merged_tree_pushback.py` (8 cases
covering happy path, missing-sidecar, `.scriptree` skip, leaf path
relativisation, multi-source dispatch, and errors).

## How future-me detects it

- Symptom: edits the user makes to a forest-in-editor "vanish" after
  closing the editor and re-opening the forest. Check whether the
  saved merged tree is being pushed back to origins (via the
  `MainWindow._save_tree` branch on `is_merged_tree`), or being
  written only to its temp path.
- Any new editor surface that saves a `.scriptreetree` needs to ask
  "is this a merged tree?" first and branch on the answer.
- The sidecar JSON is the source of truth for which folder maps to
  which file — don't try to reconstruct provenance from the tree
  contents.
