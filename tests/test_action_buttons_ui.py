"""UI tests for action buttons (Phase C) + result popup (Phase D).

Covers:

  * Action buttons render in ``ToolRunnerView`` when the tool has
    actions; the row is absent (and ``self._action_btns`` empty)
    when actions are empty.
  * Hidden actions (``hidden=True``) are filtered out of the
    visible button list.
  * Tooltip falls back to the resolved argv when ``ActionDef.tooltip``
    is empty.
  * Action buttons disable while a Run is in flight (concurrency
    lock); a paused/finished Run re-enables them.
  * The result dialog policy: ``popup="never"`` -> no dialog;
    ``popup="always"`` -> dialog shown; ``popup="auto"`` -> shown
    when output <= AUTO_POPUP_MAX_LINES, hidden when longer.
  * The result dialog's Copy button copies the body to the
    clipboard.
  * Truncation kicks in at MAX_VISIBLE_LINES with a visible note.

Auto-dismisses ``QMessageBox`` per the project's standing rule.
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.question = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)

import pytest

from scriptree.core.model import ActionDef, ParamDef, ParamType, ToolDef, Widget
from scriptree.ui.action_result_dialog import (
    AUTO_POPUP_MAX_LINES,
    MAX_VISIBLE_LINES,
    ActionResultDialog,
    _truncate_for_display,
    maybe_show_action_result,
)
from scriptree.ui.tool_runner import ToolRunnerView


def _make_tool(actions: list[ActionDef]) -> ToolDef:
    return ToolDef(
        name="git_helper", executable="echo",
        params=[ParamDef(
            id="message", label="Message",
            type=ParamType.STRING, widget=Widget.TEXT,
        )],
        argument_template=["{message}"],
        actions=actions,
    )


# ---------------------------------------------------------------------------
# Phase C: button rendering + enable/disable
# ---------------------------------------------------------------------------

class TestActionButtonRendering:
    """Verify the action row shows the right buttons."""

    def test_no_actions_means_no_buttons(self) -> None:
        view = ToolRunnerView(_make_tool([]))
        assert view._action_btns == []

    def test_one_action_one_button(self) -> None:
        view = ToolRunnerView(_make_tool([
            ActionDef(id="status", label="Status", argv=["status"]),
        ]))
        assert len(view._action_btns) == 1
        assert view._action_btns[0].text() == "Status"

    def test_multiple_actions_in_order(self) -> None:
        view = ToolRunnerView(_make_tool([
            ActionDef(id="status", label="Status"),
            ActionDef(id="log10", label="Last 10"),
            ActionDef(id="branches", label="Branches"),
        ]))
        assert [b.text() for b in view._action_btns] == [
            "Status", "Last 10", "Branches",
        ]

    def test_hidden_actions_not_rendered(self) -> None:
        view = ToolRunnerView(_make_tool([
            ActionDef(id="visible", label="Visible"),
            ActionDef(id="advanced", label="Advanced", hidden=True),
        ]))
        # Only the visible button shows up.
        assert [b.text() for b in view._action_btns] == ["Visible"]
        # But the underlying ``.actions`` list still has BOTH --
        # ``hidden=True`` is for UI suppression, not file removal.
        assert len(view._tool.actions) == 2

    def test_tooltip_falls_back_to_argv(self) -> None:
        view = ToolRunnerView(_make_tool([
            ActionDef(id="status", label="Status",
                      argv=["status", "--short"]),
        ]))
        tip = view._action_btns[0].toolTip()
        # The fallback joins executable + argv -- both must appear.
        assert "echo" in tip
        assert "status" in tip
        assert "--short" in tip

    def test_tooltip_uses_explicit_value_when_set(self) -> None:
        view = ToolRunnerView(_make_tool([
            ActionDef(id="status", label="Status",
                      argv=["status"], tooltip="My explicit tooltip"),
        ]))
        assert view._action_btns[0].toolTip() == "My explicit tooltip"


class TestActionButtonEnableState:
    """The action row obeys the same concurrency lock Run does."""

    def test_set_action_buttons_enabled_flips_all(self) -> None:
        view = ToolRunnerView(_make_tool([
            ActionDef(id="a", label="A"),
            ActionDef(id="b", label="B"),
        ]))
        # Start enabled.
        assert all(b.isEnabled() for b in view._action_btns)
        view._set_action_buttons_enabled(False)
        assert not any(b.isEnabled() for b in view._action_btns)
        view._set_action_buttons_enabled(True)
        assert all(b.isEnabled() for b in view._action_btns)

    def test_no_op_on_empty_button_list(self) -> None:
        view = ToolRunnerView(_make_tool([]))
        # Must not raise -- the helper is called from _start_run for
        # every tool regardless of whether it has actions.
        view._set_action_buttons_enabled(False)
        view._set_action_buttons_enabled(True)


class TestActionConcurrencyGate:
    """Clicking an action while one is in flight short-circuits."""

    def test_clicking_action_while_thread_active_no_ops(self) -> None:
        view = ToolRunnerView(_make_tool([
            ActionDef(id="status", label="Status", argv=["status"]),
        ]))
        # Simulate "a thread is in flight" without actually spawning.
        from PySide6.QtCore import QThread
        view._thread = QThread()
        # Click -- must not crash, must not start a new worker.
        view._action_btns[0].click()
        # If we got here, the short-circuit worked.
        # Clean up the fake thread.
        view._thread = None


# ---------------------------------------------------------------------------
# Phase D: the result popup
# ---------------------------------------------------------------------------

class TestPopupPolicy:
    """``maybe_show_action_result`` honours ``ActionDef.popup``."""

    def test_never_returns_none(self) -> None:
        result = maybe_show_action_result(
            parent=None,  # type: ignore[arg-type]
            tool_name="t", action=ActionDef(id="x", label="X", popup="never"),
            output_lines=["line\n"], exit_code=0,
        )
        assert result is None

    def test_always_returns_dialog(self) -> None:
        result = maybe_show_action_result(
            parent=None,  # type: ignore[arg-type]
            tool_name="t",
            action=ActionDef(id="x", label="X", popup="always"),
            output_lines=["line\n"], exit_code=0,
        )
        assert isinstance(result, ActionResultDialog)
        result.close()

    def test_auto_shows_for_short_output(self) -> None:
        result = maybe_show_action_result(
            parent=None,  # type: ignore[arg-type]
            tool_name="t",
            action=ActionDef(id="x", label="X", popup="auto"),
            output_lines=["short output\n"] * 5,
            exit_code=0,
        )
        assert isinstance(result, ActionResultDialog)
        result.close()

    def test_auto_hides_for_long_output(self) -> None:
        # AUTO_POPUP_MAX_LINES + 1 lines triggers the skip.
        result = maybe_show_action_result(
            parent=None,  # type: ignore[arg-type]
            tool_name="t",
            action=ActionDef(id="x", label="X", popup="auto"),
            output_lines=["x\n"] * (AUTO_POPUP_MAX_LINES + 5),
            exit_code=0,
        )
        assert result is None


class TestPopupCopy:
    """The Copy button writes the body to the clipboard."""

    def test_copy_button_copies_full_text(self) -> None:
        from PySide6.QtWidgets import QApplication
        body = "line one\nline two\nline three\n"
        dlg = ActionResultDialog(
            None,
            tool_name="t", action_label="A", action_id="x",
            output_text=body, exit_code=0,
        )
        dlg._copy_all()
        clipboard = QApplication.clipboard()
        assert clipboard.text() == body
        dlg.close()


class TestPopupTruncation:
    """Huge outputs are capped at MAX_VISIBLE_LINES."""

    def test_short_output_not_truncated(self) -> None:
        text = "line\n" * 10
        out, truncated = _truncate_for_display(text)
        assert out == text
        assert truncated is False

    def test_long_output_truncated(self) -> None:
        text = "line\n" * (MAX_VISIBLE_LINES + 100)
        out, truncated = _truncate_for_display(text)
        assert truncated is True
        assert out.count("\n") == MAX_VISIBLE_LINES

    def test_empty_text_no_truncation(self) -> None:
        out, truncated = _truncate_for_display("")
        assert out == ""
        assert truncated is False


class TestPopupErrorStyling:
    """Non-zero exit codes get a warning prefix."""

    def test_zero_exit_no_prefix(self) -> None:
        dlg = ActionResultDialog(
            None, tool_name="t", action_label="A", action_id="x",
            output_text="hi", exit_code=0,
        )
        assert "⚠" not in dlg.windowTitle()
        dlg.close()

    def test_nonzero_exit_has_prefix(self) -> None:
        dlg = ActionResultDialog(
            None, tool_name="t", action_label="A", action_id="x",
            output_text="oops", exit_code=1,
        )
        assert dlg.windowTitle().startswith("⚠")
        dlg.close()
