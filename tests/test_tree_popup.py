"""Tests for ``scriptree.shell.tree_popup`` — the in-process popup
menu shown on a cell's single-left-click."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMenu

_app = QApplication.instance() or QApplication([])

from scriptree.core.io import save_tool, save_tree
from scriptree.core.model import ParamDef, ToolDef, TreeDef, TreeNode
from scriptree.shell.tree_popup import (
    _add_node_to_menu,
    _build_menu_for_catalog,
)


def _save_tool(tmp: Path, name: str) -> Path:
    tool = ToolDef(
        name=name,
        executable="/bin/echo",
        argument_template=["{x}"],
        params=[ParamDef(id="x", label="X", default=name)],
    )
    p = tmp / f"{name}.scriptree"
    save_tool(tool, p)
    return p


def _save_tree(tmp: Path, name: str, leaves: list[Path]) -> Path:
    nodes = [
        TreeNode(type="leaf", name=p.stem, path=p.name)
        for p in leaves
    ]
    out = tmp / f"{name}.scriptreetree"
    save_tree(TreeDef(name=name, nodes=nodes), out)
    return out


# ---------------------------------------------------------------------------
# _build_menu_for_catalog
# ---------------------------------------------------------------------------

def test_build_menu_for_scriptreetree(tmp_path: Path) -> None:
    """Building a menu from a .scriptreetree should add one action per
    leaf, named after the leaf's display label."""
    t1 = _save_tool(tmp_path, "alpha")
    t2 = _save_tool(tmp_path, "beta")
    tree = _save_tree(tmp_path, "MyCat", [t1, t2])

    menu = QMenu(None)
    populated = _build_menu_for_catalog(menu, tree)
    assert populated is True
    actions = [a.text() for a in menu.actions()]
    assert "alpha" in actions
    assert "beta" in actions


def test_build_menu_for_scriptree(tmp_path: Path) -> None:
    """Single-tool catalog should produce one action labelled with the
    tool's name."""
    t1 = _save_tool(tmp_path, "alpha")

    menu = QMenu(None)
    populated = _build_menu_for_catalog(menu, t1)
    assert populated is True
    assert len(menu.actions()) == 1
    assert menu.actions()[0].text() == "alpha"


def test_build_menu_for_missing_file(tmp_path: Path) -> None:
    """Missing file should add a single disabled '(missing: ...)'
    placeholder and return False."""
    menu = QMenu(None)
    populated = _build_menu_for_catalog(menu, tmp_path / "nope.scriptree")
    assert populated is False
    assert len(menu.actions()) == 1
    assert "(missing:" in menu.actions()[0].text()
    assert not menu.actions()[0].isEnabled()


def test_build_menu_for_unsupported_extension(tmp_path: Path) -> None:
    bad = tmp_path / "garbage.txt"
    bad.write_text("not a catalog")
    menu = QMenu(None)
    populated = _build_menu_for_catalog(menu, bad)
    assert populated is False
    assert "(unsupported:" in menu.actions()[0].text()


def test_build_menu_for_empty_tree(tmp_path: Path) -> None:
    """Empty tree (no nodes) should add a disabled "(empty tree)"
    placeholder."""
    out = tmp_path / "empty.scriptreetree"
    save_tree(TreeDef(name="Empty", nodes=[]), out)
    menu = QMenu(None)
    populated = _build_menu_for_catalog(menu, out)
    assert populated is False
    assert menu.actions()[0].text() == "(empty tree)"
    assert not menu.actions()[0].isEnabled()


# ---------------------------------------------------------------------------
# _add_node_to_menu — recursive folder structure
# ---------------------------------------------------------------------------

def test_add_node_to_menu_folder_creates_submenu(tmp_path: Path) -> None:
    """A folder TreeNode should create a submenu, with leaves inside."""
    t1 = _save_tool(tmp_path, "alpha")
    folder = TreeNode(
        type="folder",
        name="Group",
        children=[TreeNode(type="leaf", name="alpha", path=t1.name)],
    )
    menu = QMenu(None)
    _add_node_to_menu(menu, folder, source_dir=tmp_path)
    # The folder action's menu() should hold the leaf.
    actions = menu.actions()
    assert len(actions) == 1
    # Submenu actions are added to a child QMenu accessible via .menu().
    submenu = actions[0].menu()
    assert submenu is not None
    assert any(a.text() == "alpha" for a in submenu.actions())


def test_add_node_to_menu_uses_display_name(tmp_path: Path) -> None:
    """display_name should win over name when set."""
    t1 = _save_tool(tmp_path, "alpha")
    leaf = TreeNode(
        type="leaf",
        name="alpha",
        display_name="Pretty Name",
        path=t1.name,
    )
    menu = QMenu(None)
    _add_node_to_menu(menu, leaf, source_dir=tmp_path)
    assert menu.actions()[0].text() == "Pretty Name"


# ---------------------------------------------------------------------------
# Action triggers → launch_tool
# ---------------------------------------------------------------------------

def test_leaf_action_triggers_launch_tool(tmp_path: Path) -> None:
    """Clicking a leaf in the popup should call ``launch_tool`` with
    the leaf's resolved absolute path."""
    t1 = _save_tool(tmp_path, "alpha")
    tree = _save_tree(tmp_path, "Cat", [t1])

    menu = QMenu(None)
    with patch("scriptree.shell.v1_launcher.launch_tool") as m_launch:
        _build_menu_for_catalog(menu, tree)
        # First action is the alpha leaf.
        leaf_action = menu.actions()[0]
        leaf_action.trigger()
    m_launch.assert_called_once()
    leaf_path = m_launch.call_args[1].get("leaf") \
        if "leaf" in m_launch.call_args[1] \
        else m_launch.call_args[0][0]
    assert Path(leaf_path).resolve() == t1.resolve()
