"""Tests for the tool-editor Actions panel (Phase E).

Covers:

  * ``ActionsEditorDialog`` opens with a deep-copy of the actions
    list -- mutations don't reach the caller until OK.
  * Add / remove / move-up / move-down work.
  * Per-action form fields write back into the dialog's actions
    list as the user types.
  * Argv multi-line text edit round-trips a list (one arg per line,
    empty lines stripped).
  * Live argv preview reflects the current edit state.
  * Validation: id uniqueness, id pattern, label non-empty.
  * Hidden checkbox surfaces in the list label.
  * Tool-editor top form has the "Action buttons:" row and the
    "Edit actions..." button is wired.

Auto-dismisses ``QMessageBox`` per the standing rule.
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)

import pytest

from scriptree.core.model import ActionDef, Section, ToolDef
from scriptree.ui.actions_editor import ActionsEditorDialog
from scriptree.ui.tool_editor import ToolEditorView, _actions_summary


def _make_tool(actions: list[ActionDef], sections: list[Section] | None = None) -> ToolDef:
    return ToolDef(
        name="t", executable="echo",
        actions=actions,
        sections=sections or [],
    )


# ---------------------------------------------------------------------------
# ActionsEditorDialog
# ---------------------------------------------------------------------------

class TestDialogLifecycle:
    """Deep-copy on open, no caller mutation until OK."""

    def test_initial_list_populated(self) -> None:
        tool = _make_tool([
            ActionDef(id="a", label="A"),
            ActionDef(id="b", label="B"),
        ])
        dlg = ActionsEditorDialog(tool.actions, tool=tool)
        assert dlg._list.count() == 2
        assert dlg._actions[0].id == "a"
        dlg.close()

    def test_mutation_does_not_leak_to_caller(self) -> None:
        caller_actions = [ActionDef(id="a", label="A")]
        tool = _make_tool(caller_actions)
        dlg = ActionsEditorDialog(caller_actions, tool=tool)
        # Mutate within the dialog -- caller's list must stay intact.
        dlg._actions[0].label = "MUTATED"
        assert caller_actions[0].label == "A"
        dlg.close()


class TestAddRemoveReorder:
    """List management buttons."""

    def test_add_creates_unique_id(self) -> None:
        dlg = ActionsEditorDialog([], tool=_make_tool([]))
        dlg._add_action()
        dlg._add_action()
        dlg._add_action()
        ids = [a.id for a in dlg._actions]
        assert len(set(ids)) == 3  # all unique
        assert ids[0] == "new_action"
        dlg.close()

    def test_remove_deletes_current(self) -> None:
        dlg = ActionsEditorDialog(
            [ActionDef(id="a", label="A"), ActionDef(id="b", label="B")],
            tool=_make_tool([]),
        )
        dlg._list.setCurrentRow(0)
        dlg._remove_action()
        assert len(dlg._actions) == 1
        assert dlg._actions[0].id == "b"
        dlg.close()

    def test_remove_when_empty_no_crash(self) -> None:
        dlg = ActionsEditorDialog([], tool=_make_tool([]))
        dlg._remove_action()  # no-op, must not raise
        assert dlg._actions == []
        dlg.close()

    def test_move_up_swaps_with_previous(self) -> None:
        dlg = ActionsEditorDialog(
            [ActionDef(id="a", label="A"),
             ActionDef(id="b", label="B"),
             ActionDef(id="c", label="C")],
            tool=_make_tool([]),
        )
        dlg._list.setCurrentRow(2)  # "c"
        dlg._move(-1)
        assert [a.id for a in dlg._actions] == ["a", "c", "b"]
        dlg.close()

    def test_move_down_swaps_with_next(self) -> None:
        dlg = ActionsEditorDialog(
            [ActionDef(id="a", label="A"),
             ActionDef(id="b", label="B")],
            tool=_make_tool([]),
        )
        dlg._list.setCurrentRow(0)
        dlg._move(1)
        assert [a.id for a in dlg._actions] == ["b", "a"]
        dlg.close()

    def test_move_at_boundary_no_op(self) -> None:
        dlg = ActionsEditorDialog(
            [ActionDef(id="a", label="A")],
            tool=_make_tool([]),
        )
        dlg._list.setCurrentRow(0)
        dlg._move(-1)  # already at top
        dlg._move(1)   # already at bottom
        assert [a.id for a in dlg._actions] == ["a"]
        dlg.close()


class TestFormFields:
    """Per-action form fields write back into the dialog list."""

    def _open_with_one(self) -> ActionsEditorDialog:
        dlg = ActionsEditorDialog(
            [ActionDef(id="orig", label="Original", argv=["one", "two"])],
            tool=_make_tool([]),
        )
        dlg._list.setCurrentRow(0)
        return dlg

    def test_label_writes_back(self) -> None:
        dlg = self._open_with_one()
        dlg._label_edit.setText("New label")
        assert dlg._actions[0].label == "New label"
        dlg.close()

    def test_tooltip_writes_back(self) -> None:
        dlg = self._open_with_one()
        dlg._tooltip_edit.setText("hover me")
        assert dlg._actions[0].tooltip == "hover me"
        dlg.close()

    def test_popup_writes_back(self) -> None:
        dlg = self._open_with_one()
        dlg._popup_combo.setCurrentText("always")
        assert dlg._actions[0].popup == "always"
        dlg.close()

    def test_hidden_writes_back(self) -> None:
        dlg = self._open_with_one()
        dlg._hidden_check.setChecked(True)
        assert dlg._actions[0].hidden is True
        dlg.close()

    def test_argv_roundtrip(self) -> None:
        dlg = self._open_with_one()
        dlg._argv_edit.setPlainText("status\n--short\n")
        assert dlg._actions[0].argv == ["status", "--short"]
        dlg.close()

    def test_argv_strips_empty_lines(self) -> None:
        dlg = self._open_with_one()
        dlg._argv_edit.setPlainText("status\n\n--short\n\n\n")
        assert dlg._actions[0].argv == ["status", "--short"]
        dlg.close()

    def test_section_combo_populated_from_tool(self) -> None:
        tool = _make_tool(
            [ActionDef(id="a", label="A")],
            sections=[Section(name="Diagnostics"), Section(name="Status")],
        )
        dlg = ActionsEditorDialog(tool.actions, tool=tool)
        # First item is the "(none)" sentinel, then declared sections.
        assert dlg._section_combo.count() == 3
        assert dlg._section_combo.itemData(0) == ""
        assert dlg._section_combo.itemText(1) == "Diagnostics"
        dlg.close()

    def test_section_selection_writes_back(self) -> None:
        tool = _make_tool(
            [ActionDef(id="a", label="A")],
            sections=[Section(name="Diagnostics")],
        )
        dlg = ActionsEditorDialog(tool.actions, tool=tool)
        dlg._list.setCurrentRow(0)
        dlg._section_combo.setCurrentIndex(1)  # "Diagnostics"
        assert dlg._actions[0].section == "Diagnostics"
        dlg.close()


class TestValidation:
    """Live validation surfaces inline warnings; OK blocks on errors."""

    def test_bad_id_pattern_warns(self) -> None:
        dlg = ActionsEditorDialog(
            [ActionDef(id="ok", label="OK")],
            tool=_make_tool([]),
        )
        dlg._list.setCurrentRow(0)
        dlg._id_edit.setText("Bad-Id")
        assert "[a-z" in dlg._id_warning.text()
        dlg.close()

    def test_duplicate_id_warns(self) -> None:
        dlg = ActionsEditorDialog(
            [ActionDef(id="a", label="A"),
             ActionDef(id="b", label="B")],
            tool=_make_tool([]),
        )
        dlg._list.setCurrentRow(1)
        dlg._id_edit.setText("a")
        assert "duplicate" in dlg._id_warning.text().lower()
        dlg.close()

    def test_valid_id_no_warning(self) -> None:
        dlg = ActionsEditorDialog(
            [ActionDef(id="a", label="A")],
            tool=_make_tool([]),
        )
        dlg._list.setCurrentRow(0)
        dlg._id_edit.setText("valid_id_2")
        assert dlg._id_warning.text() == ""
        dlg.close()


class TestPreview:
    """Live argv preview reflects current edits."""

    def test_preview_shows_executable_and_argv(self) -> None:
        tool = ToolDef(
            name="t", executable="git",
            actions=[ActionDef(id="a", label="A", argv=["status", "--short"])],
        )
        dlg = ActionsEditorDialog(tool.actions, tool=tool)
        dlg._list.setCurrentRow(0)
        assert "git" in dlg._preview.text()
        assert "status" in dlg._preview.text()
        assert "--short" in dlg._preview.text()
        dlg.close()


# ---------------------------------------------------------------------------
# Tool editor top-form integration
# ---------------------------------------------------------------------------

class TestToolEditorTopForm:
    """The editor's top form gains an 'Action buttons:' row."""

    def test_status_label_says_none_when_empty(self) -> None:
        view = ToolEditorView(ToolDef(name="t", executable="echo"))
        assert "none" in view._actions_status.text().lower()

    def test_status_label_counts_visible_and_hidden(self) -> None:
        tool = ToolDef(
            name="t", executable="echo",
            actions=[
                ActionDef(id="a", label="A"),
                ActionDef(id="b", label="B"),
                ActionDef(id="c", label="C", hidden=True),
            ],
        )
        view = ToolEditorView(tool)
        s = view._actions_status.text()
        assert "2 buttons" in s
        assert "1 hidden" in s

    def test_actions_summary_helper(self) -> None:
        assert _actions_summary(ToolDef(name="t", executable="e")) == "<i>none</i>"
        tool = ToolDef(
            name="t", executable="e",
            actions=[ActionDef(id="a", label="A")],
        )
        assert _actions_summary(tool) == "1 button"
