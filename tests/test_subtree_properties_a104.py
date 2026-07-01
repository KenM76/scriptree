"""v0.8.0a104 — "Tree properties…" on a LINKED SUBTREE row.

When the forest is opened as the editor root, a member tree (e.g. ffmpeg) is a
SUBTREE row, not the root — so the root-only "Tree properties…" action never
appeared on it, and the user could not set ffmpeg's Category from the forest
view.  a104 adds a per-subtree "Tree properties…" that edits the linked tree's
own name / category / path_prepend and writes them back to its file (preserving
its nodes + every other field), without first opening it as the root.  A
synthesised ``_groups/`` auto-group is exempt (regenerated from tool categories).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QMenu

_app = QApplication.instance() or QApplication([])

import scriptree.ui.tree_view as tv  # noqa: E402
from scriptree.core.io import load_tree, save_tool, save_tree  # noqa: E402
from scriptree.core.model import ToolDef, TreeDef, TreeNode  # noqa: E402
from scriptree.ui.tree_view import TreeLauncherView, _is_subtree  # noqa: E402


def _tool(p: Path, name: str) -> Path:
    save_tool(ToolDef(name=name, executable="python"), p)
    return p


def _find_subtree_row(view: TreeLauncherView):
    root = view._tree_widget.topLevelItem(0)
    for i in range(root.childCount()):
        c = root.child(i)
        if _is_subtree(c):
            return c
    raise AssertionError("no subtree row")


def _parent_with_member(tmp_path: Path, *, category: str = "") -> tuple[Path, Path]:
    sub = tmp_path / "sub"
    sub.mkdir()
    _tool(sub / "a.scriptree", "A")
    kit = sub / "kit.scriptreetree"
    save_tree(TreeDef(name="ffmpeg toolkit", category=category, nodes=[
        TreeNode(type="leaf", path="./a.scriptree", display_name="A"),
    ]), kit)
    parent = tmp_path / "parent.scriptreetree"
    save_tree(TreeDef(name="Parent", nodes=[
        TreeNode(type="leaf", path="./sub/kit.scriptreetree"),
    ]), parent)
    return parent, kit


class _FakeDialog:
    """Stand-in for _TreePropertiesDialog that 'accepts' with given values."""
    last_kwargs: dict = {}

    def __init__(self, **kw):
        _FakeDialog.last_kwargs = kw

    def exec(self):
        return tv.QDialog.DialogCode.Accepted

    def values(self):
        return {"name": "ffmpeg toolkit",
                "category": "Media/ffmpeg",
                "path_prepend": []}


def test_subtree_row_context_menu_has_tree_properties(tmp_path: Path) -> None:
    parent, _kit = _parent_with_member(tmp_path)
    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)
    menu = QMenu()
    view._populate_context_menu_for(menu, st)
    labels = [a.text() for a in menu.actions()]
    assert any("Tree properties" in (lbl or "") for lbl in labels), labels


def test_subtree_properties_writes_category_back(tmp_path: Path, monkeypatch) -> None:
    parent, kit = _parent_with_member(tmp_path, category="")
    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)

    monkeypatch.setattr(tv, "_TreePropertiesDialog", _FakeDialog)
    view._open_subtree_properties(st)

    reloaded = load_tree(str(kit))
    assert reloaded.category == "Media/ffmpeg"     # written back
    assert reloaded.name == "ffmpeg toolkit"
    # The tree's nodes (its tools) are preserved — only metadata changed.
    assert [n.path for n in reloaded.nodes if n.type == "leaf"] == ["./a.scriptree"]
    # The dialog was seeded from the loaded tree, not the root.
    assert _FakeDialog.last_kwargs.get("name") == "ffmpeg toolkit"


def test_subtree_properties_keeps_parent_display_name_override(
    tmp_path: Path, monkeypatch
) -> None:
    """a104 review #3: editing a member's Tree properties must NOT flip the row
    label from the PARENT leaf's display_name override to the linked tree's own
    name (the override is what a reload re-applies)."""
    sub = tmp_path / "sub"
    sub.mkdir()
    _tool(sub / "a.scriptree", "A")
    kit = sub / "kit.scriptreetree"
    save_tree(TreeDef(name="ffmpeg toolkit", category="", nodes=[
        TreeNode(type="leaf", path="./a.scriptree", display_name="A"),
    ]), kit)
    # Parent leaf carries a display_name OVERRIDE for the member.
    parent = tmp_path / "parent.scriptreetree"
    save_tree(TreeDef(name="Parent", nodes=[
        TreeNode(type="leaf", path="./sub/kit.scriptreetree",
                 display_name="My ffmpeg"),
    ]), parent)

    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)
    assert st.text(0) == "My ffmpeg"            # override is shown

    monkeypatch.setattr(tv, "_TreePropertiesDialog", _FakeDialog)
    view._open_subtree_properties(st)

    assert st.text(0) == "My ffmpeg", "override must survive the properties edit"
    # …and the linked tree's category was still written.
    assert load_tree(str(kit)).category == "Media/ffmpeg"


def test_synthesised_group_subtree_properties_not_written(tmp_path: Path, monkeypatch) -> None:
    """A ``_groups/`` member's properties are regenerated — editing them must be
    refused (info dialog), never written."""
    groups = tmp_path / "_groups"
    groups.mkdir()
    _tool(groups / "x.scriptree", "X")
    gtree = groups / "MSOffice.scriptreetree"
    save_tree(TreeDef(name="MSOffice", category="", nodes=[
        TreeNode(type="leaf", path="./x.scriptree", display_name="X"),
    ]), gtree)
    before = gtree.read_bytes()
    parent = tmp_path / "parent.scriptreetree"
    save_tree(TreeDef(name="Parent", nodes=[
        TreeNode(type="leaf", path="./_groups/MSOffice.scriptreetree"),
    ]), parent)

    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)

    seen = {"info": False}
    monkeypatch.setattr(tv.QMessageBox, "information",
                        staticmethod(lambda *a, **k: seen.update(info=True)))
    # If the dialog were reached it would mutate the file — make that loud.
    monkeypatch.setattr(tv, "_TreePropertiesDialog", _FakeDialog)
    view._open_subtree_properties(st)

    assert seen["info"] is True, "should warn that an auto-group is regenerated"
    assert gtree.read_bytes() == before, "auto-group properties must not be written"
