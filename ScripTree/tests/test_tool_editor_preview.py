"""Tests for the live form-preview panel in ToolEditorView.

The preview is rebuilt on every edit that mutates ``self._tool``,
piggybacking on the existing ``_update_preview`` method. These tests
verify the preview stays in sync with edits made through:

- Add / remove / move param
- Type change in the property panel
- Label edit in the property panel
- Required-flag toggle

The preview widgets are expected to be disabled (read-only) since
it's a preview, not an interactive form.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
)

_app = QApplication.instance() or QApplication([])

from scriptree.core.model import (  # noqa: E402
    ParamDef,
    ParamType,
    ToolDef,
    Widget,
)
from scriptree.ui.tool_editor import ToolEditorView  # noqa: E402
from scriptree.ui.widgets.param_widgets import (  # noqa: E402
    CheckboxWidget,
    DropdownWidget,
    TextWidget,
)


def _tool() -> ToolDef:
    return ToolDef(
        name="demo",
        executable="/bin/echo",
        argument_template=["{name}", "{verbose?--verbose}"],
        params=[
            ParamDef(id="name", label="Name", required=True),
            ParamDef(
                id="verbose",
                label="Verbose",
                type=ParamType.BOOL,
                widget=Widget.CHECKBOX,
                default=False,
            ),
        ],
    )


def _flat_form_layout(editor: ToolEditorView) -> QFormLayout:
    """Return the inner QFormLayout for a flat (no-section) tool preview.

    The preview's outer layout is a QVBoxLayout.  For flat tools the
    first child is a QWidget whose layout is the QFormLayout with
    param rows.
    """
    outer = editor._form_preview_layout
    inner_widget = outer.itemAt(0).widget()
    return inner_widget.layout()


def _preview_widgets(editor: ToolEditorView) -> list:
    """Return the field widgets (right column) from the preview form."""
    layout = _flat_form_layout(editor)
    out = []
    for i in range(layout.rowCount()):
        item = layout.itemAt(i, layout.ItemRole.FieldRole)
        if item is not None:
            out.append(item.widget())
    return out


class TestInitialPreview:
    def test_preview_matches_param_count(self) -> None:
        editor = ToolEditorView(_tool())
        layout = _flat_form_layout(editor)
        assert layout.rowCount() == 2

    def test_preview_widgets_are_disabled(self) -> None:
        editor = ToolEditorView(_tool())
        for w in _preview_widgets(editor):
            assert w.isEnabled() is False

    def test_preview_empty_tool_shows_placeholder(self) -> None:
        empty = ToolDef(name="empty", executable="/bin/true")
        editor = ToolEditorView(empty)
        # With no params the outer VBoxLayout holds a placeholder QLabel.
        outer = editor._form_preview_layout
        assert outer.count() >= 1
        w = outer.itemAt(0).widget()
        assert isinstance(w, QLabel)

    def test_preview_uses_same_widget_factory_as_runtime(self) -> None:
        editor = ToolEditorView(_tool())
        widgets = _preview_widgets(editor)
        # First param is a text field, second is a checkbox.
        assert isinstance(widgets[0], TextWidget)
        assert isinstance(widgets[1], CheckboxWidget)


class TestPreviewTracksAddRemove:
    def test_add_param_grows_preview(self) -> None:
        editor = ToolEditorView(_tool())
        assert _flat_form_layout(editor).rowCount() == 2
        editor._add_param()
        assert _flat_form_layout(editor).rowCount() == 3

    def test_remove_param_shrinks_preview(self) -> None:
        editor = ToolEditorView(_tool())
        editor._param_list.setCurrentRow(0)
        editor._remove_param()
        assert _flat_form_layout(editor).rowCount() == 1

    def test_move_up_preserves_row_count(self) -> None:
        editor = ToolEditorView(_tool())
        editor._param_list.setCurrentRow(1)
        editor._move_param_up()
        assert _flat_form_layout(editor).rowCount() == 2
        # The widget order should mirror the new param order.
        widgets = _preview_widgets(editor)
        assert isinstance(widgets[0], CheckboxWidget)
        assert isinstance(widgets[1], TextWidget)


class TestPreviewTracksPropertyEdits:
    def test_type_change_rebuilds_widget(self) -> None:
        editor = ToolEditorView(_tool())
        # Select the 'name' param.
        editor._param_list.setCurrentRow(0)
        # Switch its type to enum.
        idx = editor._prop_type.findData(ParamType.ENUM)
        editor._prop_type.setCurrentIndex(idx)
        # Preview should now contain a dropdown at row 0.
        widgets = _preview_widgets(editor)
        assert isinstance(widgets[0], DropdownWidget)

    def test_required_toggle_shows_asterisk(self) -> None:
        editor = ToolEditorView(_tool())
        editor._param_list.setCurrentRow(1)  # verbose (not required)
        editor._prop_required.setChecked(True)
        # Find the label for row 1 and verify it has '*'.
        layout = _flat_form_layout(editor)
        label_item = layout.itemAt(1, layout.ItemRole.LabelRole)
        assert label_item is not None
        label = label_item.widget()
        assert "*" in label.text()

    def test_label_edit_updates_preview_label(self) -> None:
        editor = ToolEditorView(_tool())
        editor._param_list.setCurrentRow(0)
        editor._prop_label.setText("Renamed Thing")
        layout = _flat_form_layout(editor)
        label_item = layout.itemAt(0, layout.ItemRole.LabelRole)
        label = label_item.widget()
        assert "Renamed Thing" in label.text()

    def test_choices_edit_propagates_to_preview_dropdown(self) -> None:
        editor = ToolEditorView(_tool())
        editor._param_list.setCurrentRow(0)
        # First make it an enum.
        idx = editor._prop_type.findData(ParamType.ENUM)
        editor._prop_type.setCurrentIndex(idx)
        # Now edit choices.
        editor._prop_choices.setText("fast,slow,auto")
        widgets = _preview_widgets(editor)
        combo = widgets[0]
        assert isinstance(combo, DropdownWidget)
        # Extract the combobox items.
        texts = [combo._combo.itemText(i) for i in range(combo._combo.count())]
        assert texts == ["fast", "slow", "auto"]


class TestFindPreviewIntegration:
    """Round-trip: parse find.exe help → hand to editor → preview shows
    all the detected params."""

    FIND_HELP = '''\
Searches for a text string in a file or files.

FIND [/V] [/C] [/N] [/I] [/OFF[LINE]] "string" [[drive:][path]filename[ ...]]

  /V         Displays all lines NOT containing the specified string.
  /C         Displays only the count of lines containing the string.
  /N         Displays line numbers with the displayed lines.
  /I         Ignores the case of characters when searching for the string.
  /OFF[LINE] Do not skip files with offline attribute set.
  "string"   Specifies the text string to find.
  [drive:][path]filename
             Specifies a file or files to search.
'''

    def test_parsed_find_tool_renders_in_preview(self) -> None:
        from scriptree.core.parser.plugins import winhelp
        tool = winhelp.detect(self.FIND_HELP)
        tool.name = "find"
        tool.executable = "C:/Windows/SysWOW64/find.exe"
        editor = ToolEditorView(tool)
        # 5 bare flags + 2 positionals = 7 rows in the preview.
        assert _flat_form_layout(editor).rowCount() == 7
        # The quoted-string positional is a TextWidget, the bracketed
        # positional is a path picker — check classes.
        widgets = _preview_widgets(editor)
        # Find the 'string' widget.
        string_idx = next(
            i for i, p in enumerate(tool.params) if p.id == "string"
        )
        assert isinstance(widgets[string_idx], TextWidget)
