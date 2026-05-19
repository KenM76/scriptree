"""Plugin: click framework detector.

## For humans

Click's shape::

    Usage: PROG [OPTIONS] COMMAND [ARGS]...

      Short description.

    Options:
      --flag         ...
      --help         Show this message and exit.

The heuristic parser handles click's flag lines fine; this plugin
just recognizes click by its ``Usage:`` / ``Options:`` header casing
and retags the source accordingly.

## For maintainers / LLMs

- EDITOR-time plugin. ``PRIORITY=20`` — after argparse (10), before
  powershell (25) / winhelp (30) / heuristic (999).
- Detection is casing-sensitive: ``_CLICK_USAGE`` matches
  capital-U ``Usage:`` and ``_CLICK_OPTIONS`` matches capital-O
  ``Options:`` on its own line. argparse's lowercase
  ``usage:``/``options:`` is what keeps these two plugins from
  fighting over the same text — do NOT make these patterns
  case-insensitive.
- Body parsing is delegated to ``_core.parse_heuristic``; this
  plugin only retags ``source.mode = "click"`` and strips the
  synthetic ``help`` param/template entries. ``_keep_entry`` is
  byte-identical to the argparse plugin's and shares the same
  ``id == "help"`` / ``"{help"`` contract with ``parse_heuristic``.
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
