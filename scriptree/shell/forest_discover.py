"""
forest_discover.py — auto-discovery walker for ``.scriptreeforest``.

## For humans

Implements the priority-by-layer rule the user signed off on:

    For each subdirectory D, walking depth-first:
      if D contains *.scriptreering → emit those rings; STOP (don't
                                       descend into D)
      elif D contains *.scriptreetree → emit those trees; STOP
      elif D contains *.scriptree    → emit those tools; STOP
      else                            → recurse into D's subdirs

Stop-descending is what gives "only add the highest-layer thing per
folder" — a folder containing a ring file is treated as one self-
contained unit; we don't pull individual tools out of it.

The walker also enforces:
  * The ``include`` filter from ``AutoDiscoverConfig`` (only emit
    items whose ``kind`` is in the include list).  The priority
    rule still picks the highest-available kind per folder, but
    if that kind is filtered out we skip the folder entirely
    rather than fall through to a lower kind.  Otherwise the
    filter would silently demote a ring-folder to its individual
    tools, which the user wouldn't expect.
  * The ``excluded`` set — paths the user has explicitly removed.
    Skipped at the path level: a single excluded ``.scriptree`` in
    a folder of three doesn't stop the folder; the other two still
    emit.  An excluded ring DOES stop the folder, since the ring
    was the highest-priority match.
  * Hidden folders (basename starting with ``.``) — skipped.

Public API
----------
    discover(roots, include, excluded)        → list[DiscoveredItem]
    diff_against(current_items, discovered, excluded)
                                              → DiscoveryDiff

## For maintainers / LLMs

- ``_emit_for_dir`` takes ``excluded_norm`` but DOES NOT USE IT.
  Exclusion is intentionally handled downstream in ``diff_against``,
  not in the walker: the walker emits EVERY priority-tier match
  (excluded or not) and stops descending; ``diff_against`` then routes
  excluded paths into ``previously_excluded``.  This is the whole reason
  an excluded ring still "blocks" its folder's tool sibling.  Do not
  "optimise" by filtering excluded files inside the walker — it would
  silently demote a ring-folder to its tools, the exact footgun the
  design avoids.
- ``SUFFIX_PRIORITY`` ordering (ring > tree > tool) is owned by
  ``forest_io``.  Both this walker and ``kind_for_suffix`` depend on
  ``.scriptreering`` / ``.scriptreetree`` being tested before the
  shorter ``.scriptree`` (suffix-endswith matching).  Reordering that
  tuple silently mis-classifies every tree as a tool.
- Per-directory priority is "first non-empty tier wins, then STOP". A
  folder with both a ring and tools yields ONLY the ring and is not
  descended into.  ``stop=True`` is also returned when a tier matches
  but its kind is filtered out of ``include`` — that is deliberate
  (don't fall through to a lower kind).
- ``_walk`` is iterative (explicit stack) with ``max_depth=16`` as a
  symlink-loop guard. Note: an emitting directory still gets its
  subdirs skipped via ``continue`` after ``stop`` — but a NON-emitting
  dir pushes children with ``depth+1``; the depth check is ``> max_depth``
  so depth 16 is still processed, 17 is dropped.
- Hidden-dir skip is applied TWICE — once when popping (``d.name
  .startswith(".")``, but only ``if d != root`` so a dotted root still
  walks) and once when pushing children. Keep both; the pop-time check
  is what lets an explicitly-configured dotted root be scanned.
- ``_norm`` lower-cases AND ``resolve()``s; all set membership across
  this module and ``forest_controller`` goes through an identical
  ``_norm``.  These two copies must stay byte-for-byte equivalent or
  add/remove/exclude comparisons desync across the controller boundary.
  On Windows this case-folding is correct; on a case-sensitive FS it
  would conflate ``Foo`` and ``foo`` (accepted trade-off, Win11 target).
- ``diff_against`` "removed" rule: an item on the forest but absent
  from discovery is removed ONLY if it no longer exists on disk —
  user-added items outside the scan roots are kept. Changing this to
  "remove anything not rediscovered" would delete hand-added items.
- ``discover`` dedups across overlapping roots by normalised path,
  FIRST hit wins (and thus the kind from the first root that saw it).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from scriptree.shell.forest_io import (
    ForestItem, ItemKind, SUFFIX_PRIORITY, kind_for_suffix,
)


def _log(msg: str) -> None:
    print(f"[forest_discover] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DiscoveredItem:
    """A file the priority-rule walker decided should be on the forest."""

    path: str   # absolute path
    kind: ItemKind


@dataclass
class DiscoveryDiff:
    """Result of diffing a current forest against a fresh discovery
    pass.  Used by the update-prompt dialog to show the user what
    changed.

    ``added``    — files newly satisfying the priority rule.
    ``removed``  — files currently on the forest but no longer on
                   disk (or no longer satisfying the priority rule
                   because a higher-layer file was added next to
                   them).
    ``previously_excluded`` — files the user previously removed but
                   that now satisfy the priority rule.  Surfaced
                   in the prompt with a checkbox so the user can
                   re-include if they want.
    """

    added: list[DiscoveredItem] = field(default_factory=list)
    removed: list[ForestItem] = field(default_factory=list)
    previously_excluded: list[DiscoveredItem] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.previously_excluded)


# ---------------------------------------------------------------------------
# Path normalisation — all comparisons go through here so the
# resolution / case-folding rules stay consistent across the module.
# ---------------------------------------------------------------------------

def _norm(path: str | Path) -> str:
    """Normalised form used for set-membership comparisons."""
    try:
        return str(Path(path).resolve()).lower().replace("\\", "/")
    except (OSError, ValueError, RuntimeError):
        return str(path).lower().replace("\\", "/")


# ---------------------------------------------------------------------------
# Walker
# ---------------------------------------------------------------------------

def _emit_for_dir(
    d: Path,
    include: set[ItemKind],
    excluded_norm: set[str],
) -> tuple[list[DiscoveredItem], bool]:
    """Decide what (if anything) to emit for directory ``d``.

    Returns ``(emitted_items, should_stop_descending)``.

    Priority + include + excluded interaction:
      * Walk SUFFIX_PRIORITY in order (highest layer first).
      * For each priority tier, glob ``d`` for matching files.
      * If any file (excluded or not) matches AND the kind is in
        ``include``, **emit ALL matches** (including excluded
        ones) and return ``stop=True``.  The caller's
        ``diff_against`` consults the excluded list to route
        each emitted item to ``added`` vs ``previously_excluded``;
        emitting them lets the prompt dialog offer re-inclusion.
      * If matches exist but the kind is filtered out, return
        ``stop=True`` with no emission — the user said "don't
        consider this kind", and falling through would silently
        demote.
      * Excluded files still ``stop`` the descent — an excluded
        ring blocks the same folder's tool sibling from being
        picked up, matching the v0.3.14 design ("if user excluded
        the ring, that folder is conceptually a ring-folder; we
        don't fall back to its tool").
      * If no priority tier matches, return ``stop=False`` so the
        caller recurses into subdirs.
    """
    try:
        entries = list(d.iterdir())
    except OSError:
        return [], False

    by_suffix: dict[str, list[Path]] = {s: [] for s, _ in SUFFIX_PRIORITY}
    for entry in entries:
        if not entry.is_file():
            continue
        for suffix, _ in SUFFIX_PRIORITY:
            if str(entry.name).lower().endswith(suffix):
                by_suffix[suffix].append(entry)
                break

    for suffix, kind in SUFFIX_PRIORITY:
        matches = by_suffix.get(suffix) or []
        if not matches:
            continue
        if kind not in include:
            return [], True
        # Emit every matching file — including excluded ones.
        # ``diff_against`` will re-route excluded items into the
        # ``previously_excluded`` bucket so the prompt dialog can
        # offer re-inclusion.
        emitted = [
            DiscoveredItem(path=str(m.resolve()), kind=kind)
            for m in matches
        ]
        return emitted, True

    return [], False


#: Directory basenames the walker never descends into.  ``_groups`` is the
#: synthesised-category-tree output dir — ``categorize.group_by_category``
#: writes ``default_personal_root()/_groups/<Top>.scriptreetree``, and that dir
#: sits UNDER the personal-apps scan root.  Without this skip the walker
#: re-ingests its OWN synthesised output as input, which (a) makes the next
#: group pass see an "existing" ``MSOffice`` tree and emit a duplicate
#: ``MSOffice__auto.scriptreetree`` (``_pick_filename`` collision avoidance),
#: and (b) can produce a circular reference when one synthesised tree is
#: discovered as a member of another.  v0.8.0a98 — the lasting fix for the
#: reorganize duplicate/circular bug.  (``_existing_tree_names`` in
#: ``forest_controller`` excludes ``_groups`` the same way.)
_SKIP_DIR_NAMES = frozenset({"_groups"})


def _is_skipped_dir(name: str) -> bool:
    """True for dirs the walker must not enter: dotfiles + the synthesised
    ``_groups`` output dir."""
    return name.startswith(".") or name in _SKIP_DIR_NAMES


def _walk(
    root: Path,
    include: set[ItemKind],
    excluded_norm: set[str],
    *,
    max_depth: int = 16,
) -> Iterable[DiscoveredItem]:
    """Depth-first traversal applying the priority rule at every dir.

    ``max_depth`` is a defensive cap against pathological symlink
    loops; ``ScripTreeApps`` trees are typically 2-4 deep.
    """
    if not root.is_dir():
        return

    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        d, depth = stack.pop()
        if depth > max_depth:
            continue
        # Skip hidden dirs (dotfiles) + the synthesised ``_groups`` output dir.
        if _is_skipped_dir(d.name) and d != root:
            continue

        emitted, stop = _emit_for_dir(d, include, excluded_norm)
        for item in emitted:
            yield item
        if stop:
            continue

        # No priority match — recurse into subdirectories.
        try:
            for sub in d.iterdir():
                if sub.is_dir() and not _is_skipped_dir(sub.name):
                    stack.append((sub, depth + 1))
        except OSError:
            continue


def discover(
    roots: list[str | Path],
    include: list[ItemKind] | None = None,
    excluded: list[str] | None = None,
) -> list[DiscoveredItem]:
    """Run the priority-rule walker against ``roots``.

    Each root is walked independently; results are merged.  If the
    same path matches under multiple roots (overlapping config —
    user error, but harmless), it's deduplicated by normalised
    path with the FIRST hit kept.

    ``include`` defaults to all three kinds.
    ``excluded`` defaults to empty.
    """
    if include is None:
        inc_set: set[ItemKind] = {"ring", "tree", "tool"}
    else:
        inc_set = set(include) or {"ring", "tree", "tool"}

    excluded_norm = {_norm(p) for p in (excluded or [])}

    seen: set[str] = set()
    out: list[DiscoveredItem] = []
    for r in roots:
        rp = Path(r)
        if not rp.is_absolute():
            # Resolve relative to the project root, same rule as io.
            from scriptree.shell.forest_io import _project_root
            rp = (_project_root() / rp).resolve()
        for item in _walk(rp, inc_set, excluded_norm):
            key = _norm(item.path)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

def diff_against(
    current_items: list[ForestItem],
    discovered: list[DiscoveredItem],
    excluded: list[str],
) -> DiscoveryDiff:
    """Compute what should change to make ``current_items`` match
    ``discovered``, respecting the user's ``excluded`` list.

    See ``DiscoveryDiff`` docstring for field meanings.
    """
    cur_keys = {_norm(i.path): i for i in current_items}
    disc_keys = {_norm(i.path): i for i in discovered}
    excl_keys = {_norm(p) for p in excluded}

    diff = DiscoveryDiff()

    # Added: in discovery, not currently on the forest, not excluded.
    for k, item in disc_keys.items():
        if k in cur_keys:
            continue
        if k in excl_keys:
            # Surface as previously-excluded so the user can opt in.
            diff.previously_excluded.append(item)
        else:
            diff.added.append(item)

    # Removed: on the forest, not in discovery (file deleted /
    # higher-layer file appeared next to it), AND on disk doesn't
    # exist.  We DO NOT remove items the user explicitly added
    # outside the auto-discover roots (those won't appear in
    # ``discovered`` but are still valid).  The disambiguator:
    # if the file still exists on disk, leave it alone.
    for k, item in cur_keys.items():
        if k in disc_keys:
            continue
        if Path(item.path).exists():
            continue  # user-added, outside discovery scope; keep it
        diff.removed.append(item)

    return diff
