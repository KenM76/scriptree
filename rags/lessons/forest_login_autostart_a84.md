---
topic: forest_login_autostart
date: 2026-06-25
status: feature-landed-pending-release
version: 0.8.0a84
related: [remembered_cell_layout_feature, version_lives_in_two_files, single_instance_handoff_qlocalserver, save_as_rebinds_path]
---
# Forest login-autostart (a84) — forest gains the tree-ring's "Auto-load on startup"

User ask: "Forest needs the same auto-load on startup options as we have for the
treering." Confirmed scope: **launch ScripTree on Windows login** (a Run-key),
**single configured forest** (not a list), three states Disabled / current user /
all-users — mirroring the ring's "Auto-load on startup" submenu.

## The one architectural constraint — ONE shared Run-key per scope

`register_autostart(scope, cmd, brand)` (ring_io.py) writes a SINGLE Run-key value
named after the brand (`HKCU\…\Run\ScripTree`, `HKLM\…\Run\ScripTree`). The ring
already owns that value (`… ring_main --autoload-rings`). ScripTree is
single-instance (PrimaryServer), so the forest must NOT get its own second Run-key
value (two values → two login launches → handoff race). Instead both features share
the one value, carrying the **combined** flags.

Design: a single chokepoint **`ring_io.recompute_autostart(scope)`** reads
`rings = bool(list_autoload_rings(scope))` + `forest = _forest_autostart_on(scope)`
and writes the unified command via `_build_autostart_cmd_combined(forest, rings)`
(`--forest` first, then `--autoload-rings`; `forest=False,rings=True` is
byte-identical to the historic `_build_autostart_cmd()` so existing ring
registrations never get rewritten). `add_autoload_ring`/`remove_autoload_ring` were
rerouted through `recompute_autostart` (remove now recomputes unconditionally — it
keeps a `--forest`-only key alive when rings empty but forest is on, instead of
unregistering). `--forest` alone is sufficient at login: forest-mode dispatch
(ring_main.py) → `ForestController.start()` loads the configured default; enabling
autostart points `default_forest_path` at the saved forest.

State lives in `ForestPreferences.autostart_scope ∈ {"off","user","system"}`
(forest_preferences.json). Helpers: `set_forest_autostart(scope, branding,
forest_path)` / `disable_forest_autostart(branding)` (forest_io.py). UI: a 3-state
submenu in `forest_controller._populate_forest_menu` + handler
`_on_forest_autostart_set`; a thin combo in `ForestSettingsDialog`. System scope
goes through a UAC-elevated child (`elevate_for_forest_autostart_*` →
`--register-forest-autostart-{system,user}` / `--unregister-forest-autostart-system`
early-flag handlers in `_handle_early_flags`, which write prefs + recompute and exit
before any GUI).

## THE recurring gotcha — every prefs-copy constructor must carry the new field

Adding a field to `ForestPreferences` is NOT done until EVERY site that *rebuilds*
the dataclass copies it. Missing one silently resets the field to its default
("off") whenever that path runs. There are **six** such sites; the plan caught five,
adversarial review caught the sixth:
1. `forest_io.normalised()` repair constructor.
2. `forest_io.load_preferences`.
3. `forest_controller.get_preferences` (copy-out).
4. `forest_controller.update_preferences` (cache copy).
5. `forest_dialogs.ForestSettingsDialog._save` (rebuild-from-widgets).
6. **`forest_controller._on_visibility_toggle`** ← the miss. A visibility toggle
   rebuilt prefs without `autostart_scope` → persisted "off" while the Run-key still
   carried `--forest` (UI says Disabled but it still autostarts, no cleanup path).
   `update_preferences` doesn't recompute the Run-key, so disk and registry desync.

Lesson: when adding a `ForestPreferences` field, `grep 'ForestPreferences('` across
`scriptree/` and audit each — bare `ForestPreferences()` defaults are fine, but every
constructor that copies an *existing* prefs must pass the new field. (Same class as
`version_lives_in_two_files`: a value duplicated across N sites needs all N updated.)

## Elevation/admin matrix gotchas (found by adversarial review of the real tree)

- **`disable_forest_autostart` must recompute ONLY the previously-active scope**, not
  both. Recomputing `"system"` calls `unregister_autostart("system")`, whose admin
  check raises `PermissionError` BEFORE the empty-key no-op — so an unelevated
  `user → off` disable (a routine, admin-free op) crashed with a scary dialog and
  left the menu stuck. Single-forest mutual exclusion guarantees at most one scope's
  Run-key ever carried `--forest`, so clearing just `old_scope` is correct AND
  admin-safe. (system→off while non-admin is routed through the elevated child, so it
  reaches `disable` as old_scope="system" only when already admin.)
- **The `runas` elevate helpers must return success (`ret > 32`), and the caller must
  flip the cached scope ONLY on True.** `ShellExecuteW(..., "runas", ...)` returns
  `SE_ERR_ACCESSDENIED (5) ≤ 32` when the user CANCELS the UAC prompt. The first cut
  swallowed that (returned void) and the controller's `_optimistic_autostart_flip`
  ran unconditionally → the menu claimed a scope nothing ever wrote (self-heals only
  on relaunch; for system→user-cancel it lies in both directions — stale HKLM kept,
  HKCU never added). Fix: helpers `return ret > 32`; controller `if elevate(...):
  flip`.

The optimistic flip (eventual consistency) is the right model for "parent can't read
the elevated child's result synchronously" — but it must (a) only fire on a real
launch, and (b) mirror `default_forest_path`/`fallback_to_default` so a same-session
Save doesn't clobber what the child wrote (finding #2 of the first review pass:
the dialog's seeded Launch-defaults widgets also had to be refreshed after the combo
live-applied, or `_save` wrote stale values back).

## Adversarial-review process note

The first 3-lens workflow had ONE lens (elevation-admin) silently read the wrong
tree — the agent's CWD is the harness **worktree** (a stale a82 snapshot lacking the
a84 symbols), and despite absolute-path instructions it grepped relative and found
nothing. The synthesis flagged it as "no claim to triage." A re-run with an explicit
"confirm `recompute_autostart` exists in `D:\Dev\ScripTree\…` or STOP — do NOT read
`.claude\worktrees\`" guard found the 2 real elevation defects. Lesson: when
dispatching review agents from a worktree session, pin them to the main tree path AND
give a self-check that fails loudly if they're on the wrong tree.

## Verification

`tests/test_forest_autostart.py` — 24 tests: T1 unified-command truth table +
byte-equality, T2 autostart_scope round-trip/legacy/clamp/normalised, T3 recompute
4-combo truth table, T4 set/disable (incl. "disable recomputes only old scope" +
"disable from off recomputes nothing"), T5 ring-regression guard, plus 4 finding
guards (visibility-toggle preserves scope; dialog combo enable+save keeps path;
UAC-cancel doesn't flip; UAC-accept flips; user→off non-admin doesn't raise). Full
suite 2409 passed (only the ~9 known-unrelated pre-existing failures). Deployed to
D: + R: at a84; git/GitHub release HELD pending user testing.
