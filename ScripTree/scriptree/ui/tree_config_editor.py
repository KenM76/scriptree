"""Dialog for editing tree-level configurations.

A tree configuration maps each leaf tool in a ``.scriptreetree`` to a
named configuration from that tool's sidecar. This dialog shows a list
of tools with a dropdown for each, lets the user pick which config each
tool should use in standalone mode, and saves the result to the tree's
sidecar file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.configs import (
    SAFETREE_CONFIG_NAME,
    TreeConfiguration,
    TreeConfigurationSet,
    default_tree_configuration_set,
    is_reserved_config_name,
    load_configs,
    load_tree_configs,
    save_tree_configs,
)
from ..core.io import load_tree
from ..core.model import TreeDef, TreeNode


def _collect_leaf_paths(
    nodes: list[TreeNode],
) -> list[tuple[str, str]]:
    """Return ``(relative_path, display_name)`` for each leaf.

    The display name is just the file stem so the dialog isn't
    cluttered with long relative paths.
    """
    result: list[tuple[str, str]] = []
    for node in nodes:
        if node.type == "leaf" and node.path:
            if node.path.endswith(".scriptreetree"):
                continue  # skip nested trees
            name = Path(node.path).stem
            result.append((node.path, name))
        elif node.type == "folder":
            result.extend(_collect_leaf_paths(node.children))
    return result


def _available_configs_for_tool(
    tool_path: Path,
) -> list[str]:
    """Read the sidecar for ``tool_path`` and return config names.

    Always includes at least ``["default"]``. Excludes the reserved
    ``safetree`` name from the list since users shouldn't pick it
    manually.
    """
    cfg_set = load_configs(str(tool_path))
    if cfg_set is None:
        return ["default"]
    return [
        c.name
        for c in cfg_set.configurations
        if c.name != SAFETREE_CONFIG_NAME
    ] or ["default"]


class TreeConfigEditorDialog(QDialog):
    """Editor for tree-level configurations.

    Shows each leaf tool in the tree with a dropdown of its available
    configurations. The user picks which config each tool should use
    when the tree is opened in standalone mode.

    Also provides Save / Save As / Delete / switch between named tree
    configurations.
    """

    def __init__(
        self,
        tree_path: str | Path,
        tree_def: TreeDef,
        *,
        read_only: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tree Configurations")
        self.resize(520, 480)
        self._read_only = read_only

        self._tree_path = Path(tree_path).resolve()
        self._tree_def = tree_def
        self._tree_dir = self._tree_path.parent

        # Load or init the tree configuration set.
        loaded = load_tree_configs(str(self._tree_path))
        self._cfg_set = loaded or default_tree_configuration_set()
        self._cfg_loading = False

        root = QVBoxLayout(self)

        # --- Tree config selector bar ---
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Tree configuration:"))

        self._cfg_combo = QComboBox()
        self._cfg_combo.setMinimumWidth(160)
        self._cfg_combo.currentIndexChanged.connect(self._on_combo_changed)
        bar.addWidget(self._cfg_combo, stretch=1)

        self._btn_save = QPushButton("Save")
        self._btn_save.clicked.connect(self._save_current)
        bar.addWidget(self._btn_save)

        self._btn_save_as = QPushButton("Save as...")
        self._btn_save_as.clicked.connect(self._save_as)
        bar.addWidget(self._btn_save_as)

        self._btn_delete = QPushButton("Delete")
        self._btn_delete.clicked.connect(self._delete_current)
        bar.addWidget(self._btn_delete)

        root.addLayout(bar)

        # --- Tool ↔ config mapping ---
        group = QGroupBox("Tool configurations for standalone mode")
        group_layout = QVBoxLayout(group)
        hint = QLabel(
            "<i>Choose which configuration each tool should use when "
            "this tree is opened in standalone mode. If a tool's config "
            "is deleted later, ScripTree will create a 'safetree' "
            "fallback automatically.</i>"
        )
        hint.setWordWrap(True)
        group_layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_widget = QWidget()
        self._form = QFormLayout(scroll_widget)
        self._form.setContentsMargins(4, 4, 4, 4)

        self._leaf_paths = _collect_leaf_paths(tree_def.nodes)
        self._tool_combos: dict[str, QComboBox] = {}

        for rel_path, display_name in self._leaf_paths:
            tool_path = (self._tree_dir / rel_path).resolve()
            available = (
                _available_configs_for_tool(tool_path)
                if tool_path.exists()
                else ["default"]
            )
            combo = QComboBox()
            combo.addItem("(default)")  # empty = use tool's own active
            for cfg_name in available:
                combo.addItem(cfg_name)
            self._tool_combos[rel_path] = combo
            self._form.addRow(display_name, combo)

        scroll.setWidget(scroll_widget)
        group_layout.addWidget(scroll, stretch=1)
        root.addWidget(group, stretch=1)

        # --- OK / Cancel ---
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # Populate the combo and load the active config.
        self._refresh_combo()
        self._load_active_into_form()

        # Disable write controls when read-only.
        if self._read_only:
            self._btn_save.setEnabled(False)
            self._btn_save_as.setEnabled(False)
            self._btn_delete.setEnabled(False)

    # --- combo management ---

    def _refresh_combo(self) -> None:
        self._cfg_loading = True
        try:
            self._cfg_combo.clear()
            for c in self._cfg_set.configurations:
                self._cfg_combo.addItem(c.name)
            idx = self._cfg_combo.findText(self._cfg_set.active)
            if idx >= 0:
                self._cfg_combo.setCurrentIndex(idx)
        finally:
            self._cfg_loading = False
        self._btn_delete.setEnabled(
            len(self._cfg_set.configurations) > 1
        )

    def _on_combo_changed(self, _idx: int) -> None:
        if self._cfg_loading:
            return
        name = self._cfg_combo.currentText()
        if not name:
            return
        self._cfg_set.active = name
        self._load_active_into_form()

    # --- form ↔ config ---

    def _load_active_into_form(self) -> None:
        """Push the active tree config's mappings into the dropdowns."""
        cfg = self._cfg_set.active_config()
        for rel_path, combo in self._tool_combos.items():
            mapped = cfg.tool_configs.get(rel_path, "")
            idx = combo.findText(mapped)
            combo.setCurrentIndex(idx if idx >= 0 else 0)  # 0 = "(default)"

    def _read_form_into_config(self) -> dict[str, str]:
        """Read the current dropdown selections into a tool_configs dict."""
        result: dict[str, str] = {}
        for rel_path, combo in self._tool_combos.items():
            text = combo.currentText()
            if text and text != "(default)":
                result[rel_path] = text
        return result

    # --- save / save as / delete ---

    def _save_current(self) -> None:
        cfg = self._cfg_set.active_config()
        cfg.tool_configs = self._read_form_into_config()
        save_tree_configs(str(self._tree_path), self._cfg_set)

    def _save_as(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Save tree config as", "New tree configuration name:"
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if is_reserved_config_name(name):
            QMessageBox.warning(
                self, "Reserved name",
                f"'{name}' is reserved by ScripTree.",
            )
            return
        existing = self._cfg_set.find(name)
        if existing is not None:
            reply = QMessageBox.question(
                self, "Overwrite?",
                f"Tree configuration '{name}' already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            existing.tool_configs = self._read_form_into_config()
        else:
            self._cfg_set.configurations.append(
                TreeConfiguration(
                    name=name,
                    tool_configs=self._read_form_into_config(),
                )
            )
        self._cfg_set.active = name
        save_tree_configs(str(self._tree_path), self._cfg_set)
        self._refresh_combo()

    def _delete_current(self) -> None:
        if len(self._cfg_set.configurations) <= 1:
            return
        cfg = self._cfg_set.active_config()
        reply = QMessageBox.question(
            self, "Delete?",
            f"Delete tree configuration '{cfg.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._cfg_set.configurations = [
            c for c in self._cfg_set.configurations if c.name != cfg.name
        ]
        self._cfg_set.active = self._cfg_set.configurations[0].name
        save_tree_configs(str(self._tree_path), self._cfg_set)
        self._refresh_combo()
        self._load_active_into_form()

    # --- accept ---

    def _on_accept(self) -> None:
        self._save_current()
        self.accept()
