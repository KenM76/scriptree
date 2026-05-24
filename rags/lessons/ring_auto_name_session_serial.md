---
topic: v3-architecture
date: 2026-05-23
status: pattern
related: [recursive_merged_menu_population, master_cells_no_catalog_path]
---
# Auto-named rings via session-global serial counter

## What happened

Bug 8 (v0.8.0a1): rings showed up in menus and labels as "Cell
master XX (no catalog bound)" — a debug string never intended for
end-users. Rings need an automatic, human-friendly label since they
have no catalog of their own to derive one from.

## Root cause

Master cells own no `_catalog_path` (see `master_cells_no_catalog_path.md`).
The label-derivation chain in `tree_popup._popup_header_text` walked
`_catalog_path` → `_text_label` → fell off the end into the placeholder
debug string. Rings tend to have neither field set, so they always
hit the placeholder.

## Fix / recipe

Session-global serial counter + helper at
`scriptree/shell/cell_window.py:2677`:

```python
_RING_SERIAL: int = 0

def _next_ring_serial() -> int:
    global _RING_SERIAL
    _RING_SERIAL += 1
    return _RING_SERIAL
```

`_try_spawn_master` Case 1 assigns the auto-name:

```python
master._auto_ring_name = f"Ring {_next_ring_serial()}"
```

`tree_popup._popup_header_text` falls through to `_auto_ring_name`
after the existing chain, and skips the forest master (forests are
named separately):

```python
def _popup_header_text(cell) -> str:
    if getattr(cell, "_is_forest_master", False):
        return "Forest"
    if cell._catalog_path:
        return derive_name_from_catalog(cell._catalog_path)
    if getattr(cell, "_text_label", None):
        return cell._text_label
    if getattr(cell, "_auto_ring_name", None):
        return cell._auto_ring_name
    return f"Cell master {cell._id} (no catalog bound)"  # debug fallback
```

## Persistence

The serial counter is session-global: it resets to 0 when the
process restarts. Rings loaded from `.scriptreering` files derive
their name from the filename (existing behaviour), so saved rings
don't depend on the runtime counter. New rings in a fresh session
start counting at "Ring 1" again — that's intentional, matches
the analogous behaviour for unsaved file naming in IDEs.

## How future-me detects it

* Symptom: ring shows the debug placeholder "Cell master XX (no
  catalog bound)" in any menu or label. Either the counter never
  ran (check Case 1 spawn path) or `_popup_header_text` is missing
  the `_auto_ring_name` rung.
* Two rings in the same session show the same name — the global
  counter is somehow being reset mid-session. Search for any
  reassignment to `_RING_SERIAL`.
* "Ring 1" appearing after the session has spawned 20 rings — the
  serial increment uses `=` instead of `+= 1` somewhere.
