# Reorganize duplicated MSOffice + circular ref: `_groups` discovery feedback loop (a98)

**Tag:** [v3-architecture] [forest-discovery]
**Version:** v0.8.0a98
**Files:** `scriptree/shell/forest_discover.py` (`_walk`, new `_is_skipped_dir` /
`_SKIP_DIR_NAMES`); `scriptree/shell/forest_controller.py` (`_existing_tree_names`).
**Tests:** `tests/test_groups_discovery_a98.py` (3).

## Symptom (what the user hit)

Re-running "Re-organise (re-run category grouping)" from the forest produced a
**duplicate** MSOffice group (`MSOffice.scriptreetree` AND
`MSOffice__auto.scriptreetree`), a **circular reference**, and tools nested under
the wrong category.  Each re-run made it worse.

## Root cause — the synth pass re-ingests its OWN output

Category grouping (`categorize.group_by_category`) writes synthesised trees to
`default_personal_root()/_groups/<Top>.scriptreetree`.  That `_groups/` dir sits
**directly under the per-user "personal-apps" scan root**
(`%LOCALAPPDATA%\ScripTree\Apps`).  So the grouping OUTPUT is inside the grouping
INPUT tree — a feedback loop.  It bites in **two** independent places, and BOTH
had to be fixed:

1. **The discovery walker** (`forest_discover._walk`) descended into `_groups/`
   and emitted `MSOffice.scriptreetree` as a discovered `tree`.  On the next pass
   that synthesised tree is now an input item.

2. **`forest_controller._existing_tree_names`** did `rp.rglob("*.scriptreetree")`
   over every root — including the personal-apps root — so it found
   `_groups/MSOffice.scriptreetree` and added `"MSOffice"` to the
   "existing tree names" set.  `categorize._pick_filename` then saw a name
   collision and renamed the FRESH synthesis to `MSOffice__auto.scriptreetree`
   to avoid clobbering what it thought was a user-authored tree — **spawning the
   duplicate**.  `MSOffice__auto` is then itself discovered next pass → cascade;
   a synthesised tree discovered as a member of another → the circular ref.

The duplicate only appeared on the SECOND+ pass (when `_groups` already held the
prior output), which is why a freshly-cleaned `_groups` looked fine until the
next Re-organise.

## Fix — never let synthesised output feed back into the synth decision

* `_walk` skips any dir named `_groups` (new `_is_skipped_dir`, alongside the
  existing dotfile skip — applied at BOTH the pop-time and push-time checks).
* `_existing_tree_names` skips any `.scriptreetree` whose path has `_groups` in
  its parts (`if "_groups" in tree.parts: continue`) — those are the synth pass's
  own output, NOT user-authored trees it must avoid colliding with.

Synthesised groups still APPEAR in the forest: `discover_now` adds them as
ForestItems directly from `group_by_category`'s outcomes (the synthesised path),
NOT by re-discovering `_groups` on disk.  So skipping `_groups` in discovery
removes the feedback without removing the groups.

## Reusable takeaways

1. **If a generator writes its output under a path it later scans as input, you
   have a feedback loop** — and it can bite at more than one ingestion point.
   We grep-audited every reader of the roots and found TWO (`_walk` and
   `rglob`).  Fixing one would have left the duplicate.
2. **A collision-avoidance rename (`__auto`) is a tell:** if a generator is
   renaming its fresh output to dodge a collision with its OWN prior output, the
   "existing names" set is contaminated with generated artifacts.
3. **The display path and the discovery path are separate** — synthesised groups
   are added from the group-pass *outcomes*, so they survive a discovery skip.
   Reserve `_groups` as a discovery-excluded name and the layers stay clean.
4. Related: [[uncategorised_wrapper_tree_floats_to_top_a94]] (the other
   category-grouping gotcha — a wrapper tree needs its own category) and the
   forest/editor provenance rework (a99) that makes these structures visible.
