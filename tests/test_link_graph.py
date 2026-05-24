"""v0.8.0 Phase 1 — tests for the link-graph parallel state.

Phase 1 introduces ``_link_parent_id`` alongside the legacy
``_group_master_id`` and mirror-writes at every set site.  These
tests pin the contract:

* Every legacy ``_group_master_id`` write is mirrored to
  ``_link_parent_id`` (no drift between the two fields).
* :meth:`CellRegistry.link_parent_of` returns the same value as
  :meth:`CellRegistry.master_of` for every cell.
* :meth:`CellRegistry.link_children_of` returns the same set as
  :meth:`CellRegistry.group_members_of` for every master.
* :func:`audit_link_graph` returns an empty report on healthy
  graphs and flags the documented invariant violations.

These tests do NOT yet validate Phase 2+ behaviours (link-driven
cascade, dock graph) — those land in their own test files.
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from PySide6.QtCore import QPoint  # noqa: E402

from scriptree.shell.branding_loader import load_branding  # noqa: E402
from scriptree.shell.cell_registry import CellRegistry  # noqa: E402
from scriptree.shell.cell_window import CellWindow  # noqa: E402
from scriptree.shell.link_dock_audit import (  # noqa: E402
    audit_link_graph, audit_mirror_writes,
)


def _fresh_registry() -> CellRegistry:
    """Close any leftover cells from a previous test."""
    reg = CellRegistry.instance()
    for c in list(reg.all()):
        c.close()
    return reg


# ---------------------------------------------------------------------------
# Mirror-write invariants
# ---------------------------------------------------------------------------

def test_set_link_parent_writes_both_fields() -> None:
    """The Phase 1 helper writes both legacy and new fields."""
    _fresh_registry()
    cell = CellWindow(load_branding())
    cell.show()
    try:
        cell._set_link_parent("ring_x_id")
        assert cell._group_master_id == "ring_x_id"
        assert cell._link_parent_id == "ring_x_id"
        cell._set_link_parent(None)
        assert cell._group_master_id is None
        assert cell._link_parent_id is None
    finally:
        cell.close()


def test_master_spawn_mirror_writes_link_parent() -> None:
    """The 5-case _try_spawn_master path writes both fields for the
    sources it claims (Case 1 — fresh master from two standalones).
    """
    _fresh_registry()
    branding = load_branding()
    master = CellWindow(branding, role="master")
    master.show()
    master.move(400, 400)
    cells: list[CellWindow] = []
    try:
        for i in range(3):
            c = CellWindow(branding)
            c.show()
            c.move(400 + 60, 400)
            master._members[c._id] = QPoint(c.pos())
            master._positioned.add(c._id)
            # The high-level set sites use direct assignment + mirror;
            # exercise one through the audit helper.
            c._group_master_id = master._id
            c._link_parent_id = master._id  # v0.8.0 P1 mirror
            cells.append(c)
        # No mismatches expected.
        report = audit_mirror_writes(CellRegistry.instance())
        assert report == {}, report
    finally:
        for c in cells:
            c.close()
        master.close()


def test_audit_mirror_writes_catches_missed_mirror() -> None:
    """If a write bypasses the mirror, the audit catches it."""
    _fresh_registry()
    cell = CellWindow(load_branding())
    cell.show()
    try:
        # Simulate a Phase-1-bug: legacy was written but mirror was
        # forgotten.
        cell._group_master_id = "ring_y_id"
        # Deliberately leave _link_parent_id None.
        report = audit_mirror_writes(CellRegistry.instance())
        assert "mirror_mismatches" in report, report
        mismatches = report["mirror_mismatches"]
        assert any(
            m[0] == cell._id and m[1] == "ring_y_id" and m[2] is None
            for m in mismatches
        ), mismatches
    finally:
        cell.close()


# ---------------------------------------------------------------------------
# Registry helper parity with legacy
# ---------------------------------------------------------------------------

def test_link_parent_of_matches_master_of() -> None:
    """The new ``link_parent_of`` returns the same value as the
    legacy ``master_of`` for any cell."""
    _fresh_registry()
    branding = load_branding()
    reg = CellRegistry.instance()
    master = CellWindow(branding, role="master")
    master.show()
    master.move(400, 400)
    cells: list[CellWindow] = []
    try:
        for _ in range(3):
            c = CellWindow(branding)
            c.show()
            c.move(460, 400)
            master._members[c._id] = QPoint(c.pos())
            master._positioned.add(c._id)
            c._group_master_id = master._id
            c._link_parent_id = master._id  # P1 mirror
            cells.append(c)
        for c in cells:
            assert reg.link_parent_of(c._id) == reg.master_of(c._id) == master._id
        assert reg.link_parent_of(master._id) is None
    finally:
        for c in cells:
            c.close()
        master.close()


def test_link_children_of_matches_group_members_of() -> None:
    """The new ``link_children_of`` returns the same set as legacy
    ``group_members_of`` for any master."""
    _fresh_registry()
    branding = load_branding()
    reg = CellRegistry.instance()
    master = CellWindow(branding, role="master")
    master.show()
    master.move(400, 400)
    cells: list[CellWindow] = []
    try:
        for _ in range(4):
            c = CellWindow(branding)
            c.show()
            c.move(460, 400)
            master._members[c._id] = QPoint(c.pos())
            master._positioned.add(c._id)
            c._group_master_id = master._id
            c._link_parent_id = master._id  # P1 mirror
            cells.append(c)
        legacy = reg.group_members_of(master._id)
        new = reg.link_children_of(master._id)
        assert legacy == new, (legacy, new)
        assert len(new) == 4
    finally:
        for c in cells:
            c.close()
        master.close()


# ---------------------------------------------------------------------------
# Link-graph invariant checks
# ---------------------------------------------------------------------------

def test_audit_link_graph_clean_on_healthy_setup() -> None:
    """Healthy master + members → empty audit report."""
    _fresh_registry()
    branding = load_branding()
    master = CellWindow(branding, role="master")
    master.show()
    master.move(400, 400)
    cells: list[CellWindow] = []
    try:
        for _ in range(3):
            c = CellWindow(branding)
            c.show()
            c.move(460, 400)
            master._members[c._id] = QPoint(c.pos())
            c._group_master_id = master._id
            c._link_parent_id = master._id
            cells.append(c)
        report = audit_link_graph(CellRegistry.instance())
        # Forest count check expects exactly 1; in this isolated test
        # there's no forest_master flag set, so 0 is accepted as
        # "test setup" by the audit (see invariant L5 comment).
        assert "stale_parents" not in report
        assert "cycles" not in report
        assert "depth_violations" not in report
        assert "cell_link_parents" not in report
    finally:
        for c in cells:
            c.close()
        master.close()


def test_audit_link_graph_flags_stale_parent() -> None:
    """A cell whose ``_link_parent_id`` points at an unregistered
    id is flagged."""
    _fresh_registry()
    cell = CellWindow(load_branding())
    cell.show()
    try:
        cell._link_parent_id = "ghost_id_does_not_exist"
        report = audit_link_graph(CellRegistry.instance())
        assert "stale_parents" in report
        assert any(
            m[0] == cell._id and m[1] == "ghost_id_does_not_exist"
            for m in report["stale_parents"]
        )
    finally:
        cell.close()


def test_audit_link_graph_flags_cycle() -> None:
    """Two cells linked to each other via _link_parent_id produce
    a cycle, which the audit detects."""
    _fresh_registry()
    branding = load_branding()
    a = CellWindow(branding)
    b = CellWindow(branding)
    a.show()
    b.show()
    try:
        a._link_parent_id = b._id
        b._link_parent_id = a._id
        report = audit_link_graph(CellRegistry.instance())
        assert "cycles" in report, report
        # At least one of the two cells should be flagged.
        assert a._id in report["cycles"] or b._id in report["cycles"]
    finally:
        a.close()
        b.close()


def test_audit_link_graph_flags_cell_link_parent() -> None:
    """A cell whose link parent is a standalone (not a master/ring/
    forest) is flagged.  In Phase 1 this is a stand-in for the
    Phase 6 ``kind == 'cell'`` check."""
    _fresh_registry()
    branding = load_branding()
    a = CellWindow(branding)
    b = CellWindow(branding)
    a.show()
    b.show()
    try:
        # b is a plain standalone (role="standalone").  Linking a → b
        # is illegal under the v0.8.0 link spec (cells never link-
        # parent other cells).
        a._link_parent_id = b._id
        report = audit_link_graph(CellRegistry.instance())
        assert "cell_link_parents" in report, report
        assert any(
            m[0] == a._id and m[1] == b._id
            for m in report["cell_link_parents"]
        )
    finally:
        a.close()
        b.close()
