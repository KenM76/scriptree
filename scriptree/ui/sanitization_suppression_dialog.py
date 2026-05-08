"""Edit -> Sanitization warnings... dialog (V3 v0.3.4).

Provides the inverse of the three "Don't warn again" checkboxes
in the injection-warning popup: a simple read/edit view of the
persisted suppression state, with one-click un-mute for any
entry.

UX
--

Top section: a single checkbox showing the global mute state.
Toggling it writes through immediately.

Middle section: list of muted tools (tool path + Remove button
per row).

Bottom section: tree of muted fields per tool (tool path expands
to show field IDs, each with a Remove button).

Footer: a single "Re-enable everything" button + Close.

The dialog is read-only of the underlying ``QSettings`` data; the
user's edits are written back as they happen via the
``sanitize_suppression`` module's setter API.  Closing the dialog
takes effect immediately on the next Run.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import sanitize_suppression as _supp


class SanitizationSuppressionDialog(QDialog):
    """The "View / re-enable suppressed warnings" dialog."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sanitization warnings")
        self.setMinimumWidth(540)
        self.setMinimumHeight(440)

        outer = QVBoxLayout(self)

        # --- Global mute --------------------------------------------------
        outer.addWidget(QLabel(
            "<b>Global mute</b> &mdash; silences sanitization warnings "
            "across every tool."
        ))
        self._chk_global = QCheckBox(
            "Suppress sanitization warnings for every tool, everywhere."
        )
        self._chk_global.setChecked(_supp.is_globally_muted())
        self._chk_global.toggled.connect(self._on_global_toggled)
        outer.addWidget(self._chk_global)

        outer.addSpacing(8)

        # --- Per-tool list ------------------------------------------------
        outer.addWidget(QLabel(
            "<b>Muted tools</b> &mdash; warnings silenced for the whole "
            "tool's form."
        ))
        self._tool_list = QListWidget()
        self._tool_list.setAlternatingRowColors(True)
        outer.addWidget(self._tool_list, stretch=1)

        tool_btn_row = QHBoxLayout()
        tool_btn_row.addStretch(1)
        self._btn_unmute_tool = QPushButton("Re-enable selected tool")
        self._btn_unmute_tool.clicked.connect(self._on_unmute_tool)
        tool_btn_row.addWidget(self._btn_unmute_tool)
        outer.addLayout(tool_btn_row)

        outer.addSpacing(8)

        # --- Per-field tree -----------------------------------------------
        outer.addWidget(QLabel(
            "<b>Muted fields</b> &mdash; warnings silenced for specific "
            "form fields within a tool."
        ))
        self._field_tree = QTreeWidget()
        self._field_tree.setHeaderLabels(["Tool / Field"])
        self._field_tree.setAlternatingRowColors(True)
        outer.addWidget(self._field_tree, stretch=1)

        field_btn_row = QHBoxLayout()
        field_btn_row.addStretch(1)
        self._btn_unmute_field = QPushButton("Re-enable selected field")
        self._btn_unmute_field.clicked.connect(self._on_unmute_field)
        field_btn_row.addWidget(self._btn_unmute_field)
        outer.addLayout(field_btn_row)

        outer.addSpacing(8)

        # --- Footer -------------------------------------------------------
        footer = QHBoxLayout()
        self._btn_clear_all = QPushButton("Re-enable everything")
        self._btn_clear_all.setToolTip(
            "Clear the global mute and every per-tool / per-field mute."
        )
        self._btn_clear_all.clicked.connect(self._on_clear_all)
        footer.addWidget(self._btn_clear_all)
        footer.addStretch(1)
        close_btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btns.rejected.connect(self.reject)
        footer.addWidget(close_btns)
        outer.addLayout(footer)

        self._refresh()

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        """Rebuild list + tree from the current QSettings state."""
        self._chk_global.blockSignals(True)
        self._chk_global.setChecked(_supp.is_globally_muted())
        self._chk_global.blockSignals(False)

        # Tools list.
        self._tool_list.clear()
        for tool_path in sorted(_supp.muted_tools()):
            item = QListWidgetItem(tool_path)
            item.setData(Qt.ItemDataRole.UserRole, tool_path)
            self._tool_list.addItem(item)
        if self._tool_list.count() == 0:
            placeholder = QListWidgetItem("(no tools muted)")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._tool_list.addItem(placeholder)

        # Field tree — one top-level item per tool, fields as children.
        self._field_tree.clear()
        from ..core.sanitize_suppression import _load_fields_map
        fields_map = _load_fields_map()
        if not fields_map:
            placeholder = QTreeWidgetItem(["(no fields muted)"])
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._field_tree.addTopLevelItem(placeholder)
        else:
            for tool_path in sorted(fields_map.keys()):
                root = QTreeWidgetItem([tool_path])
                root.setData(0, Qt.ItemDataRole.UserRole, ("tool", tool_path))
                for fid in sorted(fields_map[tool_path]):
                    child = QTreeWidgetItem([fid])
                    child.setData(
                        0, Qt.ItemDataRole.UserRole,
                        ("field", tool_path, fid),
                    )
                    root.addChild(child)
                root.setExpanded(True)
                self._field_tree.addTopLevelItem(root)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_global_toggled(self, checked: bool) -> None:
        _supp.set_globally_muted(bool(checked))

    def _on_unmute_tool(self) -> None:
        item = self._tool_list.currentItem()
        if item is None:
            return
        tool_path = item.data(Qt.ItemDataRole.UserRole)
        if not tool_path:
            return
        _supp.unmute_tool(tool_path)
        self._refresh()

    def _on_unmute_field(self) -> None:
        item = self._field_tree.currentItem()
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind = data[0]
        if kind == "field":
            _, tool_path, fid = data
            _supp.unmute_field_for_tool(tool_path, fid)
        elif kind == "tool":
            # Selected the tool root — un-mute every field under it.
            _, tool_path = data
            for fid in list(_supp.muted_fields_for_tool(tool_path)):
                _supp.unmute_field_for_tool(tool_path, fid)
        self._refresh()

    def _on_clear_all(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Re-enable everything?",
            "This clears the global mute, every per-tool mute, and "
            "every per-field mute.  Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        _supp.clear_all()
        self._refresh()
