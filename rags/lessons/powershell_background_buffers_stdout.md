---
topic: pyside6
date: 2026-05-07
status: gotcha
related: [pytest_progress_dots_stall]
---
# PowerShell `$out = python …` buffers in PS background mode

## What happened

Ran a long pytest from PowerShell with `$out = python -m pytest …`
as a background task.  The task output file showed nothing for
the entire run.  When the run later crashed, there was zero
captured output to debug from.

## Root cause

When PowerShell stores a spawned process's stdout in a variable
AND the surrounding command is running as a PS background task,
NOTHING is flushed to the task's output file until the variable
is finalised at process exit.  If the task dies (timeout, kill,
crash), the buffer is lost — you get an empty output file.

## Fix / recipe

Two reliable options:

1. **Pipe through `Tee-Object` to stream live to a file:**
   ```powershell
   python -m pytest tests/ 2>&1 | Tee-Object -FilePath C:/tmp/pytest.log
   ```
   The file gets written line-by-line as the run progresses;
   even if the task dies you have everything up to the crash.

2. **Run from bash with explicit redirect + tail:**
   ```bash
   python -m pytest tests/ > /tmp/pytest.log 2>&1
   tail -50 /tmp/pytest.log
   ```
   Bash streams to disk by default — no buffering trap.

Don't use `$out = …` in a backgrounded PS task if you care
about partial output.

## How future-me detects it

A backgrounded PowerShell task that finished (or died) with an
empty or much-shorter-than-expected output file, when running
the same command interactively prints lots of output.  The
stdout went somewhere — into a process-exit-only buffer.
