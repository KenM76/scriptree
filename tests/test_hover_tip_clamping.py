"""v0.8.0a2 Bug 12 — hover tooltip stays on-screen.

User-reported: "the hover over cell labels are sometimes displayed
off screen - if I have my cell/ring/forest on the right side of the
screen the hover labels justify right and are mostly off screen.
they also are offset pretty far below the cell."

These tests verify that ``_CellHoverTip.show`` clamps the tooltip
position so it always lands inside the available screen rect, AND
that when a ``cell_rect`` is passed, the tip is centred under the
cell and parked just below it (not offset far down-right of a
single anchor point).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


from scriptree.shell.cell_window import _CellHoverTip  # noqa: E402


def _screen_avail() -> QRect:
    s = QGuiApplication.primaryScreen()
    assert s is not None, "Tests need a primary screen"
    return s.availableGeometry()


def teardown_function(_func) -> None:
    try:
        _CellHoverTip.hide()
    except Exception:  # noqa: BLE001
        pass


def test_tip_centres_under_cell_when_cell_rect_provided() -> None:
    """Centre the tooltip horizontally on the cell and place it 6 px
    below the cell's bottom edge."""
    avail = _screen_avail()
    cell_size = 56
    # Pick a position with plenty of headroom on all sides.
    cell_x = avail.left() + 200
    cell_y = avail.top() + 200
    cell_rect = QRect(cell_x, cell_y, cell_size, cell_size)
    anchor = QPoint(cell_x + cell_size // 2, cell_y + cell_size)

    _CellHoverTip.show("Ring 1", anchor, cell_rect=cell_rect)

    lbl = _CellHoverTip._instance
    assert lbl is not None and lbl.isVisible()
    # Horizontal centre matches cell centre (within ±1 px for int round).
    expected_cx = cell_x + cell_size // 2
    actual_cx = lbl.x() + lbl.width() // 2
    assert abs(actual_cx - expected_cx) <= 1, (
        f"Tip centre {actual_cx} not aligned with cell centre "
        f"{expected_cx}."
    )
    # Top of tip sits just below cell bottom (within 8 px tolerance).
    cell_bottom = cell_y + cell_size
    assert 0 <= lbl.y() - cell_bottom <= 10, (
        f"Tip top {lbl.y()} should sit just below cell bottom "
        f"{cell_bottom} (within ~6 px), not far below."
    )


def test_tip_clamps_left_when_cell_near_right_edge() -> None:
    """When the cell sits near the right edge of the screen the tip
    must shift LEFT so its right edge stays inside the screen.

    The Bug 12 regression had the tip's left edge at the cell
    centre, so for a cell touching the right edge the tip extended
    well past the screen boundary.
    """
    avail = _screen_avail()
    cell_size = 56
    # Park the cell so its right edge is right at avail.right().
    cell_x = avail.right() - cell_size
    cell_y = avail.top() + 200
    cell_rect = QRect(cell_x, cell_y, cell_size, cell_size)
    anchor = QPoint(cell_x + cell_size // 2, cell_y + cell_size)

    _CellHoverTip.show(
        "Ring with a fairly long name", anchor, cell_rect=cell_rect,
    )
    lbl = _CellHoverTip._instance
    assert lbl is not None and lbl.isVisible()
    # Right edge of the tip is inside the available rect.
    tip_right = lbl.x() + lbl.width()
    assert tip_right <= avail.right(), (
        f"Tip right edge {tip_right} extends past screen right edge "
        f"{avail.right()} — clamping failed."
    )
    # Left edge of the tip is inside the available rect.
    assert lbl.x() >= avail.left(), (
        f"Tip left edge {lbl.x()} is left of screen left "
        f"{avail.left()}."
    )


def test_tip_flips_above_when_cell_near_bottom_edge() -> None:
    """A cell sitting at the bottom of the screen makes the
    below-cell position run off-screen; the tip should flip ABOVE
    the cell instead of falling off the bottom."""
    avail = _screen_avail()
    cell_size = 56
    cell_x = avail.left() + 200
    cell_y = avail.bottom() - cell_size  # cell rests on bottom edge
    cell_rect = QRect(cell_x, cell_y, cell_size, cell_size)
    anchor = QPoint(cell_x + cell_size // 2, cell_y + cell_size)

    _CellHoverTip.show("Ring 7", anchor, cell_rect=cell_rect)
    lbl = _CellHoverTip._instance
    assert lbl is not None and lbl.isVisible()
    # Bottom of tip is inside avail.
    tip_bottom = lbl.y() + lbl.height()
    assert tip_bottom <= avail.bottom(), (
        f"Tip bottom {tip_bottom} extends past screen bottom "
        f"{avail.bottom()} — vertical clamp failed."
    )
    # And the tip is positioned ABOVE the cell (or at worst,
    # shifted up to fit), not below.
    assert lbl.y() < cell_y + cell_size, (
        f"Tip top {lbl.y()} is below cell bottom "
        f"{cell_y + cell_size} despite no room below — should "
        f"have flipped above."
    )


def test_legacy_call_without_cell_rect_still_works() -> None:
    """Backward-compat: a call without ``cell_rect=`` still uses the
    legacy +12 / +18 offset and clamps to screen."""
    avail = _screen_avail()
    anchor = QPoint(avail.left() + 200, avail.top() + 200)
    _CellHoverTip.show("Hi", anchor)
    lbl = _CellHoverTip._instance
    assert lbl is not None and lbl.isVisible()
    assert lbl.x() == anchor.x() + 12
    assert lbl.y() == anchor.y() + 18
