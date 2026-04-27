"""Main application window: menus, left-hand launcher, right-hand pane.

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

        act_new_probe = QAction("&New tool from executable...", self)
        act_new_probe.triggered.connect(self._new_from_executable)
        m_file.addAction(act_new_probe)

        act_new_blank = QAction("New &blank tool", self)
        act_new_blank.triggered.connect(self._new_blank)
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
        m_file.addAction(act_new_tree)

        self._act_save_tree = QAction("&Save tree", self)
        self._act_save_tree.setShortcut("Ctrl+S")
        self._act_save_tree.triggered.connect(self._save_tree)
        self._act_save_tree.setEnabled(False)
        m_file.addAction(self._act_save_tree)

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
        act_settings = QAction("&Settings...", self)
        act_settings.triggered.connect(self._open_settings)
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
        if self._launcher.save():
            self.statusBar().showMessage("Tree saved.")

    def _on_tree_modified(self, dirty: bool) -> None:
        self._act_save_tree.setEnabled(
            self._launcher.tree_file() is not None or dirty
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

    def _close_active_editor(self) -> None:
        if self._active_editor is None:
            return
        self._stack.removeWidget(self._active_editor)
        self._active_editor.deleteLater()
        self._active_editor = None

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

    def _open_settings(self) -> None:
        """Open the application settings dialog."""
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
