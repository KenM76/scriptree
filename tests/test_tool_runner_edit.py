"""Tests for the editable command preview + extras wiring in ToolRunnerView.

Integration-style: builds a real ToolRunnerView against an in-memory
ToolDef, simulates user edits by calling the `textEdited`/toggled
slots directly, and asserts on the resulting widget values, extras
list, and final argv that would be passed to subprocess.

No event loop runs — we poke slots and read state.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.model import (  # noqa: E402
    ParamDef,
    ParamType,
    ToolDef,
    Widget,
)
from scriptree.core.runner import build_full_argv  # noqa: E402
from scriptree.ui.tool_runner import ToolRunnerView  # noqa: E402


# --- fixture: a tasklist-shaped tool --------------------------------------

def _tasklist() -> ToolDef:
    return ToolDef(
        name="tasklist",
        executable="C:/Windows/SysWOW64/tasklist.exe",
        argument_template=[
            ["/S", "{system}"],
            ["/U", "{user}"],
            "{svc?/SVC}",
            ["/FO", "{format}"],
            "{nh?/NH}",
        ],
        params=[
            ParamDef(id="system"),
            ParamDef(id="user"),
            ParamDef(
                id="svc",
                type=ParamType.BOOL,
                widget=Widget.CHECKBOX,
                default=False,
            ),
            ParamDef(
                id="format",
                type=ParamType.ENUM,
                widget=Widget.DROPDOWN,
                choices=["TABLE", "LIST", "CSV"],
                default="TABLE",
            ),
            ParamDef(
                id="nh",
                type=ParamType.BOOL,
                widget=Widget.CHECKBOX,
                default=False,
            ),
        ],
    )


# --- full-path checkbox ---------------------------------------------------

class TestFullPathCheckbox:
    def test_basename_default(self) -> None:
        runner = ToolRunnerView(_tasklist())
        assert "tasklist.exe" in runner._live_cmd.toPlainText()
        assert "C:/Windows" not in runner._live_cmd.toPlainText()

    def test_toggling_shows_full_path(self) -> None:
        runner = ToolRunnerView(_tasklist())
        runner._chk_full_path.setChecked(True)
        assert "C:/Windows/SysWOW64/tasklist.exe" in runner._live_cmd.toPlainText()

    def test_toggling_back_hides_full_path(self) -> None:
        runner = ToolRunnerView(_tasklist())
        runner._chk_full_path.setChecked(True)
        runner._chk_full_path.setChecked(False)
        assert "C:/Windows/SysWOW64" not in runner._live_cmd.toPlainText()
        assert "tasklist.exe" in runner._live_cmd.toPlainText()


# --- edit the preview → widgets update ------------------------------------

class TestPreviewEditUpdatesWidgets:
    def test_editing_group_value_updates_widget(self) -> None:
        runner = ToolRunnerView(_tasklist())
        # Simulate: user types /S SERVER01 /FO TABLE after the exe.
        runner._on_live_cmd_edited("tasklist.exe /S SERVER01 /FO TABLE")
        assert runner._widgets["system"].get_value() == "SERVER01"
        assert runner._widgets["format"].get_value() == "TABLE"

    def test_editing_adds_conditional_flag(self) -> None:
        runner = ToolRunnerView(_tasklist())
        runner._on_live_cmd_edited("tasklist.exe /SVC /FO TABLE")
        assert runner._widgets["svc"].get_value() is True

    def test_removing_conditional_flag_unchecks(self) -> None:
        runner = ToolRunnerView(_tasklist())
        # Start by checking svc.
        runner._widgets["svc"].set_value(True)
        assert "/SVC" in runner._live_cmd.toPlainText()
        # Now user edits the preview to drop /SVC.
        runner._on_live_cmd_edited("tasklist.exe /FO TABLE")
        assert runner._widgets["svc"].get_value() is False

    def test_dropdown_value_from_edit(self) -> None:
        runner = ToolRunnerView(_tasklist())
        runner._on_live_cmd_edited("tasklist.exe /FO CSV")
        assert runner._widgets["format"].get_value() == "CSV"


# --- extras path ----------------------------------------------------------

class TestExtras:
    def test_unknown_tokens_land_in_extras(self) -> None:
        runner = ToolRunnerView(_tasklist())
        runner._on_live_cmd_edited(
            "tasklist.exe /FO CSV --debug 2 --log-file D:/run.log"
        )
        assert runner._extras == [
            "--debug", "2", "--log-file", "D:/run.log"
        ]
        # And the extras edit widget shows them.
        assert "--debug" in runner._extras_edit.toPlainText()
        assert "D:/run.log" in runner._extras_edit.toPlainText()

    def test_extras_survive_widget_edit(self) -> None:
        runner = ToolRunnerView(_tasklist())
        runner._on_live_cmd_edited(
            "tasklist.exe /FO CSV --debug 2"
        )
        # Now the user flips a checkbox in the form.
        runner._widgets["svc"].set_value(True)
        # Extras should still be present.
        assert runner._extras == ["--debug", "2"]
        # And the preview text includes them.
        assert "--debug" in runner._live_cmd.toPlainText()
        assert "/SVC" in runner._live_cmd.toPlainText()

    def test_typing_directly_into_extras_box(self) -> None:
        runner = ToolRunnerView(_tasklist())
        runner._extras_edit.setPlainText("--foo bar --baz")
        # setPlainText fires textChanged → _on_extras_edited.
        assert runner._extras == ["--foo", "bar", "--baz"]
        # Preview now includes them.
        assert "--foo" in runner._live_cmd.toPlainText()


# --- argv that gets passed to subprocess ---------------------------------

class TestBuildFullArgv:
    def test_argv_includes_extras(self) -> None:
        runner = ToolRunnerView(_tasklist())
        runner._on_live_cmd_edited(
            "tasklist.exe /SVC /FO CSV --debug 2"
        )
        cmd = build_full_argv(
            runner._tool,
            runner._collect_values(),
            runner._extras,
            ignore_required=True,
        )
        assert cmd.argv[0].endswith("tasklist.exe")
        assert "/SVC" in cmd.argv
        assert "/FO" in cmd.argv
        assert "CSV" in cmd.argv
        # Extras land after the GUI-derived tokens.
        assert cmd.argv[-2:] == ["--debug", "2"]

    def test_copy_argv_picks_up_extras(self) -> None:
        from PySide6.QtWidgets import QApplication as QA

        runner = ToolRunnerView(_tasklist())
        runner._on_live_cmd_edited(
            "tasklist.exe --extra-only-flag"
        )
        runner._copy_argv()
        clip = QA.clipboard().text()
        assert "--extra-only-flag" in clip
        assert "tasklist.exe" in clip


# --- loop guard: setting a widget doesn't wipe extras --------------------

class TestLoopGuard:
    def test_preview_edit_then_widget_change_preserves_extras(self) -> None:
        runner = ToolRunnerView(_tasklist())
        runner._on_live_cmd_edited("tasklist.exe /FO CSV --debug 2")
        assert runner._extras == ["--debug", "2"]
        runner._widgets["svc"].set_value(True)
        # The valueChanged signal triggered _update_live_cmd which
        # must NOT have cleared extras.
        assert runner._extras == ["--debug", "2"]

    def test_no_infinite_loop_on_programmatic_widget_set(self) -> None:
        """If reconcile_edit updates widgets, valueChanged fires and
        calls _update_live_cmd. The guard should prevent that from
        calling reconcile_edit again (which would read its own output)."""
        runner = ToolRunnerView(_tasklist())
        # This used to loop without the guard. Just verify it returns.
        runner._on_live_cmd_edited("tasklist.exe /S S1 /U U1 /FO LIST")
        assert runner._widgets["system"].get_value() == "S1"
        assert runner._widgets["user"].get_value() == "U1"
        assert runner._widgets["format"].get_value() == "LIST"


# --- unparseable edit -----------------------------------------------------

class TestUnparseable:
    def test_unclosed_quote_does_not_crash(self) -> None:
        runner = ToolRunnerView(_tasklist())
        # Save current state.
        before_svc = runner._widgets["svc"].get_value()
        before_extras = list(runner._extras)
        runner._on_live_cmd_edited('tasklist.exe /FI "unclosed')
        # State should be unchanged.
        assert runner._widgets["svc"].get_value() == before_svc
        assert runner._extras == before_extras
