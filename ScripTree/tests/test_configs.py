"""Tests for the ConfigurationSet sidecar file (core/configs.py).

Covers the pure-Python half of the configurations feature: dataclass
defaults, JSON round-trip, sidecar file naming, and the load/save
helpers. UI integration is tested separately in test_tool_runner_configs.
"""
from __future__ import annotations

import json
from pathlib import Path

from scriptree.core.configs import (
    CONFIGS_SCHEMA_VERSION,
    SIDECAR_SUFFIX,
    Configuration,
    ConfigurationSet,
    UIVisibility,
    configs_from_dict,
    configs_to_dict,
    default_configuration_set,
    load_configs,
    save_configs,
    sidecar_path,
)


class TestSidecarPath:
    def test_appends_suffix(self) -> None:
        p = sidecar_path("foo.scriptree")
        assert p.name == "foo.scriptree" + SIDECAR_SUFFIX

    def test_preserves_directory(self, tmp_path: Path) -> None:
        tool = tmp_path / "sub" / "foo.scriptree"
        p = sidecar_path(tool)
        assert p.parent == tool.parent
        assert p.name.endswith(SIDECAR_SUFFIX)


class TestDefaultSet:
    def test_has_one_default_configuration(self) -> None:
        s = default_configuration_set({"x": 1})
        assert len(s.configurations) == 1
        assert s.configurations[0].name == "default"
        assert s.configurations[0].values == {"x": 1}
        assert s.active == "default"

    def test_empty_values_is_ok(self) -> None:
        s = default_configuration_set()
        assert s.configurations[0].values == {}


class TestFindAndActive:
    def test_find_returns_match(self) -> None:
        s = ConfigurationSet(
            active="b",
            configurations=[
                Configuration(name="a"),
                Configuration(name="b"),
            ],
        )
        assert s.find("b").name == "b"
        assert s.find("missing") is None

    def test_active_config_repairs_dangling_pointer(self) -> None:
        s = ConfigurationSet(
            active="gone",
            configurations=[Configuration(name="a")],
        )
        assert s.active_config().name == "a"
        assert s.active == "a"  # repaired in place


class TestJSONRoundTrip:
    def test_round_trip_preserves_everything(self) -> None:
        s = ConfigurationSet(
            active="verbose",
            configurations=[
                Configuration(name="default", values={"x": 1}, extras=[]),
                Configuration(
                    name="verbose", values={"x": 2}, extras=["-v", "--debug"]
                ),
            ],
        )
        d = configs_to_dict(s)
        s2 = configs_from_dict(d)
        assert s2.active == "verbose"
        assert len(s2.configurations) == 2
        assert s2.configurations[1].extras == ["-v", "--debug"]

    def test_future_schema_version_rejected(self) -> None:
        import pytest
        with pytest.raises(ValueError):
            configs_from_dict({"schema_version": 999, "configurations": []})

    def test_empty_configurations_falls_back_to_default(self) -> None:
        s = configs_from_dict({"schema_version": 1, "configurations": []})
        assert len(s.configurations) == 1
        assert s.configurations[0].name == "default"

    def test_dangling_active_pointer_is_repaired_on_load(self) -> None:
        s = configs_from_dict({
            "schema_version": 1,
            "active": "missing",
            "configurations": [{"name": "a", "values": {}, "extras": []}],
        })
        assert s.active == "a"


class TestLoadSave:
    def test_load_returns_none_for_missing_sidecar(self, tmp_path: Path) -> None:
        assert load_configs(tmp_path / "nope.scriptree") is None

    def test_save_then_load(self, tmp_path: Path) -> None:
        tool = tmp_path / "t.scriptree"
        s = default_configuration_set({"n": "hi"})
        save_configs(tool, s)
        assert sidecar_path(tool).exists()
        loaded = load_configs(tool)
        assert loaded is not None
        assert loaded.configurations[0].values == {"n": "hi"}

    def test_save_writes_json_with_schema_version(self, tmp_path: Path) -> None:
        tool = tmp_path / "t.scriptree"
        save_configs(tool, default_configuration_set())
        data = json.loads(sidecar_path(tool).read_text(encoding="utf-8"))
        assert data["schema_version"] == CONFIGS_SCHEMA_VERSION


# --- UIVisibility -----------------------------------------------------------


class TestUIVisibility:
    def test_defaults_are_all_visible(self) -> None:
        vis = UIVisibility()
        assert vis.output_pane is True
        assert vis.extras_box is True
        assert vis.tools_sidebar is True
        assert vis.command_line is True
        assert vis.copy_argv is True
        assert vis.clear_output is True
        assert vis.config_bar is True
        assert vis.env_button is True
        assert vis.popup_on_error is False
        assert vis.popup_on_success is False

    def test_is_default_true_for_factory(self) -> None:
        assert UIVisibility().is_default() is True

    def test_is_default_false_when_changed(self) -> None:
        vis = UIVisibility(command_line=False)
        assert vis.is_default() is False

    def test_round_trip_non_default(self) -> None:
        cfg = Configuration(
            name="standalone",
            ui_visibility=UIVisibility(
                output_pane=False,
                command_line=False,
                config_bar=False,
                popup_on_error=True,
            ),
        )
        s = ConfigurationSet(active="standalone", configurations=[cfg])
        d = configs_to_dict(s)
        # Only non-default flags should appear.
        vis_dict = d["configurations"][0]["ui_visibility"]
        assert vis_dict["output_pane"] is False
        assert vis_dict["command_line"] is False
        assert vis_dict["config_bar"] is False
        assert vis_dict["popup_on_error"] is True
        assert "extras_box" not in vis_dict  # default, omitted

        s2 = configs_from_dict(d)
        vis2 = s2.configurations[0].ui_visibility
        assert vis2.output_pane is False
        assert vis2.command_line is False
        assert vis2.config_bar is False
        assert vis2.popup_on_error is True
        assert vis2.extras_box is True  # default preserved

    def test_default_visibility_not_emitted(self) -> None:
        cfg = Configuration(name="plain")
        d = configs_to_dict(ConfigurationSet(configurations=[cfg]))
        assert "ui_visibility" not in d["configurations"][0]

    def test_legacy_sidecar_loads_with_defaults(self) -> None:
        """A v1-era sidecar with no ui_visibility key should load cleanly."""
        raw = {
            "schema_version": 1,
            "active": "default",
            "configurations": [
                {"name": "default", "values": {"x": 1}, "extras": []}
            ],
        }
        s = configs_from_dict(raw)
        assert s.configurations[0].ui_visibility.is_default()
        assert s.configurations[0].hidden_params == []


# --- hidden_params ----------------------------------------------------------


class TestHiddenParams:
    def test_round_trip(self) -> None:
        cfg = Configuration(
            name="locked",
            values={"file": "/data/input.csv"},
            hidden_params=["file"],
        )
        s = ConfigurationSet(configurations=[cfg])
        d = configs_to_dict(s)
        assert d["configurations"][0]["hidden_params"] == ["file"]

        s2 = configs_from_dict(d)
        assert s2.configurations[0].hidden_params == ["file"]

    def test_empty_hidden_params_not_emitted(self) -> None:
        cfg = Configuration(name="normal")
        d = configs_to_dict(ConfigurationSet(configurations=[cfg]))
        assert "hidden_params" not in d["configurations"][0]

    def test_save_load_with_visibility_and_hidden(self, tmp_path: Path) -> None:
        tool = tmp_path / "t.scriptree"
        cfg = Configuration(
            name="standalone",
            values={"in": "a.txt", "out": "b.txt"},
            hidden_params=["in"],
            ui_visibility=UIVisibility(command_line=False, extras_box=False),
        )
        s = ConfigurationSet(active="standalone", configurations=[cfg])
        save_configs(tool, s)
        loaded = load_configs(tool)
        assert loaded is not None
        c = loaded.configurations[0]
        assert c.hidden_params == ["in"]
        assert c.ui_visibility.command_line is False
        assert c.ui_visibility.extras_box is False
        assert c.ui_visibility.output_pane is True  # default
