"""Tests for the Stop button and the launcher running-indicator.

Covers three things that moved together in this change:

1. ``spawn_streaming`` exposes an ``on_start`` hook that fires with the
   freshly-spawned Popen handle, and the handle can be used to kill the
   child process from a different thread while the pump is still
   reading output.
2. :class:`TreeLauncherView` has a public ``mark_running`` method that
   decorates the matching leaf item and tolerates reloads, reorders,
   and multiple leaves referencing the same file.
3. :class:`ToolRunnerView` emits ``runningChanged`` on start and end,
   and the Stop button on the action row is wired up to terminate a
   live process.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.io import save_tool  # noqa: E402
from scriptree.core.model import ParamDef, ToolDef, TreeDef, TreeNode  # noqa: E402
from scriptree.core.runner import ResolvedCommand, spawn_streaming  # noqa: E402
from scriptree.ui.main_window import MainWindow  # noqa: E402
from scriptree.ui.tool_runner import ToolRunnerView  # noqa: E402
from scriptree.ui.tree_view import TreeLauncherView  # noqa: E402


# --- spawn_streaming on_start + external termination ------------------


def test_on_start_receives_popen():
    """The on_start callback must fire with the live Popen handle
    before the pump starts reading output."""
    cmd = ResolvedCommand(
        argv=[sys.executable, "-c", "print('ok')"],
        cwd=None,
    )
    procs: list = []
    result = spawn_streaming(
        cmd, lambda _: None, lambda _: None,
        on_start=lambda p: procs.append(p),
    )
    assert result.exit_code == 0
    assert len(procs) == 1
    # By the time spawn_streaming returns, the process has exited.
    assert procs[0].poll() is not None


def test_on_start_handle_can_terminate_long_running_child():
    """A long-running child must be terminate-able via the on_start
    handle — exercises the exact path the Stop button uses."""
    # sleep long enough that the test will never naturally finish
    # before we kill it.
    cmd = ResolvedCommand(
        argv=[sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=None,
    )
    procs: list = []

    def kill_soon(proc):
        procs.append(proc)
        # Terminate from a separate thread so the pump in the main
        # thread blocks on proc.stdout.readline() until the child
        # dies — same situation as the Stop button.
        t = threading.Thread(
            target=lambda: (
                __import__("time").sleep(0.1),
                proc.terminate(),
            )
        )
        t.daemon = True
        t.start()

    result = spawn_streaming(
        cmd, lambda _: None, lambda _: None, on_start=kill_soon
    )
    # Terminated processes exit with a non-zero code; exact value
    # varies by platform (15/-15 on POSIX, 1 on Windows).
    assert result.exit_code != 0
    assert result.duration_seconds < 5.0  # sanity: we didn't wait 30s


# --- TreeLauncherView.mark_running -----------------------------------


def _tree_fixture(tmp_path: Path, names: list[str]) -> Path:
    """Create a set of .scriptree files and a .scriptreetree that
    references each as a leaf. Returns the tree file path."""
    from scriptree.core.io import save_tree

    leaves: list[TreeNode] = []
    for name in names:
        tool = ToolDef(name=name, executable="/bin/echo",
                       argument_template=["hi"])
        p = tmp_path / f"{name}.scriptree"
        save_tool(tool, p)
        leaves.append(TreeNode(type="leaf", path=f"./{name}.scriptree"))
    tree = TreeDef(name="demo", nodes=leaves)
    tree_path = tmp_path / "demo.scriptreetree"
    save_tree(tree, tree_path)
    return tree_path


def test_mark_running_decorates_matching_leaf(tmp_path):
    tree_path = _tree_fixture(tmp_path, ["a", "b"])
    view = TreeLauncherView()
    try:
        view.load(str(tree_path))
        leaf_path = str((tmp_path / "a.scriptree").resolve())
        view.mark_running(leaf_path, True)

        item = view._find_leaf_items(leaf_path)[0]
        assert item.text(0).startswith("\u25B6 ")
        assert item.font(0).bold()
        assert view.is_marked_running(leaf_path) is True

        view.mark_running(leaf_path, False)
        assert item.text(0) == "a"
        assert not item.font(0).bold()
        assert view.is_marked_running(leaf_path) is False
    finally:
        view.deleteLater()


def test_mark_running_survives_tree_reload(tmp_path):
    """Reloading the tree must reapply the running indicator."""
    tree_path = _tree_fixture(tmp_path, ["a", "b"])
    view = TreeLauncherView()
    try:
        view.load(str(tree_path))
        leaf_path = str((tmp_path / "a.scriptree").resolve())
        view.mark_running(leaf_path, True)

        # Reload — rebuilds every QTreeWidgetItem from scratch.
        view.load(str(tree_path))

        new_item = view._find_leaf_items(leaf_path)[0]
        assert new_item.text(0).startswith("\u25B6 ")
        assert new_item.font(0).bold()
    finally:
        view.deleteLater()


def test_mark_running_ignores_unknown_path(tmp_path):
    """Flagging a path that isn't in the tree is a no-op (doesn't
    raise), but the state is still tracked so a later load can pick
    it up."""
    tree_path = _tree_fixture(tmp_path, ["a"])
    view = TreeLauncherView()
    try:
        view.load(str(tree_path))
        missing = str(tmp_path / "nope.scriptree")
        view.mark_running(missing, True)  # must not raise
        assert view.is_marked_running(missing) is True
    finally:
        view.deleteLater()


# --- ToolRunnerView runningChanged signal ----------------------------


def test_runner_running_changed_signal_fires_on_start_and_end():
    """A full run of a short command must emit (path, True) then
    (path, False)."""
    tool = ToolDef(
        name="t",
        executable=sys.executable,
        argument_template=["-c", "print('hi')"],
    )
    view = ToolRunnerView(tool, file_path="/fake/demo.scriptree")
    try:
        events: list[tuple[str, bool]] = []
        view.runningChanged.connect(lambda p, r: events.append((p, r)))

        # Drive the Run button and pump the event loop until the
        # finished signal has been delivered.
        view._start_run()
        # Wait up to 5 s for the worker thread to complete.
        import time
        deadline = time.monotonic() + 5.0
        while view.is_running() and time.monotonic() < deadline:
            _app.processEvents()
            time.sleep(0.01)
        # One more pump for the queued finished signal.
        for _ in range(5):
            _app.processEvents()

        assert (("/fake/demo.scriptree", True)) in events
        assert (("/fake/demo.scriptree", False)) in events
        # And they must come in the right order.
        idx_true = events.index(("/fake/demo.scriptree", True))
        idx_false = events.index(("/fake/demo.scriptree", False))
        assert idx_true < idx_false
    finally:
        view.deleteLater()


def test_stop_button_terminates_long_running_child():
    tool = ToolDef(
        name="t",
        executable=sys.executable,
        argument_template=["-c", "import time; time.sleep(30)"],
    )
    view = ToolRunnerView(tool, file_path="/fake/sleeper.scriptree")
    try:
        view._start_run()
        assert view.is_running() is True
        assert view._btn_stop.isEnabled() is True

        # Give the child a moment to actually spawn + the on_start
        # callback to stash the proc handle.
        import time
        for _ in range(20):
            if view._worker is not None and view._worker._proc is not None:
                break
            _app.processEvents()
            time.sleep(0.02)

        view._stop_run()

        deadline = time.monotonic() + 5.0
        while view.is_running() and time.monotonic() < deadline:
            _app.processEvents()
            time.sleep(0.01)
        for _ in range(5):
            _app.processEvents()

        assert view.is_running() is False
        assert view._btn_stop.isEnabled() is False
    finally:
        view.deleteLater()


# --- MainWindow → TreeLauncherView integration -----------------------


def test_main_window_forwards_running_signal_to_launcher(tmp_path):
    """A runner's runningChanged signal must drive the launcher
    indicator when routed through the MainWindow."""
    tree_path = _tree_fixture(tmp_path, ["demo"])
    tool_path = str((tmp_path / "demo.scriptree").resolve())

    win = MainWindow()
    try:
        win._launcher.load(str(tree_path))
        # Show the runner for demo.scriptree.
        from scriptree.core.io import load_tool
        tool = load_tool(tool_path)
        win._show_runner(tool, tool_path)
        runner = win._stack.currentWidget()
        assert isinstance(runner, ToolRunnerView)

        # Synthesise a runningChanged event — we don't need to actually
        # spawn a subprocess here; the main window just forwards the
        # signal payload to the launcher.
        runner.runningChanged.emit(tool_path, True)
        assert win._launcher.is_marked_running(tool_path) is True

        runner.runningChanged.emit(tool_path, False)
        assert win._launcher.is_marked_running(tool_path) is False
    finally:
        win.close()
        win.deleteLater()
