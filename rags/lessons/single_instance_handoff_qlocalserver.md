---
topic: v3-architecture
date: 2026-05-07
status: recipe
related: []
---
# Single-instance handoff via QLocalServer

## What happened

By default, double-clicking `run_scriptreering.bat` while V3 is
already running spawns a second isolated process — two ring
windows, two state files, fights over the .scriptreering on
disk.  We want the second invocation to hand its argv to the
already-running primary instead.

## Root cause / design

Standard pattern: the first instance opens a per-user
`QLocalServer`; subsequent invocations connect to that
socket as a `QLocalSocket`, send their argv as JSON, and
exit.  The primary receives the message and acts on it
(open a workspace file, focus its window, etc.).

## Fix / recipe

Implementation lives in `scriptree/shell/single_instance.py`:

- Pipe name: `ScripTreeRing--<sanitised-username>` — per-user
  so multiple users on the same Windows machine each get
  their own primary.
- Override for tests: `SCRIPTREERING_PIPE_NAME` env var.
- Connect timeout: short (~250 ms).  If connect fails, this
  process becomes the primary and starts listening.
- `--new-process` flag opts out of BOTH:
    - don't try to hand off (always start a new instance)
    - don't listen for handoffs (don't become a primary)
  Useful for tests, debug-launches, and intentionally-
  parallel runs.

```python
# scriptree/shell/single_instance.py (sketch)
def try_handoff(argv: list[str]) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(_pipe_name())
    if not sock.waitForConnected(250):
        return False
    sock.write(json.dumps(argv).encode())
    sock.waitForBytesWritten(500)
    return True

def listen_as_primary(on_message):
    server = QLocalServer()
    QLocalServer.removeServer(_pipe_name())  # clean stale
    server.listen(_pipe_name())
    server.newConnection.connect(...)
    return server
```

## How future-me detects it

Two ring windows appear after a second launch, or argv
passed to a second launch is silently dropped.  The pipe
name mismatch (e.g. tests vs prod) usually shows up as
"primary never received argv" — set
`SCRIPTREERING_PIPE_NAME` consistently across both sides.
