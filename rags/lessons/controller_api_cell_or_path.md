---
topic: v3-process
date: 2026-06-03
status: workflow
related: [uninstall_keep_remove_flags_with_backup, popup_menu_root_catalog_path]
---
# Controller handlers should accept "cell OR path" so new call-sites get covered automatically

## What happened

`ForestController._on_uninstall_app` started life as a Forest-submenu
slot that received a `CellWindow`. When the popup-tree right-click
feature was added, the new call-site only had a path string (from
the QAction's `_st_context["root_catalog_path"]`). The lazy fix
would have been a second method,
`_on_uninstall_app_from_popup(path)`, that does the same thing —
duplicating dialog wiring, file enumeration, and the actual
uninstall call. The better fix is to make the existing handler
polymorphic on its input.

## Root cause

The handler's logic is independent of *how* the user got there —
both call paths converge on "given this catalog path, run the
uninstall flow." Splitting into two methods would mean every future
call-site (e.g., a CLI flag, a forest tree-view action, a programmatic
fix-up step) has to either pick one of the two methods or get a
third. Branching on input type at one entry point lets every new
call-site pick up the feature automatically.

This is a different shape from "two methods that share a private
helper" — that pattern is fine when the two public surfaces have
genuinely different signatures or pre-conditions (e.g., one async,
one sync). For "right-click an item to do X on its catalog"-style
actions, the pre-conditions ARE the same; the input shape is the
only thing that varies.

## Fix / recipe

`ForestController._on_uninstall_app(target)` accepts either a
`CellWindow` (legacy Forest-submenu call) or a path-like
(`str | Path`) from the popup-tree call. Branch at the top:

```python
def _on_uninstall_app(self, target):
    if isinstance(target, (str, Path)):
        cat_path = str(target)
    else:
        cat_path = getattr(target, "catalog_path", None)
    if not cat_path:
        return  # bail — neither a cell with a catalog nor a path

    # ...rest of the flow is identical from here down...
```

The polymorphic check is one `isinstance` + `getattr` — cheap, and
keeps the rest of the method linear. Anything that can compute a
catalog path (a cell, a popup action, a future test helper, a CLI
flag) can call this method directly with no adapter.

## How future-me detects it

* Symptom: when adding a new way to trigger an existing controller
  action, you find yourself writing a sibling method that duplicates
  most of the original. Stop — the original should branch on input
  type instead.
* Symptom: a controller handler has a list of `if isinstance(target, X)`
  branches >2 long. THAT'S too far the other way — at that point
  extract a helper that takes the normalised input.
* This pattern is "v3-process" because it's about how controllers
  evolve as new call-sites land — not specific to Qt or to a single
  feature. Apply it to any "right-click an item to do X" action
  layered on top of a feature that already exists for cells.
