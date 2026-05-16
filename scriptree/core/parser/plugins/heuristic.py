"""Plugin: generic heuristic parser (catch-all fallback).

## For humans

Always returns a ToolDef — even for unrecognized help text — so this
plugin guarantees that the probe never falls through to nothing.
Runs last (``PRIORITY=999``) so more specific plugins get a chance
to claim the text first.

## For maintainers / LLMs

- EDITOR-time plugin and the system's guaranteed catch-all:
  ``detect`` always returns a ToolDef (never None). This is the
  invariant that lets ``probe._parse`` assume a non-None result.
- ``PRIORITY=999`` must stay the highest of all built-ins so every
  specific parser gets first refusal. Do not add another
  always-returns plugin at a lower priority, and do not give this
  one a lower number — either starves the specific parsers.
- ``detect`` is a thin pass-through to ``_core.parse_heuristic``;
  unlike argparse/click it does NOT retag source (mode stays
  ``"heuristic"``) and does NOT strip the ``help`` param. All real
  logic lives in ``_core``.
"""
from __future__ import annotations

from ...model import ToolDef
from ._core import parse_heuristic

NAME = "heuristic"
PRIORITY = 999
DESCRIPTION = "Generic fallback parser — walks any --help output for flag patterns."


def detect(help_text: str) -> ToolDef | None:
    return parse_heuristic(help_text)
