"""Plugin: click framework detector.

Click's shape::

    Usage: PROG [OPTIONS] COMMAND [ARGS]...

      Short description.

    Options:
      --flag         ...
      --help         Show this message and exit.

The heuristic parser handles click's flag lines fine; this plugin
just recognizes click by its ``Usage:`` / ``Options:`` header casing
and retags the source accordingly.
"""
from __future__ import annotations

import re

from ...model import ParseSource, TemplateEntry, ToolDef
from ._core import parse_heuristic

NAME = "click"
PRIORITY = 20
DESCRIPTION = "click framework --help output (Usage: / Options: layout)."

_CLICK_USAGE = re.compile(r"(?m)^Usage:\s")
_CLICK_OPTIONS = re.compile(r"(?m)^Options:\s*$")


def detect(help_text: str) -> ToolDef | None:
    if not _CLICK_USAGE.search(help_text):
        return None
    if not _CLICK_OPTIONS.search(help_text):
        return None
    tool = parse_heuristic(help_text)
    tool.params = [p for p in tool.params if p.id != "help"]
    tool.argument_template = [
        entry for entry in tool.argument_template
        if _keep_entry(entry)
    ]
    tool.source = ParseSource(mode="click", help_text_cached=help_text)
    return tool


def _keep_entry(entry: TemplateEntry) -> bool:
    if isinstance(entry, list):
        return not any("{help" in tok for tok in entry)
    return "{help" not in entry and entry != "{help}"
