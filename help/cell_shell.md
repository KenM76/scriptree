# The cell + ring shell (ScripTreeRing)

ScripTree V3 ships with **two launchers in one installation**:

| Launcher | What it does |
|---|---|
| `run_scriptreering.bat` | Floats one or more **hexagonal cells** on your desktop. A single click on a cell pops up its tool menu; a double click opens the full editor on the cell's catalog. Two cells dragged close together **dock** into a *ring* whose menu merges their tools. Drag a cell away to break the ring. Save and reload layouts as `.scriptreering` files. |
| `run_scriptree.bat` | The classic **V1 editor**. Tool runner, configurations, parser, save/load, the works. Identical to v0.1.x. |

ScripTreeRing **calls the V1 editor as a subprocess** for any tool launch — it is a thin desktop launcher; V1 is the toolbox. No part of V1's logic is duplicated.

---

## Cell gestures

| Gesture | Standalone cell | Master / ring cell |
|---|---|---|
| **1× left click** | Pop up the cell's tool menu next to the hexagon. Click a tool → V1 standalone runner with the tool's default configuration. | Pop up the **merged** menu (every member's tools, grouped by source). |
| **2× left click** | Open V1's full editor with the cell's `.scriptreetree` loaded. | Open V1's full editor on a *merged* `.scriptreetree` — each member becomes a top-level folder. The merged file is regenerated whenever membership changes; same membership = same temp file (V1 can keep it open). |
| **1× right click** | Cell context menu: Load catalog…, Save Cell Layout As…, Spawn another cell, Cell preferences (size, transparency, shape, orientation, always-on-top), Autostart…, Quit. | Same, plus "Disband ring" (releases members, destroys master). |
| **2× right click** | Same as 2× left for now (open V1 editor). Reserved for a future "edit this cell only" view. | Same. |
| **Drag** | Live snap detection. When the dragged cell's centre falls within `snapDistancePx` (default 18 px) of one of the target's six honeycomb-neighbour slots, a 2 px highlight outlines the intended dock. Release to commit. | (masters don't dock with other masters in v3.0 — pairwise only). |
| **Shake during drag** | Break free from the current ring. The cell un-docks; the master destroys itself if fewer than 2 members remain. | — |

### How the master ("ring" / "tree ring") spawns

When two compatible cells dock (same shape, same orientation, full-edge share), a third cell appears at the midpoint of their shared edge, displaced one hexagon-width *opposite* the centre of mass. That third cell is the **master**. Its menu = the union of every member cell's catalog. Its identity is deterministic: `master:<sorted member id pair>` — so re-docking the same two cells brings back the same master at the same remembered position.

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

Right-click any cell → **Save Ring As…**. The dialog defaults to `~/Documents/ScripTree/rings/`. The saved file captures the master's position + size + appearance, every member's same fields, and each member's `catalog_path`.

### Save a layout from the V1 editor

The editor doesn't render cells, but you can save a **single-hex layout** via **File → Save Cell Layout** (or **Save Cell Layout As…**). The resulting file references the `.scriptreetree` you currently have loaded. Open it later with **File → Open Cell Layout…** (which launches ScripTreeRing on it) or by double-clicking the `.scriptreering` in Explorer once the file association is set up.

---

## Autoload on Windows startup

Right-click any cell → **Autostart → Add this layout to my user startup**. ScripTreeRing writes the path into `<APPDATA>/ScripTree/autoload_rings.json` *and* adds a `Run` registry entry pointing at `run_scriptreering.bat --autoload-rings`. Removing autostart undoes both.

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
```

Positional `.scriptreering` paths and the `--load-ring` flag are equivalent — the positional form exists so a file association makes Explorer-double-click on a `.scriptreering` Just Work.

---

## How cells launch tools

ScripTreeRing never imports V1's `ToolRunnerView` / `MainWindow` directly. When you click a tool in a cell menu, the shell runs:

```
run_scriptree.bat <leaf>.scriptree [-configuration <name>]
```

…as a fire-and-forget subprocess. V1 starts with that argv, opens the standalone runner, and runs the tool. Cell-shell crashes can't take down a running tool, and tool-runner crashes can't take down the cell shell.

The same pattern applies for **double-left-click**: ScripTreeRing spawns `run_scriptree.bat <catalog>.scriptreetree` and lets V1's full editor take over with the tree pre-loaded.

For master cells the merged tree is built lazily into `%TEMP%/scriptreering_merged_<hash>.scriptreetree` and that's what's passed to V1.

---

## Out of scope for v3.0

- 3+ way recursive docking (masters are pairwise; a triangle of cells produces three pairwise masters, not one 3-way master).
- A separate "cell editor" mode for double-right-click (currently equivalent to double-left).
- Cross-master ring docking.
- A non-hexagonal cell shape gallery (square is implemented; circle and other shapes are post-3.0).
