"""Tests for v0.8.0a89 portable mode.

Portable mode collapses every per-user / registry store under the install
folder so a folder-copy is self-contained.  Detection is via a sentinel file
in the install root OR the ``SCRIPTREE_PORTABLE`` env var; when on, the
personal app root, the forest workspace + preferences, and the autoload-rings
dirs all redirect install-local.

All tests anchor ``portable.install_anchor`` to a ``tmp_path`` so nothing
touches the real install (and so a stray test sentinel can never make the real
app portable).  The env var is the clean toggle for the redirect tests.
"""
from __future__ import annotations

from pathlib import Path

from scriptree.core import portable


def _anchor_to(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(portable, "install_anchor", lambda: tmp_path)


# --- detection -----------------------------------------------------------

def test_is_portable_env_and_sentinel(monkeypatch, tmp_path) -> None:
    _anchor_to(monkeypatch, tmp_path)
    monkeypatch.delenv("SCRIPTREE_PORTABLE", raising=False)
    assert portable.is_portable() is False
    # a sentinel file enables it
    (tmp_path / "portable").write_text("x", encoding="utf-8")
    assert portable.is_portable() is True
    # a falsey env var OVERRIDES the sentinel (explicit dev opt-out)
    monkeypatch.setenv("SCRIPTREE_PORTABLE", "off")
    assert portable.is_portable() is False
    # a truthy env var enables it even with no sentinel
    (tmp_path / "portable").unlink()
    monkeypatch.setenv("SCRIPTREE_PORTABLE", "yes")
    assert portable.is_portable() is True


def test_roots(monkeypatch, tmp_path) -> None:
    _anchor_to(monkeypatch, tmp_path)
    assert portable.portable_apps_root() == tmp_path / "ScripTreeApps"
    assert portable.portable_data_root() == tmp_path / "_portable_data"


def test_set_portable_round_trip(monkeypatch, tmp_path) -> None:
    _anchor_to(monkeypatch, tmp_path)
    monkeypatch.delenv("SCRIPTREE_PORTABLE", raising=False)
    assert portable.is_portable() is False
    p = portable.set_portable(True)
    assert p == tmp_path / "portable" and p.exists()
    assert portable.is_portable() is True
    portable.set_portable(False)
    assert not (tmp_path / "portable").exists()
    assert portable.is_portable() is False


# --- redirects -----------------------------------------------------------

def test_personal_root_redirects_when_portable(monkeypatch, tmp_path) -> None:
    _anchor_to(monkeypatch, tmp_path)
    from scriptree.core import app_install
    # neutralise any real install.personal_root override so the OS/portable
    # fall-through is what we exercise.
    monkeypatch.setattr(app_install, "_settings_string", lambda *_a, **_k: "")
    monkeypatch.setenv("SCRIPTREE_PORTABLE", "1")
    assert app_install.default_personal_root() == tmp_path / "ScripTreeApps"
    # and it cascades: the shared root anchors at the same place in portable
    monkeypatch.setenv("SCRIPTREE_PORTABLE", "off")
    assert app_install.default_personal_root() != tmp_path / "ScripTreeApps"


def test_forest_paths_redirect_when_portable(monkeypatch, tmp_path) -> None:
    _anchor_to(monkeypatch, tmp_path)
    monkeypatch.setenv("SCRIPTREE_PORTABLE", "1")
    from scriptree.shell import forest_io
    b = {"appName": "ScripTree"}
    data = tmp_path / "_portable_data"
    assert forest_io.default_autoload_path(b) == data / forest_io._DEFAULT_FOREST_FILENAME
    assert forest_io.default_preferences_path(b).parent == data


def test_ring_dirs_redirect_when_portable(monkeypatch, tmp_path) -> None:
    _anchor_to(monkeypatch, tmp_path)
    monkeypatch.setenv("SCRIPTREE_PORTABLE", "1")
    from scriptree.shell import ring_io
    data = tmp_path / "_portable_data"
    assert ring_io._appdata_dir("ScripTree") == data
    # system scope gets a distinct subdir so the two autoload configs don't
    # collapse to the same file (see test_ring_scopes_stay_distinct_in_portable)
    assert ring_io._programdata_dir("ScripTree") == data / "system"
    assert ring_io._default_rings_dir("ScripTree") == data / "rings"


def test_no_redirect_when_not_portable(monkeypatch, tmp_path) -> None:
    _anchor_to(monkeypatch, tmp_path)
    monkeypatch.setenv("SCRIPTREE_PORTABLE", "off")
    from scriptree.shell import forest_io, ring_io
    b = {"appName": "ScripTree"}
    data = tmp_path / "_portable_data"
    # normal (non-portable) resolution must NOT point under the install
    assert forest_io.default_autoload_path(b).parent != data
    assert ring_io._appdata_dir("ScripTree") != data


# --- review fixes --------------------------------------------------------

def test_shared_autoload_redirects_when_portable(monkeypatch, tmp_path) -> None:
    """The 'Save to shared location' target must also stay install-local in
    portable mode (else it escapes the portable tree)."""
    _anchor_to(monkeypatch, tmp_path)
    monkeypatch.setenv("SCRIPTREE_PORTABLE", "1")
    from scriptree.shell import forest_io
    b = {"appName": "ScripTree"}
    data = tmp_path / "_portable_data"
    assert forest_io.shared_autoload_path(b) == data / forest_io._DEFAULT_FOREST_FILENAME
    # personal == shared in portable mode
    assert forest_io.shared_autoload_path(b) == forest_io.default_autoload_path(b)


def test_ring_scopes_stay_distinct_in_portable(monkeypatch, tmp_path) -> None:
    """user-scope and system-scope autoload configs must NOT collapse to the
    same file under the portable data root."""
    _anchor_to(monkeypatch, tmp_path)
    monkeypatch.setenv("SCRIPTREE_PORTABLE", "1")
    from scriptree.shell import ring_io
    user = ring_io._autoload_config_path("ScripTree", "user")
    system = ring_io._autoload_config_path("ScripTree", "system")
    assert user != system
    assert user.parent == tmp_path / "_portable_data"
    assert system.parent == tmp_path / "_portable_data" / "system"


def test_portable_ignores_offtree_override_but_honors_intree(monkeypatch, tmp_path) -> None:
    """A stale install.personal_root that resolves OUTSIDE the install tree must
    not defeat portability; an override INSIDE the tree is still honoured."""
    _anchor_to(monkeypatch, tmp_path)
    monkeypatch.setenv("SCRIPTREE_PORTABLE", "1")
    from scriptree.core import app_install
    # off-tree (stale, travelled in scriptree.ini) -> portable wins
    monkeypatch.setattr(
        app_install, "_settings_string", lambda *_a, **_k: r"C:/Some/Other/Place"
    )
    assert app_install.default_personal_root() == tmp_path / "ScripTreeApps"
    # in-tree override -> honoured
    inside = tmp_path / "ScripTreeApps" / "Custom"
    monkeypatch.setattr(
        app_install, "_settings_string", lambda *_a, **_k: str(inside)
    )
    assert app_install.default_personal_root() == inside
