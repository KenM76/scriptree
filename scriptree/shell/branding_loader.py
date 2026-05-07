"""
branding_loader.py — load branding/branding.config.json from the project root.

Resolution strategy: walk up from this file's directory until we find a
directory that contains both 'branding/' and 'CLAUDE.md'.  This is
portable — no env-var dependency, no hardcoded path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _log(msg: str) -> None:
    print(f"[branding_loader] {msg}", file=sys.stderr)


def _find_project_root(start: Path) -> Path:
    """Walk up from `start` until we find a dir with branding/branding.config.json."""
    current = start.resolve()
    for _ in range(10):  # guard against infinite walk
        candidate = current / "branding" / "branding.config.json"
        if candidate.is_file():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise FileNotFoundError(
        f"Could not locate branding/branding.config.json starting from {start}. "
        "Ensure you are running from within the ScripTree2 project tree."
    )


def load_branding() -> dict:
    """Return the parsed branding.config.json as a plain dict.

    Raises FileNotFoundError if the project root cannot be determined.
    """
    start = Path(__file__).resolve().parent  # apps/shell/
    project_root = _find_project_root(start)
    config_path = project_root / "branding" / "branding.config.json"
    _log(f"Loading branding from {config_path}")
    with config_path.open(encoding="utf-8") as fh:
        return json.load(fh)
