# The cell + ring shell (ScripTreeRing)

ScripTree V3 ships with **two launchers in one installation**:

| Launcher | What it does |
|---|---|
| `run_scriptreering.bat` | Floats one or more **cells** (hexagonal or square) on your desktop. A single click on a cell pops up its tool menu; a double click opens the V1 standalone runner or the full editor depending on what's bound to the cell. Two cells dragged close together **dock** into a *Tree Ring* whose menu merges their tools. Drag a cell away to break the ring. Save and reload layouts as `.scriptreering` files. |
| `run_scriptree.bat` | The classic **V1 editor**. Tool runner, configurations, parser, save/load, the works. ScripTreeRing **calls the V1 editor as a subprocess** for any tool launch — it is a thin desktop launcher; V1 is the toolbox. |

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

| Gesture | Standalone cell | Master / ring cell |
|---|---|---|
| **1× left click** | Toggle the cell's tool menu next to the cell. Click another cell → its menu opens (the previous one closes). Click the same cell again → the menu hides. Picking a tool launches the V1 standalone runner with the tool's default configuration. | Same toggle behaviour, but the popup is the **merged** menu — one sub-folder per member cell, each containing that member's catalog. Members with no catalog bound show a disabled "(no catalog bound)" entry. |
| **2× left click** | Opens V1: the **standalone runner** if the cell is bound to a `.scriptree`, or V1's **full editor** with the tree pre-loaded if the cell is bound to a `.scriptreetree`. | In-process popup with one sub-folder per member (same content as 1× left, but materialised as a regular menu so you can browse without dismissing on outside click). |
| **1× right click** | Cell context menu organised into three sub-menus — **ScripTree ▶**, **Tree Ring ▶**, **Cell ▶** — plus top-level About / Settings / Preferences and role-aware Close / Exit-all entries. See "Right-click menu" below. | Same structure, with role-aware close items ("Close ring (undock all members)", "Close all related (master + members)"). |
| **2× right click** | Opens V1's full editor on the cell's catalog (or a blank editor if no catalog is bound). | Opens V1's full editor on a *merged* `.scriptreetree` — each member becomes a top-level folder. The merged file is regenerated whenever membership changes; same membership = same temp file (V1 can keep it open). If no member has a catalog yet, a placeholder folder is shown so the editor never opens blank. |
| **Drag** | Live snap detection. When the dragged cell's centre falls within `snapDistancePx` (default 18 px) of one of the target's six honeycomb-neighbour slots, a 2 px highlight outlines the intended dock. Release to commit. | (masters don't dock with other masters in v3.x — pairwise only). |
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

## Right-click menu

The right-click menu (v0.2.3 + v0.2.4) is organised into three
sub-folders plus a top-level row:

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

- [`help/LLM/scriptree_format.md`](LLM/scriptree_format.md) — `cell`
  section under top-level shape.
- [`help/LLM/scriptreetree_format.md`](LLM/scriptreetree_format.md)
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

The format is plain UTF-8 JSON; `format = "scriptreering"`, `version = 1`. Full spec lives at [`help/LLM/scriptreering_format.md`](LLM/scriptreering_format.md).

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

---

## CLI

```
run_scriptreering.bat
run_scriptreering.bat path/to/layout.scriptreering
run_scriptreering.bat --load-ring path/to/layout.scriptreering
run_scriptreering.bat --autoload-rings
run_scriptreering.bat --register-autostart-user path/to/layout.scriptreering
run_scriptreering.bat --unregister-autostart user
run_scriptreering.bat --new-process     # opt out of single-instance handoff
```

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

Forests can be saved to `.scriptreeforest` files via right-click → **Save forest as…**. Open multiple forests with **Open forest…** to swap between named workspaces (e.g. `engineering.scriptreeforest`, `dxf-only.scriptreeforest`). The active forest is also auto-saved to `<APPDATA>/ScripTree/last_forest.scriptreeforest` on every meaningful change so a process restart restores your session.

### Why "forest"?

Trees grow out of forests. The forest contains rings (which are arrangements), which contain cells (which can be bound to trees, which contain tools). Naming chained from `.scriptree` → `.scriptreetree` → `.scriptreering` → `.scriptreeforest` keeps the metaphor consistent with the file shape.

---

## Out of scope for v3.x

- 3+ way recursive docking (masters are pairwise; a triangle of cells produces three pairwise masters, not one 3-way master).
- Cross-master ring docking.
- A non-hexagonal/non-square cell shape gallery (circle and other shapes are post-3.x).
