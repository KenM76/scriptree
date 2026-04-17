"""Regression tests for cursor preservation in the live command preview.

Before this fix, every edit to the command preview would call
``_update_live_cmd`` at the end of the edit handler, which in turn
called ``setPlainText`` — and ``QPlainTextEdit.setPlainText``
unconditionally jumps the cursor to the start. The symptom: you could
only type one character in the middle of a line before being yanked
back to the start.

The fix has two parts:

1. ``_on_live_cmd_edited`` no longer re-canonicalizes the preview
   at the end of its own edit path. The reconcile has already
   pushed changes into the widgets, and subsequent refreshes happen
   naturally via the widget valueChanged signals.

2. ``_update_live_cmd`` now uses ``_set_live_cmd_preserving_cursor``
   which saves the cursor position + selection across the setPlainText
   call and restores them afterwards, clamped to the new text
   length. It also skips setPlainText entirely when the text is already
   identical (the common no-op path).
"""
from __future__ import annotations

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.model import ParamDef, ToolDef  # noqa: E402
from scriptree.ui.tool_runner import ToolRunnerView  # noqa: E402


def _tool() -> ToolDef:
    return ToolDef(
        name="demo",
        executable="/bin/echo",
        argument_template=["{name}"],
        params=[ParamDef(id="name", label="Name", default="hello")],
    )


def _cursor_pos(view: ToolRunnerView) -> int:
    return view._live_cmd.textCursor().position()


def _set_cursor_pos(view: ToolRunnerView, pos: int) -> None:
    tc = view._live_cmd.textCursor()
    tc.setPosition(pos)
    view._live_cmd.setTextCursor(tc)


class TestCursorPreservation:
    def test_update_live_cmd_noop_keeps_cursor(self) -> None:
        view = ToolRunnerView(_tool())
        # Whatever the initial text is, position the cursor somewhere
        # in the middle and verify an idempotent refresh doesn't move
        # it.
        text = view._live_cmd.toPlainText()
        assert len(text) >= 4
        _set_cursor_pos(view, 3)
        view._update_live_cmd()
        assert _cursor_pos(view) == 3

    def test_set_preserving_clamps_to_new_length(self) -> None:
        view = ToolRunnerView(_tool())
        view._live_cmd.setPlainText("echo middle of the line")
        _set_cursor_pos(view, 18)
        view._set_live_cmd_preserving_cursor("echo short")
        # Old position 18 > new length 10 — clamp to end of new text.
        assert view._live_cmd.toPlainText() == "echo short"
        assert _cursor_pos(view) == 10

    def test_set_preserving_keeps_mid_line_position(self) -> None:
        view = ToolRunnerView(_tool())
        view._live_cmd.setPlainText("echo hello world")
        _set_cursor_pos(view, 7)  # between 'e' and 'l' of 'hello'
        view._set_live_cmd_preserving_cursor("echo hello planet")
        # Position 7 is still valid in the new text.
        assert _cursor_pos(view) == 7

    def test_on_live_cmd_edited_does_not_re_render(self) -> None:
        """After a successful reconcile the preview text must stay as
        the user typed it, not get replaced with a canonical form."""
        view = ToolRunnerView(_tool())
        # Simulate the textChanged path: set the text under the guard
        # then call the handler manually.
        typed = "/bin/echo goodbye"
        view._updating = True
        view._live_cmd.setPlainText(typed)
        view._updating = False
        view._on_live_cmd_edited(typed)
        # The text should still be exactly what the user typed
        # (no canonical re-render happened).
        assert view._live_cmd.toPlainText() == typed

    def test_typing_in_middle_preserves_cursor_across_full_path_toggle(
        self,
    ) -> None:
        """The Full Path toggle triggers _update_live_cmd which does a
        real setPlainText — that path must also preserve cursor."""
        view = ToolRunnerView(_tool())
        # Seed the preview with the canonical text first.
        view._update_live_cmd()
        text = view._live_cmd.toPlainText()
        assert len(text) >= 3
        _set_cursor_pos(view, 2)
        # Toggle full-path on — this changes the text (basename →
        # full path) so the setPlainText branch IS taken.
        view._chk_full_path.setChecked(True)
        new_text = view._live_cmd.toPlainText()
        # Clamped to new length if needed; never yanked past 2 unless
        # the new text is shorter (it shouldn't be for full path).
        assert new_text != text  # text changed
        assert _cursor_pos(view) <= len(new_text)
        # For full path the new text is LONGER than the basename, so
        # the saved position 2 should be preserved exactly.
        assert _cursor_pos(view) == 2
