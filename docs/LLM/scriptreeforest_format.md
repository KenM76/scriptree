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
    "roots": ["ScripTreeApps", "../ScripTreeApps"],
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
| `icon_data` | string | absent | Base64-encoded PNG for the forest hub's glyph.  Emitted only when set; absent files fall back to the bundled `icon-forest` glyph. |
| `icon_format` | string | absent | Image-format hint for `icon_data` (always `"png"` for runtime artifacts; the portable PySide6 build has no qsvg plugin). |
| `window_position` | `[x, y]` \| absent | absent | **v0.6.11+** — last on-screen position of the forest hub window.  Restored on next launch; absent ⇒ default to the bottom-left of the primary screen.  Hand-edited non-2-tuple values silently fall back to `None`. |

### `items[]` entries

| Field | Type | Default | Notes |
|---|---|---|---|
| `path` | string | required | Path to the source file (`.scriptreering`, `.scriptreetree`, or `.scriptree`). When `root` is present this is **relative to that named root**; otherwise it is the legacy relative-or-absolute form. |
| `root` | string | absent | **Named-root tag (v0.8.0a92, option #2).** When set, `path` is resolved as `known_roots()[root] / path`, with the root's base recomputed per machine / mode — so the reference survives a folder move, a portable↔normal toggle, and a cross-machine copy. Known ids: `install` (`<install>/ScripTreeApps`, travels with a folder-copy), `apps` (the sibling deploy tree), `personal` (per-user app-data, or install-local under portable mode). An unknown id falls back to the legacy path resolver. **Omit it and the loader treats `path` as a legacy bare path — old forests load unchanged.** |
| `kind` | `"ring"` \| `"tree"` \| `"tool"` | derived from suffix | Identifies how the controller spawns this entry — rings load via `load_ring`; trees and tools become a single bound cell. |
| `position` | `[x, y]` | `null` (let layout choose) | On-screen position for the master cell / standalone cell. |
| `catalog_path` | string | absent | Used internally for trees/tools when the bound catalog differs from `path` — usually omitted. Rooted the same way as `path` via a sibling `catalog_root` tag when applicable. |
| `catalog_root` | string | absent | Named-root tag for `catalog_path` (same rules as `root`). |

> **Excluded list (v0.8.0a92):** entries in `excluded[]` are rooted the same
> way — each is either a `{ "root": …, "path": <rel> }` object or a legacy
> string — so an ignored copy keeps matching after a move/portable-toggle.
>
> **Downgrade hazard:** a v0.8.0a92+ forest stores rooted items with the
> `ScripTreeApps/` prefix STRIPPED (`path` is relative to the named root). A
> *pre-a92* build has no `root` awareness, reads `path` as a bare relative
> string, and will mis-resolve it — stranding those cells. This only bites on a
> **downgrade / rollback** to an older build (or a second machine still on an
> older version); within a single up-to-date deployment it never occurs. Don't
> hand-edit a rooted `path` to re-add the prefix — the loader strips it against
> the named base.

### `auto_discover` config

| Field | Type | Default | Notes |
|---|---|---|---|
| `enabled` | bool | `true` | Master switch — when `false`, neither launch-time nor manual Refresh runs the walker. |
| `roots` | list of strings | `["ScripTreeApps", "../ScripTreeApps"]` | Folders to scan, relative to the project root or absolute.  The sibling-of-install entry (``../ScripTreeApps``) lets a deployment keep ScripTreeApps outside the ScripTree folder — checked into a separate repo, mounted via symlink, or on a shared drive.  Missing folders are silently skipped at discovery time. |
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

As of v0.3.15 the forest cell is a **regular `CellWindow`** with
`role="master"` and the `is_forest_master=True` flag set.  Same
default shape (hexagon / square per branding), same default size
(56 px), same drag and snap and repack behaviour as any ring
master.  The only visual difference is the stroke colour — bright
leaf-green (`#6cc48a`) so the forest cell reads as the workspace
root rather than another tool.

Two specific exemptions distinguish it from a regular master:

  1. ``_check_master_validity`` skips it (forest persists with 0
     members; a normal master with < 2 members tears itself down).
  2. The right-click menu prepends a ``Forest`` submenu via the
     ``_forest_menu_extension`` hook — workspace-level actions
     (Save forest, Auto-add, Forest settings, …) on top of the
     standard cell menu.

### Two-level groups

A ring attached to the forest forms a two-level group:

  * The forest master at the top — contains the ring's master cell
    among its members.
  * The ring master in the middle — contains the ring's own
    members.

The ring-master's `_group_master_id` points at the forest's id,
while the ring-master's own members have `_group_master_id`
pointing at the ring-master's id.  Dragging the forest translates
the ring-master (existing master-drag), which in turn cascades
into translating the ring's own members via
`_reflow_members_after_master_move`.

The ring-master's right-click menu offers **Leave forest (keep
ring intact)** — a v0.3.15 action (`_leave_forest_keep_ring`) that
severs forest membership without disbanding the ring.  **Disband
group** in the same submenu retains its existing meaning (tear
down the ring's own members), independent of forest membership.
