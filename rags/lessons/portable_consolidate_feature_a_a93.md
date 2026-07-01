# Feature A2 — "Convert this install to portable (copy local tools here)" (a93)

**Tag:** [v3-architecture]
**Version:** v0.8.0a93
**Files:**
`scriptree/shell/portable_consolidate.py` (NEW — `plan_consolidation`,
`execute_consolidation`, `rebase_forest_items`);
`scriptree/shell/forest_controller.py`
(`_on_convert_install_to_portable_with_tools`, `_private_tool_warning`, the
Forest-submenu `a_convert` action).
**Tests:** `tests/test_portable_consolidate_a93.py` (13).
**Builds on:** [[named_root_path_portability_a92]] (the `(root-id, rel)`
serialization that makes re-tagging `root → install` a trivial id swap),
[[portable_mode_and_ignore_copy_a89]] (portable sentinel + `migrate_for_toggle`).

## What it does

For every forest tool whose catalog lives OUTSIDE the install tree — under the
sibling `apps` deploy root or the per-user `personal` root — copy its folder
into `<install>/ScripTreeApps` at the same root-relative sub-path, re-point the
forest item at the install copy, then flip Portable mode on via the existing
`portable_migrate.migrate_for_toggle(True, branding)`. Because
`forest_io.known_roots()` lists `install` FIRST and `save_forest` tags each path
`(root-id, rel)`, simply pointing `item.path` at the install copy makes the next
save serialise it `root: "install"` — which travels with a folder-copy. No new
schema field; the re-root is an implicit consequence of the install-first
ordering (pinned by `test_rebase_then_save_roundtrip_tags_install`).

## The primitive (Qt-free, headless-testable)

1. `plan_consolidation(forest, install_apps_root=None)` — read-only. Classify
   each item: `skip` (already under install), `copy`/`collision` (apps/personal
   → a planned install dest), `outside` (under no known root — left alone).
2. `execute_consolidation(plan, *, on_collision="rename")` — pure COPY
   (`shutil.copytree`/`copy2`). NEVER moves or deletes a source. Returns a
   `rebasing` map (`_norm(old path)` → new catalog path) + counts.
3. `rebase_forest_items(forest, result)` — point each successfully-copied item's
   `path`/`catalog_path` at the install dest (preserving `kind`/`position`/
   `rel_offset`), drop the now-stale source from `forest.excluded`.

## Key controller insight — re-key `_spawned`, do NOT close/respawn the cells

The naive "despawn → rebase → respawn" sequence is a TRAP: `_despawn_item` calls
`win.close()`, which fires `_on_cell_closed`, which **prunes the very ForestItem
you're re-rooting** (and pushes it onto `excluded`). Instead the convert handler
leaves the live cells open and just **re-keys** `self._spawned`
(`pop(old _norm(path))` → `set _norm(new path)` on the SAME window). This:
* dodges the `_on_cell_closed` prune,
* avoids a visual flicker,
* keeps `save()`'s position capture working — `_sync_positions_into_items`
  looks up `_spawned` by the item's CURRENT path, so the key MUST already be the
  new install path before `save()` runs.

Load-bearing order (non-destructive): `execute_consolidation` (copy) → re-key
`_spawned` → `rebase_forest_items` → `save()` → `migrate_for_toggle(True)` LAST.
Migrate is last so a failure anywhere above leaves a fully-working NON-portable
install with the tools merely *also* present under the install tree.

## Three real defects a 3-lens adversarial review caught (all fixed)

1. **(HIGH) Private-tool warning checked the folder NAME, not its contents.**
   `_private_tool_warning` matched `solidworks|sw_bridge|solidworkstools|\.csx`
   against `plan_item.rel` — which is the source **folder's** path-relative-to-
   root. A neutrally-named folder (`MyMacros/`) holding `sw_bridge.exe` + `*.csx`
   never tripped it, and the `\.csx` token was **dead** (rel is a directory path;
   the catalog filename is stripped by `Path(item.path).parent`, so `.csx` could
   only match a directory literally named `*.csx`). This defeated the global
   "SolidWorks tools are PRIVATE — never publish" guard the dialog promises.
   **Fix:** walk the actual source CONTENTS (`os.walk`) and match real file/dir
   names — any `*.csx`, `sw_bridge`, `SolidWorksTools`, `solidworks.interop*.dll`;
   for a loose single-file tool, also scan the `.scriptree` text for those
   tokens. (`tests/...::test_private_tool_warning_scans_folder_contents`.)

2. **(HIGH) A loose tool sitting DIRECTLY in a root base copied the WHOLE root.**
   For an uncategorised `apps/RandomTool.scriptree` (a documented layout — see
   `docs/LLM/category_authoring.md`), `src_folder = item.path.parent` IS the root
   base, so `forest_io._path_to_rooted` returns rel `"."` (NOT `""` — verify
   `rel in ("", ".")`). Then `dest_folder = dest_root / "."` == `dest_root`, which
   always exists → `collision` → default `rename` built `<install>/ScripTreeApps-2`
   and `copytree`'d **every sibling tool** into it, rebasing the item to a bogus
   nested path. **Fix:** detect `rel in ("", ".")` in `plan_consolidation` and set
   `single_file=True`; `execute_consolidation` then copies ONLY the catalog FILE
   into a per-tool folder `<install>/ScripTreeApps/<stem>/`. Crucially, the
   per-source dedup key changed from `src_folder` to the **copy source** (the FILE
   for single-file, the folder otherwise) — else two loose tools sharing the root
   base would collapse onto one dest. (`test_loose_tool_in_root_base_copies_only_the_file`,
   `test_two_loose_tools_in_root_get_distinct_folders`.)

3. **(MED) `catalog_path` outside the copied folder dangled cross-machine.**
   `rebase_forest_items` rebased `path` unconditionally but only rebased
   `catalog_path` when it resolved UNDER the source folder; otherwise it left it
   pinned to the (un-copied) source. Same-machine it still resolved (source never
   deleted), but a cross-machine folder-copy — the whole point — dangled.
   **Fix:** when the catalog is outside, re-point it at the new install catalog
   (== the rebased `path`, self-consistent) and record the original in
   `result.catalog_relinked` (surfaced in the success dialog).
   (`test_catalog_outside_source_folder_is_relinked`.)

## Hardening already in the primitive (pre-review)

* **Per-source dedup + execute-time collision recheck.** Two forest items in ONE
  folder (a `.scriptreetree` suite + a co-located `.scriptree` leaf) copy the
  folder ONCE; two different-root folders clashing on the same install name copy
  the first and `rename` the second to `<name>-2` (collision rechecked at EXECUTE
  time, not just plan time — a clash can be *created* mid-run).
* **Rebase only what copied.** A partial/failed copy leaves its item pointing at
  the still-present source, so a cell is never stranded.

## Deliberately deferred (separate increments)

* **A1** "make a NEW portable copy elsewhere (incl. local tools)" — needs to
  import the repo-root `make_portable` script at runtime (fragile path
  resolution); the core (`plan/execute/rebase` with `install_apps_root=<dest>`
  + a deep-copied forest) already supports it.
* **Feature B** (network roots + per-root preference + local-vs-network dedup) —
  MUST NOT be interleaved with A per the design critique. `known_roots()` extends
  to network/browsed roots; dual-source = different root-ids for the same `rel` +
  a per-root preference layered over `ignore_copy`.

## Reusable takeaways

1. **Re-key a live-object registry; don't close+rebuild it** when a close fires a
   prune/cleanup slot. Closing to "refresh" a window is how you delete the thing
   you're editing.
2. **A "match the name" guard is not a "match the thing" guard.** The private-tool
   check matched a folder NAME and silently passed a folder full of private files.
   When the rule is about contents, inspect contents.
3. **`Path('x').relative_to(Path('x'))` is `"."`, not `""`.** A "folder IS the
   base" sentinel must test `rel in ("", ".")`, and `dest_root / "."` collapses to
   `dest_root` — guard so a copy dest can never resolve to the root itself.
4. **Dedup by the COPY SOURCE, not a proxy.** Keying folder-dedup on `src_folder`
   broke once `src_folder` (the root base) was shared by many loose tools; key on
   the actual thing being copied.
5. **Order destructive/irreversible steps LAST.** `migrate_for_toggle` (the mode
   flip) runs after copy+rebase+save, so every earlier failure is recoverable.
