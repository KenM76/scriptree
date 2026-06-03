---
topic: v3-architecture
date: 2026-06-03
status: recipe
related: [qmenu_per_action_right_click, controller_api_cell_or_path]
---
# Popup-tree actions need root_catalog_path, not leaf catalog path

## What happened

Wiring "Uninstall app..." from a popup-tree right-click required
the action handler to know "which app folder owns this tool?" The
intuitive answer is "the directory of the leaf's `.scriptree`
catalog" — but for a `.scriptreetree`, leaves live in
sub-directories under the tree's root and the install-root isn't
necessarily a parent of them. Keying uninstall to the per-leaf
catalog path therefore picked the wrong (or no) app folder.

## Root cause

A `.scriptreetree` is a *catalog of catalogs*: the tree file lives
at the install root, but each leaf inside it can reference a
`.scriptree` under any subfolder. The semantic question "what app
does this leaf belong to?" is answered by the **root catalog** — the
file the popup menu was originally built from — not by the leaf's
own catalog path.

For a single-tool `.scriptree` cell, the root catalog IS the leaf —
they're the same file. For a tree-cell with N leaves, all N leaves
share the same `root_catalog_path`, pointing at the `.scriptreetree`.

## Fix / recipe

`_add_node_to_menu` and `_build_menu_for_catalog` in
`D:\Dev\ScripTree\scriptree\shell\tree_popup.py` thread BOTH paths
through the build:

- `source_dir` — for resolving relative paths (icon files, child
  catalogs) when building the menu visuals.
- `root_catalog` — the catalog FILE the menu was built from, stamped
  onto every action's per-item context as
  `act._st_context["root_catalog_path"]`.

```python
def _build_menu_for_catalog(catalog_path, source_dir, *, root_catalog):
    # root_catalog is invariant across recursion into a tree's leaves
    ...
    for leaf in iter_leaves(catalog_path):
        act = menu.addAction(...)
        act._st_context = {
            "leaf_path": str(leaf.path),
            "root_catalog_path": str(root_catalog),
            "source_dir": str(source_dir),
            "kind": "tool",
        }
```

For a `.scriptree` cell, the caller passes `root_catalog=leaf_path`
so the invariant holds (root == leaf for that case).

The uninstall handler then asks "what folder?" via
`Path(act._st_context["root_catalog_path"]).parent` — that IS the
app folder, regardless of how deeply the leaf is nested inside a
tree.

Pinned by
`D:\Dev\ScripTree\tests\test_tree_popup_per_item_context.py::TestActionContextStamping`
(2 cases — `.scriptree` and `.scriptreetree`).

## How future-me detects it

* Symptom: a popup-tree action does the wrong thing for tree-cells
  (e.g., picks a subfolder as the app dir instead of the install
  root). Check whether the handler is using `leaf_path` vs
  `root_catalog_path` — for "what app does this belong to?", it
  must be the root.
* Any new per-action operation that depends on app identity needs
  `root_catalog_path` stamped into `_st_context` at menu-build time.
  Don't compute it at click time — by then the leaf path is all you
  have and you've lost the original catalog identity.
