"""
DXF to PDF — Render all DXFs in a directory into a single multi-page PDF.
Each DXF is scaled to fit on its own 11x17 sheet.

Usage: py -3.12 dxf_to_pdf.py <input_dir> <output.pdf> [--sort alpha|size]
Exit:  0=success  1=error
"""

import sys
import os
import math

import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.config import Configuration, ColorPolicy, BackgroundPolicy
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf import bbox

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend (no GUI window)
import warnings
warnings.filterwarnings('ignore', message='Ignoring fixed.*limits')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages


# --- Constants ---
PAGE_W_LANDSCAPE = 17.0   # inches
PAGE_H_LANDSCAPE = 11.0
MARGIN = 0.75              # inches on each side
TITLE_HEIGHT = 0.6         # reserved for title text at top


def get_dxf_files(input_dir, sort_mode='alpha'):
    """Find all .dxf files in directory, excluding _raw.dxf files."""
    files = []
    for f in os.listdir(input_dir):
        if f.lower().endswith('.dxf') and not f.lower().endswith('_raw.dxf'):
            files.append(os.path.join(input_dir, f))

    if sort_mode == 'size':
        files.sort(key=lambda p: os.path.getsize(p), reverse=True)
    else:
        files.sort(key=lambda p: os.path.basename(p).upper())

    return files


def render_dxf_page(dxf_path, pdf, page_num, total_pages):
    """Render a single DXF file as one page in the PDF."""
    part_name = os.path.splitext(os.path.basename(dxf_path))[0]

    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    # Detect units from $INSUNITS header
    insunits = doc.header.get('$INSUNITS', 0)
    unit_labels = {0: '', 1: 'in', 2: 'ft', 3: 'mi', 4: 'mm', 5: 'cm', 6: 'm'}
    unit_label = unit_labels.get(insunits, 'in')
    if not unit_label:
        unit_label = 'in'  # fallback

    # Get bounding box of all entities
    extents = bbox.extents(msp)
    if extents.extmin is None or extents.extmax is None:
        print(f"  SKIP {part_name}: empty geometry")
        return False

    geo_w = extents.size.x
    geo_h = extents.size.y

    if geo_w < 0.001 or geo_h < 0.001:
        print(f"  SKIP {part_name}: degenerate geometry ({geo_w:.4f} x {geo_h:.4f})")
        return False

    # Determine best orientation (landscape vs portrait)
    avail_land_w = PAGE_W_LANDSCAPE - 2 * MARGIN
    avail_land_h = PAGE_H_LANDSCAPE - 2 * MARGIN - TITLE_HEIGHT
    avail_port_w = PAGE_H_LANDSCAPE - 2 * MARGIN
    avail_port_h = PAGE_W_LANDSCAPE - 2 * MARGIN - TITLE_HEIGHT

    scale_land = min(avail_land_w / geo_w, avail_land_h / geo_h)
    scale_port = min(avail_port_w / geo_w, avail_port_h / geo_h)

    if scale_land >= scale_port:
        figsize = (PAGE_W_LANDSCAPE, PAGE_H_LANDSCAPE)
        avail_w, avail_h = avail_land_w, avail_land_h
        scale = scale_land
        orient = 'landscape'
    else:
        figsize = (PAGE_H_LANDSCAPE, PAGE_W_LANDSCAPE)
        avail_w, avail_h = avail_port_w, avail_port_h
        scale = scale_port
        orient = 'portrait'

    # Compute display scale ratio
    if scale >= 1.0:
        scale_text = f"{scale:.1f}:1"
    else:
        scale_text = f"1:{1/scale:.1f}"

    # Create figure with white background
    fig = plt.figure(figsize=figsize, facecolor='white')

    # Title area at top (above the drawing)
    title_top = 1.0 - MARGIN / figsize[1]
    title_line1_y = title_top - 0.02
    title_line2_y = title_line1_y - 0.22 / figsize[1] * 11  # scale relative to page

    # Left side: part name + size on two lines
    fig.text(MARGIN / figsize[0], title_line1_y,
             f"PART: {part_name}",
             fontsize=11, fontweight='bold', va='top', ha='left',
             fontfamily='monospace')
    fig.text(MARGIN / figsize[0], title_line2_y,
             f"Size: {geo_w:.3f} x {geo_h:.3f} {unit_label}",
             fontsize=8, va='top', ha='left',
             fontfamily='monospace', color='#555555')

    # Right side: scale + page on two lines
    right_x = 1.0 - MARGIN / figsize[0]
    fig.text(right_x, title_line1_y,
             f"Scale: {scale_text}",
             fontsize=8, va='top', ha='right',
             fontfamily='monospace', color='#555555')
    fig.text(right_x, title_line2_y,
             f"Page {page_num} of {total_pages}",
             fontsize=8, va='top', ha='right',
             fontfamily='monospace', color='#555555')

    # Drawing area (below the title block)
    draw_top = title_line2_y - 0.15 / figsize[1] * 11
    draw_bottom = MARGIN / figsize[1]
    ax = fig.add_axes([
        MARGIN / figsize[0],                     # left
        draw_bottom,                             # bottom
        (figsize[0] - 2 * MARGIN) / figsize[0],  # width
        draw_top - draw_bottom                   # height
    ])

    # White background, no fill behind geometry
    ax.set_facecolor('white')

    # Render DXF entities — black lines on white background
    ctx = RenderContext(doc)
    draw_config = Configuration(
        color_policy=ColorPolicy.BLACK,
        background_policy=BackgroundPolicy.OFF,
    )
    backend = MatplotlibBackend(ax, adjust_figure=False)
    frontend = Frontend(ctx, backend, config=draw_config)
    frontend.draw_layout(msp, finalize=True)

    # Set equal aspect ratio and fit to geometry
    ax.set_aspect('equal')

    # Add some padding around geometry
    pad = max(geo_w, geo_h) * 0.02
    ax.set_xlim(extents.extmin.x - pad, extents.extmax.x + pad)
    ax.set_ylim(extents.extmin.y - pad, extents.extmax.y + pad)

    # Remove axis ticks/labels for clean look
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.5)
        spine.set_color('#cccccc')

    pdf.savefig(fig, facecolor='white')
    plt.close(fig)
    return True


def run_pdf(input_dir, output_pdf, sort_mode="alpha"):
    """
    Render all DXFs in a directory into a multi-page PDF.

    Args:
        input_dir: directory containing DXF files
        output_pdf: path to write the PDF
        sort_mode: "alpha" or "size"

    Returns:
        int: exit code (0 = success, 1 = error)
    """
    if not os.path.isdir(input_dir):
        print(f"ERROR: '{input_dir}' is not a directory")
        return 1

    dxf_files = get_dxf_files(input_dir, sort_mode)
    if not dxf_files:
        print(f"No DXF files found in '{input_dir}'")
        return 1

    print(f"=== DXF to PDF ===")
    print(f"Input: {input_dir} ({len(dxf_files)} DXF files)")
    print(f"Output: {output_pdf}")
    print(f"Sort: {sort_mode}")

    rendered = 0
    skipped = 0

    with PdfPages(output_pdf) as pdf:
        for i, dxf_path in enumerate(dxf_files, 1):
            name = os.path.basename(dxf_path)
            print(f"  [{i}/{len(dxf_files)}] {name}...", end='')
            try:
                ok = render_dxf_page(dxf_path, pdf, i, len(dxf_files))
                if ok:
                    rendered += 1
                    print(" OK")
                else:
                    skipped += 1
            except Exception as ex:
                skipped += 1
                print(f" ERROR: {ex}")

    file_size = os.path.getsize(output_pdf)
    print(f"\n=== Done ===")
    print(f"Rendered: {rendered} pages")
    if skipped:
        print(f"Skipped: {skipped}")
    print(f"PDF: {output_pdf} ({file_size / 1024:.0f} KB)")
    return 0
