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


class TestStringPassthroughAutoSplit:
    """When a template token is exactly ``"{id}"`` and the referenced
    param is ``ParamType.STRING``, the substituted value is treated as
    argv text — multi-token strings expand into multiple argv elements.

    This is the "repeatable-flag" pattern: the user types something
    like ``--include foo --include bar`` into a single text field and
    expects four argv tokens, not one big concatenated string.

    Other contexts (embedded placeholders, token groups, conditional
    flags, non-string param types) keep their existing single-token
    semantics.
    """

    def test_multi_token_string_splits(self) -> None:
        tool = _tool(
            ["{flags}"],
            [ParamDef(id="flags", type=ParamType.STRING)],
        )
        cmd = resolve(tool, {"flags": "--include foo --include bar"})
        assert cmd.argv == [
            "/usr/bin/echo",
            "--include", "foo", "--include", "bar",
        ]

    def test_quoted_phrase_preserved_as_single_token(self) -> None:
        # shlex / CommandLineToArgvW respect quotes — a quoted phrase
        # stays as one argv token even though it contains whitespace.
        tool = _tool(
            ["{flags}"],
            [ParamDef(id="flags", type=ParamType.STRING)],
        )
        cmd = resolve(tool, {"flags": '--name "John Doe" --age 30'})
        assert cmd.argv == [
            "/usr/bin/echo",
            "--name", "John Doe", "--age", "30",
        ]

    def test_single_word_no_split(self) -> None:
        tool = _tool(
            ["{x}"],
            [ParamDef(id="x", type=ParamType.STRING)],
        )
        cmd = resolve(tool, {"x": "hello"})
        assert cmd.argv == ["/usr/bin/echo", "hello"]

    def test_empty_string_drops_token(self) -> None:
        tool = _tool(
            ["{x}", "--end"],
            [ParamDef(id="x", type=ParamType.STRING)],
        )
        cmd = resolve(tool, {"x": ""})
        assert cmd.argv == ["/usr/bin/echo", "--end"]

    def test_path_param_with_spaces_no_split(self) -> None:
        # Path params keep single-token semantics — paths with spaces
        # are atomic, even when the placeholder fills the whole token.
        tool = _tool(
            ["{p}"],
            [ParamDef(
                id="p", type=ParamType.PATH, widget=Widget.FILE_OPEN,
            )],
        )
        cmd = resolve(tool, {"p": r"C:\Program Files\Foo"})
        assert cmd.argv == ["/usr/bin/echo", r"C:\Program Files\Foo"]

    def test_embedded_placeholder_no_split(self) -> None:
        # Embedded placeholders (``--out={x}``) keep current behavior:
        # the value is concatenated into the token, no splitting.
        tool = _tool(
            ["--out={x}"],
            [ParamDef(id="x", type=ParamType.STRING)],
        )
        cmd = resolve(tool, {"x": "a b c"})
        assert cmd.argv == ["/usr/bin/echo", "--out=a b c"]

    def test_token_group_no_split(self) -> None:
        # Inside a token group, a multi-token string occupies one slot
        # of the group (group emits all-or-nothing). The whole value
        # stays as one argv token alongside the group's literal tokens.
        tool = _tool(
            [["--include", "{x}"]],
            [ParamDef(id="x", type=ParamType.STRING)],
        )
        cmd = resolve(tool, {"x": "a b c"})
        assert cmd.argv == ["/usr/bin/echo", "--include", "a b c"]

    def test_bool_param_no_split(self) -> None:
        # Bool params emit "true"/"false" — never split.
        tool = _tool(
            ["{b}"],
            [ParamDef(
                id="b", type=ParamType.BOOL, widget=Widget.CHECKBOX,
            )],
        )
        cmd = resolve(tool, {"b": True})
        assert cmd.argv == ["/usr/bin/echo", "true"]

    def test_conditional_flag_no_split(self) -> None:
        # Conditional placeholders (``{id?--flag}``) take the bool's
        # truthiness and emit a literal flag — splitting doesn't apply
        # because the emitted text is the literal flag, not the value.
        tool = _tool(
            ["{enabled?--flag value with spaces}"],
            [ParamDef(
                id="enabled", type=ParamType.BOOL, widget=Widget.CHECKBOX,
            )],
        )
        cmd = resolve(tool, {"enabled": True})
        # Conditional flag emits the entire ``--flag value with spaces``
        # text as one argv token. (No auto-split — conditional path
        # is exempt by design.)
        assert cmd.argv == [
            "/usr/bin/echo", "--flag value with spaces",
        ]

    def test_unclosed_quote_falls_back_to_single_token(self) -> None:
        # If shlex can't parse the value (unclosed quote), don't crash
        # — emit the raw string as one argv token. The live preview
        # would already flag the issue separately.
        tool = _tool(
            ["{x}"],
            [ParamDef(id="x", type=ParamType.STRING)],
        )
        cmd = resolve(tool, {"x": '--name "unclosed'})
        assert cmd.argv == ["/usr/bin/echo", '--name "unclosed']


class TestEnvVarExpansion:
    """``resolve_tool_path`` expands ``%VAR%`` / ``$VAR`` references in
    paths so tools can reference SCRIPTREE_HOME etc. without hard-coding
    absolute paths.
    """

    def test_executable_expands_env_var(
        self, tmp_path, monkeypatch
    ) -> None:
        # Create a fake "python" inside the env-var location so the
        # exists-check in resolve_tool_path returns the resolved path.
        target = tmp_path / "fake-python.exe"
        target.write_text("fake")
        monkeypatch.setenv("FAKE_LIB", str(tmp_path))
        tool = ToolDef(
            name="t",
            executable="%FAKE_LIB%/fake-python.exe",
            argument_template=[],
        )
        cmd = resolve(tool, {})
        # When env var expands to an existing absolute path, it's
        # returned as-is (after expansion).
        assert cmd.argv[0].endswith("fake-python.exe")
        # The %FAKE_LIB% form must have been expanded.
        assert "%FAKE_LIB%" not in cmd.argv[0]

    def test_unknown_env_var_left_intact(self) -> None:
        # When the env var doesn't resolve, expandvars leaves the
        # %NAME% literal in place — Popen will then fail to find it,
        # which is the correct behavior (don't silently drop).
        tool = ToolDef(
            name="t",
            executable="%DEFINITELY_NOT_SET_XYZ%/foo",
            argument_template=[],
        )
        cmd = resolve(tool, {})
        assert "%DEFINITELY_NOT_SET_XYZ%" in cmd.argv[0]


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
