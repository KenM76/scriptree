"""Tests for the new File-menu actions:

* Save tool / Save tool as...   (.scriptree)
* Save tree as...               (.scriptreetree)
* Open in cell shell            (active file → ScripTreeRing)
* Open tree in ring shell       (top-level explode → ScripTreeRing)

These are additive to the older Save tree (Ctrl+S) and Save Cell
Layout actions, so the tests focus on the new code paths.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.io import save_tool, save_tree  # noqa: E402
from scriptree.core.model import ToolDef, TreeDef, TreeNode  # noqa: E402
from scriptree.ui.main_window import MainWindow  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_tool(tmp_path: Path, name: str = "demo") -> Path:
    p = tmp_path / f"{name}.scriptree"
    save_tool(ToolDef(name=name, executable="python"), p)
    return p


def _seed_tree(tmp_path: Path, *, with_folder: bool = True) -> Path:
    """Return the path of a saved .scriptreetree.

    The tree has one folder with two leaves and one top-level leaf so
    "Open in ring" has multiple top-level items to explode.
    """
    leaf_a = _seed_tool(tmp_path, "alpha")
    leaf_b = _seed_tool(tmp_path, "beta")
    leaf_c = _seed_tool(tmp_path, "gamma")
    nodes: list[TreeNode] = []
    if with_folder:
        nodes.append(TreeNode(
            type="folder", name="Group",
            children=[
                TreeNode(type="leaf", name="alpha", path=str(leaf_a)),
                TreeNode(type="leaf", name="beta",  path=str(leaf_b)),
            ],
        ))
    nodes.append(TreeNode(type="leaf", name="gamma", path=str(leaf_c)))
    tree = TreeDef(name="DemoTree", nodes=nodes)
    p = tmp_path / "demo.scriptreetree"
    save_tree(tree, p)
    return p


# ---------------------------------------------------------------------------
# Menu items present
# ---------------------------------------------------------------------------

def test_file_menu_has_new_save_actions() -> None:
    w = MainWindow()
    labels = [a.text() for a in w._m_file.actions()]
    assert "Save &tool" in labels
    assert "Save tool &as..." in labels
    assert "&Save tree" in labels
    assert "Save tree as..." in labels


def test_file_menu_has_open_in_actions() -> None:
    w = MainWindow()
    labels = [a.text() for a in w._m_file.actions()]
    assert "Open in &cell shell" in labels
    assert "Open tree in &ring shell" in labels


def test_save_tool_disabled_without_editor() -> None:
    w = MainWindow()
    assert not w._act_save_tool.isEnabled()
    assert not w._act_save_tool_as.isEnabled()


def test_open_in_cell_disabled_when_nothing_loaded() -> None:
    w = MainWindow()
    assert not w._act_open_in_cell.isEnabled()
    assert not w._act_open_in_ring.isEnabled()


# ---------------------------------------------------------------------------
# Save tree as...
# ---------------------------------------------------------------------------

def test_save_tree_as_writes_to_chosen_path(tmp_path: Path) -> None:
    """A user-chosen path should be honoured and the launcher should
    re-bind to the new file."""
    w = MainWindow()
    src = _seed_tree(tmp_path)
    w._launcher.load(str(src))

    target = tmp_path / "renamed.scriptreetree"
    with patch(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName",
        return_value=(str(target), ""),
    ):
        w._save_tree_as()

    assert target.is_file()
    assert w._launcher.tree_file() == target.resolve()
    # The new path becomes a recent entry.
    assert any(
        Path(p).resolve() == target.resolve() for p in w._recent_trees
    )


def test_save_tree_as_cancelled_keeps_original(tmp_path: Path) -> None:
    w = MainWindow()
    src = _seed_tree(tmp_path)
    w._launcher.load(str(src))

    with patch(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName",
        return_value=("", ""),
    ):
        w._save_tree_as()

    assert w._launcher.tree_file() == src.resolve()


def test_save_tree_as_action_enabled_after_load(tmp_path: Path) -> None:
    w = MainWindow()
    src = _seed_tree(tmp_path)
    w._launcher.load(str(src))
    assert w._act_save_tree_as.isEnabled()


# ---------------------------------------------------------------------------
# Save tool / Save tool as
# ---------------------------------------------------------------------------

def test_save_tool_actions_enabled_when_editor_open(tmp_path: Path) -> None:
    w = MainWindow()
    p = _seed_tool(tmp_path)
    w.open_file(str(p))
    # _show_runner runs first; explicitly transition into editor.
    from scriptree.core.io import load_tool
    w._show_editor(load_tool(str(p)), str(p))

    assert w._act_save_tool.isEnabled()
    assert w._act_save_tool_as.isEnabled()


def test_save_tool_delegates_to_active_editor(tmp_path: Path) -> None:
    w = MainWindow()
    p = _seed_tool(tmp_path)
    from scriptree.core.io import load_tool
    w._show_editor(load_tool(str(p)), str(p))

    with patch.object(w._active_editor, "save") as m:
        w._save_tool()
    m.assert_called_once()


def test_save_tool_as_delegates_to_active_editor(tmp_path: Path) -> None:
    w = MainWindow()
    p = _seed_tool(tmp_path)
    from scriptree.core.io import load_tool
    w._show_editor(load_tool(str(p)), str(p))

    with patch.object(w._active_editor, "save_as") as m:
        w._save_tool_as()
    m.assert_called_once()


def test_save_tool_no_editor_is_noop() -> None:
    """Calling _save_tool with no editor must not raise — it just
    posts a status-bar message."""
    w = MainWindow()
    w._save_tool()
    w._save_tool_as()


# ---------------------------------------------------------------------------
# Open in cell shell
# ---------------------------------------------------------------------------

def test_open_in_cell_uses_loaded_tree(tmp_path: Path) -> None:
    w = MainWindow()
    src = _seed_tree(tmp_path)
    w._launcher.load(str(src))
    assert w._act_open_in_cell.isEnabled()

    with patch("scriptree.shell.v1_launcher.launch_ring_shell") as m:
        w._open_in_cell()
    m.assert_called_once()
    args, _ = m.call_args
    assert Path(args[0]).resolve() == src.resolve()


def test_open_in_cell_prefers_active_tool(tmp_path: Path) -> None:
    """If a tool runner is active, its path wins over the loaded tree
    (the editor has more specific intent than the tree backdrop)."""
    w = MainWindow()
    tree_p = _seed_tree(tmp_path)
    tool_p = _seed_tool(tmp_path, "active_tool")
    w._launcher.load(str(tree_p))
    w.open_file(str(tool_p))

    with patch("scriptree.shell.v1_launcher.launch_ring_shell") as m:
        w._open_in_cell()
    args, _ = m.call_args
    assert Path(args[0]).resolve() == tool_p.resolve()


def test_open_in_cell_nothing_loaded_shows_info(tmp_path: Path) -> None:
    w = MainWindow()
    with patch(
        "PySide6.QtWidgets.QMessageBox.information"
    ) as m_info, patch(
        "scriptree.shell.v1_launcher.launch_ring_shell"
    ) as m_launch:
        w._open_in_cell()
    m_info.assert_called_once()
    m_launch.assert_not_called()


# ---------------------------------------------------------------------------
# Open in ring shell — explode tree
# ---------------------------------------------------------------------------

def test_open_in_ring_disabled_without_tree() -> None:
    w = MainWindow()
    assert not w._act_open_in_ring.isEnabled()


def test_open_in_ring_enabled_after_load(tmp_path: Path) -> None:
    w = MainWindow()
    src = _seed_tree(tmp_path)
    w._launcher.load(str(src))
    assert w._act_open_in_ring.isEnabled()


def test_open_in_ring_explodes_and_launches(tmp_path: Path) -> None:
    """Should produce a temp .scriptreering with N members (one per
    top-level item) and hand it off to the ring shell."""
    w = MainWindow()
    src = _seed_tree(tmp_path)  # 1 folder + 1 leaf at top level
    w._launcher.load(str(src))

    with patch("scriptree.shell.v1_launcher.launch_ring_shell") as m:
        w._open_in_ring()

    m.assert_called_once()
    args, _ = m.call_args
    ring_path = Path(args[0])
    assert ring_path.is_file()
    assert ring_path.suffix == ".scriptreering"
    doc = json.loads(ring_path.read_text(encoding="utf-8"))
    assert doc["master"]["role"] == "master"
    assert len(doc["members"]) == 2  # folder + top-level leaf
    catalog_paths = [m["catalog_path"] for m in doc["members"]]
    assert all(cp for cp in catalog_paths)


# --- v0.6.1 — Ctrl+S context-aware dispatch ---------------------------------

def test_ctrl_s_owned_by_dispatch_not_save_tree() -> None:
    """Regression: Ctrl+S must not be hard-bound to Save-tree.  It
    used to silently save the (unchanged) tree while a tool editor
    was open, dropping the tool edits."""
    w = MainWindow()
    assert w._act_save_dispatch.shortcut().toString() == "Ctrl+S"
    assert w._act_save_tree.shortcut().toString() == ""


def test_save_active_routes_to_tool_editor_when_open(
    tmp_path: Path,
) -> None:
    """With a tool editor active, Ctrl+S saves the tool, not the
    tree — even when a tree is also loaded."""
    from unittest.mock import patch
    w = MainWindow()
    src = _seed_tree(tmp_path)
    w._launcher.load(str(src))
    # Open a tool from the tree in the editor.
    leaf = w._launcher._tree_widget.topLevelItem(0)
    # topLevelItem(0) may be a folder; find a leaf path.
    from scriptree.ui.tree_view import _is_leaf
    tw = w._launcher._tree_widget
    leaf_item = None
    for i in range(tw.topLevelItemCount()):
        it = tw.topLevelItem(i)
        if _is_leaf(it):
            leaf_item = it
            break
        for j in range(it.childCount()):
            if _is_leaf(it.child(j)):
                leaf_item = it.child(j)
                break
        if leaf_item:
            break
    assert leaf_item is not None
    w._launcher._emit_edit_for(leaf_item)
    assert w._active_editor is not None
    with patch.object(w, "_save_tool") as m_tool, \
         patch.object(w, "_save_tree") as m_tree:
        w._save_active()
        m_tool.assert_called_once()
        m_tree.assert_not_called()


def test_save_active_routes_to_tree_when_no_editor(
    tmp_path: Path,
) -> None:
    from unittest.mock import patch
    w = MainWindow()
    src = _seed_tree(tmp_path)
    w._launcher.load(str(src))
    assert w._active_editor is None
    with patch.object(w, "_save_tool") as m_tool, \
         patch.object(w, "_save_tree") as m_tree:
        w._save_active()
        m_tree.assert_called_once()
        m_tool.assert_not_called()
