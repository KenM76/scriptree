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
            "schema_version": 1,
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


# --- load/display ----------------------------------------------------------

class TestLoadDisplay:
    def test_loads_leaves_and_folders(self, tmp_tree_dir: Path) -> None:
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        tw = view._tree_widget
        assert tw.topLevelItemCount() == 2
        alpha = tw.topLevelItem(0)
        folder = tw.topLevelItem(1)
        assert _is_leaf(alpha)
        assert _is_folder(folder)
        assert folder.text(0) == "nested"
        assert folder.childCount() == 1
        assert _is_leaf(folder.child(0))
        assert view.is_dirty() is False

    def test_leaf_stores_absolute_path(self, tmp_tree_dir: Path) -> None:
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        alpha = view._tree_widget.topLevelItem(0)
        from PySide6.QtCore import Qt
        stored = alpha.data(0, Qt.ItemDataRole.UserRole)
        assert Path(stored).resolve() == (tmp_tree_dir / "alpha.scriptree").resolve()


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
        assert view._tree_widget.topLevelItemCount() == 3
        assert view.is_dirty() is True

    def test_drop_onto_folder_adds_as_child(self, tmp_tree_dir: Path) -> None:
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        folder = view._tree_widget.topLevelItem(1)
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
        alpha = view._tree_widget.topLevelItem(0)
        view._on_file_dropped(
            str(tmp_tree_dir / "beta.scriptree"), target_item=alpha
        )
        assert view._tree_widget.topLevelItemCount() == 3

    def test_remove_selected(self, tmp_tree_dir: Path) -> None:
        view = TreeLauncherView()
        view.load(str(tmp_tree_dir / "group.scriptreetree"))
        alpha = view._tree_widget.topLevelItem(0)
        view._tree_widget.setCurrentItem(alpha)
        view._remove_selected()
        assert view._tree_widget.topLevelItemCount() == 1  # only the folder remains
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
        alpha = view._tree_widget.topLevelItem(0)
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

        tw = view._tree_widget
        alpha = tw.topLevelItem(0)
        folder = tw.topLevelItem(1)
        # Take alpha off the top level and add as a child of folder.
        tw.takeTopLevelItem(tw.indexOfTopLevelItem(alpha))
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
        assert view._tree_widget.topLevelItemCount() == 0
        assert view.is_dirty() is True
        assert view._tree is not None
        assert view._tree.name == "My tree"
