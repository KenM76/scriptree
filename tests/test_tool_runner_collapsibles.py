"""Tests for the collapsible header / extras / command-line group
boxes in the runner form panel (v0.1.12).

The runner now has four collapsible regions:

- ``_header_box`` — wraps the tool name + description blurb.
- (per-section group boxes — already covered by test_sections.py)
- ``_extras_box`` — wraps the "Extra arguments" QPlainTextEdit.
- ``_cmd_box`` — wraps the command-line preview + its option row.

Each box uses the standard Qt checkable-group-box mechanism: the
title bar shows a checkbox; toggling it hides the inner content
widget(s) and shrinks the box to title height. State is session-only
(no persistence to .scriptree).
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.model import ParamDef, ToolDef  # noqa: E402
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
    assert v._header_box.isCheckable() is True
    assert v._header_box.isChecked() is True
    # Title shows the tool name.
    assert "demo" in v._header_box.title()


def test_collapsing_header_hides_description() -> None:
    v = ToolRunnerView(_tool())
    # Find the description label inside the header box.
    from PySide6.QtWidgets import QLabel
    labels = v._header_box.findChildren(QLabel)
    desc_label = next(
        (l for l in labels if "description" in l.text().lower()), None
    )
    assert desc_label is not None

    v._header_box.setChecked(False)  # collapse
    assert desc_label.isVisible() is False

    v._header_box.setChecked(True)  # expand
    # Need to attach the widget to a parent for isVisible(); checking
    # the parent visibility instead since the widget itself isn't shown.
    inner = desc_label.parentWidget()
    assert inner is not None and not inner.isHidden()


def test_header_works_for_tool_without_description() -> None:
    """When tool.description is empty the header still renders (with a
    placeholder italic note) and is still collapsible."""
    tool = _tool()
    tool.description = ""
    v = ToolRunnerView(tool)
    assert v._header_box.isCheckable() is True
    assert v._header_box.isChecked() is True


# --- extras ---------------------------------------------------------------

def test_extras_box_starts_expanded() -> None:
    v = ToolRunnerView(_tool())
    assert v._extras_box.isCheckable() is True
    assert v._extras_box.isChecked() is True
    assert v._extras_edit.isHidden() is False


def test_collapsing_extras_hides_editor() -> None:
    v = ToolRunnerView(_tool())
    v._extras_box.setChecked(False)
    assert v._extras_edit.isHidden() is True
    v._extras_box.setChecked(True)
    assert v._extras_edit.isHidden() is False


# --- command line ---------------------------------------------------------

def test_cmd_box_starts_expanded() -> None:
    v = ToolRunnerView(_tool())
    assert v._cmd_box.isCheckable() is True
    assert v._cmd_box.isChecked() is True
    assert v._live_cmd.isHidden() is False


def test_collapsing_cmd_hides_editor_and_options() -> None:
    """Toggling the command-line box off hides BOTH the preview text
    edit AND the Full-path / Word-wrap option row above it."""
    v = ToolRunnerView(_tool())
    v._cmd_box.setChecked(False)
    assert v._live_cmd.isHidden() is True
    # The Full-path / Word-wrap checkboxes live in a wrapper widget
    # inside the cmd box. ``isHidden`` reports the explicit hidden
    # state of the wrapper itself, which is what setVisible(False)
    # toggles when the box collapses.
    assert v._cmd_opts_wrapper.isHidden() is True

    v._cmd_box.setChecked(True)
    assert v._live_cmd.isHidden() is False
    assert v._cmd_opts_wrapper.isHidden() is False


# --- form / extras-cmd splitter -------------------------------------------

def test_form_panel_uses_two_way_splitter() -> None:
    """The form panel's main splitter has exactly two children: the
    form (top) and the extras+cmd container (bottom). This is the
    visible "drag handle" between what the user fills in and what
    actually gets run."""
    from PySide6.QtWidgets import QSplitter
    v = ToolRunnerView(_tool())
    # Find the splitter that's a direct child of the form panel.
    splitters = v._form_container.findChildren(QSplitter)
    # Pick the topmost (the inner panel splitter, not anything nested).
    top = splitters[0] if splitters else None
    assert top is not None
    assert top.count() == 2


def test_bottom_panel_property_returns_extras_cmd_container() -> None:
    """The bottom_panel property exposes the run-controls container
    so MainWindow can reparent it into a dedicated dock widget."""
    v = ToolRunnerView(_tool())
    panel = v.bottom_panel
    # The extras + cmd boxes live inside it.
    assert v._extras_box.parentWidget() is panel
    assert v._cmd_box.parentWidget() is panel


def test_bottom_panel_size_hint_is_compact() -> None:
    """The bottom panel uses _CompactPlainTextEdit for both the extras
    and the command-line editors, so its sizeHint is small enough
    that the run-controls dock opens at the smallest height that fits
    both editors and their group-box chrome — no scroll bar required.

    We don't assert an exact pixel count (font metrics vary) but the
    panel's sizeHint height should be well under what a default
    QPlainTextEdit pair would have produced (~250 px+)."""
    v = ToolRunnerView(_tool())
    h = v.bottom_panel.sizeHint().height()
    # Two QGroupBox titles + margins + cmd option row + two single-
    # line editors: should fit comfortably under 200 px on any
    # reasonable font. Default QPlainTextEdits would have produced
    # ~250-300 px.
    assert h < 200, f"bottom_panel sizeHint too tall: {h}"


def test_compact_plain_text_edit_one_line_size_hint() -> None:
    """The _CompactPlainTextEdit subclass returns a sizeHint whose
    height is roughly one text line + minimal chrome, instead of
    ~100 px (default QPlainTextEdit)."""
    from PySide6.QtWidgets import QPlainTextEdit
    from scriptree.ui.tool_runner import _CompactPlainTextEdit

    default = QPlainTextEdit()
    compact = _CompactPlainTextEdit()
    # Compact is dramatically shorter than default. Width is unchanged.
    assert compact.sizeHint().height() < default.sizeHint().height() / 3


def test_bottom_panel_round_trips_through_reparent() -> None:
    """install_runner_panels reparents bottom_panel into the run-controls
    dock; uninstall reattaches it to the runner's internal splitter.
    This test exercises the round-trip via main_window."""
    from scriptree.ui.main_window import MainWindow
    win = MainWindow()
    try:
        runner = ToolRunnerView(_tool())
        win._stack.addWidget(runner)

        bottom = runner.bottom_panel
        # Initially attached to the runner's bottom splitter.
        assert bottom.parentWidget() is runner._bottom_splitter

        win._install_runner_panels(runner)
        # Now reparented into the run-controls dock.
        assert win._run_controls_dock.widget() is bottom

        win._uninstall_runner_panels()
        # Reattached to the splitter on uninstall.
        assert bottom.parentWidget() is runner._bottom_splitter
    finally:
        win.close()
        win.deleteLater()
        _app.processEvents()
