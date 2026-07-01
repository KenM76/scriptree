"""Watch for screen / display configuration changes and rescue
off-screen cells.

## Why this exists

A user can change their resolution, unplug a monitor, re-arrange a
multi-display layout, or remote-desktop into the machine from a
smaller screen.  Any of those can leave ScripTree cells stranded
**off** the visible work area -- the cell window still exists at
its previous coordinates, but those coordinates no longer map to
any screen the user can see, so the cell is effectively lost.

Before this module, the user's only recourse was to quit ScripTree,
delete the saved ring/forest layout file, and start over.  That's
unacceptable for a piece of desktop chrome users live with.

## What it does

``install(app)`` connects to every screen-change signal Qt emits:

  * ``QGuiApplication.screenAdded`` -- new display plugged in.
  * ``QGuiApplication.screenRemoved`` -- display unplugged.
  * ``QGuiApplication.primaryScreenChanged`` -- the OS marked a
    different display primary.
  * Each screen's ``geometryChanged`` -- a resolution change on
    one of the existing displays.

When any of those fires, ``_on_screen_change`` runs the rescue
sweep: walk every cell registered with ``CellRegistry`` and clamp
its top-left to the available geometry of whichever screen the
cell SHOULD live on now.  Cells already on-screen are left alone
(the clamp returns the input unchanged).

The rescue is also exposed as a manual action so the user can
trigger it from the forest right-click menu after any layout
change ScripTree didn't see -- see ``rescue_all_cells``.

## Implementation notes

* Uses ``CellRegistry.instance().all()`` to enumerate cells.  No
  forest / ring awareness is needed at this layer; the rescue is
  per-cell.
* The clamp is delegated to ``CellWindow._clamp_to_screen`` --
  the same helper drag-end uses -- so the behaviour stays consistent
  with the rest of the codebase.
* Idempotent: a cell already inside a valid screen's available
  geometry is not moved.  Safe to call from any context (signal
  handler, menu action, test).
* All errors are swallowed.  This is rescue code; if the rescue
  itself crashes the user loses ScripTree, which is worse than
  losing a few off-screen cells.
"""
from __future__ import annotations

import sys


def _log(msg: str) -> None:
    print(f"[screen_watcher] {msg}", file=sys.stderr)


def rescue_all_cells() -> int:
    """Bring every cell back onto a visible work area -- GROUP-AWARE.

    Returns the number of cells whose top-left was moved.  Cells
    already on a valid screen are left alone.

    a72: a resolution change used to clamp EACH cell's top-left
    independently, which (a) can pile several members onto the same
    screen edge (the "stacked" failure mode) and (b) moves a master
    without re-packing its members around the master's new spot.  Now:

      * For a MASTER (forest hub / ring): clamp the master on-screen
        FIRST, then route its members through the layout engine
        (``_repack_members(instant=True)`` -> ``_compute_layout``),
        which assigns each a FREE, ON-SCREEN, NON-OVERLAPPING honeycomb
        slot around the master's clamped position -- "attach to a side,
        always on screen", the same engine startup/spawn/expand use.
      * For a TRUE STANDALONE (``_group_master_id is None``): clamp it.
      * A cell that is a MEMBER of a group is left to its master's
        repack (handled above), so we don't fight the engine by
        clamping it independently.
    """
    try:
        from scriptree.shell.cell_registry import CellRegistry
    except Exception as exc:  # noqa: BLE001
        _log(f"rescue_all_cells: registry import failed: {exc!r}")
        return 0

    moved = 0
    try:
        cells = list(CellRegistry.instance().all())
    except Exception as exc:  # noqa: BLE001
        _log(f"rescue_all_cells: registry enumeration failed: {exc!r}")
        return 0

    def _clamp(cell) -> bool:  # noqa: ANN001
        raw = cell.pos()
        clamped = cell._clamp_to_screen(raw)
        if clamped != raw:
            cell.move(clamped)
            _log(
                f"rescued cell id={cell._id[:8]} "
                f"({raw.x()},{raw.y()}) -> ({clamped.x()},{clamped.y()})"
            )
            return True
        return False

    for cell in cells:
        try:
            # v0.8.0a110 — AUTO-HIDE AWARENESS.  The rescue must NEVER reveal a
            # cell that is currently hidden.  The repack path it runs for a
            # forest hub (``_restore_remembered_offsets`` / ``_compute_layout``)
            # calls ``setVisible(True)`` on the members, so a display change
            # while the forest is auto-hidden (always-on-top OFF, hub
            # minimised/hidden, cells folded) would POP the folded cells back
            # onto the screen -- and leave them scattered where the rescue put
            # them, not following the hub when it is later revealed.  This is
            # the exact user-reported "the cells pop up even though always-on-
            # top is off, and don't follow the forest when I click its icon".
            #
            # A hidden forest is re-placed (clamped on-screen + re-clustered
            # around the hub) when the user NEXT reveals it via
            # ``ForestVisibilityManager.apply_state`` -- the screen watcher
            # leaves the folded cluster completely alone:
            #   * Forest hub in its hidden/minimised state (tray mode: not
            #     visible; taskbar mode: minimised) -> skip the WHOLE cluster
            #     (skip the master's repack, which is what reveals members).
            #   * Any individually-hidden cell (a folded member / hidden
            #     standalone) -> skip; it isn't on screen, so it needs no rescue
            #     and must not be shown here.
            if getattr(cell, "_is_forest_master", False):
                if cell.isMinimized() or not cell.isVisible():
                    continue
            if not cell.isVisible():
                continue
            is_master = (
                getattr(cell, "role", None) == "master"
                and getattr(cell, "_members", None)
            )
            if is_master:
                # Clamp the master FIRST so _compute_layout's
                # screenAt(master.pos()) resolves to a valid screen,
                # THEN re-pack its members onto free on-screen slots.
                if _clamp(cell):
                    moved += 1
                try:
                    # v0.8.0a83 — after a screen change, first try to restore
                    # each member to its REMEMBERED offset (cells whose spot
                    # still fits go back there); the engine then tiles only the
                    # ones that no longer fit, around the restored cells.
                    _placed = set()
                    restore = getattr(cell, "_restore_remembered_offsets", None)
                    if callable(restore):
                        _placed = restore(move=True)
                    cell._compute_layout(instant=True, pinned=_placed)
                except Exception as exc:  # noqa: BLE001
                    _log(
                        f"rescue_all_cells: repack "
                        f"{getattr(cell, '_id', '?')[:8]} raised {exc!r}"
                    )
            elif getattr(cell, "_group_master_id", None) is None:
                # True standalone (no master) -- clamp it.
                if _clamp(cell):
                    moved += 1
            # else: a member of a group -- its master's repack (above)
            # places it on a free on-screen slot; don't clamp it here.
        except Exception as exc:  # noqa: BLE001
            _log(
                f"rescue_all_cells: skipping cell "
                f"{getattr(cell, '_id', '?')[:8]}: {exc!r}"
            )
            continue
    return moved


def _on_screen_change(*_args, **_kwargs) -> None:
    """Slot fired by every Qt screen-change signal.

    Defers the actual rescue to a 200 ms single-shot timer so:

      1. Multiple signals from the same physical event coalesce
         (Qt sometimes fires screenAdded + primaryScreenChanged +
         geometryChanged in rapid succession when a monitor is
         plugged in).
      2. The OS finishes its own re-layout pass before we sample
         ``availableGeometry`` -- Qt's reported values stabilise
         a few ticks after the signal.
    """
    try:
        from PySide6.QtCore import QTimer

        # Store the timer on the QApplication so it survives across
        # signal firings; recreating it would race with the previous
        # firing's countdown.
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return
        timer = getattr(app, "_screen_rescue_timer", None)
        if timer is None:
            timer = QTimer()
            timer.setSingleShot(True)
            timer.setInterval(200)
            timer.timeout.connect(rescue_all_cells)
            app._screen_rescue_timer = timer  # type: ignore[attr-defined]
        timer.start()
        _log("screen change detected -- scheduled rescue in 200 ms")
    except Exception as exc:  # noqa: BLE001
        _log(f"_on_screen_change: {exc!r}")


def install(app) -> None:  # noqa: ANN001 -- QApplication
    """Connect every relevant Qt screen-change signal to the rescue
    pass.

    Idempotent: re-installing wires duplicate slots, which is
    harmless (each just schedules the same debounced rescue), but
    callers should still only install once per process.
    """
    try:
        # Top-level signals.
        app.screenAdded.connect(_on_screen_change)
        app.screenRemoved.connect(_on_screen_change)
        try:
            app.primaryScreenChanged.connect(_on_screen_change)
        except AttributeError:
            # Older PySide6 versions don't expose this signal at
            # the QApplication level -- not fatal, the per-screen
            # geometryChanged still catches the common case.
            pass

        # Per-screen geometry changes (resolution change on an
        # already-attached display).
        for screen in app.screens():
            try:
                screen.geometryChanged.connect(_on_screen_change)
                screen.availableGeometryChanged.connect(_on_screen_change)
            except Exception:  # noqa: BLE001
                continue

        # New screens added after install: hook their signals too.
        def _hook_new_screen(screen) -> None:  # noqa: ANN001
            try:
                screen.geometryChanged.connect(_on_screen_change)
                screen.availableGeometryChanged.connect(_on_screen_change)
            except Exception:  # noqa: BLE001
                pass

        app.screenAdded.connect(_hook_new_screen)

        _log(f"installed; watching {len(app.screens())} screen(s)")
    except Exception as exc:  # noqa: BLE001
        _log(f"install: failed -- screen watching disabled: {exc!r}")
