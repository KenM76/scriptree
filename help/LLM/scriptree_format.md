# `.scriptree` file format (schema v2)

Canonical reference. If this document and `scriptree/core/io.py`
disagree, the code wins — open an issue and fix the docs.

## Top-level shape

```json
{
  "schema_version": 2,
  "name": "string, required",
  "description": "string, optional, default \"\"",
  "executable": "string, required — absolute, relative-to-.scriptree, or bare PATH name",
  "working_directory": "string or null, optional — absolute or relative-to-.scriptree",
  "argument_template": [/* list of strings AND/OR nested lists; see below */],
  "params": [/* list[ParamDef], may be empty */],
  "sections": [/* list[SectionDef], may be empty/omitted */],
  "env": { "KEY": "value" },
  "path_prepend": ["directory", "..."],
  "menus": [/* list[MenuItemDef], optional, omitted when empty */],
  "source": {
    "mode": "manual | argparse | click | docopt | heuristic | powershell | winhelp",
    "help_text_cached": "string or null"
  }
}
```

### Field-level rules

- `schema_version` — int. Current: `2`. v1 files (no `sections`, no
  `env`, no `path_prepend`) load cleanly; the loader upgrades them in
  memory.
- `name` — user-visible. May contain spaces. Used as the window title.
- `executable` — must exist on disk at load time? No. ScripTree
  tolerates missing executables; the user sees an error at Run time.
  **Relative paths** (starting with ``./`` or ``../``, or any path
  that isn't absolute and isn't a bare PATH name like ``python``)
  are resolved against the **.scriptree file's directory** at run
  time, not against the process's current working directory. This
  makes a folder containing a .scriptree and its sibling executables
  portable — move the folder, the tool still works. Bare names like
  ``python``, ``robocopy``, or ``ffmpeg`` fall back to PATH resolution
  (they don't exist as sibling files).
- `working_directory` — if null, `dirname(executable)` is used as cwd.
  **Relative paths** are resolved against the .scriptree file's
  directory at run time, same as ``executable``.
- `path_prepend` — entries' relative paths are resolved against
  ``working_directory`` (or the resolved executable directory), which
  in turn anchors on the .scriptree file's location. Net effect:
  a fully relative ToolDef is portable without manual path fixups.
- `argument_template` — a list whose entries are either **strings**
  (one argv token each) or **nested lists of strings** (a *token
  group* that emits all elements together or drops them together).
  **For flag + value pairs use a nested list** — writing
  `"--out {out}"` as a single string produces one argv token with
  a literal space, which almost every CLI rejects. Correct:
  `["--out", "{out}"]`. See [argument_template.md](argument_template.md)
  for the full grammar and common mistakes.
- `params` — order matters; it's the form layout order within each
  section.
- `sections` — may be omitted. If present, defines section ordering and
  default collapsed state. Parameters with `section: ""` fall into a
  synthetic "Other" bucket at the end.
- `env` / `path_prepend` — tool-level environment overrides, applied to
  every run regardless of active configuration. Omitted from the on-disk
  form when empty.
- `source` — provenance. Always present; `help_text_cached` is null for
  manually-built tools.

## `ParamDef` shape

```json
{
  "id": "python_identifier, required, unique within params[]",
  "label": "string, required",
  "description": "string, optional, default \"\"",
  "type": "string|integer|float|bool|path|enum|multiselect",
  "widget": "text|textarea|number|checkbox|dropdown|file_open|file_save|folder|enum_radio",
  "required": "bool, default false",
  "default": "value of the param's type, or \"\" / null",
  "choices": ["value", "value2"],
  "choice_labels": ["Human label", "Human label 2"],
  "file_filter": "Qt file filter string, path widgets only",
  "section": "string, default \"\""
}
```

### Type × widget compatibility

| type          | allowed widgets                       |
|---------------|---------------------------------------|
| `string`      | `text`, `textarea`                    |
| `integer`     | `number`, `text`                      |
| `float`       | `number`, `text`                      |
| `bool`        | `checkbox`                            |
| `path`        | `file_open`, `file_save`, `folder`    |
| `enum`        | `dropdown`, `enum_radio`              |
| `multiselect` | `dropdown` (multi-select mode)        |

Changing `type` in the editor narrows the `widget` dropdown
automatically. Hand-edited files with incompatible combinations load
but the editor snaps the widget back on first save.

### `choices` and `choice_labels` fields

For `enum` / `multiselect` only. The canonical on-disk format uses **two
parallel lists**:

```json
"choices": ["fast", "slow", "auto"],
"choice_labels": ["Fast mode", "Slow mode", "Auto-detect"]
```

- `choices` — the raw values that go into argv. **Always flat strings.**
- `choice_labels` — human-readable labels shown in the dropdown. Same
  length as `choices`. If `choice_labels` is omitted or shorter, the
  value itself is used as the label for any missing entries.

The editor exposes this as a single-line string for ease of editing:
`fast=Fast mode,slow=Slow mode,auto`. Bare entries (no `=`) use the
value as its own label.

> **Do NOT use `[value, label]` pair format** for `choices`. The loader
> tolerates it for compatibility, but the canonical form is two flat
> lists as shown above.

### `default` semantics

- `string` / `path` — empty string `""` means "no default".
- `integer` / `float` — `0` is the null default.
- `bool` — `false` is the null default.
- `enum` — must be one of the values in `choices`, or `""` for "no
  selection".
- `multiselect` — a list of values, may be empty.

## `SectionDef` shape

```json
{
  "name": "string, non-empty, unique within sections[]",
  "collapsed": "bool, default false",
  "layout": "collapse | tab (optional, default collapse)"
}
```

Sections with duplicate names are rejected by the loader.

### Per-section `layout` field

Each section independently controls how it renders in the runner form.

| Value | Rendering |
|-------|-----------|
| `"collapse"` | A collapsible `QGroupBox`. The `collapsed` field controls initial state. This is the default. |
| `"tab"` | Rendered as a page in a `QTabWidget`. Each tab scrolls independently. The `collapsed` field is ignored. |

**Consecutive tab sections are grouped into a single `QTabWidget`.**
A collapse section between two tab runs creates separate tab widgets
above and below it.  This means you can freely mix collapsible sections
and tabs in the same tool:

```json
"sections": [
  { "name": "Source & Destination", "layout": "collapse" },
  { "name": "Copy Options", "layout": "tab" },
  { "name": "File Selection", "layout": "tab" },
  { "name": "Retry", "layout": "tab" },
  { "name": "Logging", "layout": "collapse" }
]
```

This renders as: a collapsible "Source & Destination" group, then a
3-tab widget (Copy Options / File Selection / Retry), then a
collapsible "Logging" group.

> **Legacy `section_layout` field**: older files may have a tool-level
> `"section_layout": "tabs"` instead of per-section `layout`. The
> loader applies the tool-level default to every section that doesn't
> declare its own `layout`. New files should use per-section `layout`
> and omit the tool-level field.

## `source` block

```json
{
  "mode": "manual",
  "help_text_cached": null
}
```

`help_text_cached` lets the editor re-run parsing with improved
heuristics without re-probing the executable. It's stored verbatim —
newlines, ANSI, trailing whitespace and all.

## `menus` array (optional)

Custom menu items rendered at the top of the form (or in the standalone
window's menu bar). Omitted when empty.

```json
{
  "label": "string, required — display text, or \"-\" for separator",
  "menu": "string, optional — top-level menu name, default \"Tools\"",
  "command": "string, optional — command to execute (split safely, no shell)",
  "shortcut": "string, optional — e.g. \"Ctrl+L\"",
  "tooltip": "string, optional",
  "children": [/* list[MenuItemDef], optional — submenu */]
}
```

Items with the same `menu` value are grouped under one menu. Commands
are split via `CommandLineToArgvW` (Windows) or `shlex.split` — never
`shell=True`.

## Loader invariants

The `tool_from_dict` function enforces:

1. `schema_version` is an int and ≤ current version.
2. `name` is a non-empty string.
3. `executable` is a non-empty string.
4. `argument_template` is a list whose entries are each either a
   string (single argv token) or a list of strings (token group that
   emits/drops as a unit).
5. Every `ParamDef.id` matches `^[A-Za-z_][A-Za-z0-9_]*$`.
6. Every `ParamDef.id` is unique within `params[]`.
7. Every `ParamDef.type` and `widget` is from the allowed sets above.
8. Every `ParamDef.section`, if non-empty, names a section in
   `sections[]`.
9. Every `SectionDef.name` is non-empty and unique.

Violations raise `ValueError` with a message pointing to the offending
field.
