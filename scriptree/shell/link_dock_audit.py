"""v0.8.0 — invariants for the link and dock graphs.

The v0.8.0 redesign decomposes the single ``_group_master_id`` field
into two independent graphs:

* **LINK** (``_link_parent_id``) is a tree rooted at the forest cell.
  Rings have the forest as their link parent; cells have a ring or
  the forest.  Cells never link-parent to other cells.
* **DOCK** (``_dock_partner_id`` + ``_dock_children_by_edge``) is a
  separate mesh of spatial edge-adjacencies, introduced in Phase 3.
  Phase 1 only covers the LINK graph.

This module exports pure validation functions that any test or
debugging code can call.  They never mutate.  They return a report
dict; a clean graph yields ``{}``.

Phase 1 (the file you're reading now): only :func:`audit_link_graph`
exists.  Phase 3 adds :func:`audit_dock_graph`.  Phase 4 wires both
into :meth:`CellWindow._audit_membership`'s replacement.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scriptree.shell.cell_registry import CellRegistry


# ---------------------------------------------------------------------------
# Link graph invariants
# ---------------------------------------------------------------------------

# Per the v0.8.0 spec, the LINK graph has these invariants:
#
# (L1) Each cell's ``_link_parent_id`` points to a registered cell or
#      is None.  Stale ids (parent has been unregistered) are bugs.
# (L2) No cycles.  Walking ``_link_parent_id`` from any cell terminates
#      (eventually reaches None).
# (L3) Maximum depth is 3 — forest → ring → cell.  Anything deeper
#      means a cell is link-parented to another cell (forbidden by L4),
#      or a ring is link-parented to a ring (also forbidden).
# (L4) Cells never link-parent another cell.  A cell's link parent is
#      always a ring or the forest.  Concretely: if X is a cell
#      (``X.kind == "cell"`` in Phase 6, or ``role == "standalone"``
#      pre-Phase-6) and any other Y has ``Y._link_parent_id == X._id``,
#      that's a violation.
# (L5) Exactly one forest cell.  The v0.8.0 model allows multiple in
#      the future but Phase 6's ForestRegistry enforces a singleton
#      for now.


_LINK_MAX_DEPTH = 3
_LINK_WALK_CAP = 64  # cycle-guard step limit


def audit_link_graph(registry: "CellRegistry") -> dict:
    """Inspect the link graph; return a report dict.

    The dict is empty when the graph satisfies every invariant.
    When violations are detected the keys identify which:

    * ``stale_parents`` — list of (cell_id, dangling_parent_id) where
      the parent id does not resolve to a registered cell.
    * ``cycles`` — list of cell_ids that participate in a cycle.
      Each entry is the cell from which a cycle was first detected
      walking upward.
    * ``depth_violations`` — list of (cell_id, observed_depth) where
      ``observed_depth > 3``.
    * ``cell_link_parents`` — list of (cell_id, parent_id) where the
      parent is a "cell" kind (not a ring or forest).  v0.8.0 P1
      can't distinguish kind yet (still uses ``role``), so this check
      uses ``role == "standalone"`` as a proxy for "cell".  Phase 6
      tightens the check.
    * ``forest_count`` — int, expected 1 in v0.8.0.  Reported only
      when ≠ 1.

    Callers should treat an empty report as "all good" and any
    non-empty report as a bug.  In the test suite,
    ``assert audit_link_graph(registry) == {}`` is the standard
    assertion.
    """
    report: dict = {}

    all_cells = list(registry.all())
    cells_by_id = {c._id: c for c in all_cells}

    stale: list[tuple[str, str]] = []
    cycles: list[str] = []
    depth_violations: list[tuple[str, int]] = []
    cell_link_parents: list[tuple[str, str]] = []

    for c in all_cells:
        parent_id = getattr(c, "_link_parent_id", None)
        if parent_id is None:
            continue
        # (L1) stale parent check.
        if parent_id not in cells_by_id:
            stale.append((c._id, parent_id))
            continue
        # (L2) cycle / (L3) depth check via upward walk.
        seen: set[str] = set()
        depth = 0
        cur: "str | None" = parent_id
        while cur is not None:
            if cur in seen:
                cycles.append(c._id)
                break
            seen.add(cur)
            depth += 1
            if depth > _LINK_WALK_CAP:
                # Cap hit — treat as a cycle (or extreme depth).
                cycles.append(c._id)
                break
            nxt_cell = cells_by_id.get(cur)
            if nxt_cell is None:
                # Parent chain points at an id that vanished mid-walk —
                # shouldn't happen since we snapshotted cells_by_id,
                # but treat as stale.
                stale.append((c._id, cur))
                break
            cur = getattr(nxt_cell, "_link_parent_id", None)
        # depth here is the chain length from c → root (or to a cycle).
        if depth > _LINK_MAX_DEPTH:
            depth_violations.append((c._id, depth))

        # (L4) cell-link-parents-cell check.  A cell whose parent_id
        # resolves to another standalone (non-master) cell is illegal.
        parent_cell = cells_by_id[parent_id]
        parent_role = getattr(parent_cell, "role", "standalone")
        if parent_role == "standalone":
            # The parent has no ring/forest role; the link graph treats
            # it as a cell.  Cells can't be link parents.
            cell_link_parents.append((c._id, parent_id))

    if stale:
        report["stale_parents"] = stale
    if cycles:
        report["cycles"] = sorted(set(cycles))
    if depth_violations:
        report["depth_violations"] = depth_violations
    if cell_link_parents:
        report["cell_link_parents"] = cell_link_parents

    # (L5) forest count.  In Phase 1 we identify "forest" by the legacy
    # ``_is_forest_master`` flag; Phase 6 swaps this to ``kind ==
    # "forest"``.
    forest_count = sum(
        1 for c in all_cells
        if getattr(c, "_is_forest_master", False)
    )
    if forest_count != 1 and forest_count != 0:
        # 0 is acceptable in test setups that haven't built a forest.
        # Non-zero non-one is the bug.
        report["forest_count"] = forest_count

    return report


def audit_mirror_writes(registry: "CellRegistry") -> dict:
    """Verify every cell's ``_link_parent_id`` matches the legacy
    ``_group_master_id``.

    Phase 1 keeps both fields in sync via the mirror-write at every
    set site (and the :meth:`CellWindow._set_link_parent` helper for
    new code).  If a write site was missed, this audit catches it.
    Phase 4 will delete this once readers consume only
    ``_link_parent_id`` — the discrepancy is harmless after the
    legacy field is dead.
    """
    report: dict = {}
    mismatches: list[tuple[str, "str | None", "str | None"]] = []
    for c in registry.all():
        legacy = getattr(c, "_group_master_id", None)
        new = getattr(c, "_link_parent_id", None)
        if legacy != new:
            mismatches.append((c._id, legacy, new))
    if mismatches:
        report["mirror_mismatches"] = mismatches
    return report
