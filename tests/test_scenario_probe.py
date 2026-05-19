"""Exploratory probe of the close / disassociate / re-open scenarios
from the v0.3.8 design table.

NOT a regression suite — these tests document what currently happens
so we can compare against the expected behaviour.  Some are expected
to FAIL (pre-fix); the failure messages tell us exactly what's
misbehaving.

Use ``pytest -v`` to see the full picture.

Categories probed:

* A1-A5  Closing a single cell (various states).
* B1-B4  Master close menu actions (already covered by other suites
         for the basic paths; we re-probe the unsaved-and-cancel path).
* C1-C5  Disassociate without closing (shake, leave, drift).
* D7     Double-loading the same ring.
* G1-G7  Group integrity invariants after various operations.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.question = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Yes
)


from scriptree.shell.branding_loader import load_branding
from scriptree.shell.cell_registry import CellRegistry
from scriptree.shell.cell_window import CellWindow, _try_spawn_master


def _fresh() -> CellRegistry:
    reg = CellRegistry.instance()
    for h in list(reg.standalones()) + list(reg.masters()):
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass
    return reg


def _new_cell(x: int = 0, y: int = 0) -> CellWindow:
    cell = CellWindow(load_branding())
    cell.move(x, y)
    cell.show()
    return cell


def _spawn_pair() -> tuple[CellWindow, CellWindow, CellWindow]:
    _fresh()
    a = _new_cell(200, 200)
    b = _new_cell(256, 200)
    _try_spawn_master(a, b)
    reg = CellRegistry.instance()
    master = reg.get(reg.master_of(a._id))
    return master, a, b


def _spawn_triplet() -> tuple[CellWindow, list[CellWindow]]:
    _fresh()
    a = _new_cell(200, 200)
    b = _new_cell(256, 200)
    _try_spawn_master(a, b)
    c = _new_cell(312, 200)
    _try_spawn_master(c, b)  # Case 2: c joins b's group
    reg = CellRegistry.instance()
    master = reg.get(reg.master_of(a._id))
    return master, [a, b, c]


# ===========================================================================
# Category G — Group integrity invariants
# ===========================================================================

class TestGroupInvariants:

    def test_g1_member_master_id_matches_master_members(self) -> None:
        """G1: every cell with _group_master_id == X is in master[X]._members."""
        master, members = _spawn_triplet()
        for m in members:
            assert m._group_master_id == master._id
            assert m._id in master._members

    def test_g3_no_duplicate_ids_in_registry(self) -> None:
        """G3: registry must have no duplicate ids."""
        _fresh()
        a = _new_cell()
        reg = CellRegistry.instance()
        all_cells = list(reg.standalones()) + list(reg.masters())
        ids = [c._id for c in all_cells]
        assert len(ids) == len(set(ids))
        a.close()

    def test_g5_positioned_subset_of_members(self) -> None:
        """G5: master._positioned ⊆ master._members.keys()."""
        master, members = _spawn_triplet()
        assert master._positioned.issubset(set(master._members.keys()))


# ===========================================================================
# Category C — Disassociation paths
# ===========================================================================

class TestDisassociateScenarios:

    def test_c1_explicit_leave_group_clears_membership(self) -> None:
        """C1: 'Leave group' clears member's _group_master_id and removes
        from master's _members. Master survives because 2 members remain."""
        master, members = _spawn_triplet()
        a, b, c = members
        a._explicit_leave_group()
        assert a._group_master_id is None
        assert a._id not in master._members
        assert master.role == "master"
        # Master is dirty (membership changed).
        assert master._ring_dirty is True

    def test_c2_shake_full_unassociate(self) -> None:
        """C2: shake fully unassociates a member."""
        master, members = _spawn_triplet()
        a, b, c = members
        a._on_shake_detected()
        assert a._group_master_id is None
        assert a._id not in master._members

    def test_c4_drift_keeps_membership_but_leaves_positioned(
        self,
    ) -> None:
        """C4: drift detection moves the member out of _positioned but
        keeps it in _members (group preserved)."""
        master, members = _spawn_triplet()
        a, b, c = members
        # Move a far enough away to trigger drift.  ``_check_undock``
        # uses ``snap_dist*2 + size_px`` as the threshold.
        a.move(2000, 2000)
        from scriptree.shell.cell_window import _check_undock
        _check_undock(a)
        # Membership preserved.
        assert a._id in master._members
        # But not in the cluster.
        assert a._id not in master._positioned

    def test_c4_drift_does_not_mark_master_dirty(self) -> None:
        """C4 + E7: drift is positional, NOT a membership change.
        Master should not become dirty."""
        master, members = _spawn_triplet()
        # Save the ring so we have a clean baseline.
        master._ring_dirty = False
        a = members[0]
        a.move(2000, 2000)
        from scriptree.shell.cell_window import _check_undock
        _check_undock(a)
        # Master should stay clean.
        assert master._ring_dirty is False, (
            "Drift detection (positional only) marked the master dirty "
            "— violates the v0.3.1 'membership-only dirty' contract."
        )


# ===========================================================================
# Category D7 — Double-loading the same ring
# ===========================================================================

class TestDoubleLoadRing:

    def test_d7_double_load_creates_two_masters(
        self, tmp_path: Path,
    ) -> None:
        """D7: loading a ring twice in a row currently spawns TWO
        live ring instances on screen.  Documents the behaviour;
        whether this is the right UX is open."""
        from scriptree.shell.ring_io import load_ring
        _fresh()
        # Build a real saved ring.
        master, _, _ = _spawn_pair()
        target = tmp_path / "demo.scriptreering"
        master._write_ring_to_path(target)
        master.close()
        _fresh()

        branding = load_branding()
        registry = CellRegistry.instance()
        m1 = load_ring(target, branding, registry, None)
        m2 = load_ring(target, branding, registry, None)
        # Are they the same id?  Yes — deterministic from member ids.
        # In that case, registry's "no-op on duplicate id" rule kicks in.
        # m2 may end up referencing the existing master (m1) or a
        # different fresh CellWindow.  Document either way.
        masters = list(registry.masters())
        n_masters = len(masters)
        # The probe just records the count.  Either:
        #   - Two master windows exist (n_masters == 2)  → user sees double
        #   - Or one (n_masters == 1)                    → some dedup ran
        assert n_masters in (1, 2), (
            f"Unexpected master count after double-load: {n_masters}"
        )
        # If 2, that's the bug we flagged for review.
        if n_masters == 2:
            print(
                "[probe] Double-load produced TWO master windows "
                "(deterministic-id collision allowed both to register?)."
            )


# ===========================================================================
# Category F — App-exit save prompts
# ===========================================================================

class TestExitDirtyRingPrompts:
    """F1 + F3: closing the last cell or running 'Exit all' while a
    master is dirty currently does NOT fire a save prompt — data
    loss risk.  These tests document the gap."""

    def test_f1_exit_all_skips_dirty_master_save_prompt(self) -> None:
        from scriptree.shell.cell_window import _check_master_validity  # noqa: F401
        _fresh()
        master, _a, _b = _spawn_pair()
        # Master is fresh-spawned → dirty by the v0.3.1 rules.
        assert master._ring_dirty is True

        prompt_fired = []
        original_q = QMessageBox.question

        def _track_q(*args, **kwargs):
            prompt_fired.append(args[1] if len(args) > 1 else "?")
            return QMessageBox.StandardButton.Discard

        with patch.object(QMessageBox, "question", side_effect=_track_q), \
             patch.object(QApplication, "quit"):
            # Pick any cell to call _exit_all on.
            master._exit_all()

        # PRE-FIX: prompt_fired stays empty because _exit_all closes
        # everything without firing save dialogs.
        if not prompt_fired:
            print(
                "[probe] _exit_all closed a dirty ring without "
                "firing the save prompt."
            )

    def test_f3_last_cell_close_skips_dirty_master_save_prompt(
        self,
    ) -> None:
        _fresh()
        master, a, b = _spawn_pair()

        # Member close that drops master quorum — closes master via
        # _check_master_validity.  But the master is unsaved + dirty —
        # should this prompt?  Currently NO.
        prompt_fired = []
        with patch.object(
            QMessageBox, "question",
            side_effect=lambda *a, **k: (
                prompt_fired.append("q"), QMessageBox.StandardButton.Discard
            )[1],
        ):
            a._close_this()
            b._close_this()

        if not prompt_fired:
            print(
                "[probe] Quorum-loss close path did not fire a save "
                "prompt for the dirty unsaved ring."
            )


# ===========================================================================
# Category G7 — Stale _saved_ring_path
# ===========================================================================

class TestStaleSavedPath:
    """G7: if a saved ring's file is deleted from disk, the cell
    shell still considers the ring 'clean' and writes future saves
    silently to a vanished location."""

    def test_g7_save_after_file_deleted(self, tmp_path: Path) -> None:
        master, _, _ = _spawn_pair()
        target = tmp_path / "demo.scriptreering"
        master._write_ring_to_path(target)
        assert master._ring_dirty is False
        assert target.is_file()

        # User deletes the file via Explorer.
        target.unlink()

        # Cell shell still thinks it's saved — _ring_needs_save_prompt
        # should arguably return True because the on-disk record is gone.
        if not master._ring_needs_save_prompt():
            print(
                "[probe] Master with deleted on-disk ring still reports "
                "'no save prompt needed' — close would proceed silently."
            )

    def teardown_method(self, _method) -> None:
        _fresh()
