# The `_groups` circular reference that "kept coming back": un-prunable, marker-stripped residue (a104)

**Tag:** [v3-architecture] [forest] [data-mutation] [self-heal]
**Version:** v0.8.0a104
**Files:** `scriptree/shell/merged_tree.py` (`push_back_to_origins` whole-file
`_groups` refusal), `scriptree/core/categorize.py` (`prune_orphan_synthesised`
marker-independent self-heal + `_has_subtree_leaf`).
**Tests:** `tests/test_groups_circular_selfheal_a104.py` (6).
**Investigation:** a general-purpose agent traced + EMPIRICALLY reproduced it
against the live tree (the earlier a98/a100 fixes are all still present and
working — the recurrence was a SEPARATE defect).

## Symptom

On forest startup the user kept seeing a circular reference: `_groups/Demo.scriptreetree`
contained a leaf `./MSOffice.scriptreetree` and `_groups/MSOffice.scriptreetree`
contained `./Demo.scriptreetree` — two sibling auto-groups referencing each
other. Reported as "Demo gets added to MSOffice and MSOffice gets added to Demo,
still." a98 (discovery skips `_groups`) and a100 (push-back per-child strip +
forest-hub-uses-forest-view) had each "fixed" it before, yet it returned.

## Root cause — it was RESIDUE that could never self-heal, not a live re-write

Decisive forensics (the corrupted files told us who wrote them):
- The cross-ref leaves used the **relative `./Sibling.scriptreetree`** form and
  the files had **no `synthesised_by` marker** and **no leaf `name`** — that is
  the signature of `save_tree` via **`push_back_to_origins`** (which relativises
  via `_restore_relative_leaf_paths` and rebuilds a bare `TreeDef(name, nodes)`),
  NOT of `categorize.group_by_category` (which always writes `synthesised_by` +
  leaf `name` + ABSOLUTE paths). So a **pre-a100 push-back** (no strip guard)
  was the original writer.
- **Why it never went away:** `prune_orphan_synthesised` only deleted files whose
  JSON still carried the `synthesised_by` marker. But push-back **strips** that
  marker (it builds a fresh `TreeDef` that omits it). So once a group file was
  push-back-rewritten, it became **permanently un-prunable** — it sat on disk and
  was re-shown every startup. It only got cleaned if a fresh synth pass happened
  to overwrite it (category still ≥2 tools), and could be re-corrupted before
  that. **The bug was not an active re-write on current code (all guards hold —
  it could not be reproduced without disabling a guard); it was un-healable
  residue.**

## The fix (two prongs + a one-time cleanup)

1. **`push_back_to_origins` REFUSES any `_groups/` source entirely** (whole-file,
   marker-independent) — `if "_groups" in src.resolve().parts: result.skipped += …;
   continue`, BEFORE the per-source branch. A synth group is owned by
   `categorize` and regenerated from tool categories; a push-back must NEVER
   write one. This is strictly stronger than the a100 per-child strip (which only
   scrubbed the cross-ref CONTENT) and matches the editor's posture
   (`_is_synthesised_group`, write-back Guard 2 `"_groups" in p.resolve().parts`).
2. **`prune_orphan_synthesised` SELF-HEALS** — delete a `_groups` file (not in
   `keep_paths`) that references a **SIBLING group in the same `_groups` dir**
   (`_refs_sibling_group_tree`), **even without the marker**. Reclaiming it lets
   the next pass regenerate the group cleanly. A file in `keep_paths` is never
   touched.

   **Review caught my first cut here (MED data-loss).** My initial helper
   (`_has_subtree_leaf`) flagged ANY `.scriptreetree` leaf as "illegal" on the
   false premise that a synth group lists only `.scriptree` tool leaves. That is
   wrong twice over: (i) a sub-tree leaf is a documented, legitimate node type, so
   a hand-authored `_groups` hub referencing an external sub-tree would be
   **silently deleted**; (ii) `group_by_category` ITSELF emits `.scriptreetree`
   leaves when it groups *categorised sub-trees*, so a legit synth group can
   contain them. The narrowed `_refs_sibling_group_tree` resolves the leaf path
   (relative to the file's dir, or absolute) and flags it ONLY when the target's
   parent **is the same `_groups` dir** (a direct sibling) — the true residue
   signature. External/nested sub-tree refs are preserved. (Discovery skips
   `_groups`, so synth never legitimately references a `_groups` sibling — a
   same-dir sibling ref can only be corruption.)
3. **One-time cleanup** of the user's live `_groups/Demo` + `MSOffice` (stripped
   the `.scriptreetree` cross-ref leaves in place — non-destructive, kept the
   legit tools/folders).

## a105 addendum — the WRITER fingerprint + a universal chokepoint

The a104 fixes (push-back refusal + prune self-heal) did NOT stop the recurrence,
and the user gave the decisive clue: the corruption is an *active* cross-
contamination ("it adds the msoffice one to the demo tree, then the demo one to
the msoffice tree"), not stale residue. Re-forensics on the freshly-corrupted
files nailed the writer:

* **`./MSOffice.scriptreetree` (relative, WITH the `./` prefix)** — only the
  EDITOR's `_maybe_relative` adds a `./` prefix. `push_back`'s
  `_restore_relative_leaf_paths` emits a BARE `MSOffice.scriptreetree` (no `./`);
  the synthesiser emits ABSOLUTE candidate paths. So the `./` form ⟹ the editor
  (an `_item_to_node` → `_maybe_relative` → `save_tree` path).
* **absolute tool leaves alongside the relative sibling** — `_maybe_relative`
  (and `_restore_relative_leaf_paths`) only relativise a leaf that lives UNDER
  the file's dir; the external tools (other drives/roots) stay absolute, only the
  `_groups/` sibling goes relative. The mix is the signature, not a contradiction.
* **`synthesised_by: None`** — `synthesised_by` is NOT a `TreeDef` field, so it is
  dropped by ANY `load_tree → save_tree` round-trip. Its absence ⟹ the file was
  last written by `save_tree` (editor/push-back), never by the synthesiser
  (`categorize` writes it via a separate `write_text`).

**The robust fix (a105): guard the universal write CHOKEPOINT, not each path.**
The a98/a100/a104 guards were spread across many call sites and versions;
whichever one had a gap (or whichever old build was still resident) re-wrote the
cross-ref. `core.io.save_tree` is the ONE function every tree writer funnels
through (the synth's raw `write_text` excepted, and it's clean by construction).
`save_tree` now calls `_strip_sibling_group_refs(tree, path)`: for a `_groups/`
target it drops any leaf resolving to a same-dir sibling `*.scriptreetree`
(external/nested sub-tree refs preserved); for everything else it's a no-op
(cheap `parts` short-circuit). Now NO writer — editor, push-back, or future — can
persist the cross-ref, writer-agnostic.

**THE OTHER load-bearing lesson: a code fix only acts once it is the RUNNING
process.** The files kept re-corrupting at timestamps AFTER each deploy because
ScripTree is long-running/single-instance — the resident process held the OLD
`merged_tree.py`/`tree_view.py`/`io.py` in memory. Deploying byte-identical to
D:+R: is necessary but NOT sufficient; the user must fully QUIT (forest hub +
every cell + any lingering `pythonw.exe`) and relaunch for the new chokepoint to
load. When a "fixed + deployed" bug recurs with a post-deploy timestamp on a
long-running app, **suspect a stale process before assuming a code gap.**

## Reusable takeaways

1. **A "recurring" bug with all live guards intact is often un-healed RESIDUE,
   not an active re-write.** Reproduce against the actual on-disk files; check
   whether anything CLEANS the bad state, not just whether anything still WRITES
   it.
2. **If a writer strips the very marker your cleanup keys on, your cleanup is
   blind to that writer's output.** Make the cleanup recognise the corruption by
   STRUCTURE (an illegal `.scriptreetree` leaf inside a synth group), not just by
   a marker the corrupting path removes.
3. **Guard the whole artifact, not each child.** Refusing to push-back-write a
   `_groups` file at all is simpler and more robust than scrubbing individual
   sibling-group children — and it can't be defeated by a new nesting shape.
4. **The relative-`./` vs absolute path form, and the presence/absence of a
   `synthesised_by` marker, are reliable FORENSIC fingerprints** of which writer
   (`save_tree`/push-back/editor vs `categorize`) last touched a `_groups` file.
5. **A delete-heuristic must match the corruption SIGNATURE exactly, not a
   convenient superset.** "Any `.scriptreetree` leaf is corrupt" was easy to
   write and false — sub-tree leaves are legitimate. The real signature is
   narrower (a SAME-DIR sibling-group ref). A file-deleting self-heal that's even
   slightly too broad is silent user-data loss; an adversarial review caught it.
   Resolve + compare the actual target, don't pattern-match the suffix.
6. Builds on [[groups_discovery_feedback_loop_a98]] and
   [[forest_editor_circular_pushback_a100]] — same family, deeper cause: those
   stopped NEW corruption; a104 makes existing corruption self-heal.
