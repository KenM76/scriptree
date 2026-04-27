# The tool editor

The editor is where you define what a tool looks like to the runner. You
reach it via:

- **File → New tool from executable...** — runs the parser first, opens
  the editor on the result
- **File → New blank tool** — opens an empty editor
- **Edit → Edit current tool** (Ctrl+E) — edit the currently-open tool

## Layout

```
┌──────────────────────────────────────────────────────────┐
│ Tool                                                     │
│   Executable: [.......] [Browse]                         │
│   Name:        [..........]                              │
│   Description: [..........]                              │
│   Environment: no overrides     [Edit environment...]    │
├──────────────┬───────────────────────────────────────────┤
│ Parameters   │ Property panel                            │
│ ─────────    │ ──────────                                │
│ Sections: +§ │ ID:          message                      │
│ ✎§ −§        │ Label:       Message                      │
│              │ Description: Text to echo                 │
│ ▸ message    │ Type:        string      ▾                │
│ ▸ verbose    │ Widget:      text        ▾                │
│              │ Required:    ☐                            │
│   + − ↑ ↓    │ Default:     hello                        │
│              │ Choices:     a=Alpha,b=Bravo              │
│              │ File filter: Text (*.txt);;All (*)        │
│              │ Section:     (none)       ▾               │
├──────────────┴───────────────────────────────────────────┤
│ Argument template           │ Form preview               │
│ [{message}          ]       │ [Message] [hello      ]    │
│ Live preview: echo hello    │ [✓ Verbose       ]         │
├──────────────────────────────────────────────────────────┤
│                         [Cancel] [Save as...] [Save]     │
└──────────────────────────────────────────────────────────┘
```

## Top strip — Tool

- **Executable** — full path to the binary/script. Click Browse to pick
  it with a native file dialog, or drag a file onto the field from
  Explorer (v0.1.11) — drag-drop works on every text and path widget
  in the editor and runner.
- **Name** — what the tool is called in the launcher and the runner title.
- **Description** — shown below the name in the runner.
- **Environment** — opens a popup to set tool-level environment variables
  and PATH prepends that apply to every run. See [environment.md](environment.md).

## Parameters list

The left pane lists parameters in the order they'll appear on the form.
Use:

- **+** to add a new parameter with sensible defaults (string, text widget)
- **−** to delete the selected parameter
- **↑ / ↓** to move the selected parameter up or down

Click a parameter to load it into the property panel on the right.

### Sections toolbar

Above the parameter list is a small section toolbar: **+§ ✎§ −§ ↑ ↓**.
These buttons manage "sections" — named collapsible groups of parameters.
The `↑` / `↓` buttons reorder the selected section in the list, changing
where it appears in the runner. See [sections.md](sections.md).

If the tool has no sections, the parameter list shows them flat. As soon
as you add a section, the list shows each param's section suffix after
the label.

### Custom menus

Below the environment row at the top of the editor is a **Edit menus...**
button. It opens a dedicated editor for the custom menu bar the runner
will render above the form when the tool is run:

- **+ Menu** — add a top-level menu name (e.g. "Tools", "Reports").
- **+ Action** — add an action item under the selected menu or submenu.
  Actions carry a shell command, an optional keyboard shortcut, and a
  tooltip.
- **+ Submenu** — add a nested menu. Submenus can hold their own
  actions, further submenus, and separators.
- **+ Separator** — add a horizontal line between items.
- **↑ / ↓** — reorder within the current parent.
- **Remove** — delete the selected item.

The tree on the left shows the full structure; the right panel edits
the selected item's details. Changes are staged in memory — nothing is
written to the `.scriptree` file until you click Save in the main
editor.

## Property panel

The right pane edits whichever parameter is currently selected:

- **ID** — the placeholder name used in templates (e.g. `{id}`). Must be
  a valid Python identifier.
- **Label** — what the runner displays next to the widget.
- **Description** — tooltip text. The parser also reads this to promote
  widgets (see [parsers/](parsers) docs).
- **Type** — one of `string`, `integer`, `float`, `bool`, `path`, `enum`,
  `multiselect`. Changing the type filters the Widget dropdown to show
  only compatible options.
- **Widget** — which control the runner uses: `text`, `textarea`, `number`,
  `checkbox`, `dropdown`, `file_open`, `file_save`, `folder`,
  `enum_radio`.
- **Required** — if checked, Run fails until this field has a value.
- **Do not save value** — the value is never persisted into the
  configuration sidecar (useful for passwords, tokens, scratch values).
  The user's most recent entry is kept in the form during the session
  but is lost when the tool is reloaded.
- **Do not auto-split** — opt out of the string-passthrough auto-split
  rule. By default, when a string param's `{id}` placeholder is the
  entire template token and its value contains whitespace, ScripTree
  splits the value into multiple argv tokens. Check this box to keep
  the value atomic (single argv token) even with embedded spaces —
  use it for a string field that genuinely holds one logical value
  with whitespace, like a sentence or a path. Only meaningful for
  string-typed params; ignored otherwise.
- **Default** — the value the widget is initialized with.
- **Choices** — for enum / multiselect, a comma-separated list. Each entry
  is either a bare value or `value=label`:

  ```
  fast=Fast mode,slow=Slow mode,auto
  ```

  The runner shows the labels in the dropdown; argv always carries the
  raw value.

- **File filter** — for path widgets, a QFileDialog filter string like
  `Text (*.txt);;All (*)`.
- **Section** — which section this param belongs to (if any sections
  have been declared).

## Argument template

The lower-left box defines the argv that the tool is invoked with. One
entry per line:

- Plain literals (e.g. `list-components`) are emitted as-is.
- `{param_id}` is substituted with the current value of that parameter.
- `{param_id?--flag}` is a conditional: for a bool parameter, it emits
  `--flag` when true and nothing when false.
- `{param_id?--flag=}` emits `--flag=<value>` when the value is non-empty
  and nothing when it is.
- **Multiple tokens on one line**, separated by spaces, form a *group*
  that emits together or not at all. Useful for flag-value pairs like
  `/S {system}` — both tokens appear together or both drop when
  `{system}` is empty.

Below the template is a **Live preview** that re-renders on every edit
using the current defaults, so template bugs are immediately visible.

## Form preview

The lower-right box shows a live preview of what the runner will display
when a user opens this tool. Widgets are disabled so you can't
accidentally type into them — it's purely a visual check that your
parameters render with the right widgets and labels.

## Saving

- **Save** — write to the current file path (or ask if the tool is new).
- **Save as...** — always prompts for a new file path.
- **Cancel** — discard edits and return to the previous view.

Edits are held in memory until Save; Cancel discards everything.
