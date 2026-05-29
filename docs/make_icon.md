# `make_icon.py` — the ScripTree icon generator

The script that produces every visual asset ScripTree ships: the app
icon (`scriptree.png` / `.ico` / `.svg`), the cell-shell forest hub
glyph (`icons/icon-forest.{png,svg}`), and the per-concept showcases
in `scriptree/resources/concepts/`.

End users almost never need this. The deployed app already includes
the rendered icons; this script exists for the maintainer (or anyone
preparing a custom build) who wants to **rebuild** the icon set or
**preview a palette tweak** before re-publishing.

Two modes, four formats, ten concepts. This page covers all of it.

---

## Quick reference

| You want to... | Run this |
|---|---|
| See every flag | `python make_icon.py --help` |
| Re-publish the active icon (current look) | `python make_icon.py --trunk-lightness 199 --trunk-width 80` |
| Preview a one-off 2048×2048 PNG | `python make_icon.py --depth 6 --size 2048 --out preview.png` |
| Render a coloured-tree SVG | `python make_icon.py --color "#3B82F6" --svg-out blue.svg` |
| Render PNG + SVG side-by-side | `python make_icon.py --out out.png --svg-out out.svg` |
| Auto-install Pillow if missing | append `--install-deps` |

---

## Modes

`make_icon.py` has TWO mutually exclusive modes. The CLI picks one
based on which flags you pass:

### Full publish (default — no flags, or only publish overrides)

```
python make_icon.py
```

This is what you run when you've bumped `ACTIVE` (the concept named
at the top of `make_icon.py`) or when you want every concept's
showcase up to date. It:

1. Renders every concept's showcase artefacts into
   `scriptree/resources/concepts/<NN_name>.{png,ico,svg}`.
2. Publishes the **active** concept to the app-icon paths at
   `scriptree/resources/scriptree.{png,ico,svg}`.
3. Publishes the same image to `icons/icon-forest.{png,svg}` at the
   project root, so the cell-shell's forest hub master cell falls
   back to a glyph that matches the app icon.

Two flags only affect the full-publish path:

* `--publish-depth N` — override the recursion depth used for **every**
  ICO frame, the showcase PNG, and the SVG. Bypasses the
  size-adaptive ladder. Useful range 1-6.
* `--ico-sizes 16,32,48,256` — override the ICO frame pixel sizes
  (default ladder: 16, 24, 32, 48, 64, 128, 256). Each entry must be
  8-1024 px.

### Single-shot (any of `--depth` / `--size` / `--out` / `--svg-out`)

```
python make_icon.py --depth 6 --size 2048 --out preview.png
python make_icon.py --svg-out icon.svg
python make_icon.py --out out.png --svg-out out.svg
```

This is for **previewing** a palette change before committing, or
producing a one-off render at a custom size. It writes only the
file(s) you ask for — the `concepts/` showcase, the app icon, and
the forest hub glyph are **untouched**. The flags:

* `--depth N` — recursion depth (1-6 useful range).
* `--size PX` — output PNG size in pixels (square). The default
  master canvas is 1024.
* `--out PATH.png` — where to save the PNG. Default when neither
  output flag is given: `./scriptree_custom.png`.
* `--svg-out PATH.svg` — where to save the SVG. Optional; can be set
  on its own or alongside `--out` for both formats from one render.

Combining single-shot flags with `--publish-depth` / `--ico-sizes`
raises an error — those are different intents and you'd silently
lose half your input.

---

## Palette flags (concept 10 only)

The current `ACTIVE` concept (`10_grayscale_leveled_tree`) draws a
hex-fractal tree with a per-level brightness ladder. Four CLI flags
shape that ladder. All four flags default to "off" — when none are
passed you get the stock grayscale look.

| Flag | What it does |
|---|---|
| `--invert` | Flip the brightness ladder. Default: trunk dark, tips light. With `--invert`: trunk light, tips dark. Pair with a light icon background. |
| `--color #RRGGBB` | Re-map the grayscale ladder onto a chosen hue via HLS lightness substitution. The trunk-darker / tips-lighter relationship becomes a ladder of shades-then-tints of that colour. Original ScripTree mint is `#56D6A8`. |
| `--trunk-width N` | Set the overall stroke weight. `N` is the trunk thickness in pixels at the 1024-reference canvas (so `40` is the default, `80` doubles every stroke). Branches + connector circles scale by the same ratio so the fractal's internal proportions hold. |
| `--trunk-lightness N` | Set the trunk's brightness on the 0..255 ladder. The level-step (`14`) is fixed, so pick `N = 255 - max_depth*14` to land the canopy tips on pure white. See the table below. |

### The "tips reach white" formula

The grayscale ladder works like this: the trunk starts at
`base_branch` (default 78), and each successive recursion level
adds `step` (default 14). At `max_depth=4`, that's:

```
trunk → +1 → +2 → +3 → tips (4 levels above trunk)
trunk + 4*step = trunk + 56
```

So if you want **tips at 255 (pure white)**, set `trunk = 199`:

| `--trunk-lightness` | Trunk | L1 | L2 | L3 | Tips |
|---:|---:|---:|---:|---:|---:|
| 78 (default) | 78 | 92 | 106 | 120 | 134 |
| 156 (mid-grey trunk) | 156 | 170 | 184 | 198 | 212 |
| **199** (recommended) | **199** | **213** | **227** | **241** | **255** |
| 220 (clamps early) | 220 | 234 | 248 | 255 | 255 |

The node colours follow the branch ladder up by the same delta (54),
preserving the within-level node-vs-branch contrast wherever you
set the trunk.

With `--invert` set, the assignment flips — the trunk gets the
brightest end of the ladder, the tips the darkest.

### Composing palette flags

The flags compose freely:

```bash
# Blue tree with tips reaching pure white
python make_icon.py --trunk-lightness 199 --color "#3B82F6" --svg-out blue.svg

# Inverted: light trunk, dark tips, on a green hue, thick strokes
python make_icon.py --invert --color "#56D6A8" --trunk-width 96 --out green.png

# Stock grayscale at a custom output path
python make_icon.py --depth 4 --size 1024 --out grey.png
```

Palette flags raise an error on any concept other than 10 —
re-targeting the dispatch would silently drop intent, so the script
fails early instead.

---

## The concept catalog

`make_icon.py` has accumulated ten concepts as the project's visual
direction evolved. Only one is `ACTIVE` at any time (currently
`10_grayscale_leveled_tree`); the rest live as showcase artefacts in
`concepts/` for reference and quick comparisons.

| # | Name | Style | Notes |
|---|---|---|---|
| 01 | `node_graph` | Stylised node-link graph on a dark rounded tile | Mint branches, circular nodes, ">_" prompt at root. The original V1 sketch. |
| 02 | `wood_tree_windows` | Brown tree with an "app windows" canopy | Literal "command-line wrapper" metaphor. PNG/ICO only — no SVG. |
| 03 | `branch_windows` | Concept-01 branches with windows at the tips | Interim hybrid between 01 and 02. |
| 04 | `upright_tree_windows` | Concept 02 trunk re-stood upright | Iteration on 02. |
| 05 | `upright_branch_windows` | Concept 03 with trunk re-stood upright | First concept to also emit `.svg`. |
| 06 | `hex_fractal_tree` | Recursive hex-fractal canopy on a dark tile | Coloured mint with brown trunk + gold ">_" prompt. Size-adaptive ICO ladder. |
| 07 | `glyph_fractal_tree` | Pure-stroke line glyph on a 48-grid | Matches `docs/host-software-icon-style.md`. SVG uses `currentColor`. |
| 08 | `mono_fractal_tree` | Concept 06 with a single mint hue + straight trunk | Drops the brown trunk + gold prompt for monochrome. |
| 09 | `grayscale_fractal_tree` | Grayscale, straight trunk, transparent background | First palette-free fractal; reads on light or dark surfaces. |
| 10 | `grayscale_leveled_tree` | **Current ACTIVE.** Per-level brightness ladder, full junction nodes | All four palette flags apply here. |

To switch the active concept, edit `ACTIVE` near the top of
`make_icon.py` and run a full publish.

### Choosing a concept for a custom render

Concepts 06, 08, 09, 10 share the recursive hex-fractal geometry and
can be requested with `--concept` in single-shot mode:

```
python make_icon.py --concept 08_mono_fractal_tree --depth 4 --out mint.png
```

Without `--concept`, single-shot uses `ACTIVE` (concept 10). The
palette flags only mean anything for concept 10; the others have
their palettes baked in.

---

## Recursion depth and the size-adaptive ladder

`--depth N` (single-shot) and `--publish-depth N` (full publish) both
set the number of recursive splits the canopy shows. Useful range is
1-6:

| Depth | Approx segment count | Reads well at |
|---:|---:|---|
| 1 | 5 | 16-24 px (tiny taskbar icons) |
| 2 | ~13 | 32-48 px |
| 3 | ~29 | 64 px |
| 4 | ~61 | 128+ px (default for the master PNG / SVG) |
| 5 | ~125 | screen previews only — saturates at typical icon sizes |
| 6 | ~253 | offline render targets, big previews |

The **full publish** path uses a size-adaptive ladder for ICO frames
(1 split at 16/24, 2 at 32/48, 3 at 64, 4 at 128+) so small frames
stay legible. `--publish-depth` overrides this and forces every
frame to the same depth.

---

## Output formats

| Format | When you get it |
|---|---|
| PNG | Full publish always emits `scriptree.png` (512 px). Single-shot emits a PNG to `--out` (or the default `./scriptree_custom.png`) unless you set `--svg-out` only. |
| ICO | Full publish only. Multi-frame: 16, 24, 32, 48, 64, 128, 256 px (or the `--ico-sizes` override). |
| SVG | Full publish always emits `scriptree.svg`. Single-shot emits an SVG to `--svg-out` when set. Concepts 06/07/08/09/10 all have SVG renderers; 01-05 mostly don't (concept 05 has one). |

### SVG notes

* The single-shot SVG's `viewBox` size equals `--size` (or 1024 by
  default). The vector scales freely once it's in a viewer; the
  viewBox mostly affects stroke-width units when the file is opened
  with a forced pixel size.
* Concept 07's SVG uses `stroke="currentColor"` so the glyph picks up
  the surrounding text colour — drop it into HTML and tint it via
  CSS. Concept 10's SVG bakes the colours in (it's a ladder, not a
  monochrome).
* SVG output bypasses the `--size` PNG-quality dance (single-shot
  renders the PNG at ≥ 256 then downsamples for clean AA). Vector
  doesn't need it.

---

## Pillow

`make_icon.py` is the only thing in ScripTree that uses Pillow, and
Pillow is not bundled with the deployed app. The first time you run
the script without Pillow installed, you'll see:

```
make_icon.py needs Pillow, which isn't installed in this Python.

  Interpreter: R:\ScripTree\lib\python\python.exe
  Pillow:       ~7 MB download, one-time, ~25 MB on disk.

Install with:
  "R:\ScripTree\lib\python\python.exe" -m pip install Pillow

Or re-run this command with --install-deps to install it now.
```

Two ways forward:

1. Copy the install command, paste it, run the script again.
2. Re-run the original command with `--install-deps` appended. On a
   TTY you get one `[Y/n]` prompt; in non-interactive contexts (the
   GUI runner, CI) the flag itself is treated as consent.

The reason it's not vendored: Pillow is ~25 MB installed and is
useful only for re-rendering icons, which 99 % of ScripTree users
never do. Trading ~25 MB on every install for a one-time
`pip install` on the rare icon-rendering moment is the better deal.

---

## The GUI front-end

The script is wrapped by a `.scriptree` form at:

```
ScripTreeApps/ScripTreeManagement/make_icon.scriptree
```

Open ScripTree → ScripTreeManagement → Branding → "ScripTree icon
generator". The form exposes every flag as a labelled field, in four
collapsible sections:

* **Single-shot render** — Recursion depth, Output size, Output PNG
  path, Output SVG path, Concept.
* **Full publish overrides** — Publish recursion depth, ICO frame
  sizes.
* **Palette** — Invert, Base colour, Overall stroke weight, Trunk
  lightness (all concept-10 only).
* **Dependencies** — Auto-install Pillow if missing.

Leaving every field blank and clicking Run is equivalent to bare
`python make_icon.py` — a full publish.

---

## File layout

```
D:/Dev/ScripTree/
├── scriptree/
│   └── resources/
│       ├── make_icon.py            ← the script
│       ├── concepts/               ← per-concept showcase artefacts
│       │   ├── 06_hex_fractal_tree.{png,ico,svg}
│       │   ├── 10_grayscale_leveled_tree.{png,ico,svg}
│       │   └── ...
│       ├── scriptree.png           ← active app icon (showcase, 512 px)
│       ├── scriptree.ico           ← active app icon (multi-frame)
│       └── scriptree.svg           ← active app icon (vector)
├── icons/
│   ├── icon-forest.png             ← cell-shell forest hub fallback (256 px)
│   └── icon-forest.svg             ← cell-shell forest hub fallback (vector)
└── ScripTreeApps/
    └── ScripTreeManagement/
        └── make_icon.scriptree     ← GUI front-end
```

Of these, only the `concepts/06-10` PNGs/ICOs/SVGs are **untracked**
working artefacts (regenerated each publish). Everything else is
tracked in git.

---

## Common recipes

### Re-publish the active icon with the current look

```bash
python make_icon.py --trunk-lightness 199 --trunk-width 80
```

(This is what's currently shipping — trunk grey 199 → tips white 255,
strokes doubled from the fractal default.)

### Preview a palette change before committing

```bash
python make_icon.py --depth 4 --size 1024 \
    --trunk-lightness 199 --color "#3B82F6" \
    --out /tmp/preview.png
```

Eyeball the PNG; if you like it, run the full-publish command with
the same palette flags to re-render every output.

### Render a single concept-08 icon at 4K for a print mock-up

```bash
python make_icon.py --concept 08_mono_fractal_tree \
    --depth 5 --size 4096 \
    --out /tmp/mint-4k.png
```

### Build a coloured SVG for embedding in HTML

```bash
python make_icon.py --concept 07_glyph_fractal_tree --svg-out /tmp/glyph.svg
# concept 07 uses currentColor — set the CSS color on the parent.
```

---

## See also

* `docs/host-software-icon-style.md` — the line-glyph icon family
  that concept 07 belongs to.
* `scriptree/resources/make_icon.py` — the script's own module
  docstring has a deeper architectural tour.
* `docs/cell_shell.md` — the cell + ring shell that consumes the
  forest hub glyph.
