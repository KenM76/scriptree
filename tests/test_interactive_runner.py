"""End-to-end tests for the interactive-stdin runner pathway.

Coverage:

1. ``spawn_streaming(interactive=True)`` opens a stdin pipe and the
   caller can write lines via ``Popen.stdin``.
2. The default (``interactive=False``) keeps stdin closed (DEVNULL).
3. ``_RunWorker.send_line`` returns False when no process is running.
4. ``_RunWorker.send_line`` writes successfully when a process is
   running and round-trips the line through stdout.
5. ``_RunWorker.close_stdin`` signals EOF cleanly.
6. ``ToolRunnerView`` shows / hides the interactive input row based
   on (``tool.interactive`` AND ``interactive_stdin`` permission).
7. ``ToolRunnerView`` quick-response buttons (y / n / ! / q) call
   ``send_line`` with the right text.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

_app = QApplication.instance() or QApplication([])

QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.critical = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)

from scriptree.core.model import ToolDef  # noqa: E402
from scriptree.core.runner import ResolvedCommand, spawn_streaming  # noqa: E402
from scriptree.ui.tool_runner import ToolRunnerView, _RunWorker  # noqa: E402


# ---------------------------------------------------------------------------
# Helper — a tiny stdin echo program we can spawn and feed lines to.
# ---------------------------------------------------------------------------

def _echo_stdin_script() -> Path:
    """Drop a one-line Python script that echoes each stdin line to
    stdout with an ``echo: `` prefix, exiting on EOF."""
    import tempfile
    fd, path = tempfile.mkstemp(suffix="_echo.py", text=True)
    os.close(fd)
    Path(path).write_text(
        textwrap.dedent(
            """
            import sys
            for line in sys.stdin:
                sys.stdout.write("echo: " + line)
                sys.stdout.flush()
            """
        ).strip(),
        encoding="utf-8",
    )
    return Path(path)


# ---------------------------------------------------------------------------
# 1-2. spawn_streaming with / without interactive flag
# ---------------------------------------------------------------------------

def test_spawn_streaming_interactive_opens_stdin_pipe() -> None:
    """When interactive=True, the child has stdin=PIPE and we can
    write to it."""
    script = _echo_stdin_script()
    cmd = ResolvedCommand(argv=[sys.executable, str(script)], cwd=None, env=None)

    out_lines: list[str] = []
    err_lines: list[str] = []
    proc_handle: list[subprocess.Popen] = []

    def _capture_proc(proc: subprocess.Popen) -> None:
        proc_handle.append(proc)
        # Feed two lines and EOF from a side thread.
        def _feed():
            time.sleep(0.05)
            try:
                proc.stdin.write("hello\n")
                proc.stdin.write("world\n")
                proc.stdin.flush()
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        threading.Thread(target=_feed, daemon=True).start()

    result = spawn_streaming(
        cmd,
        on_stdout_line=out_lines.append,
        on_stderr_line=err_lines.append,
        on_start=_capture_proc,
        interactive=True,
    )

    assert proc_handle, "on_start was never called"
    assert proc_handle[0].stdin is not None  # pipe was opened
    assert result.exit_code == 0
    assert any("echo: hello" in line for line in out_lines)
    assert any("echo: world" in line for line in out_lines)
    script.unlink()


def test_spawn_streaming_default_keeps_stdin_devnull() -> None:
    """Without interactive=True, stdin is DEVNULL — subprocess.stdin
    on the Popen handle is None."""
    script = _echo_stdin_script()
    cmd = ResolvedCommand(argv=[sys.executable, str(script)], cwd=None, env=None)

    proc_handle: list[subprocess.Popen] = []
    out_lines: list[str] = []

    def _capture_proc(proc: subprocess.Popen) -> None:
        proc_handle.append(proc)

    spawn_streaming(
        cmd,
        on_stdout_line=out_lines.append,
        on_stderr_line=lambda _l: None,
        on_start=_capture_proc,
        # interactive omitted -> defaults to False
    )

    assert proc_handle
    assert proc_handle[0].stdin is None
    script.unlink()


# ---------------------------------------------------------------------------
# 3-5. _RunWorker public API — send_line / close_stdin contract
# ---------------------------------------------------------------------------

def test_worker_send_line_returns_false_with_no_process() -> None:
    cmd = ResolvedCommand(argv=["python"], cwd=None, env=None)
    w = _RunWorker(cmd, interactive=True)
    assert w.send_line("hi") is False


def test_worker_close_stdin_safe_with_no_process() -> None:
    cmd = ResolvedCommand(argv=["python"], cwd=None, env=None)
    w = _RunWorker(cmd, interactive=True)
    # Must not raise.
    w.close_stdin()


def test_worker_send_line_writes_to_running_process() -> None:
    """End-to-end: spawn an echo script via the worker thread, send
    two lines, capture the echoed output."""
    from PySide6.QtCore import QThread

    script = _echo_stdin_script()
    cmd = ResolvedCommand(
        argv=[sys.executable, str(script)], cwd=None, env=None,
    )
    out_lines: list[str] = []

    worker = _RunWorker(cmd, interactive=True)
    worker.stdoutLine.connect(out_lines.append)

    finished_evt = threading.Event()
    worker.finished.connect(lambda *_: finished_evt.set())

    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    thread.start()

    # Wait until on_start has stashed the proc handle.
    deadline = time.monotonic() + 5.0
    while worker._proc is None and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert worker._proc is not None, "process never started"

    assert worker.send_line("alpha") is True
    assert worker.send_line("beta") is True
    worker.close_stdin()  # echo script reads to EOF, then exits

    # Pump the event loop until the worker emits finished.
    deadline = time.monotonic() + 5.0
    while not finished_evt.is_set() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert finished_evt.is_set(), "worker never finished"

    thread.quit()
    thread.wait(2000)
    script.unlink()

    joined = "\n".join(out_lines)
    assert "echo: alpha" in joined
    assert "echo: beta" in joined


# ---------------------------------------------------------------------------
# 6. ToolRunnerView visibility gating
# ---------------------------------------------------------------------------

def _make_view(*, interactive: bool, perm_grants: bool) -> ToolRunnerView:
    """Build a ToolRunnerView for a synthetic ToolDef.

    ``perm_grants`` patches ``get_app_permissions`` so the view sees
    a permission set that grants / denies ``interactive_stdin``.
    """
    from unittest.mock import patch
    from scriptree.core.permissions import PermissionSet

    ps = PermissionSet(allowed={"interactive_stdin": perm_grants})
    tool = ToolDef(
        name="demo", executable="python", interactive=interactive,
    )
    with patch(
        "scriptree.core.permissions.get_app_permissions",
        return_value=ps,
    ):
        return ToolRunnerView(tool, file_path=None)


def test_interactive_row_hidden_when_tool_not_interactive() -> None:
    v = _make_view(interactive=False, perm_grants=True)
    assert not v._interactive_row.isVisibleTo(v)


def test_interactive_row_hidden_when_permission_denied() -> None:
    v = _make_view(interactive=True, perm_grants=False)
    assert not v._interactive_row.isVisibleTo(v)
    # Public side-channel attribute reads back False — used by
    # the runner's start path to decide whether to spawn with
    # stdin=PIPE.
    assert getattr(v, "_interactive_enabled", None) is False
    assert getattr(v, "_interactive_permission_denied", None) is True


def test_interactive_row_shown_when_tool_and_permission_both_true() -> None:
    v = _make_view(interactive=True, perm_grants=True)
    # Visibility depends on the parent being shown; check the local
    # flag instead for offscreen test contexts.
    assert getattr(v, "_interactive_enabled", None) is True


# ---------------------------------------------------------------------------
# 7. Quick-response buttons route through send_line()
# ---------------------------------------------------------------------------

def test_quick_response_buttons_call_send_line() -> None:
    """The y / n / ! / q quick buttons live inside the interactive
    row.  Each click should call ``_send_text_to_worker`` with the
    matching string."""
    from unittest.mock import patch
    v = _make_view(interactive=True, perm_grants=True)

    # Find the QPushButtons in the row.
    buttons = [
        b for b in v._interactive_row.findChildren(QPushButton)
        if b.text() in ("y", "n", "!", "q")
    ]
    assert {b.text() for b in buttons} == {"y", "n", "!", "q"}

    sent: list[str] = []
    with patch.object(v, "_send_text_to_worker", side_effect=sent.append):
        for label in ("y", "n", "!", "q"):
            target = next(b for b in buttons if b.text() == label)
            target.click()

    assert sent == ["y", "n", "!", "q"]


def test_send_button_pulls_from_line_edit() -> None:
    from unittest.mock import patch
    v = _make_view(interactive=True, perm_grants=True)
    v._send_line_edit.setText("custom answer")

    sent: list[str] = []
    with patch.object(v, "_send_text_to_worker", side_effect=sent.append):
        v._on_send_line()

    assert sent == ["custom answer"]
    # Box is cleared after send.
    assert v._send_line_edit.text() == ""


def test_send_text_when_no_worker_writes_warning_to_output() -> None:
    """Pressing Send before Run starts should not crash — instead it
    appends a one-line ``[send]`` warning to the output pane."""
    v = _make_view(interactive=True, perm_grants=True)
    assert v._worker is None

    v._send_text_to_worker("y")

    output = v._output.toPlainText()
    assert "[send]" in output
    assert "no process" in output.lower()


def test_end_input_no_worker_is_noop() -> None:
    """End input must not crash before a run starts."""
    v = _make_view(interactive=True, perm_grants=True)
    v._on_end_input()
