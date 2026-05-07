"""Tests for the Windows-style /? help parser.

The fixture is the actual captured output of ``tasklist /?`` on a
modern Windows 11 system. If Windows ever reformats tasklist's help
this fixture may need updating — but the regex is deliberately
permissive, so minor whitespace shifts won't break it.
"""
from __future__ import annotations

from scriptree.core.model import ParamType, Widget
from scriptree.core.parser.plugins import winhelp
from scriptree.core.parser.probe import parse_text
from scriptree.core.runner import resolve


# Real output of ``C:\\Windows\\SysWOW64\\tasklist.exe /?``.
TASKLIST_HELP = """\
TASKLIST [/S system [/U username [/P [password]]]]
         [/M [module] | /SVC | /V] [/FI filter] [/FO format] [/NH]

Description:
    This tool displays a list of currently running processes on
    either a local or remote machine.

Parameter List:
   /S     system           Specifies the remote system to connect to.

   /U     [domain\\]user    Specifies the user context under which
                           the command should execute.

   /P     [password]       Specifies the password for the given
                           user context. Prompts for input if omitted.

   /M     [module]         Lists all tasks currently using the given
                           exe/dll name. If the module name is not
                           specified all loaded modules are displayed.

   /SVC                    Displays services hosted in each process.

   /APPS                   Displays Store Apps and their associated processes.

   /V                      Displays verbose task information.

   /FI    filter           Displays a set of tasks that match a
                           given criteria specified by the filter.

   /FO    format           Specifies the output format.
                           Valid values: "TABLE", "LIST", "CSV".

   /NH                     Specifies that the "Column Header" should
                           not be displayed in the output.
                           Valid only for "TABLE" and "CSV" formats.

   /?                      Displays this help message.

Filters:
    Filter Name     Valid Operators           Valid Value(s)
    -----------     ---------------           --------------------------
    STATUS          eq, ne                    RUNNING | SUSPENDED

Examples:
    TASKLIST
    TASKLIST /M
"""


class TestDetection:
    def test_detects_tasklist_help(self) -> None:
        assert winhelp.looks_like_windows_help(TASKLIST_HELP)

    def test_rejects_plain_prose(self) -> None:
        assert not winhelp.looks_like_windows_help(
            "Just some regular prose without any flags or headers."
        )

    def test_rejects_argparse_output(self) -> None:
        argparse_help = (
            "usage: foo [-h] [--verbose]\n\noptions:\n  -h, --help  show help\n"
        )
        # argparse has no /flags and no Parameter List header, so
        # winhelp should reject it.
        assert not winhelp.looks_like_windows_help(argparse_help)


class TestTasklistParse:
    def setup_method(self) -> None:
        self.tool = winhelp.detect(TASKLIST_HELP)
        assert self.tool is not None
        self.ids = {p.id for p in self.tool.params}

    def test_source_mode_winhelp(self) -> None:
        assert self.tool.source.mode == "winhelp"

    def test_help_flag_is_skipped(self) -> None:
        # "/?" should not become a parameter.
        assert "?" not in self.ids
        assert "help" not in self.ids

    def test_value_taking_flags_present(self) -> None:
        # /S system, /U [domain\]user, /P [password], /M [module],
        # /FI filter, /FO format — six value-taking flags.
        for expected in ("system", "user", "password", "module", "filter", "format"):
            assert expected in self.ids, f"missing {expected!r}: have {self.ids}"

    def test_bare_flags_present(self) -> None:
        for expected in ("svc", "apps", "v", "nh"):
            assert expected in self.ids, f"missing {expected!r}"

    def test_system_is_text(self) -> None:
        p = self.tool.param_by_id("system")
        assert p.type is ParamType.STRING
        assert p.widget is Widget.TEXT

    def test_svc_is_checkbox_bool(self) -> None:
        p = self.tool.param_by_id("svc")
        assert p.type is ParamType.BOOL
        assert p.widget is Widget.CHECKBOX

    def test_format_is_enum_dropdown(self) -> None:
        """The /FO param should pick up its Valid values from the description."""
        p = self.tool.param_by_id("format")
        assert p.type is ParamType.ENUM
        assert p.widget is Widget.DROPDOWN
        assert set(p.choices) == {"TABLE", "LIST", "CSV"}

    def test_template_has_group_for_system(self) -> None:
        """Value-taking flags must be emitted as [flag, value] groups."""
        # Find the group containing /S.
        groups = [e for e in self.tool.argument_template if isinstance(e, list)]
        flag_literals = [g[0] for g in groups]
        assert "/S" in flag_literals
        # The corresponding group should be ["/S", "{system}"].
        s_group = next(g for g in groups if g[0] == "/S")
        assert s_group == ["/S", "{system}"]

    def test_template_has_conditional_for_bare_flag(self) -> None:
        """Bare flags must be emitted as {id?/FLAG} conditionals."""
        strings = [e for e in self.tool.argument_template if isinstance(e, str)]
        assert "{svc?/SVC}" in strings
        assert "{v?/V}" in strings
        assert "{nh?/NH}" in strings

    def test_template_validates(self) -> None:
        """Every {param_id} in the template resolves to a real param."""
        self.tool.name = "tasklist"
        self.tool.executable = "C:/Windows/SysWOW64/tasklist.exe"
        assert self.tool.validate() == []


class TestTasklistResolve:
    """Use the real runner to confirm the argv comes out the way
    Windows tasklist actually expects it."""

    def setup_method(self) -> None:
        self.tool = winhelp.detect(TASKLIST_HELP)
        assert self.tool is not None
        self.tool.name = "tasklist"
        self.tool.executable = "C:/Windows/SysWOW64/tasklist.exe"

    def test_no_args_just_format(self) -> None:
        """Enum params default to their first choice, so /FO TABLE
        always emits. Everything else drops when empty."""
        values = {p.id: p.default for p in self.tool.params}
        cmd = resolve(self.tool, values)
        assert cmd.argv == [
            "C:/Windows/SysWOW64/tasklist.exe",
            "/FO", "TABLE",
        ]

    def test_svc_plus_default_format(self) -> None:
        values = {p.id: p.default for p in self.tool.params}
        values["svc"] = True
        cmd = resolve(self.tool, values)
        assert cmd.argv == [
            "C:/Windows/SysWOW64/tasklist.exe",
            "/SVC",
            "/FO", "TABLE",
        ]

    def test_user_can_clear_format_to_drop_group(self) -> None:
        """If the user explicitly clears the format, the group drops."""
        values = {p.id: p.default for p in self.tool.params}
        values["format"] = ""
        cmd = resolve(self.tool, values)
        assert cmd.argv == ["C:/Windows/SysWOW64/tasklist.exe"]

    def test_system_with_format(self) -> None:
        values = {p.id: p.default for p in self.tool.params}
        values["system"] = "SERVER01"
        values["format"] = "CSV"
        cmd = resolve(self.tool, values)
        assert cmd.argv == [
            "C:/Windows/SysWOW64/tasklist.exe",
            "/S", "SERVER01",
            "/FO", "CSV",
        ]

    def test_full_remote_query(self) -> None:
        # Matches the last example in tasklist /?:
        # TASKLIST /S system /U username /P password /FO TABLE /NH
        values = {p.id: p.default for p in self.tool.params}
        values["system"] = "SERVER01"
        values["user"] = "alice"
        values["password"] = "secret"
        values["format"] = "TABLE"
        values["nh"] = True
        cmd = resolve(self.tool, values)
        assert cmd.argv == [
            "C:/Windows/SysWOW64/tasklist.exe",
            "/S", "SERVER01",
            "/U", "alice",
            "/P", "secret",
            "/FO", "TABLE",
            "/NH",
        ]


class TestProbeDispatch:
    def test_parse_text_routes_windows_help_to_winhelp(self) -> None:
        tool = parse_text(TASKLIST_HELP)
        assert tool.source.mode == "winhelp"


class TestChoiceExtraction:
    def test_quoted_values(self) -> None:
        desc = 'Specifies the format. Valid values: "TABLE", "LIST", "CSV".'
        assert winhelp._extract_choices(desc) == ["TABLE", "LIST", "CSV"]

    def test_single_valid_value_phrase(self) -> None:
        desc = 'Valid values: "A"'
        assert winhelp._extract_choices(desc) == ["A"]

    def test_no_valid_values_phrase(self) -> None:
        assert winhelp._extract_choices("No choices here.") == []
