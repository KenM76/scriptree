---
topic: max_effort_review_fix_batch_of_the_menu_overhaul
date: 2026-07-02
status: pattern + gotchas
related: [forest_visibility_model_apply_refactor_a108, release_hygiene_two_remotes_gitignore_untrack_a116]
version: v0.8.0a121
---
# a121 — the 44-finding review-fix batch of the a117-a120 menu overhaul

A max-effort multi-agent /code-review (10 finder angles → dedup → 1-vote
verify → gap sweep; 56 agents) of the a117-a120 diff surfaced 44 verified
findings (1 refuted). Ken: "release current version to git then fix
everything." The findings and their fixes are itemised in the a121 commit
(when released) and the held-release memory; this lesson records the
REUSABLE patterns.

## Findings worth generalising

1. **Quick-save features need three guards, not one.** The a119
   "Save layout" (remembered-path quick-save) shipped with the happy path
   only. The review found THREE data-loss routes: (a) saving while the
   forest is COLLAPSED captures ~(0,0) offsets (the collapsed hub is
   exactly the thing you right-click) — guard on `_collapse_state`;
   (b) opening a layout that matched NOTHING still armed the quick-save
   target → later one-click save overwrites an unrelated file — arm the
   remembered path only after `applied > 0`; (c) switching forests kept
   the old target → forest B clobbers forest A's file — clear the path in
   `open()`. RULE: for any "quick save to remembered destination", audit
   every path that SETS the destination and every state where a capture
   would be garbage.

2. **Silent failure after an explicit user gesture is a bug.** The layout
   writer log-only bailed on "nothing positionable" and on exceptions —
   right after the user picked a filename in a dialog. Its older ring twin
   (`_write_ring_to_path`) already showed `QMessageBox.warning`. When a
   twin function exists, diff their failure paths.

3. **Menu hooks need a failure story.** a120 moved the hub's only
   Settings/Preferences/About into the controller hook; a hook exception
   (swallowed by the standard try/except-log) left the hub with
   Open/New/Exit only. FIX pattern: `hook_ok` flag + cell-native fallback
   items. Related: the `except TypeError: hook(menu)` arity-sniff re-ran
   the WHOLE builder when a TypeError escaped from inside it → duplicated
   menu. Never use exception-type sniffing for signature negotiation when
   you own both sides — just call the current signature.

4. **`getattr(obj, "name", None)` hides dead features.** The per-cell
   Uninstall read `cell.catalog_path`; CellWindow only ever stored
   `_catalog_path`, so the block was unreachable for ~95 versions and no
   test noticed (the getattr default made it silent). Grep the attribute
   you read actually EXISTS on the object you read it from.

5. **Trust-but-resolve stored ids.** The a118 `is_plain_member` gate
   trusted `_group_master_id` raw; a stale id (master died in exceptional
   teardown) would permanently hide the orphan cell's rebind/save menus.
   Resolve ids in the registry at decision time (the adjacent
   forest-member check already did — copy the in-file idiom).

6. **Structural test updates must be swept, not spot-fixed.** a120
   dissolved the "Forest" wrapper; one test was updated, but
   `carry_icons` still did `parent.actions()[0].menu()` — it silently
   degraded to checking only File's 8 actions and PASSED. After a menu/
   tree restructure, grep the test suite for every positional accessor
   (`actions()[0]`, `topLevelItem(0)`, hardcoded titles).

7. **Every test that starts a ForestController needs the isolation
   fixture** (`default_preferences_path` + `default_autoload_path`
   monkeypatch + `set_autosave_enabled(False)`). The new a119 module
   skipped it and read Ken's LIVE %APPDATA% prefs — with his tray-only
   visibility flags it would spawn a real tray icon mid-suite.

8. **Duplication the ORIGINAL fix existed to prevent can come back one
   version later.** a117 extracted `_show_about` to avoid duplicating the
   About HTML; a120's two-tab About re-inlined it in the controller. Fix:
   move the builder to a third, dependency-light home
   (`branding_loader.about_app_html`) that both surfaces import.

## Test gotchas (new this batch)

* **Never use fake drive letters in tests.** `Path("Z:/nowhere").resolve()`
  raised `OSError` (WinError 1272) because Z: is a REAL blocked network
  share on Ken's machine. Use `tmp_path / "ghost" / ...` for non-existent
  paths.
* Module-level `QMessageBox.warning = ...` patches in test files are
  redundant (conftest's `_silence_qt_modals` is session-wide) and can
  fight it — don't add them.

## Process pattern that worked

Review → release the reviewed version AS-IS (scoped commit) → fix batch as
the next version. The scoped commit matters: the main tree simultaneously
held ANOTHER session's uncommitted work (lib trim, runtime shim, its rags
lessons) — `git add -A` would have blind-published it. Stage the explicit
fileset, gate on `git diff --cached --name-status` count, and leave
foreign work for its owner.
