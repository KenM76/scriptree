"""
cell_registry.py — CellRegistry singleton.

## For humans

Owns all live CellWindow instances in this process. Acts as the
publish/subscribe bus for dock and lifecycle events.

Architecture: ADR-001 §sub-decision-1 and §sub-decision-4, updated per
Amendment 2 (group-association model).  Platform: Win11 primary; single
process, multi-window model.

## For maintainers / LLMs

- The singleton is stored in the class attribute ``_INSTANCE`` (NOT on
  the QApplication, despite the inline comment claiming otherwise).
  ``instance()`` lazily constructs on first call.  Tests that need a
  fresh registry must reset ``CellRegistry._INSTANCE = None`` themselves.
- ``register`` is keyed on ``hex_win._id`` and is idempotent — a
  duplicate id is a logged no-op and does NOT re-emit ``hexagonSpawned``.
  This is load-bearing: ``_check_master_validity`` relies on
  ``close()``→``unregister`` freeing a deterministic master id so a
  re-dock of the same pair can re-register.  If you make ``register``
  overwrite instead of no-op, that teardown/respawn cycle breaks.
- ``unregister`` takes a ``hex_id`` (string), but ``register`` takes a
  ``CellWindow``.  Asymmetric on purpose — ``closeEvent`` only has the
  id at that point.
- This class reaches into ``CellWindow`` private attributes
  (``_group_master_id``, ``_members``, ``role``).  ``master_of`` /
  ``group_members_of`` / ``dock_group_of`` are tightly coupled to
  CellWindow's Amendment-2 membership model — changing the membership
  field names there requires updating every ``getattr``/attribute access
  here.
- ``dock_group_of`` is a deliberately conservative SnapEngine shim: it
  always returns a set that includes the master and all members so a
  cell can never snap to its own group siblings.  ``group_members_of``
  returns ``set()`` (not an error) for unknown / non-master ids — callers
  rely on the empty-set contract.
- ``master_id(a, b)`` is order-independent (sorts the pair) and stable
  across dock/undock cycles.  Anything that constructs or matches master
  ids must go through this static method, never string-format its own.
- The signal arity is fixed: ``masterSpawned(str, str, str)`` and the
  rest single-``str``.  Connected slots in CellWindow / SnapEngine
  depend on these exact signatures.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from scriptree.shell.cell_window import CellWindow


def _log(msg: str) -> None:
    print(f"[CellRegistry] {msg}", file=sys.stderr)


class CellRegistry(QObject):
    """Singleton registry of all live hexagon windows.

    Signals
    -------
    hexagonSpawned(hex_id)
        Emitted when a new CellWindow registers itself.
    hexagonClosed(hex_id)
        Emitted when a CellWindow unregisters itself (about to close).
    hexagonMoved(hex_id)
        Emitted from CellWindow.moveEvent so the SnapEngine can poll.
    hexagonReshaped(hex_id)
        Emitted from apply_* methods so SnapEngine invalidates vertex caches.
    masterSpawned(master_id, source_a_id, source_b_id)
        Emitted when a MasterHexagon is created.
    masterDespawned(master_id)
        Emitted when a MasterHexagon is hidden (undocked) or destroyed (source closed).
    """

    # Singleton storage — attached to QApplication so it lives as long as the app.
    _INSTANCE: "CellRegistry | None" = None

    # ---- Signals -----------------------------------------------------------
    hexagonSpawned  = Signal(str)         # hex_id
    hexagonClosed   = Signal(str)         # hex_id
    hexagonMoved    = Signal(str)         # hex_id
    hexagonReshaped = Signal(str)         # hex_id
    masterSpawned   = Signal(str, str, str)   # master_id, a_id, b_id
    masterDespawned = Signal(str)         # master_id

    def __init__(self) -> None:
        super().__init__()
        # Dict keyed by hex_id for O(1) lookup.
        self._hexagons: dict[str, "CellWindow"] = {}
        _log("CellRegistry created")

    # ---- Singleton access --------------------------------------------------

    @classmethod
    def instance(cls) -> "CellRegistry":
        """Return (or create) the process-wide singleton."""
        if cls._INSTANCE is None:
            cls._INSTANCE = CellRegistry()
        return cls._INSTANCE

    # ---- Registration ------------------------------------------------------

    def register(self, hex_win: "CellWindow") -> None:
        """Register a newly-created CellWindow.

        Called from CellWindow.__init__. Emits hexagonSpawned.
        """
        hid = hex_win._id
        if hid in self._hexagons:
            _log(f"register: {hid} already registered — no-op")
            return
        self._hexagons[hid] = hex_win
        _log(f"register: {hid} role={hex_win.role} total={len(self._hexagons)}")
        self.hexagonSpawned.emit(hid)

    def unregister(self, hex_id: str) -> None:
        """Unregister a closing CellWindow.

        Called from CellWindow.closeEvent. Emits hexagonClosed.
        """
        if hex_id not in self._hexagons:
            _log(f"unregister: {hex_id} not found — no-op")
            return
        del self._hexagons[hex_id]
        _log(f"unregister: {hex_id} remaining={len(self._hexagons)}")
        self.hexagonClosed.emit(hex_id)

    # ---- Lookup ------------------------------------------------------------

    def get(self, hex_id: str) -> "CellWindow | None":
        return self._hexagons.get(hex_id)

    def all(self) -> list["CellWindow"]:
        return list(self._hexagons.values())

    def standalones(self) -> list["CellWindow"]:
        """Return only hexagons with role='standalone'."""
        return [h for h in self._hexagons.values() if h.role == "standalone"]

    def masters(self) -> list["CellWindow"]:
        """Return only hexagons with role='master'."""
        return [h for h in self._hexagons.values() if h.role == "master"]

    def others(self, hex_id: str) -> list["CellWindow"]:
        """Return all registered hexagons except the one with hex_id."""
        return [h for hid, h in self._hexagons.items() if hid != hex_id]

    # ---- Group-association queries (Amendment 2) ---------------------------

    def master_of(self, hex_id: str) -> "str | None":
        """Return the master_id for the group this hex belongs to, or None.

        For standalone hexes not in any group: returns None.
        For standalone hexes that ARE in a group: returns master._id.
        For master hexes: returns None (a master is not a member of another group).
        """
        h = self._hexagons.get(hex_id)
        if h is None:
            return None
        return getattr(h, "_group_master_id", None)

    def group_members_of(self, master_id: str) -> set[str]:
        """Return the set of member ids for a given master.

        Returns an empty set if master_id is not found or not a master.
        """
        master = self._hexagons.get(master_id)
        if master is None or master.role != "master":
            return set()
        return set(master._members.keys())

    # ---- Legacy shim (kept for SnapEngine compatibility) -------------------

    def dock_group_of(self, hex_id: str) -> set[str]:
        """Compatibility shim — returns hex_id's group including the master.

        The snap engine calls this to skip same-group members during snap
        candidate evaluation. Under Amendment 2, a 'group' is:
          - If hex is a master: {master_id} | members_ids
          - If hex is a member: {master_id} | all_member_ids
          - If hex is standalone with no group: {hex_id}

        This is intentionally conservative (always excludes group-mates from
        snap candidates) to prevent a hex from snapping to its own master or
        group siblings.
        """
        h = self._hexagons.get(hex_id)
        if h is None:
            return {hex_id}

        if h.role == "master":
            # Return master + all its members.
            result: set[str] = {hex_id}
            result.update(h._members.keys())
            return result

        # Standalone: check if it's in a group.
        mid = getattr(h, "_group_master_id", None)
        if mid is None:
            return {hex_id}

        master = self._hexagons.get(mid)
        if master is None:
            return {hex_id}

        result = {mid}
        result.update(master._members.keys())
        return result

    def __len__(self) -> int:
        return len(self._hexagons)

    # ---- Deterministic master id -------------------------------------------

    @staticmethod
    def master_id(a_id: str, b_id: str) -> str:
        """Return the deterministic master id for a pair of source hexes.

        Stable across dock/undock/re-dock cycles. Derived from sorted source
        ids so order of arguments doesn't matter.
        """
        return "master:" + ":".join(sorted([a_id, b_id]))

