"""Plugin: Python argparse detector.

## For humans

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

## For maintainers / LLMs

- EDITOR-time plugin. ``PRIORITY=10`` (runs before click at 20,
  powershell 25, winhelp 30, heuristic 999) — it should win for any
  genuine argparse output.
- Detection requires BOTH a ``usage:`` prefix (case-insensitive) AND
  an ``options:``/``optional arguments:`` header line. Older Python
  emits ``optional arguments:``; keep both alternatives in
  ``_ARGPARSE_SIGNATURE`` or pre-3.10 tools stop detecting.
- Parsing is delegated to ``_core.parse_heuristic``; this plugin
  only retags ``source.mode = "argparse"`` and strips the synthetic
  ``help`` entry. That strip depends on ``parse_heuristic`` emitting
  a param with ``id == "help"`` and template tokens containing
  ``"{help"`` — a contract shared with the click plugin's identical
  ``_keep_entry``. Change one, change both.
- ``_keep_entry`` handles list (token-group) and str template
  entries; the literal ``entry != "{help}"`` guard is redundant with
  the ``"{help" not in entry`` check but kept for clarity — harmless.
"""
from __future__ import annotations

import re

from ...model import ParseSource, TemplateEntry, ToolDef
from ._core import parse_heuristic

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
