"""
win_virtual_desktops.py — public-API access to Windows virtual
desktops for "follow the user" forest-hub behaviour.

## For humans

When the user puts the forest hub in taskbar mode (or any mode
where the hub is meant to be reachable from anywhere), they expect
PortableApps-style behaviour: the entry appears on EVERY virtual
desktop and clicking it doesn't yank them to whichever desktop the
window happened to live on.

The classic way to get this is to "pin" the window via
``IVirtualDesktopManagerInternal::PinWindow``.  That interface is
PRIVATE -- its IID changes with every Windows feature update
(Win10 1809, 21H2, Win11 21H2, 22H2, 23H2, 24H2 each have a
different IID), and the vtable layout shifts too.  Maintaining a
fallback chain across all of those means ScripTree silently breaks
on each new Windows release until we ship a matching IID.

a55 takes a different path with the SAME visible outcome:

  * Hook the focus-changed signal.  Whenever focus moves to a
    window on a different virtual desktop, we know the user
    switched.
  * Move the forest hub (and any visible descendants) to the user's
    current desktop via the PUBLIC
    ``IVirtualDesktopManager::MoveWindowToDesktop``.
  * Before any programmatic show (tray click, taskbar restore),
    make the same check so the hub appears on the desktop the user
    is actually looking at.

The user sees:
  * Taskbar entry visible on every desktop (because the window
    follows them).
  * Tray click never switches desktops (the hub moves first).
  * AOT hex follows them across desktops.

The user does NOT see:
  * A perfect "pinned" state.  If the user switches desktops while
    no other window has focus, focusWindowChanged doesn't fire and
    the follow happens on the NEXT focus event.  In practice that
    next event is a few hundred ms later when their pointer hits
    another window; the lag is imperceptible.

## For maintainers / LLMs

- Public API only.  CLSID_VirtualDesktopManager and
  IID_IVirtualDesktopManager have been stable since Win10 1607 and
  Microsoft has committed to keeping them.
- Wrap the COM vtable by hand via ctypes function pointers --
  no comtypes or pywin32 dependency so the portable build stays
  slim.
- Single cached singleton instance per process; create lazily on
  first call.
- ``ensure_on_current_desktop(hwnd)`` is idempotent and the hot
  path -- safe to call on every focus event.
- All public functions return ``False`` / ``None`` and log on
  non-Windows or any COM failure; the caller can ignore the
  return value if the desired behaviour is "best effort".
- COM init: we call ``CoInitializeEx`` in the thread that uses
  these functions.  Qt's main thread is STA already, so this is
  a no-op there; we still call defensively in case a worker
  thread imports the module.

Public API
----------
    is_supported() -> bool
    is_window_on_current_desktop(hwnd: int) -> bool
    get_current_desktop_id() -> _GUID | None
    move_window_to_desktop(hwnd: int, desktop_id: _GUID) -> bool
    ensure_on_current_desktop(hwnd: int) -> bool

Use the ``ensure_on_current_desktop`` helper from
``forest_visibility``; the lower-level functions are exposed for
testing and future extensions.
"""
from __future__ import annotations

import ctypes
import sys
import uuid
from ctypes import c_int, c_void_p, wintypes


def _log(msg: str) -> None:
    print(f"[win_virtual_desktops] {msg}", file=sys.stderr)


import os as _os

_DEBUG = bool(_os.environ.get("SCRIPTREE_VDM_DEBUG"))


def _dlog(msg: str) -> None:
    """Verbose log, gated on the ``SCRIPTREE_VDM_DEBUG`` env var.

    Set ``SCRIPTREE_VDM_DEBUG=1`` before launching ScripTree to
    see every COM call's HRESULT.  Useful when the
    follow-the-user logic doesn't appear to be working -- the
    log tells you whether ``MoveWindowToDesktop`` actually got
    called and what it returned.
    """
    if _DEBUG:
        print(f"[win_virtual_desktops:debug] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# COM constants and types
# ---------------------------------------------------------------------------

S_OK = 0
S_FALSE = 1
HRESULT = c_int

CLSCTX_INPROC_SERVER = 0x1
CLSCTX_LOCAL_SERVER = 0x4
CLSCTX_ALL = CLSCTX_INPROC_SERVER | CLSCTX_LOCAL_SERVER
COINIT_APARTMENTTHREADED = 0x2

# Public COM identifiers (stable since Win10 1607).
_CLSID_VirtualDesktopManager = "{AA509086-5CA9-4C25-8F95-589D3C07B48A}"
_IID_IVirtualDesktopManager = "{A5CD92FF-29BE-454C-8D04-D82879FB3F1B}"


class _GUID(ctypes.Structure):
    """The classic Win32 ``GUID`` struct.

    Public because callers (``forest_visibility``) may hold one
    across calls -- the type is small (16 bytes) and passing the
    same instance back via ``move_window_to_desktop`` is fine.
    """

    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _GUID):
            return False
        return (
            self.Data1 == other.Data1
            and self.Data2 == other.Data2
            and self.Data3 == other.Data3
            and bytes(self.Data4) == bytes(other.Data4)
        )

    def __hash__(self) -> int:
        return hash((
            self.Data1, self.Data2, self.Data3, bytes(self.Data4),
        ))


def _to_guid(s: str) -> _GUID:
    """Parse a ``{xxxxxxxx-xxxx-...}`` string into a ``_GUID``
    struct using Python's ``uuid`` module (which already knows the
    Windows byte ordering -- ``bytes_le`` is little-endian for the
    first three fields, big-endian for the last)."""
    u = uuid.UUID(s)
    b = u.bytes_le
    g = _GUID()
    g.Data1 = int.from_bytes(b[0:4], "little")
    g.Data2 = int.from_bytes(b[4:6], "little")
    g.Data3 = int.from_bytes(b[6:8], "little")
    for i in range(8):
        g.Data4[i] = b[8 + i]
    return g


# ---------------------------------------------------------------------------
# COM initialisation and IVirtualDesktopManager bootstrap
# ---------------------------------------------------------------------------

_initialised: bool = False
_vdm: c_void_p | None = None
_init_failed: bool = False


def _on_windows() -> bool:
    return sys.platform == "win32"


def _ensure_init() -> bool:
    """Lazy-init: CoInitialize + CoCreateInstance on first use.

    Caches the singleton instance so subsequent calls are zero-cost.
    Once initialisation has failed (e.g. unsupported Windows
    build, missing OLE) we don't retry -- avoid spamming the log
    from the focus watcher.
    """
    global _initialised, _vdm, _init_failed
    if _init_failed:
        return False
    if not _on_windows():
        _init_failed = True
        return False
    if _vdm is not None:
        return True
    try:
        ole32 = ctypes.windll.ole32
        if not _initialised:
            # COINIT_APARTMENTTHREADED is what Qt's main thread
            # already uses; calling it again returns S_FALSE,
            # which is benign.
            ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
            _initialised = True
        clsid = _to_guid(_CLSID_VirtualDesktopManager)
        iid = _to_guid(_IID_IVirtualDesktopManager)
        ptr = c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(clsid), None, CLSCTX_INPROC_SERVER,
            ctypes.byref(iid), ctypes.byref(ptr),
        )
        if hr != S_OK or not ptr.value:
            _log(
                f"CoCreateInstance(IVirtualDesktopManager) returned "
                f"HRESULT=0x{hr & 0xFFFFFFFF:08X}; virtual-desktop "
                f"follow-the-user disabled"
            )
            _init_failed = True
            return False
        _vdm = ptr.value
        return True
    except Exception as exc:  # noqa: BLE001
        _log(f"_ensure_init: {exc!r}")
        _init_failed = True
        return False


# ---------------------------------------------------------------------------
# Vtable call helper
# ---------------------------------------------------------------------------

def _call_vtable(
    this_ptr: c_void_p,
    method_index: int,
    restype: type,
    argtypes: list,
    *args,
):
    """Call method ``method_index`` on the COM vtable of ``this_ptr``.

    A COM object is a pointer to a vtable; the vtable is an array
    of function pointers, and ``method_index`` indexes that array
    (0 = QueryInterface, 1 = AddRef, 2 = Release, 3+ = interface
    methods).

    Every COM method takes ``this`` as its first parameter (the
    same value we're dispatching from), so we synthesize a
    ``WINFUNCTYPE`` that prepends ``c_void_p`` and then call it
    with ``this_ptr`` + the user's args.
    """
    vtable = ctypes.cast(this_ptr, ctypes.POINTER(c_void_p))[0]
    funcptr = ctypes.cast(vtable, ctypes.POINTER(c_void_p))[method_index]
    FuncType = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
    func = FuncType(funcptr)
    return func(this_ptr, *args)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# IVirtualDesktopManager vtable layout (after IUnknown's 3 entries):
#   3: HRESULT IsWindowOnCurrentVirtualDesktop(HWND, BOOL*)
#   4: HRESULT GetWindowDesktopId(HWND, GUID*)
#   5: HRESULT MoveWindowToDesktop(HWND, REFGUID)
#
# These offsets have been stable since Win10 1607.

def is_supported() -> bool:
    """True when the public ``IVirtualDesktopManager`` interface
    is available on this system.

    Cheap after the first call -- the underlying instance is
    cached.  False on non-Windows or when COM init fails (e.g.
    very old Windows builds that predate virtual desktops).
    """
    return _on_windows() and _ensure_init()


def is_window_on_current_desktop(hwnd: int) -> bool:
    """Return True when ``hwnd`` lives on the desktop the user is
    currently looking at.

    On failure (HWND no longer valid, COM call broke), returns
    True so the caller doesn't keep trying to move a dead window.
    """
    if not _ensure_init():
        return True
    try:
        result = wintypes.BOOL()
        hr = _call_vtable(
            _vdm, 3, HRESULT,
            [wintypes.HWND, ctypes.POINTER(wintypes.BOOL)],
            wintypes.HWND(hwnd), ctypes.byref(result),
        )
        return hr == S_OK and bool(result.value)
    except Exception as exc:  # noqa: BLE001
        _log(f"is_window_on_current_desktop: {exc!r}")
        return True


def get_window_desktop_id(hwnd: int) -> _GUID | None:
    """Get the desktop GUID where ``hwnd`` currently resides.

    Returns ``None`` on any failure.  Use this to discover the
    user's current desktop indirectly via the foreground window:
    ``get_window_desktop_id(user32.GetForegroundWindow())``.
    """
    if not _ensure_init():
        return None
    try:
        result = _GUID()
        hr = _call_vtable(
            _vdm, 4, HRESULT,
            [wintypes.HWND, ctypes.POINTER(_GUID)],
            wintypes.HWND(hwnd), ctypes.byref(result),
        )
        if hr != S_OK:
            return None
        return result
    except Exception as exc:  # noqa: BLE001
        _log(f"get_window_desktop_id: {exc!r}")
        return None


def get_current_desktop_id() -> _GUID | None:
    """Discover the user's current virtual desktop ID by looking
    at the foreground window.

    The foreground window is by definition the one the user is
    interacting with, which is on their current desktop.  If
    there's no foreground window (rare -- briefly during desktop
    transitions), returns ``None``.
    """
    if not _ensure_init():
        return None
    try:
        user32 = ctypes.windll.user32
        fg = user32.GetForegroundWindow()
        if not fg:
            return None
        return get_window_desktop_id(int(fg))
    except Exception as exc:  # noqa: BLE001
        _log(f"get_current_desktop_id: {exc!r}")
        return None


def move_window_to_desktop(hwnd: int, desktop_id: _GUID) -> bool:
    """Move ``hwnd`` to the desktop whose GUID is ``desktop_id``.

    Returns True on success.  Idempotent -- moving a window to
    its current desktop is cheap and harmless.
    """
    if not _ensure_init():
        return False
    try:
        hr = _call_vtable(
            _vdm, 5, HRESULT,
            [wintypes.HWND, ctypes.POINTER(_GUID)],
            wintypes.HWND(hwnd), ctypes.byref(desktop_id),
        )
        _dlog(
            f"MoveWindowToDesktop(hwnd=0x{hwnd:X}) -> "
            f"HRESULT=0x{hr & 0xFFFFFFFF:08X} "
            f"{'OK' if hr == S_OK else 'FAIL'}"
        )
        return hr == S_OK
    except Exception as exc:  # noqa: BLE001
        _log(f"move_window_to_desktop: {exc!r}")
        return False


def ensure_on_current_desktop(hwnd: int) -> bool:
    """Move ``hwnd`` to the user's current desktop if it isn't
    already there.

    Hot path -- called from the forest focus watcher on every
    focus event AND before every programmatic forest show.  The
    short-circuit via ``is_window_on_current_desktop`` makes the
    common case (window already on current desktop) a single
    COM call.

    Returns True on success or no-op; False on failure.
    """
    if not _ensure_init():
        return False
    if not hwnd:
        return False
    try:
        if is_window_on_current_desktop(hwnd):
            return True
        desktop_id = get_current_desktop_id()
        if desktop_id is None:
            return False
        return move_window_to_desktop(hwnd, desktop_id)
    except Exception as exc:  # noqa: BLE001
        _log(f"ensure_on_current_desktop: {exc!r}")
        return False
