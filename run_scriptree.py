#!/usr/bin/env python3
"""ScripTree launcher.

This is the top-level entry point. It adds the ScripTree package
directory to ``sys.path`` so ``scriptree`` is importable, then
delegates to ``scriptree.main.main()``.

**Vendored dependencies:** If ``lib/pypi/`` contains packages (run
``python lib/update_lib.py`` once to populate it), they are preferred
over any system-installed versions. This makes the whole folder
self-contained and portable. Set ``SCRIPTREE_USE_SYSTEM_DEPS=1`` to
disable this and fall back to the system Python environment.

Environment variables:

    SCRIPTREE_PYTHON
        Path to an alternate Python executable (e.g. a PortableApps
        Python). When set, ScripTree offers to install dependencies
        into that Python environment as well as the current one.

    SCRIPTREE_USE_SYSTEM_DEPS
        When set to ``1``, skip the vendored ``lib/pypi/`` directory
        and use whatever the system Python provides.

Usage::

    python run_scriptree.py
    python run_scriptree.py path/to/tool.scriptree
    python run_scriptree.py path/to/tree.scriptreetree -configuration standalone
"""
import os
import subprocess
import sys
from pathlib import Path

# ── Pre-flight checks ──────────────────────────────────────────────────

def _check_python_version():
    """Ensure Python >= 3.11."""
    if sys.version_info < (3, 11):
        msg = (
            f"ScripTree requires Python 3.11 or later.\n"
            f"You are running Python {sys.version_info.major}"
            f".{sys.version_info.minor}.{sys.version_info.micro}.\n"
            f"\n"
            f"Download the latest Python from https://www.python.org/downloads/"
        )
        print(msg, file=sys.stderr)
        _msgbox(msg, "ScripTree \u2014 Python Version")
        sys.exit(1)


def _msgbox(text: str, title: str, *, style: int = 0x10) -> None:
    """Show a native Windows MessageBox (no-op on other platforms)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, style)
    except Exception:
        pass


def _yesno_box(text: str, title: str) -> bool:
    """Show a Yes/No MessageBox on Windows. Returns True for Yes.
    On non-Windows, falls back to terminal input."""
    if sys.platform == "win32":
        try:
            import ctypes
            MB_YESNO = 0x04
            MB_ICONQUESTION = 0x20
            IDYES = 6
            result = ctypes.windll.user32.MessageBoxW(
                0, text, title, MB_YESNO | MB_ICONQUESTION
            )
            return result == IDYES
        except Exception:
            pass
    # Terminal fallback.
    try:
        answer = input(f"{text}\n\nInstall now? [y/N] ").strip().lower()
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def _pick_python_target(missing_names: str) -> str | None:
    """If SCRIPTREE_PYTHON is set, ask the user which Python to install
    into. Returns the chosen Python executable path, or None to cancel.

    When SCRIPTREE_PYTHON is not set, returns sys.executable (the
    current Python) without prompting.
    """
    alt_python = os.environ.get("SCRIPTREE_PYTHON", "").strip()
    current = sys.executable

    if not alt_python or not Path(alt_python).exists():
        # No alternate — just use current Python.
        return current

    if alt_python == current:
        return current

    # Two Pythons available — ask which one.
    current_label = f"Current Python ({current})"
    alt_label = f"SCRIPTREE_PYTHON ({alt_python})"

    if sys.platform == "win32":
        try:
            import ctypes
            MB_YESNOCANCEL = 0x03
            MB_ICONQUESTION = 0x20
            IDYES = 6
            IDNO = 7
            # Yes = current, No = alternate, Cancel = abort
            result = ctypes.windll.user32.MessageBoxW(
                0,
                f"ScripTree needs to install: {missing_names}\n\n"
                f"Two Python installations were found:\n\n"
                f"  Yes  \u2192  {current_label}\n"
                f"  No   \u2192  {alt_label}\n"
                f"  Cancel \u2192  Don't install\n\n"
                f"Which Python should the packages be installed into?",
                "ScripTree \u2014 Choose Python",
                MB_YESNOCANCEL | MB_ICONQUESTION,
            )
            if result == IDYES:
                return current
            elif result == IDNO:
                return alt_python
            else:
                return None
        except Exception:
            pass

    # Terminal fallback.
    print(f"\nScripTree needs to install: {missing_names}")
    print(f"\nTwo Python installations found:")
    print(f"  [1] {current_label}")
    print(f"  [2] {alt_label}")
    print(f"  [0] Cancel")
    try:
        choice = input("\nInstall into which Python? [1/2/0] ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if choice == "1":
        return current
    elif choice == "2":
        return alt_python
    return None


def _install_packages(python_exe: str, packages: list[str]) -> bool:
    """Run pip install for the given packages. Returns True on success."""
    cmd = [python_exe, "-m", "pip", "install"] + packages
    print(f"\nInstalling: {' '.join(packages)}")
    print(f"Running: {' '.join(cmd)}\n")
    try:
        result = subprocess.run(cmd, timeout=300)
        return result.returncode == 0
    except FileNotFoundError:
        print(f"Error: Could not find Python at {python_exe}", file=sys.stderr)
        return False
    except subprocess.TimeoutExpired:
        print("Error: Installation timed out after 5 minutes.", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error during installation: {e}", file=sys.stderr)
        return False


def _inject_vendored_libs():
    """Prepend ``lib/pypi/`` to ``sys.path`` so vendored deps win, and
    isolate the process from user site-packages that could pull in
    incompatible binaries (e.g. a globally-installed PySide6 whose DLLs
    mix with our vendored ones, or numpy 1.x/2.x mismatches from
    unrelated global packages).

    When ``SCRIPTREE_USE_SYSTEM_DEPS=1`` is set, this is a no-op and
    the system Python environment provides everything.
    """
    if os.environ.get("SCRIPTREE_USE_SYSTEM_DEPS", "").strip() == "1":
        return
    here = Path(__file__).resolve().parent
    pypi = here / "lib" / "pypi"
    if not pypi.is_dir():
        return
    # Only inject if there's something in there besides .gitkeep,
    # so an empty lib/pypi/ doesn't mask the dep-missing check.
    entries = [p for p in pypi.iterdir() if p.name != ".gitkeep"]
    if not entries:
        return

    pypi_str = str(pypi)

    # 1. Strip user site-packages from sys.path. Leaving them in means
    #    `import somepackage` can pick up a globally-installed copy that
    #    was compiled against a different numpy/Qt/etc, causing the
    #    classic "module compiled using NumPy 1.x cannot be run in
    #    NumPy 2.x" crash at import time.
    try:
        import site
        bad = set()
        usersite = getattr(site, "getusersitepackages", lambda: None)()
        if usersite:
            bad.add(os.path.normcase(os.path.abspath(usersite)))
        for p in getattr(site, "getsitepackages", lambda: [])():
            bad.add(os.path.normcase(os.path.abspath(p)))
        sys.path[:] = [
            p for p in sys.path
            if os.path.normcase(os.path.abspath(p or ".")) not in bad
        ]
    except Exception:
        pass

    # 2. Prepend the vendored folder so our copies win.
    sys.path.insert(0, pypi_str)

    # 3. Prevent any child Python processes from re-enabling user site.
    os.environ["PYTHONNOUSERSITE"] = "1"

    # 4. Point Qt at the vendored plugins explicitly so it doesn't try
    #    to auto-discover a system PySide6's plugins folder and mix DLLs.
    qt_plugin_dir = pypi / "PySide6" / "plugins"
    if qt_plugin_dir.is_dir():
        os.environ["QT_PLUGIN_PATH"] = str(qt_plugin_dir)
        platforms_dir = qt_plugin_dir / "platforms"
        if platforms_dir.is_dir():
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms_dir)

    # 5. On Windows, add the PySide6 folder as a DLL search path so
    #    Qt6Core.dll etc. resolve to the vendored copies, not whatever
    #    is on PATH.
    if sys.platform == "win32":
        pyside_dir = pypi / "PySide6"
        if pyside_dir.is_dir() and hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(pyside_dir))
            except (OSError, FileNotFoundError):
                pass


def _check_dependencies():
    """Check that required packages are installed. If any are missing,
    offer to install them automatically."""
    missing = []

    try:
        import PySide6  # noqa: F401
    except ImportError:
        missing.append("PySide6")

    if not missing:
        return

    names = ", ".join(missing)

    # Ask the user if they want to auto-install.
    # Prefer the vendored workflow (lib/update_lib.py) if this project
    # has the lib/ folder — it keeps the install self-contained.
    here = Path(__file__).resolve().parent
    have_vendor_workflow = (here / "lib" / "update_lib.py").is_file()
    vendor_hint = (
        "\n\nTip: this project has a vendored-deps workflow. You can\n"
        "also run:\n\n    python lib/update_lib.py\n\n"
        "to install into lib/pypi/ instead of your system Python."
        if have_vendor_workflow else ""
    )

    want_install = _yesno_box(
        f"ScripTree is missing required dependencies:\n\n"
        f"    {names}\n\n"
        f"Would you like ScripTree to download and install them now?\n\n"
        f"(Requires an internet connection. This may take a minute.)"
        + vendor_hint,
        "ScripTree \u2014 Missing Dependencies",
    )

    if not want_install:
        msg = (
            f"ScripTree cannot run without: {names}\n"
            f"To install manually, run:  pip install {' '.join(missing)}"
        )
        if have_vendor_workflow:
            msg += (
                "\nOr use the vendored workflow:  "
                "python lib/update_lib.py"
            )
        print(msg, file=sys.stderr)
        sys.exit(1)

    # Pick which Python to install into.
    target = _pick_python_target(names)
    if target is None:
        print("Installation cancelled.", file=sys.stderr)
        sys.exit(1)

    success = _install_packages(target, missing)
    if not success:
        _msgbox(
            f"Failed to install {names}.\n\n"
            f"Try installing manually:\n\n"
            f"    {target} -m pip install {' '.join(missing)}",
            "ScripTree \u2014 Installation Failed",
        )
        sys.exit(1)

    # If we installed into an alternate Python, we need to tell the
    # user to re-run with that Python.
    if target != sys.executable:
        msg = (
            f"Dependencies installed into:\n    {target}\n\n"
            f"Please re-run ScripTree using that Python:\n\n"
            f"    \"{target}\" \"{__file__}\""
        )
        print(msg)
        _msgbox(msg, "ScripTree \u2014 Installed Successfully", style=0x40)
        sys.exit(0)

    # Installed into current Python — verify the import now works.
    try:
        import PySide6  # noqa: F401, F811
    except ImportError:
        _msgbox(
            f"Installation appeared to succeed but PySide6 still "
            f"cannot be imported.\n\n"
            f"Try restarting your terminal and running ScripTree again.",
            "ScripTree \u2014 Import Error",
        )
        sys.exit(1)

    print("Dependencies installed successfully. Starting ScripTree...\n")


# ── Launch ─────────────────────────────────────────────────────────────

_check_python_version()
_inject_vendored_libs()
_check_dependencies()

# Add the ScripTree subdirectory (which contains the ``scriptree`` package)
# to the Python path so imports work without installing.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "ScripTree"))

from scriptree.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
