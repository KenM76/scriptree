"""Install-an-app-onto-the-forest core logic (v0.8.0a23+).

## For humans

When the user drags a folder or zip file onto a forest cell,
ScripTree offers to **install** the dropped item into a known
location and pick it up via the auto-discovery flow that's
already wired up for ``.scriptreeforest`` files.

This module owns the pure-logic half of that experience:

* Where to install (shared vs personal default; INI overrides).
* How to read the dropped source (folder copy vs zip extract
  with single-folder-wrapper auto-detection).
* What to do when the target folder already exists (overwrite
  / update-preserving-user-edits / auto-rename / refuse).

No Qt, no dialogs, no drag-drop event handling.  Those live in
``scriptree.shell`` and ``scriptree.ui``.  This module returns
``InstallResult`` records and raises ``InstallError`` on the
small set of unrecoverable conditions; the caller composes
a UX flow on top.

## For maintainers / LLMs

* Module is in ``scriptree.core``.  Stdlib-only, Qt-free.  Test
  suite uses ``tmp_path`` and ``zipfile`` -- runs headlessly.
* The four conflict modes are an enum so the UI dialog and the
  install function can compare equal without string typos.  Add
  modes here when adding UI options, never on a hot path.
* "Update" mode -- the user's specific request -- is defined as
  "replace every file that exists in source; LEAVE intact every
  file in target that's not in source."  This preserves
  ``.scriptree.configs.json`` sidecars the user has hand-edited.
  Not a full file-by-file diff -- a simple existence-in-source
  test, which matches how the user actually works.
* Source-shape detection for zips is intentionally conservative:
  a zip whose top level is ONE directory whose name matches the
  zip basename (case-insensitive, ignoring ``.zip``) is treated
  as "wrapped".  Anything else is "flat" and we wrap on
  extraction.  Edge cases (a zip with one weird folder name)
  fall to the flat path, which means the contents go inside a
  folder named after the zip -- a harmless if slightly awkward
  result the user can rename.
* Symlinks inside zips are NOT followed during extract.  The
  ``zipfile`` stdlib has documented CVE history; we use
  ``ZipFile.extractall`` after explicit member sanitisation
  rather than rolling our own.  See ``_safe_extract_members``
  for the path-traversal guard.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class ConflictMode(str, Enum):
    """How to handle an existing target folder during install.

    String-valued so the UI dialog can persist user choices as
    plain JSON without an int-to-name mapping layer.
    """
    OVERWRITE = "overwrite"
    """Delete the existing target tree, then copy/extract fresh.
    Destructive -- the user is expected to have confirmed via the
    UI before this mode reaches the install function."""

    UPDATE = "update"
    """File-by-file: for each file in the source, replace or
    create at the target; for every file in target whose name
    isn't in source, leave intact.  Preserves user-edited
    sidecars across re-installs.  See module docstring for
    the full semantics."""

    RENAME = "rename"
    """Pick the next available ``<base>-2``, ``<base>-3``, ...
    target folder name and install there.  The originating
    target stays untouched.  Reported in ``InstallResult.target``
    so the caller can see where the install actually landed."""

    CANCEL = "cancel"
    """Caller signal that the install was aborted.  ``install_app``
    raises ``InstallError`` immediately when handed this mode."""


@dataclass(frozen=True)
class InstallResult:
    """What ``install_app`` did on disk.

    Returned to the caller so the post-install hook (e.g. the
    forest's ``refresh_from_sources``) has the exact path that
    landed.  ``conflict_resolved`` is the mode actually applied
    -- equal to the caller's request except when the request
    was ``None`` (no conflict was detected on this run).
    """

    target: Path
    """The directory the install wrote to.  Absolute, resolved.
    May differ from the caller's requested name when
    ``RENAME`` produced an ``<app>-N`` variant."""

    files_written: int
    """Count of files the install copied / extracted, useful for
    a "Installed N files" UI confirmation toast."""

    conflict_resolved: ConflictMode | None
    """The mode applied when a conflict existed; ``None`` when
    the target didn't exist before this call."""


class InstallError(RuntimeError):
    """Raised when ``install_app`` cannot complete.

    Distinct from generic ``OSError`` / ``zipfile.BadZipFile``
    so callers can pin the error to "install-specific" vs
    "filesystem went sideways."  Reasons that surface this:

    * Source path doesn't exist.
    * Source is neither a directory nor a recognised zip.
    * ``ConflictMode.CANCEL`` was passed (caller's choice).
    * Path-traversal attempt detected inside a zip
      (``..`` segments, absolute paths).
    """


# ---------------------------------------------------------------------------
# Default install roots
# ---------------------------------------------------------------------------

def default_shared_root() -> Path:
    """Default shared install location.

    Resolution order:

    1. ``install.shared_root`` key in ``scriptree.ini`` (the
       portable INI managed by ``scriptree.core.app_settings``).
       Honoured when the value is non-empty and points at a
       directory that either already exists or whose parent is
       writable.
    2. ``<ScripTree install>/ScripTreeApps/`` -- travels with
       the install, so a USB-portable ScripTree install + apps
       directory works without cloud sync.

    The returned path is NOT created on call -- callers that
    want the dir to exist should call ``Path.mkdir(parents=True,
    exist_ok=True)`` themselves.  Keeps the helper pure.
    """
    custom = _settings_string("install.shared_root").strip()
    if custom:
        return Path(custom)
    # Locate the ScripTree app dir via the existing helper to
    # share its resolution rules (same parent walk, same
    # symlink semantics).
    from .app_settings import _find_scriptree_dir
    return _find_scriptree_dir() / "ScripTreeApps"


def default_personal_root() -> Path:
    """Default personal install location.

    Resolution order:

    1. ``install.personal_root`` key in ``scriptree.ini`` --
       same override mechanism as ``default_shared_root``.
    2. OS-specific per-user app-data location:
       * Windows: ``%LOCALAPPDATA%\\ScripTree\\Apps\\``
       * macOS:   ``~/Library/Application Support/ScripTree/Apps/``
       * Linux:   ``$XDG_DATA_HOME/ScripTree/Apps/`` if set,
                  else ``~/.local/share/ScripTree/Apps/``

    The fall-back logic uses ``scriptree.core.platform.host_os``
    rather than ``sys.platform`` raw values so the three-value
    OS id stays canonical across the codebase.
    """
    custom = _settings_string("install.personal_root").strip()
    if custom:
        return Path(custom)

    from .platform import host_os

    os_id = host_os()
    if os_id == "windows":
        # ``%LOCALAPPDATA%`` is the canonical per-user-no-roam
        # store on Windows; ``%APPDATA%`` (roaming) is for things
        # that should sync between machines via the domain.
        # Installed CLI tools rarely benefit from roaming.
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "ScripTree" / "Apps"
        # Fallback for an unusual env: user home.
        return Path.home() / ".scriptree" / "apps"
    if os_id == "macos":
        return (
            Path.home()
            / "Library" / "Application Support" / "ScripTree" / "Apps"
        )
    # Linux / unknown
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg:
        return Path(xdg) / "ScripTree" / "Apps"
    return Path.home() / ".local" / "share" / "ScripTree" / "Apps"


def effective_forest_roots(user_roots: list[str]) -> list[str]:
    """Return the discovery roots the forest should actually scan,
    combining the user's configured roots with the per-machine
    personal-apps directory.

    Why a runtime helper rather than baking the personal path into
    ``AutoDiscoverConfig.roots``'s default factory:

    * ``AutoDiscoverConfig.roots`` is serialised into every
      ``.scriptreeforest`` file.  Baking a machine-specific path into
      the default (``%LOCALAPPDATA%/ScripTree/Apps`` on Windows etc.)
      would write that path into the JSON the first time a forest is
      saved, then re-opening that same forest on a different machine
      (or under a different user) would scan a stale, wrong-machine
      path.  Forests are meant to travel with the user.
    * The personal-apps root is "where this user just dropped an app
      via the drop-install dialog" — it must always be scanned, even
      on legacy forests written before this feature, even when the
      user has hand-edited ``roots`` and forgotten to add it.  Adding
      it at resolution time (not at config-load time) gives us that
      guarantee without mutating the user's config.
    * The user can still REMOVE the personal apps directory from
      discovery by adding its path to ``ForestDef.excluded`` (per-app
      paths).  This helper does not check ``excluded`` — that's
      ``discover()``'s job downstream, and the contract there
      already handles "user excluded this path".

    The returned list:

    * keeps the user-configured entries first (preserving their
      ordering, so the priority-rule walker still sees them in the
      order the user wrote them);
    * appends the personal-apps directory unless it is already
      present (case-insensitive compare on resolved absolute paths,
      so ``"~/.local/share/ScripTree/Apps"`` and the same path
      already absolutified don't duplicate).

    Non-existent personal-apps directories are returned anyway —
    ``discover()`` already silently skips roots that don't exist
    on disk, and returning the path means "if the user creates it
    later, the next scan picks it up automatically without a
    config edit".
    """
    out = list(user_roots)
    try:
        personal = default_personal_root().resolve()
    except Exception:  # noqa: BLE001
        # Should never happen, but a malformed env var ought not to
        # break forest discovery.  Falling through with just the
        # user roots is the safe behaviour.
        return out

    personal_norm = str(personal).casefold()
    for existing in user_roots:
        try:
            ep = Path(existing).expanduser()
            if not ep.is_absolute():
                from scriptree.shell.forest_io import _project_root
                ep = (_project_root() / ep).resolve()
            else:
                ep = ep.resolve()
            if str(ep).casefold() == personal_norm:
                return out
        except Exception:  # noqa: BLE001
            # If we can't resolve an entry (e.g. invalid syntax),
            # treat it as "not the personal root" and continue.
            continue
    out.append(str(personal))
    return out


def _settings_string(key: str) -> str:
    """Read a string from ``scriptree.ini``.  Returns ``""`` when
    the key is absent / QSettings unavailable / any other read
    failure -- this helper is informational, not load-bearing.
    """
    try:
        from .app_settings import get_settings
        return str(get_settings().value(key, "", type=str))
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Source-shape detection
# ---------------------------------------------------------------------------

# Filesystem-unfriendly characters to scrub from an inferred app
# name.  Keeps the result usable as a directory name on every OS
# without losing too much human-readability.
_UNSAFE_NAME_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


def infer_app_name(source: Path) -> str:
    """Pick a target folder name from the dropped source.

    * Folder source: returns ``source.name`` (the basename).
    * Zip source: returns ``source.stem`` (filename minus ``.zip``).

    The result is then scrubbed for filesystem-unsafe characters:
    ``<>:"|?*`` and control chars are replaced with ``_``.  No
    other normalisation -- the user picked the source name
    deliberately and we shouldn't second-guess case / spaces.
    """
    if source.is_dir():
        name = source.name
    else:
        # Strip ``.zip`` (case-insensitive).  ``Path.stem``
        # handles that by default.
        name = source.stem
    if not name:
        name = "App"
    return _UNSAFE_NAME_CHARS.sub("_", name)


def _zip_top_level(zf: zipfile.ZipFile) -> set[str]:
    """Return the set of top-level path components inside ``zf``.

    Used by ``_zip_is_wrapped`` to detect single-folder-wrapper
    archives.  Skips empty member names (sometimes produced by
    archive tools when storing a directory entry without
    contents) so they don't artificially inflate the count.
    """
    out: set[str] = set()
    for name in zf.namelist():
        cleaned = name.replace("\\", "/").lstrip("./")
        if not cleaned:
            continue
        first = cleaned.split("/", 1)[0]
        if first:
            out.add(first)
    return out


def _zip_is_wrapped(zf: zipfile.ZipFile, expected_name: str) -> bool:
    """``True`` when the zip has exactly one top-level directory
    matching ``expected_name`` (case-insensitive).

    The expected-name match is intentionally narrow: a zip
    called ``my-tool.zip`` whose contents start with a
    ``my-tool/`` folder is "wrapped"; one whose contents start
    with ``totally-different-name/`` is treated as "flat" and
    re-wrapped in a folder named after the zip on extract.
    Without the name check, an archive that happens to put one
    folder at its root for unrelated reasons (e.g.
    ``__MACOSX/``) would silently swallow the wrap step.
    """
    tops = _zip_top_level(zf)
    if len(tops) != 1:
        return False
    only = next(iter(tops)).lower()
    return only == expected_name.lower()


# ---------------------------------------------------------------------------
# Conflict resolution -- target folder selection
# ---------------------------------------------------------------------------

def pick_rename_target(
    target_root: Path, base_name: str,
) -> Path:
    """Find the next available ``<base>-N`` slot under
    ``target_root``.

    Used by ``ConflictMode.RENAME``.  Tries ``<base>-2`` first,
    then ``-3``, ..., stopping at the first slot that doesn't
    exist.  Caps at 999 to prevent a pathological infinite loop;
    when capped, returns the un-numbered base name and lets the
    caller's existence check fail naturally with a sensible
    error (rather than spinning forever).
    """
    for n in range(2, 1000):
        candidate = target_root / f"{base_name}-{n}"
        if not candidate.exists():
            return candidate
    return target_root / base_name


# ---------------------------------------------------------------------------
# The install operation
# ---------------------------------------------------------------------------

def _safe_extract_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Filter ``zf``'s members for path-traversal safety.

    Drops any member whose name contains ``..`` path components
    or starts with ``/`` -- both of which would let a hostile
    zip write outside the target directory.  Also drops members
    whose name is empty after normalisation.

    Returns the filtered list; the caller passes it to
    ``zf.extractall(members=...)``.
    """
    safe: list[zipfile.ZipInfo] = []
    for info in zf.infolist():
        # Normalise slashes for the safety check; the OS will
        # use its own separator during extraction.
        normalised = info.filename.replace("\\", "/")
        if not normalised:
            continue
        if normalised.startswith("/"):
            raise InstallError(
                f"Zip member starts with absolute path: "
                f"{info.filename!r}"
            )
        if ".." in normalised.split("/"):
            raise InstallError(
                f"Zip member contains '..' path component: "
                f"{info.filename!r}"
            )
        safe.append(info)
    return safe


def _copy_or_extract(
    source: Path,
    target: Path,
    *,
    app_name: str,
) -> int:
    """Copy a folder OR extract a zip into ``target``.

    Returns the count of files placed.  Caller is responsible
    for ensuring ``target`` is empty (the conflict-resolution
    layer above this function makes that guarantee).

    Folder source: deep copy via ``shutil.copytree``.
    Zip source: extract via ``zipfile.ZipFile.extractall`` after
    the path-traversal filter.  Auto-detects whether the zip is
    already wrapped (one top-level dir named ``app_name``) and
    strips the wrapper so files land at ``target/`` rather than
    ``target/app_name/`` -- consistent with the folder-source
    behaviour.
    """
    target.mkdir(parents=True, exist_ok=True)

    if source.is_dir():
        # copytree expects target to NOT exist when dirs_exist_ok
        # is False; we've already mkdir'd, so use dirs_exist_ok.
        shutil.copytree(source, target, dirs_exist_ok=True)
        return _count_files(target)

    # Zip path.
    with zipfile.ZipFile(source, "r") as zf:
        members = _safe_extract_members(zf)
        wrapped = _zip_is_wrapped(zf, app_name)
        if wrapped:
            # Strip the wrapper directory.  Extract each member
            # to a relocated path under ``target``.
            wrapper_prefix = next(iter(_zip_top_level(zf))) + "/"
            count = 0
            for info in members:
                rel = info.filename.replace("\\", "/")
                if not rel.startswith(wrapper_prefix):
                    # Directory entry for the wrapper itself.
                    continue
                stripped = rel[len(wrapper_prefix):]
                if not stripped:
                    continue
                # Reconstruct on the local FS using OS sep.
                out_path = target / Path(stripped)
                if info.is_dir() or rel.endswith("/"):
                    out_path.mkdir(parents=True, exist_ok=True)
                    continue
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(out_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                count += 1
            return count
        # Flat zip -- extract straight into target.
        zf.extractall(target, members=members)
        return _count_files(target)


def _count_files(root: Path) -> int:
    """Recursive file-count helper for the ``InstallResult``.

    Counts regular files only (skips dirs, links, sockets).
    Best-effort: an ``OSError`` walking the tree returns the
    partial count rather than raising -- callers use the count
    for a UI confirmation, not for correctness."""
    total = 0
    try:
        for _root, _dirs, files in os.walk(root):
            total += len(files)
    except OSError:
        pass
    return total


def install_app(
    source: Path | str,
    target_root: Path | str,
    *,
    conflict_mode: ConflictMode | None = None,
) -> InstallResult:
    """Install ``source`` (a folder or zip) into ``target_root``.

    Parameters
    ----------
    source:
        Path to a directory or a ``.zip`` file.  Anything else
        raises ``InstallError``.
    target_root:
        Directory under which the new app folder lands.  The
        actual install path is
        ``target_root / infer_app_name(source)``.  Created if
        missing.
    conflict_mode:
        How to handle an existing target.  When ``None`` and
        the target exists, raises ``InstallError`` so the caller
        knows to prompt the user.  When set to one of the
        ``ConflictMode`` values, applies that strategy.

    Returns
    -------
    ``InstallResult`` carrying the final on-disk path (may
    differ from the requested one under ``RENAME``), the file
    count, and the conflict mode that was actually applied.

    Raises
    ------
    ``InstallError`` for unrecoverable conditions: missing
    source, unsupported source type, ``ConflictMode.CANCEL``,
    or a path-traversal attempt inside a zip.

    Does NOT mutate the forest.  Caller is responsible for
    triggering ``refresh_from_sources()`` on the relevant
    controller after a successful install.
    """
    src = Path(source).resolve()
    if not src.exists():
        raise InstallError(f"Source does not exist: {src}")

    is_dir = src.is_dir()
    is_zip = src.is_file() and src.suffix.lower() == ".zip"
    if not (is_dir or is_zip):
        raise InstallError(
            f"Source must be a folder or .zip: {src}"
        )

    if conflict_mode is ConflictMode.CANCEL:
        raise InstallError("Install cancelled by caller.")

    root = Path(target_root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    app_name = infer_app_name(src)
    requested_target = root / app_name

    # Conflict resolution.
    target = requested_target
    conflict_applied: ConflictMode | None = None

    if requested_target.exists():
        if conflict_mode is None:
            raise InstallError(
                f"Target already exists: {requested_target}.  "
                f"Pass a ``conflict_mode`` to choose how to "
                f"proceed."
            )
        conflict_applied = conflict_mode
        if conflict_mode is ConflictMode.OVERWRITE:
            shutil.rmtree(requested_target)
        elif conflict_mode is ConflictMode.UPDATE:
            # UPDATE is the only mode that doesn't recreate
            # target.  ``_copy_or_extract`` writes into an
            # existing dir; ``copytree`` with
            # ``dirs_exist_ok=True`` overwrites matching files
            # and leaves the rest.  For zip sources we extract
            # directly into the existing target; files in the
            # archive overwrite, files outside it survive.
            pass  # leave requested_target in place
        elif conflict_mode is ConflictMode.RENAME:
            target = pick_rename_target(root, app_name)

    files_written = _copy_or_extract(src, target, app_name=app_name)

    return InstallResult(
        target=target,
        files_written=files_written,
        conflict_resolved=conflict_applied,
    )


__all__ = [
    "ConflictMode",
    "InstallError",
    "InstallResult",
    "default_personal_root",
    "default_shared_root",
    "effective_forest_roots",
    "infer_app_name",
    "install_app",
    "pick_rename_target",
]
