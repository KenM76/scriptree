# `.scriptreeforest` file format (V3 v0.3.14+)

A **forest** is the top-level container in ScripTree's file
hierarchy:

```
.scriptree         single tool         (one cell)
.scriptreetree     tree of tools       (one cell + popup folder of tools)
.scriptreering     ring of cells       (master + member cells docked together)
.scriptreeforest   forest of rings ←   (everything on screen, plus auto-discovery)
```

The forest knows about all rings, trees, and individual tools that
make up a workspace, and how to refresh that workspace from a
configurable set of source folders.  It launches via
`run_scriptreeforest.bat` (Windows) / `run_scriptreeforest.py`
(Unix).

## File layout

JSON, indented for readability.  All paths are stored relative to
the project root when possible (so a forest checked into a repo
travels with the source); absolute paths are stored verbatim.

```json
{
  "format": "scriptreeforest",
  "version": 1,
  "name": "Engineering Forest",
  "saved_at": "2026-05-08T17:32:11+00:00",
  "items": [
    {
      "path": "ScripTreeApps/SolidWorks/sw_main.scriptreering",
      "kind": "ring",
      "position": [120, 180]
    },
    {
      "path": "ScripTreeApps/Demos/demos.scriptreetree",
      "kind": "tree",
      "position": [340, 180]
    }
  ],
  "excluded": [
    "ScripTreeApps/Old/legacy.scriptree"
  ],
  "auto_discover": {
    "enabled": true,
    "roots": ["ScripTreeApps"],
    "include": ["ring", "tree", "tool"],
    "update_mode": "prompt"
  }
}
```

### Field rules

| Field | Type | Default | Notes |
|---|---|---|---|
| `format` | string | required | Must be `"scriptreeforest"`. |
| `version` | int | `1` | Schema version.  Unknown versions log a warning and proceed. |
| `name` | string | `"Forest"` | Display name (used to derive the forest cell's label). |
| `saved_at` | string | written | ISO-8601 UTC timestamp.  Read-only — set by `save_forest` on every write. |
| `items` | list | `[]` | One entry per ring/tree/tool to load.  See **items** below. |
| `excluded` | list of strings | `[]` | Paths the user has explicitly removed from the forest.  Auto-discovery surfaces them in the prompt as "previously excluded" rather than re-adding silently. |
| `auto_discover` | object | sensible defaults | Settings for the discovery walker.  See **auto_discover** below. |

### `items[]` entries

| Field | Type | Default | Notes |
|---|---|---|---|
| `path` | string | required | Path to the source file (`.scriptreering`, `.scriptreetree`, or `.scriptree`). |
| `kind` | `"ring"` \| `"tree"` \| `"tool"` | derived from suffix | Identifies how the controller spawns this entry — rings load via `load_ring`; trees and tools become a single bound cell. |
| `position` | `[x, y]` | `null` (let layout choose) | On-screen position for the master cell / standalone cell. |
| `catalog_path` | string | absent | Used internally for trees/tools when the bound catalog differs from `path` — usually omitted. |

### `auto_discover` config

| Field | Type | Default | Notes |
|---|---|---|---|
| `enabled` | bool | `true` | Master switch — when `false`, neither launch-time nor manual Refresh runs the walker. |
| `roots` | list of strings | `["ScripTreeApps"]` | Folders to scan, relative to the project root or absolute. |
| `include` | list | `["ring", "tree", "tool"]` | Which kinds the walker is allowed to add.  Filtering does NOT silently demote: a folder containing a `.scriptreering` is treated as a ring-folder and skipped entirely if `"ring"` isn't in `include` (rather than falling through to its `.scriptree` siblings). |
| `update_mode` | `"off"` \| `"auto"` \| `"prompt"` | `"prompt"` | How discovery applies its diff.  `"off"` = never run; `"auto"` = apply silently; `"prompt"` = checkbox dialog. |

## Discovery priority rule

For each subdirectory of every configured root (depth-first):

```
if D contains *.scriptreering   → emit those rings;  STOP descending into D
elif D contains *.scriptreetree → emit those trees;  STOP descending into D
elif D contains *.scriptree     → emit those tools;  STOP descending into D
else                            → recurse into D's subdirs
```

The "stop descending" semantic is what gives the priority rule its
power — a folder with a ring file is treated as one self-contained
unit; we don't pull individual tools out of it.

### Excluded items

`discover()` always **emits** matches in the priority tier (so the
diff layer can route them).  The diff stage then routes:

* path in `discovered` AND path in `excluded` → `previously_excluded`
  bucket (prompt dialog offers re-inclusion).
* path in `discovered` AND not in `excluded` AND not in current
  forest → `added` bucket (prompt dialog offers acceptance).
* path in current forest AND not in `discovered` AND not on disk
  → `removed` bucket (prompt dialog offers removal; not added to
  `excluded` because the file went away on its own — the user
  didn't choose to exclude).

An **excluded ring still blocks** the same folder's `.scriptree`
sibling from being discovered.  The ring "occupies" the priority
slot; excluding it doesn't promote the lower-tier sibling — that
would silently demote the user's intent.

### Hidden directories

Subdirectories whose basename starts with `.` (e.g. `.git`,
`.vscode`) are skipped.  This is unconditional and not configurable
per discovery pass.

## First-run wizard

When the forest is empty AND no autoload file exists, the
controller pops a welcome dialog with:

* Scan-folder editor (defaults to `ScripTreeApps/`, lets you add /
  remove paths).
* Type-filter checklist (rings / trees / tools).
* Update-mode radios (off / prompt / auto).
* "Discover & populate" / "Skip — empty forest" buttons.

Discover & populate runs the walker once and applies all results
unconditionally — first-run is intentionally one-click; the user
can tidy via the right-click menu after.

## Right-click menu

The visible forest cell's context menu offers:

* **Save forest** / **Save forest as…** / **Open forest…**
* **Refresh from sources** — manual discovery + apply per the
  configured `update_mode`.
* **Auto-add from ScripTreeApps now** — force-runs the prompt
  dialog regardless of `update_mode` (useful when `update_mode` is
  `"off"` and you want a one-off discovery without changing the
  setting permanently).
* **Forest settings…** — edit `name` + everything in `auto_discover`.
* **Manage excluded items…** — list view of `excluded` with
  per-row Re-include / Forget buttons.
* **About this forest** — summary of state.

## Per-user autoload

The launcher autoloads `<APPDATA>/<BRAND>/last_forest.scriptreeforest`
on startup.  The controller saves to this path automatically on
every meaningful change (item added/removed, settings changed,
forest cell moved), so a process restart restores the user's last
session.

## Visual

The forest cell is a 12-sided polygon (dodecagon) sized 96 px by
default — visibly larger than a normal 56 px hex cell, themed in
deep forest green with a brighter leaf-green stroke.  Renders
above all other cells (`Qt.WindowStaysOnTopHint`); doesn't
participate in `SnapEngine` (it's a layer above rings, not a peer
of them).
