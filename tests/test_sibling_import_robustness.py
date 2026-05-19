"""Tests for the v0.3.12 sibling-import robustness fix.

The bug
-------
A multi-file Python tool laid out as::

    SomeTool/
        SomeTool.scriptree
        SomeTool.py            ← entry script
        _SomeTool_helper.py    ← imported by entry script

would fail with ``ModuleNotFoundError: No module named
'_SomeTool_helper'`` when run via ScripTree's bundled embeddable
Python on a clean machine — even though the same code runs fine
under a system Python.

Root cause: the Windows embeddable Python ships with a
``python<ver>._pth`` file that puts the interpreter in restricted-
``sys.path`` mode.  PYTHONPATH is ignored, PYTHONHOME is ignored,
and the script's own directory is NOT auto-prepended to
``sys.path[0]``.  Sibling imports therefore fail silently for
every tool whose author wasn't aware of the embeddable's quirks.

The fix
-------
Two cooperating layers (belt + suspenders):

1. ``lib/python/Lib/site-packages/sitecustomize.py`` — runs at
   interpreter startup (because ``import site`` is uncommented in
   ``python<ver>._pth``).  Prepends ``$SCRIPTREE_TOOL_DIR`` and the
   parent of ``sys.argv[0]`` to ``sys.path``.

2. ``scriptree.core.runner.inject_tool_dir_env`` — sets
   ``SCRIPTREE_TOOL_DIR`` (for the bundled-Python sitecustomize)
   AND prepends the tool's directory to ``PYTHONPATH`` (for system
   Python invocations and any non-Python tools that want to know
   where they live).

These tests cover layer 2 (the env injection from the runner side).
Layer 1's behaviour is verified end-to-end by spawning the bundled
Python directly with a sibling-import test script.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scriptree.core.io import save_tool
from scriptree.core.model import (
    ParamDef, ParamType, ToolDef, Widget,
)
from scriptree.core.runner import (
    build_env, build_full_argv, inject_tool_dir_env, resolve,
)


# ===========================================================================
# Layer 2 — inject_tool_dir_env
# ===========================================================================

def _make_tool(tmp_path: Path) -> ToolDef:
    """Save a minimal tool to disk so ``loaded_from`` is set the way
    the real load path sets it."""
    tool = ToolDef(
        name="x", executable="echo",
        params=[
            ParamDef(
                id="p", label="P",
                type=ParamType.STRING, widget=Widget.TEXT,
            ),
        ],
    )
    p = tmp_path / "demo.scriptree"
    save_tool(tool, p)
    from scriptree.core.io import load_tool
    return load_tool(p)


class TestInjectToolDirEnv:

    def test_sets_scriptree_tool_dir_to_loaded_parent(
        self, tmp_path: Path,
    ) -> None:
        tool = _make_tool(tmp_path)
        env = inject_tool_dir_env(None, tool, base_env={})
        assert env is not None
        assert env["SCRIPTREE_TOOL_DIR"] == str(tmp_path.resolve())

    def test_prepends_to_pythonpath_when_unset(
        self, tmp_path: Path,
    ) -> None:
        tool = _make_tool(tmp_path)
        env = inject_tool_dir_env(None, tool, base_env={})
        assert env["PYTHONPATH"] == str(tmp_path.resolve())

    def test_prepends_to_existing_pythonpath(self, tmp_path: Path) -> None:
        tool = _make_tool(tmp_path)
        env = inject_tool_dir_env(
            {"PYTHONPATH": "C:\\existing"}, tool, base_env={},
        )
        parts = env["PYTHONPATH"].split(os.pathsep)
        assert parts[0] == str(tmp_path.resolve())
        assert "C:\\existing" in parts

    def test_idempotent_when_tool_dir_already_at_front(
        self, tmp_path: Path,
    ) -> None:
        tool = _make_tool(tmp_path)
        first = inject_tool_dir_env(None, tool, base_env={})
        # Apply twice — must not duplicate the entry.
        second = inject_tool_dir_env(first, tool, base_env={})
        # Only one occurrence of the tool dir at the front.
        parts = second["PYTHONPATH"].split(os.pathsep)
        assert parts.count(str(tmp_path.resolve())) == 1

    def test_does_not_clobber_user_set_scriptree_tool_dir(
        self, tmp_path: Path,
    ) -> None:
        """A wrapper script that already set SCRIPTREE_TOOL_DIR (e.g.
        a meta-tool that runs sub-tools) should keep its value."""
        tool = _make_tool(tmp_path)
        env = inject_tool_dir_env(
            {"SCRIPTREE_TOOL_DIR": "C:\\wrapper-set"},
            tool, base_env={},
        )
        assert env["SCRIPTREE_TOOL_DIR"] == "C:\\wrapper-set"

    def test_no_loaded_from_no_executable_returns_input(self) -> None:
        """A bare in-memory ToolDef with no loaded_from and no
        executable: there's no folder to derive — return input as-is."""
        tool = ToolDef(name="x", executable="")
        # No-op path.
        out = inject_tool_dir_env(None, tool)
        assert out is None
        out = inject_tool_dir_env({"K": "v"}, tool)
        assert out == {"K": "v"}

    def test_uses_executable_dir_as_fallback(self, tmp_path: Path) -> None:
        """If loaded_from is None but executable is an absolute path,
        fall back to its parent dir."""
        exe = tmp_path / "tool.exe"
        exe.write_text("", encoding="utf-8")
        tool = ToolDef(name="x", executable=str(exe))
        # loaded_from defaults to None
        env = inject_tool_dir_env(None, tool, base_env={})
        assert env["SCRIPTREE_TOOL_DIR"] == str(tmp_path.resolve())


# ===========================================================================
# Wiring — build_full_argv applies the injection
# ===========================================================================

class TestBuildFullArgvIntegration:

    def test_resolved_command_carries_tool_dir_env(
        self, tmp_path: Path,
    ) -> None:
        tool = _make_tool(tmp_path)
        cmd = build_full_argv(tool, {"p": "hi"}, [])
        assert cmd.env is not None
        assert cmd.env["SCRIPTREE_TOOL_DIR"] == str(tmp_path.resolve())
        assert cmd.env["PYTHONPATH"].startswith(str(tmp_path.resolve()))

    def test_tool_env_still_wins_over_injection(
        self, tmp_path: Path,
    ) -> None:
        """When the tool itself sets SCRIPTREE_TOOL_DIR or PYTHONPATH
        in its ``env`` field, those values must persist (the user is
        explicitly overriding the default)."""
        tool = _make_tool(tmp_path)
        tool.env = {"SCRIPTREE_TOOL_DIR": "C:\\custom"}
        cmd = build_full_argv(tool, {"p": "hi"}, [])
        assert cmd.env["SCRIPTREE_TOOL_DIR"] == "C:\\custom"


# ===========================================================================
# Layer 1 (end-to-end) — bundled-Python sibling import works
# ===========================================================================

# Locate the bundled Python.  Skipped on systems without it.
_BUNDLED_PY = (
    Path(__file__).resolve().parents[1] / "lib" / "python" / "python.exe"
)


@pytest.mark.skipif(
    sys.platform != "win32" or not _BUNDLED_PY.is_file(),
    reason="Requires the bundled Windows embeddable Python.",
)
class TestBundledPythonSiblingImport:
    """End-to-end: spawn the bundled python.exe with an argv pointing
    at a multi-file tool and assert the sibling import resolves.

    These tests are the ground truth that the user-reported bug is
    fixed.  Without ``sitecustomize.py`` they would reproduce the
    original ``ModuleNotFoundError``."""

    def _make_tool_layout(self, tmp_path: Path) -> Path:
        helper = tmp_path / "_sibling_helper.py"
        helper.write_text(
            "def hello():\n    return 'sibling-import-ok'\n",
            encoding="utf-8",
        )
        main = tmp_path / "main.py"
        main.write_text(
            "import _sibling_helper\nprint(_sibling_helper.hello())\n",
            encoding="utf-8",
        )
        return main

    def test_sibling_import_works_via_argv0(self, tmp_path: Path) -> None:
        """When sys.argv[0] points at the script, sitecustomize.py
        prepends its parent dir to sys.path."""
        main = self._make_tool_layout(tmp_path)
        result = subprocess.run(
            [str(_BUNDLED_PY), str(main)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, (
            f"bundled python failed:\nstdout={result.stdout!r}\n"
            f"stderr={result.stderr!r}"
        )
        assert "sibling-import-ok" in result.stdout

    def test_sibling_import_works_via_scriptree_tool_dir(
        self, tmp_path: Path,
    ) -> None:
        """Even when the script is moved out of its folder (so argv[0]
        wouldn't help), SCRIPTREE_TOOL_DIR pointing at the right
        folder must make the sibling import work."""
        # Build the layout in tmp_path/tool/ and run a script from
        # tmp_path/runner/ that does the same import.
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        helper = tool_dir / "_sibling_helper.py"
        helper.write_text(
            "def hello():\n    return 'env-var-resolution-ok'\n",
            encoding="utf-8",
        )
        runner = tmp_path / "runner.py"
        runner.write_text(
            "import _sibling_helper\nprint(_sibling_helper.hello())\n",
            encoding="utf-8",
        )
        env = {**os.environ, "SCRIPTREE_TOOL_DIR": str(tool_dir)}
        result = subprocess.run(
            [str(_BUNDLED_PY), str(runner)],
            capture_output=True, text=True, timeout=30, env=env,
        )
        assert result.returncode == 0, (
            f"bundled python failed:\nstdout={result.stdout!r}\n"
            f"stderr={result.stderr!r}"
        )
        assert "env-var-resolution-ok" in result.stdout
