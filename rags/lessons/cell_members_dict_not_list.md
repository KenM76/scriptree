---
topic: v3-architecture
date: 2026-05-07
status: gotcha
related: [master_cells_no_catalog_path]
---
# `CellWindow._members` is `dict[member_id, QPoint]`, not a list of windows

## What happened

`merged_tree.build_merged_tree_for_master` and
`tree_popup.show_tree_popup_for` both iterated `self._members`
expecting `CellWindow` objects, then called
`m._catalog_path` on each.  Result: `AttributeError` on
strings, caught silently → empty merged tree, no popup.
Bug fixed in v0.2.3.

## Root cause

`_members` on a master cell is a `dict[member_id: str,
QPoint]` mapping member IDs to their docked offset positions
— NOT a list of `CellWindow` instances.  Iterating directly
hands you the string keys.

## Fix / recipe

Iterate keys and look each up via the registry:

```python
# scriptree/shell/merged_tree.py:build_merged_tree_for_master
from scriptree.shell.cell_registry import CellRegistry

reg = CellRegistry.instance()
for member_id in master._members.keys():
    member = reg.get(member_id)
    if member is None or member._catalog_path is None:
        continue
    # ... merge member's catalog into the tree
```

Same pattern in `tree_popup.show_tree_popup_for`.

## How future-me detects it

A master cell silently produces an empty merged tree, or
its right-click popup is empty even though members are
docked.  `print(type(next(iter(master._members))))` will
show `<class 'str'>` confirming the iterator gives keys, not
windows.
