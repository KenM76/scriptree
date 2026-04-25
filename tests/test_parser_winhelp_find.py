"""Tests for the winhelp parser against ``find /?``.

find.exe stresses the parser in three ways the tasklist fixture didn't:

1. **Flag with bracketed optional suffix** — ``/OFF[LINE]`` means "the
   flag can be typed as /OFF or /OFFLINE". The parser canonicalizes
   to ``/OFF`` in the template and uses ``off`` as the param id.

2. **Tight columns** — ``/OFF[LINE] Do not skip...`` has only a single
   space between the flag and the description (the flag is long
   enough to run flush against the description column). The strict
   2-space regex can't match; the loose fallback regex picks it up.

3. **Positional parameters** — ``"string"`` and ``[drive:][path]filename``
   are positional args (no leading ``/``). The parser uses a
   separate positional regex and produces text/path params.

Additionally, ``"string"`` positionals are wrapped in *literal*
double-quote characters in the argv template because find.exe
re-parses its own command line and requires them — this is a
documented Microsoft convention for FIND and FINDSTR.
"""
from __future__ import annotations

from scriptree.core.model import ParamType, Widget
from scriptree.core.parser.plugins import winhelp
from scriptree.core.runner import resolve


# Real output of ``C:\\Windows\\SysWOW64\\find.exe /?``.
FIND_HELP = """\
Searches for a text string in a file or files.

FIND [/V] [/C] [/N] [/I] [/OFF[LINE]] "string" [[drive:][path]filename[ ...]]

  /V         Displays all lines NOT containing the specified string.
  /C         Displays only the count of lines containing the string.
  /N         Displays line numbers with the displayed lines.
  /I         Ignores the case of characters when searching for the string.
  /OFF[LINE] Do not skip files with offline attribute set.
  "string"   Specifies the text string to find.
  [drive:][path]filename
             Specifies a file or files to search.

If a path is not specified, FIND searches the text typed at the prompt
or piped from another command.
"""


class TestFindDetection:
    def test_looks_like_windows_help(self) -> None:
        assert winhelp.looks_like_windows_help(FIND_HELP)

    def test_detect_produces_a_tool(self) -> None:
        tool = winhelp.detect(FIND_HELP)
        assert tool is not None
        assert tool.source.mode == "winhelp"


class TestFindFlags:
    def setup_method(self) -> None:
        self.tool = winhelp.detect(FIND_HELP)
        assert self.tool is not None
        self.ids = {p.id for p in self.tool.params}

    def test_all_bare_flags_captured(self) -> None:
        # /V /C /N /I /OFF[LINE]
        for expected in ("v", "c", "n", "i", "off"):
            assert expected in self.ids, (
                f"missing flag {expected!r}; have {sorted(self.ids)}"
            )

    def test_off_line_canonicalized_to_off(self) -> None:
        """The bracketed suffix is stripped in the template literal."""
        strings = [e for e in self.tool.argument_template if isinstance(e, str)]
        assert "{off?/OFF}" in strings
        # The full bracketed form should NOT appear as a template literal.
        assert not any("/OFF[LINE]" in e for e in strings)

    def test_off_is_boolean_checkbox(self) -> None:
        p = self.tool.param_by_id("off")
        assert p is not None
        assert p.type is ParamType.BOOL
        assert p.widget is Widget.CHECKBOX

    def test_tight_column_description_captured(self) -> None:
        """The /OFF[LINE] line has only 1 space before the description —
        the loose fallback regex must pick it up."""
        p = self.tool.param_by_id("off")
        assert "offline attribute" in p.description.lower()


class TestFindPositionals:
    def setup_method(self) -> None:
        self.tool = winhelp.detect(FIND_HELP)
        assert self.tool is not None

    def test_string_positional_present(self) -> None:
        p = self.tool.param_by_id("string")
        assert p is not None
        assert p.type is ParamType.STRING
        assert p.widget is Widget.TEXT

    def test_string_positional_is_required(self) -> None:
        """Quoted positional → required (unquoted in usage means required)."""
        p = self.tool.param_by_id("string")
        assert p.required is True

    def test_string_description_captured(self) -> None:
        p = self.tool.param_by_id("string")
        assert "text string" in p.description.lower()

    def test_filename_positional_present(self) -> None:
        p = self.tool.param_by_id("filename")
        assert p is not None

    def test_filename_is_a_path(self) -> None:
        p = self.tool.param_by_id("filename")
        assert p.type is ParamType.PATH

    def test_filename_is_optional(self) -> None:
        """Bracketed positional → optional."""
        p = self.tool.param_by_id("filename")
        assert p.required is False

    def test_filename_description_from_continuation_line(self) -> None:
        """The description is on the NEXT line, not the same line as
        ``[drive:][path]filename``. The continuation joiner must pick
        it up."""
        p = self.tool.param_by_id("filename")
        assert "file" in p.description.lower()


class TestFindTemplate:
    def setup_method(self) -> None:
        self.tool = winhelp.detect(FIND_HELP)
        assert self.tool is not None

    def test_template_order_flags_then_positionals(self) -> None:
        tmpl = self.tool.argument_template
        # Find where the flags end and positionals begin. Template
        # entries for flags are conditional strings like {v?/V};
        # positionals are bare or embedded-quoted.
        flag_indices = [
            i for i, e in enumerate(tmpl)
            if isinstance(e, str) and e.startswith("{") and "?/" in e
        ]
        positional_indices = [
            i for i, e in enumerate(tmpl)
            if isinstance(e, str) and "?" not in e and "{" in e
        ]
        assert flag_indices, "no flag entries in template"
        assert positional_indices, "no positional entries in template"
        assert max(flag_indices) < min(positional_indices), (
            "positionals should come after flags"
        )

    def test_string_template_wraps_in_literal_quotes(self) -> None:
        """find.exe demands literal double quotes around the search
        string. The template entry is ``'"{string}"'`` so the resolved
        argv token carries the quote characters."""
        tmpl = self.tool.argument_template
        assert '"{string}"' in tmpl

    def test_filename_template_is_bare_positional(self) -> None:
        tmpl = self.tool.argument_template
        assert "{filename}" in tmpl

    def test_template_validates(self) -> None:
        self.tool.name = "find"
        self.tool.executable = "C:/Windows/SysWOW64/find.exe"
        assert self.tool.validate() == []


class TestFindResolve:
    def setup_method(self) -> None:
        self.tool = winhelp.detect(FIND_HELP)
        assert self.tool is not None
        self.tool.name = "find"
        self.tool.executable = "C:/Windows/SysWOW64/find.exe"

    def _defaults(self) -> dict:
        return {p.id: p.default for p in self.tool.params}

    def test_bare_flags_only(self) -> None:
        values = self._defaults()
        values["i"] = True
        values["n"] = True
        values["string"] = "hello"
        values["filename"] = "test.txt"
        cmd = resolve(self.tool, values)
        assert cmd.argv == [
            "C:/Windows/SysWOW64/find.exe",
            "/N", "/I",
            '"hello"',
            "test.txt",
        ]

    def test_string_with_spaces_preserved(self) -> None:
        values = self._defaults()
        values["string"] = "error 404"
        values["filename"] = "log.txt"
        cmd = resolve(self.tool, values)
        # The template is '"{string}"' so the resolved token is
        # '"error 404"' (one argv entry with literal quotes).
        assert '"error 404"' in cmd.argv

    def test_off_canonical_emitted(self) -> None:
        values = self._defaults()
        values["off"] = True
        values["string"] = "x"
        values["filename"] = "y"
        cmd = resolve(self.tool, values)
        assert "/OFF" in cmd.argv
        # The full bracketed form must NOT leak into the argv.
        assert "/OFF[LINE]" not in cmd.argv
        assert "/OFFLINE" not in cmd.argv
