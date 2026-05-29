"""Qt dialogs for the ``.scriptreetree`` auto-discover feature.

## For humans

Three dialogs, each one parallel to a forest counterpart:

* ``TreeUpdateDiffDialog`` — three-section checklist (Add /
  Remove / Previously excluded) shown after a discovery pass.
  User ticks items they want and hits Apply.  Parallel to
  ``scriptree.shell.forest_dialogs.UpdateDiffDialog``.
* ``TreeSettingsDialog`` — edit the per-tree ``auto_discover``
  block: ``enabled`` toggle, ``roots`` editor, sibling-tree
  toggle, and ``update_mode`` radio.  Plus a "Save && Run
  discovery" button so the user can re-scan immediately.
  Parallel to
  ``scriptree.shell.forest_dialogs.ForestSettingsDialog``.
* ``ChooseUpdateModeDialog`` — one-shot dialog fired on FIRST
  load of any ``.scriptreetree`` that has no ``auto_discover``
  block.  Asks the user which mode to use going forward.  The
  user's choice persists by writing an ``auto_discover`` block
  to the tree, so this dialog only fires once per tree.

## For maintainers / LLMs

* This module is in ``scriptree.ui`` because it imports
  PySide6 widgets.  The dialogs accept a ``controller`` of
  duck-typed shape:

      class _Controller(Protocol):
          tree: TreeDef
          tree_file: str
          parent_widget: QWidget | None  # for modal parenting
          def save(self) -> None: ...
          def apply_diff(self, diff, *, accepted_added,
                         accepted_removed, accepted_reincluded) -> None: ...
          def refresh_from_sources(self) -> None: ...

  The Phase-6 ``TreeController`` implements this; tests can
  substitute a fake.

* Two widget classes (``_RootsEditor``, ``_UpdateModeChoice``)
  are imported directly from ``scriptree.shell.forest_dialogs``.
  That's a short-term reach across module boundaries; long-term
  these widgets belong in a shared ``ui.discovery_widgets``
  module that both forest and tree dialogs import from.  The
  reach is acceptable now because the widgets have stable
  internal APIs (``.values()`` / ``.value()``) and the layering
  is one-directional (tree dialog → forest widgets, not the
  reverse).
* Tests for the dialogs go through their public API
  (``__init__`` plus the slot the Apply button is wired to)
  rather than simulating Qt events.  See
  ``tests/test_tree_dialogs.py`` for the pattern.

## The dialog UX, decision by decision

The diff dialog uses three ``QGroupBox`` sections instead of a
single combined ``QTreeWidget`` because:

* Added / Removed / Previously-excluded carry distinct
  semantics; visual separation reinforces that.
* Default-check state differs by section (Added: checked,
  Previously-excluded: unchecked).  Putting them in one tree
  with a single header would hide that distinction.
* The forest already shipped this layout and users are
  acclimated.  Parity wins.

The settings dialog uses ``Save`` + ``Save && Run discovery`` +
``Cancel`` (three buttons), again matching the forest.  The
"Save && Run discovery" path immediately fires
``controller.refresh_from_sources()`` after persisting so the
user can flip a setting and see the effect in one step.

The first-load chooser shows three radio options in plain
language with brief descriptions, plus a default selection of
"Prompt" (the safest middle-ground).  No "Cancel" — the user
MUST pick something so the tree gets a stored ``auto_discover``
block.  Clicking the dialog's close button is treated as
"Prompt" (the default) so an accidental close doesn't strand
the tree in the "never asked" state forever.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.discovery import TreeAutoDiscoverConfig
from ..core.tree_diff import TreeDiscoveryDiff
from ..core.tree_discover import DiscoveredTreeItem
from .discovery_widgets import RootsEditor, UpdateModeChoice


# ---------------------------------------------------------------------------
# Controller protocol — what the dialogs expect from their owner.
# ---------------------------------------------------------------------------

class _TreeController(Protocol):
    """Duck-typed interface the dialogs call back into.

    The Phase-6 ``TreeController`` implements this; tests
    substitute a fake.  Kept narrow on purpose: every method
    the dialogs touch is here, nothing else.
    """

    tree: Any  # TreeDef — imported lazily to avoid core/ui cycle
    tree_file: str
    parent_widget: QWidget | None

    def save(self) -> None: ...
    def apply_diff(
        self,
        diff: TreeDiscoveryDiff,
        *,
        accepted_added: Iterable[DiscoveredTreeItem],
        accepted_removed: Iterable[Any],  # TreeNode
        accepted_reincluded: Iterable[DiscoveredTreeItem],
    ) -> None: ...
    def refresh_from_sources(self) -> None: ...


# ---------------------------------------------------------------------------
# TreeUpdateDiffDialog
# ---------------------------------------------------------------------------

class TreeUpdateDiffDialog(QDialog):
    """Diff prompt for a tree discovery pass.

    Shown after the user (or the auto-load path) triggers a
    scan that produced at least one non-empty bucket.  Three
    sections, each a ``QTreeWidget`` of checkable rows:

    * **Add to tree** — newly-found candidates.  Default
      checked.  On Apply, the checked rows are inserted into
      the ``TreeDef.nodes`` at the right folder depth.
    * **Remove from tree — file no longer on disk** — leaves
      pointing at vanished files.  Default checked (a leaf
      whose file is gone is almost certainly meant to be
      dropped).
    * **Previously excluded — found again in sources** —
      candidates whose path is in ``tree.excluded``.  Default
      UNCHECKED; the user previously said "stop suggesting
      this" and we don't want to undo that silently.

    Apply path filters each section's checked-rows-only and
    hands them to ``controller.apply_diff``.  Cancel discards
    the diff entirely.

    The sibling-tree distinction (a ``.scriptreetree``
    candidate vs a ``.scriptree`` candidate) is shown via the
    ``[tool]`` / ``[sibling_tree]`` tag prefix on the row's
    label.  Same dialog, same rules — the apply step treats
    them identically (both insert as leaves).
    """

    def __init__(
        self,
        controller: _TreeController,
        diff: TreeDiscoveryDiff,
    ) -> None:
        super().__init__(controller.parent_widget)
        self._controller = controller
        self._diff = diff

        self.setWindowTitle("Tree changes detected")
        self.setMinimumWidth(720)
        self.setMinimumHeight(540)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "<b>I found some changes for this tree.</b><br>"
            "Tick the items you want to apply.  Untick anything "
            "you'd rather leave out — the tree won't change for "
            "those."
        ))

        # Scrollable inner container so a giant diff doesn't blow
        # the dialog past the screen.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)

        # Tracked per-row state for the Apply path.
        self._added_rows: list[
            tuple[QTreeWidgetItem, DiscoveredTreeItem]
        ] = []
        self._removed_rows: list[
            tuple[QTreeWidgetItem, Any]  # TreeNode
        ] = []
        self._reincl_rows: list[
            tuple[QTreeWidgetItem, DiscoveredTreeItem]
        ] = []

        if diff.added:
            inner_layout.addWidget(
                self._build_added_section(diff.added)
            )

        if diff.removed:
            inner_layout.addWidget(
                self._build_removed_section(diff.removed)
            )

        if diff.previously_excluded:
            inner_layout.addWidget(
                self._build_reincl_section(diff.previously_excluded)
            )

        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, stretch=1)

        # Buttons: Apply (primary) + Cancel.
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        apply_btn = btn_box.button(QDialogButtonBox.StandardButton.Apply)
        apply_btn.setDefault(True)
        layout.addWidget(btn_box)
        btn_box.rejected.connect(self.reject)
        apply_btn.clicked.connect(self._apply)

    # --- section builders -------------------------------------------------

    def _build_added_section(
        self, items: list[DiscoveredTreeItem],
    ) -> QGroupBox:
        box = QGroupBox(f"Add to tree ({len(items)})")
        bl = QVBoxLayout(box)
        tw = QTreeWidget()
        tw.setHeaderLabels(["Item", "Relative path"])
        tw.setColumnCount(2)
        tw.setColumnWidth(0, 320)
        tw.setMinimumHeight(120)
        for it in items:
            label = f"[{it.kind}] {Path(it.abs_path).name}"
            row = QTreeWidgetItem(tw, [label, it.rel_path])
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(0, Qt.CheckState.Checked)
            self._added_rows.append((row, it))
        bl.addWidget(tw)
        return box

    def _build_removed_section(
        self, items: list[Any],  # TreeNode
    ) -> QGroupBox:
        box = QGroupBox(
            f"Remove from tree — file no longer on disk "
            f"({len(items)})"
        )
        bl = QVBoxLayout(box)
        tw = QTreeWidget()
        tw.setHeaderLabels(["Leaf", "Tree path"])
        tw.setColumnCount(2)
        tw.setColumnWidth(0, 320)
        tw.setMinimumHeight(80)
        for node in items:
            label = node.display_name or Path(node.path or "").name or "(leaf)"
            row = QTreeWidgetItem(tw, [label, node.path or ""])
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(0, Qt.CheckState.Checked)
            self._removed_rows.append((row, node))
        bl.addWidget(tw)
        return box

    def _build_reincl_section(
        self, items: list[DiscoveredTreeItem],
    ) -> QGroupBox:
        box = QGroupBox(
            f"Previously excluded — found again "
            f"({len(items)})"
        )
        bl = QVBoxLayout(box)
        bl.addWidget(QLabel(
            "<i>You removed these before.  Tick to bring them "
            "back; leave unticked to keep them excluded.</i>"
        ))
        tw = QTreeWidget()
        tw.setHeaderLabels(["Item", "Relative path"])
        tw.setColumnCount(2)
        tw.setColumnWidth(0, 320)
        tw.setMinimumHeight(100)
        for it in items:
            label = f"[{it.kind}] {Path(it.abs_path).name}"
            row = QTreeWidgetItem(tw, [label, it.rel_path])
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(0, Qt.CheckState.Unchecked)
            self._reincl_rows.append((row, it))
        bl.addWidget(tw)
        return box

    # --- apply path -------------------------------------------------------

    @staticmethod
    def _is_checked(row: QTreeWidgetItem) -> bool:
        return row.checkState(0) == Qt.CheckState.Checked

    def _apply(self) -> None:
        """Filter checked rows from each section and hand them
        to the controller.  Always calls ``save()`` after a
        successful apply so the on-disk file reflects the new
        state immediately (matches forest behaviour)."""
        added = [it for row, it in self._added_rows if self._is_checked(row)]
        removed = [n for row, n in self._removed_rows if self._is_checked(row)]
        reincl = [it for row, it in self._reincl_rows if self._is_checked(row)]
        self._controller.apply_diff(
            self._diff,
            accepted_added=added,
            accepted_removed=removed,
            accepted_reincluded=reincl,
        )
        self._controller.save()
        self.accept()


# ---------------------------------------------------------------------------
# TreeSettingsDialog
# ---------------------------------------------------------------------------

class _IncludeSiblingTreesCheckbox(QWidget):
    """Single checkbox: "Include sibling .scriptreetree files as
    candidate sub-tree leaves".

    Parallel to forest's ``_IncludeChecklist`` but vastly
    simpler — trees have no kind-filter (it's always
    ``.scriptree`` files plus optionally sibling trees).
    """

    def __init__(self, value: bool) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._cb = QCheckBox(
            "Surface sibling .scriptreetree files as candidate "
            "sub-tree leaves"
        )
        self._cb.setToolTip(
            "When checked, another .scriptreetree found during the "
            "scan is offered as a candidate to nest as a sub-tree "
            "leaf in this tree.  When unchecked, sibling trees are "
            "still respected as boundaries (their subdirs are "
            "skipped) but the file itself is not surfaced."
        )
        self._cb.setChecked(value)
        layout.addWidget(self._cb)

    def value(self) -> bool:
        return self._cb.isChecked()


class TreeSettingsDialog(QDialog):
    """Edit a tree's ``auto_discover`` block.

    Shows four field-group widgets in vertical stack:

    1. **Enabled** — master kill switch (``enabled`` field).
    2. **Scan folders** — list-with-add/remove of root paths
       (``roots`` field).  Reused ``_RootsEditor`` from
       forest_dialogs.
    3. **Include sibling trees** — checkbox toggle
       (``include_sibling_trees`` field).
    4. **Update mode** — three radio buttons (``update_mode``
       field).  Reused ``_UpdateModeChoice`` from forest_dialogs.

    Three buttons at the bottom: Save / Save && Run discovery /
    Cancel.  The "Save && Run discovery" button persists the
    settings then calls
    ``controller.refresh_from_sources()`` on the next event tick
    (so the diff dialog, if any, doesn't try to parent itself
    to this freshly-closed window).
    """

    def __init__(self, controller: _TreeController) -> None:
        super().__init__(controller.parent_widget)
        self._controller = controller

        # Lazy import for type — TreeDef is in core, this file is
        # in ui, and the controller's tree attribute is opaquely-
        # typed in the protocol.  Read defensively.
        tree = controller.tree
        ad = tree.auto_discover or TreeAutoDiscoverConfig()

        self.setWindowTitle(f"Tree settings — {tree.name}")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "<b>Auto-discover for this tree</b><br>"
            "These settings control how ScripTree keeps the tree "
            "in sync with the underlying folder of "
            ".scriptree files."
        ))

        # --- enabled toggle ------------------------------------------
        self._enabled_cb = QCheckBox(
            "Enable auto-discovery (run on load and on Refresh)"
        )
        self._enabled_cb.setToolTip(
            "When off, the walker is never invoked and the "
            "'Refresh from sources' menu entry is disabled.  "
            "Long-term 'this tree is frozen' toggle."
        )
        self._enabled_cb.setChecked(ad.enabled)
        layout.addWidget(self._enabled_cb)

        # --- scan folders --------------------------------------------
        roots_box = QGroupBox("Scan folders")
        rl = QVBoxLayout(roots_box)
        # v0.8.0a21 -- shared widget from ``ui.discovery_widgets``.
        # Used to import ``_RootsEditor`` from ``shell.forest_dialogs``;
        # promoted to the shared module so both forest and tree dialogs
        # import from the same canonical place.
        self._roots = RootsEditor(list(ad.roots))
        rl.addWidget(self._roots)
        rl.addWidget(QLabel(
            "<i>Folders to scan, relative to this tree's directory "
            "(or absolute).  Default is just '.' — this tree's own "
            "folder, walked recursively.</i>"
        ))
        layout.addWidget(roots_box)

        # --- include sibling trees -----------------------------------
        sib_box = QGroupBox("Sibling trees")
        sl = QVBoxLayout(sib_box)
        self._sib = _IncludeSiblingTreesCheckbox(ad.include_sibling_trees)
        sl.addWidget(self._sib)
        layout.addWidget(sib_box)

        # --- update mode ---------------------------------------------
        mode_box = QGroupBox("Update mode")
        ml = QVBoxLayout(mode_box)
        # Shared widget; see RootsEditor comment above.
        self._mode = UpdateModeChoice(ad.update_mode)
        ml.addWidget(self._mode)
        layout.addWidget(mode_box)

        # --- buttons -------------------------------------------------
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._btn_run = QPushButton("Save && Run discovery")
        self._btn_run.setToolTip(
            "Save these settings, then immediately scan and apply "
            "per the chosen update mode."
        )
        btn_box.addButton(
            self._btn_run, QDialogButtonBox.ButtonRole.ActionRole,
        )
        layout.addWidget(btn_box)
        btn_box.rejected.connect(self.reject)
        btn_box.accepted.connect(self._save)
        self._btn_run.clicked.connect(self._save_and_run)

    # --- save paths -------------------------------------------------------

    def _harvest_into_config(self) -> TreeAutoDiscoverConfig:
        """Read every widget and assemble a fresh config object."""
        return TreeAutoDiscoverConfig(
            enabled=self._enabled_cb.isChecked(),
            roots=list(self._roots.values()),
            include_sibling_trees=self._sib.value(),
            update_mode=self._mode.value(),  # type: ignore[arg-type]
        )

    def _save(self) -> None:
        self._controller.tree.auto_discover = self._harvest_into_config()
        self._controller.save()
        self.accept()

    def _save_and_run(self) -> None:
        self._save()
        # Fire on next event tick so the (possibly modal) diff
        # dialog doesn't parent itself to this freshly-closed
        # window.  Matches forest behaviour.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._controller.refresh_from_sources)


# ---------------------------------------------------------------------------
# ChooseUpdateModeDialog — one-shot first-load chooser.
# ---------------------------------------------------------------------------

class ChooseUpdateModeDialog(QDialog):
    """One-shot dialog asking the user to pick an update mode.

    Fires from ``TreeController.start`` (or equivalent) when
    ``tree.auto_discover is None`` — the runtime distinguishes
    "never asked" (``None``) from "asked and chose" (a non-None
    config, even default-valued).  After the user picks here,
    the controller writes a ``TreeAutoDiscoverConfig`` with the
    chosen ``update_mode`` and persists, so the next load no
    longer triggers this dialog.

    UX choices:

    * Three radio options: ``prompt`` (default), ``auto``,
      ``off``.  Each shown in plain language with a short
      tooltip-equivalent description.
    * The dialog window's close button is treated the same as
      clicking the default selection (``prompt``) so an
      accidental close doesn't strand the tree in the
      "never asked" state forever.
    * No "Cancel" button.  Picking SOMETHING is the whole
      point.
    * Title mentions the tree's name so the user knows which
      tree they're configuring — relevant when several trees
      are loaded in sequence.

    Result is exposed via the ``chosen`` property after
    ``exec()`` returns.  Default value (if the dialog is
    dismissed before any radio click) is ``"prompt"``.
    """

    def __init__(
        self,
        tree_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._chosen: str = "prompt"  # fallback for "closed without choosing"

        self.setWindowTitle(f"Set up auto-discovery — {tree_name}")
        self.setMinimumWidth(540)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"<b>How should ScripTree keep '{tree_name}' in sync "
            f"with new .scriptree files in its folder?</b>"
        ))
        layout.addWidget(QLabel(
            "<i>You can change this any time from the tree's "
            "right-click menu → Tree settings…</i>"
        ))

        self._rb_prompt = QRadioButton(
            "Prompt — show me what changed and let me confirm "
            "(recommended)"
        )
        self._rb_prompt.setToolTip(
            "On load and on manual refresh, scan the tree's folder. "
            "If anything new was found, pop a dialog so I can pick "
            "what to add."
        )
        self._rb_auto = QRadioButton(
            "Auto — silently add anything new"
        )
        self._rb_auto.setToolTip(
            "On load and on manual refresh, scan and add every "
            "newly-found tool without asking.  Use when the on-disk "
            "folder IS the source of truth and the tree is just a "
            "view of it."
        )
        self._rb_off = QRadioButton(
            "Off — never scan automatically (I'll manage the tree "
            "myself)"
        )
        self._rb_off.setToolTip(
            "Skip the scan entirely.  The 'Refresh from sources' "
            "menu entry still works as a one-shot prompt."
        )
        self._rb_prompt.setChecked(True)

        layout.addWidget(self._rb_prompt)
        layout.addWidget(self._rb_auto)
        layout.addWidget(self._rb_off)

        # No "Cancel" — the user must pick.
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
        )
        ok_btn = btn_box.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("Continue")
        ok_btn.setDefault(True)
        layout.addWidget(btn_box)
        btn_box.accepted.connect(self._on_ok)

    def _on_ok(self) -> None:
        if self._rb_off.isChecked():
            self._chosen = "off"
        elif self._rb_auto.isChecked():
            self._chosen = "auto"
        else:
            self._chosen = "prompt"
        self.accept()

    @property
    def chosen(self) -> str:
        """The mode the user picked.  Always one of ``"off" |
        ``"auto"`` | ``"prompt"``.  Defaults to ``"prompt"`` if
        the dialog was dismissed without an explicit Ok click."""
        return self._chosen


__all__ = [
    "ChooseUpdateModeDialog",
    "TreeSettingsDialog",
    "TreeUpdateDiffDialog",
]
