# ScripTree screenshots

Reference captures of the ScripTree v0.8.0a88 UI, rendered by the headless
screenshooter (`screenshooter.py` at the repo root) — each is an off-screen
`QWidget.grab()` of the real widget, never a manual screen-grab, so they stay
reproducible build-over-build.

| File | What it shows | How it was captured |
|---|---|---|
| `forest-cluster.png` | The **forest hub** — the frameless hexagonal cell column docked at the screen edge, with a hover tooltip naming the cell under the cursor ("SolidWorks toolkit"). This is the always-on-top launcher the user interacts with. | `screenshooter.py forest` (composite of master + member cells). |
| `forest-menu.png` | The **forest popup menu** — left-clicking the forest hub opens a filterable list of the top-level workspaces it contains (ScripTree management, SolidWorks toolkit, Outlook Migration, ffmpeg toolkit). | `screenshooter.py menu` against the forest catalog. |
| `solidworks-toolkit-menu.png` | A **single app's tree menu** — the SolidWorks toolkit expanded to its tools and sub-folders (Drawings, Assembly performance, SwDxfExport, BomDrawingViews, …). Illustrates how one `.scriptreetree` renders as a nested, filterable menu. | `screenshooter.py menu` against the toolkit's tree catalog. |
| `dxf-export-suite-tabs.png` | A **tool runner in tabbed (tree) mode** — the DXF Export Suite's four leaf tools as top tabs, with the selected tool's parameter groups (Input / Pipeline stages / BOM source / …) as inner tabs, plus the Configuration row, Command-line preview, Action buttons, and Output pane. This is the in-window view a user sees when launching a tree from a cell. | `screenshooter.py tabs DxfExport.scriptreetree` — and it is the capture that motivated the **v0.8.0a88** screenshooter fix: the headless runner now skips the blocking personal-config prompt and on-open providers, and `_capture` drives a full off-screen layout pass (`WA_DontShowOnScreen`) so the selected inner tab's fields actually render. See `rags/lessons/screenshooter_headless_capture_a88.md`. |

## Regenerating

From the repo root (any of the seven kinds — `cell`, `form`, `tree`, `editor`,
`tabs`, `forest`, `menu`):

```bat
python screenshooter.py tabs path\to\tool.scriptreetree --out docs\screenshots\out.png --width 1060 --height 820
```

The screenshooter renders without ever showing a window on the desktop, so it
is safe to run unattended. Provider-driven fields (e.g. a dropdown populated by
querying SolidWorks) render empty in headless capture — the backing app is not
live — which is expected and documented in the a88 lesson.
