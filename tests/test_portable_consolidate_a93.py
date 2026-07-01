"""v0.8.0a93 — Feature A core: consolidate non-install tools into the install tree.

Tests the pure plan → execute → rebase primitive with SYNTHETIC roots
(``known_roots`` monkeypatched to tmp dirs) — no Qt, no network.  The
highest-risk assumption (re-rooting is implicit via ``known_roots`` install-first
ordering, so a rebased item saves as ``root: "install"``) is pinned by
``test_rebase_then_save_roundtrip``.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

# (collision policy is plain strings — no ConflictMode import needed)
from scriptree.shell import forest_io  # noqa: E402
from scriptree.shell import portable_consolidate as pc  # noqa: E402
from scriptree.shell.forest_discover import _norm  # noqa: E402
from scriptree.shell.forest_io import (  # noqa: E402
    AutoDiscoverConfig,
    ForestDef,
    ForestItem,
    load_forest,
    save_forest,
)


def _roots(monkeypatch, tmp_path):
    """Create install/apps/personal tmp roots and point known_roots at them."""
    install = tmp_path / "install" / "ScripTreeApps"
    apps = tmp_path / "apps"
    personal = tmp_path / "personal"
    for r in (install, apps, personal):
        r.mkdir(parents=True)
    monkeypatch.setattr(forest_io, "known_roots", lambda: [
        ("install", install.resolve()),
        ("apps", apps.resolve()),
        ("personal", personal.resolve()),
    ])
    return install, apps, personal


def _tool(folder: Path, name: str = "tool.scriptree") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / name
    f.write_text("{}", encoding="utf-8")
    return f


# --- plan ----------------------------------------------------------------

def test_plan_classifies_each_item(monkeypatch, tmp_path) -> None:
    install, apps, personal = _roots(monkeypatch, tmp_path)
    a = _tool(apps / "Cat" / "Sub" / "ToolA")          # apps -> copy
    p = _tool(personal / "ToolP")                       # personal -> copy
    i = _tool(install / "Already")                       # install -> skip
    o = _tool(tmp_path / "elsewhere" / "ToolO")          # outside -> outside
    forest = ForestDef(name="t", items=[
        ForestItem(path=str(a), kind="tool"),
        ForestItem(path=str(p), kind="tool"),
        ForestItem(path=str(i), kind="tool"),
        ForestItem(path=str(o), kind="tool"),
    ], auto_discover=AutoDiscoverConfig())
    plan = pc.plan_consolidation(forest)
    by_status = {pl.status for pl in plan}
    assert by_status == {"copy", "skip", "outside"}
    copy_a = next(pl for pl in plan if pl.item.path == str(a))
    assert copy_a.rel == "Cat/Sub/ToolA"                 # category subpath preserved
    assert copy_a.dest_folder == (install / "Cat" / "Sub" / "ToolA")


# --- execute -------------------------------------------------------------

def test_execute_preserves_subpath_and_contents(monkeypatch, tmp_path) -> None:
    install, apps, _personal = _roots(monkeypatch, tmp_path)
    tool = _tool(apps / "Cat" / "Sub" / "Tool")
    forest = ForestDef(name="t", items=[ForestItem(path=str(tool), kind="tool")],
                       auto_discover=AutoDiscoverConfig())
    res = pc.execute_consolidation(pc.plan_consolidation(forest))
    assert res.copied == 1 and not res.errors
    dest = install / "Cat" / "Sub" / "Tool" / "tool.scriptree"
    assert dest.is_file()
    assert res.rebasing[_norm(str(tool))] == str(dest)
    # source is NEVER deleted
    assert tool.is_file()


def test_execute_never_deletes_source_on_collision_rename(monkeypatch, tmp_path) -> None:
    install, apps, _personal = _roots(monkeypatch, tmp_path)
    tool = _tool(apps / "Dup")
    _tool(install / "Dup")  # pre-existing install copy -> collision
    forest = ForestDef(name="t", items=[ForestItem(path=str(tool), kind="tool")],
                       auto_discover=AutoDiscoverConfig())
    res = pc.execute_consolidation(pc.plan_consolidation(forest),
                                   on_collision="rename")
    assert res.collisions == 1
    # renamed dest, source intact, and the rebase points at the RENAMED folder
    assert (install / "Dup-2" / "tool.scriptree").is_file()
    assert tool.is_file()
    assert res.rebasing[_norm(str(tool))] == str(install / "Dup-2" / "tool.scriptree")


def test_skip_collision_reuses_existing_install_copy(monkeypatch, tmp_path) -> None:
    install, apps, _personal = _roots(monkeypatch, tmp_path)
    tool = _tool(apps / "Dup")
    _tool(install / "Dup")
    forest = ForestDef(name="t", items=[ForestItem(path=str(tool), kind="tool")],
                       auto_discover=AutoDiscoverConfig())
    res = pc.execute_consolidation(pc.plan_consolidation(forest),
                                   on_collision="reuse")
    # re-roots the item to the EXISTING install copy (no -2 folder)
    assert not (install / "Dup-2").exists()
    assert res.rebasing[_norm(str(tool))] == str(install / "Dup" / "tool.scriptree")


# --- rebase + save round-trip (the key assumption) -----------------------

def test_rebase_then_save_roundtrip_tags_install(monkeypatch, tmp_path) -> None:
    install, apps, _personal = _roots(monkeypatch, tmp_path)
    tool = _tool(apps / "Cat" / "Tool")
    item = ForestItem(path=str(tool), kind="tool", position=(5, 7),
                      rel_offset=(3, 4))
    forest = ForestDef(name="t", items=[item], excluded=[str(tool)],
                       auto_discover=AutoDiscoverConfig())
    res = pc.execute_consolidation(pc.plan_consolidation(forest))
    n = pc.rebase_forest_items(forest, res)
    assert n == 1
    assert Path(forest.items[0].path) == install / "Cat" / "Tool" / "tool.scriptree"
    assert forest.excluded == []   # stale source dropped
    # save -> the rebased install path serialises as root:install
    ff = tmp_path / "f.scriptreeforest"
    save_forest(forest, ff)
    saved = json.loads(ff.read_text(encoding="utf-8"))["items"][0]
    assert saved["root"] == "install"
    assert saved["path"] == "Cat/Tool/tool.scriptree"
    # load -> resolves back, position + rel_offset preserved
    loaded = load_forest(ff)
    assert Path(loaded.items[0].path).resolve() == (install / "Cat" / "Tool" / "tool.scriptree").resolve()
    assert loaded.items[0].position == (5, 7)
    assert loaded.items[0].rel_offset == (3, 4)


def test_copied_scriptreetree_relative_leaf_survives(monkeypatch, tmp_path) -> None:
    install, apps, _personal = _roots(monkeypatch, tmp_path)
    suite_dir = apps / "Suite"
    suite_dir.mkdir(parents=True)
    (suite_dir / "tool.scriptree").write_text("{}", encoding="utf-8")
    (suite_dir / "suite.scriptreetree").write_text(
        json.dumps({"name": "S", "nodes": [{"type": "leaf", "path": "./tool.scriptree"}]}),
        encoding="utf-8",
    )
    forest = ForestDef(
        name="t",
        items=[ForestItem(path=str(suite_dir / "suite.scriptreetree"), kind="tree")],
        auto_discover=AutoDiscoverConfig(),
    )
    res = pc.execute_consolidation(pc.plan_consolidation(forest))
    # whole-folder copy preserves the RELATIVE leaf -> co-located after the move
    assert (install / "Suite" / "suite.scriptreetree").is_file()
    assert (install / "Suite" / "tool.scriptree").is_file()
    assert res.copied == 1


def test_two_items_sharing_one_source_folder_copy_once(monkeypatch, tmp_path) -> None:
    """A .scriptreetree suite + a co-located .scriptree leaf are TWO forest
    items in ONE folder.  The folder must copy once and BOTH items rebase into
    it — the second item must not trip a duplicate-copytree error."""
    install, apps, _personal = _roots(monkeypatch, tmp_path)
    folder = apps / "Suite"
    folder.mkdir(parents=True)
    (folder / "suite.scriptreetree").write_text("{}", encoding="utf-8")
    (folder / "leaf.scriptree").write_text("{}", encoding="utf-8")
    forest = ForestDef(name="t", items=[
        ForestItem(path=str(folder / "suite.scriptreetree"), kind="tree"),
        ForestItem(path=str(folder / "leaf.scriptree"), kind="tool"),
    ], auto_discover=AutoDiscoverConfig())
    res = pc.execute_consolidation(pc.plan_consolidation(forest))
    assert not res.errors
    assert res.copied == 1  # folder copied ONCE despite two items
    assert res.rebasing[_norm(str(folder / "suite.scriptreetree"))] == \
        str(install / "Suite" / "suite.scriptreetree")
    assert res.rebasing[_norm(str(folder / "leaf.scriptree"))] == \
        str(install / "Suite" / "leaf.scriptree")


def test_cross_root_same_name_renames_second(monkeypatch, tmp_path) -> None:
    """apps/Foo and personal/Foo both want install/Foo.  The first lands at
    Foo, the second collides (created THIS run) and renames to Foo-2 — neither
    source is touched."""
    install, apps, personal = _roots(monkeypatch, tmp_path)
    a = _tool(apps / "Foo")
    p = _tool(personal / "Foo")
    forest = ForestDef(name="t", items=[
        ForestItem(path=str(a), kind="tool"),
        ForestItem(path=str(p), kind="tool"),
    ], auto_discover=AutoDiscoverConfig())
    res = pc.execute_consolidation(pc.plan_consolidation(forest),
                                   on_collision="rename")
    assert (install / "Foo" / "tool.scriptree").is_file()
    assert (install / "Foo-2" / "tool.scriptree").is_file()
    assert a.is_file() and p.is_file()  # sources intact
    # the two items rebase to DISTINCT install copies
    dests = {res.rebasing[_norm(str(a))], res.rebasing[_norm(str(p))]}
    assert dests == {
        str(install / "Foo" / "tool.scriptree"),
        str(install / "Foo-2" / "tool.scriptree"),
    }


# --- loose-in-root (single-file) handling (a93 review fix #2) -------------

def test_loose_tool_in_root_base_copies_only_the_file(monkeypatch, tmp_path) -> None:
    """A tool sitting DIRECTLY in a root base (apps/RandomTool.scriptree, no
    per-tool folder) must copy ONLY its file into its own install sub-folder —
    never copytree the whole root (which would drag in every sibling tool and
    rebase to a bogus ScripTreeApps-2)."""
    install, apps, _personal = _roots(monkeypatch, tmp_path)
    loose = apps / "RandomTool.scriptree"
    loose.write_text("{}", encoding="utf-8")
    # unrelated siblings that must NOT be dragged along
    (apps / "Sibling.scriptree").write_text("{}", encoding="utf-8")
    (apps / "subdir").mkdir()
    (apps / "subdir" / "nested.scriptree").write_text("{}", encoding="utf-8")
    forest = ForestDef(name="t", items=[ForestItem(path=str(loose), kind="tool")],
                       auto_discover=AutoDiscoverConfig())
    plan = pc.plan_consolidation(forest)
    assert len(plan) == 1 and plan[0].single_file is True
    assert plan[0].dest_folder == install / "RandomTool"
    res = pc.execute_consolidation(plan)
    assert res.copied == 1 and not res.errors
    dest = install / "RandomTool" / "RandomTool.scriptree"
    assert dest.is_file()
    assert res.rebasing[_norm(str(loose))] == str(dest)
    # the root was NOT copied wholesale
    assert not (install / "Sibling.scriptree").exists()
    assert not (install / "subdir").exists()
    assert not (install.parent / "ScripTreeApps-2").exists()
    assert loose.is_file()  # source intact


def test_two_loose_tools_in_root_get_distinct_folders(monkeypatch, tmp_path) -> None:
    """Two loose tools share the SAME src_folder (the root base) but are
    DISTINCT files — the dedup key is the copy source (the file), so each lands
    in its own per-tool folder rather than collapsing onto one."""
    install, apps, _personal = _roots(monkeypatch, tmp_path)
    a = apps / "Alpha.scriptree"; a.write_text("{}", encoding="utf-8")
    b = apps / "Beta.scriptree"; b.write_text("{}", encoding="utf-8")
    forest = ForestDef(name="t", items=[
        ForestItem(path=str(a), kind="tool"),
        ForestItem(path=str(b), kind="tool"),
    ], auto_discover=AutoDiscoverConfig())
    res = pc.execute_consolidation(pc.plan_consolidation(forest))
    assert res.copied == 2
    assert (install / "Alpha" / "Alpha.scriptree").is_file()
    assert (install / "Beta" / "Beta.scriptree").is_file()
    assert res.rebasing[_norm(str(a))] == str(install / "Alpha" / "Alpha.scriptree")
    assert res.rebasing[_norm(str(b))] == str(install / "Beta" / "Beta.scriptree")


# --- catalog outside the copied folder (a93 review fix #3) ----------------

def test_catalog_outside_source_folder_is_relinked(monkeypatch, tmp_path) -> None:
    """When catalog_path resolves OUTSIDE the copied source folder it can't be
    rebased relatively; rather than leave it dangling (cross-machine), re-point
    it at the new install catalog and record the original."""
    install, apps, _personal = _roots(monkeypatch, tmp_path)
    tool = _tool(apps / "Cat" / "Tool")
    outside_cat = apps / "external_catalog.scriptree"
    outside_cat.write_text("{}", encoding="utf-8")
    item = ForestItem(path=str(tool), kind="tool", catalog_path=str(outside_cat))
    forest = ForestDef(name="t", items=[item], auto_discover=AutoDiscoverConfig())
    res = pc.execute_consolidation(pc.plan_consolidation(forest))
    n = pc.rebase_forest_items(forest, res)
    assert n == 1
    new_path = install / "Cat" / "Tool" / "tool.scriptree"
    assert Path(forest.items[0].path) == new_path
    assert Path(forest.items[0].catalog_path) == new_path  # relinked, no dangle
    assert res.catalog_relinked == [str(outside_cat)]


# --- private-tool warning scans contents (a93 review fix #1) --------------

def test_private_tool_warning_scans_folder_contents(monkeypatch, tmp_path) -> None:
    """A neutrally-named folder holding a .csx (or sw_bridge) must STILL trip
    the private-tool caution — the check inspects contents, not just the folder
    name."""
    from scriptree.shell.forest_controller import ForestController
    install, apps, _personal = _roots(monkeypatch, tmp_path)
    macros = apps / "MyMacros"
    macros.mkdir(parents=True)
    (macros / "macro.scriptree").write_text("{}", encoding="utf-8")
    (macros / "automation.csx").write_text("// automation", encoding="utf-8")
    forest = ForestDef(name="t", items=[
        ForestItem(path=str(macros / "macro.scriptree"), kind="tool")],
        auto_discover=AutoDiscoverConfig())
    warn = ForestController._private_tool_warning(pc.plan_consolidation(forest))
    assert "PRIVATE TOOLS" in warn and "MyMacros" in warn
    # a clean folder yields NO warning (no false positive)
    clean = apps / "CleanTool"
    clean.mkdir()
    (clean / "t.scriptree").write_text("{}", encoding="utf-8")
    forest2 = ForestDef(name="t", items=[
        ForestItem(path=str(clean / "t.scriptree"), kind="tool")],
        auto_discover=AutoDiscoverConfig())
    assert ForestController._private_tool_warning(pc.plan_consolidation(forest2)) == ""


def test_a1_rebase_on_deepcopy_does_not_mutate_live_forest(monkeypatch, tmp_path) -> None:
    install, apps, _personal = _roots(monkeypatch, tmp_path)
    tool = _tool(apps / "Tool")
    live = ForestDef(name="t", items=[ForestItem(path=str(tool), kind="tool")],
                     auto_discover=AutoDiscoverConfig())
    before = live.items[0].path
    work = copy.deepcopy(live)
    res = pc.execute_consolidation(pc.plan_consolidation(work))
    pc.rebase_forest_items(work, res)
    # the live forest is untouched; only the deep copy was rebased
    assert live.items[0].path == before
    assert Path(work.items[0].path) != Path(before)
