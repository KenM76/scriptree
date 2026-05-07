"""Tests for the role-aware right-click close/exit menu actions on
``CellWindow``.

UX contract:

* Standalone cell: "Close this cell" + "Exit all"
* Master / ring cell: "Close ring (undock all members)" +
  "Close all related (master + members)" + "Exit all"

These tests build minimal ``CellWindow`` instances and exercise
``_close_this`` / ``_close_ring_undock_all`` / ``_close_all_related`` /
``_exit_all`` directly, mocking ``QApplication.quit`` so the test
process doesn't actually terminate.
"""
from __future__ import annotations

from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

# Auto-dismiss any incidental dialogs.
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.question = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Yes
)


from scriptree.shell.branding_loader import load_branding  # noqa: E402
from scriptree.shell.cell_registry import CellRegistry  # noqa: E402
from scriptree.shell.cell_window import CellWindow  # noqa: E402


def _fresh_registry() -> CellRegistry:
    """Reset the singleton so tests don't share state."""
    reg = CellRegistry.instance()
    # Best-effort: close every hex registered from a prior test.
    try:
        for h in list(reg.standalones()) + list(reg.masters()):
            try:
                h.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    return reg


def _spawn_standalone() -> CellWindow:
    branding = load_branding()
    return CellWindow(branding)


# ---------------------------------------------------------------------------
# _close_this — standalone cell behaviour (sanity)
# ---------------------------------------------------------------------------

def test_close_this_closes_only_this_cell() -> None:
    _fresh_registry()
    h1 = _spawn_standalone()
    h2 = _spawn_standalone()
    h1.show()
    h2.show()
    with patch.object(QApplication, "quit") as m_quit:
        h1._close_this()
    # h1 closed, h2 still alive, no quit because h2 remains.
    assert not h1.isVisible()
    assert h2.isVisible()
    m_quit.assert_not_called()
    h2.close()


def test_close_this_quits_when_last_cell() -> None:
    _fresh_registry()
    only = _spawn_standalone()
    only.show()
    with patch.object(QApplication, "quit") as m_quit:
        only._close_this()
    m_quit.assert_called_once()


# ---------------------------------------------------------------------------
# _exit_all — closes everything regardless of role
# ---------------------------------------------------------------------------

def test_exit_all_closes_every_cell_and_quits() -> None:
    _fresh_registry()
    h1 = _spawn_standalone()
    h2 = _spawn_standalone()
    h3 = _spawn_standalone()
    for h in (h1, h2, h3):
        h.show()
    with patch.object(QApplication, "quit") as m_quit:
        h2._exit_all()
    for h in (h1, h2, h3):
        assert not h.isVisible(), f"{h._id} still visible after _exit_all"
    m_quit.assert_called_once()


# ---------------------------------------------------------------------------
# _close_ring_undock_all — master only
# ---------------------------------------------------------------------------

def test_close_ring_on_standalone_falls_through_to_close_this() -> None:
    """Calling ring-only handlers on a standalone should not crash —
    they fall through to ``_close_this`` so the user gets a sane
    outcome if the wrong handler is wired somehow."""
    _fresh_registry()
    h1 = _spawn_standalone()
    h2 = _spawn_standalone()
    h1.show()
    h2.show()
    with patch.object(QApplication, "quit"):
        h1._close_ring_undock_all()
    assert not h1.isVisible()
    h2.close()


def test_close_all_related_on_standalone_falls_through() -> None:
    _fresh_registry()
    h1 = _spawn_standalone()
    h2 = _spawn_standalone()
    h1.show()
    h2.show()
    with patch.object(QApplication, "quit"):
        h1._close_all_related()
    assert not h1.isVisible()
    h2.close()


# ---------------------------------------------------------------------------
# Integration: master cell with synthetic _members
# ---------------------------------------------------------------------------

def test_close_ring_undock_all_releases_member_links() -> None:
    """When _close_ring_undock_all runs on a (synthetic) master, every
    member should have its ``_group_master_id`` cleared so it
    behaves as a standalone afterward."""
    _fresh_registry()
    master = _spawn_standalone()
    master.role = "master"  # synthesize a master without real docking
    member1 = _spawn_standalone()
    member2 = _spawn_standalone()
    member1._group_master_id = master._id
    member2._group_master_id = master._id
    master._members = {member1._id: member1, member2._id: member2}
    for h in (master, member1, member2):
        h.show()

    with patch.object(QApplication, "quit"):
        master._close_ring_undock_all()

    # Master closed; members still alive AND no longer pointing at master.
    assert not master.isVisible()
    assert member1.isVisible()
    assert member2.isVisible()
    assert member1._group_master_id is None
    assert member2._group_master_id is None
    member1.close()
    member2.close()


def test_close_all_related_closes_master_and_members() -> None:
    _fresh_registry()
    master = _spawn_standalone()
    master.role = "master"
    member1 = _spawn_standalone()
    member2 = _spawn_standalone()
    member1._group_master_id = master._id
    member2._group_master_id = master._id
    master._members = {member1._id: member1, member2._id: member2}
    for h in (master, member1, member2):
        h.show()

    with patch.object(QApplication, "quit") as m_quit:
        master._close_all_related()

    # All three closed; quit fires because nothing remains.
    assert not master.isVisible()
    assert not member1.isVisible()
    assert not member2.isVisible()
    m_quit.assert_called_once()


def test_close_all_related_skips_quit_when_other_cells_remain() -> None:
    """If there's a bystander cell that's NOT in the ring,
    _close_all_related should leave it alone and not quit."""
    _fresh_registry()
    bystander = _spawn_standalone()
    master = _spawn_standalone()
    master.role = "master"
    member = _spawn_standalone()
    member._group_master_id = master._id
    master._members = {member._id: member}
    for h in (bystander, master, member):
        h.show()

    with patch.object(QApplication, "quit") as m_quit:
        master._close_all_related()

    assert bystander.isVisible()
    assert not master.isVisible()
    assert not member.isVisible()
    m_quit.assert_not_called()
    bystander.close()
