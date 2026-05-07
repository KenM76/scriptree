---
topic: v3-process
date: 2026-05-07
status: workflow
related: [v2_stale_import_pattern]
---
# Diagnostics-tagged stderr logs

## What happened / rule

Every nontrivial code path in V3 emits a `_log(...)` line
tagged with the subsystem name in brackets:

- `[v1_launcher]` — V1 process spawn / .bat shim
- `[single_instance]` — pipe handoff handshake
- `[CellWindow]` — cell click / drag / snap handlers
- `[merged_tree]` — composite tree building for masters
- `[tree_popup]` — popup menus, suppression timing
- `[cell_metadata]` — catalog metadata read/write

When something silently fails, the tagged log is what tells
you *where* to start looking.  A `tail -f` (or filter) on a
single tag isolates that subsystem's activity in a noisy
session.

## Root cause / rationale

Hidden silent failures are V3's #1 debug cost (see
`v2_stale_import_pattern`).  The fix is making every code
path *say something* on stderr — even a "[X] entered" line.
Stderr is cheap; mystery is expensive.

## Fix / recipe

Each subsystem module defines its own `_log` helper that
prefixes the tag:

```python
# scriptree/shell/cell_window.py
import sys

def _log(msg: str) -> None:
    print(f"[CellWindow] {msg}", file=sys.stderr, flush=True)
```

Then sprinkle calls through any handler that could fail:

```python
def _on_drag_end(self, ev):
    _log(f"drag end at {ev.pos()} for {self._id}")
    try:
        commit_drag_end(self)
    except Exception as exc:
        _log(f"commit_drag_end failed: {exc!r}")
```

The tag in brackets matters — it's what lets a `findstr`
filter pull just one subsystem's activity:

```powershell
python run_scriptreering.py 2>&1 | findstr "\[CellWindow\]"
```

## How future-me detects it

A subsystem that's "silent" in a debug run is a code-smell —
it should be emitting at least entry-level traces.  When
asked "where would I see this fail?", if the answer isn't
"tail stderr for `[X]`", the instrumentation isn't enough.
Adding more `_log()` calls is almost always the right move.
