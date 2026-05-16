"""
forest_dialogs.py — Qt dialogs for the forest layer.

## For humans

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

## For maintainers / LLMs

- Every dialog parents to ``controller.forest_window`` and calls
  controller methods directly (no signals). Construct → ``.exec()``.
  ``FirstRunDialog._apply`` and ``ForestSettingsDialog._save_and_run``
  both ``accept()`` THEN fire the next step on a 0 ms
  ``QTimer.singleShot`` — the deferral is REQUIRED so the follow-up
  dialog doesn't parent to a window mid-close. Don't make these
  synchronous.
- Only TOP-LEVEL rows in the discovery tree are checkable
  (``ItemIsUserCheckable``). Child rows from ``_populate_children`` /
  ``_populate_tree_nodes`` are display-only structure and MUST NOT
  influence the apply step — ``UpdateDiffDialog._apply`` only scans
  ``_added_rows`` / ``_removed_rows`` / ``_reincl_rows`` (the top-level
  pair lists), never descendants.
- ``_populate_children`` recursion is best-effort with a broad
  ``except Exception``: a malformed catalog drops a "(unable to peer
  inside)" marker row and stops recursion at that node. This swallow is
  intentional (dialog must stay interactive with half-broken catalogs)
  — but it also hides genuine load bugs; check the ``[forest_dialogs]``
  stderr log when a subtree mysteriously won't expand. ``max_depth=4``
  caps recursion.
- Ring children are read by parsing the ``.scriptreering`` JSON
  ``members[].catalog_path`` directly (relative paths resolved against
  the ring's dir); tree children go through ``core.io.load_tree``. Child
  ``kind`` is inferred purely by ``.scriptreetree`` suffix → "tree"
  else "tool" — a ``.scriptreering`` referenced as a member would be
  mislabelled "tool" here (display-only, low impact).
- ``ForestSettingsDialog._save`` swallows ``apply_label_change``
  failures (``except Exception: pass``) and catches only ``OSError``
  from ``update_preferences`` — a non-OSError prefs failure WILL
  propagate out of the dialog. Forest ``save()`` is always called last
  so in-memory state still persists even if prefs write failed.
- ``ExcludedItemsDialog`` per-row lambdas bind ``p=path`` as a default
  arg (correct late-binding fix — don't "simplify" to a closure over
  the loop var). Both ``_reinclude`` and ``_forget`` call
  ``self.accept()`` to close immediately — the dialog is single-action;
  reopen for more. ``_forget`` filters ``excluded`` by exact-string
  ``!= path`` (NOT normalised) — must match how the path was stored.
- ``_RootsEditor`` returns raw widget text verbatim; relative/absolute
  resolution is the discovery layer's job, not the dialog's.
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
    QTreeWidget,
    QTreeWidgetItem,
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
# Tree-view builder — peers DiscoveredItems into their child contents
# so the checklist shows ``ring → tree → tool`` hierarchy.
# ---------------------------------------------------------------------------

def _populate_children(
    parent_widget_item: QTreeWidgetItem,
    item_path: str,
    item_kind: str,
    *,
    depth: int = 0,
    max_depth: int = 4,
) -> None:
    """Recursively populate read-only child rows under
    ``parent_widget_item`` describing what's inside the given
    ``ring`` / ``tree`` / ``tool`` file.

    Children are display-only — they have no checkbox, can't be
    toggled, and don't affect the apply step.  Their job is to let
    the user see "this ring contains rings X and Y, and ring X
    contains tools A and B".

    Loading the inner files is best-effort: a malformed catalog
    just stops the recursion at that node with a small marker
    label.  We never raise from here — the dialog must remain
    interactive even when the user has half-broken catalogs in
    their tree.
    """
    if depth >= max_depth:
        return
    p = Path(item_path)
    if not p.is_file():
        return
    try:
        if item_kind == "ring":
            # .scriptreering — read its referenced cells.
            import json
            data = json.loads(p.read_text(encoding="utf-8"))
            members = data.get("members") or []
            for m in members:
                child_catalog = m.get("catalog_path")
                if not child_catalog:
                    continue
                # Resolve relative paths against the ring's directory.
                child_path = Path(child_catalog)
                if not child_path.is_absolute():
                    child_path = (p.parent / child_path).resolve()
                child_kind = (
                    "tree" if str(child_path).lower().endswith(".scriptreetree")
                    else "tool"
                )
                row = QTreeWidgetItem(parent_widget_item, [
                    f"[{child_kind}] {child_path.name}",
                    str(child_path),
                ])
                row.setFirstColumnSpanned(False)
                _populate_children(
                    row, str(child_path), child_kind,
                    depth=depth + 1, max_depth=max_depth,
                )
        elif item_kind == "tree":
            # .scriptreetree — recurse into its TreeNode hierarchy.
            from scriptree.core.io import load_tree
            tree_def = load_tree(p)
            _populate_tree_nodes(
                parent_widget_item, tree_def.nodes, p.parent,
                depth=depth + 1, max_depth=max_depth,
            )
        # Tools have no children — leaf of the hierarchy.
    except Exception as exc:  # noqa: BLE001
        # Display a small marker so the user knows we tried.
        QTreeWidgetItem(parent_widget_item, [
            "(unable to peer inside — see log)",
            f"{exc!r}",
        ])
        _log(f"_populate_children({item_path!r}, {item_kind!r}): {exc!r}")


def _populate_tree_nodes(
    parent_widget_item: QTreeWidgetItem,
    nodes: list,
    base_dir: Path,
    *,
    depth: int,
    max_depth: int,
) -> None:
    """Render ``TreeNode``s as read-only widget rows under
    ``parent_widget_item``.  Recurses into folders and dives into
    leaf trees/tools via ``_populate_children``."""
    if depth >= max_depth:
        return
    for node in nodes:
        ntype = getattr(node, "type", None)
        if ntype == "folder":
            label = getattr(node, "name", "") or "(folder)"
            row = QTreeWidgetItem(parent_widget_item, [
                f"[folder] {label}",
                "",
            ])
            _populate_tree_nodes(
                row, getattr(node, "children", []), base_dir,
                depth=depth + 1, max_depth=max_depth,
            )
        elif ntype == "leaf":
            leaf_path = getattr(node, "path", "")
            if not leaf_path:
                continue
            lp = Path(leaf_path)
            if not lp.is_absolute():
                lp = (base_dir / lp).resolve()
            leaf_kind = (
                "tree" if str(lp).lower().endswith(".scriptreetree")
                else "tool"
            )
            row = QTreeWidgetItem(parent_widget_item, [
                f"[{leaf_kind}] {lp.name}",
                str(lp),
            ])
            _populate_children(
                row, str(lp), leaf_kind,
                depth=depth + 1, max_depth=max_depth,
            )


def _build_discovery_tree(
    items: list,
    *,
    initial_checked: bool = True,
) -> tuple[QTreeWidget, list[tuple[QTreeWidgetItem, "DiscoveredItem"]]]:
    """Build a ``QTreeWidget`` with one top-level checkable row per
    discovered item, plus read-only children showing what's inside.

    Returns ``(tree, rows)`` where ``rows`` is a list of
    ``(QTreeWidgetItem, DiscoveredItem)`` pairs the dialog can scan
    when applying — each top-level row's check-state controls
    inclusion of the corresponding item.
    """
    tree = QTreeWidget()
    tree.setHeaderLabels(["Item", "Path"])
    tree.setColumnCount(2)
    tree.setRootIsDecorated(True)
    tree.setUniformRowHeights(False)
    tree.setColumnWidth(0, 320)

    rows: list[tuple[QTreeWidgetItem, "DiscoveredItem"]] = []
    for item in items:
        p = Path(item.path)
        top = QTreeWidgetItem(tree, [
            f"[{item.kind}] {p.name}",
            str(p),
        ])
        top.setFlags(top.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        top.setCheckState(
            0,
            Qt.CheckState.Checked if initial_checked
            else Qt.CheckState.Unchecked,
        )
        _populate_children(top, item.path, item.kind)
        rows.append((top, item))
    return tree, rows


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

        # v0.3.16: hand off to the tree-view UpdateDiffDialog so the
        # user can see the ring → tree → tool hierarchy and tick /
        # untick individual items before applying.  Pre-fix this
        # dialog applied everything unconditionally; the tree view
        # gives users useful agency on first-run.
        self.accept()
        # Run on next tick so this dialog has finished closing
        # before the tree-view dialog parents to forest_window.
        from PySide6.QtCore import QTimer

        def _open_diff() -> None:
            self._controller._show_diff_dialog(diff)

        QTimer.singleShot(0, _open_diff)


# ---------------------------------------------------------------------------
# UpdateDiffDialog
# ---------------------------------------------------------------------------

class UpdateDiffDialog(QDialog):
    """Diff prompt — tree-view checklist with three sections.

    v0.3.16: rewrote to use ``QTreeWidget`` so users can see the
    ring → tree → tool hierarchy at a glance.  The user's request
    was direct: "is it possible to have the checklist that comes
    up with the apps to select as a tree view? That way we can see
    what scriptrees are included in what scriptreetrees are
    included in what rings."

    Top-level rows are checkable (apply/skip toggle); nested rows
    are read-only and exist purely to make the hierarchy visible.
    """

    def __init__(
        self,
        controller: "ForestController",
        diff: DiscoveryDiff,
    ) -> None:
        super().__init__(controller.forest_window)
        self._controller = controller
        self._diff = diff
        self.setWindowTitle("Forest changes detected")
        self.setMinimumWidth(720)
        self.setMinimumHeight(560)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "<b>I found some changes.</b><br>"
            "Tick the top-level items you want to apply.  Expand a "
            "row to see what's inside (read-only — child rows just "
            "show structure)."
        ))

        # Three sections.  Each section renders as a QTreeWidget
        # so children are visible.  Wrapped in a scroll area to
        # handle large diffs without growing the dialog absurdly.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)

        self._added_tree: QTreeWidget | None = None
        self._added_rows: list[tuple[QTreeWidgetItem, DiscoveredItem]] = []
        self._removed_tree: QTreeWidget | None = None
        self._removed_rows: list[tuple[QTreeWidgetItem, str]] = []
        self._reincl_tree: QTreeWidget | None = None
        self._reincl_rows: list[tuple[QTreeWidgetItem, DiscoveredItem]] = []

        if diff.added:
            box = QGroupBox(f"Add to forest ({len(diff.added)})")
            bl = QVBoxLayout(box)
            self._added_tree, self._added_rows = _build_discovery_tree(
                diff.added, initial_checked=True,
            )
            self._added_tree.setMinimumHeight(120)
            bl.addWidget(self._added_tree)
            inner_layout.addWidget(box)

        if diff.removed:
            box = QGroupBox(
                f"Remove from forest — file no longer on disk "
                f"({len(diff.removed)})"
            )
            bl = QVBoxLayout(box)
            removed_tree = QTreeWidget()
            removed_tree.setHeaderLabels(["Item", "Path"])
            removed_tree.setColumnCount(2)
            removed_tree.setColumnWidth(0, 320)
            removed_tree.setMinimumHeight(80)
            for item in diff.removed:
                p = Path(item.path)
                row = QTreeWidgetItem(removed_tree, [
                    f"[{item.kind}] {p.name}",
                    str(p),
                ])
                row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                row.setCheckState(0, Qt.CheckState.Checked)
                self._removed_rows.append((row, item.path))
            bl.addWidget(removed_tree)
            self._removed_tree = removed_tree
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
            self._reincl_tree, self._reincl_rows = _build_discovery_tree(
                diff.previously_excluded, initial_checked=False,
            )
            self._reincl_tree.setMinimumHeight(120)
            bl.addWidget(self._reincl_tree)
            inner_layout.addWidget(box)

        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, stretch=1)

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

    @staticmethod
    def _is_checked(row: QTreeWidgetItem) -> bool:
        return row.checkState(0) == Qt.CheckState.Checked

    def _apply(self) -> None:
        accepted_added = {
            it.path for row, it in self._added_rows
            if self._is_checked(row)
        }
        accepted_removed = {
            p for row, p in self._removed_rows
            if self._is_checked(row)
        }
        accepted_reincl = {
            it.path for row, it in self._reincl_rows
            if self._is_checked(row)
        }
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

        # ── Launch preferences (v0.3.21+) ─────────────────────────
        # Persistent across forests — controls what the launcher
        # does when nothing is specified on the command line.  These
        # apply at the NEXT launch, not the current session.
        prefs_box = QGroupBox("Launch defaults (applies on next launch)")
        pl = QVBoxLayout(prefs_box)
        prefs = controller.get_preferences()
        self._prefs_fallback_cb = QCheckBox(
            "Load this default forest when no file is specified"
        )
        self._prefs_fallback_cb.setToolTip(
            "When checked, launching the forest with no command-line "
            "argument loads the default forest file below (creating "
            "it empty if missing).  When unchecked, the forest starts "
            "with a transient in-memory workspace — nothing is "
            "auto-saved until you explicitly Save as…"
        )
        self._prefs_fallback_cb.setChecked(prefs.fallback_to_default)
        pl.addWidget(self._prefs_fallback_cb)
        prefs_path_row = QHBoxLayout()
        prefs_path_row.addWidget(QLabel("Default forest file:"))
        self._prefs_path_edit = QLineEdit(prefs.default_forest_path)
        self._prefs_path_edit.setPlaceholderText(
            "(empty = canonical autoload path)"
        )
        prefs_path_row.addWidget(self._prefs_path_edit, stretch=1)
        self._prefs_path_browse = QPushButton("Browse…")
        prefs_path_row.addWidget(self._prefs_path_browse)
        pl.addLayout(prefs_path_row)
        layout.addWidget(prefs_box)

        # Wire enable/disable: path edit + browse are only relevant
        # when the fallback checkbox is on.
        def _sync_prefs_enable():
            on = self._prefs_fallback_cb.isChecked()
            self._prefs_path_edit.setEnabled(on)
            self._prefs_path_browse.setEnabled(on)
        _sync_prefs_enable()
        self._prefs_fallback_cb.toggled.connect(lambda _checked: _sync_prefs_enable())

        def _browse_default_path():
            current = self._prefs_path_edit.text().strip()
            target, _ = QFileDialog.getSaveFileName(
                self,
                "Default forest file",
                current,
                "ScripTree forest (*.scriptreeforest)",
            )
            if target:
                self._prefs_path_edit.setText(target)
        self._prefs_path_browse.clicked.connect(_browse_default_path)

        # Three buttons: Save (just save), Run (save + run discovery
        # immediately), Cancel.  Run is what the user asked for —
        # so the settings dialog can also kick off a discovery pass
        # without making them right-click → Refresh after closing.
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._btn_run = QPushButton("Save && Run discovery")
        self._btn_run.setToolTip(
            "Save these settings, then immediately scan the configured "
            "folders and apply per the chosen update mode."
        )
        btn_box.addButton(
            self._btn_run, QDialogButtonBox.ButtonRole.ActionRole,
        )
        layout.addWidget(btn_box)
        btn_box.rejected.connect(self.reject)
        btn_box.accepted.connect(self._save)
        self._btn_run.clicked.connect(self._save_and_run)

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
        # Persist launch preferences (v0.3.21+).  These don't change
        # the currently-loaded forest; they apply at the next launch.
        from scriptree.shell.forest_io import ForestPreferences
        new_prefs = ForestPreferences(
            fallback_to_default=self._prefs_fallback_cb.isChecked(),
            default_forest_path=self._prefs_path_edit.text().strip(),
        )
        try:
            self._controller.update_preferences(new_prefs)
        except OSError as exc:
            # Disk write of prefs failed (read-only home dir?).
            # Don't crash the dialog — the forest save below still
            # works for the in-memory state.
            from scriptree.shell.forest_controller import _log
            _log(f"_save: update_preferences failed: {exc!r}")
        self._controller.save()
        self.accept()

    def _save_and_run(self) -> None:
        """Apply settings then immediately run discovery — same as
        Save followed by right-click → Refresh, but in one step.
        Honours the chosen update_mode (auto applies silently,
        prompt opens the diff dialog).
        """
        self._save()
        # ``_save`` calls ``self.accept()`` which closes us — fire
        # the discovery on the next event tick so the diff dialog
        # (if any) doesn't try to parent itself to a freshly-closed
        # window.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._controller.refresh_from_sources)


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
