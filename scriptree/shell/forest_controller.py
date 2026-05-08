"""
forest_controller.py — orchestrates the forest singleton.

Responsibilities:

  * Owns the live ``ForestDef`` (the data model).
  * Owns the ``ForestWindow`` (the visible cell on screen).
  * Spawns / despawns rings, trees, and tools the forest tracks —
    delegates the actual work to ``load_ring`` and the standalone-
    cell construction path that ``ring_main`` already uses.
  * Handles auto-discovery + diff + apply (auto / prompt / off).
  * Handles right-click menu actions.
  * Persists state to the per-user autoload file on every meaningful
    change so a crashed session can be restored.

Why a controller, not just a state class?
-----------------------------------------
The forest sits between two layers that already exist (CellRegistry
+ SnapEngine + load_ring on one side, the user's intent on the
other), so it's natural for the orchestration code to live in its
own object that holds references to both.  This also gives us a
clean test boundary — unit tests can construct the controller with
a fake registry / branding and exercise discovery → diff → apply
without spinning up a full Qt app.

Public API
----------
    ForestController(branding, registry, snap_engine=None)

    .start(forest=None) → None
        Construct the visible cell, bind the forest, spawn its
        items.  Pass ``forest=None`` to autoload the per-user
        last_forest.scriptreeforest (or start empty if none).

    .save() / .save_as(path) → None
    .open(path) → None
    .refresh_from_sources() → None
    .open_settings() → None
    .add_item(path, kind, position=None) → None
    .remove_item(path, *, exclude=True) → None
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QPoint, Signal
from PySide6.QtWidgets import QMenu

from scriptree.shell.forest_io import (
    AutoDiscoverConfig, ForestDef, ForestItem, ItemKind,
    default_autoload_path, kind_for_suffix, list_autoload_forest,
    load_forest, save_forest,
)
from scriptree.shell.forest_discover import (
    DiscoveredItem, DiscoveryDiff, diff_against, discover,
)
from scriptree.shell.forest_window import ForestWindow


def _log(msg: str) -> None:
    print(f"[forest_controller] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Helper — derive a 1-3 char label for the forest cell from its name.
# ---------------------------------------------------------------------------

def _derive_label(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "F"
    parts = [p for p in name.split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    if len(name) >= 2:
        return name[:2].title()
    return name[0].upper()


# ---------------------------------------------------------------------------
# ForestController
# ---------------------------------------------------------------------------

class ForestController(QObject):
    """Singleton-ish orchestrator for the forest layer.

    Construct exactly one per ScripTreeRing process when running in
    forest mode.  ``ring_main.main`` calls ``start()`` after the
    QApplication is built and the registry / snap engine are wired.
    """

    forestChanged = Signal()
    """Emitted whenever the in-memory ``ForestDef`` changes (item
    added, item removed, settings altered).  The controller's
    ``save_state`` slot listens to this to keep the autoload file
    in sync."""

    def __init__(
        self,
        branding: dict,
        registry: Any,            # CellRegistry — Any to avoid import cycle
        snap_engine: Any = None,  # SnapEngine | None
    ) -> None:
        super().__init__()
        self._branding = branding
        self._registry = registry
        self._snap_engine = snap_engine
        self.forest: ForestDef = ForestDef()
        self.forest_window: ForestWindow | None = None
        # path → (CellWindow master) for items we've spawned, so
        # remove_item can find what to close.
        self._spawned: dict[str, Any] = {}
        # Persist debounce — avoid hammering the autoload file on
        # every drag-step.
        self._dirty: bool = False
        self.forestChanged.connect(self._mark_dirty)

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
        """Bind a forest, spawn its items, show the visible cell.

        ``forest=None`` means "autoload from the per-user last
        forest, or start with an empty default if none exists".

        ``suppress_first_run=True`` skips the empty-forest welcome
        dialog.  Used by tests (which would otherwise hang on the
        modal exec) and by callers who want to set up the forest
        programmatically before showing UI.
        """
        if forest is None:
            forest = list_autoload_forest(self._branding)
        if forest is None:
            forest = ForestDef()
        self.forest = forest

        # Build the visible cell.
        self.forest_window = ForestWindow(self._branding, controller=self)
        self.forest_window.set_label(_derive_label(self.forest.name))
        if position is not None:
            self.forest_window.move(position)
        else:
            # Default position: top-centre-ish so it doesn't collide
            # with cells that typically appear near the centre.
            from PySide6.QtGui import QGuiApplication
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                cx = geo.center().x() - self.forest_window.width() // 2
                top = geo.top() + 24
                self.forest_window.move(cx, top)

        # Wire signals.
        self.forest_window.rightClicked.connect(self._on_right_click)
        self.forest_window.moved.connect(lambda _p: self._mark_dirty())

        self.forest_window.show()
        self.forest_window.raise_()

        # Spawn items.
        for it in list(self.forest.items):
            self._spawn_item(it)

        # First-run check: empty forest + no autoload file → show
        # the populate prompt so the user isn't staring at a blank
        # screen with one cryptic green polygon.
        if (
            not suppress_first_run
            and not self.forest.items
            and self.forest.loaded_from is None
        ):
            # Defer to next event loop tick so the visible cell has
            # a chance to paint before the modal dialog appears.
            from PySide6.QtCore import QTimer
            QTimer.singleShot(50, self._show_first_run_dialog)

    # ------------------------------------------------------------------
    # Item spawn / despawn
    # ------------------------------------------------------------------

    def _spawn_item(self, item: ForestItem) -> None:
        """Bring ``item`` onto the screen.

        Dispatch:
          * ring  → ``load_ring`` (full master + member spawn)
          * tree / tool → standalone cell bound to the catalog,
            positioned where the forest item said.
        """
        try:
            if item.kind == "ring":
                from scriptree.shell.ring_io import load_ring
                master = load_ring(
                    Path(item.path),
                    self._branding,
                    self._registry,
                    self._snap_engine,
                )
                # Override master position if the forest item had
                # a stored placement (rings track their own
                # member positions internally).
                if item.position is not None:
                    master.move(*item.position)
                self._spawned[_norm(item.path)] = master
            else:
                # Tree / tool — spawn one standalone cell, bind catalog.
                from scriptree.shell.cell_window import CellWindow
                cell = CellWindow(self._branding)
                cell.show()
                if item.position is not None:
                    cell.move(*item.position)
                # Bind the catalog so the cell shows the right tools.
                catalog = item.catalog_path or item.path
                if hasattr(cell, "_open_catalog_path"):
                    cell._open_catalog_path(catalog)
                else:
                    cell._catalog_path = catalog
                    if hasattr(cell, "_refresh_label_from_catalog"):
                        cell._refresh_label_from_catalog()
                self._spawned[_norm(item.path)] = cell
        except Exception as exc:  # noqa: BLE001
            _log(f"_spawn_item({item.path!r}): failed: {exc!r}")

    def _despawn_item(self, item: ForestItem) -> None:
        """Close any cells/rings spawned for ``item``."""
        win = self._spawned.pop(_norm(item.path), None)
        if win is not None:
            try:
                win.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # User actions — additions / removals
    # ------------------------------------------------------------------

    def add_item(
        self,
        path: str,
        kind: ItemKind | None = None,
        position: tuple[int, int] | None = None,
    ) -> None:
        """Add ``path`` to the forest and spawn it on screen.

        ``kind`` defaults to whatever ``kind_for_suffix(path)`` says.
        If ``path`` was previously excluded the entry is removed
        from the excluded list (the user explicitly re-included it).
        """
        if kind is None:
            kind = kind_for_suffix(path) or "tool"
        # De-duplicate: don't add the same path twice.
        if any(_norm(it.path) == _norm(path) for it in self.forest.items):
            return
        # Re-include: clear from excluded list.
        self.forest.excluded = [
            e for e in self.forest.excluded if _norm(e) != _norm(path)
        ]
        item = ForestItem(path=path, kind=kind, position=position)
        self.forest.items.append(item)
        self._spawn_item(item)
        self.forestChanged.emit()

    def remove_item(self, path: str, *, exclude: bool = True) -> None:
        """Remove ``path`` from the forest.

        ``exclude=True`` (default) adds the path to ``excluded`` so
        auto-discovery doesn't silently re-add it on the next pass.
        ``exclude=False`` is for the case where the file was
        deleted from disk — we don't want to remember it as
        "excluded by user choice" because the user didn't choose
        anything.
        """
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
        if exclude and not _norm(path) in {_norm(e) for e in self.forest.excluded}:
            self.forest.excluded.append(path)
        self.forestChanged.emit()

    # ------------------------------------------------------------------
    # Auto-discovery + diff + apply
    # ------------------------------------------------------------------

    def discover_now(self) -> DiscoveryDiff:
        """Run the discovery walker against the configured roots and
        return a diff against the current forest.  Doesn't apply
        anything — the caller decides what to do with the result."""
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
        """Apply the parts of ``diff`` the user accepted.

        ``accepted_*`` are sets of normalised paths.  ``None`` means
        "accept all of that bucket" — used by ``update_mode='auto'``
        which doesn't surface a UI.  Callers wanting fine-grained
        control (the prompt dialog) pass per-row checkbox results.
        """
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

        # Apply additions.
        for d in diff.added:
            if norm_added is not None and _norm(d.path) not in norm_added:
                continue
            self.add_item(d.path, d.kind)

        # Apply re-inclusions.
        for d in diff.previously_excluded:
            if norm_reincluded is not None and _norm(d.path) not in norm_reincluded:
                continue
            self.add_item(d.path, d.kind)

        # Apply removals — these are items that disappeared from
        # disk, so don't add to excluded (the user didn't choose to
        # remove; the file went away on its own).
        for it in diff.removed:
            if norm_removed is not None and _norm(it.path) not in norm_removed:
                continue
            self.remove_item(it.path, exclude=False)

    def refresh_from_sources(self) -> None:
        """Run discovery and apply per the configured update mode.

        ``off``    — no-op (caller should use a manual button if they
                     want one-off discovery).
        ``auto``   — apply all changes silently.
        ``prompt`` — show the diff dialog if the diff is non-empty.
        """
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
        # "off" — never reaches here

    # ------------------------------------------------------------------
    # Save / open
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Save to the forest's existing path, or to the autoload
        file if no explicit save target was set."""
        target: Path
        if self.forest.loaded_from:
            target = Path(self.forest.loaded_from)
        else:
            target = default_autoload_path(self._branding)
        # Persist current visible cell positions back into items so a
        # reload restores layout faithfully.
        self._sync_positions_into_items()
        save_forest(self.forest, target)
        self._dirty = False

    def save_as(self, path: str | Path) -> None:
        self._sync_positions_into_items()
        save_forest(self.forest, path)
        self.forest.loaded_from = str(Path(path).resolve())
        self._dirty = False

    def open(self, path: str | Path) -> None:
        """Replace the current forest with the one at ``path``."""
        # Tear down current items.
        for it in list(self.forest.items):
            self._despawn_item(it)
        self.forest = load_forest(path)
        if self.forest_window is not None:
            self.forest_window.set_label(_derive_label(self.forest.name))
        for it in list(self.forest.items):
            self._spawn_item(it)
        self.forestChanged.emit()

    # ------------------------------------------------------------------
    # Layout sync — pull live positions from the registry.
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Persistence debounce
    # ------------------------------------------------------------------

    def _mark_dirty(self) -> None:
        """Mark forest state as needing a save.  We piggyback on the
        QTimer in the rest of the shell rather than spinning our own;
        ``ring_main`` calls ``flush_if_dirty`` periodically.
        """
        self._dirty = True

    def flush_if_dirty(self) -> None:
        if self._dirty:
            try:
                self.save()
            except Exception as exc:  # noqa: BLE001
                _log(f"flush_if_dirty: save failed: {exc!r}")

    # ------------------------------------------------------------------
    # Right-click menu (stub — wired to dialogs in the next file)
    # ------------------------------------------------------------------

    def _on_right_click(self, global_pos: QPoint) -> None:
        """Build and show the forest cell's context menu.

        Lives here (not in ``ForestWindow``) so the actions can call
        controller methods directly without circular imports.
        """
        from PySide6.QtWidgets import QFileDialog, QMenu

        menu = QMenu(self.forest_window)

        a_save = menu.addAction("Save forest")
        a_save_as = menu.addAction("Save forest as…")
        a_open = menu.addAction("Open forest…")
        menu.addSeparator()

        a_refresh = menu.addAction("Refresh from sources")
        a_autoadd = menu.addAction("Auto-add from ScripTreeApps now")
        menu.addSeparator()

        a_settings = menu.addAction("Forest settings…")
        a_excluded = menu.addAction("Manage excluded items…")
        menu.addSeparator()

        a_about = menu.addAction("About this forest")

        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen is a_save:
            self.save()
        elif chosen is a_save_as:
            target, _ = QFileDialog.getSaveFileName(
                self.forest_window, "Save forest as",
                str(default_autoload_path(self._branding)),
                "ScripTree forest (*.scriptreeforest)",
            )
            if target:
                self.save_as(target)
        elif chosen is a_open:
            target, _ = QFileDialog.getOpenFileName(
                self.forest_window, "Open forest",
                "",
                "ScripTree forest (*.scriptreeforest)",
            )
            if target:
                self.open(target)
        elif chosen is a_refresh:
            self.refresh_from_sources()
        elif chosen is a_autoadd:
            # Force-run discovery against the default ScripTreeApps
            # root regardless of the configured update_mode — this
            # is the explicit "do it now" button.
            diff = self.discover_now()
            if diff.is_empty():
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self.forest_window, "Auto-add",
                    "Forest is already up to date — nothing to add.",
                )
            else:
                self._show_diff_dialog(diff)
        elif chosen is a_settings:
            self._show_settings_dialog()
        elif chosen is a_excluded:
            self._show_excluded_dialog()
        elif chosen is a_about:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self.forest_window,
                "Forest",
                self._about_text(),
            )

    def _about_text(self) -> str:
        cfg = self.forest.auto_discover
        return (
            f"<b>{self.forest.name}</b><br><br>"
            f"Items: {len(self.forest.items)}<br>"
            f"Excluded: {len(self.forest.excluded)}<br>"
            f"Auto-discover: "
            f"{'enabled' if cfg.enabled else 'disabled'} "
            f"({cfg.update_mode})<br>"
            f"Roots: {', '.join(cfg.roots) or '(none)'}<br>"
            f"<br>"
            f"File: {self.forest.loaded_from or '(unsaved)'}"
        )

    # ------------------------------------------------------------------
    # Dialog stubs — implemented in forest_dialogs.py.
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(path: str) -> str:
    """Mirror of ``forest_discover._norm`` — kept private here so we
    don't pull a dependency on the discover module just for path
    normalisation."""
    try:
        return str(Path(path).resolve()).lower().replace("\\", "/")
    except (OSError, ValueError, RuntimeError):
        return str(path).lower().replace("\\", "/")
