---
topic: fast_drag_left_behind_is_a_throttle_gap_fixed_by_a_final_reflow
date: 2026-06-22
status: resolved
supersedes: "the earlier '_members divergence / sync _members' diagnosis in this same file (proven inert)"
related: [settle_rigid_slide_falls_back_to_engine_repack, full_fit_slot_selection_no_clamp, cell_positioning_central_tracker, known_issue_bloom_overlap_multidisplay]
---
# Fast-drag "cells gap / get left behind" is a THROTTLE gap at drag-end — fix with one un-throttled final reflow, NOT by removing the reflow and NOT by syncing `_members`

## The user symptom (item 10)

"Stack the cells one below the other with the forest at the top, docked, then
drag the forest QUICKLY down to the bottom of the screen — the repositioned
cells relocate but sometimes get left behind / a gap forms; and once it
happens, on the next move the gapped ones are left behind."

## Two WRONG fixes tried first (both recorded so future-me doesn't repeat them)

1. **a77 — removed `_live_edge_reflow_or_fold` entirely.**  REGRESSED corner
   drags: with the reflow gone, off-screen members merely clip during the drag,
   then drag-end `_settle_no_overlap` (a rigid block slide) can't fit the whole
   cluster and shoves the ENTIRE cluster — forest included — back on-screen.
   User: "I can't drag the forest to a corner if cells will go off-screen; it
   pushes everything back onto the screen."  Reverted in a78.  **The reflow is
   load-bearing**: it is what keeps the forest IN the corner while relocating
   the would-be-off-screen cells on-screen around it.

2. **The "sync `_members[mid]` in the reflow" idea (the prior text of THIS
   file).**  Proven INERT by an adversarial 3-agent trace of a78.  `_members[mid]`
   and `m._slot` are dead-cache at drag-end:
   - the per-frame rigid cascade moves each widget by `member.pos()+delta`
     (off the live WIDGET position), so it never reads `_members[mid]`;
   - `drag_targets` is keyed on `self._positioned`, never on `_members`/`_slot`,
     so a stale value can't drop a member from the next drag;
   - the ONLY post-drag reader of `_members`/`_slot` is `_compute_layout`'s
     corner no-fit fallback, which first clears `_slot` and re-derives every
     slot from the WIDGET centre (`m.pos()`), overwriting `_members` before use.
   So syncing `_members` would change ZERO user-visible behaviour.  **Lesson:
   don't trust a plausible bookkeeping-divergence story — trace which field is
   actually READ to position the widget.**

## The ACTUAL root cause (a78)

A timing gap, not a data-divergence bug:

1. The live `_live_edge_reflow_or_fold` (called every master-drag `moveEvent`,
   ~line 7345) is **wall-clock throttled to ~50 ms** (`if now-last < 0.05:
   return`).
2. Qt **COALESCES a fast drag** into a few large-delta `moveEvent`s.  The
   throttle is wall-clock, independent of event count — so the LAST reflow tick
   can fire at an **intermediate** master position and never again before
   release.
3. `mouseReleaseEvent` ran **no reflow at all** — v0.8.0 "P4" disabled the
   drag-end recompute (`_compute_layout` / `_reflow_members_after_master_move`)
   on purpose ("placed cells shouldn't move after I place them"), and release
   does not call the reflow.  The only drag-end pass is `_settle_no_overlap`.
4. `_settle_no_overlap` is a rigid block slide that (a) cannot re-tile members
   and (b) **explicitly SKIPS `_auto_hidden` members** (its subject loop), and
   its engine fallback fires only when the visible block can't slide AT ALL.

So two states survive to rest and nothing fixes them:

- **(a) stranded off-screen** — a member the throttle skipped, carried off-edge
  by the rigid cascade after the last tick.  (Often settle's block-slide can
  pull a *single* such member on; the real teeth are case (b).)
- **(b) folded-with-room — the one nothing else can rescue** — a mid-drag tick
  folded a member (`_auto_hidden` + `setVisible(False)`) because no on-screen
  slot existed at that INTERMEDIATE position, even though room exists at the
  RESTING position.  `_settle_no_overlap` skips `_auto_hidden`, and its engine
  fallback doesn't fire if the visible block can slide — so the member stays
  invisible forever.  This is the literal "left behind."

NOTE the rigid cascade itself is innocent: it reads the live `member.pos()` and
adds the same delta as the master, so a relocated member RIDES to the correct
offset.  On-screen offset "gaps" close themselves; the persistent failure is the
folded/stranded member with no final re-evaluation.

## The fix (a79) — one mandatory un-throttled reflow at drag-end

In `CellWindow.mouseReleaseEvent`, in the existing P4 block (gated by
`was_dragging and self.role=="master" and self._members`), replace the bare
`pass` with:

```python
self._last_live_reflow_time = 0.0          # clear the 50 ms throttle
try:
    self._live_edge_reflow_or_fold()        # re-evaluate at the TRUE rest pos
except Exception as exc:  # noqa: BLE001
    _log(f"mouseReleaseEvent: final edge-reflow raised {exc!r} id={self._id[:8]}")
```

It runs BEFORE `_settle_no_overlap`, so settle then tidies overlap on
correctly-relocated, visible members.

## Why this is correct and safe (adversarially verified, 3 lenses, all clean)

- **Corner-safe.**  It ADDS one invocation of the load-bearing reflow (a77 broke
  corners by REMOVING it).  The reflow anchors repack to `self.pos()` and never
  moves the master; in the canonical "forest + its own cells into an empty
  corner" case, settle's `_ok(0,0)` passes and the forest stays where dropped.
- **Honors the P4 "don't rearrange placed cells" spec.**  The reflow only
  `m.move()`s members in `off_ids` (currently >50% off-screen); on-screen members
  are passed as `fixed=on_ids`, kept verbatim by `group_layout.repack`, and the
  caller's apply-loop iterates `off_ids` ONLY — so a visible, correctly-placed
  member is structurally unreachable by any move here.  A normal (non-throttled)
  drag-end is therefore a strict positional NO-OP.
- **Throttle reset is safe.**  `_last_live_reflow_time` has no reader other than
  the reflow's own gate; clearing it to 0.0 just guarantees this one call runs,
  and the next drag's first tick (`now-0.0` large) runs immediately as desired.

## Known residual edges (NOT regressions from this fix — pre-existing, tracked)

- **Foreign cell adjacent to the corner.**  `repack` is blind to cells outside
  this group; an un-folded member could land on a foreign forest-docked cell,
  and settle (which then sees the overlap) block-slides the cluster off the
  corner.  This is the documented a73 obstacle-driven slide, present before this
  fix; the fix's only marginal effect is making a folded member a visible
  subject.
- **Multi-monitor.**  Classification uses a single screen (`screenAt(self.pos())`);
  a member fully visible on a SECOND monitor is mis-flagged off-screen and
  relocated/folded.  Pre-existing in the live reflow (already fires every
  moveEvent with the same single-screen logic) — see
  [[known_issue_bloom_overlap_multidisplay]] for the shared single-screen root
  cause and the planned union-of-screens fix.

## Regression tests (tests/test_chaos_movement.py, a79)

- `test_fast_drag_throttle_strands_member_then_release_rescues` — drives the REAL
  `moveEvent` path: a 2-step fast drag whose second step is throttled strands a
  docked member off-screen; the drag-end reflow must relocate it on-screen.
- `test_drag_end_rescues_member_folded_by_throttled_reflow` — the deterministic
  case settle can't fix: a folded member with room at rest is un-folded.
- `test_drag_end_runs_final_unthrottled_reflow` — the wiring: release invokes the
  reflow once with the throttle timestamp cleared to 0.0.

All three FAIL on a78 (no final reflow) and PASS on a79.  Full suite: 2366
passed, only the known-unrelated pre-existing failures.
