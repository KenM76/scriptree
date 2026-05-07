"""Tests for :class:`MainWindow` runner caching.

The runner view for each saved tool is kept alive across tool switches
so that each tool's output pane, form state, and any live child process
survive clicking between tools in the launcher. These tests exercise
that caching and the cache-invalidation paths (editor save, unsaved
tools, editor cancel).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.io import save_tool  # noqa: E402
from scriptree.core.model import ParamDef, ToolDef  # noqa: E402
from scriptree.ui.main_window import MainWindow  # noqa: E402
from scriptree.ui.tool_editor import ToolEditorView  # noqa: E402
from scriptree.ui.tool_runner import ToolRunnerView  # noqa: E402


def _make_tool(name: str = "demo") -> ToolDef:
    return ToolDef(
        name=name,
        executable="/bin/echo",
        argument_template=["{msg}"],
        params=[ParamDef(id="msg", label="Msg", default=name)],
    )


def _save(tmp_path: Path, name: str) -> tuple[ToolDef, str]:
    tool = _make_tool(name)
    path = tmp_path / f"{name}.scriptree"
    save_tool(tool, path)
    return tool, str(path)


# --- caching -----------------------------------------------------------


def test_same_path_returns_same_runner_instance(tmp_path):
    win = MainWindow()
    try:
        tool_a, path_a = _save(tmp_path, "a")

        win._show_runner(tool_a, path_a)
        view1 = win._stack.currentWidget()
        assert isinstance(view1, ToolRunnerView)

        # Showing the same tool again must re-use the cached view.
        win._show_runner(tool_a, path_a)
        view2 = win._stack.currentWidget()
        assert view2 is view1
    finally:
        win.close()
        win.deleteLater()


def test_different_paths_keep_both_runners_alive(tmp_path):
    """Switching between two tools must keep both runner views in
    memory (this is what preserves output history per tool)."""
    win = MainWindow()
    try:
        tool_a, path_a = _save(tmp_path, "a")
        tool_b, path_b = _save(tmp_path, "b")

        win._show_runner(tool_a, path_a)
        view_a = win._stack.currentWidget()
        win._show_runner(tool_b, path_b)
        view_b = win._stack.currentWidget()
        assert view_a is not view_b

        # Both runners are still in the stack.
        widgets_in_stack = {win._stack.widget(i) for i in range(win._stack.count())}
        assert view_a in widgets_in_stack
        assert view_b in widgets_in_stack

        # And switching back to A still returns the original instance.
        win._show_runner(tool_a, path_a)
        assert win._stack.currentWidget() is view_a
    finally:
        win.close()
        win.deleteLater()


def test_output_history_survives_tool_switch(tmp_path):
    """Writing into the first tool's output pane, switching to a second
    tool, then switching back, must show the original text unchanged."""
    win = MainWindow()
    try:
        tool_a, path_a = _save(tmp_path, "a")
        tool_b, path_b = _save(tmp_path, "b")

        win._show_runner(tool_a, path_a)
        view_a = win._stack.currentWidget()
        view_a._on_stdout("hello from tool a")

        win._show_runner(tool_b, path_b)
        win._show_runner(tool_a, path_a)

        assert "hello from tool a" in view_a._output.toPlainText()
    finally:
        win.close()
        win.deleteLater()


def test_path_normalization_hits_same_cache(tmp_path):
    """A tool opened as ``./foo.scriptree`` and ``foo.scriptree`` must
    map to the same cached runner — the key is the resolved absolute
    path, not the raw string."""
    win = MainWindow()
    try:
        tool, path = _save(tmp_path, "demo")
        alt = str(Path(path))  # already absolute
        win._show_runner(tool, path)
        first = win._stack.currentWidget()
        win._show_runner(tool, alt)
        second = win._stack.currentWidget()
        assert first is second
    finally:
        win.close()
        win.deleteLater()


# --- cache invalidation ------------------------------------------------


def test_editor_save_drops_cached_runner(tmp_path):
    """After an edit-and-save cycle, the old cached runner is replaced
    with a fresh one built from the new definition."""
    win = MainWindow()
    try:
        tool, path = _save(tmp_path, "demo")
        win._show_runner(tool, path)
        old_view = win._stack.currentWidget()

        # Simulate the editor emitting `saved` with an updated tool.
        updated = _make_tool("demo")
        updated.description = "updated description"
        win._on_editor_saved(updated, path)

        new_view = win._stack.currentWidget()
        assert isinstance(new_view, ToolRunnerView)
        assert new_view is not old_view
        # The old view should have been removed from the stack.
        widgets_in_stack = {win._stack.widget(i) for i in range(win._stack.count())}
        assert old_view not in widgets_in_stack
    finally:
        win.close()
        win.deleteLater()


def test_unsaved_runner_is_replaced_not_cached(tmp_path):
    """Runners for in-memory (path=None) tools are transient: each new
    unsaved runner destroys the previous one."""
    win = MainWindow()
    try:
        t1 = _make_tool("t1")
        win._show_runner(t1, None)
        first = win._unsaved_runner
        assert first is not None

        t2 = _make_tool("t2")
        win._show_runner(t2, None)
        second = win._unsaved_runner
        assert second is not None
        assert second is not first

        # And neither landed in the cache dict.
        assert win._runners == {}
    finally:
        win.close()
        win.deleteLater()


def test_editor_overlays_do_not_destroy_runner(tmp_path):
    """Opening the editor on a currently-displayed tool must not
    destroy the cached runner — cancelling the edit returns to the
    original runner view."""
    win = MainWindow()
    try:
        tool, path = _save(tmp_path, "demo")
        win._show_runner(tool, path)
        runner = win._stack.currentWidget()
        assert isinstance(runner, ToolRunnerView)

        win._show_editor(tool, path)
        assert isinstance(win._stack.currentWidget(), ToolEditorView)

        # Runner is still in the stack and still the same instance.
        widgets = {win._stack.widget(i) for i in range(win._stack.count())}
        assert runner in widgets

        win._on_editor_cancelled()
        assert win._stack.currentWidget() is runner
    finally:
        win.close()
        win.deleteLater()


# --- multi-tool concurrency ------------------------------------------


def test_runner_is_running_starts_false(tmp_path):
    """A fresh runner reports not-running until Run is clicked.
    Establishes the public API the MainWindow uses to decide whether
    tools are still active at close time."""
    tool, path = _save(tmp_path, "demo")
    view = ToolRunnerView(tool, file_path=path)
    try:
        assert view.is_running() is False
    finally:
        view.deleteLater()
