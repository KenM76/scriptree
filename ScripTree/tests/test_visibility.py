"""Tests for UI visibility, hidden params, and standalone mode.

Covers Phase 2 (runner visibility application), Phase 3 (visibility
editor dialog), Phase 4 (standalone window), and Phase 5 (CLI args).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

_app = QApplication.instance() or QApplication([])

from scriptree.core.configs import (  # noqa: E402
    Configuration,
    ConfigurationSet,
    UIVisibility,
    save_configs,
)
from scriptree.core.io import save_tool, save_tree  # noqa: E402
from scriptree.core.model import (  # noqa: E402
    ParamDef,
    ParamType,
    ToolDef,
    TreeDef,
    TreeNode,
)
from scriptree.ui.tool_runner import ToolRunnerView  # noqa: E402
from scriptree.ui.visibility_editor import VisibilityEditorDialog  # noqa: E402


def _tool() -> ToolDef:
    return ToolDef(
        name="demo",
        executable="/bin/echo",
        argument_template=["{name}", "{count}"],
        params=[
            ParamDef(id="name", label="Name", default="hello"),
            ParamDef(id="count", label="Count", default="5"),
        ],
    )


def _saved_tool(tmp_path: Path) -> tuple[ToolDef, str]:
    tool = _tool()
    path = tmp_path / "demo.scriptree"
    save_tool(tool, path)
    return tool, str(path)


# --- Phase 2: _apply_visibility tests ---


class TestApplyVisibility:
    """Verify that _apply_visibility toggles widget visibility in standalone mode."""

    def test_extras_box_hidden(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        view._standalone_mode = True
        vis = UIVisibility(extras_box=False)
        view._apply_visibility(vis)
        assert view._extras_box.isHidden()

    def test_cmd_box_hidden(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        view._standalone_mode = True
        vis = UIVisibility(command_line=False)
        view._apply_visibility(vis)
        assert view._cmd_box.isHidden()

    def test_copy_argv_hidden(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        view._standalone_mode = True
        vis = UIVisibility(copy_argv=False)
        view._apply_visibility(vis)
        assert view._btn_preview.isHidden()

    def test_clear_output_hidden(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        view._standalone_mode = True
        vis = UIVisibility(clear_output=False)
        view._apply_visibility(vis)
        assert view._btn_clear_output.isHidden()

    def test_config_bar_hidden(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        view._standalone_mode = True
        vis = UIVisibility(config_bar=False)
        view._apply_visibility(vis)
        assert view._cfg_widget.isHidden()

    def test_env_button_hidden(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        view._standalone_mode = True
        vis = UIVisibility(env_button=False)
        view._apply_visibility(vis)
        assert view._btn_cfg_env.isHidden()

    def test_clear_output_hidden_when_output_pane_hidden(self, tmp_path: Path) -> None:
        """Clear output button should also hide when output pane is hidden."""
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        view._standalone_mode = True
        vis = UIVisibility(output_pane=False, clear_output=True)
        view._apply_visibility(vis)
        assert view._btn_clear_output.isHidden()

    def test_clear_output_visible_when_both_true(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        view._standalone_mode = True
        vis = UIVisibility(output_pane=True, clear_output=True)
        view._apply_visibility(vis)
        assert not view._btn_clear_output.isHidden()

    def test_all_not_hidden_by_default_standalone(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        view._standalone_mode = True
        vis = UIVisibility()  # all defaults = visible
        view._apply_visibility(vis)
        assert not view._extras_box.isHidden()
        assert not view._cmd_box.isHidden()
        assert not view._btn_preview.isHidden()
        assert not view._btn_clear_output.isHidden()
        assert not view._cfg_widget.isHidden()

    def test_docked_mode_never_hides(self, tmp_path: Path) -> None:
        """In docked (non-standalone) mode, visibility flags are ignored."""
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        # _standalone_mode defaults to False.
        vis = UIVisibility(
            extras_box=False, command_line=False,
            copy_argv=False, clear_output=False, config_bar=False,
        )
        view._apply_visibility(vis)
        # Nothing should be hidden in docked mode.
        assert not view._extras_box.isHidden()
        assert not view._cmd_box.isHidden()
        assert not view._btn_preview.isHidden()
        assert not view._btn_clear_output.isHidden()
        assert not view._cfg_widget.isHidden()

    def test_signal_emitted_in_both_modes(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        received = []
        view.visibilityChanged.connect(received.append)
        vis = UIVisibility(extras_box=False)
        # Signal fires in docked mode too (MainWindow may use it).
        view._apply_visibility(vis)
        assert len(received) == 1
        assert received[0].extras_box is False


# --- Phase 2: hidden params tests ---


class TestHiddenParams:
    """Verify hidden params are excluded from form but in _collect_values.

    Hidden params only take effect in standalone mode. In docked mode
    all params remain visible regardless of hidden_params settings.
    """

    def test_hidden_param_not_in_widgets_standalone(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        cfg = Configuration(
            name="locked",
            values={"name": "fixed", "count": "10"},
            hidden_params=["name"],
        )
        cs = ConfigurationSet(active="locked", configurations=[cfg])
        save_configs(path, cs)

        view = ToolRunnerView(tool, file_path=path)
        view._standalone_mode = True
        view.apply_named_configuration("locked")
        # "name" should NOT be in the form widgets in standalone.
        assert "name" not in view._widgets
        assert "count" in view._widgets

    def test_hidden_param_visible_in_docked_mode(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        cfg = Configuration(
            name="locked",
            values={"name": "fixed", "count": "10"},
            hidden_params=["name"],
        )
        cs = ConfigurationSet(active="locked", configurations=[cfg])
        save_configs(path, cs)

        view = ToolRunnerView(tool, file_path=path)
        # Docked mode (default) — hidden_params should be ignored.
        assert "name" in view._widgets
        assert "count" in view._widgets

    def test_hidden_param_in_collect_values(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        cfg = Configuration(
            name="locked",
            values={"name": "fixed_value", "count": "10"},
            hidden_params=["name"],
        )
        cs = ConfigurationSet(active="locked", configurations=[cfg])
        save_configs(path, cs)

        view = ToolRunnerView(tool, file_path=path)
        view._standalone_mode = True
        view.apply_named_configuration("locked")
        values = view._collect_values()
        # Hidden param value should come from the config.
        assert values["name"] == "fixed_value"
        assert "count" in values

    def test_switching_config_rebuilds_form_standalone(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        cfg_default = Configuration(
            name="default",
            values={"name": "hello", "count": "5"},
            hidden_params=[],
        )
        cfg_locked = Configuration(
            name="locked",
            values={"name": "fixed", "count": "10"},
            hidden_params=["name"],
        )
        cs = ConfigurationSet(
            active="default",
            configurations=[cfg_default, cfg_locked],
        )
        save_configs(path, cs)

        view = ToolRunnerView(tool, file_path=path)
        view._standalone_mode = True
        view.apply_named_configuration("default")
        # Default config — both params visible.
        assert "name" in view._widgets
        assert "count" in view._widgets

        # Switch to locked config in standalone.
        view.apply_named_configuration("locked")
        assert "name" not in view._widgets
        assert "count" in view._widgets


# --- Phase 2: apply_named_configuration ---


class TestApplyNamedConfiguration:
    def test_returns_true_for_existing(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        assert view.apply_named_configuration("default") is True

    def test_returns_false_for_missing(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        assert view.apply_named_configuration("nonexistent") is False

    def test_active_visibility_property(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        cfg = Configuration(
            name="standalone",
            values={"name": "x", "count": "1"},
            ui_visibility=UIVisibility(command_line=False),
        )
        cs = ConfigurationSet(
            active="default",
            configurations=[
                Configuration(name="default", values={"name": "hello", "count": "5"}),
                cfg,
            ],
        )
        save_configs(path, cs)

        view = ToolRunnerView(tool, file_path=path)
        # Default visibility.
        assert view.active_visibility.command_line is True
        # Switch to standalone.
        view.apply_named_configuration("standalone")
        assert view.active_visibility.command_line is False


# --- Phase 3: VisibilityEditorDialog tests ---


class TestVisibilityEditorDialog:
    def test_result_visibility_reflects_checks(self) -> None:
        vis = UIVisibility(command_line=False, extras_box=False)
        dlg = VisibilityEditorDialog(
            vis,
            hidden_params=[],
            all_params=[ParamDef(id="x", label="X")],
            current_values={"x": "1"},
        )
        result = dlg.result_visibility()
        assert result.command_line is False
        assert result.extras_box is False
        assert result.output_pane is True  # default

    def test_result_hidden_params(self) -> None:
        params = [ParamDef(id="a", label="A"), ParamDef(id="b", label="B")]
        dlg = VisibilityEditorDialog(
            UIVisibility(),
            hidden_params=["a"],
            all_params=params,
            current_values={"a": "1", "b": "2"},
        )
        # "a" should be checked.
        assert dlg._hidden_checks["a"].isChecked()
        assert not dlg._hidden_checks["b"].isChecked()
        assert dlg.result_hidden_params() == ["a"]

    def test_result_locked_values(self) -> None:
        params = [ParamDef(id="x", label="X")]
        dlg = VisibilityEditorDialog(
            UIVisibility(),
            hidden_params=["x"],
            all_params=params,
            current_values={"x": "locked_val"},
        )
        locked = dlg.result_locked_values()
        assert locked["x"] == "locked_val"

    def test_unchecked_param_not_in_locked(self) -> None:
        params = [ParamDef(id="x", label="X"), ParamDef(id="y", label="Y")]
        dlg = VisibilityEditorDialog(
            UIVisibility(),
            hidden_params=[],  # none hidden
            all_params=params,
            current_values={"x": "1", "y": "2"},
        )
        assert dlg.result_locked_values() == {}
        assert dlg.result_hidden_params() == []


# --- Phase 4: StandaloneWindow tests ---


class TestStandaloneWindow:
    def test_from_tool_creates_window(self, tmp_path: Path) -> None:
        from scriptree.ui.standalone_window import StandaloneWindow

        tool, path = _saved_tool(tmp_path)
        win = StandaloneWindow.from_tool(tool, path)
        assert win.windowTitle().startswith("ScripTree")
        assert hasattr(win, "_runners")
        assert len(win._runners) == 1

    def test_from_tool_with_config(self, tmp_path: Path) -> None:
        from scriptree.ui.standalone_window import StandaloneWindow

        tool, path = _saved_tool(tmp_path)
        cfg = Configuration(
            name="standalone",
            values={"name": "x", "count": "1"},
            ui_visibility=UIVisibility(command_line=False),
        )
        cs = ConfigurationSet(
            active="default",
            configurations=[
                Configuration(name="default", values={"name": "hi", "count": "5"}),
                cfg,
            ],
        )
        save_configs(path, cs)

        win = StandaloneWindow.from_tool(tool, path, config_name="standalone")
        runner = win._runners[0]
        assert runner.active_visibility.command_line is False

    def test_from_tree_creates_tabs(self, tmp_path: Path) -> None:
        from scriptree.ui.standalone_window import StandaloneWindow

        # Create two tools.
        t1 = ToolDef(name="tool1", executable="/bin/echo")
        t2 = ToolDef(name="tool2", executable="/bin/echo")
        p1 = tmp_path / "tool1.scriptree"
        p2 = tmp_path / "tool2.scriptree"
        save_tool(t1, p1)
        save_tool(t2, p2)

        # Create a tree referencing them.
        tree = TreeDef(
            name="suite",
            nodes=[
                TreeNode(type="leaf", path="./tool1.scriptree"),
                TreeNode(type="leaf", path="./tool2.scriptree"),
            ],
        )
        tree_path = tmp_path / "suite.scriptreetree"
        save_tree(tree, tree_path)

        win = StandaloneWindow.from_tree(str(tree_path))
        assert len(win._runners) == 2
        # Should have a tab widget with 2 tabs.
        assert win._tabs.count() == 2

    def test_from_tree_with_node_configuration(self, tmp_path: Path) -> None:
        from scriptree.ui.standalone_window import StandaloneWindow

        tool = _tool()
        p = tmp_path / "demo.scriptree"
        save_tool(tool, p)

        # Create sidecar with a "minimal" config.
        cfg = Configuration(
            name="minimal",
            values={"name": "x", "count": "1"},
            ui_visibility=UIVisibility(command_line=False, extras_box=False),
        )
        cs = ConfigurationSet(
            active="default",
            configurations=[
                Configuration(name="default", values={"name": "hi", "count": "5"}),
                cfg,
            ],
        )
        save_configs(str(p), cs)

        tree = TreeDef(
            name="suite",
            nodes=[
                TreeNode(
                    type="leaf",
                    path="./demo.scriptree",
                    configuration="minimal",
                ),
            ],
        )
        tree_path = tmp_path / "suite.scriptreetree"
        save_tree(tree, tree_path)

        win = StandaloneWindow.from_tree(str(tree_path))
        assert len(win._runners) == 1
        runner = win._runners[0]
        assert runner.active_visibility.command_line is False
        assert runner.active_visibility.extras_box is False


# --- Phase 5: CLI argument parsing ---


class TestCLIParsing:
    def test_no_args(self) -> None:
        from scriptree.main import _parse_args

        args = _parse_args([])
        assert args.file is None
        assert args.configuration is None

    def test_file_only(self) -> None:
        from scriptree.main import _parse_args

        args = _parse_args(["tool.scriptree"])
        assert args.file == "tool.scriptree"
        assert args.configuration is None

    def test_file_with_configuration(self) -> None:
        from scriptree.main import _parse_args

        args = _parse_args(["tool.scriptree", "-configuration", "standalone"])
        assert args.file == "tool.scriptree"
        assert args.configuration == "standalone"

    def test_tree_with_configuration(self) -> None:
        from scriptree.main import _parse_args

        args = _parse_args(["tree.scriptreetree", "-configuration", "standalone"])
        assert args.file == "tree.scriptreetree"
        assert args.configuration == "standalone"


# --- Phase 2: popup on error/success in _on_finished ---


class TestPopupDialogs:
    """Test that _on_finished shows popup dialogs when configured."""

    def test_popup_on_error_shows_messagebox(self, tmp_path: Path, monkeypatch) -> None:
        tool, path = _saved_tool(tmp_path)
        cfg = Configuration(
            name="standalone",
            values={"name": "x", "count": "1"},
            ui_visibility=UIVisibility(popup_on_error=True),
        )
        cs = ConfigurationSet(active="standalone", configurations=[cfg])
        save_configs(path, cs)

        view = ToolRunnerView(tool, file_path=path)
        # Add some stderr content.
        view._stderr_buffer = ["error: something failed\n"]

        # Monkeypatch QMessageBox.critical to capture the call.
        calls = []
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            staticmethod(lambda *a, **k: calls.append(a)),
        )
        # Simulate _on_finished with non-zero exit code.
        # We need to set _thread to None first since _on_finished tries to tear it down.
        view._thread = None
        view._worker = None
        view._on_finished(1, 0.5)
        assert len(calls) == 1

    def test_popup_on_success_shows_messagebox(self, tmp_path: Path, monkeypatch) -> None:
        tool, path = _saved_tool(tmp_path)
        cfg = Configuration(
            name="standalone",
            values={"name": "x", "count": "1"},
            ui_visibility=UIVisibility(popup_on_success=True),
        )
        cs = ConfigurationSet(active="standalone", configurations=[cfg])
        save_configs(path, cs)

        view = ToolRunnerView(tool, file_path=path)

        calls = []
        monkeypatch.setattr(
            QMessageBox,
            "information",
            staticmethod(lambda *a, **k: calls.append(a)),
        )
        view._thread = None
        view._worker = None
        view._on_finished(0, 1.0)
        assert len(calls) == 1

    def test_no_popup_when_flags_off(self, tmp_path: Path, monkeypatch) -> None:
        tool, path = _saved_tool(tmp_path)
        # Default visibility — both popup flags False.
        view = ToolRunnerView(tool, file_path=path)

        critical_calls = []
        info_calls = []
        monkeypatch.setattr(
            QMessageBox, "critical",
            staticmethod(lambda *a, **k: critical_calls.append(a)),
        )
        monkeypatch.setattr(
            QMessageBox, "information",
            staticmethod(lambda *a, **k: info_calls.append(a)),
        )
        view._thread = None
        view._worker = None
        view._on_finished(1, 0.5)
        view._on_finished(0, 0.5)
        assert len(critical_calls) == 0
        assert len(info_calls) == 0
