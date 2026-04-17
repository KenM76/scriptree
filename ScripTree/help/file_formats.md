# File formats

ScripTree uses three file types on disk. All are JSON; all are
human-readable and safe to edit by hand.

## `.scriptree` — one tool

The tool definition. Contains everything about how the tool is invoked
and how its form renders, but *not* any per-user state like the last
values you typed in. Schema v2.

```json
{
  "schema_version": 2,
  "name": "echo demo",
  "description": "Prints a message",
  "executable": "/bin/echo",
  "working_directory": null,
  "argument_template": ["{message}"],
  "params": [
    {
      "id": "message",
      "label": "Message",
      "description": "Text to print",
      "type": "string",
      "widget": "text",
      "required": false,
      "default": "hello",
      "section": ""
    }
  ],
  "sections": [],
  "env": {},
  "path_prepend": [],
  "source": { "mode": "manual", "help_text_cached": null }
}
```

Notable fields:

- **`argument_template`** — the ordered list of tokens that become argv.
  See [tool_editor.md](tool_editor.md) for substitution rules.
- **`params[].section`** — which section the parameter belongs to, or
  `""` if none. See [sections.md](sections.md).
- **`sections`** — ordered list of section headers with their default
  collapsed state.
- **`env`** / **`path_prepend`** — tool-level environment overrides. See
  [environment.md](environment.md).
- **`source`** — records how the tool was originally created (`manual`,
  `argparse`, `click`, `heuristic`) and caches the raw help text.

Empty collections (`env: {}`, `path_prepend: []`, `sections: []`) may be
omitted from the on-disk form to keep files compact. Readers must tolerate
their absence.

## `<name>.scriptree.configs.json` — sidecar configurations

Per-tool saved form values. Stored next to the `.scriptree` file as a
sidecar so the tool definition and the per-user state can be version
controlled independently. Schema v1.

```json
{
  "schema_version": 1,
  "active": "verbose",
  "configurations": [
    { "name": "default", "values": { "message": "hi" }, "extras": [] },
    {
      "name": "verbose",
      "values": { "message": "hello" },
      "extras": ["--debug"],
      "env": { "LOG_LEVEL": "debug" },
      "path_prepend": ["./bin"],
      "ui_visibility": { "command_line": false, "extras_box": false },
      "hidden_params": ["output_dir"],
      "prompt_credentials": true
    }
  ]
}
```

Per-configuration optional fields:

- **`ui_visibility`** — boolean flags controlling which UI elements are
  visible in standalone mode. Only non-default values are stored.
- **`hidden_params`** — list of param IDs hidden from the form in
  standalone mode. Their locked values come from `values`.
- **`prompt_credentials`** — when `true`, clicking Run prompts for a
  username/password to run the process under a different user (Windows).

See [configurations.md](configurations.md) for the full lifecycle.

## `.scriptreetree` — a tree of tools

A launcher that groups several `.scriptree` files into folders. Schema v1.

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
    }
  ]
}
```

Leaf paths can be absolute or relative to the `.scriptreetree` file.
Optional `display_name` on a leaf overrides the tool's `name` in the tree.

## `<name>.scriptreetree.treeconfigs.json` — tree-level configurations

Maps each sub-tool to a named configuration for standalone mode. Schema v1.

```json
{
  "schema_version": 1,
  "active": "default",
  "configurations": [
    {
      "name": "default",
      "tool_configs": {
        "./tools/backup.scriptree": "production",
        "./tools/restore.scriptree": "verbose"
      }
    }
  ]
}
```

Each entry in `tool_configs` maps a relative tool path to the name of the
configuration to apply when the tree is opened in standalone mode.

## Custom menus

Both `.scriptree` and `.scriptreetree` files support a `"menus"` array:

```json
"menus": [
  {
    "label": "Open logs",
    "menu": "Tools",
    "command": "notepad C:\\logs\\app.log",
    "tooltip": "View the application log file",
    "shortcut": "Ctrl+L"
  },
  { "label": "-", "menu": "Tools" },
  {
    "label": "Reports",
    "menu": "Tools",
    "children": [
      { "label": "Daily report", "command": "python reports/daily.py" },
      { "label": "Weekly report", "command": "python reports/weekly.py" }
    ]
  }
]
```

Menu item fields:

- **`label`** — display text. Use `"-"` for a separator.
- **`menu`** — top-level menu name (items with the same name are grouped).
  Defaults to "Tools".
- **`command`** — the command to execute (split safely, no shell).
- **`children`** — submenu items (recursive).
- **`shortcut`** — keyboard shortcut (e.g. `"Ctrl+L"`).
- **`tooltip`** — hover text.

In `.scriptree` files, menus appear as a menu bar at the top of the form.
In `.scriptreetree` files, menus appear in the standalone window's menu bar.

## Permissions files

The `permissions/` folder contains blank files whose names are capabilities
and whose filesystem write permissions control user access. See
[security.md](security.md) for the full reference.

```
permissions/
├── files/          (create, save, save-as)
├── editing/        (tool definitions, configs, env, visibility, etc.)
├── running/        (run tools, credentials, plugins, settings)
└── settings/       (permissions path)
```

Per-file permissions: place a `permissions/` folder alongside any
`.scriptree` or `.scriptreetree` file to add per-file restrictions.

## Compatibility notes

- **Legacy schema v1 `.scriptree` files** (no `sections` or `env` fields)
  load cleanly as flat-mode tools with no environment overrides.
- **Unknown fields** on any object are preserved when possible but not
  guaranteed — avoid stashing your own metadata in these files.
- **Hand-editing** is fine. ScripTree reformats the file on save, so
  whitespace changes will be overwritten the next time you click Save.
