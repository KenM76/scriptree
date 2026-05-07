"""Tests for descriptive labels on dropdown choices.

The model stores two parallel lists on each ParamDef:

    choices:       the raw values that end up in argv
    choice_labels: the human-readable labels shown in the dropdown

An empty label entry (or a ``choice_labels`` list shorter than
``choices``) falls back to showing the value verbatim — this is
what keeps legacy .scriptree files without labels looking unchanged.
The DropdownWidget stores the value as Qt user data on each combo
entry, so ``get_value()`` always returns the raw value regardless
of what label is being displayed.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.io import load_tool, save_tool, tool_from_dict, tool_to_dict  # noqa: E402
from scriptree.core.model import (  # noqa: E402
    ParamDef,
    ParamType,
    ToolDef,
    Widget,
)
from scriptree.core.runner import resolve  # noqa: E402
from scriptree.ui.tool_editor import (  # noqa: E402
    ToolEditorView,
    _format_choices,
    _parse_choices,
)
from scriptree.ui.widgets.param_widgets import DropdownWidget  # noqa: E402


def _enum_param(**kwargs) -> ParamDef:
    return ParamDef(
        id="mode",
        label="Mode",
        type=ParamType.ENUM,
        widget=Widget.DROPDOWN,
        **kwargs,
    )


# --- model -----------------------------------------------------------------


class TestLabelForChoice:
    def test_falls_back_to_value_when_labels_empty(self) -> None:
        p = _enum_param(choices=["fast", "slow"])
        assert p.label_for_choice("fast") == "fast"
        assert p.label_for_choice("slow") == "slow"

    def test_returns_label_when_present(self) -> None:
        p = _enum_param(
            choices=["fast", "slow"],
            choice_labels=["Fast mode", "Slow mode"],
        )
        assert p.label_for_choice("fast") == "Fast mode"
        assert p.label_for_choice("slow") == "Slow mode"

    def test_empty_label_entry_falls_back_to_value(self) -> None:
        p = _enum_param(
            choices=["fast", "slow", "auto"],
            choice_labels=["Fast mode", "", "Automatic"],
        )
        assert p.label_for_choice("fast") == "Fast mode"
        assert p.label_for_choice("slow") == "slow"
        assert p.label_for_choice("auto") == "Automatic"

    def test_shorter_label_list_falls_back(self) -> None:
        p = _enum_param(
            choices=["a", "b", "c"],
            choice_labels=["Alpha"],
        )
        assert p.label_for_choice("a") == "Alpha"
        assert p.label_for_choice("b") == "b"
        assert p.label_for_choice("c") == "c"

    def test_unknown_value_returned_verbatim(self) -> None:
        p = _enum_param(choices=["a"], choice_labels=["Alpha"])
        assert p.label_for_choice("zz") == "zz"


# --- IO --------------------------------------------------------------------


class TestChoiceLabelsIO:
    def test_empty_labels_are_not_emitted(self) -> None:
        tool = ToolDef(
            name="t", executable="/bin/true",
            params=[_enum_param(choices=["a", "b"])],
        )
        d = tool_to_dict(tool)
        assert "choice_labels" not in d["params"][0]

    def test_labels_round_trip(self, tmp_path: Path) -> None:
        tool = ToolDef(
            name="t", executable="/bin/true",
            params=[
                _enum_param(
                    choices=["fast", "slow"],
                    choice_labels=["Fast mode", "Slow mode"],
                )
            ],
        )
        path = tmp_path / "t.scriptree"
        save_tool(tool, path)
        reloaded = load_tool(path)
        p = reloaded.param_by_id("mode")
        assert p.choice_labels == ["Fast mode", "Slow mode"]
        assert p.label_for_choice("fast") == "Fast mode"

    def test_legacy_file_without_labels_loads(self) -> None:
        v1 = {
            "schema_version": 1,
            "name": "legacy",
            "executable": "/bin/true",
            "params": [
                {
                    "id": "mode",
                    "label": "Mode",
                    "type": "enum",
                    "widget": "dropdown",
                    "choices": ["a", "b"],
                }
            ],
            "source": {"mode": "manual"},
        }
        tool = tool_from_dict(v1)
        p = tool.param_by_id("mode")
        assert p.choices == ["a", "b"]
        assert p.choice_labels == []
        assert p.label_for_choice("a") == "a"


# --- dropdown widget -------------------------------------------------------


class TestDropdownWidgetLabels:
    def test_displays_labels_not_values(self) -> None:
        p = _enum_param(
            choices=["fast", "slow"],
            choice_labels=["Fast mode", "Slow mode"],
        )
        w = DropdownWidget(p)
        texts = [w._combo.itemText(i) for i in range(w._combo.count())]
        assert texts == ["Fast mode", "Slow mode"]

    def test_get_value_returns_raw_value(self) -> None:
        p = _enum_param(
            choices=["fast", "slow"],
            choice_labels=["Fast mode", "Slow mode"],
            default="slow",
        )
        w = DropdownWidget(p)
        assert w.get_value() == "slow"
        w._combo.setCurrentIndex(0)
        assert w.get_value() == "fast"

    def test_set_value_matches_by_value_not_label(self) -> None:
        p = _enum_param(
            choices=["fast", "slow"],
            choice_labels=["Fast mode", "Slow mode"],
        )
        w = DropdownWidget(p)
        w.set_value("slow")
        assert w.get_value() == "slow"
        assert w._combo.currentText() == "Slow mode"

    def test_default_selects_by_value(self) -> None:
        p = _enum_param(
            choices=["fast", "slow", "auto"],
            choice_labels=["Fast", "Slow", "Auto"],
            default="auto",
        )
        w = DropdownWidget(p)
        assert w.get_value() == "auto"
        assert w._combo.currentText() == "Auto"

    def test_no_labels_still_works(self) -> None:
        p = _enum_param(choices=["a", "b"])
        w = DropdownWidget(p)
        texts = [w._combo.itemText(i) for i in range(w._combo.count())]
        assert texts == ["a", "b"]
        w.set_value("b")
        assert w.get_value() == "b"


# --- runner integration ---------------------------------------------------


class TestDropdownValuesFlowToArgv:
    def test_labeled_enum_emits_raw_value(self) -> None:
        tool = ToolDef(
            name="demo", executable="/bin/echo",
            argument_template=["{mode}"],
            params=[
                _enum_param(
                    choices=["fast", "slow"],
                    choice_labels=["Fast mode", "Slow mode"],
                    default="fast",
                )
            ],
        )
        cmd = resolve(tool, {"mode": "slow"})
        assert cmd.argv == ["/bin/echo", "slow"]


# --- editor text round-trip -----------------------------------------------


class TestParseChoices:
    def test_bare_values(self) -> None:
        values, labels = _parse_choices("fast,slow,auto")
        assert values == ["fast", "slow", "auto"]
        assert labels == ["", "", ""]

    def test_value_equals_label(self) -> None:
        values, labels = _parse_choices("fast=Fast mode,slow=Slow mode,auto")
        assert values == ["fast", "slow", "auto"]
        assert labels == ["Fast mode", "Slow mode", ""]

    def test_whitespace_trimmed(self) -> None:
        values, labels = _parse_choices("  a = Alpha ,  b=Bravo  ")
        assert values == ["a", "b"]
        assert labels == ["Alpha", "Bravo"]

    def test_empty_entries_dropped(self) -> None:
        values, labels = _parse_choices("a,,b,")
        assert values == ["a", "b"]
        assert labels == ["", ""]


class TestFormatChoices:
    def test_bare_values_render_without_equals(self) -> None:
        p = _enum_param(choices=["a", "b"])
        assert _format_choices(p) == "a,b"

    def test_labeled_values_render_with_equals(self) -> None:
        p = _enum_param(
            choices=["fast", "slow"],
            choice_labels=["Fast mode", "Slow mode"],
        )
        assert _format_choices(p) == "fast=Fast mode,slow=Slow mode"

    def test_mixed_labels(self) -> None:
        p = _enum_param(
            choices=["a", "b", "c"],
            choice_labels=["Alpha", "", "Gamma"],
        )
        assert _format_choices(p) == "a=Alpha,b,c=Gamma"


# --- editor integration ---------------------------------------------------


class TestEditorChoicesField:
    def test_typing_value_equals_label_updates_model(self) -> None:
        tool = ToolDef(
            name="t", executable="/bin/true",
            params=[_enum_param(choices=["a"])],
        )
        editor = ToolEditorView(tool)
        editor._param_list.setCurrentRow(0)
        editor._prop_choices.setText("fast=Fast mode,slow=Slow mode")
        p = editor._tool.params[0]
        assert p.choices == ["fast", "slow"]
        assert p.choice_labels == ["Fast mode", "Slow mode"]

    def test_loading_sectioned_param_shows_labeled_text(self) -> None:
        tool = ToolDef(
            name="t", executable="/bin/true",
            params=[
                _enum_param(
                    choices=["a", "b"],
                    choice_labels=["Alpha", "Bravo"],
                )
            ],
        )
        editor = ToolEditorView(tool)
        editor._param_list.setCurrentRow(0)
        assert editor._prop_choices.text() == "a=Alpha,b=Bravo"

    def test_preview_dropdown_shows_labels(self) -> None:
        tool = ToolDef(
            name="t", executable="/bin/true",
            params=[
                _enum_param(
                    choices=["fast", "slow"],
                    choice_labels=["Fast mode", "Slow mode"],
                )
            ],
        )
        editor = ToolEditorView(tool)
        # The preview layout is a QVBoxLayout; the first child widget
        # contains a QFormLayout with the actual param rows (flat case).
        outer = editor._form_preview_layout
        inner_widget = outer.itemAt(0).widget()
        layout = inner_widget.layout()
        field_item = layout.itemAt(0, layout.ItemRole.FieldRole)
        dropdown = field_item.widget()
        assert isinstance(dropdown, DropdownWidget)
        texts = [
            dropdown._combo.itemText(i)
            for i in range(dropdown._combo.count())
        ]
        assert texts == ["Fast mode", "Slow mode"]
