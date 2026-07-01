# Bloom relocation = a settle-vs-capture async race poisoning the remembered offset (a113)

**Tag:** [v3-architecture] [forest] [layout] [async-race] [remembered-offsets]
**Version:** v0.8.0a113
**File:** `scriptree/shell/cell_window.py` — `_capture_remembered_offset` (~9721),
`mouseReleaseEvent` (~7040), `_settle_no_overlap` (~10307), `_smooth_move`
(~10978), `_restore_remembered_offsets` (~9787), `_start_expand` / `_compute_layout`.

## Symptom (user, persisted through a108–a112)

Occasionally, when the forest hub is expanded (bloomed), ONE member cell
relocates to a different honeycomb slot instead of returning to where the user
last dragged it — "even though its space is still free." **Intermittent.** The
user stacked two cells above the hub; the **higher** one relocated. The debug
log showed `_restore_remembered_offsets … restored 3/5` and `4/5` — so 1–2
members per bloom were not being pinned and got engine-tiled.

## Root cause — an async animation vs a synchronous read, in the same turn

The a83 "remembered offsets" feature stores, at drag-drop, a member's offset
from its hub (`hub._remembered_offsets[path_key] = (dx,dy)`), and on bloom
restores members to `hub.pos()+offset` IF the spot passes an on-screen fit-test,
letting `_compute_layout` tile the rest around them.

The bug is the **order of two calls in one `mouseReleaseEvent` turn**:

1. `_settle_no_overlap()` runs FIRST (line ~7215). For an overlapping or
   edge-straddling drop it relocates the cell via `_smooth_move` → a
   **`QPropertyAnimation` on `b"pos"`** (`self._pos_anim = anim; anim.start()`).
   A `QPropertyAnimation` updates the widget position **only on later
   event-loop turns** — `self.pos()` does NOT change synchronously.
2. `_capture_remembered_offset()` runs SECOND (line ~7229), reads `self.pos()`
   **now** — the PRE-settle position — and stores it. Poisoned offset.

On the next bloom, `_restore_remembered_offsets` fit-tests the poisoned
`hub.pos()+offset`; if that stale spot is off-screen / straddling an edge it
fails `_visible_area_on_any_screen(rect) >= sz*sz`, the member is dropped from
`placed`, and `_compute_layout(pinned=placed)` re-tiles it to a **different
slot** — the relocation.

**Why intermittent:** a clean drop (fully on-screen, no overlap) hits settle's
`if _ok(0,0): return` early — no animation — so capture reads the FINAL position
and the offset is correct. Only a drop that overlaps a neighbour (settle's
overlap threshold is centre-distance < 0.75·size, and honeycomb neighbours sit
~0.86·size apart, so "stack directly above" trips it) or straddles a screen edge
takes the async spiral path and poisons the offset. The *higher* of two stacked
cells is the one dropped nearest its sibling/an edge → the one that relocates.

## The fix

`_capture_remembered_offset` reads the in-flight animation's **`endValue()`**
(the settled destination) instead of the live `pos()`, for the member AND the
hub (a master drag can leave the hub itself animating):

```python
def _resting_xy(widget):
    anim = getattr(widget, "_pos_anim", None)
    if anim is not None:
        end = anim.endValue()        # QPoint the widget is animating toward
        if end is not None:
            return end.x(), end.y()
    return widget.pos().x(), widget.pos().y()
sx, sy = _resting_xy(self); hx, hy = _resting_xy(hub)
hub._remembered_offsets[key] = (sx - hx, sy - hy)
```

Synchronous settle branches (`self.move()` teleport for >max_animate_px or the
engine fallback) already complete before capture runs, so the endValue read
covers the only stale case (the animation). Test:
`TestA113CaptureUsesSettledPosition` (endValue used when animating; `pos()` used
otherwise).

## a114 — the ACTUAL cause (the diagnostic paid off)

a113's endValue fix was a real bug but a **rarer sub-case**. When Ken re-tested,
the `[reloc-diag]` line I'd added told the true story in one repro:

```
_restore_remembered_offsets forest-h: restored 3/5 member(s)
  [reloc-diag] NOT restored: 3af65742=no-offset(key=…/msoffice.scriptreetree),
                             29fb1c6f=no-offset(key=…/scriptreemanagement.scriptreetree)
```

`no-offset` — not `offscreen`. Correlating the ids against the log, those two
cells were **spawned but never dragged** this session. The a83 feature only
remembers positions the user **explicitly dragged**; a cell never dragged has no
remembered offset, so on every bloom it falls through to `_compute_layout` and
gets **re-tiled to a possibly-different honeycomb slot** — the relocation. It's
"intermittent" only in the sense that it hits whichever cells the user didn't
happen to drag, and the slot the engine picks shifts as the pinned set changes.

**Fix (a114):** on a re-bloom, pin **every** member at its current on-screen
`_members[mid]` home, not just the dragged ones — new helper
`_current_home_pins(members, already_placed)`, unioned into `placed` in
`_start_expand` so `_compute_layout` only tiles genuinely new / off-screen cells.

**Critical guard (or it regresses a68):** `_members[mid]` is an ABSOLUTE
coordinate. If the hub was **dragged while collapsed**, those homes are stale
(relative to the old hub spot) and must be engine-tiled around the new hub
position — exactly what `TestCollapseExpandUsesEngine` (a68) asserts. So
`_start_collapse` snapshots `_hub_pos_at_collapse`, and the home-pin applies
**only when `hub.pos() == _hub_pos_at_collapse`** (hub didn't move). Same-spot
bloom → keep every cell where it was; moved-hub bloom → engine re-tiles.

## Reusable takeaways

1. **A `QPropertyAnimation` is a WRITE-LATER.** Any code that reads
   `widget.pos()` in the same synchronous turn that started a `pos` animation
   reads the OLD value. To capture "where it will end up," read `anim.endValue()`
   — never the live position.
2. **Order matters when one step is async.** `settle()` then `capture()` looks
   fine until you notice `settle()` schedules an animation. The classic fix is
   either read the intended end-state, or defer the capture past the animation
   (`QTimer.singleShot(duration+ε, ...)`). We chose the deterministic
   end-value read.
3. **"Intermittent" + "only sometimes" ⇒ look for a data-dependent branch**
   (here: the drop tripping settle's overlap/edge spiral). The RCA that found
   this fanned out one agent per facet of the capture→restore→tile path and had
   each trace the exact call order + the sync-vs-async boundary — the
   intermittency fell out of the `if _ok(0,0): return` early-exit.
4. **Instrument the silent skip.** `_restore_remembered_offsets` silently
   `continue`d past un-restorable members; adding a per-member skip-reason log
   (no-key / no-offset / offscreen(target,vis)) is what makes such an
   intermittent layout bug observable on the next repro.
