"""Wrapper for SwDxfExport/dxf_export.csx.

The .csx script has two runtime-substituted placeholders that ScripTree
can't pass through argv: ``<<OUTPUT_DIR>>`` and the hardcoded ``"KIT"``
BOM configuration name. This wrapper:

  1. Reads the .csx template
  2. Substitutes the placeholders in memory
  3. Writes the result to a temp .csx file
  4. Invokes ``sw_bridge run-script`` on the temp file with an export log
     written into the output directory
  5. Streams sw_bridge's stdout/stderr to this process's stdout/stderr
     so ScripTree's output pane shows it live
  6. Deletes the temp file
  7. Exits with sw_bridge's return code

Usage::

    py -3.12 run_dxf_export.py --output-dir PATH --config NAME [options]

Required:
  --output-dir PATH    Directory where DXFs + export_log.txt will be written.
                       Created if it doesn't exist.
  --config NAME        SolidWorks assembly configuration whose BOM should be
                       used (e.g. "KIT", "Default").

Optional:
  --csx PATH           Override the .csx template path (default: the
                       dxf_export.csx sibling of the SwDxfExport directory).
  --sw-bridge PATH     Override the sw_bridge.exe path.
  --no-pdf             Set generatePdf = false in the temp .csx.
  --timeout SECONDS    Kill sw_bridge after this many seconds (default: 600).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_CSX = Path(
    r"C:/Users/Ken/OneDrive/Kens_Projects/Claude/Solidworks/SwDxfExport/dxf_export.csx"
)
DEFAULT_SW_BRIDGE = Path(
    r"C:/Users/Ken/OneDrive/Kens_Projects/Claude/sw_bridge/bin/Release/net10.0-windows/sw_bridge.exe"
)
DEFAULT_TIMEOUT = 600  # 10 minutes


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run_dxf_export.py",
        description="Run SwDxfExport/dxf_export.csx via sw_bridge with "
                    "placeholder substitution.",
    )
    p.add_argument("--output-dir", required=True,
                   help="Directory where DXFs + export_log.txt will be written.")
    p.add_argument("--config", required=True,
                   help="Assembly configuration for the BOM (e.g. KIT, Default).")
    p.add_argument("--csx", default=str(DEFAULT_CSX),
                   help="Override the .csx template path.")
    p.add_argument("--sw-bridge", default=str(DEFAULT_SW_BRIDGE),
                   help="Override the sw_bridge.exe path.")
    p.add_argument("--no-pdf", action="store_true",
                   help="Set generatePdf = false before running the script.")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                   help=f"Timeout in seconds (default: {DEFAULT_TIMEOUT}).")
    return p.parse_args()


def substitute(csx_text: str, output_dir: Path, config: str, no_pdf: bool) -> str:
    """Apply the two placeholder substitutions + optional PDF toggle.

    Fails loud if a placeholder is missing — silent partial substitution
    would produce a .csx that runs but does the wrong thing.
    """
    if "<<OUTPUT_DIR>>" not in csx_text:
        raise SystemExit(
            "ERROR: <<OUTPUT_DIR>> placeholder not found in the .csx template. "
            "Has it already been pre-substituted?"
        )
    out = csx_text.replace("<<OUTPUT_DIR>>", str(output_dir).replace("\\", "\\\\"))

    # The hardcoded "KIT" config is the 5th arg to InsertBomTable4. We
    # verify uniqueness to avoid replacing any unrelated "KIT" string.
    kit_hits = out.count('"KIT"')
    if kit_hits == 0:
        raise SystemExit(
            'ERROR: Could not find "KIT" in the .csx template. '
            "The BOM configuration may have already been substituted or "
            "the template has been edited."
        )
    if kit_hits > 1:
        raise SystemExit(
            f'ERROR: Found {kit_hits} occurrences of "KIT" in the .csx '
            "template. Cannot safely replace without ambiguity — edit the "
            "template to use a unique placeholder token instead."
        )
    # Escape any double quotes the user may have typed inside their
    # config name (rare, but harmless to be defensive).
    safe_config = config.replace('"', '\\"')
    out = out.replace('"KIT"', f'"{safe_config}"')

    if no_pdf:
        out = out.replace("bool generatePdf = true;", "bool generatePdf = false;")

    return out


def main() -> int:
    args = parse_args()

    csx_path = Path(args.csx)
    if not csx_path.is_file():
        print(f"ERROR: .csx template not found: {csx_path}", file=sys.stderr)
        return 2

    sw_bridge_path = Path(args.sw_bridge)
    if not sw_bridge_path.is_file():
        print(f"ERROR: sw_bridge.exe not found: {sw_bridge_path}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Read + substitute.
    csx_text = csx_path.read_text(encoding="utf-8")
    patched = substitute(csx_text, output_dir, args.config, args.no_pdf)

    # Write to a temp .csx. We use mkstemp so it survives across the
    # subprocess call — NamedTemporaryFile with delete=True would close
    # the handle and break on Windows.
    fd, tmp_path = tempfile.mkstemp(suffix=".csx", prefix="dxf_export_")
    os.close(fd)
    tmp = Path(tmp_path)
    tmp.write_text(patched, encoding="utf-8")

    log_path = output_dir / "export_log.txt"
    print(f"[run_dxf_export] template:  {csx_path}")
    print(f"[run_dxf_export] output:    {output_dir}")
    print(f"[run_dxf_export] config:    {args.config}")
    print(f"[run_dxf_export] temp .csx: {tmp}")
    print(f"[run_dxf_export] log:       {log_path}")
    print(f"[run_dxf_export] invoking sw_bridge (timeout {args.timeout}s)...")
    print()
    sys.stdout.flush()

    argv = [
        str(sw_bridge_path),
        "run-script",
        str(tmp),
        str(log_path),
    ]

    try:
        # inherit=stdio so sw_bridge output streams live through us.
        # This is what lets ScripTree's output pane show progress instead
        # of a long silence followed by a dump.
        result = subprocess.run(argv, timeout=args.timeout, check=False)
        return_code = result.returncode
    except subprocess.TimeoutExpired:
        print(
            f"\n[run_dxf_export] ERROR: sw_bridge exceeded "
            f"{args.timeout}s timeout and was killed.",
            file=sys.stderr,
        )
        return_code = 124
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass

    # Echo the tail of the export log to stdout so the ScripTree output
    # pane shows the summary even though sw_bridge wrote it to a file.
    if log_path.is_file():
        print()
        print(f"[run_dxf_export] --- tail of {log_path.name} ---")
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-40:]:
            print(line)

    return return_code


if __name__ == "__main__":
    sys.exit(main())
