"""Auto-organise apps into category trees (v0.8.0a25+).

## What this module does

The forest's discovery walker (``scriptree.shell.forest_discover``)
returns a flat list of ``DiscoveredItem`` records — one per
``.scriptree`` / ``.scriptreetree`` / ``.scriptreering`` found on
disk.  Historically each of those becomes one cell on the forest
master, so a workspace with eight MS Office automation tools shows
eight cells side-by-side.

This module groups those flat items by their authoring-time
``category`` metadata (a slash-delimited path like
``"MSOffice/Word"``) and emits a smaller list where any top-level
category shared by **two or more** items has been rolled up into
one synthesised ``.scriptreetree`` that will become a single cell.

The grouping is purely a *view transformation*: we never move or
rename anything on disk; the synthesised tree is a fresh file
written to the personal-apps "_groups" directory and the user can
still navigate to each underlying tool individually if they want.

## Public API

``group_by_category(items, *, output_dir, existing_tree_names=None)``
runs the full pass:

  1. Buckets the inputs by category.
  2. Builds a category trie.
  3. Walks the trie; any top-level node with ≥ 2 items in its
     subtree synthesises a ``.scriptreetree`` (the trie itself
     drives the folder/leaf hierarchy).
  4. Returns ``(grouped_items, synthesised_paths)`` where
     ``grouped_items`` is the new flat list the forest should
     display and ``synthesised_paths`` is the set of disk paths
     that were written so the caller can include them in the
     forest's discovery / cleanup logic.

``existing_tree_names`` is a case-folded set of stems
(e.g. ``{"msoffice", "devtools"}``) the caller already knows
about; when a synthesised tree would collide with one, the
synthesised version is named ``<TopSegment>__auto.scriptreetree``
instead, so we never overwrite user-authored trees.

## Algorithm — concrete worked example

Inputs:

    A: StyleSanitizer.scriptree  category=MSOffice/Word
    B: WordCounter.scriptree     category=MSOffice/Word
    C: CellAggregator.scriptree  category=MSOffice/Excel
    D: GitStatus.scriptree       category=DevTools
    E: RandomTool.scriptree      category=

Trie:

    MSOffice  (3 items in subtree)
    ├── Word   (2 items)  -> [A, B]
    └── Excel  (1 item)   -> [C]
    DevTools  (1 item)    -> [D]
    "" (uncategorised)    -> [E]

Pass rule: top-level segment with ≥ 2 items in its full subtree
becomes a synthesised tree.

    MSOffice: 3 items -> synthesise
        MSOffice.scriptreetree:
            nodes:
                folder "Word":
                    leaf A
                    leaf B
                folder "Excel":
                    leaf C
    DevTools: 1 item  -> pass through as flat ForestItem (D)
    "":       1 item  -> pass through as flat ForestItem (E)

Result: three ForestItems (MSOffice tree, GitStatus, RandomTool)
instead of five.

## Why "≥ 2" not "≥ 1"

A "tree of one" reads as clutter for the user — it adds a layer of
indirection (folder cell → menu pop → one tool) without removing
the original problem (one cell per app).  Holding the threshold at
two also keeps single-vendor / single-domain installs noise-free
during the warm-up phase before the user has installed enough
related tools to need grouping.  The rule is easy to flip later
via a forest setting if a user prefers "always wrap".

## Why we don't write to the install tree

Synthesised trees live in
``default_personal_root()/_groups/<TopSegment>.scriptreetree``.
Reasons:

* The personal-apps root is already writable (the drop-install
  dialog targets it for installs by default); using the same root
  keeps the on-disk footprint small.
* Putting them under ``_groups/`` (note the leading underscore)
  keeps them visually distinct from real installed apps in any
  file browser, so the user can ``rm -rf _groups`` to fully reset
  the group state if anything goes wrong.
* Synthesised trees travel with the user via per-machine paths,
  not with the forest file -- so the forest config stays
  portable even after group passes have synthesised trees on
  the current machine.

## What this module does NOT do

* It does NOT mutate the source ``.scriptree`` / ``.scriptreetree``
  files in any way.  Recategorising a tool is purely an edit on
  the source file; the next group pass picks it up.
* It does NOT touch the forest's ``ForestItem`` records directly.
  The caller (``forest_controller.discover_now``) takes the
  grouped item list and feeds it into the standard diff/apply
  machinery.
* It does NOT delete stale synthesised trees on its own — that's
  a separate concern handled by ``prune_orphan_synthesised``
  below, fired by the caller after a successful pass.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data model — minimal shape, intentionally decoupled from the full
# ``DiscoveredItem`` so this module remains pure Python (no Qt).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupCandidate:
    """Input record for ``group_by_category``.

    Frozen so callers can build them once from their richer
    ``DiscoveredItem`` records and pass them in without worrying
    about us mutating them.
    """

    path: str
    """Absolute disk path to the ``.scriptree`` / ``.scriptreetree``."""

    category: str
    """The catalog's ``category`` field, already normalised (no
    leading/trailing slashes, no empty segments).  Empty string
    means uncategorised."""

    display_name: str
    """Human-readable label for the leaf node (typically
    ``ToolDef.name`` or ``TreeDef.name``).  Used as the leaf node's
    ``name`` field in the synthesised tree."""


@dataclass
class GroupOutcome:
    """One element of ``group_by_category``'s output.

    Two kinds, distinguished by ``kind``:

    * ``kind == "passthrough"`` — this candidate appears as-is in
      the forest (no grouping applied).  ``synthesised_path`` is
      ``None``; ``original_path`` is the same as the input.
    * ``kind == "synthesised"`` — a brand-new ``.scriptreetree``
      was written at ``synthesised_path``; the caller should add
      *that* path to the forest instead of the original items
      (which are now leaves inside the synthesised tree).
      ``original_paths`` lists every input that got rolled up.
    """

    kind: str  # "passthrough" or "synthesised"
    path: str  # the path the forest should display
    original_paths: list[str] = field(default_factory=list)
    """For ``synthesised``: every input rolled in.  For
    ``passthrough``: list containing only the input's own path
    (so callers can do bulk operations uniformly)."""


# ---------------------------------------------------------------------------
# Filename sanitisation (top-level category -> filesystem-safe stem)
# ---------------------------------------------------------------------------


_UNSAFE = re.compile(r'[<>:"|?*\x00-\x1f/\\]')


def _safe_stem(segment: str) -> str:
    """Return a safe filename stem for a top-level category segment.

    Scrubs the characters Windows rejects (``< > : " | ? *`` and
    control codes) plus forward and back slashes (defensive — the
    loader already rejects slashes within a segment).  Collapses
    runs of whitespace to a single space, then strips leading /
    trailing whitespace.  Returns ``"_"`` for an entirely-unsafe
    segment, never an empty string, so the synthesised tree
    always has a writable name.
    """
    cleaned = _UNSAFE.sub("", segment)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "_"


# ---------------------------------------------------------------------------
# Trie construction
# ---------------------------------------------------------------------------


@dataclass
class _TrieNode:
    """Internal mutable trie used to compute the synthesised trees.

    ``items`` accumulates every ``GroupCandidate`` whose category
    *ends at this node*.  ``children`` maps the next segment (as
    the user wrote it -- preserving case) to the child node.

    Case-insensitive bucketing: when we build the trie, we look
    children up by the case-folded segment.  When we emit the
    synthesised tree, we use the case the user authored (taking
    the first one we encountered as canonical).
    """

    items: list[GroupCandidate] = field(default_factory=list)
    children: dict[str, "_TrieNode"] = field(default_factory=dict)
    """Map: case-folded segment -> child node."""

    canonical_name: dict[str, str] = field(default_factory=dict)
    """Map: case-folded segment -> the original-case form we
    emit when materialising tree nodes."""


def _build_trie(candidates: list[GroupCandidate]) -> _TrieNode:
    """Build a category trie from the input candidates.

    Items with empty category are NOT added to the trie -- they
    pass through unchanged.  The caller filters them.
    """
    root = _TrieNode()
    for c in candidates:
        if not c.category:
            continue
        node = root
        for seg in c.category.split("/"):
            key = seg.casefold()
            if key not in node.children:
                node.children[key] = _TrieNode()
                node.canonical_name[key] = seg
            node = node.children[key]
        node.items.append(c)
    return root


def _subtree_item_count(node: _TrieNode) -> int:
    """Total items in a subtree (this node's items + every descendant's)."""
    n = len(node.items)
    for child in node.children.values():
        n += _subtree_item_count(child)
    return n


def _collect_subtree(node: _TrieNode) -> list[GroupCandidate]:
    """Flat list of every ``GroupCandidate`` in this subtree."""
    out = list(node.items)
    for child in node.children.values():
        out.extend(_collect_subtree(child))
    return out


# ---------------------------------------------------------------------------
# Synthesis: trie -> .scriptreetree JSON shape
# ---------------------------------------------------------------------------


def _build_tree_def_dict(
    top_segment: str, top_node: _TrieNode, *, marker_version: str,
) -> dict[str, Any]:
    """Turn a top-level trie node into the dict that ``save_tree``
    would serialise.

    Output schema follows ``scriptree.core.io.tree_to_dict``:

      * ``name`` = the canonical top-segment string
      * ``nodes`` = recursive list of folder + leaf nodes
      * ``auto_discover.update_mode`` = ``"auto"`` so the file
        doesn't re-prompt every load
      * ``synthesised_by`` = a marker the user / next-pass logic
        can read to identify "this file is auto-generated, do
        not hand-edit"

    Leaf nodes carry ABSOLUTE paths to the source catalog -- the
    synthesised tree may live in a different directory from the
    leaves (it does: ``_groups/`` vs scattered install roots)
    and a relative path would break the lookup.
    """
    def _node_recurse(trie_node: _TrieNode) -> list[dict[str, Any]]:
        """Build the JSON ``nodes`` list for one level of the trie."""
        out: list[dict[str, Any]] = []
        # Leaves first -- items that END at this level (their
        # full category matched up to here exactly).  Sorted by
        # display name for stable output.
        for item in sorted(trie_node.items, key=lambda i: i.display_name.lower()):
            out.append({
                "type": "leaf",
                "name": item.display_name,
                "path": item.path,
            })
        # Then folders -- sorted by canonical name (case-insensitive
        # ordering, case-preserving render).
        for key in sorted(trie_node.children.keys()):
            child = trie_node.children[key]
            canonical = trie_node.canonical_name[key]
            out.append({
                "type": "folder",
                "name": canonical,
                "children": _node_recurse(child),
            })
        return out

    return {
        "schema_version": 3,
        "name": top_segment,
        "nodes": _node_recurse(top_node),
        # ``auto`` update_mode + a marker field together tell the
        # loader "this tree owns itself; don't ask the user about
        # changes on load."  See AutoDiscoverConfig.update_mode.
        "auto_discover": {"update_mode": "auto"},
        "synthesised_by": marker_version,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _pick_filename(
    top_segment: str,
    output_dir: Path,
    existing_tree_names: set[str],
) -> Path:
    """Choose the on-disk filename for a synthesised tree.

    Primary choice: ``<TopSegment>.scriptreetree``.  If the user
    has authored a tree with that stem in any scan root, we fall
    back to ``<TopSegment>__auto.scriptreetree`` so we never
    overwrite a hand-authored tree -- the user-authored version
    wins by name.

    Comparison is case-folded so ``MSOffice`` / ``msoffice`` are
    treated as the same name.
    """
    stem = _safe_stem(top_segment)
    folded = stem.casefold()
    candidate = output_dir / f"{stem}.scriptreetree"
    if folded in existing_tree_names:
        candidate = output_dir / f"{stem}__auto.scriptreetree"
    return candidate


def group_by_category(
    candidates: list[GroupCandidate],
    *,
    output_dir: Path,
    existing_tree_names: set[str] | None = None,
    marker_version: str = "scriptree-auto-organise",
    min_items_to_synthesise: int = 2,
) -> list[GroupOutcome]:
    """Run the full group pass.  See module docstring for the
    full algorithm.

    Side effect: writes synthesised ``.scriptreetree`` files into
    ``output_dir`` (creating the directory if needed).  Each
    write is one ``json.dump`` of the dict produced by
    ``_build_tree_def_dict``.

    Returns a list of ``GroupOutcome`` -- the caller iterates and
    pushes each ``outcome.path`` into the forest's discovery
    pipeline as a ForestItem.  Passthrough outcomes preserve
    their original path; synthesised outcomes point at the new
    file under ``output_dir``.
    """
    existing = existing_tree_names or set()
    existing = {s.casefold() for s in existing}

    # 1. Bucket: uncategorised items are passthrough; categorised
    #    feed the trie.
    passthroughs: list[GroupCandidate] = [
        c for c in candidates if not c.category
    ]
    categorised: list[GroupCandidate] = [
        c for c in candidates if c.category
    ]

    if not categorised:
        # Nothing to group.  Every item goes through unchanged.
        return [
            GroupOutcome(
                kind="passthrough", path=c.path,
                original_paths=[c.path],
            ) for c in passthroughs
        ]

    root = _build_trie(categorised)

    output_dir.mkdir(parents=True, exist_ok=True)

    outcomes: list[GroupOutcome] = []

    # Walk the TOP level of the trie.  Each top-level segment is
    # the unit at which we decide "synthesise or pass through".
    for key in sorted(root.children.keys()):
        top_node = root.children[key]
        canonical = root.canonical_name[key]
        subtree = _collect_subtree(top_node)
        if len(subtree) < min_items_to_synthesise:
            # Solo top-level category -- pass each item through
            # as a flat ForestItem.  (Usually just one item; could
            # be more if min_items_to_synthesise is raised.)
            for item in subtree:
                outcomes.append(GroupOutcome(
                    kind="passthrough",
                    path=item.path,
                    original_paths=[item.path],
                ))
            continue

        # Synthesise.
        tree_dict = _build_tree_def_dict(
            canonical, top_node, marker_version=marker_version,
        )
        out_path = _pick_filename(canonical, output_dir, existing)
        out_path.write_text(
            json.dumps(tree_dict, indent=2), encoding="utf-8",
        )
        outcomes.append(GroupOutcome(
            kind="synthesised",
            path=str(out_path),
            original_paths=[c.path for c in subtree],
        ))

    # Uncategorised items always tail the list as passthroughs.
    for item in passthroughs:
        outcomes.append(GroupOutcome(
            kind="passthrough",
            path=item.path,
            original_paths=[item.path],
        ))

    return outcomes


# ---------------------------------------------------------------------------
# Cleanup of stale synthesised trees
# ---------------------------------------------------------------------------


def prune_orphan_synthesised(
    output_dir: Path,
    *,
    keep_paths: set[Path],
    marker_version_prefix: str = "scriptree-auto-organise",
) -> list[Path]:
    """Delete synthesised trees that aren't in ``keep_paths``.

    Called by the forest controller after a successful group pass:
    every synthesised tree it just wrote goes into ``keep_paths``;
    any pre-existing synthesised tree in ``output_dir`` that
    isn't in the set is now an orphan (the category disappeared
    or got renamed) and we delete it so the forest doesn't keep
    showing a stale cell.

    Safety: we delete a file only when it is EITHER (a) marked as
    auto-organised (``synthesised_by`` starting with
    ``marker_version_prefix``) OR (b) the v0.8.0a104 self-heal case —
    a marker-ABSENT file that references a SIBLING group in this same
    ``output_dir`` (the circular-reference residue a pre-a100
    push-back left, which also stripped the marker).  A user-authored
    ``.scriptreetree`` that the user dropped into ``output_dir`` —
    even one that legitimately references an EXTERNAL or NESTED
    sub-tree — is NOT touched (a sub-tree leaf is a perfectly valid
    node type; only a same-dir sibling-group ref is corruption).

    Returns the list of paths actually deleted, for logging.
    """
    deleted: list[Path] = []
    if not output_dir.is_dir():
        return deleted
    keep_resolved = {p.resolve() for p in keep_paths}
    for f in output_dir.glob("*.scriptreetree"):
        try:
            if f.resolve() in keep_resolved:
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Unreadable or malformed; leave alone -- safer than
            # deleting something we can't introspect.
            continue
        marker = data.get("synthesised_by", "")
        if not isinstance(marker, str):
            marker = ""
        is_synth_marker = marker.startswith(marker_version_prefix)
        # v0.8.0a104 — SELF-HEAL the circular-reference RESIDUE even when the
        # ``synthesised_by`` marker is absent.  The residue signature: a
        # ``_groups`` file that points at a SIBLING group in this same dir
        # (Demo ⊃ ``./MSOffice.scriptreetree`` and vice-versa) — written by a
        # pre-a100 push-back that ALSO stripped the marker, so the marker check
        # alone could never reclaim it (it stayed on disk, re-shown every
        # startup).  Reclaiming it lets the next pass regenerate the group
        # cleanly from tool categories.
        #
        # IMPORTANT: only a SAME-DIR SIBLING-group reference is corruption.  A
        # leaf pointing at an EXTERNAL or NESTED ``.scriptreetree`` sub-tree is a
        # LEGITIMATE node type — a hand-authored hub can carry one, and so can a
        # synthesised group built from *categorised sub-trees*.  Those must NOT
        # be deleted, so we resolve the leaf and require it to be a direct
        # neighbour inside ``output_dir`` before treating the file as residue.
        residue = _refs_sibling_group_tree(data.get("nodes", []), output_dir)
        if not (is_synth_marker or residue):
            # Marker-less AND not sibling-group residue → treat as a genuine
            # user file (incl. one legitimately referencing a sub-tree); leave it.
            continue
        try:
            f.unlink()
            deleted.append(f)
        except OSError:
            # Locked / permission issue -- log via the caller, we
            # don't have a logger here.
            pass
    return deleted


def _refs_sibling_group_tree(nodes: object, groups_dir: Path) -> bool:
    """True iff any node (recursively) is a leaf referencing a SIBLING synth
    group — a ``.scriptreetree`` leaf whose path resolves to a DIRECT neighbour
    inside ``groups_dir`` itself (e.g. ``./MSOffice.scriptreetree`` sitting next
    to ``Demo.scriptreetree``).

    That same-dir cross-ref is the circular-reference residue a pre-a100
    push-back wrote.  A leaf pointing at an EXTERNAL or NESTED ``.scriptreetree``
    sub-tree is a documented, legitimate node type and is NOT flagged — so a
    user-authored hub or a synth group built from categorised sub-trees is left
    intact.  Operates on raw JSON dict nodes; leaf paths are resolved relative to
    ``groups_dir`` (the directory the file lives in)."""
    try:
        base = groups_dir.resolve()
    except (OSError, ValueError):
        base = groups_dir

    def _walk(ns: object) -> bool:
        if not isinstance(ns, list):
            return False
        for n in ns:
            if not isinstance(n, dict):
                continue
            if n.get("type") == "folder":
                if _walk(n.get("children", [])):
                    return True
                continue
            p = n.get("path")
            if not (isinstance(p, str) and p.lower().endswith(".scriptreetree")):
                continue
            try:
                pp = Path(p)
                target = pp if pp.is_absolute() else (base / pp)
                if target.resolve().parent == base:
                    return True
            except (OSError, ValueError):
                continue
        return False

    return _walk(nodes)
