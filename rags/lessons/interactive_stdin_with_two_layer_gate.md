---
topic: v3-architecture
date: 2026-05-07
status: pattern
related: [permissions, runner, tool_runner]
---
# Interactive stdin with a two-layer permission gate

## What happened / rule

V3 v0.3.0 grew an interactive-stdin runner mode so tools can read
user input while running (Emacs M-% style query-replace, confirm-
each-file batch ops, REPL-style exploration).  The implementation
hangs on **two independent gates** that BOTH have to be true:

1. The `.scriptree` declares `"interactive": true` (per-tool opt-in).
2. The deployed `permissions/` folder has a writable
   `interactive_stdin` file (admin opt-in — **default-denied**).

When either is false the runner falls back to one-shot mode (the
pre-v0.3 contract) and the send-line widget stays hidden.  When
both are true the runner spawns with `stdin=PIPE` and surfaces a
QLineEdit + y/n/!/q quick buttons + Send + End-input row below
the output pane.

## Why two gates instead of one

* **Tool flag alone** would let any downloaded `.scriptree` switch
  on a stdin pipe — bad in shared / locked-down installs.
* **Permission alone** would force every existing tool to acquire
  the widget even when it doesn't read stdin — confusing UI.

Both must agree.  Tool authors opt in (their tool needs it);
admins opt in (their org allows it).

## Wiring map

| Layer | File | Role |
|---|---|---|
| Permission | `core/permissions.py` | Add `interactive_stdin` to `CAPABILITIES`.  Gets default-deny semantics for free from `_read_capability` (file missing -> denied at app level when a permissions/ dir is deployed). |
| Schema | `core/model.py` | `ToolDef.interactive: bool = False`.  Default keeps v0.2.x round-trip byte-identical. |
| Round-trip | `core/io.py` | Emit `"interactive": true` only when True (skip when False so legacy files stay byte-identical).  Loader coerces with `bool(data.get("interactive", False))`. |
| Subprocess | `core/runner.py` | `spawn_streaming(..., interactive=False)` — `stdin=PIPE` when True, `stdin=DEVNULL` otherwise.  No new function — extend the existing one. |
| Worker | `ui/tool_runner.py::_RunWorker` | Accepts `interactive` kwarg.  Public `send_line(text) -> bool` and `close_stdin()` — both safe to call from any thread; both no-op cleanly when no proc handle exists. |
| UI | `ui/tool_runner.py::ToolRunnerView` | `_build_interactive_input_row()` builds the widget unconditionally (so tests can inspect it), then `_refresh_interactive_visibility()` toggles `setVisible` based on (`tool.interactive` AND `perms.can("interactive_stdin")`). |
| Run path | `ui/tool_runner.py::_start_run` | Computes `run_interactive` from both gates.  When tool opted in but permission denied, prints a one-line goldenrod warning into the output pane.  Passes `interactive=run_interactive` to `_RunWorker`. |
| Editor | `ui/tool_editor.py` | `QCheckBox` in the top group, two-way bound to `ToolDef.interactive` via `_on_interactive_toggled`. |

## Run-as-user incompatibility

`spawn_streaming_as_user` uses `CreateProcessWithLogonW` and
inherited handles for stdout/stderr only — wiring an inherited
stdin pipe through impersonation needs additional plumbing we
haven't done.  When a configuration sets
`prompt_credentials: true`, the worker emits a `[warning]` on
stderr and runs non-interactively even if the tool opted in.
Documented in the ToolDef schema doc and the security doc.

## Threading note for `send_line`

```python
def send_line(self, text: str) -> bool:
    proc = self._proc
    if proc is None or proc.stdin is None:
        return False
    if proc.poll() is not None:
        return False
    try:
        proc.stdin.write(text + "\n")
        proc.stdin.flush()
    except (BrokenPipeError, OSError, ValueError):
        return False
    return True
```

Writes from the UI thread to `Popen.stdin` are safe — Python's
GIL serialises the underlying file-object access, and the
stdin pipe is independent of the stdout/stderr pump threads.
The triple-catch (BrokenPipe / OSError / ValueError) covers
the common races: child exited mid-write, pipe was closed by
End-input, file object was already closed.

## Tool-script pattern (Python)

For an interactive tool that the runner can drive cleanly:

```python
import sys

def _flush_print(*args, **kwargs):
    kwargs.setdefault("flush", True)  # critical
    print(*args, **kwargs)

_flush_print("Replace 'foo' with 'bar'? [y/n/!/q]:", end=" ")
line = sys.stdin.readline()  # blocks until UI sends a line
if not line:
    sys.exit(1)  # EOF -> treat as quit
answer = line.strip()[:1].lower()
```

Two non-obvious bits:

* **Always flush prompts.**  Without `flush=True`, Python buffers
  the prompt until newline / 4 KB / process exit.  The runner
  reads line-by-line, so a buffered prompt looks like a hang.
* **Treat empty `readline()` as EOF, not error.**  When the user
  clicks End input the pipe closes; `readline()` returns `""`.
  Exit cleanly (any non-zero code is fine).

## How future-me detects it

* If the send-line widget doesn't appear when expected, check
  BOTH gates: `tool.interactive` and `perms.can("interactive_stdin")`.
  The runner logs a `[interactive disabled]` warning to the
  output pane when the permission denies but the tool opted in.
* If a tool seems to hang waiting for input, check that its
  `print()` calls have `flush=True` — buffered output looks
  identical to a real hang from the runner's perspective.
* If `send_line` returns False repeatedly, the child has either
  exited or never opened stdin (worker built with `interactive=False`).

## Tests

Five files cover the feature:

* `tests/test_interactive_permission.py` — capability registration,
  default-deny when file missing, granted when file writable,
  denied when read-only, dev-mode (no perm dir) allows.
* `tests/test_interactive_io_roundtrip.py` — ToolDef field default,
  to_dict / from_dict, save / load round-trip, byte-identical when
  False, defensive coercion of legacy truthy values.
* `tests/test_interactive_runner.py` — `spawn_streaming(interactive=)`,
  `_RunWorker.send_line` end-to-end through a real subprocess,
  visibility gating, quick-response button wiring, no-process
  warnings.
* `tests/test_interactive_editor_checkbox.py` — checkbox <->
  ToolDef.interactive two-way binding + save round-trip.
* `tests/test_find_replace_demo.py` — the demo script with all
  answer combinations (y / n / ! / q), regex + case sensitivity,
  EOF handling, error paths.

44 tests total.
