# Parameter types and widgets

Reference matrix of legal type × widget combinations, default values,
and coercion rules.

## Types

| type          | Python type on read   | JSON form              |
|---------------|-----------------------|------------------------|
| `string`      | `str`                 | string                 |
| `integer`     | `int`                 | integer                |
| `float`       | `float`               | number                 |
| `bool`        | `bool`                | boolean                |
| `path`        | `str` (path string)   | string                 |
| `enum`        | `str`                 | string (one of choices) |
| `multiselect` | `list[str]`           | array of strings       |

## Widgets

| widget       | Qt class             | Used for              |
|--------------|----------------------|-----------------------|
| `text`       | `QLineEdit`          | short strings, ints, floats, masked input |
| `textarea`   | `QPlainTextEdit`     | long strings, regexes |
| `number`     | `QSpinBox` / `QDoubleSpinBox` | integer / float |
| `checkbox`   | `QCheckBox`          | bools                 |
| `dropdown`   | `QComboBox`          | enums, multiselects   |
| `enum_radio` | `QButtonGroup` of `QRadioButton` | enums (small sets) |
| `file_open`  | line edit + Browse (`QFileDialog.getOpenFileName`) | existing input files |
| `file_save`  | line edit + Browse (`QFileDialog.getSaveFileName`) | output files to write |
| `folder`     | line edit + Browse (`QFileDialog.getExistingDirectory`) | directories |

### Drag-and-drop (v0.1.11)

`text`, `textarea`, `file_open`, `file_save`, and `folder` widgets all
accept file/folder drops from Explorer. The implementation is two thin
Qt subclasses in `scriptree/ui/widgets/param_widgets.py`:

- `_DroppableLineEdit(QLineEdit)` — replaces the field's text with the
  first dropped local-file URL. Used by `text`, `file_open`,
  `file_save`, and `folder`.
- `_DroppablePlainTextEdit(QPlainTextEdit)` — inserts dropped paths at
  the cursor, one per line. Used by `textarea`.

Subclasses are required because Qt binds drag/drop slots on the C++
vtable at construction time — monkey-patching `dropEvent` on a stock
`QLineEdit` instance silently does nothing. Native text drops (e.g.
selecting text from another field) keep working via the parent
implementation's fallback.

## Legal combinations

| type          | legal widgets                           |
|---------------|-----------------------------------------|
| `string`      | `text`, `textarea`                      |
| `integer`     | `number`, `text`                        |
| `float`       | `number`, `text`                        |
| `bool`        | `checkbox`                              |
| `path`        | `file_open`, `file_save`, `folder`      |
| `enum`        | `dropdown`, `enum_radio`                |
| `multiselect` | `dropdown`                              |

Hand-edited files with illegal combinations load, but on first save the
editor snaps the widget to the first legal value.

## Default values per type

When a new param is added in the editor or when `default` is missing in
a hand-edited file:

| type          | default         |
|---------------|-----------------|
| `string`      | `""`            |
| `integer`     | `0`             |
| `float`       | `0.0`           |
| `bool`        | `false`         |
| `path`        | `""`            |
| `enum`        | first choice, or `""` if none |
| `multiselect` | `[]`            |

## Coercion on read

Values come out of form widgets typed, but sidecar JSON can hold
anything. `load_configs` coerces:

- `bool` — truthy Python object → `bool`.
- `integer` — `int(value)`, raises `ValueError` on non-numeric.
- `float` — `float(value)`, raises `ValueError` on non-numeric.
- `enum` — validated against `choices`; mismatch falls back to default.
- `multiselect` — wrapped in list if a single string was stored.
- `string` / `path` — `str(value)`.

Coercion failures produce a warning dialog but do not prevent the tool
from loading.

## Widget-specific fields

### `file_open`, `file_save`

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

#### `enum_radio` — radio buttons for mode switches

When the choice count is small (2–5) and the choice **gates which
other fields below it are relevant**, use `enum_radio`. Same
`choices` / `choice_labels` format as `dropdown`; only the rendering
differs.

##### When `enum_radio` beats `checkbox`

A checkbox conveys "optional flag, on or off." A radio conveys
"pick one of these mutually exclusive modes." When fields below the
control depend on the user's choice, the radio is the correct widget
because it cues the user that **the mode is the first thing to
decide**. Examples that should be `enum_radio`, not `checkbox`:

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
  "widget": "enum_radio",
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
Float spin box range: `[-1e12, 1e12]` with 4 decimals.

These can be overridden per-param via optional `min` / `max` / `step`
fields (not yet exposed in the editor UI; only reachable by hand-edit).
