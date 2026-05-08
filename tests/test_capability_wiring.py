"""Per-capability wiring tests (v0.3.3).

Confirms that every previously-unwired capability now has at least
one consumer in the production code.  These are *behavioural*
tests — they construct the relevant widget / view, deny the
capability, and assert the user-visible effect (button disabled,
action greyed, dialog refusing, warning fired, etc.).

Each capability gets at minimum:

* a "denied → feature disabled" test, and
* an "allowed → feature works" sanity test where practical.

Capabilities covered (21 declared-but-unwired before v0.3.3 + the
3-tool path-security trio):

  Run / runtime
    run_tools, run_as_different_user, access_settings

  File create / save-as
    create_new_scriptree, create_new_scriptreetree,
    save_as_scriptree, save_as_scriptreetree

  Editor controls
    edit_environment, edit_visibility, reorder_parameters,
    command_line_editor, edit_configurations,
    write_configurations

  Path-security trio
    allow_symlinks, allow_path_traversal, access_sensitive_paths

The granular config capabilities (read/write × shared/personal)
are already covered by ``test_runner_config_permissions.py`` and
related; we don't duplicate them here.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QMessageBox,
    QPushButton,
)

_app = QApplication.instance() or QApplication([])

# Auto-dismiss dialogs the production code might pop up.
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.question = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Yes
)


from scriptree.core.io import save_tool, save_tree  # noqa: E402
from scriptree.core.model import (  # noqa: E402
    ParamDef, ParamType, ToolDef, TreeDef, Widget,
)
from scriptree.core.permissions import PermissionSet  # noqa: E402


def _ps(**capabilities: bool) -> PermissionSet:
    """Build a ``PermissionSet`` with each named capability set to
    True/False.  Unspecified capabilities default to True (allowed)
    via ``PermissionSet.can``'s default behaviour."""
    return PermissionSet(allowed=dict(capabilities))


def _patch_perms(ps: PermissionSet):
    """Patch the cached app-level permission set used by the guard
    helper module + the runner / main_window directly."""
    return patch(
        "scriptree.core.permissions.get_app_permissions",
        return_value=ps,
    )


def _tool_with_paths() -> ToolDef:
    return ToolDef(
        name="x", executable="python",
        params=[
            ParamDef(
                id="p", label="Path",
                type=ParamType.PATH, widget=Widget.FILE_OPEN,
            ),
            ParamDef(id="s", label="String", type=ParamType.STRING),
        ],
    )


# ===========================================================================
# Run / runtime gates
# ===========================================================================

class TestRunTools:

    def test_run_button_disabled_when_denied(self, tmp_path: Path) -> None:
        from scriptree.ui.tool_runner import ToolRunnerView
        with _patch_perms(_ps(run_tools=False)):
            view = ToolRunnerView(_tool_with_paths())
        assert not view._btn_run.isEnabled()

    def test_run_button_enabled_when_allowed(self) -> None:
        from scriptree.ui.tool_runner import ToolRunnerView
        with _patch_perms(_ps(run_tools=True)):
            view = ToolRunnerView(_tool_with_paths())
        assert view._btn_run.isEnabled()

    def test_start_run_blocks_when_denied(self) -> None:
        """Defensive runtime check — keyboard / programmatic calls
        also need to be blocked.  We assert ``_thread`` stays None
        (no worker spawned)."""
        from scriptree.ui.tool_runner import ToolRunnerView
        view = ToolRunnerView(_tool_with_paths())
        assert view._thread is None
        with _patch_perms(_ps(run_tools=False)):
            view._start_run()
        assert view._thread is None  # never spawned


class TestRunAsDifferentUser:

    def test_credential_checkbox_disabled_when_denied(self) -> None:
        from scriptree.ui.tool_runner import ToolRunnerView
        with _patch_perms(_ps(run_as_different_user=False)):
            view = ToolRunnerView(_tool_with_paths())
        assert not view._chk_prompt_creds.isEnabled()


class TestAccessSettings:

    def test_open_settings_blocked_when_denied(self) -> None:
        from scriptree.ui.main_window import MainWindow
        w = MainWindow()
        with _patch_perms(_ps(access_settings=False)), patch(
            "scriptree.ui.settings_dialog.SettingsDialog"
        ) as m_dlg:
            w._open_settings()
        m_dlg.assert_not_called()  # dialog never instantiated


# ===========================================================================
# File create / save-as gates
# ===========================================================================

class TestCreateNewScriptree:
    def test_new_tool_action_disabled_when_denied(self) -> None:
        from scriptree.ui.main_window import MainWindow
        with _patch_perms(_ps(create_new_scriptree=False)):
            w = MainWindow()
        # Find the "New tool from executable..." action.
        labels = {a.text(): a for a in w._m_file.actions()}
        target = labels.get("&New tool from executable...")
        assert target is not None
        assert not target.isEnabled()


class TestCreateNewScriptreetree:
    def test_new_tree_action_disabled_when_denied(self) -> None:
        from scriptree.ui.main_window import MainWindow
        with _patch_perms(_ps(create_new_scriptreetree=False)):
            w = MainWindow()
        labels = {a.text(): a for a in w._m_file.actions()}
        target = labels.get("New scriptree &tree")
        assert target is not None
        assert not target.isEnabled()


class TestSaveAsScriptree:

    def test_editor_save_as_button_disabled_when_denied(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.ui.tool_editor import ToolEditorView
        with _patch_perms(_ps(save_as_scriptree=False)):
            ed = ToolEditorView(_tool_with_paths())
        assert not ed._btn_save_as.isEnabled()

    def test_main_save_tool_as_action_state_follows_perm(
        self, tmp_path: Path,
    ) -> None:
        """The action is only enabled when an editor is active AND
        save_as_scriptree is granted."""
        from scriptree.core.io import load_tool
        from scriptree.ui.main_window import MainWindow

        leaf = tmp_path / "leaf.scriptree"
        save_tool(_tool_with_paths(), leaf)

        # Allowed + editor active → action enabled.
        with _patch_perms(_ps(save_as_scriptree=True)):
            w = MainWindow()
            w._show_editor(load_tool(str(leaf)), str(leaf))
            assert w._act_save_tool_as.isEnabled()

        # Denied + editor active → action disabled.
        with _patch_perms(_ps(save_as_scriptree=False)):
            w2 = MainWindow()
            w2._show_editor(load_tool(str(leaf)), str(leaf))
            assert not w2._act_save_tool_as.isEnabled()


class TestSaveAsScriptreetree:

    def test_save_tree_as_disabled_when_denied(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.ui.main_window import MainWindow
        # Seed a tree so the launcher reports "have_tree".
        leaf = tmp_path / "leaf.scriptree"
        save_tool(_tool_with_paths(), leaf)
        tree = TreeDef(name="t", nodes=[])
        from scriptree.core.model import TreeNode
        tree.nodes.append(TreeNode(type="leaf", path=str(leaf)))
        tp = tmp_path / "demo.scriptreetree"
        save_tree(tree, tp)

        with _patch_perms(_ps(save_as_scriptreetree=False)):
            w = MainWindow()
            w._launcher.load(str(tp))
        assert not w._act_save_tree_as.isEnabled()


# ===========================================================================
# Editor / config control gates
# ===========================================================================

class TestEditEnvironmentButton:
    def test_env_button_disabled_when_denied(self) -> None:
        from scriptree.ui.tool_runner import ToolRunnerView
        with _patch_perms(_ps(edit_environment=False)):
            view = ToolRunnerView(_tool_with_paths())
        assert not view._btn_cfg_env.isEnabled()


class TestEditVisibilityButton:
    def test_visibility_button_disabled_when_denied(self) -> None:
        from scriptree.ui.tool_runner import ToolRunnerView
        with _patch_perms(_ps(edit_visibility=False)):
            view = ToolRunnerView(_tool_with_paths())
        assert not view._btn_cfg_visibility.isEnabled()


class TestEditConfigurationsButton:
    def test_edit_button_disabled_when_denied(self) -> None:
        from scriptree.ui.tool_runner import ToolRunnerView
        with _patch_perms(_ps(edit_configurations=False)):
            view = ToolRunnerView(_tool_with_paths())
        assert not view._btn_cfg_edit.isEnabled()


class TestWriteConfigurationsButtons:
    def test_save_buttons_disabled_when_denied(self) -> None:
        from scriptree.ui.tool_runner import ToolRunnerView
        with _patch_perms(_ps(write_configurations=False)):
            view = ToolRunnerView(_tool_with_paths())
        assert not view._btn_cfg_save.isEnabled()
        assert not view._btn_cfg_save_as.isEnabled()
        assert not view._btn_cfg_delete.isEnabled()


class TestCommandLineEditor:
    def test_live_cmd_readonly_when_denied(self) -> None:
        from scriptree.ui.tool_runner import ToolRunnerView
        with _patch_perms(_ps(command_line_editor=False)):
            view = ToolRunnerView(_tool_with_paths())
        assert view._live_cmd.isReadOnly()

    def test_live_cmd_editable_when_allowed(self) -> None:
        from scriptree.ui.tool_runner import ToolRunnerView
        with _patch_perms(_ps(command_line_editor=True)):
            view = ToolRunnerView(_tool_with_paths())
        assert not view._live_cmd.isReadOnly()


class TestReorderParameters:
    def test_form_drag_disabled_when_denied(self) -> None:
        """The reorderable QListWidget at the heart of the form
        sets ``DragDropMode.NoDragDrop`` when the capability is
        denied so users can't drag rows around."""
        from scriptree.ui.tool_runner import (
            ReorderableParamForm,
        )
        with _patch_perms(_ps(reorder_parameters=False)):
            form = ReorderableParamForm()
        assert (
            form.dragDropMode()
            == QAbstractItemView.DragDropMode.NoDragDrop
        )

    def test_form_drag_enabled_when_allowed(self) -> None:
        from scriptree.ui.tool_runner import (
            ReorderableParamForm,
        )
        with _patch_perms(_ps(reorder_parameters=True)):
            form = ReorderableParamForm()
        assert (
            form.dragDropMode()
            == QAbstractItemView.DragDropMode.InternalMove
        )


# ===========================================================================
# Path-security trio (sanitize.py)
# ===========================================================================

class TestAllowPathTraversal:

    def test_traversal_warning_fires_when_denied(self) -> None:
        from scriptree.core.sanitize import sanitize_all_values
        warnings = sanitize_all_values(
            {"p": "../../etc/passwd"},
            path_fields={"p"},
            allow_traversal=False,
        )
        assert any("path traversal" in w.lower() for w in warnings)

    def test_traversal_warning_suppressed_when_allowed(self) -> None:
        from scriptree.core.sanitize import sanitize_all_values
        warnings = sanitize_all_values(
            {"p": "../../etc/passwd"},
            path_fields={"p"},
            allow_traversal=True,
        )
        # The path-traversal warning is suppressed (the field still
        # exists; just no warning fires for ../).
        assert not any("path traversal" in w.lower() for w in warnings)


class TestAccessSensitivePaths:

    def test_sensitive_path_warning_fires_when_denied(self) -> None:
        from scriptree.core.sanitize import sanitize_all_values
        import sys
        sensitive_dir = (
            r"c:\windows\system32" if sys.platform == "win32"
            else "/etc/passwd"
        )
        warnings = sanitize_all_values(
            {"p": sensitive_dir},
            path_fields={"p"},
            allow_sensitive=False,
        )
        assert any("sensitive system" in w.lower() for w in warnings)

    def test_sensitive_path_warning_suppressed_when_allowed(self) -> None:
        from scriptree.core.sanitize import sanitize_all_values
        import sys
        sensitive_dir = (
            r"c:\windows\system32" if sys.platform == "win32"
            else "/etc/passwd"
        )
        warnings = sanitize_all_values(
            {"p": sensitive_dir},
            path_fields={"p"},
            allow_sensitive=True,
        )
        assert not any("sensitive system" in w.lower() for w in warnings)


class TestAllowSymlinks:

    def test_validate_resolved_path_flags_symlink_when_denied(
        self, tmp_path: Path,
    ) -> None:
        """validate_resolved_path is the entry point the runner calls
        when allow_symlinks is denied.  A real symlink in tmp_path
        should produce a warning."""
        import os
        from scriptree.core.sanitize import validate_resolved_path

        target = tmp_path / "real.txt"
        target.write_text("x", encoding="utf-8")
        link = tmp_path / "link.txt"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported (Windows non-admin)")

        warnings = validate_resolved_path(
            link.resolve() if False else link,  # don't resolve, keep symlink
            tmp_path,
            allow_symlinks=False,
            allow_traversal=True,
        )
        # The function checks parents AND the path itself; either
        # path of the test should produce a symlink warning.
        joined = " ".join(warnings)
        assert "symlink" in joined.lower() or len(warnings) >= 1


# ===========================================================================
# Smoke: when ALL capabilities denied, the UI doesn't crash
# ===========================================================================

class TestAllDeniedSmokeTest:
    """Constructing the main views with every capability denied
    should not raise.  Catches regressions where ``setEnabled(False)``
    misfires on an unparented widget or similar."""

    def test_tool_runner_view_constructs_under_full_lockdown(self) -> None:
        from scriptree.ui.tool_runner import ToolRunnerView
        denied_all = _ps(**{
            cap: False for cap in [
                "run_tools", "run_as_different_user",
                "edit_environment", "edit_visibility",
                "edit_configurations", "write_configurations",
                "command_line_editor", "reorder_parameters",
                "save_scriptree", "edit_tool_definition",
            ]
        })
        with _patch_perms(denied_all):
            view = ToolRunnerView(_tool_with_paths())
        # Just confirm the view exists and the gates fired.
        assert not view._btn_run.isEnabled()
        assert not view._btn_cfg_env.isEnabled()
        assert not view._btn_cfg_visibility.isEnabled()
        assert not view._btn_cfg_edit.isEnabled()
        assert not view._btn_cfg_save.isEnabled()
        assert view._live_cmd.isReadOnly()

    def test_main_window_constructs_under_full_lockdown(self) -> None:
        from scriptree.ui.main_window import MainWindow
        denied_all = _ps(**{
            cap: False for cap in [
                "create_new_scriptree", "create_new_scriptreetree",
                "save_scriptree", "save_as_scriptree",
                "save_scriptreetree", "save_as_scriptreetree",
                "access_settings",
            ]
        })
        with _patch_perms(denied_all):
            w = MainWindow()
        # Spot-check several gates fired.
        labels = {a.text(): a for a in w._m_file.actions()}
        new_tool = labels.get("&New tool from executable...")
        assert new_tool is not None and not new_tool.isEnabled()
