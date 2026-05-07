"""
explode_tree.py — turn a single ``.scriptreetree`` into a multi-cell ring.

The "Open in ring" action in the V1 editor takes the loaded
``.scriptreetree`` and spawns one cell per *top-level* node, all docked
together as a master/ring.  This module produces the artifact that
makes that work: a synthetic ``.scriptreering`` file the cell shell
can consume via its existing ``load_ring`` path.

Strategy
--------

1. Walk the source ``TreeDef.nodes``.
2. For each top-level node, materialise a "member catalog path":

   * Top-level **leaf** ``.scriptree`` — use the leaf's path directly
     (resolved to absolute against the source tree's directory).
   * Top-level **leaf** ``.scriptreetree`` — same: use the leaf path
     directly.
   * Top-level **folder** — write a temp ``.scriptreetree`` containing
     just that folder's children, with every leaf path resolved to
     absolute (since the temp file lives in ``%TEMP%`` and won't be
     able to find relative paths from the source tree).

3. Build a ``.scriptreering`` JSON document that has:

   * A ``master`` cell with ``role: "master"`` and no catalog (the
     master is materialised on demand by the cell shell — see
     ``MasterHexagonWindow`` notes in cell_window.py).
   * One ``member`` per materialised catalog path, positioned at a
     honeycomb-neighbour offset around the master.

4. Write the document to ``<TEMP>/scriptreering_explode_<hash>.scriptreering``
   and return its path.  The cell shell can then ``load_ring`` it
   exactly like any other ring file.

The hash is derived from the source tree path + its top-level structure
so re-exploding the same tree produces the same temp ring path, which
keeps any QFileSystemWatcher attached on the cell-shell side.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _log(msg: str) -> None:
    print(f"[explode_tree] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Honeycomb member positions
# ---------------------------------------------------------------------------

# Match the offsets in snap_engine._FLAT_TOP_OFFSETS — duplicated here so
# this module can be used outside a Qt context (e.g. from a CLI).
_SQRT3_HALF = math.sqrt(3) / 2
_SQRT3_QRTR = math.sqrt(3) / 4

_FLAT_TOP_RING_OFFSETS: list[tuple[float, float]] = [
    (+0.75, -_SQRT3_QRTR),   # NE
    (+0.75, +_SQRT3_QRTR),   # SE
    (0.0,   +_SQRT3_HALF),   # S
    (-0.75, +_SQRT3_QRTR),   # SW
    (-0.75, -_SQRT3_QRTR),   # NW
    (0.0,   -_SQRT3_HALF),   # N
]


def _ring_positions(
    n: int, master_cx: float, master_cy: float, size_px: int
) -> list[tuple[int, int]]:
    """Return ``n`` (top-left x, y) member positions arranged in a
    honeycomb ring around ``(master_cx, master_cy)``.

    For more than 6 members we fall through to a second concentric ring
    (rough placement — the SnapEngine will compress them when the user
    interacts with the ring later).
    """
    out: list[tuple[int, int]] = []
    for i in range(n):
        if i < len(_FLAT_TOP_RING_OFFSETS):
            ox, oy = _FLAT_TOP_RING_OFFSETS[i]
            radius = 1.0
        else:
            # Outer ring at 2× radius, evenly spaced.
            outer_idx = i - len(_FLAT_TOP_RING_OFFSETS)
            outer_count = max(n - len(_FLAT_TOP_RING_OFFSETS), 6)
            theta = 2 * math.pi * outer_idx / outer_count
            ox = math.cos(theta) * 0.75
            oy = math.sin(theta) * _SQRT3_HALF
            radius = 2.0
        cx = master_cx + ox * size_px * radius
        cy = master_cy + oy * size_px * radius
        out.append((round(cx - size_px / 2), round(cy - size_px / 2)))
    return out


# ---------------------------------------------------------------------------
# Top-level materialisation
# ---------------------------------------------------------------------------

def _materialise_top_level(
    tree_path: Path,
) -> list[tuple[str, str]]:
    """Return ``(label, catalog_path)`` for every top-level item of
    ``tree_path``.

    * Folders are written out as their own ``.scriptreetree`` files in
      ``%TEMP%`` (paths inside resolved to absolute).
    * Leaves are returned with their absolute paths (no temp file
      written — leaves already point at concrete catalog files).
    """
    from scriptree.core.io import load_tree, save_tree
    from scriptree.core.model import TreeDef, TreeNode

    tree = load_tree(str(tree_path))
    base = tree_path.parent.resolve()

    items: list[tuple[str, str]] = []

    def _resolve(p: str) -> str:
        pp = Path(p)
        if pp.is_absolute():
            return str(pp.resolve())
        return str((base / pp).resolve())

    def _resolve_node(node: TreeNode) -> TreeNode:
        if node.type == "leaf" and node.path is not None:
            return TreeNode(
                type="leaf",
                name=node.name,
                path=_resolve(node.path),
                configuration=node.configuration,
                display_name=node.display_name,
            )
        if node.type == "folder":
            return TreeNode(
                type="folder",
                name=node.name,
                children=[_resolve_node(c) for c in node.children],
                display_name=node.display_name,
            )
        return node

    sig_seed = f"{tree_path.resolve()}|{tree.name}|{len(tree.nodes)}"

    for idx, node in enumerate(tree.nodes):
        label = node.display_name or node.name or f"item_{idx}"
        if node.type == "leaf" and node.path is not None:
            items.append((label, _resolve(node.path)))
        elif node.type == "folder":
            # Materialise this folder as its own .scriptreetree.
            sub = TreeDef(
                name=node.display_name or node.name or f"folder_{idx}",
                nodes=[_resolve_node(c) for c in node.children],
            )
            sig = hashlib.sha1(
                f"{sig_seed}|folder|{idx}|{sub.name}".encode("utf-8")
            ).hexdigest()[:12]
            sub_path = (
                Path(tempfile.gettempdir())
                / f"scriptreering_explode_part_{sig}.scriptreetree"
            )
            save_tree(sub, str(sub_path))
            items.append((label, str(sub_path)))
        # Skip nodes with no usable content silently.

    return items


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def explode_tree_to_ring(
    tree_path: str | Path,
    size_px: int = 56,
    master_position: tuple[int, int] | None = None,
) -> Path:
    """Build a ``.scriptreering`` whose members are the top-level items
    of ``tree_path``.

    Parameters
    ----------
    tree_path
        Source ``.scriptreetree``.
    size_px
        Cell size in pixels for both master and members.
    master_position
        Top-left ``(x, y)`` of the master cell, in screen coords.  When
        omitted, the master lands roughly centred on the primary
        screen at ``(400, 300)``.

    Returns
    -------
    Path
        Absolute path to the temp ``.scriptreering`` file.

    Raises
    ------
    ValueError
        If the source tree has no top-level items.
    """
    src = Path(tree_path).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"explode_tree_to_ring: {src} not found")

    items = _materialise_top_level(src)
    if not items:
        raise ValueError(
            f"explode_tree_to_ring: tree {src.name} has no top-level items"
        )

    mx, my = master_position if master_position is not None else (400, 300)
    master_cx = mx + size_px / 2
    master_cy = my + size_px / 2
    member_topleft = _ring_positions(len(items), master_cx, master_cy, size_px)

    members: list[dict] = []
    for (label, catalog_path), (px, py) in zip(items, member_topleft):
        members.append({
            "shape": "hexagon",
            "orientation": "flat-top",
            "size_px": size_px,
            "transparency": 0.85,
            "always_on_top": True,
            "position": {"x": int(px), "y": int(py)},
            "preferred_position": {"x": int(px), "y": int(py)},
            "catalog_path": catalog_path,
            "is_positioned": True,
        })

    doc = {
        "format": "scriptreering",
        "version": 1,
        "saved_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "saved_by_brand": "ScripTree (editor explode)",
        "master": {
            "role": "master",
            "shape": "hexagon",
            "orientation": "flat-top",
            "size_px": size_px,
            "transparency": 0.85,
            "always_on_top": True,
            "position": {"x": int(mx), "y": int(my)},
            "catalog_path": None,
        },
        "members": members,
    }

    sig = hashlib.sha1(
        f"{src}|{len(items)}|{[c for _, c in items]}".encode("utf-8")
    ).hexdigest()[:12]
    out = (
        Path(tempfile.gettempdir())
        / f"scriptreering_explode_{sig}.scriptreering"
    )
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    _log(f"wrote {out}  ({len(items)} top-level item(s))")
    return out
