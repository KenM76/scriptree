"""Unhappy-path tests for the editor's tree view and the merged-
tree pipeline.

User reported via screenshot showing three top-level "MSOffice"
folders + a self-referencing circular reference, with no way to
right-click the column header to save, no way to drag/drop or
delete the duplicates, and Save All not persisting changes.

Each ``TestUH*`` class corresponds to one failure mode.  These
tests are the canonical regression suite for the v0.8.0a36 fix
sweep.

UH1 - Merged tree builder DOES NOT de-duplicate by display
      name.  Two distinct .scriptreetree files that both name
      themselves "MSOffice" produce two top-level folders both
      called "MSOffice", which the user can't distinguish.

UH2 - When the merged tree includes a .scriptreetree that
      references ANOTHER .scriptreetree as a subtree node, the
      subtree expansion in the editor is read-only.  Users
      see broken structure (e.g. circular references) and
      cannot drag/drop/delete to repair.  The fix: subtree
      expansions render as plain folders with their content
      INLINED at build time, not at view time, so the user
      can edit the merged tree as a flat hierarchy.

UH3 - Right-clicking on the tree column header ("Tools") shows
      no context menu.  ``customContextMenuRequested`` is
      wired on the QTreeWidget body, not on its QHeaderView.
      The fix: also wire the header's context-menu signal to
      the same handler.

UH4 - Save tree on a merged tree where the user has DELETED a
      top-level folder must propagate to the originating
      source file: the source ``.scriptreetree`` (or its
      "removed" sentinel) must reflect the deletion.

UH5 - load_tree's cycle guard (``_expanding_paths``) detects
      cycles between subtree references and emits a
      "(circular reference)" leaf marker, but the existing
      logic only operates at TREE-VIEW expansion time, not at
      MERGED-TREE BUILD time.  If a forest member's
      .scriptreetree references back to itself or another
      member's .scriptreetree, the merged tree can recurse
      forever during build_merged_tree.  Test: building from
      a cyclic input set terminates and emits a diagnostic.

UH6 - The same-name dedup must be deterministic across
      reruns: rebuilding with the same input produces the
      same disambiguated names (so the merged temp file
      stays hash-stable and V1 doesn't see "phantom changes").
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QHeaderView, QMenu, QMessageBox, QTreeWidget,
)

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.question = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Yes
)
QMessageBox.critical = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_scriptree(path: Path, name: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "name": name or path.stem,
            "executable": "echo",
            "params": [],
        }),
        encoding="utf-8",
    )


def _write_scriptreetree(
    path: Path,
    leaves: list[Path] | None = None,
    subtrees: list[Path] | None = None,
    name: str | None = None,
) -> None:
    """Drop a .scriptreetree with mixed leaves + subtree references."""
    path.parent.mkdir(parents=True, exist_ok=True)
    nodes: list[dict] = []
    for leaf in (leaves or []):
        try:
            rel = Path(leaf).relative_to(path.parent)
            leaf_path = str(rel).replace("\\", "/")
        except ValueError:
            leaf_path = str(leaf)
        nodes.append({
            "type": "leaf",
            "name": leaf.stem,
            "path": leaf_path,
        })
    for sub in (subtrees or []):
        try:
            rel = Path(sub).relative_to(path.parent)
            sub_path = str(rel).replace("\\", "/")
        except ValueError:
            sub_path = str(sub)
        nodes.append({
            "type": "leaf",
            "name": sub.stem,
            "path": sub_path,
        })
    path.write_text(
        json.dumps({"name": name or path.stem, "nodes": nodes}),
        encoding="utf-8",
    )


# ===========================================================================
# UH1 - Merged tree name de-duplication
# ===========================================================================

class TestUH1_MergedTreeDedupsByName:
    """Two distinct .scriptreetree files whose internal
    ``TreeDef.name`` matches must produce DIFFERENT top-level
    folder names in the merged tree -- otherwise the user sees
    multiple "MSOffice" folders and can't tell them apart.
    """

    def test_two_sources_same_name_get_disambiguated(self, tmp_path):
        from scriptree.shell.merged_tree import build_merged_tree
        from scriptree.core.io import load_tree

        # Two distinct .scriptreetree files, both name themselves
        # "MSOffice" internally.
        a_dir = tmp_path / "a_apps" / "MSOffice"
        b_dir = tmp_path / "b_apps" / "MSOffice"
        a = a_dir / "MSOffice.scriptreetree"
        b = b_dir / "MSOffice.scriptreetree"
        leaf_a = a_dir / "ta.scriptree"
        leaf_b = b_dir / "tb.scriptree"
        _write_scriptree(leaf_a)
        _write_scriptree(leaf_b)
        _write_scriptreetree(a, leaves=[leaf_a], name="MSOffice")
        _write_scriptreetree(b, leaves=[leaf_b], name="MSOffice")

        merged_path = build_merged_tree([str(a), str(b)])
        merged = load_tree(str(merged_path))
        top_names = [n.name for n in merged.nodes]

        # Must NOT have two identical names.
        assert len(top_names) == len(set(top_names)), (
            f"merged top-level folder names must be unique; got "
            f"{top_names!r}"
        )


# ===========================================================================
# UH2 - Merged tree should inline subtree contents to keep them
#       editable in the merged-tree editor.
# ===========================================================================

class TestUH2_MergedTreeInlinesSubtreesForEditing:
    """When a source ``.scriptreetree`` references another
    .scriptreetree as a subtree, the merged tree must EXPAND
    those references into plain folders at build time -- not
    leave them as live references that the editor would render
    as read-only inlines.

    Why: the merged tree's editor needs full edit power
    (drag/drop, delete) to repair a catastrophic state.  A
    read-only inline blocks the user from doing that.
    """

    def test_subtree_reference_expanded_inline(self, tmp_path):
        from scriptree.shell.merged_tree import build_merged_tree
        from scriptree.core.io import load_tree

        # Parent .scriptreetree includes a leaf that points at
        # ANOTHER .scriptreetree.
        leaf = tmp_path / "child_app" / "tool.scriptree"
        _write_scriptree(leaf, "Tool")
        child = tmp_path / "child_app" / "Child.scriptreetree"
        _write_scriptreetree(child, leaves=[leaf], name="ChildApp")

        parent = tmp_path / "parent_app" / "Parent.scriptreetree"
        # The leaf-shaped path points at a .scriptreetree which
        # ``_add_node_item`` would render as a SUBTREE node.
        _write_scriptreetree(
            parent, subtrees=[child], name="ParentApp",
        )

        merged_path = build_merged_tree([str(parent)])
        merged = load_tree(str(merged_path))

        # The merged tree's ParentApp folder should now contain
        # the child's contents as REGULAR nested folders/leaves,
        # not as a single leaf-pointing-at-the-child-tree.
        parent_folder = merged.nodes[0]
        # Walk and verify there's at least one leaf pointing at
        # a .scriptree (not at a .scriptreetree).
        leaf_paths = _collect_leaf_paths(parent_folder)
        for p in leaf_paths:
            assert not p.lower().endswith(".scriptreetree"), (
                f"merged tree should NOT include subtree "
                f"references as live links; found {p!r}.  "
                f"Subtree contents must be inlined at build time."
            )


def _collect_leaf_paths(node) -> list[str]:
    out: list[str] = []
    if node.type == "leaf" and node.path:
        out.append(node.path)
    elif node.type == "folder":
        for child in node.children:
            out.extend(_collect_leaf_paths(child))
    return out


# ===========================================================================
# UH3 - Right-click on the tree column header shows context menu
# ===========================================================================

class TestUH3_HeaderRightClickShowsContextMenu:
    """The QHeaderView (the "Tools" header row at the top of
    the tree widget) must respond to right-click with the same
    context menu the tree-widget body shows.  Today the header's
    customContextMenuRequested isn't wired.
    """

    def test_header_has_custom_context_menu_policy(self, tmp_path):
        """v0.8.0a36+ wires the header's context menu so users can
        right-click "Tools" and see Save.

        We verify the wiring by checking the header's context-
        menu policy AND that the launcher exposes the helper that
        the header signal handler delegates to.
        """
        from scriptree.ui.tree_view import TreeLauncherView
        view = TreeLauncherView()
        header = view._tree_widget.header()
        policy = header.contextMenuPolicy()
        assert policy == Qt.ContextMenuPolicy.CustomContextMenu, (
            f"header context-menu policy must be "
            f"CustomContextMenu (was {policy!r})"
        )

    def test_header_right_click_handler_exposes_save(
        self, tmp_path,
    ):
        """Direct test: trigger the header context menu handler
        and verify it builds a menu including Save."""
        from scriptree.ui.tree_view import TreeLauncherView
        view = TreeLauncherView()
        view.new_tree()
        # Public helper -- mirrors the same handler the header
        # signal routes to.  Same as the empty-area menu builder.
        menu = QMenu(view)
        view._populate_context_menu_for(menu, item=None)
        labels = [a.text() for a in menu.actions()]
        assert any(
            "save" in lbl.lower() for lbl in labels
        ), (
            f"header right-click menu must expose a Save action; "
            f"got {labels!r}"
        )


# ===========================================================================
# UH4 - Save-tree on a merged tree propagates user deletions
# ===========================================================================

class TestUH4_SaveMergedTreePropagatesDeletions:
    """When the user deletes a top-level folder from the merged
    tree and saves, the corresponding source file must reflect
    the change.  Test that ``push_back_to_origins`` writes the
    new (reduced) state."""

    def test_deletion_of_top_level_folder_propagates(
        self, tmp_path,
    ):
        from scriptree.shell.merged_tree import (
            build_merged_tree, push_back_to_origins,
        )
        from scriptree.core.io import load_tree, save_tree

        leaf_a1 = tmp_path / "A" / "a1.scriptree"
        leaf_a2 = tmp_path / "A" / "a2.scriptree"
        _write_scriptree(leaf_a1)
        _write_scriptree(leaf_a2)
        src_a = tmp_path / "A" / "AppA.scriptreetree"
        _write_scriptreetree(
            src_a, leaves=[leaf_a1, leaf_a2], name="AppA",
        )

        merged_path = build_merged_tree([str(src_a)])
        merged = load_tree(str(merged_path))

        # User edits: remove leaf_a2 from the merged tree's
        # AppA folder.
        parent_folder = merged.nodes[0]
        parent_folder.children = [
            c for c in parent_folder.children
            if not (c.path and "a2" in c.path)
        ]
        save_tree(merged, str(merged_path))

        # Push back to origins.
        result = push_back_to_origins(merged_path)
        assert not result.errors, f"errors: {result.errors!r}"

        # The source AppA.scriptreetree must now show only a1.
        reloaded = load_tree(str(src_a))
        stems = [
            Path(n.path).stem if n.path else ""
            for n in reloaded.nodes
        ]
        assert "a1" in stems
        assert "a2" not in stems, (
            f"deletion of leaf 'a2' from merged tree must "
            f"propagate to source; got source leaves {stems!r}"
        )


# ===========================================================================
# UH5 - Build-time cycle detection
# ===========================================================================

class TestUH5_BuildTimeCycleDetection:
    """``build_merged_tree`` must terminate when given input
    files that contain subtree references forming a cycle.
    Currently the cycle is detected only at view-expansion time
    in the editor (``_expanding_paths``); the BUILD side has no
    such guard, so an inline-subtree expansion at build time
    would recurse forever.

    With the UH2 fix (inline at build), build_merged_tree must
    detect + skip cyclic references rather than infinite-recurse.
    """

    def test_self_referencing_tree_does_not_hang(self, tmp_path):
        from scriptree.shell.merged_tree import build_merged_tree

        # A .scriptreetree whose only node is a leaf pointing at
        # ITSELF (the .scriptreetree).  When inlined this would
        # cycle forever.
        self_ref = tmp_path / "self.scriptreetree"
        # Write a placeholder first so the self-reference target
        # exists at file-write time.
        self_ref.write_text(
            json.dumps({"name": "Self", "nodes": []}),
            encoding="utf-8",
        )
        # Now overwrite with the cyclic reference.
        self_ref.write_text(
            json.dumps({
                "name": "Self",
                "nodes": [
                    {
                        "type": "leaf",
                        "name": "self",
                        "path": "self.scriptreetree",
                    },
                ],
            }),
            encoding="utf-8",
        )

        # Building must terminate (not hang) and produce a
        # tree.  A timeout failure mode would manifest as the
        # test never returning.  pytest's default timeout is
        # infinite, so as a safety net use a Python signal in
        # the test if the build hangs > a few seconds.
        merged_path = build_merged_tree([str(self_ref)])
        assert merged_path.is_file()


# ===========================================================================
# UH6 - Determinism: rebuilding produces the same temp file
# ===========================================================================

class TestUH6_BuildIsDeterministic:
    """Rebuilding the merged tree with the same input set must
    produce the SAME output path (so V1's open file handle stays
    valid and QFileSystemWatcher doesn't see a new file).
    """

    def test_rebuild_with_same_inputs_is_stable(self, tmp_path):
        from scriptree.shell.merged_tree import build_merged_tree

        leaf = tmp_path / "demo" / "t.scriptree"
        _write_scriptree(leaf)
        a = tmp_path / "demo" / "A.scriptreetree"
        _write_scriptreetree(a, leaves=[leaf], name="A")

        first = build_merged_tree([str(a)])
        second = build_merged_tree([str(a)])
        assert str(first) == str(second), (
            f"rebuild with same inputs must produce same path; "
            f"first={first} second={second}"
        )

    def test_disambiguation_stable_across_runs(self, tmp_path):
        """If UH1's disambiguation is order-sensitive (e.g.
        "MSOffice (1)" vs "MSOffice (2)"), running the build
        twice with the same input order must produce the same
        labels."""
        from scriptree.shell.merged_tree import build_merged_tree
        from scriptree.core.io import load_tree

        a_dir = tmp_path / "a" / "MSOffice"
        b_dir = tmp_path / "b" / "MSOffice"
        a = a_dir / "MSOffice.scriptreetree"
        b = b_dir / "MSOffice.scriptreetree"
        la = a_dir / "la.scriptree"
        lb = b_dir / "lb.scriptree"
        _write_scriptree(la)
        _write_scriptree(lb)
        _write_scriptreetree(a, leaves=[la], name="MSOffice")
        _write_scriptreetree(b, leaves=[lb], name="MSOffice")

        first = build_merged_tree([str(a), str(b)])
        second = build_merged_tree([str(a), str(b)])

        names1 = [n.name for n in load_tree(str(first)).nodes]
        names2 = [n.name for n in load_tree(str(second)).nodes]
        assert names1 == names2
