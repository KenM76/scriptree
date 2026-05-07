"""
v1_launcher.py — subprocess shellouts from the cell shell into the V1 editor.

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

    Windows: ``["<root>/run_scriptree.bat"]`` (cmd dispatches it).
    Other:   ``["bash", "<root>/run_scriptree.sh"]``.
    """
    root = _project_root()
    if sys.platform == "win32":
        bat = root / "run_scriptree.bat"
        if bat.is_file():
            return [str(bat)]
        # Last-resort: invoke the python entry point directly so the cell
        # still works in a dev tree without the .bat present.
        py = sys.executable
        script = root / "run_scriptree.py"
        if script.is_file():
            return [py, str(script)]
        raise FileNotFoundError(
            f"Cannot locate run_scriptree.bat or run_scriptree.py in {root}"
        )
    sh = root / "run_scriptree.sh"
    if sh.is_file():
        return ["bash", str(sh)]
    raise FileNotFoundError(
        f"Cannot locate run_scriptree.sh in {root}"
    )


# ---------------------------------------------------------------------------
# Public launchers — primary API
# ---------------------------------------------------------------------------

def launch_tool(scriptree_path: str | Path, configuration: str | None = None) -> None:
    """Spawn V1 with a single ``.scriptree`` file in standalone mode.

    Used when a user clicks a tool inside a cell's menu.  V1's existing
    CLI accepts ``run_scriptree.bat path/to/tool.scriptree
    [-configuration <name>]`` and opens the standalone runner.
    Fire-and-forget — we do not wait for V1 to exit.
    """
    cmd = _v1_launcher_cmd() + [str(scriptree_path)]
    if configuration:
        cmd.extend(["-configuration", configuration])
    _spawn(cmd)


def launch_editor_with_tree(scriptreetree_path: str | Path) -> None:
    """Spawn V1 with a ``.scriptreetree`` file loaded in the full editor.

    Used on double-left-click of a cell, and on double-right-click for
    the master cell's "open composite editor" gesture.  V1's existing
    CLI accepts the path positionally; the launcher routes to the main
    window with the tree loaded into the launcher dock.
    """
    cmd = _v1_launcher_cmd() + [str(scriptreetree_path)]
    _spawn(cmd)


def launch_editor_blank() -> None:
    """Spawn V1 with no file loaded.

    Used when the user double-clicks an unbound cell (no catalog
    selected yet).  V1 opens its blank-launcher state.
    """
    cmd = _v1_launcher_cmd()
    _spawn(cmd)


# ---------------------------------------------------------------------------
# V2-menu-engine polyfill — drop-in replacement for `apps.menu.main`
# ---------------------------------------------------------------------------
#
# These three names were imported by V2's hexagon_window.py from
# `apps.menu.main`.  Rather than rewrite every call site, we expose
# the same names here.  Each routes to the appropriate V1 launcher.
# Because they take a HexagonWindow instance, they can read the cell's
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
    """Fire-and-forget Popen.  No shell, no wait, fully detached.

    On Windows we use CREATE_NEW_PROCESS_GROUP so a Ctrl-C in the cell
    shell's parent console doesn't propagate to the spawned editor.
    On other platforms we use start_new_session for the equivalent
    effect.
    """
    kwargs: dict = {"shell": False}
    if sys.platform == "win32":
        # DETACHED_PROCESS = 0x00000008 — child has no console at all.
        # CREATE_NEW_PROCESS_GROUP = 0x00000200 — independent CTRL group.
        kwargs["creationflags"] = 0x00000008 | 0x00000200
        # Inherit stdin/out/err = None so the child opens its own.
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(cmd, **kwargs)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[v1_launcher] Popen failed for {cmd!r}: {exc!r}",
            file=sys.stderr,
        )
        raise
