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

    def test_folder_list_wraps_list(self) -> None:
        p = ParamDef(
            id="dirs", label="Folders",
            type=ParamType.MULTISELECT, widget=Widget.FOLDER_LIST,
        )
        w = FolderListWidget(p)
        assert isinstance(w._list_resize, ResizableContainer)
        assert w._list_resize.current_child_height() == 160
