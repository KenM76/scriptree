"""Auto-discovery walker for ``.scriptreetree`` files.

## For humans

This module answers a single question for a given
``.scriptreetree`` file: *"Which ``.scriptree`` files (and
optionally, which sibling ``.scriptreetree`` files) on disk should
be considered as candidates for this tree?"*

The result is a flat list of ``DiscoveredTreeItem`` records.  Each
record carries:

* the absolute path on disk (so the loader can read it),
* a forward-slash *relative* path anchored on the tree file's
  directory (so the Phase 3 diff/apply step can place the leaf
  inside the right folder node when it's accepted),
* a kind (``"tool"`` for ``.scriptree`` files, ``"sibling_tree"``
  for ``.scriptreetree`` files surfaced as candidates for
  nesting).

What the walker does NOT do:

* No diffing against the current tree's existing ``nodes``.  The
  walker emits every candidate it finds; the diff function in
  Phase 3 (``scriptree.core.tree_diff``) routes them into
  ``added`` / ``previously_excluded`` based on the tree's state.
  Mirrors the forest's design choice (walker / diff are
  deliberately separable).
* No exclusion filtering.  Same reason — the diff step routes
  excluded paths into a separate bucket so the prompt dialog can
  offer re-inclusion.  Filtering at walker level would silently
  drop them.
* No file parsing.  The walker only checks suffixes.  Broken
  ``.scriptree`` files surface as candidates and the Phase 3 /
  Phase 4 layers decide whether to show them as errors or skip
  them.
* No mutation of the ``TreeDef``.  Mutation is Phase 3's job.

## The walker's rules, in order

For each directory ``d`` reached by depth-first traversal of a
configured root:

1. If ``d`` is itself a hidden directory (basename starts with
   ``.``) AND ``d`` is not the explicit root, **skip ``d``
   entirely**.  Filters ``.git``, ``.vscode``, etc.  An explicit
   dotted root is honoured (rare, but the user might genuinely
   want to scan ``./.tools/``).

2. List every ``.scriptreetree`` file directly in ``d``,
   **excluding the tree file being scanned**.  Call the
   non-self set *other-trees*.

3. If ``d`` is the **root** directory (the tree file's parent
   directory or another configured root):
   * Emit every ``.scriptree`` file in ``d`` as a tool
     candidate.
   * If ``include_sibling_trees`` is true, emit each other-tree
     as a sibling-tree candidate.
   * Recurse into every non-hidden subdirectory.

4. If ``d`` is NOT the root and ``d`` contains other-trees:
   * If ``include_sibling_trees`` is true, emit each other-tree
     as a sibling-tree candidate.
   * Do NOT emit ``.scriptree`` files in ``d`` (they belong
     to the other tree that owns this subdirectory).
   * Do NOT descend into ``d``'s subdirectories.

5. If ``d`` is NOT the root and ``d`` contains no other-trees:
   * Emit every ``.scriptree`` file in ``d`` as a tool
     candidate.
   * Recurse into every non-hidden subdirectory.

The asymmetry in rule 3 vs 4 (the root scans for ``.scriptree``
files even when sibling trees are present at the root level, but a
non-root subdirectory does not) deliberately matches the user's
mental model: "the tree's own folder is its scope; another tree at
the same level is a *peer*, not an *owner*."  A subdirectory with
its own ``.scriptreetree``, however, IS owned by that other tree
and its contents are off-limits.

## Why the symlink-loop guard

``max_depth=16`` is a defensive cap, not a hard limit on real
project depths (which are typically 2-4).  A misconfigured symlink
cycle would otherwise loop forever; 16 levels is enough for any
real layout and shallow enough that the user notices when they
accidentally point a root at ``/``.

## For maintainers / LLMs

* This module is in ``scriptree.core``.  It must NOT import
  anything from ``scriptree.shell`` or ``scriptree.ui`` — those
  would pull Qt and break the headless ``python -m scriptree
  validate`` path.  ``tests/test_core_purity.py`` enforces this.
* All path normalisation goes through ``_norm`` — lower-cases AND
  resolves.  Matches the forest's normalisation byte-for-byte so
  cross-feature comparisons (e.g. a future tag-aware menu that
  unifies forest items and tree leaves) don't desync on Windows
  case-folding.  On a case-sensitive filesystem this would conflate
  ``Foo`` and ``foo`` — an accepted Windows-target trade-off.
* The ``rel_path`` field uses forward-slashes regardless of OS.
  Matches the convention in existing ``.scriptreetree`` files
  (``TreeNode.path`` is always forward-slash).  Mixing
  backslashes would break round-trip with hand-edited files on
  Windows.  ``rel_path`` starts with ``./`` so the relative form
  is unambiguous even when the leaf name itself starts with a
  dot.
* ``discover_for_tree`` deduplicates across overlapping roots by
  normalised absolute path — first-wins.  Configuring two roots
  that share a subdirectory (e.g. ``["./", "./subset"]``) is a
  user error; we make it harmless.
* The walker is recursive (function calls), not iterative-with-stack
  like ``forest_discover``.  Recursion is simpler here because the
  per-directory decision branches more (rule 3 vs 4 vs 5) and the
  depth budget (16) is well below Python's recursion limit (1000).
  If this ever shows up in a profile it can be rewritten as a stack
  walk; the public API does not depend on the implementation choice.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal


TreeItemKind = Literal["tool", "sibling_tree"]
"""What kind of file a ``DiscoveredTreeItem`` points at.

* ``"tool"`` — a ``.scriptree`` file.  Goes into the tree as a
  ``TreeNode(type="leaf", path=...)`` when accepted.
* ``"sibling_tree"`` — a ``.scriptreetree`` file other than the
  one being scanned.  Goes into the tree as a leaf pointing at
  another tree (which the launcher will load as a nested
  sub-tree at click time).  Only emitted when the tree's
  ``include_sibling_trees`` flag is true.
"""


_TOOL_SUFFIX = ".scriptree"
"""Filename suffix for tool catalogs.  Lowercase comparison."""

_TREE_SUFFIX = ".scriptreetree"
"""Filename suffix for tree catalogs.  Note that this is also a
valid suffix for the ``_TOOL_SUFFIX`` test (``.scriptree`` IS a
substring of ``.scriptreetree``), so the order of checks matters:
test ``_TREE_SUFFIX`` first, then ``_TOOL_SUFFIX``.  The
``_classify`` helper below enforces this order."""


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DiscoveredTreeItem:
    """One candidate the walker decided is in scope.

    Three fields:

    ``abs_path``    Absolute, OS-native form.  Use this when the
                    consumer needs to open or stat the file
                    (e.g. the Phase 4 dialog showing a tool's
                    description, the Phase 3 diff checking
                    file existence on disk).

    ``rel_path``    Forward-slash, prefixed with ``"./"``,
                    anchored on the tree file's directory.
                    Use this when storing the candidate into
                    a ``TreeNode.path`` field on accept — the
                    rest of the codebase expects relative
                    paths in that shape.  When the candidate
                    sits *outside* the tree file's directory
                    tree (rare; only possible via a
                    ``roots: ["../somewhere"]`` config), the
                    field falls back to an absolute
                    forward-slash form so the consumer can
                    still pass it through unchanged.

    ``kind``        ``"tool"`` or ``"sibling_tree"`` — see
                    ``TreeItemKind`` docstring.

    Marked ``frozen=True`` so the result can be put in a ``set``
    or used as a dict key without surprises.  Comparison is by
    every field (Python's default), so two records with the same
    ``abs_path`` but different ``rel_path`` would compare unequal
    — in practice the walker always derives ``rel_path`` from
    ``abs_path`` plus a fixed anchor, so this isn't a hazard.
    """

    abs_path: str
    rel_path: str
    kind: TreeItemKind


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _norm(path: str | Path) -> str:
    """Normalised form used for set-membership comparisons.

    Lower-cases, resolves symlinks/relative components, and
    swaps backslashes for forward-slashes so two records pointing
    at the same file compare equal regardless of OS or how the
    path was originally supplied.

    Falls back to a best-effort cleanup when ``resolve()`` raises
    (broken symlink, permission error, encoding edge case) — better
    to compare two non-resolved paths than to crash discovery.
    """
    try:
        return str(Path(path).resolve()).lower().replace("\\", "/")
    except (OSError, ValueError, RuntimeError):
        return str(path).lower().replace("\\", "/")


def _to_rel(abs_path: str, anchor: Path) -> str:
    """Convert ``abs_path`` to a ``./``-prefixed, forward-slash
    relative path anchored on ``anchor``.

    Used to produce the ``DiscoveredTreeItem.rel_path`` field.
    See that docstring for the consumer contract.

    When ``abs_path`` is not a descendant of ``anchor`` (the rare
    case of a configured root above the tree file's directory),
    the result is the absolute forward-slash form — still a
    valid ``TreeNode.path`` value but no longer portable across
    machines.  The caller (the user's auto-discover config) bears
    the portability cost of opting into that layout.
    """
    try:
        rel = Path(abs_path).resolve().relative_to(anchor.resolve())
        # ``str(PurePath)`` joins with OS separators; force forward.
        return "./" + str(rel).replace("\\", "/")
    except ValueError:
        return str(Path(abs_path).resolve()).replace("\\", "/")


def _classify(name: str) -> TreeItemKind | None:
    """Return the kind of file ``name`` is, or ``None`` if it's
    neither a tool nor a tree catalog.

    Test the longer suffix first — ``.scriptreetree`` contains
    ``.scriptree`` as a substring and ``endswith`` matching
    against the shorter suffix would silently mis-classify every
    tree as a tool.
    """
    lower = name.lower()
    if lower.endswith(_TREE_SUFFIX):
        return "sibling_tree"
    if lower.endswith(_TOOL_SUFFIX):
        return "tool"
    return None


def _list_classified(d: Path) -> tuple[list[Path], list[Path]]:
    """Return ``(tool_files, tree_files)`` in directory ``d``.

    Hidden-file check is NOT applied at file level — only at
    directory level.  A user may genuinely have a ``.beta.scriptree``
    they want surfaced.  The directory-level hidden-dir filter is
    sufficient to avoid VCS / IDE noise.
    """
    tools: list[Path] = []
    trees: list[Path] = []
    try:
        for entry in d.iterdir():
            if not entry.is_file():
                continue
            kind = _classify(entry.name)
            if kind == "tool":
                tools.append(entry)
            elif kind == "sibling_tree":
                trees.append(entry)
    except OSError:
        # Permission error / vanished mid-scan — skip ``d`` silently.
        # A user-visible error is the wrong response here; the
        # walker's job is best-effort discovery.
        pass
    return tools, trees


# ---------------------------------------------------------------------------
# Walker
# ---------------------------------------------------------------------------

def _walk_dir(
    d: Path,
    *,
    tree_file_norm: str,
    include_sibling_trees: bool,
    anchor: Path,
    is_root_dir: bool,
    max_depth: int,
    depth: int,
) -> Iterable[DiscoveredTreeItem]:
    """Yield ``DiscoveredTreeItem``s from ``d`` and (when allowed)
    its descendants.

    See the module docstring for the full rule list.  In short:

    * Always skip if depth budget exhausted.
    * Skip hidden non-root dirs.
    * Find ``other_trees`` (non-self ``.scriptreetree`` files in
      ``d``).
    * Root: emit tools, emit sibling-trees (if flag), recurse.
    * Non-root with other-trees: emit sibling-trees only (if
      flag), don't recurse.
    * Non-root without other-trees: emit tools, recurse.
    """
    if depth > max_depth:
        return
    if not is_root_dir and d.name.startswith("."):
        return
    if not d.is_dir():
        return

    tool_files, tree_files = _list_classified(d)
    other_trees = [
        t for t in tree_files if _norm(t) != tree_file_norm
    ]
    has_other_trees = bool(other_trees)

    # ----- Emission decisions ---------------------------------------
    #
    # The rule asymmetry between root and non-root dirs is intentional;
    # see the module docstring's "rules in order" section.
    if include_sibling_trees and other_trees:
        for t in other_trees:
            yield DiscoveredTreeItem(
                abs_path=str(t.resolve()),
                rel_path=_to_rel(str(t), anchor),
                kind="sibling_tree",
            )

    # Tool emission: ALL on root; only when no other-trees off-root.
    if is_root_dir or not has_other_trees:
        for f in tool_files:
            yield DiscoveredTreeItem(
                abs_path=str(f.resolve()),
                rel_path=_to_rel(str(f), anchor),
                kind="tool",
            )

    # ----- Recursion -------------------------------------------------
    #
    # Descent suppression: at a non-root subdir owned by another
    # tree, we deliberately do NOT recurse into its subtree.  At the
    # root, we always recurse regardless of other-trees present at
    # the same level (peers, not owners).
    if not is_root_dir and has_other_trees:
        return

    try:
        sub_dirs = [
            s for s in d.iterdir()
            if s.is_dir() and not s.name.startswith(".")
        ]
    except OSError:
        return

    for sub in sub_dirs:
        yield from _walk_dir(
            sub,
            tree_file_norm=tree_file_norm,
            include_sibling_trees=include_sibling_trees,
            anchor=anchor,
            is_root_dir=False,
            max_depth=max_depth,
            depth=depth + 1,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def discover_for_tree(
    tree_file: str | Path,
    *,
    roots: list[str] | None = None,
    include_sibling_trees: bool = True,
    max_depth: int = 16,
) -> list[DiscoveredTreeItem]:
    """Walk the discovery roots for the given tree file.

    Parameters
    ----------
    tree_file:
        Path to the ``.scriptreetree`` file driving the scan.
        The walker resolves it (so it can be relative when called
        from a test) and uses ``Path(tree_file).parent`` as the
        anchor for ``rel_path`` and for resolving any relative
        entries in ``roots``.  Also used to self-exclude: a
        ``.scriptreetree`` whose normalised path matches this
        file is never emitted as a sibling-tree candidate.

    roots:
        Folders to scan, relative to ``Path(tree_file).parent``
        or absolute.  When ``None`` (the typical case), defaults
        to ``["."]`` — i.e. the tree file's own directory.
        Folders that don't exist are skipped silently (matches
        forest semantics: a config that lists optional roots
        shouldn't break loading if some are absent on this
        machine).  An empty list yields an empty result.

    include_sibling_trees:
        When ``True`` (default), ``.scriptreetree`` files other
        than ``tree_file`` are emitted as ``"sibling_tree"``
        candidates.  When ``False``, they are still respected as
        boundaries (i.e. their subdirs are skipped) but the file
        itself is not surfaced.  Set this to ``False`` for
        master / aggregator trees that should stay flat.

    max_depth:
        Safety cap against pathological symlink loops.  16 is
        enough for any real layout; lower if you genuinely want
        a shallow scan.

    Returns
    -------
    Flat list of ``DiscoveredTreeItem``.  Order is depth-first,
    files in each directory in ``Path.iterdir`` order (which is
    OS-dependent — do not rely on it).  Deduplicated across
    overlapping roots by normalised absolute path; first hit
    wins.

    Does NOT raise.  The walker swallows ``OSError`` on
    unreadable directories and falls back to best-effort path
    normalisation on bad paths.  An empty list is the
    walker's signal for "nothing found OR everything errored";
    callers that need to distinguish must check the file system
    themselves.

    See module docstring for the full rule semantics and the
    rationale behind each design choice.
    """
    tree_path = Path(tree_file).resolve()
    anchor = tree_path.parent
    tree_norm = _norm(tree_path)

    eff_roots = roots if roots is not None else ["."]

    seen: set[str] = set()
    out: list[DiscoveredTreeItem] = []
    for r in eff_roots:
        rp = Path(r)
        if not rp.is_absolute():
            rp = (anchor / rp).resolve()
        else:
            rp = rp.resolve()
        if not rp.is_dir():
            continue
        for item in _walk_dir(
            rp,
            tree_file_norm=tree_norm,
            include_sibling_trees=include_sibling_trees,
            anchor=anchor,
            is_root_dir=True,
            max_depth=max_depth,
            depth=0,
        ):
            key = _norm(item.abs_path)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


__all__ = [
    "DiscoveredTreeItem",
    "TreeItemKind",
    "discover_for_tree",
]
