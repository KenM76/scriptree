---
date: 2026-05-07 (late)
persona: end-user (the user reported master double-click misroute + UX requests)
feature: master double-click semantics, _members iteration fix, right-click menu sub-folders, agent definition
build: V3 working tree (post-v0.2.2, on track for v0.2.3)
verdict: SHIP after manual smoke
---

# Beta report — master double-click + menu reorg

## What the user reported / requested

> A double left click should bring up a menu with each of the
> attached cell's menus each in its own sub-folder on the menu, and
> double-right click should bring them up in the full editor in the
> same sub-folder style — right now it is showing up as blank, but
> that may have to do that there is actually no file for the current
> ring as it was just created, either way, scriptreering file or
> not, it needs to be able to open this way.

> also with the right click menu on the cells and rings they should
> be logically organized with sub folders too.

> can you back yourself as an agent in the developer v3 folder too?
> You're doing great and I don't want to lose your natural
> capabilities that you've exhibited in this entire chat.

## Findings

### Issue 1 — "double-right shows blank editor" (FIXED, root cause was iteration bug)

**Root cause:** ``HexagonWindow._members`` is a
``dict[member_id, QPoint]``, but ``merged_tree.build_merged_tree_for_master``
and ``tree_popup.show_tree_popup_for`` were both iterating that dict
directly (``for m in master._members:``).  In Python that yields
**keys** (string ids), not the values.  So when each iteration did
``getattr(m, "_catalog_path", None)`` on a string, it always got
``None`` — paths list ended up empty, ``build_merged_tree``
raised, ``show_composite_for`` caught the exception and fell back
to ``launch_editor_blank`` — exactly the "blank editor" the user saw.

**Fix:** both call sites now iterate ``_members.keys()``, look each
id up via ``HexagonRegistry.instance().get(id)`` to get the actual
``HexagonWindow``, and read ``_catalog_path`` off that.  Both
locations also support unbound members (no catalog) — the popup
shows a disabled "(no catalog bound)" sub-menu for each, and the
merged-tree builder produces a placeholder ``.scriptreetree`` so
V1's editor opens with a clear "no catalogs bound — right-click each
cell to load one" hint instead of blank.  Per the user's spec:
"either way, scriptreering file or not, it needs to be able to open
this way."

### Issue 2 — master double-LEFT was the editor; user wants a popup (FIXED)

The previous behaviour: master double-LEFT → ``show_tree_for(mode="lock-open")``
→ V1 full editor.  The user wants double-LEFT to be the popup-with-
sub-folders flavour.

**Fix:** `click("double")` for master cells now calls
``show_tree_popup_for(self)`` directly (the in-process QMenu builder
that was already master-aware after the iteration fix).  Standalone
double-LEFT is unchanged (still opens the V1 editor with
``-standalone`` mode lock-open).

### Issue 3 — master double-RIGHT routing went through the wrong helper (FIXED)

Previously double-RIGHT called ``show_main_window_for`` →
``show_tree_for(mode="lock-open")``.  For masters, that helper reads
``hex_win._catalog_path`` — but masters don't have one (catalogs are
on members).  ``catalog is None`` → ``launch_editor_blank()``.

**Fix:** double-RIGHT now calls ``show_composite_for(self)`` which
correctly handles the master case via
``merged_tree.build_merged_tree_for_master``.  Standalone
double-RIGHT routes through the same helper which falls back to the
standalone editor path.  Net effect: master double-RIGHT now opens
V1's editor with the merged tree (sub-folder per member).

### Issue 4 — right-click menu organization (FEATURE)

User wanted "logically organized with sub folders".  Refactored the
context menu from a flat list to:

```
├── ScripTree[Tree]: <name>          (read-only label)
├── ─────
├── Catalog ▶
│   ├── Load ScripTree…
│   ├── Load ScripTreeTree…
│   ├── Open recent ▶
│   ├── Save catalog as…
│   └── Clear loaded file
├── Ring ▶
│   ├── Save (group) as ring…
│   ├── Load ring…
│   └── Auto-load on startup ▶
│       ├── Disabled
│       ├── For current user only
│       └── For all users (requires admin)
├── Cell ▶
│   ├── Spawn another hexagon
│   └── Disband group / Leave group   (conditional)
├── ─────
├── About <brand>
├── Settings…
├── Preferences…
├── ─────
├── Close this cell / Close ring / Close all related   (role-aware, top-level)
└── Exit all
```

Close + Exit stay at the top level for fast access (single click
through the bottom of the menu); everything else is grouped.

### Issue 5 — capture working style as a Claude Code agent (FEATURE)

Wrote ``D:\Dev\ScripTree3\.claude\agents\scriptree-engineer.md`` —
an agent definition that captures the single-session approach,
project geography, the SolidWorks privacy rule, the
backup-before-touch / TodoWrite / smoke-compile / diagnostics-first
working style, the subprocess + Qt gotchas learned the hard way,
beta-report format, and the hard "do not"s from the user's
direction.  Future sessions in this project can adopt the same
style by reading that file.

## Tests

* ``tests/test_merged_tree.py`` — replaced
  ``test_build_merged_tree_for_master_no_members_raises`` (obsolete
  contract) with two new tests
  (``..._returns_placeholder``,
  ``..._unbound_member_returns_placeholder``) verifying the new
  "always produce a tree, never raise" contract.
* ``tests/test_tree_popup.py`` — added
  ``test_master_popup_iterates_members_via_registry`` — proves the
  popup builder calls ``HexagonRegistry.get(member_id)`` (not just
  iterates dict values directly).

**750 tests passing.**  No regressions in V1's 668.

## Diagnostics added

Already comprehensive from v0.2.1 / v0.2.2.  This pass added:

* ``[merged_tree]`` log line when a placeholder is materialised
  (so we can tell from a log that a ring was opened with no member
  catalogs).
* ``[HexagonWindow] click(double) master ... — showing master popup
  with member sub-folders`` log line distinguishing the new
  master-double-LEFT path.

## Manual smoke (handed to user)

1. Close any running ScripTreeRing first.
2. ``run_scriptreering.bat`` → cell A.
3. ``run_scriptreering.bat`` again → cell B (single-instance handoff).
4. Right-click cell A → menu shows sub-folders ``Catalog``, ``Ring``,
   ``Cell``, plus top-level About/Settings/Preferences and the
   role-aware close actions.
5. Cell A → Catalog ▶ Load ScripTreeTree → SolidWorks toolkit.
6. Drag cell B near cell A → master spawns (the dock fix from v0.2.2
   is what makes this work).
7. **Double-left-click master** → popup menu with each member's tree
   as a sub-folder (cell A's tools nested under their tree's display
   name; cell B as "Cell <id> (no catalog bound)" since it's empty).
8. **Double-right-click master** → V1 editor opens with the merged
   tree.  Should NOT be blank — even with no .scriptreering saved,
   either real member catalogs or a placeholder folder appears.
9. Bind a catalog to cell B as well, repeat step 8 → both members
   should appear as top-level folders in the merged editor view.

## What's still TODO (for future sessions)

* The default-config checkbox added in v0.2.2 doesn't yet have UI
  visibility for *tree-level* default (the ``.scriptreetree`` whose
  config sidecar is ``<tree>.scriptreetree.treeconfigs.json``).  Per
  user direction, treeconfigs files were created by us and can be
  fixed later — flag for next session.
* Smoke driver (``tests/smoke_beta_sweep.py``) couldn't reliably
  spawn + drive real ScripTreeRing processes through Bash background
  due to stdout buffering.  Manual smoke remains the primary
  end-to-end verification.
