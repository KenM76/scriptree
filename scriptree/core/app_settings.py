"""Centralized application settings backed by an INI file.

## For humans

Settings are stored in ``scriptree.ini`` inside the project directory
(next to ``run_scriptree.py``), not in the OS registry. This makes
the application fully portable — copy the folder to another machine
and settings come along.

The INI path can be overridden:

1. ``settings_path`` key inside the current INI (custom location).
2. ``SCRIPTREE_SETTINGS_PATH`` environment variable.

This module is pure Python with a single PySide6 import (QSettings).

## For maintainers / LLMs

* This is the ONE grandfathered module allowed a module-level
  ``from PySide6.QtCore import QSettings`` — see
  ``tests/test_core_purity.py`` (``_MODULE_LEVEL_QT_ALLOWED``). Do
  not add other module-level Qt imports here or anywhere else in
  ``core``; do not remove this exception without updating that test.
* Resolution-order divergence to know about: ``get_settings()``
  checks ``SCRIPTREE_SETTINGS_PATH`` env FIRST, then the INI's own
  ``settings_path`` redirect, then the default path. The
  one-line summary above lists them env-first; the docstring on
  ``get_settings`` also lists env-first — keep all three in sync if
  you reorder the checks.
* ``_find_scriptree_dir()`` returns the *application* dir (parent of
  the ``scriptree`` package), NOT the project root. It depends on
  this file living at ``scriptree/core/app_settings.py`` — moving
  the file breaks every default path. ``permissions.py`` walks up
  separately for ``permissions/``; the two are intentionally
  different anchors.
* ``_sanitize_path`` strips ``\\x00-\\x1f`` and the shell-meta set
  ``; | & $ < > !`` plus backtick, then
  strips whitespace. Env / INI path values flow through it before
  becoming a ``Path``; any new path-from-untrusted-source code must
  reuse it.
* ``get_settings`` only accepts a redirect target whose suffix is
  ``.ini`` and that differs from the default path (env path must
  also be ``.ini``) — a non-``.ini`` redirect is silently ignored
  and the default is used.
* ``get_personal_configs_dir`` has the side effect of creating the
  directory (``mkdir(parents=True, exist_ok=True)``) on every call;
  callers that only want to *probe* the location must not rely on
  this being read-only.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from PySide6.QtCore import QSettings


def _find_scriptree_dir() -> Path:
    """Return the ScripTree/ application directory.

    This is the directory containing the ``scriptree`` Python package,
    tests, help, etc. — NOT the project root (which also contains
    ``run_scriptree.py``, ``permissions/``, and ``ScripTreeApps/``).
    """
    # scriptree/core/app_settings.py → scriptree/core/ → scriptree/ → ScripTree/
    return Path(__file__).resolve().parent.parent.parent


def _default_ini_path() -> Path:
    """Return the default INI file path inside the ScripTree/ folder."""
    return _find_scriptree_dir() / "scriptree.ini"


def _sanitize_path(path: str) -> str:
    """Strip dangerous characters from a settings path value.

    Prevents injection via crafted INI values or env vars.
    """
    # Remove null bytes, control chars, and shell metacharacters.
    return re.sub(r"[\x00-\x1f;|&`$<>!]", "", path).strip()


def get_settings() -> QSettings:
    """Return the application QSettings backed by an INI file.

    Resolution order for the INI file location:

    1. ``SCRIPTREE_SETTINGS_PATH`` environment variable.
    2. ``settings_path`` key inside the default INI file (allows the
       INI to redirect itself to a custom location).
    3. ``scriptree.ini`` in the project root (default).
    """
    default_path = _default_ini_path()

    # Check environment variable first.
    env_val = os.environ.get("SCRIPTREE_SETTINGS_PATH", "").strip()
    if env_val:
        env_val = _sanitize_path(env_val)
        p = Path(env_val)
        if p.suffix == ".ini":
            return QSettings(str(p), QSettings.Format.IniFormat)

    # Read the default INI to check for a redirect.
    if default_path.exists():
        qs = QSettings(str(default_path), QSettings.Format.IniFormat)
        custom = qs.value("settings_path", "", type=str)
        if custom:
            custom = _sanitize_path(custom)
            p = Path(custom)
            if p.suffix == ".ini" and p != default_path:
                return QSettings(str(p), QSettings.Format.IniFormat)
        return qs

    # Default: create/use the project-root INI.
    return QSettings(str(default_path), QSettings.Format.IniFormat)


def _default_user_configs_dir() -> Path:
    """Default location for per-user configuration files."""
    return _find_scriptree_dir() / "user_configs"


def get_personal_configs_dir() -> Path:
    """Return the directory for per-user configuration sidecars.

    Resolution order:

    1. ``SCRIPTREE_USER_CONFIGS_DIR`` environment variable (sanitized).
    2. ``personal_configs_path`` key in the settings INI.
    3. Default: ``<ScripTree app dir>/user_configs/``.

    The directory is created if it doesn't exist.
    """
    # 1. Environment variable.
    env_val = os.environ.get("SCRIPTREE_USER_CONFIGS_DIR", "").strip()
    if env_val:
        env_val = _sanitize_path(env_val)
        if env_val:
            p = Path(env_val)
            p.mkdir(parents=True, exist_ok=True)
            return p

    # 2. Settings INI redirect.
    qs = get_settings()
    custom = qs.value("personal_configs_path", "", type=str)
    if custom:
        custom = _sanitize_path(custom)
        if custom:
            p = Path(custom)
            p.mkdir(parents=True, exist_ok=True)
            return p

    # 3. Default.
    p = _default_user_configs_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p
