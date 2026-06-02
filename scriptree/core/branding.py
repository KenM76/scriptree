"""Cross-platform application branding helpers (icon + identity).

## For humans

Responsibilities:

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

## For maintainers / LLMs

* No module-level Qt import: ``QIcon`` is imported lazily inside
  ``apply_branding`` (guarded by ``try/except ImportError``). Keep
  it that way — a top-level PySide6 import here would break the
  ``core`` purity test.
* ``APP_USER_MODEL_ID`` ("ScripTree.App") is a stable external
  identity. Changing it strands users' existing pinned taskbar
  shortcuts / jump-list entries — treat it as an ABI, not a constant
  to tidy.
* Call ordering is load-bearing: ``set_windows_app_user_model_id()``
  MUST run before any HWND/window is created (``apply_branding``
  calls it first for this reason). Callers must invoke
  ``apply_branding`` right after constructing the QApplication and
  before any window.
* ``_RESOURCES`` is computed as ``<this file>/../../resources`` —
  it assumes this file stays at ``scriptree/core/branding.py``.
  Moving the file silently breaks icon discovery (``icon_path``
  just returns ``None``, no error).
* Every Windows ctypes / icon failure is intentionally swallowed
  (broad ``except``): branding is cosmetic and must never crash or
  block startup. Don't "fix" these into raising.
* ``icon_path`` returns the first existing candidate; the Linux
  branch deliberately falls back to ``.ico`` last-ditch even though
  Linux can't render it well — better than no icon.
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


def _safe_app_id_segment(s: str) -> str:
    """Sanitise a free-form string for the AppUserModelID format.

    AUMID rules (Microsoft docs):
      * Reverse-DNS-style ``CompanyName.ProductName[.SubProduct[.Version]]``.
      * Each segment must NOT be empty, must NOT contain spaces, slashes,
        or the dot used as the separator -- everything else is fine in
        practice.

    We replace anything outside the safe set with an underscore, collapse
    runs, and trim.  Empty input -> ``"Tool"`` so the AUMID always has
    a non-empty subproduct segment.
    """
    import re as _re
    s = (s or "").strip()
    if not s:
        return "Tool"
    s = _re.sub(r"[^A-Za-z0-9_]+", "_", s)
    s = _re.sub(r"_+", "_", s).strip("_")
    return s or "Tool"


def apply_tool_branding(app, catalog_path: str | Path) -> None:
    """Override the app's icon and taskbar identity with the catalog's
    own when one is available.

    Designed to be called from a per-tool subprocess immediately
    after ``apply_branding(app)`` and BEFORE the window is created.
    Reads ``cell_icon_data`` (embedded base64) or ``cell_icon``
    (file path) from the catalog and:

      * Picks a per-tool ``AppUserModelID`` so Windows gives this
        tool its own taskbar slot instead of grouping it with the
        ScripTree.App parent.  Without this, every running tool
        stacks under the same taskbar icon (the forest's).
      * Calls ``app.setWindowIcon(icon)`` so the title bar, taskbar
        thumbnail, and Alt-Tab thumbnail all show the tool's icon.

    No-op when the catalog has no per-cell icon (or when the file
    can't be parsed) -- the generic ``apply_branding`` already
    applied the ScripTree icon, and we leave that in place.

    Why we don't fall back to the auto-classified glyph here: the
    classifier lives in ``scriptree.shell`` which we deliberately
    don't import from ``core``.  A tool that wants a taskbar icon
    has to set ``cell_icon_data`` explicitly (which the Settings ->
    Label/Icon tab does by default via the Library / Choose file
    flow).  An auto-classified-only catalog falls back to the
    generic ScripTree icon on the taskbar, same as today --
    visually consistent with the cell rendering's fallback path.
    """
    try:
        from pathlib import Path as _P
        from PySide6.QtGui import QIcon
    except ImportError:
        return

    p = _P(catalog_path)
    if not p.is_file():
        return

    # Load just the cell metadata -- avoid pulling in the full
    # ToolDef / TreeDef machinery for a branding helper.
    try:
        from .cell_metadata import make_pixmap_from_metadata, read_for
        md = read_for(p)
    except Exception:  # noqa: BLE001
        return

    # Compute a name to drive the AUMID and (later) the
    # window-title fallback.
    try:
        import json
        with p.open(encoding="utf-8") as fh:
            data = json.load(fh)
        tool_name = data.get("name") or p.stem
    except Exception:  # noqa: BLE001
        tool_name = p.stem
    aumid = f"{APP_USER_MODEL_ID}.{_safe_app_id_segment(tool_name)}"
    set_windows_app_user_model_id(aumid)

    if not md.has_icon():
        # No custom icon -- keep the ScripTree icon, just with the
        # per-tool AUMID so the taskbar still gives it its own slot.
        return

    try:
        pix = make_pixmap_from_metadata(md)
    except Exception:  # noqa: BLE001
        pix = None
    if pix is None or pix.isNull():
        return

    icon = QIcon(pix)
    if not icon.isNull():
        app.setWindowIcon(icon)


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
