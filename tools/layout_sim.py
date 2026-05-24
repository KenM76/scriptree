#!/usr/bin/env python3
"""Pure-Python simulator for the ScripTree cell-layout algorithm.

No Qt, no widgets, no event loop.  Just data + functions.  The point
is to model the rules and drive them through every scenario until the
algorithm is provably correct, BEFORE encoding it into the Qt widget
code.

# Mental model

The workspace is a directed acyclic graph (a tree, actually, rooted
at the forest hub):

    Forest (root)
    ├── Ring A (master, child of forest, slot=("inner", 0))
    │   ├── Cell A1 (child of ring A, slot=("inner", 0))
    │   ├── Cell A2 (slot=("inner", 1))
    │   └── Cell A3 (slot=None  ← floating, broken from cluster)
    ├── Ring B (slot=("inner", 1))
    │   └── Cell B1 (slot=("inner", 0))
    └── Cell C (loose, slot=("inner", 2) ← direct forest child)

Every cell has:
* ``parent_id`` -- the cell it's linked to (None only for the forest).
* ``slot`` -- where it sits in the parent's honeycomb ring, OR ``None``
  if "floating-free" (the user dragged it out of its slot but didn't
  unlink it).
* ``pos`` -- absolute screen coordinates.  **Derived** for docked cells
  (computed from parent.pos + slot_offset).  **Owned** for floating
  cells and for the forest root.

Layout is a single function that walks the tree and assigns positions.
There's no per-frame timer.  Layout runs ONLY when something changes
that could affect positions (drag, drop, master move, etc.).

# Rules (user spec)

1. Every cell traces back to the forest via parent_id.
2. Docked cells (slot != None) are positioned by their parent.
3. Floating cells stay where the user put them.
4. No two docked cells share a slot. No overlap possible by construction.
5. Cells whose computed position is off-screen are auto-hidden
   (visible=False) but stay in the tree.
6. Dragging a cell away -> slot=None, link preserved.
7. Dropping near a master -> slot assigned (nearest free).
8. Clicking a master -> collapse: all linked descendants (regardless
   of slot) animate-to-hidden.
9. Click collapsed master -> expand: descendants restored.
10. Dragging a master -> docked descendants follow rigidly. Floating
    descendants stay where they are.
11. Master must remain on screen (clamped).

# Running

    python tools/layout_sim.py

Prints scenario logs + invariant checks.  Asserts on any rule
violation.  Exit 0 = algorithm is sound; exit 1 = bug to fix
before porting.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from typing import Literal, Optional


# ---------------------------------------------------------------------------
# Geometry -- flat-top hex honeycomb (v0.6.40 — edge-touching tiling)
# ---------------------------------------------------------------------------
#
# Inner ring: 6 slots at 60° intervals around the master centre.
# For a hex inscribed in a size_px × size_px box, the circumradius
# R = size_px/2 and apothem (centre-to-edge) = R × √3/2.  Two hexes
# share an edge when their centres sit ``R√3 = size_px × √3/2``
# apart — ≈ 0.866 × size_px, NOT 1.0 × size_px.  Earlier sims used
# the wrong distance and the cells docked tip-to-tip (vertex
# touching vertex).
#
# Outer ring: 12 slots at 30° intervals, alternating between
# **axial** outer (past an inner slot, distance R·2√3) and
# **corner** outer (opposite a vertex of the master, distance 3R).
# Together they complete the second concentric ring of the
# honeycomb.
#
# This sim mirrors ``scriptree/shell/layout.py``.  Keep the two in
# lockstep — the Qt widget code uses the layout module, and
# ``tests/test_layout_algorithm.py`` runs these scenarios as a
# regression net against it.

_SQRT3 = math.sqrt(3)
_SQRT3_HALF = _SQRT3 / 2
# v0.6.40 — start_offset = 90° for flat-top so slot 0 sits due north
# (the top edge midpoint); 0° for pointy-top so slot 0 sits due east.
# Subsequent slots walk clockwise in math (= CCW visually), matching
# snap_engine._FLAT_TOP_OFFSETS / _POINTY_TOP_OFFSETS indices.
_START_DEG = {"flat-top": 90.0, "pointy-top": 0.0}


def _inner_factor(slot_idx: int, orientation: str = "flat-top") -> tuple[float, float]:
    start = _START_DEG.get(orientation, 90.0)
    angle = math.radians(start - slot_idx * 60.0)
    d = _SQRT3_HALF  # R√3 with R = 1/2 (size_px units)
    return (d * math.cos(angle), -d * math.sin(angle))


def _outer_factor(slot_idx: int, orientation: str = "flat-top") -> tuple[float, float]:
    start = _START_DEG.get(orientation, 90.0)
    angle = math.radians(start - slot_idx * 30.0)
    d = _SQRT3 if slot_idx % 2 == 0 else 1.5
    return (d * math.cos(angle), -d * math.sin(angle))


# Legacy constants, populated for flat-top (the deployed orientation).
INNER_RING = [_inner_factor(i, "flat-top") for i in range(6)]
OUTER_RING = [_outer_factor(i, "flat-top") for i in range(12)]


def slot_offset(
    slot: tuple[str, int], size_px: int,
    orientation: str = "flat-top",
) -> tuple[int, int]:
    """Return (dx, dy) -- offset in pixels from master CENTRE to slot CENTRE."""
    kind, idx = slot
    if kind == "inner":
        fx, fy = _inner_factor(idx, orientation)
    elif kind == "outer":
        fx, fy = _outer_factor(idx, orientation)
    else:
        raise ValueError(f"unknown slot kind: {kind!r}")
    return (round(fx * size_px), round(fy * size_px))


def slot_world_pos(
    master_pos: tuple[int, int], master_size: int,
    slot: tuple[str, int], child_size: int,
    master_orientation: str = "flat-top",
) -> tuple[int, int]:
    """Return TOP-LEFT world coords for a child docked at ``slot``
    of a master whose top-left is at ``master_pos``.

    Both master and child are square bounding boxes of side = their
    respective size_px.  Slots are computed centre-to-centre, so we
    convert top-left↔centre at both ends.
    """
    mcx = master_pos[0] + master_size / 2
    mcy = master_pos[1] + master_size / 2
    dx, dy = slot_offset(slot, master_size, master_orientation)
    ccx = mcx + dx
    ccy = mcy + dy
    return (round(ccx - child_size / 2), round(ccy - child_size / 2))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

Slot = Optional[tuple[str, int]]  # ("inner"|"outer", index) or None=floating


@dataclass
class Cell:
    id: str
    parent_id: Optional[str] = None
    slot: Slot = None
    pos: tuple[int, int] = (0, 0)     # top-left absolute coords
    size: int = 56
    is_master: bool = False
    is_forest: bool = False           # the one root cell
    is_collapsed: bool = False        # masters only
    is_visible: bool = True            # set False when auto-hidden off-screen
    # v1.1 — distinguishes "user intentionally broke this cell free
    # from its dock cluster" (floating_intent=True, slot=None) from
    # "slot not yet assigned, please assign one at next layout"
    # (floating_intent=False, slot=None).  Without this, the startup
    # algorithm can't tell whether to assign a fresh slot or leave
    # the cell where the user put it.
    floating_intent: bool = False

    def center(self) -> tuple[int, int]:
        return (self.pos[0] + self.size // 2, self.pos[1] + self.size // 2)

    def rect(self) -> tuple[int, int, int, int]:
        """Top-left + bottom-right (exclusive) bounding box."""
        return (self.pos[0], self.pos[1],
                self.pos[0] + self.size, self.pos[1] + self.size)


@dataclass
class World:
    cells: dict[str, Cell] = field(default_factory=dict)
    screen: tuple[int, int, int, int] = (0, 0, 1920, 1080)  # left, top, right, bottom

    def root(self) -> Cell:
        for c in self.cells.values():
            if c.is_forest:
                return c
        raise RuntimeError("no forest in world")

    def children_of(self, cell_id: str) -> list[Cell]:
        """Cells whose parent_id == cell_id, in insertion order."""
        return [c for c in self.cells.values() if c.parent_id == cell_id]

    def descendants_of(self, cell_id: str) -> list[Cell]:
        """Every cell whose parent chain passes through ``cell_id`` --
        recursive, depth-first."""
        out: list[Cell] = []
        for c in self.children_of(cell_id):
            out.append(c)
            out.extend(self.descendants_of(c.id))
        return out


# ---------------------------------------------------------------------------
# Layout -- the single source of truth
# ---------------------------------------------------------------------------

def compute_layout(world: World) -> None:
    """Walk the tree depth-first from the root and compute every
    docked cell's ``pos`` from its parent's pos + slot offset.

    The forest root and floating cells (slot=None) OWN their pos --
    this function doesn't touch them.

    Also updates ``is_visible``: a cell whose centre lands outside
    the screen rect is marked invisible AND a cell whose ancestor
    is collapsed is marked invisible.  The root forest is clamped
    on-screen; docked masters that go off-screen are auto-hidden
    (not clamped — that would lie about their slot position).

    O(n) in the cell count.  Called only on state changes -- never
    on a timer.
    """
    root = world.root()
    _clamp_master_on_screen(root, world.screen)

    def visit(cell: Cell, ancestor_collapsed: bool) -> None:
        # Position THIS cell first if it's docked.
        if cell.parent_id is not None and cell.slot is not None:
            parent = world.cells[cell.parent_id]
            cell.pos = slot_world_pos(
                parent.pos, parent.size, cell.slot, cell.size,
            )
        # Visibility: hidden if ancestor collapsed, OR off-screen.
        # Forest itself is always visible (the user needs something
        # to click to expand).
        if cell.is_forest:
            cell.is_visible = True
        elif ancestor_collapsed:
            cell.is_visible = False
        else:
            cell.is_visible = _is_on_screen(cell, world.screen)
        # Recurse into children — push the "collapsed" flag down
        # the chain so a hidden ring's cells stay hidden too.
        any_ancestor_collapsed = ancestor_collapsed or cell.is_collapsed
        for child in world.children_of(cell.id):
            visit(child, any_ancestor_collapsed)

    for child in world.children_of(root.id):
        visit(child, root.is_collapsed)


def _is_on_screen(cell: Cell, screen: tuple[int, int, int, int]) -> bool:
    """More than half of cell's bounding box visible inside screen."""
    sl, st, sr, sb = screen
    cl, ct, cr, cb = cell.rect()
    inter_w = max(0, min(cr, sr) - max(cl, sl))
    inter_h = max(0, min(cb, sb) - max(ct, st))
    inter_area = inter_w * inter_h
    cell_area = cell.size * cell.size
    return inter_area * 2 >= cell_area  # >= half on screen


def _clamp_master_on_screen(cell: Cell, screen: tuple[int, int, int, int]) -> None:
    """Snap a master's top-left into the screen so it's always
    grabbable.  Skipped for non-masters (auto-hide handles them)."""
    if not cell.is_master:
        return
    sl, st, sr, sb = screen
    x, y = cell.pos
    x = max(sl, min(sr - cell.size, x))
    y = max(st, min(sb - cell.size, y))
    cell.pos = (x, y)


# ---------------------------------------------------------------------------
# Slot allocation
# ---------------------------------------------------------------------------

def find_free_slot(
    master: Cell, world: World, *, child_size: int,
    occupied_centres: Optional[set[tuple[int, int]]] = None,
) -> Slot:
    """Pick a slot on ``master`` that's free, on-screen, and doesn't
    collide globally with any other placed cell.

    Checks in order:

    1. Sibling exclusion -- the slot isn't taken by another child.
    2. Forbidden back-slot -- when master is itself docked at slot N
       of its parent, the slot pointing back at the parent (inner
       (N+3)%6 / outer (2N+6)%12) is reserved.
    3. On-screen -- the resulting world position fits inside the
       screen rect.
    4. Global no-collision -- the resulting world centre doesn't sit
       within 0.95×edge_touch_distance of any already-placed cell.
       Catches honeycomb-tiling aliasing across adjacent rings.

    v0.6.40 — collision threshold is derived from the actual
    edge-touch distance for this size pair (= (a+b) × √3/4 for
    hexes), not a flat 0.75 × child_size.  The 0.95 factor leaves
    ≈ 5 % rounding slop for adjacent neighbours that sit at exactly
    the edge-touch distance.

    ``occupied_centres`` may be supplied (a set of (cx, cy) integer
    tuples) so callers running a batch can reuse the snapshot; if
    omitted, a fresh one is computed from ``world``.
    """
    if occupied_centres is None:
        occupied_centres = set()
        for c in world.cells.values():
            if c.is_forest or (c.parent_id and c.slot is not None):
                occupied_centres.add(c.center())

    taken = {
        c.slot for c in world.children_of(master.id) if c.slot is not None
    }
    forbidden: set[Slot] = set()
    if master.slot is not None:
        _, pi = master.slot
        forbidden.add(("inner", (pi + 3) % 6))
        forbidden.add(("outer", (pi * 2 + 6) % 12))

    # Edge-touch distance for this master+child pair (hex apothem
    # sum); 0.95 factor lets exact-distance neighbours pass.
    edge_touch = (master.size + child_size) * _SQRT3 / 4
    threshold_sq = (edge_touch * 0.95) ** 2
    for kind, count in (("inner", 6), ("outer", 12)):
        for i in range(count):
            slot = (kind, i)
            if slot in taken or slot in forbidden:
                continue
            tl = slot_world_pos(master.pos, master.size, slot, child_size)
            ghost = Cell(
                id="<probe>", pos=tl, size=child_size, is_visible=True,
            )
            if not _is_on_screen(ghost, world.screen):
                continue
            gcx, gcy = ghost.center()
            collides = False
            for (ox, oy) in occupied_centres:
                dx = gcx - ox
                dy = gcy - oy
                if dx * dx + dy * dy < threshold_sq:
                    collides = True
                    break
            if collides:
                continue
            return slot
    return None


def assign_initial_slots(world: World) -> None:
    """Walk the tree and assign a free, globally-non-colliding slot
    to every cell whose ``floating_intent`` is False.

    Maintains a running ``occupied_centres`` set updated as each
    cell is placed.  Without that, two cells in DIFFERENT clusters
    (e.g. forest -> ringA -> slot 1, forest -> ringB -> slot 0)
    can hash to the same global position because the honeycomb
    tiling allows it; the global set forces alternative slots when
    that happens.

    Strategy is greedy depth-first.  Cells deeper in the tree get
    placed after their parents, so a slot conflict pushes them
    outward to the next free spot.
    """
    root = world.root()
    occupied_centres: set[tuple[int, int]] = {root.center()}

    def collides_globally(centre: tuple[int, int], size: int) -> bool:
        # v0.6.40 — threshold = 0.95 × (size+size) × √3/4 = size × √3 × 0.95/2.
        # Assumes equal-size cells (which is the common case here; the
        # root size is used as a proxy when "occupied" cells may have
        # different sizes — this is a sanity guard, not the primary
        # collision check, so an approximate threshold is fine).
        t_sq = (size * _SQRT3 * 0.95 / 2) ** 2
        for (ox, oy) in occupied_centres:
            dx = centre[0] - ox
            dy = centre[1] - oy
            if dx * dx + dy * dy < t_sq:
                return True
        return False

    def visit(parent: Cell) -> None:
        children = world.children_of(parent.id)
        # Pass 1: invalidate stored slots that collide with already-
        # placed cells anywhere in the tree.
        for child in children:
            if child.floating_intent or child.slot is None:
                continue
            tl = slot_world_pos(
                parent.pos, parent.size, child.slot, child.size,
            )
            ghost_centre = (tl[0] + child.size // 2, tl[1] + child.size // 2)
            if collides_globally(ghost_centre, child.size):
                child.slot = None
        # Pass 2: assign / reassign empty slots.
        for child in children:
            if child.floating_intent:
                continue
            if child.slot is None:
                child.slot = find_free_slot(
                    parent, world,
                    child_size=child.size,
                    occupied_centres=occupied_centres,
                )
            if child.slot is not None:
                child.pos = slot_world_pos(
                    parent.pos, parent.size, child.slot, child.size,
                )
                occupied_centres.add(child.center())
        for child in children:
            visit(child)

    visit(root)


# ---------------------------------------------------------------------------
# Operations -- the actions a user can take
# ---------------------------------------------------------------------------

def drag_cell_to(world: World, cell_id: str, new_pos: tuple[int, int]) -> None:
    """User drags ``cell_id`` to ``new_pos``.

    Before the drag, the cell may have been docked.  Now it's
    floating-by-intent: slot -> None, floating_intent -> True.
    Link (parent_id) preserved.  Pos is owned by the cell.

    Layout is called once at the end so visibility / sibling slots
    update if needed.  Siblings DO NOT shift into the freed slot —
    that's the spec ("if I move it back, my slot is still mine").
    """
    cell = world.cells[cell_id]
    cell.slot = None
    cell.floating_intent = True
    cell.pos = new_pos
    compute_layout(world)


def release_cell_near(world: World, cell_id: str) -> None:
    """The user released the dragged cell.  Find the nearest master
    whose slot the cell is closest to, and if a free slot exists
    there, dock to it.  Otherwise stay floating.

    Selection rule: pick the master whose centre is closest to the
    cell's centre.  Tie-break by hierarchy (prefer the deeper master
    so a cell dropped at the edge of a ring inside the forest joins
    the ring, not the forest).
    """
    cell = world.cells[cell_id]
    candidates = [
        c for c in world.cells.values()
        if c.is_master and c.id != cell.id and c.is_visible
    ]
    if not candidates:
        return

    cx, cy = cell.center()
    candidates.sort(
        key=lambda m: _depth(m, world) * -1,  # deeper first (negate for ascending sort)
    )
    # Stable sort: nearest centre wins among masters with same depth.
    candidates.sort(
        key=lambda m: ((m.center()[0] - cx) ** 2 + (m.center()[1] - cy) ** 2),
    )

    nearest = candidates[0]
    best_slot = _nearest_free_slot(
        nearest, world, cx, cy, cell.size,
        exclude_cell_id=cell.id,
    )
    if best_slot is None:
        return  # no slot available; stay floating
    # Re-link if dropping under a different parent.
    cell.parent_id = nearest.id
    cell.slot = best_slot
    cell.floating_intent = False  # docked again
    compute_layout(world)


def _depth(cell: Cell, world: World) -> int:
    """How many parent hops from the root."""
    d = 0
    cur = cell
    while cur.parent_id is not None:
        d += 1
        cur = world.cells[cur.parent_id]
    return d


def _nearest_free_slot(
    master: Cell, world: World,
    cx: int, cy: int, child_size: int,
    *, exclude_cell_id: Optional[str] = None,
) -> Slot:
    """Return the slot on ``master`` closest to (cx, cy) that is:

      * not taken by another sibling
      * not the back-toward-parent slot (if master is itself docked)
      * on-screen
      * globally non-colliding with every other placed cell (except
        the cell being dropped, identified by ``exclude_cell_id``)

    Returns None if no candidate qualifies.
    """
    taken = {
        c.slot for c in world.children_of(master.id) if c.slot is not None
    }
    forbidden: set[Slot] = set()
    if master.slot is not None:
        _, pi = master.slot
        forbidden.add(("inner", (pi + 3) % 6))
        forbidden.add(("outer", (pi * 2 + 6) % 12))
    # Snapshot every other placed cell's centre.
    occupied_centres: set[tuple[int, int]] = set()
    for c in world.cells.values():
        if c.id == exclude_cell_id:
            continue
        if c.is_forest or (c.parent_id and c.slot is not None):
            occupied_centres.add(c.center())
    # v0.6.40 — edge-touch-aware threshold (see find_free_slot).
    edge_touch = (master.size + child_size) * _SQRT3 / 4
    threshold_sq = (edge_touch * 0.95) ** 2
    candidates: list[tuple[float, Slot]] = []
    for kind, count in (("inner", 6), ("outer", 12)):
        for i in range(count):
            slot = (kind, i)
            if slot in taken or slot in forbidden:
                continue
            tl = slot_world_pos(master.pos, master.size, slot, child_size)
            scx = tl[0] + child_size // 2
            scy = tl[1] + child_size // 2
            ghost = Cell(
                id="<probe>", pos=tl, size=child_size, is_visible=True,
            )
            if not _is_on_screen(ghost, world.screen):
                continue
            # Skip if globally colliding.
            collides = False
            for (ox, oy) in occupied_centres:
                dx = scx - ox
                dy = scy - oy
                if dx * dx + dy * dy < threshold_sq:
                    collides = True
                    break
            if collides:
                continue
            dist = ((scx - cx) ** 2 + (scy - cy) ** 2) ** 0.5
            candidates.append((dist, slot))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def move_master_to(world: World, master_id: str, new_pos: tuple[int, int]) -> None:
    """The user drags a master to ``new_pos``.  Every docked
    descendant follows rigidly because their positions are derived.
    Floating descendants stay where they are."""
    master = world.cells[master_id]
    if not master.is_master:
        raise ValueError(f"{master_id} is not a master")
    master.pos = new_pos
    compute_layout(world)


def click_master(world: World, master_id: str) -> None:
    """Toggle collapse on ``master_id`` -- collapses every linked
    descendant (regardless of slot, so even floating linked cells
    follow).  Click again to expand.

    The state is just a flag on the master; ``compute_layout``
    cascades visibility down the tree on its own.
    """
    master = world.cells[master_id]
    if not master.is_master:
        raise ValueError(f"{master_id} is not a master")
    master.is_collapsed = not master.is_collapsed
    compute_layout(world)


def break_free(world: World, cell_id: str) -> None:
    """User drags a cell out of its slot but releases somewhere
    that isn't a snap target.  Cell goes floating but link is
    preserved (still collapses with parent click, still moves with
    parent drag is FALSE -- only DOCKED cells follow master moves).
    """
    cell = world.cells[cell_id]
    cell.slot = None
    # pos is unchanged -- the cell stays where the user dropped it
    compute_layout(world)


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

def check_invariants(world: World) -> list[str]:
    """Return a list of rule violations.  Empty list = world is
    consistent."""
    errors: list[str] = []

    # 1. Every cell traces back to the forest.
    for c in world.cells.values():
        cur = c
        seen = set()
        while cur.parent_id is not None:
            if cur.id in seen:
                errors.append(f"cycle through {c.id}")
                break
            seen.add(cur.id)
            if cur.parent_id not in world.cells:
                errors.append(f"{c.id} -> dangling parent_id {cur.parent_id!r}")
                break
            cur = world.cells[cur.parent_id]
        else:
            if not cur.is_forest:
                errors.append(f"{c.id} chain ends at non-forest {cur.id}")

    # 2. Forest is unique.
    forests = [c for c in world.cells.values() if c.is_forest]
    if len(forests) != 1:
        errors.append(f"expected 1 forest, found {len(forests)}")

    # 3. No two siblings share a slot.
    by_parent: dict[str, list[Cell]] = {}
    for c in world.cells.values():
        if c.parent_id is not None and c.slot is not None:
            by_parent.setdefault(c.parent_id, []).append(c)
    for parent_id, sibs in by_parent.items():
        slots: set[Slot] = set()
        for s in sibs:
            if s.slot in slots:
                errors.append(
                    f"slot collision on {parent_id}: {s.id} has {s.slot!r}"
                )
            slots.add(s.slot)

    # 4. No two visible cells overlap by centre-distance < 0.75*size.
    visible = [c for c in world.cells.values() if c.is_visible]
    for i, a in enumerate(visible):
        ax, ay = a.center()
        for b in visible[i + 1:]:
            bx, by = b.center()
            min_size = min(a.size, b.size)
            if (
                abs(ax - bx) < min_size * 0.75
                and abs(ay - by) < min_size * 0.75
            ):
                errors.append(
                    f"overlap: {a.id} centre={a.center()} "
                    f"vs {b.id} centre={b.center()}"
                )

    # 5. Forest is on-screen.
    forest = world.root()
    sl, st, sr, sb = world.screen
    if (
        forest.pos[0] < sl or forest.pos[1] < st
        or forest.pos[0] + forest.size > sr
        or forest.pos[1] + forest.size > sb
    ):
        errors.append(f"forest off-screen: pos={forest.pos}")

    # 6. Docked cells' positions match slot computation (sanity).
    for c in world.cells.values():
        if c.parent_id is None or c.slot is None:
            continue
        parent = world.cells[c.parent_id]
        expected = slot_world_pos(parent.pos, parent.size, c.slot, c.size)
        if c.pos != expected:
            errors.append(
                f"{c.id} pos {c.pos} != slot-computed {expected}"
            )

    return errors


def assert_clean(world: World, context: str = "") -> None:
    """Run invariants; raise AssertionError with a clear message if
    any are violated."""
    errs = check_invariants(world)
    if errs:
        ctx = f" ({context})" if context else ""
        raise AssertionError(
            f"\n  Invariant violations{ctx}:\n    "
            + "\n    ".join(errs)
        )


# ---------------------------------------------------------------------------
# Pretty printing for tracing
# ---------------------------------------------------------------------------

def dump(world: World, label: str = "") -> None:
    """Pretty-print the world state to stdout."""
    print(f"\n=== {label or 'world'} ===")
    print(f"  screen: {world.screen}")
    root = world.root()

    def show(cell: Cell, indent: int) -> None:
        pad = "  " + "  " * indent
        kind = "FOREST" if cell.is_forest else (
            "master" if cell.is_master else "cell"
        )
        slot_str = "{" + (
            f"{cell.slot[0]}:{cell.slot[1]}" if cell.slot else "FLOATING"
        ) + "}"
        vis = "V" if cell.is_visible else "."
        coll = " [COLLAPSED]" if cell.is_collapsed else ""
        print(
            f"{pad}{vis} {cell.id} ({kind}) {slot_str} pos={cell.pos}{coll}"
        )
        for child in world.children_of(cell.id):
            show(child, indent + 1)

    show(root, 0)


# ---------------------------------------------------------------------------
# Scenarios -- drive the algorithm through every rule
# ---------------------------------------------------------------------------

def make_starter_world() -> World:
    """A forest with two rings, each holding two cells.  Used as the
    base for most scenarios.

    All slots assigned via ``assign_initial_slots`` — the same
    algorithm startup will use — so the test world never has the
    "child of a docked master lands on the parent's centre" bug
    that the v1.1 forbidden-back-slot rule prevents."""
    w = World(screen=(0, 0, 1920, 1080))
    forest = Cell(
        id="forest", pos=(900, 500), size=56,
        is_master=True, is_forest=True,
    )
    w.cells["forest"] = forest

    w.cells["ringA"] = Cell(
        id="ringA", parent_id="forest", size=56, is_master=True,
    )
    w.cells["ringB"] = Cell(
        id="ringB", parent_id="forest", size=56, is_master=True,
    )

    for parent_id in ("ringA", "ringB"):
        for i in (0, 1):
            cid = f"{parent_id}_cell{i}"
            w.cells[cid] = Cell(
                id=cid, parent_id=parent_id, size=56,
            )

    assign_initial_slots(w)
    compute_layout(w)
    return w


def scenario_startup_no_jumble() -> None:
    """Build a forest with cells at random saved positions, then
    call assign_initial_slots + compute_layout.  Every cell should
    end up at a canonical slot, no overlaps."""
    print("\n=== SCENARIO: startup with stale saved positions ===")
    w = World(screen=(0, 0, 1920, 1080))
    forest = Cell(
        id="forest", pos=(800, 400), size=56,
        is_master=True, is_forest=True,
    )
    w.cells["forest"] = forest
    # Cells with stale absolute positions (pretend these were saved
    # when the forest was elsewhere).
    for i in range(4):
        cid = f"cell{i}"
        w.cells[cid] = Cell(
            id=cid, parent_id="forest", slot=None,  # not assigned yet
            pos=(100 + i * 60, 100), size=56,
        )
    # Run startup algorithm.
    assign_initial_slots(w)
    compute_layout(w)
    dump(w, "after startup")
    assert_clean(w, "startup")
    # All four cells should have inner slots 0-3.
    slots = sorted(
        c.slot for c in w.cells.values()
        if c.id.startswith("cell")
    )
    assert slots == [("inner", 0), ("inner", 1), ("inner", 2), ("inner", 3)], slots
    print("  PASS: cells docked at inner slots 0..3, no overlap.")


def scenario_drag_a_cell_then_drop_into_slot() -> None:
    """Drag cell A1 away, then release near ring A -- it should snap
    into a free slot."""
    print("\n=== SCENARIO: drag -> break free -> drop -> snap ===")
    w = make_starter_world()
    dump(w, "initial")
    assert_clean(w, "initial")

    # Drag ringA_cell0 to a far-away spot.
    drag_cell_to(w, "ringA_cell0", (200, 200))
    dump(w, "after drag (floating)")
    assert_clean(w, "drag")
    assert w.cells["ringA_cell0"].slot is None
    assert w.cells["ringA_cell0"].pos == (200, 200)
    # Still linked to ringA.
    assert w.cells["ringA_cell0"].parent_id == "ringA"

    # Now drop it back near ringA.
    ring_a = w.cells["ringA"]
    rax, ray = ring_a.center()
    w.cells["ringA_cell0"].pos = (rax + 60, ray)  # close to ringA
    release_cell_near(w, "ringA_cell0")
    dump(w, "after release")
    assert_clean(w, "after release")
    assert w.cells["ringA_cell0"].slot is not None
    print("  PASS: cell re-docked at slot", w.cells["ringA_cell0"].slot)


def scenario_drag_cell_to_different_master() -> None:
    """Cross-cluster drop: drag a cell from ringA, drop it
    clearly into ringB's territory -> it re-links to ringB.

    "Clearly into ringB's territory" means: drop the cell so its
    CENTRE lands closer to ringB's centre than to any sibling
    master's centre.  The user's mental model is "the cell goes
    where I dropped it"; the algorithm represents that as
    "snap to whatever master is closest to where the cell's
    centre wound up."
    """
    print("\n=== SCENARIO: drag from ringA, drop on ringB ===")
    w = make_starter_world()

    cell = w.cells["ringA_cell0"]
    ring_b = w.cells["ringB"]
    # Drop with the cell's CENTRE at ringB's centre, so the cell's
    # top-left = ringB.centre - size/2.  This is the unambiguous
    # "drop on ringB" position; the snap selector picks ringB
    # because it's the master whose centre is closest to the cell's
    # final centre.
    cx, cy = ring_b.center()
    target_topleft = (cx - cell.size // 2, cy - cell.size // 2)
    drag_cell_to(w, "ringA_cell0", target_topleft)
    release_cell_near(w, "ringA_cell0")
    dump(w, "after cross-cluster drop")
    assert_clean(w, "cross-cluster")
    assert w.cells["ringA_cell0"].parent_id == "ringB", \
        f"expected ringB, got {w.cells['ringA_cell0'].parent_id}"
    print(
        "  PASS: cell re-linked to ringB, slot=",
        w.cells["ringA_cell0"].slot,
    )


def scenario_drag_master_cascades_to_docked() -> None:
    """Drag the forest -- every docked descendant follows by exactly
    the same delta."""
    print("\n=== SCENARIO: drag the forest, cluster follows ===")
    w = make_starter_world()
    snapshot = {cid: c.pos for cid, c in w.cells.items()}
    # Move the forest by (+200, -150).
    fx, fy = w.cells["forest"].pos
    move_master_to(w, "forest", (fx + 200, fy - 150))
    dump(w, "after master move")
    assert_clean(w, "master move")
    # Every cell should have shifted by exactly the same delta.
    for cid, c in w.cells.items():
        old = snapshot[cid]
        if c.slot is None and not c.is_forest:
            # Floating cells don't move (n/a in this scenario)
            continue
        dx = c.pos[0] - old[0]
        dy = c.pos[1] - old[1]
        assert (dx, dy) == (200, -150), \
            f"{cid} moved by ({dx},{dy}), expected (200,-150)"
    print("  PASS: every docked descendant moved by exactly the master delta.")


def scenario_drag_master_with_floating_cell() -> None:
    """A floating (broken-free) cell should NOT follow when its
    master moves -- it stays where the user dropped it."""
    print("\n=== SCENARIO: floating cell does not follow master ===")
    w = make_starter_world()
    # Break ringA_cell0 free at a custom position.
    drag_cell_to(w, "ringA_cell0", (200, 200))
    # Verify it's floating.
    assert w.cells["ringA_cell0"].slot is None
    # Now drag the forest.
    fx, fy = w.cells["forest"].pos
    move_master_to(w, "forest", (fx + 300, fy))
    # ringA_cell0 should still be at (200, 200).
    assert w.cells["ringA_cell0"].pos == (200, 200), \
        f"floating cell moved unexpectedly to {w.cells['ringA_cell0'].pos}"
    print("  PASS: floating cell stayed put while forest moved.")


def scenario_collapse_hides_all_descendants() -> None:
    """Click the forest -> every linked descendant hides, including
    a floating one."""
    print("\n=== SCENARIO: collapse hides everything linked ===")
    w = make_starter_world()
    drag_cell_to(w, "ringA_cell0", (200, 200))  # one floating
    click_master(w, "forest")
    dump(w, "after collapse")
    # Every non-forest cell should be invisible.
    for c in w.cells.values():
        if c.is_forest:
            assert c.is_visible
        else:
            assert not c.is_visible, f"{c.id} still visible after collapse"
    # Click again to expand.
    click_master(w, "forest")
    dump(w, "after expand")
    # Every cell should be visible again (assuming on-screen).
    for c in w.cells.values():
        assert c.is_visible, f"{c.id} not restored on expand"
    # Floating cell should be back where it was dropped.
    assert w.cells["ringA_cell0"].pos == (200, 200)
    print("  PASS: collapse / expand work; floating cell preserved.")


def scenario_collapse_does_not_unlink() -> None:
    """A floating cell that was linked stays linked through a
    collapse / expand cycle."""
    print("\n=== SCENARIO: collapse does not unlink floating cells ===")
    w = make_starter_world()
    drag_cell_to(w, "ringA_cell0", (200, 200))
    parent_before = w.cells["ringA_cell0"].parent_id
    click_master(w, "forest")
    click_master(w, "forest")
    assert w.cells["ringA_cell0"].parent_id == parent_before, \
        "parent link lost across collapse/expand"
    print("  PASS: parent link preserved.")


def scenario_master_clamped_on_screen() -> None:
    """User tries to drag the forest off-screen -> clamped."""
    print("\n=== SCENARIO: forest clamped to screen ===")
    w = make_starter_world()
    move_master_to(w, "forest", (-500, -500))  # impossible
    assert_clean(w, "after off-screen drag")
    fx, fy = w.cells["forest"].pos
    assert fx >= 0 and fy >= 0, f"forest at {(fx, fy)}, not clamped"
    print("  PASS: forest clamped to (0, 0) or better.")


def scenario_off_screen_member_auto_hides() -> None:
    """A docked cell whose slot lands off-screen is set
    is_visible=False (the count badge will show it)."""
    print("\n=== SCENARIO: off-screen member auto-hides ===")
    w = make_starter_world()
    # Move forest to top-left so half the inner ring goes off-screen.
    move_master_to(w, "forest", (0, 0))
    dump(w, "forest at (0, 0)")
    # Some children of forest's children should now be off-screen.
    # No assertion about WHICH cells; just that auto-hide is applied.
    hidden = [
        c.id for c in w.cells.values()
        if not c.is_visible and not c.is_forest
    ]
    print(f"  auto-hidden: {hidden}")
    # The forest itself must still be visible.
    assert w.cells["forest"].is_visible
    print("  PASS: forest still visible; off-screen cells auto-hid.")


def scenario_no_overlap_after_arbitrary_master_moves() -> None:
    """Stress test: move the forest to 20 random positions on
    screen.  After each move, run invariants.  No two visible cells
    may overlap."""
    print("\n=== SCENARIO: no overlap under random master moves ===")
    import random
    random.seed(42)
    w = make_starter_world()
    for trial in range(20):
        x = random.randint(100, 1700)
        y = random.randint(100, 900)
        move_master_to(w, "forest", (x, y))
        errs = check_invariants(w)
        assert not errs, f"trial {trial} at ({x},{y}): {errs}"
    print("  PASS: 20 random forest positions, no overlap.")


def scenario_forest_to_corner_members_reflow() -> None:
    """Move the forest into the top-left corner.  Some slots will
    fall off-screen; those cells should auto-hide (not disappear
    forever, not move to random places).  When the forest moves
    back to the centre, the cells reappear.
    """
    print("\n=== SCENARIO: forest to corner -> auto-hide, then return ===")
    w = make_starter_world()
    pre_pos = {cid: c.pos for cid, c in w.cells.items()}
    pre_slot = {cid: c.slot for cid, c in w.cells.items()}

    # Move forest hard into top-left.
    move_master_to(w, "forest", (0, 0))
    dump(w, "forest at (0, 0)")
    # No assertion violations.
    assert_clean(w, "forest at corner")
    # Forest is still at top-left (clamped).
    assert w.cells["forest"].pos == (0, 0)
    # At least one cell auto-hidden (some slot landed off-screen).
    hidden = [
        c.id for c in w.cells.values()
        if not c.is_visible and not c.is_forest
    ]
    assert hidden, "expected some auto-hide at the corner"

    # Move forest back to centre — auto-hidden cells should
    # re-appear.
    move_master_to(w, "forest", pre_pos["forest"])
    assert_clean(w, "forest back at centre")
    for cid, c in w.cells.items():
        if c.is_forest:
            continue
        assert c.is_visible, f"{cid} did not re-appear after forest returned"
        # Slot unchanged through the round trip.
        assert c.slot == pre_slot[cid], (
            f"{cid} slot changed: {pre_slot[cid]} -> {c.slot}"
        )
    print("  PASS: corner-hide + return-show preserves slots and visibility.")


def scenario_drag_master_with_collapsed_descendant() -> None:
    """A nested collapsed master should still stay collapsed
    when an outer master is dragged."""
    print("\n=== SCENARIO: collapsed ring stays collapsed during outer drag ===")
    w = make_starter_world()
    click_master(w, "ringA")  # collapse ringA
    assert w.cells["ringA"].is_collapsed
    # ringA's cells should be invisible.
    assert not w.cells["ringA_cell0"].is_visible
    assert not w.cells["ringA_cell1"].is_visible
    # Now drag the forest.
    fx, fy = w.cells["forest"].pos
    move_master_to(w, "forest", (fx + 100, fy + 100))
    # ringA still collapsed, its cells still hidden.
    assert w.cells["ringA"].is_collapsed
    assert not w.cells["ringA_cell0"].is_visible
    assert not w.cells["ringA_cell1"].is_visible
    print("  PASS: nested collapse survives outer drag.")


def scenario_size_resize_keeps_clean_layout() -> None:
    """Resize the forest hub.  The cluster geometry should
    recompute cleanly; no overlaps."""
    print("\n=== SCENARIO: resize the forest, layout recomputes ===")
    w = make_starter_world()
    w.cells["forest"].size = 80  # was 56
    compute_layout(w)
    assert_clean(w, "after forest resize")
    print("  PASS: resize recomputes layout without overlap.")


def scenario_dock_three_then_collapse_then_expand() -> None:
    """Full lifecycle test: dock 3 cells, collapse the forest,
    expand it, verify everyone is back at their slot."""
    print("\n=== SCENARIO: dock / collapse / expand lifecycle ===")
    w = make_starter_world()
    pos_before = {cid: c.pos for cid, c in w.cells.items()}
    click_master(w, "forest")  # collapse
    click_master(w, "forest")  # expand
    for cid, c in w.cells.items():
        assert c.pos == pos_before[cid], \
            f"{cid} pos changed: {pos_before[cid]} -> {c.pos}"
    print("  PASS: round-trip collapse / expand restored every position.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

SCENARIOS = [
    scenario_startup_no_jumble,
    scenario_drag_a_cell_then_drop_into_slot,
    scenario_drag_cell_to_different_master,
    scenario_drag_master_cascades_to_docked,
    scenario_drag_master_with_floating_cell,
    scenario_collapse_hides_all_descendants,
    scenario_collapse_does_not_unlink,
    scenario_master_clamped_on_screen,
    scenario_off_screen_member_auto_hides,
    scenario_no_overlap_after_arbitrary_master_moves,
    scenario_forest_to_corner_members_reflow,
    scenario_drag_master_with_collapsed_descendant,
    scenario_size_resize_keeps_clean_layout,
    scenario_dock_three_then_collapse_then_expand,
]


def main() -> int:
    failures: list[tuple[str, Exception]] = []
    for fn in SCENARIOS:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failures.append((fn.__name__, exc))
            print(f"  X {fn.__name__} FAILED: {exc!r}")

    print()
    if failures:
        print(f"FAILED: {len(failures)} of {len(SCENARIOS)} scenarios")
        for name, exc in failures:
            print(f"  • {name}: {exc!r}")
        return 1
    print(f"ALL {len(SCENARIOS)} scenarios passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
