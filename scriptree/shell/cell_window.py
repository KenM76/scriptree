"""
cell_window.py â€” CellWindow, the branded floating hexagonal launcher.

Architecture: see docs/architecture/ADR-001-overlay-and-docking.md
Platform target: Win11 (Phase 0/1 demo). Mac/Linux behaviour: see ADR-001 Â§cross-platform.

Coordinate convention
---------------------
All sizes and positions passed to setMask / resize / move are in *logical* pixels
(device-independent units).  Qt scales them to physical pixels via devicePixelRatio
internally.  We do NOT multiply by devicePixelRatio ourselves â€” that double-scales.
"""

from __future__ import annotations

import math
import sys
import time as _time_module
import uuid
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    Qt,
    QSettings,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QPolygon,
    QRadialGradient,
    QRegion,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Logging helper (stderr only â€” no print spam on stdout)
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(f"[CellWindow] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# ShapeGeometry â€” returned by compute_polygon(), consumed by SnapEngine
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ShapeGeometry:
    """Full geometric description of a hexagon/square at a given size.

    polygon       â€” QPolygon of integer logical-pixel vertices (for setMask and drawPolygon).
    vertices      â€” same vertices as QPointF list (for snap math, float precision).
    edge_midpointsâ€” one QPointF per edge, widget-local coords.
    edge_normals  â€” outward unit normal QPointF per edge (direction only, no magnitude).
    """
    polygon: QPolygon
    vertices: list[QPointF]
    edge_midpoints: list[QPointF]
    edge_normals: list[QPointF]


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _regular_polygon_geometry(n: int, start_deg: float, size_px: int) -> ShapeGeometry:
    """Compute a regular n-gon inscribed in a size_px x size_px square.

    start_deg â€” angle of the first vertex in degrees (counter-clockwise from +X).
    Vertices are ordered clockwise in Qt screen space (y increases downward).
    """
    cx = cy = size_px / 2.0
    r = size_px / 2.0

    # Vertices
    float_pts: list[QPointF] = []
    int_pts: list[QPoint] = []
    for i in range(n):
        theta = math.radians(start_deg + 360.0 / n * i)
        fx = cx + r * math.cos(theta)
        fy = cy + r * math.sin(theta)
        float_pts.append(QPointF(fx, fy))
        int_pts.append(QPoint(round(fx), round(fy)))

    polygon = QPolygon(int_pts)

    # Edge midpoints and outward normals.
    midpoints: list[QPointF] = []
    normals: list[QPointF] = []
    for i in range(n):
        a = float_pts[i]
        b = float_pts[(i + 1) % n]
        mid = QPointF((a.x() + b.x()) / 2.0, (a.y() + b.y()) / 2.0)
        midpoints.append(mid)

        # Edge direction vector (a â†’ b).
        ex = b.x() - a.x()
        ey = b.y() - a.y()
        length = math.hypot(ex, ey)
        if length < 1e-9:
            normals.append(QPointF(0.0, 0.0))
            continue

        # Outward normal: rotate edge direction 90Â° clockwise (in Qt screen coords,
        # y increases downward, so clockwise rotation is (ey, -ex)).
        # However, for a convex polygon with vertices ordered clockwise in screen space,
        # the OUTWARD normal points away from the centre. We verify by checking
        # that the normal points away from centre.
        nx_candidate = ey / length
        ny_candidate = -ex / length
        # Check: dot(candidate, mid - centre) should be > 0 for outward.
        dx = mid.x() - cx
        dy = mid.y() - cy
        if nx_candidate * dx + ny_candidate * dy < 0:
            nx_candidate = -nx_candidate
            ny_candidate = -ny_candidate
        normals.append(QPointF(nx_candidate, ny_candidate))

    return ShapeGeometry(
        polygon=polygon,
        vertices=float_pts,
        edge_midpoints=midpoints,
        edge_normals=normals,
    )


def compute_polygon(shape: str, size_px: int, orientation: str) -> ShapeGeometry:
    """Dispatch to the right ShapeGeometry builder.

    Returns a ShapeGeometry with polygon, vertices, edge_midpoints, edge_normals.
    shape: 'hexagon' | 'square'
    orientation: 'flat-top' | 'pointy-top' (ignored for square)
    size_px: widget logical size in pixels
    """
    s = (shape or "hexagon").lower()
    if s == "hexagon":
        # flat-top: first vertex at 0Â° (right), giving horizontal top/bottom edges.
        # pointy-top: first vertex at -90Â° (top), giving vertical top/bottom vertices.
        start_deg = 0.0 if orientation == "flat-top" else -90.0
        return _regular_polygon_geometry(n=6, start_deg=start_deg, size_px=size_px)
    if s == "square":
        # Square at 45Â° rotation so vertices are at corners, edges face N/E/S/W.
        return _regular_polygon_geometry(n=4, start_deg=45.0, size_px=size_px)
    _log(f"Unknown shape {shape!r}; falling back to hexagon/flat-top.")
    return _regular_polygon_geometry(n=6, start_deg=0.0, size_px=size_px)


def _lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
    """Linear interpolate between two QColors.  t=0 â†’ c1, t=1 â†’ c2."""
    r = round(c1.red()   + t * (c2.red()   - c1.red()))
    g = round(c1.green() + t * (c2.green() - c1.green()))
    b = round(c1.blue()  + t * (c2.blue()  - c1.blue()))
    a = round(c1.alpha() + t * (c2.alpha() - c1.alpha()))
    return QColor(r, g, b, a)


def _parse_rgba_hex(hex8: str) -> QColor:
    """Parse an 8-char RRGGBBAA hex string (no leading #) into a QColor."""
    if len(hex8) != 8:
        _log(f"Warning: expected 8-char RGBA hex, got {hex8!r}; using opaque white.")
        return QColor(255, 255, 255, 255)
    r = int(hex8[0:2], 16)
    g = int(hex8[2:4], 16)
    b = int(hex8[4:6], 16)
    a = int(hex8[6:8], 16)
    return QColor(r, g, b, a)


def _coerce_bool(value) -> bool:
    """Normalise a QSettings value that might be str 'true'/'false' or actual bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return bool(value)


def _coerce_int(value, default: int, lo: int, hi: int) -> int:
    """Normalise a QSettings integer value that might arrive as a string."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _coerce_str(value, allowed: list[str], default: str) -> str:
    """Normalise a QSettings string value; fall back to default if not in allowed."""
    if isinstance(value, str) and value in allowed:
        return value
    return default


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    """Modeless settings popover launched from the hexagon right-click menu.

    All user-visible strings (title, labels) are brand-agnostic except for the
    window title which reads from the branding dict passed at construction.

    Controls:
        1. Shape        QComboBox â€” Hexagon | Square
        2. Orientation  QComboBox â€” Flat-top | Pointy-top (disabled for Square)
        3. Size         QSlider   â€” 32â€“96 px, step 4, live preview
        4. Transparency QSlider   â€” 30â€“100 (maps to 0.30â€“1.00 alpha), live preview
        5. Always on top QCheckBox
        6. Rotate 90Â°  QPushButton â€” cycles orientation (no-op for Square)

    Footer:
        - Reset to defaults
        - Close

    Settings are saved on every change (not on close).
    """

    # Map display names â†” internal keys
    _SHAPE_DISPLAY = {"Hexagon": "hexagon", "Square": "square"}
    _SHAPE_INTERNAL = {v: k for k, v in _SHAPE_DISPLAY.items()}
    _ORIENT_DISPLAY = {"Flat-top": "flat-top", "Pointy-top": "pointy-top"}
    _ORIENT_INTERNAL = {v: k for k, v in _ORIENT_DISPLAY.items()}

    def __init__(self, hexagon: "CellWindow") -> None:
        # Pass None as parent so the dialog inherits OS chrome (Win11 palette)
        # rather than the CellWindow's translucent/dark palette.  The hex
        # reference is kept in self._hex for data access; Qt.Tool keeps the
        # dialog out of the taskbar and always-on-top relative to the hex.
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint)

        self._hex = hexagon
        brand = hexagon._branding.get("appName", "App")
        self.setWindowTitle(f"{brand} â€” Settings")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(300)

        # Prevent the dialog from blocking the hexagon (modeless).
        self.setModal(False)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # ---- 1. Shape -------------------------------------------------------
        shape_row = QHBoxLayout()
        shape_row.addWidget(QLabel("Shape:"))
        self._shape_combo = QComboBox()
        self._shape_combo.addItems(list(self._SHAPE_DISPLAY.keys()))
        current_shape_display = self._SHAPE_INTERNAL.get(hexagon._shape, "Hexagon")
        self._shape_combo.setCurrentText(current_shape_display)
        shape_row.addWidget(self._shape_combo)
        layout.addLayout(shape_row)

        # ---- 2. Orientation -------------------------------------------------
        orient_row = QHBoxLayout()
        orient_row.addWidget(QLabel("Orientation:"))
        self._orient_combo = QComboBox()
        self._orient_combo.addItems(list(self._ORIENT_DISPLAY.keys()))
        current_orient_display = self._ORIENT_INTERNAL.get(hexagon._orientation, "Flat-top")
        self._orient_combo.setCurrentText(current_orient_display)
        self._orient_combo.setToolTip("Orientation only applies to hexagonal shapes")
        orient_row.addWidget(self._orient_combo)
        layout.addLayout(orient_row)

        # ---- 3. Size --------------------------------------------------------
        size_row = QVBoxLayout()
        self._size_label = QLabel(f"Size: {hexagon._size_px} px")
        self._size_slider = QSlider(Qt.Horizontal)
        self._size_slider.setMinimum(32)
        self._size_slider.setMaximum(96)
        self._size_slider.setSingleStep(4)
        self._size_slider.setPageStep(4)
        self._size_slider.setValue(hexagon._size_px)
        size_row.addWidget(self._size_label)
        size_row.addWidget(self._size_slider)
        layout.addLayout(size_row)

        # ---- 4. Transparency ------------------------------------------------
        transp_row = QVBoxLayout()
        # Store transparency as int 30â€“100; maps to 0.30â€“1.00 alpha multiplier.
        transp_int = round(hexagon._transparency * 100)
        self._transp_label = QLabel(f"Transparency: {transp_int}%")
        self._transp_slider = QSlider(Qt.Horizontal)
        self._transp_slider.setMinimum(30)
        self._transp_slider.setMaximum(100)
        self._transp_slider.setSingleStep(5)
        self._transp_slider.setPageStep(10)
        self._transp_slider.setValue(transp_int)
        transp_row.addWidget(self._transp_label)
        transp_row.addWidget(self._transp_slider)
        layout.addLayout(transp_row)

        # ---- 5. Always on top -----------------------------------------------
        self._always_on_top_cb = QCheckBox("Always on top")
        self._always_on_top_cb.setChecked(hexagon._always_on_top)
        layout.addWidget(self._always_on_top_cb)

        # ---- 6. Rotate 90Â° --------------------------------------------------
        self._rotate_btn = QPushButton("Rotate 90Â°")
        self._rotate_btn.setToolTip(
            "Cycle between Flat-top and Pointy-top orientations (no-op for Square)"
        )
        layout.addWidget(self._rotate_btn)

        # ---- Separator ------------------------------------------------------
        layout.addSpacing(4)

        # ---- Footer ---------------------------------------------------------
        footer = QHBoxLayout()
        self._reset_btn = QPushButton("Reset to defaults")
        footer.addWidget(self._reset_btn)
        footer.addStretch()
        self._close_btn = QPushButton("Close")
        footer.addWidget(self._close_btn)
        layout.addLayout(footer)

        # ---- Initial orientation enabled state ------------------------------
        self._update_orient_enabled()

        # ---- Connections ----------------------------------------------------
        self._shape_combo.currentTextChanged.connect(self._on_shape_changed)
        self._orient_combo.currentTextChanged.connect(self._on_orient_changed)
        self._size_slider.valueChanged.connect(self._on_size_changed)
        self._transp_slider.valueChanged.connect(self._on_transp_changed)
        self._always_on_top_cb.toggled.connect(self._on_always_on_top_changed)
        self._rotate_btn.clicked.connect(self._on_rotate)
        self._reset_btn.clicked.connect(self._on_reset)
        self._close_btn.clicked.connect(self.close)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_orient_enabled(self) -> None:
        shape_key = self._SHAPE_DISPLAY.get(self._shape_combo.currentText(), "hexagon")
        self._orient_combo.setEnabled(shape_key == "hexagon")

    # ------------------------------------------------------------------
    # Slot handlers
    # ------------------------------------------------------------------

    def _on_shape_changed(self, display_text: str) -> None:
        shape_key = self._SHAPE_DISPLAY.get(display_text, "hexagon")
        self._update_orient_enabled()
        orient_key = self._ORIENT_DISPLAY.get(self._orient_combo.currentText(), "flat-top")
        self._hex.apply_shape_change(shape_key, orient_key)
        self._hex._save_settings()

    def _on_orient_changed(self, display_text: str) -> None:
        orient_key = self._ORIENT_DISPLAY.get(display_text, "flat-top")
        shape_key = self._SHAPE_DISPLAY.get(self._shape_combo.currentText(), "hexagon")
        self._hex.apply_shape_change(shape_key, orient_key)
        self._hex._save_settings()

    def _on_size_changed(self, value: int) -> None:
        # Snap to nearest multiple of 4.
        snapped = round(value / 4) * 4
        snapped = max(32, min(96, snapped))
        self._size_label.setText(f"Size: {snapped} px")
        self._hex.apply_size_change(snapped)
        self._hex._save_settings()

    def _on_transp_changed(self, value: int) -> None:
        self._transp_label.setText(f"Transparency: {value}%")
        self._hex.apply_transparency_change(value / 100.0)
        self._hex._save_settings()

    def _on_always_on_top_changed(self, checked: bool) -> None:
        self._hex.apply_always_on_top_change(checked)
        self._hex._save_settings()

    def _on_rotate(self) -> None:
        shape_key = self._SHAPE_DISPLAY.get(self._shape_combo.currentText(), "hexagon")
        if shape_key != "hexagon":
            return  # no-op for Square
        current_orient = self._ORIENT_DISPLAY.get(self._orient_combo.currentText(), "flat-top")
        new_orient = "pointy-top" if current_orient == "flat-top" else "flat-top"
        new_display = self._ORIENT_INTERNAL.get(new_orient, "Flat-top")
        # Block the signal to avoid double-apply; we apply once after setting.
        self._orient_combo.blockSignals(True)
        self._orient_combo.setCurrentText(new_display)
        self._orient_combo.blockSignals(False)
        self._hex.apply_shape_change(shape_key, new_orient)
        self._hex._save_settings()

    def _on_reset(self) -> None:
        """Re-read branding defaults and push them to the hexagon + UI."""
        hex_cfg = self._hex._branding.get("hexagon", {})
        default_shape = hex_cfg.get("shape", "hexagon")
        default_orient = hex_cfg.get("orientation", "flat-top")
        default_size = hex_cfg.get("defaultSizePx", 56)
        default_transp = hex_cfg.get("defaultTransparency", 0.85)
        default_aot = hex_cfg.get("defaultAlwaysOnTop", True)

        # Block signals while we batch-update UI to avoid cascading applies.
        self._shape_combo.blockSignals(True)
        self._orient_combo.blockSignals(True)
        self._size_slider.blockSignals(True)
        self._transp_slider.blockSignals(True)
        self._always_on_top_cb.blockSignals(True)

        self._shape_combo.setCurrentText(self._SHAPE_INTERNAL.get(default_shape, "Hexagon"))
        self._orient_combo.setCurrentText(self._ORIENT_INTERNAL.get(default_orient, "Flat-top"))
        self._size_slider.setValue(default_size)
        transp_int = round(default_transp * 100)
        self._transp_slider.setValue(transp_int)
        self._always_on_top_cb.setChecked(default_aot)

        self._shape_combo.blockSignals(False)
        self._orient_combo.blockSignals(False)
        self._size_slider.blockSignals(False)
        self._transp_slider.blockSignals(False)
        self._always_on_top_cb.blockSignals(False)

        # Update labels.
        self._size_label.setText(f"Size: {default_size} px")
        self._transp_label.setText(f"Transparency: {transp_int}%")

        # Apply all at once.
        self._update_orient_enabled()
        self._hex.apply_shape_change(default_shape, default_orient)
        self._hex.apply_size_change(default_size)
        self._hex.apply_transparency_change(default_transp)
        self._hex.apply_always_on_top_change(default_aot)
        self._hex._save_settings()


# ---------------------------------------------------------------------------
# PreferencesDialog â€” app-wide defaults (not per-hex)
# ---------------------------------------------------------------------------

class PreferencesDialog(QDialog):
    """Modal app-wide preferences dialog.

    Opened from any hex's right-click â†’ "Preferencesâ€¦".

    Sections
    --------
    1. Defaults for new hexagons
       shape, orientation, size_px, transparency, always_on_top
    2. Snap behaviour
       snap_distance_px
    3. Tool execution
       default_catalog_dir, tool_history_limit
    4. Startup
       autoload_rings_enabled, list of auto-loaded rings with X buttons

    All values are stored under the QSettings prefix "app/".  Branding defaults
    from branding.config.json["hexagon"] are used as the Reset fallback.

    New hexagons spawned after a change pick up the new app/* defaults because
    CellWindow._load_settings() checks app/* when no per-hex key exists.
    Existing hexes keep their individual per-hex settings.
    """

    _SHAPE_DISPLAY   = {"Hexagon": "hexagon", "Square": "square"}
    _SHAPE_INTERNAL  = {v: k for k, v in _SHAPE_DISPLAY.items()}
    _ORIENT_DISPLAY  = {"Flat-top": "flat-top", "Pointy-top": "pointy-top"}
    _ORIENT_INTERNAL = {v: k for k, v in _ORIENT_DISPLAY.items()}

    def __init__(self, branding: dict, parent: QWidget | None = None) -> None:
        # Always pass None so the dialog inherits the OS system palette
        # rather than any translucent/dark palette set on a CellWindow parent.
        super().__init__(None, Qt.Dialog)
        self._branding = branding
        brand = branding.get("appName", "App")
        self.setWindowTitle(f"{brand} Preferences")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setSizeGripEnabled(True)

        # Read current app/* settings (fall back to branding).
        s = QSettings()
        hex_cfg = branding.get("hexagon", {})

        def _gs(key: str, default):
            v = s.value(f"app/{key}")
            return v if v is not None else default

        cur_shape       = _gs("default_shape",        hex_cfg.get("shape", "hexagon"))
        cur_orient      = _gs("default_orientation",  hex_cfg.get("orientation", "flat-top"))
        cur_size        = _coerce_int(_gs("default_size_px", hex_cfg.get("defaultSizePx", 56)), 56, 32, 96)
        cur_transp      = _coerce_int(
                              round(float(_gs("default_transparency", hex_cfg.get("defaultTransparency", 0.85))) * 100),
                              85, 30, 100)
        cur_aot         = _coerce_bool(_gs("default_always_on_top", hex_cfg.get("defaultAlwaysOnTop", True)))
        cur_snap        = _coerce_int(_gs("snap_distance_px", hex_cfg.get("snapDistancePx", 18)), 18, 4, 80)
        cur_catalog_dir = _gs("default_catalog_dir", "") or ""
        cur_hist_limit  = _coerce_int(_gs("tool_history_limit", 1000), 1000, 10, 50000)
        cur_autoload_en = _coerce_bool(_gs("autoload_rings_enabled", True))

        # ---- Main layout -------------------------------------------------------
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        # ---- 1. Defaults for new hexagons ----------------------------------------
        grp_hex = QGroupBox("Defaults for new cells")
        grp_hex_layout = QVBoxLayout(grp_hex)
        grp_hex_layout.setSpacing(6)

        # Shape
        shape_row = QHBoxLayout()
        shape_row.addWidget(QLabel("Shape:"))
        self._shape_combo = QComboBox()
        self._shape_combo.addItems(list(self._SHAPE_DISPLAY.keys()))
        self._shape_combo.setCurrentText(self._SHAPE_INTERNAL.get(cur_shape, "Hexagon"))
        shape_row.addWidget(self._shape_combo)
        grp_hex_layout.addLayout(shape_row)

        # Orientation
        orient_row = QHBoxLayout()
        orient_row.addWidget(QLabel("Orientation:"))
        self._orient_combo = QComboBox()
        self._orient_combo.addItems(list(self._ORIENT_DISPLAY.keys()))
        self._orient_combo.setCurrentText(self._ORIENT_INTERNAL.get(cur_orient, "Flat-top"))
        orient_row.addWidget(self._orient_combo)
        grp_hex_layout.addLayout(orient_row)

        # Size
        size_row_v = QVBoxLayout()
        self._size_label = QLabel(f"Size (px): {cur_size}")
        self._size_slider = QSlider(Qt.Horizontal)
        self._size_slider.setMinimum(32)
        self._size_slider.setMaximum(96)
        self._size_slider.setSingleStep(4)
        self._size_slider.setPageStep(4)
        self._size_slider.setValue(cur_size)
        size_row_v.addWidget(self._size_label)
        size_row_v.addWidget(self._size_slider)
        grp_hex_layout.addLayout(size_row_v)

        # Transparency
        transp_row_v = QVBoxLayout()
        self._transp_label = QLabel(f"Transparency: {cur_transp}%")
        self._transp_slider = QSlider(Qt.Horizontal)
        self._transp_slider.setMinimum(30)
        self._transp_slider.setMaximum(100)
        self._transp_slider.setSingleStep(5)
        self._transp_slider.setPageStep(10)
        self._transp_slider.setValue(cur_transp)
        transp_row_v.addWidget(self._transp_label)
        transp_row_v.addWidget(self._transp_slider)
        grp_hex_layout.addLayout(transp_row_v)

        # Always on top
        self._aot_cb = QCheckBox("Always on top")
        self._aot_cb.setChecked(cur_aot)
        grp_hex_layout.addWidget(self._aot_cb)

        outer.addWidget(grp_hex)

        # ---- 2. Snap behaviour --------------------------------------------------
        grp_snap = QGroupBox("Snap behavior")
        grp_snap_layout = QVBoxLayout(grp_snap)
        grp_snap_layout.setSpacing(6)

        snap_row_v = QVBoxLayout()
        self._snap_label = QLabel(f"Snap distance (px): {cur_snap}")
        self._snap_slider = QSlider(Qt.Horizontal)
        self._snap_slider.setMinimum(4)
        self._snap_slider.setMaximum(80)
        self._snap_slider.setSingleStep(1)
        self._snap_slider.setPageStep(4)
        self._snap_slider.setValue(cur_snap)
        snap_row_v.addWidget(self._snap_label)
        snap_row_v.addWidget(self._snap_slider)
        grp_snap_layout.addLayout(snap_row_v)
        outer.addWidget(grp_snap)

        # ---- 3. Tool execution --------------------------------------------------
        grp_exec = QGroupBox("Tool execution")
        grp_exec_layout = QVBoxLayout(grp_exec)
        grp_exec_layout.setSpacing(6)

        catalog_row = QHBoxLayout()
        catalog_row.addWidget(QLabel("Default catalog dir:"))
        self._catalog_dir_edit = QLabel(cur_catalog_dir or "(not set)")
        self._catalog_dir_edit.setWordWrap(True)
        self._catalog_dir_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._catalog_dir_value: str = cur_catalog_dir
        catalog_row.addWidget(self._catalog_dir_edit, stretch=1)
        browse_btn = QPushButton("Browseâ€¦")
        browse_btn.setFixedWidth(72)
        browse_btn.clicked.connect(self._on_browse_catalog_dir)
        catalog_row.addWidget(browse_btn)
        grp_exec_layout.addLayout(catalog_row)

        hist_row = QHBoxLayout()
        hist_row.addWidget(QLabel("Tool history limit:"))
        self._hist_spin = QSpinBox()
        self._hist_spin.setMinimum(10)
        self._hist_spin.setMaximum(50000)
        self._hist_spin.setSingleStep(100)
        self._hist_spin.setValue(cur_hist_limit)
        hist_row.addWidget(self._hist_spin)
        hist_row.addStretch()
        grp_exec_layout.addLayout(hist_row)
        outer.addWidget(grp_exec)

        # ---- 4. Startup ---------------------------------------------------------
        grp_startup = QGroupBox("Startup")
        grp_startup_layout = QVBoxLayout(grp_startup)
        grp_startup_layout.setSpacing(6)

        self._autoload_en_cb = QCheckBox("Auto-load configured rings")
        self._autoload_en_cb.setChecked(cur_autoload_en)
        grp_startup_layout.addWidget(self._autoload_en_cb)

        grp_startup_layout.addWidget(QLabel("Auto-loaded rings:"))
        self._rings_list = QListWidget()
        self._rings_list.setFixedHeight(90)
        grp_startup_layout.addWidget(self._rings_list)
        self._populate_rings_list()
        outer.addWidget(grp_startup)

        # ---- Footer -------------------------------------------------------------
        footer = QHBoxLayout()
        reset_btn = QPushButton("Reset to defaults")
        reset_btn.clicked.connect(self._on_reset)
        footer.addWidget(reset_btn)
        footer.addStretch()
        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        footer.addWidget(save_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        footer.addWidget(close_btn)
        outer.addLayout(footer)

        # ---- Live label updates -------------------------------------------------
        self._size_slider.valueChanged.connect(
            lambda v: self._size_label.setText(f"Size (px): {round(v / 4) * 4}")
        )
        self._transp_slider.valueChanged.connect(
            lambda v: self._transp_label.setText(f"Transparency: {v}%")
        )
        self._snap_slider.valueChanged.connect(
            lambda v: self._snap_label.setText(f"Snap distance (px): {v}")
        )
        self._shape_combo.currentTextChanged.connect(self._update_orient_enabled)
        self._update_orient_enabled()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_orient_enabled(self) -> None:
        shape_key = self._SHAPE_DISPLAY.get(self._shape_combo.currentText(), "hexagon")
        self._orient_combo.setEnabled(shape_key == "hexagon")

    def _populate_rings_list(self) -> None:
        """Fill self._rings_list from autoload config (user + system)."""
        self._rings_list.clear()
        try:
            from scriptree.shell.ring_io import list_autoload_rings, remove_autoload_ring
            for scope in ("user", "system"):
                for path in list_autoload_rings(scope):
                    item = QListWidgetItem(str(path))
                    item.setData(Qt.UserRole, (scope, path))
                    self._rings_list.addItem(item)
                    # Add an X button via a small widget trick.
                    row_widget = QWidget()
                    row_layout = QHBoxLayout(row_widget)
                    row_layout.setContentsMargins(0, 0, 0, 0)
                    lbl = QLabel(f"[{scope}]  {path.name}")
                    lbl.setWordWrap(False)
                    row_layout.addWidget(lbl, stretch=1)
                    x_btn = QPushButton("X")
                    x_btn.setFixedSize(22, 22)
                    _scope = scope
                    _path = path
                    x_btn.clicked.connect(
                        lambda checked=False, s=_scope, p=_path: self._on_remove_ring(s, p)
                    )
                    row_layout.addWidget(x_btn)
                    self._rings_list.setItemWidget(item, row_widget)
                    self._rings_list.setRowHeight(self._rings_list.row(item), 26)
        except Exception as exc:
            _log(f"PreferencesDialog._populate_rings_list: {exc!r}")

    def _on_remove_ring(self, scope: str, path) -> None:
        """Remove a ring from autoload config and refresh the list."""
        try:
            from scriptree.shell.ring_io import remove_autoload_ring
            from typing import Literal as _Lit
            remove_autoload_ring(path, scope)  # type: ignore[arg-type]
        except Exception as exc:
            _log(f"PreferencesDialog._on_remove_ring: {exc!r}")
        self._populate_rings_list()

    def _on_browse_catalog_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Select default catalog directory")
        if chosen:
            self._catalog_dir_value = chosen
            self._catalog_dir_edit.setText(chosen)

    # ------------------------------------------------------------------
    # Save / Reset
    # ------------------------------------------------------------------

    def _on_save(self) -> None:
        """Write all controls to QSettings under the app/ prefix."""
        s = QSettings()

        shape_key  = self._SHAPE_DISPLAY.get(self._shape_combo.currentText(), "hexagon")
        orient_key = self._ORIENT_DISPLAY.get(self._orient_combo.currentText(), "flat-top")
        size_px    = round(self._size_slider.value() / 4) * 4
        transp     = self._transp_slider.value() / 100.0
        aot        = self._aot_cb.isChecked()
        snap_px    = self._snap_slider.value()
        hist_limit = self._hist_spin.value()
        autoload   = self._autoload_en_cb.isChecked()

        s.setValue("app/default_shape",        shape_key)
        s.setValue("app/default_orientation",  orient_key)
        s.setValue("app/default_size_px",      size_px)
        s.setValue("app/default_transparency", transp)
        s.setValue("app/default_always_on_top", aot)
        s.setValue("app/snap_distance_px",     snap_px)
        s.setValue("app/default_catalog_dir",  self._catalog_dir_value)
        s.setValue("app/tool_history_limit",   hist_limit)
        s.setValue("app/autoload_rings_enabled", autoload)
        s.sync()

        _log(
            f"PreferencesDialog: saved app/* â€” shape={shape_key} orient={orient_key} "
            f"size={size_px} transp={transp:.2f} aot={aot} snap={snap_px} "
            f"hist_limit={hist_limit} autoload={autoload}"
        )
        self.accept()

    def _on_reset(self) -> None:
        """Clear all app/* QSettings keys and reset UI to branding defaults."""
        s = QSettings()
        app_keys = [k for k in s.allKeys() if k.startswith("app/")]
        for k in app_keys:
            s.remove(k)
        s.sync()

        hex_cfg = self._branding.get("hexagon", {})
        default_shape  = hex_cfg.get("shape", "hexagon")
        default_orient = hex_cfg.get("orientation", "flat-top")
        default_size   = hex_cfg.get("defaultSizePx", 56)
        default_transp = hex_cfg.get("defaultTransparency", 0.85)
        default_aot    = hex_cfg.get("defaultAlwaysOnTop", True)
        default_snap   = hex_cfg.get("snapDistancePx", 18)

        # Block signals to suppress live-label cascades.
        for w in (self._shape_combo, self._orient_combo,
                  self._size_slider, self._transp_slider,
                  self._snap_slider, self._aot_cb):
            w.blockSignals(True)

        self._shape_combo.setCurrentText(self._SHAPE_INTERNAL.get(default_shape, "Hexagon"))
        self._orient_combo.setCurrentText(self._ORIENT_INTERNAL.get(default_orient, "Flat-top"))
        self._size_slider.setValue(default_size)
        self._transp_slider.setValue(round(default_transp * 100))
        self._snap_slider.setValue(default_snap)
        self._aot_cb.setChecked(default_aot)
        self._hist_spin.setValue(1000)
        self._catalog_dir_value = ""
        self._catalog_dir_edit.setText("(not set)")
        self._autoload_en_cb.setChecked(True)

        for w in (self._shape_combo, self._orient_combo,
                  self._size_slider, self._transp_slider,
                  self._snap_slider, self._aot_cb):
            w.blockSignals(False)

        # Refresh labels manually.
        self._size_label.setText(f"Size (px): {default_size}")
        self._transp_label.setText(f"Transparency: {round(default_transp * 100)}%")
        self._snap_label.setText(f"Snap distance (px): {default_snap}")
        self._update_orient_enabled()
        _log("PreferencesDialog: reset to branding defaults")


# ---------------------------------------------------------------------------
# Snap-preview overlay
# ---------------------------------------------------------------------------

class _SnapPreviewOverlay(QMainWindow):
    """Transparent overlay that paints the ghost hex outline at the snap position.

    This is a separate frameless transparent window so we can position it
    independently of the dragging hexagon.  It is created lazily on first
    snapPreview signal and reused thereafter.

    Visual rules (ADR-001 Amendment 1 Â§A.5):
      - Edge snap:   2-px hexHighlight outline at the snapped position.
      - Vertex snap: 2-px outline + 4-px filled dot at the vertex touch point
                     in palette.accent colour.
    """

    def __init__(self, branding: dict) -> None:
        super().__init__(
            None,
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        # Never accept input â€” it's purely visual.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        palette = branding.get("palette", {})
        self._highlight_color = _parse_rgba_hex(palette.get("hexHighlight", "60a5faff"))
        self._accent_color = _parse_rgba_hex(palette.get("accent", "f59e0bff"))

        self._shape: str = "hexagon"
        self._orientation: str = "flat-top"
        self._size_px: int = 56
        self._mode: str = "edge"

        # Vertex touch point (widget-local) for vertex-snap mode.
        self._touch_local: QPointF | None = None

    def update_geometry(
        self,
        x: int, y: int, w: int, h: int,
        shape: str, orientation: str, mode: str,
        touch_local: QPointF | None = None,
    ) -> None:
        """Reposition and configure the overlay for a new snap preview."""
        self._shape = shape
        self._orientation = orientation
        self._size_px = w  # assume square widget
        self._mode = mode
        self._touch_local = touch_local
        self.resize(w, h)
        self.move(x, y)
        poly = compute_polygon(shape, w, orientation)
        self.setMask(QRegion(poly.polygon))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        size = self.width()
        geom = compute_polygon(self._shape, size, self._orientation)
        poly = geom.polygon

        if self._mode == "edge":
            # Outline only in hexHighlight colour.
            painter.setBrush(Qt.NoBrush)
            pen = QPen(self._highlight_color)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawPolygon(poly)
        else:
            # Vertex snap: outline in highlight + accent dot at touch point.
            painter.setBrush(Qt.NoBrush)
            pen = QPen(self._highlight_color)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawPolygon(poly)

            if self._touch_local is not None:
                # 4-px filled circle at the vertex touch point.
                painter.setBrush(self._accent_color)
                painter.setPen(Qt.NoPen)
                r = 4
                painter.drawEllipse(
                    int(self._touch_local.x()) - r,
                    int(self._touch_local.y()) - r,
                    r * 2, r * 2
                )


# ---------------------------------------------------------------------------
# _ShakeDetector â€” shake-to-unassociate (Bug 4)
# ---------------------------------------------------------------------------
# Standard mobile-app shake pattern: sample drag-direction at each move event
# using a sliding window of recent direction vectors.  Count direction
# reversals (consecutive vectors whose dot product is negative â€” they oppose
# each other).  If reversals exceed REVERSAL_THRESHOLD within WINDOW_MS, the
# shake is considered detected.
#
# Tuning constants (user-adjustable in a future settings panel):
#   BUFFER_SIZE         â€” number of direction samples in the sliding window.
#   REVERSAL_THRESHOLD  â€” minimum reversals to trigger a shake.
#   WINDOW_MS           â€” time window in milliseconds; older samples are pruned.
#   MIN_MOVE_PX         â€” minimum pixel movement to register a direction sample
#                         (prevents noise at very slow drags from creating spurious
#                         reversal counts).

class _ShakeDetector:
    """Detects a shake gesture during drag by counting direction reversals.

    Usage:
        detector = _ShakeDetector()
        # in mouseMoveEvent, after translating the window:
        detector.sample(dx, dy)
        if detector.is_shaking():
            detector.reset()
            # handle shake

    is_shaking() returns True once and resets itself to avoid re-firing.
    """

    BUFFER_SIZE        = 8     # samples in the sliding window
    REVERSAL_THRESHOLD = 4     # reversals needed to trigger
    WINDOW_MS          = 600   # milliseconds; prune samples older than this
    MIN_MOVE_PX        = 4     # ignore tiny jitter moves

    def __init__(self) -> None:
        # Each entry: (timestamp_seconds, dx, dy)
        self._samples: list[tuple[float, float, float]] = []

    def reset(self) -> None:
        self._samples.clear()

    def sample(self, dx: float, dy: float) -> None:
        """Record a movement vector. Call once per mouseMoveEvent during drag."""
        if abs(dx) < self.MIN_MOVE_PX and abs(dy) < self.MIN_MOVE_PX:
            return  # too small to register direction

        now = _time_module.monotonic()

        # Prune old samples outside the time window.
        cutoff = now - self.WINDOW_MS / 1000.0
        self._samples = [s for s in self._samples if s[0] >= cutoff]

        self._samples.append((now, float(dx), float(dy)))

        # Keep only the most recent BUFFER_SIZE samples.
        if len(self._samples) > self.BUFFER_SIZE:
            self._samples = self._samples[-self.BUFFER_SIZE:]

    def is_shaking(self) -> bool:
        """Return True if enough direction reversals occurred within the window.

        A reversal is detected when consecutive samples have a negative dot
        product (they point in roughly opposite directions).
        """
        if len(self._samples) < 3:
            return False

        reversals = 0
        for i in range(1, len(self._samples)):
            _, dx0, dy0 = self._samples[i - 1]
            _, dx1, dy1 = self._samples[i]
            dot = dx0 * dx1 + dy0 * dy1
            if dot < 0:
                reversals += 1

        return reversals >= self.REVERSAL_THRESHOLD


# ---------------------------------------------------------------------------
# Group-move re-entry guard (Bug 2)
# ---------------------------------------------------------------------------
# When the whole dock group is translated together, each member's moveEvent
# fires and would naively try to move all other members, causing infinite
# recursion.  We block re-entry by tracking which hex_ids are currently
# the *initiator* of a group move.  Partners suppress their own group-move
# emission while they appear in this set.
_GROUP_MOVE_IN_PROGRESS: set[str] = set()


# ---------------------------------------------------------------------------
# CellWindow
# ---------------------------------------------------------------------------

class CellWindow(QMainWindow):
    """Frameless, transparent, always-on-top hexagonal launcher window.

    Per ADR-001 Â§sub-decision-2, the constructor receives a branding dict
    (the parsed branding.config.json).  No brand literals live in this file.

    Instance roles
    --------------
    role = 'standalone' â€” an ordinary user-spawned hexagon.
    role = 'master'     â€” spawned when two standalone hexes dock edge-to-edge.
                          Carries source_a_id and source_b_id.

    Signals
    -------
    reshaped(hex_id: str)
        Emitted from apply_shape_change / apply_size_change so SnapEngine
        invalidates its vertex cache for this hex.

    Public harness-driveable hooks (ADR-001 Â§harness-driveable contract):
        move_to(x, y)    â€” move to logical screen coords
        click(mode)      â€” fire single/double/right click handler
        dock_with(other) â€” programmatic edge-dock (picks best edge pair)
        dump_state()     â€” serialisable snapshot dict
    """

    reshaped = Signal(str)   # hex_id

    def __init__(
        self,
        branding: dict,
        parent=None,
        role: Literal["standalone", "master"] = "standalone",
        source_a_id: str | None = None,
        source_b_id: str | None = None,
        hexagon_id: str | None = None,
        catalog_path: str | None = None,
    ) -> None:
        # ----------------------------------------------------------------
        # Window flags â€” exact set from ADR-001 Â§sub-decision-2
        # ----------------------------------------------------------------
        super().__init__(
            parent,
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool                       # WS_EX_TOOLWINDOW â†’ excluded from Alt+Tab
            | Qt.NoDropShadowWindowHint,    # we draw our own; DWM clips to bounding rect
        )

        # ----------------------------------------------------------------
        # Widget attributes
        # ----------------------------------------------------------------
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)   # registry owns lifetime

        # ----------------------------------------------------------------
        # Identity and role
        # ----------------------------------------------------------------
        self._id: str = hexagon_id if hexagon_id is not None else str(uuid.uuid4())
        self.role: Literal["standalone", "master"] = role
        self.source_a_id: str | None = source_a_id
        self.source_b_id: str | None = source_b_id

        # ----------------------------------------------------------------
        # Branding
        # ----------------------------------------------------------------
        self._branding = branding
        palette = branding.get("palette", {})
        hex_cfg = branding.get("hexagon", {})

        # ---- Branding defaults (overridden by QSettings below) ----------
        self._size_px: int = hex_cfg.get("defaultSizePx", 56)
        self._shape: str = hex_cfg.get("shape", "hexagon")
        self._orientation: str = hex_cfg.get("orientation", "flat-top")
        self._transparency: float = hex_cfg.get("defaultTransparency", 0.85)
        self._always_on_top: bool = bool(hex_cfg.get("defaultAlwaysOnTop", True))

        self._fill_color      = _parse_rgba_hex(palette.get("hexFill",      "1f2937e6"))
        self._stroke_color    = _parse_rgba_hex(palette.get("hexStroke",    "9ca3afff"))
        self._highlight_color = _parse_rgba_hex(palette.get("hexHighlight", "60a5faff"))
        self._accent_color    = _parse_rgba_hex(palette.get("accent",       "f59e0bff"))
        self._menu_bg_color   = _parse_rgba_hex(palette.get("menuBg",       "0f172af0"))
        # Bug 5 â€” unassociated standalone hex gets a green outline.
        # Tailwind emerald-500 (#10b981) is the default; overridable in branding.
        self._unassociated_stroke_color = _parse_rgba_hex(
            palette.get("unassociatedStroke", "10b981ff")
        )

        # ----------------------------------------------------------------
        # Per-hex catalog path.
        # None  â†’ use the default sample catalog.
        # str   â†’ absolute path to a .scriptreetree / .scriptree file.
        # Populated from QSettings (standalone) or passed by the caller
        # (e.g. when spawning a clone that inherits the source's catalog).
        # The constructor parameter overrides the persisted value so that
        # clone-spawn can force-inherit the parent's catalog even when the
        # new hex has no persisted setting yet.
        # Masters always use None â€” they show the merged tree of two sources.
        # ----------------------------------------------------------------
        self._catalog_path: str | None = None

        # ----------------------------------------------------------------
        # Load persisted settings (overrides branding defaults).
        # Masters get fresh branding defaults â€” they do NOT inherit
        # per-hex settings of their source hexes.
        # ----------------------------------------------------------------
        if role == "standalone":
            self._load_settings()

        # Constructor catalog_path overrides persisted value (clone-spawn path).
        if catalog_path is not None:
            self._catalog_path = catalog_path

        # ----------------------------------------------------------------
        # Pre-compute ShapeGeometry (also used by SnapEngine).
        # Stored as self._geom and refreshed by every apply_*_change call.
        # ----------------------------------------------------------------
        self._geom: ShapeGeometry = compute_polygon(self._shape, self._size_px, self._orientation)

        # ----------------------------------------------------------------
        # Hover and drag state
        # ----------------------------------------------------------------
        self._hovered: bool = False

        # Manual drag state.
        # _press_global_pos  â€” where the mouse was pressed (global px).
        # _drag_offset       â€” global press pos minus window top-left at press.
        # _drag_started      â€” True once the 4 px manhattan threshold is crossed.
        #
        # We use FULLY MANUAL drag (no startSystemMove / DWM involvement).
        # Every previous attempt to make startSystemMove cooperate with the snap
        # engine failed: DWM swallows mouseReleaseEvent for Qt.Tool frameless
        # windows on Win11, the polling-timer approach races against the event
        # loop, and event type 174 (NonClientAreaMouseButtonRelease) never fires
        # reliably for Qt.Tool windows.  Manual drag avoids all of this and
        # gives the snap engine exact, synchronous position updates.
        self._press_global_pos: QPoint = QPoint()
        self._drag_offset: QPoint = QPoint()
        self._drag_started: bool = False

        # Rate-limit timestamps for per-frame event logs (move, tick).
        self._last_move_log_time: float = 0.0

        # Bug 2 â€” group-move: remember position at start of each moveEvent
        # so we can compute the per-frame delta.
        self._last_pos: QPoint | None = None

        # ----------------------------------------------------------------
        # Dock state â€” Amendment 2 (group-association model)
        # ----------------------------------------------------------------

        # For STANDALONE hexes:
        #   _group_master_id â€” id of the master whose group this hex belongs to.
        #                      None = not in any group.
        #   _docked_to       â€” ids of hexes currently positionally adjacent
        #                      (touching honeycomb edges). Cleared on break-free.
        self._group_master_id: str | None = None
        self._docked_to: set[str] = set()

        # Legacy shim â€” kept so SnapEngine's dock_group_of call (which reads
        # _dock_partners on some code paths) does not crash in-flight.
        # _dock_partners is no longer the source of truth for group membership.
        # Use _group_master_id / _docked_to instead.
        self._dock_partners: set[str] = set()   # DEPRECATED â€” shim only

        # For MASTER hexes:
        #   _members     â€” {member_id: QPoint} â€” every group member and its
        #                  current preferred screen position. ALWAYS a real
        #                  QPoint (never None).
        #   _positioned  â€” subset of _members currently in the contiguous
        #                  honeycomb cluster anchored at this master.
        #                  Master-drag translates only _positioned members.
        self._members: dict[str, QPoint] = {}
        self._positioned: set[str] = set()

        # Edge-fold auto-hide set (master only).
        # When the master is dragged near a screen edge, positioned members
        # whose bounding box would be >50% off-screen are hidden transiently.
        # These ids remain in _members and _positioned â€” only their visibility
        # is suppressed.  _auto_hidden is purely transient view state and is
        # NOT serialised to .scriptreering files.
        self._auto_hidden: set[str] = set()

        # Creation timestamp â€” used by _try_spawn_master to pick the oldest
        # canonical master when two groups merge.
        import time as _time_mod
        self._creation_time: float = _time_mod.monotonic()

        # ----------------------------------------------------------------
        # Master collapse/expand state machine.
        # Only meaningful when self.role == 'master'.
        # 'expanded'   â€” member hexes visible at their stored positions.
        # 'collapsing' â€” animation in flight toward master's centre.
        # 'collapsed'  â€” member hexes hidden, tucked inside master.
        # 'expanding'  â€” animation in flight outward to stored positions.
        # ----------------------------------------------------------------
        self._collapse_state: str = "expanded"
        # _home_positions is kept as a shim alias for _members so that
        # any remaining internal call to _shift_home_positions still works.
        # It IS the same dict object â€” mutations via either name are shared.
        self._home_positions: dict[str, QPoint] = self._members
        # Running animations keyed by hex_id â€” kept alive to avoid GC.
        self._collapse_animations: dict[str, QPropertyAnimation] = {}

        # ----------------------------------------------------------------
        # Settings dialog (lazy â€” created on first open, then reused)
        # ----------------------------------------------------------------
        self._settings_dialog: SettingsDialog | None = None

        # ----------------------------------------------------------------
        # Menu state â€” per-hex, per ADR-001 sub-decision-4 identity rules.
        # Per menu-engineer dispatch phase1-tree-view-and-click-semantics.
        # ----------------------------------------------------------------
        # True when this hex is in lock-open mode (double-click toggled it).
        self._locked_open: bool = False
        # The live TreeMenuWindow for this hex (None when no menu is showing).
        self._menu_window = None

        # ----------------------------------------------------------------
        # Snap-preview overlay (lazy).
        # ----------------------------------------------------------------
        self._snap_overlay: _SnapPreviewOverlay | None = None

        # ----------------------------------------------------------------
        # Shake-to-unassociate detector (Bug 4).
        # Instantiated once; reset at each drag-start.
        # ----------------------------------------------------------------
        self._shake_detector = _ShakeDetector()

        # ----------------------------------------------------------------
        # Double-right-click detection (Bug 3).
        # Qt only fires mouseDoubleClickEvent for the left button.  We
        # track right-press timestamps manually.
        # _right_press_time â€” monotonic timestamp of the last right-press,
        #                     or None if no pending right-press.
        # _right_click_timer â€” QTimer that fires click("right") after the
        #                      OS double-click interval elapses, so a single
        #                      right-press still opens the context menu.
        # ----------------------------------------------------------------
        from PySide6.QtCore import QTimer as _QTimer
        self._right_press_time: float | None = None
        self._right_click_timer = _QTimer(self)
        self._right_click_timer.setSingleShot(True)
        self._right_click_timer.timeout.connect(self._fire_single_right_click)

        # ----------------------------------------------------------------
        # Master single-click deferral (Bug 6 â€” double-click preemption).
        # When role == 'master', a single left-click must not immediately
        # trigger collapse/expand: Qt synthesises mouseReleaseEvent (â†’
        # click("single")) BEFORE mouseDoubleClickEvent (â†’ click("double")),
        # so without deferral the slide animation fires on every first click
        # of a double-click sequence, making double-click unreachable.
        #
        # Solution: arm this one-shot timer for QApplication.doubleClickInterval()
        # ms.  If click("double") or click("double-right") arrives within that
        # window it cancels the timer; otherwise _fire_pending_master_single_click
        # commits the collapse/expand.
        #
        # Standalone hexes are NOT deferred â€” their single-click expectation is
        # "open menu NOW" and they have no collapse action to wait for.
        # ----------------------------------------------------------------
        self._pending_master_single_click_timer: _QTimer | None = None

        # ----------------------------------------------------------------
        # Sizing and masking
        # ----------------------------------------------------------------
        self.resize(self._size_px, self._size_px)
        self._apply_hex_mask(self._size_px)
        self.setMouseTracking(True)

        # ----------------------------------------------------------------
        # Apply always-on-top flag
        # ----------------------------------------------------------------
        self._apply_always_on_top_flag(self._always_on_top)

        # ----------------------------------------------------------------
        # Place near top-left of primary screen by default.
        # ----------------------------------------------------------------
        self.move(100, 100)

        # ----------------------------------------------------------------
        # Register with the singleton CellRegistry.
        # Import here to avoid a circular import at module level.
        # ----------------------------------------------------------------
        from scriptree.shell.cell_registry import CellRegistry
        CellRegistry.instance().register(self)

        _log(
            f"CellWindow created id={self._id} role={self.role} "
            f"size={self._size_px}px shape={self._shape} orient={self._orientation} "
            f"transparency={self._transparency:.2f} aot={self._always_on_top}"
        )
        # Bug 2 â€” OS double-click interval verification.
        # QApplication.doubleClickInterval() reads GetDoubleClickTime() on Win11
        # (typically 500 ms), so this should reflect the OS setting.
        # If you see a value very different from your OS setting, check whether
        # the Qt platform plugin is overriding it.
        _log(f"OS double-click interval: {QApplication.doubleClickInterval()} ms")

    # ------------------------------------------------------------------
    # Lifecycle: close â†’ unregister
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        from scriptree.shell.cell_registry import CellRegistry
        _log(f"closeEvent id={self._id}")
        # Close the snap overlay if present.
        if self._snap_overlay is not None:
            self._snap_overlay.hide()
        # Unregister from registry (emits hexagonClosed).
        CellRegistry.instance().unregister(self._id)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # QSettings persistence  (ADR-001 Â§sub-decision-5)
    # ------------------------------------------------------------------

    def _settings_key(self, field: str) -> str:
        """Return the QSettings key for this hexagon instance and field."""
        return f"hexagon/{self._id}/{field}"

    def _load_settings(self) -> None:
        """Load per-hex settings; fall back to app/* defaults, then branding.

        Resolution order for each field:
          1. hexagon/<id>/<field>   â€” per-hex persisted setting
          2. app/default_<field>   â€” app-wide default set via Preferences dialog
          3. branding default      â€” self._<field> as set before this call
        """
        s = QSettings()

        raw_shape = s.value(self._settings_key("shape"))
        if raw_shape is None:
            raw_shape = s.value("app/default_shape")
        if raw_shape is not None:
            self._shape = _coerce_str(raw_shape, ["hexagon", "square"], self._shape)

        raw_orient = s.value(self._settings_key("orientation"))
        if raw_orient is None:
            raw_orient = s.value("app/default_orientation")
        if raw_orient is not None:
            self._orientation = _coerce_str(
                raw_orient, ["flat-top", "pointy-top"], self._orientation
            )

        raw_size = s.value(self._settings_key("size_px"))
        if raw_size is None:
            raw_size = s.value("app/default_size_px")
        if raw_size is not None:
            self._size_px = _coerce_int(raw_size, self._size_px, 32, 96)

        raw_transp = s.value(self._settings_key("transparency"))
        if raw_transp is None:
            raw_transp = s.value("app/default_transparency")
        if raw_transp is not None:
            try:
                v = float(raw_transp)
                self._transparency = max(0.30, min(1.00, v))
            except (TypeError, ValueError):
                pass  # keep branding default

        raw_aot = s.value(self._settings_key("always_on_top"))
        if raw_aot is None:
            raw_aot = s.value("app/default_always_on_top")
        if raw_aot is not None:
            self._always_on_top = _coerce_bool(raw_aot)

        raw_cp = s.value(self._settings_key("catalog_path"))
        self._catalog_path = raw_cp if isinstance(raw_cp, str) and raw_cp else None

    def _save_settings(self) -> None:
        """Persist current per-hex settings to QSettings immediately."""
        s = QSettings()
        s.setValue(self._settings_key("shape"), self._shape)
        s.setValue(self._settings_key("orientation"), self._orientation)
        s.setValue(self._settings_key("size_px"), self._size_px)
        s.setValue(self._settings_key("transparency"), self._transparency)
        s.setValue(self._settings_key("always_on_top"), self._always_on_top)
        s.setValue(self._settings_key("catalog_path"), self._catalog_path or "")
        s.sync()

    # ------------------------------------------------------------------
    # Mask
    # ------------------------------------------------------------------

    def _apply_hex_mask(self, size_px: int) -> None:
        """Apply the shape clip region. Called at init and on screenChanged."""
        poly = compute_polygon(self._shape, size_px, self._orientation)
        self._geom = poly
        self.setMask(QRegion(poly.polygon))

    # ------------------------------------------------------------------
    # Live shape / size / transparency / always-on-top apply methods
    # Per ADR-001 Amendment 1.
    # Each of these emits reshaped(self._id) so SnapEngine invalidates cache.
    # ------------------------------------------------------------------

    def apply_shape_change(self, shape: str, orientation: str) -> None:
        """Live-update shape and orientation without recreating the widget."""
        self._shape = shape
        self._orientation = orientation
        self._geom = compute_polygon(shape, self._size_px, orientation)
        self.setMask(QRegion(self._geom.polygon))
        self.update()
        self.reshaped.emit(self._id)
        # Notify registry so SnapEngine cache is invalidated.
        from scriptree.shell.cell_registry import CellRegistry
        CellRegistry.instance().hexagonReshaped.emit(self._id)

    def apply_size_change(self, size_px: int) -> None:
        """Live-update widget size without recreating the widget."""
        self._size_px = size_px
        self.resize(size_px, size_px)
        self._geom = compute_polygon(self._shape, size_px, self._orientation)
        self.setMask(QRegion(self._geom.polygon))
        self.update()
        self.reshaped.emit(self._id)
        from scriptree.shell.cell_registry import CellRegistry
        CellRegistry.instance().hexagonReshaped.emit(self._id)

    def apply_transparency_change(self, alpha: float) -> None:
        """Live-update fill transparency (0.30â€“1.00 alpha multiplier on fill colour)."""
        self._transparency = max(0.30, min(1.00, alpha))
        self.update()

    def apply_always_on_top_change(self, on: bool) -> None:
        """Toggle the WindowStaysOnTopHint flag live."""
        self._always_on_top = on
        self._apply_always_on_top_flag(on)

    def _apply_always_on_top_flag(self, on: bool) -> None:
        """Re-apply the stay-on-top window flag.

        Qt requires a hide + show cycle for flag changes to take effect on Win11.
        We only do this if the window is already visible (not during construction).
        """
        flags = self.windowFlags()
        if on:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if self.isVisible():
            self.show()

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def _compute_stroke_color(self) -> QColor:
        """Return the correct stroke colour based on role and association state.

        Bug 5 â€” green outline rule:
          - Master hex:                      accent colour (visual differentiator).
          - Standalone with no group (unassociated): unassociatedStroke from branding
            (defaults to Tailwind emerald-500 #10b981).
          - Standalone in a group:           normal hexStroke from branding.

        Call update() after any state change that affects group membership so
        the repaint picks up the new colour.
        """
        if self.role == "master":
            return self._accent_color

        if self._group_master_id is None:
            # Unassociated standalone â€” green outline.
            return self._unassociated_stroke_color

        # Associated standalone â€” normal stroke.
        return self._stroke_color

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        size = self.width()
        poly = self._geom.polygon

        # Apply transparency multiplier to the fill colour's alpha channel.
        base_fill = (
            _lerp_color(self._fill_color, self._highlight_color, 0.30)
            if self._hovered
            else self._fill_color
        )
        fill = QColor(
            base_fill.red(),
            base_fill.green(),
            base_fill.blue(),
            round(base_fill.alpha() * self._transparency),
        )

        # ---- Shadow (painted inside mask so DWM never sees it) ----------
        cx = size / 2.0
        cy = size / 2.0
        shadow_grad = QRadialGradient(QPointF(cx, cy), size * 0.55)
        shadow_col = QColor(0, 0, 0, 0)
        shadow_edge = QColor(0, 0, 0, 90)
        shadow_grad.setColorAt(0.55, shadow_col)
        shadow_grad.setColorAt(1.0,  shadow_edge)
        painter.setBrush(shadow_grad)
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(poly)

        # ---- Fill -------------------------------------------------------
        painter.setBrush(fill)
        stroke_color = self._compute_stroke_color()
        stroke_pen = QPen(stroke_color)
        stroke_pen.setWidth(2)
        painter.setPen(stroke_pen)
        painter.drawPolygon(poly)

        # ---- Master centre dot ------------------------------------------
        if self.role == "master":
            # Small filled circle in menuBg colour at the centre.
            dot_r = max(4, size // 10)
            painter.setBrush(self._menu_bg_color)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(
                round(cx) - dot_r, round(cy) - dot_r,
                dot_r * 2, dot_r * 2
            )

        # ---- Edge-fold badge (master only) ------------------------------
        # When _auto_hidden is non-empty, draw a small filled circle badge
        # at the bottom-right of the hexagon inscribed box, with the count
        # of auto-hidden members in the accent colour.
        if self.role == "master" and self._auto_hidden:
            badge_count = len(self._auto_hidden)
            badge_r = max(6, size // 8)
            # Bottom-right corner of the bounding square, pulled inward by badge_r.
            badge_cx = size - badge_r - 2
            badge_cy = size - badge_r - 2
            # Filled circle: accent colour, full opacity.
            badge_color = QColor(self._accent_color)
            badge_color.setAlpha(255)
            painter.setBrush(badge_color)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(badge_cx - badge_r, badge_cy - badge_r,
                                badge_r * 2, badge_r * 2)
            # Count label: white text.
            label_font = QFont()
            label_font.setPixelSize(max(8, badge_r))
            label_font.setBold(True)
            painter.setFont(label_font)
            painter.setPen(QColor(255, 255, 255, 255))
            painter.drawText(
                QRect(badge_cx - badge_r, badge_cy - badge_r,
                      badge_r * 2, badge_r * 2),
                Qt.AlignCenter,
                str(badge_count),
            )

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_global_pos = event.globalPosition().toPoint()
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_started = False
            _log(f"press @ {self._press_global_pos} id={self._id[:8]}")
        elif event.button() == Qt.RightButton:
            # Bug 3 â€” double-right-click detection:
            # Qt only fires mouseDoubleClickEvent for the left button, so we
            # track right-press timestamps manually.
            #
            # Protocol:
            #   First right-press:  record timestamp; start a timer for
            #                       QApplication.doubleClickInterval() ms.
            #                       If the timer fires without a second right-press,
            #                       _fire_single_right_click() opens the context menu.
            #   Second right-press within the interval: cancel the timer; fire
            #                       click("double-right") instead.
            now = _time_module.monotonic()
            interval_s = QApplication.doubleClickInterval() / 1000.0

            if (
                self._right_press_time is not None
                and (now - self._right_press_time) <= interval_s
            ):
                # Second right-press within interval â€” double-right-click.
                self._right_click_timer.stop()
                self._right_press_time = None
                _log(f"double-right-click detected id={self._id[:8]}")
                self.click("double-right")
            else:
                # First right-press â€” arm the timer; do NOT open context menu yet.
                self._right_press_time = now
                self._right_click_timer.start(QApplication.doubleClickInterval())
        super().mousePressEvent(event)

    def _fire_single_right_click(self) -> None:
        """Timer callback: the right-click double-click window elapsed; fire single right."""
        self._right_press_time = None
        self.click("right")

    def mouseMoveEvent(self, event) -> None:
        # Diagnostic wrapper: capture any unexpected crash during drag so the
        # next stderr shows the actual traceback.  The re-raise propagates to
        # Qt's default handler (which will log it); we still surface it cleanly.
        try:
            self._mouseMoveEvent_inner(event)
        except Exception as _mme_exc:
            _log(f"mouseMoveEvent crashed: {_mme_exc!r} id={self._id[:8]}")
            raise

    def _mouseMoveEvent_inner(self, event) -> None:
        import time as _time
        if not (event.buttons() & Qt.LeftButton):
            return super().mouseMoveEvent(event)

        delta = (event.globalPosition().toPoint() - self._press_global_pos).manhattanLength()

        if not self._drag_started:
            if delta <= 4:
                return super().mouseMoveEvent(event)  # not a drag yet

            # Threshold crossed â€” commit to manual drag.
            self._drag_started = True
            # Reset shake detector at the start of each new drag.
            self._shake_detector.reset()
            _log(f"DRAG STARTED (manual) id={self._id[:8]} role={self.role} group_master={self._group_master_id and self._group_master_id[:8]} positioned={len(self._positioned) if self.role == 'master' else len(self._docked_to)}")

            # Amendment 2 â€” break-free: when a standalone source starts dragging
            # it leaves the positional cluster (_positioned set) but RETAINS its
            # group membership (_group_master_id stays set).
            # The master group-moves positionally-docked members instead.
            if self.role == "standalone" and self._docked_to:
                self._break_free_from_cluster()

            try:
                from scriptree.shell.ring_main import _get_snap_engine
                snap = _get_snap_engine()
                if snap is not None:
                    snap.attach_drag(self._id)
                else:
                    _log(f"mouseMoveEvent: snap engine is None â€” attach_drag skipped id={self._id[:8]}")
            except Exception as exc:
                _log(f"mouseMoveEvent: attach_drag exception: {exc!r}")

        # Manual translation â€” fires moveEvent â†’ hexagonMoved â†’ snap engine tick.
        # Screen-edge guard (Bug 2 â€” clock-area crash): clamp requested position
        # to the containing screen's available geometry before calling move().
        # If the cursor has drifted outside every known screen (e.g. WM dragged
        # the window off-display), fall back to the primary screen's area.
        prev_top_left = self.pos()
        raw_pos = event.globalPosition().toPoint() - self._drag_offset
        new_top_left = self._clamp_to_screen(raw_pos)
        self.move(new_top_left.x(), new_top_left.y())

        # Bug 4 â€” shake-to-unassociate: sample movement direction during drag.
        # Only meaningful for standalone hexes that are members of a group.
        # Guard: if _group_master_id is None (not in a group) the shake handler
        # is a no-op anyway, but check explicitly before sampling to avoid
        # burning cycles near the tray.
        if self.role == "standalone" and self._group_master_id is not None:
            dx = new_top_left.x() - prev_top_left.x()
            dy = new_top_left.y() - prev_top_left.y()
            self._shake_detector.sample(dx, dy)
            if self._shake_detector.is_shaking():
                self._shake_detector.reset()
                self._on_shake_detected()

        _now = _time.monotonic()
        if _now - self._last_move_log_time >= 1.0:
            _log(
                f"drag {self._id[:8]} role={self.role} "
                f"pos=({self.x()},{self.y()}) drag_started={self._drag_started}"
            )
            self._last_move_log_time = _now

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            _log(f"release drag_started={self._drag_started} id={self._id[:8]}")
            if self._drag_started:
                # End the drag â€” notify SnapEngine so it can commit a snap.
                self._drag_started = False
                if self._snap_overlay is not None:
                    self._snap_overlay.hide()
                try:
                    from scriptree.shell.ring_main import _get_snap_engine
                    snap = _get_snap_engine()
                    if snap is not None:
                        snap.detach_drag(self._id)
                    else:
                        _log(f"mouseReleaseEvent: snap engine is None â€” detach skipped id={self._id[:8]}")
                except Exception as exc:
                    _log(f"mouseReleaseEvent: detach_drag exception: {exc!r} id={self._id[:8]}")
            else:
                # No drag threshold crossed â€” pure click.
                self.click("single")
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            # Qt synthesises a doubleClick only when two presses land within
            # SM_CXDOUBLECLK and qApp.doubleClickInterval().  With manual drag
            # (no DWM involvement) the release for the second press always
            # arrives, meaning a single-click already fired from mouseReleaseEvent.
            # Per dispatch guidance, we accept the single-then-double progression
            # rather than introducing a QTimer delay to suppress the first single.
            self.click("double")
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------------
    # moveEvent â€” emit hexagonMoved so SnapEngine tick uses fresh coords.
    # Amendment 2: master-drag translates only POSITIONALLY-DOCKED members.
    # ------------------------------------------------------------------

    def moveEvent(self, event) -> None:
        import time as _time
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()
        _now = _time.monotonic()
        if _now - self._last_move_log_time >= 0.1:
            _log(
                f"moveEvent {event.oldPos()}->{event.pos()} "
                f"drag_started={self._drag_started} id={self._id[:8]}"
            )
            self._last_move_log_time = _now
        registry.hexagonMoved.emit(self._id)

        # Amendment 2 â€” master group-drag: translate only the POSITIONALLY-DOCKED
        # members (those in self._positioned). Members that have broken free stay
        # where they are on screen; their stored position in self._members is NOT
        # updated during a master drag â€” they remember their independent position.
        #
        # TODO (future dispatch): when master reaches a screen edge, nudge
        # positioned members to nearest on-screen honeycomb positions rather
        # than clipping. For now, Qt clamps windows to screen bounds.
        current_pos = self.pos()
        last = self._last_pos
        self._last_pos = current_pos

        if (
            self._drag_started
            and self.role == "master"
            and self._id not in _GROUP_MOVE_IN_PROGRESS
            and last is not None
            and self._positioned
        ):
            delta_x = current_pos.x() - last.x()
            delta_y = current_pos.y() - last.y()
            if delta_x != 0 or delta_y != 0:
                # Shift the stored preferred positions for POSITIONED members
                # so that collapse/expand targets track the group's new location.
                self._shift_positioned_members(delta_x, delta_y)

                if _now - self._last_move_log_time >= 1.0:
                    _log(
                        f"group-move from {self._id[:8]} (master); "
                        f"translating {len(self._positioned)} positioned member(s) "
                        f"by ({delta_x},{delta_y})"
                    )

                _GROUP_MOVE_IN_PROGRESS.add(self._id)
                try:
                    for member_id in list(self._positioned):
                        member = registry.get(member_id)
                        if member is None:
                            continue
                        member.move(member.pos().x() + delta_x, member.pos().y() + delta_y)
                finally:
                    _GROUP_MOVE_IN_PROGRESS.discard(self._id)

                # Edge-fold: after translating members, check which ones
                # are now more-than-half off-screen and hide/show accordingly.
                self._check_edge_fold()

        super().moveEvent(event)

    # ------------------------------------------------------------------
    # Snap preview overlay management
    # ------------------------------------------------------------------

    def show_snap_preview(
        self,
        x: int, y: int, w: int, h: int,
        mode: str,
        touch_local: QPointF | None = None,
    ) -> None:
        """Show (or update) the snap preview overlay at the given global position."""
        if self._snap_overlay is None:
            self._snap_overlay = _SnapPreviewOverlay(self._branding)
        overlay = self._snap_overlay
        overlay.update_geometry(x, y, w, h, self._shape, self._orientation, mode, touch_local)
        if not overlay.isVisible():
            overlay.show()
        else:
            overlay.update()

    def hide_snap_preview(self) -> None:
        if self._snap_overlay is not None:
            self._snap_overlay.hide()

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self, pos) -> None:
        from pathlib import Path as _Path
        from scriptree.shell import recent_files as _rf

        brand = self._branding.get("appName", "App")
        app_name_long = self._branding.get("appNameLong", brand)
        tagline = self._branding.get("tagline", "")

        # Use None parent so the menu gets Win11 system chrome rather than
        # inheriting the CellWindow's translucent/dark palette.
        menu = QMenu(None)

        # ---- File type display (read-only, at top) ----
        # Show "ScripTree: <name>" or "ScripTreeTree: <name>" based on the
        # extension of the currently-loaded file.  If nothing is loaded,
        # show a generic "(default)" label.
        if self._catalog_path is not None:
            _cp = _Path(self._catalog_path)
            _ext = _cp.suffix.lower()
            if _ext == ".scriptreetree":
                _type_label = f"ScripTreeTree: {_cp.stem}"
            else:
                # .scriptree or anything else
                _type_label = f"ScripTree: {_cp.stem}"
        else:
            _type_label = "ScripTree: (default)"
        catalog_display = menu.addAction(_type_label)
        catalog_display.setEnabled(False)

        menu.addSeparator()

        # ── ScripTree submenu ─────────────────────────────────────
        # Groups all load / save / clear catalog actions plus the
        # Open recent sub-sub-menu.  Per user direction (2026-05-07):
        # "Catalogue should say ScripTree instead."
        catalog_menu = QMenu("ScripTree", menu)
        load_scriptree_action = catalog_menu.addAction("Load ScripTree…")
        load_scriptreetree_action = catalog_menu.addAction("Load ScripTreeTree…")

        # "Open recent" submenu — last 10 entries per type, merged and
        # sorted most-recent first.  Each entry shows filename + full path.
        recent_tool_paths = _rf.get_scriptree()
        recent_tree_paths = _rf.get_scriptreetree()
        all_recent: list[str] = []
        # Interleave: each list is already most-recent-first.  We merge them
        # by prepending each list's items alternately, preserving MRU order
        # within each type, and cap the combined list at _MAX_RECENT (10).
        _MAX_RECENT_COMBINED = 10
        _ti, _ri = 0, 0
        while len(all_recent) < _MAX_RECENT_COMBINED:
            added = False
            if _ti < len(recent_tool_paths):
                all_recent.append(recent_tool_paths[_ti])
                _ti += 1
                added = True
            if _ri < len(recent_tree_paths) and len(all_recent) < _MAX_RECENT_COMBINED:
                all_recent.append(recent_tree_paths[_ri])
                _ri += 1
                added = True
            if not added:
                break

        recent_menu = QMenu("Open recent", catalog_menu)
        recent_actions: dict = {}  # action → path
        if all_recent:
            for _rp in all_recent:
                _rpath = _Path(_rp)
                _ext_r = _rpath.suffix.lower()
                _prefix = "ScripTreeTree" if _ext_r == ".scriptreetree" else "ScripTree"
                _ra = recent_menu.addAction(
                    f"{_prefix}: {_rpath.name}  —  {_rp}"
                )
                recent_actions[_ra] = _rp
        else:
            _none_act = recent_menu.addAction("(none)")
            _none_act.setEnabled(False)
        catalog_menu.addMenu(recent_menu)

        catalog_menu.addSeparator()

        # "Save as…" — save the currently-loaded catalog file under a new name.
        # Only enabled when a file is loaded.
        save_as_action = catalog_menu.addAction("Save ScripTree as…")
        save_as_action.setEnabled(self._catalog_path is not None)

        clear_catalog_action = None
        if self._catalog_path is not None:
            clear_catalog_action = catalog_menu.addAction("Clear loaded ScripTree")

        menu.addMenu(catalog_menu)

        # ── Tree Ring submenu ─────────────────────────────────────
        # Save/load + autoload of the current cell or the whole ring.
        # When a ring has already been saved (``_saved_ring_path``
        # populated), offer both "Save" (overwrite) and "Save as…"
        # (fork to a new file).  Otherwise only "Save as…" — there's
        # no remembered path to overwrite.
        ring_menu = QMenu("Tree Ring", menu)
        already_saved = getattr(self, "_saved_ring_path", None) is not None

        save_ring_action = None
        if already_saved:
            label = (
                "Save Tree Ring" if self.role != "master"
                else "Save group as Tree Ring"
            )
            save_ring_action = ring_menu.addAction(label)

        if self.role == "master":
            save_ring_as_action = ring_menu.addAction(
                "Save group as Tree Ring as…"
            )
        else:
            save_ring_as_action = ring_menu.addAction(
                "Save as Tree Ring…"
            )
        load_ring_action = ring_menu.addAction("Load Tree Ring…")

        # "Auto-load on startup" sub-sub-menu.
        autoload_menu = QMenu("Auto-load on startup", ring_menu)
        autoload_disabled_action = autoload_menu.addAction("Disabled")
        autoload_disabled_action.setCheckable(True)
        autoload_user_action = autoload_menu.addAction("For current user only")
        autoload_user_action.setCheckable(True)
        autoload_system_action = autoload_menu.addAction(
            "For all users (requires admin)"
        )
        autoload_system_action.setCheckable(True)

        # Determine which state is current.
        saved_path = getattr(self, "_saved_ring_path", None)
        user_paths = []
        sys_paths = []
        try:
            from scriptree.shell.ring_io import list_autoload_rings
            user_paths = [str(p) for p in list_autoload_rings("user")]
            sys_paths  = [str(p) for p in list_autoload_rings("system")]
        except Exception:
            pass

        in_user   = saved_path is not None and str(saved_path) in user_paths
        in_system = saved_path is not None and str(saved_path) in sys_paths

        autoload_user_action.setChecked(in_user)
        autoload_system_action.setChecked(in_system)
        autoload_disabled_action.setChecked(not in_user and not in_system)

        ring_menu.addMenu(autoload_menu)
        menu.addMenu(ring_menu)

        # ── Cell submenu ──────────────────────────────────────────
        # Multi-instance actions + group membership controls.
        cell_menu = QMenu("Cell", menu)
        spawn_action = cell_menu.addAction("Spawn another cell")

        # "Leave group" — shown when this hex belongs to a master's
        # group.  Masters show "Disband group" instead (releases all
        # members).  Visible only when relevant — keeps the submenu
        # tidy when not part of any group.
        leave_group_action = None
        if self._group_master_id is not None or (self.role == "master" and self._members):
            cell_menu.addSeparator()
            if self.role == "master":
                leave_group_action = cell_menu.addAction("Disband group")
            else:
                leave_group_action = cell_menu.addAction("Leave group")

        menu.addMenu(cell_menu)

        menu.addSeparator()

        # ── Top-level: about / settings / preferences ────────────
        about_action = menu.addAction(f"About {brand}")
        settings_action = menu.addAction("Settings…")
        preferences_action = menu.addAction("Preferences…")
        menu.addSeparator()

        # ---- Close / exit actions â€” role-aware ----
        # The user contract is: every cell offers a way to close
        # itself and a way to exit ScripTreeRing entirely. Master
        # cells (rings) additionally offer "close ring" (members
        # become standalone) and "close all related" (close master
        # + all its members).
        close_cell_action = None
        close_ring_action = None
        close_all_related_action = None
        if self.role == "master":
            close_ring_action = menu.addAction(
                "Close ring (undock all members)"
            )
            close_all_related_action = menu.addAction(
                "Close all related (master + members)"
            )
        else:
            close_cell_action = menu.addAction("Close this cell")
        exit_all_action = menu.addAction("Exit all")

        chosen = menu.exec(pos)

        if chosen == load_scriptree_action:
            self._load_catalog_dialog(prefer_ext=".scriptree")
        elif chosen == load_scriptreetree_action:
            self._load_catalog_dialog(prefer_ext=".scriptreetree")
        elif chosen in recent_actions:
            self._open_recent_catalog(recent_actions[chosen])
        elif clear_catalog_action is not None and chosen == clear_catalog_action:
            self._catalog_path = None
            self._save_settings()
            _log(f"Catalog cleared for id={self._id[:8]}")
        elif chosen == save_as_action:
            self._save_catalog_as_dialog()
        elif save_ring_action is not None and chosen == save_ring_action:
            self._save_ring_dialog()
        elif chosen == save_ring_as_action:
            self._save_ring_as_dialog()
        elif chosen == load_ring_action:
            self._load_ring_dialog()
        elif chosen == autoload_disabled_action:
            self._autoload_disable()
        elif chosen == autoload_user_action:
            self._autoload_set_scope("user")
        elif chosen == autoload_system_action:
            self._autoload_set_scope("system")
        elif chosen == spawn_action:
            self._spawn_another()
        elif close_cell_action is not None and chosen == close_cell_action:
            self._close_this()
        elif close_ring_action is not None and chosen == close_ring_action:
            self._close_ring_undock_all()
        elif close_all_related_action is not None \
                and chosen == close_all_related_action:
            self._close_all_related()
        elif chosen == exit_all_action:
            self._exit_all()
        elif leave_group_action is not None and chosen == leave_group_action:
            self._explicit_leave_group()
        elif chosen == about_action:
            # None parent: inherits OS chrome, not the hex's translucent palette.
            msg = QMessageBox(None)
            msg.setWindowTitle(f"About {brand}")
            msg.setText(
                f"<b>{app_name_long}</b><br>"
                f"{tagline}<br><br>"
                f"Version: 0.0.1-demo<br>"
                f"Build: phase-1 demo"
            )
            msg.exec()
        elif chosen == settings_action:
            self._open_settings_dialog()
        elif chosen == preferences_action:
            self._open_preferences_dialog()

    # ------------------------------------------------------------------
    # Ring save / load / autoload handlers
    # ------------------------------------------------------------------

    def _save_ring_dialog(self) -> None:
        """Save the ring to its remembered path, prompting only on
        first save.

        After a successful save, ``self._saved_ring_path`` is set so
        subsequent calls write back to the same file (V1 editor pattern:
        Save vs Save As).  ``_save_ring_as_dialog`` always prompts.
        """
        path = getattr(self, "_saved_ring_path", None)
        if path is None:
            self._save_ring_as_dialog()
            return
        self._write_ring_to_path(path)

    def _save_ring_as_dialog(self) -> None:
        """Always prompt for a destination path, then save the ring."""
        from pathlib import Path as _Path
        from PySide6.QtWidgets import QFileDialog
        from scriptree.shell.ring_io import _default_rings_dir

        brand = self._branding.get("appName", "App")
        default_dir = _default_rings_dir(brand)
        # If already saved once, default to that path so "Save As" can
        # quickly fork to a new name.
        prior = getattr(self, "_saved_ring_path", None)
        if prior is not None:
            start = str(prior)
        else:
            start = str(default_dir)

        chosen, _ = QFileDialog.getSaveFileName(
            None,
            "Save Tree Ring as",
            start,
            "Tree Rings (*.scriptreering);;All files (*)",
        )
        if not chosen:
            return
        path = _Path(chosen)
        if path.suffix.lower() != ".scriptreering":
            path = path.with_suffix(".scriptreering")
        self._write_ring_to_path(path)

    def _write_ring_to_path(self, path) -> None:  # noqa: ANN001
        """Write the current cell/ring to ``path`` via ``save_ring``."""
        from scriptree.shell.ring_io import save_ring
        try:
            save_ring(self, path)
            self._saved_ring_path = path
            _log(f"Ring saved to {path} by id={self._id[:8]}")
        except Exception as exc:  # noqa: BLE001
            _log(f"_write_ring_to_path: save_ring failed: {exc!r}")
            QMessageBox.warning(
                None, "Save failed", f"Could not save ring:\n{exc}"
            )

    def _load_ring_dialog(self) -> None:
        """Open a load dialog and call load_ring() on confirm.

        Works from both master and standalone hexagons.
        """
        from pathlib import Path as _Path
        from PySide6.QtWidgets import QFileDialog
        from scriptree.shell.ring_io import load_ring, _default_rings_dir

        brand = self._branding.get("appName", "App")
        default_dir = _default_rings_dir(brand)

        chosen, _ = QFileDialog.getOpenFileName(
            None,
            "Load Tree Ring",
            str(default_dir),
            "Tree Rings (*.scriptreering);;All files (*)",
        )
        if not chosen:
            return

        path = _Path(chosen)
        try:
            from scriptree.shell.cell_registry import CellRegistry
            from scriptree.shell.ring_main import _get_snap_engine
            registry = CellRegistry.instance()
            snap = _get_snap_engine()
            master = load_ring(path, self._branding, registry, snap)
            master._saved_ring_path = path
            _log(f"Ring loaded from {path} â€” master {master._id[:8]}")
        except Exception as exc:
            _log(f"_load_ring_dialog: load_ring failed: {exc!r}")
            QMessageBox.warning(None, "Load failed", f"Could not load ring:\n{exc}")

    def _autoload_set_scope(self, scope: str) -> None:
        """Enable auto-load for this ring at the given scope ('user' or 'system').

        If the ring has not been saved yet, prompts the user to save first.
        For 'system' scope when not admin, triggers UAC elevation.
        """
        from pathlib import Path as _Path
        from scriptree.shell.ring_io import (
            add_autoload_ring,
            _is_admin,
            elevate_for_system_autostart,
        )

        saved_path = getattr(self, "_saved_ring_path", None)
        if saved_path is None:
            # Prompt varies: masters save a group; standalones save a single hex.
            if self.role == "master":
                prompt_text = "Save this group as a ring file first, then enable auto-load?"
            else:
                prompt_text = "Save this hexagon as a ring file first, then enable auto-load?"
            reply = QMessageBox.question(
                None,
                "Save required",
                prompt_text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._save_ring_dialog()
                saved_path = getattr(self, "_saved_ring_path", None)
            if saved_path is None:
                return  # User cancelled

        if scope == "system" and not _is_admin():
            # Trigger UAC elevation for system-scope registration.
            _log(f"_autoload_set_scope(system): not admin â€” requesting elevation")
            try:
                elevate_for_system_autostart(_Path(saved_path))
            except Exception as exc:
                _log(f"_autoload_set_scope: elevation failed: {exc!r}")
                QMessageBox.warning(
                    None,
                    "Elevation failed",
                    f"Could not request admin privileges:\n{exc}",
                )
            return

        try:
            add_autoload_ring(_Path(saved_path), scope)  # type: ignore[arg-type]
            _log(
                f"_autoload_set_scope: ring {saved_path} registered for "
                f"scope={scope} id={self._id[:8]}"
            )
        except Exception as exc:
            _log(f"_autoload_set_scope: add_autoload_ring failed: {exc!r}")
            QMessageBox.warning(
                None, "Auto-load failed", f"Could not register auto-load:\n{exc}"
            )

    def _autoload_disable(self) -> None:
        """Remove this ring from both user and system autoload configs."""
        from pathlib import Path as _Path
        from scriptree.shell.ring_io import remove_autoload_ring, list_autoload_rings

        saved_path = getattr(self, "_saved_ring_path", None)
        if saved_path is None:
            _log("_autoload_disable: no saved path â€” nothing to disable")
            return

        for scope in ("user", "system"):
            try:
                paths = [str(p) for p in list_autoload_rings(scope)]  # type: ignore[arg-type]
                if str(saved_path) in paths:
                    remove_autoload_ring(_Path(saved_path), scope)  # type: ignore[arg-type]
            except Exception as exc:
                _log(f"_autoload_disable: remove_autoload_ring({scope}) failed: {exc!r}")

    def _load_catalog_dialog(self, prefer_ext: str = "") -> None:
        """Open a file dialog to assign a catalog to this hexagon.

        prefer_ext â€” if ".scriptree" or ".scriptreetree", that filter is
        selected by default in the dialog.  The user can still switch filters
        to pick the other type.
        """
        from pathlib import Path as _Path
        from scriptree.shell import recent_files as _rf

        # Start in the sample-catalog directory if it exists.
        project_root = _Path(__file__).resolve().parent.parent.parent
        start_dir = str(project_root / "sample-catalog")

        _FILTER_TOOL = "ScripTree files (*.scriptree)"
        _FILTER_TREE = "ScripTreeTree files (*.scriptreetree)"
        _FILTER_ALL  = "All catalog files (*.scriptree *.scriptreetree)"
        _FILTER_ANY  = "All files (*)"
        all_filters = ";;".join([_FILTER_TOOL, _FILTER_TREE, _FILTER_ALL, _FILTER_ANY])

        if prefer_ext == ".scriptreetree":
            default_filter = _FILTER_TREE
            caption = "Load ScripTreeTree"
        elif prefer_ext == ".scriptree":
            default_filter = _FILTER_TOOL
            caption = "Load ScripTree"
        else:
            default_filter = _FILTER_ALL
            caption = "Load ScripTree or ScripTreeTree"

        chosen, _ = QFileDialog.getOpenFileName(
            None,
            caption,
            start_dir,
            all_filters,
            default_filter,
        )
        if chosen:
            self._catalog_path = chosen
            self._save_settings()
            _rf.add(chosen)
            _log(f"Catalog set to {chosen!r} for id={self._id[:8]}")

    def _open_recent_catalog(self, path: str) -> None:
        """Load a catalog from the recent-files list, handling missing files."""
        from pathlib import Path as _Path
        from scriptree.shell import recent_files as _rf

        if not _Path(path).exists():
            msg = QMessageBox(None)
            msg.setWindowTitle("File not found")
            msg.setText(
                f"The file could not be found and will be removed from the "
                f"recent list:\n\n{path}"
            )
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.exec()
            # Remove from whichever recent list it's in.
            for key in ("hex_shell/recent_scriptree", "hex_shell/recent_scriptreetree"):
                s = QSettings()
                import json as _json
                raw = s.value(key, "[]")
                try:
                    items = _json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    items = []
                items = [p for p in items if p != path]
                s.setValue(key, _json.dumps(items))
                s.sync()
            return
        self._catalog_path = path
        self._save_settings()
        _rf.add(path)
        _log(f"Catalog set from recent: {path!r} for id={self._id[:8]}")

    def _save_catalog_as_dialog(self) -> None:
        """Save the currently-loaded catalog file under a new name.

        This is a file-copy operation: reads the loaded file and writes it to
        the chosen destination.  The hex's _catalog_path is updated to point
        at the new file.
        """
        from pathlib import Path as _Path
        import shutil
        from scriptree.shell import recent_files as _rf

        if self._catalog_path is None:
            return
        src = _Path(self._catalog_path)
        _ext = src.suffix.lower()
        if _ext == ".scriptreetree":
            file_filter = "ScripTreeTree files (*.scriptreetree);;All files (*)"
            caption = "Save ScripTreeTree as"
        else:
            file_filter = "ScripTree files (*.scriptree);;All files (*)"
            caption = "Save ScripTree as"

        chosen, _ = QFileDialog.getSaveFileName(
            None,
            caption,
            str(src.parent / src.name),
            file_filter,
        )
        if not chosen:
            return
        dest = _Path(chosen)
        try:
            shutil.copy2(str(src), str(dest))
        except OSError as exc:
            msg = QMessageBox(None)
            msg.setWindowTitle("Save failed")
            msg.setText(f"Could not save file:\n\n{exc}")
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.exec()
            return
        self._catalog_path = str(dest)
        self._save_settings()
        _rf.add(str(dest))
        _log(f"Catalog saved-as {dest!r} for id={self._id[:8]}")

    def _explicit_leave_group(self) -> None:
        """Explicit gesture: remove this hex (or disband, if master) from its group.

        For a STANDALONE member: removes self from the master's _members and
        _positioned sets. Clears _group_master_id. Closes master if < 2 remain.
        For the MASTER itself: removes all members from the group, closes master.
        Does NOT move any window.
        """
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()

        if self.role == "master":
            # Disband: clear group membership for all members, then close.
            for member_id in list(self._members.keys()):
                member = registry.get(member_id)
                if member is not None:
                    member._group_master_id = None
                    member._docked_to.clear()
                    member._dock_partners.clear()
                    member.update()  # Bug 5: refresh outline (now unassociated â†’ green)
            self._members.clear()
            self._positioned.clear()
            self._dock_partners.clear()
            if self.isVisible():
                self.hide()
                registry.masterDespawned.emit(self._id)
            _log(f"Master {self._id[:8]} disbanded by explicit gesture")
            return

        # Standalone member: leave the group.
        mid = self._group_master_id
        if mid is None:
            _log(f"_explicit_leave_group: {self._id[:8]} not in any group â€” no-op")
            return

        master = registry.get(mid)
        if master is not None:
            master._members.pop(self._id, None)
            master._positioned.discard(self._id)
            master._dock_partners.discard(self._id)

        self._group_master_id = None
        self._docked_to.clear()
        self._dock_partners.clear()
        self.update()  # Bug 5: refresh outline (now unassociated â†’ green)
        _log(f"Standalone {self._id[:8]} left group (master={mid and mid[:8]})")

        # Close master if fewer than 2 members remain.
        if master is not None:
            _check_master_validity(master, registry)

    def _on_shake_detected(self) -> None:
        """Shake gesture handler: fully unassociate this hex from its master's group.

        Bug 4 â€” shake-to-unassociate.  Called from mouseMoveEvent when the
        _ShakeDetector triggers.  This is a FULL unassociation (removes from
        master._members, clears _group_master_id) â€” stronger than break-free,
        which only leaves the positional cluster while retaining membership.

        Steps:
        1. Remove self from master._members and master._positioned.
        2. Clear self._group_master_id (fully unassociated).
        3. Trigger a brief green flash (200 ms) as visual feedback.
        4. Close master if it now has fewer than 2 members.
        5. Call update() so _compute_stroke_color() picks up the new state
           and the green outline starts rendering immediately.
        """
        from scriptree.shell.cell_registry import CellRegistry
        from PySide6.QtCore import QTimer as _QTimer

        registry = CellRegistry.instance()

        mid = self._group_master_id
        if mid is None:
            return  # already unassociated â€” no-op

        master = registry.get(mid)
        if master is not None:
            master._members.pop(self._id, None)
            master._positioned.discard(self._id)
            master._dock_partners.discard(self._id)

        old_master_short = mid[:8]
        self._group_master_id = None
        self._docked_to.clear()
        self._dock_partners.clear()

        _log(
            f"shake detected â€” {self._id[:8]} unassociated from master {old_master_short}"
        )

        # Visual feedback: briefly flash highlight colour for 200 ms then
        # revert to the new green unassociated stroke.  We achieve the flash
        # by temporarily swapping _hovered to True (which tints the fill) and
        # scheduling a revert.  This avoids a full animation infrastructure.
        self._hovered = True
        self.update()

        def _end_flash():
            self._hovered = False
            self.update()

        _QTimer.singleShot(200, _end_flash)

        # Close master if fewer than 2 members remain.
        if master is not None:
            _check_master_validity(master, registry)

    def _break_free_from_cluster(self) -> None:
        """Break-free drag path (Amendment 2): standalone source leaves the
        POSITIONAL CLUSTER but retains group membership.

        Called at the 4 px drag threshold in mouseMoveEvent when
        self.role == 'standalone' and self._docked_to is non-empty.

        Steps:
        1. Remove self from every _docked_to peer's _docked_to set.
        2. Remove self from master._positioned (if in a group).
        3. Update master._members[self._id] to the current position so
           collapse/expand knows where this member last was.
        4. Clear self._docked_to.
        5. _group_master_id is PRESERVED â€” still a group member.
        """
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()

        # Remove self from all adjacent peers' _docked_to sets.
        for peer_id in list(self._docked_to):
            peer = registry.get(peer_id)
            if peer is not None:
                peer._docked_to.discard(self._id)

        self._docked_to.clear()
        self._dock_partners.clear()   # keep shim clear too

        # Remove from master's positioned set; update stored position.
        mid = self._group_master_id
        if mid is not None:
            master = registry.get(mid)
            if master is not None:
                master._positioned.discard(self._id)
                # Record current position so collapse/expand restores it.
                master._members[self._id] = QPoint(self.pos())
                master._dock_partners.discard(self._id)

        _log(
            f"break-free: {self._id[:8]} left cluster "
            f"(group_master={mid and mid[:8]} preserved)"
        )

    def _spawn_another(self) -> None:
        """Spawn a new standalone CellWindow offset from this one.

        The new hex starts from branding defaults (fresh UUID, no persisted
        settings). Position is clamped to the primary screen's available area.
        """
        from scriptree.shell.cell_registry import CellRegistry

        # Offset: +120 logical px horizontally from this window's top-left.
        offset_x = 120
        offset_y = 0
        new_x = self.pos().x() + offset_x
        new_y = self.pos().y() + offset_y

        # Clamp to screen working area.
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            new_x = max(avail.left(), min(new_x, avail.right() - self._size_px))
            new_y = max(avail.top(), min(new_y, avail.bottom() - self._size_px))

        new_hex = CellWindow(self._branding, catalog_path=self._catalog_path)
        new_hex.move_to(new_x, new_y)
        new_hex.show()
        _log(
            f"Spawned new hex {new_hex._id} at ({new_x},{new_y}) "
            f"catalog={self._catalog_path!r}"
        )

        # Wire it to the SnapEngine if one is running.  V3 renamed the
        # entry-point module from main.py to ring_main.py, so import
        # from scriptree.shell.ring_main (V2 used scriptree.shell.main).
        try:
            from scriptree.shell.ring_main import _wire_hex_to_snap
            _wire_hex_to_snap(new_hex)
            _log(f"Wired new hex {new_hex._id[:8]} to SnapEngine")
        except Exception as exc:  # noqa: BLE001
            _log(
                f"Could not wire new hex {new_hex._id[:8]} to SnapEngine: "
                f"{exc!r} — drag-snap will not engage for this cell"
            )

    def _close_this(self) -> None:
        """Close this hexagon. If it's the last one, quit the app.

        If this hex is a source of a master, close the master too.
        """
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()

        # Close any master that has this hex as a source.
        masters_to_close = [
            m for m in registry.masters()
            if m.source_a_id == self._id or m.source_b_id == self._id
        ]
        for master in masters_to_close:
            _log(f"Closing master {master._id} because source {self._id} closed")
            registry.masterDespawned.emit(master._id)
            master.close()

        # Check if this is the last non-master hex.
        standalones = registry.standalones()
        is_last = len(standalones) <= 1 and self in standalones

        self.close()

        if is_last:
            _log("Last hexagon closed — quitting application")
            QApplication.quit()

    # ------------------------------------------------------------------
    # Role-aware close + exit handlers (right-click menu)
    # ------------------------------------------------------------------

    def _close_ring_undock_all(self) -> None:
        """Master-cell action: destroy the master and let its member
        cells revert to standalones.

        Members keep their positions and catalogs; only the master is
        gone, plus the dock relationship.  Equivalent to "Disband
        group" but framed in user-facing language: "close ring".
        """
        from scriptree.shell.cell_registry import CellRegistry
        if self.role != "master":
            _log("_close_ring_undock_all on non-master — falling back to _close_this")
            self._close_this()
            return
        registry = CellRegistry.instance()
        # Iterate a copy of member ids so we can release relationships
        # without mutating during iteration.
        member_ids = list((self._members or {}).keys())
        for mid in member_ids:
            member = registry.get(mid)
            if member is None:
                continue
            # Clear the member's link back to this master so it
            # behaves as a standalone again.
            member._group_master_id = None
            member._docked_to.discard(self._id)
        registry.masterDespawned.emit(self._id)
        _log(
            f"Closed ring {self._id[:8]} — {len(member_ids)} member(s) "
            f"reverted to standalone"
        )
        self.close()

    def _close_all_related(self) -> None:
        """Master-cell action: close the master AND all its member cells.

        Use case: "I'm done with this whole group of tools — make it
        all go away."  After this, only cells that weren't members of
        the ring remain.  If the entire desktop becomes empty, quit.
        """
        from scriptree.shell.cell_registry import CellRegistry
        if self.role != "master":
            _log("_close_all_related on non-master — falling back to _close_this")
            self._close_this()
            return
        registry = CellRegistry.instance()
        member_ids = list((self._members or {}).keys())
        _log(
            f"Closing ring + members: master={self._id[:8]} "
            f"+ {len(member_ids)} member(s)"
        )
        # Close members first so the master's masterDespawned doesn't
        # try to revert them to standalones mid-tear-down.
        for mid in member_ids:
            member = registry.get(mid)
            if member is None:
                continue
            try:
                member.close()
            except Exception as exc:  # noqa: BLE001
                _log(f"  member close failed for {mid[:8]}: {exc!r}")
        registry.masterDespawned.emit(self._id)
        self.close()
        # If we just emptied the desktop, quit.
        if not registry.standalones() and not registry.masters():
            _log("All cells closed via 'close all related' — quitting")
            QApplication.quit()

    def _exit_all(self) -> None:
        """Close every cell ScripTreeRing knows about and quit.

        This is the "fire and exit" option — the same effect as
        clicking the X on each cell in turn, but in one click.
        """
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()
        all_cells = list(registry.standalones()) + list(registry.masters())
        _log(f"Exit all: closing {len(all_cells)} cell(s)")
        for cell in all_cells:
            try:
                cell.close()
            except Exception as exc:  # noqa: BLE001
                _log(f"  cell.close() failed for {getattr(cell, '_id', '?')[:8]}: {exc!r}")
        QApplication.quit()

    def _open_settings_dialog(self) -> None:
        """Open (or raise) the modeless Settings dialog."""
        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(self)

        if not self._settings_dialog.isVisible():
            dlg_pos = self.mapToGlobal(QPoint(self.width() + 8, 0))
            self._settings_dialog.move(dlg_pos)
            self._settings_dialog.show()
        else:
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()

    def _open_preferences_dialog(self) -> None:
        """Open the modal app-wide Preferences dialog."""
        # parent=None: PreferencesDialog.__init__ already forces None, but be
        # explicit here too so the call site is not misleading.
        dlg = PreferencesDialog(self._branding, parent=None)
        dlg.exec()

    # ------------------------------------------------------------------
    # Edge-fold: auto-hide positioned members that go off-screen
    # ------------------------------------------------------------------

    def _check_edge_fold(self) -> None:
        """Evaluate which positioned members should be auto-hidden due to
        being off-screen, and update their visibility + _auto_hidden set.

        Called from moveEvent (every master drag step) and from load_ring
        immediately after members are placed.

        Hide threshold: a member is auto-hidden when MORE THAN HALF of its
        bounding box is outside the available geometry of the screen that
        contains the master.  "More than half" means the overlap between the
        member rect and the available rect is less than half the member area.

        The member's preferred position stored in _members is NEVER changed
        by this method â€” edge-fold is a transient view state only.
        """
        if self.role != "master" or not self._positioned:
            return

        from scriptree.shell.cell_registry import CellRegistry
        from PySide6.QtGui import QGuiApplication

        registry = CellRegistry.instance()
        app_inst = QGuiApplication.instance()
        if app_inst is None:
            return

        # Determine the screen's available rect.
        screen = app_inst.screenAt(self.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()

        badge_changed = False
        for member_id in list(self._positioned):
            member = registry.get(member_id)
            if member is None:
                continue

            # Member bounding box at its CURRENT screen position.
            sz = member._size_px
            mx = member.pos().x()
            my = member.pos().y()
            member_rect = QRect(mx, my, sz, sz)

            # Intersection area with available geometry.
            inter = member_rect.intersected(avail)
            member_area = sz * sz
            inter_area = inter.width() * inter.height() if not inter.isEmpty() else 0

            more_than_half_off = inter_area < (member_area / 2)

            if more_than_half_off:
                # Should be auto-hidden.
                if member_id not in self._auto_hidden:
                    self._auto_hidden.add(member_id)
                    member.setVisible(False)
                    badge_changed = True
                    _log(
                        f"_check_edge_fold: auto-hiding {member_id[:8]} "
                        f"(inter_area={inter_area} < {member_area/2:.0f})"
                    )
            else:
                # Should be visible.
                if member_id in self._auto_hidden:
                    self._auto_hidden.discard(member_id)
                    member.setVisible(True)
                    badge_changed = True
                    _log(
                        f"_check_edge_fold: restoring {member_id[:8]} "
                        f"(inter_area={inter_area} >= {member_area/2:.0f})"
                    )

        if badge_changed:
            self.update()  # repaint badge

    def _clamp_to_screen(self, raw_pos: QPoint) -> QPoint:
        """Clamp a prospective window top-left to the containing screen's
        available geometry.

        Bug 2 (clock-area crash) defensive fix: when a hex is dragged into the
        system-tray / clock area the cursor can report a position that falls
        outside the availableGeometry() of every screen (the tray strip itself
        is not part of the available area).  Without clamping, raw arithmetic
        on that position can produce out-of-bounds values that trip Qt's
        geometry machinery or confuse the shake detector.

        Strategy:
        1. Find the screen that contains raw_pos.
        2. If none, fall back to the primary screen.
        3. Clamp the window top-left so the window stays inside that screen's
           availableGeometry (accounts for taskbar and tray area).
        4. If no screen is found at all (no displays), return raw_pos unchanged
           so we do not silently freeze dragging.
        """
        from PySide6.QtGui import QGuiApplication

        app_inst = QGuiApplication.instance()
        screen = None
        if app_inst is not None:
            try:
                screen = app_inst.screenAt(raw_pos)
            except Exception as _e:
                _log(f"_clamp_to_screen: screenAt raised {_e!r} â€” falling back to primary")

        if screen is None:
            screen = QGuiApplication.primaryScreen() if app_inst is not None else None

        if screen is None:
            return raw_pos  # no display info â€” pass through unclamped

        avail = screen.availableGeometry()
        max_x = avail.right()  - self._size_px
        max_y = avail.bottom() - self._size_px
        clamped_x = max(avail.left(), min(raw_pos.x(), max_x))
        clamped_y = max(avail.top(),  min(raw_pos.y(), max_y))

        if clamped_x != raw_pos.x() or clamped_y != raw_pos.y():
            _log(
                f"_clamp_to_screen: clamped ({raw_pos.x()},{raw_pos.y()}) â†’ "
                f"({clamped_x},{clamped_y}) avail={avail.getRect()} id={self._id[:8]}"
            )

        return QPoint(clamped_x, clamped_y)

    # ------------------------------------------------------------------
    # Harness-driveable public hooks (ADR-001 Â§harness-driveable contract)
    # These are PRODUCTION methods â€” real input handlers delegate to them.
    # They are NOT gated by any build flag.
    # ------------------------------------------------------------------

    def move_to(self, x: int, y: int) -> None:
        """Move the window to logical screen coordinates (x, y).

        Identical effect to a user drag-end at that position.
        Fires CellRegistry.hexagonMoved (via moveEvent).
        """
        self.move(x, y)

    def click(self, mode: Literal["single", "double", "right", "double-right"] = "single") -> None:
        """Programmatically fire the same handler a real click would.

        mode:
            "single"       â€” single left-click (tool launch in standalone mode,
                             OR collapse/expand toggle when role == 'master').
            "double"       â€” double left-click (lock-open tree view in standalone
                             mode, OR open merged tree when role == 'master').
            "right"        â€” single right-click; opens the context menu at window centre.
            "double-right" â€” double right-click; opens the composite editor for ALL
                             roles (standalone and master).  For standalones this is
                             identical to double-left (both call show_composite_for).

        Click-mode contract (sacred â€” per menu-engineer.md hard rule 1):
            standalone single         â†’ open tree in standalone mode.
            standalone double (1st)   â†’ open tree in lock-open mode; _locked_open=True.
            standalone double (2nd)   â†’ close the open menu; _locked_open=False.
            standalone double-right   â†’ show_composite_for(self) [same as double-left].
            master single             â†’ toggle collapse/expand.
            master double             â†’ open merged tree (lock-open path).
            master double-right       â†’ open composite editor.
            right (all roles)         â†’ context menu (unchanged).

        Note: for standalones, double-left and double-right are currently equivalent.
        This redundancy is intentional â€” user confirmed "double right clicking any of
        the hexes should do the same thing."  Future disambiguation (e.g. standalone
        double-right = open composite for self only, double-left = lock-open tree)
        can be added without breaking the master contract.

        Per ADR-001 Â§harness-driveable contract: real mouse handlers delegate
        here.  This IS the one code path â€” not a test-only copy.
        Per menu-engineer dispatch phase1-tree-view-and-click-semantics.
        """
        if mode == "right":
            centre = self.mapToGlobal(
                QPoint(self.width() // 2, self.height() // 2)
            )
            self._show_context_menu(centre)

        elif mode == "single":
            # Master single-click â†’ collapse/expand toggle, but DEFERRED so
            # that a double-click has a chance to cancel it first.
            # Qt always fires mouseReleaseEvent (â†’ click("single")) before
            # mouseDoubleClickEvent (â†’ click("double")), so without the timer
            # the slide fires on every first click of a double-click sequence.
            if self.role == "master":
                if self._pending_master_single_click_timer is not None:
                    # A timer is already running (rapid repeated single-clicks).
                    # Ignore the extra signal â€” the pending fire will still happen.
                    _log(
                        f"click(single) master id={self._id[:8]} "
                        "â€” deferred fire already pending; ignoring"
                    )
                    return
                from PySide6.QtCore import QTimer as _QTimer
                interval = QApplication.doubleClickInterval()
                self._pending_master_single_click_timer = _QTimer(self)
                self._pending_master_single_click_timer.setSingleShot(True)
                self._pending_master_single_click_timer.timeout.connect(
                    self._fire_pending_master_single_click
                )
                self._pending_master_single_click_timer.start(interval)
                _log(
                    f"click(single) master id={self._id[:8]} "
                    f"â€” deferred {interval} ms waiting for possible double-click"
                )
                return

            # Standalone path: toggle popup menu on/off.
            #
            # User contract (2026-05-07): "a single click brings up
            # their tool menu, clicking on the cell again hides it,
            # clicking on another cell current behaviour good."
            #
            # Implementation: when the popup is dismissed by an
            # outside-click on this cell, Qt's QMenu mechanism closes
            # the menu AND dispatches the click to this widget — which
            # would re-open the popup unless we suppress it.  We record
            # the close time on `_tree_popup_closed_at` (set inside
            # tree_popup.show_tree_popup_for via aboutToHide) and skip
            # the re-open if the click arrives within a short window.
            if self._locked_open:
                _log(
                    f"click(single) id={self._id} — lock-open active; "
                    "ignoring single-click per click-mode contract"
                )
                return

            import time as _time
            last_close = getattr(self, "_tree_popup_closed_at", 0.0)
            if _time.monotonic() - last_close < 0.25:
                # Menu just closed because user clicked this cell to
                # dismiss it.  Don't re-open.  The next click will
                # be after the 250 ms window and will open the menu
                # again as expected.
                _log(
                    f"click(single) id={self._id[:8]} — popup just "
                    f"closed; treating second click as toggle-hide"
                )
                return

            _log(f"click(single) id={self._id} — opening tree standalone")
            try:
                from scriptree.shell.v1_launcher import show_tree_for
                show_tree_for(self, mode="standalone")
            except Exception as exc:   # noqa: BLE001
                _log(f"click(single): menu import/show failed: {exc!r} — continuing")

        elif mode == "double":
            # Cancel any pending master single-click before acting on double.
            # This is the normal path: mouseReleaseEvent fired click("single")
            # (which armed the timer), then mouseDoubleClickEvent fires click("double")
            # within the doubleClickInterval â€” we cancel the deferred toggle so the
            # slide never happens and only the double-click action executes.
            if self._pending_master_single_click_timer is not None:
                self._pending_master_single_click_timer.stop()
                self._pending_master_single_click_timer.deleteLater()
                self._pending_master_single_click_timer = None
                _log(f"click(double) id={self._id[:8]} â€” cancelled pending master single-click")

            # Master double-LEFT-click  → in-process popup menu with each
            #                              member's catalog as a sub-folder.
            # Master double-RIGHT-click → V1 full editor with merged tree.
            # Standalone double-LEFT-click → lock-open tree (V1 editor).
            #
            # Per user direction (2026-05-07): "A double left click
            # should bring up a menu with each of the attached cell's
            # menus each in its own sub-folder on the menu, and
            # double-right click should bring them up in the full
            # editor in the same sub-folder style."
            if not self._locked_open:
                if self.role == "master":
                    # Popup-style menu — same builder as single-click,
                    # already produces sub-folders per member.
                    _log(
                        f"click(double) master id={self._id[:8]} "
                        f"— showing master popup with member sub-folders"
                    )
                    try:
                        from scriptree.shell.tree_popup import show_tree_popup_for
                        show_tree_popup_for(self)
                    except Exception as exc:   # noqa: BLE001
                        _log(
                            f"click(double) master: popup failed: {exc!r}"
                        )
                else:
                    _log(
                        f"click(double) standalone id={self._id} "
                        f"— entering lock-open"
                    )
                    self._locked_open = True
                    try:
                        from scriptree.shell.v1_launcher import show_tree_for
                        show_tree_for(self, mode="lock-open")
                    except Exception as exc:   # noqa: BLE001
                        _log(
                            f"click(double): menu import/show failed: "
                            f"{exc!r} — resetting lock"
                        )
                        self._locked_open = False
            else:
                # Second double-click: unlock â€” close the open menu and clear flag.
                _log(f"click(double) id={self._id} â€” unlock; closing lock-open tree")
                self._locked_open = False
                if self._menu_window is not None:
                    try:
                        self._menu_window.close()
                    except Exception:   # noqa: BLE001
                        pass
                    self._menu_window = None

        elif mode == "double-right":
            # Cancel any pending master single-click before acting on double-right.
            if self._pending_master_single_click_timer is not None:
                self._pending_master_single_click_timer.stop()
                self._pending_master_single_click_timer.deleteLater()
                self._pending_master_single_click_timer = None
                _log(f"click(double-right) id={self._id[:8]} â€” cancelled pending master single-click")

            # double-right-click: open composite editor for ALL hex roles.
            #
            # Decision tree:
            #   master     + not locked â†’ lock-open composite editor (show_composite_for)
            #   master     + locked     â†’ unlock and close
            #   standalone + not locked â†’ same as double-LEFT for standalones
            #                             (show_composite_for(self)); both LEFT and RIGHT
            #                             do the same thing for standalones â€” that is
            #                             intentional and the user confirmed it is fine.
            #   standalone + locked     â†’ unlock and close
            #
            # Previously standalone double-right was a no-op.  Changed per user feedback:
            # "double right clicking any of the hexes should do the same thing."
            _log(f"click(double-right) id={self._id} role={self.role}")
            if not self._locked_open:
                _log(
                    f"click(double-right) {self.role} {self._id[:8]} "
                    "— opening composite editor"
                )
                self._locked_open = True
                try:
                    # Route via show_composite_for so master cells get
                    # the **merged tree** (sub-folder per member) in
                    # V1's editor, even when no .scriptreering file
                    # has been saved yet.  show_composite_for handles
                    # the masters-vs-standalones split itself.
                    from scriptree.shell.v1_launcher import show_composite_for
                    show_composite_for(self)
                except Exception as exc:   # noqa: BLE001
                    _log(
                        f"click(double-right): menu import/show failed: {exc!r} "
                        "— resetting lock"
                    )
                    self._locked_open = False
            else:
                # Already in lock-open: treat second double-right as unlock.
                _log(
                    f"click(double-right) {self.role} {self._id[:8]} "
                    "â€” unlocking composite editor"
                )
                self._locked_open = False
                if self._menu_window is not None:
                    try:
                        self._menu_window.close()
                    except Exception:   # noqa: BLE001
                        pass
                    self._menu_window = None

        else:
            _log(f"click: unknown mode {mode!r} ignored")

    # ------------------------------------------------------------------
    # Master collapse / expand (Bug 3)
    # ------------------------------------------------------------------

    def _animate_to(
        self, target_pos: QPoint, duration_ms: int = 250
    ) -> QPropertyAnimation:
        """Create and return a QPropertyAnimation that slides self to target_pos.

        Uses QEasingCurve.OutCubic for a smooth deceleration.  The caller is
        responsible for connecting finished() and for keeping a reference to
        the animation (store on the hex so GC doesn't collect it mid-flight).
        """
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(duration_ms)
        anim.setStartValue(self.pos())
        anim.setEndValue(target_pos)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        return anim

    def _fire_pending_master_single_click(self) -> None:
        """Timer callback: the double-click window elapsed with no double-click.

        Clears the pending-timer reference and commits the collapse/expand toggle
        that click("single") deferred.  If click("double") or click("double-right")
        arrived first they would have stopped the timer; this method is never called
        in that case, so no double-click action is clobbered.
        """
        _log(
            f"_fire_pending_master_single_click id={self._id[:8]} "
            "â€” double-click window elapsed; committing collapse/expand"
        )
        self._pending_master_single_click_timer = None
        self._toggle_collapse()

    def _toggle_collapse(self) -> None:
        """Toggle the collapsed/expanded state of this master hexagon (Bug 3).

        Called from click(mode='single') when role == 'master'.
        Ignores the click if an animation is currently in flight.
        """
        if self._collapse_state in ("collapsing", "expanding"):
            _log(f"_toggle_collapse {self._id}: animation in flight â€” click ignored")
            return

        if self._collapse_state == "expanded":
            self._start_collapse()
        elif self._collapse_state == "collapsed":
            self._start_expand()

    def _start_collapse(self) -> None:
        """Animate ALL group members toward master centre (Amendment 2).

        Iterates self._members regardless of positioned/separated status.
        Members animate from their current visible position to master.pos().
        """
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()

        # Build list of live member windows.
        members = [
            registry.get(mid) for mid in self._members
            if registry.get(mid) is not None
        ]
        if not members:
            _log(f"_start_collapse {self._id}: no member windows found")
            return

        self._collapse_state = "collapsing"
        target = self.pos()

        pending = [m._id for m in members]

        def _make_finish_handler(mid: str):
            def _on_finished():
                if mid in pending:
                    pending.remove(mid)
                m = registry.get(mid)
                if m is not None:
                    m.setVisible(False)
                self._collapse_animations.pop(mid, None)
                if not pending:
                    self._collapse_state = "collapsed"
                    _log(f"_toggle_collapse {self._id}: fully collapsed")
            return _on_finished

        for m in members:
            # Before animating, record current position as the preferred restore
            # position (so expand goes back to where the member is NOW, not
            # wherever it was when it first joined).
            self._members[m._id] = QPoint(m.pos())
            anim = m._animate_to(target, duration_ms=250)
            anim.finished.connect(_make_finish_handler(m._id))
            self._collapse_animations[m._id] = anim
            anim.start()

        _log(f"_start_collapse {self._id}: animating {len(members)} member(s) to master pos")

    def _start_expand(self) -> None:
        """Animate ALL group members back to their stored positions (Amendment 2).

        Iterates self._members regardless of positioned/separated status.
        Each member animates from master.pos() to its stored _members[id] position.

        Edge-fold interaction:
        - _auto_hidden is cleared before animating so setVisible(True) is not
          fought by any lingering auto-hide state.
        - After ALL animations finish, _check_edge_fold() is called once to
          re-evaluate visibility based on the current master position.  Members
          whose preferred positions are still off-screen will be immediately
          re-hidden; those with room will stay visible.
        """
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()

        members = [
            registry.get(mid) for mid in self._members
            if registry.get(mid) is not None
        ]
        if not members:
            _log(f"_start_expand {self._id}: no member windows found")
            return

        # Clear auto-hidden state before expansion so setVisible(True) is clean.
        self._auto_hidden.clear()
        self.update()  # remove badge immediately

        self._collapse_state = "expanding"

        pending = [m._id for m in members]

        def _make_finish_handler(mid: str):
            def _on_finished():
                if mid in pending:
                    pending.remove(mid)
                self._collapse_animations.pop(mid, None)
                if not pending:
                    self._collapse_state = "expanded"
                    _log(f"_toggle_collapse {self._id}: fully expanded")
                    # Re-evaluate edge-fold at the new (restored) positions.
                    self._check_edge_fold()
            return _on_finished

        for m in members:
            restore = self._members.get(m._id)
            if restore is None:
                restore = self.pos() + QPoint(self._size_px + 8, 0)
            # Make member visible and start from master position, then animate out.
            m.move(self.pos())
            m.setVisible(True)
            anim = m._animate_to(restore, duration_ms=250)
            anim.finished.connect(_make_finish_handler(m._id))
            self._collapse_animations[m._id] = anim
            anim.start()

        _log(f"_start_expand {self._id}: animating {len(members)} member(s) to stored positions")

    def _get_source_windows(self, registry) -> list["CellWindow"]:
        """Return ALL member CellWindow objects for this master.

        Uses _members keys (Amendment 2 authoritative set). Kept for any
        residual callers; _start_collapse/_start_expand now iterate _members
        directly.
        """
        sources = []
        for sid in self._members:
            w = registry.get(sid)
            if w is not None:
                sources.append(w)
        return sources

    def _shift_home_positions(self, delta_x: int, delta_y: int) -> None:
        """Translate ALL stored member positions by (delta_x, delta_y).

        This is the old alias â€” kept for any residual callers.
        Under Amendment 2 this means translating self._members (which IS
        self._home_positions since they share the same dict object).
        """
        self._shift_positioned_members(delta_x, delta_y, all_members=True)

    def _shift_positioned_members(
        self, delta_x: int, delta_y: int, *, all_members: bool = False
    ) -> None:
        """Translate stored preferred positions in _members.

        If all_members=False (default): only update _positioned members.
        If all_members=True: update every member in _members.

        Separated members (not in _positioned) are NOT moved on screen, but
        their stored position is only updated when all_members=True (used by
        _shift_home_positions shim for full-group collapse target tracking).
        """
        target_ids = self._members.keys() if all_members else self._positioned
        self._members.update({
            hid: QPoint(self._members[hid].x() + delta_x, self._members[hid].y() + delta_y)
            for hid in target_ids
            if hid in self._members
        })

    def dock_with(self, other: "CellWindow") -> None:
        """Programmatically edge-dock this hex with `other`.

        Uses the honeycomb-strict snap model (Rule 2): places `self` at the
        nearest honeycomb-neighbour slot of `other`.  Cross-shape/orientation
        pairs do not snap (Rule 3).  Vertex snap is gone.

        After moving, spawns a master hexagon (same path as drag-release).
        """
        import math as _math
        from scriptree.shell.snap_engine import _neighbour_slot_centres

        # Rule 3 guard.
        if self._shape != other._shape or self._orientation != other._orientation:
            _log(
                f"dock_with: shape/orientation mismatch "
                f"({self._shape}/{self._orientation} vs "
                f"{other._shape}/{other._orientation}) â€” no snap"
            )
            return

        # Compute other's honeycomb-neighbour slot centres.
        other_geo = other.geometry()
        other_cx = other_geo.x() + other_geo.width()  / 2.0
        other_cy = other_geo.y() + other_geo.height() / 2.0

        slots = _neighbour_slot_centres(
            other_cx, other_cy,
            other._size_px, other._shape, other._orientation,
        )

        # Find nearest slot to self's centre.
        self_geo = self.geometry()
        self_cx = self_geo.x() + self_geo.width()  / 2.0
        self_cy = self_geo.y() + self_geo.height() / 2.0

        best_dist = float("inf")
        best_slot: tuple[float, float] | None = None
        for slot_cx, slot_cy in slots:
            d = _math.hypot(self_cx - slot_cx, self_cy - slot_cy)
            if d < best_dist:
                best_dist = d
                best_slot = (slot_cx, slot_cy)

        if best_slot is None:
            _log(f"dock_with: no slot found â€” should not happen")
            return

        new_x = round(best_slot[0] - self._size_px / 2)
        new_y = round(best_slot[1] - self._size_px / 2)
        self.move_to(new_x, new_y)
        _log(
            f"dock_with: {self._id[:8]} â†’ slot ({new_x},{new_y}) "
            f"dist={best_dist:.1f}px"
        )

        _try_spawn_master(self, other)

    def dump_state(self) -> dict:
        """Return a JSON-serialisable snapshot of current window state.

        Amendment 2 additions:
          - standalone: adds 'master_id' (str|None), 'docked_to' (list[str])
          - master: adds 'members' (list[str]), 'positioned' (list[str])
          - backwards-compat: 'dock_partners' still present (now a shim list).

        Edge-fold additions:
          - all hexes: adds 'visible' (bool) reflecting current Qt visibility.
          - master: adds 'auto_hidden' (list[str]) for harness inspection.
        """
        geo = self.geometry()
        state = {
            "id": self._id,
            "role": self.role,
            "geometry": {
                "x": geo.x(),
                "y": geo.y(),
                "w": geo.width(),
                "h": geo.height(),
            },
            "mode": "standalone",
            # Shim â€” empty in the new model; kept so harness code that reads it
            # doesn't crash (it just gets an empty list for non-master hexes).
            "dock_partners": list(self._dock_partners),
            "always_on_top": self._always_on_top,
            "shape": self._shape,
            "orientation": self._orientation,
            "size_px": self._size_px,
            "transparency": self._transparency,
            "catalog_path": self._catalog_path,
            # Edge-fold: transient view state.
            "visible": self.isVisible(),
        }
        if self.role == "master":
            state["source_ids"] = [self.source_a_id, self.source_b_id]
            state["all_source_ids"] = list(self._members.keys())   # shim alias
            # Amendment 2 canonical fields:
            state["members"] = list(self._members.keys())
            state["positioned"] = list(self._positioned)
            state["collapse_state"] = self._collapse_state
            # Edge-fold: auto-hidden member ids (transient, not serialised).
            state["auto_hidden"] = list(self._auto_hidden)
        else:
            # Standalone Amendment 2 fields.
            state["master_id"] = self._group_master_id
            state["docked_to"] = list(self._docked_to)
        return state


# ---------------------------------------------------------------------------
# Master-hexagon helper
# ---------------------------------------------------------------------------

def _honeycomb_master_pos(
    source_ids: set[str],
    hex_size: int,
    registry,
    screen_avail=None,
) -> tuple[int, int]:
    """Compute the master's top-left position in the natural honeycomb-tiling slot.

    Geometry derivation (flat-top hex inscribed in hex_size Ã— hex_size square):
      circumradius  R = hex_size / 2
      apothem       a = R * cos(30Â°) = R * sqrt(3)/2 = hex_size * sqrt(3) / 4
      flat-to-flat  = 2a = hex_size * sqrt(3) / 2   â† called flat_to_flat below

    For the master to sit flush ABOVE the source centroid (master bottom flat edge
    = source top flat edge):
      master_center_y + a = centroid_y - a
      master_center_y     = centroid_y - 2a = centroid_y - flat_to_flat
      master_top_left_y   = master_center_y - R = centroid_y - flat_to_flat - hex_size/2

    NOTE: centroid is computed from each source window's CENTRE (geometry().center()),
    not its top-left pos().  This is essential â€” using pos() shifts the centroid
    by R in both axes and causes an R-pixel overlap.

    The hex bounding boxes DO overlap by (R - a) = R(1 - sqrt(3)/2) â‰ˆ 0.134R pixels
    in each direction â€” this is expected and correct because the polygon corners are
    empty; only the flat edges matter.

    If placement above goes off-screen (cand_y_above < avail.top()), place below.

    Returns (top_left_x, top_left_y) ready to pass to move().
    """
    sources_in_reg = [
        registry.get(sid) for sid in source_ids
        if registry.get(sid) is not None and registry.get(sid).role != "master"
    ]
    if not sources_in_reg:
        return (100, 100)

    # Source centres (not top-left positions).
    cx_sum = sum(s.geometry().center().x() for s in sources_in_reg)
    source_center_ys = [s.geometry().center().y() for s in sources_in_reg]
    n = len(sources_in_reg)
    centroid_x = cx_sum / n

    # flat-to-flat distance = 2 Ã— apothem for a flat-top hex inscribed in hex_size.
    flat_to_flat = hex_size * math.sqrt(3) / 2  # â‰ˆ 0.866 Ã— hex_size
    #   apothem = flat_to_flat / 2 = hex_size * sqrt(3) / 4
    #
    # For flush placement: master_bottom_flat_edge = source_top_flat_edge
    #   master_center_y + apothem = source_center_y - apothem
    #   master_center_y = source_center_y - 2*apothem = source_center_y - flat_to_flat
    #
    # Key insight: use the UPPER source's center_y (min center_y) as the reference,
    # NOT the centroid.  The centroid approach produces overlap when sources are at
    # different y-positions (e.g. after an angled-edge dock), because the centroid_y
    # is BELOW the upper source's center_y, putting the master too low.

    # For "above": flush with the uppermost source (smallest center_y).
    upper_src_cy = min(source_center_ys)
    # For "below": flush with the lowermost source (largest center_y).
    lower_src_cy = max(source_center_ys)

    # Top-left candidates for above and below placement.
    cand_x = round(centroid_x - hex_size / 2)
    cand_y_above = round(upper_src_cy - flat_to_flat - hex_size / 2)
    cand_y_below = round(lower_src_cy + flat_to_flat - hex_size / 2)

    if screen_avail is not None:
        avail = screen_avail
        # Clamp x regardless.
        cand_x = max(avail.left(), min(cand_x, avail.right() - hex_size))
        # Prefer above; fall back to below if above goes off-screen.
        if cand_y_above >= avail.top():
            cand_y = max(avail.top(), cand_y_above)
        else:
            cand_y = min(cand_y_below, avail.bottom() - hex_size)
    else:
        # No screen info â€” prefer above, fall back to below if y < 0.
        cand_y = cand_y_above if cand_y_above >= 0 else cand_y_below

    return (cand_x, cand_y)


def _try_spawn_master(a: CellWindow, b: CellWindow) -> None:
    """Snap-commit handler: wire a and b into the group-association model.

    Amendment 2 decision tree (4 cases):
    â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    Case 1 â€” both standalone (no group):
        Spawn a fresh master. Both become members. Both go into _positioned.
        Master placed at the deterministic honeycomb cell adjacent to both.

    Case 2 â€” tgt (b) is in a group, src (a) is standalone:
        a joins b's master's group. master._members[a._id] = a.pos().
        a added to master._positioned (it just snapped into the cluster).
        a._group_master_id = master._id. Master does NOT move.

    Case 3 â€” src (a) is in a group, tgt (b) is standalone:
        b joins a's master's group. Same as Case 2 mirrored.

    Case 4 â€” both in DIFFERENT groups:
        a TRANSFERS from its current master to b's master.
        Remove a from old master's _members/_positioned.
        If old master drops below 2 members, close it.
        Add a to new master's _members/_positioned.
        a._group_master_id = new master._id.

    Case 5 â€” both in the SAME group:
        This is a positional re-snap (member moved and snapped back).
        Update master._members[a._id] = a.pos(), add a back to _positioned.
        No new master, no changes to membership.

    Rule: NEVER reposition an existing master (it stays where it is).
    Rule: a._docked_to and b._docked_to are updated to record adjacency.
    """
    from scriptree.shell.cell_registry import CellRegistry
    from PySide6.QtGui import QGuiApplication

    registry = CellRegistry.instance()

    # Defensive guard: masters are not honeycomb cells and cannot be wired as
    # group members.  SnapEngine._tick now filters them out at source, but if
    # a race or future code path delivers a master here, reject immediately
    # instead of recursing into Case 1/2/3/4 with a master object.
    if a.role == "master" or b.role == "master":
        _log(
            f"rejected master-of-master attempt: "
            f"a={a._id[:8]} role={a.role} b={b._id[:8]} role={b.role}"
        )
        return

    tgt_master_id = registry.master_of(b._id)
    src_master_id = registry.master_of(a._id)

    _log(
        f"_try_spawn_master: a={a._id[:8]} (master={src_master_id and src_master_id[:8]}) "
        f"b={b._id[:8]} (master={tgt_master_id and tgt_master_id[:8]})"
    )

    # ---- Case 5: both in same group ----------------------------------------
    if (
        tgt_master_id is not None
        and src_master_id is not None
        and tgt_master_id == src_master_id
    ):
        master = registry.get(tgt_master_id)
        if master is not None:
            master._members[a._id] = QPoint(a.pos())
            master._positioned.add(a._id)
            _update_docked_to(a, b, registry)
        _log(f"Case 5 (same group): {a._id[:8]} repositioned within group {tgt_master_id[:8]}")
        return

    # ---- Case 4: both in DIFFERENT groups -----------------------------------
    if tgt_master_id is not None and src_master_id is not None:
        old_master = registry.get(src_master_id)
        new_master = registry.get(tgt_master_id)
        if old_master is not None:
            old_master._members.pop(a._id, None)
            old_master._positioned.discard(a._id)
            old_master._dock_partners.discard(a._id)
        if new_master is not None:
            new_master._members[a._id] = QPoint(a.pos())
            new_master._positioned.add(a._id)
            new_master._dock_partners.add(a._id)
        a._group_master_id = tgt_master_id
        a._docked_to.clear()
        _update_docked_to(a, b, registry)
        a.update()  # Bug 5: refresh outline colour (now associated)
        _log(
            f"Case 4 (transfer): {a._id[:8]} from {src_master_id[:8]} "
            f"to {tgt_master_id[:8]}"
        )
        # Close old master if it now has fewer than 2 members.
        if old_master is not None:
            _check_master_validity(old_master, registry)
        return

    # ---- Case 2: tgt in group, src standalone ------------------------------
    if tgt_master_id is not None and src_master_id is None:
        master = registry.get(tgt_master_id)
        if master is not None:
            master._members[a._id] = QPoint(a.pos())
            master._positioned.add(a._id)
            master._dock_partners.add(a._id)
            a._group_master_id = tgt_master_id
            a._docked_to.clear()
            _update_docked_to(a, b, registry)
            a.update()  # Bug 5: refresh outline colour (now associated)
            if not master.isVisible():
                master.show()
        _log(f"Case 2 (src joins tgt group): {a._id[:8]} â†’ group {tgt_master_id[:8]}")
        return

    # ---- Case 3: src in group, tgt standalone ------------------------------
    if src_master_id is not None and tgt_master_id is None:
        master = registry.get(src_master_id)
        if master is not None:
            master._members[b._id] = QPoint(b.pos())
            master._positioned.add(b._id)
            master._dock_partners.add(b._id)
            b._group_master_id = src_master_id
            b._docked_to.clear()
            _update_docked_to(a, b, registry)
            b.update()  # Bug 5: refresh outline colour (now associated)
            if not master.isVisible():
                master.show()
        _log(f"Case 3 (tgt joins src group): {b._id[:8]} â†’ group {src_master_id[:8]}")
        return

    # ---- Case 1: both standalone â€” fresh master -----------------------------
    _log(f"Case 1 (fresh master): spawning for {a._id[:8]} + {b._id[:8]}")

    # Deterministic pairwise master_id (stable across dock/undock/re-dock).
    master_id = CellRegistry.master_id(a._id, b._id)

    # Compute master position: honeycomb cell adjacent to BOTH a and b.
    from scriptree.shell.snap_engine import _neighbour_slot_centres as _nsc

    a_geo = a.geometry()
    b_geo = b.geometry()
    a_cx = a_geo.x() + a_geo.width()  / 2.0
    a_cy = a_geo.y() + a_geo.height() / 2.0
    b_cx = b_geo.x() + b_geo.width()  / 2.0
    b_cy = b_geo.y() + b_geo.height() / 2.0

    _TOL = 0.5
    a_slots = _nsc(a_cx, a_cy, a._size_px, a._shape, a._orientation)
    b_slots = _nsc(b_cx, b_cy, b._size_px, b._shape, b._orientation)

    adjacent_to_both: list[tuple[float, float]] = []
    for (ax, ay) in a_slots:
        for (bx, by) in b_slots:
            if abs(ax - bx) < _TOL and abs(ay - by) < _TOL:
                adjacent_to_both.append((ax, ay))

    hex_size = a._size_px
    screen = QGuiApplication.primaryScreen()
    avail = screen.availableGeometry() if screen is not None else None

    if adjacent_to_both:
        def _has_clearance(cx: float, cy: float) -> bool:
            if avail is None:
                return cy - hex_size / 2 >= 0
            tl_x = cx - hex_size / 2
            tl_y = cy - hex_size / 2
            return (
                tl_x >= avail.left()
                and tl_y >= avail.top()
                and tl_x + hex_size <= avail.right()
                and tl_y + hex_size <= avail.bottom()
            )

        with_clearance = [p for p in adjacent_to_both if _has_clearance(*p)]
        if with_clearance:
            chosen_cx, chosen_cy = min(with_clearance, key=lambda p: (p[1], p[0]))
        else:
            def _off_screen_area(cx: float, cy: float) -> float:
                if avail is None:
                    return 0.0
                tl_x = cx - hex_size / 2
                tl_y = cy - hex_size / 2
                over_x = max(0.0, (tl_x + hex_size) - avail.right()) + max(0.0, avail.left() - tl_x)
                over_y = max(0.0, (tl_y + hex_size) - avail.bottom()) + max(0.0, avail.top() - tl_y)
                return over_x + over_y
            chosen_cx, chosen_cy = min(adjacent_to_both, key=lambda p: _off_screen_area(*p))
        cand_x = round(chosen_cx - hex_size / 2)
        cand_y = round(chosen_cy - hex_size / 2)
    else:
        _log(f"_try_spawn_master: no adjacent-to-both cell â€” using centroid fallback")
        cand_x, cand_y = _honeycomb_master_pos({a._id, b._id}, hex_size, registry, avail)

    # Create the master.
    master = CellWindow(
        a._branding,
        role="master",
        source_a_id=a._id,
        source_b_id=b._id,
        hexagon_id=master_id,
    )
    master.move_to(cand_x, cand_y)

    # Wire group membership.
    master._members = {
        a._id: QPoint(a.pos()),
        b._id: QPoint(b.pos()),
    }
    # _home_positions IS _members (same dict alias set in __init__).
    master._positioned = {a._id, b._id}
    master._dock_partners = {a._id, b._id}   # shim
    master._collapse_state = "expanded"

    a._group_master_id = master_id
    b._group_master_id = master_id
    a._docked_to.clear()
    b._docked_to.clear()
    _update_docked_to(a, b, registry)
    # Bug 5: refresh outline colour â€” both are now associated; green â†’ normal.
    a.update()
    b.update()

    # Shim: update _dock_partners on sources so SnapEngine's dock_group_of
    # (which still uses the registry's shim) excludes them from snap candidates.
    a._dock_partners.add(master_id)
    b._dock_partners.add(master_id)

    master.show()
    _log(f"Master spawned: {master_id[:20]} at ({cand_x},{cand_y})")
    registry.masterSpawned.emit(master_id, a._id, b._id)


def _update_docked_to(a: CellWindow, b: CellWindow, registry) -> None:
    """Record the bidirectional positional adjacency between a and b.

    Both a._docked_to and b._docked_to get each other's id added.
    """
    a._docked_to.add(b._id)
    b._docked_to.add(a._id)


def _check_undock(moved_hex: CellWindow) -> None:
    """Called when a hex moves; checks if it has drifted far enough to leave cluster.

    Amendment 2: uses _docked_to (positional adjacency) rather than _dock_partners.
    Drift detection removes the hex from the cluster (_docked_to, master._positioned)
    but does NOT remove it from the group (_group_master_id, master._members).

    The master is closed only when len(master._members) < 2 via
    _check_master_validity (not here â€” drift just breaks position, not membership).
    """
    from scriptree.shell.cell_registry import CellRegistry

    registry = CellRegistry.instance()
    hex_cfg = moved_hex._branding.get("hexagon", {})
    snap_dist = hex_cfg.get("snapDistancePx", 18)
    undock_threshold = snap_dist * 2 + moved_hex._size_px

    peers_to_drop: list[str] = []
    for peer_id in list(moved_hex._docked_to):
        peer = registry.get(peer_id)
        if peer is None:
            peers_to_drop.append(peer_id)
            continue
        mg = moved_hex.geometry()
        pg = peer.geometry()
        dist = math.hypot(
            mg.center().x() - pg.center().x(),
            mg.center().y() - pg.center().y(),
        )
        if dist > undock_threshold:
            peers_to_drop.append(peer_id)

    if not peers_to_drop:
        return

    for peer_id in peers_to_drop:
        moved_hex._docked_to.discard(peer_id)
        peer = registry.get(peer_id)
        if peer is not None:
            peer._docked_to.discard(moved_hex._id)

    # If now fully disconnected from all positional peers, remove from master._positioned.
    if not moved_hex._docked_to:
        mid = moved_hex._group_master_id
        if mid is not None:
            master = registry.get(mid)
            if master is not None:
                master._positioned.discard(moved_hex._id)
                # Update stored position to wherever the member ended up.
                master._members[moved_hex._id] = QPoint(moved_hex.pos())
                master._dock_partners.discard(moved_hex._id)
        moved_hex._dock_partners.clear()
        _log(
            f"_check_undock: {moved_hex._id[:8]} fully left cluster "
            f"(group membership preserved: master={mid and mid[:8]})"
        )


def _check_master_validity(master: CellWindow, registry) -> None:
    """Close the master if fewer than 2 members remain in its group (Amendment 2).

    Uses len(master._members) â€” not dock_partners, not home_positions count.
    Called after a member explicitly leaves the group (not on cluster break-free,
    which preserves membership).
    """
    if master.role != "master":
        return

    member_count = len(master._members)

    _log(
        f"_check_master_validity {master._id[:8]}: "
        f"member_count={member_count} (need >= 2)"
    )

    if member_count < 2:
        # Clear group membership for any remaining members.
        from scriptree.shell.cell_registry import CellRegistry
        reg = CellRegistry.instance()
        for member_id in list(master._members.keys()):
            member = reg.get(member_id)
            if member is not None:
                member._group_master_id = None
                member._docked_to.clear()
                member._dock_partners.clear()
                member.update()  # Bug 5: refresh outline (now unassociated â†’ green)
        master._members.clear()
        master._positioned.clear()
        master._dock_partners.clear()
        if master.isVisible():
            master.hide()
            _log(f"Master {master._id[:8]} closed â€” only {member_count} member(s) remain")
            reg.masterDespawned.emit(master._id)

