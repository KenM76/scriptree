"""Shared widgets for any auto-discovery settings dialog.

## For humans

Three small reusable widget classes used by *both* the forest's
settings dialog (``scriptree.shell.forest_dialogs.ForestSettingsDialog``)
and the tree's settings dialog
(``scriptree.ui.tree_dialogs.TreeSettingsDialog``):

* ``RootsEditor`` — list-with-add/remove of root folders to scan.
* ``UpdateModeChoice`` — three radio buttons for the
  ``"off" | "prompt" | "auto"`` mode.
* ``IncludeKindsChecklist`` — three checkboxes for the forest's
  ``ItemKind`` filter (``ring`` / ``tree`` / ``tool``).  Tree
  dialogs DON'T use this widget (they have a single
  ``include_sibling_trees`` boolean instead), but it lives here
  so the forest settings dialog can import from one tidy place
  rather than scattering widget classes across modules.

## For maintainers / LLMs

* Each widget exposes a tiny ``.values()`` (list-typed) or
  ``.value()`` (scalar) accessor for harvesting the current state
  into a dataclass.  Pure read; no setter once constructed —
  re-construct with new initial values when the underlying state
  changes.
* The module is in ``scriptree.ui`` (the Qt-using widget layer).
  Both ``scriptree.shell.forest_dialogs`` and
  ``scriptree.ui.tree_dialogs`` import from here.  The
  shell→ui direction is acceptable: ``shell`` is the cell-shell
  orchestration layer; ``ui`` is the widget/dialog layer.
* These widgets used to live (under ``_``-prefixed names) inside
  ``scriptree.shell.forest_dialogs``.  v0.8.0a21 promoted them
  to this shared module so the tree dialogs could import from
  one canonical home rather than reach into shell.  The forest
  module re-exports the old underscore names as aliases so any
  external imports keep working.
* No Qt imports at module load that aren't strictly needed: only
  the widgets we use.  ``QFileDialog`` is imported because every
  one of the three widgets pops one or could plausibly want to.
"""
from __future__ import annotations

from typing import Iterable

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# RootsEditor
# ---------------------------------------------------------------------------

class RootsEditor(QWidget):
    """List-with-buttons editor for "scan roots".

    Three buttons: Add folder (browse), Browse current (re-pick
    the selected row's path), Remove (drop selected rows).  The
    underlying ``QListWidget`` shows one row per root path; the
    user can also reorder by dragging.

    Initial state is seeded from ``initial_roots``.  Read the
    final state via ``values() -> list[str]``.
    """

    def __init__(self, initial_roots: Iterable[str]) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        for r in initial_roots:
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
        """Re-browse for a folder, seeded with the currently selected
        row's path.  Falls back to a fresh browse at cwd when no
        row is selected."""
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
        return [
            self._list.item(i).text() for i in range(self._list.count())
        ]


# ---------------------------------------------------------------------------
# UpdateModeChoice
# ---------------------------------------------------------------------------

class UpdateModeChoice(QWidget):
    """Three radio buttons for the ``"off" | "prompt" | "auto"`` mode.

    The active radio reflects ``initial_mode`` on construction;
    read the user's choice via ``value() -> str``.

    Plain-language labels (no jargon).  The "Prompt" option
    carries the ``(recommended)`` suffix because it's the
    safest middle-ground for users who don't know what they
    want yet.
    """

    def __init__(self, initial_mode: str) -> None:
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
        if initial_mode == "off":
            self._rb_off.setChecked(True)
        elif initial_mode == "auto":
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
# IncludeKindsChecklist (forest-only; lives here for proximity)
# ---------------------------------------------------------------------------

class IncludeKindsChecklist(QWidget):
    """Three checkboxes for the forest's ``ItemKind`` filter
    (``ring`` / ``tree`` / ``tool``).

    Initial check state from ``initial_include``.  Read the
    final state via ``values() -> list[str]``.

    Trees DON'T use this widget — they have a single
    ``include_sibling_trees`` boolean.  Kept here so the forest
    settings dialog can import every widget from one tidy place.
    """

    def __init__(self, initial_include: Iterable[str]) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        included = set(initial_include)
        self._cb_ring = QCheckBox(".scriptreering (rings)")
        self._cb_tree = QCheckBox(".scriptreetree (trees)")
        self._cb_tool = QCheckBox(".scriptree (single tools)")
        self._cb_ring.setChecked("ring" in included)
        self._cb_tree.setChecked("tree" in included)
        self._cb_tool.setChecked("tool" in included)
        layout.addWidget(self._cb_ring)
        layout.addWidget(self._cb_tree)
        layout.addWidget(self._cb_tool)
        layout.addStretch(1)

    def values(self) -> list[str]:
        out: list[str] = []
        if self._cb_ring.isChecked():
            out.append("ring")
        if self._cb_tree.isChecked():
            out.append("tree")
        if self._cb_tool.isChecked():
            out.append("tool")
        return out


__all__ = [
    "IncludeKindsChecklist",
    "RootsEditor",
    "UpdateModeChoice",
]
