---
topic: v3-architecture
date: 2026-05-07
status: recipe
related: [icon_path_relative_normalization, embed_unembed_icon_roundtrip]
---
# Cell visual metadata lives in the catalog JSON

## What happened / design choice

Pre-v0.2.7, cell visuals (icon path, label text, scale,
opacity) were saved in QSettings, keyed by catalog path.
Moving the catalog to a new machine lost the visuals.
v0.2.7 promoted these fields into the catalog JSON itself.

## Root cause / design

`ToolDef` and `TreeDef` now carry an optional `cell`
sub-object:

```json
{
  "name": "...",
  "exe": "...",
  "cell": {
    "icon": "icons/foo.png",
    "icon_data": "<base64>",
    "icon_format": "png",
    "text_label": "Foo",
    "icon_scale": 0.85,
    "label_opacity": 0.7
  }
}
```

When a cell is bound to a catalog, settings come from the
catalog's `cell` sub-object.  When unbound (or the field is
missing), QSettings is the fallback (back-compat).  Default
values are OMITTED from the JSON to keep legacy files
byte-identical when nothing has changed.

## Fix / recipe

Read/write helpers live in `scriptree/core/cell_metadata.py`:

- `read_cell_metadata(catalog) -> CellMetadata`
- `write_cell_metadata(catalog, meta)` — only writes
  non-default keys
- `embed_icon(catalog, icon_path)` — see
  embed_unembed_icon_roundtrip lesson
- `_to_relative_if_possible(catalog, icon_path)` — see
  icon_path_relative_normalization lesson

When loading a `CellWindow`, prefer catalog metadata; fall
back to QSettings:

```python
meta = read_cell_metadata(catalog) if catalog else None
icon = (meta and meta.icon) or _qsettings_icon_for(cell_id)
```

## How future-me detects it

A cell's visuals look different after a clean install or a
catalog moved between machines, but the catalog JSON looks
unchanged.  Check whether the metadata is in the catalog (it
should be) or only in QSettings (legacy path that won't
travel).
