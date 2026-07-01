"""v0.8.0a102 — drag-to-recategorize.

Editing & saving a synthesised auto-group (`_groups/<Top>.scriptreetree`)
re-files each member by its folder position into the member's own `category`
(the source of truth), instead of writing the regenerated group file.  A tool
dragged into the group's "Excel" folder gets `category: "<Top>/Excel"`.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.io import save_tool, save_tree  # noqa: E402
from scriptree.core.model import ToolDef, TreeDef, TreeNode  # noqa: E402
from scriptree.ui import tree_view as tv  # noqa: E402
from scriptree.ui.tree_view import TreeLauncherView, _ROLE_PATH  # noqa: E402


def _tool(p: Path, name: str, category: str) -> Path:
    save_tool(ToolDef(name=name, executable="python", category=category), p)
    return p


def test_is_synthesised_group(tmp_path: Path) -> None:
    groups = tmp_path / "_groups"
    groups.mkdir()
    g = groups / "MSOffice.scriptreetree"
    save_tree(TreeDef(name="MSOffice", nodes=[]), g)
    view = TreeLauncherView()
    view.load(str(g))
    assert view._is_synthesised_group() is True

    # a normal tree elsewhere is NOT a synthesised group
    other = tmp_path / "apps" / "suite.scriptreetree"
    other.parent.mkdir(parents=True)
    save_tree(TreeDef(name="Suite", nodes=[]), other)
    view.load(str(other))
    assert view._is_synthesised_group() is False


def test_save_synthesised_group_refiles_by_layout(tmp_path: Path, monkeypatch) -> None:
    # A tool currently tagged MSOffice/Word, but the group layout places it
    # under an "Excel" folder + a second tool placed at the group root.
    apps = tmp_path / "apps"
    apps.mkdir()
    moved = _tool(apps / "moved.scriptree", "moved", "MSOffice/Word")
    rootlvl = _tool(apps / "rootlvl.scriptree", "rootlvl", "MSOffice/Word")
    same = _tool(apps / "same.scriptree", "same", "MSOffice/Excel")

    groups = tmp_path / "_groups"
    groups.mkdir()
    group = groups / "MSOffice.scriptreetree"
    save_tree(TreeDef(name="MSOffice", nodes=[
        TreeNode(type="folder", name="Excel", children=[
            TreeNode(type="leaf", path=str(moved)),
            TreeNode(type="leaf", path=str(same)),
        ]),
        TreeNode(type="leaf", path=str(rootlvl)),  # directly under the group
    ]), group)

    view = TreeLauncherView()
    view.load(str(group))
    monkeypatch.setattr(tv.QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))

    assert view._save_tree() is True

    # moved: Word → Excel (it sits under the Excel folder now)
    assert json.loads(moved.read_text(encoding="utf-8"))["category"] == "MSOffice/Excel"
    # rootlvl: now directly under the group → just "MSOffice"
    assert json.loads(rootlvl.read_text(encoding="utf-8"))["category"] == "MSOffice"
    # same: already MSOffice/Excel and still under Excel → unchanged
    assert json.loads(same.read_text(encoding="utf-8"))["category"] == "MSOffice/Excel"


def test_recategorize_returns_only_changed(tmp_path: Path) -> None:
    apps = tmp_path / "apps"
    apps.mkdir()
    a = _tool(apps / "a.scriptree", "a", "MSOffice/Word")   # will change
    b = _tool(apps / "b.scriptree", "b", "MSOffice/Excel")  # unchanged
    groups = tmp_path / "_groups"
    groups.mkdir()
    group = groups / "MSOffice.scriptreetree"
    save_tree(TreeDef(name="MSOffice", nodes=[
        TreeNode(type="folder", name="Excel", children=[
            TreeNode(type="leaf", path=str(a)),
            TreeNode(type="leaf", path=str(b)),
        ]),
    ]), group)
    view = TreeLauncherView()
    view.load(str(group))
    changes = view._recategorize_tools_from_layout()
    paths = {Path(c[0]).name for c in changes}
    assert paths == {"a.scriptree"}          # only the one that changed
    assert changes[0][1:] == ("MSOffice/Word", "MSOffice/Excel")


# --- a102 review fixes ----------------------------------------------------

def test_removed_member_category_cleared(tmp_path: Path) -> None:
    """A member dropped from the group layout must LEAVE the group — its
    category is cleared so it doesn't reappear on the next Re-organise."""
    apps = tmp_path / "apps"
    apps.mkdir()
    a = _tool(apps / "a.scriptree", "a", "MSOffice")
    b = _tool(apps / "b.scriptree", "b", "MSOffice")
    groups = tmp_path / "_groups"
    groups.mkdir()
    group = groups / "MSOffice.scriptreetree"
    save_tree(TreeDef(name="MSOffice", nodes=[
        TreeNode(type="leaf", path=str(a)),
        TreeNode(type="leaf", path=str(b)),
    ]), group)
    view = TreeLauncherView()
    view.load(str(group))
    # Remove b's row from the layout (simulate Remove / drag-out).
    root = view._tree_widget.topLevelItem(0)
    for i in range(root.childCount()):
        c = root.child(i)
        p = c.data(0, _ROLE_PATH)
        if p and Path(p).name == "b.scriptree":
            root.removeChild(c)
            break
    view._recategorize_tools_from_layout()
    assert json.loads(b.read_text(encoding="utf-8"))["category"] == ""   # left the group
    assert json.loads(a.read_text(encoding="utf-8"))["category"] == "MSOffice"


def test_unnormalised_category_not_churned(tmp_path: Path) -> None:
    """A tool stored with a trailing-slash category is in the SAME position —
    don't rewrite it or count it."""
    apps = tmp_path / "apps"
    apps.mkdir()
    t = apps / "t.scriptree"
    t.write_text(json.dumps({
        "schema_version": 3, "name": "t", "executable": "python",
        "category": "MSOffice/Word/",  # un-normalised, same position as Word
    }), encoding="utf-8")
    before = t.read_text(encoding="utf-8")
    groups = tmp_path / "_groups"
    groups.mkdir()
    group = groups / "MSOffice.scriptreetree"
    save_tree(TreeDef(name="MSOffice", nodes=[
        TreeNode(type="folder", name="Word",
                 children=[TreeNode(type="leaf", path=str(t))])]), group)
    view = TreeLauncherView()
    view.load(str(group))
    changes = view._recategorize_tools_from_layout()
    assert not any(Path(c[0]).name == "t.scriptree" for c in changes)
    assert t.read_text(encoding="utf-8") == before  # untouched


def test_folder_name_with_slash_sanitised(tmp_path: Path) -> None:
    """A folder inline-renamed to contain '/' must not inject extra category
    segments — the slash is scrubbed."""
    apps = tmp_path / "apps"
    apps.mkdir()
    t = _tool(apps / "t.scriptree", "t", "MSOffice/Old")
    groups = tmp_path / "_groups"
    groups.mkdir()
    group = groups / "MSOffice.scriptreetree"
    save_tree(TreeDef(name="MSOffice", nodes=[
        TreeNode(type="folder", name="Sub",
                 children=[TreeNode(type="leaf", path=str(t))])]), group)
    view = TreeLauncherView()
    view.load(str(group))
    folder = view._tree_widget.topLevelItem(0).child(0)
    folder.setText(0, "A/B")  # user renames with an embedded slash
    view._recategorize_tools_from_layout()
    assert json.loads(t.read_text(encoding="utf-8"))["category"] == "MSOffice/A B"
