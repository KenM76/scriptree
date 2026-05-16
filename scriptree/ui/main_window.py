"""Main application window: menus, left-hand launcher, right-hand pane.

## For humans

Uses **PySide6-QtAds** (``PySide6QtAds``) for IDE-grade docking with
drag-overlay indicators, tabbed docking, and smooth undock/redock.

Three dock widgets:

- **Tools** (left): the ``.scriptreetree`` tree launcher.
- **Form** (right): the active ``ToolRunnerView``'s form panel.
- **Output** (bottom): the active ``ToolRunnerView``'s output panel.

All three are movable, floatable, and pinnable but **not closable** —
the user can rearrange and float but never dismiss a panel entirely.

The central widget hosts a ``QStackedWidget`` for editors and the
placeholder. When a runner is active, its form and output panels are
reparented into the dock widgets; when the user switches away or opens
an editor, they are returned to the runner's internal splitter.

Menu layout::

    File
      New tool from executable...
      New blank tool
      Open .scriptree...
      Open .scriptreetree...
      Save
      ────────────────────
      Recent files >
      ────────────────────
      Exit
    Edit
      Edit current tool
    View
      Tools
      Form
      Output

## For maintainers / LLMs

- Ctrl+S is owned by a hidden ``_act_save_dispatch`` QAction (added
  to the window, in NO menu) wired to ``_save_active`` — it is
  deliberately NOT hard-bound to save-tree. ``_save_active`` routes:
  an open tool editor wins (``_save_tool``), else the loaded tree
  (``_save_tree``), else a status hint. This fixes the regression
  where Ctrl+S while editing a tool from an open tree silently saved
  the unchanged tree and discarded tool edits. This routing is
  regression-tested — do not collapse it back to a tree-only binding.
- Every Save path re-checks its capability at call time
  (``save_scriptree`` / ``save_as_scriptree`` / ``save_scriptreetree``
  / ``save_as_scriptreetree``) via ``perm_check`` so the Ctrl+S
  shortcut cannot bypass a greyed-out menu. Keep these runtime gates.
- The three docks (Tools/Form/Output, plus a Run-controls dock) are
  movable/floatable/pinnable but **never closable** — keep
  ``_DOCK_FEATURES`` without the closable bit or the user can lose a
  panel with no way back.
- Panel ownership is by reparenting, not duplication: when a runner
  is active its form/output/bottom panels are ``setWidget``-moved
  into the docks; switching away or opening an editor returns them to
  the runner's internal splitter. The central ``QStackedWidget``
  holds editors + a placeholder. Never hold a second reference to a
  reparented panel — Qt ownership transfers on ``setWidget``.
- ``_active_editor`` is the live ``ToolEditorView`` (or ``None``). It
  drives Ctrl+S routing and ``Edit current tool`` enablement. Set it
  to ``None`` whenever the editor is torn down (``_close_active_editor``)
  or the dispatcher will save into a dead widget.
- ``closeEvent`` guards the dirty *tree* (``_confirm_discard_tree``)
  and warns about running child processes, but does NOT currently
  invoke the editor's unsaved-changes guard — see the bug audit.
- Recent-files is built ONLY from deliberate File→Open / the Recent
  menu (both via ``_add_recent_file``); selecting a tree leaf is not
  an "open" and must not touch the recent list. ``_MAX_RECENT`` caps
  it; ``_SETTINGS_KEY`` (= the value in :mod:`settings_dialog`)
  namespaces ``QSettings``.
- Layout persistence (``geometry``/``windowState``) is written on
  close only when ``remember_layout`` is set; restore happens at
  construction. Keep the opt-in symmetric.
"""
from __future__ import annotations

import json
from pathlib import Path

import PySide6QtAds as ads
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
)

from ..core.io import load_tool
from ..core.model import ParseSource, ToolDef
from ..core.parser.probe import probe
from .help_dialog import HelpDialog, show_about
from .tool_editor import ToolEditorView
from .tool_runner import ToolRunnerView
from .tree_view import TreeLauncherView

_MAX_RECENT = 10
_SETTINGS_KEY = "ScripTree"

# Features for all dock widgets: movable + floatable + pinnable, NO closable.
_DOCK_FEATURES = (
    ads.CDockWidget.DockWidgetFeature.DockWidgetMovable
    | ads.CDockWidget.DockWidgetFeature.DockWidgetFloatable
    | ads.CDockWidget.DockWidgetFeature.DockWidgetPinnable
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ScripTree")
        self.resize(1200, 780)

        self._current_tool: ToolDef | None = None
        self._current_path: str | None = None
        self._help_dialog: HelpDialog | None = None

        # Cache of live ToolRunnerView instances, keyed by absolute file
        # path. We keep runners alive across tool switches so each tool's
        # output pane, form state, and any in-flight child process
        # survive clicking between tools in the launcher. Unsaved
        # (in-memory) tools are never cached — they have no stable key.
        self._runners: dict[str, ToolRunnerView] = {}
        self._active_editor: ToolEditorView | None = None
        self._unsaved_runner: ToolRunnerView | None = None
        self._active_runner: ToolRunnerView | None = None

        # Recent files — tracked separately for tools and trees so the
        # user can see at a glance what kind each recent entry is, and
        # so the File menu can offer distinct submenus. Legacy
        # "recent_files" values are migrated on first load.
        from ..core.app_settings import get_settings
        self._settings = get_settings()
        self._recent_tools, self._recent_trees = self._load_recent_files()

        # --- QAds dock manager (replaces QMainWindow dock handling) ---
        ads.CDockManager.setConfigFlags(
            ads.CDockManager.eConfigFlag.DragPreviewIsDynamic
            | ads.CDockManager.eConfigFlag.DragPreviewShowsContentPixmap
            | ads.CDockManager.eConfigFlag.OpaqueSplitterResize
            | ads.CDockManager.eConfigFlag.FocusHighlighting
            | ads.CDockManager.eConfigFlag.DockAreaHasUndockButton
            | ads.CDockManager.eConfigFlag.DockAreaHasTabsMenuButton
            | ads.CDockManager.eConfigFlag.FloatingContainerHasWidgetTitle
        )
        self._dock_manager = ads.CDockManager(self)
        self._dock_manager.setContentsMargins(0, 0, 0, 0)
        # Eliminate splitter handle gaps so docks snap together.
        self._dock_manager.setStyleSheet(
            "ads--CDockSplitter::handle { width: 1px; height: 1px; }"
        )
        self.setCentralWidget(self._dock_manager)

        # Default layout:
        #
        #   ┌──────────┬──────────────────────────────┐
        #   │  Tools   │                              │
        #   │          │                              │
        #   ├──────────┤            Form             │
        #   │          │                              │
        #   │  Output  │                              │
        #   └──────────┴──────────────────────────────┘
        #
        # Tools and Output stack vertically on the left, each sized to
        # its content. Form takes the entire right side (full window
        # height). All three docks are detachable — this is just the
        # starting arrangement.
        #
        # Build order critical:
        #   1. Form FIRST — without a pre-existing center, a Left/Right
        #      addDockWidget would just create one and share it as a
        #      tab sibling with subsequent docks. Adding Form first
        #      seeds the center area.
        #   2. Tools as LeftDockWidgetArea of Form's area — slices a
        #      narrow left column off the left side of Form.
        #   3. Output as BottomDockWidgetArea of Tools' area — slices
        #      the bottom half off the Tools column so Tools and
        #      Output share a narrow left column, stacked vertically.

        # --- Form dock (seeds center) ---
        # Holds a QStackedWidget that shows either the welcome
        # placeholder or the current ToolRunnerView. Placed in the
        # center area (not via setCentralWidget, which would make it
        # immovable) so it's detachable like Tools and Output.
        self._stack = QStackedWidget()
        self._placeholder = QLabel(
            "<h3>ScripTree</h3>"
            "<p>File → Open .scriptree to run a tool,"
            " or File → New tool from executable to build one.</p>"
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stack.addWidget(self._placeholder)

        self._form_dock = ads.CDockWidget(self._dock_manager, "Form")
        self._form_dock.setObjectName("FormDock")
        self._form_dock.setWidget(self._stack)
        self._form_dock.setFeatures(_DOCK_FEATURES)
        self._form_dock.setWindowTitle("ScripTree")
        form_area = self._dock_manager.addDockWidget(
            ads.CenterDockWidgetArea, self._form_dock
        )

        # --- Tools launcher dock (left of Form) ---
        self._launcher = TreeLauncherView()
        self._launcher.toolSelected.connect(self._on_tool_selected)
        self._launcher.editRequested.connect(self._on_tree_edit_requested)
        self._launcher.standaloneRequested.connect(
            self._on_tree_standalone_requested
        )
        self._launcher.treeModified.connect(self._on_tree_modified)

        self._tools_dock = ads.CDockWidget(self._dock_manager, "Tools")
        self._tools_dock.setObjectName("ToolsDock")
        self._tools_dock.setWidget(self._launcher)
        self._tools_dock.setFeatures(_DOCK_FEATURES)
        self._tools_dock.setMinimumSizeHintMode(
            ads.CDockWidget.eMinimumSizeHintMode.MinimumSizeHintFromContent
        )
        tools_area = self._dock_manager.addDockWidget(
            ads.LeftDockWidgetArea, self._tools_dock, form_area
        )

        # --- Output panel dock (under Tools, same left column) ---
        self._output_dock = ads.CDockWidget(self._dock_manager, "Output")
        self._output_dock.setObjectName("OutputDock")
        self._output_dock.setWidget(QLabel(""))  # placeholder
        self._output_dock.setFeatures(_DOCK_FEATURES)
        self._dock_manager.addDockWidget(
            ads.BottomDockWidgetArea, self._output_dock, tools_area
        )
        self._output_dock.toggleView(False)

        # --- Run controls dock (under Form, holds extras + cmd line) ---
        # The active runner's "bottom panel" (Extra arguments + Command
        # line collapsibles) lives here. Detachable like Output —
        # users who want a clean form view can collapse the extras /
        # cmd group boxes inside, or float the whole dock to a second
        # monitor. Hidden until a tool is loaded.
        self._run_controls_dock = ads.CDockWidget(
            self._dock_manager, "Run controls"
        )
        self._run_controls_dock.setObjectName("RunControlsDock")
        self._run_controls_dock.setWidget(QLabel(""))  # placeholder
        self._run_controls_dock.setFeatures(_DOCK_FEATURES)
        self._dock_manager.addDockWidget(
            ads.BottomDockWidgetArea, self._run_controls_dock, form_area
        )
        self._run_controls_dock.toggleView(False)

        self._build_menu()

        # Restore saved layout if the user opted in.
        if self._settings.value("remember_layout", True, type=bool):
            geom = self._settings.value("geometry")
            if geom is not None:
                self.restoreGeometry(geom)
            state = self._settings.value("windowState")
            if state is not None:
                self.restoreState(state)

        self.statusBar().showMessage("Ready.")

    # --- menu ----------------------------------------------------------------

    def _build_menu(self) -> None:
        m_file = self.menuBar().addMenu("&File")

        from .permission_guards import apply_action_perm
        act_new_probe = QAction("&New tool from executable...", self)
        act_new_probe.triggered.connect(self._new_from_executable)
        apply_action_perm(act_new_probe, "create_new_scriptree")
        m_file.addAction(act_new_probe)

        act_new_blank = QAction("New &blank tool", self)
        act_new_blank.triggered.connect(self._new_blank)
        apply_action_perm(act_new_blank, "create_new_scriptree")
        m_file.addAction(act_new_blank)

        m_file.addSeparator()

        act_open_tool = QAction("&Open .scriptree...", self)
        act_open_tool.setShortcut("Ctrl+O")
        act_open_tool.triggered.connect(self._open_tool)
        m_file.addAction(act_open_tool)

        act_open_tree = QAction("Open .scriptree&tree...", self)
        act_open_tree.triggered.connect(self._open_tree)
        m_file.addAction(act_open_tree)

        # Combined filter — opens the same dialog but defaults to
        # the "files and trees" filter so the user sees both types.
        # All three filters are available in the filter dropdown of
        # every Open dialog regardless of which menu item was used.
        act_open_any = QAction("Open &any...", self)
        act_open_any.setShortcut("Ctrl+Shift+O")
        act_open_any.triggered.connect(self._open_any_file)
        m_file.addAction(act_open_any)

        act_new_tree = QAction("New scriptree &tree", self)
        act_new_tree.triggered.connect(self._new_tree)
        apply_action_perm(act_new_tree, "create_new_scriptreetree")
        m_file.addAction(act_new_tree)

        # Save tool (.scriptree) — enabled while the tool editor is active.
        # Distinct from "Save tree": the editor edits a single ToolDef,
        # while the launcher edits the .scriptreetree that references it.
        self._act_save_tool = QAction("Save &tool", self)
        self._act_save_tool.setToolTip(
            "Save the currently-edited .scriptree tool. "
            "Available while the tool editor is open."
        )
        self._act_save_tool.triggered.connect(self._save_tool)
        self._act_save_tool.setEnabled(False)
        m_file.addAction(self._act_save_tool)

        self._act_save_tool_as = QAction("Save tool &as...", self)
        self._act_save_tool_as.setToolTip(
            "Save the currently-edited .scriptree tool to a new path."
        )
        self._act_save_tool_as.triggered.connect(self._save_tool_as)
        self._act_save_tool_as.setEnabled(False)
        m_file.addAction(self._act_save_tool_as)

        self._act_save_tree = QAction("&Save tree", self)
        # NOTE: Ctrl+S is owned by ``_act_save_dispatch`` below, NOT
        # hard-bound to Save-tree.  Previously Ctrl+S always saved the
        # tree — so editing a .scriptree opened from an open
        # .scriptreetree and pressing Ctrl+S saved the (unchanged)
        # tree and silently dropped the tool edits.  The dispatcher
        # routes Ctrl+S to whatever is actually active.
        self._act_save_tree.triggered.connect(self._save_tree)
        self._act_save_tree.setEnabled(False)
        m_file.addAction(self._act_save_tree)

        # Context-aware Ctrl+S.  Hidden action (not in any menu — the
        # visible Save tool / Save tree items keep their own
        # triggers); it just owns the shortcut and dispatches:
        #   * tool editor active        → save the tool
        #   * else a tree is loaded     → save the tree
        #   * else nothing to do        → status hint
        self._act_save_dispatch = QAction(self)
        self._act_save_dispatch.setShortcut("Ctrl+S")
        self._act_save_dispatch.triggered.connect(self._save_active)
        self.addAction(self._act_save_dispatch)

        self._act_save_tree_as = QAction("Save tree as...", self)
        self._act_save_tree_as.setToolTip(
            "Save the loaded .scriptreetree to a new path."
        )
        self._act_save_tree_as.triggered.connect(self._save_tree_as)
        self._act_save_tree_as.setEnabled(False)
        m_file.addAction(self._act_save_tree_as)

        # ── Open in ScripTreeRing ─────────────────────────────────────
        # Hand the currently-loaded file off to the cell shell:
        #   Open in cell shell  →  one cell bound to the file (works
        #     for .scriptree, .scriptreetree, and .scriptreering).
        #   Open tree in ring shell  →  explode the tree's top-level
        #     items into N cells, automatically arranged as a ring
        #     around a master.  Only meaningful for trees.
        m_file.addSeparator()

        self._act_open_in_cell = QAction("Open in &cell shell", self)
        self._act_open_in_cell.setToolTip(
            "Open the active file in ScripTreeRing as a single cell. "
            "Spawns one cell bound to the loaded .scriptree, "
            ".scriptreetree, or .scriptreering."
        )
        self._act_open_in_cell.triggered.connect(self._open_in_cell)
        self._act_open_in_cell.setEnabled(False)
        m_file.addAction(self._act_open_in_cell)

        self._act_open_in_ring = QAction("Open tree in &ring shell", self)
        self._act_open_in_ring.setToolTip(
            "Open the loaded .scriptreetree in ScripTreeRing as a "
            "multi-cell ring. Each top-level folder or leaf becomes "
            "its own cell, and the cells are arranged as a ring "
            "around a master."
        )
        self._act_open_in_ring.triggered.connect(self._open_in_ring)
        self._act_open_in_ring.setEnabled(False)
        m_file.addAction(self._act_open_in_ring)

        # ── Cell Layout (.scriptreering) ─────────────────────────────
        # The cell shell (run_scriptreering.bat) saves multi-cell
        # layouts; the editor only knows about the single tree it has
        # loaded, so its "Save Cell Layout" entries write a single-hex
        # ring referencing the active .scriptreetree (or .scriptree).
        # "Open Cell Layout" shells out to ScripTreeRing — V1 itself
        # never renders cells.
        m_file.addSeparator()

        self._act_save_cell_layout = QAction(
            "Save Cell &Layout", self
        )
        self._act_save_cell_layout.setToolTip(
            "Save the current tree as a single-hex .scriptreering layout "
            "that ScripTreeRing can re-open as a cell."
        )
        self._act_save_cell_layout.triggered.connect(
            self._save_cell_layout
        )
        m_file.addAction(self._act_save_cell_layout)

        self._act_save_cell_layout_as = QAction(
            "Save Cell Layout &As...", self
        )
        self._act_save_cell_layout_as.triggered.connect(
            self._save_cell_layout_as
        )
        m_file.addAction(self._act_save_cell_layout_as)

        act_open_cell_layout = QAction(
            "Open Cell Layout...", self
        )
        act_open_cell_layout.setToolTip(
            "Open a .scriptreering layout in the cell shell "
            "(launches ScripTreeRing as a separate process)."
        )
        act_open_cell_layout.triggered.connect(
            self._open_cell_layout
        )
        m_file.addAction(act_open_cell_layout)

        m_file.addSeparator()

        # Recent files live directly on the File menu as two separate
        # nested submenus (not under a "Recent files" parent).
        # _rebuild_recent_menu populates them and installs a separator
        # + "Clear recent files" item after them.
        self._m_file = m_file
        self._recent_tools_menu = QMenu("Recent .scriptree", self)
        self._recent_trees_menu = QMenu("Recent .scriptreetree", self)
        m_file.addMenu(self._recent_tools_menu)
        m_file.addMenu(self._recent_trees_menu)
        self._recent_sep_before_exit = m_file.addSeparator()
        self._act_clear_recent = QAction("Clear recent files", self)
        self._act_clear_recent.triggered.connect(self._clear_recent_files)
        m_file.addAction(self._act_clear_recent)
        self._rebuild_recent_menu()

        m_file.addSeparator()

        act_exit = QAction("E&xit", self)
        act_exit.triggered.connect(self.close)
        m_file.addAction(act_exit)

        m_edit = self.menuBar().addMenu("&Edit")
        act_edit_current = QAction("Edit current tool", self)
        act_edit_current.setShortcut("Ctrl+E")
        act_edit_current.triggered.connect(self._edit_current)
        m_edit.addAction(act_edit_current)

        m_edit.addSeparator()
        # ``Sanitization warnings...`` (V3 v0.3.4) — view + re-enable
        # the global / per-tool / per-field mutes set via the three
        # checkboxes in the injection-warning dialog.  Always
        # available regardless of permission state — re-enabling is
        # the safe direction (more warnings, not fewer).
        act_supp = QAction("Sani&tization warnings...", self)
        act_supp.setToolTip(
            "View and re-enable sanitization warnings you previously "
            "dismissed via the 'Don't warn again' checkboxes."
        )
        act_supp.triggered.connect(self._open_sanitization_suppression)
        m_edit.addAction(act_supp)

        m_edit.addSeparator()
        act_settings = QAction("&Settings...", self)
        act_settings.triggered.connect(self._open_settings)
        # ``access_settings`` capability gate (V3 v0.3.3) — when
        # denied, the menu action is greyed out and the tooltip
        # explains why.  ``_open_settings`` itself adds a defensive
        # call-time check for keyboard / programmatic access.
        from .permission_guards import apply_action_perm
        apply_action_perm(act_settings, "access_settings")
        m_edit.addAction(act_settings)

        # View menu — toggle dock visibility via QAds toggle actions.
        m_view = self.menuBar().addMenu("&View")
        m_view.addAction(self._tools_dock.toggleViewAction())
        m_view.addAction(self._form_dock.toggleViewAction())
        m_view.addAction(self._run_controls_dock.toggleViewAction())
        m_view.addAction(self._output_dock.toggleViewAction())
        m_view.addSeparator()
        act_standalone = QAction("Open current &tool standalone", self)
        act_standalone.setShortcut("Ctrl+Shift+S")
        act_standalone.setToolTip(
            "Pop the current tool out into a lightweight standalone "
            "window. If a folder is selected in the tree, all tools "
            "under that folder open as tabs."
        )
        act_standalone.triggered.connect(self._open_standalone)
        m_view.addAction(act_standalone)

        act_standalone_tree = QAction(
            "Open entire &tree standalone", self
        )
        act_standalone_tree.setToolTip(
            "Open the loaded .scriptreetree as a standalone tabbed "
            "window with all tools on their own tabs."
        )
        act_standalone_tree.triggered.connect(self._open_standalone_tree)
        m_view.addAction(act_standalone_tree)

        m_help = self.menuBar().addMenu("&Help")
        act_help_contents = QAction("Help &Contents...", self)
        act_help_contents.setShortcut("F1")
        act_help_contents.triggered.connect(self._show_help)
        m_help.addAction(act_help_contents)
        m_help.addSeparator()
        act_about = QAction("&About ScripTree...", self)
        act_about.triggered.connect(lambda: show_about(self))
        m_help.addAction(act_about)

    # --- recent files --------------------------------------------------------

    @staticmethod
    def _is_tree_path(path: str) -> bool:
        return path.lower().endswith(".scriptreetree")

    def _load_recent_files(self) -> tuple[list[str], list[str]]:
        """Load the two recent-files lists from QSettings.

        Returns ``(recent_tools, recent_trees)``. Migrates from the
        legacy single ``recent_files`` key on first run: each entry is
        routed to the tools or trees list by extension, preserving
        order. The legacy key is then cleared.
        """
        def _load(key: str) -> list[str]:
            raw = self._settings.value(key, "[]")
            try:
                items = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                items = []
            return [str(p) for p in items if p][:_MAX_RECENT]

        tools = _load("recent_tools")
        trees = _load("recent_trees")
        if not tools and not trees:
            # Migrate legacy flat list, if any.
            legacy = _load("recent_files")
            for path in legacy:
                if self._is_tree_path(path):
                    trees.append(path)
                else:
                    tools.append(path)
            if legacy:
                self._settings.remove("recent_files")
        return tools[:_MAX_RECENT], trees[:_MAX_RECENT]

    def _save_recent_files(self) -> None:
        self._settings.setValue(
            "recent_tools", json.dumps(self._recent_tools)
        )
        self._settings.setValue(
            "recent_trees", json.dumps(self._recent_trees)
        )

    def _add_recent_file(self, path: str) -> None:
        if not path:
            return
        resolved = str(Path(path).resolve())
        is_tree = self._is_tree_path(resolved)
        target = self._recent_trees if is_tree else self._recent_tools
        # Remove if already present, then prepend; cap length.
        target[:] = [p for p in target if p != resolved]
        target.insert(0, resolved)
        del target[_MAX_RECENT:]
        self._save_recent_files()
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        """Refill the two direct-on-File Recent submenus.

        ``Clear recent files`` is a top-level File action and is
        enabled only when at least one recent entry exists.
        """
        def _populate(sub: QMenu, paths: list[str]) -> None:
            sub.clear()
            if not paths:
                act = sub.addAction("(none)")
                act.setEnabled(False)
                return
            for p in paths:
                act = sub.addAction(f"{Path(p).name}  —  {p}")
                act.setData(p)
                act.triggered.connect(
                    lambda checked=False, q=p: self._open_recent(q)
                )

        _populate(self._recent_tools_menu, self._recent_tools)
        _populate(self._recent_trees_menu, self._recent_trees)
        self._act_clear_recent.setEnabled(
            bool(self._recent_tools) or bool(self._recent_trees)
        )

    def open_file(self, path: str) -> None:
        """Programmatically open a file (used by CLI and auto-open)."""
        self._open_recent(path)

    def _open_recent(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            # Offer the recovery dialog with a selectable path the user
            # can copy, plus a Browse option for picking a replacement.
            from .recovery_dialog import MissingFileRecoveryDialog
            is_tree = path.endswith(".scriptreetree")
            file_filter = (
                "ScripTree tree files (*.scriptreetree);;All files (*)"
                if is_tree else
                "ScripTree files (*.scriptree);;All files (*)"
            )
            dlg = MissingFileRecoveryDialog(
                self,
                title="Recent file not found",
                message=(
                    "This file has moved, been renamed, or been "
                    "deleted since it was last opened."
                ),
                missing_path=path,
                allow_replace=True,
                file_filter=file_filter,
                browse_caption="Select replacement file",
            )
            accepted = dlg.exec() == QDialog.DialogCode.Accepted
            replacement = dlg.selected_replacement() if accepted else None
            # Remove the dead entry from whichever list it's in.
            self._recent_tools[:] = [
                f for f in self._recent_tools if f != path
            ]
            self._recent_trees[:] = [
                f for f in self._recent_trees if f != path
            ]
            self._save_recent_files()
            self._rebuild_recent_menu()
            if replacement:
                # Recurse to open the replacement — it'll go through
                # the same code path and land in the right place.
                self._open_recent(str(Path(replacement).resolve()))
            return
        if path.endswith(".scriptreetree"):
            if not self._confirm_discard_tree():
                return
            self._launcher.load(path)
            self._add_recent_file(path)
            return
        try:
            tool = load_tool(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Load error", str(e))
            return
        self._show_runner(tool, path)
        self._add_recent_file(path)

    def _clear_recent_files(self) -> None:
        self._recent_tools.clear()
        self._recent_trees.clear()
        self._save_recent_files()
        self._rebuild_recent_menu()

    # --- dock management -----------------------------------------------------

    def _install_runner_panels(self, runner: ToolRunnerView) -> None:
        """Hook up the runner's panels to the surrounding docks.

        The form panel stays **inside** the runner (the runner is the
        current widget in the form dock's stack), so the form just
        naturally fills whatever area the form dock occupies — center
        by default, floating if the user detached the dock.

        The output panel is pulled out into the bottom output dock so
        it can be detached/resized independently of the form.
        """
        self._active_runner = runner

        # Form dock: retitle + make sure it's visible.
        self._form_dock.setWindowTitle(f"Form — {runner._tool.name}")
        if not self._form_dock.isVisible():
            self._form_dock.toggleView(True)

        # Output dock: reparent the runner's output panel into it.
        output = runner.output_panel
        output.setParent(None)
        self._output_dock.setWidget(output)
        self._output_dock.setWindowTitle(f"Output — {runner._tool.name}")
        self._output_dock.toggleView(True)

        # Run controls dock: reparent the bottom panel (extras + cmd
        # line) into it. The runner's internal splitter still hosts the
        # form on top; the dock now owns the bottom pane and can be
        # floated, tabbed, or hidden independently.
        bottom = runner.bottom_panel
        bottom.setParent(None)
        self._run_controls_dock.setWidget(bottom)
        self._run_controls_dock.setWindowTitle(
            f"Run controls — {runner._tool.name}"
        )
        self._run_controls_dock.toggleView(True)

        # ads gives a freshly-revealed dock half of its parent area's
        # vertical space — way too tall for the run controls. The
        # dock area splitter needs an explicit ``setSizes`` to give
        # the form most of the height. Defer to the next event-loop
        # tick so ads has finished its own layout pass first; without
        # the deferral the splitter sizes get clobbered.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._shrink_dock_to_content_height)

    def _shrink_dock_to_content_height(self) -> None:
        """Give the run-controls + output docks just enough height to
        fit their content, and hand the rest to the form.

        Walked the parent chain of each dock area until we hit the
        first ``QSplitter`` — that's the ads dock-area splitter. We
        compute a compact height for run-controls / output from their
        widget's ``sizeHint`` and assign the remainder to whichever
        sibling holds the form area.
        """
        from PySide6.QtWidgets import QSplitter

        def _find_parent_splitter(widget) -> tuple[QSplitter, int] | None:
            """Walk up until a QSplitter is found. Return (splitter,
            child_index_holding_widget) or None if none found."""
            child = widget
            parent = widget.parentWidget()
            while parent is not None and not isinstance(parent, QSplitter):
                child = parent
                parent = parent.parentWidget()
            if not isinstance(parent, QSplitter):
                return None
            for i in range(parent.count()):
                if parent.widget(i) is child:
                    return parent, i
            return None

        def _compact_one(dock, compact_px: int) -> None:
            area = dock.dockAreaWidget()
            if area is None:
                return
            found = _find_parent_splitter(area)
            if found is None:
                return
            splitter, idx = found
            sizes = splitter.sizes()
            if len(sizes) < 2 or idx >= len(sizes):
                return
            total = sum(sizes)
            if total <= compact_px:
                return
            new_sizes = list(sizes)
            new_sizes[idx] = compact_px
            # Hand everything else to the LARGEST sibling (typically
            # the form area) so the form takes precedence on startup.
            others = [j for j in range(len(sizes)) if j != idx]
            biggest = max(others, key=lambda j: sizes[j])
            new_sizes[biggest] = total - compact_px - sum(
                sizes[j] for j in others if j != biggest
            )
            splitter.setSizes(new_sizes)

        # Run controls: pick the bottom panel's natural sizeHint plus
        # ads's title-bar chrome (~30 px).
        rc_widget = self._run_controls_dock.widget()
        if rc_widget is not None:
            rc_compact = max(rc_widget.sizeHint().height() + 30, 80)
            _compact_one(self._run_controls_dock, rc_compact)

        # Output dock: less critical (it lives below Tools, not Form),
        # but a fresh install also gives it half of the left column.
        # Leave it untouched for now — the user can drag if needed.

    def _uninstall_runner_panels(self) -> None:
        """Return the active runner's output + bottom panels to their
        internal splitter and reset dock titles."""
        runner = self._active_runner
        if runner is None:
            return
        output = runner.output_panel
        output.setParent(None)
        runner._inner_splitter.addWidget(output)
        # Reattach the bottom (extras + cmd) panel to the runner's
        # internal splitter so a re-installed runner finds it where
        # _build_form_panel originally placed it.
        bottom = runner.bottom_panel
        bottom.setParent(None)
        runner._bottom_splitter.addWidget(bottom)
        self._active_runner = None
        self._output_dock.toggleView(False)
        self._run_controls_dock.toggleView(False)
        # Reset form dock title when no tool is active — the dock will
        # be showing the placeholder welcome widget.
        self._form_dock.setWindowTitle("ScripTree")

    # --- actions -------------------------------------------------------------

    def _new_from_executable(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select executable", "",
            "Executables (*.exe *.bat *.cmd *.py *.sh);;All files (*)",
        )
        if not path:
            return
        self.statusBar().showMessage(f"Probing {path} for --help...")
        result = probe(path)
        if result.tool is None:
            tool = ToolDef(
                name=Path(path).stem,
                executable=path,
                source=ParseSource(mode="manual"),
            )
            self.statusBar().showMessage(
                "No help text found — opening blank editor."
            )
            self._show_editor(tool, None)
            return
        self.statusBar().showMessage(
            f"Parsed {len(result.tool.params)} params via "
            f"{result.tool.source.mode} detector."
        )
        self._show_editor(result.tool, None)

    def _new_blank(self) -> None:
        tool = ToolDef(name="", executable="")
        self._show_editor(tool, None)

    #: Shared filter string for File -> Open dialogs. All three filters
    #: are always available in the dropdown; the ``default`` argument to
    #: ``_open_any`` just picks which one the dialog opens on.
    _OPEN_FILTERS = (
        "ScripTree files (*.scriptree)"
        ";;ScripTree trees (*.scriptreetree)"
        ";;ScripTree files and trees (*.scriptree *.scriptreetree)"
        ";;All files (*)"
    )
    _FILTER_TOOL = "ScripTree files (*.scriptree)"
    _FILTER_TREE = "ScripTree trees (*.scriptreetree)"
    _FILTER_BOTH = "ScripTree files and trees (*.scriptree *.scriptreetree)"

    def _open_any(self, title: str, default_filter: str) -> None:
        """Shared File -> Open dialog.

        Always offers three filters (.scriptree / .scriptreetree /
        both) + All files. The chosen file's extension determines
        which handler runs — so picking a .scriptreetree from the
        "Open .scriptree..." menu still works, and vice versa.
        """
        path, _ = QFileDialog.getOpenFileName(
            self, title, "", self._OPEN_FILTERS,
            default_filter,
        )
        if not path:
            return
        self._load_file_into_ui(path)

    def _load_file_into_ui(self, path: str) -> None:
        """Route an opened path to the appropriate handler and record
        it in the correct recent-files list."""
        if self._is_tree_path(path):
            if not self._confirm_discard_tree():
                return
            self._launcher.load(path)
            self._add_recent_file(path)
            return
        try:
            tool = load_tool(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Load error", str(e))
            return
        self._show_runner(tool, path)
        self._add_recent_file(path)

    def _open_tool(self) -> None:
        self._open_any("Open .scriptree", self._FILTER_TOOL)

    def _open_tree(self) -> None:
        self._open_any("Open .scriptreetree", self._FILTER_TREE)

    def _open_any_file(self) -> None:
        self._open_any("Open .scriptree or .scriptreetree", self._FILTER_BOTH)

    def _new_tree(self) -> None:
        if not self._confirm_discard_tree():
            return
        self._launcher.new_tree()
        self.statusBar().showMessage(
            "New empty tree. Drop .scriptree files here or use + Tool..."
        )

    def _save_tree(self) -> None:
        # ``save_scriptreetree`` capability gate (V3 v0.3.3) — runtime
        # check defends against the Ctrl+S keyboard shortcut bypassing
        # the menu's ``setEnabled(False)``.
        from .permission_guards import perm_check
        if not perm_check("save_scriptreetree"):
            self.statusBar().showMessage(
                "Save tree disabled by IT (capability: save_scriptreetree).",
                5000,
            )
            return
        if self._launcher.save():
            self.statusBar().showMessage("Tree saved.")

    def _save_tree_as(self) -> None:
        """Prompt for a new ``.scriptreetree`` path and save the
        loaded tree there.  Delegates to ``TreeLauncherView.save_as``."""
        from .permission_guards import perm_check
        if not perm_check("save_as_scriptreetree"):
            self.statusBar().showMessage(
                "Save tree as disabled by IT (capability: save_as_scriptreetree).",
                5000,
            )
            return
        if self._launcher.save_as():
            path = self._launcher.tree_file()
            if path is not None:
                self.statusBar().showMessage(f"Tree saved to {path.name}")
                self._add_recent_file(str(path))

    def _save_active(self) -> None:
        """Ctrl+S dispatcher — save whatever the user is actually
        looking at.

        Priority: an open tool editor wins (its edits are the most
        likely thing the user means to save, and they're lost on
        navigate-away if not persisted).  Otherwise fall back to
        saving the loaded tree.  This fixes the long-standing trap
        where Ctrl+S while editing a tool from an open tree saved
        the tree instead and silently discarded the tool edits.
        """
        if self._active_editor is not None:
            self._save_tool()
            return
        if self._launcher.tree_file() is not None:
            self._save_tree()
            return
        self.statusBar().showMessage(
            "Nothing to save — open a tool or tree first.", 4000
        )

    def _save_tool(self) -> None:
        """Save the active editor's .scriptree.  Disabled when no editor."""
        from .permission_guards import perm_check
        if not perm_check("save_scriptree"):
            self.statusBar().showMessage(
                "Save tool disabled by IT (capability: save_scriptree).",
                5000,
            )
            return
        editor = self._active_editor
        if editor is None:
            self.statusBar().showMessage(
                "No tool editor active — open a tool to edit."
            )
            return
        editor.save()

    def _save_tool_as(self) -> None:
        """Save-As variant — prompts for a path even when one is set."""
        from .permission_guards import perm_check
        if not perm_check("save_as_scriptree"):
            self.statusBar().showMessage(
                "Save tool as disabled by IT (capability: save_as_scriptree).",
                5000,
            )
            return
        editor = self._active_editor
        if editor is None:
            self.statusBar().showMessage(
                "No tool editor active — open a tool to edit."
            )
            return
        editor.save_as()

    # ── Open in ScripTreeRing handlers ─────────────────────────────

    def _active_file_path(self) -> str | None:
        """Return the most-relevant on-disk path for "Open in cell".

        Priority:
          1. The active editor's bound file (if any).
          2. The active tool runner's path (if any).
          3. The loaded tree's path (if any).
          4. ``None`` — nothing relevant to hand off.
        """
        editor = self._active_editor
        if editor is not None:
            ep = editor.file_path()
            if ep:
                return ep
        if self._current_path:
            return self._current_path
        tree_file = self._launcher.tree_file()
        if tree_file is not None:
            return str(tree_file)
        return None

    def _open_in_cell(self) -> None:
        """Hand the active file off to ScripTreeRing as a single cell.

        For ``.scriptreering`` the shell loads the ring as-is.  For
        ``.scriptree`` / ``.scriptreetree`` the shell spawns one cell
        bound to that catalog.
        """
        path = self._active_file_path()
        if not path:
            QMessageBox.information(
                self, "Nothing to open",
                "Open a .scriptree or .scriptreetree first, then use "
                "this action to send it to the cell shell.",
            )
            return
        try:
            from ..shell.v1_launcher import launch_ring_shell
            launch_ring_shell(path)
            self.statusBar().showMessage(
                f"Launched ScripTreeRing with {Path(path).name}"
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self, "Launch failed",
                f"Could not launch ScripTreeRing:\n\n{exc}",
            )

    def _open_in_ring(self) -> None:
        """Explode the loaded tree's top-level items into a ring.

        Each top-level node becomes its own cell; folders are
        materialised as their own temp ``.scriptreetree`` files first.
        The ring is written to ``%TEMP%`` and handed to ScripTreeRing.
        """
        tree_file = self._launcher.tree_file()
        if tree_file is None:
            QMessageBox.information(
                self, "No tree loaded",
                "Open a .scriptreetree first.  'Open tree in ring "
                "shell' explodes the tree's top-level items into "
                "separate cells.",
            )
            return
        if self._launcher.is_dirty():
            reply = QMessageBox.question(
                self, "Unsaved tree changes",
                "The current tree has unsaved changes.  The ring "
                "shell reads the tree from disk, so any unsaved edits "
                "will not appear in the cells.  Save now?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Save:
                if not self._launcher.save():
                    return
        try:
            from ..shell.explode_tree import explode_tree_to_ring
            from ..shell.v1_launcher import launch_ring_shell
            ring_path = explode_tree_to_ring(tree_file)
            launch_ring_shell(ring_path)
            self.statusBar().showMessage(
                f"Launched ScripTreeRing with exploded ring "
                f"({ring_path.name})"
            )
        except ValueError as exc:
            QMessageBox.information(
                self, "Empty tree",
                f"Cannot open as a ring: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self, "Launch failed",
                f"Could not build / launch the ring:\n\n{exc}",
            )

    # ── Cell Layout (.scriptreering) handlers ─────────────────────────
    #
    # The editor only knows about the catalog it has loaded, so these
    # produce / consume *single-hex* rings (master.role = "standalone").
    # The cell shell (ScripTreeRing) is what saves multi-cell layouts;
    # V1's role here is just to give users a one-click way to convert
    # a loaded tree into a launcher-ready ring file.

    def _save_cell_layout(self) -> None:
        """Save the current tree as a single-hex layout, prompting only
        if no path has been associated yet (Save vs Save As)."""
        path = getattr(self, "_cell_layout_path", None)
        if path is None:
            self._save_cell_layout_as()
            return
        self._write_single_hex_ring(path)

    def _save_cell_layout_as(self) -> None:
        """Prompt for a destination path, then save."""
        from PySide6.QtWidgets import QFileDialog

        # Default name: <tree-name>.scriptreering next to the tree.
        tree_file = self._launcher.tree_file()
        default_dir = (
            str(tree_file.parent) if tree_file is not None else ""
        )
        default_name = (
            tree_file.stem + ".scriptreering" if tree_file is not None
            else "untitled.scriptreering"
        )
        suggested = (
            str(Path(default_dir) / default_name) if default_dir
            else default_name
        )
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save Cell Layout As",
            suggested,
            "Cell Layout (*.scriptreering);;All files (*)",
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() != ".scriptreering":
            path = path.with_suffix(".scriptreering")
        self._write_single_hex_ring(path)
        self._cell_layout_path = path

    def _write_single_hex_ring(self, path: Path) -> None:
        """Serialise a single-hex ``.scriptreering`` whose catalog_path
        is the editor's currently-loaded tree (or None when no tree is
        loaded — produces a "blank starter" cell)."""
        import json
        from datetime import datetime, timezone

        tree_file = self._launcher.tree_file()
        catalog_path = str(tree_file.resolve()) if tree_file is not None else None

        # Construct the ring document by hand (no need to pull in the
        # full ring_io module just to write a 5-line JSON).
        doc = {
            "format": "scriptreering",
            "version": 1,
            "saved_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "saved_by_brand": "ScripTree (editor)",
            "master": {
                "role": "standalone",
                "shape": "hexagon",
                "orientation": "flat-top",
                "size_px": 56,
                "transparency": 0.85,
                "always_on_top": True,
                "position": {"x": 200, "y": 200},
                "catalog_path": catalog_path,
            },
            "members": [],
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=2)
                f.write("\n")
            self.statusBar().showMessage(f"Cell layout saved to {path.name}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self, "Save failed",
                f"Could not write the cell layout file:\n\n{exc}",
            )

    def _open_cell_layout(self) -> None:
        """Pick a .scriptreering file and hand it off to ScripTreeRing.

        V1 itself doesn't render cells — opening a layout simply
        launches the ring shell as a sibling process and lets it take
        over.  This window stays open; the user can close it manually.
        """
        from PySide6.QtWidgets import QFileDialog
        import subprocess
        import sys

        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Open Cell Layout",
            "",
            "Cell Layout (*.scriptreering);;All files (*)",
        )
        if not path_str:
            return

        # Locate run_scriptreering.bat / .py next to V1's launcher.
        launcher_dir = Path(__file__).resolve().parent.parent.parent
        bat = launcher_dir / "run_scriptreering.bat"
        sh = launcher_dir / "run_scriptreering.sh"
        py = launcher_dir / "run_scriptreering.py"

        cmd: list[str]
        if sys.platform == "win32" and bat.is_file():
            cmd = [str(bat), path_str]
        elif sh.is_file() and sys.platform != "win32":
            cmd = ["bash", str(sh), path_str]
        elif py.is_file():
            cmd = [sys.executable, str(py), path_str]
        else:
            QMessageBox.warning(
                self, "ScripTreeRing not found",
                "Could not locate run_scriptreering.bat / .sh / .py "
                f"next to the editor at:\n  {launcher_dir}\n\n"
                "Make sure the cell shell is installed alongside the "
                "editor.",
            )
            return

        kwargs: dict = {"shell": False}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000008 | 0x00000200
        else:
            kwargs["start_new_session"] = True
        try:
            subprocess.Popen(cmd, **kwargs)
            self.statusBar().showMessage(
                f"Launched ScripTreeRing with {Path(path_str).name}"
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self, "Launch failed",
                f"Could not launch ScripTreeRing:\n\n{exc}",
            )

    def _on_tree_modified(self, dirty: bool) -> None:
        # Capability gates (V3 v0.3.3): the dynamic "have a tree
        # loaded" state only enables the action when the corresponding
        # capability is granted.  When denied, the action stays
        # disabled regardless of the load state.
        from .permission_guards import perm_check
        have_tree = self._launcher.tree_file() is not None or dirty
        self._act_save_tree.setEnabled(
            have_tree and perm_check("save_scriptreetree")
        )
        # "Save tree as..." just needs *some* tree to be loaded — even
        # an unsaved freshly-created tree is a valid Save-As target.
        self._act_save_tree_as.setEnabled(
            have_tree and perm_check("save_as_scriptreetree")
        )
        self._refresh_ring_actions()

    def _refresh_ring_actions(self) -> None:
        """Sync the enabled state of the Open-in-cell / Open-in-ring
        actions with what's currently loaded.

        Called from anywhere the active file context changes: tree
        load, tool open, editor open/close.
        """
        # Open in cell shell — any active file path qualifies.
        self._act_open_in_cell.setEnabled(self._active_file_path() is not None)
        # Open in ring shell — only meaningful when a tree is loaded
        # (the action explodes top-level items into separate cells).
        self._act_open_in_ring.setEnabled(
            self._launcher.tree_file() is not None
        )

    def _refresh_tool_save_actions(self) -> None:
        """Sync Save tool / Save tool As enabled state to the editor.

        Capability gates (V3 v0.3.3): editor-active is necessary but
        not sufficient — ``save_scriptree`` and ``save_as_scriptree``
        must also be granted.
        """
        from .permission_guards import perm_check
        editor_active = self._active_editor is not None
        self._act_save_tool.setEnabled(
            editor_active and perm_check("save_scriptree")
        )
        self._act_save_tool_as.setEnabled(
            editor_active and perm_check("save_as_scriptree")
        )

    def _confirm_discard_tree(self) -> bool:
        if not self._launcher.is_dirty():
            return True
        reply = QMessageBox.question(
            self,
            "Unsaved tree changes",
            "The current tree has unsaved changes. Save before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if reply == QMessageBox.StandardButton.Save:
            return self._launcher.save()
        if reply == QMessageBox.StandardButton.Discard:
            return True
        return False

    def closeEvent(self, event) -> None:
        if not self._confirm_discard_tree():
            event.ignore()
            return
        running = [v for v in self._runners.values() if v.is_running()]
        if self._unsaved_runner is not None and self._unsaved_runner.is_running():
            running.append(self._unsaved_runner)
        if running:
            reply = QMessageBox.question(
                self,
                "Processes still running",
                f"{len(running)} tool run(s) still in progress. "
                "Exit anyway? Running processes will be left orphaned.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        # Save layout if the user opted in.
        if self._settings.value("remember_layout", True, type=bool):
            self._settings.setValue("geometry", self.saveGeometry())
            self._settings.setValue("windowState", self.saveState())
        event.accept()

    def _show_help(self) -> None:
        if self._help_dialog is None:
            self._help_dialog = HelpDialog(self)
        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    def _edit_current(self) -> None:
        if self._current_tool is None:
            QMessageBox.information(
                self, "Edit", "No tool is currently loaded."
            )
            return
        self._show_editor(self._current_tool, self._current_path)

    # --- launcher signal -----------------------------------------------------

    def _on_tool_selected(self, tool: ToolDef, path: str) -> None:
        # Don't touch the Recent-files lists here — clicking a leaf in
        # the Tools tree isn't an "open" in the user-facing sense.
        # Recent is built only from deliberate File -> Open and the
        # Recent menu itself (both go through _add_recent_file).
        self._show_runner(tool, path)

    def _on_tree_edit_requested(self, tool: ToolDef, path: str) -> None:
        """Right-click ▸ Edit on a tree leaf — open the tool editor
        bound to that file so Save writes back to it."""
        self._show_editor(tool, path)

    def _on_tree_standalone_requested(self, desc: object) -> None:
        """Double-right-click (or right-click ▸ Open standalone) on a
        tree item.  ``desc`` is the descriptor dict built by
        ``TreeLauncherView._standalone_descriptor``."""
        from .standalone_window import StandaloneWindow
        if not isinstance(desc, dict):
            return
        kind = desc.get("kind")
        try:
            if kind == "tool":
                win = StandaloneWindow.from_tool(
                    desc["tool"], desc.get("path"), parent=self
                )
            elif kind == "tree":
                win = StandaloneWindow.from_tree(
                    desc["path"], parent=self
                )
            else:
                # Bare in-memory folder — fall back to the whole
                # loaded tree standalone (closest existing capability).
                tree_file = self._launcher.tree_file()
                if tree_file is None:
                    self.statusBar().showMessage(
                        "Nothing to open standalone here.", 4000
                    )
                    return
                win = StandaloneWindow.from_tree(
                    str(tree_file), parent=self
                )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, "Standalone failed", str(e)
            )
            return
        win.show()

    # --- stack management ----------------------------------------------------

    def _runner_key(self, path: str | None) -> str | None:
        if not path:
            return None
        try:
            return str(Path(path).resolve())
        except OSError:
            return path

    def _show_runner(self, tool: ToolDef, path: str | None) -> None:
        self._current_tool = tool
        self._current_path = path
        self._close_active_editor()
        self._uninstall_runner_panels()
        self._discard_unsaved_runner()
        # Path may have changed — recompute "Open in cell" availability.
        self._refresh_ring_actions()

        key = self._runner_key(path)
        if key is not None:
            view = self._runners.get(key)
            if view is None:
                view = ToolRunnerView(tool, file_path=path)
                view.runningChanged.connect(self._on_runner_running_changed)
                view.visibilityChanged.connect(self._on_visibility_changed)
                self._runners[key] = view
                self._stack.addWidget(view)
        else:
            view = ToolRunnerView(tool, file_path=path)
            view.runningChanged.connect(self._on_runner_running_changed)
            view.visibilityChanged.connect(self._on_visibility_changed)
            self._unsaved_runner = view
            self._stack.addWidget(view)

        # Forward the parent tree's path_prepend (V3 v0.3.2+) so the
        # spawned child's PATH includes tree-level entries.  Refresh
        # on every _show_runner — a runner cached in ``self._runners``
        # may outlive several tree-load events; calling the setter
        # each time keeps it in sync with whichever tree the launcher
        # is currently showing.  No tree loaded → empty list.
        view.set_tree_path_prepend(self._launcher.tree_path_prepend())

        self._stack.setCurrentWidget(view)
        self._install_runner_panels(view)
        self.setWindowTitle(f"ScripTree — {tool.name}")

    def _show_editor(self, tool: ToolDef, path: str | None) -> None:
        self._close_active_editor()
        self._uninstall_runner_panels()
        self._output_dock.toggleView(False)
        self._run_controls_dock.toggleView(False)
        editor = ToolEditorView(tool, file_path=path)
        editor.saved.connect(self._on_editor_saved)
        editor.cancelled.connect(self._on_editor_cancelled)
        self._active_editor = editor
        self._stack.addWidget(editor)
        self._stack.setCurrentWidget(editor)
        self.setWindowTitle(
            f"ScripTree — editing {tool.name or '(unnamed)'}"
        )
        # Editor became active — enable Save tool / Save tool as.
        self._refresh_tool_save_actions()
        self._refresh_ring_actions()

    def _close_active_editor(self) -> None:
        if self._active_editor is None:
            return
        self._stack.removeWidget(self._active_editor)
        self._active_editor.deleteLater()
        self._active_editor = None
        # Editor went away — disable Save tool / Save tool as.
        self._refresh_tool_save_actions()
        self._refresh_ring_actions()

    def _discard_unsaved_runner(self) -> None:
        if self._unsaved_runner is None:
            return
        self._stack.removeWidget(self._unsaved_runner)
        self._unsaved_runner.deleteLater()
        self._unsaved_runner = None

    def _on_runner_running_changed(self, path: str, running: bool) -> None:
        if not path:
            return
        self._launcher.mark_running(path, running)

    def _drop_cached_runner(self, path: str | None) -> None:
        key = self._runner_key(path)
        if key is None:
            return
        view = self._runners.pop(key, None)
        if view is not None:
            if self._active_runner is view:
                self._uninstall_runner_panels()
            self._stack.removeWidget(view)
            view.deleteLater()
            if path:
                self._launcher.mark_running(path, False)

    def _on_editor_saved(self, tool: ToolDef, path: str) -> None:
        self._drop_cached_runner(path)
        self.statusBar().showMessage(f"Saved to {path}")
        self._show_runner(tool, path)
        self._add_recent_file(path)

    def _on_editor_cancelled(self) -> None:
        self.statusBar().showMessage("Edit cancelled.")
        self._close_active_editor()
        if self._current_tool is not None:
            self._show_runner(self._current_tool, self._current_path)
        else:
            self._stack.setCurrentWidget(self._placeholder)

    # --- visibility signal handling ------------------------------------------

    def _on_visibility_changed(self, vis: object) -> None:
        """Respond to a runner's UIVisibility change.

        In the main IDE window, visibility flags are intentionally
        ignored — all docks stay as the user arranged them. Visibility
        settings only take effect in standalone mode (handled by the
        runner itself via ``_standalone_mode``). We keep the signal
        connection so future features can react, but the main window
        does not toggle docks based on per-config visibility.
        """
        pass

    # --- standalone window ---------------------------------------------------

    def _open_standalone(self) -> None:
        """Pop the current tool into a standalone window.

        If a tree is loaded and a folder is selected, all tools under
        that folder are opened as tabs. Otherwise just the current
        single tool is opened.
        """
        from .standalone_window import StandaloneWindow

        # If a tool is currently shown in the runner, open just that tool.
        if self._current_tool is not None:
            win = StandaloneWindow.from_tool(
                self._current_tool, self._current_path, parent=self
            )
            win.show()
            return

        QMessageBox.information(
            self,
            "No tool loaded",
            "Open a tool first, then use this action "
            "to pop it into a standalone window.",
        )

    def _open_standalone_tree(self) -> None:
        """Open the loaded .scriptreetree as a standalone tabbed window."""
        from .standalone_window import StandaloneWindow

        tree_file = self._launcher.tree_file()
        if tree_file is None:
            QMessageBox.information(
                self,
                "No tree loaded",
                "Load a .scriptreetree file first.",
            )
            return
        win = StandaloneWindow.from_tree(str(tree_file), parent=self)
        win.show()

    # --- settings dialog ------------------------------------------------------

    def _open_sanitization_suppression(self) -> None:
        """Open the dialog to view + re-enable suppressed sanitization
        warnings (V3 v0.3.4)."""
        from .sanitization_suppression_dialog import (
            SanitizationSuppressionDialog,
        )
        dlg = SanitizationSuppressionDialog(parent=self)
        dlg.exec()

    def _open_settings(self) -> None:
        """Open the application settings dialog."""
        from .permission_guards import perm_check
        if not perm_check("access_settings"):
            QMessageBox.warning(
                self, "Settings not permitted",
                "The Settings dialog is disabled by your administrator "
                "(capability: access_settings).",
            )
            return
        from .settings_dialog import SettingsDialog

        dlg = SettingsDialog(self._settings, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        # Persist all settings.
        self._settings.setValue(
            "remember_layout", dlg.result_remember_layout()
        )
        self._settings.setValue(
            "global_env", dlg.result_global_env_text()
        )
        self._settings.setValue(
            "global_env_override", dlg.result_override_tool_env()
        )
        self._settings.setValue(
            "global_path_prepend", dlg.result_global_path_text()
        )
        self._settings.setValue(
            "global_path_override", dlg.result_override_tool_path()
        )
        new_perm_path = dlg.result_permissions_path()
        old_perm_path = self._settings.value("permissions_path", "", type=str)
        self._settings.setValue("permissions_path", new_perm_path)
        if new_perm_path != old_perm_path:
            from ..core.permissions import reset_cached_permissions
            reset_cached_permissions()
        # Settings INI path (stored in the current INI as a redirect).
        new_settings_path = dlg.result_settings_path()
        self._settings.setValue("settings_path", new_settings_path)
        new_pc_path = dlg.result_personal_configs_path()
        self._settings.setValue("personal_configs_path", new_pc_path)
        self.statusBar().showMessage("Settings saved.", 3000)
