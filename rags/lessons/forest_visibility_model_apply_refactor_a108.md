# Forest visibility: the model→apply refactor that unified the 3 show paths (a108)

**Tag:** [v3-architecture] [forest] [windows] [refactor] [model-apply] [window-flags]
**Version:** v0.8.0a108
**Files:** `scriptree/shell/forest_visibility.py` (the refactor),
`scriptree/shell/forest_controller.py` (drag-capture + startup seeding),
`scriptree/shell/cell_window.py` (`_apply_always_on_top_flag` /
`_apply_taskbar_flag` decouple), `tests/test_forest.py` (+5 tests).
**Contract:** `docs/LLM/forest_show_apply_design.md` (read this first — it is the
authoritative design; the code merely enacts it).

## The symptom that triggered it (user words)

> "It's like the taskbar forest and the system tray forest icons are calling
> different code when clicked instead of the same code. Can you look over
> everything and see what needs refactoring/merging. **Don't try to add more
> patches to fix what is an underlying issue.**"

Plus three concrete bugs: (1) hub "wasn't mobile after loading"; (2) clicking
the forest icon "jumped to the top-left corner of the screen and lost its icon";
(3) "I move the forest then click the icon in the system tray, the forest moves
back to the position it was in when it was clicked to show."

## Root cause: three divergent show paths + three disagreeing position stores

The forest hub could be revealed three ways, each hand-written separately:

| Path | Entry | What it did with position |
|---|---|---|
| Tray click | `show_hub()` | FORCED `move(_last_hub_position)` |
| Taskbar click | `eventFilter` WindowStateChange → `_restore_descendants()` | did NOT move (trusted the OS) |
| Startup | `forest_controller.start()` | `move(position)` then `show()`/`showMinimized()` |

And three position sources that could disagree:
* `_last_hub_position` — written ONLY in `hide_hub()` (so a tray click BEFORE any
  hide moved the hub to a never-set / stale coordinate → "jumps to top-left").
* `ForestDef.window_position` — written on drag.
* live `QWidget.pos()`.

Because the tray path forced a STALE store and the taskbar path trusted the OS,
the two icons genuinely "called different code" → different results. Every prior
fix had patched one path; the user correctly diagnosed it as structural.

## The fix: one model, one idempotent render pass (the game/sprite pattern)

Ken's framing: "Games seemed to fix this problem ages ago with sprites/etc." —
a single source of truth + one render pass, events mutate the model, the renderer
reflects it. Implemented as:

* **`ForestHubState` dataclass** — the ONE model: `hub_position`, the 3 mode
  flags (`always_on_top` / `taskbar` / `tray`), `shown`, `hidden_descendant_ids`,
  and a derived `auto_hide` property. Replaces the 5 scattered manager fields
  (`_taskbar_on` / `_always_on_top` / `_auto_hide` / `_last_hub_position` /
  `_hidden_descendant_ids`).
* **`apply_state()`** — the single render pass. Reads the model, moves the hub to
  `hub_position` (clamped on-screen), shows or hides it with its descendants.
  Idempotent. **Never** invokes the bloom/layout engine (docking stays the
  docking engine's job).
* **`show_hub()` / `hide_hub()`** collapse to thin wrappers: set `state.shown`,
  call `apply_state()`. The taskbar-vs-tray branching inside the old `show_hub`
  is GONE (one branch in `apply_state` handles mode).
* **`_restore_descendants` DELETED** — its reveal loop is identical to the tray
  path's, so both became the shared `_reveal_hidden_descendants()`. The
  `eventFilter` taskbar-restore now calls `show_hub` → the SAME code as the tray.
* **Drag-capture** (the missing wiring): `forest_controller._on_hex_moved`
  already saved `window_position` on every hub move; it now ALSO writes
  `state.hub_position`. So the model's position is always live → a tray/taskbar
  show lands where the user LAST LEFT IT, not a stale show-time spot.

## The two non-obvious gotchas (carry these forward)

### 1. `setWindowFlags()` resets position to (0,0) and drops the hex mask — and the old code only repaired that `if was_visible`

`_apply_always_on_top_flag` / `_apply_taskbar_flag` toggle window flags, which on
Win11 RECREATES the native HWND → position reset to (0,0), `setMask` discarded,
`WA_TranslucentBackground` dropped. The pre-a108 code gated the position-restore
+ chrome-reassert behind `if was_visible: show(); _reassert_window_chrome()`.
**But the forest hub's flags are applied at startup BEFORE the first show**
(`manager.apply()` runs in `start()` before `forest_window.show()`), so
`was_visible` was False → the repair was SKIPPED → the hub ended up at (0,0),
blank, and with no established drag region. THAT is "jumped to top-left, lost its
icon, wasn't mobile after loading."

Fix: capture `pos()` BEFORE `setWindowFlags`, `move()` it back AFTER, and call
`_reassert_window_chrome()` UNCONDITIONALLY. Only the actual `show()` stays gated
on prior visibility. Verified on the offscreen platform: a hidden cell moved to
(180,160) survives both flag swaps with pos intact and mask non-empty.

### 2. `moveEvent` fires `hexagonMoved` on PROGRAMMATIC moves too → guard the drag-capture

`CellWindow.moveEvent` emits `hexagonMoved` on EVERY move (drag or programmatic),
and `_on_hex_moved` reads `forest_window.pos()`. So `apply_state`'s own
`showMinimized()`/`move()` would re-enter `_on_hex_moved`. If a minimise
transition ever reported pos (0,0), it would overwrite the good `hub_position`.
Guard the capture: only write `state.hub_position` when the hub is
`isVisible() and not isMinimized()` — a real user drag always satisfies this;
minimise/hide transitions don't. (`apply_state` captures the authoritative
hide-time position itself, before it minimises.)

## Deliberate deviations from the design doc (both lower-risk, same outcome)

1. **Kept the construction-time flag call** (`CellWindow.__init__` ~line 3743).
   The plan said remove it; instead, now that the helpers always restore pos +
   reassert chrome, the construction call *repairs* the mask its own
   `setWindowFlags` drops, and removing it risked silently un-stay-on-top'ing
   normal cells (their base flags don't carry `WindowStaysOnTopHint`).
2. **Startup keeps its explicit live-tuned first show** (`show()`+soft fade /
   `showMinimized()`) rather than routing through `apply_state()`. Startup SEEDS
   the model (`hub_position` from the placed pos; mode via `apply()`; `shown`
   per mode) so the model is truthful — then every LATER show is unified. The
   Win11 first-map flag timing + the macify fade are too delicate to re-route
   blind on a headless-only verification.

Both deviations are documented inline + in design §5/§6.

## Out of scope (explicitly preserved / deferred)

* **Docking engine fully PRESERVED** (design §6a): snap-and-dock, `_dock_partners`,
  `_check_undock`, drag-a-cell-drags-docked-children (a82), `_forest_descendants`
  dock-graph follow (a85), bloom (`_compute_layout`/`_start_expand`/
  `_remembered_offsets`) — all untouched. `apply_state` only show/hide/moves
  existing windows; it never re-tiles.
* **Resolution-change rigid-translate** (the third a107 deferred bug) is a
  SEPARATE `screen_watcher.rescue_all_cells` → `_compute_layout` re-bloom fix,
  still pending (task #61). NOT part of a108.

## Verification + the headless limit

109 forest tests green (104 + 5 new: `TestFlagSwapPreservesPositionWhenHidden`,
`TestApplyStateUnifiedShow` — the latter locks "show reads the LIVE
`hub_position`, not a stale show-time value"). Full suite 0 net-new (10 known
baseline). **This is forest window-core code: the unit suite proves the
model/contract but CANNOT confirm real Win11 show/restore/drag behaviour.** The
design §8 manual matrix is the acceptance gate; Ken live-tests a108. Deployed
byte-identical to `D:` + `R:`; **git HELD** per the standing release rule.

## Review hardening (a109) — two real bugs the model→apply refactor introduced

A 37-agent adversarial workflow (6 review dimensions → 3 refute lenses per
finding → completeness critic) on the a108 diff found **two real runtime bugs**
in the new code (both fixed in a109, with regression tests; forest suite 109→121):

1. **[HIGH] The hide branch was not idempotent.** `apply_state`'s hide path did
   `hidden_descendant_ids = []` then re-recorded from the *currently-visible*
   descendants. A SECOND hide while already hidden (the focus watcher stays
   enabled while hidden; two focus-left events >80ms apart, or the hide's own
   focus churn, re-fire `hide_hub`) found everything already hidden, recorded
   nothing, and WIPED the set the first hide captured → next show revealed no
   cells = the exact "forest comes back empty" bug the refactor existed to kill.
   **Fix:** early-return as a no-op when already hidden (`isMinimized()` taskbar /
   `not isVisible()` otherwise), preserving the set. **Lesson: a model→apply
   "render pass" must be idempotent on BOTH transitions — a redundant hide is as
   real an event as a redundant show, and destructive list-rebuild is the trap.**

2. **[MEDIUM] Clamp-on-show re-entered the drag-capture and destroyed the saved
   position.** `apply_state` show moves the hub to `clamp(hub_position)`;
   `moveEvent` emits `hexagonMoved` synchronously on that programmatic move;
   `_on_hex_moved` (visible+not-minimised) then wrote the CLAMPED value back into
   `state.hub_position` and persisted it. Showing a hub stored off-screen
   (monitor unplugged) thus silently destroyed the user's real position.
   **Fix:** a re-entrancy flag `_applying_state`, held True across the whole
   render pass (finally-reset), makes `_on_hex_moved` ignore apply_state's own
   moves. **Lesson: the SAME signal (`hexagonMoved`) carries both user intent
   and the render pass's own programmatic moves — Qt gives you no built-in way
   to tell them apart, so a render pass that moves windows AND a capture slot
   that listens for moves MUST gate the capture with a self-flag (or the cell's
   `_drag_started`). This is the dual of the a108 minimise-guard: the hide path
   was already protected by `not isMinimized()`; the show path's clamp was not.**

Four coverage gaps were also filled (drag-capture guard, eventFilter tray↔taskbar
parity, `apply(prefs)` transition, hide-with-real-descendants) — the code was
correct but the linchpins were untested, so a future regression of the a108 fix
would have shipped green. The review's 3 rejected findings were correctly killed
(e.g. "exact-coordinate asserts are fragile" — the offscreen screen is 800×800,
positions fit; "hide path re-overwrites position" — the `not isMinimized()` guard
already blocks it). **Meta-lesson: window-core code that can't be headlessly
verified still benefits enormously from an adversarial *code-reading* pass — the
HIGH idempotency bug was a pure logic error a careful reader caught from the
source, no live test needed.**

## Reusable takeaway

When the user says two UI affordances "call different code," resist patching each
path — collapse them onto ONE model + ONE idempotent apply. The position bug, the
(0,0) bug, and the snap-back bug were all facets of "N hand-written paths reading
N stores." A dataclass model + a single render pass made them one fix. And:
**any `setWindowFlags` call on Win11 must be treated as an HWND recreation** —
re-establish position + mask + translucent bg right after it, unconditionally,
because flags are often applied before the first show.
