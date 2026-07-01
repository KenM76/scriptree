"""v0.8.0a100 — edit-routing fixes for the two reported regressions.

(1) The forest-hub editor MUST take the provenance forest-view, not the
    flattened merged/push-back path (which writes circular ``_groups`` sibling
    refs).  (2) push-back must NEVER write a sibling-group ref into a synthesised
    ``_groups`` tree (defence for ring masters too).  (3) a linked-subtree row
    can be opened in the editor to edit it.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.io import save_tool, save_tree  # noqa: E402
from scriptree.core.model import ToolDef, TreeDef, TreeNode  # noqa: E402
from scriptree.shell import merged_tree as mt  # noqa: E402
from scriptree.shell import v1_launcher as vl  # noqa: E402
from scriptree.shell.merged_tree import (  # noqa: E402
    _refs_groups_tree,
    _strip_groups_tree_refs,
    build_forest_view,
)
from scriptree.ui.tree_view import TreeLauncherView  # noqa: E402


# --- (2) the push-back guard logic ----------------------------------------

def test_refs_groups_tree_only_flags_tree_leaves_under_groups() -> None:
    groups_dir = Path("C:/x/_groups")
    ring_dir = Path("C:/x/SomeRing")
    tree_leaf = TreeNode(type="leaf", path="./MSOffice.scriptreetree")
    tool_leaf = TreeNode(type="leaf", path="./foo.scriptree")
    # Writing INTO a _groups source: a .scriptreetree leaf is a bogus sibling.
    assert _refs_groups_tree(tree_leaf, groups_dir) is True
    assert _refs_groups_tree(tool_leaf, groups_dir) is False   # tool is fine
    # Writing into a NON-_groups source (ring): never flagged — legit subtrees.
    assert _refs_groups_tree(tree_leaf, ring_dir) is False


def test_strip_groups_tree_refs_recursive() -> None:
    groups_dir = Path("C:/x/_groups")
    folder = TreeNode(type="folder", name="Demo", children=[
        TreeNode(type="leaf", path="./a.scriptree"),
        TreeNode(type="leaf", path="./MSOffice.scriptreetree"),     # circular
        TreeNode(type="folder", name="sub", children=[
            TreeNode(type="leaf", path="./Demo.scriptreetree"),     # nested circular
            TreeNode(type="leaf", path="./b.scriptree"),
        ]),
    ])
    _strip_groups_tree_refs(folder, groups_dir)
    top = [c.path for c in folder.children if c.type == "leaf"]
    assert top == ["./a.scriptree"]                 # MSOffice ref stripped
    sub = next(c for c in folder.children if c.type == "folder")
    assert [c.path for c in sub.children] == ["./b.scriptree"]  # nested stripped


# --- (1) forest hub uses the provenance view, not the merged push-back path -

def test_show_composite_for_forest_uses_forest_view(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(mt, "build_forest_view_for_master",
                        lambda m: (calls.append("forest"), "fv.scriptreetree")[1])
    monkeypatch.setattr(mt, "build_merged_tree_for_master",
                        lambda m: (calls.append("merged"), "mg.scriptreetree")[1])
    monkeypatch.setattr(vl, "launch_editor_with_tree",
                        lambda p: calls.append(f"launch:{p}"))

    class _ForestHub:
        role = "master"
        _is_forest_master = True

    vl.show_composite_for(_ForestHub())
    assert "forest" in calls and "merged" not in calls

    calls.clear()

    class _RingMaster:
        role = "master"
        _is_forest_master = False

    vl.show_composite_for(_RingMaster())
    assert "merged" in calls and "forest" not in calls   # ring unchanged


# --- (3) subtree "Open in editor" emits the new signal --------------------

def test_subtree_open_in_editor_emits_openTreeRequested(tmp_path: Path) -> None:
    leaf = tmp_path / "inner.scriptree"
    save_tool(ToolDef(name="inner", executable="python"), leaf)
    suite = tmp_path / "suite.scriptreetree"
    save_tree(TreeDef(name="Suite",
                      nodes=[TreeNode(type="leaf", path=str(leaf))]), suite)
    view_path = build_forest_view([str(suite)], forest_name="F")
    view = TreeLauncherView()
    view.load(str(view_path))
    member = view._tree_widget.topLevelItem(0).child(0)  # the suite subtree

    got: list[str] = []
    view.openTreeRequested.connect(got.append)
    view._emit_open_tree_for(member)
    assert len(got) == 1
    assert got[0].endswith("suite.scriptreetree")
