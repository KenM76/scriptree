---
topic: v3-process
date: 2026-05-07
status: gotcha
related: [diagnostics_tagged_stderr_logs]
---
# V2 stale-import pattern

## What happened

V3 inherits chunks of code from V2's hexagon shell.  V2's
style for engine integration is:

```python
try:
    from apps.shell.snap_engine import commit_drag_end
    commit_drag_end(self)
except:
    pass
```

V2's import path was `apps.shell.*`; V3 reorganised to
`scriptree.shell.*` (and renamed `apps.shell.main` to
`scriptree.shell.ring_main`).  Every one of those `try/except`
blocks is a place V3 silently drops engine work — the import
fails, `pass` swallows it, behaviour silently degrades.

v0.2.1–v0.2.3 fixed five of these (drag-end snap commit,
spawn-another snap wire, and three more).  More almost
certainly remain.

## Root cause

Bare `except: pass` around an import means a renamed module
is invisible.  Combined with V2's habit of doing this for
every cross-package call, a rename leaves a trail of
silently-dead integration points.

## Fix / recipe

Two-step fix:

1. Update the import to the new V3 path.
2. Replace the bare `except:` with a logged narrow-catch:

```python
try:
    from scriptree.shell.snap_engine import commit_drag_end
    commit_drag_end(self)
except Exception as exc:
    _log(f"[CellWindow] commit_drag_end failed: {exc!r}")
```

The narrow logged catch makes the NEXT regression visible
instantly — instead of silent degradation, you get a tagged
stderr line (see `diagnostics_tagged_stderr_logs`).

To find remaining ones, grep for the V2 pattern:

```bash
grep -rn "from apps\." scriptree/
grep -rn "except:\s*$" scriptree/ | grep -B1 "from apps"
```

## How future-me detects it

A V3 feature "doesn't do anything" but throws no errors and
leaves no log line.  Or: behaviour that worked in V2's
hexagon shell is silently absent in V3's cell shell.  Find
the corresponding code path and check for a try/import/bare-
except wrapper.
