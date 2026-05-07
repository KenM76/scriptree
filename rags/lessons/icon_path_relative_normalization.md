---
topic: v3-architecture
date: 2026-05-07
status: recipe
related: [cell_metadata_in_catalog_json, embed_unembed_icon_roundtrip]
---
# Icon path normalization: relative if under catalog dir, absolute otherwise

## What happened / design choice

When writing an icon path into the catalog JSON, blindly
storing the absolute path makes the catalog non-portable.
Blindly storing the basename loses the location for icons
outside the catalog dir.  Per the user's standing rule
("paths should default to relative"), the rule is: prefer
relative when possible, absolute as fallback.

## Root cause / design

The icon may live anywhere on disk.  Only icons that share
or are under the catalog's parent directory can be expressed
as a relative path.  Anything else stays absolute.

## Fix / recipe

`scriptree/core/cell_metadata.py:_to_relative_if_possible`:

```python
def _to_relative_if_possible(catalog_path: Path, icon_path: Path) -> str:
    """Return forward-slash relative path if icon is under catalog dir,
    otherwise the absolute path as-is."""
    try:
        rel = icon_path.resolve().relative_to(catalog_path.parent.resolve())
        return rel.as_posix()  # forward slashes for cross-platform
    except ValueError:
        # icon is not under catalog dir
        return str(icon_path.resolve())
```

Forward slashes (`as_posix`) are deliberate — they read
identically on Windows and POSIX, and Python's `Path` opens
them on either OS.

When loading: resolve a relative path against
`catalog_path.parent`; absolute paths pass through unchanged.

## How future-me detects it

A catalog opened on a different machine fails to find its
icon — the path stored is absolute when it should have been
relative.  Or: a relative icon path resolves to the wrong
file because the resolution base wasn't the catalog dir.
