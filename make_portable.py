#!/usr/bin/env python3
"""Build a portable, end-user copy of ScripTree.

Copies this repo to a destination folder (default: ``C:\\Prod\\ScripTree``
on Windows, ``~/ScripTree-portable`` elsewhere), stripping dev-only
files. The result is what an end user would expect to download — a
single folder they can zip, move, or double-click ``run_scriptree.bat``
in.

Usage::

    python make_portable.py                    # default destination
    python make_portable.py D:\\Apps\\ScripTree  # custom destination
    python make_portable.py --zip              # also produce a .zip
    python make_portable.py --force            # overwrite existing dest
    python make_portable.py --no-smoke-test    # skip launch test

What gets excluded:

- Version control:          ``.git/``, ``.gitignore``, ``.gitattributes``
- Editor / tooling:          ``.claude/``, ``.vscode/``, ``.idea/``
- Python caches:             ``__pycache__/``, ``*.pyc``, ``.pytest_cache/``
- Dev-only dirs:             ``tests/``, ``docs/``, ``scripts/``,
                             ``user_configs/``
- Transient files:           ``out.txt``, ``*.log``, ``*.tmp``

Pre-flight check: ``lib/pypi/`` must contain the vendored dependencies
(run ``python lib/update_lib.py --trim`` first if not). The script
aborts with a helpful message if it finds ``lib/pypi/`` empty, since
an empty vendored folder makes the portable copy non-portable.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent

# ── Exclusion patterns ────────────────────────────────────────────────

#: Directory names to skip at any depth.
EXCLUDE_DIRS = {
    ".git",
    ".claude",
    ".vscode",
    ".idea",
    ".pytest_cache",
    "__pycache__",
    "tests",
    "docs",
    "scripts",
    "user_configs",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "htmlcov",
    ".tox",
}

#: File name patterns (exact names and simple ``*.ext`` globs).
EXCLUDE_FILES = {
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    "out.txt",
    ".coverage",
    "make_portable.py",  # this script itself is dev-only
    # NOTE: make_shortcut.py is *included* in the portable copy so end
    # users can regenerate ScripTree.lnk / .desktop / .command after
    # moving the folder — paths inside the shortcut are absolute.
}
EXCLUDE_EXTS = {".pyc", ".pyo", ".log", ".tmp", ".bak", ".swp"}


def _ignore(dirpath: str, names: list[str]) -> list[str]:
    """``shutil.copytree`` ignore callback."""
    skip = []
    for n in names:
        if n in EXCLUDE_DIRS or n in EXCLUDE_FILES:
            skip.append(n)
            continue
        ext = os.path.splitext(n)[1].lower()
        if ext in EXCLUDE_EXTS:
            skip.append(n)
    return skip


# ── Pre-flight ────────────────────────────────────────────────────────

def _check_vendored_libs() -> None:
    """Abort if ``lib/pypi/`` is empty — the copy would not be portable."""
    pypi = REPO / "lib" / "pypi"
    if not pypi.is_dir():
        _fail(
            f"lib/pypi/ does not exist at {pypi}.\n"
            f"Run:  python lib/update_lib.py --trim\n"
            f"first to populate the vendored dependencies."
        )
    entries = [p for p in pypi.iterdir() if p.name != ".gitkeep"]
    if not entries:
        _fail(
            "lib/pypi/ is empty. A portable copy without vendored deps\n"
            "would require the end user to run pip install PySide6.\n"
            "Run:  python lib/update_lib.py --trim\n"
            "first to populate it."
        )


def _rmtree_robust(path: Path, *, attempts: int = 20, pause: float = 0.5) -> None:
    """Remove ``path`` tolerating transient Windows/OneDrive locks.

    OneDrive-synced folders can carry the ReparsePoint + ReadOnly
    directory attribute, and antivirus / indexers occasionally keep
    handles open. We clear attributes, then retry the rmtree several
    times with a short backoff.
    """
    def _on_error(func, target, excinfo):
        try:
            os.chmod(target, 0o777)
            func(target)
        except Exception:
            pass

    # Clear directory-level ReadOnly attribute tree-wide before rmtree.
    if sys.platform == "win32" and path.exists():
        try:
            subprocess.run(
                ["attrib", "-r", "-s", "-h", str(path), "/s", "/d"],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass

    for i in range(attempts):
        if not path.exists():
            return
        try:
            shutil.rmtree(path, onerror=_on_error)
        except Exception:
            pass
        if not path.exists():
            return
        time.sleep(pause)


def _fail(msg: str) -> None:
    print(f"\nERROR: {msg}\n", file=sys.stderr)
    sys.exit(1)


# ── Core ──────────────────────────────────────────────────────────────

#: Per-user content that must not be silently clobbered on rebuild.
#: This is where the end user keeps their own .scriptree / .scriptreetree
#: files, saved configurations, etc. We ask before touching it.
PROTECTED_SUBDIRS = ("ScripTreeApps",)


def _decide_protected(
    dest: Path, name: str, preset: str | None
) -> str:
    """Decide what to do with a protected sub-folder at ``dest/name``.

    Returns one of: ``"keep"``, ``"overwrite"``, ``"backup"``.

    ``preset`` is the value from ``--scriptreeapps=...`` (or equivalent
    CLI flag). If None and stdin is a TTY, we prompt; otherwise we
    default to ``"keep"`` (the safe choice).
    """
    target = dest / name
    if not target.exists():
        # Nothing to protect — caller will just copy the source version.
        return "overwrite"

    if preset in ("keep", "overwrite", "backup"):
        return preset

    if not sys.stdin.isatty():
        print(
            f"   {name}/ already exists at destination; keeping it "
            f"(non-interactive run).",
        )
        return "keep"

    print(f"\n{name}/ already exists at {target}.")
    print("This folder typically holds the end user's own tools and configs.")
    print("What should I do?")
    print("  [K]eep existing (skip copying from source)  [default]")
    print("  [O]verwrite with source version (destructive)")
    print("  [B]ackup existing to <name>.bak-<timestamp>, then copy fresh")
    while True:
        try:
            choice = input("Choice [K/o/b]: ").strip().lower()
        except EOFError:
            choice = ""
        if choice in ("", "k", "keep"):
            return "keep"
        if choice in ("o", "overwrite"):
            return "overwrite"
        if choice in ("b", "backup"):
            return "backup"
        print("  Please enter K, O, or B.")


def copy_portable(
    dest: Path, *, force: bool, protected_action: str | None = None
) -> None:
    # Decide up-front what to do with each protected subfolder so we
    # can stash it aside before the rmtree, then restore after.
    decisions: dict[str, str] = {}
    stash_root: Path | None = None
    if dest.exists():
        for name in PROTECTED_SUBDIRS:
            decisions[name] = _decide_protected(dest, name, protected_action)

        if not force:
            _fail(
                f"Destination {dest} already exists.\n"
                f"Use --force to overwrite, or pick a different path."
            )

        # Stash any protected subfolders we're keeping or backing up
        # into a sibling temp dir so the rmtree doesn't eat them.
        to_stash = [
            name for name, act in decisions.items()
            if act in ("keep", "backup") and (dest / name).exists()
        ]
        if to_stash:
            stash_root = dest.parent / f".{dest.name}.portable-stash"
            if stash_root.exists():
                _rmtree_robust(stash_root)
            stash_root.mkdir(parents=True, exist_ok=True)
            for name in to_stash:
                src = dest / name
                target = stash_root / name
                print(f"Stashing {name}/ aside ({decisions[name]}) ...")
                # os.rename is atomic on the same filesystem and
                # avoids shutil.move's copy+rmtree fallback that
                # trips on files held open by Windows indexers/AV.
                try:
                    os.rename(src, target)
                except OSError as e:
                    _fail(
                        f"Could not stash {name}/ aside: {e}.\n"
                        f"Close anything that might be using files in "
                        f"{src} and retry."
                    )

        print(f"Removing existing {dest} ...")
        _rmtree_robust(dest)
        if dest.exists():
            _fail(f"Could not fully remove {dest}. Is it open somewhere?")

    print(f"Copying {REPO}")
    print(f"     -> {dest}")
    t0 = time.time()

    # When keeping the user's existing protected subfolder, also skip
    # it in the source copy so we don't overwrite it when we restore.
    protected_to_skip = {
        name for name, act in decisions.items() if act == "keep"
    }

    def _ignore_with_protected(dirpath, names):
        skip = _ignore(dirpath, names)
        # Only skip protected subfolders when they sit directly under
        # the repo root — don't accidentally skip a same-named nested
        # folder somewhere else in the tree.
        if Path(dirpath).resolve() == REPO:
            for n in names:
                if n in protected_to_skip and n not in skip:
                    skip.append(n)
        return skip

    shutil.copytree(
        REPO, dest, ignore=_ignore_with_protected, dirs_exist_ok=False
    )
    elapsed = time.time() - t0
    print(f"   copied in {elapsed:.1f}s")

    # Restore stashed content.
    if stash_root is not None:
        ts = time.strftime("%Y%m%d-%H%M%S")
        for name, act in decisions.items():
            stashed = stash_root / name
            if not stashed.exists():
                continue
            if act == "keep":
                # Put the user's existing copy back in place.
                os.rename(stashed, dest / name)
                print(f"Kept existing {name}/ from prior build.")
            elif act == "backup":
                backup_name = f"{name}.bak-{ts}"
                os.rename(stashed, dest / backup_name)
                print(
                    f"Backed up previous {name}/ to {backup_name}/; "
                    f"fresh copy from source is now in place."
                )
        _rmtree_robust(stash_root)


def _folder_size_mb(path: Path) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / (1024 * 1024)


def make_zip(folder: Path) -> Path:
    """Zip ``folder`` as a sibling ``folder.zip``."""
    zip_path = folder.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    print(f"Zipping -> {zip_path}")
    t0 = time.time()
    with zipfile.ZipFile(
        zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as zf:
        for root, _dirs, files in os.walk(folder):
            for f in files:
                full = Path(root) / f
                arc = folder.name / full.relative_to(folder)
                zf.write(full, arc)
    elapsed = time.time() - t0
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"   zipped in {elapsed:.1f}s  ({size_mb:.1f} MB)")
    return zip_path


def smoke_test(dest: Path) -> bool:
    """Launch the portable copy briefly to verify it starts cleanly."""
    bat = dest / "run_scriptree.bat"
    py = dest / "run_scriptree.py"
    if sys.platform == "win32" and bat.is_file():
        cmd = ["cmd", "/c", str(bat)]
    else:
        cmd = [sys.executable, str(py)]

    print(f"Smoke test: {' '.join(cmd)}")
    log = dest / "_smoke.log"
    with open(log, "w", encoding="utf-8") as f:
        proc = subprocess.Popen(
            cmd, cwd=str(dest), stdout=f, stderr=subprocess.STDOUT
        )
    time.sleep(6)
    still_running = proc.poll() is None
    if still_running:
        # Kill the entire process tree — on Windows, cmd.exe launches
        # python.exe which launches the Qt GUI; terminating just cmd
        # leaves python alive holding our vendored DLLs, which then
        # blocks a subsequent --force rebuild.
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True, timeout=10,
            )
        else:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        # Give Windows a beat to actually release DLL mappings.
        time.sleep(1.0)
    # Give the OS a moment to release the log file handle before we
    # read & delete it. cmd.exe on Windows sometimes lingers briefly.
    for _ in range(10):
        try:
            output = log.read_text(encoding="utf-8", errors="replace")
            log.unlink()
            break
        except (PermissionError, OSError):
            time.sleep(0.3)
    else:
        output = ""  # couldn't read — treat as empty

    if not still_running and proc.returncode not in (0, None):
        print("   FAIL launcher exited with an error:")
        print("   " + "\n   ".join(output.splitlines()[:40]))
        return False
    if output.strip():
        # Launcher shouldn't print anything on a clean startup.
        print("   WARN launcher produced output (may be non-fatal):")
        print("   " + "\n   ".join(output.splitlines()[:20]))
    print("   OK launched cleanly")
    return True


# ── Shortcut ──────────────────────────────────────────────────────────

def _make_platform_shortcut(dest: Path) -> None:
    """Invoke make_shortcut.py *inside the portable build* so the
    shortcut points at the portable copy's launcher, not the source
    repo's. Best-effort — a failure here doesn't fail the build.
    """
    script = dest / "make_shortcut.py"
    if not script.is_file():
        return
    try:
        result = subprocess.run(
            [sys.executable, str(script), str(dest)],
            cwd=str(dest),
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            # Echo the one-line "Wrote ..." message from the helper.
            for line in result.stdout.splitlines():
                if line.strip():
                    print(f"Shortcut: {line.strip()}")
        else:
            print(
                f"Shortcut generation returned {result.returncode}; "
                f"skipping. (Portable copy still works.)"
            )
            if result.stderr.strip():
                print(f"   {result.stderr.strip().splitlines()[0]}")
    except Exception as e:
        print(f"Shortcut generation skipped: {e}")


# ── CLI ───────────────────────────────────────────────────────────────

def _default_dest() -> Path:
    if sys.platform == "win32":
        return Path(r"C:\Prod\ScripTree")
    return Path.home() / "ScripTree-portable"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build a portable end-user copy of ScripTree."
    )
    ap.add_argument(
        "dest",
        nargs="?",
        type=Path,
        default=_default_dest(),
        help=f"Destination folder (default: {_default_dest()})",
    )
    ap.add_argument(
        "--force", action="store_true",
        help="Overwrite destination if it exists",
    )
    ap.add_argument(
        "--zip", action="store_true",
        help="Also produce <dest>.zip alongside the folder",
    )
    ap.add_argument(
        "--no-smoke-test", action="store_true",
        help="Skip launching the portable copy to verify it starts",
    )
    ap.add_argument(
        "--scriptreeapps",
        choices=["keep", "overwrite", "backup"],
        default=None,
        help=(
            "What to do with an existing ScripTreeApps/ folder at the "
            "destination. 'keep' (default when interactive) preserves "
            "the user's own tools; 'overwrite' replaces with the source "
            "version; 'backup' renames the existing copy to "
            "ScripTreeApps.bak-<timestamp>/ then writes fresh. If "
            "omitted and stdin is a TTY, you'll be prompted."
        ),
    )
    args = ap.parse_args()

    _check_vendored_libs()

    dest = args.dest.resolve()
    copy_portable(
        dest, force=args.force, protected_action=args.scriptreeapps
    )

    size_mb = _folder_size_mb(dest)
    print(f"\nPortable build: {dest}")
    print(f"   size: {size_mb:.1f} MB")

    _make_platform_shortcut(dest)

    ok = True
    if not args.no_smoke_test:
        ok = smoke_test(dest)

    if args.zip:
        make_zip(dest)

    if not ok:
        return 1
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
