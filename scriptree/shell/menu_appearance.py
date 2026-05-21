"""User-tunable font + icon size for the popup menus that appear
above cells, rings, and the forest hub (v0.6.21+).

Resolution order
----------------

  local QSettings  →  shared JSON file  →  built-in defaults

The "Menu" tab in the cell Settings dialog writes values to whichever
of (local, shared) the user has ticked at the moment of the change.
The shared write is gated by the ``menu_appearance_shared_write``
capability so an admin can deny org-wide tweaking from end-user
machines while still letting individual users have their own scale.

Built-in defaults
-----------------

* ``font_pct = 125`` — the menus render 25% bigger than the OS
  default font size on a fresh install (user requested baseline).
* ``font_pt  = None`` — None means "use the percent slider"; a
  positive int overrides percent with an absolute point size.
* ``icon_pct = 125`` — same baseline for the action icons.

No module-level Qt import — the resolution side is pure I/O so the
``core`` purity test stays green if anything moves around.  Qt's
``QFont`` and stylesheet wiring live entirely in ``tree_popup.py``.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


def _log(msg: str) -> None:
    print(f"[menu_appearance] {msg}", file=sys.stderr)


DEFAULT_FONT_PCT = 125
DEFAULT_ICON_PCT = 125
DEFAULT_FONT_PT: int | None = None  # None = use percent


@dataclass
class MenuAppearance:
    """Resolved menu-appearance values for the current session.

    Plain dataclass so it's trivially JSON-able.  ``font_pt is None``
    means "use ``font_pct`` × the OS default font size"; a positive
    int means "render the menu at this absolute point size".
    ``icon_pct`` always uses the percent path (icons don't get
    an absolute-pixel override — keeps the UI minimal).
    """

    font_pct: int = DEFAULT_FONT_PCT
    font_pt: int | None = DEFAULT_FONT_PT
    icon_pct: int = DEFAULT_ICON_PCT


@dataclass
class CellDefaults:
    """v0.6.21 — global default shape/orientation/size for *newly
    spawned* cells.  Per-cell QSettings always wins for an existing
    cell; this struct is consulted only when constructing a fresh
    standalone with no persisted state.

    Stored in the same QSettings prefix (``cell_defaults/``) and the
    same shared JSON file as ``MenuAppearance`` — the user requested
    they share a single security gate
    (``menu_appearance_shared_write``).  ``shape`` and
    ``orientation`` track the same string vocabulary the
    ``CellWindow`` constructor uses (``"hexagon"``/``"square"`` etc.,
    ``"flat-top"``/``"pointy-top"``).  Defaults match the branding
    defaults so a fresh install behaves identically to pre-v0.6.21.
    """

    shape: str = "hexagon"
    orientation: str = "flat-top"
    size_px: int = 56


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def shared_menu_appearance_path(branding: dict) -> Path:
    """Where the machine-wide menu-appearance JSON lives.

    Windows : ``%ProgramData%\\<brand>\\menu_appearance.json``
    macOS   : ``/Users/Shared/<brand>/menu_appearance.json``
    Linux   : ``/usr/local/share/<brand>/menu_appearance.json``

    The shared file is OPTIONAL — when absent, the per-user QSettings
    or the built-in defaults take over.  Reads tolerate a missing /
    unreadable / malformed file; writes require the
    ``menu_appearance_shared_write`` capability.
    """
    brand_name = branding.get("appName", "ScripTree")
    if sys.platform == "win32":
        base = Path(
            os.environ.get("ProgramData", r"C:\ProgramData")
        ) / brand_name
    elif sys.platform == "darwin":
        base = Path("/Users/Shared") / brand_name
    else:
        base = Path("/usr/local/share") / brand_name
    return base / "menu_appearance.json"


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

_QSETTINGS_PREFIX = "menu_appearance/"


def _load_from_qsettings():  # noqa: ANN202
    """Read whatever local overrides QSettings carries (Qt-bound).

    Returns ``(font_pct, font_pt, icon_pct)`` where each is the
    persisted value or ``None`` if not set.  All Qt access is local
    to keep ``core`` purity intact.
    """
    try:
        from PySide6.QtCore import QSettings
    except Exception:  # noqa: BLE001
        return (None, None, None)
    s = QSettings()
    raw_fpct = s.value(_QSETTINGS_PREFIX + "font_pct")
    raw_fpt = s.value(_QSETTINGS_PREFIX + "font_pt")
    raw_ipct = s.value(_QSETTINGS_PREFIX + "icon_pct")

    def _to_int(v):  # noqa: ANN001, ANN202
        try:
            return int(v) if v is not None and str(v) != "" else None
        except (TypeError, ValueError):
            return None

    return (_to_int(raw_fpct), _to_int(raw_fpt), _to_int(raw_ipct))


def _load_from_shared(branding: dict):  # noqa: ANN202
    """Read the shared JSON file.  Returns the same 3-tuple shape as
    ``_load_from_qsettings``; missing keys / malformed file degrade
    silently to ``None``.
    """
    p = shared_menu_appearance_path(branding)
    if not p.is_file():
        return (None, None, None)
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _log(f"load_from_shared: {p}: {exc!r}; ignoring")
        return (None, None, None)

    def _to_int(v):  # noqa: ANN001, ANN202
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    return (
        _to_int(blob.get("font_pct")),
        _to_int(blob.get("font_pt")),
        _to_int(blob.get("icon_pct")),
    )


def load_menu_appearance(branding: dict) -> MenuAppearance:
    """Resolve the live values for the current session.

    Per-field precedence: **local QSettings wins** over the shared
    JSON, shared wins over the built-in default.  This lets a user
    selectively override one field (e.g. font_pt) while inheriting
    the rest from the shared file.
    """
    l_fpct, l_fpt, l_ipct = _load_from_qsettings()
    s_fpct, s_fpt, s_ipct = _load_from_shared(branding)

    def _pick_int(local, shared, default):  # noqa: ANN001, ANN202
        if local is not None:
            return local
        if shared is not None:
            return shared
        return default

    def _pick_opt_int(local, shared, default):  # noqa: ANN001, ANN202
        # Same precedence but ``font_pt`` can legitimately be None;
        # encode "explicitly cleared" via the sentinel 0.
        if local is not None:
            return None if local == 0 else local
        if shared is not None:
            return None if shared == 0 else shared
        return default

    return MenuAppearance(
        font_pct=_pick_int(l_fpct, s_fpct, DEFAULT_FONT_PCT),
        font_pt=_pick_opt_int(l_fpt, s_fpt, DEFAULT_FONT_PT),
        icon_pct=_pick_int(l_ipct, s_ipct, DEFAULT_ICON_PCT),
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _save_to_qsettings(values: MenuAppearance) -> None:
    try:
        from PySide6.QtCore import QSettings
    except Exception:  # noqa: BLE001
        return
    s = QSettings()
    s.setValue(_QSETTINGS_PREFIX + "font_pct", int(values.font_pct))
    # ``font_pt = None`` is encoded as 0 in storage (treat as "auto").
    s.setValue(
        _QSETTINGS_PREFIX + "font_pt",
        int(values.font_pt) if values.font_pt is not None else 0,
    )
    s.setValue(_QSETTINGS_PREFIX + "icon_pct", int(values.icon_pct))
    s.sync()


def _save_to_shared(values: MenuAppearance, branding: dict) -> None:
    """Merge-write the menu-appearance keys into the shared JSON.

    Cell-default keys (``cell_shape``, ``cell_orientation``,
    ``cell_size_px``) — see :pyfunc:`_save_cell_defaults_to_shared`
    — share the same file, so we read-modify-write rather than
    overwriting the whole blob.
    """
    p = shared_menu_appearance_path(branding)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if p.is_file():
        try:
            existing = json.loads(p.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError, json.JSONDecodeError):
            existing = {}
    existing["font_pct"] = int(values.font_pct)
    existing["font_pt"] = (
        int(values.font_pt) if values.font_pt is not None else None
    )
    existing["icon_pct"] = int(values.icon_pct)
    p.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    _log(f"_save_to_shared: wrote {p}")


def save_menu_appearance(
    values: MenuAppearance,
    *,
    save_local: bool = True,
    save_shared: bool = False,
    branding: dict | None = None,
) -> None:
    """Persist ``values`` to the requested destinations.

    ``save_local``  — write to QSettings (per-user, this machine).
    ``save_shared`` — write to the machine-wide shared JSON.  The
    caller is expected to have already checked the
    ``menu_appearance_shared_write`` capability; we don't
    re-check here so unit tests can drive the path freely.
    """
    if save_local:
        try:
            _save_to_qsettings(values)
        except Exception as exc:  # noqa: BLE001
            _log(f"save_to_qsettings raised {exc!r}")
    if save_shared:
        if branding is None:
            _log("save_to_shared: branding is None — skipping shared write")
            return
        try:
            _save_to_shared(values, branding)
        except Exception as exc:  # noqa: BLE001
            _log(f"save_to_shared raised {exc!r}")


# ---------------------------------------------------------------------------
# Cell defaults — shape / orientation / size for fresh cells
# ---------------------------------------------------------------------------

_CELL_QSETTINGS_PREFIX = "cell_defaults/"

DEFAULT_CELL_SHAPE = "hexagon"
DEFAULT_CELL_ORIENTATION = "flat-top"
DEFAULT_CELL_SIZE_PX = 56


def _load_cell_defaults_from_qsettings():  # noqa: ANN202
    try:
        from PySide6.QtCore import QSettings
    except Exception:  # noqa: BLE001
        return (None, None, None)
    s = QSettings()
    raw_sh = s.value(_CELL_QSETTINGS_PREFIX + "shape")
    raw_or = s.value(_CELL_QSETTINGS_PREFIX + "orientation")
    raw_sz = s.value(_CELL_QSETTINGS_PREFIX + "size_px")
    sh = str(raw_sh) if raw_sh else None
    orient = str(raw_or) if raw_or else None
    try:
        sz = int(raw_sz) if raw_sz else None
    except (TypeError, ValueError):
        sz = None
    return (sh, orient, sz)


def _load_cell_defaults_from_shared(branding: dict):  # noqa: ANN202
    p = shared_menu_appearance_path(branding)
    if not p.is_file():
        return (None, None, None)
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _log(f"load_cell_defaults_from_shared: {p}: {exc!r}")
        return (None, None, None)
    sh = blob.get("cell_shape")
    orient = blob.get("cell_orientation")
    sz = blob.get("cell_size_px")
    try:
        sz = int(sz) if sz is not None else None
    except (TypeError, ValueError):
        sz = None
    return (
        str(sh) if sh else None,
        str(orient) if orient else None,
        sz,
    )


def load_cell_defaults(branding: dict) -> CellDefaults:
    """Resolve the live cell-default values.  Local QSettings wins
    over shared JSON wins over built-in defaults — same precedence
    as :pyfunc:`load_menu_appearance`."""
    l_sh, l_or, l_sz = _load_cell_defaults_from_qsettings()
    s_sh, s_or, s_sz = _load_cell_defaults_from_shared(branding)

    def _pick(local, shared, default):  # noqa: ANN001, ANN202
        if local is not None:
            return local
        if shared is not None:
            return shared
        return default

    return CellDefaults(
        shape=_pick(l_sh, s_sh, DEFAULT_CELL_SHAPE),
        orientation=_pick(l_or, s_or, DEFAULT_CELL_ORIENTATION),
        size_px=int(_pick(l_sz, s_sz, DEFAULT_CELL_SIZE_PX)),
    )


def _save_cell_defaults_to_qsettings(values: CellDefaults) -> None:
    try:
        from PySide6.QtCore import QSettings
    except Exception:  # noqa: BLE001
        return
    s = QSettings()
    s.setValue(_CELL_QSETTINGS_PREFIX + "shape", str(values.shape))
    s.setValue(
        _CELL_QSETTINGS_PREFIX + "orientation", str(values.orientation),
    )
    s.setValue(_CELL_QSETTINGS_PREFIX + "size_px", int(values.size_px))
    s.sync()


def _save_cell_defaults_to_shared(
    values: CellDefaults, branding: dict,
) -> None:
    p = shared_menu_appearance_path(branding)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Merge with any existing menu-appearance keys so we don't
    # clobber the other half of the shared file.
    existing: dict = {}
    if p.is_file():
        try:
            existing = json.loads(p.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError, json.JSONDecodeError):
            existing = {}
    existing["cell_shape"] = str(values.shape)
    existing["cell_orientation"] = str(values.orientation)
    existing["cell_size_px"] = int(values.size_px)
    p.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    _log(f"_save_cell_defaults_to_shared: wrote {p}")


def save_cell_defaults(
    values: CellDefaults,
    *,
    save_local: bool = True,
    save_shared: bool = False,
    branding: dict | None = None,
) -> None:
    """Persist the cell-default values.  Same destination semantics
    as :pyfunc:`save_menu_appearance`."""
    if save_local:
        try:
            _save_cell_defaults_to_qsettings(values)
        except Exception as exc:  # noqa: BLE001
            _log(f"save_cell_defaults_to_qsettings raised {exc!r}")
    if save_shared:
        if branding is None:
            _log(
                "save_cell_defaults: branding is None — "
                "skipping shared write"
            )
            return
        try:
            _save_cell_defaults_to_shared(values, branding)
        except Exception as exc:  # noqa: BLE001
            _log(f"save_cell_defaults_to_shared raised {exc!r}")


__all__ = [
    "DEFAULT_FONT_PCT",
    "DEFAULT_FONT_PT",
    "DEFAULT_ICON_PCT",
    "DEFAULT_CELL_SHAPE",
    "DEFAULT_CELL_ORIENTATION",
    "DEFAULT_CELL_SIZE_PX",
    "MenuAppearance",
    "CellDefaults",
    "load_menu_appearance",
    "save_menu_appearance",
    "load_cell_defaults",
    "save_cell_defaults",
    "shared_menu_appearance_path",
]
