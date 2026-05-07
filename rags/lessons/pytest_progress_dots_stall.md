---
topic: pyside6
date: 2026-05-07
status: gotcha
related: [powershell_background_buffers_stdout]
---
# pytest progress dots can stall before the summary

## What happened

Watching pytest output through a backgrounded task pipe, the
last visible line was `[ 86% ]` for ~30 s.  It looked stuck —
but it wasn't.  The run was already done; only the summary
was waiting on a flush.

## Root cause

Stdout buffering through the pipe.  pytest's progress dots are
written incrementally, but the final summary is large enough
to trigger a different flush boundary — and when piped through
PowerShell or a file the buffer doesn't drain until the
process actually exits and the OS finalises stdout.

## Fix / recipe

Don't conclude "stuck" from a stalled progress line.  Check
the actual run state:

- `task-status <id>` to see if the process has exited
- `ps -p <pid>` / `tasklist /FI "PID eq <pid>"` to verify
- The exit code from the task wrapper, not the visible tail

If you need real-time progress, run pytest with `-s` (no
output capture) and unbuffered:

```bash
python -u -m pytest -s tests/
```

## How future-me detects it

A pytest run that "stops" at a progress percentage and stays
there for tens of seconds.  Before killing it or assuming a
hang, check the process state and the actual exit code — the
run is very likely already complete and only the flush is
late.
