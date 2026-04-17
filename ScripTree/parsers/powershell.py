"""Tier-1 parser for PowerShell ``Get-Help -Full`` output.

PowerShell cmdlets emit a distinctive structured help format::

    NAME
        New-LocalUser

    SYNTAX
        New-LocalUser [-Name] <string> -Password <securestring> ...

    PARAMETERS
        -AccountExpires <datetime>

            Required?                    false
            Position?                    Named
            Accept pipeline input?       true (ByPropertyName)
            Parameter set name           (All)
            Aliases                      None
            Dynamic?                     false

        -Disabled

            Required?                    false
            Position?                    Named
            ...

The parser detects this shape by looking for the ``NAME`` / ``SYNTAX`` /
``PARAMETERS`` section headers. From the ``PARAMETERS`` block it extracts
each flag name, its type tag (``<string>``, ``<int32>``, ``<bool>``,
``<datetime>``, ``<securestring>``, etc.), whether it's required and
positional, and its parameter-set membership.

Switch parameters (no type tag, e.g. ``-Disabled``) become booleans.
Parameters with ``<bool>`` type become booleans too. ``<securestring>``
parameters are skipped — they cannot be passed via command-line argv.

Common parameters (``-Verbose``, ``-Debug``, ``-ErrorAction``, ``-WhatIf``,
``-Confirm``, etc.) and ``<CommonParameters>`` are stripped.

Because ScripTree wraps ``powershell.exe -NoProfile -Command "CmdletName ..."``,
the generated tool uses ``powershell.exe`` as the executable and emits the
cmdlet name as a literal in the argument template.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from scriptree.core.model import (
    ParamDef,
    ParamType,
    ParseSource,
    TemplateEntry,
    ToolDef,
    Widget,
)

# --- plugin metadata -------------------------------------------------------

NAME = "powershell"
PRIORITY = 25  # between click (20) and winhelp (30)
DESCRIPTION = "PowerShell Get-Help output (NAME / SYNTAX / PARAMETERS layout)."

# --- detection --------------------------------------------------------------

_NAME_HEADER = re.compile(r"(?m)^NAME\s*$")
_SYNTAX_HEADER = re.compile(r"(?m)^SYNTAX\s*$")
_PARAMETERS_HEADER = re.compile(r"(?m)^PARAMETERS\s*$")


def looks_like_powershell_help(text: str) -> bool:
    """Return True if the text looks like PowerShell Get-Help output."""
    # Require at least NAME + PARAMETERS headers.
    return bool(_NAME_HEADER.search(text) and _PARAMETERS_HEADER.search(text))


# --- parameter extraction ---------------------------------------------------

# Matches a parameter header line like:
#   "    -Name <string>"          → flag="Name", type_tag="string"
#   "    -Disabled"               → flag="Disabled", type_tag=""  (switch)
#   "    <CommonParameters>"      → flag="", type_tag="CommonParameters"
_PARAM_HEADER = re.compile(
    r"^\s{4}-(?P<flag>[A-Za-z][A-Za-z0-9_]*)(?:\s+<(?P<type>[^>]+)>)?\s*$"
)
_COMMON_PARAMS = re.compile(r"^\s{4}<CommonParameters>")

# Metadata lines inside a parameter block.
_META_LINE = re.compile(
    r"^\s+(?P<key>Required\?|Position\?|Accept pipeline input\?|"
    r"Parameter set name|Aliases|Dynamic\?)\s+(?P<value>.+?)\s*$"
)

# Parameters to always skip — common parameters and confirmation prompts.
_SKIP_PARAMS = frozenset({
    "Verbose", "Debug", "ErrorAction", "ErrorVariable",
    "WarningAction", "WarningVariable", "InformationAction",
    "InformationVariable", "OutBuffer", "OutVariable",
    "PipelineVariable", "ProgressAction",
    "WhatIf", "Confirm",
})


@dataclass
class _ParsedParam:
    flag: str           # e.g. "Name", "Disabled"
    type_tag: str       # e.g. "string", "int32", "bool", "" (switch)
    required: bool = False
    position: str = "Named"  # "0", "1", ... or "Named"
    param_set: str = "(All)"
    aliases: str = ""
    description: str = ""


def _extract_cmdlet_name(text: str) -> str:
    """Pull the cmdlet name from the NAME section."""
    m = _NAME_HEADER.search(text)
    if not m:
        return ""
    # The cmdlet name is on the next non-blank line, indented.
    lines = text[m.end():].splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _extract_parameters(text: str) -> list[_ParsedParam]:
    """Parse the PARAMETERS block into structured param records."""
    m = _PARAMETERS_HEADER.search(text)
    if not m:
        return []

    # Find the end of the PARAMETERS section — next all-caps header.
    remaining = text[m.end():]
    lines = remaining.splitlines()

    # Find where the section ends (next top-level header like INPUTS,
    # OUTPUTS, ALIASES, REMARKS, NOTES, EXAMPLES, etc.).
    end = len(lines)
    for i, line in enumerate(lines):
        if i > 0 and re.match(r"^[A-Z][A-Z]+\s*$", line):
            end = i
            break

    block = lines[:end]
    params: list[_ParsedParam] = []
    i = 0

    while i < len(block):
        line = block[i]

        # Skip CommonParameters marker.
        if _COMMON_PARAMS.match(line):
            i += 1
            continue

        m_hdr = _PARAM_HEADER.match(line)
        if not m_hdr:
            i += 1
            continue

        flag = m_hdr.group("flag")
        type_tag = m_hdr.group("type") or ""

        # Read metadata lines until we hit another parameter header,
        # a blank line followed by another header, or end of block.
        meta: dict[str, str] = {}
        desc_parts: list[str] = []
        j = i + 1

        # Skip blank lines between header and metadata.
        while j < len(block) and not block[j].strip():
            j += 1

        # Collect metadata key-value pairs.
        while j < len(block):
            ml = _META_LINE.match(block[j])
            if ml:
                meta[ml.group("key")] = ml.group("value")
                j += 1
            elif not block[j].strip():
                # Blank line — could be end of this param or gap
                # before description continuation. Peek ahead.
                j += 1
                # If next non-blank is another param header or
                # end-of-block, stop. Otherwise it's description.
                k = j
                while k < len(block) and not block[k].strip():
                    k += 1
                if k >= len(block):
                    break
                if _PARAM_HEADER.match(block[k]) or _COMMON_PARAMS.match(block[k]):
                    break
                if re.match(r"^[A-Z][A-Z]+\s*$", block[k]):
                    break
                # It's a description continuation — collect until
                # the next param header.
                while j < len(block):
                    if _PARAM_HEADER.match(block[j]) or _COMMON_PARAMS.match(block[j]):
                        break
                    if block[j].strip():
                        desc_parts.append(block[j].strip())
                    j += 1
                break
            else:
                # Non-metadata, non-blank — description text.
                desc_parts.append(block[j].strip())
                j += 1

        pp = _ParsedParam(
            flag=flag,
            type_tag=type_tag,
            required=meta.get("Required?", "false").strip().lower() == "true",
            position=meta.get("Position?", "Named").strip(),
            param_set=meta.get("Parameter set name", "(All)").strip(),
            aliases=meta.get("Aliases", "None").strip(),
            description=" ".join(desc_parts),
        )
        params.append(pp)
        i = j

    return params


# --- type mapping -----------------------------------------------------------

# PowerShell type tags → (ParamType, Widget).
_TYPE_MAP: dict[str, tuple[ParamType, Widget]] = {
    "string": (ParamType.STRING, Widget.TEXT),
    "string[]": (ParamType.STRING, Widget.TEXT),
    "int": (ParamType.INTEGER, Widget.NUMBER),
    "int32": (ParamType.INTEGER, Widget.NUMBER),
    "int64": (ParamType.INTEGER, Widget.NUMBER),
    "uint32": (ParamType.INTEGER, Widget.NUMBER),
    "uint64": (ParamType.INTEGER, Widget.NUMBER),
    "long": (ParamType.INTEGER, Widget.NUMBER),
    "double": (ParamType.FLOAT, Widget.NUMBER),
    "float": (ParamType.FLOAT, Widget.NUMBER),
    "decimal": (ParamType.FLOAT, Widget.NUMBER),
    "bool": (ParamType.BOOL, Widget.CHECKBOX),
    "switch": (ParamType.BOOL, Widget.CHECKBOX),
    "datetime": (ParamType.STRING, Widget.TEXT),
    "timespan": (ParamType.STRING, Widget.TEXT),
    "uri": (ParamType.STRING, Widget.TEXT),
    "guid": (ParamType.STRING, Widget.TEXT),
    "hashtable": (ParamType.STRING, Widget.TEXTAREA),
    "hashtable[]": (ParamType.STRING, Widget.TEXTAREA),
    "psobject": (ParamType.STRING, Widget.TEXT),
    "object": (ParamType.STRING, Widget.TEXT),
    "object[]": (ParamType.STRING, Widget.TEXT),
}

# Types that cannot be meaningfully passed as command-line strings.
_SKIP_TYPES = frozenset({
    "securestring",     # Can't pass on command line
    "pscredential",     # Can't pass on command line
})

# Types we treat as opaque object references — skip them because they
# typically come from pipeline input, not command-line arguments.
_PIPELINE_ONLY_TYPES = frozenset({
    "localuser", "localgroup", "localprincipal", "localprincipal[]",
    "securityidentifier", "securityidentifier[]",
})


def _map_type(type_tag: str) -> tuple[ParamType, Widget] | None:
    """Map a PowerShell type tag to ParamType + Widget.

    Returns None for types that should be skipped entirely.
    """
    lower = type_tag.lower().strip()
    if not lower:
        # No type tag = switch parameter → boolean.
        return (ParamType.BOOL, Widget.CHECKBOX)
    if lower in _SKIP_TYPES:
        return None
    if lower in _PIPELINE_ONLY_TYPES:
        return None
    return _TYPE_MAP.get(lower, (ParamType.STRING, Widget.TEXT))


# --- ID / label synthesis ---------------------------------------------------

def _flag_to_id(flag: str, used: set[str]) -> str:
    """Convert a PowerShell flag name to a Python identifier param ID."""
    # CamelCase → snake_case.
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", flag).lower()
    name = re.sub(r"[^a-z0-9_]+", "_", name).strip("_")
    if not name or not name.isidentifier():
        return ""
    base = name
    n = 2
    while name in used:
        name = f"{base}_{n}"
        n += 1
    return name


def _flag_to_label(flag: str) -> str:
    """Convert a PowerShell flag to a human-readable label.

    ``AccountNeverExpires`` → ``Account Never Expires``.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", flag)
    return spaced.strip()


# --- main entry point -------------------------------------------------------

def detect(help_text: str) -> ToolDef | None:
    """Return a ToolDef if ``help_text`` looks like PowerShell help, else None."""
    if not looks_like_powershell_help(help_text):
        return None

    cmdlet_name = _extract_cmdlet_name(help_text)
    raw_params = _extract_parameters(help_text)

    if not raw_params:
        return None

    params: list[ParamDef] = []
    template: list[TemplateEntry] = [cmdlet_name] if cmdlet_name else []
    used_ids: set[str] = set()

    # When multiple parameter sets exist, prefer the "(All)" set.
    # For params only in specific sets, still include them — but mark
    # as not required even if the set says required (since the user may
    # be using a different set).
    has_multiple_sets = len({
        p.param_set for p in raw_params if p.param_set != "(All)"
    }) > 1

    for pp in raw_params:
        # Skip common/confirmation params.
        if pp.flag in _SKIP_PARAMS:
            continue

        # Skip types that can't be passed via argv.
        mapped = _map_type(pp.type_tag)
        if mapped is None:
            continue

        ptype, widget = mapped

        pid = _flag_to_id(pp.flag, used_ids)
        if not pid:
            continue
        used_ids.add(pid)

        label = _flag_to_label(pp.flag)

        # If the param is in a non-(All) set and there are multiple
        # sets, mark as not required — the user might be using a
        # different parameter set.
        required = pp.required
        if has_multiple_sets and pp.param_set != "(All)":
            required = False

        if ptype is ParamType.BOOL:
            # Switch / bool parameters → conditional flag.
            params.append(ParamDef(
                id=pid,
                label=label,
                description=pp.description,
                type=ParamType.BOOL,
                widget=Widget.CHECKBOX,
                required=False,  # bool flags are never "required"
                default=False,
            ))
            template.append("{" + pid + "?-" + pp.flag + "}")
        else:
            # Value-taking parameter.
            default = "" if ptype is not ParamType.INTEGER else ""
            params.append(ParamDef(
                id=pid,
                label=label,
                description=pp.description,
                type=ptype,
                widget=widget,
                required=required,
                default=default,
            ))
            # Positional params don't need the flag prefix.
            if pp.position != "Named" and pp.position.isdigit():
                template.append("{" + pid + "}")
            else:
                template.append(["-" + pp.flag, "{" + pid + "}"])

    if not params:
        return None

    return ToolDef(
        name=cmdlet_name or "",
        executable="powershell.exe",
        argument_template=["-NoProfile", "-Command"] + template,
        params=params,
        source=ParseSource(mode="powershell", help_text_cached=help_text),
    )
