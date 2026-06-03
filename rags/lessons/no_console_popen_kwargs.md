---
topic: pyside6
date: 2026-06-03
status: recipe
related: [detached_process_breaks_bat, version_lives_in_two_files]
---
# Suppressing the Windows console pop-up when a GUI app spawns CLI tools

## What happened

User reported: "whenever I run some tools, they invoke py.exe, which
results in a pop-up command line box.  Is there any way to reliably
hide this from happening in all situations, including cross
platform?"

Investigation showed that the main runner Popen at
`scriptree/core/runner.py:1027` (`spawn_streaming`) was missing
`creationflags` entirely.  Every tool launched through the runner
whose executable was `py.exe`, `python.exe`, `cmd.exe`, a `.bat`,
or any console-subsystem `.exe` flashed a console window because
Windows allocates one by default when the parent process
(`pythonw.exe`) is itself windowless.

Other Popen sites in the codebase already had the right flag
(`shell/v1_launcher.py`, `shell/click_to_run.py`).  Several didn't
(`core/runner.py`, `core/providers.py`, `core/parser/probe.py`,
`ui/standalone_window.py`, `ui/tool_runner.py`).  One site
(`ui/main_window.py:1305`) was using `DETACHED_PROCESS` which is
WRONG per our own
`rags/lessons/detached_process_breaks_bat.md` lesson.

## Root cause

Windows allocates a console window for every console-subsystem
child by default when the parent doesn't have a console.  The
ScripTree launcher chain ends in `pythonw.exe` (Windows subsystem,
no console), so every console-subsystem child gets a fresh window.

**Redirecting stdout/stderr does NOT suppress the window.**  Pipe
redirection controls where the streams GO, not whether the OS
allocates a console.  The window opens regardless.

The fix is the `CREATE_NO_WINDOW` creation flag passed via
`creationflags=` to `subprocess.Popen` / `subprocess.run`.  This
tells the kernel "do not allocate a console for this child" --
streams still work via PIPE / DEVNULL exactly as if a console
were present.

## Fix / recipe

Centralised helper in `scriptree/core/runner.py`:

```python
def no_console_popen_kwargs() -> dict:
    """Return Popen/run kwargs that suppress the console window.
    No-op on macOS/Linux (returns {})."""
    if sys.platform != "win32":
        return {}
    CREATE_NO_WINDOW = 0x08000000
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    return {"creationflags": CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP}
```

Apply at every Popen/run site that spawns a user-controlled tool:

```python
from scriptree.core.runner import no_console_popen_kwargs
subprocess.Popen(argv, **other_kwargs, **no_console_popen_kwargs())
subprocess.run(argv, capture_output=True, **no_console_popen_kwargs())
```

The helper returns `{}` on non-Windows, so callers can blindly
merge it into kwargs cross-platform.

### Flag selection

| Flag | Hex | What it does | Use? |
|---|---|---|---|
| `CREATE_NO_WINDOW` | `0x08000000` | Prevents allocation of a console for the child.  Streams still work via PIPE/DEVNULL. | YES — the actual no-window switch. |
| `CREATE_NEW_PROCESS_GROUP` | `0x00000200` | Puts the child in its own Ctrl-C group, isolated from the parent's group. | YES — matches GUI-spawning-CLI semantics, prevents the user's Ctrl-C from killing our tools. |
| `DETACHED_PROCESS` | `0x00000008` | Strips the console **entirely** (not just hides). | **NO** — breaks `.bat` shims because `cmd.exe` needs a console even if invisible.  See `detached_process_breaks_bat.md`. |
| `STARTF_USESHOWWINDOW`+`SW_HIDE` via `STARTUPINFO` | n/a | Hides the window AFTER allocation. | NO — can cause a visible flash on slow machines.  `CREATE_NO_WINDOW` prevents allocation in the first place. |

### Sites that need the helper

Every Popen/run that spawns a user-controlled tool.  Audit list
as of v0.8.0a29:

- `scriptree/core/runner.py::spawn_streaming` — the main runner.
- `scriptree/core/providers.py::resolve_provider` — dropdown providers.
- `scriptree/core/parser/probe.py::_run_help` — `--help` probing.
- `scriptree/ui/standalone_window.py` — custom-menu commands.
- `scriptree/ui/tool_runner.py` — custom-menu commands.
- `scriptree/ui/main_window.py` — launching ScripTreeRing
  (previously used DETACHED_PROCESS — fixed in v0.8.0a29).
- `scriptree/shell/v1_launcher.py` — already correct.
- `scriptree/shell/click_to_run.py` — already correct.

Sites that do NOT need it (exempt):

- File-manager invocations (`explorer`, `open`, `xdg-open`):
  `ui/widgets/param_widgets.py`, `ui/tool_runner.py:4031+`.  No
  console involved.
- Cases where the user explicitly wants a visible terminal —
  implemented in the user's own argv (`start cmd /k ...`), not
  by omitting this kwarg.

## How future-me detects it

* User reports "tool launches a console window briefly" or "py.exe
  pops up a window."
* New Popen site added without `no_console_popen_kwargs()` —
  regression caught by `tests/test_no_console_popen.py` if the new
  site has a corresponding test class.
* `grep -n 'subprocess\\.Popen\\|subprocess\\.run' scriptree/`
  reveals a call site without the helper merge.

## Cross-platform notes

* macOS / Linux: no per-child console window concept.  Children
  inherit the parent's terminal if any; otherwise run windowless.
  The helper returns `{}` so the same call site works
  cross-platform without branching.
* The flag values `CREATE_NO_WINDOW = 0x08000000` and
  `CREATE_NEW_PROCESS_GROUP = 0x00000200` are stable across all
  Windows versions that support them (XP SP1+).  No need to
  import from `subprocess` — defining them inline keeps the
  helper Qt-free and avoids the noise of an `import platform`
  check.

## Test recipe

`tests/test_no_console_popen.py` patches `subprocess.Popen` /
`subprocess.run` at each site, triggers the site, and inspects
the `creationflags` kwarg.  Call-site test, not end-to-end —
no actual processes spawn.  See that file for the pattern.
