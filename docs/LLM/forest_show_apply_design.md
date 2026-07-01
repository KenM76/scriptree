# Forest visibility: the model→apply refactor (design spec, v0.8.0a108)

> **Status:** DESIGN — the contract the a108 implementation must follow.
> **Scope:** the forest HUB's position / visibility / window-mode handling in
> `scriptree/shell/forest_visibility.py`, with thin touch-points in
> `scriptree/shell/forest_controller.py` (startup + drag capture) and
> `scriptree/shell/cell_window.py` (flag application / chrome reassert).
> **Out of scope:** the cell bloom/layout ENGINE (`_compute_layout`,
> `_start_expand/_collapse`, `_remembered_offsets`) — that is a separate concern
> and is NOT being rewritten here. Multi-monitor clamping stays.

---

## 1. The problem this replaces

Today the forest hub is made visible by **three independent, divergent code
paths**, each imperatively poking the OS window in its own order, with the hub's
position cached in **three places that disagree**:

| Path | Trigger | Position handling | Cells |
|---|---|---|---|
| `show_hub()` taskbar branch | tray click (taskbar mode) | `showNormal()` → `move(_last_hub_position)` | reveal descendants |
| `show_hub()` tray branch | tray click (tray-only) | `move(_last_hub_position)` → `show()` | reveal descendants |
| `eventFilter` → `_restore_descendants()` | taskbar entry click | **does NOT move** (trusts OS restore) | reveal descendants |
| `forest_controller.start()` | startup | `move(pos)` → show → `_restore_remembered_offsets` + `_compute_layout` (re-tile) | engine-tiled |

Three position stores: `ForestVisibilityManager._last_hub_position` (written
ONLY in `hide_hub()`), `ForestDef.window_position` (written on every drag via
`forest_controller._on_hex_moved`), and the live `QWidget.pos()`.

### Observed symptoms (all are facets of the same structural defect)

1. **Tray-show snaps the hub back to a stale spot.** Dragging the visible hub
   never updates `_last_hub_position` (only `hide_hub` does), so a later tray
   click restores the *pre-drag* position.
2. **Taskbar restore keeps position; tray restore moves it.** Different paths,
   different behaviour for the same intent ("show the forest").
3. **Click → hub jumps to (0,0) + loses its icon, then recovers.**
   `setWindowFlags()` (always-on-top / taskbar toggles) RECREATES the native
   HWND — resetting position to (0,0) and dropping the hex mask +
   `WA_TranslucentBackground`. Chrome is only re-asserted `if was_visible`; at
   startup the flag apply runs BEFORE the first show, so the reassert is skipped
   and the window comes up at (0,0), maskless, and not fully input-registered.
4. **Hub not draggable until a hide/show cycle.** Same root as (3): the HWND
   that the flags were applied to was never cleanly shown, so Qt's input setup
   for the frameless drag isn't finalised until a later flag/show cycle.
5. **Cells "sometimes bloom and overlap."** Startup runs the layout engine
   (re-tile); runtime show paths preserve positions; taskbar does neither — the
   same gesture yields different layouts.

`_restore_descendants` and `show_hub`'s descendant-reveal block are **literally
copy-pasted** (same loop, same `_rescue_cells_on_screen`).

---

## 2. The concept: one model, one idempotent `apply()`

Borrowed from how games handle sprites: a sprite has **one** transform; events
mutate the model; **one render pass** reflects the model to the screen. Nothing
else stores "where it is," and no event handler "draws" — they set state and let
the single renderer reflect it. Two events that mean the same thing produce the
same result because they call the same render with the same state.

Applied to the forest (Qt windows are OS-owned, so this is **model → apply on
events**, not a timed render loop, but the discipline is identical):

* **One model** owns the hub's truth: position, window-mode, shown/hidden.
* **One `apply(state)`** is the ONLY function that moves / shows / hides the hub,
  sets its flags, and re-asserts its chrome. It is **idempotent**.
* **Events mutate the model, then call `apply()`.** Tray click, taskbar restore,
  startup, flag toggle, focus-loss hide — all become: set model → `apply()`.
* **Position is read from the model and written only by user intent** (drag).
  `apply()` NEVER repositions the hub except an on-screen clamp.

---

## 3. The model — `ForestHubState`

A small dataclass owned by `ForestVisibilityManager` (single instance per
forest). It is the SINGLE SOURCE OF TRUTH for the hub.

```python
@dataclass
class ForestHubState:
    # The hub's desired top-left in global screen coords.  THE one position
    # store.  Written only by user drag (drag-end) + the initial load.  Read by
    # apply().  None = "no stored position yet; let the OS place it once".
    hub_position: QPoint | None = None

    # Window MODE (mutually-derived from the 3 visibility prefs).
    always_on_top: bool = True
    taskbar: bool = False        # hub carries Qt.Window (taskbar entry)
    tray: bool = False           # a tray icon exists

    # Desired visibility of the whole forest.
    shown: bool = True           # False => hidden/minimised per mode

    # Which descendants were hidden when the forest was last hidden, so a show
    # can reveal exactly them (and only them).  Owned here, not scattered.
    hidden_descendant_ids: list[str] = field(default_factory=list)
```

`auto_hide` (the focus-watcher enable) is **derived**: `not always_on_top and
(taskbar or tray)` — keep that derivation in one helper, don't store it.

---

## 4. `apply()` — the single render pass (the contract)

`ForestVisibilityManager.apply_state()` is the ONLY code that touches the hub
window's flags / visibility / position. It MUST be idempotent and ordered:

```
apply_state():
    w = forest_window; if w is None: return
    suppress the focus-watcher briefly (ride out focus shuffle)

    # (A) FLAGS FIRST — flag changes recreate the HWND, so do them before
    #     positioning/showing, and ALWAYS reassert chrome after a change.
    desired_flags = compute_flags(state)        # Qt.Tool/Window + StaysOnTop
    if w.windowFlags() != desired_flags:
        w.setWindowFlags(desired_flags)         # recreates HWND, drops mask, → (0,0)
        w._reassert_window_chrome()             # UNCONDITIONAL — mask + translucency
        flags_changed = True

    # (B) POSITION — from the model, clamped on-screen.  Set BEFORE show so the
    #     window never flashes at (0,0).  Never invent a position.
    if state.hub_position is not None:
        w.move(clamp_on_screen(state.hub_position))

    # (C) VISIBILITY — reflect state.shown, mode-aware (NOT a separate code path
    #     per trigger).
    if state.shown:
        if state.taskbar: w.showNormal()        # taskbar entry, restorable
        else:             w.show()
        shown_cells = reveal_hidden_descendants()   # the shared helper
        rescue_cells_on_screen(shown_cells)
        w.raise_(); w.activateWindow()
    else:
        capture_hub_position()                  # snapshot live pos into model
        hide_or_minimise(mode)                  # hide() or showMinimized()
        hide_visible_descendants()              # track ids into state
```

### Idempotence rules
* If flags already match → skip the HWND recreation (this is what stops the
  needless (0,0)/mask-drop on a no-op apply).
* Calling `apply_state()` twice with `shown=True` just re-shows + re-clamps — no
  drift, no re-bloom.
* `apply_state()` NEVER calls the layout engine (`_compute_layout`) — revealing
  cells preserves their positions; only the on-screen rescue may nudge a
  genuinely off-screen cell.

---

## 5. Event → model mappings (every entry point)

Each handler becomes "mutate model, then `apply_state()`" — nothing else:

| Event | Handler | Mutation | Then |
|---|---|---|---|
| **User drags hub** | drag-end (capture) | `state.hub_position = w.pos()` | — (window already there; no apply) |
| **Tray icon click** | tray `on_activate` | `state.shown = True` | `apply_state()` |
| **Taskbar entry click** | `eventFilter` WindowStateChange (un-minimise) | `state.shown = True` | `apply_state()` |
| **Flag toggle** (AOT / taskbar) | prefs apply | update mode flags | `apply_state()` |
| **Focus-loss / manual hide** | focus watcher / hide action | `state.shown = False` | `apply_state()` |
| **Startup** | `forest_controller.start()` | seed model from prefs (`hub_position` from placed pos, mode via `apply()`, `shown` per mode) | keep the live-tuned first show; model is truthful |

> **Implementation note (a108) — startup keeps its explicit first show.** The
> table's ideal is "startup → `apply_state()` once". As built, startup instead
> **seeds the model** (`hub_position` from the just-placed position; mode flags
> via the manager's `apply()`; `state.shown = True` for always-on-top, `False`
> for taskbar/tray) and **keeps the existing explicit `show()` + soft fade-in /
> `showMinimized()` sequence**, because the Win11 first-map flag timing + the
> macify fade are delicate and live-tuned. The win is the same: after startup
> the model agrees with reality, so EVERY later show (tray click, taskbar
> restore) funnels through `apply_state()` and they can no longer diverge.
> Only the one-time bootstrap show is bespoke; all steady-state shows are
> unified.

**Position capture on drag** is the missing wiring: `forest_controller` already
has `_on_hex_moved` (saves `window_position` on every move) — that same callback
ALSO writes `state.hub_position` (a108), **gated on the hub being visible +
not-minimised** so a programmatic minimise/hide move can't overwrite the good
position with a (0,0). After this, there is exactly one position truth and the
"snaps back to the show-time spot" bug is gone.

---

## 6. Deletions / merges (what the implementation removes)

* **Delete `_restore_descendants`** entirely. Its descendant-reveal loop is the
  same as `show_hub`'s → both become the shared `reveal_hidden_descendants()`.
* **Collapse `show_hub` / `hide_hub`** into thin wrappers:
  `show_hub()` = `state.shown=True; apply_state()`;
  `hide_hub()` = `state.shown=False; apply_state()`.
  The taskbar-vs-tray branching in `show_hub` is **deleted** (one path in
  `apply_state` handles mode).
* **`eventFilter`** stops calling `_restore_descendants`; it sets `state.shown =
  True` and calls `apply_state()` (or `show_hub()`).
* **`_last_hub_position`** is replaced by `state.hub_position` (one field); all
  reads/writes route through the model.
* **`_apply_always_on_top_flag` / `_apply_taskbar_flag`** (cell_window) are
  decoupled from visibility. `setWindowFlags()` recreates the native HWND,
  which resets the position to (0,0) and drops the hex mask. As implemented in
  a108, both helpers now **capture the position BEFORE the swap, restore it
  AFTER, and reassert chrome UNCONDITIONALLY** (not gated on `was_visible`);
  only the actual `show()` stays gated on prior visibility (we never force-show
  a window the caller meant to keep hidden). This is what makes the hub
  movable + masked from the very first show — the fix for "jumped to the
  top-left, lost its icon, wasn't mobile after loading".

  > **Implementation note — deviation from the original plan, intentional.**
  > The plan said to *remove* the construction-time `_apply_always_on_top_flag`
  > call in `CellWindow.__init__` (line ~3743). It was **kept**: with the
  > helpers now always restoring position + reasserting chrome, the
  > construction call is no longer harmful — it actually *repairs* the mask
  > that its own `setWindowFlags()` would otherwise drop, and it leaves the
  > always-on-top flag established for every normal cell (removing it risked
  > silently un-stay-on-top'ing ordinary cells, whose base flags don't carry
  > `WindowStaysOnTopHint`). Lower-risk, same outcome. The hub's *mode* flags
  > (taskbar / always-on-top per prefs) are still (re)established by the
  > manager's `apply()` at startup before the first show.

---

## 6a. Docking is PRESERVED (explicitly out of scope, untouched)

This refactor owns the **hub window's** position / visibility / mode. It does
**not** touch — and must not disturb — the docking/clustering behaviour:

* The **snap-and-dock engine** (cells snapping together, `_dock_partners`,
  `_check_undock`, master/ring formation), the **dock graph**, the
  "**drag a cell drags its docked children**" rule (a82), and `_forest_descendants`
  following the dock graph (a39) — all UNCHANGED.
* The **bloom / layout engine** (`_compute_layout`, `_start_expand/_collapse`,
  `_remembered_offsets`) — UNCHANGED. `apply_state()` never calls it.

How docking stays intact through show/hide:

* **Reveal-in-place.** Hiding then showing a descendant is `hide()`/`show()` —
  it never moves the cell, so a revealed cell reappears in exactly its docked /
  bloomed position. `apply_state()` reveals cells; it does not re-tile or
  re-dock them.
* **Cluster moves together on the one repositioning case.** The ONLY time
  `apply_state()` repositions anything is the on-screen **clamp** of the hub
  (when the saved `hub_position` is off-screen). In that case it must move the
  whole docked/bloomed cluster **rigidly** — translate the hub AND its members
  by the same delta — using the existing "master moves with its members"
  mechanism, NEVER re-slotting them. Relative (docked) positions are preserved;
  the cluster just shifts onto the screen as a unit. (Common case: the saved
  position is on-screen → no clamp → nothing moves at all.)
* The hub remains a normal master cell; user drags still move it + its docked
  children through the unchanged drag/dock code. `apply_state()` only handles
  the show/hide/restore lifecycle, not interactive movement.

## 7. Invariants (must hold after the refactor)

1. **One position store.** `state.hub_position` is the only place the hub's
   position lives; the persisted `window_position` is serialised from it.
2. **`apply_state()` is the only writer** of hub window flags / visibility /
   position. No handler calls `move()` / `show()` / `setWindowFlags()` on the hub
   directly.
3. **Showing never repositions** except an on-screen clamp. Click the icon → the
   hub appears exactly where the user left it.
4. **Flag change ⇒ chrome reassert**, unconditionally, in the same step.
5. **`apply_state()` is idempotent** and never invokes the layout engine.
6. Multi-monitor clamp + on-screen rescue are preserved (single-screen is just
   the one-monitor case).

---

## 8. Verification (live, by Ken — headless can't confirm window behaviour)

After implementation + the full unit suite (0 net-new), the manual matrix:

* Startup (each of the 8 mode combinations): hub appears at its saved position,
  rendered (mask present), **draggable immediately**, no (0,0) flash.
* Drag hub → click tray icon → hub stays where dragged (no snap-back).
* Drag hub → click taskbar entry → identical result (parity with tray).
* Toggle always-on-top off/on → hub keeps position + icon (no (0,0), no blank).
* Resolution change → cluster shifts to fit (handled by the separate rescue;
  the rigid-translate refinement is its own follow-up, tracked separately).
* Off-screen saved position (shrunk display) → clamped on-screen on show.

---

## 9. Sequencing (the implementation order this doc mandates)

Per the agreed "prototype then expand" discipline:

1. **Build the model + `apply_state()`** and the position-capture-on-drag wiring.
2. **Route ONLY tray + taskbar shows** through `apply_state()` first; verify the
   two icons behave identically (the user's headline complaint).
3. **Expand** to startup + flag-toggle + hide, deleting `_restore_descendants`
   and the `show_hub` branching, and decoupling the flag/chrome application.
4. Tests + version bump a108 + two-tree deploy; git stays held.

### Status — implemented in v0.8.0a108 (all four steps landed in one pass)

* **(1) Model + apply_state + drag-capture — DONE.** `ForestHubState` is the
  single source of truth; `apply_state()` is the one render pass;
  `forest_controller._on_hex_moved` writes `state.hub_position` on every
  interactive hub move (gated visible + not-minimised).
* **(2) Tray + taskbar unified — DONE.** Tray `on_activate` → `show_hub` →
  `apply_state`. The `eventFilter` taskbar-restore now also calls `show_hub`
  (was a bespoke `_restore_descendants`). Same code, same result.
* **(3) Startup + flags + hide + deletions — DONE.** `_restore_descendants`
  **deleted**; `show_hub`/`hide_hub` are thin model wrappers; the taskbar-vs-
  tray branching in the old `show_hub` is gone (one branch in `apply_state`).
  `_last_hub_position` / `_taskbar_on` / `_always_on_top` / `_auto_hide` /
  `_hidden_descendant_ids` collapsed into `self._state`. The flag/chrome
  helpers are decoupled (position-restore + chrome-reassert unconditional;
  construction-time call kept — see §6 note). Startup seeds the model and
  keeps its live-tuned first show — see §5 note.
* **(4) Tests + version + deploy — DONE.** 109 forest tests green (104 + 5 new
  a108: `TestFlagSwapPreservesPositionWhenHidden`,
  `TestApplyStateUnifiedShow`); full suite 0 net-new failures (10 known
  baseline). Version bumped to a108; deployed byte-identical to `D:` + `R:`;
  git HELD pending Ken's "release".

**Headless limit:** this is forest window-core code; the unit suite proves the
model/contract but cannot confirm real Win11 show/restore/drag behaviour. The
§8 manual matrix is the acceptance gate — Ken live-tests it.

### Adversarial-review hardening — v0.8.0a109 (2 real bugs fixed + coverage)

A 37-agent adversarial workflow (6 review dimensions → 3-lens refute panels →
completeness critic) reviewed the a108 diff and found **two real runtime bugs**
plus four coverage gaps. Both bugs were in the new model→apply code; both are
now fixed with regression-locking tests (forest suite 109 → **121** green; full
suite still 0 net-new).

* **[HIGH] `apply_state` hide branch was not idempotent.** It unconditionally
  cleared `hidden_descendant_ids` then re-derived it from the *currently-visible*
  descendants. A **second** hide while already hidden (two focus-left events
  >80 ms apart in auto-hide mode — the watcher stays enabled while hidden, and
  the hide's own focus churn can re-fire it) found every descendant already
  hidden, recorded nothing, and **wiped** the set the first hide captured. The
  next show then revealed **no cells** — the exact "forest comes back empty /
  cells left behind" failure this whole refactor exists to kill. **Fix:** the
  hide branch early-returns as a no-op when the hub is already hidden
  (`isMinimized()` in taskbar mode, `not isVisible()` otherwise), preserving the
  recorded set. `hide(); hide(); show() == hide(); show()`. Test:
  `TestA108HideIdempotent`.
* **[MEDIUM] Clamp-on-show re-entered `_on_hex_moved` and overwrote the stored
  position.** `apply_state`'s show branch moves the hub to
  `clamp(hub_position)`; `CellWindow.moveEvent` emits `hexagonMoved`
  synchronously on that programmatic move; `_on_hex_moved` (visible +
  not-minimised) then wrote the **clamped** value back into `state.hub_position`
  and persisted it. So showing a hub whose stored position was off every screen
  (monitor unplugged, resolution shrank) silently **destroyed the user's real
  position** — violating invariant #1 (position written only by user drag +
  load). **Fix:** a re-entrancy flag `_applying_state`, held True for the whole
  render pass (finally-reset), makes `_on_hex_moved` ignore apply_state's own
  moves; only genuine user drags update the model. The window is still clamped
  on-screen for reachability; the model keeps the off-screen intent. Test:
  `TestA108DragCaptureGuard.test_offscreen_show_preserves_real_stored_position`.
* **Coverage gaps filled (code was correct, but the linchpins were untested —
  a future regression of the a108 fix would have shipped green):** the
  drag-capture guard (`TestA108DragCaptureGuard`), the eventFilter taskbar↔tray
  parity (`TestA108EventFilterTaskbarRestore`), the `apply(prefs)` flag-toggle
  transition (`TestA108ApplyTransition`), and the hide branch with real
  descendants + `hide_descendants_only` (`TestA108HideRecordsOnlyVisible`).

The review's 3 rejected claims were correctly killed — notably one confirmed the
*hide* path's `isMinimized` guard already prevents the analogous corruption, so
only the *show* clamp needed the `_applying_state` fix. Ken live-tests a109.
