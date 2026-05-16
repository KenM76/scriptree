"""
v1_launcher.py — subprocess shellouts from the cell shell into the V1 editor.

## For humans

The cell/ring shell does NOT import the V1 ``ToolRunnerView`` /
``MainWindow`` / ``StandaloneWindow`` directly.  Instead, it spawns
``run_scriptree.bat`` as a separate process whenever the user picks
a tool from a cell menu or double-clicks a cell to open the full
editor.  Two reasons:

1. Process isolation — V1 is a separate executable that ships with
   its own state (settings, configurations, recent files).  Running
   it as a subprocess matches the user's mental model (the cell shell
   is a launcher, V1 is the editor) and protects each tool run from
   cell-shell crashes (and vice versa).

2. Drop-in V1 — V1 is "frozen" and its CLI is the public contract.
   Anything reachable via ``run_scriptree.bat <args>`` from a desktop
   shortcut is reachable from a cell.  No V1 internals leak into the
   shell.

The shell ALSO exposes three polyfill names that the V2 hexagon code
used to call (`show_tree_for`, `show_main_window_for`,
`show_composite_for`).  In V2 those routed into V2's `apps.menu.main`
which we discarded; here they all redirect to the appropriate
subprocess call (single-tool standalone, full editor, or full editor
with the cell's loaded catalog).

## For maintainers / LLMs

* This module MUST NOT import the V1 editor (ToolRunnerView /
  MainWindow / StandaloneWindow) — the whole point is process
  isolation.  It only builds an argv list and ``subprocess.Popen``s
  it.  Keep imports to stdlib + pathlib.
* ``_spawn`` always uses ``shell=False`` with a **list** argv — never
  ``shell=True``, never a joined string.  This is the injection-safe
  contract: paths with spaces/quotes/``&`` are passed as discrete
  argv elements, not re-parsed by a shell.  Do not "simplify" to a
  string command.
* Fire-and-forget: ``Popen`` is created and never ``wait()``ed/polled;
  the child is decoupled (Windows: ``CREATE_NO_WINDOW |
  CREATE_NEW_PROCESS_GROUP = 0x08000000 | 0x00000200``; POSIX:
  ``start_new_session=True``).  The ``proc`` handle is intentionally
  dropped — do not add reaping logic, the child outlives us.
* ``_v1_launcher_cmd`` / ``_ring_launcher_cmd`` invoke
  ``sys.executable`` + the ``.py`` script directly, NOT the
  ``.bat``/``.sh`` shim.  Rationale: ``DETACHED_PROCESS`` + ``.bat``
  is broken on Windows (cmd.exe with no console → silent failure) and
  ``sys.executable`` is already the correct (windowed pythonw on
  Windows) interpreter with the right vendored libs.  The
  ``.bat``/``.sh`` path is only an extreme fallback when
  ``sys.executable`` is empty.
* ``_project_root`` walks up max 10 levels looking for the launcher
  script; if not found it FALLS BACK to ``parent.parent.parent`` (an
  assumption about layout) rather than raising — a moved package
  could silently target the wrong root.  ``_v1_launcher_cmd`` then
  raises ``FileNotFoundError`` if the script truly isn't there.
* V1 CLI contract: ``launch_tool`` passes ``-standalone`` (critical —
  without it V1 opens the full editor); ``-configuration`` implies
  standalone but both are sent for unambiguous logs; ``run_on_open``
  appends ``-run``.  Treat these flags as the frozen public API.
* The three V2 polyfills (``show_tree_for`` /
  ``show_main_window_for`` / ``show_composite_for``) preserve the old
  ``apps.menu.main`` import names so call sites in cell_window need no
  rewrite — keep the names and signatures stable.
  ``show_composite_for`` on a master delegates to
  ``merged_tree.build_merged_tree_for_master`` (lazy import to avoid a
  circular dependency); a build failure degrades to a blank editor,
  not an exception.
* ``_spawn`` re-raises on ``Popen`` failure (after logging) — this is
  the ONE place callers can see an exception; ``launch_tool`` etc. do
  not catch it, the menu/closure layer does.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Path discovery
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    """Walk up from this file until we find ``run_scriptree.bat`` (Windows)
    or ``run_scriptree.sh`` (other).  That folder is the V3 install root.
    """
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / "run_scriptree.bat").is_file() or \
           (current / "run_scriptree.sh").is_file():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    # Fallback: assume <pkg>/shell/v1_launcher.py → up two = install root
    return Path(__file__).resolve().parent.parent.parent


def _v1_launcher_cmd() -> list[str]:
    """Return the argv prefix used to launch V1.

    Both platforms: invoke ``run_scriptree.py`` directly via the
    interpreter the cell shell is currently running.  This bypasses
    the ``.bat`` / ``.sh`` shim and avoids two real bugs:

    1. **DETACHED_PROCESS + .bat is broken on Windows.**  Spawning a
       ``.bat`` with ``DETACHED_PROCESS`` means cmd.exe runs without
       any console attached.  Inside the .bat the line ``start ""
       pythonw.exe ...`` then fails silently — what the user sees is
       a console flashing and disappearing with no editor window
       appearing.  Calling Python directly skips cmd.exe entirely.

    2. **The cell shell already knows where Python lives.**  We're
       running inside the same Python the cell shell launched with;
       ``sys.executable`` is the windowed (``pythonw.exe``) variant
       on Windows when launched via ``start "" pythonw.exe …``.
       Reusing it guarantees the same interpreter, the same vendored
       ``lib/pypi``, and (importantly) no console flash for the
       editor window.
    """
    root = _project_root()
    script = root / "run_scriptree.py"
    if not script.is_file():
        raise FileNotFoundError(
            f"Cannot locate run_scriptree.py in {root}"
        )
    py = sys.executable
    if not py:
        # Extreme fallback — no interpreter detected.  Try the .bat /
        # .sh as a last resort so the user at least sees the missing-
        # Python diagnostic from the launcher.
        if sys.platform == "win32":
            bat = root / "run_scriptree.bat"
            if bat.is_file():
                return [str(bat)]
        else:
            sh = root / "run_scriptree.sh"
            if sh.is_file():
                return ["bash", str(sh)]
        raise FileNotFoundError(
            f"sys.executable is empty and no fallback launcher "
            f"available in {root}"
        )
    return [py, str(script)]


# ---------------------------------------------------------------------------
# Public launchers — primary API
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    """Print a diagnostic line to stderr (visible in the cell shell's
    console / log file).  Tagged with [v1_launcher] so a `tail` filter
    can isolate launcher activity from the rest of the shell."""
    print(f"[v1_launcher] {msg}", file=sys.stderr, flush=True)


def launch_tool(
    scriptree_path: str | Path,
    configuration: str | None = None,
    *,
    run_on_open: bool = False,
) -> None:
    """Spawn V1 with a single ``.scriptree`` file in **standalone mode**.

    Used when a user clicks a tool inside a cell's menu.  V1's CLI:

        python run_scriptree.py <tool.scriptree> -standalone
            [-configuration <name>] [-run]

    The ``-standalone`` flag is critical — without it V1 opens its
    full editor (MainWindow) instead of the lightweight standalone
    runner that the cell-shell contract promises.  ``-configuration``
    implies ``-standalone`` already, but we pass both explicitly so
    the intent is unambiguous in launch logs.

    ``run_on_open`` (V3 v0.3.5+) — when True, append ``-run`` so V1
    auto-clicks the Run button after the standalone window opens.
    Used by the cell shell when a cell is configured for click-to-run
    (catalog ``cell.click_action == "run"``).

    Fire-and-forget — we do not wait for V1 to exit.
    """
    p = Path(scriptree_path)
    cmd = _v1_launcher_cmd() + [str(p), "-standalone"]
    if configuration:
        cmd.extend(["-configuration", configuration])
    if run_on_open:
        cmd.append("-run")
    _log(
        f"launch_tool: leaf={p.name!r}  exists={p.is_file()}  "
        f"configuration={configuration!r}  standalone=True  "
        f"run_on_open={run_on_open}"
    )
    if not p.is_file():
        _log(
            f"  WARNING: leaf path does not exist on disk; V1 will "
            f"likely show its missing-executable recovery dialog."
        )
    _spawn(cmd)


def launch_editor_with_tree(scriptreetree_path: str | Path) -> None:
    """Spawn V1 with a ``.scriptreetree`` file loaded in the full editor.

    Used on double-left-click of a cell, and on double-right-click for
    the master cell's "open composite editor" gesture.  V1's existing
    CLI accepts the path positionally; the launcher routes to the main
    window with the tree loaded into the launcher dock.
    """
    p = Path(scriptreetree_path)
    cmd = _v1_launcher_cmd() + [str(p)]
    _log(
        f"launch_editor_with_tree: tree={p.name!r}  exists={p.is_file()}"
    )
    _spawn(cmd)


def launch_editor_blank() -> None:
    """Spawn V1 with no file loaded.

    Used when the user double-clicks an unbound cell (no catalog
    selected yet).  V1 opens its blank-launcher state.
    """
    cmd = _v1_launcher_cmd()
    _log("launch_editor_blank")
    _spawn(cmd)


def _ring_launcher_cmd() -> list[str]:
    """Return the argv prefix used to launch ScripTreeRing (the cell shell).

    Mirrors ``_v1_launcher_cmd`` but targets ``run_scriptreering.py``
    instead.  Used by the V1 editor's "Open in cell" / "Open in ring"
    File menu actions to hand a catalog or ring file off to the cell
    shell as a separate process.
    """
    root = _project_root()
    script = root / "run_scriptreering.py"
    if not script.is_file():
        raise FileNotFoundError(
            f"Cannot locate run_scriptreering.py in {root}"
        )
    py = sys.executable
    if not py:
        if sys.platform == "win32":
            bat = root / "run_scriptreering.bat"
            if bat.is_file():
                return [str(bat)]
        else:
            sh = root / "run_scriptreering.sh"
            if sh.is_file():
                return ["bash", str(sh)]
        raise FileNotFoundError(
            f"sys.executable is empty and no fallback launcher "
            f"available in {root}"
        )
    return [py, str(script)]


def launch_ring_shell(*paths: str | Path) -> None:
    """Spawn ScripTreeRing with one or more positional file paths.

    Each ``path`` is forwarded to the ring shell.  Behaviour follows
    ScripTreeRing's existing argv parser:

    * ``.scriptree`` / ``.scriptreetree``  →  spawns one cell bound to
      that catalog.
    * ``.scriptreering``                    →  loads the ring file as a
      master + N members.

    When the ring shell is already running (single-instance handoff),
    these paths are forwarded to the primary instance and absorbed
    into its existing ``SnapEngine`` so cells spawn alongside whatever
    is already on screen.
    """
    norm = [str(Path(p)) for p in paths]
    cmd = _ring_launcher_cmd() + norm
    _log(f"launch_ring_shell: {[Path(p).name for p in norm]}")
    _spawn(cmd)


# ---------------------------------------------------------------------------
# V2-menu-engine polyfill — drop-in replacement for `apps.menu.main`
# ---------------------------------------------------------------------------
#
# These three names were imported by V2's cell_window.py from
# `apps.menu.main`.  Rather than rewrite every call site, we expose
# the same names here.  Each routes to the appropriate V1 launcher.
# Because they take a CellWindow instance, they can read the cell's
# `_catalog_path` and dispatch correctly.

def show_tree_for(hex_win, mode: str = "standalone") -> None:  # noqa: ANN001
    """V2 polyfill — show the cell's tree menu.

    Two modes:

    * ``"standalone"`` (single-left-click) — show a lightweight
      in-process popup menu of the cell's catalog right next to the
      hexagon.  Click a leaf → V1 standalone runner subprocess.
    * ``"lock-open"`` (double-left-click) — spawn V1's full editor with
      the cell's catalog loaded.  Heavier but full-featured (tool
      editing, configurations, parser, etc.).
    """
    if mode == "standalone":
        # Lazy import — tree_popup pulls in QMenu, only used when the
        # cell shell is actually rendering a popup.
        try:
            from scriptree.shell.tree_popup import show_tree_popup_for
            show_tree_popup_for(hex_win)
            return
        except Exception as exc:  # noqa: BLE001
            print(
                f"[v1_launcher] tree_popup failed: {exc!r}; falling back "
                f"to full editor",
                file=sys.stderr,
            )
            # Fall through to lock-open path.
    # lock-open / fallback / unknown mode → full editor.
    catalog = getattr(hex_win, "_catalog_path", None)
    if catalog is None:
        launch_editor_blank()
        return
    p = Path(catalog)
    if p.suffix.lower() == ".scriptreetree":
        launch_editor_with_tree(p)
    elif p.suffix.lower() == ".scriptree":
        launch_tool(p)
    else:
        launch_editor_blank()


def show_main_window_for(hex_win) -> None:  # noqa: ANN001
    """V2 polyfill — open the V1 main editor window for this cell.

    Used by the double-right-click handler.  Always lock-open so it
    spawns the full editor (not the lightweight popup).
    """
    show_tree_for(hex_win, mode="lock-open")


def show_composite_for(hex_win) -> None:  # noqa: ANN001
    """V2 polyfill — open the master's "composite" editor.

    For master cells: spawn the V1 editor on a merged temp
    ``.scriptreetree`` (built lazily from member catalogs).  For
    standalone cells: same as ``show_tree_for``.
    """
    role = getattr(hex_win, "role", "standalone")
    if role == "master":
        # Master path needs merged_tree.build_merged_tree(...).  Lazy
        # import avoids a circular dependency at module-load time.
        try:
            from scriptree.shell.merged_tree import build_merged_tree_for_master
            tree_path = build_merged_tree_for_master(hex_win)
        except Exception as exc:  # noqa: BLE001
            print(
                f"[v1_launcher] master merged-tree build failed: {exc!r}; "
                f"falling back to blank editor",
                file=sys.stderr,
            )
            launch_editor_blank()
            return
        launch_editor_with_tree(tree_path)
    else:
        show_tree_for(hex_win, mode="lock-open")


# ---------------------------------------------------------------------------
# Spawn helper
# ---------------------------------------------------------------------------

def _spawn(cmd: list[str]) -> None:
    """Fire-and-forget Popen.  No shell, no wait, hidden console.

    On Windows we use ``CREATE_NO_WINDOW`` (0x08000000) instead of the
    older ``DETACHED_PROCESS``.  Why:

    * ``DETACHED_PROCESS`` strips the console entirely — that breaks
      ``.bat`` shims because cmd.exe needs a console to run.  (We've
      already moved away from .bat to ``sys.executable + .py`` in
      ``_v1_launcher_cmd``, so this is belt-and-braces, but
      ``CREATE_NO_WINDOW`` is the right flag for "GUI launching a
      GUI" anyway.)
    * ``CREATE_NEW_PROCESS_GROUP`` keeps the spawned editor immune to
      Ctrl-C in the cell shell's parent console.

    On other platforms we use ``start_new_session`` for the same
    decoupling.
    """
    kwargs: dict = {"shell": False}
    if sys.platform == "win32":
        # CREATE_NO_WINDOW = 0x08000000 — no console window flashes.
        # CREATE_NEW_PROCESS_GROUP = 0x00000200 — independent CTRL group.
        kwargs["creationflags"] = 0x08000000 | 0x00000200
    else:
        kwargs["start_new_session"] = True

    _log(f"  Popen: {cmd!r}")
    try:
        proc = subprocess.Popen(cmd, **kwargs)
        _log(f"  spawned pid={proc.pid}")
    except Exception as exc:  # noqa: BLE001
        _log(f"  Popen FAILED: {exc!r}")
        raise
