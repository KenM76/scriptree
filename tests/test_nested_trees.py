"""Tests for nested .scriptreetree support and circular reference detection.

A .scriptreetree can contain leaf nodes pointing to other .scriptreetree
files. Those subtree references are expanded inline in the launcher and
serialized back as ordinary leaf nodes. Circular references (A -> B -> A)
are detected and blocked at add-time.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.io import (  # noqa: E402
    check_circular_tree_refs,
    collect_scriptreetree_refs,
    load_tree,
    save_tool,
)
from scriptree.core.model import (  # noqa: E402
    ParamDef,
    ToolDef,
    TreeDef,
    TreeNode,
)
from scriptree.ui.tree_view import (  # noqa: E402
    TreeLauncherView,
    _is_folder,
    _is_leaf,
    _is_subtree,
)


# --- helpers ----------------------------------------------------------------

def _write_tool(path: Path, name: str) -> None:
    tool = ToolDef(
        name=name,
        executable="/bin/echo",
        params=[ParamDef(id="msg")],
        argument_template=["{msg}"],
    )
    save_tool(tool, path)


def _write_tree(path: Path, name: str, nodes: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {"schema_version": 1, "name": name, "nodes": nodes},
            indent=2,
        ),
        encoding="utf-8",
    )


# --- fixtures ---------------------------------------------------------------

@pytest.fixture
def nested_tree_dir(tmp_path: Path) -> Path:
    """Create a directory with two .scriptreetree files, one referencing the other.

    Layout:
        tmp_path/
            alpha.scriptree
            beta.scriptree
            inner.scriptreetree  (contains alpha)
            outer.scriptreetree  (contains inner.scriptreetree + beta)
    """
    _write_tool(tmp_path / "alpha.scriptree", "alpha")
    _write_tool(tmp_path / "beta.scriptree", "beta")

    _write_tree(
        tmp_path / "inner.scriptreetree",
        "inner tree",
        [{"type": "leaf", "path": "./alpha.scriptree"}],
    )
    _write_tree(
        tmp_path / "outer.scriptreetree",
        "outer tree",
        [
            {"type": "leaf", "path": "./inner.scriptreetree"},
            {"type": "leaf", "path": "./beta.scriptree"},
        ],
    )
    return tmp_path


@pytest.fixture
def circular_dir(tmp_path: Path) -> Path:
    """Create two .scriptreetree files that reference each other (A -> B -> A)."""
    _write_tool(tmp_path / "tool.scriptree", "tool")

    _write_tree(
        tmp_path / "a.scriptreetree",
        "tree A",
        [
            {"type": "leaf", "path": "./b.scriptreetree"},
            {"type": "leaf", "path": "./tool.scriptree"},
        ],
    )
    _write_tree(
        tmp_path / "b.scriptreetree",
        "tree B",
        [
            {"type": "leaf", "path": "./a.scriptreetree"},
        ],
    )
    return tmp_path


# --- IO: collect_scriptreetree_refs ----------------------------------------

class TestCollectRefs:
    def test_finds_scriptreetree_refs(self, nested_tree_dir: Path) -> None:
        tree = load_tree(nested_tree_dir / "outer.scriptreetree")
        refs = collect_scriptreetree_refs(
            tree, nested_tree_dir / "outer.scriptreetree"
        )
        assert len(refs) == 1
        assert refs[0] == str(
            (nested_tree_dir / "inner.scriptreetree").resolve()
        )

    def test_ignores_scriptree_refs(self, nested_tree_dir: Path) -> None:
        tree = load_tree(nested_tree_dir / "inner.scriptreetree")
        refs = collect_scriptreetree_refs(
            tree, nested_tree_dir / "inner.scriptreetree"
        )
        assert refs == []


# --- IO: check_circular_tree_refs ------------------------------------------

class TestCircularRefDetection:
    def test_no_cycle_returns_none(self, nested_tree_dir: Path) -> None:
        result = check_circular_tree_refs(
            nested_tree_dir / "outer.scriptreetree"
        )
        assert result is None

    def test_cycle_returns_chain(self, circular_dir: Path) -> None:
        result = check_circular_tree_refs(
            circular_dir / "a.scriptreetree"
        )
        assert result is not None
        # The chain must include both files.
        resolved_a = str((circular_dir / "a.scriptreetree").resolve())
        resolved_b = str((circular_dir / "b.scriptreetree").resolve())
        assert resolved_a in result
        assert resolved_b in result

    def test_self_referencing_tree(self, tmp_path: Path) -> None:
        _write_tree(
            tmp_path / "self.scriptreetree",
            "self-ref",
            [{"type": "leaf", "path": "./self.scriptreetree"}],
        )
        result = check_circular_tree_refs(
            tmp_path / "self.scriptreetree"
        )
        assert result is not None

    def test_missing_ref_is_not_cycle(self, tmp_path: Path) -> None:
        _write_tree(
            tmp_path / "tree.scriptreetree",
            "missing ref",
            [{"type": "leaf", "path": "./nonexistent.scriptreetree"}],
        )
        result = check_circular_tree_refs(
            tmp_path / "tree.scriptreetree"
        )
        assert result is None


# --- tree_view: subtree display --------------------------------------------

class TestSubtreeDisplay:
    def test_subtree_item_is_created(self, nested_tree_dir: Path) -> None:
        view = TreeLauncherView()
        view.load(str(nested_tree_dir / "outer.scriptreetree"))
        tw = view._tree_widget
        # outer has 2 top-level items: inner (subtree) and beta (leaf)
        assert tw.topLevelItemCount() == 2
        inner_item = tw.topLevelItem(0)
        beta_item = tw.topLevelItem(1)
        assert _is_subtree(inner_item)
        assert _is_leaf(beta_item)

    def test_subtree_children_are_loaded(
        self, nested_tree_dir: Path
    ) -> None:
        view = TreeLauncherView()
        view.load(str(nested_tree_dir / "outer.scriptreetree"))
        inner_item = view._tree_widget.topLevelItem(0)
        # The inner tree has one leaf (alpha).
        assert inner_item.childCount() == 1
        child = inner_item.child(0)
        assert _is_leaf(child)
        assert "alpha" in child.data(0, 0x0100).lower()  # UserRole path

    def test_subtree_children_resolve_relative_to_subtree_file(
        self, nested_tree_dir: Path
    ) -> None:
        """Paths in the nested tree should resolve relative to the nested
        tree file's directory, not the parent tree's directory."""
        view = TreeLauncherView()
        view.load(str(nested_tree_dir / "outer.scriptreetree"))
        inner_item = view._tree_widget.topLevelItem(0)
        child = inner_item.child(0)
        from PySide6.QtCore import Qt

        stored = child.data(0, Qt.ItemDataRole.UserRole)
        expected = str((nested_tree_dir / "alpha.scriptree").resolve())
        assert str(Path(stored).resolve()) == expected

    def test_subtree_not_editable(self, nested_tree_dir: Path) -> None:
        view = TreeLauncherView()
        view.load(str(nested_tree_dir / "outer.scriptreetree"))
        inner_item = view._tree_widget.topLevelItem(0)
        from PySide6.QtCore import Qt

        flags = inner_item.flags()
        assert not (flags & Qt.ItemFlag.ItemIsEditable)
        assert not (flags & Qt.ItemFlag.ItemIsDropEnabled)


# --- tree_view: subtree save round-trip ------------------------------------

class TestSubtreeSaveRoundTrip:
    def test_subtree_saved_as_leaf_node(self, nested_tree_dir: Path) -> None:
        tree_path = nested_tree_dir / "outer.scriptreetree"
        view = TreeLauncherView()
        view.load(str(tree_path))
        # Save and reload.
        view._save_tree()
        reloaded = load_tree(tree_path)
        # The inner.scriptreetree reference is saved as type=leaf.
        subtree_nodes = [
            n
            for n in reloaded.nodes
            if n.type == "leaf"
            and n.path
            and n.path.endswith(".scriptreetree")
        ]
        assert len(subtree_nodes) == 1
        assert subtree_nodes[0].path == "./inner.scriptreetree"

    def test_drop_subtree_and_save(self, nested_tree_dir: Path) -> None:
        tree_path = nested_tree_dir / "outer.scriptreetree"
        view = TreeLauncherView()
        view.load(str(tree_path))

        # Create another subtree file and drop it.
        _write_tool(nested_tree_dir / "gamma.scriptree", "gamma")
        _write_tree(
            nested_tree_dir / "another.scriptreetree",
            "another",
            [{"type": "leaf", "path": "./gamma.scriptree"}],
        )
        view._on_file_dropped(
            str(nested_tree_dir / "another.scriptreetree"),
            target_item=None,
        )
        view._save_tree()

        reloaded = load_tree(tree_path)
        tree_refs = [
            n.path
            for n in reloaded.nodes
            if n.type == "leaf"
            and n.path
            and n.path.endswith(".scriptreetree")
        ]
        assert "./inner.scriptreetree" in tree_refs
        assert "./another.scriptreetree" in tree_refs


# --- tree_view: circular reference blocking --------------------------------

class TestCircularRefBlocking:
    def test_cannot_add_self(self, nested_tree_dir: Path) -> None:
        tree_path = nested_tree_dir / "outer.scriptreetree"
        view = TreeLauncherView()
        view.load(str(tree_path))
        # _check_no_cycle should block adding the tree file to itself.
        assert view._check_no_cycle(str(tree_path)) is False

    def test_can_add_non_circular(self, nested_tree_dir: Path) -> None:
        tree_path = nested_tree_dir / "outer.scriptreetree"
        view = TreeLauncherView()
        view.load(str(tree_path))
        # Adding a non-circular subtree should pass.
        _write_tree(
            nested_tree_dir / "safe.scriptreetree",
            "safe",
            [{"type": "leaf", "path": "./alpha.scriptree"}],
        )
        assert view._check_no_cycle(str(nested_tree_dir / "safe.scriptreetree")) is True

    def test_scriptree_always_passes(self, nested_tree_dir: Path) -> None:
        tree_path = nested_tree_dir / "outer.scriptreetree"
        view = TreeLauncherView()
        view.load(str(tree_path))
        # .scriptree files always pass the cycle check.
        assert view._check_no_cycle(str(nested_tree_dir / "alpha.scriptree")) is True

    def test_circular_ref_blocked(self, circular_dir: Path) -> None:
        """Loading a.scriptreetree and trying to add b.scriptreetree
        (which references a.scriptreetree) should be blocked."""
        view = TreeLauncherView()
        view.load(str(circular_dir / "a.scriptreetree"))
        # b references a, which would create a cycle.
        assert view._check_no_cycle(str(circular_dir / "b.scriptreetree")) is False

    def test_circular_tree_loads_without_crash(
        self, circular_dir: Path
    ) -> None:
        """Loading a circular tree should not crash — the cycle is
        detected at expand time and shown as an error child."""
        view = TreeLauncherView()
        # This should NOT infinite-loop or crash.
        view.load(str(circular_dir / "a.scriptreetree"))
        tw = view._tree_widget
        # a has 2 items: b subtree + tool leaf.
        assert tw.topLevelItemCount() == 2
        b_item = tw.topLevelItem(0)
        assert _is_subtree(b_item)
        # b contains one item: a subtree.
        assert b_item.childCount() == 1
        a_nested = b_item.child(0)
        assert _is_subtree(a_nested)
        # a_nested would normally have 2 children (b subtree + tool),
        # but the circular reference guard blocks the entire expansion
        # and shows a single error child instead.
        assert a_nested.childCount() == 1
        assert "circular" in a_nested.child(0).text(0).lower()


# --- tree_view: double-click subtree refreshes -----------------------------

class TestSubtreeActivation:
    def test_double_click_subtree_refreshes(
        self, nested_tree_dir: Path
    ) -> None:
        view = TreeLauncherView()
        view.load(str(nested_tree_dir / "outer.scriptreetree"))
        inner_item = view._tree_widget.topLevelItem(0)
        assert inner_item.childCount() == 1
        # Double-click refreshes (reload from disk).
        view._on_item_activated(inner_item, 0)
        assert inner_item.childCount() == 1  # still 1 child

    def test_subtree_shows_error_on_missing_file(
        self, tmp_path: Path
    ) -> None:
        _write_tree(
            tmp_path / "parent.scriptreetree",
            "parent",
            [{"type": "leaf", "path": "./missing.scriptreetree"}],
        )
        view = TreeLauncherView()
        view.load(str(tmp_path / "parent.scriptreetree"))
        subtree_item = view._tree_widget.topLevelItem(0)
        assert _is_subtree(subtree_item)
        # Should have an error child instead of crashing.
        assert subtree_item.childCount() == 1
        assert "load error" in subtree_item.child(0).text(0).lower()


# --- deep nesting ----------------------------------------------------------

class TestDeepNesting:
    def test_three_level_nesting(self, tmp_path: Path) -> None:
        """A -> B -> C -> tool. All expand correctly."""
        _write_tool(tmp_path / "tool.scriptree", "deep-tool")
        _write_tree(
            tmp_path / "c.scriptreetree",
            "C",
            [{"type": "leaf", "path": "./tool.scriptree"}],
        )
        _write_tree(
            tmp_path / "b.scriptreetree",
            "B",
            [{"type": "leaf", "path": "./c.scriptreetree"}],
        )
        _write_tree(
            tmp_path / "a.scriptreetree",
            "A",
            [{"type": "leaf", "path": "./b.scriptreetree"}],
        )

        view = TreeLauncherView()
        view.load(str(tmp_path / "a.scriptreetree"))

        # a has 1 child (b subtree)
        tw = view._tree_widget
        assert tw.topLevelItemCount() == 1
        b_item = tw.topLevelItem(0)
        assert _is_subtree(b_item)
        # b has 1 child (c subtree)
        assert b_item.childCount() == 1
        c_item = b_item.child(0)
        assert _is_subtree(c_item)
        # c has 1 child (tool leaf)
        assert c_item.childCount() == 1
        tool_item = c_item.child(0)
        assert _is_leaf(tool_item)
