# `.scriptreetree` file format (schema v2)

A tree-of-tools launcher. Leaves reference `.scriptree` files; interior
nodes are named folders.

## Shape

```json
{
  "schema_version": 2,
  "name": "string, required",
  "description": "string, optional",
  "nodes": [/* list[Node] */],
  "menus": [/* list[MenuItemDef], optional — see scriptree_format.md */],
  "folder_layout": "flat | tabs (optional, default 'flat')"
}
```

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
   own name (often technical, e.g. `SwDxfExport dxf_export`)
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
        "./sw_bridge/list-components.scriptree": "production",
        "./SwApiTrainingGen.scriptree": "verbose"
      }
    }
  ]
}
```

Edit these via the **Configs...** button in the tree view toolbar.

## Example

```json
{
  "schema_version": 1,
  "name": "SolidWorks toolkit",
  "nodes": [
    {
      "type": "folder",
      "name": "sw_bridge",
      "children": [
        { "type": "leaf", "path": "./sw_bridge/list-components.scriptree" },
        { "type": "leaf", "path": "./sw_bridge/compare-hardware.scriptree" }
      ]
    },
    {
      "type": "folder",
      "name": "Training data",
      "children": [
        { "type": "leaf",
          "path": "./SwApiTrainingGen.scriptree",
          "display_name": "Generate training pairs" }
      ]
    }
  ]
}
```
