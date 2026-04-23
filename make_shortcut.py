#!/usr/bin/env python3
"""Generate a platform-native ScripTree shortcut next to the launcher.

Windows
    Produces ``ScripTree.lnk`` pointing at ``run_scriptree.bat``, with
    the custom icon (``scriptree.ico``) attached. Uses ctypes + the
    COM IShellLink API — no third-party dependency required.

Linux
    Produces ``ScripTree.desktop`` — a standard XDG desktop entry that
    file managers (Nautilus, Dolphin, Thunar) render with the custom
    icon. Drop it into ``~/.local/share/applications/`` for full
    menu-integration, or keep it alongside the launcher for a
    portable "double-click shortcut".

macOS
    Produces ``ScripTree.command`` — a shell script that Finder knows
    to execute on double-click. Icon-wise, macOS doesn't honor custom
    icons on loose ``.command`` files the way Windows does with
    ``.lnk``, so for a properly-branded Dock entry you'll eventually
    want a real ``.app`` bundle. For now the Dock and title bar pick
    up the icon at runtime via ``QApplication.setWindowIcon``.

Usage::

    python make_shortcut.py             # write next to this script
    python make_shortcut.py <dest>      # write into <dest> folder
"""
from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ICON_DIR = HERE / "ScripTree" / "scriptree" / "resources"


def _pick_icon() -> Path | None:
    """Return the best icon for the current OS, or None if missing."""
    if sys.platform == "win32":
        for n in ("scriptree.ico", "scriptree.png"):
            p = ICON_DIR / n
            if p.is_file():
                return p
    elif sys.platform == "darwin":
        for n in ("scriptree.icns", "scriptree.png"):
            p = ICON_DIR / n
            if p.is_file():
                return p
    else:
        for n in ("scriptree.png", "scriptree.ico"):
            p = ICON_DIR / n
            if p.is_file():
                return p
    return None


# ── Windows ──────────────────────────────────────────────────────────

def _make_windows_shortcut(dest_dir: Path) -> Path:
    """Write ``<dest_dir>/ScripTree.lnk`` via COM IShellLink.

    Works on any Python 3.x on Windows — uses ctypes so it doesn't
    require pywin32 to be installed.
    """
    import ctypes
    from ctypes import wintypes

    target_bat = HERE / "run_scriptree.bat"
    icon = _pick_icon()
    lnk_path = dest_dir / "ScripTree.lnk"

    # Use PowerShell's WScript.Shell — it's present on every Windows
    # install since Vista, requires zero extra packages, and handles
    # the COM plumbing for us.
    import subprocess
    ps_script = f"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut([string]"{lnk_path}")
$sc.TargetPath = [string]"{target_bat}"
$sc.WorkingDirectory = [string]"{HERE}"
$sc.Description = "ScripTree - universal GUI for CLI tools"
$sc.WindowStyle = 7  # Minimized - the bat window flashes briefly; pythonw has no console anyway
"""
    if icon is not None:
        # ,0 picks the first icon resource in the file (for .ico the
        # whole file is one icon; this is also the idiom for .exe).
        ps_script += f'$sc.IconLocation = [string]"{icon},0"\n'
    ps_script += "$sc.Save()\n"

    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"PowerShell WScript.Shell failed:\n{result.stderr}"
        )
    return lnk_path


# ── Linux ────────────────────────────────────────────────────────────

def _make_linux_desktop(dest_dir: Path) -> Path:
    """Write ``<dest_dir>/ScripTree.desktop``."""
    target_sh = HERE / "run_scriptree.sh"
    icon = _pick_icon()
    icon_line = f"Icon={icon}\n" if icon else ""

    desktop = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=ScripTree\n"
        "Comment=Universal GUI for CLI tools\n"
        f"Exec={target_sh} %F\n"
        f"Path={HERE}\n"
        + icon_line +
        "Terminal=false\n"
        "Categories=Development;Utility;\n"
        "MimeType=application/x-scriptree;application/x-scriptreetree;\n"
    )
    path = dest_dir / "ScripTree.desktop"
    path.write_text(desktop, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


# ── macOS ────────────────────────────────────────────────────────────

def _make_macos_command(dest_dir: Path) -> Path:
    """Write ``<dest_dir>/ScripTree.command`` — double-clickable script.

    For a fully-branded Dock entry you eventually want a proper ``.app``
    bundle (Contents/MacOS/..., Info.plist with CFBundleIconFile, a
    ``.icns`` in Contents/Resources/). That's out of scope for a
    portable folder layout. At runtime the Dock + title bar icon come
    from ``QApplication.setWindowIcon`` with the PNG we ship, so the
    running app is still branded — only the Finder file icon is
    generic.
    """
    target_sh = HERE / "run_scriptree.sh"
    body = (
        "#!/usr/bin/env bash\n"
        f'cd "{HERE}" || exit 1\n'
        f'exec "{target_sh}" "$@"\n'
    )
    path = dest_dir / "ScripTree.command"
    path.write_text(body, encoding="utf-8")
    path.chmod(
        path.stat().st_mode
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH
    )
    return path


# ── CLI ──────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument(
        "dest", nargs="?", type=Path, default=HERE,
        help="Folder to write the shortcut into (default: repo root)",
    )
    args = ap.parse_args()
    dest = args.dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    if not _pick_icon():
        print(
            "Note: no icon file found at "
            f"{ICON_DIR}. Shortcut will use the system default.",
            file=sys.stderr,
        )

    if sys.platform == "win32":
        path = _make_windows_shortcut(dest)
    elif sys.platform == "darwin":
        path = _make_macos_command(dest)
    else:
        path = _make_linux_desktop(dest)

    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
