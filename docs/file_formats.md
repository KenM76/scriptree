# File formats

ScripTree uses three file types on disk. All are JSON; all are
human-readable and safe to edit by hand.

## `.scriptree` — one tool

The tool definition. Contains everything about how the tool is invoked
and how its form renders, but *not* any per-user state like the last
values you typed in. Schema v3 (current). v0.5.0 renamed `bool` →
`boolean`, `float` → `number`, `file_open` → `file`, `file_save` →
`save_file`, `enum_radio` → `radio`. The runtime hard-rejects v1/v2
files and points the user at `python -m scriptree migrate`.

```json
{
  "schema_version": 3,
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

### Optional `cell` sub-object (V3, v0.2.7+)

`.scriptree` files can carry a top-level `"cell"` sub-object that
controls how the V3 cell shell paints a launcher cell bound to this
tool — icon, text label, scale, opacity. Entirely optional; omitted
when every field is at its default, so legacy files stay
byte-identical. See [`LLM/scriptree_format.md`](LLM/scriptree_format.md)
for the full schema.

## `<name>.scriptree.configs.json` — sidecar configurations

Per-tool saved form values. Stored next to the `.scriptree` file as a
sidecar so the tool definition and the per-user state can be version
controlled independently. Sidecar schema v1 (governed by
`configs.py::CONFIGS_SCHEMA_VERSION`, independent of the parent
`.scriptree`'s `SCHEMA_VERSION`).

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

A launcher that groups several `.scriptree` files into folders. Schema v3 (same `SCHEMA_VERSION` as `.scriptree`).

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
    }
  ]
}
```

Leaf paths can be absolute or relative to the `.scriptreetree` file.
Optional `display_name` on a leaf overrides the tool's `name` in the tree.
A `.scriptreetree` may also carry a top-level `"cell"` sub-object
(same schema as on `.scriptree`) for V3 cell-shell launcher
appearance.

## `.scriptreering` — V3 cell + ring layout

A `.scriptreering` file captures one or more **cells** (the floating
desktop launchers spawned by `run_scriptreering.bat`) — their
positions, sizes, transparency, shape, and which catalog each cell
points at. The format is layout-only; cell appearance (icon / text /
scale / opacity) lives in the bound catalog's `cell` sub-object,
not in the ring file. See [`cell_shell.md`](cell_shell.md) for the
user-facing UX and [`LLM/scriptreering_format.md`](LLM/scriptreering_format.md)
for the JSON schema.

## `<name>.scriptreetree.treeconfigs.json` — tree-level configurations

Maps each sub-tool to a named configuration for standalone mode. Sidecar
schema v1 (this file is governed by `configs.py::CONFIGS_SCHEMA_VERSION`,
which is independent of the `model.py::SCHEMA_VERSION` of the parent
`.scriptree` / `.scriptreetree`).

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

## Action buttons (v0.8.0a11+)

`.scriptree` files can also declare an `"actions"` array — named
fixed-argv presets rendered as a second button row next to Run in
the tool runner. See [tool_runner.md](tool_runner.md#action-buttons-v080a11)
for the UI walkthrough and `LLM/scriptree_format.md` for the
field-level schema.

```json
"actions": [
  {"id": "status", "label": "Status", "argv": ["status", "--short"]},
  {"id": "log10",  "label": "Last 10", "argv": ["log", "--oneline", "-10"],
   "popup": "auto"}
]
```

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

- **Schema v3 is a hard gate.** The v0.8+ runtime refuses to load v1/v2
  files with an error pointing at `python -m scriptree migrate`. Run the
  migrator on old files; it rewrites widget names (`file_open`→`file`,
  etc.) and bumps the schema header.
- **Unknown fields** on any object are preserved when possible but not
  guaranteed — avoid stashing your own metadata in these files.
- **Hand-editing** is fine. ScripTree reformats the file on save, so
  whitespace changes will be overwritten the next time you click Save.
