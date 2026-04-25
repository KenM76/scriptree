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
    runner._standalone_mode = True

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
    tabs.addTab(tab, tab_label)
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
