"""Tests for v0.8.0a89 Ignore-this-copy + the tree restore dialog.

``ForestController.ignore_copy(path)`` is the dual-source action: hide THIS
physical copy of a tool/app (and, for a tree/folder, everything under its
folder) by adding it to ``forest.excluded`` and dropping its item — path-keyed,
so a copy at another location is untouched.  ``forget_excluded`` drops paths
from the list without re-adding.  ``ExcludedItemsDialog`` reconstructs a
directory tree from the excluded paths so the user can restore one item or one
item + its children.

The controller logic tests build a real ``ForestController`` but set
``forest`` directly and stub ``_despawn_item`` so no real cell windows are
needed.  The dialog test uses a lightweight fake controller.
"""
from __future__ import annotations

import types
from pathlib import Path

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.shell.branding_loader import load_branding  # noqa: E402
from scriptree.shell.cell_registry import CellRegistry  # noqa: E402
from scriptree.shell.forest_controller import ForestController  # noqa: E402
from scriptree.shell.forest_dialogs import ExcludedItemsDialog  # noqa: E402
from scriptree.shell.forest_io import ForestDef, ForestItem  # noqa: E402


def _ctrl(items, excluded=None):
    ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
    ctrl.forest = ForestDef(items=list(items), excluded=list(excluded or []))
    ctrl._despawn_item = lambda _it: None  # no real cells in unit tests
    return ctrl


def _norm_set(paths):
    from scriptree.shell.forest_controller import _norm
    return {_norm(p) for p in paths}


# --- ignore_copy ---------------------------------------------------------

def test_ignore_single_tool_excludes_only_it(tmp_path) -> None:
    a = str(tmp_path / "MSOffice" / "Word" / "a.scriptree")
    b = str(tmp_path / "MSOffice" / "Excel" / "b.scriptree")
    ctrl = _ctrl([ForestItem(path=a, kind="tool"),
                  ForestItem(path=b, kind="tool")])
    newly = ctrl.ignore_copy(a)
    assert _norm_set(newly) == _norm_set([a])
    assert _norm_set(it.path for it in ctrl.forest.items) == _norm_set([b])
    assert _norm_set(ctrl.forest.excluded) == _norm_set([a])


def test_ignore_tree_takes_children_under_its_folder(tmp_path) -> None:
    app = tmp_path / "SolidWorks"
    toolkit = str(app / "SolidWorks_toolkit.scriptreetree")
    child = str(app / "Drawings" / "RemoveDrawingPages" / "x.scriptree")
    other = str(tmp_path / "MSOffice" / "y.scriptree")
    ctrl = _ctrl([
        ForestItem(path=toolkit, kind="tree"),
        ForestItem(path=child, kind="tool"),
        ForestItem(path=other, kind="tool"),
    ])
    ctrl.ignore_copy(toolkit)
    # toolkit + the child under its folder are dropped + excluded; other stays
    assert _norm_set(it.path for it in ctrl.forest.items) == _norm_set([other])
    assert _norm_set(ctrl.forest.excluded) == _norm_set([toolkit, child])


def test_ignore_is_path_keyed_other_copy_untouched(tmp_path) -> None:
    local = str(tmp_path / "local" / "SolidWorks" / "kit.scriptreetree")
    server = str(tmp_path / "server" / "SolidWorks" / "kit.scriptreetree")
    ctrl = _ctrl([ForestItem(path=local, kind="tree"),
                  ForestItem(path=server, kind="tree")])
    ctrl.ignore_copy(local)
    # same filename, different folder -> only the local copy goes
    assert _norm_set(it.path for it in ctrl.forest.items) == _norm_set([server])
    assert _norm_set(ctrl.forest.excluded) == _norm_set([local])


def test_ignore_is_idempotent(tmp_path) -> None:
    a = str(tmp_path / "x" / "a.scriptree")
    ctrl = _ctrl([ForestItem(path=a, kind="tool")])
    ctrl.ignore_copy(a)
    ctrl.ignore_copy(a)  # second time: no item, no duplicate exclude
    assert ctrl.forest.excluded.count(a) == 1


def test_forget_excluded_drops_without_readding(tmp_path) -> None:
    a, b, c = (str(tmp_path / x) for x in ("a.scriptree", "b.scriptree", "c.scriptree"))
    ctrl = _ctrl([], excluded=[a, b, c])
    ctrl.forget_excluded([a, b])
    assert _norm_set(ctrl.forest.excluded) == _norm_set([c])
    assert not ctrl.forest.items  # forget never re-adds


# --- restore dialog (tree reconstruction) --------------------------------

class _FakeCtrl:
    def __init__(self, excluded):
        self.forest_window = None
        self.forest = types.SimpleNamespace(excluded=list(excluded))
        self.added: list[str] = []
        self.forgot: list[str] = []

    def add_item(self, p, kind=None):  # noqa: ANN001
        self.added.append(p)

    def forget_excluded(self, paths):  # noqa: ANN001
        self.forgot.extend(paths)

    def save(self):
        pass


def _all_items(tree):
    out = []
    def walk(parent):
        for i in range(parent.childCount()):
            ch = parent.child(i)
            out.append(ch)
            walk(ch)
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        out.append(top)
        walk(top)
    return out


def test_excluded_dialog_builds_tree_and_folder_restores_children(tmp_path) -> None:
    app = tmp_path / "SolidWorks"
    toolkit = str(app / "kit.scriptreetree")
    child = str(app / "Drawings" / "x.scriptree")
    other = str(tmp_path / "MSOffice" / "y.scriptree")
    fake = _FakeCtrl([toolkit, child, other])
    dlg = ExcludedItemsDialog(fake)
    try:
        items = _all_items(dlg._tree)
        # Selecting the SolidWorks folder node should yield BOTH SolidWorks
        # paths (parent + child) and not the MSOffice one.
        sw_nodes = [it for it in items if it.text(0) == "SolidWorks"]
        assert sw_nodes, "expected a SolidWorks folder node in the tree"
        dlg._tree.clearSelection()
        sw_nodes[0].setSelected(True)
        sel = set(dlg._selected_paths())
        assert sel == {toolkit, child}
        # Re-include on that selection re-adds both SolidWorks paths.
        dlg._reinclude_selected()
        assert set(fake.added) == {toolkit, child}
    finally:
        dlg.deleteLater()
        _app.processEvents()


def test_excluded_dialog_empty_is_safe() -> None:
    fake = _FakeCtrl([])
    dlg = ExcludedItemsDialog(fake)
    try:
        assert dlg._selected_paths() == []
    finally:
        dlg.deleteLater()
        _app.processEvents()
