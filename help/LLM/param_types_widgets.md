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
