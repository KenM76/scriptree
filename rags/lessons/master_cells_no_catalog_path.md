---
topic: v3-architecture
date: 2026-05-07
status: gotcha
related: [cell_members_dict_not_list]
---
# Master cells have no `_catalog_path` of their own

## What happened

Right-double-click on a master cell did nothing useful — the
fallback path `launch_editor_blank()` fired, opening an empty
V1 editor instead of the merged tree popup that should have
appeared.

## Root cause

A master cell aggregates its members.  It does not own a
`.scriptree` / `.scriptreetree` catalog; its `_catalog_path`
is `None`.  `show_tree_for(mode="lock-open")` checks
`_catalog_path` and falls through to "blank editor" when it's
None — correct behaviour for an unbound cell, wrong for a
master.

## Fix / recipe

Route master double-right through `show_composite_for(master)`
instead, which detects masterhood and builds the merged tree
on demand:

```python
# scriptree/shell/cell_window.py
def _on_double_right_click(self):
    if self.is_master():
        from scriptree.shell.tree_popup import show_composite_for
        show_composite_for(self)
        return
    # leaf cell: existing path
    show_tree_for(self, mode="lock-open")
```

`show_composite_for` walks `_members.keys()`, looks up each
via `CellRegistry`, and calls `build_merged_tree_for_master`
to assemble the tree on the fly.

## How future-me detects it

Right-double-click on a master opens an unrelated editor
window or does nothing.  Stick a `print(self.is_master(),
self._catalog_path)` at the top of the click handler — a
master will be `(True, None)`.
