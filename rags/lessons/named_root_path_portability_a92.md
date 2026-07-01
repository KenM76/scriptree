# Named-root path portability in the forest file (a92, design option #2)

**Tag:** [v3-architecture]
**Version:** v0.8.0a92
**Files:** `scriptree/shell/forest_io.py` (`known_roots`, `_path_to_rooted`,
`_rooted_to_abs`, `save_forest`, `load_forest`); `docs/LLM/scriptreeforest_format.md`.
**Tests:** `tests/test_named_roots_a92.py` (11).

## The problem it solves

A drop-installed app's forest reference was stored by **absolute path** whenever
the app fell outside the project-root anchor (`_to_relative_if_possible` falls
back to absolute). Absolute = machine-specific → breaks on a folder move,
portable↔normal toggle, and cross-machine copy. (It already used a *relative*
path when the app lived under the install tree; the absolute fallback was the
gap.)

## The fix — store `(root-id, path-relative-to-that-root)`

A small registry, `known_roots()`, returns ordered `(id, base)` pairs for the
well-known **portable-aware** roots:
* `install` = `<project root>/ScripTreeApps` (travels with a folder-copy — the
  cross-machine-portable home),
* `apps` = `<project root>/../ScripTreeApps` (the sibling deploy tree),
* `personal` = `default_personal_root()` (per-user appdata, **or** install-local
  under portable mode).

`save_forest` tags each item/catalog path with its root + a relative path
(`{"root": "apps", "path": "SolidWorks/…/foo.scriptree"}`); `load_forest`
resolves `known_roots()[root] / rel`. Because the bases are recomputed each load
(and `personal` is portable-aware), the **same** stored `(root, rel)` resolves
correctly in either mode and on any machine with the same logical roots. It is
**serialization-only** — `ForestItem.path` stays absolute in memory, so nothing
downstream changed.

**Back-compat:** a legacy forest (bare `"path"`, no `"root"`) still loads via
`_resolve_for_load`; on next save each item is re-tagged. Reverse: a *pre-a92*
build reading a NEW forest mis-resolves the prefix-stripped path → only bites on
a downgrade/rollback (documented; single up-to-date deployments never hit it).

## Five gaps a 3-agent adversarial review caught (all real, all fixed)

1. **`excluded[]` was left absolute while items were rooted** → after a base
   move the items rebase but the exclusions don't → `_norm` mismatch in
   `diff_against` → an **ignored copy reappears**. Fix: root the excluded list
   the same way (`{root, path}` dicts, legacy strings still accepted). Excluded
   resolves to the CANONICAL base with **no existence gate** (an excluded tool
   may be uninstalled-yet-excluded; it must stay pinned to the base items
   rebase to, so the suppression keeps matching).
2. **The existence fallback was dead.** `resolved = _rooted_to_abs(...) or
   _resolve_for_load(...)` never reached the `or` because `_rooted_to_abs`
   returns `(base/rel).resolve()` unconditionally (no existence check). So a
   zipped/emailed workspace where the tool sits NEXT TO the forest file (not at
   the canonical base) stranded the cell. Fix: `cand = _rooted_to_abs(...);
   resolved = cand if (cand and cand.exists()) else _resolve_for_load(rel,
   forest_file)` — the legacy resolver's forest-dir step then recovers the
   co-located file. (Items existence-gate; excluded does NOT — see #1.)
3. **`known_roots` de-dup dropped the `personal` id** under portable mode (where
   `personal` base == `install` base). Reverse lookup `_rooted_to_abs("personal",
   …)` then returned `None` and stranded those items. Fix: keep EVERY id even
   when bases coincide — forward tagging iterates in order (first match wins,
   deterministic), reverse lookup must still find every id.
4. **Stale doc:** `portable_migrate.py` still claimed "the forest stores tool
   paths as ABSOLUTE" — false after a92; updated to describe named-root /
   portable-aware resolution.
5. **Forward-compat undocumented:** added the downgrade-strands-workspace note
   to `scriptreeforest_format.md` (chose NOT to bump the forest `version` — it
   would spew a spurious mismatch warning on every legacy-file load, the common
   transition case, for a weak downgrade signal).

## Reusable takeaways

1. **When you make HALF a related set portable, the other half desyncs.**
   Rooting `items[]` but not `excluded[]` silently reintroduced a dual-source
   bug. Audit sibling collections (items ↔ excluded ↔ catalog) for the same
   treatment.
2. **An `X() or fallback()` where `X` returns a non-None sentinel is a dead
   fallback.** Gate on the real condition (`exists()`), not truthiness.
3. **De-dup a registry by VALUE only if reverse-lookup-by-KEY isn't needed.**
   Here both directions are needed, so keep all keys.
4. **This is the foundation for the rest of the portability roadmap** —
   "make a portable copy including local tools" is just *copy non-`install`
   tools into the install tree + re-tag `root` → `install`*, which is now a
   trivial id swap; and local-vs-network dual-source is *different root-ids for
   the same `rel`* + a per-root preference layered over `ignore_copy`.
   Extending to network/browsed roots = adding entries to `known_roots()`.
