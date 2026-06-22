---
topic: known_issue_bloom_overlap_and_second_display_spill
date: 2026-06-22
status: open-issue
related: [full_fit_slot_selection_no_clamp, collapse_expand_route_through_layout_engine, cell_positioning_central_tracker]
---
# OPEN ISSUE — shrink-then-bloom can overlap the forest icon / spill to a second display

## Status: DEFERRED by user ("leave the bloom as-is for now"), as of v0.8.0a78.

## Symptom (user-reported)

Collapse the forest (shrink) then expand it (bloom): cells sometimes **overlap
the forest icon**, or **spill onto a second display**.  NOT caused by a77 (which
only touched dragging and was reverted in a78) — this is in the collapse/expand
**bloom** path introduced/changed by a74.

## Where to look (next session)

- `CellWindow._start_expand` (a68 routed bloom through the engine; a74 made it
  full-fit + use the engine slot verbatim, no clamp).
- `CellWindow._compute_layout` — derives the screen rect from
  `screenAt(self.pos())` (the forest's own position).  On a multi-monitor setup
  this is the suspect for the **second-display spill**: confirm the slot world
  positions are tested against the CORRECT screen (the one the forest is on) and
  that a slot computed near a monitor boundary can't land on the adjacent
  display.  `is_on_screen` checks one screen's avail rect, so a spill implies
  either the wrong screen is chosen or the slot is accepted for the wrong rect.
- **Overlap on the forest icon**: `_compute_layout` explicitly forbids the
  master's own centre as a collider (~4481), so an overlap implies either the
  bloom animation start (members start AT the hub centre and animate out) is
  being read as the resting position, OR a member with no engine slot falls back
  to a position on the hub, OR a sub-master/ring recursion places a child on the
  parent.  Check the leaf-vs-submaster split in `_start_expand` and the
  fallback branch.

## Likely proper fix (when picked up)

Make the bloom multi-display-aware: pick the screen via the forest's CURRENT
position, compute + validate every slot against THAT screen's available rect,
and guarantee no member resolves to the hub's own cell rect.  Add a regression
test with a simulated two-screen geometry (QScreen list) asserting bloomed cells
all land on the forest's screen and none overlap the hub.

## Do NOT

- Do not "fix" this by reverting a74 — a74 was the fix for an EARLIER
  bloom-overlap; reverting reintroduces that.  Fix forward.
