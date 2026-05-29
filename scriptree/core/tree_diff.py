"""Diff + apply for the ``.scriptreetree`` auto-discover feature.

## For humans

This module bridges the walker (``scriptree.core.tree_discover``)
and the in-memory ``TreeDef`` (``scriptree.core.model``).

Two responsibilities:

1. **Diff** — compare the walker's flat candidate list against
   the tree's existing leaves and the user's ``excluded`` list,
   producing a ``TreeDiscoveryDiff`` with three buckets:
   ``added`` / ``removed`` / ``previously_excluded``.
2. **Apply** — given a user-curated subset of those buckets,
   mutate the ``TreeDef`` in place: insert new leaves into the
   right folder nodes (creating folders as needed to mirror the
   discovered hierarchy), drop accepted-remove leaves (and any
   folder nodes left empty by the drop), re-include
   previously-excluded items by removing them from the
   ``excluded`` list and adding them as leaves.

Pure-logic; no UI, no Qt, no disk I/O beyond the existence check
in the diff's "removed" routing.

## The diff's routing rules, in order

For each ``DiscoveredTreeItem`` the walker emitted:

* **Already in the tree** (its resolved-absolute form matches some
  existing leaf's resolved-absolute form): the candidate is
  *ignored*.  No bucket.  It's already accounted for; nothing
  needs to change.
* **In the excluded list** (the user previously removed this path,
  and ``TreeDef.excluded`` still contains it): routed to
  ``previously_excluded`` so the prompt dialog can offer
  re-inclusion.  These appear unchecked by default in the dialog.
* **Anything else**: routed to ``added``.  These appear checked by
  default in the dialog.

For each leaf currently in the tree:

* **Discovered**: ignored (handled by the discovered-side rule
  above).
* **Not discovered**: ``removed`` *only if* the leaf's file no
  longer exists on disk.  If the file still exists but wasn't
  discovered (because it's outside the configured ``roots``,
  or because a sibling tree now claims that subdir), the leaf
  is left alone.  Auto-removing a leaf whose file still exists
  would silently delete hand-curated content; the user must
  explicitly drop those via the tree editor.

The "still exists on disk" check is intentionally **not** "still
matches the walker's priority rule with the current config".
That stricter rule would surface leaves as ``removed`` whenever a
``.scriptreetree`` was added next to them, which is the user's
prerogative — not the walker's call.

## The apply's mutation rules

In order, on each call to ``apply_diff_to_tree``:

1. **Removes** are applied first.  Each accepted-remove leaf is
   located by normalised path and dropped wherever it sits in
   ``tree.nodes``.  After every drop, any folder node that's
   now empty (no children of any kind) is also dropped — this
   recurses bottom-up, so a chain of nested empty folders
   collapses fully.  This is intentional: dead folders are
   visual noise in the menu, and the user removed the only leaf
   that justified them.
2. **Re-includes** clear ``tree.excluded`` of matching entries
   (the user has said "I want this back"), then fall through to
   the same insertion path as adds.
3. **Adds** are applied last.  For each accepted-add item, the
   tree is walked by the candidate's ``rel_path`` parts;
   folder nodes are *found* if they already exist with a
   matching ``name``, *created* if they don't.  When the
   recursion bottoms out at the last path component, a leaf
   node is appended — unless an identical-path leaf already
   exists in that container, in which case the add is a no-op
   (idempotency).

The tree's ``auto_discover`` settings field is *never* touched by
this module — that's the settings dialog's job.

## For maintainers / LLMs

* The path-matching across this module and ``tree_discover``
  goes through identical ``_norm`` helpers (lower-case AND
  resolve).  If the two copies ever drift, diff comparisons will
  silently desync — keep them byte-for-byte equal.  Both target
  the Windows case-folded behaviour ScripTree's deployment
  needs.
* ``apply_diff_to_tree`` mutates in place.  The caller owns the
  ``TreeDef`` and decides whether to deep-copy before calling.
  Mutate-in-place matches the forest's controller pattern and
  avoids the cost of a deep clone of a multi-hundred-leaf tree
  on every prompt cycle.
* ``_insert_leaf_for_path`` does NOT preserve display_name,
  icon, or any other per-node metadata when re-encountering an
  existing folder by name.  Discovery-driven inserts always
  use bare folders; if the author had customised a folder's
  display, that customisation is preserved (the recursion finds
  the existing node and doesn't replace it).
* Folder collapse on empty: the recursion is bottom-up and
  iterative within each container; a chain like
  ``folder/sub/sub/sub/leaf`` where every container becomes
  empty after the leaf drop collapses all four containers in
  one pass.  This is the intentional design — leaving
  intermediate empty folders would be a worse UX than removing
  them.
* The diff's "removed" rule never adds anything to
  ``excluded``.  The user opted-in to removing a leaf whose
  file is missing; they did NOT say "don't ever suggest this
  again".  The path is already absent from the walker's output
  (file gone), so there's nothing to exclude *against*.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .model import TreeDef, TreeNode
from .tree_discover import DiscoveredTreeItem, _norm


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class TreeDiscoveryDiff:
    """The shape the diff function produces, fed into the dialog.

    Three buckets, each of which the dialog presents as a separate
    list-with-checkboxes:

    ``added``
        Newly-found candidates that are not in the tree and not in
        ``excluded``.  Dialog defaults: checked.  Apply: insert as
        leaves at the right folder depth.

    ``removed``
        Leaves currently in the tree whose underlying file has
        vanished from disk.  Dialog defaults: checked (the leaf
        points at a missing file; the user almost always wants
        it gone).  Apply: drop the leaf; collapse empty parent
        folders.  Note: NOT added to ``excluded`` — the file is
        already gone, so there's nothing for exclusion to guard
        against.

    ``previously_excluded``
        Newly-found candidates whose path matches an entry in
        ``TreeDef.excluded``.  The user previously said "stop
        suggesting this"; the dialog still surfaces them in
        case the user changed their mind.  Dialog defaults:
        UNCHECKED.  Apply: remove from ``tree.excluded``;
        insert as leaves.

    ``is_empty()`` returns ``True`` when there's nothing to show,
    which the controller uses to skip the dialog entirely (no
    point asking the user to confirm "nothing to do").
    """

    added: list[DiscoveredTreeItem] = field(default_factory=list)
    removed: list[TreeNode] = field(default_factory=list)
    previously_excluded: list[DiscoveredTreeItem] = field(
        default_factory=list,
    )

    def is_empty(self) -> bool:
        return not (
            self.added or self.removed or self.previously_excluded
        )


# ---------------------------------------------------------------------------
# Helpers — TreeDef traversal
# ---------------------------------------------------------------------------

def _resolve_leaf_abs(leaf_path: str, anchor: Path) -> Path:
    """Resolve a ``TreeNode.path`` to an absolute Path against an
    anchor (typically the tree file's directory).

    Leaf paths are relative in the ``.scriptreetree`` JSON by
    convention (``./folder/tool.scriptree``), but absolute paths
    are also legal.  Anchor + ``resolve()`` handles both
    uniformly.

    Falls back to a best-effort ``Path(leaf_path).resolve()`` if
    the anchored resolve raises — better to compare two
    not-fully-resolved paths than to crash the diff.
    """
    p = Path(leaf_path)
    if not p.is_absolute():
        try:
            p = (anchor / p).resolve()
        except (OSError, ValueError, RuntimeError):
            p = anchor / p
    else:
        try:
            p = p.resolve()
        except (OSError, ValueError, RuntimeError):
            pass
    return p


def _collect_existing_leaves(
    nodes: list[TreeNode],
    anchor: Path,
) -> dict[str, TreeNode]:
    """Walk ``nodes`` recursively and return a map from normalised
    absolute path → leaf TreeNode.

    Used by the diff to detect "this discovered candidate is
    already in the tree".  Folder nodes are not entries in the
    returned map; they're descended into but not collected.

    Leaves with empty / None ``path`` are skipped (malformed
    legacy data); they can't match anything anyway.
    """
    out: dict[str, TreeNode] = {}

    def _walk(group: list[TreeNode]) -> None:
        for n in group:
            if n.type == "leaf" and n.path:
                abs_p = _resolve_leaf_abs(n.path, anchor)
                out[_norm(str(abs_p))] = n
            elif n.type == "folder":
                _walk(n.children)

    _walk(nodes)
    return out


def _prune_and_collapse(
    nodes: list[TreeNode],
    remove_keys: set[str],
    anchor: Path,
) -> None:
    """Drop every leaf in ``nodes`` whose normalised abs path is
    in ``remove_keys``; then drop any folder node that became
    empty.

    Mutates ``nodes`` in place.  Recurses into folder children
    bottom-up so a chain of all-empty parents collapses cleanly.
    """
    i = 0
    while i < len(nodes):
        n = nodes[i]
        if n.type == "leaf" and n.path:
            key = _norm(str(_resolve_leaf_abs(n.path, anchor)))
            if key in remove_keys:
                nodes.pop(i)
                continue
        elif n.type == "folder":
            _prune_and_collapse(n.children, remove_keys, anchor)
            if not n.children:
                nodes.pop(i)
                continue
        i += 1


def _insert_leaf_for_path(
    nodes: list[TreeNode],
    rel_path: str,
    *,
    leaf_path_for_storage: str,
) -> None:
    """Insert a leaf for ``rel_path`` into ``nodes``, creating
    folder nodes as needed to mirror the path's hierarchy.

    ``rel_path``
        The walker's ``DiscoveredTreeItem.rel_path`` for the
        candidate being added.  Forward-slash, ``./``-prefixed.
        Drives the folder structure: every path component
        before the final basename becomes a folder node by
        that name.

    ``leaf_path_for_storage``
        What gets stored in the new leaf's ``path`` field.
        Almost always equals ``rel_path``; broken out so future
        callers can override (e.g. store an absolute path when
        the discovered item lives outside the anchor folder).

    Idempotency: if a leaf with the same ``path`` already
    exists in the target container, the call is a no-op.  This
    matters for re-runs of the apply step and for re-include
    flows.

    Existing folder nodes with a matching ``name`` are reused
    (display_name / icon / other metadata preserved).  Only
    folders are matched by ``name``; a folder named ``foo`` is
    NOT the same as a leaf whose path happens to start with
    ``foo`` in its filename.
    """
    parts = rel_path.removeprefix("./").split("/")
    if not parts or parts == [""]:
        return  # malformed; skip silently

    if len(parts) == 1:
        # Top-level leaf in this container.
        for n in nodes:
            if (
                n.type == "leaf"
                and (n.path or "") == leaf_path_for_storage
            ):
                return  # already there; idempotent no-op
        nodes.append(TreeNode(
            type="leaf",
            path=leaf_path_for_storage,
        ))
        return

    # Find or create the folder for the first component.
    folder_name = parts[0]
    folder_node: TreeNode | None = None
    for n in nodes:
        if n.type == "folder" and n.name == folder_name:
            folder_node = n
            break
    if folder_node is None:
        folder_node = TreeNode(
            type="folder", name=folder_name, children=[],
        )
        nodes.append(folder_node)

    # Recurse into the folder with the remaining path components.
    remaining = "./" + "/".join(parts[1:])
    _insert_leaf_for_path(
        folder_node.children,
        remaining,
        leaf_path_for_storage=leaf_path_for_storage,
    )


# ---------------------------------------------------------------------------
# Public API — diff
# ---------------------------------------------------------------------------

def diff_against_tree(
    tree: TreeDef,
    tree_file: str | Path,
    discovered: list[DiscoveredTreeItem],
    excluded: list[str] | None = None,
) -> TreeDiscoveryDiff:
    """Compute the three-bucket diff for a tree.

    Parameters
    ----------
    tree:
        The current in-memory ``TreeDef``.  Read-only — this
        function does not mutate it.
    tree_file:
        Path to the ``.scriptreetree`` file backing ``tree``.
        Used as the anchor for resolving relative leaf paths so
        "is this leaf the same as that discovered candidate?"
        comparisons are accurate.  Must be the same path that
        was passed to ``discover_for_tree`` for the
        ``discovered`` list to be coherent.
    discovered:
        The output of ``discover_for_tree`` for this tree.  Can
        be empty; the function still produces a useful diff (the
        ``removed`` bucket may still be populated if leaves
        point at missing files).
    excluded:
        The ``TreeDef.excluded`` list (or any list of paths the
        caller wants treated as excluded).  When ``None``, falls
        back to ``tree.excluded``.

    Returns
    -------
    ``TreeDiscoveryDiff`` with three buckets.  See its docstring
    for routing semantics.

    Does not raise.  Disk access is limited to one ``exists()``
    check per existing leaf when deciding ``removed`` membership;
    permission / IO errors are swallowed and the leaf is left
    alone (treating "can't tell" as "still present").
    """
    anchor = Path(tree_file).resolve().parent
    eff_excluded = excluded if excluded is not None else tree.excluded

    existing = _collect_existing_leaves(tree.nodes, anchor)
    excluded_norm = {
        _norm(str(_resolve_leaf_abs(p, anchor)))
        for p in eff_excluded
    }
    discovered_keys = {_norm(i.abs_path) for i in discovered}

    diff = TreeDiscoveryDiff()

    # Route discovered candidates into added / previously_excluded /
    # (silently ignored, when already in tree).
    for item in discovered:
        key = _norm(item.abs_path)
        if key in existing:
            continue
        if key in excluded_norm:
            diff.previously_excluded.append(item)
        else:
            diff.added.append(item)

    # Route existing leaves into removed.  Stable order: preserve
    # the order leaves appear in the tree by walking nodes via the
    # same recursive helper used by ``_collect_existing_leaves``,
    # but skip the ones already discovered.  We re-iterate the
    # tree rather than using the dict order so the user sees
    # removals in the same order as the source.
    def _walk_for_removed(group: list[TreeNode]) -> None:
        for n in group:
            if n.type == "leaf" and n.path:
                key = _norm(str(_resolve_leaf_abs(n.path, anchor)))
                if key in discovered_keys:
                    continue
                # File-still-exists check.
                try:
                    exists = _resolve_leaf_abs(n.path, anchor).exists()
                except OSError:
                    exists = True  # treat unknown as still-there
                if exists:
                    continue
                diff.removed.append(n)
            elif n.type == "folder":
                _walk_for_removed(n.children)

    _walk_for_removed(tree.nodes)

    return diff


# ---------------------------------------------------------------------------
# Public API — apply
# ---------------------------------------------------------------------------

def apply_diff_to_tree(
    tree: TreeDef,
    tree_file: str | Path,
    *,
    accepted_adds: list[DiscoveredTreeItem] | None = None,
    accepted_removes: list[TreeNode] | None = None,
    accepted_reincludes: list[DiscoveredTreeItem] | None = None,
) -> None:
    """Mutate ``tree`` in place by applying the user's accepted
    changes from a diff.

    Parameters
    ----------
    tree:
        ``TreeDef`` to mutate.  Both ``nodes`` and ``excluded``
        may be modified.  ``auto_discover`` is never touched —
        that's the settings dialog's job.
    tree_file:
        Path used as the anchor for resolving relative leaf
        paths in the prune step.  Must match what was used by
        the diff that produced the lists below.
    accepted_adds:
        Candidates the user wants inserted as new leaves.
        Folder nodes are created automatically as needed to
        mirror each candidate's ``rel_path``.  Idempotent: a
        candidate whose path already matches an existing leaf
        is a no-op.
    accepted_removes:
        Leaves the user wants dropped.  Each leaf is located by
        its resolved-absolute path and removed wherever it sits
        in the tree.  Folder nodes left empty after a drop are
        also removed (recursively, bottom-up).
    accepted_reincludes:
        Candidates from the diff's ``previously_excluded``
        bucket that the user wants back.  These are removed
        from ``tree.excluded`` (so future scans treat them as
        regular candidates again) and then inserted as leaves
        via the same path as ``accepted_adds``.

    All three list parameters default to empty.  Calling the
    function with all three empty is a no-op (returns
    immediately).

    Order of operations: removes first, then re-includes, then
    adds.  This order matters: a leaf could in principle appear
    in both ``accepted_removes`` and ``accepted_adds`` (a user
    contortion); the final state of the tree would then be "the
    leaf is present" (add wins) — which is the more conservative
    outcome (avoids data loss).
    """
    adds = list(accepted_adds or [])
    removes = list(accepted_removes or [])
    reincludes = list(accepted_reincludes or [])

    if not (adds or removes or reincludes):
        return  # nothing to do

    anchor = Path(tree_file).resolve().parent

    # Step 1: removes.
    if removes:
        remove_keys = {
            _norm(str(_resolve_leaf_abs(n.path or "", anchor)))
            for n in removes
            if n.path
        }
        _prune_and_collapse(tree.nodes, remove_keys, anchor)

    # Step 2: re-includes -- drop matching entries from excluded.
    if reincludes:
        reinc_keys = {_norm(i.abs_path) for i in reincludes}
        tree.excluded = [
            p for p in tree.excluded
            if _norm(str(_resolve_leaf_abs(p, anchor))) not in reinc_keys
        ]

    # Step 3: adds (including re-includes which insert the same way).
    for item in adds + reincludes:
        _insert_leaf_for_path(
            tree.nodes,
            item.rel_path,
            leaf_path_for_storage=item.rel_path,
        )


__all__ = [
    "TreeDiscoveryDiff",
    "apply_diff_to_tree",
    "diff_against_tree",
]
