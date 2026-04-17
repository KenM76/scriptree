"""UI integration tests for the configurations bar in ToolRunnerView.

Covers the Save / Save As / Delete / Edit flow plus the sidecar file
round-trip. Dialogs are monkeypatched so the tests run headlessly.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox

_app = QApplication.instance() or QApplication([])

from scriptree.core.configs import (  # noqa: E402
    Configuration,
    load_configs,
    sidecar_path,
)
from scriptree.core.io import save_tool  # noqa: E402
from scriptree.core.model import ParamDef, ToolDef  # noqa: E402
from scriptree.ui.tool_runner import (  # noqa: E402
    ConfigurationEditDialog,
    ToolRunnerView,
)


def _tool() -> ToolDef:
    return ToolDef(
        name="demo",
        executable="/bin/echo",
        argument_template=["{name}"],
        params=[ParamDef(id="name", label="Name", default="hello")],
    )


def _saved_tool(tmp_path: Path) -> tuple[ToolDef, str]:
    tool = _tool()
    path = tmp_path / "demo.scriptree"
    save_tool(tool, path)
    return tool, str(path)


def _auto_yes(monkeypatch) -> None:
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )


class TestConfigBarWithoutFilePath:
    def test_buttons_disabled_without_file_path(self) -> None:
        view = ToolRunnerView(_tool())
        assert not view._btn_cfg_save.isEnabled()
        assert not view._btn_cfg_save_as.isEnabled()
        assert not view._btn_cfg_delete.isEnabled()
        assert not view._btn_cfg_edit.isEnabled()
        assert not view._cfg_combo.isEnabled()

    def test_default_set_seeded_from_widget_defaults(self) -> None:
        view = ToolRunnerView(_tool())
        assert len(view._cfg_set.configurations) == 1
        assert view._cfg_set.configurations[0].values == {"name": "hello"}


class TestConfigBarWithFilePath:
    def test_buttons_enabled(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        assert view._btn_cfg_save.isEnabled()
        assert view._btn_cfg_save_as.isEnabled()
        assert view._btn_cfg_edit.isEnabled()
        # Only one config → Delete disabled.
        assert not view._btn_cfg_delete.isEnabled()

    def test_save_writes_sidecar(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        view._widgets["name"].set_value("changed")
        view._cfg_save()
        loaded = load_configs(path)
        assert loaded is not None
        assert loaded.configurations[0].values == {"name": "changed"}

    def test_save_as_creates_new_config(self, tmp_path: Path, monkeypatch) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        monkeypatch.setattr(
            QInputDialog,
            "getText",
            staticmethod(lambda *a, **k: ("verbose", True)),
        )
        view._widgets["name"].set_value("goodbye")
        view._cfg_save_as()
        names = view._cfg_set.names()
        assert "verbose" in names
        assert view._cfg_set.active == "verbose"
        # Now Delete should be enabled (two configs exist).
        assert view._btn_cfg_delete.isEnabled()
        # And the sidecar was persisted.
        loaded = load_configs(path)
        assert loaded is not None
        assert any(c.name == "verbose" for c in loaded.configurations)

    def test_save_as_empty_name_is_noop(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        monkeypatch.setattr(
            QInputDialog,
            "getText",
            staticmethod(lambda *a, **k: ("   ", True)),
        )
        view._cfg_save_as()
        assert view._cfg_set.names() == ["default"]

    def test_save_as_cancel_is_noop(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        monkeypatch.setattr(
            QInputDialog,
            "getText",
            staticmethod(lambda *a, **k: ("", False)),
        )
        view._cfg_save_as()
        assert view._cfg_set.names() == ["default"]

    def test_delete_removes_active(self, tmp_path: Path, monkeypatch) -> None:
        _auto_yes(monkeypatch)
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        # Add a second config so delete is legal.
        view._cfg_set.configurations.append(
            Configuration(name="extra", values={"name": "x"}, extras=[])
        )
        view._cfg_set.active = "extra"
        view._refresh_cfg_combo()
        view._refresh_cfg_buttons()
        view._cfg_delete()
        assert view._cfg_set.names() == ["default"]
        assert view._cfg_set.active == "default"

    def test_delete_blocked_when_only_one(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        assert not view._btn_cfg_delete.isEnabled()
        view._cfg_delete()  # no crash, no change
        assert view._cfg_set.names() == ["default"]

    def test_switching_active_applies_values(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        monkeypatch.setattr(
            QInputDialog,
            "getText",
            staticmethod(lambda *a, **k: ("alt", True)),
        )
        view._widgets["name"].set_value("world")
        view._cfg_save_as()  # creates 'alt' with name=world
        # Flip back to default via combo.
        idx = view._cfg_combo.findText("default")
        view._cfg_combo.setCurrentIndex(idx)
        assert view._widgets["name"].get_value() == "hello"

    def test_sidecar_loaded_on_reopen(self, tmp_path: Path, monkeypatch) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        monkeypatch.setattr(
            QInputDialog,
            "getText",
            staticmethod(lambda *a, **k: ("saved_one", True)),
        )
        view._widgets["name"].set_value("persisted")
        view._cfg_save_as()
        # Simulate reopen.
        view2 = ToolRunnerView(tool, file_path=path)
        assert "saved_one" in view2._cfg_set.names()
        assert view2._cfg_set.active == "saved_one"
        assert view2._widgets["name"].get_value() == "persisted"


class TestConfigurationEditDialog:
    def test_rename_survives_round_trip(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        view._cfg_set.configurations.append(
            Configuration(name="alt", values={"name": "x"}, extras=[])
        )
        dlg = ConfigurationEditDialog(view._cfg_set, view)
        # Rename row 1 (alt -> renamed)
        dlg._list.item(1).setText("renamed")
        result = dlg.result_configurations()
        assert [c.name for c in result] == ["default", "renamed"]
        assert result[1].values == {"name": "x"}  # values preserved

    def test_reorder_survives_round_trip(self, tmp_path: Path) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        view._cfg_set.configurations.append(
            Configuration(name="alt", values={"name": "x"}, extras=[])
        )
        dlg = ConfigurationEditDialog(view._cfg_set, view)
        dlg._list.setCurrentRow(1)
        dlg._move(-1)  # move "alt" up above "default"
        result = dlg.result_configurations()
        assert [c.name for c in result] == ["alt", "default"]

    def test_empty_name_rejected(self, tmp_path: Path, monkeypatch) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        view._cfg_set.configurations.append(
            Configuration(name="alt", values={}, extras=[])
        )
        dlg = ConfigurationEditDialog(view._cfg_set, view)
        dlg._list.item(1).setText("   ")
        warned = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(lambda *a, **k: warned.append(1)),
        )
        dlg._on_accept()
        assert warned  # user was warned
        assert dlg.result() != QDialog.DialogCode.Accepted

    def test_duplicate_name_rejected(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        view._cfg_set.configurations.append(
            Configuration(name="alt", values={}, extras=[])
        )
        dlg = ConfigurationEditDialog(view._cfg_set, view)
        dlg._list.item(1).setText("default")  # collide
        warned = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(lambda *a, **k: warned.append(1)),
        )
        dlg._on_accept()
        assert warned


class TestActiveRoundTrip:
    def test_active_pointer_persisted(self, tmp_path: Path, monkeypatch) -> None:
        tool, path = _saved_tool(tmp_path)
        view = ToolRunnerView(tool, file_path=path)
        monkeypatch.setattr(
            QInputDialog,
            "getText",
            staticmethod(lambda *a, **k: ("b", True)),
        )
        view._cfg_save_as()
        # Sidecar should now have active='b'
        loaded = load_configs(path)
        assert loaded.active == "b"
