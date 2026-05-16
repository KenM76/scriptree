"""Persisted state for the sanitization-warning suppression feature
(V3 v0.3.4).

## For humans

The injection-warning dialog gives users three "Don't warn again"
checkboxes when the ``suppress_sanitization_warnings`` capability
is granted:

* **For these field(s)** — silence further warnings for the same
  param IDs in this same tool.
* **For this tool** — silence every warning from this tool.
* **For all tools** — global mute.

This module is the single source of truth for that state, persisted
via ``QSettings``.  It also provides the inverse operations the
re-enable dialog uses:

* List currently-muted tools / fields.
* Un-mute a specific entry.
* Clear everything.

State storage layout in QSettings — three keys under the
``sanitize_suppress/`` namespace:

* ``sanitize_suppress/global``   → ``bool``
* ``sanitize_suppress/tools``    → JSON-encoded ``list[str]`` of
  resolved file paths.
* ``sanitize_suppress/fields``   → JSON-encoded
  ``dict[str, list[str]]`` mapping resolved tool path to a list
  of field IDs (param IDs OR free-text labels for non-form
  warnings — extras / cmd-line editor).

JSON is used over Qt's native list / dict roundtrip to avoid
QSettings's INI quoting quirks on Windows.

Public API:

``is_globally_muted() -> bool``
``set_globally_muted(muted: bool) -> None``

``is_tool_muted(tool_path: str) -> bool``
``mute_tool(tool_path: str) -> None``
``unmute_tool(tool_path: str) -> None``
``muted_tools() -> list[str]``

``muted_fields_for_tool(tool_path: str) -> list[str]``
``mute_fields_for_tool(tool_path: str, field_ids: Iterable[str]) -> None``
``unmute_field_for_tool(tool_path: str, field_id: str) -> None``

``clear_all() -> None``  — resets all three lists.

``filter_warnings(tool_path, warnings, field_ids_per_warning) -> list[str]``
    Convenience: drop warnings whose field is muted for this tool.
    The caller passes a parallel list of field IDs (one per
    warning) — ``""`` for warnings that came from a non-form source
    (extras / cmd-line editor).

## For maintainers / LLMs

* No module-level Qt import — QSettings is reached only through a
  function-local ``from .app_settings import get_settings`` inside
  ``_settings()``. Keep that indirection: tests monkey-patch
  ``_settings`` to use a throwaway keyspace, and a top-level Qt
  import would also break the ``core`` purity baseline.
* Tool-path KEY normalisation is the central invariant: every
  public function routes the path through ``_resolve`` (which
  ``Path.resolve()``s, falling back to the raw string when the file
  is gone). Two callers using forward vs back slashes MUST collapse
  to the same key — if you add an entry-point, route it through
  ``_resolve`` too or you'll silently fragment the store.
* Persistence values are JSON STRINGS, not native Qt list/dict
  (deliberate, to dodge INI quoting on Windows). All loaders
  (``_load_tools_list`` / ``_load_fields_map``) tolerate bad/typed
  JSON by returning the empty container — never let a corrupt
  setting raise here. Every setter calls ``.sync()`` so state
  survives a hard exit.
* Three-tier model: global and per-tool mute decide whether to skip
  the dialog ENTIRELY (``should_skip_dialog``); per-field mute only
  trims the warning list (``filter_warnings``) and can still leave
  it non-empty. That's why per-field is absent from
  ``should_skip_dialog`` — keep these two responsibilities split.
* ``filter_warnings`` is defensive: a length mismatch between
  ``warnings`` and ``field_ids_per_warning`` shows EVERYTHING rather
  than risk dropping a real warning. Preserve fail-open here —
  silently hiding a security warning is worse than a redundant one.
* ``clear_all`` writes the literal ``"[]"`` / ``"{}"`` strings (not
  ``remove``) so the keys keep their JSON-string type for the
  loaders. Keep that representation consistent if you add keys.
* Gating: the "Don't warn again" checkboxes only appear when the
  ``suppress_sanitization_warnings`` capability is granted (enforced
  at the UI layer, not here) — this module trusts its caller.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# QSettings keys
# ---------------------------------------------------------------------------

_KEY_GLOBAL = "sanitize_suppress/global"
_KEY_TOOLS = "sanitize_suppress/tools"
_KEY_FIELDS = "sanitize_suppress/fields"


def _settings():
    """Return the cached app QSettings.  Indirection here so tests
    can monkey-patch a private QSettings keyspace without poisoning
    the user's real ScripTree config."""
    from .app_settings import get_settings
    return get_settings()


def _resolve(path: str | Path) -> str:
    """Normalise a tool path so two equal-looking strings (one with
    forward slashes, one with back) collapse into the same key.

    Falls back to the raw string when ``Path.resolve()`` fails
    (e.g. the file no longer exists on disk — which is fine,
    suppression entries can outlive their file)."""
    try:
        return str(Path(path).resolve())
    except (OSError, RuntimeError):
        return str(path)


# ---------------------------------------------------------------------------
# Global mute
# ---------------------------------------------------------------------------

def is_globally_muted() -> bool:
    return bool(_settings().value(_KEY_GLOBAL, False, type=bool))


def set_globally_muted(muted: bool) -> None:
    _settings().setValue(_KEY_GLOBAL, bool(muted))
    _settings().sync()


# ---------------------------------------------------------------------------
# Per-tool mute
# ---------------------------------------------------------------------------

def _load_tools_list() -> list[str]:
    raw = _settings().value(_KEY_TOOLS, "[]", type=str)
    try:
        items = json.loads(raw) if isinstance(raw, str) else []
    except (json.JSONDecodeError, TypeError):
        items = []
    return [str(p) for p in items if p]


def _save_tools_list(tools: list[str]) -> None:
    _settings().setValue(_KEY_TOOLS, json.dumps(tools))
    _settings().sync()


def muted_tools() -> list[str]:
    return list(_load_tools_list())


def is_tool_muted(tool_path: str | Path) -> bool:
    if not tool_path:
        return False
    return _resolve(tool_path) in _load_tools_list()


def mute_tool(tool_path: str | Path) -> None:
    if not tool_path:
        return
    key = _resolve(tool_path)
    tools = _load_tools_list()
    if key in tools:
        return
    tools.append(key)
    _save_tools_list(tools)


def unmute_tool(tool_path: str | Path) -> None:
    if not tool_path:
        return
    key = _resolve(tool_path)
    tools = [t for t in _load_tools_list() if t != key]
    _save_tools_list(tools)


# ---------------------------------------------------------------------------
# Per-field mute (within a specific tool)
# ---------------------------------------------------------------------------

def _load_fields_map() -> dict[str, list[str]]:
    raw = _settings().value(_KEY_FIELDS, "{}", type=str)
    try:
        data = json.loads(raw) if isinstance(raw, str) else {}
    except (json.JSONDecodeError, TypeError):
        data = {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for k, v in data.items():
        if isinstance(v, list):
            out[str(k)] = [str(x) for x in v]
    return out


def _save_fields_map(fields: dict[str, list[str]]) -> None:
    _settings().setValue(_KEY_FIELDS, json.dumps(fields))
    _settings().sync()


def muted_fields_for_tool(tool_path: str | Path) -> list[str]:
    if not tool_path:
        return []
    return list(_load_fields_map().get(_resolve(tool_path), []))


def mute_fields_for_tool(
    tool_path: str | Path, field_ids: Iterable[str],
) -> None:
    if not tool_path:
        return
    key = _resolve(tool_path)
    new_ids = {f for f in field_ids if f}
    if not new_ids:
        return
    fields = _load_fields_map()
    existing = set(fields.get(key, []))
    fields[key] = sorted(existing | new_ids)
    _save_fields_map(fields)


def unmute_field_for_tool(
    tool_path: str | Path, field_id: str,
) -> None:
    if not tool_path or not field_id:
        return
    key = _resolve(tool_path)
    fields = _load_fields_map()
    current = fields.get(key, [])
    new = [f for f in current if f != field_id]
    if not new:
        fields.pop(key, None)
    else:
        fields[key] = new
    _save_fields_map(fields)


# ---------------------------------------------------------------------------
# Bulk reset
# ---------------------------------------------------------------------------

def clear_all() -> None:
    """Re-enable every suppressed warning.

    Called from the Edit ▸ Sanitization warnings dialog when the
    user picks "Re-enable all".  Resets the global flag, clears
    the per-tool list, and clears the per-field map.
    """
    s = _settings()
    s.setValue(_KEY_GLOBAL, False)
    s.setValue(_KEY_TOOLS, "[]")
    s.setValue(_KEY_FIELDS, "{}")
    s.sync()


# ---------------------------------------------------------------------------
# Filtering helper
# ---------------------------------------------------------------------------

def filter_warnings(
    tool_path: str | Path | None,
    warnings: list[str],
    field_ids_per_warning: list[str],
) -> list[str]:
    """Drop warnings whose field is muted for this tool.

    The two input lists must be parallel — one ``field_id`` per
    ``warning``.  Empty-string field IDs (warnings from extras /
    cmd-line editor) are kept as-is unless the whole tool is muted.

    The global / per-tool mute is NOT applied here — the caller
    decides whether to skip the dialog entirely based on those.
    """
    if not warnings:
        return []
    if not tool_path:
        # Without a tool path we have nowhere to consult per-field
        # mutes — fall back to "show every warning".
        return list(warnings)
    if len(field_ids_per_warning) != len(warnings):
        # Defensive: caller miscounted.  Show everything rather than
        # accidentally drop warnings.
        return list(warnings)
    muted = set(muted_fields_for_tool(tool_path))
    if not muted:
        return list(warnings)
    out: list[str] = []
    for warning, fid in zip(warnings, field_ids_per_warning):
        if fid and fid in muted:
            continue
        out.append(warning)
    return out


def should_skip_dialog(tool_path: str | Path | None) -> bool:
    """Return True iff the dialog should be entirely skipped for
    ``tool_path`` due to global or per-tool mute.

    Per-field mute is handled by ``filter_warnings`` (which can
    leave the warning list non-empty even when some fields are
    muted) — that's why per-field doesn't appear here.
    """
    if is_globally_muted():
        return True
    if tool_path and is_tool_muted(tool_path):
        return True
    return False
