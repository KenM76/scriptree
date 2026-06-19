---
topic: single_instance_ack_semantics
date: 2026-06-19
status: gotcha
related: [single_instance_handoff_qlocalserver, forest_controller_module_global_handle]
---
# Single-instance ack means "delivered to the primary", NOT "the work succeeded" — surface failures GUI-side

## What happened

A second launch that opened a bad/locked catalog (`load_catalog` command) or
a bad ring file (`load_ring` command) was SILENT.  The primary logged the
error, acked `ok=true`, and the secondary exited 0 — the user saw no window
and no error message.  Fixed in v0.8.0a65.

Before a65, `load_catalog` in `_handle_primary_message` was also unwrapped:
an exception could escape to `PrimaryServer._on_ready_read`, which would ack
`ok=false` — making the secondary think no primary was running and start a
second instance.

## Root cause

The ack protocol between secondary and primary is:

```
secondary → {command, args} → primary
primary   → {ok: true/false} → secondary
```

`try_handoff()` in `single_instance.py` returns `True` iff the primary acks
`ok=true`.  If `ok=false` or no ack arrives, the secondary falls through to
"no primary running" and starts a second forest.

An `ok=false` ack (or an uncaught exception reaching `_on_ready_read`) means
"there is no live primary to handle this", which is wrong — the primary IS
live; it just failed to execute the requested work.  The secondary starts a
duplicate instance; the user now has two forests.

## Fix / recipe

**Rule:** the ack ALWAYS means "I received this message" (`ok=true`), not
"the work succeeded."  All error handling happens IN THE PRIMARY, surfaced
to the user there.

```python
# ring_main.py — _notify_handoff_error (v0.8.0a65)
def _notify_handoff_error(title: str, text: str) -> None:
    def _show() -> None:
        try:
            from PySide6.QtWidgets import QMessageBox
            parent = None
            fc = _FOREST_CONTROLLER
            if fc is not None:
                parent = getattr(fc, "forest_window", None)
            QMessageBox.warning(parent, title, text)
        except Exception as exc:
            _log(f"_notify_handoff_error: show failed: {exc!r}")
    try:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, _show)   # <<< deferred: must not block readyRead
    except Exception as exc:
        _log(f"_notify_handoff_error: schedule failed: {exc!r}")
```

The `QTimer.singleShot(0, ...)` deferral is CRITICAL:
- A modal dialog inside the `readyRead` handler blocks the handler.
- A blocked handler means the ack is never written back to the socket.
- A missing ack makes the secondary time out and assume no primary → second instance.

Wrap EVERY `_handle_primary_message` branch in a `try/except` that calls
`_notify_handoff_error` on failure, NOT that re-raises to the handler:

```python
if cmd == "load_catalog":
    ...
    try:
        hexagon = CellWindow(branding, catalog_path=str(path))
        ...
    except Exception as exc:
        _log(f"  load_catalog failed: {exc!r}")
        _notify_handoff_error("Open failed", f"Couldn't open:\n{path}\n\n{exc}")
    return  # ← always return; never let exceptions escape to the handler
```

Implementation:
* `D:\Dev\ScripTree\scriptree\shell\ring_main.py`, `_notify_handoff_error` (~lines 349-383).
* `D:\Dev\ScripTree\scriptree\shell\ring_main.py`, `_handle_primary_message`, all branches (~lines 386-497).

## How future-me detects it

Every new command in `_handle_primary_message` MUST:
1. Wrap its body in `try/except`.
2. Call `_notify_handoff_error(title, text)` on failure (not re-raise).
3. Return at the end of the branch unconditionally.
4. Never call any code that itself could raise to `_on_ready_read`.

The invariant: `ack ok=true` is issued for EVERY received message, regardless
of whether the work succeeded.  Outcome is surfaced in the PRIMARY's GUI.
Never ack `ok=false` unless the message was fundamentally malformed (missing
command key etc.) — even then, consider acking ok=true with an error dialog
rather than risking a second instance.
