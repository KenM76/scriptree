# Menu appearance — global font + icon scale (v0.6.21+)

The popup menus that appear above cells, rings, and the forest hub
get their font + icon size from a *global* (per-machine) setting,
not from per-cell state.  This doc covers the storage, resolution,
and capability model so tooling that needs to read or write the
value gets it right.

## Storage layout

Two destinations, queried in this order:

1. **Local** — per-user `QSettings` under the `menu_appearance/`
   prefix.  Keys: `font_pct` (int), `font_pt` (int; `0` means
   "use percent"), `icon_pct` (int).
2. **Shared** — a JSON file at
   `%ProgramData%\<brand>\menu_appearance.json` on Windows,
   `/Users/Shared/<brand>/menu_appearance.json` on macOS,
   `/usr/local/share/<brand>/menu_appearance.json` on Linux.
   Keys: `font_pct` (int), `font_pt` (int | null), `icon_pct` (int).

The shared file is **also** where the global cell-defaults live
(`cell_shape`, `cell_orientation`, `cell_size_px`) — same JSON,
merged on writes.  Both halves are gated by the same capability
(see below).

## Resolution

For each field independently:

```
local QSettings value
    or
shared JSON value
    or
built-in default (125% font, 125% icon, branding cell shape/size)
```

Per-field, not all-or-nothing: a user who sets `font_pt` locally
still picks up `icon_pct` from the shared file if local has none.

## Defaults

| Field | Default |
|---|---|
| `font_pct` | **125** (the menus render 25% larger than the OS default font on first install — user requested baseline) |
| `font_pt` | `None` (use percent — no fixed override) |
| `icon_pct` | **125** |
| `cell_shape` | `"hexagon"` |
| `cell_orientation` | `"flat-top"` |
| `cell_size_px` | `56` |

## Capability gate

Writing to the **shared** JSON is gated by the
`menu_appearance_shared_write` capability.  Default deployments
ship without the capability file, so the "Save to shared settings"
checkbox in the Settings dialog is greyed and `save_menu_appearance(
..., save_shared=True)` silently no-ops.  An admin grants by
dropping a writable file named `menu_appearance_shared_write` into
the `permissions/` folder.

Local QSettings writes are NOT gated — every user can adjust
their own scale.

## Programmatic access

```python
from scriptree.shell.menu_appearance import (
    load_menu_appearance, save_menu_appearance,
    load_cell_defaults, save_cell_defaults,
    MenuAppearance, CellDefaults,
)
from scriptree.shell.branding_loader import load_branding

br = load_branding()
ma = load_menu_appearance(br)   # → MenuAppearance(font_pct=125, font_pt=None, icon_pct=125)
cd = load_cell_defaults(br)     # → CellDefaults(shape='hexagon', orientation='flat-top', size_px=56)

# Save.  Capability check for shared writes is the caller's job.
save_menu_appearance(
    MenuAppearance(font_pct=150, font_pt=None, icon_pct=150),
    save_local=True,
    save_shared=False,
    branding=br,
)
```

## How the values reach the UI

`tree_popup.apply_menu_appearance(menu)` resolves the live values
and applies `QFont` + `QSS QMenu { icon-size: Npx; }` to the menu,
then walks every submenu recursively so the scale propagates to
child menus the builders added during construction.  Called from:

* `show_tree_popup_for` (the single-click popup tree) — once
  before the build and once after, so live-search QWidgetActions
  AND submenus both pick up the scale.
* `CellWindow._show_context_menu` (the right-click context menu)
  — same dual call.

The base font for percent scaling is
`QApplication.font("QMenu")`, not the freshly-constructed QMenu's
font (which on Win11 has already been styled by the platform and
isn't a clean baseline).

## UI surface

The controls live in the per-cell **Settings → Shape & Size**
tab under "Menu font & icon scale" (NOT a separate tab — per
user direction the controls sit alongside the cell shape/size
controls so the same "save to local / shared default" checkboxes
cover both kinds of setting).

Controls:

* Font scale slider, 50-300%, step 5%, default 125.
* "Or fix the point size" dropdown: `Use percent` / 8 / 9 / 10 /
  11 / 12 / 14 / 16 / 18 / 20 / 24 / 28 / 32 pt.  Non-`Use percent`
  values override the slider.
* Icon scale slider, 50-300%, step 5%, default 125.
* "Save to local settings (this user)" checkbox — default on.
* "Save to shared settings (all users on this machine)" checkbox
  — default off, greyed by capability.
* "Reset to default (125% / 125%)" button.

Each control writes through immediately.  The cell shape /
orientation / size controls also write to the global
`CellDefaults` when either save-destination checkbox is ticked.

## Tests

Not separately tested as the value resolution is small (~3 if
branches per field) and the visible apply is covered by the
existing icon-library + cell-label test surfaces via the
shared apply path.
