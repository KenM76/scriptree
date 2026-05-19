"""Tests for the per-set ``default_name`` configuration pointer +
the editor's "Default" checkbox.

The semantics: every ConfigurationSet may optionally name one of its
configurations as the *default*.  Standalone-mode launches that don't
pass a ``-configuration`` flag use the default if set, falling back
to ``active`` (the last-used) otherwise.

Tests cover:
  * Round-trip of ``default_name`` through ``configs_to_dict`` /
    ``configs_from_dict``.
  * ``default_config()`` resolution order (default → active → first).
  * Legacy sidecars without ``default_name`` load fine.
  * Renamed / deleted configs invalidate the pointer (load-time sweep).
  * The editor's checkbox toggles ``default_name`` correctly.
  * ``StandaloneWindow.from_tool`` honours ``default_name``.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

# Auto-dismiss any stray QMessageBox that fires during these tests.
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.critical = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.question = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Yes
)

from scriptree.core.configs import (  # noqa: E402
    Configuration,
    ConfigurationSet,
    configs_from_dict,
    configs_to_dict,
    load_configs,
    save_configs,
)
from scriptree.core.io import save_tool  # noqa: E402
from scriptree.core.model import ParamDef, ToolDef  # noqa: E402


# ---------------------------------------------------------------------------
# default_config() resolution order
# ---------------------------------------------------------------------------

def _make_set(default_name: str = "", active: str = "default") -> ConfigurationSet:
    return ConfigurationSet(
        active=active,
        default_name=default_name,
        configurations=[
            Configuration(name="default", values={"x": "1"}),
            Configuration(name="dev", values={"x": "2"}),
            Configuration(name="prod", values={"x": "3"}),
        ],
    )


def test_default_config_returns_named_default() -> None:
    s = _make_set(default_name="prod", active="dev")
    assert s.default_config().name == "prod"


def test_default_config_falls_back_to_active() -> None:
    s = _make_set(default_name="", active="dev")
    assert s.default_config().name == "dev"


def test_default_config_invalid_default_falls_back_to_active() -> None:
    """If ``default_name`` names a config that no longer exists, the
    resolution should fall through to ``active`` (and the loader should
    have already cleared the bad pointer at deserialization, but this
    runtime guard is the second line of defence)."""
    s = ConfigurationSet(
        active="dev",
        default_name="ghost",  # not in the list
        configurations=[
            Configuration(name="default"),
            Configuration(name="dev"),
        ],
    )
    # default_config falls back via active_config when find() returns None.
    assert s.default_config().name == "dev"


# ---------------------------------------------------------------------------
# Sidecar serialization round-trip
# ---------------------------------------------------------------------------

def test_default_name_round_trip(tmp_path: Path) -> None:
    s = _make_set(default_name="prod", active="dev")
    d = configs_to_dict(s)
    assert d["default_name"] == "prod"
    s2 = configs_from_dict(d)
    assert s2.default_name == "prod"
    assert s2.active == "dev"


def test_default_name_omitted_when_empty(tmp_path: Path) -> None:
    """Empty default_name should not be emitted in the JSON to keep
    legacy sidecars byte-identical."""
    s = _make_set(default_name="", active="default")
    d = configs_to_dict(s)
    assert "default_name" not in d


def test_legacy_sidecar_loads_with_no_default(tmp_path: Path) -> None:
    """Sidecars predating the default_name field should load fine
    with default_name=''."""
    legacy_doc = {
        "schema_version": 1,
        "active": "default",
        "configurations": [
            {"name": "default", "values": {"a": "1"}},
            {"name": "alt", "values": {"a": "2"}},
        ],
    }
    s = configs_from_dict(legacy_doc)
    assert s.default_name == ""


def test_invalid_default_name_cleared_at_load(tmp_path: Path) -> None:
    """If a sidecar references a default_name that doesn't exist in
    the configs list, the pointer should be cleared at deserialization."""
    bad_doc = {
        "schema_version": 1,
        "active": "default",
        "default_name": "nonexistent",
        "configurations": [
            {"name": "default", "values": {}},
        ],
    }
    s = configs_from_dict(bad_doc)
    assert s.default_name == ""


def test_default_name_persists_through_save_load(tmp_path: Path) -> None:
    """End-to-end: save_configs() + load_configs() preserves
    default_name."""
    tool = ToolDef(
        name="demo",
        executable="/bin/echo",
        argument_template=["{x}"],
        params=[ParamDef(id="x", label="X", default="hello")],
    )
    tool_path = tmp_path / "demo.scriptree"
    save_tool(tool, tool_path)

    cfg_set = _make_set(default_name="prod")
    save_configs(tool_path, cfg_set)

    loaded = load_configs(tool_path)
    assert loaded is not None
    assert loaded.default_name == "prod"


# ---------------------------------------------------------------------------
# Editor "Default" checkbox
# ---------------------------------------------------------------------------

def _make_runner(tmp_path: Path):
    """Build a ToolRunnerView with a saved tool + multi-config sidecar."""
    from scriptree.ui.tool_runner import ToolRunnerView
    tool = ToolDef(
        name="demo",
        executable="/bin/echo",
        argument_template=["{x}"],
        params=[ParamDef(id="x", label="X", default="hello")],
    )
    tool_path = tmp_path / "demo.scriptree"
    save_tool(tool, tool_path)
    save_configs(tool_path, _make_set(default_name="dev", active="default"))
    return ToolRunnerView(tool, file_path=str(tool_path)), str(tool_path)


def test_default_checkbox_present_in_runner(tmp_path: Path) -> None:
    runner, _ = _make_runner(tmp_path)
    assert hasattr(runner, "_cfg_default_check")
    assert runner._cfg_default_check.text() == "Default"


def test_default_checkbox_reflects_loaded_default(tmp_path: Path) -> None:
    """Loading a sidecar with default_name='dev' and switching the
    combo to 'dev' should check the box; switching to 'default'
    (which is NOT the default-named one) should uncheck it."""
    runner, _ = _make_runner(tmp_path)
    # Initially active is "default" (per save) — checkbox unchecked.
    runner._sync_cfg_default_check()
    assert runner._cfg_default_check.isChecked() is False
    # Switch active to "dev" (the default).
    runner._cfg_set.active = "dev"
    runner._active_selection = ("shared", "dev")
    runner._sync_cfg_default_check()
    assert runner._cfg_default_check.isChecked() is True


def test_default_checkbox_toggle_writes_sidecar(tmp_path: Path) -> None:
    """Toggling the checkbox should set ``default_name`` and persist."""
    runner, tool_path = _make_runner(tmp_path)
    runner._active_selection = ("shared", "prod")
    runner._cfg_set.active = "prod"
    # Patch the save to a spy that lets us verify the side effect.
    runner._cfg_default_check.setChecked(True)  # fires _on_cfg_default_toggled
    # Persisted state.
    on_disk = load_configs(tool_path)
    assert on_disk is not None
    assert on_disk.default_name == "prod"


def test_default_checkbox_toggle_off_clears_default(tmp_path: Path) -> None:
    runner, tool_path = _make_runner(tmp_path)
    runner._active_selection = ("shared", "dev")
    runner._cfg_set.active = "dev"
    # The sidecar was saved with default_name='dev'; the checkbox should
    # be checked on sync.
    runner._sync_cfg_default_check()
    assert runner._cfg_default_check.isChecked() is True

    # Uncheck it.
    runner._cfg_default_check.setChecked(False)
    on_disk = load_configs(tool_path)
    assert on_disk is not None
    assert on_disk.default_name == ""


# ---------------------------------------------------------------------------
# StandaloneWindow.from_tool honours default_name
# ---------------------------------------------------------------------------

def test_standalone_picks_default_when_no_config_arg(tmp_path: Path) -> None:
    """When no ``-configuration`` flag is supplied, StandaloneWindow
    should apply ``default_config()`` (the named default, falling back
    to active)."""
    from scriptree.ui.standalone_window import StandaloneWindow

    tool = ToolDef(
        name="demo",
        executable="/bin/echo",
        argument_template=["{x}"],
        params=[ParamDef(id="x", label="X", default="hello")],
    )
    tool_path = tmp_path / "demo.scriptree"
    save_tool(tool, tool_path)
    cfg_set = _make_set(default_name="prod", active="default")
    save_configs(tool_path, cfg_set)

    win = StandaloneWindow.from_tool(tool, file_path=str(tool_path))
    # The runner should now have "prod" applied.
    runner = win._runner
    assert runner._cfg_set.active == "prod"
    win.close()


def test_standalone_falls_back_to_active_when_no_default(tmp_path: Path) -> None:
    from scriptree.ui.standalone_window import StandaloneWindow

    tool = ToolDef(
        name="demo",
        executable="/bin/echo",
        argument_template=["{x}"],
        params=[ParamDef(id="x", label="X", default="hello")],
    )
    tool_path = tmp_path / "demo.scriptree"
    save_tool(tool, tool_path)
    save_configs(tool_path, _make_set(default_name="", active="dev"))

    win = StandaloneWindow.from_tool(tool, file_path=str(tool_path))
    runner = win._runner
    assert runner._cfg_set.active == "dev"
    win.close()
