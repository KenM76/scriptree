"""Tests for the MainWindow File menu's "Scan tree for new tools…"
entry (v0.8.0a21+).

This is the editor-side equivalent of the cell shell's right-click
Tree → Refresh from sources action.  Three things to verify:

* The menu entry exists and points at the right slot.
* The action is enabled only when a tree is loaded.
* Triggering the slot constructs a ``TreeController`` against
  the loaded tree + path, calls ``run_one_shot_prompt()``, and
  re-loads the tree afterwards so the editor's view reflects
  any changes.

Tests avoid spinning up a real diff dialog by patching the
controller's ``run_one_shot_prompt`` before triggering the
slot.  Auto-dismisses ``QMessageBox`` per the standing rule.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)

from scriptree.core.discovery import TreeAutoDiscoverConfig
from scriptree.core.io import save_tree
from scriptree.core.model import TreeDef, TreeNode
from scriptree.ui.main_window import MainWindow


def _seed_tree(tmp_path: Path) -> Path:
    """Write a small ``.scriptreetree`` to disk + return its path."""
    tree = TreeDef(
        name="Test",
        nodes=[TreeNode(type="leaf", path="./existing.scriptree")],
        auto_discover=TreeAutoDiscoverConfig(),
    )
    path = tmp_path / "test.scriptreetree"
    save_tree(tree, path)
    return path


# ---------------------------------------------------------------------------
# Menu wiring
# ---------------------------------------------------------------------------


def test_file_menu_has_scan_tree_action() -> None:
    """File menu must include the new entry.

    Searches by text (with mnemonic ``&``) so a future tweak to
    the icon / shortcut doesn't break this guard."""
    w = MainWindow()
    file_menu = w._m_file
    labels = [a.text() for a in file_menu.actions()]
    assert "Scan tree for &new tools..." in labels, (
        f"File menu missing 'Scan tree for new tools' entry. "
        f"Current labels: {labels!r}"
    )


def test_scan_tree_action_disabled_with_no_tree_loaded() -> None:
    """The action must start disabled and stay disabled until a
    tree is loaded — same pattern as Save tree / Save tree as /
    Open in ring shell."""
    w = MainWindow()
    assert w._act_scan_tree.isEnabled() is False


def test_scan_tree_action_enabled_after_tree_load(
    tmp_path: Path,
) -> None:
    tree_path = _seed_tree(tmp_path)
    w = MainWindow()
    w._launcher.load(str(tree_path))
    # The editor's "tree state changed" pass should have enabled
    # the menu item.
    w._refresh_ring_actions()
    assert w._act_scan_tree.isEnabled() is True


# ---------------------------------------------------------------------------
# Slot behaviour
# ---------------------------------------------------------------------------


def test_slot_short_circuits_with_no_tree_loaded() -> None:
    """A defensive guard: invoking the slot with no tree loaded
    must show a status message and bail without raising.  Guards
    against a keyboard shortcut bypassing the menu's
    ``setEnabled(False)``."""
    w = MainWindow()
    w._scan_tree_for_new_tools()
    # No exception; status bar carried the message.
    msg = w.statusBar().currentMessage()
    assert "Load a tree first" in msg


def test_slot_constructs_controller_and_runs_one_shot_prompt(
    tmp_path: Path,
) -> None:
    """With a tree loaded, the slot must construct a
    ``TreeController`` for it and call ``run_one_shot_prompt``."""
    tree_path = _seed_tree(tmp_path)
    w = MainWindow()
    w._launcher.load(str(tree_path))

    # Patch TreeController.run_one_shot_prompt where the slot
    # actually imports it (so the dialog doesn't fire).
    with patch(
        "scriptree.shell.tree_controller.TreeController."
        "run_one_shot_prompt",
    ) as one_shot:
        w._scan_tree_for_new_tools()

    one_shot.assert_called_once()


def test_slot_reloads_tree_after_scan(tmp_path: Path) -> None:
    """The slot must call ``launcher.load`` after the controller
    returns so the editor's view reflects whatever the user
    applied.  Cancel-case is a no-op (the tree file didn't
    change), so the re-load is harmless."""
    tree_path = _seed_tree(tmp_path)
    w = MainWindow()
    w._launcher.load(str(tree_path))

    with patch(
        "scriptree.shell.tree_controller.TreeController."
        "run_one_shot_prompt",
    ), patch.object(w._launcher, "load") as launcher_load:
        w._scan_tree_for_new_tools()

    launcher_load.assert_called_once_with(str(tree_path))


def test_slot_status_bar_finishes_with_complete_message(
    tmp_path: Path,
) -> None:
    """End-state UX: the user gets a status-bar confirmation
    so they know something actually happened."""
    tree_path = _seed_tree(tmp_path)
    w = MainWindow()
    w._launcher.load(str(tree_path))

    with patch(
        "scriptree.shell.tree_controller.TreeController."
        "run_one_shot_prompt",
    ):
        w._scan_tree_for_new_tools()

    assert "Tree scan complete" in w.statusBar().currentMessage()
