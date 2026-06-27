"""v0.8.0a83 — tests for the remembered/named cell-layout persistence:
``.scriptreelayout`` (layout_io), the ``ForestItem.rel_offset`` field
(forest_io), and the layout MRU (recent_files)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scriptree.shell.forest_io import (
    AutoDiscoverConfig, ForestDef, ForestItem, load_forest, save_forest,
)
from scriptree.shell.layout_io import (
    LayoutDef, LayoutEntry, load_layout, save_layout,
)


# ---------------------------------------------------------------------------
# .scriptreelayout round-trip
# ---------------------------------------------------------------------------

def test_layout_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "my.scriptreelayout"
    lay = LayoutDef(name="My", entries=[
        LayoutEntry(catalog_path="ScripTreeApps/Demos/x.scriptree",
                    rel_offset=(120, -40), kind="tool"),
        LayoutEntry(catalog_path="ScripTreeApps/y.scriptreetree",
                    rel_offset=(-60, 80), kind="tree"),
    ])
    save_layout(lay, p)
    g = load_layout(p)
    assert g.name == "My"
    assert len(g.entries) == 2
    assert g.entries[0].rel_offset == (120, -40)
    assert g.entries[1].rel_offset == (-60, 80)
    assert g.entries[0].kind == "tool"


def test_layout_wrong_format_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.scriptreelayout"
    p.write_text(json.dumps({"format": "nope", "entries": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_layout(p)


def test_layout_skips_malformed_entries(tmp_path: Path) -> None:
    p = tmp_path / "m.scriptreelayout"
    p.write_text(json.dumps({
        "format": "scriptreelayout",
        "version": 1,
        "name": "m",
        "entries": [
            {"catalog_path": "a.scriptree", "rel_offset": [1, 2]},      # ok
            {"rel_offset": [3, 4]},                                      # no path
            {"catalog_path": "b.scriptree", "rel_offset": [5]},          # bad offset
            {"catalog_path": "c.scriptree", "rel_offset": "nope"},       # bad offset
            {"catalog_path": "d.scriptree", "rel_offset": ["x", "y"]},   # non-int
        ],
    }), encoding="utf-8")
    g = load_layout(p)
    assert len(g.entries) == 1
    assert g.entries[0].rel_offset == (1, 2)


def test_layout_version_mismatch_tolerated(tmp_path: Path) -> None:
    p = tmp_path / "v.scriptreelayout"
    p.write_text(json.dumps({
        "format": "scriptreelayout", "version": 99, "name": "v",
        "entries": [{"catalog_path": "a.scriptree", "rel_offset": [0, 0]}],
    }), encoding="utf-8")
    g = load_layout(p)  # logs, does not raise
    assert len(g.entries) == 1


# ---------------------------------------------------------------------------
# ForestItem.rel_offset persistence (additive, legacy byte-stable)
# ---------------------------------------------------------------------------

def test_forest_rel_offset_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "t.scriptreeforest"
    f = ForestDef(name="T", items=[
        ForestItem(path="ScripTreeApps/y.scriptreetree", kind="tree",
                   position=(10, 20), rel_offset=(5, -7)),
        ForestItem(path="ScripTreeApps/z.scriptree", kind="tool",
                   position=(30, 40)),  # no rel_offset
    ], excluded=[], auto_discover=AutoDiscoverConfig())
    save_forest(f, p)
    blob = json.loads(p.read_text(encoding="utf-8"))
    assert blob["items"][0]["rel_offset"] == [5, -7]
    # Legacy byte-stability: an item without an offset must NOT emit the key.
    assert "rel_offset" not in blob["items"][1]
    g = load_forest(p)
    assert g.items[0].rel_offset == (5, -7)
    assert g.items[1].rel_offset is None


def test_forest_legacy_file_without_rel_offset_loads(tmp_path: Path) -> None:
    p = tmp_path / "legacy.scriptreeforest"
    p.write_text(json.dumps({
        "format": "scriptreeforest", "version": 1, "name": "L",
        "items": [{"path": "ScripTreeApps/y.scriptreetree", "kind": "tree",
                   "position": [1, 2]}],
        "excluded": [], "auto_discover": {},
    }), encoding="utf-8")
    g = load_forest(p)
    assert g.items[0].rel_offset is None  # absent -> None, no crash


# ---------------------------------------------------------------------------
# recent_files layout MRU
# ---------------------------------------------------------------------------

def test_recent_layouts_mru(tmp_path: Path, monkeypatch) -> None:
    # recent_files uses a bare QSettings() (inherits the app's org/app store).
    # Redirect it to an isolated temp INI so the test neither depends on the
    # app being branded nor pollutes the user's real recent-files store.
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    _ = QApplication.instance() or QApplication([])
    from scriptree.shell import recent_files as rf

    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(
        rf, "QSettings",
        lambda: QSettings(ini, QSettings.Format.IniFormat),
    )
    rf.clear()
    assert rf.get_layouts() == []
    a = str((tmp_path / "a.scriptreelayout").resolve())
    b = str((tmp_path / "b.scriptreelayout").resolve())
    rf.add_layout(a)
    rf.add_layout(b)
    got = rf.get_layouts()
    assert got[0] == b and got[1] == a  # most-recent first
    # Re-adding promotes to most-recent (dedup, no duplicate).
    rf.add_layout(a)
    got = rf.get_layouts()
    assert got[0] == a
    assert got.count(a) == 1
    rf.clear()
    assert rf.get_layouts() == []
