"""
forest_io.py — read / write ``.scriptreeforest`` files.

## For humans

A **forest** is the new top-level container introduced in ScripTree
v0.3.14.  It sits one layer above ``.scriptreering`` (which contains
cells) and ``.scriptreetree`` / ``.scriptree`` (single-cell catalogs).
The forest holds:

  * **items**: a flat list of paths to load — one entry per ring,
    tree, or single tool that should appear on screen.  Each entry
    carries enough state for the launcher to reconstruct the on-
    screen layout (position, rough role hint).
  * **excluded**: paths the user has explicitly removed from the
    forest.  Auto-discovery skips these — solving the "auto-add
    keeps re-adding things I deleted" footgun.  Re-including is a
    deliberate user action via the settings dialog.
  * **auto_discover**: configuration for the auto-discovery /
    update-checking subsystem.  See ``forest_discover.py`` for the
    walker that consumes these settings.
  * **schema_version**: bumped if the file shape changes.

File format
-----------
JSON.  Roughly::

    {
      "format": "scriptreeforest",
      "version": 1,
      "name": "My Engineering Forest",
      "saved_at": "2026-05-08T14:32:11Z",
      "items": [
        {"path": "ScripTreeApps/SolidWorks/sw.scriptreering",
         "kind": "ring",
         "position": [120, 180]},
        ...
      ],
      "excluded": [
        "ScripTreeApps/Demos/find-replace/find-replace.scriptree"
      ],
      "auto_discover": {
        "enabled": true,
        "roots": ["ScripTreeApps"],
        "include": ["scriptreering", "scriptreetree", "scriptree"],
        "update_mode": "prompt"
      }
    }

All paths are stored **relative to the project root** when possible
(so a forest file checked into a repo travels with the source); we
fall back to absolute paths when the referenced item lives outside
the project tree.  Resolution at load time tries the relative-to-
forest-file form first, then the relative-to-project-root form,
then absolute.

Public API
----------
    save_forest(forest, path)             → None
    load_forest(path)                     → ForestDef
    default_autoload_path(branding)       → Path  (per-user state file)
    list_autoload_forest(branding)        → ForestDef | None

## For maintainers / LLMs

- The ``.scriptreeforest`` file carries its OWN ``"format"`` /
  ``"version"`` (``scriptreeforest`` / ``1``).  This is INDEPENDENT of
  the main editor's schema_version and of ``.scriptreering``'s version.
  ``ForestDef.schema_version`` is set from the file's ``version`` field
  at load; ``load_forest`` only LOGS on a version mismatch and proceeds
  (forward-compat slot) — it does not migrate or reject. Bump ``_VERSION``
  *and* add real migration logic if the on-disk shape ever changes.
- v0.5.2 renamed the per-user default file from
  ``last_forest.scriptreeforest`` to ``default.scriptreeforest``.
  ``migrate_legacy_autoload_path`` is the ONE-SHOT migration the
  launcher calls at startup. It is idempotent: no-op if the new path
  exists OR the legacy one doesn't. ``os.rename`` is used (not copy) so
  it must be same-volume — APPDATA always is. A failed rename is logged
  and returns ``None`` (treated as "no migration"); the launcher then
  proceeds and may create a fresh empty default, silently orphaning the
  legacy file's contents. Keep the existence guard order (new first).
- ``_project_root`` here is a THIRD copy of the walk-up heuristic
  (alongside ``branding_loader`` and ``ring_io``). The docstring says
  "keep in sync with ring_io._project_root". Unlike ``branding_loader``
  it FALLS BACK to ``Path.cwd()`` instead of raising — relied on by
  ``save_forest``/``_resolve_for_load`` to never blow up at the path
  layer.
- Path storage: ``_to_relative_if_possible`` stores paths relative to
  the project root with forward slashes when the target is under it,
  absolute otherwise. ``_resolve_for_load`` reverses it in order:
  absolute as-is → relative-to-forest-file → relative-to-project-root →
  as-given. Resolution happens at LOAD time so callers get absolute
  ``ForestItem.path``. The save-time ``path`` expression has a redundant
  ``X if cond else X`` ternary — both branches identical; harmless,
  effectively always ``_to_relative_if_possible(..., root)``.
- ``default_autoload_path`` is platform-branched (Roaming on win32,
  Application Support on darwin, ``~/.config`` elsewhere) and keyed on
  ``branding["appName"]`` (default "ScripTree"). Changing appName
  re-homes every per-user file — by design, but it orphans old state.
- ``forest_preferences.json`` is a SEPARATE concern from any forest
  file: it only tells the launcher where to look next time
  (``fallback_to_default`` + ``default_forest_path``). Editing it moves
  no data. ``ForestPreferences.resolved_default_path`` folds the
  "empty string = canonical path" rule — callers must not re-implement.
- ``save_forest`` mutates its argument: it sets
  ``forest.loaded_from = str(path.resolve())`` after writing. Callers
  relying on the pre-save ``loaded_from`` must capture it first.
- All reads/writes pin ``encoding="utf-8"``; keep it (brand/app names
  and user paths are non-ASCII-capable). ``save_*`` ``mkdir(parents=
  True, exist_ok=True)`` so first write to a fresh APPDATA works.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


_FORMAT = "scriptreeforest"
_VERSION = 1


def _log(msg: str) -> None:
    print(f"[forest_io] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

ItemKind = Literal["ring", "tree", "tool"]
"""
A forest item is one of:

  * ``ring`` — a ``.scriptreering`` file (a master + member layout).
  * ``tree`` — a ``.scriptreetree`` file (a folder of tools, bound to
    a single cell).
  * ``tool`` — a ``.scriptree`` file (one tool, bound to a single cell).
"""

UpdateMode = Literal["off", "auto", "prompt"]
"""
``off``    — auto-discovery never runs after the initial populate.
``auto``   — auto-discovery runs at launch and on Refresh; changes
             apply silently.
``prompt`` — auto-discovery runs at launch and on Refresh; the user
             gets a checkbox dialog to confirm adds / removes /
             re-includes.
"""


@dataclass
class ForestItem:
    """One thing on screen that the forest tracks."""

    path: str
    """Path to the source file.  Stored relative to the project root
    when possible, absolute otherwise.  See module docstring."""

    kind: ItemKind = "ring"
    """What layer this item is.  Determines how the launcher loads it
    (``load_ring`` vs binding a single cell to a tree/tool)."""

    position: tuple[int, int] | None = None
    """On-screen ``(x, y)`` for the master cell / standalone cell.
    ``None`` means "let the layout engine choose"."""

    catalog_path: str | None = None
    """For ``kind in ('tree', 'tool')``, the catalog the cell is bound
    to.  Usually identical to ``path`` — kept separate so the field
    is consistent with how single-cell standalones are tracked."""


@dataclass
class AutoDiscoverConfig:
    """User-tunable settings for the discovery / update-checking flow."""

    enabled: bool = True
    """When False, neither launch-time nor manual Refresh runs the
    discovery walker.  The user's hand-curated forest stays
    untouched."""

    roots: list[str] = field(
        default_factory=lambda: ["ScripTreeApps", "../ScripTreeApps"]
    )
    """Folders to scan, relative to the project root (or absolute).

    Default: two paths, both resolved at discovery time against the
    project root (the directory containing
    ``branding/branding.config.json``):

      1. ``ScripTreeApps``      — apps living inside the ScripTree
                                  install (the in-source layout).
      2. ``../ScripTreeApps``   — apps sibling to the ScripTree
                                  folder (lets a deployment keep
                                  ScripTreeApps outside the
                                  install — e.g. checked into a
                                  separate repo, mounted via a
                                  symlink, or kept on a shared
                                  team drive).

    Folders that don't exist are skipped silently by ``discover``
    — both defaults can be present without producing errors if
    only one (or neither) of the two layouts is realised on a
    given machine.

    The forest settings dialog lets the user add / remove entries.
    Relative paths re-resolve against the project root every time
    discovery runs, so moving the ScripTree install picks up the
    new sibling automatically."""

    include: list[ItemKind] = field(
        default_factory=lambda: ["ring", "tree", "tool"]
    )
    """Which item kinds the priority-rule walker is allowed to add.
    All three by default — the priority rule already prevents
    duplication (one folder picks ONE highest-layer item)."""

    update_mode: UpdateMode = "prompt"
    """How discovery applies its diff.  See ``UpdateMode`` docstring."""


@dataclass
class ForestDef:
    """In-memory representation of a ``.scriptreeforest`` file."""

    name: str = "Forest"
    items: list[ForestItem] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    auto_discover: AutoDiscoverConfig = field(default_factory=AutoDiscoverConfig)
    schema_version: int = _VERSION
    """Path of the .scriptreeforest the forest was loaded from.  Set
    by ``load_forest``; ``None`` for forests created in memory."""
    loaded_from: str | None = None


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    """Walk up from this file until we find ``branding/branding.config.json``.

    Same heuristic as ``ring_io._project_root`` — keep them in sync.
    """
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / "branding" / "branding.config.json").is_file():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    # Fall back to the cwd; the caller can override via absolute paths.
    return Path.cwd()


def _to_relative_if_possible(target: Path, anchor: Path) -> str:
    """Return ``target`` relative to ``anchor`` when target lives under
    anchor's tree; otherwise the absolute path.  Always uses forward
    slashes so cross-platform diffs of the JSON stay clean."""
    try:
        rel = target.resolve().relative_to(anchor.resolve())
        return str(rel).replace("\\", "/")
    except ValueError:
        return str(target.resolve()).replace("\\", "/")


def _resolve_for_load(stored: str, forest_file: Path | None) -> Path:
    """Reverse of ``_to_relative_if_possible``.

    Resolution order:
      1. If ``stored`` is absolute, use it as-is.
      2. Try relative to the ``.scriptreeforest`` file's directory
         (lets a forest checked into a project travel with sources).
      3. Try relative to the project root.
      4. Fall back to ``stored`` as-given (relative to CWD); the
         caller's existence check will surface "not found" cleanly.
    """
    p = Path(stored)
    if p.is_absolute():
        return p
    if forest_file is not None:
        cand = (forest_file.parent / p).resolve()
        if cand.exists():
            return cand
    cand = (_project_root() / p).resolve()
    if cand.exists():
        return cand
    return p


# ---------------------------------------------------------------------------
# Detection helper — used by both io and the discovery walker
# ---------------------------------------------------------------------------

# Suffixes that ScripTree recognises, ordered HIGHEST LAYER FIRST.
# The discovery walker uses this exact order to enforce the priority
# rule "if a folder has a ring, take the ring; else a tree; else a
# tool".  Centralised here so both io and discovery agree on what
# beats what.
SUFFIX_PRIORITY: tuple[tuple[str, ItemKind], ...] = (
    (".scriptreering", "ring"),
    (".scriptreetree", "tree"),
    (".scriptree", "tool"),
)


def kind_for_suffix(path: str | Path) -> ItemKind | None:
    """Return ``ItemKind`` for a file suffix, or ``None`` if not one
    of the recognised types.  Suffix match is case-insensitive."""
    s = str(path).lower()
    # Order matters: ``.scriptreetree`` ends in ``.scriptree`` too,
    # so we test the longer suffixes first.
    for suffix, kind in SUFFIX_PRIORITY:
        if s.endswith(suffix):
            return kind
    return None


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_forest(forest: ForestDef, path: str | Path) -> None:
    """Serialise ``forest`` to a ``.scriptreeforest`` JSON file."""
    path = Path(path)
    root = _project_root()

    items_d: list[dict] = []
    for it in forest.items:
        # L8 fix: was a ternary whose two branches were identical
        # (``X if not is_absolute() else X``) — the is_absolute()
        # test had no effect.  ``_to_relative_if_possible`` already
        # handles both absolute and relative inputs correctly, so
        # call it unconditionally.
        d = {
            "path": _to_relative_if_possible(Path(it.path), root),
            "kind": it.kind,
        }
        if it.position is not None:
            d["position"] = list(it.position)
        if it.catalog_path:
            d["catalog_path"] = _to_relative_if_possible(
                Path(it.catalog_path), root,
            )
        items_d.append(d)

    excluded_d = [
        _to_relative_if_possible(Path(e), root) for e in forest.excluded
    ]

    auto_d = {
        "enabled": bool(forest.auto_discover.enabled),
        "roots": list(forest.auto_discover.roots),
        "include": list(forest.auto_discover.include),
        "update_mode": forest.auto_discover.update_mode,
    }

    blob = {
        "format": _FORMAT,
        "version": _VERSION,
        "name": forest.name,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": items_d,
        "excluded": excluded_d,
        "auto_discover": auto_d,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    forest.loaded_from = str(path.resolve())
    _log(f"save_forest: wrote {path}")


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_forest(path: str | Path) -> ForestDef:
    """Read a ``.scriptreeforest`` file and return a ``ForestDef``.

    Raises ``FileNotFoundError`` on missing file, ``ValueError`` on
    schema errors.  Per-item path resolution happens at load time so
    callers receive absolute paths in ``ForestItem.path``.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"load_forest: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    fmt = raw.get("format")
    if fmt != _FORMAT:
        raise ValueError(
            f"load_forest: unexpected format {fmt!r} (expected {_FORMAT!r})"
        )
    ver = raw.get("version", 1)
    if ver != _VERSION:
        # Keep going — we may add forward-compat later.  For now
        # log and trust the file.
        _log(f"load_forest: version {ver} (expected {_VERSION}); proceeding")

    items: list[ForestItem] = []
    for d in raw.get("items", []):
        if not isinstance(d, dict):
            continue
        stored_path = str(d.get("path", "")).strip()
        if not stored_path:
            continue
        resolved = _resolve_for_load(stored_path, path)
        kind = d.get("kind") or kind_for_suffix(resolved) or "tool"
        pos = d.get("position")
        if isinstance(pos, list) and len(pos) == 2:
            try:
                pos = (int(pos[0]), int(pos[1]))
            except (TypeError, ValueError):
                pos = None
        else:
            pos = None
        catalog = d.get("catalog_path")
        if catalog:
            catalog = str(_resolve_for_load(str(catalog), path))
        items.append(ForestItem(
            path=str(resolved),
            kind=kind,  # type: ignore[arg-type]
            position=pos,
            catalog_path=catalog,
        ))

    excluded = [
        str(_resolve_for_load(str(e), path))
        for e in raw.get("excluded", [])
        if isinstance(e, str) and e.strip()
    ]

    auto_raw = raw.get("auto_discover") or {}
    update_mode = auto_raw.get("update_mode", "prompt")
    if update_mode not in ("off", "auto", "prompt"):
        update_mode = "prompt"
    include_raw = auto_raw.get("include") or ["ring", "tree", "tool"]
    include = [
        k for k in include_raw if k in ("ring", "tree", "tool")
    ] or ["ring", "tree", "tool"]
    auto = AutoDiscoverConfig(
        enabled=bool(auto_raw.get("enabled", True)),
        roots=[str(r) for r in (auto_raw.get("roots") or ["ScripTreeApps"])],
        include=include,  # type: ignore[arg-type]
        update_mode=update_mode,  # type: ignore[arg-type]
    )

    forest = ForestDef(
        name=str(raw.get("name", "Forest")),
        items=items,
        excluded=excluded,
        auto_discover=auto,
        schema_version=ver,
        loaded_from=str(path.resolve()),
    )
    return forest


# ---------------------------------------------------------------------------
# Per-user autoload state
# ---------------------------------------------------------------------------

_DEFAULT_FOREST_FILENAME = "default.scriptreeforest"
"""Canonical filename for the per-user default forest.

v0.5.2 — renamed from ``last_forest.scriptreeforest`` so the file's
purpose is obvious to anyone poking around APPDATA.  A legacy file
with the old name is auto-migrated by
:func:`migrate_legacy_autoload_path`.
"""

_LEGACY_FOREST_FILENAME = "last_forest.scriptreeforest"


def default_autoload_path(branding: dict) -> Path:
    """Where the per-user default forest file lives.

    Mirror of ``ring_io._appdata_dir`` for the forest layer.  The
    file is **always** written to the user-scoped state directory;
    a system-wide default is out of scope (rings already cover the
    "shared session" case via their own autoload list).

    v0.5.2 — file is now ``default.scriptreeforest``.  Previous
    installs wrote ``last_forest.scriptreeforest``; that path is
    rehomed transparently by :func:`migrate_legacy_autoload_path`,
    which the launcher calls at startup.
    """
    brand_name = branding.get("appName", "ScripTree")
    if sys.platform == "win32":
        appdata = Path.home() / "AppData" / "Roaming" / brand_name
    elif sys.platform == "darwin":
        appdata = Path.home() / "Library" / "Application Support" / brand_name
    else:
        appdata = Path.home() / ".config" / brand_name
    return appdata / _DEFAULT_FOREST_FILENAME


def migrate_legacy_autoload_path(branding: dict) -> Path | None:
    """One-shot rename of legacy ``last_forest.scriptreeforest`` to
    the v0.5.2 ``default.scriptreeforest``.

    Idempotent: if the new path already exists OR the legacy one
    doesn't, this is a no-op.  Returns the path that was renamed
    (for logging), or ``None`` if no migration happened.

    Called by the launcher at startup so the rest of the code can
    assume the canonical filename without scattering legacy probes
    everywhere.
    """
    new_path = default_autoload_path(branding)
    legacy_path = new_path.parent / _LEGACY_FOREST_FILENAME
    if new_path.is_file():
        return None  # Already migrated (or fresh install).
    if not legacy_path.is_file():
        return None  # Nothing to migrate.
    try:
        legacy_path.rename(new_path)
        _log(f"migrate_legacy_autoload_path: {legacy_path} -> {new_path}")
        return legacy_path
    except OSError as exc:
        # L9 fix: a bare `rename` failure (e.g. the legacy file is
        # transiently locked by an AV scanner / sync client) used to
        # return None — the launcher then treated it as "nothing to
        # migrate" and `start()` created a FRESH EMPTY
        # default.scriptreeforest, silently orphaning the user's
        # previous forest.  Fall back to a copy so the user's data
        # still arrives at the new path; only the legacy file lingers
        # (harmless, ignored from now on).
        _log(
            f"migrate_legacy_autoload_path: rename failed "
            f"({legacy_path} -> {new_path}): {exc!r}; trying copy"
        )
        try:
            import shutil
            shutil.copy2(legacy_path, new_path)
            _log(
                f"migrate_legacy_autoload_path: copied {legacy_path} "
                f"-> {new_path} (legacy left in place)"
            )
            return legacy_path
        except OSError as exc2:
            _log(
                f"migrate_legacy_autoload_path: copy fallback also "
                f"failed: {exc2!r}; legacy forest NOT migrated"
            )
            return None


def list_autoload_forest(branding: dict) -> ForestDef | None:
    """Return the per-user "last forest" if one exists, else None.

    Used by the launcher to restore the user's previous session
    automatically — same UX rhythm as ``list_autoload_rings``.
    """
    p = default_autoload_path(branding)
    if not p.is_file():
        return None
    try:
        return load_forest(p)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _log(f"list_autoload_forest: {p}: {exc!r}")
        return None


# ---------------------------------------------------------------------------
# Per-user preferences (V3 v0.3.21+)
# ---------------------------------------------------------------------------
#
# ``forest_preferences.json`` lives in the same per-user state
# directory as ``default.scriptreeforest``.  It controls how the
# forest behaves at launch when the user doesn't pass an explicit
# ``.scriptreeforest`` path:
#
#   * ``fallback_to_default`` — when True (factory default), the
#     launcher loads the default forest file (creating it empty if
#     missing).  When False, the launcher starts with a transient
#     in-memory forest; nothing is auto-saved until the user
#     explicitly Save-As's.
#
#   * ``default_forest_path`` — absolute path to the file the
#     fallback path uses.  Empty string means "use
#     ``default_autoload_path``" (i.e. the canonical
#     ``default.scriptreeforest`` location).  Lets the user
#     point the default at a checked-in workspace file, a USB-stick
#     file, etc.
#
# Preferences are a SEPARATE concern from a given forest file —
# editing the default-path here doesn't move any data, it just tells
# the launcher where to look next time.

_PREFS_FORMAT = "scriptreeforest_prefs"
_PREFS_VERSION = 1


@dataclass
class ForestPreferences:
    """User preferences for forest-launch behaviour."""

    fallback_to_default: bool = True
    """When True (factory default), the launcher loads the default
    forest file when nothing is specified on the command line.
    When False, the launcher starts with an in-memory transient
    forest — autosave does nothing until the user Save-As's."""

    default_forest_path: str = ""
    """Absolute path to the default forest file.  Empty = use
    ``default_autoload_path`` (the canonical
    ``default.scriptreeforest`` location).  Stored as the
    user-typed string verbatim; the controller resolves at load
    time."""

    def resolved_default_path(self, branding: dict) -> Path:
        """Return the actual file path the launcher should fall
        back to.  Folds the "empty means canonical" rule so callers
        don't have to repeat it."""
        if self.default_forest_path.strip():
            return Path(self.default_forest_path).expanduser()
        return default_autoload_path(branding)


def default_preferences_path(branding: dict) -> Path:
    """Where ``forest_preferences.json`` lives — same per-user
    state directory as ``default.scriptreeforest``."""
    return default_autoload_path(branding).parent / "forest_preferences.json"


def load_preferences(branding: dict) -> ForestPreferences:
    """Read the user's forest preferences.

    Missing / unreadable files return the factory defaults
    (fallback=True, path=empty) — matching the v0.3.20 behaviour
    so first-run users get the same experience they had before
    the preference existed.
    """
    p = default_preferences_path(branding)
    if not p.is_file():
        return ForestPreferences()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _log(f"load_preferences: {p}: {exc!r}; using defaults")
        return ForestPreferences()
    fmt = raw.get("format")
    if fmt != _PREFS_FORMAT:
        _log(f"load_preferences: unexpected format {fmt!r}; using defaults")
        return ForestPreferences()
    return ForestPreferences(
        fallback_to_default=bool(raw.get("fallback_to_default", True)),
        default_forest_path=str(raw.get("default_forest_path", "") or ""),
    )


def save_preferences(prefs: ForestPreferences, branding: dict) -> None:
    """Persist ``prefs`` to disk.  Creates the parent directory if
    needed.  Idempotent — same content writes byte-identical
    output."""
    p = default_preferences_path(branding)
    p.parent.mkdir(parents=True, exist_ok=True)
    blob = {
        "format": _PREFS_FORMAT,
        "version": _PREFS_VERSION,
        "fallback_to_default": bool(prefs.fallback_to_default),
        "default_forest_path": str(prefs.default_forest_path or ""),
    }
    p.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    _log(f"save_preferences: wrote {p}")
