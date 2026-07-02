# `.scriptreelayout` — saved cell arrangement (v0.8.0a83+)

## What it is

A **cell layout** is a *named, reusable arrangement* of the forest hub's cells.
It records, for each cell, **where that cell sits relative to the forest hub** —
nothing else. It is the file behind the forest right-click menu's
**File ▸ Save layout / Save layout as… / Open layout…** entries and the
top-level **Recent layouts** submenu (the pre-a119 "Cell layout ▸"
submenu was dissolved into those).

A layout is **positional, not membership**. Applying (loading) a layout
*repositions* the forest cells whose tool/tree path matches an entry, and
**leaves every other cell exactly where it is** — it never adds, removes, or
spawns cells. (Entries with no matching cell in the current forest are silently
skipped; cells not named in the layout are untouched.)

This is distinct from, but related to, two other things:

| Thing | Where it lives | Scope |
|---|---|---|
| Auto-remembered layout | `rel_offset` per item **inside the `.scriptreeforest`** | the *current* forest, persisted automatically as you rearrange |
| **Named layout (`.scriptreelayout`)** | a standalone file you Save/Load | a *snapshot* you can re-apply on demand |
| `.scriptreering` member positions | inside a `.scriptreering` | a ring's own members |

Both the auto-remembered layout and a named layout use the **same coordinate
convention**: each cell's offset is `(member_top_left − hub_top_left)`, so the
arrangement is reproduced *relative to the hub* regardless of where the forest
itself currently sits on screen.

## Where files live

Save/Load default to `<Documents>/<BRAND>/layouts/` (created on demand), the
sibling of the existing `<Documents>/<BRAND>/rings/` directory. The file
extension is `.scriptreelayout`. Recently-used layouts are tracked in the app's
MRU store (see `recent_files.add_layout` / `get_layouts`) and surfaced in the
"Recent layouts" submenu.

## File format

JSON. UTF-8. Pretty-printed (2-space indent).

```json
{
  "format": "scriptreelayout",
  "version": 1,
  "name": "My layout",
  "saved_at": "2026-06-23T12:34:56+00:00",
  "entries": [
    {
      "catalog_path": "ScripTreeApps/SolidWorks/sw.scriptreetree",
      "kind": "tree",
      "rel_offset": [120, -40]
    },
    {
      "catalog_path": "ScripTreeApps/Demos/find-replace/find-replace.scriptree",
      "kind": "tool",
      "rel_offset": [120, 40]
    }
  ]
}
```

### Top-level keys

| Key | Type | Meaning |
|---|---|---|
| `format` | string | Must be `"scriptreelayout"`. Loading any other value raises `ValueError`. |
| `version` | int | Schema version (currently `1`). A mismatch is logged, then the file is trusted (forward-compat). |
| `name` | string | Human label (shown in menus). Defaults to the file stem if absent. |
| `saved_at` | string | ISO-8601 UTC timestamp, written on save. Informational. |
| `entries` | array | The cells, in save order. |

### Per-entry keys

| Key | Type | Meaning |
|---|---|---|
| `catalog_path` | string | The tool/tree this cell is bound to — **the stable identity** used to match a layout entry to a live cell. Stored relative to the project root when possible (portable across machines), absolute otherwise; resolved on load. **Required** — an entry without it is skipped. |
| `kind` | string | `"ring"`, `"tree"`, or `"tool"` — a hint. Derived from the path suffix when absent. |
| `rel_offset` | `[dx, dy]` | The cell's top-left **offset from the forest hub's top-left**, in logical pixels. **Required**; must be a 2-element array of ints, else the entry is skipped. |

## How a layout is applied (the logic)

Loading a `.scriptreelayout` is **reposition-existing-only**:

1. For each entry, normalise `catalog_path` and look up the live forest cell
   bound to that path.
2. If found, record the entry's `rel_offset` as that cell's *remembered offset*
   on the hub (`CellWindow._remembered_offsets`, keyed by the same normalised
   path).
3. If not found, skip the entry (no spawning).
4. Then run the standard restore pass: each cell whose remembered offset places
   it **fully on-screen** (checked across **all** monitors) slides to
   `hub.pos() + rel_offset`; any cell whose spot would be off-screen is left to
   the layout engine to auto-tile (and keeps its remembered offset, so it
   returns to its spot if screen space later allows).

Duplicate `catalog_path` entries (the same tool docked twice) collide on the
normalised-path key: last-writer-wins, and the offset is applied to whichever
cell currently holds that path. This is a known limitation — forest items are
already path-keyed throughout ScripTree.

## Failure modes / recovery

- **Wrong `format`** → `load_layout` raises `ValueError`; the caller shows the
  error and does nothing.
- **Malformed entry** (no `catalog_path`, or `rel_offset` not a 2-int array) →
  that entry is silently skipped; the rest of the layout still applies.
- **Hand-edited / corrupt JSON** → `json.loads` raises; surfaced to the user.
- **An entry's tool/tree isn't in the forest** → skipped (reposition-only).

## Reconstruction test

A competent engineer should be able to rebuild the reader/writer from this doc:
a `LayoutDef` is `name` + `list[LayoutEntry]`; `LayoutEntry` is
`(catalog_path, rel_offset, kind)`. `save_layout` writes the blob above (paths
relativised to the project root, offsets coerced to `int`); `load_layout` parses
it, rejecting a wrong `format`, tolerating a wrong `version`, and skipping
malformed entries. No Qt/on-screen state is touched in the file layer —
placement is the forest controller's job. See
`scriptree/shell/layout_io.py`.
