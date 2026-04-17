"""
dxf-to-pdf — Render all DXFs in a directory into a single multi-page PDF.

Each DXF is rendered on its own 11x17 sheet with auto-orientation, scale
ratio, and part information in a title block. Background is white,
geometry is drawn in black for plasma-table-friendly output.
"""

import argparse
from pathlib import Path

from dxf_to_pdf_core import run_pdf


def main() -> int:
    p = argparse.ArgumentParser(
        prog="dxf-to-pdf",
        description="Render all DXFs in a directory into a single multi-page PDF, one 11x17 sheet per DXF.",
    )
    p.add_argument(
        "input_dir",
        metavar="INPUT_DIR",
        help="Path to the directory containing DXF files to render",
    )
    p.add_argument(
        "output",
        metavar="OUTPUT",
        help="Path to write the output PDF file",
    )
    p.add_argument(
        "-s", "--sort",
        choices=["alpha", "size"],
        default="alpha",
        help="Sort order for pages: alpha (filename) or size (largest first)",
    )
    args = p.parse_args()

    input_dir = str(Path(args.input_dir).resolve())
    output_pdf = str(Path(args.output).resolve())

    return run_pdf(
        input_dir=input_dir,
        output_pdf=output_pdf,
        sort_mode=args.sort,
    )


if __name__ == "__main__":
    raise SystemExit(main())
