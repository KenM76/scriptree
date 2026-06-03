"""Regression suite for the no-console-window Popen sweep (v0.8.0a29+).

Pins the `no_console_popen_kwargs()` helper and verifies every
tool-spawning site in the codebase passes its result into
subprocess.Popen / subprocess.run.

## Why these tests exist

ScripTree's primary launcher is ``pythonw.exe`` (Windows
subsystem, no console).  When it spawns a console-subsystem child
(``py.exe``, ``python.exe``, ``cmd.exe``, a ``.bat``, any console
``.exe``), Windows allocates a fresh console window for the child
by default.  This is the "console pop-up while running tools"
bug.

The fix is ``CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`` in
``creationflags``.  These tests guard against future regressions
where a developer adds a new Popen site and forgets to merge in
``no_console_popen_kwargs()``.

## Test strategy

Each tool-spawning site is exercised with subprocess.Popen /
subprocess.run patched out, then we inspect the kwargs the patched
mock was called with and assert ``creationflags`` is present (on
Windows) with the right bits set.  This is a CALL-SITE test, not
an end-to-end test — we don't need to actually spawn anything.
"""
from __future__ import annotations

import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# The helper itself
# ---------------------------------------------------------------------------

class TestNoConsolePopenKwargs:
    """Pin the helper's return shape on every platform."""

    def test_windows_returns_creationflags(self):
        from scriptree.core.runner import no_console_popen_kwargs
        if sys.platform != "win32":
            pytest.skip("Windows-specific behaviour")
        kw = no_console_popen_kwargs()
        assert "creationflags" in kw
        flags = kw["creationflags"]
        # CREATE_NO_WINDOW = 0x08000000 — the actual no-window bit.
        assert flags & 0x08000000, (
            f"CREATE_NO_WINDOW (0x08000000) missing from {flags:#x}"
        )
        # CREATE_NEW_PROCESS_GROUP = 0x00000200 — Ctrl-C isolation.
        assert flags & 0x00000200, (
            f"CREATE_NEW_PROCESS_GROUP (0x00000200) missing from "
            f"{flags:#x}"
        )

    def test_windows_does_NOT_set_detached_process(self):
        """Our own lesson says DETACHED_PROCESS breaks .bat shims.
        Make sure we haven't accidentally turned that bit on."""
        from scriptree.core.runner import no_console_popen_kwargs
        if sys.platform != "win32":
            pytest.skip("Windows-specific behaviour")
        flags = no_console_popen_kwargs()["creationflags"]
        # DETACHED_PROCESS = 0x00000008 — must NOT be set.
        assert not (flags & 0x00000008), (
            f"DETACHED_PROCESS (0x00000008) is set in {flags:#x} — "
            f"that breaks .bat shims, see "
            f"rags/lessons/detached_process_breaks_bat.md"
        )

    def test_non_windows_returns_empty_dict(self):
        """On macOS / Linux there's no per-child console window,
        so we don't need any flag.  Helper returns {} so callers
        can blindly merge into kwargs."""
        # We can't reliably skip / fake sys.platform inside the
        # already-imported module here, so test the LOGIC by
        # monkeypatching sys.platform and re-importing the helper
        # function.  The function reads sys.platform at call time.
        from scriptree.core import runner
        with patch.object(runner.sys, "platform", "linux"):
            assert runner.no_console_popen_kwargs() == {}
        with patch.object(runner.sys, "platform", "darwin"):
            assert runner.no_console_popen_kwargs() == {}


# ---------------------------------------------------------------------------
# Site-by-site call-kwargs inspection
# ---------------------------------------------------------------------------

@pytest.fixture
def assert_no_window():
    """Returns a callable that takes a kwargs dict and asserts the
    no-window flag is set when running on Windows.  No-op assertion
    on other platforms (since the helper returns {} there)."""
    def _check(kwargs: dict) -> None:
        if sys.platform != "win32":
            return
        assert "creationflags" in kwargs, (
            f"site did not pass creationflags; kwargs were {kwargs!r}"
        )
        flags = kwargs["creationflags"]
        assert flags & 0x08000000, (
            f"CREATE_NO_WINDOW missing from {flags:#x}"
        )
    return _check


class TestSpawnStreamingSite:
    """``scriptree.core.runner.spawn_streaming`` is THE main runner.
    Every tool the user runs through ScripTree goes through here.
    Bug v0.8.0a25 and earlier: this Popen had no creationflags so
    every tool that used py.exe / cmd.exe / .bat as its executable
    popped a console window.
    """

    def test_passes_no_window_flag_to_popen(self, assert_no_window):
        from scriptree.core.runner import (
            spawn_streaming, ResolvedCommand,
        )
        cmd = ResolvedCommand(argv=["echo", "hi"], cwd=None, env=None)

        # Mock subprocess.Popen so no actual process spawns.  The
        # returned mock satisfies the .stdout/.stderr/.wait/.returncode
        # attribute access spawn_streaming needs.
        fake_proc = MagicMock()
        fake_proc.stdout = iter([])
        fake_proc.stderr = iter([])
        fake_proc.wait.return_value = 0
        fake_proc.returncode = 0
        with patch(
            "scriptree.core.runner.subprocess.Popen",
            return_value=fake_proc,
        ) as mock_popen:
            spawn_streaming(
                cmd,
                on_stdout_line=lambda _l: None,
                on_stderr_line=lambda _l: None,
            )

        assert mock_popen.called
        _args, kwargs = mock_popen.call_args
        assert_no_window(kwargs)


class TestProvidersSite:
    """``scriptree.core.providers`` runs dropdown-population
    commands.  Same console-pop concern as spawn_streaming."""

    def test_passes_no_window_flag(self, assert_no_window):
        from scriptree.core import providers
        from scriptree.core.model import ProviderSpec, ParamType

        spec = ProviderSpec(command=["echo", "ok"])

        fake_completed = MagicMock()
        fake_completed.returncode = 0
        fake_completed.stdout = '{"value": "ok"}'
        fake_completed.stderr = ""
        with patch(
            "scriptree.core.providers.subprocess.run",
            return_value=fake_completed,
        ) as mock_run:
            providers.resolve_provider(
                spec,
                param_id="x",
                param_type=ParamType.STRING,
            )

        assert mock_run.called, "subprocess.run was not invoked"
        _args, kwargs = mock_run.call_args
        assert_no_window(kwargs)


class TestProbeSite:
    """``scriptree.core.parser.probe._run_help`` runs ``--help``.
    Tools probed are user-supplied executables — any of which may
    be console-subsystem."""

    def test_passes_no_window_flag(self, assert_no_window):
        # ``parser/__init__.py`` does ``from .probe import probe``
        # which overwrites the package attribute, shadowing the
        # submodule on attribute access.  ``import ... as`` follows
        # the attribute, so it also picks up the function.
        # ``importlib.import_module`` bypasses that and returns the
        # actual module from ``sys.modules``.
        import importlib
        probe_mod = importlib.import_module(
            "scriptree.core.parser.probe"
        )
        fake_completed = MagicMock()
        fake_completed.returncode = 0
        fake_completed.stdout = "usage: foo [opts]"
        fake_completed.stderr = ""
        with patch(
            "scriptree.core.parser.probe.subprocess.run",
            return_value=fake_completed,
        ) as mock_run:
            probe_mod._run_help("echo", ("--help",))

        assert mock_run.called
        _args, kwargs = mock_run.call_args
        assert_no_window(kwargs)
