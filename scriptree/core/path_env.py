"""PATH manipulation helpers for the missing-executable recovery flow.

When a tool's executable can't be located on disk, the recovery
dialog lets the user pick the file's actual location and choose
**how** to remember it: replace the path stored in the tool's
``.scriptree``, or add the parent directory to a search path at one
of several scopes. This module owns the "add to a search path"
side — keeps the dialog code declarative and the actual filesystem /
registry / file mutations isolated for testing.

Each scope has a permission gate (see ``CAPABILITIES`` in
``permissions.py``):

- ``add_to_session_path``           — modify ``os.environ["PATH"]``;
                                      survives until ScripTree exits.
- ``add_to_scriptree_path_prepend`` — append to ``ToolDef.path_prepend``
                                      and re-save the .scriptree file.
- ``add_to_scriptreetree_path_prepend`` — append to
                                          ``TreeDef.path_prepend`` and
                                          re-save the .scriptreetree.
- ``add_to_user_path``  — modify ``HKCU\\Environment\\Path`` so future
                          processes (including future ScripTree
                          launches) see the directory. No admin needed.
- ``add_to_system_path`` — modify ``HKLM\\SYSTEM\\CurrentControlSet\\
                           Control\\Session Manager\\Environment\\Path``.
                           Persists across users; **requires admin**.

The ``add_*`` functions return ``ScopeResult`` carrying a ``.ok`` flag
and a human-readable message. The dialog uses both — green check on
success, red bar with the message on failure (e.g. "Admin elevation
required for system PATH").

All scopes are idempotent: appending a directory that's already on
the target list is a no-op (the function returns ``ok=True`` with a
"already present" message).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ScopeResult:
    """Result of an ``add_to_*`` call."""

    ok: bool
    message: str
    # Optional path of a file that was modified (so the caller can
    # echo it in a status bar / log).
    file_modified: str | None = None


# --- session env -----------------------------------------------------------

def add_to_session_path(directory: str) -> ScopeResult:
    """Prepend ``directory`` to ``os.environ["PATH"]``.

    Affects the current ScripTree process and every subprocess it
    spawns afterwards. Lost when ScripTree exits — for persistent
    changes, use ``add_to_user_path`` or ``add_to_system_path`` (or
    one of the per-file scopes).
    """
    if not directory:
        return ScopeResult(False, "Empty directory.")
    abs_dir = os.path.abspath(directory)
    sep = os.pathsep
    current = os.environ.get("PATH", "")
    parts = current.split(sep) if current else []
    # Idempotency: if already at front, nothing to do.
    if parts and os.path.normcase(os.path.abspath(parts[0])) == os.path.normcase(abs_dir):
        return ScopeResult(True, f"Already first on PATH: {abs_dir}")
    # Move-to-front semantics so the user's last choice wins, even if
    # the dir was on PATH later in the order.
    parts = [p for p in parts if os.path.normcase(os.path.abspath(p)) != os.path.normcase(abs_dir)]
    parts.insert(0, abs_dir)
    os.environ["PATH"] = sep.join(parts)
    return ScopeResult(True, f"Added to session PATH: {abs_dir}")


# --- per-file (.scriptree / .scriptreetree) -------------------------------

def add_to_scriptree_path_prepend(
    scriptree_path: str, directory: str
) -> ScopeResult:
    """Append ``directory`` to ``ToolDef.path_prepend`` and re-save."""
    return _add_to_file_path_prepend(
        scriptree_path, directory, kind="scriptree"
    )


def add_to_scriptreetree_path_prepend(
    scriptreetree_path: str, directory: str
) -> ScopeResult:
    """Append ``directory`` to ``TreeDef.path_prepend`` and re-save."""
    return _add_to_file_path_prepend(
        scriptreetree_path, directory, kind="scriptreetree"
    )


def _add_to_file_path_prepend(
    file_path: str, directory: str, *, kind: str
) -> ScopeResult:
    """Shared loader for both .scriptree and .scriptreetree files."""
    if not directory:
        return ScopeResult(False, "Empty directory.")
    if not file_path:
        return ScopeResult(False, "No file path supplied.")

    p = Path(file_path)
    if not p.is_file():
        return ScopeResult(False, f"File not found: {file_path}")

    # Lazy imports — keep this module independent of the rest of core
    # for testability.
    from .io import (
        load_tool, save_tool, load_tree, save_tree,
    )

    try:
        if kind == "scriptree":
            obj = load_tool(file_path)
            existing = list(obj.path_prepend or [])
            if directory in existing:
                return ScopeResult(
                    True,
                    f"Already in path_prepend: {directory}",
                    file_modified=file_path,
                )
            obj.path_prepend = existing + [directory]
            save_tool(obj, file_path)
        elif kind == "scriptreetree":
            obj = load_tree(file_path)
            existing = list(obj.path_prepend or [])
            if directory in existing:
                return ScopeResult(
                    True,
                    f"Already in path_prepend: {directory}",
                    file_modified=file_path,
                )
            obj.path_prepend = existing + [directory]
            save_tree(obj, file_path)
        else:
            return ScopeResult(False, f"Unknown kind: {kind!r}")
    except Exception as e:  # noqa: BLE001
        return ScopeResult(False, f"Could not modify {file_path}: {e}")

    return ScopeResult(
        True,
        f"Appended to {Path(file_path).name} path_prepend: {directory}",
        file_modified=file_path,
    )


# --- system / user PATH (Windows registry-based) --------------------------

def add_to_user_path(directory: str) -> ScopeResult:
    """Prepend to ``HKCU\\Environment\\Path``.

    Windows-only. Uses the registry directly rather than ``setx``
    because ``setx`` truncates values at 1024 chars, which is
    routinely exceeded on developer machines.
    """
    if sys.platform != "win32":
        return ScopeResult(
            False, "User PATH modification is Windows-only.",
        )
    return _modify_windows_path(
        directory, hive="HKCU", subkey=r"Environment", admin_required=False,
    )


def add_to_system_path(directory: str) -> ScopeResult:
    """Prepend to ``HKLM\\SYSTEM\\CurrentControlSet\\Control\\Session
    Manager\\Environment\\Path``.

    Windows-only. Requires admin elevation (SetValue under HKLM
    raises ``PermissionError`` for non-elevated processes — we catch
    that and surface a friendly "Admin elevation required" message
    instead of a stack trace).
    """
    if sys.platform != "win32":
        return ScopeResult(
            False, "System PATH modification is Windows-only.",
        )
    return _modify_windows_path(
        directory,
        hive="HKLM",
        subkey=r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        admin_required=True,
    )


def _modify_windows_path(
    directory: str, *, hive: str, subkey: str, admin_required: bool
) -> ScopeResult:
    """Read-modify-write of a Windows registry PATH value.

    Prepends ``directory`` to the existing value (if not already
    present), preserves the original ``REG_EXPAND_SZ`` type so
    ``%VAR%`` references inside PATH still expand, and broadcasts
    ``WM_SETTINGCHANGE`` so Explorer / cmd / new processes pick up
    the change without a logout.
    """
    if not directory:
        return ScopeResult(False, "Empty directory.")
    abs_dir = os.path.abspath(directory)

    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return ScopeResult(
            False, "winreg module unavailable on this platform.",
        )

    root = {
        "HKCU": winreg.HKEY_CURRENT_USER,
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
    }[hive]

    # Open the env key. KEY_READ | KEY_WRITE under HKLM raises
    # PermissionError for non-elevated processes — we catch and
    # surface a clean message.
    access = winreg.KEY_READ | winreg.KEY_WRITE
    try:
        key = winreg.OpenKey(root, subkey, 0, access)
    except PermissionError:
        if admin_required:
            return ScopeResult(
                False,
                "Admin elevation required to modify system PATH. "
                "Re-run ScripTree as administrator and try again.",
            )
        return ScopeResult(
            False, f"Permission denied opening registry key {subkey}.",
        )
    except FileNotFoundError:
        return ScopeResult(
            False, f"Registry key not found: {subkey}",
        )

    try:
        try:
            existing, value_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            existing, value_type = "", winreg.REG_EXPAND_SZ

        existing_str = str(existing) if existing is not None else ""
        parts = existing_str.split(os.pathsep) if existing_str else []
        # Idempotency: leave alone if already in the list (case-
        # insensitive on Windows).
        for p in parts:
            if os.path.normcase(p) == os.path.normcase(abs_dir):
                winreg.CloseKey(key)
                return ScopeResult(
                    True,
                    f"{abs_dir} is already on {hive} PATH.",
                )

        new_parts = [abs_dir] + parts
        new_value = os.pathsep.join(p for p in new_parts if p)

        # Preserve the original type when possible — REG_EXPAND_SZ is
        # what Windows uses by default so %VAR% references inside
        # PATH expand at lookup time.
        if value_type not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
            value_type = winreg.REG_EXPAND_SZ
        winreg.SetValueEx(key, "Path", 0, value_type, new_value)
        winreg.CloseKey(key)
    except PermissionError:
        return ScopeResult(
            False,
            "Permission denied writing PATH. "
            + ("Re-run as administrator." if admin_required else ""),
        )
    except Exception as e:  # noqa: BLE001
        return ScopeResult(
            False, f"Failed to update {hive} PATH: {e}",
        )

    # Broadcast the change so other apps reload their environment.
    _broadcast_environment_change()

    return ScopeResult(
        True,
        f"Prepended to {hive} PATH: {abs_dir}\n"
        f"(New processes will pick up the change automatically; "
        f"already-running processes including the parent shell may "
        f"need to be restarted.)",
    )


def _broadcast_environment_change() -> None:
    """Send WM_SETTINGCHANGE so Explorer/cmd/new processes refresh env."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002

        SendMessageTimeout = ctypes.windll.user32.SendMessageTimeoutW
        SendMessageTimeout.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
            wintypes.LPCWSTR, wintypes.UINT, wintypes.UINT,
            ctypes.POINTER(wintypes.DWORD),
        ]
        SendMessageTimeout.restype = wintypes.LPARAM

        result = wintypes.DWORD()
        SendMessageTimeout(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
            SMTO_ABORTIFHUNG, 5000, ctypes.byref(result),
        )
    except Exception:
        # Broadcasting is a nice-to-have. Failing here doesn't
        # invalidate the registry update.
        pass
