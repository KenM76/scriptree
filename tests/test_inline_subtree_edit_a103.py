"""v0.8.0a103 — inline subtree edit (write-back to the referenced file).

The tree editor lets you EXPAND a linked-subtree row (its referenced
``.scriptreetree``'s nodes load as children) and edit those children *in place* —
drag a tool in, remove one, rename a folder.  Those edits belong to the
*referenced* file, not to the tree being saved (whose own serialization records
the subtree only as a one-line leaf reference).  On Save, ``_write_back_subtrees``
walks the loaded tree and rewrites each CHANGED subtree's file (preserving its
top-level metadata, leaf paths relativised against the subtree's OWN directory).

Guards under test:
  * an UNCHANGED subtree is never rewritten (no churn);
  * the parent file keeps the subtree as a one-line ref (NOT flattened/inlined);
  * a subtree that didn't expand cleanly (``_ROLE_EXPAND_OK`` False) is skipped;
  * a synthesised ``_groups/`` subtree is never written back here (a98/a102 own it);
  * write-back relativises new leaf paths against the SUBTREE's dir.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.io import load_tree, save_tool, save_tree  # noqa: E402
from scriptree.core.model import ToolDef, TreeDef, TreeNode  # noqa: E402
from scriptree.ui.tree_view import (  # noqa: E402
    TreeLauncherView,
    _ROLE_EXPAND_OK,
    _is_folder,
    _is_subtree,
)


def _tool(p: Path, name: str) -> Path:
    save_tool(ToolDef(name=name, executable="python"), p)
    return p


def _find_subtree_row(view: TreeLauncherView):
    """Return the first SUBTREE row under the editor's ROOT row."""
    root = view._tree_widget.topLevelItem(0)
    assert root is not None
    for i in range(root.childCount()):
        c = root.child(i)
        if _is_subtree(c):
            return c
    raise AssertionError("no subtree row found")


def _all_subtree_rows(view: TreeLauncherView) -> list:
    """Every SUBTREE row anywhere under the editor's ROOT row (recursive)."""
    out: list = []

    def _walk(item) -> None:
        for i in range(item.childCount()):
            c = item.child(i)
            if _is_subtree(c):
                out.append(c)
                _walk(c)
            elif _is_folder(c):
                _walk(c)

    root = view._tree_widget.topLevelItem(0)
    if root is not None:
        _walk(root)
    return out


def _make_parent_with_subtree(tmp_path: Path) -> tuple[Path, Path]:
    """A parent .scriptreetree referencing a subtree .scriptreetree in dir ``sub``.

    Returns (parent_path, subtree_path).  The subtree holds one folder with one
    leaf, plus one top-level leaf — both pointing at tools in the subtree's dir
    (relative ``./`` paths, mirroring real authored trees like ffmpeg).
    """
    sub = tmp_path / "sub"
    sub.mkdir()
    _tool(sub / "a.scriptree", "Tool A")
    _tool(sub / "b.scriptree", "Tool B")
    subtree = sub / "kit.scriptreetree"
    save_tree(TreeDef(name="Kit", nodes=[
        TreeNode(type="folder", name="Group", children=[
            TreeNode(type="leaf", path="./a.scriptree", display_name="Tool A"),
        ]),
        TreeNode(type="leaf", path="./b.scriptree", display_name="Tool B"),
    ]), subtree)

    parent = tmp_path / "parent.scriptreetree"
    save_tree(TreeDef(name="Parent", nodes=[
        TreeNode(type="leaf", path="./sub/kit.scriptreetree"),
    ]), parent)
    return parent, subtree


# --- unchanged-skip (no churn) --------------------------------------------

def test_unchanged_subtree_not_rewritten(tmp_path: Path) -> None:
    parent, subtree = _make_parent_with_subtree(tmp_path)
    before = subtree.read_bytes()
    view = TreeLauncherView()
    view.load(str(parent))
    # Save with NO edits — the subtree round-trips identically → not rewritten.
    assert view._save_tree() is True
    assert subtree.read_bytes() == before, "unedited subtree must not be churned"


# --- the core feature: edit in place + write back -------------------------

def test_inline_add_writes_back_to_subtree(tmp_path: Path) -> None:
    parent, subtree = _make_parent_with_subtree(tmp_path)
    # A new tool living in the subtree's own directory.
    new_tool = _tool(subtree.parent / "c.scriptree", "Tool C")

    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)
    # Simulate a drag-in: append a leaf child to the expanded subtree row.
    leaf = view._new_leaf_item(str(new_tool), display_name="Tool C")
    st.addChild(leaf)

    assert view._save_tree() is True

    reloaded = load_tree(str(subtree))
    paths = [n.path for n in reloaded.nodes if n.type == "leaf"]
    # The new leaf was appended, relativised against the SUBTREE's dir.
    assert "./c.scriptree" in paths
    # The pre-existing structure survived (folder + its leaf + the top leaf).
    assert any(n.type == "folder" and n.name == "Group" for n in reloaded.nodes)
    assert "./b.scriptree" in paths


def test_external_drop_onto_subtree_writes_back(tmp_path: Path) -> None:
    """Dropping a .scriptree from Explorer ONTO a subtree row (external drop via
    ``_on_file_dropped``) adds it as a CHILD of the subtree and writes back —
    matching the internal-drag behaviour (a103 consistency)."""
    parent, subtree = _make_parent_with_subtree(tmp_path)
    new_tool = _tool(subtree.parent / "c.scriptree", "Tool C")
    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)
    # Simulate an Explorer drop landing ON the subtree row.
    view._on_file_dropped(str(new_tool), target_item=st)
    assert view._save_tree() is True

    reloaded = load_tree(str(subtree))
    paths = [n.path for n in reloaded.nodes if n.type == "leaf"]
    assert "./c.scriptree" in paths


def test_parent_keeps_subtree_as_reference_not_flattened(tmp_path: Path) -> None:
    """Editing a subtree's contents must NOT inline them into the parent file —
    the parent keeps the one-line leaf reference (the a99/a100 anti-flatten rule)."""
    parent, subtree = _make_parent_with_subtree(tmp_path)
    new_tool = _tool(subtree.parent / "c.scriptree", "Tool C")
    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)
    st.addChild(view._new_leaf_item(str(new_tool), display_name="Tool C"))
    assert view._save_tree() is True

    parent_def = load_tree(str(parent))
    # Exactly one node, a leaf pointing at the subtree file — NOT a folder of
    # inlined tools.
    assert len(parent_def.nodes) == 1
    only = parent_def.nodes[0]
    assert only.type == "leaf"
    assert only.path.replace("\\", "/").endswith("kit.scriptreetree")


def test_inline_remove_writes_back(tmp_path: Path) -> None:
    parent, subtree = _make_parent_with_subtree(tmp_path)
    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)
    # Find and remove the top-level "b.scriptree" leaf from the expanded subtree.
    from scriptree.ui.tree_view import _ROLE_PATH
    removed = False
    for i in range(st.childCount()):
        c = st.child(i)
        p = c.data(0, _ROLE_PATH)
        if p and Path(p).name == "b.scriptree":
            st.removeChild(c)
            removed = True
            break
    assert removed
    assert view._save_tree() is True

    reloaded = load_tree(str(subtree))
    leaf_paths = [n.path for n in reloaded.nodes if n.type == "leaf"]
    assert "./b.scriptree" not in leaf_paths  # the removal stuck
    # The folder + its leaf are untouched.
    assert any(n.type == "folder" for n in reloaded.nodes)


# --- guards ----------------------------------------------------------------

def test_expand_failed_subtree_not_written(tmp_path: Path) -> None:
    """A subtree that didn't expand cleanly (circular / load error) carries
    ``_ROLE_EXPAND_OK`` False and must NEVER be written back."""
    parent, subtree = _make_parent_with_subtree(tmp_path)
    before = subtree.read_bytes()
    new_tool = _tool(subtree.parent / "c.scriptree", "Tool C")
    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)
    st.setData(0, _ROLE_EXPAND_OK, False)         # pretend it failed to expand
    st.addChild(view._new_leaf_item(str(new_tool), display_name="Tool C"))
    assert view._save_tree() is True
    assert subtree.read_bytes() == before, "expand-failed subtree must be skipped"


def test_groups_subtree_not_written(tmp_path: Path) -> None:
    """A synthesised ``_groups/`` subtree is regenerated from tool categories
    (a98/a102) — inline write-back must skip it even when its children differ."""
    groups = tmp_path / "_groups"
    groups.mkdir()
    _tool(groups / "x.scriptree", "X")
    gtree = groups / "MSOffice.scriptreetree"
    save_tree(TreeDef(name="MSOffice", nodes=[
        TreeNode(type="leaf", path="./x.scriptree", display_name="X"),
    ]), gtree)
    before = gtree.read_bytes()

    parent = tmp_path / "parent.scriptreetree"
    save_tree(TreeDef(name="Parent", nodes=[
        TreeNode(type="leaf", path="./_groups/MSOffice.scriptreetree"),
    ]), parent)
    new_tool = _tool(tmp_path / "y.scriptree", "Y")

    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)
    st.addChild(view._new_leaf_item(str(new_tool), display_name="Y"))
    assert view._save_tree() is True
    assert gtree.read_bytes() == before, "_groups subtree must never be written here"


def test_writeback_returns_only_changed_paths(tmp_path: Path) -> None:
    """``_write_back_subtrees`` returns exactly the files it rewrote."""
    parent, subtree = _make_parent_with_subtree(tmp_path)
    new_tool = _tool(subtree.parent / "c.scriptree", "Tool C")
    view = TreeLauncherView()
    view.load(str(parent))
    # No edit yet → nothing written.
    assert view._write_back_subtrees() == []
    # Edit → exactly the one subtree path returned.
    st = _find_subtree_row(view)
    st.addChild(view._new_leaf_item(str(new_tool), display_name="Tool C"))
    written = view._write_back_subtrees()
    assert len(written) == 1
    assert Path(written[0]).name == "kit.scriptreetree"


# ===========================================================================
# a103 ADVERSARIAL-REVIEW REGRESSIONS — the lossy round-trip + false-diff churn
# the review caught (10/10 confirmed).  Each test FAILS against the first-cut
# a103 and passes after the lossless-round-trip + churn-key + dedupe + drop-gate
# fixes.
# ===========================================================================

def _meta_subtree(tmp_path: Path) -> tuple[Path, Path]:
    """Parent → kit.scriptreetree whose nodes carry the FULL metadata surface:
    a folder with display_name + icon triplet, holding a leaf with its OWN icon
    triplet, plus a top-level leaf.  Returns (parent, subtree)."""
    sub = tmp_path / "sub"
    sub.mkdir()
    _tool(sub / "a.scriptree", "Tool A")
    _tool(sub / "b.scriptree", "Tool B")
    subtree = sub / "kit.scriptreetree"
    save_tree(TreeDef(name="Kit", nodes=[
        TreeNode(type="folder", name="Group", display_name="Pretty Group",
                 icon="build", icon_data="QUJD", icon_format="png", children=[
                     TreeNode(type="leaf", path="./a.scriptree",
                              display_name="Tool A", icon="run",
                              icon_data="WFla", icon_format="svg"),
                 ]),
        TreeNode(type="leaf", path="./b.scriptree", display_name="Tool B"),
    ]), subtree)
    parent = tmp_path / "parent.scriptreetree"
    save_tree(TreeDef(name="Parent", nodes=[
        TreeNode(type="leaf", path="./sub/kit.scriptreetree"),
    ]), parent)
    return parent, subtree


def test_metadata_bearing_subtree_not_churned_on_noop_save(tmp_path: Path) -> None:
    """REVIEW #1/#4/#5/#8 (HIGH): a folder display_name + per-node icon triplet
    must round-trip — a no-edit Save must NOT rewrite the subtree (no churn) and
    must NOT strip the metadata."""
    parent, subtree = _meta_subtree(tmp_path)
    before = subtree.read_bytes()
    view = TreeLauncherView()
    view.load(str(parent))
    assert view._save_tree() is True
    assert subtree.read_bytes() == before, "metadata subtree churned on no-op save"
    # Belt-and-suspenders: the metadata is intact on disk.
    reloaded = load_tree(str(subtree))
    folder = next(n for n in reloaded.nodes if n.type == "folder")
    assert folder.display_name == "Pretty Group"
    assert (folder.icon, folder.icon_data, folder.icon_format) == (
        "build", "QUJD", "png")
    inner = folder.children[0]
    assert (inner.icon, inner.icon_data, inner.icon_format) == (
        "run", "WFla", "svg")


def test_metadata_survives_a_real_edit(tmp_path: Path) -> None:
    """REVIEW #1 (edit path): after a genuine edit the OTHER nodes keep their
    icon/display_name metadata — write-back is lossless, not just skip-on-noop."""
    parent, subtree = _meta_subtree(tmp_path)
    new_tool = _tool(subtree.parent / "c.scriptree", "Tool C")
    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)
    st.addChild(view._new_leaf_item(str(new_tool), display_name="Tool C"))
    assert view._save_tree() is True
    reloaded = load_tree(str(subtree))
    folder = next(n for n in reloaded.nodes if n.type == "folder")
    assert folder.display_name == "Pretty Group"           # survived the edit
    assert folder.icon == "build"
    assert folder.children[0].icon == "run"                 # inner leaf icon kept
    leaf_paths = [n.path for n in reloaded.nodes if n.type == "leaf"]
    assert "./c.scriptree" in leaf_paths                    # the edit landed


def test_nested_subtree_ref_configuration_and_icon_preserved(tmp_path: Path) -> None:
    """REVIEW #2/#6 (HIGH/MED): a nested .scriptreetree leaf carrying
    configuration + an icon triplet must round-trip — no churn, no strip."""
    sub = tmp_path / "sub"
    sub.mkdir()
    # The innermost referenced tree (only needs to exist so labels load).
    save_tree(TreeDef(name="Inner", nodes=[]), sub / "inner.scriptreetree")
    kit = sub / "kit.scriptreetree"
    save_tree(TreeDef(name="Kit", nodes=[
        TreeNode(type="leaf", path="./inner.scriptreetree", display_name="Inner",
                 configuration="prod", icon="build", icon_data="QUJD",
                 icon_format="png"),
    ]), kit)
    before = kit.read_bytes()
    parent = tmp_path / "parent.scriptreetree"
    save_tree(TreeDef(name="Parent", nodes=[
        TreeNode(type="leaf", path="./sub/kit.scriptreetree"),
    ]), parent)

    view = TreeLauncherView()
    view.load(str(parent))
    assert view._save_tree() is True
    assert kit.read_bytes() == before, "nested-subtree-ref metadata churned"
    reloaded = load_tree(str(kit))
    inner = reloaded.nodes[0]
    assert inner.configuration == "prod"
    assert (inner.icon, inner.icon_data, inner.icon_format) == (
        "build", "QUJD", "png")


def test_bare_path_subtree_not_churned(tmp_path: Path) -> None:
    """REVIEW #3 (HIGH): a subtree storing BARE leaf paths (no ``./``) — like
    ScripTree's own shipped management tree — must NOT churn on a no-op Save."""
    sub = tmp_path / "sub"
    sub.mkdir()
    _tool(sub / "a.scriptree", "A")
    kit = sub / "kit.scriptreetree"
    # Bare path (no ./ prefix), written verbatim by save_tree.
    save_tree(TreeDef(name="Kit", nodes=[
        TreeNode(type="leaf", path="a.scriptree", display_name="A"),
    ]), kit)
    assert b'"a.scriptree"' in kit.read_bytes()   # confirm stored bare
    before = kit.read_bytes()
    parent = tmp_path / "parent.scriptreetree"
    save_tree(TreeDef(name="Parent", nodes=[
        TreeNode(type="leaf", path="./sub/kit.scriptreetree"),
    ]), parent)
    view = TreeLauncherView()
    view.load(str(parent))
    assert view._save_tree() is True
    assert kit.read_bytes() == before, "bare-path subtree churned on no-op save"


def test_backslash_path_subtree_not_churned(tmp_path: Path) -> None:
    """REVIEW #7 (MED): a subtree storing a Windows-backslash leaf path must NOT
    churn on a no-op Save (round-trip emits forward slashes)."""
    sub = tmp_path / "sub"
    sub.mkdir()
    nest = sub / "nest"
    nest.mkdir()
    _tool(nest / "n.scriptree", "N")
    kit = sub / "kit.scriptreetree"
    save_tree(TreeDef(name="Kit", nodes=[
        TreeNode(type="leaf", path=".\\nest\\n.scriptree", display_name="N"),
    ]), kit)
    before = kit.read_bytes()
    parent = tmp_path / "parent.scriptreetree"
    save_tree(TreeDef(name="Parent", nodes=[
        TreeNode(type="leaf", path="./sub/kit.scriptreetree"),
    ]), parent)
    view = TreeLauncherView()
    view.load(str(parent))
    assert view._save_tree() is True
    assert kit.read_bytes() == before, "backslash-path subtree churned on no-op save"


def test_duplicate_subtree_rows_edit_survives(tmp_path: Path) -> None:
    """REVIEW #9 (LOW): when the same subtree file is referenced by TWO rows,
    editing one and saving must not let the other (stale) row clobber the edit."""
    sub = tmp_path / "sub"
    sub.mkdir()
    _tool(sub / "a.scriptree", "A")
    _tool(sub / "b.scriptree", "B")
    new_tool = _tool(sub / "c.scriptree", "C")
    kit = sub / "kit.scriptreetree"
    save_tree(TreeDef(name="Kit", nodes=[
        TreeNode(type="leaf", path="./a.scriptree", display_name="A"),
        TreeNode(type="leaf", path="./b.scriptree", display_name="B"),
    ]), kit)
    # Parent references kit TWICE — once at top level, once inside a folder.
    parent = tmp_path / "parent.scriptreetree"
    save_tree(TreeDef(name="Parent", nodes=[
        TreeNode(type="leaf", path="./sub/kit.scriptreetree"),
        TreeNode(type="folder", name="Again", children=[
            TreeNode(type="leaf", path="./sub/kit.scriptreetree"),
        ]),
    ]), parent)

    view = TreeLauncherView()
    view.load(str(parent))
    rows = _all_subtree_rows(view)
    assert len(rows) == 2
    # Edit the FIRST-visited row (add Tool C).
    rows[0].addChild(view._new_leaf_item(str(new_tool), display_name="C"))
    assert view._save_tree() is True

    reloaded = load_tree(str(kit))
    leaf_paths = [n.path for n in reloaded.nodes if n.type == "leaf"]
    assert "./c.scriptree" in leaf_paths, "duplicate stale row clobbered the edit"


# ===========================================================================
# a103 SECOND-PASS review regressions — fallout from the lossless-round-trip fix
# (folder display_name now carried) + the drop-gate placeholder hole.
# ===========================================================================

def _consumer_label(node) -> str:
    """How every runtime consumer renders a folder label: display_name or name."""
    return (node.display_name or node.name or "")


def test_folder_rename_wins_over_display_name_subtree_path(tmp_path: Path) -> None:
    """REVIEW pass-2 #1 (HIGH regression): renaming a display_name-bearing folder
    in an expanded SUBTREE must take effect — the stale display_name must not
    shadow the rename (consumers show ``display_name or name``)."""
    parent, subtree = _meta_subtree(tmp_path)   # folder Group / display 'Pretty Group'
    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)
    folder = next(st.child(i) for i in range(st.childCount())
                  if _is_folder(st.child(i)))
    assert folder.text(0) == "Pretty Group"      # shown as display_name
    folder.setText(0, "Renamed")                  # user inline-renames it
    assert view._save_tree() is True
    reloaded = load_tree(str(subtree))
    f = next(n for n in reloaded.nodes if n.type == "folder")
    assert _consumer_label(f) == "Renamed", "rename shadowed by stale display_name"


def test_folder_rename_wins_over_display_name_parent_path(tmp_path: Path) -> None:
    """Same as above but the folder lives in the PARENT tree (parent-save path,
    _build_tree_def → _item_to_node)."""
    t = tmp_path / "tree.scriptreetree"
    _tool(tmp_path / "a.scriptree", "A")
    save_tree(TreeDef(name="T", nodes=[
        TreeNode(type="folder", name="Group", display_name="Pretty Group",
                 children=[TreeNode(type="leaf", path="./a.scriptree",
                                    display_name="A")]),
    ]), t)
    view = TreeLauncherView()
    view.load(str(t))
    root = view._tree_widget.topLevelItem(0)
    folder = next(root.child(i) for i in range(root.childCount())
                  if _is_folder(root.child(i)))
    assert folder.text(0) == "Pretty Group"
    folder.setText(0, "Renamed")
    assert view._save_tree() is True
    reloaded = load_tree(str(t))
    f = next(n for n in reloaded.nodes if n.type == "folder")
    assert _consumer_label(f) == "Renamed"


def test_untouched_display_named_folder_round_trips(tmp_path: Path) -> None:
    """An UNTOUCHED name+display_name folder must keep BOTH (the rename detection
    must not mistake an unedited folder for a rename)."""
    parent, subtree = _meta_subtree(tmp_path)
    before = subtree.read_bytes()
    view = TreeLauncherView()
    view.load(str(parent))
    assert view._save_tree() is True
    assert subtree.read_bytes() == before
    f = next(n for n in load_tree(str(subtree)).nodes if n.type == "folder")
    assert f.name == "Group" and f.display_name == "Pretty Group"


def test_empty_name_folder_with_display_name_not_churned(tmp_path: Path) -> None:
    """REVIEW pass-2 #2 (MED regression): a folder with name='' + display_name
    must NOT churn on a no-op Save nor have its name mutated to '(folder)'."""
    sub = tmp_path / "sub"
    sub.mkdir()
    _tool(sub / "a.scriptree", "A")
    kit = sub / "kit.scriptreetree"
    save_tree(TreeDef(name="Kit", nodes=[
        TreeNode(type="folder", name="", display_name="Shown",
                 children=[TreeNode(type="leaf", path="./a.scriptree",
                                    display_name="A")]),
    ]), kit)
    before = kit.read_bytes()
    parent = tmp_path / "parent.scriptreetree"
    save_tree(TreeDef(name="Parent", nodes=[
        TreeNode(type="leaf", path="./sub/kit.scriptreetree"),
    ]), parent)
    view = TreeLauncherView()
    view.load(str(parent))
    assert view._save_tree() is True
    assert kit.read_bytes() == before, "empty-name folder churned on no-op save"
    f = next(n for n in load_tree(str(kit)).nodes if n.type == "folder")
    assert f.name == "", "empty folder name mutated"
    assert f.display_name == "Shown"


def test_empty_name_folder_no_display_name_not_churned(tmp_path: Path) -> None:
    """A folder with name='' and NO display_name (shown as the '(folder)'
    placeholder) must round-trip name='' without mutating to '(folder)'."""
    sub = tmp_path / "sub"
    sub.mkdir()
    _tool(sub / "a.scriptree", "A")
    kit = sub / "kit.scriptreetree"
    save_tree(TreeDef(name="Kit", nodes=[
        TreeNode(type="folder", name="",
                 children=[TreeNode(type="leaf", path="./a.scriptree")]),
    ]), kit)
    before = kit.read_bytes()
    parent = tmp_path / "parent.scriptreetree"
    save_tree(TreeDef(name="Parent", nodes=[
        TreeNode(type="leaf", path="./sub/kit.scriptreetree"),
    ]), parent)
    view = TreeLauncherView()
    view.load(str(parent))
    assert view._save_tree() is True
    assert kit.read_bytes() == before
    f = next(n for n in load_tree(str(kit)).nodes if n.type == "folder")
    assert f.name == "", "empty folder name mutated to placeholder"


def test_drop_onto_load_error_placeholder_not_lost(tmp_path: Path) -> None:
    """REVIEW pass-2 #3 (HIGH, original not closed): an external drop onto the
    '(load error)' PLACEHOLDER child of a failed-expand subtree must fall through
    to the parent (saved), never vanish into neither file."""
    sub = tmp_path / "sub"
    sub.mkdir()
    broken = sub / "kit.scriptreetree"
    broken.write_text("{ not valid json", encoding="utf-8")
    parent = tmp_path / "parent.scriptreetree"
    save_tree(TreeDef(name="Parent", nodes=[
        TreeNode(type="leaf", path="./sub/kit.scriptreetree"),
    ]), parent)
    new_tool = _tool(tmp_path / "c.scriptree", "C")

    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)
    assert st.data(0, _ROLE_EXPAND_OK) is not True
    assert st.childCount() == 1                       # the (load error: …) stub
    placeholder = st.child(0)
    # Drop directly ONTO the placeholder stub.
    view._on_file_dropped(str(new_tool), target_item=placeholder)
    assert view._save_tree() is True
    parent_def = load_tree(str(parent))
    parent_leaf_paths = [n.path for n in parent_def.nodes if n.type == "leaf"]
    assert any(p.endswith("c.scriptree") for p in parent_leaf_paths), \
        "tool dropped on placeholder was lost (neither subtree nor parent)"


def test_sibling_drop_at_failed_subtree_placeholder_is_gated(tmp_path: Path) -> None:
    """REVIEW pass-3 (HIGH): an internal-drag Above/Below the '(load error)'
    placeholder would reparent the tool INTO the failed subtree (the
    placeholder's parent) — the gate must refuse it, and the rescue sweep must
    pull any stray that lands there back to a saved location."""
    from PySide6.QtWidgets import QAbstractItemView

    sub = tmp_path / "sub"
    sub.mkdir()
    broken = sub / "kit.scriptreetree"
    broken.write_text("{ not valid json", encoding="utf-8")
    parent = tmp_path / "parent.scriptreetree"
    save_tree(TreeDef(name="Parent", nodes=[
        TreeNode(type="leaf", path="./sub/kit.scriptreetree"),
    ]), parent)
    new_tool = _tool(tmp_path / "c.scriptree", "C")

    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)
    assert st.data(0, _ROLE_EXPAND_OK) is not True
    placeholder = st.child(0)
    tw = view._tree_widget

    # Gate: dropping Above/Below the placeholder (new parent = failed subtree)
    # is REFUSED; Above/Below the subtree ROW itself (new parent = root) is fine.
    above = QAbstractItemView.DropIndicatorPosition.AboveItem
    below = QAbstractItemView.DropIndicatorPosition.BelowItem
    assert tw._is_legal_drop_target(placeholder, above) is False
    assert tw._is_legal_drop_target(placeholder, below) is False
    assert tw._is_legal_drop_target(st, above) is True

    # Belt-and-suspenders: if a draggable node DOES land under the failed
    # subtree, the rescue sweep moves it out so it isn't lost on save.
    leaf = view._new_leaf_item(str(new_tool), display_name="C")
    st.addChild(leaf)
    tw._rescue_strays_from_unwritable_subtrees()
    tw._sweep_strays_under_root()
    # The stray is no longer under the failed subtree.
    assert all(not _is_subtree(st.child(i)) or st.child(i) is not leaf
               for i in range(st.childCount()))
    assert leaf.parent() is not st
    assert view._save_tree() is True
    parent_def = load_tree(str(parent))
    paths = [n.path for n in parent_def.nodes if n.type == "leaf"]
    assert any(p.endswith("c.scriptree") for p in paths), "rescued tool not saved"


# ===========================================================================
# a103 CONVERGENCE-check regressions — interactions the single-topology fixtures
# of passes 1-3 never combined.
# ===========================================================================

def _subtree_row_named(item, basename: str):
    """Find the subtree row under *item* whose referenced file ends in
    *basename* (recursing through folders + nested subtrees)."""
    from scriptree.ui.tree_view import _ROLE_SUBTREE
    for i in range(item.childCount()):
        c = item.child(i)
        if _is_subtree(c):
            sp = c.data(0, _ROLE_SUBTREE)
            if sp and str(sp).replace("\\", "/").endswith(basename):
                return c
            r = _subtree_row_named(c, basename)
            if r is not None:
                return r
        elif _is_folder(c):
            r = _subtree_row_named(c, basename)
            if r is not None:
                return r
    return None


def test_group_as_root_persists_member_subtree_edit(tmp_path: Path, monkeypatch) -> None:
    """CONVERGENCE #1 (HIGH): opening a ``_groups/`` auto-group AS the root and
    inline-editing a cleanly-expanded NON-group member subtree must persist — the
    synthesised-group save path previously returned before any write-back."""
    # The member tree (NOT under _groups), with one tool.
    kitdir = tmp_path / "kit"
    kitdir.mkdir()
    _tool(kitdir / "a.scriptree", "A")
    new_tool = _tool(kitdir / "c.scriptree", "C")
    kit = kitdir / "kit.scriptreetree"
    save_tree(TreeDef(name="Kit", nodes=[
        TreeNode(type="leaf", path="./a.scriptree", display_name="A"),
    ]), kit)
    # The synthesised group, opened AS root, referencing the member tree.
    groups = tmp_path / "_groups"
    groups.mkdir()
    group = groups / "Top.scriptreetree"
    save_tree(TreeDef(name="Top", nodes=[
        TreeNode(type="leaf", path="../kit/kit.scriptreetree"),
    ]), group)

    view = TreeLauncherView()
    view.load(str(group))
    assert view._is_synthesised_group() is True
    st = _find_subtree_row(view)            # the kit member row
    assert st.data(0, _ROLE_EXPAND_OK) is True
    st.addChild(view._new_leaf_item(str(new_tool), display_name="C"))
    # Silence the "Categories updated" dialog.
    import scriptree.ui.tree_view as tv
    monkeypatch.setattr(tv.QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))
    assert view._save_tree() is True

    reloaded = load_tree(str(kit))
    paths = [n.path for n in reloaded.nodes if n.type == "leaf"]
    assert "./c.scriptree" in paths, "member edit lost on the group save path"


def test_duplicate_row_nested_edit_not_lost(tmp_path: Path) -> None:
    """CONVERGENCE #2 (HIGH): when the same kit is referenced by two rows and the
    FIRST writes kit (its own edit) while a NESTED subtree is edited only through
    the SECOND row, the dedupe must still recurse into the second row so the
    nested edit reaches its file."""
    sub = tmp_path / "sub"
    sub.mkdir()
    _tool(sub / "a.scriptree", "A")
    _tool(sub / "b.scriptree", "B")
    x = _tool(sub / "x.scriptree", "X")
    y = _tool(sub / "y.scriptree", "Y")
    inner = sub / "inner.scriptreetree"
    save_tree(TreeDef(name="Inner", nodes=[
        TreeNode(type="leaf", path="./a.scriptree", display_name="A"),
    ]), inner)
    kit = sub / "kit.scriptreetree"
    save_tree(TreeDef(name="Kit", nodes=[
        TreeNode(type="leaf", path="./b.scriptree", display_name="B"),
        TreeNode(type="leaf", path="./inner.scriptreetree", display_name="Inner"),
    ]), kit)
    parent = tmp_path / "parent.scriptreetree"
    save_tree(TreeDef(name="Parent", nodes=[
        TreeNode(type="leaf", path="./sub/kit.scriptreetree"),
        TreeNode(type="folder", name="Again", children=[
            TreeNode(type="leaf", path="./sub/kit.scriptreetree"),
        ]),
    ]), parent)

    view = TreeLauncherView()
    view.load(str(parent))
    rows = _all_subtree_rows(view)
    kit_rows = [r for r in rows
                if str(r.data(0, __import__("scriptree.ui.tree_view",
                       fromlist=["_ROLE_SUBTREE"])._ROLE_SUBTREE) or "")
                .replace("\\", "/").endswith("kit.scriptreetree")]
    assert len(kit_rows) == 2
    row1, row2 = kit_rows[0], kit_rows[1]
    # Edit kit DIRECTLY through row1 (so kit itself is written by row1).
    row1.addChild(view._new_leaf_item(str(x), display_name="X"))
    # Edit the NESTED inner subtree ONLY through row2's copy.
    inner_row2 = _subtree_row_named(row2, "inner.scriptreetree")
    assert inner_row2 is not None
    inner_row2.addChild(view._new_leaf_item(str(y), display_name="Y"))

    assert view._save_tree() is True
    kit_paths = [n.path for n in load_tree(str(kit)).nodes if n.type == "leaf"]
    inner_paths = [n.path for n in load_tree(str(inner)).nodes if n.type == "leaf"]
    assert "./x.scriptree" in kit_paths, "row1 kit edit lost"
    assert "./y.scriptree" in inner_paths, "row2 nested edit lost to dedupe continue"


def test_drop_onto_failed_expand_subtree_is_gated(tmp_path: Path) -> None:
    """REVIEW #10 (HIGH): a subtree that FAILED to expand is NOT a legal in-place
    drop target — so a dropped tool can't vanish into neither file."""
    from PySide6.QtWidgets import QAbstractItemView

    sub = tmp_path / "sub"
    sub.mkdir()
    broken = sub / "kit.scriptreetree"
    broken.write_text("{ this is not valid json", encoding="utf-8")  # load error
    parent = tmp_path / "parent.scriptreetree"
    save_tree(TreeDef(name="Parent", nodes=[
        TreeNode(type="leaf", path="./sub/kit.scriptreetree"),
    ]), parent)
    new_tool = _tool(tmp_path / "c.scriptree", "C")

    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)
    assert st.data(0, _ROLE_EXPAND_OK) is not True   # it failed to expand

    # Internal-drag gate: an OnItem drop onto the broken subtree is REFUSED.
    on_item = QAbstractItemView.DropIndicatorPosition.OnItem
    assert view._tree_widget._is_legal_drop_target(st, on_item) is False

    # External-drop gate: a drop onto the broken subtree falls through to the
    # PARENT (sibling), so the tool is saved there — never lost.
    view._on_file_dropped(str(new_tool), target_item=st)
    assert view._save_tree() is True
    parent_def = load_tree(str(parent))
    parent_leaf_paths = [n.path for n in parent_def.nodes if n.type == "leaf"]
    assert any(p.endswith("c.scriptree") for p in parent_leaf_paths), \
        "dropped tool was lost (neither subtree nor parent)"


# --- a115: New Folder on a subtree row + no-reload-on-reclick ---------------

def test_new_folder_on_subtree_row_goes_inside_it(tmp_path: Path, monkeypatch) -> None:
    """v0.8.0a115: 'New Folder' with a cleanly-expanded subtree row selected
    must create the folder INSIDE that subtree, not in the tree root."""
    from scriptree.ui import tree_view as tv
    from scriptree.ui.tree_view import _is_folder

    parent, _sub = _make_parent_with_subtree(tmp_path)
    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)
    assert st.data(0, _ROLE_EXPAND_OK) is True

    root = view._tree_widget.topLevelItem(0)
    n_root_before = root.childCount()
    n_sub_before = st.childCount()
    view._tree_widget.setCurrentItem(st)
    monkeypatch.setattr(
        tv.QInputDialog, "getText",
        staticmethod(lambda *a, **k: ("NewFolder", True)),
    )

    view._add_folder()

    assert st.childCount() == n_sub_before + 1, "folder must land inside the subtree"
    assert root.childCount() == n_root_before, "root must be unchanged"
    new = st.child(st.childCount() - 1)
    assert _is_folder(new)


def test_click_expanded_subtree_does_not_reload(tmp_path: Path) -> None:
    """v0.8.0a115: clicking an ALREADY cleanly-expanded subtree must NOT reload
    it from disk (which would wipe in-place edits)."""
    parent, _sub = _make_parent_with_subtree(tmp_path)
    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)
    assert st.data(0, _ROLE_EXPAND_OK) is True

    calls: list = []
    view._expand_subtree = lambda it: calls.append(it)  # type: ignore[assignment]
    view._on_item_activated(st, 0)
    assert calls == [], "a cleanly-expanded subtree must not reload on click"


def test_click_failed_subtree_reloads(tmp_path: Path) -> None:
    """A subtree that FAILED to expand IS reloaded on click (retry path)."""
    parent, _sub = _make_parent_with_subtree(tmp_path)
    view = TreeLauncherView()
    view.load(str(parent))
    st = _find_subtree_row(view)
    st.setData(0, _ROLE_EXPAND_OK, False)

    calls: list = []
    view._expand_subtree = lambda it: calls.append(it)  # type: ignore[assignment]
    view._on_item_activated(st, 0)
    assert calls == [st], "a failed-expand subtree should reload on click"
