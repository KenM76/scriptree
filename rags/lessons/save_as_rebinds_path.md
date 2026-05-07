---
topic: v3-architecture
date: 2026-05-07
status: pattern
related: []
---
# Save-As re-binds the in-memory file path *before* writing

## What happened / rule

Adding **File → Save tree as...** to the V1 editor: the
existing `_save_tree` writes to `self._tree_file` and prompts
only when it's `None`.  A naive "Save As" implementation that
just calls the prompt-then-write code path twice produces a
file at the right name but leaves `self._tree_file` pointing
at the old path — subsequent Ctrl+S writes back to the
original.

The fix: in the public `save_as()` entry point, **prompt for
a path, set `self._tree_file = Path(new_path).resolve()`,
then delegate to the existing save**.  The save sees a non-
None tree-file and writes there directly; subsequent saves
also follow the new path.

## Recipe

```python
def save_as(self) -> bool:
    if self._tree is None:
        return False
    if getattr(self, "_tree_read_only", False):
        QMessageBox.warning(self, "Read-only", "...")
        return False
    path = self._ask_save_path()
    if not path:
        return False
    # Re-bind BEFORE delegating — that's what makes this
    # different from a fresh save with no path set.
    self._tree_file = Path(path).resolve()
    # Re-check write access against the new path.  A read-only
    # source tree saved-as into a writable folder must become
    # editable; vice-versa for the other direction.
    from ..core.permissions import check_write_access
    access = check_write_access(self._tree_file)
    self._tree_read_only = not access.fully_writable
    return self._save_tree()
```

The same pattern applies to `ToolEditorView` — but that
class already has a working `_on_save_as` that follows the
recipe.  We only added a public `save_as()` wrapper on
`ToolEditorView` so the main window can call it from a menu
without reaching into a private method.

## Read-only flag on the new path

A subtle gotcha: `_tree_read_only` is computed once at load
time from the original file's permissions.  Save-As to a
writable folder needs to refresh that flag, otherwise the
launcher still thinks it's editing read-only and blocks the
Save button.  Always re-run `check_write_access` after a
re-bind.

## How future-me detects it

If after Save-As, Ctrl+S still writes to the original path,
the re-bind is missing or happens after the save.  If after
Save-As, the editor refuses further edits, the read-only
flag wasn't refreshed.
