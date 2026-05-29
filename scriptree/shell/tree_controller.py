"""Tree controller — orchestration layer for ``.scriptreetree``
auto-discovery.

## For humans

This is the glue that wires Phases 1-5 together into the
runtime UX a user actually experiences when they right-click a
tree-bound cell.  Parallel to ``scriptree.shell.forest_controller``;
narrower in scope because trees have no spawn/dock/ring lifecycle
to manage — just a file, an in-memory ``TreeDef``, and a cell
the user is looking at.

One ``TreeController`` instance lives per tree-bound cell.  It:

* Loads the ``.scriptreetree`` from disk.
* Owns the in-memory ``TreeDef``.
* Installs a ``_tree_menu_extension`` callback on the cell so
  right-clicking pops a "Tree" submenu with: Refresh from
  sources, Auto-add from this folder now, Tree settings…,
  Excluded items…
* Runs ``discover_for_tree`` + ``diff_against_tree`` on demand
  (from the menu, from the settings dialog's "Save && Run",
  or from the cell's first-show event when ``update_mode ==
  "prompt"``).
* Dispatches to the right dialog (``TreeUpdateDiffDialog`` for
  prompt mode; nothing for auto mode where everything is
  silent; nothing for off mode where the walker doesn't run).
* Fires ``ChooseUpdateModeDialog`` on first load when
  ``tree.auto_discover is None``, then persists the user's
  pick so the chooser never fires again for this tree.
* Saves changes back to disk via ``save_tree``.

## For maintainers / LLMs

* Module is in ``scriptree.shell``.  Mirrors forest_controller's
  layering: orchestration sits in shell, while the pure logic
  (walker, diff) sits in ``core``, and the dialogs sit in
  ``ui``.
* The controller holds a soft reference to the cell (typed
  ``Any`` to avoid a circular import with cell_window) so the
  cell can be garbage-collected normally.  Don't subclass
  ``QObject`` here — the controller is plain Python and lifetime
  is tied to whoever holds the reference (typically the cell
  itself, via ``cell._tree_controller``).
* The menu extension is the SAME single-callback pattern as
  forest's ``_forest_menu_extension``.  See
  ``scriptree.shell.cell_window._show_context_menu`` for the
  invocation site that calls ``self._tree_menu_extension(menu)``.
* When the tree's mode is ``"prompt"``, the on-load discovery
  fires on the next event tick (via ``QTimer.singleShot(0,
  ...)``) so the dialog parents to the fully-constructed cell
  rather than to a window that's still mid-spawn.  Forest does
  the same; the pattern is established.
* ``refresh_from_sources`` is the same entry point whether
  the user clicked Refresh, clicked the dialog's Save & Run, or
  the auto-load path fired it.  Always re-reads the tree's
  current config (so a settings dialog change takes effect
  immediately even within the same session).
* The "Auto-add now" menu item is a UX shortcut: it temporarily
  treats the mode as ``"prompt"`` regardless of the persisted
  setting, so a user with ``update_mode="off"`` can still get a
  one-shot scan-and-decide flow without reconfiguring the tree.
* Disk writes go through ``save_tree`` (the existing I/O entry
  point), which produces the byte-identical-on-no-change output
  that the round-trip tests pin.  Never reach around it.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMenu, QMessageBox

from ..core.discovery import TreeAutoDiscoverConfig
from ..core.io import load_tree, save_tree
from ..core.model import TreeDef, TreeNode
from ..core.tree_diff import (
    TreeDiscoveryDiff,
    apply_diff_to_tree,
    diff_against_tree,
)
from ..core.tree_discover import (
    DiscoveredTreeItem,
    discover_for_tree,
)


def _log(msg: str) -> None:
    print(f"[tree_controller] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# TreeController
# ---------------------------------------------------------------------------

class TreeController:
    """Per-cell orchestration for a ``.scriptreetree``.

    Construct one per tree-bound cell at the moment the cell
    finishes loading its catalog.  After construction the
    caller should call :meth:`attach_to_cell` to install the
    right-click menu extension and the first-load chooser
    handler.

    The controller satisfies the ``_TreeController`` protocol
    used by the tree dialogs — same attribute and method names
    so a dialog can be wired against either a real controller
    or a test fake.

    Public attributes:

    ``tree`` : TreeDef
        In-memory model.  May be mutated by ``apply_diff`` and
        the settings dialog.

    ``tree_file`` : str
        Path to the backing ``.scriptreetree``.  Used as the
        anchor for relative-path resolution.

    ``parent_widget`` : QWidget | None
        Parent for any dialog the controller opens.  Set to the
        cell after ``attach_to_cell`` runs; ``None`` until then.

    Public methods:

    ``save() -> None``
        Persist ``tree`` to ``tree_file`` via ``save_tree``.

    ``refresh_from_sources() -> None``
        Walker + diff + dialog-or-auto-apply, honouring the
        tree's current ``auto_discover.update_mode``.

    ``apply_diff(diff, *, accepted_added, accepted_removed,
                 accepted_reincluded) -> None``
        Mutate ``tree`` in place per a user-curated subset of
        the diff buckets.  Wraps ``apply_diff_to_tree``.

    ``attach_to_cell(cell, *, fire_first_load_chooser=True) -> None``
        Install the menu extension on ``cell`` and, if the
        tree has no ``auto_discover`` block AND
        ``fire_first_load_chooser`` is true, schedule the
        ``ChooseUpdateModeDialog`` on the next event tick.
        After the chooser, schedule the first discovery pass
        per the chosen mode.
    """

    def __init__(self, tree_file: str | Path, *, tree: TreeDef | None = None):
        """Construct the controller.

        Parameters
        ----------
        tree_file:
            Path to the ``.scriptreetree``.  Must exist on disk
            unless ``tree`` is provided (then the path is just
            metadata for save/anchor purposes).
        tree:
            Pre-loaded ``TreeDef`` (e.g. when the caller already
            loaded the file).  When ``None``, the controller
            calls ``load_tree(tree_file)`` itself.
        """
        self.tree_file: str = str(Path(tree_file).resolve())
        if tree is None:
            tree = load_tree(self.tree_file)
        self.tree: TreeDef = tree
        self.parent_widget: Any = None  # set by attach_to_cell
        self._cell: Any = None  # weak-like reference; set by attach_to_cell

    # --- persistence ------------------------------------------------------

    def save(self) -> None:
        """Write ``self.tree`` back to ``self.tree_file``.

        Swallows ``OSError`` (read-only filesystem, permission
        error) with a user-visible warning rather than crashing
        — matches forest behaviour.  Other exceptions propagate.
        """
        try:
            save_tree(self.tree, self.tree_file)
        except OSError as exc:
            _log(f"save: write failed: {exc!r}")
            if self.parent_widget is not None:
                QMessageBox.warning(
                    self.parent_widget,
                    "Couldn't save tree",
                    f"Failed to write {self.tree_file}:\n{exc}",
                )

    # --- discovery / diff -------------------------------------------------

    def _effective_config(self) -> TreeAutoDiscoverConfig:
        """Return the tree's current ``auto_discover`` config,
        falling back to defaults when ``None``.

        Used by every code path that needs to know "what roots
        should we scan / what mode should we apply"; centralises
        the None→defaults coercion."""
        return self.tree.auto_discover or TreeAutoDiscoverConfig()

    def _run_walker(self) -> list[DiscoveredTreeItem]:
        cfg = self._effective_config()
        return discover_for_tree(
            self.tree_file,
            roots=cfg.roots,
            include_sibling_trees=cfg.include_sibling_trees,
        )

    def refresh_from_sources(self) -> None:
        """The main "scan now and react per the mode" entry
        point.  Called by the menu item, by the settings
        dialog's "Save && Run", by the on-load auto-fire path,
        and by tests.

        Order:

        1. If ``auto_discover.enabled`` is False, do nothing
           (the user explicitly disabled the feature).
        2. Run the walker.
        3. Diff against the current tree + excluded list.
        4. If the diff is empty, return silently (nothing to
           show; nothing to apply).
        5. Dispatch by ``update_mode``:
            * ``"off"``  — nothing to do.  The user can still
                           trigger this manually via "Auto-add
                           now", which calls
                           ``run_one_shot_prompt`` instead.
            * ``"auto"`` — apply every bucket fully and save.
            * ``"prompt"`` — open ``TreeUpdateDiffDialog``.
        """
        cfg = self._effective_config()
        if not cfg.enabled:
            return
        discovered = self._run_walker()
        diff = diff_against_tree(
            self.tree, self.tree_file, discovered,
        )
        if diff.is_empty():
            return

        if cfg.update_mode == "off":
            return
        if cfg.update_mode == "auto":
            self.apply_diff(
                diff,
                accepted_added=diff.added,
                accepted_removed=diff.removed,
                accepted_reincluded=[],  # never silently re-include
            )
            self.save()
            return
        # "prompt"
        self._show_diff_dialog(diff)

    def run_one_shot_prompt(self) -> None:
        """Force a prompt-style scan regardless of the tree's
        persisted ``update_mode``.  Used by the "Auto-add from
        this folder now" menu item so the user can scan + decide
        even when the tree is configured for ``update_mode="off"``.

        Skips the ``enabled`` check too — this is an explicit
        user action; honouring the disable here would be
        confusing UX ("I clicked the button and nothing
        happened").
        """
        discovered = self._run_walker()
        diff = diff_against_tree(
            self.tree, self.tree_file, discovered,
        )
        if diff.is_empty():
            if self.parent_widget is not None:
                QMessageBox.information(
                    self.parent_widget,
                    "Nothing new",
                    "No new tools were found in this tree's folder.",
                )
            return
        self._show_diff_dialog(diff)

    def apply_diff(
        self,
        diff: TreeDiscoveryDiff,  # noqa: ARG002 — included for protocol fidelity
        *,
        accepted_added: Iterable[DiscoveredTreeItem],
        accepted_removed: Iterable[TreeNode],
        accepted_reincluded: Iterable[DiscoveredTreeItem],
    ) -> None:
        """Mutate ``self.tree`` per the user-curated subsets.

        Wraps ``apply_diff_to_tree`` (Phase 3).  Does NOT save
        — callers (the dialog's Apply path, ``refresh_from_sources``
        in auto mode) save explicitly so the auto path can
        batch.  The protocol signature includes ``diff`` for
        forward-compatibility with surfaces that might want to
        annotate / log it, but the current implementation
        doesn't need it.
        """
        apply_diff_to_tree(
            self.tree,
            self.tree_file,
            accepted_adds=list(accepted_added),
            accepted_removes=list(accepted_removed),
            accepted_reincludes=list(accepted_reincluded),
        )

    # --- dialog dispatch --------------------------------------------------

    def _show_diff_dialog(self, diff: TreeDiscoveryDiff) -> None:
        # Lazy import to avoid pulling Qt UI at controller-construction
        # time (tests construct controllers headlessly).
        from ..ui.tree_dialogs import TreeUpdateDiffDialog
        dlg = TreeUpdateDiffDialog(self, diff)
        dlg.exec()

    def _show_settings_dialog(self) -> None:
        from ..ui.tree_dialogs import TreeSettingsDialog
        dlg = TreeSettingsDialog(self)
        dlg.exec()

    def _show_first_load_chooser(self) -> None:
        """Fire ``ChooseUpdateModeDialog`` and persist the user's
        pick to ``self.tree.auto_discover``.

        After persisting, fire ``refresh_from_sources()`` if the
        chosen mode is prompt or auto — the user just told us
        what to do, so do it (rather than wait for a manual
        Refresh).  For ``off``, just persist and stop.
        """
        from ..ui.tree_dialogs import ChooseUpdateModeDialog
        dlg = ChooseUpdateModeDialog(
            tree_name=self.tree.name,
            parent=self.parent_widget,
        )
        dlg.exec()
        mode = dlg.chosen
        # Write a fresh config with the chosen mode; other fields
        # at default.  The user can refine via Tree settings…
        # later.
        self.tree.auto_discover = TreeAutoDiscoverConfig(
            update_mode=mode,  # type: ignore[arg-type]
        )
        self.save()
        if mode != "off":
            # Fire the first discovery pass on the next event tick
            # so the diff dialog (if any) can parent to a fully-
            # settled window.
            QTimer.singleShot(0, self.refresh_from_sources)

    # --- cell attachment / menu --------------------------------------------

    def attach_to_cell(
        self,
        cell: Any,
        *,
        fire_post_attach_work: bool = True,
    ) -> None:
        """Wire the controller into a ``CellWindow``.

        Sets ``cell._tree_controller`` (so the cell can reach
        the controller for later operations) and
        ``cell._tree_menu_extension`` (the
        ``_show_context_menu`` hook that adds the right-click
        items).  Sets ``self.parent_widget = cell`` so dialogs
        the controller opens parent themselves correctly.

        When ``fire_post_attach_work`` is true (default), schedules
        one of two callbacks on the next event tick so it parents
        to the fully-constructed cell rather than a window that's
        still mid-spawn:

        * If ``tree.auto_discover is None`` (legacy / fresh tree),
          fires ``ChooseUpdateModeDialog`` — the one-shot
          first-load chooser.
        * Otherwise, fires ``refresh_from_sources`` — the regular
          on-load discovery pass per the persisted mode.

        Tests that don't want either deferred dialog firing should
        pass ``fire_post_attach_work=False``.  The cell still gets
        its menu hook installed, but no further work is scheduled
        until something else (a right-click, a manual refresh)
        triggers it.

        Idempotent: calling twice on the same cell replaces the
        previous controller's menu hook with this one.
        """
        self._cell = cell
        self.parent_widget = cell
        cell._tree_controller = self
        cell._tree_menu_extension = self._populate_tree_menu

        if not fire_post_attach_work:
            return

        if self.tree.auto_discover is None:
            QTimer.singleShot(0, self._show_first_load_chooser)
        else:
            # Tree already has a configured mode -- fire the
            # on-load discovery pass per that mode.  For
            # ``"prompt"`` this opens the diff dialog; for
            # ``"auto"`` it silently applies; for ``"off"`` it
            # short-circuits.
            QTimer.singleShot(0, self.refresh_from_sources)

    def _populate_tree_menu(self, menu: QMenu) -> None:
        """Build the "Tree" submenu and attach it to ``menu``.

        Four actions in this order:

        1. **Refresh from sources** — calls
           ``refresh_from_sources()``.  Honours the persisted
           mode (so an ``off`` tree's refresh does nothing
           unless the user changes the mode first).
        2. **Auto-add from this folder now** — calls
           ``run_one_shot_prompt()``.  Always shows the diff
           dialog (regardless of persisted mode).
        3. **Tree settings…** — opens
           ``TreeSettingsDialog``.
        4. **Excluded items…** — opens a small listing of the
           tree's ``excluded`` paths with a per-entry "remove
           from excluded" action.  Defers to a tiny inline
           dialog (kept here rather than in ``tree_dialogs``
           because it's trivially small and never reused
           elsewhere).
        """
        submenu = menu.addMenu("Tree")
        a_refresh = submenu.addAction("Refresh from sources")
        a_refresh.triggered.connect(self.refresh_from_sources)
        a_autoadd = submenu.addAction("Auto-add from this folder now")
        a_autoadd.triggered.connect(self.run_one_shot_prompt)
        submenu.addSeparator()
        a_settings = submenu.addAction("Tree settings…")
        a_settings.triggered.connect(self._show_settings_dialog)
        a_excluded = submenu.addAction("Excluded items…")
        a_excluded.triggered.connect(self._show_excluded_dialog)

    def _show_excluded_dialog(self) -> None:
        """Open a small modal listing ``tree.excluded`` with a
        "Re-include" button per row.

        Trivially small implementation kept inline to avoid
        bloating ``tree_dialogs.py`` with a dialog that doesn't
        warrant a class-level docstring of its own.
        """
        from PySide6.QtWidgets import (
            QDialog, QDialogButtonBox, QLabel, QListWidget,
            QPushButton, QVBoxLayout,
        )

        if not self.tree.excluded:
            if self.parent_widget is not None:
                QMessageBox.information(
                    self.parent_widget,
                    "Nothing excluded",
                    "This tree has no excluded items.",
                )
            return

        dlg = QDialog(self.parent_widget)
        dlg.setWindowTitle(f"Excluded items — {self.tree.name}")
        dlg.setMinimumWidth(480)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(
            "Items you've removed from this tree.  Select rows and "
            "click 'Re-include' to bring them back; they'll be "
            "re-suggested by the next scan."
        ))
        listw = QListWidget()
        for p in self.tree.excluded:
            listw.addItem(p)
        listw.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(listw)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close
        )
        btn_reinc = QPushButton("Re-include selected")
        btn_box.addButton(
            btn_reinc, QDialogButtonBox.ButtonRole.ActionRole,
        )
        layout.addWidget(btn_box)

        def _on_reinclude() -> None:
            selected = {
                listw.item(i).text()
                for i in range(listw.count())
                if listw.item(i).isSelected()
            }
            if not selected:
                return
            self.tree.excluded = [
                p for p in self.tree.excluded if p not in selected
            ]
            self.save()
            dlg.accept()

        btn_box.rejected.connect(dlg.reject)
        btn_reinc.clicked.connect(_on_reinclude)
        dlg.exec()


__all__ = ["TreeController"]
