"""Editable tree-view launcher for .scriptreetree files.

Responsibilities:

- **Launch**: double-clicking a leaf loads the referenced .scriptree
  file and emits ``toolSelected``; the main window swaps to a
  ``ToolRunnerView`` for that tool.
- **Edit**: the tree is a first-class editor. Drag-drop reorders
  items internally, external ``.scriptree`` files can be dropped from
  File Explorer, and a toolbar / context menu provides explicit
  folder creation, removal, and renaming.
- **Save**: walk the QTreeWidget back into a ``TreeDef`` and write it
  to disk. Leaf paths are serialized relative to the .scriptreetree
  file's directory when possible (portable) and absolute otherwise.

Dirty-state handling: any edit sets ``_dirty=True`` and appends ``*``
to the title. ``treeModified`` is emitted so the main window can
reflect the state in its own title / save action.

## Qt drag-drop model

Qt's ``InternalMove`` mode handles folder/leaf reparenting natively
when items have the right flags set — folders get
``ItemIsDropEnabled``, leaves don't. External drops (from File
Explorer) are accepted by overriding ``dragEnterEvent``,
``dragMoveEvent`` and ``dropEvent`` in the ``_EditableTreeWidget``
subclass below; the override only intercepts drops that carry URLs
and passes everything else through to Qt's internal handling so
reordering still works.
"""
from __future__ import annotations

import os.path
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.io import (
    check_circular_tree_refs,
    collect_scriptreetree_refs,
    load_tool,
    load_tree,
    save_tree,
)
from ..core.model import ToolDef, TreeDef, TreeNode


# Qt role used to store a leaf's absolute path on its QTreeWidgetItem.
# A non-empty value here is the defining characteristic of a leaf;
# folders have empty data at this role.
_ROLE_PATH = Qt.ItemDataRole.UserRole

# Qt role for .scriptreetree subtree references. When set, the item
# is a subtree node: it looks like a folder but its children are
# loaded from the referenced .scriptreetree file.
_ROLE_SUBTREE = Qt.ItemDataRole.UserRole + 1


def _is_leaf(item: QTreeWidgetItem) -> bool:
    return bool(item.data(0, _ROLE_PATH)) and not bool(
        item.data(0, _ROLE_SUBTREE)
    )


def _is_subtree(item: QTreeWidgetItem) -> bool:
    return bool(item.data(0, _ROLE_SUBTREE))


def _is_folder(item: QTreeWidgetItem) -> bool:
    return not _is_leaf(item) and not _is_subtree(item)


# --- editable tree widget --------------------------------------------------

class _EditableTreeWidget(QTreeWidget):
    """QTreeWidget subclass that accepts external .scriptree file drops.

    Internal reordering (drag an item onto another folder, or between
    siblings) uses Qt's built-in ``InternalMove`` handling — we don't
    touch it. External drops of ``.scriptree`` files from Explorer are
    intercepted here and turned into ``fileDropped`` signals so the
    launcher can add a leaf for each dropped file.
    """

    fileDropped = Signal(str, object)
    """Emitted for each external .scriptree file drop.

    Args: (file_path, target_item_or_None). target is the QTreeWidgetItem
    under the cursor at drop time, or None if dropped on empty space.
    """

    itemReordered = Signal()
    """Emitted after an internal drag-drop reparents or reorders an item."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.DoubleClicked
        )

    # --- drag/drop overrides ---

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and self._any_accepted_url(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls() and self._any_accepted_url(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        md = event.mimeData()
        if md.hasUrls():
            # External drop from Explorer (or anything that produces
            # file:// URLs). Emit one signal per .scriptree path and
            # let the launcher decide where to put each.
            pos = event.position().toPoint()
            target = self.itemAt(pos)
            emitted = False
            for url in md.urls():
                if not url.isLocalFile():
                    continue
                path = url.toLocalFile()
                low = path.lower()
                if low.endswith(".scriptree") or low.endswith(
                    ".scriptreetree"
                ):
                    self.fileDropped.emit(path, target)
                    emitted = True
            if emitted:
                event.acceptProposedAction()
                return
            # Drop had URLs but none were .scriptree — refuse silently.
            event.ignore()
            return
        # Not a URL drop → let Qt handle it as InternalMove.
        super().dropEvent(event)
        self.itemReordered.emit()

    # --- helpers ---

    @staticmethod
    def _any_accepted_url(event: QDragEnterEvent | QDragMoveEvent) -> bool:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                low = url.toLocalFile().lower()
                if low.endswith(".scriptree") or low.endswith(
                    ".scriptreetree"
                ):
                    return True
        return False


# --- main launcher view ----------------------------------------------------

class TreeLauncherView(QWidget):
    """Editable .scriptreetree launcher with drag-drop and save."""

    toolSelected = Signal(object, str)
    """Emitted when the user double-clicks a leaf. Args: (ToolDef, path)."""

    treeModified = Signal(bool)
    """Emitted when dirty state changes. Arg: new dirty flag."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tree_file: Path | None = None
        self._tree: TreeDef | None = None
        self._dirty = False
        # Set of resolved absolute paths whose tool is currently
        # running. Updated by MainWindow via ``mark_running``; used
        # both to style the matching leaf items and to re-apply the
        # decoration when the tree reloads or is rebuilt.
        self._running_paths: set[str] = set()
        # Guard set for subtree expansion — prevents infinite
        # recursion when .scriptreetree files form a cycle.
        self._expanding_paths: set[str] = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._title = QLabel("<i>No tree loaded.</i>")
        layout.addWidget(self._title)

        # Toolbar row.
        tb = QHBoxLayout()
        tb.setSpacing(4)
        self._btn_new_folder = QPushButton("+ Folder")
        self._btn_new_folder.setToolTip("Create a new folder (at root or inside selected folder)")
        self._btn_new_folder.clicked.connect(self._add_folder)
        self._btn_add_tool = QPushButton("+ Tool...")
        self._btn_add_tool.setToolTip("Add one or more .scriptree files")
        self._btn_add_tool.clicked.connect(self._add_tool_via_dialog)
        self._btn_remove = QPushButton("\u2212")  # minus sign
        self._btn_remove.setFixedWidth(32)
        self._btn_remove.setToolTip("Remove the selected item")
        self._btn_remove.clicked.connect(self._remove_selected)
        self._btn_save = QPushButton("Save")
        self._btn_save.setToolTip("Save tree to its .scriptreetree file")
        self._btn_save.clicked.connect(self._save_tree)
        self._btn_configs = QPushButton("Configs...")
        self._btn_configs.setToolTip(
            "Edit tree-level configurations — map each tool to a "
            "named configuration for standalone mode."
        )
        self._btn_configs.clicked.connect(self._edit_tree_configs)
        tb.addWidget(self._btn_new_folder)
        tb.addWidget(self._btn_add_tool)
        tb.addWidget(self._btn_remove)
        tb.addStretch(1)
        tb.addWidget(self._btn_configs)
        tb.addWidget(self._btn_save)
        layout.addLayout(tb)

        # Editable tree widget.
        self._tree_widget = _EditableTreeWidget()
        self._tree_widget.setHeaderLabel("Tools")
        self._tree_widget.itemDoubleClicked.connect(self._on_item_activated)
        self._tree_widget.fileDropped.connect(self._on_file_dropped)
        self._tree_widget.itemReordered.connect(self._mark_dirty)
        self._tree_widget.itemChanged.connect(self._on_item_changed)
        self._tree_widget.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._tree_widget.customContextMenuRequested.connect(
            self._show_context_menu
        )
        layout.addWidget(self._tree_widget, stretch=1)

        self._update_title()

    # --- public API ------------------------------------------------------

    def load(self, path: str) -> None:
        try:
            tree = load_tree(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Load error", str(e))
            return
        self._tree_file = Path(path).resolve()
        self._tree = tree

        # Check write permissions for read-only enforcement.
        from ..core.permissions import check_write_access
        access = check_write_access(self._tree_file)
        self._tree_read_only: bool = not access.fully_writable

        self._tree_widget.clear()
        # Add the root tree file to the expanding-paths guard so that
        # subtrees referencing us back are caught as circular.
        root_key = str(self._tree_file)
        self._expanding_paths.add(root_key)
        try:
            for node in tree.nodes:
                self._add_node_item(node, parent=None)
        finally:
            self._expanding_paths.discard(root_key)
        self._tree_widget.expandAll()
        self._dirty = False
        self._update_title()
        self._refresh_toolbar_for_permissions()
        self.treeModified.emit(False)

    def new_tree(self, name: str = "Untitled tree") -> None:
        """Start a fresh empty tree not yet bound to a file on disk."""
        self._tree_file = None
        self._tree = TreeDef(name=name, nodes=[])
        self._tree_widget.clear()
        self._dirty = True
        self._update_title()
        self.treeModified.emit(True)

    def is_dirty(self) -> bool:
        return self._dirty

    def tree_file(self) -> Path | None:
        return self._tree_file

    def save(self) -> bool:
        """Write the tree to disk. Returns True on success."""
        return self._save_tree()

    def mark_running(self, path: str, running: bool) -> None:
        """Visually flag the leaf for ``path`` as running or idle.

        ``path`` is the resolved absolute path of the tool file. The
        launcher tracks running state internally so that re-loading or
        rebuilding the tree preserves the indicator. Leaves that appear
        in multiple places in the tree are all updated.
        """
        if not path:
            return
        try:
            key = str(Path(path).resolve())
        except OSError:
            key = path
        if running:
            self._running_paths.add(key)
        else:
            self._running_paths.discard(key)
        for item in self._find_leaf_items(key):
            self._apply_running_decoration(item, running)

    def is_marked_running(self, path: str) -> bool:
        """Return True if ``path`` is currently flagged as running."""
        try:
            key = str(Path(path).resolve())
        except OSError:
            key = path
        return key in self._running_paths

    def _find_leaf_items(self, abs_path: str) -> list[QTreeWidgetItem]:
        """Return every leaf item whose stored path resolves to ``abs_path``."""
        hits: list[QTreeWidgetItem] = []
        def walk(item: QTreeWidgetItem) -> None:
            if _is_leaf(item):
                stored = item.data(0, _ROLE_PATH)
                if stored:
                    try:
                        if str(Path(stored).resolve()) == abs_path:
                            hits.append(item)
                    except OSError:
                        if stored == abs_path:
                            hits.append(item)
            for i in range(item.childCount()):
                walk(item.child(i))
        for i in range(self._tree_widget.topLevelItemCount()):
            walk(self._tree_widget.topLevelItem(i))
        return hits

    def _apply_running_decoration(
        self, item: QTreeWidgetItem, running: bool
    ) -> None:
        """Apply or clear the 'running' visual state on a leaf item."""
        stored = item.data(0, _ROLE_PATH)
        if not stored:
            return
        base_label = Path(stored).stem
        font = item.font(0)
        if running:
            item.setText(0, f"\u25B6 {base_label}")  # ▶ play arrow
            font.setBold(True)
            font.setItalic(True)
            item.setForeground(0, QColor("#1a7f37"))  # green
        else:
            item.setText(0, base_label)
            font.setBold(False)
            font.setItalic(False)
            # Clear the foreground brush by installing a default one.
            item.setForeground(0, QColor())
        item.setFont(0, font)

    # --- item construction ----------------------------------------------

    def _add_node_item(
        self, node: TreeNode, parent: QTreeWidgetItem | None
    ) -> None:
        if node.type == "folder":
            item = self._new_folder_item(node.name or "(folder)")
            if parent is None:
                self._tree_widget.addTopLevelItem(item)
            else:
                parent.addChild(item)
            for child in node.children:
                self._add_node_item(child, parent=item)
        else:
            assert node.path is not None
            full_path = self._resolve_path(node.path)
            abs_str = str(full_path)
            if abs_str.lower().endswith(".scriptreetree"):
                item = self._new_subtree_item(abs_str)
                if parent is None:
                    self._tree_widget.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                self._expand_subtree(item)
            else:
                item = self._new_leaf_item(abs_str)
                if parent is None:
                    self._tree_widget.addTopLevelItem(item)
                else:
                    parent.addChild(item)

    def _new_folder_item(self, name: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([name])
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
            | Qt.ItemFlag.ItemIsEditable
        )
        # Folders have no path data — that's how _is_folder distinguishes
        # them from leaves.
        return item

    def _new_leaf_item(self, abs_path: str) -> QTreeWidgetItem:
        stem = Path(abs_path).stem
        item = QTreeWidgetItem([stem])
        item.setData(0, _ROLE_PATH, abs_path)
        item.setToolTip(0, abs_path)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            # NOT ItemIsDropEnabled → can't drop onto a leaf
            # NOT ItemIsEditable → leaf labels are derived from filename
        )
        # If this path is currently running, re-apply the indicator
        # so tree reloads / drag-drop rebuilds don't clear it.
        try:
            key = str(Path(abs_path).resolve())
        except OSError:
            key = abs_path
        if key in self._running_paths:
            self._apply_running_decoration(item, True)
        return item

    def _new_subtree_item(self, abs_path: str) -> QTreeWidgetItem:
        """Create a QTreeWidgetItem for a .scriptreetree reference.

        Subtree items look like folders (expandable, with children
        loaded from the referenced file) but are **not** editable or
        drop-enabled — their structure comes from the referenced file.
        """
        stem = Path(abs_path).stem
        item = QTreeWidgetItem([f"\U0001F4C2 {stem}"])  # 📂
        item.setData(0, _ROLE_PATH, abs_path)
        item.setData(0, _ROLE_SUBTREE, abs_path)
        item.setToolTip(0, f"Subtree: {abs_path}")
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            # NOT ItemIsDropEnabled — can't drop into a subtree
            # NOT ItemIsEditable — label derived from filename
        )
        return item

    def _expand_subtree(self, item: QTreeWidgetItem) -> None:
        """Load the .scriptreetree file and populate *item* with its nodes.

        Children are read-only: they come from the referenced file.
        If the file can't be loaded, a single error-child is shown.
        Circular references are detected via ``_expanding_paths``.
        """
        subtree_path = item.data(0, _ROLE_SUBTREE)
        if not subtree_path:
            return
        resolved = str(Path(subtree_path).resolve())
        # Cycle guard: if we're already expanding this file higher in
        # the call stack, show an error instead of recursing forever.
        if resolved in self._expanding_paths:
            while item.childCount() > 0:
                item.removeChild(item.child(0))
            err = QTreeWidgetItem(["(circular reference)"])
            err.setFlags(Qt.ItemFlag.ItemIsEnabled)
            err.setForeground(0, QColor("red"))
            item.addChild(err)
            return
        self._expanding_paths.add(resolved)
        try:
            # Remove any existing children (re-expand / refresh).
            while item.childCount() > 0:
                item.removeChild(item.child(0))
            try:
                sub_tree = load_tree(subtree_path)
            except Exception as e:  # noqa: BLE001
                err = QTreeWidgetItem([f"(load error: {e})"])
                err.setFlags(Qt.ItemFlag.ItemIsEnabled)
                err.setForeground(0, QColor("red"))
                item.addChild(err)
                return
            # Resolve paths relative to the subtree file, not the parent tree.
            saved_tree_file = self._tree_file
            self._tree_file = Path(subtree_path).resolve()
            try:
                for node in sub_tree.nodes:
                    self._add_node_item(node, parent=item)
            finally:
                self._tree_file = saved_tree_file
            item.setExpanded(True)
        finally:
            self._expanding_paths.discard(resolved)

    # --- path helpers ----------------------------------------------------

    def _resolve_path(self, rel: str) -> Path:
        p = Path(rel)
        if p.is_absolute():
            return p.resolve()
        if self._tree_file is not None:
            return (self._tree_file.parent / p).resolve()
        return p.resolve()

    def _maybe_relative(self, abs_path: str) -> str:
        """Serialize a leaf path relative to the tree file when possible.

        Uses ``os.path.relpath`` so parent-directory paths (``../foo``)
        are handled; falls back to absolute when the paths live on
        different drives (Windows) or when no tree file is set.
        Output is normalized to forward slashes.
        """
        if self._tree_file is None:
            return str(Path(abs_path)).replace("\\", "/")
        try:
            p = Path(abs_path).resolve()
            base = self._tree_file.parent.resolve()
            rel = os.path.relpath(p, base)
        except ValueError:
            # Different drives on Windows.
            return str(Path(abs_path)).replace("\\", "/")
        rel_posix = rel.replace("\\", "/")
        if not rel_posix.startswith(("./", "../")) and not rel_posix.startswith("/"):
            rel_posix = "./" + rel_posix
        return rel_posix

    # --- dirty state -----------------------------------------------------

    def _mark_dirty(self, *args) -> None:
        if not self._dirty:
            self._dirty = True
            self._update_title()
            self.treeModified.emit(True)

    def _update_title(self) -> None:
        if self._tree is None:
            self._title.setText("<i>No tree loaded.</i>")
            self._btn_save.setEnabled(False)
            return
        marker = " \u25CF" if self._dirty else ""  # ● unsaved marker
        ro_tag = " \U0001f512" if getattr(self, "_tree_read_only", False) else ""
        src = (
            self._tree_file.name if self._tree_file is not None else "(unsaved)"
        )
        self._title.setText(
            f"<b>{self._tree.name}</b>{marker}{ro_tag}"
            f"<br><span style='color:#666; font-size:10px'>{src}</span>"
        )
        self._btn_save.setEnabled(
            not getattr(self, "_tree_read_only", False)
        )

    def _refresh_toolbar_for_permissions(self) -> None:
        """Disable toolbar buttons when the tree file is read-only."""
        ro = getattr(self, "_tree_read_only", False)
        self._btn_save.setEnabled(not ro)
        self._btn_new_folder.setEnabled(not ro)
        self._btn_add_tool.setEnabled(not ro)
        self._btn_remove.setEnabled(not ro)
        self._btn_configs.setEnabled(not ro)
        if ro:
            from PySide6.QtWidgets import QAbstractItemView
            self._tree_widget.setDragDropMode(
                QAbstractItemView.DragDropMode.NoDragDrop
            )

    def _on_item_changed(self, item: QTreeWidgetItem, col: int) -> None:
        # Fires when the user renames a folder inline. Mark dirty.
        if col == 0:
            self._mark_dirty()

    # --- toolbar actions -------------------------------------------------

    def _add_folder(self) -> None:
        name, ok = QInputDialog.getText(
            self, "New folder", "Folder name:"
        )
        if not ok or not name.strip():
            return
        item = self._new_folder_item(name.strip())
        selected = self._tree_widget.currentItem()
        if selected is not None and _is_folder(selected):
            selected.addChild(item)
            selected.setExpanded(True)
        else:
            self._tree_widget.addTopLevelItem(item)
        if self._tree is None:
            # Auto-start an unsaved tree if the user is creating folders
            # without having loaded one first.
            self._tree = TreeDef(name="Untitled tree", nodes=[])
        self._mark_dirty()

    def _add_tool_via_dialog(self) -> None:
        start_dir = str(self._tree_file.parent) if self._tree_file else ""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add .scriptree / .scriptreetree files", start_dir,
            "ScripTree files (*.scriptree *.scriptreetree);;All files (*)",
        )
        if not paths:
            return
        target = self._tree_widget.currentItem()
        parent = (
            target if target is not None and _is_folder(target) else None
        )
        for p in paths:
            if not self._check_no_cycle(p):
                continue
            self._add_leaf_at(p, parent)
        if self._tree is None:
            self._tree = TreeDef(name="Untitled tree", nodes=[])
        self._mark_dirty()

    def _remove_selected(self) -> None:
        selected = self._tree_widget.currentItem()
        if selected is None:
            return
        parent = selected.parent()
        if parent is None:
            idx = self._tree_widget.indexOfTopLevelItem(selected)
            self._tree_widget.takeTopLevelItem(idx)
        else:
            parent.removeChild(selected)
        self._mark_dirty()

    def _save_tree(self) -> bool:
        if self._tree is None:
            return False
        if getattr(self, "_tree_read_only", False):
            QMessageBox.warning(
                self, "Read-only",
                "This tree file is read-only and cannot be saved.",
            )
            return False
        if self._tree_file is None:
            path = self._ask_save_path()
            if not path:
                return False
            self._tree_file = Path(path).resolve()
        tree_def = self._build_tree_def()
        try:
            save_tree(tree_def, self._tree_file)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Save error", str(e))
            return False
        self._tree = tree_def
        self._dirty = False
        self._update_title()
        self.treeModified.emit(False)
        return True

    def _ask_save_path(self) -> str | None:
        default_name = (
            self._tree.name if self._tree is not None else "tree"
        ) + ".scriptreetree"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save .scriptreetree", default_name,
            "ScripTree tree files (*.scriptreetree);;All files (*)",
        )
        return path or None

    # --- file-drop handler ----------------------------------------------

    def _on_file_dropped(
        self, path: str, target_item: QTreeWidgetItem | None
    ) -> None:
        if not self._check_no_cycle(path):
            return
        # If dropped on a folder, add as child of that folder. If
        # dropped on a leaf, add as a sibling of that leaf. If dropped
        # on empty space, add at the root.
        parent: QTreeWidgetItem | None = None
        if target_item is not None:
            if _is_folder(target_item):
                parent = target_item
                target_item.setExpanded(True)
            else:
                parent = target_item.parent()
        self._add_leaf_at(path, parent)
        if self._tree is None:
            self._tree = TreeDef(name="Untitled tree", nodes=[])
        self._mark_dirty()

    def _add_leaf_at(
        self, path: str, parent: QTreeWidgetItem | None
    ) -> None:
        abs_path = str(Path(path).resolve())
        if abs_path.lower().endswith(".scriptreetree"):
            item = self._new_subtree_item(abs_path)
            if parent is None:
                self._tree_widget.addTopLevelItem(item)
            else:
                parent.addChild(item)
            self._expand_subtree(item)
        else:
            item = self._new_leaf_item(abs_path)
            if parent is None:
                self._tree_widget.addTopLevelItem(item)
            else:
                parent.addChild(item)

    # --- circular reference check ----------------------------------------

    def _check_no_cycle(self, path: str) -> bool:
        """Return True if adding *path* won't create a circular reference.

        Only relevant for .scriptreetree files. .scriptree files always
        pass. Shows a warning dialog and returns False on cycle.
        """
        if not path.lower().endswith(".scriptreetree"):
            return True
        resolved = str(Path(path).resolve())
        # Check 1: is this the same file as our own tree?
        if self._tree_file is not None:
            own = str(self._tree_file.resolve())
            if resolved == own:
                QMessageBox.warning(
                    self,
                    "Circular reference",
                    "Cannot add a tree file to itself.",
                )
                return False
        # Check 2: does the referenced tree (transitively) reference us?
        if self._tree_file is not None:
            cycle = check_circular_tree_refs(resolved)
            if cycle is not None:
                own = str(self._tree_file.resolve())
                if own in cycle:
                    chain = " → ".join(Path(p).name for p in cycle)
                    QMessageBox.warning(
                        self,
                        "Circular reference",
                        f"Adding this subtree would create a cycle:\n\n"
                        f"{chain}\n\n"
                        f"The reference was not added.",
                    )
                    return False
            # Check 3: does the subtree already reference us transitively?
            # Build a temporary tree with the new ref to check the full
            # graph including the addition.
            try:
                sub = load_tree(resolved)
                refs = collect_scriptreetree_refs(sub, resolved)
                own = str(self._tree_file.resolve())
                if own in refs:
                    QMessageBox.warning(
                        self,
                        "Circular reference",
                        f"The subtree '{Path(resolved).name}' already "
                        f"references this tree file. Adding it would "
                        f"create a cycle.",
                    )
                    return False
            except Exception:  # noqa: BLE001
                pass  # can't load — let it fail later on expand
        return True

    # --- context menu ----------------------------------------------------

    def _show_context_menu(self, pos) -> None:
        item = self._tree_widget.itemAt(pos)
        menu = QMenu(self)
        if item is not None:
            if _is_leaf(item):
                act_open = QAction("Open", self)
                act_open.triggered.connect(
                    lambda _=False, it=item: self._on_item_activated(it, 0)
                )
                menu.addAction(act_open)
            if _is_subtree(item):
                act_refresh = QAction("Refresh subtree", self)
                act_refresh.triggered.connect(
                    lambda _=False, it=item: self._expand_subtree(it)
                )
                menu.addAction(act_refresh)
            act_remove = QAction("Remove", self)
            act_remove.triggered.connect(self._remove_selected)
            menu.addAction(act_remove)
            if _is_folder(item):
                act_rename = QAction("Rename", self)
                act_rename.triggered.connect(
                    lambda _=False, it=item: self._tree_widget.editItem(it, 0)
                )
                menu.addAction(act_rename)
            menu.addSeparator()
        act_new_folder = QAction("New folder", self)
        act_new_folder.triggered.connect(self._add_folder)
        menu.addAction(act_new_folder)
        act_add_tool = QAction("Add tool...", self)
        act_add_tool.triggered.connect(self._add_tool_via_dialog)
        menu.addAction(act_add_tool)
        menu.exec(self._tree_widget.viewport().mapToGlobal(pos))

    # --- launch (double-click) ------------------------------------------

    def _on_item_activated(self, item: QTreeWidgetItem, _col: int) -> None:
        # Subtree items: double-click refreshes their children.
        if _is_subtree(item):
            self._expand_subtree(item)
            return
        path_data = item.data(0, _ROLE_PATH)
        if not path_data:
            return  # folder
        # If the referenced .scriptree file is missing, offer the
        # recovery dialog instead of a generic critical popup — the
        # path stays copy-pasteable, and the user can Browse to a
        # replacement if they have permission to edit the tree.
        if not Path(path_data).exists():
            self._offer_missing_tool_recovery(item, path_data)
            return
        try:
            tool = load_tool(path_data)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Load error", str(e))
            return
        self.toolSelected.emit(tool, path_data)

    def _offer_missing_tool_recovery(
        self, item: QTreeWidgetItem, missing_path: str
    ) -> None:
        """Show the recovery dialog for a missing .scriptree leaf.

        If the user picks a replacement and has permission to edit the
        tree, update the leaf's stored path and persist the tree.
        """
        from .recovery_dialog import MissingFileRecoveryDialog
        from ..core.permissions import get_app_permissions

        perms = get_app_permissions()
        # Replacing the leaf path modifies the tree — so the user needs
        # both edit_tree_structure AND the ability to save the tree.
        can_replace = (
            perms.can("edit_tree_structure")
            and perms.can("save_scriptreetree")
            and not getattr(self, "_tree_read_only", False)
        )

        dlg = MissingFileRecoveryDialog(
            self,
            title="Tool file not found",
            message=(
                f"The tool file referenced by this tree leaf no longer "
                f"exists. This usually means the file was moved, "
                f"renamed, or deleted after the tree was saved."
            ),
            missing_path=missing_path,
            allow_replace=can_replace,
            file_filter="ScripTree files (*.scriptree);;All files (*)",
            browse_caption="Select replacement .scriptree file",
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_path = dlg.selected_replacement()
        if not new_path:
            return

        # Update the item's stored path, persist the tree, and open the
        # tool from its new location.
        resolved = str(Path(new_path).resolve())
        item.setData(0, _ROLE_PATH, resolved)
        # Update the visible label from the new file's tool.name.
        try:
            tool = load_tool(resolved)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, "Replacement failed",
                f"Could not load the replacement file:\n{e}",
            )
            return
        item.setText(0, tool.name or Path(resolved).stem)
        self._mark_dirty()
        self._save_tree()  # quiet; only writes if possible
        self.toolSelected.emit(tool, resolved)

    # --- QTreeWidget → TreeDef rebuild ----------------------------------

    def _build_tree_def(self) -> TreeDef:
        assert self._tree is not None
        nodes: list[TreeNode] = []
        for i in range(self._tree_widget.topLevelItemCount()):
            top = self._tree_widget.topLevelItem(i)
            node = self._item_to_node(top)
            if node is not None:
                nodes.append(node)
        return TreeDef(name=self._tree.name, nodes=nodes)

    def _item_to_node(self, item: QTreeWidgetItem) -> TreeNode | None:
        if _is_subtree(item):
            # Subtree items are serialized as leaves pointing to
            # .scriptreetree files — their children are loaded
            # dynamically at display time, not persisted.
            abs_path = item.data(0, _ROLE_SUBTREE)
            if not abs_path:
                return None
            return TreeNode(type="leaf", path=self._maybe_relative(abs_path))
        if _is_leaf(item):
            abs_path = item.data(0, _ROLE_PATH)
            if not abs_path:
                return None
            return TreeNode(type="leaf", path=self._maybe_relative(abs_path))
        children: list[TreeNode] = []
        for i in range(item.childCount()):
            child = self._item_to_node(item.child(i))
            if child is not None:
                children.append(child)
        return TreeNode(
            type="folder", name=item.text(0), children=children
        )

    # --- tree configurations -----------------------------------------------

    def _edit_tree_configs(self) -> None:
        """Open the tree configuration editor dialog."""
        if self._tree_file is None or self._tree is None:
            QMessageBox.information(
                self,
                "No tree loaded",
                "Load or save a .scriptreetree first.",
            )
            return
        from .tree_config_editor import TreeConfigEditorDialog

        dlg = TreeConfigEditorDialog(
            self._tree_file,
            self._tree,
            read_only=getattr(self, "_tree_read_only", False),
            parent=self,
        )
        dlg.exec()
