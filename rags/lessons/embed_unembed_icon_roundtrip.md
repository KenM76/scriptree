---
topic: v3-architecture
date: 2026-05-07
status: recipe
related: [cell_metadata_in_catalog_json, icon_path_relative_normalization]
---
# Embed / unembed icon round-trip

## What happened / design choice

Two competing needs for icons in a catalog:

- **Portability**: a catalog that survives source-file moves
  and zip archiving should carry its icons inline.
- **Human readability / editability**: a designer wants to
  swap the icon by editing a file on disk, not by surgery on
  base64 inside a JSON.

v0.2.7 supports both via `embed_icon` / `unembed_icon_to_file`
helpers — the catalog can be flipped between the two
representations on demand.

## Root cause / design

Embedded form: `cell_icon_data` (base64 bytes) +
`cell_icon_format` (e.g. `"png"`) populated; `cell_icon`
(path) empty.

External form: `cell_icon` populated (relative or absolute);
`cell_icon_data` / `cell_icon_format` absent.

Loaders must accept either form and prefer embedded data
when both are present.

## Fix / recipe

```python
# scriptree/core/cell_metadata.py

def embed_icon(catalog: Path, icon_path: Path) -> None:
    """Read icon bytes, base64-encode, write into catalog;
    clear the path field."""
    data = icon_path.read_bytes()
    fmt = icon_path.suffix.lstrip(".").lower()
    obj = read_catalog(catalog)
    obj.setdefault("cell", {})
    obj["cell"]["icon_data"] = base64.b64encode(data).decode()
    obj["cell"]["icon_format"] = fmt
    obj["cell"].pop("icon", None)
    write_catalog(catalog, obj)

def unembed_icon_to_file(catalog: Path, out: Path) -> None:
    """Decode the base64 bytes back to disk; rewrite the
    catalog with a relative path (if possible) and clear
    the embedded fields."""
    obj = read_catalog(catalog)
    cell = obj.get("cell", {})
    fmt = cell.get("icon_format", "png")
    data = base64.b64decode(cell["icon_data"])
    out.write_bytes(data)
    cell["icon"] = _to_relative_if_possible(catalog, out)
    cell.pop("icon_data", None)
    cell.pop("icon_format", None)
    write_catalog(catalog, obj)
```

## How future-me detects it

A user moves a catalog to a new machine and the icon is
missing → it was external (path) instead of embedded (data).
Or: a catalog that should be human-editable contains a
mile-long base64 blob → the user wants it unembedded.  The
fix in either direction is one helper call.
