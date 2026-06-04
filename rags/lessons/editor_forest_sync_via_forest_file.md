---
topic: v3-architecture
date: 2026-06-04
status: recipe
related: [editor_uninstall_persists_to_forest_file, merged_tree_pushback_to_origins, merged_tree_dropped_origins_vs_skipped]
---
# Editor↔forest cross-process sync goes through the .scriptreeforest file

## What happened

Throughout v0.8.0a31–a37 a recurring class of bug surfaced: the
user does something in the editor that should change the running
forest's membership (uninstall, drop a top-level folder, remove a
catalog), the editor reports success, but the running forest is
unaffected and on next launch the change is partially or fully
reverted. The editor's window had updated; the forest's hadn't.

## Root cause

The editor and the forest run in TWO SEPARATE PROCESSES. The
forest's `CellWindow` lives inside `ring_main.py`'s QApplication;
the editor is launched by `v1_launcher` as a subprocess. They share
no Qt signals, no Python globals, no in-memory state. The only
shared persistent state is the per-user `.scriptreeforest` file on
disk.

Naive solutions like "in-process signal" or "callback" don't apply
— different processes, different address spaces. The only IPC
channel actually available is the forest file, mediated by file
I/O.

## Fix / recipe

The persist-to-forest-file pattern (see related lesson
`editor_uninstall_persists_to_forest_file`) is the established
recipe. Every editor-side action that should affect forest
membership MUST:

1. Resolve the per-user autoload via
   `forest_io.default_autoload_path()`.
2. Load → mutate (remove from `items`, append to `excluded`, etc.)
   → save.
3. Wrap in try/except; log on failure rather than blocking the
   editor's main action.

For OTHER kinds of forest-mutating editor surfaces that may be
added in future (e.g. drag-reorder a member, rename a catalog
reference, change a forest-level setting from the editor), the
same pattern applies: write the change to `.scriptreeforest`
ahead of returning success.

There is currently no facility for the running forest to detect
the file change live (no file-watch). The contract is: the editor
writes to the file, the user relaunches or refreshes the forest,
the new state takes effect. If a true live-update channel is ever
needed, a QFileSystemWatcher on the forest file is the obvious
next step — but as of v0.8.0a39 the editor and forest are
explicitly serialised: edit closed → forest reloaded.

## How future-me detects it

- Symptom: a new editor feature that "should" affect the forest
  works in the editor's own session but doesn't survive a forest
  relaunch. Almost certainly missing a write to the forest file.
- Whenever adding an editor surface, ask: "does this affect forest
  membership or forest-level state?" If yes, plumb a write to
  `.scriptreeforest` before returning. The editor's in-memory
  model is never sufficient on its own.
- The persist helper at
  `MainWindow._persist_uninstall_to_forest_file` is the canonical
  template — new persist helpers should follow its shape
  (best-effort, logged, never blocks the main action).
