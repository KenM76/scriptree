"""Tests for ``scriptree.shell.v1_launcher`` — subprocess shellouts
from the cell shell into the V1 editor."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.shell import v1_launcher  # noqa: E402


# ---------------------------------------------------------------------------
# _project_root + _v1_launcher_cmd
# ---------------------------------------------------------------------------

def test_project_root_finds_install_root() -> None:
    """Walking up from v1_launcher.py should hit the V3 install root
    (the folder containing run_scriptree.bat / run_scriptree.sh)."""
    root = v1_launcher._project_root()
    assert (root / "run_scriptree.bat").is_file() or \
           (root / "run_scriptree.sh").is_file()


def test_v1_launcher_cmd_uses_python_directly() -> None:
    """``_v1_launcher_cmd`` should bypass the .bat / .sh shim and call
    ``run_scriptree.py`` via ``sys.executable`` — that's what guarantees
    the editor uses the same Python (and the same vendored ``lib/pypi``)
    as the cell shell, and avoids the DETACHED_PROCESS-vs-batch bug
    where the cmd.exe console flashes and exits without spawning V1."""
    cmd = v1_launcher._v1_launcher_cmd()
    assert len(cmd) == 2
    assert cmd[0] == sys.executable
    assert cmd[1].endswith("run_scriptree.py")
    assert Path(cmd[1]).is_file()


# ---------------------------------------------------------------------------
# launch_tool / launch_editor_with_tree / launch_editor_blank
# ---------------------------------------------------------------------------

def test_launch_tool_passes_path_to_subprocess() -> None:
    """``launch_tool(path)`` should Popen([sys.executable,
    run_scriptree.py, path]) fire-and-forget.  Path may be normalised
    to native separators (``Path(...)``) en route to argv, so we
    compare on the resolved path."""
    with patch.object(v1_launcher, "subprocess") as mock_sub:
        v1_launcher.launch_tool("C:/tmp/foo.scriptree")
    mock_sub.Popen.assert_called_once()
    args, kwargs = mock_sub.Popen.call_args
    cmd = args[0]
    # Normalise both sides for cross-platform separator differences.
    assert Path(cmd[-1]) == Path("C:/tmp/foo.scriptree")
    assert kwargs.get("shell") is False


def test_launch_tool_passes_configuration() -> None:
    """When ``configuration`` is supplied the argv should include
    ``-configuration <name>`` after the path."""
    with patch.object(v1_launcher, "subprocess") as mock_sub:
        v1_launcher.launch_tool("foo.scriptree", configuration="prod")
    cmd = mock_sub.Popen.call_args[0][0]
    assert "-configuration" in cmd
    assert cmd[cmd.index("-configuration") + 1] == "prod"
    assert cmd[-2:] == ["-configuration", "prod"]


def test_launch_editor_with_tree_builds_argv() -> None:
    with patch.object(v1_launcher, "subprocess") as mock_sub:
        v1_launcher.launch_editor_with_tree("/tmp/x.scriptreetree")
    cmd = mock_sub.Popen.call_args[0][0]
    # Path may be normalised to native separators.
    assert Path(cmd[-1]) == Path("/tmp/x.scriptreetree")


def test_launch_editor_blank_no_args_after_launcher() -> None:
    with patch.object(v1_launcher, "subprocess") as mock_sub:
        v1_launcher.launch_editor_blank()
    cmd = mock_sub.Popen.call_args[0][0]
    # Just the launcher command, no positional path.
    expected = v1_launcher._v1_launcher_cmd()
    assert cmd == expected


def test_spawn_uses_no_window_creationflags_on_windows() -> None:
    """Popen kwargs should hide the console (CREATE_NO_WINDOW =
    0x08000000) and create a new process group so a Ctrl-C in the
    cell shell doesn't propagate.  Crucially we do NOT use
    DETACHED_PROCESS — that breaks .bat shims and was the cause of
    the v0.2.0 'console flashes and editor never appears' bug."""
    if sys.platform != "win32":
        return
    with patch.object(v1_launcher, "subprocess") as mock_sub:
        v1_launcher.launch_editor_blank()
    kwargs = mock_sub.Popen.call_args[1]
    flags = kwargs.get("creationflags", 0)
    # CREATE_NO_WINDOW = 0x08000000, CREATE_NEW_PROCESS_GROUP = 0x200.
    assert flags & 0x08000000, (
        f"missing CREATE_NO_WINDOW: flags=0x{flags:08X}"
    )
    assert flags & 0x200, (
        f"missing CREATE_NEW_PROCESS_GROUP: flags=0x{flags:08X}"
    )
    # And NOT DETACHED_PROCESS.
    assert not (flags & 0x8), (
        f"DETACHED_PROCESS set; that breaks .bat shims: flags=0x{flags:08X}"
    )


# ---------------------------------------------------------------------------
# Polyfill dispatch (show_tree_for / show_main_window_for / show_composite_for)
# ---------------------------------------------------------------------------

class _FakeHex:
    def __init__(self, catalog_path=None, role="standalone", members=None):
        self._catalog_path = catalog_path
        self.role = role
        self._members = members or []


def test_show_tree_for_lock_open_with_tree_calls_editor() -> None:
    """show_tree_for(mode='lock-open') with a .scriptreetree path should
    spawn the editor with the tree."""
    hx = _FakeHex(catalog_path="/tmp/x.scriptreetree")
    with patch.object(v1_launcher, "launch_editor_with_tree") as m_tree, \
         patch.object(v1_launcher, "launch_editor_blank") as m_blank, \
         patch.object(v1_launcher, "launch_tool") as m_tool:
        v1_launcher.show_tree_for(hx, mode="lock-open")
    m_tree.assert_called_once_with(Path("/tmp/x.scriptreetree"))
    m_blank.assert_not_called()
    m_tool.assert_not_called()


def test_show_tree_for_lock_open_with_scriptree_calls_tool() -> None:
    """show_tree_for(mode='lock-open') with a .scriptree path should
    spawn the standalone runner directly."""
    hx = _FakeHex(catalog_path="/tmp/x.scriptree")
    with patch.object(v1_launcher, "launch_tool") as m_tool, \
         patch.object(v1_launcher, "launch_editor_with_tree") as m_tree:
        v1_launcher.show_tree_for(hx, mode="lock-open")
    m_tool.assert_called_once()
    m_tree.assert_not_called()


def test_show_tree_for_lock_open_no_catalog_calls_blank() -> None:
    hx = _FakeHex(catalog_path=None)
    with patch.object(v1_launcher, "launch_editor_blank") as m_blank:
        v1_launcher.show_tree_for(hx, mode="lock-open")
    m_blank.assert_called_once()


def test_show_main_window_for_routes_to_lock_open() -> None:
    """show_main_window_for is the double-right-click handler — it
    should always behave like lock-open mode."""
    hx = _FakeHex(catalog_path="/tmp/x.scriptreetree")
    with patch.object(v1_launcher, "show_tree_for") as m_show:
        v1_launcher.show_main_window_for(hx)
    m_show.assert_called_once_with(hx, mode="lock-open")


def test_show_composite_for_master_uses_merged_tree() -> None:
    """For a master cell, show_composite_for should call
    build_merged_tree_for_master then launch the editor with it."""
    hx = _FakeHex(role="master")
    with patch(
        "scriptree.shell.merged_tree.build_merged_tree_for_master",
        return_value=Path("/tmp/merged.scriptreetree"),
    ), patch.object(v1_launcher, "launch_editor_with_tree") as m_tree:
        v1_launcher.show_composite_for(hx)
    m_tree.assert_called_once_with(Path("/tmp/merged.scriptreetree"))


def test_show_composite_for_standalone_routes_to_lock_open() -> None:
    hx = _FakeHex(catalog_path="/tmp/x.scriptreetree", role="standalone")
    with patch.object(v1_launcher, "show_tree_for") as m_show:
        v1_launcher.show_composite_for(hx)
    m_show.assert_called_once_with(hx, mode="lock-open")
