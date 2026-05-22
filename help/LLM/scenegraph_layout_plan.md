# Scene-graph layout refactor — next-session plan

Carry-over plan from a session where the existing layout system was
identified as architecturally broken (multiple competing helpers,
each trying to keep cells positioned correctly, none of them being
the single source of truth).  This document records the design so
the work can resume in a focused session.

## Why the current system is fragile

Cell positions are stored as **absolute screen coordinates** in
`master._members: dict[id, QPoint]`.  Multiple helpers mutate them:

| Helper | Purpose | Conflicts with |
|---|---|---|
| `_shift_positioned_members(dx, dy)` | translate during drag | repack, settle |
| `_cascade_translate_positioned(dx, dy)` | nested drag cascade (v0.6.32 — REVERTED v0.6.34) | repack |
| `_check_edge_fold()` | auto-hide off-screen | reflow |
| `_live_edge_reflow_or_fold()` | reflow off-screen during drag | check_edge_fold |
| `_resettle_overlapping_neighbours()` | overlap watchdog (v0.6.32 — REVERTED v0.6.34) | EVERYTHING |
| `_resolve_member_stacking()` | un-stack at startup | repack |
| `_settle_no_overlap()` | spiral-search non-overlap | reflow |
| `_repack_members(fixed=...)` | place at canonical slots | shift, settle |

Symptoms: members jumble at startup, cells move randomly, dock gaps
open, click-to-collapse stops working when a helper interrupts the
animation.  Each new fix has been a seventh helper that races with
the previous six.

## The right model — slot-based scene graph

Replace `dict[id, QPoint]` with **slot index** on every cell:

```python
class CellWindow:
    _group_master_id: str | None         # parent link (KEEP)
    _slot: tuple[str, int] | None        # ("inner", n) | ("outer", n) | None
```

`None` = floating-free (broken from cluster), still linked.

**Single layout function** on master:

```python
def _layout_tick(self):
    for child_id in self._children:
        child = registry.get(child_id)
        if child is None: continue
        if child._slot is None: continue    # floating — skip
        target_x, target_y = slot_world(
            self.pos(), self._size_px, self._shape,
            self._orientation, child._slot, child._size_px,
        )
        if abs(child.pos().x() - target_x) > 1 or \
           abs(child.pos().y() - target_y) > 1:
            child.move(target_x, target_y)
```

Called from `moveEvent` on the master (cheap; few children).  Same
function handles initial layout, drag cascade, post-collapse expand
— there is no other position-mutation path.

## What this kills

ALL of these become unnecessary and get deleted:

- `_shift_positioned_members`
- `_check_edge_fold` (replaced by visibility computed per-tick from slot world coords)
- `_live_edge_reflow_or_fold`
- `_resolve_member_stacking` (overlap impossible by construction)
- `_settle_no_overlap` (overlap impossible)
- `_repack_members` (slot computation is the entire repack)

## What stays

- `_group_master_id` (parent link)
- `_break_free_from_cluster` (sets `_slot = None`, keeps `_group_master_id`)
- The drag-snap engine (assigns a `_slot` on commit instead of mutating absolute coords)
- `_start_collapse` / `_start_expand` — but they no longer mutate `_members`; they trigger an animation overlay that visually moves children to master.pos(), and on expand the layout tick puts them back automatically because `_slot` never changed.

## On-disk migration

Currently `.scriptreeforest` and `.scriptreering` store `position: [x, y]` per member.  Migrate:

* On load: if `position` present and no `slot`, infer `slot` by nearest-slot lookup against the loaded master's geometry.
* On save: always write `slot`.  Optionally also write derived `position` for forward-compat readers.

No schema bump needed — `slot` is additive.

## Audit data from this-session backup

The 2026-05-22 backup (`D:\Dev\ScripTree-pre-scenegraph-20260522-103856.zip`) contains the pre-refactor code if a rollback is needed.  An exhaustive enumeration of all `_members[id]=` / `_positioned.add` / `_dock_partners.add` / `_group_master_id=` write sites was produced during that session's audit; it's preserved in the session transcript and listed ~60 touchpoints across `cell_window.py` and `forest_controller.py`.

## Phase plan for the next session

1. **Audit (Explore subagent)** — re-run the write-site enumeration.
2. **Plan (Plan subagent)** — produce ordered phases including
   on-disk format migration.
3. **Phase 1**: Add `_slot` field; co-exist with `_members` (slot is
   the new authority but write to both during transition).
4. **Phase 2**: `_layout_tick` replaces `_repack_members`.
5. **Phase 3**: Delete shift / cascade / reflow / check-edge-fold /
   settle / stacking helpers; their call sites all funnel through
   `_layout_tick`.
6. **Phase 4**: `.scriptreeforest` / `.scriptreering` writers emit
   `slot`; readers infer slot from position when not present.
7. **Phase 5**: Delete `_members` writes everywhere except the tick;
   make `_members` a derived computed view (or remove entirely).
8. **Phase 6**: Drag-snap commit assigns `_slot` directly.
9. **Phase 7**: Tests — add slot round-trip tests; replace
   position-asserting tests with slot-asserting tests.

## Reverts shipped in v0.6.34 (this-session baseline)

v0.6.34 removed the v0.6.32 helpers that introduced the worst races:

- `_resettle_overlapping_neighbours` (the watchdog that moved cells around at random)
- `_cascade_translate_positioned` (the helper that interfered with collapse animations)
- `_try_redock_to_sibling` (the re-link path that caused cells to disappear)
- `_resettle_positioned_to_home` (uncalled helper, removed for tidiness)

Startup `_repack_members` now runs with `instant=True` so the
canonical layout snaps in immediately (no 260 ms eased animation
glide from stale-saved positions, which the user perceived as
jumble).

Collapse / expand now arm a 1 s safety watchdog that force-clears
the `_collapse_state` if any animation's `finished` signal goes
missing — so a stuck "collapsing" / "expanding" state can no longer
block subsequent single-clicks.

These are *patches* on the broken model.  The scene-graph
refactor above is the durable fix.
