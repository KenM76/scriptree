"""Phase-1 regression suite for ``scriptree.core.platform`` — OS
detection + per-host resolution.

Two halves:

* ``host_os()`` returns the correct normalised id on each
  supported platform and falls back safely on unknowns.
* ``resolve_for_host(tool, os=...)`` merges per-OS overrides
  into the top-level fields with the right per-field replace
  semantics.

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
from scriptree.core.platform import (
    OS_IDS,
    host_os,
    resolve_for_host,
    _reset_host_cache_for_tests,
)


# ============================================================================
# host_os()
# ============================================================================


class TestHostDetection:
    """Maps ``platform.system()`` to the canonical OS id."""

    @pytest.mark.parametrize(
        "sysname,expected",
        [
            ("Windows", "windows"),
            ("Darwin", "macos"),
            ("Linux", "linux"),
        ],
    )
    def test_known_platforms(self, sysname: str, expected: str) -> None:
        _reset_host_cache_for_tests()
        with patch("platform.system", return_value=sysname):
            assert host_os() == expected
        _reset_host_cache_for_tests()

    def test_unknown_falls_back_to_linux(self) -> None:
        """BSDs / illumos / others fall back to ``"linux"`` --
        the safest POSIX-shaped default."""
        _reset_host_cache_for_tests()
        with patch("platform.system", return_value="FreeBSD"):
            assert host_os() == "linux"
        _reset_host_cache_for_tests()

    def test_result_is_cached(self) -> None:
        """First call goes through ``platform.system``; second
        call reads the cache.  Verifies by changing the mock
        between calls -- the second call must still return the
        first call's value."""
        _reset_host_cache_for_tests()
        with patch("platform.system", return_value="Windows"):
            first = host_os()
        with patch("platform.system", return_value="Darwin"):
            second = host_os()
        assert first == second == "windows"
        _reset_host_cache_for_tests()

    def test_os_ids_constant_matches_known_mappings(self) -> None:
        """Sanity: the public ``OS_IDS`` tuple covers every
        platform the internal mapping recognises."""
        assert set(OS_IDS) >= {"windows", "macos", "linux"}


# ============================================================================
# resolve_for_host()
# ============================================================================


def _tool_with_overrides() -> ToolDef:
    """A ToolDef with all five overridable fields set on
    top-level and a single macos override."""
    return ToolDef(
        name="X",
        executable="py.exe",
        argument_template=["-3", "./tool.py"],
        path_prepend=["C:/Tools"],
        env={"PYTHONIOENCODING": "utf-8"},
        actions=[
            ActionDef(id="default", label="Default", argv=["echo", "win"]),
        ],
        platforms={
            "macos": PlatformOverride(
                executable="python3",
                argument_template=["./tool.py"],
                path_prepend=["/usr/local/bin"],
                env={"LC_ALL": "en_US.UTF-8"},
                actions=[
                    ActionDef(
                        id="default", label="Default",
                        argv=["echo", "mac"],
                    ),
                ],
            ),
        },
    )


class TestResolveBasics:
    def test_no_overrides_returns_copy(self) -> None:
        """A ToolDef with empty platforms returns a copy with
        identical top-level fields."""
        t = ToolDef(name="X", executable="py.exe")
        resolved = resolve_for_host(t, os="windows")
        assert resolved is not t
        assert resolved.executable == "py.exe"

    def test_no_entry_for_host_returns_copy(self) -> None:
        """``platforms`` has entries but none for the requested
        os -- top-level defaults survive untouched."""
        t = _tool_with_overrides()
        resolved = resolve_for_host(t, os="linux")  # no linux entry
        assert resolved.executable == "py.exe"
        assert resolved.argument_template == ["-3", "./tool.py"]
        assert resolved.path_prepend == ["C:/Tools"]
        assert resolved.env == {"PYTHONIOENCODING": "utf-8"}
        assert resolved.actions[0].argv == ["echo", "win"]

    def test_full_override_replaces_every_field(self) -> None:
        t = _tool_with_overrides()
        resolved = resolve_for_host(t, os="macos")
        assert resolved.executable == "python3"
        assert resolved.argument_template == ["./tool.py"]
        assert resolved.path_prepend == ["/usr/local/bin"]
        assert resolved.env == {"LC_ALL": "en_US.UTF-8"}
        assert resolved.actions[0].argv == ["echo", "mac"]


class TestResolvePartial:
    """Per-field replace semantics: an override that touches
    only some fields leaves the rest at top-level defaults."""

    def test_executable_only_keeps_other_defaults(self) -> None:
        t = ToolDef(
            name="X",
            executable="py.exe",
            argument_template=["-3", "./tool.py"],
            path_prepend=["C:/Tools"],
            platforms={
                "macos": PlatformOverride(executable="python3"),
            },
        )
        resolved = resolve_for_host(t, os="macos")
        assert resolved.executable == "python3"  # overridden
        assert resolved.argument_template == ["-3", "./tool.py"]  # inherited
        assert resolved.path_prepend == ["C:/Tools"]  # inherited

    def test_argument_template_only_keeps_executable(self) -> None:
        t = ToolDef(
            name="X",
            executable="python3",
            argument_template=["-c", "print('windows')"],
            platforms={
                "linux": PlatformOverride(
                    argument_template=["-c", "print('linux')"],
                ),
            },
        )
        resolved = resolve_for_host(t, os="linux")
        assert resolved.executable == "python3"
        assert resolved.argument_template == ["-c", "print('linux')"]


class TestResolveOriginalNotMutated:
    """``resolve_for_host`` returns a NEW ToolDef.  The original
    must keep its full cross-platform shape so the editor can
    still see it."""

    def test_original_platforms_intact(self) -> None:
        t = _tool_with_overrides()
        before_keys = set(t.platforms.keys())
        before_mac_exe = t.platforms["macos"].executable

        resolve_for_host(t, os="macos")

        assert set(t.platforms.keys()) == before_keys
        assert t.platforms["macos"].executable == before_mac_exe

    def test_resolved_carries_full_platforms_map(self) -> None:
        """The resolved ToolDef KEEPS the full platforms map
        even though only one was applied -- so the editor /
        Preview-as dropdown can still inspect the others
        without re-loading."""
        t = _tool_with_overrides()
        resolved = resolve_for_host(t, os="macos")
        assert "macos" in resolved.platforms


class TestResolveEmptyOverride:
    """An empty ``PlatformOverride()`` (all fields None) means
    "supported on this OS, identical to default" -- the
    resolved ToolDef matches the top-level defaults."""

    def test_empty_override_inherits_everything(self) -> None:
        t = _tool_with_overrides()
        # Replace the macos entry with an empty override.
        t.platforms["macos"] = PlatformOverride()
        resolved = resolve_for_host(t, os="macos")
        assert resolved.executable == "py.exe"
        assert resolved.argument_template == ["-3", "./tool.py"]
        assert resolved.actions[0].argv == ["echo", "win"]


class TestResolveDefaultsToHost:
    """Without an explicit ``os=`` arg, resolution uses
    ``host_os()``."""

    def test_default_os_is_host(self) -> None:
        _reset_host_cache_for_tests()
        with patch("platform.system", return_value="Windows"):
            t = ToolDef(
                name="X", executable="py.exe",
                platforms={
                    "windows": PlatformOverride(executable="windows-py"),
                    "macos":   PlatformOverride(executable="mac-py"),
                },
            )
            resolved = resolve_for_host(t)  # no os= -> host
            assert resolved.executable == "windows-py"
        _reset_host_cache_for_tests()


class TestTypeValidation:
    def test_resolve_rejects_non_tooldef(self) -> None:
        with pytest.raises(TypeError):
            resolve_for_host({"name": "X"}, os="windows")  # type: ignore[arg-type]
