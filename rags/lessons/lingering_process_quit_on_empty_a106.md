# Lingering ScripTree process after exit — closeEvent never quit the last window (a106)

**Tag:** [v3-architecture] [shutdown] [single-instance] [process-lifecycle]
**Version:** v0.8.0a106
**Files:** `scriptree/shell/cell_window.py` (`closeEvent`, new `_quit_if_app_empty`,
`_close_this` simplified). **Tests:** `tests/test_close_menu_actions.py` (+3:
closeEvent quits-on-last / no-quit-when-others / quits-on-last-master).

## Symptom (and why it masked the REAL bug for hours)

After "exiting" the forest, a ScripTree `pythonw.exe` kept **lingering** in Task
Manager — and that lingering process is what made the a98→a105 `_groups`
circular-ref fixes appear not to work: a stale primary kept re-writing the file
AND kept owning the single-instance named pipe, so every new launch **handed off
to the old process** instead of starting the freshly-deployed code. "I deployed a
fix" was silently untrue. Killing the processes in Task Manager is what finally
let a new version actually run. (See
[[groups_circular_ref_unprunable_residue_a104]] for the data side.)

## Root cause

The app sets `app.setQuitOnLastWindowClosed(False)` (ring_main.py) — load-bearing,
because cells are frameless windows and a transient cell-close must not kill the
app while siblings live. The consequence: **Qt never auto-quits; SOMETHING must
call `QApplication.quit()` explicitly.** The explicit quit existed in `_exit_all`,
`_close_all_related`, and the taskbar-dismiss — but **`CellWindow.closeEvent` (the
window-frame [X]) only unregistered the cell and called `super().closeEvent`; it
never quit.** So closing the forest hub (or the last cell) via [X] left the
process **alive headless**. `_close_this` had a quit, but its `is_last` check was
`len(standalones) <= 1 and self in standalones` — which (a) MISSED a last *master*
(the forest hub isn't a standalone) and (b) PREMATURELY quit when the last
standalone closed while a master hub was still open.

## Fix

A single, role-agnostic rule at the close chokepoint: `closeEvent` ends with
`self._quit_if_app_empty()`, which calls `QApplication.quit()` iff the
`CellRegistry` has **no standalones AND no masters** left (after this cell's
`unregister`). `_close_this` drops its buggy `is_last` and just `self.close()`s —
`closeEvent` decides. This covers the [X] button, `_close_this`, and the loop
inside `_exit_all` uniformly.

**Why it's safe against a premature quit** (the big risk for a quit-on-empty):
auto-hide / tray uses `hide()` / `showMinimized()` (forest_visibility.py), NOT
`close()`, so hidden cells stay **registered** → registry non-empty → a
tucked-away forest is never quit. Only a genuinely empty registry quits. The
double-quit (explicit in `_exit_all` + closeEvent on the final close) is harmless
— `QApplication.quit()` is idempotent (tests assert `called`, not `called_once`).

## Reusable takeaways

1. **`setQuitOnLastWindowClosed(False)` means EVERY full-close path must quit
   explicitly — including `closeEvent`.** Audit all of them; a single un-quit path
   (here, the [X] button) leaves a headless process. Centralise the decision in
   one `_quit_if_app_empty` rather than scattering `is_last` heuristics.
2. **A lingering single-instance primary silently defeats deploys.** When "my
   fix didn't take effect" on a long-running, single-instance app, suspect a
   stale resident process intercepting handoffs BEFORE suspecting the code. A
   clean process exit on last-window-close is what makes redeploys real.
3. **Quit-on-empty must key on REGISTRATION, not visibility.** Hidden/tray cells
   are still "the app" — quit only when nothing is registered, and confirm hide
   paths use `hide()`, not `close()`.
4. **`is_last` by one role is a trap.** The registry has standalones AND masters;
   "last window" means BOTH are empty. A standalones-only check both over- and
   under-fires.
5. Pairs with the data-side lesson
   [[groups_circular_ref_unprunable_residue_a104]] — the lingering process was the
   *delivery mechanism* that kept the circular-ref corruption alive across deploys.
