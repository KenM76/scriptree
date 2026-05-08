"""
forest_dialogs.py — Qt dialogs for the forest layer.

Four dialogs:

  * **FirstRunDialog**  — appears when the forest starts empty (no
    autoload, no explicit Open).  Lets the user pick which folders
    to discover, which item kinds to include, and the update mode,
    then runs discovery and applies whatever they accepted.

  * **UpdateDiffDialog** — surfaces the result of
    ``ForestController.discover_now()`` as a checkbox tree (Adds,
    Removes, Re-includes).  Used by ``update_mode='prompt'`` and
    by the "Auto-add now" button.

  * **ForestSettingsDialog** — edit auto-discovery roots, type
    filter, update mode, enabled flag.

  * **ExcludedItemsDialog** — list of paths the user has previously
    removed from the forest, with a button per row to re-include
    (which clears the path from ``excluded`` and adds it back).

All four are modal QDialogs that take the controller as their first
positional argument and call back into it directly.  Tests can
construct them headlessly, exercise the buttons, and assert the
controller's state changed correctly.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from scriptree.shell.forest_discover import (
    DiscoveredItem, DiscoveryDiff,
)
from scriptree.shell.forest_io import ItemKind

if TYPE_CHECKING:
    from scriptree.shell.forest_controller import ForestController


def _log(msg: str) -> None:
    print(f"[forest_dialogs] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Helper widgets
# ---------------------------------------------------------------------------

class _RootsEditor(QWidget):
    """Add / Remove / Browse list of root folders to scan."""

    def __init__(self, roots: list[str]) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        for r in roots:
            self._list.addItem(QListWidgetItem(r))
        layout.addWidget(self._list)

        row = QHBoxLayout()
        self._btn_add = QPushButton("Add folder…")
        self._btn_browse = QPushButton("Browse current…")
        self._btn_remove = QPushButton("Remove")
        row.addWidget(self._btn_add)
        row.addWidget(self._btn_browse)
        row.addWidget(self._btn_remove)
        row.addStretch(1)
        layout.addLayout(row)

        self._btn_add.clicked.connect(self._add_path)
        self._btn_browse.clicked.connect(self._browse_path)
        self._btn_remove.clicked.connect(self._remove_selected)

    def _add_path(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Add scan root")
        if path:
            self._list.addItem(QListWidgetItem(path))

    def _browse_path(self) -> None:
        # If the user has a row selected, open browse seeded with
        # that path; otherwise just open at cwd.
        seed = ""
        if self._list.currentItem() is not None:
            seed = self._list.currentItem().text()
        path = QFileDialog.getExistingDirectory(self, "Pick scan root", seed)
        if path:
            if self._list.currentItem() is not None:
                self._list.currentItem().setText(path)
            else:
                self._list.addItem(QListWidgetItem(path))

    def _remove_selected(self) -> None:
        for item in list(self._list.selectedItems()):
            self._list.takeItem(self._list.row(item))

    def values(self) -> list[str]:
        return [self._list.item(i).text() for i in range(self._list.count())]


class _IncludeChecklist(QWidget):
    """Three checkboxes for ring / tree / tool inclusion."""

    def __init__(self, include: list[ItemKind]) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._cb_ring = QCheckBox(".scriptreering (rings)")
        self._cb_tree = QCheckBox(".scriptreetree (trees)")
        self._cb_tool = QCheckBox(".scriptree (single tools)")
        self._cb_ring.setChecked("ring" in include)
        self._cb_tree.setChecked("tree" in include)
        self._cb_tool.setChecked("tool" in include)
        layout.addWidget(self._cb_ring)
        layout.addWidget(self._cb_tree)
        layout.addWidget(self._cb_tool)
        layout.addStretch(1)

    def values(self) -> list[ItemKind]:
        out: list[ItemKind] = []
        if self._cb_ring.isChecked():
            out.append("ring")
        if self._cb_tree.isChecked():
            out.append("tree")
        if self._cb_tool.isChecked():
            out.append("tool")
        return out


class _UpdateModeChoice(QWidget):
    """Three radio buttons for off / prompt / auto."""

    def __init__(self, mode: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._rb_off = QRadioButton(
            "Off — never auto-update; only manual Add"
        )
        self._rb_prompt = QRadioButton(
            "Prompt — show me changes and let me confirm (recommended)"
        )
        self._rb_auto = QRadioButton(
            "Auto — apply changes silently"
        )
        if mode == "off":
            self._rb_off.setChecked(True)
        elif mode == "auto":
            self._rb_auto.setChecked(True)
        else:
            self._rb_prompt.setChecked(True)
        layout.addWidget(self._rb_off)
        layout.addWidget(self._rb_prompt)
        layout.addWidget(self._rb_auto)

    def value(self) -> str:
        if self._rb_off.isChecked():
            return "off"
        if self._rb_auto.isChecked():
            return "auto"
        return "prompt"


# ---------------------------------------------------------------------------
# FirstRunDialog
# ---------------------------------------------------------------------------

class FirstRunDialog(QDialog):
    """Empty-forest welcome dialog — populates from ScripTreeApps and
    other folders the user picks, with one-click apply.

    Layout:

      Welcome blurb
      ┌── Scan folders ────────────────┐
      │ [ScripTreeApps    ] (default)  │
      │ [Add folder…]                  │
      └────────────────────────────────┘
      Type filter: [✓] rings [✓] trees [✓] tools
      Update mode: ( ) off (•) prompt ( ) auto
      [Discover & populate]  [Skip — empty forest]
    """

    def __init__(self, controller: "ForestController") -> None:
        super().__init__(controller.forest_window)
        self._controller = controller
        self.setWindowTitle("Welcome to your forest")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "<b>Your forest is empty.</b><br><br>"
            "I can scan folders for ScripTree files and add what I find. "
            "By default I'll scan <code>ScripTreeApps/</code> in the "
            "ScripTree install, but you can add other folders too.<br><br>"
            "For each subfolder I find, I'll add the highest-layer file "
            "available — so a folder with a <code>.scriptreering</code> "
            "becomes one ring, not a pile of individual tools."
        ))

        # Scan folders editor.
        roots_box = QGroupBox("Scan folders")
        roots_layout = QVBoxLayout(roots_box)
        self._roots = _RootsEditor(controller.forest.auto_discover.roots)
        roots_layout.addWidget(self._roots)
        layout.addWidget(roots_box)

        # Type filter.
        filter_box = QGroupBox("What to add when found")
        filter_layout = QVBoxLayout(filter_box)
        self._include = _IncludeChecklist(
            controller.forest.auto_discover.include
        )
        filter_layout.addWidget(self._include)
        layout.addWidget(filter_box)

        # Update mode.
        mode_box = QGroupBox("After this initial populate, when sources change…")
        mode_layout = QVBoxLayout(mode_box)
        self._mode = _UpdateModeChoice(
            controller.forest.auto_discover.update_mode
        )
        mode_layout.addWidget(self._mode)
        layout.addWidget(mode_box)

        # Buttons.
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._btn_skip = QPushButton("Skip — empty forest")
        self._btn_apply = QPushButton("Discover && populate")
        self._btn_apply.setDefault(True)
        btn_row.addWidget(self._btn_skip)
        btn_row.addWidget(self._btn_apply)
        layout.addLayout(btn_row)

        self._btn_skip.clicked.connect(self.reject)
        self._btn_apply.clicked.connect(self._apply)

    def _apply(self) -> None:
        cfg = self._controller.forest.auto_discover
        cfg.roots = self._roots.values()
        cfg.include = self._include.values()
        cfg.update_mode = self._mode.value()
        cfg.enabled = True

        diff = self._controller.discover_now()
        if diff.is_empty():
            QMessageBox.information(
                self,
                "Nothing to add",
                "I scanned the configured folders and didn't find any "
                "ScripTree files.  You can add things manually via the "
                "forest's right-click menu, or change the scan folders "
                "in Forest settings later.",
            )
            self.accept()
            return

        # Apply all of what discovery found — first-run dialog is
        # intentionally one-click; the user can always tidy after.
        self._controller.apply_diff(diff)
        self._controller.save()
        self.accept()


# ---------------------------------------------------------------------------
# UpdateDiffDialog
# ---------------------------------------------------------------------------

class UpdateDiffDialog(QDialog):
    """Diff prompt — checkbox per row in three sections."""

    def __init__(
        self,
        controller: "ForestController",
        diff: DiscoveryDiff,
    ) -> None:
        super().__init__(controller.forest_window)
        self._controller = controller
        self._diff = diff
        self.setWindowTitle("Forest changes detected")
        self.setMinimumWidth(640)
        self.setMinimumHeight(480)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "<b>I found some changes.</b><br>"
            "Tick the items you want to apply.  Items left unticked "
            "stay as they are now."
        ))

        # Three sections, scrollable.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)

        self._cb_added: list[tuple[QCheckBox, DiscoveredItem]] = []
        self._cb_removed: list[tuple[QCheckBox, str]] = []
        self._cb_reincl: list[tuple[QCheckBox, DiscoveredItem]] = []

        if diff.added:
            box = QGroupBox(f"Add to forest ({len(diff.added)})")
            bl = QVBoxLayout(box)
            for item in diff.added:
                cb = QCheckBox(f"[{item.kind}]  {item.path}")
                cb.setChecked(True)
                bl.addWidget(cb)
                self._cb_added.append((cb, item))
            inner_layout.addWidget(box)

        if diff.removed:
            box = QGroupBox(
                f"Remove from forest — file no longer on disk "
                f"({len(diff.removed)})"
            )
            bl = QVBoxLayout(box)
            for item in diff.removed:
                cb = QCheckBox(f"[{item.kind}]  {item.path}")
                cb.setChecked(True)
                bl.addWidget(cb)
                self._cb_removed.append((cb, item.path))
            inner_layout.addWidget(box)

        if diff.previously_excluded:
            box = QGroupBox(
                f"Previously excluded — found again in sources "
                f"({len(diff.previously_excluded)})"
            )
            bl = QVBoxLayout(box)
            bl.addWidget(QLabel(
                "<i>You removed these from the forest before.  "
                "Tick to re-include; leave unticked to keep them out.</i>"
            ))
            for item in diff.previously_excluded:
                cb = QCheckBox(f"[{item.kind}]  {item.path}")
                cb.setChecked(False)
                bl.addWidget(cb)
                self._cb_reincl.append((cb, item))
            inner_layout.addWidget(box)

        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, stretch=1)

        # Action buttons.
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.button(QDialogButtonBox.StandardButton.Apply).setDefault(True)
        layout.addWidget(btn_box)
        btn_box.rejected.connect(self.reject)
        btn_box.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(
            self._apply
        )

    def _apply(self) -> None:
        accepted_added = {it.path for cb, it in self._cb_added if cb.isChecked()}
        accepted_removed = {p for cb, p in self._cb_removed if cb.isChecked()}
        accepted_reincl = {it.path for cb, it in self._cb_reincl if cb.isChecked()}
        self._controller.apply_diff(
            self._diff,
            accepted_added=accepted_added,
            accepted_removed=accepted_removed,
            accepted_reincluded=accepted_reincl,
        )
        self._controller.save()
        self.accept()


# ---------------------------------------------------------------------------
# ForestSettingsDialog
# ---------------------------------------------------------------------------

class ForestSettingsDialog(QDialog):
    """Edit name + auto-discovery config."""

    def __init__(self, controller: "ForestController") -> None:
        super().__init__(controller.forest_window)
        self._controller = controller
        self.setWindowTitle("Forest settings")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._name_edit = QLineEdit(controller.forest.name)
        form.addRow("Forest name:", self._name_edit)
        layout.addLayout(form)

        self._enabled_cb = QCheckBox(
            "Enable auto-discovery (run on launch and on Refresh)"
        )
        self._enabled_cb.setChecked(controller.forest.auto_discover.enabled)
        layout.addWidget(self._enabled_cb)

        roots_box = QGroupBox("Scan folders")
        rl = QVBoxLayout(roots_box)
        self._roots = _RootsEditor(controller.forest.auto_discover.roots)
        rl.addWidget(self._roots)
        layout.addWidget(roots_box)

        filter_box = QGroupBox("What to add when found")
        fl = QVBoxLayout(filter_box)
        self._include = _IncludeChecklist(
            controller.forest.auto_discover.include
        )
        fl.addWidget(self._include)
        layout.addWidget(filter_box)

        mode_box = QGroupBox("Update mode")
        ml = QVBoxLayout(mode_box)
        self._mode = _UpdateModeChoice(
            controller.forest.auto_discover.update_mode
        )
        ml.addWidget(self._mode)
        layout.addWidget(mode_box)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(btn_box)
        btn_box.rejected.connect(self.reject)
        btn_box.accepted.connect(self._save)

    def _save(self) -> None:
        f = self._controller.forest
        f.name = self._name_edit.text().strip() or "Forest"
        f.auto_discover.enabled = self._enabled_cb.isChecked()
        f.auto_discover.roots = self._roots.values()
        f.auto_discover.include = self._include.values()
        f.auto_discover.update_mode = self._mode.value()
        if self._controller.forest_window is not None:
            from scriptree.shell.forest_controller import _derive_label
            try:
                self._controller.forest_window.apply_label_change(
                    text_label=_derive_label(f.name),
                )
            except Exception:  # noqa: BLE001
                pass
        self._controller.save()
        self.accept()


# ---------------------------------------------------------------------------
# ExcludedItemsDialog
# ---------------------------------------------------------------------------

class ExcludedItemsDialog(QDialog):
    """List of excluded paths with per-row Re-include + Forget buttons.

    "Forget" removes a path from the excluded list **without**
    re-adding it — useful when an item was never relevant in the
    first place and the user just wants the dialog clean.
    """

    def __init__(self, controller: "ForestController") -> None:
        super().__init__(controller.forest_window)
        self._controller = controller
        self.setWindowTitle("Excluded items")
        self.setMinimumWidth(620)
        self.setMinimumHeight(420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "<b>Items previously removed from this forest.</b><br>"
            "Auto-discovery skips these even when they exist on disk.  "
            "Use <b>Re-include</b> to bring one back, or <b>Forget</b> "
            "to drop it from the list (so future discovery passes can "
            "consider it again)."
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)

        if not controller.forest.excluded:
            inner_layout.addWidget(QLabel(
                "<i>No excluded items yet.  Right-click a cell or "
                "ring → Remove from forest to add it here.</i>"
            ))

        self._rows: list[tuple[str, QPushButton, QPushButton]] = []
        for path in list(controller.forest.excluded):
            row = QHBoxLayout()
            label = QLabel(path)
            label.setWordWrap(True)
            label.setSizePolicy(label.sizePolicy().horizontalPolicy(),
                                label.sizePolicy().verticalPolicy())
            row.addWidget(label, stretch=1)
            btn_re = QPushButton("Re-include")
            btn_forget = QPushButton("Forget")
            row.addWidget(btn_re)
            row.addWidget(btn_forget)
            wrapper = QWidget()
            wrapper.setLayout(row)
            inner_layout.addWidget(wrapper)
            btn_re.clicked.connect(
                lambda _checked=False, p=path: self._reinclude(p)
            )
            btn_forget.clicked.connect(
                lambda _checked=False, p=path: self._forget(p)
            )
            self._rows.append((path, btn_re, btn_forget))
        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, stretch=1)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.reject)
        btn_box.accepted.connect(self.accept)
        layout.addWidget(btn_box)

    def _reinclude(self, path: str) -> None:
        from scriptree.shell.forest_io import kind_for_suffix
        kind = kind_for_suffix(path) or "tool"
        # add_item already strips path from `excluded`.
        self._controller.add_item(path, kind)
        self._controller.save()
        self.accept()  # close + open afresh if user wants more

    def _forget(self, path: str) -> None:
        self._controller.forest.excluded = [
            e for e in self._controller.forest.excluded if e != path
        ]
        self._controller.forestChanged.emit()
        self._controller.save()
        self.accept()
