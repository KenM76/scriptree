"""Tests for tool + per-configuration environment overrides.

Covers:
- ToolDef.env / ToolDef.path_prepend round-trip through io.py
- Configuration.env / .path_prepend round-trip through configs.py
- core.runner.build_env layering rules (os.environ → tool → config)
- PATH prepend resolution (absolute vs. relative to working_directory)
- build_full_argv passing env through to ResolvedCommand
- EnvEditorDialog parse helpers (KEY=value, comments, validation)
"""
from __future__ import annotations

import os
from pathlib import Path

from scriptree.core.configs import (
    Configuration,
    configs_from_dict,
    configs_to_dict,
    load_configs,
    save_configs,
)
from scriptree.core.io import load_tool, save_tool, tool_from_dict, tool_to_dict
from scriptree.core.model import ParamDef, ToolDef
from scriptree.core.runner import build_env, build_full_argv
from scriptree.ui.env_editor import _env_to_text, _is_valid_env_key, _parse_env, _parse_paths


def _tool(**kw) -> ToolDef:
    return ToolDef(
        name="demo",
        executable="/bin/echo",
        argument_template=["{name}"],
        params=[ParamDef(id="name", label="Name", default="hello")],
        **kw,
    )


# --- model / io ------------------------------------------------------------


class TestToolEnvRoundTrip:
    def test_default_env_is_empty(self) -> None:
        tool = _tool()
        assert tool.env == {}
        assert tool.path_prepend == []

    def test_empty_env_not_emitted(self) -> None:
        d = tool_to_dict(_tool())
        assert "env" not in d
        assert "path_prepend" not in d

    def test_env_round_trip(self, tmp_path: Path) -> None:
        tool = _tool(
            env={"MY_VAR": "hello", "API_KEY": "secret"},
            path_prepend=["C:/tools/bin", "./vendor"],
        )
        p = tmp_path / "t.scriptree"
        save_tool(tool, p)
        reloaded = load_tool(p)
        assert reloaded.env == {"MY_VAR": "hello", "API_KEY": "secret"}
        assert reloaded.path_prepend == ["C:/tools/bin", "./vendor"]

    def test_legacy_file_loads_clean(self) -> None:
        v2 = {
            "schema_version": 2,
            "name": "legacy",
            "executable": "/bin/true",
            "params": [],
            "source": {"mode": "manual"},
        }
        tool = tool_from_dict(v2)
        assert tool.env == {}
        assert tool.path_prepend == []


class TestConfigEnvRoundTrip:
    def test_empty_env_not_emitted(self) -> None:
        cfg = Configuration(name="default")
        d = configs_to_dict(
            configs_from_dict({
                "schema_version": 1,
                "configurations": [{"name": "default"}],
            })
        )
        assert "env" not in d["configurations"][0]
        assert "path_prepend" not in d["configurations"][0]

    def test_env_round_trip(self, tmp_path: Path) -> None:
        from scriptree.core.configs import ConfigurationSet
        s = ConfigurationSet(
            active="default",
            configurations=[
                Configuration(
                    name="default",
                    env={"DEBUG": "1"},
                    path_prepend=["./bin"],
                )
            ],
        )
        tool_path = tmp_path / "t.scriptree"
        save_configs(tool_path, s)
        loaded = load_configs(tool_path)
        assert loaded.configurations[0].env == {"DEBUG": "1"}
        assert loaded.configurations[0].path_prepend == ["./bin"]


# --- build_env layering ----------------------------------------------------


class TestBuildEnv:
    def test_returns_none_when_no_overrides(self) -> None:
        tool = _tool()
        assert build_env(tool) is None

    def test_tool_env_layered_on_base(self) -> None:
        tool = _tool(env={"FOO": "tool"})
        base = {"FOO": "base", "BAR": "base"}
        env = build_env(tool, base_env=base)
        assert env is not None
        assert env["FOO"] == "tool"
        assert env["BAR"] == "base"  # inherited from base

    def test_config_env_overrides_tool(self) -> None:
        tool = _tool(env={"FOO": "tool", "BAR": "tool"})
        env = build_env(
            tool,
            config_env={"BAR": "config"},
            base_env={"FOO": "base"},
        )
        assert env["FOO"] == "tool"
        assert env["BAR"] == "config"

    def test_path_prepend_order(self) -> None:
        tool = _tool(path_prepend=["/tool/path"])
        env = build_env(
            tool,
            config_path_prepend=["/config/path"],
            base_env={"PATH": "/usr/bin"},
        )
        assert env is not None
        parts = env["PATH"].split(os.pathsep)
        # Tool first, config second, then existing PATH.
        # Use suffix check since Windows may Path.resolve() normalize separators.
        assert parts[-1] == "/usr/bin"
        assert len(parts) == 3

    def test_relative_path_resolved_against_working_dir(
        self, tmp_path: Path
    ) -> None:
        work = tmp_path / "work"
        work.mkdir()
        tool = _tool(path_prepend=["./subdir"])
        tool.working_directory = str(work)
        env = build_env(tool, base_env={"PATH": ""})
        assert env is not None
        resolved = env["PATH"].split(os.pathsep)[0]
        assert Path(resolved) == (work / "subdir").resolve()

    def test_absolute_path_kept_as_is(self, tmp_path: Path) -> None:
        abs_dir = str(tmp_path / "abs")
        tool = _tool(path_prepend=[abs_dir])
        env = build_env(tool, base_env={"PATH": ""})
        assert env is not None
        assert env["PATH"].split(os.pathsep)[0] == abs_dir

    def test_empty_base_path_means_prepend_only(self, tmp_path: Path) -> None:
        # Use absolute paths so the test is cross-platform — on Windows
        # "/a" is not actually absolute and would be resolved against
        # the anchor dir.
        a, b = str(tmp_path / "a"), str(tmp_path / "b")
        tool = _tool(path_prepend=[a, b])
        env = build_env(tool, base_env={})
        assert env is not None
        # When there was no prior PATH at all, the result is just the
        # prepended entries joined (2 entries, no trailing inherited
        # PATH segment).
        parts = env["PATH"].split(os.pathsep)
        assert len(parts) == 2
        assert parts[0] == a and parts[1] == b


class TestBuildFullArgvPassesEnv:
    def test_no_env_gives_none(self) -> None:
        tool = _tool()
        cmd = build_full_argv(tool, {"name": "x"}, [])
        assert cmd.env is None

    def test_with_tool_env_env_present(self) -> None:
        tool = _tool(env={"K": "v"})
        cmd = build_full_argv(tool, {"name": "x"}, [])
        assert cmd.env is not None
        assert cmd.env["K"] == "v"

    def test_config_env_merged(self) -> None:
        tool = _tool(env={"A": "1"})
        cmd = build_full_argv(
            tool,
            {"name": "x"},
            [],
            config_env={"B": "2"},
        )
        assert cmd.env["A"] == "1"
        assert cmd.env["B"] == "2"


# --- EnvEditorDialog parsing helpers --------------------------------------


class TestParseEnv:
    def test_simple_kv(self) -> None:
        assert _parse_env("FOO=bar") == {"FOO": "bar"}

    def test_multiple_lines(self) -> None:
        assert _parse_env("A=1\nB=2") == {"A": "1", "B": "2"}

    def test_blank_and_comment_lines_ignored(self) -> None:
        text = "# comment\nA=1\n\n# another\nB=2\n"
        assert _parse_env(text) == {"A": "1", "B": "2"}

    def test_whitespace_trimmed(self) -> None:
        assert _parse_env("  FOO  =  bar  ") == {"FOO": "bar"}

    def test_value_may_contain_equals(self) -> None:
        assert _parse_env("URL=https://a.com/?x=1") == {
            "URL": "https://a.com/?x=1"
        }

    def test_missing_equals_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="expected KEY=value"):
            _parse_env("FOO bar")

    def test_invalid_key_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="invalid variable name"):
            _parse_env("1FOO=x")
        with pytest.raises(ValueError, match="invalid variable name"):
            _parse_env("FOO-BAR=x")

    def test_empty_value_allowed(self) -> None:
        # Empty value is legit — this unsets / blanks the variable.
        assert _parse_env("FOO=") == {"FOO": ""}

    def test_empty_text_gives_empty_dict(self) -> None:
        assert _parse_env("") == {}


class TestParsePaths:
    def test_simple_list(self) -> None:
        assert _parse_paths("C:/a\nC:/b") == ["C:/a", "C:/b"]

    def test_blank_and_comment_lines_ignored(self) -> None:
        text = "# comment\nC:/a\n\n# more\nC:/b\n"
        assert _parse_paths(text) == ["C:/a", "C:/b"]

    def test_trims_whitespace(self) -> None:
        assert _parse_paths("  C:/a  ") == ["C:/a"]


class TestEnvToText:
    def test_preserves_order(self) -> None:
        text = _env_to_text({"A": "1", "B": "2"})
        assert text == "A=1\nB=2"


class TestIsValidEnvKey:
    def test_valid(self) -> None:
        assert _is_valid_env_key("FOO")
        assert _is_valid_env_key("_FOO")
        assert _is_valid_env_key("FOO_BAR_1")

    def test_invalid(self) -> None:
        assert not _is_valid_env_key("")
        assert not _is_valid_env_key("1FOO")
        assert not _is_valid_env_key("FOO-BAR")
        assert not _is_valid_env_key("FOO BAR")
