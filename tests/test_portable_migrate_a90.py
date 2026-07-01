"""Tests for v0.8.0a90 portable-toggle state migration.

Toggling Portable mode must carry the user's current forest / preferences /
rings / UI settings into the target mode's locations so switching either
direction loses no data.  ``migrate_for_toggle`` snapshots the current-mode
paths, flips the sentinel, snapshots the target-mode paths, and copies 1→2.

All tests anchor ``portable.install_anchor`` to ``tmp_path`` and redirect the
non-portable (appdata) roots under ``tmp/home`` so nothing touches the real
install or user profile.  The registry↔INI settings copy is stubbed out
(``_copy_qsettings``) so no test reads/writes the real registry.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core import portable  # noqa: E402
from scriptree.shell import forest_io, portable_migrate  # noqa: E402


def _setup(monkeypatch, tmp_path):
    """Anchor portable→tmp and the appdata roots→tmp/home; stub the UI copy."""
    home = tmp_path / "home"
    monkeypatch.setattr(portable, "install_anchor", lambda: tmp_path)
    monkeypatch.delenv("SCRIPTREE_PORTABLE", raising=False)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(portable_migrate, "_copy_qsettings", lambda _s, _d: 0)
    return {"appName": "ScripTree"}


# --- _copy_qsettings (real, isolated to temp INI files) ------------------

def test_copy_qsettings_round_trips_keys(tmp_path) -> None:
    from PySide6.QtCore import QSettings
    from scriptree.shell.portable_migrate import _copy_qsettings
    src = QSettings(str(tmp_path / "src.ini"), QSettings.Format.IniFormat)
    src.setValue("recent/files", "a;b;c")
    src.setValue("dock/layout", "xyz")
    src.sync()
    dst_path = tmp_path / "dst.ini"
    dst = QSettings(str(dst_path), QSettings.Format.IniFormat)
    n = _copy_qsettings(src, dst)
    assert n >= 2
    reread = QSettings(str(dst_path), QSettings.Format.IniFormat)
    assert reread.value("dock/layout") == "xyz"
    assert reread.value("recent/files") == "a;b;c"


# --- migrate_for_toggle --------------------------------------------------

def test_enable_copies_forest_into_portable(monkeypatch, tmp_path) -> None:
    b = _setup(monkeypatch, tmp_path)
    assert portable.is_portable() is False
    # seed a non-portable forest
    src_forest = forest_io.default_autoload_path(b)
    src_forest.parent.mkdir(parents=True, exist_ok=True)
    src_forest.write_text('{"forest":"A"}', encoding="utf-8")

    res = portable_migrate.migrate_for_toggle(True, b)
    assert res["ok"] and "forest" in res["copied"]
    assert portable.is_portable() is True  # sentinel now present
    dst = portable.portable_data_root() / forest_io._DEFAULT_FOREST_FILENAME
    assert dst.is_file()
    assert dst.read_text(encoding="utf-8") == '{"forest":"A"}'


def test_disable_copies_forest_back_to_profile(monkeypatch, tmp_path) -> None:
    b = _setup(monkeypatch, tmp_path)
    # start portable with a portable-side forest
    assert portable.set_portable(True) is not None
    assert portable.is_portable() is True
    pf = portable.portable_data_root() / forest_io._DEFAULT_FOREST_FILENAME
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text('{"forest":"B"}', encoding="utf-8")

    res = portable_migrate.migrate_for_toggle(False, b)
    assert res["ok"] and "forest" in res["copied"]
    assert portable.is_portable() is False  # sentinel removed
    # now-active (non-portable) forest path holds the migrated copy
    dst = forest_io.default_autoload_path(b)
    assert dst.is_file()
    assert dst.read_text(encoding="utf-8") == '{"forest":"B"}'


def test_round_trip_preserves_state(monkeypatch, tmp_path) -> None:
    b = _setup(monkeypatch, tmp_path)
    src_forest = forest_io.default_autoload_path(b)
    src_forest.parent.mkdir(parents=True, exist_ok=True)
    src_forest.write_text('{"forest":"orig"}', encoding="utf-8")
    # enable -> portable has it
    portable_migrate.migrate_for_toggle(True, b)
    assert (portable.portable_data_root() / forest_io._DEFAULT_FOREST_FILENAME).read_text(
        encoding="utf-8"
    ) == '{"forest":"orig"}'
    # disable -> profile gets it back
    portable_migrate.migrate_for_toggle(False, b)
    assert forest_io.default_autoload_path(b).read_text(encoding="utf-8") == '{"forest":"orig"}'


def test_enable_failure_returns_not_ok(monkeypatch, tmp_path) -> None:
    b = _setup(monkeypatch, tmp_path)
    # simulate a read-only install medium: sentinel write fails
    monkeypatch.setattr(portable, "set_portable", lambda enabled: None)
    res = portable_migrate.migrate_for_toggle(True, b)
    assert res["ok"] is False
    assert res["reason"] == "sentinel-write-failed"
    assert res["copied"] == []


def test_no_state_to_copy_is_clean(monkeypatch, tmp_path) -> None:
    b = _setup(monkeypatch, tmp_path)
    # nothing seeded — toggle should still succeed, copying nothing
    res = portable_migrate.migrate_for_toggle(True, b)
    assert res["ok"] is True
    assert "forest" not in res["copied"]
