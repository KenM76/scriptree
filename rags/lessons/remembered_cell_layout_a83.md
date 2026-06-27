---
topic: remembered_cell_layout_feature
date: 2026-06-23
status: feature-landed-pending-release
version: 0.8.0a83
related: [forest_cluster_multidisplay_and_reflow_undock_fixes, full_fit_slot_selection_no_clamp, collapse_expand_route_through_layout_engine, cell_positioning_central_tracker]
---
# Remembered cell layout (a83) — forest hub remembers where the user puts cells

User ask: "remember the cell layout when I re-arrange them, keep it unless there
isn't space (then move only the affected cells); on expand, slide cells back to
where they were relative to the forest; and a right-click Cell layout →
Save/Load/Recent menu."

## Architecture (the data model is the key decision)

- **`CellWindow._remembered_offsets: dict[str, (dx,dy)]`** on the forest HUB,
  keyed by **`_member_offset_key(cell)`** = the cell's normalised
  ``_catalog_path`` (identical normalisation to ``forest_controller._norm``:
  ``Path(p).resolve().lower().replace("\\","/")``).  Value = ``member_top_left
  − hub_top_left``.  This is the **durable user intent**, kept SEPARATE from
  ``_members`` (the current, possibly-temporary position the engine/cascade/
  reflow write).
  - Keyed by PATH, not the runtime cell id (ids regenerate every launch), so it
    persists in the ``.scriptreeforest`` and rebinds to whatever cell holds that
    tool/tree path next session.  A cell with ``_catalog_path=None`` (e.g. a
    multi-hex RING master, which ``load_ring`` builds with no catalog path) has
    key ``None`` and is consistently never remembered/restored — rings own their
    own ``.scriptreering`` layout.

- **Capture (user intent only):** ``_capture_remembered_offset`` is called from
  ``mouseReleaseEvent`` ONLY at a real drag-end (gated on the local
  ``was_dragging`` snapshot, the same discriminator a81 Fix Y used).  Never from
  a system relocation (settle/reflow/``_compute_layout``/rescue/break-free/
  cascade), so the remembered offset can't drift to a system position.  It
  writes the hub dict + nudges ``ring_main._FOREST_CONTROLLER.forestChanged``
  (debounced autosave) — a pure member rearrange otherwise wouldn't mark the
  forest dirty (only a hub move did).

- **Restore-with-fallback:** ``_restore_remembered_offsets(move)`` places each
  member at ``hub.pos()+offset`` IFF it's WHOLLY visible across ALL monitors
  (``_visible_area_on_any_screen`` — the a80 union helper, never single
  ``screenAt``); otherwise leaves it for the engine and KEEPS the offset (it
  returns when space allows).  Returns the placed-id set.

- **Engine integration:** ``_compute_layout(instant, pinned=None)`` — pinned
  members are skipped in the pre-pass / Pass 1 / Pass 2 and their TARGET centres
  are seeded into ``occupied_centres`` so the engine tiles the rest AROUND them.
  ``pinned`` defaults to empty → byte-identical to pre-a83 for every existing
  caller (verified).

- **Call sites:** ``_start_expand`` (restore move=False → bloom animates to the
  remembered target), ``forest_controller.start``/``open`` (load
  ``ForestItem.rel_offset`` into the hub via ``_load_remembered_offsets_into_hub``
  then restore move=True + engine), ``screen_watcher.rescue_all_cells`` (restore
  after the hub clamp).

- **Persistence:** ``ForestItem.rel_offset`` (forest_io) — emitted only when set
  (pre-a83 files byte-stable); ``_sync_positions_into_items`` writes it from the
  hub dict, ``_load_remembered_offsets_into_hub`` is the inverse.

- **Named layouts:** ``.scriptreelayout`` (``layout_io.py`` +
  ``docs/LLM/scriptreelayout_format.md``) — ``{catalog_path, kind, rel_offset}``
  entries.  Forest right-click **Cell layout → Save / Load / Recent** (built in
  ``_populate_forest_menu``; MRU via ``recent_files.add_layout``/``get_layouts``).
  **Load = reposition-existing-only** (``_apply_layout``): match by path, move
  matched cells, skip unmatched entries, never spawn/remove; extra cells stay.

## THE gotcha — multi-monitor bloom clamp (caught by adversarial verify)

The first cut gated ``_start_expand``'s verbatim/no-clamp bloom branch on
``m._slot is not None``.  But a freshly-RESTORED (pinned) member has
``_slot == None`` (the engine skips assigning slots to pinned members).  So on a
multi-monitor setup, a restored member whose remembered spot STRADDLES A SEAM or
sits on a SECONDARY monitor (fully visible across the union, so restore pins it)
fell into the ``else`` branch and was run through ``_clamp_to_screen``, which
clamps to the SINGLE screen ``screenAt(target)`` returns — yanking it ~45px off
its remembered seam position AND potentially onto an engine-tiled neighbour
(a68-style overlap returns).  Single-monitor was unaffected (union == the one
screen → clamp is a no-op).

**Fix:** gate the verbatim branch on ``(m._id in placed or m._slot is not
None)``.  ``_restore_remembered_offsets`` has ALREADY proven each pinned
member's target is wholly visible across all monitors, so a pinned member must
use ``_members[mid]`` verbatim and never the single-screen clamp.  Regression
test: ``test_expand_restores_seam_straddling_member_verbatim`` (simulated
2-screen, member ``_slot=None``, asserts the bloom target == remembered spot,
not clamped).

Lesson: any "restore the user's absolute/relative position" path on a
multi-monitor setup must use the UNION-of-screens visibility test consistently;
mixing it with the single-screen ``_clamp_to_screen`` reintroduces the off-seam
/ overlap class.  (Same root family as the a80 ``_visible_area_on_any_screen``
work.)

## Known limitations (acceptable / future)

- A non-pinned ``_compute_layout`` (e.g. a spawn/absorb-triggered
  ``_repack_members(fixed=None)``) re-tiles a restored member to its ``_slot``
  world pos, temporarily overriding the remembered spot; the next restore
  (expand/load/rescue) puts it back (offset retained).  Eventually-consistent.
- A pinned member's stale ``_slot`` is not released from ``taken_slots``, so a
  near-full ring can leave one slot index unused (a gap, never an overlap —
  collision protection is via ``occupied_centres`` + SAT).  Optional future
  hardening.
- RING masters (no ``_catalog_path``) are never remembered (rings own their
  ``.scriptreering`` layout).  Future: explicit ring handling if desired.

## Verification

7 ``test_layout_io`` tests + 4 ``test_chaos_movement`` tests (restore on-screen,
skip-off-screen-retain, pinned-no-overlap, seam-straddle-verbatim).  Full suite
2383 passed (only the 9 known-unrelated pre-existing failures).  Adversarial
3-lens verify: capture gate clean (single caller, was_dragging-gated, no
a81/a82 entanglement), ``_compute_layout(pinned=None)`` byte-identical to
pre-a83, persistence round-trips; the one medium defect (the bloom clamp above)
was fixed and pinned by a test.
