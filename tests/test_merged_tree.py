"""Tests for ``scriptree.shell.merged_tree`` — the helper that builds
a synthetic merged ``.scriptreetree`` from multiple member catalogs."""
from __future__ import annotations

from pathlib import Path

from scriptree.core.io import load_tree, save_tool, save_tree
from scriptree.core.model import ParamDef, ToolDef, TreeDef, TreeNode
from scriptree.shell.merged_tree import (
    build_merged_tree,
    build_merged_tree_for_master,
)


def _make_tool(tmp: Path, name: str) -> Path:
    tool = ToolDef(
        name=name,
        executable="/bin/echo",
        argument_template=["{x}"],
        params=[ParamDef(id="x", label="X", default=name)],
    )
    p = tmp / f"{name}.scriptree"
    save_tool(tool, p)
    return p


def _make_tree(tmp: Path, name: str, leaves: list[Path]) -> Path:
    nodes = [
        TreeNode(type="leaf", name=p.stem, path=p.name)
        for p in leaves
    ]
    tree = TreeDef(name=name, nodes=nodes)
    out = tmp / f"{name}.scriptreetree"
    save_tree(tree, out)
    return out


# ---------------------------------------------------------------------------
# build_merged_tree
# ---------------------------------------------------------------------------

def test_build_merged_tree_single_source(tmp_path: Path) -> None:
    """One source catalog → one top-level folder in the merged tree."""
    t1 = _make_tool(tmp_path, "alpha")
    tree_a = _make_tree(tmp_path, "TreeA", [t1])

    out = build_merged_tree([str(tree_a)])
    assert out.is_file()
    merged = load_tree(str(out))
    # One member → one top-level folder named "TreeA".
    assert len(merged.nodes) == 1
    folder = merged.nodes[0]
    assert folder.type == "folder"
    assert folder.name == "TreeA"
    # Inside: the single leaf with absolute path.
    assert len(folder.children) == 1
    leaf = folder.children[0]
    assert leaf.type == "leaf"
    assert Path(leaf.path).is_absolute()
    assert Path(leaf.path).resolve() == t1.resolve()


def test_build_merged_tree_two_sources(tmp_path: Path) -> None:
    """Two source catalogs → two top-level folders, members preserved."""
    t1 = _make_tool(tmp_path, "alpha")
    t2 = _make_tool(tmp_path, "beta")
    tree_a = _make_tree(tmp_path, "TreeA", [t1])
    tree_b = _make_tree(tmp_path, "TreeB", [t2])

    out = build_merged_tree([str(tree_a), str(tree_b)])
    merged = load_tree(str(out))
    assert len(merged.nodes) == 2
    names = {n.name for n in merged.nodes}
    assert names == {"TreeA", "TreeB"}


def test_build_merged_tree_resolves_relative_paths(tmp_path: Path) -> None:
    """Leaf paths inside source trees are relative; the merged tree
    must rewrite them to absolute so the temp file is portable."""
    t1 = _make_tool(tmp_path, "alpha")
    # The tree refers to alpha.scriptree relatively (filename only).
    tree_a = _make_tree(tmp_path, "TreeA", [t1])

    out = build_merged_tree([str(tree_a)])
    merged = load_tree(str(out))
    leaf = merged.nodes[0].children[0]
    assert Path(leaf.path).is_absolute()
    assert Path(leaf.path).is_file()


def test_build_merged_tree_dedups(tmp_path: Path) -> None:
    """Passing the same source path twice should produce one folder
    (de-duplication)."""
    t1 = _make_tool(tmp_path, "alpha")
    tree_a = _make_tree(tmp_path, "TreeA", [t1])

    out = build_merged_tree([str(tree_a), str(tree_a)])
    merged = load_tree(str(out))
    assert len(merged.nodes) == 1


def test_build_merged_tree_skips_missing(tmp_path: Path) -> None:
    """Missing source files are skipped, not fatal."""
    t1 = _make_tool(tmp_path, "alpha")
    tree_a = _make_tree(tmp_path, "TreeA", [t1])

    out = build_merged_tree([
        str(tree_a),
        str(tmp_path / "does_not_exist.scriptreetree"),
    ])
    merged = load_tree(str(out))
    assert len(merged.nodes) == 1
    assert merged.nodes[0].name == "TreeA"


def test_build_merged_tree_wraps_scriptree_as_folder(tmp_path: Path) -> None:
    """A bare .scriptree source becomes a one-leaf folder in the merge."""
    t1 = _make_tool(tmp_path, "alpha")

    out = build_merged_tree([str(t1)])
    merged = load_tree(str(out))
    assert len(merged.nodes) == 1
    folder = merged.nodes[0]
    assert folder.type == "folder"
    # Folder name = tool's name.
    assert folder.name == "alpha"
    # Single leaf points at the source .scriptree.
    assert len(folder.children) == 1
    leaf = folder.children[0]
    assert Path(leaf.path).resolve() == t1.resolve()


def test_build_merged_tree_empty_sources_raises(tmp_path: Path) -> None:
    """All-missing input → ValueError (no point producing an empty
    tree that V1 will reject)."""
    import pytest
    with pytest.raises(ValueError):
        build_merged_tree([str(tmp_path / "missing.scriptreetree")])


# ---------------------------------------------------------------------------
# build_merged_tree_for_master
# ---------------------------------------------------------------------------

class _FakeMember:
    def __init__(self, catalog_path):
        self._catalog_path = catalog_path


class _FakeMaster:
    def __init__(self, members):
        self._members = members


def test_build_merged_tree_for_master_extracts_paths(tmp_path: Path) -> None:
    t1 = _make_tool(tmp_path, "alpha")
    t2 = _make_tool(tmp_path, "beta")
    tree_a = _make_tree(tmp_path, "TreeA", [t1])
    tree_b = _make_tree(tmp_path, "TreeB", [t2])

    master = _FakeMaster([
        _FakeMember(str(tree_a)),
        _FakeMember(str(tree_b)),
    ])
    out = build_merged_tree_for_master(master)
    assert out.is_file()
    merged = load_tree(str(out))
    assert len(merged.nodes) == 2


def test_build_merged_tree_for_master_skips_unbound_members(tmp_path: Path) -> None:
    """Members with no _catalog_path are silently skipped."""
    t1 = _make_tool(tmp_path, "alpha")
    tree_a = _make_tree(tmp_path, "TreeA", [t1])

    master = _FakeMaster([
        _FakeMember(str(tree_a)),
        _FakeMember(None),
        _FakeMember(""),
    ])
    out = build_merged_tree_for_master(master)
    merged = load_tree(str(out))
    assert len(merged.nodes) == 1


def test_build_merged_tree_for_master_caches_result(tmp_path: Path) -> None:
    """Repeated calls with the same membership reuse the same path."""
    t1 = _make_tool(tmp_path, "alpha")
    tree_a = _make_tree(tmp_path, "TreeA", [t1])

    master = _FakeMaster([_FakeMember(str(tree_a))])
    out1 = build_merged_tree_for_master(master)
    out2 = build_merged_tree_for_master(master)
    assert out1 == out2


def test_build_merged_tree_for_master_no_members_returns_placeholder(
    tmp_path: Path,
) -> None:
    """v0.2.3 contract change: when NO member has a catalog bound
    (e.g. a fresh ring spawned from snap-dock with two unbound cells),
    we no longer raise — we produce a placeholder ``.scriptreetree``
    so V1's editor can open with a clear "no catalogs bound" hint.

    Per the user's spec: "either way, scriptreering file or not, it
    needs to be able to open this way."
    """
    master = _FakeMaster([])  # zero members → empty paths list
    out = build_merged_tree_for_master(master)
    assert out.is_file()
    # Should be parseable as a regular .scriptreetree.
    from scriptree.core.io import load_tree
    tree = load_tree(str(out))
    # Has at least one node so the editor doesn't show "(empty)".
    assert len(tree.nodes) >= 1
    # The placeholder folder name should hint at the empty-ring state.
    assert "no" in tree.nodes[0].name.lower() or \
           "ring" in tree.name.lower() or \
           "no" in tree.name.lower()


def test_build_merged_tree_for_master_unbound_member_returns_placeholder(
    tmp_path: Path,
) -> None:
    """A master with one member that has NO catalog bound should still
    produce a tree (placeholder), not raise."""
    master = _FakeMaster([_FakeMember(None)])
    out = build_merged_tree_for_master(master)
    assert out.is_file()
    from scriptree.core.io import load_tree
    tree = load_tree(str(out))
    assert len(tree.nodes) >= 1
