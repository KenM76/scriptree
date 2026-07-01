"""Editable tree-view launcher for .scriptreetree files.

## For humans

Responsibilities:

- **Launch**: single-clicking a leaf loads the referenced .scriptree
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

### Qt drag-drop model

Qt's ``InternalMove`` mode handles folder/leaf reparenting natively
when items have the right flags set — folders get
``ItemIsDropEnabled``, leaves don't. External drops (from File
Explorer) are accepted by overriding ``dragEnterEvent``,
``dragMoveEvent`` and ``dropEvent`` in the ``_EditableTreeWidget``
subclass below; the override only intercepts drops that carry URLs
and passes everything else through to Qt's internal handling so
reordering still works.

## For maintainers / LLMs

- Activation is ``itemClicked`` (single click on a leaf), NOT
  ``itemDoubleClicked`` — the human summary line above is kept
  authoritative. Double-click is intentionally NOT the launch
  gesture; do not rewire ``_on_item_activated`` to double-click or
  single-click leaf launching breaks.
- Right-click context menu targets the item *under the cursor*, not
  the prior selection: ``_show_context_menu`` calls
  ``setCurrentItem(item)`` first so selection-based actions (Remove,
  Edit) act on the hovered row. Preserve that select-then-build order.
- The context menu is debounced ~220 ms via ``_ctx_timer`` so a
  double-right-click (→ ``standaloneRequested``) does not first flash
  the menu. ``_on_right_double_click`` must ``stop()`` the timer and
  clear ``_pending_ctx_pos`` before emitting, or a stale menu fires
  after the standalone window opens.
- Double-right-click is delivered by ``_EditableTreeWidget``'s
  ``mouseDoubleClickEvent`` filtering ``Qt.RightButton`` →
  ``rightDoubleClicked`` signal; the left-button path still calls
  ``super()`` so Qt expand/collapse is intact. Keep the
  ``RightButton`` guard and the ``super()`` fall-through.
- ``_standalone_descriptor`` returns ``None`` for a missing/unloadable
  leaf path (file gone, or ``load_tool`` raised). Callers must treat
  ``None`` as "nothing to open" — emitting ``standaloneRequested``
  with it would crash the consumer.
- ``InternalMove`` correctness depends on the drop-enabled flags:
  folders get ``ItemIsDropEnabled``, leaves do NOT. Any new item
  factory must set these or leaves become illegal drop containers.
- ``dropEvent``/``dragMoveEvent`` overrides MUST pass non-URL events
  through to ``super()`` — short-circuiting them silently kills
  internal reorder. Only URL-bearing (external-file) drops are ours.
- ``rowsMoved`` → ``_on_rows_moved`` is the only dirty hook for
  drag-reorder; explicit add/remove/rename set ``_dirty`` directly.
  Any new mutation path must mark dirty + emit ``treeModified`` or
  the main window's save state goes stale (silent data loss).
- Path serialization is relative-when-possible, absolute-fallback,
  computed against the .scriptreetree's directory; do not switch to
  CWD-relative or saved trees become non-portable.
- Adding a subtree checks for cycles (``collect_scriptreetree_refs``)
  and refuses self/ancestor references; keep that guard before any
  new subtree-insert path.
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
    QIcon,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


# --- icons (v0.6.5) --------------------------------------------------------
#
# Tree rows are iconned the same way the cell/ring/forest popup menu
# is: a tool leaf shows its catalog's configured ``cell`` icon (or
# the OS file icon as a fallback), a subtree shows its catalog icon
# (or the OS folder icon), and a plain folder shows the OS folder
# icon — so the tree view and the launcher menus look consistent.

def _tv_std_icon(which) -> QIcon:  # noqa: ANN001
    app = QApplication.instance()
    return app.style().standardIcon(which) if app is not None else QIcon()


def _tv_catalog_icon(path, fallback) -> QIcon:  # noqa: ANN001
    try:
        from scriptree.core.cell_metadata import qicon_for_catalog
        ic = qicon_for_catalog(path)
        if ic is not None and not ic.isNull():
            return ic
    except Exception:  # noqa: BLE001
        pass
    return _tv_std_icon(fallback)

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
#: Optional per-leaf display_name override from the .scriptreetree.
#: If set, takes precedence over the tool's own name in the IDE tree
#: label and the standalone tab label. Stored as a string or None.
_ROLE_DISPLAY_NAME = Qt.ItemDataRole.UserRole + 2
#: Optional per-leaf configuration name from the .scriptreetree.
#: Preserved across save so users don't lose their tree-level config
#: overrides when they reorder the tree in the IDE.
_ROLE_CONFIGURATION = Qt.ItemDataRole.UserRole + 3

# Qt role for .scriptreetree subtree references. When set, the item
# is a subtree node: it looks like a folder but its children are
# loaded from the referenced .scriptreetree file.
_ROLE_SUBTREE = Qt.ItemDataRole.UserRole + 1

#: v0.8.0a96 — marks the single synthetic ROOT row that represents the opened
#: tree itself (its name / category / cell / menus).  Its children are the
#: tree's nodes.  A root is NOT a leaf, folder, or subtree: it's the container
#: for "the thing you opened", and selecting it edits the tree's own properties.
_ROLE_IS_ROOT = Qt.ItemDataRole.UserRole + 4

#: v0.8.0a103 — True on a SUBTREE item whose ``_expand_subtree`` populated its
#: children CLEANLY (no load-error / circular-reference placeholder).  The
#: inline-edit write-back only persists subtrees flagged True, so a subtree we
#: couldn't read is NEVER clobbered with a placeholder.
_ROLE_EXPAND_OK = Qt.ItemDataRole.UserRole + 5

#: v0.8.0a103 — per-node icon override (``TreeNode.icon`` / ``icon_data`` /
#: ``icon_format``), carried onto EVERY item kind (leaf, folder, subtree-ref) so
#: the editor's serialization (``_item_to_node``) round-trips them losslessly.
#: Before a103 these were silently dropped on every save — which both stripped
#: the override AND defeated the inline write-back's unchanged-skip guard
#: (the dropped fields made an unedited subtree compare "changed", churning the
#: file and stripping the metadata on a plain no-op Save).  These roles, plus
#: ``_ROLE_DISPLAY_NAME`` now also stored on FOLDERS and ``_ROLE_CONFIGURATION``
#: now also stored on SUBTREE refs, close that whole class of loss.
_ROLE_ICON = Qt.ItemDataRole.UserRole + 6
_ROLE_ICON_DATA = Qt.ItemDataRole.UserRole + 7
_ROLE_ICON_FORMAT = Qt.ItemDataRole.UserRole + 8

#: v0.8.0a103 (review fix) — a FOLDER's authored ``name`` as loaded from the
#: file, stored separately because the visible row label is ``display_name or
#: name`` (matching the runtime / popup).  Serialisation needs the authored name
#: to (a) round-trip a folder that has BOTH name + display_name without churn,
#: and (b) detect an inline RENAME: if the row's text no longer equals the
#: "shown" baseline (``display_name or name``), the user retyped the label — that
#: text becomes the new name and the now-contradictory display_name is dropped
#: (the rename wins everywhere).  ``None`` on folders created in the editor
#: (their label simply IS the name).
_ROLE_FOLDER_NAME = Qt.ItemDataRole.UserRole + 9


def _is_root(item: QTreeWidgetItem) -> bool:
    return bool(item.data(0, _ROLE_IS_ROOT))


def _is_leaf(item: QTreeWidgetItem) -> bool:
    return bool(item.data(0, _ROLE_PATH)) and not bool(
        item.data(0, _ROLE_SUBTREE)
    )


def _is_subtree(item: QTreeWidgetItem) -> bool:
    return bool(item.data(0, _ROLE_SUBTREE))


def _is_folder(item: QTreeWidgetItem) -> bool:
    # The root carries no path/subtree data either, so exclude it explicitly —
    # otherwise it would masquerade as a folder in the drop / serialise logic.
    return (
        not _is_leaf(item) and not _is_subtree(item) and not _is_root(item)
    )


def _churn_key(node: "TreeNode") -> tuple:
    """v0.8.0a103 — a comparison key for the inline-subtree write-back's
    unchanged-skip guard that is INSENSITIVE to leaf-path *form*.

    A subtree file may store a leaf path bare (``update_lib.scriptree``) or with
    Windows separators (``.\\nest\\n.scriptree``); ``load_tree`` preserves the
    on-disk string verbatim, but the editor always re-serialises through
    ``_maybe_relative`` as ``./forward/slash``.  Comparing raw ``TreeNode``
    equality would therefore see a (false) change on every plain Save of any
    parent that links such a subtree — silently rewriting a file the user never
    edited (ScripTree's own shipped management tree stores bare paths).  Folding
    a leading ``./`` and normalising slashes here means only a GENUINE structural
    or metadata change triggers a write; pure path-form differences are ignored
    (and the file keeps its original form untouched).  All other fields — name,
    configuration, display_name, the icon triplet, children — ARE compared, so
    real edits and metadata changes still write."""
    p = node.path
    if p:
        p = p.replace("\\", "/")
        if p.startswith("./"):
            p = p[2:]
    return (
        node.type,
        node.name or "",
        p,
        node.configuration or None,
        node.display_name or None,
        node.icon or "",
        node.icon_data or "",
        node.icon_format or "",
        tuple(_churn_key(c) for c in (node.children or [])),
    )


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

    rightDoubleClicked = Signal(object)
    """Emitted on a double **right**-click. Arg: viewport QPoint.

    Used to open the item under the cursor in standalone mode. A
    single right-click still raises the context menu (the launcher
    debounces the menu so a double-right doesn't flash it)."""

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

    # --- right double-click → standalone --------------------------------

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.RightButton:
            # Don't let the base class also treat this as an edit /
            # expand trigger; it's our "open standalone" gesture.
            self.rightDoubleClicked.emit(event.pos())
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # --- single right-click → context menu only (NEVER activation) -----
    #
    # v0.8.0a34+ -- pre-a34 the base QTreeWidget's mousePressEvent
    # treated a right-click as a "click" and emitted ``itemClicked``,
    # which is wired to ``_on_item_activated`` (line ~364) and
    # launches the tool in standalone mode.  Right-click thus
    # silently launched the program AND showed the context menu.
    # Now we intercept right-button press/release before the base
    # class can fire those signals.  The context menu still works
    # because ``customContextMenuRequested`` is emitted from a
    # separate ``contextMenuEvent()`` path that's independent of
    # the mouse-press click tracking.

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.RightButton:
            # Still update the current selection so the context
            # menu acts on the row under the cursor -- the
            # ``_show_context_menu`` code already does
            # ``setCurrentItem`` defensively, but doing it here
            # too means the visual selection updates immediately
            # under the cursor.
            try:
                item = self.itemAt(event.pos())
                if item is not None:
                    self.setCurrentItem(item)
            except Exception:  # noqa: BLE001
                pass
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.RightButton:
            # Swallow the release that would otherwise pair with a
            # right press to fire itemClicked.  The context menu
            # still appears via contextMenuEvent's separate path.
            event.accept()
            return
        super().mouseReleaseEvent(event)

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

    def _is_legal_drop_target(
        self, target,  # noqa: ANN001 -- QTreeWidgetItem|None
        indicator_position,  # noqa: ANN001 -- DropIndicatorPosition
    ) -> bool:
        """v0.8.0a35+ -- predicate the dropEvent uses to reject
        illegal Internal-Move drops.

        A leaf in a ``.scriptreetree`` cannot have children: it's
        a reference to a single ``.scriptree`` tool, not a
        container.  Pre-a35 Qt's default ``QTreeWidget`` allowed
        dropping a leaf ONTO another leaf, which silently nested
        the dragged leaf as a child of the target.  The
        in-memory ``TreeDef`` schema then refused to serialise
        properly and the user saw symptoms like "ffmpeg toolkit
        ended up with another tools tool".

        Policy:
          * Dropping ``OnItem`` (i.e. ONTO an item) is legal only
            when the target is a folder.  Leaves and subtree
            references reject the drop.
          * Dropping ``AboveItem`` / ``BelowItem`` (i.e. as a
            sibling) is legal EXCEPT when the would-be new parent
            (``target.parent()``) is a subtree that failed to expand
            (v0.8.0a103 review fix) — see below.
          * Dropping ``OnViewport`` (empty space) is always legal --
            appends to the top level.
        """
        from PySide6.QtWidgets import QAbstractItemView
        if target is None:
            return True  # OnViewport
        if indicator_position != (
            QAbstractItemView.DropIndicatorPosition.OnItem
        ):
            # Above/Below = drop as a SIBLING of ``target`` → Qt reparents the
            # dragged item under ``target.parent()``.  v0.8.0a103 review fix: if
            # that new parent is a FAILED-expand subtree row (``_ROLE_EXPAND_OK``
            # not True), reject — e.g. dropping just above/below the red
            # ``(load error: …)`` / ``(circular reference)`` placeholder line
            # (whose parent IS the broken subtree row) would reparent the tool
            # INTO that unwritable subtree, where it is lost on save (the parent
            # serialises the subtree as a one-line ref and the write-back skips
            # the unreadable file).  Above/Below the subtree ROW itself is fine —
            # its parent is a real container.  This mirrors the OnItem gate.
            new_parent = target.parent()
            if (new_parent is not None
                    and _is_subtree(new_parent)
                    and new_parent.data(0, _ROLE_EXPAND_OK) is not True):
                return False
            return True  # Above/Below the item is otherwise a legal sibling
        # OnItem: a drop-enabled folder, the tree root, and (v0.8.0a103) a linked
        # SUBTREE that expanded CLEANLY — so you can drop a tool INTO it to edit
        # its contents in place.  A subtree that FAILED to expand (load error /
        # circular ref, ``_ROLE_EXPAND_OK`` not True) REFUSES the drop: its
        # write-back is skipped (we won't clobber an unreadable file) and the
        # parent serialises it as a one-line ref that never walks children, so a
        # tool dropped there would land in NEITHER file and be silently lost.
        # The ``ItemIsDropEnabled`` requirement on the folder case also excludes
        # the enabled-only ``(load error: …)`` / ``(circular reference)``
        # placeholder stub (which carries no node role, so ``_is_folder`` would
        # otherwise treat it as a container).  Leaves still reject children.
        return (
            (_is_folder(target)
             and bool(target.flags() & Qt.ItemFlag.ItemIsDropEnabled))
            or _is_root(target)
            or (_is_subtree(target)
                and target.data(0, _ROLE_EXPAND_OK) is True)
        )

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

        # v0.8.0a35+ -- guard Internal-Move drops so leaves cannot
        # become children of other leaves.  See
        # ``_is_legal_drop_target`` for the policy.
        pos = event.position().toPoint()
        target = self.itemAt(pos)
        indicator = self.dropIndicatorPosition()
        if not self._is_legal_drop_target(target, indicator):
            event.ignore()
            return

        # Legal Internal-Move: let Qt do its thing.
        super().dropEvent(event)
        # v0.8.0a103 review fix (belt-and-suspenders) — even though the gate
        # above refuses drops that would reparent a node into a failed-expand
        # subtree, rescue any node that somehow ended up there anyway, so a
        # future gate gap can NEVER silently lose a tool into an unwritable
        # subtree (whose children are serialised to no file).  Run BEFORE the
        # top-level sweep so a rescued node that lands at the top level is then
        # pulled under the root.
        self._rescue_strays_from_unwritable_subtrees()
        # v0.8.0a96 — with a single ROOT row, the only legitimate top-level item
        # is that root.  A drop on empty space (OnViewport) or as a sibling
        # ABOVE/BELOW the root lands a node at the top level next to the root;
        # pull any such stray back UNDER the root so the tree always has exactly
        # one top-level item and serialisation (which walks root.children) never
        # loses a dropped node.
        self._sweep_strays_under_root()
        self.itemReordered.emit()

    def _rescue_strays_from_unwritable_subtrees(self) -> None:
        """v0.8.0a103 — pull any real node that landed as a child of a
        failed-expand subtree row (``_ROLE_EXPAND_OK`` not True) back up to that
        subtree's own parent.

        A failed-expand subtree's only legitimate child is its non-draggable
        ``(load error: …)`` / ``(circular reference)`` placeholder stub; any
        DRAGGABLE child (a real leaf / folder / subtree the user dropped there)
        would be serialised to NO file on save — the parent records the subtree
        as a one-line ref and the write-back skips the unreadable file.  Moving
        such strays to the subtree's parent guarantees they reach a saved
        location.  The placeholder (``ItemIsEnabled`` only, not draggable) is
        left in place."""
        def _failed_subtree_rows(parent: QTreeWidgetItem) -> list[QTreeWidgetItem]:
            out: list[QTreeWidgetItem] = []
            for i in range(parent.childCount()):
                c = parent.child(i)
                if _is_subtree(c) and c.data(0, _ROLE_EXPAND_OK) is not True:
                    out.append(c)
                out.extend(_failed_subtree_rows(c))
            return out

        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            for sub in [top, *_failed_subtree_rows(top)]:
                if not (_is_subtree(sub)
                        and sub.data(0, _ROLE_EXPAND_OK) is not True):
                    continue
                dest = sub.parent()
                for c in [sub.child(j) for j in range(sub.childCount())]:
                    # The placeholder stub is enabled-only (not draggable); a
                    # real dropped node is draggable — rescue only the latter.
                    if not (c.flags() & Qt.ItemFlag.ItemIsDragEnabled):
                        continue
                    sub.removeChild(c)
                    if dest is not None:
                        dest.addChild(c)
                    else:
                        self.addTopLevelItem(c)

    def _sweep_strays_under_root(self) -> None:
        """Reparent any non-root top-level item under the root row.

        No-op when there is no root (a legacy/blank view) or nothing strayed.
        The root itself is never draggable, so it can't become a child of
        anything; only nodes ever stray to the top level."""
        root = None
        strays: list[QTreeWidgetItem] = []
        for i in range(self.topLevelItemCount()):
            it = self.topLevelItem(i)
            if it.data(0, _ROLE_IS_ROOT):
                root = it
            else:
                strays.append(it)
        if root is None or not strays:
            return
        for s in strays:
            idx = self.indexOfTopLevelItem(s)
            if idx >= 0:
                root.addChild(self.takeTopLevelItem(idx))
        root.setExpanded(True)

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


# --- tree-properties dialog (v0.8.0a96) ------------------------------------

class _TreePropertiesDialog(QDialog):
    """Edit a tree's OWN top-level properties.

    The tree view's rows are the tree's *contents*; this dialog edits the tree
    *itself* — the fields ``_build_tree_def`` preserves but the node rows don't
    expose: ``name``, ``category`` (which decides where the tree lands in the
    forest's auto-grouping — see ``docs/LLM/category_authoring.md``), and
    ``path_prepend``.  Cell-icon / menu editing stays in their own editors;
    those fields ride through a save untouched (a95 ``_build_tree_def`` fix).
    """

    def __init__(
        self, *, name: str, category: str, path_prepend: list[str],
        read_only: bool = False, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tree properties")
        self.setMinimumWidth(460)
        form = QFormLayout(self)

        self._name = QLineEdit(name)
        form.addRow("Name", self._name)

        self._category = QLineEdit(category)
        self._category.setPlaceholderText(
            "e.g. MSOffice/Outlook   (blank = its own top-level cell)"
        )
        # v0.8.0a112 -- canonical-category autocomplete (see tool_editor.py).
        try:
            from scriptree.ui.category_completer import attach_category_completer
            attach_category_completer(self._category)
        except Exception:  # noqa: BLE001 -- completer is a nicety, never fatal
            pass
        form.addRow("Category", self._category)
        hint = QLabel(
            "Slash-delimited. A tree folds into its top segment's cell in the "
            "forest — e.g. <code>MSOffice/Outlook</code> lands under the "
            "MSOffice cell. Blank shows the tree as its own top-level cell."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666; font-size:10px;")
        form.addRow("", hint)

        self._path_prepend = QPlainTextEdit("\n".join(path_prepend))
        self._path_prepend.setPlaceholderText(
            "One folder per line — prepended to PATH for every tool in the tree"
        )
        self._path_prepend.setFixedHeight(72)
        form.addRow("PATH prepend", self._path_prepend)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        if read_only:
            for w in (self._name, self._category, self._path_prepend):
                w.setReadOnly(True)
            ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
            if ok_btn is not None:
                ok_btn.setEnabled(False)

    def values(self) -> dict:
        """Return ``{name, category, path_prepend}`` from the form."""
        return {
            "name": self._name.text().strip(),
            "category": self._category.text().strip(),
            "path_prepend": [
                ln.strip()
                for ln in self._path_prepend.toPlainText().splitlines()
                if ln.strip()
            ],
        }


# --- main launcher view ----------------------------------------------------

class TreeLauncherView(QWidget):
    """Editable .scriptreetree launcher with drag-drop and save."""

    toolSelected = Signal(object, str)
    """Emitted when the user clicks a leaf. Args: (ToolDef, path).

    v0.6.1 — single click (was double-click).  Switching tools in
    the tree is a navigation action; a double-click requirement just
    added friction."""

    editRequested = Signal(object, str)
    """Emitted when the user picks Edit from a leaf's right-click
    menu. Args: (ToolDef, path).  The main window opens the tool
    editor bound to ``path`` so Save writes back to the file."""

    standaloneRequested = Signal(object)
    """Emitted on a double-right-click. Arg: a descriptor dict —
    ``{"kind": "tool", "tool": ToolDef, "path": str}`` for a leaf,
    ``{"kind": "tree", "path": str}`` for a subtree reference, or
    ``{"kind": "folder"}`` for an in-memory folder (the main window
    falls back to the whole loaded tree for a bare folder)."""

    uninstallRequested = Signal(str)
    """v0.8.0a34+ — emitted when the user picks "Uninstall app from
    disk..." in a leaf's right-click context menu.  Arg: the absolute
    catalog path (``.scriptree`` or ``.scriptreetree``) the user
    clicked.  The main window forwards this to its forest controller's
    uninstall flow (which pops the checkbox dialog with the
    keep/remove-local + keep/remove-shared options) -- same code path
    the cell-popup's per-item context menu uses, so the editor's
    Uninstall and the cell-popup's Uninstall produce IDENTICAL UX."""

    openTreeRequested = Signal(str)
    """v0.8.0a100 — emitted when the user picks "Open in editor" on a SUBTREE
    row (a linked ``.scriptreetree``, e.g. a forest member or an auto-group).
    Arg: the absolute ``.scriptreetree`` path.  The main window loads it as the
    editable root tree so the user can set its Category / properties and Save —
    the missing "right-click a linked tree → edit it" capability."""

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
        self._btn_props = QPushButton("Properties...")
        self._btn_props.setToolTip(
            "Edit the tree's own name, category (where it lands in the "
            "forest), and PATH prepend."
        )
        self._btn_props.clicked.connect(self._open_tree_properties)
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
        tb.addWidget(self._btn_props)
        tb.addWidget(self._btn_configs)
        tb.addWidget(self._btn_save)
        layout.addLayout(tb)

        # Editable tree widget.
        self._tree_widget = _EditableTreeWidget()
        self._tree_widget.setHeaderLabel("Tools")
        # v0.6.1 — single click activates a leaf (was double-click).
        self._tree_widget.itemClicked.connect(self._on_item_activated)
        self._tree_widget.fileDropped.connect(self._on_file_dropped)
        self._tree_widget.itemReordered.connect(self._mark_dirty)
        self._tree_widget.itemChanged.connect(self._on_item_changed)
        self._tree_widget.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        # The context menu is debounced (~220 ms) so a double-right-
        # click (open standalone) doesn't first flash the menu.
        self._tree_widget.customContextMenuRequested.connect(
            self._schedule_context_menu
        )
        # v0.8.0a36+ -- wire the column header ("Tools" label row)
        # to the same context menu so the user can right-click
        # ANYWHERE on the tree surface to get Save.  Pre-a36
        # right-clicking the header was a dead zone because
        # ``customContextMenuRequested`` is emitted from
        # QTreeWidget's viewport, not its QHeaderView -- so the
        # user's natural target ("the header looks like the root,
        # let me right-click it") produced nothing.
        header = self._tree_widget.header()
        header.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        header.customContextMenuRequested.connect(
            self._on_header_context_menu
        )
        self._tree_widget.rightDoubleClicked.connect(
            self._on_right_double_click
        )
        from PySide6.QtCore import QTimer
        self._ctx_timer = QTimer(self)
        self._ctx_timer.setSingleShot(True)
        self._ctx_timer.setInterval(220)
        self._ctx_timer.timeout.connect(self._fire_context_menu)
        self._pending_ctx_pos = None
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
        # v0.8.0a96 — the opened tree is shown as a single selectable ROOT row
        # ("the thing you opened"); its nodes nest underneath.  Selecting the
        # root edits the tree's own properties (name / category / …).
        root_item = self._make_root_item()
        self._tree_widget.addTopLevelItem(root_item)
        # Add the root tree file to the expanding-paths guard so that
        # subtrees referencing us back are caught as circular.
        root_key = str(self._tree_file)
        self._expanding_paths.add(root_key)
        try:
            for node in tree.nodes:
                self._add_node_item(node, parent=root_item)
        finally:
            self._expanding_paths.discard(root_key)
        root_item.setExpanded(True)
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
        root_item = self._make_root_item()
        self._tree_widget.addTopLevelItem(root_item)
        root_item.setExpanded(True)
        self._dirty = True
        self._update_title()
        self.treeModified.emit(True)

    def is_dirty(self) -> bool:
        return self._dirty

    def tree_file(self) -> Path | None:
        return self._tree_file

    def tree_path_prepend(self) -> list[str]:
        """Return the loaded tree's ``path_prepend`` list (V3 v0.3.2+).

        Empty list when no tree is loaded or when the tree carries
        no path_prepend entries.  The runner forwards these to
        ``build_full_argv`` so they reach the child's PATH at run
        time — closes the dead-code gap pinned by
        ``test_global_env_layering.TestTreePathPrependDeadCodeGap``
        in v0.3.1.
        """
        if self._tree is None:
            return []
        return list(self._tree.path_prepend or [])

    def save(self) -> bool:
        """Write the tree to disk. Returns True on success."""
        return self._save_tree()

    def save_as(self) -> bool:
        """Prompt for a new ``.scriptreetree`` path, then save there.

        Returns True on success.  Always opens the Save-As dialog,
        even when the tree was previously bound to a file — the new
        path becomes the tree's path on success (subsequent ``save()``
        calls write to it).
        """
        if self._tree is None:
            return False
        if getattr(self, "_tree_read_only", False):
            QMessageBox.warning(
                self, "Read-only",
                "This tree file is read-only and cannot be saved.",
            )
            return False
        path = self._ask_save_path()
        if not path:
            return False
        # Re-bind to the new path before delegating to ``_save_tree``,
        # which writes to ``self._tree_file``.
        self._tree_file = Path(path).resolve()
        # The new file may live on a different filesystem with its own
        # permissions; refresh the read-only flag so subsequent edits
        # are gated correctly.
        from ..core.permissions import check_write_access
        access = check_write_access(self._tree_file)
        self._tree_read_only = not access.fully_writable
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

    @staticmethod
    def _store_node_metadata(item: QTreeWidgetItem, node: TreeNode) -> None:
        """v0.8.0a103 — stash a node's serialisable metadata onto its item so
        ``_item_to_node`` can re-emit it LOSSLESSLY on save.

        Before a103 the editor only carried ``display_name`` (leaves/subtrees)
        and ``configuration`` (leaves), so ``icon`` / ``icon_data`` /
        ``icon_format`` (all node kinds), folder ``display_name`` and subtree-ref
        ``configuration`` were silently dropped on every save — stripping the
        override AND (for the inline subtree write-back) defeating the
        unchanged-skip guard so an unedited subtree compared "changed", churned
        its file and lost the metadata.  Carrying every field here makes the
        round-trip exact for leaves, folders AND subtree references."""
        if node.display_name is not None:
            item.setData(0, _ROLE_DISPLAY_NAME, node.display_name)
        if node.configuration:
            item.setData(0, _ROLE_CONFIGURATION, node.configuration)
        if node.icon:
            item.setData(0, _ROLE_ICON, node.icon)
        if node.icon_data:
            item.setData(0, _ROLE_ICON_DATA, node.icon_data)
        if node.icon_format:
            item.setData(0, _ROLE_ICON_FORMAT, node.icon_format)

    def _add_node_item(
        self, node: TreeNode, parent: QTreeWidgetItem | None
    ) -> None:
        if node.type == "folder":
            # a103 review fix — show the folder's EFFECTIVE label
            # (``display_name or name``, matching the runtime + popup), and keep
            # the authored ``name`` in its own role so serialisation can
            # round-trip a name+display_name folder without churn and tell an
            # inline rename apart from an untouched load (see _item_to_node).
            label = node.display_name or node.name or "(folder)"
            item = self._new_folder_item(label)
            # a103 — folders carry display_name + icon overrides too.
            self._store_node_metadata(item, node)
            item.setData(0, _ROLE_FOLDER_NAME, node.name)
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
                item = self._new_subtree_item(
                    abs_str, display_name=node.display_name
                )
                # a103 — subtree refs carry configuration + icon overrides too
                # (previously dropped, unlike plain .scriptree leaves).
                self._store_node_metadata(item, node)
                if parent is None:
                    self._tree_widget.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                self._expand_subtree(item)
            else:
                item = self._new_leaf_item(
                    abs_str, display_name=node.display_name
                )
                # Preserve the tree-level configuration override + per-node icon
                # (a103) so save-after-edit doesn't lose them.
                self._store_node_metadata(item, node)
                if parent is None:
                    self._tree_widget.addTopLevelItem(item)
                else:
                    parent.addChild(item)

    def _make_root_item(self) -> QTreeWidgetItem:
        """Build the single ROOT row that represents the opened tree itself.

        Labelled with the tree name (editable inline → renames the tree) and the
        tree's cell icon when it has one (else a folder glyph).  It is a drop
        CONTAINER but is NOT draggable or removable — it IS the tree.  Selecting
        it (double-click, or right-click → Tree properties, or the toolbar
        Properties button) edits the tree's own name / category / path_prepend;
        its children are the tree's nodes.
        """
        name = (self._tree.name if self._tree is not None else "") or "(tree)"
        item = QTreeWidgetItem([name])
        item.setData(0, _ROLE_IS_ROOT, True)
        if self._tree_file is not None:
            item.setIcon(0, _tv_catalog_icon(
                str(self._tree_file), QStyle.StandardPixmap.SP_DirIcon))
        else:
            item.setIcon(0, _tv_std_icon(QStyle.StandardPixmap.SP_DirIcon))
        # Bold so the root reads as the container, not just another folder.
        f = item.font(0)
        f.setBold(True)
        item.setFont(0, f)
        item.setToolTip(
            0,
            "The tree itself. Double-click (or right-click → Tree "
            "properties) to edit its name / category / icon.",
        )
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDropEnabled   # accepts dropped nodes
            | Qt.ItemFlag.ItemIsEditable      # inline-rename → tree name
            # NOT ItemIsDragEnabled — the root can't be dragged/reparented.
        )
        return item

    def _root_item(self) -> QTreeWidgetItem | None:
        """Return the synthetic ROOT row, or None (legacy / blank view)."""
        if self._tree_widget.topLevelItemCount() >= 1:
            top = self._tree_widget.topLevelItem(0)
            if _is_root(top):
                return top
        return None

    def _add_under_root(self, item: QTreeWidgetItem) -> None:
        """Add ``item`` at the TREE's top level — i.e. as a child of the ROOT
        row — falling back to the widget top level if there's no root (legacy)."""
        root = self._root_item()
        if root is not None:
            root.addChild(item)
            root.setExpanded(True)
        else:
            self._tree_widget.addTopLevelItem(item)

    def _new_folder_item(self, name: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([name])
        item.setIcon(0, _tv_std_icon(QStyle.StandardPixmap.SP_DirIcon))
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
            | Qt.ItemFlag.ItemIsEditable
        )
        # v0.8.0a99 — provenance tooltip: an in-memory folder has NO backing
        # file (it organises tools within the containing tree), so hovering it
        # says so — distinct from a linked-tree or auto-group row (which name a
        # file / category).  Folders have no path data — that's also how
        # _is_folder distinguishes them from leaves.
        item.setToolTip(
            0, "Folder — organises tools within this tree (no separate file).",
        )
        return item

    def _new_leaf_item(
        self, abs_path: str, display_name: str | None = None
    ) -> QTreeWidgetItem:
        # Precedence for the visible label:
        #   1. explicit display_name from the .scriptreetree node (pretty)
        #   2. the tool's own name (if the file loads cheaply)
        #   3. the filename stem (cheap fallback; always works)
        label = display_name
        if not label:
            try:
                tool = load_tool(abs_path)
                label = tool.name or Path(abs_path).stem
            except Exception:  # noqa: BLE001
                label = Path(abs_path).stem
        item = QTreeWidgetItem([label])
        item.setIcon(0, _tv_catalog_icon(
            abs_path, QStyle.StandardPixmap.SP_FileIcon))
        item.setData(0, _ROLE_PATH, abs_path)
        if display_name:
            item.setData(0, _ROLE_DISPLAY_NAME, display_name)
        item.setToolTip(0, abs_path)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            # NOT ItemIsDropEnabled → can't drop onto a leaf
            # NOT ItemIsEditable → leaf labels come from node.display_name
            #   or the tool's own name (edit via the .scriptree or tree JSON)
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

    def _new_subtree_item(
        self, abs_path: str, display_name: str | None = None
    ) -> QTreeWidgetItem:
        """Create a QTreeWidgetItem for a .scriptreetree reference.

        Subtree items look like folders (expandable, with children
        loaded from the referenced file) but are **not** editable or
        drop-enabled — their structure comes from the referenced file.
        """
        # Prefer the tree node's display_name override. Otherwise try
        # the referenced tree's own name (e.g. "SolidWorks toolkit"),
        # falling back to the filename stem.
        label = display_name
        if not label:
            try:
                sub = load_tree(abs_path)
                label = sub.name or Path(abs_path).stem
            except Exception:  # noqa: BLE001
                label = Path(abs_path).stem
        # v0.6.5 — was a 📂 emoji text-prefix; now a real QIcon (the
        # referenced tree's configured icon, else the OS folder
        # icon) so it matches the leaf rows and the popup menu.
        item = QTreeWidgetItem([label])
        item.setIcon(0, _tv_catalog_icon(
            abs_path, QStyle.StandardPixmap.SP_DirIcon))
        item.setData(0, _ROLE_PATH, abs_path)
        item.setData(0, _ROLE_SUBTREE, abs_path)
        if display_name:
            item.setData(0, _ROLE_DISPLAY_NAME, display_name)
        # v0.8.0a99 — provenance tooltip that NAMES the backing file (the user
        # couldn't tell a linked tree from a plain folder before).  A
        # synthesised category group (under ``_groups/``) gets a distinct
        # caption explaining it's derived from tools' Category fields and edited
        # there, not in the regenerated file.
        if "_groups" in Path(abs_path).parts:
            cat = Path(abs_path).stem
            if cat.endswith("__auto"):
                cat = cat[: -len("__auto")]
            item.setToolTip(
                0,
                f"Auto-group · category '{cat}'\n"
                "Built from tools' Category fields — to move a tool, edit its "
                "Category. This file is regenerated, not edited directly.\n"
                f"{abs_path}",
            )
        else:
            item.setToolTip(0, f"Linked tree: {abs_path}")
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
            # v0.8.0a103 — drop-enabled so you can edit the LINKED tree in
            # place (drop tools/folders into it, rearrange its children); the
            # edits write back to the referenced .scriptreetree on Save.
            # NOT ItemIsEditable — label derived from the referenced file.
        )
        return item

    def _expand_subtree(self, item: QTreeWidgetItem) -> None:
        """Load the .scriptreetree file and populate *item* with its nodes.

        v0.8.0a103 — the children are EDITABLE IN PLACE: drop a tool in, remove
        one, rename a folder, and on Save those edits are written back to the
        referenced file (see ``_write_back_subtrees``).  This sets
        ``_ROLE_EXPAND_OK`` True on a clean load so write-back knows the child
        view is faithful; a circular reference or load error sets it False so the
        partial/stub view is NEVER written back.
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
            item.setData(0, _ROLE_EXPAND_OK, False)  # a103 — never write back
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
                item.setData(0, _ROLE_EXPAND_OK, False)  # a103 — never write back
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
            # a103 — populated cleanly; inline edits to these children may now be
            # written back to the referenced file on Save.
            item.setData(0, _ROLE_EXPAND_OK, True)
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
        # Fires when the user renames a folder (or the ROOT) inline.
        if col != 0:
            return
        if _is_root(item) and self._tree is not None:
            from dataclasses import replace
            new_name = (item.text(0) or "").strip()
            if new_name and new_name != self._tree.name:
                self._tree = replace(self._tree, name=new_name)
            elif not new_name:
                # A blank/whitespace root name is refused (self._tree.name kept).
                # Restore the visible label so the row doesn't desync from the
                # title.  Re-setting to the existing name re-fires itemChanged
                # once, but then new_name == self._tree.name, so neither branch
                # runs again — no loop.
                item.setText(0, self._tree.name)
        self._mark_dirty()
        self._update_title()

    # --- toolbar actions -------------------------------------------------

    def _add_folder(self) -> None:
        name, ok = QInputDialog.getText(
            self, "New folder", "Folder name:"
        )
        if not ok or not name.strip():
            return
        item = self._new_folder_item(name.strip())
        selected = self._tree_widget.currentItem()
        # v0.8.0a115 -- a cleanly-expanded SUBTREE row (``_ROLE_EXPAND_OK``) is a
        # valid container too: its children are edited in place and written back
        # to the referenced ``.scriptreetree`` on Save.  Without this, "New
        # Folder" on e.g. the ffmpeg subtree fell through to ``_add_under_root``
        # and the folder was created in the Forest root instead of INSIDE ffmpeg
        # (user-reported).  A FAILED-expand subtree (EXPAND_OK not True) is NOT a
        # container -- a folder added there would be lost on save -- so it still
        # falls through to root.
        if selected is not None and (
            _is_folder(selected)
            or (_is_subtree(selected)
                and selected.data(0, _ROLE_EXPAND_OK) is True)
        ):
            selected.addChild(item)
            selected.setExpanded(True)
        else:
            self._add_under_root(item)
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
        if selected is None or _is_root(selected):
            return  # the tree root isn't removable — it IS the tree
        parent = selected.parent()
        if parent is None:
            idx = self._tree_widget.indexOfTopLevelItem(selected)
            self._tree_widget.takeTopLevelItem(idx)
        else:
            parent.removeChild(selected)
        self._mark_dirty()

    def _is_synthesised_group(self) -> bool:
        """True when the loaded tree is a synthesised auto-group — a
        ``_groups/<Top>.scriptreetree``.  Detected by the file living under a
        ``_groups`` dir (the synth output dir); these are regenerated from tool
        ``category`` fields and so are never saved directly (see a102)."""
        if self._tree_file is None:
            return False
        try:
            return "_groups" in Path(self._tree_file).resolve().parts
        except (OSError, ValueError):
            return False

    def _recategorize_tools_from_layout(self) -> list[tuple[str, str, str]]:
        """Rewrite each group member's ``category`` to match its position in the
        (synthesised-group) tree — the drag-to-recategorize write-back (a102).

        A member under ``<root> → Excel`` gets ``category = "<Root>/Excel"``;
        directly under the root gets ``"<Root>"``.  Targeted JSON edit: ONLY the
        ``category`` key is rewritten, every other field of the tool/tree file
        is preserved byte-for-byte otherwise.  Returns ``(path, old, new)`` for
        each member whose category actually changed.  Does NOT recurse into a
        member subtree's own children (those belong to the referenced file).
        """
        import json
        from scriptree.core.io import _normalise_category
        root = self._root_item()
        if root is None:
            return []
        top = (root.text(0) or "").strip() or (
            (self._tree.name if self._tree is not None else "") or ""
        ).strip()
        if not top:
            return []
        changes: list[tuple[str, str, str]] = []
        current: set[str] = set()

        def _rewrite(path: str, new_cat: str) -> None:
            try:
                p = Path(path)
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, ValueError):
                return
            if not isinstance(d, dict):
                return
            old = d.get("category", "") or ""
            # a102-review fix: compare NORMALISED forms — grouping feeds on the
            # normalised category, so a merely un-normalised stored value
            # ('A/B/' etc.) is the SAME position; don't churn it or count it.
            if _normalise_category(old) == _normalise_category(new_cat):
                return
            d["category"] = new_cat
            try:
                p.write_text(json.dumps(d, indent=2), encoding="utf-8")
            except OSError:
                return
            changes.append((path, old, new_cat))

        def _seg(name: str) -> str:
            # a102-review fix: a folder name must never embed a path separator,
            # or the round-trip splits it into extra nested folders.  Mirror
            # categorize._safe_stem's slash scrub.
            return (name or "").replace("/", " ").replace("\\", " ").strip()

        def _walk(item: QTreeWidgetItem, prefix: list[str]) -> None:
            for i in range(item.childCount()):
                child = item.child(i)
                if _is_folder(child):
                    seg = _seg(child.text(0))
                    _walk(child, prefix + ([seg] if seg else []))
                else:
                    # A leaf (tool) or subtree (linked tree) member — both carry
                    # _ROLE_PATH.  Re-file by its folder position; do NOT recurse
                    # into a subtree's referenced children.
                    path = child.data(0, _ROLE_PATH)
                    if path:
                        try:
                            current.add(str(Path(path).resolve()))
                        except (OSError, ValueError):
                            current.add(str(path))
                        _rewrite(str(path), "/".join(prefix))

        _walk(root, [top])

        # a102-review fix: a member REMOVED from the group view (Remove /
        # drag-out) must actually leave the group — otherwise it reappears on
        # the next Re-organise (the group is rebuilt from categories).  Clear
        # the category of any originally-loaded member no longer in the layout.
        for orig in self._original_member_paths():
            if orig not in current:
                _rewrite(orig, "")
        return changes

    def _original_member_paths(self) -> set[str]:
        """Resolved absolute paths of every leaf/subtree member in the
        ORIGINALLY-loaded tree (``self._tree``) — used to detect members the
        user removed from a synthesised group's layout."""
        if self._tree is None:
            return set()
        out: set[str] = set()

        def _walk(nodes) -> None:
            for n in nodes:
                if getattr(n, "type", None) == "folder":
                    _walk(n.children)
                elif getattr(n, "path", None):
                    try:
                        out.add(str(self._resolve_path(n.path).resolve()))
                    except (OSError, ValueError):
                        pass

        _walk(self._tree.nodes)
        return out

    # --- a103: inline subtree edit (write-back to referenced files) ---------

    def _write_back_subtrees(self) -> list[str]:
        """v0.8.0a103 — persist INLINE edits made to expanded linked subtrees.

        When the user expands a linked-subtree row (``_expand_subtree`` loads the
        referenced ``.scriptreetree``'s nodes as children) and then edits those
        children in place — drags a tool in, removes one, renames a folder — those
        edits belong to the *referenced* file, not to the tree currently being
        saved (whose serialization records the subtree only as a one-line leaf
        reference; see ``_item_to_node``).  This walks the loaded tree and, for
        every subtree whose contents now DIFFER from its file, rewrites that file's
        ``nodes`` (preserving every top-level metadata field).  Recurses, so a
        subtree nested inside a subtree (or inside a folder) is handled too.

        Returns the list of subtree file paths actually written.  Each write is
        independently guarded and best-effort: a failure on one subtree never
        aborts the parent save nor the other subtrees.

        GUARDS (each prevents clobbering a file we must not touch):
          * ``_ROLE_EXPAND_OK`` is True only when the subtree expanded cleanly —
            a circular reference or a load error sets it False, so its children
            are a stub/partial view and must NEVER be written back.
          * a SYNTHESISED group (``_groups/``) is regenerated from tool
            ``category`` fields (a98/a102) — writing it is futile and is handled
            separately by the drag-to-recategorize path; skip it here.
          * an unchanged subtree (round-tripped nodes equal the file's nodes,
            path-form aside) is skipped, so a plain Save of an unedited tree
            writes nothing.
          * the SAME file referenced by two rows is written at most ONCE per
            pass (the first row that actually changes it wins) — otherwise a
            second, stale duplicate row would reload the just-written file, see
            a diff, and clobber the edit back to its pre-edit content.
        """
        written: list[str] = []
        written_keys: set[str] = set()  # resolved subtree paths already written

        def _resolved_key(child: QTreeWidgetItem) -> str | None:
            sp = child.data(0, _ROLE_SUBTREE)
            if not sp:
                return None
            try:
                return str(Path(sp).resolve())
            except (OSError, ValueError):
                return str(sp)

        def _visit(item: QTreeWidgetItem) -> None:
            for i in range(item.childCount()):
                child = item.child(i)
                if _is_subtree(child):
                    key = _resolved_key(child)
                    # De-dupe only the WRITE of THIS file: if a sibling/earlier
                    # row already wrote the same file this pass, don't let this
                    # (possibly stale) duplicate clobber it.  But ALWAYS recurse —
                    # a duplicate row's NESTED subtrees are DIFFERENT files and
                    # may carry edits made only through this row's copy; skipping
                    # the recursion (the convergence review's finding) would lose
                    # them.  Nested files are themselves de-duped by their own
                    # resolved key, so recursing can't double-write.
                    if key is None or key not in written_keys:
                        if self._write_one_subtree_if_changed(child):
                            if key is not None:
                                written_keys.add(key)
                            sp = child.data(0, _ROLE_SUBTREE)
                            if sp:
                                written.append(str(sp))
                    # Recurse: a folder OR nested subtree inside this subtree may
                    # itself hold a deeper edited subtree (in a different file).
                    _visit(child)
                elif _is_folder(child):
                    _visit(child)

        root = self._root_item()
        _visit(root if root is not None
               else self._tree_widget.invisibleRootItem())
        return written

    def _write_one_subtree_if_changed(self, item: QTreeWidgetItem) -> bool:
        """Write ONE expanded subtree's current children back to its referenced
        file iff they differ from what the file holds.  Returns True iff written.

        The children are re-serialized with paths relativised against the
        SUBTREE's own directory (not the parent tree's) by temporarily pointing
        ``self._tree_file`` at the subtree file across ``_item_to_node`` — the
        same relativisation trick the parent save uses, retargeted.  The file's
        top-level metadata is preserved by re-loading it and replacing only its
        ``nodes`` (mirrors the a95 ``dataclasses.replace`` discipline).
        """
        path = item.data(0, _ROLE_SUBTREE)
        if not path:
            return False
        # Guard 1 — only a cleanly-expanded subtree has a faithful child view.
        if item.data(0, _ROLE_EXPAND_OK) is not True:
            return False
        p = Path(path)
        # Guard 2 — never write a synthesised auto-group (regenerated elsewhere).
        try:
            if "_groups" in p.resolve().parts:
                return False
        except (OSError, ValueError):
            return False
        # Build the new node list from the row's CHILDREN, relativised against
        # the subtree's own directory.
        saved_tree_file = self._tree_file
        self._tree_file = p
        try:
            new_nodes: list[TreeNode] = []
            for i in range(item.childCount()):
                node = self._item_to_node(item.child(i))
                if node is not None:
                    new_nodes.append(node)
        finally:
            self._tree_file = saved_tree_file
        # Guard 3 — must re-load to preserve the file's top-level metadata; if it
        # won't load, leave it untouched rather than overwrite blindly.
        try:
            existing = load_tree(str(p))
        except Exception:  # noqa: BLE001
            return False
        # Guard 4 — skip when nothing GENUINELY changed.  Compare via _churn_key
        # so a pure leaf-path FORM difference (bare vs ``./``, ``\`` vs ``/``)
        # does NOT count as a change — otherwise a plain Save of any parent that
        # links a bare-path subtree (e.g. ScripTree's own management tree) would
        # silently rewrite that file.  Every other field — incl. the icon
        # triplet, display_name, configuration — IS compared (now that the
        # round-trip carries them), so real edits + metadata changes still write.
        if [_churn_key(n) for n in existing.nodes] == \
                [_churn_key(n) for n in new_nodes]:
            return False  # unchanged — no churn
        from dataclasses import replace
        try:
            save_tree(replace(existing, nodes=new_nodes), p)
        except Exception:  # noqa: BLE001
            return False
        return True

    def _save_tree(self) -> bool:
        if self._tree is None:
            return False
        if getattr(self, "_tree_read_only", False):
            QMessageBox.warning(
                self, "Read-only",
                "This tree file is read-only and cannot be saved.",
            )
            return False
        # v0.8.0a102 — DRAG-TO-RECATEGORIZE.  A synthesised auto-group
        # (``_groups/<Top>.scriptreetree``) is REGENERATED from tool ``category``
        # fields, so writing the group file is futile (the next Re-organise
        # overwrites it).  Instead, translate the current folder LAYOUT into each
        # member's ``category`` — the source of truth: a tool now sitting under
        # ``MSOffice → Excel`` gets ``category: "MSOffice/Excel"``.  Re-organise
        # then rebuilds the group from those categories.  (Editing tool
        # *contents* still uses the normal per-tool editor; this only re-files
        # them by category.)
        if self._is_synthesised_group():
            changes = self._recategorize_tools_from_layout()
            self._dirty = False
            self._update_title()
            self.treeModified.emit(False)
            refiled = sum(1 for _p, _o, new in changes if new)
            removed = sum(1 for _p, _o, new in changes if not new)
            if changes:
                parts = []
                if refiled:
                    parts.append(f"re-filed {refiled} tool(s) by Category")
                if removed:
                    parts.append(
                        f"removed {removed} from the group (cleared Category)"
                    )
                msg = (
                    "Updated tool categories to match the layout: "
                    + "; ".join(parts) + ".\n\n"
                    "This auto-group is rebuilt from tool categories, so the "
                    "changes were written to each tool's .scriptree (not to "
                    "the group file) — empty folders aren't kept.\n\n"
                    "Re-organise the forest to apply."
                )
            else:
                msg = (
                    "No category changes — every tool is already filed under "
                    "the folder matching its Category.\n\n(This auto-group is "
                    "rebuilt from tool categories; empty folders or layout "
                    "tweaks without a tool move aren't persisted.)"
                )
            # v0.8.0a103 (convergence-review fix) — a group opened as the root
            # can still contain cleanly-expanded NON-group member subtrees the
            # user edited in place; persist those (the group file itself is
            # regenerated from categories, not written here).
            self._persist_subtree_edits()
            QMessageBox.information(self, "Categories updated", msg)
            return True
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
        # v0.8.0a103 — persist any INLINE edits made to expanded linked subtrees.
        self._persist_subtree_edits()
        return True

    def _persist_subtree_edits(self) -> None:
        """v0.8.0a103 — run the inline-subtree write-back, surfacing a failure
        without undoing the parent save that already succeeded.

        Called on BOTH ``_save_tree`` paths — the normal save AND the
        synthesised-group branch (which ``return``s early).  The convergence
        review found that omitting it from the group path silently dropped an
        inline edit to a cleanly-expanded NON-group member subtree when a
        ``_groups/`` auto-group was opened as the root: the group file is
        regenerated (not written) and the member's write-back never ran.  The
        per-subtree ``_groups/`` guard in ``_write_one_subtree_if_changed`` still
        protects any group MEMBER that is itself synthesised, so running it here
        only persists legitimate member edits."""
        try:
            self._write_back_subtrees()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self, "Subtree save",
                "The tree was saved, but writing inline edits back to a linked "
                f"subtree failed:\n{exc}",
            )

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

    def _nearest_drop_container(
        self, item: QTreeWidgetItem | None
    ) -> QTreeWidgetItem | None:
        """v0.8.0a103 review fix — walk UP from a drop target to the nearest row
        that can actually PERSIST a dropped child, returning ``None`` for "top
        level / under the root".

        A child is persisted only if it lands under one of:
          * a real, drop-enabled FOLDER (the ``(load error)`` / ``(circular
            reference)`` placeholder stub is enabled-only, NOT drop-enabled, so
            it is skipped — otherwise a tool dropped on it would be serialised
            into NEITHER file: the parent records the failed subtree as a
            one-line ref that never walks children, and the subtree write-back
            skips a non-``EXPAND_OK`` row);
          * the ROOT row;
          * a cleanly-expanded SUBTREE (its inline edits write back to the
            referenced file).
        Leaves, failed-expand subtree rows, and placeholder stubs are walked
        past to their nearest persisting ancestor."""
        cur = item
        while cur is not None:
            if _is_root(cur):
                return cur
            if _is_folder(cur) and bool(
                cur.flags() & Qt.ItemFlag.ItemIsDropEnabled
            ):
                return cur
            if _is_subtree(cur) and cur.data(0, _ROLE_EXPAND_OK) is True:
                return cur
            cur = cur.parent()
        return None

    def _on_file_dropped(
        self, path: str, target_item: QTreeWidgetItem | None
    ) -> None:
        if not self._check_no_cycle(path):
            return
        # Resolve the drop target to the nearest row that can actually PERSIST a
        # dropped child (v0.8.0a103 review fix).  This walks UP past anything that
        # can't hold a saved child — a leaf, a failed-expand subtree row, and
        # crucially the ``(load error: …)`` / ``(circular reference)`` PLACEHOLDER
        # stub under a failed subtree (which ``_is_folder`` would otherwise treat
        # as a container, silently swallowing the tool into NEITHER file).  A
        # cleanly-expanded subtree IS a container (edits write back); a real
        # folder / the root are containers; ``None`` → top level.
        parent = self._nearest_drop_container(target_item)
        if parent is not None:
            parent.setExpanded(True)
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
                self._add_under_root(item)
            else:
                parent.addChild(item)
            self._expand_subtree(item)
        else:
            item = self._new_leaf_item(abs_path)
            if parent is None:
                self._add_under_root(item)
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

    def _schedule_context_menu(self, pos) -> None:
        """Debounce the context menu so a double-right-click (open
        standalone) doesn't first flash it."""
        self._pending_ctx_pos = pos
        self._ctx_timer.start()

    def _fire_context_menu(self) -> None:
        if self._pending_ctx_pos is not None:
            self._show_context_menu(self._pending_ctx_pos)

    def _on_right_double_click(self, pos) -> None:
        """Double-right-click → open the item under the cursor in
        standalone mode.  Cancels the pending context menu."""
        self._ctx_timer.stop()
        self._pending_ctx_pos = None
        item = self._tree_widget.itemAt(pos)
        desc = self._standalone_descriptor(item)
        if desc is not None:
            self.standaloneRequested.emit(desc)

    def _standalone_descriptor(self, item) -> dict | None:
        """Build the payload for ``standaloneRequested`` from an
        item (or None for empty space → whole tree)."""
        if item is None:
            return {"kind": "folder"}  # whole loaded tree
        if _is_subtree(item):
            return {"kind": "tree",
                    "path": item.data(0, _ROLE_SUBTREE)}
        if _is_leaf(item):
            path = item.data(0, _ROLE_PATH)
            if not path or not Path(path).exists():
                return None
            try:
                tool = load_tool(path)
            except Exception:  # noqa: BLE001
                return None
            return {"kind": "tool", "tool": tool, "path": path}
        # Plain in-memory folder — no own file; the main window
        # opens the whole loaded tree standalone as the closest
        # existing capability.
        return {"kind": "folder"}

    def _on_header_context_menu(self, pos) -> None:
        """v0.8.0a36+ -- right-click on the tree's column header
        ("Tools" label row).

        Reuses the same menu builder as the body's context menu
        but always with ``item=None`` (the header has no item
        underneath the cursor).  Maps the header's local
        position to global so the menu appears under the user's
        cursor, not at the top-left of the screen.
        """
        menu = QMenu(self)
        self._populate_context_menu_for(menu, item=None)
        header = self._tree_widget.header()
        menu.exec(header.mapToGlobal(pos))

    def _show_context_menu(self, pos) -> None:
        item = self._tree_widget.itemAt(pos)
        # v0.6.1 — operate on whatever the mouse is over, not the
        # prior selection.  Select it first so selection-based
        # actions (Remove) target the hovered row.
        if item is not None:
            self._tree_widget.setCurrentItem(item)
        menu = QMenu(self)
        # v0.8.0a35+ -- the action-building logic is exposed via
        # ``_populate_context_menu_for`` so it's testable in
        # isolation (no need to synthesise a real right-click
        # position).
        self._populate_context_menu_for(menu, item)
        menu.exec(
            self._tree_widget.viewport().mapToGlobal(pos)
        )

    def _populate_context_menu_for(
        self, menu: QMenu, item,  # noqa: ANN001 -- QTreeWidgetItem|None
    ) -> None:
        """Fill ``menu`` with the right-click actions appropriate
        to ``item``.

        Extracted from ``_show_context_menu`` in v0.8.0a35 so the
        same action set can be tested without going through a
        real mouse position.  Behaviour is identical to the
        pre-a35 inline build, plus a Save action that the user
        asked for ("right-clicked at the top of the tree with
        forest open there was no save option").
        """
        # v0.6.5 — program/built-in menu items get OS standard icons
        # too (the user: "menu items both for the program and apps").
        _SP = QStyle.StandardPixmap
        # v0.8.0a96 — tree-level properties: available on the ROOT row and on
        # empty space / the header (item is None).  This is where you edit the
        # tree's own name / category / PATH-prepend.
        if item is None or _is_root(item):
            act_props = QAction("Tree properties…", self)
            act_props.setIcon(_tv_std_icon(_SP.SP_FileDialogDetailedView))
            act_props.triggered.connect(
                lambda _=False: self._open_tree_properties()
            )
            menu.addAction(act_props)
        # Per-node actions never apply to the ROOT row (it IS the tree, not a
        # tool/folder you can open, edit, or remove).
        if item is not None and not _is_root(item):
            if _is_leaf(item):
                act_open = QAction("Open", self)
                act_open.setIcon(_tv_std_icon(_SP.SP_MediaPlay))
                act_open.triggered.connect(
                    lambda _=False, it=item: self._on_item_activated(it, 0)
                )
                menu.addAction(act_open)
                # v0.6.1 — Edit the tool the mouse is over.  Emits
                # editRequested so the main window opens the tool
                # editor bound to this file (Save writes back here).
                act_edit = QAction("Edit", self)
                act_edit.setIcon(
                    _tv_std_icon(_SP.SP_FileDialogContentsView))
                act_edit.triggered.connect(
                    lambda _=False, it=item: self._emit_edit_for(it)
                )
                menu.addAction(act_edit)
            if _is_subtree(item):
                # v0.8.0a100 — open the LINKED tree in the editor so the user
                # can edit IT (set its Category / properties / nodes).  Without
                # this, a linked subtree (forest member, auto-group, wrapper)
                # could only be Refreshed or Run, never edited — the "can't
                # right-click and edit the underlying tree" gap.
                act_open_tree = QAction("Open in editor", self)
                act_open_tree.setIcon(
                    _tv_std_icon(_SP.SP_FileDialogContentsView))
                act_open_tree.triggered.connect(
                    lambda _=False, it=item: self._emit_open_tree_for(it)
                )
                menu.addAction(act_open_tree)
                # v0.8.0a104 — edit the LINKED tree's OWN properties (name /
                # category / path-prepend) in place, writing back to its file,
                # WITHOUT first opening it as the editor root.  This is the
                # forest-editor gap the user hit: right-clicking a member like
                # ffmpeg offered no "Tree properties" (only the ROOT row did), so
                # there was no direct way to set ffmpeg's Category from the forest
                # view.  Mirrors the root row's "Tree properties…".
                act_sub_props = QAction("Tree properties…", self)
                act_sub_props.setIcon(
                    _tv_std_icon(_SP.SP_FileDialogDetailedView))
                act_sub_props.triggered.connect(
                    lambda _=False, it=item: self._open_subtree_properties(it)
                )
                menu.addAction(act_sub_props)
                act_refresh = QAction("Refresh subtree", self)
                act_refresh.setIcon(_tv_std_icon(_SP.SP_BrowserReload))
                act_refresh.triggered.connect(
                    lambda _=False, it=item: self._expand_subtree(it)
                )
                menu.addAction(act_refresh)
            # Open standalone — same gesture as double-right-click,
            # also reachable from the menu.
            act_standalone = QAction("Open standalone", self)
            act_standalone.setIcon(
                _tv_std_icon(_SP.SP_TitleBarNormalButton))
            act_standalone.triggered.connect(
                lambda _=False, it=item: self._emit_standalone_for(it)
            )
            menu.addAction(act_standalone)
            act_remove = QAction("Remove", self)
            act_remove.setIcon(_tv_std_icon(_SP.SP_TrashIcon))
            act_remove.triggered.connect(self._remove_selected)
            menu.addAction(act_remove)

            # v0.8.0a34+ -- Uninstall app from disk.  Mirrors the
            # action surfaced in the cell-popup right-click menu
            # (scriptree.shell.tree_popup._PerItemContextFilter).
            # The catalog path that drives uninstall lives in the
            # leaf's _ROLE_PATH; for subtrees we use the subtree's
            # own .scriptreetree path.  Disabled with a tooltip
            # when the catalog isn't under one of the install
            # roots (the underlying uninstall_app would refuse it
            # anyway -- this gives the user feedback BEFORE the
            # click).
            uninstall_path: str | None = None
            if _is_leaf(item):
                uninstall_path = item.data(0, _ROLE_PATH) or None
            elif _is_subtree(item):
                uninstall_path = item.data(0, _ROLE_SUBTREE) or None
            if uninstall_path:
                act_uninstall = QAction(
                    "Uninstall app from disk...", self,
                )
                act_uninstall.setIcon(
                    _tv_std_icon(_SP.SP_TrashIcon)
                )
                # Predicate matches the cell-popup's
                # ``_catalog_is_uninstallable`` semantics: the
                # catalog's parent folder must be a strict
                # descendant of one of the install roots.
                uninstallable = False
                try:
                    from scriptree.core.app_install import (
                        default_personal_root,
                        default_shared_root,
                    )
                    parent_dir = Path(
                        uninstall_path
                    ).resolve().parent
                    for fn in (
                        default_personal_root,
                        default_shared_root,
                    ):
                        try:
                            root = Path(fn()).resolve()
                        except Exception:  # noqa: BLE001
                            continue
                        try:
                            rel = parent_dir.relative_to(root)
                        except ValueError:
                            continue
                        if len(rel.parts) >= 1:
                            uninstallable = True
                            break
                except Exception:  # noqa: BLE001
                    uninstallable = False
                if uninstallable:
                    act_uninstall.triggered.connect(
                        lambda _=False, p=uninstall_path:
                        self.uninstallRequested.emit(p)
                    )
                else:
                    act_uninstall.setEnabled(False)
                    act_uninstall.setToolTip(
                        "This catalog is not under a managed "
                        "install location (the personal "
                        "app-data root or the shared "
                        "<ScripTree>/ScripTreeApps tree).\n\n"
                        "Drop-installed apps can be uninstalled "
                        "from here; manually-placed catalogs "
                        "must be removed by hand from their "
                        "folder."
                    )
                menu.addAction(act_uninstall)

            if _is_folder(item):
                act_rename = QAction("Rename", self)
                act_rename.setIcon(
                    _tv_std_icon(_SP.SP_FileDialogDetailedView))
                act_rename.triggered.connect(
                    lambda _=False, it=item: self._tree_widget.editItem(it, 0)
                )
                menu.addAction(act_rename)
            menu.addSeparator()
        act_new_folder = QAction("New folder", self)
        act_new_folder.setIcon(_tv_std_icon(_SP.SP_FileDialogNewFolder))
        act_new_folder.triggered.connect(self._add_folder)
        menu.addAction(act_new_folder)
        act_add_tool = QAction("Add tool...", self)
        act_add_tool.setIcon(_tv_std_icon(_SP.SP_DialogOpenButton))
        act_add_tool.triggered.connect(self._add_tool_via_dialog)
        menu.addAction(act_add_tool)

        # v0.8.0a35+ -- Save actions surfaced on every right-click,
        # so the user doesn't have to fish through the menu bar to
        # save the loaded tree.  Pre-a35 the only path was File ->
        # Save (now File -> Save current); the right-click was
        # surface-blind and offered no Save at all.  User
        # explicitly asked for it: "When I right clicked at the
        # top of the tree with forest open there was no save
        # option."
        menu.addSeparator()
        act_save_tree = QAction("Save tree", self)
        act_save_tree.setIcon(
            _tv_std_icon(_SP.SP_DialogSaveButton)
        )
        act_save_tree.setToolTip(
            "Save the currently loaded .scriptreetree.  When the "
            "tree is the merged temp tree built by V3's forest, "
            "this also pushes back to each origin file."
        )
        act_save_tree.triggered.connect(self._save_tree)
        menu.addAction(act_save_tree)

        act_save_tree_as = QAction("Save tree as...", self)
        act_save_tree_as.setIcon(
            _tv_std_icon(_SP.SP_DialogSaveButton)
        )
        act_save_tree_as.triggered.connect(self.save_as)
        menu.addAction(act_save_tree_as)

    def _emit_edit_for(self, item) -> None:
        path = item.data(0, _ROLE_PATH)
        if not path:
            return
        if not Path(path).exists():
            self._offer_missing_tool_recovery(item, path)
            return
        try:
            tool = load_tool(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Load error", str(e))
            return
        self.editRequested.emit(tool, path)

    def _emit_open_tree_for(self, item) -> None:
        """Open a SUBTREE row's linked ``.scriptreetree`` in the editor as the
        editable root tree (v0.8.0a100)."""
        path = item.data(0, _ROLE_SUBTREE)
        if not path:
            return
        if not Path(path).exists():
            QMessageBox.warning(
                self, "Open in editor",
                f"The linked tree no longer exists:\n{path}",
            )
            return
        self.openTreeRequested.emit(str(path))

    def _emit_standalone_for(self, item) -> None:
        desc = self._standalone_descriptor(item)
        if desc is not None:
            self.standaloneRequested.emit(desc)

    # --- launch (single-click) ------------------------------------------

    def _on_item_activated(self, item: QTreeWidgetItem, _col: int) -> None:
        if _is_root(item):
            return  # the tree root isn't launchable — it IS the tree
        # Subtree items: (re)load their children from the referenced file ONLY
        # if they haven't been cleanly expanded yet.  v0.8.0a115 -- a single
        # click on an ALREADY-loaded subtree used to call ``_expand_subtree``,
        # which wipes the children and re-reads from disk (line ~1236) --
        # discarding the user's in-place edits (drop / remove / rename / New
        # Folder).  That's the reported "reorganise ffmpeg, click it again, lose
        # my changes" bug.  The initial load (``_add_node_item``) already
        # populated + flagged ``_ROLE_EXPAND_OK`` True; clicking such a row must
        # only SELECT it, not reload.  A subtree that FAILED to expand
        # (EXPAND_OK not True) is still reloaded on click so the user can retry.
        if _is_subtree(item):
            if item.data(0, _ROLE_EXPAND_OK) is not True:
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
        # Respect an existing display_name override if one was set on
        # this leaf in the tree JSON — the user replaced the file, but
        # the pretty label the tree author gave it still applies.
        existing_display = item.data(0, _ROLE_DISPLAY_NAME)
        item.setText(
            0, existing_display or tool.name or Path(resolved).stem
        )
        self._mark_dirty()
        self._save_tree()  # quiet; only writes if possible
        self.toolSelected.emit(tool, resolved)

    # --- QTreeWidget → TreeDef rebuild ----------------------------------

    def _build_tree_def(self) -> TreeDef:
        """Rebuild the ``TreeDef`` from the live tree widget on save.

        v0.8.0a95 — **preserve every tree-level field.**  Pre-a95 this returned
        ``TreeDef(name=self._tree.name, nodes=nodes)``, which silently RESET all
        of ``TreeDef``'s other 18 fields to their defaults on every Save — so
        opening a tree in the editor and saving wiped its ``category``, the whole
        ``cell_*`` icon/label set, ``menus``, ``path_prepend``, ``folder_layout``,
        ``auto_discover``, ``excluded`` and ``schema_version``.  We instead start
        from the loaded ``self._tree`` and ``dataclasses.replace`` ONLY the two
        things the widget actually owns: the node list (the on-screen structure)
        and the name (in case it was renamed).  Any tree-level edits the user
        makes (e.g. via the properties editor) are applied to ``self._tree``
        first, so they flow through here automatically.
        """
        from dataclasses import replace
        assert self._tree is not None
        root = self._root_item()
        nodes: list[TreeNode] = []
        if root is not None:
            # v0.8.0a96 — the nodes live UNDER the root row; the root's label is
            # the (possibly inline-renamed) tree name.
            name = (root.text(0) or "").strip() or self._tree.name
            for i in range(root.childCount()):
                node = self._item_to_node(root.child(i))
                if node is not None:
                    nodes.append(node)
        else:
            # Legacy / defensive: no root row → top-level items ARE the nodes.
            name = self._tree.name
            for i in range(self._tree_widget.topLevelItemCount()):
                node = self._item_to_node(self._tree_widget.topLevelItem(i))
                if node is not None:
                    nodes.append(node)
        return replace(self._tree, name=name, nodes=nodes)

    @staticmethod
    def _icon_kwargs_from_item(item: QTreeWidgetItem) -> dict[str, str]:
        """v0.8.0a103 — the per-node icon override (``icon`` / ``icon_data`` /
        ``icon_format``) read back off the item for lossless serialization.
        Defaults to ``""`` (matching ``TreeNode`` + ``_node_from_dict``) so an
        icon-free node round-trips identically and never false-diffs."""
        return {
            "icon": item.data(0, _ROLE_ICON) or "",
            "icon_data": item.data(0, _ROLE_ICON_DATA) or "",
            "icon_format": item.data(0, _ROLE_ICON_FORMAT) or "",
        }

    def _item_to_node(self, item: QTreeWidgetItem) -> TreeNode | None:
        if _is_subtree(item):
            # Subtree items are serialized as leaves pointing to
            # .scriptreetree files — their children are loaded
            # dynamically at display time, not persisted.  a103 — carry
            # configuration + icon overrides (previously dropped for subtree
            # refs, unlike plain leaves).
            abs_path = item.data(0, _ROLE_SUBTREE)
            if not abs_path:
                return None
            return TreeNode(
                type="leaf",
                path=self._maybe_relative(abs_path),
                display_name=item.data(0, _ROLE_DISPLAY_NAME) or None,
                configuration=item.data(0, _ROLE_CONFIGURATION) or None,
                **self._icon_kwargs_from_item(item),
            )
        if _is_leaf(item):
            abs_path = item.data(0, _ROLE_PATH)
            if not abs_path:
                return None
            return TreeNode(
                type="leaf",
                path=self._maybe_relative(abs_path),
                display_name=item.data(0, _ROLE_DISPLAY_NAME) or None,
                configuration=item.data(0, _ROLE_CONFIGURATION) or None,
                **self._icon_kwargs_from_item(item),
            )
        children: list[TreeNode] = []
        for i in range(item.childCount()):
            child = self._item_to_node(item.child(i))
            if child is not None:
                children.append(child)
        # a103 review fix — derive a folder's name + display_name from the row's
        # current label vs the "shown" baseline, so:
        #   * a name+display_name folder round-trips losslessly when untouched;
        #   * an inline RENAME (label changed away from the shown baseline) makes
        #     the new text the name and DROPS the now-stale display_name, so the
        #     rename takes effect everywhere (consumers show ``display_name or
        #     name``) instead of being shadowed by the old display_name;
        #   * an empty-name folder does NOT mutate to the "(folder)" placeholder
        #     or churn (the placeholder is display-only; the authored "" name is
        #     recovered from _ROLE_FOLDER_NAME).
        authored = item.data(0, _ROLE_FOLDER_NAME)
        dn = item.data(0, _ROLE_DISPLAY_NAME) or None
        text = item.text(0)
        if authored is None:
            # Folder created in the editor: its label simply IS the name.
            name, display_name = text, None
        else:
            shown = dn or authored or "(folder)"
            if text == shown:
                name, display_name = authored, dn       # untouched
            else:
                name, display_name = text, None          # renamed → label wins
        return TreeNode(
            type="folder",
            name=name,
            children=children,
            display_name=display_name,
            **self._icon_kwargs_from_item(item),
        )

    # --- tree configurations -----------------------------------------------

    def _open_tree_properties(self) -> None:
        """Open the tree-properties editor for the loaded tree (v0.8.0a96).

        Edits the tree's OWN ``name`` / ``category`` / ``path_prepend`` and
        applies them to ``self._tree`` so the next Save persists them (every
        other tree-level field rides through untouched via ``_build_tree_def``).
        """
        if self._tree is None:
            QMessageBox.information(
                self, "No tree loaded", "Load or start a tree first.",
            )
            return
        ro = getattr(self, "_tree_read_only", False)
        dlg = _TreePropertiesDialog(
            name=self._tree.name,
            category=self._tree.category,
            path_prepend=list(self._tree.path_prepend or []),
            read_only=ro,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted or ro:
            return
        from dataclasses import replace
        vals = dlg.values()
        new_name = vals["name"] or self._tree.name
        self._tree = replace(
            self._tree,
            name=new_name,
            category=vals["category"],
            path_prepend=vals["path_prepend"],
        )
        # Reflect the (possibly new) name on the root row + the title.
        root = self._root_item()
        if root is not None:
            root.setText(0, new_name)
        self._mark_dirty()
        self._update_title()

    def _open_subtree_properties(self, item: QTreeWidgetItem) -> None:
        """v0.8.0a104 — edit a LINKED subtree's OWN ``name`` / ``category`` /
        ``path_prepend`` directly from its row and write them back to the
        referenced ``.scriptreetree`` file, WITHOUT first opening it as the
        editor root.

        The forest-editor gap this closes: when the forest is opened as the
        root, a member like ``ffmpeg`` is a subtree ROW (not the root), so the
        root-only "Tree properties…" action never appeared on it — the user
        could not set ffmpeg's Category from the forest view (only via the extra
        "Open in editor" hop).  This loads the linked tree, shows the same
        ``_TreePropertiesDialog``, and persists name/category/path_prepend back
        to its file (``dataclasses.replace`` preserves the tree's nodes + every
        other field, the a95 discipline)."""
        path = item.data(0, _ROLE_SUBTREE)
        if not path:
            return
        p = Path(path)
        try:
            tree = load_tree(str(p))
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, "Load error",
                f"Could not load the linked tree:\n{e}",
            )
            return
        # A synthesised auto-group's name/category are REGENERATED from its
        # member tools' Category fields (a98/a102), so editing them here is
        # futile — say so and bail rather than write a file that the next
        # Re-organise overwrites.  (To move a tool, edit ITS Category, or use
        # the group's drag-to-recategorize via "Open in editor".)
        try:
            is_group = "_groups" in p.resolve().parts
        except (OSError, ValueError):
            is_group = "_groups" in p.parts
        if is_group:
            QMessageBox.information(
                self, "Synthesised auto-group",
                "This is an auto-generated category group — its name and "
                "category are rebuilt from the member tools' Category fields, "
                "so changes here would not persist.\n\nTo re-file a tool, edit "
                "its Category (right-click the tool → Edit), or open this group "
                "in the editor and drag tools between its folders.",
            )
            return
        dlg = _TreePropertiesDialog(
            name=tree.name,
            category=tree.category,
            path_prepend=list(tree.path_prepend or []),
            read_only=False,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        from dataclasses import replace
        vals = dlg.values()
        new_name = vals["name"] or tree.name
        updated = replace(
            tree,
            name=new_name,
            category=vals["category"],
            path_prepend=vals["path_prepend"],
        )
        try:
            save_tree(updated, p)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, "Save error",
                f"Could not save the linked tree:\n{e}",
            )
            return
        # Reflect the (possibly new) name on the subtree row's label — but KEEP
        # the PARENT leaf's display_name override when one was set: that override
        # (stored in _ROLE_DISPLAY_NAME) is what a fresh reload re-applies (see
        # _new_subtree_item), so writing the linked tree's own name here would
        # transiently desync the visible label until the next load.  Mirrors the
        # leaf-replacement path's label logic.
        existing_display = item.data(0, _ROLE_DISPLAY_NAME)
        new_label = existing_display or new_name
        if new_label:
            item.setText(0, new_label)

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
