"""Bugs surfaced by user testing of v0.8.0a34 -- pin each as a
failing test, then fix in the code.  Each ``TestXxx`` class
corresponds to one user-reported issue.

Bugs:
  B1 - Tree view's right-click context menu has no Save action,
       making the editor's "save the loaded tree" path
       undiscoverable from the surface the user actually right-
       clicks.
  B2 - Uninstalling an app from the editor doesn't persist its
       removal -- the next forest launch re-creates the cell as
       if it was never uninstalled.  Editor's ephemeral
       controller (introduced in a34) writes only to a MagicMock
       forest; the real on-disk .scriptreeforest never updates.
  B3 - After uninstall completes, a spurious tool runner pops up
       showing the extras + command-line panes.  Almost
       certainly the editor's tree view reselecting the next
       remaining item after the uninstalled one is gone, which
       fires toolSelected -> _show_runner.
  B4 - Drag-and-drop in the tree view lets the user drop a leaf
       ONTO another leaf, nesting it as a child.  Leaves should
       only ever be siblings of other leaves, or children of
       folders.
  B5 - Single-click on a leaf in the editor's tree view opens
       the tool's runner (extras + command line).  Users expect
       single-click to NAVIGATE (select), not to launch.
       Launches should require explicit double-click or right-
       click -> Open.

Each class verifies the BUG (failing test) and then the FIX
(passing once the code is patched).  The bug-witness tests are
marked with a v0.8.0a35 expectation; the same test will start
passing once the fix lands.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QDialog, QMenu, QMessageBox, QTreeWidgetItem,
)

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
QMessageBox.critical = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_scriptree(path: Path, name: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "name": name or path.stem,
            "executable": "echo",
            "params": [],
        }),
        encoding="utf-8",
    )


def _write_scriptreetree(
    path: Path, leaves: list[Path], name: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nodes = []
    for leaf in leaves:
        try:
            rel = Path(leaf).relative_to(path.parent)
            leaf_path = str(rel).replace("\\", "/")
        except ValueError:
            leaf_path = str(leaf)
        nodes.append({
            "type": "leaf",
            "name": leaf.stem,
            "path": leaf_path,
        })
    path.write_text(
        json.dumps({"name": name or path.stem, "nodes": nodes}),
        encoding="utf-8",
    )


# ===========================================================================
# B1 - Tree view's right-click context menu missing Save
# ===========================================================================

class TestB1_TreeViewSaveInContextMenu:
    """The tree view's right-click context menu should include
    a Save action.  Today the only way to save the loaded tree
    is via the File menu -- not discoverable from the surface
    the user is actively right-clicking in."""

    def test_empty_area_context_menu_has_save(self, tmp_path):
        """Right-click on empty space (no item under cursor)
        should still offer Save tree -- the loaded tree is the
        implicit root.
        """
        from scriptree.ui.tree_view import TreeLauncherView
        view = TreeLauncherView()
        # Load a fresh empty tree so the launcher has SOMETHING
        # to "save" -- the menu's Save action is enabled
        # regardless of dirty/empty.
        view.new_tree()
        menu = QMenu(view)
        view._populate_context_menu_for(menu, item=None)
        labels = [a.text() for a in menu.actions()]
        save_present = any(
            "save" in lbl.lower() for lbl in labels
        )
        assert save_present, (
            f"empty-area context menu should expose a Save "
            f"action; got {labels!r}"
        )

    def test_top_level_item_context_menu_has_save(self, tmp_path):
        """When right-clicking a top-level item in the tree the
        menu should also have Save."""
        from scriptree.ui.tree_view import TreeLauncherView
        # Write a tree file to load.
        leaf = tmp_path / "a.scriptree"
        _write_scriptree(leaf, "A")
        tree_path = tmp_path / "demo.scriptreetree"
        _write_scriptreetree(tree_path, [leaf], name="Demo")
        view = TreeLauncherView()
        view.load(str(tree_path))
        item = view._tree_widget.topLevelItem(0)
        assert item is not None
        menu = QMenu(view)
        view._populate_context_menu_for(menu, item=item)
        labels = [a.text() for a in menu.actions()]
        save_present = any(
            "save" in lbl.lower() for lbl in labels
        )
        assert save_present, (
            f"item context menu should expose a Save action; "
            f"got {labels!r}"
        )


def _make_simple_tree():
    """Build a minimal TreeDef in memory for the editor to render."""
    from scriptree.core.model import TreeDef, TreeNode
    return TreeDef(
        name="DemoTree",
        nodes=[
            TreeNode(
                type="folder", name="ToolsA",
                children=[
                    TreeNode(type="leaf", path="a1.scriptree"),
                    TreeNode(type="leaf", path="a2.scriptree"),
                ],
            ),
            TreeNode(
                type="folder", name="ToolsB",
                children=[
                    TreeNode(type="leaf", path="b1.scriptree"),
                ],
            ),
        ],
    )


# ===========================================================================
# B2 - Uninstall from editor doesn't persist
# ===========================================================================

class TestB2_EditorUninstallPersistsExclusion:
    """The editor's ``_on_tree_uninstall_requested`` (a34) used
    a MagicMock for the forest -- so the on-disk
    ``.scriptreeforest`` never received the exclusion + items-
    removal that the real ForestController.uninstall_app does.
    Next forest launch re-creates the cell.

    The fix: editor's uninstall handler must also update the
    on-disk forest file (the running forest can't be notified
    cross-process; updating the file is what survives a relaunch).
    """

    def test_persist_helper_updates_on_disk_forest_file(
        self, tmp_path, monkeypatch,
    ):
        """The ``_persist_uninstall_to_forest_file`` helper must
        load the per-user default forest file, remove the
        uninstalled catalog from ``items``, and add it to
        ``excluded``.

        We test the persist helper directly (rather than the
        whole _on_tree_uninstall_requested flow) because the
        full flow needs a real QMainWindow + dialog event loop
        which is brittle in a test environment.  The helper IS
        the unit of fix for this bug; the dialog plumbing is
        tested elsewhere.
        """
        from scriptree.shell import forest_io
        forest_file = tmp_path / "default.scriptreeforest"
        catalog = tmp_path / "DemoApp" / "demo.scriptree"
        _write_scriptree(catalog)
        forest = forest_io.ForestDef(
            items=[
                forest_io.ForestItem(
                    path=str(catalog), kind="tool",
                ),
            ],
            excluded=[],
        )
        forest_io.save_forest(forest, forest_file)

        with patch.object(
            forest_io, "default_autoload_path",
            return_value=forest_file,
        ):
            from scriptree.ui.main_window import MainWindow
            mw = MainWindow.__new__(MainWindow)
            mw._persist_uninstall_to_forest_file(str(catalog))

        updated = forest_io.load_forest(forest_file)
        norm_excluded = [
            str(Path(e).resolve()) for e in updated.excluded
        ]
        assert str(Path(catalog).resolve()) in norm_excluded or (
            str(catalog) in updated.excluded
        ), (
            f"uninstalled catalog should be in excluded list; "
            f"got excluded={updated.excluded!r}"
        )
        items_paths = [
            str(Path(it.path).resolve()) for it in updated.items
        ]
        assert str(Path(catalog).resolve()) not in items_paths, (
            f"uninstalled catalog should be removed from items; "
            f"got items={items_paths!r}"
        )


# ===========================================================================
# B3 - Spurious runner popup after uninstall
# ===========================================================================

class TestB3_NoSpuriousRunnerAfterUninstall:
    """After a successful uninstall, the editor must not emit
    ``toolSelected`` (which would open the runner).  The most
    common trigger is the tree view's auto-reselect of the next
    item after the deleted one disappears.
    """

    def test_uninstall_does_not_emit_tool_selected(
        self, tmp_path, monkeypatch,
    ):
        """If the editor was showing the uninstalled tree, the
        ``new_tree()`` reset that follows uninstall must NOT
        trigger toolSelected emissions.
        """
        from scriptree.shell import forest_io
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        from scriptree.core.app_install import default_personal_root
        apps = default_personal_root()
        apps.mkdir(parents=True, exist_ok=True)
        app_dir = apps / "DemoApp"
        catalog = app_dir / "demo.scriptree"
        _write_scriptree(catalog)

        from scriptree.ui.tree_view import TreeLauncherView
        view = TreeLauncherView()

        emissions: list = []
        view.toolSelected.connect(
            lambda tool, path: emissions.append((tool, path))
        )

        # Simulate "new_tree" being called as part of post-
        # uninstall cleanup.  It must not fire toolSelected.
        view.new_tree()
        assert emissions == [], (
            f"new_tree should not emit toolSelected; got {emissions!r}"
        )


# ===========================================================================
# B4 - Drag-drop nests leaves under leaves
# ===========================================================================

class TestB4_DropDoesNotNestLeafUnderLeaf:
    """Dropping a leaf ONTO another leaf must NOT nest it as a
    child of the target.  Either the drop is rejected, or it's
    repositioned to a sibling slot adjacent to the target.
    """

    def test_internal_move_drop_on_leaf_rejected_or_sibling(
        self, tmp_path,
    ):
        """Verify the policy via the public helper.  We can't
        easily synthesise a real Qt InternalMove without
        QDropEvent gymnastics; instead we check that the
        editable-tree-widget exposes a guard the dropEvent uses.

        v0.8.0a35+ -- ``_EditableTreeWidget._is_legal_drop_target``
        returns False for leaf targets when the source is also a
        leaf.  Until the guard exists, ``hasattr`` returns False
        and this test fails.
        """
        from scriptree.ui.tree_view import _EditableTreeWidget
        assert hasattr(_EditableTreeWidget, "_is_legal_drop_target"), (
            "_EditableTreeWidget must expose a guard predicate "
            "that the dropEvent uses to reject leaf-onto-leaf "
            "drops"
        )


# ===========================================================================
# B5 - Single-click launches runner
# ===========================================================================

class TestB5_SingleClickLaunchesRunner:
    """Single-clicking a leaf in the editor's tree view MUST
    open the runner.

    History note: this test originally asserted the OPPOSITE
    (in a35 I no-op'd ``_on_tool_selected`` because of a user
    complaint about right-click also launching).  Turned out
    the actual annoyance was right-click firing itemClicked --
    which a34 fixed by swallowing right-button events.  The a35
    no-op broke legitimate left-click activation; a38 reverted
    it.  The test is rewritten to match the corrected policy.
    """

    def test_single_click_opens_runner(self, tmp_path):
        """``_on_tool_selected`` MUST call ``_show_runner``.

        v0.8.0a38+ -- restored from the a35 no-op regression.
        Right-click no longer hits this path (see the a34
        mousePressEvent / mouseReleaseEvent overrides in
        _EditableTreeWidget that swallow right-button before
        itemClicked fires), so opening the runner here is the
        legitimate single-left-click semantic.
        """
        from scriptree.ui.main_window import MainWindow
        mw = MainWindow.__new__(MainWindow)
        mw._launcher = MagicMock()
        mw._dock_manager = MagicMock()
        mw._stack = MagicMock()
        mw._active_editor = None
        mw._runners = {}
        mw._unsaved_runner = None
        show_runner_calls = []
        mw._show_runner = lambda tool, path: show_runner_calls.append(
            (tool, path),
        )
        mw._show_editor = lambda tool, path: None

        from scriptree.core.model import ToolDef
        tool = ToolDef(name="demo", executable="echo")
        mw._on_tool_selected(tool, "C:/fake/demo.scriptree")

        assert show_runner_calls == [
            (tool, "C:/fake/demo.scriptree"),
        ], (
            f"single-click MUST open the runner; got "
            f"calls={show_runner_calls!r}"
        )


# ===========================================================================
# Bonus: proactive checks
# ===========================================================================

class TestProactive_RightClickStillSwallowsLaunch:
    """The a34 fix for right-click suppressed itemClicked.
    Verify it still holds (no regression)."""

    def test_right_click_filter_swallows_release(self):
        """The editor tree widget must override
        mouseReleaseEvent to swallow the right-button release
        (the matching half of mousePressEvent's swallow).
        Otherwise a single right-click still fires itemClicked
        when the release reaches the base class."""
        from scriptree.ui.tree_view import _EditableTreeWidget
        # The override is what guarantees the fix from a34.
        # Verify it exists.
        assert "mouseReleaseEvent" in _EditableTreeWidget.__dict__, (
            "mouseReleaseEvent override is missing -- right-"
            "click could re-trigger launch via base class"
        )
        assert "mousePressEvent" in _EditableTreeWidget.__dict__, (
            "mousePressEvent override is missing"
        )
