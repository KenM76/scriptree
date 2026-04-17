"""
dxf-cleanup — Clean up raw SolidWorks DXF exports into plasma-ready profiles.

Removes chamfer/fillet projection artifacts, dangling entities, countersink
circles, and optionally tapped holes. Writes an AutoCAD 2000 (R2000) DXF
with AutoCAD LT 2004 compatibility (MATERIAL objects and group code 94
stripped).
"""

import argparse
from pathlib import Path

from dxf_cleanup_core import run_cleanup


def main() -> int:
    p = argparse.ArgumentParser(
        prog="dxf-cleanup",
        description="Clean up a raw SolidWorks DXF export into a plasma-ready profile.",
    )
    p.add_argument(
        "input",
        metavar="INPUT",
        help="Path to the raw DXF file to clean up",
    )
    p.add_argument(
        "output",
        metavar="OUTPUT",
        help="Path to write the cleaned DXF file",
    )
    p.add_argument(
        "-t", "--tapped-sidecar",
        metavar="FILE",
        default="",
        help="Optional path to a tapped-holes sidecar file (u,v,diameter per line)",
    )
    p.add_argument(
        "-u", "--unit",
        type=int,
        default=3,
        choices=[0, 1, 2, 3, 4, 5],
        help="SolidWorks length unit code: 0=mm, 1=cm, 2=m, 3=in (default), 4=ft, 5=ft-in",
    )
    args = p.parse_args()

    input_path = str(Path(args.input).resolve())
    output_path = str(Path(args.output).resolve())
    tapped_path = str(Path(args.tapped_sidecar).resolve()) if args.tapped_sidecar else None

    return run_cleanup(
        input_path=input_path,
        output_path=output_path,
        tapped_sidecar_path=tapped_path,
        sw_unit=args.unit,
    )


if __name__ == "__main__":
    raise SystemExit(main())
