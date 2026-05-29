"""Phase-4/5/7 regression suite for tree dialogs.

The dialogs in ``scriptree.ui.tree_dialogs`` are exercised by
constructing them against a fake controller and either:

* calling the slot the Apply / Save button is wired to directly
  (``_apply`` / ``_save`` / ``_save_and_run``), to verify the
  controller callbacks land with the expected arguments and the
  tree is in the expected state, or
* setting widget state programmatically (``setChecked`` on radio
  buttons, ``setCheckState`` on tree-widget rows) and then
  invoking the slot.

This is the same testing pattern the rest of the codebase uses
for Qt-bound logic: stay below the event loop to keep tests fast
(<1s each) and deterministic.

Auto-dismisses ``QMessageBox`` per the standing rule.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)

from scriptree.core.discovery import TreeAutoDiscoverConfig
from scriptree.core.model import TreeDef, TreeNode
from scriptree.core.tree_diff import (
    TreeDiscoveryDiff,
    apply_diff_to_tree,
)
from scriptree.core.tree_discover import DiscoveredTreeItem
from scriptree.ui.tree_dialogs import (
    ChooseUpdateModeDialog,
    TreeSettingsDialog,
    TreeUpdateDiffDialog,
)


# ----------------------------------------------------------------------------
# Fake controller — matches the _TreeController protocol.
# ----------------------------------------------------------------------------


class _FakeController:
    """In-memory stand-in for the Phase-6 TreeController.

    Mirrors the protocol used by the dialogs.  Records calls so
    tests can assert what the dialog did.
    """

    def __init__(self, tree: TreeDef, tree_file: str | Path) -> None:
        self.tree = tree
        self.tree_file = str(tree_file)
        self.parent_widget = None
        self.save_calls: int = 0
        self.refresh_calls: int = 0
        self.last_apply_args: dict[str, Any] | None = None

    def save(self) -> None:
        self.save_calls += 1

    def apply_diff(
        self,
        diff: TreeDiscoveryDiff,
        *,
        accepted_added,
        accepted_removed,
        accepted_reincluded,
    ) -> None:
        # Record the call so tests can verify what was passed AND
        # also perform the actual mutation so downstream tree
        # state is correct.
        self.last_apply_args = {
            "added": list(accepted_added),
            "removed": list(accepted_removed),
            "reincluded": list(accepted_reincluded),
        }
        apply_diff_to_tree(
            self.tree,
            self.tree_file,
            accepted_adds=list(accepted_added),
            accepted_removes=list(accepted_removed),
            accepted_reincludes=list(accepted_reincluded),
        )

    def refresh_from_sources(self) -> None:
        self.refresh_calls += 1


def _disc(abs_path: Path, rel_path: str, kind: str = "tool") -> DiscoveredTreeItem:
    return DiscoveredTreeItem(
        abs_path=str(abs_path.resolve()),
        rel_path=rel_path,
        kind=kind,  # type: ignore[arg-type]
    )


def _mk(p: Path, content: str = "{}") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ============================================================================
# TreeUpdateDiffDialog
# ============================================================================


class TestUpdateDiffDialogAccept:
    """The Apply path filters checked rows and calls the
    controller correctly."""

    def test_all_checked_default_added_section_applies_all(
        self, tmp_path: Path,
    ) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tree = TreeDef(name="t")
        ctl = _FakeController(tree, tree_file)
        new_tool = _mk(tmp_path / "new.scriptree")
        diff = TreeDiscoveryDiff(
            added=[_disc(new_tool, "./new.scriptree")],
        )

        dlg = TreeUpdateDiffDialog(ctl, diff)
        # Don't show; the API path runs without exec.
        dlg._apply()

        assert ctl.last_apply_args is not None
        assert len(ctl.last_apply_args["added"]) == 1
        # save() must be called as part of Apply.
        assert ctl.save_calls == 1
        # The tree was mutated through the fake's apply_diff
        # implementation.
        assert any(
            n.type == "leaf" and n.path == "./new.scriptree"
            for n in tree.nodes
        )

    def test_unchecked_row_is_skipped(self, tmp_path: Path) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tree = TreeDef(name="t")
        ctl = _FakeController(tree, tree_file)
        new_tool = _mk(tmp_path / "skip.scriptree")
        diff = TreeDiscoveryDiff(
            added=[_disc(new_tool, "./skip.scriptree")],
        )

        dlg = TreeUpdateDiffDialog(ctl, diff)
        # Untick the one row.
        for row, _ in dlg._added_rows:
            row.setCheckState(0, Qt.CheckState.Unchecked)
        dlg._apply()

        assert ctl.last_apply_args is not None
        assert ctl.last_apply_args["added"] == []
        assert tree.nodes == []  # nothing inserted

    def test_previously_excluded_defaults_unchecked(
        self, tmp_path: Path,
    ) -> None:
        """The previously-excluded section MUST start unticked --
        the user previously said no, we don't undo that silently."""
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tree = TreeDef(name="t", excluded=["./old.scriptree"])
        ctl = _FakeController(tree, tree_file)
        old_tool = _mk(tmp_path / "old.scriptree")
        diff = TreeDiscoveryDiff(
            previously_excluded=[_disc(old_tool, "./old.scriptree")],
        )

        dlg = TreeUpdateDiffDialog(ctl, diff)
        # Verify the row is unchecked by default.
        assert len(dlg._reincl_rows) == 1
        row, _ = dlg._reincl_rows[0]
        assert row.checkState(0) == Qt.CheckState.Unchecked

        # Apply without ticking it.
        dlg._apply()
        assert ctl.last_apply_args is not None
        assert ctl.last_apply_args["reincluded"] == []
        # Excluded list NOT modified.
        assert tree.excluded == ["./old.scriptree"]

    def test_removed_section_default_checked(
        self, tmp_path: Path,
    ) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        # Note: missing.scriptree NOT created on disk -- it's a
        # leaf pointing at a vanished file.
        gone_leaf = TreeNode(type="leaf", path="./missing.scriptree")
        tree = TreeDef(name="t", nodes=[gone_leaf])
        ctl = _FakeController(tree, tree_file)
        diff = TreeDiscoveryDiff(removed=[gone_leaf])

        dlg = TreeUpdateDiffDialog(ctl, diff)
        assert len(dlg._removed_rows) == 1
        row, _ = dlg._removed_rows[0]
        assert row.checkState(0) == Qt.CheckState.Checked, (
            "Removed-section row should default to checked -- "
            "a leaf with no file is almost always meant to go."
        )

        dlg._apply()
        # Leaf was dropped through the fake's apply_diff.
        assert tree.nodes == []


class TestUpdateDiffDialogConstruction:
    """The dialog handles empty / partial diffs gracefully."""

    def test_empty_diff_constructs(self, tmp_path: Path) -> None:
        """A controller might call the dialog on an empty diff
        (it shouldn't, but defensive); we must not crash."""
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tree = TreeDef(name="t")
        ctl = _FakeController(tree, tree_file)
        diff = TreeDiscoveryDiff()
        # Should not raise.
        dlg = TreeUpdateDiffDialog(ctl, diff)
        # _apply on empty diff -> empty args.
        dlg._apply()
        assert ctl.last_apply_args == {
            "added": [], "removed": [], "reincluded": [],
        }

    def test_only_removed_section_present(self, tmp_path: Path) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        leaf = TreeNode(type="leaf", path="./gone.scriptree")
        tree = TreeDef(name="t", nodes=[leaf])
        ctl = _FakeController(tree, tree_file)
        diff = TreeDiscoveryDiff(removed=[leaf])

        dlg = TreeUpdateDiffDialog(ctl, diff)
        # Only the removed section's rows.
        assert dlg._added_rows == []
        assert dlg._reincl_rows == []
        assert len(dlg._removed_rows) == 1


# ============================================================================
# TreeSettingsDialog
# ============================================================================


class TestSettingsDialog:
    def test_initial_state_reflects_existing_config(
        self, tmp_path: Path,
    ) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tree = TreeDef(
            name="t",
            auto_discover=TreeAutoDiscoverConfig(
                enabled=False,
                roots=["./alpha", "./beta"],
                include_sibling_trees=False,
                update_mode="auto",
            ),
        )
        ctl = _FakeController(tree, tree_file)

        dlg = TreeSettingsDialog(ctl)
        assert dlg._enabled_cb.isChecked() is False
        assert dlg._roots.values() == ["./alpha", "./beta"]
        assert dlg._sib.value() is False
        assert dlg._mode.value() == "auto"

    def test_initial_state_from_none_auto_discover(
        self, tmp_path: Path,
    ) -> None:
        """When ``tree.auto_discover is None``, the dialog seeds
        from defaults so the user has sensible widgets to edit."""
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tree = TreeDef(name="t", auto_discover=None)
        ctl = _FakeController(tree, tree_file)

        dlg = TreeSettingsDialog(ctl)
        assert dlg._enabled_cb.isChecked() is True  # default
        assert dlg._roots.values() == ["."]
        assert dlg._sib.value() is True
        assert dlg._mode.value() == "prompt"

    def test_save_persists_to_tree_and_calls_controller(
        self, tmp_path: Path,
    ) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tree = TreeDef(name="t")  # auto_discover=None
        ctl = _FakeController(tree, tree_file)

        dlg = TreeSettingsDialog(ctl)
        # Mutate widgets.
        dlg._enabled_cb.setChecked(False)
        dlg._sib._cb.setChecked(False)
        dlg._mode._rb_off.setChecked(True)

        dlg._save()

        assert tree.auto_discover is not None
        assert tree.auto_discover.enabled is False
        assert tree.auto_discover.include_sibling_trees is False
        assert tree.auto_discover.update_mode == "off"
        assert ctl.save_calls == 1

    def test_save_and_run_schedules_refresh(
        self, tmp_path: Path,
    ) -> None:
        """The 'Save && Run discovery' path saves THEN schedules
        a refresh on the next event tick (via QTimer.singleShot)."""
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tree = TreeDef(name="t")
        ctl = _FakeController(tree, tree_file)

        dlg = TreeSettingsDialog(ctl)
        dlg._save_and_run()

        # Save happened synchronously.
        assert ctl.save_calls == 1
        # Refresh was scheduled but hasn't fired yet (we haven't
        # spun the event loop).
        assert ctl.refresh_calls == 0
        # Pump the event loop once -- the singleShot fires.
        _app.processEvents()
        assert ctl.refresh_calls == 1


# ============================================================================
# ChooseUpdateModeDialog
# ============================================================================


class TestChooseUpdateMode:
    def test_default_is_prompt(self) -> None:
        dlg = ChooseUpdateModeDialog("MyTree")
        # Before any user interaction, the default radio is set.
        assert dlg._rb_prompt.isChecked()

    def test_picks_prompt_when_ok_clicked(self) -> None:
        dlg = ChooseUpdateModeDialog("MyTree")
        dlg._on_ok()
        assert dlg.chosen == "prompt"

    def test_picks_auto(self) -> None:
        dlg = ChooseUpdateModeDialog("MyTree")
        dlg._rb_auto.setChecked(True)
        dlg._on_ok()
        assert dlg.chosen == "auto"

    def test_picks_off(self) -> None:
        dlg = ChooseUpdateModeDialog("MyTree")
        dlg._rb_off.setChecked(True)
        dlg._on_ok()
        assert dlg.chosen == "off"

    def test_chosen_default_when_never_pressed_ok(self) -> None:
        """If the dialog is destroyed without ever firing _on_ok
        (e.g. window close), ``chosen`` falls back to 'prompt'
        rather than crashing the controller."""
        dlg = ChooseUpdateModeDialog("MyTree")
        # No _on_ok call.
        assert dlg.chosen == "prompt"
