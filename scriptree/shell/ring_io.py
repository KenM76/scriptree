"""
ring_io.py â€” Save / load master-hexagon groups as .scriptreering files.

Public API
----------
    save_ring(master, path)                          â†’ None
    load_ring(path, branding, registry, snap_engine) â†’ CellWindow (master)
    list_autoload_rings(scope)                       â†’ list[Path]
    add_autoload_ring(path, scope)                   â†’ None
    remove_autoload_ring(path, scope)                â†’ None

Windows-only helpers (no-ops / raise on non-Windows):
    register_autostart(scope, cmd)
    unregister_autostart(scope)

Platform: Windows 11 (winreg module).  Non-Windows platforms receive a logged
warning and a no-op for the registry functions.  save_ring / load_ring work on
all platforms.

Format reference: docs/specs/scriptreering-format.md
"""

from __future__ import annotations

import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from scriptree.shell.cell_window import CellWindow
    from scriptree.shell.cell_registry import CellRegistry
    from scriptree.shell.snap_engine import SnapEngine


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(f"[ring_io] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Brand / path helpers
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    """Walk up from this file until we find branding/branding.config.json."""
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / "branding" / "branding.config.json").is_file():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise FileNotFoundError(
        "Cannot locate project root (branding/branding.config.json not found)"
    )


def _appdata_dir(brand_name: str) -> Path:
    """Return <APPDATA>/<brand_name> on Windows; XDG_CONFIG_HOME on Linux/Mac."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config"
        )
    return Path(base) / brand_name


def _programdata_dir(brand_name: str) -> Path:
    """Return <PROGRAMDATA>/<brand_name> (Windows only)."""
    if sys.platform == "win32":
        base = os.environ.get("PROGRAMDATA") or "C:/ProgramData"
    else:
        base = "/etc"
    return Path(base) / brand_name


def _autoload_config_path(brand_name: str, scope: Literal["user", "system"]) -> Path:
    """Return path to the autoload config JSON for the given scope."""
    if scope == "user":
        return _appdata_dir(brand_name) / "autoload_rings.json"
    else:
        return _programdata_dir(brand_name) / "autoload_rings.json"


def _default_rings_dir(brand_name: str) -> Path:
    """<USERPROFILE>/Documents/<BRAND>/rings/ â€” created on demand."""
    if sys.platform == "win32":
        docs = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Documents"
    else:
        docs = Path(os.path.expanduser("~")) / "Documents"
    d = docs / brand_name / "rings"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Position clamping
# ---------------------------------------------------------------------------

def _clamp_position(x: int, y: int, size_px: int) -> tuple[int, int]:
    """Clamp (x, y) so the widget fully fits within the nearest screen's
    availableGeometry(). Falls back to primary screen if centre is off-screen.
    """
    try:
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QGuiApplication

        pt = QPoint(x + size_px // 2, y + size_px // 2)
        screen = QGuiApplication.screenAt(pt)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return (max(0, x), max(0, y))

        avail = screen.availableGeometry()
        clamped_x = max(avail.left(), min(x, avail.right() - size_px))
        clamped_y = max(avail.top(), min(y, avail.bottom() - size_px))
        return (clamped_x, clamped_y)
    except Exception as exc:
        _log(f"_clamp_position: fallback due to error: {exc!r}")
        return (max(0, x), max(0, y))


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

_FORMAT = "scriptreering"
_VERSION = 1


def _hex_to_dict(hex_win: "CellWindow", include_member_fields: bool = False) -> dict:
    """Serialise a single CellWindow to a plain dict.

    include_member_fields â€” add preferred_position, catalog_path, is_positioned
    (only meaningful for member hexes within a master's _members set).
    These are populated by save_ring() which has access to the master's state.
    """
    return {
        "shape": hex_win._shape,
        "orientation": hex_win._orientation,
        "size_px": hex_win._size_px,
        "transparency": hex_win._transparency,
        "always_on_top": hex_win._always_on_top,
        "position": {"x": hex_win.pos().x(), "y": hex_win.pos().y()},
    }


def _coerce_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes")
    return bool(v)


def _load_hex_fields(d: dict, size_px: int | None = None) -> dict:
    """Parse and clamp per-hex fields from a raw dict.

    Returns a normalised dict with keys: shape, orientation, size_px,
    transparency, always_on_top, pos_x, pos_y.
    """
    shape = d.get("shape", "hexagon")
    if shape not in ("hexagon", "square"):
        _log(f"Unknown shape {shape!r} â€” coerced to 'hexagon'")
        shape = "hexagon"

    orientation = d.get("orientation", "flat-top")
    if orientation not in ("flat-top", "pointy-top"):
        _log(f"Unknown orientation {orientation!r} â€” coerced to 'flat-top'")
        orientation = "flat-top"

    raw_size = d.get("size_px", size_px or 56)
    try:
        sz = max(32, min(96, int(raw_size)))
    except (TypeError, ValueError):
        sz = 56

    raw_transp = d.get("transparency", 0.85)
    try:
        transp = max(0.30, min(1.00, float(raw_transp)))
    except (TypeError, ValueError):
        transp = 0.85

    always_on_top = _coerce_bool(d.get("always_on_top", True))

    pos = d.get("position") or {}
    raw_x = pos.get("x", 100)
    raw_y = pos.get("y", 100)
    try:
        x, y = int(raw_x), int(raw_y)
    except (TypeError, ValueError):
        x, y = 100, 100

    cx, cy = _clamp_position(x, y, sz)

    return {
        "shape": shape,
        "orientation": orientation,
        "size_px": sz,
        "transparency": transp,
        "always_on_top": always_on_top,
        "pos_x": cx,
        "pos_y": cy,
    }


# ---------------------------------------------------------------------------
# Public API: save_ring
# ---------------------------------------------------------------------------

def save_ring(hex_window: "CellWindow", path: Path) -> None:
    """Serialise a hexagon group (or single standalone hex) to a .scriptreering file.

    Accepts either a master hexagon (role == 'master') or a standalone hexagon
    (role == 'standalone').

    Master case: serialises the master descriptor plus all members from
    hex_window._members (Amendment 2 authoritative set).

    Standalone case: serialises the hex itself as the master descriptor with an
    empty members list.  The resulting .scriptreering is a valid single-hex ring â€”
    load_ring() will spawn one standalone hex at the saved position.

    Raises ValueError if hex_window.role is neither 'master' nor 'standalone'.
    Raises OSError if the file cannot be written.
    """
    if hex_window.role not in ("master", "standalone"):
        raise ValueError(
            f"save_ring: expected role 'master' or 'standalone', "
            f"got role={hex_window.role!r} (id={hex_window._id[:8]})"
        )

    brand_name: str = hex_window._branding.get("appName", "ScripTree")

    if hex_window.role == "standalone":
        # Single-hex ring: the standalone IS the master entry; members is empty.
        master_dict = _hex_to_dict(hex_window)
        # Stash the catalog_path so load_ring can restore it.
        master_dict["catalog_path"] = hex_window._catalog_path  # None or str
        # Tag the file so load_ring knows to spawn a standalone, not a master.
        master_dict["role"] = "standalone"
        members_list: list[dict] = []
        _log(
            f"save_ring: standalone hex {hex_window._id[:8]} â†’ "
            f"single-hex ring at {path}"
        )
    else:
        # Master case (original behaviour).
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()

        master_dict = _hex_to_dict(hex_window)
        members_list = []
        for member_id, preferred_qpoint in hex_window._members.items():
            member_win = registry.get(member_id)
            if member_win is None:
                _log(f"save_ring: member {member_id[:8]} not in registry â€” skipping")
                continue

            m_dict = _hex_to_dict(member_win)

            # preferred_position from master._members (QPoint).
            m_dict["preferred_position"] = {
                "x": preferred_qpoint.x(),
                "y": preferred_qpoint.y(),
            }

            # catalog_path: store as-is (absolute or relative preserved).
            m_dict["catalog_path"] = member_win._catalog_path  # None or str

            # is_positioned: whether member is in the contiguous cluster.
            m_dict["is_positioned"] = member_id in hex_window._positioned

            members_list.append(m_dict)

    payload = {
        "format": _FORMAT,
        "version": _VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "saved_by_brand": brand_name,
        "master": master_dict,
        "members": members_list,
    }

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _log(f"save_ring: wrote {path} ({len(members_list)} member(s))")


# ---------------------------------------------------------------------------
# Public API: load_ring
# ---------------------------------------------------------------------------

def load_ring(
    path: Path,
    branding: dict,
    registry: "CellRegistry",
    snap_engine: "SnapEngine | None",
) -> "CellWindow":
    """Deserialise a .scriptreering file and spawn master + members.

    Returns the newly-created master CellWindow.

    Raises FileNotFoundError if `path` does not exist.
    Raises ValueError on schema errors (wrong format/version).
    """
    from scriptree.shell.cell_window import CellWindow
    from PySide6.QtCore import QPoint

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"load_ring: file not found: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))

    # Format / version checks.
    fmt = raw.get("format")
    if fmt != _FORMAT:
        raise ValueError(
            f"load_ring: unexpected format {fmt!r} (expected {_FORMAT!r})"
        )
    ver = raw.get("version", 1)
    if ver != _VERSION:
        _log(
            f"load_ring: file version {ver} differs from reader version {_VERSION}; "
            "attempting load anyway."
        )

    # ---- Parse master -------------------------------------------------------
    master_raw = raw.get("master") or {}
    mf = _load_hex_fields(master_raw)

    # Determine whether this is a single-hex (standalone) ring.
    # save_ring() sets master_raw["role"] = "standalone" for standalone saves.
    saved_role = master_raw.get("role", "master")
    is_standalone_ring = (saved_role == "standalone")

    if is_standalone_ring:
        # Single-hex ring: spawn one standalone hex and return it.
        # The "master" section in the file IS the standalone hex.
        cat_path_raw: str | None = master_raw.get("catalog_path")
        resolved_catalog = _resolve_catalog_path(cat_path_raw, branding)

        master_win = CellWindow(
            branding,
            role="standalone",
            catalog_path=resolved_catalog,
        )
        master_win.apply_shape_change(mf["shape"], mf["orientation"])
        master_win.apply_size_change(mf["size_px"])
        master_win.apply_transparency_change(mf["transparency"])
        master_win.apply_always_on_top_change(mf["always_on_top"])
        master_win.move(mf["pos_x"], mf["pos_y"])
        master_win.show()
        _log(
            f"load_ring: standalone hex {master_win._id[:8]} spawned at "
            f"({mf['pos_x']}, {mf['pos_y']}) catalog={resolved_catalog!r}"
        )
        return master_win

    # Spawn master hex (normal multi-hex ring case).
    master_win = CellWindow(
        branding,
        role="master",
    )
    master_win.apply_shape_change(mf["shape"], mf["orientation"])
    master_win.apply_size_change(mf["size_px"])
    master_win.apply_transparency_change(mf["transparency"])
    master_win.apply_always_on_top_change(mf["always_on_top"])
    master_win.move(mf["pos_x"], mf["pos_y"])
    master_win.show()
    _log(
        f"load_ring: master {master_win._id[:8]} spawned at "
        f"({mf['pos_x']}, {mf['pos_y']})"
    )

    # Wire master to snap engine.
    if snap_engine is not None:
        try:
            from scriptree.shell.ring_main import _on_snap_preview
            snap_engine.snapPreview.connect(
                lambda src, tgt, mode, geom, h=master_win: _on_snap_preview(
                    src, tgt, mode, geom, h
                )
            )
        except Exception as exc:
            _log(f"load_ring: snap-engine wire for master failed: {exc!r}")

    # ---- Parse members ------------------------------------------------------
    members_raw: list[dict] = raw.get("members") or []
    for i, m_raw in enumerate(members_raw):
        mf_m = _load_hex_fields(m_raw)

        # Resolve catalog path.
        cat_path_raw: str | None = m_raw.get("catalog_path")
        resolved_catalog: str | None = _resolve_catalog_path(cat_path_raw, branding)

        member_win = CellWindow(
            branding,
            role="standalone",
            catalog_path=resolved_catalog,
        )
        member_win.apply_shape_change(mf_m["shape"], mf_m["orientation"])
        member_win.apply_size_change(mf_m["size_px"])
        member_win.apply_transparency_change(mf_m["transparency"])
        member_win.apply_always_on_top_change(mf_m["always_on_top"])
        member_win.move(mf_m["pos_x"], mf_m["pos_y"])
        member_win.show()

        # preferred_position â€” also clamp.
        pref_raw = m_raw.get("preferred_position") or {}
        try:
            pref_x = int(pref_raw.get("x", mf_m["pos_x"]))
            pref_y = int(pref_raw.get("y", mf_m["pos_y"]))
        except (TypeError, ValueError):
            pref_x, pref_y = mf_m["pos_x"], mf_m["pos_y"]
        pref_cx, pref_cy = _clamp_position(pref_x, pref_y, mf_m["size_px"])
        preferred_qpoint = QPoint(pref_cx, pref_cy)

        # Wire group association on both sides.
        member_win._group_master_id = master_win._id
        master_win._members[member_win._id] = preferred_qpoint

        is_positioned = _coerce_bool(m_raw.get("is_positioned", True))
        if is_positioned:
            master_win._positioned.add(member_win._id)
            member_win._docked_to.add(master_win._id)

        member_win.update()  # refresh green/normal outline

        # Wire member to snap engine.
        if snap_engine is not None:
            try:
                from scriptree.shell.ring_main import _on_snap_preview
                snap_engine.snapPreview.connect(
                    lambda src, tgt, mode, geom, h=member_win: _on_snap_preview(
                        src, tgt, mode, geom, h
                    )
                )
            except Exception as exc:
                _log(f"load_ring: snap-engine wire for member {i} failed: {exc!r}")

        _log(
            f"load_ring: member {member_win._id[:8]} spawned at "
            f"({mf_m['pos_x']}, {mf_m['pos_y']}) "
            f"catalog={resolved_catalog!r} positioned={is_positioned}"
        )

    # Notify registry that a master was spawned.
    if master_win._members:
        first_id = next(iter(master_win._members))
        second_id = list(master_win._members.keys())[1] if len(master_win._members) >= 2 else first_id
        registry.masterSpawned.emit(master_win._id, first_id, second_id)

    # Edge-fold: evaluate immediately after all members are placed.
    # The master's position from the file might already push some members
    # off-screen at the user's current screen size/DPI configuration.
    try:
        master_win._check_edge_fold()
    except Exception as _efe:
        _log(f"load_ring: _check_edge_fold raised {_efe!r} â€” continuing")

    _log(
        f"load_ring: complete â€” master {master_win._id[:8]} "
        f"with {len(master_win._members)} member(s)"
    )
    return master_win


def _resolve_catalog_path(cat_path_raw: str | None, branding: dict) -> str | None:
    """Resolve a saved catalog_path value to an absolute path or None.

    Resolution order:
    1. Absolute path that exists on disk.
    2. Relative path resolved against project root.
    3. Relative path resolved against <APPDATA>/<BRAND>/catalogs/.
    4. Warning + None.
    """
    if not cat_path_raw:
        return None

    p = Path(cat_path_raw)

    if p.is_absolute():
        if p.exists():
            return str(p)
        _log(f"_resolve_catalog_path: absolute path not found: {p}")
        return None

    # Relative â€” try project root first.
    try:
        root = _project_root()
        candidate = (root / p).resolve()
        if candidate.exists():
            return str(candidate)
    except Exception:
        pass

    # Fallback: <APPDATA>/<BRAND>/catalogs/.
    brand_name = branding.get("appName", "ScripTree")
    fallback = _appdata_dir(brand_name) / "catalogs" / p
    if fallback.exists():
        return str(fallback)

    _log(f"_resolve_catalog_path: could not resolve {cat_path_raw!r} â€” treating as None")
    return None


# ---------------------------------------------------------------------------
# Public API: autoload config
# ---------------------------------------------------------------------------

def list_autoload_rings(scope: Literal["user", "system"]) -> list[Path]:
    """Return the list of .scriptreering paths registered for auto-load in scope."""
    # We need the brand name; read it from branding.config.json.
    brand_name = _read_brand_name()
    cfg_path = _autoload_config_path(brand_name, scope)
    if not cfg_path.exists():
        return []
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _log(f"list_autoload_rings: cannot read {cfg_path}: {exc!r}")
        return []

    raw_rings = cfg.get("rings") or []
    result: list[Path] = []
    for entry in raw_rings:
        p = Path(entry)
        if not p.is_absolute():
            p = (cfg_path.parent / p).resolve()
        result.append(p)
    return result


def add_autoload_ring(path: Path, scope: Literal["user", "system"]) -> None:
    """Add path to scope's autoload config and register the Windows autostart entry.

    Idempotent â€” adding the same path twice results in a single entry.
    For 'system' scope, requires admin privileges (raises PermissionError if not).
    """
    path = Path(path).resolve()
    brand_name = _read_brand_name()
    cfg_path = _autoload_config_path(brand_name, scope)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing config.
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    else:
        cfg = {}

    cfg.setdefault("format", "scriptreering-autoload")
    cfg.setdefault("version", 1)
    rings: list[str] = cfg.get("rings") or []

    path_str = str(path)
    if path_str not in rings:
        rings.append(path_str)
        cfg["rings"] = rings
        cfg_path.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        _log(f"add_autoload_ring: added {path_str} to {scope} config")
    else:
        _log(f"add_autoload_ring: {path_str} already in {scope} config â€” skipped")

    # Register autostart entry.
    cmd = _build_autostart_cmd()
    register_autostart(scope, cmd, brand_name)


def remove_autoload_ring(path: Path, scope: Literal["user", "system"]) -> None:
    """Remove path from scope's autoload config.

    If no rings remain in this scope, unregisters the Windows autostart entry.
    """
    path = Path(path).resolve()
    brand_name = _read_brand_name()
    cfg_path = _autoload_config_path(brand_name, scope)

    if not cfg_path.exists():
        _log(f"remove_autoload_ring: config not found â€” nothing to remove")
        return

    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _log(f"remove_autoload_ring: cannot read config: {exc!r}")
        return

    rings: list[str] = cfg.get("rings") or []
    path_str = str(path)
    if path_str in rings:
        rings.remove(path_str)
        cfg["rings"] = rings
        cfg_path.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        _log(f"remove_autoload_ring: removed {path_str} from {scope} config")
    else:
        _log(f"remove_autoload_ring: {path_str} not in {scope} config â€” no-op")

    # If no rings remain, remove the autostart entry.
    if not rings:
        _log(f"remove_autoload_ring: no rings left in {scope} â€” unregistering autostart")
        unregister_autostart(scope, brand_name)


def _read_brand_name() -> str:
    """Read appName from branding.config.json. Falls back to 'ScripTree'."""
    try:
        root = _project_root()
        cfg = json.loads(
            (root / "branding" / "branding.config.json").read_text(encoding="utf-8")
        )
        return cfg.get("appName", "ScripTree")
    except Exception:
        return "ScripTree"


def _build_autostart_cmd() -> str:
    """Build the command-line string for the Windows Run-key value."""
    exe = sys.executable
    # Quote the executable path to handle spaces.
    return f'"{exe}" -m scriptree.shell.ring_main --autoload-rings'


# ---------------------------------------------------------------------------
# Windows registry helpers
# ---------------------------------------------------------------------------

def register_autostart(
    scope: Literal["user", "system"],
    cmd: str,
    brand_name: str | None = None,
) -> None:
    """Add a Run-key entry so the shell launches at Windows login.

    For 'system' scope, requires admin elevation; raises PermissionError if not.
    On non-Windows platforms, logs a warning and returns.
    """
    if sys.platform != "win32":
        _log("register_autostart: non-Windows platform â€” no-op")
        return

    if brand_name is None:
        brand_name = _read_brand_name()

    import winreg  # stdlib â€” Windows only

    if scope == "user":
        hive = winreg.HKEY_CURRENT_USER
        subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
    else:
        hive = winreg.HKEY_LOCAL_MACHINE
        subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
        # Verify we have admin rights before attempting HKLM write.
        if not _is_admin():
            raise PermissionError(
                "register_autostart(scope='system') requires administrator privileges."
            )

    try:
        with winreg.CreateKeyEx(hive, subkey, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, brand_name, 0, winreg.REG_SZ, cmd)
        _log(
            f"register_autostart: set HKLM\\...\\Run[{brand_name!r}] = {cmd!r} "
            f"(scope={scope})"
        )
    except PermissionError:
        raise
    except Exception as exc:
        _log(f"register_autostart: winreg error: {exc!r}")
        raise


def unregister_autostart(
    scope: Literal["user", "system"],
    brand_name: str | None = None,
) -> None:
    """Remove the Run-key entry for this application.

    Silently succeeds if the key does not exist.
    On non-Windows platforms, logs a warning and returns.
    """
    if sys.platform != "win32":
        _log("unregister_autostart: non-Windows platform â€” no-op")
        return

    if brand_name is None:
        brand_name = _read_brand_name()

    import winreg

    if scope == "user":
        hive = winreg.HKEY_CURRENT_USER
    else:
        hive = winreg.HKEY_LOCAL_MACHINE
        if not _is_admin():
            raise PermissionError(
                "unregister_autostart(scope='system') requires administrator privileges."
            )

    subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(hive, subkey, 0, winreg.KEY_SET_VALUE) as k:
            try:
                winreg.DeleteValue(k, brand_name)
                _log(f"unregister_autostart: deleted Run[{brand_name!r}] scope={scope}")
            except FileNotFoundError:
                _log(f"unregister_autostart: Run[{brand_name!r}] not found â€” no-op")
    except FileNotFoundError:
        _log(f"unregister_autostart: subkey not found â€” no-op")
    except Exception as exc:
        _log(f"unregister_autostart: winreg error: {exc!r}")
        raise


def _is_admin() -> bool:
    """Return True if the current process has administrator privileges (Windows)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate_for_system_autostart(ring_path: Path) -> None:
    """Re-launch with 'runas' verb to register system-scope autostart.

    Called from the context menu when scope='system' and not admin.
    The elevated process runs:
        <exe> -m apps.shell.main --register-autostart-system <ring-path>
    and exits immediately.

    On non-Windows or if ShellExecuteW fails, logs an error.
    """
    if sys.platform != "win32":
        _log("elevate_for_system_autostart: non-Windows â€” cannot elevate")
        return

    import ctypes

    exe = sys.executable
    args = f'-m apps.shell.main --register-autostart-system "{ring_path}"'
    _log(f"elevate_for_system_autostart: launching elevated: {exe} {args}")

    ret = ctypes.windll.shell32.ShellExecuteW(
        0,          # hwnd
        "runas",    # verb â€” triggers UAC prompt
        exe,
        args,
        None,       # working directory (inherit)
        1,          # SW_SHOWNORMAL
    )
    # ShellExecuteW returns > 32 on success.
    if ret <= 32:
        _log(f"elevate_for_system_autostart: ShellExecuteW returned {ret} (error)")
    else:
        _log(f"elevate_for_system_autostart: elevation launched (ret={ret})")

