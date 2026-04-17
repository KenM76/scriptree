"""Plugin: generic heuristic parser (catch-all fallback).

Always returns a ToolDef — even for unrecognized help text — so this
plugin guarantees that the probe never falls through to nothing.
Runs last (``PRIORITY=999``) so more specific plugins get a chance
to claim the text first.
"""
from __future__ import annotations

from ...model import ToolDef
from ._core import parse_heuristic

NAME = "heuristic"
PRIORITY = 999
DESCRIPTION = "Generic fallback parser — walks any --help output for flag patterns."


def detect(help_text: str) -> ToolDef | None:
    return parse_heuristic(help_text)
