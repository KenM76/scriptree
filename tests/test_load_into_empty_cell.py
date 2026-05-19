"""Tests for the v0.2.11 "load into empty cell" behaviour and the
member-close-doesn't-tear-down-master fix.

Scope
-----

* When a user picks a ``.scriptree`` / ``.scriptreetree`` from the
  Load dialog or the recent-files menu **on an empty cell**, the
  catalog binds to *that* cell (no sibling spawn).
* When the same action runs on a **bound** cell, a sibling cell is
  spawned (matches the v0.2.8 behaviour for non-empty cells).
* When a ``.scriptreering`` is loaded on an empty cell, the empty
  cell is closed and the ring's master + members appear in its
  place.
* Closing a member of a 4-cell ring (master + 3 members) leaves the
  master + remaining 2 members alive.  Only when the member count
  drops below 2 does the master close.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.question = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Yes
)


from scriptree.core.io import save_tool, save_tree  # noqa: E402
from scriptree.core.model import ToolDef, TreeDef, TreeNode  # noqa: E402
from scriptree.shell.branding_loader import load_branding  # noqa: E402
from scriptree.shell.cell_registry import CellRegistry  # noqa: E402
from scriptree.shell.cell_window import CellWindow, _try_spawn_master  # noqa: E402


def _fresh_registry() -> CellRegistry:
    reg = CellRegistry.instance()
    for h in list(reg.standalones()) + list(reg.masters()):
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass
    return reg


def _spawn_empty() -> CellWindow:
    """Empty placeholder cell — no catalog bound, role=standalone."""
    branding = load_branding()
    return CellWindow(branding)


def _seed_tool(tmp_path: Path, name: str = "demo") -> Path:
    p = tmp_path / f"{name}.scriptree"
    save_tool(ToolDef(name=name, executable="python"), p)
    return p


def _seed_tree(tmp_path: Path, name: str = "demo") -> Path:
    p = tmp_path / f"{name}.scriptreetree"
    save_tree(TreeDef(name=name, nodes=[]), p)
    return p


# ---------------------------------------------------------------------------
# Empty vs bound — the _can_bind_self predicate
# ---------------------------------------------------------------------------

def test_empty_standalone_cell_can_bind_self() -> None:
    _fresh_registry()
    cell = _spawn_empty()
    assert cell._can_bind_self() is True
    cell.close()


def test_bound_standalone_cell_cannot_bind_self(tmp_path: Path) -> None:
    _fresh_registry()
    cell = _spawn_empty()
    cell._catalog_path = str(_seed_tool(tmp_path).resolve())
    assert cell._can_bind_self() is False
    cell.close()


def test_master_cell_cannot_bind_self() -> None:
    _fresh_registry()
    branding = load_branding()
    master = CellWindow(branding, role="master", hexagon_id="m-1")
    assert master._can_bind_self() is False
    master.close()


# ---------------------------------------------------------------------------
# Load .scriptree / .scriptreetree — bind-self vs spawn-sibling
# ---------------------------------------------------------------------------

def test_load_scriptree_into_empty_cell_binds_self(tmp_path: Path) -> None:
    _fresh_registry()
    tool_path = _seed_tool(tmp_path)

    cell = _spawn_empty()
    cell.show()
    assert cell._catalog_path is None

    with patch.object(cell, "_spawn_sibling_with_catalog") as m_sibling:
        cell._open_catalog_path(str(tool_path))

    # No sibling spawned; this cell now owns the catalog.
    m_sibling.assert_not_called()
    assert Path(cell._catalog_path).resolve() == tool_path.resolve()
    cell.close()


def test_load_scriptreetree_into_empty_cell_binds_self(tmp_path: Path) -> None:
    _fresh_registry()
    tree_path = _seed_tree(tmp_path)

    cell = _spawn_empty()
    cell.show()
    cell._open_catalog_path(str(tree_path))
    assert Path(cell._catalog_path).resolve() == tree_path.resolve()
    cell.close()


def test_load_scriptree_into_bound_cell_spawns_sibling(tmp_path: Path) -> None:
    _fresh_registry()
    first_tool = _seed_tool(tmp_path, "first")
    second_tool = _seed_tool(tmp_path, "second")

    cell = _spawn_empty()
    cell.show()
    cell._catalog_path = str(first_tool.resolve())
    original_path = cell._catalog_path

    with patch.object(cell, "_spawn_sibling_with_catalog") as m_sibling:
        cell._open_catalog_path(str(second_tool))

    # Bound cell still points at the first tool; sibling spawn was used.
    m_sibling.assert_called_once_with(str(second_tool))
    assert cell._catalog_path == original_path
    cell.close()


def test_open_recent_on_empty_cell_binds_self(tmp_path: Path) -> None:
    _fresh_registry()
    tool_path = _seed_tool(tmp_path)
    cell = _spawn_empty()
    cell.show()
    cell._open_recent_catalog(str(tool_path))
    assert Path(cell._catalog_path).resolve() == tool_path.resolve()
    cell.close()


# ---------------------------------------------------------------------------
# Load .scriptreering — empty cell gets replaced by ring
# ---------------------------------------------------------------------------

def _seed_ring(tmp_path: Path) -> Path:
    """A minimal but valid .scriptreering with one standalone master."""
    ring = {
        "format": "scriptreering",
        "version": 1,
        "saved_at": "2026-05-07T00:00:00Z",
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
    p.write_text(json.dumps(ring), encoding="utf-8")
    return p


def test_load_ring_on_empty_cell_closes_self_and_loads_ring(tmp_path: Path) -> None:
    _fresh_registry()
    ring_path = _seed_ring(tmp_path)

    cell = _spawn_empty()
    cell.show()
    assert cell.isVisible()

    cell._open_catalog_path(str(ring_path))

    # The empty placeholder closed; the ring's standalone cell took
    # its place on the desktop.
    assert not cell.isVisible()
    reg = CellRegistry.instance()
    # At least one cell from the loaded ring should now be in the registry.
    all_cells = list(reg.standalones()) + list(reg.masters())
    assert len(all_cells) >= 1


def test_load_ring_on_bound_cell_keeps_self_alive(tmp_path: Path) -> None:
    _fresh_registry()
    ring_path = _seed_ring(tmp_path)
    tool_path = _seed_tool(tmp_path)

    cell = _spawn_empty()
    cell.show()
    cell._catalog_path = str(tool_path.resolve())

    cell._open_catalog_path(str(ring_path))

    # Already-bound cell stays on screen — the ring loads alongside it.
    assert cell.isVisible()
    cell.close()


# ---------------------------------------------------------------------------
# Closing a member doesn't tear down the master while ≥ 2 members remain
# ---------------------------------------------------------------------------

def _build_three_member_group(branding: dict) -> tuple[CellWindow, list[CellWindow]]:
    """Master with 3 members.  All members connect via _try_spawn_master."""
    a = CellWindow(branding); a.show()
    b = CellWindow(branding); b.show()
    a.move(200, 200); b.move(200 + 56, 200)
    _try_spawn_master(a, b)
    reg = CellRegistry.instance()
    master_id = reg.master_of(a._id)
    assert master_id is not None
    master = reg.get(master_id)
    assert master is not None

    # Add a third member by docking with one of the existing two
    # (Case 2 path).  We bypass the snap engine and call
    # _try_spawn_master directly with c + an existing member.
    c = CellWindow(branding); c.show()
    c.move(b.pos().x() + 56, b.pos().y())
    _try_spawn_master(c, b)
    return master, [a, b, c]


def test_close_first_seed_member_keeps_master_with_other_members() -> None:
    """The bug: closing the cell that was ``source_a_id`` of the
    master tore the master down even though ≥2 other members remained.
    The fix: master only closes when its member count drops below 2."""
    _fresh_registry()
    branding = load_branding()
    master, members = _build_three_member_group(branding)
    a, b, c = members
    assert len(master._members) == 3

    # Close the very first cell (the original source_a_id).
    a._close_this()

    reg = CellRegistry.instance()
    # Master should still be alive with the remaining two members.
    assert reg.get(master._id) is master
    assert master.role == "master"
    assert len(master._members) == 2
    assert b._id in master._members
    assert c._id in master._members


def test_close_second_member_collapses_master_below_quorum() -> None:
    """Once the master is down to one member, it should close (the
    quorum rule that ``_check_master_validity`` already enforces).
    This regression test pins down the behaviour after the
    ``_close_this`` rewrite."""
    _fresh_registry()
    branding = load_branding()
    master, members = _build_three_member_group(branding)
    a, b, c = members

    a._close_this()
    b._close_this()

    reg = CellRegistry.instance()
    # Master should be hidden / despawned, c stands alone.
    assert not master.isVisible() or len(master._members) < 2
    assert c.role == "standalone"
    c.close()


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def teardown_function(_func) -> None:
    _fresh_registry()
