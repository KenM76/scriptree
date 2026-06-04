---
topic: v3-architecture
date: 2026-06-04
status: recipe
related: [merged_tree_pushback_to_origins, editor_uninstall_persists_to_forest_file, uninstall_keep_remove_flags_with_backup]
---
# Merged-tree push-back: dropped origins ≠ skipped ≠ errors

## What happened

The first cut of `PushBackResult` (v0.8.0a31) had two outcome lists:
`written` (source written successfully) and `errors` (write
attempted, raised). That collapsed two genuinely different states
into "errors": a `.scriptree` single-tool source that can't be
written because the wrapper-folder has no analog, and a top-level
folder the user DELETED in the merged tree. The first is benign,
the second should DROP the forest's membership of that source.

## Root cause

The merged tree can lose top-level folders in three distinct ways
during an edit pass, and each needs different handling on save:

| Case | What it means | What to do |
|---|---|---|
| Folder present, write succeeds | Normal edit | Record in `written` |
| Folder present, write declined | Source can't accept this content shape (e.g. `.scriptree` wrapper) | Record in `skipped` |
| Folder present, write raised | I/O error, malformed source, etc. | Record in `errors` |
| Folder absent in saved tree, sidecar lists it | User deleted the top-level folder | Record in `dropped_origins` — forest should exclude this source |

## Fix / recipe

`PushBackResult` (v0.8.0a37, in
`D:\Dev\ScripTree\scriptree\shell\merged_tree.py`) carries four
lists:

```python
@dataclass
class PushBackResult:
    written: list[Path]          # sources successfully updated
    skipped: list[Path]          # sources present but write declined
    errors: list[tuple[Path, Exception]]  # sources that raised
    dropped_origins: list[Path]  # sources the user removed
```

Crucially, `dropped_origins` does NOT modify the source file. The
source `.scriptreetree` stays on disk as-is — only the forest's
MEMBERSHIP of that source is dropped (via
`_persist_uninstall_to_forest_file`, see related lesson
`editor_uninstall_persists_to_forest_file`). The explicit
`ForestController.uninstall_app` path is what actually DELETES the
source files; merged-tree drop is gentler.

Pinned by
`D:\Dev\ScripTree\tests\test_dropped_origins_a37.py` (4 cases:
detect dropped origin, persist exclusion, don't touch source file,
distinguish from skipped).

## How future-me detects it

- Symptom: user removes a top-level folder in the editor-as-forest
  view, the editor saves cleanly, but on relaunch the forest still
  shows the dropped source. Check whether `_save_tree` is
  consuming `result.dropped_origins` and calling the forest-file
  persist helper for each one.
- New PushBackResult callers MUST handle all four categories —
  don't fall through to a single "if errors:" branch.
- If a user-reported issue sounds like "I removed it but it came
  back," it's almost certainly a missed `dropped_origins` handler.
