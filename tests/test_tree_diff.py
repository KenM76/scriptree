"""Phase-3 regression suite for ``scriptree.core.tree_diff``.

Two functions under test:

* ``diff_against_tree(tree, tree_file, discovered, excluded)``
  → ``TreeDiscoveryDiff`` with ``added`` / ``removed`` /
  ``previously_excluded``.
* ``apply_diff_to_tree(tree, tree_file, accepted_adds=..., ...)``
  mutates ``tree`` in place.

Tests pin every rule documented in the module's docstring:

Diff routing:
* candidate already in tree → ignored (no bucket)
* candidate in excluded list → previously_excluded
* candidate neither in tree nor excluded → added
* leaf in tree whose file is gone → removed
* leaf in tree whose file still exists (outside scan scope)
  → NOT removed
* leaf in tree whose file is gone but is in
  ``accepted_removes`` semantics → covered in apply tests

Apply mutations:
* add at top level → leaf appended
* add nested → folder created with leaf inside
* add deeply nested → folder chain created
* add into existing folder → folder reused, leaf appended
* add idempotency → same path twice = single leaf
* remove leaf → leaf gone
* remove leaf leaves empty folder → folder collapses
* remove leaf leaves non-empty folder → folder stays
* nested folder collapse → multi-level empty chain removes fully
* re-include moves path out of excluded list
* re-include inserts leaf
* all-empty inputs → no-op

Auto-dismisses ``QMessageBox`` per the standing rule.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)

from scriptree.core.model import TreeDef, TreeNode
from scriptree.core.tree_diff import (
    TreeDiscoveryDiff,
    apply_diff_to_tree,
    diff_against_tree,
)
from scriptree.core.tree_discover import DiscoveredTreeItem


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _mk(path: Path, content: str = "{}") -> Path:
    """Create the file (and parent dirs) on disk; used so the diff's
    ``exists()`` check sees the right state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _disc(abs_path: Path, rel_path: str, kind: str = "tool") -> DiscoveredTreeItem:
    """Construct a DiscoveredTreeItem with the absolute resolved
    form (matching what the real walker emits)."""
    return DiscoveredTreeItem(
        abs_path=str(abs_path.resolve()),
        rel_path=rel_path,
        kind=kind,  # type: ignore[arg-type]
    )


def _flat_leaf_paths(nodes: list[TreeNode]) -> list[str]:
    """Walk the tree and return every leaf's path string in
    depth-first order.  Used so tests can assert structure with
    a single readable list."""
    out: list[str] = []
    for n in nodes:
        if n.type == "leaf":
            out.append(n.path or "")
        elif n.type == "folder":
            out.append(f"<{n.name}>")
            out.extend(_flat_leaf_paths(n.children))
            out.append(f"</{n.name}>")
    return out


# ============================================================================
# diff_against_tree
# ============================================================================


class TestDiffRouting:
    def test_candidate_already_in_tree_ignored(
        self, tmp_path: Path,
    ) -> None:
        """A discovered candidate whose path already matches an
        existing leaf goes into NO bucket."""
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tool = _mk(tmp_path / "exists.scriptree")

        tree = TreeDef(
            name="t",
            nodes=[TreeNode(type="leaf", path="./exists.scriptree")],
        )
        item = _disc(tool, "./exists.scriptree")

        diff = diff_against_tree(tree, tree_file, [item], excluded=[])
        assert diff.added == []
        assert diff.removed == []
        assert diff.previously_excluded == []

    def test_candidate_not_in_tree_goes_to_added(
        self, tmp_path: Path,
    ) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tool = _mk(tmp_path / "new.scriptree")

        tree = TreeDef(name="t", nodes=[])
        item = _disc(tool, "./new.scriptree")

        diff = diff_against_tree(tree, tree_file, [item], excluded=[])
        assert len(diff.added) == 1
        assert diff.added[0] is item

    def test_candidate_in_excluded_goes_to_previously_excluded(
        self, tmp_path: Path,
    ) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tool = _mk(tmp_path / "skip.scriptree")

        tree = TreeDef(name="t", nodes=[])
        item = _disc(tool, "./skip.scriptree")

        diff = diff_against_tree(
            tree, tree_file, [item], excluded=["./skip.scriptree"],
        )
        assert diff.added == []
        assert len(diff.previously_excluded) == 1
        assert diff.previously_excluded[0] is item

    def test_excluded_uses_treedef_when_none_passed(
        self, tmp_path: Path,
    ) -> None:
        """When ``excluded=None``, the function falls back to
        ``tree.excluded`` so callers don't have to thread it
        manually."""
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tool = _mk(tmp_path / "skip.scriptree")

        tree = TreeDef(
            name="t",
            nodes=[],
            excluded=["./skip.scriptree"],
        )
        item = _disc(tool, "./skip.scriptree")

        diff = diff_against_tree(tree, tree_file, [item])  # no excluded=
        assert len(diff.previously_excluded) == 1


class TestDiffRemoved:
    def test_leaf_with_missing_file_routes_to_removed(
        self, tmp_path: Path,
    ) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        # Note: 'gone.scriptree' is NOT created on disk -- the leaf
        # in the tree is pointing at a missing file.
        tree = TreeDef(
            name="t",
            nodes=[TreeNode(type="leaf", path="./gone.scriptree")],
        )

        # Empty discovery (the walker didn't see anything).
        diff = diff_against_tree(tree, tree_file, [], excluded=[])
        assert len(diff.removed) == 1
        assert diff.removed[0].path == "./gone.scriptree"

    def test_leaf_with_existing_file_outside_scan_kept(
        self, tmp_path: Path,
    ) -> None:
        """A leaf whose file still exists but wasn't discovered
        (because it lives outside the walker's scope) must NOT
        be routed to removed -- the user added it deliberately
        and the auto-discover scope just didn't see it."""
        tree_file = _mk(tmp_path / "t.scriptreetree")
        _mk(tmp_path / "still-here.scriptree")  # exists on disk

        tree = TreeDef(
            name="t",
            nodes=[TreeNode(type="leaf", path="./still-here.scriptree")],
        )

        # Discovery returns nothing -- maybe scan was scoped narrowly.
        diff = diff_against_tree(tree, tree_file, [], excluded=[])
        assert diff.removed == [], (
            "Leaf whose file still exists was incorrectly routed "
            "to 'removed'.  The diff must only remove leaves "
            "whose underlying file has vanished."
        )

    def test_leaf_in_nested_folder_can_be_removed(
        self, tmp_path: Path,
    ) -> None:
        """The diff walks folder children so a nested missing-file
        leaf is still picked up as removed."""
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tree = TreeDef(
            name="t",
            nodes=[
                TreeNode(type="folder", name="sub", children=[
                    TreeNode(
                        type="leaf",
                        path="./sub/missing.scriptree",
                    ),
                ]),
            ],
        )

        diff = diff_against_tree(tree, tree_file, [], excluded=[])
        assert len(diff.removed) == 1
        assert diff.removed[0].path == "./sub/missing.scriptree"


class TestDiffMixed:
    """End-to-end with a realistic mix of discovered, existing,
    excluded, and missing items."""

    def test_realistic_mix(self, tmp_path: Path) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        existing_tool = _mk(tmp_path / "existing.scriptree")
        new_tool = _mk(tmp_path / "new.scriptree")
        excluded_tool = _mk(tmp_path / "skip.scriptree")
        # gone.scriptree intentionally not created.

        tree = TreeDef(
            name="t",
            nodes=[
                TreeNode(type="leaf", path="./existing.scriptree"),
                TreeNode(type="leaf", path="./gone.scriptree"),
            ],
            excluded=["./skip.scriptree"],
        )

        discovered = [
            _disc(existing_tool, "./existing.scriptree"),
            _disc(new_tool, "./new.scriptree"),
            _disc(excluded_tool, "./skip.scriptree"),
        ]

        diff = diff_against_tree(tree, tree_file, discovered)

        # added: only the truly new one.
        assert [i.rel_path for i in diff.added] == ["./new.scriptree"]
        # removed: only the missing-file leaf.
        assert [n.path for n in diff.removed] == ["./gone.scriptree"]
        # previously_excluded: only the explicitly excluded.
        assert [i.rel_path for i in diff.previously_excluded] == ["./skip.scriptree"]

    def test_is_empty_helper(self) -> None:
        assert TreeDiscoveryDiff().is_empty()
        non_empty = TreeDiscoveryDiff(
            added=[DiscoveredTreeItem(
                abs_path="/x", rel_path="./x", kind="tool",
            )],
        )
        assert not non_empty.is_empty()


# ============================================================================
# apply_diff_to_tree -- adds
# ============================================================================


class TestApplyAdds:
    def test_add_top_level_leaf(self, tmp_path: Path) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tree = TreeDef(name="t")
        item = DiscoveredTreeItem(
            abs_path=str(tmp_path / "new.scriptree"),
            rel_path="./new.scriptree",
            kind="tool",
        )

        apply_diff_to_tree(tree, tree_file, accepted_adds=[item])
        assert len(tree.nodes) == 1
        assert tree.nodes[0].type == "leaf"
        assert tree.nodes[0].path == "./new.scriptree"

    def test_add_nested_creates_folder(self, tmp_path: Path) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tree = TreeDef(name="t")
        item = DiscoveredTreeItem(
            abs_path=str(tmp_path / "export" / "dxf.scriptree"),
            rel_path="./export/dxf.scriptree",
            kind="tool",
        )

        apply_diff_to_tree(tree, tree_file, accepted_adds=[item])
        assert len(tree.nodes) == 1
        folder = tree.nodes[0]
        assert folder.type == "folder"
        assert folder.name == "export"
        assert len(folder.children) == 1
        assert folder.children[0].path == "./export/dxf.scriptree"

    def test_add_deeply_nested_creates_chain(
        self, tmp_path: Path,
    ) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tree = TreeDef(name="t")
        item = DiscoveredTreeItem(
            abs_path=str(tmp_path / "a/b/c/deep.scriptree"),
            rel_path="./a/b/c/deep.scriptree",
            kind="tool",
        )

        apply_diff_to_tree(tree, tree_file, accepted_adds=[item])
        flat = _flat_leaf_paths(tree.nodes)
        assert flat == [
            "<a>",
            "<b>",
            "<c>",
            "./a/b/c/deep.scriptree",
            "</c>",
            "</b>",
            "</a>",
        ]

    def test_add_into_existing_folder_reuses_it(
        self, tmp_path: Path,
    ) -> None:
        """An accepted add whose path starts with an existing
        folder name must reuse that folder (preserving any
        existing display_name / icon)."""
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tree = TreeDef(
            name="t",
            nodes=[
                TreeNode(
                    type="folder",
                    name="export",
                    display_name="Exporters",
                    children=[
                        TreeNode(
                            type="leaf",
                            path="./export/step.scriptree",
                        ),
                    ],
                ),
            ],
        )
        item = DiscoveredTreeItem(
            abs_path=str(tmp_path / "export" / "dxf.scriptree"),
            rel_path="./export/dxf.scriptree",
            kind="tool",
        )

        apply_diff_to_tree(tree, tree_file, accepted_adds=[item])
        # Still one top-level folder -- not a duplicate.
        assert len(tree.nodes) == 1
        folder = tree.nodes[0]
        # display_name preserved.
        assert folder.display_name == "Exporters"
        # Existing leaf still there, new leaf appended.
        assert len(folder.children) == 2
        paths = sorted(c.path for c in folder.children)
        assert paths == ["./export/dxf.scriptree", "./export/step.scriptree"]

    def test_add_idempotent_for_same_path(self, tmp_path: Path) -> None:
        """Two calls with the same item must NOT produce a duplicate
        leaf."""
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tree = TreeDef(name="t")
        item = DiscoveredTreeItem(
            abs_path=str(tmp_path / "dup.scriptree"),
            rel_path="./dup.scriptree",
            kind="tool",
        )

        apply_diff_to_tree(tree, tree_file, accepted_adds=[item])
        apply_diff_to_tree(tree, tree_file, accepted_adds=[item])
        assert len(tree.nodes) == 1, (
            "Repeated apply of the same add created a duplicate leaf."
        )


# ============================================================================
# apply_diff_to_tree -- removes
# ============================================================================


class TestApplyRemoves:
    def test_remove_top_level_leaf(self, tmp_path: Path) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        leaf = TreeNode(type="leaf", path="./drop.scriptree")
        tree = TreeDef(name="t", nodes=[leaf])

        apply_diff_to_tree(tree, tree_file, accepted_removes=[leaf])
        assert tree.nodes == []

    def test_remove_collapses_empty_folder(self, tmp_path: Path) -> None:
        """When the removed leaf was the only child of a folder,
        the folder must also be dropped."""
        tree_file = _mk(tmp_path / "t.scriptreetree")
        leaf = TreeNode(type="leaf", path="./only-child/orphan.scriptree")
        folder = TreeNode(type="folder", name="only-child", children=[leaf])
        tree = TreeDef(name="t", nodes=[folder])

        apply_diff_to_tree(tree, tree_file, accepted_removes=[leaf])
        assert tree.nodes == [], (
            "Folder that became empty after a remove was not collapsed."
        )

    def test_remove_preserves_non_empty_folder(
        self, tmp_path: Path,
    ) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        drop = TreeNode(type="leaf", path="./group/drop.scriptree")
        keep = TreeNode(type="leaf", path="./group/keep.scriptree")
        folder = TreeNode(
            type="folder", name="group", children=[drop, keep],
        )
        tree = TreeDef(name="t", nodes=[folder])

        apply_diff_to_tree(tree, tree_file, accepted_removes=[drop])
        assert len(tree.nodes) == 1
        assert tree.nodes[0] is folder
        assert len(folder.children) == 1
        assert folder.children[0] is keep

    def test_remove_collapses_chain_of_empty_folders(
        self, tmp_path: Path,
    ) -> None:
        """A long ``a/b/c/d/`` chain whose only descendant is a
        single leaf collapses fully when that leaf is removed."""
        tree_file = _mk(tmp_path / "t.scriptreetree")
        leaf = TreeNode(type="leaf", path="./a/b/c/d/sole.scriptree")
        node_d = TreeNode(type="folder", name="d", children=[leaf])
        node_c = TreeNode(type="folder", name="c", children=[node_d])
        node_b = TreeNode(type="folder", name="b", children=[node_c])
        node_a = TreeNode(type="folder", name="a", children=[node_b])
        tree = TreeDef(name="t", nodes=[node_a])

        apply_diff_to_tree(tree, tree_file, accepted_removes=[leaf])
        assert tree.nodes == [], (
            "Multi-level chain of all-empty folders was not collapsed."
        )


# ============================================================================
# apply_diff_to_tree -- re-includes
# ============================================================================


class TestApplyReincludes:
    def test_reinclude_removes_from_excluded(
        self, tmp_path: Path,
    ) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tree = TreeDef(
            name="t",
            excluded=[
                "./skip.scriptree",
                "./other.scriptree",
            ],
        )
        item = DiscoveredTreeItem(
            abs_path=str(tmp_path / "skip.scriptree"),
            rel_path="./skip.scriptree",
            kind="tool",
        )

        apply_diff_to_tree(tree, tree_file, accepted_reincludes=[item])
        # Re-included path is gone from excluded.
        assert "./skip.scriptree" not in tree.excluded
        # Other excluded entry is untouched.
        assert "./other.scriptree" in tree.excluded

    def test_reinclude_inserts_leaf(self, tmp_path: Path) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tree = TreeDef(name="t", excluded=["./skip.scriptree"])
        item = DiscoveredTreeItem(
            abs_path=str(tmp_path / "skip.scriptree"),
            rel_path="./skip.scriptree",
            kind="tool",
        )

        apply_diff_to_tree(tree, tree_file, accepted_reincludes=[item])
        assert len(tree.nodes) == 1
        assert tree.nodes[0].path == "./skip.scriptree"


# ============================================================================
# apply_diff_to_tree -- edge cases & combinations
# ============================================================================


class TestApplyMisc:
    def test_no_op_when_all_inputs_empty(self, tmp_path: Path) -> None:
        tree_file = _mk(tmp_path / "t.scriptreetree")
        leaf = TreeNode(type="leaf", path="./x.scriptree")
        tree = TreeDef(name="t", nodes=[leaf], excluded=["./y"])
        apply_diff_to_tree(tree, tree_file)
        assert tree.nodes == [leaf]
        assert tree.excluded == ["./y"]

    def test_combined_add_remove_reinclude(
        self, tmp_path: Path,
    ) -> None:
        """One of each operation in a single call."""
        tree_file = _mk(tmp_path / "t.scriptreetree")
        drop = TreeNode(type="leaf", path="./drop.scriptree")
        tree = TreeDef(
            name="t",
            nodes=[drop],
            excluded=["./skip.scriptree"],
        )
        add_item = DiscoveredTreeItem(
            abs_path=str(tmp_path / "new.scriptree"),
            rel_path="./new.scriptree",
            kind="tool",
        )
        reinc_item = DiscoveredTreeItem(
            abs_path=str(tmp_path / "skip.scriptree"),
            rel_path="./skip.scriptree",
            kind="tool",
        )

        apply_diff_to_tree(
            tree,
            tree_file,
            accepted_adds=[add_item],
            accepted_removes=[drop],
            accepted_reincludes=[reinc_item],
        )

        paths = sorted(
            n.path for n in tree.nodes if n.type == "leaf" and n.path
        )
        assert paths == ["./new.scriptree", "./skip.scriptree"]
        assert tree.excluded == []

    def test_sibling_tree_kind_inserts_as_leaf(
        self, tmp_path: Path,
    ) -> None:
        """A ``sibling_tree``-kind candidate inserts as a regular
        leaf whose path points at the .scriptreetree -- the
        launcher handles nested trees at click time."""
        tree_file = _mk(tmp_path / "t.scriptreetree")
        tree = TreeDef(name="t")
        item = DiscoveredTreeItem(
            abs_path=str(tmp_path / "sub.scriptreetree"),
            rel_path="./sub.scriptreetree",
            kind="sibling_tree",
        )

        apply_diff_to_tree(tree, tree_file, accepted_adds=[item])
        assert len(tree.nodes) == 1
        leaf = tree.nodes[0]
        assert leaf.type == "leaf"
        assert leaf.path == "./sub.scriptreetree"
