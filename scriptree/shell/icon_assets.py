"""Access to the shipped ``icons/`` facet library (v0.6.7).

The repo/deploy ships a curated, trademark-safe monochrome line-icon
set at ``<project root>/icons/icon-<name>.svg`` (see
``help/host-software-icon-style.md``).  This module locates that
directory and hands back an icon's bytes / base64 so the shell can
give a bare ring/forest hub a real glyph instead of derived letters.

No module-level Qt import (used on shell paths that must stay
light); base64 + pathlib only.
"""
from __future__ import annotations

import base64
import sys
from functools import lru_cache
from pathlib import Path


def _log(msg: str) -> None:
    print(f"[icon_assets] {msg}", file=sys.stderr)


@lru_cache(maxsize=1)
def icons_dir() -> Path | None:
    """The shipped ``icons/`` directory, or ``None`` if not found.

    Walks up from this file until an ``icons/`` folder containing at
    least the canonical ``icon-tool.svg`` is found — same
    walk-up-to-project-root heuristic ``ring_io._project_root`` uses,
    but anchored on the icon set so it works in both the source tree
    and a ``make_portable`` deploy.
    """
    here = Path(__file__).resolve().parent
    for _ in range(8):
        cand = here / "icons"
        if (cand / "icon-tool.svg").is_file():
            return cand
        if here.parent == here:
            break
        here = here.parent
    return None


@lru_cache(maxsize=64)
def bundled_icon_b64(name: str) -> str:
    """Return base64 of ``icon-<name>.svg`` from the shipped set, or
    ``""`` if unavailable.  Cached — the hub icon is read on every
    forest/ring launch."""
    d = icons_dir()
    if d is None:
        _log("icons/ directory not found; hub icon unavailable")
        return ""
    p = d / f"icon-{name}.svg"
    if not p.is_file():
        _log(f"bundled icon {name!r} missing at {p}")
        return ""
    try:
        return base64.b64encode(p.read_bytes()).decode("ascii")
    except OSError as exc:
        _log(f"read {p} failed: {exc!r}")
        return ""


__all__ = ["icons_dir", "bundled_icon_b64"]
