"""Tests for scriptree.core.runner."""
from __future__ import annotations

import sys

import pytest

from scriptree.core.model import (
    ParamDef,
    ParamType,
    ToolDef,
    Widget,
)
from scriptree.core.runner import (
    ResolvedCommand,
    RunnerError,
    resolve,
    spawn_streaming,
)


def _tool(template: list[str], params: list[ParamDef]) -> ToolDef:
    return ToolDef(
        name="t",
        executable="/usr/bin/echo",
        argument_template=template,
        params=params,
    )


class TestResolvePositional:
    def test_simple_substitution(self) -> None:
        tool = _tool(["{name}"], [ParamDef(id="name")])
        cmd = resolve(tool, {"name": "hello"})
        assert cmd.argv == ["/usr/bin/echo", "hello"]

    def test_literal_tokens_pass_through(self) -> None:
        tool = _tool(
            ["--mode", "fast", "{x}"],
            [ParamDef(id="x")],
        )
        cmd = resolve(tool, {"x": "42"})
        assert cmd.argv == ["/usr/bin/echo", "--mode", "fast", "42"]

    def test_embedded_substitution(self) -> None:
        tool = _tool(["--name={name}"], [ParamDef(id="name")])
        cmd = resolve(tool, {"name": "bob"})
        assert cmd.argv == ["/usr/bin/echo", "--name=bob"]

    def test_empty_embedded_drops_whole_token(self) -> None:
        tool = _tool(["--name={name}"], [ParamDef(id="name")])
        cmd = resolve(tool, {"name": ""})
        assert cmd.argv == ["/usr/bin/echo"]

    def test_unknown_param_reference_raises(self) -> None:
        tool = _tool(["{missing}"], [])
        with pytest.raises(RunnerError, match="unknown parameter"):
            resolve(tool, {})


class TestResolveRequired:
    def test_missing_required_raises(self) -> None:
        tool = _tool(
            ["{name}"],
            [ParamDef(id="name", required=True)],
        )
        with pytest.raises(RunnerError, match="Required"):
            resolve(tool, {"name": ""})

    def test_missing_required_ok_for_preview(self) -> None:
        tool = _tool(
            ["--name={name}"],
            [ParamDef(id="name", required=True)],
        )
        cmd = resolve(tool, {"name": ""}, ignore_required=True)
        # Empty embedded substitution still drops the token.
        assert cmd.argv == ["/usr/bin/echo"]


class TestResolveConditionalFlag:
    def _bool_tool(self) -> ToolDef:
        return _tool(
            ["{verbose?--verbose}"],
            [ParamDef(id="verbose", type=ParamType.BOOL, widget=Widget.CHECKBOX)],
        )

    def test_true_emits_flag(self) -> None:
        cmd = resolve(self._bool_tool(), {"verbose": True})
        assert cmd.argv == ["/usr/bin/echo", "--verbose"]

    def test_false_drops_flag(self) -> None:
        cmd = resolve(self._bool_tool(), {"verbose": False})
        assert cmd.argv == ["/usr/bin/echo"]

    def test_string_truthy(self) -> None:
        cmd = resolve(self._bool_tool(), {"verbose": "yes"})
        assert cmd.argv == ["/usr/bin/echo", "--verbose"]

    def test_conditional_embedded_raises(self) -> None:
        tool = _tool(
            ["prefix{v?--v}"],
            [ParamDef(id="v", type=ParamType.BOOL, widget=Widget.CHECKBOX)],
        )
        with pytest.raises(RunnerError, match="standalone token"):
            resolve(tool, {"v": True})


class TestResolveConditionalFlagValue:
    def test_flag_equals_emits_with_value(self) -> None:
        tool = _tool(
            ["{model?--model=}"],
            [ParamDef(id="model")],
        )
        cmd = resolve(tool, {"model": "opus"})
        assert cmd.argv == ["/usr/bin/echo", "--model=opus"]

    def test_flag_equals_drops_when_empty(self) -> None:
        tool = _tool(
            ["{model?--model=}"],
            [ParamDef(id="model")],
        )
        cmd = resolve(tool, {"model": ""})
        assert cmd.argv == ["/usr/bin/echo"]


class TestTokenGroups:
    """A token group (list[str]) emits all-or-nothing.

    This is the key feature that makes Windows-style flags like
    ``/S system`` expressible — two argv tokens that must appear
    together or not at all.
    """

    def _group_tool(self) -> ToolDef:
        return _tool(
            template=[
                ["/S", "{system}"],
                "{verbose?/V}",
                ["/U", "{user}"],
            ],
            params=[
                ParamDef(id="system"),
                ParamDef(
                    id="verbose",
                    type=ParamType.BOOL,
                    widget=Widget.CHECKBOX,
                    default=False,
                ),
                ParamDef(id="user"),
            ],
        )

    def test_group_emits_both_tokens_when_value_set(self) -> None:
        cmd = resolve(
            self._group_tool(),
            {"system": "SERVER01", "verbose": False, "user": ""},
        )
        assert cmd.argv == ["/usr/bin/echo", "/S", "SERVER01"]

    def test_group_drops_entirely_when_value_empty(self) -> None:
        cmd = resolve(
            self._group_tool(),
            {"system": "", "verbose": False, "user": ""},
        )
        assert cmd.argv == ["/usr/bin/echo"]

    def test_multiple_groups_independent(self) -> None:
        cmd = resolve(
            self._group_tool(),
            {"system": "SERVER01", "verbose": True, "user": "alice"},
        )
        assert cmd.argv == ["/usr/bin/echo", "/S", "SERVER01", "/V", "/U", "alice"]

    def test_group_with_literal_only_always_emits(self) -> None:
        tool = _tool(
            template=[["literal", "tokens"]],
            params=[],
        )
        cmd = resolve(tool, {})
        assert cmd.argv == ["/usr/bin/echo", "literal", "tokens"]

    def test_required_missing_inside_group_still_raises(self) -> None:
        tool = _tool(
            template=[["/S", "{system}"]],
            params=[ParamDef(id="system", required=True)],
        )
        with pytest.raises(RunnerError, match="Required"):
            resolve(tool, {"system": ""})


class TestResolveCwd:
    def test_explicit_working_dir(self) -> None:
        tool = _tool([], [])
        tool.working_directory = "/tmp"
        cmd = resolve(tool, {})
        assert cmd.cwd == "/tmp"

    def test_default_cwd_is_exe_dir(self) -> None:
        tool = _tool([], [])
        cmd = resolve(tool, {})
        # /usr/bin/echo → cwd /usr/bin
        assert cmd.cwd is not None
        assert cmd.cwd.endswith("bin")


class TestDisplay:
    def test_display_quotes_spaces(self) -> None:
        """Quoting is platform-specific: single quotes on POSIX
        (shlex.quote), double quotes on Windows (list2cmdline)."""
        import sys
        cmd = ResolvedCommand(argv=["echo", "hello world"], cwd=None)
        if sys.platform == "win32":
            assert cmd.display() == 'echo "hello world"'
        else:
            assert cmd.display() == "echo 'hello world'"


class TestSpawnStreaming:
    """Integration test for the actual subprocess runner.

    Uses ``python -c ...`` so the test is portable across Windows and
    Linux — no reliance on /usr/bin/echo actually existing.
    """

    def test_captures_stdout_and_exit_code(self) -> None:
        cmd = ResolvedCommand(
            argv=[sys.executable, "-c", "print('hi'); print('there')"],
            cwd=None,
        )
        lines: list[str] = []
        err_lines: list[str] = []
        result = spawn_streaming(cmd, lines.append, err_lines.append)
        assert result.exit_code == 0
        assert "hi" in lines
        assert "there" in lines

    def test_captures_stderr(self) -> None:
        cmd = ResolvedCommand(
            argv=[
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('oops\\n'); sys.exit(2)",
            ],
            cwd=None,
        )
        out: list[str] = []
        err: list[str] = []
        result = spawn_streaming(cmd, out.append, err.append)
        assert result.exit_code == 2
        assert any("oops" in line for line in err)
