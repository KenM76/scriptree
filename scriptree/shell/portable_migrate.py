"""Migrate per-user state when toggling Portable mode (v0.8.0a90).

## Why this exists

Portable mode (``scriptree.core.portable``) chooses ALL of its data roots once
at startup.  v0.8.0a89 shipped the redirect but NOT a migration, so flipping the
toggle made the target mode boot with an EMPTY forest + settings (your old state
was still safe in the other location, but it *looked* like a reset).  The user
asked for switching "without data loss".

This module copies the CURRENT mode's live state into the TARGET mode's
locations at toggle time, so after the restart your forest, preferences, rings,
and UI settings are right where the new mode looks for them.

## What is migrated (and what is NOT)

Migrated:
* the forest workspace ``default.scriptreeforest``,
* ``forest_preferences.json``,
* the user-scope autoload-rings config + the saved-rings directory,
* the recent-files / dock-layout / menu-appearance settings — these are the
  bare-``QSettings()`` store, which is the **Windows registry** in normal mode
  and an **INI** under ``_portable_data`` in portable mode, so the migration
  copies key-by-key between a registry ``QSettings`` and an INI ``QSettings``.

NOT migrated — **personal drop-installed apps** (the app FOLDERS).  Since
v0.8.0a92 the forest stores tool paths via portable-aware **named roots**
(``forest_io.known_roots``), not absolutes: an app installed under
``%LOCALAPPDATA%`` is tagged ``root:"personal"`` + a relative path, and the
``personal`` base itself redirects to the install-local apps tree under portable
mode.  So after a toggle a personal-rooted reference re-resolves to the
*portable* apps tree — which only holds the file if the app FOLDER was copied
there.  This migration deliberately does NOT copy app folders (the
personal↔shared merge is ambiguous on the way back — the shared root already
holds the bundled apps), so on the SAME machine such an app keeps working only
while its original folder still exists at the old base (the load-time existence
gate then recovers it via the legacy resolver).  For a true *cross-machine*
portable copy, keep apps in the shared ``<install>/ScripTreeApps`` tree (which
travels with a folder-copy, tagged ``root:"install"``) or re-install them into
the portable tree — that is the "make a portable copy including local tools"
operation, a future step.  (Note: ``excluded[]`` is also rooted as of a92, so
the two halves track together across a toggle.)

## The snapshot-flip-snapshot trick

The path resolvers (``default_autoload_path`` etc.) answer for whichever mode is
CURRENTLY active (they read the sentinel via ``is_portable()``).  So we:

1. snapshot the CURRENT-mode locations (before flipping),
2. flip the sentinel via ``portable.set_portable``,
3. snapshot the TARGET-mode locations (after flipping),
4. copy 1 → 3.

This reuses the resolvers' own logic for both modes — no duplicated path maths.
Everything is best-effort: a copy failure is logged, never raised, so the toggle
itself can't be blocked by a locked file.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def _log(msg: str) -> None:
    print(f"[portable_migrate] {msg}", file=sys.stderr)


def _state_paths(branding: dict) -> dict:
    """Resolve the current-mode state file/dir locations (mode = whatever
    ``is_portable()`` says right now)."""
    from scriptree.shell import forest_io, ring_io
    brand = branding.get("appName", "ScripTree")
    return {
        "forest": forest_io.default_autoload_path(branding),
        "prefs": forest_io.default_preferences_path(branding),
        "rings_cfg": ring_io._autoload_config_path(brand, "user"),
        "rings_dir": ring_io._default_rings_dir(brand),
    }


def _copy_file(src: Path, dst: Path) -> bool:
    try:
        if src and Path(src).is_file() and Path(src).resolve() != Path(dst).resolve():
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return True
    except OSError as e:  # noqa: BLE001
        _log(f"copy file {src} -> {dst} failed: {e}")
    return False


def _copy_dir(src: Path, dst: Path) -> bool:
    try:
        if src and Path(src).is_dir() and Path(src).resolve() != Path(dst).resolve():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            return True
    except OSError as e:  # noqa: BLE001
        _log(f"copy dir {src} -> {dst} failed: {e}")
    return False


def _copy_qsettings(src, dst) -> int:  # noqa: ANN001 — QSettings
    """Copy every key from one ``QSettings`` store to another. Returns count."""
    n = 0
    for k in src.allKeys():
        dst.setValue(k, src.value(k))
        n += 1
    dst.sync()
    return n


def _ui_settings_stores(to_portable: bool, brand: str):  # noqa: ANN201
    """Return ``(src_qsettings, dst_qsettings)`` for the recent/dock/menu store.

    The normal-mode store is the platform-native one (registry on Windows); the
    portable-mode store is an INI at ``<_portable_data>/<brand>/<brand>.ini``
    (the exact file ``ring_main``'s ``setPath`` redirect resolves to).  When
    enabling, src = native, dst = INI; when disabling, the reverse.
    """
    from PySide6.QtCore import QSettings
    from scriptree.core.portable import portable_data_root
    native = QSettings(
        QSettings.Format.NativeFormat, QSettings.Scope.UserScope, brand, brand,
    )
    ini_path = portable_data_root() / brand / f"{brand}.ini"
    ini_path.parent.mkdir(parents=True, exist_ok=True)
    ini = QSettings(str(ini_path), QSettings.Format.IniFormat)
    return (native, ini) if to_portable else (ini, native)


def migrate_for_toggle(to_portable: bool, branding: dict) -> dict:
    """Flip Portable mode and migrate the current state into the new locations.

    Returns ``{"ok": bool, "copied": list[str], "reason": str}``.  ``ok`` is
    False only when ENABLING and the sentinel write failed (read-only medium) —
    in that case nothing was flipped or copied.  All copies are best-effort.
    """
    from scriptree.core.portable import set_portable

    brand = branding.get("appName", "ScripTree")

    # 1. snapshot CURRENT-mode locations (before the flip).
    src = _state_paths(branding)

    # 2. flip the sentinel.
    res = set_portable(to_portable)
    if to_portable and res is None:
        return {"ok": False, "copied": [], "reason": "sentinel-write-failed"}

    # 3. snapshot TARGET-mode locations (after the flip).
    dst = _state_paths(branding)

    # 4. copy state files current -> target.
    copied: list[str] = []
    if _copy_file(src["forest"], dst["forest"]):
        copied.append("forest")
    if _copy_file(src["prefs"], dst["prefs"]):
        copied.append("preferences")
    if _copy_file(src["rings_cfg"], dst["rings_cfg"]):
        copied.append("autoload rings")
    if _copy_dir(src["rings_dir"], dst["rings_dir"]):
        copied.append("saved rings")

    # 5. UI settings (registry <-> INI).  Best-effort + isolated so a settings
    #    hiccup never blocks the forest/state migration.
    try:
        s, d = _ui_settings_stores(to_portable, brand)
        if _copy_qsettings(s, d):
            copied.append("settings")
    except Exception as e:  # noqa: BLE001
        _log(f"UI-settings migration skipped: {e}")

    _log(f"toggle to_portable={to_portable}: migrated {copied or '(nothing)'}")
    return {"ok": True, "copied": copied, "reason": ""}
