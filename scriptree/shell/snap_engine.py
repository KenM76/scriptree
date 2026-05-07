"""
snap_engine.py â€” SnapEngine: continuous 60 Hz honeycomb-strict snap detection.

Architecture: ADR-001 Â§sub-decision-3 (superseding Amendment 1).
Platform: Win11 primary (uses QTimer in the Qt event loop â€” no threads).

Algorithm summary (honeycomb-strict, Rule 2)
---------------------------------------------
On drag-attach:
  - A QTimer fires at 16 ms (~60 Hz).
  - Each tick: for the dragging hex D, compute D's centre in screen coords.
  - For each other registered hex T (not in D's dock group):
    - Compute T's 6 honeycomb-neighbour slot centres.
    - If D's centre is within snap_distance_px of any slot, record candidate.
  - Pick nearest candidate across all targets.
  - Emit snapPreview(source_id, target_id, "edge", geom) while candidate exists.
  - On drag-end (detach_drag): commit â€” move D to the exact slot top-left.

Why position-snap rather than edge-midpoint matching
-----------------------------------------------------
The previous engine matched edge midpoints with normal-vector anti-parallelism.
This required a 15Â° tolerance and still fired for non-honeycomb arrangements
(e.g. edge touching vertex).  The new model is simpler:

  Two hexagons form a honeycomb pair iff D's centre == one of T's neighbour slots.

This is an exact geometric statement.  The snap threshold is the tolerance.
Vertex snap is GONE â€” no vertex-to-vertex path exists.  Two hexagons whose
vertices touch but whose edges do NOT share a full face will not snap.

Rule 3 â€” cross-shape / cross-orientation: if D._shape != T._shape or
D._orientation != T._orientation, no snap.  Honeycomb tiling requires identical
tiles.

Debug logging is rate-limited to at most once per second.
"""

from __future__ import annotations

import math
import sys
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QPointF, QTimer, Signal

if TYPE_CHECKING:
    from scriptree.shell.hexagon_registry import HexagonRegistry
    from scriptree.shell.hexagon_window import HexagonWindow


def _log(msg: str) -> None:
    print(f"[SnapEngine] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Honeycomb neighbour slot offsets (center-to-center, relative to target)
# ---------------------------------------------------------------------------
# For a FLAT-TOP hex of side length R = size_px/2:
#   Horizontal spacing between adjacent centres: 2 * R * cos(30Â°) = size_px * sqrt(3)/2
#     That is the flat-to-flat distance (= apothem * 2).  BUT for honeycomb the
#     off-axis pairs (NE/NW/SE/SW) have x-offset = R * 3/2 = size_px * 3/4 and
#     y-offset = R * sqrt(3)/2 = size_px * sqrt(3)/4.
#   N/S pairs (stacked vertically) share their horizontal flat edges:
#     y-offset = size_px * sqrt(3)/2  (flat-to-flat distance, full vertical step).
#
# Summary (flat-top, offsets as multiples of size_px):
#   N:  ( 0,           -sqrt(3)/2 )
#   S:  ( 0,           +sqrt(3)/2 )
#   NE: (+3/4,         -sqrt(3)/4 )
#   NW: (-3/4,         -sqrt(3)/4 )
#   SE: (+3/4,         +sqrt(3)/4 )
#   SW: (-3/4,         +sqrt(3)/4 )
#
# For POINTY-TOP: rotate the above offsets by 90Â°:
#   (x, y)  â†’  (-y, x)
#   E:  (+sqrt(3)/2,  0          )   â† was N rotated
#   W:  (-sqrt(3)/2,  0          )   â† was S rotated
#   NE: (+sqrt(3)/4,  -3/4       )   â† was NW rotated
#   SE: (+sqrt(3)/4,  +3/4       )   â† was SW rotated
#   NW: (-sqrt(3)/4,  -3/4       )   â† was NE rotated
#   SW: (-sqrt(3)/4,  +3/4       )   â† was SE rotated
#
# For SQUARE (4 neighbours, any orientation â€” same-orientation requirement applies):
#   N:  ( 0,  -1 )
#   S:  ( 0,  +1 )
#   E:  (+1,   0 )
#   W:  (-1,   0 )

_SQRT3_HALF  = math.sqrt(3) / 2   # â‰ˆ 0.8660
_SQRT3_QRTR  = math.sqrt(3) / 4   # â‰ˆ 0.4330

# Raw offsets as (dx_factor, dy_factor) Ã— size_px.
# Indices 0â€“5 match a clockwise ordering for readability; order doesn't matter.
_FLAT_TOP_OFFSETS: list[tuple[float, float]] = [
    ( 0.0,          -_SQRT3_HALF),   # N
    (+0.75,         -_SQRT3_QRTR),   # NE
    (+0.75,         +_SQRT3_QRTR),   # SE
    ( 0.0,          +_SQRT3_HALF),   # S
    (-0.75,         +_SQRT3_QRTR),   # SW
    (-0.75,         -_SQRT3_QRTR),   # NW
]

_POINTY_TOP_OFFSETS: list[tuple[float, float]] = [
    (+_SQRT3_HALF,   0.0),           # E
    (+_SQRT3_QRTR,  +0.75),          # SE
    (-_SQRT3_QRTR,  +0.75),          # SW
    (-_SQRT3_HALF,   0.0),           # W
    (-_SQRT3_QRTR,  -0.75),          # NW
    (+_SQRT3_QRTR,  -0.75),          # NE
]

_SQUARE_OFFSETS: list[tuple[float, float]] = [
    ( 0.0,  -1.0),   # N
    (+1.0,   0.0),   # E
    ( 0.0,  +1.0),   # S
    (-1.0,   0.0),   # W
]


def _neighbour_slot_centres(
    target_cx: float, target_cy: float,
    size_px: int,
    shape: str,
    orientation: str,
) -> list[tuple[float, float]]:
    """Return the 6 (or 4) honeycomb-neighbour centre positions for a target hex.

    All values in global screen logical pixels.
    """
    s = (shape or "hexagon").lower()
    if s == "hexagon":
        offsets = _FLAT_TOP_OFFSETS if orientation == "flat-top" else _POINTY_TOP_OFFSETS
    else:
        offsets = _SQUARE_OFFSETS

    return [
        (target_cx + ox * size_px, target_cy + oy * size_px)
        for ox, oy in offsets
    ]


# ---------------------------------------------------------------------------
# _SnapCandidate â€” internal result of one tick evaluation
# ---------------------------------------------------------------------------

class _SnapCandidate:
    __slots__ = (
        "source_id", "target_id",
        "distance",
        "slot_cx", "slot_cy",   # exact centre of the honeycomb slot to snap to
    )

    def __init__(
        self,
        source_id: str,
        target_id: str,
        distance: float,
        slot_cx: float,
        slot_cy: float,
    ) -> None:
        self.source_id = source_id
        self.target_id = target_id
        self.distance  = distance
        self.slot_cx   = slot_cx
        self.slot_cy   = slot_cy

    def top_left(self, size_px: int) -> tuple[int, int]:
        """Convert slot centre to window top-left."""
        return (
            round(self.slot_cx - size_px / 2),
            round(self.slot_cy - size_px / 2),
        )


# ---------------------------------------------------------------------------
# SnapEngine
# ---------------------------------------------------------------------------

class SnapEngine(QObject):
    """Continuous 60 Hz honeycomb-strict snap detection for dragging hexagons.

    Signals
    -------
    snapPreview(source_id, target_id, mode, preview_geometry)
        Fired every tick while a snap candidate is within threshold.
        mode is always 'edge' (honeycomb snap = full-edge share, no vertex snap).
        preview_geometry: dict with 'x','y','w','h' in global logical px.

    snapCommit(source_id, target_id, mode, snap_geometry)
        Fired once on drag-end if a preview was active.
        snap_geometry: same shape as preview_geometry.

    Design notes
    ------------
    - No edge-midpoint matching. No normal-vector math. No vertex snap.
    - Snap rule: D snaps to T iff D.centre is within snap_distance_px of any
      honeycomb-neighbour slot of T, AND D and T have the same shape and
      orientation (Rule 3 cross-shape/orientation guard).
    - Mode string is always 'edge' for downstream compatibility with
      _on_snap_commit (which gates master spawn on mode == 'edge').
    """

    snapPreview = Signal(str, str, str, dict)   # source_id, target_id, mode, geom
    snapCommit  = Signal(str, str, str, dict)   # source_id, target_id, mode, geom

    def __init__(self, registry: "HexagonRegistry", snap_distance_px: int) -> None:
        super().__init__()
        self._registry = registry
        self._snap_px  = snap_distance_px

        # Maps hex_id â†’ best _SnapCandidate seen this tick.
        self._active_previews: dict[str, _SnapCandidate] = {}

        # Set of hex_ids currently being dragged.
        self._dragging: set[str] = set()

        # Position cache: hex_id â†’ (cx, cy, size_px, shape, orientation)
        # Invalidated by hexagonMoved (source only) and hexagonReshaped (any).
        self._cache: dict[str, tuple[float, float, int, str, str]] = {}

        # Timer â€” fires at 16 ms (~60 Hz).
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

        # Rate-limited debug log state.
        self._last_log_time: float = 0.0
        self._last_tick_log_time: float = 0.0

        # Bug A fix â€” Belt: single-fire commit guard.
        # Cleared at attach_drag; set immediately before snapCommit.emit.
        self._committed_ids: set[str] = set()

        # Wire registry signals for cache invalidation.
        registry.hexagonReshaped.connect(self._invalidate_cache)
        registry.hexagonMoved.connect(self._invalidate_source_cache)
        registry.hexagonClosed.connect(self._on_hex_closed)

    # ---- Cache management --------------------------------------------------

    def _invalidate_cache(self, hex_id: str) -> None:
        self._cache.pop(hex_id, None)

    def _invalidate_source_cache(self, hex_id: str) -> None:
        """Invalidate only the moved hex (targets are stationary)."""
        self._cache.pop(hex_id, None)

    def _on_hex_closed(self, hex_id: str) -> None:
        self._cache.pop(hex_id, None)
        self._dragging.discard(hex_id)
        self._active_previews.pop(hex_id, None)
        if not self._dragging and self._timer.isActive():
            self._timer.stop()

    def _get_pos(self, hex_win: "HexagonWindow") -> tuple[float, float, int, str, str]:
        """Return (cx, cy, size_px, shape, orientation) from cache or fresh."""
        hid = hex_win._id
        if hid not in self._cache:
            geo = hex_win.geometry()
            cx = geo.x() + geo.width()  / 2.0
            cy = geo.y() + geo.height() / 2.0
            self._cache[hid] = (cx, cy, hex_win._size_px, hex_win._shape, hex_win._orientation)
        return self._cache[hid]

    # ---- Drag lifecycle ----------------------------------------------------

    def attach_drag(self, hex_id: str) -> None:
        """Called when a hex starts being dragged."""
        self._dragging.add(hex_id)
        self._active_previews.pop(hex_id, None)
        self._committed_ids.discard(hex_id)  # Bug A fix
        if not self._timer.isActive():
            self._timer.start()
        _log(
            f"attach_drag({hex_id[:8]}) â€” "
            f"dragging={[h[:8] for h in self._dragging]} "
            f"timer_active={self._timer.isActive()}"
        )

    def detach_drag(self, hex_id: str) -> None:
        """Called when a hex drag ends. Commits snap if preview was active.

        Bug A fix â€” Belt: _committed_ids prevents a double-commit if
        detach_drag is called re-entrantly during the snap-nudge move_to().
        """
        _log(
            f"detach_drag({hex_id[:8]}) â€” "
            f"preview_active={hex_id in self._active_previews} "
            f"already_committed={hex_id in self._committed_ids} "
            f"previews={[k[:8] for k in self._active_previews]}"
        )
        self._dragging.discard(hex_id)

        if hex_id in self._committed_ids:
            _log(f"detach_drag({hex_id[:8]}) â€” already committed this drag, skipping")
            self._active_previews.pop(hex_id, None)
            if not self._dragging and self._timer.isActive():
                self._timer.stop()
            return

        candidate = self._active_previews.pop(hex_id, None)
        if candidate is not None:
            src = self._registry.get(candidate.source_id)
            if src is not None:
                new_x, new_y = candidate.top_left(src._size_px)
                src.move_to(new_x, new_y)
                geo = src.geometry()
                snap_geom = {
                    "x": geo.x(), "y": geo.y(),
                    "w": geo.width(), "h": geo.height(),
                }
                _log(
                    f"snapCommit emit: {candidate.source_id[:8]} â†’ "
                    f"{candidate.target_id[:8]} at ({new_x},{new_y})"
                )
                self._committed_ids.add(hex_id)  # mark BEFORE emit (Bug A)
                self.snapCommit.emit(
                    candidate.source_id,
                    candidate.target_id,
                    "edge",
                    snap_geom,
                )
            else:
                _log(
                    f"detach_drag: source {candidate.source_id[:8]} not in registry "
                    f"â€” snapCommit skipped"
                )
        else:
            _log(f"detach_drag({hex_id[:8]}) â€” no preview active, no commit")

        if not self._dragging and self._timer.isActive():
            self._timer.stop()
        _log(
            f"detach_drag({hex_id[:8]}) done â€” "
            f"dragging now={[h[:8] for h in self._dragging]}"
        )

    # ---- 60 Hz tick --------------------------------------------------------

    def _tick(self) -> None:
        """Evaluate honeycomb snap candidates for all dragging hexagons."""
        now = time.monotonic()

        if now - self._last_tick_log_time >= 1.0 and self._dragging:
            _log(
                f"_tick dragging={[h[:8] for h in self._dragging]} "
                f"previews={len(self._active_previews)}"
            )
            self._last_tick_log_time = now

        for src_id in list(self._dragging):
            src = self._registry.get(src_id)
            if src is None:
                self._dragging.discard(src_id)
                continue

            # Always recompute dragging hex position (it moves every tick).
            self._cache.pop(src_id, None)
            src_cx, src_cy, src_size, src_shape, src_orient = self._get_pos(src)

            # Skip committed drags (belt guard â€” shouldn't fire mid-drag but defensive).
            if src_id in self._committed_ids:
                continue

            # Bug 1 fix â€” snap-back-to-own-group:
            # Do NOT exclude the dragging hex's own group members from snap
            # candidates.  Excluding them (the old behaviour) prevented a
            # separated member from snapping back onto its own master's cluster.
            # We exclude ONLY the dragging hex itself (handled by others()).
            # When the separated source snaps to a positioned member of its
            # own master's cluster, _try_spawn_master's Case 5 path re-adds
            # it to master._positioned, completing the rejoin.

            best: _SnapCandidate | None = None

            for tgt in self._registry.others(src_id):
                # (No group-membership filter here â€” see Bug 1 fix comment above.)

                # Bug 2 fix â€” master-of-master guard:
                # Masters are anchors, not honeycomb cells; they have no
                # edges to dock to.  Allowing a master as a snap target
                # causes _try_spawn_master(src, master) to run, which either
                # absorbs the master as a member or spawns a second master
                # between them â€” both paths are wrong.  Skip all masters.
                if tgt.role == "master":
                    continue

                # Rule 3: cross-shape/orientation â†’ no snap.
                if tgt._shape != src_shape or tgt._orientation != src_orient:
                    continue

                tgt_cx, tgt_cy, tgt_size, _tshape, _torient = self._get_pos(tgt)

                # Quick reject: bounding-box distance check.
                coarse_dist = math.hypot(src_cx - tgt_cx, src_cy - tgt_cy)
                max_slot_reach = tgt_size * _SQRT3_HALF + self._snap_px
                if coarse_dist > max_slot_reach + tgt_size:
                    continue

                # Compute all 6 (or 4) neighbour slot centres for target.
                slots = _neighbour_slot_centres(
                    tgt_cx, tgt_cy, tgt_size, tgt._shape, tgt._orientation
                )

                for slot_cx, slot_cy in slots:
                    d = math.hypot(src_cx - slot_cx, src_cy - slot_cy)
                    if d <= self._snap_px:
                        if best is None or d < best.distance:
                            best = _SnapCandidate(
                                source_id=src_id,
                                target_id=tgt._id,
                                distance=d,
                                slot_cx=slot_cx,
                                slot_cy=slot_cy,
                            )

            # ---- Emit preview or clear -------------------------------------
            if best is not None:
                self._active_previews[src_id] = best
                tl_x, tl_y = best.top_left(src._size_px)
                geo = src.geometry()
                preview_geom = {
                    "x": tl_x,
                    "y": tl_y,
                    "w": geo.width(),
                    "h": geo.height(),
                }
                if now - self._last_log_time >= 1.0:
                    _log(
                        f"snapPreview emit: {best.source_id[:8]}â†’{best.target_id[:8]} "
                        f"dist={best.distance:.1f}px slot=({best.slot_cx:.0f},{best.slot_cy:.0f})"
                    )
                    self._last_log_time = now
                self.snapPreview.emit(
                    best.source_id, best.target_id, "edge", preview_geom
                )
            else:
                self._active_previews.pop(src_id, None)

