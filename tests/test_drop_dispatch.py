"""Tests for the v0.3.6 drag-drop dispatch matrix on cells.

Per the user spec:

    "drag-and-dropping a scriptree or scriptreetree or scriptreering
     file on an existing cell or ring opens it. if it is a scriptree
     or scriptreetree dropped on a ring it gets linked and located
     attached to the group. if it is a ring, it just opens it. if
     it is dropped on an empty cell, it occupies that cell, or if
     it is a ring, replaces the cell. if the cell is already
     occupied it just opens - same behaviour as our current open
     command."

Final dispatch matrix:

============== ====================== =========================
Source state   .scriptree / .tree     .scriptreering
============== ====================== =========================
Empty cell     bind to self           close self + load ring
Bound cell     spawn sibling          load ring alongside
Master / ring  spawn member + JOIN    load ring alongside
============== ====================== =========================

These tests drive ``_handle_dropped_file`` directly so we don't
have to synthesise Qt drag events.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)


from scriptree.core.io import save_tool, save_tree
from scriptree.core.model import (
    ParamDef, ParamType, ToolDef, TreeDef, TreeNode, Widget,
)
from scriptree.shell.branding_loader import load_branding
from scriptree.shell.cell_registry import CellRegistry
from scriptree.shell.cell_window import CellWindow


def _fresh_registry() -> CellRegistry:
    reg = CellRegistry.instance()
    for h in list(reg.standalones()) + list(reg.masters()):
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass
    return reg


def _seed_tool(tmp_path: Path, name: str = "demo") -> Path:
    p = tmp_path / f"{name}.scriptree"
    save_tool(
        ToolDef(
            name=name, executable="python",
            params=[ParamDef(
                id="p", label="P",
                type=ParamType.PATH, widget=Widget.FILE,
            )],
        ),
        p,
    )
    return p


def _seed_tree(tmp_path: Path, name: str = "demo") -> Path:
    leaf = _seed_tool(tmp_path, "leaf")
    p = tmp_path / f"{name}.scriptreetree"
    save_tree(
        TreeDef(name=name, nodes=[TreeNode(type="leaf", path=str(leaf))]),
        p,
    )
    return p


def _seed_ring(tmp_path: Path) -> Path:
    """Minimal valid .scriptreering with a single standalone master."""
    doc = {
        "format": "scriptreering",
        "version": 1,
        "saved_at": "2026-05-08T00:00:00Z",
        "saved_by_brand": "test",
        "master": {
            "role": "standalone",
            "shape": "hexagon",
            "orientation": "flat-top",
            "size_px": 56,
            "transparency": 0.85,
            "always_on_top": True,
            "position": {"x": 400, "y": 400},
            "catalog_path": None,
        },
        "members": [],
    }
    p = tmp_path / "demo.scriptreering"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _empty_cell() -> CellWindow:
    return CellWindow(load_branding())


# ===========================================================================
# Empty-cell drops
# ===========================================================================

class TestDropOnEmptyCell:

    def test_drop_scriptree_binds_to_self(self, tmp_path: Path) -> None:
        _fresh_registry()
        cell = _empty_cell()
        tool = _seed_tool(tmp_path)
        assert cell._catalog_path is None
        cell._handle_dropped_file(str(tool))
        assert cell._catalog_path is not None
        assert Path(cell._catalog_path).resolve() == tool.resolve()
        cell.close()

    def test_drop_scriptreetree_binds_to_self(self, tmp_path: Path) -> None:
        _fresh_registry()
        cell = _empty_cell()
        tree = _seed_tree(tmp_path)
        cell._handle_dropped_file(str(tree))
        assert Path(cell._catalog_path).resolve() == tree.resolve()
        cell.close()

    def test_drop_ring_replaces_cell(self, tmp_path: Path) -> None:
        """Empty cell + drop ring → close cell, ring loads in its place."""
        _fresh_registry()
        cell = _empty_cell()
        cell.show()
        assert cell.isVisible()
        ring = _seed_ring(tmp_path)
        cell._handle_dropped_file(str(ring))
        assert not cell.isVisible()  # cell closed
        # The loaded ring's master cell appears in the registry.
        reg = CellRegistry.instance()
        assert (
            len(list(reg.standalones())) + len(list(reg.masters()))
            >= 1
        )


# ===========================================================================
# Bound standalone drops
# ===========================================================================

class TestDropOnBoundStandalone:

    def test_drop_scriptree_spawns_sibling(self, tmp_path: Path) -> None:
        """Already-bound cell + drop tool → spawn sibling, source untouched."""
        _fresh_registry()
        cell = _empty_cell()
        first = _seed_tool(tmp_path, "first")
        second = _seed_tool(tmp_path, "second")
        cell._catalog_path = str(first.resolve())
        original_path = cell._catalog_path

        with patch.object(cell, "_spawn_sibling_with_catalog") as m_sibling:
            cell._handle_dropped_file(str(second))
        m_sibling.assert_called_once()
        # The source cell's binding is unchanged.
        assert cell._catalog_path == original_path
        cell.close()

    def test_drop_ring_loads_alongside(self, tmp_path: Path) -> None:
        """Bound standalone + drop ring → keep self alive, load ring."""
        _fresh_registry()
        cell = _empty_cell()
        first = _seed_tool(tmp_path, "first")
        cell._catalog_path = str(first.resolve())
        cell.show()
        ring = _seed_ring(tmp_path)
        cell._handle_dropped_file(str(ring))
        # Cell still alive (NOT replaced), ring loaded in addition.
        assert cell.isVisible()
        cell.close()


# ===========================================================================
# Master / ring drops
# ===========================================================================

class TestDropOnMaster:

    def _make_master(self, tmp_path: Path) -> CellWindow:
        """Build a synthetic master cell with empty member list — we
        don't need real members for these tests, just the role."""
        master = CellWindow(load_branding(), role="master", hexagon_id="m-1")
        # Mark as already-saved so close-prompt doesn't fire.
        master._saved_ring_path = tmp_path / "fake.scriptreering"
        return master

    def test_drop_scriptree_spawns_member_and_links_to_group(
        self, tmp_path: Path,
    ) -> None:
        """Drop on master → new cell joins the ring's group."""
        _fresh_registry()
        master = self._make_master(tmp_path)
        master.show()
        before_member_count = len(master._members)
        tool = _seed_tool(tmp_path)
        master._handle_dropped_file(str(tool))
        # New member added to the master.
        assert len(master._members) == before_member_count + 1
        # The new cell has master's _id as its group_master_id.
        new_member_id = next(iter(master._members.keys()))
        reg = CellRegistry.instance()
        new_cell = reg.get(new_member_id)
        assert new_cell is not None
        assert new_cell._group_master_id == master._id
        # Master is dirty (membership changed).
        assert master._ring_dirty is True

    def test_drop_scriptreetree_spawns_member_and_links(
        self, tmp_path: Path,
    ) -> None:
        _fresh_registry()
        master = self._make_master(tmp_path)
        master.show()
        tree = _seed_tree(tmp_path)
        master._handle_dropped_file(str(tree))
        assert len(master._members) == 1
        new_id = next(iter(master._members.keys()))
        new_cell = CellRegistry.instance().get(new_id)
        assert new_cell._group_master_id == master._id

    def test_drop_ring_just_opens_alongside(
        self, tmp_path: Path,
    ) -> None:
        """Drop ring on master → load_ring spawns the new ring's
        master + members but does NOT auto-link to this master."""
        _fresh_registry()
        master = self._make_master(tmp_path)
        master.show()
        before_member_count = len(master._members)
        ring = _seed_ring(tmp_path)
        master._handle_dropped_file(str(ring))
        # Master's own member count unchanged — the new ring is a
        # separate group, not joined into ours.
        assert len(master._members) == before_member_count


# ===========================================================================
# Adopt-on-link: new member joins WITH master's geometry
# ===========================================================================

class TestDropOnMasterAdoptsGeometry:

    def test_new_member_adopts_master_size(self, tmp_path: Path) -> None:
        """When a tool is dropped on a master with custom size, the new
        member should adopt that size (group-uniform geometry rule)."""
        _fresh_registry()
        master = CellWindow(load_branding(), role="master", hexagon_id="m-1")
        master._saved_ring_path = tmp_path / "fake.scriptreering"
        master._apply_size_self(72)  # override the branding default
        master.show()
        tool = _seed_tool(tmp_path)
        master._handle_dropped_file(str(tool))
        new_id = next(iter(master._members.keys()))
        new_cell = CellRegistry.instance().get(new_id)
        assert new_cell._size_px == 72
