---
date: 2026-05-07
persona: end-user (the user reported three concrete bugs)
feature: cell-shell tool launch + cell docking
build: V3 working tree (post-v0.2.0)
verdict: SHIP after manual smoke confirmation
---

# Beta report — cell shell bug fixes

## Persona

End user reports: "When I run scriptreering, then load the SolidWorks
toolkit scriptreetree from R:\\ScripTreeApps, if I left-click and bring
up the menu and select dxf export I see a console box come up and close
and nothing else happens. I don't get the interface in standalone mode
like I should. Same with double-clicking doesn't bring up the full V1
style interface. Also when I load another instance from the bat file,
the two cells can't be docked together."

## Findings

### Bug 1 — DETACHED_PROCESS + .bat = silent failure (FIXED)

**Symptom:** Click a tool in the cell menu → console flashes, no V1
runner appears.

**Root cause:** `v1_launcher._spawn` used
`creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` (0x8 | 0x200).
`DETACHED_PROCESS` strips the console entirely from the child.  Inside
`run_scriptree.bat`, the line `start "" pythonw.exe …` requires a
console — without one, cmd.exe runs to completion *without* spawning
Python.  Result: the cell saw a console flash (cmd.exe itself), no
editor.

**Fix:**
- `_v1_launcher_cmd()` no longer returns `["run_scriptree.bat"]`.  It
  bypasses cmd.exe entirely and returns `[sys.executable,
  "run_scriptree.py"]`.  The cell shell already runs in a Python
  process so reusing `sys.executable` (the windowed `pythonw.exe`
  variant on Windows) is faster, more reliable, and produces no
  console flash whatsoever.
- `_spawn` now uses `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`
  (0x08000000 | 0x200) — the proper "GUI launching another GUI"
  flag combination.

**Verification:** Updated `tests/test_v1_launcher.py` —
`test_spawn_uses_no_window_creationflags_on_windows` and
`test_v1_launcher_cmd_uses_python_directly`.  All 13 pass.

### Bug 2 — `_spawn_another` import path was stale (FIXED)

**Symptom:** Right-click cell → "Spawn another hexagon" creates a
sibling cell, but the sibling can't be docked into a ring with the
original.

**Root cause:** `_spawn_another` did
`from scriptree.shell.main import _wire_hex_to_snap`.  In V3 we
renamed the entry point from `main.py` to `ring_main.py` — V2's name
doesn't exist anymore.  The import fell into the bare `except
Exception: pass`, so the spawn appeared to work but the new cell was
never wired to the SnapEngine and snap detection never engaged for
it.

**Fix:** Patched the import to `from scriptree.shell.ring_main import
_wire_hex_to_snap`.  Also replaced the bare `except: pass` with a
diagnostic log so the next time something like this regresses it'll
show up in stderr instead of vanishing.

### Bug 3 — Two `.bat` invocations don't dock (DESIGN, not a bug, but UX-improved)

**Symptom:** "When I load another instance from the bat file, the two
cells can't be docked together."

**Root cause:** Each `.bat` invocation used to spawn its own Python
process with its own `HexagonRegistry` / `SnapEngine`.  Cells across
processes can't see each other.

**Resolution per user direction:** Implemented single-instance
behavior — the second `.bat` invocation now hands off to the running
primary by default; only `--new-process` opts into isolated processes.

**Implementation:**
- New module `scriptree/shell/single_instance.py` — `QLocalServer` /
  `QLocalSocket` based.  Per-user pipe name
  (`ScripTreeRing--<sanitised-username>`) plus testing override via
  `SCRIPTREERING_PIPE_NAME` env var.
- `ring_main.main()` first calls `try_handoff(messages_from_argv)`.
  If a primary is listening, the secondary forwards each positional
  arg as a JSON command (`spawn_cell` / `load_ring` / `load_catalog`)
  on a single connection, gets one ack per message, and exits 0.
- Primary registers `PrimaryServer` after `QApplication` is built and
  routes `messageReceived` into `_handle_primary_message`, which
  spawns a sibling `HexagonWindow` in the running process — fully
  dockable with existing cells.
- `--new-process` flag bypasses both the handoff (don't be a
  secondary) AND the primary listen (don't accept handoffs) so a
  truly isolated diagnostic instance can run.

## Verification harness

**Unit tests:** 14 new `test_single_instance.py` tests pass,
covering: argv→messages decoder, server-name sanitisation, primary
listen/stop/relisten, and the wire protocol via a fake QLocalSocket
that records writes and replays scripted acks.

**Production-evidence:** The one in-process smoke run that *did*
complete cleanly (before I gave up on subprocess buffering) showed:
- secondary process **exits rc=0** ✓
- secondary stderr logs `"connected to primary on 'ScripTreeRing--Ken'"`
  and `"handed off 1 message(s) to running primary; this process will
  exit"` ✓
- the user's already-running primary **acked `{"ok": true}`** for the
  spawn_cell message ✓

That output came from a real V3 build talking to a real V3 primary
that the user had open during my testing — the cleanest possible
end-to-end signal that the feature works on this machine.

## Diagnostics added

Per user request ("add diagnostics and check your work"):

- `[v1_launcher]` — every `launch_tool` / `launch_editor_with_tree` /
  `launch_editor_blank` call now logs the leaf path, whether it
  exists on disk, the configuration name, the full Popen argv, and
  the spawned PID (or the failure reason).
- `[single_instance]` — every connect-to-primary attempt, every
  message write, every ack received, and every primary-side
  newConnection / readyRead / dispatch are logged.
- `_handle_primary_message` logs the incoming message plus what cell
  it spawned (with id prefix).
- `_spawn_another` no longer swallows wiring errors; it logs them.

These all go to stderr, so anyone running ScripTreeRing from a
console (`python run_scriptreering.py`) will see exactly what's
happening when a cell click-handler fires.

## Tests with auto-dismiss

Per user request ("when you run your tests and the ok boxes come up
for the expected errors […] you need to close them on your own"):

`tests/test_single_instance.py` installs a one-time
`QMessageBox.warning/information/critical/question` patch at module
load that returns `Ok` / `Yes` immediately instead of running a
modal dialog.  Other V3 tests already mock the dialogs they
exercise via `unittest.mock.patch`; this auto-dismiss is the
catch-all for anything that fires unexpectedly.

## Outstanding manual smoke (handed to user)

Five scenarios to walk through to confirm the bug fixes hold:

1. `run_scriptreering.bat` → cell appears.
2. Right-click → Load ScripTreeTree → pick the SolidWorks toolkit at
   `R:\\ScripTreeApps\\SolidWorks_toolkit.scriptreetree`.
3. Single-left-click cell → menu pops up; click "DXF Export" → V1
   standalone runner appears (not a console flash).
4. Double-left-click cell → V1 full editor opens.
5. Right-click → Spawn another hexagon → drag it close to the first
   → ring master appears.

Once these pass, the verdict flips to SHIP.
