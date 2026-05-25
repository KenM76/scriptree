"""Generate ScripTree app icons and concept variants.

Running this script produces:

* ``concepts/01_node_graph.{png,ico}`` — the original clean
  node-graph concept: mint branches, circular nodes, ">" glyph at root.
* ``concepts/02_wood_tree_windows.{png,ico}`` — a literal brown tree
  whose canopy is a cluster of tiny app windows.
* ``concepts/03_branch_windows.{png,ico}`` — node-graph branches (from
  concept 01) with tiny app windows hanging at the branch tips instead
  of plain dots (current working favourite).

The "active" icon in the resources root (``scriptree.png`` /
``scriptree.ico``) is rebuilt from the chosen concept — set
``ACTIVE`` below.
"""
from __future__ import annotations

import argparse
import io
import math
import struct
from pathlib import Path
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
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return m


def vertical_gradient(size: int, top, bot) -> Image.Image:
    col = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        col.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return col.resize((size, size))


def make_tile(size: int, bg_top, bg_bot, halo=None) -> Image.Image:
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
    s = MASTER
    tile = make_tile(s, (34, 52, 82), (18, 28, 46),
                     halo=(int(s * 0.5), int(s * 0.2), int(s * 0.5),
                           (255, 255, 255), 28))
    d = ImageDraw.Draw(tile)

    accent = (86, 214, 168)
    accent_hi = (176, 246, 214)
    prompt = (255, 214, 102)

    def px(x, y): return (int(x * s), int(y * s))

    line_w = int(s * 0.028)
    node_r = int(s * 0.055)
    leaf_r = int(s * 0.045)

    root = (0.28, 0.26)
    t1 = [(0.58, 0.26), (0.58, 0.50), (0.58, 0.74)]
    t2 = [(0.82, 0.42), (0.82, 0.58)]

    d.line([px(root[0], root[1]), px(root[0], t1[-1][1])], fill=accent, width=line_w)
    for (bx, by) in t1:
        d.line([px(root[0], by), px(bx, by)], fill=accent, width=line_w)
    mid = t1[1]
    d.line([px(mid[0], mid[1]), px(mid[0], t2[-1][1])], fill=accent, width=line_w)
    for (bx, by) in t2:
        d.line([px(mid[0], by), px(bx, by)], fill=accent, width=line_w)

    def disc(p, r, fill):
        cx, cy = px(*p)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)

    for p in t1 + t2:
        disc(p, leaf_r, accent)
    disc(root, node_r + int(s * 0.012), accent_hi)
    disc(root, node_r, (22, 36, 58))

    cx, cy = px(*root)
    stroke = int(s * 0.022)
    arm = int(node_r * 0.62)
    d.line([(cx - arm // 2, cy - arm), (cx + arm // 2, cy), (cx - arm // 2, cy + arm)],
           fill=prompt, width=stroke, joint="curve")
    return tile


# ---------------------------------------------------------------------------
# Concept 02 — wood tree with window-leaf canopy
# ---------------------------------------------------------------------------

def concept_wood_tree_windows() -> Image.Image:
    s = MASTER
    tile = make_tile(s, (22, 54, 66), (9, 22, 30),
                     halo=(int(s * 0.5), int(s * 0.38), int(s * 0.32),
                           (255, 210, 130), 70))

    # canopy backing blobs
    CG_A = (86, 204, 138); CG_B = (42, 150, 102)
    canopy = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    cd = ImageDraw.Draw(canopy)
    for (cx, cy, r, color, a) in [
        (0.50, 0.38, 0.30, CG_B, 220),
        (0.36, 0.34, 0.20, CG_A, 230),
        (0.64, 0.34, 0.20, CG_A, 230),
        (0.50, 0.22, 0.19, CG_A, 230),
        (0.30, 0.46, 0.16, CG_B, 220),
        (0.70, 0.46, 0.16, CG_B, 220),
    ]:
        cx, cy, r = int(cx * s), int(cy * s), int(r * s)
        cd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*color, a))
    canopy = canopy.filter(ImageFilter.GaussianBlur(s * 0.008))
    tile = Image.alpha_composite(tile, canopy)
    d = ImageDraw.Draw(tile)

    TRUNK = (138, 92, 46); TRUNK_HI = (190, 134, 74); PROMPT = (252, 220, 128)

    def px(x, y): return (int(x * s), int(y * s))

    d.polygon([px(0.47, 0.48), px(0.53, 0.48), px(0.56, 0.88), px(0.44, 0.88)],
              fill=TRUNK)
    d.polygon([px(0.475, 0.48), px(0.495, 0.48), px(0.475, 0.88), px(0.455, 0.88)],
              fill=TRUNK_HI)

    base_y = int(0.88 * s)
    for dx in (-1, 1):
        cx = int((0.50 + dx * 0.06) * s)
        r = int(s * 0.05)
        d.pieslice((cx - r, base_y - r, cx + r, base_y + r),
                   0 if dx > 0 else 90, 90 if dx > 0 else 180, fill=TRUNK)

    branch_w = int(s * 0.028)
    for (x2, y2) in [(0.30, 0.48), (0.70, 0.48), (0.50, 0.30)]:
        d.line([px(0.50, 0.55), px(x2, y2)], fill=TRUNK, width=branch_w)

    cx, cy = px(0.50, 0.70)
    arm = int(s * 0.035); stroke = int(s * 0.018)
    d.line([(cx - arm, cy - arm), (cx, cy), (cx - arm, cy + arm)],
           fill=PROMPT, width=stroke, joint="curve")
    under_w = int(s * 0.07)
    d.rounded_rectangle((cx + int(s * 0.012), cy + arm - stroke // 2,
                         cx + int(s * 0.012) + under_w, cy + arm + stroke // 2),
                        radius=stroke // 2, fill=PROMPT)

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
    s = MASTER
    tile = make_tile(s, (34, 52, 82), (18, 28, 46),
                     halo=(int(s * 0.5), int(s * 0.2), int(s * 0.5),
                           (255, 255, 255), 28))
    d = ImageDraw.Draw(tile)

    accent = (86, 214, 168)
    accent_hi = (176, 246, 214)
    prompt = (255, 214, 102)

    def px(x, y): return (int(x * s), int(y * s))

    line_w = int(s * 0.028)
    node_r = int(s * 0.055)

    # Layout: root at left-centre, three branches fanning to the right.
    # Each branch terminates in a window-leaf. The middle branch also has
    # a short sub-spine with two secondary window-leaves.
    root = (0.18, 0.50)
    t1  = [(0.50, 0.22), (0.50, 0.50), (0.50, 0.78)]
    t2  = [(0.80, 0.36), (0.80, 0.64)]  # secondaries off middle branch

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


def _grayscale_levels(max_depth: int,
                      base_branch: int = 78,
                      base_node:   int = 132,
                      step:        int = 14,
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
    """
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
                               ) -> Image.Image:
    """Render the grayscale fractal-tree icon onto a transparent canvas.

    ``trunk_width`` (optional) overrides the trunk stroke thickness.
    Expressed in pixels at the 1024-reference canvas, scaled
    proportionally for other canvas sizes — so passing 50 means "50 px
    at 1024, ~12 px at 256, ~3 px at 64."  The branch widths are left
    untouched: only the trunk gets thicker / thinner, the canopy stays
    at its fractal-derived weights.
    """
    s = canvas_size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)

    levels = _grayscale_levels(max_depth, invert=invert, color=color)
    trunk_color = levels[0][0]          # same as depth-0 branch
    cap_color   = levels[0][1]          # depth-0 node colour at the seam

    # Stroke widths follow the fractal's scaling sequence.  The trunk
    # is the "level −1" width by default (one step up from the depth-0
    # branch stroke), but ``trunk_width`` can override it — useful when
    # the icon is being placed alongside other glyphs whose strokes
    # have a different reference thickness.  The value is interpreted at
    # the 1024-reference canvas and scaled proportionally for any other.
    line_w  = max(2, int(round(s * 0.022)))
    if trunk_width is not None:
        trunk_w = max(2, int(round(trunk_width * (s / 1024.0))))
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
    # meet at it.
    initial_side = s * 0.155
    node_r = max(2, int(round(s * 0.014)))
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
                               trunk_width: int | None = None) -> str:
    S = canvas_size
    levels = _grayscale_levels(max_depth, invert=invert, color=color)
    trunk_rgb, cap_rgb = levels[0]
    trunk_color = f'rgb({trunk_rgb[0]},{trunk_rgb[1]},{trunk_rgb[2]})'
    cap_color   = f'rgb({cap_rgb[0]},{cap_rgb[1]},{cap_rgb[2]})'

    line_w  = S * 0.022
    if trunk_width is not None:
        trunk_w = trunk_width * (S / 1024.0)
    else:
        trunk_w = line_w / _BRANCH_SCALE

    cx       = 0.50 * S
    ty0, ty1 = 0.66 * S, 0.93 * S
    trunk = (f'<rect x="{cx-trunk_w/2:.2f}" y="{ty0:.2f}" '
             f'width="{trunk_w:.2f}" height="{ty1-ty0:.2f}" '
             f'rx="{trunk_w/2:.2f}" ry="{trunk_w/2:.2f}" fill="{trunk_color}"/>')

    trunk_top    = (0.50 * S, 0.66 * S)
    initial_side = S * 0.155
    node_r       = S * 0.014
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
             "Default: ./scriptree_custom.png next to this script.",
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
        help="Override the trunk stroke thickness, in pixels at the "
             "1024-reference canvas (scaled proportionally for other "
             "canvas sizes — 50 means '50 px at 1024, ~12 px at 256').  "
             "Default: derived from the fractal scaling ladder "
             "(~40 px at 1024).  Only the trunk is affected; the canopy "
             "branches keep their fractal-derived weights.  Concept 10 only.",
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
    """Render one PNG of one concept at a chosen depth and size."""
    name = args.concept or ACTIVE
    if name not in _ADAPTIVE_CONCEPTS:
        raise SystemExit(
            f"--depth/--size require an adaptive concept (one of "
            f"{sorted(_ADAPTIVE_CONCEPTS)}); got {name!r}.")
    if ((args.invert or args.color or args.trunk_width is not None)
            and name != "10_grayscale_leveled_tree"):
        raise SystemExit(
            f"--invert / --color / --trunk-width only affect concept "
            f"10_grayscale_leveled_tree; got concept {name!r}.  Re-run "
            f"without those flags or pick --concept 10_grayscale_leveled_tree.")
    if args.trunk_width is not None and args.trunk_width < 1:
        raise SystemExit("--trunk-width must be at least 1 px.")
    pil_fn = _ADAPTIVE_CONCEPTS[name][0]
    depth  = args.depth if args.depth is not None else 4
    size   = args.size  if args.size  is not None else MASTER

    # Validate --color early so the user gets a clean error before render
    if args.color:
        _parse_hex_color(args.color)  # raises ValueError if malformed

    # Render at the requested size directly when ≥ 256, else render at a
    # higher working resolution and downsample for clean antialiasing.
    work = max(256, size)
    img  = pil_fn(canvas_size=work, max_depth=depth,
                  invert=args.invert, color=args.color,
                  trunk_width=args.trunk_width)
    if work != size:
        img = img.resize((size, size), Image.LANCZOS)

    out = args.out or (HERE / "scriptree_custom.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    palette_note = ""
    bits = []
    if args.invert:                    bits.append("invert")
    if args.color:                     bits.append(f"color={args.color}")
    if args.trunk_width is not None:   bits.append(f"trunk-width={args.trunk_width}px")
    if bits:
        palette_note = f", {', '.join(bits)}"
    print(f"Wrote {out}  ({name}, depth={depth}, size={size}px{palette_note})")


# Adaptive concepts.  Renderers all accept ``invert`` / ``color`` kwargs
# for forward-compat with the palette CLI flags; concepts 06/08/09 ignore
# them (their palettes are baked in), only concept 10 honours them.
def _wrap_palette_pil(fn):
    return lambda *, canvas_size, max_depth, invert=False, color=None, trunk_width=None: fn(canvas_size, max_depth)

def _wrap_palette_svg(fn):
    return lambda S, max_depth, invert=False, color=None, trunk_width=None: fn(S, max_depth)

_ADAPTIVE_CONCEPTS = {
    # name -> (pil_renderer, svg_renderer, size→depth fn, default max_depth)
    "06_hex_fractal_tree":       (_wrap_palette_pil(pil_fractal_tree),       _wrap_palette_svg(svg_fractal_tree),       None, 4),
    "08_mono_fractal_tree":      (_wrap_palette_pil(pil_mono_fractal_tree),      _wrap_palette_svg(svg_mono_fractal_tree),      None, 4),
    "09_grayscale_fractal_tree": (_wrap_palette_pil(pil_grayscale_fractal_tree), _wrap_palette_svg(svg_grayscale_fractal_tree), None, 4),
    # Concept 10 honours invert + color + trunk_width directly.
    "10_grayscale_leveled_tree": (
        lambda *, canvas_size, max_depth, invert=False, color=None, trunk_width=None:
            pil_grayscale_leveled_tree(canvas_size, max_depth,
                                       invert=invert, color=color,
                                       trunk_width=trunk_width),
        lambda S, max_depth, invert=False, color=None, trunk_width=None:
            svg_grayscale_leveled_tree(S, max_depth,
                                       invert=invert, color=color,
                                       trunk_width=trunk_width),
        None, 4),
}


def main() -> None:
    args = _build_cli().parse_args()
    single_shot = (args.depth is not None or args.size is not None
                   or args.out is not None)
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

        # --invert / --color / --trunk-width only mean anything for
        # concept 10.  Reject early instead of silently dropping intent.
        palette_active = (args.invert or args.color
                          or args.trunk_width is not None)
        if palette_active and ACTIVE != "10_grayscale_leveled_tree":
            raise SystemExit(
                f"--invert / --color / --trunk-width only affect "
                f"10_grayscale_leveled_tree; active concept is {ACTIVE!r}.  "
                f"Re-run without those flags or switch ACTIVE.")
        if args.color:
            _parse_hex_color(args.color)   # validate early
        if args.trunk_width is not None and args.trunk_width < 1:
            raise SystemExit("--trunk-width must be at least 1 px.")
        palette = dict(invert=args.invert, color=args.color,
                       trunk_width=args.trunk_width)

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
        if publish_overrides or args.invert or args.color or args.trunk_width is not None:
            bits = []
            if publish_overrides:
                bits.append(f"publish-depth={args.publish_depth!r}")
                bits.append(f"ico-sizes={list(effective_sizes)}")
            if args.invert:                  bits.append("invert")
            if args.color:                   bits.append(f"color={args.color}")
            if args.trunk_width is not None: bits.append(f"trunk-width={args.trunk_width}px")
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
                       trunk_width=args.trunk_width)
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
