"""
merged_tree.py — build a synthetic ``.scriptreetree`` that merges the
catalogs of every member of a master cell.

When the user double-left-clicks a master/ring cell, V3 spawns the V1
editor with a *merged* tree: each member cell's loaded catalog becomes
a top-level folder in the merged tree, named after the member's source
file (or its ``TreeDef.name`` field when the source is a
``.scriptreetree``).  Every leaf path is **resolved to an absolute
path** before serialisation so the merged file can live in ``%TEMP%``
without breaking V1's relative-path resolver (which would otherwise
look for leaves relative to the temp file's parent directory).

Public API
----------

    build_merged_tree(catalog_paths) -> Path
        Build a merged ``.scriptreetree`` from a list of source
        catalog paths (each a ``.scriptree`` or ``.scriptreetree``).
        Writes to ``<TEMP>/scriptreering_merged_<hash>.scriptreetree``
        and returns the absolute path.

    build_merged_tree_for_master(master) -> Path
        Convenience: extract ``catalog_path`` from each member of the
        master and call ``build_merged_tree``.  Skips members without
        a bound catalog.  Caches the result on the master via
        ``_merged_tree_cache_path`` so repeated double-clicks reuse
        the same temp file (which V1 keeps open) until the membership
        changes.

The temp file is intentionally **not** auto-deleted; V1 may keep it
open via ``QFileSystemWatcher`` for live-reload semantics.  ScripTree
cleans up its own ``%TEMP%\\scriptreering_merged_*.scriptreetree``
files at startup of either launcher; for now we rely on the OS to
sweep ``%TEMP%`` periodically.
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path
from typing import Iterable


def _log(msg: str) -> None:
    print(f"[merged_tree] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _resolve_relative_to(catalog_path: Path, leaf_path: str) -> str:
    """Resolve a leaf reference inside ``catalog_path`` to absolute.

    V1's tree loader treats leaf paths as relative to the directory
    containing the source ``.scriptreetree``.  When we lift those
    leaves into a merged tree at a different location, the relative
    paths break — so we fully resolve them to absolute strings here.
    """
    p = Path(leaf_path)
    if p.is_absolute():
        return str(p.resolve())
    return str((catalog_path.parent / p).resolve())


def _resolve_node_paths(
    node: "TreeNode",  # noqa: F821 — local import to avoid hard dep at module load
    catalog_path: Path,
):  # noqa: ANN201
    """Mutate ``node`` in place so every leaf path is absolute.

    Recurses into folder children.  Folder nodes are unchanged
    (they have no path).  Leaf nodes get their ``path`` rewritten.
    """
    if node.type == "leaf" and node.path is not None:
        node.path = _resolve_relative_to(catalog_path, node.path)
    elif node.type == "folder":
        for child in node.children:
            _resolve_node_paths(child, catalog_path)


# ---------------------------------------------------------------------------
# Synthetic tree builder
# ---------------------------------------------------------------------------

def build_merged_tree(catalog_paths: Iterable[str | Path]) -> Path:
    """Build a merged ``.scriptreetree`` from a list of source paths.

    Each source is loaded via V1's ``load_tree`` (for ``.scriptreetree``
    files) or wrapped as a single-leaf folder (for ``.scriptree``
    files).  Top-level folder name = the source file's ``TreeDef.name``
    (preferred) or its file stem.

    Returns the absolute ``Path`` of the temp file.
    """
    # Lazy imports — keep merged_tree importable in tests without the
    # full V1 core stack having to load.
    from scriptree.core.io import load_tree, load_tool, save_tree
    from scriptree.core.model import TreeDef, TreeNode

    sources: list[Path] = [Path(p).resolve() for p in catalog_paths]
    # De-dup while preserving order.
    seen: set[str] = set()
    sources = [p for p in sources if not (str(p) in seen or seen.add(str(p)))]

    merged_nodes: list = []
    member_names: list[str] = []

    for src in sources:
        if not src.is_file():
            _log(f"skipping missing source: {src}")
            continue
        ext = src.suffix.lower()
        if ext == ".scriptreetree":
            try:
                tree = load_tree(str(src))
            except Exception as exc:  # noqa: BLE001
                _log(f"load_tree({src}) failed: {exc!r}; skipping")
                continue
            top_name = tree.name or src.stem
            # Resolve every leaf inside this member's nodes to absolute.
            for child in tree.nodes:
                _resolve_node_paths(child, src)
            folder = TreeNode(
                type="folder",
                name=top_name,
                children=list(tree.nodes),
            )
            merged_nodes.append(folder)
            member_names.append(top_name)
        elif ext == ".scriptree":
            # Wrap a single-tool catalog as a one-leaf folder.
            try:
                tool = load_tool(str(src))
                top_name = tool.name or src.stem
            except Exception as exc:  # noqa: BLE001
                _log(f"load_tool({src}) failed: {exc!r}; using stem as name")
                top_name = src.stem
            leaf = TreeNode(
                type="leaf",
                name=top_name,
                path=str(src),  # absolute already
            )
            folder = TreeNode(
                type="folder",
                name=top_name,
                children=[leaf],
            )
            merged_nodes.append(folder)
            member_names.append(top_name)
        else:
            _log(f"unknown extension {ext!r} for {src}; skipping")

    if not merged_nodes:
        raise ValueError("build_merged_tree: no valid catalogs supplied")

    merged = TreeDef(
        name="Ring — " + " + ".join(member_names),
        nodes=merged_nodes,
    )

    # Stable, hash-based filename so repeated calls with the same set
    # of member catalogs produce the same temp file (V1 can re-read it
    # cleanly after edits).
    sig = hashlib.sha1(
        "\n".join(str(p) for p in sources).encode("utf-8")
    ).hexdigest()[:12]
    out = Path(tempfile.gettempdir()) / f"scriptreering_merged_{sig}.scriptreetree"
    save_tree(merged, str(out))
    _log(f"wrote {out}  ({len(merged_nodes)} members)")
    return out


# ---------------------------------------------------------------------------
# Convenience for masters
# ---------------------------------------------------------------------------

def build_merged_tree_for_master(master) -> Path:  # noqa: ANN001 — CellWindow
    """Pull catalog paths from each member of ``master`` and merge.

    ``master._members`` is a ``dict[member_id, QPoint]`` (id → home
    position), NOT a list of CellWindow instances.  We have to look
    up each id in the global ``CellRegistry`` to get the actual
    window and read its ``_catalog_path``.

    When NONE of the members have a catalog bound (e.g. fresh ring
    where no Load Catalog… has been clicked yet), we still produce a
    valid merged tree — one with a single placeholder folder so V1's
    editor opens with something visible.  This is the user-facing
    contract: "either way, scriptreering file or not, it needs to be
    able to open this way".
    """
    from scriptree.shell.cell_registry import CellRegistry
    from scriptree.core.io import save_tree
    from scriptree.core.model import TreeDef, TreeNode

    members_dict = getattr(master, "_members", None) or {}
    # Iterate keys (member ids) and look up each window in the registry.
    # When _members is unexpectedly a list/tuple, fall back to using
    # entries directly (keeps tests with synthetic _members happy).
    if isinstance(members_dict, dict):
        member_ids = list(members_dict.keys())
    else:
        member_ids = list(members_dict)

    registry = CellRegistry.instance()
    paths: list[str] = []
    unbound_count = 0
    for mid in member_ids:
        member = registry.get(mid) if isinstance(mid, str) else mid
        if member is None:
            continue
        cp = getattr(member, "_catalog_path", None)
        if cp:
            paths.append(str(cp))
        else:
            unbound_count += 1

    # Cache: if the membership signature is unchanged from a previous
    # call, return the cached path so V1 doesn't have to re-parse the
    # file (and so QFileSystemWatcher stays attached to a single inode).
    sig_key = "|".join(sorted(paths)) + f"|unbound={unbound_count}"
    cache_attr = "_merged_tree_cache"
    cache = getattr(master, cache_attr, None)
    if cache and cache[0] == sig_key and Path(cache[1]).is_file():
        return Path(cache[1])

    if paths:
        out = build_merged_tree(paths)
    else:
        # No member has a catalog yet — produce a placeholder tree so
        # the editor still has something to display, and so the
        # caller (e.g. show_composite_for) doesn't have to fall back
        # to launching a blank editor.
        placeholder = TreeDef(
            name="Ring (no member catalogs bound yet)",
            nodes=[
                TreeNode(
                    type="folder",
                    name="No catalogs bound",
                    children=[],
                    display_name=(
                        "Right-click each cell → Load Catalog… "
                        "to populate this ring."
                    ),
                ),
            ],
        )
        import tempfile, hashlib
        # ``_id`` may be missing on synthetic test objects — use the
        # object's repr as a fallback so the cache key still varies
        # per master instance.
        master_id = getattr(master, "_id", repr(master))
        sig = hashlib.sha1(
            f"empty:{master_id}".encode("utf-8")
        ).hexdigest()[:12]
        out = Path(tempfile.gettempdir()) / (
            f"scriptreering_merged_{sig}.scriptreetree"
        )
        save_tree(placeholder, str(out))
        _log(f"wrote placeholder merged tree at {out}")

    setattr(master, cache_attr, (sig_key, str(out)))
    return out
