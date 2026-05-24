---
topic: v3-architecture
date: 2026-05-23
status: pattern
related: [master_cells_no_catalog_path, ring_auto_name_session_serial]
---
# Forest popup menu populates rings recursively — masters without catalogs are sub-menus, not skipped

## What happened

Bug 9 (v0.8.0a1): after fixing Bug 8 (skip members without
`_catalog_path` during menu population, on the theory that a master
has no catalog and should not appear as a leaf), the forest popup
menu stopped showing rings entirely. Rings are masters → no
catalog → skipped → invisible.

## Root cause

The Bug 8 fix was too aggressive. The original problem was: a master
appearing as a leaf entry would show "Cell master XX (no catalog
bound)" which is meaningless to the user. The fix dropped them
entirely. But rings ARE the relevant thing for the forest's menu —
they shouldn't be leaves, but they shouldn't be invisible either.
They should be **sub-menus** that expand into their own members.

## Fix / recipe

New recursive helper `_populate_menu_from_member` (depth-capped at
8 to avoid pathological loops):

```python
def _populate_menu_from_member(menu: QMenu, member, *, depth: int = 0) -> None:
    if depth > 8:
        return
    if not member.is_master():
        # Leaf cell with a catalog — single action
        if member._catalog_path:
            menu.addAction(_popup_header_text(member),
                           lambda m=member: launch_member(m))
        return
    # Master — make a sub-menu and recurse
    sub = menu.addMenu(_popup_header_text(member))
    if not member._members:
        empty = sub.addAction("(empty)")
        empty.setEnabled(False)
        return
    for mid in member._members.keys():
        child = registry.get(mid)
        if child is not None:
            _populate_menu_from_member(sub, child, depth=depth + 1)
```

The master's sub-menu title comes from `_popup_header_text(member)`
which, for rings, falls through to `_auto_ring_name` ("Ring 3" etc.)
— see `ring_auto_name_session_serial.md`. Empty masters get an
italic "(empty)" hint so the user sees the master exists but has no
contents.

## Wiring

`tree_popup.show_tree_popup_for` master path calls
`_populate_menu_from_member` for each top-level member rather than
walking once and dropping non-catalog entries.

## How future-me detects it

* "The forest menu has no rings in it" — most likely a non-recursive
  walk that filters `not _catalog_path`. Switch to the recursive
  helper above.
* Right-clicking the forest shows a sub-menu titled "Cell master
  XX (no catalog bound)" — `_popup_header_text` fall-through to
  `_auto_ring_name` is broken; check the order of the title-source
  chain (`_catalog_path` → `_text_label` → `_auto_ring_name`).
* If the menu recurses infinitely, the depth cap (8) didn't catch
  it — probably a self-referencing master. Check whether
  `_members` contains the master's own id (it shouldn't).
