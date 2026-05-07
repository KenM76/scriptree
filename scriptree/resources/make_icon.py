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

from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
CONCEPTS = HERE / "concepts"
CONCEPTS.mkdir(exist_ok=True)

MASTER = 1024
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

ACTIVE = "05_upright_branch_windows"   # which concept populates scriptree.{png,ico}


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
# Entry point
# ---------------------------------------------------------------------------

CONCEPTS_TABLE = {
    "01_node_graph":           concept_node_graph,
    "02_wood_tree_windows":    concept_wood_tree_windows,
    "03_branch_windows":       concept_branch_windows,
    "04_upright_tree_windows": lambda: concept_upright_tree_windows(),
    "05_upright_branch_windows": lambda: concept_upright_branch_windows(),
}


def main() -> None:
    print("Rendering concepts:")
    rendered: dict[str, Image.Image] = {}
    for name, fn in CONCEPTS_TABLE.items():
        img = fn()
        save_concept(name, img)
        rendered[name] = img

    # Publish the active concept at the resources root
    active = rendered[ACTIVE]
    active.resize((512, 512), Image.LANCZOS).save(HERE / "scriptree.png", "PNG")
    frames = [active.resize((n, n), Image.LANCZOS) for n in ICO_SIZES]
    frames[0].save(HERE / "scriptree.ico", format="ICO",
                   sizes=[(n, n) for n in ICO_SIZES])
    print(f"Active = {ACTIVE} -> scriptree.png / scriptree.ico")

    # Emit SVG for the active concept (currently only 05 has an SVG impl)
    if ACTIVE == "05_upright_branch_windows":
        svg = svg_concept_05(1024)
        (HERE / "scriptree.svg").write_text(svg, encoding="utf-8")
        (CONCEPTS / "05_upright_branch_windows.svg").write_text(svg, encoding="utf-8")
        print("Wrote scriptree.svg")


if __name__ == "__main__":
    main()
