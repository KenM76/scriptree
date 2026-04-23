#!/usr/bin/env python3
"""Vendor / refresh ScripTree's Python dependencies into ``lib/pypi/``.

Usage:

    python lib/update_lib.py                  # install anything missing
    python lib/update_lib.py --upgrade        # wipe lib/pypi/, reinstall
    python lib/update_lib.py --audit          # check pinned versions for CVEs
    python lib/update_lib.py --trim           # remove unused Qt modules
    python lib/update_lib.py --upgrade --trim # full refresh + trim in one go
    python lib/update_lib.py --dry-run        # preview without changes

Trim strategy
-------------

PySide6 ships the entire Qt framework — WebEngine, QML, Quick/3D,
Multimedia, PDF, Charts, Designer, translations for dozens of
languages, developer tooling, and more. ScripTree only imports
``QtCore``, ``QtGui``, and ``QtWidgets``. ``--trim`` deletes the
unused pieces, shrinking ``lib/pypi/`` by ~3/4 without affecting
functionality.

Trim is opt-in, not default. Power users might want the full
install (e.g. if they're extending ScripTree with a plugin that
uses QtNetwork, QtSql, etc. — add the module to TRIM_KEEP_EXTRA
below or skip ``--trim``).

Every trim writes ``lib/_manifests/trim_log.md`` recording exactly
what was removed and how much space was freed.

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
            if existing.stem == "trim_log":
                continue  # don't touch the trim log
            if existing.stem not in installed:
                existing.unlink()
    for name, version in installed.items():
        _write_manifest(name, version, source="PyPI (via pip install)")


# ── Trim: remove unused Qt modules ────────────────────────────────────

# Qt submodules ScripTree imports. Everything else is fair game for
# trimming. Extend this list if you add imports like QtNetwork.
#
# Names match the Qt module DLL/PYD root. For example, adding
# "QtNetwork" here would keep ``Qt6Network.dll`` and ``QtNetwork.pyd``.
TRIM_KEEP_MODULES = {
    "QtCore",
    "QtGui",
    "QtWidgets",
}

# Extra files/directories always kept regardless of trim. These are
# Qt's runtime plumbing (C runtime, platform plugins, etc.) that Qt
# won't start without, even if we only use the three core modules.
TRIM_ALWAYS_KEEP = {
    # Core C++ runtime libs shipped with Qt6.
    "vcruntime*.dll",
    "msvcp*.dll",
    "concrt*.dll",
    # The ICU libs (Unicode) are dependencies of Qt6Core.
    "icu*.dll",
    # d3dcompiler is a dependency of QtGui on Windows for software
    # rendering paths. Keep it to be safe.
    "d3dcompiler_*.dll",
    # Package metadata — keep the dist-info dirs so pip knows what's
    # installed and tooling like pip-audit still works.
    "*.dist-info",
    # Essential Python-level files.
    "__init__.py",
    "py.typed",
    "*.pyi",
    # Config and runtime support files.
    "qt.conf",
    # shiboken6 (Qt-Python binding glue) is mandatory.
    "shiboken6",
    "shiboken6.abi3.so",
    "*Shiboken*.dll",
    "*Shiboken*.pyd",
}

# Top-level items under PySide6/ to remove entirely when trimming.
# Paths are relative to lib/pypi/PySide6/.
TRIM_REMOVE_DIRS = {
    "translations",      # ~43 MB — we don't localize.
    "qml",               # ~19 MB — QML templates (we use Widgets).
    "resources",         # ~18 MB — WebEngine resources, mostly.
    "metatypes",         # ~11 MB — QML type metadata.
    "doc",               # any included docs.
    "examples",          # Qt examples bundled with some wheels.
    "include",           # Qt C++ headers.
    "mkspecs",           # qmake build configs.
    "typesystems",       # shiboken build-time data.
    "glue",              # shiboken build-time data.
    "support",           # Qt Creator integration files.
    "Assistant.app",     # Qt Assistant (doc viewer).
    "Designer.app",
    "Linguist.app",
}

# Globs removed anywhere in PySide6/. Executables, dev tools, and
# modules we don't import.
TRIM_REMOVE_GLOBS = {
    # Qt developer command-line tools (not needed at runtime).
    "lupdate*",
    "lrelease*",
    "linguist*",
    "designer*",
    "assistant*",
    "qmllint*",
    "qmlformat*",
    "qmlls*",
    "qmlsc*",
    "qmlcachegen*",
    "qmltestrunner*",
    "qmlplugindump*",
    "qmlimportscanner*",
    "qmltyperegistrar*",
    "qdbus*",
    "qtdiag*",
    "qtpaths*",
    "qmake*",
    "uic*",
    "rcc*",
    "moc*",
    "androiddeployqt*",
    "pyside6-*",
    "shiboken6.exe",
    "shiboken6-*",
    # Translation binary files outside translations/ (unlikely but
    # cheap to match).
    "*.qm",
    # Giant modules we don't use.
    "Qt6WebEngine*.dll",
    "Qt6WebEngine*.dylib",
    "libQt6WebEngine*.so*",
    "Qt6Quick*.dll",
    "libQt6Quick*.so*",
    "Qt6Qml*.dll",
    "libQt6Qml*.so*",
    "Qt6Pdf*.dll",
    "libQt6Pdf*.so*",
    "Qt6Charts*.dll",
    "libQt6Charts*.so*",
    "Qt6DataVisualization*.dll",
    "libQt6DataVisualization*.so*",
    "Qt63D*.dll",
    "libQt63D*.so*",
    "Qt6Designer*.dll",
    "libQt6Designer*.so*",
    "Qt6Multimedia*.dll",
    "libQt6Multimedia*.so*",
    "Qt6Spatial*.dll",
    "libQt6Spatial*.so*",
    "Qt6ShaderTools*.dll",
    "libQt6ShaderTools*.so*",
    "Qt6Sensors*.dll",
    "libQt6Sensors*.so*",
    "Qt6Bluetooth*.dll",
    "libQt6Bluetooth*.so*",
    "Qt6Nfc*.dll",
    "libQt6Nfc*.so*",
    "Qt6SerialPort*.dll",
    "libQt6SerialPort*.so*",
    "Qt6Positioning*.dll",
    "libQt6Positioning*.so*",
    "Qt6TextToSpeech*.dll",
    "libQt6TextToSpeech*.so*",
    "Qt6WebSockets*.dll",
    "libQt6WebSockets*.so*",
    "Qt6WebChannel*.dll",
    "libQt6WebChannel*.so*",
    "Qt6HttpServer*.dll",
    "libQt6HttpServer*.so*",
    "Qt6OpenGL*.dll",
    "libQt6OpenGL*.so*",
    "Qt6Test*.dll",
    "libQt6Test*.so*",
    "Qt6Scxml*.dll",
    "libQt6Scxml*.so*",
    "Qt6RemoteObjects*.dll",
    "libQt6RemoteObjects*.so*",
    "Qt6SpatialAudio*.dll",
    "Qt6StateMachine*.dll",
    "Qt6Concurrent*.dll",
    "libQt6Concurrent*.so*",
    "Qt6Help*.dll",
    "Qt6UiTools*.dll",
    "libQt6UiTools*.so*",
    "Qt6Sql*.dll",
    "libQt6Sql*.so*",
    "Qt6Svg*.dll",
    "libQt6Svg*.so*",
    "Qt6Xml*.dll",
    "libQt6Xml*.so*",
    "Qt6Network*.dll",
    "libQt6Network*.so*",
    "Qt6VirtualKeyboard*.dll",
    "libQt6VirtualKeyboard*.so*",
    # FFmpeg (audio/video codecs used by Qt Multimedia).
    "avcodec-*.dll",
    "avformat-*.dll",
    "avutil-*.dll",
    "swresample-*.dll",
    "swscale-*.dll",
    # OpenGL software renderer (we use native).
    "opengl32sw.dll",
    # D3D shader compiler variants we don't need.
}

# Plugin subdirectories. KEEP minimal set; remove everything else.
# Qt WILL refuse to start a GUI app on Windows without platforms/
# and typically needs styles/ for QStyleFactory. Others are optional.
TRIM_PLUGINS_KEEP = {
    "platforms",      # mandatory (qwindows.dll / libqxcb.so / libqcocoa.dylib)
    "styles",         # QStyleFactory — we use windowsvista / windows11 / fusion
    "imageformats",   # allow PNG/JPG/ICO icons (tiny)
    "iconengines",    # SVG icon engine (tiny, commonly used)
    "platforminputcontexts",  # IME support — small, safe to keep
}


def _matches(name: str, patterns: set[str]) -> bool:
    """Return True if ``name`` matches any glob in ``patterns``."""
    import fnmatch
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def _iter_module_related(pypi_dir: Path, keep_modules: set[str]):
    """Yield paths to all Qt module files (QtXxx.pyd, Qt6Xxx.dll, etc.)
    that we do NOT want to keep, based on ``keep_modules``.

    We preserve files where the Qt module name appears in ``keep_modules``;
    any other ``Qt6<Name>.dll`` or ``Qt<Name>.pyd`` gets flagged.
    """
    import re
    pyside = pypi_dir / "PySide6"
    if not pyside.is_dir():
        return
    # Match QtXxx.pyd / QtXxx.abi3.so / Qt6Xxx.dll / libQt6Xxx.so.*
    pyd_re = re.compile(r"^Qt([A-Za-z0-9]+)\.(pyd|abi3\.so|so)$", re.IGNORECASE)
    dll_re = re.compile(r"^(?:lib)?Qt6([A-Za-z0-9]+)(?:\.dll|\.dylib|\.so(?:\.\d+)*)$", re.IGNORECASE)
    for entry in pyside.iterdir():
        if not entry.is_file():
            continue
        m = pyd_re.match(entry.name) or dll_re.match(entry.name)
        if m is None:
            continue
        module_name = f"Qt{m.group(1)}"
        if module_name in keep_modules:
            continue
        # Already handled by TRIM_REMOVE_GLOBS for some big modules —
        # but this catches everything including the small ones (e.g.
        # Qt6Xml.dll, Qt6Svg.dll) so we end up with a clean minimal set.
        yield entry


def _dir_size(path: Path) -> int:
    """Return total size in bytes of a path (file or directory)."""
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def cmd_trim(args: argparse.Namespace) -> int:
    """Remove unused Qt modules from lib/pypi/PySide6/.

    Runs idempotently — re-running after a fresh install is safe.
    Writes a log to lib/_manifests/trim_log.md.
    """
    pyside = PYPI_DIR / "PySide6"
    if not pyside.is_dir():
        print(
            f"No PySide6 vendored at {pyside}. Run "
            "`python lib/update_lib.py` first.",
            file=sys.stderr,
        )
        return 1

    to_remove: list[Path] = []

    # Top-level directories to prune.
    for dname in TRIM_REMOVE_DIRS:
        p = pyside / dname
        if p.exists():
            to_remove.append(p)

    # Glob-matched files anywhere under PySide6/.
    for entry in pyside.iterdir():
        if entry.is_file() and _matches(entry.name, TRIM_REMOVE_GLOBS):
            if not _matches(entry.name, TRIM_ALWAYS_KEEP):
                to_remove.append(entry)

    # Qt module PYD/DLL files not in TRIM_KEEP_MODULES.
    for p in _iter_module_related(PYPI_DIR, TRIM_KEEP_MODULES):
        if not _matches(p.name, TRIM_ALWAYS_KEEP):
            to_remove.append(p)

    # Plugin subdirs outside the keep list.
    plugins_dir = pyside / "plugins"
    if plugins_dir.is_dir():
        for plugin in plugins_dir.iterdir():
            if plugin.is_dir() and plugin.name not in TRIM_PLUGINS_KEEP:
                to_remove.append(plugin)

    # De-duplicate and sort by size so the log is informative.
    seen: set[Path] = set()
    unique = []
    for p in to_remove:
        if p not in seen and p.exists():
            seen.add(p)
            unique.append(p)
    sized = [(p, _dir_size(p)) for p in unique]
    sized.sort(key=lambda t: -t[1])

    total_before = _dir_size(pyside)
    total_freed = sum(s for _, s in sized)

    if args.dry_run:
        print(f"\n-- dry run: would remove {len(sized)} item(s) --\n")
        for p, size in sized:
            print(f"  {_human_size(size):>10s}  {p.relative_to(pyside)}")
        print(f"\n  total to free: {_human_size(total_freed)}")
        print(f"  PySide6 current size: {_human_size(total_before)}")
        print(
            f"  PySide6 after trim:   "
            f"~{_human_size(total_before - total_freed)}"
        )
        return 0

    print(f"\n-- trimming {len(sized)} item(s) from PySide6 --\n")
    removed_log: list[str] = []
    for p, size in sized:
        rel = p.relative_to(pyside)
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        except OSError as e:
            print(f"  SKIP (error): {rel} — {e}", file=sys.stderr)
            continue
        removed_log.append(f"| {rel} | {_human_size(size)} |")
        print(f"  removed {_human_size(size):>10s}  {rel}")

    total_after = _dir_size(pyside)
    freed = total_before - total_after
    print(
        f"\nBefore: {_human_size(total_before)}  "
        f"After: {_human_size(total_after)}  "
        f"Freed: {_human_size(freed)}"
    )

    # Write trim log.
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    log_path = MANIFEST_DIR / "trim_log.md"
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_content = (
        f"# Trim log\n\n"
        f"- **Trimmed on:** {now}\n"
        f"- **Platform:** {sys.platform}\n"
        f"- **PySide6 size before:** {_human_size(total_before)}\n"
        f"- **PySide6 size after:** {_human_size(total_after)}\n"
        f"- **Space freed:** {_human_size(freed)}\n\n"
        f"## Kept Qt modules\n\n"
        + "".join(f"- `{m}`\n" for m in sorted(TRIM_KEEP_MODULES))
        + "\n"
        f"## Kept Qt plugin directories\n\n"
        + "".join(f"- `{p}`\n" for p in sorted(TRIM_PLUGINS_KEEP))
        + "\n"
        f"## Removed items\n\n"
        f"| Path | Size |\n|---|---|\n"
        + "\n".join(removed_log) + "\n"
    )
    log_path.write_text(log_content, encoding="utf-8")
    print(f"\nTrim log: {log_path}")
    return 0


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
        "--trim", action="store_true",
        help=(
            "After install (or on its own) remove Qt modules ScripTree "
            "doesn't use — WebEngine, QML, Quick/3D, Multimedia, PDF, "
            "Charts, translations, dev tools, etc. Typically saves "
            "~350 MB. Writes a log to lib/_manifests/trim_log.md."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would happen without actually running pip.",
    )
    parser.add_argument(
        "--all-apps", action="store_true",
        help=(
            "After refreshing ScripTree's own lib/pypi/, also walk "
            "ScripTreeApps/ and refresh every per-tool lib/ folder "
            "found there. Each tool's lib/requirements.txt may start "
            "with a '# python: <cmd>' line specifying which interpreter "
            "to use (e.g. '# python: py -3.12'); falls back to the "
            "current Python otherwise."
        ),
    )
    parser.add_argument(
        "--apps-only", action="store_true",
        help=(
            "Like --all-apps but skip ScripTree's own lib/. Useful "
            "when you only want to refresh per-tool deps."
        ),
    )
    args = parser.parse_args(argv)

    if args.audit:
        return cmd_audit(args)

    if args.apps_only:
        return cmd_apps(args)

    # Decide whether to install.
    # - Default (no flags): install missing packages.
    # - --upgrade: always reinstall.
    # - --trim alone: only trim if there's already an install; otherwise
    #   we need to install first.
    has_install = PYPI_DIR.is_dir() and any(
        p.name != ".gitkeep" for p in PYPI_DIR.iterdir()
    )
    do_install = args.upgrade or not has_install or not args.trim

    if do_install:
        rc = cmd_install(args)
        if rc != 0:
            return rc

    if args.trim:
        rc = cmd_trim(args)
        if rc != 0:
            return rc

    if args.all_apps:
        return cmd_apps(args)

    return 0


# ── Per-tool app deps ──────────────────────────────────────────────

def _find_app_libs() -> list[Path]:
    """Return every ``ScripTreeApps/**/lib/requirements.txt`` path.

    Walks the ``ScripTreeApps/`` folder at the project root. Skips any
    ``lib/`` that doesn't have a ``requirements.txt`` — those are just
    stubs.
    """
    project_root = HERE.parent
    apps_root = project_root / "ScripTreeApps"
    results: list[Path] = []
    if not apps_root.is_dir():
        return results
    for req in apps_root.rglob("lib/requirements.txt"):
        # Skip nested matches inside an app's own lib/pypi/<package>/
        # — those are vendored packages shipping their own extras_require
        # files, not per-tool requirement manifests.
        if "pypi" in req.parts:
            continue
        results.append(req)
    return sorted(results)


def _parse_python_cmd(requirements: Path) -> list[str]:
    """Return the interpreter command for this tool as a list of argv.

    Honors a ``# python: <command>`` line anywhere in the first 30
    lines of the requirements file, e.g. ``# python: py -3.12`` ->
    ``["py", "-3.12"]``. Falls back to ``[sys.executable]`` if no hint
    is found.
    """
    try:
        lines = requirements.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()[:30]
    except OSError:
        return [sys.executable]
    for raw in lines:
        line = raw.strip()
        if line.startswith("#"):
            line = line.lstrip("#").strip()
            if line.lower().startswith("python:"):
                cmd = line.split(":", 1)[1].strip()
                if cmd:
                    return cmd.split()
    return [sys.executable]


def cmd_apps(args) -> int:
    """Refresh every per-tool ``lib/`` folder under ``ScripTreeApps/``.

    For each one, reads the ``# python: ...`` hint and runs
    ``<that-python> -m pip install --target <tool>/lib/pypi
    --upgrade -r <tool>/lib/requirements.txt``.
    """
    libs = _find_app_libs()
    if not libs:
        print("No ScripTreeApps/*/lib/requirements.txt files found.")
        return 0

    print(f"Found {len(libs)} tool lib/ folder(s):")
    for req in libs:
        print(f"  - {req.parent.parent.name}  ({req})")

    failures: list[tuple[Path, int]] = []
    for req in libs:
        tool_lib = req.parent
        tool_pypi = tool_lib / "pypi"
        py = _parse_python_cmd(req)
        print(
            f"\n=== {req.parent.parent.name} "
            f"(interpreter: {' '.join(py)}) ==="
        )

        if getattr(args, "dry_run", False):
            print(f"   would: {' '.join(py)} -m pip install --target "
                  f"{tool_pypi} --upgrade -r {req}")
            continue

        tool_pypi.mkdir(parents=True, exist_ok=True)
        cmd = (
            py
            + ["-m", "pip", "install", "--target", str(tool_pypi),
               "--upgrade", "-r", str(req)]
        )
        rc = _run(cmd)
        if rc != 0:
            failures.append((req, rc))
            print(
                f"   ! pip failed for {req.parent.parent.name} "
                f"(exit {rc}). Common causes:",
                file=sys.stderr,
            )
            print(
                "     - the declared Python interpreter isn't installed\n"
                "     - no wheel available for that Python/OS\n"
                "     - network blocked",
                file=sys.stderr,
            )

    if failures:
        print(
            f"\n{len(failures)} of {len(libs)} tool lib/ folder(s) "
            f"failed to refresh.",
            file=sys.stderr,
        )
        return 1
    print(f"\nAll {len(libs)} tool lib/ folder(s) refreshed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
