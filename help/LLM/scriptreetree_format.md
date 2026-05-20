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
  "children": [/* list[Node], may be empty */] }
```

```json
{ "type": "leaf", "path": "string, required",
  "display_name": "string, optional — override for the tree label and standalone tab",
  "configuration": "string, optional — config name for standalone mode" }
```

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
