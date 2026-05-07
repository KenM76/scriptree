"""
recent_files.py — QSettings-backed recent-files list for HexagonWindow.

Tracks the last N files opened via the hex right-click menu, separated into
two typed lists:
  - recent_scriptree:     *.scriptree  (single-tool definitions)
  - recent_scriptreetree: *.scriptreetree  (multi-tool catalogs)

Storage key: "hex_shell/recent_files" (QSettings, no app/org qualifier —
inherits whatever QApplication set, same as the rest of HexagonWindow).

Public API
----------
  add(path: str) -> None
  get_scriptree() -> list[str]          (most-recent first)
  get_scriptreetree() -> list[str]      (most-recent first)
  clear() -> None
  SCRIPTREE_EXT   = ".scriptree"
  SCRIPTREETREE_EXT = ".scriptreetree"
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings

_MAX_RECENT: int = 10
_KEY_TOOL: str = "hex_shell/recent_scriptree"
_KEY_TREE: str = "hex_shell/recent_scriptreetree"

SCRIPTREE_EXT: str = ".scriptree"
SCRIPTREETREE_EXT: str = ".scriptreetree"


def _ext(path: str) -> str:
    """Return the lower-cased suffix of *path*."""
    return Path(path).suffix.lower()


def _load(key: str) -> list[str]:
    s = QSettings()
    raw = s.value(key, "[]")
    try:
        items = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        items = []
    return [str(p) for p in items if p][:_MAX_RECENT]


def _save(key: str, items: list[str]) -> None:
    s = QSettings()
    s.setValue(key, json.dumps(items))
    s.sync()


def add(path: str) -> None:
    """Prepend *path* to the appropriate typed recent list (capped at _MAX_RECENT)."""
    if not path:
        return
    resolved = str(Path(path).resolve())
    ext = _ext(resolved)
    if ext == SCRIPTREETREE_EXT:
        key = _KEY_TREE
    else:
        # .scriptree and anything else lands in the tool list.
        key = _KEY_TOOL
    items = _load(key)
    items = [p for p in items if p != resolved]
    items.insert(0, resolved)
    del items[_MAX_RECENT:]
    _save(key, items)


def get_scriptree() -> list[str]:
    """Return the recent *.scriptree list, most-recent first."""
    return _load(_KEY_TOOL)


def get_scriptreetree() -> list[str]:
    """Return the recent *.scriptreetree list, most-recent first."""
    return _load(_KEY_TREE)


def clear() -> None:
    """Erase both recent lists from QSettings."""
    s = QSettings()
    s.remove(_KEY_TOOL)
    s.remove(_KEY_TREE)
    s.sync()
