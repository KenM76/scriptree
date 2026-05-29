"""Phase-6 regression suite for ``scriptree.shell.tree_controller``.

Pins the orchestration layer's contract:

* Construction loads the tree file (or accepts a pre-loaded one).
* ``refresh_from_sources`` honours the persisted ``update_mode``:
    - ``off`` → no-op
    - ``auto`` → walker + diff + apply silently, then save
    - ``prompt`` → opens diff dialog (tests bypass via mocking the
      dialog class)
* ``refresh_from_sources`` short-circuits when ``enabled`` is False.
* ``run_one_shot_prompt`` forces a prompt regardless of persisted
  mode (the menu's "Auto-add from this folder now" entry).
* ``run_one_shot_prompt`` shows an info dialog when there's
  nothing to show (rather than silently doing nothing).
* ``apply_diff`` mutates ``tree`` correctly without saving (saver
  is the caller's responsibility — matches forest).
* ``attach_to_cell`` installs the menu hook and the controller
  back-reference on the cell.
* ``attach_to_cell`` schedules the chooser dialog when
  ``tree.auto_discover is None``.
* ``attach_to_cell`` skips the chooser when ``auto_discover`` is
  already set, and instead schedules ``refresh_from_sources``.
* The menu builder populates four actions in the right order.

Auto-dismisses ``QMessageBox`` per the standing rule.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMenu, QMessageBox, QWidget,
)

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
from scriptree.core.tree_diff import TreeDiscoveryDiff
from scriptree.core.tree_discover import DiscoveredTreeItem
from scriptree.shell.tree_controller import TreeController


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _mk(path: Path, content: str = "{}") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _seed_tree(tmp_path: Path, *, with_config: bool = True) -> Path:
    """Write a small ``.scriptreetree`` to disk.  Returns the path.

    When ``with_config=True`` the on-disk file gets a non-None
    ``auto_discover`` block so the loader treats it as "user has
    been asked".  The block uses default values for every field
    so tests that don't care about specific settings get the
    standard ``prompt`` behaviour.
    """
    tree = TreeDef(
        name="Test",
        nodes=[
            TreeNode(type="leaf", path="./existing.scriptree"),
        ],
    )
    if with_config:
        # v0.8.0a21+: ``auto_discover=TreeAutoDiscoverConfig()``
        # (any non-None instance) serialises to at least an empty
        # ``auto_discover: {}`` block, which is what makes the
        # loader skip the first-load chooser.  Before the
        # default-equals-omitted fix, a default-mode config
        # would silently round-trip back to ``None``, causing
        # the chooser to re-fire on every load.
        tree.auto_discover = TreeAutoDiscoverConfig()
    path = tmp_path / "test.scriptreetree"
    save_tree(tree, path)
    return path


# ============================================================================
# Construction
# ============================================================================


class TestConstruction:
    def test_loads_tree_from_disk(self, tmp_path: Path) -> None:
        tree_path = _seed_tree(tmp_path)
        ctl = TreeController(tree_path)
        assert ctl.tree.name == "Test"
        assert ctl.tree_file == str(tree_path.resolve())
        # parent_widget is unset until attach_to_cell runs.
        assert ctl.parent_widget is None

    def test_accepts_preloaded_tree(self, tmp_path: Path) -> None:
        """The optional ``tree=`` parameter lets the caller skip
        the disk read (useful when the cell already loaded the
        catalog for its own purposes)."""
        tree_path = tmp_path / "preloaded.scriptreetree"
        # Note: file doesn't have to exist on disk -- the path is
        # just metadata when we pass tree=.
        preloaded = TreeDef(name="Pre", nodes=[])
        ctl = TreeController(tree_path, tree=preloaded)
        assert ctl.tree is preloaded


# ============================================================================
# refresh_from_sources -- mode dispatch
# ============================================================================


class TestRefreshDispatch:
    def test_off_mode_no_op(self, tmp_path: Path) -> None:
        tree_path = _seed_tree(tmp_path)
        ctl = TreeController(tree_path)
        ctl.tree.auto_discover = TreeAutoDiscoverConfig(update_mode="off")
        # Create a new tool that would otherwise show up.
        _mk(tmp_path / "new.scriptree")

        with patch.object(
            ctl, "_show_diff_dialog",
        ) as show, patch.object(ctl, "save") as save:
            ctl.refresh_from_sources()

        show.assert_not_called()
        save.assert_not_called()

    def test_auto_mode_applies_silently_and_saves(
        self, tmp_path: Path,
    ) -> None:
        tree_path = _seed_tree(tmp_path)
        ctl = TreeController(tree_path)
        ctl.tree.auto_discover = TreeAutoDiscoverConfig(update_mode="auto")
        _mk(tmp_path / "new-in-auto.scriptree")

        with patch.object(ctl, "_show_diff_dialog") as show:
            ctl.refresh_from_sources()

        show.assert_not_called()
        # The new tool was added.
        leaves = {
            n.path for n in ctl.tree.nodes
            if n.type == "leaf" and n.path
        }
        assert "./new-in-auto.scriptree" in leaves
        # Saved to disk.
        from scriptree.core.io import load_tree
        reloaded = load_tree(tree_path)
        assert any(
            n.path == "./new-in-auto.scriptree"
            for n in reloaded.nodes
            if n.type == "leaf"
        )

    def test_prompt_mode_opens_dialog(self, tmp_path: Path) -> None:
        tree_path = _seed_tree(tmp_path)
        ctl = TreeController(tree_path)
        # default mode is "prompt"
        _mk(tmp_path / "new-for-prompt.scriptree")

        with patch.object(ctl, "_show_diff_dialog") as show:
            ctl.refresh_from_sources()

        show.assert_called_once()
        diff_arg = show.call_args.args[0]
        assert isinstance(diff_arg, TreeDiscoveryDiff)
        assert len(diff_arg.added) == 1

    def test_disabled_short_circuits(self, tmp_path: Path) -> None:
        tree_path = _seed_tree(tmp_path)
        ctl = TreeController(tree_path)
        ctl.tree.auto_discover = TreeAutoDiscoverConfig(
            enabled=False, update_mode="prompt",
        )
        _mk(tmp_path / "would-show.scriptree")

        with patch.object(ctl, "_show_diff_dialog") as show:
            ctl.refresh_from_sources()

        show.assert_not_called()

    def test_empty_diff_does_not_open_dialog(
        self, tmp_path: Path,
    ) -> None:
        """When the walker finds nothing new, the prompt path
        must NOT open an empty dialog (annoying UX)."""
        tree_path = _seed_tree(tmp_path)
        ctl = TreeController(tree_path)
        _mk(tmp_path / "existing.scriptree")  # already in tree

        with patch.object(ctl, "_show_diff_dialog") as show:
            ctl.refresh_from_sources()

        show.assert_not_called()


# ============================================================================
# run_one_shot_prompt -- the "Auto-add now" menu shortcut
# ============================================================================


class TestOneShotPrompt:
    def test_forces_prompt_regardless_of_mode(
        self, tmp_path: Path,
    ) -> None:
        """User clicks 'Auto-add now' on a tree configured for
        ``mode=off``.  The walker + diff dialog should still
        run -- it's an explicit user action."""
        tree_path = _seed_tree(tmp_path)
        ctl = TreeController(tree_path)
        ctl.tree.auto_discover = TreeAutoDiscoverConfig(update_mode="off")
        _mk(tmp_path / "found.scriptree")

        with patch.object(ctl, "_show_diff_dialog") as show:
            ctl.run_one_shot_prompt()

        show.assert_called_once()

    def test_shows_info_when_nothing_to_add(
        self, tmp_path: Path,
    ) -> None:
        """When the one-shot scan finds nothing, the user gets
        an info dialog instead of silent no-op (which would feel
        broken)."""
        tree_path = _seed_tree(tmp_path)
        ctl = TreeController(tree_path)
        ctl.parent_widget = QWidget()  # so the info dialog can parent
        _mk(tmp_path / "existing.scriptree")  # already in tree

        info_called: list[bool] = []
        original = QMessageBox.information

        def _record(*a, **kw):  # type: ignore[no-untyped-def]
            info_called.append(True)
            return QMessageBox.StandardButton.Ok

        QMessageBox.information = staticmethod(_record)  # type: ignore[assignment]
        try:
            ctl.run_one_shot_prompt()
        finally:
            QMessageBox.information = staticmethod(original)  # type: ignore[assignment]

        assert info_called == [True]


# ============================================================================
# apply_diff
# ============================================================================


class TestApplyDiff:
    def test_apply_diff_mutates_tree(self, tmp_path: Path) -> None:
        tree_path = _seed_tree(tmp_path)
        ctl = TreeController(tree_path)
        new_tool = _mk(tmp_path / "new.scriptree")

        item = DiscoveredTreeItem(
            abs_path=str(new_tool.resolve()),
            rel_path="./new.scriptree",
            kind="tool",
        )
        diff = TreeDiscoveryDiff(added=[item])

        ctl.apply_diff(
            diff,
            accepted_added=[item],
            accepted_removed=[],
            accepted_reincluded=[],
        )

        leaves = {
            n.path for n in ctl.tree.nodes
            if n.type == "leaf" and n.path
        }
        assert "./new.scriptree" in leaves

    def test_apply_diff_does_not_save(self, tmp_path: Path) -> None:
        """``apply_diff`` mutates the in-memory tree; ``save`` is
        the caller's responsibility (so auto-mode can batch).
        Confirm that calling apply_diff alone doesn't touch disk."""
        tree_path = _seed_tree(tmp_path)
        ctl = TreeController(tree_path)
        original_bytes = tree_path.read_bytes()
        new_tool = _mk(tmp_path / "new2.scriptree")
        item = DiscoveredTreeItem(
            abs_path=str(new_tool.resolve()),
            rel_path="./new2.scriptree",
            kind="tool",
        )

        ctl.apply_diff(
            TreeDiscoveryDiff(added=[item]),
            accepted_added=[item],
            accepted_removed=[],
            accepted_reincluded=[],
        )

        # Disk content is unchanged; save() was never called.
        assert tree_path.read_bytes() == original_bytes


# ============================================================================
# attach_to_cell
# ============================================================================


class _FakeCell(QWidget):
    """Mimics the minimal CellWindow surface the controller uses."""


class TestAttachToCell:
    def test_installs_menu_hook_and_back_reference(
        self, tmp_path: Path,
    ) -> None:
        tree_path = _seed_tree(tmp_path)
        ctl = TreeController(tree_path)
        cell = _FakeCell()

        # Suppress the auto-fired refresh so we can assert the
        # attachment cleanly.
        ctl.attach_to_cell(cell, fire_first_load_chooser=False)

        assert getattr(cell, "_tree_controller", None) is ctl
        # Bound-method comparison: two `getattr` calls on the same
        # instance produce distinct bound-method objects (`is`
        # fails); `==` compares the underlying function + self.
        assert getattr(cell, "_tree_menu_extension", None) == ctl._populate_tree_menu
        assert ctl.parent_widget is cell

    def test_schedules_chooser_when_auto_discover_none(
        self, tmp_path: Path,
    ) -> None:
        """Legacy trees (no ``auto_discover`` block) trigger the
        first-load chooser dialog on the next event tick."""
        # Build a tree explicitly with auto_discover=None.
        tree = TreeDef(name="Legacy")
        tree.auto_discover = None
        tree_path = tmp_path / "legacy.scriptreetree"
        save_tree(tree, tree_path)

        ctl = TreeController(tree_path)
        cell = _FakeCell()

        with patch.object(ctl, "_show_first_load_chooser") as chooser:
            ctl.attach_to_cell(cell)  # fire_first_load_chooser defaults True
            # Chooser is scheduled but not yet called.
            assert chooser.call_count == 0
            _app.processEvents()
            assert chooser.call_count == 1

    def test_schedules_refresh_when_already_configured(
        self, tmp_path: Path,
    ) -> None:
        """Trees with an existing ``auto_discover`` block skip the
        chooser and go straight to a refresh per the chosen mode."""
        tree_path = _seed_tree(tmp_path)  # default mode='prompt'
        ctl = TreeController(tree_path)
        cell = _FakeCell()

        with patch.object(ctl, "refresh_from_sources") as refresh, \
                patch.object(ctl, "_show_first_load_chooser") as chooser:
            ctl.attach_to_cell(cell)
            _app.processEvents()

        chooser.assert_not_called()
        refresh.assert_called_once()


# ============================================================================
# Menu builder
# ============================================================================


class TestMenuBuilder:
    def test_populate_tree_menu_adds_submenu(
        self, tmp_path: Path,
    ) -> None:
        tree_path = _seed_tree(tmp_path)
        ctl = TreeController(tree_path)
        ctl.parent_widget = QWidget()

        outer = QMenu()
        ctl._populate_tree_menu(outer)

        # The submenu is the first item.
        actions = outer.actions()
        assert len(actions) == 1
        sub = actions[0].menu()
        assert sub is not None
        sub_labels = [a.text() for a in sub.actions() if a.text()]
        # Expected entries (order matters for the UX contract).
        assert sub_labels[0] == "Refresh from sources"
        assert sub_labels[1] == "Auto-add from this folder now"
        # Index 2 is the separator (text is empty); the actions
        # filter above already drops it.  Items 2 and 3 are the
        # remaining named entries.
        assert "Tree settings…" in sub_labels
        assert "Excluded items…" in sub_labels
