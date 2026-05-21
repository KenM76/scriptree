# Parameter types and widgets

Reference matrix of legal type × widget combinations, default values,
and coercion rules.

> **v0.5.0 / schema_version 3 — canonical-names rename (breaking).**
> Type and widget names are now JSON-Schema / HTML5 aligned. Old names
> (`bool`, `float`, `file_open`, `file_save`, `enum_radio`) are **no
> longer accepted** — run `python -m scriptree migrate <path>` to
> upgrade v2 files in place. See the bottom of this doc for the full
> rename map.

## Types

| type          | Python type on read   | JSON form               |
|---------------|-----------------------|-------------------------|
| `string`      | `str`                 | string                  |
| `integer`     | `int`                 | integer                 |
| `number`      | `float`               | number                  |
| `boolean`     | `bool`                | boolean                 |
| `path`        | `str` (path string)   | string                  |
| `enum`        | `str`                 | string (one of choices) |
| `multiselect` | `list[str]`           | array of strings        |

The first four mirror [JSON Schema's primitive types][jsonschema-types]
verbatim. `path` / `enum` / `multiselect` are ScripTree extensions —
they don't have direct JSON-Schema analogues but they round-trip as
strings (or arrays of strings) so JSON-Schema validators still
accept the files.

[jsonschema-types]: https://json-schema.org/understanding-json-schema/reference/type

## Widgets

| widget       | Qt class                              | Used for              |
|--------------|---------------------------------------|-----------------------|
| `text`       | `QLineEdit`                           | short strings, ints, numbers, masked input |
| `textarea`   | `QPlainTextEdit`                      | long strings, regexes |
| `number`     | `QSpinBox` / `QDoubleSpinBox`         | integer / number      |
| `checkbox`   | `QCheckBox`                           | booleans              |
| `dropdown`   | `QComboBox`                           | enums, multiselects   |
| `checkbox_list` | scroll of `QCheckBox` (+ optional tri-state master) | multiselects, esp. dynamic provider-populated lists |
| `radio`      | `QButtonGroup` of `QRadioButton`      | enums (small sets)    |
| `file`       | line edit + Browse (`getOpenFileName`) | existing input files  |
| `save_file`  | line edit + Browse (`getSaveFileName`) | output files to write |
| `folder`     | line edit + Browse (`getExistingDirectory`) | directories     |
| `folder_list` | `QListWidget` + Add / Remove / Up / Down | ordered list of folders (search paths, ignore lists, library roots) |
| `file_list`  | `QListWidget` + Add / Remove / Up / Down | ordered list of files |

Widget names mirror the [HTML5 form-element vocabulary][html5-forms]
where there's a direct analogue — `text`, `textarea`, `number`,
`checkbox`, `radio`, `file` all map straight onto their `<input>`
counterparts. `save_file` (for output paths) and `folder` (for
directories) are ScripTree extensions that HTML doesn't have. `dropdown`
is the conventional name for what HTML calls `<select>`.

[html5-forms]: https://developer.mozilla.org/en-US/docs/Web/HTML/Element/input

### Drag-and-drop (v0.1.11+)

`text`, `textarea`, `file`, `save_file`, and `folder` widgets all
accept file/folder drops from Explorer. The implementation is two thin
Qt subclasses in `scriptree/ui/widgets/param_widgets.py`:

- `_DroppableLineEdit(QLineEdit)` — replaces the field's text with the
  first dropped local-file URL. Used by `text`, `file`, `save_file`,
  and `folder`.
- `_DroppablePlainTextEdit(QPlainTextEdit)` — inserts dropped paths at
  the cursor, one per line. Used by `textarea`.

Subclasses are required because Qt binds drag/drop slots on the C++
vtable at construction time — monkey-patching `dropEvent` on a stock
`QLineEdit` instance silently does nothing. Native text drops (e.g.
selecting text from another field) keep working via the parent
implementation's fallback.

## Legal combinations

| type          | legal widgets                       |
|---------------|-------------------------------------|
| `string`      | `text`, `textarea`                  |
| `integer`     | `number`, `text`                    |
| `number`      | `number`, `text`                    |
| `boolean`     | `checkbox`                          |
| `path`        | `file`, `save_file`, `folder`       |
| `enum`        | `dropdown`, `radio`                 |
| `multiselect` | `dropdown`, `checkbox_list`, `folder_list`, `file_list` |

> **v0.6.0** — `multiselect` may now render as `checkbox_list` (a
> scrollable column of checkboxes with an optional select-all/none
> master via `select_all: true`). Any param type may also pull its
> choices/value from an external command at form-open time via
> `choices_provider`. See
> [`dynamic_providers.md`](dynamic_providers.md).
>
> **v0.6.28** — `multiselect` may also render as `folder_list` /
> `file_list` (a user-composed ordered list of paths with Add /
> Remove / Up / Down buttons; see the **Multi-path pickers**
> section below for details and the new `must_exist` / `min_items`
> / `max_items` fields).

Hand-edited files with illegal combinations load, but on first save the
editor snaps the widget to the first legal value. `scriptree validate`
flags the mismatch up front so you can fix it before run-time.

## Default values per type

When a new param is added in the editor or when `default` is missing in
a hand-edited file:

| type          | default                       |
|---------------|-------------------------------|
| `string`      | `""`                          |
| `integer`     | `0`                           |
| `number`      | `0.0`                         |
| `boolean`     | `false`                       |
| `path`        | `""`                          |
| `enum`        | first choice, or `""` if none |
| `multiselect` | `[]`                          |

## Coercion on read

Values come out of form widgets typed, but sidecar JSON can hold
anything. `load_configs` coerces:

- `boolean` — truthy Python object → `bool`.
- `integer` — `int(value)`, raises `ValueError` on non-numeric.
- `number` — `float(value)`, raises `ValueError` on non-numeric.
- `enum` — validated against `choices`; mismatch falls back to default.
- `multiselect` — wrapped in list if a single string was stored.
- `string` / `path` — `str(value)`.

Coercion failures produce a warning dialog but do not prevent the tool
from loading.

## Widget-specific fields

### `folder_list`, `file_list` (v0.6.28+)

Both render the same shell: a `QListWidget` of paths with an
Add / Remove / Up / Down button row and a live count label.  The
user composes the list manually — there's no provider; for "read
folders from an external command" use `choices_provider` +
`checkbox_list`.

| field          | type            | default | meaning |
|----------------|-----------------|---------|---------|
| `type`         | `"multiselect"` | required | runner emits a `list[str]` (same as the multi-select dropdown) |
| `widget`       | `"folder_list"` or `"file_list"` | required | picks the dialog used by Add |
| `default`      | `list[str]`     | `[]`    | preseeded entries; not validated against `must_exist` |
| `file_filter`  | `str`           | `""`    | **`file_list` only** — Qt filter for the Add dialog |
| `must_exist`   | `bool`          | `false` | when `true`, Add rejects a path that doesn't currently exist on disk (user-typed defaults / config-loaded entries skip the check so a since-deleted folder still loads) |
| `min_items`    | `int`           | `0`     | soft cap — surfaced in the count label and (when `required`) in the form's validate step |
| `max_items`    | `int` / `null`  | `null`  | soft cap — Add is greyed when reached |

Argv emission is unchanged from any other `multiselect`: the
runner comma-joins the list into one token by default, or fires
one token per entry when the argument template uses the
repeating-token pattern (see `argument_template.md`).

Example — a CLI that takes `--include FOLDER` once per folder:

```json
{
  "id": "search_folders",
  "label": "Folders to search",
  "type": "multiselect",
  "widget": "folder_list",
  "default": [],
  "must_exist": true,
  "min_items": 1
}
```

```jsonc
"argument_template": [
  ["--include", "{search_folders}"]   // repeating-token group
]
```

> **When to pick `folder_list` over `choices_provider` +
> `checkbox_list`:** `folder_list` is for the user composing a
> list (search paths, ignore-folder lists).  `choices_provider` is
> for ScripTree reading external state (a list of open documents,
> running containers, remote branches).  They compose — a future
> `folder_list` could carry a `choices_provider` that suggests
> recently-used folders — but the base capability is independent.

### `file`, `save_file`

Read `file_filter` from the param. Format is Qt's filter string:

```
Text files (*.txt);;All files (*)
```

First entry is the default filter. If missing, falls back to `All files (*)`.

### `enum`, `multiselect`

The on-disk format uses **two parallel flat lists**:

```json
"choices": ["fast", "slow", "auto"],
"choice_labels": ["Fast mode", "Slow mode", "Auto-detect"]
```

- `choices` — raw string values for argv. **Always a flat list of strings.**
- `choice_labels` — human-readable labels for the dropdown. If omitted
  or shorter than `choices`, the value itself is shown as the label.

In the editor, both fields are edited as a single comma-separated string:

```
fast=Fast mode,slow=Slow mode,auto
```

Bare entries (no `=`) use the value as its own label. Parsing strips
whitespace around commas and `=`.

> **Do NOT** write `choices` as `[[value, label], ...]` pairs. The
> loader accepts that format for compatibility, but the canonical form
> is two flat lists.

#### Preset bundles — the highest-leverage `enum` pattern

`choices` values are emitted **verbatim** into argv. They do not have
to be single flags or single tokens. **A single dropdown choice can
carry an entire filter chain, a complete expression, a paired
width:height combo, a multi-token configuration string — anything the
underlying CLI accepts as one token.** Pair with `choice_labels` to
show a human-readable description.

Example — resize presets for an ffmpeg wrapper:

```json
{
  "id": "vf",
  "type": "enum",
  "widget": "dropdown",
  "default": "scale=-2:720:flags=lanczos",
  "choices": [
    "scale=-2:720:flags=lanczos",
    "scale=1920:1080:flags=lanczos",
    "scale=3840:2160:flags=lanczos",
    "scale='min(1280,iw)':-2:flags=lanczos",
    "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black"
  ],
  "choice_labels": [
    "720p (HD) — height 720, aspect preserved",
    "1080p exact — 1920×1080",
    "4K exact — 3840×2160",
    "Cap to 1280 wide (downscale only)",
    "Letterbox to 1080p (16:9 black bars)"
  ]
}
```

The argv emitted for the letterbox preset is one token — `"-vf",
"scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black"`
— and ffmpeg parses the comma-chained filter graph internally.

**When wrapping a CLI with a complex filter / expression vocabulary,
prefer 15–25 named presets over a free-form text field.** The
free-form field is the escape hatch, not the primary UI. Presets do
the heavy lifting of teaching the user what's possible; without
them, the user has to know the filter syntax to use the tool at all.

This is the single highest-leverage pattern in the schema. Use it
heavily.

##### Common preset-bundle use cases

| Domain | Example presets to bundle |
|---|---|
| Resolutions | `scale=-2:720:flags=lanczos`, `scale=1920:1080`, letterbox/pillarbox to fixed canvas |
| Frame selection | `fps=1`, `fps=1/10`, `select='not(mod(n\,100))'`, `select='eq(pict_type\,I)'`, `thumbnail` |
| Audio normalisation | `volume=0.5`, `volume=+6dB`, `loudnorm=I=-16:TP=-1.5:LRA=11` (streaming), `loudnorm=I=-23:TP=-2:LRA=7` (broadcast) |
| Speed / setpts | `setpts=0.5*PTS` paired with `atempo=2.0` |
| Rotation / flip | `transpose=1`, `transpose=2`, `transpose=2,transpose=2`, `hflip,vflip` |
| Compression presets | `-preset medium -crf 23` paired as one bundled value where the CLI accepts it |
| Position expressions | `main_w-overlay_w-20:main_h-overlay_h-20`, `(main_w-overlay_w)/2:(main_h-overlay_h)/2` |
| Encoder profile / level | `high@4.1`, `main10@5.1` (when the CLI accepts the combined form) |

#### `radio` — radio buttons for mode switches

When the choice count is small (2–5) and the choice **gates which
other fields below it are relevant**, use `radio`. Same `choices` /
`choice_labels` format as `dropdown`; only the rendering differs.

##### When `radio` beats `checkbox`

A checkbox conveys "optional flag, on or off." A radio conveys
"pick one of these mutually exclusive modes." When fields below the
control depend on the user's choice, the radio is the correct widget
because it cues the user that **the mode is the first thing to
decide**. Examples that should be `radio`, not `checkbox`:

- **Stream copy / re-encode** for trim, concat, convert. Codec /
  preset / CRF below only matter in re-encode mode.
- **Burn / mux / extract** for a subtitles tool. Each mode wires up
  a completely different field set.
- **Fast seek / accurate seek** for a thumbnail or trim tool. The
  choice changes where `-ss` lands in the argv (before vs. after
  `-i`).
- **Quiet / verbose / debug** log-level switches when the underlying
  flag takes one of a small fixed set of values.

If the choice is a true binary toggle and nothing else below it
cares (`-y` overwrite, `-vn` drop video, `-sn` drop subtitles),
`checkbox` is fine.

A **(none)** option that emits nothing is just an empty-string
choice with a friendly label:

```json
{
  "id": "verbosity",
  "type": "enum",
  "widget": "radio",
  "default": "",
  "choices": ["", "-v", "-vv", "-vvv"],
  "choice_labels": ["(none)", "Quiet", "Verbose", "Debug"]
}
```

Selecting `(none)` makes `{verbosity}` substitute as `""`, which
**drops the whole token** (or its enclosing token group). So the
template `["{verbosity}", "file.txt"]` produces:

| Selection | argv |
|---|---|
| `(none)` | `["tool", "file.txt"]` |
| `Quiet`  | `["tool", "-v", "file.txt"]` |
| `Debug`  | `["tool", "-vvv", "file.txt"]` |

This is the same drop-on-empty rule that applies to every other
substitution — no new mechanism. It just composes nicely with
radio buttons.

### `text` with masking

If the param's description or label matches (case-insensitive) any of
`password`, `secret`, `token`, `api key`, `apikey`, the widget uses
`QLineEdit.Password` echo mode. This is a heuristic — users can override
by editing the param manually.

### `number`

Integer spin box range: `[-2**31, 2**31 - 1]`.
Number (float) spin box range: `[-1e12, 1e12]` with 4 decimals.

These can be overridden per-param via optional `min` / `max` / `step`
fields (not yet exposed in the editor UI; only reachable by hand-edit).

## v0.5.0 — Canonical-name rename (schema_version 2 → 3)

Files written before v0.5.0 used a mix of Python-flavoured (`bool`,
`float`) and ScripTree-specific (`file_open`, `file_save`,
`enum_radio`) names. v0.5.0 swaps those for the JSON-Schema- and
HTML5-aligned names tabulated above. **This is a hard break** — v3
loaders refuse to open v2 files, pointing the user at the migrator.

### Rename map (run `scriptree migrate` to apply)

| Field    | v2 (old)      | v3 (new)     |
|----------|---------------|--------------|
| `type`   | `bool`        | `boolean`    |
| `type`   | `float`       | `number`     |
| `widget` | `file_open`   | `file`       |
| `widget` | `file_save`   | `save_file`  |
| `widget` | `enum_radio`  | `radio`      |

The migrator **also** folds in past LLM-noise aliases that the loader
used to tolerate (these were never canonical — they were workarounds
for upstream LLMs picking the wrong name):

| Field    | LLM noise        | Canonical    |
|----------|------------------|--------------|
| `type`   | `int`            | `integer`    |
| `type`   | `str`            | `string`     |
| `widget` | `spinbox`        | `number`     |
| `widget` | `radiobutton`    | `radio`      |
| `widget` | `select`         | `dropdown`   |

### Diagnostics

On a bad type or widget value, the loader now produces a diff-style
hint:

```
'int' is not a valid type for param 'iterations'.
Did you mean 'integer'?
Valid types: string, integer, number, boolean, path, enum, multiselect.
```

Run `python -m scriptree validate <path>` to check a file (or recurse
through a directory) before run time — it catches both the loader
errors and widget/type mismatches that the loader is too permissive to
flag on its own.
