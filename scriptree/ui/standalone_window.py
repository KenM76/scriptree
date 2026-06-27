"""Standalone window for running tools outside the IDE.

## For humans

Two modes:

- **Single tool** — three ``PySide6QtAds`` docks (Form / Output /
  Run controls) so the user can resize, undock, float, or tab the
  panels exactly like the main editor.  Mirrors
  :class:`MainWindow`'s dock layout (centre Form, Output below,
  Run controls below).
- **Tree mode** — a :class:`QTabWidget` with one
  :class:`ToolRunnerView` per leaf tool in the tree.  Each tab
  applies its own configuration (from ``TreeNode.configuration``)
  and keeps the runner's internal QSplitter; tabs are not docked
  because docking-inside-a-tab interactions are confusing.

The window reads :class:`UIVisibility` from the specified
configuration and applies it at construction time.

## For maintainers / LLMs

- Construct via the :meth:`from_tool` / :meth:`from_tree` classmethods
  only — they own loading + tab creation. Calling ``__init__``
  directly bypasses that and yields a half-built window.
- This window passes ``standalone_mode`` semantics to
  :class:`ToolRunnerView`: in standalone mode ``hidden_params`` are
  actually removed from the form (in docked mode they stay visible).
  A config change that alters hidden params triggers a full
  ``_populate_form_rows`` rebuild in the runner — expect provider
  re-init on tab/config switches here.
- **Single-tool mode now uses QtAds docks** (v0.6.30+).  The window
  owns its own ``CDockManager``; the runner's ``form_panel``,
  ``output_panel``, and ``bottom_panel`` are reparented into three
  ``CDockWidget`` instances.  Layout state is persisted under the
  per-window QSettings key ``standalone_layout_<safe_name>``.
- Tree mode keeps the dockless splitter approach inside each tab —
  the docking story there belongs to a follow-up.  Per-tab
  resizing still works via the runner's own internal splitter.
- :class:`UIVisibility` is read and applied once at construction from
  the *specified* configuration; per-tab configs in tree mode come
  from ``TreeNode.configuration``.  In single-tool mode the
  output dock's visibility tracks runner ``visibilityChanged``
  emissions so config switches that flip ``output_pane`` update
  the layout live.
- Each tab owns an independent ToolRunnerView with its own run
  worker/thread; closing the window must let in-flight runs tear down
  via the runner's own ``_on_finished`` path — don't kill threads
  from here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import PySide6QtAds as ads

from ..core.configs import (
    SAFETREE_CONFIG_NAME,
    UIVisibility,
    ensure_safetree_config,
    load_configs,
    load_tree_configs,
)
from ..core.io import load_tool, load_tree
from ..core.model import ToolDef, TreeDef, TreeNode


def _log(msg: str) -> None:
    """Print to stderr (captured by verbose logging when enabled)."""
    import sys
    print(f"[standalone_window] {msg}", file=sys.stderr)


# Same feature set the main editor uses, kept consistent so a user
# moving between the editor and a standalone window doesn't get
# subtly different dock behaviour.  No DockWidgetClosable — the
# panels of a tool runner make no sense individually closed; users
# who want a clean form view collapse the inner group boxes instead.
_STANDALONE_DOCK_FEATURES = (
    ads.CDockWidget.DockWidgetFeature.DockWidgetMovable
    | ads.CDockWidget.DockWidgetFeature.DockWidgetFloatable
    | ads.CDockWidget.DockWidgetFeature.DockWidgetPinnable
)


# Bump this string whenever the form-panel layout structure changes
# in a way that makes previously-saved QtAds dock geometries wrong.
# (Saved geometries override widget minimumSizeHints, so a layout
# saved before a fix gets re-applied and silently re-creates the
# bug.)
#
# v4 (v0.8.0a19) -- form_dock now uses
# ``MinimumSizeHintFromContent`` so QtAds routes minimum-size
# queries to the contained QStackedWidget / _FormPanelContainer
# (which has a real C++ virtual override returning header +
# floor + bottom_band).  Without this mode QtAds asks the dock
# widget itself, which returns 0/0, and shrinks the form dock
# below the bottom band's natural height.  Any saved v3 layout
# is from a build where this mode wasn't set and may pin a
# too-small form dock height; bumping schema invalidates them.
_LAYOUT_SCHEMA = "v4"


def _standalone_settings_key(label: str) -> str:
    """Build a per-window QSettings sub-key for layout persistence.

    Each distinct tool / tree label gets its own dock layout slot
    so a user's preferred sizes for "find-missing-refs" don't get
    overwritten when they next open a different standalone tool.
    """
    safe = "".join(c if c.isalnum() else "_" for c in (label or "default"))
    return f"standalone_layout_{_LAYOUT_SCHEMA}_{safe}"


class StandaloneWindow(QMainWindow):
    """A clean, dockless window for running tools.

    Use the class methods :meth:`from_tool` and :meth:`from_tree` to
    construct instances — they handle loading and tab creation.
    """

    def __init__(
        self,
        title: str = "ScripTree",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(800, 600)
        # Don't set WA_DeleteOnClose — the parent (MainWindow) may
        # hold a reference. Let normal garbage collection do the work.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

    # --- factory: single tool -----------------------------------------------

    @classmethod
    def from_tool(
        cls,
        tool: ToolDef,
        file_path: str | None = None,
        config_name: str | None = None,
        *,
        parent: QWidget | None = None,
    ) -> "StandaloneWindow":
        """Create a standalone window for a single tool.

        v0.6.30 — the layout is now QtAds-based.  Three docks live
        in the window:

        * **Form** (centre) — the runner's parameter panel.  Owns
          the heavy lifting; the inner reorderable param form
          stretches/scrolls inside it.
        * **Output** (bottom of Form) — the stdout/stderr pane.
          Hidden when the active configuration's
          :attr:`UIVisibility.output_pane` is False; shown again
          on the next config switch that flips it back.
        * **Run controls** (bottom of Form, beneath Output) — the
          "Extra arguments" + "Command line" group boxes the
          runner used to put at the bottom of its form panel.

        Each dock is movable / floatable / pinnable.  The runner is
        constructed once and its three panels (``form_panel``,
        ``output_panel``, ``bottom_panel``) are reparented into
        their respective docks.

        Saved layouts (per-tool name) are restored on construction;
        ``closeEvent`` saves the current layout back to QSettings.
        """
        from .tool_runner import ToolRunnerView

        win = cls(title=f"ScripTree — {tool.name}", parent=parent)
        runner = ToolRunnerView(tool, file_path=file_path)
        runner.set_standalone_mode(True)

        if config_name:
            runner.apply_named_configuration(config_name)
        else:
            # No explicit -configuration flag — resolve via the set's
            # default_name pointer (set via the editor's "Default"
            # checkbox), falling back to ``active`` (the last-used
            # one).  V1 path (active only) is preserved when no
            # default is set, so existing behaviour is unchanged for
            # any sidecar that hasn't opted in.
            cfg = runner._cfg_set.default_config()
            # Sync ``active`` to whatever default_config picked, so the
            # standalone window's combo box (if visible) reflects the
            # actually-applied config.
            if runner._cfg_set.active != cfg.name:
                runner._cfg_set.active = cfg.name
            runner._apply_configuration(cfg)

        vis = runner.active_visibility

        # ----------------------------------------------------------------
        # QtAds dock layout — same shape as the editor's MainWindow.
        # ----------------------------------------------------------------
        ads.CDockManager.setConfigFlags(
            ads.CDockManager.eConfigFlag.DragPreviewIsDynamic
            | ads.CDockManager.eConfigFlag.DragPreviewShowsContentPixmap
            | ads.CDockManager.eConfigFlag.OpaqueSplitterResize
            | ads.CDockManager.eConfigFlag.FocusHighlighting
            | ads.CDockManager.eConfigFlag.DockAreaHasUndockButton
            | ads.CDockManager.eConfigFlag.DockAreaHasTabsMenuButton
            | ads.CDockManager.eConfigFlag.FloatingContainerHasWidgetTitle
        )
        dock_manager = ads.CDockManager(win)
        win.setCentralWidget(dock_manager)
        win._dock_manager = dock_manager  # type: ignore[attr-defined]

        # Reparent the form panel into the centre dock.  Reparent
        # explicitly so the runner's outer layout doesn't hold a
        # stale child pointer (Qt reparents on setWidget but being
        # explicit avoids the "widget shows briefly in old parent"
        # flicker on Win11).
        #
        # v0.8.0a19 -- no more QStackedWidget wrap.  Earlier (a16+)
        # this code wrapped form_panel in a QStackedWidget because
        # MainWindow does so for its own reasons (tool switching).
        # The hope was that the wrap would also help standalone
        # honour the bottom-band's Fixed size policy.  It did not:
        # ``QStackedWidget.sizeHint`` empirically diverges from its
        # current widget's ``sizeHint()`` override when the child
        # has a complex layout with expanding children -- with 16
        # form rows it reports ~730 px instead of the 404 px the
        # override returns, so QtAds's content-scroll-area wraps
        # the whole form_panel and the Run row scrolls off the
        # bottom.  Installing ``form_panel`` directly bypasses that
        # confused middle-man so the _FormPanelContainer subclass's
        # sizeHint / minimumSizeHint overrides flow straight into
        # QtAds.
        form_panel = runner.form_panel
        form_panel.setParent(None)
        form_dock = ads.CDockWidget(dock_manager, "Form")
        form_dock.setObjectName("StandaloneFormDock")
        form_dock.setWidget(form_panel)
        # v0.8.0a19 -- without this, QtAds asks the *dock widget*
        # for its minimum-size (always 0/0), ignores the contained
        # widget's ``minimumSizeHint`` entirely, and freely shrinks
        # the form dock below the bottom band's natural height.
        # ``MinimumSizeHintFromContent`` routes the query to
        # ``form_stack.minimumSizeHint()``, which propagates to the
        # _FormPanelContainer subclass override (header + floor +
        # bottom_band) and stops QtAds from amputating the Run row.
        # This is the same wiring MainWindow's tools dock uses
        # (main_window.py around line 226).
        form_dock.setMinimumSizeHintMode(
            ads.CDockWidget.eMinimumSizeHintMode.MinimumSizeHintFromContent
        )
        form_dock.setFeatures(_STANDALONE_DOCK_FEATURES)
        form_dock.setWindowTitle(f"Form — {tool.name}")
        form_area = dock_manager.addDockWidget(
            ads.CenterDockWidgetArea, form_dock
        )
        win._form_dock = form_dock  # type: ignore[attr-defined]
        # Saved so ``_on_visibility_changed`` (live config-switch
        # handler) can re-add the bottom docks under the same area
        # they were originally placed under.
        win._form_area = form_area  # type: ignore[attr-defined]

        # Output dock — sits below the form area.  v0.8.0a25: when the
        # active configuration's ``UIVisibility.output_pane`` is False
        # we DO NOT add the dock to the manager at all.  The previous
        # behaviour was to add it then call ``toggleView(False)``, but
        # QtAds left an empty container in the bottom dock area --
        # the user reported it as "empty docked windows instead of
        # being removed from the layout entirely."
        # The reference is preserved on the window so a future live
        # config switch (visibilityChanged) can re-add the dock.
        output_panel = runner.output_panel
        output_panel.setParent(None)
        output_dock = ads.CDockWidget(dock_manager, "Output")
        output_dock.setObjectName("StandaloneOutputDock")
        output_dock.setWidget(output_panel)
        output_dock.setFeatures(_STANDALONE_DOCK_FEATURES)
        output_dock.setWindowTitle(f"Output — {tool.name}")
        if vis.output_pane:
            dock_manager.addDockWidget(
                ads.BottomDockWidgetArea, output_dock, form_area
            )
        win._output_dock = output_dock  # type: ignore[attr-defined]
        win._output_dock_added = bool(vis.output_pane)  # type: ignore[attr-defined]

        # Run controls dock — extras + command line.  Same construction
        # rule: only add to the layout when at least one of its two
        # sub-sections (extras or command-line) is visible in the
        # active configuration.  If BOTH are suppressed, the dock
        # would just be an empty container -- don't add it.
        bottom_panel = runner.bottom_panel
        bottom_panel.setParent(None)
        run_dock = ads.CDockWidget(dock_manager, "Run controls")
        run_dock.setObjectName("StandaloneRunControlsDock")
        run_dock.setWidget(bottom_panel)
        run_dock.setFeatures(_STANDALONE_DOCK_FEATURES)
        run_dock.setWindowTitle(f"Run controls — {tool.name}")
        run_controls_wanted = bool(
            getattr(vis, "extras_box", True)
            or getattr(vis, "command_line", True)
        )
        if run_controls_wanted:
            dock_manager.addDockWidget(
                ads.BottomDockWidgetArea, run_dock, form_area
            )
        win._run_controls_dock = run_dock  # type: ignore[attr-defined]
        win._run_controls_dock_added = run_controls_wanted  # type: ignore[attr-defined]

        # Keep references so neither runner nor docks get garbage
        # collected when the closure unwinds.
        win._runner = runner  # type: ignore[attr-defined]
        win._runners: list[ToolRunnerView] = [runner]  # type: ignore[attr-defined]

        # Persist layout key for save/restore.
        win._layout_key = _standalone_settings_key(tool.name)  # type: ignore[attr-defined]
        # v0.8.0a87 — snapshot the freshly-built DEFAULT dock arrangement BEFORE
        # restoring any saved layout, so "Reset layout" (View menu) can return to
        # it even when a stale/degenerate saved layout (e.g. all three docks
        # collapsed into one tabbed area) was persisted.
        try:
            win._default_layout_state = dock_manager.saveState()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            win._default_layout_state = None  # type: ignore[attr-defined]
            _log(f"from_tool: default-layout snapshot failed: {exc!r}")
        # The single-tool dock window otherwise has no menu bar; add a minimal
        # View ▸ Reset layout so the user can recover a merged/rearranged layout.
        win._build_layout_menu()
        win._restore_layout()

        # Listen for visibility changes from the runner so a config
        # switch that flips ``output_pane`` updates the dock live.
        runner.visibilityChanged.connect(win._on_visibility_changed)

        return win

    # --- factory: tree mode -------------------------------------------------

    @classmethod
    def from_tree(
        cls,
        tree_path: str,
        config_overrides: dict[str, str] | None = None,
        *,
        parent: QWidget | None = None,
    ) -> "StandaloneWindow":
        """Create a standalone window with one tab per leaf tool.

        Configuration resolution order for each tool:

        1. ``config_overrides`` dict (explicit caller override)
        2. Active tree configuration's ``tool_configs`` mapping
        3. ``TreeNode.configuration`` from the ``.scriptreetree`` file
        4. No config (tool's active/default config is used)

        If a resolved config name doesn't exist in the tool's sidecar,
        the reserved ``safetree`` config is created/overwritten in the
        tool's sidecar and applied instead.
        """
        from .tool_runner import ToolRunnerView

        tree_def = load_tree(tree_path)
        tree_dir = Path(tree_path).resolve().parent

        win = cls(title=f"ScripTree — {tree_def.name}", parent=parent)
        # Default: wrap tabs onto multiple rows when they don't fit
        # (see WrappingTabBar). Users can flip to classic scroll
        # arrows or expand-to-fit via the right-click context menu.
        from .wrapping_tab_bar import make_wrapping_tab_widget
        tabs = make_wrapping_tab_widget()
        tabs.setElideMode(Qt.TextElideMode.ElideNone)
        tabs.tabBar().setExpanding(False)

        # Right-click menu on tab bar to change overflow mode.
        tabs.tabBar().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        tabs.tabBar().customContextMenuRequested.connect(
            lambda pos: _show_tab_mode_menu(tabs, pos, win)
        )
        win._tabs_widget = tabs  # keep ref for mode switching

        runners: list[ToolRunnerView] = []
        overrides = config_overrides or {}

        # Load the tree-level configuration sidecar if it exists.
        tree_cfg_set = load_tree_configs(tree_path)
        tree_cfg_mapping: dict[str, str] = {}
        if tree_cfg_set is not None:
            active_tree_cfg = tree_cfg_set.active_config()
            tree_cfg_mapping = active_tree_cfg.tool_configs

        # Stash everything the runtime layout-toggle needs to rebuild.
        win._tree_def = tree_def           # type: ignore[attr-defined]
        win._tree_dir = tree_dir           # type: ignore[attr-defined]
        win._tree_path = tree_path         # type: ignore[attr-defined]
        win._overrides = overrides         # type: ignore[attr-defined]
        win._tree_cfg_mapping = tree_cfg_mapping  # type: ignore[attr-defined]
        win._folder_layout = tree_def.folder_layout  # type: ignore[attr-defined]

        # Build the tab tree according to folder_layout. Each branch
        # uses _build_leaf_panel for the per-leaf widget construction
        # so configuration resolution, safetree fallback, and output-
        # pane visibility behave identically in both layouts.
        if tree_def.folder_layout == "tabs":
            _populate_folder_tabs(
                tabs, tree_def.nodes, tree_dir, overrides,
                tree_cfg_mapping, runners, win,
            )
        else:
            for node in _collect_leaves(tree_def.nodes):
                _add_leaf_tab(
                    tabs, node, tree_dir, overrides,
                    tree_cfg_mapping, runners, win,
                )

        win.setCentralWidget(tabs)
        win._runners = runners             # type: ignore[attr-defined]
        win._tabs = tabs                   # type: ignore[attr-defined]

        # Build tree-level custom menus if defined.
        if tree_def.menus:
            from collections import defaultdict
            from PySide6.QtGui import QAction
            import subprocess as _sp
            from ..core.model import MenuItemDef

            groups: dict[str, list[MenuItemDef]] = defaultdict(list)
            for item in tree_def.menus:
                groups[item.menu or "Tools"].append(item)
            mb = win.menuBar()
            for menu_name, menu_items in groups.items():
                menu = mb.addMenu(menu_name)
                _build_menu_actions(menu, menu_items, win, tree_dir)

        return win

    # --- visibility handling ------------------------------------------------

    def _on_visibility_changed(self, vis: object) -> None:
        """Add or remove the Output / Run-controls docks to match the
        active configuration's :class:`UIVisibility`.

        v0.6.30 -- was a no-op in the splitter era.  v0.8.0a25 -- uses
        ``addDockWidget`` / ``removeDockWidget`` instead of
        ``toggleView`` so a hidden section is fully removed from the
        layout (no empty container left behind).  ``_*_dock_added``
        tracks whether each dock is currently in the manager so
        repeated visibilityChanged firings don't double-add.

        For the Run-controls dock, "hidden" means BOTH
        ``extras_box`` and ``command_line`` are False -- if either
        is visible, the dock has content worth showing.
        """
        # ``ads`` is already imported at module top as
        # ``import PySide6QtAds as ads`` -- reuse it.
        dm = getattr(self, "_dock_manager", None)
        if dm is None:
            return  # tree mode (no docks).
        form_area = getattr(self, "_form_area", None)
        if form_area is None:
            # ``_form_area`` is the central dock area we add bottom
            # docks under; without it we don't know where to attach.
            form_area = getattr(getattr(self, "_form_dock", None),
                                "dockAreaWidget", None)
            if callable(form_area):
                form_area = form_area()

        # Output dock.
        out_dock = getattr(self, "_output_dock", None)
        want_out = False
        try:
            want_out = bool(getattr(vis, "output_pane", True))
        except Exception:  # noqa: BLE001
            want_out = True
        if out_dock is not None:
            currently_in = bool(getattr(self, "_output_dock_added", False))
            try:
                if want_out and not currently_in:
                    if form_area is not None:
                        dm.addDockWidget(
                            ads.BottomDockWidgetArea, out_dock, form_area,
                        )
                    else:
                        dm.addDockWidget(
                            ads.BottomDockWidgetArea, out_dock,
                        )
                    self._output_dock_added = True  # type: ignore[attr-defined]
                elif not want_out and currently_in:
                    dm.removeDockWidget(out_dock)
                    self._output_dock_added = False  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                # Last-ditch: fall through to toggleView so the user
                # at least sees the section hide rather than crash.
                try:
                    out_dock.toggleView(want_out)
                except Exception:  # noqa: BLE001
                    pass

        # Run-controls dock.
        run_dock = getattr(self, "_run_controls_dock", None)
        want_run = False
        try:
            want_run = bool(
                getattr(vis, "extras_box", True)
                or getattr(vis, "command_line", True),
            )
        except Exception:  # noqa: BLE001
            want_run = True
        if run_dock is not None:
            currently_in = bool(
                getattr(self, "_run_controls_dock_added", False),
            )
            try:
                if want_run and not currently_in:
                    if form_area is not None:
                        dm.addDockWidget(
                            ads.BottomDockWidgetArea, run_dock, form_area,
                        )
                    else:
                        dm.addDockWidget(
                            ads.BottomDockWidgetArea, run_dock,
                        )
                    self._run_controls_dock_added = True  # type: ignore[attr-defined]
                elif not want_run and currently_in:
                    dm.removeDockWidget(run_dock)
                    self._run_controls_dock_added = False  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                try:
                    run_dock.toggleView(want_run)
                except Exception:  # noqa: BLE001
                    pass

    # --- layout persistence (single-tool mode) -----------------------------

    def _restore_layout(self) -> None:
        """Pull a previously-saved QtAds layout out of QSettings and
        apply it.  Silently no-ops when there's nothing saved yet
        (first launch for this tool) or when the dock manager isn't
        present (tree mode).

        The layout key is per-tool — see ``_standalone_settings_key``.
        """
        dm = getattr(self, "_dock_manager", None)
        key = getattr(self, "_layout_key", None)
        if dm is None or not key:
            return
        try:
            # v0.8.0a19 -- routed through ``app_settings.get_settings``
            # so layout state lands in the portable ``scriptree.ini``
            # next to the install, NOT the Windows registry under
            # HKCU\Software\ScripTree.  Earlier code used
            # ``QSettings("ScripTree", "ScripTree")`` which is
            # platform-default (registry on Windows, .conf on Linux,
            # plist on macOS) -- cross-platform UNFRIENDLY and stores
            # state outside the install tree.
            from ..core.app_settings import get_settings
            settings = get_settings()
            blob = settings.value(key)
            if blob:
                dm.restoreState(blob)
        except Exception:  # noqa: BLE001 — never let restore break open
            pass

    def _build_layout_menu(self) -> None:
        """Add a minimal ``View`` menu with a ``Reset layout`` action to the
        single-tool dock window (v0.8.0a87).

        The single-tool window otherwise has no menu bar (tree mode builds its
        own).  ``Reset layout`` restores the default dock arrangement captured
        at construction — the recovery path for a saved layout that got the
        three docks (Form / Output / Run controls) merged or rearranged.
        """
        from PySide6.QtGui import QAction
        try:
            mb = self.menuBar()
            view_menu = mb.addMenu("&View")
            act_reset = QAction("Reset layout", self)
            act_reset.setToolTip(
                "Restore the Form / Output / Run-controls docks to their "
                "default arrangement (use if the panels got merged or "
                "rearranged)."
            )
            act_reset.triggered.connect(self.reset_layout)
            view_menu.addAction(act_reset)
        except Exception as exc:  # noqa: BLE001
            _log(f"_build_layout_menu: {exc!r}")

    def reset_layout(self) -> None:
        """Restore the dock layout to the default snapshot taken at
        construction (v0.8.0a87).

        Live recovery for a merged/rearranged or stale-restored layout.  The
        snapshot is the pristine default built by ``from_tool`` before any saved
        layout was applied, so restoring it un-merges the docks immediately; the
        subsequent close-time ``_save_layout`` then persists that clean default,
        overwriting the bad saved blob.
        """
        dm = getattr(self, "_dock_manager", None)
        state = getattr(self, "_default_layout_state", None)
        if dm is None or not state:
            _log("reset_layout: no dock manager / default snapshot — no-op")
            return
        try:
            dm.restoreState(state)
            _log("reset_layout: restored default dock arrangement")
        except Exception as exc:  # noqa: BLE001
            _log(f"reset_layout: restoreState failed: {exc!r}")
            return
        # Persist immediately so the clean default survives even if the window
        # is killed before a normal close-time save.
        try:
            self._save_layout()
        except Exception as exc:  # noqa: BLE001
            _log(f"reset_layout: save failed: {exc!r}")

    def _save_layout(self) -> None:
        """Persist the current QtAds layout under the per-tool key
        so the next launch of this tool restores the user's
        resizing / undocking choices."""
        dm = getattr(self, "_dock_manager", None)
        key = getattr(self, "_layout_key", None)
        if dm is None or not key:
            return
        try:
            # See ``_restore_layout`` — uses the portable INI, not
            # the Windows registry.
            from ..core.app_settings import get_settings
            settings = get_settings()
            settings.setValue(key, dm.saveState())
        except Exception:  # noqa: BLE001
            pass

    # --- close guard --------------------------------------------------------

    def closeEvent(self, event: Any) -> None:
        runners = getattr(self, "_runners", [])
        running = [r for r in runners if r.is_running()]
        if running:
            reply = QMessageBox.question(
                self,
                "Processes still running",
                f"{len(running)} tool run(s) still in progress. "
                "Close anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        # Persist the dock layout before tear-down so the next launch
        # of this tool restores the user's resizing / undocking
        # choices.  No-op in tree mode (no dock manager).
        self._save_layout()
        event.accept()


def _build_menu_actions(
    menu: Any,
    items: list,
    parent: QWidget,
    cwd: Path | None = None,
) -> None:
    """Recursively populate a QMenu from MenuItemDef items."""
    import subprocess as _sp
    from PySide6.QtGui import QAction

    for item in items:
        if item.label == "-":
            menu.addSeparator()
            continue
        if item.children:
            sub = menu.addMenu(item.label)
            _build_menu_actions(sub, item.children, parent, cwd)
            continue
        act = QAction(item.label, parent)
        if item.tooltip:
            act.setToolTip(item.tooltip)
        if item.shortcut:
            act.setShortcut(item.shortcut)
        if item.command:
            cmd = item.command
            work_dir = str(cwd) if cwd else None
            from ..core.sanitize import split_command
            # v0.8.0a29+: no_console_popen_kwargs() suppresses the
            # Windows console-window flash for custom-menu commands
            # that invoke console-subsystem programs.
            from ..core.runner import no_console_popen_kwargs
            act.triggered.connect(
                lambda checked=False, c=cmd, d=work_dir: _sp.Popen(
                    split_command(c), shell=False, cwd=d,
                    **no_console_popen_kwargs(),
                )
            )
        menu.addAction(act)


def _show_tab_mode_menu(
    tabs: QTabWidget, pos: Any, win: QWidget
) -> None:
    """Show a context menu for switching tab overflow mode.

    Three mutually-exclusive options:

    - **Wrap onto multiple rows** — tabs flow onto extra rows when
      they don't fit (via :class:`WrappingTabBar`). Default.
    - **Scroll arrows** — classic Qt behavior, single row with
      left/right scroll buttons for overflow.
    - **Expand window** — single row, no scroll buttons; widening
      the window is the only way to see hidden tabs.
    """
    from PySide6.QtGui import QAction, QActionGroup
    from PySide6.QtWidgets import QMenu

    from .wrapping_tab_bar import WrappingTabBar

    bar = tabs.tabBar()
    is_wrapping_bar = isinstance(bar, WrappingTabBar)

    menu = QMenu(win)
    group = QActionGroup(menu)
    group.setExclusive(True)

    if is_wrapping_bar:
        act_rows = QAction("Wrap onto multiple rows", menu)
        act_rows.setCheckable(True)
        act_rows.setChecked(bar.wrap_enabled())
        group.addAction(act_rows)
        menu.addAction(act_rows)
    else:
        act_rows = None

    act_scroll = QAction("Scroll arrows", menu)
    act_scroll.setCheckable(True)
    act_scroll.setChecked(
        (not is_wrapping_bar or not bar.wrap_enabled())
        and tabs.usesScrollButtons()
    )
    group.addAction(act_scroll)
    menu.addAction(act_scroll)

    act_expand = QAction("Expand window", menu)
    act_expand.setCheckable(True)
    act_expand.setChecked(
        (not is_wrapping_bar or not bar.wrap_enabled())
        and not tabs.usesScrollButtons()
        and bar.documentMode()
    )
    group.addAction(act_expand)
    menu.addAction(act_expand)

    # Folder-layout submenu (only meaningful in tree mode — when win
    # has a _tree_def attribute set by from_tree). Lets the user flip
    # between flat (one tab per tool) and tabs (folders as outer tabs,
    # tools as inner tabs) at runtime. The toggle only affects the
    # current session — the .scriptreetree on disk isn't touched.
    act_layout_flat = None
    act_layout_tabs = None
    if hasattr(win, "_tree_def") and getattr(win, "_tree_def", None) is not None:
        menu.addSeparator()
        layout_menu = menu.addMenu("Folder layout")
        layout_group = QActionGroup(layout_menu)
        layout_group.setExclusive(True)
        current = getattr(win, "_folder_layout", "flat")

        act_layout_flat = QAction("Flat (one tab per tool)", layout_menu)
        act_layout_flat.setCheckable(True)
        act_layout_flat.setChecked(current == "flat")
        layout_group.addAction(act_layout_flat)
        layout_menu.addAction(act_layout_flat)

        act_layout_tabs = QAction(
            "Folders as tabs (nested)", layout_menu
        )
        act_layout_tabs.setCheckable(True)
        act_layout_tabs.setChecked(current == "tabs")
        layout_group.addAction(act_layout_tabs)
        layout_menu.addAction(act_layout_tabs)

    chosen = menu.exec(bar.mapToGlobal(pos))
    if chosen is act_rows:
        if is_wrapping_bar:
            bar.set_wrap(True)
        tabs.setUsesScrollButtons(False)
        bar.setDocumentMode(False)
    elif chosen is act_scroll:
        if is_wrapping_bar:
            bar.set_wrap(False)
        tabs.setUsesScrollButtons(True)
        bar.setDocumentMode(False)
    elif chosen is act_expand:
        if is_wrapping_bar:
            bar.set_wrap(False)
        tabs.setUsesScrollButtons(False)
        bar.setDocumentMode(True)
    elif chosen is act_layout_flat:
        _rebuild_window_for_layout(win, "flat")
    elif chosen is act_layout_tabs:
        _rebuild_window_for_layout(win, "tabs")


def _collect_leaves(nodes: list[TreeNode]) -> list[TreeNode]:
    """Flatten a tree into a list of leaf nodes (depth-first)."""
    result: list[TreeNode] = []
    for node in nodes:
        if node.type == "leaf":
            result.append(node)
        elif node.type == "folder":
            result.extend(_collect_leaves(node.children))
    return result


# --- shared tab-construction helpers (flat + nested-folder layouts) ─

def _resolve_leaf_icon(
    node: TreeNode,
    tool,  # noqa: ANN001 -- ToolDef, avoid hoisting the import
    tool_path: Path,
):  # noqa: ANN201 -- returns QIcon
    """Resolve a ``QIcon`` for a tree-leaf tab.

    v0.8.0a32+.  Walks the icon-source chain in priority order and
    returns the first one that resolves to a real image:

      1. **Tree-node override** (``node.icon`` / ``node.icon_data``
         / ``node.icon_format``) -- set when the tree author wanted
         a leaf-specific glyph that differs from the tool's own.
      2. **Tool's cell-icon** (``tool.cell_icon`` /
         ``tool.cell_icon_data`` / ``tool.cell_icon_format``) --
         the icon the tool advertises for use in cell shells.

    For each source we check the embedded base64 form first
    (``*_icon_data``); if that's absent we treat ``*_icon`` as:

      * a bundled-icon name -- looks up
        ``scriptree/resources/icons/icon-<name>.{svg,png}``;
      * a relative path -- resolved against the tool file's parent
        directory;
      * an absolute path -- used verbatim.

    Returns an empty ``QIcon()`` when no source resolves; callers
    should detect ``isNull()`` and fall back to a no-icon tab.

    Defensive: every QPixmap.loadFromData / file-existence check is
    wrapped so a malformed icon never aborts tab construction.
    """
    from PySide6.QtGui import QIcon, QPixmap
    import base64 as _b64
    from pathlib import Path as _P

    sources = [
        (node.icon, node.icon_data, node.icon_format),
        (
            getattr(tool, "cell_icon", ""),
            getattr(tool, "cell_icon_data", ""),
            getattr(tool, "cell_icon_format", ""),
        ),
    ]
    for icon_field, icon_data, icon_format in sources:
        # Embedded base64 wins -- catalog stays self-contained.
        if icon_data:
            try:
                raw = _b64.b64decode(icon_data)
                px = QPixmap()
                # PySide6's loadFromData auto-detects from the
                # magic bytes when no format hint is given.  We
                # had a bytes-vs-str hint that broke on Windows;
                # the no-hint path is more portable.  ``str``
                # format hint also works on Linux Qt but not all
                # Windows Qt builds.
                if px.loadFromData(raw) and not px.isNull():
                    return QIcon(px)
                # Fallback: explicit hint as str (some Qt builds
                # need it for SVG, which lacks magic bytes).
                hint = (icon_format or "").upper()
                if hint and px.loadFromData(raw, hint) and not px.isNull():
                    return QIcon(px)
            except Exception:  # noqa: BLE001
                pass
        if icon_field:
            # Bundled name? Try the shipped icon set first.
            try:
                resources = (
                    _P(__file__).parent.parent
                    / "resources" / "icons"
                )
                for ext in (".svg", ".png"):
                    cand = resources / f"icon-{icon_field}{ext}"
                    if cand.is_file():
                        ic = QIcon(str(cand))
                        if not ic.isNull():
                            return ic
            except Exception:  # noqa: BLE001
                pass
            # Path? Absolute or relative-to-tool.
            try:
                p = _P(icon_field)
                if not p.is_absolute():
                    p = tool_path.parent / p
                if p.is_file():
                    ic = QIcon(str(p))
                    if not ic.isNull():
                        return ic
            except Exception:  # noqa: BLE001
                pass
    return QIcon()


def _add_leaf_tab(
    tabs: QTabWidget,
    node: TreeNode,
    tree_dir: Path,
    overrides: dict[str, str],
    tree_cfg_mapping: dict[str, str],
    runners: list,
    win: "StandaloneWindow",
) -> None:
    """Resolve a leaf node, build its ToolRunnerView, and append a tab.

    Skips nodes whose path is missing, points at a .scriptreetree, or
    fails to load. Configuration resolution honors overrides → tree
    config → node config, with the safetree fallback when a name
    doesn't exist in the tool's sidecar.

    Used by both the flat layout (top-level call against every leaf)
    and the nested-folder layout (call against leaves inside each
    folder's inner tab widget).
    """
    if not node.path:
        return
    tool_path = (tree_dir / node.path).resolve()
    if not tool_path.exists():
        return
    if str(tool_path).endswith(".scriptreetree"):
        return
    try:
        tool = load_tool(str(tool_path))
    except Exception:  # noqa: BLE001
        return

    from .tool_runner import ToolRunnerView

    runner = ToolRunnerView(tool, file_path=str(tool_path))
    runner.set_standalone_mode(True)

    # Resolve configuration name: overrides > tree config > node.
    cfg_name = (
        overrides.get(str(tool_path))
        or tree_cfg_mapping.get(node.path or "")
        or node.configuration
    )

    if cfg_name:
        applied = runner.apply_named_configuration(cfg_name)
        if not applied:
            from ..core.permissions import check_write_access
            access = check_write_access(tool_path)
            if access.sidecar_writable:
                ensure_safetree_config(str(tool_path))
                runner._load_or_init_configs()
                runner._refresh_cfg_combo()
                runner.apply_named_configuration(SAFETREE_CONFIG_NAME)
    else:
        cfg = runner._cfg_set.active_config()
        runner._apply_configuration(cfg)

    vis = runner.active_visibility

    tab = QWidget()
    tab_layout = QVBoxLayout(tab)
    tab_layout.setContentsMargins(0, 0, 0, 0)
    splitter = QSplitter(Qt.Orientation.Vertical)
    splitter.addWidget(runner.form_panel)
    if vis.output_pane:
        splitter.addWidget(runner.output_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
    tab_layout.addWidget(splitter)

    # Prefer the tree node's display_name override; fall back to
    # the tool's own name.
    tab_label = node.display_name or tool.name
    # v0.8.0a32+ -- show the tool's icon on the tab when one is
    # configured.  Sources checked in order: tree-node icon
    # override (per-leaf), then the tool's own cell-icon fields
    # (catalog-level).  Empty QIcon when none of the sources
    # resolve, so the tab still renders.
    icon = _resolve_leaf_icon(node, tool, tool_path)
    if icon.isNull():
        tabs.addTab(tab, tab_label)
    else:
        tabs.addTab(tab, icon, tab_label)
    runners.append(runner)
    runner.visibilityChanged.connect(win._on_visibility_changed)


def _populate_folder_tabs(
    parent_tabs: QTabWidget,
    nodes: list[TreeNode],
    tree_dir: Path,
    overrides: dict[str, str],
    tree_cfg_mapping: dict[str, str],
    runners: list,
    win: "StandaloneWindow",
) -> None:
    """Recursively populate ``parent_tabs`` with ``nodes``.

    For each node:

    - **Leaf** → one outer tab (via :func:`_add_leaf_tab`).
    - **Folder** → a new inner ``QTabWidget`` (also wrapping) appended
      as one outer tab, then this function recurses on the folder's
      ``children`` to populate the inner tab widget.

    A 📁 prefix on folder labels distinguishes them from leaf tabs
    when both share the outer level. Tools without a containing
    folder (top-level leaves) sit alongside folder tabs at the
    outer level — same UX as a file manager that mixes folders and
    files in the same listing.
    """
    from .wrapping_tab_bar import make_wrapping_tab_widget

    for node in nodes:
        if node.type == "leaf":
            _add_leaf_tab(
                parent_tabs, node, tree_dir, overrides,
                tree_cfg_mapping, runners, win,
            )
            continue
        # folder
        if not node.children:
            continue  # empty folder — skip to avoid an empty tab
        inner = make_wrapping_tab_widget()
        inner.setElideMode(Qt.TextElideMode.ElideNone)
        inner.tabBar().setExpanding(False)
        # Inner tab bar gets the same right-click context menu as the
        # outer one, so users can flip overflow modes / folder layout
        # / wrap-tabs at any level.
        inner.tabBar().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        inner.tabBar().customContextMenuRequested.connect(
            lambda pos, tw=inner: _show_tab_mode_menu(tw, pos, win)
        )
        _populate_folder_tabs(
            inner, node.children, tree_dir, overrides,
            tree_cfg_mapping, runners, win,
        )
        # Skip if recursion produced no usable tabs (e.g. folder full
        # of broken-path leaves).
        if inner.count() == 0:
            inner.deleteLater()
            continue
        label = node.display_name or node.name or "(unnamed)"
        parent_tabs.addTab(inner, f"\U0001f4c1 {label}")  # 📁


def _rebuild_window_for_layout(
    win: "StandaloneWindow", new_layout: str
) -> None:
    """Tear down the current tab widget and rebuild from scratch using
    the given ``new_layout`` ("flat" or "tabs").

    Discards in-flight ToolRunnerView state — any unsaved values in
    the form panels are lost. That matches user expectation for a
    layout toggle: it's a view-mode flip, not a save-state operation.
    Connected via the right-click context menu's "Folder layout"
    submenu.
    """
    from .wrapping_tab_bar import make_wrapping_tab_widget

    win._folder_layout = new_layout

    # Build a fresh outer tab widget and populate it.
    new_tabs = make_wrapping_tab_widget()
    new_tabs.setElideMode(Qt.TextElideMode.ElideNone)
    new_tabs.tabBar().setExpanding(False)
    new_tabs.tabBar().setContextMenuPolicy(
        Qt.ContextMenuPolicy.CustomContextMenu
    )
    new_tabs.tabBar().customContextMenuRequested.connect(
        lambda pos: _show_tab_mode_menu(new_tabs, pos, win)
    )

    new_runners: list = []
    if new_layout == "tabs":
        _populate_folder_tabs(
            new_tabs, win._tree_def.nodes, win._tree_dir,
            win._overrides, win._tree_cfg_mapping, new_runners, win,
        )
    else:
        for node in _collect_leaves(win._tree_def.nodes):
            _add_leaf_tab(
                new_tabs, node, win._tree_dir, win._overrides,
                win._tree_cfg_mapping, new_runners, win,
            )

    win.setCentralWidget(new_tabs)
    win._tabs_widget = new_tabs
    win._tabs = new_tabs
    win._runners = new_runners
