"""Tests for the editable TreeLauncherView.

These tests exercise the pure-ish helpers that don't require a real
user drag-drop interaction: path relativization, the QTreeWidget →
TreeDef rebuild, dirty-state tracking, and the full save-reload
round-trip. Anything that requires actual mouse events (real
drag-drop from File Explorer) is out of scope — we test the handler
functions that drops would call into, which is the honest layer to
pin.

Requires a QApplication, so we create one at module scope. The tests
don't run an event loop; they just construct widgets, poke their
methods, and inspect the resulting state.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# Create a QApplication once for the whole module. pytest-qt would
# give us a ``qtbot`` fixture, but we don't want to add a new test
# dependency just for widget construction.
from PySide6.QtWidgets import QApplication, QTreeWidgetItem

_app = QApplication.instance() or QApplication([])

from scriptree.core.io import load_tree, save_tool  # noqa: E402
from scriptree.core.model import (  # noqa: E402
    ParamDef,
    ToolDef,
    TreeDef,
    TreeNode,
)
from scriptree.ui.tree_view import (  # noqa: E402
    TreeLauncherView,
    _is_folder,
    _is_leaf,
)


# --- fixtures --------------------------------------------------------------

def _write_tool(path: Path, name: str) -> None:
    tool = ToolDef(
        name=name,
        executable="/bin/echo",
        params=[ParamDef(id="msg")],
        argument_template=["{msg}"],
    )
    save_tool(tool, path)


@pytest.fixture
def tmp_tree_dir(tmp_path: Path) -> Path:
    """Create a directory with three .scriptree files and a tree file."""
    (tmp_path / "sub").mkdir()
    _write_tool(tmp_path / "alpha.scriptree", "alpha")
    _write_tool(tmp_path / "beta.scriptree", "beta")
    _write_tool(tmp_path / "sub" / "gamma.scriptree", "gamma")

    tree = TreeDef(
        name="test tree",
        nodes=[
            TreeNode(type="leaf", path="./alpha.scriptree"),
            TreeNode(
                type="folder",
                name="nested",
                children=[
                    TreeNode(type="leaf", path="./sub/gamma.scriptree"),
                ],
            ),
        ],
    )
    tree_path = tmp_path / "group.scriptreetree"
    tree_path.write_text(
        json.dumps({
            "schema_version": 3,
            "name": tree.name,
            "nodes": [
                {"type": "leaf", "path": "./alpha.scriptree"},
                {
                    "type": "folder",
                    "name": "nested",
                    "children": [
                        {"type": "leaf", "path": "./sub/gamma.scriptree"},
                    ],
                },
            ],
        }, indent=2),
        encoding="utf-8",
    )
    return tmp_path


# --- a96 helpers: the tree now renders under a single ROOT row -------------

def _root(view: TreeLauncherView) -> QTreeWidgetItem:
    """The synthetic ROOT row added in v0.8.0a96 (topLevelItem(0))."""
    return view._tree_widget.topLevelItem(0)


def _nodes(view: TreeLauncherView) -> list[QTreeWidgetItem]:
    """The tree's top-level NODE items — children of the ROOT row."""
    r = _root(view)
    return [r.child(i) for i in range(r.childCount())]


# --- load/display ----------------------------------------------------------

class TestLoadDisplay:
    def test_loads_leaves_and_folders(self, tmp_tree_dir: Path) -> None:
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        # a96 — exactly one ROOT row, which holds the two nodes as children.
        assert view._tree_widget.topLevelItemCount() == 1
        assert _root(view).childCount() == 2
        alpha = _nodes(view)[0]
        folder = _nodes(view)[1]
        assert _is_leaf(alpha)
        assert _is_folder(folder)
        assert folder.text(0) == "nested"
        assert folder.childCount() == 1
        assert _is_leaf(folder.child(0))
        assert view.is_dirty() is False

    def test_leaf_stores_absolute_path(self, tmp_tree_dir: Path) -> None:
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        alpha = _nodes(view)[0]
        from PySide6.QtCore import Qt
        stored = alpha.data(0, Qt.ItemDataRole.UserRole)
        assert Path(stored).resolve() == (tmp_tree_dir / "alpha.scriptree").resolve()


# --- save preserves tree-level metadata (a95 regression) ------------------

class TestSavePreservesTreeMetadata:
    """v0.8.0a95 — saving a tree via the editor must NOT reset its tree-level
    fields.  Pre-a95 ``_build_tree_def`` returned ``TreeDef(name, nodes)`` and
    wiped ``category`` / the ``cell_*`` set / ``path_prepend`` / ``menus`` /
    ``folder_layout`` on every Save (silent data loss)."""

    def test_save_round_trip_preserves_category_icon_and_path_prepend(
        self, tmp_path: Path,
    ) -> None:
        _write_tool(tmp_path / "alpha.scriptree", "alpha")
        tree_path = tmp_path / "rich.scriptreetree"
        tree_path.write_text(json.dumps({
            "schema_version": 3,
            "name": "Rich Tree",
            "category": "MSOffice/Outlook",
            "path_prepend": ["C:/tools/bin"],
            "cell": {"icon": "email"},
            "nodes": [{"type": "leaf", "path": "./alpha.scriptree"}],
        }, indent=2), encoding="utf-8")

        view = TreeLauncherView()
        view.load(str(tree_path))
        # A bare save (no structural edit) must round-trip the metadata.
        assert view._save_tree() is True

        reloaded = load_tree(str(tree_path))
        assert reloaded.category == "MSOffice/Outlook"
        assert reloaded.path_prepend == ["C:/tools/bin"]
        assert reloaded.cell_icon == "email"
        assert len(reloaded.nodes) == 1  # structure intact

    def test_build_tree_def_keeps_fields_after_node_edit(
        self, tmp_path: Path,
    ) -> None:
        """Even after the node list changes, non-node fields survive."""
        _write_tool(tmp_path / "alpha.scriptree", "alpha")
        tree_path = tmp_path / "rich2.scriptreetree"
        tree_path.write_text(json.dumps({
            "schema_version": 3,
            "name": "Rich Tree 2",
            "category": "DevTools",
            "nodes": [{"type": "leaf", "path": "./alpha.scriptree"}],
        }, indent=2), encoding="utf-8")
        view = TreeLauncherView()
        view.load(str(tree_path))
        rebuilt = view._build_tree_def()
        assert rebuilt.category == "DevTools"
        assert rebuilt.name == "Rich Tree 2"


# --- a96: clickable root node + properties editor -------------------------

class TestRootNodeA96:
    def test_root_row_present_and_holds_nodes(self, tmp_tree_dir: Path) -> None:
        from scriptree.ui.tree_view import _is_root
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        assert view._tree_widget.topLevelItemCount() == 1
        root = _root(view)
        assert _is_root(root)
        assert root.text(0) == "test tree"        # labelled with the tree name
        assert root.childCount() == 2              # the two nodes nest under it

    def test_root_not_draggable_but_drop_enabled(self, tmp_tree_dir: Path) -> None:
        from PySide6.QtCore import Qt
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        flags = _root(view).flags()
        assert flags & Qt.ItemFlag.ItemIsDropEnabled       # accepts dropped nodes
        assert not (flags & Qt.ItemFlag.ItemIsDragEnabled)  # but can't be dragged

    def test_root_is_not_removable(self, tmp_tree_dir: Path) -> None:
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        root = _root(view)
        view._tree_widget.setCurrentItem(root)
        view._remove_selected()
        assert _root(view) is root          # root survives a Remove
        assert root.childCount() == 2       # nodes intact

    def test_drop_on_empty_lands_under_root_no_stray(
        self, tmp_tree_dir: Path,
    ) -> None:
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        view._on_file_dropped(
            str(tmp_tree_dir / "beta.scriptree"), target_item=None,
        )
        # exactly ONE top-level item (the root); the new leaf nests under it.
        assert view._tree_widget.topLevelItemCount() == 1
        assert _root(view).childCount() == 3

    def test_sweep_reparents_stray_top_level_item(self, tmp_tree_dir: Path) -> None:
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        tw = view._tree_widget
        # Simulate a Qt internal-move that left a node at the top level.
        stray = QTreeWidgetItem(["stray"])
        tw.addTopLevelItem(stray)
        assert tw.topLevelItemCount() == 2
        tw._sweep_strays_under_root()
        assert tw.topLevelItemCount() == 1          # only the root remains
        root = _root(view)
        assert root.child(root.childCount() - 1) is stray  # swept under root

    def test_blank_root_rename_restores_label(self, tmp_tree_dir: Path) -> None:
        """Clearing the root label inline must snap back to the tree name —
        not leave a blank row desynced from the title (a96 review fix)."""
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        root = _root(view)
        root.setText(0, "   ")              # user clears it to whitespace
        assert root.text(0) == "test tree"  # restored to canonical name
        assert view._tree.name == "test tree"

    def test_properties_editor_sets_category_and_save_persists(
        self, monkeypatch, tmp_tree_dir: Path,
    ) -> None:
        from scriptree.ui import tree_view as tv
        tree_path = tmp_tree_dir / "group.scriptreetree"
        view = TreeLauncherView()
        view.load(str(tree_path))
        assert view._tree.category == ""  # the fixture tree is uncategorised

        # Drive the (modal) properties dialog headlessly: stub exec() to fill
        # the fields and accept.
        def fake_exec(dlg):
            dlg._name.setText("Renamed Tree")
            dlg._category.setText("MSOffice/Outlook")
            dlg._path_prepend.setPlainText("C:/x/bin")
            return tv.QDialog.DialogCode.Accepted

        monkeypatch.setattr(tv._TreePropertiesDialog, "exec", fake_exec)
        view._open_tree_properties()

        assert view._tree.category == "MSOffice/Outlook"
        assert view._tree.name == "Renamed Tree"
        assert view._tree.path_prepend == ["C:/x/bin"]
        assert _root(view).text(0) == "Renamed Tree"   # root row relabelled

        assert view._save_tree() is True
        reloaded = load_tree(str(tree_path))
        assert reloaded.category == "MSOffice/Outlook"
        assert reloaded.name == "Renamed Tree"
        assert reloaded.path_prepend == ["C:/x/bin"]


# --- path relativization --------------------------------------------------

class TestMaybeRelative:
    def test_sibling_becomes_dot_slash(self, tmp_tree_dir: Path) -> None:
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        rel = view._maybe_relative(str(tmp_tree_dir / "alpha.scriptree"))
        assert rel == "./alpha.scriptree"

    def test_subfolder_path(self, tmp_tree_dir: Path) -> None:
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        rel = view._maybe_relative(str(tmp_tree_dir / "sub" / "gamma.scriptree"))
        assert rel == "./sub/gamma.scriptree"

    def test_parent_folder_uses_dotdot(
        self, tmp_tree_dir: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        # Create a tool one directory up from the tree.
        parent = tmp_tree_dir.parent
        outside = parent / "outside.scriptree"
        _write_tool(outside, "outside")
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        rel = view._maybe_relative(str(outside))
        assert rel.startswith("../")
        assert rel.endswith("outside.scriptree")

    def test_no_tree_file_returns_posix_absolute(self) -> None:
        view = TreeLauncherView()
        # No tree loaded → _tree_file is None.
        rel = view._maybe_relative("C:/some/abs/path.scriptree")
        assert "\\" not in rel  # normalized to forward slashes


# --- add/remove operations ------------------------------------------------

class TestAddRemove:
    def test_add_leaf_via_drop_handler(self, tmp_tree_dir: Path) -> None:
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        # Simulate an external drop on empty space.
        view._on_file_dropped(
            str(tmp_tree_dir / "beta.scriptree"), target_item=None
        )
        # The new leaf should be top-level, dirty flag should be set.
        assert _root(view).childCount() == 3
        assert view.is_dirty() is True

    def test_drop_onto_folder_adds_as_child(self, tmp_tree_dir: Path) -> None:
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        folder = _nodes(view)[1]
        before = folder.childCount()
        view._on_file_dropped(
            str(tmp_tree_dir / "beta.scriptree"), target_item=folder
        )
        assert folder.childCount() == before + 1
        assert view.is_dirty() is True

    def test_drop_onto_leaf_adds_as_sibling(self, tmp_tree_dir: Path) -> None:
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        # Drop onto the top-level alpha leaf → becomes another top-level leaf.
        alpha = _nodes(view)[0]
        view._on_file_dropped(
            str(tmp_tree_dir / "beta.scriptree"), target_item=alpha
        )
        assert _root(view).childCount() == 3

    def test_remove_selected(self, tmp_tree_dir: Path) -> None:
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        alpha = _nodes(view)[0]
        view._tree_widget.setCurrentItem(alpha)
        view._remove_selected()
        assert _root(view).childCount() == 1  # only the folder remains
        assert view.is_dirty() is True


# --- save / rebuild round-trip --------------------------------------------

class TestSaveRoundTrip:
    def test_save_unchanged_tree_preserves_structure(
        self, tmp_tree_dir: Path
    ) -> None:
        tree_path = tmp_tree_dir / "group.scriptreetree"
        view = TreeLauncherView()
        view.load(str(tree_path))

        ok = view._save_tree()
        assert ok is True
        assert view.is_dirty() is False

        # Reload from disk and check structural identity.
        reloaded = load_tree(tree_path)
        assert reloaded.name == "test tree"
        assert len(reloaded.nodes) == 2
        assert reloaded.nodes[0].type == "leaf"
        assert reloaded.nodes[0].path == "./alpha.scriptree"
        assert reloaded.nodes[1].type == "folder"
        assert reloaded.nodes[1].name == "nested"
        assert len(reloaded.nodes[1].children) == 1
        assert reloaded.nodes[1].children[0].path == "./sub/gamma.scriptree"

    def test_save_after_drop_adds_new_leaf(
        self, tmp_tree_dir: Path
    ) -> None:
        tree_path = tmp_tree_dir / "group.scriptreetree"
        view = TreeLauncherView()
        view.load(str(tree_path))

        # Drop beta.scriptree at the root, then save.
        view._on_file_dropped(
            str(tmp_tree_dir / "beta.scriptree"), target_item=None
        )
        view._save_tree()

        reloaded = load_tree(tree_path)
        paths = [
            n.path for n in reloaded.nodes if n.type == "leaf"
        ]
        assert "./alpha.scriptree" in paths
        assert "./beta.scriptree" in paths

    def test_save_after_remove_drops_leaf(
        self, tmp_tree_dir: Path
    ) -> None:
        tree_path = tmp_tree_dir / "group.scriptreetree"
        view = TreeLauncherView()
        view.load(str(tree_path))

        # Remove alpha, save, reload → should only have the folder.
        alpha = _nodes(view)[0]
        view._tree_widget.setCurrentItem(alpha)
        view._remove_selected()
        view._save_tree()

        reloaded = load_tree(tree_path)
        assert len(reloaded.nodes) == 1
        assert reloaded.nodes[0].type == "folder"

    def test_save_after_move_to_folder(self, tmp_tree_dir: Path) -> None:
        """Simulate reparenting by manipulating the QTreeWidget directly.

        Drag-drop would call the same underlying Qt methods — we're
        exercising the rebuild path, not the mouse handling.
        """
        tree_path = tmp_tree_dir / "group.scriptreetree"
        view = TreeLauncherView()
        view.load(str(tree_path))

        # a96 — nodes live under the ROOT row, so reparent within the root.
        alpha = _nodes(view)[0]
        folder = _nodes(view)[1]
        # Take alpha off the root and add as a child of folder.
        alpha.parent().removeChild(alpha)
        folder.addChild(alpha)
        view._mark_dirty()
        view._save_tree()

        reloaded = load_tree(tree_path)
        assert len(reloaded.nodes) == 1
        assert reloaded.nodes[0].type == "folder"
        child_paths = [
            c.path for c in reloaded.nodes[0].children if c.type == "leaf"
        ]
        assert "./alpha.scriptree" in child_paths
        assert "./sub/gamma.scriptree" in child_paths


# --- new empty tree --------------------------------------------------------

class TestNewTree:
    def test_new_tree_is_dirty_and_empty(self) -> None:
        view = TreeLauncherView()
        view.new_tree("My tree")
        # a96 — a new tree still has its ROOT row, with zero child nodes.
        assert view._tree_widget.topLevelItemCount() == 1
        assert _root(view).childCount() == 0
        assert view.is_dirty() is True
        assert view._tree is not None
        assert view._tree.name == "My tree"


# --- v0.6.1 interaction changes --------------------------------------------

class TestTreeInteractionV061:
    """Single-click activation, right-click Edit on the hovered item,
    double-right-click → standalone descriptor, debounced menu."""

    def _view(self, tmp_tree_dir: Path) -> TreeLauncherView:
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        return view

    def test_single_click_activates_leaf(self, tmp_tree_dir: Path) -> None:
        view = self._view(tmp_tree_dir)
        got: list = []
        view.toolSelected.connect(lambda t, p: got.append(p))
        alpha = _nodes(view)[0]
        # itemClicked is the wired signal now (not itemDoubleClicked).
        view._tree_widget.itemClicked.emit(alpha, 0)
        assert len(got) == 1
        assert got[0].endswith("alpha.scriptree")

    def test_right_click_edit_emits_editRequested(
        self, tmp_tree_dir: Path
    ) -> None:
        view = self._view(tmp_tree_dir)
        got: list = []
        view.editRequested.connect(lambda t, p: got.append((t, p)))
        alpha = _nodes(view)[0]
        view._emit_edit_for(alpha)
        assert len(got) == 1
        tool, path = got[0]
        assert path.endswith("alpha.scriptree")
        assert tool.name == "alpha"

    def test_double_right_click_descriptor_for_leaf(
        self, tmp_tree_dir: Path
    ) -> None:
        view = self._view(tmp_tree_dir)
        alpha = _nodes(view)[0]
        desc = view._standalone_descriptor(alpha)
        assert desc["kind"] == "tool"
        assert desc["path"].endswith("alpha.scriptree")
        assert desc["tool"].name == "alpha"

    def test_double_right_click_descriptor_for_folder(
        self, tmp_tree_dir: Path
    ) -> None:
        view = self._view(tmp_tree_dir)
        folder = _nodes(view)[1]
        assert view._standalone_descriptor(folder) == {"kind": "folder"}
        # Empty space (None) → whole-tree fallback descriptor.
        assert view._standalone_descriptor(None) == {"kind": "folder"}

    def test_standalone_requested_emitted_on_right_double(
        self, tmp_tree_dir: Path
    ) -> None:
        view = self._view(tmp_tree_dir)
        got: list = []
        view.standaloneRequested.connect(lambda d: got.append(d))
        alpha = _nodes(view)[0]
        view._emit_standalone_for(alpha)
        assert len(got) == 1 and got[0]["kind"] == "tool"

    def test_context_menu_is_debounced(
        self, tmp_tree_dir: Path
    ) -> None:
        view = self._view(tmp_tree_dir)
        from PySide6.QtCore import QPoint
        view._schedule_context_menu(QPoint(1, 1))
        assert view._ctx_timer.isActive()
        # A right double-click cancels the pending menu.
        view._on_right_double_click(QPoint(1, 1))
        assert not view._ctx_timer.isActive()
