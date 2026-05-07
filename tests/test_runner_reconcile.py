"""Tests for scriptree.core.runner.reconcile_edit.

These are pure-Python tests — no Qt, no filesystem. They pin the
reverse-parse semantics of the editable command-line preview so I
catch regressions when the ReconcileResult layout or the template
grammar changes.

The algorithm is documented in the ``reconcile_edit`` docstring;
these tests cover:

- Flag groups (position-independent match)
- Conditional bool flags (presence/absence)
- Conditional flag-value form ``{name?--name=}``
- Bare positional params (sequential, flag-skipping)
- Literals (sequential, user-removed literals don't crash)
- Extras — unmatched tokens flow through
- Reordering flags still matches (pass 1 is position-independent)
- Shlex parse failure (unclosed quote) returns ok=False
"""
from __future__ import annotations

from scriptree.core.model import ParamDef, ParamType, ToolDef, Widget
from scriptree.core.runner import (
    build_full_argv,
    reconcile_edit,
    resolve,
)


# --- helpers --------------------------------------------------------------

def _tasklist_tool() -> ToolDef:
    """The same shape winhelp produces for tasklist /?."""
    return ToolDef(
        name="tasklist",
        executable="C:/Windows/SysWOW64/tasklist.exe",
        argument_template=[
            ["/S", "{system}"],
            ["/U", "{user}"],
            ["/P", "{password}"],
            ["/M", "{module}"],
            "{svc?/SVC}",
            "{apps?/APPS}",
            "{v?/V}",
            ["/FI", "{filter}"],
            ["/FO", "{format}"],
            "{nh?/NH}",
        ],
        params=[
            ParamDef(id="system"),
            ParamDef(id="user"),
            ParamDef(id="password"),
            ParamDef(id="module"),
            ParamDef(id="svc", type=ParamType.BOOL, widget=Widget.CHECKBOX, default=False),
            ParamDef(id="apps", type=ParamType.BOOL, widget=Widget.CHECKBOX, default=False),
            ParamDef(id="v", type=ParamType.BOOL, widget=Widget.CHECKBOX, default=False),
            ParamDef(id="filter"),
            ParamDef(
                id="format",
                type=ParamType.ENUM,
                widget=Widget.DROPDOWN,
                choices=["TABLE", "LIST", "CSV"],
                default="TABLE",
            ),
            ParamDef(id="nh", type=ParamType.BOOL, widget=Widget.CHECKBOX, default=False),
        ],
    )


def _sw_bridge_tool() -> ToolDef:
    """list-components shape: literals + positional bare subs."""
    return ToolDef(
        name="sw_bridge list-components",
        executable="C:/x/sw_bridge.exe",
        argument_template=["list-components", "{title}", "{output}"],
        params=[
            ParamDef(id="title", required=True),
            ParamDef(id="output", required=True),
        ],
    )


def _dxf_tool() -> ToolDef:
    """dxf_export shape: literal flags interleaved with positional subs."""
    return ToolDef(
        name="dxf-export",
        executable="C:/py.exe",
        argument_template=[
            "-3.12",
            "run_dxf_export.py",
            "--output-dir",
            "{output_dir}",
            "--config",
            "{config}",
            "{no_pdf?--no-pdf}",
        ],
        params=[
            ParamDef(id="output_dir", required=True),
            ParamDef(id="config", required=True, default="KIT"),
            ParamDef(
                id="no_pdf",
                type=ParamType.BOOL,
                widget=Widget.CHECKBOX,
                default=False,
            ),
        ],
    )


def _defaults(tool: ToolDef) -> dict:
    return {p.id: p.default for p in tool.params}


# --- pass 1: flag groups --------------------------------------------------

class TestFlagGroups:
    def test_group_match_updates_value(self) -> None:
        tool = _tasklist_tool()
        r = reconcile_edit(tool, "tasklist.exe /S SERVER01 /FO TABLE", _defaults(tool))
        assert r.ok
        assert r.values["system"] == "SERVER01"
        assert r.extras == []

    def test_group_absence_leaves_value_alone(self) -> None:
        tool = _tasklist_tool()
        current = _defaults(tool)
        current["system"] = "old"  # user had typed this earlier
        r = reconcile_edit(tool, "tasklist.exe /FO TABLE", current)
        # /S not in the command, so system should still be "old" —
        # group entries don't explicitly clear.
        assert r.values["system"] == "old"

    def test_reordered_flags_still_match(self) -> None:
        tool = _tasklist_tool()
        r = reconcile_edit(
            tool,
            "tasklist.exe /U alice /S SERVER /FO CSV",
            _defaults(tool),
        )
        assert r.values["user"] == "alice"
        assert r.values["system"] == "SERVER"
        assert r.values["format"] == "CSV"
        assert r.extras == []


# --- pass 1: conditional bool flags ---------------------------------------

class TestConditionalBoolFlags:
    def test_bool_flag_presence_sets_true(self) -> None:
        tool = _tasklist_tool()
        r = reconcile_edit(
            tool, "tasklist.exe /SVC /FO TABLE", _defaults(tool)
        )
        assert r.values["svc"] is True

    def test_bool_flag_absence_sets_false(self) -> None:
        tool = _tasklist_tool()
        current = _defaults(tool)
        current["svc"] = True  # user had checked it
        r = reconcile_edit(tool, "tasklist.exe /FO TABLE", current)
        assert r.values["svc"] is False

    def test_substring_flags_dont_collide(self) -> None:
        """/V is a substring of /SVC but must not match /SVC as a token."""
        tool = _tasklist_tool()
        r = reconcile_edit(
            tool, "tasklist.exe /SVC /FO TABLE", _defaults(tool)
        )
        assert r.values["svc"] is True
        assert r.values["v"] is False


# --- pass 1: conditional flag=value form ----------------------------------

class TestConditionalEqForm:
    def _eq_tool(self) -> ToolDef:
        return ToolDef(
            name="t",
            executable="/bin/t",
            argument_template=["{model?--model=}"],
            params=[ParamDef(id="model")],
        )

    def test_match_extracts_value(self) -> None:
        tool = self._eq_tool()
        r = reconcile_edit(tool, "t --model=opus", _defaults(tool))
        assert r.values["model"] == "opus"

    def test_absence_clears(self) -> None:
        tool = self._eq_tool()
        current = {"model": "old"}
        r = reconcile_edit(tool, "t", current)
        assert r.values["model"] == ""


# --- pass 2: positionals and literals -------------------------------------

class TestPositionals:
    def test_sw_bridge_positionals(self) -> None:
        tool = _sw_bridge_tool()
        r = reconcile_edit(
            tool,
            "sw_bridge.exe list-components my_asm out.txt",
            _defaults(tool),
        )
        assert r.values["title"] == "my_asm"
        assert r.values["output"] == "out.txt"
        assert r.extras == []

    def test_positional_refuses_flag_looking_token(self) -> None:
        """If the user deletes a positional, the next flag must not be
        eaten as its replacement value."""
        tool = _dxf_tool()
        current = _defaults(tool)
        # User removed the output_dir value AND its --output-dir flag.
        r = reconcile_edit(
            tool,
            "py.exe -3.12 run_dxf_export.py --config Default",
            current,
        )
        # output_dir should NOT have been set to "--config".
        assert r.values["output_dir"] != "--config"
        assert r.values["config"] == "Default"

    def test_positional_with_literal_flag_preserved(self) -> None:
        """The common edit: just change a value."""
        tool = _dxf_tool()
        current = _defaults(tool)
        r = reconcile_edit(
            tool,
            "py.exe -3.12 run_dxf_export.py --output-dir D:/NEW --config KIT",
            current,
        )
        assert r.values["output_dir"] == "D:/NEW"
        assert r.values["config"] == "KIT"
        assert r.extras == []

    def test_literal_user_deleted(self) -> None:
        """If the user deletes a literal token the reconciler skips it."""
        tool = _sw_bridge_tool()
        r = reconcile_edit(
            tool, "sw_bridge.exe foo bar", _defaults(tool)
        )
        # "list-components" literal was deleted; "foo" becomes title,
        # "bar" becomes output.
        assert r.values["title"] == "foo"
        assert r.values["output"] == "bar"


# --- extras ---------------------------------------------------------------

class TestExtras:
    def test_unknown_tokens_become_extras(self) -> None:
        tool = _tasklist_tool()
        r = reconcile_edit(
            tool,
            "tasklist.exe /FO CSV /EXTRA /WEIRD thing",
            _defaults(tool),
        )
        assert r.values["format"] == "CSV"
        assert r.extras == ["/EXTRA", "/WEIRD", "thing"]

    def test_extras_preserved_across_known_edits(self) -> None:
        """Editing known params doesn't touch the unknown tokens."""
        tool = _tasklist_tool()
        r = reconcile_edit(
            tool,
            'tasklist.exe /FO LIST --debug 2 /NH',
            _defaults(tool),
        )
        assert r.values["format"] == "LIST"
        assert r.values["nh"] is True
        assert "--debug" in r.extras
        assert "2" in r.extras


# --- shlex failure mode ---------------------------------------------------

class TestParseFailure:
    def test_unclosed_quote_returns_not_ok(self) -> None:
        tool = _tasklist_tool()
        r = reconcile_edit(
            tool, 'tasklist.exe /FI "unterminated', _defaults(tool)
        )
        assert r.ok is False
        # Values returned are the starting state.
        assert r.values == _defaults(tool)


# --- build_full_argv helper ----------------------------------------------

class TestBuildFullArgv:
    def test_extras_appended(self) -> None:
        tool = _tasklist_tool()
        values = _defaults(tool)
        values["svc"] = True
        cmd = build_full_argv(
            tool, values, extras=["--debug", "2"], ignore_required=True
        )
        # GUI argv first, extras appended at the end.
        assert cmd.argv[0].endswith("tasklist.exe")
        assert "/SVC" in cmd.argv
        assert cmd.argv[-2:] == ["--debug", "2"]

    def test_no_extras_matches_resolve(self) -> None:
        tool = _tasklist_tool()
        values = _defaults(tool)
        a = resolve(tool, values, ignore_required=True)
        b = build_full_argv(tool, values, extras=[], ignore_required=True)
        assert a.argv == b.argv
        assert a.cwd == b.cwd
