"""v0.8.0a91 — canonical JSON field order in the writers.

Hand-editing ergonomics: the emitted key order runs stable-at-top →
most-edited-at-bottom, with ``category`` lifted near the top and THE FORM
(``params`` for a tool, ``nodes`` for a tree) kept dead last so a person
editing the JSON can Ctrl+End straight to it.  Key order is cosmetic (the
loader is order-independent) — these tests pin it so it doesn't silently drift,
and re-assert that the reorder changed only ORDER, never the key set / values
(byte-identity via omit-when-empty is preserved).
"""
from __future__ import annotations

from scriptree.core.io import (
    tool_from_dict,
    tool_to_dict,
    tree_from_dict,
    tree_to_dict,
)
from scriptree.core.model import ParamDef, ToolDef, TreeDef, TreeNode


def test_tool_category_near_top_form_at_bottom() -> None:
    t = ToolDef(
        name="d", executable="py", argument_template=["{x}"],
        params=[ParamDef(id="x", label="X")], category="A/B",
    )
    keys = list(tool_to_dict(t).keys())
    assert keys[0] == "schema_version"
    assert keys[1] == "name"
    assert keys[2] == "category"                 # near the top
    assert keys[-1] == "params"                  # most-edited, dead last
    assert keys[-2] == "argument_template"       # kept right above params
    assert keys.index("category") < keys.index("executable") < keys.index("params")


def test_tree_category_near_top_nodes_at_bottom() -> None:
    tr = TreeDef(
        name="t", category="X/Y",
        nodes=[TreeNode(type="leaf", path="a.scriptree")],
    )
    keys = list(tree_to_dict(tr).keys())
    assert keys[0] == "schema_version"
    assert keys[2] == "category"
    assert keys[-1] == "nodes"


def test_category_omitted_when_empty() -> None:
    t = ToolDef(name="d", executable="py", argument_template=[], params=[])
    keys = list(tool_to_dict(t).keys())
    assert "category" not in keys                # omit-when-empty preserved
    assert keys[-1] == "params"


def test_reorder_changes_only_order_not_content() -> None:
    t = ToolDef(
        name="d", executable="py", argument_template=["{x}"],
        params=[ParamDef(id="x", label="X")], category="A/B",
        env={"K": "V"}, interactive=True,
    )
    d = tool_to_dict(t)
    # dict equality is order-independent: round-trip stays stable
    assert tool_to_dict(tool_from_dict(d)) == d
    tr = TreeDef(
        name="t", category="X",
        nodes=[TreeNode(type="folder", name="F", children=[
            TreeNode(type="leaf", path="a.scriptree")])],
        folder_layout="tabs",
    )
    td = tree_to_dict(tr)
    assert tree_to_dict(tree_from_dict(td)) == td
