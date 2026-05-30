"""Phase-2 regression suite for cross-platform overrides at the
runner integration point.

Verifies that ``build_full_argv`` and ``resolve_action`` consult
``tool.platforms`` for the host OS BEFORE assembling argv, and
that the original ToolDef passed in stays untouched so the editor
keeps the full cross-platform view.

Tests use ``unittest.mock.patch`` against ``platform.system`` plus
``_reset_host_cache_for_tests`` to simulate running on each OS in
turn from the same machine.

Auto-dismisses ``QMessageBox`` per the standing rule.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)

from scriptree.core.model import ActionDef, PlatformOverride, ToolDef
from scriptree.core.platform import _reset_host_cache_for_tests
from scriptree.core.runner import build_full_argv, resolve_action


@pytest.fixture
def _host_macos():
    """Force ``host_os()`` to return ``"macos"`` for the test."""
    _reset_host_cache_for_tests()
    with patch("platform.system", return_value="Darwin"):
        yield
    _reset_host_cache_for_tests()


@pytest.fixture
def _host_windows():
    _reset_host_cache_for_tests()
    with patch("platform.system", return_value="Windows"):
        yield
    _reset_host_cache_for_tests()


@pytest.fixture
def _host_linux():
    _reset_host_cache_for_tests()
    with patch("platform.system", return_value="Linux"):
        yield
    _reset_host_cache_for_tests()


def _multi_os_tool() -> ToolDef:
    """A ToolDef wired for three distinct OS argv shapes -- the
    combridge-vs-osascript style of cross-platform definition."""
    return ToolDef(
        name="Hello",
        executable="py.exe",
        argument_template=["-3", "-c", "print('hi from windows')"],
        platforms={
            "macos": PlatformOverride(
                executable="/usr/bin/osascript",
                argument_template=[
                    "-e", "display dialog \"hi from mac\"",
                ],
            ),
            "linux": PlatformOverride(
                executable="python3",
                argument_template=["-c", "print('hi from linux')"],
            ),
        },
    )


# ============================================================================
# build_full_argv
# ============================================================================


class TestBuildFullArgv:
    def test_picks_windows_variant_on_windows(
        self, _host_windows,
    ) -> None:
        tool = _multi_os_tool()
        cmd = build_full_argv(tool, values={}, extras=[])
        # Argv[0] is the resolved executable; substrings let us
        # ignore the path-resolution prefix.
        assert "py.exe" in cmd.argv[0].lower()
        # Argv[1:] should reflect the Windows argument_template.
        joined = " ".join(cmd.argv)
        assert "hi from windows" in joined

    def test_picks_mac_variant_on_macos(
        self, _host_macos,
    ) -> None:
        tool = _multi_os_tool()
        cmd = build_full_argv(tool, values={}, extras=[])
        joined = " ".join(cmd.argv)
        assert "osascript" in cmd.argv[0]
        assert "hi from mac" in joined
        # Windows-only variant did NOT leak through.
        assert "py.exe" not in cmd.argv[0]

    def test_picks_linux_variant_on_linux(
        self, _host_linux,
    ) -> None:
        tool = _multi_os_tool()
        cmd = build_full_argv(tool, values={}, extras=[])
        joined = " ".join(cmd.argv)
        assert "python3" in cmd.argv[0]
        assert "hi from linux" in joined

    def test_falls_back_to_default_on_unconfigured_os(
        self, _host_macos,
    ) -> None:
        """When the tool has no entry for the host's OS, the
        top-level default is used (verifies fall-back path even
        when ``platforms`` exists but the relevant key is
        missing)."""
        tool = ToolDef(
            name="WinOnly",
            executable="py.exe",
            argument_template=["-3", "x.py"],
            platforms={
                # Note: only ``linux`` -- nothing for macos.
                "linux": PlatformOverride(executable="python3"),
            },
        )
        cmd = build_full_argv(tool, values={}, extras=[])
        # macos host with no macos override + no linux match for
        # this host = fall back to top-level py.exe.
        assert "py.exe" in cmd.argv[0].lower()

    def test_original_tool_not_mutated(
        self, _host_macos,
    ) -> None:
        """``build_full_argv`` returns a NEW ResolvedCommand; the
        ToolDef passed in must keep its full ``platforms`` map
        and original top-level fields intact so the editor's
        live view stays accurate."""
        tool = _multi_os_tool()
        before_exe = tool.executable
        before_keys = set(tool.platforms.keys())

        build_full_argv(tool, values={}, extras=[])

        assert tool.executable == before_exe
        assert set(tool.platforms.keys()) == before_keys
        assert tool.platforms["macos"].executable == "/usr/bin/osascript"


# ============================================================================
# resolve_action
# ============================================================================


class TestResolveAction:
    def test_action_uses_override_executable_on_mac(
        self, _host_macos,
    ) -> None:
        """An action defined at top-level still gets the
        per-OS executable when the override sets one."""
        action = ActionDef(
            id="hello",
            label="Hello",
            argv=["-e", "tell application \"Finder\" to display dialog \"hi\""],
        )
        tool = ToolDef(
            name="HelloMac",
            executable="py.exe",
            argument_template=["-3", "x.py"],
            actions=[action],
            platforms={
                "macos": PlatformOverride(
                    executable="/usr/bin/osascript",
                ),
            },
        )
        cmd = resolve_action(tool, action)
        # Argv[0] should be the macOS-overridden executable.
        assert "osascript" in cmd.argv[0]
        # Argv[1:] is action.argv passed through literally.
        assert cmd.argv[1:] == action.argv

    def test_action_falls_back_to_default_on_unconfigured_os(
        self, _host_linux,
    ) -> None:
        action = ActionDef(id="hi", label="Hi", argv=["arg"])
        tool = ToolDef(
            name="WinHi",
            executable="py.exe",
            actions=[action],
            platforms={
                # Only macos -- linux host gets the default.
                "macos": PlatformOverride(executable="osascript"),
            },
        )
        cmd = resolve_action(tool, action)
        assert "py.exe" in cmd.argv[0].lower()
