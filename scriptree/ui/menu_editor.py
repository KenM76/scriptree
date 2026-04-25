"""Editor dialog for a tool's custom menus (``ToolDef.menus``).

The tool runner exposes a ``QMenuBar`` built from
``list[MenuItemDef]``. Each top-level item declares which menu bar
entry (``MenuItemDef.menu``) it belongs to, and items with non-empty
``children`` become submenus. ``label == "-"`` is a separator.

This dialog lets the tool author edit that list visually — add menus,
add action items, add submenus, add separators, reorder within a
parent, and edit each item's label / command / keyboard shortcut /
tooltip — without hand-editing the JSON.

On OK it returns a fresh flat ``list[MenuItemDef]`` ready to drop
into ``tool.menus``.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.model import MenuItemDef


# Qt data roles used on each QTreeWidgetItem.
#: Stores the internal kind: "menu" (top-level branch), "action",
#: "submenu", or "separator".
_ROLE_KIND = Qt.ItemDataRole.UserRole
#: For "action" and "submenu" items, stores the current MenuItemDef
#: fields as a dict so the property panel can edit them before they're
#: flushed back to the model on accept(). "menu" branches just use the
#: Qt item text as their display/menu name.
_ROLE_DATA = Qt.ItemDataRole.UserRole + 1


class MenuEditorDialog(QDialog):
    """Edit a tool's custom menu bar.

    Input: ``menus: list[MenuItemDef]`` (read, not mutated).
    Output: ``self.menus`` after ``exec()`` returns ``Accepted``.
    """

    def __init__(
        self,
        menus: list[MenuItemDef],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit custom menus")
        self.resize(720, 520)

        # Work on a deep copy so Cancel is genuinely non-destructive.
        self._menus: list[MenuItemDef] = deepcopy(menus)

        outer = QVBoxLayout(self)

        help_label = QLabel(
            "<i>Top-level branches are menu bar entries. Each can hold "
            "actions, submenus, and separators. Select an item to edit "
            "its details on the right.</i>"
        )
        help_label.setWordWrap(True)
        outer.addWidget(help_label)

        split = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(split, stretch=1)

        # --- Left: tree + toolbar ----------------------------------------
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Menu / item", "Kind"])
        self._tree.setColumnWidth(0, 280)
        self._tree.currentItemChanged.connect(self._on_selection_changed)
        self._tree.itemChanged.connect(self._on_item_renamed_inline)
        left_layout.addWidget(self._tree, stretch=1)

        toolbar = QHBoxLayout()
        self._btn_add_menu = QPushButton("+ Menu")
        self._btn_add_menu.setToolTip(
            "Add a new top-level menu (e.g. \"Tools\", \"Reports\")."
        )
        self._btn_add_menu.clicked.connect(self._add_menu)
        toolbar.addWidget(self._btn_add_menu)

        self._btn_add_action = QPushButton("+ Action")
        self._btn_add_action.setToolTip(
            "Add an action item under the selected menu or submenu."
        )
        self._btn_add_action.clicked.connect(self._add_action)
        toolbar.addWidget(self._btn_add_action)

        self._btn_add_submenu = QPushButton("+ Submenu")
        self._btn_add_submenu.setToolTip(
            "Add a submenu (a nested menu) under the selected parent."
        )
        self._btn_add_submenu.clicked.connect(self._add_submenu)
        toolbar.addWidget(self._btn_add_submenu)

        self._btn_add_sep = QPushButton("+ Separator")
        self._btn_add_sep.setToolTip(
            "Add a horizontal separator line under the selected parent."
        )
        self._btn_add_sep.clicked.connect(self._add_separator)
        toolbar.addWidget(self._btn_add_sep)

        toolbar.addStretch(1)
        self._btn_up = QPushButton("↑")
        self._btn_up.setFixedWidth(32)
        self._btn_up.setToolTip("Move the selected item up within its parent.")
        self._btn_up.clicked.connect(lambda: self._move_selected(-1))
        toolbar.addWidget(self._btn_up)

        self._btn_down = QPushButton("↓")
        self._btn_down.setFixedWidth(32)
        self._btn_down.setToolTip("Move the selected item down within its parent.")
        self._btn_down.clicked.connect(lambda: self._move_selected(+1))
        toolbar.addWidget(self._btn_down)

        self._btn_remove = QPushButton("Remove")
        self._btn_remove.setToolTip("Delete the selected menu or item.")
        self._btn_remove.clicked.connect(self._remove_selected)
        toolbar.addWidget(self._btn_remove)

        left_layout.addLayout(toolbar)
        split.addWidget(left)

        # --- Right: property panel ---------------------------------------
        right_box = QGroupBox("Details")
        right_form = QFormLayout(right_box)

        self._field_label = QLineEdit()
        self._field_label.editingFinished.connect(self._on_field_changed)
        right_form.addRow("Label:", self._field_label)

        self._field_command = QLineEdit()
        self._field_command.setPlaceholderText(
            "Shell command to run when clicked (e.g. notepad C:/tmp/log.txt)"
        )
        self._field_command.editingFinished.connect(self._on_field_changed)
        right_form.addRow("Command:", self._field_command)

        self._field_shortcut = QLineEdit()
        self._field_shortcut.setPlaceholderText(
            "e.g. Ctrl+L — Qt shortcut string"
        )
        self._field_shortcut.editingFinished.connect(self._on_field_changed)
        right_form.addRow("Shortcut:", self._field_shortcut)

        self._field_tooltip = QLineEdit()
        self._field_tooltip.editingFinished.connect(self._on_field_changed)
        right_form.addRow("Tooltip:", self._field_tooltip)

        self._detail_hint = QLabel()
        self._detail_hint.setWordWrap(True)
        self._detail_hint.setStyleSheet("color: #666; font-style: italic;")
        right_form.addRow(self._detail_hint)

        split.addWidget(right_box)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        # --- OK / Cancel --------------------------------------------------
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

        self._reloading = False
        self._load_tree()
        self._update_detail_panel(None)

    # --- load / save ------------------------------------------------------

    def _load_tree(self) -> None:
        """Rebuild the tree widget from self._menus."""
        self._reloading = True
        try:
            self._tree.clear()
            # Group top-level items by their .menu field, preserving
            # the first-occurrence order of each menu name.
            order: list[str] = []
            seen: dict[str, list[MenuItemDef]] = {}
            for item in self._menus:
                key = item.menu or "Tools"
                if key not in seen:
                    seen[key] = []
                    order.append(key)
                seen[key].append(item)
            for menu_name in order:
                menu_item = self._make_menu_branch(menu_name)
                for sub in seen[menu_name]:
                    self._append_item(menu_item, sub)
                menu_item.setExpanded(True)
            self._tree.expandAll()
        finally:
            self._reloading = False

    def _make_menu_branch(self, name: str) -> QTreeWidgetItem:
        """Create a top-level branch representing a menu bar entry."""
        item = QTreeWidgetItem([name, "menu"])
        item.setData(0, _ROLE_KIND, "menu")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self._tree.addTopLevelItem(item)
        return item

    def _append_item(
        self, parent: QTreeWidgetItem, mid: MenuItemDef
    ) -> QTreeWidgetItem:
        """Recursively materialize one MenuItemDef beneath *parent*."""
        if mid.label == "-":
            child = QTreeWidgetItem(["———", "separator"])
            child.setData(0, _ROLE_KIND, "separator")
            child.setData(0, _ROLE_DATA, {"label": "-"})
            parent.addChild(child)
            return child

        kind = "submenu" if mid.children else "action"
        child = QTreeWidgetItem([mid.label, kind])
        child.setData(0, _ROLE_KIND, kind)
        child.setData(0, _ROLE_DATA, {
            "label": mid.label,
            "command": mid.command,
            "shortcut": mid.shortcut,
            "tooltip": mid.tooltip,
        })
        child.setFlags(child.flags() | Qt.ItemFlag.ItemIsEditable)
        parent.addChild(child)
        for grandchild in mid.children:
            self._append_item(child, grandchild)
        return child

    def accept(self) -> None:
        """Walk the tree back into a flat list of MenuItemDefs."""
        self._flush_panel_to_current()
        result: list[MenuItemDef] = []
        for i in range(self._tree.topLevelItemCount()):
            menu_branch = self._tree.topLevelItem(i)
            menu_name = menu_branch.text(0).strip() or "Tools"
            for j in range(menu_branch.childCount()):
                result.append(
                    self._item_to_def(menu_branch.child(j), menu_name)
                )
        self.menus = result
        super().accept()

    def _item_to_def(
        self, item: QTreeWidgetItem, menu_name: str
    ) -> MenuItemDef:
        kind = item.data(0, _ROLE_KIND)
        if kind == "separator":
            return MenuItemDef(label="-", menu=menu_name)
        data = item.data(0, _ROLE_DATA) or {}
        children = []
        if kind == "submenu":
            for i in range(item.childCount()):
                # Nested items don't carry menu_name on the MenuItemDef
                # itself — the top-level grouping is enough.
                children.append(self._item_to_def(item.child(i), ""))
        return MenuItemDef(
            label=data.get("label") or item.text(0),
            menu=menu_name,
            command=data.get("command", ""),
            children=children,
            shortcut=data.get("shortcut", ""),
            tooltip=data.get("tooltip", ""),
        )

    # --- add / remove -----------------------------------------------------

    def _add_menu(self) -> None:
        name, ok = QInputDialog.getText(
            self, "New menu", "Menu name:", text="Tools",
        )
        if not ok or not name.strip():
            return
        # Don't allow duplicates — users should add to an existing menu
        # by selecting it and clicking "+ Action" / "+ Submenu".
        for i in range(self._tree.topLevelItemCount()):
            if self._tree.topLevelItem(i).text(0) == name:
                QMessageBox.information(
                    self, "Menu exists",
                    f"A top-level menu named {name!r} already exists.",
                )
                return
        self._make_menu_branch(name.strip())

    def _add_action(self) -> None:
        parent = self._resolve_parent_for_add(allow_menu=True, allow_submenu=True)
        if parent is None:
            return
        child = QTreeWidgetItem(["New action", "action"])
        child.setData(0, _ROLE_KIND, "action")
        child.setData(0, _ROLE_DATA, {
            "label": "New action",
            "command": "",
            "shortcut": "",
            "tooltip": "",
        })
        child.setFlags(child.flags() | Qt.ItemFlag.ItemIsEditable)
        parent.addChild(child)
        parent.setExpanded(True)
        self._tree.setCurrentItem(child)

    def _add_submenu(self) -> None:
        parent = self._resolve_parent_for_add(allow_menu=True, allow_submenu=True)
        if parent is None:
            return
        child = QTreeWidgetItem(["New submenu", "submenu"])
        child.setData(0, _ROLE_KIND, "submenu")
        child.setData(0, _ROLE_DATA, {
            "label": "New submenu",
            "command": "",
            "shortcut": "",
            "tooltip": "",
        })
        child.setFlags(child.flags() | Qt.ItemFlag.ItemIsEditable)
        parent.addChild(child)
        parent.setExpanded(True)
        self._tree.setCurrentItem(child)

    def _add_separator(self) -> None:
        parent = self._resolve_parent_for_add(allow_menu=True, allow_submenu=True)
        if parent is None:
            return
        child = QTreeWidgetItem(["———", "separator"])
        child.setData(0, _ROLE_KIND, "separator")
        child.setData(0, _ROLE_DATA, {"label": "-"})
        parent.addChild(child)
        parent.setExpanded(True)
        self._tree.setCurrentItem(child)

    def _resolve_parent_for_add(
        self, *, allow_menu: bool, allow_submenu: bool
    ) -> QTreeWidgetItem | None:
        """Pick a parent for an add operation based on the selection.

        Rules:
        * If the selected item is a menu or a submenu -> add inside it.
        * If the selected item is an action or separator -> add as a
          sibling inside its parent.
        * If nothing is selected and only one menu exists -> add inside it.
        * Otherwise prompt the user to pick a menu first.
        """
        sel = self._tree.currentItem()
        if sel is not None:
            kind = sel.data(0, _ROLE_KIND)
            if kind == "menu" and allow_menu:
                return sel
            if kind == "submenu" and allow_submenu:
                return sel
            # Treat action/separator selections as "add-sibling" shortcuts.
            if kind in ("action", "separator"):
                return sel.parent() or self._tree.invisibleRootItem()
        # No selection or no usable selection — pick a menu.
        if self._tree.topLevelItemCount() == 0:
            QMessageBox.information(
                self, "No menu yet",
                "Add a top-level menu first (+ Menu), then add actions "
                "or submenus inside it.",
            )
            return None
        if self._tree.topLevelItemCount() == 1:
            return self._tree.topLevelItem(0)
        QMessageBox.information(
            self, "Pick a menu",
            "Select which menu to add to (or click inside a submenu), "
            "then use + Action / + Submenu / + Separator.",
        )
        return None

    def _remove_selected(self) -> None:
        sel = self._tree.currentItem()
        if sel is None:
            return
        parent = sel.parent()
        if parent is None:
            # Top-level menu branch.
            idx = self._tree.indexOfTopLevelItem(sel)
            if idx >= 0:
                self._tree.takeTopLevelItem(idx)
        else:
            parent.removeChild(sel)

    # --- reorder ---------------------------------------------------------

    def _move_selected(self, delta: int) -> None:
        sel = self._tree.currentItem()
        if sel is None:
            return
        parent = sel.parent()
        if parent is None:
            # Top-level menu — reorder within top-level.
            idx = self._tree.indexOfTopLevelItem(sel)
            new_idx = idx + delta
            if not (0 <= new_idx < self._tree.topLevelItemCount()):
                return
            taken = self._tree.takeTopLevelItem(idx)
            self._tree.insertTopLevelItem(new_idx, taken)
            self._tree.setCurrentItem(taken)
            taken.setExpanded(True)
        else:
            idx = parent.indexOfChild(sel)
            new_idx = idx + delta
            if not (0 <= new_idx < parent.childCount()):
                return
            taken = parent.takeChild(idx)
            parent.insertChild(new_idx, taken)
            self._tree.setCurrentItem(taken)

    # --- details panel ---------------------------------------------------

    def _on_selection_changed(
        self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None
    ) -> None:
        # Flush edits made to *previous* before repainting the panel.
        self._flush_panel_to_item(previous)
        self._update_detail_panel(current)

    def _update_detail_panel(self, item: QTreeWidgetItem | None) -> None:
        self._reloading = True
        try:
            if item is None:
                self._field_label.setText("")
                self._field_label.setEnabled(False)
                self._field_command.setText("")
                self._field_command.setEnabled(False)
                self._field_shortcut.setText("")
                self._field_shortcut.setEnabled(False)
                self._field_tooltip.setText("")
                self._field_tooltip.setEnabled(False)
                self._detail_hint.setText(
                    "Select an item in the tree to edit its details."
                )
                return

            kind = item.data(0, _ROLE_KIND)
            if kind == "menu":
                self._field_label.setText(item.text(0))
                self._field_label.setEnabled(True)
                self._field_command.setText("")
                self._field_command.setEnabled(False)
                self._field_shortcut.setText("")
                self._field_shortcut.setEnabled(False)
                self._field_tooltip.setText("")
                self._field_tooltip.setEnabled(False)
                self._detail_hint.setText(
                    "Top-level menu — only the label is editable. Add "
                    "actions, submenus, or separators inside it."
                )
                return

            if kind == "separator":
                self._field_label.setText("———")
                self._field_label.setEnabled(False)
                self._field_command.setText("")
                self._field_command.setEnabled(False)
                self._field_shortcut.setText("")
                self._field_shortcut.setEnabled(False)
                self._field_tooltip.setText("")
                self._field_tooltip.setEnabled(False)
                self._detail_hint.setText(
                    "Separator — renders as a horizontal line. No "
                    "editable fields."
                )
                return

            # action or submenu
            data = item.data(0, _ROLE_DATA) or {}
            self._field_label.setText(data.get("label", item.text(0)))
            self._field_label.setEnabled(True)
            self._field_command.setText(data.get("command", ""))
            self._field_command.setEnabled(kind == "action")
            self._field_shortcut.setText(data.get("shortcut", ""))
            self._field_shortcut.setEnabled(True)
            self._field_tooltip.setText(data.get("tooltip", ""))
            self._field_tooltip.setEnabled(True)
            if kind == "submenu":
                self._detail_hint.setText(
                    "Submenu — holds nested items. Commands attached "
                    "to a submenu itself are ignored; put them on "
                    "action items inside."
                )
            else:
                self._detail_hint.setText(
                    "Action — clicking it runs the command below. "
                    "Shortcut is a Qt shortcut string (e.g. Ctrl+L)."
                )
        finally:
            self._reloading = False

    def _on_field_changed(self) -> None:
        if self._reloading:
            return
        self._flush_panel_to_current()

    def _flush_panel_to_current(self) -> None:
        self._flush_panel_to_item(self._tree.currentItem())

    def _flush_panel_to_item(self, item: QTreeWidgetItem | None) -> None:
        """Copy the detail panel's field values back onto *item*."""
        if item is None or self._reloading:
            return
        kind = item.data(0, _ROLE_KIND)
        new_label = self._field_label.text().strip()
        if kind == "menu":
            if new_label and new_label != item.text(0):
                item.setText(0, new_label)
            return
        if kind == "separator":
            return
        # action / submenu
        data = item.data(0, _ROLE_DATA) or {}
        data["label"] = new_label or data.get("label", "(unnamed)")
        if kind == "action":
            data["command"] = self._field_command.text()
        data["shortcut"] = self._field_shortcut.text()
        data["tooltip"] = self._field_tooltip.text()
        item.setData(0, _ROLE_DATA, data)
        if data["label"] != item.text(0):
            item.setText(0, data["label"])

    def _on_item_renamed_inline(
        self, item: QTreeWidgetItem, column: int
    ) -> None:
        """Keep _ROLE_DATA.label in sync when the user double-clicks
        to rename a row in the tree directly."""
        if self._reloading or column != 0:
            return
        kind = item.data(0, _ROLE_KIND)
        if kind in ("action", "submenu"):
            data = item.data(0, _ROLE_DATA) or {}
            data["label"] = item.text(0)
            item.setData(0, _ROLE_DATA, data)
            # If this is the current selection, refresh the field too.
            if item is self._tree.currentItem():
                was_reloading = self._reloading
                self._reloading = True
                try:
                    self._field_label.setText(item.text(0))
                finally:
                    self._reloading = was_reloading
