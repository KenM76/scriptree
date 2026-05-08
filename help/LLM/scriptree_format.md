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
  "cell": {/* CellAppearance, optional, see below — v0.2.7+ */},
  "interactive": "bool, optional, default false — v0.3.0+",
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
  `["--out", "{out}"]`.

  **Repeatable-flag pattern.** A bare `"{id}"` token whose param is a
  `string` (any `line_edit`/`text` widget) gets *string-passthrough*
  treatment — its value is shlex-tokenized into multiple argv elements.
  This is how a user types `--include foo --include bar` into one
  field and gets four argv tokens. The split honors quote rules so
  `--name "John Doe"` produces three tokens, not four. Auto-split
  fires only when the placeholder is the entire template token; it
  does **not** apply to embedded placeholders (`"--out={x}"`), token
  groups (`["--include", "{x}"]`), conditional flags
  (`"{id?--flag}"`), or non-string param types.

  See [argument_template.md](argument_template.md) for the full
  grammar, the auto-split details, and common mistakes.
- `params` — order matters; it's the form layout order within each
  section.
- `sections` — may be omitted. If present, defines section ordering and
  default collapsed state. Parameters with `section: ""` fall into a
  synthetic "Other" bucket at the end.
- `env` / `path_prepend` — tool-level environment overrides, applied to
  every run regardless of active configuration. Omitted from the on-disk
  form when empty.
- **Sibling imports (Python tools).**  If your tool is a Python script
  laid out as a folder with `_helper.py` / `_common.py` siblings the
  entry script imports, ScripTree v0.3.12+ makes those imports work
  reliably across:
    * the bundled embeddable Python that ships in `lib/python/` (whose
      `python<ver>._pth` file would otherwise disable script-dir
      auto-prepending),
    * system Python with `-P` or `PYTHONSAFEPATH=1` set,
    * `runpy`-style invocations.

  The runner injects two environment variables before spawn:
    * `SCRIPTREE_TOOL_DIR` — absolute path of the `.scriptree` file's
      parent folder.  Read by the bundled Python's `sitecustomize.py`
      (at `lib/python/Lib/site-packages/sitecustomize.py`) and
      prepended to `sys.path`.
    * `PYTHONPATH` — same directory prepended (any pre-existing
      PYTHONPATH entries are preserved at the tail).

  **You do not need to add any boilerplate** to your tool scripts —
  `import _helper` from a sibling module simply works.  If you have
  a wrapper script that needs to set `SCRIPTREE_TOOL_DIR` to a
  different directory (e.g. a meta-tool that runs sub-tools), the
  wrapper-set value is preserved (the runner only fills the var
  when it isn't already set).
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

> **Default to using sections.** When generating a `.scriptree` for a
> tool with more than ~4 parameters, group them into 2–4 named
> sections. For 10+ params, prefer tab-mode sections. See the
> [LLM README's "Form design defaults"](README.md) for the heuristic
> table and rationale — flat ungrouped forms are the most common
> failure mode of AI-generated tools.

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

## `cell` sub-object (v0.2.7+, optional)

Controls how the V3 cell shell paints a launcher cell bound to this
`.scriptree`. **Entirely optional** — when every field sits at its
default the whole sub-object is omitted from the on-disk JSON, so
legacy files stay byte-identical.

```json
"cell": {
  "icon": "string, optional — path to an icon file",
  "icon_data": "string, optional — base64-encoded image bytes (embedded)",
  "icon_format": "string, optional — \"png\" | \"jpg\" | \"jpeg\" | \"svg\" | ... — only meaningful when icon_data is set",
  "text_label": "string, optional — explicit text override for the cell label",
  "icon_scale": "number, optional — relative scale, range 0.25–2.00, default 1.00",
  "label_opacity": "number, optional — alpha multiplier, range 0.20–1.00, default 1.00",
  "fill_color": "string, optional — \"#RRGGBB\" override for the cell fill (v0.3.6+)",
  "text_color": "string, optional — \"#RRGGBB\" override for the label text colour (v0.3.8+)"
}
```

### Field rules

| Field | Type | Default | Range | Notes |
|-------|------|---------|-------|-------|
| `icon` | string | `""` (empty) | — | Path to an icon file. **Forward slashes preferred**, relative resolution: if the icon sits inside the `.scriptree` file's directory tree, the writer normalises to `./...`-style relative-to-catalog. Otherwise an absolute path is stored. Either form loads. Mutually exclusive with `icon_data` (Embed clears `icon`; Unembed clears `icon_data` and writes a fresh relative `icon`). |
| `icon_data` | string | `""` | — | Base64-encoded image bytes. When non-empty, the cell renders from this in-JSON payload. Set by **Embed** in Settings → Cell label; cleared by **Unembed (Save as…)**. |
| `icon_format` | string | `""` | — | Image format hint for `icon_data` (`"png"`, `"jpg"`, `"svg"`, etc.). Required only when `icon_data` is set; ignored when `icon` is used. |
| `text_label` | string | `""` | — | Explicit label text. When non-empty, takes priority over auto-derived letters but loses to icons. |
| `icon_scale` | float | `1.00` | `[0.25, 2.00]` | Relative — the painter resizes the icon proportionally to the cell's current `size_px`. So a 100 % icon "feels the same size" on a 56-px cell as on a 96-px cell. Out-of-range values are clamped silently at load. |
| `label_opacity` | float | `1.00` | `[0.20, 1.00]` | Alpha multiplier on the painted label / icon. Out-of-range values are clamped. |
| `fill_color` | string | `""` | `#RRGGBB` (v0.3.6+) | Override for the cell's fill colour. Empty = use branding default. Alpha is owned by the separate `transparency` slider; this field is RGB only. Invalid hex is silently dropped at load. |
| `text_color` | string | `""` | `#RRGGBB` (v0.3.8+) | Override for the label text colour (auto-letters or `text_label`; icon labels are not tinted). Empty = follow stroke-derived default. Alpha is computed from `transparency × label_opacity` at paint time. Invalid hex is silently dropped. |

### Label-painting priority (recap)

1. `icon_data` → render embedded image at `icon_scale` × `label_opacity`.
2. `icon` (file path) → render the file the same way.
3. `text_label` → render the explicit text at `label_opacity`.
4. **Auto-derived letters** from `name` (CamelCase precedence, skip-word
   filter, two-letter fallback). See `help/cell_shell.md` for the full
   rules.
5. `?` if all of the above produce nothing.

### Compactness

The whole `cell` sub-object is omitted from the on-disk JSON when
every field is at its default. Likewise, individual fields with
default values are omitted. Readers must treat any missing field as
its default.

### Example with an embedded icon

```json
"cell": {
  "icon_data": "iVBORw0KGgoAAAANSUhEUgAAACAAAAAg...",
  "icon_format": "png",
  "icon_scale": 1.25,
  "label_opacity": 0.85
}
```

### Example with a relative icon path

```json
"cell": {
  "icon": "./icons/dxf-export.svg",
  "icon_scale": 0.8
}
```

## `interactive` flag (v0.3.0+, optional)

Top-level boolean.  When `true`, the runner spawns the child process
with `stdin=PIPE` and shows a send-line widget below the output
pane (line edit + `y` / `n` / `!` / `q` quick-response buttons +
Send + End input).  Lines typed into the widget — or sent via the
quick buttons — are written to the running tool's stdin, so tools
can implement query-replace-style prompt loops (Emacs M-%) inside
the GUI.

```json
"interactive": true
```

Field rules:

- **Type** — `bool`.
- **Default** — `false`.  Omitted from the JSON when at the default
  so v0.2.x files round-trip byte-identical.
- **Permission gate** — the runner ALSO requires the
  `interactive_stdin` capability to be granted at the app level
  (file present and writable in the deployed `permissions/`
  directory).  When the tool opts in but the permission denies,
  the runner falls back to one-shot mode and prints a one-line
  warning into the output pane.
- **Run-as-user incompatibility** — interactive mode is suppressed
  when a configuration is set to `prompt_credentials: true`.  A
  warning is emitted on stderr; the run proceeds non-interactively.
- **Stdout buffering** — tools that read from stdin should
  `flush=True` after every prompt (`print(..., flush=True)` in
  Python) so the runner sees each prompt as it's emitted, not all
  at once after the script exits.

Use `interactive: true` for tools that genuinely benefit from a
live prompt loop:

- Find / replace with per-match accept / skip (`query-replace`).
- Confirm-each-file batch operations.
- REPL-style exploration tools.

Don't use `interactive: true` for tools that just emit progress
bars or status output — those work fine without stdin.

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
