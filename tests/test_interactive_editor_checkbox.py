"""ToolEditorView ``Interactive`` checkbox tests.

The checkbox lives in the top group and mirrors
``ToolDef.interactive``.  The save flow has its own coverage in
``test_interactive_io_roundtrip.py``; this file pins the editor wiring.
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)

from scriptree.core.model import ToolDef  # noqa: E402
from scriptree.ui.tool_editor import ToolEditorView  # noqa: E402


def _editor(*, interactive: bool = False) -> ToolEditorView:
    return ToolEditorView(ToolDef(
        name="demo", executable="python", interactive=interactive,
    ))


def test_checkbox_initial_state_matches_tool_false() -> None:
    e = _editor(interactive=False)
    assert e._interactive_check.isChecked() is False


def test_checkbox_initial_state_matches_tool_true() -> None:
    e = _editor(interactive=True)
    assert e._interactive_check.isChecked() is True


def test_toggle_writes_back_to_tooldef() -> None:
    e = _editor(interactive=False)
    e._interactive_check.setChecked(True)
    assert e._tool.interactive is True
    e._interactive_check.setChecked(False)
    assert e._tool.interactive is False


def test_save_round_trip_after_editor_toggle(tmp_path) -> None:
    """End-to-end: build editor, toggle checkbox, call save -> verify
    on-disk JSON has the field."""
    from scriptree.core.io import load_tool
    import json

    e = _editor(interactive=False)
    e._interactive_check.setChecked(True)

    target = tmp_path / "edited.scriptree"
    e._file_path = str(target)
    e.save()

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk.get("interactive") is True
    assert load_tool(target).interactive is True
