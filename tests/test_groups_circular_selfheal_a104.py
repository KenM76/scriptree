"""v0.8.0a104 — kill the recurring `_groups` circular reference for good.

Root cause (traced + reproduced): a synthesised auto-group under `_groups/` got a
leaf pointing at its SIBLING group (Demo ⊃ `./MSOffice.scriptreetree` and
vice-versa).  The writer was a PRE-a100 `push_back_to_origins` (which strips the
`synthesised_by` marker and relativises the leaf to `./Sibling.scriptreetree`).
The a100 per-child strip neutralised NEW writes, but the marker-stripped residue
on disk was UN-PRUNABLE (`prune_orphan_synthesised` only deleted marker-bearing
files) and was re-shown every startup.

Two fixes pinned here:
  1. ``push_back_to_origins`` REFUSES to write any `_groups/` source at all
     (whole-file, marker-independent) — a synth group is owned by ``categorize``.
  2. ``prune_orphan_synthesised`` SELF-HEALS: it now also deletes a `_groups`
     file that is structurally illegal (contains a `.scriptreetree` leaf), even
     without the marker, so existing/residual corruption is reclaimed and the
     next pass regenerates the group cleanly from tool categories.
"""
from __future__ import annotations

import json
from pathlib import Path


def _write_scriptree(path: Path, name: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "name": name or path.stem, "executable": "echo", "params": [],
    }), encoding="utf-8")


def _write_scriptreetree(path: Path, leaves, name=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nodes = []
    for leaf in leaves:
        rel = Path(leaf).relative_to(path.parent)
        nodes.append({"type": "leaf", "name": Path(leaf).stem,
                      "path": str(rel).replace("\\", "/")})
    path.write_text(json.dumps({"name": name or path.stem, "nodes": nodes}),
                    encoding="utf-8")


def _group_file(groups: Path, name: str, nodes, marker: str | None = None) -> Path:
    blob: dict = {"name": name, "nodes": nodes}
    if marker is not None:
        blob["synthesised_by"] = marker
    f = groups / f"{name}.scriptreetree"
    f.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    return f


# --- Fix 1: push-back refuses to write a _groups source --------------------

def test_pushback_refuses_groups_source(tmp_path: Path) -> None:
    from scriptree.shell.merged_tree import (
        build_merged_tree, push_back_to_origins,
    )
    from scriptree.core.io import load_tree, save_tree
    from scriptree.core.model import TreeNode

    groups = tmp_path / "_groups"
    leaf = groups / "t.scriptree"
    _write_scriptree(leaf, "T")
    src = groups / "MSOffice.scriptreetree"
    _write_scriptreetree(src, [leaf], name="MSOffice")
    before = src.read_bytes()

    merged_path = build_merged_tree([str(src)])
    merged = load_tree(str(merged_path))
    # Simulate the merged tree nesting a sibling-group leaf into MSOffice's
    # folder (the exact gesture that used to persist a circular ref).
    sibling = tmp_path / "_groups" / "Demo.scriptreetree"
    _write_scriptreetree(sibling, [], name="Demo")
    for top in merged.nodes:
        top.children.append(TreeNode(
            type="leaf", name="Demo", path=str(sibling.resolve())))
        break
    save_tree(merged, str(merged_path))

    result = push_back_to_origins(merged_path)

    written_res = {Path(p).resolve() for p in result.written}
    skipped_res = {Path(s[0]).resolve() for s in result.skipped}
    assert src.resolve() not in written_res, "a _groups source must NOT be written"
    assert src.resolve() in skipped_res, "a _groups source must be skipped"
    assert src.read_bytes() == before, "the _groups file must be left untouched"


# --- Fix 2: prune self-heals illegal/residual group corruption -------------

def test_prune_deletes_illegal_unmarked_group(tmp_path: Path) -> None:
    from scriptree.core.categorize import prune_orphan_synthesised
    groups = tmp_path / "_groups"
    groups.mkdir()
    bad = _group_file(groups, "Demo", [
        {"type": "leaf", "path": "./deselect.scriptree"},
        {"type": "leaf", "path": "./MSOffice.scriptreetree"},  # illegal cross-ref
    ])  # NOTE: no synthesised_by marker (push-back stripped it)
    deleted = prune_orphan_synthesised(groups, keep_paths=set())
    assert bad in deleted
    assert not bad.exists(), "marker-stripped circular-ref residue must be reclaimed"


def test_prune_deletes_illegal_ref_nested_in_folder(tmp_path: Path) -> None:
    from scriptree.core.categorize import prune_orphan_synthesised
    groups = tmp_path / "_groups"
    groups.mkdir()
    bad = _group_file(groups, "MSOffice", [
        {"type": "folder", "name": "Excel", "children": [
            {"type": "leaf", "path": "./excel/a.scriptree"},
        ]},
        {"type": "leaf", "path": "./Demo.scriptreetree"},  # illegal, top-level
    ])
    deleted = prune_orphan_synthesised(groups, keep_paths=set())
    assert bad in deleted


def test_prune_keeps_valid_unmarked_user_tree(tmp_path: Path) -> None:
    """A structurally VALID tree (only .scriptree leaves) with no marker is
    user-authored — never delete it."""
    from scriptree.core.categorize import prune_orphan_synthesised
    groups = tmp_path / "_groups"
    groups.mkdir()
    ok = _group_file(groups, "MyTree", [
        {"type": "leaf", "path": "./a.scriptree"},
        {"type": "folder", "name": "sub", "children": [
            {"type": "leaf", "path": "./b.scriptree"}]},
    ])  # valid, no marker, no .scriptreetree leaf
    deleted = prune_orphan_synthesised(groups, keep_paths=set())
    assert ok not in deleted
    assert ok.exists(), "a valid unmarked (user-authored) tree must be preserved"


def test_prune_keeps_unmarked_hub_with_external_subtree_ref(tmp_path: Path) -> None:
    """a104 review #1: a marker-less hub referencing an EXTERNAL sub-tree (a
    legitimate node type, NOT a same-dir sibling-group cross-ref) must be
    PRESERVED — only same-dir sibling refs are corruption."""
    from scriptree.core.categorize import prune_orphan_synthesised
    groups = tmp_path / "_groups"
    groups.mkdir()
    hub = _group_file(groups, "MyHub", [
        {"type": "leaf", "path": "./tool.scriptree"},
        {"type": "leaf", "path": "../shared/kit.scriptreetree"},  # external sub-tree
    ])  # no marker
    deleted = prune_orphan_synthesised(groups, keep_paths=set())
    assert hub not in deleted
    assert hub.exists(), "external sub-tree ref is legitimate, must be preserved"


def test_prune_keeps_unmarked_hub_with_nested_subtree_ref(tmp_path: Path) -> None:
    """A marker-less hub referencing a NESTED sub-tree (under a sub-dir of
    _groups, not a direct sibling) must also be preserved."""
    from scriptree.core.categorize import prune_orphan_synthesised
    groups = tmp_path / "_groups"
    groups.mkdir()
    hub = _group_file(groups, "MyHub", [
        {"type": "leaf", "path": "./sub/kit.scriptreetree"},  # nested, not sibling
    ])
    deleted = prune_orphan_synthesised(groups, keep_paths=set())
    assert hub not in deleted
    assert hub.exists()


def test_prune_keeps_marked_synth_group_of_subtrees_when_kept(tmp_path: Path) -> None:
    """a104 review #2: a legitimately synthesised group built from categorised
    SUB-TREES carries .scriptreetree leaves — it must survive prune when kept
    (the 'subtree leaf == corrupt' invariant is false)."""
    from scriptree.core.categorize import prune_orphan_synthesised
    groups = tmp_path / "_groups"
    groups.mkdir()
    g = _group_file(groups, "Office", [
        {"type": "leaf", "path": "../trees/alpha.scriptreetree", "name": "alpha"},
        {"type": "leaf", "path": "../trees/beta.scriptreetree", "name": "beta"},
    ], marker="scriptree-auto-organise/1")
    deleted = prune_orphan_synthesised(groups, keep_paths={g.resolve()})
    assert g not in deleted
    assert g.exists()


def test_prune_still_deletes_marked_orphan(tmp_path: Path) -> None:
    """Regression: the original marker-based orphan delete still works."""
    from scriptree.core.categorize import prune_orphan_synthesised
    groups = tmp_path / "_groups"
    groups.mkdir()
    orphan = _group_file(groups, "Old", [
        {"type": "leaf", "path": "./a.scriptree"}],
        marker="scriptree-auto-organise/1")
    deleted = prune_orphan_synthesised(groups, keep_paths=set())
    assert orphan in deleted


# --- a105: save_tree write-chokepoint strips sibling-group cross-refs --------

def test_save_tree_strips_sibling_group_ref_in_groups(tmp_path: Path) -> None:
    """a105: writing a `_groups` file via save_tree must DROP any same-dir
    sibling-group cross-ref (the circular reference), whatever the caller —
    while keeping the legit tools."""
    from scriptree.core.io import save_tree, load_tree
    from scriptree.core.model import TreeDef, TreeNode
    groups = tmp_path / "_groups"
    groups.mkdir()
    t = TreeDef(name="Demo", nodes=[
        TreeNode(type="leaf", path="C:/apps/tool.scriptree"),       # external tool
        TreeNode(type="leaf", path="./MSOffice.scriptreetree"),     # sibling ref → drop
        TreeNode(type="folder", name="Sub", children=[
            TreeNode(type="leaf", path="./Other.scriptreetree"),    # nested sibling → drop
            TreeNode(type="leaf", path="C:/apps/t2.scriptree"),     # external tool
        ]),
    ])
    f = groups / "Demo.scriptreetree"
    save_tree(t, f)
    paths: list[str] = []

    def _walk(ns):
        for n in ns:
            if n.type == "folder":
                _walk(n.children)
            elif n.path:
                paths.append(n.path)

    _walk(load_tree(f).nodes)
    assert "./MSOffice.scriptreetree" not in paths, "sibling cross-ref not stripped"
    assert "./Other.scriptreetree" not in paths, "nested sibling cross-ref not stripped"
    assert any(p.endswith("tool.scriptree") for p in paths)
    assert any(p.endswith("t2.scriptree") for p in paths)


def test_save_tree_keeps_external_subtree_ref_in_groups(tmp_path: Path) -> None:
    """a105: an EXTERNAL/nested .scriptreetree ref (a legit node type, e.g. a
    group built from categorised sub-trees) is preserved by the chokepoint."""
    from scriptree.core.io import save_tree, load_tree
    from scriptree.core.model import TreeDef, TreeNode
    groups = tmp_path / "_groups"
    groups.mkdir()
    t = TreeDef(name="MSOffice", nodes=[
        TreeNode(type="leaf", path="../trees/OutlookMigration.scriptreetree"),
    ])
    f = groups / "MSOffice.scriptreetree"
    save_tree(t, f)
    r = load_tree(f)
    assert any(n.path and n.path.endswith("OutlookMigration.scriptreetree")
               for n in r.nodes), "external sub-tree ref must be preserved"


def test_save_tree_outside_groups_untouched(tmp_path: Path) -> None:
    """a105: the chokepoint is a no-op for files NOT under `_groups` — a normal
    tree's subtree ref is preserved."""
    from scriptree.core.io import save_tree, load_tree
    from scriptree.core.model import TreeDef, TreeNode
    t = TreeDef(name="Hub", nodes=[
        TreeNode(type="leaf", path="./kit.scriptreetree"),
    ])
    f = tmp_path / "hub.scriptreetree"
    save_tree(t, f)
    r = load_tree(f)
    assert any(n.path == "./kit.scriptreetree" for n in r.nodes)


def test_prune_never_deletes_a_kept_file(tmp_path: Path) -> None:
    """A file the synth pass just (re)wrote is in keep_paths and must never be
    deleted — even if it transiently still looks illegal on disk."""
    from scriptree.core.categorize import prune_orphan_synthesised
    groups = tmp_path / "_groups"
    groups.mkdir()
    kept = _group_file(groups, "MSOffice", [
        {"type": "leaf", "path": "./Demo.scriptreetree"}])  # illegal-looking
    deleted = prune_orphan_synthesised(groups, keep_paths={kept.resolve()})
    assert kept not in deleted
    assert kept.exists()
