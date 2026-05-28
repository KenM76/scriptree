"""Tests for ``ResizableContainer`` -- vertical resize wrapper for
multi-line / list param widgets (v0.8.0a15+).

Covers:

* The container constructs with the child set to ``initial_height``.
* Dragging the handle grows the child.
* Drags can't shrink below ``min_height``.
* No upper cap -- the user can grow the child without limit.
* TextAreaWidget / CheckboxListWidget / FolderListWidget all
  produce a wrapped child whose initial fixed height is the
  expected default and which can be grown via the handle.

Auto-dismisses ``QMessageBox`` per the standing rule.
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMessageBox, QPlainTextEdit

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)

from scriptree.core.model import ParamDef, ParamType, Widget
from scriptree.ui.widgets.param_widgets import (
    CheckboxListWidget,
    FolderListWidget,
    TextAreaWidget,
)
from scriptree.ui.widgets.resizable_container import (
    ResizableContainer,
    _ResizeHandle,
)


class TestContainerBasics:
    """Direct exercise of the wrapper without the param machinery."""

    def test_initial_height_applied_to_child(self) -> None:
        child = QPlainTextEdit()
        c = ResizableContainer(child, initial_height=120, min_height=32)
        assert c.current_child_height() == 120

    def test_drag_grows_child(self) -> None:
        child = QPlainTextEdit()
        c = ResizableContainer(child, initial_height=80, min_height=32)
        c._on_dragged(40)  # simulate 40 px downward drag
        assert c.current_child_height() == 120

    def test_drag_does_not_shrink_below_min(self) -> None:
        child = QPlainTextEdit()
        c = ResizableContainer(child, initial_height=80, min_height=32)
        c._on_dragged(-1000)  # drag way up
        assert c.current_child_height() == 32

    def test_drag_grows_without_upper_cap(self) -> None:
        """Whole point of the change -- the form's outer scroll
        area handles overflow; the wrapper itself doesn't clip."""
        child = QPlainTextEdit()
        c = ResizableContainer(child, initial_height=80, min_height=32)
        c._on_dragged(5000)
        assert c.current_child_height() == 5080

    def test_child_widget_accessor(self) -> None:
        child = QPlainTextEdit()
        c = ResizableContainer(child, initial_height=80)
        assert c.child_widget is child

    def test_handle_emits_dragged_with_delta(self) -> None:
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        h = _ResizeHandle()
        received: list[int] = []
        h.dragged.connect(received.append)

        # Simulate press at y=100, move to y=130.  Use globalPosition
        # because the handler reads ``event.globalPosition().y()``.
        press = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(5, 2), QPointF(5, 100), QPointF(5, 100),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        h.mousePressEvent(press)
        move = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(5, 2), QPointF(5, 130), QPointF(5, 130),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        h.mouseMoveEvent(move)
        assert received == [30]


class TestParamWidgetWiring:
    """Each candidate widget builds with a ResizableContainer
    around its scrollable / list / multi-line inner widget."""

    def test_text_area_wraps_edit(self) -> None:
        p = ParamDef(
            id="msg", label="Msg",
            type=ParamType.STRING, widget=Widget.TEXTAREA,
        )
        w = TextAreaWidget(p)
        assert isinstance(w._resize, ResizableContainer)
        assert w._resize.current_child_height() == 80
        # Dragging the handle still grows the inner edit.
        w._resize._on_dragged(60)
        assert w._resize.current_child_height() == 140
        # And the widget still round-trips its value through the
        # original ``_edit`` reference -- no functional regression.
        w.set_value("hello\nworld")
        assert w.get_value() == "hello\nworld"

    def test_checkbox_list_wraps_scroll(self) -> None:
        p = ParamDef(
            id="opts", label="Opts",
            type=ParamType.MULTISELECT, widget=Widget.CHECKBOX_LIST,
            choices=["a", "b", "c"],
        )
        w = CheckboxListWidget(p)
        assert isinstance(w._scroll_resize, ResizableContainer)
        assert w._scroll_resize.current_child_height() == 160

    def test_dragging_inside_param_form_grows_the_row(self) -> None:
        """v0.8.0a16 regression: when a ResizableContainer lives
        inside a row of a ``ReorderableParamForm`` (which is a
        QListWidget under the hood), dragging the handle should grow
        not just the inner widget but ALSO the row's QListWidgetItem
        sizeHint -- otherwise the resized widget overflows behind the
        next param row.
        """
        from scriptree.ui.tool_runner import ReorderableParamForm
        from PySide6.QtWidgets import QWidget, QHBoxLayout

        form = ReorderableParamForm()
        form.resize(600, 400)

        # Build a row containing a TextAreaWidget (which uses
        # ResizableContainer internally).
        p = ParamDef(
            id="msg", label="Msg",
            type=ParamType.STRING, widget=Widget.TEXTAREA,
        )
        widget = TextAreaWidget(p)
        form.add_param_row("msg", "Message", widget)

        # Capture the row height before drag.
        item = form.item(0)
        h_before = item.sizeHint().height()

        # Grow the inner edit by 80 px via the wrapper's drag path.
        widget._resize._on_dragged(80)

        # The row's QListWidgetItem sizeHint should have grown by
        # roughly the same amount.  Allow some slack for margins
        # but require a meaningful increase, not just zero.
        h_after = form.item(0).sizeHint().height()
        assert h_after > h_before + 40, (
            f"Row sizeHint did not grow with the widget: "
            f"{h_before} -> {h_after}"
        )

    def test_shrink_drag_shrinks_row_sizehint(self) -> None:
        """When the user drags the handle UP to shrink the widget,
        the row's QListWidgetItem sizeHint must shrink with it --
        not stay pinned at the larger value.

        This was the v0.8.0a18 bug the user reported: shrinking
        looked like the widget collapsed from BOTH top AND bottom
        (because the row stayed tall and the smaller container
        was centred inside the still-tall row), and the next row
        didn't move up until the parent window was resized
        (which forced ``ReorderableParamForm.relayout_rows`` to
        re-poll every row's natural sizeHint).  Root cause was a
        ``max(current.height(), ...)`` clamp in
        ``ResizableContainer._on_dragged`` that prevented the row
        sizeHint from ever decreasing.
        """
        from scriptree.ui.tool_runner import ReorderableParamForm
        form = ReorderableParamForm()
        child = QPlainTextEdit()
        rc = ResizableContainer(child, initial_height=100, min_height=20)
        form.add_param_row("p0", "P0", rc)
        # A second row so we can also verify it tracks live.
        form.add_param_row("p1", "P1", QPlainTextEdit())
        form.resize(500, 400)
        form.show()
        _app.processEvents()

        # Grow first, then shrink, then verify the row's sizeHint
        # follows in BOTH directions.
        h_initial = form.item(0).sizeHint().height()
        rc._on_dragged(60)  # grow by 60
        _app.processEvents()
        h_grown = form.item(0).sizeHint().height()
        assert h_grown > h_initial + 40, (
            f"row sizeHint failed to grow: {h_initial} -> {h_grown}"
        )

        rc._on_dragged(-80)  # shrink by 80 (smaller than initial)
        _app.processEvents()
        h_shrunk = form.item(0).sizeHint().height()
        assert h_shrunk < h_grown - 40, (
            f"row sizeHint did NOT shrink with the widget "
            f"({h_grown} -> {h_shrunk}).  Regression: the "
            f"``max(current.height(), ...)`` clamp is back -- the "
            f"row tracks growth but never shrinks, so the widget "
            f"appears centred in a too-tall row and the next row "
            f"stays put."
        )

        # And the second row's y in the viewport must follow the
        # first row's height -- meaning row 2 moves UP live when
        # row 1 shrinks (not waiting for a window resize).
        row1_y = form.visualItemRect(form.item(1)).y()
        assert abs(row1_y - h_shrunk) <= 4, (
            f"Row 1 y ({row1_y}) does not match row 0 height "
            f"({h_shrunk}) -- the QListWidget didn't relayout "
            f"after the shrink.  The next param row will appear "
            f"to stay put until the user resizes the window."
        )

    def test_folder_list_wraps_list(self) -> None:
        p = ParamDef(
            id="dirs", label="Folders",
            type=ParamType.MULTISELECT, widget=Widget.FOLDER_LIST,
        )
        w = FolderListWidget(p)
        assert isinstance(w._list_resize, ResizableContainer)
        assert w._list_resize.current_child_height() == 160
