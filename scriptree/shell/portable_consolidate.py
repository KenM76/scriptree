"""Consolidate non-install forest tools INTO the install tree (v0.8.0a93).

## What this is for

Two user-facing operations build on this primitive:

* **"Make a portable copy including local tools"** — produce a NEW
  self-contained folder (a ``make_portable`` copy) and pull every tool that
  lives *outside* the install tree into it, so the whole folder travels.
* **"Convert this install to portable"** — do the same *in place* under the
  current install, then flip portable mode on.

Both reduce to ONE primitive, implemented here: for each forest item whose
catalog is NOT already under the ``install`` named root (i.e. it sits under the
``apps`` sibling tree or the per-user ``personal`` root), **copy its tool
folder into ``<install>/ScripTreeApps`` at the same root-relative sub-path**,
then re-tag the forest item so it points at the install copy.  Because
``forest_io.save_forest`` serialises each path as ``(root-id, rel)`` and
``known_roots()`` lists ``install`` FIRST, simply pointing ``item.path`` at the
install copy makes the next save tag it ``root: "install"`` — no schema field,
no string surgery.

## The three functions (pure-ish, Qt-free, headless-testable)

1. :func:`plan_consolidation` — read-only.  Classify every item: ``skip`` (already
   under install), ``copy`` (apps/personal → a planned install dest), ``collision``
   (dest already exists), ``outside`` (under no known root — left alone, won't
   travel).  No writes.
2. :func:`execute_consolidation` — do the copies (``shutil.copytree``); resolve a
   dest collision via the local :data:`CollisionPolicy`
   (``reuse``=re-root to the existing install copy, ``update``=merge,
   ``overwrite``=replace, ``rename``=``<name>-N``).  Copies each unique source
   FOLDER once (multiple items in one folder share the copy).  Returns a
   rebasing map + per-item success.  **Never touches the forest and NEVER
   deletes a source folder** — it is a pure copy.
3. :func:`rebase_forest_items` — point each *successfully-copied* item's
   ``path``/``catalog_path`` at its install dest (preserving ``kind`` /
   ``position`` / ``rel_offset``), and drop the now-stale source from
   ``forest.excluded``.  Returns the count rebased.

## Safety invariants (see the a93 lesson + the design critique)

* **Copy only, never move/delete a source.**  The only ``rmtree`` is inside
  ``ConflictMode.OVERWRITE`` on the DEST under the install, and only when the
  caller explicitly asks for it.
* **Non-destructive default.**  ``on_collision`` defaults to ``RENAME`` (then
  ``SKIP``) — never silently overwrite an install tool of the same name.
* **Rebase only what copied.**  ``rebase_forest_items`` skips any item whose
  copy didn't yield a real dest, leaving it pointing at its still-present
  source — so a partial/failed run can't strand a cell.
* **Re-rooting is implicit** via ``known_roots`` install-first ordering; pinned
  by ``test_rebase_then_save_roundtrip``.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from scriptree.core.app_install import pick_rename_target
from scriptree.shell import forest_io
from scriptree.shell.forest_discover import _norm

PlanStatus = Literal["skip", "copy", "collision", "outside"]

#: Collision policy for ``execute_consolidation`` when the install dest exists.
#: ``reuse`` re-roots the item to the EXISTING install copy without copying
#: (non-destructive); ``rename`` copies as ``<name>-N``; ``update`` merges;
#: ``overwrite`` replaces (destructive — explicit opt-in only).  ``ConflictMode``
#: from ``app_install`` has no "skip/reuse", so this is a local policy.
CollisionPolicy = Literal["rename", "reuse", "update", "overwrite"]


@dataclass
class ConsolidationPlanItem:
    """One forest item's consolidation plan (read-only)."""

    item: object                 # the ForestItem (kept by reference)
    status: PlanStatus
    src_folder: Path | None      # the tool's source folder (item.path.parent)
    dest_folder: Path | None     # planned install dest folder (None for skip/outside)
    root_id: str = ""            # which root the source is under ("apps"/"personal"/…)
    rel: str = ""                # source folder's path relative to that root
    single_file: bool = False    # the source folder IS a root base (a loose tool
                                 # sitting directly in apps/ or personal/) — copy
                                 # ONLY the catalog FILE into a per-tool dest, NEVER
                                 # copytree the whole root.  See the rel-in-('','.')
                                 # branch in plan_consolidation.


@dataclass
class ConsolidationResult:
    """Outcome of :func:`execute_consolidation`."""

    #: ``_norm(old item.path)`` → new absolute catalog-file path (the rebase map).
    rebasing: dict[str, str] = field(default_factory=dict)
    copied: int = 0
    skipped: int = 0          # already under install
    collisions: int = 0       # resolved via on_collision
    outside: int = 0          # under no known root — left alone
    errors: list[str] = field(default_factory=list)
    #: items whose ``catalog_path`` pointed OUTSIDE the copied source folder, so
    #: it could not be rebased relatively and was re-pointed at the new install
    #: catalog instead (avoids a dangling cross-machine reference).  Each entry
    #: is the ORIGINAL ``catalog_path`` for transparency.  Set by
    #: :func:`rebase_forest_items`.
    catalog_relinked: list[str] = field(default_factory=list)


def _install_apps_root() -> Path:
    """The ``install`` named root's base = ``<install>/ScripTreeApps``."""
    for rid, base in forest_io.known_roots():
        if rid == "install":
            return base
    # Defensive: known_roots always yields install first; fall back to the
    # project-root sibling if a future build reorders it.
    return forest_io._project_root() / "ScripTreeApps"


def plan_consolidation(
    forest, install_apps_root: Path | None = None,
) -> list[ConsolidationPlanItem]:
    """Classify every forest item for consolidation.  Read-only — no writes.

    An item is ``copy``-planned when its tool folder is under the ``apps`` or
    ``personal`` root; ``skip`` when already under ``install``; ``collision``
    when the planned install dest already exists; ``outside`` when under no
    known root (it stays put and won't travel).
    """
    dest_root = (install_apps_root or _install_apps_root()).resolve()
    plan: list[ConsolidationPlanItem] = []
    for it in forest.items:
        src_folder = Path(it.path).parent
        rooted = forest_io._path_to_rooted(src_folder)
        if rooted is None:
            plan.append(ConsolidationPlanItem(it, "outside", src_folder, None))
            continue
        root_id, rel = rooted
        if root_id == "install":
            plan.append(
                ConsolidationPlanItem(it, "skip", src_folder, None, root_id, rel)
            )
            continue
        if rel in ("", "."):
            # The tool's folder IS the root base — i.e. a LOOSE tool living
            # directly in apps/ or personal/ (a supported layout: an
            # uncategorised ``RandomTool.scriptree`` at the root).  We must NOT
            # copytree the whole root (that would drag every sibling tool into
            # the install + rebase this item to a bogus nested path).  Instead
            # give the loose tool its OWN per-tool folder under the install,
            # named after the catalog stem, and copy ONLY its file.
            stem = Path(it.path).stem or "tool"
            dest_folder = dest_root / stem
            status_lf: PlanStatus = "collision" if dest_folder.exists() else "copy"
            plan.append(ConsolidationPlanItem(
                it, status_lf, src_folder, dest_folder, root_id, rel,
                single_file=True,
            ))
            continue
        dest_folder = dest_root / rel
        status: PlanStatus = "collision" if dest_folder.exists() else "copy"
        plan.append(
            ConsolidationPlanItem(it, status, src_folder, dest_folder, root_id, rel)
        )
    return plan


def execute_consolidation(
    plan: list[ConsolidationPlanItem],
    install_apps_root: Path | None = None,
    *,
    on_collision: CollisionPolicy = "rename",
    dry_run: bool = False,
) -> ConsolidationResult:
    """Copy each planned tool folder into the install tree.

    Pure COPY — never moves or deletes a source.  Collisions on the install
    DEST are resolved by ``on_collision``.  Returns a :class:`ConsolidationResult`
    whose ``rebasing`` maps ``_norm(old item.path)`` → the new install
    catalog-file path for every item that copied successfully.  Does NOT mutate
    the forest (that's :func:`rebase_forest_items`).
    """
    res = ConsolidationResult()
    dest_root = (install_apps_root or _install_apps_root()).resolve()
    # One source thing may back several forest items (a .scriptreetree suite
    # plus co-located .scriptree leaves share ONE folder).  Copy each unique
    # SOURCE exactly ONCE and remember the dest it landed at, so every item that
    # shares it rebases into the SAME copy (and the second item never trips a
    # ``FileExistsError`` from a duplicate copy).  The dedup key is the COPY
    # SOURCE (the folder for a normal tool, the FILE for a loose-in-root tool),
    # NOT ``src_folder`` — for loose tools ``src_folder`` is the shared root base,
    # which would otherwise collapse every loose tool onto one dest.
    done_sources: dict[str, Path] = {}

    def _copy_into(src: Path, dest: Path, *, single_file: bool) -> None:
        """Materialise ``src`` at ``dest`` (a folder copy, or a single-file copy
        into the per-tool ``dest`` folder).  No-op under ``dry_run``."""
        if dry_run:
            return
        if single_file:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / src.name)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dest)

    for p in plan:
        if p.status == "skip":
            res.skipped += 1
            continue
        if p.status == "outside":
            res.outside += 1
            continue
        # status is "copy" or "collision" — both reduce to "materialise the
        # source at the install dest, resolving any collision that exists AT
        # EXECUTE TIME".
        # The COPY SOURCE: the catalog FILE for a loose-in-root tool, else the
        # whole tool folder.
        src = Path(p.item.path) if p.single_file else p.src_folder  # type: ignore[arg-type]
        src_key = _norm(str(src))
        dest = p.dest_folder or (dest_root / p.rel)
        try:
            if src_key in done_sources:
                # Already copied this source this run — reuse its dest, no copy.
                dest = done_sources[src_key]
            else:
                # Recheck existence NOW (a collision can also be created earlier
                # in this same run by a different-root source of the same name),
                # not just at plan time.
                if dest.exists():
                    res.collisions += 1
                    if on_collision == "reuse":
                        pass  # re-root to the EXISTING install copy; no copy.
                    elif on_collision == "overwrite":
                        if not dry_run:
                            shutil.rmtree(dest)
                        _copy_into(src, dest, single_file=p.single_file)
                    elif on_collision == "update":
                        if p.single_file:
                            _copy_into(src, dest, single_file=True)
                        elif not dry_run:
                            shutil.copytree(src, dest, dirs_exist_ok=True)
                    else:  # "rename" (default)
                        dest = pick_rename_target(dest.parent, dest.name)
                        _copy_into(src, dest, single_file=p.single_file)
                else:
                    _copy_into(src, dest, single_file=p.single_file)
                    res.copied += 1
                done_sources[src_key] = dest
        except OSError as e:  # noqa: BLE001
            res.errors.append(f"{src} -> {dest}: {e}")
            continue
        # Map old catalog-file path -> new catalog-file path under the dest.
        new_catalog = dest / Path(p.item.path).name  # type: ignore[attr-defined]
        res.rebasing[_norm(p.item.path)] = str(new_catalog)  # type: ignore[attr-defined]
    return res


def rebase_forest_items(forest, result: ConsolidationResult) -> int:
    """Point each successfully-copied item at its install dest, in place.

    Matches by ``_norm(item.path)``.  Preserves ``kind`` / ``position`` /
    ``rel_offset``; rebases ``catalog_path`` when it lived under the same source
    folder; drops the now-stale source path from ``forest.excluded``.  Returns
    the number of items rebased.  Items not in ``result.rebasing`` (skip /
    outside / failed copy) are left untouched, so a partial run never strands a
    cell.
    """
    rebased = 0
    dropped: set[str] = set()
    for it in forest.items:
        key = _norm(it.path)
        new_path = result.rebasing.get(key)
        if new_path is None:
            continue
        old_folder = Path(it.path).parent
        new_folder = Path(new_path).parent
        # Rebase catalog_path when it sat under the same source folder.
        if it.catalog_path:
            try:
                cat_rel = Path(it.catalog_path).resolve().relative_to(
                    old_folder.resolve()
                )
                it.catalog_path = str(new_folder / cat_rel)
            except (ValueError, OSError):
                # Catalog sits OUTSIDE the copied folder (rare — needs a forest
                # whose catalog_path diverges from path.parent).  That file was
                # NOT copied into the install tree, so leaving catalog_path at
                # the source would DANGLE on a cross-machine folder-copy (the
                # whole point of consolidation).  Re-point it at the new install
                # catalog (== the rebased ``path``) so the reference is
                # self-consistent and travels; record the original for
                # transparency.
                result.catalog_relinked.append(str(it.catalog_path))
                it.catalog_path = new_path
        dropped.add(key)
        it.path = new_path
        rebased += 1
    if dropped:
        forest.excluded = [
            e for e in forest.excluded if _norm(e) not in dropped
        ]
    return rebased
