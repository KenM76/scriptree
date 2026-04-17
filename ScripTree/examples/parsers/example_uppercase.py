"""Example user parser plugin for ScripTree.

This plugin handles a fictional "UPPERCASE HELP" format where every
flag line is written in capital letters with the description after a
colon::

    MYTOOL 1.0
    USAGE: MYTOOL [OPTIONS] INPUT

    OPTIONS:
      -V : enable verbose output
      -F FORMAT : set output format (choices: JSON,YAML,XML)
      -O PATH : write result to output file

Not a real tool — but a simple, complete demonstration of the plugin
protocol. Read the comments as a tutorial for writing your own parser.

## To try it out

Set the environment variable to this directory and launch ScripTree::

    $env:SCRIPTREE_PARSERS_DIR = "<repo>/examples/parsers"
    python -m scriptree.main

Then call ``scriptree.core.parser.probe.parse_text`` on a string
containing ``MYTOOL 1.0`` and you'll get back a ToolDef whose
``source.mode == "example_uppercase"``.
"""
from __future__ import annotations

import re

# Plugins import from the main scriptree package like any other code.
from scriptree.core.model import (
    ParamDef,
    ParamType,
    ParseSource,
    ToolDef,
    Widget,
)


# ----------------------------------------------------------------------
# Step 1: Plugin metadata
# ----------------------------------------------------------------------
#
# Three required attributes. The loader only treats this file as a
# plugin if all three are present.

NAME = "example_uppercase"
"""Unique id. Two plugins with the same name override each other —
later additions win."""

PRIORITY = 500
"""Dispatch order. Lower runs first. Built-in plugins use 10 (argparse),
20 (click), 30 (winhelp), 999 (heuristic fallback). I'm picking 500
here so the built-in structured detectors still run first — this
plugin only claims text they don't recognize."""

DESCRIPTION = "Example plugin: uppercase MYTOOL help format."
"""Optional. Used by the UI and by ``PluginRegistry.by_name()``."""


# ----------------------------------------------------------------------
# Step 2: Detection
# ----------------------------------------------------------------------
#
# ``detect(help_text)`` must return either a ToolDef or None. Return
# None quickly if the text isn't in your expected format — cheap
# rejection keeps the pipeline fast.

_SIGNATURE = re.compile(r"(?m)^\s*MYTOOL\s+\d", re.IGNORECASE)
_FLAG_LINE = re.compile(
    r"""
    ^\s*
    -(?P<flag>[A-Z])           # short flag, e.g. -V
    (?:\s+(?P<metavar>[A-Z]+))? # optional ALL-CAPS metavar
    \s*:\s*
    (?P<desc>.+?)
    \s*$
    """,
    re.VERBOSE,
)
_CHOICES = re.compile(r"\bchoices:\s*([A-Z][A-Z0-9,]*)", re.IGNORECASE)


def detect(help_text: str) -> ToolDef | None:
    # Reject fast: our signature is the "MYTOOL <version>" header line.
    if not _SIGNATURE.search(help_text):
        return None

    params: list[ParamDef] = []
    template: list = []

    # Parse each matching flag line. We don't care about section
    # headers or usage lines in this format — just the -X : description
    # lines.
    for line in help_text.splitlines():
        m = _FLAG_LINE.match(line)
        if not m:
            continue

        flag = "-" + m.group("flag")
        metavar = m.group("metavar") or ""
        description = m.group("desc")

        # Use the flag letter (lowercased) as the param id. In a real
        # plugin you'd want something smarter — prefer metavars,
        # avoid collisions — but for the example this is fine.
        pid = m.group("flag").lower()

        if not metavar:
            # Bare flag → bool checkbox + conditional-emit template entry.
            params.append(
                ParamDef(
                    id=pid,
                    label=pid.upper(),
                    description=description,
                    type=ParamType.BOOL,
                    widget=Widget.CHECKBOX,
                    default=False,
                )
            )
            template.append("{" + pid + "?" + flag + "}")
            continue

        # Value-taking flag: check for inline "choices:" hint.
        choices_match = _CHOICES.search(description)
        if choices_match:
            choices = [c.strip() for c in choices_match.group(1).split(",") if c]
            ptype = ParamType.ENUM
            widget = Widget.DROPDOWN
            default = choices[0] if choices else ""
        else:
            choices = []
            ptype = ParamType.STRING
            widget = Widget.TEXT
            default = ""

        params.append(
            ParamDef(
                id=pid,
                label=metavar.title(),
                description=description,
                type=ptype,
                widget=widget,
                default=default,
                choices=choices,
            )
        )
        # Token group: literal flag + value. If the value is empty at
        # run time, the whole group drops (all-or-nothing semantics).
        template.append([flag, "{" + pid + "}"])

    if not params:
        # Found the signature but no flags — pass so another plugin
        # or the fallback heuristic gets a shot.
        return None

    # Return a ToolDef. Caller (the probe) fills in ``executable`` and
    # ``name`` from the filesystem path — we just tag the source mode.
    return ToolDef(
        name="",
        executable="",
        argument_template=template,
        params=params,
        source=ParseSource(
            mode=NAME,
            help_text_cached=help_text,
        ),
    )


# ----------------------------------------------------------------------
# Step 3 (optional): Self-test
# ----------------------------------------------------------------------
#
# Running this file directly will exercise the parser against a sample
# input so you can sanity-check your plugin without launching ScripTree.
# Run with::
#
#     python example_uppercase.py

if __name__ == "__main__":
    sample = """\
MYTOOL 1.0
USAGE: MYTOOL [OPTIONS] INPUT

OPTIONS:
  -V : enable verbose output
  -F FORMAT : set output format (choices: JSON,YAML,XML)
  -O PATH : write result to output file
"""
    tool = detect(sample)
    assert tool is not None, "Parser did not detect the sample text."
    print(f"Parsed {len(tool.params)} params:")
    for p in tool.params:
        extras = f" choices={p.choices}" if p.choices else ""
        print(f"  {p.id:4s} {p.type.value:8s} {p.widget.value:10s} {p.label!r}{extras}")
    print()
    print("Template:")
    for entry in tool.argument_template:
        print(f"  {entry!r}")
