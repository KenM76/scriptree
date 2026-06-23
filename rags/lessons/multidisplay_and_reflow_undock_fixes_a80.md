---
topic: forest_cluster_multidisplay_and_reflow_undock_fixes
date: 2026-06-22
status: fix-landed-pending-release
version: 0.8.0a82
related: [fast_drag_left_behind_is_a_throttle_gap, known_issue_bloom_overlap_multidisplay, cell_positioning_central_tracker, live_edge_reflow_races_rigid_drag]
---

# UPDATE v0.8.0a82 — "moving one cell shifts ANOTHER docked cell" (the dock-child cascade)

After a81, the undock/left-behind was fixed but the user still saw: "when I move
a cell to a new dock location, sometimes one of the OTHER cells shifts a little
and becomes offset" — and crucially flagged "it has something to do with a docked
relationship between the moved cell and the others." Spot on.

## Root cause — `move_to`'s Bug-4 cascade + break-free not detaching CHILDREN

The dock graph is a directed tree, SEPARATE from the forest link graph:
- `_dock_partner_id` / `_dock_edge` — the ONE cell this cell is docked to (its
  parent) and which edge of that partner it sits at.
- `_dock_children_by_edge` = `{edge: child_id}` — reverse index: cells docked to
  THIS cell's edges (its children).

`CellWindow.move_to` (~cell_window.py:10291, "Bug 4") cascades its move delta to
every cell in `self._dock_children_by_edge` (recursively). `snap_engine.detach_drag`
calls `src.move_to(slot)` to place a snapped cell — so when a dragged cell snaps to
its new spot, its dock-children are shifted by the same delta.

`_break_free_from_cluster` (fired at the 4px drag-start threshold for any non-forest
cell/ring) cleared the dragged cell's PARENT link (`_dock_partner_id`/`_dock_edge`,
popped self from the partner's `_dock_children_by_edge`) but LEFT
`self._dock_children_by_edge` (its own children) intact. So a dragged cell kept its
children, and the snap-commit `move_to` dragged them along. Log proof: dragging
`581d0284` snapped it `(-4,-16)`, and the three cells docked to it
(`2a7a19ec`/`e34ac36e`/`5afd4e2d`) all shifted by exactly `(-4,-16)`.

## Fix — break-free fully severs the cell from the dock graph (parent AND children)

In `_break_free_from_cluster`, after the parent-detach, also release each dock-child
(mirrors the master-disband child-release at ~cell_window.py:9075):
```python
for _edge, _child_id in list(self._dock_children_by_edge.items()):
    _child = registry.get(_child_id)
    if _child is not None and _child._dock_partner_id == self._id:
        _child._dock_partner_id = None
        _child._dock_edge = None
self._dock_children_by_edge.clear()
```
Result: dragging a single cell out moves ONLY that cell; its former dock-children
stay put (they keep `_group_master_id` — still forest members — and just lose the
dock-chain link). Re-dock works normally (`_set_cell_dock` rebuilds both directions
from geometry). The Bug-4 cascade is preserved for other `move_to` callers
(`dock_with`, programmatic) — it only goes dead for the user-dragged-then-redocked
cell, which is exactly the unwanted case.

State-consistency proven (adversarial 2-lens verify, both defect_found=false):
forward/reverse dock pointers are written atomically by `_set_cell_dock`, the
per-child guard `_child._dock_partner_id == self._id` skips a child that re-parented
elsewhere, and `_audit_membership` never reads the dock-graph fields so no audit
violation is possible. Test: `test_break_free_detaches_dock_children_so_redock_does_not_drag_them`
(fails pre-fix, passes post-fix). Full suite 2373 passed.

## FUTURE — tree-ring exemption (user-requested, not yet implemented)

The user wants an eventual exception: a tree RING (master) dragged as a unit should
carry ALL its docked components. The detach block is self-contained at the tail of
break-free; gate it on `self.role != "master"` to exempt rings, then re-verify the
`move_to` cascade for ring drags. ("Get it working the way you propose first" — so
a82 ships the unconditional version.)

## Non-blocking pre-existing observations (NOT introduced by a82)

- `_check_undock` clears `_docked_to` symmetry but leaves the dock graph
  (`_dock_partner_id`/`_dock_children_by_edge`) intact — a long-standing divergence
  between the adjacency set and the dock graph. Consider severing the dock-graph link
  there too when a cell fully leaves the cluster.
- Several one-sided `_docked_to.clear()` calls can transiently orphan a peer's
  reverse `_docked_to` entry; a symmetric-`_docked_to` invariant assertion in the
  chaos harness would catch regressions.

---


# UPDATE v0.8.0a81 — two residuals after testing a80 (both in `_settle_no_overlap`)

After the user ran a80 on the real two-monitor setup, the stacked-drag
left-behind (Fix A) was fixed, but two residuals remained — both traced (fresh
debug log) to `_settle_no_overlap`, which a80 did NOT touch:

**Fix X — settle nudged the cluster (single-screen `avail`).** Log showed
`_settle_no_overlap: forest-h shifted by (±25,±25) to clear 0 obstacle(s)`
repeating. `_settle_no_overlap._ok` tested "fully on-screen" against ONE screen
(`screenAt(pivot).availableGeometry()`), so a member that crossed onto the 2nd
monitor read as off-screen and settle slid the whole cluster a `size//3` (~25px)
spiral step to pull it back — "a cell shifts a little and becomes offset." Fix:
`_ok` now uses `_visible_area_on_any_screen(moved) < moved_area` (the same
union-of-screens helper Fix C added). Single-monitor: union-of-one == the old
single-screen full-containment test, BIT-EXACT (verified by sweeping hundreds of
edge positions; QRect inclusive-coord flush edges handled; integer area math).
NOTE the helper SUMS per-screen intersections (disjoint extended-desktop screens
→ sum == true union area; a seam-straddling cell counts both halves).

**Fix Y — system moves undocked cells (`_check_undock` on non-drag moves).** Log
showed `_check_undock: <id> fully left cluster` right after a settle shift.
`_settle_no_overlap` moves members via `_smooth_move` (async glide); those moves
fire `hexagonMoved → _on_hexagon_moved → _check_undock`, which dropped a member
from `_positioned` → "moved to a good spot but didn't complete docking / left
behind on the next drag." a80's Fix A guarded only the REFLOW's relocations
(`_GROUP_MOVE_IN_PROGRESS`); settle's async `_smooth_move` fires AFTER that guard
is gone. **Root fix (generalises Fix A):** gate `_check_undock` in
`_on_hexagon_moved` on the moved hex being USER-dragged
(`hex_win._drag_started`). Only the cell the user physically drags can
drift-undock; SYSTEM relocations (settle, reflow, `_compute_layout`) all move
cells with `_drag_started=False`.

**Why Fix Y loses no legitimate undock (closed proof, adversarially verified):**
`_drag_started=True` is set at EXACTLY one site (`_mouseMoveEvent_inner`,
~cell_window.py:6774), immediately followed by `_break_free_from_cluster()`
(~6795) for any non-forest cell with `_docked_to`/`_group_master_id` — which
CLEARS `_docked_to` BEFORE the `self.move()` that emits `hexagonMoved`. So by the
time `_on_hexagon_moved` runs for a user-dragged cell, its `_docked_to` is already
empty and `_check_undock` was ALREADY a no-op. The real user-drag-out undock is
done by break-free, not `_check_undock`. The forest root is exempt from break-free
but is never a `_docked_to` party in a way that should undock, and system moves
never move the root. So gating removes ZERO legitimate undock and kills every
spurious system-move undock. (Fix A's reflow guard is now redundant but harmless
— pure early-return; left in place as belt-and-suspenders.)

Tests (a81, tests/test_chaos_movement.py): `test_system_move_does_not_undock_member`
(drives the real `_on_hexagon_moved` chain; system move with `_drag_started=False`
must not undock) and `test_settle_does_not_shift_for_member_straddling_monitor_seam`
(seam-straddling member → settle makes NO `_smooth_move`). Also updated
`TestSettleEngineFallbackAtCorner` to pin a single 1920×1080 screen — its
"x=6000 is off-screen" premise broke on a multi-monitor host once Fix X made the
on-screen test union-aware (x=6000 is ON the 2nd monitor). Full suite: 2372
passed (only the 9 known-unrelated failures + 2 transient clipboard flakes).

Diagnosis tip reinforced: a process started BEFORE a deploy runs the OLD code in
memory (no hot-reload). Confirm the running build via Win32_Process CreationDate
vs the R: file mtime BEFORE concluding "the fix didn't work" — the user's first
"same problem" report was a79 (the a80 deploy had been HELD pending sign-off).

---

# Three forest-cluster bugs fixed in a80: reflow-undock (left-behind), multi-monitor clamp teleport, multi-display reflow/auto-hide misclassification

User report (running v0.8.0a79 on a single 3440×1392 ultrawide + a SECOND monitor
to its right): "after a fast drag one of the cells got left behind" and
"sometimes when I move a cell and dock it to another spot, another cell will
randomly offset itself so it is no longer aligned."

## How the live state was diagnosed (reusable method)

The running forest is a `pythonw.exe` launched from `R:\ScripTree\run_scriptreeforest.py`.
Diagnosis used three on-disk artefacts — no debugger:

1. **Process + version:** `Get-CimInstance Win32_Process` gave the forest PID and
   `CreationDate`.  Compare the process start time to the deploy/commit time of the
   build under test — Python does NOT hot-reload, so a process started BEFORE the
   deploy is running the OLD code in memory even if R:/D: on disk are newer.  Here
   the process started 11:46, after the a79 deploy (11:39), so a79 WAS live — which
   meant the still-present bug was a DIFFERENT bug, not an un-restarted fix.
2. **Verbose debug log** `%APPDATA%/ScripTree/logs/scriptree-debug-YYYY-MM-DD.log`
   (the `_log()` stderr tee; on when the Debug submenu toggle is set).  It records
   every `moveEvent`, `release`, `group-move`, `_clamp_to_screen`, `_check_undock`,
   `_settle_no_overlap`, `_try_spawn_master` with positions.  Grep the TAIL for the
   recent gesture.  (The `layout_trace` at `%TEMP%/scriptree-layout-trace-*.log` is
   richer but OPT-IN via `SCRIPTREE_LAYOUT_TRACE=1`, usually absent.)
3. **Saved state** `%APPDATA%/Roaming/ScripTree/default.scriptreeforest` +
   `forest_preferences.json` — the persisted positions/window_position.  A restart
   reloads these, which is the quick rescue for a stranded cluster.

The log was conclusive: `avail=(0,0,3440,1392)` (one screen) but the cluster sat at
`x≈6780` (off the right edge, i.e. a SECOND monitor); the forest oscillated between
`x=3383` (primary right edge) and `x≈6712` with `group-move … by (3329,4)` jumps and
repeated `_clamp_to_screen: clamped (6751,-15) → (3383,0)`; and the saved
`window_position` was `[24,1311]` (bottom-left).  One member (`ae463801`) was at
`(42,33)` while the other three were at `x≈6780` — the literal "left behind" cell,
preceded by `_check_undock: ae463801 fully left cluster`.

## Bug 1 — "left behind": the reflow's relocation TRIGGERS `_check_undock` (Fix A)

`CellWindow.moveEvent` runs the rigid cascade INSIDE `_GROUP_MOVE_IN_PROGRESS`
(add at the start, discard in `finally`), then calls `_live_edge_reflow_or_fold()`
AFTER that block — so the reflow runs with the guard CLEARED.  When the reflow
relocates an off-screen member with `m.move()`, that fires the member's
`hexagonMoved` → `ring_main._on_hexagon_moved`, which runs `_check_undock` whenever
`_GROUP_MOVE_IN_PROGRESS` is empty.  `_check_undock` drops a member from
`_docked_to`/`master._positioned` when its centre is `> snapDist*2 + size_px` (~92px)
from a docked peer.  A reflow relocation easily exceeds that (it can move a member to
the opposite side of the master), so the member is silently ejected from
`_positioned` — and the next master drag (cascade only moves `_positioned`) leaves it
behind.

**Fix A:** wrap the reflow's relocation loop in `_GROUP_MOVE_IN_PROGRESS.add(self._id)`
/ `try … finally: discard`.  The reflow is a coordinated SYSTEM relocation — exactly
what the guard exists to mark — so `_on_hexagon_moved` skips the drift undock during
it.  User-initiated undock (dragging a cell OUT) is unaffected: that drives the
MEMBER's own moveEvent (role != master → guard never set) so `_check_undock` still
fires normally.  Leak-proof: all fallible work (`repack`, throttle) returns before the
`add`; `set.add`/`discard` can't raise; the `finally` is total.

## Bug 2 — jitter / "reposition when they don't have to": clamp teleports to primary (Fix B)

`_clamp_to_screen(raw_pos)` did `screenAt(raw_pos)` and, when that was `None`, fell
back to `primaryScreen()`.  Dragging near the TOP edge of the second monitor puts the
cursor at a slightly-NEGATIVE y that is above EVERY screen → `screenAt` returns `None`
→ the forest was clamped to the PRIMARY's right edge (3383) even though it lived on
the second monitor.  As the cursor wobbled across y=0 the forest oscillated
3383↔6712, dragging the whole cluster back and forth.

**Fix B:** when `screenAt(raw_pos)` is `None`, prefer the screen the cell is CURRENTLY
on (`screenAt(self.pos())`, then `screenAt(centre)`), then the NEAREST screen (new
`_nearest_screen` helper: min squared distance to each screen's availableGeometry),
and only THEN the primary.  Proven a no-op on single-monitor (every branch collapses
to the sole screen; the Bug-2 clock/tray clamp is preserved because the tray strip is
inside the screen's *physical* `geometry()`, so `screenAt(raw_pos)` is non-None there
and the new fallback isn't entered).  Legitimate cross-monitor drags still work
(cursor over the target monitor → `screenAt(raw_pos)` non-None → fallback skipped).

## Bug 3 — cells relocated/auto-hidden though visible: single-screen classification (Fix C)

`_live_edge_reflow_or_fold` AND `_check_edge_fold` classified on/off-screen against
`screenAt(master.pos()).availableGeometry()` — a SINGLE monitor.  A member fully
visible on a SECOND monitor (master on the first) scored zero overlap → judged
off-screen → relocated onto the master's monitor (reflow) or auto-hidden
(`_check_edge_fold`).  That's "cells reposition when they don't have to" on
multi-monitor.

**Fix C:** new helper `_visible_area_on_any_screen(rect)` = SUM of the rect's
intersection area over ALL screens (extended-desktop screens are disjoint in
virtual-desktop coords, so the sum is the true union; a seam-straddling member counts
both halves; single monitor → one term → identical to the old `inter_area`).  Both
the reflow's off/on classification AND `_check_edge_fold` now use it, so a member is
relocated/hidden only when off EVERY monitor.  The rigid cascade still keeps the
cluster following the master across a bezel; the reflow only rescues the truly-invisible.

## What was traced CLEAN (so we did NOT touch it)

The DOCK path does NOT spuriously move a non-dragged cell: `_try_spawn_master`
Cases 2–5 explicitly "DO NOT repack"; the master-drag-end surgical repacks
(`_try_join_forest_near_member`, `_try_absorb_nearby_free_cells`) pass the COMPLETE
set of placed members as `fixed` (kept verbatim by `group_layout.repack`); the
fresh-spawn `master._repack_members()` only ever has the two freshly-docked cells;
and `_compute_layout` is never reached with a pre-placed member on a dock.
`_relocate_overlapping_members_individually` moves only members that GENUINELY overlap
(real polygon collision).  So symptom 2 is the multi-display misclassification (Fix C),
not a dock re-tile bug.  (Verified by a 3-lens adversarial trace.)

## Tests (tests/test_chaos_movement.py, a80) — each fails pre-fix, passes post-fix

- `test_reflow_relocation_does_not_undock_member` (Fix A — drives the real
  hexagonMoved → _on_hexagon_moved → _check_undock chain).
- `test_clamp_offscreen_point_keeps_cell_on_current_monitor` (Fix B — simulated
  2-monitor geometry via monkeypatch).
- `test_reflow_keeps_member_visible_on_other_monitor` (Fix C — reflow).
- `test_check_edge_fold_keeps_member_visible_on_other_monitor` (Fix C — auto-hide twin).

Adversarial verify (3 lenses): all `defect_found=false`; single-monitor proven
unchanged for B and C; Fix A's single-monitor change is the intended corrective
(members stay bonded through edge reflow instead of undocking).

## Residual / follow-ups

- Seam-straddling on FLUSH same-res monitors is now handled (sum-of-overlaps), but
  MIRRORED displays (coincident geometry) over-count — harmless (only inflates the
  visibility score, never wrongly hides).
- `_compute_layout`, `_settle_no_overlap`, and `_relocate_overlapping_members_individually`
  still build their `screen_rect` from `screenAt(master.pos())` (single screen) for
  PLACEMENT.  That's correct for clustering members around the master, but a future
  pass could make placement multi-display-aware too.  Shares the root with
  [[known_issue_bloom_overlap_multidisplay]].
- These three fixes are the same single-screen root cause as the deferred bloom /
  second-display-spill issue; that one (bloom path) is still open.
