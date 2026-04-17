"""
dxf-export — End-to-end DXF export pipeline for plasma-cutting plate parts
from a SolidWorks assembly.

Pipeline (runs by default):
  1. SolidWorks stage: opens the assembly, inserts a BOM using the given
     configuration and BOM template, exports each PLATE/SHEET part as a
     raw DXF + tapped-holes sidecar.
  2. Cleanup stage: runs dxf-cleanup on every raw DXF (dangler removal,
     countersink/tapped-hole removal, AutoCAD LT 2004 compatibility).
  3. PDF stage: runs dxf-to-pdf to produce a single multi-page 11x17 PDF
     of all cleaned plates.

Flags --skip-cleanup and --skip-pdf disable stages 2 and 3 respectively.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_SW_BRIDGE = r"C:\Users\Ken\OneDrive\Kens_Projects\Claude\sw_bridge\bin\Release\net10.0-windows\sw_bridge.exe"
DEFAULT_BOM_TEMPLATE = str(Path(__file__).resolve().parent / "Claude_to_dxf.sldbomtbt")

HERE = Path(__file__).resolve().parent
DXF_EXPORT_SW_CSX = HERE / "dxf_export_sw.csx"

# Sibling tool directories (same ScripTreeApps parent)
APPS_ROOT = HERE.parent
DXF_CLEANUP_DIR = APPS_ROOT / "dxf-cleanup"
DXF_TO_PDF_DIR = APPS_ROOT / "dxf-to-pdf"


def run_sw_stage(
    sw_bridge_exe: str,
    assembly_path: str,
    config_name: str,
    output_dir: str,
    bom_template: str,
    log_file: str,
) -> int:
    """Run the SolidWorks export stage via sw_bridge.

    Passes parameters to the .csx script via environment variables.
    """
    env = os.environ.copy()
    env["DXFEXPORT_ASSEMBLY"] = assembly_path
    env["DXFEXPORT_CONFIG"] = config_name
    env["DXFEXPORT_OUTPUT_DIR"] = output_dir
    env["DXFEXPORT_BOM_TEMPLATE"] = bom_template

    cmd = [sw_bridge_exe, "run-script", str(DXF_EXPORT_SW_CSX), log_file]
    print("=" * 60)
    print("STAGE 1: SolidWorks export")
    print("=" * 60)
    print(f"  Assembly:     {assembly_path}")
    print(f"  Config:       {config_name}")
    print(f"  Output dir:   {output_dir}")
    print(f"  BOM template: {bom_template}")
    print(f"  Log file:     {log_file}")
    print()

    try:
        result = subprocess.run(cmd, env=env, check=False)
    except FileNotFoundError:
        print(f"ERROR: sw_bridge.exe not found at: {sw_bridge_exe}")
        return 1

    # Print the log file contents so the user sees the per-part progress
    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                print(f.read())
        except Exception:
            pass

    return result.returncode


def read_unit_from_sidecar(sidecar_path: str) -> int:
    """Read the #unit=N header from a tapped sidecar file, default 3 (inches)."""
    if not os.path.exists(sidecar_path):
        return 3
    try:
        with open(sidecar_path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#unit="):
                    return int(line[6:])
                if not line.startswith("#"):
                    break
    except Exception:
        pass
    return 3


def strip_unit_header(sidecar_path: str) -> str:
    """Create a temporary sidecar file with the #unit header stripped,
    since dxf-cleanup's sidecar parser expects only u,v,dia lines.
    Returns the temp file path, or "" if no tapped holes were recorded."""
    if not os.path.exists(sidecar_path):
        return ""
    try:
        with open(sidecar_path, "r") as f:
            lines = [line for line in f if not line.strip().startswith("#")]
        if not lines:
            return ""
        tmp_path = sidecar_path + ".stripped"
        with open(tmp_path, "w") as f:
            f.writelines(lines)
        return tmp_path
    except Exception:
        return ""


def run_cleanup_stage(output_dir: str) -> tuple[int, int]:
    """Run dxf-cleanup on every raw DXF in the output directory.

    Returns (success_count, fail_count).
    """
    print("=" * 60)
    print("STAGE 2: DXF cleanup")
    print("=" * 60)

    # Import the cleanup core directly — avoid the subprocess overhead per-file
    sys.path.insert(0, str(DXF_CLEANUP_DIR))
    try:
        from dxf_cleanup_core import run_cleanup
    except ImportError as e:
        print(f"ERROR: Could not import dxf_cleanup_core: {e}")
        return (0, 0)

    # Find all raw DXFs in the output directory
    out_path = Path(output_dir)
    raw_files = sorted([
        p for p in out_path.glob("*_raw.dxf")
    ])

    if not raw_files:
        print("  No raw DXF files found in output directory.")
        return (0, 0)

    print(f"  Found {len(raw_files)} raw DXFs to clean")
    success = 0
    fail = 0

    for raw in raw_files:
        base = raw.name[:-len("_raw.dxf")]
        clean_path = out_path / f"{base}.dxf"
        sidecar_path = out_path / f"{base}_tapped.txt"

        # Read the unit code recorded by the SW stage
        sw_unit = read_unit_from_sidecar(str(sidecar_path))

        # Strip the #unit header so dxf-cleanup's sidecar parser sees
        # only u,v,dia lines
        stripped_sidecar = strip_unit_header(str(sidecar_path))

        print(f"  [{base}] unit={sw_unit}...", end="", flush=True)
        try:
            result = run_cleanup(
                input_path=str(raw),
                output_path=str(clean_path),
                tapped_sidecar_path=stripped_sidecar or None,
                sw_unit=sw_unit,
            )
        except Exception as e:
            print(f" ERROR: {e}")
            fail += 1
            continue

        # If cleanup didn't change anything, delete the raw file
        # (the cleanup core prints "MATCH:true" in that case — we don't
        # need to check that here because it already made the call)
        try:
            # Check if raw is identical to clean (very simple: same size)
            if raw.exists() and clean_path.exists():
                if raw.stat().st_size == clean_path.stat().st_size:
                    # Not a reliable match test — use dxf-cleanup's own
                    # MATCH detection instead, via exit code or output
                    pass
        except Exception:
            pass

        # Always delete the raw file after successful cleanup
        # (match-detection already happened inside run_cleanup; whether
        # the raw is kept is a user preference — we keep the clean one
        # and discard the raw since the user can always re-run).
        try:
            if raw.exists():
                raw.unlink()
        except Exception:
            pass

        # Also delete the sidecar files
        try:
            if sidecar_path.exists():
                sidecar_path.unlink()
        except Exception:
            pass
        if stripped_sidecar:
            try:
                os.remove(stripped_sidecar)
            except Exception:
                pass

        if result == 0 or result == 2:
            print(" OK")
            success += 1
        else:
            print(f" FAIL (exit {result})")
            fail += 1

    print(f"\n  Cleanup: {success} OK, {fail} failed")
    print()
    return (success, fail)


def run_pdf_stage(output_dir: str, pdf_name: str = "all_plates.pdf") -> int:
    """Run dxf-to-pdf on the cleaned DXFs in the output directory."""
    print("=" * 60)
    print("STAGE 3: PDF generation")
    print("=" * 60)

    sys.path.insert(0, str(DXF_TO_PDF_DIR))
    try:
        from dxf_to_pdf_core import run_pdf
    except ImportError as e:
        print(f"ERROR: Could not import dxf_to_pdf_core: {e}")
        return 1

    pdf_path = os.path.join(output_dir, pdf_name)
    try:
        result = run_pdf(
            input_dir=output_dir,
            output_pdf=pdf_path,
            sort_mode="alpha",
        )
    except Exception as e:
        print(f"ERROR: PDF generation failed: {e}")
        return 1

    return result


def main() -> int:
    p = argparse.ArgumentParser(
        prog="dxf-export",
        description=(
            "End-to-end DXF export pipeline for plasma-cutting plate parts from "
            "a SolidWorks assembly. Runs SolidWorks export, DXF cleanup, and PDF "
            "generation by default. Use --skip-cleanup or --skip-pdf to stop early."
        ),
    )
    p.add_argument(
        "assembly",
        metavar="ASSEMBLY",
        help="Path to the SolidWorks assembly file (.sldasm)",
    )
    p.add_argument(
        "config",
        metavar="CONFIG",
        help="Name of the assembly configuration to use for the BOM (e.g. DXFS, KIT)",
    )
    p.add_argument(
        "output_dir",
        metavar="OUTPUT_DIR",
        help="Directory to write the DXF files into",
    )
    p.add_argument(
        "-t", "--bom-template",
        metavar="FILE",
        default=DEFAULT_BOM_TEMPLATE,
        help=f"Path to the BOM template file (default: {DEFAULT_BOM_TEMPLATE})",
    )
    p.add_argument(
        "-b", "--sw-bridge",
        metavar="FILE",
        default=DEFAULT_SW_BRIDGE,
        help=f"Path to sw_bridge.exe (default: {DEFAULT_SW_BRIDGE})",
    )
    p.add_argument(
        "-l", "--log-file",
        metavar="FILE",
        default="",
        help="Path to write the SolidWorks stage log file (default: <output_dir>/dxf_export_log.txt)",
    )
    p.add_argument(
        "--skip-cleanup",
        action="store_true",
        help="Skip the DXF cleanup stage (raw DXFs will be left in the output folder)",
    )
    p.add_argument(
        "--skip-pdf",
        action="store_true",
        help="Skip the PDF generation stage",
    )
    args = p.parse_args()

    assembly_path = str(Path(args.assembly).resolve())
    output_dir = str(Path(args.output_dir).resolve())
    bom_template = str(Path(args.bom_template).resolve())
    sw_bridge = str(Path(args.sw_bridge).resolve())

    log_file = args.log_file or os.path.join(output_dir, "dxf_export_log.txt")

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Stage 1: SolidWorks export
    sw_rc = run_sw_stage(
        sw_bridge_exe=sw_bridge,
        assembly_path=assembly_path,
        config_name=args.config,
        output_dir=output_dir,
        bom_template=bom_template,
        log_file=log_file,
    )
    if sw_rc != 0:
        print(f"\nSolidWorks stage failed (exit {sw_rc}). Skipping remaining stages.")
        return sw_rc

    # Stage 2: DXF cleanup
    if not args.skip_cleanup:
        ok, fail = run_cleanup_stage(output_dir)
        if fail > 0 and ok == 0:
            print("\nAll cleanup failed. Skipping PDF stage.")
            return 1
    else:
        print("STAGE 2: DXF cleanup — SKIPPED (--skip-cleanup)\n")

    # Stage 3: PDF generation
    if not args.skip_pdf:
        pdf_rc = run_pdf_stage(output_dir)
        if pdf_rc != 0:
            print(f"\nPDF stage failed (exit {pdf_rc}).")
            return pdf_rc
    else:
        print("STAGE 3: PDF generation — SKIPPED (--skip-pdf)\n")

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"Output: {output_dir}")
    print(">>> WARNING: REVIEW ALL DXFs BEFORE SENDING TO PLASMA TABLE <<<")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
