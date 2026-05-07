---
date: 2026-05-07 (afternoon)
persona: end-user (the user reported follow-up issues + two UX requests)
feature: cell-shell second-pass UX polish
build: V3 working tree (post-v0.2.1, on track for v0.2.2)
verdict: SHIP after manual smoke
---

# Beta report — cell shell second pass

## What the user reported

> single clicking doesn't bring up standalone mode but instead brought
> up the full editor like it does with the double click. Also when I
> spawned a new cell they didn't snap and dock together with a tree
> ring.

Plus two UX requests:

> Right-click quit should be different. There should be an option to
> close cell, exit all, and for rings, close ring (undocks all) and
> close all related, or exit all.

> We may need to add a check box to the editor for the configs to set
> a default. There should always be a default configuration, or
> otherwise it just defaults to the last one used.

## Findings (in order of investigation)

### Issue 1 — single-click brings up the full editor (FIXED)

**Root cause:** ``v1_launcher.launch_tool`` was running V1's CLI as
``python run_scriptree.py <leaf>`` with no ``-standalone`` flag.  V1's
default behaviour when given a ``.scriptree`` file with no
``-standalone`` is to open the **full editor** (MainWindow), not the
standalone runner.  Cell-shell users single-clicked a tool, V1 opened
its full editor, and the user reasonably said "this is what double-click
gives me — single click is broken".

**Fix:** `launch_tool` now appends ``-standalone`` to argv every time:

    python run_scriptree.py <leaf>.scriptree -standalone [-configuration <name>]

**Test:** `test_launch_tool_includes_standalone_flag` plus the path
assertion in `test_launch_tool_passes_path_to_subprocess`.

### Issue 2 — spawned cells don't snap-dock (FIXED)

**Root cause (5 separate stale imports):** When V3 renamed V2's
`apps/shell/main.py` to `scriptree/shell/ring_main.py`, five
references inside the ported files were missed:

* `cell_window.py:1649`  `_get_snap_engine`  (drag-start path)
* `cell_window.py:1700`  `_get_snap_engine`  (mouseRelease — drag-end!)
* `cell_window.py:2079`  `_get_snap_engine`  (master-drag translate)
* `cell_window.py:_spawn_another` `_wire_hex_to_snap` (already fixed in v0.2.1)
* `ring_io.py:392, 446`     `_on_snap_preview` (autoload path)

Every one of these was wrapped in `except Exception: pass` so the
import failure was silently swallowed.  In particular line 1700 in
`mouseReleaseEvent` meant **every drag-release skipped notifying the
snap engine** — no snap commit, no master spawn.

**Fix:** swept all `from scriptree.shell.main import` references to
`from scriptree.shell.ring_main import`.

**Test:** existing `test_v1_launcher.py` covers the launch path; the
snap path is verified via the manual smoke (next section).

### Issue 3 — right-click "Quit" was a single hammer (FEATURE)

User wanted role-aware close/exit options.  Implemented:

* **Standalone cell** → "Close this cell" + "Exit all"
* **Master / ring cell** → "Close ring (undock all members)" +
  "Close all related (master + members)" + "Exit all"

**New methods on CellWindow:**

* `_close_ring_undock_all()` — destroys the master, members revert
  to standalones (keep their position + catalog).
* `_close_all_related()` — closes master + every member; quits if the
  desktop becomes empty.
* `_exit_all()` — closes every cell in the registry, quits.

**Tests:** `tests/test_close_menu_actions.py` (8 tests) — covers
standalone close, multi-cell close-this, exit-all, ring undock with
synthetic members, close-all-related with bystander cells, and the
fall-through paths when ring-only handlers are accidentally called
on standalone cells.

### Issue 4 — default configuration (FEATURE)

User asked for a "Default" checkbox per configuration.  Per the spec:

> there should always be a default configuration, or otherwise it just
> defaults to the last one used.

**Implementation:**

* `ConfigurationSet.default_name: str = ""` — per-set pointer.  Empty
  means "no explicit default; fall back to active".
* `ConfigurationSet.default_config()` — resolution helper.  Returns
  the named default if it resolves, else falls back to
  `active_config()`.
* `configs_to_dict` / `configs_from_dict` round-trip the field.
  Empty default_name is omitted from the JSON so legacy sidecars
  stay byte-identical.  Invalid (renamed/deleted) default names
  are cleared at load time.
* `StandaloneWindow.from_tool` calls `default_config()` instead of
  `active_config()` when no `-configuration` CLI arg is supplied.
* Tool-runner configurations bar — new "Default" checkbox next to
  the configuration combo box.  `_sync_cfg_default_check()` keeps
  it in sync when the user changes the combo selection;
  `_on_cfg_default_toggled` writes the change and saves the sidecar.
* Per user direction: "Don't worry about breaking compatibility with
  scriptree and scriptreetree files. They were all made by you and
  can be fixed by you later."  We didn't break anything — sidecars
  predating the field load fine — but the option to break them was
  there if needed.

**Tests:** `tests/test_default_config.py` (14 tests) — resolution
order, round-trip, legacy sidecar load, invalid-name cleanup,
end-to-end save/load, editor checkbox presence + sync + toggle +
write-through, and StandaloneWindow integration.

## Tests with auto-dismiss

Per the user's standing rule about expected error dialogs in tests:
both `test_default_config.py` and `test_close_menu_actions.py` patch
`QMessageBox.warning/information/critical/question` at module load to
return Ok/Yes immediately, so any stray dialog doesn't block the suite.

## Test summary

* 748 tests passing (725 prior + 14 default_config + 8 close menu + 1
  new launch-tool standalone assertion).
* No regressions in V1's 668 tests.
* `tests/smoke_beta_sweep.py` available as a non-pytest end-to-end
  driver for the single-instance handoff flow.

## Diagnostics added

Already present from v0.2.1.  This pass added explicit logging in:

* The role-aware close/exit handlers (`_close_ring_undock_all`,
  `_close_all_related`, `_exit_all`) — count of members, count of
  related cells, the per-cell close outcomes.
* `_on_cfg_default_toggled` — short status message echoed in the
  runner status bar so the user gets feedback that the default
  changed.

All log lines are tagged so a `tail -f` filter can isolate them.

## Manual smoke (handed to user)

1. **Close any running ScripTreeRing first.**  The fix targets the
   single-instance primary; with a stale primary running, your bat
   invocation will hand off to it instead of testing the new code.
2. `run_scriptreering.bat` → cell appears.
3. Right-click → Load ScripTreeTree → pick the SolidWorks toolkit at
   `R:\\ScripTreeApps\\SolidWorks_toolkit.scriptreetree`.
4. **Single-left-click** → menu pops up.  Click "DXF Export" →
   **standalone runner** (NOT the full editor) appears.
5. **Double-left-click** cell → V1 full editor opens with the catalog
   loaded.
6. `run_scriptreering.bat` a second time → no new isolated process;
   a sibling cell appears next to the existing one.
7. Drag the sibling close to the original → ring master appears.
8. Right-click the master cell → menu shows
   "Close ring (undock all members)", "Close all related",
   "Exit all" (NOT just "Quit").
9. In the editor (run_scriptree.bat), open a tool with multiple
   configurations.  Toggle the new "Default" checkbox on one of
   them.  Reopen the tool standalone (`run_scriptree.bat <tool>.scriptree
   -standalone`) — the default config should be the active one.

If any step misbehaves, the relevant log lines will show up in
stderr.  The diagnostics from v0.2.1 plus the new ones from this
pass cover the full click → spawn → launch → close lifecycle.
