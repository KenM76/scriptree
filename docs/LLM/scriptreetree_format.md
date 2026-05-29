# `.scriptreetree` file format

A tree-of-tools launcher. Leaves reference `.scriptree` files; interior
nodes are named folders.

> **Schema version — single source of truth**
>
> The current `schema_version` value is the `SCHEMA_VERSION`
> constant in `scriptree/core/model.py` (shared with the
> `.scriptree` leaf format).  **Read it from the constant.  Do
> not copy the number out of this doc's title, JSON sketch
> below, or any example** — those have shipped stale at least
> once when the schema rolled (an LLM session wrote v2 after v3
> was released; the loader hard-rejected the file).  Files with
> `schema_version` *above* the current build are hard-rejected;
> files *below* may load with in-memory upgrade (see the
> `model.py` comment block).

## Shape

```json
{
  "schema_version": "<int — current SCHEMA_VERSION from scriptree/core/model.py; do NOT copy this string literally>",
  "name": "string, required",
  "description": "string, optional",
  "nodes": [/* list[Node] */],
  "menus": [/* list[MenuItemDef], optional — see scriptree_format.md */],
  "folder_layout": "flat | tabs (optional, default 'flat')",
  "path_prepend": [/* list[string], optional, v0.1.11+ */],
  "cell": {/* CellAppearance, optional, see below — v0.2.7+ */}
}
```

### `path_prepend` (v0.1.11; run-time wiring landed in v0.3.2)

Optional list of directories prepended to the child process's
`PATH` for **every tool launched via this tree**.  Layered between
local (tool + config) and global per-Settings entries — see
[../environment.md](../environment.md) for the full search-order
table.

Typical use: a tree of CLIs that all need a vendored binary
directory on PATH (e.g. `./vendor/bin`).  Setting it once on the
tree avoids copy-pasting the same `path_prepend` into every leaf
tool's `.scriptree`.  The missing-executable recovery dialog can
populate this field automatically when the user picks the
*.scriptreetree path_prepend* scope.

Empty / missing fields serialize to nothing — the field is omitted
from the JSON when the list is empty so legacy trees stay
byte-identical.

> **Note on v0.3.2.** The field has existed since v0.1.11 and the
> recovery dialog has always been able to write to it, but the
> run-time wiring (forwarding the list into the spawned child's
> PATH at Run time) was missing in v0.1.x – v0.3.1.  v0.3.2 closed
> the gap: ``build_env`` / ``build_full_argv`` accept a
> ``tree_path_prepend=`` kwarg, ``TreeLauncherView.tree_path_prepend()``
> exposes the loaded tree's list, and ``MainWindow._show_runner``
> forwards it to the runner before each Run.  Existing
> `.scriptreetree` files that already had `path_prepend` entries
> from the recovery dialog will start having them honoured at Run
> time after upgrading.

Each `Node` is either a folder or a leaf:

```json
{ "type": "folder", "name": "string, required",
  "display_name": "string, optional — override for the folder label",
  "icon": "string, optional — bundled glyph name (e.g. 'build') OR path",
  "icon_data": "string, optional — base64-encoded PNG bytes",
  "icon_format": "string, optional — 'png' (only PNG renders portably)",
  "children": [/* list[Node], may be empty */] }
```

```json
{ "type": "leaf", "path": "string, required",
  "display_name": "string, optional — override for the tree label and standalone tab",
  "configuration": "string, optional — config name for standalone mode",
  "icon": "string, optional — bundled glyph name OR path",
  "icon_data": "string, optional — base64-encoded PNG bytes",
  "icon_format": "string, optional — 'png'" }
```

## Per-node icon overrides (v0.6.26+)

Folder and leaf nodes both accept an optional `icon` / `icon_data` /
`icon_format` triplet that overrides the default glyph used in the
single-click popup menu.  Resolution priority — first match wins:

1. `icon_data` (base64 PNG bytes) — embedded; portable, no path
   fragility, takes precedence when both forms are set.
2. `icon` — first tried as a **bundled glyph name** (e.g. `"build"`
   → `icons/icon-build.png` from the shipped set); on miss, treated
   as a **path** (relative to the `.scriptreetree`'s directory or
   absolute).
3. Fallback — folders use the OS folder icon, leaves use the bound
   `.scriptree`'s own `cell.icon_data` (or a classified bundled
   glyph chosen from the tool name).

All three fields are emitted only when non-empty, so legacy trees
round-trip byte-identical.  The override is consumed by the popup
menu only — V1's full editor view still shows the bound tool's own
icon.  Use this when:

- A folder collects e.g. "scissor" workflows and you want its
  submenu to show a `scissors` glyph instead of the generic folder.
- The same `.scriptree` is referenced from multiple trees and one
  of them wants a different glyph than the tool's default.

## `display_name` — precedence

For **leaves**, the label shown in the tree view and the standalone
tab bar is chosen in this order:

1. `display_name` from the tree node (if non-empty) — pretty label
   controlled by the tree author
2. `ToolDef.name` from the referenced `.scriptree` file — the tool's
   own name (often technical, e.g. `DxfExport dxf_export`)
3. The referenced file's stem (fallback if the tool can't be loaded)

For **folders**, `display_name` overrides the folder's `name` field
in the tree view. If absent, `name` is used as-is.

For **subtree leaves** (paths ending in `.scriptreetree`), the label
in the IDE tree is:

1. `display_name` if set
2. The referenced tree's own `name`
3. The filename stem

Standalone mode skips subtree leaves entirely — flatten the referenced
tree's leaves into the parent, or open each nested tree separately.

## Path resolution

`leaf.path` is resolved as follows:

1. If absolute, used as-is.
2. Otherwise, resolved relative to the directory containing the
   `.scriptreetree` file (NOT the current working directory).

Broken references don't prevent the file from loading — the tree view
shows the leaf with a red icon and a tooltip explaining the error.

## Invariants

- `nodes` may be empty (the tree shows "(empty tree)").
- Folder names need not be unique — the UI shows duplicates fine.
- Leaf paths need not be unique — you can reference the same tool from
  multiple places in the tree.
- Cycles are impossible: the format is a tree of folders, and leaves
  are paths on disk, not references to other tree nodes.
- `leaf.configuration` names a configuration in the tool's sidecar to
  apply when the tree is opened in standalone mode.

## Standalone mode

Use **View → Open in standalone window** (Ctrl+Shift+S) to pop a tree
out of the IDE. The runtime layout depends on `folder_layout`:

- **`"flat"` (default)** — every leaf tool in the tree (depth-first)
  becomes one tab in a single QTabWidget. Folders are flattened away.
  Same behavior as pre-v0.1.9.
- **`"tabs"`** — each top-level folder becomes an outer tab containing
  a nested QTabWidget with one inner tab per tool. Top-level leaves
  (tools that aren't inside any folder) sit alongside folder tabs at
  the outer level. Nested folders recurse — folder inside folder
  becomes a nested QTabWidget inside the outer folder's tab.

Folder tabs are prefixed with 📁 to distinguish them from leaf tabs
when both share the outer level. Both inner and outer tab bars use
the wrapping tab implementation, so they flow onto multiple rows
when the window is narrow.

The user can also flip `folder_layout` at runtime via the standalone
window's tab-bar right-click menu (**Folder layout → Flat** /
**Folders as tabs (nested)**). The runtime toggle is in-session only;
it doesn't write back to disk.

Per-tool configurations are applied from the tree-level config sidecar
(`<name>.scriptreetree.treeconfigs.json`), or from
`leaf.configuration`, or from tool defaults if neither is set.

If a referenced configuration no longer exists in a tool's sidecar,
ScripTree creates a reserved `safetree` config (all UI hidden, popup
dialogs enabled). The name `safetree` is reserved and cannot be used
by users.

> **When generating a `.scriptreetree`** for a tree with 8+ tools or
> meaningful folder structure, set `"folder_layout": "tabs"`. The
> nested layout makes a 20-tool tree dramatically easier to navigate
> than 20 sibling tabs in a single QTabWidget. For small trees
> (≤7 tools) flat is usually clearer.

## `cell` sub-object (v0.2.7+, optional)

Same shape as the `cell` sub-object on a `.scriptree` (see
[`scriptree_format.md`](scriptree_format.md) → "`cell` sub-object").
Controls how the V3 cell shell paints a launcher cell bound to this
`.scriptreetree`.

```json
"cell": {
  "icon": "string, optional — path to an icon file",
  "icon_data": "string, optional — base64-encoded image bytes (embedded)",
  "icon_format": "string, optional — \"png\" | \"jpg\" | \"svg\" | ...",
  "text_label": "string, optional — explicit text override",
  "icon_scale": "number, optional — relative scale, range 0.25–2.00, default 1.00",
  "label_opacity": "number, optional — alpha, range 0.20–1.00, default 1.00",
  "fill_color": "string, optional — \"#RRGGBB\" override for the cell fill (v0.3.6+)",
  "text_color": "string, optional — \"#RRGGBB\" override for the label text colour (v0.3.8+)"
}
```

Field rules, defaults, ranges, label-painting priority, and the
relative-path convention (forward-slash, relative-to-catalog when
the icon sits under the catalog dir; absolute otherwise) are
identical to the `.scriptree` case. The whole sub-object is omitted
on save when every field is at its default, so legacy `.scriptreetree`
files stay byte-identical.

The cell shell uses these fields when a cell is bound to this tree;
they have no effect on the V1 editor or runner. A `.scriptreering`
file does NOT override them — icon and text always come from the
catalog itself; the ring file only persists position, size,
transparency, shape, and the catalog path each cell points at.

## Use of `.scriptreetree` from the V3 cell shell

The cell shell binds catalogs to cells. A `.scriptreetree` bound to
a single cell (single-left click) renders as one popup folder of
tools. When two cells are docked into a ring, the shell builds a
**merged** `.scriptreetree` on the fly into
`%TEMP%/scriptreering_merged_<hash>.scriptreetree`, with one
top-level folder per member; this is what V1 receives on a master's
double-right-click. The hash is derived from the membership
signature, so re-docking the same cells produces the same path
(V1 can keep the file open across re-docks).

Master cells themselves have no persistent `catalog_path` — their
"catalog" is materialised on demand from the members' catalogs. A
`.scriptreetree` saved manually with the same content as a merged
tree would behave identically when bound to a cell, but the on-disk
form is reserved for member catalogs.

## Auto-discover: `auto_discover` and `excluded` (v0.8.0a21+)

A `.scriptreetree` can ask ScripTree to keep itself in sync with a
folder of `.scriptree` files on disk.  This is the **new-tool-found
feature** — parallel to the forest's auto-discover, scoped to trees.

Two new top-level fields participate:

```json
{
  "auto_discover": {/* TreeAutoDiscoverConfig, optional */},
  "excluded":      [/* list[string], optional */]
}
```

### Why it exists

Hand-curated trees age badly when the underlying tool folder grows.
Authors add new `.scriptree` files but forget to mention them in the
tree; users miss tools because the menu shows yesterday's snapshot.
The auto-discover feature closes that gap: ScripTree walks the
tree's containing folder, finds anything new, and offers to add it
through a diff dialog.  The user picks what to accept; the
`.scriptreetree` is rewritten to include the chosen leaves.

### `auto_discover` field shape

```json
{
  "auto_discover": {
    "enabled":                "bool, default true — master kill switch",
    "roots":                  ["./", "list of folders to scan, relative to the tree file's directory"],
    "include_sibling_trees":  "bool, default true — surface sub-.scriptreetree files as candidate sub-tree leaves",
    "update_mode":            "off | auto | prompt, default 'prompt'"
  }
}
```

**`enabled`** (bool, default `true`).  When `false`, the walker is
never invoked: no auto-discovery on load, and the "Scan tree for
new tools" menu entry is disabled (the tooltip explains why).
Distinct in spirit from `update_mode: "off"` — `enabled=false` is
the author's long-term "this tree is frozen" toggle; `update_mode`
is the user's per-session "stop asking but keep the manual menu
available" preference.

**`roots`** (list of strings, default `["."]`).  Folders to scan,
each resolved against the tree file's own directory at the moment
discovery runs.  The default `["."]` means "this tree's folder and
everything below it".  Use multiple roots for the rare case where
one tree aggregates two parallel folders (e.g.
`roots=["./shared", "../bespoke"]`).  Absolute paths are honoured
but make the tree non-portable across machines.  Folders that
don't exist are skipped silently.

**`include_sibling_trees`** (bool, default `true`).  When the
walker encounters another `.scriptreetree` file during the scan,
this flag controls whether that file becomes a candidate sub-tree
leaf in the current tree's diff dialog.  Either way, the walker
**stops descending** at the `.scriptreetree` boundary (that
subtree is owned by that other file); the flag only affects
whether the boundary file itself is surfaced as something the
current tree could add.

Set to `false` for a master / aggregator tree that should remain
flat — direct `.scriptree` leaves only, no nested trees.

**`update_mode`** (one of `"off"`, `"auto"`, `"prompt"`, default
`"prompt"`).  How the discovery pass applies its diff:

* `"off"` — discovery does not run.  The walker, diff, and prompt
  are all skipped.  Set this when a user explicitly opts out of
  the feature for this tree.  The manual "Scan tree for new
  tools" menu entry still works (it temporarily upgrades to a
  one-shot prompt).
* `"auto"` — discovery runs and applies adds/removes/re-includes
  **silently**.  No dialog.  Suits authoritative trees where the
  on-disk folder IS the source of truth and the
  `.scriptreetree` is just a cache.  The user can still inspect
  the result in the editor; nothing destructive happens (a
  removed leaf is one click to re-add).
* `"prompt"` — discovery runs but mutations go through the diff
  dialog.  The user picks which adds to accept and confirms each
  remove.  Default for hand-curated trees.

### `excluded` field shape

```json
{
  "excluded": [
    "./deprecated/old-tool.scriptree",
    "./experimental/scratch.scriptree"
  ]
}
```

Paths the user has explicitly removed via the diff dialog.
Stored relative to the tree file's directory when possible,
absolute otherwise — same resolution rules as `TreeNode.path`.

Discovery still emits these paths so the diff dialog can route
them to the "Previously excluded" section (in case the user
changes their mind), but they do NOT enter the "Added" bucket
on a regular pass — the exclusion is the user's way of saying
"stop re-suggesting this."

Kept at the top level of the tree (not inside `auto_discover`)
because exclusion is *state* the user has built up over time,
while `auto_discover` is *settings*.  Separating them makes
"reset settings to default" a sensible operation that doesn't
wipe accrued exclusions.

### The walker's priority rule

The walker descends the tree's `roots` depth-first with the
following per-directory rules:

1. If the directory contains a `.scriptreetree` file other than
   the one being scanned, **stop descending**.  That subtree is
   owned by that other file.  When `include_sibling_trees: true`,
   the `.scriptreetree` is emitted as a candidate sub-tree leaf.
2. Otherwise, emit every `.scriptree` file in the directory as
   a candidate tool leaf, then recurse into subdirectories.
3. Directories whose basename starts with `.` (e.g. `.git`,
   `.vscode`) are skipped silently — they hold no user tools.

A candidate is only added to the "Added" bucket of the diff if
all of the following hold:

* The path is not already represented as a leaf anywhere in the
  current `tree.nodes`.
* The path is not in `excluded` (matched paths get routed to
  "Previously excluded" instead).
* The corresponding file exists and parses (broken files are
  shown in a separate "errors" expander at the bottom of the
  dialog rather than offered for inclusion).

### The first-load contract

The `auto_discover` JSON key is **optional**.  Three states are
possible:

| On disk | In memory | Behaviour on next load |
|---|---|---|
| Key absent OR explicit `null` | `TreeDef.auto_discover = None` | Editor fires the one-shot `ChooseUpdateModeDialog` so the user picks `prompt` / `auto` / `off`.  The chosen mode is written back as a non-`None` block, so this dialog only ever fires once per tree. |
| Key present, value `{}` or all-defaults | `TreeAutoDiscoverConfig()` with default values | Treated as "user has been asked, chose all defaults" — the regular `update_mode` path runs (default `"prompt"`).  On save, the block is **omitted again** (the default-equals-omitted rule) so the file stays byte-identical to the no-block form. |
| Key present, at least one field non-default | `TreeAutoDiscoverConfig(...)` with the explicit values | Regular `update_mode` path runs.  The block is preserved on save with only the non-default fields written. |

Every pre-feature `.scriptreetree` file in the wild lands in the
first row — opening it once triggers the chooser, then either
writes a configured block (if the user picks `auto` or `prompt`
and a non-default option) or leaves the file byte-identical (if
the user picks every default).

### Folder-shape convention (recommended)

The walker is folder-agnostic and works against any layout, but
authors get the cleanest auto-discover ergonomics with the
following structure:

```
ScripTreeApps/
└── <program>/                   e.g. solidworks, outlook, git, pwsh
    ├── <program>.scriptreetree  the program's top-level tree
    ├── <purpose>/               e.g. export, cleanup, migration, analysis
    │   ├── tool-a.scriptree
    │   └── tool-b.scriptree
    └── <purpose>/
        └── ...
```

With this layout, the `<program>.scriptreetree`'s default
`roots: ["."]` auto-discovers every tool in the program's
`<purpose>/` subfolders.  When a sister program's tree wants to
absorb this one as a nested sub-tree, the
`include_sibling_trees` flag surfaces it as a candidate.

The hashtag / view-modes system (planned for a future release)
will use `program`, `purpose`, `tags` fields on individual
`.scriptree` files to let the menu re-bucket discovered tools
by axis (by-program, by-purpose, by-program-x-purpose) at
render time — independent of how they're laid out on disk.

### Worked example

A `.scriptreetree` that scans its own folder, prompts the user
on changes, and has removed one deprecated tool from past
suggestions:

```json
{
  "schema_version": 3,
  "name": "SolidWorks Toolkit",
  "nodes": [
    { "type": "folder", "name": "export", "children": [
        { "type": "leaf", "path": "./export/dxf-export-drawing.scriptree" },
        { "type": "leaf", "path": "./export/step-export.scriptree" }
      ]
    },
    { "type": "folder", "name": "cleanup", "children": [
        { "type": "leaf", "path": "./cleanup/hide-sketches.scriptree" }
      ]
    }
  ],
  "auto_discover": {
    "update_mode": "prompt"
  },
  "excluded": [
    "./deprecated/old-batch-export.scriptree"
  ]
}
```

Next time this file is opened, the walker scans `./` (the file's
folder), descends into `./export/`, `./cleanup/`, and any other
subdirs *except* those containing their own `.scriptreetree`.
Newly-found `.scriptree` files appear in the "Added" section of
the diff dialog; the one in `./deprecated/` is routed to
"Previously excluded" (still visible, still re-includable, but
unchecked by default).

## Tree configuration sidecar

Tree-level configurations live in a separate sidecar:

```json
{
  "schema_version": 1,
  "active": "default",
  "configurations": [
    {
      "name": "default",
      "tool_configs": {
        "./file-utils/list-files.scriptree": "production",
        "./ReportGen.scriptree": "verbose"
      }
    }
  ]
}
```

Edit these via the **Configs...** button in the tree view toolbar.

## Example

The `schema_version` value below is rendered with the current
`SCHEMA_VERSION` constant at the time of writing.  When you copy
this example, **use the current value from
`scriptree/core/model.py:SCHEMA_VERSION`**, not the literal here —
see the note at the top of this doc.

```json
{
  "schema_version": 3,
  "name": "Demo toolkit",
  "nodes": [
    {
      "type": "folder",
      "name": "file-utils",
      "children": [
        { "type": "leaf", "path": "./file-utils/list-files.scriptree" },
        { "type": "leaf", "path": "./file-utils/compare-dirs.scriptree" }
      ]
    },
    {
      "type": "folder",
      "name": "Reports",
      "children": [
        { "type": "leaf",
          "path": "./ReportGen.scriptree",
          "display_name": "Generate report" }
      ]
    }
  ]
}
```
