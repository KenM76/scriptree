"""v0.8.0a94 — Feature A1 core: build a NEW portable copy incl. local tools.

Tests the three pure pieces of ``scriptree.shell.portable_export`` (no Qt, no
network): the install-tree copy (with its exclude set), the install-item rebase
onto an EXTERNAL ScripTreeApps, and the dest-rooted save (paths under the
destination tag ``root: "install"`` and resolve when the copy runs from dest).
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.shell import forest_io  # noqa: E402
from scriptree.shell import portable_export as pe  # noqa: E402
from scriptree.shell.forest_io import (  # noqa: E402
    AutoDiscoverConfig,
    ForestDef,
    ForestItem,
    load_forest,
)


# --- copy_install_tree ---------------------------------------------------

def test_copy_install_tree_skips_dev_and_vcs_junk(tmp_path) -> None:
    src = tmp_path / "install"
    # things that MUST travel
    (src / "scriptree" / "shell").mkdir(parents=True)
    (src / "scriptree" / "__init__.py").write_text("x", encoding="utf-8")
    (src / "ScripTreeApps" / "Cat" / "Tool").mkdir(parents=True)
    (src / "ScripTreeApps" / "Cat" / "Tool" / "tool.scriptree").write_text("{}", encoding="utf-8")
    (src / "branding").mkdir()
    (src / "run_scriptree.bat").write_text("@echo", encoding="utf-8")
    # things that must be SKIPPED
    (src / ".git" / "objects").mkdir(parents=True)
    (src / ".git" / "config").write_text("x", encoding="utf-8")
    (src / "tests").mkdir()
    (src / "tests" / "test_x.py").write_text("x", encoding="utf-8")
    (src / "_portable_data").mkdir()
    (src / "_portable_data" / "default.scriptreeforest").write_text("{}", encoding="utf-8")
    (src / "rags").mkdir()
    (src / "rags" / "index.md").write_text("x", encoding="utf-8")
    (src / "scriptree" / "__pycache__").mkdir()
    (src / "scriptree" / "stale.pyc").write_text("x", encoding="utf-8")
    # per-machine private state — must NOT travel into a shareable copy
    (src / "scriptree.ini").write_text("[recent]\n", encoding="utf-8")
    (src / "scriptree.ini.bak").write_text("[recent]\n", encoding="utf-8")

    dest = tmp_path / "copy"
    pe.copy_install_tree(src, dest)

    assert (dest / "scriptree" / "__init__.py").is_file()
    assert (dest / "ScripTreeApps" / "Cat" / "Tool" / "tool.scriptree").is_file()
    assert (dest / "branding").is_dir()
    assert (dest / "run_scriptree.bat").is_file()
    # skipped
    assert not (dest / ".git").exists()
    assert not (dest / "tests").exists()
    assert not (dest / "_portable_data").exists()
    assert not (dest / "rags").exists()
    assert not (dest / "scriptree" / "__pycache__").exists()
    assert not (dest / "scriptree" / "stale.pyc").exists()
    assert not (dest / "scriptree.ini").exists()       # private state, excluded
    assert not (dest / "scriptree.ini.bak").exists()


# --- prune_items_outside_external (a94 review fix #3) ---------------------

def test_prune_drops_items_not_under_dest_apps(tmp_path) -> None:
    dest_apps = tmp_path / "copy" / "ScripTreeApps"
    inside = dest_apps / "Cat" / "Tool" / "tool.scriptree"
    inside.parent.mkdir(parents=True)
    inside.write_text("{}", encoding="utf-8")
    outside = tmp_path / "host" / "personal" / "Failed" / "f.scriptree"
    outside.parent.mkdir(parents=True)
    outside.write_text("{}", encoding="utf-8")
    forest = ForestDef(name="t", items=[
        ForestItem(path=str(inside), kind="tool"),
        ForestItem(path=str(outside), kind="tool"),   # copy-failed / outside
    ], auto_discover=AutoDiscoverConfig())
    dropped = pe.prune_items_outside_external(forest, dest_apps)
    assert dropped == [str(outside)]
    assert [it.path for it in forest.items] == [str(inside)]


# --- lifted private-tool detection helpers (a94 review fix #4) ------------

def test_private_helpers_detect_by_content(tmp_path) -> None:
    assert pe.is_private_name("sw_bridge.exe")
    assert pe.is_private_name("Automation.csx")
    assert pe.is_private_name("SolidWorks.Interop.sldworks.dll")
    assert not pe.is_private_name("readme.txt")
    macros = tmp_path / "MyMacros"
    macros.mkdir()
    (macros / "macro.scriptree").write_text("{}", encoding="utf-8")
    (macros / "auto.csx").write_text("//", encoding="utf-8")
    assert pe.folder_has_private_tools(macros)
    clean = tmp_path / "Clean"
    clean.mkdir()
    (clean / "t.scriptree").write_text("{}", encoding="utf-8")
    assert not pe.folder_has_private_tools(clean)


def test_copy_install_tree_refuses_nonempty_dest(tmp_path) -> None:
    src = tmp_path / "install"
    (src / "scriptree").mkdir(parents=True)
    dest = tmp_path / "copy"
    dest.mkdir()
    (dest / "important.txt").write_text("do not delete me", encoding="utf-8")
    try:
        pe.copy_install_tree(src, dest)
        assert False, "expected FileExistsError on a non-empty dest"
    except FileExistsError:
        pass
    # the user's file is untouched
    assert (dest / "important.txt").read_text(encoding="utf-8") == "do not delete me"


# --- rebase_install_items_to_external ------------------------------------

def test_rebase_install_items_points_at_external_apps(tmp_path) -> None:
    cur_apps = tmp_path / "install" / "ScripTreeApps"
    dest_apps = tmp_path / "copy" / "ScripTreeApps"
    cur_apps.mkdir(parents=True)
    inside = cur_apps / "Cat" / "Tool" / "tool.scriptree"
    inside.parent.mkdir(parents=True)
    inside.write_text("{}", encoding="utf-8")
    outside = tmp_path / "elsewhere" / "loose.scriptree"
    outside.parent.mkdir(parents=True)
    outside.write_text("{}", encoding="utf-8")
    forest = ForestDef(name="t", items=[
        ForestItem(path=str(inside), kind="tool"),
        ForestItem(path=str(outside), kind="tool"),
    ], auto_discover=AutoDiscoverConfig())
    n = pe.rebase_install_items_to_external(
        forest, current_install_apps=cur_apps, dest_apps=dest_apps,
    )
    assert n == 1
    assert Path(forest.items[0].path) == dest_apps / "Cat" / "Tool" / "tool.scriptree"
    assert Path(forest.items[1].path) == outside  # untouched


# --- save_forest_for_external_install ------------------------------------

def test_save_for_external_install_tags_install_and_resolves(monkeypatch, tmp_path) -> None:
    dest_root = tmp_path / "copy"
    dest_apps = dest_root / "ScripTreeApps"
    tool = dest_apps / "Cat" / "Tool" / "tool.scriptree"
    tool.parent.mkdir(parents=True)
    tool.write_text("{}", encoding="utf-8")
    item = ForestItem(path=str(tool), kind="tool", position=(9, 9), rel_offset=(1, 2))
    forest = ForestDef(name="t", items=[item], auto_discover=AutoDiscoverConfig())

    out = pe.external_autoload_path(dest_root)
    assert out == dest_root / "_portable_data" / "default.scriptreeforest"
    pe.save_forest_for_external_install(forest, out, dest_root)

    saved = json.loads(out.read_text(encoding="utf-8"))["items"][0]
    assert saved["root"] == "install"
    assert saved["path"] == "Cat/Tool/tool.scriptree"

    # When the copy RUNS (project root == dest_root), it resolves back.
    monkeypatch.setattr(forest_io, "_project_root", lambda: dest_root)
    loaded = load_forest(out)
    assert Path(loaded.items[0].path).resolve() == tool.resolve()
    assert loaded.items[0].position == (9, 9)
    assert loaded.items[0].rel_offset == (1, 2)


def test_save_for_external_install_restores_project_root(tmp_path) -> None:
    """The resolver swap must be restored even on a normal return."""
    before = forest_io._project_root
    dest_root = tmp_path / "copy"
    (dest_root / "_portable_data").mkdir(parents=True)
    forest = ForestDef(name="t", items=[], auto_discover=AutoDiscoverConfig())
    pe.save_forest_for_external_install(
        forest, pe.external_autoload_path(dest_root), dest_root,
    )
    assert forest_io._project_root is before  # restored
