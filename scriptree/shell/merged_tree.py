"""
merged_tree.py — build a synthetic ``.scriptreetree`` that merges the
catalogs of every member of a master cell.

## For humans

When the user double-left-clicks a master/ring cell, V3 spawns the V1
editor with a *merged* tree: each member cell's loaded catalog becomes
a top-level folder in the merged tree, named after the member's source
file (or its ``TreeDef.name`` field when the source is a
``.scriptreetree``).  Every leaf path is **resolved to an absolute
path** before serialisation so the merged file can live in ``%TEMP%``
without breaking V1's relative-path resolver (which would otherwise
look for leaves relative to the temp file's parent directory).

## Back-propagation (v0.8.0a31+)

The merged tree is **editable**.  When the user saves it in V1, the
editor's save path detects the merged-tree filename pattern and calls
``push_back_to_origins(merged_path)``, which:

  1. Reads the sidecar JSON written alongside the merged tree (see
     ``_origins_sidecar_path``) — this lists ``folder_name ->
     source_path`` per top-level folder.
  2. Walks the just-saved merged tree.
  3. For each top-level folder, writes its ``children`` back to the
     matching source ``.scriptreetree`` file -- or, for single-tool
     sources that came from a ``.scriptree``, writes the leaf's
     resolved tool definition back.
  4. Converts absolute leaf paths back to paths relative-to-origin
     before saving (canonical .scriptreetree convention).

This is what makes "edit the forest in the editor" actually save
changes back to the per-member files the forest reads from.

Public API
----------

    build_merged_tree(catalog_paths) -> Path
        Build a merged ``.scriptreetree`` from a list of source
        catalog paths (each a ``.scriptree`` or ``.scriptreetree``).
        Writes to ``<TEMP>/scriptreering_merged_<hash>.scriptreetree``
        AND a sidecar ``...origins.json`` next to it.  Returns the
        absolute path of the .scriptreetree.

    build_merged_tree_for_master(master) -> Path
        Convenience: extract ``catalog_path`` from each member of the
        master and call ``build_merged_tree``.  Skips members without
        a bound catalog.  Caches the result on the master via
        ``_merged_tree_cache_path`` so repeated double-clicks reuse
        the same temp file (which V1 keeps open) until the membership
        changes.

    is_merged_tree(path) -> bool
        Heuristic check: does ``path`` look like a merged-tree temp
        file? Used by V1's save path to decide whether to invoke
        ``push_back_to_origins``.

    push_back_to_origins(merged_path) -> PushBackResult
        Walk a freshly-saved merged tree + its origins sidecar, and
        write each top-level folder's contents back to the file the
        folder originated from.  Returns a structured result so the
        caller can show the user a "wrote N source files" toast.

The temp file is intentionally **not** auto-deleted; V1 may keep it
open via ``QFileSystemWatcher`` for live-reload semantics.  ScripTree
cleans up its own ``%TEMP%\\scriptreering_merged_*.scriptreetree``
files at startup of either launcher; for now we rely on the OS to
sweep ``%TEMP%`` periodically.

## For maintainers / LLMs

* The temp file is deliberately NEVER deleted by this module — V1 may
  hold it open via ``QFileSystemWatcher`` for live-reload.  Do not add
  a finally-block unlink here; cleanup is the launcher's job at
  startup.  The hash-stable filename is the only thing keeping
  ``%TEMP%`` from growing per double-click.
* ``_resolve_node_paths`` MUTATES the loaded ``TreeNode`` tree in
  place.  ``load_tree`` returns fresh objects per call so this is
  currently safe, but never pass a cached/shared tree through it or
  you will rewrite leaf paths on the original.
* Filename signature is ``sha1(<newline-joined resolved source
  paths>)[:12]`` — order-sensitive *after* the de-dup that preserves
  first-seen order.  Same member set in a different order → different
  temp file.  Keep the de-dup and the signing input consistent.
* ``build_merged_tree`` raises ``ValueError`` when no source resolves
  to a valid catalog; ``build_merged_tree_for_master`` never does — it
  falls back to a placeholder tree (user contract: "either way it must
  open").  Callers of the master variant should not expect the
  ValueError path.
* ``master._members`` is ``dict[member_id, QPoint]`` (id → home pos),
  NOT a list of windows — ids are looked up in ``CellRegistry``.  The
  ``isinstance(dict)`` fallback to a list/tuple exists only for
  synthetic test masters; production always hits the dict path.
* Cache key is ``"|".join(sorted(paths)) + f"|unbound={n}"`` stored on
  ``master._merged_tree_cache`` as ``(sig_key, path_str)``; it is
  re-validated with ``Path(...).is_file()`` so a swept temp dir
  forces a rebuild.  The placeholder branch keys on ``master._id``
  (repr fallback for test objects) so each master gets a distinct
  empty file.
* Lazy imports of ``scriptree.core.io`` / ``.model`` are intentional —
  keep ``merged_tree`` importable in tests without the V1 core stack.
  Do not hoist them to module scope.
* ``_log`` writes to stderr only; load failures of individual sources
  are logged and skipped, not raised — a partially-broken member set
  still yields a usable merged tree.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# L14 fix: merged temp files were never reclaimed by this module —
# %TEMP% growth depended entirely on the launcher's startup sweep.
# Best-effort sweep stale merged files (older than this many
# seconds) on every build so the directory self-bounds even if the
# launcher sweep never runs.
_MERGED_STALE_SECONDS = 24 * 3600
_MERGED_GLOB = "scriptreering_merged_*.scriptreetree"


def _sweep_stale_merged_files() -> None:
    """Delete merged temp files older than ``_MERGED_STALE_SECONDS``.

    Self-contained, exception-safe: a locked/in-use file (another
    live master still reading it) just gets skipped — it's younger
    than the threshold anyway in the normal case, and even a
    spurious skip only defers cleanup to the next build."""
    try:
        tmp = Path(tempfile.gettempdir())
        cutoff = time.time() - _MERGED_STALE_SECONDS
        for f in tmp.glob(_MERGED_GLOB):
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                continue  # in use / permission — leave it
    except OSError:
        pass  # %TEMP% itself unreadable — nothing we can do


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
    # L14 fix: reclaim old merged temp files before writing a new
    # one so %TEMP% self-bounds regardless of the launcher sweep.
    _sweep_stale_merged_files()
    save_tree(merged, str(out))
    _log(f"wrote {out}  ({len(merged_nodes)} members)")

    # v0.8.0a31+ -- write the origins sidecar alongside the merged
    # tree so V1's save path can find it and push back-edits.  See
    # ``_origins_sidecar_path`` and ``push_back_to_origins``.
    _write_origins_sidecar(out, list(zip(member_names, sources)))

    return out


# ---------------------------------------------------------------------------
# Origins sidecar + back-propagation (v0.8.0a31+)
# ---------------------------------------------------------------------------

# Filename suffix appended to the merged tree's path to locate the
# sidecar JSON that maps top-level folder names to their source
# files.  Co-located so a moved or copied merged tree carries its
# origin map along.
_ORIGINS_SUFFIX = ".origins.json"

# Filename heuristic: a merged tree's stem starts with this prefix.
# Used by ``is_merged_tree`` so the V1 save path can decide whether
# to invoke back-propagation.
_MERGED_PREFIX = "scriptreering_merged_"


@dataclass
class PushBackResult:
    """Outcome of pushing merged-tree edits back to their source
    catalog files.

    Returned by :func:`push_back_to_origins` so the caller (V1's
    save handler) can show the user a precise summary: "wrote 3
    source files, skipped 1, errors on 0."
    """
    written: list[str] = field(default_factory=list)
    """Absolute paths of source files that were successfully written."""

    skipped: list[tuple[str, str]] = field(default_factory=list)
    """Tuples of (source_path, reason) for files we couldn't or
    wouldn't write -- e.g. a top-level folder in the merged tree
    no longer matches any sidecar entry."""

    errors: list[tuple[str, str]] = field(default_factory=list)
    """Tuples of (source_path, exception_repr) for files where the
    write attempt raised."""

    @property
    def total(self) -> int:
        return len(self.written) + len(self.skipped) + len(self.errors)


def _origins_sidecar_path(merged_path: Path | str) -> Path:
    """Path of the origins sidecar for a given merged tree."""
    p = Path(merged_path)
    return p.with_name(p.name + _ORIGINS_SUFFIX)


def is_merged_tree(path: str | Path) -> bool:
    """True if ``path`` looks like a merged-tree temp file.

    Used by V1's save path to decide whether to invoke
    :func:`push_back_to_origins` after saving.  Two checks:

    1. The filename stem starts with the merged-tree prefix
       (e.g. ``scriptreering_merged_abc123def456``).
    2. An origins sidecar exists co-located with the file.

    Both must hold -- a file the user happens to name with the
    same prefix isn't a real merged tree without its sidecar.
    """
    try:
        p = Path(path)
    except (TypeError, ValueError):
        return False
    if not p.name.startswith(_MERGED_PREFIX):
        return False
    return _origins_sidecar_path(p).is_file()


def _write_origins_sidecar(
    merged_path: Path,
    entries: Iterable[tuple[str, Path]],
) -> Path:
    """Write the origins sidecar for ``merged_path``.

    ``entries`` is an iterable of ``(folder_name, source_path)``
    pairs in the same order the merged tree's top-level folders
    appear.  The order matters for back-propagation: when two
    members happen to share a folder name (e.g. both renamed to
    "Tools"), the order disambiguates which source each merged
    folder writes back to.
    """
    sidecar = _origins_sidecar_path(merged_path)
    payload = {
        "version": 1,
        "merged_tree": str(merged_path),
        "origins": [
            {
                "folder_name": name,
                "source_path": str(Path(src).resolve()),
            }
            for name, src in entries
        ],
    }
    sidecar.write_text(
        json.dumps(payload, indent=2), encoding="utf-8",
    )
    _log(f"wrote origins sidecar {sidecar}  ({len(payload['origins'])} entries)")
    return sidecar


def _read_origins_sidecar(merged_path: Path | str) -> list[dict] | None:
    """Load the origins sidecar list, or ``None`` if missing /
    malformed.  Returns the raw list of entry dicts so the caller
    can iterate in order."""
    sidecar = _origins_sidecar_path(merged_path)
    if not sidecar.is_file():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log(f"origins sidecar unreadable at {sidecar}: {exc!r}")
        return None
    if not isinstance(data, dict):
        return None
    origins = data.get("origins")
    if not isinstance(origins, list):
        return None
    return origins


def _restore_relative_leaf_paths(
    node,  # noqa: ANN001 -- TreeNode
    origin_dir: Path,
) -> None:
    """Recursively rewrite absolute leaf paths to be relative to
    ``origin_dir`` where possible.

    Inverse of :func:`_resolve_node_paths`.  We want the saved
    source ``.scriptreetree`` to use relative leaf paths (canonical
    convention) rather than absolute ones (merged-tree convention).
    Paths that don't live under ``origin_dir`` are left absolute --
    cross-tree references the user explicitly created.
    """
    if node.type == "leaf" and node.path is not None:
        leaf = Path(node.path)
        if leaf.is_absolute():
            try:
                rel = leaf.resolve().relative_to(origin_dir.resolve())
                # Use forward slashes for cross-platform stability;
                # ``Path.as_posix`` is the standard idiom for this.
                node.path = rel.as_posix()
            except ValueError:
                # Leaf isn't under origin_dir -- keep absolute.
                pass
    elif node.type == "folder":
        for child in node.children:
            _restore_relative_leaf_paths(child, origin_dir)


def push_back_to_origins(merged_path: str | Path) -> PushBackResult:
    """Push edits in a merged tree back to its originating source files.

    Workflow:

      1. Load the merged tree from disk.
      2. Load the origins sidecar (created during
         :func:`build_merged_tree`).
      3. For each top-level folder in the merged tree:
         - Find the matching origin entry by folder name.
         - If the source file ended in ``.scriptreetree``: replace
           that file's ``nodes`` with the folder's children, then
           save -- preserving the original ``TreeDef.name`` and
           other top-level metadata.
         - If the source file ended in ``.scriptree``: the folder
           should contain exactly one leaf whose path is the
           source.  Leaf-only edits to a single-tool catalog are
           not supported here (the leaf path IS the file; editing
           "the tree wrapper" doesn't have an analog).  Skipped
           with a clear reason.
      4. Each leaf path is rewritten from absolute to
         relative-to-origin-folder where possible (so the saved
         source file uses canonical relative paths).

    Returns a :class:`PushBackResult` summarising what was written,
    skipped, or errored.  The caller is expected to surface this
    to the user (status bar / dialog) so they know which files
    on disk just changed.

    Errors during individual file writes do NOT abort the whole
    operation -- each file is independently best-effort.  This
    matches the user contract: "save what you can, tell me what
    you couldn't."
    """
    from scriptree.core.io import load_tree, save_tree
    from scriptree.core.model import TreeDef, TreeNode

    result = PushBackResult()

    merged = Path(merged_path)
    if not merged.is_file():
        result.errors.append(
            (str(merged), "merged tree file not found"),
        )
        return result

    origins = _read_origins_sidecar(merged)
    if origins is None:
        result.errors.append(
            (str(merged), "origins sidecar missing or malformed"),
        )
        return result

    try:
        loaded = load_tree(str(merged))
    except Exception as exc:  # noqa: BLE001
        result.errors.append((str(merged), f"load_tree failed: {exc!r}"))
        return result

    # Build a lookup of folder-name -> top-level node in the merged
    # tree.  Iterate the merged tree's top level once, in order.
    # When two folders share a name we use the first occurrence and
    # the sidecar's order to disambiguate.
    merged_top: list = list(loaded.nodes)

    # Cross-reference the sidecar entries with the merged top in
    # ORDER (position-stable).  If a sidecar entry's folder_name
    # doesn't match the same-position folder in the merged tree
    # (because the user renamed it), fall back to the FIRST
    # remaining folder with that name.
    used_indices: set[int] = set()

    for i, entry in enumerate(origins):
        src_path = entry.get("source_path")
        sidecar_name = entry.get("folder_name", "")
        if not src_path:
            continue

        # Pick the matching merged-tree folder.  Position-first,
        # name-fallback.
        chosen: int | None = None
        if (
            i < len(merged_top)
            and i not in used_indices
            and merged_top[i].type == "folder"
        ):
            chosen = i
        else:
            for j, node in enumerate(merged_top):
                if j in used_indices:
                    continue
                if (
                    node.type == "folder"
                    and node.name == sidecar_name
                ):
                    chosen = j
                    break
        if chosen is None:
            result.skipped.append((
                src_path,
                f"top-level folder '{sidecar_name}' not found in "
                f"saved merged tree (deleted? renamed twice?)",
            ))
            continue
        used_indices.add(chosen)
        folder = merged_top[chosen]

        src = Path(src_path)
        ext = src.suffix.lower()

        if ext == ".scriptreetree":
            # Re-load the existing source so we preserve top-level
            # metadata (TreeDef.name, etc.).  If load fails, fall
            # back to a fresh TreeDef using the folder's display.
            try:
                existing = load_tree(str(src))
            except Exception as exc:  # noqa: BLE001
                _log(
                    f"push_back: load_tree({src}) failed: {exc!r}; "
                    f"will write a fresh TreeDef"
                )
                existing = TreeDef(name=folder.name, nodes=[])

            # Restore relative leaf paths so the source file
            # doesn't carry the merged tree's absolutes.
            for child in folder.children:
                _restore_relative_leaf_paths(child, src.parent)

            # Build a new TreeDef preserving the source's name +
            # other meta, but using the merged folder's children
            # as the new node list.
            new_tree = TreeDef(
                name=existing.name or folder.name,
                nodes=list(folder.children),
            )
            try:
                save_tree(new_tree, str(src))
                result.written.append(str(src))
                _log(f"push_back: wrote {src}")
            except Exception as exc:  # noqa: BLE001
                result.errors.append(
                    (str(src), f"save_tree failed: {exc!r}"),
                )

        elif ext == ".scriptree":
            # Single-tool catalogs -- the folder wraps exactly one
            # leaf that IS the source.  Editing the wrapper folder
            # has no analog in the source.  Skip cleanly.
            result.skipped.append((
                str(src),
                "single-tool .scriptree catalogs can't be edited "
                "via the merged-tree wrapper (the leaf IS the "
                "file)",
            ))

        else:
            result.skipped.append((
                str(src),
                f"unknown source extension {ext!r}",
            ))

    return result


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
