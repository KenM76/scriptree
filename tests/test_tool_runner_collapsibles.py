"""Tests for the collapsible header / extras / command-line sections
in the runner form panel.

v0.8.0a12+ replaced the Qt-native ``QGroupBox(setCheckable=True)``
pattern (which puts a CHECKBOX in the title bar -- visually reads as
"enable / disable the feature") with :class:`ArrowSection`, a custom
widget that uses a ▶ / ▼ collapse arrow.  The public API is
backward-compatible -- ``setChecked`` / ``isChecked`` / ``toggled``
all still work -- but the underlying widget type changed, so this
file's "Qt-checkable-group-box" assertions were retargeted to test
the new contract:

* ``isChecked()`` / ``isExpanded()`` still report the toggle state.
* The header arrow flips ▶ / ▼ to match.
* The content widget's visibility tracks the toggle.
* Bottom panel still exposes a ``bottom_panel`` property for
  MainWindow's reparent-into-dock dance.

The form panel no longer uses a QSplitter -- the user's v0.8.0a12
direction was "Configuration line and everything below should be
in a separate scroll area from the parameters section -- always
try to stay visible without a scroll bar."  The new shape:

    [Header section]            ← arrow-collapsible
    [Parameters scroll area]    ← takes available space
    [Configurations bar]
    [Extras section]            ← arrow-collapsible
    [Command line section]      ← arrow-collapsible
    [Run / Stop row]
    [Action buttons row]
    [Status]

So this file drops the splitter assertion entirely and replaces it
with a layout-order assertion instead.
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.model import ParamDef, ToolDef  # noqa: E402
from scriptree.ui.arrow_section import ArrowSection  # noqa: E402
from scriptree.ui.tool_runner import ToolRunnerView  # noqa: E402


def _tool() -> ToolDef:
    return ToolDef(
        name="demo",
        executable="/bin/echo",
        description="A demo tool with a description blurb.",
        argument_template=["{x}"],
        params=[ParamDef(id="x", label="X", default="hello")],
    )


# --- header ---------------------------------------------------------------

def test_header_box_exists_and_starts_expanded() -> None:
    v = ToolRunnerView(_tool())
    assert isinstance(v._header_box, ArrowSection)
    # ``isChecked`` aliases to ``isExpanded`` for backward compat.
    assert v._header_box.isChecked() is True
    assert v._header_box.isExpanded() is True
    # Title shows the tool name.
    assert "demo" in v._header_box.title()


def test_collapsing_header_hides_description() -> None:
    v = ToolRunnerView(_tool())
    # Find the description label inside the header section's content.
    from PySide6.QtWidgets import QLabel
    labels = v._header_box.findChildren(QLabel)
    desc_label = next(
        (l for l in labels if "description" in l.text().lower()), None
    )
    assert desc_label is not None
    # Collapse hides the inner content widget which contains the label.
    inner = desc_label.parentWidget()
    assert inner is not None

    v._header_box.setChecked(False)
    assert inner.isHidden() or not inner.isVisible()

    v._header_box.setChecked(True)
    assert not inner.isHidden()


def test_header_works_for_tool_without_description() -> None:
    """When tool.description is empty the header still renders (with a
    placeholder italic note) and is still collapsible."""
    tool = _tool()
    tool.description = ""
    v = ToolRunnerView(tool)
    assert isinstance(v._header_box, ArrowSection)
    assert v._header_box.isChecked() is True


# --- extras ---------------------------------------------------------------

def test_extras_box_starts_expanded() -> None:
    v = ToolRunnerView(_tool())
    assert isinstance(v._extras_box, ArrowSection)
    assert v._extras_box.isChecked() is True
    assert v._extras_edit.isHidden() is False


def test_collapsing_extras_hides_editor() -> None:
    v = ToolRunnerView(_tool())
    v._extras_box.setChecked(False)
    # The arrow section hides its inner content holder; the edit
    # widget itself reports hidden because its parent is hidden.
    assert v._extras_edit.isHidden() or not v._extras_edit.isVisible()
    v._extras_box.setChecked(True)
    assert v._extras_edit.isHidden() is False


def test_extras_collapsed_by_default_in_standalone_mode() -> None:
    """v0.8.0a12 contract: ``set_standalone_mode(True)`` collapses
    the extras section because direct-launches almost never use
    extras (the form is the canonical input surface)."""
    v = ToolRunnerView(_tool())
    assert v._extras_box.isChecked() is True
    v.set_standalone_mode(True)
    assert v._extras_box.isChecked() is False
    assert v._standalone_mode is True


# --- command line ---------------------------------------------------------

def test_cmd_box_starts_expanded() -> None:
    v = ToolRunnerView(_tool())
    assert isinstance(v._cmd_box, ArrowSection)
    assert v._cmd_box.isChecked() is True
    assert v._live_cmd.isHidden() is False


def test_collapsing_cmd_hides_editor_and_options() -> None:
    """Toggling the command-line section off hides BOTH the preview
    text edit AND the Full-path / Word-wrap option row above it
    because they live in the same content widget."""
    v = ToolRunnerView(_tool())
    v._cmd_box.setChecked(False)
    assert v._live_cmd.isHidden() or not v._live_cmd.isVisible()
    assert (
        v._cmd_opts_wrapper.isHidden()
        or not v._cmd_opts_wrapper.isVisible()
    )

    v._cmd_box.setChecked(True)
    assert v._live_cmd.isHidden() is False
    assert v._cmd_opts_wrapper.isHidden() is False


# --- layout ----------------------------------------------------------------

def test_form_panel_layout_order() -> None:
    """v0.8.0a14+ -- cfg widget + bottom pane live inside a
    ``bottom_band`` widget below the form scroll area.  Verify the
    visual order (cfg before bottom pane) is preserved inside the
    band's own layout.
    """
    v = ToolRunnerView(_tool())
    layout = v._bottom_band_layout
    # Walk the band layout and find indices of our key widgets.
    indices: dict[str, int] = {}
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None:
            continue
        w = item.widget()
        if w is None:
            continue
        if w is v._cfg_widget:
            indices["cfg"] = i
        elif w is v._bottom_pane:
            indices["bottom"] = i
    assert "cfg" in indices, "configurations widget not in bottom band"
    assert "bottom" in indices, "bottom pane not in bottom band"
    # Configurations bar appears before bottom pane (extras + cmd).
    assert indices["cfg"] < indices["bottom"]


def test_bottom_panel_property_returns_extras_cmd_container() -> None:
    """The bottom_panel property exposes the run-controls container
    so MainWindow can reparent it into a dedicated dock widget."""
    v = ToolRunnerView(_tool())
    panel = v.bottom_panel
    # The extras + cmd sections live inside it.
    assert v._extras_box.parentWidget() is panel
    assert v._cmd_box.parentWidget() is panel


def test_bottom_panel_round_trips_through_reparent() -> None:
    """install_runner_panels reparents bottom_panel into the
    run-controls dock; uninstall calls ``_return_bottom_panel`` which
    re-inserts it at the original position in the main layout."""
    from scriptree.ui.main_window import MainWindow
    win = MainWindow()
    try:
        runner = ToolRunnerView(_tool())
        win._stack.addWidget(runner)

        bottom = runner.bottom_panel
        original_index = runner._bottom_pane_index

        win._install_runner_panels(runner)
        # Now reparented into the run-controls dock.
        assert win._run_controls_dock.widget() is bottom

        win._uninstall_runner_panels()
        # Reattached to the layout that owns the form's outer
        # widgets at the original index.  Parent is whichever widget
        # owns the main form layout (the form container, not the
        # runner directly).
        new_index = runner._main_form_layout.indexOf(bottom)
        assert new_index == original_index, (
            f"bottom pane re-inserted at index {new_index} "
            f"(expected {original_index})"
        )
    finally:
        win.close()
        win.deleteLater()
        _app.processEvents()


def test_run_button_visible_when_dock_is_tight() -> None:
    """v0.8.0a13 regression: when the form dock is shorter than the
    natural height of (header + params + cfg + extras + cmd + Run
    row + status), the Run button must remain visible.  The
    parameters scroll area shrinks; the bottom band keeps its
    natural height.

    Failure mode pre-fix: ``form_scroll``'s minimum height was its
    content's sizeHint, so Qt's QVBoxLayout kept it tall even when
    the dock was constrained -- pushing the Run buttons off the
    bottom edge.  Fix: ``form_scroll.setMinimumHeight(0)`` +
    ``QSizePolicy.Expanding`` so the scroll area genuinely
    compresses to nothing when space is tight.
    """
    # Build a tool with several params so the form is naturally
    # taller than the dock we'll force on it.
    tool = ToolDef(
        name="big",
        executable="/bin/echo",
        argument_template=["{a}"],
        params=[
            ParamDef(id=f"p{i}", label=f"Param {i}", default=f"v{i}")
            for i in range(15)
        ] + [ParamDef(id="a", label="A", default="x")],
    )
    v = ToolRunnerView(tool)
    # Force a small fixed height typical of a half-screen dock.
    v.resize(600, 280)
    v.show()
    _app.processEvents()

    # The Run button MUST have a non-zero visible region.
    run_btn = v._btn_run
    # ``isVisible`` is True if the widget's window is mapped; it
    # doesn't check whether the widget's geometry is on-screen.
    # ``visibleRegion`` does -- and that's the contract we need.
    assert run_btn.isVisible(), "Run button widget is not visible"
    # The widget's mapped y-coordinate must be within the runner's
    # own height -- otherwise it's been pushed off the bottom edge.
    pos_in_runner = run_btn.mapTo(v, run_btn.rect().topLeft())
    assert pos_in_runner.y() < v.height(), (
        f"Run button is at y={pos_in_runner.y()} but the runner is "
        f"only {v.height()} px tall -- it's been pushed off the "
        f"bottom of the dock."
    )

    v.close()
    v.deleteLater()
    _app.processEvents()


def test_compact_plain_text_edit_one_line_size_hint() -> None:
    """The _CompactPlainTextEdit subclass returns a sizeHint whose
    height is roughly one text line + minimal chrome, instead of
    ~100 px (default QPlainTextEdit)."""
    from PySide6.QtWidgets import QPlainTextEdit
    from scriptree.ui.tool_runner import _CompactPlainTextEdit

    default = QPlainTextEdit()
    compact = _CompactPlainTextEdit()
    # Compact is dramatically shorter than default.
    assert compact.sizeHint().height() < default.sizeHint().height() / 3
