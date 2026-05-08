"""Tests for the v0.3.1 ring dirty-flag + close-prompt behaviour.

User spec:

> When I right clicked on the ring I had made and not saved and
> closed it, it did not ask me if I wanted to save it. That should
> happen if a ring isn't saved yet, or if we click to add it to
> start up (going to need to be a file for that), or if we've
> add or removed cells from it, but shouldn't if the only thing
> that has changed is the positions of the cells.

Coverage:

1. ``_ring_dirty`` is False on a freshly-constructed master.
2. ``_try_spawn_master`` Case 1 (fresh master) sets ``_ring_dirty=True``.
3. Case 2/3 add — master's ``_ring_dirty`` becomes True.
4. Member close (``_close_this`` member-leave path) — master's
   ``_ring_dirty`` becomes True.
5. ``save_ring`` clears ``_ring_dirty``.
6. ``load_ring`` clears ``_ring_dirty``.
7. Position-only changes (group drag, repack, drift snap-back) do
   NOT mark dirty.
8. ``_ring_needs_save_prompt`` returns True iff dirty OR never saved.
9. ``_close_ring_undock_all`` shows a confirm dialog when prompt
   needed; cancel aborts the close; discard / save proceed.
10. ``_close_all_related`` shows the same dialog.
11. Saved-and-clean ring closes silently (no prompt).
"""
from __future__ import annotations

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


from scriptree.shell.branding_loader import load_branding  # noqa: E402
from scriptree.shell.cell_registry import CellRegistry  # noqa: E402
from scriptree.shell.cell_window import (  # noqa: E402
    CellWindow,
    _try_spawn_master,
)


def _fresh_registry() -> CellRegistry:
    reg = CellRegistry.instance()
    for h in list(reg.standalones()) + list(reg.masters()):
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass
    return reg


def _spawn() -> CellWindow:
    return CellWindow(load_branding())


def _build_pair_master() -> tuple[CellWindow, CellWindow, CellWindow]:
    _fresh_registry()
    a = _spawn()
    b = _spawn()
    a.move(200, 200); b.move(200 + 56, 200)
    a.show(); b.show()
    _try_spawn_master(a, b)
    reg = CellRegistry.instance()
    master_id = reg.master_of(a._id)
    assert master_id is not None
    master = reg.get(master_id)
    assert master is not None
    return master, a, b


# ---------------------------------------------------------------------------
# 1-2. Initial state + Case 1 master spawn
# ---------------------------------------------------------------------------

def test_freshly_constructed_master_starts_clean() -> None:
    """A naked CellWindow constructed in master role hasn't taken
    any membership changes yet — clean."""
    branding = load_branding()
    m = CellWindow(branding, role="master", hexagon_id="m-1")
    assert m._ring_dirty is False
    m.close()


def test_case1_fresh_master_marks_dirty() -> None:
    """Two cells docking spawn a fresh master with two members —
    that's a brand-new ring, dirty by definition."""
    master, _, _ = _build_pair_master()
    assert master._ring_dirty is True
    assert master._saved_ring_path is None  # never saved either


# ---------------------------------------------------------------------------
# 3. Case 2 / 3 member-add marks dirty
# ---------------------------------------------------------------------------

def test_case2_member_add_marks_dirty() -> None:
    """Adding a third member to an existing master via Case 2 path."""
    master, a, b = _build_pair_master()
    # Save and reset dirty so we can observe the next add.
    master._ring_dirty = False
    c = _spawn()
    c.move(b.pos().x() + 56, b.pos().y())
    c.show()
    _try_spawn_master(c, b)  # Case 2 — c standalone, b in master's group
    assert c._id in master._members
    assert master._ring_dirty is True


# ---------------------------------------------------------------------------
# 4. Member-close (Case _close_this member-leave) marks dirty
# ---------------------------------------------------------------------------

def test_member_close_marks_master_dirty() -> None:
    master, a, b = _build_pair_master()
    master._ring_dirty = False
    # Closing one member must NOT collapse the master (need ≥ 2);
    # add a third so removing one leaves two.
    c = _spawn(); c.move(b.pos().x() + 56, b.pos().y()); c.show()
    _try_spawn_master(c, b)
    master._ring_dirty = False  # reset after the add

    a._close_this()
    assert master._ring_dirty is True
    assert a._id not in master._members


def test_explicit_leave_group_marks_dirty() -> None:
    master, a, b = _build_pair_master()
    master._ring_dirty = False
    # Need 3 members so leave-group doesn't collapse master.
    c = _spawn(); c.move(b.pos().x() + 56, b.pos().y()); c.show()
    _try_spawn_master(c, b)
    master._ring_dirty = False

    a._explicit_leave_group()
    assert master._ring_dirty is True


# ---------------------------------------------------------------------------
# 5-6. Save / load reset dirty
# ---------------------------------------------------------------------------

def test_save_clears_dirty(tmp_path: Path) -> None:
    master, _, _ = _build_pair_master()
    assert master._ring_dirty is True

    target = tmp_path / "demo.scriptreering"
    master._write_ring_to_path(target)
    assert target.is_file()
    assert master._ring_dirty is False
    assert master._saved_ring_path == target


def test_load_clears_dirty(tmp_path: Path) -> None:
    """Loading a ring file produces a clean master that doesn't
    immediately prompt to save on close."""
    from scriptree.shell.ring_io import load_ring, save_ring

    master, _, _ = _build_pair_master()
    target = tmp_path / "demo.scriptreering"
    save_ring(master, target)

    _fresh_registry()  # clear in-memory state for a clean load
    loaded = load_ring(
        target, master._branding, CellRegistry.instance(), None,
    )
    assert loaded._ring_dirty is False


# ---------------------------------------------------------------------------
# 7. Position-only changes do NOT mark dirty
# ---------------------------------------------------------------------------

def test_repack_does_not_mark_dirty(tmp_path: Path) -> None:
    """A repack moves members around without changing membership.
    The dirty flag must not flip."""
    master, _, _ = _build_pair_master()
    target = tmp_path / "demo.scriptreering"
    master._write_ring_to_path(target)
    assert master._ring_dirty is False

    master._repack_members()
    assert master._ring_dirty is False


def test_group_drag_translation_does_not_mark_dirty(tmp_path: Path) -> None:
    """Translating member positions during a master drag must not
    flip dirty (it's a position-only event)."""
    master, _, _ = _build_pair_master()
    target = tmp_path / "demo.scriptreering"
    master._write_ring_to_path(target)
    assert master._ring_dirty is False

    master._shift_positioned_members(15, 20)
    assert master._ring_dirty is False


# ---------------------------------------------------------------------------
# 8. _ring_needs_save_prompt
# ---------------------------------------------------------------------------

def test_needs_prompt_when_brand_new() -> None:
    master, _, _ = _build_pair_master()
    assert master._ring_needs_save_prompt() is True


def test_needs_prompt_false_after_save_clean(tmp_path: Path) -> None:
    master, _, _ = _build_pair_master()
    master._write_ring_to_path(tmp_path / "demo.scriptreering")
    assert master._ring_needs_save_prompt() is False


def test_needs_prompt_true_after_save_and_membership_change(
    tmp_path: Path,
) -> None:
    """Saved once, then a cell joins → prompt should re-fire."""
    master, a, b = _build_pair_master()
    master._write_ring_to_path(tmp_path / "demo.scriptreering")
    assert master._ring_needs_save_prompt() is False

    c = _spawn(); c.move(b.pos().x() + 56, b.pos().y()); c.show()
    _try_spawn_master(c, b)

    assert master._ring_needs_save_prompt() is True


def test_needs_prompt_false_for_non_master() -> None:
    _fresh_registry()
    cell = _spawn()
    assert cell._ring_needs_save_prompt() is False


def test_needs_prompt_false_for_empty_master() -> None:
    """An empty master is being closed by _check_master_validity —
    nothing worth saving."""
    branding = load_branding()
    m = CellWindow(branding, role="master", hexagon_id="m-empty")
    m._ring_dirty = True  # even with dirty flag set
    assert m._ring_needs_save_prompt() is False
    m.close()


# ---------------------------------------------------------------------------
# 9-10. Close-path dialog wiring
# ---------------------------------------------------------------------------

def test_close_ring_undock_all_prompts_when_unsaved() -> None:
    master, _, _ = _build_pair_master()
    with patch.object(QMessageBox, "question") as m_q:
        m_q.return_value = QMessageBox.StandardButton.Discard
        master._close_ring_undock_all()
    m_q.assert_called_once()


def test_close_ring_undock_all_silent_when_saved_and_clean(
    tmp_path: Path,
) -> None:
    master, _, _ = _build_pair_master()
    master._write_ring_to_path(tmp_path / "demo.scriptreering")
    with patch.object(QMessageBox, "question") as m_q:
        master._close_ring_undock_all()
    m_q.assert_not_called()


def test_close_all_related_prompts_when_unsaved() -> None:
    master, _, _ = _build_pair_master()
    with patch.object(QMessageBox, "question") as m_q:
        m_q.return_value = QMessageBox.StandardButton.Discard
        master._close_all_related()
    m_q.assert_called_once()


def test_close_cancel_aborts_close() -> None:
    """Cancel must leave the master alive."""
    master, _, _ = _build_pair_master()
    member_count_before = len(master._members)
    with patch.object(QMessageBox, "question") as m_q:
        m_q.return_value = QMessageBox.StandardButton.Cancel
        master._close_ring_undock_all()
    # Master and members all still present.
    assert master.role == "master"
    assert len(master._members) == member_count_before


def test_close_save_path_writes_then_closes(tmp_path: Path) -> None:
    """Picking Save in the dialog should trigger the save-as flow
    (because the ring was never saved), then close."""
    master, _, _ = _build_pair_master()
    target = tmp_path / "saved-via-prompt.scriptreering"
    with patch.object(QMessageBox, "question") as m_q, patch(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName",
        return_value=(str(target), ""),
    ):
        m_q.return_value = QMessageBox.StandardButton.Save
        master._close_ring_undock_all()
    assert target.is_file()


def teardown_function(_func) -> None:
    _fresh_registry()
