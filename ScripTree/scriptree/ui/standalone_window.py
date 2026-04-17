"""Lightweight standalone window for running tools outside the IDE.

Two modes:

- **Single tool** — one :class:`ToolRunnerView` with optional output
  in a vertical splitter.  No docks, no tree sidebar.
- **Tree mode** — a :class:`QTabWidget` with one ToolRunnerView per
  leaf tool in the tree.  Each tab applies its own configuration
  (from ``TreeNode.configuration``).

The window reads :class:`UIVisibility` from the specified configuration
and applies it at construction time. The output pane is shown/hidden
by reparenting into or out of the splitter (there are no dock widgets).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.configs import (
    SAFETREE_CONFIG_NAME,
    UIVisibility,
    ensure_safetree_config,
    load_configs,
    load_tree_configs,
)
from ..core.io import load_tool, load_tree
from ..core.model import ToolDef, TreeDef, TreeNode


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
        """Create a standalone window for a single tool."""
        from .tool_runner import ToolRunnerView

        win = cls(title=f"ScripTree — {tool.name}", parent=parent)
        runner = ToolRunnerView(tool, file_path=file_path)
        runner._standalone_mode = True

        if config_name:
            runner.apply_named_configuration(config_name)
        else:
            # Re-apply the active configuration now that standalone
            # mode is set — the initial apply during __init__ ran
            # before _standalone_mode was True, so visibility flags
            # weren't applied.
            cfg = runner._cfg_set.active_config()
            runner._apply_configuration(cfg)

        vis = runner.active_visibility

        # Build a splitter with form + output (if output is visible).
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(runner.form_panel)
        if vis.output_pane:
            splitter.addWidget(runner.output_panel)
            splitter.setStretchFactor(0, 3)
            splitter.setStretchFactor(1, 2)
        else:
            splitter.setStretchFactor(0, 1)

        layout.addWidget(splitter)
        win.setCentralWidget(central)

        # Keep a reference so the runner isn't garbage collected.
        win._runner = runner  # type: ignore[attr-defined]
        win._runners: list[ToolRunnerView] = [runner]  # type: ignore[attr-defined]

        # Listen for visibility changes from the runner.
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
        tabs = QTabWidget()
        # Default: scroll buttons for tab overflow.
        tabs.setElideMode(Qt.TextElideMode.ElideNone)
        tabs.setUsesScrollButtons(True)
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

        # Flatten the tree to leaf nodes.
        leaves = _collect_leaves(tree_def.nodes)

        for node in leaves:
            if not node.path:
                continue
            tool_path = (tree_dir / node.path).resolve()
            if not tool_path.exists():
                continue
            if str(tool_path).endswith(".scriptreetree"):
                continue
            try:
                tool = load_tool(str(tool_path))
            except Exception:  # noqa: BLE001
                continue

            runner = ToolRunnerView(tool, file_path=str(tool_path))
            runner._standalone_mode = True

            # Resolve configuration name: overrides > tree config > node.
            rel_path = node.path  # relative path as stored in the tree
            cfg_name = (
                overrides.get(str(tool_path))
                or tree_cfg_mapping.get(rel_path or "")
                or node.configuration
            )

            if cfg_name:
                applied = runner.apply_named_configuration(cfg_name)
                if not applied:
                    # Config doesn't exist in the tool — create/overwrite
                    # the reserved safetree config and apply that.
                    # Guard: only write if the sidecar is writable.
                    from ..core.permissions import check_write_access
                    access = check_write_access(tool_path)
                    if access.sidecar_writable:
                        ensure_safetree_config(str(tool_path))
                        # Reload configs in the runner after writing sidecar.
                        runner._load_or_init_configs()
                        runner._refresh_cfg_combo()
                        runner.apply_named_configuration(SAFETREE_CONFIG_NAME)
            else:
                # No specific config — re-apply the active config now
                # that standalone mode is set (visibility wasn't applied
                # during __init__ because _standalone_mode was False).
                cfg = runner._cfg_set.active_config()
                runner._apply_configuration(cfg)

            vis = runner.active_visibility

            # Build a per-tab widget with form + optional output.
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

            tabs.addTab(tab, tool.name)
            runners.append(runner)
            runner.visibilityChanged.connect(win._on_visibility_changed)

        win.setCentralWidget(tabs)
        win._runners = runners  # type: ignore[attr-defined]
        win._tabs = tabs  # type: ignore[attr-defined]

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
        """Handle runner visibility changes (no docks to toggle here)."""
        # In standalone mode the output pane visibility is set at
        # construction time. Dynamic toggling would require more
        # complex splitter management — for now we just note it.
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
            act.triggered.connect(
                lambda checked=False, c=cmd, d=work_dir: _sp.Popen(
                    split_command(c), shell=False, cwd=d,
                )
            )
        menu.addAction(act)


def _show_tab_mode_menu(
    tabs: QTabWidget, pos: Any, win: QWidget
) -> None:
    """Show a context menu for switching tab overflow mode."""
    from PySide6.QtGui import QAction, QActionGroup
    from PySide6.QtWidgets import QMenu

    menu = QMenu(win)

    group = QActionGroup(menu)
    group.setExclusive(True)

    act_scroll = QAction("Scroll arrows", menu)
    act_scroll.setCheckable(True)
    act_scroll.setChecked(tabs.usesScrollButtons())
    group.addAction(act_scroll)
    menu.addAction(act_scroll)

    act_wrap = QAction("Expand window", menu)
    act_wrap.setCheckable(True)
    act_wrap.setChecked(
        not tabs.usesScrollButtons()
        and tabs.tabBar().documentMode()
    )
    group.addAction(act_wrap)
    menu.addAction(act_wrap)

    chosen = menu.exec(tabs.tabBar().mapToGlobal(pos))
    if chosen is act_scroll:
        tabs.setUsesScrollButtons(True)
        tabs.tabBar().setDocumentMode(False)
    elif chosen is act_wrap:
        tabs.setUsesScrollButtons(False)
        tabs.tabBar().setDocumentMode(True)


def _collect_leaves(nodes: list[TreeNode]) -> list[TreeNode]:
    """Flatten a tree into a list of leaf nodes (depth-first)."""
    result: list[TreeNode] = []
    for node in nodes:
        if node.type == "leaf":
            result.append(node)
        elif node.type == "folder":
            result.extend(_collect_leaves(node.children))
    return result
