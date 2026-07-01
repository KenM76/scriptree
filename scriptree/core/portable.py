"""Portable-mode detection + install-local data root (v0.8.0a89).

## What "portable" means — and the problem it solves

Normally ScripTree splits its state across THREE stores, only one of which
travels with the install:

* install-local — ``scriptree.ini``, ``user_configs/``, ``permissions/`` and
  the ``ScripTreeApps`` *shared* app root.  These already move with a
  folder-copy.
* per-user appdata — the forest workspace (``default.scriptreeforest``),
  ``forest_preferences.json``, and the autoload-rings config/dir.
* the Windows **registry** — recent files, dock layouts, menu appearance
  (everything written through a bare ``QSettings()``).

So copying the install folder to a USB stick / shared-server folder does NOT
carry the user's forest, their UI settings, or any *personal* drop-installed
app.  That is the gap "portable mode" closes.

**Portable mode** redirects every per-user / registry store to live UNDER the
install folder, so the whole thing is one self-contained tree.  It behaves
exactly as if every "personal" write went to the install-local *shared*
location instead of appdata/registry — which is the "acts like saving to the
server/shared location, contained in the install folder" behaviour the design
called for.

## Detection — either signal turns it on

1. a sentinel FILE in the install root (the dir holding the ``scriptree``
   package): any of ``portable`` / ``PORTABLE`` / ``scriptree.portable`` /
   ``portable.flag``; or
2. the ``SCRIPTREE_PORTABLE`` environment variable set truthy
   (``1`` / ``true`` / ``yes`` / ``on``, case-insensitive).  Setting it to a
   falsey value (``0`` / ``false`` / ``no`` / ``off``) FORCES portable off even
   if a stray sentinel file exists — an explicit env override always wins, so a
   developer can run a non-portable session inside a portable tree.

The Settings dialog's "Portable mode" toggle just creates/removes the sentinel
via :func:`set_portable` and tells the user to restart — the data roots are
resolved once at startup, so a live toggle cannot move the open forest file.

## Where things land in portable mode (the redirect map)

| state | normal location | portable location |
|---|---|---|
| installed apps (personal == shared) | ``%LOCALAPPDATA%\\ScripTree\\Apps`` | ``<install>/ScripTreeApps`` |
| synthesised ``_groups`` trees | ``<personal>/_groups`` | ``<install>/ScripTreeApps/_groups`` * |
| forest workspace + preferences | ``%APPDATA%\\<brand>`` | ``<install>/_portable_data`` |
| autoload rings + config | ``%APPDATA%`` / Documents | ``<install>/_portable_data`` |
| recent / dock / menu (QSettings) | Windows registry | ``<install>/_portable_data`` (INI) |

(*) ``_groups`` and the third forest auto-discover root both derive from
:func:`default_personal_root`, so redirecting the personal root cascades to
them for free — there is no separate ``_groups`` chokepoint to patch.

This module is intentionally Qt-free and import-light so it can be consulted
from the headless ``validate`` path and from ``core`` without pulling in the
shell layer.
"""
from __future__ import annotations

import os
from pathlib import Path

#: Sentinel filenames that, present in the install root, enable portable mode.
_SENTINELS = ("portable", "PORTABLE", "scriptree.portable", "portable.flag")
_ENV = "SCRIPTREE_PORTABLE"
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}

#: The sentinel file name the toggle writes (lower-case canonical form).
_CANONICAL_SENTINEL = "portable"


def install_anchor() -> Path:
    """The install root — the directory that contains the ``scriptree`` package.

    This is the SAME anchor :func:`scriptree.core.app_install.default_shared_root`
    uses, so portable state sits beside the apps that travel with the install.

    ``scriptree/core/portable.py`` → ``scriptree/core/`` → ``scriptree/`` →
    ``<install>/``.
    """
    return Path(__file__).resolve().parent.parent.parent


def is_portable() -> bool:
    """True when ScripTree should run fully self-contained under the install.

    Env var wins over the sentinel file (truthy → on, falsey → off); absent the
    env var, the presence of any recognised sentinel file enables it.
    """
    val = os.environ.get(_ENV, "").strip().lower()
    if val in _TRUE:
        return True
    if val in _FALSE:
        return False
    root = install_anchor()
    return any((root / name).exists() for name in _SENTINELS)


def portable_data_root() -> Path:
    """Install-local home for per-user-style STATE in portable mode.

    ``<install>/_portable_data`` — the forest workspace, preferences, autoload
    rings, and the INI-redirected recent/dock/menu settings.  NOT where apps
    live (those go under :func:`portable_apps_root`).  Not created here; callers
    that write into it make parents as usual.
    """
    return install_anchor() / "_portable_data"


def portable_apps_root() -> Path:
    """Install-local app root in portable mode — identical to the shared root,
    so a folder-copy carries personal drop-installed apps too."""
    return install_anchor() / "ScripTreeApps"


def set_portable(enabled: bool) -> Path | None:
    """Create (enable) or remove (disable) the portable sentinel file.

    Returns the sentinel path when enabling, ``None`` when disabling or on
    failure.  A RESTART is required for the change to take effect — the data
    roots are resolved once at startup and cannot be re-homed under a live
    forest.  Best-effort: filesystem errors are swallowed (a read-only install
    medium simply can't toggle, which the caller surfaces as "couldn't write").
    """
    if enabled:
        sentinel = install_anchor() / _CANONICAL_SENTINEL
        try:
            sentinel.write_text(
                "ScripTree portable-mode marker.\n\n"
                "While this file exists, ScripTree keeps ALL of its state "
                "(apps, the forest workspace, settings, rings) under the "
                "install folder instead of your user profile / the registry, "
                "so the whole folder is self-contained and travels with a "
                "copy/USB stick.\n\n"
                "Delete this file (or toggle Portable mode off in Settings) "
                "and restart to return to normal per-user storage.\n",
                encoding="utf-8",
            )
        except OSError:
            return None
        return sentinel
    # Disabling: remove every recognised sentinel we can.
    for name in _SENTINELS:
        p = install_anchor() / name
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass
    return None
