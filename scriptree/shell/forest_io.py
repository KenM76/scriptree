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
import os
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

    rel_offset: tuple[int, int] | None = None
    """v0.8.0a83 — this item's offset RELATIVE TO the forest hub
    (``(dx, dy)`` = item_top_left − hub_top_left), as the user last
    arranged it.  Authoritative for the remembered-layout restore on
    expand / startup / screen-rescue; ``position`` (absolute) remains the
    legacy seed / fallback.  ``None`` when the user has never deliberately
    placed this item (the layout engine tiles it).  Serialised only when
    set, so pre-a83 forests stay byte-identical."""


def _default_roots() -> list[str]:
    """Compute the factory default for ``AutoDiscoverConfig.roots``.

    Three entries, in order:

      1. ``"ScripTreeApps"``         — in-install layout
      2. ``"../ScripTreeApps"``      — sibling-to-install layout
      3. ``str(default_personal_root())`` — the host OS's per-user
         app-data directory used by the drop-install dialog's
         **Personal** target.  Resolved fresh at call time, so a
         freshly-constructed ``AutoDiscoverConfig`` always points
         at the actual on-disk path the current user would land
         apps in.

    Importing ``default_personal_root`` inside the function (rather
    than at module top) avoids a circular import: ``app_install``
    indirectly references ``forest_io`` via the launcher prelude on
    some platforms.  At call time the import has long since
    resolved.

    The list is materialised eagerly, not lazily — once a forest
    is constructed (or a new one created), its ``roots`` list is a
    plain Python list of strings the user can see and edit in the
    settings dialog.  Re-running ``_default_roots()`` is not
    expensive (path joins + a settings lookup), so we don't cache.
    """
    from scriptree.core.app_install import default_personal_root
    try:
        personal = str(default_personal_root())
    except Exception:  # noqa: BLE001
        # Should never happen in normal use, but a malformed env
        # var should not break forest construction.  Fall through
        # to just the two static roots.
        return ["ScripTreeApps", "../ScripTreeApps"]
    return ["ScripTreeApps", "../ScripTreeApps", personal]


@dataclass
class AutoDiscoverConfig:
    """User-tunable settings for the discovery / update-checking flow."""

    enabled: bool = True
    """When False, neither launch-time nor manual Refresh runs the
    discovery walker.  The user's hand-curated forest stays
    untouched."""

    roots: list[str] = field(
        default_factory=lambda: _default_roots()
    )
    """Folders to scan, relative to the project root (or absolute).

    Default: three paths, all resolved at discovery time:

      1. ``ScripTreeApps``      — apps living inside the ScripTree
                                  install (the in-source layout).
                                  Resolves against the project root
                                  (the directory containing
                                  ``branding/branding.config.json``).
      2. ``../ScripTreeApps``   — apps sibling to the ScripTree
                                  folder (lets a deployment keep
                                  ScripTreeApps outside the
                                  install — e.g. checked into a
                                  separate repo, mounted via a
                                  symlink, or kept on a shared
                                  team drive).
      3. The OS-canonical per-user app-data directory used by the
         drop-install dialog's **Personal** target (the path
         returned by
         ``scriptree.core.app_install.default_personal_root``):

           * Windows: ``%LOCALAPPDATA%\\ScripTree\\Apps``
           * macOS:   ``~/Library/Application Support/ScripTree/Apps``
           * Linux:   ``$XDG_DATA_HOME/ScripTree/Apps`` (or
                       ``~/.local/share/ScripTree/Apps``)

         Resolved on the **host machine** at default construction
         time so a forest written on one OS lists THAT OS's path
         in its JSON.  If the forest is later opened on a different
         OS, the missing path is silently skipped (see below) —
         the user can add the new-host path via the forest settings
         dialog if they want both surfaces scanned.

    Folders that don't exist are skipped silently by ``discover``
    — all three defaults can be present without producing errors
    if only some of them are realised on a given machine.  The
    user sees no message about a missing path; the walker just
    moves on.

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

    fold_single_item_categories: bool = False
    """v0.8.0a101 — when True, a category with only ONE member still gets its
    own synthesised folder (``group_by_category`` runs with
    ``min_items_to_synthesise=1``).  When False (default), a single-item
    category passes through at the TOP LEVEL — the "don't make a one-item
    folder" rule — which is why e.g. a lone ``Media/ffmpeg`` tool shows at the
    top rather than under a ``Media`` folder.  Per-forest, so a curated
    workspace can opt into folding every categorised tool while auto-discovered
    installs keep the clutter-free default."""


@dataclass
class ForestDef:
    """In-memory representation of a ``.scriptreeforest`` file."""

    name: str = "Forest"
    items: list[ForestItem] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    auto_discover: AutoDiscoverConfig = field(default_factory=AutoDiscoverConfig)
    # v0.6.7 — optional icon for the forest *hub* cell (the bare
    # master that owns the workspace).  Base64 SVG/PNG + format, same
    # convention as a catalog's cell.icon_data.  Empty by default;
    # serialised only when set so legacy .scriptreeforest files stay
    # byte-identical.
    icon_data: str = ""
    icon_format: str = ""
    # v0.6.11 — last on-screen position of the forest hub window,
    # restored on launch so the forest reopens where the user left
    # it.  ``None`` means "no preference"; the controller falls
    # back to the bottom-left of the primary screen.  Stored as a
    # plain (x, y) tuple in window coordinates.  Serialised only
    # when set so pre-v0.6.11 ``.scriptreeforest`` files stay
    # byte-identical on round-trip.
    window_position: tuple[int, int] | None = None
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
# Named-root path portability (v0.8.0a92 — design option #2)
# ---------------------------------------------------------------------------
#
# Item / catalog paths are serialised as ``(root-id, path-relative-to-that-root)``
# instead of a bare absolute path, so the absolute location is RECOMPUTED per
# context at load time — surviving a folder move, a portable<->normal toggle,
# and a cross-machine copy.  The root BASES come from the portable-aware
# resolvers (``default_personal_root`` redirects under portable mode), so the
# SAME stored ``(root, rel)`` resolves correctly in either mode and on any
# machine that has the same logical roots.
#
# Back-compat: a legacy forest stores a bare ``"path"`` (no ``"root"`` key) and
# still loads via ``_resolve_for_load``; on the next save each item is
# re-tagged with its root.  Extending this to network / browsed roots is just
# adding entries to ``known_roots`` (the single registry).

def known_roots() -> list[tuple[str, Path]]:
    """Ordered ``(root-id, absolute-base)`` pairs used to root / unroot item
    paths.  MOST-SPECIFIC FIRST (a tool under the install tree tags as
    ``install`` rather than a broader parent).  Recomputed each call so
    portable-mode redirects and per-machine bases are picked up automatically.

    Today's registry — the three well-known roots that cover the shipped
    layout; network / user-configured roots are a future addition here:
      * ``install``  — ``<project root>/ScripTreeApps`` (travels with a
        folder-copy of the install; the cross-machine-portable home).
      * ``apps``     — ``<project root>/../ScripTreeApps`` (the sibling deploy
        tree, e.g. ``R:\\Scriptreeapps``).
      * ``personal`` — ``default_personal_root()`` (per-user app-data, or the
        install-local apps root under portable mode).
    """
    from scriptree.core.app_install import default_personal_root
    pr = _project_root()
    out: list[tuple[str, Path]] = []

    def _add(rid: str, base: Path) -> None:
        try:
            rb = base.resolve()
        except OSError:
            return
        # Keep EVERY id even when two bases coincide (install == personal under
        # portable mode): forward tagging (_path_to_rooted) iterates in order so
        # the first matching id wins deterministically, while reverse lookup
        # (_rooted_to_abs) must still resolve a 'personal'-tagged item even when
        # its base now equals 'install'.  (De-duping by base would drop the id
        # and strand those items.)
        out.append((rid, rb))

    _add("install", pr / "ScripTreeApps")
    _add("apps", pr / ".." / "ScripTreeApps")
    _add("personal", default_personal_root())
    return out


def _path_to_rooted(target: Path) -> tuple[str, str] | None:
    """Return ``(root-id, forward-slash rel)`` when ``target`` lives under a
    known root; otherwise ``None`` (the caller stores a bare path)."""
    try:
        t = target.resolve()
    except OSError:
        return None
    for rid, base in known_roots():
        try:
            rel = t.relative_to(base)
        except ValueError:
            continue
        return rid, str(rel).replace("\\", "/")
    return None


def _rooted_to_abs(root_id: str, rel: str) -> Path | None:
    """Reverse of :func:`_path_to_rooted`: ``known_roots()[root_id] / rel``.
    ``None`` when this build doesn't know ``root_id`` (caller then falls back
    to the legacy resolver)."""
    for rid, base in known_roots():
        if rid == root_id:
            return (base / rel).resolve()
    return None


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
        # v0.8.0a92 — store the path as (root-id, rel-to-root) when it lives
        # under a known root, so it survives moves / portable toggle /
        # cross-machine.  Fall back to the legacy relative-or-absolute string
        # for paths under no known root (a hand-placed tool on another drive).
        d: dict = {}
        rooted = _path_to_rooted(Path(it.path))
        if rooted:
            d["root"], d["path"] = rooted
        else:
            d["path"] = _to_relative_if_possible(Path(it.path), root)
        d["kind"] = it.kind
        if it.position is not None:
            d["position"] = list(it.position)
        # v0.8.0a83 — emit the remembered offset-from-hub only when set so
        # pre-a83 forests round-trip byte-identical.
        if it.rel_offset is not None:
            d["rel_offset"] = [int(it.rel_offset[0]), int(it.rel_offset[1])]
        if it.catalog_path:
            crooted = _path_to_rooted(Path(it.catalog_path))
            if crooted:
                d["catalog_root"], d["catalog_path"] = crooted
            else:
                d["catalog_path"] = _to_relative_if_possible(
                    Path(it.catalog_path), root,
                )
        items_d.append(d)

    # v0.8.0a92 — root the excluded list the SAME way as items, so an ignored
    # copy keeps matching after a move / portable toggle / cross-machine copy
    # (items rebase to the new base; if excluded stayed absolute it would
    # desync and the ignored copy would reappear).  Each entry is a
    # ``{root, path}`` dict when it falls under a known root, else the legacy
    # string (which an old loader still reads; it just skips dict entries).
    excluded_d: list = []
    for e in forest.excluded:
        er = _path_to_rooted(Path(e))
        if er:
            excluded_d.append({"root": er[0], "path": er[1]})
        else:
            excluded_d.append(_to_relative_if_possible(Path(e), root))

    auto_d = {
        "enabled": bool(forest.auto_discover.enabled),
        "roots": list(forest.auto_discover.roots),
        "include": list(forest.auto_discover.include),
        "update_mode": forest.auto_discover.update_mode,
        "fold_single_item_categories": bool(
            forest.auto_discover.fold_single_item_categories
        ),
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
    # v0.6.7 — emit the hub icon only when set so legacy files
    # round-trip byte-identical.
    if forest.icon_data:
        blob["icon_data"] = forest.icon_data
        if forest.icon_format:
            blob["icon_format"] = forest.icon_format
    # v0.6.11 — emit the hub window position only when set.
    if forest.window_position is not None:
        wp = forest.window_position
        blob["window_position"] = [int(wp[0]), int(wp[1])]
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
        # v0.8.0a92 — a tagged item resolves via its named root (recomputed for
        # this machine / mode); an untagged legacy item via the path resolver.
        # Accept the rooted candidate only when it EXISTS, else fall through to
        # the legacy resolver — which recovers a tool co-located with the
        # forest file (a zipped/emailed workspace) that the canonical base no
        # longer points at.
        root_id = d.get("root")
        if root_id:
            cand = _rooted_to_abs(str(root_id), stored_path)
            resolved = (
                cand if (cand is not None and cand.exists())
                else _resolve_for_load(stored_path, path)
            )
        else:
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
            cat_root = d.get("catalog_root")
            if cat_root:
                ccand = _rooted_to_abs(str(cat_root), str(catalog))
                catalog = str(
                    ccand if (ccand is not None and ccand.exists())
                    else _resolve_for_load(str(catalog), path)
                )
            else:
                catalog = str(_resolve_for_load(str(catalog), path))
        # v0.8.0a83 — remembered offset-from-hub.  Same defensive 2-int
        # parse as position/window_position; any other shape -> None.
        ro_raw = d.get("rel_offset")
        rel_offset: tuple[int, int] | None = None
        if isinstance(ro_raw, (list, tuple)) and len(ro_raw) == 2:
            try:
                rel_offset = (int(ro_raw[0]), int(ro_raw[1]))
            except (TypeError, ValueError):
                rel_offset = None
        items.append(ForestItem(
            path=str(resolved),
            kind=kind,  # type: ignore[arg-type]
            position=pos,
            catalog_path=catalog,
            rel_offset=rel_offset,
        ))

    # v0.8.0a92 — excluded entries are either {root, path} dicts (rooted) or
    # legacy strings.  Rooted entries resolve to the CANONICAL base (NO
    # existence gate — an excluded tool may be uninstalled-yet-excluded; keep
    # it pinned to the same base items rebase to, so the suppression keeps
    # matching).  Legacy strings resolve via the path resolver as before.
    excluded: list[str] = []
    for e in raw.get("excluded", []):
        if isinstance(e, dict):
            ep = str(e.get("path", "")).strip()
            if not ep:
                continue
            er = e.get("root")
            if er:
                excluded.append(str(
                    _rooted_to_abs(str(er), ep) or _resolve_for_load(ep, path)
                ))
            else:
                excluded.append(str(_resolve_for_load(ep, path)))
        elif isinstance(e, str) and e.strip():
            excluded.append(str(_resolve_for_load(e, path)))

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
        fold_single_item_categories=bool(
            auto_raw.get("fold_single_item_categories", False)
        ),
    )

    # v0.6.11 — restore the hub's last on-screen position when the
    # file carries one.  Defensive parse: only accept a 2-tuple of
    # ints; any other shape silently falls back to None so a hand-
    # edited file can't poison the launcher.
    wp_raw = raw.get("window_position")
    window_position: tuple[int, int] | None = None
    if (
        isinstance(wp_raw, (list, tuple))
        and len(wp_raw) == 2
    ):
        try:
            window_position = (int(wp_raw[0]), int(wp_raw[1]))
        except (TypeError, ValueError):
            window_position = None

    forest = ForestDef(
        name=str(raw.get("name", "Forest")),
        items=items,
        excluded=excluded,
        auto_discover=auto,
        icon_data=str(raw.get("icon_data", "") or ""),
        icon_format=str(raw.get("icon_format", "") or ""),
        window_position=window_position,
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
    # Portable mode: the forest workspace lives install-local (and
    # ``default_preferences_path`` follows, since it derives from this dir).
    from scriptree.core.portable import is_portable, portable_data_root
    if is_portable():
        return portable_data_root() / _DEFAULT_FOREST_FILENAME
    if sys.platform == "win32":
        appdata = Path.home() / "AppData" / "Roaming" / brand_name
    elif sys.platform == "darwin":
        appdata = Path.home() / "Library" / "Application Support" / brand_name
    else:
        appdata = Path.home() / ".config" / brand_name
    return appdata / _DEFAULT_FOREST_FILENAME


def shared_autoload_path(branding: dict) -> Path:
    """Where a *machine-wide* default forest file lives — the
    "shared location" the v0.6.9 unsaved-forest prompt offers next
    to the per-user "personal" path.

    This is a LOCAL shared spot (all users of this machine), NOT a
    network/published location.  Same ``default.scriptreeforest``
    filename so the two are interchangeable; only the directory
    differs:

      * Windows — ``%ProgramData%\\<brand>\\``
      * macOS   — ``/Users/Shared/<brand>/``
      * Linux   — ``/usr/local/share/<brand>/``

    No directory is created here (the caller writes the file and
    ``save_forest`` makes parents); if the shared dir isn't writable
    by this user the write will surface its own error.
    """
    brand_name = branding.get("appName", "ScripTree")
    # Portable mode: a portable install is single-scope (personal == shared),
    # so the "shared" save target must ALSO stay install-local — otherwise the
    # unsaved-forest "Save to shared location" button (forest_controller) would
    # write the whole forest to %ProgramData% and a folder-copy/USB move would
    # silently lose it.  Coincides with default_autoload_path in portable mode.
    from scriptree.core.portable import is_portable, portable_data_root
    if is_portable():
        return portable_data_root() / _DEFAULT_FOREST_FILENAME
    if sys.platform == "win32":
        base = Path(
            os.environ.get("ProgramData", r"C:\ProgramData")
        ) / brand_name
    elif sys.platform == "darwin":
        base = Path("/Users/Shared") / brand_name
    else:
        base = Path("/usr/local/share") / brand_name
    return base / _DEFAULT_FOREST_FILENAME


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

    # ------------------------------------------------------------------
    # Visibility modes (v0.8.0a52+)
    # ------------------------------------------------------------------
    #
    # The forest hub can be made reachable through up to three
    # surfaces simultaneously.  At least one MUST be True; the UI
    # enforces this, and ``normalised()`` repairs a hand-edited
    # disk file that violated the invariant.
    #
    # ``show_always_on_top`` is the historical behaviour: the hex
    # floats above the desktop with ``Qt.WindowStaysOnTopHint`` and
    # carries ``Qt.Tool`` (so it does NOT appear on the taskbar /
    # Alt+Tab).  Factory default ON to preserve the pre-a52
    # experience.
    #
    # ``show_on_taskbar`` adds a Windows taskbar entry that brings
    # the forest hub to the front when clicked.  Implemented via a
    # separate dedicated ``ForestTaskbarHost`` window so the taskbar
    # entry survives the forest being hidden (a hidden window
    # doesn't show on the taskbar by itself).
    #
    # ``show_in_system_tray`` adds a system tray icon with the
    # forest glyph.  Left-click → show the forest hub; right-click
    # → small menu with Show / Quit.
    #
    # When ``show_always_on_top`` is OFF the forest hub starts
    # hidden and only appears via taskbar / tray.  It auto-hides
    # when focus moves to a window OUTSIDE the forest hierarchy
    # (hub, rings, cells), or when a tool launch fires.

    show_always_on_top: bool = True
    """Float the forest hub above the desktop.  Factory default
    ON.  When OFF and at least one of the other two flags is ON,
    the hub starts hidden and the taskbar / tray act as the
    user's entry point."""

    show_on_taskbar: bool = False
    """Add a Windows taskbar entry for the forest.  Click brings
    the hub to the front.  Survives the hub being hidden."""

    show_in_system_tray: bool = False
    """Add a system tray icon.  Left-click brings the hub to the
    front; right-click menu offers Show / Quit."""

    # ------------------------------------------------------------------
    # Login autostart (v0.8.0a84+)
    # ------------------------------------------------------------------
    autostart_scope: str = "off"
    """Windows login-autostart scope for the forest, mirroring the
    tree-ring's "Auto-load on startup" capability.  One of:

      * ``"off"``     — not registered to launch at login (factory default).
      * ``"user"``    — a per-user Run-key (``HKCU\\...\\Run``) launches
                        ScripTree in forest mode at login.
      * ``"system"``  — an all-users Run-key (``HKLM\\...\\Run``), set via a
                        UAC-elevated child; requires admin.

    A forest is the single top-level workspace, so unlike rings (which keep a
    *list* of autoload paths) there is exactly one scope (or none).  This is
    the source of truth for the menu/dialog state; the actual Run-key is kept
    in sync by ``ring_io.recompute_autostart`` (the shared chokepoint that also
    folds in ring autostart so the two never clobber the single Run-key value).
    When enabled, ``default_forest_path`` + ``fallback_to_default`` are set so
    the login ``--forest`` process loads exactly the configured forest."""

    def resolved_default_path(self, branding: dict) -> Path:
        """Return the actual file path the launcher should fall
        back to.  Folds the "empty means canonical" rule so callers
        don't have to repeat it."""
        if self.default_forest_path.strip():
            return Path(self.default_forest_path).expanduser()
        return default_autoload_path(branding)

    def normalised(self) -> "ForestPreferences":
        """Return a copy with the visibility invariant enforced.

        At least one of the three visibility flags MUST be True or
        the forest hub becomes unreachable.  Hand-edited disk
        files could put us in that state; ``load_preferences``
        runs every loaded prefs through this so the runtime never
        sees an unreachable forest.

        Repair rule: if all three flags are False, force
        ``show_always_on_top`` back ON (the historical default).
        Other invariant violations are left alone.
        """
        if not (
            self.show_always_on_top
            or self.show_on_taskbar
            or self.show_in_system_tray
        ):
            _log(
                "normalised: all three visibility flags were False; "
                "forcing show_always_on_top=True so the hub is "
                "reachable"
            )
            return ForestPreferences(
                fallback_to_default=self.fallback_to_default,
                default_forest_path=self.default_forest_path,
                show_always_on_top=True,
                show_on_taskbar=self.show_on_taskbar,
                show_in_system_tray=self.show_in_system_tray,
                autostart_scope=self.autostart_scope,
            )
        return self


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
    # Clamp autostart_scope to the known set; legacy files (and any
    # hand-edited garbage) fall back to "off" so a bad value can never
    # leave the forest silently registered for login.
    raw_scope = str(raw.get("autostart_scope", "off") or "off")
    autostart_scope = raw_scope if raw_scope in ("off", "user", "system") else "off"
    prefs = ForestPreferences(
        fallback_to_default=bool(raw.get("fallback_to_default", True)),
        default_forest_path=str(raw.get("default_forest_path", "") or ""),
        show_always_on_top=bool(raw.get("show_always_on_top", True)),
        show_on_taskbar=bool(raw.get("show_on_taskbar", False)),
        show_in_system_tray=bool(raw.get("show_in_system_tray", False)),
        autostart_scope=autostart_scope,
    )
    # Hand-edited / older prefs files may not carry the visibility
    # keys at all (older format) -- defaults restore the historical
    # ``always-on-top only`` behaviour.  ``normalised()`` repairs the
    # degenerate case where all three flags ended up False.
    return prefs.normalised()


def save_preferences(prefs: ForestPreferences, branding: dict) -> None:
    """Persist ``prefs`` to disk.  Creates the parent directory if
    needed.  Idempotent — same content writes byte-identical
    output."""
    p = default_preferences_path(branding)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Repair any all-False visibility set before we write -- the
    # in-memory copy may be in transit (e.g. the UI hasn't yet
    # rejected an unchecked-all-three attempt) but disk must never
    # carry the degenerate state.
    prefs = prefs.normalised()
    blob = {
        "format": _PREFS_FORMAT,
        "version": _PREFS_VERSION,
        "fallback_to_default": bool(prefs.fallback_to_default),
        "default_forest_path": str(prefs.default_forest_path or ""),
        "show_always_on_top": bool(prefs.show_always_on_top),
        "show_on_taskbar": bool(prefs.show_on_taskbar),
        "show_in_system_tray": bool(prefs.show_in_system_tray),
        "autostart_scope": str(prefs.autostart_scope or "off"),
    }
    p.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    _log(f"save_preferences: wrote {p}")


# ---------------------------------------------------------------------------
# Login autostart (v0.8.0a84) — forest analog of the ring autostart API
# ---------------------------------------------------------------------------

def set_forest_autostart(scope: str, branding: dict, *, forest_path: str) -> None:
    """Register the forest to auto-load at Windows login in *scope*.

    *scope* is ``"user"`` or ``"system"``.  Mirrors the tree-ring's
    ``add_autoload_ring`` but for the single top-level forest:

      1. Persist the intent — set ``autostart_scope = scope`` and point the
         launch-default at the saved forest (``default_forest_path =
         resolve(forest_path)``, ``fallback_to_default = True``) so the login
         ``--forest`` process loads exactly *this* forest via the existing
         ``ForestController.start`` path (no new load code needed).
      2. Sync the Run-key — call ``ring_io.recompute_autostart(scope)`` (the
         shared chokepoint), which writes the combined ring+forest command
         into the one Run-key value for that scope.
      3. Single-forest mutual exclusion — if the forest was previously
         registered in the OTHER scope, recompute that scope too so its
         Run-key drops the ``--forest`` flag.

    For ``scope == "system"`` the recompute's HKLM write raises
    ``PermissionError`` unless elevated, so callers route system-scope
    requests through ``ring_io.elevate_for_forest_autostart_system`` (which
    re-enters this function inside the elevated child).

    The caller must ensure *forest_path* is a real saved file (the forest has
    a ``loaded_from``); a transient/unsaved forest cannot be autostarted.
    """
    # Lazy import to avoid an import cycle (ring_io imports forest_io lazily
    # from inside recompute_autostart / _forest_autostart_on).
    from scriptree.shell.ring_io import recompute_autostart

    prefs = load_preferences(branding)
    old_scope = prefs.autostart_scope
    prefs.autostart_scope = scope if scope in ("user", "system") else "off"
    prefs.default_forest_path = str(Path(forest_path).expanduser().resolve())
    prefs.fallback_to_default = True
    save_preferences(prefs, branding)

    recompute_autostart(scope)  # type: ignore[arg-type]
    # If we moved scopes, the old scope's Run-key must drop --forest.
    if old_scope in ("user", "system") and old_scope != scope:
        recompute_autostart(old_scope)  # type: ignore[arg-type]
    _log(f"set_forest_autostart: scope={scope} forest={prefs.default_forest_path}")


def disable_forest_autostart(branding: dict) -> None:
    """Remove the forest from login autostart (set scope to ``"off"``).

    Mirrors the ring's ``_autoload_disable`` clearing both scopes: sets
    ``autostart_scope = "off"`` and recomputes BOTH the user and system
    Run-keys so neither carries ``--forest`` afterwards.  Leaves
    ``default_forest_path`` / ``fallback_to_default`` intact (the in-app
    default-forest behaviour is independent of login autostart).

    Recomputing the SYSTEM scope writes/deletes the HKLM value and so raises
    ``PermissionError`` unless elevated; callers route a system→off transition
    through ``ring_io.elevate_for_forest_autostart_disable_system`` when not
    admin.
    """
    from scriptree.shell.ring_io import recompute_autostart

    prefs = load_preferences(branding)
    old_scope = prefs.autostart_scope
    prefs.autostart_scope = "off"
    save_preferences(prefs, branding)

    # Recompute ONLY the previously-active scope.  Single-forest mutual
    # exclusion guarantees that at most one scope's Run-key ever carried
    # ``--forest``, so that is the only one to clear.  Recomputing the OTHER
    # scope would be pointless AND harmful: an unelevated ``user → off``
    # disable would call ``recompute_autostart("system")`` →
    # ``unregister_autostart("system")``, whose admin check raises
    # ``PermissionError`` BEFORE the empty-key no-op — crashing a routine,
    # admin-free operation.  (System → off while non-admin is routed through
    # the elevated child by the caller, so it reaches here as old_scope
    # ``"system"`` only when already admin.)
    if old_scope in ("user", "system"):
        recompute_autostart(old_scope)  # type: ignore[arg-type]
    _log(
        f"disable_forest_autostart: autostart_scope set off; "
        f"recomputed old scope={old_scope!r}"
    )
