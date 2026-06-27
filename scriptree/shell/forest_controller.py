"""
forest_controller.py — orchestrates the forest singleton.

## For humans

The forest is a one-per-session top-level container.  Per the v0.3.15
redesign the visible forest cell is a **regular CellWindow** (same
size, shape, drag/snap/repack behaviour as any other cell) constructed
with role=``"master"`` and the ``is_forest_master=True`` flag.  This
lets us reuse the entire master/member infrastructure that rings
already use:

  * Cells / rings added to the forest become its **members**, sitting
    at honeycomb slots around the forest cell with the existing
    ``_repack_members`` algorithm.
  * Dragging the forest moves all its positioned members (existing
    master-drag translation), which in turn cascades to ring members
    via ``_reflow_members_after_master_move``.
  * Edge-fold + on-screen reflow + per-cell positions all work for
    free — they're properties of "this cell is a master".
  * The member's own role can be ``"master"`` (a ring whose master
    cell is itself a forest member; the ring's own members hang
    off it as normal).

Two specific exemptions distinguish the forest from a regular ring
master:

  1. ``_check_master_validity`` skips it (forest persists with 0
     members).
  2. The right-click menu prepends forest-specific items via the
     ``_forest_menu_extension`` hook — wired by this controller in
     ``_install_menu_hook``.

Public API
----------
    ForestController(branding, registry, snap_engine=None)

    .start(forest=None, suppress_first_run=False) → None
    .save() / .save_as(path) / .open(path) → None
    .refresh_from_sources() → None
    .add_item(path, kind, position=None) → None
    .remove_item(path, *, exclude=True) → None

## For maintainers / LLMs

- The forest cell is a REAL ``CellWindow(role="master",
  is_forest_master=True)`` — it reuses ring master infra
  (_repack_members, reflow, edge-fold, drag-translate). Only TWO
  exemptions: ``_check_master_validity`` skips it (0-member persist),
  and the right-click menu prepends forest items via the
  ``_forest_menu_extension`` hook installed in ``_install_menu_hook``.
  Don't add a third special-case without updating this list and the
  mirror note in ``cell_window.CellWindow.__init__``.
- Autosave is a 250 ms single-shot debounce: ``forestChanged`` →
  ``_mark_dirty`` + ``_schedule_autosave`` (restarts timer) →
  ``_autosave_flush`` → ``save()``. Bursts (discovery applying N items)
  coalesce into one write. EVERY user-visible mutation MUST emit
  ``forestChanged`` or it won't persist. ``flush_if_dirty()`` is the
  synchronous exit-time flush — the launcher must call it on shutdown
  or the last sub-250 ms change is lost.
- ``save()`` target precedence: ``forest.loaded_from`` →
  (only if ``_preferences.fallback_to_default``) resolved default path →
  silent no-op (transient session). In the no-op branch ``_dirty`` is
  deliberately LEFT True so a later ``save_as`` still flushes; do not
  clear it there. ``save_as`` sets ``loaded_from`` so all subsequent
  autosaves retarget the new file.
- ``add_item`` is idempotent by ``_norm`` path and ALSO un-excludes the
  path (re-include is implicit). ``remove_item(exclude=True)`` adds to
  ``excluded`` (auto-discovery won't re-add); ``exclude=False`` is for
  "file deleted from disk" — ``apply_diff`` uses ``exclude=False`` for
  the ``removed`` bucket so a transiently-missing file isn't permanently
  blacklisted.
- ``_norm`` here MUST stay byte-identical to ``forest_discover._norm``
  (resolve + lower + forward-slash). The diff/apply round-trip compares
  keys across the controller↔discover boundary; any divergence desyncs
  add/remove/exclude.
- ``_spawn_item`` dispatch: ring → ``ring_io.load_ring`` then
  ``_attach_existing_master_as_member`` (manual membership wiring +
  surgical repack with existing members fixed); tree/tool →
  ``forest_window._drop_spawn_member_and_link`` (same path as drag-drop)
  then recover the new member via ``next(reversed(_members))``. That
  ``reversed`` recovery assumes ``_drop_spawn_member_and_link`` appended
  exactly one member and dict insertion order holds — fragile coupling
  to CellWindow internals.
- ``_attach_existing_master_as_member`` reaches deep into CellWindow
  privates (``_members``, ``_positioned``, ``_dock_partners``,
  ``_group_master_id``). It repacks with ``fixed=existing_ids`` to honour
  the v0.3.17 "no reshift of existing members" contract.
- ``start()``: with no explicit forest, consults
  ``forest_preferences.json``. fallback_to_default=True loads/creates
  the default file; False = transient in-memory (autosave gated off via
  ``save()``'s no-op branch). First-run dialog fires whenever ``items``
  is empty (NOT gated on ``loaded_from is None``) on a 50 ms singleShot.
- Dialogs are constructed parented to ``self.forest_window`` and shown
  with ``.exec()`` (modal). Dialog→controller calls are direct (no
  signal hop). ``_show_diff_dialog`` is invoked from FirstRunDialog via
  a 0 ms singleShot so the first dialog finishes closing first.
- The launcher should call ``migrate_legacy_autoload_path`` BEFORE
  ``start()`` — this controller assumes the canonical filename.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QPoint, Signal
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox

from scriptree.shell.forest_io import (
    AutoDiscoverConfig, ForestDef, ForestItem, ForestPreferences, ItemKind,
    default_autoload_path, kind_for_suffix, list_autoload_forest,
    load_forest, load_preferences, save_forest, save_preferences,
    shared_autoload_path,
)
from scriptree.shell.forest_discover import (
    DiscoveredItem, DiscoveryDiff, diff_against, discover,
)


def _log(msg: str) -> None:
    print(f"[forest_controller] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Stable identifier for the forest hub cell
# ---------------------------------------------------------------------------
#
# Forest cells persist per-cell QSettings under
# ``hexagon/<id>/<field>``.  Pre-v0.8.0a47 the forest hub got a fresh
# ``uuid.uuid4()`` from ``CellWindow.__init__`` on every launch, so
# none of the cell-Settings-dialog choices the user made for the
# forest (text label, icon, size, transparency, always-on-top,
# label opacity, text-over-icon, collapse behaviour) ever survived a
# restart -- they were re-saved under a new uuid every run and the
# old uuid's entries became zombies.
#
# The forest hub is a SINGLETON per ScripTreeRing process (there is
# exactly one workspace root, even when the user switches between
# different ``.scriptreeforest`` files via ``open()``), so a fixed
# sentinel id is correct.  Passed as ``hexagon_id=`` to the
# ``CellWindow`` constructor in ``ForestController.__init__`` below.
#
# DO NOT change the literal once it's shipped -- every existing
# user's saved settings live at ``hexagon/forest-hub/*`` from a47
# onward, and changing the value would orphan them.
FOREST_HUB_HEX_ID = "forest-hub"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_label(name: str) -> str:
    """[DEPRECATED in v0.8.0a46]  1-3 char abbreviation of a
    forest's name for the cell label.

    Was used pre-v0.6.7 when the forest cell was letters-only
    (no glyph) -- "Forest" became "Fo", "My Stuff" became "MS",
    etc.  v0.6.7 added the proper glyph and the abbreviation
    became redundant; v0.8.0a46 stopped calling this from
    ``ForestController.__init__`` / ``open`` and
    ``ForestSettingsDialog._save`` because the unconditional
    re-apply was overwriting any value the user cleared via the
    cell Settings dialog every launch.

    Kept in place so external code that imports it (none in
    tree, but defensive) still resolves.  Do NOT add new
    callers -- if a feature needs a cell label, get it from the
    user via the cell Settings dialog.
    """
    name = (name or "").strip()
    if not name:
        return "F"
    parts = [p for p in name.split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    if len(name) >= 2:
        return name[:2].title()
    return name[0].upper()


def _norm(path: str) -> str:
    try:
        return str(Path(path).resolve()).lower().replace("\\", "/")
    except (OSError, ValueError, RuntimeError):
        return str(path).lower().replace("\\", "/")


# ---------------------------------------------------------------------------
# ForestController
# ---------------------------------------------------------------------------

class ForestController(QObject):
    """Singleton orchestrator for the forest layer."""

    forestChanged = Signal()

    def __init__(
        self,
        branding: dict,
        registry: Any,
        snap_engine: Any = None,
    ) -> None:
        super().__init__()
        self._branding = branding
        self._registry = registry
        self._snap_engine = snap_engine
        self.forest: ForestDef = ForestDef()
        # The forest cell — a regular CellWindow with
        # ``_is_forest_master=True``, role="master".  Constructed
        # in ``start()``.
        self.forest_window: Any = None
        # path → spawned window (CellWindow master for rings,
        # CellWindow standalone for trees/tools).  We keep this so
        # ``remove_item`` can find what to close.
        self._spawned: dict[str, Any] = {}
        self._dirty: bool = False
        # V3 v0.3.20+ — auto-save default ON.
        #
        # ``forestChanged`` fires when something user-visible
        # changes (item added/removed, settings edited, forest
        # cell moved).  We wire it to a debounced QTimer that
        # runs ``save()`` 250 ms after the last change so:
        #   * Bursts of changes (e.g. discovery applying 10 items
        #     in one batch) coalesce into a single disk write.
        #   * A solo change (one drag, one menu toggle) hits disk
        #     before the user can close the app.
        from PySide6.QtCore import QTimer
        self._autosave_enabled: bool = True
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(250)
        self._autosave_timer.timeout.connect(self._autosave_flush)
        self.forestChanged.connect(self._mark_dirty)
        self.forestChanged.connect(self._schedule_autosave)

        # v0.8.0a25 fix -- when a cell closes WHILE THE APP IS RUNNING,
        # treat that as "user wants this item removed from the forest"
        # and prune the corresponding ForestItem so the next ``save``
        # writes the forest without that cell.  Before this hook, the
        # forest persisted closed cells indefinitely: closing a cell
        # removed the window but left the item in ``forest.items``,
        # so reload + spawn brought the cell back from the dead.
        #
        # ``_app_quitting`` distinguishes user-initiated cell close
        # (False -> prune the item) from app shutdown cascade (True
        # -> leave forest.items alone so flush_if_dirty's final save
        # reflects the user's actual layout).  Set to True by
        # ``flush_if_dirty`` and ``close_all_cells``.
        self._app_quitting: bool = False
        try:
            from scriptree.shell.cell_registry import CellRegistry
            CellRegistry.instance().hexagonClosed.connect(
                self._on_cell_closed
            )
        except Exception as exc:  # noqa: BLE001
            _log(f"__init__: hexagonClosed hook failed: {exc!r}")

        # v0.8.0a52 -- visibility manager.  None until ``start()``
        # constructs the forest_window; the manager needs that
        # reference to flip flags / hide / show on prefs change.
        # Wiring happens at the bottom of ``start()``.
        self._visibility: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        forest: ForestDef | None = None,
        *,
        position: QPoint | None = None,
        suppress_first_run: bool = False,
    ) -> None:
        """Construct the forest cell, bind a forest, spawn its items.

        ``forest=None`` means "autoload from the per-user last
        forest, or empty default if none exists".
        """
        # v0.8.0a57: re-apply the persisted debug-logging toggle
        # on every launch so a user who flipped it ON from the
        # menu, then exited, still has the tee active for the
        # NEXT run -- which is the one that captures the bug
        # they're trying to reproduce.  Cheap: a single
        # QSettings read + (only if True) an open() on a log
        # file.  No-op when the user never toggled it on.
        try:
            from scriptree.shell import debug_logging
            if debug_logging.load_persisted_state():
                debug_logging.set_enabled(True)
        except Exception as exc:  # noqa: BLE001
            _log(f"start: debug_logging restore failed: {exc!r}")

        # V3 v0.3.21+ — honour ``forest_preferences.json``.
        #
        # When the caller didn't pass an explicit ``forest`` argument
        # (the common case — bare ``run_scriptreeforest`` launch with
        # no positional path), we consult the user's preferences:
        #
        #   * fallback_to_default=True  → load the configured default
        #     forest file, creating it empty if it doesn't exist (the
        #     v0.3.20 default-file behaviour).
        #   * fallback_to_default=False → start with an empty
        #     in-memory transient forest.  Autosave is implicitly
        #     gated: ``save()`` is a no-op until the user explicitly
        #     ``save_as``s, since there's nowhere safe to write to.
        #
        # First-run users hit the factory defaults (fallback=True,
        # path=""), matching the v0.3.20 experience verbatim.
        self._preferences: ForestPreferences = load_preferences(self._branding)

        if forest is None:
            if self._preferences.fallback_to_default:
                target = self._preferences.resolved_default_path(self._branding)
                # Try to load the configured default file.
                if target.is_file():
                    try:
                        forest = load_forest(target)
                    except (OSError, ValueError) as exc:
                        _log(
                            f"start: failed to load default forest at "
                            f"{target}: {exc!r}; starting empty"
                        )
                        forest = ForestDef()
                else:
                    # File doesn't exist yet — create it so autosave
                    # has a target.
                    forest = ForestDef()
                    try:
                        save_forest(forest, target)
                        _log(
                            f"start: no forest found — created default "
                            f"at {forest.loaded_from}"
                        )
                    except OSError as exc:
                        _log(
                            f"start: could not create default forest "
                            f"file: {exc!r}; running in-memory only"
                        )
            else:
                # Preferences say: do NOT fall back.  Run with a
                # transient forest; autosave is a no-op until the
                # user explicitly saves.
                forest = ForestDef()
                _log(
                    "start: fallback_to_default disabled — running "
                    "with a transient in-memory forest"
                )
        self.forest = forest

        # Build the forest cell.  CellWindow construction needs to
        # happen here (not at module load) so the QApplication is
        # already up by the time we instantiate Qt widgets.
        #
        # v0.8.0a47+ -- pass a STABLE ``hexagon_id`` so the forest
        # cell's per-cell QSettings entries
        # (``hexagon/<id>/text_label``, ``hexagon/<id>/icon_path``,
        # ``hexagon/<id>/size_px``, etc.) survive across launches.
        # Pre-a47 the forest_window was given a fresh
        # ``uuid.uuid4()`` every launch (the CellWindow default),
        # so anything the user customised via the cell Settings
        # dialog -- text label, icon, size, transparency,
        # always-on-top -- silently vanished on the next run.
        # See the matching cleanup at ``rags/lessons/
        # forest_hub_cell_stable_settings_id.md`` (filed below).
        #
        # The forest hub is a singleton per ScripTreeRing process
        # so a fixed sentinel is correct -- there is exactly one
        # "forest cell" per workspace and its QSettings should
        # always live at the same key.  If we ever support
        # multiple forests in one process, the id will need to be
        # derived from the forest file path instead, but that's
        # not a near-term concern (forest is the singular
        # workspace root).
        from scriptree.shell.cell_window import CellWindow
        self.forest_window = CellWindow(
            self._branding,
            role="master",
            is_forest_master=True,
            hexagon_id=FOREST_HUB_HEX_ID,
        )
        # v0.8.0a46+ -- DO NOT auto-set the cell's text label from the
        # forest's name.  Pre-v0.6.7 the forest cell was letters-only
        # (no glyph), so we stamped a 1-3 char abbreviation
        # ("Fo" for "Forest") via ``_derive_label`` and called
        # ``apply_label_change`` to make it visible on the hex.
        # v0.6.7 added the proper conifer / fractal-tree glyph (set
        # below from ``self.forest.icon_data`` or the bundled
        # ``forest`` asset).  The auto-text-label became redundant
        # AND actively harmful: it overwrote any value the user
        # cleared via the cell Settings dialog every time
        # ``ForestController.__init__`` ran (i.e. every launch), so
        # the "Fo" abbreviation kept coming back even after the user
        # explicitly removed it.  See the analogous removals in
        # ``open()`` (post-load) and ``ForestSettingsDialog._save``
        # (post-rename).  The hover tooltip / popup header falls
        # through ``tree_popup._popup_header_text`` to the "Forest"
        # role default when ``_text_label`` is empty, which is the
        # behaviour the user wants.

        # v0.6.7 — give the bare forest hub an icon (was letters
        # only).  Prefer the forest's own embedded icon; otherwise
        # fall back to the bundled "folder" workspace glyph so a
        # fresh / legacy forest still shows a real icon.  Paint code
        # prefers _icon_data_b64 over the text label, so the glyph
        # wins while the label survives as a fallback.
        try:
            ic_data = self.forest.icon_data
            ic_fmt = self.forest.icon_format or "png"
            if not ic_data:
                from scriptree.shell.icon_assets import (
                    BUNDLED_FORMAT, bundled_icon_b64,
                )
                # v0.6.13 — the forest hub gets the dedicated
                # ``forest`` glyph (a conifer-tree archetype) so the
                # workspace root reads as the forest, not as a
                # generic folder.  Fall back to ``folder`` only if
                # the new icon isn't on disk yet (e.g. running an
                # older deploy whose icons/ wasn't refreshed).
                ic_data = (
                    bundled_icon_b64("forest")
                    or bundled_icon_b64("folder")
                )
                ic_fmt = BUNDLED_FORMAT
            if ic_data:
                self.forest_window._icon_data_b64 = ic_data
                self.forest_window._icon_data_format = ic_fmt
                self.forest_window.update()
        except Exception as exc:  # noqa: BLE001
            _log(f"forest hub icon apply failed: {exc!r}")

        # The forest is a master, but we DO want it to participate in
        # the snap engine for hover/preview behaviour — same as a
        # ring master.  ``_wire_hex_to_snap`` is the canonical wire-
        # up that handles signal connection for both standalone and
        # master cells; we call it the same way ring spawn does.
        try:
            from scriptree.shell.ring_main import _wire_hex_to_snap
            _wire_hex_to_snap(self.forest_window)
        except Exception as exc:  # noqa: BLE001
            _log(f"could not wire forest cell to snap engine: {exc!r}")

        # Position.  Restore the user's last placement when the
        # forest carried one (v0.6.11 — ``ForestDef.window_position``
        # persists across launches).  Default is the bottom-left
        # corner of the primary screen per user spec ("start in the
        # bottom left corner").  ``_window_position`` is the legacy
        # transient attribute name; honour it as a fallback so any
        # caller that set it before the field existed still works.
        if position is None:
            stored = getattr(self.forest, "window_position", None)
            if stored is None:
                stored = getattr(self.forest, "_window_position", None)
            if stored is not None:
                position = QPoint(*stored)
            else:
                from PySide6.QtGui import QGuiApplication
                screen = QGuiApplication.primaryScreen()
                if screen is not None:
                    geo = screen.availableGeometry()
                    margin = 24
                    x = geo.left() + margin
                    y = geo.bottom() - self.forest_window.height() - margin
                    position = QPoint(x, y)
                else:
                    position = QPoint(24, 600)
        # a69: clamp the restored/derived position on-screen so a forest
        # saved at a coordinate that no longer fits the current display
        # (resolution shrank, monitor unplugged) can't start the hub
        # off-screen -- the "forest disappeared" bug.
        try:
            position = self.forest_window._clamp_to_screen(position)
        except Exception as exc:  # noqa: BLE001
            _log(f"start: hub position clamp raised {exc!r}")
        self.forest_window.move(position)
        # Seed the in-memory ForestDef so the first save without an
        # explicit move still carries the position (matches the user
        # spec "remember its last location").
        try:
            self.forest.window_position = (
                int(position.x()), int(position.y()),
            )
        except Exception:  # noqa: BLE001
            pass

        # v0.6.11 — keep ``forest.window_position`` in sync with every
        # actual move so a later save (autosave or user-triggered)
        # carries the latest coordinates.  Marking dirty triggers the
        # debounced autosave when fallback_to_default is on.
        def _on_hex_moved(hex_id: str) -> None:
            if (
                self.forest_window is None
                or hex_id != self.forest_window._id
            ):
                return
            try:
                p = self.forest_window.pos()
                new_pos = (int(p.x()), int(p.y()))
                if self.forest.window_position != new_pos:
                    self.forest.window_position = new_pos
                    self._mark_dirty()
            except Exception:  # noqa: BLE001
                pass
        try:
            self._registry.hexagonMoved.connect(_on_hex_moved)
            # Keep a reference so GC doesn't collect the closure.
            self._forest_pos_slot = _on_hex_moved
        except Exception as exc:  # noqa: BLE001
            _log(f"start: could not wire window-position capture: {exc!r}")
        # v0.8.0a52 -- construct the visibility manager BEFORE the
        # first show() so its ``apply()`` call sets the correct
        # window flags (Qt.Tool / Qt.Window swap for taskbar mode,
        # WindowStaysOnTopHint for AOT) before Qt commits the
        # native window.
        #
        # v0.8.0a54 -- the taskbar surface is now the hub itself
        # (not a proxy), so the initial visibility decision is
        # three-way:
        #   show_always_on_top ON  -> show normally (current
        #                             behaviour).
        #   AOT off, taskbar ON    -> showMinimized() so the
        #                             taskbar entry appears at
        #                             startup; the hex stays
        #                             off-screen.  Cells get
        #                             hidden after spawn (the
        #                             "Decide initial visibility"
        #                             tail at the bottom of
        #                             start()).
        #   AOT off, tray-only     -> leave hidden; the tray
        #                             icon brings everything back.
        # In all auto-hide combos the descendants spawned below
        # also need to fold away -- handled at the tail of
        # start() once spawn + repack have settled.
        from scriptree.shell.forest_visibility import (
            ForestVisibilityManager,
        )
        self._visibility = ForestVisibilityManager(
            self.forest_window,
            self._registry,
            quit_callback=self._on_visibility_quit,
        )
        try:
            self._visibility.apply(self._preferences)
        except Exception as exc:  # noqa: BLE001
            _log(f"start: visibility.apply failed: {exc!r}")

        # Initial show.  Always-on-top wins; otherwise taskbar
        # gets a minimised hex; otherwise the hub stays hidden
        # (tray-only mode -- user clicks the tray icon).
        #
        # a63 (user-reported "hub won't move until I hide/show it"):
        # capture the startup mode + post-show hub state in the debug
        # log so a persistent movability regression can be diagnosed
        # directly, and schedule ``_finalize_hub_interactive`` to
        # raise + activate the hub once Qt has finished the first map.
        _startup_mode = (
            "always_on_top" if self._preferences.show_always_on_top
            else "taskbar" if self._preferences.show_on_taskbar
            else "tray_only_hidden"
        )
        if self._preferences.show_always_on_top:
            self.forest_window.show()
            # v0.6.10 macify: soft fade-in for the forest hub.
            try:
                self.forest_window._fade_in()
            except Exception:  # noqa: BLE001
                pass
        elif self._preferences.show_on_taskbar:
            # showMinimized() is what creates the taskbar entry
            # on Win11 for a ``Qt.Window``-flagged hub.  Without
            # this, a hidden Qt.Window has no taskbar button --
            # the user would have no surface to click and the
            # forest would be unreachable until they restarted.
            self.forest_window.showMinimized()
        _log(f"[forest_startup] mode={_startup_mode} initial show issued")
        try:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._finalize_hub_interactive)
        except Exception as exc:  # noqa: BLE001
            _log(f"start: could not schedule hub finalize: {exc!r}")
        # v0.6.12 — settle: the hub may overlap a standalone cell that
        # was loaded from QSettings before us; slide whichever side
        # is movable until clear.
        try:
            self.forest_window._settle_no_overlap()
        except Exception as exc:  # noqa: BLE001
            _log(f"_settle_no_overlap (forest hub) raised {exc!r}")

        # Install the menu hook now that the cell exists.
        self._install_menu_hook(self.forest_window)

        # Spawn items.
        for it in list(self.forest.items):
            self._spawn_item(it)

        # v0.8.0a83 — load the saved remembered offsets into the hub BEFORE
        # the canonical repack, so the repack restores the user's arrangement.
        self._load_remembered_offsets_into_hub()

        # v0.6.14 — canonicalise every forest member's position at
        # startup so stale stored item.position values (from when
        # the forest was at a different location, or from a save
        # before the hub moved) never leave cells jumbled.  Pre-
        # v0.6.14 we only checked for *centre-stacked* members
        # (_resolve_member_overlap → _resolve_member_stacking) —
        # but the user reported "cells get jumbled over top of each
        # other until I drag the forest a bit", which means the
        # surgical check wasn't catching everything.  A full
        # canonical _repack_members() places every member on a free
        # honeycomb slot around the (possibly moved) hub.  Trade-
        # off: per-item.position overrides set by hand are
        # discarded; the user has explicitly asked for this in
        # exchange for never-jumbled-startup.
        if self.forest_window is not None:
            try:
                # v0.6.34 — ``instant=True``: snap members onto
                # their canonical slots immediately so the user
                # never sees the stale-saved-positions jumble glide
                # into place.  The previous 260 ms eased animation
                # was the source of the "jumbled mess with spaces in
                # between" report.
                # v0.8.0a83 — restore the user's remembered arrangement first
                # (cells whose remembered spot fits go there), then engine-tile
                # only the remainder around them.  Falls back to pure canonical
                # tiling when there are no remembered offsets (fresh forest).
                _placed = self.forest_window._restore_remembered_offsets(
                    move=True,
                )
                self.forest_window._compute_layout(instant=True, pinned=_placed)
                # Recursive repack into rings.  The call above
                # places the forest's direct members (rings + cells)
                # at free slots around the hub, but each RING is
                # itself a master whose own members were loaded at
                # absolute positions via ``load_ring``.  After the
                # forest moved a ring, the ring's members are now
                # offset from the ring; repacking the ring brings
                # its cells back onto the ring's honeycomb slots.
                registry = self._registry
                for ring_id in list(self.forest_window._members):
                    ring = registry.get(ring_id)
                    if ring is None:
                        continue
                    if ring.role != "master":
                        continue
                    if not ring._members:
                        continue
                    try:
                        ring._repack_members(instant=True)
                    except Exception as exc:  # noqa: BLE001
                        _log(
                            f"startup recursive _repack_members on "
                            f"ring {ring_id[:8]} failed: {exc!r}"
                        )
            except Exception as exc:  # noqa: BLE001
                _log(
                    f"startup _repack_members failed: {exc!r} — "
                    f"falling back to stack-only resolution"
                )
                self._resolve_member_overlap()

        # First-run: empty forest → welcome dialog after the next
        # event-loop tick.  v0.3.16: trigger now fires whenever
        # ``items`` is empty (not gated on ``loaded_from is None``).
        # Pre-fix, autoloading the per-user file always set
        # ``loaded_from``, suppressing the dialog even when the user
        # had explicitly cleared their forest and was looking at an
        # empty workspace expecting a way to repopulate.
        if not suppress_first_run and not self.forest.items:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(50, self._show_first_run_dialog)

        # v0.8.0a54: in auto-hide mode (always-on-top OFF +
        # taskbar / tray ON) the spawn pass above showed every
        # cell.  Fold them away so the startup state matches the
        # invariant "only what the taskbar / tray reveals is
        # visible".  hide_descendants_only() also seeds the
        # manager's _hidden_descendant_ids list so a subsequent
        # show_hub restores ONLY the cells we just hid (not
        # ones the user collapsed before).
        if (
            not self._preferences.show_always_on_top
            and (
                self._preferences.show_on_taskbar
                or self._preferences.show_in_system_tray
            )
        ):
            try:
                self._visibility.hide_descendants_only()
            except Exception as exc:  # noqa: BLE001
                _log(
                    f"start: post-spawn hide_descendants_only "
                    f"raised {exc!r}"
                )

    # ------------------------------------------------------------------
    # Menu hook
    # ------------------------------------------------------------------

    def _install_menu_hook(self, cell: Any) -> None:
        """Register the forest-specific menu items on ``cell``'s
        right-click menu.  Uses the ``_forest_menu_extension`` hook
        added to ``CellWindow._show_context_menu`` in v0.3.15."""
        cell._forest_menu_extension = self._populate_forest_menu

    def _populate_forest_menu(
        self, menu: QMenu, cell: Any | None = None,
    ) -> None:
        """Insert forest-specific actions at the top of ``menu``.

        Layout: a ``Forest`` submenu so the standard cell menu stays
        readable.  All actions wire to controller methods directly
        (no signal hops, simpler debug).

        ``cell`` is the right-clicked cell (v0.8.0a25+).  When
        provided AND the cell is bound to a catalog under one of
        the install roots, a per-cell "Uninstall app..." action is
        added so the user can remove the app's files from disk.
        Defaults to None for back-compat with callers on the
        older 1-arg hook contract.
        """
        # v0.6.15 — icon helpers.  Universal save/open/refresh come
        # from Qt's standard set so they match every other app on
        # the platform; everything else uses a glyph from our
        # bundled ``icons/`` set whose category matches the action.
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication, QStyle
        _SP = QStyle.StandardPixmap

        def _std(which):  # noqa: ANN001, ANN202
            app = QApplication.instance()
            return app.style().standardIcon(which) if app else QIcon()

        def _bundled(name: str) -> QIcon:
            try:
                from scriptree.shell.icon_assets import (
                    bundled_icon_png_path,
                )
                p = bundled_icon_png_path(name)
                if p is None:
                    return QIcon()
                ic = QIcon(str(p))
                return ic if not ic.isNull() else QIcon()
            except Exception:  # noqa: BLE001
                return QIcon()

        forest_menu = QMenu("Forest", menu)
        forest_menu.setIcon(_bundled("forest"))

        a_save = forest_menu.addAction(_std(_SP.SP_DialogSaveButton), "Save forest")
        a_save_as = forest_menu.addAction(
            _std(_SP.SP_DialogSaveButton), "Save forest as…",
        )
        a_open = forest_menu.addAction(
            _std(_SP.SP_DialogOpenButton), "Open forest…",
        )
        forest_menu.addSeparator()
        a_refresh = forest_menu.addAction(
            _std(_SP.SP_BrowserReload), "Refresh from sources",
        )
        a_autoadd = forest_menu.addAction(
            _bundled("package"),
            "Auto-add from ScripTreeApps now",
        )
        a_reorganise = forest_menu.addAction(
            _bundled("folder"),
            "Re-organise (re-run category grouping)",
        )
        a_rescue = forest_menu.addAction(
            _std(_SP.SP_DesktopIcon),
            "Bring all cells back on-screen",
        )
        forest_menu.addSeparator()

        # v0.8.0a83 — Cell layout sub-submenu: Save / Load / Recent.  Saves
        # the CURRENT arrangement (each cell's offset from the hub) to a named
        # .scriptreelayout, and re-applies a saved one (reposition-existing-
        # only: matching cells move to their saved spot, others stay put,
        # entries with no matching cell are skipped).
        layout_menu = QMenu("Cell layout", forest_menu)
        layout_menu.setIcon(_bundled("forest"))
        a_layout_save = layout_menu.addAction(
            _std(_SP.SP_DialogSaveButton), "Save layout…",
        )
        a_layout_load = layout_menu.addAction(
            _std(_SP.SP_DialogOpenButton), "Load layout…",
        )
        layout_menu.addSeparator()
        recent_layout_menu = QMenu("Recent layouts", layout_menu)
        recent_layout_menu.setIcon(_std(_SP.SP_FileDialogDetailedView))
        try:
            from pathlib import Path as _P
            from scriptree.shell import recent_files as _rf
            _recent_layouts = _rf.get_layouts()
        except Exception:  # noqa: BLE001
            _recent_layouts = []
        if _recent_layouts:
            for _lp in _recent_layouts:
                _ra = recent_layout_menu.addAction(f"{_P(_lp).stem}  —  {_lp}")
                _ra.triggered.connect(
                    lambda _checked=False, p=_lp: self._apply_layout_from_path(p)
                )
        else:
            _none = recent_layout_menu.addAction("(none)")
            _none.setEnabled(False)
        layout_menu.addMenu(recent_layout_menu)
        a_layout_save.triggered.connect(self._on_save_layout)
        a_layout_load.triggered.connect(self._on_load_layout)
        forest_menu.addMenu(layout_menu)
        forest_menu.addSeparator()

        # v0.8.0a52 -- Visibility sub-submenu with three checkable
        # actions.  Each toggle persists via ``update_preferences``
        # and re-applies live through the visibility manager.  The
        # toggle handler refuses to uncheck the LAST checked
        # action so the user can't accidentally make the hub
        # unreachable.
        vis_menu = QMenu("Visibility", forest_menu)
        vis_menu.setIcon(_bundled("forest"))
        prefs_now = self.get_preferences()

        a_aot = vis_menu.addAction("Show always on top (over desktop)")
        a_aot.setCheckable(True)
        a_aot.setChecked(prefs_now.show_always_on_top)
        a_aot.setToolTip(
            "Float the forest hub above the desktop, the way "
            "it has worked since ScripTree v0.3.  Default ON."
        )

        a_tb = vis_menu.addAction("Show on taskbar")
        a_tb.setCheckable(True)
        a_tb.setChecked(prefs_now.show_on_taskbar)
        a_tb.setToolTip(
            "Add a persistent ScripTree Forest entry to the "
            "Windows taskbar.  Click the entry to bring the "
            "forest hub to the front.  Works the same way "
            "PortableApps does."
        )

        a_tr = vis_menu.addAction("Show in system tray")
        a_tr.setCheckable(True)
        a_tr.setChecked(prefs_now.show_in_system_tray)
        a_tr.setToolTip(
            "Add a forest icon to the system tray.  Left-click "
            "to bring the forest hub to the front; right-click "
            "for Show / Quit.  Works the same way PortableApps "
            "does."
        )

        # Toggle handler: every change goes through here so we
        # can enforce "at least one stays checked" + persist +
        # apply live.  Captured ``_actions`` lets us re-check the
        # last action and surface a brief warning when the user
        # tries to uncheck it.
        _actions = [
            (a_aot, "show_always_on_top"),
            (a_tb, "show_on_taskbar"),
            (a_tr, "show_in_system_tray"),
        ]

        def _on_visibility_toggle(fired_action, _checked: bool = False) -> None:
            # Read the candidate new state off the actions.
            new_aot = a_aot.isChecked()
            new_tb = a_tb.isChecked()
            new_tr = a_tr.isChecked()
            if not (new_aot or new_tb or new_tr):
                # a66: the user just unchecked the LAST enabled mode --
                # refuse it, restoring ONLY the action that fired.
                #
                # The pre-a66 code looped over _actions re-checking
                # EVERY unchecked action.  When you uncheck your one
                # remaining mode, all three are momentarily unchecked,
                # so that loop turned ON all three; and because each
                # setChecked re-emitted ``toggled`` (no blockSignals)
                # it re-entered this handler and persisted the bogus
                # all-modes-on state.  Restore just the fired action,
                # with its signals blocked so the programmatic
                # re-check neither re-enters nor persists.
                fired_action.blockSignals(True)
                fired_action.setChecked(True)
                fired_action.blockSignals(False)
                try:
                    from PySide6.QtWidgets import QToolTip
                    from PySide6.QtGui import QCursor
                    QToolTip.showText(
                        QCursor.pos(),
                        "At least one visibility option must stay "
                        "enabled — otherwise the forest hub would "
                        "become unreachable.",
                    )
                except Exception:  # noqa: BLE001
                    pass
                return
            new_prefs = ForestPreferences(
                fallback_to_default=prefs_now.fallback_to_default,
                default_forest_path=prefs_now.default_forest_path,
                show_always_on_top=new_aot,
                show_on_taskbar=new_tb,
                show_in_system_tray=new_tr,
                # a84: MUST carry the autostart scope through — omitting it
                # defaults to "off", so a visibility toggle would silently
                # reset forest login-autostart on disk while the Run-key still
                # carries --forest (UI says Disabled but it still launches at
                # login, with no cleanup path).  This was the #1 adversarial
                # finding: every ForestPreferences(...) the user can reach must
                # preserve every field it isn't deliberately changing.
                autostart_scope=prefs_now.autostart_scope,
            )
            try:
                self.update_preferences(new_prefs)
            except Exception as exc:  # noqa: BLE001
                _log(f"Visibility toggle: update_preferences failed: {exc!r}")

        for action, _attr in _actions:
            # Pass the firing action explicitly so the "refuse to
            # uncheck the last mode" path can restore exactly that one
            # (self.sender() is unreliable for a plain-callable slot).
            action.toggled.connect(
                lambda checked, a=action: _on_visibility_toggle(a, checked)
            )

        forest_menu.addMenu(vis_menu)
        forest_menu.addSeparator()

        # ---- Auto-load on startup (v0.8.0a84) ----------------------------
        # Forest analog of the tree-ring's "Auto-load on startup" submenu
        # (cell_window.py).  Registers a Windows Run-key so ScripTree
        # launches in forest mode at login and loads THIS forest.  Three
        # mutually-exclusive states; only one carries a check at a time and
        # the checks are rebuilt from prefs each time the menu opens.  The
        # heavy lifting (save-first prompt, UAC elevation for system scope,
        # the shared Run-key recompute) lives in ``_on_forest_autostart_set``.
        autostart_menu = QMenu("Auto-load on startup", forest_menu)
        autostart_menu.setIcon(_std(_SP.SP_BrowserReload))
        _as_scope = prefs_now.autostart_scope

        a_as_off = autostart_menu.addAction("Disabled")
        a_as_off.setCheckable(True)
        a_as_off.setChecked(_as_scope == "off")
        a_as_off.setToolTip(
            "Do not launch ScripTree automatically at Windows login."
        )

        a_as_user = autostart_menu.addAction("For current user only")
        a_as_user.setCheckable(True)
        a_as_user.setChecked(_as_scope == "user")
        a_as_user.setToolTip(
            "Launch ScripTree with this forest when the current user logs "
            "in (a per-user Run-key — no admin required)."
        )

        a_as_sys = autostart_menu.addAction("For all users (requires admin)")
        a_as_sys.setCheckable(True)
        a_as_sys.setChecked(_as_scope == "system")
        a_as_sys.setToolTip(
            "Launch ScripTree with this forest for every user at login (an "
            "all-users Run-key).  Prompts for administrator rights."
        )

        a_as_off.triggered.connect(
            lambda _checked=False: self._on_forest_autostart_set("off")
        )
        a_as_user.triggered.connect(
            lambda _checked=False: self._on_forest_autostart_set("user")
        )
        a_as_sys.triggered.connect(
            lambda _checked=False: self._on_forest_autostart_set("system")
        )

        forest_menu.addMenu(autostart_menu)
        forest_menu.addSeparator()

        # v0.8.0a57 -- Debug sub-submenu.  Two items:
        #   * "Enable verbose logging" -- checkable toggle that
        #     tees stderr to %APPDATA%/ScripTree/logs/ AND flips
        #     win_virtual_desktops verbose output on.  Persisted
        #     in QSettings so it survives the restart that's
        #     usually needed to reproduce a startup-only bug.
        #   * "Open debug folder" -- pops Explorer at the log
        #     directory so the user can grab the file to send.
        from scriptree.shell import debug_logging as _dbg
        debug_menu = QMenu("Debug", forest_menu)
        debug_menu.setIcon(_bundled("bug"))
        a_verbose = debug_menu.addAction("Enable verbose logging")
        a_verbose.setCheckable(True)
        a_verbose.setChecked(_dbg.is_enabled())
        a_verbose.setToolTip(
            "Capture stderr (including virtual-desktop COM calls) "
            "to a daily log file under %APPDATA%/ScripTree/logs/.  "
            "Persists across restarts so a bug you can only "
            "reproduce on launch is still captured.  Use the "
            "'Open debug folder' item below to find the log."
        )

        def _on_verbose_toggled(checked: bool) -> None:
            actual = _dbg.set_enabled_and_persist(checked)
            # Sync the checkbox state with reality (set_enabled
            # can return False if opening the log file failed).
            if actual != checked:
                a_verbose.blockSignals(True)
                a_verbose.setChecked(actual)
                a_verbose.blockSignals(False)
        a_verbose.toggled.connect(_on_verbose_toggled)

        a_open_log = debug_menu.addAction("Open debug folder")
        a_open_log.setToolTip(
            "Open %APPDATA%/ScripTree/logs/ in Explorer."
        )
        a_open_log.triggered.connect(_dbg.open_log_folder)

        forest_menu.addMenu(debug_menu)
        forest_menu.addSeparator()

        a_settings = forest_menu.addAction(
            _bundled("settings"), "Forest settings…",
        )
        a_excluded = forest_menu.addAction(
            _bundled("filter"), "Manage excluded items…",
        )
        forest_menu.addSeparator()
        a_about = forest_menu.addAction(
            _bundled("forest"), "About this forest",
        )

        # v0.8.0a25 -- per-cell Uninstall action.  Only added when
        # the right-clicked cell is bound to a catalog whose folder
        # lives under one of the install roots (otherwise we have
        # nothing to safely delete).  Lives at the bottom of the
        # Forest submenu so the user doesn't trigger it by accident
        # while reaching for Save or Refresh.
        a_uninstall = None
        if cell is not None:
            cat_path = getattr(cell, "catalog_path", None)
            if cat_path:
                from pathlib import Path
                from scriptree.core.app_install import (
                    default_personal_root, default_shared_root,
                )
                try:
                    parent = Path(cat_path).resolve().parent
                    roots: list[Path] = []
                    for fn in (
                        default_personal_root, default_shared_root,
                    ):
                        try:
                            roots.append(Path(fn()).resolve())
                        except Exception:  # noqa: BLE001
                            continue
                    under_install_root = any(
                        parent != r and parent.is_relative_to(r)
                        for r in roots
                    )
                except Exception:  # noqa: BLE001
                    under_install_root = False
                if under_install_root:
                    forest_menu.addSeparator()
                    a_uninstall = forest_menu.addAction(
                        _std(_SP.SP_TrashIcon),
                        "Uninstall app from disk...",
                    )
                    # Capture both controller + cell so the slot
                    # knows which catalog to delete.
                    a_uninstall.triggered.connect(
                        lambda _checked=False, c=cell:
                        self._on_uninstall_app(c)
                    )

        a_save.triggered.connect(self.save)
        a_save_as.triggered.connect(self._on_save_as)
        a_open.triggered.connect(self._on_open)
        a_refresh.triggered.connect(self.refresh_from_sources)
        a_autoadd.triggered.connect(self._on_autoadd_now)
        a_reorganise.triggered.connect(self.refresh_from_sources)
        a_rescue.triggered.connect(self._on_rescue_offscreen)
        a_settings.triggered.connect(self._show_settings_dialog)
        a_excluded.triggered.connect(self._show_excluded_dialog)
        a_about.triggered.connect(self._on_about)

        # Insert the submenu at the top of the parent menu so the
        # forest items are reachable without scrolling past every
        # standard cell action.
        first = menu.actions()[0] if menu.actions() else None
        menu.insertMenu(first, forest_menu)

    # ------------------------------------------------------------------
    # Cell layout — Save / Load / apply (v0.8.0a83)
    # ------------------------------------------------------------------

    def _layouts_dir(self) -> Path:
        """Default directory for ``.scriptreelayout`` files — a sibling of the
        rings dir: ``<Documents>/<BRAND>/layouts/`` (created on demand)."""
        from scriptree.shell.ring_io import _default_rings_dir

        brand = (self._branding or {}).get("appName", "ScripTree")
        d = _default_rings_dir(brand).parent / "layouts"
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return d

    def _on_save_layout(self) -> None:
        """Capture the CURRENT cell arrangement (each forest member's offset
        from the hub) and write it to a named ``.scriptreelayout``."""
        from pathlib import Path as _P

        from PySide6.QtWidgets import QFileDialog

        from scriptree.shell import recent_files as _rf
        from scriptree.shell.cell_window import _member_offset_key
        from scriptree.shell.layout_io import (
            LayoutDef, LayoutEntry, save_layout,
        )

        hub = self.forest_window
        if hub is None:
            return
        hub_pos = hub.pos()
        entries: list[LayoutEntry] = []
        for it in self.forest.items:
            win = self._spawned.get(_norm(it.path))
            if win is None:
                continue
            cp = getattr(win, "_catalog_path", None)
            if not cp or _member_offset_key(win) is None:
                continue  # no stable key -> can't be remembered/applied
            entries.append(LayoutEntry(
                catalog_path=str(cp),
                rel_offset=(
                    win.pos().x() - hub_pos.x(),
                    win.pos().y() - hub_pos.y(),
                ),
                kind=it.kind,
            ))
        if not entries:
            _log("save layout: no positionable cells")
            return
        chosen, _ = QFileDialog.getSaveFileName(
            None,
            "Save cell layout as",
            str(self._layouts_dir() / "layout.scriptreelayout"),
            "ScripTree cell layouts (*.scriptreelayout);;All files (*)",
        )
        if not chosen:
            return
        p = _P(chosen)
        if p.suffix.lower() != ".scriptreelayout":
            p = p.with_suffix(".scriptreelayout")
        try:
            save_layout(LayoutDef(name=p.stem, entries=entries), p)
            _rf.add_layout(str(p))
            _log(f"saved cell layout: {p} ({len(entries)} cells)")
        except Exception as exc:  # noqa: BLE001
            _log(f"save layout failed: {exc!r}")

    def _on_load_layout(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        chosen, _ = QFileDialog.getOpenFileName(
            None,
            "Load cell layout",
            str(self._layouts_dir()),
            "ScripTree cell layouts (*.scriptreelayout);;All files (*)",
        )
        if chosen:
            self._apply_layout_from_path(chosen)

    def _apply_layout_from_path(self, path: str) -> None:
        from scriptree.shell import recent_files as _rf
        from scriptree.shell.layout_io import load_layout

        try:
            layout = load_layout(path)
        except Exception as exc:  # noqa: BLE001
            _log(f"load layout failed ({path}): {exc!r}")
            return
        _rf.add_layout(path)
        self._apply_layout(layout)

    def _apply_layout(self, layout: Any) -> None:
        """Reposition EXISTING forest cells to match ``layout`` (positions
        only): cells matched by tool/tree path move to the saved offset; cells
        not named in the layout stay put; entries with no matching cell are
        skipped.  Never spawns or removes cells.
        """
        hub = self.forest_window
        if hub is None:
            return
        from scriptree.shell.cell_window import _member_offset_key

        # Index each spawned forest member by its offset key.
        by_key: dict[str, Any] = {}
        for it in self.forest.items:
            win = self._spawned.get(_norm(it.path))
            if win is None:
                continue
            k = _member_offset_key(win)
            if k is not None:
                by_key[k] = win

        applied = 0
        for entry in layout.entries:
            ek = _norm(entry.catalog_path)
            if ek not in by_key:
                continue  # reposition-existing-only: skip unmatched entries
            hub._remembered_offsets[ek] = (
                int(entry.rel_offset[0]), int(entry.rel_offset[1]),
            )
            applied += 1
        if applied == 0:
            _log(
                f"apply layout '{getattr(layout, 'name', '?')}': "
                f"no matching cells in the current forest"
            )
            return
        try:
            placed = hub._restore_remembered_offsets(move=True)
            hub._compute_layout(instant=True, pinned=placed)
        except Exception as exc:  # noqa: BLE001
            _log(f"apply layout: restore/repack raised {exc!r}")
        self.forestChanged.emit()
        _log(
            f"apply layout '{getattr(layout, 'name', '?')}': "
            f"repositioned {applied} cell(s)"
        )

    # ------------------------------------------------------------------
    # Item spawn
    # ------------------------------------------------------------------

    def _spawn_item(self, item: ForestItem) -> None:
        """Bring ``item`` onto the screen as a member of the forest.

        Dispatch:
          * ring  → ``load_ring`` produces a master CellWindow; we
            then attach that master to the forest as a forest-member
            via ``_attach_existing_master_as_member``.
          * tree / tool → reuse the master's ``_drop_spawn_member_
            and_link`` path so the forest behaves identically to
            the way an existing ring absorbs a dropped catalog file.
        """
        try:
            if item.kind == "ring":
                from scriptree.shell.ring_io import load_ring
                ring_master = load_ring(
                    Path(item.path),
                    self._branding,
                    self._registry,
                    self._snap_engine,
                )
                self._attach_existing_master_as_member(ring_master)
                if item.position is not None:
                    ring_master.move(*item.position)
                self._spawned[_norm(item.path)] = ring_master
            else:
                # Tree / tool → use the existing path that drops a
                # catalog onto a master ring.  Same code path the
                # drag-drop UX uses, so behaviour stays consistent.
                # M4 fix: use the id the spawn method now returns
                # instead of guessing the just-added member via
                # ``next(reversed(self._members))`` (fragile coupling
                # to dict insertion order — wrong cell recorded if
                # the method ever added ≠1 member or reused an id).
                new_id = self.forest_window._drop_spawn_member_and_link(
                    Path(item.path)
                )
                if new_id is None:
                    # Defensive: fall back to the old heuristic only
                    # if the spawn returned nothing.
                    new_id = (
                        next(reversed(self.forest_window._members))
                        if self.forest_window._members else None
                    )
                if new_id is not None:
                    cell = self._registry.get(new_id)
                    if cell is not None:
                        if item.position is not None:
                            cell.move(*item.position)
                        self._spawned[_norm(item.path)] = cell
            # v0.6.37 — run layout immediately after each spawn so
            # the new member lands on its honeycomb slot, not at
            # the spawn-time pos (which is typically the master's
            # own pos + offset).  Previously the cell stayed at
            # the spawn pos until SOMETHING ELSE triggered the next
            # _repack_members, which the trace (v0.6.36) showed
            # could be many seconds later — the user perceived
            # this as "started off spaced out / stacked".
            if self.forest_window is not None:
                try:
                    self.forest_window._repack_members(instant=True)
                except Exception as exc:  # noqa: BLE001
                    _log(
                        f"_spawn_item({item.path!r}): "
                        f"post-spawn _repack_members raised {exc!r}"
                    )
        except Exception as exc:  # noqa: BLE001
            _log(f"_spawn_item({item.path!r}): {exc!r}")

    def _resolve_member_overlap(self) -> None:
        """v0.6.11 — repack any forest members whose centres land on
        (or very near) another member's centre.

        v0.6.12 — now a thin delegate to
        ``CellWindow._resolve_member_stacking`` so plain rings get
        the same fix at ``load_ring`` time without duplicating the
        centre-stacking logic.
        """
        forest = self.forest_window
        if forest is None:
            return
        try:
            forest._resolve_member_stacking()
        except Exception as exc:  # noqa: BLE001
            _log(f"_resolve_member_overlap: delegate raised {exc!r}")

    def _attach_existing_master_as_member(self, ring_master: Any) -> None:
        """Make ``ring_master`` a member of the forest's group.

        Mirrors ``_drop_spawn_member_and_link``'s membership wiring
        but for a cell that already exists (the ring master returned
        by ``load_ring``) rather than a freshly-constructed one.
        Triggers a forest repack so the new member lands on a free
        honeycomb slot.
        """
        forest = self.forest_window
        from PySide6.QtCore import QPoint
        # Initial position: next to the forest so the repack has a
        # sensible starting direction.  ``_repack_members`` will
        # immediately move it to a proper slot.
        ring_master.move(
            forest.pos().x() + forest.width() + 12,
            forest.pos().y(),
        )
        forest._members[ring_master._id] = QPoint(ring_master.pos())
        forest._positioned.add(ring_master._id)
        forest._dock_partners.add(ring_master._id)
        ring_master._group_master_id = forest._id
        ring_master._link_parent_id = forest._id  # v0.8.0 P1 mirror
        # Refresh the ring-master's own outline (its
        # _compute_stroke_color is unchanged but the assoc state
        # paint code reads _group_master_id).
        ring_master.update()
        # Repack only the newcomer — pre-existing forest members
        # keep their positions verbatim (per the v0.3.17 "no
        # reshift" contract).
        try:
            existing_ids = {
                mid for mid in forest._members.keys() if mid != ring_master._id
            }
            forest._repack_members(fixed=existing_ids)
        except Exception as exc:  # noqa: BLE001
            _log(f"_attach_existing_master_as_member: repack failed: {exc!r}")

    def _despawn_item(self, item: ForestItem) -> None:
        win = self._spawned.pop(_norm(item.path), None)
        if win is not None:
            try:
                win.close()
            except Exception:  # noqa: BLE001
                pass

    def _on_cell_closed(self, hex_id: str) -> None:
        """A CellWindow somewhere just unregistered itself.

        If the closing cell is one of our spawned forest items AND
        we're NOT in the middle of shutting down, treat it as
        "user wants this item removed from the forest": prune the
        ForestItem from ``self.forest.items``, drop it from
        ``self._spawned``, add the path to ``self.forest.excluded``
        so a subsequent auto-discovery pass doesn't immediately
        re-add it, and mark the forest dirty so the next save
        persists the removal.

        ``self._app_quitting`` short-circuits the prune so the
        shutdown cascade (which closes every cell as the app
        tears down) doesn't wipe the user's whole forest into
        the excluded list -- in that case we want the on-disk
        layout to survive the quit verbatim.

        v0.8.0a25 -- fixes the bug where closing cells, saving,
        quitting, and reloading brought every closed cell back
        because ``save`` never noticed they were gone.
        """
        if self._app_quitting:
            return
        # Find which spawned path corresponds to this hex_id.
        # ``_spawned`` is path -> CellWindow; we want the inverse
        # lookup.  Cells are sparse (a few per forest) so the
        # linear scan is fine.
        target_path: str | None = None
        for path_key, win in list(self._spawned.items()):
            try:
                if getattr(win, "_id", None) == hex_id:
                    target_path = path_key
                    break
            except Exception:  # noqa: BLE001
                continue
        if target_path is None:
            # Not a forest cell (could be a ring member, a standalone
            # not under us, etc.) -- ignore.
            return
        _log(
            f"_on_cell_closed: pruning forest item for hex_id={hex_id} "
            f"path={target_path!r}"
        )
        # Drop the live mapping.
        self._spawned.pop(target_path, None)
        # Remove the ForestItem whose normalised path matches.
        removed: list[str] = []
        new_items: list[ForestItem] = []
        for it in self.forest.items:
            if _norm(it.path) == target_path:
                removed.append(it.path)
                continue
            new_items.append(it)
        self.forest.items = new_items
        # Exclude the path so the next discover_now doesn't suggest
        # re-adding the item -- the user just told us they don't
        # want it.  ``Re-include`` from the Excluded-items dialog
        # is the documented way to bring it back.
        for raw in removed:
            if raw not in self.forest.excluded:
                self.forest.excluded.append(raw)
        if removed:
            self.forestChanged.emit()

    def _on_uninstall_app(self, target: Any) -> None:
        """Confirmation + dispatch for the "Uninstall app..." action.

        ``target`` is either a ``CellWindow`` (the legacy call from
        the Forest right-click submenu, which knows the cell that
        was clicked) OR a string path to a catalog file (the new
        call from the per-item right-click context menu inside the
        cell's popup tree -- there's no specific cell there, just
        the catalog the menu item came from).

        Both paths converge on the same catalog-file path → dialog
        → ``uninstall_app`` pipeline below.  When the call comes
        from a cell, that cell is closed by ``uninstall_app``'s
        ``_spawned`` cleanup; when it comes from a menu item,
        every cell bound to the same catalog (there usually
        isn't one beyond the source cell) is closed via the
        same ``_spawned`` registry lookup.

        Pops a custom dialog with two checkboxes:

          * **Also remove my local saved configurations** -- when
            ticked, deletes every personal sidecar belonging to
            tools in this app folder.  Default ON.
          * **Also remove shared configurations stored with the
            app** -- when ticked, the whole app folder goes,
            sidecars and all.  When unticked, the sidecars are
            copied to a sibling backup folder first.  Default ON.

        Only delegates to ``uninstall_app`` after the user clicks
        the destructive Uninstall button; cancel is a no-op.
        """
        from pathlib import Path
        from PySide6.QtWidgets import (
            QCheckBox, QDialog, QDialogButtonBox, QLabel,
            QVBoxLayout,
        )

        # Accept either a cell OR a raw path string.  When the call
        # comes from the popup-tree right-click filter, ``target``
        # is a string already resolved to the leaf's root catalog.
        if isinstance(target, (str, Path)):
            cat_path = str(target)
        else:
            cat_path = getattr(target, "catalog_path", None)
        if not cat_path:
            return
        app_dir = Path(cat_path).parent

        # Peek at how many local sidecars exist BEFORE the user
        # confirms, so the checkbox label can show a useful count.
        try:
            from scriptree.core.configs import (
                find_personal_configs_for_app,
            )
            local_count = len(
                find_personal_configs_for_app(app_dir)
            )
        except Exception as exc:  # noqa: BLE001
            _log(
                f"_on_uninstall_app: local-count scan failed: {exc!r}"
            )
            local_count = 0
        try:
            shared_count = sum(
                1 for f in app_dir.rglob("*")
                if f.is_file() and (
                    f.name.endswith(".scriptree.configs.json")
                    or f.name.endswith(
                        ".scriptreetree.treeconfigs.json"
                    )
                )
            )
        except Exception:  # noqa: BLE001
            shared_count = 0

        try:
            dlg = QDialog(self.forest_window)
            dlg.setWindowTitle("Uninstall app")
            dlg.setMinimumWidth(520)
            layout = QVBoxLayout(dlg)
            header = QLabel(
                f"Uninstall the app at:\n\n  {app_dir}\n\n"
                f"This will permanently delete the app folder.  "
                f"This cannot be undone."
            )
            header.setWordWrap(True)
            layout.addWidget(header)

            local_label = (
                "Also remove my local saved configurations"
                if local_count == 0 else
                f"Also remove my local saved configurations "
                f"({local_count} file{'s' if local_count != 1 else ''})"
            )
            cb_local = QCheckBox(local_label)
            cb_local.setChecked(True)
            cb_local.setToolTip(
                "Personal sidecars saved under your user "
                "configs folder for this app's tools.  Unchecked "
                "leaves them in place so they reattach on a "
                "future re-install at the same location."
            )
            layout.addWidget(cb_local)

            shared_label = (
                "Also remove shared configurations stored with "
                "the app"
                if shared_count == 0 else
                f"Also remove shared configurations stored with "
                f"the app "
                f"({shared_count} file{'s' if shared_count != 1 else ''})"
            )
            cb_shared = QCheckBox(shared_label)
            cb_shared.setChecked(True)
            cb_shared.setToolTip(
                "Sidecar files ('*.configs.json' / "
                "'*.treeconfigs.json') stored INSIDE the app "
                "folder.  Unchecked copies them to a sibling "
                "'<app>_uninstalled_configs/' folder BEFORE "
                "the app folder is removed."
            )
            layout.addWidget(cb_shared)

            # Custom buttons -- DestructiveRole for the Uninstall
            # button so platforms that style destructive actions
            # (macOS, modern Linux DEs) show it in red.
            buttons = QDialogButtonBox(dlg)
            del_btn = buttons.addButton(
                "Uninstall",
                QDialogButtonBox.ButtonRole.DestructiveRole,
            )
            cancel_btn = buttons.addButton(
                QDialogButtonBox.StandardButton.Cancel,
            )
            cancel_btn.setDefault(True)
            del_btn.clicked.connect(dlg.accept)
            cancel_btn.clicked.connect(dlg.reject)
            layout.addWidget(buttons)

            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            remove_local = cb_local.isChecked()
            remove_shared = cb_shared.isChecked()
        except Exception as exc:  # noqa: BLE001
            _log(f"_on_uninstall_app: dialog failed: {exc!r}")
            return

        ok, msg = self.uninstall_app(
            cat_path,
            remove_local_configs=remove_local,
            remove_shared_configs=remove_shared,
        )
        try:
            if ok:
                QMessageBox.information(
                    self.forest_window, "Uninstall", msg,
                )
            else:
                QMessageBox.warning(
                    self.forest_window, "Uninstall failed", msg,
                )
        except Exception:  # noqa: BLE001
            pass

    def _on_rescue_offscreen(self) -> None:
        """Manual hook for the Forest -> "Bring all cells back on-screen"
        menu action.

        Delegates to ``screen_watcher.rescue_all_cells`` which knows
        how to clamp every registered CellWindow back inside the
        nearest screen's available geometry.  Pops an
        ``information`` box with the count so the user knows
        something happened (or didn't).
        """
        try:
            from scriptree.shell.screen_watcher import rescue_all_cells
            moved = rescue_all_cells()
        except Exception as exc:  # noqa: BLE001
            _log(f"_on_rescue_offscreen: {exc!r}")
            moved = 0
        try:
            QMessageBox.information(
                self.forest_window, "Bring cells on-screen",
                f"Moved {moved} off-screen cell(s) back into view."
                if moved else
                "All cells were already on-screen.",
            )
        except Exception:  # noqa: BLE001
            pass

    def uninstall_app(
        self,
        path: str,
        *,
        remove_local_configs: bool = True,
        remove_shared_configs: bool = True,
    ) -> tuple[bool, str]:
        """Delete the on-disk folder of a forest-tracked app.

        Hard guards to prevent disaster:

          * ``path`` must be a real file (.scriptree or
            .scriptreetree) that currently exists on disk.
          * Its containing folder must be inside either
            ``default_personal_root()`` (per-user install) OR
            ``default_shared_root()`` (in-install ScripTreeApps tree),
            with the parent of the catalog file -- the app's own
            folder -- being a direct or grand-child of one of those
            roots.  Refuse to delete from arbitrary user folders.
          * Refuse to delete the root itself or the app folder when
            the app folder IS one of the install roots (case where
            someone names an app the same as the root by accident).

        Parameters
        ----------
        path:
            The catalog file inside the app folder being
            uninstalled.  Its parent directory IS the app folder.
        remove_local_configs:
            When True (default), every personal sidecar in
            ``get_personal_configs_dir()`` whose ``source_filename``
            matches a tool inside the app folder AND whose
            ``source_locations`` overlaps the app folder is deleted.
            When False, those sidecars are left intact so the user's
            saved personal configurations survive the uninstall and
            line up automatically on a future re-install at the
            same location.
        remove_shared_configs:
            When True (default), the app folder is removed wholesale
            (``shutil.rmtree``), which incidentally also removes the
            shared sidecars (``*.scriptree.configs.json``,
            ``*.scriptreetree.treeconfigs.json``) that live inside
            it.  When False, every shared sidecar inside the app
            folder is first MOVED to a sibling backup directory
            named ``<app_dir>_uninstalled_configs/`` under the same
            install root, and only THEN is the app folder removed.
            The backup folder's path is appended to the success
            message so the user knows where to look.

        Behaviour on success: removes the app's folder via
        ``shutil.rmtree``, drops the ForestItem from
        ``self.forest.items``, adds the path to ``forest.excluded``
        so the next auto-discovery doesn't suggest re-installing
        from a sibling location, and fires ``forestChanged`` so
        autosave persists the removal.

        Returns ``(ok, message)``.  Caller is expected to
        prompt the user with a confirmation dialog BEFORE
        calling this -- ``uninstall_app`` itself does no UI.

        v0.8.0a25 -- initial release (folder delete only).
        v0.8.0a26 -- added ``remove_local_configs`` /
        ``remove_shared_configs`` knobs.
        """
        from pathlib import Path
        import shutil
        from scriptree.core.app_install import (
            default_personal_root, default_shared_root,
        )

        try:
            p = Path(path).resolve()
        except Exception as exc:  # noqa: BLE001
            return False, f"Invalid path: {exc!r}"
        if not p.is_file():
            return False, f"Catalog file not found: {p}"

        app_dir = p.parent
        # Resolve install roots for the containment check.
        roots: list[Path] = []
        for fn in (default_personal_root, default_shared_root):
            try:
                roots.append(Path(fn()).resolve())
            except Exception:  # noqa: BLE001
                continue
        if not roots:
            return False, (
                "Could not resolve the install roots; refusing to "
                "uninstall to avoid deleting the wrong folder."
            )

        # Containment: app_dir must be UNDER one of the roots (not
        # equal to one).  ``relative_to`` raises ValueError when the
        # path isn't a descendant, which we catch.
        chosen_root: Path | None = None
        for root in roots:
            try:
                rel = app_dir.relative_to(root)
            except ValueError:
                continue
            # Reject the empty / root-itself case.
            if len(rel.parts) >= 1:
                chosen_root = root
                break
        if chosen_root is None:
            return False, (
                f"App folder {app_dir} is not under a known install "
                f"root.  Uninstall refused to avoid deleting from "
                f"arbitrary user folders."
            )
        if app_dir.resolve() == chosen_root:
            return False, (
                f"Refusing to delete the install root itself: "
                f"{app_dir}"
            )

        # Drop the ForestItem first so closing the cell windows
        # doesn't re-add them via auto-discovery before the delete.
        norm = _norm(str(p))
        self.forest.items = [
            it for it in self.forest.items
            if _norm(it.path) != norm
        ]
        if str(p) not in self.forest.excluded:
            self.forest.excluded.append(str(p))
        # Close any spawned cell bound to this catalog so the
        # files aren't held open during the rmtree.
        win = self._spawned.pop(norm, None)
        if win is not None:
            try:
                win.close()
            except Exception:  # noqa: BLE001
                pass

        # Find the personal sidecars belonging to this app folder
        # BEFORE we mutate the disk -- we need to walk the app
        # folder for tool files, and that walk obviously can't
        # happen after rmtree.
        try:
            from scriptree.core.configs import (
                find_personal_configs_for_app,
            )
            local_sidecars = find_personal_configs_for_app(app_dir)
        except Exception as exc:  # noqa: BLE001
            _log(f"uninstall_app: local-config scan failed: {exc!r}")
            local_sidecars = []

        # If the user asked us to keep shared configs, snapshot
        # them to a sibling backup folder BEFORE the rmtree.  We
        # name the backup deterministically (same parent, suffix
        # ``_uninstalled_configs``) so the user has somewhere
        # obvious to look.  If the backup folder already exists
        # (a previous uninstall), append a numbered suffix.
        backup_dir: Path | None = None
        if not remove_shared_configs:
            shared_sidecars = [
                f for f in app_dir.rglob("*")
                if f.is_file() and (
                    f.name.endswith(".scriptree.configs.json")
                    or f.name.endswith(
                        ".scriptreetree.treeconfigs.json"
                    )
                )
            ]
            if shared_sidecars:
                base = app_dir.parent / (
                    app_dir.name + "_uninstalled_configs"
                )
                backup_dir = base
                n = 2
                while backup_dir.exists():
                    backup_dir = (
                        app_dir.parent
                        / f"{app_dir.name}_uninstalled_configs-{n}"
                    )
                    n += 1
                try:
                    backup_dir.mkdir(parents=True, exist_ok=False)
                    for sidecar in shared_sidecars:
                        rel = sidecar.relative_to(app_dir)
                        dest = backup_dir / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(sidecar, dest)
                except Exception as exc:  # noqa: BLE001
                    _log(
                        f"uninstall_app: shared-config backup failed: "
                        f"{exc!r}"
                    )
                    return False, (
                        f"Could not back up shared configs to "
                        f"{backup_dir}: {exc!r}.  Refusing to delete "
                        f"app folder because the backup would be "
                        f"incomplete."
                    )

        try:
            shutil.rmtree(app_dir)
        except Exception as exc:  # noqa: BLE001
            return False, f"Delete failed: {exc!r}"

        # Now clean (or keep) the personal sidecars.  Doing this
        # AFTER the rmtree is safe: we already enumerated them
        # above; the rmtree only touched the app folder.
        local_removed = 0
        local_kept = 0
        if local_sidecars:
            if remove_local_configs:
                for sidecar in local_sidecars:
                    try:
                        sidecar.unlink()
                        local_removed += 1
                    except Exception as exc:  # noqa: BLE001
                        _log(
                            f"uninstall_app: failed to delete personal "
                            f"sidecar {sidecar}: {exc!r}"
                        )
            else:
                local_kept = len(local_sidecars)

        self.forestChanged.emit()

        # Compose a human-readable summary line so the post-uninstall
        # toast tells the user what actually happened.
        parts = [f"Uninstalled {app_dir.name} from {chosen_root}."]
        if local_removed:
            parts.append(
                f"Removed {local_removed} local config file(s)."
            )
        if local_kept:
            parts.append(
                f"Kept {local_kept} local config file(s) under "
                f"{local_sidecars[0].parent}."
            )
        if backup_dir is not None:
            parts.append(
                f"Shared configs backed up to {backup_dir}."
            )
        return True, "  ".join(parts)

    # ------------------------------------------------------------------
    # User actions
    # ------------------------------------------------------------------

    def add_item(
        self,
        path: str,
        kind: ItemKind | None = None,
        position: tuple[int, int] | None = None,
    ) -> None:
        """Add ``path`` to the forest and spawn it on-screen.

        Removes ``path`` from the excluded list if present (the user
        explicitly re-included).  Idempotent: adding the same path
        twice is a no-op.
        """
        if kind is None:
            kind = kind_for_suffix(path) or "tool"
        if any(_norm(it.path) == _norm(path) for it in self.forest.items):
            return
        self.forest.excluded = [
            e for e in self.forest.excluded if _norm(e) != _norm(path)
        ]
        item = ForestItem(path=path, kind=kind, position=position)
        self.forest.items.append(item)
        self._spawn_item(item)
        self.forestChanged.emit()

    def remove_item(self, path: str, *, exclude: bool = True) -> None:
        """Remove ``path`` from the forest.  When ``exclude=True``
        the path is added to the excluded list so auto-discovery
        won't silently re-add it; ``exclude=False`` for the case
        where the file was deleted from disk."""
        keep = []
        target = None
        for it in self.forest.items:
            if _norm(it.path) == _norm(path):
                target = it
            else:
                keep.append(it)
        if target is None:
            return
        self.forest.items = keep
        self._despawn_item(target)
        if exclude and _norm(path) not in {
            _norm(e) for e in self.forest.excluded
        }:
            self.forest.excluded.append(path)
        self.forestChanged.emit()

    # ------------------------------------------------------------------
    # Discovery + diff + apply
    # ------------------------------------------------------------------

    def discover_now(self) -> DiscoveryDiff:
        cfg = self.forest.auto_discover
        discovered = discover(cfg.roots, cfg.include, self.forest.excluded)
        # v0.8.0a25+ -- auto-organise pass.  Read each discovered
        # item's ``category`` field (best effort -- I/O failures
        # fall back to "uncategorised") and bucket multiple items
        # sharing a top-level category into one synthesised
        # ``.scriptreetree`` under the personal-apps ``_groups/``
        # directory.  The resulting flat list -- mix of original
        # paths (passthroughs) and synthesised-tree paths -- is
        # then fed to the standard diff machinery.  Orphan synth
        # trees from prior passes (categories the user removed)
        # are pruned at the end.
        try:
            discovered = self._apply_categorize_pass(discovered)
        except Exception as exc:  # noqa: BLE001
            # Best-effort: if the categorise pass blows up for any
            # reason, fall back to the raw discovery list.  The
            # forest still works; the user just sees flat cells
            # for now.  Logged so we can diagnose later.
            import sys
            print(
                f"[forest_controller] categorize pass failed: {exc!r}",
                file=sys.stderr,
            )
        return diff_against(
            self.forest.items, discovered, self.forest.excluded,
        )

    def _apply_categorize_pass(
        self, discovered: list[Any],
    ) -> list[Any]:
        """Run ``group_by_category`` over the discovered list and
        return a new list with synthesised trees substituted for
        the items that got rolled up.

        Implementation detail: ``group_by_category`` works on
        ``GroupCandidate`` records, not ``DiscoveredItem``.  We
        translate, run the pass, then translate the synthesised
        outputs back into ``DiscoveredItem`` shapes the diff
        machinery understands.  Items that pass through unchanged
        keep their original ``DiscoveredItem`` (no translation
        round-trip, so any future fields land safely).
        """
        from pathlib import Path
        from scriptree.core.app_install import default_personal_root
        from scriptree.core.categorize import (
            GroupCandidate, group_by_category, prune_orphan_synthesised,
        )
        from scriptree.core.io import load_tool, load_tree
        from scriptree.shell.forest_discover import DiscoveredItem

        if not discovered:
            return []

        # Map item path -> original DiscoveredItem so we can return
        # passthroughs verbatim without losing kind / catalog_path.
        original_by_path: dict[str, Any] = {
            di.path: di for di in discovered
        }

        # Build GroupCandidate records.  ``category`` and a
        # ``display_name`` come from the catalog; failure to read
        # the catalog (broken JSON, missing file) means we treat
        # it as uncategorised so it still appears in the forest.
        candidates: list[GroupCandidate] = []
        for di in discovered:
            cat = ""
            display = Path(di.path).stem
            try:
                p = Path(di.path)
                if p.suffix.lower() == ".scriptree":
                    tool = load_tool(di.path)
                    cat = getattr(tool, "category", "") or ""
                    display = tool.name or display
                elif p.suffix.lower() == ".scriptreetree":
                    tree = load_tree(di.path)
                    cat = getattr(tree, "category", "") or ""
                    display = tree.name or display
                # .scriptreering: rings carry no category today;
                # they always pass through.
            except Exception:  # noqa: BLE001
                # Unreadable -- best to surface the file in the
                # forest as-is, so the user can see and fix it,
                # rather than swallow it.
                cat = ""
            candidates.append(GroupCandidate(
                path=di.path, category=cat, display_name=display,
            ))

        groups_dir = default_personal_root() / "_groups"

        outcomes = group_by_category(
            candidates,
            output_dir=groups_dir,
            existing_tree_names=self._existing_tree_names(),
        )

        # Translate outcomes back to DiscoveredItem-shaped records.
        new_discovered: list[Any] = []
        kept_synth_paths: set[Path] = set()
        for outcome in outcomes:
            if outcome.kind == "passthrough":
                orig = original_by_path.get(outcome.path)
                if orig is not None:
                    new_discovered.append(orig)
                # If we can't find the original, drop -- shouldn't
                # happen, but never insert a bare path.
            else:
                # synthesised tree -- create a DiscoveredItem record
                # of kind "tree" pointing at the synthesised file.
                p = Path(outcome.path)
                kept_synth_paths.add(p)
                new_discovered.append(DiscoveredItem(
                    path=str(p), kind="tree",
                ))

        # Sweep orphans from prior passes -- a category the user
        # has since removed (or every tool from a category got
        # uninstalled) leaves behind a stale ``.scriptreetree``
        # in _groups/ that no longer appears in
        # ``kept_synth_paths``.  Prune them so the forest doesn't
        # keep showing a ghost cell.
        try:
            prune_orphan_synthesised(
                groups_dir, keep_paths=kept_synth_paths,
            )
        except Exception as exc:  # noqa: BLE001
            import sys
            print(
                f"[forest_controller] orphan prune failed: {exc!r}",
                file=sys.stderr,
            )

        return new_discovered

    def _existing_tree_names(self) -> set[str]:
        """Stems of every ``.scriptreetree`` currently in the
        forest's roots, so the synth pass can avoid colliding
        with a user-authored tree of the same name."""
        from pathlib import Path
        names: set[str] = set()
        for root in self.forest.auto_discover.roots:
            try:
                rp = Path(root)
                if not rp.is_absolute():
                    from scriptree.shell.forest_io import _project_root
                    rp = (_project_root() / rp).resolve()
                if rp.is_dir():
                    for tree in rp.rglob("*.scriptreetree"):
                        names.add(tree.stem)
            except Exception:  # noqa: BLE001
                continue
        return names

    def apply_diff(
        self,
        diff: DiscoveryDiff,
        *,
        accepted_added: set[str] | None = None,
        accepted_removed: set[str] | None = None,
        accepted_reincluded: set[str] | None = None,
    ) -> None:
        norm_added = (
            {_norm(p) for p in accepted_added}
            if accepted_added is not None else None
        )
        norm_removed = (
            {_norm(p) for p in accepted_removed}
            if accepted_removed is not None else None
        )
        norm_reincluded = (
            {_norm(p) for p in accepted_reincluded}
            if accepted_reincluded is not None else None
        )

        for d in diff.added:
            if norm_added is not None and _norm(d.path) not in norm_added:
                continue
            self.add_item(d.path, d.kind)

        for d in diff.previously_excluded:
            if norm_reincluded is not None and _norm(d.path) not in norm_reincluded:
                continue
            self.add_item(d.path, d.kind)

        for it in diff.removed:
            if norm_removed is not None and _norm(it.path) not in norm_removed:
                continue
            self.remove_item(it.path, exclude=False)

    def refresh_from_sources(self) -> None:
        cfg = self.forest.auto_discover
        if not cfg.enabled:
            return
        diff = self.discover_now()
        if diff.is_empty():
            return
        if cfg.update_mode == "auto":
            self.apply_diff(diff)
        elif cfg.update_mode == "prompt":
            self._show_diff_dialog(diff)

    # ------------------------------------------------------------------
    # Save / open
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist the forest to disk.

        Target resolution:
          1. ``self.forest.loaded_from`` — the file the forest was
             opened / saved-as'd to.  Always wins when set.
          2. The configured default forest path — only used as a
             fallback when ``fallback_to_default`` is True in the
             user's preferences.
          3. Otherwise — silent no-op.  The user has explicitly
             opted into a transient in-memory session; writing
             to APPDATA without being told to would surprise them.
        """
        target: Path | None
        if self.forest.loaded_from:
            target = Path(self.forest.loaded_from)
        elif getattr(self, "_preferences", None) is not None and \
                self._preferences.fallback_to_default:
            target = self._preferences.resolved_default_path(self._branding)
        else:
            # Transient session — no target, no write.  ``_dirty``
            # stays True so a future ``save_as`` can pick up the
            # pending changes.
            _log(
                "save: no target (transient forest + fallback off); "
                "skipping write — use Save as… to persist"
            )
            return
        self._sync_positions_into_items()
        save_forest(self.forest, target)
        self._dirty = False

    def save_as(self, path: str | Path) -> None:
        self._sync_positions_into_items()
        save_forest(self.forest, path)
        self.forest.loaded_from = str(Path(path).resolve())
        self._dirty = False

    def open(self, path: str | Path) -> None:
        for it in list(self.forest.items):
            self._despawn_item(it)
        # v0.8.0a83 — opening a DIFFERENT forest replaces the arrangement;
        # drop the previous forest's remembered offsets before loading.
        if self.forest_window is not None:
            self.forest_window._remembered_offsets.clear()
        self.forest = load_forest(path)
        # v0.8.0a46+ -- do NOT stamp ``_derive_label(name)`` here;
        # see the matching note in ``__init__`` for the full
        # rationale.  Opening a different forest file leaves the
        # cell's user-set ``_text_label`` alone (or empty, which
        # falls back to the "Forest" role default in
        # ``_popup_header_text``).
        for it in list(self.forest.items):
            self._spawn_item(it)
        # v0.8.0a83 — restore the opened forest's saved arrangement (remembered
        # offsets), engine-tiling only the cells whose spot doesn't fit.
        self._load_remembered_offsets_into_hub()
        if self.forest_window is not None:
            try:
                _placed = self.forest_window._restore_remembered_offsets(
                    move=True,
                )
                self.forest_window._compute_layout(instant=True, pinned=_placed)
            except Exception as exc:  # noqa: BLE001
                _log(f"open: restore/repack raised {exc!r}")
        self.forestChanged.emit()

    def _load_remembered_offsets_into_hub(self) -> None:
        """Populate the forest hub's ``_remembered_offsets`` from the loaded
        ``ForestItem.rel_offset`` values (v0.8.0a83), keyed by the SAME
        per-cell key the hub uses (``_member_offset_key`` of the spawned
        window), so a later ``_restore_remembered_offsets`` reproduces the
        user's saved arrangement.  Inverse of ``_sync_positions_into_items``.
        """
        hub = self.forest_window
        if hub is None:
            return
        from scriptree.shell.cell_window import _member_offset_key

        for it in self.forest.items:
            if it.rel_offset is None:
                continue
            win = self._spawned.get(_norm(it.path))
            if win is None:
                continue
            key = _member_offset_key(win)
            if key is not None:
                hub._remembered_offsets[key] = (
                    int(it.rel_offset[0]), int(it.rel_offset[1]),
                )

    def _sync_positions_into_items(self) -> None:
        from scriptree.shell.cell_window import _member_offset_key

        hub = self.forest_window
        offs = getattr(hub, "_remembered_offsets", {}) if hub is not None else {}
        for it in self.forest.items:
            win = self._spawned.get(_norm(it.path))
            if win is None:
                continue
            try:
                pt = win.pos()
                it.position = (pt.x(), pt.y())
            except Exception:  # noqa: BLE001
                continue
            # v0.8.0a83 — persist the REMEMBERED offset-from-hub (the user's
            # arrangement) alongside the absolute position, keyed by the SAME
            # per-cell key the hub's _remembered_offsets uses.  Only written
            # when the hub actually holds an offset for this cell, so an item
            # the user never placed keeps rel_offset=None (and the engine tiles
            # it).
            try:
                key = _member_offset_key(win)
                if key is not None and key in offs:
                    ox, oy = offs[key]
                    it.rel_offset = (int(ox), int(oy))
            except Exception:  # noqa: BLE001
                pass

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _schedule_autosave(self) -> None:
        """Restart the autosave debounce timer.  Fires
        ``_autosave_flush`` ~250 ms after the last change."""
        if not self._autosave_enabled:
            return
        # Restart on each change so bursts coalesce.
        self._autosave_timer.start()

    def _autosave_flush(self) -> None:
        """Debounce target.  Writes the forest to disk if dirty,
        swallowing any errors so a transient I/O failure doesn't
        crash the GUI."""
        if not self._dirty:
            return
        if not self._autosave_enabled:
            return
        try:
            self.save()
        except Exception as exc:  # noqa: BLE001
            _log(f"autosave: save failed: {exc!r}")

    def flush_if_dirty(self) -> None:
        """Synchronous flush — used at process exit to make sure
        no pending change is lost when the debounce timer never
        gets to fire.

        v0.8.0a25 -- also flips ``_app_quitting`` to True so the
        ``hexagonClosed`` handler stops pruning forest items as
        the cells cascade-close during shutdown.  Without this
        flag flip, every cell that closes during the quit would
        be added to ``forest.excluded`` AFTER the save here, but
        that mutation never reaches disk so it's harmless --
        defense-in-depth in case any future save path runs
        after this point.

        L7 fix: when the session is transient (no ``loaded_from`` and
        ``fallback_to_default`` off) ``save()`` is a deliberate
        no-op — but at process exit that silently discarded the
        user's whole forest with only a stderr line.  Here, at the
        last possible moment, surface it: offer Save As… / Discard
        instead of vanishing the work."""
        # Tell the hexagonClosed handler we're shutting down so the
        # cascade of cell closes during quit doesn't add every cell
        # to forest.excluded.
        self._app_quitting = True
        if not self._dirty:
            return
        try:
            self.save()
        except Exception as exc:  # noqa: BLE001
            _log(f"flush_if_dirty: save failed: {exc!r}")
        # Still dirty after save() ⇒ the transient no-op branch ran
        # (or the write failed).  Only prompt when there's actually
        # something to lose and no file target exists.
        if not self._dirty or not self.forest.items:
            return
        if self.forest.loaded_from:
            return  # had a target; a real write failure already logged
        # v0.6.9 — the forest started empty with no file loaded and
        # the user never did Save As.  Per user direction: don't ask
        # WHERE or for a filename — just offer Personal vs Shared,
        # write to that fixed default-load spot, and remember it so
        # next launch loads it automatically without asking.
        try:
            personal = default_autoload_path(self._branding)
            shared = shared_autoload_path(self._branding)
            box = QMessageBox(self.forest_window)
            box.setWindowTitle("Save this forest?")
            box.setIcon(QMessageBox.Icon.Question)
            box.setText(
                f"This forest has {len(self.forest.items)} item(s) "
                "but hasn't been saved to a file.\n\n"
                "Save it as your default forest so it loads "
                "automatically next time?"
            )
            box.setInformativeText(
                f"Personal:  {personal}\n"
                f"Shared:  {shared}"
            )
            personal_btn = box.addButton(
                "Personal", QMessageBox.ButtonRole.AcceptRole
            )
            shared_btn = box.addButton(
                "Shared", QMessageBox.ButtonRole.AcceptRole
            )
            discard_btn = box.addButton(
                "Don't save", QMessageBox.ButtonRole.DestructiveRole
            )
            box.setDefaultButton(personal_btn)
            box.exec()
            clicked = box.clickedButton()
            if clicked is discard_btn or clicked is None:
                return
            target = personal if clicked is personal_btn else shared
            self._save_as_default(target)
        except Exception as exc:  # noqa: BLE001
            # Never let the exit-time guard itself block shutdown.
            _log(f"flush_if_dirty: transient-save prompt failed: {exc!r}")

    def _save_as_default(self, target: "Path") -> None:
        """Write the forest to ``target`` (a fixed personal/shared
        default path — no filename/dir prompt) and record it as the
        auto-load default for next launch.

        Mirrors ``save_as`` for the write, then additionally persists
        ``ForestPreferences`` so ``fallback_to_default`` is on and
        ``default_forest_path`` points here — that's what makes it
        "the default to load next time without asking"."""
        target = Path(target)
        self.save_as(target)
        try:
            if getattr(self, "_preferences", None) is None:
                self._preferences = load_preferences(self._branding)
            self._preferences.fallback_to_default = True
            self._preferences.default_forest_path = str(target)
            save_preferences(self._preferences, self._branding)
            _log(
                f"_save_as_default: saved {target} and set it as the "
                "auto-load default"
            )
        except Exception as exc:  # noqa: BLE001
            _log(f"_save_as_default: preference persist failed: {exc!r}")

    def get_preferences(self) -> ForestPreferences:
        """Return a snapshot of the user's launch preferences.

        v0.8.0a52+ -- the snapshot now carries the three
        visibility flags (``show_always_on_top``,
        ``show_on_taskbar``, ``show_in_system_tray``) so the
        settings dialog and Visibility submenu can edit them
        without having to read prefs from disk again.
        """
        if getattr(self, "_preferences", None) is None:
            self._preferences = load_preferences(self._branding)
        # Return a copy so callers can mutate without aliasing.
        return ForestPreferences(
            fallback_to_default=self._preferences.fallback_to_default,
            default_forest_path=self._preferences.default_forest_path,
            show_always_on_top=self._preferences.show_always_on_top,
            show_on_taskbar=self._preferences.show_on_taskbar,
            show_in_system_tray=self._preferences.show_in_system_tray,
            autostart_scope=self._preferences.autostart_scope,
        )

    def update_preferences(self, prefs: ForestPreferences) -> None:
        """Persist ``prefs`` to disk, update the cached copy, AND
        re-apply visibility live.

        Launch defaults (``fallback_to_default``,
        ``default_forest_path``) only kick in at the next launch.
        Visibility flags, however, apply immediately via the
        attached ``ForestVisibilityManager`` -- toggling
        ``show_in_system_tray`` from the settings dialog spawns
        / tears down the tray icon right away rather than
        forcing a restart.
        """
        # Repair degenerate "all three visibility flags False"
        # before we write -- the UI should already prevent this
        # but defence in depth is cheap.
        prefs = prefs.normalised()
        save_preferences(prefs, self._branding)
        self._preferences = ForestPreferences(
            fallback_to_default=prefs.fallback_to_default,
            default_forest_path=prefs.default_forest_path,
            show_always_on_top=prefs.show_always_on_top,
            show_on_taskbar=prefs.show_on_taskbar,
            show_in_system_tray=prefs.show_in_system_tray,
            autostart_scope=prefs.autostart_scope,
        )
        # Apply visibility live so the user sees the result of
        # their toggle without restarting ScripTree.
        if self._visibility is not None:
            try:
                self._visibility.apply(self._preferences)
            except Exception as exc:  # noqa: BLE001
                _log(f"update_preferences: visibility.apply failed: {exc!r}")

    def _finalize_hub_interactive(self) -> None:
        """a63: make the freshly-shown forest hub fully interactive.

        User-reported: at startup the forest hub could not be dragged
        until the user manually hid and re-showed it.

        The startup show path was the ONLY reveal path that never
        raised / activated the hub -- every ``show_hub`` and
        taskbar-restore reveal calls ``raise_()`` + ``activateWindow()``.
        A frameless ``Qt.Tool`` window shown without activation can
        fail to pick up the first drag gesture on Windows until it
        gains activation; the hide/show the user did was, in effect,
        that activation.  We replicate it here, scheduled one
        event-loop tick after the initial show (via
        ``QTimer.singleShot(0, ...)`` in ``start()``) so it runs after
        Qt finishes the first map and the fade-in -- no visible
        flicker.

        Guarded to act ONLY when the hub is actually shown and not
        minimised:
          * taskbar mode starts the hub minimised -- a taskbar click
            later restores + activates it through
            ``_restore_descendants``;
          * tray-only mode starts it hidden -- the tray click reveals
            it through ``show_hub`` (which already activates).
        So the only case this finalise touches is the always-on-top
        hub the user sees floating at startup -- exactly the surface
        they reported as unmovable.
        """
        w = self.forest_window
        if w is None:
            return
        try:
            visible = bool(w.isVisible())
            minimized = bool(w.isMinimized())
            if visible and not minimized:
                w.raise_()
                w.activateWindow()
            # Diagnostic: a persistent movability regression can now be
            # read straight from the debug log (Forest -> Debug ->
            # Enable verbose logging) instead of guessed at.
            try:
                flags = f"0x{int(w.windowFlags()):X}"
            except Exception:  # noqa: BLE001
                flags = "?"
            try:
                active = bool(w.isActiveWindow())
            except Exception:  # noqa: BLE001
                active = False
            _log(
                "[forest_startup] hub finalize: "
                f"visible={visible} min={minimized} active={active} "
                f"flags={flags}"
            )
        except Exception as exc:  # noqa: BLE001
            _log(f"_finalize_hub_interactive: {exc!r}")

    def _on_visibility_quit(self) -> None:
        """Terminate ScripTree when the user dismisses the taskbar
        host or picks Quit from the tray menu.

        Flushes any pending autosave first so we don't lose the
        last sub-debounce change.  Then asks the QApplication to
        quit, which cascades through the normal shutdown
        machinery (cell windows close, settings persist, etc.).
        """
        try:
            self.flush_if_dirty()
        except Exception as exc:  # noqa: BLE001
            _log(f"_on_visibility_quit: flush_if_dirty raised {exc!r}")
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                app.quit()
        except Exception as exc:  # noqa: BLE001
            _log(f"_on_visibility_quit: app.quit failed: {exc!r}")

    def set_autosave_enabled(self, enabled: bool) -> None:
        """Toggle auto-save at runtime.  Disabling stops the
        debounce timer but doesn't clear the dirty flag — a future
        manual ``save()`` or re-enable still picks up pending
        changes."""
        self._autosave_enabled = bool(enabled)
        if not self._autosave_enabled:
            self._autosave_timer.stop()

    # ------------------------------------------------------------------
    # Menu action handlers (wired via _populate_forest_menu)
    # ------------------------------------------------------------------

    def _on_save_as(self) -> None:
        target, _ = QFileDialog.getSaveFileName(
            self.forest_window, "Save forest as",
            str(default_autoload_path(self._branding)),
            "ScripTree forest (*.scriptreeforest)",
        )
        if target:
            self.save_as(target)

    def _on_open(self) -> None:
        target, _ = QFileDialog.getOpenFileName(
            self.forest_window, "Open forest",
            "",
            "ScripTree forest (*.scriptreeforest)",
        )
        if target:
            self.open(target)

    def _on_autoadd_now(self) -> None:
        diff = self.discover_now()
        if diff.is_empty():
            QMessageBox.information(
                self.forest_window, "Auto-add",
                "Forest is already up to date — nothing to add.",
            )
        else:
            self._show_diff_dialog(diff)

    def _on_about(self) -> None:
        cfg = self.forest.auto_discover
        QMessageBox.information(
            self.forest_window, "Forest",
            f"<b>{self.forest.name}</b><br><br>"
            f"Items: {len(self.forest.items)}<br>"
            f"Excluded: {len(self.forest.excluded)}<br>"
            f"Auto-discover: "
            f"{'enabled' if cfg.enabled else 'disabled'} "
            f"({cfg.update_mode})<br>"
            f"Roots: {', '.join(cfg.roots) or '(none)'}<br>"
            f"<br>"
            f"File: {self.forest.loaded_from or '(unsaved)'}",
        )

    # ------------------------------------------------------------------
    # Login autostart (v0.8.0a84)
    # ------------------------------------------------------------------

    def _on_forest_autostart_set(self, scope: str) -> None:
        """Handle "Auto-load on startup → <scope>" (a84).

        Forest analog of the ring's ``_autoload_set_scope`` /
        ``_autoload_disable``.  *scope* ∈ ``{"off","user","system"}``.

        Admin / Run-key rules (the single Run-key value per scope is written by
        ``ring_io.recompute_autostart``; HKLM writes need admin):
          * ``"off"`` from system, not admin → drop HKLM via a UAC-elevated
            child (``elevate_for_forest_autostart_disable_system``); else
            ``disable_forest_autostart`` clears both scopes here.
          * ``"user"`` / ``"system"`` → the forest must be SAVED (have a
            ``loaded_from``) so the login ``--forest`` process has a real file;
            prompt to Save-As if transient.
          * ``"system"`` not admin → elevate (enable system).
          * ``"user"`` coming FROM system, not admin → elevate (the HKLM drop
            needs admin even though the HKCU add does not).
          * otherwise write here via ``set_forest_autostart``.

        The elevated child re-derives prefs from disk and owns the registry
        write; the parent flips its cached scope optimistically so THIS
        process's menu stays consistent until the next launch reloads prefs
        (eventual consistency — same model the ring uses).
        """
        from pathlib import Path
        from PySide6.QtWidgets import QMessageBox
        from scriptree.shell.ring_io import (
            _is_admin,
            elevate_for_forest_autostart_system,
            elevate_for_forest_autostart_user,
            elevate_for_forest_autostart_disable_system,
        )
        from scriptree.shell.forest_io import (
            set_forest_autostart, disable_forest_autostart, load_preferences,
        )

        if scope not in ("off", "user", "system"):
            return
        old_scope = self.get_preferences().autostart_scope
        if scope == old_scope:
            return  # re-selecting the active state — nothing to do

        # ---- Disable ----------------------------------------------------
        if scope == "off":
            if old_scope == "system" and not _is_admin():
                # Only flip the cached scope if the elevation actually
                # LAUNCHED — a cancelled UAC prompt (ShellExecuteW ≤ 32 →
                # False) wrote nothing, so flipping would make the menu lie
                # until the next relaunch.
                if elevate_for_forest_autostart_disable_system():
                    self._optimistic_autostart_flip("off")
                return
            try:
                disable_forest_autostart(self._branding)
            except Exception as exc:  # noqa: BLE001
                _log(f"_on_forest_autostart_set(off): {exc!r}")
                QMessageBox.warning(
                    self.forest_window, "Auto-load on startup",
                    f"Could not disable auto-load:\n{exc}",
                )
                return
            self._preferences = load_preferences(self._branding)
            return

        # ---- Enable (user / system) — require a saved forest ------------
        forest_path = self.forest.loaded_from
        if not forest_path:
            reply = QMessageBox.question(
                self.forest_window, "Save required",
                "Save this forest to a file first, then enable auto-load "
                "on startup?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._on_save_as()
                forest_path = self.forest.loaded_from
            if not forest_path:
                return  # cancelled or still unsaved

        # ---- Elevation paths (HKLM writes need admin) -------------------
        if scope == "system" and not _is_admin():
            # Flip only if the elevation launched (UAC not cancelled).
            if elevate_for_forest_autostart_system(Path(forest_path)):
                self._optimistic_autostart_flip("system", str(forest_path))
            return
        if scope == "user" and old_scope == "system" and not _is_admin():
            if elevate_for_forest_autostart_user(Path(forest_path)):
                self._optimistic_autostart_flip("user", str(forest_path))
            return

        # ---- Write here (user, or system-with-admin) --------------------
        try:
            set_forest_autostart(scope, self._branding, forest_path=str(forest_path))
        except Exception as exc:  # noqa: BLE001
            _log(f"_on_forest_autostart_set({scope}): {exc!r}")
            QMessageBox.warning(
                self.forest_window, "Auto-load on startup",
                f"Could not enable auto-load:\n{exc}",
            )
            return
        self._preferences = load_preferences(self._branding)

    def _optimistic_autostart_flip(self, scope: str, forest_path: str | None = None) -> None:
        """Flip the CACHED autostart fields without touching disk/registry.

        Used after handing a registry change to a UAC-elevated child: the child
        owns the disk + Run-key write, but this (unelevated) process can't read
        its result synchronously, so we update only the in-memory cache to keep
        the menu checkmarks consistent.  The next launch reloads prefs from disk
        (written by the child), reconciling any drift.  Deliberately does NOT
        call ``update_preferences`` / ``save_preferences`` — that would race the
        child and try to recompute the Run-key from an unelevated process.

        For an ENABLE flip we also mirror the ``default_forest_path`` +
        ``fallback_to_default`` the child will write, so that if the user
        immediately clicks Save (which DOES persist the cache via
        ``update_preferences``) the parent's write stays consistent with the
        child's instead of clobbering the configured forest path.
        """
        prefs = self.get_preferences()  # a copy
        prefs.autostart_scope = scope if scope in ("off", "user", "system") else "off"
        if scope in ("user", "system") and forest_path:
            from pathlib import Path
            prefs.default_forest_path = str(Path(forest_path).expanduser().resolve())
            prefs.fallback_to_default = True
        self._preferences = prefs

    # ------------------------------------------------------------------
    # Dialog stubs
    # ------------------------------------------------------------------

    def _show_first_run_dialog(self) -> None:
        from scriptree.shell.forest_dialogs import FirstRunDialog
        FirstRunDialog(self).exec()

    def _show_diff_dialog(self, diff: DiscoveryDiff) -> None:
        from scriptree.shell.forest_dialogs import UpdateDiffDialog
        UpdateDiffDialog(self, diff).exec()

    def _show_settings_dialog(self) -> None:
        from scriptree.shell.forest_dialogs import ForestSettingsDialog
        ForestSettingsDialog(self).exec()

    def _show_excluded_dialog(self) -> None:
        from scriptree.shell.forest_dialogs import ExcludedItemsDialog
        ExcludedItemsDialog(self).exec()
