"""UI integration tests for the Env... button on the configurations bar.

Covers:
- The env button is present and disabled without a file path.
- Opening the dialog and accepting writes back to the active config.
- Env overrides propagate through build_full_argv to ResolvedCommand.env
  when the user presses Run (we intercept before subprocess spawn).
- Sidecar persistence of env / path_prepend on the active configuration.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog

_app = QApplication.instance() or QApplication([])

import os  # noqa: E402

from scriptree.core.configs import Configuration, load_configs  # noqa: E402
from scriptree.core.io import save_tool  # noqa: E402
from scriptree.core.model import ParamDef, ToolDef  # noqa: E402
from scriptree.core.runner import build_full_argv  # noqa: E402
from scriptree.ui.tool_runner import ToolRunnerView  # noqa: E402


def _tool(**kw) -> ToolDef:
    return ToolDef(
        name="demo",
        executable="/bin/echo",
        argument_template=["{name}"],
        params=[ParamDef(id="name", label="Name", default="hello")],
        **kw,
    )


def _saved_tool(tmp_path: Path, **kw) -> tuple[ToolDef, str]:
    tool = _tool(**kw)
    path = tmp_path / "demo.scriptree"
    save_tool(tool, path)
    return tool, str(path)


class TestEnvButtonLayout:
    def test_env_button_exists(self) -> None:
        view = ToolRunnerView(_tool())
        assert view._btn_cfg_env.text() == "Env..."

    def test_env_button_disabled_without_file_path(self) -> None:
        view = ToolRunnerView(_tool())
        assert not view._btn_cfg_env.isEnabled()

    def test_env_button_enabled_with_file_path(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        assert view._btn_cfg_env.isEnabled()


class TestEditConfigEnv:
    def test_accept_writes_to_active_config(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)

        captured_dialogs = []

        class _FakeDialog:
            def __init__(self, *args, **kwargs):
                captured_dialogs.append(self)

            def exec(self):
                return QDialog.DialogCode.Accepted

            def result_env(self):
                return {"MY_VAR": "hello"}

            def result_paths(self):
                return ["C:/tools/bin"]

        monkeypatch.setattr(
            "scriptree.ui.tool_runner.EnvEditorDialog", _FakeDialog
        )
        view._cfg_edit_env()

        cfg = view._cfg_set.active_config()
        assert cfg.env == {"MY_VAR": "hello"}
        assert cfg.path_prepend == ["C:/tools/bin"]

        # Persisted to sidecar
        loaded = load_configs(path)
        assert loaded.active_config().env == {"MY_VAR": "hello"}
        assert loaded.active_config().path_prepend == ["C:/tools/bin"]

    def test_cancel_leaves_config_untouched(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)

        class _FakeDialog:
            def __init__(self, *args, **kwargs):
                pass

            def exec(self):
                return QDialog.DialogCode.Rejected

            def result_env(self):
                return {"SHOULD_NOT_APPEAR": "x"}

            def result_paths(self):
                return []

        monkeypatch.setattr(
            "scriptree.ui.tool_runner.EnvEditorDialog", _FakeDialog
        )
        view._cfg_edit_env()
        assert view._cfg_set.active_config().env == {}

    def test_no_file_path_is_noop(self, monkeypatch) -> None:
        view = ToolRunnerView(_tool())

        called = []
        monkeypatch.setattr(
            "scriptree.ui.tool_runner.EnvEditorDialog",
            lambda *a, **k: called.append(1),
        )
        view._cfg_edit_env()
        assert called == []


class TestEnvLayeringThroughRunner:
    def test_run_path_merges_tool_and_config_env(self, tmp_path: Path) -> None:
        cfg_bin = tmp_path / "cfg_bin"
        tool, path = _saved_tool(
            tmp_path,
            env={"TOOL_VAR": "from_tool", "SHARED": "tool_wins_over_base"},
        )
        view = ToolRunnerView(tool, file_path=path)
        # Install a config-level override.
        cfg = view._cfg_set.active_config()
        cfg.env = {"CFG_VAR": "from_config", "SHARED": "cfg_wins"}
        cfg.path_prepend = [str(cfg_bin)]

        # Simulate what _start_run does to build the command.
        cmd = build_full_argv(
            view._tool,
            view._collect_values(),
            view._extras,
            config_env=cfg.env,
            config_path_prepend=cfg.path_prepend,
        )
        assert cmd.env is not None
        assert cmd.env["TOOL_VAR"] == "from_tool"
        assert cmd.env["CFG_VAR"] == "from_config"
        assert cmd.env["SHARED"] == "cfg_wins"  # config overrides tool
        first = cmd.env["PATH"].split(os.pathsep)[0]
        assert Path(first) == cfg_bin

    def test_sidecar_loaded_env_applied_on_reopen(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)

        class _FakeDialog:
            def __init__(self, *a, **k):
                pass

            def exec(self):
                return QDialog.DialogCode.Accepted

            def result_env(self):
                return {"PERSISTED": "yes"}

            def result_paths(self):
                return []

        monkeypatch.setattr(
            "scriptree.ui.tool_runner.EnvEditorDialog", _FakeDialog
        )
        view._cfg_edit_env()

        # Reopen — verify the sidecar is reloaded and the env is applied.
        view2 = ToolRunnerView(tool, file_path=path)
        assert view2._cfg_set.active_config().env == {"PERSISTED": "yes"}
