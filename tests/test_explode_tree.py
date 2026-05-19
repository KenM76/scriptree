"""Tests for ``scriptree.shell.explode_tree``.

The explode helper turns a single ``.scriptreetree`` into a multi-cell
``.scriptreering`` whose members are the tree's top-level items (one
cell per leaf or folder).  Folders get materialised as their own
``.scriptreetree`` files in ``%TEMP%`` with absolute leaf paths.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scriptree.core.io import load_tree, save_tool, save_tree
from scriptree.core.model import ToolDef, TreeDef, TreeNode
from scriptree.shell.explode_tree import explode_tree_to_ring


def _seed_tool(tmp_path: Path, name: str) -> Path:
    p = tmp_path / f"{name}.scriptree"
    save_tool(ToolDef(name=name, executable="python"), p)
    return p


def _seed_tree(tmp_path: Path) -> Path:
    leaf_a = _seed_tool(tmp_path, "alpha")
    leaf_b = _seed_tool(tmp_path, "beta")
    leaf_c = _seed_tool(tmp_path, "gamma")
    tree = TreeDef(
        name="ExplodeMe",
        nodes=[
            TreeNode(type="folder", name="Group", children=[
                # Use *relative* path to verify the explode helper
                # resolves it against the tree's own directory.
                TreeNode(type="leaf", name="alpha", path="alpha.scriptree"),
                TreeNode(type="leaf", name="beta",  path=str(leaf_b)),
            ]),
            TreeNode(type="leaf", name="gamma", path=str(leaf_c)),
        ],
    )
    p = tmp_path / "demo.scriptreetree"
    save_tree(tree, p)
    return p


def test_empty_tree_raises(tmp_path: Path) -> None:
    """No top-level items → ValueError so the editor can show a
    friendly message instead of silently producing an empty ring."""
    tree = TreeDef(name="Empty", nodes=[])
    p = tmp_path / "empty.scriptreetree"
    save_tree(tree, p)
    with pytest.raises(ValueError):
        explode_tree_to_ring(p)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        explode_tree_to_ring(tmp_path / "nope.scriptreetree")


def test_explode_produces_one_member_per_top_level(tmp_path: Path) -> None:
    p = _seed_tree(tmp_path)
    out = explode_tree_to_ring(p)

    assert out.is_file()
    assert out.suffix == ".scriptreering"
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["format"] == "scriptreering"
    assert doc["master"]["role"] == "master"
    # Two top-level items — one folder + one leaf.
    assert len(doc["members"]) == 2


def test_explode_folder_member_is_a_real_scriptreetree(tmp_path: Path) -> None:
    """The folder top-level item must be materialised as its own
    .scriptreetree with absolute leaf paths."""
    p = _seed_tree(tmp_path)
    out = explode_tree_to_ring(p)
    doc = json.loads(out.read_text(encoding="utf-8"))

    # Find the member whose catalog_path is a .scriptreetree
    folder_members = [
        m for m in doc["members"]
        if str(m["catalog_path"]).lower().endswith(".scriptreetree")
    ]
    assert len(folder_members) == 1
    sub_path = Path(folder_members[0]["catalog_path"])
    assert sub_path.is_file()

    # Loading it back must succeed and contain absolute leaf paths.
    sub_tree = load_tree(str(sub_path))
    assert len(sub_tree.nodes) == 2
    for node in sub_tree.nodes:
        assert node.type == "leaf"
        assert Path(node.path).is_absolute()
        assert Path(node.path).is_file()


def test_explode_leaf_member_uses_absolute_path(tmp_path: Path) -> None:
    """Top-level leaves should be referenced by their absolute path
    (relative paths in the source tree get resolved against the tree's
    directory before being copied into the ring file)."""
    p = _seed_tree(tmp_path)
    out = explode_tree_to_ring(p)
    doc = json.loads(out.read_text(encoding="utf-8"))

    leaf_members = [
        m for m in doc["members"]
        if str(m["catalog_path"]).lower().endswith(".scriptree")
    ]
    assert len(leaf_members) == 1
    cp = Path(leaf_members[0]["catalog_path"])
    assert cp.is_absolute()
    assert cp.is_file()


def test_explode_member_positions_form_a_ring(tmp_path: Path) -> None:
    """Every member should have a non-default position so the cells
    appear arranged around the master, not stacked on top of it."""
    p = _seed_tree(tmp_path)
    out = explode_tree_to_ring(p)
    doc = json.loads(out.read_text(encoding="utf-8"))

    master_x = doc["master"]["position"]["x"]
    master_y = doc["master"]["position"]["y"]

    seen: set[tuple[int, int]] = set()
    for m in doc["members"]:
        pos = (m["position"]["x"], m["position"]["y"])
        assert pos != (master_x, master_y)
        assert pos not in seen, "members should not overlap"
        seen.add(pos)


def test_explode_is_deterministic(tmp_path: Path) -> None:
    """Re-exploding the same tree should produce the same temp ring
    path so a cell-shell QFileSystemWatcher can stay attached."""
    p = _seed_tree(tmp_path)
    out1 = explode_tree_to_ring(p)
    out2 = explode_tree_to_ring(p)
    assert out1 == out2


def test_explode_preserves_member_count_for_only_leaves(tmp_path: Path) -> None:
    """A tree with only top-level leaves — no folders — should still
    produce one member per leaf."""
    leaves = [_seed_tool(tmp_path, n) for n in ("a", "b", "c", "d")]
    tree = TreeDef(
        name="LeavesOnly",
        nodes=[
            TreeNode(type="leaf", name=p.stem, path=str(p)) for p in leaves
        ],
    )
    p = tmp_path / "leaves.scriptreetree"
    save_tree(tree, p)
    out = explode_tree_to_ring(p)
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert len(doc["members"]) == 4
