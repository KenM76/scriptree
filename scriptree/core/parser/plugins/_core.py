"""Shared parser implementation — the generic heuristic engine.

This file is excluded from plugin discovery (leading underscore) but
is the workhorse that the argparse, click, and heuristic plugins all
reuse. Keeping it inside the plugins folder means plugins import from
a sibling rather than reaching up multiple package levels.

It doesn't assume argparse, click, or any specific framework — it
walks the help output line by line looking for flag patterns and
keyword hints to promote widgets.

Accuracy is deliberately not perfect. The design is: get the parser to
~80 % on well-formed help output, then trust the inline editor to fix
the rest.

The parser returns a ``ToolDef`` with params, an argument template, and
``source.mode = "heuristic"``. Caller is expected to set ``executable``
and ``name``.
"""
from __future__ import annotations

import re
from typing import Iterator

from ...model import (
    ParamDef,
    ParamType,
    ParseSource,
    ToolDef,
    Widget,
    default_widget_for,
)

# --- regexes ---------------------------------------------------------------

# A flag "word" looks like  -x  or  --foo-bar  or  --foo_bar
_FLAG_WORD = r"-{1,2}[A-Za-z][A-Za-z0-9_-]*"

# Match a flag line's "flag portion" at the start of a line (after
# leading whitespace). Captures the whole flag spec and leaves the
# description as everything after 2+ spaces.
# Examples this handles:
#   -v, --verbose             description
#   --output FILE             description
#   --mode {a,b,c}            description
#   -o OUT, --output OUT      description
#   --threads=N               description
_FLAG_LINE = re.compile(
    r"""
    ^\s*                                 # leading indent
    (?P<spec>
        -{1,2}[A-Za-z][A-Za-z0-9_-]*     # first flag
        (?:[ =]\S+)?                     # optional metavar / value
        (?:\s*,\s*                       # comma between short/long
           -{1,2}[A-Za-z][A-Za-z0-9_-]*
           (?:[ =]\S+)?
        )*
    )
    (?:\s{2,}(?P<desc>\S.*?))?           # description after 2+ spaces
    \s*$
    """,
    re.VERBOSE,
)

# Enum choices inside a flag spec: {a,b,c} or <a|b|c>
_CHOICES_BRACE = re.compile(r"\{([^{}]+)\}")
_CHOICES_ANGLE = re.compile(r"<([^<>|]+(?:\|[^<>|]+)+)>")

# Usage line detector.
_USAGE_LINE = re.compile(r"^\s*(?:usage|Usage|USAGE)\s*:\s*(?P<rest>.+)$")


# --- keyword → widget promotion ---------------------------------------------

# Order matters — first match wins. Each entry is (regex, param_type,
# widget) where the widget overrides the default for the type.
_KEYWORD_RULES: list[tuple[re.Pattern[str], ParamType, Widget]] = [
    # Paths — directory before file so "input directory" beats "input file".
    (re.compile(r"\b(directory|folder|dir)\b", re.I), ParamType.PATH, Widget.FOLDER),
    (re.compile(r"\boutput\s+(file|path)\b", re.I), ParamType.PATH, Widget.FILE_SAVE),
    (re.compile(r"\b(output|write to|save to)\b", re.I), ParamType.PATH, Widget.FILE_SAVE),
    (re.compile(r"\b(input|read from|load|path to|file)\b", re.I), ParamType.PATH, Widget.FILE_OPEN),
    # Numbers.
    (re.compile(r"\b(port|count|number of|num|size|limit|threads|integer|\bint\b)\b", re.I),
     ParamType.INTEGER, Widget.NUMBER),
    # Textarea-ish.
    (re.compile(r"\b(regex|pattern|expression)\b", re.I), ParamType.STRING, Widget.TEXTAREA),
    # URL / token — stay strings but flag for caller via description.
    # (We don't have a masked widget yet; keep as TEXT.)
]


def _promote_widget(description: str) -> tuple[ParamType, Widget] | None:
    for pattern, ptype, widget in _KEYWORD_RULES:
        if pattern.search(description):
            return ptype, widget
    return None


# --- public entry point ----------------------------------------------------

def parse_heuristic(help_text: str) -> ToolDef:
    """Parse arbitrary help text into a ToolDef.

    The returned tool has an empty ``executable`` and ``name`` —
    caller should fill these in before handing off to the editor.
    """
    lines = help_text.splitlines()

    positional_tokens = _extract_positionals(lines)
    params: list[ParamDef] = []
    used_ids: set[str] = set()

    # Positional params first, in the order they appear in the usage line.
    for token in positional_tokens:
        pid = _sanitize_id(token, used_ids)
        if pid is None:
            continue
        used_ids.add(pid)
        params.append(
            ParamDef(
                id=pid,
                label=token.strip("[]<>").replace("_", " ").capitalize(),
                description=f"(Positional argument {token!r})",
                type=ParamType.STRING,
                widget=Widget.TEXT,
                required=token.startswith("<") or not token.startswith("["),
            )
        )

    # Then options.
    for line, desc in _iter_flag_lines(lines):
        for parsed in _parse_flag_line(line, desc, used_ids):
            used_ids.add(parsed.id)
            params.append(parsed)

    # Build the argument template.
    template: list[str] = []
    for p in params:
        if p.description.startswith("(Positional"):
            template.append("{" + p.id + "}")
        elif p.type is ParamType.BOOL:
            flag = _primary_flag_for(p)
            template.append("{" + p.id + "?" + flag + "}")
        else:
            flag = _primary_flag_for(p)
            template.append(f"{flag}={{{p.id}}}")

    return ToolDef(
        name="",
        executable="",
        argument_template=template,
        params=params,
        source=ParseSource(mode="heuristic", help_text_cached=help_text),
    )


# --- positional extraction -------------------------------------------------

def _extract_positionals(lines: list[str]) -> list[str]:
    """Pull positional tokens from the usage line.

    Looks for things like ``<input>``, ``[output]``, ``FILE``. Ignores
    ``[OPTIONS]`` / ``[options]`` boilerplate.
    """
    usage = _find_usage_line(lines)
    if usage is None:
        return []

    positionals: list[str] = []
    # Order of patterns: <foo>, [foo], UPPERCASE_WORD (≥ 2 chars).
    for m in re.finditer(r"<([^<>\s]+)>|\[([^\[\]\s]+)\]|([A-Z][A-Z0-9_]+)", usage):
        token = m.group(1) or m.group(2) or m.group(3) or ""
        if token.upper() in ("OPTIONS", "OPTION", "ARGS", "COMMAND", "COMMANDS"):
            continue
        # Preserve the original bracket form for required/optional detection.
        raw = m.group(0)
        positionals.append(raw)
    return positionals


def _find_usage_line(lines: list[str]) -> str | None:
    """Find and return the usage line's content (after ``usage:``).

    Also joins continuation lines that are indented under the usage header.
    """
    for i, line in enumerate(lines):
        m = _USAGE_LINE.match(line)
        if not m:
            continue
        chunks = [m.group("rest")]
        # Continuation lines: indented, non-blank, and no section header.
        for cont in lines[i + 1 :]:
            if not cont.strip():
                break
            if not cont.startswith((" ", "\t")):
                break
            chunks.append(cont.strip())
        return " ".join(chunks)
    return None


# --- flag-line extraction --------------------------------------------------

def _iter_flag_lines(lines: list[str]) -> Iterator[tuple[str, str]]:
    """Yield (flag_spec, description) for each option-like line.

    Description is joined with continuation lines that are indented
    further than the flag spec and contain no leading dash.
    """
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or not re.match(r"^\s*-", line):
            i += 1
            continue
        m = _FLAG_LINE.match(line)
        if not m:
            i += 1
            continue
        spec = m.group("spec").strip()
        desc_parts: list[str] = []
        if m.group("desc"):
            desc_parts.append(m.group("desc").strip())
        # Join wrapped description lines.
        j = i + 1
        indent_level = len(line) - len(line.lstrip())
        while j < len(lines):
            cont = lines[j]
            if not cont.strip():
                break
            cont_indent = len(cont) - len(cont.lstrip())
            if cont_indent <= indent_level or re.match(r"^\s*-", cont):
                break
            desc_parts.append(cont.strip())
            j += 1
        yield spec, " ".join(desc_parts)
        i = j


def _split_on_commas_respecting_brackets(spec: str) -> list[str]:
    """Split ``spec`` on commas that are NOT inside braces or angles.

    We need this because an enum metavar like ``{fast,slow,auto}``
    contains commas that are not flag separators.
    """
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in spec:
        if ch in "{<":
            depth += 1
            buf.append(ch)
        elif ch in "}>":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _parse_flag_line(
    spec: str, desc: str, used_ids: set[str]
) -> list[ParamDef]:
    """Turn a flag spec + description into one ParamDef.

    Handles "``-o OUT, --output OUT``" by taking the long form as the
    canonical id and keeping the short form in the description.
    """
    flags = [f.strip() for f in _split_on_commas_respecting_brackets(spec)]
    long_flag = next((f for f in flags if f.startswith("--")), None)
    short_flag = next((f for f in flags if f.startswith("-") and not f.startswith("--")), None)

    # Extract the metavar (if any) from whichever form we use.
    canonical = long_flag or short_flag
    if canonical is None:
        return []

    # Split flag name from its metavar: "--output FILE" or "--output=FILE"
    name_part, metavar = _split_flag_and_metavar(canonical)
    pid = _sanitize_id(name_part.lstrip("-").replace("-", "_"), used_ids)
    if pid is None:
        return []

    # Detect enum choices.
    choices: list[str] = []
    if metavar:
        for pattern in (_CHOICES_BRACE, _CHOICES_ANGLE):
            cm = pattern.search(metavar)
            if cm:
                sep = "," if pattern is _CHOICES_BRACE else "|"
                choices = [c.strip() for c in cm.group(1).split(sep) if c.strip()]
                break

    # Determine type + widget.
    if not metavar and not choices:
        ptype = ParamType.BOOL
        widget = Widget.CHECKBOX
    elif choices:
        ptype = ParamType.ENUM
        widget = Widget.DROPDOWN
    else:
        ptype = ParamType.STRING
        widget = Widget.TEXT

    # Keyword-promote widget from the description.
    if ptype in (ParamType.STRING,):
        promoted = _promote_widget(desc)
        if promoted is not None:
            ptype, widget = promoted

    # Label: prefer a human-readable form of the long flag.
    label = (long_flag or short_flag).lstrip("-").replace("-", " ").capitalize()

    description = desc
    if short_flag and long_flag:
        description = f"{desc} (alias: {short_flag})" if desc else f"alias: {short_flag}"

    return [
        ParamDef(
            id=pid,
            label=label,
            description=description,
            type=ptype,
            widget=widget,
            required=False,
            default="" if ptype is not ParamType.BOOL else False,
            choices=choices,
        )
    ]


def _split_flag_and_metavar(flag_with_meta: str) -> tuple[str, str | None]:
    """'--output FILE' → ('--output', 'FILE'); '--x=VAL' → ('--x', 'VAL')."""
    if "=" in flag_with_meta:
        name, _, meta = flag_with_meta.partition("=")
        return name, meta or None
    parts = flag_with_meta.split(None, 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return flag_with_meta, None


def _primary_flag_for(param: ParamDef) -> str:
    """Reconstruct the primary flag token for an option param.

    We round-trip the id back into ``--kebab-case``; if the original
    had a short flag that's the id, we keep it single-dashed.
    """
    name = param.id.replace("_", "-")
    if len(name) == 1:
        return f"-{name}"
    return f"--{name}"


def _sanitize_id(raw: str, used: set[str]) -> str | None:
    """Produce a valid, unique Python-identifier-compatible id."""
    # Strip decoration.
    s = raw.strip("[]<>")
    # Collapse non-word runs to underscores.
    s = re.sub(r"[^A-Za-z0-9_]+", "_", s).strip("_")
    if not s:
        return None
    if s[0].isdigit():
        s = "_" + s
    if not s.isidentifier():
        return None
    base = s
    n = 2
    while s in used:
        s = f"{base}_{n}"
        n += 1
    return s


# Expose default_widget_for for callers if they want it.
__all__ = ["parse_heuristic", "default_widget_for"]
