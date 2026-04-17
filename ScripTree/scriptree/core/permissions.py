"""File-permission checks and capability-based access control.

Two permission layers:

1. **File-access permissions** — ``check_write_access()`` checks whether
   the current user can write a ``.scriptree`` / ``.scriptreetree`` file
   and its sidecar.  Used by the UI to disable editing controls on
   read-only files.

2. **Capability permissions** — ``load_permissions()`` reads blank
   sentinel files from a ``permissions/`` folder.  Each file's *name*
   describes a capability; its *file-system write permission* determines
   whether the current user has that capability.  A writable file means
   "allowed"; a read-only file means "denied".

   Capability folders are checked in order:

   a. **Application-level** — ``<project_root>/permissions/``
   b. **Per-file** — ``<tool_or_tree_folder>/permissions/``

   Per-file permissions can only **restrict** — they cannot grant a
   capability the user doesn't have at the application level.  If the
   two levels conflict (app says allowed, per-file says denied), the
   lowest (most restrictive) wins and the conflict is recorded for a
   UI warning.

Security note
-------------
On Windows, ``os.access(path, os.W_OK)`` checks the **read-only file
attribute** (``attrib +R``) but does **not** inspect NTFS ACLs.  For
the initial deployment scenario — admins setting the read-only attribute
on distributed tool files — this is sufficient.  A future enhancement
could use ``win32security`` for ACL-level checking if needed.

This module is pure Python, no Qt imports.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .configs import SIDECAR_SUFFIX, TREE_SIDECAR_SUFFIX


# ── File-access checks ─────────────────────────────────────────────────

@dataclass(frozen=True)
class WriteAccess:
    """Result of a write-permission check on a tool/tree file."""

    main_file_writable: bool
    sidecar_writable: bool

    @property
    def fully_writable(self) -> bool:
        return self.main_file_writable and self.sidecar_writable

    @property
    def any_writable(self) -> bool:
        return self.main_file_writable or self.sidecar_writable


def _is_writable(path: Path) -> bool:
    """Check if an existing file is writable by the current user.

    On Windows, ``os.access(path, os.W_OK)`` only checks the read-only
    file attribute — it does NOT check NTFS ACLs. For server deployments
    where IT uses ACL-based deny, we fall back to a non-destructive open
    test: open the file for append without writing, then close it. If
    the OS denies the open, the file is not writable.

    This approach:
    - Does NOT trigger security audit "access denied" events in most
      configurations (the open is immediately closed, no write occurs)
    - Does NOT modify the file or its timestamps
    - Does NOT cause UAC prompts
    - Works with both ``attrib +R`` and NTFS ACL deny rules
    """
    # Fast path: read-only attribute check.
    if not os.access(path, os.W_OK):
        return False
    # On Windows, also try an actual open to catch ACL denials that
    # os.access misses.
    if sys.platform == "win32":
        try:
            # Open for append (doesn't truncate), immediately close.
            fd = os.open(str(path), os.O_APPEND | os.O_WRONLY)
            os.close(fd)
            return True
        except (PermissionError, OSError):
            return False
    return True


def _can_write_file(path: Path) -> bool:
    if not path.exists():
        return True
    return _is_writable(path)


def _can_write_to_directory(directory: Path) -> bool:
    if not directory.exists():
        return False
    return os.access(directory, os.W_OK)


def _sidecar_for(file_path: Path) -> Path:
    name = file_path.name
    if name.endswith(".scriptreetree"):
        return file_path.with_name(name + TREE_SIDECAR_SUFFIX)
    return file_path.with_name(name + SIDECAR_SUFFIX)


def check_write_access(file_path: str | Path) -> WriteAccess:
    """Check write permissions for a tool/tree file and its sidecar."""
    path = Path(file_path)
    parent = path.parent

    if path.exists():
        main_writable = _is_writable(path)
    else:
        main_writable = _can_write_to_directory(parent)

    sidecar = _sidecar_for(path)
    if sidecar.exists():
        sidecar_writable = _is_writable(sidecar)
    else:
        sidecar_writable = _can_write_to_directory(parent)

    return WriteAccess(
        main_file_writable=main_writable,
        sidecar_writable=sidecar_writable,
    )


# ── Capability-based permissions ───────────────────────────────────────

# All known capabilities, keyed by **filename** (not path).
#
# The folder structure under permissions/ is purely organizational —
# IT can arrange files into any subfolder hierarchy they want (by
# department, role, etc.). ScripTree searches recursively for each
# filename.  When the same filename appears in multiple subfolders,
# the most restrictive (least access) wins.
#
# At the **application level** (the program's permissions/ folder):
#   - File exists + writable  → allowed
#   - File exists + read-only → denied
#   - File missing            → DENIED (secure default — prevents bypass
#                                by deleting files from a local copy)
#
# At the **per-file level** (a tool/tree's sibling permissions/ folder):
#   - File exists + writable  → allowed (but cannot exceed app-level)
#   - File exists + read-only → denied
#   - File missing            → INHERIT from app-level

CAPABILITIES: dict[str, str] = {
    # files
    "create_new_scriptree": "Create new .scriptree files",
    "create_new_scriptreetree": "Create new .scriptreetree files",
    "save_scriptree": "Save .scriptree files",
    "save_scriptreetree": "Save .scriptreetree files",
    "save_as_scriptree": "Save As .scriptree files",
    "save_as_scriptreetree": "Save As .scriptreetree files",
    # editing
    "edit_tool_definition": "Edit tool definitions in the editor",
    "read_configurations": "Switch between saved configurations (read-only access)",
    "write_configurations": "Create, save, delete, and rename configurations",
    "edit_configurations": "Edit saved configurations",
    "edit_environment": "Edit environment variables",
    "edit_visibility": "Edit UI visibility and hidden parameters",
    "edit_tree_structure": "Edit tree structure (add/remove/reorder tools)",
    "reorder_parameters": "Reorder parameters by drag-drop",
    "command_line_editor": "Access the command-line editor",
    "injection_protection_on_editor": (
        "Enable injection prevention on the command-line editor "
        "and extra arguments box"
    ),
    # running
    "run_tools": "Run tools",
    "run_as_different_user": "Run tools as a different user",
    "access_settings": "Access the Settings dialog",
    # settings
    "change_permissions_path": "Change the permissions folder location",
    "change_settings_path": "Change the settings INI file location",
    # security
    "load_user_plugins": "Load user parser plugins from external directories",
    "allow_symlinks": "Allow symlinks in tool/tree path resolution",
    "allow_path_traversal": "Allow ../ path traversal in tree leaf paths",
    "access_sensitive_paths": (
        "Access paths outside the tool's working directory "
        "(e.g. system directories, user profile folders)"
    ),
}


@dataclass
class PermissionConflict:
    """Records a conflict between two permission sources."""

    capability: str
    description: str
    app_level_allowed: bool
    file_level_allowed: bool
    resolved_to: bool  # always the more restrictive (False)
    app_source: str     # path to the app-level permission file
    file_source: str    # path to the per-file permission file


@dataclass
class PermissionSet:
    """Resolved permission set for the current session.

    ``allowed`` maps capability names to booleans.  Missing keys
    default to True (no restriction).
    """

    allowed: dict[str, bool] = field(default_factory=dict)
    conflicts: list[PermissionConflict] = field(default_factory=list)
    app_permissions_dir: str = ""
    file_permissions_dir: str = ""

    def can(self, capability: str) -> bool:
        """Return True if the capability is allowed."""
        return self.allowed.get(capability, True)

    def has_conflicts(self) -> bool:
        return len(self.conflicts) > 0

    def conflict_summary(self) -> str:
        """Human-readable summary of all conflicts."""
        if not self.conflicts:
            return ""
        lines = ["Permission conflicts detected:\n"]
        for c in self.conflicts:
            lines.append(
                f"  \u2022 {c.description} ({c.capability})\n"
                f"    App-level: {'allowed' if c.app_level_allowed else 'denied'}"
                f" ({c.app_source})\n"
                f"    File-level: {'allowed' if c.file_level_allowed else 'denied'}"
                f" ({c.file_source})\n"
                f"    \u2192 Resolved to: denied (most restrictive)\n"
            )
        return "\n".join(lines)


def _read_capability(perm_dir: Path, capability: str) -> bool | None:
    """Check a single capability by searching recursively for its file.

    Searches the entire ``perm_dir`` tree for files named ``capability``.
    If multiple copies are found (e.g. in different organizational
    subfolders), the most restrictive result wins (i.e. if ANY copy is
    read-only, the capability is denied).

    Returns True (allowed), False (denied), or None (no file found
    anywhere — no restriction from this source).
    """
    # Recursively find all files with this name under perm_dir.
    matches = list(perm_dir.rglob(capability))
    if not matches:
        return None  # not found anywhere

    # Check each match. If ANY is read-only, the answer is denied.
    # This is the "most restrictive wins" rule for duplicate files.
    for match in matches:
        if match.is_file() and not _is_writable(match):
            return False  # at least one copy denies → denied

    # All copies are writable → allowed.
    return True


def _find_app_permissions_dir(
    custom_path: str | None = None,
) -> Path | None:
    """Locate the application-level permissions directory.

    Resolution order:

    1. ``custom_path`` argument (from QSettings, passed by the UI).
       If given but invalid, returns None immediately (does NOT
       fall through — the user explicitly pointed somewhere).
    2. ``SCRIPTREE_PERMISSIONS_DIR`` environment variable. Same rule.
    3. Walk up from the ``scriptree`` package directory looking for a
       ``permissions/`` folder at the project root.
    """
    # 1. Explicit custom path — if given, it's authoritative.
    if custom_path:
        p = Path(custom_path)
        return p if p.is_dir() else None

    # 2. Environment variable — also authoritative if set.
    env_val = os.environ.get("SCRIPTREE_PERMISSIONS_DIR", "").strip()
    if env_val:
        p = Path(env_val)
        if not p.is_dir():
            return None
        # Security: the permissions directory itself should not be
        # writable by the current user — if it is, an attacker could
        # add their own permission files. Log a warning but still use it.
        if os.access(p, os.W_OK):
            import logging
            logging.getLogger(__name__).warning(
                "SCRIPTREE_PERMISSIONS_DIR %s is writable by the "
                "current user. For security, the permissions directory "
                "should be read-only (admin-managed).",
                p,
            )
        return p

    # 3. Walk up from this file.
    here = Path(__file__).resolve().parent  # scriptree/core/
    for _ in range(5):
        here = here.parent
        candidate = here / "permissions"
        if candidate.is_dir():
            return candidate
    return None


def load_permissions(
    *,
    file_path: str | Path | None = None,
    custom_permissions_path: str | None = None,
) -> PermissionSet:
    """Load and merge permission sets.

    Parameters
    ----------
    file_path:
        Optional path to a ``.scriptree`` or ``.scriptreetree`` file.
        If provided, checks for a sibling ``permissions/`` directory
        for per-file permission overrides.
    custom_permissions_path:
        Optional custom path to the app-level permissions directory
        (from the Settings dialog).

    Returns
    -------
    PermissionSet with resolved capabilities and any conflicts.

    Merge rules
    -----------
    **App-level** (the program's permissions/ folder):
      - File exists + writable  → allowed
      - File exists + read-only → denied
      - File missing            → **DENIED** (secure default)
      - No permissions dir found → all capabilities allowed (no
        permission system deployed — developer mode)

    **Per-file level** (tool/tree sibling permissions/ folder):
      - File exists + writable  → allowed (capped by app-level)
      - File exists + read-only → denied
      - File missing            → **INHERIT** from app-level

    Per-file can only restrict, never grant beyond app-level.
    """
    result = PermissionSet()

    # --- Application-level ---
    app_dir = _find_app_permissions_dir(custom_permissions_path)
    app_dir_exists = app_dir is not None
    if app_dir is not None:
        result.app_permissions_dir = str(app_dir)

    app_caps: dict[str, bool | None] = {}
    if app_dir is not None:
        for cap in CAPABILITIES:
            app_caps[cap] = _read_capability(app_dir, cap)

    # --- Per-file level ---
    file_dir: Path | None = None
    if file_path is not None:
        fp = Path(file_path).resolve()
        candidate = fp.parent / "permissions"
        if candidate.is_dir():
            file_dir = candidate
            result.file_permissions_dir = str(file_dir)

    file_caps: dict[str, bool | None] = {}
    if file_dir is not None:
        for cap in CAPABILITIES:
            file_caps[cap] = _read_capability(file_dir, cap)

    # --- Merge ---
    for cap, desc in CAPABILITIES.items():
        app_val = app_caps.get(cap)      # True / False / None
        file_val = file_caps.get(cap)    # True / False / None

        # App-level resolution:
        # - If no permissions dir exists at all → developer mode, allow everything
        # - If dir exists but file missing → DENIED (secure default)
        # - Otherwise use the file's writable state
        if not app_dir_exists:
            app_allowed = True  # no permission system deployed
        elif app_val is None:
            app_allowed = False  # file missing → denied (prevents deletion bypass)
        else:
            app_allowed = app_val

        # Per-file resolution:
        # - File missing → inherit from app-level
        # - File exists → use its writable state, but cap at app-level
        if file_val is None:
            file_allowed = app_allowed  # inherit
        else:
            file_allowed = file_val

        # Final: per-file can only restrict, never grant beyond app.
        if file_allowed and not app_allowed:
            resolved = False  # file tries to grant what app denies
        elif not app_allowed or not file_allowed:
            resolved = False
        else:
            resolved = True

        result.allowed[cap] = resolved

        # Detect conflicts: both sources have explicit values that disagree.
        if (app_val is not None and file_val is not None
                and app_val != file_val):
            result.conflicts.append(PermissionConflict(
                capability=cap,
                description=desc,
                app_level_allowed=app_allowed,
                file_level_allowed=file_val,
                resolved_to=resolved,
                app_source=str(app_dir / cap) if app_dir else "",
                file_source=str(file_dir / cap) if file_dir else "",
            ))

    return result


# Module-level cache for the app-level permissions (loaded once).
_cached_app_permissions: PermissionSet | None = None


def get_app_permissions(
    custom_permissions_path: str | None = None,
) -> PermissionSet:
    """Return the cached application-level permission set.

    Call ``reset_cached_permissions()`` to force a reload.
    """
    global _cached_app_permissions
    if _cached_app_permissions is None:
        _cached_app_permissions = load_permissions(
            custom_permissions_path=custom_permissions_path,
        )
    return _cached_app_permissions


def reset_cached_permissions() -> None:
    """Clear the cached permissions. Next call to
    ``get_app_permissions()`` will re-read from disk."""
    global _cached_app_permissions
    _cached_app_permissions = None
