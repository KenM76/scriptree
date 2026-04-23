"""Cross-platform application branding helpers (icon + identity).

Responsibilities
----------------

* Locate the best available icon file for the current OS:

  - Windows prefers ``scriptree.ico`` (multi-res), falls back to PNG.
  - macOS prefers ``scriptree.icns``, falls back to PNG.
  - Linux uses ``scriptree.png``.

* Apply the icon to the running QApplication so title bars, taskbar,
  Dock, and Alt-Tab show our icon instead of the generic Python one.

* On Windows, call ``SetCurrentProcessExplicitAppUserModelID`` so the
  taskbar groups ScripTree windows under "ScripTree" (with our icon)
  instead of under "Python" along with every other python.exe process.

All functions are no-ops if PySide6 isn't importable or the icon files
are absent — ScripTree still runs, just without custom branding.
"""
from __future__ import annotations

import sys
from pathlib import Path

#: Stable identifier shown by Windows for taskbar grouping, file
#: associations, jump-list entries, etc. Format is "Company.Product[.Subproduct.Version]".
#: Don't change casually — changing this strands existing pinned taskbar
#: shortcuts.
APP_USER_MODEL_ID = "ScripTree.App"

#: Human-readable name used in places that accept a display string
#: (e.g. ``QApplication.setApplicationName``).
APP_DISPLAY_NAME = "ScripTree"

#: Resources folder — sibling to this file's parent (``core``).
_RESOURCES = Path(__file__).resolve().parent.parent / "resources"


def icon_path() -> Path | None:
    """Return the best icon file path for the current platform, or None.

    Search order per platform, first hit wins:

    * Windows:  ``scriptree.ico`` -> ``scriptree.png``
    * macOS:    ``scriptree.icns`` -> ``scriptree.png``
    * Linux/*:  ``scriptree.png`` -> ``scriptree.ico`` (last-ditch)
    """
    if sys.platform == "win32":
        candidates = ("scriptree.ico", "scriptree.png")
    elif sys.platform == "darwin":
        candidates = ("scriptree.icns", "scriptree.png")
    else:
        candidates = ("scriptree.png", "scriptree.ico")

    for name in candidates:
        p = _RESOURCES / name
        if p.is_file():
            return p
    return None


def set_windows_app_user_model_id(app_id: str = APP_USER_MODEL_ID) -> None:
    """Tell Windows to group our windows under our own taskbar identity.

    Without this call, Windows groups every python.exe under a single
    "Python" taskbar entry with the generic Python icon, regardless of
    what ``QApplication.setWindowIcon`` does. This must be called
    **before** any windows are shown.

    No-op on non-Windows platforms.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            app_id
        )
    except Exception:
        # Function is present on Windows 7+; worst case is generic
        # grouping — not worth crashing the app over.
        pass


def apply_branding(app) -> None:
    """Apply icon + display name + Windows AppUserModelID to ``app``.

    ``app`` is a ``QApplication`` (or ``QGuiApplication``) instance.
    Call this once immediately after constructing the application but
    before creating any windows.
    """
    # Windows taskbar grouping must happen before any HWND is created.
    set_windows_app_user_model_id()

    try:
        from PySide6.QtGui import QIcon
    except ImportError:
        return

    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)

    path = icon_path()
    if path is None:
        return
    icon = QIcon(str(path))
    if not icon.isNull():
        app.setWindowIcon(icon)
