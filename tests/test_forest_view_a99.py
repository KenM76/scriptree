"""v0.8.0a99 — provenance-visible forest view.

The forest opens with its members rendered as linked SUBTREE refs (each naming
its source file on hover), not the old flattened merge.  Row tooltips name the
backing file / category so a real folder, a linked tree, and a synthesised
category group are distinguishable.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.io import load_tree, save_tool, save_tree  # noqa: E402
from scriptree.core.model import ToolDef, TreeDef, TreeNode  # noqa: E402
from scriptree.shell.merged_tree import build_forest_view  # noqa: E402
from scriptree.ui.tree_view import (  # noqa: E402
    TreeLauncherView,
    _is_leaf,
    _is_subtree,
)


def _tool(p: Path, name: str = "t") -> Path:
    save_tool(ToolDef(name=name, executable="python"), p)
    return p


def test_build_forest_view_keeps_members_as_leaves_not_folders(tmp_path: Path) -> None:
    leaf = _tool(tmp_path / "inner.scriptree", "inner")
    suite = tmp_path / "suite.scriptreetree"
    save_tree(TreeDef(name="Suite",
                      nodes=[TreeNode(type="leaf", path=str(leaf))]), suite)
    loose = _tool(tmp_path / "loose.scriptree", "loose")

    out = build_forest_view([str(suite), str(loose)], forest_name="F")
    view = load_tree(str(out))
    assert view.name == "F"
    # NOT flattened: each member is a top-level LEAF pointing at its own file
    # (not a folder with inlined children).
    assert len(view.nodes) == 2
    assert all(n.type == "leaf" for n in view.nodes)
    assert {Path(n.path).name for n in view.nodes} == {
        "suite.scriptreetree", "loose.scriptree",
    }


def test_tree_member_renders_as_subtree_with_file_tooltip(tmp_path: Path) -> None:
    leaf = _tool(tmp_path / "inner.scriptree", "inner")
    suite = tmp_path / "suite.scriptreetree"
    save_tree(TreeDef(name="Suite",
                      nodes=[TreeNode(type="leaf", path=str(leaf))]), suite)
    out = build_forest_view([str(suite)], forest_name="F")
    view = TreeLauncherView()
    view.load(str(out))
    member = view._tree_widget.topLevelItem(0).child(0)
    assert _is_subtree(member)                          # linked subtree
    assert "Linked tree" in member.toolTip(0)
    assert "suite.scriptreetree" in member.toolTip(0)   # names the file


def test_tool_member_renders_as_leaf_with_path_tooltip(tmp_path: Path) -> None:
    loose = _tool(tmp_path / "loose.scriptree", "loose")
    out = build_forest_view([str(loose)], forest_name="F")
    view = TreeLauncherView()
    view.load(str(out))
    member = view._tree_widget.topLevelItem(0).child(0)
    assert _is_leaf(member)
    assert "loose.scriptree" in member.toolTip(0)


def test_synthesised_group_member_gets_autogroup_tooltip(tmp_path: Path) -> None:
    groups = tmp_path / "_groups"
    groups.mkdir()
    msoffice = groups / "MSOffice.scriptreetree"
    save_tree(TreeDef(name="MSOffice", nodes=[]), msoffice)
    out = build_forest_view([str(msoffice)], forest_name="F")
    view = TreeLauncherView()
    view.load(str(out))
    tip = view._tree_widget.topLevelItem(0).child(0).toolTip(0)
    assert "Auto-group" in tip
    assert "MSOffice" in tip
    assert "Category" in tip


def test_in_memory_folder_tooltip(tmp_path: Path) -> None:
    leaf = _tool(tmp_path / "x.scriptree", "x")
    tp = tmp_path / "t.scriptreetree"
    save_tree(TreeDef(name="T", nodes=[TreeNode(
        type="folder", name="Group",
        children=[TreeNode(type="leaf", path=str(leaf))])]), tp)
    view = TreeLauncherView()
    view.load(str(tp))
    folder = view._tree_widget.topLevelItem(0).child(0)
    assert "Folder" in folder.toolTip(0)
    assert "no separate file" in folder.toolTip(0).lower()
