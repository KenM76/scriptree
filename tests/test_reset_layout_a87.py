"""Tests for the v0.8.0a87 'Reset layout' action.

Both the single-tool standalone window and the editor MainWindow snapshot their
default QtAds dock arrangement at construction and expose a 'Reset layout' menu
action that restores it — the recovery path for a saved/rearranged layout that
collapsed the docks (the DXF Export V2 'command merged with form' symptom).

These tests pin: the default snapshot is captured, a 'Reset layout' action
exists in the View menu, and invoking the reset runs without error and keeps the
docks present.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Ok)  # type: ignore[assignment]
QMessageBox.information = staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Ok)  # type: ignore[assignment]
QMessageBox.question = staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Ok)  # type: ignore[assignment]

from scriptree.core.io import save_tool
from scriptree.core.model import ParamDef, ToolDef


def _saved_tool(tmp_path: Path) -> tuple[ToolDef, str]:
    tool = ToolDef(
        name="ResetLayoutTool",
        executable="echo",
        argument_template=["{p0}"],
        params=[ParamDef(id="p0", label="P0", default="v0")],
    )
    p = tmp_path / "reset.scriptree"
    save_tool(tool, p)
    return tool, str(p)


def _find_action(menubar, text: str):
    """Find a top-level-or-submenu QAction whose text matches *text*."""
    for top in menubar.actions():
        m = top.menu()
        if m is None:
            continue
        for act in m.actions():
            if act.text() == text:
                return act
    return None


def test_standalone_snapshots_default_and_exposes_reset(tmp_path: Path) -> None:
    from scriptree.ui.standalone_window import StandaloneWindow
    tool, p = _saved_tool(tmp_path)
    win = StandaloneWindow.from_tool(tool, p)
    try:
        # Default arrangement snapshotted at construction.
        assert getattr(win, "_default_layout_state", None), (
            "from_tool must snapshot the default dock layout for reset"
        )
        # The single-tool window now has a View ▸ Reset layout action.
        act = _find_action(win.menuBar(), "Reset layout")
        assert act is not None, "single-tool window must expose 'Reset layout'"
    finally:
        win.close()
        win.deleteLater()
        _app.processEvents()


def test_standalone_reset_runs_and_keeps_three_docks(tmp_path: Path) -> None:
    from scriptree.ui.standalone_window import StandaloneWindow
    tool, p = _saved_tool(tmp_path)
    win = StandaloneWindow.from_tool(tool, p)
    try:
        win.resize(800, 700)
        win.show()
        _app.processEvents()
        # Invoking reset must not raise.
        win.reset_layout()
        _app.processEvents()
        # The three docks still exist after a reset.
        assert win._form_dock is not None
        assert win._output_dock is not None
        assert win._run_controls_dock is not None
    finally:
        win.close()
        win.deleteLater()
        _app.processEvents()


def test_mainwindow_snapshots_default_and_exposes_reset() -> None:
    from scriptree.ui.main_window import MainWindow
    w = MainWindow()
    try:
        assert getattr(w, "_default_layout_state", None), (
            "MainWindow must snapshot the default dock layout for reset"
        )
        act = _find_action(w.menuBar(), "Reset layout")
        assert act is not None, "MainWindow View menu must expose 'Reset layout'"
        # Invoking the reset must not raise.
        w._reset_dock_layout()
        _app.processEvents()
        assert w._form_dock is not None
        assert w._output_dock is not None
    finally:
        w.close()
        w.deleteLater()
        _app.processEvents()
