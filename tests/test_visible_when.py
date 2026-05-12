"""Tests for the v0.4.0 ``visible_when`` / ``required_when`` feature.

Two layers tested:

1. ``scriptree.core.visible_when.evaluate`` — the expression
   evaluator.  Pure function, exhaustive table-style tests for
   every grammar production.

2. ``scriptree.core.runner.resolve`` integration — hidden params
   are exempt from the required check; ``required_when`` makes a
   field required only in some modes.

Plus io round-trip pinning the schema fields.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scriptree.core.io import load_tool, save_tool
from scriptree.core.model import (
    ParamDef, ParamType, ToolDef, Widget,
)
from scriptree.core.runner import RunnerError, build_full_argv
from scriptree.core.visible_when import evaluate


# ===========================================================================
# Evaluator — grammar coverage
# ===========================================================================

class TestEvaluatorBasics:

    def test_empty_string_is_true(self) -> None:
        """An empty expression is the documented "always" sentinel."""
        assert evaluate("", {}) is True
        assert evaluate("   ", {}) is True

    def test_simple_equality(self) -> None:
        assert evaluate("mode == 'verbose'", {"mode": "verbose"}) is True
        assert evaluate("mode == 'verbose'", {"mode": "quiet"}) is False

    def test_simple_inequality(self) -> None:
        assert evaluate("mode != 'verbose'", {"mode": "quiet"}) is True
        assert evaluate("mode != 'verbose'", {"mode": "verbose"}) is False

    def test_in_list(self) -> None:
        v = {"src": "drawing"}
        assert evaluate("src in ('drawing', 'insert')", v) is True
        assert evaluate("src in ('insert', 'auto')", v) is False
        assert evaluate("src in ('drawing')", v) is True  # one-item list

    def test_and(self) -> None:
        v = {"a": "x", "b": "y"}
        assert evaluate("a == 'x' AND b == 'y'", v) is True
        assert evaluate("a == 'x' AND b == 'z'", v) is False

    def test_or(self) -> None:
        v = {"a": "x", "b": "y"}
        assert evaluate("a == 'wrong' OR b == 'y'", v) is True
        assert evaluate("a == 'wrong' OR b == 'wrong'", v) is False

    def test_not(self) -> None:
        v = {"mode": "silent"}
        assert evaluate("NOT (mode == 'silent')", v) is False
        assert evaluate("NOT mode == 'verbose'", v) is True

    def test_parens_override_precedence(self) -> None:
        v = {"a": "x", "b": "y", "c": "z"}
        # Default precedence: AND tighter than OR.
        assert evaluate("a == 'x' OR b == 'wrong' AND c == 'wrong'", v) is True
        # Parens force: (a OR b) AND c.
        assert evaluate(
            "(a == 'x' OR b == 'wrong') AND c == 'wrong'", v,
        ) is False

    def test_keywords_case_insensitive(self) -> None:
        v = {"a": "x", "b": "y"}
        assert evaluate("a == 'x' and b == 'y'", v) is True
        assert evaluate("a == 'x' aNd b == 'y'", v) is True
        assert evaluate("a == 'x' or b == 'z'", v) is True

    def test_bare_token_literal(self) -> None:
        """Unquoted tokens (letters, digits, ``_-.``) work as
        literals — handy for ``bom_type == 3`` style comparisons."""
        v = {"bom_type": "3", "mode": "off"}
        assert evaluate("bom_type == 3", v) is True
        assert evaluate("bom_type == 3", v) is True
        assert evaluate("mode == off", v) is True

    def test_unknown_ident_compares_to_empty(self) -> None:
        """An identifier with no entry in values evaluates to ''."""
        assert evaluate("missing == ''", {}) is True
        assert evaluate("missing == 'x'", {}) is False


# ===========================================================================
# Evaluator — fail-open behaviour
# ===========================================================================

class TestEvaluatorFailOpen:

    def test_syntax_error_returns_true(self) -> None:
        """A typo in a tool's expression must NOT permanently hide
        the field.  The evaluator logs and returns True so the user
        can still see and fix the field."""
        assert evaluate("foo bar baz", {}) is True
        assert evaluate("a == ", {"a": "x"}) is True
        assert evaluate("a in (", {"a": "x"}) is True

    def test_unterminated_string_fails_open(self) -> None:
        assert evaluate("mode == 'oops", {"mode": "x"}) is True

    def test_unexpected_trailing_token_fails_open(self) -> None:
        assert evaluate("a == 'x' garbage", {"a": "x"}) is True


# ===========================================================================
# Schema round-trip
# ===========================================================================

class TestRoundTrip:

    def _tool(self) -> ToolDef:
        return ToolDef(
            name="x", executable="echo",
            params=[
                ParamDef(
                    id="mode", label="M", type=ParamType.STRING,
                    widget=Widget.TEXT, default="quiet",
                ),
                ParamDef(
                    id="message", label="Msg", type=ParamType.STRING,
                    widget=Widget.TEXT,
                    visible_when="mode == 'verbose'",
                    required_when="mode == 'verbose'",
                ),
            ],
        )

    def test_visible_when_round_trips(self, tmp_path: Path) -> None:
        p = tmp_path / "x.scriptree"
        save_tool(self._tool(), p)
        loaded = load_tool(p)
        msg = loaded.params[1]
        assert msg.visible_when == "mode == 'verbose'"
        assert msg.required_when == "mode == 'verbose'"

    def test_default_empty_omitted_from_disk(self, tmp_path: Path) -> None:
        """Tools that don't use visible_when must round-trip
        byte-identically to the v0.3.x form."""
        import json
        tool = ToolDef(
            name="x", executable="echo",
            params=[ParamDef(id="a", label="A")],
        )
        p = tmp_path / "x.scriptree"
        save_tool(tool, p)
        raw = json.loads(p.read_text(encoding="utf-8"))
        assert "visible_when" not in raw["params"][0]
        assert "required_when" not in raw["params"][0]


# ===========================================================================
# Runner integration
# ===========================================================================

class TestRunnerIntegration:

    def _tool(self) -> ToolDef:
        return ToolDef(
            name="x", executable="echo",
            params=[
                ParamDef(
                    id="mode", label="Mode",
                    type=ParamType.STRING, widget=Widget.TEXT,
                    default="quiet",
                ),
                ParamDef(
                    id="message", label="Msg",
                    type=ParamType.STRING, widget=Widget.TEXT,
                    visible_when="mode == 'verbose'",
                    required_when="mode == 'verbose'",
                ),
            ],
            argument_template=["{message?--msg}", "{message}"],
        )

    def test_hidden_param_exempt_from_required(self) -> None:
        """When visible_when hides the field, the required check
        skips it — the user couldn't fill it in even if they
        wanted to."""
        t = self._tool()
        # mode=quiet → message hidden → required check skipped → no raise.
        cmd = build_full_argv(t, {"mode": "quiet", "message": ""}, [])
        # Argv omits message entirely (the {message?--msg} flag
        # token sees an empty value and drops).
        assert cmd.argv == ["echo"]

    def test_required_when_visible_and_empty_raises(self) -> None:
        t = self._tool()
        with pytest.raises(RunnerError) as exc:
            build_full_argv(t, {"mode": "verbose", "message": ""}, [])
        assert "Msg" in str(exc.value)

    def test_required_when_visible_and_filled_passes(self) -> None:
        t = self._tool()
        cmd = build_full_argv(
            t, {"mode": "verbose", "message": "hello"}, [],
        )
        assert cmd.argv == ["echo", "--msg", "hello"]

    def test_required_static_still_works_when_no_required_when(
        self,
    ) -> None:
        """Tools that use plain ``required: True`` and no
        ``required_when`` keep the legacy semantics."""
        t = ToolDef(
            name="x", executable="echo",
            params=[ParamDef(
                id="must", label="Must",
                type=ParamType.STRING, widget=Widget.TEXT,
                required=True,
            )],
            argument_template=["{must}"],
        )
        with pytest.raises(RunnerError):
            build_full_argv(t, {"must": ""}, [])
        cmd = build_full_argv(t, {"must": "ok"}, [])
        assert "ok" in cmd.argv
