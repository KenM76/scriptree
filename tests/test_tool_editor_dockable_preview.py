"""Tests for the dockable form-preview panel inside ToolEditorView.

The preview now lives in a real ``QDockWidget`` hosted by an internal
``QMainWindow`` inside the editor.  Users can detach / float / hide it
just like any other dock; the rest of the editor (param list, template,
buttons) is the host's central widget.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDockWidget, QMainWindow

_app = QApplication.instance() or QApplication([])

from scriptree.core.model import ParamDef, ParamType, ToolDef  # noqa: E402
from scriptree.ui.tool_editor import ToolEditorView  # noqa: E402


def _editor() -> ToolEditorView:
    tool = ToolDef(
        name="demo",
        executable="python",
        params=[
            ParamDef(id="x", label="X", type=ParamType.STRING),
        ],
    )
    return ToolEditorView(tool)


# ---------------------------------------------------------------------------
# Structure: editor hosts a QMainWindow with a QDockWidget for preview.
# ---------------------------------------------------------------------------

def test_editor_has_internal_qmainwindow_host() -> None:
    e = _editor()
    assert isinstance(e._preview_host, QMainWindow)
    # The host is laid out inside the editor — not a separate
    # top-level window — so it must have a parent widget.
    assert e._preview_host.parentWidget() is not None
    # And it must not paint as its own top-level window.
    assert not e._preview_host.isWindow()


def test_editor_preview_dock_is_qdockwidget() -> None:
    e = _editor()
    assert isinstance(e._preview_dock, QDockWidget)
    assert e._preview_dock.parent() is e._preview_host


def test_preview_dock_features_allow_float_and_close() -> None:
    e = _editor()
    feats = e._preview_dock.features()
    assert feats & QDockWidget.DockWidgetFeature.DockWidgetFloatable
    assert feats & QDockWidget.DockWidgetFeature.DockWidgetMovable
    assert feats & QDockWidget.DockWidgetFeature.DockWidgetClosable


def test_preview_dock_starts_in_right_dock_area() -> None:
    e = _editor()
    area = e._preview_host.dockWidgetArea(e._preview_dock)
    assert area == Qt.DockWidgetArea.RightDockWidgetArea


def test_preview_dock_allows_all_areas() -> None:
    e = _editor()
    assert (
        e._preview_dock.allowedAreas()
        == Qt.DockWidgetArea.AllDockWidgetAreas
    )


def test_preview_dock_can_float() -> None:
    """Float and re-dock the preview to confirm Qt accepts the move."""
    e = _editor()
    dock = e._preview_dock
    dock.setFloating(True)
    assert dock.isFloating()
    dock.setFloating(False)
    assert not dock.isFloating()
    # After re-dock it should still belong to the host.
    assert dock.parent() is e._preview_host


def test_preview_dock_close_then_show() -> None:
    """Closing then showing the dock must flip its hidden state.

    We use ``isHidden()`` rather than ``isVisible()`` because a
    QDockWidget's visibility depends on the host QMainWindow itself
    being visible, which it isn't in this offscreen test context.
    """
    e = _editor()
    dock = e._preview_dock
    dock.close()
    assert dock.isHidden()
    dock.show()
    assert not dock.isHidden()


def test_preview_dock_accessor_returns_dock() -> None:
    e = _editor()
    assert e.preview_dock() is e._preview_dock


def test_preview_still_rebuilds_on_param_changes() -> None:
    """Moving the preview into a dock must not break the per-mutation
    rebuild contract — the form preview content must still update
    when the tool definition changes."""
    e = _editor()
    container = e._form_preview_container
    initial_children = container.findChildren(object)
    e._tool.params.append(
        ParamDef(id="y", label="Y", type=ParamType.STRING),
    )
    e._refresh_param_list()
    e._rebuild_form_preview()
    new_children = container.findChildren(object)
    # The container must have repopulated (at least the same count;
    # exact widget identity isn't guaranteed because the rebuild
    # tears down the previous contents).
    assert len(new_children) >= len(initial_children)
