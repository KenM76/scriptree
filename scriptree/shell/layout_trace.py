"""Diagnostic tracing for cell layout (v0.6.36).

Always-on detailed logging of every event that affects cell
positions or slot state: moves, drags, layout calculations, slot
assignments, snap events, collapse animations.  Writes to a
plain-text log under ``%TEMP%/scriptree-layout-trace.log``
(rotated per process) so a user-reported issue can be analysed
from the actual sequence of events.

The user's instruction (v0.6.36):

    "add diagnostics to track what is happening when I drag,
    where cells are sitting, and anything else. tie up cpu cycles
    if you have to just to do the tracking and logging. get all
    the data you think you need and can use to solve the problem."

CPU budget: this module deliberately ignores the idle-CPU contract
that the rest of the shell holds to.  Each trace call serialises
state, formats a line, and appends to a buffered file.  When idle
(no events) the trace generates nothing — it's event-driven, so
there's no continuous overhead.

Disable with the env var ``SCRIPTREE_LAYOUT_TRACE=0``.

Log format
----------

Plain text, one event per line.  Each line:

    [HH:MM:SS.mmm] EVENT_TYPE key=value key=value ...

A ``SNAPSHOT`` event dumps the entire world state across multiple
lines for context.  Grep-friendly; no JSON.
"""
from __future__ import annotations

import datetime
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Log file management
# ---------------------------------------------------------------------------

_log_path: Optional[Path] = None
_log_handle = None
_log_lock = threading.Lock()
_enabled: bool = os.environ.get("SCRIPTREE_LAYOUT_TRACE", "1") != "0"


def _log_file() -> Optional[Path]:
    """Return (lazily creating on first call) the open log file
    path, or ``None`` if tracing is disabled."""
    global _log_path, _log_handle
    if not _enabled:
        return None
    if _log_handle is not None:
        return _log_path
    # One log per process — timestamped so multiple ScripTree
    # instances don't trample each other.
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    pid = os.getpid()
    tmp = Path(tempfile.gettempdir())
    _log_path = tmp / f"scriptree-layout-trace-{stamp}-{pid}.log"
    try:
        _log_handle = open(_log_path, "w", encoding="utf-8", buffering=1)
    except OSError as exc:
        print(
            f"[layout_trace] failed to open log file "
            f"{_log_path!r}: {exc!r}; tracing disabled",
            file=sys.stderr,
        )
        _log_handle = None
        return None
    header = (
        f"# ScripTree layout trace\n"
        f"# Started: {datetime.datetime.now().isoformat()}\n"
        f"# PID: {pid}\n"
        f"# Format: [HH:MM:SS.mmm] EVENT key=value ...\n"
    )
    _log_handle.write(header)
    print(
        f"[layout_trace] writing trace to {_log_path}",
        file=sys.stderr,
    )
    return _log_path


def log_path() -> Optional[Path]:
    """Public accessor — returns the current log file path (or
    ``None`` if tracing is disabled / hasn't started)."""
    return _log_file()


def is_enabled() -> bool:
    """Whether tracing is currently active."""
    return _enabled


# ---------------------------------------------------------------------------
# Event logging
# ---------------------------------------------------------------------------

def _format_kv(kwargs: dict[str, Any]) -> str:
    """Serialise key=value pairs into a single line, terse and
    grep-friendly.  Tuples render as ``(a,b)`` (no spaces); lists as
    ``[a,b,c]``; strings as bare text (no quotes); None as None."""
    parts: list[str] = []
    for k, v in kwargs.items():
        if isinstance(v, tuple):
            inner = ",".join(str(x) for x in v)
            s = f"({inner})"
        elif isinstance(v, list):
            inner = ",".join(str(x) for x in v)
            s = f"[{inner}]"
        elif isinstance(v, str):
            s = v
        elif v is None:
            s = "None"
        else:
            s = str(v)
        parts.append(f"{k}={s}")
    return " ".join(parts)


def event(event_type: str, **kwargs: Any) -> None:
    """Emit one diagnostic event line."""
    f = _log_file()
    if f is None:
        return
    if _log_handle is None:
        return
    now = datetime.datetime.now()
    ts = now.strftime("%H:%M:%S") + f".{now.microsecond // 1000:03d}"
    line = f"[{ts}] {event_type} {_format_kv(kwargs)}\n"
    with _log_lock:
        try:
            _log_handle.write(line)
        except Exception:  # noqa: BLE001 — tracing must never crash
            pass


def snapshot(label: str, world: Any = None) -> None:
    """Dump the entire world state (every cell's pos, slot,
    parent, role, visibility) as a multi-line block.  Call at
    important transitions (drag start, drag end, after layout,
    forest startup) so the log captures full context.

    ``world`` can be a ``CellRegistry`` instance or None — in the
    None case we ask CellRegistry.instance() for it.
    """
    f = _log_file()
    if f is None or _log_handle is None:
        return

    try:
        from scriptree.shell.cell_registry import CellRegistry
        registry = world if world is not None else CellRegistry.instance()
        cells = list(registry.all())
    except Exception as exc:  # noqa: BLE001
        event("SNAPSHOT_FAILED", label=label, err=repr(exc))
        return

    now = datetime.datetime.now()
    ts = now.strftime("%H:%M:%S") + f".{now.microsecond // 1000:03d}"

    lines: list[str] = [f"[{ts}] SNAPSHOT label={label} n={len(cells)}\n"]
    for c in cells:
        # Best-effort attribute extraction — every CellWindow has
        # these but we guard against odd test doubles.
        try:
            pos = (c.pos().x(), c.pos().y())
        except Exception:  # noqa: BLE001
            pos = ("?", "?")
        cid = getattr(c, "_id", "?")[:8]
        role = getattr(c, "role", "?")
        size = getattr(c, "_size_px", "?")
        # v0.6.37 — also capture the widget's actual rendered size
        # so a discrepancy between logical _size_px and widget
        # geometry (e.g. due to DPI scaling, an unexpected resize)
        # is visible in the trace.  Reported as too-big icons +
        # overlay in v0.6.36 with no obvious cause in the data.
        try:
            widget_w = c.width()
            widget_h = c.height()
        except Exception:  # noqa: BLE001
            widget_w = widget_h = "?"
        icon_scale = getattr(c, "_icon_scale", "?")
        slot = getattr(c, "_slot", "<no-attr>")
        floating = getattr(c, "_floating_intent", "<no-attr>")
        parent = getattr(c, "_group_master_id", None)
        parent_short = parent[:8] if isinstance(parent, str) else parent
        visible = "?"
        try:
            visible = c.isVisible()
        except Exception:  # noqa: BLE001
            pass
        collapse = getattr(c, "_collapse_state", "<no-attr>")
        is_forest = getattr(c, "_is_forest_master", False)
        positioned_count = len(getattr(c, "_positioned", ()) or ())
        members_count = len(getattr(c, "_members", ()) or ())
        auto_hidden = len(getattr(c, "_auto_hidden", ()) or ())
        drag = getattr(c, "_drag_started", "<no-attr>")
        lines.append(
            f"  id={cid} role={role} size_px={size} "
            f"widget=({widget_w}x{widget_h}) icon_scale={icon_scale} "
            f"pos=({pos[0]},{pos[1]}) "
            f"slot={slot} floating={floating} "
            f"parent={parent_short} visible={visible} "
            f"collapse={collapse} forest={is_forest} "
            f"members={members_count} positioned={positioned_count} "
            f"auto_hidden={auto_hidden} drag={drag}\n"
        )

    with _log_lock:
        try:
            for ln in lines:
                _log_handle.write(ln)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def close() -> None:
    """Close the log file.  Called at shutdown — safe to call
    multiple times."""
    global _log_handle
    with _log_lock:
        if _log_handle is not None:
            try:
                _log_handle.write(
                    f"# Closed: {datetime.datetime.now().isoformat()}\n"
                )
                _log_handle.close()
            except Exception:  # noqa: BLE001
                pass
            _log_handle = None
