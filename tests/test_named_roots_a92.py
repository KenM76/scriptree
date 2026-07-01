"""v0.8.0a92 — named-root path portability in the `.scriptreeforest` (option #2).

Forest item paths are stored as ``(root-id, path-relative-to-that-root)`` for
the well-known portable-aware roots (``install`` / ``apps`` / ``personal``), so
the absolute location is recomputed per machine / mode at load — a folder move,
a portable<->normal toggle, or a cross-machine copy no longer strands the
reference.  Legacy forests (bare ``path``, no ``root``) still load unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.shell import forest_io as fio  # noqa: E402
from scriptree.shell.forest_io import (  # noqa: E402
    AutoDiscoverConfig,
    ForestDef,
    ForestItem,
    load_forest,
    save_forest,
)


def _roots() -> dict:
    return dict(fio.known_roots())


def test_known_roots_registry() -> None:
    ids = [rid for rid, _b in fio.known_roots()]
    assert "install" in ids and "apps" in ids and "personal" in ids
    # most-specific-first ordering: install precedes apps
    assert ids.index("install") < ids.index("apps")


def test_path_under_root_round_trips_through_helpers() -> None:
    inst = _roots()["install"]
    p = inst / "Foo" / "bar.scriptree"
    assert fio._path_to_rooted(p) == ("install", "Foo/bar.scriptree")
    assert fio._rooted_to_abs("install", "Foo/bar.scriptree").resolve() == p.resolve()


def test_path_outside_all_roots_is_none(tmp_path) -> None:
    # tmp_path is not under any known root
    assert fio._path_to_rooted(tmp_path / "x.scriptree") is None


def test_save_stores_rooted_and_load_resolves(tmp_path, monkeypatch) -> None:
    # point the 'install' root at a tmp apps dir holding a REAL file (load now
    # existence-gates the rooted candidate).
    apps = tmp_path / "apps"
    (apps / "Demo").mkdir(parents=True)
    monkeypatch.setattr(fio, "known_roots", lambda: [("install", apps.resolve())])
    tool = apps / "Demo" / "d.scriptree"
    tool.write_text("{}", encoding="utf-8")
    f = ForestDef(
        name="t", items=[ForestItem(path=str(tool), kind="tool")],
        auto_discover=AutoDiscoverConfig(),
    )
    ff = tmp_path / "f.scriptreeforest"
    save_forest(f, ff)
    item = json.loads(ff.read_text(encoding="utf-8"))["items"][0]
    assert item["root"] == "install"
    assert item["path"] == "Demo/d.scriptree"            # portable rel, no drive
    assert ":" not in item["path"] and not item["path"].startswith("/")
    loaded = load_forest(ff)
    assert Path(loaded.items[0].path).resolve() == tool.resolve()


def test_legacy_bare_path_still_loads(tmp_path) -> None:
    inst = _roots()["install"]
    tool = inst / "Demo" / "d.scriptree"
    legacy = {
        "format": fio._FORMAT, "version": fio._VERSION, "name": "L",
        "items": [{"path": str(tool), "kind": "tool"}],
        "excluded": [], "auto_discover": {},
    }
    ff = tmp_path / "legacy.scriptreeforest"
    ff.write_text(json.dumps(legacy), encoding="utf-8")
    assert Path(load_forest(ff).items[0].path).resolve() == tool.resolve()


def test_unknown_root_falls_back_gracefully(tmp_path) -> None:
    inst = _roots()["install"]
    tool = inst / "Demo" / "d.scriptree"
    blob = {
        "format": fio._FORMAT, "version": fio._VERSION, "name": "U",
        "items": [{"path": str(tool), "root": "network99", "kind": "tool"}],
        "excluded": [], "auto_discover": {},
    }
    ff = tmp_path / "u.scriptreeforest"
    ff.write_text(json.dumps(blob), encoding="utf-8")
    # unknown root-id -> _rooted_to_abs returns None -> legacy resolver, no crash
    assert Path(load_forest(ff).items[0].path).resolve() == tool.resolve()


def test_all_root_ids_reverse_resolve() -> None:
    # even when bases coincide (install == personal under portable mode), every
    # id must still reverse-resolve — the de-dup-removal fix.
    for rid in ("install", "apps", "personal"):
        assert fio._rooted_to_abs(rid, "x.scriptree") is not None


def test_existence_gate_recovers_colocated_tool(tmp_path) -> None:
    # a tool tagged `install` whose canonical base lacks it, but which sits NEXT
    # TO the forest file (a zipped/emailed workspace) — the existence gate must
    # fall through to the forest-dir-relative recovery.
    (tmp_path / "Demo").mkdir()
    real = tmp_path / "Demo" / "d.scriptree"
    real.write_text("{}", encoding="utf-8")
    blob = {
        "format": fio._FORMAT, "version": fio._VERSION, "name": "Z",
        "items": [{"path": "Demo/d.scriptree", "root": "install", "kind": "tool"}],
        "excluded": [], "auto_discover": {},
    }
    ff = tmp_path / "f.scriptreeforest"
    ff.write_text(json.dumps(blob), encoding="utf-8")
    loaded = load_forest(ff)
    assert Path(loaded.items[0].path).resolve() == real.resolve()


def test_excluded_is_rooted_and_round_trips(tmp_path) -> None:
    inst = _roots()["install"]
    ex = inst / "Old" / "x.scriptree"
    f = ForestDef(
        name="t", items=[], excluded=[str(ex)],
        auto_discover=AutoDiscoverConfig(),
    )
    ff = tmp_path / "f.scriptreeforest"
    save_forest(f, ff)
    blob = json.loads(ff.read_text(encoding="utf-8"))
    assert blob["excluded"][0] == {"root": "install", "path": "Old/x.scriptree"}
    loaded = load_forest(ff)
    assert Path(loaded.excluded[0]).resolve() == ex.resolve()


def test_legacy_string_excluded_still_loads(tmp_path) -> None:
    inst = _roots()["install"]
    ex = inst / "Old" / "x.scriptree"
    blob = {
        "format": fio._FORMAT, "version": fio._VERSION, "name": "L",
        "items": [], "excluded": [str(ex)], "auto_discover": {},
    }
    ff = tmp_path / "f.scriptreeforest"
    ff.write_text(json.dumps(blob), encoding="utf-8")
    assert Path(load_forest(ff).excluded[0]).resolve() == ex.resolve()


def test_catalog_path_is_rooted_too(tmp_path, monkeypatch) -> None:
    apps = tmp_path / "apps"
    (apps / "Suite").mkdir(parents=True)
    monkeypatch.setattr(fio, "known_roots", lambda: [("install", apps.resolve())])
    leaf = apps / "Suite" / "tool.scriptree"
    cat = apps / "Suite" / "suite.scriptreetree"
    leaf.write_text("{}", encoding="utf-8")
    cat.write_text("{}", encoding="utf-8")
    f = ForestDef(
        name="t",
        items=[ForestItem(path=str(leaf), kind="tool", catalog_path=str(cat))],
        auto_discover=AutoDiscoverConfig(),
    )
    ff = tmp_path / "c.scriptreeforest"
    save_forest(f, ff)
    item = json.loads(ff.read_text(encoding="utf-8"))["items"][0]
    assert item["catalog_root"] == "install"
    assert item["catalog_path"] == "Suite/suite.scriptreetree"
    loaded = load_forest(ff)
    assert Path(loaded.items[0].catalog_path).resolve() == cat.resolve()
