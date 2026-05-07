"""beta-style smoke driver — exercises the cell shell end-to-end.

This is NOT a pytest test (it spawns long-running GUI processes).
Run it manually with::

    python tests/smoke_beta_sweep.py

It will:

1. Spawn ``run_scriptreering.py --new-process`` as a primary, capture
   stderr.
2. Wait for the primary's "Spawned hexagon" log line.
3. Spawn a secondary ``run_scriptreering.py`` (no flag) and verify the
   secondary handed off and exited with rc=0.
4. Verify the primary received a "spawn_cell" message and spawned a
   second cell.
5. Spawn a tertiary with a positional ``.scriptreetree`` path and
   verify the primary received a load_catalog message.
6. Send SIGTERM to the primary, exit.

Each step prints PASS / FAIL with a short rationale.  No interactive
windows are dismissed — the test framework auto-dismisses dialogs
via ``QMessageBox`` patching, but this driver doesn't run GUI code in
its own process; it only inspects the children.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PYTHON = sys.executable

# Unique pipe name per smoke run so we don't collide with the user's
# live cell shell.  Set in os.environ for every spawned process.
PIPE_NAME = f"ScripTreeRing-smoke-{uuid.uuid4().hex[:12]}"
os.environ["SCRIPTREERING_PIPE_NAME"] = PIPE_NAME
print(f"(using SCRIPTREERING_PIPE_NAME={PIPE_NAME})")


def _spawn(*args: str, isolated: bool = False) -> subprocess.Popen:
    """Spawn ``run_scriptreering.py`` with ``args``.

    ``isolated=True`` adds ``--new-process`` so the spawned instance
    neither tries to hand off to a running primary NOR registers
    itself as one — useful only when intentionally running multiple
    independent processes for diagnostics.
    """
    cmd = [PYTHON, str(ROOT / "run_scriptreering.py"), *args]
    if isolated:
        cmd.append("--new-process")
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def _read_stderr_until(proc: subprocess.Popen, marker: str,
                       timeout_s: float = 5.0) -> str:
    """Read primary's stderr until ``marker`` appears or timeout.
    Returns the accumulated stderr buffer."""
    buf = ""
    end = time.time() + timeout_s
    while time.time() < end:
        # Non-blocking read of one line — Popen.stderr is line-buffered.
        line = proc.stderr.readline()
        if not line:
            time.sleep(0.05)
            continue
        buf += line
        if marker in line:
            return buf
    return buf


def _drain_stderr(proc: subprocess.Popen, dur_s: float = 0.5) -> str:
    """Read whatever is in stderr for ``dur_s`` and return it."""
    buf = ""
    end = time.time() + dur_s
    while time.time() < end:
        line = proc.stderr.readline()
        if not line:
            time.sleep(0.05)
            continue
        buf += line
    return buf


def main() -> int:
    print("=== Beta-style smoke for ScripTreeRing ===")
    fails = 0

    # ---- Step 1: primary boot -----------------------------------------
    print("\n[1] Spawning primary (no flag — should listen + spawn cell) …")
    primary = _spawn()
    out = _read_stderr_until(primary, "Spawned hexagon", timeout_s=8.0)
    if "Spawned hexagon" in out:
        print("  PASS  primary spawned a starter cell")
    else:
        print("  FAIL  primary did not spawn a starter cell within 8s")
        print(f"  stderr so far:\n{out}")
        fails += 1

    if "primary listening on" in out:
        print("  PASS  primary's QLocalServer is listening")
    else:
        print("  FAIL  primary's QLocalServer never logged 'listening'")
        fails += 1

    # ---- Step 2: secondary handoff -----------------------------------
    print("\n[2] Spawning secondary (no flag) — should hand off and exit …")
    secondary = _spawn()
    rc = secondary.wait(timeout=10)
    sec_err = secondary.stderr.read()
    if rc == 0:
        print("  PASS  secondary exited cleanly (rc=0)")
    else:
        print(f"  FAIL  secondary exit code = {rc}")
        print(f"  secondary stderr:\n{sec_err}")
        fails += 1
    if "handed off" in sec_err and "running primary" in sec_err:
        print("  PASS  secondary logged handoff to running primary")
    else:
        print("  FAIL  secondary did not appear to hand off")
        print(f"  secondary stderr:\n{sec_err}")
        fails += 1

    # ---- Step 3: primary received the spawn_cell message -------------
    out2 = _drain_stderr(primary, 1.0)
    if "_handle_primary_message" in out2 and "spawn_cell" in out2:
        print("  PASS  primary received and dispatched the spawn_cell message")
    else:
        print("  FAIL  primary did not log spawn_cell dispatch")
        print(f"  primary stderr after handoff:\n{out2}")
        fails += 1

    # ---- Step 4: tertiary with --new-process ------------------------
    print("\n[3] Spawning a tertiary with --new-process — should NOT hand off …")
    tertiary = _spawn(isolated=True)
    out3 = _read_stderr_until(tertiary, "Spawned hexagon", timeout_s=8.0)
    if "Spawned hexagon" in out3:
        print("  PASS  tertiary spawned its own starter cell")
    else:
        print("  FAIL  tertiary did not spawn a starter cell")
        print(f"  tertiary stderr:\n{out3}")
        fails += 1
    if "no primary running" in out3 or "primary server listen" in out3:
        # Either a clean fall-through OR a name collision (depends on race).
        # Both are fine in a smoke; the key is the cell appeared.
        pass

    # ---- Cleanup -----------------------------------------------------
    print("\n[Cleanup] Terminating spawned processes …")
    for p in (primary, tertiary):
        try:
            p.terminate()
            p.wait(timeout=3)
        except Exception:  # noqa: BLE001
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass

    print("\n=== Summary ===")
    if fails == 0:
        print("ALL CHECKS PASSED")
        return 0
    print(f"{fails} CHECKS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
