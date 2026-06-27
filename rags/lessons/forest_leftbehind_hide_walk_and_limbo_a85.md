---
topic: forest_cells_left_behind
date: 2026-06-25
status: fixes-landed-pending-release
version: 0.8.0a85
related: [forest_login_autostart, group_aware_rescue_repack, full_fit_slot_selection_no_clamp, remembered_cell_layout_feature, multidisplay_and_reflow_undock_fixes]
---
# "Cells left behind" — two independent bugs (a85): dock-graph hide walk + on-screen limbo

User report: sometimes cells are left on the desktop. Two scenarios:
- **A (forest auto-hide / not-always-on-top):** the hub AND the cell docked
  directly to it disappear, but a stack of ~3 further cells (docked one-to-the
  next, a separate sub-cluster) stay visible.
- **B (forest always-on-top):** occasionally ONLY the cell docked directly to
  the hub vanishes, while the hub and all other cells stay.

These are **two different bugs in two different subsystems**, not one root cause.

## Bug A — the hide walk follows the LINK graph but not the DOCK graph

`ForestVisibilityManager.hide_hub` (forest_visibility.py) hides exactly what
`_forest_descendants()` returns. Pre-a85 that walk iterated only `hub._members`
and recursed into a member's `_members` **only if `role == "master"`**. It
never consulted the **dock graph** (`_dock_children_by_edge`).

Verified membership facts (so the fix targets the real gap, not the workflow
synthesis's first guess):
- A cell docked DIRECTLY to the hub → `_try_spawn_master` **Case M2**
  (cell_window.py ~11656) sets `_group_master_id = hub` and adds it to
  `hub._members`. Cells then chained onto it → **Case 2** (~11804) also land
  FLAT in `hub._members`. So a *simple* chain is fully reachable and DOES hide
  — which is why "the directly-docked cell" disappears correctly.
- A **ring / sub-cluster dragged onto the forest** → **Case M1** (~11648):
  *"a ring docking onto anything is purely spatial — no link change."* It wires
  only `hub._dock_children_by_edge`; it is NEVER added to `hub._members` and its
  `_group_master_id` is not the hub. It follows the forest visually (the move
  cascade walks the dock graph) but is invisible to `_forest_descendants` → the
  whole sub-cluster is **left behind on hide**.
- `_break_free_from_cluster` (~8680) deliberately PRESERVES membership
  (`_group_master_id` kept, stays in `master._members`), so dragging the cluster
  around does NOT drop cells from `_members` — ruling break-free out as the
  trigger. The load-time `_attach_existing_master_as_member`
  (forest_controller.py ~1335) DOES make a ring a member, but the *interactive*
  Case-M1 drag-dock does not.

**Fix:** `_forest_descendants._walk` (forest_visibility.py ~1144) now enqueues
BOTH `parent._members` AND `parent._dock_children_by_edge.values()`, and
recurses through EVERY node (the `role == "master"` gate is gone; a plain cell
can carry a dock-chain). The `seen` set bounds it and dedupes the two graphs.
Restore is automatic: `hide_hub` records every enumerated visible cell in
`_hidden_descendant_ids`, and `show_hub` (~694) re-shows + rescues exactly
those — so fixing the hide-time enumeration auto-fixes restore.

Invariant restored: *everything reachable in the on-screen dock cluster is also
enumerated by the hide walk.*

## Bug B — `_compute_layout` auto-hides an unslotted member that can't fit

In always-on-top mode `hide_hub` is never involved. The vanishing is the
**layout engine**: `_compute_layout` Pass 2 (cell_window.py ~4666) hides a
member it can't place — `_slot is None` and not `_floating_intent` (LIMBO: no
free full-fit slot) → `_auto_hidden.add` + `setVisible(False)`. The only un-hide
is a LATER pass that finds it an on-screen slot. If a docked sibling / non-member
cell keeps the nearby slots occupied (`nearest_free_slot` returns None at
`fraction_required=1.0`), none ever opens and the cell stays gone.

**Fix:** keep an on-screen limbo member VISIBLE at its current position instead
of hiding it (leave `_slot` None so the next pass tiles it when a slot frees) —
"a visible cell beats a vanished one". Gated two ways:
1. **on-screen** (`is_on_screen(...,1.0)`) — a genuinely off-screen limbo member
   still auto-hides (preserves the a74/a80 behaviour + the chaos invariant "no
   visible member fully off-screen").
2. **non-overlapping** — see the gotcha below.

## THE a85 gotcha (caught by adversarial verify) — keep-visible MUST collision-check

First cut gated keep-visible on `is_on_screen` ALONE. But limbo is entered
*precisely because* the member's slots are blocked — `nearest_free_slot` returns
None when every on-screen slot is taken, off-screen, **or COLLIDING**
(layout.py:239 `any_polygon_collides`). So the member's current spot can sit ON
TOP of a sibling or the hub; keeping it visible there re-admits the exact
a67/a74 visible-overlap class the auto-hide was preventing — and chaos invariant
#1 (polygon SAT) would catch it, but the first regression test placed the member
non-overlapping so it slipped through.

Also flagged: `_floating_intent` is **never set True in production** (only in a
test), so the `if m._floating_intent` branch is dead and the limbo `else`
catches EVERY unslotted non-pinned member — widening the blast radius.

**Final fix:** before keeping a limbo member visible, collision-check it with the
SAME primitive the slot engine uses — `tiling.any_polygon_collides(c_spec,
size, centre, others, slop_px=0.5)` where `others` is built from
`occupied_centres` (already in scope in Pass 2; it holds the hub centre + every
Pass-1-slotted sibling + external visible cells). On collision → fall back to
auto-hide. Each kept-visible limbo member is also added to `occupied_centres` so
a second limbo member in the same pass sees it. Net rule:
**try-slot → if-blocked-and-on-screen-and-not-overlapping keep visible → else hide.**

Lesson: any change that makes the layout engine KEEP a cell visible without a
slot must run the engine's own collision check (`any_polygon_collides` over
`occupied_centres`), or it silently reintroduces the overlap class. And a
regression test for "keep visible" must place the cell in an OCCUPIED position
and assert `_polygon_overlap_pairs == []`, not just assert visibility.

## Process note (recurring): pin review agents to the MAIN tree

For the SECOND time this session, an adversarial review agent dispatched from
the worktree session read the stale a82 worktree by default and produced nothing
usable. The re-run with an explicit "confirm symbol X exists in
`D:\Dev\ScripTree\...` or STOP — do NOT read `.claude\worktrees\`" guard worked.
Always pin review/explore agents to the main tree path with a self-check when
the session CWD is a worktree.

## Verification

`tests/test_chaos_movement.py`: `test_forest_descendants_follows_dock_graph`
(Bug A — real CellWindows + a real ForestVisibilityManager, Case-M1 ring +
plain-cell dock chain), `test_onscreen_limbo_member_stays_visible` (+ overlap
assertion), `test_onscreen_limbo_member_hidden_when_it_would_overlap` (the
collision guard), `test_offscreen_limbo_member_stays_hidden`. Bug A + Bug-B-keep
tests fail pre-fix. Full suite 2413 passed (only the ~9 known-unrelated
pre-existing failures). Deployed D: + R: at a85; git/GitHub HELD pending user
testing. A timestamped pre-change backup zip was taken before the edits.
