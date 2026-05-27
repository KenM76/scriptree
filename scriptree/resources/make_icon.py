"""Generate ScripTree's app icons and the cell-shell forest hub glyph.

## What this script is

A self-contained Pillow + raw-SVG generator that produces every icon
asset ScripTree ships:

* the app icon at the resources root —
  ``scriptree.{png,ico,svg}`` (taskbar / About dialog / file
  association); the ``.ico`` is multi-frame with sizes
  ``16/24/32/48/64/128/256`` px;
* the cell-shell forest hub glyph at the project root —
  ``icons/icon-forest.{png,svg}`` (the fallback face for any forest
  master cell that doesn't have a per-forest icon embedded);
* one ``concepts/<NN_name>.{png,ico,svg}`` showcase per design
  concept the project has explored (current count: ten).

The script has TWO modes:

* **Full publish (default, no flags):** re-render every concept into
  ``concepts/``, then publish the ``ACTIVE`` concept to the app-icon
  paths AND the forest-hub paths.  Use this when you've bumped
  ``ACTIVE`` or you want every concept's showcase up to date.
* **Single-shot (``--depth`` / ``--size`` / ``--out`` / ``--svg-out``
  in any combination):** render one PNG and/or SVG of one concept at
  a chosen recursion depth and pixel size, leaving the published
  icons and the ``concepts/`` folder alone.  Use this to preview
  palette tweaks or to drop a one-off custom render somewhere.

End-users never run this; it's a maintainer tool.  Pillow is
deliberately not vendored — see ``_ensure_pillow`` for the lazy
import + ``--install-deps`` prompt that handles the missing-Pillow
case cleanly.

## The concept catalog

Each concept lives in its own section below.  ``ACTIVE`` (set after
the constants block) names the one that's currently shipping.

| Concept                          | Style                                                        | Notes                                                                                                   |
|----------------------------------|--------------------------------------------------------------|---------------------------------------------------------------------------------------------------------|
| ``01_node_graph``                | Stylised node-link graph on a dark rounded tile              | Mint branches, circular nodes, ``>_`` prompt etched at root.  Frozen — the original V1 sketch.          |
| ``02_wood_tree_windows``         | Brown tree whose canopy is a cluster of tiny app windows     | A literal "command-line wrapper" metaphor.  Rasterised only.                                            |
| ``03_branch_windows``            | Concept-01 branches with windows at the tips                 | An interim hybrid between 01 and 02.                                                                    |
| ``04_upright_tree_windows``      | Concept 02 trunk re-stood upright                            | Iteration on 02.                                                                                        |
| ``05_upright_branch_windows``    | Concept 03 with the trunk re-stood upright                   | First concept to also emit ``.svg``.                                                                    |
| ``06_hex_fractal_tree``          | Recursive hex-fractal canopy on a dark tile                  | Size-adaptive ICO depth ladder.  Coloured mint with brown trunk and gold ``>_`` prompt.                 |
| ``07_glyph_fractal_tree``        | Pure-stroke line glyph on a 48 grid, ``currentColor`` SVG    | Matches the bundled facet-icon style (see ``help/host-software-icon-style.md``).                        |
| ``08_mono_fractal_tree``         | Concept 06 with a single mint hue and a straight trunk       | Drops the brown trunk + gold prompt for a monochrome look.                                              |
| ``09_grayscale_fractal_tree``    | Grayscale, straight trunk, transparent background            | First palette-free fractal; reads on light or dark surfaces.                                            |
| ``10_grayscale_leveled_tree``    | **Current ACTIVE.** Per-level brightness ladder + full nodes | Trunk colour matches depth-0 branches, every junction has a connector dot, brightness steps per level.  |

Concepts 06/08/09/10 share recursion geometry and use a
**size-adaptive ICO depth ladder** (1 split at 16-24 px, up to 4 at
128+ px) so small frames stay legible.  Concept 07 uses a tighter
ladder because its line-glyph language gets busy fast.

## Palette flags (concept 10 only)

The grayscale ladder used by ``10_grayscale_leveled_tree`` exposes
four CLI knobs, all defaulting to "off":

* ``--invert`` flips the ladder so the trunk is brightest and the
  tips darkest.  Pair with a light background; the default direction
  is biased for dark backgrounds.
* ``--color #RRGGBB`` re-maps the grayscale ladder onto a chosen hue
  via HLS lightness substitution — trunk-dark / tips-light becomes a
  ladder of shades-then-tints of that colour.  Original ScripTree
  mint is ``#56D6A8``.
* ``--trunk-width N`` sets the overall stroke weight (trunk px at
  the 1024 reference canvas).  Branches + connector circles scale
  by the same ratio so the fractal's internal proportions hold.
* ``--trunk-lightness 0..255`` sets the trunk's brightness on the
  ladder.  Each level brightens by ``step=14``, so pick
  ``255 - max_depth*step`` to land the tips on pure white.  At the
  default ``max_depth=4`` that's ``199`` (199 → 213 → 227 → 241 → 255).

The flags compose: ``--trunk-lightness 199 --color '#3B82F6'``
produces a blue ladder ending in white tips; ``--invert
--trunk-lightness 78`` produces a near-original look with the trunk
near-white and the tips near-black.

## Anatomy of a fractal concept

Each fractal renderer (concepts 06/07/08/09/10) follows the same
recipe:

1. Start with a vertical trunk anchored at ``(0.50, 0.66) → (0.50,
   0.93)`` in fractional canvas coordinates.
2. At the trunk top, anchor a hex fractal.  ``_split_pts`` computes
   the five vertices of one hex split (``v1`` = anchor, ``v2``/``v6``
   = side mid-points, ``v3``/``v5`` = far corners).
3. Recurse on ``v3`` and ``v5`` with side ×``_BRANCH_SCALE``, tilted
   outward by ``±_BRANCH_TILT``, until ``max_depth``.  Stroke widths
   and node radii scale by the same factor each level.
4. The palette is applied per level — either a single colour (06/08)
   or a brightness ladder (09/10).  Concept 10 ALSO places a
   connector dot at every junction, with leaf tips ~1.5× larger so
   the canopy edge stays visually anchored.

## Module layout

* **Imports + lazy-Pillow check** — top.  ``_ensure_pillow()`` runs
  before the real PIL import so a missing-dep case prints a
  copy-paste install command instead of a traceback.
* **Bookkeeping helpers** — ``write_ico_png_frames`` (raw .ico
  writer, used by concepts with per-frame distinct depth),
  ``rounded_mask``, ``vertical_gradient``, ``make_tile``,
  ``draw_window``, ``save_concept``.
* **Concept sections (01..10)** — each section opens with a
  banner comment describing the concept, then defines (where
  applicable): a ``concept_XX`` builder OR a
  ``pil_XX_NAME`` / ``svg_XX_NAME`` renderer pair, and a
  ``save_concept_XX`` publisher.
* **Hex-fractal geometry** — ``_BRANCH_SCALE`` / ``_BRANCH_TILT`` /
  ``_split_pts`` / ``_depth_for_size`` are shared by the fractal
  concepts.
* **Concept 10's palette ladder** — ``_DEFAULT_BASE_BRANCH`` /
  ``_DEFAULT_STEP`` / ``_NODE_BRANCH_OFFSET`` constants,
  ``_grayscale_levels`` builder, ``_collect_fractal`` /
  ``_svg_collect_fractal`` two-pass walkers.
* **CLI** — ``_build_cli`` defines every flag and writes its own
  help text; ``_single_shot`` handles the one-render path;
  ``main`` orchestrates the full-publish path including the
  ``icons/icon-forest`` companion publish.

## Quick reference

Re-publish the active concept with the current "tips reach white" look::

    python make_icon.py --trunk-lightness 199 --trunk-width 80

Single-shot a 2048-px concept-10 PNG at deep recursion::

    python make_icon.py --depth 6 --size 2048 \\
        --out D:/TEMP/preview.png \\
        --trunk-lightness 199

Single-shot a coloured ladder, PNG + SVG together::

    python make_icon.py --depth 4 --size 1024 --color '#3B82F6' \\
        --out /tmp/blue.png --svg-out /tmp/blue.svg

See ``help/make_icon.md`` for the user-facing manual.
"""
from __future__ import annotations

import argparse
import io
import math
import struct
import subprocess
import sys
from pathlib import Path


def _ensure_pillow() -> None:
    """Import-check Pillow, prompting / installing on demand if missing.

    Pillow (~7 MB wheel / ~25 MB installed) is only used by this
    script -- the icon generator.  We deliberately do NOT ship it as
    a vendored runtime dep: bloating every ScripTree install for a
    feature only the maintainer touches isn't worth it.  Instead, we
    lazy-prompt here:

    * Missing + ``--install-deps`` on argv -> ask once, then
      ``pip install Pillow`` into the running interpreter and retry.
    * Missing + no ``--install-deps`` -> print the exact pip command
      tied to ``sys.executable`` so the user can copy-paste, then
      exit cleanly (no traceback).
    * Present -> no-op.

    Runs BEFORE argparse so the missing-dep case surfaces with
    friendly output rather than a bare ``ModuleNotFoundError`` from
    the module-level ``from PIL import ...`` line below.

    Why pre-scan ``sys.argv`` instead of asking argparse: argparse
    runs AFTER the top-level PIL import would fire, so by the time
    argparse could tell us about ``--install-deps`` we've already
    crashed.  A pre-scan dodges that ordering trap.  ``--install-deps``
    is still registered on the argparse parser so ``--help`` documents
    it; argparse just sees it twice (once here, once for the usage
    string).
    """
    try:
        import PIL.Image  # noqa: F401 -- importability check only
        return
    except ImportError:
        pass

    # Exact command, tied to the interpreter currently running so the
    # user can copy-paste and hit the right Python.  When multiple
    # installs are on PATH ("python" can mean any of them), pinning
    # to sys.executable removes all ambiguity.
    install_cmd = f'"{sys.executable}" -m pip install Pillow'

    if "--install-deps" not in sys.argv[1:]:
        print(
            "make_icon.py needs Pillow, which isn't installed in this "
            "Python.\n"
            "\n"
            f"  Interpreter: {sys.executable}\n"
            "  Pillow:       ~7 MB download, one-time, ~25 MB on disk.\n"
            "\n"
            "Install with:\n"
            f"  {install_cmd}\n"
            "\n"
            "Or re-run this command with --install-deps to install it now.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # --install-deps was passed -- confirm once, then install.
    prompt = (
        "make_icon.py needs Pillow (image library, ~7 MB).\n"
        f"  Interpreter: {sys.executable}\n"
        "Install it now? [Y/n] "
    )
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        # Non-TTY parent (GUI runner pipes stdin, CI runners, etc.) --
        # treat the explicit --install-deps flag as consent and proceed
        # without a prompt.  The user opted in by passing the flag.
        answer = "y"
        print("(non-interactive: proceeding)", file=sys.stderr)
    if answer and answer not in ("y", "yes"):
        print("Skipped.", file=sys.stderr)
        raise SystemExit(1)

    print(f"Running: {install_cmd}", file=sys.stderr)
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "Pillow"])
    except subprocess.CalledProcessError as exc:
        print(
            f"\npip install failed (exit {exc.returncode}).  "
            f"Try the manual command above.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # Retry the import -- if pip succeeded but PIL still can't be
    # imported (PATH weirdness, permission issue, broken wheel) we
    # need to fail loudly rather than continue and crash later on a
    # confusing ``NameError: Image is not defined``.
    try:
        import PIL.Image  # noqa: F401
    except ImportError as exc:
        print(
            f"\npip succeeded but Pillow still can't be imported: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print("Pillow installed successfully.", file=sys.stderr)


_ensure_pillow()

from PIL import Image, ImageDraw, ImageFilter


def write_ico_png_frames(path: Path, frames: list[Image.Image]) -> None:
    """Write a Windows .ico whose frames are independent PNG payloads.

    Pillow's ICO writer takes one source image and resamples it to every
    requested size — it has no way to embed per-frame distinct images
    (no ``append_images`` for ICO).  This helper writes the container
    directly so callers can pre-render each frame at its own resolution
    (and, for concept 06, its own recursion depth).

    Frames are stored as PNG payloads inside the ICO, which Windows has
    supported since Vista and which is mandatory for 256-px frames.
    """
    headers = b""
    body    = b""
    offset  = 6 + 16 * len(frames)
    for img in frames:
        w, h = img.size
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()
        bw = 0 if w >= 256 else w   # 0 means 256 in ICO header
        bh = 0 if h >= 256 else h
        headers += struct.pack("<BBBBHHII",
                               bw, bh, 0, 0,    # w, h, palette, reserved
                               1, 32,            # planes, bpp
                               len(data), offset)
        body   += data
        offset += len(data)
    with open(path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(frames)))   # reserved, type=icon, count
        f.write(headers)
        f.write(body)

HERE = Path(__file__).resolve().parent
CONCEPTS = HERE / "concepts"
CONCEPTS.mkdir(exist_ok=True)

MASTER = 1024
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

ACTIVE = "10_grayscale_leveled_tree"   # which concept populates scriptree.{png,ico}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def rounded_mask(size: int, radius: int) -> Image.Image:
    """Return an L-mode alpha mask: a ``size``×``size`` rounded square.

    Used by ``make_tile`` to clip the gradient + halo into the rounded
    "macOS-style" tile shape every legacy concept (01-06, 08) shares.
    """
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return m


def vertical_gradient(size: int, top, bot) -> Image.Image:
    """Return an RGB ``size``×``size`` linear gradient from ``top`` to ``bot``.

    ``top`` and ``bot`` are 3-tuples in ``(R, G, B)``.  The gradient
    direction is screen-y (top of image = ``top``, bottom = ``bot``).
    Built by drawing a one-pixel-wide column and resizing — cheap, and
    accurate enough for the icon scale we're working at.
    """
    col = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        col.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return col.resize((size, size))


def make_tile(size: int, bg_top, bg_bot, halo=None) -> Image.Image:
    """Build the shared "dark rounded square + soft halo" background tile.

    ``bg_top`` / ``bg_bot`` define a vertical gradient that fills the
    tile.  When ``halo=(cx, cy, r, (R,G,B), alpha)`` is supplied an
    additional Gaussian-blurred glow ellipse is composited on top of
    the gradient, clipped to the tile shape.  Returns an RGBA image
    with transparency outside the rounded square.

    Used by concepts 01/02/03/04/05/06/08.  Concepts 07/09/10 skip the
    tile entirely and draw their tree on a transparent canvas.
    """
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = vertical_gradient(size, bg_top, bg_bot).convert("RGBA")
    mask = rounded_mask(size, radius=int(size * 0.22))
    tile.paste(grad, (0, 0), mask)
    if halo:
        cx, cy, r, color, alpha = halo
        glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse(
            (cx - r, cy - r, cx + r, cy + r), fill=(*color, alpha))
        glow = glow.filter(ImageFilter.GaussianBlur(r * 0.5))
        tile = Image.alpha_composite(
            tile, Image.composite(glow, Image.new("RGBA", (size, size), (0, 0, 0, 0)), mask))
    return tile


def draw_window(tile: Image.Image, cx_f, cy_f, w_f, h_f, rot_deg=0,
                fill=(244, 248, 252), bar=(210, 220, 232),
                line=(120, 140, 162),
                dots=((232, 92, 86), (246, 192, 78), (86, 204, 138))):
    """Paste a tiny 'app window' leaf centred on (cx_f, cy_f)."""
    s = tile.width
    w = int(w_f * s); h = int(h_f * s)
    pad = 20
    layer = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))

    # drop shadow
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    r = int(min(w, h) * 0.18)
    ImageDraw.Draw(shadow).rounded_rectangle(
        (pad, pad + 6, pad + w, pad + 6 + h), radius=r, fill=(0, 0, 0, 140))
    shadow = shadow.filter(ImageFilter.GaussianBlur(7))
    layer = Image.alpha_composite(layer, shadow)

    ld = ImageDraw.Draw(layer)
    # body
    ld.rounded_rectangle((pad, pad, pad + w, pad + h), radius=r, fill=fill)
    # title bar
    bar_h = max(6, int(h * 0.26))
    ld.rounded_rectangle((pad, pad, pad + w, pad + bar_h), radius=r, fill=bar)
    ld.rectangle((pad, pad + bar_h - r, pad + w, pad + bar_h), fill=bar)
    # traffic lights
    dot_r = max(2, int(bar_h * 0.28))
    dy = pad + bar_h // 2
    for i, col in enumerate(dots):
        dx = pad + int(bar_h * 0.55) + i * dot_r * 3
        ld.ellipse((dx - dot_r, dy - dot_r, dx + dot_r, dy + dot_r), fill=col)
    # content lines
    content_top = pad + bar_h + max(4, int(h * 0.10))
    line_h = max(2, int(h * 0.08))
    gap = max(3, int(h * 0.10))
    y = content_top
    for wf in (0.80, 0.55, 0.90, 0.45):
        if y + line_h > pad + h - 6:
            break
        ld.rounded_rectangle(
            (pad + int(w * 0.10), y,
             pad + int(w * 0.10) + int(w * 0.72 * wf), y + line_h),
            radius=line_h // 2, fill=line)
        y += line_h + gap

    if rot_deg:
        layer = layer.rotate(rot_deg, resample=Image.BICUBIC, expand=True)

    cx = int(cx_f * s); cy = int(cy_f * s)
    tile.alpha_composite(layer, (cx - layer.width // 2, cy - layer.height // 2))


def save_concept(name: str, master: Image.Image) -> None:
    """Write the simple-path concept artefacts: ``<name>.png`` + ``<name>.ico``.

    For static concepts whose canopy doesn't change with the on-screen
    size (01-05), the master image is resampled to every required
    pixel size with PIL's built-in ICO resizer — fine when the design
    is busy enough to read at every scale.  Concepts 06/07/08/09/10
    bypass this and re-render at each ICO size with a size-appropriate
    recursion depth (see ``save_concept_0N`` for those).
    """
    png_path = CONCEPTS / f"{name}.png"
    ico_path = CONCEPTS / f"{name}.ico"
    master.resize((512, 512), Image.LANCZOS).save(png_path, "PNG")
    frames = [master.resize((n, n), Image.LANCZOS) for n in ICO_SIZES]
    frames[0].save(ico_path, format="ICO", sizes=[(n, n) for n in ICO_SIZES])
    print(f"  {png_path.relative_to(HERE)}")
    print(f"  {ico_path.relative_to(HERE)}")


# ---------------------------------------------------------------------------
# Concept 01 — clean node graph
# ---------------------------------------------------------------------------

def concept_node_graph() -> Image.Image:
    """Concept 01 — clean stylised node-link graph.

    Two layers of branches fan out from a central node above a stubby
    trunk, with circular node highlights at every junction and a gold
    ``>_`` prompt etched into the trunk.  Built on the shared dark
    rounded tile + halo.

    Frozen since v0.1 — the original V1 sketch, kept around as a
    reference for the project's visual language.
    """
    s = MASTER
    # Background tile: dark blue-grey gradient with a soft top-centre halo.
    tile = make_tile(s, (34, 52, 82), (18, 28, 46),
                     halo=(int(s * 0.5), int(s * 0.2), int(s * 0.5),
                           (255, 255, 255), 28))
    d = ImageDraw.Draw(tile)

    # --- Palette --------------------------------------------------------
    accent    = (86, 214, 168)    # mint — branches + leaf nodes
    accent_hi = (176, 246, 214)   # lighter mint — root highlight ring
    prompt    = (255, 214, 102)   # gold — ">_" prompt glyph

    # Fractional-canvas helper: ``px(0.5, 0.5)`` -> centre pixel.
    def px(x, y): return (int(x * s), int(y * s))

    # --- Stroke / node sizing (relative to canvas) ----------------------
    line_w = int(s * 0.028)       # branch stroke
    node_r = int(s * 0.055)       # central root node radius
    leaf_r = int(s * 0.045)       # leaf-node radius

    # --- Branch geometry (fractional canvas coords) ---------------------
    # root: anchor point on the left; t1: first-tier branch tips on the
    # mid-vertical column; t2: second-tier branch tips on the right.
    root = (0.28, 0.26)
    t1   = [(0.58, 0.26), (0.58, 0.50), (0.58, 0.74)]
    t2   = [(0.82, 0.42), (0.82, 0.58)]

    # --- Draw branches: a vertical spine from root + horizontal arms ----
    d.line([px(root[0], root[1]), px(root[0], t1[-1][1])], fill=accent, width=line_w)
    for (bx, by) in t1:
        d.line([px(root[0], by), px(bx, by)], fill=accent, width=line_w)
    mid = t1[1]
    d.line([px(mid[0], mid[1]), px(mid[0], t2[-1][1])], fill=accent, width=line_w)
    for (bx, by) in t2:
        d.line([px(mid[0], by), px(bx, by)], fill=accent, width=line_w)

    # --- Nodes at every branch tip + a haloed root node -----------------
    def disc(p, r, fill):
        cx, cy = px(*p)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)

    for p in t1 + t2:
        disc(p, leaf_r, accent)
    disc(root, node_r + int(s * 0.012), accent_hi)  # outer highlight ring
    disc(root, node_r, (22, 36, 58))                # darker inner fill so ">_" reads

    # --- ">_" prompt centred on the root node ---------------------------
    cx, cy = px(*root)
    stroke = int(s * 0.022)
    arm    = int(node_r * 0.62)
    d.line([(cx - arm // 2, cy - arm), (cx + arm // 2, cy), (cx - arm // 2, cy + arm)],
           fill=prompt, width=stroke, joint="curve")
    return tile


# ---------------------------------------------------------------------------
# Concept 02 — wood tree with window-leaf canopy
# ---------------------------------------------------------------------------

def concept_wood_tree_windows() -> Image.Image:
    """Concept 02 — literal brown tree with an "app windows" canopy.

    A more representational direction: a stylised wood-coloured trunk
    with a tiered foliage canopy made up of tiny rounded-rectangle
    "application windows" (each with title bar + traffic-light dots,
    rendered by ``draw_window``).  Reads as "this is a wrapper for
    other applications."  Rasterised only — no SVG, no size-adaptive
    ladder.
    """
    s = MASTER
    # Background tile: dark teal gradient with a warm halo near top-centre.
    tile = make_tile(s, (22, 54, 66), (9, 22, 30),
                     halo=(int(s * 0.5), int(s * 0.38), int(s * 0.32),
                           (255, 210, 130), 70))

    # --- Canopy backing blobs ------------------------------------------
    # Six soft-blurred green ellipses build a tiered foliage shape that
    # sits BEHIND the trunk + the actual window leaves.  Each entry is
    # ``(cx, cy, r, color, alpha)`` in fractional canvas coords.
    CG_A = (86, 204, 138)   # lighter green — front layer
    CG_B = (42, 150, 102)   # darker green  — back layer
    canopy = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    cd = ImageDraw.Draw(canopy)
    for (cx, cy, r, color, a) in [
        (0.50, 0.38, 0.30, CG_B, 220),    # central back blob
        (0.36, 0.34, 0.20, CG_A, 230),    # left  front blob
        (0.64, 0.34, 0.20, CG_A, 230),    # right front blob
        (0.50, 0.22, 0.19, CG_A, 230),    # top   front blob
        (0.30, 0.46, 0.16, CG_B, 220),    # lower-left  back blob
        (0.70, 0.46, 0.16, CG_B, 220),    # lower-right back blob
    ]:
        cx, cy, r = int(cx * s), int(cy * s), int(r * s)
        cd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*color, a))
    canopy = canopy.filter(ImageFilter.GaussianBlur(s * 0.008))
    tile = Image.alpha_composite(tile, canopy)
    d = ImageDraw.Draw(tile)

    # --- Palette --------------------------------------------------------
    TRUNK    = (138, 92, 46)    # warm brown
    TRUNK_HI = (190, 134, 74)   # lighter brown highlight stripe
    PROMPT   = (252, 220, 128)  # gold ">_" glyph

    def px(x, y): return (int(x * s), int(y * s))

    # --- Trunk: tapered polygon + lighter highlight stripe + base flare -
    # Trunk top y=0.48, base y=0.88; slight outward taper at the base.
    d.polygon([px(0.47, 0.48), px(0.53, 0.48), px(0.56, 0.88), px(0.44, 0.88)],
              fill=TRUNK)
    d.polygon([px(0.475, 0.48), px(0.495, 0.48), px(0.475, 0.88), px(0.455, 0.88)],
              fill=TRUNK_HI)

    # Two quarter-circle "root flare" wedges where the trunk meets the
    # ground line.  ``dx=-1`` is the left wedge, ``dx=+1`` the right.
    base_y = int(0.88 * s)
    for dx in (-1, 1):
        cx = int((0.50 + dx * 0.06) * s)
        r = int(s * 0.05)
        d.pieslice((cx - r, base_y - r, cx + r, base_y + r),
                   0 if dx > 0 else 90, 90 if dx > 0 else 180, fill=TRUNK)

    # --- Three branch arms reaching from the trunk into the canopy ------
    branch_w = int(s * 0.028)
    for (x2, y2) in [(0.30, 0.48), (0.70, 0.48), (0.50, 0.30)]:
        d.line([px(0.50, 0.55), px(x2, y2)], fill=TRUNK, width=branch_w)

    # --- ">_" prompt etched into the trunk ------------------------------
    cx, cy = px(0.50, 0.70)
    arm    = int(s * 0.035)
    stroke = int(s * 0.018)
    d.line([(cx - arm, cy - arm), (cx, cy), (cx - arm, cy + arm)],
           fill=PROMPT, width=stroke, joint="curve")
    under_w = int(s * 0.07)
    d.rounded_rectangle((cx + int(s * 0.012), cy + arm - stroke // 2,
                         cx + int(s * 0.012) + under_w, cy + arm + stroke // 2),
                        radius=stroke // 2, fill=PROMPT)

    # --- Window leaves (tiny "app windows" with traffic-light dots) -----
    # Six windows scattered through the canopy, rotated slightly for a
    # hand-placed feel.  ``draw_window(tile, cx, cy, w, h, rot_deg)`` —
    # all coords/dims fractional.
    draw_window(tile, 0.32, 0.34, 0.24, 0.22, rot_deg=-10)
    draw_window(tile, 0.68, 0.34, 0.24, 0.22, rot_deg=10)
    draw_window(tile, 0.50, 0.22, 0.26, 0.20, rot_deg=-3)
    draw_window(tile, 0.30, 0.52, 0.20, 0.18, rot_deg=-18)
    draw_window(tile, 0.70, 0.52, 0.20, 0.18, rot_deg=18)
    draw_window(tile, 0.50, 0.42, 0.30, 0.26, rot_deg=0)
    return tile


# ---------------------------------------------------------------------------
# Concept 03 — concept-01 branches, concept-02 window leaves
# ---------------------------------------------------------------------------

def concept_branch_windows() -> Image.Image:
    """Concept 03 — node-graph branches (from 01) with windows at the tips.

    A hybrid that keeps concept 01's branching geometry but replaces
    its terminal circular nodes with concept 02's tiny app-window
    leaves.  Reads as "node-tree wrapping app processes."  Was the
    working favourite for a stretch.
    """
    s = MASTER
    # Same dark blue-grey tile + halo as concept 01.
    tile = make_tile(s, (34, 52, 82), (18, 28, 46),
                     halo=(int(s * 0.5), int(s * 0.2), int(s * 0.5),
                           (255, 255, 255), 28))
    d = ImageDraw.Draw(tile)

    # --- Palette --------------------------------------------------------
    accent    = (86, 214, 168)    # mint — branches
    accent_hi = (176, 246, 214)   # lighter mint — elbow highlights + root halo
    prompt    = (255, 214, 102)   # gold — ">_" glyph

    def px(x, y): return (int(x * s), int(y * s))

    # --- Stroke / node sizing -------------------------------------------
    line_w = int(s * 0.028)
    node_r = int(s * 0.055)

    # --- Branch layout --------------------------------------------------
    # Root at left-centre, three branches fanning to the right.  Each
    # branch terminates in a window-leaf.  The middle branch also has
    # a short sub-spine with two secondary window-leaves.
    root = (0.18, 0.50)
    t1   = [(0.50, 0.22), (0.50, 0.50), (0.50, 0.78)]
    t2   = [(0.80, 0.36), (0.80, 0.64)]  # secondaries off middle branch

    # Vertical spine from root
    d.line([px(root[0], t1[0][1]), px(root[0], t1[-1][1])],
           fill=accent, width=line_w)
    # Connector from root-point into spine (keeps the root node centred)
    d.line([px(root[0], root[1]), px(root[0], root[1])],
           fill=accent, width=line_w)

    # Horizontal branches out to tier-1 tips
    for (bx, by) in t1:
        d.line([px(root[0], by), px(bx, by)], fill=accent, width=line_w)

    # Secondary spine off the middle tier-1 branch
    mid = t1[1]
    d.line([px(mid[0], t2[0][1]), px(mid[0], t2[-1][1])],
           fill=accent, width=line_w)
    for (bx, by) in t2:
        d.line([px(mid[0], by), px(bx, by)], fill=accent, width=line_w)

    # Small accent nodes where branches meet (visually anchors each elbow)
    for p in t1:
        cx, cy = px(p[0] - 0.00, p[1])  # at the elbow (on the spine)
    small_r = int(s * 0.018)
    for (bx, by) in t1:
        cx, cy = px(root[0], by)
        d.ellipse((cx - small_r, cy - small_r, cx + small_r, cy + small_r), fill=accent_hi)
    for (bx, by) in t2:
        cx, cy = px(mid[0], by)
        d.ellipse((cx - small_r, cy - small_r, cx + small_r, cy + small_r), fill=accent_hi)

    # Window-leaves at branch tips
    leaf_w, leaf_h = 0.22, 0.19
    draw_window(tile, t1[0][0] + 0.05, t1[0][1], leaf_w, leaf_h, rot_deg=-6)
    draw_window(tile, t1[2][0] + 0.05, t1[2][1], leaf_w, leaf_h, rot_deg=6)
    # Secondary tips (smaller, off to the right)
    small_w, small_h = 0.18, 0.16
    draw_window(tile, t2[0][0] + 0.04, t2[0][1], small_w, small_h, rot_deg=-4)
    draw_window(tile, t2[1][0] + 0.04, t2[1][1], small_w, small_h, rot_deg=4)

    # Root node with ">" prompt — the "script" half of ScripTree
    disc_r = node_r + int(s * 0.018)
    cx, cy = px(*root)
    d.ellipse((cx - disc_r, cy - disc_r, cx + disc_r, cy + disc_r), fill=accent_hi)
    d.ellipse((cx - node_r, cy - node_r, cx + node_r, cy + node_r), fill=(22, 36, 58))

    stroke = int(s * 0.022)
    arm = int(node_r * 0.62)
    d.line([(cx - arm // 2, cy - arm), (cx + arm // 2, cy), (cx - arm // 2, cy + arm)],
           fill=prompt, width=stroke, joint="curve")
    return tile


# ---------------------------------------------------------------------------
# Concept 04 — upright wooden tree with app-window leaves
# ---------------------------------------------------------------------------

def concept_upright_tree_windows() -> Image.Image:
    """Concept 02's wooden trunk with concept 03's window-leaves, but
    oriented like a real tree — trunk rising from the base, branches
    reaching up into a canopy of four app windows."""
    s = MASTER
    tile = make_tile(s, (22, 54, 66), (9, 22, 30),
                     halo=(int(s * 0.5), int(s * 0.32), int(s * 0.34),
                           (255, 210, 130), 60))
    d = ImageDraw.Draw(tile)

    TRUNK    = (138, 92, 46)
    TRUNK_HI = (190, 134, 74)
    PROMPT   = (252, 220, 128)
    NODE     = (232, 184, 110)

    def px(x, y): return (int(x * s), int(y * s))

    # --- Trunk (tapered, highlighted) --------------------------------------
    trunk_top_y  = 0.60
    trunk_base_y = 0.92
    d.polygon([
        px(0.465, trunk_top_y), px(0.535, trunk_top_y),
        px(0.575, trunk_base_y), px(0.425, trunk_base_y),
    ], fill=TRUNK)
    # Highlight stripe
    d.polygon([
        px(0.470, trunk_top_y), px(0.490, trunk_top_y),
        px(0.470, trunk_base_y), px(0.450, trunk_base_y),
    ], fill=TRUNK_HI)
    # Root flare
    base_y = int(trunk_base_y * s)
    for dx in (-1, 1):
        cx = int((0.50 + dx * 0.075) * s)
        r = int(s * 0.055)
        d.pieslice((cx - r, base_y - r, cx + r, base_y + r),
                   0 if dx > 0 else 90, 90 if dx > 0 else 180, fill=TRUNK)

    # --- Branches (upward fork pattern) ------------------------------------
    branch_w = int(s * 0.040)
    tip_w    = int(s * 0.028)

    fork = (0.50, 0.60)
    main_L = (0.30, 0.40)
    main_R = (0.70, 0.40)
    tip_LL = (0.17, 0.23)
    tip_LR = (0.40, 0.19)
    tip_RL = (0.60, 0.19)
    tip_RR = (0.83, 0.23)

    # Main boughs from the fork
    d.line([px(*fork), px(*main_L)], fill=TRUNK, width=branch_w)
    d.line([px(*fork), px(*main_R)], fill=TRUNK, width=branch_w)
    # Secondary branches to the tips
    d.line([px(*main_L), px(*tip_LL)], fill=TRUNK, width=tip_w)
    d.line([px(*main_L), px(*tip_LR)], fill=TRUNK, width=tip_w)
    d.line([px(*main_R), px(*tip_RL)], fill=TRUNK, width=tip_w)
    d.line([px(*main_R), px(*tip_RR)], fill=TRUNK, width=tip_w)

    # Subtle nodes at the forks to hide the line-join seams
    for p, r in ((fork, int(s * 0.032)),
                 (main_L, int(s * 0.024)),
                 (main_R, int(s * 0.024))):
        cx, cy = px(*p)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=TRUNK)

    # Tiny highlight nubs at branch tips so windows look "pinned" to the wood
    for p in (tip_LL, tip_LR, tip_RL, tip_RR):
        cx, cy = px(*p)
        r = int(s * 0.018)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=NODE)

    # --- ">_" prompt etched into the trunk ---------------------------------
    cx, cy = px(0.495, 0.78)
    arm = int(s * 0.033); stroke = int(s * 0.017)
    d.line([(cx - arm, cy - arm), (cx, cy), (cx - arm, cy + arm)],
           fill=PROMPT, width=stroke, joint="curve")
    under_w = int(s * 0.060)
    d.rounded_rectangle((cx + int(s * 0.010), cy + arm - stroke // 2,
                         cx + int(s * 0.010) + under_w, cy + arm + stroke // 2),
                        radius=stroke // 2, fill=PROMPT)

    # --- Window-leaves at each branch tip ----------------------------------
    leaf_w, leaf_h = 0.26, 0.22
    draw_window(tile, tip_LL[0] + 0.01, tip_LL[1] - 0.02, leaf_w, leaf_h, rot_deg=-10)
    draw_window(tile, tip_LR[0] + 0.00, tip_LR[1] - 0.02, leaf_w, leaf_h, rot_deg=-3)
    draw_window(tile, tip_RL[0] - 0.00, tip_RL[1] - 0.02, leaf_w, leaf_h, rot_deg=3)
    draw_window(tile, tip_RR[0] - 0.01, tip_RR[1] - 0.02, leaf_w, leaf_h, rot_deg=10)

    return tile


# ---------------------------------------------------------------------------
# Concept 05 — concept-03 branch pattern, rotated upright, green branches,
# brown trunk, app-window leaves at tips
# ---------------------------------------------------------------------------

def concept_upright_branch_windows() -> Image.Image:
    """Concept 05 — upright tree with stylised branches + window leaves.

    Combines concept 04's upright wooden trunk with concept 03's
    node-style branches and tiny app-window leaves.  The first concept
    to also ship an SVG (``svg_concept_05``) — the line geometry is
    simple enough to translate cleanly.
    """
    s = MASTER
    tile = make_tile(s, (22, 54, 66), (9, 22, 30),
                     halo=(int(s * 0.5), int(s * 0.28), int(s * 0.36),
                           (255, 210, 130), 55))
    d = ImageDraw.Draw(tile)

    BRANCH    = (86, 214, 168)   # mint — same as concept 01/03
    NODE_HI   = (176, 246, 214)
    TRUNK     = (138, 92, 46)
    TRUNK_HI  = (190, 134, 74)
    PROMPT    = (255, 214, 102)

    def px(x, y): return (int(x * s), int(y * s))

    line_w = int(s * 0.028)
    small_node_r = int(s * 0.020)

    # --- Brown trunk at the base -------------------------------------------
    trunk_top_y  = 0.66
    trunk_base_y = 0.93
    # tapered body
    d.polygon([
        px(0.475, trunk_top_y), px(0.525, trunk_top_y),
        px(0.565, trunk_base_y), px(0.435, trunk_base_y),
    ], fill=TRUNK)
    # highlight stripe
    d.polygon([
        px(0.480, trunk_top_y), px(0.495, trunk_top_y),
        px(0.470, trunk_base_y), px(0.450, trunk_base_y),
    ], fill=TRUNK_HI)
    # root flare
    base_y = int(trunk_base_y * s)
    for dx in (-1, 1):
        cx = int((0.50 + dx * 0.075) * s)
        r = int(s * 0.055)
        d.pieslice((cx - r, base_y - r, cx + r, base_y + r),
                   0 if dx > 0 else 90, 90 if dx > 0 else 180, fill=TRUNK)

    # ">_" prompt etched into the trunk
    cx, cy = px(0.492, 0.80)
    arm = int(s * 0.032); stroke = int(s * 0.017)
    d.line([(cx - arm, cy - arm), (cx, cy), (cx - arm, cy + arm)],
           fill=PROMPT, width=stroke, joint="curve")
    under_w = int(s * 0.055)
    d.rounded_rectangle((cx + int(s * 0.010), cy + arm - stroke // 2,
                         cx + int(s * 0.010) + under_w, cy + arm + stroke // 2),
                        radius=stroke // 2, fill=PROMPT)

    # --- Green branch skeleton (concept-03 pattern, rotated) ---------------
    # Primary crossbar running horizontally where the trunk tops out,
    # three primary verticals rising from it (outer two → large windows,
    # middle → sub-spine). A secondary crossbar higher up carries two
    # smaller verticals that → small windows.
    primary_y    = 0.66
    primary_xL   = 0.22
    primary_xR   = 0.78
    primary_xMid = 0.50

    secondary_y  = 0.38
    secondary_xL = 0.36
    secondary_xR = 0.64

    large_tip_y  = 0.38   # where the outer primary branches stop
    small_tip_y  = 0.18   # where the secondary branches stop

    # Primary crossbar
    d.line([px(primary_xL, primary_y), px(primary_xR, primary_y)],
           fill=BRANCH, width=line_w)
    # Primary outer verticals (to large-window tips)
    d.line([px(primary_xL, primary_y), px(primary_xL, large_tip_y)],
           fill=BRANCH, width=line_w)
    d.line([px(primary_xR, primary_y), px(primary_xR, large_tip_y)],
           fill=BRANCH, width=line_w)
    # Middle vertical continuing up to secondary crossbar
    d.line([px(primary_xMid, primary_y), px(primary_xMid, secondary_y)],
           fill=BRANCH, width=line_w)
    # Secondary crossbar
    d.line([px(secondary_xL, secondary_y), px(secondary_xR, secondary_y)],
           fill=BRANCH, width=line_w)
    # Secondary verticals (to small-window tips)
    d.line([px(secondary_xL, secondary_y), px(secondary_xL, small_tip_y)],
           fill=BRANCH, width=line_w)
    d.line([px(secondary_xR, secondary_y), px(secondary_xR, small_tip_y)],
           fill=BRANCH, width=line_w)

    # Small highlight nodes at all junctions (hides line-join seams and
    # echoes the look of concept 03)
    for p in [
        (primary_xL,   primary_y),
        (primary_xMid, primary_y),
        (primary_xR,   primary_y),
        (secondary_xL, secondary_y),
        (primary_xMid, secondary_y),
        (secondary_xR, secondary_y),
    ]:
        cx, cy = px(*p)
        d.ellipse((cx - small_node_r, cy - small_node_r,
                   cx + small_node_r, cy + small_node_r), fill=NODE_HI)

    # --- Window-leaves at each branch tip ---------------------------------
    leaf_w, leaf_h = 0.24, 0.20
    small_w, small_h = 0.19, 0.17

    # Large outer windows (sit just above the tip, tilted outward slightly)
    draw_window(tile, primary_xL,   large_tip_y - 0.08, leaf_w,  leaf_h, rot_deg=-8)
    draw_window(tile, primary_xR,   large_tip_y - 0.08, leaf_w,  leaf_h, rot_deg=8)
    # Small secondary windows at the top
    draw_window(tile, secondary_xL, small_tip_y - 0.07, small_w, small_h, rot_deg=-5)
    draw_window(tile, secondary_xR, small_tip_y - 0.07, small_w, small_h, rot_deg=5)

    return tile


# ---------------------------------------------------------------------------
# SVG emitter for concept 05 (the active icon)
# ---------------------------------------------------------------------------

def svg_concept_05(size: int = 1024) -> str:
    """Return an SVG string matching ``concept_upright_branch_windows``.

    Coordinates are kept identical to the PIL renderer so the SVG is an
    exact analog of the chosen concept.
    """
    S = size

    BG_TOP   = "#163642"
    BG_BOT   = "#09161E"
    BRANCH   = "#56D6A8"
    NODE_HI  = "#B0F6D6"
    TRUNK    = "#8A5C2E"
    TRUNK_HI = "#BE864A"
    PROMPT   = "#FFD666"
    WIN_FILL = "#F4F8FC"
    WIN_BAR  = "#D2DCE8"
    WIN_LINE = "#788CA2"
    DOT_R    = "#E85C56"
    DOT_Y    = "#F6C04E"
    DOT_G    = "#56CC8A"

    # Everything in fractions of S, then scaled
    def p(f): return f * S
    LW = 0.028 * S       # branch stroke width
    NR = 0.020 * S       # junction dot radius
    R_TILE = 0.22 * S    # background corner radius

    # Branch skeleton coords
    primary_y    = 0.66
    primary_xL   = 0.22
    primary_xR   = 0.78
    primary_xMid = 0.50
    secondary_y  = 0.38
    secondary_xL = 0.36
    secondary_xR = 0.64
    large_tip_y  = 0.38
    small_tip_y  = 0.18

    # Trunk coords
    tt, tb = 0.66, 0.93

    # Prompt coords
    cpx, cpy = 0.492 * S, 0.80 * S
    arm = 0.032 * S
    stroke = 0.017 * S
    under_w = 0.055 * S
    under_x = cpx + 0.010 * S

    # Window builder (as an inline <g>)
    def window(cx_f, cy_f, w_f, h_f, rot_deg):
        w = w_f * S; h = h_f * S
        cx = cx_f * S; cy = cy_f * S
        r = min(w, h) * 0.18
        x0 = -w / 2; y0 = -h / 2
        bar_h = max(6, h * 0.26)
        dot_r = max(2, bar_h * 0.28)
        dots = []
        for i, col in enumerate((DOT_R, DOT_Y, DOT_G)):
            dx = x0 + bar_h * 0.55 + i * dot_r * 3
            dy = y0 + bar_h / 2
            dots.append(f'<circle cx="{dx:.2f}" cy="{dy:.2f}" '
                        f'r="{dot_r:.2f}" fill="{col}"/>')
        # content lines
        content_top = y0 + bar_h + max(4, h * 0.10)
        line_h = max(2, h * 0.08)
        gap = max(3, h * 0.10)
        lines = []
        y = content_top
        for wf in (0.80, 0.55, 0.90, 0.45):
            if y + line_h > y0 + h - 6:
                break
            lx = x0 + w * 0.10
            lw = w * 0.72 * wf
            lines.append(
                f'<rect x="{lx:.2f}" y="{y:.2f}" width="{lw:.2f}" '
                f'height="{line_h:.2f}" rx="{line_h/2:.2f}" '
                f'ry="{line_h/2:.2f}" fill="{WIN_LINE}"/>')
            y += line_h + gap

        # Title bar: rounded rect + square-off rect to make bottom flush
        title_parts = (
            f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{w:.2f}" '
            f'height="{bar_h:.2f}" rx="{r:.2f}" ry="{r:.2f}" fill="{WIN_BAR}"/>'
            f'<rect x="{x0:.2f}" y="{y0 + bar_h - r:.2f}" width="{w:.2f}" '
            f'height="{r:.2f}" fill="{WIN_BAR}"/>'
        )

        return (
            f'<g transform="translate({cx:.2f},{cy:.2f}) rotate({rot_deg})" '
            f'filter="url(#winShadow)">'
            f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{w:.2f}" height="{h:.2f}" '
            f'rx="{r:.2f}" ry="{r:.2f}" fill="{WIN_FILL}"/>'
            + title_parts + "".join(dots) + "".join(lines) +
            '</g>'
        )

    # Root flare: two quarter-circles on left/right at the base
    def root_flare():
        y = tb * S
        r = 0.055 * S
        out = []
        for dx, start, end in ((-0.075, 90, 180), (0.075, 0, 90)):
            cx = (0.50 + dx) * S
            # Build a path for the pie slice
            import math
            a0, a1 = math.radians(start), math.radians(end)
            x0 = cx + r * math.cos(a0); y0 = y - r * math.sin(a0)
            x1 = cx + r * math.cos(a1); y1 = y - r * math.sin(a1)
            out.append(
                f'<path d="M{cx:.2f},{y:.2f} L{x0:.2f},{y0:.2f} '
                f'A{r:.2f},{r:.2f} 0 0 0 {x1:.2f},{y1:.2f} Z" '
                f'fill="{TRUNK}"/>'
            )
        return "\n".join(out)

    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" width="{S}" height="{S}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{BG_TOP}"/>
      <stop offset="1" stop-color="{BG_BOT}"/>
    </linearGradient>
    <radialGradient id="halo" cx="0.5" cy="0.28" r="0.36">
      <stop offset="0" stop-color="#FFD282" stop-opacity="0.35"/>
      <stop offset="1" stop-color="#FFD282" stop-opacity="0"/>
    </radialGradient>
    <clipPath id="tile">
      <rect x="0" y="0" width="{S}" height="{S}" rx="{R_TILE}" ry="{R_TILE}"/>
    </clipPath>
    <filter id="winShadow" x="-20%" y="-20%" width="140%" height="150%">
      <feGaussianBlur in="SourceAlpha" stdDeviation="6"/>
      <feOffset dx="0" dy="6"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.55"/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>

  <g clip-path="url(#tile)">
    <!-- Background -->
    <rect x="0" y="0" width="{S}" height="{S}" fill="url(#bg)"/>
    <rect x="0" y="0" width="{S}" height="{S}" fill="url(#halo)"/>

    <!-- Trunk -->
    <polygon points="{0.475*S:.2f},{tt*S:.2f} {0.525*S:.2f},{tt*S:.2f} {0.565*S:.2f},{tb*S:.2f} {0.435*S:.2f},{tb*S:.2f}" fill="{TRUNK}"/>
    <polygon points="{0.480*S:.2f},{tt*S:.2f} {0.495*S:.2f},{tt*S:.2f} {0.470*S:.2f},{tb*S:.2f} {0.450*S:.2f},{tb*S:.2f}" fill="{TRUNK_HI}"/>
    {root_flare()}

    <!-- ">_" prompt on trunk -->
    <polyline points="{cpx-arm:.2f},{cpy-arm:.2f} {cpx:.2f},{cpy:.2f} {cpx-arm:.2f},{cpy+arm:.2f}"
              fill="none" stroke="{PROMPT}" stroke-width="{stroke:.2f}"
              stroke-linecap="round" stroke-linejoin="round"/>
    <rect x="{under_x:.2f}" y="{cpy+arm-stroke/2:.2f}" width="{under_w:.2f}" height="{stroke:.2f}"
          rx="{stroke/2:.2f}" ry="{stroke/2:.2f}" fill="{PROMPT}"/>

    <!-- Branch skeleton (mint) -->
    <g stroke="{BRANCH}" stroke-width="{LW:.2f}" stroke-linecap="butt">
      <line x1="{p(primary_xL):.2f}" y1="{p(primary_y):.2f}" x2="{p(primary_xR):.2f}" y2="{p(primary_y):.2f}"/>
      <line x1="{p(primary_xL):.2f}" y1="{p(primary_y):.2f}" x2="{p(primary_xL):.2f}" y2="{p(large_tip_y):.2f}"/>
      <line x1="{p(primary_xR):.2f}" y1="{p(primary_y):.2f}" x2="{p(primary_xR):.2f}" y2="{p(large_tip_y):.2f}"/>
      <line x1="{p(primary_xMid):.2f}" y1="{p(primary_y):.2f}" x2="{p(primary_xMid):.2f}" y2="{p(secondary_y):.2f}"/>
      <line x1="{p(secondary_xL):.2f}" y1="{p(secondary_y):.2f}" x2="{p(secondary_xR):.2f}" y2="{p(secondary_y):.2f}"/>
      <line x1="{p(secondary_xL):.2f}" y1="{p(secondary_y):.2f}" x2="{p(secondary_xL):.2f}" y2="{p(small_tip_y):.2f}"/>
      <line x1="{p(secondary_xR):.2f}" y1="{p(secondary_y):.2f}" x2="{p(secondary_xR):.2f}" y2="{p(small_tip_y):.2f}"/>
    </g>

    <!-- Junction dots -->
    <g fill="{NODE_HI}">
      <circle cx="{p(primary_xL):.2f}" cy="{p(primary_y):.2f}" r="{NR:.2f}"/>
      <circle cx="{p(primary_xMid):.2f}" cy="{p(primary_y):.2f}" r="{NR:.2f}"/>
      <circle cx="{p(primary_xR):.2f}" cy="{p(primary_y):.2f}" r="{NR:.2f}"/>
      <circle cx="{p(secondary_xL):.2f}" cy="{p(secondary_y):.2f}" r="{NR:.2f}"/>
      <circle cx="{p(primary_xMid):.2f}" cy="{p(secondary_y):.2f}" r="{NR:.2f}"/>
      <circle cx="{p(secondary_xR):.2f}" cy="{p(secondary_y):.2f}" r="{NR:.2f}"/>
    </g>

    <!-- Window-leaves -->
    {window(primary_xL,   large_tip_y - 0.08, 0.24, 0.20, -8)}
    {window(primary_xR,   large_tip_y - 0.08, 0.24, 0.20,  8)}
    {window(secondary_xL, small_tip_y - 0.07, 0.19, 0.17, -5)}
    {window(secondary_xR, small_tip_y - 0.07, 0.19, 0.17,  5)}
  </g>
</svg>
'''
    return svg


# ---------------------------------------------------------------------------
# Concept 06 — hex-fractal tree
# ---------------------------------------------------------------------------
#
# Geometry brief
# --------------
# At every node the "split" is built from FOUR consecutive sides of a
# regular hexagon whose bottom vertex sits on the top of that node's
# trunk segment:
#
#       V3           V5
#        |           |
#        |   V4      |             (V4 is the hex's top vertex — not drawn,
#        |  /  \     |              shown here just for orientation)
#        | /    \    |
#        V2      V6
#         \      /
#          \    /
#           V1   <-- top of trunk
#
# The drawn 4 sides are V1-V2, V2-V3, V1-V6, V6-V5.  V3 and V5 are the
# new "trunk tops" for the next recursion level, each carrying a smaller
# hex split that tilts further outward.  Side length scales by 0.58
# (≈ 1/φ) per level and the local frame rotates by ±25° per branch, so
# the silhouette opens like a fractal canopy.
#
# Scalability: the recursion depth is chosen from the *rendered* pixel
# size — tiny icons (16/24) get depth 1 so detail survives, large icons
# (128+) get depth 4.
#
# Public entry points:
#   pil_fractal_tree(canvas_size, max_depth) -> Image.Image
#   svg_fractal_tree(canvas_size, max_depth) -> str

_BRANCH_SCALE = 0.58       # side-length ratio per recursion level
_BRANCH_TILT  = 25.0       # degrees the sub-frame tilts outward per level
_SQRT3_2   = math.sqrt(3) / 2


def _depth_for_size(n: int) -> int:
    """Pick recursion depth from the on-screen pixel size."""
    if n <= 24:  return 1
    if n <= 48:  return 2
    if n <= 96:  return 3
    return 4


def _split_pts(anchor, angle_deg, side):
    """Return (v1, v2, v6, v3, v5) for the hex split at ``anchor``.

    The local frame's "up" axis is rotated CW (in screen coords) by
    ``angle_deg``.  ``side`` is the hex's edge length.
    """
    c = math.cos(math.radians(angle_deg))
    s = math.sin(math.radians(angle_deg))
    cx, cy = anchor

    def rot(x, y):
        return (cx + x * c - y * s, cy + x * s + y * c)

    # Local frame is y-up; screen y is down, so "up" becomes -y here.
    h = side * _SQRT3_2
    v1 = anchor
    v2 = rot(-h, -side / 2)
    v6 = rot( h, -side / 2)
    v3 = rot(-h, -3 * side / 2)
    v5 = rot( h, -3 * side / 2)
    return v1, v2, v6, v3, v5


def _pil_subtree(d, anchor, angle_deg, side, depth, max_depth,
                     branch, node_hi, leaf_tip,
                     line_w, node_r, leaf_r):
    """Recursively draw one hex-fractal subtree (PIL, with junction dots).

    Used by concepts 06/08/09 — they all share this geometry, only the
    palette differs (colour-per-concept passed via ``branch`` /
    ``node_hi`` / ``leaf_tip``).  At each level we stroke the four hex
    segments, drop a node circle at every junction, then recurse on
    ``v3`` / ``v5`` with ``side`` × ``_BRANCH_SCALE`` and an outward
    ``±_BRANCH_TILT`` tilt.  At ``max_depth`` the recursion stops and
    leaf-tip discs (larger radius) are drawn at the canopy edge.

    Concept 10 uses ``_collect_fractal`` instead — a two-pass walker
    that lets the renderer draw every line first and every dot
    afterwards, so junction circles always sit on top of the deeper
    levels' branch strokes meeting at the same point.
    """
    v1, v2, v6, v3, v5 = _split_pts(anchor, angle_deg, side)
    d.line([v1, v2], fill=branch, width=line_w)
    d.line([v1, v6], fill=branch, width=line_w)
    d.line([v2, v3], fill=branch, width=line_w)
    d.line([v6, v5], fill=branch, width=line_w)

    # Elbow nodes at the diagonal-to-vertical bend
    for (x, y) in (v2, v6):
        d.ellipse((x - node_r, y - node_r, x + node_r, y + node_r), fill=node_hi)

    if depth < max_depth:
        ns = side * _BRANCH_SCALE
        nlw = max(1, int(round(line_w * _BRANCH_SCALE)))
        nnr = max(1, int(round(node_r * _BRANCH_SCALE)))
        nlr = max(2, int(round(leaf_r * _BRANCH_SCALE)))
        _pil_subtree(d, v3, angle_deg - _BRANCH_TILT, ns,
                         depth + 1, max_depth, branch, node_hi, leaf_tip,
                         nlw, nnr, nlr)
        _pil_subtree(d, v5, angle_deg + _BRANCH_TILT, ns,
                         depth + 1, max_depth, branch, node_hi, leaf_tip,
                         nlw, nnr, nlr)
    else:
        for (x, y) in (v3, v5):
            d.ellipse((x - leaf_r, y - leaf_r, x + leaf_r, y + leaf_r),
                      fill=leaf_tip)


def pil_fractal_tree(canvas_size: int = MASTER, max_depth: int = 4) -> Image.Image:
    """Concept 06 — hex-fractal tree over a dark tile (PIL).

    The "first fractal" concept.  Dark teal background tile with a
    soft warm halo, brown trunk with a gold ``>_`` prompt, and a mint
    hex-fractal canopy with circular junction highlights + leaf-tip
    discs.  ``max_depth`` controls how many recursive splits the
    canopy shows (1-6 useful range; ICO ladder picks per-frame depth).

    Palette is baked in — concept 06 does NOT honour ``--invert`` /
    ``--color`` / ``--trunk-width`` / ``--trunk-lightness``; only
    concept 10 does.
    """
    s = canvas_size
    tile = make_tile(s, (22, 54, 66), (9, 22, 30),
                     halo=(int(s * 0.5), int(s * 0.30), int(s * 0.40),
                           (255, 210, 130), 60))
    d = ImageDraw.Draw(tile)

    BRANCH   = (86, 214, 168)
    NODE_HI  = (176, 246, 214)
    LEAF_TIP = (140, 232, 188)
    TRUNK    = (138, 92, 46)
    TRUNK_HI = (190, 134, 74)
    PROMPT   = (255, 214, 102)

    def px(x, y): return (int(x * s), int(y * s))

    # --- Trunk (same proportions as concept 05) ---------------------------
    trunk_top_y  = 0.66
    trunk_base_y = 0.93
    d.polygon([px(0.475, trunk_top_y), px(0.525, trunk_top_y),
               px(0.565, trunk_base_y), px(0.435, trunk_base_y)], fill=TRUNK)
    d.polygon([px(0.480, trunk_top_y), px(0.495, trunk_top_y),
               px(0.470, trunk_base_y), px(0.450, trunk_base_y)], fill=TRUNK_HI)
    base_y = int(trunk_base_y * s)
    for dx in (-1, 1):
        cx = int((0.50 + dx * 0.075) * s)
        r = int(s * 0.055)
        d.pieslice((cx - r, base_y - r, cx + r, base_y + r),
                   0 if dx > 0 else 90, 90 if dx > 0 else 180, fill=TRUNK)

    # ">_" prompt etched into trunk
    cx, cy = px(0.492, 0.80)
    arm = int(s * 0.032); stroke = int(s * 0.017)
    d.line([(cx - arm, cy - arm), (cx, cy), (cx - arm, cy + arm)],
           fill=PROMPT, width=stroke, joint="curve")
    under_w = int(s * 0.055)
    d.rounded_rectangle((cx + int(s * 0.010), cy + arm - stroke // 2,
                         cx + int(s * 0.010) + under_w, cy + arm + stroke // 2),
                        radius=stroke // 2, fill=PROMPT)

    # --- Hex-fractal canopy ----------------------------------------------
    # Initial side length is sized so a depth-4 tree fits comfortably
    # above the trunk without crashing into the rounded-tile margin.
    initial_side = s * 0.155
    # Stroke and node radii scale with the canvas so the look holds at
    # any rendered pixel size.
    line_w  = max(2, int(round(s * 0.022)))
    node_r  = max(2, int(round(s * 0.014)))
    leaf_r  = max(3, int(round(s * 0.024)))

    trunk_top = (0.50 * s, trunk_top_y * s)
    _pil_subtree(d, trunk_top, angle_deg=0.0, side=initial_side,
                     depth=0, max_depth=max_depth,
                     branch=BRANCH, node_hi=NODE_HI, leaf_tip=LEAF_TIP,
                     line_w=line_w, node_r=node_r, leaf_r=leaf_r)

    # Cap the seam where trunk meets V1 with a node dot
    tx, ty = trunk_top
    cap_r = max(3, int(round(s * 0.022)))
    d.ellipse((tx - cap_r, ty - cap_r, tx + cap_r, ty + cap_r), fill=NODE_HI)

    return tile


# --- SVG emitter -------------------------------------------------------

def _svg_subtree(anchor, angle_deg, side, depth, max_depth,
                     branch, node_hi, leaf_tip,
                     line_w, node_r, leaf_r) -> str:
    """SVG analogue of ``_pil_subtree`` — returns an SVG fragment string.

    Same geometry rules (``_split_pts`` + ``_BRANCH_SCALE`` +
    ``_BRANCH_TILT``), same single-pass walk that draws junction
    circles inline (since SVG document order = z-order, this works
    for concepts 06/08/09 whose junction circles don't overlap deeper
    levels' strokes).  Concept 10 uses ``_svg_collect_fractal``
    instead so its connector dots can be appended LAST and end up on
    top.
    """
    v1, v2, v6, v3, v5 = _split_pts(anchor, angle_deg, side)
    parts = []
    cap = 'stroke-linecap="round"'
    for a, b in ((v1, v2), (v1, v6), (v2, v3), (v6, v5)):
        parts.append(
            f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" '
            f'x2="{b[0]:.2f}" y2="{b[1]:.2f}" '
            f'stroke="{branch}" stroke-width="{line_w:.2f}" {cap}/>')
    for (x, y) in (v2, v6):
        parts.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{node_r:.2f}" fill="{node_hi}"/>')

    if depth < max_depth:
        ns  = side * _BRANCH_SCALE
        nlw = line_w * _BRANCH_SCALE
        nnr = node_r * _BRANCH_SCALE
        nlr = leaf_r * _BRANCH_SCALE
        parts.append(_svg_subtree(v3, angle_deg - _BRANCH_TILT, ns,
                                      depth + 1, max_depth,
                                      branch, node_hi, leaf_tip,
                                      nlw, nnr, nlr))
        parts.append(_svg_subtree(v5, angle_deg + _BRANCH_TILT, ns,
                                      depth + 1, max_depth,
                                      branch, node_hi, leaf_tip,
                                      nlw, nnr, nlr))
    else:
        for (x, y) in (v3, v5):
            parts.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{leaf_r:.2f}" fill="{leaf_tip}"/>')
    return "\n".join(parts)


def svg_fractal_tree(canvas_size: int = 1024, max_depth: int = 4) -> str:
    """Concept 06 as SVG — vector twin of ``pil_fractal_tree``.

    Same dark-tile background, brown trunk with gold ``>_`` prompt,
    mint hex-fractal canopy with junction highlights + leaf tips.
    Embeds the gradient + halo as ``<defs>``/``<linearGradient>``/
    ``<radialGradient>`` and clips the whole composition to a rounded
    rectangle.  ``canvas_size`` sets the viewBox size; the file
    scales freely once it's in a viewer.
    """
    S = canvas_size
    BG_TOP   = "#163642"; BG_BOT  = "#09161E"
    BRANCH   = "#56D6A8"; NODE_HI = "#B0F6D6"; LEAF_TIP = "#8CE8BC"
    TRUNK    = "#8A5C2E"; TRUNK_HI = "#BE864A"; PROMPT  = "#FFD666"

    R_TILE   = 0.22 * S
    trunk_top_y, trunk_base_y = 0.66, 0.93

    # Trunk polygons
    t_body = (f'<polygon points="'
              f'{0.475*S:.2f},{trunk_top_y*S:.2f} '
              f'{0.525*S:.2f},{trunk_top_y*S:.2f} '
              f'{0.565*S:.2f},{trunk_base_y*S:.2f} '
              f'{0.435*S:.2f},{trunk_base_y*S:.2f}" fill="{TRUNK}"/>')
    t_hi   = (f'<polygon points="'
              f'{0.480*S:.2f},{trunk_top_y*S:.2f} '
              f'{0.495*S:.2f},{trunk_top_y*S:.2f} '
              f'{0.470*S:.2f},{trunk_base_y*S:.2f} '
              f'{0.450*S:.2f},{trunk_base_y*S:.2f}" fill="{TRUNK_HI}"/>')

    # Root flare (two quarter pies)
    flare = []
    y0 = trunk_base_y * S
    rf = 0.055 * S
    for dx, start, end in ((-0.075, 90, 180), (0.075, 0, 90)):
        cx = (0.50 + dx) * S
        a0, a1 = math.radians(start), math.radians(end)
        # SVG y-axis is down — sine flipped relative to math convention
        x0 = cx + rf * math.cos(a0); y_a = y0 - rf * math.sin(a0)
        x1 = cx + rf * math.cos(a1); y_b = y0 - rf * math.sin(a1)
        flare.append(
            f'<path d="M{cx:.2f},{y0:.2f} L{x0:.2f},{y_a:.2f} '
            f'A{rf:.2f},{rf:.2f} 0 0 0 {x1:.2f},{y_b:.2f} Z" fill="{TRUNK}"/>')

    # ">_" prompt
    cpx, cpy = 0.492 * S, 0.80 * S
    arm = 0.032 * S; stroke = 0.017 * S
    under_w = 0.055 * S; under_x = cpx + 0.010 * S
    prompt = (
        f'<polyline points="{cpx-arm:.2f},{cpy-arm:.2f} {cpx:.2f},{cpy:.2f} '
        f'{cpx-arm:.2f},{cpy+arm:.2f}" fill="none" stroke="{PROMPT}" '
        f'stroke-width="{stroke:.2f}" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<rect x="{under_x:.2f}" y="{cpy+arm-stroke/2:.2f}" '
        f'width="{under_w:.2f}" height="{stroke:.2f}" '
        f'rx="{stroke/2:.2f}" ry="{stroke/2:.2f}" fill="{PROMPT}"/>'
    )

    # Hex fractal
    trunk_top = (0.50 * S, trunk_top_y * S)
    initial_side = S * 0.155
    line_w = S * 0.022
    node_r = S * 0.014
    leaf_r = S * 0.024
    fractal = _svg_subtree(trunk_top, 0.0, initial_side, 0, max_depth,
                               BRANCH, NODE_HI, LEAF_TIP,
                               line_w, node_r, leaf_r)

    # Cap dot at trunk top
    cap_r = S * 0.022
    cap = (f'<circle cx="{trunk_top[0]:.2f}" cy="{trunk_top[1]:.2f}" '
           f'r="{cap_r:.2f}" fill="{NODE_HI}"/>')

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" width="{S}" height="{S}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{BG_TOP}"/>
      <stop offset="1" stop-color="{BG_BOT}"/>
    </linearGradient>
    <radialGradient id="halo" cx="0.5" cy="0.30" r="0.40">
      <stop offset="0" stop-color="#FFD282" stop-opacity="0.32"/>
      <stop offset="1" stop-color="#FFD282" stop-opacity="0"/>
    </radialGradient>
    <clipPath id="tile">
      <rect x="0" y="0" width="{S}" height="{S}" rx="{R_TILE}" ry="{R_TILE}"/>
    </clipPath>
  </defs>
  <g clip-path="url(#tile)">
    <rect x="0" y="0" width="{S}" height="{S}" fill="url(#bg)"/>
    <rect x="0" y="0" width="{S}" height="{S}" fill="url(#halo)"/>
    {t_body}
    {t_hi}
    {chr(10).join(flare)}
    {prompt}
    {fractal}
    {cap}
  </g>
</svg>
'''


def save_concept_06() -> None:
    """Render concept 06 with size-adaptive recursion depth.

    Each .ico frame is rendered fresh at a high working resolution with
    a depth chosen from the *target* pixel size, then downsampled.  This
    is what gives the file its "fractal scaling" — 16-px frames show one
    split, 256-px frames show four.
    """
    name = "06_hex_fractal_tree"

    # Master PNG (depth 4 at 512 — the showcase size)
    master = pil_fractal_tree(canvas_size=MASTER, max_depth=4)
    png_path = CONCEPTS / f"{name}.png"
    master.resize((512, 512), Image.LANCZOS).save(png_path, "PNG")

    # ICO frames with per-size depth — each size is rendered fresh at a
    # high working resolution with a depth chosen for *that* on-screen
    # size, then downsampled.  PIL's `sizes=` parameter would resample a
    # single source for every frame (defeating the point), so we pass the
    # distinct frames via `append_images=` and let PIL embed each as-is.
    frames = []
    for n in ICO_SIZES:
        depth = _depth_for_size(n)
        work  = max(256, n * 4)
        img   = pil_fractal_tree(canvas_size=work, max_depth=depth)
        frames.append(img.resize((n, n), Image.LANCZOS))
    ico_path = CONCEPTS / f"{name}.ico"
    write_ico_png_frames(ico_path, frames)

    # SVG (depth 4 — vector scales freely; large displays get the full tree)
    svg_path = CONCEPTS / f"{name}.svg"
    svg_path.write_text(svg_fractal_tree(1024, max_depth=4), encoding="utf-8")

    print(f"  {png_path.relative_to(HERE)}")
    print(f"  {ico_path.relative_to(HERE)}  (depths per size: "
          + ", ".join(f"{n}px={_depth_for_size(n)}" for n in ICO_SIZES) + ")")
    print(f"  {svg_path.relative_to(HERE)}")


# ---------------------------------------------------------------------------
# Concept 10 — grayscale hex-fractal tree, full junction dots, no prompt
# ---------------------------------------------------------------------------
#
# Refined from concept 09 based on user feedback:
#
#   * Trunk colour matches the depth-0 branch colour (no longer the
#     darkest tone — the trunk is just a wider continuation of a branch).
#   * No ">_" prompt and no background at all — the file is purely the
#     tree on transparent RGBA.
#   * Every junction now carries a connector dot.  Previously only the
#     diagonal-to-vertical bends (V2 / V6) had dots; the points where
#     one subtree attaches to the next (V3 / V5 of the parent = V1 of
#     the child) were drawn as bare line meetings.  Concept 10 places a
#     dot at every V2 / V6 / V3 / V5 (with V3 / V5 of the deepest level
#     becoming the leaf tips).
#   * Branch and dot colours step *slightly lighter* with each
#     recursion level — the strokes themselves get thinner by the same
#     ``_BRANCH_SCALE`` factor, and a touch more brightness compensates
#     visually so the outermost tips don't fade into the background.

def _parse_hex_color(s: str) -> tuple[int, int, int]:
    """Parse a CSS-style ``#RRGGBB`` (or ``RRGGBB`` / ``#RGB``) to an RGB tuple."""
    s = s.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"expected 6-digit hex colour, got {s!r}")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _colorize_gray(gray: int, base_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Re-map a grayscale luminance onto a chosen hue.

    Keeps the hue and saturation of ``base_rgb``; substitutes the gray
    value as the new HLS lightness.  The ladder of grays therefore
    becomes a ladder of tints/shades of one colour, preserving the
    "trunk dark, tips light" relationship (or the inverted equivalent).
    """
    import colorsys
    r, g, b = base_rgb
    h, _, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    nr, ng, nb = colorsys.hls_to_rgb(h, gray / 255, s)
    return (int(round(nr * 255)), int(round(ng * 255)), int(round(nb * 255)))


_DEFAULT_BASE_BRANCH = 78
_DEFAULT_BASE_NODE   = 132
_DEFAULT_STEP        = 14
# Node-vs-branch offset preserved when ``base_branch`` is overridden
# from the CLI — moving the trunk brightness up by Δ also moves the
# node base up by Δ so the within-level contrast stays the same.
_NODE_BRANCH_OFFSET  = _DEFAULT_BASE_NODE - _DEFAULT_BASE_BRANCH


def _grayscale_levels(max_depth: int,
                      base_branch: int | None = None,
                      base_node:   int | None = None,
                      step:        int = _DEFAULT_STEP,
                      invert:      bool = False,
                      color:       str | None = None,
                      ) -> list[tuple[tuple, tuple]]:
    """Return [(branch_rgb, node_rgb)] for each recursion level 0..max_depth.

    Both branch and node values brighten by ``step`` per level so the
    within-level contrast (node vs branch) stays the same while the
    overall tone climbs toward white at the canopy edge.

    With ``invert=True`` the ladder is flipped — depth 0 (trunk &
    closest-to-trunk branches) ends up *lightest*, the canopy tips
    *darkest*.  Useful when the icon will sit on a light background.

    With ``color="#RRGGBB"`` each gray luminance is re-mapped onto that
    hue via HLS lightness substitution, so the same brightness ladder
    becomes a ladder of tints/shades of the chosen colour.

    ``base_branch`` (None = default 78) sets the trunk's gray value;
    every other level steps up by ``step``.  Pick
    ``255 - max_depth * step`` to land the tips on pure white.
    ``base_node`` (None = follow base_branch + 54) sets the node gray
    value at depth 0.  Both clamp to [0, 255].
    """
    if base_branch is None:
        base_branch = _DEFAULT_BASE_BRANCH
    base_branch = max(0, min(255, int(base_branch)))
    if base_node is None:
        base_node = max(0, min(255, base_branch + _NODE_BRANCH_OFFSET))
    else:
        base_node = max(0, min(255, int(base_node)))
    base_rgb = _parse_hex_color(color) if color else None
    out = []
    for L in range(max_depth + 1):
        level_for_grad = (max_depth - L) if invert else L
        bv = min(255, base_branch + level_for_grad * step)
        nv = min(255, base_node   + level_for_grad * step)
        if base_rgb is not None:
            out.append((_colorize_gray(bv, base_rgb),
                        _colorize_gray(nv, base_rgb)))
        else:
            out.append(((bv, bv, bv), (nv, nv, nv)))
    return out


def _collect_fractal(anchor, angle_deg, side, depth, max_depth,
                         levels, line_w, node_r,
                         lines: list, dots: list) -> None:
    """Walk the fractal once and append draw commands to ``lines`` / ``dots``.

    Separating collection from rendering lets the caller draw every line
    first and every dot afterwards — so the junction circles always sit
    on top, never half-covered by a deeper level's branch stroke
    starting from the same point.
    """
    branch, node = levels[depth]
    v1, v2, v6, v3, v5 = _split_pts(anchor, angle_deg, side)

    for a, b in ((v1, v2), (v1, v6), (v2, v3), (v6, v5)):
        lines.append((a, b, branch, line_w))

    for p in (v2, v6):
        dots.append((p, node_r, node))

    if depth < max_depth:
        for p in (v3, v5):
            dots.append((p, node_r, node))
        ns  = side * _BRANCH_SCALE
        nlw = max(1, int(round(line_w * _BRANCH_SCALE)))
        nnr = max(1, int(round(node_r * _BRANCH_SCALE)))
        _collect_fractal(v3, angle_deg - _BRANCH_TILT, ns,
                             depth + 1, max_depth, levels, nlw, nnr,
                             lines, dots)
        _collect_fractal(v5, angle_deg + _BRANCH_TILT, ns,
                             depth + 1, max_depth, levels, nlw, nnr,
                             lines, dots)
    else:
        tip_r = max(node_r + 1, int(round(node_r * 1.5)))
        for p in (v3, v5):
            dots.append((p, tip_r, node))


def pil_grayscale_leveled_tree(canvas_size: int = MASTER,
                               max_depth: int = 4,
                               invert: bool = False,
                               color: str | None = None,
                               trunk_width: int | None = None,
                               trunk_lightness: int | None = None,
                               ) -> Image.Image:
    """Render the grayscale fractal-tree icon onto a transparent canvas.

    ``trunk_width`` (optional) sets the overall stroke weight for the
    whole tree.  It names the trunk thickness (in pixels at the
    1024-reference canvas, scaled proportionally for other sizes), but
    the canopy branches and the connector circles scale together with
    it so the fractal proportions are preserved.  Passing
    ``trunk_width=80`` doubles every stroke — trunk + every branch
    level + every junction node — relative to the default 40 px trunk
    at the 1024 canvas.

    ``trunk_lightness`` (optional, 0..255) sets the brightness of the
    trunk in the grayscale ladder.  Each successive recursion level
    brightens by the same fixed ``step`` (default 14), so picking
    ``trunk_lightness = 255 - max_depth * step`` lands the canopy tips
    on pure white.  At default ``max_depth=4`` and ``step=14``, that's
    ``trunk_lightness=199``.  Node colours move up by the same delta
    as the branches so the within-level node-vs-branch contrast is
    preserved.  Inverted ladders flip the assignment (trunk gets the
    highest, tips the lowest).
    """
    s = canvas_size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)

    levels = _grayscale_levels(max_depth, invert=invert, color=color,
                               base_branch=trunk_lightness)
    trunk_color = levels[0][0]          # same as depth-0 branch
    cap_color   = levels[0][1]          # depth-0 node colour at the seam

    # Stroke widths follow the fractal's scaling sequence.  The trunk
    # is the "level −1" width by default (one step up from the depth-0
    # branch stroke).  ``trunk_width`` overrides BOTH the trunk width
    # AND scales the canopy strokes + connector circles by the same
    # factor — set the trunk to N px and everything below follows
    # proportionally (so the user can match a different icon family's
    # reference weight without breaking the fractal's internal ratios).
    line_w  = max(2, int(round(s * 0.022)))
    node_r  = max(2, int(round(s * 0.014)))
    if trunk_width is not None:
        trunk_w = max(2, int(round(trunk_width * (s / 1024.0))))
        # Default trunk thickness at the 1024 canvas: round(23/_BRANCH_SCALE).
        # The override's ratio to that default is the global scale factor
        # we apply to line_w + node_r so trunk / branch / node geometry
        # stays proportional.
        default_trunk_1024 = max(3, int(round(
            int(round(1024 * 0.022)) / _BRANCH_SCALE)))
        scale = trunk_width / default_trunk_1024
        line_w = max(2, int(round(line_w * scale)))
        node_r = max(2, int(round(node_r * scale)))
    else:
        trunk_w = max(3, int(round(line_w / _BRANCH_SCALE)))

    # Straight trunk: stadium-shape, untapered, same colour as branches
    cx_px = int(0.50 * s)
    ty0   = int(0.66 * s)
    ty1   = int(0.93 * s)
    half  = trunk_w // 2
    d.rounded_rectangle((cx_px - half, ty0, cx_px + half, ty1),
                        radius=half, fill=trunk_color)

    # Hex-fractal canopy — collect first, then draw all lines, then all
    # dots, so every junction circle sits on top of the strokes that
    # meet at it.  ``line_w`` and ``node_r`` were already computed above
    # (scaled together with ``trunk_w`` when the user supplied a
    # ``trunk_width`` override; default fractal-ladder values otherwise).
    initial_side = s * 0.155
    trunk_top = (0.50 * s, 0.66 * s)
    lines: list = []
    dots:  list = []
    _collect_fractal(trunk_top, angle_deg=0.0, side=initial_side,
                         depth=0, max_depth=max_depth, levels=levels,
                         line_w=line_w, node_r=node_r,
                         lines=lines, dots=dots)
    for (a, b, color, w) in lines:
        d.line([a, b], fill=color, width=w)
    for ((x, y), r, color) in dots:
        d.ellipse((x - r, y - r, x + r, y + r), fill=color)

    # Seam dot at trunk top / V1 (drawn last so it caps the seam too).
    # cap_r must grow with the trunk so a wide trunk doesn't poke out
    # from under the cap.  Defaults to the canvas-derived value; bumps
    # up to (trunk_w / 2 + small margin) whenever that's bigger.
    tx, ty = trunk_top
    cap_r_default = max(3, int(round(s * 0.022)))
    cap_r = max(cap_r_default, (trunk_w + 4) // 2)
    d.ellipse((tx - cap_r, ty - cap_r, tx + cap_r, ty + cap_r), fill=cap_color)

    return img


# --- SVG emitter --------------------------------------------------------

def _svg_collect_fractal(anchor, angle_deg, side, depth, max_depth,
                     levels, line_w, node_r,
                     line_parts: list, dot_parts: list) -> None:
    """SVG analog of ``_collect_fractal`` — separate line/dot streams."""
    branch_rgb, node_rgb = levels[depth]
    branch = f'rgb({branch_rgb[0]},{branch_rgb[1]},{branch_rgb[2]})'
    node   = f'rgb({node_rgb[0]},{node_rgb[1]},{node_rgb[2]})'

    v1, v2, v6, v3, v5 = _split_pts(anchor, angle_deg, side)
    for a, b in ((v1, v2), (v1, v6), (v2, v3), (v6, v5)):
        line_parts.append(
            f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" '
            f'x2="{b[0]:.2f}" y2="{b[1]:.2f}" '
            f'stroke="{branch}" stroke-width="{line_w:.2f}" '
            f'stroke-linecap="round"/>')
    for (x, y) in (v2, v6):
        dot_parts.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{node_r:.2f}" fill="{node}"/>')

    if depth < max_depth:
        for (x, y) in (v3, v5):
            dot_parts.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{node_r:.2f}" fill="{node}"/>')
        ns  = side * _BRANCH_SCALE
        nlw = line_w * _BRANCH_SCALE
        nnr = node_r * _BRANCH_SCALE
        _svg_collect_fractal(v3, angle_deg - _BRANCH_TILT, ns, depth + 1, max_depth,
                         levels, nlw, nnr, line_parts, dot_parts)
        _svg_collect_fractal(v5, angle_deg + _BRANCH_TILT, ns, depth + 1, max_depth,
                         levels, nlw, nnr, line_parts, dot_parts)
    else:
        tip_r = max(node_r + 0.5, node_r * 1.5)
        for (x, y) in (v3, v5):
            dot_parts.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{tip_r:.2f}" fill="{node}"/>')


def svg_grayscale_leveled_tree(canvas_size: int = 1024,
                               max_depth: int = 4,
                               invert: bool = False,
                               color: str | None = None,
                               trunk_width: int | None = None,
                               trunk_lightness: int | None = None) -> str:
    """Concept 10 as SVG — vector twin of ``pil_grayscale_leveled_tree``.

    Honours the same four palette knobs as the PIL version (``invert``
    / ``color`` / ``trunk_width`` / ``trunk_lightness``).  Returns a
    plain SVG string with a transparent background — no tile, no
    halo, no gradient — so the same icon reads cleanly on light or
    dark surfaces depending on which way the brightness ladder is
    pointing.  ``canvas_size`` sets the viewBox + internal coordinate
    space; the file scales freely once it's in a viewer.
    """
    S = canvas_size
    levels = _grayscale_levels(max_depth, invert=invert, color=color,
                               base_branch=trunk_lightness)
    trunk_rgb, cap_rgb = levels[0]
    trunk_color = f'rgb({trunk_rgb[0]},{trunk_rgb[1]},{trunk_rgb[2]})'
    cap_color   = f'rgb({cap_rgb[0]},{cap_rgb[1]},{cap_rgb[2]})'

    # Stroke / node sizing — mirrors ``pil_grayscale_leveled_tree``:
    # ``trunk_width`` (when given) sets the trunk in 1024-canvas px AND
    # scales the canopy / connector geometry by the same ratio so all
    # stroke weights stay proportional.
    line_w = S * 0.022
    node_r = S * 0.014
    if trunk_width is not None:
        trunk_w = trunk_width * (S / 1024.0)
        default_trunk_1024 = (1024 * 0.022) / _BRANCH_SCALE
        scale = trunk_width / default_trunk_1024
        line_w *= scale
        node_r *= scale
    else:
        trunk_w = line_w / _BRANCH_SCALE

    cx       = 0.50 * S
    ty0, ty1 = 0.66 * S, 0.93 * S
    trunk = (f'<rect x="{cx-trunk_w/2:.2f}" y="{ty0:.2f}" '
             f'width="{trunk_w:.2f}" height="{ty1-ty0:.2f}" '
             f'rx="{trunk_w/2:.2f}" ry="{trunk_w/2:.2f}" fill="{trunk_color}"/>')

    trunk_top    = (0.50 * S, 0.66 * S)
    initial_side = S * 0.155
    line_parts: list = []
    dot_parts:  list = []
    _svg_collect_fractal(trunk_top, 0.0, initial_side, 0, max_depth,
                     levels, line_w, node_r, line_parts, dot_parts)
    # Seam-cap radius matches the PIL renderer's logic — grow with the
    # trunk so a wide trunk doesn't poke out from under the cap.
    cap_r = max(S * 0.022, (trunk_w + 4) / 2.0)
    cap = (f'<circle cx="{trunk_top[0]:.2f}" cy="{trunk_top[1]:.2f}" '
           f'r="{cap_r:.2f}" fill="{cap_color}"/>')

    # Lines first, then dots — guarantees every junction circle sits on
    # top of the strokes that meet at it.
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" width="{S}" height="{S}">
  {trunk}
  {chr(10).join(line_parts)}
  {chr(10).join(dot_parts)}
  {cap}
</svg>
'''


def save_concept_10() -> None:
    """Render concept 10's showcase artefacts into ``concepts/``.

    Writes ``10_grayscale_leveled_tree.{png,ico,svg}`` with the
    size-adaptive ICO depth ladder (1 split at 16-24 px, 4 at 128+).
    Mirrors ``save_concept_06`` but for concept 10's geometry +
    palette ladder.  All palette knobs default to "off" here —
    user-driven palette overrides flow through ``main``'s publish
    path, not this showcase render.
    """
    name = "10_grayscale_leveled_tree"

    master = pil_grayscale_leveled_tree(canvas_size=MASTER, max_depth=4)
    png_path = CONCEPTS / f"{name}.png"
    master.resize((512, 512), Image.LANCZOS).save(png_path, "PNG")

    frames = []
    for n in ICO_SIZES:
        depth = _depth_for_size(n)
        work  = max(256, n * 4)
        img   = pil_grayscale_leveled_tree(canvas_size=work, max_depth=depth)
        frames.append(img.resize((n, n), Image.LANCZOS))
    ico_path = CONCEPTS / f"{name}.ico"
    write_ico_png_frames(ico_path, frames)

    svg_path = CONCEPTS / f"{name}.svg"
    svg_path.write_text(svg_grayscale_leveled_tree(1024, max_depth=4),
                        encoding="utf-8")

    print(f"  {png_path.relative_to(HERE)}")
    print(f"  {ico_path.relative_to(HERE)}  (depths per size: "
          + ", ".join(f"{n}px={_depth_for_size(n)}" for n in ICO_SIZES) + ")")
    print(f"  {svg_path.relative_to(HERE)}")


# ---------------------------------------------------------------------------
# Concept 09 — grayscale hex-fractal tree, straight trunk, transparent BG
# ---------------------------------------------------------------------------
#
# Same fractal geometry as concept 06.  Differences:
#
#   * Background tile / halo / gradient dropped — fully transparent RGBA.
#   * Palette flattened to grayscale, preserving the *contrast steps*
#     that made concept 06 read well: darker trunk, mid branches, lighter
#     junction highlights, lighter-still leaf tips, near-white prompt.
#   * Trunk is a straight (untapered) stadium-shape whose width is the
#     fractal-scaling "level -1" of the branch stroke
#     (``trunk_w = branch_line_w / _BRANCH_SCALE`` ≈ 1.72×), so the trunk
#     sits naturally inside the same scaling sequence the branches use
#     at each recursion level.
#
# Designed to read on either a light or dark surface, but biased a touch
# darker so it has good contrast on the usual light file-explorer
# background.

_C09_TRUNK    = (46, 46, 46)    # near-black — bottom of contrast ladder
_C09_BRANCH   = (78, 78, 78)
_C09_LEAF_TIP = (122, 122, 122)
_C09_NODE_HI  = (158, 158, 158)
_C09_PROMPT   = (232, 232, 232) # near-white — pops on the dark trunk


def pil_grayscale_fractal_tree(canvas_size: int = MASTER,
                               max_depth: int = 4) -> Image.Image:
    """Concept 09 — grayscale hex-fractal tree, straight trunk, transparent BG.

    Same fractal geometry as concept 06 but with the dark tile, halo,
    and warm gradient removed, palette flattened to grayscale, and
    the trunk re-drawn as a straight (untapered) stadium rectangle
    whose width is one fractal-scaling step "up" from the depth-0
    branch stroke.  Designed to read on either a light or dark
    surface, biased a touch darker for good contrast against the
    usual light file-explorer background.
    """
    s = canvas_size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)

    def px(x, y): return (int(x * s), int(y * s))

    # Stroke widths follow the fractal's scaling sequence.  The trunk is
    # the "level −1" width: one step *up* from the depth-0 branch stroke.
    line_w  = max(2, int(round(s * 0.022)))
    trunk_w = max(3, int(round(line_w / _BRANCH_SCALE)))

    # --- Straight trunk: stadium-shape (rounded ends, untapered) ---
    cx_px = int(0.50 * s)
    ty0   = int(0.66 * s)
    ty1   = int(0.93 * s)
    half  = trunk_w // 2
    d.rounded_rectangle((cx_px - half, ty0, cx_px + half, ty1),
                        radius=half, fill=_C09_TRUNK)

    # --- ">_" prompt on the trunk, in the near-white tone ---
    pcx, pcy = px(0.500, 0.80)
    arm    = int(s * 0.028)
    stroke = max(2, int(round(s * 0.014)))
    d.line([(pcx - arm, pcy - arm), (pcx, pcy), (pcx - arm, pcy + arm)],
           fill=_C09_PROMPT, width=stroke, joint="curve")
    under_w = int(s * 0.040)
    d.rounded_rectangle((pcx + int(s * 0.010), pcy + arm - stroke // 2,
                         pcx + int(s * 0.010) + under_w, pcy + arm + stroke // 2),
                        radius=stroke // 2, fill=_C09_PROMPT)

    # --- Hex-fractal canopy ---
    initial_side = s * 0.155
    node_r = max(2, int(round(s * 0.014)))
    leaf_r = max(3, int(round(s * 0.024)))
    trunk_top = (0.50 * s, 0.66 * s)
    _pil_subtree(d, trunk_top, angle_deg=0.0, side=initial_side,
                     depth=0, max_depth=max_depth,
                     branch=_C09_BRANCH, node_hi=_C09_NODE_HI,
                     leaf_tip=_C09_LEAF_TIP,
                     line_w=line_w, node_r=node_r, leaf_r=leaf_r)

    # Seam cap at the trunk-top / fractal-root junction
    tx, ty = trunk_top
    cap_r = max(3, int(round(s * 0.022)))
    d.ellipse((tx - cap_r, ty - cap_r, tx + cap_r, ty + cap_r), fill=_C09_NODE_HI)

    return img


# --- SVG emitter --------------------------------------------------------

def svg_grayscale_fractal_tree(canvas_size: int = 1024,
                               max_depth: int = 4) -> str:
    """Concept 09 as SVG — vector twin of ``pil_grayscale_fractal_tree``.

    Same grayscale palette (``_C09_*`` constants), same straight
    stadium trunk, same hex-fractal canopy with junction + leaf
    circles.  No background — the file is just the tree on a
    transparent viewBox.
    """
    S = canvas_size

    TRUNK    = f'rgb({_C09_TRUNK[0]},{_C09_TRUNK[1]},{_C09_TRUNK[2]})'
    BRANCH   = f'rgb({_C09_BRANCH[0]},{_C09_BRANCH[1]},{_C09_BRANCH[2]})'
    NODE_HI  = f'rgb({_C09_NODE_HI[0]},{_C09_NODE_HI[1]},{_C09_NODE_HI[2]})'
    LEAF_TIP = f'rgb({_C09_LEAF_TIP[0]},{_C09_LEAF_TIP[1]},{_C09_LEAF_TIP[2]})'
    PROMPT   = f'rgb({_C09_PROMPT[0]},{_C09_PROMPT[1]},{_C09_PROMPT[2]})'

    # Stroke widths matching the PIL renderer's proportions
    line_w  = S * 0.022
    trunk_w = line_w / _BRANCH_SCALE

    # Straight trunk (stadium)
    cx       = 0.50 * S
    ty0, ty1 = 0.66 * S, 0.93 * S
    trunk = (f'<rect x="{cx-trunk_w/2:.2f}" y="{ty0:.2f}" '
             f'width="{trunk_w:.2f}" height="{ty1-ty0:.2f}" '
             f'rx="{trunk_w/2:.2f}" ry="{trunk_w/2:.2f}" fill="{TRUNK}"/>')

    # ">_" prompt
    pcx, pcy = 0.500 * S, 0.80 * S
    arm = 0.028 * S
    stroke = 0.014 * S
    under_w = 0.040 * S
    under_x = pcx + 0.010 * S
    prompt = (
        f'<polyline points="{pcx-arm:.2f},{pcy-arm:.2f} {pcx:.2f},{pcy:.2f} '
        f'{pcx-arm:.2f},{pcy+arm:.2f}" fill="none" stroke="{PROMPT}" '
        f'stroke-width="{stroke:.2f}" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<rect x="{under_x:.2f}" y="{pcy+arm-stroke/2:.2f}" '
        f'width="{under_w:.2f}" height="{stroke:.2f}" '
        f'rx="{stroke/2:.2f}" ry="{stroke/2:.2f}" fill="{PROMPT}"/>'
    )

    # Hex fractal
    trunk_top = (0.50 * S, 0.66 * S)
    initial_side = S * 0.155
    node_r = S * 0.014
    leaf_r = S * 0.024
    fractal = _svg_subtree(trunk_top, 0.0, initial_side, 0, max_depth,
                               BRANCH, NODE_HI, LEAF_TIP,
                               line_w, node_r, leaf_r)
    cap_r = S * 0.022
    cap = (f'<circle cx="{trunk_top[0]:.2f}" cy="{trunk_top[1]:.2f}" '
           f'r="{cap_r:.2f}" fill="{NODE_HI}"/>')

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" width="{S}" height="{S}">
  {trunk}
  {prompt}
  {fractal}
  {cap}
</svg>
'''


def save_concept_09() -> None:
    """Write concept 09's PNG + size-adaptive ICO + SVG into ``concepts/``."""
    name = "09_grayscale_fractal_tree"

    master = pil_grayscale_fractal_tree(canvas_size=MASTER, max_depth=4)
    png_path = CONCEPTS / f"{name}.png"
    master.resize((512, 512), Image.LANCZOS).save(png_path, "PNG")

    frames = []
    for n in ICO_SIZES:
        depth = _depth_for_size(n)
        work  = max(256, n * 4)
        img   = pil_grayscale_fractal_tree(canvas_size=work, max_depth=depth)
        frames.append(img.resize((n, n), Image.LANCZOS))
    ico_path = CONCEPTS / f"{name}.ico"
    write_ico_png_frames(ico_path, frames)

    svg_path = CONCEPTS / f"{name}.svg"
    svg_path.write_text(svg_grayscale_fractal_tree(1024, max_depth=4),
                        encoding="utf-8")

    print(f"  {png_path.relative_to(HERE)}")
    print(f"  {ico_path.relative_to(HERE)}  (depths per size: "
          + ", ".join(f"{n}px={_depth_for_size(n)}" for n in ICO_SIZES) + ")")
    print(f"  {svg_path.relative_to(HERE)}")


# ---------------------------------------------------------------------------
# Concept 08 — concept 06 with a straight trunk, single mint colour
# ---------------------------------------------------------------------------
#
# Same dark rounded tile and same hex-fractal canopy as concept 06, but:
#   * The trunk is a straight (untapered) rounded rectangle — no flare
#     at the base.
#   * Every drawn element of the tree (trunk, branches, junction dots,
#     leaf tips, ">_" prompt) renders in a single mint hue.  The brown
#     trunk and gold prompt from concept 06 are gone.

_C08_MINT = (86, 214, 168)


def pil_mono_fractal_tree(canvas_size: int = MASTER, max_depth: int = 4) -> Image.Image:
    """Concept 08 — monochrome mint fractal on the dark tile.

    Same dark teal tile + warm halo as concept 06, but every
    foreground element (trunk, branches, junction dots, leaf tips,
    ``>_`` prompt) renders in a single mint hue.  The trunk is a
    straight rounded rectangle — no flare, no taper — and the
    ``>_`` is drawn as a "punch-through" in the background colour
    so it reads as a cutout rather than another mint glyph on top
    of the trunk.
    """
    s = canvas_size
    tile = make_tile(s, (22, 54, 66), (9, 22, 30),
                     halo=(int(s * 0.5), int(s * 0.30), int(s * 0.40),
                           (255, 210, 130), 60))
    d = ImageDraw.Draw(tile)

    MINT = _C08_MINT
    def px(x, y): return (int(x * s), int(y * s))

    # --- Straight trunk: rounded rectangle, no taper, no flare -----------
    tx0, ty0 = px(0.46, 0.66)
    tx1, ty1 = px(0.54, 0.93)
    rx = int((tx1 - tx0) * 0.4)   # softly rounded ends
    d.rounded_rectangle((tx0, ty0, tx1, ty1), radius=rx, fill=MINT)

    # --- ">_" prompt etched into trunk, same mint colour -----------------
    # A subtle inset is created by drawing the prompt in the *background*
    # colour so it reads as a cutout rather than a coloured glyph.
    BG_PUNCH = (14, 36, 46)   # close to the lower tile gradient stop
    cx, cy = px(0.500, 0.80)
    arm = int(s * 0.032); stroke = int(s * 0.017)
    d.line([(cx - arm, cy - arm), (cx, cy), (cx - arm, cy + arm)],
           fill=BG_PUNCH, width=stroke, joint="curve")
    under_w = int(s * 0.045)
    d.rounded_rectangle((cx + int(s * 0.010), cy + arm - stroke // 2,
                         cx + int(s * 0.010) + under_w, cy + arm + stroke // 2),
                        radius=stroke // 2, fill=BG_PUNCH)

    # --- Hex-fractal canopy, single mint hue for all parts ---------------
    initial_side = s * 0.155
    line_w  = max(2, int(round(s * 0.022)))
    node_r  = max(2, int(round(s * 0.014)))
    leaf_r  = max(3, int(round(s * 0.024)))

    trunk_top = (0.50 * s, 0.66 * s)
    _pil_subtree(d, trunk_top, angle_deg=0.0, side=initial_side,
                     depth=0, max_depth=max_depth,
                     branch=MINT, node_hi=MINT, leaf_tip=MINT,
                     line_w=line_w, node_r=node_r, leaf_r=leaf_r)

    # Seam cap where the trunk top meets V1
    tx, ty = trunk_top
    cap_r = max(3, int(round(s * 0.022)))
    d.ellipse((tx - cap_r, ty - cap_r, tx + cap_r, ty + cap_r), fill=MINT)

    return tile


# --- SVG emitter --------------------------------------------------------

def svg_mono_fractal_tree(canvas_size: int = 1024, max_depth: int = 4) -> str:
    """Concept 08 as SVG — vector twin of ``pil_mono_fractal_tree``.

    Embeds the dark gradient + halo as SVG defs, then renders trunk +
    canopy + ``>_`` prompt all in the same mint hue (with the prompt
    in the punch-through background colour for the cutout effect).
    """
    S = canvas_size
    BG_TOP   = "#163642"; BG_BOT  = "#09161E"
    MINT     = "#56D6A8"
    BG_PUNCH = "#0E242E"   # punch-through colour for the prompt cutout

    R_TILE = 0.22 * S

    # Straight trunk rounded rectangle
    tx0, ty0 = 0.46 * S, 0.66 * S
    tx1, ty1 = 0.54 * S, 0.93 * S
    trunk_rx = (tx1 - tx0) * 0.4
    trunk = (f'<rect x="{tx0:.2f}" y="{ty0:.2f}" '
             f'width="{tx1-tx0:.2f}" height="{ty1-ty0:.2f}" '
             f'rx="{trunk_rx:.2f}" ry="{trunk_rx:.2f}" fill="{MINT}"/>')

    # ">_" prompt as a darker cutout on the trunk
    cpx, cpy = 0.500 * S, 0.80 * S
    arm = 0.032 * S; stroke = 0.017 * S
    under_w = 0.045 * S; under_x = cpx + 0.010 * S
    prompt = (
        f'<polyline points="{cpx-arm:.2f},{cpy-arm:.2f} {cpx:.2f},{cpy:.2f} '
        f'{cpx-arm:.2f},{cpy+arm:.2f}" fill="none" stroke="{BG_PUNCH}" '
        f'stroke-width="{stroke:.2f}" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<rect x="{under_x:.2f}" y="{cpy+arm-stroke/2:.2f}" '
        f'width="{under_w:.2f}" height="{stroke:.2f}" '
        f'rx="{stroke/2:.2f}" ry="{stroke/2:.2f}" fill="{BG_PUNCH}"/>'
    )

    trunk_top = (0.50 * S, 0.66 * S)
    initial_side = S * 0.155
    line_w = S * 0.022
    node_r = S * 0.014
    leaf_r = S * 0.024
    fractal = _svg_subtree(trunk_top, 0.0, initial_side, 0, max_depth,
                               MINT, MINT, MINT,
                               line_w, node_r, leaf_r)
    cap_r = S * 0.022
    cap = (f'<circle cx="{trunk_top[0]:.2f}" cy="{trunk_top[1]:.2f}" '
           f'r="{cap_r:.2f}" fill="{MINT}"/>')

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" width="{S}" height="{S}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{BG_TOP}"/>
      <stop offset="1" stop-color="{BG_BOT}"/>
    </linearGradient>
    <radialGradient id="halo" cx="0.5" cy="0.30" r="0.40">
      <stop offset="0" stop-color="#FFD282" stop-opacity="0.32"/>
      <stop offset="1" stop-color="#FFD282" stop-opacity="0"/>
    </radialGradient>
    <clipPath id="tile">
      <rect x="0" y="0" width="{S}" height="{S}" rx="{R_TILE}" ry="{R_TILE}"/>
    </clipPath>
  </defs>
  <g clip-path="url(#tile)">
    <rect x="0" y="0" width="{S}" height="{S}" fill="url(#bg)"/>
    <rect x="0" y="0" width="{S}" height="{S}" fill="url(#halo)"/>
    {trunk}
    {prompt}
    {fractal}
    {cap}
  </g>
</svg>
'''


def save_concept_08() -> None:
    """Write concept 08's PNG + size-adaptive ICO + SVG into ``concepts/``."""
    name = "08_mono_fractal_tree"

    master = pil_mono_fractal_tree(canvas_size=MASTER, max_depth=4)
    png_path = CONCEPTS / f"{name}.png"
    master.resize((512, 512), Image.LANCZOS).save(png_path, "PNG")

    frames = []
    for n in ICO_SIZES:
        depth = _depth_for_size(n)
        work  = max(256, n * 4)
        img   = pil_mono_fractal_tree(canvas_size=work, max_depth=depth)
        frames.append(img.resize((n, n), Image.LANCZOS))
    ico_path = CONCEPTS / f"{name}.ico"
    write_ico_png_frames(ico_path, frames)

    svg_path = CONCEPTS / f"{name}.svg"
    svg_path.write_text(svg_mono_fractal_tree(1024, max_depth=4), encoding="utf-8")

    print(f"  {png_path.relative_to(HERE)}")
    print(f"  {ico_path.relative_to(HERE)}  (depths per size: "
          + ", ".join(f"{n}px={_depth_for_size(n)}" for n in ICO_SIZES) + ")")
    print(f"  {svg_path.relative_to(HERE)}")


# ---------------------------------------------------------------------------
# Concept 07 — glyph-style hex-fractal tree
# ---------------------------------------------------------------------------
#
# Matches the program's bundled facet-icon style as documented in
# ``help/host-software-icon-style.md``:
#
#   * 48-grid composition, content within the 4→44 band.
#   * Stroke-only, no fill, no background tile, no gradient.
#   * Single colour, expressed as ``currentColor`` in the SVG so the
#     glyph picks up the surrounding text colour (free theming).
#   * Canonical stroke-width 2.5; secondary nested detail at 2.
#     (The trunk breaks this on purpose — see below — because the user
#     wanted it visibly wider than the branches.)
#   * Round caps and joins on every stroke.
#
# Differences from concept 06:
#   * No tile / halo / gradient — transparent background.
#   * Trunk is a straight untapered stroke (no polygon, no flare), just
#     a thicker version of a branch.
#   * Junction and leaf dots are dropped (filled circles aren't part of
#     the line-glyph language).
#   * The fractal is the same hex geometry, but tuned tighter so depth
#     3-4 still fits inside the 4→44 band.

# 48-grid coordinates (matching the style guide's canvas)
#
# Stroke weights are calibrated *lighter* than the canonical 2.5 used by
# the bundled facet icons.  Those icons are 1-4 primitives sparse on the
# 48 grid; our fractal at depth 3 puts ~28 segments in the same area,
# and 2.5 turns the canopy into a solid blob.  The aesthetic stays in
# the family — `currentColor`, no fill, round caps — but the weights are
# tuned for density.  The trunk is still ~2× the branch width so it
# reads as the "wider version of a branch" the user asked for.
_G07_TRUNK_TOP    = (24.0, 30.0)
_G07_TRUNK_BOTTOM = (24.0, 44.0)
_G07_BRANCH_STROKE = 1.4
_G07_TRUNK_STROKE  = 3.0
_G07_PROMPT_STROKE = 1.4
_G07_INITIAL_SIDE  = 5.5


def _pil_subtree_lines(d, anchor, angle_deg, side, depth, max_depth,
                           color, line_w_px, scale_per_unit):
    """Stroke-only variant of the hex fractal — no junction or leaf dots."""
    v1, v2, v6, v3, v5 = _split_pts(anchor, angle_deg, side)
    for a, b in ((v1, v2), (v1, v6), (v2, v3), (v6, v5)):
        d.line([a, b], fill=color, width=line_w_px)
    if depth < max_depth:
        ns  = side * _BRANCH_SCALE
        nlw = max(1, int(round(line_w_px * _BRANCH_SCALE)))
        _pil_subtree_lines(d, v3, angle_deg - _BRANCH_TILT, ns,
                               depth + 1, max_depth, color, nlw, scale_per_unit)
        _pil_subtree_lines(d, v5, angle_deg + _BRANCH_TILT, ns,
                               depth + 1, max_depth, color, nlw, scale_per_unit)


def pil_glyph_fractal_tree(canvas_size: int = MASTER, max_depth: int = 3,
                           color=(86, 214, 168)) -> Image.Image:
    """Render concept 07 — line-glyph hex-fractal tree on transparent BG."""
    s = canvas_size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)

    # 48-grid → pixel scale
    u  = s / 48.0
    def g(x, y): return (x * u, y * u)

    # ---- Trunk: a single straight stroke, no taper ----
    trunk_w_px = max(2, int(round(_G07_TRUNK_STROKE * u)))
    # PIL doesn't do round line caps natively for `Draw.line`; draw the
    # line, then cap both ends with filled circles of matching radius.
    tx0, ty0 = g(*_G07_TRUNK_TOP)
    tx1, ty1 = g(*_G07_TRUNK_BOTTOM)
    d.line([(tx0, ty0), (tx1, ty1)], fill=color, width=trunk_w_px)
    rcap = trunk_w_px / 2
    for (cx, cy) in ((tx0, ty0), (tx1, ty1)):
        d.ellipse((cx - rcap, cy - rcap, cx + rcap, cy + rcap), fill=color)

    # ---- ">_" prompt to the left of the trunk base ----
    # Small, drawn in the secondary stroke weight per the style guide.
    pstroke = max(1, int(round(_G07_PROMPT_STROKE * u)))
    # chevron centre at (14, 40) on the 48 grid, arm = 2.2, underscore len 4
    pcx, pcy = g(14, 40)
    parm = 2.2 * u
    chev = [(pcx - parm * 0.6, pcy - parm),
            (pcx, pcy),
            (pcx - parm * 0.6, pcy + parm)]
    d.line(chev, fill=color, width=pstroke, joint="curve")
    # round-cap the chevron ends
    for (cx, cy) in (chev[0], chev[2]):
        r = pstroke / 2
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
    # underscore
    uy = pcy + parm
    ux0 = pcx + 0.6 * u
    ux1 = ux0 + 3.4 * u
    d.line([(ux0, uy), (ux1, uy)], fill=color, width=pstroke)
    for (cx, cy) in ((ux0, uy), (ux1, uy)):
        r = pstroke / 2
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)

    # ---- Hex fractal canopy ----
    bw_px = max(2, int(round(_G07_BRANCH_STROKE * u)))
    initial_side_px = _G07_INITIAL_SIDE * u
    _pil_subtree_lines(d, (tx0, ty0), 0.0, initial_side_px,
                           depth=0, max_depth=max_depth,
                           color=color, line_w_px=bw_px, scale_per_unit=u)

    # PIL's polyline join 'curve' doesn't fully round caps at segment
    # ENDS; cap every fractal endpoint with a small disc so the tree's
    # outermost tips don't look chopped square.
    # We re-walk the structure to collect endpoints — cheap.
    def collect_endpoints(anchor, angle, side, depth):
        v1, v2, v6, v3, v5 = _split_pts(anchor, angle, side)
        if depth < max_depth:
            ns = side * _BRANCH_SCALE
            return (collect_endpoints(v3, angle - _BRANCH_TILT, ns, depth + 1)
                    + collect_endpoints(v5, angle + _BRANCH_TILT, ns, depth + 1))
        return [v3, v5]
    tips = collect_endpoints((tx0, ty0), 0.0, initial_side_px, 0)
    r = bw_px / 2
    for (cx, cy) in tips:
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)

    return img


# --- SVG emitter --------------------------------------------------------

def _svg_subtree_lines(anchor, angle_deg, side, depth, max_depth,
                           stroke_w) -> str:
    """SVG analogue of ``_pil_subtree_lines`` — stroke-only hex fractal.

    Recurses through the hex-split geometry just like the dot-bearing
    variants but emits ``<line>`` elements only, with ``currentColor``
    so the line-glyph icon picks up its colour from the surrounding
    text colour (per the facet-icon style guide).  No junction dots,
    no leaf tips.
    """
    v1, v2, v6, v3, v5 = _split_pts(anchor, angle_deg, side)
    parts = []
    for a, b in ((v1, v2), (v1, v6), (v2, v3), (v6, v5)):
        parts.append(
            f'<line x1="{a[0]:.3f}" y1="{a[1]:.3f}" '
            f'x2="{b[0]:.3f}" y2="{b[1]:.3f}" '
            f'stroke="currentColor" stroke-width="{stroke_w:.3f}" '
            f'stroke-linecap="round"/>')
    if depth < max_depth:
        ns = side * _BRANCH_SCALE
        nsw = stroke_w * _BRANCH_SCALE
        parts.append(_svg_subtree_lines(v3, angle_deg - _BRANCH_TILT, ns,
                                            depth + 1, max_depth, nsw))
        parts.append(_svg_subtree_lines(v5, angle_deg + _BRANCH_TILT, ns,
                                            depth + 1, max_depth, nsw))
    return "\n".join(parts)


def svg_glyph_fractal_tree(max_depth: int = 3) -> str:
    """48-grid line-glyph SVG, currentColor, matching the style guide."""
    initial_side = _G07_INITIAL_SIDE
    trunk_top    = _G07_TRUNK_TOP
    trunk_bot    = _G07_TRUNK_BOTTOM

    trunk = (
        f'<line x1="{trunk_top[0]:.2f}" y1="{trunk_top[1]:.2f}" '
        f'x2="{trunk_bot[0]:.2f}" y2="{trunk_bot[1]:.2f}" '
        f'stroke="currentColor" stroke-width="{_G07_TRUNK_STROKE}" '
        f'stroke-linecap="round"/>'
    )
    # ">_" prompt
    pcx, pcy = 14, 40
    parm = 2.2
    prompt = (
        f'<path d="M{pcx-parm*0.6:.2f} {pcy-parm:.2f} L{pcx:.2f} {pcy:.2f} '
        f'L{pcx-parm*0.6:.2f} {pcy+parm:.2f}" stroke="currentColor" '
        f'stroke-width="{_G07_PROMPT_STROKE}" stroke-linecap="round" '
        f'stroke-linejoin="round" fill="none"/>'
        f'<line x1="{pcx+0.6:.2f}" y1="{pcy+parm:.2f}" '
        f'x2="{pcx+0.6+3.4:.2f}" y2="{pcy+parm:.2f}" stroke="currentColor" '
        f'stroke-width="{_G07_PROMPT_STROKE}" stroke-linecap="round"/>'
    )
    fractal = _svg_subtree_lines(trunk_top, 0.0, initial_side, 0,
                                     max_depth, _G07_BRANCH_STROKE)

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none" aria-hidden="true">
  <!-- Generic fractal-tree shape — ScripTree app glyph, no trademark risk -->
  {trunk}
  {prompt}
  {fractal}
</svg>
'''


def save_concept_07() -> None:
    """Render concept 07 (line-glyph fractal) with size-adaptive depth."""
    name = "07_glyph_fractal_tree"
    color = (86, 214, 168)   # mint accent for the rasterised version

    master = pil_glyph_fractal_tree(canvas_size=MASTER, max_depth=3, color=color)
    png_path = CONCEPTS / f"{name}.png"
    master.resize((512, 512), Image.LANCZOS).save(png_path, "PNG")

    # ICO frames — slightly different depth ladder than concept 06 because
    # line-glyph strokes get very busy at depth 4 in the 48-grid box.
    def depth_for(n):
        if n <= 24:  return 1
        if n <= 64:  return 2
        return 3

    frames = []
    for n in ICO_SIZES:
        depth = depth_for(n)
        work  = max(256, n * 4)
        img   = pil_glyph_fractal_tree(canvas_size=work, max_depth=depth, color=color)
        frames.append(img.resize((n, n), Image.LANCZOS))
    ico_path = CONCEPTS / f"{name}.ico"
    write_ico_png_frames(ico_path, frames)

    svg_path = CONCEPTS / f"{name}.svg"
    svg_path.write_text(svg_glyph_fractal_tree(max_depth=3), encoding="utf-8")

    print(f"  {png_path.relative_to(HERE)}")
    print(f"  {ico_path.relative_to(HERE)}  (depths per size: "
          + ", ".join(f"{n}px={depth_for(n)}" for n in ICO_SIZES) + ")")
    print(f"  {svg_path.relative_to(HERE)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

CONCEPTS_TABLE = {
    "01_node_graph":           concept_node_graph,
    "02_wood_tree_windows":    concept_wood_tree_windows,
    "03_branch_windows":       concept_branch_windows,
    "04_upright_tree_windows": lambda: concept_upright_tree_windows(),
    "05_upright_branch_windows": lambda: concept_upright_branch_windows(),
}


def _build_cli() -> argparse.ArgumentParser:
    """Construct the argparse parser for ``make_icon.py``.

    The parser drives two distinct paths in ``main`` — see the
    parser's own ``description`` text for the user-facing split.
    Help text on every flag is written for end-users (the script
    is also wired into the GUI front-end at
    ``ScripTreeApps/ScripTreeManagement/make_icon.scriptree``, which
    surfaces each flag as a labelled form field).
    """
    p = argparse.ArgumentParser(
        prog="make_icon.py",
        description=(
            "Generate ScripTree icons.  With no flags: re-renders every "
            "concept into ./concepts/ and re-publishes the ACTIVE concept "
            "(currently '%s') to scriptree.{png,ico,svg} and to "
            "icons/icon-forest.{png,svg}.\n\n"
            "Single-shot mode: pass --depth and/or --size to render just "
            "the active concept at a chosen recursion depth and PNG size, "
            "writing one PNG to --out (default: ./scriptree_custom.png).  "
            "In single-shot mode no concepts/ files, .ico, .svg, or "
            "icons/icon-forest are touched."
        ) % ACTIVE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--depth", type=int, default=None,
        help="Hex-fractal recursion depth (number of branch iterations). "
             "Default render uses size-adaptive depth (1 at 16/24 px, 2 at "
             "32/48, 3 at 64, 4 at 128+).  Try 1..6.",
    )
    p.add_argument(
        "--size", type=int, default=None,
        help="Output PNG size in pixels (square).  Single-shot only.  "
             "Default master canvas: %d." % MASTER,
    )
    p.add_argument(
        "--concept", default=None,
        help="Override which concept to render.  Default: ACTIVE = '%s'.  "
             "Must be one of the size-adaptive concepts (06/08/09/10) for "
             "--depth/--size to apply." % ACTIVE,
    )
    p.add_argument(
        "--out", type=Path, default=None,
        help="Output PNG path for single-shot mode.  "
             "Default: ./scriptree_custom.png next to this script "
             "(suppressed automatically when --svg-out is the only "
             "output requested).",
    )
    p.add_argument(
        "--svg-out", type=Path, default=None,
        help="Output SVG path for single-shot mode.  May be set on its "
             "own, or alongside --out to produce both formats in one "
             "render.  Concept must be size-adaptive (06/08/09/10).  "
             "--size sets the SVG's viewBox + internal coordinate "
             "space, which mostly affects stroke widths when the file "
             "is opened with a forced pixel size (default 1024 is "
             "fine for almost everything).",
    )
    # ---- Full-publish overrides (applied to the default no-flag run) ----
    p.add_argument(
        "--publish-depth", type=int, default=None,
        help="Override the recursion depth used by the FULL PUBLISH path "
             "(scriptree.{png,ico,svg} + icons/icon-forest.{png,svg}).  "
             "When set, this depth is used for every ICO frame *and* the "
             "showcase PNG and SVG (bypasses the size-adaptive ladder).  "
             "Implies a full publish — incompatible with --depth/--size/--out.",
    )
    p.add_argument(
        "--ico-sizes", type=_parse_ico_sizes, default=None,
        metavar="N,N,...",
        help="Override the .ico frame ladder used by the full publish.  "
             "Comma-separated pixel sizes, e.g. '--ico-sizes 16,32,48,256'.  "
             "Default: %s.  Implies a full publish."
             % ",".join(str(n) for n in ICO_SIZES),
    )
    # ---- Palette options (apply to both single-shot and full publish) ----
    p.add_argument(
        "--invert", action="store_true",
        help="Flip the brightness ladder so the trunk + nearest branches "
             "end up LIGHTEST and the canopy tips DARKEST.  Pair with "
             "no --color to get a light-on-dark icon; with --color to get "
             "the inverted tints of that hue.  Concept 10 only.",
    )
    def _color_arg(s: str) -> str:
        try:
            _parse_hex_color(s)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"--color: {exc}")
        return s
    p.add_argument(
        "--trunk-width", type=int, default=None, metavar="PX",
        help="Set the overall stroke weight for the whole tree.  "
             "Value names the trunk thickness in pixels at the "
             "1024-reference canvas (scaled proportionally for other "
             "canvas sizes -- 50 means '50 px at 1024, ~12 px at 256'), "
             "and the canopy branches plus connector circles are "
             "scaled by the same ratio so the fractal proportions are "
             "preserved.  Passing --trunk-width 80 doubles every "
             "stroke -- trunk, every branch level, and every junction "
             "node -- relative to the default 40 px trunk.  Default: "
             "derived from the fractal scaling ladder (~40 px at 1024 "
             "with the canopy at its default thickness).  Concept 10 "
             "only.",
    )
    p.add_argument(
        "--color", default=None, metavar="#RRGGBB", type=_color_arg,
        help="Re-map the grayscale brightness ladder onto a chosen hue "
             "(#RRGGBB or RRGGBB; #RGB shorthand also accepted).  The "
             "trunk-darker / tips-lighter relationship is preserved as "
             "shades-then-tints of the chosen colour.  Example: "
             "--color '#56D6A8' restores the original ScripTree mint.  "
             "Concept 10 only.",
    )
    p.add_argument(
        "--trunk-lightness", type=int, default=None, metavar="0..255",
        help="Set the trunk's brightness on the 0..255 grayscale ladder.  "
             "Each successive recursion level brightens by a fixed step "
             "(default 14), so pick 255 - max_depth * step to land the "
             "canopy tips on pure white.  At the default max_depth=4 + "
             "step=14, that's --trunk-lightness 199 (trunk=199, level1=213, "
             "level2=227, level3=241, tips=255).  Node colours follow the "
             "branch ladder up by the same delta so the within-level "
             "node-vs-branch contrast is preserved.  When --invert is "
             "also set, the assignment flips (trunk gets the brightest "
             "end, tips the darkest).  Default: 78 (the bottom of the "
             "fractal's stock contrast range).  Concept 10 only.",
    )
    # Documented for ``--help`` only -- the real handling lives in
    # ``_ensure_pillow`` at module top, which pre-scans sys.argv before
    # the top-level ``from PIL import ...`` could fire on a missing
    # Pillow.  Argparse just sees the flag and ignores it (no business
    # logic depends on args.install_deps once we get this far -- by
    # then Pillow is already present).  Listed here so ``--help`` shows
    # the flag and the prompt text mentions a real, discoverable option.
    p.add_argument(
        "--install-deps", action="store_true",
        help="Offer to ``pip install Pillow`` into this Python "
             "(``sys.executable``) when it's missing, instead of just "
             "printing the install command and exiting.  Prompts for "
             "confirmation on a TTY; in non-interactive contexts (GUI "
             "runner, CI) treats the flag itself as consent.  Has no "
             "effect when Pillow is already installed.",
    )
    return p


def _parse_ico_sizes(s: str) -> list[int]:
    """argparse type for --ico-sizes: 'a,b,c' -> [a, b, c] (deduped, sorted)."""
    try:
        sizes = sorted({int(t.strip()) for t in s.split(",") if t.strip()})
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--ico-sizes expects a comma-separated list of integers: {exc}")
    if not sizes:
        raise argparse.ArgumentTypeError("--ico-sizes can't be empty")
    bad = [n for n in sizes if n < 8 or n > 1024]
    if bad:
        raise argparse.ArgumentTypeError(
            f"--ico-sizes entries must be 8..1024 px; got {bad}")
    return sizes


def _single_shot(args: argparse.Namespace) -> None:
    """Render one PNG and/or SVG of one concept at a chosen depth/size.

    Output selection rules:

    * ``--out`` alone -> PNG only (current behaviour, preserved).
    * ``--svg-out`` alone -> SVG only.
    * Both -> both formats, side-by-side at the paths given.
    * Neither -> PNG only at the legacy default
      ``./scriptree_custom.png`` next to this script.

    The same ``--depth / --size / --color / --invert / --trunk-width /
    --trunk-lightness`` flags apply to both formats so the two outputs
    are visually consistent when produced together.
    """
    name = args.concept or ACTIVE
    if name not in _ADAPTIVE_CONCEPTS:
        raise SystemExit(
            f"--depth/--size require an adaptive concept (one of "
            f"{sorted(_ADAPTIVE_CONCEPTS)}); got {name!r}.")
    if ((args.invert or args.color or args.trunk_width is not None
                or args.trunk_lightness is not None)
            and name != "10_grayscale_leveled_tree"):
        raise SystemExit(
            f"--invert / --color / --trunk-width / --trunk-lightness only "
            f"affect concept 10_grayscale_leveled_tree; got concept "
            f"{name!r}.  Re-run without those flags or pick "
            f"--concept 10_grayscale_leveled_tree.")
    if args.trunk_width is not None and args.trunk_width < 1:
        raise SystemExit("--trunk-width must be at least 1 px.")
    if args.trunk_lightness is not None and not (0 <= args.trunk_lightness <= 255):
        raise SystemExit("--trunk-lightness must be in [0, 255].")
    pil_fn, svg_fn, *_ = _ADAPTIVE_CONCEPTS[name]
    depth  = args.depth if args.depth is not None else 4
    size   = args.size  if args.size  is not None else MASTER

    # Validate --color early so the user gets a clean error before render
    if args.color:
        _parse_hex_color(args.color)  # raises ValueError if malformed

    # Decide which formats to write.  The default-when-nothing-given
    # behaviour preserves the v0.7-era "render a PNG to a sensible
    # default path" so existing invocations with no output flag still
    # work as documented.
    png_out = args.out
    svg_out = args.svg_out
    if png_out is None and svg_out is None:
        png_out = HERE / "scriptree_custom.png"

    # Shared bits-suffix for the "Wrote ..." print lines so the user
    # can tell at a glance what palette knobs landed on each file.
    bits = []
    if args.invert:                       bits.append("invert")
    if args.color:                        bits.append(f"color={args.color}")
    if args.trunk_width is not None:      bits.append(f"trunk-width={args.trunk_width}px")
    if args.trunk_lightness is not None:  bits.append(f"trunk-lightness={args.trunk_lightness}")
    palette_note = f", {', '.join(bits)}" if bits else ""

    if png_out is not None:
        # Render at the requested size directly when ≥ 256, else
        # render at a higher working resolution and downsample for
        # clean antialiasing.  SVG doesn't need this dance — it's
        # resolution-independent.
        work = max(256, size)
        img  = pil_fn(canvas_size=work, max_depth=depth,
                      invert=args.invert, color=args.color,
                      trunk_width=args.trunk_width,
                      trunk_lightness=args.trunk_lightness)
        if work != size:
            img = img.resize((size, size), Image.LANCZOS)
        png_out.parent.mkdir(parents=True, exist_ok=True)
        img.save(png_out, "PNG")
        print(f"Wrote {png_out}  ({name}, depth={depth}, size={size}px{palette_note})")

    if svg_out is not None:
        svg_text = svg_fn(size, depth,
                          invert=args.invert, color=args.color,
                          trunk_width=args.trunk_width,
                          trunk_lightness=args.trunk_lightness)
        svg_out.parent.mkdir(parents=True, exist_ok=True)
        svg_out.write_text(svg_text, encoding="utf-8")
        print(f"Wrote {svg_out}  ({name}, depth={depth}, viewBox={size}{palette_note})")


# Adaptive concepts.  Renderers all accept ``invert`` / ``color`` kwargs
# for forward-compat with the palette CLI flags; concepts 06/08/09 ignore
# them (their palettes are baked in), only concept 10 honours them.
def _wrap_palette_pil(fn):
    """Wrap a palette-free PIL renderer so it accepts (and ignores) the palette kwargs.

    Concepts 06/08/09 take ``(canvas_size, max_depth)``; concept 10
    additionally takes ``invert`` / ``color`` / ``trunk_width`` /
    ``trunk_lightness``.  The ``_ADAPTIVE_CONCEPTS`` dispatch table
    calls every renderer with the same signature for uniformity, so
    we wrap the simpler ones to discard the extra kwargs silently.
    """
    return lambda *, canvas_size, max_depth, invert=False, color=None, trunk_width=None, trunk_lightness=None: fn(canvas_size, max_depth)

def _wrap_palette_svg(fn):
    """SVG counterpart of ``_wrap_palette_pil`` — discards palette kwargs."""
    return lambda S, max_depth, invert=False, color=None, trunk_width=None, trunk_lightness=None: fn(S, max_depth)

_ADAPTIVE_CONCEPTS = {
    # name -> (pil_renderer, svg_renderer, size→depth fn, default max_depth)
    "06_hex_fractal_tree":       (_wrap_palette_pil(pil_fractal_tree),       _wrap_palette_svg(svg_fractal_tree),       None, 4),
    "08_mono_fractal_tree":      (_wrap_palette_pil(pil_mono_fractal_tree),      _wrap_palette_svg(svg_mono_fractal_tree),      None, 4),
    "09_grayscale_fractal_tree": (_wrap_palette_pil(pil_grayscale_fractal_tree), _wrap_palette_svg(svg_grayscale_fractal_tree), None, 4),
    # Concept 10 honours invert + color + trunk_width + trunk_lightness.
    "10_grayscale_leveled_tree": (
        lambda *, canvas_size, max_depth, invert=False, color=None, trunk_width=None, trunk_lightness=None:
            pil_grayscale_leveled_tree(canvas_size, max_depth,
                                       invert=invert, color=color,
                                       trunk_width=trunk_width,
                                       trunk_lightness=trunk_lightness),
        lambda S, max_depth, invert=False, color=None, trunk_width=None, trunk_lightness=None:
            svg_grayscale_leveled_tree(S, max_depth,
                                       invert=invert, color=color,
                                       trunk_width=trunk_width,
                                       trunk_lightness=trunk_lightness),
        None, 4),
}


def main() -> None:
    """Entry point — dispatch to single-shot or full-publish based on argv.

    Decision tree:

    * Any of ``--depth`` / ``--size`` / ``--out`` / ``--svg-out`` set
      -> **single-shot** (``_single_shot``).  Touches only the user-
      named output path(s).
    * Any of ``--publish-depth`` / ``--ico-sizes`` set, and none of
      the single-shot flags -> **full publish with overrides**.
    * Combining single-shot flags with publish-override flags raises
      ``SystemExit`` (those are different intents and would silently
      drop one user's input).
    * Otherwise -> **full publish** with defaults.

    The full-publish path:

      1. Renders every concept's showcase artefacts into
         ``concepts/<NN_name>.{png,ico,svg}``.
      2. Publishes the ``ACTIVE`` concept to ``scriptree.{png,ico,svg}``
         at the resources root, applying any palette flags
         (concept 10 only) and any ICO-ladder overrides.
      3. Publishes the same image to ``icons/icon-forest.{png,svg}``
         at the project root so the cell-shell forest hub falls back
         to a consistent glyph when no per-forest icon is embedded.
    """
    args = _build_cli().parse_args()
    # ``--svg-out`` belongs on this list -- a user who passes ONLY
    # ``--svg-out`` (no --depth / --size / --out) is asking for a
    # single-shot SVG render, not a full publish.  Missing this
    # caused --svg-out alone to silently fall through to publish.
    single_shot = (args.depth is not None or args.size is not None
                   or args.out is not None
                   or args.svg_out is not None)
    publish_overrides = (args.publish_depth is not None
                        or args.ico_sizes is not None)
    if single_shot and publish_overrides:
        raise SystemExit(
            "--publish-depth / --ico-sizes apply to the FULL PUBLISH path "
            "and cannot be combined with --depth / --size / --out "
            "(single-shot mode).  Run them separately.")
    if single_shot:
        # Don't touch the published icons, the concepts dir, or icon-forest.
        _single_shot(args)
        return

    print("Rendering concepts:")
    rendered: dict[str, Image.Image] = {}
    for name, fn in CONCEPTS_TABLE.items():
        img = fn()
        save_concept(name, img)
        rendered[name] = img

    # Concepts 06 and 07 have size-adaptive recursion depth, so they own
    # their own save paths (one render per ICO frame at its target depth).
    save_concept_06()
    save_concept_07()
    save_concept_08()
    save_concept_09()
    save_concept_10()

    # Publish the active concept at the resources root.  Concepts with a
    # size-adaptive ICO renderer get the per-frame depth treatment here
    # too (the bare resize-from-master path is only used for the simpler
    # static concepts).
    _ADAPTIVE_PUBLISH = {
        "06_hex_fractal_tree":         (pil_fractal_tree,        svg_fractal_tree,        _depth_for_size, 4),
        "08_mono_fractal_tree":        (pil_mono_fractal_tree,       svg_mono_fractal_tree,       _depth_for_size, 4),
        "09_grayscale_fractal_tree":   (pil_grayscale_fractal_tree,  svg_grayscale_fractal_tree,  _depth_for_size, 4),
        "10_grayscale_leveled_tree":   (pil_grayscale_leveled_tree,  svg_grayscale_leveled_tree,  _depth_for_size, 4),
    }

    if ACTIVE in _ADAPTIVE_PUBLISH:
        pil_fn, svg_fn, depth_fn, max_d = _ADAPTIVE_PUBLISH[ACTIVE]
        # Apply --publish-depth / --ico-sizes overrides if given
        effective_max_d   = args.publish_depth if args.publish_depth is not None else max_d
        effective_sizes   = args.ico_sizes      if args.ico_sizes      is not None else ICO_SIZES
        # When --publish-depth is set, every frame uses that depth
        # (bypasses the size-adaptive ladder); otherwise the ladder
        # picks per-frame depth as before.
        if args.publish_depth is not None:
            frame_depth_fn = lambda n: args.publish_depth   # noqa: E731
        else:
            frame_depth_fn = depth_fn

        # --invert / --color / --trunk-width / --trunk-lightness only
        # mean anything for concept 10.  Reject early instead of
        # silently dropping intent.
        palette_active = (args.invert or args.color
                          or args.trunk_width is not None
                          or args.trunk_lightness is not None)
        if palette_active and ACTIVE != "10_grayscale_leveled_tree":
            raise SystemExit(
                f"--invert / --color / --trunk-width / --trunk-lightness "
                f"only affect 10_grayscale_leveled_tree; active concept "
                f"is {ACTIVE!r}.  Re-run without those flags or switch "
                f"ACTIVE.")
        if args.color:
            _parse_hex_color(args.color)   # validate early
        if args.trunk_width is not None and args.trunk_width < 1:
            raise SystemExit("--trunk-width must be at least 1 px.")
        if args.trunk_lightness is not None and not (0 <= args.trunk_lightness <= 255):
            raise SystemExit("--trunk-lightness must be in [0, 255].")
        palette = dict(invert=args.invert, color=args.color,
                       trunk_width=args.trunk_width,
                       trunk_lightness=args.trunk_lightness)

        # Master PNG at the (possibly-overridden) max depth
        master = pil_fn(canvas_size=MASTER, max_depth=effective_max_d, **palette)
        master.resize((512, 512), Image.LANCZOS).save(HERE / "scriptree.png", "PNG")
        # ICO frames with per-frame depth from the ladder (or the override)
        frames = []
        for n in effective_sizes:
            depth = frame_depth_fn(n)
            work  = max(256, n * 4)
            img   = pil_fn(canvas_size=work, max_depth=depth, **palette)
            frames.append(img.resize((n, n), Image.LANCZOS))
        write_ico_png_frames(HERE / "scriptree.ico", frames)
        # SVG
        (HERE / "scriptree.svg").write_text(
            svg_fn(1024, max_depth=effective_max_d, **palette), encoding="utf-8")
        print(f"Active = {ACTIVE} -> scriptree.png / scriptree.ico / scriptree.svg")
        if (publish_overrides or args.invert or args.color
                or args.trunk_width is not None
                or args.trunk_lightness is not None):
            bits = []
            if publish_overrides:
                bits.append(f"publish-depth={args.publish_depth!r}")
                bits.append(f"ico-sizes={list(effective_sizes)}")
            if args.invert:                     bits.append("invert")
            if args.color:                      bits.append(f"color={args.color}")
            if args.trunk_width is not None:    bits.append(f"trunk-width={args.trunk_width}px")
            if args.trunk_lightness is not None: bits.append(f"trunk-lightness={args.trunk_lightness}")
            print(f"  {', '.join(bits)}")
    else:
        active = rendered[ACTIVE]
        active.resize((512, 512), Image.LANCZOS).save(HERE / "scriptree.png", "PNG")
        frames = [active.resize((n, n), Image.LANCZOS) for n in ICO_SIZES]
        frames[0].save(HERE / "scriptree.ico", format="ICO",
                       sizes=[(n, n) for n in ICO_SIZES])
        print(f"Active = {ACTIVE} -> scriptree.png / scriptree.ico")
        if ACTIVE == "05_upright_branch_windows":
            svg = svg_concept_05(1024)
            (HERE / "scriptree.svg").write_text(svg, encoding="utf-8")
            (CONCEPTS / "05_upright_branch_windows.svg").write_text(svg, encoding="utf-8")
            print("Wrote scriptree.svg")

    # When the tree-style icons are active, also publish them to the
    # bundled facet-icon set as ``icon-forest`` — the forest hub falls
    # back to this glyph when no per-forest icon is embedded
    # (see scriptree/shell/forest_controller.py).
    if ACTIVE in _ADAPTIVE_PUBLISH:
        pil_fn, svg_fn, _, max_d = _ADAPTIVE_PUBLISH[ACTIVE]
        forest_max_d = args.publish_depth if args.publish_depth is not None else max_d
        palette = dict(invert=args.invert, color=args.color,
                       trunk_width=args.trunk_width,
                       trunk_lightness=args.trunk_lightness)
        icons_dir = HERE.parent.parent / "icons"
        if icons_dir.is_dir():
            # 256-px PNG matches the existing icon-*.png set
            forest_png = pil_fn(canvas_size=1024, max_depth=forest_max_d, **palette)
            forest_png.resize((256, 256), Image.LANCZOS).save(
                icons_dir / "icon-forest.png", "PNG")
            (icons_dir / "icon-forest.svg").write_text(
                svg_fn(1024, max_depth=forest_max_d, **palette), encoding="utf-8")
            print(f"Published {ACTIVE} -> icons/icon-forest.png / .svg")
        else:
            print(f"icons/ directory not found at {icons_dir}; skipped forest publish")


if __name__ == "__main__":
    main()
