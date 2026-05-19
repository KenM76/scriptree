"""Click-to-run launcher for cell single-click "run" mode (V3 v0.3.5+).

When a cell's bound catalog has ``cell.click_action == "run"`` and
the ``cell_click_to_run`` capability is granted, single-clicking
the cell fires the tool(s) directly instead of showing the popup
menu.  Three dispatch shapes:

* **.scriptree / single tool** — spawn one V1 standalone with
  ``-run`` so V1 auto-clicks the Run button after the form loads.
* **.scriptreetree, parallel mode** — for every top-level leaf
  (``ToolDef`` reference), spawn a V1 standalone with ``-run``
  immediately.  All processes start at the same time; the user
  ends up with N independent windows.
* **.scriptreetree, sequential mode** — spawn the first leaf's V1
  standalone with ``-run``.  Poll for that process's exit via a
  ``QTimer``.  When it exits, spawn the next.  Continue until
  the leaf list is exhausted (or the user closes the cell shell).

Sequential mode tracks state in a module-level dict keyed by a
fresh per-invocation UUID so two cells running their own
sequences don't clobber each other.

### Tree-walk semantics

The leaf-walker recurses through every folder, accepting any
leaf whose path resolves to a ``.scriptree``.  Sub-trees
(``.scriptreetree`` leaves) are NOT recursively walked — running
a tree-of-trees deeply could trigger surprising fan-out and the
cell-shell UX hasn't reasoned about it yet.  A nested tree leaf
is treated as a single tool (``-run`` opens its standalone with
all leaves in tabs; the user has to click Run on each tab).

## For maintainers / LLMs

- This module shells out to the V1 editor via subprocess
  (``v1_launcher._spawn`` / ``_v1_launcher_cmd`` / ``launch_tool``).
  It NEVER imports the editor.  Keep it that way — the shell and the
  V1 editor are separate processes by design.
- ``_inflight_runs`` is keyed by a fresh ``uuid4()`` per
  ``_run_sequential`` call, NOT by a "master_key".  The old docstring
  said "master_key" — that was wrong; the UUID scheme is what prevents
  two concurrent sequences from sharing state.
- ``_spawn_v1_standalone`` duplicates ``v1_launcher._spawn``'s Windows
  ``creationflags`` (``CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`` =
  ``0x08000000 | 0x00000200``).  If ``v1_launcher._spawn`` changes its
  flags, change them here too — they are intentionally identical and
  hand-copied, so they will silently drift otherwise.
- Sequential "exit" means the *V1 standalone window* closed, not the
  underlying tool process (which V1 owns).  ``_poll_sequential`` reads
  ``Popen.poll()`` and re-arms a 500 ms ``QTimer.singleShot``.  There is
  no cap on total polls and no way for a caller to cancel an in-flight
  sequence — closing the cell shell does not stop the chain (it keeps
  spawning the rest of the queue).
- ``_schedule_poll`` has a no-Qt fallback that calls ``proc.wait()``
  synchronously — TEST ONLY.  It will block the calling thread; never
  rely on it in production (production always has PySide6 importable).
- ``_advance_sequential`` recurses synchronously when a spawn fails or
  ``current_proc`` is ``None`` (skip-to-next).  A long run of
  back-to-back spawn failures recurses once per leaf — bounded by queue
  length, but it is real recursion, not a loop.
- ``collect_leaf_tool_paths`` resolves relative leaf paths against the
  *tree file's directory*, not CWD.  Absolute leaf paths are
  ``.resolve()``-d.  ``.scriptreetree`` leaves are returned verbatim
  (opaque) — the caller decides fan-out.
- ``run_catalog_on_click`` swallows a failed tree walk (logs and
  returns) so a broken catalog can't crash the cell on click; a single
  bad leaf in parallel mode is logged and skipped, the rest still spawn.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Iterable

from .v1_launcher import _spawn, _v1_launcher_cmd, launch_tool


def _log(msg: str) -> None:
    print(f"[click_to_run] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Tree walking
# ---------------------------------------------------------------------------

def collect_leaf_tool_paths(tree_path: str | Path) -> list[str]:
    """Return the absolute paths of every ``.scriptree`` leaf in
    the tree (depth-first, in document order).

    Folder nodes are recursed into.  Sub-tree leaves
    (``.scriptreetree`` paths) are kept as-is — the caller
    decides whether to fan them out or treat them as opaque.
    """
    from ..core.io import load_tree

    src = Path(tree_path).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"Tree not found: {src}")

    tree = load_tree(str(src))
    base = src.parent

    leaves: list[str] = []

    def _resolve(raw_path: str) -> str:
        p = Path(raw_path)
        if p.is_absolute():
            return str(p.resolve())
        return str((base / p).resolve())

    def _walk(node) -> None:  # noqa: ANN001 — TreeNode
        if node.type == "leaf" and node.path:
            leaves.append(_resolve(node.path))
        elif node.type == "folder":
            for child in node.children:
                _walk(child)

    for child in tree.nodes:
        _walk(child)
    return leaves


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def run_catalog_on_click(catalog_path: str | Path, run_mode: str) -> None:
    """Top-level entry — pick the right launch path based on the
    catalog's extension and the cell's configured run mode.

    Parameters
    ----------
    catalog_path:
        Resolved path to a ``.scriptree`` or ``.scriptreetree``.
    run_mode:
        ``"sequential"`` or ``"parallel"`` — only meaningful for
        ``.scriptreetree`` catalogs.  Single tools always launch
        in a single V1 standalone with ``-run``.
    """
    p = Path(catalog_path)
    ext = p.suffix.lower()

    if ext == ".scriptree":
        _log(f"single-tool launch: {p.name}")
        launch_tool(p, run_on_open=True)
        return

    if ext == ".scriptreetree":
        try:
            leaves = collect_leaf_tool_paths(p)
        except Exception as exc:  # noqa: BLE001
            _log(f"tree walk failed for {p.name}: {exc!r}")
            return
        if not leaves:
            _log(f"tree {p.name} has no leaves; nothing to run")
            return
        if run_mode == "parallel":
            _run_parallel(leaves)
        else:
            _run_sequential(leaves)
        return

    _log(f"unknown catalog extension {ext!r} for {p}")


# ---------------------------------------------------------------------------
# Parallel mode
# ---------------------------------------------------------------------------

def _run_parallel(leaf_paths: Iterable[str]) -> None:
    """Spawn every leaf's V1 standalone immediately.

    Each leaf gets its own V1 standalone window with ``-run``.
    The user ends up with N independent windows, all firing
    concurrently.
    """
    paths = list(leaf_paths)
    _log(f"parallel: spawning {len(paths)} leaf(s)")
    for p in paths:
        try:
            launch_tool(p, run_on_open=True)
        except Exception as exc:  # noqa: BLE001
            _log(f"parallel spawn for {p!r} failed: {exc!r}")


# ---------------------------------------------------------------------------
# Sequential mode
# ---------------------------------------------------------------------------

# Module-level registry of in-flight sequential runs.  Keyed by a
# fresh UUID per invocation so concurrent runs (e.g. two cells in
# click-to-run mode triggered in quick succession) don't collide.
#
# The QTimer's ``singleShot`` fires every poll_ms and consults
# this dict to decide what to do next.
_inflight_runs: dict[str, dict] = {}


def _run_sequential(leaf_paths: Iterable[str]) -> None:
    """Spawn leaves one at a time; each waits for the previous to exit.

    Implementation note: V1's standalone window is itself a
    subprocess of the cell shell.  "Exit" means the user closed
    the V1 window (or it crashed).  We DO NOT track the underlying
    tool's process — that's owned by V1.  This keeps the
    sequencer simple and matches the user's intuition: each
    leaf's full lifecycle (form open → Run → output → close
    window) plays out before the next opens.
    """
    paths = [str(p) for p in leaf_paths]
    if not paths:
        return
    run_id = str(uuid.uuid4())
    _inflight_runs[run_id] = {
        "queue": paths,
        "current_proc": None,
        "started_at": time.monotonic(),
    }
    _log(f"sequential[{run_id[:8]}]: queued {len(paths)} leaf(s)")
    _advance_sequential(run_id)


def _spawn_v1_standalone(leaf_path: str) -> subprocess.Popen | None:
    """Spawn V1 standalone for ``leaf_path`` and return the Popen
    handle so the sequencer can poll for exit.

    Mirrors ``v1_launcher.launch_tool(..., run_on_open=True)`` but
    keeps the Popen handle alive.  Errors return ``None`` and the
    sequencer skips to the next leaf.
    """
    cmd = _v1_launcher_cmd() + [
        str(leaf_path), "-standalone", "-run",
    ]
    kwargs: dict = {"shell": False}
    if sys.platform == "win32":
        # CREATE_NO_WINDOW + CREATE_NEW_PROCESS_GROUP — same as
        # v1_launcher._spawn.
        kwargs["creationflags"] = 0x08000000 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, **kwargs)
        _log(f"sequential: spawned pid={proc.pid} for {Path(leaf_path).name}")
        return proc
    except Exception as exc:  # noqa: BLE001
        _log(f"sequential spawn failed for {leaf_path!r}: {exc!r}")
        return None


def _advance_sequential(run_id: str) -> None:
    """Pop the next leaf off the queue and spawn it.

    If the queue is empty, clean up.  Otherwise install a
    ``QTimer.singleShot`` that re-checks the just-spawned proc
    for exit and recurses.
    """
    state = _inflight_runs.get(run_id)
    if state is None:
        return
    queue: list[str] = state["queue"]
    if not queue:
        _log(
            f"sequential[{run_id[:8]}]: queue empty; "
            f"completed in {time.monotonic() - state['started_at']:.1f}s"
        )
        _inflight_runs.pop(run_id, None)
        return

    next_leaf = queue.pop(0)
    proc = _spawn_v1_standalone(next_leaf)
    state["current_proc"] = proc
    if proc is None:
        # Spawn failed — try the next leaf immediately.
        _advance_sequential(run_id)
        return

    _schedule_poll(run_id)


def _schedule_poll(run_id: str, poll_ms: int = 500) -> None:
    """Re-check the in-flight Popen handle every ``poll_ms`` ms.

    QTimer.singleShot from PySide6 — runs on the Qt event loop.
    Importable lazily so this module loads cleanly in non-GUI
    test contexts where ``run_catalog_on_click`` won't be invoked.
    """
    try:
        from PySide6.QtCore import QTimer
    except ImportError:
        # No Qt — fall back to a synchronous wait so tests can
        # still exercise the sequencer when they spawn dummy
        # processes that exit fast.  Not used in production.
        state = _inflight_runs.get(run_id)
        if state is None:
            return
        proc = state["current_proc"]
        if proc is not None:
            proc.wait()
        _advance_sequential(run_id)
        return

    QTimer.singleShot(poll_ms, lambda: _poll_sequential(run_id))


def _poll_sequential(run_id: str) -> None:
    """Check whether the current proc has exited; advance if so."""
    state = _inflight_runs.get(run_id)
    if state is None:
        return
    proc: subprocess.Popen | None = state["current_proc"]
    if proc is None:
        # Defensive — spawn was nilled mid-flight.  Skip to next.
        _advance_sequential(run_id)
        return
    if proc.poll() is None:
        # Still running — re-check in another tick.
        _schedule_poll(run_id)
        return
    # Exited.  Advance to the next leaf.
    _log(
        f"sequential[{run_id[:8]}]: pid={proc.pid} exited with "
        f"code {proc.returncode}; advancing"
    )
    state["current_proc"] = None
    _advance_sequential(run_id)


# ---------------------------------------------------------------------------
# Test helpers — exposed so unit tests can drive the sequencer
# without needing a real Qt event loop or V1 install.
# ---------------------------------------------------------------------------

def _inflight_count() -> int:
    """Return the number of in-flight sequential runs.  Test only."""
    return len(_inflight_runs)


def _reset_inflight() -> None:
    """Clear the in-flight run registry.  Test only."""
    _inflight_runs.clear()
