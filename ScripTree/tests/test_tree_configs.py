"""Tests for tree-level configurations and the safetree reserved config.

Covers:
- TreeConfiguration / TreeConfigurationSet data model
- Tree config sidecar round-trip (load/save)
- safetree reserved name enforcement
- safetree config creation via ensure_safetree_config
- StandaloneWindow safetree fallback when a config is missing
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.configs import (  # noqa: E402
    SAFETREE_CONFIG_NAME,
    Configuration,
    ConfigurationSet,
    TreeConfiguration,
    TreeConfigurationSet,
    default_tree_configuration_set,
    ensure_safetree_config,
    is_reserved_config_name,
    load_configs,
    load_tree_configs,
    safetree_configuration,
    safetree_visibility,
    save_configs,
    save_tree_configs,
    tree_configs_from_dict,
    tree_configs_to_dict,
    tree_sidecar_path,
)
from scriptree.core.io import save_tool, save_tree  # noqa: E402
from scriptree.core.model import (  # noqa: E402
    ParamDef,
    ToolDef,
    TreeDef,
    TreeNode,
)


# --- safetree visibility ---


class TestSafetreeVisibility:
    def test_everything_hidden(self) -> None:
        vis = safetree_visibility()
        assert vis.output_pane is False
        assert vis.extras_box is False
        assert vis.command_line is False
        assert vis.copy_argv is False
        assert vis.clear_output is False
        assert vis.config_bar == "hidden"
        assert vis.env_button is False
        assert vis.tools_sidebar is False

    def test_popups_enabled(self) -> None:
        vis = safetree_visibility()
        assert vis.popup_on_error is True
        assert vis.popup_on_success is True


# --- safetree config ---


class TestSafetreeConfiguration:
    def test_name_is_safetree(self) -> None:
        cfg = safetree_configuration()
        assert cfg.name == SAFETREE_CONFIG_NAME

    def test_values_seeded(self) -> None:
        cfg = safetree_configuration({"x": "1"})
        assert cfg.values == {"x": "1"}

    def test_visibility_is_safetree(self) -> None:
        cfg = safetree_configuration()
        assert cfg.ui_visibility == safetree_visibility()


# --- reserved name ---


class TestReservedName:
    def test_safetree_is_reserved(self) -> None:
        assert is_reserved_config_name("safetree") is True

    def test_case_insensitive(self) -> None:
        assert is_reserved_config_name("SafeTree") is True
        assert is_reserved_config_name("SAFETREE") is True

    def test_default_not_reserved(self) -> None:
        assert is_reserved_config_name("default") is False

    def test_empty_not_reserved(self) -> None:
        assert is_reserved_config_name("") is False


# --- ensure_safetree_config ---


class TestEnsureSafetreeConfig:
    def test_creates_sidecar_when_missing(self, tmp_path: Path) -> None:
        tool_path = tmp_path / "t.scriptree"
        save_tool(ToolDef(name="t", executable="/bin/echo"), tool_path)
        ensure_safetree_config(str(tool_path))
        loaded = load_configs(str(tool_path))
        assert loaded is not None
        st = loaded.find(SAFETREE_CONFIG_NAME)
        assert st is not None
        assert st.ui_visibility == safetree_visibility()

    def test_adds_to_existing_sidecar(self, tmp_path: Path) -> None:
        tool_path = tmp_path / "t.scriptree"
        save_tool(ToolDef(name="t", executable="/bin/echo"), tool_path)
        # Create a sidecar with just "default".
        cs = ConfigurationSet(
            active="default",
            configurations=[Configuration(name="default", values={"x": "1"})],
        )
        save_configs(str(tool_path), cs)
        ensure_safetree_config(str(tool_path))
        loaded = load_configs(str(tool_path))
        assert loaded is not None
        # Both default and safetree should exist.
        assert loaded.find("default") is not None
        assert loaded.find(SAFETREE_CONFIG_NAME) is not None

    def test_overwrites_existing_safetree(self, tmp_path: Path) -> None:
        tool_path = tmp_path / "t.scriptree"
        save_tool(ToolDef(name="t", executable="/bin/echo"), tool_path)
        # Create a sidecar with a manually-tweaked safetree.
        from scriptree.core.configs import UIVisibility

        cs = ConfigurationSet(
            active="default",
            configurations=[
                Configuration(name="default"),
                Configuration(
                    name=SAFETREE_CONFIG_NAME,
                    ui_visibility=UIVisibility(output_pane=True),  # wrong
                ),
            ],
        )
        save_configs(str(tool_path), cs)
        ensure_safetree_config(str(tool_path))
        loaded = load_configs(str(tool_path))
        st = loaded.find(SAFETREE_CONFIG_NAME)
        # Should be overwritten with the canonical version.
        assert st.ui_visibility.output_pane is False


# --- TreeConfiguration data model ---


class TestTreeConfigurationModel:
    def test_default_set(self) -> None:
        s = default_tree_configuration_set()
        assert len(s.configurations) == 1
        assert s.configurations[0].name == "default"
        assert s.active == "default"

    def test_find(self) -> None:
        s = TreeConfigurationSet(
            active="b",
            configurations=[
                TreeConfiguration(name="a"),
                TreeConfiguration(name="b", tool_configs={"./t.scriptree": "min"}),
            ],
        )
        assert s.find("b") is not None
        assert s.find("b").tool_configs == {"./t.scriptree": "min"}
        assert s.find("missing") is None

    def test_active_config_repairs_dangling(self) -> None:
        s = TreeConfigurationSet(
            active="gone",
            configurations=[TreeConfiguration(name="a")],
        )
        assert s.active_config().name == "a"
        assert s.active == "a"


# --- Tree config sidecar round-trip ---


class TestTreeConfigSidecar:
    def test_sidecar_path(self) -> None:
        p = tree_sidecar_path("foo.scriptreetree")
        assert p.name == "foo.scriptreetree.treeconfigs.json"

    def test_dict_round_trip(self) -> None:
        s = TreeConfigurationSet(
            active="standalone",
            configurations=[
                TreeConfiguration(name="default"),
                TreeConfiguration(
                    name="standalone",
                    tool_configs={
                        "./tool_a.scriptree": "minimal",
                        "./sub/tool_b.scriptree": "headless",
                    },
                ),
            ],
        )
        d = tree_configs_to_dict(s)
        s2 = tree_configs_from_dict(d)
        assert s2.active == "standalone"
        assert len(s2.configurations) == 2
        assert s2.find("standalone").tool_configs == {
            "./tool_a.scriptree": "minimal",
            "./sub/tool_b.scriptree": "headless",
        }

    def test_file_round_trip(self, tmp_path: Path) -> None:
        tree = tmp_path / "suite.scriptreetree"
        tree.write_text("{}")  # dummy
        s = TreeConfigurationSet(
            active="prod",
            configurations=[
                TreeConfiguration(
                    name="prod",
                    tool_configs={"./a.scriptree": "fast"},
                ),
            ],
        )
        save_tree_configs(str(tree), s)
        loaded = load_tree_configs(str(tree))
        assert loaded is not None
        assert loaded.active == "prod"
        assert loaded.find("prod").tool_configs == {"./a.scriptree": "fast"}

    def test_load_returns_none_when_missing(self, tmp_path: Path) -> None:
        assert load_tree_configs(str(tmp_path / "nope.scriptreetree")) is None

    def test_empty_configurations_fall_back(self) -> None:
        s = tree_configs_from_dict({"schema_version": 1, "configurations": []})
        assert len(s.configurations) == 1
        assert s.configurations[0].name == "default"


# --- safetree fallback in StandaloneWindow ---


class TestStandaloneTreeSafetreeFallback:
    def test_missing_config_creates_safetree(self, tmp_path: Path) -> None:
        from scriptree.ui.standalone_window import StandaloneWindow

        # Create a tool with only "default" config.
        tool = ToolDef(name="t", executable="/bin/echo")
        tool_path = tmp_path / "t.scriptree"
        save_tool(tool, tool_path)

        # Create a tree referencing a config that doesn't exist.
        tree = TreeDef(
            name="suite",
            nodes=[
                TreeNode(
                    type="leaf",
                    path="./t.scriptree",
                    configuration="nonexistent",
                ),
            ],
        )
        tree_path = tmp_path / "suite.scriptreetree"
        save_tree(tree, tree_path)

        win = StandaloneWindow.from_tree(str(tree_path))
        assert len(win._runners) == 1

        # safetree should now exist in the tool's sidecar.
        loaded = load_configs(str(tool_path))
        assert loaded is not None
        st = loaded.find(SAFETREE_CONFIG_NAME)
        assert st is not None
        assert st.ui_visibility.output_pane is False

    def test_tree_config_sidecar_used(self, tmp_path: Path) -> None:
        from scriptree.ui.standalone_window import StandaloneWindow

        # Create a tool with "default" and "minimal" configs.
        tool = ToolDef(
            name="t",
            executable="/bin/echo",
            params=[ParamDef(id="x", label="X", default="1")],
        )
        tool_path = tmp_path / "t.scriptree"
        save_tool(tool, tool_path)
        from scriptree.core.configs import UIVisibility

        cs = ConfigurationSet(
            active="default",
            configurations=[
                Configuration(name="default", values={"x": "1"}),
                Configuration(
                    name="minimal",
                    values={"x": "2"},
                    ui_visibility=UIVisibility(command_line=False),
                ),
            ],
        )
        save_configs(str(tool_path), cs)

        # Create a tree with NO node.configuration set.
        tree = TreeDef(
            name="suite",
            nodes=[TreeNode(type="leaf", path="./t.scriptree")],
        )
        tree_path = tmp_path / "suite.scriptreetree"
        save_tree(tree, tree_path)

        # But set it via the tree config sidecar.
        tree_cfg = TreeConfigurationSet(
            active="standalone",
            configurations=[
                TreeConfiguration(
                    name="standalone",
                    tool_configs={"./t.scriptree": "minimal"},
                ),
            ],
        )
        save_tree_configs(str(tree_path), tree_cfg)

        win = StandaloneWindow.from_tree(str(tree_path))
        assert len(win._runners) == 1
        runner = win._runners[0]
        # Should have applied "minimal" config.
        assert runner.active_visibility.command_line is False


# --- safetree name blocked in tool_runner UI ---


class TestSafetreeBlockedInUI:
    def test_save_as_blocks_safetree(self, tmp_path: Path, monkeypatch) -> None:
        from scriptree.ui.tool_runner import ToolRunnerView

        tool = ToolDef(name="t", executable="/bin/echo")
        tool_path = tmp_path / "t.scriptree"
        save_tool(tool, tool_path)

        view = ToolRunnerView(tool, file_path=str(tool_path))

        # Monkeypatch QInputDialog to return "safetree".
        from PySide6.QtWidgets import QInputDialog

        monkeypatch.setattr(
            QInputDialog,
            "getText",
            staticmethod(lambda *a, **k: ("safetree", True)),
        )
        # Monkeypatch QMessageBox.warning to capture the call.
        from PySide6.QtWidgets import QMessageBox

        warnings = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(lambda *a, **k: warnings.append(a)),
        )
        view._cfg_save_as()
        assert len(warnings) == 1
        assert "reserved" in warnings[0][2].lower()

    def test_rename_blocks_safetree(self, monkeypatch) -> None:
        from scriptree.ui.tool_runner import ConfigurationEditDialog

        from scriptree.core.configs import ConfigurationSet, Configuration
        from PySide6.QtWidgets import QMessageBox

        cs = ConfigurationSet(
            configurations=[Configuration(name="default")],
        )
        dlg = ConfigurationEditDialog(cs)
        # Rename the single item to "safetree".
        dlg._list.item(0).setText("safetree")

        warnings = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(lambda *a, **k: warnings.append(a)),
        )
        dlg._on_accept()
        assert len(warnings) == 1
        assert "reserved" in warnings[0][2].lower()
