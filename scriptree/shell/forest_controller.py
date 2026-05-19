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
)
from scriptree.shell.forest_discover import (
    DiscoveredItem, DiscoveryDiff, diff_against, discover,
)


def _log(msg: str) -> None:
    print(f"[forest_controller] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_label(name: str) -> str:
    """1-3 char abbreviation of a forest's name for the cell label."""
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
        from scriptree.shell.cell_window import CellWindow
        self.forest_window = CellWindow(
            self._branding,
            role="master",
            is_forest_master=True,
        )
        # Use the forest's name as the cell's text label.  This goes
        # through the standard ``apply_label_change`` so it persists
        # via the same machinery as user-set labels.
        try:
            self.forest_window.apply_label_change(
                text_label=_derive_label(self.forest.name),
            )
        except Exception:  # noqa: BLE001
            self.forest_window._text_label = _derive_label(self.forest.name)

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
                ic_data = bundled_icon_b64("folder")
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

        # Position.  Default is top-centre-ish; restore the user's
        # last placement when the autoloaded forest carried one.
        if position is None:
            stored = getattr(self.forest, "_window_position", None)
            if stored is not None:
                position = QPoint(*stored)
            else:
                from PySide6.QtGui import QGuiApplication
                screen = QGuiApplication.primaryScreen()
                if screen is not None:
                    geo = screen.availableGeometry()
                    cx = geo.center().x() - self.forest_window.width() // 2
                    top = geo.top() + 24
                    position = QPoint(cx, top)
                else:
                    position = QPoint(100, 100)
        self.forest_window.move(position)
        self.forest_window.show()

        # Install the menu hook now that the cell exists.
        self._install_menu_hook(self.forest_window)

        # Spawn items.
        for it in list(self.forest.items):
            self._spawn_item(it)

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

    # ------------------------------------------------------------------
    # Menu hook
    # ------------------------------------------------------------------

    def _install_menu_hook(self, cell: Any) -> None:
        """Register the forest-specific menu items on ``cell``'s
        right-click menu.  Uses the ``_forest_menu_extension`` hook
        added to ``CellWindow._show_context_menu`` in v0.3.15."""
        cell._forest_menu_extension = self._populate_forest_menu

    def _populate_forest_menu(self, menu: QMenu) -> None:
        """Insert forest-specific actions at the top of ``menu``.

        Layout: a ``Forest`` submenu so the standard cell menu stays
        readable.  All actions wire to controller methods directly
        (no signal hops, simpler debug).
        """
        forest_menu = QMenu("Forest", menu)
        a_save = forest_menu.addAction("Save forest")
        a_save_as = forest_menu.addAction("Save forest as…")
        a_open = forest_menu.addAction("Open forest…")
        forest_menu.addSeparator()
        a_refresh = forest_menu.addAction("Refresh from sources")
        a_autoadd = forest_menu.addAction("Auto-add from ScripTreeApps now")
        forest_menu.addSeparator()
        a_settings = forest_menu.addAction("Forest settings…")
        a_excluded = forest_menu.addAction("Manage excluded items…")
        forest_menu.addSeparator()
        a_about = forest_menu.addAction("About this forest")

        a_save.triggered.connect(self.save)
        a_save_as.triggered.connect(self._on_save_as)
        a_open.triggered.connect(self._on_open)
        a_refresh.triggered.connect(self.refresh_from_sources)
        a_autoadd.triggered.connect(self._on_autoadd_now)
        a_settings.triggered.connect(self._show_settings_dialog)
        a_excluded.triggered.connect(self._show_excluded_dialog)
        a_about.triggered.connect(self._on_about)

        # Insert the submenu at the top of the parent menu so the
        # forest items are reachable without scrolling past every
        # standard cell action.
        first = menu.actions()[0] if menu.actions() else None
        menu.insertMenu(first, forest_menu)

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
        except Exception as exc:  # noqa: BLE001
            _log(f"_spawn_item({item.path!r}): {exc!r}")

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
        return diff_against(
            self.forest.items, discovered, self.forest.excluded,
        )

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
        self.forest = load_forest(path)
        if self.forest_window is not None:
            try:
                self.forest_window.apply_label_change(
                    text_label=_derive_label(self.forest.name),
                )
            except Exception:  # noqa: BLE001
                pass
        for it in list(self.forest.items):
            self._spawn_item(it)
        self.forestChanged.emit()

    def _sync_positions_into_items(self) -> None:
        for it in self.forest.items:
            win = self._spawned.get(_norm(it.path))
            if win is None:
                continue
            try:
                pt = win.pos()
                it.position = (pt.x(), pt.y())
            except Exception:  # noqa: BLE001
                continue

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

        L7 fix: when the session is transient (no ``loaded_from`` and
        ``fallback_to_default`` off) ``save()`` is a deliberate
        no-op — but at process exit that silently discarded the
        user's whole forest with only a stderr line.  Here, at the
        last possible moment, surface it: offer Save As… / Discard
        instead of vanishing the work."""
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
        try:
            reply = QMessageBox.question(
                self.forest_window,
                "Unsaved forest",
                f"This forest has {len(self.forest.items)} item(s) "
                "and is running as a transient (in-memory) session — "
                "it will NOT be saved automatically.\n\n"
                "Save it to a file before exiting?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard,
                QMessageBox.StandardButton.Save,
            )
            if reply == QMessageBox.StandardButton.Save:
                path, _ = QFileDialog.getSaveFileName(
                    self.forest_window, "Save forest as",
                    "forest.scriptreeforest",
                    "ScripTree forest (*.scriptreeforest)",
                )
                if path:
                    self.save_as(path)
        except Exception as exc:  # noqa: BLE001
            # Never let the exit-time guard itself block shutdown.
            _log(f"flush_if_dirty: transient-save prompt failed: {exc!r}")

    def get_preferences(self) -> ForestPreferences:
        """Return a snapshot of the user's launch preferences."""
        if getattr(self, "_preferences", None) is None:
            self._preferences = load_preferences(self._branding)
        # Return a copy so callers can mutate without aliasing.
        return ForestPreferences(
            fallback_to_default=self._preferences.fallback_to_default,
            default_forest_path=self._preferences.default_forest_path,
        )

    def update_preferences(self, prefs: ForestPreferences) -> None:
        """Persist ``prefs`` to disk and update the controller's
        cached copy.  Doesn't change the currently-loaded forest —
        the new settings apply at the next launch."""
        save_preferences(prefs, self._branding)
        self._preferences = ForestPreferences(
            fallback_to_default=prefs.fallback_to_default,
            default_forest_path=prefs.default_forest_path,
        )

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
