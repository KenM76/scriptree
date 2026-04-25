"""Tier-1 parser for Windows-style ``/?`` help text.

Windows command-line tools (tasklist, taskkill, sc, net, robocopy, xcopy,
reg, schtasks, …) almost all follow the same help layout:

1. A usage line in **ALL CAPS** at the top: ``TASKLIST [/S system ...]``.
2. A ``Description:`` section with prose.
3. A ``Parameter List:`` section where each flag is shown as
   ``   /X    metavar    Description...`` with continuation lines
   indented under the description column.
4. Optionally extra sections like ``Filters:``, ``Examples:``, ``NOTE:``.

Flags that take a value emit **two** argv tokens (``/S system`` — not
``/S=system``), which is why this parser produces token **groups** in
the argument template. Bare flags emit a single conditional token like
``{svc?/SVC}``.

Enum extraction: if a parameter's description contains a phrase like
``Valid values: "TABLE", "LIST", "CSV".``, the quoted strings become
the ``choices`` for a dropdown.

Masked widget hint: if the flag name is ``/P`` or the metavar mentions
``password``, the description is tagged so the editor knows to render
it with masked entry (v2 feature — v1 just uses a regular text widget
but flags the param via its description).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ...model import (
    ParamDef,
    ParamType,
    ParseSource,
    TemplateEntry,
    ToolDef,
    Widget,
)

# --- plugin metadata -------------------------------------------------------

NAME = "winhelp"
PRIORITY = 30
DESCRIPTION = "Windows-style /? help output (tasklist, taskkill, sc, schtasks, ...)."


# --- detection -------------------------------------------------------------

# Headers Windows tools use to introduce their flag list. We deliberately
# DO NOT include ``options`` here — that overlaps with argparse/click and
# would cause winhelp to claim help text it shouldn't.
_PARAMETER_LIST_HEADER = re.compile(
    r"(?im)^\s*(?:parameter\s*list|parameters|switches|command[- ]line\s*switches)\s*:\s*$"
)
_USAGE_ALLCAPS = re.compile(r"(?m)^\s*([A-Z][A-Z0-9_.]*)\s+\[?/", )
_SLASH_FLAG_ANYWHERE = re.compile(r"(?m)^\s*/[A-Za-z?]")


def looks_like_windows_help(text: str) -> bool:
    """Return True if the text looks like Windows-style help.

    We require either a ``Parameter List:`` header, OR at least one
    line that starts with 3+ spaces and a ``/`` flag (the standard
    indent used by Windows help formatters). Also accept an all-caps
    usage line with ``/`` flags in brackets, which is how tasklist,
    net, sc, taskkill, etc. all start their help.
    """
    if _PARAMETER_LIST_HEADER.search(text):
        return True
    if _USAGE_ALLCAPS.search(text):
        return True
    # At least 2 slash-flag lines is a strong signal too.
    if len(_SLASH_FLAG_ANYWHERE.findall(text)) >= 2:
        return True
    return False


# --- flag line extraction --------------------------------------------------

# The flag-name sub-pattern allows a bracketed optional suffix, like
# ``find /OFF[LINE]`` where the bracket denotes optional trailing
# characters (the flag can be typed as either ``/OFF`` or ``/OFFLINE``).
_FLAG_NAME = r"/[A-Za-z?][A-Za-z0-9_]*(?:\[[A-Z0-9_]+\])?"

# Match a parameter-list flag line. Captures:
#   indent, flag (/X or /Word), optional metavar, description.
#
# The key disambiguator is ``\s{2,}`` before the description: a metavar
# must be followed by ≥2 spaces. If the would-be metavar is followed by
# only one space it's actually the first word of the description, and
# regex backtracking skips the optional metavar group correctly.
_WIN_FLAG_LINE = re.compile(
    rf"""
    ^(?P<indent>\s*)
    (?P<flag>{_FLAG_NAME})
    (?:\s+
        (?P<metavar>
            \[[^\]]*\]\S*       # bracketed, possibly with trailing chars
          | [A-Za-z][^\s]*      # plain word metavar
        )
    )?
    \s{{2,}}
    (?P<desc>\S.*?)
    \s*$
    """,
    re.VERBOSE,
)

# Loose fallback: flag + 1+ spaces + description. Used only when the
# strict form fails, which happens when the flag is long enough to run
# flush against the description column with only a single space gap
# (``find /?`` does this with ``/OFF[LINE] Do not skip...``).
#
# We cannot use this form unconditionally because it would incorrectly
# eat a metavar like the ``system`` in tasklist's ``/S    system  Specifies...``
# as part of the description. Strict-first, loose-fallback keeps both
# cases correct.
_WIN_FLAG_LINE_LOOSE = re.compile(
    rf"""
    ^(?P<indent>\s*)
    (?P<flag>{_FLAG_NAME})
    \s+
    (?P<desc>\S.*?)
    \s*$
    """,
    re.VERBOSE,
)

# Positional parameter line (no leading ``/``). Three shapes:
#   "string"                           — quoted-string positional (required)
#   [drive:][path]filename             — bracketed-prefix positional (usually optional)
#   <file>                             — angle-bracket positional
# The description may be empty on this line; the continuation-line
# handler in ``_parse_flag_block`` picks it up from the next indented
# line (which is how ``find /?`` formats the ``filename`` positional).
_WIN_POSITIONAL_LINE = re.compile(
    r"""
    ^(?P<indent>\s*)
    (?P<positional>
        "[^"]+"                           # quoted: "string"
      | \[[^\]]+\]\S*                     # bracketed-prefix: [drive:][path]filename
      | <[^>]+>\S*                        # angle-bracket: <file>
    )
    (?:\s+(?P<desc>\S.*?))?
    \s*$
    """,
    re.VERBOSE,
)


@dataclass
class _ParsedFlag:
    flag: str           # e.g. "/S", "/OFF[LINE]", or "" for positionals
    metavar: str        # metavar (flags) or the full positional token (positionals)
    description: str    # joined description including continuations
    indent: int         # leading-space count (for continuation detection)
    is_positional: bool = False


def _extract_flag_block(lines: list[str]) -> list[_ParsedFlag]:
    """Parse lines under the Parameter List / Options header.

    If no such header exists, scan the whole text — some tools (like
    ``xcopy /?``) put their flags directly after the usage block.
    """
    # Find the parameter-list header if present.
    start = 0
    for i, line in enumerate(lines):
        if _PARAMETER_LIST_HEADER.match(line):
            start = i + 1
            break

    # Find the end: next all-caps header like "Filters:", "Examples:",
    # "NOTE:", or a line at col 0 starting with a letter.
    end = len(lines)
    for i in range(start, len(lines)):
        line = lines[i]
        if re.match(r"^[A-Z][A-Za-z ]*:\s*$", line):
            # But skip if we just consumed the Parameter List header.
            if i > start:
                end = i
                break

    block = lines[start:end]
    return _parse_flag_block(block)


def _parse_flag_block(block: list[str]) -> list[_ParsedFlag]:
    """Walk the param block, matching each line as a flag or positional.

    Three regex attempts per line, in priority order:

    1. ``_WIN_FLAG_LINE``        — strict flag + optional metavar + 2-space gap
    2. ``_WIN_FLAG_LINE_LOOSE``  — flag + 1-space gap + description
    3. ``_WIN_POSITIONAL_LINE``  — quoted / bracketed / angle positional

    The strict flag regex runs first so tool formats with metavars
    (``tasklist /S system  Specifies...``) keep their metavar instead
    of eating it as part of the description. The loose fallback only
    catches lines that the strict form can't — typically long flag
    names like ``/OFF[LINE]`` that have only a single space before
    the description column.

    Continuation lines (next-line descriptions that are indented
    deeper than the main line with no leading ``/``) are joined to
    whichever main-line kind matched.
    """
    parsed: list[_ParsedFlag] = []
    i = 0
    while i < len(block):
        line = block[i]
        if not line.strip():
            i += 1
            continue

        flag_text = ""
        metavar = ""
        is_positional = False
        desc_part = ""
        indent = 0

        m_strict = _WIN_FLAG_LINE.match(line)
        if m_strict:
            indent = len(m_strict.group("indent"))
            flag_text = m_strict.group("flag")
            metavar = m_strict.group("metavar") or ""
            desc_part = m_strict.group("desc") or ""
        else:
            m_loose = _WIN_FLAG_LINE_LOOSE.match(line)
            if m_loose:
                indent = len(m_loose.group("indent"))
                flag_text = m_loose.group("flag")
                desc_part = m_loose.group("desc") or ""
            else:
                m_pos = _WIN_POSITIONAL_LINE.match(line)
                if m_pos:
                    indent = len(m_pos.group("indent"))
                    metavar = m_pos.group("positional")
                    is_positional = True
                    desc_part = m_pos.group("desc") or ""
                else:
                    i += 1
                    continue

        # Join continuation lines — same rule for flags and positionals:
        # next line must be indented deeper than the main line, be
        # non-blank, and not start with another /flag or positional marker.
        desc_parts = [desc_part.strip()] if desc_part else []
        j = i + 1
        while j < len(block):
            cont = block[j]
            if not cont.strip():
                break
            cont_indent = len(cont) - len(cont.lstrip())
            if cont_indent <= indent:
                break
            if re.match(r"^\s*[/\[\"<]", cont):
                break
            desc_parts.append(cont.strip())
            j += 1

        parsed.append(
            _ParsedFlag(
                flag=flag_text,
                metavar=metavar,
                description=" ".join(desc_parts),
                indent=indent,
                is_positional=is_positional,
            )
        )
        i = j
    return parsed


# --- enum / metadata extraction --------------------------------------------

_VALID_VALUES_QUOTED = re.compile(
    r'Valid\s*values?\s*:\s*(.+?)(?:\.|$)', re.IGNORECASE
)


def _extract_choices(description: str) -> list[str]:
    """Return ["TABLE","LIST","CSV"] for a description that contains
    ``Valid values: "TABLE", "LIST", "CSV".``

    Falls back to comma-separated unquoted tokens if no quoted strings
    are found.
    """
    m = _VALID_VALUES_QUOTED.search(description)
    if not m:
        return []
    tail = m.group(1)
    quoted = re.findall(r'"([^"]+)"', tail)
    if quoted:
        return quoted
    # Unquoted fallback: split on commas, strip whitespace.
    return [
        t.strip()
        for t in tail.split(",")
        if t.strip() and not t.strip().startswith("|")
    ]


# --- id / label synthesis --------------------------------------------------

def _synth_id(flag: str, metavar: str, used: set[str]) -> str:
    """Choose a unique Python-identifier id for a parameter.

    Prefer the metavar (stripped of brackets/backslashes) when it looks
    like a real word — ``/S system`` → ``system`` is much nicer than
    ``s``. Fall back to the flag name for bare flags.
    """
    candidate = ""
    if metavar:
        # "[domain\\]user" → "user". "[password]" → "password".
        cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", metavar).strip("_")
        # Prefer the last segment if there are multiple (domain_user → user).
        parts = [p for p in cleaned.split("_") if p]
        if parts:
            candidate = parts[-1].lower()

    if not candidate or not candidate.isidentifier():
        candidate = flag.lstrip("/").lower()
        # "?" is not a valid identifier — will be filtered by caller anyway.
        candidate = re.sub(r"[^A-Za-z0-9_]+", "_", candidate).strip("_")

    if not candidate or not candidate.isidentifier():
        return ""

    base = candidate
    n = 2
    while candidate in used:
        candidate = f"{base}_{n}"
        n += 1
    return candidate


def _synth_label(flag: str, metavar: str) -> str:
    if metavar:
        cleaned = re.sub(r"[^A-Za-z0-9 ]+", " ", metavar).strip()
        if cleaned:
            return cleaned.title()
    return _canonical_flag(flag).lstrip("/").upper()


def _canonical_flag(flag: str) -> str:
    """Strip any bracketed-suffix from a Windows flag name.

    ``/OFF[LINE]`` → ``/OFF``. The bracketed suffix means "optional
    trailing characters" — the short form is what we'll emit in the
    argv template, since both forms are accepted by the tool.
    """
    return re.sub(r"\[.*?\]", "", flag)


def _synth_positional_id(token: str, used: set[str]) -> str:
    """Derive an identifier from a positional token.

    Examples::

        "string"                        -> string
        [drive:][path]filename          -> filename
        <file>                          -> file
        [FOO_BAR]baz                    -> baz
    """
    # Strip quotes and remove bracketed prefixes (drive:, path, etc.).
    cleaned = token.strip('"')
    cleaned = re.sub(r"\[[^\]]*\]", "", cleaned)
    cleaned = cleaned.strip("<>")
    # What's left is the "root" token; sanitize to an identifier.
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", cleaned).strip("_").lower()
    if not cleaned or not cleaned.isidentifier():
        # Fallback: use a generic name.
        cleaned = "positional"
    base = cleaned
    n = 2
    while cleaned in used:
        cleaned = f"{base}_{n}"
        n += 1
    return cleaned


def _synth_positional_label(token: str) -> str:
    """Make a human-readable label for a positional param."""
    t = token.strip('"')
    t = re.sub(r"\[[^\]]*\]", "", t)
    t = t.strip("<>")
    t = re.sub(r"[^A-Za-z0-9 ]+", " ", t).strip()
    return t.title() or "Positional"


# --- main entry point ------------------------------------------------------

def detect(help_text: str) -> ToolDef | None:
    """Return a ToolDef if ``help_text`` looks like Windows help, else None."""
    if not looks_like_windows_help(help_text):
        return None

    lines = help_text.splitlines()
    flags = _extract_flag_block(lines)
    if not flags:
        return None

    params: list[ParamDef] = []
    flag_template: list[TemplateEntry] = []
    positional_template: list[TemplateEntry] = []
    used_ids: set[str] = set()

    for pf in flags:
        if pf.is_positional:
            # Positional argument — e.g. ``"string"`` or ``[drive:][path]filename``.
            # Required heuristic: quoted is required, bracket-prefixed is optional.
            raw = pf.metavar
            required = raw.startswith('"')
            pid = _synth_positional_id(raw, used_ids)
            if not pid:
                continue
            used_ids.add(pid)

            if raw.startswith('"'):
                ptype = ParamType.STRING
                widget = Widget.TEXT
                # Quoted-string positionals in Windows help mean "pass
                # this with literal double-quote characters in the
                # argv". find.exe and findstr.exe actually require
                # this — they re-parse their own command line and
                # reject a bare unquoted search string. The template
                # wraps the placeholder in literal quotes so the
                # resolved argv token is '"value"'.
                template_token = '"{' + pid + '}"'
                description_note = (
                    '(literal double-quotes are wrapped around your '
                    'value before the tool sees it) '
                ) + pf.description
            else:
                # Bracketed or angle-wrapped → probably a file path.
                ptype = ParamType.PATH
                widget = Widget.FILE_OPEN
                # Let keyword promotion downgrade to folder if needed.
                promoted = _promote_by_keyword(pf.description, raw)
                if promoted:
                    ptype, widget = promoted
                template_token = "{" + pid + "}"
                description_note = pf.description

            params.append(
                ParamDef(
                    id=pid,
                    label=_synth_positional_label(raw),
                    description=description_note,
                    type=ptype,
                    widget=widget,
                    required=required,
                    default="",
                )
            )
            positional_template.append(template_token)
            continue

        # --- flag entries ---

        canonical = _canonical_flag(pf.flag)
        if canonical in ("/?", "/H", "/HELP"):
            continue

        pid = _synth_id(canonical, pf.metavar, used_ids)
        if not pid:
            continue
        used_ids.add(pid)

        has_value = bool(pf.metavar)
        label = _synth_label(canonical, pf.metavar)

        if has_value:
            # Value-taking flag → enum if choices were found, else
            # plain text. Path/folder detection is best-effort using
            # the same keyword rules the generic heuristic uses.
            choices = _extract_choices(pf.description)
            if choices:
                ptype = ParamType.ENUM
                widget = Widget.DROPDOWN
            else:
                ptype = ParamType.STRING
                widget = Widget.TEXT
                promoted = _promote_by_keyword(pf.description, pf.metavar)
                if promoted:
                    ptype, widget = promoted

            params.append(
                ParamDef(
                    id=pid,
                    label=label,
                    description=pf.description,
                    type=ptype,
                    widget=widget,
                    required=False,
                    default="" if not choices else choices[0],
                    choices=choices,
                )
            )
            # Token group: literal flag + value substitution.
            flag_template.append([canonical, "{" + pid + "}"])
        else:
            # Bare flag → checkbox with a conditional-emit token.
            params.append(
                ParamDef(
                    id=pid,
                    label=label,
                    description=pf.description,
                    type=ParamType.BOOL,
                    widget=Widget.CHECKBOX,
                    required=False,
                    default=False,
                )
            )
            flag_template.append("{" + pid + "?" + canonical + "}")

    # Positionals go after flags in the command line, mirroring how
    # Windows tools document them in their usage string.
    template: list[TemplateEntry] = flag_template + positional_template

    if not params:
        return None

    return ToolDef(
        name="",
        executable="",
        argument_template=template,
        params=params,
        source=ParseSource(mode="winhelp", help_text_cached=help_text),
    )


# --- keyword promotion (subset of heuristic.py, inlined to avoid circular) -

_PROMOTE_RULES: list[tuple[re.Pattern[str], ParamType, Widget]] = [
    (re.compile(r"\b(directory|folder)\b", re.I), ParamType.PATH, Widget.FOLDER),
    (re.compile(r"\boutput\s+file\b", re.I), ParamType.PATH, Widget.FILE_SAVE),
    (re.compile(r"\binput\s+file\b", re.I), ParamType.PATH, Widget.FILE_OPEN),
    (re.compile(r"\bpath\s+to\b", re.I), ParamType.PATH, Widget.FILE_OPEN),
    (re.compile(r"\b(port|count|number of|size|limit)\b", re.I),
     ParamType.INTEGER, Widget.NUMBER),
]


def _promote_by_keyword(
    description: str, metavar: str
) -> tuple[ParamType, Widget] | None:
    haystack = f"{description} {metavar}"
    for pattern, ptype, widget in _PROMOTE_RULES:
        if pattern.search(haystack):
            return ptype, widget
    return None
