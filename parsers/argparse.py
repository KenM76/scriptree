"""Plugin: Python argparse detector.

argparse has a very recognizable shape::

    usage: PROG [-h] [--flag] POSITIONAL

    description line

    positional arguments:
      foo          ...
      bar          ...

    options:
      -h, --help   show this help message and exit
      --flag       ...

Older Python versions say ``optional arguments:`` instead of ``options:``.
If we detect this shape we reuse the shared heuristic parser (which
already handles argparse's formatting well) and just retag the source.
"""
from __future__ import annotations

import re

from scriptree.core.model import ParseSource, TemplateEntry, ToolDef
from _core import parse_heuristic

NAME = "argparse"
PRIORITY = 10
DESCRIPTION = "Python argparse --help output (usage: / options: layout)."

_ARGPARSE_SIGNATURE = re.compile(r"(?m)^(options|optional arguments):\s*$")
_USAGE_PREFIX = re.compile(r"(?m)^usage:\s", re.IGNORECASE)


def detect(help_text: str) -> ToolDef | None:
    if not _USAGE_PREFIX.search(help_text):
        return None
    if not _ARGPARSE_SIGNATURE.search(help_text):
        return None
    tool = parse_heuristic(help_text)
    # argparse always adds --help; strip it from the detected params
    # and from any template entries that reference it.
    tool.params = [p for p in tool.params if p.id != "help"]
    tool.argument_template = [
        entry for entry in tool.argument_template
        if _keep_entry(entry)
    ]
    tool.source = ParseSource(mode="argparse", help_text_cached=help_text)
    return tool


def _keep_entry(entry: TemplateEntry) -> bool:
    if isinstance(entry, list):
        return not any("{help" in tok for tok in entry)
    return "{help" not in entry and entry != "{help}"
