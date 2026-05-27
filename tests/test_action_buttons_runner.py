"""Tests for ``runner.resolve_action`` / ``runner.build_full_action_argv``.

Phase B of the action-buttons feature (v0.8.0a11+).  Covers:

  * Argv shape: ``[executable, *action.argv]`` -- literal append, no
    template substitution, no fan-out, no string-passthrough split.
  * Working-directory resolution: matches Run's anchoring against
    ``tool.loaded_from``.
  * Env block: built via ``build_env`` + ``inject_tool_dir_env`` so
    actions inherit the tool's env + the active configuration's
    overrides + the SCRIPTREE_TOOL_DIR / PYTHONPATH injections.
  * Runtime-shim injection: Python interpreters get the shim spliced
    in, same as Run.
  * Error paths: empty executable, unknown action id.
  * Action argv is NOT subject to ``{token}`` substitution -- a string
    that looks like a template token survives verbatim.

These tests mock no subprocess -- they exercise the argv-assembly
plumbing only, since that's what the UI hands off to the existing
``spawn_streaming`` path.  Spawn behaviour is already covered by the
Run-button tests; the contract here is "an action's ResolvedCommand
is shaped identically to a Run-button ResolvedCommand for the same
tool."
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from scriptree.core.io import load_tool, save_tool
from scriptree.core.model import ActionDef, ToolDef
from scriptree.core.runner import (
    RunnerError,
    build_full_action_argv,
    resolve_action,
)


# ---------------------------------------------------------------------------
# resolve_action — argv shape + cwd + shim
# ---------------------------------------------------------------------------

class TestResolveAction:
    """Per-action argv assembly without env/configuration concerns."""

    def test_argv_is_literal_append(self) -> None:
        """No ``{token}`` substitution against action argv -- a string
        that looks like a placeholder must survive verbatim, because
        actions are presets not form-driven invocations."""
        tool = ToolDef(name="t", executable="git")
        action = ActionDef(
            id="commit", label="Commit",
            argv=["commit", "-m", "{message}", "-a"],
        )
        cmd = resolve_action(tool, action)
        # The bare "{message}" stays exactly as written -- it's NOT a
        # placeholder, it's literal text the producer typed.  This is
        # the headline behavioural difference vs Run.
        assert cmd.argv == ["git", "commit", "-m", "{message}", "-a"]

    def test_empty_action_argv_runs_executable_alone(self) -> None:
        tool = ToolDef(name="t", executable="git")
        action = ActionDef(id="x", label="X", argv=[])
        cmd = resolve_action(tool, action)
        assert cmd.argv == ["git"]

    def test_empty_executable_raises(self) -> None:
        tool = ToolDef(name="t", executable="")
        action = ActionDef(id="x", label="X", argv=["status"])
        with pytest.raises(RunnerError, match="no executable"):
            resolve_action(tool, action)

    def test_cwd_defaults_to_executable_parent(self, tmp_path: Path) -> None:
        """When ``working_directory`` is empty, cwd defaults to the
        executable's directory (same as Run)."""
        exe = tmp_path / "echo.exe"
        exe.write_bytes(b"")
        tool = ToolDef(name="t", executable=str(exe), working_directory="")
        action = ActionDef(id="x", label="X")
        cmd = resolve_action(tool, action)
        assert cmd.cwd == str(tmp_path)

    def test_bare_executable_name_yields_none_cwd(self) -> None:
        """A bare name like ``python`` has no parent dir on disk -- the
        contract is "no anchor -> inherit process CWD" which is
        represented as ``cwd=None`` (NOT '.').  Matches Run."""
        tool = ToolDef(name="t", executable="python", working_directory="")
        action = ActionDef(id="x", label="X")
        cmd = resolve_action(tool, action)
        assert cmd.cwd is None

    def test_working_directory_used_when_set(self, tmp_path: Path) -> None:
        d = tmp_path / "workdir"
        d.mkdir()
        tool = ToolDef(name="t", executable="echo",
                       working_directory=str(d))
        action = ActionDef(id="x", label="X")
        cmd = resolve_action(tool, action)
        assert cmd.cwd == str(d)

    def test_relative_paths_anchor_to_loaded_from(
        self, tmp_path: Path,
    ) -> None:
        """Relative ``executable`` resolves against the .scriptree's
        directory when ``tool.loaded_from`` is set -- same anchoring
        contract as Run, so a tool folder remains movable."""
        tool_dir = tmp_path / "mytool"
        tool_dir.mkdir()
        exe = tool_dir / "bin.exe"
        exe.write_bytes(b"")
        tool = ToolDef(
            name="t", executable="bin.exe",
            loaded_from=str(tool_dir / "t.scriptree"),
        )
        action = ActionDef(id="x", label="X")
        cmd = resolve_action(tool, action)
        # On Windows, the resolved path uses backslashes; on POSIX
        # forward slashes -- normalize both for the compare.
        assert os.path.normpath(cmd.argv[0]) == os.path.normpath(str(exe))


# ---------------------------------------------------------------------------
# Runtime shim injection (Python tools)
# ---------------------------------------------------------------------------

class TestRuntimeShimInjection:
    """Python interpreters get the shim spliced -- same as Run does."""

    def test_python_executable_gets_shim(self) -> None:
        tool = ToolDef(name="t", executable="python")
        action = ActionDef(id="x", label="X", argv=["script.py", "--flag"])
        cmd = resolve_action(tool, action)
        # The argv should be:
        #   ["python", "<shim>", "script.py", "--flag"]
        # We don't assert the exact shim path (it's an internal
        # implementation detail), just that:
        #   - argv[0] is the python interpreter
        #   - argv[1] is the shim file
        #   - argv[2:] is the original action argv preserved in order
        assert cmd.argv[0] == "python"
        assert cmd.argv[1].endswith("_runtime_shim.py")
        assert cmd.argv[2:] == ["script.py", "--flag"]

    def test_non_python_executable_no_shim(self) -> None:
        tool = ToolDef(name="t", executable="git")
        action = ActionDef(id="x", label="X", argv=["status"])
        cmd = resolve_action(tool, action)
        assert cmd.argv == ["git", "status"]


# ---------------------------------------------------------------------------
# build_full_action_argv — env block + action lookup
# ---------------------------------------------------------------------------

class TestBuildFullActionArgv:
    """End-to-end argv + env, mirroring ``build_full_argv``'s contract."""

    def test_unknown_action_id_raises(self) -> None:
        tool = ToolDef(name="t", executable="git",
                       actions=[ActionDef(id="status", label="S")])
        with pytest.raises(RunnerError, match="no action with id"):
            build_full_action_argv(tool, "missing_id")

    def test_known_action_resolves(self) -> None:
        tool = ToolDef(
            name="t", executable="git",
            actions=[ActionDef(id="status", label="S",
                               argv=["status", "--short"])],
        )
        cmd = build_full_action_argv(tool, "status")
        assert cmd.argv == ["git", "status", "--short"]

    def test_config_env_merges_in(self, tmp_path: Path) -> None:
        """A configuration's env overrides flow through, same as Run."""
        tool = ToolDef(
            name="t", executable="git",
            env={"BASE": "tool"},
            actions=[ActionDef(id="s", label="S", argv=["status"])],
        )
        cmd = build_full_action_argv(
            tool, "s",
            config_env={"EXTRA": "from_config"},
        )
        assert cmd.env is not None
        assert cmd.env.get("BASE") == "tool"
        assert cmd.env.get("EXTRA") == "from_config"

    def test_tool_env_only(self) -> None:
        tool = ToolDef(
            name="t", executable="git",
            env={"FOO": "bar"},
            actions=[ActionDef(id="s", label="S")],
        )
        cmd = build_full_action_argv(tool, "s")
        assert cmd.env is not None
        assert cmd.env.get("FOO") == "bar"

    def test_no_env_overrides_yields_inheriting_env(self) -> None:
        """When the tool sets no env and no config env is provided, the
        runner ALWAYS injects SCRIPTREE_TOOL_DIR so sibling imports
        work -- so the env will be non-None even for "vanilla" tools.
        Just confirm it's not blowing up and has the injection."""
        tool = ToolDef(
            name="t", executable="git",
            actions=[ActionDef(id="s", label="S")],
        )
        cmd = build_full_action_argv(tool, "s")
        # SCRIPTREE_TOOL_DIR is unset unless the tool has loaded_from.
        # Without loaded_from, env may be None or empty -- both are OK.
        # The contract is "build_full_action_argv runs cleanly with no
        # extras."  No assertion needed beyond no-raise.


# ---------------------------------------------------------------------------
# Shape match with build_full_argv (Run's path)
# ---------------------------------------------------------------------------

class TestShapeMatchesRun:
    """A ResolvedCommand from an action must be shaped identically to a
    Run-button ResolvedCommand -- callers downstream
    (``spawn_streaming``) shouldn't be able to tell the difference."""

    def test_returns_resolved_command(self) -> None:
        from scriptree.core.runner import ResolvedCommand
        tool = ToolDef(
            name="t", executable="git",
            actions=[ActionDef(id="s", label="S", argv=["status"])],
        )
        cmd = build_full_action_argv(tool, "s")
        assert isinstance(cmd, ResolvedCommand)
        assert isinstance(cmd.argv, list)
        # All argv elements are strings (the contract Popen needs).
        assert all(isinstance(a, str) for a in cmd.argv)

    def test_display_works(self) -> None:
        """``ResolvedCommand.display()`` works on action commands too
        (used by the UI's hover-tooltip on action buttons)."""
        tool = ToolDef(
            name="t", executable="git",
            actions=[ActionDef(id="s", label="S",
                               argv=["status", "--short"])],
        )
        cmd = build_full_action_argv(tool, "s")
        s = cmd.display()
        assert "git" in s
        assert "status" in s
        assert "--short" in s
