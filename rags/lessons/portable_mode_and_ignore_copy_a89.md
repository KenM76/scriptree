# Portable mode + "Ignore this copy" (a89): the chokepoint set, the gaps an adversarial review caught, and the Ignore/restore design

**Tag:** [v3-architecture] / [pyside6]
**Version:** v0.8.0a89
**Files:** `scriptree/core/portable.py` (NEW); `scriptree/core/app_install.py`
(`default_personal_root`); `scriptree/shell/forest_io.py`
(`default_autoload_path`, `shared_autoload_path`); `scriptree/shell/ring_io.py`
(`_appdata_dir`/`_programdata_dir`/`_default_rings_dir`);
`scriptree/shell/ring_main.py` (QSettings redirect); `scriptree/ui/settings_dialog.py`
(toggle); `scriptree/shell/forest_controller.py` (`ignore_copy`/`forget_excluded`);
`scriptree/shell/tree_popup.py` (Ignore button); `scriptree/shell/forest_dialogs.py`
(`ExcludedItemsDialog` → tree).
**Tests:** `tests/test_portable_a89.py` (10), `tests/test_ignore_copy_a89.py` (7).

---

## ITEM 3 — "Truly portable" mode

### The problem
ScripTree state lives in THREE stores, only one of which travels with a
folder-copy: install-local (`scriptree.ini`, `user_configs/`, `permissions/`,
the shared `ScripTreeApps` root), per-user **appdata** (the
`.scriptreeforest`, `forest_preferences.json`, autoload-rings), and — on
Windows — the **registry** (recent files, dock layouts, menu appearance, all
via bare `QSettings()`). So a USB/folder copy silently loses the forest, the UI
settings, and any *personal* drop-installed app.

### The mechanism
A new `scriptree/core/portable.py` with `is_portable()` (a `portable` sentinel
file in the install root OR `SCRIPTREE_PORTABLE` env; **env wins over the
sentinel** — truthy on, falsey off — so a dev can force non-portable inside a
portable tree), `portable_data_root()` = `<install>/_portable_data`,
`portable_apps_root()` = `<install>/ScripTreeApps`, and `set_portable(bool)`
(writes/removes the sentinel; the Settings toggle calls it).

### The CHOKEPOINT SET (memorise this — missing one leaks state off-tree)
Redirecting **`default_personal_root()` cascades for free** to `_groups`
(`forest_controller` derives it) AND the forest's 3rd auto-discover root
(`forest_io._default_roots`) — they both derive from it. The rest must each be
patched:
1. `app_install.default_personal_root` → `portable_apps_root()`
2. `forest_io.default_autoload_path` → `portable_data_root()` (and
   `default_preferences_path` follows, it's `.parent`-derived)
3. **`forest_io.shared_autoload_path`** → `portable_data_root()` — the one the
   first pass MISSED (see gaps)
4. `ring_io._appdata_dir` → `portable_data_root()`,
   `_programdata_dir` → `portable_data_root()/"system"`,
   `_default_rings_dir` → `portable_data_root()/"rings"`
5. `ring_main` startup (right after `setOrganizationName`): if portable,
   `QSettings.setDefaultFormat(IniFormat)` + `setPath(IniFormat, UserScope,
   portable_data_root())`. **Must run before the first bare `QSettings()`** (the
   cell shell builds them lazily, well after this point). `app_settings.get_settings()`
   uses an explicit `QSettings(path, IniFormat)` and is untouched.

### Five gaps an adversarial review (3 agents) caught after the first pass — ALL real
1. **`shared_autoload_path` left un-redirected (BUG).** Every other store was
   redirected, but the unsaved-forest "Save to **shared** location" exit button
   (`forest_controller.flush_if_dirty`) wrote the whole forest to
   `%ProgramData%` — straight out of the portable tree. *Lesson: when you
   redirect a "personal" path, grep for its SHARED/sibling twin and redirect it
   too; a portable install is single-scope so personal == shared.*
2. **user/system autoload scopes collapsed (RISK).** `_appdata_dir` and
   `_programdata_dir` both returned `portable_data_root()` **without the
   brand subdir** the non-portable branches add, so `autoload_rings.json`
   user-scope == system-scope → a user ring was misread as a system ring →
   `recompute_autostart("system")` attempted an HKLM write (PermissionError
   unless admin). *Fix: give system scope a distinct `/system` subdir.*
3. **A stale `install.personal_root` override defeats portability (RISK).** The
   override is read from `scriptree.ini`, which TRAVELS with a folder-copy. A
   machine-specific override set on the source machine then points off-tree on
   the destination, overriding the portable root (cascading to `_groups` + a
   discover root). *Fix: in portable mode, honour an `install.*` override ONLY
   when it resolves INSIDE `install_anchor()`; otherwise portable wins.*
4. **Settings toggle claimed success on a read-only medium (BUG).**
   `set_portable(True)` returns `None` when the sentinel write raises OSError
   (read-only USB) — the handler ignored the return and popped "enabled,
   restart". *Fix: capture the return; warn + revert the checkbox on
   `want and res is None`.*
5. **Claim-bearing doc went stale (BUG).** `docs/features.md` asserted "Fully
   portable — zero registry" as an UNCONDITIONAL property, but post-a89 that's
   true only when portable mode is *opt-in* enabled. *Lesson: a new opt-in
   feature can FALSIFY an existing always-true marketing claim — grep the docs
   for the claim and qualify it (the global claim-bearing-copy rule).*

### a90 — switch without data loss (state migration)
a89 shipped the redirect but NOT migration, so a toggle made the target mode
boot EMPTY (the data was safe in the other location, but it *looked* like a
reset). a90 adds `scriptree/shell/portable_migrate.py::migrate_for_toggle`
(called by the Settings toggle) which copies the CURRENT mode's forest,
preferences, autoload-rings config + saved-rings dir, and the recent/dock/menu
**QSettings** into the target mode's locations. The key trick is
**snapshot-flip-snapshot**: resolve the state paths via the resolvers BEFORE
flipping the sentinel (current mode), `set_portable(to_portable)`, resolve again
AFTER (target mode), copy 1→2 — reusing the resolvers' own logic for both modes
with no duplicated path maths. The UI-settings copy is a key-by-key
`QSettings`→`QSettings` between a **NativeFormat (registry)** store and an
**IniFormat** store (`<_portable_data>/<brand>/<brand>.ini`), so it works in both
directions and cross-platform. **Personal apps are deliberately NOT copied** —
the forest stores ABSOLUTE tool paths, so apps keep launching on the same
machine after the switch, and the personal↔shared merge is ambiguous on the way
back (the shared root already holds the bundled apps); for a cross-machine
portable USB, keep apps in the shared `ScripTreeApps` tree (which always
travels). All copies are best-effort + logged so a locked file can't block the
toggle.

---

## ITEM 4 — "Ignore this copy" + tree restore dialog

### Why it's small
Discovery already dedupes by **normalised path only, first-hit-wins, with NO
name/identity dedup** (`forest_discover.discover`), so a local copy and a server
copy at different paths **already both appear**. The missing piece was the
*inverse* — suppressing one — and the `excluded[]` substrate
(`ForestDef.excluded`, path-keyed, honoured by `diff_against`, undo via the
Excluded-items dialog) already existed. So:

- **`ForestController.ignore_copy(path)`** — adds `path` to `excluded`, drops
  its item. **"Plus children":** when `path` is a `.scriptreetree`, every OTHER
  forest item whose catalog lives UNDER the same app folder is excluded too
  (covers an app that surfaced as several items). Path-keyed → the other copy
  is untouched.
- **`forget_excluded(paths)`** — drop from `excluded` without re-adding.
- Right-click **"Ignore this copy"** wired into the per-item popup
  (`tree_popup._show_for_action`, modelled on the existing Uninstall button +
  the `_forest_menu_extension.__self__` controller walk).
- **`ExcludedItemsDialog` rebuilt as a `QTreeWidget`** grouped by on-disk
  folder (common-prefix-collapsed directory trie; each node carries its
  subtree's excluded paths). Select a leaf → restore just it; select a folder →
  restore it + children. "Restore one, or one and its children."

### The Ignore gotcha the review caught
`ignore_copy`'s child-folder match first used `os.path.abspath` while the
excluded set + discovery use **`_norm` (which `Path.resolve()`s symlinks)**. On
a junctioned/symlinked tree the two could disagree, so an "ignored" child could
reappear next discovery. *Fix: derive `app_dir` and the child test through the
SAME `_norm` used for the excluded set.* The trailing `/` on `app_dir` is
load-bearing — it stops a sibling folder whose name shares a prefix
(`SolidWorks/` vs `SolidWorksTools/`) from matching.

### Test-isolation note
Rebuilding the dialog broke two EXISTING `test_forest.py::TestDialogs` tests
that called the removed flat-list `_reinclude(path)`/`_forget(path)` — updated
to the tree API (`_tree.selectAll()` → `_reinclude_selected()`/
`_forget_selected()`). Separately, `test_global_env_layering.py` sets
`QSettings.setDefaultFormat(IniFormat)` process-globally and never restores it —
a pre-existing cross-test leak that can make QSettings-touching dialog tests
flaky under `pytest-randomly`; not a89's doing.

---

## Reusable takeaways
1. **Portable = redirect ONE master root (`default_personal_root`) + the
   handful of paths that DON'T derive from it.** Enumerate the chokepoint set;
   the sibling SHARED twin (`shared_autoload_path`) and the per-scope subdir
   (`_programdata_dir`) are the easy misses.
2. **A travelling `scriptree.ini` override can defeat the very portability it
   ships in** — gate `install.*` overrides on "inside the install anchor" when
   portable.
3. **A `set_*` that swallows OSError must return success/failure; callers that
   show a success toast must honour it** (read-only USB is the target medium).
4. **Adding an opt-in feature can falsify an existing unconditional doc claim** —
   re-grep the marketing/feature docs.
5. **Dual-source "both copies show" is already the default** (path-only dedup);
   build the *Ignore* (suppress one) on the existing `excluded[]` substrate, and
   match its `_norm`/resolve normalisation so child-suppression can't drift.
