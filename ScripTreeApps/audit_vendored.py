#!/usr/bin/env python3
"""Audit every per-tool ``lib/`` folder under ``ScripTreeApps/``.

Walks this directory and, for each ``<tool>/lib/requirements.txt`` it
finds, extracts:

- the declared Python interpreter (from the ``# python:`` hint)
- the pinned packages + their versions
- the total on-disk size of ``<tool>/lib/pypi/``
- whether the install appears consistent (every pinned pkg present)

Writes a Markdown report to ``ScripTreeApps/VENDORED_DEPS.md``.

Usage::

    python ScripTreeApps/audit_vendored.py            # write the file
    python ScripTreeApps/audit_vendored.py --stdout   # also print it
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORT = HERE / "VENDORED_DEPS.md"

_PINS_RE = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s#]+)"
)


def _parse_requirements(req: Path) -> tuple[str, list[tuple[str, str]]]:
    """Return ``(python_cmd, [(pkg, version), ...])`` for this tool."""
    py = ""
    pins: list[tuple[str, str]] = []
    for raw in req.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            stripped = line.lstrip("#").strip()
            if not py and stripped.lower().startswith("python:"):
                py = stripped.split(":", 1)[1].strip()
            continue
        m = _PINS_RE.match(raw)
        if m:
            pins.append((m.group(1).lower(), m.group(2)))
    return py or "(default)", pins


def _folder_size_mb(p: Path) -> float:
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / (1024 * 1024)


def _installed_pkgs(pypi: Path) -> dict[str, str]:
    """Read ``.dist-info/METADATA`` entries to learn what's actually there."""
    out: dict[str, str] = {}
    if not pypi.is_dir():
        return out
    for di in pypi.glob("*.dist-info"):
        meta = di / "METADATA"
        if not meta.is_file():
            continue
        name = version = ""
        for line in meta.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Name:"):
                name = line.split(":", 1)[1].strip().lower()
            elif line.startswith("Version:"):
                version = line.split(":", 1)[1].strip()
            if name and version:
                break
        if name:
            out[name] = version
    return out


def _relpath(p: Path) -> str:
    try:
        return str(p.relative_to(HERE)).replace("\\", "/")
    except ValueError:
        return str(p)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--stdout", action="store_true",
        help="Also print the report to stdout.",
    )
    args = ap.parse_args()

    reqs = sorted(HERE.rglob("lib/requirements.txt"))
    reqs = [r for r in reqs if "pypi" not in r.parts]

    lines: list[str] = []
    lines.append("# ScripTreeApps vendored dependencies")
    lines.append("")
    lines.append(
        f"_Generated {time.strftime('%Y-%m-%d %H:%M:%S')} by "
        f"`audit_vendored.py`. Do not edit by hand — re-run the "
        f"script to refresh._"
    )
    lines.append("")
    lines.append(
        "Every ScripTree app that vendors its own Python packages "
        "should live under `ScripTreeApps/` with a "
        "`<tool>/lib/requirements.txt` + `<tool>/lib/pypi/` layout "
        "(mirroring ScripTree's own top-level `lib/`). This report "
        "is an auditable snapshot of what's installed where."
    )
    lines.append("")

    if not reqs:
        lines.append("_No per-tool `lib/requirements.txt` files found._")
        REPORT.write_text("\n".join(lines), encoding="utf-8")
        print(f"Wrote {REPORT}")
        return 0

    lines.append("## Summary")
    lines.append("")
    lines.append(
        "| Tool | Python | Packages | Size |"
    )
    lines.append(
        "|---|---|---|---|"
    )

    problem_sections: list[str] = []
    total_size = 0.0
    for req in reqs:
        tool_dir = req.parent.parent
        name = tool_dir.relative_to(HERE).as_posix()
        py, pins = _parse_requirements(req)
        pypi = req.parent / "pypi"
        size = _folder_size_mb(pypi) if pypi.is_dir() else 0.0
        total_size += size
        lines.append(
            f"| [{name}](#{name.replace('/', '').replace('-', '').lower()}) "
            f"| `{py}` | {len(pins)} | {size:.1f} MB |"
        )

    lines.append(f"| **Total** | | | **{total_size:.1f} MB** |")
    lines.append("")

    # Per-tool detail.
    for req in reqs:
        tool_dir = req.parent.parent
        name = tool_dir.relative_to(HERE).as_posix()
        py, pins = _parse_requirements(req)
        pypi = req.parent / "pypi"
        installed = _installed_pkgs(pypi)

        anchor = name.replace("/", "").replace("-", "").lower()
        lines.append(f'<a id="{anchor}"></a>')
        lines.append(f"## {name}")
        lines.append("")
        lines.append(f"- **Path:** `ScripTreeApps/{name}/`")
        lines.append(f"- **Requirements:** `{_relpath(req)}`")
        lines.append(f"- **Interpreter:** `{py}`")
        lines.append(
            f"- **Install size:** {_folder_size_mb(pypi):.1f} MB "
            f"(`{_relpath(pypi)}/`)"
        )
        lines.append("")
        lines.append("| Package | Pinned | Installed | Status |")
        lines.append("|---|---|---|---|")

        per_tool_problems: list[str] = []
        for pkg, pin in pins:
            got = installed.get(pkg, "")
            if not got:
                status = "MISSING"
                per_tool_problems.append(
                    f"  - `{pkg}` pinned at {pin} but not found in `lib/pypi/`"
                )
            elif got != pin:
                status = f"MISMATCH ({got})"
                per_tool_problems.append(
                    f"  - `{pkg}` pinned at {pin} but installed {got}"
                )
            else:
                status = "OK"
            lines.append(f"| `{pkg}` | {pin} | {got or '—'} | {status} |")
        lines.append("")

        if per_tool_problems:
            problem_sections.append(f"### {name}\n" + "\n".join(per_tool_problems))

    if problem_sections:
        lines.append("## Problems")
        lines.append("")
        lines.append(
            "The following tools have a pinned/installed mismatch. "
            "Run `python lib/update_lib.py --all-apps` from the "
            "project root to bring them back in sync."
        )
        lines.append("")
        lines.extend(problem_sections)
        lines.append("")

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {REPORT}")
    if args.stdout:
        print()
        print("\n".join(lines))
    return 1 if problem_sections else 0


if __name__ == "__main__":
    sys.exit(main())
