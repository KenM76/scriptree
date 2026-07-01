"""
cell_window.py — CellWindow, the branded floating hexagonal launcher.

## For humans

Architecture: see docs/architecture/ADR-001-overlay-and-docking.md
Platform target: Win11 (Phase 0/1 demo). Mac/Linux behaviour: see
ADR-001 §cross-platform.

Coordinate convention
---------------------
All sizes and positions passed to setMask / resize / move are in
*logical* pixels (device-independent units).  Qt scales them to
physical pixels via devicePixelRatio internally.  We do NOT multiply by
devicePixelRatio ourselves — that double-scales.

## For maintainers / LLMs

- ``WA_DeleteOnClose`` is FALSE — the ``CellRegistry`` owns window
  lifetime. ``closeEvent`` calls ``CellRegistry.instance().unregister``
  (emits ``hexagonClosed``). Never set DeleteOnClose True; the registry
  would dereference freed C++ objects.
- Membership model (Amendment 2) lives in private sets/dicts:
  ``_members: dict[id, QPoint]`` (master's HOME slots — authoritative
  preferred positions), ``_positioned`` (members rigidly translated on
  master drag), ``_docked_to`` / ``_dock_partners`` (cluster adjacency
  / SnapEngine shim), ``_group_master_id`` (member→master link, RETAINED
  on break-free, CLEARED on shake/full-unassociate). ``cell_registry``
  reads all of these by name — renaming any requires updating that file.
- HOME vs widget position: ``_members[mid]`` is HOME. A surgical repack
  (``_repack_members(fixed=...)``, ``fixed is not None``) moves the
  widget to a temp slot but MUST NOT overwrite ``_members[mid]`` — that
  is the v0.3.17 contract that lets a member return HOME when the master
  moves back on-screen. Canonical repack (``fixed is None``) DOES update
  ``_members``. Don't collapse the two modes.
- ``moveEvent`` re-emits ``CellRegistry.hexagonMoved`` every move and,
  during a master drag, rigidly translates ``_positioned`` members
  guarded by the module-global ``_GROUP_MOVE_IN_PROGRESS`` set (reentry
  guard — a member's own moveEvent must not re-trigger group move).
  ``_reflow_members_after_master_move`` runs only on drag END (mouse
  release), not per-move (per-move would be O(members) math every pixel).
- Single ``_last_move_log_time`` field is shared by THREE throttled log
  sites at different intervals (drag 1.0 s, moveEvent 0.1 s, group-move
  1.0 s). They stomp each other's timestamp; the group-move 1.0 s branch
  is effectively dead because moveEvent's 0.1 s site reset the field
  microseconds earlier in the same call. This only affects log verbosity,
  not behaviour — but don't trust these logs to be evenly spaced.
- Right-click double-detection is manual (Qt only synthesises
  doubleClick for the left button): ``_right_click_timer`` (single-shot,
  ``QApplication.doubleClickInterval()``) fires ``_fire_single_right_click``
  unless a 2nd right-press arrives first. Left single/double: a single
  click ALWAYS fires before a double (manual-drag design choice — no
  suppression timer). Slots must tolerate single-then-double.
- The forest cell is a normal CellWindow with ``is_forest_master=True``;
  ``_check_master_validity`` skips its <2-member quorum teardown and the
  context menu calls ``_forest_menu_extension`` (set by
  ForestController). Those are the ONLY two forest exemptions — mirror
  of the note in ``forest_controller``.
- Drag start has a 4 px manhattan threshold; below it a release is a
  pure click. Screen clamping (``_clamp_to_screen``) runs every drag
  move to dodge the "clock-area / off-display" crash — keep it.
- This module shells out to the V1 editor via subprocess
  (``ring_main`` / ``v1_launcher``); it does NOT import the editor.
- ``_load_settings`` only runs for ``role == "standalone"`` — masters
  take fresh branding defaults and never inherit a source's per-hex
  QSettings. Catalog-derived label/icon settings (from the bound
  ``.scriptree*`` JSON) take precedence over QSettings per v0.2.7.
- ~6.7k lines. When editing, find the method via the ``def`` index and
  read its neighbourhood; do not assume behaviour from the name alone.
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
    QEvent,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    Qt,
    QSettings,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
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
    QTabWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Logging helper (stderr only — no print spam on stdout)
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(f"[CellWindow] {msg}", file=sys.stderr)


# Layout trace — diagnostic event log written to a temp file.  See
# ``scriptree/shell/layout_trace.py`` for the format.  Imported here
# so every CellWindow event path can emit trace lines without each
# call site needing its own import.  v0.6.36.
from scriptree.shell import layout_trace as _trace  # noqa: E402


# ---------------------------------------------------------------------------
# Custom hover-tooltip (v0.6.27)
# ---------------------------------------------------------------------------
#
# Why a custom widget instead of ``QToolTip.showText``:
#
# Cells are ``Qt.Tool`` frameless windows with ``WA_TranslucentBackground``
# and a custom mask, AND they typically carry ``Qt.WindowStaysOnTopHint``.
# On Win11 the standard QToolTip popup — which Qt creates as a
# ``Qt.ToolTip`` window — competes with the cell windows for z-order and
# often loses (the tooltip materialises *behind* the cells the user is
# hovering, so they see nothing).  v0.6.13 tried catching ``QEvent.ToolTip``
# manually and calling ``QToolTip.showText`` — that fixed *delivery* but
# not the z-order problem.
#
# This widget is a tiny ``QLabel`` we own that carries the right window
# flags ourselves (``Qt.ToolTip | Qt.FramelessWindowHint |
# Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus |
# Qt.WindowTransparentForInput``) so it draws *above* every cell window
# in the workspace, regardless of which cells were created first or which
# carry ``StaysOnTop`` themselves.  One module-level instance is shared
# across all cells; ``show_at(text, global_point)`` re-uses it.
#
# Trigger: ``CellWindow.enterEvent`` starts a 700 ms ``QTimer`` (matching
# Qt's default tooltip delay); on fire we look up the cell's hover title
# and show the tip just below the cell.  ``leaveEvent`` / drag / popup
# show all hide it.  We do NOT rely on ``QEvent.ToolTip`` at all — that
# delivery is too unreliable on the cell's window combination.


class _CellHoverTip:
    """Singleton-style holder for the shared hover-tip widget.

    Lazily creates a ``QLabel`` the first time ``show()`` is called,
    so the import cost is zero on the headless ``validate`` /
    ``migrate`` path and the widget construction only happens after
    ``QApplication`` is running.

    Methods:
      * ``show(text, global_pt)`` — display the tip near ``global_pt``
        with ``text`` as content.  Reuses the same QLabel; no flicker.
      * ``hide()`` — hide the tip if visible.
    """

    _instance: "QLabel | None" = None

    @classmethod
    def _widget(cls) -> "QLabel":
        if cls._instance is not None:
            return cls._instance
        lbl = QLabel(None)
        # Tool-tip-style window with our own stays-on-top so it draws
        # above the cells regardless of their stacking.
        lbl.setWindowFlags(
            Qt.ToolTip
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
            | Qt.WindowTransparentForInput
        )
        lbl.setAttribute(Qt.WA_ShowWithoutActivating, True)
        lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # Match the OS default tooltip look — small border + light
        # background.  Stylesheet is fine since this widget is solely
        # ours and never inherits app-wide QSS for QLabel that we
        # didn't author.
        lbl.setStyleSheet(
            "QLabel {"
            "  background-color: rgb(255, 255, 220);"
            "  color: rgb(20, 20, 20);"
            "  border: 1px solid rgb(120, 120, 120);"
            "  padding: 3px 6px;"
            "}"
        )
        lbl.setTextFormat(Qt.PlainText)
        cls._instance = lbl
        return lbl

    @classmethod
    def show(  # noqa: ANN001
        cls, text: str, global_pt, *, cell_rect=None,
    ) -> None:
        """Display the hover tip near ``global_pt``, optionally
        anchored on a cell's global bounding rect for clamping.

        v0.8.0a2 Bug 12 — earlier revisions used a fixed +12, +18
        offset from ``global_pt`` (the cell's bottom-centre) which
        pushed the tip off the right edge of the screen for cells
        near the right edge and dangled it noticeably below the
        cell.  When ``cell_rect`` is provided the tip is centred
        horizontally on the cell and parked 6 px below the cell's
        bottom edge; both axes are then clamped against the
        containing screen's available rect.  If clamping would
        still leave the tip overlapping the cell on the bottom
        edge, the tip flips ABOVE the cell instead.  When
        ``cell_rect`` is None (legacy call sites) the old offset is
        kept as a fallback.
        """
        if not text:
            cls.hide()
            return
        try:
            lbl = cls._widget()
            lbl.setText(text)
            lbl.adjustSize()
            w = lbl.width()
            h = lbl.height()

            if cell_rect is not None:
                # Centre under the cell, 6 px below the cell bottom.
                x = cell_rect.center().x() - w // 2
                y = cell_rect.bottom() + 6
            else:
                # Fallback (cursor-anchored).
                x = global_pt.x() + 12
                y = global_pt.y() + 18

            # Clamp to the screen containing (x, y) — using the
            # tip's intended top-left so we pick the right monitor
            # for multi-monitor layouts.
            from PySide6.QtGui import QGuiApplication
            screen = (
                QGuiApplication.screenAt(QPoint(x, y))
                or QGuiApplication.primaryScreen()
            )
            if screen is not None:
                avail = screen.availableGeometry()
                # Horizontal clamp: if off the right edge, shift
                # left; if off the left edge, shift right.
                if x + w > avail.right():
                    x = avail.right() - w - 4
                if x < avail.left():
                    x = avail.left() + 4
                # Vertical clamp: if off the bottom AND we have the
                # cell rect, flip above the cell.  Otherwise just
                # shift the tip back on-screen.
                if y + h > avail.bottom():
                    if cell_rect is not None:
                        flipped = cell_rect.top() - h - 6
                        if flipped >= avail.top():
                            y = flipped
                        else:
                            y = avail.bottom() - h - 4
                    else:
                        y = avail.bottom() - h - 4
                if y < avail.top():
                    y = avail.top() + 4

            lbl.move(x, y)
            lbl.show()
            lbl.raise_()
        except Exception as exc:  # noqa: BLE001
            _log(f"_CellHoverTip.show: {exc!r}")

    @classmethod
    def hide(cls) -> None:
        try:
            if cls._instance is not None and cls._instance.isVisible():
                cls._instance.hide()
        except Exception as exc:  # noqa: BLE001
            _log(f"_CellHoverTip.hide: {exc!r}")


# ---------------------------------------------------------------------------
# ShapeGeometry — returned by compute_polygon(), consumed by SnapEngine
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ShapeGeometry:
    """Full geometric description of a hexagon/square at a given size.

    polygon       — QPolygon of integer logical-pixel vertices (for setMask and drawPolygon).
    vertices      — same vertices as QPointF list (for snap math, float precision).
    edge_midpoints— one QPointF per edge, widget-local coords.
    edge_normals  — outward unit normal QPointF per edge (direction only, no magnitude).
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

    start_deg — angle of the first vertex in degrees (counter-clockwise from +X).
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

        # Outward normal: rotate edge direction 90° clockwise (in Qt screen coords,
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
        # flat-top: first vertex at 0° (right), giving horizontal top/bottom edges.
        # pointy-top: first vertex at -90° (top), giving vertical top/bottom vertices.
        start_deg = 0.0 if orientation == "flat-top" else -90.0
        return _regular_polygon_geometry(n=6, start_deg=start_deg, size_px=size_px)
    if s == "square":
        # Square at 45° rotation so vertices are at corners, edges face N/E/S/W.
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
# Auto-letter derivation from a catalog or tool name
# ---------------------------------------------------------------------------

# Words skipped when deriving letters from a multi-word name.  These are
# articles, conjunctions, prepositions that would make a poor first letter
# in a 2-letter abbreviation.  Per user spec: "skips over words like and
# or and the, etc."  Comparison is lower-case.
_LETTER_SKIP_WORDS: frozenset[str] = frozenset({
    "a", "an", "and", "or", "the", "of", "to", "in", "on", "for",
    "at", "by", "as", "is", "if",
})


def _derive_letters(name: str) -> str:
    """Derive a 1-2 character abbreviation from ``name``.

    User spec (verbatim, 2026-05-07):
      "they take the first and second letter of the tool's name if it
       is one word, or first and second capital letter if it is one
       word with capital letter at start and a second one elsewhere,
       or the letter of the first word and second word (but skips
       over words like and or and the, etc) unless that is the only
       word after the first one, then it will use the character for
       that."

      Follow-up clarification: "SolidWorks toolkit should show as SW
      as the first 2 capital letters rule takes precidence."

    Rules in order:
      1. **CamelCase wins.**  If ANY word in the input starts with a
         capital AND contains a second capital, use the first two
         capitals from that word (e.g. "SolidWorks toolkit" → "SW",
         "MakeCode" → "MC", "ScripTreeRing" → "ST").
      2. Multi-word with 2+ meaningful (non-skip) words → first
         letter of each of the first two meaningful words
         (e.g. "git status" → "GS", "the quick fox" → "QF").
      3. Multi-word but only ONE meaningful word survives the skip
         filter → fall through to single-word logic on that word
         (e.g. "the cat" → "CA", "foo and" → "FO").
      4. Otherwise → the first two characters of the (meaningful)
         word, upper-cased.

    Always returns at least one character.  Returns ``"?"`` only when
    the input is empty / whitespace.
    """
    s = (name or "").strip()
    if not s:
        return "?"

    words = [w for w in s.split() if w]
    meaningful = [w for w in words if w.lower() not in _LETTER_SKIP_WORDS]

    # Rule 1 (precedence): CamelCase / PascalCase from any word in
    # the input.  Walk in order so the first qualifying word wins —
    # matches what the user expects from "SolidWorks toolkit" → SW.
    for w in (meaningful or words):
        if w[0].isupper():
            caps = [c for c in w if c.isupper()]
            if len(caps) >= 2:
                return caps[0] + caps[1]

    # Rule 2: ≥2 meaningful words.
    if len(meaningful) >= 2:
        return (meaningful[0][0] + meaningful[1][0]).upper()

    # Pick the single word to inspect: meaningful (if any) or the first.
    word = meaningful[0] if meaningful else words[0]

    # Rule 4: first two characters of the word.
    if len(word) >= 2:
        return word[:2].upper()
    return word[0].upper()


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    """Modeless settings popover launched from the hexagon right-click menu.

    All user-visible strings (title, labels) are brand-agnostic except for the
    window title which reads from the branding dict passed at construction.

    Controls:
        1. Shape        QComboBox — Hexagon | Square
        2. Orientation  QComboBox — Flat-top | Pointy-top (disabled for Square)
        3. Size         QSlider   — 32–96 px, step 4, live preview
        4. Transparency QSlider   — 30–100 (maps to 0.30–1.00 alpha), live preview
        5. Always on top QCheckBox
        6. Rotate 90°  QPushButton — cycles orientation (no-op for Square)

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
        self.setWindowTitle(f"{brand} — Settings")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(300)

        # Prevent the dialog from blocking the hexagon (modeless).
        self.setModal(False)

        # v0.5.1 — tabbed layout.  The flat single-column form was
        # getting long enough that it routinely opened taller than
        # the desktop work area when launched from a cell sitting
        # near a screen edge.  Four tabs ("Shape & Size", "Click
        # action", "Colours", "Label/Icon") keep any single page short
        # enough to fit on a typical 1080 p display without
        # scrolling.
        outer_layout = QVBoxLayout(self)
        outer_layout.setSpacing(8)
        outer_layout.setContentsMargins(12, 12, 12, 12)

        self._tabs = QTabWidget()
        outer_layout.addWidget(self._tabs)

        # Each tab is a plain QWidget whose own QVBoxLayout receives
        # the section's controls.  Below the section code reassigns
        # the local variable ``layout`` to the appropriate per-tab
        # layout before each section so the existing
        # ``layout.addWidget`` / ``layout.addLayout`` calls drop the
        # controls into the right tab — minimising diff vs. the
        # pre-tabbed structure.
        shape_tab = QWidget()
        shape_tab_layout = QVBoxLayout(shape_tab)
        shape_tab_layout.setSpacing(10)
        self._tabs.addTab(shape_tab, "Shape && Size")

        click_tab = QWidget()
        click_tab_layout = QVBoxLayout(click_tab)
        click_tab_layout.setSpacing(10)
        self._tabs.addTab(click_tab, "Click action")

        colour_tab = QWidget()
        colour_tab_layout = QVBoxLayout(colour_tab)
        colour_tab_layout.setSpacing(10)
        self._tabs.addTab(colour_tab, "Colours")

        label_tab = QWidget()
        label_tab_layout = QVBoxLayout(label_tab)
        label_tab_layout.setSpacing(10)
        # v0.8.0a25 -- tab renamed from "Label" to "Label/Icon" so
        # users can find the icon controls (which have always lived
        # here, alongside the custom-text + auto-letters fields)
        # without hunting through the other tabs.
        self._tabs.addTab(label_tab, "Label/Icon")

        # v0.6.21 — menu-appearance controls live INSIDE the Shape &
        # Size tab (per user direction: "Put it in the same section
        # that controls cell size/shape").  They get appended to
        # shape_tab_layout below, after the existing shape/size
        # widgets.  The "Save to local / shared default" checkboxes
        # also apply to the cell shape/size controls so the same
        # group serves as a global-default save destination for
        # both kinds of setting.

        # First section drops into the shape tab.
        layout = shape_tab_layout

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
        # Store transparency as int 30–100; maps to 0.30–1.00 alpha multiplier.
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

        # ---- 6. Rotate 90° --------------------------------------------------
        self._rotate_btn = QPushButton("Rotate 90°")
        self._rotate_btn.setToolTip(
            "Cycle between Flat-top and Pointy-top orientations (no-op for Square)"
        )
        layout.addWidget(self._rotate_btn)
        layout.addStretch(1)

        # Switch to the click-action tab.
        layout = click_tab_layout

        # ---- 6.5 Click action (V3 v0.3.5+) ---------------------------------
        # Two dropdowns:
        #   - Click action:   "Show menu" (default) | "Run tool(s)"
        #   - Run mode:        "Sequential" | "Parallel" (only meaningful
        #                       when click action is "Run tool(s)" AND the
        #                       bound catalog is a .scriptreetree)
        #
        # Both are gated by the ``cell_click_to_run`` capability — when
        # denied, both controls are disabled with an explanatory tooltip
        # and any catalog-side click_action="run" is overridden to
        # "menu" at click-dispatch time anyway.
        # Local re-import of QGroupBox + QComboBox so this section
        # is independent of the cell-label section's lazy imports
        # below — Python's lexical scoping treats those imports as
        # local-binding-creators that would otherwise shadow our
        # uses here with an UnboundLocalError.
        from PySide6.QtWidgets import (
            QGroupBox as _QGroupBox,
            QComboBox as _QComboBox,
        )
        click_grp = _QGroupBox("Single-click action")
        click_layout = QVBoxLayout(click_grp)

        click_action_row = QHBoxLayout()
        click_action_row.addWidget(QLabel("Click action:"))
        self._click_action_combo = _QComboBox()
        self._click_action_combo.addItem("Show menu", "menu")
        self._click_action_combo.addItem("Run tool(s)", "run")
        # Initial state from the catalog (or "menu" when unbound).
        from scriptree.core.cell_metadata import read_for as _read_for
        try:
            initial_md = (
                _read_for(hexagon._catalog_path)
                if hexagon._catalog_path else None
            )
        except Exception:  # noqa: BLE001
            initial_md = None
        initial_action = (
            initial_md.click_action if initial_md is not None else "menu"
        )
        idx = self._click_action_combo.findData(initial_action)
        self._click_action_combo.setCurrentIndex(max(idx, 0))
        click_action_row.addWidget(self._click_action_combo)
        click_layout.addLayout(click_action_row)

        run_mode_row = QHBoxLayout()
        run_mode_row.addWidget(QLabel("Run mode:"))
        self._click_run_mode_combo = _QComboBox()
        self._click_run_mode_combo.addItem("Sequential", "sequential")
        self._click_run_mode_combo.addItem("Parallel", "parallel")
        initial_mode = (
            initial_md.click_run_mode if initial_md is not None else "sequential"
        )
        idx = self._click_run_mode_combo.findData(initial_mode)
        self._click_run_mode_combo.setCurrentIndex(max(idx, 0))
        run_mode_row.addWidget(self._click_run_mode_combo)
        click_layout.addLayout(run_mode_row)

        layout.addWidget(click_grp)

        # Capability gate (V3 v0.3.5).  The dropdowns disable when
        # ``cell_click_to_run`` is denied so the user can't change
        # the action away from "menu".  A tooltip explains why.
        try:
            from scriptree.ui.permission_guards import perm_check
            click_perm_ok = perm_check("cell_click_to_run")
        except Exception:  # noqa: BLE001
            click_perm_ok = True
        if not click_perm_ok:
            self._click_action_combo.setEnabled(False)
            self._click_run_mode_combo.setEnabled(False)
            tip = (
                "Disabled by IT — cell click-to-run is not permitted "
                "(capability: cell_click_to_run)."
            )
            self._click_action_combo.setToolTip(tip)
            self._click_run_mode_combo.setToolTip(tip)

        # Run-mode is only meaningful when the catalog is a tree AND
        # the click action is "run".  We disable the run-mode combo
        # outside that case to avoid confusing the user.
        def _refresh_run_mode_enabled() -> None:
            action = self._click_action_combo.currentData()
            cat = hexagon._catalog_path or ""
            is_tree = cat.lower().endswith(".scriptreetree")
            self._click_run_mode_combo.setEnabled(
                click_perm_ok and action == "run" and is_tree
            )
            if not self._click_run_mode_combo.isEnabled() and click_perm_ok:
                if action != "run":
                    self._click_run_mode_combo.setToolTip(
                        "Run mode only applies when Click action is "
                        "'Run tool(s)'."
                    )
                elif not is_tree:
                    self._click_run_mode_combo.setToolTip(
                        "Run mode only applies to .scriptreetree "
                        "catalogs (single tools have only one thing "
                        "to run)."
                    )
        _refresh_run_mode_enabled()
        self._click_action_combo.currentIndexChanged.connect(
            lambda _i: _refresh_run_mode_enabled()
        )
        layout.addStretch(1)

        # Switch to the colours tab.
        layout = colour_tab_layout

        # ---- 6.6 Cell colour (V3 v0.3.6+) ----------------------------------
        # Three synced controls + reset:
        #
        #   - Hex entry (QLineEdit, 6-digit ``#RRGGBB``)
        #   - R / G / B QSpinBoxes (0-255 each)
        #   - Hue rainbow slider (0-359, full saturation/value)
        #   - Reset to default button
        #
        # All four controls reflect the same underlying ``_fill_color``
        # state.  Editing any one updates the others (with signal
        # blocking to avoid feedback loops) and writes the new hex
        # through to the bound catalog via
        # ``apply_fill_color_change``.
        from PySide6.QtWidgets import (
            QGroupBox as _QGroupBox2,
            QHBoxLayout as _QHBoxLayout2,
            QLabel as _QLabel2,
            QLineEdit as _QLineEdit2,
            QPushButton as _QPushButton2,
            QSpinBox as _QSpinBox2,
            QSlider as _QSlider2,
        )
        color_grp = _QGroupBox2("Cell fill colour")
        color_layout = QVBoxLayout(color_grp)

        # Initial RGB values from the cell's current fill colour.
        c0 = hexagon._fill_color
        initial_r = c0.red()
        initial_g = c0.green()
        initial_b = c0.blue()
        initial_hex = (
            hexagon._fill_color_hex
            or f"#{initial_r:02x}{initial_g:02x}{initial_b:02x}"
        )

        # Row 1: swatch + hex entry + reset button.
        row1 = _QHBoxLayout2()
        self._color_swatch = _QLabel2()
        self._color_swatch.setFixedSize(28, 22)
        self._color_swatch.setStyleSheet(
            f"QLabel {{ background:{initial_hex}; "
            f"border:1px solid #888; }}"
        )
        row1.addWidget(self._color_swatch)
        row1.addWidget(_QLabel2("Hex:"))
        self._color_hex_edit = _QLineEdit2(initial_hex)
        self._color_hex_edit.setMaxLength(7)
        self._color_hex_edit.setPlaceholderText("#RRGGBB")
        row1.addWidget(self._color_hex_edit, stretch=1)
        self._color_reset_btn = _QPushButton2("Reset")
        self._color_reset_btn.setToolTip(
            "Revert to the branding default fill colour."
        )
        row1.addWidget(self._color_reset_btn)
        color_layout.addLayout(row1)

        # Row 2: R / G / B spinboxes.
        row2 = _QHBoxLayout2()
        row2.addWidget(_QLabel2("R:"))
        self._color_r_spin = _QSpinBox2()
        self._color_r_spin.setRange(0, 255)
        self._color_r_spin.setValue(initial_r)
        row2.addWidget(self._color_r_spin)
        row2.addWidget(_QLabel2("G:"))
        self._color_g_spin = _QSpinBox2()
        self._color_g_spin.setRange(0, 255)
        self._color_g_spin.setValue(initial_g)
        row2.addWidget(self._color_g_spin)
        row2.addWidget(_QLabel2("B:"))
        self._color_b_spin = _QSpinBox2()
        self._color_b_spin.setRange(0, 255)
        self._color_b_spin.setValue(initial_b)
        row2.addWidget(self._color_b_spin)
        row2.addStretch(1)
        color_layout.addLayout(row2)

        # Row 3: hue rainbow slider.  Stylesheet draws an HSL
        # rainbow gradient under the groove so the user can see
        # which hue they're picking.
        row3 = _QHBoxLayout2()
        row3.addWidget(_QLabel2("Hue:"))
        self._color_hue_slider = _QSlider2(Qt.Horizontal)
        self._color_hue_slider.setMinimum(0)
        self._color_hue_slider.setMaximum(359)
        # Initial hue = HSV-hue of the current fill (if any).
        initial_hue = max(0, c0.hsvHue())  # -1 for greys → clamp to 0
        self._color_hue_slider.setValue(initial_hue)
        # Inline rainbow gradient under the groove.  qlineargradient
        # syntax with stops at every 60° = clean six-stop rainbow.
        self._color_hue_slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 12px; "
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            "stop:0    #ff0000, stop:0.166 #ffff00, "
            "stop:0.333 #00ff00, stop:0.5   #00ffff, "
            "stop:0.666 #0000ff, stop:0.833 #ff00ff, "
            "stop:1    #ff0000); border-radius:3px; } "
            "QSlider::handle:horizontal { width:10px; "
            "background:#ffffff; border:1px solid #444; }"
        )
        row3.addWidget(self._color_hue_slider, stretch=1)
        color_layout.addLayout(row3)

        layout.addWidget(color_grp)

        # Two-way sync logic.  Each control writes to the cell's
        # fill via ``apply_fill_color_change`` and refreshes the
        # other controls — signals are blocked during programmatic
        # updates so the chain doesn't loop.
        def _set_swatch(hex_rgb: str) -> None:
            self._color_swatch.setStyleSheet(
                f"QLabel {{ background:{hex_rgb}; "
                f"border:1px solid #888; }}"
            )

        def _block(widgets, fn):
            blockers = [w.blockSignals(True) for w in widgets]
            try:
                fn()
            finally:
                for w, prev in zip(widgets, blockers):
                    w.blockSignals(prev)

        def _on_rgb_changed():
            r = self._color_r_spin.value()
            g = self._color_g_spin.value()
            b = self._color_b_spin.value()
            hex_rgb = f"#{r:02x}{g:02x}{b:02x}"
            # Sync hex + slider (signal-blocked to prevent feedback).
            _block(
                [self._color_hex_edit, self._color_hue_slider],
                lambda: (
                    self._color_hex_edit.setText(hex_rgb),
                    self._color_hue_slider.setValue(
                        max(0, QColor(r, g, b).hsvHue())
                    ),
                ),
            )
            _set_swatch(hex_rgb)
            self._hex.apply_fill_color_change(hex_rgb)

        def _on_hex_changed():
            txt = self._color_hex_edit.text()
            from scriptree.core.cell_metadata import _normalise_hex_rgb
            canonical = _normalise_hex_rgb(txt)
            if not canonical:
                # Don't sync to incomplete typing — wait until the
                # user lands on a 6-digit hex.
                return
            r = int(canonical[1:3], 16)
            g = int(canonical[3:5], 16)
            b = int(canonical[5:7], 16)
            _block(
                [
                    self._color_r_spin, self._color_g_spin,
                    self._color_b_spin, self._color_hue_slider,
                ],
                lambda: (
                    self._color_r_spin.setValue(r),
                    self._color_g_spin.setValue(g),
                    self._color_b_spin.setValue(b),
                    self._color_hue_slider.setValue(
                        max(0, QColor(r, g, b).hsvHue())
                    ),
                ),
            )
            _set_swatch(canonical)
            self._hex.apply_fill_color_change(canonical)

        def _on_hue_changed():
            hue = self._color_hue_slider.value()
            # Hue slider always picks a fully-saturated full-value
            # colour at the chosen hue.  S/V variation isn't exposed
            # here intentionally — the rainbow slider is a quick
            # picker, not a full HSV editor.
            new_color = QColor.fromHsv(hue, 255, 255)
            r, g, b = new_color.red(), new_color.green(), new_color.blue()
            hex_rgb = f"#{r:02x}{g:02x}{b:02x}"
            _block(
                [
                    self._color_r_spin, self._color_g_spin,
                    self._color_b_spin, self._color_hex_edit,
                ],
                lambda: (
                    self._color_r_spin.setValue(r),
                    self._color_g_spin.setValue(g),
                    self._color_b_spin.setValue(b),
                    self._color_hex_edit.setText(hex_rgb),
                ),
            )
            _set_swatch(hex_rgb)
            self._hex.apply_fill_color_change(hex_rgb)

        def _on_color_reset():
            # Empty string clears the override.  After applying we
            # re-read the cell's now-default fill to refresh the
            # controls.
            self._hex.apply_fill_color_change("")
            new_c = self._hex._fill_color
            r, g, b = new_c.red(), new_c.green(), new_c.blue()
            new_hex = f"#{r:02x}{g:02x}{b:02x}"
            _block(
                [
                    self._color_r_spin, self._color_g_spin,
                    self._color_b_spin, self._color_hex_edit,
                    self._color_hue_slider,
                ],
                lambda: (
                    self._color_r_spin.setValue(r),
                    self._color_g_spin.setValue(g),
                    self._color_b_spin.setValue(b),
                    self._color_hex_edit.setText(new_hex),
                    self._color_hue_slider.setValue(
                        max(0, QColor(r, g, b).hsvHue())
                    ),
                ),
            )
            _set_swatch(new_hex)

        # Wire up the signals.
        self._color_r_spin.valueChanged.connect(lambda _v: _on_rgb_changed())
        self._color_g_spin.valueChanged.connect(lambda _v: _on_rgb_changed())
        self._color_b_spin.valueChanged.connect(lambda _v: _on_rgb_changed())
        self._color_hex_edit.editingFinished.connect(_on_hex_changed)
        self._color_hue_slider.valueChanged.connect(lambda _v: _on_hue_changed())
        self._color_reset_btn.clicked.connect(_on_color_reset)

        # ---- 6.7 Cell text colour (V3 v0.3.8+) -----------------------------
        # Mirror of the fill-colour group, but for the label text.
        # Default ("Reset") clears the override so paint code falls
        # back to the stroke-derived default.
        text_color_grp = _QGroupBox2("Cell text colour")
        text_color_layout = QVBoxLayout(text_color_grp)

        # Initial RGB values: the override if set, else the stroke
        # colour the paint code currently picks.  This way the
        # dialog opens showing the *actual* colour on the cell, not
        # a misleading "default of nothing".
        if hexagon._text_color_hex:
            tc0 = QColor(
                int(hexagon._text_color_hex[1:3], 16),
                int(hexagon._text_color_hex[3:5], 16),
                int(hexagon._text_color_hex[5:7], 16),
            )
        else:
            tc0 = QColor(hexagon._compute_stroke_color())
        initial_tr = tc0.red()
        initial_tg = tc0.green()
        initial_tb = tc0.blue()
        initial_thex = (
            hexagon._text_color_hex
            or f"#{initial_tr:02x}{initial_tg:02x}{initial_tb:02x}"
        )

        # Row 1: swatch + hex entry + reset.
        trow1 = _QHBoxLayout2()
        self._text_color_swatch = _QLabel2()
        self._text_color_swatch.setFixedSize(28, 22)
        self._text_color_swatch.setStyleSheet(
            f"QLabel {{ background:{initial_thex}; "
            f"border:1px solid #888; }}"
        )
        trow1.addWidget(self._text_color_swatch)
        trow1.addWidget(_QLabel2("Hex:"))
        self._text_color_hex_edit = _QLineEdit2(initial_thex)
        self._text_color_hex_edit.setMaxLength(7)
        self._text_color_hex_edit.setPlaceholderText("#RRGGBB")
        trow1.addWidget(self._text_color_hex_edit, stretch=1)
        self._text_color_reset_btn = _QPushButton2("Reset")
        self._text_color_reset_btn.setToolTip(
            "Revert to the default (stroke-derived) text colour."
        )
        trow1.addWidget(self._text_color_reset_btn)
        text_color_layout.addLayout(trow1)

        # Row 2: R / G / B spinboxes.
        trow2 = _QHBoxLayout2()
        trow2.addWidget(_QLabel2("R:"))
        self._text_color_r_spin = _QSpinBox2()
        self._text_color_r_spin.setRange(0, 255)
        self._text_color_r_spin.setValue(initial_tr)
        trow2.addWidget(self._text_color_r_spin)
        trow2.addWidget(_QLabel2("G:"))
        self._text_color_g_spin = _QSpinBox2()
        self._text_color_g_spin.setRange(0, 255)
        self._text_color_g_spin.setValue(initial_tg)
        trow2.addWidget(self._text_color_g_spin)
        trow2.addWidget(_QLabel2("B:"))
        self._text_color_b_spin = _QSpinBox2()
        self._text_color_b_spin.setRange(0, 255)
        self._text_color_b_spin.setValue(initial_tb)
        trow2.addWidget(self._text_color_b_spin)
        trow2.addStretch(1)
        text_color_layout.addLayout(trow2)

        # Row 3: hue rainbow slider.  Same gradient as the fill row.
        trow3 = _QHBoxLayout2()
        trow3.addWidget(_QLabel2("Hue:"))
        self._text_color_hue_slider = _QSlider2(Qt.Horizontal)
        self._text_color_hue_slider.setMinimum(0)
        self._text_color_hue_slider.setMaximum(359)
        initial_thue = max(0, tc0.hsvHue())
        self._text_color_hue_slider.setValue(initial_thue)
        self._text_color_hue_slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 12px; "
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            "stop:0    #ff0000, stop:0.166 #ffff00, "
            "stop:0.333 #00ff00, stop:0.5   #00ffff, "
            "stop:0.666 #0000ff, stop:0.833 #ff00ff, "
            "stop:1    #ff0000); border-radius:3px; } "
            "QSlider::handle:horizontal { width:10px; "
            "background:#ffffff; border:1px solid #444; }"
        )
        trow3.addWidget(self._text_color_hue_slider, stretch=1)
        text_color_layout.addLayout(trow3)

        layout.addWidget(text_color_grp)

        # Two-way sync logic for the text-colour group.  Same shape
        # as the fill group; signal-blocking prevents feedback loops.
        def _set_text_swatch(hex_rgb: str) -> None:
            self._text_color_swatch.setStyleSheet(
                f"QLabel {{ background:{hex_rgb}; "
                f"border:1px solid #888; }}"
            )

        def _on_text_rgb_changed():
            r = self._text_color_r_spin.value()
            g = self._text_color_g_spin.value()
            b = self._text_color_b_spin.value()
            hex_rgb = f"#{r:02x}{g:02x}{b:02x}"
            _block(
                [self._text_color_hex_edit, self._text_color_hue_slider],
                lambda: (
                    self._text_color_hex_edit.setText(hex_rgb),
                    self._text_color_hue_slider.setValue(
                        max(0, QColor(r, g, b).hsvHue())
                    ),
                ),
            )
            _set_text_swatch(hex_rgb)
            self._hex.apply_text_color_change(hex_rgb)

        def _on_text_hex_changed():
            txt = self._text_color_hex_edit.text()
            from scriptree.core.cell_metadata import _normalise_hex_rgb
            canonical = _normalise_hex_rgb(txt)
            if not canonical:
                return
            r = int(canonical[1:3], 16)
            g = int(canonical[3:5], 16)
            b = int(canonical[5:7], 16)
            _block(
                [
                    self._text_color_r_spin, self._text_color_g_spin,
                    self._text_color_b_spin, self._text_color_hue_slider,
                ],
                lambda: (
                    self._text_color_r_spin.setValue(r),
                    self._text_color_g_spin.setValue(g),
                    self._text_color_b_spin.setValue(b),
                    self._text_color_hue_slider.setValue(
                        max(0, QColor(r, g, b).hsvHue())
                    ),
                ),
            )
            _set_text_swatch(canonical)
            self._hex.apply_text_color_change(canonical)

        def _on_text_hue_changed():
            hue = self._text_color_hue_slider.value()
            new_color = QColor.fromHsv(hue, 255, 255)
            r, g, b = new_color.red(), new_color.green(), new_color.blue()
            hex_rgb = f"#{r:02x}{g:02x}{b:02x}"
            _block(
                [
                    self._text_color_r_spin, self._text_color_g_spin,
                    self._text_color_b_spin, self._text_color_hex_edit,
                ],
                lambda: (
                    self._text_color_r_spin.setValue(r),
                    self._text_color_g_spin.setValue(g),
                    self._text_color_b_spin.setValue(b),
                    self._text_color_hex_edit.setText(hex_rgb),
                ),
            )
            _set_text_swatch(hex_rgb)
            self._hex.apply_text_color_change(hex_rgb)

        def _on_text_color_reset():
            # Empty string clears the override; paint code reverts
            # to stroke-derived colour.  Refresh controls to show
            # the resulting default (so the dialog stays accurate).
            self._hex.apply_text_color_change("")
            new_c = QColor(self._hex._compute_stroke_color())
            r, g, b = new_c.red(), new_c.green(), new_c.blue()
            new_hex = f"#{r:02x}{g:02x}{b:02x}"
            _block(
                [
                    self._text_color_r_spin, self._text_color_g_spin,
                    self._text_color_b_spin, self._text_color_hex_edit,
                    self._text_color_hue_slider,
                ],
                lambda: (
                    self._text_color_r_spin.setValue(r),
                    self._text_color_g_spin.setValue(g),
                    self._text_color_b_spin.setValue(b),
                    self._text_color_hex_edit.setText(new_hex),
                    self._text_color_hue_slider.setValue(
                        max(0, QColor(r, g, b).hsvHue())
                    ),
                ),
            )
            _set_text_swatch(new_hex)

        self._text_color_r_spin.valueChanged.connect(
            lambda _v: _on_text_rgb_changed()
        )
        self._text_color_g_spin.valueChanged.connect(
            lambda _v: _on_text_rgb_changed()
        )
        self._text_color_b_spin.valueChanged.connect(
            lambda _v: _on_text_rgb_changed()
        )
        self._text_color_hex_edit.editingFinished.connect(
            _on_text_hex_changed
        )
        self._text_color_hue_slider.valueChanged.connect(
            lambda _v: _on_text_hue_changed()
        )
        self._text_color_reset_btn.clicked.connect(_on_text_color_reset)
        layout.addStretch(1)

        # Switch to the label tab.
        layout = label_tab_layout

        # ---- 7. Cell label (icon / custom text / default auto) -------------
        # Per user spec (2026-05-07): the per-cell Settings dialog needs
        # to choose between three label modes (Default / Custom Text /
        # Icon), an icon scale slider that live-updates as you drag,
        # and a label-opacity setting.  Once committed, the icon scale
        # is a *relative* value so it tracks future cell-size changes.
        from PySide6.QtWidgets import (
            QGroupBox, QRadioButton, QButtonGroup, QLineEdit, QFileDialog,
        )
        label_grp = QGroupBox("Cell label")
        label_layout = QVBoxLayout(label_grp)

        # Mode radio buttons.  ``Default`` clears overrides so the
        # paint code falls back to auto-derived letters.
        self._label_mode_default_rb = QRadioButton("Default (auto letters)")
        self._label_mode_text_rb = QRadioButton("Custom text")
        self._label_mode_icon_rb = QRadioButton("Icon")
        self._label_mode_grp = QButtonGroup(self)
        self._label_mode_grp.addButton(self._label_mode_default_rb, 0)
        self._label_mode_grp.addButton(self._label_mode_text_rb, 1)
        self._label_mode_grp.addButton(self._label_mode_icon_rb, 2)

        # Pick the radio that reflects the cell's current state.
        # v0.8.0a25 fix: check ``_icon_data_b64`` too -- the embedded
        # base64 storage is the canonical "icon set" signal today,
        # but the legacy check only looked at ``_icon_path`` so any
        # cell whose icon was embedded (the common case after
        # v0.6.33) showed "Default" by mistake.
        if hexagon._icon_path or hexagon._icon_data_b64:
            self._label_mode_icon_rb.setChecked(True)
        elif hexagon._text_label:
            self._label_mode_text_rb.setChecked(True)
        else:
            self._label_mode_default_rb.setChecked(True)

        label_layout.addWidget(self._label_mode_default_rb)
        label_layout.addWidget(self._label_mode_text_rb)

        # Custom-text input — only enabled when "Custom text" radio is on.
        text_row = QHBoxLayout()
        text_row.addSpacing(20)  # indent
        self._text_input = QLineEdit(hexagon._text_label or "")
        self._text_input.setPlaceholderText(
            "Up to a few characters; auto-resized to fit"
        )
        self._text_input.setMaxLength(12)
        text_row.addWidget(self._text_input)
        label_layout.addLayout(text_row)

        label_layout.addWidget(self._label_mode_icon_rb)

        # === OBSOLETE-ICON-UI-START (v0.8.0a25 -- delete after sign-off) ===
        # The old icon section exposed an external file path + a manual
        # Embed/Unembed dance, dating from before v0.6.33 made
        # embedded-base64 the canonical storage and v0.6.33 added the
        # auto-classified-glyph paint priority.  Today nothing the user
        # picks should produce a bare file link: ``Library...`` already
        # embeds the bundled PNG, ``Choose file...`` (below) reads-and-
        # embeds in one step, and any legacy ``_icon_path`` value on a
        # loaded catalog is honoured on read but never produced by the
        # editor.  The path label + Browse + Embed/Unembed widgets
        # remained here only to display the now-defunct state.  Block
        # commented out for a release cycle so we can revert quickly
        # if something downstream still references these attributes;
        # search for OBSOLETE-ICON-UI to delete after sign-off.
        #
        # icon_path_row = QHBoxLayout()
        # icon_path_row.addSpacing(20)
        # if getattr(hexagon, "_icon_data_b64", ""):
        #     initial_label = "(icon embedded in catalog file)"
        # elif hexagon._icon_path:
        #     initial_label = hexagon._icon_path
        # else:
        #     initial_label = "(no icon set)"
        # self._icon_path_label = QLabel(initial_label)
        # self._icon_path_label.setStyleSheet("QLabel { color: #888; }")
        # self._icon_path_label.setMinimumWidth(160)
        # self._icon_path_label.setWordWrap(True)
        # self._icon_browse_btn = QPushButton("Browse…")
        # icon_path_row.addWidget(self._icon_path_label, stretch=1)
        # icon_path_row.addWidget(self._icon_browse_btn)
        # icon_path_row.addWidget(self._icon_library_btn)
        # icon_path_row.addWidget(self._icon_clear_btn)
        # label_layout.addLayout(icon_path_row)
        #
        # embed_row = QHBoxLayout()
        # embed_row.addSpacing(20)
        # self._icon_embed_btn = QPushButton("Embed in catalog")
        # self._icon_unembed_btn = QPushButton("Unembed (Save as…)")
        # embed_row.addWidget(self._icon_embed_btn)
        # embed_row.addWidget(self._icon_unembed_btn)
        # embed_row.addStretch(1)
        # label_layout.addLayout(embed_row)
        # === OBSOLETE-ICON-UI-END ===

        # --- New icon section (v0.8.0a25+) -------------------------------
        # Live preview of the actually-rendered glyph (whatever resolves
        # through the paint precedence: embedded -> file -> auto-classified
        # -> letters), three action buttons that all keep the icon storage
        # canonical (embedded base64), and a status line telling the user
        # which source is winning.
        icon_preview_row = QHBoxLayout()
        icon_preview_row.addSpacing(20)
        self._icon_preview_label = QLabel()
        self._icon_preview_label.setFixedSize(96, 96)
        self._icon_preview_label.setStyleSheet(
            "QLabel { border: 1px solid #ccc; background: #fafafa; }"
        )
        self._icon_preview_label.setAlignment(Qt.AlignCenter)
        self._icon_preview_label.setToolTip(
            "Preview of the icon currently rendered on the cell.  "
            "Updates live when you pick a new icon."
        )
        icon_preview_row.addWidget(self._icon_preview_label)
        icon_preview_row.addSpacing(8)

        # Right-hand column: status text on top of the action buttons.
        icon_actions_col = QVBoxLayout()
        self._icon_source_label = QLabel("")  # filled by _refresh_icon_preview
        self._icon_source_label.setStyleSheet("QLabel { color: #666; }")
        self._icon_source_label.setWordWrap(True)
        icon_actions_col.addWidget(self._icon_source_label)

        icon_btn_row = QHBoxLayout()
        self._icon_choose_btn = QPushButton("Choose image file…")
        self._icon_choose_btn.setToolTip(
            "Pick an image file from disk and embed it into this "
            "cell's catalog as base64.  Always embedded -- the "
            "file you pick is not linked, so moving or deleting it "
            "won't break the cell."
        )
        self._icon_library_btn = QPushButton("Library…")
        self._icon_library_btn.setToolTip(
            "Pick a shipped, trademark-safe line icon.  When the cell "
            "is bound to a catalog the chosen glyph is embedded into "
            "it (portable); otherwise it's linked from the icons/ set."
        )
        self._icon_clear_btn = QPushButton("Clear")
        self._icon_clear_btn.setToolTip(
            "Remove any explicit icon set on this cell.  The cell "
            "will fall back to the auto-classified bundled glyph "
            "(based on the catalog's name and content) or to the "
            "auto-letters if no classification matches."
        )
        icon_btn_row.addWidget(self._icon_choose_btn)
        icon_btn_row.addWidget(self._icon_library_btn)
        icon_btn_row.addWidget(self._icon_clear_btn)
        icon_btn_row.addStretch(1)
        icon_actions_col.addLayout(icon_btn_row)
        icon_actions_col.addStretch(1)

        icon_preview_row.addLayout(icon_actions_col, stretch=1)
        label_layout.addLayout(icon_preview_row)

        # Icon scale slider — live preview as you drag.  Default 100
        # = the cell's natural inscribed-circle size (~70 % diameter).
        # Range 25–200 lets the user shrink/grow the icon relative
        # to the cell.  Since the rendered icon is computed as
        # ``size * 0.70 * (icon_scale / 100)`` and ``size`` is the
        # cell's ``_size_px``, the scale is automatically relative —
        # resizing the cell scales the icon with it.
        scale_row = QVBoxLayout()
        scale_row.setContentsMargins(20, 0, 0, 0)
        icon_scale_int = round(hexagon._icon_scale * 100)
        self._icon_scale_label = QLabel(f"Icon scale: {icon_scale_int}%")
        self._icon_scale_slider = QSlider(Qt.Horizontal)
        self._icon_scale_slider.setMinimum(25)
        self._icon_scale_slider.setMaximum(200)
        self._icon_scale_slider.setSingleStep(5)
        self._icon_scale_slider.setPageStep(10)
        self._icon_scale_slider.setValue(icon_scale_int)
        scale_row.addWidget(self._icon_scale_label)
        scale_row.addWidget(self._icon_scale_slider)
        label_layout.addLayout(scale_row)

        # Superimpose-text-over-icon checkbox (v0.6.9+).  Per user
        # direction: "we should have the choice to superimpose the
        # text label options we had earlier."  Only meaningful in
        # Icon mode — when on, the cell paints the icon AND the text
        # label (custom override or auto-letters) in a band over it.
        tover_row = QHBoxLayout()
        tover_row.addSpacing(20)
        self._text_over_icon_cb = QCheckBox(
            "Also show the text label over the icon"
        )
        self._text_over_icon_cb.setChecked(
            bool(getattr(hexagon, "_label_text_over_icon", False))
        )
        self._text_over_icon_cb.setToolTip(
            "Draw the cell's text label (custom text, or the "
            "auto-derived letters) on top of the icon instead of "
            "hiding it.  Uses the custom text from the box above "
            "when set, otherwise the auto letters."
        )
        tover_row.addWidget(self._text_over_icon_cb)
        tover_row.addStretch(1)
        label_layout.addLayout(tover_row)

        # Label opacity slider — multiplies the cell's transparency.
        # Always visible (applies to all modes including default
        # auto-letters).  Default 100 = same opacity as the cell.
        op_row = QVBoxLayout()
        label_op_int = round(hexagon._label_opacity * 100)
        self._label_opacity_label = QLabel(
            f"Label opacity: {label_op_int}%"
        )
        self._label_opacity_slider = QSlider(Qt.Horizontal)
        self._label_opacity_slider.setMinimum(20)
        self._label_opacity_slider.setMaximum(100)
        self._label_opacity_slider.setSingleStep(5)
        self._label_opacity_slider.setPageStep(10)
        self._label_opacity_slider.setValue(label_op_int)
        op_row.addWidget(self._label_opacity_label)
        op_row.addWidget(self._label_opacity_slider)
        label_layout.addLayout(op_row)

        layout.addWidget(label_grp)
        self._update_label_controls_enabled()
        layout.addStretch(1)

        # v0.6.21 — append the global menu-appearance group at the
        # end of the Shape & Size tab.  This is intentionally NOT
        # a separate tab — per user direction the controls live
        # alongside the cell shape/size controls so the "Save to
        # local / shared default" checkboxes apply to BOTH the
        # menu font/icon scale AND the cell shape/size choices.
        self._build_menu_appearance_tab(shape_tab_layout)

        # ---- Footer (lives outside the tab widget) -------------------------
        # The footer applies to the whole dialog regardless of which
        # tab is active.  Three buttons:
        #   * Reset to defaults -- reload the cell's authored state
        #     from the bound catalog (or branding defaults when
        #     unbound).  STAYS in the dialog so the user can keep
        #     tweaking from the reset baseline.
        #   * Cancel -- revert every change made since the dialog
        #     opened and close.  Implements the "I was experimenting,
        #     forget what I did" exit.
        #   * OK -- keep changes and close.  Since the dialog uses
        #     live-preview, OK just closes; the cell state is
        #     already updated.
        #
        # v0.8.0a25 -- introduced the OK / Cancel pattern.  The
        # window-frame [X] maps to Cancel so the modern "X means
        # discard unsaved changes" expectation is honoured -- see
        # ``closeEvent`` for the wiring.
        footer = QHBoxLayout()
        self._reset_btn = QPushButton("Reset to defaults")
        self._reset_btn.setToolTip(
            "Reload this cell's settings from the bound catalog file "
            "(or restore the app defaults when unbound).  Stays in "
            "this dialog so you can keep tweaking from there."
        )
        footer.addWidget(self._reset_btn)
        footer.addStretch()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setToolTip(
            "Discard every change you've made since opening this "
            "dialog and close."
        )
        footer.addWidget(self._cancel_btn)
        self._ok_btn = QPushButton("OK")
        self._ok_btn.setDefault(True)
        self._ok_btn.setToolTip(
            "Keep these settings and close."
        )
        footer.addWidget(self._ok_btn)
        outer_layout.addLayout(footer)

        # Capture the cell's state as it was when the dialog opened.
        # ``Cancel`` and the [X] button restore this snapshot so the
        # user can experiment without committing.  Computed AFTER
        # all the widgets have read ``hexagon._*`` but BEFORE any
        # signal handler fires (which is guaranteed because nothing
        # is connected yet -- connections happen in the block below).
        self._open_snapshot = self._capture_hex_state()
        # Track whether the user committed via OK so the closeEvent
        # knows whether to revert.  Defaults False -- if the user
        # clicks the [X], we treat it as Cancel.
        self._committed = False

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
        self._ok_btn.clicked.connect(self._on_ok)
        self._cancel_btn.clicked.connect(self._on_cancel)
        # Click-action dropdowns (V3 v0.3.5+) — write through to the
        # catalog on every change so the choice survives a restart.
        self._click_action_combo.currentIndexChanged.connect(
            self._on_click_action_changed
        )
        self._click_run_mode_combo.currentIndexChanged.connect(
            self._on_click_run_mode_changed
        )

        # Cell-label group connections (live preview).  Every value
        # change calls into the hex's apply_*_label_change methods
        # which mutate state, persist to QSettings, and call update()
        # so the cell repaints immediately as the user drags.
        self._label_mode_grp.idToggled.connect(self._on_label_mode_changed)
        self._text_input.textChanged.connect(self._on_label_text_changed)
        # New v0.8.0a25+ icon section -- browse-and-embed is one button
        # ``Choose image file…``; Library + Clear unchanged.
        self._icon_choose_btn.clicked.connect(self._on_icon_choose_file)
        self._icon_library_btn.clicked.connect(self._on_icon_library)
        self._icon_clear_btn.clicked.connect(self._on_icon_clear)
        self._icon_scale_slider.valueChanged.connect(
            self._on_icon_scale_changed
        )
        self._label_opacity_slider.valueChanged.connect(
            self._on_label_opacity_changed
        )
        # === OBSOLETE-ICON-UI-START (v0.8.0a25 -- delete after sign-off) ===
        # self._icon_browse_btn.clicked.connect(self._on_icon_browse)
        # self._icon_embed_btn.clicked.connect(self._on_icon_embed)
        # self._icon_unembed_btn.clicked.connect(self._on_icon_unembed)
        # === OBSOLETE-ICON-UI-END ===
        self._text_over_icon_cb.toggled.connect(
            self._on_text_over_icon_toggled
        )

        # Initial paint of the preview thumbnail.
        self._refresh_icon_preview()

    # ------------------------------------------------------------------
    # Show-time geometry — clamp into the visible work area
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Ensure the dialog lands fully on a connected display.

        The dialog is launched from a cell that may sit anywhere on
        the desktop, including pressed against a screen edge.  Before
        v0.5.1 the dialog's default position routinely landed mostly
        off-screen because Qt placed it relative to the parent cell.
        We override ``showEvent`` to find the screen the dialog's
        upper-left corner currently maps to (or, if it maps to none,
        the screen nearest the cell), then translate the dialog so
        the entire frame fits inside that screen's available area
        (``availableGeometry`` excludes the taskbar / dock).
        """
        super().showEvent(event)
        try:
            self._clamp_to_screen()
        except Exception as exc:  # noqa: BLE001
            _log(f"SettingsDialog._clamp_to_screen failed: {exc!r}")

    def _clamp_to_screen(self) -> None:
        from PySide6.QtGui import QGuiApplication
        # Use the dialog's current top-left as the hint.  If Qt has
        # already snapped it somewhere, that point is on whichever
        # screen Qt thinks owns the dialog.
        geom = self.frameGeometry()
        # Pick the screen containing the top-left of the dialog;
        # fall back to the screen under the parent cell; fall back
        # again to the primary screen.
        screen = QGuiApplication.screenAt(geom.topLeft())
        if screen is None and self._hex is not None:
            screen = QGuiApplication.screenAt(self._hex.frameGeometry().center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return  # No screens? Nothing sensible we can do.
        avail = screen.availableGeometry()
        new_x = geom.x()
        new_y = geom.y()
        # If wider/taller than the screen, pin to the top-left
        # corner and let the user scroll/resize.  Otherwise clamp.
        if geom.width() <= avail.width():
            new_x = min(max(new_x, avail.left()), avail.right() - geom.width())
        else:
            new_x = avail.left()
        if geom.height() <= avail.height():
            new_y = min(max(new_y, avail.top()), avail.bottom() - geom.height())
        else:
            new_y = avail.top()
        if (new_x, new_y) != (geom.x(), geom.y()):
            self.move(new_x, new_y)

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
        # v0.6.21 — also push to global cell defaults if user opted in.
        self._maybe_save_cell_defaults_globally()

    def _on_orient_changed(self, display_text: str) -> None:
        orient_key = self._ORIENT_DISPLAY.get(display_text, "flat-top")
        shape_key = self._SHAPE_DISPLAY.get(self._shape_combo.currentText(), "hexagon")
        self._hex.apply_shape_change(shape_key, orient_key)
        self._hex._save_settings()
        self._maybe_save_cell_defaults_globally()

    def _on_size_changed(self, value: int) -> None:
        # Snap to nearest multiple of 4.
        snapped = round(value / 4) * 4
        snapped = max(32, min(96, snapped))
        self._size_label.setText(f"Size: {snapped} px")
        self._hex.apply_size_change(snapped)
        self._hex._save_settings()
        self._maybe_save_cell_defaults_globally()

    def _maybe_save_cell_defaults_globally(self) -> None:
        """v0.6.21 — if the user has the menu-appearance tab's
        "Save to local/shared default" checkboxes ticked, also
        push the *current* cell's shape/orientation/size to the
        global CellDefaults storage so newly-spawned cells pick
        the choice up.  Gated by the same checkboxes (and the
        same shared-write capability) as the menu-appearance
        settings — one set of toggles controls both."""
        # Defensive: the menu tab is built late in __init__, so
        # very-early calls (before the checkboxes exist) must
        # silently no-op.
        local_cb = getattr(self, "_menu_save_local_cb", None)
        shared_cb = getattr(self, "_menu_save_shared_cb", None)
        if local_cb is None or shared_cb is None:
            return
        if not (local_cb.isChecked() or shared_cb.isChecked()):
            return
        try:
            from scriptree.shell.menu_appearance import (
                CellDefaults, save_cell_defaults,
            )
            values = CellDefaults(
                shape=self._hex._shape,
                orientation=self._hex._orientation,
                size_px=int(self._hex._size_px),
            )
            save_cell_defaults(
                values,
                save_local=local_cb.isChecked(),
                save_shared=shared_cb.isChecked(),
                branding=self._hex._branding,
            )
        except Exception as exc:  # noqa: BLE001
            _log(
                f"_maybe_save_cell_defaults_globally: "
                f"save failed: {exc!r}"
            )

    def _on_transp_changed(self, value: int) -> None:
        self._transp_label.setText(f"Transparency: {value}%")
        self._hex.apply_transparency_change(value / 100.0)
        self._hex._save_settings()

    def _on_always_on_top_changed(self, checked: bool) -> None:
        self._hex.apply_always_on_top_change(checked)
        self._hex._save_settings()

    # ---- Click-action slots (V3 v0.3.5+) ---------------------------------

    def _on_click_action_changed(self, _idx: int) -> None:
        """Persist the chosen click action to the bound catalog's
        ``cell.click_action`` field.  No-op when the cell has no
        catalog (the dropdown was a transient choice without a
        place to write to)."""
        action = str(self._click_action_combo.currentData() or "menu")
        cat = self._hex._catalog_path
        if not cat:
            return
        try:
            from scriptree.core.cell_metadata import write_for
            write_for(cat, click_action=action)
        except Exception as exc:  # noqa: BLE001
            _log(
                f"_on_click_action_changed: write_for({cat!r}) failed: "
                f"{exc!r}"
            )

    def _on_click_run_mode_changed(self, _idx: int) -> None:
        """Persist the run-mode choice to the bound catalog."""
        mode = str(self._click_run_mode_combo.currentData() or "sequential")
        cat = self._hex._catalog_path
        if not cat:
            return
        try:
            from scriptree.core.cell_metadata import write_for
            write_for(cat, click_run_mode=mode)
        except Exception as exc:  # noqa: BLE001
            _log(
                f"_on_click_run_mode_changed: write_for({cat!r}) failed: "
                f"{exc!r}"
            )

    # ---- Cell-label slots ------------------------------------------------

    # ------------------------------------------------------------------
    # v0.6.21 — Menu appearance tab (font + icon scale for popup menus)
    # ------------------------------------------------------------------

    def _build_menu_appearance_tab(self, layout) -> None:  # noqa: ANN001
        """Populate the Settings dialog's "Menu" tab with the
        font/icon scale controls + local/shared save toggles.

        Reads the current resolved values via
        ``menu_appearance.load_menu_appearance`` so the sliders
        reflect the live state (local QSettings override, shared
        file fallback, 125% default).  Every control writes back
        live via ``_apply_menu_appearance_change``.
        """
        from scriptree.shell.menu_appearance import (
            DEFAULT_FONT_PCT, DEFAULT_ICON_PCT,
            load_menu_appearance,
        )
        ma = load_menu_appearance(self._hex._branding)

        grp = QGroupBox("Menu font & icon scale")
        glayout = QVBoxLayout(grp)

        # ---- Font scale slider ---------------------------------------
        font_row = QVBoxLayout()
        self._menu_font_pct_label = QLabel(
            f"Font scale: {ma.font_pct}% of the OS default"
        )
        self._menu_font_pct_slider = QSlider(Qt.Horizontal)
        self._menu_font_pct_slider.setMinimum(50)
        self._menu_font_pct_slider.setMaximum(300)
        self._menu_font_pct_slider.setSingleStep(5)
        self._menu_font_pct_slider.setPageStep(10)
        self._menu_font_pct_slider.setValue(int(ma.font_pct))
        font_row.addWidget(self._menu_font_pct_label)
        font_row.addWidget(self._menu_font_pct_slider)
        glayout.addLayout(font_row)

        # ---- Fixed-pt override dropdown ------------------------------
        pt_row = QHBoxLayout()
        pt_row.addWidget(QLabel("Or fix the point size:"))
        self._menu_font_pt_combo = QComboBox()
        self._menu_font_pt_combo.addItem("Use percent", userData=0)
        for pt in (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32):
            self._menu_font_pt_combo.addItem(f"{pt} pt", userData=int(pt))
        # Select current value.
        idx = 0
        if ma.font_pt is not None and ma.font_pt > 0:
            for i in range(self._menu_font_pt_combo.count()):
                if self._menu_font_pt_combo.itemData(i) == int(ma.font_pt):
                    idx = i
                    break
        self._menu_font_pt_combo.setCurrentIndex(idx)
        pt_row.addWidget(self._menu_font_pt_combo, stretch=1)
        glayout.addLayout(pt_row)

        # ---- Icon scale slider ---------------------------------------
        icon_row = QVBoxLayout()
        self._menu_icon_pct_label = QLabel(
            f"Icon scale: {ma.icon_pct}% of the OS default"
        )
        self._menu_icon_pct_slider = QSlider(Qt.Horizontal)
        self._menu_icon_pct_slider.setMinimum(50)
        self._menu_icon_pct_slider.setMaximum(300)
        self._menu_icon_pct_slider.setSingleStep(5)
        self._menu_icon_pct_slider.setPageStep(10)
        self._menu_icon_pct_slider.setValue(int(ma.icon_pct))
        icon_row.addWidget(self._menu_icon_pct_label)
        icon_row.addWidget(self._menu_icon_pct_slider)
        glayout.addLayout(icon_row)

        # ---- Save destinations ---------------------------------------
        glayout.addSpacing(4)
        self._menu_save_local_cb = QCheckBox(
            "Save changes to local settings (this user)"
        )
        self._menu_save_local_cb.setChecked(True)
        glayout.addWidget(self._menu_save_local_cb)

        self._menu_save_shared_cb = QCheckBox(
            "Save changes to shared settings (all users on this machine)"
        )
        # v0.6.25 — gated by the appearance_shared_write capability
        # (renamed from menu_appearance_shared_write).  Accept the
        # legacy name too so installs that already deployed the
        # old capability file keep working.  The same capability
        # governs the cell shape/orientation/size global defaults
        # — one switch for everything in this tab.
        try:
            from scriptree.ui.permission_guards import perm_check
            can_shared = (
                perm_check("appearance_shared_write")
                or perm_check("menu_appearance_shared_write")
            )
        except Exception:  # noqa: BLE001
            can_shared = False
        self._menu_save_shared_cb.setChecked(False)
        if not can_shared:
            self._menu_save_shared_cb.setEnabled(False)
            self._menu_save_shared_cb.setToolTip(
                "Disabled by IT — capability not granted: "
                "appearance_shared_write"
            )
        glayout.addWidget(self._menu_save_shared_cb)

        # ---- Reset to default ----------------------------------------
        reset_row = QHBoxLayout()
        self._menu_reset_btn = QPushButton(
            f"Reset to default ({DEFAULT_FONT_PCT}% / {DEFAULT_ICON_PCT}%)"
        )
        reset_row.addStretch(1)
        reset_row.addWidget(self._menu_reset_btn)
        glayout.addLayout(reset_row)

        layout.addWidget(grp)

        # ---- Connections ---------------------------------------------
        self._menu_font_pct_slider.valueChanged.connect(
            self._on_menu_font_pct_changed
        )
        self._menu_font_pt_combo.currentIndexChanged.connect(
            self._on_menu_font_pt_changed
        )
        self._menu_icon_pct_slider.valueChanged.connect(
            self._on_menu_icon_pct_changed
        )
        self._menu_reset_btn.clicked.connect(
            self._on_menu_appearance_reset
        )

    def _current_menu_appearance(self):  # noqa: ANN202
        """Snapshot the dialog's controls into a ``MenuAppearance``."""
        from scriptree.shell.menu_appearance import MenuAppearance
        pt = self._menu_font_pt_combo.currentData()
        return MenuAppearance(
            font_pct=int(self._menu_font_pct_slider.value()),
            font_pt=(int(pt) if pt else None),
            icon_pct=int(self._menu_icon_pct_slider.value()),
        )

    def _apply_menu_appearance_change(self) -> None:
        """Persist the dialog's current state to whichever
        destinations are ticked.  Live — fires on every control
        change so the user sees the next popup menu reflect the
        new scale immediately."""
        from scriptree.shell.menu_appearance import save_menu_appearance
        values = self._current_menu_appearance()
        try:
            save_menu_appearance(
                values,
                save_local=self._menu_save_local_cb.isChecked(),
                save_shared=self._menu_save_shared_cb.isChecked(),
                branding=self._hex._branding,
            )
        except Exception as exc:  # noqa: BLE001
            _log(f"_apply_menu_appearance_change: save failed: {exc!r}")

    def _on_menu_font_pct_changed(self, value: int) -> None:
        self._menu_font_pct_label.setText(
            f"Font scale: {value}% of the OS default"
        )
        self._apply_menu_appearance_change()

    def _on_menu_font_pt_changed(self, _idx: int) -> None:
        # When a pt size is selected the percent slider is greyed —
        # it's an override.  "Use percent" re-enables it.
        pt = self._menu_font_pt_combo.currentData()
        self._menu_font_pct_slider.setEnabled(not bool(pt))
        self._menu_font_pct_label.setEnabled(not bool(pt))
        self._apply_menu_appearance_change()

    def _on_menu_icon_pct_changed(self, value: int) -> None:
        self._menu_icon_pct_label.setText(
            f"Icon scale: {value}% of the OS default"
        )
        self._apply_menu_appearance_change()

    def _on_menu_appearance_reset(self) -> None:
        from scriptree.shell.menu_appearance import (
            DEFAULT_FONT_PCT, DEFAULT_ICON_PCT,
        )
        self._menu_font_pct_slider.setValue(DEFAULT_FONT_PCT)
        self._menu_icon_pct_slider.setValue(DEFAULT_ICON_PCT)
        self._menu_font_pt_combo.setCurrentIndex(0)  # "Use percent"

    def _update_label_controls_enabled(self) -> None:
        """Enable / disable the per-mode controls based on the radio
        selection + cell state.  Called from radio toggle handler and
        at init."""
        is_text = self._label_mode_text_rb.isChecked()
        is_icon = self._label_mode_icon_rb.isChecked()
        has_icon_path = bool(self._hex._icon_path)
        has_embedded = bool(getattr(self._hex, "_icon_data_b64", ""))
        catalog_bound = bool(self._hex._catalog_path)

        self._text_input.setEnabled(is_text)
        self._icon_choose_btn.setEnabled(is_icon)
        if hasattr(self, "_icon_library_btn"):
            self._icon_library_btn.setEnabled(is_icon)
        self._icon_clear_btn.setEnabled(
            is_icon and (has_icon_path or has_embedded)
        )
        self._icon_scale_slider.setEnabled(is_icon)
        self._icon_scale_label.setEnabled(is_icon)
        # Superimpose-text checkbox only matters when an icon is shown.
        if hasattr(self, "_text_over_icon_cb"):
            self._text_over_icon_cb.setEnabled(is_icon)
        # === OBSOLETE-ICON-UI-START ===
        # Embed / Unembed buttons no longer exist in the new icon
        # section -- "Choose image file…" reads-and-embeds in one
        # step, so the manual Embed step is gone, and Unembed
        # (re-extract to disk) is YAGNI for now.
        # self._icon_embed_btn.setEnabled(
        #     is_icon and has_icon_path and catalog_bound
        # )
        # self._icon_unembed_btn.setEnabled(
        #     is_icon and has_embedded and catalog_bound
        # )
        # === OBSOLETE-ICON-UI-END ===

    def _on_label_mode_changed(self, btn_id: int, checked: bool) -> None:
        """Radio toggle in the Cell label group.

        Mode 0 (Default) clears both icon_path and text_label so the
        paint code falls back to auto-derived letters.
        Mode 1 (Custom text) sets text_label from the input field
        (or "" if empty) and clears icon_path.
        Mode 2 (Icon) keeps the cell's existing icon_path (or
        "(none)" until the user browses).
        """
        if not checked:
            return  # ignore the "unchecked" half of the toggle pair
        from PySide6.QtCore import QTimer
        if btn_id == 0:
            # Default: clear overrides.
            self._hex.apply_label_change(
                icon_path=None, text_label=None,
            )
        elif btn_id == 1:
            # Custom text — apply whatever's in the input now.
            self._hex.apply_label_change(
                icon_path=None,
                text_label=self._text_input.text() or None,
            )
        elif btn_id == 2:
            # Icon — keep the existing path (if any).  User clicks
            # Browse to assign one.  We deliberately PRESERVE any
            # custom text_label here (v0.6.9+): the paint code already
            # suppresses text when an icon is present *unless* the
            # superimpose-text-over-icon checkbox is on, so keeping
            # the text means the user can tick that box and get their
            # custom label back over the icon without retyping it.
            self._hex.apply_label_change(
                icon_path=self._hex._icon_path,
            )
        self._update_label_controls_enabled()

    def _on_label_text_changed(self, text: str) -> None:
        """Live update as the user types in the custom-text box."""
        if not self._label_mode_text_rb.isChecked():
            return
        self._hex.apply_label_change(text_label=text or None)

    # === OBSOLETE-ICON-UI-START (v0.8.0a25 -- delete after sign-off) ===
    # def _on_icon_browse(self) -> None:
    #     """Old browse-and-link handler.  Replaced by
    #     ``_on_icon_choose_file`` which reads-and-embeds in one step,
    #     so no new ``_icon_path`` links get written by the editor."""
    #     from PySide6.QtWidgets import QFileDialog
    #     chosen, _ = QFileDialog.getOpenFileName(
    #         self,
    #         "Select cell icon",
    #         self._hex._icon_path or "",
    #         "Images (*.png *.jpg *.jpeg *.svg *.ico *.bmp);;All files (*)",
    #     )
    #     if not chosen:
    #         return
    #     self._hex.apply_label_change(icon_path=chosen)
    #     self._icon_path_label.setText(chosen)
    #     self._icon_clear_btn.setEnabled(True)
    # === OBSOLETE-ICON-UI-END ===

    def _on_icon_choose_file(self) -> None:
        """Open a file picker; read the chosen image; embed it into the
        cell's catalog as base64.

        Replaces the old browse-and-link flow (which left the cell
        depending on an external file path that could go stale).
        When the cell isn't bound to a catalog (a bare standalone),
        the picked file is linked as ``_icon_path`` -- that's the
        only remaining write site for the legacy field and it's
        kept because there's nowhere else for the icon data to
        live in that case.
        """
        from PySide6.QtWidgets import QFileDialog
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Select cell icon",
            "",
            "Images (*.png *.jpg *.jpeg *.svg *.ico *.bmp);;All files (*)",
        )
        if not chosen:
            return

        # Make sure the cell is in Icon mode so the dialog state and
        # the painted result agree.
        self._label_mode_icon_rb.setChecked(True)

        if self._hex._catalog_path:
            # Embed into the bound catalog (portable).
            try:
                from scriptree.core.cell_metadata import embed_icon
                md = embed_icon(self._hex._catalog_path, chosen)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(
                    self, "Embed failed",
                    f"Could not embed the icon:\n\n{exc}",
                )
                return
            self._hex._icon_data_b64 = md.icon_data
            self._hex._icon_data_format = md.icon_format
            self._hex._icon_path = None
            self._hex._label_cache = None
            self._hex.update()
        else:
            # Unbound cell -- no catalog to embed into; keep the
            # external link as a fallback so the icon still paints.
            self._hex.apply_label_change(icon_path=chosen)
        self._refresh_icon_preview()
        self._update_label_controls_enabled()

    def _refresh_icon_preview(self) -> None:
        """Repaint the preview thumbnail in the Icon section + update
        the source-status label.

        Mirrors ``CellWindow.resolve_displayed_icon``: whatever the
        cell would actually paint is what shows in the 96x96 preview.
        When the resolved source is text/none, the preview area shows
        a friendly placeholder so the user knows it's not broken --
        just that no glyph is currently in play.
        """
        from PySide6.QtCore import QSize, Qt
        from PySide6.QtGui import QPixmap

        try:
            pix, source = self._hex.resolve_displayed_icon()
        except Exception as exc:  # noqa: BLE001
            pix, source = None, "none"
            _log(f"_refresh_icon_preview: resolve raised {exc!r}")

        if pix is not None and not pix.isNull():
            scaled = pix.scaled(
                QSize(80, 80),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._icon_preview_label.setPixmap(scaled)
        else:
            self._icon_preview_label.setPixmap(QPixmap())
            self._icon_preview_label.setText(
                "(text)" if source == "text" else "(none)"
            )

        # Status text describing the current source.
        status_text = {
            "embedded":
                "Source: <b>embedded</b> in this cell's catalog file.",
            "file":
                "Source: <i>external file link (legacy)</i>.  "
                "Pick a new icon to switch to embedded storage.",
            "auto":
                "Source: <b>auto-classified</b> bundled glyph "
                "(picked from the catalog's name + content).  "
                "Pick an icon below to override.",
            "text":
                "No glyph -- the cell renders text (custom label "
                "or auto-letters).  Switch to <b>Icon</b> mode "
                "above to use a glyph.",
            "none":
                "Nothing renders on this cell yet.  "
                "Switch to <b>Icon</b> mode above and pick one.",
        }.get(source, "")
        self._icon_source_label.setText(status_text)

    def _on_icon_library(self) -> None:
        """Pick a glyph from the shipped, trademark-safe ``icons/``
        set.  Per user direction: "I should have the option to change
        the icon … from the settings menu."

        When the cell is bound to a catalog the chosen icon is
        *embedded* (base64 PNG) so it travels with the file and
        renders in the plugin-less portable runtime; otherwise the
        bundled PNG path is linked directly.
        """
        from scriptree.shell.icon_assets import (
            bundled_icon_png_path, list_bundled_icons,
        )
        names = list_bundled_icons()
        if not names:
            QMessageBox.information(
                self, "Icon library unavailable",
                "The shipped icons/ set could not be located.",
            )
            return

        from PySide6.QtCore import QSize
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import (
            QDialog, QDialogButtonBox, QGridLayout, QToolButton,
            QVBoxLayout, QScrollArea, QWidget,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("Choose an icon")
        outer = QVBoxLayout(dlg)
        scroll = QScrollArea(dlg)
        scroll.setWidgetResizable(True)
        host = QWidget()
        grid = QGridLayout(host)
        grid.setSpacing(6)

        chosen: dict[str, str] = {}

        def _pick(nm: str) -> None:
            chosen["name"] = nm
            dlg.accept()

        cols = 5
        for i, nm in enumerate(names):
            p = bundled_icon_png_path(nm)
            btn = QToolButton()
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setText(nm)
            if p is not None:
                btn.setIcon(QIcon(str(p)))
                btn.setIconSize(QSize(40, 40))
            btn.setAutoRaise(True)
            btn.setFixedSize(84, 78)
            btn.clicked.connect(lambda _=False, n=nm: _pick(n))
            grid.addWidget(btn, i // cols, i % cols)

        scroll.setWidget(host)
        outer.addWidget(scroll)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        bb.rejected.connect(dlg.reject)
        outer.addWidget(bb)
        dlg.resize(480, 420)

        if dlg.exec() != QDialog.Accepted or "name" not in chosen:
            return

        png_path = bundled_icon_png_path(chosen["name"])
        if png_path is None:
            QMessageBox.warning(
                self, "Icon unavailable",
                f"Could not locate icon-{chosen['name']}.png.",
            )
            return

        # Make sure the cell is in Icon mode so the dialog state and
        # the painted result agree.
        self._label_mode_icon_rb.setChecked(True)

        if self._hex._catalog_path:
            # Embed into the bound catalog (portable).
            try:
                from scriptree.core.cell_metadata import embed_icon
                md = embed_icon(
                    self._hex._catalog_path, str(png_path),
                )
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(
                    self, "Embed failed",
                    f"Could not embed the icon:\n\n{exc}",
                )
                return
            self._hex._icon_data_b64 = md.icon_data
            self._hex._icon_data_format = md.icon_format
            self._hex._icon_path = None
            self._hex._label_cache = None
            self._hex.update()
        else:
            # Unbound cell — link the bundled PNG directly.
            self._hex.apply_label_change(icon_path=str(png_path))
        self._refresh_icon_preview()
        self._update_label_controls_enabled()

    def _on_icon_clear(self) -> None:
        """Clear every explicit icon storage slot on the cell.

        After clear, the cell falls through to the auto-classified
        glyph (when bound) or auto-letters.  We zero out BOTH the
        legacy ``_icon_path`` and the canonical ``_icon_data_b64``
        so a single Clear truly resets the icon state.
        """
        self._hex.apply_label_change(icon_path=None)
        self._hex._icon_data_b64 = ""
        self._hex._icon_data_format = ""
        self._hex._label_cache = None
        self._hex.update()
        self._refresh_icon_preview()
        self._icon_clear_btn.setEnabled(False)

    def _on_icon_scale_changed(self, value: int) -> None:
        """Live preview as the user drags the scale slider."""
        self._icon_scale_label.setText(f"Icon scale: {value}%")
        self._hex.apply_icon_scale_change(value / 100.0)

    def _on_label_opacity_changed(self, value: int) -> None:
        """Live preview for label opacity."""
        self._label_opacity_label.setText(f"Label opacity: {value}%")
        self._hex.apply_label_opacity_change(value / 100.0)

    def _on_text_over_icon_toggled(self, on: bool) -> None:
        """Live-toggle the superimpose-text-over-icon mode."""
        self._hex.apply_text_over_icon_change(bool(on))

    # === OBSOLETE-ICON-UI-START (v0.8.0a25 -- delete after sign-off) ===
    # The manual Embed and Unembed flows are gone -- the new
    # "Choose image file…" button reads-and-embeds in one step, and
    # the inverse "extract embedded icon back to a file" was YAGNI
    # in the field (no user ever asked for it, and it complicates
    # the storage story).  Kept commented for one release in case
    # we discover a downstream caller; delete after sign-off.
    #
    # def _on_icon_embed(self) -> None:
    #     if not self._hex._catalog_path: ...
    #     if not self._hex._icon_path: ...
    #     from scriptree.core.cell_metadata import embed_icon
    #     md = embed_icon(self._hex._catalog_path, self._hex._icon_path)
    #     self._hex._icon_data_b64 = md.icon_data
    #     self._hex._icon_data_format = md.icon_format
    #     self._hex._icon_path = None
    #     self._hex._label_cache = None
    #     self._hex.update()
    #     self._icon_path_label.setText("(icon embedded in catalog file)")
    #     self._update_label_controls_enabled()
    #
    # def _on_icon_unembed(self) -> None:
    #     if not self._hex._catalog_path: ...
    #     if not getattr(self._hex, "_icon_data_b64", ""): ...
    #     from scriptree.core.cell_metadata import unembed_icon_to_file
    #     md = unembed_icon_to_file(self._hex._catalog_path, chosen)
    #     self._hex._icon_path = md.icon_resolved_path or chosen
    #     self._hex._icon_data_b64 = ""
    #     self._hex._icon_data_format = ""
    #     self._hex._label_cache = None
    #     self._hex.update()
    #     self._icon_path_label.setText(self._hex._icon_path)
    #     self._update_label_controls_enabled()
    # === OBSOLETE-ICON-UI-END ===

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

    # ------------------------------------------------------------------
    # State capture / restore -- backbone of the OK / Cancel /
    # Reset semantics (v0.8.0a25+).
    # ------------------------------------------------------------------

    def _capture_hex_state(self) -> dict:
        """Snapshot every cell attribute the dialog can mutate.

        Used by ``Cancel`` (revert to open-time state) and as the
        common shape produced by ``_authored_state`` /
        ``_branding_default_state`` for ``Reset to defaults``.
        Keep this in lockstep with ``_apply_hex_state`` so a round-
        trip (capture -> apply) is the identity transform.
        """
        h = self._hex
        return {
            "shape": h._shape,
            "orientation": h._orientation,
            "size_px": h._size_px,
            "transparency": h._transparency,
            "always_on_top": h._always_on_top,
            "icon_path": h._icon_path,
            "icon_data_b64": h._icon_data_b64,
            "icon_data_format": h._icon_data_format,
            "text_label": h._text_label,
            "icon_scale": h._icon_scale,
            "label_opacity": h._label_opacity,
            "label_text_over_icon": getattr(
                h, "_label_text_over_icon", False,
            ),
            "fill_color": getattr(h, "_fill_color", ""),
            "text_color": getattr(h, "_text_color", ""),
            "click_action": getattr(h, "_click_action", "menu"),
            "click_run_mode": getattr(
                h, "_click_run_mode", "sequential",
            ),
        }

    def _apply_hex_state(self, snap: dict) -> None:
        """Push a state snapshot back into the cell + the dialog's
        widgets.  Uses the cell's ``apply_*`` methods so the cell
        repaints + persists in the same way an interactive change
        would.

        Widget signals are blocked during the bulk update so we
        don't cascade through the textChanged / valueChanged
        handlers; one final pass refreshes the icon preview and
        re-enables the per-mode controls.
        """
        h = self._hex

        # Block every signal that could re-trigger an apply while
        # we're already applying.
        widgets = [
            self._shape_combo, self._orient_combo,
            self._size_slider, self._transp_slider,
            self._always_on_top_cb,
            self._text_input,
            self._icon_scale_slider, self._label_opacity_slider,
        ]
        if hasattr(self, "_text_over_icon_cb"):
            widgets.append(self._text_over_icon_cb)
        if hasattr(self, "_click_action_combo"):
            widgets.append(self._click_action_combo)
        if hasattr(self, "_click_run_mode_combo"):
            widgets.append(self._click_run_mode_combo)
        for w in widgets:
            w.blockSignals(True)
        try:
            # Shape + orientation + size.
            h.apply_shape_change(snap["shape"], snap["orientation"])
            h.apply_size_change(snap["size_px"])
            h.apply_transparency_change(snap["transparency"])
            h.apply_always_on_top_change(snap["always_on_top"])

            # Icon storage -- push the raw fields and force a repaint.
            h._icon_path = snap["icon_path"]
            h._icon_data_b64 = snap["icon_data_b64"]
            h._icon_data_format = snap["icon_data_format"]
            h._text_label = snap["text_label"]
            h._icon_scale = snap["icon_scale"]
            h._label_opacity = snap["label_opacity"]
            h._label_text_over_icon = snap["label_text_over_icon"]
            h._fill_color = snap.get("fill_color", "")
            h._text_color = snap.get("text_color", "")
            h._click_action = snap.get("click_action", "menu")
            h._click_run_mode = snap.get(
                "click_run_mode", "sequential",
            )
            h._label_cache = None
            h._save_settings()
            h.update()

            # Sync widgets.
            self._shape_combo.setCurrentText(
                self._SHAPE_INTERNAL.get(snap["shape"], "Hexagon"),
            )
            self._orient_combo.setCurrentText(
                self._ORIENT_INTERNAL.get(
                    snap["orientation"], "Flat-top",
                ),
            )
            self._size_slider.setValue(snap["size_px"])
            self._size_label.setText(f"Size: {snap['size_px']} px")
            transp_int = round(snap["transparency"] * 100)
            self._transp_slider.setValue(transp_int)
            self._transp_label.setText(
                f"Transparency: {transp_int}%",
            )
            self._always_on_top_cb.setChecked(snap["always_on_top"])
            self._text_input.setText(snap["text_label"] or "")
            self._icon_scale_slider.setValue(
                round(snap["icon_scale"] * 100),
            )
            self._icon_scale_label.setText(
                f"Icon scale: {round(snap['icon_scale'] * 100)}%",
            )
            self._label_opacity_slider.setValue(
                round(snap["label_opacity"] * 100),
            )
            self._label_opacity_label.setText(
                f"Label opacity: {round(snap['label_opacity'] * 100)}%",
            )
            if hasattr(self, "_text_over_icon_cb"):
                self._text_over_icon_cb.setChecked(
                    bool(snap["label_text_over_icon"]),
                )
            # Sync the mode radio (icon if any icon storage is set,
            # text if text_label, else default).
            if snap["icon_path"] or snap["icon_data_b64"]:
                self._label_mode_icon_rb.setChecked(True)
            elif snap["text_label"]:
                self._label_mode_text_rb.setChecked(True)
            else:
                self._label_mode_default_rb.setChecked(True)
        finally:
            for w in widgets:
                w.blockSignals(False)

        # Repaint the preview thumbnail + status line.
        if hasattr(self, "_icon_preview_label"):
            self._refresh_icon_preview()
        self._update_orient_enabled()
        self._update_label_controls_enabled()

    def _authored_state(self) -> dict | None:
        """Snapshot built from the bound catalog file as it sits on
        disk -- the "as authored" state Reset returns to.

        Returns ``None`` when the cell has no bound catalog, in
        which case Reset falls back to ``_branding_default_state``.
        Read failures (corrupt JSON, missing file) also return
        ``None`` -- safer than half-applying.
        """
        from pathlib import Path
        cp = getattr(self._hex, "_catalog_path", None)
        if not cp:
            return None
        try:
            p = Path(cp)
            suffix = p.suffix.lower()
            if suffix == ".scriptree":
                from scriptree.core.io import load_tool
                obj = load_tool(cp)
            elif suffix == ".scriptreetree":
                from scriptree.core.io import load_tree
                obj = load_tree(cp)
            else:
                return None
        except Exception:  # noqa: BLE001
            return None

        # Both ToolDef and TreeDef carry the same cell_* field set.
        base = self._branding_default_state()
        base.update({
            "icon_path": getattr(obj, "cell_icon", "") or None,
            "icon_data_b64": getattr(obj, "cell_icon_data", "") or "",
            "icon_data_format": getattr(obj, "cell_icon_format", "") or "",
            "text_label": getattr(obj, "cell_text_label", "") or None,
            "icon_scale": getattr(obj, "cell_icon_scale", 1.0),
            "label_opacity": getattr(obj, "cell_label_opacity", 1.0),
            "label_text_over_icon": getattr(
                obj, "cell_text_over_icon", False,
            ),
            "fill_color": getattr(obj, "cell_fill_color", "") or "",
            "text_color": getattr(obj, "cell_text_color", "") or "",
            "click_action": getattr(
                obj, "cell_click_action", "menu",
            ) or "menu",
            "click_run_mode": getattr(
                obj, "cell_click_run_mode", "sequential",
            ) or "sequential",
        })
        return base

    def _branding_default_state(self) -> dict:
        """Snapshot built from branding defaults -- the fallback
        Reset target when there's no catalog to read from."""
        hex_cfg = self._hex._branding.get("hexagon", {})
        return {
            "shape": hex_cfg.get("shape", "hexagon"),
            "orientation": hex_cfg.get("orientation", "flat-top"),
            "size_px": hex_cfg.get("defaultSizePx", 56),
            "transparency": hex_cfg.get("defaultTransparency", 0.85),
            "always_on_top": hex_cfg.get("defaultAlwaysOnTop", True),
            "icon_path": None,
            "icon_data_b64": "",
            "icon_data_format": "",
            "text_label": None,
            "icon_scale": 1.0,
            "label_opacity": 1.0,
            "label_text_over_icon": False,
            "fill_color": "",
            "text_color": "",
            "click_action": "menu",
            "click_run_mode": "sequential",
        }

    # ------------------------------------------------------------------
    # Footer button handlers -- Reset, Cancel, OK.
    # ------------------------------------------------------------------

    def _on_reset(self) -> None:
        """Reset every visible setting to the cell's "authored"
        state.

        Authored state is, in priority order:

          1. The bound catalog file's ``cell.*`` block on disk --
             so if the user has set up an icon and saved the
             catalog, Reset returns the cell to *that* icon
             rather than wiping it.
          2. Branding defaults (shape, size, transparency,
             always-on-top, no icon, no text label) for
             unbound cells.

        Stays in the dialog so the user can keep tweaking from
        the reset baseline -- per the standard
        Reset / Cancel / OK pattern in modern dialogs.
        """
        snap = self._authored_state() or self._branding_default_state()
        self._apply_hex_state(snap)

    def _on_cancel(self) -> None:
        """Revert every change made since the dialog opened, then
        close.  Implements the "I was experimenting, forget it"
        exit path."""
        self._apply_hex_state(self._open_snapshot)
        self._committed = False
        self.close()

    def _on_ok(self) -> None:
        """Keep the current settings (already live in the cell)
        and close."""
        self._committed = True
        self.close()

    def closeEvent(self, event) -> None:  # noqa: ANN001 (Qt event)
        """Map the window-frame [X] to Cancel.

        The modern UX expectation is "X discards unsaved
        changes."  ``_committed`` is True only when the user
        clicked OK; any other path (frame close, Esc, alt-F4)
        falls through here and we revert before letting the
        close proceed.
        """
        if not self._committed:
            try:
                self._apply_hex_state(self._open_snapshot)
            except Exception as exc:  # noqa: BLE001
                _log(
                    f"SettingsDialog closeEvent: revert raised "
                    f"{exc!r} -- proceeding with close",
                )
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# PreferencesDialog — app-wide defaults (not per-hex)
# ---------------------------------------------------------------------------

class PreferencesDialog(QDialog):
    """Modal app-wide preferences dialog.

    Opened from any hex's right-click â†’ "Preferences…".

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
        browse_btn = QPushButton("Browse…")
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
        # v0.8.0a25 -- swap "Close" for "Cancel" so the
        # dismiss-without-saving action reads correctly.  "Close"
        # was misleading here because clicking it threw away every
        # change the user had made; "Cancel" makes that explicit.
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setToolTip(
            "Discard every change you've made since opening this "
            "dialog and close."
        )
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn)
        save_btn = QPushButton("OK")
        save_btn.setDefault(True)
        save_btn.setToolTip(
            "Save these preferences and close."
        )
        save_btn.clicked.connect(self._on_save)
        footer.addWidget(save_btn)
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
            f"PreferencesDialog: saved app/* — shape={shape_key} orient={orient_key} "
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
        # Never accept input — it's purely visual.
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
# _ShakeDetector — shake-to-unassociate (Bug 4)
# ---------------------------------------------------------------------------
# Standard mobile-app shake pattern: sample drag-direction at each move event
# using a sliding window of recent direction vectors.  Count direction
# reversals (consecutive vectors whose dot product is negative — they oppose
# each other).  If reversals exceed REVERSAL_THRESHOLD within WINDOW_MS, the
# shake is considered detected.
#
# Tuning constants (user-adjustable in a future settings panel):
#   BUFFER_SIZE         — number of direction samples in the sliding window.
#   REVERSAL_THRESHOLD  — minimum reversals to trigger a shake.
#   WINDOW_MS           — time window in milliseconds; older samples are pruned.
#   MIN_MOVE_PX         — minimum pixel movement to register a direction sample
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


# v0.8.0a1+ramps Bug 8 — monotonic counter for auto-naming freshly
# spawned rings ("Ring 1", "Ring 2", …) so the user can tell them
# apart in the merged-menu header and hover-tooltip before they
# bind a catalog or save a file.  Process-lifetime; resets on
# restart (loaded rings keep their on-disk filename so they don't
# need a serial).
_RING_SERIAL: int = 0


def _next_ring_serial() -> int:
    """Allocate the next per-session ring serial."""
    global _RING_SERIAL
    _RING_SERIAL += 1
    return _RING_SERIAL


# ---------------------------------------------------------------------------
# CellWindow
# ---------------------------------------------------------------------------

class CellWindow(QMainWindow):
    """Frameless, transparent, always-on-top hexagonal launcher window.

    Per ADR-001 §sub-decision-2, the constructor receives a branding dict
    (the parsed branding.config.json).  No brand literals live in this file.

    Link vs Dock (v0.6.16 — the conceptual model in one place)
    -----------------------------------------------------------
    Every cell has TWO independent parent-pointers:

    * **Link parent**  — ``_group_master_id`` (also exposed as
      :pyattr:`link_master_id`).  The master this cell logically
      belongs to.  Determines outline tint, save/exit-all
      propagation, and — v0.6.16+ — collapse propagation down the
      link tree.  Set once on join; **preserved on break-free**
      (a cell dragged out of its cluster stays linked); cleared
      only by the explicit "Leave group / Leave forest" gesture.

    * **Dock parent** — encoded as membership in
      ``master._positioned`` (the contiguous-cluster set).  The
      master whose physical drag this cell rigidly translates
      with.  A cell can be linked-but-not-docked
      (:pyattr:`is_loose_linked` → True): logically associated
      with the master, drawn with a dimmer outline, but NOT
      translated when the master drags.  Re-docking happens
      automatically when the snap engine fires.

    Hierarchy: links form a tree with the Forest as root.  Rings
    can be forest members (``ring._group_master_id == forest_id``)
    so a forest-member ring's own cells are *transitive* forest
    descendants — they collapse when the forest hub collapses
    (recursive ``_start_collapse``), but only their direct master's
    drag translates them.

    Instance roles
    --------------
    role = 'standalone' — an ordinary user-spawned hexagon.
    role = 'master'     — spawned when two standalone hexes dock edge-to-edge.
                          Carries source_a_id and source_b_id.

    Signals
    -------
    reshaped(hex_id: str)
        Emitted from apply_shape_change / apply_size_change so SnapEngine
        invalidates its vertex cache for this hex.

    Public harness-driveable hooks (ADR-001 Â§harness-driveable contract):
        move_to(x, y)    — move to logical screen coords
        click(mode)      — fire single/double/right click handler
        dock_with(other) — programmatic edge-dock (picks best edge pair)
        dump_state()     — serialisable snapshot dict
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
        is_forest_master: bool = False,
    ) -> None:
        # ----------------------------------------------------------------
        # Window flags — exact set from ADR-001 Â§sub-decision-2
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

        # Accept file drops from Explorer (.scriptree, .scriptreetree,
        # .scriptreering).  Behaviour depends on cell role; see
        # dragEnterEvent / dropEvent below.
        self.setAcceptDrops(True)

        # ----------------------------------------------------------------
        # Identity and role
        # ----------------------------------------------------------------
        self._id: str = hexagon_id if hexagon_id is not None else str(uuid.uuid4())
        self.role: Literal["standalone", "master"] = role
        self.source_a_id: str | None = source_a_id
        self.source_b_id: str | None = source_b_id
        # ----------------------------------------------------------------
        # Forest-master flag (V3 v0.3.15+)
        # ----------------------------------------------------------------
        # When True, this cell IS the top-level forest container
        # (see ``scriptree.shell.forest_controller``).  It looks and
        # behaves like a master cell — same size, shape, repack,
        # reflow, edge-fold, drag-translation — except for two
        # specific exemptions:
        #
        #   1. ``_check_master_validity``'s quorum check skips it.
        #      A normal master with < 2 members tears itself down;
        #      the forest persists even with 0 members because it's
        #      the workspace root, not a transient docking artefact.
        #
        #   2. The right-click menu adds forest-specific entries
        #      (Save forest, Auto-add, Forest settings, …) on top
        #      of the standard master menu.
        #
        # Set by ``ForestController`` when constructing the forest
        # cell; never True for cells spawned via standalone /
        # ``_try_spawn_master`` / ``_drop_spawn_member_and_link``.
        self._is_forest_master: bool = bool(is_forest_master)
        # Hook the ForestController registers when this cell is the
        # forest master — prepends forest-specific items to the
        # context menu.  See ``_show_context_menu`` for invocation.
        self._forest_menu_extension = None  # type: ignore[assignment]
        # v0.8.0a21 — same hook, parallel feature.  When this cell is
        # bound to a ``.scriptreetree``, ``TreeController.attach_to_cell``
        # registers a callback here that prepends a "Tree" submenu
        # with auto-discover actions (Refresh from sources, Auto-add
        # from this folder now, Tree settings…, Excluded items…).
        # Non-tree-bound cells skip this entirely.  See the parallel
        # ``forest_menu_extension`` hook + invocation in
        # ``_show_context_menu``.
        self._tree_menu_extension = None  # type: ignore[assignment]
        # Companion soft-reference holder.  ``TreeController`` sets
        # ``cell._tree_controller = self`` in ``attach_to_cell`` so
        # later operations (e.g. a deferred refresh, a settings
        # dialog opened from another path) can find the controller
        # off the cell instead of via a global registry.
        self._tree_controller = None  # type: ignore[assignment]

        # ----------------------------------------------------------------
        # Branding
        # ----------------------------------------------------------------
        self._branding = branding
        palette = branding.get("palette", {})
        hex_cfg = branding.get("hexagon", {})

        # ---- Branding defaults (overridden by QSettings below) ----------
        # v0.6.21 — global CellDefaults (load_cell_defaults) is
        # consulted BEFORE branding fallbacks for shape/orientation
        # /size so the user's "save as default" choices in the
        # Settings dialog actually shape new cells.  Per-cell
        # QSettings (loaded further down) still wins for an
        # existing cell that's already been customised.
        try:
            from scriptree.shell.menu_appearance import load_cell_defaults
            _cell_def = load_cell_defaults(branding)
        except Exception:  # noqa: BLE001
            _cell_def = None
        self._size_px: int = (
            int(_cell_def.size_px) if _cell_def is not None
            else hex_cfg.get("defaultSizePx", 56)
        )
        self._shape: str = (
            str(_cell_def.shape) if _cell_def is not None
            else hex_cfg.get("shape", "hexagon")
        )
        self._orientation: str = (
            str(_cell_def.orientation) if _cell_def is not None
            else hex_cfg.get("orientation", "flat-top")
        )
        self._transparency: float = hex_cfg.get("defaultTransparency", 0.85)
        self._always_on_top: bool = bool(hex_cfg.get("defaultAlwaysOnTop", True))

        # Branding-default fill — held separately so the user's
        # per-cell override can be reset back to it without re-
        # reading the branding config (V3 v0.3.6+).
        self._branding_fill_color = _parse_rgba_hex(
            palette.get("hexFill", "1f2937e6")
        )
        # Active fill — defaults to branding fill until the cell
        # binds a catalog whose ``cell.fill_color`` overrides it
        # (or until ``apply_fill_color_change`` runs from the
        # Settings dialog).  Alpha is preserved from the branding
        # default; see ``apply_fill_color_change`` for why.
        self._fill_color      = QColor(self._branding_fill_color)
        # User-set hex override (V3 v0.3.6+).  Empty when no
        # override is active — paint code uses ``_fill_color``
        # directly either way.  ``_fill_color_hex`` lets the
        # Settings dialog round-trip the user's choice without
        # losing precision through the QColor encode.
        self._fill_color_hex: str = ""
        # Cell text-colour override (V3 v0.3.8+).  Empty hex →
        # paint code falls back to the stroke-derived default.
        # Non-empty 6-digit ``#RRGGBB`` → that colour, modulated
        # at paint time by (transparency × label_opacity).  Mirrors
        # the fill-colour override pattern.
        self._text_color_hex: str = ""
        self._stroke_color    = _parse_rgba_hex(palette.get("hexStroke",    "9ca3afff"))
        self._highlight_color = _parse_rgba_hex(palette.get("hexHighlight", "60a5faff"))
        self._accent_color    = _parse_rgba_hex(palette.get("accent",       "f59e0bff"))
        self._menu_bg_color   = _parse_rgba_hex(palette.get("menuBg",       "0f172af0"))
        # Bug 5 — unassociated standalone hex gets a green outline.
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
        # Masters always use None — they show the merged tree of two sources.
        # ----------------------------------------------------------------
        self._catalog_path: str | None = None

        # ----------------------------------------------------------------
        # Per-cell visual label (v0.2.5).
        #
        # Resolution order at paint time (handled in paintEvent):
        #   1. ``_icon_path`` — path to a PNG/SVG/etc. shown centred
        #      and scaled to ~70 % of the cell's inscribed circle.
        #   2. ``_text_label`` — explicit user-assigned text, drawn
        #      with auto-resized font that fits the cell width.
        #   3. Auto-derived letters from the loaded catalog's name
        #      (see ``_derive_letters``).
        #   4. Nothing — empty cell shows just the shape.
        #
        # All three flavours render in the cell's translucent
        # foreground colour so they read as part of the cell rather
        # than a sticker on top.  Persisted in QSettings (per-cell)
        # and in .scriptreering files (per-saved-ring).
        # ----------------------------------------------------------------
        self._icon_path: str | None = None
        self._text_label: str | None = None
        # v0.8.0a1+ramps Bug 8 — process-lifetime auto-name for ring
        # masters that haven't been bound to a catalog or saved to a
        # ``.scriptreering`` yet.  Assigned in ``_try_spawn_master``
        # via ``_next_ring_serial()``; left None for cells and for
        # loaded rings (those derive their display name from their
        # file path).  Read by ``_popup_header_text`` and
        # ``_update_hover_tooltip`` so the user sees "Ring 3" instead
        # of the generic "Tree Ring" label.
        self._auto_ring_name: str | None = None
        # Embedded icon (base64 string + format) — populated when the
        # bound catalog has ``cell_icon_data`` set instead of an
        # external ``cell_icon`` path.  Both empty when no icon /
        # external path.  Paint code prefers _icon_data_b64 over
        # _icon_path so embedded icons survive even if the source
        # file moves on disk.
        self._icon_data_b64: str = ""
        self._icon_data_format: str = ""
        # Icon scale — multiplier of the natural inscribed-circle size
        # (which is ~70 % of the cell's diameter).  1.0 means "use the
        # natural size".  Range from the Settings dialog: 0.25 – 2.0.
        # Because the renderer multiplies by ``self._size_px * 0.7``,
        # the scale is automatically RELATIVE to the cell — resizing
        # the cell scales the icon with it.  Per user spec: "once
        # accepted this scale will automatically adjust with the
        # scaling of the cell shape."
        self._icon_scale: float = 1.0
        # Label opacity — multiplier of the cell's overall transparency.
        # 1.0 = label fully matches cell transparency.  Lower = fainter
        # label.  Independent of the cell-shape transparency so a user
        # can have a fully opaque cell with a faint letter, or vice
        # versa.
        self._label_opacity: float = 1.0

        # ----------------------------------------------------------------
        # Load persisted settings (overrides branding defaults).
        # Masters get fresh branding defaults — they do NOT inherit
        # per-hex settings of their source hexes.
        # ----------------------------------------------------------------
        if role == "standalone":
            self._load_settings()

        # Constructor catalog_path overrides persisted value (clone-spawn path).
        if catalog_path is not None:
            self._catalog_path = catalog_path

        # If we have a catalog (constructor arg, persisted setting, or
        # later load), pull cell-visual settings (icon, text, scale,
        # opacity) directly from its JSON.  These take precedence
        # over QSettings — per the V3 v0.2.7 user direction "the icon
        # settings should be stored in the json of the scriptree,
        # scriptreetree or scriptreering file the cell/ring is
        # associated with."  ``_label_cache`` is a runtime field so
        # we have to attribute-set it before any paint can happen;
        # _refresh_label_from_catalog reads/writes it.
        self._label_cache: tuple | None = None  # type: ignore[assignment]
        if self._catalog_path:
            try:
                self._refresh_label_from_catalog()
            except Exception as exc:  # noqa: BLE001
                _log(
                    f"refresh_label_from_catalog at init failed: "
                    f"{exc!r}; cell will use QSettings fallback"
                )

        # v0.8.0a21 -- if the bound catalog is a ``.scriptreetree``,
        # wire the auto-discover ``TreeController``.  The attach call
        # installs the right-click menu hook + schedules the
        # ``ChooseUpdateModeDialog`` on next-event-tick when
        # ``tree.auto_discover is None`` (legacy / fresh trees).
        # Non-tree catalogs (.scriptree / .scriptreering) are
        # ignored.  Idempotent: a later catalog rebind would need
        # to call ``_attach_tree_controller_if_applicable`` again
        # (currently not called from other paths -- TODO follow-up
        # to hot-reload on right-click "Load ScripTree…").
        self._attach_tree_controller_if_applicable()

        # ----------------------------------------------------------------
        # Pre-compute ShapeGeometry (also used by SnapEngine).
        # Stored as self._geom and refreshed by every apply_*_change call.
        # ----------------------------------------------------------------
        self._geom: ShapeGeometry = compute_polygon(self._shape, self._size_px, self._orientation)

        # ----------------------------------------------------------------
        # Hover and drag state
        # ----------------------------------------------------------------
        self._hovered: bool = False
        # v0.6.27 — custom hover-tip trigger.  enterEvent starts this
        # one-shot timer; on fire we show the cell's title via
        # ``_CellHoverTip``.  Reset on every mouseMoveEvent while the
        # cursor is over the cell (matches OS tooltip behaviour: the
        # tip appears after the cursor has been still for ~700 ms).
        self._hover_tip_timer = QTimer(self)
        self._hover_tip_timer.setSingleShot(True)
        self._hover_tip_timer.setInterval(700)
        self._hover_tip_timer.timeout.connect(self._show_hover_tip_now)

        # Manual drag state.
        # _press_global_pos  — where the mouse was pressed (global px).
        # _drag_offset       — global press pos minus window top-left at press.
        # _drag_started      — True once the 4 px manhattan threshold is crossed.
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
        # L6 fix: three independent throttled log sites used to
        # share ONE timestamp, so they clobbered each other —
        # making all three logs fire at irregular intervals, and
        # the group-move log permanently dead (moveEvent's own log
        # set the shared field to ``now`` ~30 lines earlier in the
        # same call, so ``now - field`` was always 0).  Each site
        # now owns its own timestamp.
        self._last_move_log_time: float = 0.0       # moveEvent (0.1s)
        self._last_drag_log_time: float = 0.0       # drag (1.0s)
        self._last_groupmove_log_time: float = 0.0  # group-move (1.0s)

        # Bug 2 — group-move: remember position at start of each moveEvent
        # so we can compute the per-frame delta.
        self._last_pos: QPoint | None = None

        # ----------------------------------------------------------------
        # Dock state — Amendment 2 (group-association model)
        # ----------------------------------------------------------------

        # For STANDALONE hexes:
        #   _group_master_id — id of the master whose group this hex belongs to.
        #                      None = not in any group.
        #   _docked_to       — ids of hexes currently positionally adjacent
        #                      (touching honeycomb edges). Cleared on break-free.
        self._group_master_id: str | None = None
        self._docked_to: set[str] = set()

        # v0.8.0 Phase 1 — the corrected link-tree relationship.  The
        # LINK graph (forest → rings → cells) is distinct from the DOCK
        # graph (spatial edge-adjacency).  ``_link_parent_id`` is the
        # link parent — the ring this cell belongs to, or the forest
        # for top-level cells, or None for the forest cell itself.
        # During Phase 1 this field is mirror-written alongside the
        # legacy ``_group_master_id`` so both stay in sync; readers
        # still use the legacy field.  Phase 4 swaps readers over to
        # ``_link_parent_id`` and Phase 9 deletes the legacy.  Always
        # write through :meth:`_set_link_parent` so the mirror is
        # never accidentally bypassed.
        self._link_parent_id: str | None = None

        # v0.8.0 Phase 3 — the DOCK graph: spatial edge-adjacency,
        # distinct from LINK.  ``_dock_partner_id`` is the single
        # cell/ring/forest this cell is currently sitting at the edge
        # of.  ``_dock_edge`` is the edge index of THE PARTNER (0..5
        # for hex, 0..3 for square) where this cell sits.  Both are
        # None when the cell is floating (not edge-adjacent to anyone).
        # ``_dock_children_by_edge`` is the reverse index: which cells
        # are docked TO me, keyed by edge of mine.  Used at drag-end
        # of a single cell to find which children's dock target was
        # just yanked away, so the Phase 5 re-find heuristic can fire.
        # Phase 3 writes these fields at snap-commit.  Phase 5 reads
        # them to drive dock break + re-find.
        self._dock_partner_id: str | None = None
        self._dock_edge: int | None = None
        self._dock_children_by_edge: dict[int, str] = {}

        # v0.6.35 — slot-based scene-graph layout (see
        # ``scriptree/shell/layout.py``).  When the cell is docked to
        # a master, ``_slot`` is the master's ring slot it occupies
        # (``("inner", N)`` or ``("outer", N)``).  When the user
        # drags the cell out of its dock cluster it goes floating
        # (``_slot = None``, ``_floating_intent = True``); the link
        # to the master via ``_group_master_id`` is preserved so
        # collapse / forest-click still pulls the cell back.
        # See ``docs/LLM/scenegraph_layout_plan.md`` for the model.
        self._slot: tuple[str, int] | None = None
        self._floating_intent: bool = False

        # Legacy shim — kept so SnapEngine's dock_group_of call (which reads
        # _dock_partners on some code paths) does not crash in-flight.
        # _dock_partners is no longer the source of truth for group membership.
        # Use _group_master_id / _docked_to instead.
        self._dock_partners: set[str] = set()   # DEPRECATED — shim only

        # For MASTER hexes:
        #   _members     — {member_id: QPoint} — every group member and its
        #                  current preferred screen position. ALWAYS a real
        #                  QPoint (never None).
        #   _positioned  — subset of _members currently in the contiguous
        #                  honeycomb cluster anchored at this master.
        #                  Master-drag translates only _positioned members.
        self._members: dict[str, QPoint] = {}
        self._positioned: set[str] = set()

        # Edge-fold auto-hide set (master only).
        # When the master is dragged near a screen edge, positioned members
        # whose bounding box would be >50% off-screen are hidden transiently.
        # These ids remain in _members and _positioned — only their visibility
        # is suppressed.  _auto_hidden is purely transient view state and is
        # NOT serialised to .scriptreering files.
        self._auto_hidden: set[str] = set()

        # v0.8.0a83 — REMEMBERED cell layout (master only).  DISTINCT from
        # ``_members`` (the current/possibly-temporary position written by the
        # engine, cascade, reflow, settle): this stores each member's offset
        # RELATIVE TO this hub as the user LAST DROPPED it — captured at a
        # user drag-end ONLY, never on a system relocation.  Keyed by the
        # member's normalised catalog path (``_member_offset_key`` — stable
        # across the member-id regeneration every launch/load), so it persists
        # in the ``.scriptreeforest`` (``ForestItem.rel_offset``) and rebinds
        # to whatever cell holds that tool/tree path next session.  Value =
        # ``(dx, dy)`` = member_top_left − hub_top_left.  Read by
        # ``_restore_remembered_offsets`` to slide members back to where the
        # user put them, engine-tiling only the ones whose remembered spot is
        # off-screen.
        self._remembered_offsets: dict[str, tuple[int, int]] = {}

        # Ring dirty-state flag (V3 v0.3.1).  Only meaningful on
        # master cells.  Set when a cell is added to or removed from
        # this master's group; cleared when the ring is saved.
        # Position-only mutations (drag, repack, drift snap-back) do
        # NOT set this flag — the user spec is "ask before close iff
        # membership has changed since save, but stay quiet for pure
        # rearrangements".  Initialised False; ``_try_spawn_master``
        # Case 1 sets it True on a fresh master so a never-saved
        # ring counts as dirty.  ``ring_io.load_ring`` resets it to
        # False after a successful load (the on-disk ring matches).
        self._ring_dirty: bool = False
        # On-disk ring file (.scriptreering) backing this master, if
        # any.  Set by ``save_ring`` / ``load_ring`` / the editor's
        # Open Cell Layout flow; ``None`` means brand-new ring.
        # Initialised here (was a lazy attribute pre-v0.3.1) so
        # ``_ring_needs_save_prompt`` and tests can check it
        # directly without ``getattr(..., None)``.
        self._saved_ring_path = None  # type: ignore[assignment]

        # Creation timestamp — used by _try_spawn_master to pick the oldest
        # canonical master when two groups merge.
        import time as _time_mod
        self._creation_time: float = _time_mod.monotonic()

        # ----------------------------------------------------------------
        # Master collapse/expand state machine.
        # Only meaningful when self.role == 'master'.
        # 'expanded'   — member hexes visible at their stored positions.
        # 'collapsing' — animation in flight toward master's centre.
        # 'collapsed'  — member hexes hidden, tucked inside master.
        # 'expanding'  — animation in flight outward to stored positions.
        # ----------------------------------------------------------------
        self._collapse_state: str = "expanded"
        # _home_positions is kept as a shim alias for _members so that
        # any remaining internal call to _shift_home_positions still works.
        # It IS the same dict object — mutations via either name are shared.
        self._home_positions: dict[str, QPoint] = self._members
        # Running animations keyed by hex_id — kept alive to avoid GC.
        self._collapse_animations: dict[str, QPropertyAnimation] = {}
        # v0.6.17 — opt-in: tuck this cell into its link-master when
        # the master collapses.  Default False (cells stay open).
        # ``_load_settings`` overrides for cells with persisted state;
        # this default is what masters and freshly-spawned cells use.
        self._collapse_with_master: bool = False

        # ----------------------------------------------------------------
        # Settings dialog (lazy — created on first open, then reused)
        # ----------------------------------------------------------------
        self._settings_dialog: SettingsDialog | None = None

        # ----------------------------------------------------------------
        # Menu state — per-hex, per ADR-001 sub-decision-4 identity rules.
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
        # _right_press_time — monotonic timestamp of the last right-press,
        #                     or None if no pending right-press.
        # _right_click_timer — QTimer that fires click("right") after the
        #                      OS double-click interval elapses, so a single
        #                      right-press still opens the context menu.
        # ----------------------------------------------------------------
        from PySide6.QtCore import QTimer as _QTimer
        self._right_press_time: float | None = None
        self._right_click_timer = _QTimer(self)
        self._right_click_timer.setSingleShot(True)
        self._right_click_timer.timeout.connect(self._fire_single_right_click)

        # ----------------------------------------------------------------
        # Master single-click deferral (Bug 6 — double-click preemption).
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
        # Standalone hexes are NOT deferred — their single-click expectation is
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

        # Hover tooltip — show what this cell/ring is for even before
        # any paint.  ``_refresh_label_from_catalog`` (called above
        # when a catalog is bound) already set it; this unconditional
        # call covers no-catalog cells, masters, and forests too.
        self._update_hover_tooltip()

        _log(
            f"CellWindow created id={self._id} role={self.role} "
            f"size={self._size_px}px shape={self._shape} orient={self._orientation} "
            f"transparency={self._transparency:.2f} aot={self._always_on_top}"
        )
        # v0.6.36 — trace cell construction.
        try:
            _trace.event(
                "CREATE",
                id=self._id[:8],
                role=self.role,
                size=self._size_px,
                shape=self._shape,
                orient=self._orientation,
            )
        except Exception:  # noqa: BLE001
            pass
        # Bug 2 — OS double-click interval verification.
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
        try:
            _trace.event("CLOSE", id=self._id[:8], role=self.role)
        except Exception:  # noqa: BLE001
            pass
        # Close the snap overlay if present.
        if self._snap_overlay is not None:
            self._snap_overlay.hide()
        # Unregister from registry (emits hexagonClosed).
        CellRegistry.instance().unregister(self._id)
        super().closeEvent(event)
        # v0.8.0a106 — manual last-window quit.  ``app`` runs with
        # ``setQuitOnLastWindowClosed(False)`` (cells are frameless windows; a
        # transient cell-close must not kill the app while siblings live), so Qt
        # will NOT auto-quit when the final window closes.  Closing the forest
        # hub (or the last cell) via the window-frame [X] therefore used to leave
        # the PROCESS alive headless — a lingering instance that (a) wastes
        # memory + can hold file locks, and (b) keeps owning the single-instance
        # named pipe, so every later launch HANDS OFF to the stale process
        # instead of starting fresh (newly-deployed code never runs).  Quit
        # explicitly once nothing is left to show.
        self._quit_if_app_empty()

    def _quit_if_app_empty(self) -> None:
        """v0.8.0a106 — quit the app when NO cells remain registered.

        "Empty" = no standalones AND no masters in the ``CellRegistry``.  Hidden
        cells (auto-hide / tray) stay REGISTERED, so this never quits a forest
        that's merely tucked away — only a genuinely empty app.  Idempotent:
        ``QApplication.quit()`` is safe to call more than once (e.g. it also
        fires on the final close inside ``_exit_all``)."""
        from scriptree.shell.cell_registry import CellRegistry
        reg = CellRegistry.instance()
        if not reg.standalones() and not reg.masters():
            _log("Last cell closed — quitting application (registry empty).")
            QApplication.quit()

    # ------------------------------------------------------------------
    # QSettings persistence  (ADR-001 Â§sub-decision-5)
    # ------------------------------------------------------------------

    def _settings_key(self, field: str) -> str:
        """Return the QSettings key for this hexagon instance and field."""
        return f"hexagon/{self._id}/{field}"

    def _load_settings(self) -> None:
        """Load per-hex settings; fall back to app/* defaults, then branding.

        Resolution order for each field:
          1. hexagon/<id>/<field>   — per-hex persisted setting
          2. app/default_<field>   — app-wide default set via Preferences dialog
          3. branding default      — self._<field> as set before this call
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

        # Per-cell visual label (icon path + text override).  Empty
        # string is treated as "unset" so legacy QSettings entries
        # without these keys behave the same as fresh installs.
        raw_icon = s.value(self._settings_key("icon_path"))
        self._icon_path = (
            raw_icon if isinstance(raw_icon, str) and raw_icon else None
        )
        raw_text = s.value(self._settings_key("text_label"))
        self._text_label = (
            raw_text if isinstance(raw_text, str) and raw_text else None
        )
        # Icon scale + label opacity (v0.2.6+).  Defaults are 1.0 if
        # unset.  Both clamped so a malformed QSettings value can't
        # produce an invisible / oversized label.
        try:
            self._icon_scale = max(0.25, min(2.0, float(
                s.value(self._settings_key("icon_scale"), 1.0)
            )))
        except (TypeError, ValueError):
            self._icon_scale = 1.0
        try:
            self._label_opacity = max(0.20, min(1.00, float(
                s.value(self._settings_key("label_opacity"), 1.0)
            )))
        except (TypeError, ValueError):
            self._label_opacity = 1.0
        # Superimpose-text-over-icon toggle (v0.6.9+).  QSettings
        # stores it as a string; coerce defensively.
        self._label_text_over_icon = _coerce_bool(
            s.value(self._settings_key("text_over_icon"), False)
        )
        # v0.6.17 — opt-in to tuck into the link-master when that
        # master collapses.  Default False per user spec: "If I
        # collapse a ring the cells that were on it should remain
        # open unless opted to close."  Only the cells that have
        # explicitly opted in via the right-click menu tuck.
        self._collapse_with_master = _coerce_bool(
            s.value(self._settings_key("collapse_with_master"), False)
        )

    def _save_settings(self) -> None:
        """Persist current per-hex settings to QSettings immediately."""
        s = QSettings()
        s.setValue(self._settings_key("shape"), self._shape)
        s.setValue(self._settings_key("orientation"), self._orientation)
        s.setValue(self._settings_key("size_px"), self._size_px)
        s.setValue(self._settings_key("transparency"), self._transparency)
        s.setValue(self._settings_key("always_on_top"), self._always_on_top)
        s.setValue(self._settings_key("catalog_path"), self._catalog_path or "")
        s.setValue(self._settings_key("icon_path"), self._icon_path or "")
        s.setValue(self._settings_key("text_label"), self._text_label or "")
        s.setValue(self._settings_key("icon_scale"), float(self._icon_scale))
        s.setValue(self._settings_key("label_opacity"), float(self._label_opacity))
        s.setValue(
            self._settings_key("text_over_icon"),
            bool(getattr(self, "_label_text_over_icon", False)),
        )
        s.setValue(
            self._settings_key("collapse_with_master"),
            bool(getattr(self, "_collapse_with_master", False)),
        )
        s.sync()

    # ------------------------------------------------------------------
    # Mask
    # ------------------------------------------------------------------

    def _apply_hex_mask(self, size_px: int) -> None:
        """Apply the shape clip region. Called at init and on screenChanged."""
        poly = compute_polygon(self._shape, size_px, self._orientation)
        self._geom = poly
        self.setMask(QRegion(poly.polygon))

    def _reassert_window_chrome(self) -> None:
        """Re-apply the hex mask + translucent background after a
        ``setWindowFlags()``-driven native-window recreation.

        a71: on Win11, changing window flags recreates the native HWND,
        which DISCARDS ``setMask()`` and can reset
        ``WA_TranslucentBackground``.  Without re-asserting them the cell
        renders as an opaque, unclipped rectangle and the painted glyph
        is lost -- the user-reported "the forest lost its icon" after a
        visibility-mode (Qt.Tool <-> Qt.Window / always-on-top) flag
        swap.  Safe to call on any cell; a no-op visually when the
        chrome was already intact.
        """
        try:
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self._apply_hex_mask(self._size_px)
            self.update()
        except Exception as exc:  # noqa: BLE001
            _log(f"_reassert_window_chrome: {exc!r}")

    # ------------------------------------------------------------------
    # Live shape / size / transparency / always-on-top apply methods
    # Per ADR-001 Amendment 1.
    # Each of these emits reshaped(self._id) so SnapEngine invalidates cache.
    # ------------------------------------------------------------------

    def _apply_shape_self(self, shape: str, orientation: str) -> None:
        """Per-cell shape/orientation update — does not propagate to a group.

        Internal helper used by both the public ``apply_shape_change``
        (which broadcasts to the cell's group, if any) and the dock-
        adoption code path that needs to set one cell's geometry to
        match a master's without triggering a recursive broadcast.
        """
        self._shape = shape
        self._orientation = orientation
        self._geom = compute_polygon(shape, self._size_px, orientation)
        self.setMask(QRegion(self._geom.polygon))
        self.update()
        self.reshaped.emit(self._id)
        # Notify registry so SnapEngine cache is invalidated.
        from scriptree.shell.cell_registry import CellRegistry
        CellRegistry.instance().hexagonReshaped.emit(self._id)

    def _apply_size_self(self, size_px: int) -> None:
        """Per-cell size update — does not propagate to a group.

        Internal helper — see ``_apply_shape_self`` rationale.
        """
        self._size_px = size_px
        self.resize(size_px, size_px)
        self._geom = compute_polygon(self._shape, size_px, self._orientation)
        self.setMask(QRegion(self._geom.polygon))
        self.update()
        self.reshaped.emit(self._id)
        from scriptree.shell.cell_registry import CellRegistry
        CellRegistry.instance().hexagonReshaped.emit(self._id)

    def apply_shape_change(self, shape: str, orientation: str) -> None:
        """Live-update shape (and orientation).

        Group-aware: if this cell is part of a master+members group,
        the master and every member adopt the new shape and the ring
        is repacked so all cells stay edge-touching with no overlap.
        """
        self._apply_group_geometry(shape=shape, orientation=orientation)

    def apply_size_change(self, size_px: int) -> None:
        """Live-update cell size.

        Group-aware: if this cell is part of a master+members group,
        the master and every member adopt the new size and the ring
        is repacked so all cells stay edge-touching with no overlap.
        """
        self._apply_group_geometry(size_px=size_px)

    def _apply_group_geometry(
        self,
        *,
        size_px: int | None = None,
        shape: str | None = None,
        orientation: str | None = None,
    ) -> None:
        """Apply size / shape / orientation to this cell's whole group.

        Resolution rules:

        * **Standalone** (no group) — applies only to ``self``.
        * **Member** — forwards to the master cell so master + every
          member update together, then triggers a repack.
        * **Master** — applies to ``self`` and every member, then
          repacks the ring around the new master geometry.

        Repacking guarantees: cells remain edge-touching where
        possible, no two cells share a slot, and members that would
        land off-screen are reassigned to the nearest valid on-screen
        slot.
        """
        from scriptree.shell.cell_registry import CellRegistry

        registry = CellRegistry.instance()

        # ---- Member case — defer to master --------------------------
        if self.role != "master" and self._group_master_id is not None:
            master = registry.get(self._group_master_id)
            if master is not None:
                master._apply_group_geometry(
                    size_px=size_px, shape=shape, orientation=orientation,
                )
                return
            # Master vanished — fall through to standalone update.

        # ---- Apply to self ------------------------------------------
        if shape is not None or orientation is not None:
            self._apply_shape_self(
                shape if shape is not None else self._shape,
                orientation if orientation is not None else self._orientation,
            )
        if size_px is not None:
            self._apply_size_self(size_px)

        # ---- Master case — propagate then repack --------------------
        if self.role == "master" and self._members:
            for mid in list(self._members.keys()):
                member = registry.get(mid)
                if member is None:
                    continue
                if shape is not None or orientation is not None:
                    member._apply_shape_self(
                        shape if shape is not None else member._shape,
                        orientation if orientation is not None else member._orientation,
                    )
                if size_px is not None:
                    member._apply_size_self(size_px)
            self._repack_members()

    def _reflow_members_after_master_move(self) -> None:
        """Re-evaluate every member's slot after the master has moved.

        v0.3.17 — try HOME first, then temp.

        ``self._members[mid]`` is the member's HOME slot — the
        position the user explicitly placed it at, expressed in the
        master's reference frame and shifted rigidly during master
        drag.  Member widget positions can DIVERGE from HOME when
        a previous reflow had to relocate them to a temp slot
        because HOME was off-screen.  This routine reconciles both:

          1. Move every member's widget to its HOME (``_members[mid]``).
             Members previously living at temp slots get the chance
             to return.
          2. Partition by on-/off-screen at HOME.
          3. For off-screen members, run a surgical repack — pass
             the on-screen ones as ``fixed`` so they retain HOME,
             and let off-screen members find a temp slot adjacent
             to other elements.

        Crucially, the surgical repack does NOT overwrite
        ``_members[mid]`` for non-fixed members; HOME is preserved
        across temp relocations so a future master move that brings
        HOME back on-screen restores the original layout.

        Pre-v0.3.17 history:
          * pre-v0.3.8: any non-canonical layout triggered a full
            repack on every master nudge.
          * v0.3.8:     repack only when AT LEAST ONE member was
            off-screen — but it was still a FULL repack of every
            member, blowing away on-screen ones too.
          * v0.3.16:    repack only the off-screen members; pass
            the on-screen ones to ``repack`` via the ``fixed``
            argument so their slots are pre-claimed.  Still
            overwrote ``_members`` for relocated members, so HOME
            was lost on the first temp relocation.
          * v0.3.17:    HOME preserved.  Step 1 above gives every
            member a chance to return to HOME on each master move;
            only those whose HOME is genuinely off-screen go to
            temp.

        During a master drag, members are translated rigidly with
        the master (cheap — no math).  When the drag ends, this
        routine runs the home-then-temp reconciliation.
        """
        if self.role != "master" or not self._members:
            return
        from scriptree.shell.cell_registry import CellRegistry
        from scriptree.shell.group_layout import screen_rect_for_master

        registry = CellRegistry.instance()

        # Step 1: try to restore each member to its HOME slot.
        # During a master drag the rigid-translation kept widget
        # and HOME in sync; after a previous temp relocation they
        # may have drifted apart.  Move the widget back so the
        # on-screen check below sees the HOME position.
        for mid, home_pt in list(self._members.items()):
            member = registry.get(mid)
            if member is None:
                continue
            cur = member.pos()
            if cur.x() != home_pt.x() or cur.y() != home_pt.y():
                # Eased slide back HOME (Mac-style); falls back to
                # instant when off-screen or below threshold.
                member._smooth_move(home_pt.x(), home_pt.y())

        # Step 2: partition by on-/off-screen at HOME.
        master_tl = (self.pos().x(), self.pos().y())
        screen_rect = screen_rect_for_master(master_tl, self._size_px)
        off_screen: list[str] = []
        on_screen: list[str] = []
        for mid, qp in self._members.items():
            if self._slot_on_screen(qp.x(), qp.y(), screen_rect):
                on_screen.append(mid)
            else:
                off_screen.append(mid)
        if not off_screen:
            self._check_edge_fold()
            return

        # Step 3: surgical repack for off-screen members only.
        self._repack_members(fixed=set(on_screen))

    @staticmethod
    def _slot_on_screen(
        tl_x: int, tl_y: int,
        screen_rect: tuple[int, int, int, int] | None,
    ) -> bool:
        """Helper for ``_reflow_members_after_master_move``."""
        if screen_rect is None:
            return True
        left, top, right, bottom = screen_rect
        return (
            tl_x >= left and tl_y >= top
            # The size component is checked in repack via slot_fits_on_screen;
            # here the test is conservative — top-left in-bounds.
            and tl_x < right and tl_y < bottom
        )

    def _set_link_parent(self, parent_id: "str | None") -> None:
        """v0.8.0 P1 — write the cell's link-parent pointer to both
        the legacy ``_group_master_id`` and the new
        ``_link_parent_id`` in lockstep.

        Phase 1 of the v0.8.0 link/dock split keeps both fields in
        sync so existing readers (which still use the legacy field)
        observe identical behaviour while the new field becomes
        available for Phase 2's link-driven cascade and Phase 3's
        snap-commit rewrite.  Phase 4 switches readers to the new
        field; Phase 9 deletes the legacy.

        Always route link-parent writes through this method.  A
        direct ``self._group_master_id = X`` (or ``= None``) that
        bypasses the mirror would create a state where one field
        is stale relative to the other, and Phase 4 tests would
        find the discrepancy.
        """
        self._group_master_id = parent_id
        self._link_parent_id = parent_id

    def _audit_membership(self) -> dict:
        """Defensive consistency check on this master's membership
        bookkeeping (v0.6.38).

        Symptoms the v0.6.37 trace exposed:

        * **Phantom ids in ``_positioned``** — an id that no longer
          exists in the registry (a closed pair-master left its
          id behind in the forest's positioned set).
        * **Orphaned cells** — cell.``_group_master_id`` is ``None``
          but ``_slot`` is still set (snap-commit pair-master spawn
          partially wired up state, then something else cleared the
          parent without clearing the slot).
        * **Linked-but-not-positioned cells** — cell.parent matches
          this master, has a ``_slot`` assigned, but the cell isn't
          in ``self._positioned``.  These cells SHOULD follow when
          the master drags but currently don't.
        * **Stale ``_members`` entries** — id is in ``_members``
          but the cell either doesn't exist or points its parent
          elsewhere.

        The helper fixes each case in place and returns a dict
        summarising what it changed.  Called from ``moveEvent``
        (before each group-translate) and from
        ``mousePressEvent`` (on drag start of a master) so the
        forest self-heals before the user notices a stale id.

        No-op when not a master.
        """
        if self.role != "master":
            return {}
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()

        report = {
            "phantom_positioned": 0,
            "orphaned_cleared": 0,
            "linked_not_positioned_added": 0,
            "stale_members_removed": 0,
        }

        # Step 1 — remove phantom ids from _positioned + _members.
        # An id with no registry entry is a leftover from a closed
        # cell / pair-master that wasn't cleaned up.
        for mid in list(self._members.keys()):
            if registry.get(mid) is None:
                self._members.pop(mid, None)
                self._positioned.discard(mid)
                self._dock_partners.discard(mid)
                self._auto_hidden.discard(mid)
                report["stale_members_removed"] += 1
                try:
                    _trace.event(
                        "AUDIT_STALE_MEMBER",
                        master=self._id[:8],
                        cell=mid[:8],
                    )
                except Exception:  # noqa: BLE001
                    pass

        for pid in list(self._positioned):
            if pid not in self._members:
                self._positioned.discard(pid)
                report["phantom_positioned"] += 1
                try:
                    _trace.event(
                        "AUDIT_PHANTOM_POSITIONED",
                        master=self._id[:8],
                        phantom=pid[:8],
                    )
                except Exception:  # noqa: BLE001
                    pass

        # Step 2 — for each member that claims this master as parent
        # AND has a _slot, ensure it's in _positioned.  Without this
        # the drag-cascade in moveEvent skips it and the cell gets
        # left behind when the master moves.
        for mid in list(self._members.keys()):
            m = registry.get(mid)
            if m is None:
                continue
            if m._group_master_id == self._id and m._slot is not None:
                if mid not in self._positioned:
                    self._positioned.add(mid)
                    report["linked_not_positioned_added"] += 1
                    try:
                        _trace.event(
                            "AUDIT_LINKED_REPOSITIONED",
                            master=self._id[:8],
                            cell=mid[:8],
                            slot=m._slot,
                        )
                    except Exception:  # noqa: BLE001
                        pass

        # Step 3 — re-parent orphan cells (parent=None) whose slot
        # is still set AND who appear in this master's _members.
        # The membership says "you're mine" — believe that side and
        # restore the parent pointer.
        for mid in list(self._members.keys()):
            m = registry.get(mid)
            if m is None:
                continue
            if m._group_master_id is None and m._slot is not None:
                m._group_master_id = self._id
                m._link_parent_id = self._id  # v0.8.0 P1 mirror
                if mid not in self._positioned:
                    self._positioned.add(mid)
                report["orphaned_cleared"] += 1
                try:
                    _trace.event(
                        "AUDIT_REPARENT_ORPHAN",
                        master=self._id[:8],
                        cell=mid[:8],
                        slot=m._slot,
                    )
                except Exception:  # noqa: BLE001
                    pass

        if any(report.values()):
            try:
                _trace.event(
                    "AUDIT_SUMMARY",
                    master=self._id[:8],
                    **{k: v for k, v in report.items() if v},
                )
            except Exception:  # noqa: BLE001
                pass

        return report

    def _cancel_member_smooth_moves(self) -> None:
        """v0.7.1 — stop any in-flight ``_smooth_move``
        animations on this master's members, snapping each to its
        animation's end value.

        Why this exists: ``_smooth_move`` runs a 180-260 ms
        QPropertyAnimation on a member's ``pos`` whenever the
        layout settles after a drag-release.  If the user starts
        ANOTHER master-drag before that animation finishes, the
        moveEvent GROUP_MOVE cascade adds per-frame deltas to a
        position that's simultaneously being eased toward an
        old target — the two forces fight, and members end up
        drifting away from the slot world position they were
        supposed to occupy.  This is the "icons out of alignment
        after a quick movement" symptom in the v0.7.0 ship.

        Cancelling the animation AND snapping to its end value
        gives the cascade a stable starting point: the cluster
        is at its final settled position when the new drag
        begins, so per-frame deltas keep relative positions
        intact.

        Cheap to call (a few dict lookups + maybe an animation
        stop per member); safe when no animations are running
        (just a no-op).
        """
        if self.role != "master":
            return
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()
        cancelled = 0
        for mid in list(self._members.keys()):
            m = registry.get(mid)
            if m is None:
                continue
            anim = getattr(m, "_pos_anim", None)
            if anim is None:
                continue
            try:
                end = anim.endValue()
            except Exception:  # noqa: BLE001
                end = None
            try:
                anim.stop()
            except Exception:  # noqa: BLE001
                pass
            m._pos_anim = None
            if end is not None:
                try:
                    m.move(end)
                except Exception:  # noqa: BLE001
                    pass
            cancelled += 1
        if cancelled:
            try:
                _trace.event(
                    "CANCEL_ANIMS",
                    master=self._id[:8],
                    cancelled=cancelled,
                )
            except Exception:  # noqa: BLE001
                pass

    def _compute_layout(
        self, *, instant: bool = True, pinned: set[str] | None = None,
    ) -> None:
        """The single slot-based layout authority (v0.6.35).

        Walks every member id in ``self._members`` and:

          1. If the member's ``_slot`` is None and
             ``_floating_intent`` is False, assigns a free slot
             via :func:`scriptree.shell.layout.find_free_slot`,
             with the back-toward-parent slot excluded and a
             global collision check against every other placed
             cell in the workspace.
          2. Computes the world position from the assigned slot
             and writes it back into ``self._members[mid]``
             (the canonical "where the member is now" map).
          3. Moves the widget — instant ``move()`` when
             ``instant=True`` (used at startup so the user never
             sees a glide from stale positions), eased
             ``_smooth_move`` otherwise.

        Floating members (``_slot is None`` AND
        ``_floating_intent`` True) are skipped — they own their
        own ``pos``, set by the user via drag.

        Off-screen members (slot computed lies outside the screen
        rect) get ``_auto_hidden`` and ``setVisible(False)``;
        slots that come back on-screen drop the hide.

        O(n) in the member count.  Called from ``_repack_members``
        (startup + spawn) and (in a future commit) from
        ``moveEvent`` during master drag.  Never on a timer.
        """
        if self.role != "master" or not self._members:
            return

        # v0.8.0a83 — ``pinned`` members were just placed at their REMEMBERED
        # offset by ``_restore_remembered_offsets`` and must NOT be re-tiled:
        # they are skipped in the pre-pass / Pass 1 / Pass 2 below, and their
        # target centres are fed into ``occupied_centres`` so the engine tiles
        # the remaining members AROUND them.  Empty by default -> identical to
        # pre-a83 behaviour.
        pinned = pinned or set()

        # v0.6.36 — trace entry.
        try:
            _trace.event(
                "LAYOUT_RUN",
                master=self._id[:8],
                pos=(self.pos().x(), self.pos().y()),
                size=self._size_px,
                members=len(self._members),
                instant=instant,
            )
        except Exception:  # noqa: BLE001
            pass

        from PySide6.QtGui import QGuiApplication
        from scriptree.shell.cell_registry import CellRegistry
        from scriptree.shell.layout import (
            find_free_slot, nearest_free_slot, slot_world_pos, is_on_screen,
        )

        # v0.7.4 — cancel any in-flight member smooth-move animations
        # before computing layout.  Without this, the legacy
        # ``_reflow_members_after_master_move`` (called immediately
        # before this from mouseReleaseEvent) starts smooth_move
        # animations toward stale ``_members[mid]`` HOMEs.  Pass 2
        # below only stops those animations when it needs to move
        # the widget (drift > 1 px); for cells already at their slot
        # world position via cascade, no move = no stop, and the
        # stale-target animations continue, pulling cells uniformly
        # off their slots.  Trace at 13:43:27 in
        # ``scriptree-layout-trace-20260523-134000-4432.log``:
        # every cell got a uniform (25, 25) drift from the legacy
        # reflow's smooth_move targets, producing visible overlap
        # at master in the bottom-right corner.  Pinned by
        # ``test_chaos_movement.py::
        # test_compute_layout_cancels_pending_smooth_moves``.
        try:
            self._cancel_member_smooth_moves()
        except Exception:  # noqa: BLE001
            pass

        registry = CellRegistry.instance()
        app_inst = QGuiApplication.instance()
        if app_inst is None:
            return

        # Screen rect: prefer the screen the master sits on; fall
        # back to the primary screen.
        screen = app_inst.screenAt(self.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        screen_rect = (
            avail.left(), avail.top(),
            avail.right() + 1, avail.bottom() + 1,
        )

        master_pos = (self.pos().x(), self.pos().y())

        # Build the "globally occupied centres" snapshot, plus the
        # set of slots already taken on this master.  Both are
        # passed to find_free_slot so a freshly-assigned slot
        # respects every other placed cell in the workspace.
        #
        # v0.6.39 — exclude this master's own members from the
        # snapshot.  Their current world positions are stale until
        # Pass 2 writes the slot-derived positions through.  When
        # the first member of a fresh master ran the layout, its
        # own pre-layout center (just east of the master, where it
        # was spawned) blocked slot ``inner,0`` (East) because the
        # 42 px collision threshold treated the cell as if it
        # already owned that slot.  ``find_free_slot`` then
        # cascaded through inner,1 NE, inner,2 NW, … leaving the
        # East/West slots empty and the ring with visible gaps
        # instead of an edge-tiled honeycomb.  Sibling collisions
        # among this master's own members are handled by
        # ``taken_slots`` + the incremental ``occupied_centres``
        # update in Pass 1, so excluding them from the initial
        # snapshot is safe and correct.
        my_member_ids = set(self._members.keys())
        occupied_centres: set[tuple[int, int]] = set()
        for c in registry.all():
            if c._id == self._id:
                continue
            if c._id in my_member_ids:
                continue
            # Forest hub + any docked cell anywhere counts.
            if c.isVisible():
                occupied_centres.add((
                    c.pos().x() + c._size_px // 2,
                    c.pos().y() + c._size_px // 2,
                ))
        # Also count this master's centre (a child should not
        # land on it).
        occupied_centres.add((
            self.pos().x() + self._size_px // 2,
            self.pos().y() + self._size_px // 2,
        ))
        # v0.8.0a83 — seed PINNED members' TARGET centres (from _members,
        # which holds their just-restored remembered spot) into the snapshot.
        # Own members are normally excluded above because their pre-layout
        # positions are stale; a pinned member's _members IS its final
        # position, so the engine must avoid tiling onto it.
        for _pid in pinned:
            _pp = self._members.get(_pid)
            if _pp is None:
                continue
            _pm = registry.get(_pid)
            _psz = _pm._size_px if _pm is not None else self._size_px
            occupied_centres.add((_pp.x() + _psz // 2, _pp.y() + _psz // 2))

        taken_slots: set[tuple[str, int]] = set()
        for mid in self._members:
            m = registry.get(mid)
            if m is None:
                continue
            if m._slot is not None:
                taken_slots.add(m._slot)

        # v0.7.3 — Pre-pass: any member whose CURRENT slot world
        # position is off-screen gets its slot cleared so Pass 1
        # below can reassign it via ``nearest_free_slot`` to a
        # free on-screen slot (typically an outer-ring slot in the
        # available quadrant).  Without this, a cluster dragged
        # to a screen edge leaves cells permanently auto-hidden
        # at slots whose world position falls off-screen, even
        # when there's plenty of free space in the on-screen
        # quadrant of the outer ring.  Symptom: user dragged
        # forest to bottom-right corner; NE/SE/S inner cells
        # got auto-hidden at attempted_pos like (1905, 945) past
        # screen right, instead of being reassigned to NW outer
        # slots in the upper-left direction where space existed.
        # The trace at 13:33:39.000-13:33:39.003 in
        # ``scriptree-layout-trace-20260523-133300-23204.log``
        # shows three AUTO_HIDE events with no corresponding
        # reassignment attempt.  Pinned by
        # ``test_chaos_movement.py::test_master_at_corner_uses_all_visible_slots``
        # and ``::test_off_screen_slot_gets_reassigned_to_on_screen``.
        for mid in list(self._members.keys()):
            m = registry.get(mid)
            if m is None:
                continue
            if mid in pinned:
                continue  # a83: restored at remembered offset — don't re-tile
            if m._slot is None:
                continue
            if m._floating_intent:
                continue
            slot_tl = slot_world_pos(
                master_pos, self._size_px, m._slot, m._size_px,
                master_orientation=self._orientation,
            )
            # a74: full-fit (1.0) -- release any slot whose cell isn't
            # WHOLLY on-screen so Pass 1 reassigns it to a fully-fitting
            # slot, instead of leaving it half-off-screen (which the
            # reveal clamp then shoved into a neighbour).
            if not is_on_screen(slot_tl, m._size_px, screen_rect, 1.0):
                # Release the slot so this cell can be reassigned.
                taken_slots.discard(m._slot)
                m._slot = None

        # Pass 1: assign slots to any member that doesn't have one
        # and isn't floating.
        for mid in list(self._members.keys()):
            m = registry.get(mid)
            if m is None:
                continue
            if mid in pinned:
                continue  # a83: restored at remembered offset — don't re-tile
            if m._slot is not None:
                continue
            if m._floating_intent:
                continue
            # v0.7.0 — bind to the slot NEAREST the cell's current
            # widget centre, not the first free index.  This fixes
            # the "snap committed cell to NE but layout reassigned
            # to N" jumble bug: the snap engine put the cell at a
            # specific edge of the master, and the next layout call
            # should keep it there.  For freshly-spawned cells that
            # appear at master.pos() (centred on master), all six
            # inner slots tie at the same distance and slot 0 wins
            # the lexicographic tiebreak — same behaviour as before.
            cur_centre = (
                m.pos().x() + m._size_px / 2.0,
                m.pos().y() + m._size_px / 2.0,
            )
            slot = nearest_free_slot(
                master_pos=master_pos,
                master_size=self._size_px,
                master_slot=self._slot,
                drop_centre=cur_centre,
                child_size=m._size_px,
                taken_slots=taken_slots,
                occupied_centres=occupied_centres,
                screen_rect=screen_rect,
                master_orientation=self._orientation,
                # a74: only commit a slot where the WHOLE cell fits on
                # screen, so the chosen position never needs clamping
                # (which would push it into an adjacent cell).
                fraction_required=1.0,
            )
            if slot is not None:
                m._slot = slot
                taken_slots.add(slot)
                # Update occupied_centres immediately so the next
                # cell in the loop sees this one as a collider.
                tl = slot_world_pos(
                    master_pos, self._size_px, slot, m._size_px,
                    master_orientation=self._orientation,
                )
                occupied_centres.add(
                    (tl[0] + m._size_px // 2, tl[1] + m._size_px // 2),
                )
                # v0.6.36 — trace the slot assignment.
                try:
                    _trace.event(
                        "SLOT_ASSIGN",
                        master=self._id[:8],
                        cell=m._id[:8],
                        slot=slot,
                        target_pos=tl,
                    )
                except Exception:  # noqa: BLE001
                    pass

        # Pass 2: compute world positions, write them through to
        # ``_members[mid]`` and the widget, handle visibility.
        for mid in list(self._members.keys()):
            m = registry.get(mid)
            if m is None:
                continue
            if mid in pinned:
                continue  # a83: restored at remembered offset — keep _members

            if m._slot is None:
                # Floating — leave widget alone, just sync the
                # _members map to the cell's owned pos.
                if m._floating_intent:
                    self._members[mid] = QPoint(m.pos().x(), m.pos().y())
                # v0.8.0a85 — neither slot nor floating intent = LIMBO: Pass 1
                # found no free slot where the whole cell fits on-screen.
                # Pre-a85 we auto-hid the member (setVisible(False)) and relied
                # on a LATER ``_compute_layout`` to slot it.  But if a docked
                # sibling or a non-member cell docked into the cluster keeps the
                # nearby slots occupied, no slot ever opens and the cell stays
                # GONE with no way back short of a manual reflow — the
                # user-reported "occasionally the cell docked to the forest just
                # disappears" (always-on-top mode, where the auto-hide visibility
                # manager isn't even involved).  Keep it VISIBLE at its current
                # position instead, and leave ``_slot`` unassigned so the next
                # pass tiles it the instant a slot frees up.  A visible
                # (possibly slightly-overlapping) cell beats a vanished one, and
                # for this forest (a handful of cells, never a genuinely
                # over-full 18-slot ring) limbo is always a transient blocking
                # failure, not real overflow.
                #
                # Gate on the cell being WHOLLY on-screen: only an on-screen
                # limbo cell is kept visible (the user's case — a centred hub's
                # directly-docked cell that momentarily can't grab a slot).  A
                # limbo cell that is actually OFF-screen (a member dragged past
                # the screen edge with no on-screen slot to rebind to) keeps the
                # legitimate a74/a80 auto-hide — which also preserves the
                # chaos-test invariant "no visible member fully off-screen".
                else:
                    cur_tl = (m.pos().x(), m.pos().y())
                    # Keep an on-screen limbo member VISIBLE only if it does NOT
                    # overlap any already-placed cell or the hub.  Limbo is
                    # entered precisely because the member's slots are blocked
                    # (taken / off-screen / COLLIDING), so its current spot may
                    # sit on top of a sibling or the hub — keeping it visible
                    # there would re-admit the a67/a74 visible-overlap class.
                    # Reuse the SAME polygon-SAT collision the slot engine uses
                    # (``any_polygon_collides`` over ``occupied_centres``, which
                    # already holds the hub centre + every Pass-1-slotted sibling
                    # + external visible cells), so a kept-visible cell never
                    # trips the chaos overlap invariant.  On overlap, fall back
                    # to auto-hide — better hidden than overlapping.
                    keep = is_on_screen(cur_tl, m._size_px, screen_rect, 1.0)
                    if keep:
                        from scriptree.shell import tiling as _tiling
                        c_spec = _tiling.shape_from_legacy(
                            m._shape, m._orientation,
                        )
                        ccx = cur_tl[0] + m._size_px / 2.0
                        ccy = cur_tl[1] + m._size_px / 2.0
                        others = [
                            (c_spec, m._size_px, (float(ox), float(oy)))
                            for ox, oy in occupied_centres
                        ]
                        if _tiling.any_polygon_collides(
                            c_spec, m._size_px, (ccx, ccy), others, slop_px=0.5,
                        ):
                            keep = False
                    if keep:
                        if mid in self._auto_hidden:
                            self._auto_hidden.discard(mid)
                        if not m.isVisible():
                            m.setVisible(True)
                        self._members[mid] = QPoint(cur_tl[0], cur_tl[1])
                        # Add to occupied_centres so a later limbo member in
                        # this same pass sees this one as a collider.
                        occupied_centres.add((
                            cur_tl[0] + m._size_px // 2,
                            cur_tl[1] + m._size_px // 2,
                        ))
                    else:
                        self._auto_hidden.add(mid)
                        if m.isVisible():
                            m.setVisible(False)
                continue

            tl = slot_world_pos(
                master_pos, self._size_px, m._slot, m._size_px,
                master_orientation=self._orientation,
            )
            new_x, new_y = tl
            self._members[mid] = QPoint(new_x, new_y)

            on = is_on_screen(tl, m._size_px, screen_rect, 1.0)
            if on:
                if mid in self._auto_hidden:
                    self._auto_hidden.discard(mid)
                    m.setVisible(True)
                    try:
                        _trace.event(
                            "AUTO_SHOW",
                            cell=m._id[:8],
                            master=self._id[:8],
                        )
                    except Exception:  # noqa: BLE001
                        pass
                # Move widget if drift > 1 px.
                if (
                    abs(m.pos().x() - new_x) > 1
                    or abs(m.pos().y() - new_y) > 1
                ):
                    try:
                        _trace.event(
                            "LAYOUT_MOVE",
                            cell=m._id[:8],
                            master=self._id[:8],
                            from_=(m.pos().x(), m.pos().y()),
                            to=(new_x, new_y),
                            instant=instant,
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    if instant:
                        prior = getattr(m, "_pos_anim", None)
                        if prior is not None:
                            try:
                                prior.stop()
                            except Exception:  # noqa: BLE001
                                pass
                            m._pos_anim = None
                        m.move(new_x, new_y)
                    else:
                        m._smooth_move(new_x, new_y, duration_ms=180)
            else:
                if mid not in self._auto_hidden:
                    self._auto_hidden.add(mid)
                    if m.isVisible():
                        m.setVisible(False)
                    try:
                        _trace.event(
                            "AUTO_HIDE",
                            cell=m._id[:8],
                            master=self._id[:8],
                            slot=m._slot,
                            attempted_pos=tl,
                        )
                    except Exception:  # noqa: BLE001
                        pass

        self.update()

    def _repack_members(
        self,
        *,
        fixed: set[str] | None = None,
        instant: bool = False,
    ) -> None:
        """Recompute and apply on-screen positions for every member.

        Uses ``group_layout.repack`` to:

        * Place each member on its nearest free first-ring slot whose
          top-left fits on the master's screen.
        * Spill into the outer ring when the inner ring is full.
        * Auto-hide members for which no on-screen slot is available.

        ``fixed`` (V3 v0.3.16+) — set of member ids whose positions
        should be preserved verbatim.  Their nearest-slot is marked
        as taken so non-fixed members don't overlap.  Used by
        ``_reflow_members_after_master_move`` for surgical repacks.
        ``None`` = legacy behaviour: every member up for reassignment.

        ``instant`` (v0.6.34) — when True, members move into their
        new slots via plain ``move()`` instead of ``_smooth_move``
        animation.  Used at forest startup so the user never sees
        the jumbled saved positions glide into the canonical
        layout; the cells just appear where they belong.

        Updates ``self._members`` (the authoritative dict of preferred
        positions) and re-runs ``_check_edge_fold`` so the badge count
        reflects the new visibility state.
        """
        if self.role != "master" or not self._members:
            return

        # v0.6.35 — canonical mode (no ``fixed`` set) now delegates
        # to the proven slot-based layout algorithm in
        # ``_compute_layout``.  Members without a ``_slot`` get one
        # assigned via the global-collision-aware ``find_free_slot``;
        # members with a ``_slot`` get their world position derived
        # from it.  This replaces the older centre-distance repack
        # that didn't account for honeycomb aliasing across
        # adjacent clusters (the "ring members floating off-axis
        # from their ring at startup" bug).
        #
        # Surgical mode (``fixed != None``) — used by
        # ``_reflow_members_after_master_move`` — keeps the older
        # path for now; that one is a tight in-drag inner loop and
        # the slot model + on-demand recompute haven't been wired
        # into it yet.  Listed in
        # ``docs/LLM/scenegraph_layout_plan.md`` as a follow-up.
        if fixed is None:
            self._compute_layout(instant=instant)
            return

        from scriptree.shell.cell_registry import CellRegistry
        from scriptree.shell.group_layout import (
            repack,
            screen_rect_for_master,
        )

        registry = CellRegistry.instance()
        master_tl = (self.pos().x(), self.pos().y())
        screen_rect = screen_rect_for_master(master_tl, self._size_px)

        member_positions: dict[str, tuple[int, int]] = {}
        for mid in self._members.keys():
            member = registry.get(mid)
            if member is None:
                # Use the stored preferred position as the input.
                stored = self._members[mid]
                member_positions[mid] = (stored.x(), stored.y())
            else:
                pos = member.pos()
                member_positions[mid] = (pos.x(), pos.y())

        new_positions = repack(
            master_top_left=master_tl,
            size_px=self._size_px,
            shape=self._shape,
            orientation=self._orientation,
            members=member_positions,
            screen_rect=screen_rect,
            fixed=fixed,
        )

        # Apply the new positions.  v0.3.17: in SURGICAL mode
        # (``fixed`` is non-None), this is a temp relocation —
        # widget moves but ``_members[mid]`` (HOME) must NOT be
        # overwritten so a future reflow can restore the member to
        # its original slot.  In CANONICAL mode (``fixed`` is
        # None — used by Case 1 of ``_try_spawn_master`` for fresh
        # ring spawn), the new positions ARE the HOME slots and
        # ``_members[mid]`` updates accordingly.
        is_surgical = fixed is not None
        for mid, new_tl in new_positions.items():
            member = registry.get(mid)
            if new_tl is None:
                # No on-screen slot — keep stored position, hide via
                # _check_edge_fold below.
                if member is not None:
                    self._auto_hidden.add(mid)
                    member.setVisible(False)
                continue
            new_x, new_y = new_tl
            if not is_surgical:
                self._members[mid] = QPoint(new_x, new_y)
            if member is not None:
                # Eased slide into the (re)packed slot; collapsed
                # members would not be visible yet, so re-show first
                # if needed and let the smooth move animate from
                # whatever position they have now.
                if mid in self._auto_hidden:
                    self._auto_hidden.discard(mid)
                    member.setVisible(True)
                if instant:
                    # v0.6.34 — startup path: snap to slot
                    # immediately so the user never sees the
                    # stale-saved-positions jumble glide into
                    # place.  Kills any pending eased animation
                    # first to avoid the new position being
                    # over-written next frame.
                    prior = getattr(member, "_pos_anim", None)
                    if prior is not None:
                        try:
                            prior.stop()
                        except Exception:  # noqa: BLE001
                            pass
                        member._pos_anim = None
                    member.move(new_x, new_y)
                else:
                    member._smooth_move(new_x, new_y, duration_ms=260)

        # Refresh badge / visibility for any members that changed state.
        self._check_edge_fold()
        self.update()

    def apply_transparency_change(self, alpha: float) -> None:
        """Live-update fill transparency (0.30–1.00 alpha multiplier on fill colour)."""
        self._transparency = max(0.30, min(1.00, alpha))
        self.update()

    def apply_fill_color_change(self, hex_rgb: str) -> None:
        """Live-update the cell's fill colour (V3 v0.3.6+).

        ``hex_rgb`` is either a 6-digit ``"#RRGGBB"`` string (any
        case, ``#`` optional) or an empty string to clear the
        override and revert to the branding default.

        Alpha behaviour: the user's RGB controls *just* the colour.
        The cell's existing ``_fill_color`` alpha (typically ``e6``
        from the branding default) is preserved — that way an
        existing transparency slider doesn't drift just because the
        user picked a new hue.  The ``transparency`` slider in the
        Settings dialog controls alpha as a separate axis.

        Persistence: the new value is written through to the bound
        catalog's ``cell.fill_color`` field via
        ``cell_metadata.write_for`` so the choice travels with the
        file.  Cells with no catalog keep the override in memory
        only.
        """
        from ..core.cell_metadata import _normalise_hex_rgb

        canonical = _normalise_hex_rgb(hex_rgb)
        # Compute the new QColor.  Empty canonical == revert.
        if canonical:
            r = int(canonical[1:3], 16)
            g = int(canonical[3:5], 16)
            b = int(canonical[5:7], 16)
            existing_alpha = self._fill_color.alpha()
            self._fill_color = QColor(r, g, b, existing_alpha)
        else:
            # Reset: copy the branding default verbatim.
            self._fill_color = QColor(self._branding_fill_color)
        self._fill_color_hex = canonical

        self.update()

        # Persist to the bound catalog if any.  Failures log + no-op
        # so the in-memory change still takes effect for this session.
        if self._catalog_path:
            try:
                from scriptree.core import cell_metadata as _cm  # noqa: F401
                from scriptree.core.cell_metadata import write_for as _write_for
                _write_for(self._catalog_path, fill_color=canonical)
            except Exception as exc:  # noqa: BLE001
                _log(
                    f"apply_fill_color_change: write_for({self._catalog_path!r}) "
                    f"failed: {exc!r}"
                )

    def apply_text_color_change(self, hex_rgb: str) -> None:
        """Live-update the cell's label text colour (V3 v0.3.8+).

        ``hex_rgb`` is either a 6-digit ``"#RRGGBB"`` string (any
        case, ``#`` optional) or an empty string to clear the
        override — paint code then falls back to the stroke-derived
        default colour.

        Alpha behaviour: the override is RGB-only.  Effective alpha
        at paint time is ``transparency × label_opacity`` (same as
        the default-stroke path), so the label always tracks the
        cell's overall translucency settings.

        Persistence: when the cell is bound to a catalog, the new
        value is written through to ``cell.text_color`` via
        ``cell_metadata.write_for``.  Cells without a catalog keep
        the override in memory only.
        """
        from ..core.cell_metadata import _normalise_hex_rgb

        canonical = _normalise_hex_rgb(hex_rgb)
        self._text_color_hex = canonical

        self.update()

        if self._catalog_path:
            try:
                from scriptree.core.cell_metadata import write_for as _write_for
                _write_for(self._catalog_path, text_color=canonical)
            except Exception as exc:  # noqa: BLE001
                _log(
                    f"apply_text_color_change: write_for({self._catalog_path!r}) "
                    f"failed: {exc!r}"
                )

    # ------------------------------------------------------------------
    # Cell-label apply_* (live-update from Settings dialog)
    # ------------------------------------------------------------------

    _UNSET = object()  # sentinel for "don't change this attribute"

    def apply_label_change(
        self,
        *,
        icon_path: str | None | object = _UNSET,
        text_label: str | None | object = _UNSET,
    ) -> None:
        """Live-update the cell's label override fields and persist.

        ``icon_path`` and ``text_label`` accept a sentinel
        ``_UNSET`` (the default) so callers can update only one
        without clobbering the other.  Pass ``None`` to clear, or a
        string to set.

        Persistence destination depends on whether the cell is bound
        to a catalog (``.scriptree`` / ``.scriptreetree``):
          * If yes — write to the catalog JSON's ``cell`` sub-object
            (per V3 v0.2.7 user direction).  ``icon_path`` is
            normalised relative to the catalog when possible.
          * If no — fall back to QSettings (transient cells without
            a bound catalog still need somewhere to keep their
            preference).

        Always invalidates ``_label_cache`` (auto-letters cache) and
        repaints.
        """
        if icon_path is not self._UNSET:
            self._icon_path = icon_path  # type: ignore[assignment]
        if text_label is not self._UNSET:
            self._text_label = text_label  # type: ignore[assignment]
        # Invalidate auto-label cache; the new override may be in
        # effect on the next paint.
        self._label_cache = None

        self._persist_label_state(
            icon_changed=icon_path is not self._UNSET,
            text_changed=text_label is not self._UNSET,
        )
        self.update()

    def apply_icon_scale_change(self, scale: float) -> None:
        """Live-update the icon scale multiplier (0.25–2.0)."""
        self._icon_scale = max(0.25, min(2.0, scale))
        self._persist_label_state(scale_changed=True)
        self.update()

    def apply_label_opacity_change(self, opacity: float) -> None:
        """Live-update the label opacity multiplier (0.20–1.00)."""
        self._label_opacity = max(0.20, min(1.00, opacity))
        self._persist_label_state(opacity_changed=True)
        self.update()

    def apply_text_over_icon_change(self, on: bool) -> None:
        """Live-toggle the superimpose-text-over-icon mode (v0.6.9+)."""
        self._label_text_over_icon = bool(on)
        self._persist_label_state(text_over_icon_changed=True)
        self.update()

    def _persist_label_state(  # noqa: C901
        self,
        *,
        icon_changed: bool = False,
        text_changed: bool = False,
        scale_changed: bool = False,
        opacity_changed: bool = False,
        text_over_icon_changed: bool = False,
    ) -> None:
        from pathlib import Path
        """Persist the cell's label state to wherever it belongs.

        When the cell is bound to a ``.scriptree`` / ``.scriptreetree``
        catalog, writes to the catalog JSON's ``cell`` sub-object so
        the icon ships with the tool/tree definition.  Otherwise
        falls back to QSettings (the v0.2.6 behaviour).

        ``*_changed`` flags let us write only the field that the
        user actually changed — keeps the other fields untouched on
        disk so a no-op save doesn't clobber data the catalog file
        carried before this cell loaded it.
        """
        catalog = self._catalog_path
        # No catalog → fall back to QSettings (unbound cell).
        if not catalog or not Path(catalog).is_file():
            self._save_settings()
            return

        # Catalog-bound cell — write the changed fields back to the
        # JSON.  Unchanged fields are passed as None so write_for
        # leaves them alone.
        try:
            from scriptree.core.cell_metadata import write_for
            kwargs = {}
            if icon_changed:
                kwargs["icon"] = self._icon_path or ""
            if text_changed:
                kwargs["text_label"] = self._text_label or ""
            if scale_changed:
                kwargs["icon_scale"] = float(self._icon_scale)
            if opacity_changed:
                kwargs["label_opacity"] = float(self._label_opacity)
            if text_over_icon_changed:
                kwargs["text_over_icon"] = bool(
                    getattr(self, "_label_text_over_icon", False)
                )
            if not kwargs:
                # Initial sync — write everything.
                kwargs = {
                    "icon": self._icon_path or "",
                    "text_label": self._text_label or "",
                    "icon_scale": float(self._icon_scale),
                    "label_opacity": float(self._label_opacity),
                    "text_over_icon": bool(
                        getattr(self, "_label_text_over_icon", False)
                    ),
                }
            write_for(catalog, **kwargs)
            _log(
                f"persisted cell label to catalog {Path(catalog).name!r} "
                f"(changed: {kwargs!r})"
            )
        except Exception as exc:  # noqa: BLE001
            _log(
                f"_persist_label_state: write_for({catalog!r}) failed: "
                f"{exc!r} — falling back to QSettings"
            )
            self._save_settings()

    def _read_click_action(self) -> str:
        """Return the cell's effective click action ("menu" or "run").

        Resolution (V3 v0.3.5+):

        * ``cell_click_to_run`` capability is denied → always "menu".
          The capability is the org-level kill switch — without it,
          single-click can never auto-run regardless of catalog
          settings.
        * Catalog has ``cell.click_action == "run"`` and the cell
          has a bound catalog → "run".
        * Anything else → "menu" (default, pre-v0.3.5 behaviour).
        """
        try:
            from ..ui.permission_guards import perm_check
            if not perm_check("cell_click_to_run"):
                return "menu"
        except Exception:  # noqa: BLE001
            return "menu"
        catalog = self._catalog_path
        if not catalog:
            return "menu"
        try:
            from scriptree.core.cell_metadata import read_for
            md = read_for(catalog)
        except Exception:  # noqa: BLE001
            return "menu"
        return "run" if md.click_action == "run" else "menu"

    def _read_click_run_mode(self) -> str:
        """Return the cell's effective run mode ("sequential" or
        "parallel"), defaulting to "sequential" if anything goes
        wrong loading the catalog."""
        catalog = self._catalog_path
        if not catalog:
            return "sequential"
        try:
            from scriptree.core.cell_metadata import read_for
            md = read_for(catalog)
        except Exception:  # noqa: BLE001
            return "sequential"
        return (
            "parallel" if md.click_run_mode == "parallel" else "sequential"
        )

    def _attach_tree_controller_if_applicable(self) -> None:
        """Synchronise the cell's ``TreeController`` attachment
        with the currently-bound catalog.  Three transitions:

        * **Attach**: no controller, catalog is a ``.scriptreetree``
          → instantiate ``TreeController(catalog)``, call
          ``attach_to_cell(self)``.  The first-load chooser may
          fire on the next event tick if the tree has no
          ``auto_discover`` block.
        * **Rebind**: controller exists but ``controller.tree_file``
          doesn't match the current catalog (user did "Load
          ScripTree…" → different ``.scriptreetree``, or "Save
          as…" → renamed the catalog on disk).  Drop the existing
          controller and re-attach with the new file.
        * **Detach**: controller exists but the catalog is now
          ``None`` or a non-tree file (user did "Clear catalog"
          or loaded a ``.scriptree``).  Clear the menu hook + the
          back-reference so the right-click menu drops the
          stale Tree submenu.

        Failure modes are swallowed (logged, not raised):

        * Catalog file vanished between bind and attach → log and
          skip; the right-click menu won't have the Tree submenu.
        * ``TreeController`` import fails (Qt unavailable in some
          headless test paths) → log and skip.

        The cell remains fully functional in all failure cases;
        only the discovery feature is unavailable.

        Called from ``__init__`` for the constructor binding AND
        from every runtime ``_catalog_path`` mutation site:

        * Context-menu "Clear catalog"   (catalog → None)
        * Context-menu "Load ScripTree…" / drag-drop / recent
          (catalog → new path)  -- via ``_bind_catalog_to_self``
        * Context-menu "Save as…"        (catalog → new path)

        Always call AFTER the assignment to ``_catalog_path`` and
        the matching ``_save_settings`` so the new state is fully
        persisted before any first-load chooser fires.
        """
        cat = getattr(self, "_catalog_path", None)
        is_tree = bool(cat) and cat.lower().endswith(".scriptreetree")
        current = getattr(self, "_tree_controller", None)

        # --- DETACH or REBIND when the current controller no longer
        # matches the current catalog.
        if current is not None:
            current_file = getattr(current, "tree_file", "")
            try:
                # Compare normalised absolute paths so case / slash
                # variation doesn't trigger a needless rebind.
                from pathlib import Path
                same = bool(cat) and (
                    Path(current_file).resolve()
                    == Path(cat).resolve()
                )
            except (OSError, ValueError):
                same = (cat or "").lower() == (current_file or "").lower()
            if not is_tree or not same:
                # Detach: drop the menu hook + back-reference.  The
                # controller object itself is garbage-collected once
                # there are no more references; we don't need to
                # call any explicit ``.close()`` on it.
                self._tree_menu_extension = None  # type: ignore[assignment]
                self._tree_controller = None  # type: ignore[assignment]
                current = None  # fall through to attach if is_tree

        # --- ATTACH when the current catalog is a tree and we have
        # no controller.
        if is_tree and current is None:
            try:
                # Lazy import: tree_controller imports tree_dialogs
                # which imports PySide6.  Importing here keeps the
                # cost off cells that don't need it.
                from .tree_controller import TreeController
                ctl = TreeController(cat)
                ctl.attach_to_cell(self)
            except Exception as exc:  # noqa: BLE001
                _log(
                    f"attach_tree_controller failed for {cat!r}: "
                    f"{exc!r}; cell will work but Tree submenu "
                    f"won't appear."
                )

    def _refresh_label_from_catalog(self) -> None:
        """Pull cell label state from the currently-bound catalog file
        and apply it.  Called after ``_catalog_path`` changes (Load…,
        drop, etc.).  Does nothing for cells with no catalog.

        Catalog values take precedence over QSettings — the user
        explicitly bound this cell to a tool/tree, so the tool/tree's
        embedded preference is what they want.
        """
        from pathlib import Path
        catalog = self._catalog_path
        if not catalog or not Path(catalog).is_file():
            return
        try:
            from scriptree.core.cell_metadata import read_for
            md = read_for(catalog)
        except Exception as exc:  # noqa: BLE001
            _log(
                f"_refresh_label_from_catalog: read_for({catalog!r}) "
                f"failed: {exc!r}; keeping current state"
            )
            return
        # Apply.  ``icon_resolved_path`` is the absolute path the
        # paint code can hand to QPixmap.  ``icon_data`` (embedded)
        # is stored on a parallel attribute the paint code prefers
        # over ``_icon_path``.
        if md.is_embedded():
            self._icon_path = None
            self._icon_data_b64 = md.icon_data
            self._icon_data_format = md.icon_format
        else:
            self._icon_path = md.icon_resolved_path or None
            self._icon_data_b64 = ""
            self._icon_data_format = ""
        self._text_label = md.text_label or None
        self._icon_scale = md.icon_scale
        self._label_opacity = md.label_opacity
        self._label_text_over_icon = bool(md.text_over_icon)
        # Fill colour override (V3 v0.3.6+).  Empty hex → revert to
        # branding default; non-empty → apply.  We touch
        # ``_fill_color`` directly here (not via
        # ``apply_fill_color_change``) because the catalog already
        # carries the value — re-writing it would be redundant.
        if md.fill_color:
            from ..core.cell_metadata import _normalise_hex_rgb
            canonical = _normalise_hex_rgb(md.fill_color)
            if canonical:
                r = int(canonical[1:3], 16)
                g = int(canonical[3:5], 16)
                b = int(canonical[5:7], 16)
                existing_alpha = self._fill_color.alpha()
                self._fill_color = QColor(r, g, b, existing_alpha)
                self._fill_color_hex = canonical
        else:
            self._fill_color = QColor(self._branding_fill_color)
            self._fill_color_hex = ""
        # Text colour override (V3 v0.3.8+).  Same pattern; an empty
        # value clears any prior override so re-binds don't leak.
        if md.text_color:
            from ..core.cell_metadata import _normalise_hex_rgb
            canonical = _normalise_hex_rgb(md.text_color)
            self._text_color_hex = canonical
        else:
            self._text_color_hex = ""
        self._label_cache = None
        self._update_hover_tooltip()
        self.update()

    def _update_hover_tooltip(self) -> None:
        """Set the cell's hover tooltip to a human title for whatever
        it's bound to (the bound catalog's name, else the user's text
        label, else a role-based default — Forest / Tree Ring /
        ScripTree).  Mirrors the single-click popup header so the
        hover label and the menu title agree.

        Called from ``__init__`` (covers no-catalog cells),
        ``_refresh_label_from_catalog`` (covers bind / Load… / drop),
        and the catalog-cleared / save-as paths.
        """
        try:
            from scriptree.shell.tree_popup import _popup_header_text
            title = _popup_header_text(self)
        except Exception:  # noqa: BLE001 — never let a tooltip break paint
            title = getattr(self, "_text_label", None) or "ScripTree"
        try:
            self.setToolTip(title or "ScripTree")
        except Exception:  # noqa: BLE001
            pass

    def event(self, ev) -> bool:  # noqa: ANN001
        """Suppress the platform's own QEvent.ToolTip delivery
        (v0.6.27) — the custom hover-tip widget owned by this module
        replaces it.

        We previously caught ``QEvent.ToolTip`` ourselves and called
        ``QToolTip.showText`` (v0.6.13) but that popup competed with
        the cell windows' ``Qt.WindowStaysOnTopHint`` and frequently
        rendered *behind* them on Win11.  v0.6.27 moves the trigger
        to a manual ``enterEvent`` → ``QTimer`` → ``_CellHoverTip``
        path so the tip widget can carry its own stays-on-top
        flag.  Eating the platform tooltip event here prevents the
        OS tooltip from racing the custom one (which would flicker).
        """
        try:
            if ev.type() == QEvent.Type.ToolTip:
                # Custom tip is driven by enterEvent + the QTimer;
                # don't let Qt's default tooltip path fire.
                return True
        except Exception:  # noqa: BLE001
            pass
        return super().event(ev)

    def apply_always_on_top_change(self, on: bool) -> None:
        """Toggle the WindowStaysOnTopHint flag live."""
        self._always_on_top = on
        self._apply_always_on_top_flag(on)

    def _apply_always_on_top_flag(self, on: bool) -> None:
        """Re-apply the stay-on-top window flag.

        Qt requires a hide + show cycle for flag changes to take effect on
        Win11, and ``setWindowFlags()`` RECREATES the native HWND -- which
        resets the window position to (0,0) and DISCARDS the hex mask +
        translucent background.

        v0.8.0a108 -- decoupled from visibility.  The pre-a108 code gated the
        position-restore + chrome-reassert behind ``if was_visible``, so a flag
        applied BEFORE the first show (the forest hub: the manager's ``apply()``
        runs at startup before any ``show()``) silently left the hub at (0,0)
        with a blank mask and an unestablished drag region -- exactly the
        user-reported "jumped to the top-left corner, lost its icon, wasn't
        mobile after loading".  Now we ALWAYS restore the pre-swap position and
        reassert the chrome; only the actual ``show()`` stays gated on prior
        visibility (we never force-show a window the caller meant to keep
        hidden).  Idempotent + safe on a hidden window (``setMask`` /
        ``setAttribute`` / ``move`` don't require visibility).
        """
        # a71: setWindowFlags() HIDES the widget (it calls setParent), so
        # ``isVisible()`` is already False AFTER it -- capture visibility
        # BEFORE.  a108: also capture the position BEFORE, since the HWND
        # recreation resets it to (0,0).
        was_visible = self.isVisible()
        prev_pos = self.pos()
        flags = self.windowFlags()
        if on:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        # a108: restore position unconditionally -- the flag swap must NEVER
        # relocate the window (this is the heart of the "jumps to (0,0)" fix).
        try:
            self.move(prev_pos)
        except Exception as exc:  # noqa: BLE001
            _log(f"_apply_always_on_top_flag: move restore raised {exc!r}")
        if was_visible:
            self.show()
        # a108: reassert chrome unconditionally (was gated on was_visible).
        # The HWND recreation dropped the hex mask + translucent background;
        # re-applying it on a hidden window is harmless and means the very
        # first show already has its mask + drag region -- so the hub is
        # movable immediately, no hide/show cycle needed.
        self._reassert_window_chrome()

    def _apply_taskbar_flag(self, on: bool) -> None:
        """v0.8.0a54: swap ``Qt.Tool`` <-> ``Qt.Window`` so this cell
        appears (or doesn't) on the Windows taskbar / Alt+Tab.

        ONLY the forest hub should ever call this -- normal cells
        stay ``Qt.Tool`` (excluded from taskbar) by design.

        Why the swap matters: pre-a54 the forest hub kept ``Qt.Tool``
        in all visibility modes, and a separate ``ForestTaskbarHost``
        proxy held the taskbar entry.  That introduced a well-known
        Qt-on-Windows quirk -- ``Qt.Tool`` windows shown right after
        another window was active become Windows-transient children
        of that other window.  When the host then minimised itself
        (the proxy's bounce-back pattern), Windows dragged the
        freshly-shown forest down with it.  Symptom: forest pops up
        briefly then disappears, cells left behind.

        a54 fix: when ``show_on_taskbar`` is on, the forest hub
        itself gets ``Qt.Window`` -- it IS the taskbar entry, no
        proxy involved.  No transient-parent confusion, no race.
        When ``show_on_taskbar`` is off the hub reverts to
        ``Qt.Tool`` so it doesn't crowd Alt+Tab.

        Mirrors ``_apply_always_on_top_flag``'s hide-and-reshow
        ritual (Win11 only picks up flag changes on the next show).
        """
        # a71: capture visibility BEFORE setWindowFlags() hides the
        # widget (see _apply_always_on_top_flag) -- the pre-a71
        # ``if self.isVisible()`` re-show was dead, so toggling taskbar
        # mode at runtime silently hid the hub.
        # a108: also capture position BEFORE -- the Qt.Tool<->Qt.Window swap
        # recreates the HWND and resets it to (0,0).
        was_visible = self.isVisible()
        prev_pos = self.pos()
        flags = self.windowFlags()
        if on:
            flags &= ~Qt.Tool
            flags |= Qt.Window
        else:
            flags &= ~Qt.Window
            flags |= Qt.Tool
        self.setWindowFlags(flags)
        # a108: restore position + reassert chrome UNCONDITIONALLY (was gated on
        # was_visible).  The forest hub's taskbar flag is applied at startup
        # before the first show; gating left it at (0,0) with a blank mask.  See
        # the full rationale in _apply_always_on_top_flag.
        try:
            self.move(prev_pos)
        except Exception as exc:  # noqa: BLE001
            _log(f"_apply_taskbar_flag: move restore raised {exc!r}")
        if was_visible:
            self.show()
        self._reassert_window_chrome()

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def _compute_stroke_color(self) -> QColor:
        """Return the correct stroke colour based on role and association state.

        Bug 5 — green outline rule:
          - Forest master:                   forest-green leaf colour
                                             (V3 v0.3.15+ — visually
                                             distinct from a normal
                                             ring master).
          - Master hex:                      accent colour (visual differentiator).
          - Standalone with no group (unassociated): unassociatedStroke from branding
            (defaults to Tailwind emerald-500 #10b981).
          - Standalone in a group:           normal hexStroke from branding.

        Call update() after any state change that affects group membership so
        the repaint picks up the new colour.
        """
        if getattr(self, "_is_forest_master", False):
            # Bright leaf-green so the forest reads as the workspace
            # root.  Same RGB as the previous standalone ForestWindow
            # used, kept for visual continuity.
            c = QColor(108, 196, 138, 255)
            # v0.6.17 — when collapsed, the forest also dims so the
            # user sees the state change even though members didn't
            # tuck (the new opt-in-only collapse model).
            if self._collapse_state == "collapsed":
                c.setAlpha(round(c.alpha() * 0.55))
            return c

        if self.role == "master":
            # v0.6.17 — dim the accent stroke when collapsed so the
            # state change reads visually even with the new "cells
            # stay open" default (otherwise the master looks
            # unchanged after a collapse click).
            c = QColor(self._accent_color)
            if self._collapse_state == "collapsed":
                c.setAlpha(round(c.alpha() * 0.55))
            return c

        if self._group_master_id is None:
            # Unassociated standalone — green outline.
            return self._unassociated_stroke_color

        # v0.6.16 — "loose-linked": the cell is *linked* to a master
        # (group_master_id is set) but isn't currently in that
        # master's positional cluster (broken-free state).  Visual
        # cue: same hue as a docked associated cell, but dimmer
        # alpha (~55%) so the user can tell the cell is associated
        # *without* being in the cluster right now.  The link still
        # propagates collapse / save / outline tint; only the
        # opacity is reduced.
        if self._is_loose_linked():
            c = QColor(self._stroke_color)
            c.setAlpha(round(c.alpha() * 0.55))
            return c

        # Docked associated standalone — normal stroke.
        return self._stroke_color

    def _is_loose_linked(self) -> bool:
        """v0.6.16 — True iff this cell has a link_master but isn't
        currently in that master's positional cluster (a "free but
        still associated" break-free state).

        Used by ``_compute_stroke_color`` to dim the outline so the
        user can tell at a glance whether the cell is docked or
        just loose-linked.
        """
        mid = self._group_master_id
        if mid is None or self.role == "master":
            return False
        from scriptree.shell.cell_registry import CellRegistry
        master = CellRegistry.instance().get(mid)
        if master is None:
            return False
        return self._id not in master._positioned

    @property
    def link_master_id(self) -> "str | None":
        """v0.6.16 — read-only alias for ``_group_master_id``.

        The id of this cell's *logical* parent — the master it
        collapses with, shows the "associated" outline tint for,
        and saves under.  ``None`` for unaffiliated cells and for
        masters themselves.  See the class docstring for the full
        link-vs-dock model.
        """
        return self._group_master_id

    @property
    def is_loose_linked(self) -> bool:
        """v0.6.16 — read-only flag: True when ``link_master_id`` is
        set but the cell isn't currently in the link-master's
        ``_positioned`` (dock) set."""
        return self._is_loose_linked()

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

        # ---- Cell label / icon (standalone cells only) ------------------
        # User contract (2026-05-07): "I want the cells to have the
        # option to have icons. If not an icon they can be assigned
        # text that auto resizes to fit. If they are opening from a
        # file they should start with their icon, and if no icon, their
        # text assignment, and if no text is assigned they take the
        # first and second letter of the tool's name…"
        #
        # Resolution order:
        #   1. _icon_data_b64 / _icon_path → paint scaled pixmap.
        #   2. _text_label → paint user-assigned text.
        #   3. _catalog_path → derive 1-2 letters from catalog name.
        # All three render at the cell's translucent default so they
        # blend with the background.
        #
        # v0.6.13: forest and ring HUBS (role == "master") *also*
        # render an icon when they have one (icon-forest /
        # icon-ring / a user-bound catalog).  Pre-v0.6.13 the master
        # branch only painted a small centre dot, so the hub-icon
        # wiring in forest_controller.start / ring_io.load_ring had
        # no visible effect.  The centre dot is now a fallback for
        # masters that genuinely have no icon (e.g. a bare master
        # that hasn't loaded a hub default yet).
        master_painted_icon = False
        if self.role != "master":
            self._paint_cell_label(painter, size, cx, cy)
        else:
            # v0.6.33 — masters auto-classify too: forest hub →
            # icon-forest, ring hub → icon-ring, catalog-bound
            # master → classified glyph.  ``_paint_cell_label``
            # short-circuits to the centre-dot fallback when even
            # the auto-classifier yields nothing (e.g. icon set is
            # missing from the install), so the historical
            # "blank master → centre dot" behaviour is preserved
            # for that edge case.
            self._paint_cell_label(painter, size, cx, cy)
            # Detect whether the paint actually drew an icon by
            # re-checking the same resolution path the paint code
            # used; we suppress the centre-dot fallback only when
            # something was painted.
            has_icon = bool(
                getattr(self, "_icon_data_b64", "")
                or getattr(self, "_icon_path", None)
            )
            if not has_icon:
                try:
                    has_icon = self._auto_classified_pixmap() is not None
                except Exception:  # noqa: BLE001
                    has_icon = False
            if has_icon:
                master_painted_icon = True

        # ---- Master centre dot ------------------------------------------
        if self.role == "master" and not master_painted_icon:
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
    # Label / icon rendering
    # ------------------------------------------------------------------

    def resolve_displayed_icon(self):  # noqa: ANN201
        """Return ``(pixmap, source)`` for the icon currently rendered
        on this cell.

        ``pixmap`` is a ``QPixmap`` (possibly ``Null``) or ``None``.
        ``source`` is one of:

          * ``"embedded"``      -- ``_icon_data_b64`` (the canonical
                                  new way; survives moves of the
                                  source file).
          * ``"file"``          -- ``_icon_path`` (deprecated legacy
                                  path; still supported on read but
                                  the editor no longer emits new
                                  links).
          * ``"auto"``          -- ``_auto_classified_pixmap`` (the
                                  bundled icon picked from the
                                  catalog's name + content).
          * ``"text"``          -- a custom or auto-derived text
                                  label is what gets rendered today
                                  (no glyph).
          * ``"none"``          -- nothing renders (unbound bare
                                  cell with no auto-icon).

        This mirrors ``_paint_cell_label``'s precedence verbatim
        so the SettingsDialog's Icon-section preview shows exactly
        what the cell shows.  Whenever this method is changed,
        ``_paint_cell_label`` must change to match (or vice versa).
        v0.8.0a25+ -- introduced when the SettingsDialog Icon
        section was rebuilt to show a live preview.
        """
        # Priority 1a: embedded base64 (the new canonical source).
        if self._icon_data_b64:
            from PySide6.QtGui import QPixmap
            try:
                import base64
                raw = base64.b64decode(self._icon_data_b64.encode("ascii"))
                pix = QPixmap()
                if pix.loadFromData(
                    raw, (self._icon_data_format or "png").upper() or None,
                ):
                    return (pix, "embedded")
            except Exception:  # noqa: BLE001
                pass

        # Priority 1b: legacy external file link.  Still honoured on
        # read so old user files keep working; the editor no longer
        # writes new ones.
        if self._icon_path:
            from PySide6.QtGui import QPixmap
            pix = QPixmap(self._icon_path)
            if not pix.isNull():
                return (pix, "file")

        # Priority 2: explicit text label takes precedence over the
        # auto-classified icon (this is what the cell would render).
        if self._text_label:
            return (None, "text")

        # Priority 3: auto-classified bundled icon.
        try:
            classified = self._auto_classified_pixmap()
        except Exception:  # noqa: BLE001
            classified = None
        if classified is not None:
            return (classified, "auto")

        # Priority 4: auto-derived letters (no glyph).
        if self._auto_label_text():
            return (None, "text")

        return (None, "none")

    def _paint_cell_label(
        self, painter: QPainter, size: int, cx: float, cy: float,
    ) -> None:
        """Paint the standalone cell's icon / text / auto-letters.

        Called from ``paintEvent`` after the polygon fill, before any
        role-specific overlays.  Translucent foreground so it reads as
        part of the cell.
        """
        # Priority 1: icon — embedded base64 first, then external file.
        # Embedded wins because it survives even if the source file
        # has been moved on disk.
        pix = None
        if self._icon_data_b64:
            from PySide6.QtGui import QPixmap
            try:
                import base64
                raw = base64.b64decode(self._icon_data_b64.encode("ascii"))
                pix = QPixmap()
                if not pix.loadFromData(
                    raw, self._icon_data_format.upper() or None
                ):
                    pix = None
            except Exception:  # noqa: BLE001
                pix = None
        if pix is None and self._icon_path:
            from PySide6.QtGui import QPixmap
            pix = QPixmap(self._icon_path)
            if pix.isNull():
                pix = None
        if pix is not None:
            # Inscribed-circle diameter is ~cell_size * 0.7.
            # Multiply by ``_icon_scale`` so the user can grow or
            # shrink the icon relative to the cell.  Because the
            # base is ``size`` (the cell's current pixel
            # dimension), this scale automatically tracks future
            # cell-size changes — per user spec: "once accepted
            # this scale will automatically adjust with the
            # scaling of the cell shape."
            target = max(8, int(size * 0.7 * self._icon_scale))
            scaled = pix.scaled(
                target, target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            # Apply (cell transparency × label opacity) so the
            # icon visually matches the cell's translucency and
            # the user's per-cell label-opacity override.
            effective_op = max(
                0.0, min(1.0, self._transparency * self._label_opacity),
            )
            if effective_op < 0.999:
                painter.save()
                painter.setOpacity(effective_op)
                painter.drawPixmap(
                    int(cx - scaled.width() / 2),
                    int(cy - scaled.height() / 2),
                    scaled,
                )
                painter.restore()
            else:
                painter.drawPixmap(
                    int(cx - scaled.width() / 2),
                    int(cy - scaled.height() / 2),
                    scaled,
                )
            # v0.6.9: superimpose the text label over the icon when
            # the user opted in.  Drawn in a legible band across the
            # lower third with a translucent backing so it reads
            # against any icon.  Without the opt-in we keep the
            # historical icon-suppresses-text behaviour.
            if getattr(self, "_label_text_over_icon", False):
                over = self._text_label or self._auto_label_text()
                if over:
                    self._paint_label_text(
                        painter, size, cx, cy, over,
                        anchor="bottom", backing=True,
                    )
            return

        # Priority 2: explicit text label — the user typed it, paint it.
        if self._text_label:
            self._paint_label_text(painter, size, cx, cy, self._text_label)
            return

        # Priority 3 (v0.6.33+): auto-classified bundled icon.  Picks a
        # sensible glyph for the bound catalog from
        # ``icon_assets.classify_icon`` so a fresh ``.scriptree`` /
        # ``.scriptreetree`` shows the right kind of icon on its cell
        # without the user opening Settings → Library.  Falls through
        # to auto-letters when there's no catalog (unbound standalone
        # cell) or the bundled icon set is missing.
        try:
            classified = self._auto_classified_pixmap()
        except Exception as exc:  # noqa: BLE001
            _log(f"_paint_cell_label: auto-classify raised {exc!r}")
            classified = None
        if classified is not None:
            target = max(8, int(size * 0.7 * self._icon_scale))
            scaled = classified.scaled(
                target, target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            effective_op = max(
                0.0, min(1.0, self._transparency * self._label_opacity),
            )
            if effective_op < 0.999:
                painter.save()
                painter.setOpacity(effective_op)
                painter.drawPixmap(
                    int(cx - scaled.width() / 2),
                    int(cy - scaled.height() / 2),
                    scaled,
                )
                painter.restore()
            else:
                painter.drawPixmap(
                    int(cx - scaled.width() / 2),
                    int(cy - scaled.height() / 2),
                    scaled,
                )
            return

        # Priority 4: auto-derived letters from the bound catalog's
        # name.  Final fallback for unbound or unclassifiable cells.
        text = self._auto_label_text()
        if not text:
            return  # nothing to paint
        self._paint_label_text(painter, size, cx, cy, text)

    def _auto_classified_pixmap(self):  # noqa: ANN202 — QPixmap | None
        """Return the bundled-icon pixmap for the cell's bound catalog
        when the user hasn't picked an explicit one — v0.6.33.

        The lookup uses ``icon_assets.classify_icon`` against the
        loaded catalog's name + the file's stem, so a tool named
        "build-and-push" picks up ``icon-build.png`` automatically.
        For unbound cells (no ``_catalog_path``) the role-default
        glyph is used:

          * forest master → ``icon-forest``
          * ring master   → ``icon-ring``
          * standalone    → no auto-icon (paint falls through to
                             text-label / auto-letters as before)

        Result is cached by (catalog_path, mtime) so paintEvent
        doesn't re-read the catalog + re-decode the PNG on every
        repaint.  The cache key tracks mtime so an edit to the
        catalog's name (which can change classification) invalidates
        next paint.

        Returns ``None`` when nothing applies — paint code falls
        through to the existing text-label / auto-letters branches.
        """
        # Cell with no catalog: only masters get a role-default
        # auto-icon; standalone bare cells stay bare per the
        # existing "icon → text-label → auto-letters → nothing"
        # contract.
        catalog_path = self._catalog_path
        is_master = (self.role == "master")
        is_forest = bool(
            getattr(self, "_is_forest_master", False)
        )

        if not catalog_path and not is_master:
            return None

        # Per-instance pixmap cache.  Re-use the existing
        # ``_classified_icon_cache`` slot if present, otherwise
        # initialise here.
        cache = getattr(self, "_classified_icon_cache", None)

        # Build the cache key.  For an unbound master the key is
        # the role default; otherwise it's the catalog path + mtime.
        from pathlib import Path
        cache_key: tuple
        chosen_name: str = ""
        if catalog_path:
            try:
                p = Path(catalog_path)
                if not p.is_file():
                    return None
                try:
                    mtime = p.stat().st_mtime_ns
                except OSError:
                    mtime = 0
                cache_key = ("catalog", str(p.resolve()), mtime)
            except Exception:  # noqa: BLE001
                return None
        else:
            cache_key = (
                "master-default",
                "forest" if is_forest else "ring",
            )

        if cache is not None and cache[0] == cache_key:
            return cache[1]

        # Cache miss — resolve the bundled-icon name.
        if catalog_path:
            try:
                from scriptree.shell.icon_assets import classify_icon
                p = Path(catalog_path)
                name = ""
                ext = p.suffix.lower()
                if ext == ".scriptreetree":
                    from scriptree.core.io import load_tree
                    name = load_tree(str(p)).name or p.stem
                elif ext == ".scriptree":
                    from scriptree.core.io import load_tool
                    name = load_tool(str(p)).name or p.stem
                else:
                    name = p.stem
                # The master that's a ring or forest still uses the
                # catalog's classification IF a catalog is bound —
                # the user bound a tool here, that beats the
                # role-default.
                chosen_name = classify_icon(
                    name=name, filename=p.stem,
                )
            except Exception as exc:  # noqa: BLE001
                _log(
                    f"_auto_classified_pixmap: classify_icon failed "
                    f"for {catalog_path!r}: {exc!r}"
                )
                return None
        else:
            # Unbound master — role default.
            chosen_name = "forest" if is_forest else "ring"

        # Decode the PNG into a QPixmap.
        pix = None
        try:
            from PySide6.QtGui import QPixmap
            from scriptree.shell.icon_assets import (
                bundled_icon_png_path,
            )
            path = bundled_icon_png_path(chosen_name)
            if path is not None:
                cand = QPixmap(str(path))
                if not cand.isNull():
                    pix = cand
        except Exception as exc:  # noqa: BLE001
            _log(
                f"_auto_classified_pixmap: pixmap load failed "
                f"for {chosen_name!r}: {exc!r}"
            )
            pix = None

        # Cache miss-or-hit either way; missing pix caches None so
        # we don't retry on every paint.
        self._classified_icon_cache = (cache_key, pix)
        return pix

    def _auto_label_text(self) -> str | None:
        """Derive a label from the loaded catalog's name.

        For ``.scriptree`` files we read the ``ToolDef.name``; for
        ``.scriptreetree`` files we read the ``TreeDef.name``.  The
        result is fed through ``_derive_letters`` so even tools with
        long names produce a 1-2 character label.

        Cached on a per-(catalog_path, mtime) key so we don't re-read
        the file on every paint event.
        """
        cp = self._catalog_path
        if not cp:
            return None
        try:
            from pathlib import Path as _Path
            p = _Path(cp)
            if not p.is_file():
                return None
            try:
                mtime = p.stat().st_mtime_ns
            except OSError:
                mtime = 0
            cache_key = (str(p.resolve()), mtime)
            cache = getattr(self, "_label_cache", None)
            if cache and cache[0] == cache_key:
                return cache[1]
            # Cache miss — read the catalog name.
            name = ""
            ext = p.suffix.lower()
            if ext == ".scriptreetree":
                from scriptree.core.io import load_tree
                name = load_tree(str(p)).name or p.stem
            elif ext == ".scriptree":
                from scriptree.core.io import load_tool
                name = load_tool(str(p)).name or p.stem
            else:
                name = p.stem
            label = _derive_letters(name)
            self._label_cache = (cache_key, label)
            return label
        except Exception as exc:  # noqa: BLE001
            _log(f"_auto_label_text({cp!r}) failed: {exc!r}")
            return None

    def _paint_label_text(
        self, painter: QPainter, size: int,
        cx: float, cy: float, text: str,
        *, anchor: str = "center", backing: bool = False,
    ) -> None:
        """Paint ``text`` centred in the cell, auto-sized to fit.

        Font size is chosen so the rendered text fits within ~70 % of
        the cell's diameter — works for the typical 1-3 character
        auto-derived labels and for short user-assigned overrides.
        Longer text shrinks down to a minimum of 8 px before
        ellipsising.

        Colour: the cell's stroke colour (which is already palette-
        coordinated) at the cell's transparency multiplier.  This
        keeps the label visually part of the cell rather than a
        sticker.

        ``anchor`` — ``"center"`` (default, historical) or
        ``"bottom"`` (lower-third band, used when superimposing the
        text over an icon so the glyph stays visible).
        ``backing`` — when True draw a translucent rounded pill
        behind the text for legibility over a busy icon.
        """
        # Target box: 70 % of cell width.  The bottom-anchored band
        # is shorter so it doesn't cover the icon's centre.
        target_w = max(16, int(size * 0.70))
        target_h = (
            max(12, int(size * 0.34)) if anchor == "bottom"
            else max(16, int(size * 0.70))
        )

        # Initial font size guess based on text length.
        if len(text) <= 2:
            font_px = max(10, int(size * 0.45))
        elif len(text) <= 4:
            font_px = max(10, int(size * 0.30))
        else:
            font_px = max(10, int(size * 0.20))

        font = QFont()
        font.setBold(True)
        # Shrink iteratively until the text fits the target box.
        for _ in range(8):
            font.setPixelSize(font_px)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            advance = metrics.horizontalAdvance(text)
            ascent = metrics.ascent()
            if advance <= target_w and ascent <= target_h:
                break
            new_px = int(font_px * 0.85)
            if new_px < 8:
                font_px = 8
                break
            font_px = new_px

        # Pick the source colour:
        #   * If the user set ``_text_color_hex`` (V3 v0.3.8+),
        #     paint with that exact RGB — alpha still derives from
        #     transparency × label_opacity so the label tracks the
        #     cell's translucency.
        #   * Otherwise fall back to the stroke colour, which is
        #     palette-coordinated and readable against the fill.
        if self._text_color_hex:
            r = int(self._text_color_hex[1:3], 16)
            g = int(self._text_color_hex[3:5], 16)
            b = int(self._text_color_hex[5:7], 16)
            col = QColor(r, g, b, 255)
        else:
            col = QColor(self._compute_stroke_color())
        effective_op = max(
            0.0, min(1.0, self._transparency * self._label_opacity),
        )
        col.setAlpha(round(255 * effective_op))
        # Vertical placement: centred, or pushed into the lower third
        # when superimposed over an icon.
        if anchor == "bottom":
            top = int(cy + size * 0.5 - target_h - size * 0.06)
        else:
            top = int(cy - target_h / 2)
        rect = QRect(
            int(cx - target_w / 2),
            top,
            target_w,
            target_h,
        )
        if backing:
            # Translucent dark pill so light text reads over a busy
            # icon (and a light pill is unnecessary — text is bold).
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            backing_col = QColor(0, 0, 0)
            backing_col.setAlpha(round(140 * effective_op))
            painter.setBrush(backing_col)
            pad = max(2, int(size * 0.04))
            painter.drawRoundedRect(
                rect.adjusted(-pad, -pad // 2, pad, pad // 2),
                max(3, int(size * 0.10)),
                max(3, int(size * 0.10)),
            )
            painter.restore()
            # Force a high-contrast colour for the overlaid text.
            col = QColor(255, 255, 255)
            col.setAlpha(round(255 * max(effective_op, 0.85)))
        painter.setPen(col)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawText(
            rect,
            Qt.AlignmentFlag.AlignCenter,
            text,
        )

    # ------------------------------------------------------------------
    # File drag-and-drop
    # ------------------------------------------------------------------
    #
    # User contract (2026-05-07): "to open a scriptree or scriptreetree
    # or scriptreering file I should be able to drag and drop it onto
    # a cell, or have a scriptree or scriptreetree open a new cell
    # docked to an existing tree ring if dropped on that tree ring.
    # If I drop a tree ring file onto an existing tree ring or cell it
    # should just open undocked to the other, but still related in
    # that I can take cells from one ring and dock them to the other."
    #
    # Dispatch matrix:
    #
    #   File type       │ Standalone cell    │ Master / ring
    #   ────────────────┼────────────────────┼───────────────────────────
    #   .scriptree      │ Bind to this cell  │ Spawn a new docked member
    #   .scriptreetree  │ Bind to this cell  │ Spawn a new docked member
    #   .scriptreering  │ Open new ring      │ Open new ring (same proc)
    #                   │ (same registry)    │ (same registry)
    #
    # ``Open new ring (same registry)`` means the cells from the
    # dropped ring file appear at their saved positions WITHOUT
    # auto-docking with the existing ones — the user can drag
    # individual cells between rings later because everything lives
    # in the same SnapEngine.

    @staticmethod
    def _drop_paths(event) -> list[str]:  # noqa: ANN001 — Qt event
        """Extract local file paths from a drag/drop event.

        Returns only paths whose extension matches the three formats
        we accept; other URLs (http://, file:// of unknown types) are
        filtered out so we never attempt to load random files.
        """
        md = event.mimeData()
        if not md.hasUrls():
            return []
        out: list[str] = []
        for u in md.urls():
            if not u.isLocalFile():
                continue
            p = u.toLocalFile()
            ext = p.lower().rsplit(".", 1)[-1] if "." in p else ""
            if ext in ("scriptree", "scriptreetree", "scriptreering"):
                out.append(p)
        return out

    def _drop_installables(self, event) -> list[str]:  # noqa: ANN001
        """Extract installable paths (folders + .zip files) from a
        drag/drop event.

        v0.8.0a23+ -- enables the "drop a ScripTree app onto the
        forest" workflow.  Only forest-master cells accept these;
        on non-forest cells the method returns ``[]`` so the
        existing extension-based ``_drop_paths`` flow stays the
        single owner of the drop behaviour.

        Folders are detected via ``Path.is_dir()``; zips by suffix
        match (``.zip``, case-insensitive).  Anything else is
        filtered out -- a stray ``.tar.gz`` won't surprise the
        install flow with an unsupported source.
        """
        if not getattr(self, "_is_forest_master", False):
            return []
        md = event.mimeData()
        if not md.hasUrls():
            return []
        from pathlib import Path as _Path
        out: list[str] = []
        for u in md.urls():
            if not u.isLocalFile():
                continue
            p = u.toLocalFile()
            path = _Path(p)
            try:
                if path.is_dir():
                    out.append(p)
                elif (
                    path.is_file()
                    and path.suffix.lower() == ".zip"
                ):
                    out.append(p)
            except OSError:
                # Unreachable / permission-denied paths -- skip.
                continue
        return out

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        if self._drop_paths(event) or self._drop_installables(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: ANN001
        if self._drop_paths(event) or self._drop_installables(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: ANN001
        paths = self._drop_paths(event)
        installables = self._drop_installables(event)
        if not paths and not installables:
            super().dropEvent(event)
            return
        event.acceptProposedAction()
        for p in paths:
            self._handle_dropped_file(p)
        for p in installables:
            self._handle_dropped_installable(p)

    def _handle_dropped_file(self, path: str) -> None:
        """Dispatch a dropped file based on extension + this cell's role.

        v0.3.6 unifies the drop-dispatch with the menu-driven Load
        actions (``_open_catalog_path``).  The user-facing matrix
        (per the v0.3.6 spec):

        ============== ====================== =========================
        Source state   .scriptree / .tree     .scriptreering
        ============== ====================== =========================
        Empty cell     bind to self           close cell + load ring
        Bound cell     spawn sibling cell     load ring alongside
        Master / ring  spawn member, JOIN     load ring alongside
                       group + slot it
        ============== ====================== =========================

        Always emits a ``[CellWindow] drop ...`` log line so the
        dispatch is observable from stderr.
        """
        from pathlib import Path as _Path

        p = _Path(path)
        if not p.is_file():
            _log(f"drop ignored — file not found: {path!r}")
            return

        ext = p.suffix.lower()
        _log(
            f"drop {ext!r} on {self.role} {self._id[:8]}: {p.name!r}"
        )

        if ext not in (".scriptree", ".scriptreetree", ".scriptreering"):
            _log(f"  unsupported extension: {ext}")
            return

        # Master / ring case (v0.3.6 spec):
        #   tool/tree → spawn a NEW member cell, auto-link it into
        #               the master's group, position via the repack
        #               so it lands on a free slot.
        #   ring     → "just opens" (load_ring loads alongside).
        if self.role == "master":
            if ext == ".scriptreering":
                self._drop_open_related_ring(p)
            else:
                self._drop_spawn_member_and_link(p)
            return

        # Standalone case — empty / bound logic mirrors the menu
        # Load-X handlers via the v0.2.11 ``_open_catalog_path``
        # dispatcher (which already implements: empty + tool/tree
        # → bind-self; bound + tool/tree → spawn sibling; empty +
        # ring → close-self + load; bound + ring → load alongside).
        self._open_catalog_path(str(p.resolve()))

    def _handle_dropped_installable(self, path: str) -> None:
        """Forest-only: route a folder / zip drop through the
        drop-install workflow.

        Composed of three pieces that already exist:

        1. ``InstallLocationDialog`` -- where to install
           (Shared / Personal / Other).
        2. ``InstallConflictDialog`` -- fired only when the
           chosen target already exists (Update / Rename /
           Overwrite / Cancel).
        3. ``scriptree.core.app_install.install_app`` -- the
           pure-logic copy/extract.

        On success, calls the forest controller's
        ``refresh_from_sources`` so the newly-installed app is
        offered for inclusion in the forest immediately
        (subject to whatever discovery mode the user has
        configured: prompt / auto / off).

        Failures surface as a ``QMessageBox.warning`` rather
        than crashing the cell -- a drop should never break
        the desktop.
        """
        # Defensive guard: ``_drop_installables`` already filters
        # non-forest cells, but keep this check too in case a
        # caller invokes the method directly.
        if not getattr(self, "_is_forest_master", False):
            _log(f"installable drop ignored on non-forest cell: {path!r}")
            # Surface to the user — stderr is invisible under
            # ``pythonw.exe`` and a silent ignore here was reported as
            # "drop accepted, nothing happened".  v0.8.0a25.
            try:
                QMessageBox.information(
                    self, "Install",
                    "Only the forest hub cell accepts folder / zip "
                    "drops for installation.  Drop your folder onto "
                    "the central forest cell instead.",
                )
            except Exception:  # noqa: BLE001
                pass
            return

        # Lazy imports keep these out of the cell module's
        # import-time graph for non-forest cells.  Wrapped in a
        # try/except because an ImportError would otherwise propagate
        # out of the drop-event handler and into Qt's silent
        # exception swallowing — the user sees "nothing happened"
        # again.  v0.8.0a25.
        try:
            from pathlib import Path as _Path
            from ..core.app_install import (
                ConflictMode, InstallError, install_app,
            )
            from ..ui.install_dialogs import (
                InstallConflictDialog, InstallLocationDialog,
            )
        except Exception as exc:  # noqa: BLE001
            _log(f"installable drop: import failed: {exc!r}")
            QMessageBox.warning(
                self, "Install failed",
                f"Could not load the install helpers:\n\n{exc!r}\n\n"
                f"This usually means the ScripTree install tree is "
                f"out of sync — try restarting ScripTree.",
            )
            return

        source = _Path(path)
        if not source.exists():
            _log(f"installable drop ignored — source not found: {path!r}")
            QMessageBox.warning(
                self, "Install failed",
                f"The dropped source does not exist:\n\n{path}",
            )
            return

        _log(
            f"installable drop: {source.name!r} "
            f"(kind={'folder' if source.is_dir() else 'zip'})"
        )

        # Step 1: where?  Wrap dialog construction + exec so any
        # exception inside the dialog (e.g. branding-config read
        # failure) surfaces as a popup rather than vanishing into
        # Qt's silent handler.
        try:
            loc = InstallLocationDialog(self, source)
            accepted = (loc.exec() == loc.DialogCode.Accepted)
        except Exception as exc:  # noqa: BLE001
            _log(f"installable drop: location dialog crashed: {exc!r}")
            import traceback as _tb
            tb_str = _tb.format_exc()
            QMessageBox.warning(
                self, "Install failed",
                f"The location-picker dialog crashed:\n\n{exc!r}\n\n"
                f"Details:\n{tb_str}",
            )
            return
        if not accepted:
            return
        target_root = loc.chosen_root()

        # Step 2: install (with a one-shot retry on conflict).
        conflict_mode: ConflictMode | None = None
        result = None
        for _attempt in range(2):  # at most: try once, retry once
            try:
                result = install_app(
                    source, target_root,
                    conflict_mode=conflict_mode,
                )
                break
            except InstallError as exc:
                msg = str(exc)
                if "already exists" not in msg:
                    QMessageBox.warning(
                        self, "Install failed", msg,
                    )
                    return
                # Target conflict -- prompt the user.
                existing = target_root / loc.chosen_app_name()
                cdlg = InstallConflictDialog(
                    self, loc.chosen_app_name(), existing,
                )
                if cdlg.exec() != cdlg.DialogCode.Accepted:
                    return  # cancel
                conflict_mode = cdlg.chosen_mode()
                if conflict_mode == ConflictMode.CANCEL:
                    return

        if result is None:
            # Belt-and-braces: shouldn't happen, but fail loudly
            # rather than silently if the retry-loop logic regresses.
            QMessageBox.warning(
                self, "Install failed",
                "Install did not complete after retry.",
            )
            return

        _log(
            f"installed {result.files_written} files to {result.target}"
        )

        # Step 3: trigger forest auto-discovery so the new app
        # appears in the forest right away.  Reached via the
        # ``_forest_menu_extension`` bound method's ``__self__``
        # -- the forest controller registers itself there on
        # cell attach.
        self._post_install_refresh_forest()

    def _post_install_refresh_forest(self) -> None:
        """Best-effort: trigger ``refresh_from_sources`` on the
        forest controller bound to this cell (if any).

        Recovers the controller from
        ``self._forest_menu_extension.__self__`` -- the forest
        controller stores its ``_populate_forest_menu`` bound
        method as the menu extension during attach, so the
        bound method's ``__self__`` IS the controller.
        Avoids needing a separate ``cell._forest_controller``
        attribute; idempotent and harmless when no controller
        is attached.
        """
        hook = getattr(self, "_forest_menu_extension", None)
        if hook is None:
            return
        controller = getattr(hook, "__self__", None)
        if controller is None:
            return
        refresh = getattr(controller, "refresh_from_sources", None)
        if not callable(refresh):
            return
        try:
            refresh()
        except Exception as exc:  # noqa: BLE001
            _log(f"post-install refresh failed: {exc!r}")

    def _drop_spawn_member_and_link(self, path):  # noqa: ANN001, ANN201
        """Master case (v0.3.6+): spawn a fresh cell bound to the
        dropped catalog AND auto-join it to this master's group.

        M4 fix: returns the new member's ``_id`` (str) so callers can
        record exactly the cell that was created instead of guessing
        via ``next(reversed(self._members))`` — that guess broke if
        this method ever added ≠1 member or reused an id. Returns
        ``None`` only if construction failed before a cell existed.
        The lone other caller ignores the return; the legacy alias
        below inherits it harmlessly.

        Replaces the older ``_drop_spawn_docked_member`` which only
        positioned the new cell adjacent and required the user to
        manually drag it into a slot.  The user's v0.3.6 spec:

            "if it is a scriptree or scriptreetree dropped on a ring
             it gets linked and located attached to the group"

        Implementation:

        1. Construct a ``CellWindow`` bound to ``path``.
        2. Adopt the master's group geometry (size / shape /
           orientation) via ``_adopt_member_geometry`` so the new
           member matches the ring's look immediately.
        3. Wire it into the SnapEngine.
        4. Add to ``master._members`` / ``_positioned`` /
           ``_dock_partners`` and set its ``_group_master_id``.
        5. Mark the ring dirty (membership changed — close-prompt
           will fire if the user closes the ring without saving).
        6. Run ``master._repack_members()`` so the new cell lands
           on a free honeycomb slot around the master with the rest
           of the group rearranged as needed.
        """
        from PySide6.QtCore import QPoint
        from scriptree.shell.cell_registry import CellRegistry
        from scriptree.shell import recent_files as _rf

        new_cell = CellWindow(
            self._branding,
            catalog_path=str(path.resolve()),
        )
        # Geometry + visibility come first so the cell exists and
        # can adopt the master's appearance before the repack
        # decides where to put it.
        try:
            _adopt_member_geometry(new_cell, self)
        except Exception as exc:  # noqa: BLE001
            _log(
                f"  _adopt_member_geometry failed for {new_cell._id[:8]}: "
                f"{exc!r} — proceeding anyway"
            )
        # Initial position next to the master so the repack has a
        # sensible starting direction to assign.
        start_x = self.pos().x() + self.width() + 12
        start_y = self.pos().y()
        new_cell.move(start_x, start_y)
        try:
            from scriptree.shell.ring_main import _wire_hex_to_snap
            _wire_hex_to_snap(new_cell)
        except Exception as exc:  # noqa: BLE001
            _log(f"  could not wire new cell to snap engine: {exc!r}")
        new_cell.show()
        new_cell._fade_in()
        try:
            new_cell._settle_no_overlap()
        except Exception as exc:  # noqa: BLE001
            _log(f"_settle_no_overlap (drop-join) raised {exc!r}")
        _rf.add(str(path.resolve()))

        # Wire ring membership.  Mirrors ``_try_spawn_master`` Case 2
        # (standalone joining an existing master's group), minus
        # the docked_to bookkeeping that requires a specific peer
        # cell — the repack right after will set positions cleanly.
        self._members[new_cell._id] = QPoint(new_cell.pos())
        self._positioned.add(new_cell._id)
        self._dock_partners.add(new_cell._id)
        new_cell._group_master_id = self._id
        new_cell._link_parent_id = self._id  # v0.8.0 P1 mirror
        new_cell.update()  # Bug 5: refresh outline (now associated).
        # Membership changed — flag dirty so the close-prompt fires
        # if the user closes the ring without saving (v0.3.1).
        self._ring_dirty = True
        _log(
            f"  spawned new cell {new_cell._id[:8]} bound to "
            f"{path.name!r}, joined ring {self._id[:8]} "
            f"(now {len(self._members)} member(s))"
        )

        # Re-pack ONLY the new cell — existing members keep their
        # positions verbatim (per user contract: "moving one element
        # does not cause a reshift in the others").  The new cell
        # was placed at a tentative spot next to the master and
        # needs to find a real free slot; the ``fixed`` argument
        # tells repack to leave every other member where it is.
        try:
            existing_ids = {
                mid for mid in self._members.keys() if mid != new_cell._id
            }
            self._repack_members(fixed=existing_ids)
        except Exception as exc:  # noqa: BLE001
            _log(
                f"  _repack_members after drop-join failed: "
                f"{exc!r} — leaving new cell at its initial position"
            )

        return new_cell._id

    # Legacy alias — kept so any out-of-tree caller (V2 polyfills,
    # third-party patches) that called the old name still works.
    # Internally we now route every drop-on-master to the linking
    # variant.
    _drop_spawn_docked_member = _drop_spawn_member_and_link

    def _drop_open_related_ring(self, path) -> None:  # noqa: ANN001
        """Open a .scriptreering file in the current process.

        New ring's cells appear at their saved positions; they do NOT
        auto-dock to existing cells, but they share the SnapEngine so
        the user can drag a cell from one ring near a cell from
        another and snap them together.
        """
        from scriptree.shell.cell_registry import CellRegistry
        from scriptree.shell.ring_main import _get_snap_engine
        from scriptree.shell.ring_io import load_ring

        try:
            registry = CellRegistry.instance()
            snap = _get_snap_engine()
            master = load_ring(path, self._branding, registry, snap)
            master._saved_ring_path = path
            _log(
                f"  opened ring {path.name!r} → master "
                f"{master._id[:8]} (related, undocked from existing)"
            )
        except Exception as exc:  # noqa: BLE001
            _log(f"  load_ring({path!r}) failed: {exc!r}")
            QMessageBox.warning(
                None, "Could not open ring",
                f"Failed to open {path.name}:\n\n{exc}",
            )

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        # v0.6.27 — start the custom hover-tip delay.  Doing this on
        # enterEvent (instead of relying on QEvent.ToolTip delivery)
        # is what makes the tip actually appear over Qt.Tool +
        # WA_TranslucentBackground frameless windows on Win11; see
        # the docstring on _CellHoverTip for the full reasoning.
        try:
            self._hover_tip_timer.start()
        except Exception:  # noqa: BLE001
            pass
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        # v0.6.27 — cancel any pending tip + hide the visible one.
        try:
            self._hover_tip_timer.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            _CellHoverTip.hide()
        except Exception:  # noqa: BLE001
            pass
        super().leaveEvent(event)

    def _show_hover_tip_now(self) -> None:
        """Called by the hover-tip QTimer after the cursor has been
        still over this cell for ~700 ms.  Resolves the cell's title
        the same way the popup-menu header does and renders it via
        the shared ``_CellHoverTip`` widget.

        Bails silently if the cell isn't hovered any more (the user
        moved the cursor off between timer start and fire), or if
        the cell has been destroyed.
        """
        try:
            if not self._hovered:
                return
            from scriptree.shell.tree_popup import _popup_header_text
            title = _popup_header_text(self)
            if not title:
                return
            # Anchor below-centre of the cell + pass the cell's
            # global bounding rect so _CellHoverTip can centre the
            # tip on the cell and flip / clamp it against screen
            # edges (v0.8.0a2 Bug 12).  Falls back to cursor
            # position if mapToGlobal raises (unlikely but
            # belt-and-suspenders).
            cell_rect = None
            try:
                tl = self.mapToGlobal(QPoint(0, 0))
                anchor = self.mapToGlobal(
                    QPoint(self.width() // 2, self.height())
                )
                cell_rect = QRect(
                    tl.x(), tl.y(), self.width(), self.height(),
                )
            except Exception:  # noqa: BLE001
                from PySide6.QtGui import QCursor
                anchor = QCursor.pos()
            _CellHoverTip.show(title, anchor, cell_rect=cell_rect)
        except Exception as exc:  # noqa: BLE001
            _log(f"_show_hover_tip_now: {exc!r}")

    def mousePressEvent(self, event) -> None:
        # v0.6.27 — kill any visible hover-tip and pending timer when
        # the user starts interacting; nothing more annoying than a
        # tooltip lingering during a drag or click.
        try:
            self._hover_tip_timer.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            _CellHoverTip.hide()
        except Exception:  # noqa: BLE001
            pass
        if event.button() == Qt.LeftButton:
            self._press_global_pos = event.globalPosition().toPoint()
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_started = False
            _log(f"press @ {self._press_global_pos} id={self._id[:8]}")
            # v0.8.0a113 [drag-diag] -- for the forest hub, log the window
            # activation/foreground state at press time.  The "hub not draggable
            # on first startup until a manual minimise/restore" bug is a Win11
            # foreground-lock symptom: if the hub isn't the ACTIVE window, mouse
            # MOVE events may not be delivered while a button is held, so the
            # drag never crosses the threshold (drag_started stays False).  When
            # the user hits the non-draggable state, this line tells us whether
            # the window was inactive (root cause) vs moves simply not arriving.
            if getattr(self, "_is_forest_master", False):
                try:
                    _log(
                        f"[drag-diag] hub press: active={self.isActiveWindow()} "
                        f"min={self.isMinimized()} visible={self.isVisible()} "
                        f"focus={self.hasFocus()} "
                        f"flags=0x{int(self.windowFlags()):X}"
                    )
                except Exception:  # noqa: BLE001
                    pass
            # v0.6.38 — self-heal any membership inconsistency on the
            # master before a drag begins.  The v0.6.37 trace
            # surfaced phantom ids in _positioned + orphan cells +
            # linked-but-not-positioned cells.  Auditing here means a
            # corrupt state from a previous interaction can't cause
            # cells to "go missing" or "not follow" during the NEXT
            # drag — every press is a fresh consistency point.
            if self.role == "master":
                try:
                    self._audit_membership()
                except Exception as exc:  # noqa: BLE001
                    _log(f"mousePressEvent: audit raised {exc!r}")
                # v0.7.1 — cancel any in-flight member ``_smooth_move``
                # animations and snap them to their target.  Without
                # this, a drag that starts WHILE a post-release
                # settle animation is still running has the GROUP_MOVE
                # cascade ADD deltas to a position that's also being
                # eased toward an old target — net result is members
                # drift away from their slot positions and the
                # cluster falls out of alignment with the master.
                # Trace ``scriptree-layout-trace-20260523-071726-42748.log``
                # shows the divergence: at 07:17:50.751 (release+22ms)
                # smooth_move starts; user immediately drags again,
                # cascade and animation fight, ending with members
                # at the wrong delta from the master.
                try:
                    self._cancel_member_smooth_moves()
                except Exception as exc:  # noqa: BLE001
                    _log(f"mousePressEvent: cancel_member_smooth_moves raised {exc!r}")
            # v0.6.36 — trace + snapshot at drag start so the log
            # captures the world state just before any movement.
            try:
                _trace.event(
                    "PRESS",
                    id=self._id[:8],
                    role=self.role,
                    pos=(self.pos().x(), self.pos().y()),
                    press=(
                        self._press_global_pos.x(),
                        self._press_global_pos.y(),
                    ),
                )
                _trace.snapshot(f"press-{self._id[:8]}")
            except Exception:  # noqa: BLE001
                pass
        elif event.button() == Qt.RightButton:
            # Bug 3 — double-right-click detection:
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
                # Second right-press within interval — double-right-click.
                self._right_click_timer.stop()
                self._right_press_time = None
                _log(f"double-right-click detected id={self._id[:8]}")
                self.click("double-right")
            else:
                # First right-press — arm the timer; do NOT open context menu yet.
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

            # Threshold crossed — commit to manual drag.
            self._drag_started = True
            # Reset shake detector at the start of each new drag.
            self._shake_detector.reset()
            _log(f"DRAG STARTED (manual) id={self._id[:8]} role={self.role} group_master={self._group_master_id and self._group_master_id[:8]} positioned={len(self._positioned) if self.role == 'master' else len(self._docked_to)}")

            # Amendment 2 — break-free: dragging a cell/ring out of
            # its positional cluster (forest._positioned) leaves the
            # cluster but retains link-group membership.
            #
            # v0.8.0 — extended to RINGS too.  Per the user's spec:
            # "once I make a ring that is not docked to the forest
            # cluster it [shouldn't] move when I move the forest."
            # Previously break-free was standalone-only, so a dragged
            # ring stayed in forest._positioned and the cascade gate
            # picked it up.  Now any non-forest cell (cell or ring)
            # that's been dragged out of cluster auto-undocks at
            # drag-start, dropping out of _positioned + clearing
            # ``_slot`` + ``_dock_partner_id``.  The forest itself
            # never break-frees (it IS the workspace root).
            is_forest = getattr(self, "_is_forest_master", False)
            if not is_forest and (self._docked_to or self._group_master_id is not None):
                self._break_free_from_cluster()

            try:
                from scriptree.shell.ring_main import _get_snap_engine
                snap = _get_snap_engine()
                if snap is not None:
                    snap.attach_drag(self._id)
                else:
                    _log(f"mouseMoveEvent: snap engine is None — attach_drag skipped id={self._id[:8]}")
            except Exception as exc:
                _log(f"mouseMoveEvent: attach_drag exception: {exc!r}")

        # Manual translation — fires moveEvent â†’ hexagonMoved â†’ snap engine tick.
        # Screen-edge guard (Bug 2 — clock-area crash): clamp requested position
        # to the containing screen's available geometry before calling move().
        # If the cursor has drifted outside every known screen (e.g. WM dragged
        # the window off-display), fall back to the primary screen's area.
        prev_top_left = self.pos()
        raw_pos = event.globalPosition().toPoint() - self._drag_offset
        new_top_left = self._clamp_to_screen(raw_pos)
        self.move(new_top_left.x(), new_top_left.y())

        # Bug 4 — shake-to-unassociate: sample movement direction during drag.
        # Only meaningful for standalone hexes that are members of a group.
        # Guard: if _group_master_id is None (not in a group) the shake handler
        # is a no-op anyway, but check explicitly before sampling to avoid
        # burning cycles near the tray.
        #
        # v0.8.0a1+ramps Bug 5 — also fire shake on RING masters so the
        # user can dispose of a ring (per: "shake to close and have a
        # box come up then to close, save or cancel").  The forest
        # master is explicitly excluded — it's the workspace root and
        # never closes by shake.
        is_shakeable_standalone = (
            self.role == "standalone"
            and self._group_master_id is not None
        )
        is_shakeable_ring = (
            self.role == "master"
            and not getattr(self, "_is_forest_master", False)
        )
        if is_shakeable_standalone or is_shakeable_ring:
            dx = new_top_left.x() - prev_top_left.x()
            dy = new_top_left.y() - prev_top_left.y()
            self._shake_detector.sample(dx, dy)
            if self._shake_detector.is_shaking():
                self._shake_detector.reset()
                if is_shakeable_ring:
                    self._close_ring_via_shake_with_prompt()
                else:
                    self._on_shake_detected()

        _now = _time.monotonic()
        if _now - self._last_drag_log_time >= 1.0:
            _log(
                f"drag {self._id[:8]} role={self.role} "
                f"pos=({self.x()},{self.y()}) drag_started={self._drag_started}"
            )
            self._last_drag_log_time = _now

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            _log(f"release drag_started={self._drag_started} id={self._id[:8]}")
            was_dragging = self._drag_started
            # v0.6.36 — trace release with current state.
            try:
                _trace.event(
                    "RELEASE",
                    id=self._id[:8],
                    role=self.role,
                    pos=(self.pos().x(), self.pos().y()),
                    was_dragging=was_dragging,
                )
            except Exception:  # noqa: BLE001
                pass
            if was_dragging:
                # End the drag — notify SnapEngine so it can commit a snap.
                self._drag_started = False
                if self._snap_overlay is not None:
                    self._snap_overlay.hide()
                try:
                    from scriptree.shell.ring_main import _get_snap_engine
                    snap = _get_snap_engine()
                    if snap is not None:
                        snap.detach_drag(self._id)
                    else:
                        _log(f"mouseReleaseEvent: snap engine is None - detach skipped id={self._id[:8]}")
                except Exception as exc:
                    _log(f"mouseReleaseEvent: detach_drag exception: {exc!r} id={self._id[:8]}")
            else:
                # No drag threshold crossed — pure click.
                self.click("single")
            # v0.6.36 — snapshot post-release so we can compare to
            # the press-time snapshot for any drag.
            try:
                _trace.snapshot(f"release-{self._id[:8]}")
            except Exception:  # noqa: BLE001
                pass
        super().mouseReleaseEvent(event)
        # Master-drag end: reflow members onto valid on-screen slots.
        # During the drag, members translate rigidly with the master
        # (see moveEvent).  When the master settles, any member that
        # would now be off-screen gets reattached to a still-free slot
        # whose top-left fits the screen.  This is the user's
        # ring-falls-off-edge requirement.
        if (
            event.button() == Qt.LeftButton
            and was_dragging
            and self.role == "master"
            and self._members
        ):
            # v0.8.0 P4 — recompute-at-drag-end DISABLED.
            #
            # Previously two passes ran here:
            #   1. ``_reflow_members_after_master_move`` (legacy v0.6.x):
            #      smooth-moved members toward slot-relative HOMEs,
            #      potentially reshuffling user-placed cells.
            #   2. ``_compute_layout(instant=True)`` (v0.7.2): re-derived
            #      every member's slot world position from the master's
            #      current pos and snapped them there.
            # Both passes implemented the slot-recompute behaviour that
            # the user explicitly does NOT want: "they shouldn't have
            # moved after I placed them. If they get forced to
            # rearrange they should move to the nearest entity, not
            # try to grab the available spot on forest."  Under the
            # v0.8.0 link/dock model, position is absolute; cells stay
            # where the cascade put them.  No recompute fires.
            #
            # Phase 5 will introduce the targeted "auto-undock for
            # forest-linked cells dragged away" logic on the
            # cell-alone-drag path; that's the new dock-break rule
            # that replaces this blanket recompute.
            #
            # v0.8.0a79 (item 10 — "cells gap / get left behind on a
            # fast drag") — one MANDATORY, un-throttled edge reflow at
            # rest.
            #
            # WHY this is needed and is NOT the recompute P4 disabled:
            # the live ``_live_edge_reflow_or_fold`` (moveEvent, ~7345)
            # is wall-clock throttled to ~50 ms, but Qt COALESCES a fast
            # drag into a few large-delta moveEvents.  So the LAST reflow
            # tick can fire at an INTERMEDIATE master position and never
            # again before release.  Two states then survive to rest and
            # nothing fixes them:
            #   (a) a member the throttle stranded off-screen, and
            #   (b) — the one nothing else can rescue — a member the tick
            #       *folded* (``_auto_hidden`` + ``setVisible(False)``)
            #       because no on-screen slot existed at that intermediate
            #       position, even though room exists at the RESTING
            #       position.  ``_settle_no_overlap`` (the only drag-end
            #       pass) explicitly SKIPS ``_auto_hidden`` members
            #       (see its subject loop), and its engine fallback fires
            #       only when the visible block can't slide at all — so a
            #       folded member stays hidden forever.
            # Forcing ONE reflow here, with the throttle cleared, re-runs
            # ``group_layout.repack`` against the TRUE final master
            # position: stranded members relocate, folded-but-now-fittable
            # members un-fold, and a member with genuinely no slot folds
            # (the historical, correct overflow behaviour).
            #
            # This does NOT reintroduce the recompute P4 removed: the
            # reflow only touches members that are currently OFF-screen
            # (its ``off_ids`` set); on-screen, user-placed members are
            # passed as ``fixed`` and kept verbatim.  So "cells stay where
            # I put them" still holds — we only rescue the ones the
            # throttle would otherwise leave off-screen or hidden.
            #
            # Corner-safe: a77 broke corner drags by *removing* the live
            # reflow (it is load-bearing for keeping the forest in the
            # corner while relocating cells on-screen around it).  This
            # ADDS one more invocation of that exact same path; the master
            # never moves (repack is relative to ``self.pos()``), so the
            # forest stays where the user dropped it.  Runs BEFORE the
            # ``_settle_no_overlap`` below, so settle then tidies overlap
            # on correctly-relocated, visible members.
            self._last_live_reflow_time = 0.0
            try:
                self._live_edge_reflow_or_fold()
            except Exception as exc:  # noqa: BLE001
                _log(
                    f"mouseReleaseEvent: final edge-reflow raised "
                    f"{exc!r} id={self._id[:8]}"
                )

        # v0.6.12 — drag-end settle: glide the just-released cell (or
        # the whole master group) to a non-overlapping, fully-on-screen
        # resting position.  No-op if already free.  This is the
        # ultimate guarantor of the user's "never overlap, never
        # off-screen" invariant — every other code path relies on
        # this safety net at rest.
        if event.button() == Qt.LeftButton and was_dragging:
            # v0.6.16 — masters that release near a forest-linked
            # cell *join the forest* (link=Forest, dock=Forest)
            # rather than absorbing the cell as a ring member.
            # This is the user-spec direction-asymmetry: "drag a
            # ring to a cell that is docked to the forest" should
            # park the ring beside the cell as a forest sibling,
            # not pull the cell into the ring.  Runs BEFORE the
            # absorb routine so we don't accidentally poach a
            # forest-linked free cell.
            if self.role == "master":
                try:
                    self._try_join_forest_near_member()
                except Exception as exc:  # noqa: BLE001
                    _log(
                        f"_try_join_forest_near_member raised {exc!r}"
                    )
            # v0.6.14 — masters that landed near a free cell on
            # release absorb it as a new ring member (and inherit
            # the forest link when applicable).  Runs BEFORE the
            # settle so any absorbed cells are part of the
            # subject set when no-overlap is computed.
            if self.role == "master":
                try:
                    self._try_absorb_nearby_free_cells()
                except Exception as exc:  # noqa: BLE001
                    _log(
                        f"_try_absorb_nearby_free_cells raised {exc!r}"
                    )
            # v0.8.0a1+ramps Bug 3 — when the released cell is a ring
            # master that just docked to another cell/ring/forest
            # (master._dock_partner_id set by ``_set_cell_dock`` in
            # ``_try_spawn_master`` Case M1), don't run the rigid
            # group-shift settle.  That pushes the master away from
            # its dock slot whenever even one member overlaps another
            # cell — the user-visible symptom: "I can't dock the
            # ring to a position if the cells in the ring are
            # sitting over other cells".  Instead, leave the master
            # at its snap-committed position and relocate just the
            # overlapping members individually to free honeycomb
            # slots around the ring.
            try:
                if (
                    self.role == "master"
                    and self._dock_partner_id is not None
                ):
                    self._relocate_overlapping_members_individually()
                else:
                    self._settle_no_overlap()
            except Exception as exc:  # noqa: BLE001
                _log(
                    f"settle/relocate (drag-end) raised {exc!r}"
                )

            # v0.8.0a83 — REMEMBER where the user just dropped this cell
            # (offset from its forest hub) so the arrangement is restored on
            # expand / startup / screen-rescue.  Captured ONLY here — a real
            # USER drag-end (this block is gated on ``was_dragging``) — never
            # from a system relocation, so the remembered layout reflects user
            # intent.  Runs AFTER the settle so the stored offset is the final
            # non-overlapping resting position.
            try:
                self._capture_remembered_offset()
            except Exception as exc:  # noqa: BLE001
                _log(f"capture remembered offset raised {exc!r}")

    def _single_leaf_path(self) -> str | None:
        """Return the absolute path of this cell's lone tool leaf, or
        ``None`` if the cell doesn't bind exactly one tool.

        Resolution by cell role:

        * **Standalone bound to a ``.scriptree``** -> that path
          (one tool by definition).
        * **Standalone bound to a ``.scriptreetree``** -> the lone
          leaf path IFF the tree contains exactly one leaf
          (recursively); otherwise ``None``.
        * **Master cell** (ring or forest) -> the lone leaf across
          ALL members' catalogs: if every member is bound and the
          combined leaf count is exactly one, return that path;
          otherwise ``None``.
        * **Empty / no catalog** -> ``None``.
        * **Bound to a ``.scriptreering``** -> ``None`` (the ring
          contains cells, not tools per se -- we'd need to recurse
          into each cell's binding, which can be a tree, ring,
          etc.; keeping the shortcut intentionally narrow here
          avoids confusing edge cases).

        Used by ``click("double")`` to short-circuit the menu /
        lock-open tree dance when there's only one possible target.
        Errors reading a catalog (broken JSON, missing file) return
        ``None`` so the standard menu path runs and the user can
        see the issue.
        """
        from pathlib import Path

        def _count_leaves_in_tree(tree_path: str) -> tuple[int, str | None]:
            """Return ``(count, last_leaf_path)`` for a tree.

            ``last_leaf_path`` is meaningful only when ``count == 1``;
            otherwise we keep counting until we know "≥ 2" and bail
            out (the caller only cares whether it's exactly one).
            """
            try:
                from scriptree.core.io import load_tree
                tree = load_tree(tree_path)
            except Exception:  # noqa: BLE001
                return (0, None)
            tree_dir = Path(tree_path).parent
            found: list[str] = []

            def _walk(nodes):  # noqa: ANN001
                for n in nodes:
                    if getattr(n, "type", "") == "leaf":
                        leaf_path = getattr(n, "path", None)
                        if leaf_path:
                            # Tree leaf paths are typically relative
                            # to the tree file's directory.
                            resolved = (tree_dir / leaf_path).resolve()
                            found.append(str(resolved))
                            if len(found) > 1:
                                return  # early bail
                    else:
                        _walk(getattr(n, "children", []) or [])
                        if len(found) > 1:
                            return
            _walk(tree.nodes)
            if len(found) == 1:
                return (1, found[0])
            return (len(found), None)

        # --- master case: walk every member's binding ---
        if self.role == "master":
            members = list(getattr(self, "_members", {}).keys())
            if not members:
                return None
            from scriptree.shell.cell_registry import CellRegistry
            registry = CellRegistry.instance()
            total = 0
            last_leaf: str | None = None
            for mid in members:
                cell = registry.get(mid)
                if cell is None:
                    continue
                cp = getattr(cell, "catalog_path", None)
                if not cp:
                    continue
                p = Path(cp)
                if p.suffix.lower() == ".scriptree":
                    total += 1
                    last_leaf = str(p.resolve())
                elif p.suffix.lower() == ".scriptreetree":
                    cnt, leaf = _count_leaves_in_tree(str(p))
                    total += cnt
                    if cnt == 1 and total == 1:
                        last_leaf = leaf
                else:
                    return None  # rings/unknown -> don't short-circuit
                if total > 1:
                    return None
            return last_leaf if total == 1 else None

        # --- standalone case ---
        cp = getattr(self, "catalog_path", None)
        if not cp:
            return None
        p = Path(cp)
        ext = p.suffix.lower()
        if ext == ".scriptree":
            return str(p.resolve())
        if ext == ".scriptreetree":
            cnt, leaf = _count_leaves_in_tree(str(p))
            return leaf if cnt == 1 else None
        return None

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
    # moveEvent — emit hexagonMoved so SnapEngine tick uses fresh coords.
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
        # v0.6.36 — diagnostic trace.  Every moveEvent is logged so
        # the user-reported "they move randomly" can be analysed
        # post-hoc by tail-ing the trace file.
        try:
            old = event.oldPos()
            new = event.pos()
            _trace.event(
                "MOVE",
                id=self._id[:8],
                role=self.role,
                from_=(old.x(), old.y()),
                to=(new.x(), new.y()),
                delta=(new.x() - old.x(), new.y() - old.y()),
                drag=self._drag_started,
                slot=self._slot,
                floating=self._floating_intent,
                parent=(
                    self._group_master_id[:8]
                    if self._group_master_id else None
                ),
            )
        except Exception:  # noqa: BLE001
            pass
        registry.hexagonMoved.emit(self._id)

        # Amendment 2 — master group-drag: translate only the POSITIONALLY-DOCKED
        # members (those in self._positioned). Members that have broken free stay
        # where they are on screen; their stored position in self._members is NOT
        # updated during a master drag — they remember their independent position.
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
            # v0.8.0 P2 — gate dropped (was: ``and self._positioned``).
            # Phase 2's link-driven cascade has to fire whenever the
            # master has ANY link children, not just when it has
            # ``_positioned`` membership.  A forest with a single
            # loose-linked ring (ring's link_parent_id = forest but
            # ring not in forest._positioned) was the regression
            # this gate caused — the cascade was skipped and the
            # ring didn't follow.  Body handles an empty drag_targets
            # case as a no-op.
        ):
            delta_x = current_pos.x() - last.x()
            delta_y = current_pos.y() - last.y()
            if delta_x != 0 or delta_y != 0:
                # Shift the stored preferred positions for POSITIONED members
                # so that collapse/expand targets track the group's new location.
                self._shift_positioned_members(delta_x, delta_y)

                if _now - self._last_groupmove_log_time >= 1.0:
                    _log(
                        f"group-move from {self._id[:8]} (master); "
                        f"translating {len(self._positioned)} positioned member(s) "
                        f"by ({delta_x},{delta_y})"
                    )
                    self._last_groupmove_log_time = _now
                # v0.6.36 — trace the group-move (every frame, not
                # throttled, so we can see jitter in the trace).
                try:
                    _trace.event(
                        "GROUP_MOVE",
                        master=self._id[:8],
                        delta=(delta_x, delta_y),
                        positioned=len(self._positioned),
                        member_ids=[m[:8] for m in self._positioned],
                    )
                except Exception:  # noqa: BLE001
                    pass

                # v0.6.38 — drag-target set = UNION of
                #   (1) ``_positioned`` (the legacy authority), and
                #   (2) cells in ``_members`` that claim this master
                #       as parent AND have a slot assigned.
                # The trace from v0.6.37 surfaced cells in (2) that
                # had been silently dropped from ``_positioned`` by
                # a snap-commit pair-master spawn that closed —
                # those cells need to drag with the master.
                # Including (1) keeps pre-slot cells (legacy or
                # synthetic tests) working without modification.
                drag_targets: set[str] = set(self._positioned)
                for mid in list(self._members.keys()):
                    if mid in drag_targets:
                        continue
                    m = registry.get(mid)
                    if m is None:
                        continue
                    if (
                        m._group_master_id == self._id
                        and m._slot is not None
                    ):
                        drag_targets.add(mid)
                        # Heal _positioned while we're here.
                        self._positioned.add(mid)

                # v0.8.0 P2 — extend drag_targets per the link-driven
                # cascade rule.
                #
                # v0.8.0a1+ramps Bug 10 — under the latest user spec,
                # BOTH forest and ring cascades gate on the dock-
                # path proxy (``_positioned`` membership).  The cell
                # has to actually be in the cluster to follow.
                #
                # Originally P2 made ring drag unconditional for any
                # link-child of the ring ("cells linked with the
                # ring move with the ring, they do not have to be
                # docked with it"), then v0.8.0a1+ramps gated the
                # forest case too.  This iteration generalises the
                # gate to rings.  User: "when I drag a cell off the
                # ring, it should stay put when I drag the ring."
                # ``_break_free_from_cluster`` drops the dragged
                # cell from ``_positioned`` at the 4 px drag
                # threshold (preserving link membership), so cells
                # the user has pulled out of the ring are excluded
                # from this cascade — they stay put when the ring
                # later moves.  The loop body below is now a no-op
                # for both cases; the legacy ``_positioned`` union
                # above is the sole authority on what moves.
                is_self_forest = getattr(
                    self, "_is_forest_master", False,
                )
                for mid in registry.link_children_of(self._id):
                    if mid in drag_targets:
                        continue
                    m = registry.get(mid)
                    if m is None:
                        continue
                    # Both forest and ring cases: no-op.  Cells the
                    # user dragged out (no longer in _positioned)
                    # stay put.
                _GROUP_MOVE_IN_PROGRESS.add(self._id)
                try:
                    for member_id in drag_targets:
                        member = registry.get(member_id)
                        if member is None:
                            continue
                        # v0.6.11 — kill any in-flight eased-move on
                        # this member before applying the rigid drag
                        # translation.  Without this, a still-running
                        # _pos_anim from a prior repack/reflow keeps
                        # driving the member toward its old target and
                        # the drag delta is overwritten the next
                        # animation tick — the cell appears to "lag
                        # behind" or get "left behind" entirely.
                        prior = getattr(member, "_pos_anim", None)
                        if prior is not None:
                            try:
                                prior.stop()
                            except Exception:  # noqa: BLE001
                                pass
                            member._pos_anim = None
                        member.move(member.pos().x() + delta_x, member.pos().y() + delta_y)
                        # v0.6.34 — when the moved member is itself a
                        # master with its own positioned cluster, shift
                        # its members by the same delta so a nested
                        # group (forest → ring → cells) moves rigidly
                        # as one unit.  Using ``_shift_positioned_members``
                        # (not the cell's moveEvent cascade) keeps the
                        # update self-contained and avoids the
                        # collapse-interference bug introduced by the
                        # v0.6.32 cascade helper.
                        if (
                            member.role == "master"
                            and member._positioned
                            and member._id not in _GROUP_MOVE_IN_PROGRESS
                        ):
                            try:
                                member._shift_positioned_members(
                                    delta_x, delta_y,
                                )
                                from scriptree.shell.cell_registry import (
                                    CellRegistry as _Reg,
                                )
                                _reg = _Reg.instance()
                                _GROUP_MOVE_IN_PROGRESS.add(member._id)
                                try:
                                    for sub_id in list(member._positioned):
                                        sub = _reg.get(sub_id)
                                        if sub is None:
                                            continue
                                        sub_prior = getattr(sub, "_pos_anim", None)
                                        if sub_prior is not None:
                                            try:
                                                sub_prior.stop()
                                            except Exception:  # noqa: BLE001
                                                pass
                                            sub._pos_anim = None
                                        sub.move(
                                            sub.pos().x() + delta_x,
                                            sub.pos().y() + delta_y,
                                        )
                                finally:
                                    _GROUP_MOVE_IN_PROGRESS.discard(member._id)
                            except Exception as exc:  # noqa: BLE001
                                _log(
                                    f"moveEvent nested-shift: inner master "
                                    f"{member._id[:8]} raised {exc!r}"
                                )
                finally:
                    _GROUP_MOVE_IN_PROGRESS.discard(self._id)

                # v0.6.11 — live edge reflow (replaces the old hide-only
                # behaviour): when the group is dragged toward an edge,
                # off-screen members are *relocated* to free on-screen
                # honeycomb slots so they stay bonded and visible.  The
                # call is throttled internally to ~50 ms; only the final
                # call inside _live_edge_reflow_or_fold may fall back to
                # the historical auto-hide when there's genuinely no
                # on-screen slot left.
                self._live_edge_reflow_or_fold()

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
        # v0.6.21 — apply the user's configured font / icon scale
        # (cell Settings → Menu tab; default 125%).  Same helper the
        # single-click popup uses so context and popup match.
        try:
            from scriptree.shell.tree_popup import apply_menu_appearance
            apply_menu_appearance(menu)
        except Exception as exc:  # noqa: BLE001
            _log(f"_show_context_menu: apply_menu_appearance: {exc!r}")

        # v0.6.5 — OS standard icons on the program/context-menu items
        # (the user: "menu items both for the program and apps").
        from PySide6.QtWidgets import QStyle as _QStyle
        _SP = _QStyle.StandardPixmap

        def _ic(which):  # noqa: ANN001, ANN202
            _a = QApplication.instance()
            return _a.style().standardIcon(which) if _a else None

        def _seticon(obj, which) -> None:  # noqa: ANN001
            """Set a standard icon on a QAction or QMenu, no-op-safe."""
            try:
                ic = _ic(which)
                if ic is not None:
                    obj.setIcon(ic)
            except Exception:  # noqa: BLE001
                pass

        def _seticon_bundled(obj, name: str) -> None:  # noqa: ANN001
            """v0.6.15 — set an icon from our bundled `icons/` set on
            a QAction or QMenu.  Used where a category-specific glyph
            reads better than the generic Qt standard one (e.g.
            ``ring`` for the Tree Ring submenu instead of
            SP_DriveNetIcon)."""
            try:
                from scriptree.shell.icon_assets import (
                    bundled_icon_png_path,
                )
                p = bundled_icon_png_path(name)
                if p is None:
                    return
                ic = QIcon(str(p))
                if not ic.isNull():
                    obj.setIcon(ic)
            except Exception:  # noqa: BLE001
                pass

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

        # V3 v0.3.15+ — forest hook.  When the cell is the forest
        # master, ``ForestController`` registers a callback here
        # that prepends a ``Forest`` submenu with workspace-wide
        # actions (Save forest, Auto-add, Forest settings, …)
        # alongside the standard cell context menu.  Non-forest
        # cells skip this entirely.
        forest_hook = getattr(self, "_forest_menu_extension", None)
        if forest_hook is not None:
            try:
                # v0.8.0a25+ -- pass ``self`` as the originating cell
                # so the forest extension can offer cell-specific
                # actions (uninstall, etc.).  Older
                # ``_populate_forest_menu`` accepts ``(menu)``
                # only; the controller's new signature defaults
                # the cell to None for the back-compat case where
                # this hook fires before the controller has been
                # updated.
                try:
                    forest_hook(menu, self)
                except TypeError:
                    # Hook still on the old 1-arg signature.
                    forest_hook(menu)
                menu.addSeparator()
            except Exception as _exc:  # noqa: BLE001
                _log(f"forest_menu_extension failed: {_exc!r}")

        # v0.8.0a21+ — parallel hook for ``.scriptreetree``-bound cells.
        # ``TreeController.attach_to_cell`` installs the callback;
        # non-tree-bound cells have ``_tree_menu_extension is None``
        # and skip this block entirely.  Same try/except shape as the
        # forest hook above so a buggy menu extension never crashes
        # the right-click — at worst we log and keep going.
        tree_hook = getattr(self, "_tree_menu_extension", None)
        if tree_hook is not None:
            try:
                tree_hook(menu)
                menu.addSeparator()
            except Exception as _exc:  # noqa: BLE001
                _log(f"tree_menu_extension failed: {_exc!r}")

        # ── ScripTree submenu ─────────────────────────────────────
        # Groups all load / save / clear catalog actions plus the
        # Open recent sub-sub-menu.  Per user direction (2026-05-07):
        # "Catalogue should say ScripTree instead."
        catalog_menu = QMenu("ScripTree", menu)
        # v0.6.15 — submenu marker uses our bundled `script` glyph
        # (document + prompt, the canonical script archetype) so the
        # menu reads as "things that load/save catalogs" rather
        # than the generic OS folder icon.
        _seticon_bundled(catalog_menu, "script")
        load_scriptree_action = catalog_menu.addAction("Load ScripTree…")
        _seticon(load_scriptree_action, _SP.SP_DialogOpenButton)
        load_scriptreetree_action = catalog_menu.addAction("Load ScripTreeTree…")
        _seticon(load_scriptreetree_action, _SP.SP_DialogOpenButton)

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
        _seticon(recent_menu, _SP.SP_FileDialogDetailedView)
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
        _seticon(save_as_action, _SP.SP_DialogSaveButton)
        save_as_action.setEnabled(self._catalog_path is not None)

        clear_catalog_action = None
        if self._catalog_path is not None:
            clear_catalog_action = catalog_menu.addAction("Clear loaded ScripTree")
            _seticon(clear_catalog_action, _SP.SP_DialogResetButton)

        menu.addMenu(catalog_menu)

        # ── Tree Ring submenu ─────────────────────────────────────
        # Save/load + autoload of the current cell or the whole ring.
        # When a ring has already been saved (``_saved_ring_path``
        # populated), offer both "Save" (overwrite) and "Save as…"
        # (fork to a new file).  Otherwise only "Save as…" — there's
        # no remembered path to overwrite.
        ring_menu = QMenu("Tree Ring", menu)
        # v0.6.15 — submenu marker uses our `ring` glyph (concentric
        # circles, hub + orbit) instead of the OS network-drive icon
        # that read as wildly off-topic.
        _seticon_bundled(ring_menu, "ring")
        already_saved = getattr(self, "_saved_ring_path", None) is not None

        save_ring_action = None
        if already_saved:
            label = (
                "Save Tree Ring" if self.role != "master"
                else "Save group as Tree Ring"
            )
            save_ring_action = ring_menu.addAction(label)
            _seticon(save_ring_action, _SP.SP_DialogSaveButton)

        if self.role == "master":
            save_ring_as_action = ring_menu.addAction(
                "Save group as Tree Ring as…"
            )
        else:
            save_ring_as_action = ring_menu.addAction(
                "Save as Tree Ring…"
            )
        _seticon(save_ring_as_action, _SP.SP_DialogSaveButton)
        load_ring_action = ring_menu.addAction("Load Tree Ring…")
        _seticon(load_ring_action, _SP.SP_DialogOpenButton)

        # "Auto-load on startup" sub-sub-menu.
        autoload_menu = QMenu("Auto-load on startup", ring_menu)
        _seticon(autoload_menu, _SP.SP_BrowserReload)
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
        # v0.6.15 — submenu marker uses our `tool` glyph (the
        # universal wrench, fitting for cell-itself actions like
        # spawn / leave / disband).
        _seticon_bundled(cell_menu, "tool")
        spawn_action = cell_menu.addAction("Spawn another cell")
        # "Spawn another" = a fresh package coming into existence.
        _seticon_bundled(spawn_action, "package")

        # Group membership actions.  Three possible entries:
        #   * Leave forest  — when this cell is grouped under the
        #     forest master.  For a ring-master attached to the
        #     forest, leaves ONLY the forest membership (the ring's
        #     own members stay intact).  v0.3.15+.
        #   * Leave group   — for a non-master cell grouped under
        #     a regular ring master.
        #   * Disband group — for any master with members (including
        #     a ring-master that's also a forest member, where it
        #     means "tear down THIS ring's members" while the ring
        #     itself stays attached to the forest).
        leave_group_action = None
        leave_forest_action = None
        disband_action = None
        # Detect forest membership: our group_master is the forest.
        _is_forest_member = False
        if self._group_master_id is not None:
            from scriptree.shell.cell_registry import CellRegistry as _CR
            _master = _CR.instance().get(self._group_master_id)
            if _master is not None and getattr(
                _master, "_is_forest_master", False
            ):
                _is_forest_member = True

        if self._group_master_id is not None or (
            self.role == "master" and self._members
        ):
            cell_menu.addSeparator()
            if self.role == "master":
                # Master cell.
                if _is_forest_member:
                    # Ring-master attached to the forest — offer
                    # both "Leave forest" (sever forest membership,
                    # keep ring) and "Disband group" (tear down
                    # the ring's own members).
                    leave_forest_action = cell_menu.addAction(
                        "Leave forest (keep ring intact)"
                    )
                    # v0.6.15 — `scissors` reads as "cut the link" /
                    # "detach from the parent group", consistent
                    # across all three leave/disband actions below.
                    _seticon_bundled(leave_forest_action, "scissors")
                if self._members:
                    disband_action = cell_menu.addAction("Disband group")
                    _seticon_bundled(disband_action, "scissors")
                    # Preserve the legacy variable name so existing
                    # downstream dispatch keeps working unchanged.
                    leave_group_action = disband_action
            else:
                # Non-master cell in a group.
                if _is_forest_member:
                    leave_group_action = cell_menu.addAction("Leave forest")
                else:
                    leave_group_action = cell_menu.addAction("Leave group")
                _seticon_bundled(leave_group_action, "scissors")

        # v0.6.20 — the v0.6.17 "Tuck with my master" per-cell opt-in
        # and the v0.6.19 "Collapse this group" right-click toggle
        # were both removed: single-click on a master is the
        # one-and-only "collapse all linked cells" gesture, and
        # every member tucks by default (no opt-in/out at the cell
        # level).  Locals kept as None so the action-dispatch
        # branches below still typecheck.
        collapse_with_action = None
        collapse_toggle_action = None

        menu.addMenu(cell_menu)

        menu.addSeparator()

        # ── Top-level: about / settings / preferences ────────────
        about_action = menu.addAction(f"About {brand}")
        _seticon(about_action, _SP.SP_MessageBoxInformation)
        settings_action = menu.addAction("Settings…")
        # v0.6.15 — `settings` (three labelled sliders) is the
        # category archetype; SP_FileDialogDetailedView reads as
        # "show a file list", not "configure this thing".
        _seticon_bundled(settings_action, "settings")
        preferences_action = menu.addAction("Preferences…")
        _seticon_bundled(preferences_action, "settings")
        menu.addSeparator()

        # ---- Close / exit actions — role-aware ----
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
            _seticon(close_ring_action, _SP.SP_DialogCloseButton)
            close_all_related_action = menu.addAction(
                "Close all related (master + members)"
            )
            _seticon(close_all_related_action, _SP.SP_DialogCloseButton)
        else:
            close_cell_action = menu.addAction("Close this cell")
            _seticon(close_cell_action, _SP.SP_DialogCloseButton)
        exit_all_action = menu.addAction("Exit all")
        _seticon(exit_all_action, _SP.SP_BrowserStop)

        # v0.6.22 — re-apply menu-appearance AFTER all submenus are
        # added so the catalog / Tree Ring / Cell sub-menus all
        # match the top-level font + icon scale.  The pre-build
        # call only catches the top level; submenus added via
        # addMenu(label) start with default font and need the
        # recursive walk.
        try:
            from scriptree.shell.tree_popup import apply_menu_appearance
            apply_menu_appearance(menu)
        except Exception as exc:  # noqa: BLE001
            _log(
                f"_show_context_menu: re-apply after build failed: "
                f"{exc!r}"
            )

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
            self._update_hover_tooltip()
            # v0.8.0a21+ -- detach any tree controller since the
            # catalog is now empty.  See the method docstring.
            self._attach_tree_controller_if_applicable()
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
        elif leave_forest_action is not None and chosen == leave_forest_action:
            self._leave_forest_keep_ring()
        elif leave_group_action is not None and chosen == leave_group_action:
            self._explicit_leave_group()
        elif (
            collapse_with_action is not None
            and chosen == collapse_with_action
        ):
            # v0.6.17 — toggle the per-cell opt-in.  Persist
            # immediately so the choice survives a restart.
            self._collapse_with_master = bool(
                collapse_with_action.isChecked()
            )
            try:
                self._save_settings()
            except Exception as exc:  # noqa: BLE001
                _log(
                    f"_collapse_with_master toggle: "
                    f"_save_settings raised {exc!r}"
                )
            _log(
                f"{self._id[:8]}: _collapse_with_master = "
                f"{self._collapse_with_master}"
            )
        elif (
            collapse_toggle_action is not None
            and chosen == collapse_toggle_action
        ):
            # v0.6.19 — master collapse/expand toggle.  The action
            # label was decided when building the menu based on
            # the current ``_collapse_state``; flipping just fires
            # the same toggle helper master single-click used to
            # call.
            try:
                self._toggle_collapse()
            except Exception as exc:  # noqa: BLE001
                _log(f"collapse_toggle: _toggle_collapse raised {exc!r}")
        elif chosen == about_action:
            # None parent: inherits OS chrome, not the hex's translucent palette.
            try:
                from scriptree import __version__ as _ver
            except Exception:  # noqa: BLE001
                _ver = "(unknown)"
            # v0.6.29 — show the build date alongside the version so
            # the user can tell which build they're running when
            # revisions happen quickly.
            try:
                from scriptree import __build_date__ as _bd  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                _bd = ""
            build_line = (
                f"<br><b>Built:</b> {_bd}" if _bd else ""
            )
            msg = QMessageBox(None)
            msg.setWindowTitle(f"About {brand}")
            msg.setText(
                f"<b>{app_name_long}</b><br>"
                f"{tagline}<br><br>"
                f"<b>Version:</b> {_ver}"
                f"{build_line}"
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
            # Ring on disk now matches the in-memory state — clean.
            self._ring_dirty = False
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
            _log(f"Ring loaded from {path} — master {master._id[:8]}")
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
            _log(f"_autoload_set_scope(system): not admin — requesting elevation")
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
            _log("_autoload_disable: no saved path — nothing to disable")
            return

        for scope in ("user", "system"):
            try:
                paths = [str(p) for p in list_autoload_rings(scope)]  # type: ignore[arg-type]
                if str(saved_path) in paths:
                    remove_autoload_ring(_Path(saved_path), scope)  # type: ignore[arg-type]
            except Exception as exc:
                _log(f"_autoload_disable: remove_autoload_ring({scope}) failed: {exc!r}")

    def _load_catalog_dialog(self, prefer_ext: str = "") -> None:
        """Open a file dialog and load a catalog into this cell or a sibling.

        Behaviour (v0.2.11):

        * **Empty cell** (``self._catalog_path is None`` and not a
          master): the chosen catalog binds to *this* cell.  No new
          window is spawned — the empty placeholder cell becomes the
          loaded one.
        * **Bound cell** (already has a catalog) or **master**: a
          fresh sibling cell is spawned next to ``self``, bound to
          the chosen catalog.  ``self`` stays untouched, matching
          the v0.2.8 contract for non-empty cells.

        ``prefer_ext`` — ``".scriptree"`` or ``".scriptreetree"``
        selects that filter by default in the dialog.  The user can
        still switch filters to pick the other type.
        """
        from pathlib import Path as _Path

        # Start in the sample-catalog directory if it exists.
        project_root = _Path(__file__).resolve().parent.parent.parent
        start_dir = str(project_root / "sample-catalog")

        _FILTER_TOOL = "ScripTree files (*.scriptree)"
        _FILTER_TREE = "ScripTreeTree files (*.scriptreetree)"
        _FILTER_ALL  = "All catalog files (*.scriptree *.scriptreetree)"
        _FILTER_ANY  = "All files (*)"
        all_filters = ";;".join([_FILTER_TOOL, _FILTER_TREE, _FILTER_ALL, _FILTER_ANY])

        action = "loads here" if self._can_bind_self() else "opens in a new cell"
        if prefer_ext == ".scriptreetree":
            default_filter = _FILTER_TREE
            caption = f"Load ScripTreeTree ({action})"
        elif prefer_ext == ".scriptree":
            default_filter = _FILTER_TOOL
            caption = f"Load ScripTree ({action})"
        else:
            default_filter = _FILTER_ALL
            caption = f"Load ScripTree or ScripTreeTree ({action})"

        chosen, _ = QFileDialog.getOpenFileName(
            None,
            caption,
            start_dir,
            all_filters,
            default_filter,
        )
        if chosen:
            self._open_catalog_path(chosen)

    def _open_recent_catalog(self, path: str) -> None:
        """Load a recent catalog into this cell (when empty) or a
        sibling (when already bound).  See ``_load_catalog_dialog``
        for the empty-vs-bound rule."""
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
        self._open_catalog_path(path)

    def _can_bind_self(self) -> bool:
        """True iff a chosen catalog should populate this cell rather
        than spawn a sibling.

        Empty standalone cells (no role=master, no catalog bound)
        qualify — they're placeholders waiting for content, so loading
        into them is the natural action.  Master cells and already-
        bound standalones get sibling-spawn behaviour instead.
        """
        return (
            self.role != "master"
            and not self._catalog_path
        )

    def _open_catalog_path(self, catalog_path: str) -> None:
        """Dispatch a chosen catalog path to the right entry-point.

        * ``.scriptree`` / ``.scriptreetree`` on an **empty** cell →
          ``_bind_catalog_to_self``.
        * ``.scriptree`` / ``.scriptreetree`` on a **bound** cell or
          **master** → ``_spawn_sibling_with_catalog``.
        * ``.scriptreering`` → handled by ``_open_ring_path`` so an
          empty cell gets replaced by the loaded ring rather than
          orphaned next to it.
        """
        from pathlib import Path as _Path

        ext = _Path(catalog_path).suffix.lower()
        if ext == ".scriptreering":
            self._open_ring_path(catalog_path)
            return
        if self._can_bind_self():
            self._bind_catalog_to_self(catalog_path)
        else:
            self._spawn_sibling_with_catalog(catalog_path)

    def _bind_catalog_to_self(self, catalog_path: str) -> None:
        """Bind ``catalog_path`` to *this* cell — the same in-place
        behaviour as the drop-on-standalone code path.  Updates the
        recent-files list, refreshes the label cache, and triggers
        a repaint.
        """
        from pathlib import Path as _Path
        from scriptree.shell import recent_files as _rf

        try:
            resolved = str(_Path(catalog_path).resolve())
        except OSError:
            resolved = catalog_path
        self._catalog_path = resolved
        try:
            self._save_settings()
        except Exception as exc:  # noqa: BLE001
            _log(f"_bind_catalog_to_self: _save_settings raised {exc!r}")
        # v0.8.0a21+ -- catalog binding changed via Load ScripTree…,
        # drag-drop, or "Open recent…".  Re-sync the tree controller.
        # The helper handles attach (new tree), rebind (different
        # tree), and detach (non-tree catalog) in one call.
        self._attach_tree_controller_if_applicable()
        try:
            _rf.add(resolved)
        except Exception as exc:  # noqa: BLE001
            _log(f"_bind_catalog_to_self: recent_files.add raised {exc!r}")
        self._label_cache = None
        try:
            self._refresh_label_from_catalog()
        except Exception as exc:  # noqa: BLE001
            _log(f"_bind_catalog_to_self: _refresh_label_from_catalog raised {exc!r}")
        self.update()
        _log(f"_bind_catalog_to_self: bound {resolved!r} to cell {self._id[:8]}")

    def _open_ring_path(self, ring_path: str) -> None:
        """Load a ``.scriptreering`` file.

        When called on an **empty** cell, this cell is closed first —
        the loaded ring's master + members take its place on screen.
        On a **bound** cell or **master**, the ring loads alongside
        whatever is already there (no replacement).

        The actual ring spawning is done by ``ring_io.load_ring`` so
        the master's auto-repack and edge-fold checks run normally.
        """
        from pathlib import Path as _Path
        from scriptree.shell.cell_registry import CellRegistry
        from scriptree.shell.ring_io import load_ring
        from scriptree.shell.ring_main import _get_snap_engine

        registry = CellRegistry.instance()
        snap = _get_snap_engine()
        path = _Path(ring_path)

        replace_self = self._can_bind_self()
        try:
            master = load_ring(path, self._branding, registry, snap)
            master._saved_ring_path = path
            _log(
                f"_open_ring_path: loaded {path.name} - master {master._id[:8]} "
                f"(replace_self={replace_self})"
            )
        except Exception as exc:  # noqa: BLE001
            _log(f"_open_ring_path: load_ring failed: {exc!r}")
            QMessageBox.warning(
                None, "Load failed", f"Could not load ring:\n{exc}",
            )
            return

        if replace_self:
            # Empty placeholder — let the freshly-loaded ring stand
            # in for it.  We close ``self`` last so the ring shell
            # doesn't see an empty desktop and quit before the new
            # master is registered.
            self.close()

    def _spawn_sibling_with_catalog(self, catalog_path: str) -> None:
        """Spawn a fresh standalone cell next to this one, bound to
        ``catalog_path``.  This cell stays untouched.

        The new cell is wired into the SnapEngine so it can dock with
        existing cells.  Position: offset by one cell width to the
        right of this cell, clamped to the screen.  Used by both
        Load… dialogs and Open recent.
        """
        from pathlib import Path as _Path
        from scriptree.shell import recent_files as _rf

        try:
            new_cell = CellWindow(
                self._branding,
                catalog_path=str(_Path(catalog_path).resolve()),
            )
        except Exception as exc:  # noqa: BLE001
            _log(
                f"_spawn_sibling_with_catalog: CellWindow ctor failed "
                f"for {catalog_path!r}: {exc!r}"
            )
            QMessageBox.warning(
                None, "Could not load catalog",
                f"Failed to create cell for {catalog_path}:\n\n{exc}",
            )
            return

        # Position offset to the right of this cell; clamp to screen.
        offset = self.width() + 12
        new_x = self.pos().x() + offset
        new_y = self.pos().y()
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            new_x = max(
                avail.left(),
                min(new_x, avail.right() - new_cell._size_px),
            )
            new_y = max(
                avail.top(),
                min(new_y, avail.bottom() - new_cell._size_px),
            )
        new_cell.move(new_x, new_y)

        # Wire to the snap engine so the new cell can dock with
        # existing cells (and rings).
        try:
            from scriptree.shell.ring_main import _wire_hex_to_snap
            _wire_hex_to_snap(new_cell)
        except Exception as exc:  # noqa: BLE001
            _log(
                f"_spawn_sibling_with_catalog: snap-engine wire failed: "
                f"{exc!r} — drag-snap will not engage for the new cell"
            )

        new_cell.show()
        new_cell._fade_in()
        try:
            new_cell._settle_no_overlap()
        except Exception as exc:  # noqa: BLE001
            _log(f"_settle_no_overlap (sibling) raised {exc!r}")
        _rf.add(catalog_path)
        _log(
            f"Spawned sibling cell {new_cell._id[:8]} bound to "
            f"{_Path(catalog_path).name!r}; this cell ({self._id[:8]}) "
            f"stays untouched."
        )

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
        self._update_hover_tooltip()
        # v0.8.0a21+ -- Save-as redirects the cell to a new path on
        # disk; the existing tree controller's ``tree_file`` is now
        # stale.  Re-sync so the new path is what the right-click
        # menu's Tree actions operate on.
        self._attach_tree_controller_if_applicable()
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
                    member._link_parent_id = None  # v0.8.0 P1 mirror
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
            _log(f"_explicit_leave_group: {self._id[:8]} not in any group — no-op")
            return

        master = registry.get(mid)
        if master is not None:
            master._members.pop(self._id, None)
            master._positioned.discard(self._id)
            master._dock_partners.discard(self._id)
            # Member removed — ring is dirty (membership changed).
            master._ring_dirty = True

        self._group_master_id = None

        self._link_parent_id = None  # v0.8.0 P1 mirror
        self._docked_to.clear()
        self._dock_partners.clear()
        self.update()  # Bug 5: refresh outline (now unassociated â†’ green)
        _log(f"Standalone {self._id[:8]} left group (master={mid and mid[:8]})")

        # Close master if fewer than 2 members remain.
        if master is not None:
            _check_master_validity(master, registry)

    def _leave_forest_keep_ring(self) -> None:
        """Detach this cell from the FOREST's group while keeping
        its own ring intact (V3 v0.3.15+).

        For a ring-master that's currently a forest member:
          * Removes self from forest._members / _positioned /
            _dock_partners.
          * Clears self._group_master_id.
          * Does NOT touch self._members (the ring's own members
            stay grouped under this master — the ring lives on as
            a top-level standalone ring).
          * Repacks the forest so its remaining members rearrange.

        For a non-master cell whose group_master is the forest, the
        existing ``_explicit_leave_group`` already does the right
        thing — this method is the master-specific variant that
        protects the ring's children from being disbanded.
        """
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()

        forest_id = self._group_master_id
        if forest_id is None:
            _log(
                f"_leave_forest_keep_ring: {self._id[:8]} not in "
                f"any group — no-op"
            )
            return

        forest = registry.get(forest_id)
        if forest is not None and getattr(
            forest, "_is_forest_master", False
        ):
            forest._members.pop(self._id, None)
            forest._positioned.discard(self._id)
            forest._dock_partners.discard(self._id)
            try:
                forest._repack_members()
            except Exception as exc:  # noqa: BLE001
                _log(
                    f"_leave_forest_keep_ring: forest repack "
                    f"failed: {exc!r}"
                )

        self._group_master_id = None

        self._link_parent_id = None  # v0.8.0 P1 mirror
        # Don't clear self._docked_to / _dock_partners across the
        # board — those track the ring's INTERNAL dock graph, not
        # the forest membership.  We only severed the forest tie.
        self.update()
        _log(
            f"_leave_forest_keep_ring: {self._id[:8]} left forest "
            f"(was master of {len(self._members)} member(s))"
        )

    def _on_shake_detected(self) -> None:
        """Shake gesture handler: fully unassociate this hex from its master's group.

        Bug 4 — shake-to-unassociate.  Called from mouseMoveEvent when the
        _ShakeDetector triggers.  This is a FULL unassociation (removes from
        master._members, clears _group_master_id) — stronger than break-free,
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
            return  # already unassociated — no-op

        master = registry.get(mid)
        # v0.8.0 — per user spec: "shake only removes them from a
        # ring."  If the cell is already linked directly to the
        # forest, shake is a no-op (use drag-away to undock from
        # forest cluster instead).
        if master is not None and getattr(master, "_is_forest_master", False):
            _log(
                f"shake on {self._id[:8]} — already forest-linked, "
                f"shake is a no-op (drag-away to undock from forest)"
            )
            return

        if master is not None:
            master._members.pop(self._id, None)
            master._positioned.discard(self._id)
            master._dock_partners.discard(self._id)
            # Member removed — ring is dirty (membership changed).
            master._ring_dirty = True

        old_master_short = mid[:8]
        # v0.8.0 — per user spec: "Cells will always be linked with
        # the forest or ring."  When shaken out of a ring, the cell
        # re-links to the forest (NOT to None).  Find the forest
        # via the registry — the ring's link parent is the forest.
        forest_id: "str | None" = None
        if master is not None:
            forest_id = getattr(master, "_link_parent_id", None) or getattr(
                master, "_group_master_id", None,
            )
        # Fallback: find the forest cell in the registry by flag.
        if forest_id is None:
            for c in registry.all():
                if getattr(c, "_is_forest_master", False):
                    forest_id = c._id
                    break
        self._group_master_id = forest_id
        self._link_parent_id = forest_id  # v0.8.0 P1 mirror
        # Also wire the cell into the forest's _members so the forest
        # cascade can find it via legacy paths.
        if forest_id is not None:
            forest = registry.get(forest_id)
            if forest is not None:
                forest._members[self._id] = QPoint(self.pos())
                # Do NOT add to forest._positioned — the cell is now
                # loose forest-linked (no dock path), so it stays
                # put when the forest is dragged.
        self._docked_to.clear()
        self._dock_partners.clear()
        # Clear dock fields — cell is now floating relative to the
        # forest, no longer docked to its former ring.
        self._slot = None
        if self._dock_partner_id is not None and self._dock_edge is not None:
            partner = registry.get(self._dock_partner_id)
            if partner is not None:
                partner._dock_children_by_edge.pop(self._dock_edge, None)
        self._dock_partner_id = None
        self._dock_edge = None

        _log(
            f"shake detected — {self._id[:8]} unlinked from ring "
            f"{old_master_short}, re-linked to forest "
            f"{forest_id and forest_id[:8]}"
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
        """Break-free drag path: cell leaves the POSITIONAL CLUSTER
        but retains link-group membership.

        Called at the 4 px drag threshold in mouseMoveEvent for any
        NON-forest cell that is docked or grouped — the actual trigger is
        ``not is_forest and (self._docked_to or self._group_master_id is
        not None)``, i.e. standalone cells AND ring masters (never the
        forest root).

        Steps:
        1. Remove self from every _docked_to peer's _docked_to set.
        2. Remove self from master._positioned (if in a group).
        3. Update master._members[self._id] to the current position so
           collapse/expand knows where this member last was.
        4. Clear self._docked_to.
        5. v0.8.0 — clear ``_slot``, ``_dock_partner_id``,
           ``_dock_edge``.  Without this, the v0.6.38 cascade union
           loop in master.moveEvent picks up this cell via the
           "linked + has slot" rule, and the cell follows the master
           even though the user just dragged it off the cluster.
           Per the user's spec, forest-linked cells need only a drag
           to undock — no shake required.
        6. ``_link_parent_id`` / ``_group_master_id`` PRESERVED —
           still a group member.
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

        # v0.8.0 — clear slot + dock partner so the cascade union
        # loop ("linked + has slot" rule) skips this cell on the
        # next master drag.  The cell is now "loose forest-linked"
        # in the v0.8.0 sense.
        self._slot = None
        if self._dock_partner_id is not None and self._dock_edge is not None:
            partner = registry.get(self._dock_partner_id)
            if partner is not None:
                partner._dock_children_by_edge.pop(self._dock_edge, None)
        self._dock_partner_id = None
        self._dock_edge = None

        # v0.8.0a82 — also detach our dock-CHILDREN (cells docked to OUR
        # edges).  Without this, dragging a single cell OUT of the cluster
        # leaves ``self._dock_children_by_edge`` populated, so when the cell
        # re-docks the snap commit funnels through ``move_to``, whose Bug-4
        # cascade (~line 10291) shifts every dock-child by the snap delta —
        # the user-reported "moving one cell makes another docked cell shift
        # and become offset".  A user pulling a single cell out of the
        # cluster should move ONLY that cell; its former dock-children stay
        # put (they keep ``_group_master_id`` — still forest members — they
        # just lose the dock-chain link to the cell that was dragged away).
        # Mirrors the master-disband child-release at ~line 9075.
        #
        # FUTURE (user note, a82): tree RING masters may later be EXEMPTED
        # here so a ring travels with all its docked components as one unit
        # — e.g. gate this block on ``self.role != "master"``.  Left
        # unconditional for now per "get it working the way you propose
        # first".
        for _edge, _child_id in list(self._dock_children_by_edge.items()):
            _child = registry.get(_child_id)
            if _child is not None and _child._dock_partner_id == self._id:
                _child._dock_partner_id = None
                _child._dock_edge = None
        self._dock_children_by_edge.clear()

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
            f"(group_master={mid and mid[:8]} preserved, "
            f"slot+dock cleared)"
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
        try:
            new_hex._fade_in()
        except Exception:  # noqa: BLE001
            pass
        try:
            new_hex._settle_no_overlap()
        except Exception as exc:  # noqa: BLE001
            _log(f"_settle_no_overlap (_spawn_another) raised {exc!r}")
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

        Group semantics (corrected v0.2.11): closing a *member* removes
        it from the master's ``_members`` and runs
        ``_check_master_validity`` — the master only goes away when
        fewer than 2 members remain.  The previous behaviour (close
        the master if this cell was its ``source_a_id`` /
        ``source_b_id``) was wrong: those fields record the
        *originating* pair, not the current cluster, so closing the
        first cell ever docked into a 4-cell ring tore the whole
        master down even though three live members remained.
        """
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()

        # ── Member case — leave group cleanly ────────────────────────
        # If this cell is a member of a master, take it out of the
        # master's _members + _positioned + _dock_partners so the
        # master can decide for itself whether to close (it does so
        # only when fewer than 2 members are left, via
        # _check_master_validity).
        if self.role != "master" and self._group_master_id is not None:
            master = registry.get(self._group_master_id)
            if master is not None and master.role == "master":
                master._members.pop(self._id, None)
                master._positioned.discard(self._id)
                master._dock_partners.discard(self._id)
                master._auto_hidden.discard(self._id)
                # Member removed — ring is dirty (membership changed).
                master._ring_dirty = True
                # V3 v0.3.17 — DO NOT repack survivors.  Per user
                # contract, "moving one element does not cause a
                # reshift in the others" extends to closures: the
                # closed cell leaves a gap, and the rest of the
                # group stays exactly where the user placed them.
                # The user can manually drag a survivor into the
                # gap if they want to fill it.
                _check_master_validity(master, registry)

        # ── Master case — closing the master itself ──────────────────
        # Falling through to self.close() below is fine: the master's
        # closeEvent (if any) handles member cleanup.  We do NOT
        # cascade-close based on source_a_id / source_b_id any more.
        if self.role == "master":
            # Same save-prompt rule as _close_ring_undock_all /
            # _close_all_related — masters with unsaved membership
            # changes get a Save / Discard / Cancel dialog before
            # vanishing.  Non-master cells skip the prompt entirely
            # (already short-circuited above by ``role != "master"``).
            if self._ring_needs_save_prompt():
                if not self._confirm_discard_unsaved_ring():
                    _log(
                        f"_close_this: cancelled by user "
                        f"(unsaved master ring {self._id[:8]})"
                    )
                    return
            registry.masterDespawned.emit(self._id)

        # v0.8.0a106 — quitting on the last close is now handled uniformly in
        # ``closeEvent`` → ``_quit_if_app_empty`` (fires for the [X] button too,
        # and correctly covers closing the last MASTER).  This replaces the old
        # standalones-only ``is_last`` check, which both (a) MISSED a last master
        # (closing the forest hub left the process running headless) and (b)
        # PREMATURELY quit when the last standalone closed while a master hub was
        # still open.  Just close; ``closeEvent`` decides whether to quit.
        self.close()

    # ------------------------------------------------------------------
    # Role-aware close + exit handlers (right-click menu)
    # ------------------------------------------------------------------

    def _ring_needs_save_prompt(self) -> bool:
        """True iff closing this master should ask the user to save first.

        Trigger conditions:

        * **Never saved** (``_saved_ring_path is None``) — no on-disk
          file exists yet.
        * **Membership changed** since last save (``_ring_dirty``) —
          a cell was added or removed.
        * **G7 (v0.3.8+):** the previously-saved file no longer
          exists on disk — treat as "needs prompt" so the user can
          re-save (or pick Discard with full awareness that the
          saved-path-they-trusted is gone).

        Returns False for:

        * Non-masters (a standalone cell carries no ring file).
        * Empty masters (mid-teardown from quorum loss — F3's
          separate prompt path handles that).
        * **The forest master** (v0.8.0a1+ramps Bug 11) — the
          forest is the workspace singleton; it isn't persisted to
          a ``.scriptreering`` file (the autoload config tracks the
          cluster instead).  Without this skip, exit-all / close-all
          on the forest fired one prompt for the forest itself and
          a second prompt for an unsaved ring member, both reading
          identically ("This ring has not been saved yet") — user
          reported as "asks me to save the unsaved ring twice
          instead of just once."
        """
        from pathlib import Path
        if self.role != "master":
            return False
        if getattr(self, "_is_forest_master", False):
            return False
        if not self._members:
            return False
        saved_path = getattr(self, "_saved_ring_path", None)
        if saved_path is None:
            return True
        if not Path(saved_path).is_file():
            # G7 — saved file vanished off disk.
            return True
        return self._ring_dirty

    def _confirm_discard_unsaved_ring(self) -> bool:
        """Show a Save / Discard / Cancel dialog for an unsaved ring.

        Returns True if the caller may proceed with closing the ring
        (user picked Save and save succeeded, or picked Discard).
        Returns False if the caller must abort (user picked Cancel
        or save failed).

        Caller is responsible for first checking
        ``_ring_needs_save_prompt`` — this method always shows the
        dialog when invoked.
        """
        path = getattr(self, "_saved_ring_path", None)
        if path is None:
            text = (
                "This ring has not been saved yet.\n\n"
                "Save it before closing?"
            )
        else:
            # ``_saved_ring_path`` may be a Path or a plain str
            # (legacy code paths set strings).  Normalise to a Path
            # before reading .name so we don't AttributeError on str.
            from pathlib import Path as _Path
            try:
                short = _Path(path).name
            except (TypeError, ValueError):
                short = str(path)
            text = (
                f"This ring has unsaved changes since it was last "
                f"saved to '{short}'.\n\n"
                "Save the changes before closing?"
            )

        reply = QMessageBox.question(
            None,
            "Unsaved ring",
            text,
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return False
        if reply == QMessageBox.StandardButton.Discard:
            return True
        # Save chosen — delegate to the standard save flow.  If the
        # ring already has a path, this just writes; if not, the
        # save-as dialog runs and the user can still cancel it.
        self._save_ring_dialog()
        # If save succeeded, _write_ring_to_path cleared _ring_dirty
        # AND set _saved_ring_path.  If the user cancelled save-as,
        # _saved_ring_path stays None and we abort the close.
        if self._ring_needs_save_prompt():
            return False
        return True

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
        if self._ring_needs_save_prompt():
            if not self._confirm_discard_unsaved_ring():
                _log(
                    f"_close_ring_undock_all: cancelled by user "
                    f"(unsaved ring {self._id[:8]})"
                )
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
            member._link_parent_id = None  # v0.8.0 P1 mirror
            member._docked_to.discard(self._id)
        registry.masterDespawned.emit(self._id)
        _log(
            f"Closed ring {self._id[:8]} — {len(member_ids)} member(s) "
            f"reverted to standalone"
        )
        self.close()

    def _close_ring_via_shake_with_prompt(self) -> None:
        """v0.8.0a1+ramps Bug 5 — shake-on-ring close path.

        Per user: "shake to close and have a box come up then to
        close, save or cancel."  Replaces the v0.6.x auto-close-on-
        quorum-loss path (now disabled per v0.8.0 spec) with an
        explicit user-confirmed disposal gesture.

        Behaviour:
        * Forest master → no-op (the forest is the workspace root).
        * Non-master cell → no-op (shake-to-disassociate handled
          elsewhere; this method is only meaningful for rings).
        * Ring master → always prompt with Save / Close / Cancel.
            - Cancel → no change.
            - Save   → write file (save-as if no path); if save was
              cancelled or failed, abort the close.
            - Close  → disband immediately, members re-link to the
              forest per the v0.8.0 spec ("Cells will always be
              linked with the forest or ring").
        """
        if self.role != "master":
            _log(
                f"_close_ring_via_shake_with_prompt on non-master "
                f"{self._id[:8]} — ignored"
            )
            return
        if getattr(self, "_is_forest_master", False):
            _log(
                f"_close_ring_via_shake_with_prompt on FOREST "
                f"{self._id[:8]} — forest never closes by shake"
            )
            return

        # Build prompt text — distinguish dirty/clean for context.
        needs_save = self._ring_needs_save_prompt()
        if needs_save:
            path = getattr(self, "_saved_ring_path", None)
            if path is None:
                text = (
                    "Close this ring?\n\n"
                    "It has not been saved yet."
                )
            else:
                from pathlib import Path as _Path
                try:
                    short = _Path(path).name
                except (TypeError, ValueError):
                    short = str(path)
                text = (
                    f"Close this ring?\n\n"
                    f"It has unsaved changes since '{short}'."
                )
        else:
            text = (
                "Close this ring?\n\n"
                "Members will re-link to the forest."
            )

        reply = QMessageBox.question(
            None,
            "Close ring",
            text,
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )

        if reply == QMessageBox.StandardButton.Cancel:
            _log(
                f"shake-close ring {self._id[:8]} — cancelled by user"
            )
            return

        if reply == QMessageBox.StandardButton.Save:
            self._save_ring_dialog()
            # If the user cancelled the save-as dialog or save
            # otherwise failed, the ring is still dirty / unsaved —
            # abort the close instead of silently discarding data.
            if self._ring_needs_save_prompt():
                _log(
                    f"shake-close ring {self._id[:8]} — save failed/"
                    f"cancelled; close aborted"
                )
                return

        # Save succeeded OR user picked Discard → disband.
        self._disband_ring_relinking_members_to_forest()

    def _disband_ring_relinking_members_to_forest(self) -> None:
        """Tear down this ring and re-link its members to the forest.

        Mirrors ``_close_ring_undock_all`` but follows the v0.8.0
        spec where cells are ALWAYS linked to either a ring or the
        forest (never unlinked).  Called from the shake-to-close
        path after the user has already confirmed at the prompt —
        do NOT re-prompt here.
        """
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()

        # Find the forest (link parent of this ring, or any cell
        # flagged ``_is_forest_master`` in the registry).
        forest_id: "str | None" = getattr(
            self, "_link_parent_id", None,
        ) or getattr(self, "_group_master_id", None)
        if forest_id is None:
            for c in registry.all():
                if getattr(c, "_is_forest_master", False):
                    forest_id = c._id
                    break
        forest = registry.get(forest_id) if forest_id else None

        member_ids = list((self._members or {}).keys())
        for mid in member_ids:
            member = registry.get(mid)
            if member is None:
                continue
            # Re-link to forest (or None if no forest exists).
            member._group_master_id = forest_id
            member._link_parent_id = forest_id  # v0.8.0 P1 mirror
            member._docked_to.discard(self._id)
            # Clear dock relationship to the disbanded master.
            if member._dock_partner_id == self._id:
                member._dock_partner_id = None
                member._dock_edge = None
            # Wire into forest._members (NOT _positioned — they're
            # now loose forest-linked, no dock path).
            if forest is not None:
                forest._members[member._id] = QPoint(member.pos())

        registry.masterDespawned.emit(self._id)
        _log(
            f"shake-close ring {self._id[:8]} — disbanded "
            f"({len(member_ids)} member(s) re-linked to forest "
            f"{forest_id and forest_id[:8]})"
        )
        self.close()

    def _close_all_related(self) -> None:
        """Master-cell action: close the master AND all its member cells.

        Use case: "I'm done with this whole group of tools — make it
        all go away."  After this, only cells that weren't members of
        the ring remain.  If the entire desktop becomes empty, quit.

        v0.8.0a1+ramps Bug 11 — pre-walk every master member and
        prompt for its unsaved ring before touching anything.  Under
        v0.8.0 the forest contains rings as members; the forest
        itself never prompts (it's not persisted) but each unsaved
        ring inside it must.  Cancel on any prompt aborts the whole
        close so the user can keep working.
        """
        from scriptree.shell.cell_registry import CellRegistry
        if self.role != "master":
            _log("_close_all_related on non-master — falling back to _close_this")
            self._close_this()
            return
        # Self prompt (forest skips per the Bug 11 forest guard in
        # _ring_needs_save_prompt).
        if self._ring_needs_save_prompt():
            if not self._confirm_discard_unsaved_ring():
                _log(
                    f"_close_all_related: cancelled by user "
                    f"(unsaved ring {self._id[:8]})"
                )
                return
        registry = CellRegistry.instance()
        member_ids = list((self._members or {}).keys())
        # Pre-walk: prompt for any unsaved ring member (Bug 11).  Done
        # BEFORE any actual close so the user can cancel without
        # losing partial state.
        for mid in member_ids:
            member = registry.get(mid)
            if member is None:
                continue
            if member.role != "master":
                continue
            if not member._ring_needs_save_prompt():
                continue
            if not member._confirm_discard_unsaved_ring():
                _log(
                    f"_close_all_related: cancelled by user during "
                    f"pre-walk for member ring {member._id[:8]}"
                )
                return
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

        F1 (v0.3.8+): before closing anything, walk every master
        in the registry and prompt for any that's dirty / unsaved.
        Cancel on any prompt aborts the whole exit so the user
        can keep working without losing data.  Save / Discard
        proceed individually; only after every master has been
        resolved do we tear down.
        """
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()

        # F1 — gather and resolve dirty masters first.
        masters = list(registry.masters())
        for m in masters:
            if not m._ring_needs_save_prompt():
                continue
            if not m._confirm_discard_unsaved_ring():
                # User picked Cancel — abort the whole exit.
                _log(
                    f"Exit all: cancelled by user during "
                    f"unsaved-ring prompt for master {m._id[:8]}"
                )
                return

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

    def _try_join_forest_near_member(self) -> None:
        """v0.6.16 — at master drag-end, if this master is not yet
        linked anywhere AND it released within docking distance of
        a cell that's linked to the forest, promote *this master*
        to a forest member (``link=Forest, dock=Forest``).

        This is the directional inverse of
        ``_try_absorb_nearby_free_cells``: when the user drags a
        ring *to* a forest member, the ring should join the forest
        as a sibling — NOT pull the forest member into itself.

        Implementation: just add the master to ``forest._members +
        _positioned`` and call ``forest._repack_members(fixed=
        existing)``.  The forest's repack places the new member on
        its closest free first-ring slot, which by closest-slot
        semantics will be adjacent to the cell the user dragged
        toward.  No need for explicit "dock to that cell" wiring —
        the layout authority is the forest's honeycomb.
        """
        if self.role != "master":
            return
        if getattr(self, "_is_forest_master", False):
            return
        # Already linked somewhere?  No double-link.
        if self._group_master_id is not None:
            return

        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()

        # Find the forest hub (singleton).
        forest = None
        for m in registry.masters():
            if getattr(m, "_is_forest_master", False):
                forest = m
                break
        if forest is None:
            return  # No forest in this session; nothing to join.

        # Look for any forest-linked cell within docking distance of
        # the master.  The forest-linked cell can be a standalone
        # OR another ring master (forest member).
        dock_radius = self._size_px * 1.6
        sz = self._size_px
        mcx = self.pos().x() + sz // 2
        mcy = self.pos().y() + sz // 2

        nearest_id: str | None = None
        nearest_dist: float = float("inf")
        for h in registry.all():
            if h._id == self._id or h._id == forest._id:
                continue
            if not h.isVisible():
                continue
            if h._group_master_id != forest._id:
                continue  # not a forest member
            csx = h.pos().x() + h._size_px // 2
            csy = h.pos().y() + h._size_px // 2
            dist = math.hypot(csx - mcx, csy - mcy)
            if dist <= dock_radius and dist < nearest_dist:
                nearest_id = h._id
                nearest_dist = dist
        if nearest_id is None:
            return  # not near any forest-linked cell — no-op

        # Promote: become a forest member.
        forest._members[self._id] = QPoint(self.pos())
        forest._positioned.add(self._id)
        forest._dock_partners.add(self._id)
        self._group_master_id = forest._id
        self._link_parent_id = forest._id  # v0.8.0 P1 mirror
        forest._ring_dirty = True
        forest.update()
        # Repack the forest so the new member lands on a real
        # honeycomb slot adjacent to where it was dropped.  The
        # closest-free-slot semantics naturally satisfy the user's
        # "docks to cell; falls back to another forest-linked cell
        # if no space" requirement.
        try:
            existing = {mid for mid in forest._members if mid != self._id}
            forest._repack_members(fixed=existing)
        except Exception as exc:  # noqa: BLE001
            _log(f"_try_join_forest_near_member: repack failed: {exc!r}")
        _log(
            f"_try_join_forest_near_member: master {self._id[:8]} "
            f"joined forest near cell {nearest_id[:8]}"
        )
        self.update()

    def _try_absorb_nearby_free_cells(self) -> None:
        """v0.6.14 — at the end of a master drag, absorb any free
        standalone cell whose centre lies within ``absorb_radius``
        of the master's centre.

        "Free" means: visible, role=="standalone", and either
        unaffiliated (``_group_master_id`` is None) OR linked only
        to the forest hub (a break-free forest member).  Cells
        that belong to another ring are NOT poached.

        Forest-link semantics:
          * If any absorbed cell was forest-linked AND this master
            isn't itself a forest member, the master inherits the
            forest link.  This is the symmetric counterpart of the
            "two forest-linked cells form a forest-linked ring"
            rule in ``_try_spawn_master``.
          * The forest itself is never absorbed (it's a master).
        """
        if self.role != "master":
            return
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()

        # Honeycomb neighbour distance ≈ size_px; add slack so the
        # user doesn't have to land perfectly on a slot.
        absorb_radius = self._size_px * 1.6
        sz = self._size_px
        mcx = self.pos().x() + sz // 2
        mcy = self.pos().y() + sz // 2

        absorbed: list[CellWindow] = []
        forest_link_to_inherit: str | None = None
        for c in list(registry.standalones()):
            if c._id == self._id:
                continue
            if c._id in self._members:
                continue
            if not c.isVisible():
                continue
            # Already in another ring?  Don't poach.  Forest is
            # special: a cell linked ONLY to the forest hub is
            # "free" in the sense that it's not committed to a
            # member ring.
            gm = c._group_master_id
            if gm is not None and gm != self._id:
                # v0.6.16 — sibling guard: if `c` shares THIS
                # master's link parent (we're peers under the
                # same forest hub), do not absorb.  This lets a
                # master that just became a forest member (via
                # ``_try_join_forest_near_member``) sit beside
                # its peer forest cells without pulling them in.
                if (
                    self._group_master_id is not None
                    and gm == self._group_master_id
                ):
                    continue
                gm_cell = registry.get(gm)
                if gm_cell is not None and not getattr(
                    gm_cell, "_is_forest_master", False,
                ):
                    continue  # member of a real ring; leave alone
            # Distance check.
            csx = c.pos().x() + c._size_px // 2
            csy = c.pos().y() + c._size_px // 2
            dist = math.hypot(csx - mcx, csy - mcy)
            if dist > absorb_radius:
                continue
            absorbed.append(c)
            if gm is not None:
                gm_cell = registry.get(gm)
                if gm_cell is not None and getattr(
                    gm_cell, "_is_forest_master", False,
                ):
                    forest_link_to_inherit = gm

        if not absorbed:
            return

        # Wire each absorbed cell as a ring member.
        for c in absorbed:
            # Detach from prior group (if any) — only forest-linked
            # cells reach here, but stay defensive.
            prior_id = c._group_master_id
            if prior_id is not None and prior_id != self._id:
                prior_master = registry.get(prior_id)
                if prior_master is not None:
                    prior_master._members.pop(c._id, None)
                    prior_master._positioned.discard(c._id)
                    prior_master._dock_partners.discard(c._id)
                    if getattr(prior_master, "_is_forest_master", False):
                        prior_master._ring_dirty = True
                        prior_master.update()
            self._members[c._id] = QPoint(c.pos())
            self._positioned.add(c._id)
            self._dock_partners.add(c._id)
            c._group_master_id = self._id
            c._link_parent_id = self._id  # v0.8.0 P1 mirror
            c._docked_to.discard(prior_id) if prior_id else None
            c.update()  # outline refresh

        # Inherit forest link if applicable.
        if (
            forest_link_to_inherit is not None
            and not getattr(self, "_is_forest_master", False)
            and self._group_master_id != forest_link_to_inherit
        ):
            forest = registry.get(forest_link_to_inherit)
            if forest is not None and self._id not in forest._members:
                forest._members[self._id] = QPoint(self.pos())
                forest._positioned.add(self._id)
                forest._dock_partners.add(self._id)
                self._group_master_id = forest_link_to_inherit
                self._link_parent_id = forest_link_to_inherit  # v0.8.0 P1 mirror
                forest._ring_dirty = True
                forest.update()

        # Re-pack so absorbed cells land on real honeycomb slots
        # around the master rather than wherever they happened to
        # be on release.  Existing members keep their positions.
        try:
            existing_ids = {
                m for m in self._members.keys()
                if m not in {c._id for c in absorbed}
            }
            self._repack_members(fixed=existing_ids)
        except Exception as exc:  # noqa: BLE001
            _log(f"_try_absorb: repack failed: {exc!r}")
        self._ring_dirty = True
        self.update()
        _log(
            f"_try_absorb_nearby_free_cells: master {self._id[:8]} "
            f"absorbed {len(absorbed)} free cell(s); forest-link "
            f"inherited: {bool(forest_link_to_inherit)}"
        )

    def _resolve_member_stacking(self) -> None:
        """v0.6.12 — surgical-repack any of *this master's* members
        whose centres land on (or very near) a peer's centre.

        Mirror of ``ForestController._resolve_member_overlap`` but
        on the CellWindow so plain ring-masters benefit too (load_ring
        calls it after spawning members, the forest controller now
        delegates to it).  Centre-distance test (< size_px / 2)
        avoids flagging legitimate honeycomb-adjacent peers — only
        catches the "stacked on the same pixel" case from stale
        saved positions.
        """
        if self.role != "master" or not self._members:
            return
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()

        centres: list[tuple[str, int, int, int]] = []  # id, cx, cy, sz
        for mid in self._members.keys():
            m = registry.get(mid)
            if m is None:
                continue
            sz = m._size_px
            centres.append((
                mid,
                m.pos().x() + sz // 2,
                m.pos().y() + sz // 2,
                sz,
            ))
        if len(centres) < 2:
            return

        colliders: set[str] = set()
        for i, (id_a, cx_a, cy_a, sz_a) in enumerate(centres):
            for id_b, cx_b, cy_b, sz_b in centres[i + 1:]:
                threshold = min(sz_a, sz_b) * 0.5
                if (
                    abs(cx_a - cx_b) < threshold
                    and abs(cy_a - cy_b) < threshold
                ):
                    colliders.add(id_a)
                    colliders.add(id_b)
        if not colliders:
            return

        non_colliding = {
            mid for mid in self._members.keys() if mid not in colliders
        }
        _log(
            f"_resolve_member_stacking ({self._id[:8]}): "
            f"{len(colliders)} of {len(self._members)} member(s) stack; "
            f"surgical repack"
        )
        try:
            self._repack_members(fixed=non_colliding)
        except Exception as exc:  # noqa: BLE001
            _log(f"_resolve_member_stacking: repack failed: {exc!r}")

    def _capture_remembered_offset(self) -> None:
        """Record where the USER just dropped THIS cell, as an offset from its
        forest hub, into the hub's ``_remembered_offsets`` (v0.8.0a83).

        Called only from ``mouseReleaseEvent`` at a real drag-end (the caller
        gates on ``was_dragging``) — never from a system relocation — so the
        remembered layout captures user intent, not a transient reflow/settle.

        No-op unless this cell is a forest-cluster member: its
        ``_group_master_id`` resolves to an ``_is_forest_master`` hub and it
        carries a catalog path (the stable key).  The forest hub itself is
        skipped — its members' offsets are hub-relative and are preserved by
        the drag cascade, so moving the hub needs no re-capture.  Nested
        ring-members (whose master is a ring, not the forest) are likewise
        skipped — they belong to the ring's own ``.scriptreering`` layout.

        Triggers the forest controller's debounced autosave so the new offset
        persists to the ``.scriptreeforest`` (a pure member rearrange does not
        otherwise mark the forest dirty — only a hub move does).
        """
        if getattr(self, "_is_forest_master", False):
            return
        mid = getattr(self, "_group_master_id", None)
        if mid is None:
            return
        from scriptree.shell.cell_registry import CellRegistry

        hub = CellRegistry.instance().get(mid)
        if hub is None or not getattr(hub, "_is_forest_master", False):
            return
        key = _member_offset_key(self)
        if key is None:
            return
        # v0.8.0a113 [reloc FIX] -- capture the SETTLED resting position, not a
        # mid-flight one.  ``mouseReleaseEvent`` runs ``_settle_no_overlap()``
        # BEFORE this capture, and settle relocates an overlapping / edge-
        # straddling drop via ``_smooth_move`` -> an ASYNC ``QPropertyAnimation``
        # whose target ``self.pos()`` isn't reached until LATER event-loop
        # turns.  Reading ``self.pos()`` here would therefore store the
        # PRE-settle (stale) offset; on the next bloom that stale spot fails the
        # on-screen fit-test in ``_restore_remembered_offsets`` and the cell is
        # dropped from ``placed`` -> the engine re-tiles it to a DIFFERENT
        # honeycomb slot.  That is the intermittent "a stacked cell relocates
        # even though its space is still free" bug (root-caused in a113): it
        # only fires when the drop tripped settle's overlap/edge spiral, which
        # is exactly why it was intermittent.  Fix: read the in-flight
        # animation's ``endValue`` (the settled destination) instead of the
        # live position -- for the member AND the hub (a master drag can leave
        # the hub itself animating).
        def _resting_xy(widget: "CellWindow") -> tuple[int, int]:
            anim = getattr(widget, "_pos_anim", None)
            if anim is not None:
                try:
                    end = anim.endValue()
                    if end is not None:
                        return end.x(), end.y()
                except Exception:  # noqa: BLE001
                    pass
            return widget.pos().x(), widget.pos().y()

        sx, sy = _resting_xy(self)
        hx, hy = _resting_xy(hub)
        dx = sx - hx
        dy = sy - hy
        hub._remembered_offsets[key] = (dx, dy)
        _log(f"remembered offset {self._id[:8]} -> ({dx},{dy})")
        # Persist: nudge the forest controller's debounced autosave (250 ms).
        try:
            from scriptree.shell import ring_main as _rm
            ctrl = getattr(_rm, "_FOREST_CONTROLLER", None)
            if ctrl is not None:
                ctrl.forestChanged.emit()
        except Exception:  # noqa: BLE001
            pass

    def _restore_remembered_offsets(self, *, move: bool) -> set[str]:
        """Place this hub's members at their REMEMBERED offset
        (``_remembered_offsets``) when that spot is fully visible across ALL
        monitors.  Returns the set of placed member ids — the caller passes
        them as ``_compute_layout(pinned=...)`` so the engine tiles the
        remainder AROUND them (v0.8.0a83).

        This is the "keep the user's arrangement unless there's no room" half
        of the remembered-layout feature:

        * A member whose ``hub.pos() + remembered_offset`` is WHOLLY on-screen
          (``_visible_area_on_any_screen`` — union of all monitors) is
          restored to that spot.
        * A member with no remembered offset, or an off-screen target, is LEFT
          for the layout engine; its offset is RETAINED so it returns once
          screen space allows.

        ``move=True`` moves the widget there now (load / screen-rescue, where
        there is no bloom animation).  ``move=False`` only writes the target
        into ``_members[mid]`` (and un-folds it) — used by ``_start_expand``,
        whose bloom animation then animates each member from the hub centre to
        that target.  Floating members own their own position and are skipped.
        Master-only; a no-op when there are no remembered offsets.
        """
        if (
            self.role != "master"
            or not self._remembered_offsets
            or not self._members
        ):
            return set()
        from scriptree.shell.cell_registry import CellRegistry

        registry = CellRegistry.instance()
        hub_x, hub_y = self.pos().x(), self.pos().y()
        placed: set[str] = set()
        # v0.8.0a113 [reloc-diag] -- record WHY each member was NOT restored so
        # the intermittent "a bloomed cell relocated even though its spot was
        # free" bug is observable in the debug log.  Reasons: floating /
        # no-key / no-offset / off-screen.  Logged once per bloom as a summary.
        skips: list[str] = []
        for mid in list(self._members.keys()):
            m = registry.get(mid)
            if m is None:
                skips.append(f"{mid[:8]}=gone")
                continue
            if getattr(m, "_floating_intent", False):
                skips.append(f"{m._id[:8]}=floating")
                continue  # owns its own position
            key = _member_offset_key(m)
            if key is None:
                skips.append(f"{m._id[:8]}=no-key(path={getattr(m, '_catalog_path', None)!r})")
                continue
            off = self._remembered_offsets.get(key)
            if off is None:
                skips.append(f"{m._id[:8]}=no-offset(key={key[-40:]})")
                continue
            tx, ty = hub_x + int(off[0]), hub_y + int(off[1])
            sz = m._size_px
            # Fully on-screen across ALL monitors?  Else leave for the engine
            # (offset kept, so the cell returns to its spot when space allows).
            vis = self._visible_area_on_any_screen(QRect(tx, ty, sz, sz))
            if vis < sz * sz:
                skips.append(
                    f"{m._id[:8]}=offscreen(target=({tx},{ty}) "
                    f"vis={vis}/{sz * sz})"
                )
                continue
            self._members[mid] = QPoint(tx, ty)
            self._auto_hidden.discard(mid)
            if move:
                prior = getattr(m, "_pos_anim", None)
                if prior is not None:
                    try:
                        prior.stop()
                    except Exception:  # noqa: BLE001
                        pass
                    m._pos_anim = None
                m.move(tx, ty)
                m.setVisible(True)
            placed.add(mid)
        if placed or skips:
            _log(
                f"_restore_remembered_offsets {self._id[:8]}: restored "
                f"{len(placed)}/{len(self._members)} member(s) (move={move})"
                + (f"  [reloc-diag] NOT restored: {', '.join(skips)}"
                   if skips else "")
            )
        return placed

    def _current_home_pins(
        self, members: list, already_placed: set[str]
    ) -> set[str]:  # noqa: ANN001
        """v0.8.0a113 [reloc FIX] -- return the member ids to PIN at their
        CURRENT ``_members[mid]`` home so a RE-BLOOM doesn't relocate them.

        ``_restore_remembered_offsets`` only pins members the user explicitly
        DRAGGED (those with a remembered offset).  Every other member would be
        handed to ``_compute_layout`` and re-tiled to a possibly-different
        honeycomb slot -- the user-reported "a cell relocated even though its
        space is still free" bug, whose true cause (confirmed by the
        ``[reloc-diag]`` log: ``NOT restored: <id>=no-offset``) is simply that
        the cell has no remembered offset because it was never dragged.

        A member is pinned here iff it isn't floating, isn't already pinned by a
        remembered offset, and its current home is WHOLLY on-screen.  Genuinely
        new or off-screen members are left for the engine (so a fresh cell still
        honeycomb-tiles, and an off-screen home is rescued on-screen).

        This is scoped to ``_start_expand``, which is ALWAYS a re-bloom of an
        already-laid-out cluster -- the initial startup layout tiles cells via
        ``_compute_layout`` directly and never routes through here, so every
        member reaching this point already has a valid pre-collapse home.
        """
        pins: set[str] = set()
        for m in members:
            mid = getattr(m, "_id", None)
            if mid is None or mid in already_placed:
                continue
            if getattr(m, "_floating_intent", False):
                continue
            home = self._members.get(mid)
            if home is None:
                continue
            sz = m._size_px
            if self._visible_area_on_any_screen(
                QRect(home.x(), home.y(), sz, sz)
            ) >= sz * sz:
                pins.add(mid)
        return pins

    def _visible_area_on_any_screen(self, rect: QRect) -> int:
        """Total visible area (px²) of ``rect`` across ALL monitors — 0 if
        ``rect`` is off every screen.

        Multi-display correctness helper (v0.8.0a80).  The single-screen
        ``screenAt(master.pos())`` test treated a cell visible on a second
        monitor as off-screen (zero overlap with the master's monitor) and
        relocated/auto-hid it; summing the overlap across every monitor
        means a member counts as on-screen when it is visible on ANY
        display.  Used by the live edge reflow and ``_check_edge_fold``.

        We SUM the per-screen intersection areas rather than taking the max.
        Extended-desktop screens are DISJOINT in virtual-desktop
        coordinates, so the sum is exactly the true visible (union) area —
        and a member straddling a monitor seam (e.g. ~45 % on each of two
        flush monitors) correctly scores ~90 % visible instead of 45 %.
        For the rare mirrored-display case the geometries coincide and the
        sum over-counts, but that only inflates the visibility score, so a
        clearly-visible member can never be misclassified as off-screen.
        With a single monitor the loop runs once and the result equals the
        old single-screen ``inter_area`` exactly (no behaviour change).
        """
        from PySide6.QtGui import QGuiApplication

        total = 0
        for s in QGuiApplication.screens():
            inter = rect.intersected(s.availableGeometry())
            if not inter.isEmpty():
                total += inter.width() * inter.height()
        return total

    def _live_edge_reflow_or_fold(self) -> None:
        """v0.6.11 — during a group drag, *relocate* off-screen members
        to free on-screen honeycomb slots so they stay bonded to the
        master and visible.  Falls back to the historical auto-hide
        only when no on-screen slot is available.

        Throttled to ~20 Hz so a per-pixel master move doesn't repack
        the ring on every frame.  Per-frame cost dominated by
        ``group_layout.repack``, which is cheap but not free.

        Standalone-cell stay-on-screen clamping is handled separately
        by ``_clamp_to_screen``.
        """
        import time as _time
        now = _time.monotonic()
        last = getattr(self, "_last_live_reflow_time", 0.0)
        if now - last < 0.05:
            return
        self._last_live_reflow_time = now

        if self.role != "master" or not self._positioned:
            return

        from scriptree.shell.cell_registry import CellRegistry
        from scriptree.shell.group_layout import (
            repack, screen_rect_for_master,
        )
        from PySide6.QtGui import QGuiApplication

        registry = CellRegistry.instance()
        app_inst = QGuiApplication.instance()
        if app_inst is None:
            return
        screen = app_inst.screenAt(self.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return  # no displays at all — nothing to classify against

        # v0.8.0a80 (multi-display "cells reposition when they don't have
        # to" fix) — classify a member off-screen ONLY when it is off
        # EVERY monitor, not just off the master's monitor.  The old code
        # tested intersection against ``screenAt(self.pos())`` alone, so on
        # a multi-monitor desktop a member genuinely visible on a SECOND
        # monitor (while the master is on the first, or vice versa) scored
        # zero intersection and was treated as off-screen — then relocated
        # onto the master's monitor, yanking a cell the user had placed and
        # could plainly see.  ``_visible_area_on_any_screen`` sums the
        # overlap across all screens (the true visible area), so only a
        # truly-invisible member (off every monitor) is relocated/folded.
        off_ids: list[str] = []
        on_ids: list[str] = []
        for mid in self._positioned:
            m = registry.get(mid)
            if m is None:
                continue
            sz = m._size_px
            rect = QRect(m.pos().x(), m.pos().y(), sz, sz)
            if self._visible_area_on_any_screen(rect) < (sz * sz) / 2:
                off_ids.append(mid)
            else:
                on_ids.append(mid)

        if not off_ids:
            # Everything that should be visible IS — un-fold any
            # members that came back on-screen (on ANY monitor).
            for mid in list(self._auto_hidden):
                m = registry.get(mid)
                if m is None:
                    continue
                sz = m._size_px
                rect = QRect(m.pos().x(), m.pos().y(), sz, sz)
                if self._visible_area_on_any_screen(rect) >= (sz * sz) / 2:
                    self._auto_hidden.discard(mid)
                    m.setVisible(True)
            return

        # Surgical repack: keep every on-screen member fixed, find
        # fresh slots for the off-screen ones.
        master_tl = (self.pos().x(), self.pos().y())
        screen_rect = screen_rect_for_master(master_tl, self._size_px)
        member_positions: dict[str, tuple[int, int]] = {}
        for mid in self._positioned:
            m = registry.get(mid)
            if m is None:
                continue
            member_positions[mid] = (m.pos().x(), m.pos().y())

        try:
            new_positions = repack(
                master_top_left=master_tl,
                size_px=self._size_px,
                shape=self._shape,
                orientation=self._orientation,
                members=member_positions,
                screen_rect=screen_rect,
                fixed=set(on_ids),
            )
        except Exception as exc:  # noqa: BLE001
            _log(f"_live_edge_reflow_or_fold: repack failed: {exc!r}")
            return

        # v0.8.0a80 (left-behind fix) — these relocations are a SYSTEM
        # move of off-screen members around the (stationary) master to
        # keep them on-screen.  Each ``m.move()`` below fires the
        # member's ``hexagonMoved`` -> ``ring_main._on_hexagon_moved``,
        # which runs ``_check_undock`` whenever NO group move is flagged.
        # A relocation can jump a member well past the ~92 px undock
        # threshold from its docked peer, so ``_check_undock`` would
        # silently drop it from ``_positioned`` — and the next master
        # drag (which only cascades ``_positioned`` members) would then
        # leave it behind.  This is the user-reported "cell got left
        # behind", traced live to ``ae463801`` stranded at (42,33) while
        # the rest of the cluster moved to the second monitor.
        #
        # The reflow is a coordinated, system-driven relocation — exactly
        # what ``_GROUP_MOVE_IN_PROGRESS`` exists to mark — so set it for
        # the duration of these moves.  ``_on_hexagon_moved`` then sees a
        # group move in progress and skips the drift undock (the relative
        # positions are managed by the engine, not drifting under a user
        # drag).  Mirrors the guard the rigid cascade uses in moveEvent.
        _GROUP_MOVE_IN_PROGRESS.add(self._id)
        try:
            for mid in off_ids:
                m = registry.get(mid)
                if m is None:
                    continue
                new_tl = new_positions.get(mid)
                if new_tl is None:
                    # No on-screen slot — fall back to the historical
                    # hide so the ring doesn't grow off-screen ghosts.
                    # The v0.6.32 sibling-redock branch was reverted in
                    # v0.6.34: it introduced re-link races during
                    # collapse / drag that made cells disappear.  See
                    # the next-session scene-graph refactor plan for
                    # the proper redock path.
                    if mid not in self._auto_hidden:
                        self._auto_hidden.add(mid)
                        m.setVisible(False)
                    continue
                new_x, new_y = new_tl
                if mid in self._auto_hidden:
                    self._auto_hidden.discard(mid)
                    m.setVisible(True)
                # Instant move — we're inside the drag event loop and an
                # eased animation would fight the next per-frame rigid
                # translation from master.moveEvent.  Kill any prior
                # in-flight pos animation first (defensive).
                prior = getattr(m, "_pos_anim", None)
                if prior is not None:
                    try:
                        prior.stop()
                    except Exception:  # noqa: BLE001
                        pass
                    m._pos_anim = None
                m.move(new_x, new_y)
        finally:
            _GROUP_MOVE_IN_PROGRESS.discard(self._id)

        self.update()  # repaint badge / outline

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
        by this method — edge-fold is a transient view state only.
        """
        if self.role != "master" or not self._positioned:
            return

        from scriptree.shell.cell_registry import CellRegistry
        from PySide6.QtGui import QGuiApplication

        registry = CellRegistry.instance()
        app_inst = QGuiApplication.instance()
        if app_inst is None:
            return

        # Guard: bail only when there is NO display at all (otherwise we'd
        # auto-hide every member).  Visibility itself is judged against ALL
        # monitors below, not just the master's screen.
        screen = app_inst.screenAt(self.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return

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

            # v0.8.0a80 multi-display: judge visibility across EVERY monitor
            # (see _visible_area_on_any_screen), so a member visible on a
            # second monitor isn't auto-hidden just because it's off the
            # master's monitor — the single-screen test was the auto-hide
            # twin of the live-reflow misclassification.
            member_area = sz * sz
            inter_area = self._visible_area_on_any_screen(member_rect)

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

    def _nearest_screen(self, point: QPoint):
        """Return the ``QScreen`` whose ``availableGeometry`` is nearest to
        ``point`` (a point inside a screen scores distance 0), or ``None``
        if there are no screens.

        Used by :meth:`_clamp_to_screen` when ``point`` lies outside every
        screen so the cell clamps to the CLOSEST monitor rather than being
        yanked to the primary (the v0.8.0a80 multi-monitor jitter fix).
        Distance is the squared Euclidean distance from the point to the
        rect (0 when contained), which is monotonic and avoids a sqrt.
        """
        from PySide6.QtGui import QGuiApplication

        screens = QGuiApplication.screens()
        if not screens:
            return None
        px, py = point.x(), point.y()
        best = None
        best_d: int | None = None
        for s in screens:
            r = s.availableGeometry()
            # Clamp the point into the rect on each axis; the leftover is
            # the axis distance (0 when the point is inside on that axis).
            dx = max(r.left() - px, 0, px - r.right())
            dy = max(r.top() - py, 0, py - r.bottom())
            d = dx * dx + dy * dy
            if best_d is None or d < best_d:
                best_d = d
                best = s
        return best

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
        2. If none (raw_pos lies outside EVERY screen — e.g. the cursor
           drifted just above the top edge of a secondary monitor during a
           drag), DON'T blindly fall back to the primary screen.  Prefer the
           screen the cell is CURRENTLY on, then the screen nearest to
           raw_pos, and only then the primary.  (v0.8.0a80 multi-monitor
           fix — see below.)
        3. Clamp the window top-left so the window stays inside that screen's
           availableGeometry (accounts for taskbar and tray area).
        4. If no screen is found at all (no displays), return raw_pos unchanged
           so we do not silently freeze dragging.

        v0.8.0a80 — multi-monitor jitter fix.  The old step 2 fell back to
        ``primaryScreen()`` whenever ``screenAt(raw_pos)`` was None.  On a
        multi-monitor desktop, dragging the forest near the TOP edge of a
        secondary monitor puts the cursor at a slightly-negative y that is
        above every screen, so ``screenAt`` returned None and the cell was
        yanked all the way to the PRIMARY monitor's edge — then, when the
        cursor dropped back onto the secondary, it jumped back.  The forest
        oscillated between the primary edge and the secondary (the live
        trace showed it snapping between x=3383 and x~6712), dragging its
        whole cluster back and forth ("cells reposition when they don't
        have to").  Keeping the cell on its CURRENT monitor when raw_pos is
        off every screen eliminates the teleport.
        """
        from PySide6.QtGui import QGuiApplication

        app_inst = QGuiApplication.instance()
        screen = None
        if app_inst is not None:
            try:
                screen = app_inst.screenAt(raw_pos)
            except Exception as _e:
                _log(f"_clamp_to_screen: screenAt raised {_e!r} — falling back to current/nearest screen")

        if screen is None and app_inst is not None:
            # raw_pos is outside every screen.  Prefer the monitor the cell
            # is currently on (by top-left, then by centre), then the
            # nearest monitor — anything but a blind jump to the primary.
            try:
                screen = app_inst.screenAt(self.pos())
                if screen is None:
                    centre = QPoint(
                        self.pos().x() + self._size_px // 2,
                        self.pos().y() + self._size_px // 2,
                    )
                    screen = app_inst.screenAt(centre)
            except Exception:  # noqa: BLE001
                screen = None
            if screen is None:
                screen = self._nearest_screen(raw_pos)

        if screen is None:
            screen = QGuiApplication.primaryScreen() if app_inst is not None else None

        if screen is None:
            return raw_pos  # no display info — pass through unclamped

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
    # v0.6.12 — universal "never overlap, never off-screen" invariant.
    #
    # Per user spec: "cells/rings/forest should never overlap except
    # (obviously) when collapsed."  Called from every settle point
    # (drag-end, spawn, ring load, forest load) so a freshly placed
    # subject can never come to rest stacked on another or hanging
    # off the screen.  Live drag-frames keep using ``_clamp_to_screen``
    # for the active cell and the live edge reflow for masters;
    # this helper handles the resting state.
    # ------------------------------------------------------------------

    def _settle_no_overlap(self) -> None:
        """Slide self (and, for masters, every positioned member) by
        the smallest translation that puts every subject rect
        fully on-screen AND not intersecting any other visible cell.

        No-op when:
          * the cell isn't visible yet;
          * a collapse/expand animation is in flight (overlap during
            collapse is allowed by spec);
          * the resting state is already overlap-free + on-screen.

        Spiral-searches 16 angles per ring outward in
        ``size_px // 3``-px rings up to a generous cap.  If no
        non-overlapping slot is found, leaves position unchanged and
        logs so the failure surfaces in diagnostics.
        """
        if not self.isVisible():
            return
        if getattr(self, "_collapse_state", "expanded") in (
            "collapsing", "expanding",
        ):
            return

        from PySide6.QtGui import QGuiApplication
        from scriptree.shell.cell_registry import CellRegistry

        registry = CellRegistry.instance()
        app_inst = QGuiApplication.instance()
        if app_inst is None:
            return

        # Build the subject set: just self, or master + every
        # positioned (and visible, not auto-hidden) member.
        subjects: list[tuple["CellWindow", QRect]] = []
        if self.role == "master":
            subjects.append((
                self,
                QRect(self.pos().x(), self.pos().y(),
                      self._size_px, self._size_px),
            ))
            for mid in list(self._positioned):
                if mid in self._auto_hidden:
                    continue
                m = registry.get(mid)
                if m is None or not m.isVisible():
                    continue
                subjects.append((
                    m,
                    QRect(m.pos().x(), m.pos().y(),
                          m._size_px, m._size_px),
                ))
        else:
            subjects.append((
                self,
                QRect(self.pos().x(), self.pos().y(),
                      self._size_px, self._size_px),
            ))

        if not subjects:
            return

        subject_ids = {c._id for c, _ in subjects}

        # Obstacles: every other visible cell, with auto-hidden ones
        # filtered out (they're not visually present anyway).
        obstacles: list[QRect] = []
        for h in registry.all():
            if h._id in subject_ids:
                continue
            if not h.isVisible():
                continue
            # If this cell is auto-hidden by some master, skip.
            mid = getattr(h, "_group_master_id", None)
            if mid is not None:
                m = registry.get(mid)
                if m is not None and h._id in m._auto_hidden:
                    continue
            sz = h._size_px
            obstacles.append(
                QRect(h.pos().x(), h.pos().y(), sz, sz),
            )

        # v0.8.0a81 multi-display: judge "fully on-screen" against the UNION
        # of ALL monitors, not just the subject's own screen.  The old
        # single-screen ``avail`` made settle treat a member that crossed onto
        # a SECOND monitor as off-screen, so it nudged the whole cluster back
        # by a 25px (size//3) spiral step "to clear 0 obstacle(s)" — the
        # user-reported "a cell shifts a little and becomes offset from its
        # docked location".  Keep ``screenAt`` only as a no-display guard so we
        # never spiral-shift blindly when there are zero screens.
        pivot = subjects[0][1].center()
        screen = app_inst.screenAt(pivot)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return

        def _ok(dx: int, dy: int) -> bool:
            for _c, r in subjects:
                moved = r.translated(dx, dy)
                # Must be FULLY visible across all monitors (union of screen
                # avail rects).  A member fully on ANY single screen — or split
                # across a flush inter-monitor bezel — counts as on-screen;
                # only a member hanging into dead space (off every monitor)
                # forces a slide.  On a single monitor this is identical to the
                # old full-containment test.
                if self._visible_area_on_any_screen(moved) < (
                    moved.width() * moved.height()
                ):
                    return False
                # v0.6.18 — overlap test uses CENTRE-DISTANCE, not
                # bounding-rect intersection.  Two hexes at
                # honeycomb-adjacent slots share an edge, but
                # their axis-aligned bounding squares intersect at
                # that edge — so the v0.6.12 rect.intersects()
                # check flagged every legitimate dock attempt as
                # "overlap" and the settle pushed the cells apart
                # ("bounces away from each other").  Pixel-stacked
                # cells have centre distance ~ 0, honeycomb
                # neighbours have centre distance ≥ ~0.86 *
                # size_px; threshold = 0.75 * (smaller size) lets
                # honeycomb adjacency through while still
                # catching genuine stacking.
                mcx = moved.center().x()
                mcy = moved.center().y()
                for o in obstacles:
                    ocx = o.center().x()
                    ocy = o.center().y()
                    threshold = min(moved.width(), o.width()) * 0.75
                    if (
                        abs(mcx - ocx) < threshold
                        and abs(mcy - ocy) < threshold
                    ):
                        return False
            return True

        if _ok(0, 0):
            return  # already settled

        import math
        step = max(8, self._size_px // 3)
        best: tuple[int, int] | None = None
        for ring in range(1, 41):  # up to ~ 40 * step px
            radius = ring * step
            for ang_i in range(16):
                ang = (ang_i / 16.0) * 2.0 * math.pi
                dx = int(round(radius * math.cos(ang)))
                dy = int(round(radius * math.sin(ang)))
                if _ok(dx, dy):
                    best = (dx, dy)
                    break
            if best is not None:
                break

        if best is None:
            # a73: the rigid block didn't fit anywhere -- the classic
            # case is a MASTER dragged into a CORNER where the whole
            # cluster can't slide on-screen as ONE unit.  A rigid
            # translation can only SLIDE the group; it can't
            # RE-ARRANGE it.  So fall back to the layout ENGINE, which
            # plans EVERY member's free, on-screen, non-overlapping
            # slot UP FRONT (Pass 1) and then applies them (Pass 2) --
            # "know where everything is going to go before placing it".
            # Clear non-floating slots first so Pass 1 re-derives fresh
            # slots around the master's current (corner) position.
            if self.role == "master" and self._members:
                _log(
                    f"_settle_no_overlap: rigid block doesn't fit "
                    f"{self._id[:8]} (subjects={len(subjects)}, "
                    f"obstacles={len(obstacles)}) -- re-packing members "
                    f"via the layout engine"
                )
                try:
                    for mid in list(self._members):
                        mm = registry.get(mid)
                        if mm is not None and not getattr(
                            mm, "_floating_intent", False
                        ):
                            mm._slot = None
                    self._compute_layout(instant=True)
                except Exception as exc:  # noqa: BLE001
                    _log(
                        f"_settle_no_overlap: engine re-pack fallback "
                        f"raised {exc!r}"
                    )
            else:
                _log(
                    f"_settle_no_overlap: no free slot found for "
                    f"{self._id[:8]} (subjects={len(subjects)}, "
                    f"obstacles={len(obstacles)})"
                )
            return

        dx, dy = best
        for c, r in subjects:
            c._smooth_move(r.left() + dx, r.top() + dy)
        _log(
            f"_settle_no_overlap: {self._id[:8]} shifted by "
            f"({dx},{dy}) to clear {len(obstacles)} obstacle(s)"
        )

    def _relocate_overlapping_members_individually(self) -> None:
        """v0.8.0a1+ramps Bug 3 — for a master that just docked to
        a target, leave the master at its snap-committed position
        and move each individual member that overlaps another cell
        to a free honeycomb slot around the master.

        Per the user's spec: "I should be able to dock and the
        cells should find new dock positions, if none available
        that are linked to their cell, then dock to the nearest
        available dock location on another cell or tree or ring,
        but stay linked to their current ring."

        Differs from ``_settle_no_overlap`` which shifts the entire
        master+members group rigidly — that approach pushes the
        master away from its dock slot when only some members
        overlap.

        Currently implements the first strategy (free slot around
        the master).  The "fall back to slot on another cell/tree/
        ring" strategy is a follow-up — for v0.8.0a1+ramps we
        leave overlapping members at their current position when
        no slot is free around the master (visually imperfect but
        the ring stays docked).  Link membership is never changed.
        """
        if self.role != "master":
            return
        from PySide6.QtGui import QGuiApplication
        from scriptree.shell.cell_registry import CellRegistry
        from scriptree.shell.layout import nearest_free_slot
        from scriptree.shell import tiling as _tiling

        registry = CellRegistry.instance()
        app = QGuiApplication.instance()
        if app is None:
            return

        # Build the obstacle spec list: every visible cell EXCEPT
        # the master itself.  We use this both for detecting which
        # members overlap and for the slot-collision check.
        obstacles_by_id: dict[str, tuple] = {}
        for h in registry.all():
            if h._id == self._id:
                continue
            if not h.isVisible():
                continue
            sz = h._size_px
            cx = h.pos().x() + sz / 2.0
            cy = h.pos().y() + sz / 2.0
            shape = _tiling.shape_from_legacy(h._shape, h._orientation)
            obstacles_by_id[h._id] = (shape, sz, (cx, cy))

        # Identify overlapping positioned members.
        members_to_relocate: list = []
        for mid in list(self._positioned):
            if mid in self._auto_hidden:
                continue
            member = registry.get(mid)
            if member is None or not member.isVisible():
                continue
            m_shape = _tiling.shape_from_legacy(
                member._shape, member._orientation,
            )
            m_cx = member.pos().x() + member._size_px / 2.0
            m_cy = member.pos().y() + member._size_px / 2.0
            others = [
                v for k, v in obstacles_by_id.items() if k != mid
            ]
            if _tiling.any_polygon_collides(
                m_shape, member._size_px, (m_cx, m_cy),
                others, slop_px=0.5,
            ):
                members_to_relocate.append(member)

        if not members_to_relocate:
            return

        # Build screen rect.
        screen = app.screenAt(self.pos())
        if screen is None:
            screen = app.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        screen_rect = (
            avail.left(), avail.top(),
            avail.right(), avail.bottom(),
        )
        master_pos = (self.pos().x(), self.pos().y())

        # Track slots already used by members staying put so we
        # don't double-assign.
        taken_slots: set[tuple[str, int]] = set()
        ids_to_relocate = {m._id for m in members_to_relocate}
        for mid in list(self._positioned):
            if mid in ids_to_relocate:
                continue
            member = registry.get(mid)
            if member is None:
                continue
            slot = getattr(member, "_slot", None)
            if slot is not None:
                taken_slots.add(tuple(slot))

        for member in members_to_relocate:
            drop_centre = (
                int(member.pos().x() + member._size_px / 2.0),
                int(member.pos().y() + member._size_px / 2.0),
            )
            other_specs = [
                v for k, v in obstacles_by_id.items() if k != member._id
            ]
            slot = nearest_free_slot(
                master_pos=master_pos,
                master_size=self._size_px,
                master_slot=None,
                drop_centre=drop_centre,
                child_size=member._size_px,
                taken_slots=taken_slots,
                occupied_centres=set(),
                screen_rect=screen_rect,
                master_orientation=self._orientation,
                master_shape=self._shape,
                child_shape=member._shape,
                child_orientation=member._orientation,
                other_specs=other_specs,
            )
            if slot is None:
                _log(
                    f"_relocate_overlapping_members: no free slot "
                    f"around ring {self._id[:8]} for member "
                    f"{member._id[:8]} — leaving in place (follow-up: "
                    f"search slots on other cells/rings)"
                )
                continue
            kind, idx = slot
            tl = _tiling.slot_world_pos(
                master_pos,
                _tiling.shape_from_legacy(self._shape, self._orientation),
                self._size_px,
                kind, idx,
                _tiling.shape_from_legacy(
                    member._shape, member._orientation,
                ),
                member._size_px,
            )
            member.move_to(int(tl[0]), int(tl[1]))
            member._slot = slot
            taken_slots.add(slot)
            self._members[member._id] = QPoint(int(tl[0]), int(tl[1]))
            # Update obstacles_by_id so subsequent relocates see
            # this member at its new position.
            new_cx = tl[0] + member._size_px / 2.0
            new_cy = tl[1] + member._size_px / 2.0
            obstacles_by_id[member._id] = (
                _tiling.shape_from_legacy(member._shape, member._orientation),
                member._size_px,
                (new_cx, new_cy),
            )
            _log(
                f"_relocate_overlapping_members: moved {member._id[:8]} "
                f"to slot {slot} at ({tl[0]:.0f},{tl[1]:.0f})"
            )

    # ------------------------------------------------------------------
    # Harness-driveable public hooks (ADR-001 Â§harness-driveable contract)
    # These are PRODUCTION methods — real input handlers delegate to them.
    # They are NOT gated by any build flag.
    # ------------------------------------------------------------------

    def move_to(self, x: int, y: int) -> None:
        """Move the window to logical screen coordinates (x, y).

        Identical effect to a user drag-end at that position.
        Fires CellRegistry.hexagonMoved (via moveEvent).

        v0.8.0a1+ramps Bug 4 — additionally cascade the delta to
        every cell in this cell's ``_dock_children_by_edge``.  Snap-
        commit (``snap_engine.detach_drag``) and ``dock_with`` both
        funnel through here, and the user expects "the cells docked
        to it" to follow when the parent shifts to its snap slot.
        Children's own ``move_to`` re-cascades, so a dock-chain
        A→B→C→… all follows.
        """
        prev = self.pos()
        delta_x = x - prev.x()
        delta_y = y - prev.y()
        self.move(x, y)
        if (delta_x or delta_y) and self._dock_children_by_edge:
            from scriptree.shell.cell_registry import CellRegistry
            registry = CellRegistry.instance()
            # Guard: mark self in flight so a child whose own
            # cascade somehow tries to re-enter via us is a no-op.
            _GROUP_MOVE_IN_PROGRESS.add(self._id)
            try:
                for child_id in list(self._dock_children_by_edge.values()):
                    if child_id in _GROUP_MOVE_IN_PROGRESS:
                        continue
                    child = registry.get(child_id)
                    if child is None:
                        continue
                    # Recursive: chain-children carry their own
                    # grandchildren via this same code path.
                    child.move_to(
                        child.pos().x() + delta_x,
                        child.pos().y() + delta_y,
                    )
            finally:
                _GROUP_MOVE_IN_PROGRESS.discard(self._id)

    def click(self, mode: Literal["single", "double", "right", "double-right"] = "single") -> None:
        """Programmatically fire the same handler a real click would.

        mode:
            "single"       — single left-click (tool launch in standalone mode,
                             OR collapse/expand toggle when role == 'master').
            "double"       — double left-click (lock-open tree view in standalone
                             mode, OR open merged tree when role == 'master').
            "right"        — single right-click; opens the context menu at window centre.
            "double-right" — double right-click; opens the composite editor for ALL
                             roles (standalone and master).  For standalones this is
                             identical to double-left (both call show_composite_for).

        Click-mode contract (sacred — per menu-engineer.md hard rule 1):
            standalone single         â†’ open tree in standalone mode.
            standalone double (1st)   â†’ open tree in lock-open mode; _locked_open=True.
            standalone double (2nd)   â†’ close the open menu; _locked_open=False.
            standalone double-right   â†’ show_composite_for(self) [same as double-left].
            master single             â†’ toggle collapse/expand.
            master double             â†’ open merged tree (lock-open path).
            master double-right       â†’ open composite editor.
            right (all roles)         â†’ context menu (unchanged).

        Note: for standalones, double-left and double-right are currently equivalent.
        This redundancy is intentional — user confirmed "double right clicking any of
        the hexes should do the same thing."  Future disambiguation (e.g. standalone
        double-right = open composite for self only, double-left = lock-open tree)
        can be added without breaking the master contract.

        Per ADR-001 Â§harness-driveable contract: real mouse handlers delegate
        here.  This IS the one code path — not a test-only copy.
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
                    # Ignore the extra signal — the pending fire will still happen.
                    _log(
                        f"click(single) master id={self._id[:8]} "
                        "— deferred fire already pending; ignoring"
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
                    f"— deferred {interval} ms waiting for possible double-click"
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

            # Click-to-run dispatch (V3 v0.3.5+).  The bound catalog's
            # ``cell.click_action`` field decides whether single-left-
            # click shows the popup menu (default, pre-v0.3.5 behaviour)
            # or fires the tool(s) directly via click_to_run.
            #
            # The capability ``cell_click_to_run`` is checked at the
            # Settings-dialog level (the dropdown is locked when
            # denied), so an action of "run" reaching this dispatch
            # means the admin previously allowed it.  We still
            # short-circuit to "menu" when the catalog hasn't been
            # loaded yet (no ``click_action`` to read).
            click_action = self._read_click_action()
            if click_action == "run" and self._catalog_path:
                run_mode = self._read_click_run_mode()
                _log(
                    f"click(single) id={self._id[:8]} — click-to-run "
                    f"(mode={run_mode}, catalog={Path(self._catalog_path).name})"
                )
                try:
                    from scriptree.shell.click_to_run import run_catalog_on_click
                    run_catalog_on_click(self._catalog_path, run_mode)
                except Exception as exc:  # noqa: BLE001
                    _log(
                        f"click(single): click-to-run failed: {exc!r} "
                        f"— falling back to menu"
                    )
                    try:
                        from scriptree.shell.v1_launcher import show_tree_for
                        show_tree_for(self, mode="standalone")
                    except Exception as exc2:  # noqa: BLE001
                        _log(
                            f"click(single): menu fallback also failed: "
                            f"{exc2!r}"
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
            # within the doubleClickInterval — we cancel the deferred toggle so the
            # slide never happens and only the double-click action executes.
            if self._pending_master_single_click_timer is not None:
                self._pending_master_single_click_timer.stop()
                self._pending_master_single_click_timer.deleteLater()
                self._pending_master_single_click_timer = None
                _log(f"click(double) id={self._id[:8]} — cancelled pending master single-click")

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
            #
            # v0.8.0a45+ REMOVED: the a25 "single-tool shortcut"
            # called ``launch_tool`` (V1 standalone runner) for
            # cells that contained exactly one leaf.  Per updated
            # user spec, single-tool cells should behave like
            # tree cells -- double-left opens the developer EDITOR,
            # not the standalone runner.  Falling through to the
            # standalone-cell branch below routes the .scriptree
            # path through ``show_tree_for(mode="lock-open")``,
            # which now ends up at ``launch_editor_with_tree`` for
            # both extensions (see v1_launcher.py a45 fix).
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
                # Second double-click: unlock — close the open menu and clear flag.
                _log(f"click(double) id={self._id} — unlock; closing lock-open tree")
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
                _log(f"click(double-right) id={self._id[:8]} — cancelled pending master single-click")

            # double-right-click: open composite editor for ALL hex roles.
            #
            # Decision tree:
            #   master     + not locked â†’ lock-open composite editor (show_composite_for)
            #   master     + locked     â†’ unlock and close
            #   standalone + not locked â†’ same as double-LEFT for standalones
            #                             (show_composite_for(self)); both LEFT and RIGHT
            #                             do the same thing for standalones — that is
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
                    "— unlocking composite editor"
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
        self,
        target_pos: QPoint,
        duration_ms: int = 250,
        curve: "QEasingCurve.Type | None" = None,
    ) -> QPropertyAnimation:
        """Create and return a QPropertyAnimation that slides self to target_pos.

        Defaults to ``QEasingCurve.OutCubic`` (smooth deceleration; Mac-style
        ease-out feel).  The caller is responsible for connecting finished() and
        for keeping a reference to the animation (store on the hex so GC doesn't
        collect it mid-flight).
        """
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(duration_ms)
        anim.setStartValue(self.pos())
        anim.setEndValue(target_pos)
        anim.setEasingCurve(curve or QEasingCurve.Type.OutCubic)
        return anim

    # ------------------------------------------------------------------
    # Macify (v0.6.10) — smooth moves and spawn fade-ins.
    #
    # ``_smooth_move`` is the Mac-style replacement for ``self.move(x, y)``
    # at the *end* of a logical reposition (a repack, a reflow restore, a
    # snap commit).  Per-frame manual drag MUST still use the plain
    # ``self.move`` — animating each cursor tick would feel laggy.
    # ``_fade_in`` softens cell spawn so members slide into existence
    # rather than popping.
    # ------------------------------------------------------------------

    def _smooth_move(
        self,
        target_x: int,
        target_y: int,
        *,
        duration_ms: int = 240,
        curve: "QEasingCurve.Type | None" = None,
        threshold_px: int = 2,
        max_animate_px: int = 600,
    ) -> None:
        """Eased slide to ``(target_x, target_y)``.

        Falls back to an instant ``self.move`` when:
          * the widget isn't visible (no point animating off-screen);
          * the cell is mid-drag (per-frame translation, animation
            would lag the cursor);
          * the delta is below ``threshold_px`` (de-jitter no-ops);
          * the delta exceeds ``max_animate_px`` on either axis — a
            cross-screen slide of several hundred ms reads as slow,
            not fluid, so we just teleport (matches Mac behaviour
            where windows snap, not crawl, to a distant slot).

        Cancels any prior in-flight position animation so successive
        calls don't fight each other — the latest target always wins.
        """
        cur = self.pos()
        dx = target_x - cur.x()
        dy = target_y - cur.y()
        if (
            not self.isVisible()
            or getattr(self, "_drag_started", False)
            or (abs(dx) <= threshold_px and abs(dy) <= threshold_px)
            or abs(dx) > max_animate_px
            or abs(dy) > max_animate_px
        ):
            prior = getattr(self, "_pos_anim", None)
            if prior is not None:
                try:
                    prior.stop()
                except Exception:  # noqa: BLE001
                    pass
                self._pos_anim = None
            self.move(target_x, target_y)
            return
        prior = getattr(self, "_pos_anim", None)
        if prior is not None:
            try:
                prior.stop()
            except Exception:  # noqa: BLE001
                pass
        anim = self._animate_to(
            QPoint(target_x, target_y),
            duration_ms=duration_ms,
            curve=curve,
        )
        self._pos_anim = anim  # keep alive until finished
        anim.finished.connect(lambda: setattr(self, "_pos_anim", None))
        anim.start()

    def _fade_in(self, duration_ms: int = 180) -> None:
        """Animate windowOpacity 0 → current on the next event loop tick.

        Called by the spawn paths (drop-join, sibling clone, master
        spawn) so a new cell glides into existence instead of popping.
        Safe to call repeatedly — only triggers the first time per
        cell unless ``_fade_in_done`` is cleared.
        """
        if getattr(self, "_fade_in_done", False):
            return
        self._fade_in_done = True
        try:
            target = float(self.windowOpacity())
            if target <= 0.0:
                target = 1.0
            self.setWindowOpacity(0.0)
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(duration_ms)
            anim.setStartValue(0.0)
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._fade_anim = anim
            anim.finished.connect(
                lambda: setattr(self, "_fade_anim", None)
            )
            anim.start()
        except Exception as exc:  # noqa: BLE001
            # Never let a cosmetic fade abort the spawn.
            _log(f"_fade_in failed: {exc!r}")

    def _fire_pending_master_single_click(self) -> None:
        """Timer callback: the double-click window elapsed with no double-click.

        Master single-click toggles collapse/expand on the master.
        Per user spec (v0.6.20, correcting v0.6.17/v0.6.19): a single
        click on the forest or any ring collapses *all linked cells*
        — every member tucks into the master with the v0.6.16
        recursive cascade so sub-rings collapse along with their
        forest.  No opt-in / opt-out per cell; the toggle is the
        one and only "minimize / maximize this group" gesture.
        """
        _log(
            f"_fire_pending_master_single_click id={self._id[:8]} "
            "— double-click window elapsed; toggling collapse"
        )
        self._pending_master_single_click_timer = None
        self._toggle_collapse()

    def _toggle_collapse(self) -> None:
        """Toggle the collapsed/expanded state of this master hexagon (Bug 3).

        Called from click(mode='single') when role == 'master'.
        Ignores the click if an animation is currently in flight.
        """
        if self._collapse_state in ("collapsing", "expanding"):
            _log(f"_toggle_collapse {self._id}: animation in flight — click ignored")
            return

        if self._collapse_state == "expanded":
            self._start_collapse()
        elif self._collapse_state == "collapsed":
            self._start_expand()

    def _start_collapse(self) -> None:
        """Animate ALL link-children toward the master centre,
        recursing into sub-masters so the whole link tree collapses
        together (v0.6.20, reverting the v0.6.17 opt-in to the
        v0.6.16 cascade per user direction "single click on forest
        or a ring is supposed to collapse all linked cells").
        """
        # v0.8.0a113 [reloc FIX] -- snapshot the hub position at collapse.  On
        # the matching expand, members are pinned at their current (absolute)
        # home ONLY IF the hub hasn't moved since -- because ``_members[mid]``
        # is absolute, so if the hub was dragged WHILE collapsed those homes are
        # stale (relative to the old hub spot) and must be engine-tiled around
        # the new hub position instead (the a68 behaviour).  Same-position
        # expand keeps every cell where it was (the a113 no-relocation fix).
        from PySide6.QtCore import QPoint as _QP
        self._hub_pos_at_collapse = _QP(self.pos())
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()

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

        # v0.6.36 — trace collapse start.
        try:
            _trace.event(
                "COLLAPSE_START",
                master=self._id[:8],
                pos=(target.x(), target.y()),
                member_count=len(members),
                member_ids=[m._id[:8] for m in members],
            )
            _trace.snapshot(f"collapse-start-{self._id[:8]}")
        except Exception:  # noqa: BLE001
            pass

        # v0.6.34 — safety watchdog.  If any animation's ``finished``
        # signal is lost (e.g. the animation is interrupted by a
        # later ``_smooth_move`` that replaces it) the collapse state
        # would stay stuck in ``"collapsing"`` forever and the next
        # single-click would be ignored by ``_toggle_collapse``'s
        # animation-in-flight guard.  Schedule a force-clear after
        # 1 s — well past the 250 ms animation duration — that
        # finalises the state if pending is still non-empty.
        from PySide6.QtCore import QTimer as _QTimer
        def _force_finalise_collapse():
            if self._collapse_state != "collapsing":
                return
            for mid in list(pending):
                m = registry.get(mid)
                if m is not None:
                    m.setVisible(False)
                self._collapse_animations.pop(mid, None)
            pending.clear()
            self._collapse_state = "collapsed"
            _log(
                f"_start_collapse {self._id[:8]}: safety watchdog "
                f"finalised stuck collapse"
            )
        _QTimer.singleShot(1000, _force_finalise_collapse)

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
            # v0.6.20 — recursive cascade restored.  If this member
            # is itself a master with link-children (e.g. a ring
            # inside the forest), collapse it FIRST so its members
            # tuck into it in parallel with it traveling toward us.
            # Result: forest collapse → ring's cells shrink into
            # the ring AND the ring shrinks into the forest in one
            # synchronized motion.
            if (
                m.role == "master"
                and getattr(m, "_members", None)
                and m._collapse_state == "expanded"
            ):
                try:
                    m._start_collapse()
                except Exception as exc:  # noqa: BLE001
                    _log(
                        f"_start_collapse: recursive collapse of "
                        f"{m._id[:8]} raised {exc!r} — continuing"
                    )
            anim = m._animate_to(target, duration_ms=250)
            anim.finished.connect(_make_finish_handler(m._id))
            self._collapse_animations[m._id] = anim
            anim.start()

        _log(f"_start_collapse {self._id}: animating {len(members)} member(s) to master pos")

    def _start_expand(self) -> None:
        """Restore ALL link-children to their stored positions
        (v0.6.20, reverting v0.6.17 opt-in).  Sub-masters in a
        collapsed state are recursively expanded so the whole
        sub-tree re-blooms together.

        Edge-fold interaction (unchanged):
        - _auto_hidden is cleared before expansion so setVisible(True)
          isn't fought by any lingering auto-hide state.
        - After all animations finish, _check_edge_fold() runs once
          to re-evaluate visibility at the master's current position.
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

        # v0.6.36 — trace expand start.
        try:
            _trace.event(
                "EXPAND_START",
                master=self._id[:8],
                pos=(self.pos().x(), self.pos().y()),
                member_count=len(members),
                member_ids=[m._id[:8] for m in members],
            )
            _trace.snapshot(f"expand-start-{self._id[:8]}")
        except Exception:  # noqa: BLE001
            pass

        # v0.6.34 — safety watchdog (matches _start_collapse).  If any
        # animation's ``finished`` signal is lost, force-clear the
        # state so the next single-click isn't ignored by the
        # animation-in-flight guard.
        from PySide6.QtCore import QTimer as _QTimer
        def _force_finalise_expand():
            if self._collapse_state != "expanding":
                return
            pending.clear()
            self._collapse_state = "expanded"
            self._check_edge_fold()
            _log(
                f"_start_expand {self._id[:8]}: safety watchdog "
                f"finalised stuck expand"
            )
        _QTimer.singleShot(1000, _force_finalise_expand)

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

        # v0.8.0a68 — re-bloom THROUGH THE LAYOUT ENGINE.
        #
        # The pre-a68 path (incl. a67's offset trick) replayed a
        # remembered ABSOLUTE coordinate per member, with no free-slot,
        # on-screen, or collision check -- so members overlapped the hub
        # or each other and could land off-screen.  Route placement
        # through the same engine startup/spawn already use:
        #
        #   1. Clamp the HUB on-screen first, so _compute_layout's
        #      ``screenAt(self.pos())`` resolves to a real screen (an
        #      off-screen hub would compute every slot off a bad origin).
        #   2. Clear each non-floating member's ``_slot`` so Pass 1
        #      re-derives a FREE, ON-SCREEN, NON-COLLIDING honeycomb slot
        #      around the hub's CURRENT position -- _compute_layout
        #      forbids the hub's own centre as a collider (~4481), i.e.
        #      "attach to a side, never on the forest icon".
        #   3. _compute_layout(instant=True) writes each member's
        #      engine-assigned top-left into ``self._members[mid]`` --
        #      now the authoritative bloom target.
        try:
            self.move(self._clamp_to_screen(self.pos()))
        except Exception as exc:  # noqa: BLE001
            _log(f"_start_expand: hub clamp raised {exc!r}")
        # v0.8.0a83 — RESTORE the user's remembered arrangement first, then
        # let the engine tile ONLY the remainder around the restored cells:
        #
        #   1. _restore_remembered_offsets(move=False): for each member whose
        #      remembered offset from this hub is WHOLLY on-screen, write that
        #      spot into _members[mid] (the bloom target).  Returns the placed
        #      set; an off-screen member is skipped but KEEPS its offset (so it
        #      returns to its spot once screen space allows).
        #   2. Clear _slot only for members NOT restored, so the engine
        #      re-derives a fresh free slot for them; restored members keep
        #      their remembered _members target untouched.
        #   3. _compute_layout(pinned=placed): the engine tiles the remainder,
        #      treating each restored member's centre as occupied so it never
        #      tiles onto one.  a74 full-fit / hub-centre-forbidden invariants
        #      are preserved (no a68 overlap or off-screen regression).
        # The bloom loop below then animates every member from the hub centre
        # to its _members[mid] target (remembered for restored, engine for the
        # rest).
        placed = self._restore_remembered_offsets(move=False)
        # v0.8.0a113 [reloc FIX] -- also pin every member at its CURRENT on-
        # screen home so a re-bloom NEVER relocates a cell the user didn't
        # explicitly drag (its space is free -> keep it there).  ONLY when the
        # hub is at the SAME position as at collapse: if the hub was dragged
        # while collapsed, the absolute homes are stale and must be engine-
        # tiled around the new hub position (a68).  Genuinely new / off-screen
        # members always fall through to the engine below.
        hub_static = (
            getattr(self, "_hub_pos_at_collapse", None) is not None
            and self._hub_pos_at_collapse == self.pos()
        )
        if hub_static:
            home_pins = self._current_home_pins(members, placed)
            if home_pins:
                placed = placed | home_pins
                _log(
                    f"_start_expand {self._id[:8]}: pinned {len(home_pins)} "
                    f"member(s) at current home (no-drag stability)"
                )
        for m in members:
            if getattr(m, "_id", None) in placed:
                continue
            if not getattr(m, "_floating_intent", False):
                m._slot = None
        try:
            self._compute_layout(instant=True, pinned=placed)
        except Exception as exc:  # noqa: BLE001
            _log(f"_start_expand: _compute_layout raised {exc!r}")

        leaf_pending: list[str] = []
        for m in members:
            # a74: for an ENGINE-PLACED member (``_slot`` set), use the
            # engine slot VERBATIM -- do NOT clamp.  The a74 full-fit
            # rule guarantees that slot is wholly on-screen, and
            # clamping it was exactly what pushed a corner cell DOWN off
            # its slot into the neighbour below ("bloom-into-corner
            # overlap").  Only the FALLBACK (a floating member, which
            # _compute_layout skips, or a member for which no free slot
            # was found) is clamped on-screen.
            # a83 — a RESTORED (pinned) member must use its remembered target
            # VERBATIM: _restore_remembered_offsets already proved that spot is
            # wholly visible across ALL monitors, so it must never be run
            # through the single-screen _clamp_to_screen (which would yank a
            # seam-straddling / secondary-monitor member off its remembered
            # position and could land it on an engine-tiled neighbour).  Gate
            # the verbatim/no-clamp branch on membership in ``placed`` as well
            # as on an engine slot (a74), since a freshly-restored member's
            # _slot is None.
            target = self._members.get(m._id)
            if target is not None and (m._id in placed or m._slot is not None):
                target = QPoint(target)
            else:
                if target is None:
                    target = self.pos() + QPoint(self._size_px + 8, 0)
                try:
                    target = m._clamp_to_screen(QPoint(target))
                except Exception:  # noqa: BLE001
                    target = QPoint(target)
            is_submaster = (
                m.role == "master"
                and getattr(m, "_members", None)
                and m._collapse_state == "collapsed"
            )
            if is_submaster:
                # A nested ring: drop it straight onto its engine slot
                # (no slide), THEN recurse so its OWN children bloom
                # around the ring's correct, on-screen slot rather than
                # around the hub centre mid-animation.
                m.move(target)
                m.setVisible(True)
                try:
                    m._start_expand()
                except Exception as exc:  # noqa: BLE001
                    _log(
                        f"_start_expand: recursive expand of "
                        f"{m._id[:8]} raised {exc!r} — continuing"
                    )
            else:
                # Leaf cell: slide out from the hub centre to its
                # engine-assigned slot (the "bloom").
                leaf_pending.append(m._id)
                m.move(self.pos())
                m.setVisible(True)
                anim = m._animate_to(target, duration_ms=250)
                anim.finished.connect(_make_finish_handler(m._id))
                self._collapse_animations[m._id] = anim
                anim.start()

        # Only the sliding leaf members gate the "expanded" transition;
        # if there are none (e.g. only nested rings), finalise now.
        pending[:] = leaf_pending
        if not leaf_pending:
            self._collapse_state = "expanded"
            self._check_edge_fold()

        _log(
            f"_start_expand {self._id}: re-bloomed {len(members)} "
            f"member(s) via the layout engine"
        )

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

        This is the old alias — kept for any residual callers.
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
                f"{other._shape}/{other._orientation}) — no snap"
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
            _log(f"dock_with: no slot found — should not happen")
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
            # Shim — empty in the new model; kept so harness code that reads it
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
      apothem       a = R * cos(30°) = R * sqrt(3)/2 = hex_size * sqrt(3) / 4
      flat-to-flat  = 2a = hex_size * sqrt(3) / 2   â† called flat_to_flat below

    For the master to sit flush ABOVE the source centroid (master bottom flat edge
    = source top flat edge):
      master_center_y + a = centroid_y - a
      master_center_y     = centroid_y - 2a = centroid_y - flat_to_flat
      master_top_left_y   = master_center_y - R = centroid_y - flat_to_flat - hex_size/2

    NOTE: centroid is computed from each source window's CENTRE (geometry().center()),
    not its top-left pos().  This is essential — using pos() shifts the centroid
    by R in both axes and causes an R-pixel overlap.

    The hex bounding boxes DO overlap by (R - a) = R(1 - sqrt(3)/2) â‰ˆ 0.134R pixels
    in each direction — this is expected and correct because the polygon corners are
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
        # No screen info — prefer above, fall back to below if y < 0.
        cand_y = cand_y_above if cand_y_above >= 0 else cand_y_below

    return (cand_x, cand_y)


# ---------------------------------------------------------------------------
# v0.8.0 P3 — dock relationship helpers
# ---------------------------------------------------------------------------

def _compute_dock_edge(
    child_centre: tuple[float, float],
    partner: "CellWindow",
    tolerance_px: float = 4.0,
) -> "int | None":
    """Find which of ``partner``'s edges ``child_centre`` is sitting at.

    Returns the edge index (0..5 for hex, 0..3 for square) of the
    partner's neighbour slot closest to the child centre.  Returns
    None if no slot is within ``tolerance_px`` — child isn't actually
    edge-adjacent.

    Used at snap-commit time to record which edge of the snap target
    the dragged cell landed at, so the new ``_dock_partner_id`` /
    ``_dock_edge`` fields point at the right slot.
    """
    import math as _math
    from scriptree.shell.snap_engine import _neighbour_slot_centres
    p_geo = partner.geometry()
    p_cx = p_geo.x() + p_geo.width() / 2.0
    p_cy = p_geo.y() + p_geo.height() / 2.0
    slots = _neighbour_slot_centres(
        p_cx, p_cy, partner._size_px,
        partner._shape, partner._orientation,
    )
    best_idx: "int | None" = None
    best_dist = float("inf")
    for i, (sx, sy) in enumerate(slots):
        d = _math.hypot(sx - child_centre[0], sy - child_centre[1])
        if d < best_dist:
            best_dist = d
            best_idx = i
    if best_dist > tolerance_px:
        return None
    return best_idx


def _set_cell_dock(
    child: "CellWindow", partner: "CellWindow",
    *,
    child_centre: "tuple[float, float] | None" = None,
) -> None:
    """v0.8.0 P3 — atomically wire the dock relationship between
    ``child`` and ``partner``.

    Computes the edge index of ``partner`` where ``child`` currently
    sits, sets ``child._dock_partner_id`` + ``child._dock_edge``,
    and updates ``partner._dock_children_by_edge`` reciprocally.

    If ``child`` was already docked elsewhere, the old partner's
    reverse index is cleared first (no orphan back-references).

    If ``child`` is not actually edge-adjacent to ``partner``
    (no slot within 4 px tolerance), the dock pointer is left
    unset and a debug line is logged — the snap engine emits
    snapCommit only after positioning ``child`` at a slot of
    ``partner``, so this case implies a programmer error in the
    caller, not user input.

    ``child_centre`` (v0.8.0a1+ramps Bug 6 fix) — when provided,
    use this (cx, cy) instead of ``child.geometry()`` to compute
    the edge.  Callers that wire dock pointers immediately after
    triggering an animated ``_repack_members`` (e.g.
    ``_try_spawn_master``) need to pass the TARGET position
    because ``child.geometry()`` still returns the stale pre-
    animation position.
    """
    from scriptree.shell.cell_registry import CellRegistry
    if child_centre is None:
        c_geo = child.geometry()
        c_cx = c_geo.x() + c_geo.width() / 2.0
        c_cy = c_geo.y() + c_geo.height() / 2.0
    else:
        c_cx, c_cy = child_centre
    edge = _compute_dock_edge((c_cx, c_cy), partner)
    if edge is None:
        _log(
            f"_set_cell_dock: {child._id[:8]} not edge-adjacent to "
            f"{partner._id[:8]} — dock pointer left unset"
        )
        return
    registry = CellRegistry.instance()
    # Clear any prior dock relationship on this child.
    if child._dock_partner_id is not None and child._dock_edge is not None:
        old_partner = registry.get(child._dock_partner_id)
        if old_partner is not None:
            old_partner._dock_children_by_edge.pop(child._dock_edge, None)
    # If the partner's target edge is already taken by some other cell,
    # clear that cell's dock pointer to keep the invariant
    # (one child per edge).
    prior_child_id = partner._dock_children_by_edge.get(edge)
    if prior_child_id is not None and prior_child_id != child._id:
        prior_child = registry.get(prior_child_id)
        if prior_child is not None:
            prior_child._dock_partner_id = None
            prior_child._dock_edge = None
    # Wire the new dock.
    child._dock_partner_id = partner._id
    child._dock_edge = edge
    partner._dock_children_by_edge[edge] = child._id


def _try_spawn_master(a: CellWindow, b: CellWindow) -> None:
    """Snap-commit handler: wire a and b into the group-association model.

    Amendment 2 decision tree (4 cases):
    â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    Case 1 — both standalone (no group):
        Spawn a fresh master. Both become members. Both go into _positioned.
        Master placed at the deterministic honeycomb cell adjacent to both.

    Case 2 — tgt (b) is in a group, src (a) is standalone:
        a joins b's master's group. master._members[a._id] = a.pos().
        a added to master._positioned (it just snapped into the cluster).
        a._group_master_id = master._id. Master does NOT move.
        a._link_parent_id = master._id. Master does NOT move.  # v0.8.0 P1 mirror

    Case 3 — src (a) is in a group, tgt (b) is standalone:
        b joins a's master's group. Same as Case 2 mirrored.

    Case 4 — both in DIFFERENT groups:
        a TRANSFERS from its current master to b's master.
        Remove a from old master's _members/_positioned.
        If old master drops below 2 members, close it.
        Add a to new master's _members/_positioned.
        a._group_master_id = new master._id.
        a._link_parent_id = new master._id.  # v0.8.0 P1 mirror

    Case 5 — both in the SAME group:
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
    # v0.8.0 — the pre-v0.8.0 reject is replaced with explicit case
    # handling.  The link/dock split allows rings and the forest
    # to be dock targets:
    #
    #   Case M1 — src IS a master (ring): per user Q2=(b), a ring
    #             docking onto anything is purely spatial — no link
    #             change.  Rings always stay forest-linked.  Set
    #             dock fields and return.
    #   Case M2 — src is a cell, tgt is a master (ring or forest):
    #             cell links to the master and docks at the snapped
    #             edge.  This is the cell-onto-ring or cell-onto-
    #             forest case the user described.
    if a.role == "master":
        # Case M1
        _set_cell_dock(a, b)
        _log(
            f"Case M1 (master src dock): {a._id[:8]} role={a.role} "
            f"dock-attaches to {b._id[:8]} role={b.role} (no link change)"
        )
        return
    if b.role == "master":
        # Case M2 — cell docks onto a master (ring or forest).
        master = b
        a._group_master_id = master._id
        a._link_parent_id = master._id  # v0.8.0 P1 mirror
        master._members[a._id] = QPoint(a.pos())
        master._positioned.add(a._id)
        a._docked_to.clear()
        try:
            _update_docked_to(a, b, registry)
        except Exception:  # noqa: BLE001
            pass
        a.update()
        if not master.isVisible():
            master.show()
        master._ring_dirty = True
        _set_cell_dock(a, master)
        _log(
            f"Case M2 (cell-to-master dock): {a._id[:8]} links to "
            f"{master._id[:8]} (role={master.role})"
        )
        return

    tgt_master_id = registry.master_of(b._id)
    src_master_id = registry.master_of(a._id)

    _log(
        f"_try_spawn_master: a={a._id[:8]} (master={src_master_id and src_master_id[:8]}) "
        f"b={b._id[:8]} (master={tgt_master_id and tgt_master_id[:8]})"
    )

    # ---- Case 5: both in same group ----------------------------------------
    # v0.6.14 — if the "common group" is the *forest* hub (not a
    # ring master), the two cells are forest-linked but not in the
    # same ring.  Per user spec, they should form a NEW ring under
    # the forest, not be repositioned as direct forest members.
    # Fall through to Case 1 for the ring spawn; the link
    # preservation block at the end of this function then promotes
    # the new ring to a forest member.
    if (
        tgt_master_id is not None
        and src_master_id is not None
        and tgt_master_id == src_master_id
    ):
        master = registry.get(tgt_master_id)
        # v0.6.17 — only fall through to ring-spawn when BOTH
        # cells are LOOSE-linked to the forest (link parent is
        # the forest AND they're NOT currently in the forest's
        # positional cluster).  v0.6.14's check was too loose:
        # it fired for any two forest-linked cells, so moving a
        # cell within a chain of docked forest members spawned a
        # spurious ring.  Loose-linked-only restores the intent:
        # "two cells dragged AWAY from the forest, brought back
        # together, form a new ring."
        a_is_loose = (
            master is not None
            and a._id not in master._positioned
        )
        b_is_loose = (
            master is not None
            and b._id not in master._positioned
        )
        if (
            master is not None
            and getattr(master, "_is_forest_master", False)
            and a_is_loose and b_is_loose
        ):
            _log(
                f"Case 5→1 (both forest-linked AND both loose): "
                f"{a._id[:8]} + {b._id[:8]} → spawn new ring "
                f"under forest {master._id[:8]}"
            )
            # Fall through to the Case-1 path.  Null out the
            # locally-resolved master ids so Case 4 / Case 2 / 3
            # don't grab the flow on the way down.  The forest
            # link is preserved later by the link-preservation
            # block at the end of this function (it reads the
            # *original* _group_master_id we captured into
            # _a_prior_group / _b_prior_group).
            tgt_master_id = None
            src_master_id = None
        elif master is not None:
            _adopt_member_geometry(a, master)
            master._members[a._id] = QPoint(a.pos())
            master._positioned.add(a._id)
            _update_docked_to(a, b, registry)
            # v0.8.0 P3 — Case 5 dock update: ``a`` re-snapped
            # against ``b`` within the same group.  Dock partner is
            # ``b``, which may differ from any previous partner ``a``
            # had (it could have been the master, or a different
            # sibling cell).
            _set_cell_dock(a, b)
            # V3 v0.3.17 — DO NOT repack.  Per user contract:
            # moving one element within a group must NOT reshift
            # the others.  ``a`` is at the position the snap engine
            # committed to (edge-adjacent to ``b``), and ``b`` and
            # the rest of the group stay where they are.
            _log(
                f"Case 5 (same ring): {a._id[:8]} repositioned "
                f"within group {tgt_master_id[:8]}"
            )
            return
        else:
            _log(
                f"Case 5 (same group): {a._id[:8]} repositioned "
                f"within group {tgt_master_id[:8]} (master gone)"
            )
            return

    # ---- Case 4: both in DIFFERENT groups -----------------------------------
    if tgt_master_id is not None and src_master_id is not None:
        old_master = registry.get(src_master_id)
        new_master = registry.get(tgt_master_id)
        if old_master is not None:
            old_master._members.pop(a._id, None)
            old_master._positioned.discard(a._id)
            old_master._dock_partners.discard(a._id)
            # Member transferred out — old ring is dirty (membership changed).
            old_master._ring_dirty = True
        if new_master is not None:
            _adopt_member_geometry(a, new_master)
            new_master._members[a._id] = QPoint(a.pos())
            new_master._positioned.add(a._id)
            new_master._dock_partners.add(a._id)
            # Member added — new ring is dirty (membership changed).
            new_master._ring_dirty = True
        a._group_master_id = tgt_master_id
        a._link_parent_id = tgt_master_id  # v0.8.0 P1 mirror
        a._docked_to.clear()
        _update_docked_to(a, b, registry)
        a.update()  # Bug 5: refresh outline colour (now associated)
        # v0.8.0 P3 — Case 4 dock write: ``a`` transferred to ``b``'s
        # group, snapped against ``b``'s edge.  Dock partner is ``b``.
        _set_cell_dock(a, b)
        _log(
            f"Case 4 (transfer): {a._id[:8]} from {src_master_id[:8]} "
            f"to {tgt_master_id[:8]}"
        )
        # Close old master if it now has fewer than 2 members.
        # V3 v0.3.17 — DO NOT repack remaining members of the old
        # master; per user contract, the survivors stay where they
        # are.  The new master also doesn't repack — ``a`` already
        # sits at the snap-committed edge of ``b``.
        if old_master is not None:
            _check_master_validity(old_master, registry)
        return

    # ---- Case 2: tgt in group, src standalone ------------------------------
    if tgt_master_id is not None and src_master_id is None:
        master = registry.get(tgt_master_id)
        if master is not None:
            _adopt_member_geometry(a, master)
            master._members[a._id] = QPoint(a.pos())
            master._positioned.add(a._id)
            master._dock_partners.add(a._id)
            a._group_master_id = tgt_master_id
            a._link_parent_id = tgt_master_id  # v0.8.0 P1 mirror
            a._docked_to.clear()
            _update_docked_to(a, b, registry)
            a.update()  # Bug 5: refresh outline colour (now associated)
            if not master.isVisible():
                master.show()
            # V3 v0.3.17 — DO NOT repack.  ``a`` arrives at the
            # snap-committed edge of ``b``; existing members of
            # the ring keep their positions.
            master._ring_dirty = True
            # v0.8.0 P3 — write the dock relationship.  ``a`` was
            # snapped against ``b``'s edge by the snap engine, so the
            # dock partner is ``b`` (not the master).  This is the
            # chain-dock case the user described.
            _set_cell_dock(a, b)
        _log(f"Case 2 (src joins tgt group): {a._id[:8]} -> group {tgt_master_id[:8]}")
        return

    # ---- Case 3: src in group, tgt standalone ------------------------------
    if src_master_id is not None and tgt_master_id is None:
        master = registry.get(src_master_id)
        if master is not None:
            _adopt_member_geometry(b, master)
            master._members[b._id] = QPoint(b.pos())
            master._positioned.add(b._id)
            master._dock_partners.add(b._id)
            b._group_master_id = src_master_id
            b._link_parent_id = src_master_id  # v0.8.0 P1 mirror
            b._docked_to.clear()
            _update_docked_to(a, b, registry)
            b.update()  # Bug 5: refresh outline colour (now associated)
            if not master.isVisible():
                master.show()
            # V3 v0.3.17 — DO NOT repack (same rationale as Case 2).
            master._ring_dirty = True
            # v0.8.0 P3 — Case 3 mirror of Case 2: ``b`` is the cell
            # that got pulled into ``a``'s group; ``a`` is its dock
            # partner.
            _set_cell_dock(b, a)
        _log(f"Case 3 (tgt joins src group): {b._id[:8]} -> group {src_master_id[:8]}")
        return

    # ---- Case 1: both standalone — fresh master -----------------------------
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
        _log(f"_try_spawn_master: no adjacent-to-both cell — using centroid fallback")
        cand_x, cand_y = _honeycomb_master_pos({a._id, b._id}, hex_size, registry, avail)

    # Create the master.
    master = CellWindow(
        a._branding,
        role="master",
        source_a_id=a._id,
        source_b_id=b._id,
        hexagon_id=master_id,
    )
    # v0.8.0a1+ramps Bug 8 — give the fresh ring a session-unique
    # auto-name ("Ring 1", "Ring 2", …) so the user can tell rings
    # apart in the menu header / hover tooltip before they save or
    # bind a catalog.  Cleared whenever the ring is later bound to
    # a file (the file's stem takes over).
    master._auto_ring_name = f"Ring {_next_ring_serial()}"
    # Master inherits the source cells' shape, orientation, and size so the
    # whole group renders identically.  ``a`` and ``b`` already share these
    # values (Rule 3 in SnapEngine rejects cross-shape pairs), but their
    # ``size_px`` may differ — pick the larger so neither source is forced
    # to shrink at the moment of docking.
    group_size_px = max(a._size_px, b._size_px)
    master._apply_shape_self(a._shape, a._orientation)
    master._apply_size_self(group_size_px)
    if a._size_px != group_size_px:
        a._apply_size_self(group_size_px)
    if b._size_px != group_size_px:
        b._apply_size_self(group_size_px)
    master.move_to(cand_x, cand_y)

    # v0.6.14 — capture prior forest-link state BEFORE reassigning
    # ``_group_master_id`` so we can promote the new ring to a
    # forest member if either source cell was forest-linked.  The
    # user spec: two forest-linked cells dragged together form a
    # ring that itself stays forest-linked; the cells become normal
    # ring members under that new ring.
    _a_prior_group = a._group_master_id
    _b_prior_group = b._group_master_id

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
    a._link_parent_id = master_id  # v0.8.0 P1 mirror
    b._group_master_id = master_id
    b._link_parent_id = master_id  # v0.8.0 P1 mirror
    a._docked_to.clear()
    b._docked_to.clear()
    _update_docked_to(a, b, registry)

    # Bug 5: refresh outline colour — both are now associated; green â†’ normal.
    a.update()
    b.update()

    # Shim: update _dock_partners on sources so SnapEngine's dock_group_of
    # (which still uses the registry's shim) excludes them from snap candidates.
    a._dock_partners.add(master_id)
    b._dock_partners.add(master_id)

    master.show()
    try:
        # Macify: the master glides into existence when two cells dock.
        master._fade_in()
    except Exception:  # noqa: BLE001
        pass
    # v0.8.0a1 — wire the freshly-spawned master to the snap engine
    # so the snap-preview overlay shows when the user drags the new
    # ring as a source.  ``ring_io.load_ring`` already wires loaded
    # masters; ``_try_spawn_master`` is the dynamic-spawn path that
    # was missing the wire — the master could be dragged (attach_drag
    # fires) but the ``snapPreview`` signal had no listener whose
    # ``listening_hex._id`` matched the master's id, so the preview
    # overlay never fired.  User-reported symptom: "Docking the ring
    # to a cell or forest does work, but it doesn't outline the
    # docking area like the cells do (it should)."
    try:
        from scriptree.shell.ring_main import _wire_hex_to_snap
        _wire_hex_to_snap(master)
    except Exception as exc:  # noqa: BLE001
        _log(
            f"_try_spawn_master: snap-engine wire for master {master_id[:8]} "
            f"failed: {exc!r} — drag-snap preview will not show for this ring"
        )
    # Canonicalise positions: both sources adopt their nearest free
    # honeycomb slots around the master so a non-canonical drag-release
    # (e.g. dropped slightly off-slot) snaps to a clean ring layout.
    master._repack_members()

    # v0.8.0 P3 — Case 1 dock writes (v0.8.0a1+ramps Bug 6 fix:
    # use the TARGET centre stored in master._members so the dock
    # edge resolves even while the cells are still smooth-moving
    # toward their final slot positions).  A fresh master was
    # placed at a honeycomb slot adjacent to BOTH ``a`` and ``b``;
    # _repack_members above started an animated slide of ``a`` and
    # ``b`` to those slots.  Reading ``child.geometry()`` here
    # returns the stale pre-animation pixel position (often ≥ 4 px
    # off from the slot centre) and ``_set_cell_dock``'s 4 px
    # tolerance would silently leave the dock pointer unset —
    # then the master.move_to cascade (Bug 4) wouldn't carry these
    # members when the ring docked elsewhere ("ring left its
    # linked cells behind").  Passing the target centre via the
    # ``child_centre`` kwarg sidesteps the animation race.
    for src_cell in (a, b):
        home = master._members.get(src_cell._id)
        if home is None:
            _set_cell_dock(src_cell, master)
            continue
        tgt_cx = home.x() + src_cell._size_px / 2.0
        tgt_cy = home.y() + src_cell._size_px / 2.0
        _set_cell_dock(src_cell, master, child_centre=(tgt_cx, tgt_cy))
    # v0.6.12 — fresh master + ring must not overlap any cell that
    # already lived on screen before the dock fired.
    try:
        master._settle_no_overlap()
    except Exception as exc:  # noqa: BLE001
        _log(f"_settle_no_overlap (try_spawn_master) raised {exc!r}")
    # Fresh master = brand-new ring with content but no on-disk file
    # → dirty (so close prompts to save).
    master._ring_dirty = True

    # v0.6.17 — give the bare new ring hub the dedicated "ring"
    # glyph (concentric circles).  ``load_ring`` already does this
    # for *loaded* rings, but a ring spawned by drag-docking two
    # cells doesn't go through load_ring — so without this block
    # the ring rendered as just the centre dot (no icon).
    try:
        bare = (
            not getattr(master, "_catalog_path", None)
            and not getattr(master, "_icon_data_b64", "")
            and not getattr(master, "_icon_path", None)
        )
        if bare:
            from scriptree.shell.icon_assets import (
                BUNDLED_FORMAT, bundled_icon_b64,
            )
            b64 = (
                bundled_icon_b64("ring")
                or bundled_icon_b64("container")
            )
            if b64:
                master._icon_data_b64 = b64
                master._icon_data_format = BUNDLED_FORMAT
                master.update()
    except Exception as exc:  # noqa: BLE001
        _log(f"_try_spawn_master: bare-hub icon failed: {exc!r}")

    # v0.6.14 — preserve the forest link.  If either source cell
    # had been a forest member that was dragged free (break-free
    # preserves _group_master_id; see _break_free_from_cluster),
    # promote the new ring to a forest member so the cluster
    # stays bonded to the workspace root.  Symmetric: the cells
    # are now ring members (their direct forest link is gone,
    # transitively under the ring), and the ring takes the forest
    # slot.
    forest_id_for_link: str | None = None
    for prior in (_a_prior_group, _b_prior_group):
        if prior is None:
            continue
        prior_cell = registry.get(prior)
        if prior_cell is not None and getattr(
            prior_cell, "_is_forest_master", False,
        ):
            forest_id_for_link = prior
            break
    if forest_id_for_link is not None:
        forest = registry.get(forest_id_for_link)
        if forest is not None and forest._id != master_id:
            try:
                forest._members[master._id] = QPoint(master.pos())
                # v0.8.0a1+ramps Bug 7 — do NOT add the fresh ring to
                # forest._positioned / forest._dock_partners.  Those
                # two sets are the forest cascade's dock-path gate,
                # and the new ring sits wherever the two source
                # cells happened to dock — typically NOT at a slot
                # adjacent to the forest cluster.  Per the user
                # spec ("once I make a ring that is not docked to
                # the forest cluster it [shouldn't] move when I
                # move the forest"), a loose-linked ring is link-
                # attached only.  If the user later docks this ring
                # to the forest cluster, the snap-commit path adds
                # it to _positioned then.
                #
                # User-reported symptom of the prior (wrong) write:
                # "the separated ring still drags when forest drags
                # but only under this specific condition: I drag a
                # cell away from the group, then I drag another cell
                # from the group directly to dock with the other
                # cell and form a ring."
                master._group_master_id = forest_id_for_link
                master._link_parent_id = forest_id_for_link  # v0.8.0 P1 mirror
                # Drop the two source cells from forest's direct
                # membership — they're now reachable via the new
                # ring.  Membership change → forest dirty.
                forest._members.pop(a._id, None)
                forest._members.pop(b._id, None)
                forest._positioned.discard(a._id)
                forest._positioned.discard(b._id)
                forest._dock_partners.discard(a._id)
                forest._dock_partners.discard(b._id)
                forest._ring_dirty = True
                forest.update()  # refresh badge / count
                _log(
                    f"forest-link preserved: new ring {master_id[:8]} "
                    f"promoted to forest {forest._id[:8]} link-child "
                    f"(NOT dock-positioned); sources {a._id[:8]} + "
                    f"{b._id[:8]} now ring members under that ring"
                )
            except Exception as exc:  # noqa: BLE001
                _log(
                    f"_try_spawn_master: forest-link promotion "
                    f"failed: {exc!r}"
                )

    _log(f"Master spawned: {master_id[:20]} at ({cand_x},{cand_y})")
    registry.masterSpawned.emit(master_id, a._id, b._id)


def _adopt_member_geometry(member: CellWindow, master: CellWindow) -> None:
    """Force ``member`` to take on ``master``'s shape / orientation / size.

    Called from every dock case (Cases 2/3/4/5) before the member is
    wired into the master's ``_members`` dict.  Repack runs afterwards
    so the position is recomputed at the now-uniform size.

    Rule 3 in SnapEngine already guarantees matching shape and
    orientation at snap-commit time, but a future relaxation
    (cross-shape grouping) would land this routine on a real cross-
    shape adoption — the helper does the right thing either way.
    """
    if member is master:
        return  # Defensive — masters never adopt from themselves.
    if (
        member._shape != master._shape
        or member._orientation != master._orientation
    ):
        member._apply_shape_self(master._shape, master._orientation)
    if member._size_px != master._size_px:
        member._apply_size_self(master._size_px)


def _update_docked_to(a: CellWindow, b: CellWindow, registry) -> None:
    """Record the bidirectional positional adjacency between a and b.

    Both a._docked_to and b._docked_to get each other's id added.
    """
    a._docked_to.add(b._id)
    b._docked_to.add(a._id)


def _member_offset_key(cell: "CellWindow") -> str | None:
    """Stable per-cell key for a hub's ``_remembered_offsets`` dict
    (v0.8.0a83): the cell's catalog/tree path, normalised (resolved, lower,
    forward-slashes) the SAME way ``forest_controller._norm`` normalises
    ``ForestItem.path`` / keys ``_spawned``.

    Keying by PATH (not the runtime cell id, which regenerates every spawn)
    is what lets a remembered offset persist in the ``.scriptreeforest`` and
    rebind to whatever cell holds that tool/tree path next session.  Returns
    ``None`` when the cell has no catalog path — such a cell is never
    remembered and is always engine-tiled.
    """
    cp = getattr(cell, "_catalog_path", None)
    if not cp:
        return None
    try:
        from pathlib import Path as _P
        return str(_P(cp).resolve()).lower().replace("\\", "/")
    except (OSError, ValueError, RuntimeError):
        return str(cp).lower().replace("\\", "/")


def _check_undock(moved_hex: CellWindow) -> None:
    """Called when a hex moves; checks if it has drifted far enough to leave cluster.

    Amendment 2: uses _docked_to (positional adjacency) rather than _dock_partners.
    Drift detection removes the hex from the cluster (_docked_to, master._positioned)
    but does NOT remove it from the group (_group_master_id, master._members).

    The master is closed only when len(master._members) < 2 via
    _check_master_validity (not here — drift just breaks position, not membership).
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

    Uses len(master._members) — not dock_partners, not home_positions count.
    Called after a member explicitly leaves the group (not on cluster break-free,
    which preserves membership).
    """
    if master.role != "master":
        return

    # V3 v0.3.15+ — the forest cell is a master that persists even
    # with zero members.  It's the workspace root, not a transient
    # docking artefact, so the quorum-close rule must NOT apply.
    if getattr(master, "_is_forest_master", False):
        _log(
            f"_check_master_validity {master._id[:8]}: forest master, "
            f"skipping quorum check (member_count={len(master._members)})"
        )
        return

    member_count = len(master._members)

    _log(
        f"_check_master_validity {master._id[:8]}: "
        f"member_count={member_count} (need >= 2)"
    )

    # v0.8.0 — auto-close on quorum-loss DISABLED.  Per the user:
    # "I think we should not remove them automatically anymore -
    # shake to close and have a box come up then to close, save
    # or cancel."  Rings now persist with 0 or 1 members.  Explicit
    # close gestures (shake on ring, context menu) will surface
    # the save prompt and handle teardown — that's a separate code
    # path.  Keeping the legacy quorum-loss save prompt below as
    # dead code commented out for reference; if you uncomment,
    # restore the `if member_count < 2:` outer condition too.
    if False and member_count < 2:
        if (
            master._ring_needs_save_prompt()
            and member_count >= 1  # something to save
        ):
            from PySide6.QtWidgets import QMessageBox
            saved_path = getattr(master, "_saved_ring_path", None)
            if saved_path is None:
                msg = (
                    "This ring has not been saved and is about to "
                    "close because too few members remain.\n\n"
                    "Save it before closing?"
                )
            else:
                msg = (
                    f"This ring has unsaved changes since it was "
                    f"last saved to '{saved_path.name if hasattr(saved_path, 'name') else saved_path}'. "
                    "It is about to close because too few members "
                    "remain.\n\nSave the changes before closing?"
                )
            reply = QMessageBox.question(
                None,
                "Unsaved ring closing",
                msg,
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard,
                QMessageBox.StandardButton.Save,
            )
            if reply == QMessageBox.StandardButton.Save:
                try:
                    master._save_ring_dialog()
                except Exception as exc:  # noqa: BLE001
                    _log(
                        f"_check_master_validity: save-prompt save "
                        f"failed: {exc!r} — proceeding to teardown"
                    )

        # Clear group membership for any remaining members.
        from scriptree.shell.cell_registry import CellRegistry
        reg = CellRegistry.instance()
        for member_id in list(master._members.keys()):
            member = reg.get(member_id)
            if member is not None:
                member._group_master_id = None
                member._link_parent_id = None  # v0.8.0 P1 mirror
                member._docked_to.clear()
                member._dock_partners.clear()
                member.update()  # Bug 5: refresh outline (now unassociated → green)
        master._members.clear()
        master._positioned.clear()
        master._dock_partners.clear()
        # V3 v0.3.8 fix — close the master fully (was: hide()).  Pre-fix
        # the master was only hidden, so the registry kept it under the
        # deterministic master_id.  Re-docking the original pair would
        # compute the same id; ``CellRegistry.register`` short-circuits
        # on the duplicate id and the new master never registers,
        # leaving the user unable to "reassociate them again and get a
        # respawned ring".  ``close()`` triggers ``closeEvent`` →
        # ``unregister`` → emits ``masterDespawned`` and frees the id
        # for a future spawn.
        reg.masterDespawned.emit(master._id)
        _log(
            f"Master {master._id[:8]} closing — "
            f"only {member_count} member(s) remain"
        )
        master.close()

