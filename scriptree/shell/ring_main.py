"""
ring_main.py — ScripTreeRing entry point.

## For humans

Launch:
    py -3.11 -m scriptree.shell.ring_main

Or import and call:
    from scriptree.shell.ring_main import main; main()

Subsystems wired here
---------------------
- CellRegistry: singleton, owns all live CellWindow instances.
- SnapEngine: 60 Hz timer, snap detection, preview and commit signals.
- MasterHexagon spawn: triggered by SnapEngine.snapCommit(mode='edge').
- Undock detection: triggered by SnapEngine.snapPreview / hexagonMoved.

## For maintainers / LLMs

* When launched via ``py -m scriptree.shell.ring_main`` this module is
  registered as ``__main__``, NOT ``scriptree.shell.ring_main``.  A
  second import of the dotted name gets a DIFFERENT module object whose
  ``_SNAP_ENGINE`` is still None.  ``_get_snap_engine`` works around
  this by checking ``sys.modules["__main__"]`` first — preserve that
  lookup order; never assume ``_SNAP_ENGINE`` is the same object across
  importers.
* ``app.setQuitOnLastWindowClosed(False)`` is load-bearing: cells are
  ``Qt.Tool`` windows excluded from Qt's last-window count, so a
  dismissed tool dialog would otherwise call ``QApplication.quit()``
  and nuke the whole shell.  Do not remove or re-enable this.
* CLI flag order matters: ``_handle_early_flags`` runs BEFORE the
  QApplication and may ``return 0`` (autostart register/unregister).
  Single-instance handoff runs next and may also exit (handed off to a
  running primary).  Only past both gates does this process become the
  primary.
* ``--load-ring``, positional ``*.scriptreering``, ``--autoload-rings``
  and ``SCRIPTREE2_INITIAL_HEXAGONS`` are ADDITIVE, not mutually
  exclusive.  ``_ring_loaded_any`` only suppresses the *default*
  single-hex spawn; forest mode also sets it.  Don't make these
  exclusive without revisiting the default-spawn guard.
* ``_maybe_start_harness`` is a SECURITY-sensitive two-gate check: env
  var (``SCRIPTREE2_TEST_HARNESS == "1"``) is tested before the
  package import, and ALL failure modes are silent — no log line may
  reveal harness presence.  Do not add diagnostics to the failure
  paths.
* Every spawned cell must be wired to the SnapEngine via
  ``_wire_hex_to_snap`` / a ``snapPreview.connect`` lambda binding
  ``h=hexagon`` as a default arg (late-binding trap otherwise).
  ``load_ring`` does its own member wiring; ``_handle_primary_message``
  must call ``_wire_hex_to_snap`` for cells it spawns.
* ``_on_hexagon_moved`` suppresses the undock check while
  ``_GROUP_MOVE_IN_PROGRESS`` is truthy (coordinated group drag → no
  relative motion → undock impossible).  Its rate-limited log uses a
  function attribute ``_last_log``; that mutable-default-on-function
  pattern is intentional, not a bug.
* The primary single-instance server is only set up when
  ``--new-process`` is absent; its ``messageReceived`` handler
  (``_handle_primary_message``) runs in THIS process's event loop so
  spawned cells share one CellRegistry/SnapEngine and can dock.
"""

from __future__ import annotations

import os
import sys
import math

from PySide6.QtWidgets import QApplication

from scriptree.shell.branding_loader import load_branding
from scriptree.shell.cell_window import (
    CellWindow,
    _try_spawn_master,
    _check_undock,
    _GROUP_MOVE_IN_PROGRESS,
)
from scriptree.shell.cell_registry import CellRegistry
from scriptree.shell.snap_engine import SnapEngine


# ---------------------------------------------------------------------------
# Early CLI flag handling (non-Qt, no QApplication required)
# ---------------------------------------------------------------------------

def _handle_early_flags(argv: list[str]) -> bool:
    """Handle flags that require no QApplication and exit immediately.

    Returns True if the process should exit after this function returns.

    Handled flags:
        --register-autostart-user <ring-path>
            Add ring to user autoload config and register user Run-key entry.
        --register-autostart-system <ring-path>
            Add ring to system autoload config and register HKLM Run-key entry.
            Requires admin (the caller already elevated via ShellExecuteW).
        --unregister-autostart <scope>
            Remove the Run-key entry and (optionally) empty the autoload config.
    """
    if "--register-autostart-user" in argv:
        idx = argv.index("--register-autostart-user")
        if idx + 1 >= len(argv):
            print("[shell.main] --register-autostart-user requires a path", file=sys.stderr)
            return True
        ring_path = argv[idx + 1]
        try:
            from pathlib import Path
            from scriptree.shell.ring_io import add_autoload_ring
            add_autoload_ring(Path(ring_path), "user")
            print(f"[shell.main] Registered user autoload for {ring_path}", file=sys.stderr)
        except Exception as exc:
            print(f"[shell.main] --register-autostart-user failed: {exc!r}", file=sys.stderr)
        return True

    if "--register-autostart-system" in argv:
        idx = argv.index("--register-autostart-system")
        if idx + 1 >= len(argv):
            print("[shell.main] --register-autostart-system requires a path", file=sys.stderr)
            return True
        ring_path = argv[idx + 1]
        try:
            from pathlib import Path
            from scriptree.shell.ring_io import add_autoload_ring
            add_autoload_ring(Path(ring_path), "system")
            print(f"[shell.main] Registered system autoload for {ring_path}", file=sys.stderr)
        except Exception as exc:
            print(f"[shell.main] --register-autostart-system failed: {exc!r}", file=sys.stderr)
        return True

    if "--unregister-autostart" in argv:
        idx = argv.index("--unregister-autostart")
        scope = argv[idx + 1] if idx + 1 < len(argv) else "user"
        if scope not in ("user", "system"):
            print(f"[shell.main] --unregister-autostart: invalid scope {scope!r}", file=sys.stderr)
            return True
        try:
            from scriptree.shell.ring_io import unregister_autostart
            unregister_autostart(scope)  # type: ignore[arg-type]
            print(f"[shell.main] Unregistered autostart scope={scope}", file=sys.stderr)
        except Exception as exc:
            print(f"[shell.main] --unregister-autostart failed: {exc!r}", file=sys.stderr)
        return True

    return False


def _log(msg: str) -> None:
    print(f"[shell.main] {msg}", file=sys.stderr)


def _parse_initial_specs(env_value: str | None) -> list[dict]:
    """Parse SCRIPTREE2_INITIAL_HEXAGONS env var into a list of spawn specs.

    Format: JSON list of dicts, each with optional keys:
      - x, y    : int (logical px screen coords; defaults 100, 100)
      - shape   : "hexagon" | "square" (defaults to branding default)
      - orientation : "flat-top" | "pointy-top" (defaults to branding default)

    Example::

        SCRIPTREE2_INITIAL_HEXAGONS='[{"x":200,"y":200},{"x":400,"y":200,"orientation":"pointy-top"},{"x":600,"y":200,"shape":"square"}]'

    Returns an empty list if env is unset / empty / malformed (the caller
    falls back to single-hex default behaviour).
    """
    if not env_value:
        return []
    import json
    try:
        parsed = json.loads(env_value)
    except json.JSONDecodeError as e:
        _log(f"SCRIPTREE2_INITIAL_HEXAGONS parse error: {e}; falling back to single-hex")
        return []
    if not isinstance(parsed, list):
        _log(f"SCRIPTREE2_INITIAL_HEXAGONS must be a JSON list; got {type(parsed).__name__}")
        return []
    out = []
    for item in parsed:
        if isinstance(item, dict):
            out.append(item)
        else:
            _log(f"SCRIPTREE2_INITIAL_HEXAGONS entry not a dict; skipping: {item!r}")
    return out


# ---------------------------------------------------------------------------
# Test-harness two-gate check (ADR-002)
# ---------------------------------------------------------------------------

def _maybe_start_harness(app: QApplication) -> None:
    """Two-gate check for the GUI test harness.  Silently no-ops on any failure.

    SECURITY: do NOT log the gate state.  A log line saying
    "harness disabled" is a side channel that tells an attacker the harness
    could be enabled.  The consumer build's correct behaviour is to make the
    harness invisible — not just inactive.  Identical observable behaviour in
    all three failure modes:
      (a) package not installed (consumer build),
      (b) env var unset / != "1" (dev install, no harness opt-in),
      (c) both missing.

    The ONLY log emission is on success of both gates (see server.py).
    """
    # Gate 2: env-var check comes FIRST — it is a cheap os.environ read and
    # avoids even attempting the import on the common case where the env var
    # is unset.  Order per ADR-002 code-path sketch (diagram shows env-var
    # checked before import attempt).
    if os.environ.get("SCRIPTREE2_TEST_HARNESS") != "1":
        return  # Silent — env-var gate not set.

    try:
        # Gate 1: package importable?  In a consumer build this raises
        # ImportError because the package is not installed.
        import scriptree2_test_harness  # noqa: F401
    except ImportError:
        return  # Silent — package gate not satisfied.

    # Both gates passed.  Hand off to the harness (it emits the loud log).
    try:
        scriptree2_test_harness.start_server(app)
    except Exception:
        return  # Silent — harness startup failure must not surface to user.


# ---------------------------------------------------------------------------
# Process-level SnapEngine reference
# We expose this via a module-level getter so CellWindow can reach it
# without importing main at module load time (which would be circular).
# ---------------------------------------------------------------------------

_SNAP_ENGINE: SnapEngine | None = None


def _get_snap_engine() -> SnapEngine | None:
    """Return the process-wide SnapEngine instance, or None if not yet created.

    CRITICAL: when launched via `py -m apps.shell.main`, Python registers this
    module as `__main__` rather than `apps.shell.main`.  Other modules that
    `from scriptree.shell.main import _get_snap_engine` end up with a SECOND module
    object whose `_SNAP_ENGINE` is None — so the caller sees None even after
    main() set it on `__main__`.

    Look up `__main__` first, then fall back to this module's binding.  Same
    pattern the harness uses in `test-harness/.../api/hexagon.py`.
    """
    main_mod = sys.modules.get("__main__")
    if main_mod is not None:
        engine = getattr(main_mod, "_SNAP_ENGINE", None)
        if engine is not None:
            return engine
    return _SNAP_ENGINE


def _wire_hex_to_snap(hex_win: CellWindow) -> None:
    """Connect a new CellWindow to the process-wide SnapEngine."""
    if _SNAP_ENGINE is None:
        return
    # The SnapEngine receives hexagonMoved via the registry signal (already wired
    # in SnapEngine.__init__).  The drag attach/detach is called from
    # CellWindow._start_drag / _end_drag.  No additional per-hex wiring needed.
    # Wire snapPreview â†’ show_snap_preview on this hex.
    _SNAP_ENGINE.snapPreview.connect(
        lambda src, tgt, mode, geom, h=hex_win: _on_snap_preview(src, tgt, mode, geom, h)
    )
    _log(f"Wired hex {hex_win._id[:8]} to SnapEngine")


def _on_snap_preview(
    source_id: str,
    target_id: str,
    mode: str,
    geom: dict,
    listening_hex: CellWindow,
) -> None:
    """Route snapPreview signals to the dragging hex's overlay."""
    if listening_hex._id != source_id:
        return
    listening_hex.show_snap_preview(
        geom["x"], geom["y"], geom["w"], geom["h"],
        mode=mode,
    )


def _on_snap_commit(
    source_id: str,
    target_id: str,
    mode: str,
    snap_geom: dict,
) -> None:
    """Handle a committed snap.

    - Hide the source hex's preview overlay.
    - If mode == 'edge', spawn/re-show a master hexagon.
    """
    _log(
        f"_on_snap_commit src={source_id[:8]} tgt={target_id[:8]} "
        f"mode={mode} geom={snap_geom}"
    )
    registry = CellRegistry.instance()
    src = registry.get(source_id)
    tgt = registry.get(target_id)

    if src is not None:
        src.hide_snap_preview()

    if mode == "edge" and src is not None and tgt is not None:
        _log(f"_on_snap_commit: calling _try_spawn_master src={source_id[:8]} tgt={target_id[:8]}")
        _try_spawn_master(src, tgt)
    elif mode != "edge":
        _log(f"_on_snap_commit: mode={mode!r} — no master spawn (edge mode only)")


def _on_hexagon_moved(hex_id: str) -> None:
    """Check if a moved hex has undocked from any partners.

    Bug 2: when the whole dock group is translating together, every member
    fires hexagonMoved.  Suppress the undock check during coordinated group
    moves — the relative positions haven't changed, so undock cannot have
    occurred.  We identify coordinated moves via _GROUP_MOVE_IN_PROGRESS:
    if ANY hex is listed there as the initiator, the move is part of a
    group drag.
    """
    group_in_progress = bool(_GROUP_MOVE_IN_PROGRESS)
    # Rate-limited log — _on_hexagon_moved fires every frame during a drag.
    import time as _time
    _now = _time.monotonic()
    if not hasattr(_on_hexagon_moved, '_last_log'):
        _on_hexagon_moved._last_log = 0.0  # type: ignore[attr-defined]
    if _now - _on_hexagon_moved._last_log >= 0.5:  # type: ignore[attr-defined]
        _log(f"_on_hexagon_moved id={hex_id[:8]} group_in_progress={group_in_progress}")
        _on_hexagon_moved._last_log = _now  # type: ignore[attr-defined]
    if group_in_progress:
        # A group move is in progress; relative positions are unchanged.
        # Do not trigger undock.
        return
    registry = CellRegistry.instance()
    hex_win = registry.get(hex_id)
    # Amendment 2: use _docked_to (positional cluster) rather than _dock_partners (shim).
    if hex_win is not None and hex_win._docked_to:
        _check_undock(hex_win)


def _handle_primary_message(msg: dict, branding: dict, registry) -> None:  # noqa: ANN001
    """Dispatch a single-instance hand-off message inside the primary.

    Schema (see ``scriptree.shell.single_instance``):

      * ``{"command": "spawn_cell"}`` — spawn a fresh standalone hex.
      * ``{"command": "load_catalog", "path": "..."}`` — spawn a hex
        bound to the given ``.scriptreetree`` / ``.scriptree`` catalog.
      * ``{"command": "load_ring", "path": "..."}`` — call
        ``load_ring`` from ``ring_io`` to materialise the saved layout.
    """
    from pathlib import Path

    cmd = msg.get("command")
    _log(f"_handle_primary_message: {msg!r}")

    if cmd == "spawn_cell":
        # Position the new cell off-screen-center, slightly offset
        # so it doesn't land on top of an existing one.
        n_existing = len(registry.hexagons())
        offset = 32 * n_existing
        hexagon = CellWindow(branding)
        hexagon.move(100 + offset, 100 + offset)
        _wire_hex_to_snap(hexagon)
        hexagon.show()
        _log(f"  spawn_cell → new hex {hexagon._id[:8]}")
        return

    if cmd == "load_catalog":
        path = msg.get("path")
        if not path:
            _log("  load_catalog: missing 'path'")
            return
        n_existing = len(registry.hexagons())
        offset = 32 * n_existing
        hexagon = CellWindow(branding, catalog_path=str(path))
        hexagon.move(100 + offset, 100 + offset)
        _wire_hex_to_snap(hexagon)
        hexagon.show()
        _log(f"  load_catalog → new hex {hexagon._id[:8]} bound to {path}")
        return

    if cmd == "load_ring":
        path = msg.get("path")
        if not path:
            _log("  load_ring: missing 'path'")
            return
        try:
            from scriptree.shell.ring_io import load_ring
            master = load_ring(
                Path(path), branding, registry, _SNAP_ENGINE
            )
            master._saved_ring_path = Path(path)
            _log(f"  load_ring → master {master._id[:8]} from {path}")
        except Exception as exc:  # noqa: BLE001
            _log(f"  load_ring failed for {path}: {exc!r}")
        return

    _log(f"  unknown command: {cmd!r}")


def main() -> int:
    """Create the QApplication, wire subsystems, show one CellWindow, run event loop."""
    global _SNAP_ENGINE

    # Handle early exit flags (no QApplication needed).
    if _handle_early_flags(sys.argv):
        return 0

    branding = load_branding()

    app = QApplication.instance() or QApplication(sys.argv)

    # ---- Single-instance handoff ---------------------------------------
    #
    # Default behaviour: if another ScripTreeRing process is already
    # running for this user, hand our argv off to it (one cell-spawn
    # request per positional argument, or a single "spawn_cell" if
    # no positional args).  That existing process spawns the new
    # cell(s) in its own CellRegistry, so they can dock with the
    # already-visible cells.
    #
    # Opt out with the ``--new-process`` flag — useful for diagnostics
    # or when you intentionally want isolated processes (e.g. testing
    # autoload without disturbing your live cells).
    if "--new-process" not in sys.argv:
        try:
            from scriptree.shell.single_instance import (
                try_handoff,
                messages_from_argv,
            )
            messages = messages_from_argv(sys.argv)
            if try_handoff(messages):
                _log(
                    f"handed off {len(messages)} message(s) to running "
                    f"primary; this process will exit"
                )
                return 0
            _log("no primary running; this process will become primary")
        except Exception as exc:  # noqa: BLE001
            _log(
                f"single-instance handoff errored: {exc!r}; "
                f"falling through to start a primary anyway"
            )

    # CRITICAL: never quit just because some QDialog was the last
    # visible non-tool window.  Hexagons are Qt.Tool (excluded from
    # Qt's "last window" count); when a tool's QMessageBox /
    # QFileDialog / OutputDialog dismisses, Qt's default
    # quitOnLastWindowClosed=True would invoke QApplication.quit() —
    # taking the entire shell with it and making every hex disappear.
    # The shell's lifecycle is owned by CellRegistry, not by Qt's
    # window-counting heuristic.  See lesson
    # `shell-engineer__qt-tool-vs-qmainwindow-quitonclose.md` for the
    # related WA_QuitOnClose pattern; this is the application-level
    # counterpart that catches transient dialogs the per-window
    # attribute can't reach.
    app.setQuitOnLastWindowClosed(False)

    # Brand the application so QStandardPaths resolves to branded dirs (ADR-001 Â§sub-decision-5).
    app_name = branding.get("appName", "ScripTree")
    app.setOrganizationName(app_name)
    app.setApplicationName(app_name)
    app.setApplicationVersion("0.0.1-demo")

    _log(f"Starting {branding.get('appNameLong', app_name)} — phase-1 demo")

    # ---- Test-harness (two-gate check — ADR-002) ------------------------
    # Must run after QApplication is constructed but before any CellWindow.
    _maybe_start_harness(app)

    # ---- CellRegistry ------------------------------------------------
    registry = CellRegistry.instance()

    # ---- SnapEngine -----------------------------------------------------
    hex_cfg = branding.get("hexagon", {})
    snap_dist = int(hex_cfg.get("snapDistancePx", 18))
    _SNAP_ENGINE = SnapEngine(registry, snap_distance_px=snap_dist)
    _log(f"SnapEngine created, snap_distance_px={snap_dist}")

    # Wire SnapEngine commit signal â†’ master spawn.
    _SNAP_ENGINE.snapCommit.connect(_on_snap_commit)

    # Wire registry hexagonMoved â†’ undock check.
    registry.hexagonMoved.connect(_on_hexagon_moved)

    # ---- Log master lifecycle events ------------------------------------
    registry.masterSpawned.connect(
        lambda mid, aid, bid: _log(f"masterSpawned: {mid} ({aid[:8]}+{bid[:8]})")
    )
    registry.masterDespawned.connect(
        lambda mid: _log(f"masterDespawned: {mid}")
    )

    # ---- Single-instance primary server ---------------------------------
    # Listen for handoff messages from secondary launches.  Each message
    # spawns a new sibling cell / loads a ring / loads a catalog into a
    # new cell, all in this process so they can dock with the live ones.
    _primary_server = None
    if "--new-process" not in sys.argv:
        try:
            from scriptree.shell.single_instance import PrimaryServer
            _primary_server = PrimaryServer(app)
            if _primary_server.listen():
                _primary_server.messageReceived.connect(
                    lambda msg: _handle_primary_message(
                        msg, branding, registry
                    )
                )
            else:
                _log(
                    "primary server listen() failed; subsequent "
                    "run_scriptreering invocations will be isolated"
                )
                _primary_server = None
        except Exception as exc:  # noqa: BLE001
            _log(f"primary server setup errored: {exc!r}")
            _primary_server = None

    # ---- Ring auto-load / explicit load (CLI flags) ---------------------
    # These run after registry + snap engine are wired so load_ring() can
    # register each spawned hex with both subsystems.
    #
    # --autoload-rings  : load all rings from user + system autoload configs.
    # --load-ring <path>: load exactly one ring from the given path.
    #
    # Both flags are additive — they do NOT suppress the SCRIPTREE2_INITIAL_HEXAGONS
    # env var or the default single-hex fallback.  If you want ONLY the rings,
    # set SCRIPTREE2_INITIAL_HEXAGONS=[] (empty list) alongside the flag.
    _ring_loaded_any = False

    if "--load-ring" in sys.argv:
        idx = sys.argv.index("--load-ring")
        if idx + 1 < len(sys.argv):
            ring_path_str = sys.argv[idx + 1]
            try:
                from pathlib import Path
                from scriptree.shell.ring_io import load_ring
                master = load_ring(Path(ring_path_str), branding, registry, _SNAP_ENGINE)
                master._saved_ring_path = Path(ring_path_str)
                _log(f"--load-ring: loaded {ring_path_str} → master {master._id[:8]}")
                _ring_loaded_any = True
            except Exception as exc:
                _log(f"--load-ring {ring_path_str!r}: failed: {exc!r}")
        else:
            _log("--load-ring: missing path argument")

    # Positional .scriptreering — Explorer-double-click case. Anything that
    # ends in .scriptreering (case-insensitive) gets loaded the same way as
    # --load-ring would, so file-association launches work without a flag.
    for _arg in sys.argv[1:]:
        if _arg.startswith("-"):
            continue
        if _arg.lower().endswith(".scriptreering"):
            try:
                from pathlib import Path
                from scriptree.shell.ring_io import load_ring
                master = load_ring(Path(_arg), branding, registry, _SNAP_ENGINE)
                master._saved_ring_path = Path(_arg)
                _log(f"positional ring: loaded {_arg} → master {master._id[:8]}")
                _ring_loaded_any = True
            except Exception as exc:
                _log(f"positional ring {_arg!r}: failed: {exc!r}")

    if "--autoload-rings" in sys.argv:
        try:
            from pathlib import Path
            from scriptree.shell.ring_io import load_ring, list_autoload_rings
            for scope in ("user", "system"):
                for ring_p in list_autoload_rings(scope):  # type: ignore[arg-type]
                    if not Path(ring_p).exists():
                        _log(
                            f"--autoload-rings: skipping missing ring "
                            f"{ring_p} (scope={scope})"
                        )
                        continue
                    try:
                        master = load_ring(Path(ring_p), branding, registry, _SNAP_ENGINE)
                        master._saved_ring_path = Path(ring_p)
                        _log(
                            f"--autoload-rings: loaded {ring_p} "
                            f"â†’ master {master._id[:8]} (scope={scope})"
                        )
                        _ring_loaded_any = True
                    except Exception as exc:
                        _log(f"--autoload-rings: failed to load {ring_p}: {exc!r}")
        except Exception as exc:
            _log(f"--autoload-rings: error reading autoload config: {exc!r}")

    # ---- Initial hexagons -----------------------------------------------
    # Default: spawn 1 hexagon.
    # Demo override: SCRIPTREE2_INITIAL_HEXAGONS env var = JSON list of
    #   {x, y, shape?, orientation?} dicts spawns one hex per entry.
    # This lets the Lead pre-populate the desktop with several hexes for
    # docking experiments without poking the harness.
    initial_specs = _parse_initial_specs(os.environ.get("SCRIPTREE2_INITIAL_HEXAGONS"))

    # ---- Forest mode (V3 v0.3.14+) --------------------------------------
    # When ``--forest`` is on argv (or SCRIPTREE_FOREST_MODE=1), we
    # construct a ForestController BEFORE the default-spawn section.
    # The forest is a singleton top-level container that owns all
    # rings + cells on screen; its first-run dialog handles the
    # "what to populate" question, so we want to skip the legacy
    # single-cell default spawn that would otherwise leave a stray
    # cell next to the forest.
    _forest_controller = None
    forest_mode = (
        "--forest" in sys.argv
        or os.environ.get("SCRIPTREE_FOREST_MODE", "").strip() == "1"
    )
    if forest_mode:
        try:
            from scriptree.shell.forest_controller import ForestController
            # v0.5.2 — rehome any pre-existing
            # ``last_forest.scriptreeforest`` to its v0.5.2 name
            # (``default.scriptreeforest``) before the controller
            # tries to load.  Idempotent: a no-op on first install
            # or when the rename has already happened.
            from scriptree.shell.forest_io import (
                migrate_legacy_autoload_path,
            )
            migrate_legacy_autoload_path(branding)
            _forest_controller = ForestController(branding, registry, _SNAP_ENGINE)
            _forest_controller.start()
            _log("Forest mode: ForestController started")
            # Forest mode owns the initial population — no default
            # single-hex spawn.  If the user wants a blank cell the
            # forest's right-click menu has Add → Spawn cell.
            _ring_loaded_any = True
        except Exception as exc:  # noqa: BLE001
            _log(
                f"Forest mode: ForestController.start failed: {exc!r}; "
                f"falling back to legacy ring/cell behaviour"
            )

    if not initial_specs and not _ring_loaded_any:
        # Default single-hex behaviour (unchanged).
        initial_specs = [{"x": 100, "y": 100}]

    spawned: list[CellWindow] = []
    for spec in initial_specs:
        hexagon = CellWindow(branding)
        # Apply shape/orientation override if requested (uses the same
        # apply_*_change path the Settings popover uses, so the persistence
        # and re-mask sequence are identical).
        spec_shape = spec.get("shape")
        spec_orient = spec.get("orientation")
        if spec_shape or spec_orient:
            hexagon.apply_shape_change(
                spec_shape or hexagon._shape,
                spec_orient or hexagon._orientation,
            )
        # Apply per-hex catalog override (resolves relative paths to project root).
        spec_catalog = spec.get("catalog_path")
        if spec_catalog:
            from pathlib import Path
            cp = Path(spec_catalog)
            if not cp.is_absolute():
                # resolve relative to project root (parent of apps/)
                project_root = Path(__file__).resolve().parent.parent.parent
                cp = (project_root / cp).resolve()
            hexagon._catalog_path = str(cp)
            hexagon._save_settings()  # persist so reload after restart works
        hexagon.move(int(spec.get("x", 100)), int(spec.get("y", 100)))
        # Wire snapPreview for this hex.
        _SNAP_ENGINE.snapPreview.connect(
            lambda src, tgt, mode, geom, h=hexagon: _on_snap_preview(src, tgt, mode, geom, h)
        )
        hexagon.show()
        spawned.append(hexagon)
        _log(f"Spawned hexagon: {hexagon._id[:8]} at ({spec.get('x')}, {spec.get('y')}) "
             f"shape={hexagon._shape} orient={hexagon._orientation}")

    if len(spawned) == 1:
        _log("Right-click the hexagon â†’ 'Spawn another hexagon' to get a second one,")
        _log("then drag them together to trigger snap-and-dock.")
    else:
        _log(f"{len(spawned)} hexagons spawned. Drag them together — "
             f"honeycomb-strict snap: same shape/orientation, full-edge share only. "
             f"Two flat-top hexes that dock will spawn a master.")

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

