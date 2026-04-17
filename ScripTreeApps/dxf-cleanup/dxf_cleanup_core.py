"""
DXF Cleanup for Plasma Cutting
Processes a raw SolidWorks DXF export to produce a plasma-ready profile.

Usage: py -3.12 dxf_cleanup.py <input_raw.dxf> <output.dxf>
Exit:  0=success  1=error  2=success-with-warnings
"""

import sys
import math
import ezdxf
from collections import defaultdict

# --- Constants (defaults for inches, adjusted by --unit flag) ---
TOL = 0.001         # Coordinate matching tolerance
KERF_MIN = 0.060    # Minimum plasma kerf width
ANGLE_TOL = 0.01    # Degrees, for arc angle comparison
TWO_PI = 2.0 * math.pi
DXF_INSUNITS = 1    # $INSUNITS value for the output DXF
UNIT_LABEL = "in"   # Label for PDF/reports

# SolidWorks swLengthUnit_e -> ($INSUNITS, TOL, KERF_MIN, label)
UNIT_MAP = {
    0: (4,  0.025,   1.5,    "mm"),     # swMM
    1: (5,  0.0025,  0.15,   "cm"),     # swCM
    2: (6,  0.00003, 0.0015, "m"),      # swMETER
    3: (1,  0.001,   0.060,  "in"),     # swINCHES
    4: (2,  0.00008, 0.005,  "ft"),     # swFEET
    5: (1,  0.001,   0.060,  "in"),     # swFEETINCHES (exports as inches)
}


def configure_units(sw_unit_code):
    """Set module-level constants based on SolidWorks unit code."""
    global TOL, KERF_MIN, DXF_INSUNITS, UNIT_LABEL
    if sw_unit_code in UNIT_MAP:
        DXF_INSUNITS, TOL, KERF_MIN, UNIT_LABEL = UNIT_MAP[sw_unit_code]
    else:
        # Unknown unit — default to inches
        DXF_INSUNITS, TOL, KERF_MIN, UNIT_LABEL = UNIT_MAP[3]

# --- Point registry (cluster-based snapping) ---

class PointRegistry:
    """Cluster-based point snapping. Avoids grid-boundary artifacts."""
    def __init__(self, tol):
        self.tol = tol
        self.points = []

    def snap(self, x, y):
        """Return the canonical point for (x, y). Reuses existing nearby point."""
        for px, py in self.points:
            if abs(x - px) < self.tol and abs(y - py) < self.tol:
                return (px, py)
        pt = (round(x, 6), round(y, 6))
        self.points.append(pt)
        return pt

# Module-level registry, reset per main() call
_registry = PointRegistry(TOL)

# --- Helpers ---

def snap_pt(x, y):
    """Snap a 2D point using the cluster registry."""
    return _registry.snap(x, y)

def pts_equal(a, b):
    """Check if two 2D points are equal within tolerance."""
    return abs(a[0] - b[0]) < TOL and abs(a[1] - b[1]) < TOL

def dist(a, b):
    """Distance between two 2D points."""
    return math.hypot(a[0] - b[0], a[1] - b[1])

def normalize_angle(a):
    """Normalize angle to [0, 2*pi)."""
    a = a % TWO_PI
    if a < 0:
        a += TWO_PI
    return a

def arc_endpoint(cx, cy, r, angle_deg):
    """Compute endpoint of an arc at a given angle (degrees)."""
    rad = math.radians(angle_deg)
    return (cx + r * math.cos(rad), cy + r * math.sin(rad))


# --- Entity wrapper ---

class Ent:
    """Unified wrapper for LINE, ARC, CIRCLE entities."""
    def __init__(self, etype, data, original=None):
        self.etype = etype  # 'LINE', 'ARC', 'CIRCLE'
        self.data = data    # dict of geometric data
        self.original = original  # ezdxf entity reference
        self.used = False   # for loop tracing

    def start_pt(self):
        if self.etype == 'LINE':
            return snap_pt(self.data['sx'], self.data['sy'])
        elif self.etype == 'ARC':
            return snap_pt(*arc_endpoint(
                self.data['cx'], self.data['cy'], self.data['r'], self.data['sa']))
        return None

    def end_pt(self):
        if self.etype == 'LINE':
            return snap_pt(self.data['ex'], self.data['ey'])
        elif self.etype == 'ARC':
            return snap_pt(*arc_endpoint(
                self.data['cx'], self.data['cy'], self.data['r'], self.data['ea']))
        return None

    def length(self):
        if self.etype == 'LINE':
            return dist((self.data['sx'], self.data['sy']),
                        (self.data['ex'], self.data['ey']))
        elif self.etype == 'ARC':
            sweep = self.data['ea'] - self.data['sa']
            if sweep < 0:
                sweep += 360.0
            return abs(math.radians(sweep)) * self.data['r']
        elif self.etype == 'CIRCLE':
            return TWO_PI * self.data['r']
        return 0

    def departure_angle(self, from_pt):
        """Compute the departure angle (radians) when leaving from from_pt."""
        if self.etype == 'LINE':
            sp = self.start_pt()
            ep = self.end_pt()
            if pts_equal(from_pt, sp):
                return math.atan2(ep[1] - sp[1], ep[0] - sp[0])
            else:
                return math.atan2(sp[1] - ep[1], sp[0] - ep[0])
        elif self.etype == 'ARC':
            cx, cy, r = self.data['cx'], self.data['cy'], self.data['r']
            sp = self.start_pt()
            # DXF arcs go counterclockwise
            if pts_equal(from_pt, sp):
                # Forward: tangent is 90 deg CCW from radius at start
                rx, ry = from_pt[0] - cx, from_pt[1] - cy
                return math.atan2(rx, -ry)  # (-ry, rx) rotated for tangent
            else:
                # Reverse: tangent is 90 deg CW from radius at end
                rx, ry = from_pt[0] - cx, from_pt[1] - cy
                return math.atan2(-rx, ry)  # (ry, -rx)
        return 0

    def arrival_angle(self, at_pt):
        """Compute the arrival angle (radians) when arriving at at_pt."""
        if self.etype == 'LINE':
            sp = self.start_pt()
            ep = self.end_pt()
            if pts_equal(at_pt, ep):
                return math.atan2(ep[1] - sp[1], ep[0] - sp[0])
            else:
                return math.atan2(sp[1] - ep[1], sp[0] - ep[0])
        elif self.etype == 'ARC':
            cx, cy = self.data['cx'], self.data['cy']
            sp = self.start_pt()
            if pts_equal(at_pt, self.end_pt()):
                # Forward arrival: tangent at end is CCW from radius
                rx, ry = at_pt[0] - cx, at_pt[1] - cy
                return math.atan2(rx, -ry)
            else:
                # Reverse arrival at start
                rx, ry = at_pt[0] - cx, at_pt[1] - cy
                return math.atan2(-rx, ry)
        return 0

    def other_pt(self, from_pt):
        """Get the other endpoint."""
        sp = self.start_pt()
        ep = self.end_pt()
        if pts_equal(from_pt, sp):
            return ep
        return sp

    def center(self):
        if self.etype in ('ARC', 'CIRCLE'):
            return snap_pt(self.data['cx'], self.data['cy'])
        return None

    def radius(self):
        if self.etype in ('ARC', 'CIRCLE'):
            return self.data['r']
        return None

    def sig(self):
        """Signature for deduplication."""
        if self.etype == 'LINE':
            pts = sorted([self.start_pt(), self.end_pt()])
            return ('LINE', pts[0], pts[1])
        elif self.etype == 'ARC':
            return ('ARC', self.center(), round(self.data['r'] / TOL),
                    round(self.data['sa'] / ANGLE_TOL),
                    round(self.data['ea'] / ANGLE_TOL))
        elif self.etype == 'CIRCLE':
            return ('CIRCLE', self.center(), round(self.data['r'] / TOL))
        return None


# --- Parsing ---

def parse_dxf(filepath):
    """Parse a DXF file, return lists of Ent wrappers and warnings."""
    doc = ezdxf.readfile(filepath)
    msp = doc.modelspace()

    lines_arcs = []
    circles = []
    warnings = []
    skipped = 0

    for e in msp:
        etype = e.dxftype()

        # Filter hidden/dashed linetypes
        lt = (e.dxf.linetype or '').upper()
        if lt in ('HIDDEN', 'HIDDEN2', 'DASHED', 'DASHDOT', 'CENTER', 'PHANTOM'):
            skipped += 1
            continue

        if etype == 'LINE':
            sx, sy = e.dxf.start.x, e.dxf.start.y
            ex, ey = e.dxf.end.x, e.dxf.end.y
            ent = Ent('LINE', {'sx': sx, 'sy': sy, 'ex': ex, 'ey': ey}, e)
            lines_arcs.append(ent)

        elif etype == 'ARC':
            cx, cy = e.dxf.center.x, e.dxf.center.y
            r = e.dxf.radius
            sa = e.dxf.start_angle
            ea = e.dxf.end_angle
            ent = Ent('ARC', {'cx': cx, 'cy': cy, 'r': r, 'sa': sa, 'ea': ea}, e)
            lines_arcs.append(ent)

        elif etype == 'CIRCLE':
            cx, cy = e.dxf.center.x, e.dxf.center.y
            r = e.dxf.radius
            ent = Ent('CIRCLE', {'cx': cx, 'cy': cy, 'r': r}, e)
            circles.append(ent)

        else:
            warnings.append(f"Unexpected entity type: {etype}")
            skipped += 1

    if skipped > 0:
        warnings.append(f"Skipped {skipped} entities (hidden/dashed/unsupported)")

    return lines_arcs, circles, warnings


# --- Deduplication ---

def dedup(entities):
    """Remove duplicate entities based on geometric signature."""
    seen = set()
    result = []
    dupes = 0
    for e in entities:
        s = e.sig()
        if s not in seen:
            seen.add(s)
            result.append(e)
        else:
            dupes += 1
    return result, dupes


# --- Degenerate removal ---

def remove_degenerate(entities):
    """Remove zero-length lines, zero-sweep arcs, zero-radius circles."""
    result = []
    removed = 0
    for e in entities:
        if e.length() < TOL:
            removed += 1
        elif e.etype == 'CIRCLE' and e.data['r'] < TOL:
            removed += 1
        else:
            result.append(e)
    return result, removed


# --- Connectivity graph ---

def build_graph(entities):
    """Build adjacency list from LINE/ARC endpoints."""
    graph = defaultdict(list)  # node -> [(other_node, entity, direction)]
    for e in entities:
        sp = e.start_pt()
        ep = e.end_pt()
        if sp is None or ep is None:
            continue
        graph[sp].append((ep, e, 'fwd'))
        graph[ep].append((sp, e, 'rev'))
    return graph


# --- Outermost boundary tracing ---

def trace_outermost(graph, entities):
    """
    Trace the outermost boundary loop using the smallest-clockwise-turn rule.
    Returns list of (entity, direction) tuples forming the outer boundary.
    """
    if not graph:
        return []

    # Find leftmost node (on convex hull = guaranteed on outer boundary)
    start = min(graph.keys(), key=lambda p: (p[0], p[1]))

    # Initial incoming angle: pretend we arrived from the right (angle = pi)
    incoming_angle = math.pi

    loop = []
    current = start
    visited_edges = set()
    max_iters = len(entities) * 4  # safety limit

    for _ in range(max_iters):
        neighbors = graph[current]
        best_edge = None
        best_turn = float('inf')

        for (other, ent, direction) in neighbors:
            edge_id = id(ent)
            if edge_id in visited_edges:
                continue

            # Compute departure angle
            dep_angle = normalize_angle(ent.departure_angle(current))

            # Clockwise turn = incoming - departure (mod 2pi)
            turn = normalize_angle(incoming_angle - dep_angle)

            # Prevent U-turns from floating-point noise
            if turn < 0.001:
                turn = TWO_PI

            if turn < best_turn:
                best_turn = turn
                best_edge = (other, ent, direction)

        if best_edge is None:
            break  # Dead end (shouldn't happen for closed boundary)

        other, ent, direction = best_edge
        visited_edges.add(id(ent))
        ent.used = True
        loop.append((ent, direction))

        # Update incoming angle (arrival angle at the next node, then flip by pi)
        arr_angle = normalize_angle(ent.arrival_angle(other))
        incoming_angle = normalize_angle(arr_angle + math.pi)

        current = other
        if pts_equal(current, start) and len(loop) > 2:
            break  # Closed the loop

    return loop


# --- Find remaining hole loops ---

def trace_loop_from(graph, start_node, start_ent, start_dir):
    """Trace a closed loop starting from a specific unused edge."""
    incoming_angle = normalize_angle(
        start_ent.departure_angle(start_node) + math.pi)
    # Actually, we depart from start_node along start_ent
    dep_angle = normalize_angle(start_ent.departure_angle(start_node))
    other = start_ent.other_pt(start_node)

    loop = [(start_ent, start_dir)]
    start_ent.used = True
    visited_edges = {id(start_ent)}

    incoming_angle = normalize_angle(start_ent.arrival_angle(other) + math.pi)
    current = other

    max_iters = 500

    for _ in range(max_iters):
        if pts_equal(current, start_node) and len(loop) > 1:
            return loop  # Closed

        neighbors = graph[current]
        best_edge = None
        best_turn = float('inf')

        for (nb, ent, direction) in neighbors:
            if id(ent) in visited_edges:
                continue

            dep = normalize_angle(ent.departure_angle(current))
            turn = normalize_angle(incoming_angle - dep)
            if turn < 0.001:
                turn = TWO_PI

            if turn < best_turn:
                best_turn = turn
                best_edge = (nb, ent, direction)

        if best_edge is None:
            return None  # Dead end, not a closed loop

        nb, ent, direction = best_edge
        visited_edges.add(id(ent))
        ent.used = True
        loop.append((ent, direction))

        incoming_angle = normalize_angle(ent.arrival_angle(nb) + math.pi)
        current = nb

    return None  # Exceeded max iterations


def find_hole_loops(graph, entities):
    """Find all remaining closed loops from unused edges."""
    loops = []
    for ent in entities:
        if ent.used:
            continue
        sp = ent.start_pt()
        ep = ent.end_pt()
        if sp is None:
            continue

        loop = trace_loop_from(graph, sp, ent, 'fwd')
        if loop:
            loops.append(loop)

    return loops


# --- Concentric circle handling ---

def filter_concentric_circles(circles, has_line_boundary):
    """
    For circles sharing the same center, keep only the smallest.
    Returns (kept, removed, warnings).
    """
    groups = defaultdict(list)
    for c in circles:
        center = c.center()
        groups[center].append(c)

    kept = []
    removed = []
    warns = []

    for center, group in groups.items():
        if len(group) == 1:
            kept.append(group[0])
        elif len(group) == 2:
            group.sort(key=lambda c: c.radius())
            if has_line_boundary:
                # Keep smallest (through-hole), remove largest (countersink)
                kept.append(group[0])
                removed.append(group[1])
                warns.append(
                    f"Concentric circles at ({center[0]:.4f}, {center[1]:.4f}): "
                    f"kept R={group[0].radius():.4f}, removed R={group[1].radius():.4f} (countersink)")
            else:
                # Circle-only part: keep both (outer=boundary, inner=hole)
                kept.extend(group)
        else:
            # 3+ concentric: keep all, flag for review
            kept.extend(group)
            warns.append(
                f"REVIEW: {len(group)} concentric circles at ({center[0]:.4f}, {center[1]:.4f}) "
                f"radii: {[round(c.radius(), 4) for c in group]}")

    return kept, removed, warns


# --- Small feature detection ---

def check_small_features(circles, loops, kerf_min):
    """Warn about features smaller than plasma kerf width."""
    warns = []
    for c in circles:
        d = c.radius() * 2
        if d < kerf_min:
            warns.append(
                f"Small hole: R={c.radius():.4f} (dia={d:.4f}) < kerf {kerf_min:.3f}")

    for i, loop in enumerate(loops):
        for ent, _ in loop:
            if ent.etype == 'ARC' and ent.radius() < kerf_min / 2:
                warns.append(
                    f"Tight arc in loop {i}: R={ent.radius():.4f} < kerf/2 {kerf_min/2:.3f}")
    return warns


# --- Closure verification ---

def verify_loop_closure(loop):
    """Verify a loop is gap-free. Returns max gap distance."""
    if not loop:
        return 0

    max_gap = 0
    for i in range(len(loop)):
        ent_a, dir_a = loop[i]
        ent_b, dir_b = loop[(i + 1) % len(loop)]

        # End of current entity
        if dir_a == 'fwd':
            pt_a = ent_a.end_pt()
        else:
            pt_a = ent_a.start_pt()

        # Start of next entity
        if dir_b == 'fwd':
            pt_b = ent_b.start_pt()
        else:
            pt_b = ent_b.end_pt()

        if pt_a and pt_b:
            gap = dist(pt_a, pt_b)
            max_gap = max(max_gap, gap)

    return max_gap


# --- DXF output ---

def write_cleaned_dxf(output_path, outer_loop, hole_loops, kept_circles):
    """Write the cleaned entities to a new DXF file."""
    doc = ezdxf.new('R2000')
    msp = doc.modelspace()

    # Set units from document detection
    doc.header['$INSUNITS'] = DXF_INSUNITS

    def add_ent(ent):
        if ent.etype == 'LINE':
            msp.add_line(
                (ent.data['sx'], ent.data['sy']),
                (ent.data['ex'], ent.data['ey']),
                dxfattribs={'layer': '0'})
        elif ent.etype == 'ARC':
            msp.add_arc(
                center=(ent.data['cx'], ent.data['cy']),
                radius=ent.data['r'],
                start_angle=ent.data['sa'],
                end_angle=ent.data['ea'],
                dxfattribs={'layer': '0'})
        elif ent.etype == 'CIRCLE':
            msp.add_circle(
                center=(ent.data['cx'], ent.data['cy']),
                radius=ent.data['r'],
                dxfattribs={'layer': '0'})

    for ent, _ in outer_loop:
        add_ent(ent)
    for loop in hole_loops:
        for ent, _ in loop:
            add_ent(ent)
    for c in kept_circles:
        add_ent(c)

    doc.saveas(output_path)

    # Post-process: strip MATERIAL objects and ACAD_MATERIAL dictionary entries
    # from the saved file. These use group code 94 which AutoCAD LT 2004 can't parse.
    _strip_material_from_dxf(output_path)


def _strip_material_from_dxf(filepath):
    """Remove content that crashes AutoCAD LT 2004 from R2000 DXF files.
    Strips: MATERIAL entity blocks, MATERIAL CLASS definitions,
    ACAD_MATERIAL dictionary refs, and ALL group code 94 pairs.
    DXF files use alternating group-code / value line pairs — must advance by 2."""
    with open(filepath, 'r') as f:
        lines = f.readlines()

    out = []
    i = 0
    while i < len(lines) - 1:
        code = lines[i].strip()
        value = lines[i + 1].strip()

        # Skip MATERIAL entity blocks (group 0 / MATERIAL ... until next group 0)
        if code == '0' and value == 'MATERIAL':
            i += 2
            while i < len(lines) - 1:
                if lines[i].strip() == '0':
                    break
                i += 2
            continue

        # Skip MATERIAL CLASS definitions (group 0 / CLASS where group 1 = MATERIAL)
        if code == '0' and value == 'CLASS':
            # Peek ahead to check if group 1 value is MATERIAL
            if i + 3 < len(lines) and lines[i + 2].strip() == '1' and lines[i + 3].strip() == 'MATERIAL':
                # Skip entire CLASS block until next group 0
                i += 2
                while i < len(lines) - 1:
                    if lines[i].strip() == '0':
                        break
                    i += 2
                continue

        # Skip ACAD_MATERIAL dictionary reference (group 3 / ACAD_MATERIAL + group 350 / handle)
        if code == '3' and value == 'ACAD_MATERIAL':
            i += 4
            continue

        # Skip ALL group code 94 pairs (only used by advanced objects, not LINE/ARC/CIRCLE)
        if code == '94':
            i += 2
            continue

        # Keep this pair
        out.append(lines[i])
        out.append(lines[i + 1])
        i += 2

    # Handle any trailing odd line
    if i < len(lines):
        out.append(lines[i])

    with open(filepath, 'w') as f:
        f.writelines(out)


# === MAIN ===

def parse_tapped_sidecar(path):
    """Read a tapped holes sidecar file. Returns list of (u, v, dia) tuples."""
    holes = []
    if not path:
        return holes
    try:
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(',')
                if len(parts) >= 3:
                    holes.append((float(parts[0]), float(parts[1]), float(parts[2])))
    except Exception:
        pass
    return holes


def remove_tapped_circles(circles, tapped_holes):
    """
    Remove CIRCLE entities that correspond to tapped holes.

    Strategy:
    1. Group tapped holes by diameter (within tolerance)
    2. For each group, find all circles with matching diameter
    3. If the count of matching circles equals or exceeds the tapped count,
       remove the N closest circles (by position) to the tapped hole centers.
    4. If fewer circles than tapped holes match by diameter, warn and don't remove.

    Position matching tolerance is loose (0.5") since view projection may differ
    from our 3D projection. Diameter is the primary discriminator.
    """
    if not tapped_holes or not circles:
        return circles, [], []

    DIA_TOL = 0.01   # diameter match tolerance (inches)
    POS_TOL = 1.0    # position match tolerance (loose - inches)

    warnings = []
    removed = []

    # Group tapped holes by diameter (rounded to nearest 0.001")
    tapped_by_dia = defaultdict(list)
    for (u, v, dia) in tapped_holes:
        key = round(dia, 3)
        tapped_by_dia[key].append((u, v, dia))

    # For each tapped diameter group, find matching circles
    kept = list(circles)
    for dia_key, holes in tapped_by_dia.items():
        target_dia = dia_key
        matching_circles = [c for c in kept
                            if abs(c.radius() * 2.0 - target_dia) < DIA_TOL]

        if len(matching_circles) == 0:
            warnings.append(
                f"Tapped hole dia={target_dia:.4f} has no matching circles in DXF")
            continue

        if len(matching_circles) == len(holes):
            # Exact count match - remove them all
            for c in matching_circles:
                removed.append(c)
                kept.remove(c)
        elif len(matching_circles) > len(holes):
            # More circles than tapped holes - use position to disambiguate
            # For each tapped hole, find the closest circle (by 2D distance)
            # NOTE: position comparison is approximate because view transform
            # may differ from our projection. Use as tiebreaker only.
            to_remove = []
            available = list(matching_circles)
            for (u, v, _) in holes:
                if not available:
                    break
                # Find closest circle by center distance
                best = None
                best_dist = float('inf')
                for c in available:
                    cx, cy = c.center()
                    d = math.hypot(cx - u, cy - v)
                    if d < best_dist:
                        best_dist = d
                        best = c
                if best is not None:
                    to_remove.append(best)
                    available.remove(best)

            for c in to_remove:
                removed.append(c)
                if c in kept:
                    kept.remove(c)
            warnings.append(
                f"Tapped dia={target_dia:.4f}: {len(to_remove)}/{len(matching_circles)} circles matched by position (ambiguous - verify)")
        else:
            # Fewer circles than tapped holes
            warnings.append(
                f"Tapped dia={target_dia:.4f}: expected {len(holes)} circles, found {len(matching_circles)} (some may not be in view)")
            # Remove what we found
            for c in matching_circles:
                removed.append(c)
                kept.remove(c)

    return kept, removed, warnings


def run_cleanup(input_path, output_path, tapped_sidecar_path=None, sw_unit=3):
    """
    Run the cleanup pipeline on a single DXF file.

    Args:
        input_path: path to the raw DXF input file
        output_path: path to write the cleaned DXF
        tapped_sidecar_path: optional path to a tapped-holes sidecar file
        sw_unit: SolidWorks unit code (0=mm, 1=cm, 2=m, 3=in, 4=ft, 5=ft-in)

    Returns:
        int: exit code (0 = success, 2 = success with warnings)
    """
    # Configure tolerances and $INSUNITS for the document's unit system
    configure_units(sw_unit)

    exit_code = 0
    all_warnings = []

    # Reset point registry for this file (uses updated TOL)
    global _registry
    _registry = PointRegistry(TOL)

    # Load tapped hole sidecar if provided
    tapped_holes_input = parse_tapped_sidecar(tapped_sidecar_path)
    tapped_removed_count = 0

    print(f"=== DXF Cleanup: {input_path} ===")
    if tapped_holes_input:
        print(f"Tapped holes from sidecar: {len(tapped_holes_input)}")

    # --- Step 1-2: Parse and filter ---
    lines_arcs, circles, parse_warns = parse_dxf(input_path)
    all_warnings.extend(parse_warns)
    total_input = len(lines_arcs) + len(circles)
    print(f"Parsed: {len(lines_arcs)} lines/arcs, {len(circles)} circles ({total_input} total)")

    # --- Step 3: Deduplicate ---
    lines_arcs, la_dupes = dedup(lines_arcs)
    circles, c_dupes = dedup(circles)
    total_dupes = la_dupes + c_dupes
    if total_dupes > 0:
        print(f"Removed {total_dupes} duplicates")

    # --- Step 4: Remove degenerate ---
    lines_arcs, la_degen = remove_degenerate(lines_arcs)
    circles, c_degen = remove_degenerate(circles)
    total_degen = la_degen + c_degen
    if total_degen > 0:
        print(f"Removed {total_degen} degenerate entities")

    # --- Step 5: Circle-only early exit ---
    if len(lines_arcs) == 0:
        print("Circle-only part (no lines/arcs)")
        has_boundary = False
        kept_circles, removed_circles, conc_warns = filter_concentric_circles(
            circles, has_line_boundary=False)
        all_warnings.extend(conc_warns)

        # Tapped hole removal (if sidecar provided)
        if tapped_holes_input:
            kept_circles, tap_removed, tap_warns = remove_tapped_circles(
                kept_circles, tapped_holes_input)
            tapped_removed_count = len(tap_removed)
            all_warnings.extend(tap_warns)
            if tap_removed:
                print(f"Removed {len(tap_removed)} tapped holes")

        # Small feature check
        small_warns = check_small_features(kept_circles, [], KERF_MIN)
        all_warnings.extend(small_warns)

        # Write output
        write_cleaned_dxf(output_path, [], [], kept_circles)

        total_output = len(kept_circles)
        print(f"Output: {total_output} circles")
        if removed_circles:
            print(f"Removed {len(removed_circles)} concentric circles")

    else:
        # --- Step 6: Build graph ---
        graph = build_graph(lines_arcs)
        print(f"Graph: {len(graph)} nodes")

        # --- Step 7: Trace outermost boundary ---
        outer_loop = trace_outermost(graph, lines_arcs)
        print(f"Outer boundary: {len(outer_loop)} entities")

        # Verify outer closure
        outer_gap = verify_loop_closure(outer_loop)
        if outer_gap > TOL:
            all_warnings.append(f"Outer boundary gap: {outer_gap:.6f}")

        # --- Step 8: Find hole loops ---
        hole_loops = find_hole_loops(graph, lines_arcs)
        print(f"Hole loops: {len(hole_loops)}")

        for i, loop in enumerate(hole_loops):
            gap = verify_loop_closure(loop)
            if gap > TOL:
                all_warnings.append(f"Hole loop {i} gap: {gap:.6f}")

        # --- Step 9: Count danglers ---
        dangling = [e for e in lines_arcs if not e.used]
        if dangling:
            print(f"Removed {len(dangling)} dangling entities")

        # --- Step 10: Concentric circles ---
        kept_circles, removed_circles, conc_warns = filter_concentric_circles(
            circles, has_line_boundary=True)
        all_warnings.extend(conc_warns)
        if removed_circles:
            print(f"Removed {len(removed_circles)} concentric circles (countersinks)")

        # --- Step 10b: Tapped hole removal (if sidecar provided) ---
        if tapped_holes_input:
            kept_circles, tap_removed, tap_warns = remove_tapped_circles(
                kept_circles, tapped_holes_input)
            tapped_removed_count = len(tap_removed)
            all_warnings.extend(tap_warns)
            if tap_removed:
                print(f"Removed {len(tap_removed)} tapped holes")

        # --- Step 11-12: Small features ---
        small_warns = check_small_features(kept_circles, hole_loops, KERF_MIN)
        all_warnings.extend(small_warns)

        # --- Step 13: Write cleaned DXF ---
        write_cleaned_dxf(output_path, outer_loop, hole_loops, kept_circles)

        total_output = len(outer_loop) + sum(len(l) for l in hole_loops) + len(kept_circles)
        print(f"Output: {total_output} entities "
              f"({len(outer_loop)} boundary + {sum(len(l) for l in hole_loops)} hole edges + {len(kept_circles)} circles)")

    # --- Step 14: Report ---
    # Determine if cleanup changed anything
    if len(lines_arcs) == 0:
        # Circle-only path
        nothing_changed = (total_dupes == 0 and total_degen == 0
                           and len(removed_circles) == 0
                           and tapped_removed_count == 0)
    else:
        dangling_count = len([e for e in lines_arcs if not e.used])
        nothing_changed = (total_dupes == 0 and total_degen == 0
                           and dangling_count == 0 and len(removed_circles) == 0
                           and tapped_removed_count == 0)

    if all_warnings:
        exit_code = 2
        print(f"\nWARNINGS ({len(all_warnings)}):")
        for w in all_warnings:
            print(f"  ! {w}")

    # Machine-readable match indicator for the caller
    if nothing_changed:
        print("MATCH:true")
    else:
        print("MATCH:false")

    print(f"\n>>> WARNING: REVIEW THIS DXF BEFORE SENDING TO PLASMA TABLE <<<")
    print(f"=== Done: {input_path} -> {output_path} ===")

    return exit_code
