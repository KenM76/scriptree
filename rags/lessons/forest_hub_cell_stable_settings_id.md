# Forest hub cell needs a stable QSettings ID across launches

**Tag**: `v3-architecture`
**Date**: 2026-06-05
**Versions affected**: pre-v0.8.0a47 — fixed in v0.8.0a47

## TL;DR

`CellWindow.__init__` accepts an optional `hexagon_id` parameter; if
omitted it generates a fresh `uuid.uuid4()`. The forest hub cell —
which is a logical **singleton per workspace** — was being constructed
without an explicit `hexagon_id`, so it got a new uuid on every
ScripTreeRing launch. All its per-cell QSettings entries
(`hexagon/<uuid>/text_label`, `/icon_path`, `/size_px`,
`/transparency`, `/always_on_top`, `/icon_scale`, `/label_opacity`,
`/text_over_icon`, `/collapse_with_master`, `/catalog_path`) were
re-saved under a new uuid every run and the previous uuid's entries
became zombies.

User-visible symptom: any customisation made via the cell Settings
dialog on the forest hex (text label, icon, size, transparency,
always-on-top, etc.) silently vanished on the next launch. Behaviour
that depended on a stable id (per-cell preferences across runs)
silently broke.

**Fix**: pass an explicit constant `hexagon_id` to the `CellWindow`
constructor for the forest hub. ScripTree uses the sentinel
`FOREST_HUB_HEX_ID = "forest-hub"` defined at the top of
`scriptree/shell/forest_controller.py`. The literal is **frozen** —
changing it would orphan every existing user's saved settings.

## How it presented

The user reported the "Fo" label issue (`qmenu_freeze_under_floating_dialog.md`'s
sibling — `_derive_label` was unconditionally re-stamping `"Fo"` on
the forest cell every launch). v0.8.0a46 fixed the auto-stamp source;
v0.8.0a43 had previously cleaned up 155 zombie `hexagon/<uuid>/text_label
= "Fo"` entries from QSettings. The user then noticed: even with the
a46 fix, **any intentional** customisation on the forest cell wouldn't
survive a restart — only the unintentional "Fo" auto-stamp had been
re-applying.

That made the underlying defect (fresh uuid per launch) the actual
load-bearing bug. a47 is the structural fix.

## Why a sentinel and not a derived id

The forest hub is the workspace root — exactly one per ScripTreeRing
process. Even when the user opens a different `.scriptreeforest` file
via `ForestController.open()`, the same `forest_window` cell is
reused with a new `ForestDef` loaded into it. The cell's appearance
preferences belong to "the forest cell", not to any specific forest
file, so they should be shared across files.

A derived id (e.g. `sha256(forest_path)[:16]`) would tie settings to
the forest file path, which means a user who renames the file or
opens a different forest gets a fresh blank cell. That's worse UX
than the sentinel.

If a future change introduces multiple-forests-in-one-process, the
right move is to add a `forest_hub_id` field to the forest preferences
file (defaulting to `"forest-hub"` for back-compat) and read it at
construction time — NOT to change the sentinel literal.

## Fix code

```python
# scriptree/shell/forest_controller.py (top-of-module)

FOREST_HUB_HEX_ID = "forest-hub"  # do not change — orphans saved settings

# scriptree/shell/forest_controller.py (ForestController.__init__)

self.forest_window = CellWindow(
    self._branding,
    role="master",
    is_forest_master=True,
    hexagon_id=FOREST_HUB_HEX_ID,   # ← stable across launches
)
```

## How future-me detects regressions

* Symptom: user-set cell preferences on the forest cell vanish on
  restart. First check is whether `forest_window._id` is the
  `FOREST_HUB_HEX_ID` sentinel, not a random uuid.
* The `test_forest_cell_has_stable_settings_id` test in
  `tests/test_forest.py` pins both the sentinel literal AND the
  derived settings key (`hexagon/forest-hub/text_label`) so a
  refactor that loses either fails CI.

## Cross-reference

- `rags/lessons/qmenu_freeze_under_floating_dialog.md` — the
  sibling "Fo" investigation that surfaced this id-stability issue
- `scriptree/shell/cell_window.py::_settings_key` — the function
  whose key format depends on `self._id`
- `scriptree/shell/cell_window.py::_save_settings` /
  `_load_settings` — what gets persisted under that key

## User-visible recovery

a47 introduces stable settings for the forest cell. Pre-a47 zombie
`hexagon/<uuid>/*` entries are inert (they're for uuids that will
never come back); they can be cleared on demand with the same
`QSettings.allKeys()` filter we used in a43, but doing so is
optional — they consume a tiny amount of registry space and don't
affect behaviour.
