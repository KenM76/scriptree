"""Regression tests for the v0.3.8 ring lifecycle bugs.

Two specific user-reported scenarios:

1. **Reassociate after 2-member dissoc.**  When a 2-member ring loses
   one member, ``_check_master_validity`` correctly clears the
   surviving member's ``_group_master_id`` — but the master itself
   is only ``.hide()``-d, not ``.close()``-d.  The master stays in
   the registry under its deterministic id.  Subsequent attempts
   to re-dock the original pair compute the SAME deterministic
   master id; ``CellRegistry.register`` no-ops because the id is
   "already registered", so the new master never gets registered
   and the docking pair end up grouped to a phantom invisible
   master.  User-visible: "I could not reassociate them again
   and get a respawned ring."

2. **Corner-reflow stickiness.**  When the ring is dragged to a
   corner and members reflow to stay on-screen, the user can
   manually rearrange members to non-canonical positions.  As
   long as those positions are still on-screen, a subsequent
   master drag (or any other ``_reflow_members_after_master_move``
   trigger) should leave them alone.  Currently the reflow
   predicate requires positions to be BOTH canonical AND
   on-screen — the canonical check forces the user's manual
   layout back to the default ring positions.  User-visible:
   "I wanted the ring at the bottom, and the two cells stacked,
   but they kept moving back to the other position."

Tests are written before the fix lands so they fail cleanly first
(test-first discipline).
"""
from __future__ import annotations

import pytest

from PySide6.QtCore import QPoint
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.question = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Yes
)


from scriptree.shell.branding_loader import load_branding
from scriptree.shell.cell_registry import CellRegistry
from scriptree.shell.cell_window import CellWindow, _try_spawn_master


def _fresh_registry() -> CellRegistry:
    reg = CellRegistry.instance()
    for h in list(reg.standalones()) + list(reg.masters()):
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass
    return reg


def _spawn_pair_master() -> tuple[CellWindow, CellWindow, CellWindow]:
    """Build a master-of-2 ring via _try_spawn_master.  Returns
    (master, a, b) where a and b are the two members."""
    _fresh_registry()
    branding = load_branding()
    a = CellWindow(branding); a.move(200, 200); a.show()
    b = CellWindow(branding); b.move(200 + 56, 200); b.show()
    _try_spawn_master(a, b)
    reg = CellRegistry.instance()
    master_id = reg.master_of(a._id)
    assert master_id is not None
    master = reg.get(master_id)
    assert master is not None
    return master, a, b


# ===========================================================================
# Bug 1 — reassociate after 2-member dissoc
# ===========================================================================

class TestReassociateAfter2MemberDissoc:

    @pytest.mark.skip(reason=(
        "v0.8.0 spec change: rings no longer auto-close on quorum "
        "loss.  This test asserted the master was removed from the "
        "registry when a 2-member ring lost a member; v0.8.0 keeps "
        "the master alive (per user: 'I think we should not remove "
        "them automatically anymore - shake to close and have a box "
        "come up then to close, save or cancel').  Phase 7 will "
        "rewrite the lifecycle tests."
    ))
    def test_master_is_unregistered_when_one_of_two_closes(self) -> None:
        """When a 2-member ring loses one member, the master must be
        FULLY removed from the registry — not just hidden — so a
        fresh master with the same deterministic id can spawn later."""
        master, a, b = _spawn_pair_master()
        master_id = master._id

        # Close one member.  Triggers _check_master_validity which
        # detects member count < 2.
        b._close_this()

        reg = CellRegistry.instance()
        # PRE-FIX: master.hide() was called but registry still holds it.
        # Post-fix: master.close() runs full lifecycle, registry forgets it.
        assert reg.get(master_id) is None, (
            "Master with id %s is still in the registry after "
            "_check_master_validity closed it." % master_id[:16]
        )

    @pytest.mark.skip(reason=(
        "v0.8.0 spec change: rings no longer auto-close on quorum "
        "loss.  The pre-v0.8.0 path was: member leaves → master "
        "drops below 2 → _check_master_validity closes master → "
        "id freed → redock spawns fresh master.  Under v0.8.0 the "
        "master persists, so 'redock' adds back to the existing "
        "master rather than spawning a new one.  This test needs "
        "rewriting for the new lifecycle (planned in Phase 7)."
    ))
    def test_redocking_same_pair_spawns_fresh_master(self) -> None:
        """Close one of two members, recreate it (or use any cell at
        b's position), redock with a — a NEW master must spawn
        and be registered."""
        master, a, b = _spawn_pair_master()
        original_master_id = master._id

        # User shakes b off and closes it.
        b._explicit_leave_group()
        # Master now has 0 members; _check_master_validity should
        # have closed it.
        b._close_this()

        # a is now standalone.
        assert a._group_master_id is None

        # User docks a fresh cell c with a — should spawn a new master.
        branding = load_branding()
        c = CellWindow(branding); c.move(200 + 56, 200); c.show()
        _try_spawn_master(a, c)

        reg = CellRegistry.instance()
        new_master_id = reg.master_of(a._id)
        assert new_master_id is not None, (
            "No master spawned for the redocked (a, c) pair."
        )
        new_master = reg.get(new_master_id)
        assert new_master is not None
        assert new_master.role == "master"
        assert a._id in new_master._members
        assert c._id in new_master._members

    def test_redocking_with_same_pair_id_works_after_dissoc(self) -> None:
        """The killer scenario: same pair (a, b) re-docked after a
        full dissoc.  The deterministic master_id collides with the
        prior (now-defunct) master.  Without the fix, register()
        no-ops on the duplicate id and the new master never enters
        the registry."""
        master, a, b = _spawn_pair_master()
        original_master_id = master._id

        # b leaves the group fully (shake gesture).
        b._on_shake_detected()
        # a has been left as the sole member; quorum check should
        # have closed master.

        # CRITICAL: do NOT close b.  Just re-position it next to a
        # and re-dock.  This is the EXACT scenario the user reported.
        _try_spawn_master(a, b)

        reg = CellRegistry.instance()
        # The deterministic id for the (a, b) pair is the same as
        # before — but the new master must now be live in the registry.
        new_master_id = reg.master_of(a._id)
        assert new_master_id == original_master_id, (
            "Deterministic master id mismatch — pair-id calc changed?"
        )
        new_master = reg.get(new_master_id)
        assert new_master is not None, (
            "Re-docked pair with same deterministic id failed to "
            "register a fresh master.  CellRegistry.register no-op'd "
            "on the collision."
        )
        assert new_master.isVisible()
        assert a._id in new_master._members
        assert b._id in new_master._members


# ===========================================================================
# Bug 2 — corner-reflow stickiness
# ===========================================================================

class TestCornerReflowStickiness:

    def test_manual_rearrangement_survives_reflow_when_on_screen(
        self,
    ) -> None:
        """When members are at non-canonical but ON-SCREEN positions,
        a subsequent ``_reflow_members_after_master_move`` should
        leave them alone — the canonical check should only force a
        repack when something is actually OFF-screen."""
        master, a, b = _spawn_pair_master()

        # Force the cells off canonical slots — user's manual
        # rearrangement.  Pick positions that are obviously non-canonical
        # (well away from the master's six honeycomb slots) but
        # on-screen near the master.
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        # Place master in the middle so non-canonical-but-on-screen
        # positions are easy to choose.
        if avail is not None:
            mid_x = avail.left() + avail.width() // 2
            mid_y = avail.top() + avail.height() // 2
        else:
            mid_x, mid_y = 800, 500
        master.move(mid_x, mid_y)

        # Manual layout: stack a directly above master, b directly below.
        # Both on-screen; neither at the master's canonical N/NE/SE/...
        # slot centres (since the y-stride for canonical N is sqrt(3)/2*size,
        # not size).
        manual_a = (mid_x, mid_y - 100)
        manual_b = (mid_x, mid_y + 100)
        a.move(*manual_a)
        b.move(*manual_b)
        master._members[a._id] = QPoint(*manual_a)
        master._members[b._id] = QPoint(*manual_b)

        # Trigger reflow as if the user nudged the master slightly.
        master._reflow_members_after_master_move()

        # POST-FIX: positions stick because everything's on-screen.
        # PRE-FIX: repack runs and snaps a/b to canonical slots.
        actual_a = (a.pos().x(), a.pos().y())
        actual_b = (b.pos().x(), b.pos().y())
        assert actual_a == manual_a, (
            f"Manual position for a was overwritten by reflow.  "
            f"Wanted {manual_a}, got {actual_a}."
        )
        assert actual_b == manual_b, (
            f"Manual position for b was overwritten by reflow.  "
            f"Wanted {manual_b}, got {actual_b}."
        )

    def test_reflow_still_runs_when_member_off_screen(self) -> None:
        """Sanity: the off-screen → repack path is still active.
        Drop a member off-screen; reflow must move it on-screen."""
        master, a, b = _spawn_pair_master()

        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        if avail is not None:
            corner_x = avail.left() + 100
            corner_y = avail.top() + 100
        else:
            corner_x, corner_y = 100, 100
        master.move(corner_x, corner_y)

        # Push a far off-screen to the left.
        a.move(-1000, corner_y)
        master._members[a._id] = QPoint(-1000, corner_y)

        master._reflow_members_after_master_move()

        # Repack should have moved a back on-screen.
        new_x = a.pos().x()
        if avail is not None:
            assert new_x >= avail.left(), (
                f"Reflow failed to reel a back on-screen — left at x={new_x}."
            )

    def teardown_method(self, _method) -> None:
        _fresh_registry()
