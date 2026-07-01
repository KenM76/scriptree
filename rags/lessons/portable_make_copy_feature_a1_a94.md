# Feature A1 — "Make a portable copy (incl. local tools)" (a94)

**Tag:** [v3-architecture]
**Version:** v0.8.0a94
**Files:** `scriptree/shell/portable_export.py` (NEW); `scriptree/shell/forest_controller.py`
(`_on_make_portable_copy_with_tools`, `_private_tool_warning` refactor, the
`a_make_copy` Forest action).
**Tests:** `tests/test_portable_export_a94.py` (8).
**Builds on:** [[portable_consolidate_feature_a_a93.md]] (A2 + the plan/execute/rebase
primitive), [[named_root_path_portability_a92.md]] (the `(root-id, rel)` save).

## What it does

Build a NEW self-contained portable ScripTree at a user-chosen EMPTY folder,
bundling the app + install tools + every outside (`apps`/`personal`) tool, WITHOUT
touching the running install or the live forest (the forest is rebased on a deep
copy).  Composes:

    copy_install_tree(install_root, dest)                 # app + install tools
    execute_consolidation(plan, install_apps_root=dest/ScripTreeApps)  # outside tools
    rebase_forest_items(work, result)                     # apps/personal -> dest
    rebase_install_items_to_external(work, cur_apps, dest_apps)        # install -> dest mirror
    prune_items_outside_external(work, dest_apps)         # drop anything that didn't land in dest
    save_forest_for_external_install(work, dest_autoload, dest)        # tag root:install for DEST
    (dest / "portable").write_text(...)                   # portable sentinel

## Why A1 can't reuse `make_portable.py`

`make_portable.py` (repo root) does the dev app-copy, but it lists itself in its
own exclude set and is therefore **absent from a deployed runtime tree**
(`R:\ScripTree` has no `make_portable.py`).  A1 runs from the runtime, so it CANNOT
import it.  `portable_export.py` re-implements the small runtime-needed slice
(copytree + exclude set) inside the package.

## The hard part — rooting a forest for a DIFFERENT install location

A2 (in-place) was easy: the dest install root IS the current install, so rebased
items map to `root:install` automatically.  A1's dest install root ≠ the current
machine's, so the current process's `save_forest` (which derives the `install`
base from `forest_io._project_root()`) would tag dest paths as ABSOLUTE, not
`root:install`.  Fix: `save_forest_for_external_install` temporarily points
`forest_io._project_root` at `dest` for the single synchronous write (restored in
`finally`), so `known_roots()`'s install base becomes `<dest>/ScripTreeApps` and
every traveling item serialises `root:install` — resolving correctly when the copy
runs FROM `dest`.  `external_autoload_path` mirrors the portable autoload location
(`<dest>/_portable_data/default.scriptreeforest` — NO brand subdir under portable).

## Four real defects a 3-lens adversarial review caught (all fixed)

1. **(HIGH) `scriptree.ini` copied verbatim into the shareable copy.**  The exclude
   set skipped `.git`/`tests`/`_portable_data`/etc. but NOT `scriptree.ini` — which
   holds the author's recent-file MRU, per-tool dock layouts, absolute machine
   paths, and an `install.personal_root` override (and SolidWorks tool NAMES).
   It's on the project never-commit list; shipping it leaks private state AND can
   point the copy off-tree.  **Fix:** add `scriptree.ini` + `scriptree.ini.bak`
   to `EXCLUDE_FILES` so the copy starts with clean per-machine state.

2. **(MED) Steps 2–4 unguarded + a cursor double-restore.**  Step 1 (copy app) and
   step 4 (save) each had a nested `try/except` that ALSO called
   `restoreOverrideCursor()` — then the outer `finally` restored it AGAIN (one too
   many pops off Qt's cursor stack).  And steps 2–3 (consolidate/deepcopy/rebase)
   had NO handler, so a raise left a half-built dest (app present, no
   sentinel/forest → boots NON-portable) with an uncaught Qt-slot exception.
   **Fix:** one `setOverrideCursor` + a single restore in `finally`; wrap steps
   2–4 as one guarded unit that tells the user the dest is INCOMPLETE and safe to
   delete.

3. **(MED) A copy-FAILED personal item serialised `root:personal` and dangled.**
   `save_forest_for_external_install` patches `_project_root` (→ install/apps
   bases) but NOT `default_personal_root` (the `personal` base).  A personal tool
   whose copytree failed (swallowed `OSError` → no rebasing entry → left at its
   host path) then tagged `root:personal`, which on the DEST machine resolves to
   the dest's empty app-data → dangling cell.  **Fix:** after rebasing,
   `prune_items_outside_external` drops every item NOT under `<dest>/ScripTreeApps`
   (copy-failed OR under no known root) so the exported forest references ONLY
   tools that physically travel — no off-tree root can be serialised.  (Also
   subsumes the "outside" tools the up-front warning already said wouldn't travel.)

4. **(MED) Install-resident private SolidWorks tools travelled un-warned.**
   `_private_tool_warning` only scans the consolidation `plan` (the OUTSIDE tools);
   the install's OWN `ScripTreeApps` is copied wholesale by `copy_install_tree` and
   was never scanned.  **Fix:** lift the private-detection helpers
   (`is_private_name`/`folder_has_private_tools`/`file_is_private`) to module level
   in `portable_export`, and in the A1 handler also
   `folder_has_private_tools(cur_apps)` → add an install-resident caution to the
   confirm dialog.

(Two LOW symlink/recursion-hardening claims were reviewed and REJECTED as
defensive-only, not real defects.)

## Reusable takeaways

1. **Serialising paths for a DIFFERENT root than the running machine's:** point the
   root resolver at the target for the write, restore in `finally`.  The named-root
   design makes "where does install resolve" a single swappable function.
2. **A shareable artifact must be scrubbed of per-machine state.**  `scriptree.ini`
   (recent files, layouts, absolute paths, tool names) is private — exclude it from
   any copy you invite the user to hand out.
3. **One cursor push = one pop.**  Don't `restoreOverrideCursor()` in both a nested
   `except` AND the outer `finally`; pick one (the `finally`).
4. **Guard everything written AFTER the first irreversible write as one unit** —
   once the app tree is on disk, any later failure must tell the user the artifact
   is incomplete, not throw out of the slot.
5. **For a portable EXPORT, prune don't dangle:** drop items that didn't physically
   travel rather than letting them serialise a root that resolves to nothing on the
   destination.

## Still deferred

* **Bundled-Python USB copy** — A1 copies the app as-installed; a clean-machine copy
  still needs `make_portable.py --bundle-python` (noted in the A1 dialog).
* **Feature B** — network roots + per-root preference + local-vs-network dedup
  (the larger multi-stage piece; NOT interleaved with A).
* A1 copies the whole install on the GUI thread with a wait cursor (no progress /
  cancel) — acceptable for an explicit action; threaded progress is a follow-up.
