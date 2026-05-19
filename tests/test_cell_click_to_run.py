"""Tests for the v0.3.5 cell click-to-run feature.

Coverage:

1. Schema round-trip — ``cell_click_action`` / ``cell_click_run_mode``
   on ``ToolDef`` and ``TreeDef`` survive ``save_*`` / ``load_*``.
2. ``cell_metadata.read_for`` / ``write_for`` round-trip and coerce.
3. ``click_to_run.collect_leaf_tool_paths`` walks tree + folders.
4. ``run_catalog_on_click`` dispatch:
   - ``.scriptree``  → single ``launch_tool`` with ``run_on_open=True``.
   - ``.scriptreetree`` parallel → one ``launch_tool`` per leaf.
   - ``.scriptreetree`` sequential → spawn first; subsequent only
     after previous Popen exits (mocked).
5. ``CellWindow._read_click_action`` honours the
   ``cell_click_to_run`` capability gate.
6. Settings dialog dropdowns:
   - Initial state matches the catalog.
   - Toggling persists via ``write_for``.
   - Both controls disabled when ``cell_click_to_run`` is denied.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)


from scriptree.core.io import load_tool, load_tree, save_tool, save_tree
from scriptree.core.model import (
    ParamDef, ParamType, ToolDef, TreeDef, TreeNode, Widget,
)
from scriptree.core.permissions import PermissionSet


def _ps(**caps: bool) -> PermissionSet:
    return PermissionSet(allowed=dict(caps))


def _patch_perms(ps: PermissionSet):
    return patch(
        "scriptree.core.permissions.get_app_permissions",
        return_value=ps,
    )


def _tool() -> ToolDef:
    return ToolDef(
        name="x", executable="python",
        params=[
            ParamDef(
                id="p", label="P",
                type=ParamType.PATH, widget=Widget.FILE,
            ),
        ],
    )


# ===========================================================================
# 1. ToolDef / TreeDef round-trip
# ===========================================================================

class TestSchemaRoundTrip:

    def test_tool_default_click_fields(self) -> None:
        t = ToolDef(name="x", executable="python")
        assert t.cell_click_action == "menu"
        assert t.cell_click_run_mode == "sequential"

    def test_tree_default_click_fields(self) -> None:
        tree = TreeDef(name="t", nodes=[])
        assert tree.cell_click_action == "menu"
        assert tree.cell_click_run_mode == "sequential"

    def test_tool_round_trip_default_omits_fields(
        self, tmp_path: Path,
    ) -> None:
        """Legacy round-trip: defaults stay out of the JSON so v0.3.4
        files remain byte-identical when re-saved."""
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        on_disk = json.loads(p.read_text(encoding="utf-8"))
        cell_obj = on_disk.get("cell", {})
        assert "click_action" not in cell_obj
        assert "click_run_mode" not in cell_obj

    def test_tool_round_trip_run_mode_preserved(
        self, tmp_path: Path,
    ) -> None:
        t = _tool()
        t.cell_click_action = "run"
        t.cell_click_run_mode = "parallel"
        p = tmp_path / "demo.scriptree"
        save_tool(t, p)
        on_disk = json.loads(p.read_text(encoding="utf-8"))
        assert on_disk["cell"]["click_action"] == "run"
        assert on_disk["cell"]["click_run_mode"] == "parallel"
        loaded = load_tool(p)
        assert loaded.cell_click_action == "run"
        assert loaded.cell_click_run_mode == "parallel"

    def test_tree_round_trip_run_mode_preserved(
        self, tmp_path: Path,
    ) -> None:
        leaf = tmp_path / "leaf.scriptree"
        save_tool(_tool(), leaf)
        tree = TreeDef(
            name="t",
            nodes=[TreeNode(type="leaf", path=str(leaf))],
            cell_click_action="run",
            cell_click_run_mode="parallel",
        )
        p = tmp_path / "demo.scriptreetree"
        save_tree(tree, p)
        loaded = load_tree(p)
        assert loaded.cell_click_action == "run"
        assert loaded.cell_click_run_mode == "parallel"


# ===========================================================================
# 2. cell_metadata.read_for / write_for
# ===========================================================================

class TestCellMetadataClickFields:

    def test_read_for_default_when_unset(self, tmp_path: Path) -> None:
        from scriptree.core.cell_metadata import read_for
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        md = read_for(p)
        assert md.click_action == "menu"
        assert md.click_run_mode == "sequential"

    def test_write_for_persists_run_mode(self, tmp_path: Path) -> None:
        from scriptree.core.cell_metadata import read_for, write_for
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        write_for(p, click_action="run", click_run_mode="parallel")
        md = read_for(p)
        assert md.click_action == "run"
        assert md.click_run_mode == "parallel"

    def test_write_for_coerces_invalid_action(
        self, tmp_path: Path,
    ) -> None:
        """Unknown action values fall back to the safe default
        ('menu') so a typo in the JSON can't unlock auto-run."""
        from scriptree.core.cell_metadata import read_for, write_for
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        write_for(p, click_action="bogus")
        md = read_for(p)
        assert md.click_action == "menu"

    def test_write_for_coerces_invalid_run_mode(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.core.cell_metadata import read_for, write_for
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        write_for(p, click_run_mode="batch")
        md = read_for(p)
        assert md.click_run_mode == "sequential"


# ===========================================================================
# 3. click_to_run.collect_leaf_tool_paths
# ===========================================================================

class TestCollectLeafToolPaths:

    def test_walks_top_level_leaves(self, tmp_path: Path) -> None:
        from scriptree.shell.click_to_run import collect_leaf_tool_paths
        a = tmp_path / "a.scriptree"
        b = tmp_path / "b.scriptree"
        save_tool(_tool(), a)
        save_tool(_tool(), b)
        tree = TreeDef(name="t", nodes=[
            TreeNode(type="leaf", path=str(a)),
            TreeNode(type="leaf", path=str(b)),
        ])
        tp = tmp_path / "tree.scriptreetree"
        save_tree(tree, tp)
        leaves = collect_leaf_tool_paths(tp)
        assert leaves == [str(a.resolve()), str(b.resolve())]

    def test_recurses_through_folders(self, tmp_path: Path) -> None:
        from scriptree.shell.click_to_run import collect_leaf_tool_paths
        a = tmp_path / "a.scriptree"
        b = tmp_path / "b.scriptree"
        save_tool(_tool(), a)
        save_tool(_tool(), b)
        tree = TreeDef(name="t", nodes=[
            TreeNode(type="folder", name="g", children=[
                TreeNode(type="leaf", path=str(a)),
            ]),
            TreeNode(type="leaf", path=str(b)),
        ])
        tp = tmp_path / "tree.scriptreetree"
        save_tree(tree, tp)
        leaves = collect_leaf_tool_paths(tp)
        assert leaves == [str(a.resolve()), str(b.resolve())]

    def test_resolves_relative_leaf_paths(self, tmp_path: Path) -> None:
        from scriptree.shell.click_to_run import collect_leaf_tool_paths
        leaf = tmp_path / "rel.scriptree"
        save_tool(_tool(), leaf)
        tree = TreeDef(name="t", nodes=[
            TreeNode(type="leaf", path="./rel.scriptree"),
        ])
        tp = tmp_path / "tree.scriptreetree"
        save_tree(tree, tp)
        leaves = collect_leaf_tool_paths(tp)
        # Forward-slash check across platforms: just compare
        # canonicalised forms.
        assert Path(leaves[0]).resolve() == leaf.resolve()

    def test_missing_tree_raises(self, tmp_path: Path) -> None:
        from scriptree.shell.click_to_run import collect_leaf_tool_paths
        with pytest.raises(FileNotFoundError):
            collect_leaf_tool_paths(tmp_path / "absent.scriptreetree")


# ===========================================================================
# 4. run_catalog_on_click dispatch
# ===========================================================================

class TestRunCatalogDispatch:

    def test_single_scriptree_launches_one_tool(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.shell import click_to_run
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        with patch.object(click_to_run, "launch_tool") as m_launch:
            click_to_run.run_catalog_on_click(p, run_mode="sequential")
        m_launch.assert_called_once()
        # run_on_open=True must be passed for the V1 -run flag.
        kwargs = m_launch.call_args.kwargs
        assert kwargs.get("run_on_open") is True

    def test_tree_parallel_launches_every_leaf(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.shell import click_to_run
        a = tmp_path / "a.scriptree"
        b = tmp_path / "b.scriptree"
        c = tmp_path / "c.scriptree"
        for x in (a, b, c):
            save_tool(_tool(), x)
        tree = TreeDef(name="t", nodes=[
            TreeNode(type="leaf", path=str(a)),
            TreeNode(type="leaf", path=str(b)),
            TreeNode(type="leaf", path=str(c)),
        ])
        tp = tmp_path / "tree.scriptreetree"
        save_tree(tree, tp)
        with patch.object(click_to_run, "launch_tool") as m_launch:
            click_to_run.run_catalog_on_click(tp, run_mode="parallel")
        # All 3 spawned at once, all with run_on_open=True.
        assert m_launch.call_count == 3
        for call in m_launch.call_args_list:
            assert call.kwargs.get("run_on_open") is True

    def test_tree_sequential_advances_on_proc_exit(
        self, tmp_path: Path,
    ) -> None:
        """Sequential mode: only the first leaf spawns immediately;
        the next spawns when the first's Popen exits."""
        from scriptree.shell import click_to_run
        a = tmp_path / "a.scriptree"
        b = tmp_path / "b.scriptree"
        for x in (a, b):
            save_tool(_tool(), x)
        tree = TreeDef(name="t", nodes=[
            TreeNode(type="leaf", path=str(a)),
            TreeNode(type="leaf", path=str(b)),
        ])
        tp = tmp_path / "tree.scriptreetree"
        save_tree(tree, tp)

        # Mock Popens that exit immediately so the sync-wait fallback
        # in click_to_run._schedule_poll runs fast.
        spawn_calls: list[str] = []
        def fake_spawn(leaf_path: str):
            spawn_calls.append(leaf_path)
            m = MagicMock()
            m.poll.return_value = 0  # already exited
            m.wait.return_value = 0
            m.returncode = 0
            m.pid = 12345
            return m

        # Disable the QTimer polling so we hit the synchronous-wait
        # fallback (which calls proc.wait() then advances).
        click_to_run._reset_inflight()
        with patch.object(click_to_run, "_spawn_v1_standalone", side_effect=fake_spawn), \
             patch.dict(sys.modules, {"PySide6.QtCore": None}):
            click_to_run.run_catalog_on_click(tp, run_mode="sequential")

        # Both leaves were spawned (first immediately, second after
        # the first's mock-exited Popen poll fired).
        assert len(spawn_calls) == 2
        assert Path(spawn_calls[0]).name == "a.scriptree"
        assert Path(spawn_calls[1]).name == "b.scriptree"
        # In-flight registry cleaned up.
        assert click_to_run._inflight_count() == 0

    def test_unknown_extension_logs_and_does_nothing(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.shell import click_to_run
        p = tmp_path / "demo.txt"
        p.write_text("hi", encoding="utf-8")
        with patch.object(click_to_run, "launch_tool") as m_launch:
            click_to_run.run_catalog_on_click(p, run_mode="sequential")
        m_launch.assert_not_called()


# ===========================================================================
# 5. CellWindow._read_click_action capability gate
# ===========================================================================

class TestCellWindowReadClickAction:

    def _spawn_cell_with_catalog(
        self, tmp_path: Path, *, action: str, run_mode: str,
    ):
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        cat = tmp_path / "demo.scriptree"
        t = _tool()
        t.cell_click_action = action
        t.cell_click_run_mode = run_mode
        save_tool(t, cat)

        cell = CellWindow(load_branding())
        cell._catalog_path = str(cat)
        return cell

    def test_returns_run_when_capability_granted_and_catalog_set(
        self, tmp_path: Path,
    ) -> None:
        cell = self._spawn_cell_with_catalog(
            tmp_path, action="run", run_mode="parallel",
        )
        with _patch_perms(_ps(cell_click_to_run=True)):
            assert cell._read_click_action() == "run"
            assert cell._read_click_run_mode() == "parallel"
        cell.close()

    def test_falls_back_to_menu_when_capability_denied(
        self, tmp_path: Path,
    ) -> None:
        cell = self._spawn_cell_with_catalog(
            tmp_path, action="run", run_mode="parallel",
        )
        with _patch_perms(_ps(cell_click_to_run=False)):
            assert cell._read_click_action() == "menu"
        cell.close()

    def test_unbound_cell_returns_menu_regardless(self) -> None:
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow
        cell = CellWindow(load_branding())
        with _patch_perms(_ps(cell_click_to_run=True)):
            assert cell._read_click_action() == "menu"
        cell.close()


# ===========================================================================
# 6. Settings-dialog dropdowns
# ===========================================================================

class TestSettingsDialogDropdowns:

    def _open_settings(self, tmp_path: Path, action: str = "menu"):
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow, SettingsDialog

        cat = tmp_path / "demo.scriptree"
        t = _tool()
        t.cell_click_action = action
        save_tool(t, cat)

        cell = CellWindow(load_branding())
        cell._catalog_path = str(cat)
        dlg = SettingsDialog(cell)
        return cell, dlg

    def test_initial_action_matches_catalog(self, tmp_path: Path) -> None:
        with _patch_perms(_ps(cell_click_to_run=True)):
            cell, dlg = self._open_settings(tmp_path, action="run")
        assert dlg._click_action_combo.currentData() == "run"
        dlg.close()
        cell.close()

    def test_dropdowns_disabled_when_capability_denied(
        self, tmp_path: Path,
    ) -> None:
        with _patch_perms(_ps(cell_click_to_run=False)):
            cell, dlg = self._open_settings(tmp_path)
        assert not dlg._click_action_combo.isEnabled()
        assert not dlg._click_run_mode_combo.isEnabled()
        dlg.close()
        cell.close()

    def test_run_mode_disabled_when_action_is_menu(
        self, tmp_path: Path,
    ) -> None:
        with _patch_perms(_ps(cell_click_to_run=True)):
            cell, dlg = self._open_settings(tmp_path, action="menu")
        # Action "menu" → run_mode dropdown disabled.
        assert not dlg._click_run_mode_combo.isEnabled()
        dlg.close()
        cell.close()

    def test_changing_action_persists_to_catalog(
        self, tmp_path: Path,
    ) -> None:
        with _patch_perms(_ps(cell_click_to_run=True)):
            cell, dlg = self._open_settings(tmp_path, action="menu")
            # Switch to "run" via the combo.
            idx = dlg._click_action_combo.findData("run")
            dlg._click_action_combo.setCurrentIndex(idx)
        from scriptree.core.cell_metadata import read_for
        md = read_for(cell._catalog_path)
        assert md.click_action == "run"
        dlg.close()
        cell.close()
