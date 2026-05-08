"""
cell_metadata.py — read / write cell visual settings inside a
``.scriptree`` or ``.scriptreetree`` JSON file.

Per V3 v0.2.7 user direction (2026-05-07): "The icon settings should
be stored in the json of the scriptree, scriptreetree or scriptreering
file the cell/ring is associated with."

The fields live on ``ToolDef`` and ``TreeDef`` already (see
``scriptree.core.model``).  This module wraps the read/write boilerplate
so the cell-shell can:

  * pull the settings off a catalog file when binding to it
  * write changes back when the user adjusts them via the per-cell
    Settings dialog
  * embed an external icon as base64 in the JSON
  * unembed (extract) an embedded icon back out to a file

All paths are resolved RELATIVE to the catalog file by default — when
saving a setting that points to an external icon, we store the path
relative to the catalog's directory whenever the icon lives at or
under that directory.  Otherwise we fall back to an absolute path.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from scriptree.core.io import load_tool, load_tree, save_tool, save_tree
from scriptree.core.model import ToolDef, TreeDef


# ---------------------------------------------------------------------------
# Data carrier
# ---------------------------------------------------------------------------

@dataclass
class CellMetadata:
    """A snapshot of the cell-visual fields stored in a catalog file.

    All fields are optional; callers should ignore those that are
    empty / default.  ``icon_resolved_path`` is set by ``read_for``
    when the catalog has an external ``cell_icon`` path; it's the
    absolute, resolved path the cell can directly hand to QPixmap.
    """
    icon: str = ""              # raw value from JSON (relative or absolute)
    icon_data: str = ""         # base64-encoded image (when embedded)
    icon_format: str = ""       # "png" / "jpg" / "svg" / etc. (with icon_data)
    text_label: str = ""
    icon_scale: float = 1.0
    label_opacity: float = 1.0
    icon_resolved_path: str = ""  # absolute path (computed) or "" if embedded/none
    # Click-to-run fields (V3 v0.3.5+).  See ``ToolDef.cell_click_action``
    # / ``ToolDef.cell_click_run_mode`` for the contract.
    click_action: str = "menu"
    click_run_mode: str = "sequential"

    def has_icon(self) -> bool:
        return bool(self.icon_resolved_path) or bool(self.icon_data)

    def is_embedded(self) -> bool:
        return bool(self.icon_data) and bool(self.icon_format)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_for(catalog_path: str | Path) -> CellMetadata:
    """Read cell metadata from a ``.scriptree`` or ``.scriptreetree``.

    Returns an all-default ``CellMetadata`` if the file doesn't exist
    or doesn't carry any cell fields.  ``icon_resolved_path`` is
    populated when ``cell_icon`` is a non-empty path; the path is
    resolved against the catalog's directory.
    """
    p = Path(catalog_path)
    if not p.is_file():
        return CellMetadata()

    suffix = p.suffix.lower()
    try:
        if suffix == ".scriptree":
            obj = load_tool(str(p))
        elif suffix == ".scriptreetree":
            obj = load_tree(str(p))
        else:
            return CellMetadata()
    except Exception:  # noqa: BLE001
        return CellMetadata()

    md = CellMetadata(
        icon=getattr(obj, "cell_icon", "") or "",
        icon_data=getattr(obj, "cell_icon_data", "") or "",
        icon_format=getattr(obj, "cell_icon_format", "") or "",
        text_label=getattr(obj, "cell_text_label", "") or "",
        icon_scale=float(getattr(obj, "cell_icon_scale", 1.0) or 1.0),
        label_opacity=float(getattr(obj, "cell_label_opacity", 1.0) or 1.0),
        click_action=str(getattr(obj, "cell_click_action", "menu") or "menu"),
        click_run_mode=str(
            getattr(obj, "cell_click_run_mode", "sequential")
            or "sequential"
        ),
    )

    if md.icon and not md.icon_data:
        # Resolve relative to the catalog's directory.
        ip = Path(md.icon)
        if not ip.is_absolute():
            ip = (p.parent / ip).resolve()
        md.icon_resolved_path = str(ip)

    return md


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def _to_relative_if_possible(catalog_path: Path, icon_path: Path) -> str:
    """Return the icon path relative to the catalog dir when it lives
    under that dir tree; otherwise the absolute path.  Per user
    direction: 'paths should default to relative.'
    """
    icon_abs = icon_path.resolve()
    catalog_dir = catalog_path.resolve().parent
    try:
        rel = icon_abs.relative_to(catalog_dir)
        # Use forward slashes so cross-platform diffs stay clean.
        return str(rel).replace("\\", "/")
    except ValueError:
        # icon_abs not a subpath of catalog_dir — keep absolute.
        return str(icon_abs)


def write_for(
    catalog_path: str | Path,
    *,
    icon: str | None = None,
    icon_data: str | None = None,
    icon_format: str | None = None,
    text_label: str | None = None,
    icon_scale: float | None = None,
    label_opacity: float | None = None,
    click_action: str | None = None,
    click_run_mode: str | None = None,
) -> CellMetadata:
    """Mutate the catalog file's cell-visual fields and persist.

    Pass ``None`` for any field to LEAVE IT UNCHANGED.  Pass empty
    string / 1.0 to clear / reset to default.

    ``click_action`` / ``click_run_mode`` (V3 v0.3.5+) — gate the
    cell's single-click behaviour.  Valid ``click_action`` values
    are ``"menu"`` and ``"run"``; valid ``click_run_mode`` values
    are ``"sequential"`` and ``"parallel"``.  Unknown values are
    coerced to defaults at load time.

    Path normalisation: when ``icon`` is a non-empty absolute path,
    we rewrite it relative to the catalog directory whenever the
    icon lives under that directory.

    Returns the post-save ``CellMetadata`` so callers can sync their
    in-memory state.  Raises ``FileNotFoundError`` if the catalog
    doesn't exist.
    """
    p = Path(catalog_path)
    if not p.is_file():
        raise FileNotFoundError(catalog_path)

    suffix = p.suffix.lower()
    if suffix == ".scriptree":
        obj = load_tool(str(p))
    elif suffix == ".scriptreetree":
        obj = load_tree(str(p))
    else:
        raise ValueError(
            f"Unsupported catalog extension {suffix!r} for cell metadata."
        )

    if icon is not None:
        if icon:
            icon_p = Path(icon)
            if icon_p.is_absolute():
                icon = _to_relative_if_possible(p, icon_p)
        obj.cell_icon = icon
    if icon_data is not None:
        obj.cell_icon_data = icon_data
    if icon_format is not None:
        obj.cell_icon_format = icon_format
    if text_label is not None:
        obj.cell_text_label = text_label
    if icon_scale is not None:
        obj.cell_icon_scale = float(icon_scale)
    if label_opacity is not None:
        obj.cell_label_opacity = float(label_opacity)
    if click_action is not None:
        # Coerce to a known value.  Unknown values fall back to
        # the safe default ("menu") so mistyped JSON can't unlock
        # auto-run.
        obj.cell_click_action = (
            "run" if str(click_action) == "run" else "menu"
        )
    if click_run_mode is not None:
        obj.cell_click_run_mode = (
            "parallel" if str(click_run_mode) == "parallel" else "sequential"
        )

    if isinstance(obj, ToolDef):
        save_tool(obj, p)
    else:
        save_tree(obj, p)

    return read_for(p)


# ---------------------------------------------------------------------------
# Embed / unembed
# ---------------------------------------------------------------------------

# File extensions we recognise as embeddable image formats.  Anything
# else ("ico", "tif") still works — we just record the suffix as-is in
# ``icon_format`` and trust the consumer (QPixmap.loadFromData does
# format auto-detection on most common formats).
_KNOWN_FORMATS = {"png", "jpg", "jpeg", "gif", "bmp", "svg", "webp", "ico"}


def embed_icon(catalog_path: str | Path, icon_path: str | Path) -> CellMetadata:
    """Read ``icon_path`` from disk, base64-encode it, and write the
    bytes into the catalog's ``cell_icon_data`` field.  Clears the
    external ``cell_icon`` path on success.

    Returns the resulting ``CellMetadata``.  Raises if either file is
    missing / unreadable.
    """
    catalog_p = Path(catalog_path)
    icon_p = Path(icon_path)
    if not icon_p.is_file():
        raise FileNotFoundError(f"Icon not found: {icon_path}")

    raw = icon_p.read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")

    fmt = icon_p.suffix.lower().lstrip(".")
    if fmt not in _KNOWN_FORMATS and fmt:
        # Unrecognised but non-empty → keep as-is; QPixmap may still
        # be able to detect.  Empty → "bin" placeholder so future
        # readers know it's not a pre-determined format.
        pass
    if not fmt:
        fmt = "bin"

    return write_for(
        catalog_p,
        icon="",                # clear the external path
        icon_data=encoded,
        icon_format=fmt,
    )


def unembed_icon_to_file(
    catalog_path: str | Path,
    out_path: str | Path,
) -> CellMetadata:
    """Decode the catalog's embedded ``cell_icon_data``, write the
    bytes to ``out_path``, then rewrite the catalog so ``cell_icon``
    points at the new file (relative to the catalog when possible).

    Raises ``ValueError`` if the catalog has no embedded data.
    """
    catalog_p = Path(catalog_path)
    out_p = Path(out_path)
    md = read_for(catalog_p)
    if not md.icon_data:
        raise ValueError(
            "No embedded icon to unembed in this catalog."
        )

    raw = base64.b64decode(md.icon_data.encode("ascii"))
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_bytes(raw)

    return write_for(
        catalog_p,
        icon=str(out_p.resolve()),  # write_for will relativise if possible
        icon_data="",
        icon_format="",
    )


# ---------------------------------------------------------------------------
# QPixmap helper
# ---------------------------------------------------------------------------

def make_pixmap_from_metadata(md: CellMetadata):  # noqa: ANN201
    """Return a ``QPixmap`` for the icon described by ``md``.

    Tries embedded data first, then the resolved external path.
    Returns ``None`` if neither is available or the data fails to
    decode.
    """
    from PySide6.QtGui import QPixmap

    if md.icon_data:
        try:
            raw = base64.b64decode(md.icon_data.encode("ascii"))
            pix = QPixmap()
            if pix.loadFromData(raw, md.icon_format.upper() or None):
                return pix
        except Exception:  # noqa: BLE001
            return None

    if md.icon_resolved_path:
        pix = QPixmap(md.icon_resolved_path)
        if not pix.isNull():
            return pix

    return None
