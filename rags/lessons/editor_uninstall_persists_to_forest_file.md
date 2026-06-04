---
topic: v3-architecture
date: 2026-06-04
status: recipe
related: [merged_tree_pushback_to_origins, merged_tree_dropped_origins_vs_skipped, editor_forest_sync_via_forest_file, uninstall_keep_remove_flags_with_backup]
---
# Editor-side uninstall must persist to the on-disk forest file

## What happened

V1's editor (the developer-facing `MainWindow`) and the running
forest are two SEPARATE PROCESSES — the forest spawns the editor as
a subprocess to edit catalogs. When the editor performs an uninstall
(or implicitly drops a forest member by removing its top-level
folder from a merged-tree edit), it cannot notify the running
forest via in-process signals. The running forest's in-memory state
gets out of sync with what the user expects, and on next relaunch
the dropped catalog reappears from the still-stale forest file.

## Root cause

The editor and forest don't share Qt signal/slot connections. The
only shared state that survives a forest relaunch is the on-disk
`.scriptreeforest` file (the per-user autoload). Whatever the
editor does that should affect forest membership has to write to
THAT file or the change is lost.

## Fix / recipe

`MainWindow._persist_uninstall_to_forest_file(catalog_path)`,
introduced in v0.8.0a35 and extended in v0.8.0a37:

1. Resolve the per-user forest file via
   `forest_io.default_autoload_path()`.
2. Load the forest JSON; remove any entry from `items` whose
   `catalog` resolves to `catalog_path`.
3. Append the path to the forest's `excluded` list so the forest
   won't re-discover and re-add the catalog on next launch.
4. Save the forest file back. Best-effort: wrap in try/except and
   log on failure — never block the editor's main action on this
   persistence step.

Call sites:

- `MainWindow._on_tree_uninstall_requested` — explicit uninstall
  triggered from a right-click "Uninstall app..." action.
- `MainWindow._save_tree` after a merged-tree push-back returns
  `dropped_origins` (see related lesson
  `merged_tree_dropped_origins_vs_skipped`) — user implicitly
  removed a top-level folder.

## How future-me detects it

- Symptom: user uninstalls / removes a catalog in the editor, the
  editor closes cleanly, but on next launch the catalog reappears
  in the forest. Check whether the action plumbed through the
  forest-file persist helper, or only updated the editor's in-
  memory model.
- Any new editor surface that should affect forest membership
  MUST call `_persist_uninstall_to_forest_file` (or follow the same
  shape). In-memory state alone is insufficient.
- Treat the `.scriptreeforest` file as the IPC channel between
  editor and forest. There is no other.
