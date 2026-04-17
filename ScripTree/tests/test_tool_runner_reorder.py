"""Tests for runtime widget reordering in ToolRunnerView.

The runtime view renders ``tool.params`` as a drag-reorderable list
(``ReorderableParamForm``). When the user drops a row into a new
position, the view rewrites ``tool.params`` in the new order and
persists the change back to the .scriptree file if one was supplied.

These tests exercise the reorder path programmatically — simulating
a drag is awkward in a headless Qt test, so we invoke
``_on_form_reordered`` with the target order directly. The UI wiring
from rowsMoved → orderChanged → _on_form_reordered is a one-line
relay and is left to manual verification.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.io import load_tool, save_tool  # noqa: E402
from scriptree.core.model import (  # noqa: E402
    ParamDef,
    ParamType,
    ToolDef,
    Widget,
)
from scriptree.ui.tool_runner import (  # noqa: E402
    ReorderableParamForm,
    ToolRunnerView,
)


def _tool() -> ToolDef:
    return ToolDef(
        name="demo",
        executable="/bin/echo",
        argument_template=["{first}", "{second}", "{third}"],
        params=[
            ParamDef(id="first", label="First"),
            ParamDef(id="second", label="Second"),
            ParamDef(id="third", label="Third"),
        ],
    )


class TestReorderableParamForm:
    def test_add_rows_and_order(self) -> None:
        form = ReorderableParamForm()
        from PySide6.QtWidgets import QLineEdit
        form.add_param_row("a", "Alpha", QLineEdit())
        form.add_param_row("b", "Beta", QLineEdit())
        form.add_param_row("c", "Gamma", QLineEdit())
        assert form.current_order() == ["a", "b", "c"]

    def test_order_changed_signal_emits_ids(self) -> None:
        form = ReorderableParamForm()
        from PySide6.QtWidgets import QLineEdit
        form.add_param_row("a", "Alpha", QLineEdit())
        form.add_param_row("b", "Beta", QLineEdit())
        form.add_param_row("c", "Gamma", QLineEdit())
        captured = []
        form.orderChanged.connect(lambda order: captured.append(list(order)))
        # Simulate what Qt's internal-move drop does: take item from
        # row 2 and re-insert it at row 0. The QListWidget's underlying
        # model fires rowsMoved, which our relay converts to
        # orderChanged emission.
        item = form.takeItem(2)
        form.insertItem(0, item)
        # takeItem/insertItem don't use the model's moveRow so we have
        # to emit manually by calling the relay directly. The real
        # production path uses drag-drop which goes through moveRows.
        form._on_rows_moved()
        assert captured
        assert captured[-1] == ["c", "a", "b"]


class TestRunnerReorderParams:
    def test_reorder_rewrites_tool_params(self) -> None:
        view = ToolRunnerView(_tool())
        assert [p.id for p in view._tool.params] == ["first", "second", "third"]
        view._on_form_reordered("", ["third", "first", "second"])
        assert [p.id for p in view._tool.params] == ["third", "first", "second"]

    def test_reorder_updates_live_command_preview(self) -> None:
        view = ToolRunnerView(_tool())
        view._on_form_reordered("", ["third", "second", "first"])
        # The live preview is built from argument_template; the
        # template still references {first}{second}{third} by id, so
        # the argv order itself doesn't change — but the widget order
        # in the form does. What we verify here is that the preview
        # regenerated without crashing after the reorder.
        assert view._live_cmd.toPlainText() != ""

    def test_reorder_with_unknown_id_is_noop(self) -> None:
        view = ToolRunnerView(_tool())
        before = [p.id for p in view._tool.params]
        view._on_form_reordered("", ["does_not_exist", "first", "second"])
        assert [p.id for p in view._tool.params] == before

    def test_reorder_empty_list_is_noop(self) -> None:
        view = ToolRunnerView(_tool())
        before = [p.id for p in view._tool.params]
        view._on_form_reordered("", [])
        assert [p.id for p in view._tool.params] == before


class TestRunnerReorderPersistence:
    def test_reorder_saves_to_file(self, tmp_path: Path) -> None:
        tool = _tool()
        path = tmp_path / "demo.scriptree"
        save_tool(tool, path)
        view = ToolRunnerView(tool, file_path=str(path))
        view._on_form_reordered("", ["second", "third", "first"])
        # Re-load from disk and confirm the new order was persisted.
        reloaded = load_tool(path)
        assert [p.id for p in reloaded.params] == ["second", "third", "first"]

    def test_reorder_without_file_path_does_not_crash(self) -> None:
        view = ToolRunnerView(_tool())  # no file_path
        view._on_form_reordered("", ["third", "second", "first"])
        assert [p.id for p in view._tool.params] == ["third", "second", "first"]

    def test_reorder_status_message_on_success(self, tmp_path: Path) -> None:
        tool = _tool()
        path = tmp_path / "demo.scriptree"
        save_tool(tool, path)
        view = ToolRunnerView(tool, file_path=str(path))
        view._on_form_reordered("", ["second", "first", "third"])
        assert "saved" in view._status.text().lower()

    def test_reorder_preserves_param_data(self, tmp_path: Path) -> None:
        """Reorder is a permutation — no field on any param should change."""
        tool = ToolDef(
            name="demo",
            executable="/bin/echo",
            argument_template=["{a}", "{b}"],
            params=[
                ParamDef(
                    id="a",
                    label="Alpha",
                    description="first param",
                    type=ParamType.STRING,
                    widget=Widget.TEXT,
                    default="hello",
                    required=True,
                ),
                ParamDef(
                    id="b",
                    label="Beta",
                    type=ParamType.BOOL,
                    widget=Widget.CHECKBOX,
                    default=False,
                ),
            ],
        )
        path = tmp_path / "demo.scriptree"
        save_tool(tool, path)
        view = ToolRunnerView(tool, file_path=str(path))
        view._on_form_reordered("", ["b", "a"])
        reloaded = load_tool(path)
        a = reloaded.param_by_id("a")
        assert a.label == "Alpha"
        assert a.description == "first param"
        assert a.default == "hello"
        assert a.required is True
        b = reloaded.param_by_id("b")
        assert b.type is ParamType.BOOL
        assert b.default is False
