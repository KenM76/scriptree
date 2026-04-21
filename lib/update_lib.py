#!/usr/bin/env python3
"""Vendor / refresh ScripTree's Python dependencies into ``lib/pypi/``.

Usage:

    python lib/update_lib.py              # install anything missing
    python lib/update_lib.py --upgrade    # wipe lib/pypi/ first, reinstall
    python lib/update_lib.py --audit      # check pinned versions for CVEs
    python lib/update_lib.py --dry-run    # show what would happen

Under the hood this is just a thin wrapper around::

    pip install --target lib/pypi/ -r lib/requirements.txt

plus provenance-note generation so every installed top-level package
ends up with a ``lib/_manifests/<package>.md`` file describing where it
came from, when, and exactly which version is on disk.

See ``lib/README.md`` for the rationale and full workflow.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
PYPI_DIR = HERE / "pypi"
MANIFEST_DIR = HERE / "_manifests"
REQUIREMENTS = HERE / "requirements.txt"


def _run(cmd: list[str]) -> int:
    """Run a subprocess, streaming output. Returns exit code."""
    print(f"\n$ {' '.join(cmd)}\n")
    return subprocess.run(cmd).returncode


def _installed_packages() -> dict[str, str]:
    """Return ``{package_name: version}`` for everything currently in
    ``lib/pypi/``. Reads ``.dist-info/METADATA`` files.
    """
    pkgs: dict[str, str] = {}
    if not PYPI_DIR.is_dir():
        return pkgs
    for dist_info in PYPI_DIR.glob("*.dist-info"):
        metadata = dist_info / "METADATA"
        if not metadata.is_file():
            continue
        name = ""
        version = ""
        for line in metadata.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            if line.startswith("Name:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("Version:"):
                version = line.split(":", 1)[1].strip()
            if name and version:
                break
        if name:
            pkgs[name] = version
    return pkgs


def _write_manifest(name: str, version: str, source: str) -> None:
    """Write a provenance note for one package."""
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    path = MANIFEST_DIR / f"{name}.md"
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = f"""# {name}

- **Version:** {version}
- **Source:** {source}
- **Installed:** {now}
- **Installed by:** `lib/update_lib.py` on
  `{sys.platform}` / Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}

## Notes

This package is vendored into `lib/pypi/` so ScripTree can run without
a system `pip install`. To upgrade, edit `lib/requirements.txt` and
run `python lib/update_lib.py --upgrade`.

For security audits, run `python lib/update_lib.py --audit`.
"""
    path.write_text(content, encoding="utf-8")


def _refresh_manifests() -> None:
    """Rewrite all manifests from the current pypi/ state."""
    # Drop stale manifests whose package no longer exists.
    installed = _installed_packages()
    if MANIFEST_DIR.is_dir():
        for existing in MANIFEST_DIR.glob("*.md"):
            if existing.stem not in installed:
                existing.unlink()
    for name, version in installed.items():
        _write_manifest(name, version, source="PyPI (via pip install)")


def cmd_install(args: argparse.Namespace) -> int:
    if not REQUIREMENTS.is_file():
        print(f"error: {REQUIREMENTS} not found", file=sys.stderr)
        return 1

    if args.upgrade and PYPI_DIR.is_dir():
        if args.dry_run:
            print(f"would remove existing {PYPI_DIR}")
        else:
            print(f"removing existing {PYPI_DIR} for a clean install...")
            # Preserve .gitkeep
            gitkeep = PYPI_DIR / ".gitkeep"
            keep_content = (
                gitkeep.read_text(encoding="utf-8")
                if gitkeep.is_file() else None
            )
            shutil.rmtree(PYPI_DIR)
            PYPI_DIR.mkdir(parents=True)
            if keep_content is not None:
                gitkeep.write_text(keep_content, encoding="utf-8")

    PYPI_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--target", str(PYPI_DIR),
        "--upgrade" if args.upgrade else "--no-deps",
        "-r", str(REQUIREMENTS),
    ]
    # Note: --no-deps on the non-upgrade path is intentional. pip with
    # --target plus --upgrade will correctly install full transitive
    # dependencies. Without --upgrade, we already ran it once and want
    # idempotent "install if missing" behavior.
    if not args.upgrade:
        cmd.remove("--no-deps")

    if args.dry_run:
        print(f"\nwould run: {' '.join(cmd)}")
        return 0

    rc = _run(cmd)
    if rc != 0:
        print(
            "\npip install failed. Common causes:\n"
            "  - No network connection\n"
            "  - Pinned version doesn't have a wheel for this Python/OS\n"
            "  - Permission denied on lib/pypi/ (try running from a\n"
            "    folder where your user can write)\n",
            file=sys.stderr,
        )
        return rc

    print("\n-- writing provenance manifests --")
    _refresh_manifests()

    print(f"\ndone. Vendored into: {PYPI_DIR}")
    print(f"manifest files:    {MANIFEST_DIR}")
    print(
        "\nTo use ScripTree with these vendored libs, just run "
        "run_scriptree.py as usual."
    )
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Run pip-audit against the pinned versions and print any CVEs.

    Installs pip-audit into a temporary location if it's not already
    available, so the user doesn't have to pre-install it.
    """
    # Try the user's Python first. If pip-audit isn't installed there,
    # install it into a scratch directory and run from there.
    try:
        rc = _run([sys.executable, "-m", "pip_audit", "--version"])
        have_audit = rc == 0
    except FileNotFoundError:
        have_audit = False

    if not have_audit:
        print(
            "pip-audit not available; installing it temporarily "
            "(not into lib/pypi/)..."
        )
        rc = _run([
            sys.executable, "-m", "pip", "install", "--user", "pip-audit"
        ])
        if rc != 0:
            print("Could not install pip-audit.", file=sys.stderr)
            return rc

    cmd = [sys.executable, "-m", "pip_audit", "-r", str(REQUIREMENTS)]
    return _run(cmd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="update_lib.py",
        description=(
            "Install / refresh the vendored dependencies listed in "
            "lib/requirements.txt into lib/pypi/."
        ),
    )
    parser.add_argument(
        "--upgrade", action="store_true",
        help=(
            "Wipe lib/pypi/ first and do a full reinstall. Use this "
            "when changing pinned versions or to get rid of stale "
            "transitive dependencies."
        ),
    )
    parser.add_argument(
        "--audit", action="store_true",
        help=(
            "Instead of installing, run pip-audit against the pinned "
            "versions to report known CVEs."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would happen without actually running pip.",
    )
    args = parser.parse_args(argv)

    if args.audit:
        return cmd_audit(args)
    return cmd_install(args)


if __name__ == "__main__":
    sys.exit(main())
