# `.scriptreetree` file format (schema v1)

A tree-of-tools launcher. Leaves reference `.scriptree` files; interior
nodes are named folders.

## Shape

```json
{
  "schema_version": 1,
  "name": "string, required",
  "description": "string, optional",
  "nodes": [/* list[Node] */],
  "menus": [/* list[MenuItemDef], optional — see scriptree_format.md */]
}
```

Each `Node` is either a folder or a leaf:

```json
{ "type": "folder", "name": "string, required",
  "children": [/* list[Node], may be empty */] }
```

```json
{ "type": "leaf", "path": "string, required",
  "display_name": "string, optional — falls back to the tool's name",
  "configuration": "string, optional — config name for standalone mode" }
```

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
out of the IDE. Each leaf tool becomes a tab. Per-tool configurations
are applied from the tree-level config sidecar
(`<name>.scriptreetree.treeconfigs.json`), or from
`leaf.configuration`, or from tool defaults if neither is set.

If a referenced configuration no longer exists in a tool's sidecar,
ScripTree creates a reserved `safetree` config (all UI hidden, popup
dialogs enabled). The name `safetree` is reserved and cannot be used
by users.

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
