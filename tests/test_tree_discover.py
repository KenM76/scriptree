"""Phase-2 regression suite for the ``.scriptreetree`` auto-discover
walker.

Pins every rule in ``scriptree.core.tree_discover``'s module
docstring against a synthetic directory layout built with
``tmp_path``.  Each test isolates one behaviour so a failure
points at exactly one rule.

The contracts under test:

* Empty directory → empty discovery.
* Single ``.scriptree`` in root → one tool candidate with the
  correct ``rel_path``.
* Self-tree exclusion: the ``.scriptreetree`` being scanned is
  NEVER surfaced as a sibling-tree candidate, even when it
  sits at the root.
* Sibling tree at root: emitted as sibling-tree candidate when
  flag on, NOT emitted when flag off.  Either way, root tools
  ARE scanned (rule 3 root asymmetry).
* Sibling tree in a non-root subdir: emitted (or not) per
  the same flag; the subdir's tools are NOT picked up;
  descent into the subdir's children is suppressed.
* Tools in nested subdirs: emitted with ``rel_path`` capturing
  the full ``./folder/sub/tool.scriptree`` path so the Phase 3
  apply step can reconstruct the folder hierarchy.
* Dotfile directories (``.git``, ``.vscode``) skipped — but an
  explicit dotted root is honoured.
* Symlink-loop guard: ``max_depth`` cap respected.
* Non-existent root: skipped silently rather than raising.
* Overlapping roots: deduplicated by normalised absolute path.
* The walker NEVER consults the excluded list (excluded
  routing belongs to Phase 3 ``diff_against_tree``).

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

from scriptree.core.tree_discover import (
    DiscoveredTreeItem,
    discover_for_tree,
)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _mk(path: Path, content: str = "{}") -> Path:
    """Create the file (and any missing parent dirs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _rel_paths_of(items: list[DiscoveredTreeItem]) -> set[str]:
    return {i.rel_path for i in items}


def _kinds_of(items: list[DiscoveredTreeItem]) -> set[str]:
    return {i.kind for i in items}


# ----------------------------------------------------------------------------
# Empty / trivial cases
# ----------------------------------------------------------------------------


class TestTrivialCases:
    def test_empty_directory_yields_nothing(self, tmp_path: Path) -> None:
        tree = _mk(tmp_path / "root.scriptreetree")
        out = discover_for_tree(tree)
        assert out == []

    def test_root_with_single_tool_yields_one(self, tmp_path: Path) -> None:
        tree = _mk(tmp_path / "root.scriptreetree")
        _mk(tmp_path / "alpha.scriptree")

        out = discover_for_tree(tree)
        assert len(out) == 1
        assert out[0].kind == "tool"
        assert out[0].rel_path == "./alpha.scriptree"
        # ``abs_path`` is the resolved file (case-folded under _norm).
        assert Path(out[0].abs_path).name == "alpha.scriptree"


# ----------------------------------------------------------------------------
# Self-exclusion: the tree being scanned must never be a candidate.
# ----------------------------------------------------------------------------


class TestSelfExclusion:
    def test_self_tree_at_root_not_surfaced(self, tmp_path: Path) -> None:
        """The single most important rule.  The tree file being
        scanned must NEVER appear in its own candidate list — even
        though every other ``.scriptreetree`` at the root would."""
        tree = _mk(tmp_path / "self.scriptreetree")
        _mk(tmp_path / "peer.scriptreetree")  # a peer
        _mk(tmp_path / "tool.scriptree")

        out = discover_for_tree(tree)
        rels = _rel_paths_of(out)
        assert "./self.scriptreetree" not in rels, (
            "Walker surfaced the tree being scanned as a candidate "
            "for inclusion in itself.  Self-exclusion regressed."
        )
        # Both peer + tool ARE picked up.
        assert "./peer.scriptreetree" in rels
        assert "./tool.scriptree" in rels


# ----------------------------------------------------------------------------
# Sibling-tree flag: rule 3 root vs. rule 4 non-root.
# ----------------------------------------------------------------------------


class TestSiblingTreeFlag:
    def test_root_peer_tree_surfaced_when_flag_on(
        self, tmp_path: Path,
    ) -> None:
        tree = _mk(tmp_path / "self.scriptreetree")
        _mk(tmp_path / "peer.scriptreetree")

        out = discover_for_tree(tree, include_sibling_trees=True)
        assert any(
            i.kind == "sibling_tree" and i.rel_path == "./peer.scriptreetree"
            for i in out
        )

    def test_root_peer_tree_not_surfaced_when_flag_off(
        self, tmp_path: Path,
    ) -> None:
        tree = _mk(tmp_path / "self.scriptreetree")
        _mk(tmp_path / "peer.scriptreetree")

        out = discover_for_tree(tree, include_sibling_trees=False)
        assert "sibling_tree" not in _kinds_of(out)

    def test_root_tools_still_scanned_when_peer_tree_present(
        self, tmp_path: Path,
    ) -> None:
        """Rule 3 asymmetry: the root dir is the current tree's
        scope.  A peer tree at the same level does NOT prevent the
        root's own ``.scriptree`` files from being emitted."""
        tree = _mk(tmp_path / "self.scriptreetree")
        _mk(tmp_path / "peer.scriptreetree")
        _mk(tmp_path / "root-tool.scriptree")

        out = discover_for_tree(tree)
        assert "./root-tool.scriptree" in _rel_paths_of(out)


# ----------------------------------------------------------------------------
# Subdir boundary: the central rule the user cares about.
# ----------------------------------------------------------------------------


class TestSubdirBoundary:
    def test_subdir_with_other_tree_blocks_descent(
        self, tmp_path: Path,
    ) -> None:
        """The ``.scriptreetree`` in a subdir owns that subdir.  The
        current tree must NOT see its tools."""
        tree = _mk(tmp_path / "self.scriptreetree")
        _mk(tmp_path / "owned-subdir" / "other.scriptreetree")
        _mk(tmp_path / "owned-subdir" / "owned-tool.scriptree")
        _mk(tmp_path / "owned-subdir" / "deeper" / "very-owned.scriptree")

        out = discover_for_tree(tree, include_sibling_trees=True)
        rels = _rel_paths_of(out)
        assert "./owned-subdir/owned-tool.scriptree" not in rels, (
            "Walker descended into a subdir that contains its own "
            ".scriptreetree -- boundary rule regressed."
        )
        assert "./owned-subdir/deeper/very-owned.scriptree" not in rels
        # The other-tree itself IS surfaced as a sibling-tree.
        assert "./owned-subdir/other.scriptreetree" in rels
        # And it's marked correctly.
        assert any(
            i.rel_path == "./owned-subdir/other.scriptreetree"
            and i.kind == "sibling_tree"
            for i in out
        )

    def test_subdir_other_tree_not_emitted_when_flag_off(
        self, tmp_path: Path,
    ) -> None:
        tree = _mk(tmp_path / "self.scriptreetree")
        _mk(tmp_path / "owned" / "other.scriptreetree")
        _mk(tmp_path / "owned" / "tool.scriptree")

        out = discover_for_tree(tree, include_sibling_trees=False)
        # Still respects the boundary (no owned/tool emitted).
        assert "./owned/tool.scriptree" not in _rel_paths_of(out)
        # AND the boundary file itself isn't surfaced.
        assert "./owned/other.scriptreetree" not in _rel_paths_of(out)

    def test_subdir_with_no_other_tree_is_descended(
        self, tmp_path: Path,
    ) -> None:
        tree = _mk(tmp_path / "self.scriptreetree")
        _mk(tmp_path / "open" / "tool-a.scriptree")
        _mk(tmp_path / "open" / "nested" / "tool-b.scriptree")

        out = discover_for_tree(tree)
        rels = _rel_paths_of(out)
        assert "./open/tool-a.scriptree" in rels
        assert "./open/nested/tool-b.scriptree" in rels

    def test_boundary_does_not_leak_into_sibling_subtree(
        self, tmp_path: Path,
    ) -> None:
        """A boundary in ``/owned/`` must NOT prevent scanning a
        peer subdir ``/open/`` at the same level."""
        tree = _mk(tmp_path / "self.scriptreetree")
        _mk(tmp_path / "owned" / "other.scriptreetree")
        _mk(tmp_path / "owned" / "owned-tool.scriptree")
        _mk(tmp_path / "open" / "good-tool.scriptree")

        out = discover_for_tree(tree)
        rels = _rel_paths_of(out)
        assert "./owned/owned-tool.scriptree" not in rels
        assert "./open/good-tool.scriptree" in rels


# ----------------------------------------------------------------------------
# Hidden directories.
# ----------------------------------------------------------------------------


class TestHiddenDirs:
    def test_dotgit_directory_skipped(self, tmp_path: Path) -> None:
        tree = _mk(tmp_path / "self.scriptreetree")
        _mk(tmp_path / ".git" / "config-tool.scriptree")
        _mk(tmp_path / ".vscode" / "settings-tool.scriptree")
        _mk(tmp_path / "visible-tool.scriptree")

        out = discover_for_tree(tree)
        rels = _rel_paths_of(out)
        assert "./visible-tool.scriptree" in rels
        assert "./.git/config-tool.scriptree" not in rels
        assert "./.vscode/settings-tool.scriptree" not in rels

    def test_explicit_dotted_root_is_honoured(
        self, tmp_path: Path,
    ) -> None:
        """When the user explicitly configures a dotted folder as
        a root, it gets scanned anyway.  Rule 1 has a 'unless
        explicit root' carve-out."""
        tree = _mk(tmp_path / "self.scriptreetree")
        _mk(tmp_path / ".dotted-tools" / "deliberately-here.scriptree")

        out = discover_for_tree(tree, roots=["./.dotted-tools"])
        assert any(
            "deliberately-here.scriptree" in i.rel_path for i in out
        )


# ----------------------------------------------------------------------------
# Multiple roots / dedup.
# ----------------------------------------------------------------------------


class TestMultipleRoots:
    def test_two_disjoint_roots_walked_independently(
        self, tmp_path: Path,
    ) -> None:
        tree = _mk(tmp_path / "self.scriptreetree")
        _mk(tmp_path / "a" / "a1.scriptree")
        _mk(tmp_path / "b" / "b1.scriptree")

        out = discover_for_tree(tree, roots=["./a", "./b"])
        rels = _rel_paths_of(out)
        # Note: when roots are individually specified, the rel_path
        # is anchored on the tree file's parent (not on each root),
        # so the path still reflects the full structure.
        assert "./a/a1.scriptree" in rels
        assert "./b/b1.scriptree" in rels

    def test_overlapping_roots_deduplicated(
        self, tmp_path: Path,
    ) -> None:
        tree = _mk(tmp_path / "self.scriptreetree")
        _mk(tmp_path / "shared" / "tool.scriptree")

        out = discover_for_tree(tree, roots=["./", "./shared"])
        # The same file would be discovered through both roots --
        # the dedup MUST keep exactly one.
        matching = [i for i in out if "tool.scriptree" in i.rel_path]
        assert len(matching) == 1

    def test_non_existent_root_skipped_silently(
        self, tmp_path: Path,
    ) -> None:
        tree = _mk(tmp_path / "self.scriptreetree")
        _mk(tmp_path / "real" / "tool.scriptree")

        out = discover_for_tree(tree, roots=["./does-not-exist", "./real"])
        rels = _rel_paths_of(out)
        assert "./real/tool.scriptree" in rels
        # And no crash for the missing root.

    def test_empty_roots_list_yields_empty_result(
        self, tmp_path: Path,
    ) -> None:
        tree = _mk(tmp_path / "self.scriptreetree")
        _mk(tmp_path / "tool.scriptree")
        out = discover_for_tree(tree, roots=[])
        assert out == []


# ----------------------------------------------------------------------------
# Path semantics.
# ----------------------------------------------------------------------------


class TestPaths:
    def test_rel_path_uses_forward_slashes(self, tmp_path: Path) -> None:
        """Even on Windows the ``rel_path`` must be forward-slash so
        it matches the ``TreeNode.path`` convention used everywhere
        else in the codebase."""
        tree = _mk(tmp_path / "self.scriptreetree")
        _mk(tmp_path / "sub" / "nested" / "deep.scriptree")

        out = discover_for_tree(tree)
        deep = next(i for i in out if "deep.scriptree" in i.rel_path)
        assert "\\" not in deep.rel_path, (
            f"rel_path contains backslash: {deep.rel_path!r}.  "
            f"Round-trip with hand-edited Windows files will break."
        )
        assert deep.rel_path == "./sub/nested/deep.scriptree"

    def test_abs_path_is_absolute(self, tmp_path: Path) -> None:
        tree = _mk(tmp_path / "self.scriptreetree")
        _mk(tmp_path / "alpha.scriptree")
        out = discover_for_tree(tree)
        assert Path(out[0].abs_path).is_absolute()

    def test_suffix_classification_prefers_tree_over_tool(
        self, tmp_path: Path,
    ) -> None:
        """``.scriptreetree`` ends with ``.scriptree`` as substring;
        the longer suffix MUST be tested first."""
        tree = _mk(tmp_path / "self.scriptreetree")
        _mk(tmp_path / "peer.scriptreetree")

        out = discover_for_tree(tree)
        peer = next(i for i in out if "peer" in i.rel_path)
        assert peer.kind == "sibling_tree", (
            f"peer.scriptreetree classified as {peer.kind!r} -- "
            f"the longer-suffix-first rule is wrong."
        )


# ----------------------------------------------------------------------------
# Depth budget.
# ----------------------------------------------------------------------------


class TestDepthBudget:
    def test_max_depth_caps_descent(self, tmp_path: Path) -> None:
        tree = _mk(tmp_path / "self.scriptreetree")
        # Create files at depths 0, 1, 2, 3.
        _mk(tmp_path / "d0.scriptree")
        _mk(tmp_path / "sub1" / "d1.scriptree")
        _mk(tmp_path / "sub1" / "sub2" / "d2.scriptree")
        _mk(tmp_path / "sub1" / "sub2" / "sub3" / "d3.scriptree")

        out = discover_for_tree(tree, max_depth=2)
        rels = _rel_paths_of(out)
        assert "./d0.scriptree" in rels
        assert "./sub1/d1.scriptree" in rels
        assert "./sub1/sub2/d2.scriptree" in rels
        assert "./sub1/sub2/sub3/d3.scriptree" not in rels, (
            "max_depth=2 should cap descent at depth 2."
        )


# ----------------------------------------------------------------------------
# End-to-end realistic shape (the recommended ScripTreeApps layout).
# ----------------------------------------------------------------------------


class TestRealisticLayout:
    """A folder shape that mirrors the recommended convention from
    docs/LLM/scriptreetree_format.md:

        solidworks/
          solidworks.scriptreetree   <- the tree being scanned
          export/
            dxf.scriptree
            step.scriptree
          cleanup/
            hide-sketches.scriptree
          subtree/
            cleanup.scriptreetree    <- owned subtree
            owned-tool.scriptree
    """

    def test_recommended_shape_resolves_correctly(
        self, tmp_path: Path,
    ) -> None:
        root = tmp_path / "solidworks"
        tree = _mk(root / "solidworks.scriptreetree")
        _mk(root / "export" / "dxf.scriptree")
        _mk(root / "export" / "step.scriptree")
        _mk(root / "cleanup" / "hide-sketches.scriptree")
        _mk(root / "subtree" / "cleanup.scriptreetree")
        _mk(root / "subtree" / "owned-tool.scriptree")

        out = discover_for_tree(tree)
        rels = _rel_paths_of(out)
        # Tools in scope subdirs ARE found.
        assert "./export/dxf.scriptree" in rels
        assert "./export/step.scriptree" in rels
        assert "./cleanup/hide-sketches.scriptree" in rels
        # The owned subtree is surfaced as a sibling-tree candidate.
        assert "./subtree/cleanup.scriptreetree" in rels
        # The owned subtree's tools are NOT.
        assert "./subtree/owned-tool.scriptree" not in rels
        # And the kinds are right.
        kinds = {i.rel_path: i.kind for i in out}
        assert kinds["./export/dxf.scriptree"] == "tool"
        assert kinds["./subtree/cleanup.scriptreetree"] == "sibling_tree"
