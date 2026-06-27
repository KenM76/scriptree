"""
recent_files.py — QSettings-backed recent-files list for CellWindow.

## For humans

Tracks the last N files opened via the hex right-click menu, separated into
two typed lists:
  - recent_scriptree:     *.scriptree  (single-tool definitions)
  - recent_scriptreetree: *.scriptreetree  (multi-tool catalogs)

Storage key: "hex_shell/recent_files" (QSettings, no app/org qualifier —
inherits whatever QApplication set, same as the rest of CellWindow).

Public API
----------
  add(path: str) -> None
  get_scriptree() -> list[str]          (most-recent first)
  get_scriptreetree() -> list[str]      (most-recent first)
  clear() -> None
  SCRIPTREE_EXT   = ".scriptree"
  SCRIPTREETREE_EXT = ".scriptreetree"

## For maintainers / LLMs

* Two physical keys are used — ``hex_shell/recent_scriptree`` and
  ``hex_shell/recent_scriptreetree`` — despite the docstring header
  mentioning ``hex_shell/recent_files``; the per-type keys are the
  source of truth.  ``clear()`` removes exactly those two.
* ``QSettings()`` is constructed with NO org/app args on purpose: it
  inherits whatever the running ``QApplication`` set. Calling these
  functions before ``QApplication.setOrganizationName/Name`` writes
  into a different store than later reads — only call after the app
  is branded.
* Routing rule: only the exact suffix ``.scriptreetree`` lands in the
  tree list; ``.scriptree`` *and any other extension* fall through to
  the tool list.  This is intentional (`add` has no validation) — do
  not "fix" it into raising on unknown extensions.
* ``add`` resolves the path (``Path.resolve()``) before storing AND
  de-dupes on the resolved string, so two spellings of the same file
  collapse to one entry; dedup happens before the ``insert(0, ...)``
  so re-adding promotes to most-recent.
* Cap is enforced twice: ``_load`` slices ``[:_MAX_RECENT]`` on read
  and ``add`` does ``del items[_MAX_RECENT:]`` on write — keep both so
  a hand-edited oversized store still self-heals.
* ``_load`` tolerates a stored value that is already a list (older
  format) or a JSON string, and swallows ``JSONDecodeError``/``TypeError``
  to ``[]``.  Falsy entries are filtered (``if p``).  Preserve this
  leniency — corrupt settings must degrade to an empty list, never
  raise into the menu code.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings

_MAX_RECENT: int = 10
_KEY_TOOL: str = "hex_shell/recent_scriptree"
_KEY_TREE: str = "hex_shell/recent_scriptreetree"
_KEY_LAYOUT: str = "hex_shell/recent_scriptreelayout"

SCRIPTREE_EXT: str = ".scriptree"
SCRIPTREETREE_EXT: str = ".scriptreetree"
SCRIPTREELAYOUT_EXT: str = ".scriptreelayout"


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


def add_layout(path: str) -> None:
    """Prepend *path* to the recent cell-layout list (v0.8.0a83).

    Same dedup-on-resolved-path + cap-at-_MAX_RECENT contract as ``add``,
    but a dedicated list (no extension routing — layouts are always
    ``.scriptreelayout``).  Used by the forest's Cell-layout Save/Load menu.
    """
    if not path:
        return
    resolved = str(Path(path).resolve())
    items = _load(_KEY_LAYOUT)
    items = [p for p in items if p != resolved]
    items.insert(0, resolved)
    del items[_MAX_RECENT:]
    _save(_KEY_LAYOUT, items)


def get_layouts() -> list[str]:
    """Return the recent *.scriptreelayout list, most-recent first."""
    return _load(_KEY_LAYOUT)


def clear() -> None:
    """Erase all recent lists from QSettings."""
    s = QSettings()
    s.remove(_KEY_TOOL)
    s.remove(_KEY_TREE)
    s.remove(_KEY_LAYOUT)
    s.sync()
