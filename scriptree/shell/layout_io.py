"""
layout_io.py — read / write ``.scriptreelayout`` files (v0.8.0a83).

## For humans

A **cell layout** is a named, reusable *arrangement* of the forest hub's
cells.  It is purely POSITIONAL: an ordered list of ``(catalog/tree path,
offset-from-the-forest-hub)`` entries.  It deliberately does NOT record
membership — applying a layout repositions the forest cells whose tool/tree
path matches an entry and leaves everything else untouched (see
``ForestController._apply_layout``).  This is the file behind the forest
hub right-click menu's **File ▸ Save layout / Save layout as… / Open
layout…** entries and the top-level **Recent layouts** submenu (the
pre-a119 "Cell layout ▸" submenu was dissolved into those).

Why store the OFFSET from the hub (not an absolute position)?  So a layout can
be applied no matter where the forest itself currently sits — the cells land in
the same arrangement *relative to the hub*.  This is the same convention as
``ForestItem.rel_offset`` (the per-session auto-remembered layout that lives in
the ``.scriptreeforest``); a ``.scriptreelayout`` is the user's explicitly
*named* snapshot of that same idea.

## File format

JSON::

    {
      "format": "scriptreelayout",
      "version": 1,
      "name": "My layout",
      "saved_at": "2026-06-23T12:34:56+00:00",
      "entries": [
        {"catalog_path": "ScripTreeApps/SolidWorks/sw.scriptreetree",
         "kind": "tree",
         "rel_offset": [120, -40]}
      ]
    }

* ``rel_offset`` is ``(member_top_left − hub_top_left)`` in logical pixels.
* ``catalog_path`` is stored relative to the project root when possible
  (portable), absolute otherwise — resolved on load via
  ``forest_io._resolve_for_load`` (the same helper the forest loader uses).
* ``kind`` is a hint (``"ring" | "tree" | "tool"``); derived from the suffix
  when absent.

The reader is defensive: a malformed entry (missing path, non-2-int offset) is
skipped rather than poisoning the whole load, mirroring ``forest_io``.

## Reconstruction contract

To recreate this module from these docs: it is a thin JSON (de)serialiser for a
``LayoutDef`` (``name`` + ``list[LayoutEntry]``).  ``save_layout`` writes the
blob above (paths relativised, offsets coerced to ``int``); ``load_layout``
parses it, rejecting a wrong ``format`` with ``ValueError`` and tolerating a
mismatched ``version`` with a log line.  No on-screen / Qt state is touched
here — placement is the controller's job.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from scriptree.shell.forest_io import (
    ItemKind,
    _project_root,
    _resolve_for_load,
    _to_relative_if_possible,
    kind_for_suffix,
)

_FORMAT = "scriptreelayout"
_VERSION = 1


def _log(msg: str) -> None:
    print(f"[layout_io] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LayoutEntry:
    """One cell's place in a saved layout: which tool/tree, and its offset
    from the forest hub's top-left."""

    catalog_path: str
    rel_offset: tuple[int, int]
    kind: ItemKind = "tree"


@dataclass
class LayoutDef:
    """A named cell arrangement (positions only — never membership)."""

    name: str = "Layout"
    entries: list[LayoutEntry] = field(default_factory=list)
    saved_at: str | None = None
    loaded_from: str | None = None


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------

def save_layout(layout: LayoutDef, path: str | Path) -> None:
    """Serialise ``layout`` to a ``.scriptreelayout`` JSON file."""
    path = Path(path)
    root = _project_root()

    entries_d: list[dict] = []
    for e in layout.entries:
        entries_d.append({
            "catalog_path": _to_relative_if_possible(Path(e.catalog_path), root),
            "kind": e.kind,
            "rel_offset": [int(e.rel_offset[0]), int(e.rel_offset[1])],
        })

    blob = {
        "format": _FORMAT,
        "version": _VERSION,
        "name": layout.name,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entries": entries_d,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    layout.loaded_from = str(path.resolve())
    _log(f"save_layout: wrote {path} ({len(entries_d)} entries)")


def load_layout(path: str | Path) -> LayoutDef:
    """Parse a ``.scriptreelayout`` file into a ``LayoutDef``.

    Raises ``ValueError`` on a wrong ``format``; tolerates a mismatched
    ``version`` (logs and proceeds).  Malformed entries are skipped.
    """
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    fmt = raw.get("format")
    if fmt != _FORMAT:
        raise ValueError(
            f"load_layout: unexpected format {fmt!r} (expected {_FORMAT!r})"
        )
    ver = raw.get("version", 1)
    if ver != _VERSION:
        _log(f"load_layout: version {ver} (expected {_VERSION}); proceeding")

    entries: list[LayoutEntry] = []
    for d in raw.get("entries", []):
        if not isinstance(d, dict):
            continue
        cp = str(d.get("catalog_path", "")).strip()
        if not cp:
            continue
        resolved = str(_resolve_for_load(cp, path))
        ro = d.get("rel_offset")
        if not (isinstance(ro, (list, tuple)) and len(ro) == 2):
            continue
        try:
            rel = (int(ro[0]), int(ro[1]))
        except (TypeError, ValueError):
            continue
        kind = d.get("kind") or kind_for_suffix(resolved) or "tree"
        entries.append(LayoutEntry(
            catalog_path=resolved,
            rel_offset=rel,
            kind=kind,  # type: ignore[arg-type]
        ))

    layout = LayoutDef(
        name=str(raw.get("name") or path.stem),
        entries=entries,
        saved_at=raw.get("saved_at"),
        loaded_from=str(path.resolve()),
    )
    _log(f"load_layout: read {path} ({len(entries)} entries)")
    return layout
