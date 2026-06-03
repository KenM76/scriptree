"""Regression suite for merged-tree back-propagation (v0.8.0a31+).

The merged tree (built by ``build_merged_tree`` from a master cell's
members) is now an editable surface: when V1 saves it, our
``push_back_to_origins`` walks the saved file + the origins sidecar
and pushes each top-level folder back to its source ``.scriptreetree``
file.  These tests pin:

  * ``build_merged_tree`` writes a sidecar alongside the merged
    .scriptreetree.  Sidecar JSON has a ``version`` and an
    ``origins`` list of {folder_name, source_path} entries in the
    same order the merged-tree top-level folders appear.
  * ``is_merged_tree`` returns True iff the path looks like a
    merged-tree temp file AND its sidecar exists.
  * ``push_back_to_origins`` round-trips a multi-source merge:
    edit the merged tree, push back, and the originating
    .scriptreetree files now hold the edits.
  * Leaf paths in the source files are restored from absolute
    (the merged-tree convention) to relative-to-source (the
    canonical .scriptreetree convention).
  * Single-tool .scriptree origins are skipped cleanly (with a
    reason recorded in ``PushBackResult.skipped``) rather than
    erroring or silently overwriting.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_scriptree(path: Path, name: str | None = None) -> None:
    """Drop a minimal .scriptree at ``path``."""
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
    path: Path, leaves: list[Path], name: str | None = None,
) -> None:
    """Drop a .scriptreetree at ``path`` referencing ``leaves`` as
    top-level leaf nodes.  All leaf paths are stored as RELATIVE
    to the .scriptreetree's directory (canonical convention)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    nodes = []
    for leaf in leaves:
        rel = Path(leaf).relative_to(path.parent)
        nodes.append({
            "type": "leaf",
            "name": leaf.stem,
            "path": str(rel).replace("\\", "/"),
        })
    path.write_text(
        json.dumps({
            "name": name or path.stem,
            "nodes": nodes,
        }),
        encoding="utf-8",
    )


# ===========================================================================
# Sidecar writing during build_merged_tree
# ===========================================================================

class TestSidecar:
    """``build_merged_tree`` writes a sidecar JSON next to the
    merged .scriptreetree.  The sidecar lists each source path
    paired with the top-level folder name that came from it."""

    def test_sidecar_written_with_correct_entries(self, tmp_path):
        from scriptree.shell.merged_tree import (
            build_merged_tree, _origins_sidecar_path,
        )
        # Build two source trees so the merged tree has two
        # top-level folders.
        tree_a = tmp_path / "appA.scriptreetree"
        leaf_a1 = tmp_path / "a1.scriptree"
        _write_scriptree(leaf_a1, "a1")
        _write_scriptreetree(tree_a, [leaf_a1], name="AppA")

        tree_b = tmp_path / "appB.scriptreetree"
        leaf_b1 = tmp_path / "b1.scriptree"
        _write_scriptree(leaf_b1, "b1")
        _write_scriptreetree(tree_b, [leaf_b1], name="AppB")

        merged = build_merged_tree([str(tree_a), str(tree_b)])
        sidecar = _origins_sidecar_path(merged)
        assert sidecar.is_file(), "sidecar wasn't written"
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        assert data["version"] == 1
        origins = data["origins"]
        assert len(origins) == 2
        names = [o["folder_name"] for o in origins]
        srcs = [o["source_path"] for o in origins]
        assert "AppA" in names
        assert "AppB" in names
        assert str(tree_a.resolve()) in srcs
        assert str(tree_b.resolve()) in srcs


class TestIsMergedTree:
    """``is_merged_tree`` should accept a true merged-tree path +
    sidecar and reject everything else."""

    def test_accepts_real_merged_tree(self, tmp_path):
        from scriptree.shell.merged_tree import (
            build_merged_tree, is_merged_tree,
        )
        src = tmp_path / "x.scriptreetree"
        leaf = tmp_path / "x.scriptree"
        _write_scriptree(leaf, "x")
        _write_scriptreetree(src, [leaf], name="X")
        merged = build_merged_tree([str(src)])
        assert is_merged_tree(merged) is True
        # str also works
        assert is_merged_tree(str(merged)) is True

    def test_rejects_plain_scriptreetree(self, tmp_path):
        from scriptree.shell.merged_tree import is_merged_tree
        plain = tmp_path / "plain.scriptreetree"
        plain.write_text("{}", encoding="utf-8")
        assert is_merged_tree(plain) is False

    def test_rejects_merged_prefix_without_sidecar(self, tmp_path):
        """A file the user happens to name with the same prefix
        must not trip the detection without its sidecar."""
        from scriptree.shell.merged_tree import is_merged_tree
        fake = tmp_path / "scriptreering_merged_fake.scriptreetree"
        fake.write_text("{}", encoding="utf-8")
        assert is_merged_tree(fake) is False


# ===========================================================================
# Back-propagation round-trip
# ===========================================================================

class TestPushBackToOrigins:
    """The core round-trip: build a merged tree from two sources,
    edit the merged tree, push back, and verify each source file
    holds the edits."""

    def test_round_trip_to_two_scriptreetree_sources(self, tmp_path):
        from scriptree.shell.merged_tree import (
            build_merged_tree, push_back_to_origins,
        )
        from scriptree.core.io import load_tree, save_tree
        from scriptree.core.model import TreeDef, TreeNode

        # Two source trees, each with one leaf.
        src_a = tmp_path / "A" / "appA.scriptreetree"
        leaf_a = tmp_path / "A" / "tool_a.scriptree"
        _write_scriptree(leaf_a, "ToolA")
        _write_scriptreetree(src_a, [leaf_a], name="AppA")

        src_b = tmp_path / "B" / "appB.scriptreetree"
        leaf_b = tmp_path / "B" / "tool_b.scriptree"
        _write_scriptree(leaf_b, "ToolB")
        _write_scriptreetree(src_b, [leaf_b], name="AppB")

        # Build the merged tree.
        merged_path = build_merged_tree([str(src_a), str(src_b)])
        merged = load_tree(str(merged_path))

        # Edit: add a SECOND leaf to the "AppA" folder (simulating
        # the user adding a tool in V1 to one of the forest members).
        new_leaf = tmp_path / "A" / "tool_a2.scriptree"
        _write_scriptree(new_leaf, "ToolA2")
        for top in merged.nodes:
            if top.name == "AppA":
                top.children.append(TreeNode(
                    type="leaf",
                    name="tool_a2",
                    path=str(new_leaf.resolve()),  # merged-tree
                                                   # convention:
                                                   # absolute
                ))
                break
        save_tree(merged, str(merged_path))

        # Push back.
        result = push_back_to_origins(merged_path)
        assert not result.errors, f"unexpected errors: {result.errors}"
        assert str(src_a.resolve()) in result.written
        assert str(src_b.resolve()) in result.written

        # Verify source A now has BOTH leaves.  V1's tree leaves
        # don't carry a separate ``name`` field -- the display
        # label comes from the leaf path's file stem -- so we
        # assert on the leaf paths rather than node names.
        reloaded_a = load_tree(str(src_a))
        a_stems = [
            Path(n.path).stem if n.path else ""
            for n in reloaded_a.nodes
        ]
        assert "tool_a" in a_stems
        assert "tool_a2" in a_stems

        # Verify source B still has its single leaf.
        reloaded_b = load_tree(str(src_b))
        b_stems = [
            Path(n.path).stem if n.path else ""
            for n in reloaded_b.nodes
        ]
        assert "tool_b" in b_stems
        assert len(b_stems) == 1

    def test_leaf_paths_restored_to_relative(self, tmp_path):
        """Source files must store leaf paths RELATIVE to the
        .scriptreetree (canonical convention), not the absolute
        paths the merged tree uses."""
        from scriptree.shell.merged_tree import (
            build_merged_tree, push_back_to_origins,
        )
        from scriptree.core.io import load_tree, save_tree

        src = tmp_path / "App" / "app.scriptreetree"
        leaf = tmp_path / "App" / "subdir" / "tool.scriptree"
        _write_scriptree(leaf, "Tool")
        _write_scriptreetree(src, [leaf], name="App")

        merged_path = build_merged_tree([str(src)])
        merged = load_tree(str(merged_path))
        save_tree(merged, str(merged_path))  # no edits, just save

        push_back_to_origins(merged_path)

        # Now inspect the source file directly: leaf path must be
        # "subdir/tool.scriptree" (relative), not an absolute path.
        data = json.loads(src.read_text(encoding="utf-8"))
        leaf_node = data["nodes"][0]
        assert leaf_node["path"] == "subdir/tool.scriptree", (
            f"expected relative leaf path, got {leaf_node['path']!r}"
        )

    def test_scriptree_origin_is_skipped(self, tmp_path):
        """Single-tool .scriptree catalogs can't round-trip through
        the merged-tree wrapper -- they should be skipped with a
        clear reason rather than erroring or overwriting wrongly."""
        from scriptree.shell.merged_tree import (
            build_merged_tree, push_back_to_origins,
        )
        # Source is a .scriptree (not a tree).
        src = tmp_path / "lone.scriptree"
        _write_scriptree(src, "Lone")
        merged_path = build_merged_tree([str(src)])
        result = push_back_to_origins(merged_path)
        skipped_paths = [s[0] for s in result.skipped]
        assert str(src.resolve()) in skipped_paths
        assert not result.errors

    def test_missing_sidecar_returns_error(self, tmp_path):
        """If someone tries to push-back a file whose sidecar
        doesn't exist (e.g. the user copied the merged tree
        elsewhere first), report the failure clearly."""
        from scriptree.shell.merged_tree import push_back_to_origins
        fake = tmp_path / "scriptreering_merged_orphan.scriptreetree"
        fake.write_text(
            json.dumps({"name": "x", "nodes": []}),
            encoding="utf-8",
        )
        result = push_back_to_origins(fake)
        assert result.errors
        assert "origins sidecar missing" in result.errors[0][1]
