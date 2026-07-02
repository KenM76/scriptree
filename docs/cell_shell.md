# The cell + ring shell (ScripTreeRing)

ScripTree V3 ships with **three launchers + a headless screenshot tool in one installation**:

| Launcher | What it does |
|---|---|
| `run_scriptreeforest.bat` **(primary)** | The **forest workspace**: a persistent root cell on the desktop plus every cell linked under it. Auto-discovers nearby `.scriptreering` / `.scriptreetree` / `.scriptree` catalogs at startup, restores the saved layout, adopts new tools as they appear. Most users double-click this after install. Internally chains into `run_scriptreering.py` with `SCRIPTREE_FOREST_MODE=1`. |
| `run_scriptreering.bat` | Floats one or more **cells** (hexagonal or square) on your desktop with **no forest workspace**. A single click pops up its tool menu; a double click opens the V1 standalone runner or the full editor. Two cells dragged close together **dock** into a *Tree Ring*. Save and reload layouts as `.scriptreering` files. |
| `run_scriptree.bat` | The classic **V1 editor**. Tool runner, configurations, parser, save/load. All three shells (forest / ring / cell) **call the V1 editor as a subprocess** for any tool launch — V1 is the toolbox; the shells are launchers. |
| `run_screenshooter.bat` | Headless screenshot tool — renders cells, forms, menus, and composites as PNG without ever flashing a window onto the desktop. |

> "Cell" is the user-facing term for the launcher widget. The visible
> shape can be either `hexagon` or `square` (a Cell preferences setting),
> so the words "hexagon" and "square" still appear in this doc when
> describing the *shape*. The thing being launched is always a "cell".

---

## Single-instance handoff (v0.2.1)

By default a second `run_scriptreering.bat` invocation **hands off**
to the running primary instance via a per-user `QLocalServer` pipe.
The new positional `.scriptreering` paths and any catalog drops are
handled by the existing process so newly-spawned cells can dock with
the cells already on screen.

Pass `--new-process` on the command line to opt out (the second
invocation runs as a fully isolated process — useful for diagnostics,
not for everyday use, since the cells in the two processes can't
dock with each other).

---

## Cell gestures

| Gesture | Standalone cell | Master / ring cell (and Forest hub) |
|---|---|---|
| **1× left click** | Toggle the cell's tool menu next to the cell. Click another cell → its menu opens (the previous one closes). Click the same cell again → the menu hides. Picking a tool launches the V1 standalone runner with the tool's default configuration. **v0.8.0a28+:** right-click any entry inside the popup tree for a per-item context menu (**Open containing folder**, **Uninstall app from disk…** when the tool's catalog lives under an install root). | **v0.6.20+:** collapse / expand the whole linked group. Forest single-click recursively tucks every link-descendant into the forest hub; ring single-click tucks the ring's members. Click again → expand. (Pre-v0.6.20 this opened a popup menu; the popup now lives on double-click — see below.) |
| **2× left click** | Opens V1: the **standalone runner** if the cell is bound to a `.scriptree`, or V1's **full editor** with the tree pre-loaded if the cell is bound to a `.scriptreetree`. | **v0.6.20+:** in-process popup tree with one sub-folder per member (union of every member's catalog for a ring; every forest item for the forest hub). Same content the single-click used to show. Works whether the group is expanded or collapsed (v0.6.23: the popup raises above the always-on-top member cells when the group is expanded). |
| **1× right click** | Role-aware context menu (v0.8.0a117+). Standalone cells: **ScripTree ▶**, **Tree Ring ▶**, **Cell ▶** sub-menus plus top-level About / Settings / Preferences and Close / Exit-all. Plain member cells (a docked tool under a forest or ring) omit the **ScripTree ▶** and **Tree Ring ▶** sub-menus — a docked tool doesn't manage catalogs or rings. See "Right-click menu" below. | The forest hub gets a dedicated, curated menu instead (a117–a121): **Open…**, **New ▸ Cell**, then the controller-built groups **File ▸ / Sources ▸ / Settings ▸ / Recent layouts ▸**, **Bring all cells back on-screen**, the two-tab **About…**, and **Exit all**. It deliberately has NO Close-ring/Disband-style actions — those could detach forest members. |
| **2× right click** | Opens V1's full editor on the cell's catalog (or a blank editor if no catalog is bound). | Opens V1's full editor on a *merged* `.scriptreetree` — each member becomes a top-level folder. The merged file is regenerated whenever membership changes; same membership = same temp file (V1 can keep it open). If no member has a catalog yet, a placeholder folder is shown so the editor never opens blank. |
| **Drag (cell)** | Live snap detection — when the dragged cell's centre falls within `snapDistancePx` (default 18 px) of one of the target's six honeycomb-neighbour slots, a 2 px highlight outlines the intended dock. Release to commit. Two forest-linked cells dragged together while loose form a new ring that itself stays linked to the forest (v0.6.14+). | At master drag-end, a free standalone within ~1.6×size_px of the master's centre is absorbed as a new ring member; if the absorbed cell was forest-linked, the master inherits the forest link too (v0.6.14+). |
| **Drag (ring to a forest cell)** | — | The ring becomes a forest sibling of the cell (`link = Forest, dock = Forest`); the cell is NOT pulled into the ring. The forest's repack lands the new ring on the nearest free honeycomb slot, which by closest-slot semantics ends up adjacent to the cell you dropped near (v0.6.16+). |

## Link vs Dock (v0.6.16+)

Every cell carries **two independent parent-pointers**:

| Relationship | Field on cell | What it does | Triggers |
|---|---|---|---|
| **Link** | `_group_master_id` (alias `link_master_id`) | The master this cell logically belongs to. Forms a tree rooted at the Forest. | Outline tint (associated colour), recursive collapse, save/exit-all propagation. |
| **Dock** | Membership in `master._positioned` | The master whose physical drag this cell rigidly translates with. Flat set. | Drag-translation, edge-fold, collapse-tuck animation. |

The two usually coincide. They diverge in two practical cases:

* **Loose-linked** — a cell dragged out of its cluster keeps its
  `link_master_id` (you're still associated, you just stepped out
  of the ring's geometry).  Visible via a dimmer outline tint.
  The cell still collapses with the master when the master
  collapses.
* **Forest member rings** — a ring that's a child of the forest
  has its master's `link_master_id` set to the forest hub.  Drag
  the forest, the ring follows (it's also in `forest._positioned`).
  Collapse the forest, the ring shrinks into it AND the ring's own
  cells shrink into the ring (recursive).

See `docs/LLM/icon_library.md` for the icon vocabulary
(`icon-forest`, `icon-ring`, …) and
`docs/LLM/menu_appearance.md` for the menu font / icon scale UI
that lives in the cell **Settings → Shape & Size** tab.

## Menu font & icon scale (v0.6.21+)

Right-click any cell → **Settings… → Shape & Size** tab → scroll
down to "Menu font & icon scale".  Slider for percent (default
**125%** of OS default), dropdown for absolute pt size, separate
slider for icon scale, and checkboxes for **Save to local** (this
user) and **Save to shared** (all users on this machine; gated
by the `menu_appearance_shared_write` capability).  The same
save checkboxes also publish the current cell's shape /
orientation / size to the global cell defaults so new cells you
spawn afterwards inherit those choices.  Storage paths and
resolution order in `docs/LLM/menu_appearance.md`.
| **Shake during drag** | Break free from the current ring. The cell un-docks; the master destroys itself if fewer than 2 members remain. | — |

### How the master ("ring" / "tree ring") spawns

When two compatible cells dock (same shape, same orientation, full-edge share), a third cell appears at the midpoint of their shared edge, displaced one hexagon-width *opposite* the centre of mass. That third cell is the **master**. Its menu = the union of every member cell's catalog. Its identity is deterministic: `master:<sorted member id pair>` — so re-docking the same two cells brings back the same master at the same remembered position.

### Group uniformity (v0.2.10)

Every cell in a master+members group shares the same **size**, **shape**, and **orientation**. The user-visible consequences:

- When a cell joins a group (via drag-snap or drag-drop), it adopts the group's size and shape on the spot. If the docking cell was 40px and the group is at 56px, it grows to 56px the moment the snap commits.
- Opening the right-click → **Settings** dialog on **any** cell of a group treats every change as a group-level edit: changing the size on one member resizes the master and every other member; changing the shape from hexagon to square switches the whole ring.
- Standalone cells (no group) still have per-cell size/shape — those settings only propagate once the cell docks.
- After any geometry change, the ring is **repacked** so members stay edge-touching the master with no overlap. Members that would land off-screen at the new geometry are reassigned to a free, on-screen direction.
- When you drag a master so part of the ring would slide off-screen, the off-edge members reattach to a different direction on release. They never end up clipped, hidden behind the taskbar, or stacked on top of each other.
- **Collapse and expand keep cells on-screen and attached to a side (v0.8.0a68+).** Single-clicking the forest hub or a ring master to collapse tucks all members into the hub; single-clicking again to expand re-blooms them through the same free-slot engine that startup uses — each member lands on the nearest free, on-screen, non-overlapping honeycomb slot attached to the hub's current position. If the hub moved while collapsed, the cells re-bloom around the new position. Stacked or off-screen re-bloom is a sign that the expand path is replaying a stored coordinate instead of routing through the engine.
- **Display-change keeps the whole ring together (v0.8.0a72+).** When a monitor is unplugged or the resolution changes, the ring master is clamped on-screen first, then its members are repacked via the same free-slot engine. They never stack at the screen edge — each member gets an unoccupied honeycomb slot around the master's new position.

### Drag-drop dispatch (v0.3.6)

The full matrix for dropping a `.scriptree`, `.scriptreetree`, or `.scriptreering` file from Explorer onto a cell:

| Cell state | `.scriptree` / `.scriptreetree` | `.scriptreering` |
|---|---|---|
| **Empty standalone** (no catalog) | Binds the catalog to *this* cell. | Closes this cell, loads the ring in its place. |
| **Bound standalone** (has a catalog) | Spawns a fresh sibling cell next to this one, bound to the dropped catalog. The source cell's binding is unchanged. | Loads the ring alongside (same as the right-click → **Load ring** action). |
| **Master / ring** | Spawns a fresh member cell bound to the dropped catalog, **auto-joins it to this ring's group** at a free honeycomb slot, with the master's size / shape / orientation. The ring is marked dirty so closing without saving prompts. | Loads the ring alongside (a separate group — does NOT merge into this ring). |

The dispatch is the same whether you trigger it via drag-drop OR the right-click → **Load…** menu actions; both routes share the v0.2.11 `_open_catalog_path` for standalones and the v0.3.6 `_drop_spawn_member_and_link` for masters.

---

### Cell fill colour (v0.3.6)

The right-click → **Settings** dialog has a **Cell fill colour** group with four mutually-synced controls:

- **Hex entry** — `#RRGGBB` text input.
- **R / G / B spinboxes** — 0–255 each.
- **Hue rainbow slider** — drag the thumb across the rainbow gradient to pick a fully-saturated colour at that hue.
- **Reset** — revert to the branding default.

Editing any one control updates the others. The hue slider always picks a fully-saturated, full-value colour at the chosen hue; if you want a muted colour, type the hex directly. Alpha (transparency) is owned by the separate **Transparency** slider — picking a new fill colour never changes transparency.

The chosen colour is stored in the catalog JSON's `cell.fill_color` field (e.g. `"fill_color": "#ff8800"`) so it travels with the file. Per-cell, not group-uniform — a master and its members can each have a different colour, useful for colour-coding the tools in a ring.

---

### Cell text colour (v0.3.8)

Right below the fill-colour group, the **Settings** dialog now carries a matching **Cell text colour** group with the same four controls (hex, RGB spinboxes, hue rainbow slider, Reset). The override applies to whatever label the cell is showing — auto-derived letters or your custom-text override; icon labels are not tinted.

- **Reset** — clears the override; the label colour falls back to the cell's stroke-derived default (palette-coordinated to remain readable against the fill).
- **Alpha** is computed from `transparency × label_opacity` at paint time; the text-colour controls are RGB-only, exactly like the fill-colour group.
- **Persistence** — stored in the catalog JSON's `cell.text_color` field (e.g. `"text_color": "#eeeeee"`), independent of `fill_color`. Pre-v0.3.8 catalogs round-trip byte-identical.

Use it to colour-code tools in a ring even more aggressively (e.g. dark fills with light text vs. light fills with dark text).

---

### Click-to-run cells (v0.3.5)

By default, single-clicking a cell pops up a tool menu — pick a tool from the menu, V1's standalone runner opens. v0.3.5 adds a per-cell setting that **changes single-click into a Run button**:

- **Click action** (`Show menu` / `Run tool(s)`) — set in the cell's right-click → **Settings** dialog. When set to **Run tool(s)**:
  - For a `.scriptree` cell → single-click opens V1's standalone with the tool, immediately auto-clicking Run.
  - For a `.scriptreetree` cell → single-click runs every leaf (depth-first through folders).
- **Run mode** (`Sequential` / `Parallel`) — only meaningful for trees:
  - **Sequential** (default) — opens leaves one at a time. Each leaf's V1 standalone window opens, auto-runs, and stays open until the user closes it. The next leaf opens only after the previous closes.
  - **Parallel** — every leaf's V1 standalone spawns simultaneously. Each window auto-runs in its own process. The user ends up with N independent windows running concurrently.

The choice is stored in the catalog JSON's `cell` sub-object (`cell.click_action`, `cell.click_run_mode`) so the configuration travels with the file. Rebinding the cell to a different catalog reads back that catalog's preference.

**Permission gate.** The `cell_click_to_run` capability gates this feature — when the file is missing or read-only, the **Click action** dropdown in the Settings dialog is locked at "Show menu" and the Run-mode dropdown stays disabled. Even if a catalog's JSON specifies `click_action: "run"`, the cell falls back to the menu-popup behaviour at click-dispatch time when the capability is denied.

Implementation note: V1 gained a `-run` CLI flag in v0.3.5 that auto-clicks the Run button after the standalone window finishes loading. Click-to-run cells append `-run` to the V1 launch command. The same flag is available from the command line for scripting:

```
run_scriptree.bat path/to/tool.scriptree -run
```

---

## Drag-drop file support (v0.2.5)

Drop targets and effects:

| File dropped | Onto **standalone** cell | Onto **master** / ring |
|---|---|---|
| `.scriptree` or `.scriptreetree` | **Spawns a new cell** (sibling of the drop target) bound to the dropped catalog. The drop target is left alone. | Spawns a new sibling member next to the master, bound to the dropped catalog, and joins it into the ring. |
| `.scriptreering` | Opens the new ring undocked-but-related. Cells from the new ring share the same `SnapEngine` as cells already on screen, so members of one ring can still dock against members of another. | Same — opens the new ring alongside the existing one. |

You can also drop catalogs onto the menu items inside a cell's
right-click → **ScripTree ▶ Open recent ▶** sub-menu via Explorer's
normal "open with" association.

---

## Drop-install: folders and zips onto a forest cell (v0.8.0a23+)

If you drag a **folder** or a **`.zip` archive** onto a forest cell
(the hub at the top of your forest), ScripTree treats it as an *app
to install* and walks you through two short dialogs:

### 1. Where to install

| Choice | Default location |
|---|---|
| **Shared** | `<ScripTree install>/ScripTreeApps/` — travels with the install. Good for portable / USB setups and for apps that should be visible to every Windows user on the machine. |
| **Personal** | OS-canonical per-user app data: `%LOCALAPPDATA%/ScripTree/Apps/` on Windows, `~/Library/Application Support/ScripTree/Apps/` on macOS, `$XDG_DATA_HOME/ScripTree/Apps/` (or `~/.local/share/ScripTree/Apps/`) on Linux.  Private to the current user — does not need elevation. |
| **Other…** | Pick any folder.  ScripTree creates the app's subfolder inside it. |

Below each radio is a **live preview path** that updates as you
edit the **Install as:** field.  By default the app name is taken
from the folder name (or zip stem, e.g. `MyTool.zip` → `MyTool`);
type a new name to rename on install.  Unsafe characters
(`< > : " | ? *` and control codes) are scrubbed silently — you
won't see an error, just a sanitised name.

You can override the **Shared** and **Personal** defaults in
**Edit → Settings… → Drop-install locations** (writes the
`install.shared_root` / `install.personal_root` INI keys).  Blank
field means "use the OS default" again.

### 2. Conflict handling

If the chosen target already contains a folder with that name,
a second dialog opens with four radio buttons:

| Choice | What it does | When to use |
|---|---|---|
| **Update** (default) | For every file in the *source*, replace the corresponding file in the *target*.  Files in the target that don't exist in the source are **left untouched** — your `.scriptree.configs.json` sidecars and any user-edited configurations survive. | Upgrading an app to a new release. |
| **Overwrite** | Delete the existing target folder, then copy/extract fresh.  **Destructive** — you lose any local edits. | Reinstalling a broken or corrupted app. |
| **Rename** | Install as `<name>-2`, `<name>-3`, … until a free slot is found (capped at 999). | Keeping multiple versions side-by-side, or installing two apps that happen to share a name. |
| **Cancel** | Abort.  Nothing is written. | Mis-targeted drop. |

If you skip the conflict dialog (close it without picking),
the safe default is **Cancel** — nothing is written.

### 3. After install

The forest's `refresh_from_sources()` is fired immediately, so
the newly-installed app appears in the forest's menu and tree on
the next layout pass.  The forest's `auto_discover` configuration
governs whether new items are auto-added or prompted-for — same
flow as the manual **Forest ▶ Auto-add** menu entry.

**The personal-apps directory is in the default scan-folders list**
(v0.8.0a24+).  When a fresh forest is constructed, its
`AutoDiscoverConfig.roots` defaults to **three** entries instead of
two:

1. `ScripTreeApps` (in-install)
2. `../ScripTreeApps` (sibling-to-install)
3. The host machine's per-user app-data directory — whatever
   `default_personal_root()` returns on the OS where the forest is
   first constructed (e.g. `C:\Users\<you>\AppData\Local\ScripTree\Apps`
   on Windows, `~/Library/Application Support/ScripTree/Apps` on
   macOS, `~/.local/share/ScripTree/Apps` on Linux).

The third entry is **visible in the forest settings dialog's
scan-folders list** — you can edit it, remove it, or add a second
personal path by hand.  If a forest written on Windows is later
opened on macOS (or vice versa), the Windows path doesn't exist on
the macOS host so `discover()` silently skips it — no error, no
warning.  Add the macOS path manually via the settings dialog if you
want both surfaces scanned from one forest.

This means an app you drop-install on this machine is guaranteed to
show up on the next forest launch with no further setup, while
forests stay editable and the user can always see exactly which
folders are being scanned.

### Zip extraction details

* **Single-folder wrapper auto-detect.**  If the zip's top level
  is one directory whose name matches the zip stem
  (case-insensitive, with `.zip` stripped), ScripTree extracts
  *that folder's contents* directly into the target.  Otherwise
  the zip contents are extracted into a folder named after the
  zip stem.  Either way you get a clean `<target>/<app name>/…`
  tree without the awkward `<target>/<app name>/<app name>/…`
  double-wrap.
* **Path-traversal safety.**  Members with `..` segments or
  absolute paths are rejected before any byte is written — the
  install is aborted with an error.
* **Symlinks inside zips are NOT followed.**  We extract them
  as ordinary file entries.

### What about non-forest cells?

Drop-install is **gated on the forest master**.  Dropping a
folder onto a standalone cell, a ring master, or a ring member
is silently ignored (the standard `.scriptree` / `.scriptreetree`
/ `.scriptreering` drops still work on every cell — only the
"new behaviour" of installing a *folder* is forest-specific,
because the forest is the surface that knows how to pick up the
newly-installed app via auto-discovery).

### Uninstall: removing an installed app (v0.8.0a26+)

The reverse of drop-install. There are **two ways** to reach
it:

1. **From the cell's tool-popup menu (recommended for one
   specific tool):**
   single-left-click the cell to open its tool menu, then
   **right-click any tool entry**. A small context menu
   appears with **Uninstall app from disk…** (when the
   tool's containing catalog lives under one of the install
   roots) plus **Open containing folder**.
2. **From the cell's right-click context menu:**
   right-click the cell, **Forest** ▶ **Uninstall app from
   disk…**.

Either entry pops the same checkbox-style confirmation
dialog:

> **Uninstall the app at: `<path>`**
> This will permanently delete the app folder.
>
> ☑ Also remove my local saved configurations *(N files)*
> ☑ Also remove shared configurations stored with the app
>   *(N files)*

The live counts are computed before the dialog opens so you
know exactly what's about to be touched.

**Local saved configurations** are the personal sidecars
ScripTree wrote for this app's tools to your per-user configs
folder (`%LOCALAPPDATA%\ScripTree\UserConfigs\` on Windows,
under `Application Support` on macOS, `~/.config/ScripTree/`
on Linux). A sidecar "belongs to" an app when *both* its
recorded source filename matches a tool inside the app folder
*and* its recorded source location resolves into that folder.
The two-prong match means two different installs of the
same-named tool don't sweep each other's personal configs.

* **Box checked (default)** — those sidecars are deleted.
* **Box unchecked** — sidecars are left on disk. If you
  later re-install the same app at the same path, your
  saved configurations re-attach automatically.

**Shared configurations** are the `*.scriptree.configs.json`
and `*.scriptreetree.treeconfigs.json` files that live
**inside** the app folder. Normally they go with the
`shutil.rmtree(app_dir)`.

* **Box checked (default)** — they're removed with the
  folder.
* **Box unchecked** — before the rmtree, every shared
  sidecar is copied into a sibling backup folder named
  `<app>_uninstalled_configs/` (with a numbered suffix
  `<app>_uninstalled_configs-2/`, `…-3/` if the path is
  already taken). The success toast tells you exactly where
  the backup went. If the copy step fails for any reason
  (permissions, disk full, etc.) the uninstall is **refused**
  — the app folder is not removed when its configs would
  otherwise be lost.

**Safety guards on the uninstall path itself:**

* Refuses unless the app folder is a strict descendant of
  either the personal install root or the shared install root.
  Drop-installs elsewhere on disk are never touched by the
  uninstall flow.
* Refuses to delete the install root itself when the cell
  happens to be bound to a catalog dropped directly in the
  root (an edge case but the guard catches it).
* The ForestItem is removed and the path is added to
  `forest.excluded` **before** the rmtree, so auto-discovery
  won't silently re-add the app from a sibling location while
  cleanup is still running.
* Any open cell bound to the catalog is closed first so the
  files aren't held open during the delete.

The uninstall is **not undoable** — the rmtree is a real
filesystem delete, not a recycle-bin move. The shared-configs
backup is the only recoverable scrap.

---

## Forest hub visibility modes (v0.8.0a52+)

The forest hub has three independently-toggleable surfaces.  At least
one must always be active (the UI refuses to uncheck the last one and
tells you why).

| Surface | What it does | "Hidden" means |
|---|---|---|
| **Always on top** (default ON) | The hub floats above every other app window. It is always visible on the desktop. | — (you can minimise by right-clicking the taskbar entry if taskbar mode is also on, but AOT mode has no dedicated hide path) |
| **Show on taskbar** | The hub gets a dedicated Windows taskbar entry (like PortableApps). Clicking the entry reveals the hub and all cells; clicking again minimises the hub back. | Hub minimised — taskbar button stays, hex is off-screen. |
| **Show in system tray** | A small tree icon in the notification area. Left-click → reveal hub + cells; right-click → Show / Quit menu. Works whether or not AOT is also on. | Hub hidden (no taskbar entry, no hex). |

Toggle these under **Forest ▶ Visibility** in the hub's right-click menu.

### Auto-hide (taskbar and tray modes)

When "Always on top" is OFF and at least one of taskbar / tray is ON,
ScripTree enters **auto-hide** mode:

* Clicking the taskbar entry or tray icon reveals the hub and every cell
  that was visible when the hub was last hidden.  Cells you had
  deliberately closed before hiding stay closed.
* As soon as focus moves to a window that is NOT the forest hub or a
  registered cell, the hub and its cells auto-hide after an 80 ms
  debounce.
* **Own dialogs are exempt.**  While a ScripTree-spawned dialog (About,
  Settings, a warning dialog) or the cell right-click menu is open, the
  auto-hide is suppressed — `QApplication.activeModalWidget()` and
  `activePopupWidget()` are checked before every hide decision (v0.8.0a60).
  A `QMessageBox.warning(parent=None, ...)` call (no explicit parent) is
  caught by this check even though a parent-chain walk would miss it.

### Cells revealed after a move (v0.8.0a62)

If you drag the hub to a new location while the forest is hidden, the cells
you previously had open remember their old positions — which may now be
partly or wholly off-screen.  When the hub is next revealed (tray or
taskbar click), ScripTree automatically rescues every revealed cell back
onto a visible screen using the same clamping logic as the display-change
rescue.  A cell that was already on-screen is left exactly where it is.

### Re-launching the shortcut (v0.8.0a64)

Double-clicking the ScripTree Forest shortcut while a forest is already
running sends a "show me" signal to the live process.  The existing forest
hub is revealed via the visibility manager — no duplicate instance is
created, no stray cell is dropped.  This is the same PortableApps-style
behaviour: re-launching = "bring it forward", not "start another copy."

### Error feedback from file-open via second launch (v0.8.0a65)

If you launch `run_scriptreeforest.bat path/to/file.scriptreering` while a
forest is already running and the file can't be opened (bad path, read error,
corrupted file), the LIVE primary process pops a warning dialog.  The second
launch exits cleanly — the live process does not crash, and a second instance
is NOT started.

---

## Display-change recovery (v0.8.0a26+)

If you change your screen resolution, unplug a monitor,
re-arrange a multi-display layout, or remote-desktop in from
a smaller machine while ScripTree is running, cells whose
position no longer maps to any visible work area are
**automatically pulled back on-screen**.

Mechanics:

* `scriptree.shell.screen_watcher` hooks every Qt screen-
  change signal (`screenAdded`, `screenRemoved`,
  `primaryScreenChanged`, per-screen `geometryChanged` and
  `availableGeometryChanged`).
* When any of those fires, a 200 ms debounce timer schedules
  one rescue pass — Qt fires a storm of signals when a
  monitor is plugged in, and we want one rescue per physical
  event, not one per signal.
* The rescue walks every registered cell and clamps its
  top-left to the available geometry of the nearest visible
  screen using the same `_clamp_to_screen` helper drag-end
  uses, so behaviour is identical to "drag the cell off the
  screen edge and release."

If something didn't get caught (e.g. the OS reported the new
layout in pieces that didn't trip any signal we hook),
there's a manual escape hatch: **Forest** ▶ **Bring all
cells back on-screen**. A toast tells you how many were
moved.

This replaces the old workaround of quitting ScripTree,
deleting the ring/forest save file by hand, and starting over.

---

## Right-click menu

The right-click menu (v0.2.3 + v0.2.4; role-aware gating v0.8.0a117/a118)
is organised into three sub-folders plus a top-level row.  The tree below
is the FULL menu as a **standalone cell** shows it; a **plain member cell**
(role != master, docked under a live master) omits the **ScripTree ▶** and
**Tree Ring ▶** sub-folders, and the **forest hub** never uses this menu at
all (it takes its own curated branch — see `scriptreeforest_format.md`,
"Right-click menu"):

```
├── ScripTree[Tree]: <name>          (read-only label of what's loaded)
├── ─────
├── ScripTree ▶
│   ├── Load ScripTree…              (spawns a new cell — v0.2.8)
│   ├── Load ScripTreeTree…          (spawns a new cell — v0.2.8)
│   ├── Open recent ▶                (each entry spawns a new cell — v0.2.8)
│   ├── Save catalog as…
│   └── Clear loaded file
├── Tree Ring ▶
│   ├── Save ring…                   (file filter "Tree Rings (*.scriptreering)")
│   ├── Load ring…
│   └── Auto-load on startup ▶
│       ├── Disabled
│       ├── For current user only
│       └── For all users (requires admin)
├── Cell ▶
│   ├── Spawn another cell
│   └── Disband group / Leave group  (conditional — only on rings)
├── ─────
├── About <brand>
├── Settings…
├── Preferences…
├── ─────
├── Close this cell  /  Close ring (undock all members)  /  Close all related   (role-aware)
└── Exit all
```

### "Load X" — empty cell binds, bound cell spawns sibling (v0.2.11)

Every "load" action under **ScripTree ▶** — Load ScripTree, Load
ScripTreeTree, Open recent — and **Tree Ring ▶ Load ring** routes
through one rule:

* **Empty cell** (no catalog bound, not a master) → the loaded
  catalog populates *this* cell. The placeholder you opened becomes
  the loaded cell. For a `.scriptreering`, the empty cell closes
  and the ring's master + members appear in its place.
* **Bound cell** (already has a catalog) or **master** → a fresh
  sibling cell is spawned next to the source. The source stays
  untouched.

Drag-drop of a catalog onto a cell follows the same rule: empty cell
binds, bound cell spawns a sibling, master adds the dropped catalog
as a new member.

If you want to *rebind* an already-bound cell, use **Cell ▶ Clear
loaded file** first.

---

## Cell labels (v0.2.5–v0.2.7)

Each cell paints a centered label so you can tell them apart at a
glance. The label is chosen by priority:

1. **Icon** if one is configured.
2. **Custom text** if one is configured.
3. **Auto-derived letters** from the bound catalog's name (default).
4. **`?`** if nothing is bound and no override is set.

### Auto-derived letter rules

The default auto-letters take 1–2 characters from the catalog name.
The rules are applied in order:

- **CamelCase precedence.** A camel-cased single word always wins
  over the multi-word rule. `"FastAPI tools"` → **"FA"**, not
  **"Ft"**, because the first word is a CamelCase compound.
- **Skip-words filter.** When falling through to the multi-word
  rule, the words `{a, an, and, or, the, of, to, in, on, for, at,
  by, as, is, if}` are removed (case-insensitively) before
  collecting first letters. So `"The Daily Build"` →  **"DB"**.
- **Two-word fallback.** Take the first letter of the first two
  surviving words, upper-cased. `"build runner"` → **"BR"**.
- **One-word fallback.** First two characters of the surviving word,
  upper-cased. `"build"` → **"BU"**.
- **Empty.** Falls through to **`?`**.

### Per-cell label settings

Right-click cell → **Settings… → Cell label** group. Three modes:

| Mode | What's shown |
|---|---|
| **Default** | Auto-derived letters from the catalog name. |
| **Custom text** | Whatever short string you type into the field. |
| **Icon** | An image file (PNG / JPG / SVG / etc.) painted inside the cell. |

When **Icon** is selected, two sliders become available:

- **Scale** — 25 % to 200 %, **relative**. Resizing the cell scales
  the icon proportionally so a 56-px cell with a 100 % icon and a
  96-px cell with a 100 % icon both feel "the same size of icon
  for that cell".
- **Opacity** — 20 % to 100 %, controls the painted alpha so a
  busy icon can fade into the cell colour.

### Embed / Unembed (v0.2.7)

The Cell label group has two extra buttons next to the icon picker:

- **Embed** — read the chosen icon file from disk, base64-encode it,
  and write the bytes into the catalog JSON. The on-disk path is
  cleared (so the catalog is now self-contained — no broken icon
  reference if you move the catalog).
- **Unembed (Save as…)** — extract the embedded bytes back to a
  chosen file, rewrite the catalog with a relative path to that
  file, and clear the embedded payload.

### Where cell appearance lives (v0.2.7)

Icon, text, scale and opacity are stored in the **catalog JSON**
(`.scriptree` or `.scriptreetree`) under a `cell` sub-object on the
top-level `ToolDef` / `TreeDef`. The full schema is in the LLM docs:

- [`docs/LLM/scriptree_format.md`](LLM/scriptree_format.md) — `cell`
  section under top-level shape.
- [`docs/LLM/scriptreetree_format.md`](LLM/scriptreetree_format.md)
  — same `cell` sub-object on the tree.

Defaults are omitted on save, so a `.scriptree` that doesn't customise
its cell appearance stays byte-identical to the legacy format.

A `.scriptreering` file overrides the catalog's `cell` settings only
for the saved-and-restored layout (positions, sizes, transparency).
Icon and text always come from the catalog itself.

---

## File format: `.scriptreering`

A `.scriptreering` file captures either:

- a **single standalone cell** (`master.role = "standalone"`, `members = []`), OR
- a **whole ring** (the master cell plus all its member cells).

The format is plain UTF-8 JSON; `format = "scriptreering"`, `version = 1`. Full spec lives at [`docs/LLM/scriptreering_format.md`](LLM/scriptreering_format.md).

When ScripTreeRing starts, it reads:

- Any `.scriptreering` paths passed positionally on the command line.
- The user-scoped autoload list at `<APPDATA>/ScripTree/autoload_rings.json`.
- The system-scoped autoload list at `<PROGRAMDATA>/ScripTree/autoload_rings.json`.

If none of those produce any cells, ScripTreeRing spawns one fresh starter cell with no catalog bound (right-click it to load one).

### Save a layout from the cell shell

Right-click any cell → **Tree Ring ▶ Save ring…**. The dialog defaults to `~/Documents/ScripTree/rings/` and uses the file filter "Tree Rings (*.scriptreering)". The saved file captures every cell's position, size, transparency, shape/orientation and `catalog_path`.

### Unsaved-ring close prompt (v0.3.1)

Closing a ring with unsaved membership changes shows a **Save / Discard / Cancel** dialog before tearing it down. The prompt fires when:

- The ring has never been saved (no `.scriptreering` file exists for it yet), **or**
- A cell has been added to or removed from the ring since the last save.

It does **not** fire for pure position changes — dragging the ring around, repacking after a size/shape change, drift snap-back. Position is cheap to redo; membership isn't.

The check runs from all three master close paths: **Close ring (undock all members)**, **Close all related (master + members)**, and the rare master-cell **Close this cell**. Picking Cancel aborts the close; Save runs the standard save flow (Save-As prompt if no file exists yet, otherwise straight write); Discard closes without writing.

### Save a single-cell layout from the V1 editor

The V1 editor doesn't render cells, but **File → Save Cell Layout** (or **Save Cell Layout As…**) saves a single-cell `.scriptreering` referencing the `.scriptreetree` you currently have loaded. Open it later with **File → Open Cell Layout…** (which launches ScripTreeRing on it) or by double-clicking the `.scriptreering` in Explorer once the file association is set.

### Hand a file off to the cell shell from the V1 editor (v0.2.9)

Two File-menu actions launch ScripTreeRing on whatever you're currently working on:

- **File → Open in cell shell** — works for any active file (the editor's bound `.scriptree`, the loaded `.scriptreetree`, or a `.scriptreering`). The shell spawns one cell bound to the file (or loads the ring if it's a `.scriptreering`).
- **File → Open tree in ring shell** — only enabled when a `.scriptreetree` is loaded. Each top-level item (folder or leaf) becomes its own cell, and the cells appear in a honeycomb ring around a master. Folders are materialised as their own temp `.scriptreetree` files in `%TEMP%` with absolute leaf paths. The ring file is written to `%TEMP%/scriptreering_explode_<hash>.scriptreering` and handed to ScripTreeRing.

Both actions fire-and-forget the cell shell as a separate process; the editor stays open. If ScripTreeRing is already running, single-instance handoff (above) routes the new file into the existing primary so the cells appear alongside whatever's already on screen.

---

## Autoload on Windows startup

Right-click any cell → **Tree Ring ▶ Auto-load on startup → For current user only**. ScripTreeRing writes the path into `<APPDATA>/ScripTree/autoload_rings.json` *and* adds a `Run` registry entry pointing at `run_scriptreering.bat --autoload-rings`. Removing autostart undoes both.

System-wide autostart (HKLM, all users) requires admin elevation — ScripTreeRing prompts via UAC when needed.

### Forest login-autostart (v0.8.0a84)

The **forest** has the same capability: right-click the forest hub → **Forest ▶ Auto-load on startup → For current user only / For all users**. This records the scope in `forest_preferences.json` (`autostart_scope`) and points the launch default at the currently-saved forest, so ScripTree starts in forest mode at login and loads exactly that forest. A transient (unsaved) forest is prompted to Save first; "all users" prompts for admin via UAC.

Because ScripTree is single-instance, the ring and forest share **one** `Run` value per scope (named after the brand). A single chokepoint — `ring_io.recompute_autostart(scope)` — writes the combined command, adding `--forest` and/or `--autoload-rings` as configured (`"<exe>" -m scriptree.shell.ring_main --forest --autoload-rings`), so enabling forest autostart never clobbers ring autostart and vice-versa.

---

## CLI

```
run_scriptreering.bat
run_scriptreering.bat path/to/layout.scriptreering
run_scriptreering.bat --load-ring path/to/layout.scriptreering
run_scriptreering.bat --autoload-rings
run_scriptreering.bat --register-autostart-user path/to/layout.scriptreering
run_scriptreering.bat --unregister-autostart user
run_scriptreering.bat --forest          # start in forest mode (or set SCRIPTREE_FOREST_MODE=1)
run_scriptreering.bat --register-forest-autostart-user path/to/forest.scriptreeforest    # (a84, elevated child)
run_scriptreering.bat --register-forest-autostart-system path/to/forest.scriptreeforest  # (a84, elevated child)
run_scriptreering.bat --unregister-forest-autostart-system                                # (a84, elevated child)
run_scriptreering.bat --new-process     # opt out of single-instance handoff
```

The `--register-forest-autostart-*` / `--unregister-forest-autostart-system` flags (a84) are normally invoked only by the UAC-elevated child that the forest's "Auto-load on startup" menu spawns — not typed by hand. They set `forest_preferences.json`'s `autostart_scope` and recompute the shared `Run` value.

Positional `.scriptreering` paths and the `--load-ring` flag are equivalent — the positional form exists so a file association makes Explorer-double-click on a `.scriptreering` Just Work. Without `--new-process`, a second invocation hands off to the running primary instead of starting its own process.

---

## How cells launch tools

ScripTreeRing never imports V1's `ToolRunnerView` / `MainWindow` directly. When you click a tool in a cell menu, the shell runs:

```
python run_scriptree.py <leaf>.scriptree -standalone [-configuration <name>]
```

…as a fire-and-forget subprocess, using `sys.executable` (no `cmd.exe` shell, no console flash). V1 starts with that argv, opens the standalone runner, and runs the tool. Cell-shell crashes can't take down a running tool, and tool-runner crashes can't take down the cell shell.

The `-standalone` flag is mandatory — without it V1 would open the full editor for any `.scriptree` argument, which is what the **2× left click** path actually wants for `.scriptreetree` files.

For master cells the merged tree is built lazily into `%TEMP%/scriptreering_merged_<hash>.scriptreetree` and that's what's passed to V1.

---

## The forest layer (v0.3.14+)

A **forest** is the top-level container that sits one layer above rings. It owns every ring, tree, and tool on screen, plus an auto-discovery configuration that can populate / refresh the workspace from configurable source folders.

Launch with `run_scriptreeforest.bat` (Windows) / `run_scriptreeforest.py` (Unix) — same Python search and self-healing as the ring launcher; the only difference is it sets `SCRIPTREE_FOREST_MODE=1` so the cell shell builds a `ForestController` before showing any cells.

### What you see

A **regular cell** (same hexagonal shape and default size as any other cell) with a **bright leaf-green stroke** to mark it as the forest. The forest cell IS a master cell — it sits at the center of the workspace, with rings, trees, and individual tools docked to it as members on the surrounding honeycomb slots.

The forest cell behaves like any other ring master:

- Has the same right-click menu (load catalog, settings, transparency, shape, color, etc.)
- Plus a `Forest` submenu at the top with workspace-level actions (save / open / refresh / settings).
- Drag the forest → its members translate with it (existing master-drag behaviour).
- Edge-fold + on-screen reflow + per-member position memory — all the same as a ring master.
- The same hexagon shape and size as every other cell, themed only in stroke colour.

When something gets added to the forest (manually or via auto-discovery), it docks to a free honeycomb slot adjacent to the forest cell, the same way a `.scriptreetree` dropped onto a ring takes the next free slot. Drag it manually afterwards and the position sticks.

### Rings attached to the forest

A ring (master + its own members) attached to the forest is a **two-level group**:

- The ring's **master cell** is a member of the forest.
- The ring's own members are members of the ring's master.

The ring-master's right-click menu carries an extra option: **Leave forest (keep ring intact)**. This severs the forest membership but leaves the ring's own members alone — useful when you want to move the ring out of the workspace temporarily or save it as a separate `.scriptreering`. **Disband group** in the same submenu means the existing thing (tear down the ring's own members), independent of forest membership.

A standalone cell attached directly to the forest gets the same menu it'd have when attached to any ring, but **Leave group** is renamed to **Leave forest** so the action label matches what the user is actually doing.

### First run

When the forest is empty (no `last_forest.scriptreeforest` to autoload), a welcome dialog asks:

* Which folders should I scan for ScripTree files? (default: `ScripTreeApps/`)
* What to add when found: rings, trees, single tools (default: all three)
* When sources change later, should I auto-update? (default: prompt me)

Click **Discover & populate** to one-click everything found, or **Skip** to keep an empty forest.

### Discovery priority rule

For each subdirectory, the walker picks the **highest available layer** and stops descending:

```
folder has a .scriptreering   → load the ring; ignore any sibling .scriptree files
folder has a .scriptreetree   → load the tree; ignore any sibling .scriptree files
folder has only .scriptree(s) → load each tool
folder has none of the above  → recurse into its subdirs
```

This is what makes a "self-contained subdirectory" work — drop a folder containing one `.scriptreering` and a half-dozen `.scriptree` files into `ScripTreeApps`, and the forest sees one ring on its desktop, not seven random tools.

### Excluded items (the "I removed it for a reason" memory)

When you remove a ring/tree/tool from the forest (right-click → Remove from forest), its path goes into the forest's `excluded` list. **Auto-discovery remembers your removal** — the next refresh won't silently re-add it. If you later change your mind, the prompt dialog shows previously-excluded items in a separate section with a checkbox to re-include, or you can manage them from **Forest settings → Manage excluded items**.

The excluded path still **blocks demotion**: an excluded ring keeps its folder from being scanned for individual tools (you removed the ring, not promoted the tool).

### Discovery preview (tree view)

When the prompt-mode discovery dialog appears, each row is shown as an **expandable tree** so you can see what's inside before ticking. A `.scriptreering` row expands into the cells it contains; a `.scriptreetree` row expands into its tools (recursively, through nested folders); a `.scriptree` row is a leaf.

The tree-view is read-only **below** the top-level row — only the top item is checkable; expanding a row is purely informational. Use it to answer "what's in this ring?" before deciding whether to add it.

### Settings dialog → "Save && Run discovery"

Forest settings has three buttons: **Save** (apply settings, close), **Save && Run discovery** (apply settings, then immediately scan the configured folders), and **Cancel**. The Run variant honours the configured update mode — if it's `prompt` you'll see the tree-view diff dialog; if it's `auto` the changes apply silently.

### Selective reflow on master move (v0.3.16)

When you drag the forest cell, members move with it. If the corner of the screen pushes any of them off-screen, **only the off-screen members get reassigned to fresh slots** — the on-screen ones stay exactly where you put them. Pre-v0.3.16 a single off-screen member triggered a full repack of every member, blowing away your manual layout. The new contract is surgical: the user's spread-out arrangement survives every master nudge, and only the cells that genuinely need a new slot get one.

### Update modes

Right-click the forest cell → **Forest settings…** → Update mode:

* **Off** — no automatic discovery; only manual Add and explicit Refresh.
* **Prompt (default)** — on launch and on Refresh, walk the configured roots; if anything changed, show a checkbox dialog with three sections: To add / To remove / Previously excluded. Tick what you want, click Apply.
* **Auto** — same walk, applied silently. Best when you trust the sources to track your intent.

The **Auto-add from ScripTreeApps now** menu entry runs the prompt dialog **regardless of the configured mode** — useful when you keep the mode at "off" but want a one-off discovery.

### Saving

Forests can be saved to `.scriptreeforest` files via right-click → **Save forest as…**. Open multiple forests with **Open forest…** to swap between named workspaces (e.g. `engineering.scriptreeforest`, `dxf-only.scriptreeforest`).

**A default file is always present (by default).** When the forest starts and no `.scriptreeforest` exists at the configured default path, the launcher **creates one** there immediately. Every subsequent change auto-saves to that file (debounced ~250 ms after the last edit), so a process restart always restores your session.

### Launch defaults (v0.3.21+)

Right-click the forest cell → **Forest settings…** → **Launch defaults** section:

- **Load this default forest when no file is specified** — checkbox.  When **on** (factory default), launching the forest with no command-line argument loads the default forest file, creating it empty if missing.  When **off**, the forest starts with a transient in-memory workspace — nothing is auto-saved until you explicitly **Save as…**.
- **Default forest file** — path field with **Browse…**.  Where the fallback points.  Leave blank to use the canonical autoload path (`<APPDATA>/ScripTree/last_forest.scriptreeforest`).  Set to a checked-in workspace file, a USB-stick file, or any `.scriptreeforest` you want as your default.

The preferences live in `<APPDATA>/ScripTree/forest_preferences.json`.  Changes apply at the **next launch**, not the current session.

First-run users see factory defaults: fallback on, path empty — same experience as v0.3.20.

Auto-save is on by default; the controller exposes `set_autosave_enabled(False)` for callers (tests, headless tools) that need disk-quiet mode.  When fallback is off and the forest has never been saved-as, autosave silently no-ops — there's no safe target.  Manual **Save** is the right thing to use when saving to a named `.scriptreeforest` other than the autoload path.

### Why "forest"?

Trees grow out of forests. The forest contains rings (which are arrangements), which contain cells (which can be bound to trees, which contain tools). Naming chained from `.scriptree` → `.scriptreetree` → `.scriptreering` → `.scriptreeforest` keeps the metaphor consistent with the file shape.

---

## Vocabulary (v0.3.17 — pinned by code contract)

- **Associated** — a cell belongs to a group (a ring or the forest). It has `_group_master_id` set to that group's master.
- **Docked** — physically adjacent to another element on a specific edge. Tracked in `_docked_to` / `_dock_partners`.
- **Associatedocked** — both. Belongs to a group AND is on its master's honeycomb slot. Moves rigidly with the master during a master drag.

Cells **don't associate with each other**. They dock to each other; docking causes both to associate with the same ring (a fresh ring if neither was associated, or the existing ring of whichever cell was already grouped).

If you drag an associatedocked cell **away** from its group, it stays associated unless it gets within docking distance of an unassociated element (creating a new ring) or a member of a different group (transferring to that group).

## No-reshift contract (v0.3.17)

**Moving one element does not cause a reshift in the others.** When you dock or undock or close a cell, every other cell in every group keeps its widget position byte-identical to where you placed it. This applies to:

- Dragging a member around within its own group (Case 5 dock).
- A standalone joining a group via dock (Cases 2 / 3).
- A member transferring between groups (Case 4).
- Closing a member (the gap stays; you can manually drag a survivor in).
- Drag-dropping a `.scriptree` / `.scriptreetree` onto a master (only the new cell takes a slot).
- The forest auto-attaching a discovered ring (existing forest members stay put).

The only path that **does** rearrange members is **`_repack_members(fixed=None)`**, used solely by the **fresh-ring spawn** (Case 1) when two standalones first dock. There the two new members get canonical honeycomb slots — they have no prior layout to preserve.

## Home vs temp positions (v0.3.17)

Each member has a **HOME** slot — the ordinary position it should occupy relative to its master. HOME is stored in `master._members[member_id]` and shifts rigidly when the master is dragged.

When the master moves to a corner that pushes a member off-screen, the member's widget gets relocated to a **temp** slot adjacent to other on-screen elements (the "find a temporary space and edge to link onto" rule). HOME is **not** overwritten — the surgical repack only updates the widget position, not `_members[id]`.

When the master returns to a position where HOME is back on-screen, the next reflow pass restores the member to HOME. Members **take precedence for their own ordinary space** over any temp arrangement; only members whose HOME is genuinely off-screen at the master's current position settle for a temp slot.

## Tree auto-discovery (v0.8.0a21+)

A `.scriptreetree`-bound cell can scan its own folder for new `.scriptree` files and offer to add them. Same feature shape as the forest's auto-discovery, scoped to a single tree.

### Right-click → "Tree" submenu

When you right-click a cell bound to a `.scriptreetree`, the context menu gains a **Tree** submenu with four entries:

| Entry | What it does |
|---|---|
| **Refresh from sources** | Run the walker against the tree's `roots`, diff against current leaves, and react per the tree's `update_mode`: `prompt` opens the diff dialog, `auto` applies silently, `off` is a no-op. |
| **Auto-add from this folder now** | Always opens the diff dialog regardless of `update_mode`. Use when you want a one-shot scan + decide even on a tree configured for `off`. |
| **Tree settings…** | Opens the `TreeSettingsDialog`: toggle enabled, edit `roots`, toggle sibling-tree surfacing, pick `update_mode`. "Save && Run discovery" persists then immediately re-scans. |
| **Excluded items…** | Lists every path the user has explicitly removed (the `tree.excluded` list). Each row is selectable; "Re-include selected" drops the chosen paths from `excluded` and persists. |

### First-load chooser

The first time you open a `.scriptreetree` written before this feature existed (or any tree whose `auto_discover` key is missing), a small dialog pops up asking *"How should ScripTree keep this tree in sync with new .scriptree files in its folder?"* — three radio buttons:

- **Prompt** *(default, recommended)* — every load and every Refresh scans; if anything new is found, a diff dialog appears so you can pick what to add.
- **Auto** — silently add everything new on every load. Use when the on-disk folder IS the source of truth.
- **Off** — never scan automatically. The "Refresh from sources" menu entry still works as a one-shot.

Your choice is persisted as an `auto_discover` block in the tree's JSON, so this chooser only fires once per tree. Closing the window without picking is treated as "Prompt" so an accidental close doesn't strand the tree in the "never asked" state forever.

### The diff dialog

Three sections, each a list of rows with checkboxes:

- **Add to tree** — newly-found `.scriptree` files (and, when `include_sibling_trees=true`, sibling `.scriptreetree` files). Default checked.
- **Remove from tree — file no longer on disk** — leaves whose underlying file has vanished. Default checked.
- **Previously excluded — found again** — candidates whose path is in the tree's `excluded` list. Default **unchecked** (you previously said no; we don't undo that silently).

Tick the rows you want. Hit **Apply** to mutate the tree (the JSON is saved automatically) or **Cancel** to discard.

### Walking rule

The walker descends the tree's `roots` (default `["."]`, i.e. the tree's own folder) and applies a boundary rule at every directory:

- If the directory contains another `.scriptreetree`, **stop descending**. That subtree is owned by the other file. When `include_sibling_trees` is on, the boundary `.scriptreetree` itself is surfaced as a candidate sub-tree leaf you can add.
- Otherwise, emit every `.scriptree` file in the directory and recurse into subdirectories.

So a folder shape like:

```
solidworks/
├── solidworks.scriptreetree   ← the tree you're scanning
├── export/
│   ├── dxf.scriptree          ← surfaced as ./export/dxf.scriptree
│   └── step.scriptree         ← surfaced as ./export/step.scriptree
└── subtree/
    ├── owned.scriptreetree    ← surfaced as sibling-tree candidate
    └── owned-tool.scriptree   ← NOT surfaced (owned by owned.scriptreetree)
```

…yields three candidates for the current tree, plus one sibling-tree candidate (the user can decide whether to nest it).

### Recommended folder convention

Authors who want auto-discovery to give the cleanest UX should organise tools as:

```
ScripTreeApps/
└── <program>/                   solidworks, outlook, git, pwsh, …
    ├── <program>.scriptreetree
    ├── <purpose>/               export, cleanup, migration, analysis, …
    │   └── *.scriptree
    └── <purpose>/
        └── *.scriptree
```

With this layout, each `<program>.scriptreetree`'s default `roots: ["."]` auto-discovers every tool in its purpose-subfolders. The hashtag / view-modes system planned for a future release will let the menu re-bucket discovered tools across the program-axis at render time, regardless of how they sit on disk.

Full schema for the `auto_discover` block and the `excluded` list is in [LLM/scriptreetree_format.md](LLM/scriptreetree_format.md).

## Out of scope for v3.x

- 3+ way recursive docking (masters are pairwise; a triangle of cells produces three pairwise masters, not one 3-way master).
- Cross-master ring docking.
- A non-hexagonal/non-square cell shape gallery (circle and other shapes are post-3.x).
