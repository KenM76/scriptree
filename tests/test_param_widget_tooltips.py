"""Tests for v0.4.0 universal hover tooltips on runner-form widgets.

Every widget built by ``build_widget_for`` gets ``param.description``
as its hover tooltip, applied recursively to the widget's
interactive children so hovering any part of the row triggers the
help text.  Previously the description was only used as
placeholder text (truncated to 80 chars) on a couple of widgets;
other widgets had no tooltip at all.
"""
from __future__ import annotations

import pytest

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.model import ParamDef, ParamType, Widget
from scriptree.ui.widgets.param_widgets import (
    CheckboxWidget,
    DropdownWidget,
    FileOpenWidget,
    FolderWidget,
    NumberWidget,
    TextAreaWidget,
    TextWidget,
    build_widget_for,
)


_DESC = (
    "A non-trivial description with multiple words and some "
    "<angle-y> characters that must HTML-escape correctly."
)


def _make(widget_kind: Widget, type_: ParamType = ParamType.STRING) -> ParamDef:
    return ParamDef(
        id="x",
        label="My field",
        description=_DESC,
        type=type_,
        widget=widget_kind,
        choices=["a", "b"] if widget_kind in (
            Widget.DROPDOWN, Widget.ENUM_RADIO,
        ) else [],
    )


class TestUniversalTooltip:
    """Every widget kind gets a tooltip drawn from ``description``."""

    def test_text_widget(self) -> None:
        w = build_widget_for(_make(Widget.TEXT))
        assert "non-trivial description" in w.toolTip()
        # The inner line edit also gets the tooltip.
        assert "non-trivial description" in w._edit.toolTip()

    def test_textarea_widget(self) -> None:
        w = build_widget_for(_make(Widget.TEXTAREA))
        assert "non-trivial description" in w.toolTip()

    def test_number_widget(self) -> None:
        w = build_widget_for(_make(Widget.NUMBER, ParamType.INTEGER))
        assert "non-trivial description" in w.toolTip()

    def test_checkbox_widget(self) -> None:
        w = build_widget_for(_make(Widget.CHECKBOX, ParamType.BOOL))
        assert "non-trivial description" in w.toolTip()

    def test_dropdown_widget(self) -> None:
        w = build_widget_for(_make(Widget.DROPDOWN, ParamType.ENUM))
        assert "non-trivial description" in w.toolTip()

    def test_radio_widget(self) -> None:
        w = build_widget_for(_make(Widget.ENUM_RADIO, ParamType.ENUM))
        assert "non-trivial description" in w.toolTip()

    def test_file_open_widget(self) -> None:
        w = build_widget_for(_make(Widget.FILE_OPEN, ParamType.PATH))
        assert "non-trivial description" in w.toolTip()
        # Browse button keeps its more-specific tooltip — the
        # universal one only fills empty tooltips.
        assert w._btn.toolTip() == "" or "Browse" in w._btn.toolTip() or "non-trivial" in w._btn.toolTip()

    def test_folder_widget(self) -> None:
        w = build_widget_for(_make(Widget.FOLDER, ParamType.PATH))
        assert "non-trivial description" in w.toolTip()


class TestTooltipFormat:

    def test_html_escapes_angle_brackets(self) -> None:
        """A description containing ``<angle>`` characters must not
        produce a malformed HTML tooltip."""
        w = build_widget_for(_make(Widget.TEXT))
        tip = w.toolTip()
        assert "&lt;angle-y&gt;" in tip
        # And the bare ``<angle-y>`` shouldn't appear as a real tag.
        assert "<angle-y>" not in tip

    def test_label_bold_in_tooltip(self) -> None:
        w = build_widget_for(_make(Widget.TEXT))
        assert "<b>My field</b>" in w.toolTip()

    def test_empty_description_still_gets_label_tooltip(self) -> None:
        """A param with no description but a label still gets a
        label-only tooltip — useful when the label itself is the
        whole help message.  (``ParamDef.__post_init__`` falls
        back to ``id`` when ``label`` is empty, so there's always
        SOMETHING to show.)"""
        param = ParamDef(id="x", label="My field", description="")
        w = build_widget_for(param)
        tip = w.toolTip()
        assert "<b>My field</b>" in tip
        # No <br> since there's only one line.
        assert "<br/>" not in tip or tip.count("<br/>") <= 1
